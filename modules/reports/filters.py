# -*- coding: utf-8 -*-
"""Filtr agregatów Analizy sprzedażowej: format w adresie i warunki SQL.

JEDEN MECHANIZM, DWA ZASTOSOWANIA
=================================
Segment porównawczy na dashboardzie („Dodaj porównanie +") i kontrolka „Filtr"
w Eksploratorze wybierają ten sam obiekt: koniunkcję warunków po wymiarach.
Dwie osobne implementacje rozjechałyby się przy pierwszej zmianie formatu,
więc jest jedna, tutaj.

DWA PRZEŁOŻENIA NA SQL — I DLACZEGO TO NIE JEST NADMIAROWE
===========================================================
Saldo i kwota wpłaty żyją na ZAMÓWIENIU, netto i objętość na POZYCJI. Filtr po
polu pozycji dołożony joinem do zapytania sumującego saldo powieli je przez
liczbę pasujących pozycji — czyli odtworzy błąd 7,58× z poprzednika
(5 618 320 zł zamiast 741 279 zł, zmierzone na produkcji 21.09.2026).

Dlatego:
- `warunki_pozycji`  — do zapytania `SalesOrderItem JOIN SalesOrder`. Warunek
  po polu pozycji zawęża POZYCJE, bo netto i objętość i tak liczą się z nich.
- `warunki_zamowienia` — do zapytania po samym `SalesOrder`. Warunek po polu
  pozycji wchodzi skorelowanym `EXISTS`, który niczego nie zwielokrotnia.

FORMAT W ADRESIE
================
    ?filtr=order_source:shop,wood_species:d%C4%85b|jesion

Człony rozdzielone przecinkiem to koniunkcja, wartości po pionowej kresce to
alternatywa w obrębie jednego wymiaru. Wartości są URL-kodowane osobno, bo
Flask rozpakowuje parametr tylko raz, a `delivery_method` z BaseLinkera bywa
wolnym tekstem z przecinkiem. Pusta wartość znaczy „brak wartości", czyli
`NULL` albo pusty string — karty pokazują wiersz `(brak)`, więc musi dać się
go wybrać.

WARUNEK STAŁY: TYLKO SPRZEDAŻ (partia E, punkt E5)
===================================================
Zamówienia anulowane i nieopłacone nie są sprzedażą (`service.
STATUSY_POZA_SPRZEDAZA`). Warunek jest dokładany TUTAJ, w obu funkcjach
warunków, także przy pustym filtrze — bo przez nie idzie każde zapytanie
sumujące pulpitu, segmentu porównawczego i Eksploratora. Warunek wpisywany
przy każdym zapytaniu z osobna zostałby kiedyś pominięty w nowym.

Jest NIEZALEŻNY od filtra użytkownika i łączy się z nim koniunkcją. Filtr
(także pola wykluczeń pozycji — punkty E4 i E8, sekcja „WYKLUCZENIA
POZYCJI" na końcu modułu) dalej wyraża się słownikiem `Filtr`;
warunek stały nie jest jego częścią,
więc nie trafia do adresu, do klucza pamięci żądania ani do opisu kontrolki.

Leży na POZIOMIE ZAMÓWIENIA (`SalesOrder.baselinker_status_id`), więc
w zapytaniu po samym `SalesOrder` jest zwykłym `WHERE` — bez joina z
pozycjami i bez ryzyka powielenia salda.

Z warunku zwalnia wyłącznie `tylko_sprzedaz=False`. Woła tak jedynie Arkusz,
bo pokazuje WSZYSTKIE zamówienia (zastępuje Excela i anulowanie ma tam być
widać) — ale jego stopka sumuje już z warunkiem, tak jak pulpit.
"""

from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Dict, List, Optional
from urllib.parse import quote, unquote

from extensions import db
from modules.reports.fields import POLA, Poziom, Zrodlo
from modules.reports.models_sales import SalesOrder, SalesOrderItem
from modules.reports.service import STATUSY_POZA_SPRZEDAZA

# Nazwa wymiaru z rejestru -> lista dopuszczalnych wartości (alternatywa).
# Różne klucze łączy koniunkcja.
Filtr = Dict[str, List[str]]

SEPARATOR_WARUNKOW = ','
SEPARATOR_WARTOSCI = '|'
SEPARATOR_POLA = ':'

# Ile wartości pokazujemy w skrócie, zanim przejdziemy na „+N".
_ILE_W_OPISIE = 2

# Napis dla wartości pustej w opisie kontrolki. Ta sama co w serwisie
# dashboardu — obie warstwy mówią o tym samym wierszu.
PUSTA_WARTOSC = '(brak)'


def _sprawdz_wymiar(nazwa: str):
    """Zwraca pole rejestru albo rzuca ValueError z powodem po polsku."""
    pole = POLA.get(nazwa)
    if pole is None or not pole.wymiar:
        raise ValueError(f"'{nazwa}' nie jest wymiarem w rejestrze pól")
    if pole.skladniki is not None:
        raise ValueError(f"'{nazwa}' jest wymiarem złożonym — po nim nie filtrujemy")
    if pole.zrodlo is Zrodlo.PRODUKCJA:
        raise ValueError(f"'{nazwa}' pochodzi z modułu produkcji")
    return pole


def parsuj_filtr(tekst: Optional[str]) -> Optional[Filtr]:
    """Filtr z parametru adresu. `None`, gdy parametru nie ma albo jest pusty."""
    if not tekst or not tekst.strip():
        return None

    filtr: Filtr = {}
    for czlon in tekst.split(SEPARATOR_WARUNKOW):
        if not czlon.strip():
            continue
        if SEPARATOR_POLA not in czlon:
            raise ValueError(f"'{czlon}' nie ma postaci pole:wartość")
        nazwa, surowe = czlon.split(SEPARATOR_POLA, 1)
        nazwa = nazwa.strip()
        _sprawdz_wymiar(nazwa)
        if nazwa in filtr:
            # Cicha wygrana ostatniego członu byłaby pułapką: użytkownik
            # zobaczyłby w kontrolce co innego niż liczą agregaty.
            raise ValueError(f"'{nazwa}' występuje w filtrze dwa razy — "
                             f"alternatywę zapisuje się pionową kreską")
        wartosci = [unquote(w) for w in surowe.split(SEPARATOR_WARTOSCI)]
        # Wartość niezgodna z typem kolumny ma polec TUTAJ, przy parsowaniu
        # adresu: trasy łapią ValueError i oddają 400 z komunikatem po polsku.
        # Puszczona dalej dochodzi do MySQL-a, który odrzuca całe zapytanie
        # błędem 1525 „Incorrect DATE value" — użytkownik dostaje 500.
        _sprawdz_wartosci(nazwa, wartosci)
        filtr[nazwa] = wartosci

    return filtr or None


def _sprawdz_wartosci(nazwa: str, wartosci: List[str]) -> None:
    """Rzuca ValueError, gdy któraś wartość nie pasuje do typu kolumny.

    Pusta wartość znaczy „brak wartości" i nie podlega konwersji — przechodzi
    zawsze, bo dla każdego typu kolumny oznacza `NULL`.
    """
    _, kolumna = _kolumna(nazwa)
    for wartosc in wartosci:
        if wartosc != '':
            _na_typ_kolumny(kolumna, wartosc)


def zapisz_filtr(filtr: Optional[Filtr]) -> str:
    """Filtr do postaci w adresie. Kolejność jest stała, żeby ten sam filtr
    dawał ten sam adres — inaczej zakładka przestałaby wskazywać ten sam widok."""
    if not filtr:
        return ''
    czesci = []
    for nazwa in sorted(filtr):
        wartosci = SEPARATOR_WARTOSCI.join(
            quote(w, safe='') for w in filtr[nazwa])
        czesci.append(nazwa + SEPARATOR_POLA + wartosci)
    return SEPARATOR_WARUNKOW.join(czesci)


def opis_filtru(filtr: Optional[Filtr]) -> str:
    """Skrót warunku do napisu w kontrolce, np. „Gatunek: dąb"."""
    if not filtr:
        return 'brak'
    czesci = []
    for nazwa in sorted(filtr):
        wartosci = [w if w != '' else PUSTA_WARTOSC for w in filtr[nazwa]]
        widoczne = ', '.join(wartosci[:_ILE_W_OPISIE])
        if len(wartosci) > _ILE_W_OPISIE:
            widoczne += f' +{len(wartosci) - _ILE_W_OPISIE}'
        czesci.append(f'{POLA[nazwa].etykieta}: {widoczne}')
    return ' · '.join(czesci)


def _kolumna(nazwa: str):
    """(model, kolumna) dla nazwy wymiaru. Model decyduje o przełożeniu na SQL."""
    pole = _sprawdz_wymiar(nazwa)
    model = SalesOrder if pole.poziom is Poziom.ZAMOWIENIE else SalesOrderItem
    return model, getattr(model, nazwa)


# Słowa uznawane za PRAWDA/FAŁSZ w wartości logicznej z adresu. Rozpoznane
# w obie strony — inaczej `False`/„nie" jedzie tym samym torem co wartość
# bez sensu, a to i jest ten błąd.
_WARTOSCI_PRAWDA = ('1', 'true', 'tak', 't', 'y')
_WARTOSCI_FALSZ = ('0', 'false', 'nie', 'f', 'n')


def _na_typ_kolumny(kolumna, wartosc: str):
    """Tekst z adresu na typ kolumny.

    Bez tego filtr po `own_transport` porównywałby TINYINT z napisem „true"
    i nigdy nic nie znajdował, a filtr po `thickness_cm` porównywałby DECIMAL
    z napisem. `python_type` bywa niezaimplementowane dla typów złożonych,
    stąd ostrożne `try`.

    Wartość, której nie da się jednoznacznie odwzorować, ma WYSADZIĆ
    parsowanie ValueError-em (trasa łapie go i oddaje 400 po polsku), a nie
    przejść dalej. Puszczona dalej dawała dwa różne ciche kłamstwa, oba
    zmierzone na produkcji:
    - BOOLEAN: `kolumna.in_([False])` dla KAŻDEJ nierozpoznanej wartości
      (`?filtr=own_transport:moze` zwracało 423 zamówienia z
      `own_transport = 0`, zamiast odrzucić filtr jako niepoprawny),
    - DECIMAL: nierozpoznana wartość wracała surowym napisem i trafiała do
      `kolumna.in_(['cokolwiek'])` — MySQL rzutuje nie-liczbę w porównaniu
      z DECIMAL-em na 0, więc `?filtr=thickness_cm:cokolwiek` po cichu
      dopasowałby wiersze z `thickness_cm = 0`, ten sam mechanizm co przy
      BOOLEAN.
    Dla DATE błąd tej klasy naprawiał już commit 44c5699 — tu domykamy
    pozostałe typy tą samą metodą.
    """
    try:
        typ = kolumna.type.python_type
    except (NotImplementedError, AttributeError):
        return wartosc

    if typ is bool:
        surowa = wartosc.strip().lower()
        if surowa in _WARTOSCI_PRAWDA:
            return True
        if surowa in _WARTOSCI_FALSZ:
            return False
        raise ValueError(
            f"'{wartosc}' nie jest wartością logiczną (tak/nie)")
    if typ in (int,):
        try:
            return int(wartosc)
        except ValueError:
            raise ValueError(f"'{wartosc}' nie jest liczbą całkowitą")
    if typ in (float, Decimal):
        try:
            return Decimal(wartosc)
        except (InvalidOperation, ValueError):
            raise ValueError(f"'{wartosc}' nie jest liczbą")
    if typ.__name__ in ('date', 'datetime'):
        try:
            return datetime.strptime(wartosc, '%Y-%m-%d').date()
        except ValueError:
            # NIE oddajemy surowego napisu. Porównanie kolumny DATE z „nie-data"
            # albo z nieistniejącym „2026-02-30" wywala MySQL-a błędem 1525
            # i cały endpoint kończy się kodem 500. Lepiej 400 z powodem.
            raise ValueError(f"'{wartosc}' nie jest datą w formacie RRRR-MM-DD")
    return wartosc


def _jest_tekstowa(kolumna) -> bool:
    """Czy kolumna trzyma tekst. Wariant `= ''` ma sens WYŁĄCZNIE dla niej."""
    try:
        return kolumna.type.python_type is str
    except (NotImplementedError, AttributeError):
        return False


def _warunek_wartosci(kolumna, wartosci: List[str]):
    """`IN` po wartościach; pusta wartość dokłada wariant NULL / pusty string.

    PUŁAPKA TYPU: `kolumna == ''` wolno dołożyć tylko do kolumny tekstowej.
    Dla DATE MySQL odpowiada błędem 1525 i użytkownik dostaje 500, a dla
    BOOLEAN i DECIMAL rzutuje `''` na 0 — i `?filtr=own_transport:` cicho
    zwraca WSZYSTKIE zamówienia z `own_transport = 0` zamiast zera wierszy
    (zmierzone na produkcji: 3324 zamówienia i 4,4 mln zł zamiast pustki).
    """
    konkretne = [_na_typ_kolumny(kolumna, w) for w in wartosci if w != '']
    warianty = []
    if konkretne:
        warianty.append(kolumna.in_(konkretne))
    if len(konkretne) != len(wartosci):
        brak = kolumna.is_(None)
        if _jest_tekstowa(kolumna):
            brak = db.or_(brak, kolumna == '')
        warianty.append(brak)
    if not warianty:
        return None
    return warianty[0] if len(warianty) == 1 else db.or_(*warianty)


def warunek_sprzedazy():
    """Zamówienie liczy się do sprzedaży — warunek SQL na `SalesOrder`.

    `NOT IN` samo nie wystarczy: dla `NULL` daje w SQL-u `NULL`, czyli
    odrzucenie wiersza, a zamówienie bez identyfikatora statusu ma się liczyć
    (patrz komentarz przy `STATUSY_POZA_SPRZEDAZA`). Stąd jawne `IS NULL`.

    Publiczny, bo kilka zapytań nie idzie przez `warunki_pozycji` ani
    `warunki_zamowienia` — złączenie wyceny z zamówieniem w lejku, ostrzeżenie
    o saldzie i przeliczenie denormalizacji klienta w `ingest.py`. Każde
    z nich dokłada TEN warunek, a nie własną kopię listy statusów.
    """
    kolumna = SalesOrder.baselinker_status_id
    return db.or_(kolumna.is_(None), kolumna.notin_(sorted(STATUSY_POZA_SPRZEDAZA)))


def liczy_sie_do_sprzedazy(status_id: Optional[int]) -> bool:
    """To samo pytanie co `warunek_sprzedazy`, zadane w Pythonie.

    Dla Arkusza, który dostaje wiersze z bazy BEZ warunku i musi sam
    oznaczyć te poza sprzedażą. Ta sama stała, ta sama reguła dla `None`.
    """
    return status_id is None or status_id not in STATUSY_POZA_SPRZEDAZA


def warunki_pozycji(filtr: Optional[Filtr], tylko_sprzedaz: bool = True) -> List:
    """Warunki do zapytania, którego FROM to `SalesOrderItem JOIN SalesOrder`.

    Netto i objętość liczą się z pozycji, więc warunek po polu pozycji zawęża
    pozycje wprost — i tak ma być. Pole zamówienia idzie na `SalesOrder`.

    Na końcu listy stoi warunek stały `warunek_sprzedazy` (patrz „WARUNEK
    STAŁY" w nagłówku modułu) — także przy pustym filtrze.
    """
    warunki = []
    for nazwa, wartosci in (filtr or {}).items():
        _, kolumna = _kolumna(nazwa)
        warunek = _warunek_wartosci(kolumna, wartosci)
        if warunek is not None:
            warunki.append(warunek)
    if tylko_sprzedaz:
        warunki.append(warunek_sprzedazy())
    return warunki


def warunki_zamowienia(filtr: Optional[Filtr], tylko_sprzedaz: bool = True) -> List:
    """Warunki do zapytania, którego FROM to samo `SalesOrder`.

    PUŁAPKA SALDA: pola pozycji NIE WOLNO tu dokładać joinem. `SUM(balance_due)`
    po dołączonych pozycjach zawyża saldo tyle razy, ile pasujących pozycji ma
    zamówienie. Warunek po polu pozycji wchodzi więc skorelowanym `EXISTS`,
    który nie zwielokrotnia wierszy.

    JEDEN EXISTS NA WSZYSTKIE POLA POZYCJI (partia E, punkt E4). Zamówienie
    liczy się wtedy, gdy ma POZYCJĘ spełniającą WSZYSTKIE warunki pozycji
    naraz — tak samo jak netto, które sumuje się z pozycji spełniających je
    wszystkie (`warunki_pozycji`). Dwa osobne EXISTS (po jednym na pole)
    przepuszczały zamówienie z pozycjami (buk, A/B) i (dąb, B/B) przy
    odznaczonych „buk" i „B/B": jedna pozycja spełniała warunek gatunku,
    druga klasy, a ŻADNA nie zostawała w netto — zamówienie liczyło się
    w liczbie zamówień i saldzie z zerowym netto.

    Warunek stały `warunek_sprzedazy` stoi na końcu listy i jest zwykłym
    warunkiem na kolumnie zamówienia — też niczego nie zwielokrotnia.
    """
    warunki = []
    warunki_pozycji_zamowienia = []
    for nazwa, wartosci in (filtr or {}).items():
        model, kolumna = _kolumna(nazwa)
        warunek = _warunek_wartosci(kolumna, wartosci)
        if warunek is None:
            continue
        if model is SalesOrder:
            warunki.append(warunek)
        else:
            warunki_pozycji_zamowienia.append(warunek)
    if warunki_pozycji_zamowienia:
        warunki.append(
            db.session.query(SalesOrderItem.id)
            .filter(SalesOrderItem.order_id == SalesOrder.id, *warunki_pozycji_zamowienia)
            .exists()
        )
    if tylko_sprzedaz:
        warunki.append(warunek_sprzedazy())
    return warunki


# --- WYKLUCZENIA POZYCJI (partia E, punkty E4 i E8) -------------------------
#
# Pola wyboru na górze pulpitu: „GATUNEK ☑ dąb ☑ buk ☑ jesion │ TECHNOLOGIA …
# │ KLASA … │ WYKOŃCZENIE …". Odznaczenie wartości wyklucza z liczb POZYCJE
# z tą wartością.
#
# TO NIE JEST DRUGI MECHANIZM FILTRA. W adresie wykluczenia mają format filtra
# (`?wyklucz=wood_class:B%2FB,wood_species:buk` — pole:wartość, alternatywa po
# pionowej kresce), a przed liczeniem zamieniają się w ZWYKŁY `Filtr`
# zaznaczonych wartości plus wartości pustej: `IN (zaznaczone) OR NULL/''`.
# Pusta wartość znaczy w filtrze „brak wartości", więc pozycje z pustym polem
# (usługi, pozycje nierozpoznane) zostają ZAWSZE.
# Naiwne `wood_species IN (zaznaczone)` wycięłoby je po cichu.
#
# Lista pól pochodzi z DANYCH (`analiza_service.wartosci_wykluczen`), więc
# „zaznaczone" jest dokładnie dopełnieniem „odznaczonych" i całość jest
# równoważna `NOT IN (odznaczone)` z zachowaniem NULL.
#
# Warunek stały „tylko sprzedaż" (E5) jest od tego niezależny: nie trafia do
# `Filtr`, a dokładają go `warunki_pozycji`/`warunki_zamowienia` — oba
# warunki łączą się koniunkcją.

# JEDYNE ŹRÓDŁO listy pól wykluczeń. Kolejność grup na pasku: gatunek,
# technologia i klasa z cytatu prezesa (E4), wykończenie dopisane przez
# użytkownika 23.09 („surowy, lakierowany, olejowany", E8) — po klasie.
# Szablon, walidacja, pigułka „Bez: …" i każde zdanie o wykluczeniach biorą
# pola STĄD, a ich nazwy z rejestru (`POLA[...].etykieta`) — czwarta grupa
# nie ma prawa zostać pominięta w zdaniu, które ktoś napisał z pamięci.
POLA_WYKLUCZEN = ('wood_species', 'technology', 'wood_class', 'finish_state')

# Pole -> ODZNACZONE wartości (to, co wypada z liczb).
Wykluczenia = Dict[str, List[str]]

KOMUNIKAT_OSTATNIEJ_WARTOSCI = 'Zostaw co najmniej jedną wartość'


def nazwy_pol_wykluczen() -> str:
    """Nazwy grup wykluczeń z rejestru, w kolejności pól wyboru — do zdań.

    Np. „Gatunek, …, Wykończenie". Mianownik i wielkie litery
    celowo: to nazwy pól, które użytkownik widzi nad polami wyboru, a nie
    odmieniane słowa w zdaniu — odmiana przez przypadki wymagałaby drugiej
    listy form obok rejestru, czyli dokładnie tego, czego ta stała pilnuje.
    """
    return ', '.join(POLA[nazwa].etykieta for nazwa in POLA_WYKLUCZEN)


def parsuj_wykluczenia(tekst: Optional[str],
                       obecne: Dict[str, List[str]]) -> Optional[Wykluczenia]:
    """Wykluczenia z parametru adresu. `None`, gdy parametru nie ma albo jest pusty.

    `obecne` to wartości obecne w danych (pole -> lista w kolejności pól
    wyboru). Rzuca ValueError z powodem po polsku, gdy parametr wskazuje pole
    spoza `POLA_WYKLUCZEN`, wartość, której w danych nie ma (także „brak wartości" —
    ten zostaje zawsze), albo odznacza WSZYSTKIE wartości pola: pulpit
    pokazałby wtedy same zera, a interfejs blokuje ostatnie pole.

    Format i jego walidację (dwukropek, to samo pole dwa razy, kodowanie
    wartości) bierzemy z `parsuj_filtr` — to ten sam format.
    """
    filtr = parsuj_filtr(tekst)
    if not filtr:
        return None
    wynik: Wykluczenia = {}
    for nazwa in POLA_WYKLUCZEN:
        if nazwa not in filtr:
            continue
        dostepne = obecne.get(nazwa) or []
        etykieta = POLA[nazwa].etykieta
        for wartosc in filtr[nazwa]:
            if wartosc not in dostepne:
                pokaz = wartosc if wartosc != '' else PUSTA_WARTOSC
                raise ValueError(f'„{pokaz}" — takiej wartości pola „{etykieta}" nie ma '
                                 f'w danych, więc nie da się jej wykluczyć')
        odznaczone = [w for w in dostepne if w in filtr[nazwa]]
        if len(odznaczone) >= len(dostepne):
            raise ValueError(f'{KOMUNIKAT_OSTATNIEJ_WARTOSCI} pola „{etykieta}" — '
                             f'bez niej pulpit pokazałby same zera')
        wynik[nazwa] = odznaczone
    obce = sorted(set(filtr) - set(POLA_WYKLUCZEN))
    if obce:
        raise ValueError(f"'{obce[0]}' — wykluczać można tylko po polach: "
                         f'{nazwy_pol_wykluczen()}')
    return wynik or None


def filtr_z_wykluczen(wykluczenia: Optional[Wykluczenia],
                      obecne: Dict[str, List[str]]) -> Optional[Filtr]:
    """Wykluczenia jako zwykły `Filtr`: zaznaczone wartości plus „brak wartości".

    Kolejność wartości idzie za danymi, żeby ten sam stan dawał zawsze ten
    sam napis w adresie wyjść do Eksploratora (`zapisz_filtr`).
    """
    if not wykluczenia:
        return None
    return {nazwa: [w for w in obecne[nazwa] if w not in odznaczone] + ['']
            for nazwa, odznaczone in wykluczenia.items()}
