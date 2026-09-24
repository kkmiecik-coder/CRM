# -*- coding: utf-8 -*-
"""Agregaty Analizy sprzedażowej — jedno miejsce, w którym liczymy sumy.

DWIE PUŁAPKI, KTÓRE TU ZAMYKAMY
===============================
1. Saldo i kwota wpłaty żyją na ZAMÓWIENIU, nie na pozycji. W poprzedniku były
   powielone na każdym wierszu i `SUM()` mnożył je przez liczbę pozycji:
   5 618 320 zł zamiast 741 279 zł (produkcja, 21.09.2026). Tutaj sumujemy je
   z `sales_orders`, a netto i objętość z `sales_order_items`.
2. Objętość musi wykluczać usługi. 17 wierszy w bazie ma `total_volume > 1`
   i są to głównie usługi suszenia, gdzie ilość oznacza metry sześcienne
   („Suszenie usługowe 88m3"). Wrzesień 2025 pokazywał przez to 167 m³
   zamiast realnych ~12. Netto usługi zostaje — usługa też jest sprzedażą.
"""

import unicodedata
from datetime import date
from decimal import Decimal
from typing import Dict, List, Optional, Sequence, Tuple

from sqlalchemy import func

from extensions import db
from modules.reports.fields import POLA, Poziom, Zrodlo
from modules.reports.filters import warunki_pozycji, warunki_zamowienia
from modules.reports.models_sales import SalesOrder, SalesOrderItem

# Grupy, które nie wchodzą do sum objętościowych.
_GRUPY_BEZ_OBJETOSCI = ('usługa',)

# Dolna granica PIERWSZEGO kubelka jest celowo ujemna i bardzo niska.
# Zamowienie z data z przyszlosci (literowka w BaseLinkerze) ma wiek < 0
# i przy granicy 0 nie trafialo do zadnego kubelka — znikalo bez sladu,
# a suma kubelkow przestawala sie zgadzac z saldem calosci.
_KUBELKI_WIEKU = (
    ('0-14 dni', -100000, 14),
    ('15-30 dni', 15, 30),
    ('31-60 dni', 31, 60),
    ('61-90 dni', 61, 90),
    ('>90 dni', 91, 100000),
)


def _zero(wartosc) -> Decimal:
    return Decimal('0') if wartosc is None else Decimal(str(wartosc))


def sztuki_bez_uslug():
    """Suma SZTUK PRODUKTÓW: `quantity` pozycji z pominięciem usług.

    Miara „szt." przełącznika na kafelkach pulpitu (24.09.2026). Usługi
    wypadają tą samą listą, co z objętości (`_GRUPY_BEZ_OBJETOSCI`), i z tego
    samego powodu: „Suszenie usługowe 88m3" ma w polu ilości METRY
    SZEŚCIENNE, nie sztuki. Jedna lista dla obu miar — druga kopia znaczyłaby,
    że nowa grupa usługowa poprawia m³, a psuje sztuki.

    To WYRAŻENIE, nie zapytanie: wołający wstawia je w to samo zapytanie,
    które sumuje netto (wymóg: żadnego dodatkowego zapytania na kafelek),
    więc sztuki dostają dokładnie te same warunki — okres, sprzedaż (E5)
    i wykluczenia użytkownika (E4/E8).

    Pozycja bez ilości (NULL) nie liczy się wcale: SUM pomija NULL, tak jak
    netto pomija pozycję bez wartości.
    """
    return func.sum(
        db.case(
            (SalesOrderItem.group_type.in_(_GRUPY_BEZ_OBJETOSCI), 0),
            else_=SalesOrderItem.quantity,
        )
    )


def _sztuki(wartosc) -> int:
    """Suma sztuk jako liczba całkowita.

    MySQL oddaje SUM po kolumnie INT jako DECIMAL, SQLite jako int — bez
    rzutowania payload niósłby raz „11", raz „11.0".
    """
    return int(wartosc or 0)


def cena_netto_za_m3(netto, objetosc) -> Decimal:
    """Cena netto za m³ z dokładnością do grosza — JEDNA definicja zaokrąglenia.

    Wołają ją pasek KPI i wniosek o cenie w „Statystykach", który zestawia
    cenę okresu z cenami miesięcy trendu. Do weryfikacji partii E miesiące
    szły bez zaokrąglenia: KPI 20 132,97 zł przegrywało z tym samym miesiącem
    liczonym jako 20 132,9746 zł i zdanie brzmiało „20 133 zł, poniżej rekordu
    roku: 20 133 zł w WRZ". Obie strony porównania muszą mieć tę samą
    dokładność, więc liczy je ta sama funkcja.
    """
    if not objetosc:
        return Decimal('0')
    return (_zero(netto) / _zero(objetosc)).quantize(Decimal('0.01'))


def kpi(od: date, do: date, filtr=None) -> Dict[str, object]:
    """Pięć liczb z paska KPI dla zadanego okresu.

    `filtr` zawęża wynik: netto, objętość i sztuki po pozycjach, saldo i liczba
    zamówień po zamówieniach (przez EXISTS, patrz modules/reports/filters.py).
    `filtr=None` daje dokładnie to, co przed jego wprowadzeniem.

    `sztuki` (sztuki produktów bez usług) to dopisek z 24.09.2026 — liczony
    W TYM SAMYM zapytaniu co netto, więc KPI nie kosztuje przez nie ani
    jednego zapytania więcej.
    """
    pozycje = (
        db.session.query(
            func.sum(SalesOrderItem.value_net),
            # Forma pozycyjna db.case((warunek, wartość), else_=...) — taka sama
            # jak w modules/production/routers/api/logistics_api.py:40. Stara
            # forma listowa jest w 1.4 przestarzała i znika w 2.0.
            func.sum(
                db.case(
                    (SalesOrderItem.group_type.in_(_GRUPY_BEZ_OBJETOSCI), 0),
                    else_=SalesOrderItem.total_volume,
                )
            ),
            sztuki_bez_uslug(),
        )
        .join(SalesOrder, SalesOrderItem.order_id == SalesOrder.id)
        .filter(SalesOrder.date_created >= od, SalesOrder.date_created <= do,
                *warunki_pozycji(filtr))
        .one()
    )
    netto, objetosc = _zero(pozycje[0]), _zero(pozycje[1])
    sztuki = _sztuki(pozycje[2])

    # Saldo i liczba zamówień — z poziomu zamówienia, nigdy z pozycji.
    zamowienia = (
        db.session.query(func.count(SalesOrder.id), func.sum(SalesOrder.balance_due))
        .filter(SalesOrder.date_created >= od, SalesOrder.date_created <= do,
                *warunki_zamowienia(filtr))
        .one()
    )
    liczba, saldo = int(zamowienia[0] or 0), _zero(zamowienia[1])

    return {
        'netto': netto,
        'objetosc': objetosc,
        'sztuki': sztuki,
        'zamowienia': liczba,
        'saldo': saldo,
        'srednie_zamowienie': (netto / liczba).quantize(Decimal('0.01')) if liczba else Decimal('0'),
        'cena_za_m3': cena_netto_za_m3(netto, objetosc),
    }


# Sklejacz etykiety wymiaru złożonego. Etykietę buduje warstwa widoku, ale
# separator ma jedno źródło — inaczej karta i Eksplorator podpisałyby tę samą
# konfigurację inaczej.
SEPARATOR_ZLOZONY = ' · '


def kolumny_wymiaru(nazwa: str) -> List:
    """Kolumny ORM, po których grupuje dany wymiar.

    Jedna kolumna dla wymiaru zwykłego, kilka dla złożonego (`Pole.skladniki`).
    Walidacja jest tu, a nie w `wg_wymiaru`, bo tej samej listy potrzebuje
    Eksplorator — dwie kopie reguł znaczyłyby, że dashboard i Eksplorator mogą
    kiedyś przyjąć inny zbiór dozwolonych wymiarów.
    """
    pole = POLA.get(nazwa)
    if pole is None or not pole.wymiar:
        raise ValueError(f"'{nazwa}' nie jest wymiarem w rejestrze pól")
    if pole.zrodlo is Zrodlo.PRODUKCJA:
        raise ValueError(f"'{nazwa}' pochodzi z modułu produkcji — grupuj tam")

    nazwy = pole.skladniki if pole.skladniki is not None else (nazwa,)
    kolumny = []
    for skladnik in nazwy:
        skladowe = POLA[skladnik]
        if skladowe.zrodlo is Zrodlo.PRODUKCJA:
            raise ValueError(f"'{skladnik}' pochodzi z modułu produkcji — grupuj tam")
        model = SalesOrder if skladowe.poziom is Poziom.ZAMOWIENIE else SalesOrderItem
        kolumny.append(getattr(model, skladnik))
    return kolumny


def wg_wymiaru(nazwa: str, od: date, do: date, filtr=None) -> List[Dict[str, object]]:
    """Grupowanie po wymiarze z rejestru pól — jednokolumnowym lub złożonym.

    Rejestr decyduje, po czym wolno grupować — dzięki temu Eksplorator nie
    potrzebuje własnej listy dozwolonych kolumn, a dodanie pola z `wymiar=True`
    automatycznie udostępnia je do grupowania.

    `wartosc` jest surową wartością kolumny dla wymiaru zwykłego (tak było
    zawsze i tak ma zostać), a krotką wartości składowych dla złożonego.
    Sklejenie ich w etykietę jest zadaniem warstwy widoku — tutaj nie zgadujemy,
    jak `None` ma się nazywać po polsku.
    """
    kolumny = kolumny_wymiaru(nazwa)
    etykiety = [kolumna.label(f'w{i}') for i, kolumna in enumerate(kolumny)]

    zapytanie = (
        db.session.query(
            *etykiety,
            func.sum(SalesOrderItem.value_net).label('netto'),
            func.sum(
                db.case(
                    (SalesOrderItem.group_type.in_(_GRUPY_BEZ_OBJETOSCI), 0),
                    else_=SalesOrderItem.total_volume,
                )
            ).label('objetosc'),
            # Sztuki produktów — w tym samym zapytaniu, patrz `sztuki_bez_uslug`.
            sztuki_bez_uslug().label('sztuki'),
            func.count(func.distinct(SalesOrder.id)).label('zamowienia'),
        )
        # select_from JAWNIE, choc dotad go nie bylo: przy kilku kolumnach
        # grupowania SQLAlchemy nie ma jak zgadnac, ktora tabela jest lewa
        # strona joinu. Wynik jest ten sam (INNER JOIN jest przemienny),
        # a zapytanie przestaje zalezec od kolejnosci kolumn w SELECT.
        .select_from(SalesOrderItem)
        .join(SalesOrder, SalesOrderItem.order_id == SalesOrder.id)
        .filter(SalesOrder.date_created >= od, SalesOrder.date_created <= do,
                *warunki_pozycji(filtr))
        .group_by(*kolumny)
        .order_by(func.sum(SalesOrderItem.value_net).desc())
    )

    wynik = []
    for w in zapytanie.all():
        skladowe = tuple(getattr(w, f'w{i}') for i in range(len(kolumny)))
        wynik.append({
            # Jedna kolumna -> surowa wartość, nie krotka jednoelementowa.
            'wartosc': skladowe[0] if len(kolumny) == 1 else skladowe,
            'netto': _zero(w.netto),
            'objetosc': _zero(w.objetosc),
            'sztuki': _sztuki(w.sztuki),
            'zamowienia': int(w.zamowienia or 0),
        })
    return wynik


# --- JEDNA WARTOŚĆ, KILKA ZAPISÓW (24.09.2026) --------------------------------
#
# Dane z BaseLinkera mają tę samą wartość zapisaną różnie: „Kurier" i „kurier",
# „pobranie " i „pobranie", „Płatnośc" i „Płatność" (lokalny zrzut produkcji:
# 7 takich grup w `delivery_method`, 5 w `payment_method`, 1 w `wood_species`).
# Kolumny sprzedaży mają kolację `utf8mb4_unicode_ci` (2026-09-22-sales-tabele.sql),
# więc dla MySQL-a to JEDNA wartość: `GROUP BY` robi z nich jedną grupę, `IN`
# i `NOT IN` filtra łapią wszystkie zapisy naraz. Jako `wartosc` grupy baza
# oddaje jednak JEDEN z zapisów, wybrany przez plan zapytania — i zapytanie
# segmentu, zapytanie bez wykluczeń albo zapytanie po miesiącach potrafią oddać
# tę samą grupę INNYM zapisem niż zapytanie bazowe.
#
# Kod, który zestawiał wyniki dwóch zapytań po DOKŁADNYM napisie, gubił wtedy
# wiersz. Zmierzone na lokalnym zrzucie (weryfikacja 24.09.2026): domyślny
# kafelek „Dostawa", sierpień 2025, segment „kanał: personal" — wiersz #1
# segmentu 0 zł / 0 szt. zamiast 46 586,17 zł / 238 szt., a ta kwota
# w „Pozostałe" segmentu. Testy tego nie widziały, bo SQLite grupuje
# z rozróżnianiem wielkości liter.
#
# Zasada: KAŻDE miejsce, które zestawia wyniki dwóch zapytań po wartości
# wymiaru albo składa kilka wierszy jednego zapytania w jedną wartość, robi to
# przez `klucz_grupy` / `dopasuj_wiersze`, a nie przez `==` na napisie.
# Normalizacja danych przy zapisie tego nie zastąpi: zapisy przychodzą
# z BaseLinkera przy każdej synchronizacji, a część pól (sposób dostawy, forma
# płatności) Arkusz odsyła z powrotem do BaseLinkera.

def klucz_grupy(wartosc):
    """Klucz, pod którym BAZA uznaje wartość wymiaru za tę samą grupę.

    Odtwarza porównanie kolacji `utf8mb4_unicode_ci` (sprawdzone na MySQL 8.4,
    24.09.2026, oraz na wszystkich zapisach wymiarów z lokalnego zrzutu
    produkcji — podział na grupy identyczny z `GROUP BY` bazy):

    - wielkość liter się nie liczy („Kurier" = „kurier", „ß" = „ss");
    - znaki diakrytyczne ROZKŁADALNE się nie liczą („ą" = „a", „ó" = „o",
      „ć" = „c") — ale „ł" to nie „l", bo Unicode nie rozkłada „ł" na „l"
      i znak, i baza też ich nie utożsamia;
    - spacje NA KOŃCU się nie liczą (kolacja PAD SPACE), inne białe znaki
      i spacje na początku — tak.

    Napis zamienia się na klucz, krotka (wymiar złożony) — składnik po
    składniku, każda inna wartość (None, liczba, data, bool) zostaje sobą:
    NULL i pusty napis to w `GROUP BY` dwie osobne grupy.
    """
    if isinstance(wartosc, tuple):
        return tuple(klucz_grupy(skladowa) for skladowa in wartosc)
    if not isinstance(wartosc, str):
        return wartosc
    rozlozony = unicodedata.normalize('NFD', wartosc.casefold())
    return ''.join(znak for znak in rozlozony
                   if not unicodedata.combining(znak)).rstrip(' ')


def dopasuj_wiersze(wartosci: Sequence, wiersze: Sequence[Dict[str, object]]
                    ) -> Tuple[List[Optional[Dict[str, object]]], List[Dict[str, object]]]:
    """Każdej wartości z `wartosci` — wiersz z `wiersze` tej samej grupy albo None.

    `wiersze` to wynik INNEGO zapytania (np. segmentu) z kluczem `wartosc`.
    Zwraca parę: listę wierszy równoległą do `wartosci` i resztę wierszy bez
    pary, w ich kolejności.

    Każdy wiersz trafia do co najwyżej jednej wartości. Najpierw DOKŁADNY
    zapis, dopiero potem ta sama grupa (`klucz_grupy`). Na MySQL-u kolejność
    nie ma znaczenia (w jednym zapytaniu grupa jest jednym wierszem), ale
    SQLite testów grupuje z rozróżnianiem wielkości liter i „Kurier"
    z „kurier" to tam dwa wiersze — samo dopasowanie po grupie dałoby obu ten
    sam wiersz segmentu i policzyło jego kwotę dwa razy.
    """
    przydzial: List[Optional[Dict[str, object]]] = [None] * len(wartosci)
    zajete = set()

    po_zapisie: Dict[object, List[int]] = {}
    for i, wiersz in enumerate(wiersze):
        po_zapisie.setdefault(wiersz['wartosc'], []).append(i)
    for j, wartosc in enumerate(wartosci):
        wolny = next((i for i in po_zapisie.get(wartosc, ()) if i not in zajete), None)
        if wolny is not None:
            przydzial[j] = wiersze[wolny]
            zajete.add(wolny)

    po_grupie: Dict[object, List[int]] = {}
    for i, wiersz in enumerate(wiersze):
        if i not in zajete:
            po_grupie.setdefault(klucz_grupy(wiersz['wartosc']), []).append(i)
    for j, wartosc in enumerate(wartosci):
        if przydzial[j] is not None:
            continue
        kandydaci = po_grupie.get(klucz_grupy(wartosc))
        if kandydaci:
            wolny = kandydaci.pop(0)
            przydzial[j] = wiersze[wolny]
            zajete.add(wolny)

    return przydzial, [w for i, w in enumerate(wiersze) if i not in zajete]


def naleznosci_wg_wieku(na_dzien: date, filtr=None) -> List[Dict[str, object]]:
    """Saldo w kubełkach wieku. Liczone RAZ na zamówienie.

    Uwaga interpretacyjna: na produkcji 596 tys. zł z tego siedzi w kubełku
    >90 dni, ale 50 z tych zamówień ma status „W produkcji — surowe", a jedno
    „Nowe — opłacone". To nie są należności, tylko rekordy, których nikt nie
    domknął w BaseLinkerze. Widget musi to komunikować.

    Warunek `balance_due > 0` jest CELOWY i zostaje: kubełki wieku to
    należności, nie saldo netto. Zamówienia z saldem ujemnym (nadpłaty) mają
    osobną funkcję — `nadplaty()` niżej — właśnie dlatego, że są inną
    kategorią, a nie brakującym kubełkiem.
    """
    wiersze = (
        db.session.query(SalesOrder.date_created, SalesOrder.balance_due)
        .filter(SalesOrder.balance_due > 0, *warunki_zamowienia(filtr))
        .all()
    )

    wynik = {nazwa: {'kubelek': nazwa, 'zamowienia': 0, 'saldo': Decimal('0')}
             for nazwa, _, _ in _KUBELKI_WIEKU}
    for dzien, saldo in wiersze:
        wiek = (na_dzien - dzien).days
        for nazwa, od_dni, do_dni in _KUBELKI_WIEKU:
            if od_dni <= wiek <= do_dni:
                wynik[nazwa]['zamowienia'] += 1
                wynik[nazwa]['saldo'] += _zero(saldo)
                break
    return list(wynik.values())


def naleznosci_wg_wymiaru(nazwa: str, od: date, do: date,
                          filtr=None) -> List[Dict[str, object]]:
    """Saldo dodatnie zamówień Z OKRESU, w przekroju wymiaru zamówienia.

    Karta „Należności według" ma domyślnie kubełki wieku, ale użytkownik może
    przełączyć ją na opiekuna albo kanał — i wtedy pyta „komu ile wisi",
    a nie „jak stare to jest".

    Zapytanie idzie po SAMYM `SalesOrder`, bez pozycji: saldo żyje na
    zamówieniu i join z `sales_order_items` pomnożyłby je przez liczbę pozycji
    (pułapka 1 z nagłówka tego modułu — 5 618 320 zł zamiast 741 279 zł).
    Dlatego wymiar MUSI być kolumną zamówienia; wymiar pozycji odrzucamy
    wyjątkiem, zamiast po cichu podać zawyżoną sumę.

    Warunek `balance_due > 0` jest ten sam, co w `naleznosci_wg_wieku` —
    oba przekroje tej karty mają liczyć TO SAMO, tylko inaczej pogrupowane.
    Zamówienia z nadpłatą zostają poza nimi i mają własną pozycję.
    """
    pole = POLA.get(nazwa)
    if pole is None or not pole.wymiar or pole.skladniki is not None:
        raise ValueError(f"'{nazwa}' nie jest prostym wymiarem w rejestrze pól")
    if pole.poziom is not Poziom.ZAMOWIENIE:
        raise ValueError(f"'{nazwa}' opisuje pozycję, a saldo żyje na zamówieniu "
                         '— grupowanie po nim zwielokrotniłoby należności')

    kolumna = kolumny_wymiaru(nazwa)[0]
    wiersze = (
        db.session.query(
            kolumna.label('wartosc'),
            func.sum(SalesOrder.balance_due).label('saldo'),
            func.count(SalesOrder.id).label('zamowienia'),
        )
        .filter(SalesOrder.balance_due > 0,
                SalesOrder.date_created >= od, SalesOrder.date_created <= do,
                *warunki_zamowienia(filtr))
        .group_by(kolumna)
        .order_by(func.sum(SalesOrder.balance_due).desc())
        .all()
    )
    return [{'wartosc': w.wartosc, 'saldo': _zero(w.saldo),
             'zamowienia': int(w.zamowienia or 0)} for w in wiersze]


def nadplaty(filtr=None) -> Dict[str, object]:
    """Zamówienia z saldem UJEMNYM — dokładnie to, co `naleznosci_wg_wieku`
    odrzuca warunkiem `balance_due > 0` (i słusznie — patrz komentarz tam,
    ten warunek zostaje niezmieniony).

    Nadpłaty są CAŁĄ różnicą między sumą kubełków wieku a KPI „Saldo": oba
    są policzone poprawnie, tylko z innego zbioru zamówień. Zmierzone na
    zrzucie produkcji 21.09.2026: 741 279,02 zł (same salda dodatnie) wobec
    732 418,20 zł (KPI, saldo netto) — różnicę robi 13 zamówień na łącznie
    -8 860,82 zł. Karta należności pokazuje tę liczbę osobno, żeby czytelnik
    sam zestawił `należności − nadpłaty = saldo`, zamiast dostać dwie zgodne
    ze sobą, ale niewytłumaczone liczby na jednym ekranie.
    """
    wiersz = (
        db.session.query(func.count(SalesOrder.id), func.sum(SalesOrder.balance_due))
        .filter(SalesOrder.balance_due < 0, *warunki_zamowienia(filtr))
        .one()
    )
    # Suma ujemnych sald jest ujemna z definicji. Karta ma pokazać KWOTĘ
    # nadpłaty jako liczbę dodatnią („nadpłacono X zł”), więc odwracamy znak
    # tutaj, RAZ, a nie w szablonie czy w JavaScripcie.
    return {'zamowienia': int(wiersz[0] or 0), 'saldo': -_zero(wiersz[1])}
