# -*- coding: utf-8 -*-
"""Zapis zmian z arkusza sprzedażowego.

DWA ROZŁĄCZNE ZBIORY (spec §5.2)
================================
Kolumny tylko-CRM zapisują się lokalnie w jednej transakcji i commitują
niezależnie od BaseLinkera. Kolumny z BaseLinkera idą przez API i **zapisują
się lokalnie DOPIERO po potwierdzeniu z API** — nigdy odwrotnie, bo inaczej
CRM pokazywałby wartość, której w BaseLinkerze nie ma.

WALIDACJA JEST PER POLE, NIE PER PACZKA
=======================================
Jedna zła wartość nie ma prawa skasować pracy użytkownika w pozostałych
komórkach. Każda zmiana dostaje własny wynik: `zapisane` albo `odrzucone`
z powodem. Przeglądarka gasi te pierwsze i zostawia brudne te drugie.

UPRAWNIENIA W WARIANCIE ROLOWYM
===============================
Decyzja użytkownika z 22.09.2026: zapis zwrotny do BaseLinkera tylko dla
roli `admin`, edycja kolumn CRM-owych dla wszystkich z dostępem do modułu.
Sprawdzenie jest TUTAJ, po stronie serwera — atrybut `data-moze-wysylac`
w HTML-u służy interfejsowi, nie bezpieczeństwu.

DWA ŹRÓDŁA LIMITU DŁUGOŚCI (przegląd Zadania 10, [KRYTYCZNE])
===============================================================
`Pole.max_dlugosc` z rejestru (`fields.py`) to limit API BaseLinkera i
istnieje TYLKO dla pól, które tam idą. Kolumny czysto CRM-owe
(`client_origin`, `wood_species`, `wood_class`…) są w bazie zwykłymi
VARCHAR-ami i bez drugiego źródła limitu — wprost z modelu
(`_limit_kolumny_modelu`) — nadmiar leciałby do `db.session.commit()`
i na MySQL-u w trybie `STRICT_TRANS_TABLES` wywalał błędem 1406 CAŁĄ
paczkę kolumn CRM, nie tylko złą komórkę.
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Dict, List, Optional, Tuple

from extensions import db
from modules.logging import get_structured_logger
from modules.reports.analiza_service import dzis_lokalnie
from modules.reports.arkusz_service import (
    NAJWCZESNIEJSZA_DATA, kolumna_arkusza, moze_wysylac_do_bl, sformatuj, surowa,
)
from modules.reports.bl_zapis import (
    KOLEJNOSC_METOD, BladBaselinkera, buduj_ladunek, data_platnosci_efektywna,
)
from modules.reports.fields import POLA
from modules.reports.ingest import (
    _kwota_w_zakresie, _powierzchnia_m2, _przelicz_klienta, saldo_z_wierszy,
)
from modules.reports.models_sales import SalesOrder, SalesOrderItem

logger = get_structured_logger('reports.arkusz.zapis')

# Zaporowa wielkość paczki. Arkusz z 55 kolumnami i 200 zamówieniami na
# stronie pozwala teoretycznie zaznaczyć tysiące komórek; paczka tej
# wielkości to i tak pomyłka, a nie intencja.
MAKS_ZMIAN = 500

# Ile WYWOŁAŃ API BaseLinkera wolno zrobić w jednej paczce (przegląd fali 3,
# [WAŻNE]). `MAKS_ZMIAN` ogranicza liczbę komórek, a nie liczbę strzałów do
# API: 500 zmian statusu na 500 zamówieniach to 500 SEKWENCYJNYCH POST-ów,
# każdy z `timeout=30` (`KlientBL`), w JEDNYM żądaniu HTTP trzymającym worker
# gunicorna. Trzy niezależne granice mówią, ile wolno:
#   * BaseLinker przyjmuje 100 żądań na minutę na token — powyżej zaczyna
#     odrzucać, czyli końcówka paczki poszłaby do kosza;
#   * domyślny `proxy_read_timeout` nginxa to 60 s, a przeglądarka i tak
#     nie ma jak pokazać postępu — użytkownik zobaczyłby błąd sieci, nie
#     wiedząc, ile zmian weszło;
#   * przy typowych 0,3–0,6 s na wywołanie 50 strzałów to 15–30 s, czyli
#     mieści się pod oboma progami z zapasem.
# Stąd 50. Paczka większa NIE jest wysyłana częściowo — użytkownik dostaje
# komunikat, żeby podzielić ją na porcje (wysłanie połowy i urwanie się
# w środku jest gorsze niż nie wysłanie niczego).
MAKS_WYWOLAN_BL = 50

# Ile dni w przód wolno wpisać datę płatności — wpłaty księgowane z
# wyprzedzeniem (np. przedpłata zaksięgowana „na jutro") się zdarzają,
# rok 9999 nie (przegląd Zadania 11, [WAŻNE]).
_DNI_PRZYSZLOSCI_PLATNOSCI = 7

# Kwota netto->brutto dla pozycji (patrz `_przelicz_ceny_pozycji`) — ten sam
# mnożnik, co `bl_zapis._VAT` i `ingest._VAT`. Duplikat literału, nie
# importu: to stała czysto arytmetyczna, nie warto po nią ciągnąć
# zależności między modułami.
_VAT = Decimal('1.23')

_POZIOMY = ('zamowienie', 'pozycja')

# Trzy wymiary pozycji, po których liczą się kolumny WYLICZANE
# (`volume_per_piece`, `total_volume`, `total_surface_m2`, `price_per_m3`) —
# patrz `_przelicz_pochodne_pozycji`.
_WYMIARY_POZYCJI = ('length_cm', 'width_cm', 'thickness_cm')

# Kolumny `id` w `sales_orders`/`sales_order_items` są INT, nie BIGINT.
_MAKS_ID = 2 ** 31 - 1

# PRZEGLĄD ZADANIA 11, [KRYTYCZNE]: bez dolnej granicy ujemna ilość, ujemna
# wpłata i ujemny koszt kuriera przechodziły walidację i leciały do
# BaseLinkera (setOrderProductFields quantity=-5, setOrderPayment
# payment_done=-1000.0, setOrderFields delivery_price=-99.0) — rozjeżdżając
# stan magazynowy i robiąc z zamówienia nadpłatę ze znakiem minus.
#
# PRZEGLĄD FALI 3, [WAŻNE]: dołożone trzy wymiary pozycji. Ujemna długość
# przechodziła walidację, a `_przelicz_pochodne_pozycji` zapisywał z niej
# UJEMNĄ objętość (zmierzone: length_cm=-120 → total_volume < 0) — liczba
# fizycznie niemożliwa, która wchodziła do sumy „TTL m³" w stopce arkusza
# i do przychodu w m³ na dashboardzie, zaniżając je bez śladu.
_POLA_NIEUJEMNE = frozenset({'quantity', 'paid_amount', 'price_gross', 'delivery_cost',
                             'length_cm', 'width_cm', 'thickness_cm'})
# Ilość dodatkowo nie może być zerem — zero sztuk to nie jest pozycja
# zamówienia, a pusta komórka (patrz `na_wartosc`, typ 'liczba') dawała
# wcześniej `int(None)` i angielski `TypeError` prosto do interfejsu
# (przegląd Zadania 11, [WAŻNE]).
_POLA_TYLKO_DODATNIE = frozenset({'quantity'})

# SKŁADNIKI SALDA (przegląd fali 3, [KRYTYCZNE]). `sales_orders.balance_due`
# to kolumna ZAPISANA, wypełniana przez `ingest.mapuj_zamowienie` przy
# synchronizacji — nic jej nie liczy w locie przy odczycie. Po edycji
# któregokolwiek z tych pól saldo w bazie zostawało sprzed edycji (zmierzone:
# paid_amount 0,00 → 1,00, a balance_due dalej 0,00), więc kolumna „Saldo"
# w arkuszu, kafelek KPI, kubełki należności i nadpłaty pokazywały cicho
# złą liczbę. Rozbite na dwa zbiory, bo `zmiana.poziom` rozstrzyga, którego
# rekordu dotyczy nazwa.
#
# „GRUPA" ZOSTAJE W ZBIORZE, CHOĆ NIE JEST JUŻ SKŁADNIKIEM SALDA (fala 6).
# Do 22.09.2026 saldo pomijało pozycje usługowe, więc przeniesienie pozycji
# do usług naprawdę zmieniało liczbę. Od fali 6 saldo liczy się ze WSZYSTKICH
# pozycji (uzasadnienie i pomiar: `ingest.oblicz_saldo`), czyli przeliczenie
# po zmianie grupy daje ten sam wynik. Zostaje z dwóch powodów: jest to
# JEDYNA kolumna tylko-CRM wyzwalająca gałąź przeliczenia salda przy zapisie
# bez BaseLinkera (bez niej ta gałąź nie miałaby żadnego wyzwalacza ani
# pokrycia testem), a samo przeliczenie jest idempotentne. Pilnuje tego
# `test_zmiana_grupy_pozycji_nie_rusza_salda`.
_POLA_SALDA_ZAMOWIENIA = frozenset({'paid_amount', 'delivery_cost', 'price_type'})
_POLA_SALDA_POZYCJI = frozenset({'quantity', 'price_gross', 'group_type'})


class BladWalidacji(ValueError):
    """Wejście, którego nie da się przetworzyć w całości. Kończy się 400."""


@dataclass(frozen=True)
class Zmiana:
    poziom: str
    id: int
    nazwa: str
    jest: str
    # Wartość SUROWA sprzed edycji, w formacie `arkusz_service.surowa`.
    # Służy strażnikowi optymistycznemu. `None` znaczy „nie sprawdzaj" i jest
    # przewidziane WYŁĄCZNIE dla testów jednostkowych — `parsuj_zmiany`
    # wymaga tego pola od każdego żądania HTTP.
    bylo: Optional[str] = None

    @property
    def klucz(self) -> str:
        # TEN SAM format buduje arkusz.js (funkcja `klucz`). Rozjazd oznacza
        # „zapisano" nad komórką, której nikt nie zapisał.
        return '{}:{}:{}'.format(self.poziom, self.id, self.nazwa)


def parsuj_zmiany(cialo) -> List[Zmiana]:
    """Lista zmian z ciała żądania. Rzuca BladWalidacji z komunikatem po polsku.

    Tu odrzucamy wyłącznie to, co czyni paczkę nieprzetwarzalną: zły kształt,
    pusta lista, absurdalna wielkość, brak wymaganych pól. Wszystko, co da się
    ocenić per pole (edytowalność, typ, limit długości, uprawnienia), rozstrzyga
    `zapisz` i zwraca jako `odrzucone` — inaczej jedna literówka kasowałaby
    całą pracę użytkownika.
    """
    if not isinstance(cialo, dict):
        raise BladWalidacji('oczekiwano obiektu JSON z listą „zmiany"')
    surowe = cialo.get('zmiany')
    if not isinstance(surowe, list) or not surowe:
        raise BladWalidacji('lista „zmiany" jest pusta albo nie jest listą')
    if len(surowe) > MAKS_ZMIAN:
        raise BladWalidacji(f'za dużo zmian naraz (limit {MAKS_ZMIAN})')

    zmiany = []
    widziane_klucze = set()
    for wpis in surowe:
        if not isinstance(wpis, dict):
            raise BladWalidacji('każda zmiana musi być obiektem JSON')
        poziom = wpis.get('poziom')
        if poziom not in _POZIOMY:
            raise BladWalidacji(f"'{poziom}' nie jest poziomem "
                                f"(dozwolone: {', '.join(_POZIOMY)})")
        try:
            identyfikator = int(wpis.get('id'))
        except (TypeError, ValueError, OverflowError):
            # OverflowError, a nie tylko TypeError/ValueError (przegląd
            # fali 3, [KRYTYCZNE]): `{"id": 1e999}` to POPRAWNY JSON, Flask
            # parsuje go do `float('inf')`, a `int(inf)` rzuca właśnie
            # OverflowError. Nie łapany, szedł przez `parsuj_zmiany` aż do
            # obsługi błędów Flaska — endpoint oddawał 500 zamiast 400
            # z komunikatem. `float('nan')` daje w tym miejscu ValueError,
            # więc mieści się w tej samej gałęzi.
            raise BladWalidacji(f"'{wpis.get('id')}' nie jest identyfikatorem wiersza")
        # GÓRNA GRANICA IDENTYFIKATORA (przegląd Zadania 10, [WAŻNE]).
        # Kolumny `id` są INT, więc `2**31-1` to i tak jedyna sensowna
        # wartość. Bez tej granicy absurdalnie duży `id` (np. 10**30)
        # dociera do `Model.query.get()`, gdzie na SQLite rzuca
        # `OverflowError` PRZED try/except w `zapisz()` — endpoint oddaje
        # 500 zamiast czytelnego 400.
        if identyfikator <= 0 or identyfikator > _MAKS_ID:
            raise BladWalidacji('identyfikator wiersza musi być liczbą dodatnią, '
                                f'nie większą niż {_MAKS_ID}')
        nazwa = wpis.get('nazwa')
        # `isinstance` PRZED `in POLA` (przegląd fali 3, [KRYTYCZNE], ta sama
        # klasa błędu co `int(inf)` wyżej): `POLA` jest słownikiem, więc
        # `['client_origin'] in POLA` rzuca `TypeError: unhashable type:
        # 'list'` — a lista albo obiekt w polu „nazwa" to POPRAWNY JSON,
        # który tą drogą kończył się 500 zamiast czytelnego 400.
        if not isinstance(nazwa, str) or nazwa not in POLA \
                or POLA[nazwa].skladniki is not None:
            raise BladWalidacji(f"'{nazwa}' nie jest kolumną arkusza")
        if 'jest' not in wpis:
            raise BladWalidacji(f"zmiana kolumny '{nazwa}' nie niesie nowej wartości")
        # Strażnik optymistyczny: bez wartości pierwotnej nie da się wykryć,
        # że ktoś zmienił tę komórkę w międzyczasie. Wymagamy jej od KAŻDEGO
        # żądania HTTP — inaczej klient, który jej nie wyśle, po cichu
        # ominąłby zabezpieczenie.
        if 'bylo' not in wpis:
            raise BladWalidacji(f"zmiana kolumny '{nazwa}' nie niesie wartości "
                                f"pierwotnej — bez niej nie wykryjemy, czy ktoś "
                                f"nie zmienił jej w międzyczasie")
        zmiana = Zmiana(poziom, identyfikator, nazwa,
                        '' if wpis['jest'] is None else str(wpis['jest']),
                        '' if wpis['bylo'] is None else str(wpis['bylo']))
        # DWIE ZMIANY O TYM SAMYM KLUCZU W JEDNEJ PACZCE (przegląd Zadania 10,
        # [WAŻNE]). `zapisz()` przetwarza wpisy niezależnie — obie dostałyby
        # status „zapisane", a w bazie zostałaby tylko ta ostatnia. Zadanie 12
        # odnajduje komórkę po kluczu, więc pierwsza podświetliłaby się na
        # zielono z wartością, której w bazie nie ma. Odrzucamy całą paczkę:
        # dziś to nieosiągalne z arkusza (`arkusz.js` trzyma zmiany w mapie
        # po kluczu), ale endpoint jest granicą bezpieczeństwa, nie widok.
        if zmiana.klucz in widziane_klucze:
            raise BladWalidacji('paczka zawiera dwie zmiany tej samej komórki '
                                f"'{zmiana.klucz}'")
        widziane_klucze.add(zmiana.klucz)
        zmiany.append(zmiana)
    return zmiany


def _kolumna_modelu(poziom: str, nazwa: str):
    """Kolumna SQLAlchemy odpowiadająca (poziom, nazwa) albo None."""
    model = SalesOrder if poziom == 'zamowienie' else SalesOrderItem
    return model.__table__.columns.get(nazwa)


def _limit_kolumny_modelu(poziom: str, nazwa: str) -> Optional[int]:
    """Maksymalna długość VARCHAR-a w bazie dla tej kolumny, albo None."""
    kolumna_modelu = _kolumna_modelu(poziom, nazwa)
    if kolumna_modelu is None:
        return None
    dlugosc = getattr(kolumna_modelu.type, 'length', None)
    return int(dlugosc) if dlugosc else None


def _limit_dlugosci(kolumna: Dict) -> Optional[int]:
    """Mniejszy z dwóch limitów długości: API BaseLinkera i VARCHAR-a w bazie.

    `kolumna['max_dlugosc']` to WYŁĄCZNIE limit API — istnieje tylko dla pól
    z `Zrodlo.BL`. Kolumny tylko-CRM nie mają go wcale i bez tej drugiej
    strony nie miały ŻADNEGO ograniczenia długości.
    """
    limity = [l for l in (kolumna['max_dlugosc'],
                          _limit_kolumny_modelu(kolumna['poziom'], kolumna['nazwa']))
             if l is not None]
    return min(limity) if limity else None


def _zakres_kolumny_modelu(poziom: str, nazwa: str) -> Optional[Tuple[int, int]]:
    """(precyzja, skala) kolumny NUMERIC w bazie, albo None.

    Używane do dwóch rzeczy naraz: odcięcia wartości spoza zakresu kolumny
    (MySQL w trybie ścisłym odrzuca całą transakcję błędem 1264/1366) i
    kwantyzacji do WŁAŚCIWEJ liczby miejsc po przecinku PRZED zapisem — ten
    sam zaokrąglony wynik idzie potem do `sformatuj()`, więc tekst nad
    komórką po zapisie zawsze zgadza się z tym, co naprawdę wylądowało
    w bazie (przegląd Zadania 10, [WAŻNE] — MySQL zaokrągla decimal(10,2)
    w górę od połówki, a domyślne formatowanie Decimal w Pythonie zaokrągla
    do parzystej; bez wspólnej kwantyzacji te dwie strony się rozjeżdżały).
    """
    kolumna_modelu = _kolumna_modelu(poziom, nazwa)
    if kolumna_modelu is None:
        return None
    precyzja = getattr(kolumna_modelu.type, 'precision', None)
    skala = getattr(kolumna_modelu.type, 'scale', None)
    if precyzja is None or skala is None:
        return None
    return int(precyzja), int(skala)


def _zakres_calkowitej(poziom: str, nazwa: str) -> Optional[Tuple[int, int]]:
    """(minimum, maksimum) kolumny całkowitej w bazie, albo None.

    PRZEGLĄD FALI 3, [KRYTYCZNE]: `_zakres_kolumny_modelu` czyta
    `precision`/`scale`, których kolumna `db.Integer` po prostu NIE MA —
    zwracała więc None i gałąź `typ == 'liczba'` w `na_wartosc` nie miała
    ŻADNEJ górnej granicy. „Ilość" = 99999999999 przechodziła walidację
    i LECIAŁA DO BASELINKERA (`setOrderProductFields` z tą wartością,
    potwierdzone uruchomieniem na atrapie), a dopiero potem commit lokalny
    wywracał się na MySQL-u błędem 1264 — czyli BaseLinker dostawał ilość,
    której CRM nie był w stanie zapisać.

    Granica bierze się z TYPU kolumny, nie z domysłu o rozsądnej ilości
    sztuk: INT to ±2^31, BIGINT ±2^63, SMALLINT ±2^15. Kolejność sprawdzeń
    ma znaczenie — nazwa klasy `BigInteger` zawiera w sobie `Integer`.
    """
    kolumna_modelu = _kolumna_modelu(poziom, nazwa)
    if kolumna_modelu is None:
        return None
    nazwa_typu = kolumna_modelu.type.__class__.__name__.lower()
    for fragment, bitow in (('smallinteger', 16), ('biginteger', 64), ('integer', 32)):
        if fragment in nazwa_typu:
            return -(2 ** (bitow - 1)), 2 ** (bitow - 1) - 1
    return None


def _wymaga_wartosci(poziom: str, nazwa: str) -> bool:
    """Czy kolumna w bazie jest NOT NULL — pustej wartości nie wolno jej wysłać.

    `na_wartosc` zwraca dla pustego tekstu bezwarunkowo `None`. Dla kolumny
    typu `sales_orders.paid_cash` (decimal(10,2) NOT NULL) to
    `setattr(..., None)`, który na commicie wywala `IntegrityError` — a przez
    `except Exception` w `zapisz()` kasuje CAŁĄ paczkę kolumn CRM, więc
    poprawna edycja sąsiedniej komórki ginie bez winy użytkownika (przegląd
    Zadania 10, [KRYTYCZNE]).
    """
    kolumna_modelu = _kolumna_modelu(poziom, nazwa)
    return bool(kolumna_modelu is not None and not kolumna_modelu.nullable)


def na_wartosc(kolumna: Dict, tekst: str):
    """Tekst z przeglądarki na wartość kolumny. Rzuca ValueError po polsku.

    Format wejścia jest ten sam, który `arkusz_service.surowa` wysyła do
    przeglądarki: kropka dziesiętna, data ISO, `true`/`false`. Przecinek
    dziesiętny odrzucamy świadomie — inaczej „10,50" i „10.50" znaczyłyby
    to samo w jednym miejscu, a w innym nie.
    """
    tekst = (tekst or '').strip()
    typ = kolumna['typ']
    if tekst == '':
        # WYJĄTEK: pola, które muszą być liczbą DODATNIĄ (dziś: `quantity`),
        # nie mają czego zwrócić dla pustej komórki. Bez tego wyjątku
        # pusty tekst szedł dalej jako `None`, a `buduj_ladunek` wołał na
        # nim goły `int(None)` — angielski `TypeError` trafiał prosto do
        # interfejsu (przegląd Zadania 11, [WAŻNE]).
        if kolumna['nazwa'] in _POLA_TYLKO_DODATNIE:
            raise ValueError('pole „{}" nie może być puste — wpisz liczbę '
                             'większą od zera'.format(kolumna['etykieta']))
        return None
    if typ in ('kwota', 'objetosc'):
        try:
            wartosc = Decimal(tekst)
        except InvalidOperation:
            raise ValueError(f"'{tekst}' nie jest liczbą (użyj kropki dziesiętnej)")
        # WARTOŚCI SPECJALNE (przegląd Zadania 10, [KRYTYCZNE]). `Decimal()`
        # NIE rzuca `InvalidOperation` dla 'NaN', 'Infinity', '-Infinity',
        # 'inf' ani 'sNaN' — wszystkie parsują się „poprawnie". Bez tego
        # sprawdzenia nieskończoność wchodziła do kolumny kwotowej i truła
        # każdą sumę w stopce i na dashboardzie (SQLite), a na MySQL-u
        # commit padał błędem 1366 i kasował całą paczkę kolumn CRM.
        if not wartosc.is_finite():
            raise ValueError(f"'{tekst}' nie jest liczbą (użyj kropki dziesiętnej)")
        zakres = _zakres_kolumny_modelu(kolumna['poziom'], kolumna['nazwa'])
        if zakres:
            precyzja, skala = zakres
            cyfry_calkowite = precyzja - skala
            try:
                wartosc = wartosc.quantize(Decimal(1).scaleb(-skala),
                                           rounding=ROUND_HALF_UP)
            except InvalidOperation:
                # Kwantyzacja sama rzuca dla liczb tak ogromnych (np.
                # '1E+40'), że przekraczają domyślną precyzję Decimal
                # (28 cyfr) — i tak nie zmieściłyby się w kolumnie.
                raise ValueError(f"'{tekst}' jest za duża dla tej kolumny "
                                 f"(maksymalnie {cyfry_calkowite} cyfr "
                                 f"przed przecinkiem)")
            if abs(wartosc) >= Decimal(10) ** cyfry_calkowite:
                raise ValueError(f"'{tekst}' jest za duża dla tej kolumny "
                                 f"(maksymalnie {cyfry_calkowite} cyfr "
                                 f"przed przecinkiem)")
        # DOLNA GRANICA (przegląd Zadania 11, [KRYTYCZNE]). Bez niej ujemna
        # wpłata/cena/koszt kuriera przechodziły walidację i leciały do
        # BaseLinkera — robiąc z zamówienia nadpłatę ze znakiem minus.
        if kolumna['nazwa'] in _POLA_NIEUJEMNE and wartosc < 0:
            raise ValueError('pole „{}" nie może być ujemne'.format(
                kolumna['etykieta']))
        return wartosc
    if typ == 'liczba':
        try:
            wartosc = int(tekst)
        except ValueError:
            raise ValueError(f"'{tekst}' nie jest liczbą całkowitą")
        if kolumna['nazwa'] in _POLA_TYLKO_DODATNIE and wartosc <= 0:
            raise ValueError('pole „{}" musi być liczbą większą od zera'.format(
                kolumna['etykieta']))
        elif kolumna['nazwa'] in _POLA_NIEUJEMNE and wartosc < 0:
            raise ValueError('pole „{}" nie może być ujemne'.format(
                kolumna['etykieta']))
        # GÓRNA GRANICA Z TYPU KOLUMNY (przegląd fali 3, [KRYTYCZNE]) —
        # patrz `_zakres_calkowitej`. Sprawdzana PO znaku, żeby ujemna ilość
        # dostała swój czytelniejszy komunikat, a nie suchy zakres.
        zakres_calkowity = _zakres_calkowitej(kolumna['poziom'], kolumna['nazwa'])
        if zakres_calkowity and not (zakres_calkowity[0] <= wartosc <= zakres_calkowity[1]):
            raise ValueError('„{}" jest poza zakresem kolumny „{}" ({} – {})'.format(
                tekst, kolumna['etykieta'], zakres_calkowity[0], zakres_calkowity[1]))
        return wartosc
    if typ == 'data':
        try:
            wartosc = datetime.strptime(tekst, '%Y-%m-%d').date()
        except ValueError:
            raise ValueError(f"'{tekst}' nie jest datą w formacie RRRR-MM-DD")
        # OSŁONA ZAKRESU DATY PŁATNOŚCI (przegląd Zadania 11, [WAŻNE]).
        # `na_wartosc` sprawdzała wyłącznie FORMAT — data w formacie
        # poprawnym, ale absurdalnej wartości ('1900-01-01', '9999-12-31',
        # a skrajnie '0001-01-01') przechodziła dalej jako 'zapisana' i
        # leciała do BaseLinkera jako sfabrykowany unixtime, albo — dla dat
        # tak skrajnych, że `datetime.timestamp()` sobie z nimi nie radzi
        # na niektórych platformach — wywalała angielski wyjątek systemowy
        # prosto do interfejsu. Okno jest takie samo, jak dla okna dat
        # arkusza (`NAJWCZESNIEJSZA_DATA`), plus kilka dni w przód na
        # wpłaty księgowane z wyprzedzeniem.
        if kolumna['nazwa'] == 'payment_date':
            gorna_granica = dzis_lokalnie() + timedelta(days=_DNI_PRZYSZLOSCI_PLATNOSCI)
            if not (NAJWCZESNIEJSZA_DATA <= wartosc <= gorna_granica):
                raise ValueError(
                    "'{}' jest poza dopuszczalnym zakresem daty płatności "
                    '({} – {})'.format(tekst, NAJWCZESNIEJSZA_DATA.isoformat(),
                                       gorna_granica.isoformat()))
        return wartosc
    if typ == 'logiczna':
        if tekst not in ('true', 'false'):
            raise ValueError(f"'{tekst}' nie jest wartością tak/nie")
        return tekst == 'true'
    if typ == 'wybor':
        if tekst not in (kolumna['opcje'] or []):
            # `current_status` ma dedykowany komunikat (istniejące testy go
            # pilnują) — każda INNA kolumna typu 'wybor' (np. Enum z bazy,
            # patrz `price_type`) dostaje komunikat ogólny z etykietą pola.
            if kolumna['nazwa'] == 'current_status':
                raise ValueError(f"'{tekst}' nie jest znanym statusem BaseLinkera")
            raise ValueError('„{}" nie jest dozwoloną wartością pola „{}"'.format(
                tekst, kolumna['etykieta']))
        return tekst
    limit = _limit_dlugosci(kolumna)
    if limit and len(tekst) > limit:
        raise ValueError(f"wartość dłuższa niż {limit} znaków")
    return tekst


def _wiersz(zmiana: Zmiana):
    model = SalesOrder if zmiana.poziom == 'zamowienie' else SalesOrderItem
    return model.query.get(zmiana.id)


def _przelicz_pochodne_pozycji(wiersz: SalesOrderItem) -> None:
    """Przelicza kolumny WYLICZANE pozycji po edycji jednego z trzech wymiarów.

    `volume_per_piece`, `total_volume`, `total_surface_m2` i `price_per_m3`
    to kolumny ZAPISANE w `sales_order_items`, wypełniane przez `ingest.py`
    przy synchronizacji — arkusz je tylko CZYTA (`arkusz_service._wypelnij`
    robi goły `getattr`). Bez przeliczenia tutaj, po ręcznej poprawce
    grubości użytkownik widziałby w jednym wierszu nową grubość i starą
    objętość, a suma „TTL m³" w stopce zostawałaby błędna — cicho zła liczba
    wyprodukowana przez samą ścieżkę zapisu (przegląd Zadania 10, [WAŻNE]).

    Ten sam wzór, co `ingest.mapuj_pozycje` — wołany stąd wprost (import
    `_kwota_w_zakresie`/`_powierzchnia_m2`), żeby nie dublować logiki i nie
    dopuścić do rozjazdu dwóch miejsc liczących to samo.
    """
    dlugosc, szerokosc, grubosc = wiersz.length_cm, wiersz.width_cm, wiersz.thickness_cm
    ilosc = wiersz.quantity or 0

    if dlugosc is not None and szerokosc is not None and grubosc is not None:
        objetosc_szt = ((Decimal(str(dlugosc)) / 100)
                        * (Decimal(str(szerokosc)) / 100)
                        * (Decimal(str(grubosc)) / 100))
        objetosc_ttl = objetosc_szt * ilosc
    else:
        objetosc_szt = None
        objetosc_ttl = None

    powierzchnia = _powierzchnia_m2(dlugosc, szerokosc, grubosc, ilosc)
    cena_m3 = ((wiersz.value_net / objetosc_ttl)
              if (objetosc_ttl and wiersz.value_net is not None) else None)

    wiersz.volume_per_piece = _kwota_w_zakresie(objetosc_szt, '0.000001', 4,
                                                'volume_per_piece')
    wiersz.total_volume = _kwota_w_zakresie(objetosc_ttl, '0.000001', 4, 'total_volume')
    wiersz.total_surface_m2 = _kwota_w_zakresie(powierzchnia, '0.0001', 6,
                                                'total_surface_m2')
    wiersz.price_per_m3 = _kwota_w_zakresie(cena_m3, '0.01', 8, 'price_per_m3')


def _przelicz_ceny_pozycji(wiersz: SalesOrderItem) -> None:
    """Przelicza `price_net`/`value_gross`/`value_net` po edycji `quantity`
    lub `price_gross` przez BaseLinkera (`setOrderProductFields`).

    Ten sam wzór, co `ingest.mapuj_pozycje`: niezależnie od typu ceny
    zamówienia obie jego gałęzie redukują się algebraicznie do tego samego
    ilorazu, `price_net = price_gross / VAT` — `price_gross` w bazie jest
    zawsze prawdziwą ceną BRUTTO (to ona leci do BaseLinkera jako
    `price_brutto`), więc przeliczenie nie potrzebuje `zamowienie.price_type`.

    Bez tego przeliczenia zmiana `quantity`/`price_gross` w BaseLinkerze
    zostawiała stare `price_net`/`value_gross`/`value_net` policzone dla
    poprzedniej ilości/ceny — cicho zła liczba w głównym KPI projektu
    (suma „TTL m³"/przychód w m³ na dashboardzie), dokładnie ta sama klasa
    błędu, którą `_przelicz_pochodne_pozycji` naprawia dla wymiarów
    (przegląd Zadania 11, [KRYTYCZNE]). Wołane RAZEM z
    `_przelicz_pochodne_pozycji` — `price_per_m3` liczy się z `value_net`,
    który ta funkcja dopiero tutaj aktualizuje.
    """
    if wiersz.price_gross is None:
        return
    ilosc = wiersz.quantity or 0
    cena_netto = wiersz.price_gross / _VAT
    wiersz.price_net = _kwota_w_zakresie(cena_netto, '0.01', 8, 'price_net')
    wiersz.value_gross = _kwota_w_zakresie(wiersz.price_gross * ilosc, '0.01', 8,
                                           'value_gross')
    wiersz.value_net = _kwota_w_zakresie(cena_netto * ilosc, '0.01', 8, 'value_net')


def _rusza_saldo(zmiana: Zmiana) -> bool:
    """Czy ta zmiana zmienia którykolwiek składnik salda zamówienia."""
    zbior = (_POLA_SALDA_ZAMOWIENIA if zmiana.poziom == 'zamowienie'
             else _POLA_SALDA_POZYCJI)
    return zmiana.nazwa in zbior


def _przelicz_saldo(zamowienie: SalesOrder) -> None:
    """Przelicza `SalesOrder.balance_due` po edycji dowolnego jego składnika.

    Wzoru TU JUŻ NIE MA — jest jeden, wspólny, w `ingest.saldo_z_wierszy`
    (nad nim `ingest.oblicz_saldo`). Do fali 5 obie strony liczyły saldo
    same i przy zamówieniu z wierszem-dziedzictwem dawały DWIE różne liczby
    (zmierzone: synchronizacja 800,00, przeliczenie w arkuszu 1600,00) —
    czyli saldo przesuwało się w dniu pierwszej ręcznej edycji, bez żadnego
    zdarzenia biznesowego pod spodem. Uzasadnienie wyboru zbioru pozycji
    (wiersze, nie przysyłka) siedzi w docstringu `saldo_z_wierszy`.

    Kwantyzacja tam idzie przez `_kwota` (do grosza), a NIE przez
    `_kwota_w_zakresie`: ta druga zwraca `None` dla wartości spoza kolumny,
    a `balance_due` jest NOT NULL — zapis `None` wywróciłby commit i skasował
    całą paczkę. Wartość spoza DECIMAL(10,2) i tak zatrzyma commit, ale
    z rollbackiem i polskim komunikatem, czyli bez cichej złej liczby w bazie.
    """
    zamowienie.balance_due = saldo_z_wierszy(zamowienie)


def _sprawdz(zmiana: Zmiana, kolumna: Dict, wiersz, uzytkownik,
             klient_bl) -> Optional[str]:
    """Powód odrzucenia zmiany albo None, gdy wolno ją zapisać."""
    if not kolumna['edytowalne']:
        return 'kolumna „{}" nie jest edytowalna'.format(kolumna['etykieta'])
    if kolumna['poziom'] != zmiana.poziom:
        return ('kolumna „{}" jest na poziomie „{}", a zmiana przyszła '
                'z poziomu „{}"').format(kolumna['etykieta'], kolumna['poziom'],
                                         zmiana.poziom)
    if wiersz is None:
        return 'wiersz nie istnieje albo został w międzyczasie usunięty'

    # LIMIT DŁUGOŚCI — mniejszy z limitu API BaseLinkera i VARCHAR-a w bazie
    # (patrz `_limit_dlugosci`).
    limit = _limit_dlugosci(kolumna)
    if limit and len(zmiana.jest) > limit:
        return (f"wartość ma {len(zmiana.jest)} znaków, "
                f"a kolumna przyjmuje najwyżej {limit} znaków")

    # PUSTA WARTOŚĆ W KOLUMNIE NOT NULL. Odrzucamy TUTAJ, zanim cokolwiek
    # dotknie sesji — inaczej `setattr(..., None)` wywraca commit
    # `IntegrityError`-em i kasuje całą paczkę (patrz `_wymaga_wartosci`).
    if not (zmiana.jest or '').strip() and _wymaga_wartosci(zmiana.poziom, zmiana.nazwa):
        return 'to pole nie może być puste — wpisz jakąś wartość'

    # STRAŻNIK OPTYMISTYCZNY. Domyślnie porównujemy w formacie SUROWYM — tym
    # samym, który poszedł do przeglądarki. Dla kwot/objętości porównujemy
    # PO WARTOŚCI (przez `na_wartosc`), nie po napisie: „2.70" i „2.7" to
    # ten sam Decimal, a różny napis — bez tego druga edycja zaokrąglonej
    # kwoty (serwer zwraca WYŁĄCZNIE tekst sformatowany, nigdy kanonicznej
    # wartości surowej) dostawała fałszywy komunikat o równoległej edycji
    # (przegląd Zadania 10, [WAŻNE]).
    if zmiana.bylo is not None:
        aktualna = getattr(wiersz, zmiana.nazwa, None)
        if kolumna['typ'] in ('kwota', 'objetosc'):
            try:
                bylo_wartosc = na_wartosc(kolumna, zmiana.bylo)
            except ValueError:
                bylo_wartosc = None
            zgadza_sie = bylo_wartosc == aktualna
        else:
            zgadza_sie = surowa(aktualna, kolumna['typ']) == zmiana.bylo
        if not zgadza_sie:
            teraz = surowa(aktualna, kolumna['typ'])
            return ('ktoś zmienił tę komórkę w międzyczasie (jest „{}", '
                    'a Twoja edycja wychodziła z „{}"). Odśwież arkusz '
                    'i wprowadź zmianę jeszcze raz.').format(teraz or '—',
                                                             zmiana.bylo or '—')
    if kolumna['metoda_api']:
        if not moze_wysylac_do_bl(uzytkownik):
            return ('kolumna z BaseLinkera — zmienić ją może administrator')
        if (kolumna['metoda_api'] == 'setOrderProductFields'
                and not getattr(wiersz, 'bl_order_product_id', None)):
            return ('pozycji nie da się zmienić w BaseLinkerze: brak '
                    'identyfikatora pozycji (rekord sprzed przebudowy)')
    return None


def zapisz(zmiany: List[Zmiana], uzytkownik, klient_bl=None) -> Dict[str, object]:
    """Zapisuje zmiany i oddaje wynik per pole.

    Kolumny CRM-owe commitują się w jednej transakcji. Kolumny z BaseLinkera
    idą przez `wyslij_do_baselinkera` (Zadanie 11) — `klient_bl=None` jest
    wartością domyślną WYŁĄCZNIE dla testów jednostkowych, które nie ruszają
    kolumn z BaseLinkera; endpoint HTTP zawsze podaje prawdziwego klienta
    (`bl_zapis.klient_z_konfiguracji`).
    """
    wyniki = []
    do_zapisu = []

    for zmiana in zmiany:
        kolumna = kolumna_arkusza(zmiana.nazwa)
        wiersz = _wiersz(zmiana)
        powod = _sprawdz(zmiana, kolumna, wiersz, uzytkownik, klient_bl)
        if powod:
            wyniki.append({'klucz': zmiana.klucz, 'status': 'odrzucone',
                           'metoda': kolumna['metoda_api'], 'tekst': None,
                           'blad': powod})
            continue
        try:
            wartosc = na_wartosc(kolumna, zmiana.jest)
        except ValueError as blad:
            wyniki.append({'klucz': zmiana.klucz, 'status': 'odrzucone',
                           'metoda': kolumna['metoda_api'], 'tekst': None,
                           'blad': str(blad)})
            continue
        do_zapisu.append((zmiana, kolumna, wiersz, wartosc))

    # Kolumny tylko-CRM: jedna transakcja, jeden commit. Edycja scalonej
    # komórki to JEDEN setattr na SalesOrder, bo `zmiana.poziom` jest
    # „zamowienie" — żadnej pętli po pozycjach.
    crm = [(z, k, w, v) for (z, k, w, v) in do_zapisu if not k['metoda_api']]
    if crm:
        try:
            # Pozycje, którym po tej paczce trzeba przeliczyć objętość/
            # powierzchnię/cenę za m³ — patrz `_przelicz_pochodne_pozycji`.
            do_przeliczenia = set()
            # Zamówienia, którym po tej paczce trzeba przeliczyć saldo —
            # patrz `_przelicz_saldo`. Z kolumn tylko-CRM wyzwala to dziś
            # jedynie „Grupa"; od fali 6 przeliczenie po zmianie grupy daje
            # tę samą liczbę (saldo nie zależy już od grupy — patrz
            # `_POLA_SALDA_POZYCJI` wyżej), ale gałąź musi zostać sprawna,
            # bo rozstrzyga o niej `_rusza_saldo`, a nie ten jeden przypadek.
            do_salda = set()
            for zmiana, kolumna, wiersz, wartosc in crm:
                setattr(wiersz, zmiana.nazwa, wartosc)
                if zmiana.poziom == 'pozycja' and zmiana.nazwa in _WYMIARY_POZYCJI:
                    do_przeliczenia.add(wiersz)
                if _rusza_saldo(zmiana):
                    zamowienie_zmiany = _zamowienie_zmiany(zmiana, wiersz)
                    if zamowienie_zmiany is not None:
                        do_salda.add(zamowienie_zmiany)
            for wiersz in do_przeliczenia:
                _przelicz_pochodne_pozycji(wiersz)
            for zamowienie_zmiany in do_salda:
                _przelicz_saldo(zamowienie_zmiany)
            db.session.commit()
            for zmiana, kolumna, _, wartosc in crm:
                wyniki.append({'klucz': zmiana.klucz, 'status': 'zapisane',
                               'metoda': None,
                               'tekst': sformatuj(wartosc, kolumna['typ']),
                               'blad': None})
        except Exception as blad:
            db.session.rollback()
            logger.error('Zapis kolumn CRM arkusza nie powiodl sie', error=str(blad))
            # Komunikat dla użytkownika jest STAŁY i PO POLSKU — surowy tekst
            # wyjątku SQLAlchemy niesie całe zapytanie SQL razem z wartościami
            # parametrów (imię, adres, kwota), czyli wyciek struktury bazy
            # i komunikat, którego użytkownik i tak nie zrozumie. Szczegóły
            # zostają WYŁĄCZNIE w logu (linia wyżej) — przegląd Zadania 10,
            # [WAŻNE].
            for zmiana, kolumna, _, _ in crm:
                wyniki.append({'klucz': zmiana.klucz, 'status': 'odrzucone',
                               'metoda': None, 'tekst': None,
                               'blad': 'nie udało się zapisać zmian w bazie — '
                                       'spróbuj ponownie albo zgłoś to '
                                       'administratorowi'})

    bl = [(z, k, w, v) for (z, k, w, v) in do_zapisu if k['metoda_api']]
    if bl:
        wyniki.extend(wyslij_do_baselinkera(bl, klient_bl))

    return {
        'zapisane': sum(1 for w in wyniki if w['status'] == 'zapisane'),
        'odrzucone': sum(1 for w in wyniki if w['status'] == 'odrzucone'),
        'wyniki': wyniki,
    }


def _zamowienie_zmiany(zmiana: Zmiana, wiersz):
    """SalesOrder, którego dotyczy zmiana — także dla zmian na pozycji."""
    return wiersz if zmiana.poziom == 'zamowienie' else wiersz.order


def _pozycja_potwierdzenia(klucz, zamowienie, nazwa, kolumna, bylo, bedzie,
                           dorozumiane) -> Dict[str, object]:
    return {
        'klucz': klucz,
        'zamowienie': zamowienie.baselinker_order_id if zamowienie else None,
        'nazwa': nazwa,
        'etykieta': kolumna['etykieta'],
        'bylo': bylo,
        'bedzie': bedzie,
        'metoda': kolumna['metoda_api'],
        'dorozumiane': dorozumiane,
    }


def pozycje_potwierdzenia(zmiany: List[Zmiana]) -> List[Dict[str, object]]:
    """Co NAPRAWDĘ poleci do BaseLinkera — dane dla dialogu potwierdzenia.

    SPEC §5.3 PUNKT 1 wymaga, żeby dialog wymieniał IMIENNIE każde pole
    lecące do BL: zamówienie, pole, było, będzie, metoda API. Dialog składany
    wyłącznie z zaznaczonych komórek tego NIE spełnia, bo `setOrderPayment`
    podmienia całą płatność naraz i dokłada do ładunku pola, których nikt
    nie edytował:

      * edycja samej kolumny „Zapłacono" na zamówieniu z pustym
        `payment_date` wysyła DZISIEJSZĄ datę płatności
        (`bl_zapis.data_platnosci_efektywna`) — datę, której użytkownik
        nie wpisał i której dialog nie pokazywał (przegląd fali 3,
        [KRYTYCZNE]);
      * symetrycznie: edycja samej „Daty płatności" wysyła kwotę wpłaty
        z bazy, bo bez niej BaseLinker wyzerowałby płatność.

    Oba dopisujemy jako osobne, jawne pozycje z `dorozumiane=True`, żeby
    dialog mógł je odróżnić od tego, co użytkownik wpisał ręcznie. Pozycje
    dorozumiane nie mają `klucz`a — nie odpowiadają żadnej edytowanej
    komórce, więc nie ma czego podświetlać po zapisie.

    Wartości są sformatowane PO STRONIE SERWERA (`sformatuj`) — Global
    Constraint planu: żadna liczba nie jest składana w przeglądarce.

    Kolumny tylko-CRM są pomijane: ta lista opisuje ładunek BaseLinkera,
    a nie całą paczkę. Uprawnień też nie sprawdza — pilnuje ich `zapisz()`;
    tu chodzi o prawdę o ładunku, nie o decyzję, czy wolno go wysłać.
    """
    pozycje: List[Dict[str, object]] = []
    platnosci: Dict[int, Dict[str, object]] = {}

    for zmiana in zmiany:
        try:
            kolumna = kolumna_arkusza(zmiana.nazwa)
        except KeyError:
            continue
        if not kolumna['metoda_api'] or kolumna['poziom'] != zmiana.poziom:
            continue
        wiersz = _wiersz(zmiana)
        if wiersz is None:
            continue
        zamowienie = _zamowienie_zmiany(zmiana, wiersz)
        try:
            wartosc = na_wartosc(kolumna, zmiana.jest)
            bedzie = sformatuj(wartosc, kolumna['typ'])
            bledna = False
        except ValueError:
            # Wartość, której `zapisz()` i tak nie przepuści. Pokazujemy ją
            # tak, jak ją wpisano — dialog ma mówić prawdę o zamiarze, a nie
            # udawać, że komórka jest pusta.
            wartosc, bedzie, bledna = None, zmiana.jest, True
        pozycje.append(_pozycja_potwierdzenia(
            zmiana.klucz, zamowienie, zmiana.nazwa, kolumna,
            sformatuj(getattr(wiersz, zmiana.nazwa, None), kolumna['typ']),
            bedzie, False))

        if kolumna['metoda_api'] == 'setOrderPayment' and zamowienie is not None:
            wpis = platnosci.setdefault(zamowienie.id, {
                'zamowienie': zamowienie, 'pola': [], 'nazwy': set(),
                'bledne': False})
            wpis['pola'].append((kolumna, wartosc))
            wpis['nazwy'].add(zmiana.nazwa)
            wpis['bledne'] = wpis['bledne'] or bledna

    for wpis in platnosci.values():
        if wpis['bledne']:
            # Któreś pole płatności nie przejdzie walidacji, więc CAŁA grupa
            # `setOrderPayment` zostanie odrzucona (dzielą jej los). Nic nie
            # poleci, więc nie ma czego dopisywać.
            continue
        zamowienie = wpis['zamowienie']
        if 'payment_date' not in wpis['nazwy']:
            kolumna_daty = kolumna_arkusza('payment_date')
            pozycje.append(_pozycja_potwierdzenia(
                None, zamowienie, 'payment_date', kolumna_daty,
                sformatuj(zamowienie.payment_date, kolumna_daty['typ']),
                sformatuj(data_platnosci_efektywna(wpis['pola'], zamowienie),
                          kolumna_daty['typ']),
                True))
        if 'paid_amount' not in wpis['nazwy']:
            kolumna_kwoty = kolumna_arkusza('paid_amount')
            tekst_kwoty = sformatuj(zamowienie.paid_amount, kolumna_kwoty['typ'])
            pozycje.append(_pozycja_potwierdzenia(
                None, zamowienie, 'paid_amount', kolumna_kwoty,
                tekst_kwoty, tekst_kwoty, True))
    return pozycje


def wyslij_do_baselinkera(pozycje, klient_bl) -> List[Dict[str, object]]:
    """Wysyła pola BaseLinkera i zapisuje je lokalnie PO potwierdzeniu.

    GRUPOWANIE: jedno wywołanie na (zamówienie, metoda), a dla
    `setOrderProductFields` dodatkowo na pozycję — API wymaga tam
    `order_product_id`. Wszystkie pola jednego wywołania dzielą jego los,
    bo w BaseLinkerze jest ono atomowe.

    KOLEJNOŚĆ jest ustalona i nie wolno jej zmieniać (patrz KOLEJNOSC_METOD).
    """
    if klient_bl is None:
        # OSTATNIA LINIA OBRONY (przegląd Zadania 11, [WAŻNE]). Zadanie 10
        # miało tu stan przejściowy w `_sprawdz` („wysyłka jest w
        # przygotowaniu"), usunięty w Zadaniu 11, bo endpoint HTTP ZAWSZE
        # podaje prawdziwego klienta. Ale `zapisz()` i tak przyjmuje
        # `klient_bl=None` jako domyślną wartość — dla wołającego spoza
        # HTTP (skrypt, przyszły cron), który o tym zapomni, `None.wyslij(...)`
        # kilka linii niżej wywalałby surowy `AttributeError`
        # („'NoneType' object has no attribute 'wyslij'") prosto do wyniku.
        return [{'klucz': zmiana.klucz, 'status': 'odrzucone',
                'metoda': kolumna['metoda_api'], 'tekst': None,
                'blad': 'brak połączenia z BaseLinkerem — zgłoś to administratorowi'}
               for zmiana, kolumna, _, _ in pozycje]

    grupy = {}
    for zmiana, kolumna, wiersz, wartosc in pozycje:
        zamowienie = _zamowienie_zmiany(zmiana, wiersz)
        klucz_grupy = (kolumna['metoda_api'], zamowienie.id if zamowienie else None,
                       wiersz.id if kolumna['metoda_api'] == 'setOrderProductFields'
                       else None)
        grupy.setdefault(klucz_grupy, {
            'metoda': kolumna['metoda_api'], 'zamowienie': zamowienie,
            'pozycja': wiersz if kolumna['metoda_api'] == 'setOrderProductFields' else None,
            'pola': [],
        })['pola'].append((zmiana, kolumna, wiersz, wartosc))

    # LIMIT LICZBY WYWOŁAŃ (przegląd fali 3, [WAŻNE] — patrz MAKS_WYWOLAN_BL).
    # Liczony PO grupowaniu, bo dopiero ono mówi, ile strzałów naprawdę
    # wyjdzie: dwadzieścia zmian na jednym zamówieniu to jedno wywołanie,
    # a dwadzieścia zmian statusu na dwudziestu zamówieniach to dwadzieścia.
    # Sprawdzany PRZED pierwszym wywołaniem — paczka albo idzie w całości,
    # albo nie idzie wcale.
    if len(grupy) > MAKS_WYWOLAN_BL:
        return [{'klucz': zmiana.klucz, 'status': 'odrzucone',
                 'metoda': kolumna['metoda_api'], 'tekst': None,
                 'blad': 'ta paczka wymaga {} wywołań API BaseLinkera, a za '
                         'jednym razem wolno najwyżej {} — podziel zmiany na '
                         'mniejsze porcje i zapisz je po kolei'.format(
                             len(grupy), MAKS_WYWOLAN_BL)}
                for zmiana, kolumna, _, _ in pozycje]

    wyniki = []
    for metoda in KOLEJNOSC_METOD:
        for grupa in [g for g in grupy.values() if g['metoda'] == metoda]:
            wyniki.extend(_wyslij_grupe(grupa, klient_bl))
    return wyniki


def _wyslij_grupe(grupa, klient_bl) -> List[Dict[str, object]]:
    metoda, zamowienie = grupa['metoda'], grupa['zamowienie']
    pola = grupa['pola']

    def wynik(status, blad=None):
        return [{
            'klucz': zmiana.klucz, 'status': status, 'metoda': metoda,
            'tekst': sformatuj(wartosc, kolumna['typ']) if status == 'zapisane' else None,
            'blad': blad,
        } for zmiana, kolumna, _, wartosc in pola]

    if not zamowienie or not zamowienie.baselinker_order_id:
        return wynik('odrzucone',
                     'zamówienie nie ma numeru zamówienia w BaseLinkerze')

    # (kolumna, wartość) — kształt, który przyjmuje `buduj_ladunek` i
    # `data_platnosci_efektywna`. Liczymy raz, używamy w obu miejscach.
    pola_bl = [(kolumna, wartosc) for _, kolumna, _, wartosc in pola]

    try:
        ladunek = buduj_ladunek(metoda, pola_bl, zamowienie, grupa['pozycja'])
        klient_bl.wyslij(metoda, ladunek)
    except BladBaselinkera as blad:
        return wynik('odrzucone', str(blad))
    except Exception as blad:
        # Wyjątek spoza umowy (timeout, błąd sieci, cokolwiek) NIE MOŻE
        # zamienić się w 500 — użytkownik ma zobaczyć komunikat przy komórce.
        logger.error('Wysylka do BaseLinkera nie powiodla sie',
                     metoda=metoda, order_id=zamowienie.baselinker_order_id,
                     error=str(blad))
        return wynik('odrzucone', str(blad))

    # ZAPIS LOKALNY DOPIERO TERAZ — spec §5.3 punkt 4. Odwrotna kolejność
    # oznaczałaby, że CRM pokazuje wartość, której w BaseLinkerze nie ma.
    try:
        for zmiana, kolumna, wiersz, wartosc in pola:
            setattr(wiersz, zmiana.nazwa, wartosc)
        if metoda == 'setOrderProductFields' and grupa['pozycja'] is not None:
            # PRZELICZ POCHODNE (przegląd Zadania 11, [KRYTYCZNE]). Bez tego
            # zmiana `quantity`/`price_gross` przez BaseLinkera zostawiała
            # stare `price_net`/`value_gross`/`value_net`/objętość/cenę za m³
            # policzone dla poprzedniej ilości/ceny — cicho zła liczba w
            # głównym KPI projektu (suma „TTL m³", przychód w m³).
            _przelicz_ceny_pozycji(grupa['pozycja'])
            _przelicz_pochodne_pozycji(grupa['pozycja'])
        if metoda == 'setOrderPayment' and not any(z.nazwa == 'payment_date'
                                                    for z, _, _, _ in pola):
            # DOPISZ DATĘ, KTÓRĄ NAPRAWDĘ WYSŁALIŚMY (przegląd Zadania 11,
            # [KRYTYCZNE]). Gdy w bazie nie było `payment_date`, do
            # BaseLinkera poszła dzisiejsza data (patrz
            # `bl_zapis.data_platnosci_efektywna`) — ta sama data MUSI
            # wylądować też w CRM-ie, inaczej baza i BaseLinker się
            # rozjeżdżają o tę datę.
            zamowienie.payment_date = data_platnosci_efektywna(pola_bl, zamowienie)
        # PRZELICZ SALDO (przegląd fali 3, [KRYTYCZNE]). Po `paid_amount`,
        # `delivery_cost`, `price_type`, `quantity` i `price_gross` żadna
        # z powyższych gałęzi nie ruszała `balance_due` — kolumna „Saldo"
        # zostawała sprzed edycji. Wołane jako ostatnie, bo liczy z
        # `value_net`, które `_przelicz_ceny_pozycji` kilka linii wyżej
        # dopiero aktualizuje. Ta sama transakcja, co zapis samego pola.
        if any(_rusza_saldo(zmiana) for zmiana, _, _, _ in pola):
            _przelicz_saldo(zamowienie)
        if metoda == 'setOrderStatus':
            # IDENTYFIKATOR RAZEM Z NAZWĄ (partia E, punkt E5). Warunek „tylko
            # sprzedaż" (`filters.warunek_sprzedazy`) rozpoznaje zamówienia
            # anulowane i nieopłacone po `baselinker_status_id`, a nie po
            # nazwie. Sama nazwa zostawiała stary numer — zamówienie anulowane
            # w Arkuszu liczyło się do sprzedaży aż do kolejnej synchronizacji.
            # Bierzemy DOKŁADNIE ten numer, który poszedł do BaseLinkera.
            zamowienie.baselinker_status_id = ladunek['status_id']
            if zamowienie.client is not None:
                # Status decyduje, czy zamówienie jest sprzedażą, a klient
                # liczy wyłącznie sprzedaż — ta sama transakcja, ta sama
                # funkcja co przy synchronizacji. `flush` przed przeliczeniem,
                # żeby zapytanie w nim widziało już nowy numer statusu.
                db.session.flush()
                _przelicz_klienta(zamowienie.client, db.session)
        db.session.commit()
    except Exception as blad:
        db.session.rollback()
        logger.error('BaseLinker przyjal zmiane, ale zapis lokalny padl',
                     metoda=metoda, order_id=zamowienie.baselinker_order_id,
                     error=str(blad))
        # Komunikat dla użytkownika jest STAŁY i PO POLSKU — surowy tekst
        # wyjątku SQLAlchemy niesie całe zapytanie SQL razem z wartościami
        # parametrów, czyli wyciek struktury bazy. Szczegóły zostają
        # WYŁĄCZNIE w logu (linia wyżej) — ten sam błąd wrócił po tym, jak
        # przegląd Zadania 10 naprawił go w gałęzi kolumn CRM (przegląd
        # Zadania 11, [WAŻNE]).
        return wynik('odrzucone',
                     'BaseLinker przyjął zmianę, ale zapis w CRM-ie się nie '
                     'powiódł — odśwież arkusz i sprawdź, czy dane w '
                     'BaseLinkerze i w CRM-ie się zgadzają.')
    return wynik('zapisane')
