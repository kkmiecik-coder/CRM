# -*- coding: utf-8 -*-
"""Kompozycja danych dashboardu Analizy sprzedażowej.

Jedno miejsce, w którym z agregatów powstaje jeden słownik dla jednego żądania.
Decyzja zamknięta w spec §D9 i §7: siedem agregatów w jednym połączeniu to
35 ms, a strumieniowanie per karta dołożyłoby endpointów za zero zysku.

ŻADNA LICZBA NIE JEST LICZONA W PRZEGLĄDARCE. Udziały procentowe, zmiany
okres-do-okresu, cena za m3 w wierszu i lumpowanie ogona do „Pozostałe"
powstają tutaj. Poprzednik liczył TTL m3, koszt kuriera netto i statystyki
wykończenia w JavaScripcie — to jeden z długów wypisanych w spec §11.
"""

import logging
from datetime import date, datetime, timedelta
from decimal import ROUND_FLOOR, Decimal
from typing import Dict, List, Optional, Sequence, Tuple

import pytz

from extensions import db
from modules.reports import analytics
from modules.reports.aggregates import (
    SEPARATOR_ZLOZONY, cena_netto_za_m3, dopasuj_wiersze, klucz_grupy, kolumny_wymiaru, kpi,
    nadplaty, naleznosci_wg_wieku, naleznosci_wg_wymiaru, wg_wymiaru,
)
from modules.reports.fields import (
    METR_SZESCIENNY, POLA, PROCENT, SZTUKI, ZLOTY, ZLOTY_ZA_M3, Porzadek,
    wymiary, wymiary_proste,
)
# PUSTA_WARTOSC mieszka w filters.py — ten sam napis widzi użytkownik w wierszu
# karty i w opisie kontrolki filtra, więc ma jedno źródło.
from modules.reports.filters import (
    KOMUNIKAT_OSTATNIEJ_WARTOSCI, POLA_WYKLUCZEN, PUSTA_WARTOSC, filtr_z_wykluczen,
    warunek_sprzedazy, warunki_pozycji, warunki_zamowienia, zapisz_filtr,
)
from modules.reports.models_sales import SalesOrder, SalesOrderItem
# Import w tę stronę jest bezpieczny: `uklad` importuje wyłącznie `fields`
# i celowo NIE importuje tego modułu (patrz docstring `uklad.py`).
from modules.reports.uklad import KATALOG, Instancja, wymiary_typu


def _domyslne_wymiary() -> Dict[str, str]:
    """Klucz karty -> pole rejestru, które pokazuje na start. WYLICZANE
    z katalogu, nie wpisane: do 23.09.2026 były to dwie listy tego samego
    (katalog powstał później), a dwie listy tego samego rozjeżdżają się zawsze.

    Tylko typy BEZ własnej listy wymiarów. Karty kubełkowe („Klienci według",
    „Należności według") mają na start PSEUDO-WYMIAR, który nie jest polem
    rejestru, i opisuje je `KARTY_KUBELKOWE` niżej — ta nazwa obiecuje pole
    rejestru i ma go dotrzymać. (Makieta karty miksu pokazuje „Gatunek ·
    technologia · klasa", stąd `konfiguracja` jako jej wymiar domyślny —
    wpisana w katalogu, nie tutaj.)

    Wymiar, który przestał być ważny (pole straciło wymiar=True), jest
    POMIJANY z ostrzeżeniem w logu, a nie rzucany wyjątkiem — ten słownik
    powstaje przy imporcie i wyjątek wywróciłby całą aplikację (przegląd
    gałęzi, M7). Rozjazd łapie test `test_domyslny_wymiar_typu_zwyklego_*`.
    """
    wynik: Dict[str, str] = {}
    for klucz, typ in KATALOG.items():
        if not typ.wymiarowy or typ.wymiary is not None:
            continue
        if typ.domyslny_wymiar not in wymiary_typu(klucz):
            # Ten sam logger, co pominięcia w `uklad.py` — jedno miejsce do
            # szukania śladów rozjazdu katalogu z rejestrem pól.
            logging.getLogger('reports.uklad').warning(
                'DOMYSLNE_WYMIARY: pomijam karte %s - wymiar %s nie jest juz '
                'wymiarem w rejestrze pol', klucz, typ.domyslny_wymiar)
            continue
        wynik[klucz] = typ.domyslny_wymiar
    return wynik


DOMYSLNE_WYMIARY: Dict[str, str] = _domyslne_wymiary()

# Ile wierszy mieści się na karcie ŁĄCZNIE, wliczając wiersz „Pozostałe (N)".
# Liczby wprost z makiety Main.dc.html — karta ma stałą wysokość w siatce,
# a karta opiekunów pokazuje tam cztery nazwiska plus wiersz zbiorczy, czyli
# pięć wierszy razem. Gdyby limit znaczył „wierszy przed zwinięciem ogona",
# każda karta z ogonem urosłaby o jeden rząd ponad makietę.
LIMITY_KART: Dict[str, int] = {
    'kanal': 4, 'opiekun': 5, 'mix': 6, 'wojewodztwo': 7,
    'wykonczenie': 3, 'dostawa': 3,
}

# Kanał „wystawione ręcznie w BaseLinkerze". Karta kanałów rozbija na segmenty
# WYŁĄCZNIE ten kanał — bez zawężenia pokazywałaby segmentację całej sprzedaży
# pod nagłówkiem „Wewnątrz kanału ręcznego", a zamówienia ze sklepu i z Allegro
# (bez `client_origin`) zdominowałyby ją wierszem „(brak)".
# WARTOŚĆ DO POTWIERDZENIA NA PRODUKCJI — patrz krok weryfikacji w tym zadaniu:
#   SELECT DISTINCT order_source FROM sales_orders;
KANAL_RECZNY: Tuple[str, ...] = ('personal',)

# Wymiar, po którym karta kanałów rozbija kanał ręczny na segmenty („Detal",
# „Stały B2B"...). Wpisany na sztywno, tak jak `WYMIAR_WNIOSKU_O_KANALE` niżej,
# więc oba przechodzą przez `_pole_na_sztywno_dziala` przed użyciem.
WYMIAR_ROZBICIA_KANALU = 'client_origin'


def _pole_na_sztywno_dziala(nazwa: str, blok: str) -> bool:
    """Czy pole wpisane w tym serwisie NA SZTYWNO jest wciąż wymiarem prostym.

    Wymiary kafelków przychodzą z układu i przechodzą walidację przy odczycie
    (`uklad.wymiary_typu`). Dwa bloki payloadu mają jednak pola wpisane tutaj:
    rozbicie kanału ręcznego (`client_origin`, zawężone filtrem po
    `order_source`) i wniosek „Największy kanał" (`order_source`). Gdy któreś
    z tych pól straci wymiar=True w `fields.py`, grupowanie albo filtr rzuca
    ValueError i każde `/api/analytics` z układem domyślnym kończyło się 500.

    Tak jak przy katalogu (poprawka M7): blok zwraca None, ostrzeżenie idzie
    do tego samego loggera `reports.uklad`, a reszta pulpitu się liczy.
    Sprawdzamy TĄ SAMĄ walidacją, której użyje zapytanie (`kolumny_wymiaru`
    dla grupowania, `wymiary_proste` dla filtra), więc nie ma drugiej reguły.
    """
    try:
        kolumny_wymiaru(nazwa)
        dziala = nazwa in wymiary_proste()
    except ValueError:
        dziala = False
    if not dziala:
        logging.getLogger('reports.uklad').warning(
            '%s: pomijam blok - pole %s nie jest juz wymiarem prostym w rejestrze '
            'pol (zmiana w fields.py?)', blok, nazwa)
    return dziala

# Kolory chipów segmentów. Bazowy to pomarańcz WoodPower z makiety, porównawczy
# to turkus z palety — para zwalidowana pod kątem daltonizmu (README makiet).
# Kolory SERII na wykresach idą za kolorem chipa, więc mają jedno źródło i jest
# nim serwer: inaczej chip i słupek mogłyby się rozjechać.
KOLOR_SEGMENTU_BAZA = '#ED6B24'
KOLOR_SEGMENTU_POROWNANIA = '#0F7D94'

# Napis chipa bazowego bez wykluczeń. Jedno źródło dla szablonu (pierwsza
# klatka) i payloadu (każde odświeżenie).
NAZWA_SEGMENTU_BAZY = 'Wszystkie zamówienia'

# Nazwy miesięcy bierzemy z analytics — jedno źródło dla dashboardu
# i Eksploratora (patrz komentarz przy ich deklaracji).
MIESIACE_SKROT = analytics.MIESIACE_SKROT
MIESIACE_MALE = analytics.MIESIACE_MALE

# Etykiety kubełków wieku w makiecie są krótsze niż te, które zwraca
# `naleznosci_wg_wieku`. Mapujemy je TUTAJ, a nie w JavaScripcie — inaczej
# powstałoby drugie źródło prawdy o nazwach kubełków.
ETYKIETY_WIEKU: Dict[str, str] = {
    '0-14 dni': '0–14 dni',
    '15-30 dni': '15–30',
    '31-60 dni': '31–60',
    '61-90 dni': '61–90',
    '>90 dni': '>90',
}

# Słownik „kod z BaseLinkera -> nazwa dla człowieka". Tłumaczymy TYLKO to, co
# widzi użytkownik: tekst źródłowy zostaje w kluczu `wartosc` i to on jedzie
# do filtra oraz do Eksploratora (spec §9: „Normalizujemy do wymiaru, tekst
# źródłowy zostaje"). Mapa siedzi na SERWERZE, tak samo jak ETYKIETY_WIEKU
# i z tego samego powodu — inaczej karta, Eksplorator i eksport CSV
# podpisałyby ten sam kanał na trzy sposoby.
#
# Kolumny logiczne są tu obowiązkowo: MySQL odda TINYINT 0/1, SQLite True/False,
# a użytkownik zobaczyłby w karcie wiersze podpisane „0" i „1".
ETYKIETY_WARTOSCI: Dict[str, Dict[object, str]] = {
    'order_source': {'shop': 'Sklep', 'personal': 'Ręczne w BL',
                     'allegro': 'Allegro', 'olx': 'OLX'},
    # UWAGA: w Pythonie `1 == True` i `0 == False`, więc klucze liczbowe
    # i logiczne to TEN SAM wpis — TINYINT z MySQL-a trafia w `True`/`False`.
    # Klucze '1'/'0' są tu dla wartości, która przyszła z ADRESU jako napis.
    'own_transport': {True: 'Tak', False: 'Nie', '1': 'Tak', '0': 'Nie'},
    'picked_up': {True: 'Odebrane', False: 'Nieodebrane',
                  '1': 'Odebrane', '0': 'Nieodebrane'},
}


# Jednostka czasu karty lejka. W `fields.py` jej NIE MA i nie ma jak być:
# tamten rejestr opisuje KOLUMNY bazy, a żadna kolumna nie trzyma liczby dni
# (`lead_time_days` ma „(dni)" w etykiecie, bo nie jest miarą i jednostki nie
# deklaruje). Mediana czasu wycena -> zamówienie jest liczona, nie czytana
# z kolumny, więc jej jednostka mieszka razem z resztą jednostek MIAR.
DZIEN = 'dni'


# JEDNOSTKI. Każda liczba na dashboardzie i w Eksploratorze ma jednostkę,
# i jest ona deklarowana TUTAJ, po stronie serwera — tak samo jak etykiety
# wartości wyżej i z tego samego powodu. Przeglądarka jednostki nie zgaduje
# ani nie wylicza: dostaje ją w payloadzie (klucz `jednostki`) albo ma ją już
# wypisaną w szablonie.
#
# Klucze to nazwy MIAR agregatów (`aggregates.kpi`, `wg_wymiaru`,
# `MIARY_PANELU`), nie nazwy pól rejestru — rejestr opisuje kolumny bazy,
# a tu chodzi o to, co widać na karcie. Spójność obu list pilnuje test
# (np. JEDNOSTKI_MIAR['netto'] == POLA['value_net'].jednostka).
JEDNOSTKI_MIAR: Dict[str, str] = {
    'netto': ZLOTY,
    'udzial': PROCENT,
    'objetosc': METR_SZESCIENNY,
    'zamowienia': SZTUKI,
    'srednie_zamowienie': ZLOTY,
    'cena_za_m3': ZLOTY_ZA_M3,
    'klienci': SZTUKI,
    'nowi_klienci': SZTUKI,
    'saldo': ZLOTY,
    'wycen': SZTUKI,
    'koszt_kuriera': ZLOTY,
    # Dwie miary karty lejka. Jednostki miar mieszkają tutaj, nie w szablonie
    # — tak samo jak pozostałe dwanaście wpisów wyżej.
    'wartosc_wyceny': ZLOTY,
    'czas_do_zamowienia': DZIEN,
    # Miara dymka mapy województw: ile z tych zamówień ma zlecenie produkcyjne.
    # Liczba zleceń, więc sztuki — ta sama jednostka co „zamowienia", bo obie
    # liczą zamówienia, tylko w innym zbiorze.
    'w_produkcji': SZTUKI,
    # SZTUKI PRODUKTÓW — miara „szt." przełącznika na kafelkach (24.09.2026):
    # suma ilości pozycji bez usług (`aggregates.sztuki_bez_uslug`). Jednostka
    # WPROST z pola rejestru, które sumujemy (`quantity`, „Ilość"), a nie ze
    # stałej obok — tak test „jednostki miar zgadzają się z rejestrem" nie ma
    # czego pilnować osobno: rozjazd jest niemożliwy z konstrukcji.
    'sztuki': POLA['quantity'].jednostka,
}

# Kolumna liczb karty ze słupkami: KTÓRĄ miarę pokazuje i jak ją podpisać.
# Z samego tytułu karty tego nie widać, np. karta „Klienci według: liczba
# zamówień" pokazuje kwotę, mimo że wiersze są podpisane liczbą zamówień
# i czyta się je jak liczbę klientów. Nagłówek kolumny bierze się WYŁĄCZNIE
# stąd, więc podpis nie ma jak rozjechać się z tym, co rysuje analiza.js.
#
# NIEZMIENNIK: dla każdej karty ze słupkami `miara` tutaj MUSI być tą samą
# wielkością, po której analiza.js skaluje słupek — a słupek skaluje się
# zawsze po netto (patrz rysujWiersze w analiza.js). Karty wojewodztwo i
# dostawa miały tu kiedyś 'objetosc': słupek niósł netto, ale wypisana liczba
# (opcja `jednaDziesiata` w JS) była objętością w m³ — dwie różne wielkości
# w jednym wierszu, mimo że obie karty nazywają się „Sprzedaż netto według"
# / „Dostawa według". Zmierzone na danych produkcyjnych: woj. mazowieckie
# miało netto 84 419,53 zł i objętość 4,8412 m³, a na ekranie stało „4,8" —
# słupek mówił „netto", liczba obok kłamała. Naprawione 22.09.2026.
KOLUMNY_KART: Dict[str, Tuple[str, str]] = {   # karta -> (miara, podpis)
    'kanal':          ('netto', 'Netto'),
    'kanal_rozbicie': ('netto', 'Wewnątrz kanału ręcznego'),
    'opiekun':        ('netto', 'Netto'),
    # Karta „Klienci według" to od partii E (punkt E2) KOŁO udziału w wartości:
    # kawałek = netto (kubełki: z całej historii, wymiar: za okres). Kolumna
    # kwoty pod kołem nazywa się więc „Netto" — jak na każdej karcie netto.
    'klienci':        ('netto', 'Netto'),
    'wojewodztwo':    ('netto', 'Netto'),
    'dostawa':        ('netto', 'Netto'),
    'naleznosci':     ('saldo', 'Saldo'),
    'wykonczenie':    ('netto', 'Netto'),
    # Lejek: słupek niesie UDZIAŁ stopnia w stopniu pierwszym, a wypisana
    # liczba to ten sam stopień w sztukach — dwa zapisy tej samej wielkości,
    # więc wiersz nie ma jak sam sobie przeczyć. Kolumna procentowa ma własny
    # podpis w nagłówku (jednostki['udzial']), obok tego.
    'lejek':          ('wycen', 'Wyceny'),
}


def _naglowek(miara: str, podpis: str) -> Dict[str, str]:
    return {'podpis': podpis, 'jednostka': JEDNOSTKI_MIAR[miara], 'miara': miara}


def naglowki_kolumn_kart() -> Dict[str, Dict[str, str]]:
    """Podpis i jednostka kolumny liczb, gotowe do wstawienia w szablon."""
    return {klucz: _naglowek(miara, podpis)
            for klucz, (miara, podpis) in KOLUMNY_KART.items()}


# --- KARTY KUBEŁKOWE: „Klienci według" i „Należności według" -----------------
#
# Obie karty kubełkują po czymś, co NIE JEST kolumną bazy (liczba zamówień
# klienta, wiek zamówienia), więc ich selektor wymiaru miał dotąd jedną opcję
# i atrybut `disabled`. Wyglądał dokładnie jak siedem działających selektorów
# obok i nie dawał się otworzyć — zgłoszenie użytkownika 23.09.2026.
#
# Naprawa polega na daniu im PRAWDZIWYCH wymiarów, a nie na schowaniu
# kontrolki: użytkownik planuje układ, w którym ta sama karta występuje kilka
# razy z różnymi wymiarami, więc musi umieć wymiar zmieniać.

# Wartości selektora, które nie są polami rejestru — tak samo jak BEZ_PODZIALU
# na karcie lejka i z tego samego powodu: rejestr opisuje KOLUMNY, a tu chodzi
# o kubełkowanie liczone w locie, które własnej kolumny nie ma.
LICZBA_ZAMOWIEN = 'liczba_zamowien'
WIEK_ZAMOWIENIA = 'wiek_zamowienia'

# Wymiary karty KLIENTÓW. To NAZWY z rejestru pól — etykiety biorą się stamtąd,
# więc „Opiekun" znaczy na tej karcie to samo, co na każdej innej. Przepuszczamy
# je przez `wymiary_proste()`, więc nazwa, która z rejestru wypadła, po prostu
# znika z listy zamiast rozsypywać zapytanie (ten sam wzorzec, co
# `analytics.WYMIARY_LEJKA`).
#
# Wybrane są te, które opisują KLIENTA: skąd przyszedł (`client_origin`), kto
# go prowadzi (`caretaker`), którym kanałem kupuje (`order_source`), gdzie
# mieszka (`delivery_state`). Świadomie NIE MA tu gatunku, klasy ani grubości
# (opisują deskę, nie klienta), formy płatności, statusu ani sposobu odbioru
# (opisują jedno zamówienie, nie klienta) ani daty (to oś czasu, a nie przekrój
# — z dokładnością do dnia dałaby setki wierszy, z których widać by było cztery).
WYMIARY_KLIENTOW: Tuple[str, ...] = (
    'client_origin', 'caretaker', 'order_source', 'delivery_state')

# Wymiary karty NALEŻNOŚCI. Saldo żyje na ZAMÓWIENIU, więc wolno grupować
# wyłącznie po kolumnach zamówienia — `naleznosci_wg_wymiaru` odrzuca resztę
# wyjątkiem, żeby nie podać należności zwielokrotnionych przez liczbę pozycji.
# Pytania, na które odpowiadają: komu wisi najwięcej (`caretaker`), którym
# kanałem to przyszło (`order_source`), w jakim stanie te zamówienia stoją
# (`current_status`) i jaką formą płatności miały być opłacone
# (`payment_method`).
WYMIARY_NALEZNOSCI: Tuple[str, ...] = (
    'caretaker', 'order_source', 'current_status', 'payment_method')

# Opis obu kart w jednym miejscu: wartość domyślna selektora wraz z jej
# etykietą, lista wymiarów, miara i podpis kolumny PO przełączeniu na wymiar
# oraz liczba wierszy, która mieści się na karcie.
#
# KARTA KLIENTÓW (partia E, punkt E2). Do 23.09.2026 przekrój po wymiarze
# pokazywał LICZBĘ KLIENTÓW, żeby nie powtarzać karty „Sprzedaż netto według"
# obok. Prezes chce koła z udziałem % i kwotą — a koło jest czystym podziałem
# całości tylko wtedy, gdy każdy element należy do jednego kawałka. Zamówienie
# należy do jednego opiekuna, kanału czy województwa; klient — nie zawsze
# (ten sam klient kupuje w dwóch kanałach). Kawałek to więc NETTO: % sumuje
# się do 100, złotówki do netto okresu. Miara jest ta sama w obu trybach, więc
# podpis kolumny też. Karta należności: saldo w obu trybach, jak dotąd.
KARTY_KUBELKOWE: Dict[str, Dict[str, object]] = {
    'klienci': {
        'domyslny': LICZBA_ZAMOWIEN, 'etykieta_domyslnego': 'Liczba zamówień',
        'wymiary': WYMIARY_KLIENTOW, 'miara': 'netto', 'podpis': 'Netto',
        'limit': 4,
    },
    'naleznosci': {
        'domyslny': WIEK_ZAMOWIENIA, 'etykieta_domyslnego': 'Wiek zamówienia',
        'wymiary': WYMIARY_NALEZNOSCI, 'miara': 'saldo', 'podpis': 'Saldo',
        'limit': 5,
    },
}

# Zdania o zasięgu liczb — po jednym na każdy stan karty. Kubełki liczą się
# z całej historii (klienci) albo na dziś (należności), a przekrój po wymiarze
# — za wybrany okres, jak każda inna karta. Adnotacja MUSI to rozróżniać:
# pokazana bez zmian przy przekroju okresowym kłamałaby, a schowana zostawiłaby
# kubełki bez ostrzeżenia, którego dorobiły się z konkretnego powodu.
_RESZTA_UWAGI_KOLA_KLIENTOW = ('Konwersja i kubełki (wybór powyżej) liczą się '
                               'z całej historii, a segment porównawczy tej karty '
                               'nie dotyczy.')

_UWAGI_KART_KUBELKOWYCH: Dict[str, Dict[bool, str]] = {
    'klienci': {
        True: ('Uwaga: kubełki i konwersja liczą się z całej historii klientów '
               '— nie za wybrany okres ani segment.'),
        False: ('Uwaga: kawałki koła to netto zamówień złożonych w wybranym okresie. '
                + _RESZTA_UWAGI_KOLA_KLIENTOW),
    },
    'naleznosci': {
        True: ('Uwaga: należności liczą się na dziś — nie za wybrany okres '
               'ani segment.'),
        False: ('Uwaga: wiersze liczą saldo zamówień z wybranego okresu. Kubełki '
                'wieku (wybór powyżej) liczą je na dziś, z całej historii, '
                'a segment porównawczy tej karty nie dotyczy.'),
    },
}

# Te same zdania dla TRYBU „szt." przełącznika (24.09.2026) — tylko karta
# klientów, bo tylko ona z kart kubełkowych ma przełącznik. Koło na wymiarze
# pokazuje wtedy sztuki, a zdanie „kawałki koła to netto" stało pod nim bez
# zmian (weryfikacja 24.09.2026, WAŻNE 2) — ta sama klasa błędu, przez którą
# tytuł „Sprzedaż netto według:" ma wariant „Sprzedaż według:". Zdanie
# o kubełkach miary nie nazywa, więc jest to samo w obu trybach. Przeglądarka
# wybiera wariant nazwą klucza miary (POLA_MIARY w analiza.js), jak udział
# i środek koła — tekstu nie składa.
_UWAGI_SZTUK_KART_KUBELKOWYCH: Dict[str, Dict[bool, str]] = {
    'klienci': {
        True: _UWAGI_KART_KUBELKOWYCH['klienci'][True],
        False: ('Uwaga: kawałki koła to sztuki produktów (bez usług) z zamówień '
                'złożonych w wybranym okresie. ' + _RESZTA_UWAGI_KOLA_KLIENTOW),
    },
}

# DOPISEK przy aktywnych wykluczeniach (partia E, punkty E4 i E8) — tylko tam,
# gdzie wykluczenie NIE MOŻE zadziałać. Pól nie wymieniamy z nazwy: stoją
# nad pulpitem, a lista wypisana z pamięci rozjechałaby się z
# `filters.POLA_WYKLUCZEN` przy pierwszej nowej grupie (E8 dopisało czwartą).
# Kubełki klientów i konwersja lead → klient
# liczą się z denormalizacji z całej historii (`lifetime_net`,
# `orders_count`), w której pozycji już nie ma. Należności dopisku nie mają:
# ich saldo liczy się z zamówień, które mają choć jedną niewykluczoną pozycję
# (EXISTS), więc wykluczenia działają tam jak wszędzie.
_DOPISKI_WYKLUCZEN: Dict[str, Dict[bool, str]] = {
    'klienci': {
        True: ' Wykluczeń z pól u góry pulpitu też nie uwzględniają.',
        False: (' Wykluczenia z pól u góry pulpitu działają na kawałki koła '
                'i nowych klientów, ale nie na konwersję ani kubełki.'),
    },
}


def wymiar_wyjscia_karty_kubelkowej(klucz: str, wymiar: str) -> str:
    """Wymiar, po którym stopka karty kubełkowej prowadzi do Eksploratora.

    Karta na wymiarze z rejestru — po TYM wymiarze, jak każda inna karta
    (partia E8, punkt 4g: stopka „Klienci według" szła zawsze po pochodzeniu
    klienta, choć karta stała na opiekunie). Kubełki to pseudo-wymiar spoza
    rejestru, którego Eksplorator nie zna — wtedy pierwszy wymiar karty
    z `KARTY_KUBELKOWE`, a nie napis wpisany w szablon.
    """
    opis = KARTY_KUBELKOWE[klucz]
    return wymiar if wymiar in opis['wymiary'] else opis['wymiary'][0]


def wymiary_karty_kubelkowej(klucz: str) -> List[Dict[str, str]]:
    """Opcje selektora karty kubełkowej: pseudo-wymiar domyślny, potem rejestr."""
    opis = KARTY_KUBELKOWE[klucz]
    proste = set(wymiary_proste())
    pozycje = [{'nazwa': opis['domyslny'], 'etykieta': opis['etykieta_domyslnego']}]
    pozycje.extend({'nazwa': nazwa, 'etykieta': POLA[nazwa].etykieta}
                   for nazwa in opis['wymiary'] if nazwa in proste)
    return pozycje


def naglowek_karty_kubelkowej(klucz: str, wymiar: str) -> Dict[str, str]:
    """Podpis i jednostka kolumny liczb dla BIEŻĄCEGO wymiaru karty."""
    opis = KARTY_KUBELKOWE[klucz]
    if wymiar == opis['domyslny']:
        return _naglowek(*KOLUMNY_KART[klucz])
    return _naglowek(opis['miara'], opis['podpis'])


# --- PRZEŁĄCZNIK MIARY NA KAFELKU: „zł" / „szt." / „zł + szt." --------------
#
# Decyzja użytkownika z 24.09.2026: „do wykresów/statystyk pokazywanie sztuk.
# Tylko nie zrobiłbym tego jako statystyki zaraz obok, tylko np. w prawym
# górnym rogu przełącznik". Przełącznik jest NA KAŻDYM kafelku z wykresem albo
# słupkami osobno, nie jeden na pulpit.
#
# TRZECIA OPCJA TO „zł + szt.", NIE „porównanie". Na pulpicie „porównanie"
# znaczy już segment porównawczy („Dodaj porównanie") — ta sama etykieta ma
# wszędzie znaczyć to samo.
#
# STAN PRZEŁĄCZNIKA to stan WIDOKU: nie jedzie do adresu ani do zapisanego
# układu (`uklad._DOZWOLONE_KLUCZE` odrzuca pole „tryb"). Serwer niczego
# o bieżącym trybie nie wie — payload niesie OBIE miary dla każdego kafelka,
# który ma przełącznik, więc zmiana trybu nie wysyła żądania.
#
# GDZIE LEŻĄ SZTUKI W PAYLOADZIE (obok dotychczasowych kluczy złotówek):
#   kpi.sztuki, kpi.zmiana.sztuki, trend.biezacy[].sztuki,
#   trend.poprzedni[].sztuki — kafelek KPI;
#   karty[k].wiersze[] / .ogon[]: sztuki, udzial_sztuk — listy słupków
#   i pierścień wykończeń (+ karty[k].najwiekszy_sztuk przy pierścieniu);
#   kanal_rozbicie.wiersze[] / .ogon[]: sztuki, udzial_sztuk;
#   karty[klienci:…]: wiersze[]/ogon[] sztuki, udzial_sztuk (do stu),
#   najwiekszy_sztuk, kubelki[].sztuki, uwaga_sztuk (dopisek pod kołem);
#   karty[wojewodztwo:delivery_state].mapa: maks_sztuk, dymek_sztuk,
#   obszary[].sztuki, obszary[].poziom_sztuk, poza_mapa[].sztuki;
#   porownanie: kpi.sztuki, trend[].sztuki, karty[k][].sztuki,
#   ogony[k][].sztuki, kanal_rozbicie[].sztuki, kanal_rozbicie_ogon[].sztuki,
#   mapa.obszary[].sztuki, mapa.poza_mapa[].sztuki.
TRYB_ZL = 'zl'
TRYB_SZT = 'szt'
TRYB_OBA = 'zl_szt'

# Miary, z których rysuje się tryb — NAZWY MIAR z `JEDNOSTKI_MIAR`
# i `ETYKIETY_MIAR`, więc jednostka i podpis każdej z nich mają jedno źródło.
# W trybie „zł + szt." kolejność jest znacząca: PIERWSZA miara to słupki
# (lewa oś wykresu czasowego, długość słupka na liście kategorii), DRUGA —
# krzywa na prawej osi wykresu czasowego albo druga kolumna liczb na liście.
MIARY_TRYBOW: Dict[str, Tuple[str, ...]] = {
    TRYB_ZL: ('netto',),
    TRYB_SZT: ('sztuki',),
    TRYB_OBA: ('sztuki', 'netto'),
}

# Napisy opcji składamy z JEDNOSTEK, a nie wpisujemy obok nich: „zł" na
# przełączniku ma być tym samym „zł", co w nagłówku kolumny kafelka.
ETYKIETY_TRYBOW: Dict[str, str] = {
    TRYB_ZL: JEDNOSTKI_MIAR['netto'],
    TRYB_SZT: JEDNOSTKI_MIAR['sztuki'],
    TRYB_OBA: f"{JEDNOSTKI_MIAR['netto']} + {JEDNOSTKI_MIAR['sztuki']}",
}

_TRZY_TRYBY = (TRYB_ZL, TRYB_SZT, TRYB_OBA)
# Koło i kartogram pokazują JEDNĄ miarę naraz — kawałek koła nie ma jak być
# jednocześnie złotówkami i sztukami, a kolor obszaru mapy jedną skalą.
_DWA_TRYBY = (TRYB_ZL, TRYB_SZT)

# Decyzja dla KAŻDEGO typu z katalogu (test pilnuje kompletności). None =
# kafelek bez przełącznika — nie wyłączony, po prostu go nie ma:
# - „Statystyki" to trzy zdania, nie wykres;
# - „Objętość i cena za m³" to tabela dwóch osobnych miar (m³ i zł/m³);
# - „Należności" liczą saldo, którego nie da się wyrazić w sztukach;
# - lejek liczy WYCENY, a wycena nie ma sztuk produktów w sensie sprzedaży.
TRYBY_TYPOW: Dict[str, Optional[Tuple[str, ...]]] = {
    'kpi': _TRZY_TRYBY,
    'wnioski': None,
    'kanal': _TRZY_TRYBY,
    'opiekun': _TRZY_TRYBY,
    'mix': None,
    'klienci': _DWA_TRYBY,
    'wojewodztwo': _TRZY_TRYBY,     # na wymiarze mapy — dwa, patrz niżej
    'naleznosci': None,
    'wykonczenie': _DWA_TRYBY,
    'dostawa': _TRZY_TRYBY,
    'lejek': None,
}


def opcje_przelacznika(typ: str, wymiar: Optional[str]) -> Optional[Dict[str, object]]:
    """Opcje przełącznika kafelka albo None, gdy kafelek go nie ma.

    JEDNO źródło dla payloadu (`przelaczniki`) i dla szablonu kafelka
    (`routers_analiza._kontekst_kafelkow`), więc przełącznik narysowany przez
    serwer i dane, którymi przeglądarka go obsługuje, nie mają jak się
    rozjechać.

    Zależy od WYMIARU, nie tylko od typu: karta województw na wymiarze
    „Województwo" jest kartogramem (jedna miara naraz), a na każdym innym —
    listą słupków (trzy tryby). Po zmianie wymiaru kafelek przychodzi
    z serwera od nowa, razem ze swoimi opcjami.

    Typ spoza `TRYBY_TYPOW` dostaje None (brak przełącznika), a nie wyjątek:
    wyjątek tutaj wywróciłby cały pulpit (lekcja M7). Kompletność mapy
    pilnuje test.
    """
    tryby = TRYBY_TYPOW.get(typ)
    if tryby is None:
        return None
    if typ == 'wojewodztwo' and wymiar == WYMIAR_MAPY:
        tryby = _DWA_TRYBY
    return {
        'domyslny': TRYB_ZL,
        'opcje': [{'tryb': tryb, 'etykieta': ETYKIETY_TRYBOW[tryb],
                   'miary': list(MIARY_TRYBOW[tryb])} for tryb in tryby],
    }


# ZEGAR. Kontener i serwer produkcyjny chodzą na UTC, a użytkownik siedzi
# w Polsce. Zegar systemowy bez przeliczenia pokazuje mu „Stan na" młodszy
# o 1–2 h i dashboard wygląda na nieodświeżony (zmierzone: 02:07 w kontenerze
# przy 04:07 na hoście). Ta sama konwencja, co `modules/production/models.py`.
STREFA_LOKALNA = pytz.timezone('Europe/Warsaw')


def teraz_lokalnie() -> datetime:
    """Bieżąca chwila w strefie Europe/Warsaw, bez znacznika strefy."""
    return datetime.now(STREFA_LOKALNA).replace(tzinfo=None)


def dzis_lokalnie() -> date:
    """Dzisiejsza data w Polsce.

    Między północą a drugą w nocy czasu polskiego UTC jest jeszcze w dniu
    poprzednim, więc preset „bieżący miesiąc" wyliczony w przeglądarce nie
    zgadzałby się z serwerem i podpis zakresu spadałby na „zakres własny".
    Dotyczy też dnia, na który liczą się należności.
    """
    return teraz_lokalnie().date()


def poprzedni_okres(od: date, do: date) -> Tuple[date, date]:
    """Okres tej samej długości, kończący się dzień przed `od`."""
    dlugosc = (do - od).days + 1
    do_poprz = od - timedelta(days=1)
    return do_poprz - timedelta(days=dlugosc - 1), do_poprz


def zmiana_procentowa(teraz, wczesniej) -> Optional[Decimal]:
    """Zmiana w procentach, albo None gdy nie ma od czego liczyć.

    Wzrost z zera nie jest „plus nieskończoność" ani „plus 100%" — jest
    nieokreślony. Karta pokazuje wtedy kreskę zamiast strzałki.
    """
    baza = Decimal(str(wczesniej or 0))
    if baza == 0:
        return None
    return ((Decimal(str(teraz or 0)) - baza) * 100 / baza).quantize(Decimal('0.1'))


def _koniec_miesiaca(rok: int, miesiac: int) -> date:
    if miesiac == 12:
        return date(rok, 12, 31)
    return date(rok, miesiac + 1, 1) - timedelta(days=1)


def _etykieta_wartosci(nazwa: str, wartosc) -> str:
    """Etykieta wiersza karty. Obsługuje trzy przypadki naraz.

    1. Wymiar złożony — `wartosc` jest krotką składowych, sklejamy je
       separatorem z `aggregates.SEPARATOR_ZLOZONY`.
    2. Wymiar ze słownikiem — bierzemy nazwę po polsku z ETYKIETY_WARTOSCI.
    3. Wartość nieznana — zostaje DOSŁOWNIE. Mapa etykiet nie jest filtrem:
       kanał, którego nikt nie przewidział, ma się pokazać taki, jaki jest,
       a nie zniknąć.
    """
    if isinstance(wartosc, tuple):
        return SEPARATOR_ZLOZONY.join(
            _etykieta_wartosci(nazwa, skladowa) for skladowa in wartosc)
    if wartosc is None or str(wartosc).strip() == '':
        return PUSTA_WARTOSC
    slownik = ETYKIETY_WARTOSCI.get(nazwa)
    if slownik:
        if wartosc in slownik:
            return slownik[wartosc]
        # 4. Wartość z ADRESU jest ZAWSZE napisem, a mapa dla `own_transport`
        #    i `picked_up` jest kluczowana boolem. Bez tego kroku użytkownik
        #    zaznacza w popoverze „Nie" (lista wartości mapuje poprawnie),
        #    a chip segmentu pokazuje mu „Transport własny: False".
        tekst = str(wartosc).strip().lower()
        for klucz, etykieta in slownik.items():
            if str(klucz).strip().lower() == tekst:
                return etykieta
    return str(wartosc)


# Ile wartości w skrócie opisu segmentu, zanim przejdziemy na „+N". Ta sama
# liczba co w `filters.opis_filtru` (tam prywatna `_ILE_W_OPISIE`) — trzymamy
# jawnie tutaj, żeby nie sięgać po nazwę z podkreśleniem z cudzego modułu.
_ILE_W_OPISIE_SEGMENTU = 2


def opis_z_etykietami(filtr: Optional[Dict[str, List[str]]]) -> str:
    """Opis warunku z etykietami wartości po polsku — dla KAŻDEJ kontrolki,
    która go pokazuje użytkownikowi: chipa segmentu na dashboardzie i kontrolki
    „Filtr" w Eksploratorze.

    `opis_filtru` z `filters.py` zostaje OGÓLNĄ warstwą niżej i pokazuje
    wartość surową — test regresyjny Zadania 2 tego pilnuje („Kanał sprzedaży:
    shop, allegro"). Użyty wprost w interfejsie dawał dwa języki na raz: chip
    na dashboardzie mówił „Kanał sprzedaży: Sklep, Ręczne w BL", a kontrolka
    Eksploratora dla tego samego filtra „Kanał sprzedaży: shop, personal".
    """
    if not filtr:
        return 'brak'
    czesci = []
    for nazwa in sorted(filtr):
        wartosci = [_etykieta_wartosci(nazwa, w) for w in filtr[nazwa]]
        widoczne = ', '.join(wartosci[:_ILE_W_OPISIE_SEGMENTU])
        if len(wartosci) > _ILE_W_OPISIE_SEGMENTU:
            widoczne += f' +{len(wartosci) - _ILE_W_OPISIE_SEGMENTU}'
        czesci.append(f'{POLA[nazwa].etykieta}: {widoczne}')
    return ' · '.join(czesci)


def _udzial(czesc, suma) -> Decimal:
    """Udział w procentach z dokładnością 0,1 — reguła wierszy kart ze słupkami."""
    if not suma:
        return Decimal('0')
    return (Decimal(czesc) * 100 / Decimal(suma)).quantize(Decimal('0.1'))


def _wiersz(wartosc, etykieta, netto, objetosc, zamowienia, suma,
            zbiorczy: bool = False, sztuki: int = 0,
            suma_sztuk: int = 0) -> Dict[str, object]:
    """Jeden wiersz karty.

    `zbiorczy` odróżnia wiersz „Pozostałe (N)" od wiersza prawdziwej wartości
    pustej. Oba mają `wartosc = None` i bez tego znacznika nie da się ich
    rozróżnić — a Zadanie 10 musi, żeby wyrównać wiersze segmentu
    porównawczego do wierszy karty bazowej.

    `sztuki` i `udzial_sztuk` (24.09.2026) niosą tryb „szt." przełącznika.
    Udział sztuk liczy się TĄ SAMĄ regułą co udział netto — ta sama karta,
    ten sam sposób zaokrąglenia, tylko inna miara.
    """
    return {
        'wartosc': wartosc,
        'etykieta': etykieta,
        'netto': netto,
        'objetosc': objetosc,
        'sztuki': sztuki,
        'zamowienia': zamowienia,
        'udzial': _udzial(netto, suma),
        'udzial_sztuk': _udzial(sztuki, suma_sztuk),
        'cena_za_m3': (netto / objetosc).quantize(Decimal('0.01')) if objetosc else None,
        'zbiorczy': zbiorczy,
    }


def _wymiar_z_pamieci(nazwa: str, od: date, do: date, filtr, pamiec):
    """`wg_wymiaru` z pamięcią na czas JEDNEGO żądania.

    Po co: przy własnym układzie ten sam wymiar potrafi wystąpić na kilku
    kafelkach naraz („Sprzedaż netto wg gatunku" i „Objętość i cena wg
    gatunku"), a zapytanie jest za każdym razem identyczne. Zmierzone na kopii
    produkcji: 20 kafelków na 4 różnych wymiarach to 305,9 ms bez pamięci
    i 69,3 ms z pamięcią.

    Pamięć jest przekazywana JAWNIE, nigdy modułowa. Modułowa byłaby wspólna
    dla wszystkich użytkowników, wszystkich okresów i wszystkich segmentów —
    dokładnie ten błąd, którym cache cennika per worker kazał czekać godzinę
    na zmianę ceny (naprawiane 05.08.2026).

    Klucz zawiera FILTR. Bez niego karta segmentu porównawczego dostałaby
    wyniki całego okresu i wykres pokazałby dwie identyczne serie.

    NIEZMIENNIK: nikt nie mutuje zwróconej listy ani jej słowników.
    `_wiersze_wymiaru` ją kroi (co tworzy nowe listy), `_karta_porownania`
    i `_najlepsze_srednie` tylko czytają. Gdyby ktoś zaczął mutować, drugi
    kafelek o tym samym wymiarze dostałby cudze poprawki.
    """
    if pamiec is None:
        return wg_wymiaru(nazwa, od, do, filtr=filtr)
    klucz = (nazwa, od, do, zapisz_filtr(filtr))
    if klucz not in pamiec:
        pamiec[klucz] = wg_wymiaru(nazwa, od, do, filtr=filtr)
    return pamiec[klucz]


def _wartosc_z_pamieci(klucz: tuple, funkcja, pamiec):
    """Wynik bezargumentowego wywołania `funkcja()` z tą samą pamięcią co
    `_wymiar_z_pamieci`, pod WŁASNYM kluczem.

    Po co: karta kubełkowa („Klienci według", „Należności według") postawiona
    kilka razy na pulpicie z różnymi wymiarami woła `klienci_wg_liczby_zamowien`,
    `konwersja_lead_klient`, `nowi_klienci` (po stronie należności analogicznie
    `naleznosci_wg_wieku`, `ostrzezenie_salda`, `nadplaty`) raz na INSTANCJĘ,
    choć żadna z tych sześciu funkcji nie zależy od wymiaru — tylko ewentualnie
    od okresu albo `na_dzien`. Przy pięciu kartach „Klienci" to była piąta
    część zbędnych zapytań.

    Klucz MUSI obejmować wszystkie argumenty, z którymi `funkcja` jest wołana
    w danym miejscu (patrz wywołania w `_karta_kubelkowa`) — inaczej żądanie
    z innym okresem albo `na_dzien` dostałoby cudzy wynik z pamięci.

    NIEZMIENNIK, ten sam co w `_wymiar_z_pamieci`: nikt nie mutuje zwróconej
    wartości. Kto chce ją zmienić (np. `_karta_kubelkowa` przy karcie klientów
    przypisuje wynik wprost do `blok['kubelki']`), kopiuje najpierw.
    """
    if pamiec is None:
        return funkcja()
    if klucz not in pamiec:
        pamiec[klucz] = funkcja()
    return pamiec[klucz]


def _wiersze_wymiaru(nazwa: str, od: date, do: date, limit: int,
                     filtr=None, pamiec=None
                     ) -> Tuple[List[Dict[str, object]], List[Dict[str, object]]]:
    """Wiersze jednej karty: górka, wiersz zbiorczy — i OSOBNO rozpisany ogon.

    `limit` to liczba wierszy ŁĄCZNIE z wierszem zbiorczym. Karta ma w siatce
    stałą wysokość, więc „5 wierszy plus ewentualnie szósty" rozjechałoby rząd
    wobec makiety.

    Zwracamy PARĘ: wiersze widoczne od razu i ogon rozpisany na pojedyncze
    wiersze. Ogon jedzie w tej samej odpowiedzi, gotowy — kliknięcie w „Pozostałe
    (N)" tylko go pokazuje, bez drugiego żądania i bez liczenia czegokolwiek
    w przeglądarce (spec §6.1). Jest OSOBNYM kluczem, a nie dopiskiem do
    `wiersze`, bo wszystko, co czyta `wiersze`, ma widzieć dokładnie to, co
    widać na karcie: pierścień wykończeń rysowałby z ogona kilkanaście
    dodatkowych plasterków, a wniosek o największym kanale wskazywałby wiersz,
    którego na ekranie nie ma.
    """
    surowe = _wymiar_z_pamieci(nazwa, od, do, filtr, pamiec)
    suma = sum((w['netto'] for w in surowe), Decimal('0'))
    suma_sztuk = sum(w['sztuki'] for w in surowe)

    # Górka i ogon idą za ZŁOTÓWKAMI (kolejność `wg_wymiaru`) w każdym trybie
    # przełącznika: „szt." pokazuje te same encje w tych samych miejscach,
    # a nie przetasowaną listę — tak samo jak kolor kawałka koła nie zmienia
    # się przy przełączeniu miary.
    if len(surowe) > limit:
        glowa, ogon = surowe[:limit - 1], surowe[limit - 1:]
    else:
        glowa, ogon = surowe, []

    def na_wiersz(w):
        return _wiersz(w['wartosc'], _etykieta_wartosci(nazwa, w['wartosc']),
                       w['netto'], w['objetosc'], w['zamowienia'], suma,
                       sztuki=w['sztuki'], suma_sztuk=suma_sztuk)

    wiersze = [na_wiersz(w) for w in glowa]

    if ogon:
        wiersze.append(_wiersz(
            None, f'Pozostałe ({len(ogon)})',
            sum((w['netto'] for w in ogon), Decimal('0')),
            sum((w['objetosc'] for w in ogon), Decimal('0')),
            sum(w['zamowienia'] for w in ogon),
            suma,
            zbiorczy=True,
            sztuki=sum(w['sztuki'] for w in ogon),
            suma_sztuk=suma_sztuk,
        ))
    return wiersze, [na_wiersz(w) for w in ogon]


def _karta(nazwa: str, od: date, do: date, limit: int, filtr=None,
           pamiec=None) -> Dict[str, object]:
    wiersze, ogon = _wiersze_wymiaru(nazwa, od, do, limit, filtr=filtr, pamiec=pamiec)
    return {
        'wymiar': nazwa,
        'etykieta': POLA[nazwa].etykieta,
        'wiersze': wiersze,
        # Rozpisany ogon wiersza „Pozostałe (N)". Pusty, gdy karta mieści się
        # w limicie — wtedy nie ma czego rozwijać.
        'ogon': ogon,
    }


def _wiersze_z_ogonem(surowe: List[Dict[str, object]], limit: int
                      ) -> Tuple[List[Dict[str, object]], List[Dict[str, object]]]:
    """Górka, wiersz zbiorczy i rozpisany ogon — dla kart o JEDNEJ liczbie.

    Ta sama reguła, co w `_wiersze_wymiaru`: `limit` liczy wiersze ŁĄCZNIE
    z „Pozostałe (N)", a ogon jedzie gotowy w tej samej odpowiedzi. Osobna
    funkcja, bo wiersze kart kubełkowych niosą jedną liczbę (`liczba`),
    a nie komplet netto/objętość/zamówienia.
    """
    if len(surowe) > limit:
        glowa, ogon = surowe[:limit - 1], surowe[limit - 1:]
    else:
        glowa, ogon = surowe, []

    wiersze = [dict(w, zbiorczy=False) for w in glowa]
    if ogon:
        wiersze.append({
            'wartosc': None, 'etykieta': f'Pozostałe ({len(ogon)})',
            'liczba': sum(w['liczba'] for w in ogon), 'zbiorczy': True,
        })
    return wiersze, [dict(w, zbiorczy=False) for w in ogon]


def _udzialy_do_stu(wartosci: List[Decimal], cel: Decimal = Decimal('100.0')
                    ) -> List[Decimal]:
    """Udziały z dokładnością 0,1 sumujące się DOKŁADNIE do `cel`.

    Metoda największej reszty: każdy udział zaokrąglamy w dół do dziesiątej,
    a brakujące dziesiąte części rozdajemy kawałkom z największą resztą (przy
    remisie — wcześniejszemu). Zaokrąglone osobno trzy równe kawałki dają
    33,3 × 3 = 99,9, a legenda pod kołem, której procenty nie sumują się do
    stu, czyta się jak błąd.

    `cel` inny niż sto służy ogonowi „Pozostałe (N)": rozpisane wiersze ogona
    sumują się do udziału wiersza zbiorczego, a nie do stu.
    """
    if not wartosci:
        return []
    suma = sum(wartosci, Decimal('0'))
    if not suma:
        return [Decimal('0')] * len(wartosci)
    jednostki = int((Decimal(cel) * 10).to_integral_value())
    dokladne = [Decimal(w) * jednostki / suma for w in wartosci]
    podlogi = [int(d.to_integral_value(rounding=ROUND_FLOOR)) for d in dokladne]
    brak = jednostki - sum(podlogi)
    kolejnosc = sorted(range(len(wartosci)),
                       key=lambda i: (-(dokladne[i] - podlogi[i]), i))
    for i in kolejnosc[:max(0, brak)]:
        podlogi[i] += 1
    return [Decimal(p) / 10 for p in podlogi]


def _udzialy_kola_do_stu(wiersze: List[Dict[str, object]],
                         ogon: List[Dict[str, object]]) -> None:
    """Udziały kawałków KOŁA (netto i sztuki) sumujące się dokładnie do 100,0.

    JEDNA reguła dla obu kół pulpitu — pierścienia wykończeń i koła klientów
    (weryfikacja 24.09.2026: na pierścieniu udziały sztuk zaokrąglane osobno
    dawały 99,9–100,1, a legenda koła, której procenty nie sumują się do
    stu, czyta się jak błąd). Widoczne kawałki sumują się do stu, a rozpisany
    ogon — do udziału wiersza „Pozostałe (N)". Zmienia wiersze w miejscu.
    """
    for miara, pole_udzialu in (('netto', 'udzial'), ('sztuki', 'udzial_sztuk')):
        for wiersz, udzial in zip(wiersze, _udzialy_do_stu(
                [Decimal(w.get(miara) or 0) for w in wiersze])):
            wiersz[pole_udzialu] = udzial
        if ogon and wiersze and wiersze[-1].get('zbiorczy'):
            for wiersz, udzial in zip(ogon, _udzialy_do_stu(
                    [Decimal(w.get(miara) or 0) for w in ogon],
                    cel=wiersze[-1][pole_udzialu])):
                wiersz[pole_udzialu] = udzial


def _srodek_kola(wiersze: List[Dict[str, object]], miara: str = 'netto',
                 udzial: str = 'udzial') -> Optional[Dict[str, object]]:
    """Środek pierścienia: największy NAZWANY kawałek z udziałem — albo None.

    JEDNA reguła dla obu kół pulpitu (karta wykończeń i koło klientów,
    weryfikacja partii E, Z5). Wiersz „Pozostałe (N)" nie jest wartością
    wymiaru, więc w środku nie staje, nawet gdy jest największy: środek
    ma mówić, co dominuje, a „57,4% Pozostałe (14)" nie mówi nic. Przy
    remisie wygrywa wcześniejszy wiersz. Kawałek zerowy środkiem nie jest.

    `miara` i `udzial` wybierają miarę koła: domyślnie złotówki, dla trybu
    „szt." przełącznika — `sztuki` i `udzial_sztuk` (24.09.2026). Kształt
    wyniku jest ten sam, więc przeglądarka rysuje oba środki jedną funkcją.
    """
    najwiekszy = None
    for wiersz in wiersze:
        if wiersz.get('zbiorczy') or not wiersz[miara] > 0:
            continue
        if najwiekszy is None or wiersz[miara] > najwiekszy[miara]:
            najwiekszy = wiersz
    return ({'etykieta': najwiekszy['etykieta'], 'udzial': najwiekszy[udzial]}
            if najwiekszy else None)


# Ile kolorów ma paleta kół w analiza.js (`KOLORY_PIERSCIENIA`).
KOLORY_KOLA = 5

# Kolor NEUTRALNY w tej palecie: `KOLORY_PIERSCIENIA[0]`, szary `--neutral`
# (#C9C2B7) z analiza.css — ten sam, którym makieta maluje zbiorczy wiersz
# „Partnerzy (7)". Dostaje go kawałek „Pozostałe (N)" i KAŻDA wartość spoza
# czołówki odniesienia (patrz `_przydziel_kolory`). Żadna kategoria go nie
# nosi, więc neutralny kawałek nie udaje kategorii.
INDEKS_NEUTRALNY = 0

# Kolory KATEGORII — cała paleta bez neutralnego, w stałej kolejności. Ile
# ich jest, tyle wartości czołówki odniesienia dostaje własny kolor.
KOLORY_KATEGORII: Tuple[int, ...] = tuple(
    k for k in range(KOLORY_KOLA) if k != INDEKS_NEUTRALNY)


def _przydziel_kolory(wiersze: List[Dict[str, object]], ogon: List[Dict[str, object]],
                      odniesienie: List[Dict[str, object]],
                      ogon_odniesienia: List[Dict[str, object]]) -> None:
    """Indeks koloru każdego kawałka koła — kolor idzie za ENCJĄ (wartością)
    i nie zmienia się przy żadnej kombinacji wykluczeń.

    Decyzja z 24.09.2026 (kontrola ostatnich poprawek, WAŻNE 1). Poprzednie
    reguły pożyczały „wolne" kolory wartościom, które wypłynęły z ogona,
    a gdy wolnych brakowało — kolor „Pozostałe" albo niewidocznej wartości.
    Każda z nich przemalowywała jakiś kawałek przy którymś kliknięciu, bo to,
    co było wolne, zależało od tego, co akurat widać.

    `odniesienie` i `ogon_odniesienia` to wiersze i rozpisany ogon TEJ SAMEJ
    karty (typ, wymiar, okres; seria bazowa) policzone BEZ wykluczeń
    użytkownika. Warunek stały „tylko sprzedaż" (E5) zostaje, bo wykluczeniem
    nie jest. Reguła:

    - CZOŁÓWKA odniesienia, czyli pierwsze `len(KOLORY_KATEGORII)` wartości
      w jego kolejności (kawałki, potem rozpisany ogon), dostaje swoje stałe
      kolory kategorii, po kolei;
    - każda INNA wartość i kawałek „Pozostałe (N)" dostają ZAWSZE jeden i ten
      sam kolor neutralny (`INDEKS_NEUTRALNY`). Żadnego zapasu, żadnego
      pożyczania wolnych kolorów: wartość, dla której zabrakło koloru
      kategorii, nie dostaje wymyślonego odcienia, tylko kolor „Inne". Gdy
      wykluczenia wypchną do widoku kilka wartości spoza czołówki, na kole
      stoi kilka neutralnych kawałków obok siebie — rozróżniają je etykiety,
      legenda i odstęp między kawałkami;
    - wiersze rozpisanego ogona to części kawałka „Pozostałe", więc mają
      jego kolor, czyli neutralny.

    Przydział zależy WYŁĄCZNIE od odniesienia, nigdy od tego, co akurat widać,
    więc wartość ma ten sam kolor w każdym stanie, a dwa nieneutralne kawałki
    jednego koła nigdy nie dzielą koloru. Serwer podaje INDEKS, przeglądarka
    tylko tłumaczy go na barwę z palety; żadna liczba nie powstaje
    w przeglądarce.

    Kawałek szuka swojej wartości w odniesieniu po GRUPIE bazy
    (`aggregates.dopasuj_wiersze`), nie po dokładnym napisie: zapytanie bez
    wykluczeń potrafi oddać tę samą wartość innym zapisem („buk" wobec „Buk").
    Po napisie encja z czołówki dostawała wtedy kolor neutralny.
    """
    # WSZYSTKIE wartości odniesienia, nie tylko czołówka: kawałek spoza
    # czołówki ma znaleźć SWÓJ wiersz (z kolorem neutralnym), a nie pożyczyć
    # koloru innego zapisu, który w czołówce jest.
    wartosci_odniesienia: List[Dict[str, object]] = []
    widziane = set()
    for w in list(odniesienie) + list(ogon_odniesienia):
        if w.get('zbiorczy') or w['wartosc'] in widziane:
            continue
        widziane.add(w['wartosc'])
        miejsce = len(wartosci_odniesienia)
        wartosci_odniesienia.append({
            'wartosc': w['wartosc'],
            'indeks_koloru': (KOLORY_KATEGORII[miejsce]
                              if miejsce < len(KOLORY_KATEGORII) else INDEKS_NEUTRALNY)})

    nazwane = [w for w in wiersze if not w.get('zbiorczy')]
    pary, _ = dopasuj_wiersze([w['wartosc'] for w in nazwane], wartosci_odniesienia)
    for w, para in zip(nazwane, pary):
        w['indeks_koloru'] = para['indeks_koloru'] if para else INDEKS_NEUTRALNY
    for w in wiersze:
        if w.get('zbiorczy'):
            w['indeks_koloru'] = INDEKS_NEUTRALNY
    for w in ogon:
        w['indeks_koloru'] = INDEKS_NEUTRALNY


def _wiersze_kola(pary: List[Tuple[object, str, Decimal, int]], limit: int
                  ) -> Tuple[List[Dict[str, object]], List[Dict[str, object]],
                             Optional[Dict[str, object]]]:
    """Kawałki koła: górka, wiersz „Pozostałe (N)" i rozpisany ogon — z udziałem %.

    `pary` to (wartość, etykieta, netto, sztuki) w kolejności wyświetlania;
    para bez czwartego elementu ma zero sztuk. Ta sama reguła limitu, co na
    kartach ze słupkami: `limit` liczy wiersze ŁĄCZNIE z wierszem zbiorczym,
    a ogon jedzie gotowy w tej samej odpowiedzi.

    Udział liczy SERWER (`_udzialy_do_stu`) — widoczne kawałki sumują się do
    100,0, a ogon do udziału „Pozostałe". Największy kawałek (środek
    pierścienia) też wskazuje serwer (`_srodek_kola`): przy kubełkach
    kolejność jest stała („1 zam.", „2–3"…), więc pierwszy wiersz nie musi
    być największy.

    SZTUKI (24.09.2026, tryb „szt." przełącznika): każdy kawałek niesie też
    `sztuki` i `udzial_sztuk` — tą samą metodą największej reszty, osobno dla
    widocznych kawałków (do stu) i dla ogona (do udziału „Pozostałe" w
    sztukach). Skład kawałków i ogona jest JEDEN, ustalony po złotówkach —
    w trybie „szt." te same encje zmieniają tylko wielkość, a ich kolor
    (`_przydziel_kolory`) zostaje.
    """
    pary = [(p[0], p[1], p[2], p[3] if len(p) > 3 else 0) for p in pary]
    if len(pary) > limit:
        glowa, ogon = pary[:limit - 1], pary[limit - 1:]
    else:
        glowa, ogon = pary, []

    wiersze = [{'wartosc': wartosc, 'etykieta': etykieta, 'netto': netto,
                'sztuki': sztuki, 'zbiorczy': False}
               for wartosc, etykieta, netto, sztuki in glowa]
    if ogon:
        wiersze.append({'wartosc': None, 'etykieta': f'Pozostałe ({len(ogon)})',
                        'netto': sum((p[2] for p in ogon), Decimal('0')),
                        'sztuki': sum(p[3] for p in ogon),
                        'zbiorczy': True})
    rozpisany = [{'wartosc': wartosc, 'etykieta': etykieta, 'netto': netto,
                  'sztuki': sztuki, 'zbiorczy': False}
                 for wartosc, etykieta, netto, sztuki in ogon]
    _udzialy_kola_do_stu(wiersze, rozpisany)

    return wiersze, rozpisany, _srodek_kola(wiersze)


def _wiersze_klientow(wymiar: str, od: date, do: date,
                      kubelki: List[Dict[str, object]], filtr=None, pamiec=None):
    """Kawałki koła karty „Klienci według" dla wybranego wymiaru.

    KAWAŁEK TO NETTO (partia E, punkt E2 — uzasadnienie przy
    `KARTY_KUBELKOWE`). Kubełki (domyślnie) niosą `lifetime_net` klientów
    z danego kubełka — z całej historii, tak jak było, i mówi o tym uwaga pod
    kartą. Każdy inny wymiar niesie netto z POZYCJI za wybrany okres — liczone
    DOKŁADNIE tak samo jak w „Sprzedaż netto według", tą samą funkcją przez tę
    samą pamięć żądania (`_wymiar_z_pamieci`), więc karta nie ma trzeciego
    zapytania i nie ma jak rozjechać się z kartą obok. Wszystkie cztery
    wymiary karty (`WYMIARY_KLIENTOW`) leżą na poziomie zamówienia, więc
    żadne zamówienie nie trafia do dwóch kawałków.

    Zwraca (wiersze, ogon, największy) — patrz `_wiersze_kola`.
    """
    if wymiar == KARTY_KUBELKOWE['klienci']['domyslny']:
        pary = [(k['kubelek'], k['kubelek'], k['netto'], k['sztuki']) for k in kubelki]
    else:
        pary = [(w['wartosc'], _etykieta_wartosci(wymiar, w['wartosc']), w['netto'],
                 w['sztuki'])
                for w in _wymiar_z_pamieci(wymiar, od, do, filtr, pamiec)]
    return _wiersze_kola(pary, KARTY_KUBELKOWE['klienci']['limit'])


def _wiersze_naleznosci(wymiar: str, od: date, do: date,
                        kubelki: List[Dict[str, object]], filtr=None
                        ) -> Tuple[List[Dict[str, object]], List[Dict[str, object]]]:
    """Wiersze karty „Należności według" dla wybranego wymiaru.

    Miara zostaje ta sama w obu trybach — saldo — więc podpis kolumny się nie
    zmienia. Zmienia się ZASIĘG: kubełki wieku liczą się na dziś z całej
    historii, a przekrój po wymiarze za wybrany okres, jak każda inna karta.
    Mówi to wprost adnotacja pod kartą (`_UWAGI_KART_KUBELKOWYCH`).
    """
    if wymiar == KARTY_KUBELKOWE['naleznosci']['domyslny']:
        surowe = [{'wartosc': k['kubelek'], 'etykieta': k['kubelek'],
                   'liczba': k['saldo']} for k in kubelki]
    else:
        surowe = [{'wartosc': w['wartosc'],
                   'etykieta': _etykieta_wartosci(wymiar, w['wartosc']),
                   'liczba': w['saldo']}
                  for w in naleznosci_wg_wymiaru(wymiar, od, do, filtr=filtr)]
    return _wiersze_z_ogonem(surowe, KARTY_KUBELKOWE['naleznosci']['limit'])


def _najlepsze_srednie(nazwa: str, od: date, do: date,
                       filtr=None, pamiec=None) -> Optional[Dict[str, object]]:
    """Wiersz o najwyższym średnim zamówieniu — liczony na PEŁNYCH wynikach.

    Liczymy tutaj, a nie w przeglądarce, z dwóch powodów. Po pierwsze, spec §6.1
    mówi wprost: żadna liczba nie jest liczona w dwóch miejscach. Po drugie,
    karta dostaje wiersze już ZWINIĘTE — przeglądarka wskazałaby syntetyczny
    wiersz „Pozostałe (7)" jako najlepszego handlowca.

    `nazwa` idzie z selektora karty, a nie na sztywno: po przełączeniu karty
    opiekunów na inny wymiar podpis „Najwyższe śr. zamówienie" ma dotyczyć
    tego, co użytkownik właśnie ogląda.
    """
    najlepszy = None
    for w in _wymiar_z_pamieci(nazwa, od, do, filtr, pamiec):
        if not w['zamowienia']:
            continue
        srednie = (w['netto'] / w['zamowienia']).quantize(Decimal('0.01'))
        if najlepszy is None or srednie > najlepszy['srednie']:
            najlepszy = {'etykieta': _etykieta_wartosci(nazwa, w['wartosc']),
                         'srednie': srednie}
    return najlepszy


# Pole rejestru, przy którym karta wykończeń liczy „Cenę za m³ z wykończeniem"
# wobec surowego. Tak jak przy WYMIAR_MAPY: selektor karty zostaje, ale po
# przełączeniu jej na inny wymiar porównanie z „surowym" traci sens — na
# produkcji status „W produkcji - surowe" zawiera „surow" i karta na Statusie
# pokazywała „-10,7% wobec surowego". Serwer tej liczby wtedy nie liczy,
# a szablon nie rysuje podsekcji.
WYMIAR_WYKONCZENIA = 'finish_state'


def _roznica_do_surowego(nazwa: str, od: date, do: date,
                         filtr=None, pamiec=None) -> Optional[Decimal]:
    """O ile procent droższy jest metr sześcienny z wykończeniem niż surowy.

    Jak wyżej: na PEŁNYCH wynikach `wg_wymiaru`, przed zwinięciem ogona.
    Liczone w przeglądarce uśredniałoby razem z wierszem zbiorczym i podawało
    liczbę, której nie da się odtworzyć z niczego widocznego na ekranie.

    Zwraca `None`, gdy w wybranym wymiarze nie ma wiersza „surowy" — karta
    pokazuje wtedy kreskę, a nie zmyśloną różnicę.

    Stronę „z wykończeniem" tworzą tylko wiersze, które NAZYWAJĄ wykończenie
    i MAJĄ objętość. Dwa rodzaje wierszy odpadają:

    - „(brak)" — pusta wartość to nie wykończenie, tylko jego brak. Na
      produkcji to prawie wyłącznie usługi (netto bez objętości). Doliczone
      podbijały licznik, a mianownika nie ruszały: karta pokazywała
      +2 027,4% wobec surowego zamiast +153,5% (wrzesień 2025, odznaczony
      lakierowany — weryfikacja E8, Z1). Odznaczenie wykończenia zabiera
      prawdziwą objętość, a pusta wartość zostaje zawsze, więc wykluczenia
      błąd pogłębiały;
    - wiersz z zerową objętością — jego cena za m³ nie istnieje (karta
      „Objętość i cena za m³" ma przy nim kreskę), a doliczony dawałby netto
      bez metrów.

    Wiersz „surowy" liczy się tak jak na karcie „Objętość i cena za m³":
    całe netto przez całą objętość wiersza.
    """
    surowy, reszta = None, []
    for w in _wymiar_z_pamieci(nazwa, od, do, filtr, pamiec):
        etykieta = _etykieta_wartosci(nazwa, w['wartosc'])
        if surowy is None and 'surow' in etykieta.lower():
            surowy = w
        elif etykieta != PUSTA_WARTOSC and w['objetosc']:
            reszta.append(w)

    if surowy is None or not surowy['objetosc'] or not reszta:
        return None
    suma_netto = sum((w['netto'] for w in reszta), Decimal('0'))
    suma_obj = sum((w['objetosc'] for w in reszta), Decimal('0'))
    if not suma_obj:
        return None
    cena_surowego = surowy['netto'] / surowy['objetosc']
    if not cena_surowego:
        return None
    return (((suma_netto / suma_obj) / cena_surowego - 1) * 100).quantize(Decimal('0.1'))


# Karty, które biorą segment porównawczy. Reszta („Statystyki", „Klienci",
# „Należności", „Lejek") zostaje jednosegmentowa — uzasadnienie w opisie
# Zadania 10 i w sekcji „Zakres".
KARTY_Z_SEGMENTEM = ('kanal', 'opiekun', 'mix', 'wojewodztwo', 'wykonczenie', 'dostawa')


def _karta_porownania(nazwa: str, od: date, do: date,
                      wiersze_bazy: List[Dict[str, object]], filtr,
                      ogon_bazy: Optional[List[Dict[str, object]]] = None,
                      pamiec=None
                      ) -> Tuple[List[Dict[str, object]], List[Dict[str, object]]]:
    """Wartości segmentu W UKŁADZIE wierszy karty bazowej.

    Wyrównanie robimy tutaj, bo tylko tutaj wiadomo, które wartości wpadły do
    wiersza zbiorczego. Gdyby przeglądarka dopasowywała po etykiecie,
    „Pozostałe (7)" bazy nigdy nie zeszłoby się z „Pozostałe (4)" segmentu,
    a wiersz `(brak)` zlałby się z wierszem zbiorczym — oba mają `wartosc = None`
    i dlatego `_wiersz` niesie osobny znacznik `zbiorczy`.

    Ogon dostaje własną, równoległą listę — po jednym wpisie na wiersz
    `karta['ogon']`. Bez niej rozwinięty ogon pokazywałby przy włączonym
    segmencie sam słupek bazowy, a wiersze nad nim — dwa: ten sam wiersz
    wyglądałby inaczej przed rozwinięciem i po nim.

    Wiersz segmentu łączymy z wierszem bazy po GRUPIE bazy
    (`aggregates.dopasuj_wiersze`), nie po dokładnym napisie: zapytanie
    segmentu potrafi oddać tę samą wartość innym zapisem („kurier DPD" wobec
    „Kurier DPD" bazy). Po napisie wiersz segmentu pokazywał wtedy 0 zł
    i 0 szt., a jego kwota szła do „Pozostałe" (weryfikacja 24.09.2026).
    """
    segment = _wymiar_z_pamieci(nazwa, od, do, filtr, pamiec)
    nazwane = [w['wartosc'] for w in wiersze_bazy if not w['zbiorczy']]
    pary_nazwanych, reszta = dopasuj_wiersze(nazwane, segment)
    # Wiersze rozpisanego ogona bazy szukają pary WYŁĄCZNIE w tym, co nie
    # trafiło do nazwanych wierszy — dokładnie w tym, z czego składa się
    # „Pozostałe" segmentu. Ogon rozpisany i jego wiersz zbiorczy nie mają
    # więc jak się rozjechać.
    pary_ogona, _ = dopasuj_wiersze([w['wartosc'] for w in (ogon_bazy or [])], reszta)
    # `sztuki` (24.09.2026): druga seria w trybie „szt." przełącznika.
    pusty = {'netto': Decimal('0'), 'objetosc': Decimal('0'), 'sztuki': 0,
             'zamowienia': 0}

    def liczby(trafiony):
        return dict(pusty) if trafiony is None else {
            'netto': trafiony['netto'], 'objetosc': trafiony['objetosc'],
            'sztuki': trafiony['sztuki'], 'zamowienia': trafiony['zamowienia'],
        }

    kolejne_pary = iter(pary_nazwanych)
    wynik = []
    for wiersz in wiersze_bazy:
        if wiersz['zbiorczy']:
            wynik.append({
                'netto': sum((w['netto'] for w in reszta), Decimal('0')),
                'objetosc': sum((w['objetosc'] for w in reszta), Decimal('0')),
                'sztuki': sum(w['sztuki'] for w in reszta),
                'zamowienia': sum(w['zamowienia'] for w in reszta),
            })
        else:
            wynik.append(liczby(next(kolejne_pary)))
    return wynik, [liczby(para) for para in pary_ogona]


def _dane_porownania(od: date, do: date, trend_od: date,
                     uklad: Sequence[Instancja], karty: Dict[str, object], segment,
                     *, licz_kpi: bool, rozbicie: Optional[Dict[str, object]],
                     ma_dostawe: bool, pamiec, baza=None) -> Dict[str, object]:
    """Druga seria: te same liczby, policzone z filtrem segmentu.

    Karty segmentu są kluczowane TYM SAMYM kluczem instancji, co karty bazowe —
    inaczej przeglądarka nie miałaby jak ich zestawić przy trzech kafelkach
    tego samego typu.

    Ta sama reguła, co w serii bazowej: liczymy tylko bloki, które są na
    ekranie. Klucze bloków nieobecnych mają `None` — kontrakt jest jeden,
    niezależnie od układu.

    `baza` to filtr WYKLUCZEŃ serii bazowej (partia E, punkt E4). Segment
    liczy się z PRZECIĘCIEM obu (`_polacz_filtry`, koniunkcja): segment
    „gatunek: buk" przy odznaczonym buku jest pusty i tak ma być. Opis
    segmentu i jego parametr w adresie mówią wyłącznie o segmencie.
    """
    filtr = _polacz_filtry(segment, baza)
    drugie = kpi(od, do, filtr=filtr) if licz_kpi else None

    # Karty i ich ogony liczymy RAZ, a rozdzielamy na dwa klucze payloadu:
    # `karty` jest wyrównane do `karta['wiersze']`, `ogony` do `karta['ogon']`.
    # Karty kubełkowe są z segmentu wykluczone tak samo jak przed Planem D —
    # `KARTY_Z_SEGMENTEM` ich nie zawiera i NIE dopisujemy ich: kubełki
    # klientów liczą się z całej historii, a należności na dziś, więc druga
    # seria byłaby kłamstwem (spec §6.1.1 i zdanie na samej karcie).
    pary = {}
    for instancja in uklad:
        if instancja.typ not in KARTY_Z_SEGMENTEM:
            continue
        karta = karty[instancja.klucz]
        pary[instancja.klucz] = _karta_porownania(
            instancja.wymiar, od, do, karta['wiersze'], filtr,
            ogon_bazy=karta['ogon'], pamiec=pamiec)

    # Rozbicie kanału ręcznego liczy się TYLKO wtedy, gdy na pulpicie
    # w ogóle jest kafelek kanałów. Bez niego nie ma czego porównywać.
    # Rozbicie bazowe jest None także wtedy, gdy któreś z jego pól straciło
    # wymiar=True (`_pole_na_sztywno_dziala`) — wtedy nie ma czego porównywać.
    if rozbicie is not None:
        rozbicie_wiersze, rozbicie_ogon = _karta_porownania(
            WYMIAR_ROZBICIA_KANALU, od, do, rozbicie['wiersze'],
            _polacz_filtry(filtr, {WYMIAR_WNIOSKU_O_KANALE: list(KANAL_RECZNY)}),
            ogon_bazy=rozbicie['ogon'], pamiec=pamiec)
    else:
        rozbicie_wiersze, rozbicie_ogon = None, None

    return {
        'filtr': zapisz_filtr(segment),
        'nazwa': opis_z_etykietami(segment),
        'kolor': KOLOR_SEGMENTU_POROWNANIA,
        'kpi': {klucz: drugie[klucz] for klucz in
                ('netto', 'objetosc', 'sztuki', 'zamowienia', 'saldo',
                 'srednie_zamowienie', 'cena_za_m3')} if licz_kpi else None,
        'trend': (analytics.szereg_miesieczny(trend_od, do, filtr=filtr)
                  if licz_kpi else None),
        'karty': {klucz: para[0] for klucz, para in pary.items()},
        # Druga seria dla ROZWINIĘTEGO ogona — osobny klucz, bo `karty` musi
        # zostać wyrównane co do indeksu do `karta['wiersze']`.
        'ogony': {klucz: para[1] for klucz, para in pary.items()},
        'kanal_rozbicie': rozbicie_wiersze,
        'kanal_rozbicie_ogon': rozbicie_ogon,
        # Druga seria kartogramu. Kluczem `mapa`, a nie wierszem w `karty`,
        # bo mapa nie ma wierszy — dymek dopisuje drugą liczbę obok pierwszej.
        'mapa': _mapa_porownania(od, do, filtr, _mapa_bazowa(karty)),
        'dostawa_koszt_kuriera': (analytics.suma_kosztu_kuriera(od, do, filtr=filtr)
                                  if ma_dostawe else None),
    }


def _mapa_bazowa(karty: Dict[str, object]):
    """Kartogram karty województw, która go ma — albo None.

    Mapę niesie wyłącznie instancja `wojewodztwo:delivery_state` (patrz
    WYMIAR_MAPY), a klucz instancji jest w układzie unikalny, więc kartogram
    jest na stronie najwyżej jeden. Szukamy go po zawartości, a nie po
    kluczu, żeby ta funkcja nie musiała znać składni klucza instancji.
    """
    for karta in karty.values():
        if isinstance(karta, dict) and karta.get('mapa'):
            return karta['mapa']
    return None


def _polacz_filtry(a, b):
    """Koniunkcja dwóch filtrów. Wspólny wymiar daje PRZECIĘCIE wartości —
    „kanał ręczny" ORAZ „kanał sklep" to pustka i tak ma być, bo takie jest
    znaczenie koniunkcji. Bez tego rozbicie kanału ręcznego ignorowałoby
    segment i pokazywałoby liczby niezgodne z resztą dashboardu."""
    if not a:
        return dict(b) if b else None
    if not b:
        return dict(a)
    wynik = dict(a)
    for nazwa, wartosci in b.items():
        if nazwa in wynik:
            # Po KLUCZU GRUPY, nie po napisie: oba filtry pochodzą z różnych
            # zapytań (pola wykluczeń z całej historii, segment z popovera za
            # okres), a baza potrafi oddać tę samą grupę innym zapisem
            # („buk" / „Buk"). Porównanie po napisie dawało pustkę i segment
            # z zerami (kontrola 24.09.2026). Zostaje zapis z `a` — kolacja
            # bazy i tak porówna go z każdym zapisem tej grupy.
            klucze_b = {klucz_grupy(w) for w in wartosci}
            wspolne = [w for w in wynik[nazwa] if klucz_grupy(w) in klucze_b]
            wynik[nazwa] = wspolne if wspolne else ['\\x00brak-takiej-wartosci']
        else:
            wynik[nazwa] = list(wartosci)
    return wynik


# --- WYKLUCZENIA POZYCJI (partia E, punkt E4) -------------------------------
#
# Pola wyboru na górze pulpitu. Format w adresie i przełożenie na zwykły
# `Filtr` mieszkają w `filters.py` (sekcja „WYKLUCZENIA POZYCJI"); tutaj jest
# to, co wymaga bazy albo etykiet: lista wartości z danych, pola do szablonu
# i zdania po polsku.

def wartosci_wykluczen() -> Dict[str, List[str]]:
    """Wartości pól wykluczeń obecne w danych: pole -> lista od największego netto.

    Z DANYCH, nie ze słownika i nie z cytatu („w sumie 7 checkboxów"): na kopii
    produkcji jest też rzadka klasa A/A (35 pozycji). Klasa bez pola wyboru
    liczyłaby się po cichu zawsze, bo nie dałoby się jej odznaczyć.

    Bez wartości pustej — „brak wartości" (usługi, pozycje nierozpoznane)
    zostaje w liczbach ZAWSZE i nie ma pola. Z całej historii, a nie z okresu:
    lista pól zmieniająca się razem z okresem gubiłaby stan zapisany w adresie.
    Kolejność po netto sprzedaży (warunek stały E5), przy remisie po nazwie,
    żeby nie zależała od kolejności zwróconej przez bazę.
    """
    wynik: Dict[str, List[str]] = {}
    for nazwa in POLA_WYKLUCZEN:
        kolumna = getattr(SalesOrderItem, nazwa)
        netto = db.func.sum(SalesOrderItem.value_net)
        wiersze = (
            db.session.query(kolumna, netto)
            .join(SalesOrder, SalesOrderItem.order_id == SalesOrder.id)
            .filter(kolumna.isnot(None), kolumna != '', warunek_sprzedazy())
            .group_by(kolumna)
            .order_by(netto.desc(), kolumna)
            .all()
        )
        wynik[nazwa] = [w[0] for w in wiersze]
    return wynik


def _odznaczone_etykiety(wykluczenia) -> List[str]:
    """Etykiety odznaczonych wartości w kolejności pól (`POLA_WYKLUCZEN`)."""
    return [_etykieta_wartosci(nazwa, wartosc)
            for nazwa in POLA_WYKLUCZEN
            for wartosc in (wykluczenia or {}).get(nazwa, [])]


def pola_wykluczen(wykluczenia, obecne: Dict[str, List[str]]) -> List[Dict[str, object]]:
    """Grupy pól wyboru dla szablonu — stan każdego pola liczy SERWER.

    `czlon` to wartość zakodowana tak samo jak w `filters.zapisz_filtr`:
    przeglądarka skleja z nich parametr adresu, niczego sama nie kodując —
    jedno źródło postaci adresu.

    `zablokowane`: ostatnie zaznaczone pole grupy. Odznaczone dałoby pulpit
    z samymi zerami, więc się nie da — i pole mówi dlaczego.
    """
    from urllib.parse import quote

    grupy = []
    for nazwa in POLA_WYKLUCZEN:
        wartosci = obecne.get(nazwa) or []
        if not wartosci:
            continue
        odznaczone = (wykluczenia or {}).get(nazwa, [])
        zaznaczonych = len([w for w in wartosci if w not in odznaczone])
        grupy.append({
            'nazwa': nazwa,
            'etykieta': POLA[nazwa].etykieta,
            'wartosci': [{
                'wartosc': w,
                'etykieta': _etykieta_wartosci(nazwa, w),
                'czlon': quote(w, safe=''),
                'zaznaczone': w not in odznaczone,
                'zablokowane': w not in odznaczone and zaznaczonych == 1,
            } for w in wartosci],
        })
    return grupy


def opis_wykluczen(wykluczenia) -> str:
    """Napis pigułki bazowej przy aktywnych wykluczeniach, np. „Bez: buk, B/B".

    Pigułka „Wszystkie zamówienia" przy odznaczonym buku kłamałaby: ta sama
    etykieta „Sprzedaż netto" znaczy wtedy co innego niż bez wykluczeń.
    """
    etykiety = _odznaczone_etykiety(wykluczenia)
    return 'Bez: ' + ', '.join(etykiety) if etykiety else ''


def blok_wykluczen(wykluczenia, baza) -> Dict[str, object]:
    """Wykluczenia w payloadzie — wszystko, czego przeglądarka potrzebuje,
    gotowe: stan pól (`wykluczone`), znormalizowany parametr adresu (`tekst`),
    filtr dla wyjść do Eksploratora (`filtr`) i oba zdania po polsku."""
    etykiety = _odznaczone_etykiety(wykluczenia)
    # Nazwy pól z rejestru, tylko tych z odznaczonymi wartościami.
    grupy = [POLA[nazwa].etykieta for nazwa in POLA_WYKLUCZEN
             if (wykluczenia or {}).get(nazwa)]
    # „Gatunek, Technologia albo Klasa" — przy czterech grupach samo „albo"
    # dawało „Gatunek albo Technologia albo Klasa albo Wykończenie".
    pola = ' albo '.join([', '.join(grupy[:-1]), grupy[-1]] if len(grupy) > 2 else grupy)
    # Puste pole chroni pozycję TYLKO przed wykluczeniem z TEGO pola. Przy
    # jednej grupie „liczą się zawsze" jest więc prawdą. Przy kilku już nie:
    # pozycja z pustym gatunkiem, ale lakierowana, wypada przez „lakierowany"
    # (weryfikacja E8, Z3: na produkcji 4 pozycje, 13 453,08 zł). Wtedy zdanie
    # mówi, co naprawdę się dzieje, zamiast obiecywać.
    if len(grupy) > 1:
        dopisek = (f'Pozycja wypada tylko przez odznaczoną wartość: puste pole '
                   f'{pola} (np. u usług) jej nie wyklucza.')
    else:
        dopisek = f'Pozycje z pustym polem {pola} (np. usługi) liczą się zawsze.'
    return {
        'wykluczone': {nazwa: list(wartosci)
                       for nazwa, wartosci in (wykluczenia or {}).items()},
        'tekst': zapisz_filtr(wykluczenia),
        # Eksplorator rozumie `filtr` — i to ten sam warunek, więc wyjście
        # ze stopki kafelka prowadzi do tych samych liczb.
        'filtr': zapisz_filtr(baza),
        'opis': opis_wykluczen(wykluczenia),
        'zdanie': (f'Liczby bez pozycji: {", ".join(etykiety)}. {dopisek}'
                   if etykiety else ''),
    }


# --- KARTA LEJKA ------------------------------------------------------------

# Wartość selektora podziału, która znaczy „pokaż sam lejek". NIE jest nazwą
# pola z rejestru i nie ma nią być: rejestr opisuje kolumny, a to jest BRAK
# kolumny. Podział lejka nie jedzie też do `/api/analytics` — serwer liczy
# wszystkie trzy warianty naraz (kosztują 0,14 s na całej bazie), a selektor
# tylko przełącza między gotowymi liczbami. Dzięki temu przełączenie podziału
# jest natychmiastowe, nie kosztuje żądania i nie wymaga nowego parametru
# w adresie, którego trasa i tak musiałaby walidować.
BEZ_PODZIALU = 'brak'

# Ile wierszy podziału mieści karta ŁĄCZNIE z wierszem „Pozostałe (N)".
# Ta sama zasada co w LIMITY_KART: karta ma w siatce stałą wysokość, więc
# „5 wierszy plus ewentualnie szósty" rozjechałoby cały rząd.
LIMIT_PODZIALU_LEJKA = 5


def wymiary_lejka() -> List[Dict[str, str]]:
    """Opcje selektora podziału na karcie lejka.

    NAZWY wymiarów są nazwami z REJESTRU PÓL i przechodzą przez
    `wymiary_proste()` — nazwa, która z rejestru wypadła, po prostu znika
    z listy zamiast rozsypywać zapytanie.

    ETYKIETY są WŁASNE i celowo różne od rejestrowych („Autor wyceny", nie
    „Opiekun"). Powód w całości siedzi przy `analytics.ETYKIETY_LEJKA`:
    rejestr podpisuje kolumny ZAMÓWIENIA, a lejek grupuje po kolumnach
    WYCENY i są to inne zbiory wartości. Wspólny podpis pozwoliłby zestawić
    ze sobą dwie liczby, które nie mają wspólnego mianownika.
    """
    proste = set(wymiary_proste())
    pozycje = [{'nazwa': BEZ_PODZIALU, 'etykieta': 'Brak podziału'}]
    pozycje.extend({'nazwa': nazwa, 'etykieta': analytics.ETYKIETY_LEJKA[nazwa]}
                   for nazwa in analytics.WYMIARY_LEJKA if nazwa in proste)
    return pozycje


def _wiersze_podzialu_lejka(nazwa: str,
                            surowe: List[Dict[str, object]]) -> Dict[str, object]:
    """Podział lejka przycięty do wysokości karty, z etykietami po polsku.

    Kształt taki sam, jak na kartach ze słupkami (`_karta`): `wiersze` to
    to, co widać od razu, `ogon` to rozpisana reszta wiersza „Pozostałe (N)",
    gotowa do pokazania po kliknięciu. Jeden kształt dla obu miejsc, żeby
    „Pozostałe" znaczyło i zachowywało się wszędzie tak samo.
    """
    if len(surowe) > LIMIT_PODZIALU_LEJKA:
        glowa = surowe[:LIMIT_PODZIALU_LEJKA - 1]
        ogon = surowe[LIMIT_PODZIALU_LEJKA - 1:]
    else:
        glowa, ogon = surowe, []

    def na_wiersz(w):
        return {'wartosc': w['wartosc'],
                'etykieta': _etykieta_wartosci(nazwa, w['wartosc']),
                'wycen': w['wycen'], 'zamowione': w['zamowione'],
                'konwersja': w['konwersja']}

    wiersze = [na_wiersz(w) for w in glowa]

    if ogon:
        wycen = sum(w['wycen'] for w in ogon)
        zamowione = sum(w['zamowione'] for w in ogon)
        wiersze.append({
            'wartosc': None, 'etykieta': f'Pozostałe ({len(ogon)})',
            'wycen': wycen, 'zamowione': zamowione,
            # Świadomie sięgamy po prywatną funkcję `analytics`: reguła
            # zaokrąglenia konwersji ma być JEDNA. Przeliczenie „na piechotę"
            # dałoby w wierszu zbiorczym inną liczbę miejsc dziesiętnych niż
            # w wierszach nad nim — ta sama klasa błędu, co przepisana lista
            # grup wykluczonych z objętości.
            'konwersja': analytics._procent(zamowione, wycen),
        })
    return {'wiersze': wiersze, 'ogon': [na_wiersz(w) for w in ogon]}


def _uwaga_lejka(lejek: Dict[str, object]) -> str:
    """Zdanie, którego karta lejka nie ma prawa przemilczeć.

    Dwie rzeczy naraz. Po pierwsze: stopnie 2-5 opisują stan NA DZIŚ wycen
    z okresu, a nie zdarzenia z okresu — bez tego czytelnik odejmie stopień
    trzeci od drugiego i zobaczy „stracone" tam, gdzie jest „jeszcze
    nierozstrzygnięte". Po drugie: część wycen z numerem z BaseLinkera nie ma
    odpowiednika w tabeli sprzedaży (na całej bazie 1365 wobec 1173), bo
    tamta obejmuje węższy zakres. Ta różnica jest PRAWDZIWA i karta ma ją
    pokazać, zamiast udawać spadek konwersji między „Zamówione" a „Opłacone".

    Od partii E (punkt E5) odpowiednikiem jest zamówienie, które LICZY SIĘ do
    sprzedaży — wycena dowiązana do zamówienia anulowanego albo nieopłaconego
    też go nie ma. Stąd „w sprzedaży", a nie „w tabeli sprzedaży": wiersz
    anulowanego zamówienia w tabeli jest, tylko sprzedażą nie jest.
    """
    tekst = ('Stopnie 2–5 mówią, co stało się z wycenami z tego okresu '
             'do dziś — także już po jego końcu.')
    z_numerem = lejek['zamienionych']
    dopasowanych = lejek['dopasowanych']
    if z_numerem > dopasowanych:
        tekst += (f' Numer z BaseLinkera ma {formatuj_liczbe(z_numerem)} wycen, '
                  f'ale odpowiednik w sprzedaży — '
                  f'{formatuj_liczbe(dopasowanych)}; „Opłacone" liczy się '
                  f'z tych {formatuj_liczbe(dopasowanych)}.')
    return tekst


# --- KARTA WOJEWÓDZTW: KARTOGRAM --------------------------------------------

# Pole rejestru, przy którym karta województw pokazuje MAPĘ zamiast listy
# słupków. Selektor wymiaru na tej karcie zostaje (anatomia karty z makiety),
# więc po przełączeniu go na „Opiekun" mapa Polski opisywałaby handlowców —
# dlatego mapa jedzie do payloadu WYŁĄCZNIE dla tego jednego wymiaru,
# a każdy inny wraca do słupków, które działały zawsze.
WYMIAR_MAPY = 'delivery_state'

# Ile stopni ma skala kartogramu POWYŻEJ zera. Stopień 0 to „ma zamówienia,
# ale zerową wartość miary", a brak danych w ogóle jest osobnym stanem
# (`ma_dane`) i ma własny kolor — województwo bez ani jednego zamówienia
# musi dać się odróżnić od takiego, które ma zamówienia za 0 zł.
POZIOMY_MAPY = 5

# Ile miejsc po przecinku ma każda liczba w dymku. Decyduje SERWER, tak samo
# jak o jednostce: przeglądarka dostaje gotową regułę, zamiast trzymać własną
# listę „objętość ma dwa miejsca, reszta zero".
MIEJSCA_MAPY: Dict[str, int] = {
    'netto': 0, 'objetosc': 2, 'zamowienia': 0, 'klienci': 0, 'w_produkcji': 0,
    'sztuki': 0,
}

# Miara trybu „szt." kartogramu (24.09.2026). NIE dopisujemy jej do
# `analytics.MIARY_MAPY`: tamta krotka to wiersze dymka w trybie „zł", czyli
# dzisiejszy dymek co do wiersza. Sztuki jadą obok — w statystykach każdego
# obszaru, z własną skalą kolorów (`poziom_sztuk`) i opisem wiersza dymka
# (`dymek_sztuk`), który przeglądarka dokłada w trybie „szt.".
MIARA_SZTUK_MAPY = 'sztuki'
MIARY_DANYCH_MAPY: Tuple[str, ...] = analytics.MIARY_MAPY + (MIARA_SZTUK_MAPY,)


def _poziom_mapy(wartosc: Decimal, maks: Decimal) -> int:
    """Stopień skali sekwencyjnej dla jednej wartości, 0..POZIOMY_MAPY.

    Liczony TUTAJ, nie w przeglądarce — tak samo jak udziały i zmiany
    procentowe. Skala jest liniowa wobec maksimum, bo czytelnik porównuje
    województwa między sobą, a nie z wartością bezwzględną.
    """
    if wartosc <= 0 or maks <= 0:
        return 0
    udzial = Decimal(wartosc) * POZIOMY_MAPY / Decimal(maks)
    poziom = int(udzial)
    if udzial > poziom:         # sufit, żeby najmniejsza dodatnia wartość
        poziom += 1             # dostała stopień 1, a nie 0
    return max(1, min(POZIOMY_MAPY, poziom))


def _statystyki_mapy(dane: Dict[str, object]) -> Dict[str, object]:
    """Same miary obszaru, bez pól opisowych — jeden kształt dla obu serii.

    Miary dymka plus sztuki (`MIARY_DANYCH_MAPY`) — tryb „szt." przełącznika
    potrzebuje ich w obu seriach, a dymek trybu „zł" czyta tylko swoje.
    """
    return {miara: dane[miara] for miara in MIARY_DANYCH_MAPY}


def _opis_miary_dymka(miara: str) -> Dict[str, object]:
    """Wiersz dymka mapy: nazwa miary, jej podpis i liczba miejsc dziesiętnych."""
    return {'nazwa': miara, 'etykieta': ETYKIETY_MIAR[miara],
            'miejsca': MIEJSCA_MAPY[miara]}


def miary_mapy() -> List[Dict[str, object]]:
    """Wiersze dymka: nazwa miary, jej podpis i liczba miejsc dziesiętnych.

    Podpisy idą z `ETYKIETY_MIAR`, czyli z tego samego miejsca, co nagłówki
    kolumn Eksploratora — „Klienci" w dymku i „Klienci" w panelu miar liczą
    to samo i mają się tak samo nazywać. Jednostkę przeglądarka dobiera po
    `nazwa` z klucza `jednostki` payloadu (JEDNOSTKI_MIAR), tak jak wszędzie
    indziej na tej stronie.
    """
    return [_opis_miary_dymka(miara) for miara in analytics.MIARY_MAPY]


def _mapa_wojewodztw(od: date, do: date, filtr=None) -> Dict[str, object]:
    """Kartogram: szesnaście obszarów plus to, co na mapę nie trafiło.

    Kolor skaluje się po TEJ SAMEJ mierze, którą deklaruje `KOLUMNY_KART`
    dla tej karty — inaczej kartogram malowałby jedno, a nagłówek kolumny
    nad nim podpisywał drugie. To dokładnie ten błąd, który karty województw
    i dostawy miały już raz (słupek niósł netto, liczba obok objętość).

    `poza_mapa` NIE JEST pomijalną resztką: na całej bazie to 296 zamówień
    bez województwa (691 103 zł) i jedno z uciętą nazwą „Dol". Suma mapy
    nie zgadza się bez nich z KPI i karta musi to pokazać wprost.
    """
    miara = KOLUMNY_KART['wojewodztwo'][0]
    surowe = analytics.sprzedaz_wg_wojewodztw(od, do, filtr=filtr)
    obszary_surowe = surowe['obszary']
    maks = max((obszary_surowe[klucz][miara]
                for klucz in analytics.IDENTYFIKATORY_WOJEWODZTW),
               default=Decimal('0'))
    # Druga skala kolorów — tryb „szt." przełącznika (24.09.2026). Liczona
    # tą samą funkcją, wobec maksimum SZTUK, bo województwo z dużą kwotą
    # i małą liczbą sztuk ma być w tym trybie jasne, a nie ciemne.
    maks_sztuk = max((obszary_surowe[klucz][MIARA_SZTUK_MAPY]
                      for klucz in analytics.IDENTYFIKATORY_WOJEWODZTW), default=0)

    obszary = []
    for klucz in analytics.IDENTYFIKATORY_WOJEWODZTW:
        dane = obszary_surowe[klucz]
        pozycja = {
            'id': klucz,
            'nazwa': analytics.WOJEWODZTWA[klucz],
            # „Ma dane" to ma ZAMÓWIENIA, nie „ma dodatnią miarę". Bez tego
            # rozróżnienia województwo z zamówieniami na 0 zł wyglądałoby
            # identycznie jak takie, do którego nigdy nic nie pojechało.
            'ma_dane': dane['zamowienia'] > 0,
            'poziom': _poziom_mapy(dane[miara], maks),
            'poziom_sztuk': _poziom_mapy(Decimal(dane[MIARA_SZTUK_MAPY]),
                                         Decimal(maks_sztuk)),
        }
        pozycja.update(_statystyki_mapy(dane))
        obszary.append(pozycja)

    poza_mapa = [dict(_statystyki_mapy(p), wartosc=p['wartosc'],
                      etykieta=_etykieta_wartosci(WYMIAR_MAPY, p['wartosc']))
                 for p in surowe['poza_mapa']]

    return {'miara': miara, 'maks': maks, 'maks_sztuk': maks_sztuk,
            'poziomy': POZIOMY_MAPY, 'miary': miary_mapy(),
            'dymek_sztuk': _opis_miary_dymka(MIARA_SZTUK_MAPY),
            'obszary': obszary, 'poza_mapa': poza_mapa}


def _mapa_porownania(od: date, do: date, filtr,
                     mapa_bazy: Optional[Dict[str, object]]) -> Optional[Dict[str, object]]:
    """Te same liczby pod filtrem segmentu, W UKŁADZIE mapy bazowej.

    Wyrównanie co do indeksu, dokładnie jak w `_karta_porownania`: dymek
    dopisuje drugą liczbę obok pierwszej i musi wiedzieć, która do której.
    Bez tego karta po włączeniu segmentu wyglądałaby identycznie jak bez
    niego — znalezisko z przeglądu Zadania 10, powtórzone tu celowo.

    Kolor kartogramu zostaje przy serii BAZOWEJ. Dwa kartogramy na jednej
    mapie nie mają jak współistnieć, a przemalowanie jej na segment ukryłoby
    fakt, że pozostałe karty pokazują obie serie naraz.
    """
    if not mapa_bazy:
        return None
    surowe = analytics.sprzedaz_wg_wojewodztw(od, do, filtr=filtr)
    puste = {miara: Decimal('0') if miara in ('netto', 'objetosc') else 0
             for miara in MIARY_DANYCH_MAPY}
    # „Poza mapą" to surowe zapisy województw — łączone po GRUPIE bazy, nie po
    # napisie, jak wiersze kart (patrz `_karta_porownania`).
    pary, _ = dopasuj_wiersze([wiersz['wartosc'] for wiersz in mapa_bazy['poza_mapa']],
                              surowe['poza_mapa'])
    return {
        'obszary': [_statystyki_mapy(surowe['obszary'][pozycja['id']])
                    for pozycja in mapa_bazy['obszary']],
        'poza_mapa': [_statystyki_mapy(para) if para else dict(puste) for para in pary],
    }


def _karta_kubelkowa(klucz: str, wymiar: str, od: date, do: date,
                     na_dzien: date, pamiec=None, filtr=None) -> Dict[str, object]:
    """Karta „Klienci według" albo „Należności według", dla JEDNEGO wymiaru.

    Treść przeniesiona co do klucza z `dane_dashboardu` sprzed Planu D
    (commit 5206f18). Zmieniło się to, że wolno ją zawołać kilka razy
    w jednym żądaniu — po razie na każdą instancję kafelka — i że sześć
    funkcji NIEZALEŻNYCH od wymiaru (`klienci_wg_liczby_zamowien`,
    `konwersja_lead_klient`, `nowi_klienci`, `naleznosci_wg_wieku`,
    `ostrzezenie_salda`, `nadplaty`) idzie przez `_wartosc_z_pamieci`, więc
    liczy się co najwyżej raz na żądanie, a nie raz na instancję. Nic tu nie
    liczymy inaczej niż przedtem.

    `filtr` to filtr WYKLUCZEŃ pulpitu (partia E, punkt E4). Dostają go liczby
    liczone z zamówień: nowi klienci w okresie, wiersze przekroju, kubełki
    wieku należności, ostrzeżenie o saldzie i nadpłaty. NIE dostają go kubełki
    klientów i konwersja — liczą się z denormalizacji z całej historii, w której
    pozycji już nie ma; mówi o tym dopisek do uwagi karty. Klucze pamięci
    niosą filtr, choć w jednym żądaniu jest on jeden — zmiana tego założenia
    nie ma prawa podać cudzych liczb.
    """
    klucz_filtra = zapisz_filtr(filtr)
    if klucz == 'klienci':
        # `list(...)`: kopia listy z pamięci, żeby druga instancja karty
        # klientów (inny wymiar, ta sama pamięć) nie dostała referencji do
        # listy, którą ktoś kiedyś zacznie mutować pod `blok['kubelki']`.
        kubelki = list(_wartosc_z_pamieci(
            ('klienci_wg_liczby_zamowien',), analytics.klienci_wg_liczby_zamowien, pamiec))
        wiersze, ogon, najwiekszy = _wiersze_klientow(wymiar, od, do, kubelki,
                                                      filtr=filtr, pamiec=pamiec)
        # Kolor kawałka za encją: odniesieniem to samo koło bez wykluczeń,
        # razem z ogonem (patrz `_przydziel_kolory`). Kubełki i tak liczą się
        # bez filtra.
        odniesienie, ogon_odniesienia = (
            _wiersze_klientow(wymiar, od, do, kubelki, pamiec=pamiec)[:2]
            if filtr else (wiersze, ogon))
        _przydziel_kolory(wiersze, ogon, odniesienie, ogon_odniesienia)
        blok = {
            'kubelki': kubelki,
            # Środek pierścienia: największy kawałek z udziałem — z serwera.
            'najwiekszy': najwiekszy,
            # To samo dla trybu „szt." przełącznika (24.09.2026).
            'najwiekszy_sztuk': _srodek_kola(wiersze, 'sztuki', 'udzial_sztuk'),
            'konwersja': _wartosc_z_pamieci(
                ('konwersja_lead_klient',), analytics.konwersja_lead_klient, pamiec),
            'nowi_w_okresie': _wartosc_z_pamieci(
                ('nowi_klienci', od, do, klucz_filtra),
                lambda: analytics.nowi_klienci(od, do, filtr=filtr), pamiec),
        }
    else:
        surowe_wieku = _wartosc_z_pamieci(
            ('naleznosci_wg_wieku', na_dzien, klucz_filtra),
            lambda: naleznosci_wg_wieku(na_dzien, filtr=filtr), pamiec)
        # Lista budowana od nowa z surowych kubełków (przemianowanie etykiet)
        # — nie referencja do tego, co leży w pamięci, więc kopiować nie trzeba.
        kubelki = [
            {'kubelek': ETYKIETY_WIEKU.get(k['kubelek'], k['kubelek']),
             'zamowienia': k['zamowienia'], 'saldo': k['saldo']}
            for k in surowe_wieku
        ]
        wiersze, ogon = _wiersze_naleznosci(wymiar, od, do, kubelki, filtr=filtr)
        blok = {
            'kubelki': kubelki,
            'ostrzezenie': _wartosc_z_pamieci(
                ('ostrzezenie_salda', na_dzien, klucz_filtra),
                lambda: analytics.ostrzezenie_salda(na_dzien, filtr=filtr), pamiec),
            # Osobna pozycja, NIE kubełek wieku — patrz komentarz przy
            # `aggregates.nadplaty`. Liczona bez filtru daty, tak samo jak
            # kubełki wyżej: obie liczą się „na dziś", nie za wybrany okres.
            'nadplaty': _wartosc_z_pamieci(('nadplaty', klucz_filtra),
                                           lambda: nadplaty(filtr=filtr), pamiec),
        }

    blok.update({
        # Wiersze karty przychodzą POLICZONE, w tym samym kształcie co
        # na kartach ze słupkami: `wiersze` to co widać od razu, `ogon`
        # to rozpisana reszta wiersza „Pozostałe (N)".
        'wymiar': wymiar,
        'wymiary': wymiary_karty_kubelkowej(klucz),
        'naglowek': naglowek_karty_kubelkowej(klucz, wymiar),
        'wiersze': wiersze,
        'ogon': ogon,
        'uwaga': _uwaga_karty_kubelkowej(_UWAGI_KART_KUBELKOWYCH, klucz, wymiar, filtr),
    })
    if klucz in _UWAGI_SZTUK_KART_KUBELKOWYCH:
        # Wariant dla trybu „szt." przełącznika — patrz _UWAGI_SZTUK_KART_KUBELKOWYCH.
        blok['uwaga_sztuk'] = _uwaga_karty_kubelkowej(
            _UWAGI_SZTUK_KART_KUBELKOWYCH, klucz, wymiar, filtr)
    return blok


def _uwaga_karty_kubelkowej(uwagi: Dict[str, Dict[bool, str]], klucz: str,
                            wymiar: str, filtr) -> str:
    """Zdanie o zasięgu liczb karty kubełkowej dla jej stanu (kubełki albo
    wymiar) i — przy aktywnych wykluczeniach — dopisek o nich. `uwagi` wybiera
    zestaw zdań: tryb „zł" albo „szt." przełącznika."""
    kubelki = wymiar == KARTY_KUBELKOWE[klucz]['domyslny']
    dopisek = _DOPISKI_WYKLUCZEN.get(klucz, {}).get(kubelki, '') if filtr else ''
    return uwagi[klucz][kubelki] + dopisek


# Typy, których kafelki czytają pasek wskaźników i wykres trendu. `kpi` pokazuje
# oba, a „Statystyki" składają z nich swoje trzy zdania (`_wniosek_cena` czyta
# `trend`, `_wniosek_srednie` czyta `kpi`). Gdy nie ma ani jednego z nich,
# nie liczymy tych dwóch bloków wcale — to 26 ms, a przy `/api/kafelek`
# (Zadanie 8), które prosi o JEDEN kafelek, byłby to czysty narzut.
TYPY_CZYTAJACE_KPI = ('kpi', 'wnioski')


def dane_dashboardu(od: date, do: date, uklad: Sequence[Instancja],
                    na_dzien: Optional[date] = None,
                    porownanie=None, pominietych: int = 0,
                    wykluczenia=None, obecne=None) -> Dict[str, object]:
    """Komplet danych pulpitu dla jednego żądania.

    `uklad` to uporządkowana lista `uklad.Instancja`. Kolejność nie ma tu
    znaczenia (payload jest słownikiem po kluczach instancji), ale ZBIÓR ma:
    liczymy WYŁĄCZNIE to, co realnie jest na ekranie. Użytkownik, który usunął
    lejek, oszczędza 20,9 ms na każdym odświeżeniu; wywołanie z jedną instancją
    (`/api/kafelek`, Zadanie 8) kosztuje tyle, co jeden kafelek.

    Wołający ręczy za układ: typ jest w katalogu, a wymiar na liście tego
    typu. Trasa bierze układ z bazy przez `uklad_service.uklad_uzytkownika`,
    który to gwarantuje (zapis przechodzi przez `uklad.parsuj_uklad`, odczyt
    przez `uklad.uklad_z_bazy`).

    Klucze bloków, których w układzie nie ma, są w payloadzie obecne i mają
    `None`. Kontrakt jest przez to JEDEN, niezależnie od układu — przeglądarka
    nie musi zgadywać, czy klucz zniknął, czy się nie policzył.

    WYKLUCZENIA (partia E, punkty E4 i E8): `wykluczenia` to odznaczone
    wartości pól `filters.POLA_WYKLUCZEN` (`filters.parsuj_wykluczenia`), `obecne` —
    wartości z danych, z których zbudowano pola wyboru (trasa ma je już po
    walidacji, więc nie pytamy bazy drugi raz). Zamieniamy je RAZ na zwykły
    filtr `baza` i ten filtr dostaje KAŻDA liczba serii bazowej, a segment
    — jego przecięcie ze swoim filtrem. Nie dostają go wyłącznie kubełki
    klientów z konwersją (cała historia, bez pozycji) i lejek (wyceny, nie
    pozycje sprzedaży) — obie karty mówią o tym wprost.
    """
    na_dzien = na_dzien or dzis_lokalnie()
    od_poprz, do_poprz = poprzedni_okres(od, do)
    # Pamięć na czas TEGO żądania — patrz `_wymiar_z_pamieci`.
    pamiec: Dict[tuple, object] = {}

    if wykluczenia and obecne is None:
        obecne = wartosci_wykluczen()
    baza = filtr_z_wykluczen(wykluczenia, obecne or {})

    typy = {i.typ for i in uklad}
    licz_kpi = bool(set(TYPY_CZYTAJACE_KPI) & typy)

    biezacy = kpi(od, do, filtr=baza) if licz_kpi else None
    poprzedni = kpi(od_poprz, do_poprz, filtr=baza) if licz_kpi else None

    # Wykres trendu pokazuje CAŁY bieżący rok do końca okresu, z nakładką tych
    # samych miesięcy roku poprzedniego — nie okres z paska KPI. Tak jest
    # w makiecie (słupki STY..WRZ przy okresie 1-21 września).
    trend_od = date(do.year, 1, 1)
    trend_poprz_od = date(do.year - 1, 1, 1)
    trend_poprz_do = _koniec_miesiaca(do.year - 1, do.month)

    # --- karty wymiarowe, jedna na INSTANCJĘ --------------------------------
    karty: Dict[str, object] = {}
    for instancja in uklad:
        typ = KATALOG[instancja.typ]
        if not typ.wymiarowy:
            continue
        if instancja.typ in KARTY_KUBELKOWE:
            # Karty kubełkowe mają własne budowanie wierszy i własną, węższą
            # listę wymiarów — patrz `_karta_kubelkowa` i commit 5206f18.
            karty[instancja.klucz] = _karta_kubelkowa(
                instancja.typ, instancja.wymiar, od, do, na_dzien, pamiec=pamiec,
                filtr=baza)
            continue
        karta = _karta(instancja.wymiar, od, do,
                       LIMITY_KART.get(instancja.typ, 7), filtr=baza, pamiec=pamiec)
        # Dwie liczby, które poprzednik liczył w PRZEGLĄDARCE (spec §11:
        # „logika biznesowa w przeglądarce … to jeden z długów"). Dodatki są
        # cechą TYPU, ale liczą się dla wymiaru TEJ instancji. Obie liczby
        # powstają na PEŁNYCH wynikach `wg_wymiaru`, przed zwinięciem ogona,
        # więc nie da się ich odtworzyć z `wiersze`.
        if instancja.typ == 'opiekun':
            karta['najlepszy'] = _najlepsze_srednie(instancja.wymiar, od, do,
                                                    filtr=baza, pamiec=pamiec)
        elif instancja.typ == 'wykonczenie':
            # Kolor kawałka za encją: odniesieniem ta sama karta bez
            # wykluczeń, razem z ogonem (patrz `_przydziel_kolory`).
            odniesienie = (_karta(instancja.wymiar, od, do, LIMITY_KART.get(instancja.typ, 7),
                                  pamiec=pamiec) if baza else karta)
            _przydziel_kolory(karta['wiersze'], karta['ogon'],
                              odniesienie['wiersze'], odniesienie['ogon'])
            # Udziały pierścienia do stu — ta sama reguła co na kole klientów.
            _udzialy_kola_do_stu(karta['wiersze'], karta['ogon'])
            # Tylko na wymiarze wykończenia (patrz WYMIAR_WYKONCZENIA). Klucz
            # zostaje z None, żeby kształt karty był ten sam na każdym wymiarze.
            karta['roznica_do_surowego'] = (
                _roznica_do_surowego(instancja.wymiar, od, do, filtr=baza, pamiec=pamiec)
                if instancja.wymiar == WYMIAR_WYKONCZENIA else None)
            # Środek pierścienia — ta sama reguła co na kole klientów.
            karta['najwiekszy'] = _srodek_kola(karta['wiersze'])
            # I dla trybu „szt." przełącznika (24.09.2026). Wiersze są te
            # same, więc kolory kawałków (wyżej) nie zależą od miary.
            karta['najwiekszy_sztuk'] = _srodek_kola(karta['wiersze'], 'sztuki',
                                                     'udzial_sztuk')
        elif instancja.typ == 'wojewodztwo' and instancja.wymiar == WYMIAR_MAPY:
            # Kartogram TYLKO dla wymiaru, który opisuje województwa — przy
            # każdym innym karta wraca do słupków (patrz WYMIAR_MAPY).
            karta['mapa'] = _mapa_wojewodztw(od, do, filtr=baza)
        karty[instancja.klucz] = karta

    # --- rozbicie kanału ręcznego -------------------------------------------
    # Osobno, bo to druga oś karty kanałów, a nie alternatywny wymiar do wyboru
    # w selektorze — i NIEZALEŻNE od wymiaru kafelka kanałów. Przy kilku
    # kafelkach kanałów liczy się RAZ i jest wspólne, bo od wymiaru nie zależy.
    #
    # ZAWĘŻONE DO KANAŁU RĘCZNEGO. Bez tego zawężenia karta pokazywałaby
    # segmentację CAŁEJ sprzedaży pod nagłówkiem „Wewnątrz kanału ręcznego",
    # a `client_origin` jest wypełniony tylko dla części zamówień (po skrypcie
    # uzupełnienia z partii E: ok. 1160 z 3339 na kopii produkcji z 23.09.2026)
    # — duża część zamówień ze sklepu i z Allegro go nie ma, więc wiersz
    # „(brak)" z ogromnym netto wypchnąłby prawdziwe segmenty poza limit
    # trzech wierszy.
    #
    # Oba pola są wpisane TU na sztywno, nie przyszły z układu, więc nikt ich
    # nie sprawdził przy odczycie. Pole, które straciło wymiar=True, wyłącza
    # sam blok (None + ostrzeżenie w logu), a nie cały pulpit — partia E, E7.
    rozbicie = _karta(WYMIAR_ROZBICIA_KANALU, od, do, 3,
                      filtr=_polacz_filtry(
                          baza, {WYMIAR_WNIOSKU_O_KANALE: list(KANAL_RECZNY)}),
                      pamiec=pamiec) if (
        'kanal' in typy
        and _pole_na_sztywno_dziala(WYMIAR_ROZBICIA_KANALU, 'kanal_rozbicie')
        and _pole_na_sztywno_dziala(WYMIAR_WNIOSKU_O_KANALE, 'kanal_rozbicie')
    ) else None

    wynik = {
        'okres': {
            'od': od, 'do': do,
            'stan_na': teraz_lokalnie().strftime('%H:%M'),
            # Nazwa presetu i opis po polsku powstaja TUTAJ. Gdyby liczyl je
            # JavaScript, polskie skroty miesiecy i reguly laczenia zakresow
            # zylyby w dwoch miejscach.
            'nazwa': nazwa_zakresu(od, do),
            'opis': opis_okresu(od, do),
        },
        'kpi': {
            'netto': biezacy['netto'],
            'objetosc': biezacy['objetosc'],
            # Sztuki produktów okresu (24.09.2026) — dla trybu „szt."
            # przełącznika kafelka KPI; liczone w zapytaniu netto.
            'sztuki': biezacy['sztuki'],
            'zamowienia': biezacy['zamowienia'],
            'saldo': biezacy['saldo'],
            'srednie_zamowienie': biezacy['srednie_zamowienie'],
            'cena_za_m3': biezacy['cena_za_m3'],
            'zmiana': {
                klucz: zmiana_procentowa(biezacy[klucz], poprzedni[klucz])
                for klucz in ('netto', 'objetosc', 'sztuki', 'zamowienia',
                              'srednie_zamowienie', 'cena_za_m3')
            },
        } if licz_kpi else None,
        'trend': {
            'etykiety': list(MIESIACE_SKROT[:do.month]),
            'biezacy_rok': do.year,
            'poprzedni_rok': do.year - 1,
            'biezacy': analytics.szereg_miesieczny(trend_od, do, filtr=baza),
            'poprzedni': analytics.szereg_miesieczny(trend_poprz_od, trend_poprz_do,
                                                     filtr=baza),
        } if licz_kpi else None,
        # Karty kluczowane INSTANCJĄ (`typ:wymiar`) — także obie karty
        # kubełkowe, które do Planu D były kluczami najwyższego poziomu
        # (`klienci`, `naleznosci`), bo każda występowała raz.
        'karty': karty,
        'kanal_rozbicie': rozbicie,
        'lejek': None,
        'dostawa_koszt_kuriera': (analytics.suma_kosztu_kuriera(od, do, filtr=baza)
                                  if 'dostawa' in typy else None),
        'wymiary_dostepne': [
            {'nazwa': n, 'etykieta': POLA[n].etykieta} for n in wymiary()
        ],
        # Jednostki JADĄ Z SERWERA. analiza.js składa z nich teksty w rodzaju
        # „41 248 zł brutto" — bez tego napis „zł" byłby drugim źródłem prawdy
        # o jednostce, obok nagłówków, które wypisuje szablon.
        'jednostki': dict(JEDNOSTKI_MIAR),
        # Nazwy miar dla wspólnego dymka wykresów (partia E, punkt E3) — ten
        # sam słownik, co nagłówki Eksploratora i dymek mapy. „Netto" w dymku
        # koła ma znaczyć to samo, co „Netto" nad kolumną kwot obok.
        'etykiety_miar': dict(ETYKIETY_MIAR),
        # Bez segmentu na pasku jest sam chip bazowy, a `porownanie` to None.
        # Przy aktywnych wykluczeniach chip bazowy mówi „Bez: buk, B/B" —
        # „Wszystkie zamówienia" byłoby wtedy nieprawdą (partia E, punkt E4).
        'segmenty': [{'id': 'baza',
                      'nazwa': opis_wykluczen(wykluczenia) or NAZWA_SEGMENTU_BAZY,
                      'wykluczenia': bool(baza),
                      'kolor': KOLOR_SEGMENTU_BAZA, 'filtr': ''}],
        'wykluczenia': blok_wykluczen(wykluczenia, baza),
        'porownanie': None,
        'wnioski': None,
        # Ile pozycji zapisanego układu nie dało się rozpoznać (zniknął typ
        # karty albo pole straciło wymiar=True). Zero to normalny stan;
        # cokolwiek innego zamienia się na pasku w jedno bursztynowe zdanie.
        'pominietych': pominietych,
        # Przełącznik „zł / szt. / zł + szt." KAŻDEJ instancji układu
        # (24.09.2026) — None, gdy kafelek go nie ma. Klucze te same, co
        # w `karty`; kafelek bez wymiaru (KPI) pod swoim kluczem typu.
        # Dane obu miar już są w payloadzie, więc przełączenie niczego nie
        # dopytuje.
        'przelaczniki': {i.klucz: opcje_przelacznika(i.typ, i.wymiar) for i in uklad},
    }

    if 'lejek' in typy:
        # Jedno wywołanie zamiast dwóch. Karta nie rysuje już szeregu
        # miesięcznego konwersji (pięć stopni lejka zajęło miejsce wykresu).
        # Podziały liczymy od razu wszystkie — patrz komentarz przy BEZ_PODZIALU.
        lejek = analytics.lejek_wycen(od, do, podzialy=analytics.WYMIARY_LEJKA)
        wynik['lejek'] = {
            # Bez osobnych kluczy „wycen" i „zamienionych": obie liczby są
            # stopniami lejka i drugi zapis w payloadzie byłby drugim źródłem
            # prawdy o tej samej wielkości.
            'stopnie': lejek['stopnie'],
            'dopasowanych': lejek['dopasowanych'],
            'srednia_wycena': lejek['srednia_wycena'],
            'srednia_zamowiona': lejek['srednia_zamowiona'],
            'mediana_dni': lejek['mediana_dni'],
            'mediana_probka': lejek['mediana_probka'],
            'uwaga': _uwaga_lejka(lejek),
            # Opcje selektora i gotowe liczby dla KAŻDEJ z nich — przeglądarka
            # tylko przełącza widok, niczego nie licząc i nie dopytując.
            'wymiary': wymiary_lejka(),
            'domyslny_wymiar': BEZ_PODZIALU,
            'podzial': {nazwa: _wiersze_podzialu_lejka(nazwa, wiersze)
                        for nazwa, wiersze in lejek['podzial'].items()},
        }

    if 'wnioski' in typy and _pole_na_sztywno_dziala(WYMIAR_WNIOSKU_O_KANALE, 'wnioski'):
        # Wnioski liczymy DOPIERO TERAZ, bo czytają gotowe KPI i trend.
        # Wniosek o kanale liczy się po STAŁYM wymiarze — patrz komentarz
        # przy WYMIAR_WNIOSKU_O_KANALE. Idzie przez pamięć, więc gdy na
        # pulpicie jest kafelek kanałów po `order_source`, nie kosztuje nic.
        wiersze_kanalu, _ = _wiersze_wymiaru(WYMIAR_WNIOSKU_O_KANALE, od, do,
                                             LIMITY_KART.get('kanal', 7),
                                             filtr=baza, pamiec=pamiec)
        # Udziały kanałów z poprzedniego okresu — jedyne dodatkowe zapytanie,
        # jakie karta „Statystyki" kosztuje.
        kanal_poprz = wg_wymiaru(WYMIAR_WNIOSKU_O_KANALE, od_poprz, do_poprz,
                                 filtr=baza)
        suma_poprz = sum((w['netto'] for w in kanal_poprz), Decimal('0'))
        udzialy_poprzednie = {
            w['wartosc']: (w['netto'] * 100 / suma_poprz).quantize(Decimal('0.1'))
            for w in kanal_poprz
        } if suma_poprz else {}
        wynik['wnioski'] = wnioski(wynik, wiersze_kanalu, udzialy_poprzednie)

    if porownanie:
        wynik['porownanie'] = _dane_porownania(
            od, do, trend_od, uklad, karty, porownanie,
            licz_kpi=licz_kpi, rozbicie=rozbicie,
            ma_dostawe='dostawa' in typy, pamiec=pamiec, baza=baza)
        wynik['segmenty'].append({
            'id': 'porownanie', 'nazwa': opis_z_etykietami(porownanie),
            'kolor': KOLOR_SEGMENTU_POROWNANIA, 'filtr': zapisz_filtr(porownanie),
        })

    return wynik


def formatuj_liczbe(wartosc, miejsca: int = 0) -> str:
    """Liczba po polsku: spacja na tysiące, przecinek na część dziesiętną.

    Formatujemy na serwerze, bo teksty wniosków powstają tutaj. Przeniesienie
    tego do JavaScriptu oznaczałoby drugie miejsce, w którym trzeba pamiętać
    o polskich separatorach.
    """
    if wartosc is None:
        return '—'
    liczba = Decimal(str(wartosc))
    return f'{liczba:,.{miejsca}f}'.replace(',', ' ').replace('.', ',')


def _z_procentem(wartosc) -> str:
    """Zmiana procentowa ze znakiem, np. '−7,6%'. Minus typograficzny, nie dywiz."""
    if wartosc is None:
        return 'bez porównania'
    znak = '+' if Decimal(str(wartosc)) >= 0 else '−'
    return f'{znak}{formatuj_liczbe(abs(Decimal(str(wartosc))), 1)}%'


# Wymiar, po którym liczy się wniosek „Największy kanał". STAŁY, nie wzięty
# z karty kanałów — z dwóch powodów. Po pierwsze przy własnym układzie karty
# kanałów może w ogóle nie być. Po drugie, i ważniejsze: do 23.09.2026 wniosek
# brał wymiar Z KARTY, więc po przełączeniu jej na „Opiekun" zdanie brzmiało
# „Największy kanał to Anna Makietowa". Słowo „kanał" w zdaniu obiecuje kanał
# sprzedaży i ma go dotrzymać — to piąty przypadek reguły „ta sama etykieta
# znaczy wszędzie to samo" w tym projekcie.
WYMIAR_WNIOSKU_O_KANALE = 'order_source'


def _wniosek_kanal(wiersze_kanalu, udzialy_poprzednie) -> Dict[str, str]:
    """Największy kanał i jego udział wobec poprzedniego okresu.

    Dostaje WIERSZE, a nie cały payload: karta kanałów może nie istnieć,
    a wniosek ma działać i tak.
    """
    if not wiersze_kanalu:
        return {'tekst': 'Brak zamówień w wybranym okresie — nie ma z czego liczyć '
                         'udziałów kanałów.',
                'kontekst': 'wybrany okres', 'akcent': 'accent'}

    czolo = wiersze_kanalu[0]
    teraz = formatuj_liczbe(czolo['udzial'], 1)
    # Poprzedni okres to OSOBNE zapytanie — kanał szukamy po grupie bazy,
    # nie po napisie (patrz `aggregates.dopasuj_wiersze`).
    (para,), _ = dopasuj_wiersze(
        [czolo['wartosc']],
        [{'wartosc': wartosc, 'udzial': udzial}
         for wartosc, udzial in udzialy_poprzednie.items()])
    wczesniej = para['udzial'] if para else None
    if wczesniej is None:
        tekst = (f"Największy kanał to {czolo['etykieta']} — {teraz}% przychodu. "
                 f"Dla poprzedniego okresu brak danych porównawczych.")
    else:
        tekst = (f"Największy kanał to {czolo['etykieta']} — {teraz}% przychodu "
                 f"wobec {formatuj_liczbe(wczesniej, 1)}% w poprzednim okresie.")
    return {'tekst': tekst, 'kontekst': 'wybrany okres wobec poprzedniego',
            'akcent': 'accent'}


def _wniosek_cena(dane) -> Dict[str, str]:
    """Cena za m3 w okresie na tle najlepszego miesiąca bieżącego roku.

    ZDANIE NIE MOŻE PRZECZYĆ SAMO SOBIE (weryfikacja partii E, Z2/D2). Do
    23.09.2026 cena miesiąca szła bez zaokrąglenia, a cena okresu z KPI —
    zaokrąglona do grosza. Gdy okres był miesiącem rekordowym, a KPI
    zaokrąglało w dół, wychodziło „20 133 zł, poniżej rekordu roku: 20 133 zł
    w WRZ" (15 takich zdań na 80 prób na kopii produkcji). Teraz obie strony
    liczy `cena_netto_za_m3`, więc miesiąc okresu wygrywa sam ze sobą remisem.

    Drugi przypadek tej samej sprzeczności: rekordem jest inny miesiąc, droższy
    o grosze. Zdanie pokazuje złotówki, więc „17 000 zł, poniżej rekordu roku:
    17 000 zł" też czyta się jak błąd — mówimy wtedy „na poziomie rekordu".
    """
    cena = dane['kpi']['cena_za_m3']
    etykiety = dane['trend']['etykiety']

    najlepszy_indeks, najlepsza_cena = None, None
    for indeks, punkt in enumerate(dane['trend']['biezacy']):
        if not punkt['objetosc']:
            continue
        cena_miesiaca = cena_netto_za_m3(punkt['netto'], punkt['objetosc'])
        if najlepsza_cena is None or cena_miesiaca > najlepsza_cena:
            najlepszy_indeks, najlepsza_cena = indeks, cena_miesiaca

    if najlepsza_cena is None or not cena:
        return {'tekst': 'W wybranym okresie nie ma objętości, więc ceny za m³ nie da '
                         'się policzyć — sprawdź, czy zamówienia to nie same usługi.',
                'kontekst': 'wybrany okres', 'akcent': 'teal'}

    nazwa = etykiety[najlepszy_indeks] if najlepszy_indeks < len(etykiety) else '?'
    if cena >= najlepsza_cena:
        tekst = (f"Cena netto za m³ w okresie to {formatuj_liczbe(cena)} zł — "
                 f"najwyższa w tym roku.")
    elif formatuj_liczbe(cena) == formatuj_liczbe(najlepsza_cena):
        tekst = (f"Cena netto za m³ w okresie to {formatuj_liczbe(cena)} zł, "
                 f"na poziomie rekordu roku w {nazwa}.")
    else:
        tekst = (f"Cena netto za m³ w okresie to {formatuj_liczbe(cena)} zł, "
                 f"poniżej rekordu roku: {formatuj_liczbe(najlepsza_cena)} zł w {nazwa}.")
    return {'tekst': tekst, 'kontekst': f'{etykiety[0]}–{etykiety[-1]}' if etykiety else 'rok',
            'akcent': 'teal'}


def _wniosek_srednie(dane) -> Dict[str, str]:
    """Średnie zamówienie zestawione z liczbą zamówień.

    Osobno każda z tych liczb kłamie: rosnąca liczba zamówień przy spadającym
    koszyku wygląda w kafelku na sukces i porażkę naraz. Razem mówią, że zmienia
    się struktura sprzedaży.
    """
    zmiana = dane['kpi']['zmiana']
    kwoty = (f"{formatuj_liczbe(dane['kpi']['srednie_zamowienie'])} zł "
             f"na {formatuj_liczbe(dane['kpi']['zamowienia'])} zamówień")
    # BEZ OKRESU PORÓWNAWCZEGO (partia E, punkt E7) zdanie brzmiało „Średnie
    # zamówienie bez porównania przy liczbie zamówień bez porównania — …".
    # Zestawienie dwóch zmian nie ma wtedy sensu, zostają same liczby okresu.
    if zmiana['srednie_zamowienie'] is None or zmiana['zamowienia'] is None:
        return {'tekst': f'Średnie zamówienie: {kwoty}.', 'kontekst': 'wybrany okres',
                'akcent': 'neutral'}
    tekst = (f"Średnie zamówienie {_z_procentem(zmiana['srednie_zamowienie'])} "
             f"przy liczbie zamówień {_z_procentem(zmiana['zamowienia'])} — {kwoty}.")
    return {'tekst': tekst, 'kontekst': 'wybrany okres wobec poprzedniego',
            'akcent': 'neutral'}


def wnioski(dane: Dict[str, object], wiersze_kanalu,
            udzialy_poprzednie: Dict[object, Decimal]) -> List[Dict[str, str]]:
    """Trzy wnioski karty „Statystyki", liczone z danych już policzonych.

    `dane` to payload z gotowymi `kpi` i `trend`; `wiersze_kanalu` to wiersze
    po WYMIAR_WNIOSKU_O_KANALE (osobno, bo karty kanałów może nie być).

    Funkcja jest czysta — nie dotyka bazy. Dzięki temu da się ją testować bez
    zasiewania zamówień, a dashboard nie płaci za nią ani jednym zapytaniem
    ponad to, które i tak wykonuje `dane_dashboardu`.
    """
    return [
        _wniosek_kanal(wiersze_kanalu, udzialy_poprzednie),
        _wniosek_cena(dane),
        _wniosek_srednie(dane),
    ]


def nazwa_zakresu(od: date, do: date) -> str:
    """Nazwa presetu okresu, np. „bieżący miesiąc". Inaczej „zakres własny"."""
    dzis = dzis_lokalnie()
    if od == dzis.replace(day=1) and do == dzis:
        return 'bieżący miesiąc'
    if od == date(do.year, 1, 1) and do == dzis:
        return 'bieżący rok'
    if od.day == 1 and do == _koniec_miesiaca(od.year, od.month):
        return 'pełny miesiąc'
    return 'zakres własny'


def opis_okresu(od: date, do: date) -> str:
    """Okres po polsku, w formie z makiety: „1–21 wrz 2026"."""
    if od.year == do.year and od.month == do.month:
        return f'{od.day}–{do.day} {MIESIACE_MALE[do.month - 1]} {do.year}'
    if od.year == do.year:
        return (f'{od.day} {MIESIACE_MALE[od.month - 1]} – '
                f'{do.day} {MIESIACE_MALE[do.month - 1]} {do.year}')
    return (f'{od.day} {MIESIACE_MALE[od.month - 1]} {od.year} – '
            f'{do.day} {MIESIACE_MALE[do.month - 1]} {do.year}')


# Ile wartości wchodzi na listę w popoverze filtra. `delivery_method`
# na produkcji ma kilkadziesiąt wariantów wolnego tekstu — lista bez limitu
# byłaby nie do przeczytania, a odpowiedź niepotrzebnie ciężka.
LIMIT_WARTOSCI_FILTRA = 50

# Zdanie o UCIĘTEJ liście — po jednym na każdy porządek, bo każdy ucina co
# innego. Przy porządku po sprzedaży wypada z listy to, co sprzedaje się
# najsłabiej; przy porządku własnym — najstarsze albo największe wartości.
# Napis, który tego nie rozróżnia („Pokazano najważniejsze wartości"), po
# wprowadzeniu porządku chronologicznego zaczął kłamać: obcięte zostały
# NAJSTARSZE daty, a nie najmniej ważne.
#
# Tekst mieszka TUTAJ, a nie w filtr.js — tak samo jak etykiety wartości
# i jednostki, i z tego samego powodu.
_OPISY_UCIECIA: Dict[object, str] = {
    None: ('Pokazano {ile} wartości o najwyższej sprzedaży — {reszta} '
           'o niższej jest poza listą. Zawęź okres, żeby do nich dojść.'),
    Porzadek.MALEJACO: ('Pokazano {ile} najnowszych wartości — {reszta} '
                        'starszych jest poza listą. Zawęź okres, żeby do nich dojść.'),
    Porzadek.ROSNACO: ('Pokazano {ile} najmniejszych wartości — {reszta} '
                       'większych jest poza listą. Zawęź okres, żeby do nich dojść.'),
}


def _w_porzadku_wymiaru(nazwa: str, surowe: List[Dict[str, object]]
                        ) -> List[Dict[str, object]]:
    """Wiersze `wg_wymiaru` ułożone porządkiem WŁASNYM wymiaru, jeśli go ma.

    Bez deklaracji w rejestrze zostaje kolejność z `wg_wymiaru`, czyli malejąco
    po netto — i tak ma zostać dla kanału, opiekuna czy województwa.

    Wartość PUSTA idzie zawsze na koniec: „(brak)" nie ma miejsca ani na osi
    czasu, ani na skali grubości, a na górze listy zajmowałaby miejsce
    wartości, której użytkownik szuka.

    Wolny tekst z BaseLinkera potrafi wpaść do kolumny obok liczby albo daty
    i wtedy porównanie rzuca TypeError — wracamy wtedy do porządku po napisie,
    bo dziwna kolejność jest lepsza niż wyjątek na całym popoverze. Ta sama
    zasada, co w `explorer._kolejnosc_kolumn`.
    """
    porzadek = POLA[nazwa].porzadek
    if porzadek is None:
        return list(surowe)

    puste = [w for w in surowe if w['wartosc'] is None]
    nazwane = [w for w in surowe if w['wartosc'] is not None]
    malejaco = porzadek is Porzadek.MALEJACO
    try:
        nazwane.sort(key=lambda w: w['wartosc'], reverse=malejaco)
    except TypeError:
        nazwane.sort(key=lambda w: str(w['wartosc']), reverse=malejaco)
    return nazwane + puste


def wartosci_wymiaru(nazwa: str, od: date, do: date, filtr=None) -> Dict[str, object]:
    """Wartości wymiaru obecne W DANYCH bieżącego okresu, do listy w filtrze.

    `filtr` to filtr wykluczeń pulpitu (partia E8, punkt 4f): lista
    w popoverze „Dodaj porównanie" liczy zamówienia tak samo jak karty obok —
    wartość, w której po wykluczeniu nic nie zostaje, na liście nie staje,
    a liczniki zgadzają się z liczbami pulpitu. Eksplorator i Arkusz wykluczeń
    nie mają i wołają bez filtra.

    Nie ze słownika, tylko z danych: wartość, której w okresie nie ma, nie ma
    po co być na liście, a słowniki z BaseLinkera i tak są niepełne.

    Kolejność: dla wymiaru BEZ porządku własnego dziedziczymy ją po
    `wg_wymiaru` (malejąco po netto, więc na górze jest to, co użytkownik
    najpewniej chce wybrać), a dla wymiaru z porządkiem własnym — po tym
    porządku (patrz `Pole.porzadek` i `_w_porzadku_wymiaru`).

    Wymiar złożony jest odrzucany: jego wartość to krotka i nie przechodzi
    przez format filtra w adresie (Zadanie 2).
    """
    pole = POLA.get(nazwa)
    if pole is None or not pole.wymiar or pole.skladniki is not None:
        raise ValueError(f"'{nazwa}' nie nadaje się na filtr")

    surowe = _w_porzadku_wymiaru(nazwa, wg_wymiaru(nazwa, od, do, filtr=filtr))
    uciete = len(surowe) > LIMIT_WARTOSCI_FILTRA
    return {
        'wymiar': {'nazwa': nazwa, 'etykieta': pole.etykieta},
        'wartosci': [
            {
                # Pusta wartość to umowa formatu filtra: „brak wartości".
                'wartosc': '' if w['wartosc'] is None else str(w['wartosc']),
                'etykieta': _etykieta_wartosci(nazwa, w['wartosc']),
                'zamowienia': w['zamowienia'],
                # Klucz grupy bazy (kolacja: wielkość liter, diakrytyki,
                # spacja na końcu). Popover zaznacza po nim pole, gdy segment
                # wybrano w innym okresie, w którym baza oddała tę grupę innym
                # zapisem („Kurier" / „kurier"). Liczy go SERWER — przeglądarka
                # tylko porównuje.
                'klucz': ('' if w['wartosc'] is None
                          else str(klucz_grupy(w['wartosc']))),
            }
            for w in surowe[:LIMIT_WARTOSCI_FILTRA]
        ],
        'uciete': uciete,
        # Czego dokładnie brakuje na liście — zdanie składa SERWER, bo tylko on
        # zna porządek, którym ucinał.
        'opis_uciecia': _OPISY_UCIECIA[pole.porzadek].format(
            ile=LIMIT_WARTOSCI_FILTRA,
            reszta=len(surowe) - LIMIT_WARTOSCI_FILTRA) if uciete else '',
    }


# Osiem kolumn panelu miar — dokładnie te z makiety Eksploratora, w tej kolejności.
MIARY_PANELU: Tuple[str, ...] = (
    'netto', 'udzial', 'objetosc', 'zamowienia',
    'srednie_zamowienie', 'cena_za_m3', 'klienci', 'nowi_klienci',
)

# Miary, które wolno postawić w przestawieniu. Tylko addytywne — udział czy
# średnie zamówienie nie sumują się po kolumnach i dawałyby nieprawdę w sumie.
MIARY_PRZESTAWIENIA: Tuple[str, ...] = ('netto', 'objetosc', 'zamowienia')

# NAZWY miar, bez jednostek — te dokłada `etykieta_z_jednostka` z
# JEDNOSTKI_MIAR. Dawniej dwie pozycje niosły tu samą jednostkę zamiast nazwy
# („m³", „zł / m³"), więc kolumna była podpisana raz nazwą, raz jednostką,
# a doklejenie jednostki dałoby „m³ m³".
ETYKIETY_MIAR: Dict[str, str] = {
    'netto': 'Netto', 'udzial': 'Udział', 'objetosc': 'Objętość',
    'zamowienia': 'Zamówienia', 'srednie_zamowienie': 'Śr. zamówienie',
    'cena_za_m3': 'Cena', 'klienci': 'Klienci', 'nowi_klienci': 'Nowi klienci',
    # Miara dymka mapy. Podpisana TUTAJ, razem z pozostałymi — dymek nie ma
    # własnej listy nazw, bo wtedy „Klienci" mogłoby kiedyś znaczyć w nim coś
    # innego niż w kafelku KPI obok. Eksplorator jej nie oferuje (nie ma jej
    # w MIARY_PANELU), bo liczy się z `prod_orders`, a nie ze sprzedaży.
    'w_produkcji': 'W produkcji',
    # Miara „szt." przełącznika kafelków (24.09.2026). „Sztuki", a nie
    # „Ilość" z rejestru: „Ilość" w arkuszu to ilość JEDNEJ pozycji, razem
    # z usługami (88 „sztuk" suszenia to metry sześcienne), a tu jest suma
    # sztuk produktów BEZ usług. Inna wielkość — inna nazwa. Eksplorator jej
    # nie oferuje (nie ma jej w MIARY_PANELU).
    'sztuki': 'Sztuki',
}


def etykieta_z_jednostka(miara: str) -> str:
    """Nazwa miary z jednostką, np. „Netto zł".

    Jedno źródło dla nagłówka kolumny w Eksploratorze, nagłówka eksportu CSV
    i podpisu miary w tytule panelu przestawienia. Spacja jest NIEROZDZIELAJĄCA
    — nagłówek „Śr. zamówienie zł" nie ma się łamać między liczbą a walutą.
    """
    jednostka = JEDNOSTKI_MIAR.get(miara)
    if not jednostka:
        return ETYKIETY_MIAR[miara]
    return f'{ETYKIETY_MIAR[miara]} {jednostka}'


def _przemapuj_etykiety_przestawienia(panel: Dict[str, object], wymiar: str,
                                      kolumny: str) -> None:
    """Etykiety panelu przestawienia tą samą mapą, co etykiety panelu miar.

    `explorer` nie zna ETYKIETY_WARTOSCI i ma nie znać — buduje etykietę
    surowym rzutowaniem wartości na tekst. Bez tego kroku jeden ekran pokazuje
    „Sklep / Ręczne w BL / Allegro" u góry i „shop / personal / allegro" na
    dole (oględziny 22.09.2026), a dla `own_transport` w nagłówkach kolumn —
    angielskie „False".

    Wiersz i kolumna ZBIORCZA („Pozostałe") zostają ze swoją etykietą: nie stoi
    za nimi żadna wartość wymiaru, więc nie ma czego mapować. Wartość pusta
    dostaje „(brak)" tak samo jak w panelu miar, bo robi to `_etykieta_wartosci`.
    """
    from modules.reports import explorer

    for wiersz in panel['wiersze']:
        if wiersz.get('zbiorczy'):
            continue
        wiersz['etykieta'] = _etykieta_wartosci(wymiar, wiersz['wartosc'])

    # Oś miesięczna ma WŁASNE etykiety („wrz", „gru 25") i nie jest wymiarem
    # z rejestru — przemapowanie by je zepsuło.
    if kolumny == explorer.PRZESTAWIENIE_MIESIAC:
        return
    for kolumna in panel['kolumny']:
        # Wartość surowa jest w payloadzie tylko po to, żeby zbudować z niej
        # etykietę; do przeglądarki nie jedzie (klucz kolumny wystarczy).
        surowa = kolumna.pop('wartosc', None)
        if kolumna.get('zbiorcza'):
            continue
        kolumna['etykieta'] = _etykieta_wartosci(kolumny, surowa)


def dane_eksploratora(wymiar: str, kolumny: str, miara: str,
                      od: date, do: date, filtr=None) -> Dict[str, object]:
    """Komplet danych Eksploratora: panel miar + panel przestawienia.

    `filtr` ZAWĘŻA widok (inaczej niż segment porównawczy na dashboardzie,
    który dokłada drugą serię) — dlatego w adresie nazywa się `filtr`, a tam
    `porownanie`. Ta sama nazwa dla dwóch różnych znaczeń byłaby pułapką przy
    kopiowaniu adresów między widokami.
    """
    from modules.reports import explorer

    surowe = wg_wymiaru(wymiar, od, do, filtr=filtr)
    klienci = explorer.klienci_wg_wymiaru(wymiar, od, do, filtr=filtr)
    suma_netto = sum((w['netto'] for w in surowe), Decimal('0'))
    # Liczniki klientów to OSOBNE zapytanie, więc łączymy je z wierszami po
    # GRUPIE bazy, nie po napisie (patrz `aggregates.dopasuj_wiersze`).
    pary_klientow, _ = dopasuj_wiersze(
        [w['wartosc'] for w in surowe],
        [dict(liczby, wartosc=wartosc) for wartosc, liczby in klienci.items()])

    def wiersz(w, liczby_klientow):
        liczby_klientow = liczby_klientow or {'klienci': 0, 'nowi': 0}
        return {
            'wartosc': w['wartosc'],
            'etykieta': _etykieta_wartosci(wymiar, w['wartosc']),
            'netto': w['netto'],
            'udzial': (w['netto'] * 100 / suma_netto).quantize(Decimal('0.1'))
                      if suma_netto else Decimal('0'),
            'objetosc': w['objetosc'],
            'zamowienia': w['zamowienia'],
            'srednie_zamowienie': (w['netto'] / w['zamowienia']).quantize(Decimal('0.01'))
                                  if w['zamowienia'] else None,
            'cena_za_m3': (w['netto'] / w['objetosc']).quantize(Decimal('0.01'))
                          if w['objetosc'] else None,
            'klienci': liczby_klientow['klienci'],
            'nowi_klienci': liczby_klientow['nowi'],
        }

    wiersze = [wiersz(w, para) for w, para in zip(surowe, pary_klientow)]

    suma_objetosc = sum((w['objetosc'] for w in wiersze), Decimal('0'))
    suma_zamowien = sum(w['zamowienia'] for w in wiersze)
    # UWAGA: klientów w wierszu sumy NIE wolno dodać po wierszach — ten sam
    # klient bywa w dwóch kanałach i policzylibyśmy go dwa razy. Liczymy go
    # raz, osobnym zapytaniem bez podziału na wymiar.
    wszyscy = _klienci_okresu(od, do, filtr=filtr)

    suma = {
        'etykieta': 'Razem',
        'netto': suma_netto,
        'udzial': Decimal('100.0') if suma_netto else Decimal('0'),
        'objetosc': suma_objetosc,
        'zamowienia': suma_zamowien,
        'srednie_zamowienie': (suma_netto / suma_zamowien).quantize(Decimal('0.01'))
                              if suma_zamowien else None,
        'cena_za_m3': (suma_netto / suma_objetosc).quantize(Decimal('0.01'))
                      if suma_objetosc else None,
        'klienci': wszyscy['klienci'],
        'nowi_klienci': wszyscy['nowi'],
    }

    panel_przestawienia = explorer.przestawienie(wymiar, kolumny, miara, od, do,
                                                filtr=filtr)
    # Komórki przestawienia to jedna miara powtórzona w kilkunastu kolumnach
    # miesięcy — jednostka ma być podpisana RAZ, w tytule panelu, a nie przy
    # każdej liczbie. `explorer` zna tylko klucz miary, nazwę z jednostką
    # dokładamy tutaj, żeby nie powstało drugie źródło etykiet.
    panel_przestawienia['etykieta_miary'] = etykieta_z_jednostka(miara)
    # Ta sama wartość ma w obu panelach ten sam ZAPIS. Wiersze przestawienia
    # to osobne zapytanie i baza potrafi oddać w nim grupę innym zapisem niż
    # w panelu miar („kurier" wobec „Kurier" — patrz `aggregates.dopasuj_wiersze`),
    # więc wiersz przestawienia bierze zapis swojej grupy z panelu miar. Tak
    # samo kolumna, gdy na osi kolumn stoi ten sam wymiar co w wierszach.
    osie = [[w for w in panel_przestawienia['wiersze'] if not w.get('zbiorczy')]]
    if kolumny == wymiar:
        osie.append([k for k in panel_przestawienia['kolumny'] if not k.get('zbiorcza')])
    for os_przestawienia in osie:
        pary_panelu, _ = dopasuj_wiersze([p['wartosc'] for p in os_przestawienia], surowe)
        for pozycja, para in zip(os_przestawienia, pary_panelu):
            if para is not None:
                pozycja['wartosc'] = para['wartosc']
    # Niezmiennik MIĘDZYPANELOWY: ta sama wartość ma tę samą etykietę w panelu
    # miar, w wierszach przestawienia i w nagłówkach jego kolumn.
    _przemapuj_etykiety_przestawienia(panel_przestawienia, wymiar, kolumny)

    return {
        'okres': {'od': od, 'do': do, 'nazwa': nazwa_zakresu(od, do),
                  'opis': opis_okresu(od, do),
                  'stan_na': teraz_lokalnie().strftime('%H:%M')},
        'wymiar': {'nazwa': wymiar, 'etykieta': POLA[wymiar].etykieta},
        # Kontrolka „Filtr" pokazuje to samo co chip segmentu na dashboardzie —
        # `opis_filtru` zostaje warstwą niżej, z wartością surową.
        'filtr': {'tekst': zapisz_filtr(filtr), 'opis': opis_z_etykietami(filtr)},
        'liczniki': _liczniki_okresu(od, do, filtr=filtr),
        'miary': {'kolejnosc': list(MIARY_PANELU),
                  # Z jednostką: nagłówek eksportu CSV ma mówić to samo, co
                  # nagłówek kolumny na ekranie.
                  'etykiety': {m: etykieta_z_jednostka(m) for m in MIARY_PANELU},
                  'jednostki': {m: JEDNOSTKI_MIAR[m] for m in MIARY_PANELU},
                  'wiersze': wiersze, 'suma': suma},
        'przestawienie': panel_przestawienia,
        'wymiary_dostepne': [{'nazwa': n, 'etykieta': POLA[n].etykieta} for n in wymiary()],
        # Do popovera filtra idą TYLKO wymiary proste — wartość wymiaru
        # złożonego nie przechodzi przez format filtra w adresie.
        'wymiary_filtra': [{'nazwa': n, 'etykieta': POLA[n].etykieta}
                           for n in wymiary_proste()],
        'miary_przestawienia': [{'nazwa': m, 'etykieta': etykieta_z_jednostka(m)}
                                for m in MIARY_PRZESTAWIENIA],
    }


def _klienci_okresu(od: date, do: date, filtr=None) -> Dict[str, int]:
    """Klienci i nowi klienci w okresie, bez podziału na wymiar.

    Zapytanie o „klienci" idzie po `SalesOrder`, więc filtr wchodzi przez
    `warunki_zamowienia` — warunek po polu pozycji trafia tam jako `EXISTS`.
    `COUNT(DISTINCT ...)` i tak nie dałoby się zwielokrotnić, ale reguła jest
    jedna dla całego modułu i nie robimy od niej wyjątków „bo tu nie zaszkodzi".

    „Nowi" NIE liczymy tutaj drugi raz — `analytics.nowi_klienci` jest
    JEDYNYM źródłem tej liczby (patrz komentarz przy tamtej funkcji: dwa
    niezależne zapytania dawały dwa różne wyniki dla tego samego okresu,
    381 na dashboardzie vs 380 w Eksploratorze, przez klienta bez realnego
    zamówienia w `sales_orders`).
    """
    from modules.reports.models_sales import SalesOrder

    klienci = int(
        db.session.query(db.func.count(db.func.distinct(SalesOrder.client_id)))
        .filter(SalesOrder.date_created >= od, SalesOrder.date_created <= do,
                *warunki_zamowienia(filtr))
        .scalar() or 0
    )
    nowi = analytics.nowi_klienci(od, do, filtr=filtr)
    return {'klienci': klienci, 'nowi': nowi}


def _liczniki_okresu(od: date, do: date, filtr=None) -> Dict[str, int]:
    """„423 zamówienia · 700 pozycji" z nagłówka panelu miar.

    Licznik ZAMÓWIEŃ idzie po `SalesOrder` (EXISTS dla pól pozycji), licznik
    POZYCJI po `SalesOrderItem` (warunek wprost) — każdy liczy to, czego
    dotyczy jego nagłówek.
    """
    from modules.reports.models_sales import SalesOrder, SalesOrderItem

    zamowienia = int(
        db.session.query(db.func.count(SalesOrder.id))
        .filter(SalesOrder.date_created >= od, SalesOrder.date_created <= do,
                *warunki_zamowienia(filtr))
        .scalar() or 0
    )
    pozycje = int(
        db.session.query(db.func.count(SalesOrderItem.id))
        .join(SalesOrder, SalesOrderItem.order_id == SalesOrder.id)
        .filter(SalesOrder.date_created >= od, SalesOrder.date_created <= do,
                *warunki_pozycji(filtr))
        .scalar() or 0
    )
    return {'zamowienia': zamowienia, 'pozycje': pozycje}


def do_json(wartosc):
    """Rekurencyjnie zamienia Decimal na float, a daty na ISO.

    `jsonify` nie umie serializować Decimal i wywala się TypeError dopiero
    w trakcie odpowiedzi, czyli po wykonaniu wszystkich zapytań.
    """
    if isinstance(wartosc, Decimal):
        return float(wartosc)
    if isinstance(wartosc, (datetime, date)):
        return wartosc.isoformat()
    if isinstance(wartosc, dict):
        return {klucz: do_json(v) for klucz, v in wartosc.items()}
    if isinstance(wartosc, (list, tuple)):
        return [do_json(v) for v in wartosc]
    return wartosc
