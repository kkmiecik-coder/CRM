# -*- coding: utf-8 -*-
"""
Runda 2 poprawek logistyki, task 7: mapa kodow pocztowych na wojewodztwa w
PostcodeToStateMapper (modules/reports/utils.py) — brakujace dotad prefiksy
dwucyfrowe (24, 69, 88, 89) i nowe wyjatki trzycyfrowe (POSTCODE_OVERRIDES) dla
prefiksow przecinajacych granice wojewodztw.

To samo zrodlo zasila filtr wojewodztw Logistyki (modules/production/logistics/
wojewodztwa.py — rownowaznosc SQL <-> Python sprawdza osobno
tests/test_logistyka_wojewodztwa.py), kolumne „Region” w eksporcie Routimo i
uzupelnianie wojewodztwa w Analizie sprzedazowej.
"""
import pytest

from modules.reports.utils import PostcodeToStateMapper


def test_zakresy_dwucyfrowe_pokrywaja_00_99_rozlacznie():
    """Sekcja 1 briefu: po zmianie kazdy prefiks 00-99 nalezy do DOKLADNIE jednego
    wojewodztwa w POSTCODE_RANGES — zadnej luki, zadnego nakladania."""
    wlasciciel = {}
    for stan, zakresy in PostcodeToStateMapper.POSTCODE_RANGES.items():
        for start, koniec in zakresy:
            for n in range(start, koniec + 1):
                assert n not in wlasciciel, (
                    'prefiks %02d juz nalezy do %s, a takze do %s' % (n, wlasciciel.get(n), stan))
                wlasciciel[n] = stan
    assert set(wlasciciel) == set(range(100))


def test_kazdy_prefiks_dwucyfrowy_ma_wojewodztwo():
    """Brak None dla zadnego z prefiksow 00-99 (dotychczasowa luka 24/69/88/89 zamknieta)."""
    for n in range(100):
        kod = '%02d-100' % n
        assert PostcodeToStateMapper.get_state_from_postcode(kod) is not None, kod


@pytest.mark.parametrize('kod, oczekiwane', [
    ('24-100', 'Lubelskie'),             # dawna luka — Pulawy, Kraśnik
    ('69-100', 'Lubuskie'),              # dawna luka — Slubice, Sulecin
    ('88-100', 'Kujawsko-Pomorskie'),    # dawna luka — Inowroclaw, Mogilno, Znin
    ('89-500', 'Kujawsko-Pomorskie'),    # dawna luka — Naklo, Szubin, Sepolno, Tuchola
    ('27-400', 'Świętokrzyskie'),        # Starachowice/Ostrowiec/Opatow/Sandomierz
    ('77-300', 'Pomorskie'),             # Bytow, Miastko, Czluchow
    ('26-600', 'Mazowieckie'),           # Radom — domyslne przypisanie prefiksu 26
])
def test_dotychczasowe_luki_i_przestawienia(kod, oczekiwane):
    assert PostcodeToStateMapper.get_state_from_postcode(kod) == oczekiwane


@pytest.mark.parametrize('kod, oczekiwane', [
    ('08-500', 'Lubelskie'),               # Ryki, Deblin
    ('19-300', 'Warmińsko-Mazurskie'),     # Elk
    ('26-110', 'Świętokrzyskie'),          # Skarzysko-Kamienna, Suchedniow
    ('26-300', 'Łódzkie'),                 # Opoczno, Drzewica
    ('27-100', 'Mazowieckie'),             # Ilza
    ('34-300', 'Śląskie'),                 # Zywiec
    ('47-400', 'Śląskie'),                 # Racibórz
    ('67-200', 'Dolnośląskie'),            # Glogow
    ('76-200', 'Pomorskie'),               # Slupsk, Ustka
    ('77-400', 'Wielkopolskie'),           # Zlotow
    ('82-300', 'Warmińsko-Mazurskie'),     # Elblag
    ('89-300', 'Wielkopolskie'),           # Wyrzysk
    ('89-600', 'Pomorskie'),               # Chojnice, Czersk
    ('96-300', 'Mazowieckie'),             # Zyrardow, Mszczonow
    ('96-500', 'Mazowieckie'),             # Sochaczew
    ('38-300', 'Małopolskie'),             # Gorlice, Biecz, Bobowa
])
def test_wyjatki_trzycyfrowe(kod, oczekiwane):
    assert PostcodeToStateMapper.get_state_from_postcode(kod) == oczekiwane


@pytest.mark.parametrize('kod, oczekiwane', [
    ('08-400', 'Mazowieckie'),
    ('19-200', 'Podlaskie'),
    ('34-100', 'Małopolskie'),
    ('47-300', 'Opolskie'),
    ('67-100', 'Lubuskie'),
    ('76-100', 'Zachodniopomorskie'),
    ('96-100', 'Łódzkie'),
    ('82-200', 'Pomorskie'),
    ('38-400', 'Podkarpackie'),            # Krosno
])
def test_sasiedzi_wyjatkow_zostaja_przy_domyslnym_prefiksie(kod, oczekiwane):
    assert PostcodeToStateMapper.get_state_from_postcode(kod) == oczekiwane


@pytest.mark.parametrize('kod', ['35310', '35-310', '35 310'])
def test_formaty_kodu(kod):
    assert PostcodeToStateMapper.get_state_from_postcode(kod) == 'Podkarpackie'


def test_kod_dwucyfrowy_bez_reszty():
    """< 3 cyfry: zawsze zakres dwucyfrowy, wyjatki trzycyfrowe nie moga sie zadzialac."""
    assert PostcodeToStateMapper.get_state_from_postcode('26') == 'Mazowieckie'


@pytest.mark.parametrize('kod', ['', None, 'abc', '3'])
def test_brak_wojewodztwa(kod):
    assert PostcodeToStateMapper.get_state_from_postcode(kod) is None


def test_wyjatki_nie_dublują_wojewodztwa_swojego_prefiksu():
    """Zaden wyjatek nie wskazuje tego samego wojewodztwa co zakres jego dwucyfrowego
    prefiksu — inaczej bylby bez znaczenia."""
    for kod3, cel in PostcodeToStateMapper.POSTCODE_OVERRIDES.items():
        prefix = int(kod3[:2])
        domyslne = None
        for stan, zakresy in PostcodeToStateMapper.POSTCODE_RANGES.items():
            if any(start <= prefix <= koniec for start, koniec in zakresy):
                domyslne = stan
                break
        assert domyslne is not None, kod3
        assert domyslne != cel, '%s: wyjatek i zakres wskazuja to samo wojewodztwo %s' % (kod3, cel)


def test_wartosci_wyjatkow_to_znane_wojewodztwa():
    """Kazda wartosc POSTCODE_OVERRIDES musi byc kluczem POSTCODE_RANGES (ten sam slownik
    zasila filtr wojewodztw Logistyki — nieznany klucz wysypalby _wczytaj())."""
    for kod3, cel in PostcodeToStateMapper.POSTCODE_OVERRIDES.items():
        assert cel in PostcodeToStateMapper.POSTCODE_RANGES, kod3
        assert len(kod3) == 3 and kod3.isdigit(), kod3
