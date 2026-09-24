# -*- coding: utf-8 -*-
"""Agregaty wyłącznie dla Eksploratora.

Panel miar potrzebuje dwóch liczb, których `wg_wymiaru` nie daje: ilu klientów
stoi za wartością wymiaru i ilu z nich kupiło pierwszy raz. Panel przestawienia
potrzebuje siatki dwuwymiarowej, której nie da się złożyć z pojedynczych
grupowań bez N zapytań.

WIRTUALNY WYMIAR „miesiac"
==========================
Kolumnami przestawienia bywa miesiąc, a `miesiac` nie jest polem rejestru —
jest pochodną `date_created`. Traktujemy go jako osobny, jawnie nazwany
przypadek (`PRZESTAWIENIE_MIESIAC`), a nie jako wpis w `POLA`: rejestr opisuje
kolumny, które istnieją w bazie, i dopisanie do niego bytu wyliczanego
rozmyłoby jego znaczenie dla arkusza i zapisu zwrotnego.
"""

from datetime import date
from decimal import Decimal
from typing import Dict, List, Optional

from extensions import db
# kolumny_wymiaru jest WSPOLNE z aggregates.py — jedna reguła, co wolno
# postawić na osi, obowiązuje dashboard i Eksplorator. Druga kopia walidacji
# znaczyłaby, że oba mogą kiedyś przyjąć inny zbiór wymiarów.
from modules.reports.aggregates import (
    _GRUPY_BEZ_OBJETOSCI, _zero, SEPARATOR_ZLOZONY, klucz_grupy, kolumny_wymiaru,
)
from modules.reports.analytics import MIESIACE_MALE, kolejne_miesiace
from modules.reports.filters import warunki_pozycji
from modules.reports.models_sales import SalesClient, SalesOrder, SalesOrderItem

PRZESTAWIENIE_MIESIAC = 'miesiac'

# Ile wierszy i kolumn wchodzi na siatkę przestawienia.
#
# `date_created` („Data") jest normalną pozycją w OBU selektorach, więc bez
# limitu dwa kliknięcia w interfejsie zawieszają przeglądarkę: zmierzone na
# produkcyjnych danych „Data × Data" to odpowiedź 7 852 841 B i tabela
# 406 × 406, czyli 164 836 komórek do zbudowania w DOM-ie.
#
# Ogon nie jest UCINANY, tylko zwijany w jeden wiersz i jedną kolumnę
# „Pozostałe" — inaczej suma przestałaby się zgadzać z panelem miar, a to
# najgorszy możliwy rodzaj limitu w raporcie sprzedaży.
MAKS_WIERSZY = 40
MAKS_KOLUMN = 24

# Klucz kolumny zbiorczej. Podkreślenia po obu stronach, żeby nie zderzył się
# z żadną wartością z BaseLinkera.
KLUCZ_POZOSTALE = '__pozostale__'
ETYKIETA_POZOSTALE = 'Pozostałe'


def _etykiety_kolumn(kolumny):
    """Kolumny grupowania z aliasami w0, w1, … — potrzebne, żeby odczytać
    wartości składowe wymiaru złożonego z jednego wiersza wyniku."""
    return [kolumna.label(f'w{i}') for i, kolumna in enumerate(kolumny)]


def _wartosc(wiersz, ile: int):
    """Surowa wartość dla wymiaru jednokolumnowego, krotka dla złożonego —
    dokładnie ta sama umowa co w `wg_wymiaru`."""
    skladowe = tuple(getattr(wiersz, f'w{i}') for i in range(ile))
    return skladowe[0] if ile == 1 else skladowe


def _tekst_wartosci(wartosc) -> str:
    """Wartość jako napis, używany jako KLUCZ kolumny przestawienia.

    Klucz musi być napisem, bo trafia do słownika serializowanego do JSON-a.
    Wymiar złożony sklejamy tym samym separatorem co etykietę karty.
    """
    if isinstance(wartosc, tuple):
        return SEPARATOR_ZLOZONY.join('' if s is None else str(s) for s in wartosc)
    return '' if wartosc is None else str(wartosc)


def _miara_wyrazenie(miara: str):
    """Wyrażenie SQL dla miary przestawienia."""
    if miara == 'netto':
        return db.func.sum(SalesOrderItem.value_net)
    if miara == 'objetosc':
        # Usługi (suszenie) nie mają objętości — ilość oznacza tam m3.
        return db.func.sum(db.case(
            (SalesOrderItem.group_type.in_(_GRUPY_BEZ_OBJETOSCI), 0),
            else_=SalesOrderItem.total_volume))
    if miara == 'zamowienia':
        return db.func.count(db.func.distinct(SalesOrder.id))
    raise ValueError(f"'{miara}' nie jest miarą przestawienia")


def klienci_wg_wymiaru(nazwa: str, od: date, do: date,
                       filtr=None) -> Dict[object, Dict[str, int]]:
    """Ilu klientów i ilu nowych klientów stoi za każdą wartością wymiaru.

    Liczymy po DISTINCT kliencie, nie po zamówieniu: klient z trzema
    zamówieniami w kanale to jeden klient. `COUNT(DISTINCT CASE WHEN ...)`
    działa tak samo na MySQL-u i na SQLite.

    Zapytanie idzie po `SalesOrderItem JOIN SalesOrder`, więc filtr wchodzi
    przez `warunki_pozycji` — saldo tu nie występuje, więc EXISTS nie jest
    potrzebny, a `COUNT(DISTINCT ...)` i tak nie da się zwielokrotnić.
    """
    kolumny = kolumny_wymiaru(nazwa)

    nowy_klient = db.case(
        (db.and_(SalesClient.first_order_at >= od,
                 SalesClient.first_order_at <= do), SalesClient.id),
        else_=None,
    )

    wiersze = (
        db.session.query(
            *_etykiety_kolumn(kolumny),
            db.func.count(db.func.distinct(SalesOrder.client_id)).label('klienci'),
            db.func.count(db.func.distinct(nowy_klient)).label('nowi'),
        )
        .select_from(SalesOrderItem)
        .join(SalesOrder, SalesOrderItem.order_id == SalesOrder.id)
        .outerjoin(SalesClient, SalesOrder.client_id == SalesClient.id)
        .filter(SalesOrder.date_created >= od, SalesOrder.date_created <= do,
                *warunki_pozycji(filtr))
        .group_by(*kolumny)
        .all()
    )

    return {_wartosc(w, len(kolumny)): {'klienci': int(w.klienci or 0),
                                        'nowi': int(w.nowi or 0)}
            for w in wiersze}


def _podpisy_grup(pary) -> Dict[object, object]:
    """Klucz grupy (`aggregates.klucz_grupy`) -> ZAPIS, którym przestawienie ją podpisuje.

    `pary` to (surowy zapis, wartość miary) z kolejnych wierszy wyniku.

    Zapytanie przestawienia grupuje po wymiarze ORAZ po miesiącu (albo drugim
    wymiarze), a w kolacji bazy „Kurier" i „kurier" to jedna wartość — baza
    oddaje ją w każdej komórce zapisem, który sama wybierze. Scalane po
    napisie, ta sama wartość stała w dwóch wierszach: „Forma płatności" miała
    25 wierszy zamiast 23 (lokalny zrzut produkcji, 24.09.2026).

    Podpisem jest zapis o NAJWIĘKSZEJ sumie miary, przy remisie pierwszy
    w porządku napisów — ten sam przy każdym odświeżeniu, niezależnie od
    kolejności, w jakiej baza oddała wiersze.
    """
    wagi: Dict[object, Dict[object, Decimal]] = {}
    for zapis, waga in pary:
        zapisy = wagi.setdefault(klucz_grupy(zapis), {})
        zapisy[zapis] = zapisy.get(zapis, Decimal('0')) + waga
    return {klucz: min(zapisy, key=lambda z, zapisy=zapisy: (-zapisy[z], str(z)))
            for klucz, zapisy in wagi.items()}


def _zmiana(szereg: List[Decimal]) -> Optional[Decimal]:
    """Zmiana między pierwszą a ostatnią kolumną. None przy zerowej bazie."""
    if len(szereg) < 2 or not szereg[0]:
        return None
    return ((szereg[-1] - szereg[0]) * 100 / szereg[0]).quantize(Decimal('0.1'))


def _kolejnosc_kolumn(surowe: Dict[str, object]) -> List[str]:
    """Kolejność kolumn po WARTOŚCI SUROWEJ, nie po jej zapisie tekstowym.

    Leksykalnie grubości ustawiają się '(brak)', '0.50', '1.00', '1.10',
    '10.00', '2.00', '27.00', '3.00' — czyli tak, że nikt nie znajdzie tej,
    której szuka. Pusta wartość idzie pierwsza, tak jak w panelu miar.

    Wolny tekst z BaseLinkera potrafi wpaść do kolumny obok liczby i wtedy
    porównanie rzuca TypeError; wracamy wtedy do porządku po napisie, bo
    dziwna kolejność jest lepsza niż wyjątek na całym panelu.
    """
    def klucz(nazwa):
        wartosc = surowe[nazwa]
        return (wartosc is not None, wartosc)

    try:
        return sorted(surowe, key=klucz)
    except TypeError:
        return sorted(surowe)


def _kolumny_miesiecy(od: date, do: date) -> List[Dict[str, object]]:
    """Wszystkie miesiące okresu, także PUSTE — oś budujemy z zakresu, nie z danych.

    To ta sama klasa błędu, którą `szereg_miesieczny` zamyka po stronie wykresu
    trendu: dziura w osi skleiłaby marzec z majem i pokazała wzrost, którego
    nie było. Iskierka w panelu przestawienia i kolumna „Zmiana" liczą się
    z tego samego szeregu, więc bez uzupełniania kłamałyby dokładnie tak samo.

    Rok w etykiecie pojawia się dopiero wtedy, gdy okres przechodzi przez
    granicę roku — przy presecie „całość" (do 1100 dni) trzy kolumny podpisane
    `lip` byłyby nie do odróżnienia.
    """
    pary = kolejne_miesiace(od, do)
    wiele_lat = len({rok for rok, _ in pary}) > 1
    return [{'klucz': f'{rok}-{miesiac:02d}',
             'etykieta': MIESIACE_MALE[miesiac - 1]
                         + (f' {str(rok)[2:]}' if wiele_lat else '')}
            for rok, miesiac in pary]


def _zwin_ogon_wierszy(wiersze: List[Dict[str, object]], klucze: List[str],
                       miesieczne: bool) -> List[Dict[str, object]]:
    """Ogon ponad `MAKS_WIERSZY` w jeden wiersz zbiorczy — tak jak karty
    dashboardu zwijają swój ogon w „Pozostałe (N)".

    Zwijamy, a nie ucinamy: wiersz „Razem" liczy się z tej listy, więc ucięcie
    rozjechałoby sumę przestawienia z sumą panelu miar na tym samym ekranie.
    """
    gora = wiersze[:MAKS_WIERSZY - 1]
    ogon = wiersze[MAKS_WIERSZY - 1:]
    komorki = {k: sum((w['komorki'][k] for w in ogon), Decimal('0')) for k in klucze}
    szereg = [komorki[k] for k in klucze]
    gora.append({
        'wartosc': None,
        'etykieta': f'{ETYKIETA_POZOSTALE} ({len(ogon)})',
        'komorki': komorki,
        'szereg': szereg if miesieczne else None,
        'suma': sum(szereg, Decimal('0')),
        'zmiana': _zmiana(szereg) if miesieczne else None,
        # Za tym wierszem nie stoi żadna wartość wymiaru — serwis nie ma
        # czego przemapować na etykietę po polsku i ma go pominąć.
        'zbiorczy': True,
    })
    return gora


def przestawienie(wymiar: str, kolumny: str, miara: str,
                  od: date, do: date, filtr=None) -> Dict[str, object]:
    """Siatka wymiar × (miesiąc albo drugi wymiar) dla jednej miary.

    To, co ludzie robią w Excelu tabelą przestawną — tylko zawsze na aktualnych
    danych. Jedno zapytanie, nie jedno na wiersz.

    `miara` jest ograniczona do trzech wartości addytywnych (`netto`,
    `objetosc`, `zamowienia`). Miary pochodne (udział, średnie zamówienie,
    zł/m3) nie sumują się po kolumnach, więc w przestawieniu nie mają sensu —
    żyją w panelu miar.

    Oba wymiary mogą być złożone. Wiersz niesie wtedy krotkę składowych
    w `wartosc`, a kolumna — składowe sklejone separatorem, bo jej klucz
    musi być napisem (trafia do słownika serializowanego do JSON-a).
    """
    kolumny_wiersza = kolumny_wymiaru(wymiar)
    ile_wiersza = len(kolumny_wiersza)
    wyrazenie = _miara_wyrazenie(miara)
    # Iskierka i „Zmiana" mówią o UPŁYWIE CZASU. Przy drugim wymiarze
    # na osi kolumn liczyłyby „pierwsza kolumna kontra ostatnia", czyli
    # np. sprzedaż jednego opiekuna kontra sprzedaż drugiego — podane jako
    # trend, na zielono (zmierzone: +310,7% dla wiersza „personal"
    # i +656,9% dla „Razem" przy przestawienie=caretaker).
    miesieczne = kolumny == PRZESTAWIENIE_MIESIAC

    podstawa = (
        db.session.query()
        .select_from(SalesOrderItem)
        .join(SalesOrder, SalesOrderItem.order_id == SalesOrder.id)
        .filter(SalesOrder.date_created >= od, SalesOrder.date_created <= do,
                *warunki_pozycji(filtr))
    )

    if miesieczne:
        rok = db.extract('year', SalesOrder.date_created)
        miesiac = db.extract('month', SalesOrder.date_created)
        wiersze = (podstawa
                   .add_columns(*_etykiety_kolumn(kolumny_wiersza),
                                rok.label('rok'), miesiac.label('miesiac'),
                                wyrazenie.label('miara'))
                   .group_by(*kolumny_wiersza, rok, miesiac)
                   .all())
        # Oś z ZAKRESU, nie z danych — patrz docstring _kolumny_miesiecy.
        opis_kolumn = _kolumny_miesiecy(od, do)
        klucz_kolumny = lambda w: f'{int(w.rok)}-{int(w.miesiac):02d}'  # noqa: E731
    else:
        kolumny_kolumn = kolumny_wymiaru(kolumny)
        ile_kolumny = len(kolumny_kolumn)
        etykiety_kolumn = [k.label(f'k{i}') for i, k in enumerate(kolumny_kolumn)]
        wiersze = (podstawa
                   .add_columns(*_etykiety_kolumn(kolumny_wiersza),
                                *etykiety_kolumn,
                                wyrazenie.label('miara'))
                   .group_by(*kolumny_wiersza, *kolumny_kolumn)
                   .all())

        def zapis_kolumny(w):  # noqa: E306
            skladowe = tuple(getattr(w, f'k{i}') for i in range(ile_kolumny))
            return skladowe if ile_kolumny > 1 else skladowe[0]

        # Kolumna to GRUPA bazy, nie zapis: „Kurier" i „kurier" to jedna
        # kolumna podpisana jednym zapisem (patrz `_podpisy_grup`).
        podpisy_kolumn = _podpisy_grup((zapis_kolumny(w), _zero(w.miara)) for w in wiersze)

        def surowa_kolumny(w):  # noqa: E306
            return podpisy_kolumn[klucz_grupy(zapis_kolumny(w))]

        def klucz_kolumny(w):  # noqa: E306
            return _tekst_wartosci(surowa_kolumny(w))

        # Wartość surową trzymamy obok klucza: po niej sortujemy oś, a serwis
        # mapuje z niej etykietę po polsku (`analiza_service` — `explorer`
        # o etykietach nie wie i ma nie wiedzieć).
        surowe: Dict[str, object] = {}
        sumy_kolumn: Dict[str, Decimal] = {}
        for w in wiersze:
            klucz = klucz_kolumny(w)
            surowe.setdefault(klucz, surowa_kolumny(w))
            sumy_kolumn[klucz] = sumy_kolumn.get(klucz, Decimal('0')) + _zero(w.miara)

        uporzadkowane = _kolejnosc_kolumn(surowe)
        zwiniete = set()
        if len(uporzadkowane) > MAKS_KOLUMN:
            # Zostają najważniejsze po sumie miary — nie pierwsze alfabetycznie.
            zostaja = set(sorted(sumy_kolumn, key=lambda k: sumy_kolumn[k],
                                 reverse=True)[:MAKS_KOLUMN])
            zwiniete = {k for k in uporzadkowane if k not in zostaja}
            uporzadkowane = [k for k in uporzadkowane if k in zostaja]

        opis_kolumn = [{'klucz': k, 'wartosc': surowe[k], 'etykieta': k or '(brak)'}
                       for k in uporzadkowane]
        if zwiniete:
            opis_kolumn.append({
                'klucz': KLUCZ_POZOSTALE, 'wartosc': None, 'zbiorcza': True,
                'etykieta': f'{ETYKIETA_POZOSTALE} ({len(zwiniete)})'})
        # Dalej wypełniamy siatkę kluczem JUŻ ZWINIĘTYM, żeby pętla poniżej
        # nie musiała wiedzieć o limicie. `surowy_klucz` zapamiętuje poprzednią
        # funkcję PRZED podmianą — inaczej lambda wołałaby samą siebie.
        surowy_klucz, zwiniete_klucze = klucz_kolumny, zwiniete
        klucz_kolumny = (  # noqa: E731
            lambda w: KLUCZ_POZOSTALE if surowy_klucz(w) in zwiniete_klucze
            else surowy_klucz(w))

    klucze = [k['klucz'] for k in opis_kolumn]
    zbior_kluczy = set(klucze)
    # Wiersz to GRUPA bazy, nie zapis — tak jak kolumna wyżej. Bez tego
    # wartość, którą baza oddała w sierpniu jako „Kurier", a we wrześniu jako
    # „kurier", stała w dwóch wierszach po pół sprzedaży.
    podpisy_wierszy = _podpisy_grup((_wartosc(w, ile_wiersza), _zero(w.miara))
                                    for w in wiersze)
    siatka: Dict[object, Dict[str, Decimal]] = {}
    for w in wiersze:
        wartosc_wiersza = podpisy_wierszy[klucz_grupy(_wartosc(w, ile_wiersza))]
        klucz = klucz_kolumny(w)
        komorki = siatka.setdefault(wartosc_wiersza, {})
        # DODAJEMY, nie przypisujemy. NULL i pusty napis dają TEN SAM klucz
        # kolumny (`_tekst_wartosci` mapuje oba na ''), więc przypisanie
        # kasowało jedną z dwóch grup — bez śladu w komórce, w sumie wiersza
        # i w wierszu „Razem" (1000 zł + 2000 zł pokazywało 2000 zł).
        #
        # Klucz spoza osi (miesiąc bez pokrycia w `kolejne_miesiace` nie zdarzy
        # się, ale wartość drugiego wymiaru zawsze jest na osi) pomijamy cicho.
        if klucz in zbior_kluczy:
            komorki[klucz] = komorki.get(klucz, Decimal('0')) + _zero(w.miara)

    def zbuduj(wartosc, komorki):
        szereg = [komorki.get(k, Decimal('0')) for k in klucze]
        tekst = _tekst_wartosci(wartosc)
        return {
            'wartosc': wartosc,
            'etykieta': tekst if tekst.strip() else '(brak)',
            'komorki': {k: komorki.get(k, Decimal('0')) for k in klucze},
            'szereg': szereg if miesieczne else None,
            'suma': sum(szereg, Decimal('0')),
            'zmiana': _zmiana(szereg) if miesieczne else None,
            'zbiorczy': False,
        }

    zbudowane = [zbuduj(wartosc, komorki) for wartosc, komorki in siatka.items()]
    zbudowane.sort(key=lambda w: w['suma'], reverse=True)
    if len(zbudowane) > MAKS_WIERSZY:
        zbudowane = _zwin_ogon_wierszy(zbudowane, klucze, miesieczne)

    suma_szereg = [sum((w['komorki'][k] for w in zbudowane), Decimal('0')) for k in klucze]
    suma = {
        'etykieta': 'Razem',
        'komorki': dict(zip(klucze, suma_szereg)),
        'szereg': suma_szereg if miesieczne else None,
        'suma': sum(suma_szereg, Decimal('0')),
        'zmiana': _zmiana(suma_szereg) if miesieczne else None,
    }

    # `trend` mówi frontowi, czy kolumny „Trend" i „Zmiana" w ogóle rysować.
    return {'kolumny': opis_kolumn, 'wiersze': zbudowane, 'suma': suma,
            'miara': miara, 'trend': miesieczne}
