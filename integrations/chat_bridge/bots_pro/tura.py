# -*- coding: utf-8 -*-
"""
Jedna tura Dębusia Pro: pętla agentów -> guardrail -> wysyłka.

Rozstrzygnięcie ślepej uliczki między agentami (Task 6): agenci wyspecjalizowani
(Wycena/Wiedza/Posprzedaz, bots_pro/agenci.py) NIE MAJĄ własnych handoffs — tylko
Router ma handoffs=[Wycena, Wiedza, Posprzedaz]. Bez dodatkowego mechanizmu rozmowa,
która trafiła np. do agenta Wiedzy, nie miałaby jak dotrzeć do agenta Wyceny w TEJ
SAMEJ turze.

Rozwiązanie: KAŻDA tura wchodzi przez Router OD NOWA (`zbuduj_router()` wołane tu, przy
każdym `uruchom()`), a historia rozmowy (w tym to, który agent i co odpowiedział
poprzednio) leci przez `SQLiteSession`. Scenariusz „najpierw pytam o materiał (Wiedza),
potem chcę cenę (Wycena)" działa więc MIĘDZY turami: turn 1 -> Router -> Wiedza,
turn 2 -> Router (świeży, ale widzi historię z sesji) -> Wycena. Koszt: jedno
dodatkowe wywołanie routera na turę, w zamian za prostotę (bez N*(N-1) ręcznie
utrzymywanych handoffów między agentami wyspecjalizowanymi) i bez ryzyka, że agent
wyceny zacznie odpowiadać na pytania o wiedzę (i odwrotnie) tylko dlatego, że ma do
niego handoff pod ręką. Patrz test_pro_tura.py::TestScenariuszMaterialPotemCena.

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
Świadomie NIE zamyka trzeciego efektu (b): korekta nadal wchodzi przez Router, który
teoretycznie mógłby przekazać ją do Wiedzy/Posprzedaży — agentów bez narzędzi
policz_wycene/policz_wysylke, więc niezdolnych naprawić ceny. Zamknięcie tego
wymagałoby ominięcia Routera (np. retry na `wynik.last_agent`) — świadomie odłożone,
bo to już zmiana architektury, a nie tylko formatu wiadomości.

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
from agents import SQLiteSession

from config import BOT_PRO_CW_AGENT_TOKEN, BOT_PRO_MAX_TURNS, DB_PATH
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
    mostka (DB_PATH), więc nie dokłada żadnej nowej zależności/pliku."""
    return SQLiteSession(str(conv_id), DB_PATH)


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

    `stan.init_pro()` odpala DDL (CREATE TABLE IF NOT EXISTS) przy KAŻDEJ turze, nie
    tylko raz przy starcie workera — celowo NIEZMIENIONE w tej rundzie poprawek:
    przeniesienie do startu workera wykracza poza ten moduł (worker Dębusia Pro nie
    jest jeszcze częścią tego zadania). Koszt jest mały (CREATE TABLE IF NOT EXISTS na
    już istniejących tabelach), ale odnotowane jako coś do ruszenia, gdy worker powstanie."""
    stan.ustaw_kontekst(conv_id, persona_tury=persona)
    stan.init_pro()

    wynik = Runner.run_sync(
        zbuduj_router(), tresc, session=_sesja(conv_id), max_turns=BOT_PRO_MAX_TURNS)
    odpowiedz = (wynik.final_output or "").strip()

    if odpowiedz:
        # Guardrail G1: kwota spoza kalkulatora nie opuszcza procesu (inwariant I1).
        naruszenia = guardraile.sprawdz_ceny(odpowiedz, stan.znane_kwoty())
        if naruszenia:
            log("guardrail G1: kwoty spoza kalkulatora %s (conv %s)" % (naruszenia, conv_id))
            wynik = Runner.run_sync(zbuduj_router(), _KOMUNIKAT_KOREKTY,
                                    session=_sesja(conv_id), max_turns=BOT_PRO_MAX_TURNS)
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
    if stan.podsumowanie_wyslane():
        return
    if not odpowiedz:
        return

    for czesc in wysylka.przygotuj(odpowiedz, persona):
        if czesc:
            cw_agent_reply(conv_id, czesc, token=BOT_PRO_CW_AGENT_TOKEN)
