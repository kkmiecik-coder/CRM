# -*- coding: utf-8 -*-
"""
Watchdog porzuconej rozmowy.

Rozmowa w statusie 'pending', NA INBOKSIE DEBUSIA PRO, w której ostatnia
wiadomość jest od bota i minął próg ciszy, dostaje automatyczny handoff. Bez
tego lead ginie: bot może pisać wyłącznie przy 'pending', a handoff
(`bots_pro.tura._oddaj_konsultantowi`, guardrail, limity tur — Task 8/B2)
odpala się dziś tylko z jawnej decyzji modelu albo z twardych reguł WEWNĄTRZ
tury, NIGDY z samej bezczynności klienta — rozmowa, w której klient po prostu
przestał pisać, nie ma kto by ją przekazała dalej. Audyt: w jednym shardzie 10
z 24 rozmów kończyło się dokładnie tak — bot ostatni, bez handoffu, bez
właściciela.

UWAGA (luka, świadomy kompromis — inna sprawa niż K1 niżej): ten watchdog
pokrywa WYŁĄCZNIE przypadek "bot mówił ostatni, klient milczy" (patrz
`znajdz_porzucone`, `_BOT_MOWIL_OSTATNI`). Odwrotny przypadek — rozmowa NA
INBOKSIE PRO, w której OSTATNIE SŁOWO MA KLIENT, a bot w ogóle nie
odpowiedział (np. zgubiony webhook) — nie ma dziś właściciela: `sweeper.py`
świadomie pomija inboksy Pro (patrz W5 tam), a ten moduł filtruje po
`last_msg_type` BOTA, więc tego przypadku nie złapie. Na skrzynce testowej to
nie boli (mały ruch, obserwacja ręczna) — ale luka MUSI zostać domknięta,
zanim Pro trafi na żywy inboks marketplace'u (OLX/Allegro).

K1 (code review, runda poprawek 1, KRYTYCZNE): PIERWSZA wersja tego modułu
wołała `cw_pending_conversations()` bez ŻADNEGO filtra inboksu — działała więc
na WSZYSTKICH rozmowach pending w całym koncie, nie tylko na inboksach
Debusia Pro (`BOT_PRO_INBOXES`). Skutek: rozmowy z `/agent-bot-quote` (live
chat starego silnika) świadomie NIE dostają handoffu przy wejściu (inna
ścieżka niż `/agent-bot`), więc siedzą w pending przez całą rozmowę — watchdog
przełączał je po progu ciszy na 'open', a stary silnik (`bots/quotebot.py`:
`if status != "pending": bot milczy`) TRWALE wycisza tam bota poza statusem
'pending'. Każdy klient live chatu wracający po przerwie dłuższej niż próg
ciszy dostawałby ciszę zamiast bota. Naprawa: `znajdz_porzucone` filtruje po
`quote_worker._jest_pro_inbox` — GOTOWY, już istniejący i testowany predykat,
nie własna kopia tej samej logiki (dwie kopie łatwo się rozjeżdżają przy
przyszłej zmianie `BOT_PRO_INBOXES`/person silnika Pro).

Z4 (naprawa notatki handoffowej): oddanie rozmowy przez watchdoga zostawia
DOKŁADNIE TĘ SAMĄ notatkę, co handoff z tury (`bots_pro.notatki.notatka_stanu`)
— z zebranymi pozycjami, dostawą, linkiem do wyceny i ostatnią kwotą pokazaną
klientowi. Wcześniej szło stąd jedno zaszyte zdanie bez żadnej treści, a tą
ścieżką wychodzi znaczna część oddawanych rozmów; konsultantka odtwarzała więc
specyfikację, czytając cały wątek od początku. Warunek konieczny tej naprawy
siedzi w `_notatka_watchdoga`: bez ustawionego conv_id odczyty stanu po cichu
zwracają pustkę, więc notatka pisałaby „Zebrane pozycje: brak" na rozmowie,
która pozycje ma.

Wątek (`watchdog()`) NIE startuje (wraca natychmiast, bez wejścia w pętlę),
gdy `BOT_PRO_INBOXES` jest puste — kill-switch migracji (ten sam mechanizm co
w reszcie mostka) ma obejmować TEŻ ten wątek, nie tylko trasy webhooków.
"""
import time

from bots_pro import notatki, stan
from bots_pro.notatki import kod_notatki_ok
from config import (BOT_PRO_CW_AGENT_TOKEN, BOT_PRO_INBOXES, BOT_PRO_WATCHDOG_INTERVAL,
                    BOT_PRO_WATCHDOG_MINUTES)
from core.chatwoot import cw, cw_bot_handoff, cw_note, cw_pending_conversations
from core.log import log
from quote_worker import _jest_pro_inbox

# Chatwoot niesie last_msg_type PROSTO z pola API "message_type" — to LICZBA
# (0=incoming, 1=outgoing, patrz core/chatwoot.py:_cw_conversations_by_status),
# nie string. Sprawdzamy OBIE postacie — dokladnie ten sam wzorzec obronny co
# w sweeper.py/hot_lead_sweeper.py (`in (0, "incoming")` / `in (1, "outgoing")`),
# zeby watchdog dzialal na PRAWDZIWYM ksztalcie danych z API, nie tylko na
# stringu, ktorego produkcja nigdy nie wysyla.
_BOT_MOWIL_OSTATNI = (1, "outgoing")

# Sender.type Chatwoota dla wiadomosci wyslanych PRZEZ BOTA (w odroznieniu od
# "user" — czlowiek-agent, i "contact" — klient). Ten sam rozklad wartosci,
# ktorego juz uzywa bots_pro.stan.wolno_prowadzic_rozmowe.
_NADAWCA_BOT = "agent_bot"


def znajdz_porzucone(rozmowy, teraz, prog_minut):
    """Identyfikatory rozmów NA INBOKSACH DEBUSIA PRO, w których bot mówił
    ostatni (wg TANIEGO podsumowania z listy rozmów) i minął próg ciszy.

    UWAGA: to WSTĘPNY filtr, bez dodatkowych wywołań API — nie rozróżnia bota
    od człowieka-agenta w polu `last_msg_type` (oba to `message_type=1`/
    outgoing w podsumowaniu listy rozmów). Druga, dokładniejsza weryfikacja
    (`_bot_naprawde_mowil_ostatni`, patrz W5 w docstringu modułu) idzie PO tym
    filtrze, w `watchdog_once` — NIE tutaj, żeby ta funkcja została CZYSTA i
    tania do testowania jednostkowego (bez mockowania sieciowego API
    Chatwoota, tylko listy słowników)."""
    prog = prog_minut * 60
    porzucone = []
    for rozmowa in rozmowy or []:
        if not _jest_pro_inbox(rozmowa.get("inbox_id")):
            continue
        znacznik = rozmowa.get("last_msg_ts")
        if not znacznik:
            continue
        if rozmowa.get("last_msg_type") not in _BOT_MOWIL_OSTATNI:
            continue
        if teraz - znacznik >= prog:
            porzucone.append(rozmowa["id"])
    return porzucone


def _bot_naprawde_mowil_ostatni(conv_id):
    """Weryfikacja DRUGIM źródłem (W5, code review runda poprawek 1):
    `last_msg_type` z `cw_pending_conversations` (message_type=1/outgoing) w
    PODSUMOWANIU listy rozmów obejmuje TAKŻE człowieka-agenta — agent może
    odpisać publicznie w rozmowie na inboksie Pro i świadomie zaparkować ją z
    powrotem w pending (snooze, np. czekając na dokumenty od klienta).
    Watchdog NIE MOŻE kasować tej decyzji.

    Sprawdzamy więc `sender.type` OSTATNIEJ publicznej (nieprywatnej)
    wiadomości PRZEZ `/messages` — TEN SAM kształt API, którego już używa i
    testuje `bots_pro.stan.wolno_prowadzic_rozmowe` (w odróżnieniu od pola
    nadawcy w PODSUMOWANIU listy rozmów z `cw_pending_conversations`, którego
    kształt NIE jest tu zweryfikowany żywym dostępem do API — stąd osobne,
    dodatkowe zapytanie o TEN SAM, już sprawdzony endpoint, zamiast zgadywania
    kształtu podsumowania).

    Zwraca True TYLKO gdy ostatnia publiczna wiadomość jest od bota
    (`sender.type == 'agent_bot'`). Błąd sieci/parsowania -> False (ostrożnie:
    nie oddawaj rozmowy człowiekowi, gdy nie jesteśmy PEWNI, że to bot mówił
    ostatni — false negative tu jest tani, false positive kasuje czyjąś
    decyzję).

    N2 (code review, runda poprawek 2): PIERWSZA wersja przerywała pętlę na
    PIERWSZEJ nieprywatnej pozycji od końca — ale wiadomości SYSTEMOWE
    Chatwoota ("Konwersacja oznaczona jako oczekująca", zmiana przypisania,
    etykiety — `message_type == 2`, "activity") są NIEPRYWATNE i NIE MAJĄ
    `sender`. Gdy taka wiadomość jest ostatnia (a bywa — dokładnie to zdarzenie
    często PRZEŁĄCZA rozmowę z powrotem w 'pending', czyli generuje kandydata
    dla tego watchdoga), pierwsza wersja zwracała False, mimo że bot NAPRAWDĘ
    mówił ostatni przed nią — cichym skutkiem było, że watchdog nic nie robił.
    To NIESPÓJNE z `bots_pro.stan.wolno_prowadzic_rozmowe`, gdzie `activity` jest
    już jawnie inertne (patrz przypadek C w `TestWolnoProwadzicRozmowe`). Poza
    tym `znajdz_porzucone` wyżej czyta `last_msg_type` z
    `last_non_activity_message` (Chatwoot udostępnia to pole właśnie DLATEGO,
    że ostatnia wiadomość bywa systemowa) — więc kandydat był wybierany po
    "ostatniej NIE-systemowej", a weryfikowany tu po "ostatniej DOWOLNEJ": dwa
    niespójne źródła. Naprawa: pomijamy (`continue`, nie `return`) też
    wiadomości bez `sender` ALBO z `message_type == 2` — dwa niezależne
    warunki, bo Chatwoot nie zawsze ustawia je spójnie w każdej wersji API."""
    try:
        odpowiedz = cw("GET", "/conversations/%s/messages" % conv_id)
        if not odpowiedz.ok:
            return False
        wiadomosci = odpowiedz.json().get("payload", [])
    except Exception:
        return False
    for wiadomosc in reversed(wiadomosci or []):
        if wiadomosc.get("private"):
            continue
        nadawca = wiadomosc.get("sender")
        if wiadomosc.get("message_type") == 2 or not nadawca:
            continue   # N2: wiadomosc systemowa (activity) - nie liczy sie jako "kto mowil ostatni"
        return nadawca.get("type") == _NADAWCA_BOT
    return False


def _minuty_ciszy(znacznik, teraz):
    """Ile pełnych minut klient milczy — albo None, gdy nie wiadomo.

    Liczymy z tego samego `last_msg_ts`, po którym `znajdz_porzucone` wybrało
    kandydata, żeby liczba w notatce zgadzała się z decyzją, która ją
    wywołała."""
    if not znacznik:
        return None
    return max(0, int((teraz - znacznik) // 60))


def _powod_watchdoga(minuty):
    """Powód do notatki: mówi WPROST, na czym rozmowa stanęła i JAK DAWNO.

    Sama liczba minut jest tu treścią, nie ozdobą: konsultant przejmujący
    rozmowę widzi w Chatwoocie tylko godzinę notatki, a nie to, czy klient
    zamilkł chwilę wcześniej, czy pół dnia temu — a od tego zależy, czy warto
    jeszcze pisać.

    Świadomie NIE rozróżniamy „cisza PO podsumowaniu z ceną" od „cisza po
    zwykłym pytaniu bota", choć kolumna `oczekiwany_podpis` by na to pozwoliła.
    Ta kolumna przeżywa JAWNĄ ODMOWĘ klienta (jeden pisarz, zero miejsc
    czyszczących — patrz komentarz w `notatki.tresc_dla_agenta`), więc powód
    zbudowany na niej sugerowałby „brakuje już tylko jego »tak«" także tam,
    gdzie klient właśnie zgłosił, że zestawienie jest błędne."""
    if minuty is None:
        return ("brak odpowiedzi klienta ponad próg %s min od ostatniej wiadomości bota "
                "— rozmowa oddana automatycznie (watchdog)" % BOT_PRO_WATCHDOG_MINUTES)
    return ("brak odpowiedzi klienta od %s min (ostatni mówił bot) — rozmowa oddana "
            "automatycznie (watchdog)" % minuty)


def _notatka_watchdoga(conv_id, minuty):
    """Notatka po automatycznym oddaniu rozmowy — TA SAMA treść, którą dostaje
    konsultant przy handoffie z tury (`notatki.notatka_stanu`).

    DLACZEGO to jest naprawa, a nie kosmetyka: watchdog wysyłał dotąd jedno
    zaszyte zdanie, bez pozycji, bez kwoty i bez czasu ciszy — a jest to
    ścieżka, którą wychodzi ok. 40% oddawanych rozmów. Konsultantka
    odtwarzała więc specyfikację, czytając wątek od początku (zmierzone czasy
    reakcji po przekazaniu: 39 min, 46 min, 1 h 27, 1 h 45, 3 h 56, 12 h).

    `stan.ustaw_kontekst_odczytu` jest tu WARUNKIEM KONIECZNYM, nie
    formalnością: odczyty stanu biorą conv_id z contextvara i NIE wołają
    `_wymagany_conv_id` (świadomie — przy odczycie brak conv_id jest
    nieszkodliwy, przy zapisie uszkadza cudzy wiersz). Bez tej linii
    `stan.pozycje()` zwróciłoby po cichu pustą listę i notatka napisałaby
    „Zebrane pozycje: brak" na rozmowie, która pozycje MA — czyli zamieniłaby
    dzisiejszy widoczny brak w niewidoczne kłamstwo. Używamy wersji ZAWĘŻONEJ,
    a nie pełnego `ustaw_kontekst`: powody przy `stan.ustaw_kontekst_odczytu`.

    Porażka notatki NIE cofa handoffu, który się udał (ta sama zasada, co
    przed tą zmianą) — zostaje log i notatka AWARYJNA, czyli dawne gołe
    zdanie. Uboga notatka jest lepsza niż żadna przy rozmowie, która już leży
    u człowieka."""
    powod = _powod_watchdoga(minuty)
    try:
        stan.ustaw_kontekst_odczytu(conv_id)
        # poza_tura=True: bramka N7 („jedna notatka na turę") liczy TURY bota, a
        # watchdog działa właśnie wtedy, gdy żadna nie trwa; flagi turowe
        # ostatniej tury tej rozmowy nadal wiszą w pamięci procesu i bez tego
        # zjadłyby notatkę po cichu.
        if notatki.notatka_stanu(conv_id, powod, poza_tura=True):
            return True
        log("watchdog: notatka stanu NIEUDANA (conv %s) -> notatka awaryjna" % conv_id)
    except Exception as e:
        log("watchdog: notatka stanu wywrocila sie (conv %s): %r -> notatka awaryjna"
            % (conv_id, e))
    try:
        odpowiedz = cw_note(conv_id, "⏱️ Watchdog: %s" % powod, token=BOT_PRO_CW_AGENT_TOKEN)
        if not kod_notatki_ok(odpowiedz):
            log("watchdog: notatka ODRZUCONA przez Chatwoota (conv %s, HTTP %s) — "
                "sprawdz BOT_PRO_CW_AGENT_TOKEN"
                % (conv_id, getattr(odpowiedz, "status_code", "?")))
            return False
    except Exception as e:
        log("watchdog: notatka NIEUDANA (conv %s): %r" % (conv_id, e))
        return False
    return True


def watchdog_once(teraz):
    """Jedno przejście watchdoga. Zwraca liczbę rozmów oddanych konsultantowi."""
    oddane = 0
    rozmowy = cw_pending_conversations()
    # Znaczniki czasu z TEGO SAMEGO pobrania, po ktorym wybieramy kandydatow —
    # `znajdz_porzucone` zwraca same identyfikatory (i ma taka zostac: jest
    # czysta i tania do testowania), a notatka potrzebuje jeszcze czasu ciszy.
    # Drugie zapytanie do API dawaloby inna chwile pomiaru niz decyzja.
    znaczniki = {r.get("id"): r.get("last_msg_ts") for r in (rozmowy or [])}
    for conv_id in znajdz_porzucone(rozmowy, teraz, BOT_PRO_WATCHDOG_MINUTES):
        if not _bot_naprawde_mowil_ostatni(conv_id):
            log("watchdog: rozmowa %s wyglada na porzucona, ale ostatnia publiczna "
                "wiadomosc jest od czlowieka -> pomijam" % conv_id)
            continue
        # W4 (code review, runda poprawek 1): token JAWNIE Pro — domyslny cw_bot_handoff
        # siegalby po token bota-podpowiadacza (BOT_CW_AGENT_TOKEN), zly dla inboksow Pro
        # (ten sam powod co w bots_pro.stan.handoff).
        if cw_bot_handoff(conv_id, token=BOT_PRO_CW_AGENT_TOKEN):
            oddane += 1
            log("watchdog: rozmowa %s porzucona przez bota -> konsultant" % conv_id)
            # W2: kod HTTP notatki jest SPRAWDZANY (bledny albo wygasly
            # BOT_PRO_CW_AGENT_TOKEN daje 401, a wtedy handoff juz sie odbyl inna
            # sciezka i konsultant nie wie, DLACZEGO dostal rozmowe) — dzis w
            # `_notatka_watchdoga`, razem z reszta skladania notatki. Porazka
            # notatki NIE cofa handoffu, ktory sie udal: tylko log, bez zmiany
            # licznika.
            _notatka_watchdoga(conv_id, _minuty_ciszy(znaczniki.get(conv_id), teraz))
        else:
            # W4: log NIEUDANEGO handoffu byl wczesniej TYLKO w galezi sukcesu — czesc
            # inboksow moglaby po cichu nie dzialac bez sladu w logach.
            log("watchdog: handoff NIEUDANY (conv %s)" % conv_id)
    return oddane


def watchdog():
    """Wątek tła: co `BOT_PRO_WATCHDOG_INTERVAL` sekund oddaje porzucone
    rozmowy konsultantowi. NIE startuje (wraca natychmiast, zero wywołań API),
    gdy `BOT_PRO_INBOXES` jest puste (K1 — kill-switch migracji) albo
    `BOT_PRO_WATCHDOG_MINUTES <= 0` (wyłącznik — <=0 ma WYŁĄCZAĆ, nie dawać
    natychmiastowy handoff wszystkiego, ten sam wzorzec co
    `sweeper.py`/`hot_lead_sweeper.py`)."""
    if not BOT_PRO_INBOXES:
        log("watchdog: wylaczony (BOT_PRO_INBOXES puste)")
        return
    if BOT_PRO_WATCHDOG_MINUTES <= 0:
        log("watchdog: wylaczony (BOT_PRO_WATCHDOG_MINUTES<=0)")
        return
    # DDL Debusia Pro RAZ, przed petla — ten sam wzorzec co w `quote_worker`.
    # Watchdog czyta teraz `pro_dane`/`pro_stan` przy skladaniu notatki, a
    # bridge.py startuje oba watki rownolegle: bez tego pierwsze przejscie
    # mogloby trafic na jeszcze nieutworzone tabele i oddac rozmowe z uboga
    # notatka awaryjna. Wywolanie jest idempotentne (CREATE/ALTER IF NOT EXISTS).
    try:
        stan.init_pro()
    except Exception as e:
        log("watchdog: init_pro nieudany: %r" % e)
    while True:
        try:
            watchdog_once(time.time())
        except Exception as e:
            log("watchdog ERROR:", repr(e))
        time.sleep(BOT_PRO_WATCHDOG_INTERVAL)
