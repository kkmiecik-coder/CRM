# -*- coding: utf-8 -*-
"""Katalog statystyk pulpitu i układ kafelków użytkownika.

CO TU SIEDZI. Lista typów kafelków, które wolno postawić na pulpicie Analizy
sprzedażowej, i opis instancji kafelka — pary (typ, wybrany wymiar). Układ
użytkownika to uporządkowana lista takich instancji; kolejność listy JEST
kolejnością w siatce.

DLACZEGO OSOBNY MODUŁ, A NIE DOPISEK DO analiza_service.py. Tamten plik ma
1300 linii i importuje bazę, Flaska i wszystkie agregaty. Ten importuje
wyłącznie `fields` i standardową bibliotekę (`logging`) — nie Flaska ani
`modules.logging` — więc da się go czytać i testować bez podnoszenia
aplikacji. Ta sama zasada, co przy `fields.py`.

DLACZEGO NIE IMPORTUJEMY TU `analiza_service`. Zadanie 5 każe `analiza_service`
importować ten moduł (dane_dashboardu dostaje listę instancji), więc import
w drugą stronę zamknąłby cykl. Zgodność katalogu z `DOMYSLNE_WYMIARY`
sprawdza TEST, który importuje oba moduły naraz.

INSTANCJA, NIE TYP. Ten sam typ może wystąpić w układzie wiele razy z różnymi
wymiarami — to wprost intencja użytkownika („3× klienci wg, ale z różnymi
»według«"). Dlatego kluczem kafelka w payloadzie i w DOM-ie jest `typ:wymiar`,
a nie sam typ, jak było do 23.09.2026.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import logging

from modules.reports.fields import POLA, wymiary

logger = logging.getLogger('reports.uklad')

# Ile kafelków wolno mieć na pulpicie. Liczba wzięta z pomiaru, nie z sufitu:
# na kopii produkcji (3324 zamówienia, 7938 pozycji) dwadzieścia kafelków
# na najdroższym wymiarze (`konfiguracja`, trzy kolumny) i najszerszym zakresie
# („całość") kosztuje 608 ms, a z włączonym segmentem porównawczym 806 ms.
# Przy 24 to już 746 / 957 ms, czyli ponad sekundę — próg, po którym jedno
# żądanie przestaje być odczuwane jako natychmiastowe. Układ domyślny ma
# dziesięć kafelków (od partii E należności wypadły z niego — punkt E1), więc
# zostaje dziesięć miejsc do zagospodarowania.
#
# To limit TWARDY, egzekwowany przy zapisie (patrz `parsuj_uklad`), a nie tylko
# podpowiedź w interfejsie: endpoint zapisu jest osiągalny dla każdego, kto ma
# dostęp do modułu.
MAKS_KAFELKOW = 20

# PSEUDO-WYMIARY kart kubełkowych. Powtórzone tutaj, a NIE zaimportowane
# z `analiza_service` — ten moduł celowo nie importuje niczego poza `fields`,
# bo Zadanie 5 każe `analiza_service` importować `uklad` i import w drugą
# stronę zamknąłby cykl. Zgodność obu miejsc pilnuje test
# `test_domyslny_wymiar_karty_kubelkowej_to_jej_pseudo_wymiar`.
PSEUDO_LICZBA_ZAMOWIEN = 'liczba_zamowien'
PSEUDO_WIEK_ZAMOWIENIA = 'wiek_zamowienia'


@dataclass(frozen=True)
class TypKafelka:
    """Jeden rodzaj kafelka — to, co widać w modalu „Dodaj statystykę"."""

    klucz: str
    # Nazwa w modalu. NIE jest tytułem karty na pulpicie: cztery karty noszą
    # tam ten sam tytuł „Sprzedaż netto według:", więc lista czterech
    # identycznych pozycji byłaby nie do rozróżnienia. Nazwa mówi, co ta karta
    # pokazuje PONAD słupki.
    nazwa: str
    opis: str
    # 1 albo 2 kolumny siatki. Rozstrzygnięcie użytkownika: wykresy i tabele są
    # dobrane pod swoją szerokość, więc szerokość wynika z typu, a użytkownik
    # zmienia wyłącznie miejsce.
    szerokosc: int = 1
    # Czy instancja niesie wymiar (czyli czy karta ma selektor „według:").
    wymiarowy: bool = False
    domyslny_wymiar: Optional[str] = None
    # Czy wolno mieć więcej niż jedną instancję tego typu.
    wielokrotny: bool = False
    # Dozwolone wymiary. None = WSZYSTKIE z `fields.wymiary()` (tak działa
    # dzisiejszy selektor na dziewięciu kartach). Krotka = tylko te wymienione,
    # i wolno w niej postawić PSEUDO-WYMIAR, którego w rejestrze nie ma.
    #
    # Po co pseudo-wymiar: karty „Klienci według" i „Należności według" mają
    # wartość domyślną, która nie jest kolumną bazy — kubełki po liczbie
    # zamówień i po wieku zamówienia (`analiza_service.LICZBA_ZAMOWIEN`,
    # `WIEK_ZAMOWIENIA`, commit 5206f18). To poprawne wartości zapisanego
    # układu, więc katalog musi je znać.
    #
    # Po co węższa lista: saldo żyje na ZAMÓWIENIU. Grupowanie należności po
    # wymiarze POZYCJI wymagałoby joina z pozycjami i zwielokrotniłoby saldo
    # przez ich liczbę — dokładnie ten błąd 7,58×, od którego zaczął się
    # cały projekt.
    wymiary: Optional[Tuple[str, ...]] = None

    def __post_init__(self):
        # WYŁĄCZNIE SPÓJNOŚĆ SAMEGO WPISU. Żadne sprawdzenie nie pyta tu
        # rejestru pól (`fields.POLA`, `wymiary()`) — do przeglądu gałęzi
        # 23.09.2026 (M7) pytało i jedna zmiana w `fields.py` (pole traci
        # wymiar=True, np. żeby zniknęło z Eksploratora) wywracała IMPORT
        # całej aplikacji: gunicorn nie wstawał, API tabletów hali razem z nim,
        # a `flask migrate` w deploy.sh padał już po `git reset --hard`, bo
        # deploy nie uruchamia testów. Wyjątek wybuchał przy tym w innym pliku
        # niż ten, który ktoś zmienił.
        #
        # Zgodność katalogu z rejestrem pilnują teraz TESTY
        # (tests/test_uklad_katalog.py) — padają przed deployem, a nie
        # na produkcji. Przy starcie aplikacji niezgodny wymiar jest
        # pomijany (`wymiary_typu`, `_uklad_domyslny`) z ostrzeżeniem w logu.
        if self.szerokosc not in (1, 2):
            raise ValueError(f'{self.klucz}: szerokość kafelka to 1 albo 2 kolumny')
        if self.wymiarowy and not self.domyslny_wymiar:
            raise ValueError(f'{self.klucz}: typ wymiarowy musi mieć domyślny wymiar')
        if not self.wymiarowy and self.domyslny_wymiar:
            raise ValueError(f'{self.klucz}: typ bez wymiaru nie ma czym wypełnić '
                             f'domyślnego wymiaru')
        # Bez wymiaru druga instancja pokazuje co do cyfry to samo, co pierwsza,
        # i kosztuje drugi komplet zapytań za zero informacji.
        if not self.wymiarowy and self.wielokrotny:
            raise ValueError(f'{self.klucz}: typ bez wymiaru nie może być wielokrotny')
        if self.wymiary is not None and not self.wymiarowy:
            raise ValueError(f'{self.klucz}: typ bez wymiaru nie ma listy wymiarów')
        if self.wymiary is not None and len(self.wymiary) < 2:
            raise ValueError(f'{self.klucz}: własna lista wymiarów ma mieć co najmniej '
                             f'dwie pozycje — jedna to selektor bez wyboru')
        if self.wymiary is not None and self.domyslny_wymiar not in self.wymiary:
            raise ValueError(f'{self.klucz}: „{self.domyslny_wymiar}" — nie ma go '
                             f'na własnej liście tego typu')


# UWAGA: kolejność wpisów = kolejność pozycji w modalu „Dodaj statystykę".
# Najpierw to, co opisuje cały okres, potem karty wymiarowe, na końcu lejek.
KATALOG: Dict[str, TypKafelka] = {typ.klucz: typ for typ in (
    TypKafelka(
        'kpi', 'Sprzedaż w skrócie',
        'Pięć wskaźników okresu ze zmianą procentową wobec poprzedniego okresu '
        'i wykres miesięczny z nakładką roku poprzedniego.',
        szerokosc=2),
    TypKafelka(
        'wnioski', 'Statystyki',
        'Trzy zdania wyliczone z danych okresu: największy kanał, cena za m³ '
        'na tle roku i średnie zamówienie wobec liczby zamówień.'),
    TypKafelka(
        'kanal', 'Sprzedaż netto z rozbiciem kanału ręcznego',
        'Poziome słupki według wybranego wymiaru, a pod nimi rozbicie zamówień '
        'wystawionych ręcznie w BaseLinkerze na segmenty.',
        wymiarowy=True, domyslny_wymiar='order_source', wielokrotny=True),
    TypKafelka(
        'opiekun', 'Sprzedaż netto z najwyższym średnim zamówieniem',
        'Poziome słupki według wybranego wymiaru i wiersz z najwyższym średnim '
        'zamówieniem — także spośród wartości schowanych w „Pozostałe".',
        wymiarowy=True, domyslny_wymiar='caretaker', wielokrotny=True),
    TypKafelka(
        'mix', 'Objętość i cena za m³',
        'Tabela: objętość w m³ i cena za m³ w każdej wartości wybranego wymiaru.',
        wymiarowy=True, domyslny_wymiar='konfiguracja', wielokrotny=True),
    # KARTA KUBEŁKOWA. Domyślnie pokazuje kubełki po liczbie zamówień
    # (`LICZBA_ZAMOWIEN` z analiza_service) — to NIE jest pole rejestru.
    # Wymiary wzięte z `WYMIARY_KLIENTOW`; test pilnuje, żeby lista nie
    # rozjechała się z serwisem.
    # Opis mówi to, co karta pokazuje od partii E (punkt E2): koło udziału
    # w WARTOŚCI (netto), a pod nim udział % i kwota — nie liczbę klientów.
    TypKafelka(
        'klienci', 'Klienci z konwersją lead → klient',
        'Koło udziału w wartości zamówień (netto) według kubełków liczby '
        'zamówień albo wybranego wymiaru, pod nim udział % i kwota; konwersja '
        'lead → klient i liczba nowych klientów w okresie.',
        wymiarowy=True, domyslny_wymiar=PSEUDO_LICZBA_ZAMOWIEN, wielokrotny=True,
        wymiary=(PSEUDO_LICZBA_ZAMOWIEN, 'client_origin', 'caretaker',
                 'order_source', 'delivery_state')),
    TypKafelka(
        'wojewodztwo', 'Sprzedaż netto z mapą Polski',
        'Kartogram szesnastu województw z dymkiem, gdy wymiarem jest '
        'Województwo; przy każdym innym wymiarze zwykłe słupki.',
        wymiarowy=True, domyslny_wymiar='delivery_state', wielokrotny=True),
    # KARTA KUBEŁKOWA. Domyślnie kubełki wieku zamówienia (`WIEK_ZAMOWIENIA`).
    # Lista wymiarów zawiera WYŁĄCZNIE kolumny poziomu ZAMÓWIENIA — patrz
    # komentarz przy `TypKafelka.wymiary`.
    TypKafelka(
        'naleznosci', 'Należności z ostrzeżeniem o saldzie',
        'Kubełki wieku zamówienia albo przekrój po wybranym wymiarze, '
        'ostrzeżenie o zamówieniach starszych niż 90 dni, które wciąż mają '
        'status „W produkcji", i osobno nadpłaty.',
        wymiarowy=True, domyslny_wymiar=PSEUDO_WIEK_ZAMOWIENIA, wielokrotny=True,
        wymiary=(PSEUDO_WIEK_ZAMOWIENIA, 'caretaker', 'order_source',
                 'current_status', 'payment_method')),
    TypKafelka(
        'wykonczenie', 'Sprzedaż netto z pierścieniem udziałów',
        'Pierścień udziałów w sprzedaży netto według wybranego wymiaru, '
        'z największym udziałem w środku i legendą w złotych; pod nim, tylko '
        'na wymiarze Wykończenie, cena za m³ z wykończeniem wobec surowego.',
        wymiarowy=True, domyslny_wymiar='finish_state', wielokrotny=True),
    TypKafelka(
        'dostawa', 'Dostawa z kosztem kuriera',
        'Poziome słupki według wybranego wymiaru i suma kosztu kuriera '
        'pobranego od klienta.',
        wymiarowy=True, domyslny_wymiar='delivery_method', wielokrotny=True),
    TypKafelka(
        'lejek', 'Lejek wycena → zamówienie',
        'Pięć stopni od wyceny do realizacji, z własnym selektorem podziału '
        'po atrybutach wyceny.'),
)}


@dataclass(frozen=True)
class Instancja:
    """Jeden kafelek na pulpicie: typ plus wybrany wymiar."""

    typ: str
    wymiar: Optional[str] = None

    @property
    def klucz(self) -> str:
        """Tożsamość kafelka w payloadzie i w DOM-ie.

        Do 23.09.2026 kluczem był sam typ, bo kart było jedenaście i każda
        występowała raz. Odkąd ten sam typ może wystąpić kilka razy z różnymi
        wymiarami, sam typ przestał identyfikować kafelek.

        Klucz jest STABILNY wobec przestawiania — nie zawiera pozycji. Dzięki
        temu przeniesienie kafelka nie zrywa powiązania między payloadem
        a węzłem DOM-u, który ten payload wypełnia.
        """
        return self.typ if self.wymiar is None else f'{self.typ}:{self.wymiar}'


def _domyslna_instancja(klucz: str) -> Instancja:
    typ = KATALOG[klucz]
    return Instancja(klucz, typ.domyslny_wymiar if typ.wymiarowy else None)


def _jest_pseudo_wymiarem(typ: TypKafelka, nazwa: str) -> bool:
    """Pseudo-wymiar = domyślna wartość typu z własną listą, której NIE MA
    w rejestrze pól (kubełki po liczbie zamówień, po wieku zamówienia).
    Rejestr go nie zna, więc zmiana rejestru nie ma jak go unieważnić."""
    return typ.wymiary is not None and nazwa == typ.domyslny_wymiar and nazwa not in POLA


def wymiary_typu(klucz: str) -> List[str]:
    """Wymiary, które wolno postawić na kafelku tego typu.

    Dziewięć typów nie ogranicza niczego i dostaje pełny rejestr. Dwa (karty
    kubełkowe) mają listę własną, z pseudo-wymiarem na pierwszym miejscu.
    Jedno miejsce, z którego korzysta i walidacja zapisu, i odczyt z bazy,
    i modal dodawania, i selektor na karcie.

    Własna lista to CZĘŚĆ WSPÓLNA krotki typu i BIEŻĄCEGO rejestru (plus
    pseudo-wymiar). Gdyby pole straciło w `fields.py` wymiar=True, a krotka
    dalej je wymieniała, zapisana pozycja przeszłaby odczyt i agregat rzuciłby
    ValueError, czyli 500 (przegląd gałęzi, M7). Tak pozycja jest pomijana
    i liczona jako pominięta, zgodnie z R2 planu.
    """
    typ = KATALOG[klucz]
    if not typ.wymiarowy:
        return []
    biezace = wymiary()
    if typ.wymiary is None:
        return biezace
    dozwolone = set(biezace)
    return [nazwa for nazwa in typ.wymiary
            if nazwa in dozwolone or _jest_pseudo_wymiarem(typ, nazwa)]


def _uklad_domyslny(klucze) -> Tuple[Instancja, ...]:
    """Układ domyślny BEZ kafelków, których wymiar przestał być ważny.

    Wyjątek w tym miejscu wywróciłby import całej aplikacji (M7), a pominięcie
    jednego kafelka zostawia działający pulpit. Ostrzeżenie idzie do logu,
    a test `test_uklad_domyslny_ma_wszystkie_dziesiec_kafelkow` pilnuje, żeby
    takie pominięcie nie doszło do produkcji niezauważone.
    """
    wynik = []
    for klucz in klucze:
        instancja = _domyslna_instancja(klucz)
        if instancja.wymiar is not None and instancja.wymiar not in wymiary_typu(klucz):
            logger.warning('Uklad domyslny: pomijam kafelek %s - wymiar %s nie jest juz '
                           'dozwolony dla tego typu (zmiana w rejestrze pol?)',
                           klucz, instancja.wymiar)
            continue
        wynik.append(instancja)
    return tuple(wynik)


# Układ domyślny w kolejności DOM-u: rząd 1 (kpi, wnioski, kanal), rząd 2
# (opiekun, mix, klienci, wojewodztwo), rząd 3 (lejek, wykonczenie, dostawa).
# Dostaje go każdy, kto nigdy nie dotknął trybu edycji, i każdy, kto kliknie
# „Przywróć domyślny".
#
# BEZ „Należności według" (partia E, punkt E1, decyzja prezesa z 23.09.2026,
# doprecyzowana przez użytkownika: „tylko z domyślnego"). Typ ZOSTAJE
# w katalogu — da się go dodać przez „+ Dodaj statystykę" — a serwer liczy
# tylko to, co stoi na pulpicie, więc pierwsze wczytanie strony nie płaci już
# za kubełki wieku, ostrzeżenie o saldzie ani nadpłaty.
UKLAD_DOMYSLNY: Tuple[Instancja, ...] = _uklad_domyslny((
    'kpi', 'wnioski', 'kanal',
    'opiekun', 'mix', 'klienci', 'wojewodztwo',
    'lejek', 'wykonczenie', 'dostawa',
))


def katalog_do_json() -> List[Dict[str, object]]:
    """Katalog w postaci, którą szablon wstawia w atrybut `data-katalog`.

    Modal „Dodaj statystykę" składa się WYŁĄCZNIE z tego — przeglądarka nie ma
    własnej listy typów, własnych nazw ani własnej wiedzy o tym, które wymiary
    wolno wybrać dla którego typu. Ta sama zasada, co przy jednostkach miar
    i etykietach wartości: jedno źródło prawdy, po stronie serwera.
    """
    return [{'klucz': typ.klucz, 'nazwa': typ.nazwa, 'opis': typ.opis,
             'szerokosc': typ.szerokosc, 'wymiarowy': typ.wymiarowy,
             'wielokrotny': typ.wielokrotny,
             'domyslny_wymiar': typ.domyslny_wymiar,
             'wymiary': wymiary_typu(typ.klucz)}
            for typ in KATALOG.values()]


class BladUkladu(ValueError):
    """Układ przysłany przez przeglądarkę jest nie do przyjęcia.

    Komunikat jest PO POLSKU i trafia wprost na ekran użytkownika (endpoint
    zapisu oddaje go w polu `komunikat`), więc ma mówić, co jest nie tak,
    a nie cytować nazwy pól z kodu.
    """


# Klucze, które wolno postawić w pozycji układu. Każdy inny jest błędem,
# a nie czymś do zignorowania: po cichu pominięta literówka znaczy, że klient
# myśli, że zapisał coś, czego nie zapisał.
_DOZWOLONE_KLUCZE = {'typ', 'wymiar'}

# Ile znaków napisu od klienta wolno wkleić do komunikatu błędu. Dłuższy jest
# nadal czytelny po ucięciu — komunikat ma naprowadzić na literówkę, a nie
# przepisywać całe pole z powrotem.
_DLUGOSC_CYTATU = 40

# Ile nazw nieznanych pól wolno wypisać w jednym komunikacie. Klient może
# przysłać słownik z dowolną liczbą kluczy (JSON nie ogranicza) — komunikat
# ma naprowadzić na literówkę, a nie stać się drugą kopią przysłanego
# payloadu.
_MAKS_NIEZNANYCH_W_KOMUNIKACIE = 3


def _cytuj(wartosc: object) -> str:
    """Wartość gotowa do wklejenia w komunikat błędu dla człowieka.

    Napis wraca w cudzysłowie, ucięty do `_DLUGOSC_CYTATU` znaków. Coś innego
    niż napis (None, liczba, lista, słownik) NIE trafia do treści wprost —
    komunikat ma być stałym zdaniem, a nie echem fragmentu JSON-a, który
    klient sam wysłał.
    """
    if not isinstance(wartosc, str):
        return 'podana wartość'
    if len(wartosc) > _DLUGOSC_CYTATU:
        wartosc = wartosc[:_DLUGOSC_CYTATU] + '…'
    return f'„{wartosc}"'


def _rozpoznaj(pozycja: dict) -> Tuple[Optional[TypKafelka], object, bool]:
    """(typ, wymiar, wymiar_pasuje) rozpoznane z jednej pozycji układu.

    WSPÓLNE dla `parsuj_uklad` i `uklad_z_bazy` — obie funkcje rozpoznają typ
    i wymiar po dokładnie tych samych warunkach, różni je wyłącznie reakcja
    na brak rozpoznania (wyjątek z komunikatem kontra licznik pominiętych).

    `typ` jest `None`, gdy `typ` pozycji nie jest znaną statystyką — reszta
    krotki jest wtedy nieistotna. Dla typu wymiarowego `wymiar_pasuje` mówi,
    czy `wymiar` pozycji jest jednym z dozwolonych dla NIEGO (lista typu, nie
    cały rejestr — patrz `wymiary_typu`). Dla typu bez wymiaru `wymiar_pasuje`
    jest zawsze `True`; co zrobić z ewentualną wartością `wymiar` w tym
    wypadku (odrzucić czy zignorować) rozstrzyga wołający.
    """
    nazwa_typu = pozycja.get('typ')
    if not isinstance(nazwa_typu, str) or nazwa_typu not in KATALOG:
        return None, None, False
    typ = KATALOG[nazwa_typu]
    wymiar = pozycja.get('wymiar')
    if typ.wymiarowy:
        wymiar_pasuje = isinstance(wymiar, str) and wymiar in set(wymiary_typu(nazwa_typu))
    else:
        wymiar_pasuje = True
    return typ, wymiar, wymiar_pasuje


def parsuj_uklad(dane: object) -> List[Instancja]:
    """Układ z ciała żądania. Rzuca `BladUkladu` z komunikatem dla człowieka.

    Kształt wejścia: `{"uklad": [{"typ": "kanal", "wymiar": "order_source"}, ...]}`.
    Obiekt, nie goła lista — goła tablica na najwyższym poziomie żądania jest
    znanym problemem bezpieczeństwa, a obiekt zostawia miejsce na kolejne pola
    bez zmiany kontraktu.

    Walidacja jest rozpisana na osobne warunki celowo. Przegląd Planu B znalazł
    trzy błędy dające 500 i wszystkie trzy siedziały w walidacji wejścia.
    """
    if not isinstance(dane, dict) or 'uklad' not in dane:
        raise BladUkladu('W żądaniu brakuje pola „uklad" z listą kafelków.')
    pozycje = dane['uklad']
    if not isinstance(pozycje, list):
        raise BladUkladu('Pole „uklad" ma być listą kafelków.')
    if len(pozycje) > MAKS_KAFELKOW:
        raise BladUkladu(f'Na pulpicie mieści się najwyżej {MAKS_KAFELKOW} kafelków, '
                         f'a przysłano {len(pozycje)}.')

    uklad: List[Instancja] = []
    widziane_klucze = set()

    for numer, pozycja in enumerate(pozycje, start=1):
        if not isinstance(pozycja, dict):
            raise BladUkladu(f'Kafelek nr {numer} nie jest poprawnym opisem kafelka.')
        nieznane = set(pozycja) - _DOZWOLONE_KLUCZE
        if nieznane:
            # `_cytuj` na KAŻDEJ nazwie: klucz słownika w JSON zawsze jest
            # napisem, ale ta sama funkcja co przy `typ`/`wymiar` ucina go do
            # 40 znaków i jest odporna, gdyby kiedyś do tej ścieżki trafiło
            # coś innego. Sortujemy CYTOWANE napisy, nie surowe klucze —
            # `_cytuj` nienapisów zwraca stały tekst „podana wartość", więc
            # sortowanie surowych kluczy różnych typów mogłoby się wywalić.
            cytowane = sorted(_cytuj(nazwa) for nazwa in nieznane)
            widoczne = cytowane[:_MAKS_NIEZNANYCH_W_KOMUNIKACIE]
            ile_pominietych = len(cytowane) - len(widoczne)
            dopisek = f' i {ile_pominietych} innych' if ile_pominietych else ''
            raise BladUkladu(f'Kafelek nr {numer} ma nieznane pola: '
                             f'{", ".join(widoczne)}{dopisek}.')

        nazwa_typu = pozycja.get('typ')
        typ, wymiar, wymiar_pasuje = _rozpoznaj(pozycja)
        if typ is None:
            raise BladUkladu(f'Kafelek nr {numer}: {_cytuj(nazwa_typu)} nie jest znaną '
                             f'statystyką.')

        if typ.wymiarowy:
            # Lista TYPU, nie cały rejestr. Karta należności przyjmuje wyłącznie
            # kolumny poziomu zamówienia: saldo żyje na zamówieniu, więc join
            # z pozycjami zwielokrotniłby je przez ich liczbę. Karty kubełkowe
            # przyjmują dodatkowo swój pseudo-wymiar, którego w rejestrze nie ma.
            if not wymiar_pasuje:
                raise BladUkladu(f'Kafelek „{typ.nazwa}": {_cytuj(wymiar)} nie jest '
                                 f'wymiarem, po którym ta statystyka da się '
                                 f'pogrupować.')
        else:
            if wymiar is not None:
                raise BladUkladu(f'Kafelek „{typ.nazwa}" nie ma wymiaru do wyboru.')

        instancja = Instancja(typ.klucz, wymiar if typ.wymiarowy else None)
        if instancja.klucz in widziane_klucze:
            # Dwa identyczne kafelki pokazują identyczne liczby i kosztują
            # podwójnie. Typ jednokrotny łapie się w ten sam warunek, bo jego
            # klucz nie zawiera wymiaru.
            raise BladUkladu(f'Kafelek „{typ.nazwa}" jest już na pulpicie.')
        widziane_klucze.add(instancja.klucz)
        uklad.append(instancja)

    return uklad


def uklad_do_json(uklad) -> List[Dict[str, Optional[str]]]:
    """Układ w postaci zapisywanej w kolumnie `reports_dashboard_layouts.uklad`.

    `wymiar` jest wypisywany ZAWSZE, także gdy jest `None` — dzięki temu
    zapisany dokument ma jeden kształt i nie trzeba zgadywać, czy brak klucza
    znaczy „bez wymiaru", czy „stary zapis".
    """
    return [{'typ': i.typ, 'wymiar': i.wymiar} for i in uklad]


def uklad_z_bazy(surowe: object) -> Tuple[List[Instancja], int]:
    """(instancje, liczba pominiętych) z tego, co leży w kolumnie.

    ODCZYT JEST WYROZUMIAŁY, w przeciwieństwie do zapisu. Powód: katalog i
    rejestr pól mogą się zmienić po tym, jak użytkownik zapisał układ — pole
    traci `wymiar=True`, typ karty znika. Układ nie może się przez to wywalić
    ani zniknąć: pozycje nie do rozpoznania są POMIJANE W RENDERZE, ale NIE
    kasowane z bazy. Wiersz przepisuje się dopiero wtedy, gdy użytkownik SAM
    zapisze układ — bo pole może wrócić, a zniszczenie cudzego układu przy
    przejściowej zmianie rejestru jest gorsze niż jego przycięcie.

    Liczba pominiętych jedzie do payloadu i zamienia się w jedno bursztynowe
    zdanie na pasku. Ciche przycięcie byłoby dla użytkownika nieodróżnialne
    od zgubienia układu.

    Limitu `MAKS_KAFELKOW` odczyt NIE egzekwuje: gdyby limit kiedyś spadł,
    egzekwowanie go przy odczycie zabrałoby ludziom kafelki bez ich decyzji.

    NIC NIE ZNIKA PO CICHU. Dwa źródła dają dziś zapisanej pozycji ten sam
    klucz instancji: ręczna edycja bazy (dosłownie ten sam wiersz dwa razy)
    i typ, który przestał być wymiarowy — dwie zapisane pozycje z różnymi
    wymiarami tego samego typu dają po utracie `wymiarowy=True` dokładnie tę
    samą `Instancja(typ)`. Druga i każda kolejna pozycja o kluczu, który już
    wystąpił, jest POMIJANA i liczona — układ nigdy nie oddaje dwóch kafelków
    o tym samym kluczu.

    Wartość kolumny, która NIE JEST listą, jest anomalią wartą zalogowania
    i liczy się jako jedna pominięta pozycja. Dotyczy to także `None`:
    kolumna jest NOT NULL, więc `None` przychodzi wyłącznie z dokumentu JSON
    `null`, czyli z ręcznej edycji bazy. Do przeglądu gałęzi (D3) dawał po
    cichu pusty pulpit bez śladu. „Brak wiersza" to coś innego i do tej
    funkcji nie dochodzi — obsługuje go `uklad_service.uklad_uzytkownika`
    (układ domyślny).
    """
    if not isinstance(surowe, list):
        # `logging.Logger.warning` (stdlib) nie przyjmuje dowolnych kwargs jak
        # `StructuredLogger` — kontekst wchodzi przez %-formatowanie w treści.
        logger.warning('Kolumna ukladu w bazie nie jest lista - zwracam pusty uklad '
                       '(typ_wartosci=%s)', type(surowe).__name__)
        return [], 1

    uklad: List[Instancja] = []
    pominietych = 0
    widziane_klucze = set()

    for pozycja in surowe:
        if not isinstance(pozycja, dict):
            pominietych += 1
            continue
        # `isinstance(..., str)` PRZED `in`: lista albo słownik w kolumnie JSON
        # (ręczna edycja bazy) jest niehaszowalny i `in KATALOG` rzuciłby
        # TypeError — czyli 500 zamiast pominięcia pozycji. Warunek siedzi
        # w `_rozpoznaj`, tej samej funkcji, której używa zapis.
        typ, wymiar, wymiar_pasuje = _rozpoznaj(pozycja)
        if typ is None or not wymiar_pasuje:
            pominietych += 1
            continue
        if not typ.wymiarowy:
            wymiar = None
        instancja = Instancja(typ.klucz, wymiar)
        if instancja.klucz in widziane_klucze:
            # Powtórzony klucz — patrz akapit „NIC NIE ZNIKA PO CICHU" wyżej.
            pominietych += 1
            continue
        widziane_klucze.add(instancja.klucz)
        uklad.append(instancja)

    return uklad, pominietych
