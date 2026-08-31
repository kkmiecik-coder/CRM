# -*- coding: utf-8 -*-
"""
Guard startowy Dębusia Pro — WSPÓLNY dla obu entrypointów mostka.

Osobny moduł, a nie funkcja w `bridge.py` (B1). Guard musi się wykonać także w
instancji KANDYDATA (`bridge_quote_candidate.py`), a kandydat nie może zrobić
`from bridge import sprawdz_guard_pro`: `bridge.py` na poziomie modułu importuje
rejestr kanałów, wszystkie workery i pollery ORAZ tworzy obiekt Flask —
kandydat dostałby drugą aplikację i połowę produkcyjnego mostka jako efekt
uboczny importu. Ten moduł zależy wyłącznie od `config` i `core.log`.

Dlaczego kandydat bez guarda był groźny: `bridge-candidate.env` z
`BOT_PRO_INBOXES=18` i pustym `BOT_PRO_AGENT_WEBHOOK_TOKEN` zostawiał
`/cand/agent-bot-pro` OTWARTY na dowolny nieautoryzowany POST — weryfikacja
tokenu w `webhooks.py` jest WARUNKOWA (`if BOT_PRO_AGENT_WEBHOOK_TOKEN and
...`). Wstrzyknięty JSON z `conv_id` i `inbox_id` 18 wywoływał PUBLICZNĄ
odpowiedź bota. Na produkcji ten sam błąd kończył się głośnym logiem i
wyłączeniem Pro; u kandydata nie było nawet wpisu w logu.

Guard sprawdza OBA tokeny Pro (B2). Sam `BOT_PRO_AGENT_WEBHOOK_TOKEN` broni
wejścia (kto może wywołać bota), `BOT_PRO_CW_AGENT_TOKEN` broni wyjścia (czyim
imieniem bot się odezwie) — brak tego drugiego nie wywala niczego, tylko po
cichu podstawia cudze tokeny z fallbacków `core/chatwoot.py`.
"""
from config import (BOT_PRO_AGENT_WEBHOOK_TOKEN, BOT_PRO_CW_AGENT_TOKEN, BOT_PRO_INBOXES,
                    BOT_QUOTE_NOTE_PERSONAS, BOT_QUOTE_PERSONAS, CW_OLX_INBOX)
from core.log import log


def _konflikt_olx_pro():
    """Opis konfliktu konfiguracji OLX <-> Debus Pro, albo None gdy go nie ma (U10).

    `BOT_PRO_INBOXES` i `BOT_QUOTE_NOTE_PERSONAS` sa SPRZEZONE, i nic tego nie
    pilnowalo. Poller OLX (`channels/olx.py`, `_enqueue_quote_olx`) ustepuje
    webhookowi WYLACZNIE dzieki warunkowi `if "quote_olx" in
    BOT_QUOTE_NOTE_PERSONAS: return`. Migracja OLX na Pro to naturalny moment,
    w ktorym operator zdejmuje `quote_olx` z tej listy ("OLX juz nie jest w
    trybie notatki") — i wtedy oba tory kolejkuja TE SAMA wiadomosc:

      - poller:  persona="quote_olx", klucz dedupu "olx-<id>"  -> STARY silnik,
      - webhook: persona="olx",       klucz dedupu = mid       -> Debus Pro.

    `quote_seen` ich nie skojarzy (rozne klucze), a `enqueue_quote_turn` przy
    scalaniu zachowuje persone PIERWSZEGO wiersza — o tym, ktory silnik obsluzy
    rozmowe (i czy odpowie PUBLICZNIE, czy notatka), decyduje wyscig.

    Dwie konfiguracje sa bezpieczne i obie akceptujemy: `quote_olx` zostaje w
    trybie notatki (poller ustepuje sam), albo `olx` znika z `BOT_QUOTE_PERSONAS`
    (poller w ogole nie kolejkuje tur). Guard NIE dotyka OLX-a spoza
    `BOT_PRO_INBOXES` — tam zdjecie trybu notatki to normalna konfiguracja
    starego silnika."""
    if not CW_OLX_INBOX:
        return None
    if str(CW_OLX_INBOX).strip() not in BOT_PRO_INBOXES:
        return None
    if "quote_olx" in BOT_QUOTE_NOTE_PERSONAS:
        return None
    if "olx" not in BOT_QUOTE_PERSONAS:
        return None
    return (
        "Inbox OLX (%s) jest w BOT_PRO_INBOXES, ale 'quote_olx' NIE MA w "
        "BOT_QUOTE_NOTE_PERSONAS, a 'olx' jest w BOT_QUOTE_PERSONAS. Poller OLX i "
        "webhook /agent-bot-pro kolejkowalyby wtedy TE SAMA wiadomosc pod roznymi "
        "kluczami dedupu (olx-<id> vs mid Chatwoota) — dedup ich nie skojarzy, a o "
        "tym, ktory silnik obsluzy rozmowe, decydowalby wyscig. Wybierz JEDNO: "
        "dopisz 'quote_olx' do BOT_QUOTE_NOTE_PERSONAS (poller ustepuje webhookowi) "
        "albo usun 'olx' z BOT_QUOTE_PERSONAS (poller nie kolejkuje tur)."
        % CW_OLX_INBOX)


def sprawdz_guard_pro():
    """Guard startowy Debusia Pro. Zwraca True, gdy konfiguracja Pro jest zdrowa;
    przy bledzie WYLACZA Pro (czysci BOT_PRO_INBOXES), glosno loguje i zwraca False.

    Trzy kontrole:
    1. (Task 7) Weryfikacja tokenu webhooka /agent-bot-pro jest WARUNKOWA
       (`if BOT_PRO_AGENT_WEBHOOK_TOKEN and ...` w webhooks.py) — brak tokenu przy
       WLACZONYCH inboksach oznacza, ze endpoint przyjmuje DOWOLNE zadanie bez
       autoryzacji.
    2. (B2) Brak BOT_PRO_CW_AGENT_TOKEN przy wlaczonych inboksach — cala izolacja
       TOZSAMOSCI Debusia Pro stoi na tej jednej zmiennej, a `config.py` czyta ja
       golym `os.environ.get`, bez domyslnej i bez zadnej kontroli.
    3. (U10) Sprzezenie BOT_PRO_INBOXES <-> BOT_QUOTE_NOTE_PERSONAS na OLX —
       patrz `_konflikt_olx_pro`.

    U14b (recenzja koncowa): to NIE JEST juz `SystemExit`. Wadliwa konfiguracja
    dotyczaca WYLACZNIE Pro ubijala CALY kontener mostka — razem ze STARYM
    silnikiem, ktory obsluguje dzis zywy ruch na livechacie, OLX i Allegro, oraz
    z pollerami kanalow, sweeperami i indeksem bazy wiedzy. Proporcja byla zla:
    "Pro nie wstaje" to niedostarczona nowa funkcja, "kontener nie wstaje" to
    awaria produkcji. Wylaczamy wiec dokladnie to, co jest wadliwe.

    Mechanizm wylaczenia to TEN SAM kill-switch, co pusta zmienna srodowiskowa:
    `BOT_PRO_INBOXES` jest JEDNYM obiektem wspoldzielonym przez webhooks.py,
    quote_worker.py i pro_watchdog.py (`from config import ...` wiaze ten sam
    zbior), wiec jego wyczyszczenie odcina Pro we wszystkich trzech naraz —
    webhook odrzuca kazdy inbox, worker kieruje 100% wierszy do starego silnika,
    watchdog wraca natychmiast bez wywolan API.

    Wydzielone z `if __name__ == "__main__":` do osobnej funkcji, zeby dalo sie to
    przetestowac bez uruchamiania calego procesu (watki/app.run), a od B1 — do
    osobnego MODULU, zeby ten sam guard dalo sie wolac takze z entrypointu
    kandydata bez importowania calego `bridge.py`."""
    powody = []
    if not BOT_PRO_AGENT_WEBHOOK_TOKEN and BOT_PRO_INBOXES:
        powody.append(
            "BOT_PRO_INBOXES ustawione, a BOT_PRO_AGENT_WEBHOOK_TOKEN puste — "
            "webhook /agent-bot-pro stalby otworem. Uzupelnij bridge.env.")
    if not BOT_PRO_CW_AGENT_TOKEN and BOT_PRO_INBOXES:
        # Komunikat mowi, CO SIE STANIE, nie tylko "brak tokenu": pusta zmienna nie
        # wywala niczego, tylko przepuszcza `token=None` do wszystkich wywolan Pro,
        # a `core/chatwoot.py` po cichu podstawia CUDZE tokeny w fallbackach. Kazde
        # z tych wywolan konczy sie kodem 200, wiec bez tego guarda jedynym objawem
        # jest odpowiedz do klienta podpisana niewlasciwym botem.
        powody.append(
            "BOT_PRO_INBOXES ustawione, a BOT_PRO_CW_AGENT_TOKEN puste — Debus Pro "
            "odezwalby sie CUDZA tozsamoscia. token=None spada na fallbacki w "
            "core/chatwoot.py: cw_agent_reply -> token live-bota, cw_bot_handoff -> "
            "bot-podpowiadacz, cw_note -> konto admina. Wszystkie trzy zwracaja 200, "
            "wiec klient dostaje odpowiedz podpisana innym botem, a w logach jest "
            "cicho. Uzupelnij bridge.env (access_token z setup/create_agent_bot.py).")
    konflikt = _konflikt_olx_pro()
    if konflikt:
        powody.append(konflikt)
    if not powody:
        return True
    for powod in powody:
        log("GUARD PRO: %s" % powod)
    log("GUARD PRO: WYLACZAM Debusia Pro (BOT_PRO_INBOXES wyczyszczone). Stary silnik "
        "i pozostale watki mostka dzialaja dalej. Popraw bridge.env i zrob recreate.")
    BOT_PRO_INBOXES.clear()
    return False
