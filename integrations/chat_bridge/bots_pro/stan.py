# -*- coding: utf-8 -*-
"""
Stan rozmowy Dębusia Pro.

Historia rozmowy idzie przez SQLiteSession Agents SDK — tutaj trzymamy
wyłącznie to, co jest DECYZJĄ BIZNESOWĄ, a nie odtwarzalnym przebiegiem:
identyfikator zapisanej wyceny, dane kontaktowe, fakt podania ceny.

Znane kwoty (do guardraila G1) zbieramy w `pro_stan`, TRWALE PER ROZMOWA — nie
per tura (Task 8, B1). Pierwsza wersja trzymała je w contextvar zerowanym na
starcie KAŻDEJ tury (`ustaw_kontekst` -> `_kwoty.set(set())`) — to działało w
JEDNEJ turze (np. `policz_wycene` rejestruje, `wyslij_podsumowanie` cytuje w tej
samej turze), ale pękało na granicy DWÓCH tur: klient potwierdza w turze N+1,
model woła `potwierdz` -> `znajdz_klienta` -> `zapisz_wycene` i naturalnie pisze
"wycena na 1936,71 zł zapisana" — `zapisz_wycene` NIE zasila rejestru (nie musi,
tylko cytuje już ustaloną cenę), a rejestr TEJ tury jest pusty, bo zerowany na
starcie. Guardrail uznawał więc PRAWDZIWĄ cenę za halucynację, w momencie
udanego zamknięcia sprzedaży. Przechowanie w `pro_stan` (kluczowane po conv_id,
jak reszta tego modułu) usuwa problem u źródła: rejestr żyje tak długo jak
rozmowa, nie jak pojedyncza tura, i — dzięki kluczowaniu po conv_id — NIE
przecieka między różnymi rozmowami (patrz TestKwoty w test_pro_stan.py).
Usuwa to też ryzyko z poprzedniej wersji (B3): `zapamietaj_kwoty` mutowała
WSPÓLNY set z contextvara i TYLKO DZIĘKI TEJ MUTACJI kwoty w ogóle propagowały
z kontekstu narzędzia do tury — gałąź `if biezace is None: _kwoty.set(nowy_set)`
w SKOPIOWANYM kontekście (np. inny wątek/task asyncio) zgubiłaby je PO CICHU,
z fałszywym alarmem guardraila jako jedynym objawem. Zapis do bazy nie ma tej
klasy błędu — nie ma kontekstu do skopiowania.

Runda poprawek 1 (code review) — trzy dalsze poprawki tego samego rejestru:

K1 (K3 w numeracji recenzji, KRYTYCZNE): każdy zapis do `pro_stan`/`pro_dane`
wymaga TERAZ jawnie ustawionego `conv_id()` — `_wymagany_conv_id()` rzuca,
zamiast pozwolić SQLite potraktować NULL w kolumnie `INTEGER PRIMARY KEY` jako
autoinkrement i cicho wylądować w wierszu NASTĘPNEJ (przypadkowej, zwykle
świeżo tworzonej — identyfikatory Chatwoota rosną monotonicznie) rozmowy.

W1 (WAŻNE): rejestr kwot NIE jest już jednym blobem JSON (`zapisz_stan(znane_kwoty_json=...)`,
read-modify-write) — to nie było bezpieczne pod PRAWDZIWĄ współbieżnością: Agents
SDK woła wszystkie narzędzia z JEDNEGO kroku modelu RÓWNOLEGLE (asyncio.gather),
a synchroniczne ciało `@function_tool` idzie przez `asyncio.to_thread`, więc dwa
równoległe `policz_wycene`/`policz_wysylke` mogły odczytać ten sam "stary" zbiór
i nadpisać się nawzajem. Rejestr żyje teraz w osobnej tabeli `pro_kwoty`
(`conv_id, kwota`, klucz złożony) — KAŻDA kwota to OSOBNY wiersz (`INSERT OR
IGNORE`), bez kroku "odczytaj cały zbiór, policz unię, zapisz cały zbiór z
powrotem" nie ma czego zgubić w przeplocie.

W2 (WAŻNE): rejestr nigdy sam nie wygasał — po kilku przeliczeniach RÓŻNYCH
konfiguracji (klient zmienia materiał/wymiary między przeliczeniami; prompt
WPROST zachęca do liczenia kilka razy w rozmowie) rósł bez ograniczeń i
zawierał też ceny konfiguracji już porzuconych, które bot mógłby zacytować, a
guardrail by je przepuścił (formalnie "znane"). `zapisz_pozycje` TERAZ czyści
cały rejestr tej rozmowy przy KAŻDEJ FAKTYCZNEJ zmianie pozycji (patrz `_zmien_pozycje`
— porównanie starego/nowego `dane_json`, uszczelnione w rundzie poprawek 2, N1,
po tym jak bezwarunkowe czyszczenie kasowało też no-opowe zapisy) — kolejne
`policz_wycene`/`wyslij_podsumowanie` musi go zasilić od nowa, zanim bot znów
będzie mógł zacytować jakąkolwiek cenę. Dokładnie ten sam kształt co I2
(potwierdzenia.py), tylko zastosowany do rejestru cen zamiast do podpisu
potwierdzenia.

Analogicznie, fakt wysłania deterministycznego podsumowania (`podsumowanie.wyslij`)
zbieramy per tura w OSOBNYM contextvarze — `tura.py` sprawdza go PO Runner.run_sync,
żeby nie wysłać klientowi DRUGIEGO, tym razem sparafrazowanego przez model,
podsumowania w tej samej turze (patrz komentarz w podsumowanie.py przy `wyslij()`:
model dostaje wskazówkę zostawić `final_output` puste, ale to dyscyplina promptu,
nie bramka — bramka jest tutaj)."""
import contextvars
import json
import threading

from core.db import db
from core.events import log_event
from core.log import log

_conv_id = contextvars.ContextVar("conv_id", default=None)
_persona = contextvars.ContextVar("persona", default=None)
# N6 (runda napraw 2): tozsamosc klienta odczytana z Chatwoota na starcie tury —
# {name, email, phone}. Per TURA, nie per rozmowa: dane na kontakcie moga sie
# miedzy turami zmienic (konsultant je poprawi, klient dopisze telefon w profilu),
# a stan sprzed dwoch tur jest tu gorszy niz swiezy odczyt. `ustaw_kontekst`
# zeruje ten var — inaczej kolejna rozmowa obsluzona w tym samym watku workera
# zobaczylaby CUDZY adres e-mail, a bot ma go klientowi pokazac.
_kontakt = contextvars.ContextVar("kontakt", default=None)

# X1: sekcja krytyczna dla stanu, ktorego NIE DA SIE zapisac jednym, atomowym
# zapytaniem — czyli dla blobu pozycji (`pro_dane.dane_json`) i dla pary
# „zapisz oszacowanie dostawy + zarejestruj jego kwoty".
#
# DLACZEGO w ogole: to ten sam ksztalt bledu, ktory W1 (docstring modulu wyzej)
# usunal dla REJESTRU KWOT, rozbijajac go na osobne wiersze `pro_kwoty` —
# pozycje tej poprawki nie dostaly, bo one MAJA istotna kolejnosc (podsumowanie
# drukuje je po kolei, `wynik_dla_modelu` robi zip z odpowiedzia kalkulatora),
# wiec blob z gwarantowana kolejnoscia jest tu wlasciwa struktura, a nie wada.
# Zamiast rozbijac dane, serializujemy sekwencje. `zapisz_pozycje` bylo
# klasycznym read-modify-write na DWOCH osobnych polaczeniach (`_wczytaj` ->
# mutacja w pamieci -> `_zapisz`), a Agents SDK woła wszystkie narzedzia
# JEDNEGO kroku modelu rownolegle (asyncio.gather w agents/run_internal/
# tool_execution.py), przepuszczajac synchroniczne cialo `@function_tool` przez
# `asyncio.to_thread` — czyli przez PRAWDZIWE watki, ktorych GIL nie
# synchronizuje na granicy I/O do SQLite. Prompt kaze wołać `zapisz_pozycje`
# osobno dla kazdej pozycji, wiec lista 13 elementow to 13 rownoleglych
# read-modify-write na jednym blobie. ZMIERZONE na tym kodzie przed naprawa:
# z 13 rownoleglych zapisow roznych pozycji zostawala DOKLADNIE 1, w 10/10
# przebiegow — dokladnie ten podpis ma produkcyjna rozmowa 4912 (z 13 elementow
# ocalal szosty, `horizontal-divider`, a klient dostal do potwierdzenia 123,55 zl
# zamiast ~1000 zl). Bramka I2 dziala wtedy formalnie bez zarzutu i jednoczesnie
# przypina podpis klienta do 1/13 zamowienia.
#
# RLock, nie Lock: sekcja krytyczna obejmuje cale cialo razem z zapisem, a ten
# importuje `bots_pro.potwierdzenia`; ponowne wejscie tego samego watku (dzis:
# `policz_wysylke` -> `zapisz_dostawe`) ma dac poprawny przebieg, nie
# zakleszczenie. Nazwa PUBLICZNA (bez podkreslnika), bo zamka uzywa takze
# `narzedzia.py` — para „zapis stanu + rejestracja kwot" musi byc jedna sekcja
# krytyczna po stronie WOLAJACEGO, tu nie da sie jej zamknac.
#
# RYZYKO RESZTKOWE, nazwane wprost: to jest zamek PROCESU. Wystarcza, bo mostek
# to JEDEN proces — `bridge.py` startuje same watki i konczy na
# `app.run(threaded=True)`, a Dockerfile ma `CMD ["python","bridge.py"]`; drugi
# entrypoint (`bridge_quote_candidate.py`) pracuje na WLASNYM pliku bazy
# (`BRIDGE_DB`). Uruchomienie tego kiedykolwiek pod gunicornem z WIECEJ NIZ
# JEDNYM workerem — albo wskazanie obu entrypointom tego samego `BRIDGE_DB` —
# CICHO cofnie te naprawe: zamek nie siega poza proces, a objawem beda znowu
# gubione pozycje, bez zadnego bledu w logach.
zamek_stanu = threading.RLock()

# X2: cztery flagi „co juz zdarzylo sie w TEJ turze", czytane przez `tura.py`
# PO `Runner.run_sync`, a ustawiane z wnetrza narzedzi.
#
# BYLY contextvarami i przez to BYLY MARTWE. Agents SDK uruchamia synchroniczne
# cialo `@function_tool` przez `asyncio.to_thread`, a to odpala funkcje w KOPII
# kontekstu — `.set()` z narzedzia nie wraca do wolajacego. Zmierzone: narzedzie
# ustawia flage na True, po powrocie do `tura.py` widac False. Zawsze. Czyli
# bezpieczniki U1 („podsumowanie nie doszlo i model nic nie napisal -> handoff
# zamiast ciszy"), U11 („handoff z narzedzia, model nic nie napisal -> komunikat
# zamiast ciszy") i bramka W3 (blokada DRUGIEGO, sparafrazowanego przez model
# podsumowania) nie uruchamialy sie NIGDY. Nie wybuchlo dotad tylko dlatego, ze
# model posluchal promptu i po podsumowaniu milczal — czyli bezpiecznik istnial
# wylacznie na papierze, a cisza po pytaniu bota to jedna z awarii, ktore audyt
# wskazal jako przyczyne porzucen.
#
# Slownik modulowy pod `zamek_stanu`, a NIE kolumny w `pro_stan`: semantyka ma
# zostac „per TURA, nie per rozmowa" (patrz komentarze przy poszczegolnych
# flagach nizej), a to znaczy zerowanie na starcie kazdej tury. Kolumny w bazie
# daloby sie wyzerowac tak samo, ale kosztem zapisu do bazy przy KAZDEJ fladze i
# — co wazniejsze — `ustaw_kontekst` musialoby zaczac PISAC do `pro_stan` dla
# rozmowy, ktora bota moze w ogole nie dotyczyc (dzis nie dotyka bazy w ogole).
# Pamiec procesu jest tu wlasciwym miejscem, bo to stan JEDNEJ tury tego samego
# procesu, a nie decyzja biznesowa, ktora ma przezyc restart: po restarcie
# mostka tura i tak zaczyna sie od nowa.
#
# Kluczowanie po conv_id, nie jedna globalna flaga: `to_thread` kopiuje kontekst,
# wiec `conv_id()` w watku narzedzia jest ten sam co w turze — a rozmowy
# obslugiwane rownolegle (dzis: jeden watek workera, ale watchdog i przyszly
# drugi worker sa w zasiegu) nie moga sobie nawzajem zapalac bezpiecznikow.
_flagi_tury = {}
# Slownik zyje tyle, co proces, wiec bez limitu roslby o jeden maly wpis na
# rozmowe az do restartu. Limit jest hojny (kilkadziesiat rozmow naraz mostek i
# tak nie prowadzi) i przycinamy wpis NAJDAWNIEJ UZYWANY, czyli te rozmowe,
# ktora najdawniej zaczynala ture — a wiec te, ktorej tura na pewno sie juz
# skonczyla.
#
# „Najdawniej uzywany" wymaga wspolpracy `_wyzeruj_flagi_tury`: dict trzyma
# kolejnosc PIERWSZEGO wstawienia, wiec samo `_flagi_tury[conv_id] = {}` na
# starcie kolejnej tury NIE odswiezalo pozycji w kolejce i najdawniej WIDZIANA
# rozmowa (np. aktywna od startu procesu) wypadala jako pierwsza, w srodku
# swojej wlasnej tury. `tura.py` czytalby wtedy `podsumowanie_wyslane()` jako
# False, choc podsumowanie poszlo — czyli drugie, sparafrazowane podsumowanie
# albo cisza, dokladnie ta klasa awarii, ktorej flagi mialy zapobiec. Dzis
# nieosiagalne (jeden watek workera, tury sekwencyjne), ale drugi worker jest
# w zasiegu. Stad `pop` przed przypisaniem w `_wyzeruj_flagi_tury`.
_LIMIT_ROZMOW_Z_FLAGAMI = 64

_SCHEMAT = """
CREATE TABLE IF NOT EXISTS pro_dane(
  conv_id INTEGER PRIMARY KEY, dane_json TEXT);
CREATE TABLE IF NOT EXISTS pro_stan(
  conv_id INTEGER PRIMARY KEY,
  quote_edit_uuid TEXT, quote_saved INTEGER DEFAULT 0, priced INTEGER DEFAULT 0,
  contact_email TEXT, contact_phone TEXT, contact_name TEXT,
  oczekiwany_podpis TEXT, potwierdzony_podpis TEXT,
  potwierdzenie_cytat TEXT, potwierdzenie_ts REAL,
  czlowiek_odezwal_sie INTEGER DEFAULT 0,
  tury_rozmowy INTEGER DEFAULT 0, tury_bez_postepu INTEGER DEFAULT 0,
  ostatni_liczony_mid TEXT,
  dostawa_kod TEXT, dostawa_kurier TEXT,
  dostawa_netto REAL, dostawa_brutto REAL,
  quote_public_url TEXT, quote_dostawa_niedopisana INTEGER DEFAULT 0,
  pokazana_kwota REAL);
CREATE TABLE IF NOT EXISTS pro_kwoty(
  conv_id INTEGER, kwota TEXT, zrodlo TEXT DEFAULT 'produkt',
  PRIMARY KEY(conv_id, kwota));
"""


def init_pro():
    """Tabele stanu Dębusia Pro. Świadomie BEZ kolumn bot_turns, awaiting_*,
    reject_*, sent_images, returning_greeted, human_deflected — przebieg rozmowy
    odtwarza sesja Agents SDK, a te kolumny były księgowaniem tego przebiegu.

    `czlowiek_odezwal_sie` (N2, code review runda 2), `tury_rozmowy`/
    `tury_bez_postepu` (Task 8, B2) i `ostatni_liczony_mid` (Task 8, W3 code
    review) dołożone ALTER-em osobno — `CREATE TABLE IF NOT EXISTS` w
    `_SCHEMAT` nie doda kolumny do tabeli, która już istnieje z wdrożeń sprzed
    tej zmiany (ten sam wzorzec co w core/db.py). `pro_kwoty` (Task 8, W1 code
    review) to NOWA tabela — zastąpiła kolumnę `znane_kwoty_json` (jeden blob
    JSON, read-modify-write) rejestrem kwot jako osobnych wierszy, żeby zapisy
    z różnych wątków/tasków nie mogły się nawzajem nadpisać (patrz docstring
    modułu, W1)."""
    polaczenie = db()
    try:
        polaczenie.executescript(_SCHEMAT)
        for stmt in (
            "ALTER TABLE pro_stan ADD COLUMN czlowiek_odezwal_sie INTEGER DEFAULT 0",
            "ALTER TABLE pro_stan ADD COLUMN tury_rozmowy INTEGER DEFAULT 0",
            "ALTER TABLE pro_stan ADD COLUMN tury_bez_postepu INTEGER DEFAULT 0",
            "ALTER TABLE pro_stan ADD COLUMN ostatni_liczony_mid TEXT",
            # U4: dostawa jest CZĘŚCIĄ ceny (wymóg właściciela: produkt + ew.
            # dostawa), więc musi być trwała jak reszta stanu biznesowego —
            # inaczej nie ma jak wejść ani do podpisu, ani do podsumowania.
            "ALTER TABLE pro_stan ADD COLUMN dostawa_kod TEXT",
            "ALTER TABLE pro_stan ADD COLUMN dostawa_kurier TEXT",
            "ALTER TABLE pro_stan ADD COLUMN dostawa_netto REAL",
            "ALTER TABLE pro_stan ADD COLUMN dostawa_brutto REAL",
            # U3: publiczny link do wyceny. Modelu NIE da się poprosić o jego
            # złożenie — token publiczny nie jest edit_uuid i bot nie zna adresu
            # bazowego CRM, więc jedynym źródłem prawdy jest to, co zwróciło
            # create_quote/update_quote. Bez tej kolumny nie ma czego wysłać.
            "ALTER TABLE pro_stan ADD COLUMN quote_public_url TEXT",
            # R1: wycena zapisana w CRM, ale BEZ potwierdzonej przez klienta
            # dostawy (nieudany PUT dopisujacy kuriera). Link do takiej wyceny
            # NIE MOZE wyjsc — klient zobaczylby inna cene niz potwierdzil.
            "ALTER TABLE pro_stan ADD COLUMN quote_dostawa_niedopisana INTEGER DEFAULT 0",
            # N2: skąd wzięła się kwota w rejestrze G1 — 'produkt' albo
            # 'dostawa'. Bez tego nowe oszacowanie kuriera nie miało jak
            # unieważnić poprzedniego kosztu wysyłki (patrz `zapisz_dostawe`).
            "ALTER TABLE pro_kwoty ADD COLUMN zrodlo TEXT DEFAULT 'produkt'",
            # Z4: kwota, ktora klient FAKTYCZNIE zobaczyl w podsumowaniu — do
            # notatki dla konsultanta. Nie da sie jej odtworzyc z `pro_kwoty`:
            # tam leza WSZYSTKIE kwoty zwrocone przez kalkulator (ceny
            # jednostkowe kazdej pozycji, sumy czastkowe), bez sladu, ktora z
            # nich poszla do klienta jako cena calosci. Kolumna jest zapisem
            # HISTORYCZNYM i swiadomie NIE jest czyszczona przy zmianie pozycji
            # (inaczej ginalby jedyny slad tego, co klient widzial) — nie
            # kopiuj tu logiki uniewazniania z sasiedniego N2.
            "ALTER TABLE pro_stan ADD COLUMN pokazana_kwota REAL",
        ):
            try:
                polaczenie.execute(stmt)
            except Exception:
                pass
        polaczenie.commit()
    finally:
        polaczenie.close()


def ustaw_kontekst(conv_id, persona_tury="pro"):
    """Wołane na początku tury przez worker.

    Świadomie NIE zeruje rejestru kwot (Task 8, B1) — ten żyje w `pro_stan`,
    trwale per ROZMOWA (conv_id), nie per tura. Zerowanie go tutaj byłoby
    dokładnie tym błędem, który B1 naprawia: cena ustalona w tej rozmowie w
    poprzedniej turze ma zostać znana guardrailowi także w kolejnych turach tej
    samej rozmowy — patrz docstring modułu i TestKwoty w test_pro_stan.py."""
    _conv_id.set(conv_id)
    _persona.set(persona_tury)
    _kontakt.set(None)
    _wyzeruj_flagi_tury(conv_id)


def ustaw_kontekst_odczytu(conv):
    """Ustawia conv_id do ODCZYTÓW spoza tury — dziś: wątek `pro_watchdog`,
    który po automatycznym oddaniu rozmowy musi złożyć notatkę z tego, co bot
    w niej zebrał.

    ZAWĘŻONA WERSJA `ustaw_kontekst`, i to jest cała jej racja bytu. Bez
    ustawionego conv_id odczyty (`pozycje`, `dostawa`, `zapisana_wycena`,
    `pokazana_kwota`) świadomie NIE wołają `_wymagany_conv_id` i po prostu nie
    znajdą wiersza — notatka napisałaby „Zebrane pozycje: brak" na rozmowie,
    która pozycje MA, czyli zamieniłaby widoczny brak w niewidoczne kłamstwo.
    Ale pełne `ustaw_kontekst` w tym miejscu byłoby lekarstwem gorszym od
    choroby: woła `_wyzeruj_flagi_tury`, a `_flagi_tury` to słownik MODUŁOWY,
    wspólny dla wszystkich wątków procesu (patrz X2 w docstringu modułu).
    Watchdog i worker chodzą równolegle, a rozmowa może w tej samej sekundzie
    dostać wiadomość od klienta i wejść w turę — wyzerowanie jej flag z cudzego
    wątku w środku tury gasi dokładnie te bezpieczniki, które X2 przywróciło do
    życia (drugie podsumowanie, drugi handoff, cisza po pytaniu bota). Dlatego
    tutaj ustawiamy WYŁĄCZNIE contextvary, które są prywatne dla wątku
    wołającego, i nie dotykamy stanu współdzielonego.

    Persony NIE ustawiamy: notatka dla konsultanta jej nie używa (to profil
    wysyłki do KLIENTA), a watchdog do klienta nic nie pisze."""
    _conv_id.set(conv)
    _kontakt.set(None)


def _wyzeruj_flagi_tury(conv_id):
    """Kasuje flagi turowe TEJ rozmowy (X2). Wolane wylacznie z `ustaw_kontekst`,
    czyli raz na ture — to jest cala definicja „per tura": flaga zyje od startu
    tury do startu nastepnej, a nie przez cala rozmowe."""
    with zamek_stanu:
        # `pop` PRZED przypisaniem, i to nie jest kosmetyka. Przypisanie do
        # klucza, ktory juz istnieje, NIE przesuwa go na koniec — dict trzyma
        # kolejnosc PIERWSZEGO wstawienia. Bez tego popu rozmowa aktywna od
        # startu procesu byla pierwsza w kolejce do wyrzucenia przez limit
        # nizej, mimo ze jej tura wlasnie sie zaczela; wyrzucany mial byc wpis
        # najdawniej UZYWANY, a wyrzucany byl najdawniej WIDZIANY.
        _flagi_tury.pop(conv_id, None)
        _flagi_tury[conv_id] = {}
        while len(_flagi_tury) > _LIMIT_ROZMOW_Z_FLAGAMI:
            _flagi_tury.pop(next(iter(_flagi_tury)))


def _ustaw_flage_tury(nazwa, wartosc=True):
    """Zapala flage turowa BIEZACEJ rozmowy.

    Swiadomie NIE wola `_wymagany_conv_id()`: flagi to sygnal miedzy narzedziem
    a `tura.py`, a nie zapis do bazy — brak conv_id nie moze tu uszkodzic cudzej
    rozmowy (klucz `None` jest osobnym, wlasnym wpisem), a twardy fail
    zamienialby drobiazg w przerwana ture. Odwrotnie niz przy zapisach, gdzie
    cichy zapis pod NULL-em lezy w cudzym wierszu (patrz `_wymagany_conv_id`).

    `wartosc` jest zwykle `True` (flaga = fakt zaszedl). Jedyny wyjatek —
    `podsumowanie_bez_wysylki` — trzyma tu KROTKI KOD POWODU, bo `tura.py`
    musi napisac klientowi co innego przy „lista sie zmienila" niz przy „nie
    mam ani jednej pozycji". Osobne flagi na kazdy powod rozmnozylyby warunki
    w turze; wartosc w tej samej fladze trzyma decyzje w jednym miejscu."""
    with zamek_stanu:
        _flagi_tury.setdefault(conv_id(), {})[nazwa] = wartosc


def _flaga_tury(nazwa):
    """Czy flaga jest zapalona w BIEZACEJ turze BIEZACEJ rozmowy."""
    with zamek_stanu:
        return bool((_flagi_tury.get(conv_id()) or {}).get(nazwa))


def _wartosc_flagi_tury(nazwa):
    """Wartosc flagi turowej (kod powodu) albo None, gdy flagi nie ma."""
    with zamek_stanu:
        return (_flagi_tury.get(conv_id()) or {}).get(nazwa)


def conv_id():
    return _conv_id.get()


def wczytaj_kontakt(conv_id):
    """Tozsamosc klienta z kontaktu rozmowy w Chatwoocie — do udostepnienia
    agentowi Wyceny (N6).

    DLACZEGO w ogole: formularz wstepny widgetu zapisuje e-mail i nazwe na
    KONTAKCIE rozmowy, a Debus Pro i tak prosil po wycenie o „e-mail i telefon".
    To regres wobec starego silnika, nie brakujaca funkcja — `cw_contact_full`
    istnieje w `core/chatwoot.py` i `bots/quotebot.py` z niej korzysta; przy
    przepisywaniu na `bots_pro/` po prostu nie przeniesiono ani jednego
    wywolania. Rozstrzygniecie wlasciciela: „bot moze co najwyzej potwierdzic
    czy sie zgadza".

    ODCZYT, nie zapis — idzie tokenem admina jak reszta odczytow Pro (patrz
    docstring `test_pro_zapora_core_chatwoot.py`: zapora dotyczy ZAPISOW, bo to
    one zostawiaja w rozmowie slad podpisany cudza tozsamoscia).

    NIE RZUCA. `cw_contact_full` sama lapie wyjatki, ale osloniecie jest tu
    dodatkowe i celowe: brak kontaktu ma byc brakiem DANYCH (bot poprosi o
    e-mail, jak dotad), nigdy przerwana tura. Odwrotnie niz
    `wolno_prowadzic_rozmowe`, gdzie blad odczytu MUSI przejsc dalej, bo cisza
    jest tam bezpieczniejsza od zgadywania.

    Wolane jako atrybut modulu (`stan.wczytaj_kontakt`), zeby dalo sie je
    podmienic w `e2e/replay.py` tak samo jak pozostale odczyty z Chatwoota."""
    try:
        from core.chatwoot import cw_contact_full
        dane = cw_contact_full(conv_id) or {}
    except Exception as blad:
        log("stan: nie udalo sie wczytac kontaktu klienta (conv %s): %s" % (conv_id, blad))
        dane = {}
    _kontakt.set(dane)
    return dane


def kontakt():
    """Kontakt wczytany w TEJ turze; pusty slownik, gdy odczytu nie bylo albo
    Chatwoot nic nie zna (kanaly bez formularza wstepnego — OLX, Allegro).
    Zawsze slownik, nigdy None — inaczej oslone musialby miec KAZDY wolajacy."""
    return _kontakt.get() or {}


def persona():
    """Persona bieżącej tury (np. 'pro', 'quote_olx', 'quote_allegro') — decyduje
    m.in. o profilu wysyłki w podsumowaniu (bez markdownu na OLX, bez linków na Allegro)."""
    return _persona.get()


def oznacz_podsumowanie_wyslane():
    """Wołane WYŁĄCZNIE przez `podsumowanie.wyslij()`, zaraz po tym, jak sam wyśle
    deterministyczne podsumowanie do klienta. `tura.py` czyta to niżej
    (`podsumowanie_wyslane`), żeby nie wysłać jeszcze jednej wiadomości w tej
    samej turze — nawet jeśli model coś dopisał, a guardrail G1 (integralność
    ceny) by to przepuścił (bo dopiska nie musi mieć ceny, żeby był problemem —
    problemem jest DRUGIE podsumowanie własnymi słowami modelu tuż po pierwszym,
    deterministycznym).

    X2: flaga żyje w słowniku modułowym pod `zamek_stanu`, nie w contextvarze —
    contextvar ustawiony TUTAJ nigdy nie wracał do `tura.py`, bo SDK uruchamia
    ciało narzędzia przez `asyncio.to_thread`, czyli w KOPII kontekstu. Bramka
    opisana w docstringu `tura.py` jako „tą bramką" nie strzelała ani razu."""
    _ustaw_flage_tury("podsumowanie_wyslane")


def podsumowanie_wyslane():
    """Czy w BIEŻĄCEJ turze już wysłano deterministyczne podsumowanie."""
    return _flaga_tury("podsumowanie_wyslane")


def oznacz_podsumowanie_nieudane():
    """Wołane przez `podsumowanie.wyslij()`, gdy Chatwoot NIE przyjął podsumowania
    (`cw_agent_reply` zwróciło False — ta funkcja nigdy nie rzuca, więc bez
    sprawdzenia wartości niepowodzenie jest niewidoczne).

    Świadomie NIE ustawia `_podsumowanie_wyslane`: tamta flaga BLOKUJE dalszą
    wysyłkę w tej turze, a tu jest odwrotna potrzeba — klient nie dostał nic i
    trzeba mu cokolwiek powiedzieć (albo oddać rozmowę konsultantowi).

    U1 (recenzja końcowa): wysyłka podsumowania do Chatwoota NIE POWIODŁA się w
    tej turze. Osobny sygnał od `podsumowanie_wyslane` — tamten mówi „nie
    wysyłaj nic więcej", ten mówi „klient NIC nie dostał, a miał dostać".
    `tura.py` czyta go, żeby tura, w której model dodatkowo nic nie napisał,
    skończyła się handoffem, nie ciszą."""
    _ustaw_flage_tury("podsumowanie_nieudane")


def podsumowanie_nieudane():
    """Czy w BIEŻĄCEJ turze próba wysłania podsumowania się NIE powiodła."""
    return _flaga_tury("podsumowanie_nieudane")


def oznacz_podsumowanie_bez_wysylki(powod):
    """`wyslij_podsumowanie` skończyło się BEZ wysłania czegokolwiek klientowi,
    a NIE była to awaria kanału. Dwa powody dziś (`powod` to ich krótki kod):

      - `"zmiana_w_trakcie"` (P1b) — stan zmienił się w trakcie liczenia, więc
        treść opisywałaby dane sprzed ostatnich zapisów tego samego kroku
        modelu, a klient dostałby prefiks listy podany jako komplet;
      - `"brak_pozycji"` (R3) — w rozmowie nie ma ani jednej zapisanej pozycji,
        bo `wyslij_podsumowanie` uszeregowało się PRZED `zapisz_pozycje` tego
        samego kroku modelu. Ta ścieżka do tej poprawki nie zapalała NICZEGO:
        narzędzie oddawało `BRAK_POZYCJI`, model po wywołaniu podsumowania ma
        prawo milczeć — i tura kończyła się ciszą.

    TRZECI, osobny sygnał — nie da się go zastąpić żadnym z dwóch istniejących
    i to jest cały powód, dla którego istnieje:
      - `podsumowanie_wyslane` BLOKUJE dalszą wysyłkę w tej turze, a tu klient
        nie dostał nic i coś dostać musi;
      - `podsumowanie_nieudane` znaczy „Chatwoot odrzucił", czyli awarię
        kanału, i `tura.py` odpowiada na nią HANDOFFEM. Tu awarii nie ma:
        wystarczy policzyć jeszcze raz, gdy zapisy już wylądowały. Handoff
        byłby niepotrzebną eskalacją na w pełni odwracalnym zdarzeniu.

    `tura.py` czyta ten sygnał WYŁĄCZNIE po to, żeby tura nie skończyła się
    ciszą — dosyła klientowi jedno krótkie zdanie dobrane po `powod`. NIE
    ponawia podsumowania: wysyłka poza przebiegiem modelu rozjeżdżała bazę z
    pamięcią modelu i potrafiła odezwać się do klienta po oddaniu rozmowy
    człowiekowi (patrz komentarz w `tura.uruchom`)."""
    _ustaw_flage_tury("podsumowanie_bez_wysylki", powod)


def podsumowanie_bez_wysylki():
    """Kod powodu, dla którego podsumowanie nie dotarło do klienta w TEJ turze
    (patrz wyżej), albo None. Prawdziwościowo działa jak flaga."""
    return _wartosc_flagi_tury("podsumowanie_bez_wysylki")


def oznacz_handoff_w_turze():
    """U11/U7: w tej turze doszło już do handoffu — WYWOŁANEGO Z NARZĘDZIA,
    wewnątrz `Runner.run_sync` (`oddaj_czlowiekowi`, albo `przygotuj_zamowienie`
    na Allegro). Wołane wyłącznie przez `handoff` niżej."""
    _ustaw_flage_tury("handoff_w_turze")


def handoff_w_turze():
    """Czy w BIEŻĄCEJ turze rozmowa została już oddana konsultantowi.

    Prawdziwe TYLKO dla handoffu z wnętrza tury (`stan.handoff`) — czyta to
    `tura.py`, żeby tura, w której model oddał rozmowę narzędziem i NIC nie
    napisał, nie skończyła się ciszą (U11: `przygotuj_zamowienie` na Allegro
    kończy notatką i handoffem, a wskazówka dla modelu to tylko prośba).

    N7: czyta to także sam `handoff` — drugie oddanie rozmowy w tej samej
    turze jest już bezczynne.

    Per TURA, nie per rozmowa — pytanie brzmi „czy klient dostał coś w TEJ
    turze", nie „czy kiedykolwiek"."""
    return _flaga_tury("handoff_w_turze")


def oznacz_notatke_w_turze():
    """Wołane przez `notatki.wyslij_notatke` po UDANYM wysłaniu notatki (N7).
    Notatka, która NIE doszła, świadomie się nie liczy — inaczej awaria
    Chatwoota zostawiałaby konsultanta bez czegokolwiek.

    N7 (rerecenzja): wyjścia, które piszą WŁASNĄ, bogatszą notatkę (Allegro w
    `przygotuj_zamowienie`, nieudane dopisanie dostawy w `zapisz_wycene`) wołają
    zaraz po niej `handoff`, a ten dokładał drugą, prawie identyczną
    (`notatki.notatka_stanu`). Jedna notatka na turę — wygrywa ta napisana
    PIERWSZA, bo to zawsze ta konkretniejsza."""
    _ustaw_flage_tury("notatka_w_turze")


def notatka_w_turze():
    """Czy w BIEŻĄCEJ turze konsultant dostał już prywatną notatkę (N7)."""
    return _flaga_tury("notatka_w_turze")


def _wymagany_conv_id():
    """`conv_id()` z kontekstu, z TWARDYM failem gdy nie ustawiony (Task 8, K3
    code review runda poprawek 1). SQLite traktuje NULL w `INTEGER PRIMARY KEY`
    jako autoinkrement — zapis bez ustawionego `conv_id` NIE rzuca sam z siebie,
    tylko cicho ląduje w wierszu NASTĘPNEJ (przypadkowej, zwykle świeżo tworzonej
    — identyfikatory Chatwoota rosną monotonicznie) rozmowy. Ta funkcja zamienia
    ciche uszkodzenie cudzych danych na głośny, natychmiastowy błąd. Wołana
    PRZEZ WSZYSTKIE funkcje piszące (`_zmien_pozycje`, `zapisz_stan`, `zarejestruj_ture`,
    `zarejestruj_brak_postepu`) — funkcje WYŁĄCZNIE czytające (`znane_kwoty`,
    `pozycje` przez `_wczytaj`, `migawka_postepu`) zostają bez zmian: brak
    conv_id przy odczycie po prostu nie znajdzie żadnego wiersza, co jest
    nieszkodliwe (pusty wynik), w odróżnieniu od zapisu (cudzy wiersz
    uszkodzony)."""
    biezacy = conv_id()
    if biezacy is None:
        raise RuntimeError(
            "bots_pro.stan: conv_id nie jest ustawiony (brak stan.ustaw_kontekst przed "
            "zapisem) — odmawiam zapisu, zeby nie wyladowal w wierszu INNEJ rozmowy")
    return biezacy


def zapamietaj_kwoty(wartosci, zrodlo="produkt"):
    """Rejestruje kwoty zwrócone przez kalkulator — guardrail porówna z nimi
    treść odpowiedzi. Wartości mogą przyjść jako float (typowo) albo string
    z polskim przecinkiem dziesiętnym — stąd zamiana przed float().

    Trwały zapis w tabeli `pro_kwoty` (Task 8, B1 + W1 code review), nie
    contextvar ani jeden blob JSON — patrz docstring modułu. Każda kwota to
    OSOBNY wiersz: żaden krok nie czyta "starego" zbioru przed zapisem, więc
    dwa równoległe wywołania (Agents SDK woła narzędzia z jednego kroku modelu
    przez `asyncio.gather`) nie mogą się nawzajem nadpisać (W1) — w najgorszym
    razie oba INSERT-y po prostu się skolejkują na poziomie SQLite.

    `zrodlo` (N2, rerecenzja gałęzi): 'produkt' albo 'dostawa'. Kwoty dostawy
    (koszt kuriera i suma „produkt + dostawa") tracą ważność przy KAŻDYM nowym
    oszacowaniu wysyłki — `zapisz_dostawe` kasuje wtedy właśnie je, tak jak
    `_zmien_pozycje` kasuje cały rejestr przy zmianie pola cenotwórczego pozycji.

    Przy konflikcie (ta sama kwota już w rejestrze) 'produkt' WYPIERA 'dostawa',
    nigdy odwrotnie. To jest ochrona przed zbiegiem okoliczności „koszt kuriera
    równy jednej z cen produktu": kasowanie kwot dostawy nie ma prawa zabrać
    kwoty, którą zna także kalkulator produktu, bo wtedy PRAWDZIWA cena stałaby
    się dla guardraila halucynacją."""
    biezacy_conv_id = _wymagany_conv_id()
    znormalizowane = {"%.2f" % float(str(w).replace(",", ".")) for w in wartosci}
    if not znormalizowane:
        return
    polaczenie = db()
    try:
        polaczenie.executemany(
            "INSERT INTO pro_kwoty(conv_id, kwota, zrodlo) VALUES(?,?,?) "
            "ON CONFLICT(conv_id, kwota) DO UPDATE SET zrodlo='produkt' "
            "WHERE excluded.zrodlo='produkt'",
            [(biezacy_conv_id, k, zrodlo) for k in znormalizowane])
        polaczenie.commit()
    finally:
        polaczenie.close()


def znane_kwoty():
    """Kwoty znane guardrailowi G1 dla BIEŻĄCEJ rozmowy (conv_id z kontekstu) —
    zbiór trwa przez całą rozmowę (dopóki jej pozycje się FAKTYCZNIE nie
    zmienią — patrz `_zmien_pozycje`, W2/N1), nie tylko bieżącą turę (patrz docstring
    modułu)."""
    polaczenie = db()
    try:
        wiersze = polaczenie.execute(
            "SELECT kwota FROM pro_kwoty WHERE conv_id=?", (conv_id(),)).fetchall()
    finally:
        polaczenie.close()
    return {w["kwota"] for w in wiersze}


def zarejestruj_ture(message_id=None):
    """Inkrementuje licznik TUR CAŁEJ ROZMOWY (Task 8, B2) — NIE mylić z
    BOT_PRO_MAX_RUNNER_STEPS (limit iteracji narzędzie->model WEWNĄTRZ jednej
    tury, config.py). Wołane RAZ, na samym początku `tura.uruchom`, dla KAŻDEJ
    tury, w której bot faktycznie działa (a więc już PO bramce ciszy
    `wolno_prowadzic_rozmowe` — tura, w której bot milczy, nie zużywa budżetu).
    Zwraca nową wartość licznika PO inkrementacji (albo BIEŻĄCĄ, niezmienioną,
    gdy to retry — patrz niżej).

    W3 (code review, runda poprawek 1): `message_id` odróżnia PRAWDZIWĄ nową
    turę od PONOWNEJ PRÓBY workera tej samej wiadomości klienta po błędzie
    przejściowym — `quote_worker.process_one` po wyjątku wraca wierszem do
    'pending' i woła `tura.uruchom` PONOWNIE dla TEJ SAMEJ wiadomości. Bez tego
    rozróżnienia kilka błędów sieci zjadałoby budżet `BOT_PRO_MAX_TURNS` bez
    UDZIAŁU klienta, prowadząc do przedwczesnego handoffu "limit długości
    rozmowy". Rozpoznanie retry: `quote_worker` przetwarza rozmowy w kolejności
    per conv_id (API-06 — nie bierze nowszego rekordu, gdy starszy tej samej
    rozmowy jeszcze czeka), więc kolejne próby TEJ SAMEJ wiadomości ZAWSZE
    przychodzą z rzędu, zanim jakakolwiek NOWSZA wiadomość tej rozmowy w ogóle
    trafi do `uruchom()` — prosta pamięć "ostatnio policzony message_id"
    wystarcza, bez osobnej tabeli historii. `message_id=None` (np. wywołanie
    bez identyfikatora, albo w testach) ZAWSZE liczy się jako nowa tura — nie
    da się wykryć retry bez identyfikatora."""
    biezacy_conv_id = _wymagany_conv_id()
    mid = str(message_id) if message_id is not None else None
    polaczenie = db()
    try:
        if mid is not None:
            wiersz = polaczenie.execute(
                "SELECT tury_rozmowy, ostatni_liczony_mid FROM pro_stan WHERE conv_id=?",
                (biezacy_conv_id,)).fetchone()
            if wiersz and wiersz["ostatni_liczony_mid"] == mid:
                return wiersz["tury_rozmowy"]
        polaczenie.execute(
            "INSERT INTO pro_stan(conv_id, tury_rozmowy, ostatni_liczony_mid) VALUES(?, 1, ?) "
            "ON CONFLICT(conv_id) DO UPDATE SET tury_rozmowy = tury_rozmowy + 1, "
            "ostatni_liczony_mid = excluded.ostatni_liczony_mid",
            (biezacy_conv_id, mid))
        polaczenie.commit()
        wiersz = polaczenie.execute(
            "SELECT tury_rozmowy FROM pro_stan WHERE conv_id=?", (biezacy_conv_id,)).fetchone()
    finally:
        polaczenie.close()
    return wiersz["tury_rozmowy"]


def migawka_postepu():
    """Odcisk stanu BIZNESOWEGO bieżącej rozmowy — do wykrywania braku postępu
    między turami (Task 8, B2). Obejmuje zapisane pozycje (`pro_dane`), znane
    kwoty (`pro_kwoty`) ORAZ kolumny `pro_stan`, które zmieniają się WYŁĄCZNIE
    w wyniku realnej decyzji (wysłane podsumowanie, potwierdzenie klienta,
    zapisana wycena) — celowo BEZ `tury_rozmowy`/`tury_bez_postepu`/
    `ostatni_liczony_mid` (te zmieniają się co turę z definicji, więc wliczenie
    ich do odcisku zawsze pokazywałoby "postęp" i bezpiecznik nigdy by się nie
    uruchomił).

    Porównanie odcisku SPRZED i PO turze (w `tura.uruchom`) wykrywa postęp
    niezależnie od tego, KTÓRE konkretne narzędzie go spowodowało — odporne na
    nowe narzędzia zmieniające stan dodane w przyszłości bez aktualizacji tej
    funkcji, w odróżnieniu od ręcznie utrzymywanej listy nazw narzędzi."""
    polaczenie = db()
    try:
        wiersz_stanu = polaczenie.execute(
            "SELECT quote_edit_uuid, quote_saved, oczekiwany_podpis, potwierdzony_podpis, "
            "potwierdzenie_cytat FROM pro_stan WHERE conv_id=?",
            (conv_id(),)).fetchone()
        wiersz_pozycji = polaczenie.execute(
            "SELECT dane_json FROM pro_dane WHERE conv_id=?", (conv_id(),)).fetchone()
        kwoty = sorted(w["kwota"] for w in polaczenie.execute(
            "SELECT kwota FROM pro_kwoty WHERE conv_id=?", (conv_id(),)).fetchall())
    finally:
        polaczenie.close()
    return json.dumps({
        "stan": dict(wiersz_stanu) if wiersz_stanu else None,
        "pozycje": wiersz_pozycji["dane_json"] if wiersz_pozycji else None,
        "kwoty": kwoty,
    }, sort_keys=True, ensure_ascii=False)


def zarejestruj_brak_postepu():
    """Inkrementuje licznik KOLEJNYCH tur BEZ ŻADNEJ zmiany stanu biznesowego
    (patrz `migawka_postepu`). Zwraca nową wartość licznika PO inkrementacji."""
    biezacy_conv_id = _wymagany_conv_id()
    polaczenie = db()
    try:
        polaczenie.execute(
            "INSERT INTO pro_stan(conv_id, tury_bez_postepu) VALUES(?, 1) "
            "ON CONFLICT(conv_id) DO UPDATE SET tury_bez_postepu = tury_bez_postepu + 1",
            (biezacy_conv_id,))
        polaczenie.commit()
        wiersz = polaczenie.execute(
            "SELECT tury_bez_postepu FROM pro_stan WHERE conv_id=?", (biezacy_conv_id,)).fetchone()
    finally:
        polaczenie.close()
    return wiersz["tury_bez_postepu"]


def zresetuj_brak_postepu():
    """Wołane, gdy tura ZROBIŁA realny postęp — zeruje licznik z
    `zarejestruj_brak_postepu`, żeby kolejna seria bezczynności liczyła się od nowa."""
    zapisz_stan(tury_bez_postepu=0)


def _wczytaj():
    polaczenie = db()
    try:
        wiersz = polaczenie.execute(
            "SELECT dane_json FROM pro_dane WHERE conv_id=?", (conv_id(),)).fetchone()
    finally:
        polaczenie.close()
    return json.loads(wiersz["dane_json"]) if wiersz else {"pozycje": []}


def _zmien_pozycje(mutator):
    """Jedyne miejsce piszące do `pro_dane`. Bierze funkcję, która dostaje
    ODCZYTANY słownik danych, mutuje go w pamięci i zwraca wynik dla wołającego
    — a odczyt, mutacja i zapis dzieją się w JEDNEJ sekcji krytycznej, na
    JEDNYM połączeniu.

    X1 (naprawa wyścigu): wcześniej odczyt (`_wczytaj`) i zapis (`_zapisz`)
    chodziły po DWÓCH osobnych połączeniach, z mutacją w pamięci pomiędzy —
    klasyczny read-modify-write bez blokady. Wszystkie narzędzia jednego kroku
    modelu lecą u SDK równolegle, w prawdziwych wątkach, a prompt każe wołać
    `zapisz_pozycje` osobno dla każdej pozycji, więc 13-elementowa lista klienta
    to 13 wątków czytających TEN SAM stary blob i nadpisujących się nawzajem.
    Zmierzone przed naprawą: z 13 równoległych zapisów zostawała 1, w 10/10
    przebiegach. Uzasadnienie zamka i ryzyko resztkowe — patrz `zamek_stanu`.

    DLACZEGO NIE `BEGIN IMMEDIATE`, choć to podręcznikowy sposób na
    read-modify-write w SQLite: bo w TYM module przesuwa moment wzięcia zamka
    zapisu z pierwszego INSERT-a na sam początek sekcji, a wtedy równoległy
    `zapamietaj_kwoty` ZAWSZE przegrywa wyścig i jego INSERT ląduje PO
    `DELETE FROM pro_kwoty` niżej. Skutek: kwota policzona dla PORZUCONEJ już
    konfiguracji zostaje w rejestrze G1 jako „znana" i guardrail ją przepuści —
    czyli dokładnie ta awaria, przed którą chroni W2 (patrz docstring modułu).
    Zmierzone na tym samym scenariuszu (realna zmiana pozycji równolegle z
    rejestracją kwoty, 20 przebiegów): dziś nieaktualna kwota przeżywa 0/20,
    z `BEGIN IMMEDIATE` 20/20 — DETERMINISTYCZNA regresja I1. Sam zamek procesu
    daje ten sam komplet 13/13 pozycji (też zmierzone), a moment wzięcia zamka
    ZAPISU zostawia dokładnie tam, gdzie był: na pierwszym INSERT-cie. Odczyt
    leci w autocommit, jak dotąd — spójności czytanej migawki pilnuje zamek
    procesu, nie izolacja transakcji, i tylko dlatego wolno tu tak zrobić.

    Czyszczenie rejestru kwot siedzi TU, a nie w `zapisz_pozycje` (W2, code
    review runda poprawek 1): gwarantuje, że KAŻDA zmiana pozycji czyści
    rejestr, niezależnie od tego, którą ścieżką `zapisz_pozycje` do niej
    doszło — i niezależnie od przyszłych wywołujących, gdyby jacyś powstali.

    N1 (code review, runda poprawek 2): czyszczenie było BEZWARUNKOWE — każde
    wywołanie zapisu (a więc każde `zapisz_pozycje`, TAKŻE bez faktycznej
    zmiany treści, np. model powtarza identyczne dane albo dopisuje puste
    `otwory=[]` PO tym, jak już policzył cenę) kasowało rejestr, mimo że nic
    się nie zmieniło. Naprawa: PRZED zapisem odczytujemy STARY `dane_json` NA
    TYM SAMYM połączeniu i czyścimy TYLKO gdy treść faktycznie się różni — w
    JEDNEJ transakcji z UPSERT-em pozycji, przed wspólnym commitem (nie jako
    osobne, późniejsze wywołanie na nowym połączeniu). Dwa efekty: (1) no-opowy
    zapis nigdy nie czyści (zamyka to w całości sekwencyjny przebieg z sondy
    code review); (2) gdy czyszczenie NAPRAWDĘ następuje (prawdziwa zmiana
    pozycji), dzieje się to w tej samej transakcji co zapis pozycji, więc okno
    na wyścig z równoległym `policz_wycene`/`zapamietaj_kwoty` (W1) jest węższe
    — DELETE nie jest już osobną, PÓŹNIEJSZĄ operacją na osobnym połączeniu,
    czekającą na własną kolejkę I/O już PO commicie zapisu pozycji.

    U6 (recenzja końcowa): porównanie idzie po POLACH CENOTWÓRCZYCH
    (`potwierdzenia.odcisk_cenotworczy`), nie po całym `dane_json`. Poprzednia
    wersja czyściła rejestr przy zmianie DOWOLNEGO pola — w tym `otwory`
    (jawnie NIEWYCENIANE, `build_products` ich nie czyta) i `produkt`. Typowa
    tura „dopisuję wycięcie na zlew, cena blatu to nadal 1 936,71 zł" kończyła
    się więc naruszeniem G1 na PRAWDZIWEJ kwocie: runda korekty, a przy drugim
    niepowodzeniu oddanie rozmowy człowiekowi — na końcu udanej wyceny.
    Definicja „pola cenotwórczego" jest JEDNA i mieszka w `potwierdzenia.py`
    razem z listą pól podpisu.

    U-N7b (rerecenzja): rejestr kwot czyści TAKŻE zejście pozycji z prostokąta,
    mimo że `ksztalt` nie jest polem cenotwórczym i odcisk się nie zmienia. To
    dwa różne pytania: odcisk odpowiada „czy kalkulator policzyłby to samo"
    (kształtu nie czyta, więc policzyłby), a rejestr G1 — „czy ta kwota nadal
    opisuje tę pozycję". Bez tego warunku cena policzona dla prostokąta zostawała
    w rejestrze po deklaracji „a ma być sześciokątny" i model mógł ją LEGALNIE
    powtórzyć klientowi jako orientacyjną: G1 jej nie zatrzymywał, bo przyszła
    z kalkulatora. Bramka kształtu zamyka policzenie i podsumowanie, ale nie
    POWTÓRZENIE kwoty już zarejestrowanej — a materiał sześciokąta 87x75 tej
    kwoty nie pokrywa (rozmowa 4727). Fałszywych alarmów to nie tworzy: po
    takiej deklaracji model i tak nie ma jak przeliczyć, bo bramka odmawia,
    więc żadnej PRAWDZIWEJ kwoty do wypowiedzenia już nie ma.

    Zwraca parę `(wynik mutatora, liczba pozycji PO zapisie)`."""
    from bots_pro.potwierdzenia import kwota_nadal_opisuje

    biezacy_conv_id = _wymagany_conv_id()
    with zamek_stanu:
        polaczenie = db()
        try:
            wiersz = polaczenie.execute(
                "SELECT dane_json FROM pro_dane WHERE conv_id=?",
                (biezacy_conv_id,)).fetchone()
            dane = (json.loads(wiersz["dane_json"]) or {}) if wiersz else {"pozycje": []}
            # Kopia GŁĘBOKA przez JSON, nie `list(...)`: mutator sięga do wnętrza
            # słowników pozycji (ustawia pola, czyści `finishing_id`), więc płytka
            # kopia dałaby te same obiekty i porównanie odcisku niżej zawsze
            # wychodziłoby „bez zmian" — rejestr kwot nigdy by się nie czyścił.
            stare_pozycje = json.loads(json.dumps(dane.get("pozycje") or []))

            wynik = mutator(dane)

            # Predykat „czy kwota nadal opisuje tę pozycję" mieszka w
            # `potwierdzenia`, bo zadają go TRZY miejsca (tu, `policz_wycene`
            # i `podsumowanie.wyslij`) — dwie kopie tej reguły już raz się
            # rozjechały i cena prostokąta wchodziła do rejestru G1 dla
            # pozycji zadeklarowanej jako sześciokąt.
            uniewaznic_kwoty = (
                wiersz is None
                or not kwota_nadal_opisuje(stare_pozycje, dane.get("pozycje")))
            polaczenie.execute(
                "INSERT INTO pro_dane(conv_id, dane_json) VALUES(?,?) "
                "ON CONFLICT(conv_id) DO UPDATE SET dane_json=excluded.dane_json",
                (biezacy_conv_id, json.dumps(dane, ensure_ascii=False)))
            if uniewaznic_kwoty:
                polaczenie.execute(
                    "DELETE FROM pro_kwoty WHERE conv_id=?", (biezacy_conv_id,))
                # U4: koszt dostawy zależy od GABARYTU, więc zmiana pozycji unieważnia
                # go tak samo jak cenę produktu. Kod pocztowy ZOSTAJE (klient go już
                # podał, nie ma powodu pytać drugi raz) — znika tylko kurier i koszt,
                # żeby podsumowanie nie pokazało ceny dostawy sprzed zmiany wymiarów.
                # Przy zejściu z prostokąta gabaryt się nie zmienia, a mimo to
                # kasujemy dostawę tą samą ścieżką: rejestr kwot idzie do zera
                # CAŁY (kwoty ze źródła 'dostawa' to także suma „produkt +
                # dostawa", więc niosą w sobie nieaktualną cenę produktu), a
                # koszt wysyłki zostawiony w `pro_stan` bez pokrycia w rejestrze
                # byłby dla G1 halucynacją przy następnym podsumowaniu.
                polaczenie.execute(
                    "UPDATE pro_stan SET dostawa_kurier=NULL, dostawa_netto=NULL, "
                    "dostawa_brutto=NULL WHERE conv_id=?", (biezacy_conv_id,))
            polaczenie.commit()
        except Exception:
            # Wyjątek z mutatora (np. `_rozloz_wariant` na uszkodzonym katalogu)
            # nie może zostawić półzapisanego stanu ani otwartej transakcji na
            # połączeniu, które za chwilę zamykamy — jawny rollback, a błąd leci
            # dalej do wołającego, bo cichy zapis „części pozycji" byłby gorszy
            # od przerwanej tury.
            polaczenie.rollback()
            raise
        finally:
            polaczenie.close()
    return wynik, len(dane.get("pozycje") or [])


def pozycje():
    """Pozycje wyceny zapisane w tej rozmowie."""
    return _wczytaj().get("pozycje", [])


def migawka():
    """Spójna para `(pozycje, dostawa)` — OBA odczyty pod jednym `zamek_stanu`.

    K2: to są dwa osobne odczyty z dwóch różnych tabel (`pro_dane` i
    `pro_stan`), a KAŻDE narzędzie kroku modelu leci równolegle, w prawdziwym
    wątku. Wzięte osobno potrafią więc opisywać dwa różne momenty — a razem
    składają się na jedną rzecz: to, co klient potwierdził i co idzie do CRM
    (cena to produkt + ew. dostawa, wymóg właściciela). Podpis I2 liczy się
    z obu, więc rozjazd między nimi jest rozjazdem W ŚRODKU podpisu.

    Po co osobna funkcja, a nie `with zamek_stanu:` u każdego wołającego:
    bo wołających jest kilku (`zapisz_wycene`, `popraw_wycene`,
    `podsumowanie.wyslij`) i pytanie „którą parę odczytów trzeba objąć jednym
    zamkiem" ma mieć JEDNĄ odpowiedź, tak samo jak predykat
    `potwierdzenia.kwota_nadal_opisuje` ma jedną definicję.

    Zamek jest tylko na czas dwóch odczytów SQLite — żadnego obcego I/O pod
    nim nie ma i nie może być (patrz `zamek_stanu`)."""
    with zamek_stanu:
        return pozycje(), dostawa()


def _zapomnij_kwoty_dostawy():
    """Kasuje z rejestru G1 kwoty pochodzące z oszacowania wysyłki (N2)."""
    polaczenie = db()
    try:
        polaczenie.execute(
            "DELETE FROM pro_kwoty WHERE conv_id=? AND zrodlo='dostawa'",
            (_wymagany_conv_id(),))
        polaczenie.commit()
    finally:
        polaczenie.close()


def zapisz_dostawe(kod_pocztowy, kurier=None, netto=None, brutto=None):
    """Zapamiętuje oszacowanie dostawy dla tej rozmowy (U4).

    NADPISUJE komplet czterech pól, nie łączy z poprzednim stanem: nowy kod
    pocztowy bez kuriera (gabaryt poza standardem) MUSI wyczyścić koszt sprzed
    zmiany, inaczej klient potwierdziłby nieaktualną cenę dostawy.

    Dostawa mieszka w `pro_stan`, nie w `pro_dane` (pozycje), świadomie: to stan
    PER ROZMOWA, a nie pole pozycji, i nie ma powodu, żeby jej zapis przechodził
    przez logikę czyszczenia rejestru kwot z `_zmien_pozycje`.

    N2 (rerecenzja gałęzi): ma jednak swoją WŁASNĄ, węższą — zmiana kuriera albo
    kosztu unieważnia kwoty dostawy w rejestrze G1 (sam koszt i sumę „produkt +
    dostawa"). Bez tego stara cena wysyłki zostawała w rejestrze na zawsze i bot
    mógł ją legalnie zacytować klientowi po zmianie kodu pocztowego — asymetria
    wobec ceny produktu, którą `_zmien_pozycje` chroni od U6/N1. Czyścimy
    WYŁĄCZNIE przy faktycznej zmianie (ta sama zasada co tam): powtórzone
    identyczne oszacowanie nie ma prawa kasować niczego.

    X1: sekwencja „odczytaj poprzednie -> zapisz nowe -> porównaj -> ewentualnie
    skasuj kwoty" to ten sam read-modify-write co przy pozycjach, tylko rozłożony
    na trzy połączenia. Dwa równoległe `policz_wysylke` (klient podaje dwa kody
    pocztowe w jednej wiadomości) mogły przeplotem zostawić w `pro_stan` kwotę
    jednego kuriera, a w rejestrze G1 kwoty drugiego. Zamek to zamyka."""
    with zamek_stanu:
        poprzednia = dostawa()
        zapisz_stan(dostawa_kod=kod_pocztowy or None, dostawa_kurier=kurier or None,
                    dostawa_netto=netto, dostawa_brutto=brutto)
        bylo = (poprzednia.get("kurier"), poprzednia.get("netto"), poprzednia.get("brutto"))
        jest = (kurier or None, netto, brutto)
        if bylo != jest:
            _zapomnij_kwoty_dostawy()


def dostawa():
    """Oszacowanie dostawy tej rozmowy — `{}` gdy nic nie policzono.

    Klucze pojawiają się tylko dla wartości USTAWIONYCH: brak `kurier`/`brutto`
    znaczy „wysyłki nie udało się oszacować", nie „gratis" (ta sama zasada, co
    w `narzedzia.policz_wysylke`, gdzie klucze o wartości None są pomijane).
    Ten sam kształt trafia do podpisu potwierdzenia i do podsumowania."""
    polaczenie = db()
    try:
        wiersz = polaczenie.execute(
            "SELECT dostawa_kod, dostawa_kurier, dostawa_netto, dostawa_brutto "
            "FROM pro_stan WHERE conv_id=?", (conv_id(),)).fetchone()
    finally:
        polaczenie.close()
    if not wiersz:
        return {}
    surowe = {"kod_pocztowy": wiersz["dostawa_kod"], "kurier": wiersz["dostawa_kurier"],
              "netto": wiersz["dostawa_netto"], "brutto": wiersz["dostawa_brutto"]}
    return {k: v for k, v in surowe.items() if v is not None}


def _rozloz_wariant(kod):
    """selected_variant (enum bezpieczny dla modelu, np. 'dab-lity-ab') -> (gatunek,
    technologia, klasa) w języku, którego oczekuje bots.crm_calc.build_products.

    NIE rezygnujemy z enuma jako parametru narzędzia — to on chroni model przed
    kombinacją spoza oferty (np. 'jes-lity-bb', której nie ma w VARIANT_CODES).
    Warstwa stanu tłumaczy bezpieczny enum na język kalkulatora, więc obie
    własności (bezpieczeństwo enuma + zgodność z build_products) są zachowane
    naraz, zamiast wybierać jedną kosztem drugiej."""
    from bots.crm_calc import VARIANT_CODES
    cfg = VARIANT_CODES.get(kod)
    if not cfg:
        return None
    return cfg["species"], cfg["technology"], cfg["wood_class"]


def _zastosuj_krawedzie(biezaca, edges):
    """Krawędzie są POZA generyczną pętlą pól — jak w starym silniku (patrz
    bots/quotebot.py, komentarz przy _merge_dane: "Krawedzie — poza
    _merge_pola. Znormalizowana niepusta lista (round/chamfer) zastepuje.").

    Znormalizowana niepusta lista ZASTĘPUJE w całości wcześniejszą obróbkę tej
    pozycji — model podaje komplet krawędzi, które mają obowiązywać, nie tylko
    zmienianą literę. Jawne "sharp" (ostra) w którymś wpisie to sygnał
    USUNIĘCIA całej wcześniej zapisanej obróbki: crm_calc.normalize_edges
    milcząco POMIJA wpisy "sharp" (dla niej to "brak obróbki", nie osobna
    wartość do zapisania), więc bez tej odrębnej ścieżki intencja klienta
    "chcę ostre, bez fazowania" ginęłaby, a stara obróbka zostawałaby
    w pozycji na zawsze. `edges=None` (model nic nie powiedział o krawędziach
    w tej turze) NIE kasuje — nie trzeba ich powtarzać co turę."""
    from bots.crm_calc import normalize_edges, raw_ma_sharp
    if edges is None:
        return
    znormalizowane = normalize_edges(edges)
    if znormalizowane:
        biezaca["edges"] = znormalizowane
    elif raw_ma_sharp(edges):
        biezaca["edges"] = []


def zapisz_pozycje(id, produkt="", dlugosc_cm=0, szerokosc_cm=0, grubosc_cm=0,
                   ilosc=0, selected_variant="", finishing_option_id=None,
                   wykonczenie="", edges=None, otwory=None, ksztalt="",
                   usun=False):
    """Wstawia albo aktualizuje JEDNĄ pozycję pod stałym identyfikatorem.
    Puste pola nie kasują wcześniej ustalonych wartości — model woła to
    narzędzie raz na zmianę, a nie przepisuje całej listy.

    `selected_variant` jest dodatkowo rozkładany na gatunek/technologia/klasa
    (patrz `_rozloz_wariant`) — bez tego crm_calc.build_products nie rozpozna
    pozycji (czyta te trzy pola osobno, nie kod wariantu) i KAŻDA wycena
    kończyłaby się `WYCENA_NIEUDANA`, niezależnie od tego, co wybrał klient.

    `edges` i `otwory` mają WŁASNĄ semantykę zapisu, inną niż reszta pól —
    patrz `_zastosuj_krawedzie` (edges) i sekcję niżej (otwory). `wykonczenie
    == "surowe"` dodatkowo czyści `finishing_id` — patrz komentarz przy tym
    warunku (W1, runda poprawek 1).

    `ksztalt` (U-N7) idzie zwykłą ścieżką pól tekstowych: pusty NIE kasuje
    wcześniejszej deklaracji. To jest tu WIĄŻĄCE, nie kosmetyczne — gdyby pole
    miało domyślną wartość "prostokąt" zamiast pustej, KAŻDE kolejne wywołanie
    (np. samo doprecyzowanie ilości) po cichu cofałoby wcześniejsze
    „sześciokąt" i otwierało bramkę `podsumowanie.blokada_ksztaltu`. Domyślnym
    kształtem jest prostokąt, ale wyraża go BRAK pola, nie jego nadpisywanie.

    X1: ciało (odczyt -> mutacja -> zapis) było wcześniej rozłożone na dwa
    osobne połączenia i przez to gubiło pozycje pod współbieżnością — dziś jest
    MUTATOREM przekazanym do `_zmien_pozycje`, które wykonuje je w jednej sekcji
    krytycznej. Semantyka jednowątkowa jest bez najmniejszej zmiany: te same
    gałęzie, w tej samej kolejności, na tym samym słowniku `dane`."""
    def _mutuj(dane):
        pozycje = dane.setdefault("pozycje", [])
        biezaca = next((p for p in pozycje if p.get("id") == id), None)

        if usun:
            dane["pozycje"] = [p for p in pozycje if p.get("id") != id]
            return {"ok": True, "usunieto": id}

        if biezaca is None:
            biezaca = {"id": id}
            pozycje.append(biezaca)

        return _uzupelnij_pozycje(
            biezaca, produkt, dlugosc_cm, szerokosc_cm, grubosc_cm, ilosc,
            selected_variant, finishing_option_id, wykonczenie, edges, otwory,
            ksztalt)

    wynik, liczba_pozycji = _zmien_pozycje(_mutuj)
    # X1: model widzi, ile pozycji ma zapisanych PO swoim zapisie — sam wynik
    # `{"ok": True, "pozycja": ...}` mówił wyłącznie o JEDNEJ pozycji, więc
    # zwinięcie listy do jednej było dla modelu niewidoczne. To SYGNAŁ, nie
    # bramka: przy kilku wywołaniach w jednym kroku każde zwraca licznik ze
    # swojego momentu, a `asyncio.gather` oddaje wyniki w kolejności WYWOŁANIA,
    # nie zakończenia — więc pełną listę widać dopiero w największej z liczb, a
    # jedynym wiarygodnym miejscem na weryfikację kompletu zostaje świeży odczyt
    # w podsumowaniu.
    wynik["liczba_pozycji"] = liczba_pozycji
    # T1: JEDYNY sposób, żeby na produkcji rozstrzygnąć spór o przyczynę
    # zwinięcia listy 13 elementów do jednej pozycji — czy model zrobił JEDNO
    # wywołanie z jedną pozycją, czy TRZYNAŚCIE wywołań, które nadpisały się
    # nawzajem (lost update na `pro_dane`). Te dwie hipotezy dają identyczny
    # stan końcowy i różnią się WYŁĄCZNIE liczbą wywołań tej funkcji oraz
    # przebiegiem licznika po każdym z nich. Kasowanie logujemy tak samo, bo
    # zmienia liczbę pozycji dokładnie tak jak zapis.
    #
    # Zwykły `log`, nie `log_event`: to diagnostyka wywołań narzędzia, nie
    # zdarzenie lejka — do `quote_events` należą etapy sprzedaży, nie zapisy
    # pól. Nie jest gated `BOT_PRO_TRACING` (dziś 0), bo wtedy pojawiłaby się
    # dopiero po włączeniu tracingu na produkcji, a ma być widoczna OD RAZU
    # i PRZED naprawą wyścigu — inaczej nie będzie z czym porównać stanu po niej.
    log("stan: %s pozycji %r, pozycji po zapisie: %s (conv %s)"
        % ("usuniecie" if usun else "zapis", id, liczba_pozycji, conv_id()))
    return wynik


def _uzupelnij_pozycje(biezaca, produkt, dlugosc_cm, szerokosc_cm, grubosc_cm,
                       ilosc, selected_variant, finishing_option_id, wykonczenie,
                       edges, otwory, ksztalt=""):
    """Nakłada pola z wywołania `zapisz_pozycje` na JEDNĄ pozycję — czysta
    mutacja w pamięci, bez ani jednego dotknięcia bazy.

    Wydzielone z `zapisz_pozycje` przy X1 wyłącznie po to, żeby mutator
    przekazywany do `_zmien_pozycje` nie urósł do trzech ekranów wewnątrz
    sekcji krytycznej. Treść jest tą samą, co przed X1, co do znaku — pola idą
    w tej samej kolejności i po tych samych warunkach."""
    for pole, wartosc in (
        ("produkt", produkt), ("dlugosc", dlugosc_cm), ("szerokosc", szerokosc_cm),
        ("grubosc", grubosc_cm), ("ilosc", ilosc),
        ("selected_variant", selected_variant), ("finishing_id", finishing_option_id),
        ("wykonczenie", wykonczenie), ("ksztalt", ksztalt),
    ):
        if wartosc not in ("", 0, None):
            biezaca[pole] = wartosc

    if selected_variant:
        rozlozony = _rozloz_wariant(selected_variant)
        if rozlozony:
            biezaca["gatunek"], biezaca["technologia"], biezaca["klasa"] = rozlozony

    from bots.crm_calc import _finish_type
    if _finish_type(wykonczenie) == "Surowe":
        # "surowe" = brak wykończenia -> finishing_id staje się bez znaczenia
        # dla WYCENY (crm_calc.build_products/_finish_type ignoruje go, gdy
        # ftype == "Surowe") — ale bez jawnego wyczyszczenia zostawałby w
        # pozycji jako duch: podsumowanie (i podpis potwierdzenia) pokazywałyby
        # KOLOR/POŁYSK sprzed zmiany na "surowe", mimo że wycena go już nie
        # liczy (W1, runda poprawek 1 — ta sama klasa błędu co W5 z poprzedniej
        # rundy, tylko odwrócona: tam klient widział MNIEJ niż podpisywał, tu
        # widziałby CO INNEGO). `finishing_option_id` samo w sobie NIE ma
        # sposobu na wyczyszczenie (0 -> None -> pole pomijane w pętli wyżej,
        # patrz bots_pro/narzedzia.py:zapisz_pozycje) — czyszczenie musi więc
        # być automatyczne, wywołane samą zmianą wykończenia na "surowe".
        #
        # Porównanie przez crm_calc._finish_type (podciąg "surow", bez
        # względu na wielkość liter/diakrytyki), NIE `== "surowe"` (runda
        # poprawek 2, N1): to DOKŁADNIE ta sama reguła, którą stosuje wycena
        # (crm_calc.build_products), więc "czyszczę finishing_id" i "wycena
        # ignoruje finishing_id" są zawsze zgodne ze sobą — dwa niezależne
        # porównania tego samego tekstu łatwo rozjeżdżają się przy literówce/
        # innej pisowni. Dziś enum narzędzia (Wykonczenie) wysyła wyłącznie
        # dokładne "surowe", więc luka jest nieosiągalna PRZEZ NARZĘDZIE —
        # ale to samo dotyczyło W2 dla selected_variant, więc obrona ma
        # działać niezależnie od enumu, nie zamiast niego.
        biezaca.pop("finishing_id", None)

    _zastosuj_krawedzie(biezaca, edges)

    # Otwory/wycięcia: opisowa lista, NIE wyceniana automatycznie (koszt
    # dolicza konsultant — jak w starym silniku, bots/quotebot.py: "OTWORY/
    # WYCIĘCIA: NIE wyceniasz"). Podana lista (także pusta — jawne
    # "klient zrezygnował") ZASTĘPUJE poprzednią; `otwory=None` (pole
    # pominięte w tej turze) niczego nie zmienia.
    if otwory is not None:
        biezaca["otwory"] = list(otwory)

    return {"ok": True, "pozycja": biezaca}


def zapisz_stan(**kolumny):
    """Upsert dowolnych kolumn `pro_stan` dla bieżącej rozmowy. `potwierdzenia.py`
    i `podsumowanie.py` wołają to zamiast dublować własny UPSERT do cudzej
    tabeli (tabela rozjeżdża się przy pierwszej zmianie schematu, tak jak
    groziło to podwójnemu odczytowi pozycji przed poprawką w tym module).

    UWAGA (drobne, code review runda poprawek 1): NIE jest już jedynym
    miejscem piszącym do `pro_stan` — `zarejestruj_ture`/`zarejestruj_brak_postepu`
    (Task 8, B2) mają WŁASNE UPSERT-y (potrzebują `RETURNING`-owej wartości PO
    inkrementacji, czego generyczny upsert tutaj by nie dał bez dodatkowego
    zapytania). Nadal jedyne miejsce dla kolumn zapisywanych PRZEZ WARTOŚĆ
    (nie inkrementowanych)."""
    if not kolumny:
        return
    biezacy_conv_id = _wymagany_conv_id()
    nazwy = list(kolumny)
    polaczenie = db()
    try:
        polaczenie.execute(
            "INSERT INTO pro_stan(conv_id, %s) VALUES(?,%s) "
            "ON CONFLICT(conv_id) DO UPDATE SET %s" % (
                ",".join(nazwy), ",".join("?" * len(nazwy)),
                ",".join("%s=excluded.%s" % (n, n) for n in nazwy)),
            tuple([biezacy_conv_id] + [kolumny[n] for n in nazwy]))
        polaczenie.commit()
    finally:
        polaczenie.close()


def handoff(powod):
    """Oddaje rozmowę konsultantowi. Token bota Pro przekazujemy JAWNIE —
    domyślny cw_bot_handoff sięga po token bota-podpowiadacza.

    U7 (recenzja końcowa): NAJPIERW prywatna notatka z powodem i zebranym
    stanem, DOPIERO POTEM przełączenie statusu. Ta kolejność jest ta sama, co
    w starym silniku (`bots.quotebot._do_handoff`, API-05): gdy notatka
    padnie, rozmowa wciąż jest w 'pending', więc worker może ponowić turę
    czysto, zamiast zostawić rozmowę w 'open' bez śladu, dlaczego. Notatka
    siedzi TUTAJ, a nie w `tura._oddaj_konsultantowi`, żeby objąć TAKŻE
    handoff wywołany przez sam model (narzędzie `oddaj_czlowiekowi`) — inaczej
    najczęstsze wyjście handoffowe zostałoby jedynym bez notatki.

    N7 (rerecenzja): IDEMPOTENTNE w obrębie tury. Model potrafi wołać
    `oddaj_czlowiekowi` i przy tym napisać pożegnanie — wtedy tura nie zmienia
    stanu biznesowego i bezpiecznik braku postępu (`tura.py`) oddaje rozmowę
    DRUGI RAZ: druga notatka, druga wiadomość i drugie przełączenie statusu
    rozmowy, która jest już w 'open' i należy do człowieka. Drugie wywołanie w
    tej samej turze nie robi więc nic i melduje sukces — z punktu widzenia
    wołającego cel („rozmowa jest u konsultanta") jest osiągnięty."""
    from config import BOT_PRO_CW_AGENT_TOKEN
    from core.chatwoot import cw_bot_handoff
    from bots_pro import notatki
    biezacy = conv_id()
    if handoff_w_turze():
        log("stan: rozmowa juz oddana w tej turze — pomijam powtorny handoff "
            "(conv %s, powod=%r)" % (biezacy, powod))
        return {"ok": True, "powod": powod, "pominiety": True}
    # T1 (telemetria lejka): `handoff` emitujemy WYŁĄCZNIE TUTAJ, mimo że
    # oddanie rozmowy ma dwa wejścia — `tura._oddaj_konsultantowi` (bezpieczniki
    # tury: limit tur, brak postępu, guardraile) i sam model przez narzędzie
    # `oddaj_czlowiekowi` / `przygotuj_zamowienie`. To miejsce jest jedynym, przez
    # które przechodzą OBA, więc żadne wyjście handoffowe nie wypada z telemetrii.
    #
    # Podwójne liczenie rozwiązuje się bez nowej flagi turowej: `tura.
    # _oddaj_konsultantowi` woła tę funkcję, a ona ma OD N7 bramkę
    # `handoff_w_turze()` kilka linii wyżej — drugie oddanie tej samej rozmowy w
    # tej samej turze kończy się `return` PRZED tym miejscem. Jedna tura = co
    # najwyżej jedno zdarzenie `handoff`, i to bez dokładania stanu, który i tak
    # przebudowuje osobne zadanie.
    #
    # PRZED notatką i przed przełączeniem statusu — dokładnie ta sama kolejność
    # i to samo uzasadnienie co w starym silniku (`bots.quotebot._do_handoff`,
    # LS-08): telemetria ma zostać nawet wtedy, gdy sama wysyłka do Chatwoota
    # padnie. Dlatego logujemy fakt DECYZJI o oddaniu rozmowy, a nie jej
    # powodzenie — powodzenie widać w `ok` zwracanym niżej i w logu `tura.py`.
    log_event(biezacy, "handoff", {"powod": powod})
    notatki.notatka_stanu(biezacy, powod)
    udane = cw_bot_handoff(biezacy, token=BOT_PRO_CW_AGENT_TOKEN)
    oznacz_handoff_w_turze()
    return {"ok": bool(udane), "powod": powod}


def zapamietaj_wycene(wynik):
    """Trwale zapisuje identyfikator i publiczny link wyceny zwróconej przez CRM
    (U3). Wołane po `create_quote` i po `update_quote`.

    Nieudany wynik NIE nadpisuje niczego — inaczej nieudana korekta skasowałaby
    link do wyceny, którą klient już dostał. `quote_saved` ustawiamy dopiero tu,
    bo dopiero teraz istnieje obiekt wyceny w CRM; `migawka_postepu` czyta obie
    kolumny, więc zapis wyceny jest wreszcie WIDOCZNY jako postęp rozmowy (dotąd
    bezpiecznik „brak postępu" mógł oddać rozmowę człowiekowi zaraz po
    najcenniejszym kroku)."""
    if not (isinstance(wynik, dict) and wynik.get("ok")):
        return
    kolumny = {}
    if wynik.get("edit_uuid"):
        kolumny["quote_edit_uuid"] = wynik["edit_uuid"]
    if wynik.get("public_url"):
        kolumny["quote_public_url"] = wynik["public_url"]
    if kolumny:
        kolumny["quote_saved"] = 1
        zapisz_stan(**kolumny)


# R4: rozmowy, dla ktorych `zapisz_wycene` WLASNIE wisi na `create_quote`.
# Zbior w pamieci procesu, pod `zamek_stanu` — dokladnie ta sama konstrukcja i
# to samo ryzyko resztkowe co przy samym zamku (patrz jego komentarz: drugi
# proces albo drugi worker CICHO cofa te ochrone). Do bazy nie idzie, bo to stan
# JEDNEJ trwajacej operacji, a nie decyzja biznesowa majaca przezyc restart:
# po restarcie mostka zadne `create_quote` juz nie leci, wiec pusty zbior jest
# poprawna odpowiedzia.
_wyceny_w_toku = set()


def rezerwuj_zapis_wyceny():
    """Rezerwuje prawo do zalozenia wyceny w CRM dla biezacej rozmowy.
    Zwraca False, gdy wycena juz istnieje ALBO wlasnie powstaje.

    R4: bramka `WYCENA_JUZ_ZAPISANA` czytala sam `zapisana_wycena()` — czyli
    stan bazy — i robila to PRZED wyjsciem na `crm_calc.create_quote` (HTTP,
    timeout 30 s), a wynik zapisywala dopiero PO powrocie. Miedzy sprawdzeniem
    a zapisem nie bylo NICZEGO, wiec dwa rownolegle wywolania z jednego kroku
    modelu (SDK odpala narzedzia w watkach) przechodzily OBA. ZMIERZONE, 15
    przebiegow pod limitami produkcji: dwie wyceny w CRM w 15/15, z czego jedna
    OSIEROCONA — jest w CRM, `pro_stan` trzyma druga, klient dostaje link tylko
    do jednej. Docstring narzedzia zabrania tego wprost, ale zakaz w docstringu
    to dyscyplina promptu, a nie bramka.

    Sprawdzenie bazy i zaznaczenie rezerwacji dzieja sie w JEDNEJ sekcji
    krytycznej — inaczej przesunelibysmy okno, zamiast je zamknac.

    Zwolnienie: patrz `zwolnij_zapis_wyceny`."""
    with zamek_stanu:
        biezacy = _wymagany_conv_id()
        if zapisana_wycena().get("edit_uuid") or biezacy in _wyceny_w_toku:
            return False
        _wyceny_w_toku.add(biezacy)
        return True


def zwolnij_zapis_wyceny():
    """Zdejmuje rezerwacje z `rezerwuj_zapis_wyceny`.

    Wolane BEZWARUNKOWO po powrocie z CRM, takze po sukcesie — i to nie jest
    przeoczenie. Gdy wycena powstala, `zapamietaj_wycene` zdazylo juz zapisac
    `quote_edit_uuid`, wiec pojedynczosci pilnuje dalej bramka na BAZIE (ta
    przezywa restart procesu, czego zbior w pamieci nie potrafi). Gdy nie
    powstala — model ma prawo sprobowac jeszcze raz, a wieczna rezerwacja
    zamknelaby mu te droge na zawsze. Przy okazji zbior nie rosnie o jeden wpis
    na kazda rozmowe az do restartu."""
    with zamek_stanu:
        _wyceny_w_toku.discard(conv_id())


def zapisana_wycena():
    """`{"edit_uuid": ..., "public_url": ...}` zapisanej wyceny; `{}` gdy jej nie ma."""
    polaczenie = db()
    try:
        wiersz = polaczenie.execute(
            "SELECT quote_edit_uuid, quote_public_url FROM pro_stan WHERE conv_id=?",
            (conv_id(),)).fetchone()
    finally:
        polaczenie.close()
    if not wiersz:
        return {}
    surowe = {"edit_uuid": wiersz["quote_edit_uuid"],
              "public_url": wiersz["quote_public_url"]}
    return {k: v for k, v in surowe.items() if v}


def oznacz_dostawe_niedopisana(niedopisana=True):
    """Zaznacza (albo zdejmuje) blokadę „wycena w CRM nie ma dostawy, którą
    klient potwierdził" — R1.

    `zapisz_wycene` tworzy wycenę POST-em, który nie przyjmuje kuriera, i
    dopisuje dostawę osobnym PUT-em. Gdy ten PUT padnie, w CRM leży wycena
    TAŃSZA niż to, co klient potwierdził. Wypuszczenie linku do niej byłoby
    dokładnie tą dziurą, którą U4 zamykało (klient potwierdza cenę z dostawą,
    widzi cenę bez niej), więc `link_do_checkoutu` odmawia, dopóki flaga stoi."""
    zapisz_stan(quote_dostawa_niedopisana=1 if niedopisana else 0)


def dostawa_niedopisana():
    """Czy zapisana wycena jest niekompletna o dostawę (patrz wyżej)."""
    polaczenie = db()
    try:
        wiersz = polaczenie.execute(
            "SELECT quote_dostawa_niedopisana FROM pro_stan WHERE conv_id=?",
            (conv_id(),)).fetchone()
    finally:
        polaczenie.close()
    return bool(wiersz and wiersz["quote_dostawa_niedopisana"])


def pokazana_kwota():
    """Kwota, którą klient FAKTYCZNIE zobaczył w ostatnim podsumowaniu — albo
    None, gdy żadne podsumowanie do niego nie doszło (Z4).

    Zapisuje ją `podsumowanie.wyslij()` w TYM SAMYM `zapisz_stan`, co
    `oczekiwany_podpis`, czyli DOPIERO po udanej wysyłce (U1) — kwota z
    podsumowania, które utknęło na błędzie Chatwoota, nie ma prawa tu trafić.

    NIE jest to „aktualna cena" i nie wolno jej tak używać: to zapis
    historyczny, świadomie NIE czyszczony przy zmianie pozycji (inaczej
    `_zmien_pozycje` kasowałoby jedyny ślad tego, co klient widział, a właśnie
    po to ta kolumna istnieje). Wychodzi WYŁĄCZNIE do prywatnej notatki dla
    konsultanta i nie wchodzi do rejestru G1 — guardrail nadal zna tylko to, co
    policzył kalkulator."""
    polaczenie = db()
    try:
        wiersz = polaczenie.execute(
            "SELECT pokazana_kwota FROM pro_stan WHERE conv_id=?",
            (conv_id(),)).fetchone()
    finally:
        polaczenie.close()
    return wiersz["pokazana_kwota"] if wiersz else None


def cytat_potwierdzenia():
    """Dosłowny fragment, którym klient potwierdził podsumowanie — albo None.
    Do notatki dla konsultanta (U7): człowiek przejmujący rozmowę ma widzieć,
    CZY i CZYM klient się zgodził, nie tylko że bot uznał zgodę za ważną."""
    polaczenie = db()
    try:
        wiersz = polaczenie.execute(
            "SELECT potwierdzenie_cytat FROM pro_stan WHERE conv_id=?",
            (conv_id(),)).fetchone()
    finally:
        polaczenie.close()
    return wiersz["potwierdzenie_cytat"] if wiersz else None


def link_do_checkoutu(edit_uuid=""):
    """Publiczny link, pod którym klient obejrzy wycenę i domknie zamówienie.

    U3: zwracamy `public_url`, nie sam identyfikator — tak mówi specyfikacja
    (wiersz 442), i tak wygląda kontrakt docstringu narzędzia („link do strony").
    Model nie zna adresu bazowego CRM ani publicznego tokenu wyceny (to NIE jest
    `edit_uuid`), więc z samego identyfikatora nie da się złożyć adresu — mógłby
    go tylko zmyślić albo powtórzyć link sprzed kilku tur.

    `edit_uuid` jest opcjonalny: brak argumentu bierze wycenę zapisaną w stanie
    rozmowy. Podany identyfikator INNY niż zapisany jest błędem — na rozmowę
    przypada jedna wycena (patrz docstring `zapisz_wycene`), więc rozjazd znaczy,
    że model pomylił identyfikator, a nie że są dwie wyceny."""
    zapisana = zapisana_wycena()
    uuid_wyceny = zapisana.get("edit_uuid") or edit_uuid or None
    if not uuid_wyceny:
        return {"ok": False, "error": "Brak zapisanej wyceny — najpierw ją zapisz."}
    if edit_uuid and zapisana.get("edit_uuid") and edit_uuid != zapisana["edit_uuid"]:
        return {"ok": False, "error": "INNA_WYCENA",
                "wskazowka": "Ta rozmowa ma zapisaną inną wycenę. Wywołaj to narzędzie "
                             "bez edit_uuid, żeby dostać link do właściwej."}
    if dostawa_niedopisana():
        # R1: wycena JEST w CRM, ale bez dostawy, którą klient potwierdził —
        # link pokazałby mu inną (niższą) cenę niż ta, na którą się zgodził.
        return {"ok": False, "error": "WYCENA_BEZ_DOSTAWY",
                "wskazowka": "Wyceny w CRM nie udało się uzupełnić o koszt dostawy, "
                             "więc link pokazałby cenę BEZ wysyłki. Rozmowa jest już "
                             "u konsultanta — nie podawaj klientowi żadnego adresu, "
                             "napisz tylko, że konsultant domknie zamówienie."}
    if not zapisana.get("public_url"):
        return {"ok": False, "error": "BRAK_LINKU",
                "wskazowka": "Nie mam publicznego linku do tej wyceny — zapisz ją "
                             "(zapisz_wycene) albo zaktualizuj (popraw_wycene), a link "
                             "przyjdzie z CRM. NIE układaj adresu samodzielnie."}
    return {"ok": True, "edit_uuid": uuid_wyceny,
            "public_url": zapisana["public_url"]}


class BladOdczytuStanu(Exception):
    """Statusu rozmowy albo jej historii nie dało się odczytać (sieć/Chatwoot) —
    PRZEJŚCIOWY błąd. `.retryable = True` jawnie (nie polegamy na hierarchii
    wyjątków `requests`/`ConnectionError`, która i tak NIE pokrywa np.
    `requests.exceptions.ConnectionError` — ten nie dziedziczy po wbudowanym
    `ConnectionError`), żeby `quote_worker._klasyfikuj_retryable` (Task 7, W3
    code review) zakwalifikowało to jako retry niezależnie od zawężenia dla
    persony bota (K2 code review) — patrz `wolno_prowadzic_rozmowe` niżej."""
    retryable = True


def _czlowiek_juz_sie_odezwal(conv_id):
    """Odczyt sticky-bita (N2, code review runda 2) — NIE przez kontekst `conv_id()`
    (contextvar), bo ta funkcja jest wołana PRZED `stan.ustaw_kontekst` (patrz
    `tura.uruchom`). Konto conv_id idzie więc jawnym parametrem, jak w reszcie
    tego modułu przy podobnych wywołaniach spoza tury (np. `handoff`)."""
    polaczenie = db()
    try:
        wiersz = polaczenie.execute(
            "SELECT czlowiek_odezwal_sie FROM pro_stan WHERE conv_id=?", (conv_id,)).fetchone()
    finally:
        polaczenie.close()
    return bool(wiersz and wiersz["czlowiek_odezwal_sie"])


def _oznacz_czlowiek_odezwal_sie(conv_id):
    polaczenie = db()
    try:
        polaczenie.execute(
            "INSERT INTO pro_stan(conv_id, czlowiek_odezwal_sie) VALUES(?, 1) "
            "ON CONFLICT(conv_id) DO UPDATE SET czlowiek_odezwal_sie=1", (conv_id,))
        polaczenie.commit()
    finally:
        polaczenie.close()


def wolno_prowadzic_rozmowe(conv_id):
    """Bramka ciszy po handoffie (Task 7, brief o niej nie wspomina — rozstrzygnięcie
    właściciela zadania; przepisana w rundzie poprawek 1 i 2 po code review —
    K1/W3, potem N2).

    Sam status "pending" NIE wystarcza jako bramka: w Chatwoocie "Oczekująca"
    (pending) to jednocześnie stan startowy (bot jeszcze się nie odezwał) I zwykły
    "snooze" agenta — agent może ręcznie zaparkować rozmowę w pending PO WŁASNEJ
    publicznej odpowiedzi (np. czekając na klienta). Dokładnie to wydarzyło się
    w audycie (rozmowa #1316): agentka odpisała klientowi ("nie robimy naturalnych
    krawędzi"), a godzinę później bot podjął rozmowę od nowa i jej zaprzeczył.
    Stary silnik (bots/quotebot.py:_wolno_prowadzic_rozmowe) ma dokładnie tę lukę
    — sprawdza WYŁĄCZNIE status.

    K1 (code review, runda 1): PIERWSZA wersja tej funkcji sprawdzała, kto napisał
    OSTATNIĄ publiczną wiadomość — ale tura Dębusia Pro jest ZAWSZE wyzwalana
    świeżą wiadomością `incoming` klienta (webhooks.py + okno ciszy w
    quote_intake), więc w momencie sprawdzania bramki ostatnią wiadomością jest
    PRAWIE ZAWSZE wiadomość klienta, niezależnie od tego, czy wcześniej odpisał
    już agent. Warunek "kto mówił ostatni" był więc martwy — sekwencja
    [klient, agent, klient] (dokładnie #1316: agent odpisał, klient napisał
    później) dawała True (bot mówi), mimo że agent już się włączył.

    Poprawka: bramka sprawdza, czy w PUBLICZNEJ historii rozmowy W OGÓLE
    pojawiła się wiadomość człowieka-agenta (sender.type == "user" w Chatwoocie —
    w odróżnieniu od klienta "contact" i samego bota "agent_bot"), niezależnie od
    pozycji w historii i niezależnie od ewentualnych wiadomości `activity`
    (systemowych, bez sender) między nią a wiadomością wyzwalającą. Gdy human
    KIEDYKOLWIEK odpisał publicznie w tej rozmowie, bot milczy TRWALE (dopóki
    ktoś ręcznie nie przypnie rozmowy z powrotem do bota w Chatwoocie) — to
    świadomie zachowawcze: koszt fałszywego alarmu (bot niepotrzebnie milczy,
    mimo że agent tylko przelotnie coś napisał) jest dużo niższy niż koszt
    #1316 (bot zaprzecza agentowi). Notatki prywatne (private=True) są POMIJANE
    — wewnętrzna notatka między agentami nie jest publiczną odpowiedzią klientowi.

    Zapytanie o historię idzie PRZEZ `core.chatwoot.cw` (surowe wywołanie API),
    NIE przez `cw_messages` — `cw_messages` celowo gubi nadawcę (mapuje tylko
    role user/assistant) i pomija wiadomości z pustą treścią (np. sam załącznik
    obrazu bez tekstu), co ukryłoby realną odpowiedź agenta przed tą bramką.

    W3 (code review, runda 1): błąd odczytu statusu/historii RZUCA
    `BladOdczytuStanu` (retryable=True), NIE zwraca cicho False. Pierwsza wersja
    zwracała False przy błędzie — z punktu widzenia `tura.uruchom` to WYGLĄDA
    identycznie jak legalna blokada (human już rozmawia), więc `quote_worker`
    oznaczał wiersz kolejki jako 'sent' i CICHO GUBIŁ wiadomość klienta przy
    zwykłym, przejściowym błędzie sieci. Rzucanie (jak w starym silniku, ten sam
    powód) oddaje decyzję workerowi: retry z backoffem, a nie zgadywanie tutaj.
    `cw()` sam NIE rzuca na odpowiedź błędu (nie robi `raise_for_status`) — gdy
    ciało błędu sparsuje się jako JSON bez klucza "payload", `.get("payload", [])`
    cicho dałoby `[]` (pusta historia -> bramka pozwala), więc status HTTP jest
    sprawdzany JAWNIE (`r.ok`) przed odczytem `payload`.

    N2 (code review, runda 2): semantyka "czy CZŁOWIEK KIEDYKOLWIEK się odezwał"
    (K1) niejawnie zakłada, że pobrana strona `payload` to CAŁA historia — ale
    endpoint `/messages` jest stronicowany i bez parametru strony zwraca tylko
    najświeższą stronę. Gdy po odpowiedzi agenta narośnie dość kolejnych
    wiadomości KLIENTA (np. kilka dni niecierpliwych ponagleń), odpowiedź agenta
    wypadnie z pobranej strony i bramka wróci na True — bot znów zaprzeczy
    agentowi, dokładnie ten sam błąd co #1316, tylko odroczony w czasie zamiast
    natychmiastowy. Rozwiązanie NIEZALEŻNE od rozmiaru strony: sticky bit
    `czlowiek_odezwal_sie` w `pro_stan`, ustawiany RAZ (`_oznacz_czlowiek_odezwal_sie`)
    gdy wiadomość agenta zostanie znaleziona, i sprawdzany PRZED sięgnięciem po
    historię (`_czlowiek_juz_sie_odezwal`) — raz ustawiony, blokuje TRWALE bez
    ponownego skanowania /messages. To jednocześnie ogranicza liczbę wywołań API
    Chatwoota na turę (odmowa scalenia statusu+historii z rundy 1 pozostaje
    słuszna — patrz raport — ale po ustawieniu sticky bita druga rozmowa idzie
    już wyłącznie po statusie, bez /messages w ogóle)."""
    from core.chatwoot import cw_conv_status, cw

    status = cw_conv_status(conv_id)
    if status is None:
        raise BladOdczytuStanu(
            "stan: nie mozna odczytac statusu rozmowy (conv %s)" % conv_id)
    if status != "pending":
        return False
    if _czlowiek_juz_sie_odezwal(conv_id):
        return False
    try:
        odpowiedz = cw("GET", "/conversations/%s/messages" % conv_id)
        if not odpowiedz.ok:
            raise BladOdczytuStanu(
                "stan: HTTP %s przy odczycie historii rozmowy (conv %s)"
                % (odpowiedz.status_code, conv_id))
        wiadomosci = odpowiedz.json().get("payload", [])
    except BladOdczytuStanu:
        raise
    except Exception as e:
        raise BladOdczytuStanu(
            "stan: nie mozna odczytac historii rozmowy (conv %s): %r" % (conv_id, e)) from e
    for wiadomosc in wiadomosci or []:
        if wiadomosc.get("private"):
            continue
        if (wiadomosc.get("sender") or {}).get("type") == "user":
            _oznacz_czlowiek_odezwal_sie(conv_id)
            return False
    return True


def ostatnia_wiadomosc_klienta():
    """Treść ostatniej wiadomości przychodzącej — materiał do weryfikacji cytatu."""
    from config import BOT_HISTORY_LIMIT
    from core.chatwoot import cw_messages
    for wiadomosc in reversed(cw_messages(conv_id(), BOT_HISTORY_LIMIT) or []):
        if wiadomosc.get("role") == "user":
            return wiadomosc.get("text") or ""
    return ""


def rozmowy_z_pokazana_cena(conv_ids):
    """Które z podanych rozmów Pro pokazały już klientowi cenę — zbiór conv_id.

    JEDYNA funkcja w tym module czytająca WIELE rozmów naraz i jedyna, która
    NIE bierze conv_id z kontekstu: woła ją `hot_lead_sweeper`, który chodzi po
    wszystkich otwartych rozmowach kanału i nie prowadzi żadnej z nich (N11).
    Zbiorczo, JEDNYM zapytaniem — odpytywanie bazy per rozmowa skalowałoby się
    z długością kolejki agenta.

    Sygnałem jest `oczekiwany_podpis`, nie kolumna `priced` (ta istnieje
    w schemacie, ale silnik Pro nigdy jej nie zapisuje). `oczekiwany_podpis`
    zapisuje `podsumowanie.wyslij()` DOPIERO po udanej wysyłce zestawienia
    z ceną — czyli dokładnie w tym momencie, w którym stary silnik ustawiał
    `priced` (bots/quotebot.py, tuż po `cw_agent_reply` z ceną). To ten sam
    fakt w obu silnikach: „klient zobaczył cenę".

    ZNANA LUKA: cena wypowiedziana przez model w wolnym tekście, bez wołania
    `wyslij_podsumowanie`, nie ustawia `oczekiwany_podpis` i taka rozmowa tu nie
    wejdzie. Alternatywą byłby niepusty rejestr `pro_kwoty`, ale ten mówi tylko,
    że KALKULATOR coś policzył — bot mógł tej kwoty nigdy nie wypowiedzieć,
    a notatka sweepera twierdzi wprost, że klient wycenę dostał."""
    identyfikatory = [c for c in (conv_ids or []) if c is not None]
    if not identyfikatory:
        return set()
    polaczenie = db()
    try:
        wiersze = polaczenie.execute(
            "SELECT conv_id FROM pro_stan WHERE conv_id IN (%s) "
            "AND oczekiwany_podpis IS NOT NULL AND oczekiwany_podpis != ''"
            % ",".join("?" * len(identyfikatory)), identyfikatory).fetchall()
    finally:
        polaczenie.close()
    return {w["conv_id"] for w in wiersze}
