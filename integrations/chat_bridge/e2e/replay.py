# -*- coding: utf-8 -*-
"""
Odtwarzanie zapisanych rozmów (audyt produkcji) przeciwko bieżącej
konfiguracji modeli Dębusia Pro — Task 9, harness ewaluacyjny.

Użycie:
    python e2e/replay.py sciezka/do/shard_1.txt [shard_2.txt ...] [--persona pro|olx|allegro]
                                                                    [--out wyniki.json]

Transkrypty NIGDY nie leżą w repo — zawierają dane osobowe klientów (nazwiska,
adresy dostawy, telefony), a repo auto-deployuje się na produkcję. Podaj
ścieżkę bezwzględną poza repo (np. ~/Documents/woodpower-eval-dane/). Testy
tego modułu jeżdżą na SYNTETYCZNYCH fixture'ach w `e2e/dane/` — w pełni
zmyślonych, bez żadnych prawdziwych danych klientów.

Konfiguracja modeli idzie ze zmiennych MODEL_* (patrz bots_pro/models.py) —
porównanie dostawców (OpenAI <-> Anthropic) to uruchomienie TEGO SAMEGO
polecenia z inną wartością, np.:
    MODEL_WYCENA=litellm/anthropic/claude-sonnet-5 \\
    MODEL_WIEDZA=litellm/anthropic/claude-sonnet-5 \\
    MODEL_POSPRZEDAZ=litellm/anthropic/claude-sonnet-5 \\
    MODEL_ROUTER=litellm/anthropic/claude-sonnet-5 \\
    ANTHROPIC_API_KEY=... python e2e/replay.py ...

BEZPIECZEŃSTWO (krytyczne — harness NIE MOŻE pisać do prawdziwego Chatwoota
ani produkcyjnego CRM, ani ich odpytywać siecią). Trzy NIEZALEŻNE miejsca w
kodzie bota importują sieciowe funkcje PRZEZ NAZWĘ (`from X import y`) — ta
konstrukcja WIĄŻE referencję w przestrzeni nazw importującego modułu RAZ, przy
imporcie. Podmiana atrybutu na module ŹRÓDŁOWYM po fakcie (naiwne podejście,
jakie sugerował pierwotny brief tego zadania) nie ma WIĘC żadnego wpływu na
to, co te moduły faktycznie wywołują:

  1. `bots_pro/tura.py`: `from core.chatwoot import cw_agent_reply` — wysyłka
     zwykłej odpowiedzi bota.
  2. `bots_pro/podsumowanie.py`: WŁASNE, OSOBNE `from core.chatwoot import
     cw_agent_reply` — wysyłka deterministycznego podsumowania (Runda
     poprawek 1, K1: pierwsza wersja tego harnessu łatała TYLKO (1), więc
     KAŻDA rozmowa, w której model wołał narzędzie `wyslij_podsumowanie`,
     wysyłała prawdziwą wiadomość do prawdziwego Chatwoota — a treść tej
     wiadomości NIE trafiała do `odpowiedzi`, więc harness jej nawet nie
     mierzył, mierząc tylko ciszę, której nie było).

`odtworz()` niżej podmienia właściwe miejsca — `tura.cw_agent_reply` ORAZ
`podsumowanie.cw_agent_reply` (osobno, bo to DWIE różne referencje), oraz
`tura.Runner`. `stan.handoff`/`stan.wolno_prowadzic_rozmowe` są używane przez
`tura.py` jako atrybuty MODUŁU (`from bots_pro import stan`, potem
`stan.handoff(...)`), więc dla nich wystarcza podmiana atrybutu modułu —
`odtworz()` traktuje wszystkie przypadki jednolicie (`_podmien`).

Druga, NIEZALEŻNA klasa wycieku (Runda poprawek 1, K2): `bots_pro/narzedzia.py`
woła `bots.crm_calc.find_or_create_client`/`.create_quote`/`.update_quote` —
funkcje PISZĄCE do produkcyjnego CRM (nowy klient/nowa wycena/aktualizacja
wyceny). W odróżnieniu od `cw_agent_reply`, te są dostępne przez ATRYBUT
MODUŁU (`from bots import crm_calc`, potem `crm_calc.find_or_create_client(...)`),
więc podmiana działa identycznie jak dla `stan.handoff` — ale bez niej
KAŻDA rozmowa dochodząca do etapu "podaj kontakt"/"zapisz wycenę" zakładałaby
REALNEGO klienta pod `client_number="chat-<900000+id>"` w produkcyjnym CRM.
`crm_calc` ma DWIE rozłączne grupy funkcji: LICZĄCE (`get_options`,
`calculate`, `shipping_quote` — muszą zostać PRAWDZIWE, inaczej inwariant I1
"cena wyłącznie z kalkulatora CRM" byłby zmierzony na atrapie, nie na
prawdziwym systemie) i PISZĄCE (te trzy wyżej — nie mają NIC wspólnego z I1,
tylko tworzą rekordy w produkcji). `odtworz()` przechwytuje WYŁĄCZNIE grupę
piszącą.

Testy `tests/test_replay_odtworz.py::TestZadneWywolanieSieciowe` dowodzą
braku wycieku na WSZYSTKICH tych ścieżkach naraz — flagowy test podmienia
`requests.post`/`.request` (warstwa transportowa, przez którą przechodzą
WSZYSTKIE wywołania sieciowe niezależnie od tego, jak dana funkcja została
zaimportowana) na REJESTRATOR wywołań (NIE atrapę, która rzuca wyjątek —
`cw_agent_reply`/`cw_bot_handoff`/`crm_calc._send` łapią wyjątki z `requests`
WEWNĄTRZ SIEBIE i nigdy same nie rzucają, więc rzucająca atrapa na tym
poziomie zostałaby po cichu połknięta, a test „przeszedłby” NAWET PRZY
REALNYM WYCIEKU — rejestrator, sprawdzany na końcu testu, jest jedynym
niezawodnym sposobem). Patrz też K3 w raporcie zadania: test podmieniający
WYŁĄCZNIE `core.chatwoot.cw_agent_reply` (atrybut modułu źródłowego) jest w
stosunku do (1)/(2) bezzębny — nie dosięga żadnego z nich, niezależnie od
tego, co robi `odtworz()` — i dlatego NIE jest już jedynym testem
bezpieczeństwa w tym module.

Import `bots_pro.tura` (a więc i `agents`) jest LENIWY — dopiero wewnątrz
`odtworz()` — żeby parser transkryptów (`wczytaj_rozmowy`) dawał się używać
(i testować) TAKŻE bez zainstalowanego SDK, ten sam wzorzec co w
tests/test_pro_tura.py.
"""
import contextlib
import json
import os
import re
import sys
import time

_NAGLOWEK_RE = re.compile(r"^ROZMOWA\s*#\s*(\d+)")
_LINIA_RE = re.compile(
    r"^\[[^\]]*\]\s*(KLIENT|BOT|AGENT|NOTATKA-PRYW|SYSTEM):\s*(.*)$")
# Nagłówek bloku metadanych (np. "ZDARZENIA" z listą zdarzeń pod spodem) —
# linia złożona WYŁĄCZNIE z wielkich liter polskiego alfabetu/cyfr/spacji/
# myślnika, bez ani jednej litery małej. Realna proza klienta w tym formacie
# jest pisana normalnie (małymi literami z rzadka Wielką na początku zdania),
# więc taka linia praktycznie na pewno NIE jest treścią wiadomości — patrz
# `_koniec_doklejania` niżej i jej docstring o incydencie, który to wykrył.
_BLOK_METADANYCH_RE = re.compile(r"^[A-ZĄĆĘŁŃÓŚŹŻ0-9][A-ZĄĆĘŁŃÓŚŹŻ0-9 \-/]*$")

# Persony ważne dla silnika Pro (bots_pro) — patrz quote_worker._PERSONY_SILNIKA_PRO
# i webhooks._persona_pro_dla_inboxu. "quote_olx"/"quote_allegro" (z
# bots/channel_caps.py) NALEŻĄ do starego silnika, nie do Debusia Pro — użycie
# ich tutaj dawałoby caps istniejące, ale NIGDY faktycznie produkowane przez
# Pro w produkcji.
PERSONY_PRO = ("pro", "olx", "allegro")

# Woła się raz na proces, nie raz na rozmowę — `agents.set_tracing_disabled`
# jest globalnym przełącznikiem SDK, wywołanie go wielokrotnie jest
# nieszkodliwe, ale bez sensu.
_tracing_wylaczone = False


def _koniec_doklejania(linia):
    """Czy `linia` kończy doklejanie do bieżącej wiadomości — bo wygląda na
    strukturalne metadane transkryptu (nagłówek bloku typu "ZDARZENIA" z
    listą zdarzeń pod spodem, np. zmian statusu/handoffu), nie na dalszy
    ciąg zdania klienta/bota.

    Zgłoszony incydent (Runda poprawek 1, W2): pierwsza wersja doklejała
    KAŻDĄ niepustą, niedopasowaną linię do ostatniej wiadomości — więc blok
    "ZDARZENIA" z wciętymi podpunktami zdarzeń, występujący w realnym
    formacie BEZPOŚREDNIO po linii wiadomości (bez pustej linii oddzielającej),
    trafiał W CAŁOŚCI do treści KLIENTA i szedł do bota jako część jego
    wiadomości. Dwa niezależne sygnały, każdy osobno wystarczający:
      1. linia z WCIĘCIEM (zaczyna się białym znakiem) — realne wiadomości
         klienta/bota w tym formacie nie są wcinane, podpunkty metadanych są;
      2. linia złożona WYŁĄCZNIE z wielkich liter/cyfr/spacji/myślnika, bez
         ani jednej litery małej — nagłówki bloków ("ZDARZENIA"), nie proza.
    Fixture w e2e/dane/ nie zawierał takiego bloku, więc żaden test tego nie
    łapał — dodany osobno w tests/test_replay_kryteria.py, reprodukujący
    dokładnie ten kształt."""
    if linia != linia.lstrip():
        return True  # linia zaczyna się bialym znakiem = wciety podpunkt bloku
    return bool(_BLOK_METADANYCH_RE.match(linia.strip()))


def wczytaj_rozmowy(sciezka):
    """Parsuje plik transkryptu (format audytu produkcji) na listę rozmów:
    [{'id': int, 'wiadomosci': [(kto, tresc), ...]}, ...].

    Nagłówek `ROZMOWA #<id>` zaczyna nową rozmowę — dalszy tekst nagłówka
    (data, inbox...) jest ignorowany, liczy się tylko numer. Wiadomość to
    `[czas] KTO: treść`, KTO w {KLIENT, BOT, AGENT, NOTATKA-PRYW, SYSTEM}.
    UWAGA: „AGENT" w tym formacie to CZŁOWIEK-konsultant z Chatwoota
    (sender.type == "user"), NIE agent wyspecjalizowany Agents SDK (Wycena/
    Wiedza/Posprzedaz z bots_pro/agenci.py) — to dwa różne pojęcia o tej
    samej nazwie, jedno z transkryptu (dane), drugie z architektury bota
    (kod). `odtworz()` niżej korzysta WYŁĄCZNIE z linii KLIENT — reszta jest
    tu i tak sparsowana (nie odrzucana), żeby wywołujący mógł np. policzyć,
    ile razy STARY bot się powtarzał, do porównania z nowym.

    Linie, które nie pasują do żadnego wzorca, dzielą się na trzy rodzaje:
      - puste — nie doklejają się, ale NIE przerywają kontynuacji (akapit
        rozdzielony pustą linią to wciąż JEDNA wiadomość, np. wieloliniowy
        adres dostawy);
      - blok metadanych (wykryty przez `_koniec_doklejania` — linia wcięta
        albo złożona wyłącznie z wielkich liter, patrz jej docstring) —
        PRZERYWA kontynuację i sama nie trafia nigdzie;
      - wszystko inne — DOKLEJANE do OSTATNIO rozpoznanej wiadomości (dalszy
        ciąg zdania klienta/bota złamany na kilka linii)."""
    rozmowy = []
    biezaca = None
    ostatnia = None  # [kto, tresc] — mutowalna referencja do domklejania
    with open(sciezka, encoding="utf-8") as plik:
        for surowa in plik:
            linia = surowa.rstrip("\n\r")
            naglowek = _NAGLOWEK_RE.match(linia)
            if naglowek:
                biezaca = {"id": int(naglowek.group(1)), "wiadomosci": []}
                rozmowy.append(biezaca)
                ostatnia = None
                continue
            if biezaca is None:
                continue  # tekst przed pierwszym naglowkiem — ignorujemy
            trafienie = _LINIA_RE.match(linia)
            if trafienie:
                ostatnia = [trafienie.group(1), trafienie.group(2)]
                biezaca["wiadomosci"].append(ostatnia)
                continue
            if not linia.strip():
                continue  # pusta linia - nie dokleja, ale NIE przerywa kontynuacji
            if _koniec_doklejania(linia):
                ostatnia = None  # naglowek bloku metadanych - koniec doklejania
                continue
            if ostatnia is not None:
                ostatnia[1] = (ostatnia[1] + "\n" + linia).strip()
    for rozmowa in rozmowy:
        rozmowa["wiadomosci"] = [(k, t) for k, t in rozmowa["wiadomosci"]]
    return rozmowy


@contextlib.contextmanager
def _podmien(obiekt, atrybut, nowa_wartosc):
    """Podmienia `obiekt.atrybut` na czas bloku `with`, gwarantując
    przywrócenie oryginału (nawet po wyjątku). Odpowiednik `monkeypatch` z
    pytest — ale `replay.py` działa POZA testami (skrypt CLI), gdzie
    `monkeypatch` nie istnieje."""
    stara_wartosc = getattr(obiekt, atrybut)
    setattr(obiekt, atrybut, nowa_wartosc)
    try:
        yield
    finally:
        setattr(obiekt, atrybut, stara_wartosc)


def _wyczysc_poprzedni_stan(conv_id):
    """Zeruje WSZYSTKO, co harness zostawił po ewentualnym POPRZEDNIM
    przebiegu dla TEGO SAMEGO conv_id (`conv_id_bazowy + rozmowa['id']` jest
    deterministyczny — dwa uruchomienia `replay.py` na tym samym shardzie i
    tym samym DB_PATH liczą się do TEJ SAMEJ rozmowy w bazie).

    Bez tego DRUGI przebieg (typowo: ten sam shard z innym MODEL_* — cały
    sens porównania dwóch dostawców) dziedziczyłby stan z PIERWSZEGO: historię
    sesji SDK (SQLiteSession — model widziałby własne, stare wiadomości jako
    już wypowiedziane), zapisane pozycje/kwoty/podpisy potwierdzenia
    (pro_stan/pro_dane/pro_kwoty). Efekt: druga rozmowa mogłaby np. zobaczyć
    "już potwierdzoną" wycenę z zupełnie INNEGO dostawcy modelu, robiąc
    porównanie bezwartościowym. Czyścimy WYŁĄCZNIE dane TEGO conv_id — inne
    rozmowy w tym samym przebiegu (i ich historia z WCZEŚNIEJSZYCH przebiegów)
    zostają nietknięte."""
    import asyncio

    from agents import SQLiteSession
    from bots_pro.stan import init_pro
    from config import DB_PATH
    from core.db import db

    init_pro()  # gwarantuje istnienie pro_stan/pro_dane/pro_kwoty przed DELETE

    sesja = SQLiteSession(str(conv_id), DB_PATH)
    asyncio.run(sesja.clear_session())

    polaczenie = db()
    try:
        for tabela in ("pro_stan", "pro_dane", "pro_kwoty"):
            polaczenie.execute("DELETE FROM %s WHERE conv_id=?" % tabela, (conv_id,))
        polaczenie.commit()
    finally:
        polaczenie.close()


def odtworz(rozmowa, conv_id_bazowy=900000, persona="pro"):
    """Odtwarza JEDNĄ rozmowę: kolejne wiadomości KLIENTA idą do
    `tura.uruchom()` — prawdziwy Router, prawdziwi agenci wyspecjalizowani,
    prawdziwe narzędzia i prawdziwy kalkulator CRM (LICZENIE, nie zapis —
    patrz niżej), prawdziwe guardraile (I1 integralność ceny/G1, I2
    potwierdzenie klienta) — harness ma te inwarianty MIERZYĆ, nie omijać.

    `persona` (Runda poprawek 1, W3) MUSI odpowiadać kanałowi, z którego
    pochodzi transkrypt — `bots_pro.wysylka.przygotuj` egzekwuje profil
    kanału (np. `links=False` na Allegro), więc odtwarzanie rozmowy z Allegro
    z domyślną personą "pro" mierzyłoby kryterium "ma link" tam, gdzie z
    definicji nie ma prawa wystąpić. Prawidłowe wartości: `PERSONY_PRO` —
    "pro" (live-chat/Messenger), "olx", "allegro" (NIE "quote_olx"/
    "quote_allegro" — te klucze istnieją w bots/channel_caps.py, ale należą
    do STAREGO silnika, Pro nigdy ich nie produkuje, patrz
    quote_worker._PERSONY_SILNIKA_PRO).

    Co jest przechwycone (nigdy nie leci siecią do prawdziwego Chatwoota ani
    nie zakłada rekordów w produkcyjnym CRM) — patrz też akapit
    "BEZPIECZEŃSTWO" w nagłówku modułu, tam jest pełne uzasadnienie KAŻDEGO
    punktu:
      - wysłanie odpowiedzi/podsumowania do klienta (`tura.cw_agent_reply`
        ORAZ `podsumowanie.cw_agent_reply` — DWIE osobne referencje, K1),
      - oddanie rozmowy konsultantowi (`stan.handoff`),
      - odczyt statusu/historii rozmowy — bramka ciszy po handoffie
        (`stan.wolno_prowadzic_rozmowe`) — syntetyczny `conv_id` i tak nie
        odpowiada żadnej realnej rozmowie w Chatwoocie,
      - odczyt „ostatniej wiadomości klienta" do weryfikacji cytatu
        potwierdzenia (`stan.ostatnia_wiadomosc_klienta` — W1: bez tego
        `potwierdzenia.potwierdz` odpytuje PRAWDZIWY Chatwoot o historię
        nieistniejącej rozmowy, dostaje pustkę/błąd i ZAWSZE odmawia
        `CYTAT_SPOZA_WIADOMOSCI` — inwariant I2 nigdy by się nie domknął w
        replayu, a `zawiera_link`/`ma_wyjscie` degenerowałyby się do samego
        handoffu, robiąc porównanie z audytem bezwartościowym),
      - założenie/zaktualizowanie klienta i zapis/aktualizacja wyceny w CRM
        (`crm_calc.find_or_create_client`/`.create_quote`/`.update_quote` —
        K2; `crm_calc.get_options`/`.calculate`/`.shipping_quote` ZOSTAJĄ
        prawdziwe — to one liczą cenę, a I1 ma być zmierzone na PRAWDZIWYM
        kalkulatorze).

    Dwie DODATKOWE rzeczy dzieją się przy każdym wywołaniu (Runda poprawek 1,
    drobne): tracing Agents SDK jest wyłączany raz na proces (transkrypty
    NIE mają wyciekać do zewnętrznego endpointu tracingu tej samej klasy
    powodu, dla którego w ogóle nie wolno ich commitować), i stan tego
    conv_id z EWENTUALNEGO poprzedniego przebiegu jest czyszczony
    (`_wyczysc_poprzedni_stan`) — patrz jej docstring.

    Zwraca dict:
      odpowiedzi      — publiczne odpowiedzi bota, w kolejności (jedna tura
                        klienta może dać 0 lub więcej — zwykle 1, 0 gdy bot
                        milczał/został zablokowany guardrailem bez udanej
                        korekty)
      handoff         — czy w KTÓREJKOLWIEK turze doszło do oddania rozmowy
                        konsultantowi
      trasa           — nazwy agentów SDK (Router/Wycena/Wiedza/Posprzedaz),
                        którzy faktycznie odpowiedzieli — jedna pozycja na
                        KAŻDE wywołanie Runner.run_sync (jedna tura klienta
                        może wywołać go dwa razy, gdy G1 zażąda korekty)
      uzycia          — obiekty Usage z SDK (jeden na wywołanie
                        Runner.run_sync) — surowiec dla
                        `kryteria.koszt_rozmowy`
      czasy_tur       — sekundy na KAŻDĄ wiadomość KLIENTA (jedna tura może
                        zrobić 1-2 wywołania Runnera w środku — to CAŁKOWITY
                        czas tej tury, nie pojedynczego wywołania modelu)
      kwoty_niezgodne — ile razy guardrail G1 złapał w odpowiedzi cenę spoza
                        kalkulatora (licząc też próbę korekty — patrz
                        docstring `tura.uruchom`)
      crm_zapisy_przechwycone — ile razy narzędzie próbowało założyć klienta
                        albo zapisać/zaktualizować wycenę w CRM — informacyjne,
                        dowód że I2/zapis faktycznie były wołane w tej rozmowie
                        (bez tego pola nie dałoby się tego odróżnić od
                        rozmowy, która nigdy tam nie doszła)."""
    if persona not in PERSONY_PRO:
        raise ValueError(
            "replay.odtworz: nieznana persona %r — dozwolone: %s "
            "(NIE 'quote_olx'/'quote_allegro', te naleza do STAREGO silnika)"
            % (persona, PERSONY_PRO))

    global _tracing_wylaczone
    if not _tracing_wylaczone:
        import agents
        agents.set_tracing_disabled(True)
        _tracing_wylaczone = True

    from bots import crm_calc
    from bots_pro import guardraile, podsumowanie, stan, tura

    conv_id = conv_id_bazowy + rozmowa["id"]
    _wyczysc_poprzedni_stan(conv_id)

    odpowiedzi = []
    trasa = []
    uzycia = []
    czasy_tur = []
    zdarzenia_handoff = []
    naruszenia_g1 = []
    wyslane_w_turze = []
    zapisy_crm = []
    biezaca_wiadomosc_klienta = [""]

    def _przechwyc_wyslanie(_conv_id, tekst, image_path=None, image_name=None,
                            image_mime="image/jpeg", token=None):
        wyslane_w_turze.append(tekst)
        return True

    def _przechwyc_handoff(powod):
        zdarzenia_handoff.append(powod)
        return {"ok": True, "powod": powod}

    def _wolno_zawsze(_conv_id):
        # Replay nie ma (i nie powinien mieć) prawdziwej rozmowy w Chatwoocie
        # do odpytania — bot ma w replayu ZAWSZE mówić, tak jak w świeżej
        # rozmowie w statusie 'pending', bez ludzkiego agenta w tle. To NIE
        # jest obchodzenie inwariantów I1/I2 (te żyją niezależnie od tej
        # bramki, w guardraile.py i potwierdzenia.py — nietknięte), tylko
        # usunięcie zależności od stanu zewnętrznego systemu, którego
        # replay z definicji nie posiada.
        return True

    def _ostatnia_wiadomosc_klienta_z_transkryptu():
        # W1: podmienia `stan.ostatnia_wiadomosc_klienta`, która normalnie
        # odpytuje PRAWDZIWY Chatwoot (core.chatwoot.cw_messages) o historię
        # rozmowy, której w replayu nie ma. Zwraca treść wiadomości KLIENTA,
        # którą WŁAŚNIE przetwarza bieżąca tura (patrz pętla niżej) — dokładnie
        # to, co zwróciłby prawdziwy Chatwoot, gdyby ta rozmowa w nim istniała.
        return biezaca_wiadomosc_klienta[0]

    def _stub_find_or_create_client(email, phone, name, client_number=None):
        # K2: odpowiednik POST /api/bot/clients/find-or-create — kontrakt
        # (pola ok/matched/created/client.id/client_name/email/phone)
        # potwierdzony w modules/calculator/routers/bot_api.py::bot_find_or_create_client.
        zapisy_crm.append(("find_or_create_client", email, phone, name, client_number))
        return {"ok": True, "matched": False, "created": True,
                "client": {"id": conv_id, "client_name": name or email or phone
                           or client_number or "Klient replay (nie zapisany)",
                           "email": email, "phone": phone}}

    def _nastepny_edit_uuid():
        return "replay-%s-%s" % (conv_id, len(zapisy_crm) + 1)

    def _stub_create_quote(pozycje, options, client_id, notes=""):
        # K2: odpowiednik POST /api/bot/quotes (bot_create_quote) — kontrakt
        # (ok/quote_number/quote_id/edit_uuid/public_url) jw.
        edit_uuid = _nastepny_edit_uuid()
        zapisy_crm.append(("create_quote", client_id, edit_uuid))
        return {"ok": True, "quote_number": "REPLAY-%s" % conv_id, "quote_id": conv_id,
                "edit_uuid": edit_uuid,
                "public_url": "https://crm.woodpower.pl/quotes/c/%s" % edit_uuid}

    def _stub_update_quote(edit_uuid, pozycje, options, notes="",
                           courier_name=None, shipping_netto=None, shipping_brutto=None):
        # K2: odpowiednik PUT /api/bot/quotes/<edit_uuid> (bot_update_quote).
        zapisy_crm.append(("update_quote", edit_uuid))
        return {"ok": True, "quote_number": "REPLAY-%s" % conv_id, "quote_id": conv_id,
                "edit_uuid": edit_uuid,
                "public_url": "https://crm.woodpower.pl/quotes/c/%s" % edit_uuid}

    oryginalny_runner = tura.Runner

    class _SzpiegRunnera:
        """Deleguje KAŻDE wywołanie do runnera, który faktycznie był
        podpięty pod `tura.Runner` w momencie wejścia do `odtworz()` —
        w produkcyjnym użyciu to prawdziwy `agents.Runner` (import na
        poziomie modułu w tura.py), w testach to, co test podstawił (patrz
        tests/test_replay_odtworz.py) — dzięki temu TEN SAM kod działa i na
        prawdziwym SDK (replay właściwy), i pod atrapą bez sieci/klucza API
        (testy). Po drodze zapisuje `last_agent`/`context_wrapper.usage` do
        metryk trasy/kosztu, których `tura.uruchom()` (funkcja bez wartości
        zwrotnej) nie ujawnia wywołującemu."""

        def run_sync(self, agent, tresc, session=None, max_turns=None):
            wynik = oryginalny_runner.run_sync(
                agent, tresc, session=session, max_turns=max_turns)
            nazwa_agenta = getattr(getattr(wynik, "last_agent", None), "name", None)
            if nazwa_agenta:
                trasa.append(nazwa_agenta)
            uzycie = getattr(getattr(wynik, "context_wrapper", None), "usage", None)
            if uzycie is not None:
                uzycia.append(uzycie)
            return wynik

    oryginalny_sprawdz_ceny = guardraile.sprawdz_ceny

    def _sprawdz_ceny_ze_zliczeniem(tekst, znane_kwoty):
        naruszenia = oryginalny_sprawdz_ceny(tekst, znane_kwoty)
        if naruszenia:
            naruszenia_g1.append(naruszenia)
        return naruszenia

    with contextlib.ExitStack() as podmiany:
        podmiany.enter_context(_podmien(tura, "cw_agent_reply", _przechwyc_wyslanie))
        podmiany.enter_context(_podmien(podsumowanie, "cw_agent_reply", _przechwyc_wyslanie))
        podmiany.enter_context(_podmien(tura, "Runner", _SzpiegRunnera()))
        podmiany.enter_context(_podmien(stan, "handoff", _przechwyc_handoff))
        podmiany.enter_context(_podmien(stan, "wolno_prowadzic_rozmowe", _wolno_zawsze))
        podmiany.enter_context(_podmien(
            stan, "ostatnia_wiadomosc_klienta", _ostatnia_wiadomosc_klienta_z_transkryptu))
        podmiany.enter_context(_podmien(guardraile, "sprawdz_ceny", _sprawdz_ceny_ze_zliczeniem))
        podmiany.enter_context(_podmien(
            crm_calc, "find_or_create_client", _stub_find_or_create_client))
        podmiany.enter_context(_podmien(crm_calc, "create_quote", _stub_create_quote))
        podmiany.enter_context(_podmien(crm_calc, "update_quote", _stub_update_quote))

        stan.ustaw_kontekst(conv_id)
        for kto, tresc in rozmowa["wiadomosci"]:
            if kto != "KLIENT" or not tresc.strip():
                continue
            biezaca_wiadomosc_klienta[0] = tresc
            wyslane_w_turze.clear()
            poczatek = time.monotonic()
            tura.uruchom(conv_id, "replay", tresc, persona=persona)
            czasy_tur.append(time.monotonic() - poczatek)
            odpowiedzi.extend(wyslane_w_turze)

    return {
        "odpowiedzi": odpowiedzi,
        "handoff": bool(zdarzenia_handoff),
        "trasa": trasa,
        "uzycia": uzycia,
        "czasy_tur": czasy_tur,
        "kwoty_niezgodne": len(naruszenia_g1),
        "crm_zapisy_przechwycone": len(zapisy_crm),
    }


def _parsuj_argumenty(argv):
    import argparse

    ap = argparse.ArgumentParser(
        description="Odtwarza zapisane rozmowy audytu przez biezacy silnik Debusia Pro.")
    # nargs="*" (nie "+"): pusta lista ma dac przyjazny komunikat uzycia
    # (patrz main() nizej), nie twardy SystemExit z argparse.
    ap.add_argument("sciezki", nargs="*", help="pliki transkryptow (ROZMOWA #<id>...)")
    ap.add_argument("--persona", default="pro", choices=PERSONY_PRO,
                    help="profil kanalu calego przebiegu (domyslnie 'pro' — "
                         "live-chat/Messenger; 'olx'/'allegro' dla tych kanalow — "
                         "patrz docstring odtworz())")
    ap.add_argument("--out", help="zapisz pelny wynik (lista ocen + bledy) jako JSON")
    ap.add_argument("--cennik-input", type=float, default=None,
                    help="nadpisz stawke za token wejsciowy w kryteria.koszt_rozmowy "
                         "(domyslnie proxy tokenowe, patrz kryteria.CENNIK_DOMYSLNY)")
    ap.add_argument("--cennik-output", type=float, default=None,
                    help="nadpisz stawke za token wyjsciowy (jw.)")
    return ap.parse_args(argv)


def main(argv):
    """Runner CLI: odtwarza wszystkie rozmowy z podanych plików transkryptów,
    drukuje wynik KAŻDEJ i podsumowanie zbiorcze — do numerycznego porównania
    dwóch silników uruchom to polecenie DWA RAZY, z inną wartością MODEL_*
    (bots_pro/models.py) między przebiegami, i porównaj podsumowania (albo
    pliki `--out`, jeśli podane — porównanie liczbowe nie ma polegać na
    diffowaniu wydruku terminala)."""
    from e2e import kryteria

    args = _parsuj_argumenty(argv)
    if not args.sciezki:
        print("Uzycie: python e2e/replay.py sciezka/do/shard_1.txt [shard_2.txt ...] "
              "[--persona pro|olx|allegro] [--out wyniki.json]")
        return

    cennik = None
    if args.cennik_input is not None or args.cennik_output is not None:
        domyslny = kryteria.CENNIK_DOMYSLNY
        cennik = {"input": args.cennik_input if args.cennik_input is not None
                  else domyslny["input"],
                  "output": args.cennik_output if args.cennik_output is not None
                  else domyslny["output"]}

    # `quote_worker.py` (jedyny inny wolajacy tura.uruchom() w produkcji) robi
    # to raz, przy starcie procesu — replay.py jest OSOBNYM procesem/skryptem,
    # wiec musi to zrobic samo. Idempotentne (CREATE TABLE IF NOT EXISTS),
    # bezpieczne wolac przy kazdym uruchomieniu.
    from core.db import init_db
    from bots_pro.stan import init_pro
    init_db()
    init_pro()

    wyniki = []
    bledy = []
    wszystkie_czasy_tur = []
    for sciezka in args.sciezki:
        for rozmowa in wczytaj_rozmowy(sciezka):
            # W5: jedna rozmowa, ktora wywali wyjatek (np. przejsciowy blad
            # sieci/limit dostawcy modelu w polowie ze 117), NIE MA prawa
            # ukrasc wynikow WSZYSTKICH juz odtworzonych rozmow — bez tego
            # jeden RateLimitError na np. 40. rozmowie kasowalby caly
            # przebieg, zmuszajac do odpalania od zera.
            try:
                wynik_odtworzenia = odtworz(rozmowa, persona=args.persona)
            except Exception as e:
                print("   [BLAD] rozmowa #%s: %r" % (rozmowa.get("id"), e))
                bledy.append({"id": rozmowa.get("id"), "blad": repr(e)})
                continue
            wszystkie_czasy_tur.extend(wynik_odtworzenia["czasy_tur"])
            ocena = kryteria.ocen(
                rozmowa, wynik_odtworzenia["odpowiedzi"],
                handoff=wynik_odtworzenia["handoff"],
                kwoty_niezgodne=wynik_odtworzenia["kwoty_niezgodne"],
                trasa=wynik_odtworzenia["trasa"],
                uzycia=wynik_odtworzenia["uzycia"],
                czasy_tur=wynik_odtworzenia["czasy_tur"])
            ocena["powtorki_przyblizone"] = kryteria.powtorzone_formulki_przyblizone(
                wynik_odtworzenia["odpowiedzi"])
            ocena["crm_zapisy_przechwycone"] = wynik_odtworzenia["crm_zapisy_przechwycone"]
            if cennik is not None:
                ocena["koszt"] = kryteria.koszt_rozmowy(wynik_odtworzenia["uzycia"], cennik)
            wyniki.append(ocena)
            print("#%s tur=%s powtorki=%s(~%s) wyjscie=%s handoff=%s kwoty_niezgodne=%s "
                  "trasa=%s koszt=%.2f"
                  % (ocena["id"], ocena["tur"], ocena["powtorki"], ocena["powtorki_przyblizone"],
                     ocena["ma_wyjscie"], ocena["handoff"], ocena["kwoty_niezgodne"],
                     "->".join(ocena["trasa"]) or "-", ocena["koszt"]))

    razem = len(wyniki)
    z_wyjsciem = sum(1 for w in wyniki if w["ma_wyjscie"])
    powtorki = sum(w["powtorki"] for w in wyniki)
    powtorki_przyblizone = sum(w["powtorki_przyblizone"] for w in wyniki)
    kwoty_niezgodne = sum(w["kwoty_niezgodne"] for w in wyniki)
    handoffy = sum(1 for w in wyniki if w["handoff"])
    koszt_calkowity = sum(w["koszt"] for w in wyniki)
    p95 = kryteria.p95_czas(wszystkie_czasy_tur)

    print("\n=== PODSUMOWANIE (%s rozmow odtworzonych, %s z bledem) ===" % (razem, len(bledy)))
    if bledy:
        print("rozmowy z bledem (pominiete w reszcie podsumowania): %s"
              % ", ".join(str(b["id"]) for b in bledy))
    print("z wyjsciem (handoff albo link): %s (%.0f%%)"
          % (z_wyjsciem, 100.0 * z_wyjsciem / razem if razem else 0))
    print("powtorzonych formulek lacznie: %s (dokladnie) / %s (z tolerancja na liczby)"
          % (powtorki, powtorki_przyblizone))
    print("kwot spoza kalkulatora (G1) lacznie: %s" % kwoty_niezgodne)
    print("handoffy na 100 rozmow: %.1f" % kryteria.handoffy_na_100(razem, handoffy))
    print("koszt calkowity (%s): %.2f"
          % ("cennik podany flagami --cennik-*" if cennik is not None
             else "proxy tokenowe, patrz kryteria.CENNIK_DOMYSLNY", koszt_calkowity))
    print("p95 czasu tury: %s" % ("%.2fs" % p95 if p95 is not None else "brak danych"))
    print("trafnosc routingu: NIE liczona automatycznie — realne transkrypty audytu "
          "nie niosa etykiety 'ktory agent SDK POWINIEN odpowiedziec' (surowy tekst "
          "rozmowy, nie oznaczenie routingu). kryteria.trafnosc_routingu() jest gotowa "
          "do uzycia z kazdym zrodlem takich etykiet, gdy powstanie (patrz jej "
          "docstring i tests/test_replay_odtworz.py, gdzie liczona jest na "
          "syntetycznych danych ze znanym oczekiwanym routingiem).")

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump({"wyniki": wyniki, "bledy": bledy}, f, ensure_ascii=False, indent=2)
        print("\nPelny wynik (JSON): %s" % args.out)


if __name__ == "__main__":
    # Uruchomione jako skrypt (`python e2e/replay.py ...`) — Python wtedy
    # wklada na sys.path WYLACZNIE katalog e2e/, nie jego rodzica, przez co
    # `from e2e import kryteria`/`from bots_pro import ...` (wolane wewnatrz
    # main()/odtworz()) by sie nie odnalazly. Dopisujemy katalog nadrzedny
    # (integrations/chat_bridge) — pod pytest ten sam efekt daje sam
    # rootdir, wiec ten fragment jest potrzebny WYLACZNIE do bezposredniego
    # `python e2e/replay.py`, nie do testow.
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    main(sys.argv[1:])
