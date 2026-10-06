# -*- coding: utf-8 -*-
"""Zapis przyrostowy zamówień z BaseLinkera do tabel sales_*.

DLACZEGO TEN PLIK ISTNIEJE
==========================
Do 22.09.2026 do `sales_*` nie pisało NIC poza jednorazowym
`scripts/backfill_sales_tables.py`. Ręczna synchronizacja „Pobierz zamówienia"
zapisywała wyłącznie do starej tabeli `baselinker_reports_orders`. Nowa
zakładka zamarzłaby więc na dniu backfillu i nie zastąpiłaby Excela.

JEDEN MECHANIZM, DWA PUNKTY WYZWALANIA (decyzja użytkownika 22.09.2026)
=======================================================================
    „Pobieranie tutaj = zapis tylko do analityki.
     Pobieranie na produkcji = zapis w produkcji + analityka."

Ten moduł jest tym jednym mechanizmem. Wołają go:
  * `SyncService.process_orders_with_priority_logic` (modules/production) —
    OSŁONIĘTY try/except, bo produkcja to tor krytyczny (tablety na hali);
  * `POST /reports/api/arkusz/pobierz` — wyłącznie analityka.

CZEGO TEN MODUŁ NIE DOTYKA
==========================
Kolumn, których BaseLinker nie zna: `client_origin`, `own_transport`,
`picked_up` oraz sześciu kolumn rozbicia wpłat (`advance_*`, `paid_*`).
Zbiory „pola z BL" i „pola tylko CRM" są rozłączne i dlatego konflikt
edycja↔synchronizacja nie istnieje — patrz specyfikacja §5.2.

Jeden wyjątek, i to tylko w jedną stronę: PUSTE `client_origin` zapis
wypełnia nazwą źródła (słownik BaseLinkera albo produkcja — partia E, punkt
E6, `_pochodzenie_klienta`). Wartości niepustej nie rusza nigdy, więc ręczna
praca w Arkuszu dalej przeżywa każdą synchronizację.

SALDO
=====
Saldo i wpłata istnieją WYŁĄCZNIE na poziomie zamówienia. `mapuj_pozycje`
nie zwraca ich w ogóle i test tego pilnuje. To ta sama pułapka, która
w poprzedniku zawyżała `SUM(balance_due)` 7,58-krotnie.

WŁASNOŚĆ SESJI (przebudowa 22.09.2026 — znalezisko KRYTYCZNE)
=============================================================
`zapisz_zamowienia` pracuje na WŁASNEJ sesji bazodanowej, którą sama zakłada
i sama zamyka, i NIGDY nie woła `commit()` ani `rollback()` na `db.session`.

Powód jest jeden i jest twardy: kontrola adwersaryjna UDOWODNIŁA WYKONANIEM,
że poprzednie rozwiązanie kasuje dane produkcji. Pętla produkcji
(`SyncService.process_orders_with_priority_logic`) ma gałęzie, które ani nie
commitują, ani nie rollbackują — „Brak produktów do zapisania"
(sync_service.py:884) i `except Exception as item_error` (:825) — a w tym
momencie `_create_production_product_from_data` zrobiło już
`db.session.add(ProductionOrder)` + `db.session.flush()` (:1689-1702), zaś
`ProductionConfiguration.find_or_create` flushuje w models.py:121-122.
Praca produkcji jest więc ZFLUSHOWANA I NIEZACOMMITOWANA, a `rollback()`
analityki na współdzielonej sesji ją KASOWAŁ. Zmierzone: w `prod_orders`
zostawało [50854536] zamiast [50854536, 50854537], a przy paczce
jednozamówieniowej tabela była pusta. Działało też w drugą stronę: udany
commit analityki ZATWIERDZAŁ pracę produkcji, której produkcja świadomie
nie zatwierdziła.

Poprzedni strażnik (`sesja_bez_cudzych_zmian`, usunięty) nie miał jak
zadziałać: patrzył na `db.session.new/dirty/deleted`, a po `flush()` te
zbiory są PUSTE. Przepuszczał więc dokładnie ten przypadek, przed którym
miał bronić.

Konsekwencje praktyczne tej decyzji:
  * `Model.query` rozwiązuje się przez rejestr `scoped_session`, czyli
    ZAWSZE przez `db.session` — dlatego w tym module i w `dedup.py` jest
    wszędzie `sesja.query(Model)`, a sesja idzie w parametrze;
  * własna sesja to jedno dodatkowe połączenie do MySQL-a (limit 40 na
    użytkownika) na czas jednej synchronizacji — zamykane jawnie
    w `finally`, także przy wyjątku;
  * listener audytu `prod_product_events` jest podpięty pod `db.session`
    (product_events.py:322), więc nasza sesja go nie odpala. Nie ma to
    znaczenia: analityka pisze wyłącznie do `sales_*`, a `prod_orders`
    czyta.
"""

from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Dict, List, Optional

import pytz
from sqlalchemy import func

from extensions import db
from modules.logging import get_structured_logger
from modules.reports.dedup import (
    dowiaz_lead, norm_email, norm_nip, norm_phone, znajdz_lub_utworz_klienta,
    zbuduj_indeks_leadow,
)
from modules.reports.fields import POLA, Poziom, Zrodlo
from modules.reports.filters import warunek_sprzedazy
from modules.reports.models_sales import SalesClient, SalesOrder, SalesOrderItem
from modules.reports.parser import ProductNameParser
from modules.reports.service import STATUSY_BASELINKER, czy_usluga, kwota_netto
from modules.reports.utils import PostcodeToStateMapper

logger = get_structured_logger('reports.ingest')

# Identyfikatory pól dodatkowych BaseLinkera. Te same, które czyta stara
# synchronizacja (service.py:1352 i :1804).
POLE_OPIEKUN = '105623'
POLE_TYP_CENY = '106169'

_VAT = Decimal('1.23')
_ZERO = Decimal('0')

# ZEGAR. Ta sama konwencja, co `modules/reports/analiza_service.py`
# (commit a5c68aa) i `modules/production/models.py`: kontener i serwer
# produkcyjny chodzą na UTC, a firma pracuje w Polsce. Patrz
# `_data_z_timestampu` — bez tego jedna kolumna `date_created` niosłaby
# dwa różne zegary.
STREFA_LOKALNA = pytz.timezone('Europe/Warsaw')

# Tekst, który stara synchronizacja wpisywała przy braku opiekuna. Zostaje
# dosłownie: 7938 wierszy backfillu ma tę wartość, a None zrobiłby drugi
# kubełek dla tego samego zjawiska na karcie „Sprzedaż według opiekuna".
BRAK_OPIEKUNA = 'Brak danych'

# Kolumny POZYCJI, których BaseLinker nie zna — czyli te, których
# synchronizacja nie ma prawa nadpisać. Lista NIE jest tu wypisana ręcznie:
# bierze się wprost z rejestru pól (`fields.py`), więc dopisanie kolumny
# CRM-owej do rejestru automatycznie ją tu chroni, a przeniesienie kolumny
# do BaseLinkera automatycznie ochronę zdejmuje. Ręczna kopia listy
# rozjechałaby się z rejestrem przy pierwszej zmianie.
#
# Skąd te kolumny w ogóle są CRM-owe: parser czyta je z NAZWY produktu,
# a `setOrderProductFields` nazwy nie ustawia (komentarz w fields.py:216).
KOLUMNY_POZYCJI_TYLKO_CRM = frozenset(
    nazwa for nazwa, pole in POLA.items()
    if pole.poziom is Poziom.POZYCJA and pole.zrodlo is Zrodlo.CRM
)

# Wymiary — po ich zmianie trzeba przeliczyć kolumny pochodne.
WYMIARY_POZYCJI = ('length_cm', 'width_cm', 'thickness_cm')

# Kolumny pozycji liczone Z WYMIARÓW (patrz `pochodne_wymiarowe`).
KOLUMNY_POCHODNE_POZYCJI = ('volume_per_piece', 'total_volume',
                            'total_surface_m2', 'price_per_m3')

# SALDO NIE PATRZY NA GRUPĘ PRODUKTOWĄ (fala 6). Stała `GRUPY_POZA_SALDEM`,
# która stała tu do 22.09.2026, wykluczała usługi z netto branego do salda —
# uzasadnienie tamtego wyboru zostało OBALONE POMIAREM, patrz `oblicz_saldo`.
# Jedyne poprawne wykluczenie usług siedzi w `aggregates._GRUPY_BEZ_OBJETOSCI`
# i dotyczy METRÓW SZEŚCIENNYCH (usługa nie ma objętości), nie pieniędzy.


def nowa_sesja_analityki():
    """Świeża, WŁASNA sesja bazodanowa analityki. Wołający ją zamyka.

    Fabryka Flask-SQLAlchemy (`db.create_session`) zamiast gołego
    `sessionmaker(bind=db.engine)`: daje tę samą klasę sesji i to samo
    rozwiązywanie bindów, co `db.session`, tylko poza rejestrem
    `scoped_session`. Dzięki temu commit i rollback tej sesji dotyczą
    WYŁĄCZNIE wierszy analityki — patrz „WŁASNOŚĆ SESJI" w docstringu modułu.
    """
    return db.create_session({})()


def _jest_tabela(nazwa: str, sesja=None) -> bool:
    """Czy tabela `nazwa` istnieje w aktualnie podłączonej bazie.

    ODCHYLENIE OD PLANU (Zadanie 6): funkcja jest wymieniona w sekcji
    „Consumes" Zadania 6 jako gotowa zależność z Zadań 2-4, ale te zadania
    nie wylądowały jeszcze na tej gałęzi (sprawdzone: brak jej w repo przed
    tym commitem). Arkusz potrzebuje jej już teraz, żeby kolumny produkcyjne
    nie wywalały zapytania, gdy moduł produkcji jest niedostępny (osobny
    etap wdrożenia) — ten sam problem, który w `modules/production/services/
    product_events.py:_table_exists` rozwiązuje `sqlalchemy.inspect(engine)
    .has_table(...)`. Ten sam wzorzec, bez cache'owania: w przeciwieństwie
    do listenera `before_flush` (gorąca ścieżka przy KAŻDYM zapisie w całej
    aplikacji) to jedno sprawdzenie na żądanie do arkusza.

    ZNALEZISKO WAŻNE (przegląd Zadania 3): `sa_inspect(db.engine)` otwiera
    NOWE logiczne połączenie z puli. Na SQLite in-memory + `StaticPool`
    (konwencja testów tego pakietu) to nowe połączenie dzieli surowe
    połączenie DB-API z sesją ORM-a — a zamknięcie go bez commita (tak robi
    `Inspector` po jednym zapytaniu) cicho ROLLBACKuje też NIEZACOMMITOWANĄ
    pracę tamtej sesji. W `zapisz_zamowienia` ta funkcja jest wołana RAZ na
    paczkę, PRZED pętlą zapisu — jedno flushnięte-ale-niescommitowane
    wstawienie sprzed wywołania (np. lead w teście) znikałoby bezpowrotnie.
    Na produkcyjnym MySQL-u z prawdziwym poolem połączeń tego efektu nie ma
    (nowe połączenie jest naprawdę osobne), stąd błąd był niewidoczny do tej
    pory. Zapytanie o `has_table` przez `db.session.connection()` używa
    połączenia JUŻ otwartego przez bieżącą transakcję sesji zamiast otwierać
    nowe, więc nie ma czego zamykać ani czego rollbackować.

    `sesja` — patrz „WŁASNOŚĆ SESJI" w docstringu modułu. Domyślnie
    współdzielona `db.session`, bo tak woła tę funkcję `arkusz_service.py`.
    """
    from sqlalchemy import inspect as sa_inspect

    from extensions import db

    aktywna = sesja if sesja is not None else db.session
    try:
        return sa_inspect(aktywna.connection()).has_table(nazwa)
    except Exception:
        return False


def _kwota(wartosc, miejsca: str = '0.01') -> Optional[Decimal]:
    """Decimal zaokrąglony do skali kolumny. None zostaje None."""
    if wartosc is None:
        return None
    return Decimal(str(wartosc)).quantize(Decimal(miejsca), rounding=ROUND_HALF_UP)


def _kwota_w_zakresie(wartosc, miejsca: str, cyfr_calkowitych: int,
                      kolumna: str = '') -> Optional[Decimal]:
    """Jak `_kwota`, ale wartość spoza zakresu kolumny daje None, nie wyjątek.

    ZNALEZISKO (przegląd Zadania 6): kolumny wyliczane w `sales_order_items`
    są wąskimi DECIMAL-ami — `price_per_m3` to DECIMAL(10,2), czyli maksimum
    99 999 999,99. Cena za metr sześcienny jest ilorazem, więc pozycja
    o znikomej objętości (źle sparsowany wymiar, próbka 1x1x0,1 cm) potrafi
    ten zakres przebić. MySQL w trybie ścisłym odrzuca wtedy CAŁY INSERT
    błędem 1264, a `zapisz_zamowienia` liczy to jako błąd całego zamówienia —
    jedna felerna pozycja wyrzuca z analityki komplet danych zamówienia.
    Zapisanie NULL-a zamiast przycięcia do 99 999 999,99 jest świadome:
    przycięta liczba weszłaby do średnich i wykresów jako fakt, a NULL mówi
    „nie wiadomo" i wypada z `SUM`/`AVG` tak samo jak brak wymiarów.

    NAJWIĘKSZA ZMIERZONA wartość na `woodpower_crm_local` to 227 366,28 zł/m3
    (7938 pozycji) — czyli dzisiejsze dane zakresu NIE przebijają. To jest
    zabezpieczenie przed awarią zapisu, nie naprawa istniejącej rozbieżności.
    """
    kwota = _kwota(wartosc, miejsca)
    if kwota is None:
        return None
    if abs(kwota) >= Decimal(10) ** cyfr_calkowitych:
        logger.warning('Wartosc poza zakresem kolumny - zapisuje NULL',
                       kolumna=kolumna, wartosc=str(kwota))
        return None
    return kwota


def _tekst(wartosc, limit: Optional[int] = None) -> Optional[str]:
    """Przycięty tekst albo None. Pusty napis to też None."""
    if wartosc is None:
        return None
    oczyszczony = str(wartosc).strip()
    if not oczyszczony:
        return None
    return oczyszczony[:limit] if limit else oczyszczony


def _tekst_zamowienia(wartosc, limit: Optional[int] = None) -> str:
    """Przycięty tekst dla kolumn poziomu zamówienia. Pusty napis, nie None.

    ZNALEZISKO WAŻNE (przegląd Zadania 1): w `sales_orders` po backfillu
    (3324 zamówienia) te kolumny NIE MAJĄ ani jednego NULL-a — stara
    synchronizacja zawsze pisała pusty napis, nigdy None (zmierzone:
    internal_order_number 128 wierszy '', delivery_state 296, email 224,
    phone 140, delivery_address 326, payment_method 91). `_tekst()` zwracał
    tu None, więc `aggregates.wg_wymiaru` (grupowanie po surowej kolumnie
    w SQL) rozbijało np. kartę „Województwo" na dwa wiersze pustki: 296
    starych z '' i nowe z NULL. Filtry (filters.py:207-209) są odporne na
    oba warianty, karty nie — więc mapper musi pisać tą samą stroną, co
    dane historyczne: '', nie None.
    """
    if wartosc is None:
        return ''
    oczyszczony = str(wartosc).strip()
    return oczyszczony[:limit] if limit else oczyszczony


def _calkowita(wartosc, domyslna: int = 1) -> int:
    try:
        return int(wartosc)
    except (TypeError, ValueError):
        return domyslna


def _data_z_timestampu(wartosc) -> Optional[date]:
    """Data z unixtime BaseLinkera, liczona w strefie Europe/Warsaw.

    Zero i śmieć dają None.

    ZNALEZISKO WAŻNE (przegląd Zadania 6): `datetime.fromtimestamp` BEZ strefy
    bierze zegar procesu, a kontener i serwer produkcyjny chodzą na UTC —
    podczas gdy fallback `_dzis()` (użyty, gdy zamówienie nie ma `date_add`)
    liczy już Europe/Warsaw (`analiza_service.dzis_lokalnie`, commit a5c68aa).
    Jedna kolumna `date_created` dostawała więc DWA RÓŻNE ZEGARY. Między
    północą a drugą w nocy czasu polskiego UTC jest jeszcze w dniu poprzednim,
    więc zamówienie złożone w nocy 19 września lądowało w sprzedaży
    18 września i nie zgadzało się z tym, co użytkownik widzi w BaseLinkerze
    ani z dniem, na który liczą się należności.
    """
    if not wartosc:
        return None
    try:
        return datetime.fromtimestamp(int(wartosc), STREFA_LOKALNA).date()
    except (TypeError, ValueError, OSError, OverflowError):
        return None


def _identyfikator(wartosc) -> Optional[int]:
    """JEDYNA normalizacja identyfikatora liczbowego z BaseLinkera.

    Zwraca int albo None. ZERO ZNACZY BRAK.

    ZNALEZISKO WAŻNE (kontrola adwersaryjna fali 5). Identyfikatory
    normalizowały się w tym module DWOMA różnymi sposobami i ta sama wartość
    dawała dwa wyniki:

      * numer zamówienia szedł przez `int(wartosc)`, więc `991.0` dawało 991;
      * `order_product_id` szedł przez `int(str(wartosc).strip())`, czyli
        `int('991.0')` — ValueError, a więc None.

    Skutek był asymetryczny i cichy: zamówienie zapisywało się poprawnie,
    ale jego pozycje traktowaliśmy jak BEZKLUCZOWE, czyli po regule 4
    („klucz albo nic") pomijaliśmy je przy każdej kolejnej synchronizacji.
    Stąd jedna funkcja i jedno miejsce, w którym ta decyzja żyje.

    ZERO TO BRAK (znalezisko WAŻNE, ta sama kontrola). Poprzednik tej funkcji
    po stronie pozycji zwracał dla '0' liczbę 0, a warunki w upsercie
    sprawdzają `klucz is None` — integracja, która wstawi 0 zamiast braku
    (a BaseLinker i pośrednicy tak robią), dawała jeden wspólny
    „identyfikator" dla WSZYSTKICH pozycji zamówienia, więc mieszały się one
    między sobą przy każdym przebiegu. Decyzja jest ta sama, co dla numeru
    zamówienia (patrz `_numer_bl`): 0 nie identyfikuje niczego.

    Ułamek obcinamy (`12.9` -> 12), bo tak liczył numer zamówienia od
    początku i tak zapisane są dzisiejsze dane — zmiana tej reguły
    przestawiłaby wiersze już leżące w bazie.
    """
    if wartosc is None:
        return None
    if isinstance(wartosc, int):
        # `int(...)` też dla `bool` — inaczej `True` wracałoby jako bool
        # i wchodziło do kolumny BIGINT jako wartość innego typu.
        return int(wartosc) or None
    if isinstance(wartosc, (float, Decimal)):
        try:
            return int(wartosc) or None
        except (ValueError, OverflowError, InvalidOperation):
            # NaN i nieskończoność — nie jest to identyfikator.
            return None
    tekst = str(wartosc).strip()
    if not tekst:
        return None
    try:
        return int(tekst) or None
    except (TypeError, ValueError):
        pass
    # Napisowa postać liczby z ułamkiem ('991.0' z JSON-a) — ta sama wartość,
    # co float, więc musi dać ten sam wynik.
    try:
        return int(Decimal(tekst)) or None
    except (ArithmeticError, ValueError, TypeError):
        return None


def _numer_bl(order: Dict) -> Optional[int]:
    """Numer zamówienia BaseLinkera albo None. NIGDY 0.

    ZNALEZISKO WAŻNE (przegląd Zadania 6): dawniej `_calkowita(order.get(
    'order_id'), 0)`, czyli brak numeru zapisywał się jako 0. Kolumna
    `sales_orders.baselinker_order_id` jest UNIQUE, więc PIERWSZE takie
    zamówienie zajmowało slot 0 na stałe, a DRUGIE wywracało zapis na
    duplikacie klucza zamiast zostać pominięte. Zamówienie bez identyfikatora
    BL jest po prostu niepoprawne i nie ma czego identyfikować przy kolejnej
    synchronizacji — `zapisz_zamowienia` pomija je i liczy.
    Ta sama decyzja, co w `scripts/backfill_sales_tables.py` (licznik
    `bez_numeru_bl`, wiersze świadomie NIE migrowane).

    Czytamy oba klucze, bo `getOrders` oddaje `order_id`, a część wywołań
    wewnątrz CRM-a podaje zamówienie pod `id`.

    Sama normalizacja siedzi w `_identyfikator` — tej samej, której używa
    `order_product_id` (patrz jej docstring, znalezisko WAŻNE fali 5).
    """
    return _identyfikator(order.get('order_id') or order.get('id'))


def _dzis() -> date:
    # Import leniwy: analiza_service ciągnie agregaty i pytz, a mapper ma się
    # dać zaimportować bez tego łańcucha.
    from modules.reports.analiza_service import dzis_lokalnie
    return dzis_lokalnie()


def typ_ceny(order: Dict) -> str:
    """'netto', 'brutto' albo '' — z custom_extra_fields[106169].

    Pusty napis znaczy „bez oznaczenia", co w całym CRM-ie jest traktowane
    jak BRUTTO. Wartość wpada wprost do kolumny `sales_orders.price_type`,
    która jest ENUM('netto','brutto',''), więc cokolwiek innego wywaliłoby
    zapis błędem 1265.
    """
    pola = order.get('custom_extra_fields') or {}
    wartosc = str(pola.get(POLE_TYP_CENY, '') or '').strip().lower()
    return wartosc if wartosc in ('netto', 'brutto') else ''


def _wojewodztwo(order: Dict) -> str:
    """Województwo w formie kanonicznej („Mazowieckie"), w razie potrzeby
    dorobione z kodu pocztowego.

    ZNALEZISKO KRYTYCZNE (przegląd Zadania 6): ten mapper sprowadzał wartość
    do MAŁYCH liter, powołując się na „wszystkie wiersze w bazie mają małe".
    To twierdzenie jest FAŁSZYWE i zmierzyłem to na `woodpower_crm_local`:
    `sales_orders` ma 3028 wierszy z WIELKIEJ litery i 0 z małej (plus 296
    pustych), `baselinker_reports_orders` — 6543 z wielkiej i 0 z małej.
    Formę kanoniczną Title Case wymusza w tych danych
    `BaselinkerReportOrder.normalize_delivery_state` (models.py:619), a taką
    samą zwracają OBIE ścieżki `PostcodeToStateMapper.auto_fill_state`:
    `normalize_state_name` dla wartości z BL i `get_state_from_postcode` dla
    dorabianej z kodu pocztowego (utils.py:74 `STATE_NORMALIZATION`).
    Zapisanie małych liter rozbiłoby wymiar „Województwo" na dwa wiersze
    dla tego samego regionu — `aggregates.wg_wymiaru` grupuje po surowej
    kolumnie w SQL, a MySQL grupuje po collation bazy, więc mieszanka
    „Mazowieckie"/„mazowieckie" jest tu groźna dokładnie w drugą stronę,
    niż zakładał poprzedni komentarz. Dlatego NIE wolno tu wołać `.lower()`
    ani `.title()` — bierzemy to, co zwraca wspólny normalizator.

    Nie do ustalenia -> pusty napis, nie None — patrz `_tekst_zamowienia`.
    """
    uzupelnione = PostcodeToStateMapper.auto_fill_state(
        order.get('delivery_postcode') or '', order.get('delivery_state') or '')
    return _tekst_zamowienia(uzupelnione or '', 50)


def _powierzchnia_m2(dlugosc, szerokosc, grubosc, ilosc: int) -> Optional[Decimal]:
    """Powierzchnia CAŁEGO prostopadłościanu (sześć ścian) w m², razy ilość.

    ZNALEZISKO KRYTYCZNE (przegląd Zadania 6): mapper liczył tu
    `(L/100) * (W/100) * ilość`, czyli JEDNĄ ścianę — a dane historyczne
    w TEJ SAMEJ kolumnie `total_surface_m2` niosą pole całego prostopadło-
    ścianu, liczone przez `BaselinkerReportOrder.calculate_surface_area`
    (models.py:431-462) wzorem `2 * (L*W + L*T + W*T) * ilość` na metrach.
    Zmierzone na `woodpower_crm_local` (7911 pozycji z wypełnioną kolumną):
    suma historyczna 19 096,25 m², wzór sześciościenny na tych samych
    wierszach — 19 096,25 m² co do grosza, a wzór jednościenny — 8 563,81 m².
    Po wdrożeniu ta sama kolumna niosłaby dwa nieporównywalne znaczenia
    i karta „Powierzchnia" pokazywałaby załamanie w dniu wdrożenia.

    BRAK GRUBOŚCI. Historyczna funkcja zwraca przy braku któregokolwiek
    wymiaru `0.0`, a w bazie 114 pozycji bez wymiarów dzieli się na 87 zer
    i 27 NULL-i — czyli dane historyczne same nie są tu jednorodne. Bierzemy
    None, bo tak samo zachowują się w tym mapperze `total_volume`
    i `price_per_m3` przy braku wymiarów, a dla `SUM` (kolumna jest miarą
    addytywną, `fields.py:253`) NULL i 0 są nierozróżnialne.
    """
    if dlugosc is None or szerokosc is None or grubosc is None:
        return None
    dlugosc_m = Decimal(str(dlugosc)) / 100
    szerokosc_m = Decimal(str(szerokosc)) / 100
    grubosc_m = Decimal(str(grubosc)) / 100
    if not (dlugosc_m and szerokosc_m and grubosc_m):
        return None
    jedna_sztuka = 2 * (dlugosc_m * szerokosc_m
                        + dlugosc_m * grubosc_m
                        + szerokosc_m * grubosc_m)
    return jedna_sztuka * ilosc


def pochodne_wymiarowe(dlugosc, szerokosc, grubosc, ilosc: int, wartosc_netto,
                       nazwa: Optional[str] = None) -> Dict[str, Optional[Decimal]]:
    """Cztery kolumny WYLICZANE pozycji, policzone z PODANYCH wymiarów.

    Wydzielone z `mapuj_pozycje`, bo liczą się w dwóch momentach i muszą dać
    ten sam wynik: przy mapowaniu świeżej pozycji z BaseLinkera oraz przy
    aktualizacji pozycji, której wymiary ktoś poprawił ręcznie w arkuszu
    (`_zaktualizuj_pozycje`). Wymiary są kolumną CRM-ową — parser czyta je
    z NAZWY produktu, a `setOrderProductFields` nazwy nie ustawia — więc po
    ręcznej poprawce jedynym prawdziwym źródłem wymiaru jest wiersz w bazie,
    nie nazwa z BaseLinkera.

    UWAGA: bliźniaczy wzór siedzi w `arkusz_zapis._przelicz_pochodne_pozycji`
    (ta sama arytmetyka, wejściem jest wiersz zamiast luźnych wartości).
    Tamten plik jest poza zakresem tej poprawki; zejście do jednej funkcji
    zostaje na osobne zadanie.
    """
    if dlugosc is not None and szerokosc is not None and grubosc is not None:
        # ZNALEZISKO WAŻNE (przegląd Zadania 1): liczymy wprost z wymiarów,
        # a nie z `rozbior['volume_per_piece']` zaokrąglonego przez parser
        # do 4 miejsc — kolumna i dane historyczne mają 6.
        objetosc_szt = ((Decimal(str(dlugosc)) / 100)
                        * (Decimal(str(szerokosc)) / 100)
                        * (Decimal(str(grubosc)) / 100))
        objetosc_ttl = objetosc_szt * ilosc
    elif nazwa:
        # ZNALEZISKO KRYTYCZNE (przegląd Zadania 1): bez trzech wymiarów
        # w nazwie parser nie zwraca objętości WCALE, a część towaru
        # (tarcica, deska) ma objętość podaną WPROST w nazwie, np.
        # „Tarcica jesionowa 0,96m3" — bez tego 14,2% objętości towaru
        # (50 wierszy, 46,099 m3 na woodpower_crm_local) wypadało z KPI
        # m3 i z price_per_m3. Stara synchronizacja czytała ją przez
        # analyze_product_for_volume_and_attributes z
        # analysis_type='volume_only' (service.py:1468-1480) — ta sama
        # ścieżka tutaj.
        from .routers import analyze_product_for_volume_and_attributes
        analiza = analyze_product_for_volume_and_attributes(nazwa)
        if analiza.get('analysis_type') == 'volume_only' and analiza.get('volume'):
            # Objętość z nazwy to już objętość CAŁEJ pozycji — NIE mnożyć
            # przez ilość (service.py:414-417, komentarz „NIE MNÓŻ!").
            objetosc_ttl = Decimal(str(analiza['volume']))
            objetosc_szt = objetosc_ttl / ilosc if ilosc else None
        else:
            objetosc_szt = None
            objetosc_ttl = None
    else:
        objetosc_szt = None
        objetosc_ttl = None

    powierzchnia = _powierzchnia_m2(dlugosc, szerokosc, grubosc, ilosc)
    cena_m3 = ((Decimal(str(wartosc_netto)) / objetosc_ttl)
               if (objetosc_ttl and wartosc_netto is not None) else None)

    # Kolumny wyliczane idą przez `_kwota_w_zakresie` — patrz jej docstring:
    # wartość spoza DECIMAL-a kolumny ma dać NULL, a nie wywrócić zapis
    # CAŁEGO zamówienia błędem 1264 MySQL-a.
    return {
        'volume_per_piece': _kwota_w_zakresie(objetosc_szt, '0.000001', 4,
                                              'volume_per_piece'),
        'total_volume': _kwota_w_zakresie(objetosc_ttl, '0.000001', 4,
                                          'total_volume'),
        'total_surface_m2': _kwota_w_zakresie(powierzchnia, '0.0001', 6,
                                              'total_surface_m2'),
        'price_per_m3': _kwota_w_zakresie(cena_m3, '0.01', 8, 'price_per_m3'),
    }


def mapuj_pozycje(order: Dict) -> List[Dict]:
    """Pozycje zamówienia jako słowniki kolumn `sales_order_items`.

    Klucz `order_id` NIE jest tu ustawiany — zna go dopiero upsert.
    """
    typ = typ_ceny(order)
    parser = ProductNameParser()
    wynik: List[Dict] = []

    for produkt in order.get('products') or []:
        if not isinstance(produkt, dict):
            continue

        nazwa = _tekst(produkt.get('name')) or ''
        rozbior = parser.parse_product_name(nazwa)
        ilosc = _calkowita(produkt.get('quantity'), 1)
        cena_surowa = Decimal(str(produkt.get('price_brutto') or 0))

        if typ == 'netto':
            cena_netto, cena_brutto = cena_surowa, cena_surowa * _VAT
        else:
            cena_brutto, cena_netto = cena_surowa, cena_surowa / _VAT

        dlugosc, szerokosc = rozbior.get('length_cm'), rozbior.get('width_cm')
        grubosc = rozbior.get('thickness_cm')

        wartosc_netto = cena_netto * ilosc
        pochodne = pochodne_wymiarowe(dlugosc, szerokosc, grubosc, ilosc,
                                      wartosc_netto, nazwa)

        wynik.append({
            'bl_order_product_id': _identyfikator(
                produkt.get('order_product_id')),
            'wood_species': _tekst(rozbior.get('wood_species'), 50),
            'technology': _tekst(rozbior.get('technology'), 50),
            'wood_class': _tekst(rozbior.get('wood_class'), 10),
            'finish_state': _tekst(rozbior.get('finish_state'), 50),
            'group_type': 'usługa' if czy_usluga(nazwa) else 'towar',
            'product_type': _tekst(rozbior.get('product_type'), 30),
            'length_cm': _kwota(dlugosc),
            'width_cm': _kwota(szerokosc),
            'thickness_cm': _kwota(grubosc),
            'quantity': ilosc,
            'price_gross': _kwota(cena_brutto),
            'price_net': _kwota(cena_netto),
            'value_gross': _kwota(cena_brutto * ilosc),
            'value_net': _kwota(wartosc_netto),
            'raw_product_name': nazwa or None,
            **pochodne,
        })

    return wynik


def oblicz_saldo(wartosci_pozycji, koszt_dostawy, typ_ceny_zamowienia,
                 wplacone) -> Optional[Decimal]:
    """JEDYNA definicja salda zamówienia w całym CRM-ie.

    `wartosci_pozycji` to iterowalne `value_net` WSZYSTKICH pozycji — dzięki
    temu ta sama arytmetyka obsługuje słowniki mappera i wiersze ORM, bez
    dwóch kopii wzoru. Wołają ją TRZY miejsca: `mapuj_zamowienie` (czysty
    mapper, bez bazy), `_upsert_zamowienia` (po upsercie pozycji — przez
    `saldo_z_wierszy`) i `arkusz_zapis._przelicz_saldo` (po ręcznej edycji
    w arkuszu, też przez `saldo_z_wierszy`).

    Saldo = netto WSZYSTKICH pozycji + kurier do zapłaty − wpłata.
    Kurier w bazie jest BRUTTO (rejestr: „Koszt kuriera brutto"), więc dla
    zamówienia oznaczonego jako netto idzie wprost, a w pozostałych
    przypadkach dzieli się przez VAT. `paid_amount` trzyma kwotę NETTO
    (patrz `bl_zapis._platnosc_brutto`), więc odejmuje się bez przeliczania.

    DLACZEGO WSZYSTKIE POZYCJE, RAZEM Z USŁUGAMI (rozstrzygnięcie 22.09.2026
    — nie odwracaj tego bez powtórzenia pomiaru opisanego niżej)
    =====================================================================
    W `service.py` są DWIE sprzeczne definicje `order_amount_net`:
    `total_order_value_net_products_only` (:1392-1425) liczy pozycje
    NIE-usługowe, a `_calculate_order_amount_net_for_record` (:555) wszystkie.
    Do 22.09.2026 stała tu ta pierwsza, a uzasadnieniem było zdanie „tak
    policzone są dane leżące dziś w bazie". TO ZDANIE BYŁO NIEPRAWDZIWE —
    obalił je pomiar.

    ZMIERZONE na `woodpower_crm_local`, cała tabela `sales_orders` (3324
    zamówienia), wszystkie warianty tego samego wzoru „netto pozycji + kurier
    − wpłata":

        zapisane dziś w kolumnie `balance_due` ...... 732 418,20 zł
        wariant Z USŁUGAMI ......................... 732 517,93 zł
        wariant BEZ USŁUG (poprzedni) .............. 649 723,04 zł
        wariant bez usług, kurier brutto wprost .... 712 708,09 zł
        netto samych usług .......................... 82 794,89 zł

    Wariant z usługami odtwarza stan bazy z dokładnością do 99,73 zł na 732
    tysiącach (0,014%, czyli zaokrąglenia); poprzedni rozjeżdżał się o 82 695
    zł, czyli o CAŁE netto usług. Licząc per zamówienie: z wariantem
    „z usługami" zgadza się 3319 zamówień z 3324, z wariantem „bez usług" —
    3292, a różnicę stanowi komplet 27 zamówień mających pozycję usługową.

    Zgadza się to z kodem, który te dane wyprodukował. `balance_due` w starej
    tabeli liczy `BaselinkerReportOrder.calculate_fields` (models.py:488-502)
    z pola `order_amount_net`, a to pole zależy od tego, CZYM jest dany
    wiersz: `_prepare_record_data` wychodzi dla usługi wcześniej
    (service.py:355) i zostawia jej sumę WSZYSTKICH produktów, a wierszowi
    towarowemu nadpisuje ją sumą samych produktów fizycznych (:377). Wiersze
    jednego zamówienia miały więc RÓŻNE saldo — zmierzone: dokładnie te 12
    zamówień, które mają i towar, i usługę. Backfill brał wiersz najświeższy
    (scripts/backfill_sales_tables.py:105 i :125) i w każdym z tych 12
    przypadków był nim wiersz usługowy, stąd wszystkie 27 zamówień z usługą
    ma dziś w `sales_orders` saldo policzone ze wszystkich pozycji.

    Dwa powody, każdy wystarczający osobno:
      1. tak policzone są dane, które JUŻ leżą w bazie. Przy definicji bez
         usług pierwsza synchronizacja albo pierwsza edycja w arkuszu
         przesunęłaby saldo o 82,7 tysiąca złotych bez żadnego zdarzenia
         biznesowego, a kafelek KPI „Saldo" i karta „Należności" zmieniłyby
         się bez wyjaśnienia;
      2. merytorycznie saldo to pieniądze, które klient jest nam winien —
         za suszenie usługowe też jest winien.

    Wykluczanie usług jest poprawną regułą przy METRACH SZEŚCIENNYCH (usługa
    nie ma objętości, a „Suszenie usługowe 88m3" wnosiłoby 88 m³ nieistnieją-
    cego towaru) i tam zostaje BEZ ZMIAN — patrz
    `aggregates._GRUPY_BEZ_OBJETOSCI`. Przy pieniądzach nie.

    Pilnują tego testy `test_saldo_wlicza_pozycje_uslugowa`
    i `test_saldo_zgadza_sie_z_pomiarem_z_bazy_a_nie_z_wariantem_bez_uslug`
    (tests/test_sales_ingest_zapis.py) oraz
    `test_kwota_do_zaplaty_idzie_za_danymi_lezacymi_w_bazie`
    (tests/test_sales_ingest_mapper.py).
    """
    netto_pozycji = sum((wartosc or _ZERO for wartosc in wartosci_pozycji), _ZERO)
    kurier = Decimal(koszt_dostawy or 0)
    kurier_do_zaplaty = (kurier if (typ_ceny_zamowienia or '') == 'netto'
                         else kurier / _VAT)
    return _kwota(netto_pozycji + kurier_do_zaplaty - Decimal(wplacone or 0))


def saldo_z_wierszy(zamowienie: SalesOrder) -> Optional[Decimal]:
    """Saldo policzone z WIERSZY pozycji leżących w bazie.

    WYBÓR ZBIORU POZYCJI (znalezisko KRYTYCZNE, kontrola adwersaryjna fali 5).
    `mapuj_zamowienie` liczyło saldo z PRZYSYŁKI, a `arkusz_zapis` z WIERSZY —
    dwie funkcje, dwa wyniki dla tego samego zamówienia. Rozjazd widać było
    wszędzie tam, gdzie zbiór wierszy w bazie różni się od przysyłki:

      * zamówienie z wierszem-dziedzictwem (backfill, bez klucza) i tym samym
        produktem przysłanym dziś Z KLUCZEM ma DWA wiersze; zmierzone:
        `ingest` zapisywał 800,00, a `arkusz_zapis` przeliczał na 1600,00;
      * pusta lista `products` (przysyłka podejrzana) nie kasuje wierszy,
        ale saldo liczone z przysyłki spadało do zera — zmierzone: 800,00 -> 0,00
        przy nietkniętym wierszu na 800 zł, czyli zamówienie znikało
        z należności bez żadnego zdarzenia biznesowego.

    Rozstrzygnięcie: liczymy Z WIERSZY, czyli dublety SĄ wliczane —
    konsekwentnie w obu miejscach. Uzasadnienie:
      1. arkusz pokazuje WIERSZE i użytkownik sumuje wzrokiem to samo, co my;
      2. inaczej pierwsza ręczna edycja dowolnego składnika przesuwałaby
         saldo (przeliczenie w arkuszu idzie z wierszy) — dokładnie to
         zjawisko, przed którym broni `arkusz_zapis._przelicz_saldo`;
      3. dublet-dziedzictwo jest WIDOCZNY i policzony
         (`pozycje_zachowane_bez_klucza`), więc da się go usunąć ręcznie,
         a po usunięciu obie definicje i tak zbiegają się do tej samej liczby.
    """
    return oblicz_saldo((p.value_net for p in zamowienie.items),
                        zamowienie.delivery_cost, zamowienie.price_type,
                        zamowienie.paid_amount)


def mapuj_zamowienie(order: Dict, pozycje: Optional[List[Dict]] = None) -> Dict:
    """Zamówienie jako słownik kolumn `sales_orders`.

    `pozycje` można podać, żeby nie parsować nazw produktów dwa razy —
    saldo liczy się z ich wartości netto.
    """
    if pozycje is None:
        pozycje = mapuj_pozycje(order)

    typ = typ_ceny(order)
    pola_dodatkowe = order.get('custom_extra_fields') or {}

    nazwa_klienta = (
        _tekst(order.get('delivery_fullname'))
        or _tekst(order.get('delivery_company'))
        or _tekst(order.get('user_login'))
        or 'Nieznany klient'
    )

    status_id = order.get('order_status_id')
    try:
        status_id = int(status_id) if status_id is not None else None
    except (TypeError, ValueError):
        status_id = None

    koszt_dostawy = _kwota(order.get('delivery_price') or 0) or _ZERO
    wplacone = _kwota(kwota_netto(order.get('payment_done'), typ)) or _ZERO

    # Wzór siedzi w `oblicz_saldo` — JEDNEJ definicji dla mappera, upsertu
    # i przeliczenia po ręcznej edycji w arkuszu. Tutaj, czyli w czystym
    # mapperze bez bazy, zbiorem pozycji jest sama przysyłka; ścieżka
    # zapisu liczy to samo z WIERSZY (patrz `saldo_z_wierszy`).
    saldo = oblicz_saldo((p['value_net'] for p in pozycje),
                         koszt_dostawy, typ, wplacone)

    ma_wplate = bool(order.get('payment_done'))

    return {
        'baselinker_order_id': _numer_bl(order),
        'date_created': _data_z_timestampu(order.get('date_add')) or _dzis(),
        # internal_order_number/email/phone/delivery_address/payment_method
        # (niżej) i delivery_state (przez _wojewodztwo) idą przez
        # _tekst_zamowienia — patrz jej docstring (znalezisko WAŻNE, przegląd
        # Zadania 1).
        'internal_order_number': _tekst_zamowienia(order.get('extra_field_1'), 50),
        'customer_name': nazwa_klienta[:200],
        'email': _tekst_zamowienia(order.get('email'), 150),
        'phone': _tekst_zamowienia(order.get('phone'), 100),
        'delivery_address': _tekst_zamowienia(order.get('delivery_address'), 250),
        'delivery_postcode': _tekst(order.get('delivery_postcode'), 20),
        'delivery_city': _tekst(order.get('delivery_city'), 100),
        'delivery_state': _wojewodztwo(order),
        'caretaker': _tekst(pola_dodatkowe.get(POLE_OPIEKUN), 100) or BRAK_OPIEKUNA,
        'order_source': _tekst(order.get('order_source'), 50),
        'order_source_id': (_calkowita(order.get('order_source_id'), 0)
                            if order.get('order_source_id') is not None else None),
        'delivery_method': _tekst(order.get('delivery_method'), 255),
        'delivery_cost': koszt_dostawy,
        'price_type': typ,
        'payment_method': _tekst_zamowienia(order.get('payment_method'), 255),
        'paid_amount': wplacone,
        'payment_date': _data_z_timestampu(order.get('date_confirmed')) if ma_wplate else None,
        'balance_due': saldo,
        # ZNALEZISKO WAŻNE (przegląd Zadania 6): przy braku `order_status_id`
        # wchodził tu dosłowny napis „Status None". Kolumna jest indeksowana
        # i widoczna w arkuszu, więc użytkownik dostawał ten napis wprost
        # w komórce, a karty grupujące po statusie robiły z niego osobny
        # kubełek. Brak statusu to brak wartości, czyli NULL. Nieznany, ale
        # ISTNIEJĄCY identyfikator zostaje jako „Status 417343" — to niesie
        # informację (numer do sprawdzenia w BaseLinkerze) i jest zgodne
        # z danymi historycznymi.
        'current_status': (STATUSY_BASELINKER.get(status_id, f'Status {status_id}')
                           if status_id is not None else None),
        'baselinker_status_id': status_id,
        # admin_comments JEST polem BaseLinkera (rejestr: SetOrderFields).
        # Uwaga: produkcja dopisuje tam komunikaty systemowe („Pominięto
        # pozycje usługowe…"), więc kolumna bywa zajęta tekstem robota.
        'notes': _tekst(order.get('admin_comments'), 200),
    }


def _zaktualizuj_pozycje(wiersz: SalesOrderItem, pola: Dict) -> None:
    """Nakłada dane z BaseLinkera na ISTNIEJĄCY wiersz pozycji.

    Granica jest ta sama, co na poziomie zamówienia (spec §5.2): kolumny,
    których BaseLinker nie zna, zostają nietknięte. Na poziomie zamówienia
    wychodzi to samo z siebie — mapper takich kluczy w ogóle nie produkuje.
    Na poziomie pozycji mapper produkuje je WSZYSTKIE, bo są potrzebne przy
    zakładaniu nowego wiersza, więc rozdzielić trzeba tutaj.

    WYMIARY I POCHODNE. Długość, szerokość i grubość są CRM-owe, więc ręczna
    poprawka wygrywa — także przy KAŻDEJ kolejnej synchronizacji, bo nazwa
    produktu w BaseLinkerze dalej niesie stary wymiar. Objętość, powierzchnia
    i cena za m³ muszą wtedy iść ZA wymiarem z bazy, nie za nazwą z BL —
    inaczej w jednym wierszu stałaby nowa długość i stara objętość, a suma
    „TTL m³" byłaby cicho zła. Przeliczamy je dopiero po pętli, bo
    `price_per_m3` liczy się z `value_net`, który pętla właśnie zaktualizowała.
    """
    zmieniono_wymiary = any(getattr(wiersz, nazwa) != pola.get(nazwa)
                            for nazwa in WYMIARY_POZYCJI)

    for nazwa, wartosc in pola.items():
        if nazwa in KOLUMNY_POZYCJI_TYLKO_CRM:
            continue
        if zmieniono_wymiary and nazwa in KOLUMNY_POCHODNE_POZYCJI:
            continue
        setattr(wiersz, nazwa, wartosc)

    if zmieniono_wymiary:
        for nazwa, wartosc in pochodne_wymiarowe(
                wiersz.length_cm, wiersz.width_cm, wiersz.thickness_cm,
                wiersz.quantity or 0, wiersz.value_net,
                wiersz.raw_product_name).items():
            setattr(wiersz, nazwa, wartosc)


def _pusty_licznik_pozycji() -> Dict[str, int]:
    """Zerowy zestaw liczników jednego przebiegu `_upsert_pozycje`."""
    return {'nowe': 0, 'zaktualizowane': 0, 'usuniete': 0, 'pominiete': 0,
            'zachowane_bez_klucza': 0, 'podejrzana_paczka': 0,
            'powtorzony_klucz': 0, 'znormalizowane_zero': 0}


def _upsert_pozycje(zamowienie: SalesOrder, pozycje: List[Dict]) -> Dict[str, int]:
    """Dopasowuje pozycje z BaseLinkera do wierszy, które już są w bazie.

    Zwraca liczniki tego, co się naprawdę stało (patrz `_pusty_licznik_pozycji`).

    HISTORIA. Do 22.09.2026 upsert robił `zamowienie.items = [...]`, czyli przy
    `cascade='all, delete-orphan'` KASOWAŁ komplet pozycji i zakładał je od
    nowa przy KAŻDEJ synchronizacji — ręczna praca operatora znikała bez śladu.
    Pierwsza poprawka zamieniła to na upsert z trzema przebiegami dopasowania
    (klucz, nazwa, kolejność) i kontrola adwersaryjna złamała WYKONANIEM dwa
    słabsze:

      * pozycja z BL BEZ `order_product_id` nie dopasowywała się do wiersza,
        który ten klucz JUŻ MA (przebiegi po nazwie i po kolejności wymagały
        od wiersza braku klucza) — wiersz zostawał nieprzypisany, więc leciał
        do kasacji jako „usunięty w BaseLinkerze", a na jego miejsce wchodził
        świeży, pusty. Zmierzone: `id` wiersza 1 -> 2, ręczna poprawka zniknęła;
      * przy wierszach BEZ klucza (czyli przy CAŁYM backfillu historycznym)
        przebieg „po kolejności" oddawał NOWEMU produktowi wiersz po pozycji
        SKASOWANEJ w BL. Zmierzone: wiersz „Blat bukowy" wraz z ręcznym
        wykończeniem stawał się „Blatem jesionowym". To nie utrata danych,
        tylko ich PRZESTAWIENIE — groźniejsze, bo z arkusza niewidoczne.

    REGUŁA OBOWIĄZUJĄCA: PRZESTAJEMY ZGADYWAĆ
    =========================================
    Wiersze z backfillu nie mają `bl_order_product_id` i nigdy go nie dostaną —
    zamówienia starsze niż trzy miesiące siedzą w archiwum BaseLinkera,
    którego `getOrders` nie widzi żadnym parametrem (patrz pamięć projektu
    „BL getOrders — archiwum"). Każda heurystyka tożsamości musi się więc
    kiedyś pomylić, a każda pomyłka przestawia RĘCZNĄ pracę na inny produkt.
    Dlatego:

      1. dopasowanie WYŁĄCZNIE po `bl_order_product_id`, bez żadnego fallbacku;
      2. wiersza BEZ klucza nie usuwamy NIGDY — zostaje nietknięty, nawet gdy
         BaseLinker go nie przysłał;
      3. usuwamy wyłącznie wiersz, który MA klucz, a tego klucza NIE MA
         w przysyłce;
      4. pozycji z BL bez klucza nie dopasowujemy do niczego (patrz niżej);
      5. przysyłka, której nie da się potraktować jak spisu inwentarza, nie
         kasuje NICZEGO (patrz „PRZYSYŁKA PEŁNA");
      6. klucza POWTÓRZONEGO w jednej przysyłce nie dopasowujemy do niczego
         (patrz „POWTÓRZONY KLUCZ");
      7. każde usunięcie i każde pominięcie jest policzone i trafia do wyniku
         `zapisz_zamowienia` oraz do logu na poziomie ostrzeżenia.

    POWTÓRZONY KLUCZ (reguła 6). ZNALEZISKO KRYTYCZNE, kontrola adwersaryjna
    fali 5: dopasowanie po kolejności wracało tylnymi drzwiami. Lista pod
    kluczem (`po_kluczu`) plus `kandydaci.pop(0)` znaczyły, że przy DWÓCH
    wierszach o tym samym kluczu i DWÓCH kopiach tego klucza w przysyłce
    pierwsza kopia dostawała pierwszy wiersz, a druga — drugi. To jest
    kolejność, tyle że schowana, i przestawia ręczną pracę między wierszami.
    Zmierzone: wiersz „Blat dębowy" z ręcznym wykończeniem stawał się „Blatem
    jesionowym". Powtórzony klucz nie identyfikuje niczego (to samo, co zero
    i to samo, co brak), więc WSZYSTKIE kopie takiego klucza pomijamy
    i liczymy, a całą przysyłkę traktujemy jak podejrzaną — czyli nie kasuje
    NICZEGO, dokładnie jak przysyłka pusta.

    POZYCJA Z BL BEZ KLUCZA — wybór i uzasadnienie (reguła 4). Nie nadpisuje
    niczego; zostaje POMINIĘTA I POLICZONA, z jednym wyjątkiem: gdy zamówienie
    nie ma jeszcze ANI JEDNEGO wiersza, zakładamy ją normalnie. Powód takiego
    rozgraniczenia jest arytmetyczny. Bezwarunkowe „dodaj jako nową" przy
    wierszach, których nie da się dopasować, dokłada komplet pozycji przy
    KAŻDYM przebiegu — licznik wierszy rośnie bez końca, a razem z nim
    `SUM(value_net)` i metry sześcienne na kartach. Bezwarunkowe „pomiń"
    z kolei gubiłoby pozycje przy PIERWSZYM zapisie zamówienia, czyli wtedy,
    gdy z definicji nie ma czego przestawić ani zdublować. Pusta kolekcja jest
    jedynym stanem, w którym dodanie jest bezpieczne, i tylko tam dodajemy.

    PRZYSYŁKA PEŁNA (reguła 5). Kasować wolno wyłącznie na podstawie przysyłki,
    którą da się czytać jak KOMPLETNY spis pozycji zamówienia: niepustej
    i takiej, w której KAŻDA pozycja ma klucz. Pusta lista `products` kasowała
    dotąd wszystko (zmierzone: 1 -> 0) razem z ręczną pracą, a lista z pozycją
    bez klucza nie mówi nic o tym, czy wiersz z kluczem dalej istnieje —
    bez tej bramki naprawa reguły 4 otworzyłaby nową drogę do kasowania.

    Operujemy na kolekcji W MIEJSCU (`append`/`remove`), bo to `delete-orphan`
    na niej kasuje wiersze; podmiana całej listy jest właśnie tym, co psuło.
    """
    licznik = _pusty_licznik_pozycji()

    # Kolejność wstawienia, nie przypadkowa kolejność z bazy — liczy się przy
    # duplikatach tego samego klucza (patrz niżej), żeby wynik był powtarzalny.
    istniejace = sorted(zamowienie.items, key=lambda w: (w.id is None, w.id or 0))
    mialo_pozycje = bool(istniejace)

    # Wiersze Z kluczem, indeksowane po nim. Lista pod kluczem, bo teoretycznie
    # nic nie broni dwóm wierszom nosić tego samego `bl_order_product_id`.
    po_kluczu: Dict[int, List[SalesOrderItem]] = {}
    bez_klucza: List[SalesOrderItem] = []
    for wiersz in istniejace:
        klucz = _identyfikator(wiersz.bl_order_product_id)
        if klucz is None:
            if wiersz.bl_order_product_id is not None:
                # ZERO W BAZIE ZAPISUJEMY JAKO NULL (znalezisko WAŻNE,
                # trzecia kontrola adwersaryjna). `_identyfikator` już teraz
                # czyta 0 jak BRAK klucza, ale sam zapis zostawał w kolumnie
                # — i to wystarczało, żeby taki wiersz utknął na zawsze:
                #
                #   * nie dopasuje się do niczego po kluczu (0 znaczy brak),
                #     a innych ścieżek nie ma (reguła 1);
                #   * `scripts/uzupelnij_klucze_pozycji.py` go NIE WIDZI, bo
                #     szuka wierszy po `bl_order_product_id IS NULL` — czyli
                #     narzędzie od dorabiania kluczy omija go systematycznie;
                #   * dla ograniczenia UNIQUE(order_id, bl_order_product_id)
                #     (migracja 2026-09-23) zero NIE jest NULL-em: NULL-e nie
                #     kolidują ze sobą nigdy, ZERA kolidują zawsze. Dwa takie
                #     wiersze w jednym zamówieniu wywracają cały zapis
                #     błędem 1062.
                #
                # Wybór padł na NORMALIZACJĘ, a nie na samo „czytaj 0 jak NULL",
                # bo tylko ona te trzy skutki usuwa; zapisujemy tę samą treść
                # w kanonicznej postaci, więc jest idempotentna i nic nie traci.
                # Skala dzisiaj: 0 takich wierszy na 7938 w woodpower_crm_local
                # (pomiar 22.09.2026, wszystkie mają NULL) — to zabezpieczenie
                # przed integracją wstawiającą zera, nie naprawa zastanych danych.
                wiersz.bl_order_product_id = None
                licznik['znormalizowane_zero'] += 1
            bez_klucza.append(wiersz)
        else:
            po_kluczu.setdefault(klucz, []).append(wiersz)

    # Klucze POWTÓRZONE w tej przysyłce (reguła 6) — liczone Z GÓRY, przed
    # pętlą, bo pomijamy WSZYSTKIE kopie takiego klucza, także pierwszą.
    # Wybór pierwszej byłby dokładnie tym dopasowaniem po kolejności,
    # którego się pozbywamy.
    wystapienia: Dict[int, int] = {}
    for pola in pozycje:
        klucz = pola.get('bl_order_product_id')
        if klucz is not None:
            wystapienia[klucz] = wystapienia.get(klucz, 0) + 1
    powtorzone = {klucz for klucz, ile in wystapienia.items() if ile > 1}

    klucze_z_bl = set()
    pozycji_bez_klucza_w_bl = 0

    for pola in pozycje:
        klucz = pola.get('bl_order_product_id')
        if klucz in powtorzone:
            licznik['pominiete'] += 1
            licznik['powtorzony_klucz'] += 1
            continue
        if klucz is None:
            pozycji_bez_klucza_w_bl += 1
            if mialo_pozycje:
                licznik['pominiete'] += 1
                continue
            zamowienie.items.append(SalesOrderItem(**pola))
            licznik['nowe'] += 1
            continue

        klucze_z_bl.add(klucz)
        kandydaci = po_kluczu.get(klucz)
        if kandydaci:
            # Wiersz jest tu dokładnie jeden w zdrowym stanie bazy. Gdy
            # dziedzictwo zostawiło ich kilka pod jednym kluczem,
            # aktualizujemy NAJSTARSZY (kolejność wstawienia, patrz `istniejace`),
            # a nadmiarowe zostają nietknięte — nie zgadujemy, który jest
            # „ten właściwy", i niczego nie kasujemy.
            _zaktualizuj_pozycje(kandydaci[0], pola)
            licznik['zaktualizowane'] += 1
        else:
            zamowienie.items.append(SalesOrderItem(**pola))
            licznik['nowe'] += 1

    if not pozycje or pozycji_bez_klucza_w_bl or powtorzone:
        # Przysyłka nie nadaje się na spis inwentarza — nie kasujemy NICZEGO.
        licznik['podejrzana_paczka'] = 1
        return licznik

    for klucz, wiersze in po_kluczu.items():
        if klucz in klucze_z_bl:
            # Klucz JEST w przysyłce — ewentualne nadmiarowe wiersze o tym
            # samym kluczu zostają (reguła 3 mówi o BRAKU klucza w przysyłce).
            continue
        for wiersz in wiersze:
            zamowienie.items.remove(wiersz)
            licznik['usuniete'] += 1

    # Wiersze bez klucza przeżywają nawet pełną przysyłkę, która o nich
    # milczy (reguła 2). Liczymy je, bo to one dublują się z pozycjami, które
    # BaseLinker przysyła dziś już z kluczem — użytkownik ma prawo wiedzieć,
    # ile takich dziedzictw zostawiamy.
    licznik['zachowane_bez_klucza'] = len(bez_klucza)
    return licznik


def _przelicz_klienta(klient: SalesClient, sesja) -> None:
    """Denormalizacja klienta liczona OD NOWA z bazy, nie inkrementowana.

    `scripts/backfill_sales_tables.py:138` inkrementuje i to jest poprawne
    w skrypcie jednorazowym. Tutaj byłoby błędem: drugi przebieg tego samego
    zamówienia podwoiłby `orders_count` i `lifetime_net`, a karta „Klienci"
    na dashboardzie stoi właśnie na tej denormalizacji. Przeliczenie jest
    idempotentne z definicji i przy okazji leczy liczniki rozjechane wcześniej.

    `lifetime_net` sumuje WSZYSTKIE pozycje, także usługowe — tak liczy je
    backfill, a rozjazd definicji zrobiłby skok na karcie w dniu wdrożenia.

    TYLKO SPRZEDAŻ (partia E, punkt E5): zamówienia anulowane i nieopłacone
    nie wchodzą ani do licznika, ani do `lifetime_net`, ani do dat. Klient,
    którego jedyne zamówienie anulowano, ma `orders_count = 0` i puste
    `first_order_at` — nie wpada do kubełka „1 zam." i nie jest nowym
    klientem. Przeliczenie od nowa działa w obie strony: nieopłacone, które
    przy kolejnej synchronizacji przyjdzie jako opłacone, wraca do liczb samo.
    """
    (klient.orders_count, klient.lifetime_net,
     klient.first_order_at, klient.last_order_at) = liczniki_klientow(
        sesja, [klient.id]).get(klient.id, BRAK_SPRZEDAZY)


# Denormalizacja klienta bez ani jednego zamówienia w sprzedaży.
BRAK_SPRZEDAZY = (0, Decimal('0.00'), None, None)


def liczniki_klientow(sesja, identyfikatory: Optional[List[int]] = None
                      ) -> Dict[int, tuple]:
    """(orders_count, lifetime_net, first_order_at, last_order_at) per klient.

    JEDNA definicja denormalizacji klienta — woła ją `_przelicz_klienta`
    (jeden klient, przy każdym zapisie) i `scripts/przelicz_klientow_
    sprzedazy.py` (wszyscy naraz, przy każdym wdrożeniu przez `deploy.sh`).
    Dwie kopie tej reguły rozjechałyby się przy pierwszej zmianie jednej z nich.

    Samo CZYTA — nic nie ustawia, więc skrypt w trybie próby nie dotyka bazy.
    Klient bez ani jednego zamówienia w sprzedaży nie ma klucza w wyniku;
    wołający bierze wtedy `BRAK_SPRZEDAZY`.

    Dwa zapytania zamiast jednego z joinem: `COUNT` zamówień po pozycjach
    policzyłby zamówienie tyle razy, ile ma pozycji — ta sama pułapka co
    przy saldzie.
    """
    warunki = [SalesOrder.client_id.isnot(None), warunek_sprzedazy()]
    if identyfikatory is not None:
        warunki.append(SalesOrder.client_id.in_(list(identyfikatory)))

    zamowienia = (
        sesja.query(SalesOrder.client_id, func.count(SalesOrder.id),
                    func.min(SalesOrder.date_created),
                    func.max(SalesOrder.date_created))
        .filter(*warunki)
        .group_by(SalesOrder.client_id)
        .all()
    )
    netto = dict(
        sesja.query(SalesOrder.client_id, func.sum(SalesOrderItem.value_net))
        .join(SalesOrder, SalesOrderItem.order_id == SalesOrder.id)
        .filter(*warunki)
        .group_by(SalesOrder.client_id)
        .all()
    )
    return {
        id_klienta: (int(licznik or 0), _kwota(netto.get(id_klienta) or 0),
                     pierwsze, ostatnie)
        for id_klienta, licznik, pierwsze, ostatnie in zamowienia
    }


def _krotki_opis_bledu(wyjatek: Exception) -> str:
    """Typ wyjątku + pierwsza linia komunikatu, nic więcej.

    ZNALEZISKO WAŻNE (przegląd Zadania 2): `str(wyjątku)` dla `IntegrityError`
    SQLAlchemy wkleja CAŁY INSERT razem z parametrami — imię, nazwisko, mail,
    telefon i adres klienta. Ten słownik trafia i do loga, i — przez
    endpointy Zadań 4/6 — do przeglądarki jako komunikat dla użytkownika.
    Pełny `str(wyjątku)` (z parametrami) zostaje WYŁĄCZNIE w `logger.error`,
    gdzie nikt z zewnątrz go nie zobaczy.
    """
    opis = str(wyjatek).strip()
    pierwsza_linia = opis.splitlines()[0] if opis else ''
    nazwa = type(wyjatek).__name__
    return f'{nazwa}: {pierwsza_linia}' if pierwsza_linia else nazwa


def _upsert_zamowienia(surowe: Dict, bl_id: int, stat: Dict, sesja,
                       ma_produkcje: bool = False, ma_leady: bool = False,
                       pamiec_leadow: Optional[Dict] = None,
                       pamiec_zrodel: Optional[Dict] = None) -> None:
    """Jedno zamówienie. Woła commit NA `sesja`. Wyjątek zostawia wołającemu.

    `sesja` to WŁASNA sesja analityki (patrz „WŁASNOŚĆ SESJI" w docstringu
    modułu), nigdy `db.session`. Commit tutaj zatwierdza wyłącznie wiersze
    analityki — cudza praca zflushowana w sesji produkcji jest poza nim.

    `bl_id` przychodzi już przeliczony i zwalidowany od wołającego (patrz
    `zapisz_zamowienia`) — to JEDYNE źródło prawdy o numerze zamówienia BL,
    używane zarówno do wyszukania wiersza, jak i do jego zapisania.

    `ma_produkcje` mówi, czy tabela `prod_orders` w ogóle istnieje w podpiętej
    bazie — liczone raz na całą paczkę przez wołającego (`_jest_tabela`),
    nie tutaj, żeby nie odpytywać `information_schema` przy każdym zamówieniu.

    `ma_leady` — analogicznie dla tabeli `leads`. ODCHYLENIE OD BRIEFU
    (Zadanie 3): sam brief tego nie przewidywał, ale bez tej bramki
    `dowiaz_lead` wysypuje `OperationalError: no such table: leads`
    na każdej bazie, która tabeli `leads` nie zakłada — w tym
    `tests/test_sales_ingest_zapis.py` (Zadanie 2), którego `_TABLES`
    nie zawiera `Client`. Wyjątek leciałby w górę, `zapisz_zamowienia`
    łapałaby go jako błąd CAŁEGO zamówienia i cofała już wstawiony wiersz
    (rollback) — ten sam mechanizm ryzyka, przed którym broni `ma_produkcje`
    dla `prod_orders`. Symetria jest celowa.

    `pamiec_leadow` — słownik-pamięć podręczna współdzielony przez CAŁĄ
    paczkę (`zapisz_zamowienia`), pod jednym kluczem `'indeks'`. ZNALEZISKO
    WAŻNE (przegląd Zadania 4): `dowiaz_lead` bez indeksu wczytuje całą
    tabelę `leads` do Pythona aż 3x, a robione to było przy KAŻDYM
    zamówieniu klienta bez `lead_id` — ~6-20 s doklejone do synchronizacji
    100 zamówień. Budujemy indeks LENIWIE, przy pierwszej faktycznej
    potrzebie (nie z góry — paczka złożona wyłącznie z już dowiązanych
    klientów nie ma po co go liczyć), i trzymamy w tym samym słowniku przez
    resztę paczki.

    `pamiec_zrodel` — ta sama zasada dla słownika źródeł BaseLinkera
    (`getOrderSources`), pod kluczem `'slownik'`: pobierany LENIWIE, przy
    pierwszym zamówieniu, które go naprawdę potrzebuje (puste pochodzenie
    i para kanał-id), i najwyżej RAZ na paczkę.
    """
    pozycje = mapuj_pozycje(surowe)
    pola = mapuj_zamowienie(surowe, pozycje)
    # Mapper liczy `baselinker_order_id` tą samą funkcją (`_numer_bl`), co
    # wołający, więc wartości są z definicji zgodne. Przypisanie zostaje jako
    # jawny niezmiennik: numer użyty do WYSZUKANIA wiersza i numer, który
    # trafia do kolumny, muszą być tą samą liczbą — inaczej drugi przebieg
    # wpada w UNIQUE constraint zamiast zaktualizować wiersz (znalezisko
    # WAŻNE, przegląd Zadania 2).
    pola['baselinker_order_id'] = bl_id

    zamowienie = sesja.query(SalesOrder).filter_by(baselinker_order_id=bl_id).first()
    nowe = zamowienie is None
    if nowe:
        zamowienie = SalesOrder(baselinker_order_id=bl_id)
        sesja.add(zamowienie)

    # Klient sprzed tego przebiegu — None dla nowego zamówienia. Potrzebny
    # do dwóch napraw niżej: re-pinowania bez klucza dedupikacji i przeliczenia
    # klienta, który zamówienie ewentualnie straci.
    poprzedni_client_id = zamowienie.client_id

    # Ustawiamy WYŁĄCZNIE klucze z mappera. Kolumny tylko-CRM (client_origin,
    # own_transport, picked_up, advance_*, paid_*) nie są w tym słowniku
    # i dlatego ręczna praca w arkuszu przeżywa każdą synchronizację.
    for nazwa, wartosc in pola.items():
        setattr(zamowienie, nazwa, wartosc)

    przed = sesja.query(SalesClient).count()
    ma_klucz_dedupikacji = bool(
        norm_email(pola['email']) or norm_nip(surowe.get('invoice_nip'))
        or norm_phone(pola['phone']))
    if poprzedni_client_id is not None and not ma_klucz_dedupikacji:
        # ZNALEZISKO KRYTYCZNE (przegląd Zadania 2): zamówienie bez ŻADNEGO
        # klucza dedupikacji (e-mail, NIP, telefon >= 9 cyfr) nie ma jak
        # trafić z powrotem do tego samego klienta przez
        # `znajdz_lub_utworz_klienta` — ta funkcja przy braku e/n/t ZAWSZE
        # zakłada NOWEGO klienta z `needs_merge=True` (dedup.py). Zamówienie,
        # które już ma klienta, przypinamy więc do niego ponownie, zamiast
        # pozwolić, żeby każdy kolejny przebieg (cron produkcji, powtórne
        # kliknięcie „Pobierz zamówienia") dokładał kolejnego sierotę.
        klient = sesja.query(SalesClient).get(poprzedni_client_id)
    else:
        klient = None
    if klient is None:
        klient = znajdz_lub_utworz_klienta(
            email=pola['email'],
            nip=surowe.get('invoice_nip'),
            phone=pola['phone'],
            nazwa=pola['customer_name'],
            sesja=sesja,
        )
    nowy_klient = sesja.query(SalesClient).count() > przed
    zamowienie.client_id = klient.id

    # Dowiązanie do rejestru wycenianych. Robimy to wyłącznie, gdy klient
    # jeszcze nie ma leada — `dowiaz_lead` sam też to sprawdza, ale warunek
    # tutaj oszczędza wczytanie całej tabeli `leads` przy każdym zamówieniu
    # znanego już klienta. `ma_leady` chroni środowiska bez tabeli `leads`
    # (patrz docstring `_upsert_zamowienia`).
    if ma_leady and klient.lead_id is None:
        if pamiec_leadow is not None:
            # Indeks budowany LENIWIE i RAZ na całą paczkę — patrz
            # docstring `_upsert_zamowienia` i `zbuduj_indeks_leadow`.
            if 'indeks' not in pamiec_leadow:
                pamiec_leadow['indeks'] = zbuduj_indeks_leadow(sesja)
            dowiaz_lead(klient, pamiec_leadow['indeks'], sesja)
        else:
            # Wołanie spoza `zapisz_zamowienia` (bez współdzielonej pamięci) —
            # `dowiaz_lead` sam zbuduje sobie indeks ad-hoc dla tego klienta.
            dowiaz_lead(klient, None, sesja)

    # POCHODZENIE KLIENTA (partia E, punkt E6). Wypełniamy WYŁĄCZNIE puste
    # pole, ale przy KAŻDYM zapisie — do 23.09.2026 tylko przy pierwszym
    # i tylko z produkcji, więc zamówienie, które nie weszło na halę albo
    # przyszło przez Arkusz, zostawało bez pochodzenia na zawsze (14 z 14
    # nowych zamówień z 23.09). Kolumna jest tylko-CRM i edytowalna
    # w Arkuszu: wartości niepustej NIE RUSZAMY NIGDY, bo to ręczna praca.
    if _puste_pochodzenie(zamowienie.client_origin):
        propozycja = _pochodzenie_klienta(
            pola.get('order_source'), pola.get('order_source_id'), bl_id,
            sesja, ma_produkcje, pamiec_zrodel)
        if propozycja:
            zamowienie.client_origin = propozycja

    licznik_pozycji = _upsert_pozycje(zamowienie, pozycje)

    # SALDO LICZY SIĘ Z WIERSZY, KTÓRE ZOSTAŁY W BAZIE — nie z przysyłki
    # (znalezisko KRYTYCZNE fali 5, uzasadnienie w `saldo_z_wierszy`).
    # `mapuj_zamowienie` policzyło je wyżej z przysyłki, bo jako czysty mapper
    # innego zbioru nie zna; tutaj, po upsercie pozycji, znamy stan faktyczny
    # i to on rozstrzyga. Ta sama liczba, którą po ręcznej edycji wyliczy
    # `arkusz_zapis._przelicz_saldo`.
    zamowienie.balance_due = saldo_z_wierszy(zamowienie)

    sesja.flush()
    _przelicz_klienta(klient, sesja)
    if poprzedni_client_id is not None and poprzedni_client_id != klient.id:
        # ZNALEZISKO WAŻNE (przegląd Zadania 2): zamówienie zmieniło klienta
        # (poprawiony e-mail w BaseLinkerze, dopisany NIP) — stary klient bez
        # tego zostawałby z licznikami po zamówieniu, które już do niego nie
        # należy.
        poprzedni_klient = sesja.query(SalesClient).get(poprzedni_client_id)
        if poprzedni_klient is not None:
            _przelicz_klienta(poprzedni_klient, sesja)
    sesja.commit()

    # ZNALEZISKO WAŻNE (przegląd Zadania 2): liczniki idą do `stat` DOPIERO
    # po udanym commicie. Wcześniej `klienci_nowi` rósł od razu po utworzeniu
    # klienta (samo `flush`), a `db.session.rollback()` przy błędzie dalszej
    # części funkcji cofał wstawienie klienta bez korekty licznika.
    stat['nowe' if nowe else 'zaktualizowane'] += 1
    # `pozycje` liczy pozycje PRZYSŁANE przez BaseLinkera — tak było od
    # początku i tak zostaje. Same w sobie nie mówią jednak, co się z nimi
    # stało, więc obok idą liczniki faktycznych skutków: ile wierszy powstało,
    # ile zaktualizowaliśmy, ile skasowaliśmy, ile pozycji pominęliśmy
    # i ile wierszy-dziedzictw zostawiliśmy. Bez nich kasowanie jest CICHE.
    stat['pozycje'] += len(pozycje)
    stat['pozycje_nowe'] += licznik_pozycji['nowe']
    stat['pozycje_zaktualizowane'] += licznik_pozycji['zaktualizowane']
    stat['pozycje_usuniete'] += licznik_pozycji['usuniete']
    stat['pozycje_pominiete'] += licznik_pozycji['pominiete']
    stat['pozycje_zachowane_bez_klucza'] += licznik_pozycji['zachowane_bez_klucza']
    stat['podejrzane_paczki_pozycji'] += licznik_pozycji['podejrzana_paczka']
    # Rozbicie powodu pominięcia: te pozycje są JUŻ policzone
    # w `pozycje_pominiete`, a ten licznik mówi, dlaczego (patrz reguła 6).
    stat['pozycje_powtorzony_klucz'] += licznik_pozycji['powtorzony_klucz']
    if nowy_klient:
        stat['klienci_nowi'] += 1


def zapisz_zamowienia(zamowienia: List[Dict], zrodlo: str = 'analiza') -> Dict[str, object]:
    """Upsert listy surowych zamówień z BaseLinkera do `sales_*`.

    Idempotentny po `baselinker_order_id` (kolumna jest UNIQUE): ponowne
    przetworzenie tego samego zamówienia aktualizuje wiersz, a pozycje
    dopasowuje po `bl_order_product_id` (patrz `_upsert_pozycje`) — nie
    dokłada duplikatu ani zamówienia, ani pozycji.

    Commit idzie PO KAŻDYM zamówieniu, a błąd jednego nie przerywa paczki —
    raportujemy go w `bledy` i idziemy dalej. Ten sam wybór, co w
    `SyncService`: jedno felerne zamówienie z BaseLinkera nie może zablokować
    pozostałych stu.

    CAŁOŚĆ IDZIE PO WŁASNEJ SESJI, którą ta funkcja zakłada i zamyka
    w `finally` — patrz „WŁASNOŚĆ SESJI" w docstringu modułu. `db.session`
    nie jest tu tykana ani razu, więc analityka nie może ani zatwierdzić,
    ani cofnąć pracy produkcji.

    DUPLIKAT ZAMÓWIENIA W PACZCE (znalezisko WAŻNE, kontrola adwersaryjna
    fali 5). Gdy ta sama paczka niesie DWIE kopie jednego zamówienia,
    wygrywała OSTATNIA — i to nie tylko na polach zamówienia. Zmierzone na
    paczce [kopia z pozycjami 991 i 992, kopia tylko z 991]: druga kopia była
    dla `_upsert_pozycje` kompletnym spisem inwentarza, więc KASOWAŁA wiersz
    992 razem z ręczną pracą operatora, a wynik paczki mówił o tym tyle,
    co nic.

    Rozstrzygnięcie: liczy się PIERWSZA kopia, każda kolejna jest pomijana,
    policzona (`duplikaty_zamowien`, `pominiete`) i zgłoszona w `bledy`.
    Uzasadnienie wyboru:
      * „najbogatsza kopia wygrywa" wymagałaby rankingu kompletności, czyli
        dokładnie tego zgadywania tożsamości, którego pozbyliśmy się na
        poziomie pozycji — a pomyłka kosztuje skasowany wiersz;
      * „ostatnia wygrywa" to stan sprzed naprawy: pozwala UBOŻSZEJ kopii
        skasować wiersze zapisane przez bogatszą;
      * „pierwsza wygrywa" jest rozstrzygnięciem deterministycznym,
        niezależnym od zawartości kopii, a świeższe dane i tak dojdą przy
        najbliższej synchronizacji — tym razem w jednej kopii.
    Paczka z duplikatem jest więc traktowana jak podejrzana: zamówienie
    zapisuje się raz, a użytkownik dostaje o tym jawny komunikat. Zgłoszenie
    NIE jest hałasem na normalnej ścieżce: `fetch_orders_from_date_range`
    odsiewa powtórki po `order_id` już przy sklejaniu chunków (service.py:2223),
    więc duplikat, który tu dociera, znaczy, że coś poszło nie tak wyżej —
    albo że dwie kopie mają numer zapisany inaczej ('991' i 991), czego
    tamta dedupikacja nie widzi, a nasza normalizacja (`_numer_bl`) tak.

    `zrodlo` jest wyłącznie etykietą do logu i do wyniku ('analiza' albo
    'produkcja') — zachowanie jest w obu przypadkach identyczne.
    """
    stat: Dict[str, object] = {
        'nowe': 0, 'zaktualizowane': 0, 'pozycje': 0, 'klienci_nowi': 0,
        'pominiete': 0, 'bledy': [], 'zrodlo': zrodlo, 'ostrzezenie': None,
        # Skutki na POZYCJACH — patrz `_upsert_pozycje`. `pozycje` (wyżej)
        # liczy to, co przysłał BaseLinker; te sześć liczników mówi, co się
        # z tym stało. Koniec cichych kasowań.
        'pozycje_nowe': 0, 'pozycje_zaktualizowane': 0, 'pozycje_usuniete': 0,
        'pozycje_pominiete': 0, 'pozycje_zachowane_bez_klucza': 0,
        'podejrzane_paczki_pozycji': 0, 'pozycje_powtorzony_klucz': 0,
        # Ile razy to samo zamówienie przyszło w JEDNEJ paczce — patrz
        # „DUPLIKAT ZAMÓWIENIA W PACZCE" w docstringu.
        'duplikaty_zamowien': 0,
    }

    # ZNALEZISKO DROBNE (przegląd Zadania 6): `zapisz_zamowienia(42)` wypuszczał
    # na zewnątrz `TypeError: 'int' object is not iterable` z pętli poniżej.
    # Ta funkcja jest wołana z zaczepu produkcji i z endpointu HTTP — jedno
    # i drugie łapie wyjątek i melduje awarię całej analityki, choć problemem
    # jest wyłącznie kształt argumentu. `None` traktujemy jak pustą paczkę
    # (tak było i tak wołają ją dzisiejsze ścieżki), cokolwiek innego
    # niż lista/krotka to błąd wołającego i tak go raportujemy.
    if zamowienia is None:
        zamowienia = []
    elif not isinstance(zamowienia, (list, tuple)):
        stat['bledy'].append({
            'order_id': None,
            'blad': f'Oczekiwano listy zamowien, dostano {type(zamowienia).__name__}',
        })
        logger.error('Zapis do sales_* dostal argument, ktory nie jest lista',
                     zrodlo=zrodlo, typ=type(zamowienia).__name__)
        _zglos_niepelny_zapis(stat, zrodlo)
        return stat

    # WŁASNA sesja analityki. Zamykana w `finally` — także przy wyjątku,
    # bo inaczej jedno połączenie zostawałoby wiszące przy każdej awarii,
    # a hosting ma limit 40 połączeń na użytkownika (awaria 1040/1203
    # w historii projektu).
    sesja = nowa_sesja_analityki()
    try:
        # Jedno sprawdzenie na paczkę, nie na zamówienie.
        ma_produkcje = _jest_tabela('prod_orders', sesja)
        ma_leady = _jest_tabela('leads', sesja)

        # ZNALEZISKO WAŻNE (przegląd Zadania 4, dedup.py:169): pamięć podręczna
        # indeksu leadów, współdzielona przez całą paczkę — patrz docstring
        # `_upsert_zamowienia` i `zbuduj_indeks_leadow`. Budowana leniwie (klucz
        # `'indeks'` pojawia się w środku, przy pierwszym kliencie bez leada),
        # więc paczka złożona wyłącznie z już dowiązanych klientów nie płaci
        # kosztu wczytania tabeli `leads` wcale.
        pamiec_leadow: Dict[str, object] = {}
        # Słownik źródeł BaseLinkera — też leniwie i raz na paczkę (patrz
        # `_slownik_z_pamieci`).
        pamiec_zrodel: Dict[str, object] = {}

        # Numery zamówień JUŻ wzięte w tej paczce — patrz „DUPLIKAT
        # ZAMÓWIENIA W PACZCE" w docstringu. Zbiór jest lokalny dla jednego
        # wywołania: powtórne wołanie `zapisz_zamowienia` z tym samym
        # zamówieniem to normalna, idempotentna synchronizacja, nie duplikat.
        # Numer trafia tu PRZED próbą zapisu, więc kopia druga jest pomijana
        # także wtedy, gdy pierwsza wywaliła się błędem: „pierwsza wygrywa"
        # ma znaczyć pierwszą, a nie „pierwszą, która się udała" — inaczej
        # o wyniku decydowałaby awaria. Oba zdarzenia są w `bledy`, a samo
        # zamówienie dojdzie przy najbliższej synchronizacji.
        przetworzone: set = set()

        for surowe in zamowienia:
            if not isinstance(surowe, dict):
                stat['pominiete'] += 1
                continue
            # ZNALEZISKO WAŻNE (przegląd Zadania 2): numer BL liczy się TUTAJ,
            # raz, i ten sam `bl_id` leci do `_upsert_zamowienia` — do wyszukania
            # wiersza I do jego zapisania. `_numer_bl` jest tą samą funkcją,
            # której używa mapper, więc nie ma jak się rozjechać.
            bl_id = _numer_bl(surowe)
            if bl_id is None:
                # ZNALEZISKO WAŻNE (przegląd Zadania 6): pomijamy, ale LICZYMY
                # także w `bledy`. Zamówienie bez numeru BaseLinkera przepada
                # cicho, a jest to sytuacja, o której użytkownik musi wiedzieć —
                # nie ma jak go potem dosynchronizować. Numeru nie znamy, więc
                # `order_id` w zgłoszeniu jest None (kształt wpisu bez zmian).
                stat['pominiete'] += 1
                stat['bledy'].append({
                    'order_id': None,
                    'blad': 'Zamowienie bez numeru BaseLinkera — pominiete',
                })
                continue
            if bl_id in przetworzone:
                # Druga (i każda kolejna) kopia tego samego zamówienia
                # w jednej paczce — pomijamy, liczymy i MELDUJEMY.
                stat['pominiete'] += 1
                stat['duplikaty_zamowien'] += 1
                stat['bledy'].append({
                    'order_id': bl_id,
                    'blad': 'Duplikat zamowienia w paczce — pominiety, '
                            'liczy sie pierwsza kopia',
                })
                logger.warning('Duplikat zamowienia w jednej paczce',
                               order_id=bl_id, zrodlo=zrodlo)
                continue
            przetworzone.add(bl_id)
            try:
                _upsert_zamowienia(surowe, bl_id, stat, sesja, ma_produkcje,
                                   ma_leady, pamiec_leadow, pamiec_zrodel)
            except Exception as blad:
                # Rollback WŁASNEJ sesji. Praca produkcji wisząca w `db.session`
                # jest poza tą transakcją i pozostaje nietknięta.
                sesja.rollback()
                stat['bledy'].append({'order_id': bl_id, 'blad': _krotki_opis_bledu(blad)})
                logger.error('Nie udalo sie zapisac zamowienia do analityki',
                             order_id=bl_id, zrodlo=zrodlo, error=str(blad))
    finally:
        try:
            sesja.close()
        except Exception as blad_zamkniecia:
            # Zamknięcie sesji nie może przesłonić wyniku paczki, ale ma
            # zostawić ślad — niezwrócone połączenie to problem operacyjny.
            logger.error('Nie udalo sie zamknac sesji analityki',
                         zrodlo=zrodlo, error=str(blad_zamkniecia))

    _zglos_niepelny_zapis(stat, zrodlo)
    logger.info('Zapis przyrostowy do sales_* zakonczony', **{
        k: v for k, v in stat.items() if k != 'bledy'})
    return stat


def opis_niepelnego_zapisu(stat: Dict[str, object]) -> Optional[str]:
    """Jednolinijkowe streszczenie tego, czego analityka NIE zapisała.

    None, gdy paczka przeszła w komplecie.

    ZNALEZISKO (kontrola adwersaryjna 22.09.2026): utrata danych była CICHA.
    Gdy błąd obsłużyło wnętrze `zapisz_zamowienia`, funkcja kończyła się
    „sukcesem" — `success` produkcji `True`, `blad` `None` — a informacja
    siedziała wyłącznie w liście `bledy`, której ani operator, ani log crona
    nie oglądał. Ten napis jest po to, żeby pominięcie dało się zobaczyć
    jednym spojrzeniem w log.
    """
    pominiete = int(stat.get('pominiete') or 0)
    bledy = stat.get('bledy') or []
    pozycje_pominiete = int(stat.get('pozycje_pominiete') or 0)
    podejrzane = int(stat.get('podejrzane_paczki_pozycji') or 0)
    duplikaty = int(stat.get('duplikaty_zamowien') or 0)
    if not pominiete and not bledy and not pozycje_pominiete and not podejrzane:
        return None
    # Kolejność i brzmienie dwóch pierwszych członów są związane: produkcja
    # sprawdza w nich podciąg („bledow 1") i pokazuje ten napis operatorowi.
    czesci = ['pominietych %d' % pominiete, 'bledow %d' % len(bledy)]
    if pozycje_pominiete:
        czesci.append('pozycji pominietych %d' % pozycje_pominiete)
    if podejrzane:
        czesci.append('podejrzanych przysylek pozycji %d' % podejrzane)
    if duplikaty:
        czesci.append('duplikatow zamowien w paczce %d' % duplikaty)
    return 'Zapis do analityki niepelny: ' + ', '.join(czesci)


def _zglos_zmiany_pozycji(stat: Dict[str, object], zrodlo: str) -> None:
    """Ostrzeżenie w logu o tym, co stało się z POZYCJAMI.

    Osobno od `opis_niepelnego_zapisu`, bo to dwie różne rzeczy. Usunięcie
    pozycji skasowanej w BaseLinkerze jest normalną, poprawną pracą — nie ma
    prawa zapalać operatorowi czerwonego komunikatu w arkuszu
    (`arkusz.js` pokazuje `zapis.ostrzezenie` przez `pokazBlad`). Ale CICHE
    być nie może: usunięty wiersz mógł nieść ręczną pracę, a nikt się o tym
    nie dowiadywał. Stąd ślad w logu na poziomie ostrzeżenia — z kompletem
    liczników, także tych o wierszach, których świadomie NIE ruszyliśmy.
    """
    zmiany = {
        'pozycje_usuniete': int(stat.get('pozycje_usuniete') or 0),
        'pozycje_pominiete': int(stat.get('pozycje_pominiete') or 0),
        'pozycje_zachowane_bez_klucza': int(
            stat.get('pozycje_zachowane_bez_klucza') or 0),
        'podejrzane_paczki_pozycji': int(
            stat.get('podejrzane_paczki_pozycji') or 0),
        # Podzbiór `pozycje_pominiete` z podanym powodem (reguła 6).
        'pozycje_powtorzony_klucz': int(
            stat.get('pozycje_powtorzony_klucz') or 0),
        'duplikaty_zamowien': int(stat.get('duplikaty_zamowien') or 0),
    }
    if not any(zmiany.values()):
        return
    logger.warning('Zapis do sales_* zmienil stan pozycji', zrodlo=zrodlo,
                   pozycje_nowe=stat.get('pozycje_nowe'),
                   pozycje_zaktualizowane=stat.get('pozycje_zaktualizowane'),
                   **zmiany)


def _zglos_niepelny_zapis(stat: Dict[str, object], zrodlo: str) -> None:
    """Ostrzeżenie do logu + `stat['ostrzezenie']` dla wołającego."""
    _zglos_zmiany_pozycji(stat, zrodlo)
    opis = opis_niepelnego_zapisu(stat)
    stat['ostrzezenie'] = opis
    if opis is None:
        return
    logger.warning('Zapis do sales_* niepelny', zrodlo=zrodlo,
                   pominiete=stat.get('pominiete'),
                   bledow=len(stat.get('bledy') or []),
                   pierwszy_blad=(stat['bledy'][0] if stat.get('bledy') else None))


# Szerokość kolumny `sales_orders.client_origin` (VARCHAR(50)). Nazwy źródeł
# w BaseLinkerze i w `prod_orders.order_source_name` mogą mieć do 100 znaków.
_DLUGOSC_POCHODZENIA = 50


def _puste_pochodzenie(wartosc) -> bool:
    """Czy pole pochodzenia jest PUSTE — NULL, pusty napis albo same spacje.

    Tylko takie pole wolno wypełnić. Każda inna wartość to czyjaś decyzja
    (ręczna poprawka w Arkuszu) i synchronizacja jej nie rusza.
    """
    return not (wartosc or '').strip()


def nazwa_pochodzenia(surowa) -> Optional[str]:
    """Nazwa źródła gotowa do `client_origin`: bez spacji na brzegach,
    przycięta do szerokości kolumny, `None` zamiast pustego napisu.

    Jedno miejsce dla trzech dróg: słownika BaseLinkera, produkcji i skryptu
    zaległości (`scripts/uzupelnij_pochodzenie_klienta.py`).
    """
    nazwa = (surowa or '').strip()[:_DLUGOSC_POCHODZENIA]
    return nazwa or None


def slownik_zrodel_baselinkera() -> Dict[str, Dict[int, str]]:
    """Słownik źródeł zamówień z BaseLinkera: kanał -> {id -> nazwa}.

    NIE piszemy drugiego wywołania API. Czytamy ISTNIEJĄCY odczyt
    produkcji (`BaselinkerSyncService.get_order_sources`, singleton
    `get_sync_service`), który ma własną pamięć podręczną na 12 godzin
    i pamięć awarii na 5 minut — synchronizacja produkcji i tak pyta o ten
    słownik przy tych samych zamówieniach, więc tu zwykle trafiamy w jej
    pamięć. Przy awarii API tamta metoda oddaje przestarzały słownik albo
    pusty — nigdy nie rzuca, ale wołający i tak jest osłonięty.

    Import lokalny: moduł produkcji importuje z kolei `modules.reports.ingest`
    (zaczep analityki w `process_orders_with_priority_logic`).
    """
    from modules.production.services.sync_service import get_sync_service
    return get_sync_service().get_order_sources()


def _slownik_z_pamieci(pamiec: Optional[Dict]) -> Optional[Dict[str, Dict[int, str]]]:
    """Słownik źródeł najwyżej RAZ na paczkę; `None`, gdy go nie ma.

    AWARIA NIE WYWRACA ZAPISU (partia E, punkt E6): wyjątek zamienia się
    w `None` i ostrzeżenie w logu, zamówienie zapisuje się dalej, a pole
    pochodzenia zostaje puste albo dostaje nazwę z produkcji. Kolejna
    synchronizacja uzupełni je sama, bo wypełniamy przy każdym zapisie.
    Awaria jest pamiętana na całą paczkę — sto zamówień to jedno nieudane
    pytanie, nie sto.
    """
    if pamiec is None:
        pamiec = {}
    if 'slownik' not in pamiec:
        try:
            pamiec['slownik'] = slownik_zrodel_baselinkera() or None
        except Exception as blad:
            logger.warning('Slownik zrodel BaseLinkera niedostepny - pochodzenie '
                           'klienta tylko z produkcji', error=str(blad))
            pamiec['slownik'] = None
    return pamiec['slownik']


def _pochodzenie_klienta(kanal: Optional[str], id_zrodla: Optional[int], bl_id: int,
                         sesja, ma_produkcje: bool,
                         pamiec_zrodel: Optional[Dict] = None) -> Optional[str]:
    """Propozycja `client_origin` dla zamówienia z PUSTYM pochodzeniem.

    Kolejność z decyzji użytkownika (partia E, punkt E6):
      1. słownik BaseLinkera po PARZE (kanał, id) przychodzącego zamówienia.
         Samo id jest niejednoznaczne — 0 to „Detal" w `personal`
         i „Zwrot do zamówienia" w `order_return`;
      2. nazwa z produkcji (`origin_z_produkcji`), gdy słownika brak albo nie
         zna pary;
      3. `None` — niczego nie zgadujemy (ani z e-maila, ani z nazwy klienta);
         karta pokaże „(brak)".
    Słownika nie pobieramy, gdy zamówienie nie ma pary — nie ma o co pytać.
    """
    if kanal and id_zrodla is not None:
        slownik = _slownik_z_pamieci(pamiec_zrodel)
        nazwa = nazwa_pochodzenia(((slownik or {}).get(kanal) or {}).get(id_zrodla))
        if nazwa:
            return nazwa
    if ma_produkcje:
        return origin_z_produkcji(bl_id, sesja)
    return None


def origin_z_produkcji(baselinker_order_id: int, sesja=None) -> Optional[str]:
    """Nazwa źródła zamówienia z modułu produkcji albo None.

    CZYTAMY `order_source_name`, NIE `order_source`. Ta druga kolumna trzyma
    KANAŁ (`shop` / `personal` / `allegro`), czyli dokładnie to, co mamy już
    w `sales_orders.order_source` — skopiowanie jej zdublowałoby jeden wymiar.
    `client_origin` ma nieść NAZWĘ źródła, bo to ona rozróżnia „Detal" od
    „Stały B2B" wewnątrz kanału ręcznego.

    NIE czytamy też `ProductionOrder.order_source_display`. To `@property`,
    nie kolumna (specyfikacja §8 krok 4 pomyliła jedno z drugim i dlatego
    ten krok backfillu nigdy się nie wykonał), a poza tym dla kanałów innych
    niż `personal` zwraca etykietę kanału („Sklep"), czyli znowu to samo,
    co już mamy.

    `client_origin` to VARCHAR(50), a `order_source_name` VARCHAR(100) —
    stąd przycięcie.
    """
    from modules.production.models import ProductionOrder
    aktywna = sesja if sesja is not None else db.session
    zamowienie = (aktywna.query(ProductionOrder)
                  .filter_by(baselinker_order_id=baselinker_order_id)
                  .first())
    if zamowienie is None:
        return None
    return nazwa_pochodzenia(zamowienie.order_source_name)
