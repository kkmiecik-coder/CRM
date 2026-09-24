# -*- coding: utf-8 -*-
"""Arkusz wewnętrzny Analizy sprzedażowej — warstwa danych.

Wszystko, co arkusz wie o kolumnach, pochodzi z rejestru pól
(`modules/reports/fields.py`). Druga lista kolumn w szablonie albo
w JavaScripcie byłaby dokładnie tym, co rejestr miał zlikwidować: dziś
w starej zakładce lista statusów jest wpisana na sztywno w HTML
(reports.html:1163), a mapa kolumn do sortowania ręcznie wyliczona
w 44 wpisach (table_sorting.js:167).

CZEGO REJESTR NIE WIE I DLACZEGO TO SIEDZI TUTAJ
================================================
Rejestr opisuje POLE, nie WIDOK. Lista dopuszczalnych statusów, typ edytora,
domyślny zestaw kolumn, sposób formatowania i mapa kolumn produkcyjnych to
wiedza arkusza. `fields.py` zostaje nietknięty przez cały Plan C.
"""

from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Dict, Iterator, List, Optional, Tuple

from sqlalchemy import func

from extensions import db
from modules.reports.aggregates import _GRUPY_BEZ_OBJETOSCI
from modules.reports.analiza_service import (
    ETYKIETY_WARTOSCI, dzis_lokalnie, formatuj_liczbe, opis_okresu, teraz_lokalnie,
)
from modules.reports.fields import (
    POLA, Pole, Poziom, SetOrderCustomField, SetOrderFields, SetOrderPayment,
    SetOrderProductFields, SetOrderStatus, Zrodlo,
)
from modules.reports.filters import (
    liczy_sie_do_sprzedazy, warunki_pozycji, warunki_zamowienia,
)
from modules.reports.ingest import _jest_tabela
from modules.reports.models_sales import SalesOrder, SalesOrderItem
from modules.reports.service import OPIS_POZA_SPRZEDAZA, STATUSY_BASELINKER

# `reports_bp` istnieje juz w tym momencie importu: modules/reports/__init__.py
# tworzy Blueprint (linia z `Blueprint(...)`) PRZED zaimportowaniem routerow
# (`from . import routers_analiza`), a to ten import wciaga ten plik. Import
# „w gore" do wlasnego pakietu wyglada niebezpiecznie, ale w tej kolejnosci
# nie jest cykliczny — `reports_bp` jest juz atrybutem czesciowo
# zainicjalizowanego modulu `modules.reports`.
from modules.reports import reports_bp

RODZAJE = ('bl', 'crm', 'wyliczana', 'produkcja')

_RODZAJ_ZE_ZRODLA = {
    Zrodlo.BL: 'bl',
    Zrodlo.CRM: 'crm',
    Zrodlo.WYLICZANE: 'wyliczana',
    Zrodlo.PRODUKCJA: 'produkcja',
}

# Wszystkie trzy pola dodatkowe BaseLinkera jadą metodą setOrderFields,
# tylko do innego miejsca w jej ładunku (`custom_extra_fields[id]`).
# Dialog potwierdzenia pokazuje METODĘ, nie miejsce w ładunku — użytkownik
# ma wiedzieć, co API zrobi, a nie jak wygląda JSON.
_METODA_ZAPISU = {
    SetOrderFields: 'setOrderFields',
    SetOrderCustomField: 'setOrderFields',
    SetOrderPayment: 'setOrderPayment',
    SetOrderStatus: 'setOrderStatus',
    SetOrderProductFields: 'setOrderProductFields',
}

# Podpowiedzi przy kolumnach, których wartość NIE JEST tym, czym wygląda.
# Lądują jako `title` na nagłówku siatki (Zadanie 8), bo użytkownik ma szansę
# je zobaczyć akurat wtedy, gdy się nad kolumną zastanawia.
_PODPOWIEDZI = {
    # BaseLinker nie zwraca daty płatności w `getOrders` — prawdziwa siedzi
    # w `getOrderPaymentsHistory`, czyli jedno dodatkowe wywołanie API NA
    # ZAMÓWIENIE. Import przyjmuje datę potwierdzenia zamówienia jako
    # przybliżenie i użytkownik musi o tym wiedzieć, ZANIM zacznie na tej
    # kolumnie budować raport.
    'payment_date': ('Data przybliżona: przy imporcie bierzemy datę potwierdzenia '
                     'zamówienia w BaseLinkerze, bo API nie zwraca daty wpłaty. '
                     'Wartość wpisana ręcznie jest dokładna i wraca do BaseLinkera.'),
    # Tekst byl nieaktualny od 554ac3a: do tamtej poprawki brak oznaczenia
    # typu ceny byl CICHO traktowany jak „brutto" (mnożenie razy 1,23) —
    # dzis taki zapis konczy sie ODMOWA (BladBaselinkera w bl_zapis.py,
    # `_platnosc_brutto`), nie zgadywaniem. Podpowiedz klamala uzytkownikowi
    # o rzeczywistym zachowaniu zapisu (przeglad fali 3, [WAZNE] 6).
    'paid_amount': ('Kwota NETTO. Do BaseLinkera wysyłamy ją przeliczoną na brutto, '
                    'jeśli zamówienie ma typ ceny „brutto", bez przeliczenia przy '
                    '„netto". Zamówienie BEZ oznaczonego typu ceny zapis ODRZUCA — '
                    'uzupełnij kolumnę „Typ ceny" i zapisz wpłatę jeszcze raz.'),
    'notes': ('To samo pole, w które moduł produkcji wpisuje komunikaty systemowe '
              '(„Pominięto pozycje usługowe…"). Limit 200 znaków narzuca BaseLinker.'),
}

# Kolumny, które nie mają odpowiednika w żadnym modelu `sales_*`: trzy sumy
# wyliczane na poziomie zamówienia i cztery znaczniki z modułu produkcji.
# Typ podajemy wprost, bo nie ma z czego go odczytać.
_TYPY_BEZ_KOLUMNY = {
    'order_amount_net': 'kwota',
    'total_m3': 'objetosc',
    'lead_time_days': 'liczba',
    'gluing_done_at': 'znacznik',
    'formatting_done_at': 'znacznik',
    'packaging_done_at': 'znacznik',
    'logistics_done_at': 'znacznik',
}

# Skąd bierze się każda kolumna produkcyjna. Rejestr zna je pod nazwami
# `*_done_at`, a moduł produkcji trzyma je pod `*_completed_at` — i część
# na POZYCJI (`prod_products`), a nie na zamówieniu. Mapa jest jedynym
# miejscem, które o tym wie.
KOLUMNY_PRODUKCJI: Dict[str, Tuple[str, str]] = {
    'gluing_done_at': ('pozycja', 'gluing_completed_at'),
    'formatting_done_at': ('pozycja', 'formatting_completed_at'),
    'packaging_done_at': ('pozycja', 'packaging_completed_at'),
    'logistics_done_at': ('zamowienie', 'logistics_completed_at'),
}

# Zestaw z makiety Arkusz.dc.html (blok <thead>). Trzy świadome różnice,
# wszystkie opisane w planie:
#   * „Wymiary cm" to w makiecie jedna kolumna, u nas trzy — bo każdy wymiar
#     jest osobno edytowalny, a rejestr nie ma wpisu złożonego na wymiary;
#   * „Cena netto" jest w makiecie neutralna, u nas WYLICZANA — bo naprawdę
#     powstaje z ceny brutto i typu ceny, a nie przychodzi z BaseLinkera;
#   * licznik pokazuje 19/55, nie 24/51 — makieta ma liczby poglądowe.
KOLUMNY_DOMYSLNE: Tuple[str, ...] = (
    'date_created', 'baselinker_order_id', 'customer_name', 'delivery_state',
    'caretaker', 'client_origin', 'wood_species', 'technology', 'wood_class',
    'length_cm', 'width_cm', 'thickness_cm', 'quantity', 'price_net',
    'value_net', 'total_volume', 'paid_amount', 'paid_cash', 'gluing_done_at',
)

PRESETY_OKNA = ('miesiac', 'kwartal', 'rok', 'calosc')

# Dziesięć lat. Dane zaczynają się 2025-05-05, więc „całość" mieści się
# z zapasem, a granica chroni przed `?od=0001-01-01`, który w Planie B
# wyprodukował OverflowError i 500.
MAKS_DNI_OKNA = 3660
NAJWCZESNIEJSZA_DATA = date(2000, 1, 1)

# Pełne nazwy miesięcy w mianowniku, z wielkiej litery — do etykiety
# przycisku okna („Wrzesień 2026", tak jest w makiecie). To NIE jest duplikat
# `analytics.MIESIACE_MALE`: tamto są trzyliterowe skróty małą literą na oś
# wykresu, tutaj potrzebna jest inna forma tego samego słowa.
MIESIACE_PELNE: Tuple[str, ...] = (
    'Styczeń', 'Luty', 'Marzec', 'Kwiecień', 'Maj', 'Czerwiec',
    'Lipiec', 'Sierpień', 'Wrzesień', 'Październik', 'Listopad', 'Grudzień',
)

_RZYMSKIE = ('I', 'II', 'III', 'IV')


def _kolumna_modelu(nazwa: str, pole: Pole):
    """Kolumna SQLAlchemy odpowiadająca polu rejestru albo None."""
    model = SalesOrder if pole.poziom is Poziom.ZAMOWIENIE else SalesOrderItem
    return model.__table__.columns.get(nazwa)


def _typ_kolumny(nazwa: str, pole: Pole) -> str:
    """Typ edytora i formatowania: tekst / liczba / kwota / objetosc /
    data / znacznik / logiczna / wybor."""
    if nazwa == 'current_status':
        return 'wybor'
    # PRZEGLĄD ZADANIA 11, [KRYTYCZNE]: `price_type` w bazie to
    # `Enum('netto', 'brutto', '')`, ale bez tego wyjątku kolumna nie
    # trafiała w żadną gałąź niżej (nazwa typu SQLAlchemy dla Enuma to
    # „enum", nie „numeric"/„integer"/…) i wracała jako zwykły 'tekst' —
    # arkusz dawał wolne pole edycji, a wpisanie czegokolwiek spoza trzech
    # wartości Enuma przechodziło walidację i leciało do BaseLinkera
    # (custom_extra_fields „typ ceny"), po czym commit w CRM-ie wywalał się
    # LookupError-em przy każdym kolejnym odczycie tego zamówienia.
    if nazwa == 'price_type':
        return 'wybor'
    # Wyjatek: to JEDYNY identyfikator w rejestrze, ktory udaje miare.
    # Model trzyma go jako db.Integer, wiec bez tego wyjatku dostaje typ
    # 'liczba': serwer formatuje go przez formatuj_liczbe(v, 0) (spacje co
    # trzy cyfry, wyrownanie do prawej), a numer zamowienia w BaseLinkerze
    # nie ma spacji i nie da sie go tak skopiowac do wyszukiwarki BL
    # (przeglad Zadania 8, znalezisko [WAZNE]).
    if nazwa == 'baselinker_order_id':
        return 'tekst'
    if nazwa in _TYPY_BEZ_KOLUMNY:
        return _TYPY_BEZ_KOLUMNY[nazwa]

    kolumna = _kolumna_modelu(nazwa, pole)
    if kolumna is None:
        return 'tekst'

    nazwa_typu = kolumna.type.__class__.__name__.lower()
    if 'boolean' in nazwa_typu:
        return 'logiczna'
    if 'datetime' in nazwa_typu:
        return 'znacznik'
    if 'date' in nazwa_typu:
        return 'data'
    if 'numeric' in nazwa_typu:
        # Objętość ma sześć miejsc po przecinku i nie jest kwotą — pomyłka
        # kosztowałaby zaokrąglenie 0,044800 m³ do „0,04 zł".
        return 'objetosc' if (kolumna.type.scale or 0) > 2 else 'kwota'
    if 'integer' in nazwa_typu:
        return 'liczba'
    return 'tekst'


def _opcje_wyboru(nazwa: str, pole: Pole) -> Optional[List[str]]:
    """Lista dozwolonych wartości dla kolumny typu 'wybor'.

    `current_status` NIE jest w bazie Enum-em (zwykły `db.String(100)`) —
    lista statusów żyje w słowniku BaseLinkera (`STATUSY_BASELINKER`), bo
    to z nim ma się zgadzać zapis. Każda INNA kolumna typu 'wybor' (dziś:
    `price_type`) to prawdziwy `db.Enum` w modelu — listę bierzemy WPROST
    z kolumny (`type.enums`), żeby nie duplikować wartości Enuma w drugim
    miejscu i nie rozjechać się z bazą, gdyby ktoś kiedyś dopisał czwartą
    wartość (przegląd Zadania 11, [KRYTYCZNE]).
    """
    if nazwa == 'current_status':
        return sorted(STATUSY_BASELINKER.values())
    kolumna = _kolumna_modelu(nazwa, pole)
    enumy = getattr(kolumna.type, 'enums', None) if kolumna is not None else None
    return list(enumy) if enumy else None


def _opis_kolumny(nazwa: str, pole: Pole) -> Dict[str, object]:
    rodzaj = _RODZAJ_ZE_ZRODLA[pole.zrodlo]
    typ = _typ_kolumny(nazwa, pole)
    return {
        'nazwa': nazwa,
        'etykieta': pole.etykieta,
        'rodzaj': rodzaj,
        'poziom': pole.poziom.value,
        # Edytowalne są WYŁĄCZNIE kolumny z BaseLinkera i tylko-CRM, i tylko
        # te, którym rejestr na to pozwala. Wyliczane przeliczają się same,
        # produkcyjne mają źródło prawdy w innym module.
        'edytowalne': bool(pole.edytowalne and rodzaj in ('bl', 'crm')),
        'wrazliwe': pole.wrazliwe,
        'metoda_api': _METODA_ZAPISU.get(type(pole.zapis)) if pole.zapis else None,
        'id_pola_bl': (pole.zapis.id_pola
                       if isinstance(pole.zapis, SetOrderCustomField) else None),
        'klucz_bl': getattr(pole.zapis, 'klucz', None),
        'max_dlugosc': pole.max_dlugosc,
        'typ': typ,
        'opcje': _opcje_wyboru(nazwa, pole) if typ == 'wybor' else None,
        'liczbowa': typ in ('liczba', 'kwota', 'objetosc'),
        # Czcionka monospace na KAZDA cyfre (zasada projektu), nie tylko na
        # 'liczbowa' — 'baselinker_order_id' jest ciagiem cyfr, ale to
        # IDENTYFIKATOR, nie „wielkosc liczbowa": nie sumuje sie go
        # i nie porownuje wzrokowo kolumna w kolumne, wiec 'liczbowa' zostaje
        # False (bez wyrownania do prawej i bez separatora tysiecy — patrz
        # wyjatek w `_typ_kolumny`). Mimo to makieta pokazuje go czcionka
        # monospace (`m` bez `num`), stad osobna flaga zamiast przeciazania
        # 'liczbowa' (przeglad zadan 7+8, [WAZNE] nr 5).
        'monospace': typ in ('liczba', 'kwota', 'objetosc', 'data', 'znacznik')
                     or nazwa == 'baselinker_order_id',
        'podpowiedz': _PODPOWIEDZI.get(nazwa),
        # Jednostka do wyświetlenia obok etykiety nagłówka („zł", „m³",
        # „szt."…) — to samo pole rejestru, którego czyta dashboard.
        # Informacja, nie mechanizm: arkusz i tak formatuje wartości
        # po stronie serwera (`sformatuj`).
        'jednostka': pole.jednostka,
    }


def _opis_kolumny_lekki(nazwa: str, pole: Pole) -> Dict[str, object]:
    """Skrócony opis kolumny: TYLKO to, czego potrzebuje selektor „Kolumny"
    (checkbox na każdą z 55 pozycji) i walidacja `?kolumny=` z adresu.

    Pełny piętnastopolowy opis (`_opis_kolumny`) niesie m.in. `opcje` —
    pełną, 18-elementową listę statusów BaseLinkera. Wpisanie go do
    WSZYSTKICH 55 kolumn (a nie tylko do tej jednej, która go realnie
    potrzebuje) napompowało atrybut `data-kolumny-wszystkie` do ~77% wagi
    strony, mimo że selektor kolumn — jedyny konsument tej listy — czyta
    z niej wyłącznie `nazwa`/`etykieta` (do checkboksa) i `rodzaj`/
    `metoda_api`/`edytowalne` (pilnowane testami `test_arkusz_kolumny.py`).
    Pełny opis (typ, opcje wyboru, jednostka, progi edycji...) dostaje
    WYŁĄCZNIE zestaw kolumn faktycznie pokazywanych w danym oknie —
    `kolumna_arkusza()`, wołane per wybrana kolumna w `dane_arkusza()` —
    tam, gdzie się naprawdę przyda (przegląd zadań 7+8, [WAZNE] nr 2).
    """
    rodzaj = _RODZAJ_ZE_ZRODLA[pole.zrodlo]
    return {
        'nazwa': nazwa,
        'etykieta': pole.etykieta,
        'rodzaj': rodzaj,
        'metoda_api': _METODA_ZAPISU.get(type(pole.zapis)) if pole.zapis else None,
        'edytowalne': bool(pole.edytowalne and rodzaj in ('bl', 'crm')),
    }


def kolumny_arkusza() -> List[Dict[str, object]]:
    """Skrócony opis wszystkich kolumn arkusza, w kolejności rejestru.

    Wymiary złożone są pomijane: ich wartość to krotka kolumn składowych,
    nie ma własnej kolumny w bazie i nie da się jej wyrenderować ani
    wyedytować jako jednej komórki (spec §6.3.2).

    Zwraca SKRÓCONY opis (`_opis_kolumny_lekki`) — pełny opis pojedynczej
    kolumny, z listami wyboru i jednostką włącznie, daje `kolumna_arkusza()`.
    """
    return [_opis_kolumny_lekki(nazwa, pole)
            for nazwa, pole in POLA.items() if pole.skladniki is None]


@reports_bp.context_processor
def _jednostki_stopki_arkusza() -> Dict[str, Optional[str]]:
    """Jednostki do stopki arkusza (`arkusz.html`), z rejestru pól.

    `zł`/`m³` siedziały tam wpisane na sztywno — łamie to regułę wprowadzoną
    commitem a892ca8 („jednostka kolumny przychodzi WYŁĄCZNIE z rejestru,
    nigdy wpisana na sztywno w widoku") i istniejące testy tej reguły
    (przegląd zadań 7+8, [WAŻNE] nr 1). Trasa `/reports/arkusz`
    (routers_analiza.py) jest poza tym pasmem poprawek, więc dodanie
    zmiennej do jej `render_template(...)` nie wchodzi w grę bez dotykania
    cudzego pliku — stąd context processor blueprintu zamiast argumentu
    widoku: uruchamia się dla każdego renderu szablonu w `reports_bp`,
    niezależnie od tego, który plik zawołał `render_template`.
    """
    return {
        'jednostka_netto': POLA['order_amount_net'].jednostka,
        'jednostka_objetosc': POLA['total_m3'].jednostka,
        # Podpis zakresu sum stopki (partia E, punkt E5) — z tego samego
        # miejsca co stała statusów, żeby nazwa zbioru nie rozjechała się
        # z tym, co naprawdę wyłączamy.
        'opis_poza_sprzedaza': OPIS_POZA_SPRZEDAZA,
    }


def kolumna_arkusza(nazwa: str) -> Dict[str, object]:
    """Opis jednej kolumny. Rzuca KeyError dla nazwy spoza rejestru."""
    pole = POLA[nazwa]
    if pole.skladniki is not None:
        raise KeyError(f'{nazwa} jest wymiarem złożonym, nie kolumną arkusza')
    return _opis_kolumny(nazwa, pole)


def _parsuj_date(tekst) -> date:
    try:
        return datetime.strptime(tekst, '%Y-%m-%d').date()
    except (TypeError, ValueError):
        raise ValueError(f"'{tekst}' nie jest datą w formacie RRRR-MM-DD")


def _zakres_presetu(preset: str) -> Tuple[date, date]:
    dzis = dzis_lokalnie()
    if preset == 'miesiac':
        return dzis.replace(day=1), dzis
    if preset == 'kwartal':
        pierwszy_miesiac = 3 * ((dzis.month - 1) // 3) + 1
        return date(dzis.year, pierwszy_miesiac, 1), dzis
    if preset == 'rok':
        return date(dzis.year, 1, 1), dzis
    # 'calosc' — od granicy MAKS_DNI_OKNA, nie „od zawsze". Dane zaczynają
    # się 2025-05-05, więc to obejmuje wszystko, a jednocześnie nie pozwala
    # zapytaniu urosnąć w nieskończoność, gdy baza za pięć lat spuchnie.
    return max(NAJWCZESNIEJSZA_DATA, dzis - timedelta(days=MAKS_DNI_OKNA)), dzis


def parsuj_okno(argumenty) -> Tuple[date, date, str]:
    """Okno dat arkusza: (od, do, preset). Rzuca ValueError po polsku.

    Dwa tryby: preset (`?okno=miesiac`) albo jawny zakres (`?od=&do=`).
    Jawny zakres wygrywa. Brak obu daje bieżący miesiąc.

    Walidacja jest tu rozpisana na pięć osobnych warunków celowo — trzy błędy
    krytyczne z przeglądu Planu B siedziały właśnie w walidacji wejścia.
    """
    argumenty = argumenty or {}
    od_tekst = argumenty.get('od')
    do_tekst = argumenty.get('do')

    if od_tekst or do_tekst:
        if not (od_tekst and do_tekst):
            raise ValueError('podając zakres własny, podaj oba pola: „od" i „do"')
        od, do, preset = _parsuj_date(od_tekst), _parsuj_date(do_tekst), 'wlasne'
    else:
        preset = argumenty.get('okno') or 'miesiac'
        if preset not in PRESETY_OKNA:
            raise ValueError(f"'{preset}' nie jest zakresem arkusza "
                             f"(dozwolone: {', '.join(PRESETY_OKNA)})")
        od, do = _zakres_presetu(preset)

    if od > do:
        raise ValueError('początek okna jest późniejszy niż koniec')
    if od < NAJWCZESNIEJSZA_DATA:
        raise ValueError('początek okna jest wcześniejszy niż '
                         f'{NAJWCZESNIEJSZA_DATA.isoformat()}')
    if (do - od).days > MAKS_DNI_OKNA:
        raise ValueError(f'okno dłuższe niż {MAKS_DNI_OKNA} dni')
    return od, do, preset


def etykieta_okna(od: date, do: date, preset: str) -> str:
    """Napis na przycisku okna dat. Makieta pokazuje „Wrzesień 2026"."""
    if preset == 'miesiac':
        return f'{MIESIACE_PELNE[do.month - 1]} {do.year}'
    if preset == 'kwartal':
        return f'{_RZYMSKIE[(do.month - 1) // 3]} kwartał {do.year}'
    if preset == 'rok':
        return f'Rok {do.year}'
    if preset == 'calosc':
        return 'Cała historia'
    # Zakres własny opisujemy tak samo, jak pasek dashboardu — jedno źródło
    # prawdy o tym napisie.
    return opis_okresu(od, do)


# Znacznik pustej komorki na EKRANIE. W pliku CSV (`wiersze_eksportu`) musi
# zostac zamieniony z powrotem na pusty string — inaczej Excel traktuje go
# jako zwykla wartosc tekstowa: autofiltr wystawia „—" jako osobna pozycje,
# a kolumny liczbowe/datowe z brakami przestaja byc liczbami (SUMA, tabela
# przestawna i sortowanie po nich milcza nie dzialaja).
PUSTA_KOMORKA = '—'


# Liczby w CSV NIE dostaja spacji tysiecznej formatuj_liczbe() uzywanej na
# EKRANIE — Excel i Arkusze Google parsuja "12345,67" jako LICZBE, ale
# "12 345,67" (zwykla spacja, nie cyfra) jako TEKST, wiec kazda kwota >= 1000
# ladowala sie do arkusza kalkulacyjnego wyrownana do lewej, bez sumowania
# ani formatowania warunkowego (przeglad fali 3, [WAZNE] 2). Przecinek
# dziesietny ZOSTAJE (nie kropka): eksport idzie srednikiem (routers_analiza.py,
# csv.writer(..., delimiter=';')) — to polskie ustawienie regionalne Excela,
# ktore i tak oczekuje przecinka jako separatora dziesietnego przy tym
# separatorze listy, wiec kropka wprowadzalaby NOWA niezgodnosc zamiast
# naprawiac stara.
def _liczba_eksportu(wartosc, miejsca: int) -> str:
    liczba = Decimal(str(wartosc))
    return f'{liczba:.{miejsca}f}'.replace('.', ',')


def sformatuj(wartosc, typ: str, nazwa: Optional[str] = None,
             eksport: bool = False) -> str:
    """Wartość gotowa do wyświetlenia w komórce (ekran) albo do zapisu w CSV.

    Formatowanie jest po stronie SERWERA, bo Global Constraint tego planu
    mówi wprost: żadna liczba nie jest liczona ani składana w przeglądarce.
    JavaScript dostaje napis i wkłada go do komórki.

    `nazwa` — nazwa kolumny — wpasowuje wymiary słownikowe (dziś: order_source,
    own_transport, picked_up) w TĘ SAMĄ mapę etykiet, z której korzysta
    dashboard i filtry (`analiza_service.ETYKIETY_WARTOSCI`). Bez tego
    kroku siatka i eksport CSV arkusza pokazywały surowy kod z BaseLinkera
    („shop") zamiast etykiety widocznej wszędzie indziej w zakładce
    („Sklep") — ta sama wartość pod dwiema nazwami, PO RAZ CZWARTY w tym
    projekcie (przegląd fali 3, [KRYTYCZNE] 1).

    `eksport=True` przełącza formatowanie liczb na wariant pod plik CSV —
    patrz `_liczba_eksportu`.
    """
    if wartosc is None or wartosc == '':
        return PUSTA_KOMORKA
    slownik = ETYKIETY_WARTOSCI.get(nazwa) if nazwa else None
    if slownik and wartosc in slownik:
        return slownik[wartosc]
    if typ == 'kwota':
        return _liczba_eksportu(wartosc, 2) if eksport else formatuj_liczbe(wartosc, 2)
    if typ == 'objetosc':
        return _liczba_eksportu(wartosc, 6) if eksport else formatuj_liczbe(wartosc, 6)
    if typ == 'liczba':
        return _liczba_eksportu(wartosc, 0) if eksport else formatuj_liczbe(wartosc, 0)
    if typ == 'logiczna':
        return 'tak' if wartosc else 'nie'
    if typ == 'znacznik':
        return wartosc.strftime('%d.%m.%Y %H:%M')
    if typ == 'data':
        return wartosc.strftime('%d.%m.%Y')
    return str(wartosc)


def moze_wysylac_do_bl(uzytkownik) -> bool:
    """Czy użytkownik ma prawo wysłać zmiany do BaseLinkera.

    WARIANT ROLOWY, decyzja użytkownika z 22.09.2026: zapis zwrotny do BL
    tylko dla roli `admin`, edycja kolumn CRM-owych dla wszystkich
    z dostępem do modułu. Prawdziwe pod-uprawnienia (`reports.push_bl`)
    wymagałyby zmiany w silniku uprawnień całej aplikacji i są poza
    zakresem — `modules/users/decorators/permission_required.py`
    nie zna dziś pod-uprawnień w ogóle.

    Nie importujemy tu `User` — wystarczy, że obiekt ma `is_admin()`.
    Dzięki temu funkcję da się przetestować bez podnoszenia modułu users.
    """
    return bool(uzytkownik is not None and uzytkownik.is_admin())


DOMYSLNY_LIMIT = 200
MAKS_LIMIT = 500

# Ile znaków szukajki bierzemy pod uwagę. Bez limitu wklejony z Worda
# akapit poszedłby do LIKE-a i zmusił MySQL do pełnego skanu po nic.
MAKS_DLUGOSC_SZUKANIA = 100


def kolumny_z_adresu(tekst: Optional[str]) -> List[str]:
    """Lista kolumn z parametru `?kolumny=a,b,c`. Rzuca ValueError.

    Brak parametru daje zestaw domyślny z makiety. Nazwa spoza rejestru
    (albo wymiar złożony) kończy się błędem 400, nie 500 — bez tej walidacji
    `POLA[nazwa]` rzuciłby KeyError i użytkownik dostałby stronę błędu
    zamiast komunikatu.
    """
    wybrane = [n.strip() for n in (tekst or '').split(',') if n.strip()]
    if not wybrane:
        return list(KOLUMNY_DOMYSLNE)
    dozwolone = {k['nazwa'] for k in kolumny_arkusza()}
    nieznane = [n for n in wybrane if n not in dozwolone]
    if nieznane:
        raise ValueError(f"nie ma takich kolumn arkusza: {', '.join(nieznane)}")
    return wybrane


def _warunek_szukania(szukane: Optional[str]):
    """Warunek szukajki albo None.

    PUŁAPKA: `%` i `_` są w LIKE wieloznacznikami. Bez escapowania wpisanie
    samego `%` zwróciłoby WSZYSTKO — użytkownik zobaczyłby wyniki dla frazy,
    której w danych nie ma. Escapujemy ręcznie i podajemy znak ucieczki.
    """
    szukane = (szukane or '').strip()[:MAKS_DLUGOSC_SZUKANIA]
    if not szukane:
        return None

    bezpieczne = (szukane.replace('\\', '\\\\')
                         .replace('%', '\\%')
                         .replace('_', '\\_'))
    wzorzec = f'%{bezpieczne.lower()}%'

    warunki = [
        func.lower(SalesOrder.customer_name).like(wzorzec, escape='\\'),
        func.lower(SalesOrder.internal_order_number).like(wzorzec, escape='\\'),
        func.lower(SalesOrder.email).like(wzorzec, escape='\\'),
    ]
    # Numer BaseLinkera jest liczbą całkowitą, więc porównujemy go wprost,
    # bez CAST — `CAST(x AS VARCHAR)` nie skompiluje się na MySQL-u bez
    # podanej długości. Dopasowanie jest w całości, nie po fragmencie.
    # `str.isdigit()` zwraca True też dla cyfr spoza ASCII (np. „²", „³",
    # „⁵" — Numeric_Type=Digit), których `int()` nie sparsuje i rzuci
    # ValueError. `isascii()` odcina je przed próbą konwersji.
    if szukane.isascii() and szukane.isdigit() and len(szukane) <= 12:
        warunki.append(SalesOrder.baselinker_order_id == int(szukane))
    return db.or_(*warunki)


def _dane_produkcji(bl_identyfikatory: List[int]) -> Dict[int, Dict[str, object]]:
    """Cztery znaczniki produkcyjne per zamówienie, jednym zapytaniem.

    Dla kolumn stanowiskowych (`prod_products`) wartością zamówienia jest
    NAJPÓŹNIEJSZY znacznik, ale WYŁĄCZNIE gdy mają go wszystkie pozycje.
    „Sklejone" ma znaczyć „całe zamówienie sklejone", nie „coś sklejono".
    `COUNT(kolumna)` liczy wartości nie-NULL, więc porównanie z `COUNT(id)`
    załatwia to jednym zapytaniem, bez pętli po pozycjach.
    """
    if not bl_identyfikatory or not _jest_tabela('prod_orders'):
        return {}

    from modules.production.models import ProductionOrder, ProductionProduct

    wiersze = (
        db.session.query(
            ProductionOrder.baselinker_order_id,
            ProductionOrder.logistics_completed_at,
            func.count(ProductionProduct.id),
            func.count(ProductionProduct.gluing_completed_at),
            func.max(ProductionProduct.gluing_completed_at),
            func.count(ProductionProduct.formatting_completed_at),
            func.max(ProductionProduct.formatting_completed_at),
            func.count(ProductionProduct.packaging_completed_at),
            func.max(ProductionProduct.packaging_completed_at),
        )
        .outerjoin(ProductionProduct, ProductionProduct.order_id == ProductionOrder.id)
        .filter(ProductionOrder.baselinker_order_id.in_(bl_identyfikatory))
        # logistics_completed_at MUSI być w GROUP BY — MySQL z ONLY_FULL_GROUP_BY
        # odrzuciłby zapytanie, a SQLite przepuściłby je po cichu.
        .group_by(ProductionOrder.baselinker_order_id,
                  ProductionOrder.logistics_completed_at)
        .all()
    )

    wynik: Dict[int, Dict[str, object]] = {}
    for (bl_id, logistyka, pozycji,
         sklejonych, sklejone_max,
         docietych, dociete_max,
         spakowanych, spakowane_max) in wiersze:
        def komplet(ile, maksimum):
            return maksimum if pozycji and ile == pozycji else None
        wynik[bl_id] = {
            'gluing_done_at': komplet(sklejonych, sklejone_max),
            'formatting_done_at': komplet(docietych, dociete_max),
            'packaging_done_at': komplet(spakowanych, spakowane_max),
            'logistics_done_at': logistyka,
        }
    return wynik


def surowa(wartosc, typ: str) -> str:
    """Wartość w formie maszynowej — do edytora w przeglądarce.

    Format jest jednoznaczny i niezależny od ustawień regionalnych: kropka
    dziesiętna, data ISO, `true`/`false`. Serwis zapisu (Zadanie 10) parsuje
    dokładnie to samo I PORÓWNUJE po tym formacie przy strażniku
    optymistycznym — dlatego funkcja jest publiczna, a nie prywatna.
    """
    if wartosc is None:
        return ''
    if typ == 'logiczna':
        return 'true' if wartosc else 'false'
    if typ in ('data', 'znacznik'):
        return wartosc.isoformat()
    return str(wartosc)


def _wypelnij(zrodlo, kolumny: List[Dict], nadpisania: Dict,
              eksport: bool = False) -> Tuple[Dict, Dict]:
    """Dwa słowniki komórek: sformatowany tekst i wartości surowe.

    Wartości surowe lecą WYŁĄCZNIE dla kolumn edytowalnych. Dla reszty byłyby
    martwym balastem — przy 55 kolumnach i 700 wierszach to zauważalna część
    odpowiedzi.

    `eksport=True` idzie do `sformatuj` — liczby w pliku CSV mają inny
    format niż na ekranie (patrz `_liczba_eksportu`).
    """
    tekst, surowe = {}, {}
    for kolumna in kolumny:
        nazwa = kolumna['nazwa']
        wartosc = (nadpisania[nazwa] if nazwa in nadpisania
                   else getattr(zrodlo, nazwa, None))
        tekst[nazwa] = sformatuj(wartosc, kolumna['typ'], nazwa, eksport)
        if kolumna['edytowalne']:
            surowe[nazwa] = surowa(wartosc, kolumna['typ'])
    return tekst, surowe


def _wyliczane_zamowienia(zamowienie, produkcja: Dict[str, object]) -> Dict[str, object]:
    """Trzy kolumny, których nie ma w żadnym modelu, plus cztery z produkcji.

    Liczymy je w Pythonie z już wczytanych pozycji — dokładanie zapytania
    agregującego per zamówienie dałoby N+1, a pozycje i tak są w pamięci
    (`SalesOrder.items` ma `lazy='selectin'`).
    """
    netto = sum((p.value_net or Decimal('0') for p in zamowienie.items), Decimal('0'))
    objetosc = sum(
        (p.total_volume or Decimal('0') for p in zamowienie.items
         if p.group_type not in _GRUPY_BEZ_OBJETOSCI), Decimal('0'))

    zeszlo = produkcja.get('logistics_done_at')
    dni = ((zeszlo.date() - zamowienie.date_created).days
           if zeszlo and zamowienie.date_created else None)

    wyliczane = {'order_amount_net': netto, 'total_m3': objetosc, 'lead_time_days': dni}
    wyliczane.update({nazwa: produkcja.get(nazwa) for nazwa in KOLUMNY_PRODUKCJI})
    return wyliczane


def _opis_poza_sprzedaza(zamowienie: SalesOrder) -> Optional[str]:
    """Zdanie pod wyszarzonym zamówieniem albo None, gdy liczy się do sprzedaży.

    Status bierzemy z bazy (`current_status`) — to ten sam napis, który
    użytkownik zna z BaseLinkera. Zapas na numer, gdyby nazwy nie było.
    """
    if liczy_sie_do_sprzedazy(zamowienie.baselinker_status_id):
        return None
    status = zamowienie.current_status or f'Status {zamowienie.baselinker_status_id}'
    return (f'{status} — poza sprzedażą: nie wlicza się do sum w stopce '
            f'ani do liczb pulpitu.')


def dane_arkusza(od: date, do: date, preset: str = 'wlasne',
                 kolumny: Optional[List[str]] = None, szukaj: Optional[str] = None,
                 filtr=None, offset: int = 0,
                 limit: int = DOMYSLNY_LIMIT, eksport: bool = False) -> Dict[str, object]:
    """Komplet danych jednego ekranu arkusza.

    `eksport=True` (wołane wyłącznie z `wiersze_eksportu`) przełącza
    formatowanie liczb w komórkach na wariant pod plik CSV — patrz
    `_liczba_eksportu`. Ekran (`eksport=False`, domyślne) dostaje polskie
    formatowanie ze spacją tysięczną, tak jak dotychczas.

    STRONICUJEMY PO ZAMÓWIENIACH, NIE PO WIERSZACH. Wiersz siatki to pozycja,
    ale komórki poziomu zamówienia są scalone przez `rowspan`. Strona, która
    rozcięłaby zamówienie, rozbiłaby scalanie i pokazała pół zamówienia
    bez klienta i bez salda.

    PODSUMOWANIE LICZY CAŁE OKNO, NIE STRONĘ — tak jest w makiecie
    („700 pozycji w 423 zamówieniach" obok napisu o przewijaniu wirtualnym).
    """
    opisy = [kolumna_arkusza(n) for n in (kolumny or list(KOLUMNY_DOMYSLNE))]
    zamowieniowe = [k for k in opisy if k['poziom'] == 'zamowienie']
    pozycyjne = [k for k in opisy if k['poziom'] == 'pozycja']

    # Warunki bazowe (daty + szukajka) idą do OBU zapytań. Filtr po wymiarze
    # NIE — ma dwa różne przełożenia na SQL zależnie od FROM zapytania
    # (patrz docstringi `warunki_pozycji`/`warunki_zamowienia` w filters.py),
    # więc każde zapytanie dostaje TYLKO swoje: zapytanie po `SalesOrder`
    # dostaje `warunki_zamowienia`, zapytanie po `SalesOrderItem JOIN
    # SalesOrder` (stopka niżej) dostaje `warunki_pozycji`. Wrzucenie obu
    # naraz do zapytania joinowego powoduje, że SQLAlchemy auto-koreluje
    # `SalesOrder` w obu miejscach i rzuca `InvalidRequestError` (500).
    warunki_bazowe = [SalesOrder.date_created >= od, SalesOrder.date_created <= do]
    szukanie = _warunek_szukania(szukaj)
    if szukanie is not None:
        warunki_bazowe.append(szukanie)

    # SIATKA POKAZUJE WSZYSTKO, STOPKA SUMUJE SPRZEDAŻ (partia E, punkt E5).
    # Arkusz zastępuje Excela, więc zamówienie anulowane i nieopłacone ma tu
    # być widać — wyszarzone, ze statusem. Dlatego lista i stronicowanie idą
    # z `tylko_sprzedaz=False`. Stopka (niżej) liczy już z warunkiem stałym,
    # tak jak pulpit: suma netto w Arkuszu i na pulpicie za to samo okno ma
    # być tą samą liczbą.
    warunki = warunki_bazowe + warunki_zamowienia(filtr, tylko_sprzedaz=False)

    zamowien_lacznie = int(
        db.session.query(func.count(SalesOrder.id)).filter(*warunki).scalar() or 0)
    zamowien_w_sprzedazy = int(
        db.session.query(func.count(SalesOrder.id))
        .filter(*warunki_bazowe, *warunki_zamowienia(filtr)).scalar() or 0)

    strona = (SalesOrder.query
              .filter(*warunki)
              .order_by(SalesOrder.date_created.desc(), SalesOrder.id.desc())
              .offset(offset).limit(limit).all())

    produkcja = _dane_produkcji([z.baselinker_order_id for z in strona
                                 if z.baselinker_order_id])

    # NIEZMIENNIK nr 8: suma w stopce musi się równać sumie po wierszach na
    # ekranie, które NIE SĄ WYSZARZONE. Stopka niżej liczy się
    # `warunki_pozycji(filtr)` — siatka musi pokazywać DOKŁADNIE te same
    # pozycje, inaczej przy filtrze poziomu pozycji (np. `wood_species:dąb`)
    # użytkownik widziałby WSZYSTKIE pozycje zamówienia, a stopka tylko
    # pasujące. Dopasowanie liczymy jednym zapytaniem, ograniczonym do
    # zamówień bieżącej strony — BEZ warunku sprzedaży, bo wyszarzone
    # zamówienie ma pokazać te same pozycje, które pokazałoby nie-wyszarzone.
    pasujace_pozycje_id: Optional[set] = None
    if filtr:
        identyfikatory_strony = [z.id for z in strona]
        if identyfikatory_strony:
            pasujace_pozycje_id = {
                wiersz[0] for wiersz in
                db.session.query(SalesOrderItem.id)
                .join(SalesOrder, SalesOrderItem.order_id == SalesOrder.id)
                .filter(SalesOrder.id.in_(identyfikatory_strony),
                        *warunki_pozycji(filtr, tylko_sprzedaz=False))
                .all()
            }
        else:
            pasujace_pozycje_id = set()

    zamowienia = []
    for zamowienie in strona:
        wyliczane = _wyliczane_zamowienia(
            zamowienie, produkcja.get(zamowienie.baselinker_order_id) or {})
        tekst, surowe = _wypelnij(zamowienie, zamowieniowe, wyliczane, eksport)

        pozycje = []
        for pozycja in zamowienie.items:
            if pasujace_pozycje_id is not None and pozycja.id not in pasujace_pozycje_id:
                continue
            tekst_poz, surowe_poz = _wypelnij(pozycja, pozycyjne, {}, eksport)
            pozycje.append({
                'id': pozycja.id,
                # Bez `order_product_id` z BaseLinkera setOrderProductFields
                # nie ma jak zadziałać. Dotyczy wszystkiego, co przyszło
                # z backfillu — arkusz robi wtedy te dwie kolumny
                # tylko do odczytu.
                'bez_id_bl': pozycja.bl_order_product_id is None,
                'pola': tekst_poz,
                'surowe': surowe_poz,
            })

        zamowienia.append({
            'id': zamowienie.id,
            'bl_id': zamowienie.baselinker_order_id,
            # rowspan=0 rozwaliłby tabelę, a zamówienie bez pozycji jest
            # osiągalne (BaseLinker potrafi oddać zamówienie, z którego
            # usunięto wszystkie pozycje).
            'wierszy': max(1, len(pozycje)),
            'pola': tekst,
            'surowe': surowe,
            'pozycje': pozycje,
            # Zdanie dla wyszarzonego zamówienia albo None. Składa je SERWER,
            # bo tylko on zna regułę (`liczy_sie_do_sprzedazy`) — przeglądarka
            # nie trzyma własnej listy statusów.
            'poza_sprzedaza': _opis_poza_sprzedaza(zamowienie),
        })

    liczba_pozycji, suma_netto, suma_objetosci = (
        db.session.query(
            func.count(SalesOrderItem.id),
            func.sum(SalesOrderItem.value_net),
            func.sum(db.case(
                (SalesOrderItem.group_type.in_(_GRUPY_BEZ_OBJETOSCI), 0),
                else_=SalesOrderItem.total_volume)),
        )
        .join(SalesOrder, SalesOrderItem.order_id == SalesOrder.id)
        .filter(*warunki_bazowe, *warunki_pozycji(filtr))
        .one()
    )

    return {
        'kolumny': opisy,
        'okno': {'od': od.isoformat(), 'do': do.isoformat(), 'preset': preset,
                 'etykieta': etykieta_okna(od, do, preset)},
        'zamowienia': zamowienia,
        'podsumowanie': {
            # Zamówienia W SPRZEDAŻY, nie wszystkie z listy — stopka mówi
            # „N pozycji w M zamówieniach" o tych samych wierszach, które
            # sumuje. Wszystkie (z wyszarzonymi) liczy `stronicowanie`.
            'zamowienia': zamowien_w_sprzedazy,
            'pozycje': int(liczba_pozycji or 0),
            'netto': formatuj_liczbe(suma_netto or 0, 2),
            'objetosc': formatuj_liczbe(suma_objetosci or 0, 6),
        },
        'stronicowanie': {
            'offset': offset, 'limit': limit,
            'zamowien_lacznie': zamowien_lacznie,
            'wiecej': offset + limit < zamowien_lacznie,
        },
        # Stempel „Stan na HH:MM" zamiast auto-odświeżania, wzorem panelu
        # produkcji i dashboardu (spec §7).
        'stan_na': teraz_lokalnie().strftime('%H:%M'),
    }


# Ile zamówień bierzemy na raz przy eksporcie. Eksport NIE stronicuje —
# plik ma objąć całe okno dat — ale czytamy je porcjami, żeby nie trzymać
# w pamięci trzech tysięcy zamówień z pozycjami naraz.
_PORCJA_EKSPORTU = 200


def wiersze_eksportu(od: date, do: date, kolumny: Optional[List[str]] = None,
                     szukaj: Optional[str] = None, filtr=None) -> Iterator[List[str]]:
    """Wiersze do pliku CSV: nagłówek, potem jeden wiersz na POZYCJĘ.

    Scalanie komórek jest sprawą ekranu. W pliku każdy wiersz musi być
    kompletny — inaczej filtr w Excelu pokazałby puste komórki klienta
    w drugiej i trzeciej pozycji zamówienia.

    Reużywa `dane_arkusza`, więc okno, szukajka, filtr i formatowanie są
    dokładnie te same, co na ekranie. Drugie zapytanie byłoby drugim
    źródłem prawdy o tym, co użytkownik widzi.
    """
    opisy = [kolumna_arkusza(n) for n in (kolumny or list(KOLUMNY_DOMYSLNE))]
    yield [k['etykieta'] for k in opisy]

    offset = 0
    while True:
        strona = dane_arkusza(od, do, kolumny=[k['nazwa'] for k in opisy],
                              szukaj=szukaj, filtr=filtr,
                              offset=offset, limit=_PORCJA_EKSPORTU, eksport=True)
        for zamowienie in strona['zamowienia']:
            pozycje = zamowienie['pozycje'] or [{'pola': {}}]
            for pozycja in pozycje:
                wiersz = [zamowienie['pola'].get(k['nazwa'])
                          or pozycja['pola'].get(k['nazwa'], '') for k in opisy]
                # Znacznik pustej komorki jest poprawny na EKRANIE, ale w pliku
                # CSV musi byc pusta komorka, nie tekst „—" — patrz PUSTA_KOMORKA.
                yield ['' if wartosc == PUSTA_KOMORKA else wartosc for wartosc in wiersz]
        if not strona['stronicowanie']['wiecej']:
            return
        offset += _PORCJA_EKSPORTU
