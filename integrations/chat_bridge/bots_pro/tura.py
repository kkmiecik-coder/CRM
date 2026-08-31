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
from bots_pro import guardraile, obrazy, stan, wysylka
from bots_pro.agenci import zbuduj_router
from core.chatwoot import cw_agent_reply
from core.log import log

# Jedno zdanie do klienta na KAŻDYM wyjściu handoffowym (U7). Świadomie bez
# obietnicy czasu odpowiedzi konsultanta — `prompty.WYCENA` zabrania jej modelowi,
# więc komunikat sklejany w kodzie tym bardziej nie może jej składać. Bez linków
# i bez markdownu, żeby był bezpieczny w każdym profilu kanału jeszcze przed
# `wysylka.przygotuj` (ta i tak go przepuszcza, ale komunikat awaryjny nie ma
# zależeć od czyszczenia).
KOMUNIKAT_HANDOFF = "Przekazuję rozmowę konsultantowi WoodPower — poprowadzi ją dalej."

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


def _oddaj_konsultantowi(powod, conv_id, persona="pro",
                         klient_dostal_wiadomosc=False):
    """`stan.handoff` zwraca {"ok": False, ...} przy nieudanej wysyłce do Chatwoota —
    bez logu ten stan wygląda z zewnątrz identycznie jak udany handoff (runda poprawek 1,
    drobne). Nie rzucamy wyjątku — brak handoffu nie ma dobrej ścieżki odzysku w tej
    turze, ale ma być WIDOCZNY w logach, nie cichy.

    U7 (recenzja końcowa): przed przekazaniem klient dostaje JEDNO zdanie o tym,
    co się dzieje. Trzy z czterech wyjść handoffowych robiły wcześniej `return`
    bez żadnej wysyłki — klient zostawał w ciszy dokładnie w momencie, w którym
    bot rezygnował z prowadzenia rozmowy (audyt wskazał ciszę jako przyczynę
    porzuceń). Komunikat idzie przez `wysylka.przygotuj`, więc podlega profilowi
    kanału tak samo jak zwykła odpowiedź — sklejony w Pythonie tekst NIE
    przechodzi przez personę modelu, więc bez tego omijałby caps kanału.

    NOTATKI dla konsultanta tu NIE MA — pisze ją `stan.handoff` (patrz jej
    docstring), żeby objąć też handoff wywołany przez sam model.

    N7 (rerecenzja): gdy rozmowa została już oddana W TEJ TURZE (model wołał
    `oddaj_czlowiekowi` albo `przygotuj_zamowienie` na Allegro), nie powtarzamy
    SKUTKÓW UBOCZNYCH — notatki dla konsultanta ani przełączenia statusu. Bramka
    `handoff_w_turze() and not odpowiedz` wyżej nie łapie przypadku, w którym
    model po handoffie JEDNAK coś napisał: klient dostał wtedy pożegnanie modelu,
    a bezpiecznik braku postępu dokładał zaraz po nim drugą wiadomość, drugą
    notatkę i drugie przełączenie statusu — do rozmowy, która jest już u
    człowieka.

    C2 (runda D): ta bramka stała wcześniej na POCZĄTKU funkcji, więc gasiła
    RÓWNIEŻ komunikat do klienta. Gdy handoff przyszedł z narzędzia, a wypowiedzi
    modelu do klienta nie dotarły (zablokował je guardrail G1 albo padło
    podsumowanie), tura kończyła się CISZĄ — zero wiadomości, mimo że rozmowę
    właśnie przejmował człowiek. Idempotentne mają być skutki uboczne, nie
    pożegnanie: `klient_dostal_wiadomosc` mówi, czy klient JUŻ dostał w tej turze
    wypowiedź modelu; tylko wtedy (i tylko po handoffie z narzędzia, bo wtedy to
    model pisze pożegnanie) komunikat pomijamy. W każdym innym przypadku klient
    dostaje dokładnie jedno zdanie o przekazaniu rozmowy."""
    if not (stan.handoff_w_turze() and klient_dostal_wiadomosc):
        for czesc in wysylka.przygotuj(KOMUNIKAT_HANDOFF, persona):
            if czesc:
                cw_agent_reply(conv_id, czesc, token=BOT_PRO_CW_AGENT_TOKEN)
    if stan.handoff_w_turze():
        log("tura: rozmowa juz oddana w tej turze -> pomijam powtorne przekazanie, "
            "powod=%r (conv %s)" % (powod, conv_id))
        return {"ok": True, "powod": powod, "pominiety": True}
    wynik = stan.handoff(powod)
    if not wynik.get("ok"):
        log("tura: handoff do konsultanta NIEUDANY, powod=%r (conv %s)" % (powod, conv_id))
    return wynik


def _oddaj_po_zobowiazaniu(odpowiedz, conv_id, persona):
    """Guardrail G3 (N9): odpowiedź z zakazanym zobowiązaniem NIE idzie do klienta —
    rozmowa idzie do człowieka. Zwraca True, gdy do tego doszło (wołający ma wtedy
    zakończyć turę).

    BEZ rundy korekty, w odróżnieniu od G1. Tam druga próba ma sens, bo zmyśloną
    kwotę da się zastąpić prawdziwą z rejestru — model ma czym poprawić. Tu
    „napisz to jeszcze raz bez obietnicy" dałoby tę samą treść innymi słowami,
    a pytanie, które taką obietnicę wywołało (nośność, użytek zewnętrzny,
    gwarancja, atest), i tak należy do człowieka — mówi to wprost sekcja
    KONSTRUKCJA w `prompty.WYCENA`/`prompty.WIEDZA`.

    `klient_dostal_wiadomosc` czytane tak samo jak przy G1: jedyną rzeczą, którą
    klient mógł już w tej turze dostać, jest deterministyczne podsumowanie."""
    zobowiazania = guardraile.znajdz_zakazane_zobowiazania(odpowiedz)
    if not zobowiazania:
        return False
    log("guardrail G3: zakazane zobowiazania %s -> handoff (conv %s)"
        % (zobowiazania, conv_id))
    _oddaj_konsultantowi(
        "guardrail zobowiązań — odpowiedź obiecywała: %s" % ", ".join(zobowiazania),
        conv_id, persona, klient_dostal_wiadomosc=stan.podsumowanie_wyslane())
    return True


def uruchom(conv_id, inbox_id, tresc, zalaczniki=None, persona="pro", message_id=None):
    """Przeprowadza jedną turę i wysyła odpowiedź do klienta.

    `message_id` (Task 8, W3 code review runda poprawek 1): identyfikator
    wiadomości klienta, którą przetwarza ta tura — wołane z `quote_worker`
    (`mid` wiersza kolejki). Idzie WYŁĄCZNIE do `stan.zarejestruj_ture`, żeby
    odróżnić PRAWDZIWĄ nową turę od PONOWNEJ PRÓBY workera tej samej
    wiadomości po błędzie przejściowym (patrz docstring `zarejestruj_ture`).
    Domyślnie `None` — wywołania bez tego argumentu (w tym większość testów w
    tym pliku) liczą się ZAWSZE jako nowa tura, zachowanie sprzed W3.

    `zalaczniki` (U2, recenzja końcowa): adresy obrazów z tej wiadomości —
    lista albo SUROWY tekst JSON z kolumny `quote_queue.attachments`. Idą do
    modelu jako wejście multimodalne (`bots_pro.obrazy.wejscie`), z formatami
    ograniczonymi profilem kanału. Do tej poprawki parametr istniał WYŁĄCZNIE
    w sygnaturze: wiadomość samym zdjęciem (webhook celowo taką przepuszcza)
    dawała modelowi pusty string.

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
    zapętlonych rozmów w zbadanym shardzie, klienci odpadali przy 10-28 turach).
    UWAGA na asymetrię porównań (drobne, code review runda poprawek 1) — oba progi
    czytane sąsiednio, ale różnie: `BOT_PRO_MAX_TURNS` używa `>` (N tur PRZECHODZI,
    N+1 jest zablokowana — próg to LICZBA DOZWOLONYCH tur), `BOT_PRO_MAX_BEZ_POSTEPU`
    używa `>=` (próg to LICZBA, przy KTÓREJ już blokujemy — "3" oznacza tam "2
    dozwolone"). Nie ujednolicono świadomie: pierwszy sprawdzany jest PRZED turą
    (naturalne "czy ta n-ta tura jeszcze się mieści"), drugi PO turze (naturalne
    "czy licznik po tej turze już osiągnął próg") — ale czytelnik nie ma prawa
    zakładać symetrii tylko z sąsiedztwa w kodzie.
    1. `BOT_PRO_MAX_TURNS` — licznik TUR CAŁEJ ROZMOWY (`stan.zarejestruj_ture`).
       Sprawdzany PRZED wywołaniem Routera/LLM — rozmowa, która już przekroczyła
       budżet, nie dostaje kolejnej (kosztownej) próbki modelu, od razu handoff.
       <=0 WYŁĄCZA ten bezpiecznik (nie: "0 tur dozwolonych" — wzorzec jak w
       sweeper.py/hot_lead_sweeper.py, patrz config.py).
    2. `BOT_PRO_MAX_BEZ_POSTEPU` — licznik KOLEJNYCH tur BEZ ŻADNEJ zmiany stanu
       biznesowego (`stan.migawka_postepu` przed/po turze — patrz jej docstring).
       Mierzalny dopiero PO turze, więc odpowiedź z TEJ (n-tej bez postępu) tury
       nadal idzie do klienta jak zwykle — bezpiecznik dokłada handoff PO wysyłce,
       nie zamiast niej. <=0 WYŁĄCZA analogicznie."""
    if not stan.wolno_prowadzic_rozmowe(conv_id):
        log("tura: bot milczy (rozmowa nie w pending albo ostatnio pisal czlowiek) "
            "(conv %s)" % conv_id)
        return

    stan.ustaw_kontekst(conv_id, persona_tury=persona)

    # Licznik zarejestruj_ture() dziala ZAWSZE (bookkeeping niezalezny od tego, czy
    # bezpiecznik jest wlaczony) — spojnie z zarejestruj_brak_postepu() nizej, gdzie
    # tez tylko EGZEKWOWANIE (handoff) jest gated przez prog>0, nie samo liczenie.
    tury_rozmowy = stan.zarejestruj_ture(message_id)
    if BOT_PRO_MAX_TURNS > 0 and tury_rozmowy > BOT_PRO_MAX_TURNS:
        log("tura: limit %s tur rozmowy przekroczony -> handoff (conv %s)"
            % (BOT_PRO_MAX_TURNS, conv_id))
        _oddaj_konsultantowi("limit dlugosci rozmowy (ponad %s tur)" % BOT_PRO_MAX_TURNS,
                             conv_id, persona)
        return

    # N6: tozsamosc klienta z kontaktu rozmowy (e-mail i nazwa z formularza
    # wstepnego widgetu) — WCZESNIEJ niz `zbuduj_router()` nizej, bo to ono
    # buduje agenta Wyceny, a ten dokleja sobie sekcje DANE KLIENTA z tego, co
    # tu wyladuje. Po bramce ciszy, zeby tura, w ktorej bot i tak ma milczec,
    # nie placila za odczyt. Nie rzuca — brak kontaktu to brak danych (bot
    # poprosi o e-mail, jak dotad), nie przerwana tura.
    stan.wczytaj_kontakt(conv_id)

    migawka_przed = stan.migawka_postepu()

    # U2: zdjecia klienta ida do modelu RAZEM z tekstem (wejscie multimodalne,
    # bots_pro/obrazy.py). Bez zalacznikow `wejscie()` zwraca goly string —
    # sciezka bez zdjec zachowuje sie DOKLADNIE jak przed ta poprawka.
    wejscie_modelu = obrazy.wejscie(tresc, zalaczniki, persona)

    wynik = Runner.run_sync(
        zbuduj_router(), wejscie_modelu, session=_sesja(conv_id),
        max_turns=BOT_PRO_MAX_RUNNER_STEPS)
    odpowiedz = (wynik.final_output or "").strip()

    if odpowiedz:
        # Guardrail G3: zakazane zobowiązanie nie opuszcza procesu (N9). BEZ rundy
        # korekty — patrz `_oddaj_po_zobowiazaniu`. Sprawdzany PRZED G1, żeby
        # obietnica nie kosztowała najpierw (bezużytecznego tutaj) wywołania modelu
        # na poprawkę ceny.
        if _oddaj_po_zobowiazaniu(odpowiedz, conv_id, persona):
            return
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
                    "guardrail ceny — dwie próby z kwotą spoza kalkulatora", conv_id, persona,
                    klient_dostal_wiadomosc=stan.podsumowanie_wyslane())
                return
            # Korekta cenowa produkuje NOWY tekst — G3 ogląda go tak samo jak
            # pierwszą wersję. Bez tego obietnica dopisana dopiero w poprawce
            # wychodziłaby do klienta przez tę samą dziurę, którą G3 zamyka.
            if _oddaj_po_zobowiazaniu(odpowiedz, conv_id, persona):
                return

    # W3: podsumowanie.wyslij() (wolane jako narzedzie, w KTORYMKOLWIEK z powyzszych
    # wywolan Runnera) moglo juz samo wyslac deterministyczna tresc - wtedy NIC wiecej
    # w tej turze nie wysylamy, nawet gdy final_output jest niepusty i przeszedl G1.
    # C2: `klient_dostal_wiadomosc` sledzi, czy klient FAKTYCZNIE cos dostal w tej
    # turze — to jedyna informacja odrozniajaca „model juz sie pozegnal" od
    # „wypowiedzi modelu nie dotarly", a od tego zalezy, czy wyjscie handoffowe
    # ma dolozyc KOMUNIKAT_HANDOFF, czy bylby on powtorka.
    klient_dostal_wiadomosc = stan.podsumowanie_wyslane()
    if not stan.podsumowanie_wyslane() and odpowiedz:
        for czesc in wysylka.przygotuj(odpowiedz, persona):
            if czesc:
                cw_agent_reply(conv_id, czesc, token=BOT_PRO_CW_AGENT_TOKEN)
                klient_dostal_wiadomosc = True

    # U1: podsumowania NIE udalo sie wyslac (Chatwoot odrzucil), a model nic nie
    # napisal — bo prompt wprost pozwala mu zostawic final_output puste po wolaniu
    # wyslij_podsumowanie. Tura konczylaby sie wtedy BEZ ANI JEDNEJ wiadomosci do
    # klienta: dokladnie ta awaria, ktora audyt wskazal jako przyczyne porzucen.
    # Oddajemy rozmowe konsultantowi zamiast milczec. Gdy model jednak cos napisal,
    # klient dostal wiadomosc (wyzej) i handoff bylby zbedna eskalacja.
    if stan.podsumowanie_nieudane() and not odpowiedz:
        log("tura: podsumowanie nie dotarlo do klienta i model nic nie napisal "
            "-> handoff (conv %s)" % conv_id)
        _oddaj_konsultantowi("podsumowanie nie dotarlo do klienta", conv_id, persona)
        return

    # U11: rozmowa zostala oddana konsultantowi Z WNETRZA tury (narzedzie
    # `oddaj_czlowiekowi`, albo `przygotuj_zamowienie` na Allegro — tam handoff
    # jest CZESCIA szczesliwej sciezki, patrz spec D8), a model nic nie napisal.
    # Wskazowka zwracana przez narzedzie to PROSBA w prompcie, nie bramka —
    # bramka jest tutaj. Handoff juz byl, wiec wysylamy sam komunikat.
    if stan.handoff_w_turze() and not odpowiedz and not stan.podsumowanie_wyslane():
        log("tura: handoff z narzedzia, model nic nie napisal -> komunikat "
            "zamiast ciszy (conv %s)" % conv_id)
        for czesc in wysylka.przygotuj(KOMUNIKAT_HANDOFF, persona):
            if czesc:
                cw_agent_reply(conv_id, czesc, token=BOT_PRO_CW_AGENT_TOKEN)
        return

    # B2: bezpiecznik braku postepu — ZAWSZE, niezaleznie od tego, co powyzej
    # wyslano (albo nie wyslano) w tej turze. `podsumowanie.wyslij()` samo juz
    # wyslalo tresc i zapisalo `oczekiwany_podpis` (realny postep), wiec ta
    # galaz tez ma zostac policzona, nie pominieta razem z wczesniejszym "return".
    if stan.migawka_postepu() == migawka_przed:
        bez_postepu = stan.zarejestruj_brak_postepu()
    else:
        bez_postepu = 0
        stan.zresetuj_brak_postepu()
    if BOT_PRO_MAX_BEZ_POSTEPU > 0 and bez_postepu >= BOT_PRO_MAX_BEZ_POSTEPU:
        log("tura: %s kolejnych tur bez postepu -> handoff (conv %s)" % (bez_postepu, conv_id))
        _oddaj_konsultantowi("brak postepu przez %s kolejnych tur" % bez_postepu,
                             conv_id, persona,
                             klient_dostal_wiadomosc=klient_dostal_wiadomosc)
