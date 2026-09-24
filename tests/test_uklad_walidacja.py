# -*- coding: utf-8 -*-
"""Walidacja układu przychodzącego z przeglądarki i odczyt układu z bazy.

Wejście jest wrogie z założenia: endpoint zapisu jest osiągalny dla każdego,
kto ma dostęp do modułu, a limit dwudziestu kafelków ma znaczenie tylko wtedy,
gdy pilnuje go SERWER. Osobny plik i osobne zadanie, bo trzy błędy krytyczne
Planu B były błędami walidacji wejścia.

CZEGO TE TESTY NIE GWARANTUJĄ: że kolumna w MySQL-u przyjmie to, co zapisujemy.
Jadą na czystym Pythonie, bez bazy. Zgodność z kolumną JSON sprawdza Zadanie 3
(kroki 8–10) na prawdziwym MySQL-u.
"""
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from modules.reports.fields import wymiary
from modules.reports.uklad import (
    KATALOG, MAKS_KAFELKOW, UKLAD_DOMYSLNY, BladUkladu, Instancja,
    parsuj_uklad, uklad_do_json, uklad_z_bazy, wymiary_typu,
)

# Typ wymiarowy BEZ własnej listy (przyjmuje cały rejestr) i typ Z własną listą
# — oba brane Z KATALOGU, nie wpisane z pamięci.
TYP_WYMIAROWY = next(k for k, t in KATALOG.items() if t.wymiarowy and t.wymiary is None)
TYP_KUBELKOWY = next(k for k, t in KATALOG.items() if t.wymiarowy and t.wymiary is not None)
TYP_BEZ_WYMIARU = next(k for k, t in KATALOG.items() if not t.wymiarowy)
WYMIAR = KATALOG[TYP_WYMIAROWY].domyslny_wymiar
INNY_WYMIAR = next(w for w in wymiary() if w != WYMIAR)
PSEUDO = KATALOG[TYP_KUBELKOWY].domyslny_wymiar


def cialo(pozycje):
    return {'uklad': pozycje}


# --- wejście poprawne -------------------------------------------------------

def test_pusty_uklad_jest_poprawny():
    """Usunięcie wszystkich kafelków to świadoma decyzja, nie błąd."""
    assert parsuj_uklad(cialo([])) == []


def test_jedna_instancja_wymiarowa_przechodzi():
    wynik = parsuj_uklad(cialo([{'typ': TYP_WYMIAROWY, 'wymiar': WYMIAR}]))
    assert wynik == [Instancja(TYP_WYMIAROWY, WYMIAR)]


def test_instancja_bez_wymiaru_przechodzi_bez_klucza_wymiar():
    assert parsuj_uklad(cialo([{'typ': TYP_BEZ_WYMIARU}])) == [Instancja(TYP_BEZ_WYMIARU)]


def test_instancja_bez_wymiaru_przechodzi_z_wymiarem_rownym_none():
    """Przeglądarka serializuje brak wartości jako null — to nie jest błąd."""
    assert parsuj_uklad(cialo([{'typ': TYP_BEZ_WYMIARU, 'wymiar': None}])) \
        == [Instancja(TYP_BEZ_WYMIARU)]


def test_ten_sam_typ_dwa_razy_z_roznymi_wymiarami_przechodzi():
    """Sedno całej funkcji — intencja użytkownika wprost."""
    wynik = parsuj_uklad(cialo([
        {'typ': TYP_WYMIAROWY, 'wymiar': WYMIAR},
        {'typ': TYP_WYMIAROWY, 'wymiar': INNY_WYMIAR},
    ]))
    assert len(wynik) == 2


def test_kolejnosc_listy_jest_kolejnoscia_ukladu():
    wynik = parsuj_uklad(cialo([
        {'typ': TYP_WYMIAROWY, 'wymiar': INNY_WYMIAR},
        {'typ': TYP_BEZ_WYMIARU},
        {'typ': TYP_WYMIAROWY, 'wymiar': WYMIAR},
    ]))
    assert [i.typ for i in wynik] == [TYP_WYMIAROWY, TYP_BEZ_WYMIARU, TYP_WYMIAROWY]
    assert wynik[0].wymiar == INNY_WYMIAR


def test_uklad_domyslny_przechodzi_wlasna_walidacje():
    """Strażnik: układ, który wydajemy wszystkim, musi przejść przez tę samą
    bramkę, co układ od użytkownika."""
    wynik = parsuj_uklad(cialo(uklad_do_json(UKLAD_DOMYSLNY)))
    assert list(wynik) == list(UKLAD_DOMYSLNY)


def test_uklad_o_dokladnie_maksymalnej_dlugosci_przechodzi():
    # Rejestr ma 19 wymiarów, czyli mniej niż MAKS_KAFELKOW — jeden typ nie
    # wystarczy do zbudowania 20 RÓŻNYCH instancji. Bierzemy wszystkie typy
    # bez własnej listy, każdy z każdym wymiarem, i ucinamy do limitu.
    typy_bez_listy = [k for k, t in KATALOG.items() if t.wymiarowy and t.wymiary is None]
    pozycje = [{'typ': typ, 'wymiar': w}
               for typ in typy_bez_listy for w in wymiary()][:MAKS_KAFELKOW]
    assert len(pozycje) == MAKS_KAFELKOW
    assert len(parsuj_uklad(cialo(pozycje))) == MAKS_KAFELKOW


# --- wejście złe ------------------------------------------------------------

@pytest.mark.parametrize('dane', [None, [], 'uklad', 42, {'cos': []}])
def test_cialo_bez_klucza_uklad_odrzucone(dane):
    with pytest.raises(BladUkladu):
        parsuj_uklad(dane)


@pytest.mark.parametrize('wartosc', [None, 'kpi', 42, {'typ': 'kpi'}])
def test_uklad_ktory_nie_jest_lista_odrzucony(wartosc):
    with pytest.raises(BladUkladu):
        parsuj_uklad({'uklad': wartosc})


@pytest.mark.parametrize('pozycja', [None, 'kpi', 42, ['kpi']])
def test_pozycja_ktora_nie_jest_slownikiem_odrzucona(pozycja):
    with pytest.raises(BladUkladu):
        parsuj_uklad(cialo([pozycja]))


def test_uklad_dluzszy_niz_limit_odrzucony():
    pozycje = [{'typ': TYP_WYMIAROWY, 'wymiar': w} for w in wymiary()]
    pozycje = (pozycje * 3)[:MAKS_KAFELKOW + 1]
    with pytest.raises(BladUkladu) as blad:
        parsuj_uklad(cialo(pozycje))
    assert str(MAKS_KAFELKOW) in str(blad.value)


def test_nieznany_typ_odrzucony():
    with pytest.raises(BladUkladu) as blad:
        parsuj_uklad(cialo([{'typ': 'wykres-slonca'}]))
    assert 'wykres-slonca' in str(blad.value)


def test_brak_klucza_typ_odrzucony():
    with pytest.raises(BladUkladu):
        parsuj_uklad(cialo([{'wymiar': WYMIAR}]))


def test_typ_wymiarowy_bez_wymiaru_odrzucony():
    """Cicha podstawa wymiaru domyślnego byłaby zapisaniem czegoś innego,
    niż użytkownik wysłał."""
    with pytest.raises(BladUkladu):
        parsuj_uklad(cialo([{'typ': TYP_WYMIAROWY}]))


def test_typ_wymiarowy_z_wymiarem_spoza_rejestru_odrzucony():
    with pytest.raises(BladUkladu) as blad:
        parsuj_uklad(cialo([{'typ': TYP_WYMIAROWY, 'wymiar': 'email'}]))
    assert 'email' in str(blad.value)


def test_pseudo_wymiar_karty_kubelkowej_przechodzi():
    """„Kubełki po liczbie zamówień" nie są polem rejestru, a są poprawną
    wartością zapisanego układu — to jest domyślny stan tej karty."""
    wynik = parsuj_uklad(cialo([{'typ': TYP_KUBELKOWY, 'wymiar': PSEUDO}]))
    assert wynik == [Instancja(TYP_KUBELKOWY, PSEUDO)]


def test_karta_kubelkowa_przyjmuje_wymiar_ze_swojej_listy():
    wlasny = [w for w in wymiary_typu(TYP_KUBELKOWY) if w != PSEUDO][0]
    assert parsuj_uklad(cialo([{'typ': TYP_KUBELKOWY, 'wymiar': wlasny}]))


@pytest.mark.parametrize('typ_kubelkowy',
                         [k for k, t in KATALOG.items() if t.wymiary is not None])
def test_karta_kubelkowa_odrzuca_wymiar_z_rejestru_spoza_swojej_listy(typ_kubelkowy):
    """NAJWAŻNIEJSZY test tego bloku, na KAŻDEJ karcie kubełkowej (`klienci`,
    `naleznosci`) osobno — sparametryzowane po katalogu, a nie wpisane z ręki,
    żeby trzecia taka karta w przyszłości automatycznie dostała to samo
    pokrycie. `wood_species` jest poprawnym wymiarem rejestru, ale na karcie
    należności wymaga joina z pozycjami — a saldo żyje na ZAMÓWIENIU, więc
    join zwielokrotniłby je przez liczbę pozycji. To ten sam błąd 7,58×, od
    którego zaczął się cały projekt. Walidacja sprawdza listę TYPU, nie cały
    rejestr."""
    wymiar_spoza_listy = next(w for w in wymiary()
                              if w not in wymiary_typu(typ_kubelkowy))
    with pytest.raises(BladUkladu) as blad:
        parsuj_uklad(cialo([{'typ': typ_kubelkowy, 'wymiar': wymiar_spoza_listy}]))
    assert wymiar_spoza_listy in str(blad.value)


def test_pseudo_wymiar_jednej_karty_nie_przechodzi_na_drugiej():
    """„wiek_zamowienia" na karcie klientów nie znaczy nic."""
    inny_kubelkowy = [k for k, typ in KATALOG.items()
                      if typ.wymiary is not None and k != TYP_KUBELKOWY]
    if not inny_kubelkowy:
        pytest.skip('tylko jedna karta z własną listą wymiarów')
    with pytest.raises(BladUkladu):
        parsuj_uklad(cialo([{'typ': inny_kubelkowy[0], 'wymiar': PSEUDO}]))


def test_typ_bez_wlasnej_listy_przyjmuje_kazdy_wymiar_rejestru():
    for nazwa in wymiary():
        assert parsuj_uklad(cialo([{'typ': TYP_WYMIAROWY, 'wymiar': nazwa}]))


def test_typ_bez_wymiaru_z_wymiarem_odrzucony():
    """Odrzucamy, a nie ignorujemy: ciche zignorowanie pola znaczy, że klient
    myśli, że zapisał coś, czego nie zapisał."""
    with pytest.raises(BladUkladu):
        parsuj_uklad(cialo([{'typ': TYP_BEZ_WYMIARU, 'wymiar': WYMIAR}]))


def test_typ_jednokrotny_dwa_razy_odrzucony():
    with pytest.raises(BladUkladu) as blad:
        parsuj_uklad(cialo([{'typ': TYP_BEZ_WYMIARU}, {'typ': TYP_BEZ_WYMIARU}]))
    assert KATALOG[TYP_BEZ_WYMIARU].nazwa in str(blad.value)


def test_ta_sama_para_typ_wymiar_dwa_razy_odrzucona():
    """Dwa identyczne kafelki pokazują identyczne liczby i kosztują dwa razy
    tyle zapytań. Modal i tak wyszarza to, co już jest na pulpicie, więc
    użytkownik nie ma jak tu trafić przypadkiem."""
    with pytest.raises(BladUkladu) as blad:
        parsuj_uklad(cialo([{'typ': TYP_WYMIAROWY, 'wymiar': WYMIAR},
                            {'typ': TYP_WYMIAROWY, 'wymiar': WYMIAR}]))
    assert 'już' in str(blad.value)


def test_nieznany_klucz_w_pozycji_odrzucony():
    """Literówka w nazwie pola po cichu zignorowana to klasyczne
    „zapisało się, ale nie to"."""
    with pytest.raises(BladUkladu) as blad:
        parsuj_uklad(cialo([{'typ': TYP_BEZ_WYMIARU, 'szerokosc': 2}]))
    assert 'szerokosc' in str(blad.value)


@pytest.mark.parametrize('zly_typ', [None, 42, ['kpi'], {'a': 1}])
def test_typ_ktory_nie_jest_napisem_odrzucony(zly_typ):
    with pytest.raises(BladUkladu):
        parsuj_uklad(cialo([{'typ': zly_typ}]))


@pytest.mark.parametrize('zly_wymiar', [42, ['caretaker'], {'a': 1}])
def test_wymiar_ktory_nie_jest_napisem_odrzucony(zly_wymiar):
    with pytest.raises(BladUkladu):
        parsuj_uklad(cialo([{'typ': TYP_WYMIAROWY, 'wymiar': zly_wymiar}]))


@pytest.mark.parametrize('zly_typ', [None, 42, ['kpi'], {'a': 1}])
def test_komunikat_typu_niebedacego_napisem_nie_wkleja_surowej_wartosci(zly_typ):
    """Wejście, którego nie da się zacytować sensownie (liczba, lista,
    słownik, None), ma dać STAŁY komunikat — nie echo `repr()` tego, co
    klient wysłał."""
    with pytest.raises(BladUkladu) as blad:
        parsuj_uklad(cialo([{'typ': zly_typ}]))
    tekst = str(blad.value)
    assert repr(zly_typ) not in tekst
    assert str(zly_typ) not in tekst


@pytest.mark.parametrize('zly_wymiar', [42, ['caretaker'], {'a': 1}])
def test_komunikat_wymiaru_niebedacego_napisem_nie_wkleja_surowej_wartosci(zly_wymiar):
    with pytest.raises(BladUkladu) as blad:
        parsuj_uklad(cialo([{'typ': TYP_WYMIAROWY, 'wymiar': zly_wymiar}]))
    tekst = str(blad.value)
    assert repr(zly_wymiar) not in tekst
    assert str(zly_wymiar) not in tekst


def test_komunikat_dlugiego_typu_jest_uciety_do_40_znakow():
    dlugi = 'x' * 80
    with pytest.raises(BladUkladu) as blad:
        parsuj_uklad(cialo([{'typ': dlugi}]))
    tekst = str(blad.value)
    assert dlugi not in tekst
    assert 'x' * 40 in tekst


def test_komunikat_dlugiego_wymiaru_jest_uciety_do_40_znakow():
    dlugi = 'y' * 80
    with pytest.raises(BladUkladu) as blad:
        parsuj_uklad(cialo([{'typ': TYP_WYMIAROWY, 'wymiar': dlugi}]))
    tekst = str(blad.value)
    assert dlugi not in tekst
    assert 'y' * 40 in tekst


def test_komunikat_dlugiej_nazwy_nieznanego_pola_jest_uciety_do_40_znakow():
    """Ten sam wymóg co dla `typ`/`wymiar`, ale dla KLUCZA pozycji: klient
    przysyła słownik, w którym literówka w nazwie pola jest bardzo długa."""
    dlugi = 'z' * 1000
    with pytest.raises(BladUkladu) as blad:
        parsuj_uklad(cialo([{'typ': TYP_BEZ_WYMIARU, dlugi: 1}]))
    tekst = str(blad.value)
    assert dlugi not in tekst
    assert 'z' * 40 in tekst


def test_komunikat_wielu_nieznanych_pol_pokazuje_najwyzej_trzy_i_dopisek():
    """Dziesięć nieznanych pól na jednej pozycji nie ma prawa wkleić w komunikat
    dziesięciu nazw — najwyżej trzy, posortowane, plus dopisek o reszcie."""
    pozycja = {'typ': TYP_BEZ_WYMIARU}
    pozycja.update({f'pole{i}': i for i in range(10)})
    with pytest.raises(BladUkladu) as blad:
        parsuj_uklad(cialo([pozycja]))
    tekst = str(blad.value)

    posortowane = sorted(f'pole{i}' for i in range(10))
    for nazwa in posortowane[:3]:
        assert nazwa in tekst
    for nazwa in posortowane[3:]:
        assert nazwa not in tekst
    assert 'i 7 innych' in tekst


def test_krotki_napis_w_komunikacie_nie_jest_ucinany():
    """Krótki, poprawny napis (przypadek z życia — literówka w nazwie typu)
    ma zostać zacytowany W CAŁOŚCI, tak jak dotychczas."""
    with pytest.raises(BladUkladu) as blad:
        parsuj_uklad(cialo([{'typ': 'wykres-slonca'}]))
    assert '„wykres-slonca"' in str(blad.value)


def test_komunikat_bledu_jest_po_polsku():
    """Komunikat trafia wprost na ekran użytkownika, nie do logu."""
    with pytest.raises(BladUkladu) as blad:
        parsuj_uklad(cialo([{'typ': 'wykres-slonca'}]))
    tekst = str(blad.value)
    assert tekst == tekst.strip() and tekst
    assert any(znak in tekst for znak in 'ąćęłńóśźżĄĆĘŁŃÓŚŹŻ') or ' nie ' in tekst


# --- zapis do bazy i odczyt z bazy ------------------------------------------

def test_uklad_do_json_daje_liste_slownikow():
    surowe = uklad_do_json([Instancja(TYP_WYMIAROWY, WYMIAR), Instancja(TYP_BEZ_WYMIARU)])
    assert surowe == [{'typ': TYP_WYMIAROWY, 'wymiar': WYMIAR},
                      {'typ': TYP_BEZ_WYMIARU, 'wymiar': None}]


def test_zapis_i_odczyt_sa_swoja_odwrotnoscia():
    wejscie = list(UKLAD_DOMYSLNY)
    odczytane, pominietych = uklad_z_bazy(uklad_do_json(wejscie))
    assert odczytane == wejscie
    assert pominietych == 0


def test_odczyt_pomija_nieznany_typ_i_liczy_go():
    """Po zmianie katalogu układ użytkownika nie może się wywalić — ma się
    przyciąć i powiedzieć o tym."""
    odczytane, pominietych = uklad_z_bazy([
        {'typ': TYP_BEZ_WYMIARU, 'wymiar': None},
        {'typ': 'karta-ktorej-juz-nie-ma', 'wymiar': None},
    ])
    assert [i.typ for i in odczytane] == [TYP_BEZ_WYMIARU]
    assert pominietych == 1


def test_odczyt_pomija_nieznany_wymiar_i_liczy_go():
    """Ten sam scenariusz, ale po stronie rejestru pól: ktoś zdjął wymiar=True."""
    odczytane, pominietych = uklad_z_bazy([
        {'typ': TYP_WYMIAROWY, 'wymiar': WYMIAR},
        {'typ': TYP_WYMIAROWY, 'wymiar': 'pole-ktore-przestalo-byc-wymiarem'},
    ])
    assert len(odczytane) == 1
    assert pominietych == 1


@pytest.mark.parametrize('smiec', [None, 'nie-lista', 42, {'uklad': []}])
def test_odczyt_smiecia_z_bazy_daje_pusty_uklad_zamiast_wyjatku(smiec):
    """Kolumna JSON może zawierać cokolwiek, jeśli ktoś ją ruszył ręcznie.
    Pulpit ma się wtedy pokazać pusty, a nie oddać 500. Każda wartość, która
    NIE JEST listą — także `None` — to anomalia warta policzenia jako
    pominięta pozycja.

    `None` do przeglądu gałęzi (D3) był wyjątkiem „kolumna bez wpisanego
    wiersza". Takiego stanu nie ma: kolumna jest NOT NULL, a brak wiersza
    obsługuje serwis (`uklad_uzytkownika` daje wtedy układ domyślny i do tej
    funkcji w ogóle nie dochodzi). `None` bierze się wyłącznie z dokumentu
    JSON `null`, czyli z ręcznej edycji bazy."""
    odczytane, pominietych = uklad_z_bazy(smiec)
    assert odczytane == []
    assert pominietych == 1


def test_odczyt_wartosci_ktora_nie_jest_lista_loguje_ostrzezenie(caplog):
    """Ostrzeżenie ma iść do loggera MODUŁU (`logging.getLogger('reports.uklad')`,
    zwykły `logging.Logger` stdlib — `uklad.py` celowo nie importuje
    `modules.logging`, patrz docstring modułu) — `caplog` łapie je jak każdy
    inny log stdlib. Filtrujemy po nazwie loggera, a nie po samym poziomie:
    inny log ≥ WARNING (np. z `sqlalchemy` albo z pytest) w tym samym teście
    dałby fałszywy zielony wynik."""
    with caplog.at_level(logging.WARNING):
        odczytane, pominietych = uklad_z_bazy(42)
    assert odczytane == []
    assert pominietych == 1
    assert any(rekord.levelno >= logging.WARNING and rekord.name == 'reports.uklad'
              for rekord in caplog.records)


def test_odczyt_wartosci_none_loguje_ostrzezenie(caplog):
    """`None` w kolumnie NOT NULL to dokument JSON `null` z ręcznej edycji
    bazy — uszkodzony wiersz, więc ślad w logu jak przy każdej innej
    nie-liście (przegląd gałęzi, D3)."""
    with caplog.at_level(logging.WARNING):
        odczytane, pominietych = uklad_z_bazy(None)
    assert odczytane == []
    assert pominietych == 1
    assert any(rekord.levelno >= logging.WARNING and rekord.name == 'reports.uklad'
              for rekord in caplog.records)


@pytest.mark.parametrize('pozycja', [
    {'typ': ['kpi'], 'wymiar': None},
    {'typ': {'a': 1}, 'wymiar': None},
    {'typ': TYP_WYMIAROWY, 'wymiar': ['caretaker']},
    {'typ': TYP_WYMIAROWY, 'wymiar': {'a': 1}},
])
def test_odczyt_niehaszowalnej_wartosci_pomija_pozycje_zamiast_wyjatku(pozycja):
    """Lista albo słownik w miejscu napisu (ręczna edycja kolumny) jest
    niehaszowalny — gołe `in KATALOG` rzuciłoby TypeError, czyli 500.
    Pozycja ma zostać pominięta i policzona, jak każda nierozpoznana."""
    odczytane, pominietych = uklad_z_bazy([{'typ': TYP_BEZ_WYMIARU, 'wymiar': None},
                                           pozycja])
    assert odczytane == [Instancja(TYP_BEZ_WYMIARU)]
    assert pominietych == 1


def test_odczyt_pomija_doslownie_powtorzony_wiersz_z_recznej_edycji_bazy():
    """Ręczna edycja bazy potrafi zostawić dwie IDENTYCZNE pozycje. Druga ma
    zostać pominięta i policzona — układ nigdy nie oddaje dwóch kafelków
    o tym samym kluczu, choćby kolumna JSON mówiła inaczej."""
    odczytane, pominietych = uklad_z_bazy([
        {'typ': TYP_BEZ_WYMIARU, 'wymiar': None},
        {'typ': TYP_BEZ_WYMIARU, 'wymiar': None},
    ])
    assert odczytane == [Instancja(TYP_BEZ_WYMIARU)]
    assert pominietych == 1


def test_odczyt_pomija_powtorzony_klucz_po_utracie_wymiarowosci_typu():
    """Drugie źródło duplikatu: typ, który MIAŁ `wymiarowy=True` w chwili
    zapisu (stąd dwie pozycje z różnymi wymiarami), a dziś go nie ma. Obie
    pozycje dają wtedy tę samą `Instancja(typ)` bez wymiaru — druga ma zostać
    pominięta, a nie zdublować klucz w wyniku."""
    odczytane, pominietych = uklad_z_bazy([
        {'typ': TYP_BEZ_WYMIARU, 'wymiar': 'a'},
        {'typ': TYP_BEZ_WYMIARU, 'wymiar': 'b'},
    ])
    assert odczytane == [Instancja(TYP_BEZ_WYMIARU)]
    assert pominietych == 1


def test_odczyt_nie_egzekwuje_limitu_kafelkow():
    """Limit pilnuje ZAPISU. Gdyby pilnował też odczytu, obniżenie limitu
    w przyszłości zabrałoby ludziom kafelki bez żadnej ich decyzji.

    Instancje muszą być RÓŻNE — od 23.09.2026 odczyt pomija powtórzony klucz
    (patrz testy wyżej), więc powtórzenie tej samej listy `* 2` liczyłoby się
    jako połowa pominięta, a nie jako dowód braku limitu. Bierzemy więc typy
    BEZ własnej listy (przyjmują cały rejestr) i mnożymy je przez wszystkie
    wymiary rejestru — to daje więcej niż `MAKS_KAFELKOW` RÓŻNYCH instancji."""
    typy_bez_listy = [k for k, t in KATALOG.items() if t.wymiarowy and t.wymiary is None]
    kombinacje = [(typ, w) for typ in typy_bez_listy for w in wymiary()]
    assert len(kombinacje) > MAKS_KAFELKOW, 'test zaklada wiecej kombinacji niz limit'
    surowe = [{'typ': typ, 'wymiar': w} for typ, w in kombinacje[:MAKS_KAFELKOW + 1]]
    odczytane, pominietych = uklad_z_bazy(surowe)
    assert len(odczytane) == len(surowe)
    assert pominietych == 0
