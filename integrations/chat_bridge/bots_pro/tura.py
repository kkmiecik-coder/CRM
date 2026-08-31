# -*- coding: utf-8 -*-
"""
Jedna tura Dębusia Pro: pętla agentów -> guardrail -> wysyłka.

Rozstrzygnięcie ślepej uliczki między agentami (Task 6): agenci wyspecjalizowani
(Wycena/Wiedza/Posprzedaz, bots_pro/agenci.py) domyślnie NIE MAJĄ własnych
handoffs — tylko Router ma handoffs=[Wycena, Wiedza, Posprzedaz]. Bez dodatkowego
mechanizmu rozmowa, która trafiła np. do agenta Wiedzy, nie miałaby jak dotrzeć do
agenta Wyceny w TEJ SAMEJ turze.

Rozwiązanie: KAŻDA tura wchodzi przez Router OD NOWA (`zbuduj_router()` wołane tu, przy
każdym `uruchom()`), a historia rozmowy (w tym to, który agent i co odpowiedział
poprzednio) leci przez `SQLiteSession`. Scenariusz „najpierw pytam o materiał (Wiedza),
potem chcę cenę (Wycena)" działa więc MIĘDZY turami: turn 1 -> Router -> Wiedza,
turn 2 -> Router (świeży, ale widzi historię z sesji) -> Wycena. Koszt: jedno
dodatkowe wywołanie routera na turę, w zamian za prostotę (bez N*(N-1) ręcznie
utrzymywanych handoffów między agentami wyspecjalizowanymi) i bez ryzyka, że agent
wyceny zacznie odpowiadać na pytania o wiedzę (i odwrotnie) tylko dlatego, że ma do
niego handoff pod ręką. Patrz test_pro_tura.py::TestScenariuszMaterialPotemCena.

WYJĄTEK (Task 8, B4): Wiedza dostała WŁASNY handoff DO Wyceny (patrz docstring
agenci.py) — jedyne odstępstwo od reguły wyżej, świadome i wąskie (Wiedza -> Wycena,
nie odwrotnie, nie Posprzedaż). Droga MIĘDZY turami opisana wyżej nadal działa i
nadal jest GŁÓWNYM mechanizmem (Router wchodzi od nowa co turę) — handoff Wiedzy
dokłada dodatkowo drogę WEWNĄTRZ jednej tury, dla pytania łączącego wiedzę i cenę
w JEDNEJ wiadomości. Patrz test_pro_tura.py::TestHandoffWiedzaDoWyceny.

Guardrail wyjściowy G1 (integralność ceny, bots_pro/guardraile.py) jest WYJŚCIOWY
celowo — łapie odpowiedź niezależnie od tego, KTÓRY agent ją wyprodukował (przy
handoffach guardraile WEJŚCIOWE Agents SDK działają tylko na pierwszym agencie,
nie na tym, do którego nastąpiło przekazanie — G1 musiałby więc być podpięty do
każdego agenta z osobna i tak i tak by nie widział wyniku PO handoffie w tej samej
turze). Sprawdzamy więc `wynik.final_output` PO całym Runner.run_sync, raz — i PONOWNIE
po ewentualnej korekcie (runda poprawek 1, W1): pusta LUB nadal błędna odpowiedź na
korektę kończy turę handoffem, nie ciszą — guardrail, który wykrył problem, ale przy
drugiej próbie milczy, jest z punktu widzenia klienta nieodróżnialny od braku odpowiedzi.

Komunikat korekty idzie do modelu z rolą "system", NIE jako goły string (runda poprawek 1,
W2). Goły string trafiłby do `SQLiteSession` jako wiadomość roli "user" — trwale, na stałe
w historii rozmowy — co ma dwa efekty uboczne: (a) model mógłby tę wewnętrzną instrukcję
sparafrazować klientowi, myląc ją z prawdziwym pytaniem; (c) odpowiedź NA tę wiadomość
i tak przechodzi przez tę samą pętlę Runnera co zwykła tura, więc leci do klienta bez
żadnej dodatkowej kontroli poza G1. Rola "system" zamyka oba te przypadki bez zmiany
architektury (Runner.run_sync przyjmuje listę pozycji wejściowych, nie tylko string).
Trzeci efekt (b) — korekta nadal wchodzi przez Router, który teoretycznie mógłby
przekazać ją do Wiedzy/Posprzedaży, agentów bez narzędzi policz_wycene/policz_wysylke —
jest dziś CZĘŚCIOWO domknięty (Task 8, B4): Wiedza ma własny handoff do Wyceny, więc
jeśli Router odeśle korektę do Wiedzy, ta może przekazać ją DALEJ do Wyceny w TEJ SAMEJ
turze zamiast utknąć bez narzędzi cenowych. To NIE jest twarda gwarancja (model musi
sam rozpoznać, że potrzebuje Wyceny — patrz prompty.WIEDZA) — pełne zamknięcie
wymagałoby ominięcia Routera (np. retry na `wynik.last_agent`), co świadomie
pozostaje odłożone jako zmiana architektury, a nie tylko formatu wiadomości.
Posprzedaż NIE dostała analogicznego handoffu (patrz uzasadnienie w agenci.py) —
dla niej luka (b) zostaje.

Guardrail NIE jest dublowany: bramki narzędzi (potwierdzenie klienta I2, integralność
ceny przy zapisie) mieszkają w bots_pro.potwierdzenia/.narzedzia — ten moduł dokłada
wyłącznie kontrolę WYJŚCIOWĄ (I1), której z definicji nie da się umieścić w narzędziu
(narzędzie nie widzi ostatecznego tekstu odpowiedzi modelu).

`podsumowanie.wyslij()` (wołane przez narzędzie `wyslij_podsumowanie`) SAM wysyła do
klienta deterministyczną treść i oznacza to w `stan.oznacz_podsumowanie_wyslane()`
(runda poprawek 1, W3). Wskazówka zwracana modelowi („zostaw final_output puste") to
tylko PROŚBA w prompcie, nie bramka — model może ją zignorować i dopisać własnymi
słowami sparafrazowane podsumowanie (włącznie z ceną, którą G1 by przepuścił, bo to
ta sama, prawdziwa kwota z rejestru). `stan.podsumowanie_wyslane()` niżej jest tą
bramką: gdy prawdziwa, tura NIE wysyła niczego więcej, niezależnie od treści
`final_output`.
"""
from agents import Runner
from agents import SessionSettings, SQLiteSession

from config import (BOT_PRO_CW_AGENT_TOKEN, BOT_PRO_MAX_BEZ_POSTEPU, BOT_PRO_MAX_RUNNER_STEPS,
                    BOT_PRO_MAX_TURNS, BOT_PRO_SESSION_ITEMS_LIMIT, DB_PATH)
from bots_pro import guardraile, stan, wysylka
from bots_pro.agenci import zbuduj_router
from core.chatwoot import cw_agent_reply
from core.log import log

# Rola "system" (nie goły string / rola "user") - patrz akapit o W2 w docstringu modułu.
_KOMUNIKAT_KOREKTY = [{
    "role": "system",
    "content": (
        "Podałeś kwotę, której nie ma w wyniku kalkulatora. Napisz odpowiedź jeszcze raz, "
        "używając wyłącznie kwot zwróconych przez narzędzie policz_wycene albo policz_wysylke."
    ),
}]


def _sesja(conv_id):
    """SQLiteSession z rdzenia `agents`, NIE SQLAlchemySession — ta ostatnia importuje
    `Select` z sqlalchemy, co istnieje dopiero w 2.0, a projekt ma twarde ograniczenie
    `<2.0` (requirements.txt). SQLiteSession pisze do tego samego pliku co reszta
    mostka (DB_PATH), więc nie dokłada żadnej nowej zależności/pliku.

    `session_settings=SessionSettings(limit=...)` (Task 8, B5): bez tego
    `SQLiteSession.get_items()` zwraca CAŁĄ historię sesji — `Runner.run_sync`
    woła `session.get_items()` bez jawnego limitu (patrz
    `agents.run_internal.session_persistence._session_get_items`), więc de facto
    dziedziczy limit z `session_settings` samej sesji. Efekt bez tego: Router
    płaci (w tokenach i czasie) coraz dłuższą historię na KAŻDĄ turę, rosnącą
    liniowo z długością rozmowy — koszt/opóźnienie, nie poprawność (stary silnik
    miał analogiczne okno, `BOT_HISTORY_LIMIT`, ale liczone w WIADOMOŚCIACH
    czatu — tu limit jest w ITEMS SDK, więc to CELOWO osobna stała,
    `BOT_PRO_SESSION_ITEMS_LIMIT`, patrz jej komentarz w config.py)."""
    return SQLiteSession(str(conv_id), DB_PATH,
                         session_settings=SessionSettings(limit=BOT_PRO_SESSION_ITEMS_LIMIT))


def _oddaj_konsultantowi(powod, conv_id):
    """`stan.handoff` zwraca {"ok": False, ...} przy nieudanej wysyłce do Chatwoota —
    bez logu ten stan wygląda z zewnątrz identycznie jak udany handoff (runda poprawek 1,
    drobne). Nie rzucamy wyjątku — brak handoffu nie ma dobrej ścieżki odzysku w tej
    turze, ale ma być WIDOCZNY w logach, nie cichy."""
    wynik = stan.handoff(powod)
    if not wynik.get("ok"):
        log("tura: handoff do konsultanta NIEUDANY, powod=%r (conv %s)" % (powod, conv_id))
    return wynik


def uruchom(conv_id, inbox_id, tresc, zalaczniki=None, persona="pro"):
    """Przeprowadza jedną turę i wysyła odpowiedź do klienta.

    `persona` MUSI trafić do `stan.ustaw_kontekst` (nie tylko zostać lokalnym
    parametrem) — `podsumowanie.wyslij()`, wołane jako narzędzie WEWNĄTRZ tej tury,
    czyta profil kanału przez `stan.persona()`, nie przez argument. Bez tego
    podsumowanie na Allegro wysyłałoby się z domyślnym profilem 'pro' (markdown,
    emoji, linki) zamiast z ALLEGRO_CAPS — dokładnie ten wyciek, przed którym
    ma chronić `wysylka.py` (link do wyceny w treści zabronionej regulaminem
    marketplace'u).

    Bramka ciszy po handoffie (Task 7): jeśli `stan.wolno_prowadzic_rozmowe(conv_id)`
    zwróci False (rozmowa nie jest w statusie "pending", albo w jej publicznej
    historii pojawiła się już wypowiedź człowieka-agenta), tura kończy się
    NATYCHMIAST — bez wołania Routera/LLM i bez żadnej wysyłki. Sprawdzana jest
    PRZED `ustaw_kontekst`, bo cała reszta funkcji jest bez sensu, gdy bot ma
    milczeć (patrz docstring `bots_pro.stan.wolno_prowadzic_rozmowe` — tam jest
    pełne uzasadnienie i opis incydentu, który ta bramka ma uniemożliwić).

    Błąd odczytu statusu/historii NIE jest tu łapany — `wolno_prowadzic_rozmowe`
    rzuca wtedy `stan.BladOdczytuStanu` (`.retryable = True`), która świadomie
    PRZEPUSZCZA się przez `uruchom()` aż do `quote_worker.process_one` (W3 code
    review): błąd sieciowy ma skończyć się retry z backoffem, nie cichym
    zaznaczeniem wiersza kolejki jako 'sent' bez faktycznej odpowiedzi.

    `stan.init_pro()` (DDL, CREATE TABLE IF NOT EXISTS) NIE jest już wołane tutaj —
    przeniesione do startu `quote_worker.py` (jedynego miejsca, które faktycznie
    woła `uruchom()` w produkcji), zgodnie z tym samym wzorcem co `init_db()` tamże.
    Odpalanie DDL przy KAŻDEJ turze było niepotrzebnym kosztem bez korzyści — tabele
    już istnieją po pierwszym starcie procesu.

    Dwa bezpieczniki kończące PORZUCONĄ/ZAPĘTLONĄ rozmowę (Task 8, B2 — audyt: stary
    limit 30 tur, dziś BOT_PRO_MAX_RUNNER_STEPS, nie uratował ANI JEDNEJ z 10
    zapętlonych rozmów w zbadanym shardzie, klienci odpadali przy 10-28 turach):
    1. `BOT_PRO_MAX_TURNS` — licznik TUR CAŁEJ ROZMOWY (`stan.zarejestruj_ture`).
       Sprawdzany PRZED wywołaniem Routera/LLM — rozmowa, która już przekroczyła
       budżet, nie dostaje kolejnej (kosztownej) próbki modelu, od razu handoff.
    2. `BOT_PRO_MAX_BEZ_POSTEPU` — licznik KOLEJNYCH tur BEZ ŻADNEJ zmiany stanu
       biznesowego (`stan.migawka_postepu` przed/po turze — patrz jej docstring).
       Mierzalny dopiero PO turze, więc odpowiedź z TEJ (n-tej bez postępu) tury
       nadal idzie do klienta jak zwykle — bezpiecznik dokłada handoff PO wysyłce,
       nie zamiast niej."""
    if not stan.wolno_prowadzic_rozmowe(conv_id):
        log("tura: bot milczy (rozmowa nie w pending albo ostatnio pisal czlowiek) "
            "(conv %s)" % conv_id)
        return

    stan.ustaw_kontekst(conv_id, persona_tury=persona)

    if stan.zarejestruj_ture() > BOT_PRO_MAX_TURNS:
        log("tura: limit %s tur rozmowy przekroczony -> handoff (conv %s)"
            % (BOT_PRO_MAX_TURNS, conv_id))
        _oddaj_konsultantowi("limit dlugosci rozmowy (ponad %s tur)" % BOT_PRO_MAX_TURNS, conv_id)
        return

    migawka_przed = stan.migawka_postepu()

    wynik = Runner.run_sync(
        zbuduj_router(), tresc, session=_sesja(conv_id), max_turns=BOT_PRO_MAX_RUNNER_STEPS)
    odpowiedz = (wynik.final_output or "").strip()

    if odpowiedz:
        # Guardrail G1: kwota spoza kalkulatora nie opuszcza procesu (inwariant I1).
        naruszenia = guardraile.sprawdz_ceny(odpowiedz, stan.znane_kwoty())
        if naruszenia:
            log("guardrail G1: kwoty spoza kalkulatora %s (conv %s)" % (naruszenia, conv_id))
            wynik = Runner.run_sync(zbuduj_router(), _KOMUNIKAT_KOREKTY,
                                    session=_sesja(conv_id), max_turns=BOT_PRO_MAX_RUNNER_STEPS)
            odpowiedz = (wynik.final_output or "").strip()
            # W1: pusta odpowiedź na korektę liczy się jak naruszenie — model NIE
            # naprawił ceny, więc i tak nie mamy czego bezpiecznie wysłać. Bez tego
            # `sprawdz_ceny("")` zwróciłoby [] (brak kwot w pustym tekście = brak
            # naruszeń), pętla zeszłaby do wysyłki, `wysylka.przygotuj("")` wysłałaby
            # zero wiadomości, a klient zostałby BEZ odpowiedzi i BEZ handoffu.
            if not odpowiedz or guardraile.sprawdz_ceny(odpowiedz, stan.znane_kwoty()):
                log("guardrail G1: druga proba tez z naruszeniem -> handoff (conv %s)" % conv_id)
                _oddaj_konsultantowi(
                    "guardrail ceny — dwie próby z kwotą spoza kalkulatora", conv_id)
                return

    # W3: podsumowanie.wyslij() (wolane jako narzedzie, w KTORYMKOLWIEK z powyzszych
    # wywolan Runnera) moglo juz samo wyslac deterministyczna tresc - wtedy NIC wiecej
    # w tej turze nie wysylamy, nawet gdy final_output jest niepusty i przeszedl G1.
    if not stan.podsumowanie_wyslane() and odpowiedz:
        for czesc in wysylka.przygotuj(odpowiedz, persona):
            if czesc:
                cw_agent_reply(conv_id, czesc, token=BOT_PRO_CW_AGENT_TOKEN)

    # B2: bezpiecznik braku postepu — ZAWSZE, niezaleznie od tego, co powyzej
    # wyslano (albo nie wyslano) w tej turze. `podsumowanie.wyslij()` samo juz
    # wyslalo tresc i zapisalo `oczekiwany_podpis` (realny postep), wiec ta
    # galaz tez ma zostac policzona, nie pominieta razem z wczesniejszym "return".
    if stan.migawka_postepu() == migawka_przed:
        bez_postepu = stan.zarejestruj_brak_postepu()
    else:
        bez_postepu = 0
        stan.zresetuj_brak_postepu()
    if bez_postepu >= BOT_PRO_MAX_BEZ_POSTEPU:
        log("tura: %s kolejnych tur bez postepu -> handoff (conv %s)" % (bez_postepu, conv_id))
        _oddaj_konsultantowi("brak postepu przez %s kolejnych tur" % bez_postepu, conv_id)
