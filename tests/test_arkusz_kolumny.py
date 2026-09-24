# -*- coding: utf-8 -*-
"""Rejestr kolumn arkusza, okno dat i formatowanie wartosci.

Czyste funkcje — zero bazy, zero HTTP. Blok importow „rejestr mapperow"
jest mimo to potrzebny, bo import czegokolwiek z modules.reports ciagnie
modules/reports/__init__.py -> routers.py -> modules.users.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import date, datetime
from decimal import Decimal

import pytest

from modules.reports.arkusz_service import (
    KOLUMNY_DOMYSLNE, MAKS_DNI_OKNA, PRESETY_OKNA, RODZAJE,
    etykieta_okna, kolumna_arkusza, kolumny_arkusza, parsuj_okno, sformatuj,
)
from modules.reports.fields import POLA
from modules.reports.service import STATUSY_BASELINKER

from modules.calculator.models import (  # noqa: F401 — rejestr mapperów
    Quote, QuoteItem, QuoteItemDetails, Price, Multiplier,
    FinishingOption, EdgeOption, CalculatorSetting, QuoteCounter, QuoteLog,
)
from modules.clients.models import Client  # noqa: F401 — rejestr mapperów
import modules.quotes.models  # noqa: F401 — rejestr mapperów


# ===== rejestr kolumn ==================================================

def test_arkusz_pomija_wymiar_zlozony_i_bierze_reszte_rejestru():
    nazwy = [k['nazwa'] for k in kolumny_arkusza()]
    assert 'konfiguracja' not in nazwy
    assert len(nazwy) == len(POLA) - 1 == 55


def test_kolejnosc_kolumn_jest_kolejnoscia_rejestru():
    nazwy = [k['nazwa'] for k in kolumny_arkusza()]
    oczekiwane = [n for n, p in POLA.items() if p.skladniki is None]
    assert nazwy == oczekiwane
    assert nazwy[0] == 'date_created'


def test_kazda_kolumna_ma_rodzaj_z_czterech_dozwolonych():
    for kolumna in kolumny_arkusza():
        assert kolumna['rodzaj'] in RODZAJE, kolumna['nazwa']


@pytest.mark.parametrize('nazwa, metoda', [
    ('delivery_state', 'setOrderFields'),
    ('internal_order_number', 'setOrderFields'),
    ('caretaker', 'setOrderFields'),      # custom_extra_fields idzie ta sama metoda
    ('price_type', 'setOrderFields'),
    ('paid_amount', 'setOrderPayment'),
    ('payment_date', 'setOrderPayment'),
    ('current_status', 'setOrderStatus'),
    ('quantity', 'setOrderProductFields'),
    ('price_gross', 'setOrderProductFields'),
])
def test_kolumny_z_baselinkera_niosa_nazwe_metody_api(nazwa, metoda):
    assert kolumna_arkusza(nazwa)['metoda_api'] == metoda


def test_pola_dodatkowe_niosa_swoj_identyfikator():
    # Opiekun i typ ceny ida setOrderFields, ale do custom_extra_fields[id].
    # Bez identyfikatora serwis zapisu nie wie, gdzie je wlozyc.
    assert kolumna_arkusza('caretaker')['id_pola_bl'] == '105623'
    assert kolumna_arkusza('price_type')['id_pola_bl'] == '106169'
    assert kolumna_arkusza('delivery_state')['id_pola_bl'] is None


def test_kolumny_tylko_crm_nie_maja_metody_api():
    for kolumna in kolumny_arkusza():
        if kolumna['rodzaj'] == 'crm':
            assert kolumna['metoda_api'] is None, kolumna['nazwa']


def test_kolumny_wyliczane_i_produkcyjne_nie_sa_edytowalne():
    for kolumna in kolumny_arkusza():
        if kolumna['rodzaj'] in ('wyliczana', 'produkcja'):
            assert kolumna['edytowalne'] is False, kolumna['nazwa']


def test_kolumny_nieedytowalne_z_rejestru_zostaja_nieedytowalne():
    # date_created, baselinker_order_id i order_source sa z BL, ale rejestr
    # ma na nich edytowalne=False — API ich nie przyjmuje.
    for nazwa in ('date_created', 'baselinker_order_id', 'order_source'):
        assert kolumna_arkusza(nazwa)['edytowalne'] is False


def test_pola_wrazliwe_sa_oznaczone():
    assert kolumna_arkusza('paid_amount')['wrazliwe'] is True
    assert kolumna_arkusza('client_origin')['wrazliwe'] is False


def test_status_jest_wyborem_z_listy_znanych_statusow():
    kolumna = kolumna_arkusza('current_status')
    assert kolumna['typ'] == 'wybor'
    assert set(kolumna['opcje']) == set(STATUSY_BASELINKER.values())
    assert len(kolumna['opcje']) == 18


def test_max_dlugosc_przechodzi_z_rejestru():
    assert kolumna_arkusza('notes')['max_dlugosc'] == 200
    assert kolumna_arkusza('delivery_method')['max_dlugosc'] == 30
    assert kolumna_arkusza('client_origin')['max_dlugosc'] is None


@pytest.mark.parametrize('nazwa, typ', [
    ('customer_name', 'tekst'),
    ('paid_amount', 'kwota'),
    ('quantity', 'liczba'),
    ('date_created', 'data'),
    ('payment_date', 'data'),
    ('own_transport', 'logiczna'),
    ('total_volume', 'objetosc'),
    ('gluing_done_at', 'znacznik'),
    ('lead_time_days', 'liczba'),
])
def test_typ_kolumny_bierze_sie_z_modelu_albo_z_jawnej_mapy(nazwa, typ):
    assert kolumna_arkusza(nazwa)['typ'] == typ


def test_kolumny_niosace_przyblizenie_maja_podpowiedz():
    # payment_date przy imporcie to data POTWIERDZENIA zamowienia, nie data
    # wplaty — BaseLinker nie zwraca tej drugiej w getOrders. Uzytkownik
    # musi to widziec, zanim zacznie na tej kolumnie budowac raport.
    podpowiedz = kolumna_arkusza('payment_date')['podpowiedz']
    assert podpowiedz and 'przybliżona' in podpowiedz
    assert 'datę potwierdzenia' in podpowiedz
    assert kolumna_arkusza('paid_amount')['podpowiedz']
    assert kolumna_arkusza('customer_name')['podpowiedz'] is None


def test_kolumny_liczbowe_sa_oznaczone_do_wyrownania_i_monospace():
    assert kolumna_arkusza('paid_amount')['liczbowa'] is True
    assert kolumna_arkusza('quantity')['liczbowa'] is True
    assert kolumna_arkusza('customer_name')['liczbowa'] is False


def test_nieznana_kolumna_rzuca_keyerror():
    with pytest.raises(KeyError):
        kolumna_arkusza('nie_ma_takiej')


def test_domyslny_zestaw_kolumn_odwzorowuje_makiete():
    # Makieta Arkusz.dc.html, blok <thead>. Trzy rozne miejsca od makiety,
    # kazde uzasadnione w planie: „Wymiary cm" to u nas trzy osobne kolumny
    # (kazda edytowalna z osobna), a „Cena netto" jest kolumna WYLICZANA,
    # nie z BaseLinkera.
    assert KOLUMNY_DOMYSLNE == (
        'date_created', 'baselinker_order_id', 'customer_name', 'delivery_state',
        'caretaker', 'client_origin', 'wood_species', 'technology', 'wood_class',
        'length_cm', 'width_cm', 'thickness_cm', 'quantity', 'price_net',
        'value_net', 'total_volume', 'paid_amount', 'paid_cash', 'gluing_done_at',
    )
    assert set(KOLUMNY_DOMYSLNE) <= set(POLA)


def test_kolumna_niesie_jednostke_z_rejestru_pol():
    # `Pole.jednostka` dolozony rownolegle do tego zadania (fields.py, poza
    # tym planem) — arkusz ma podac ja przegladarce razem z reszta opisu
    # kolumny, zeby nagłówek mógł pokazać „zł”/„m³” obok etykiety, tak jak
    # robi to dashboard. Formatowanie liczby i tak liczy sie na serwerze —
    # to jest wylacznie informacja, nie mechanizm.
    assert kolumna_arkusza('paid_amount')['jednostka'] == 'zł'
    assert kolumna_arkusza('total_volume')['jednostka'] == 'm³'
    assert kolumna_arkusza('customer_name')['jednostka'] is None


# ===== okno dat ========================================================

def test_domyslne_okno_to_biezacy_miesiac():
    from modules.reports.analiza_service import dzis_lokalnie
    od, do, preset = parsuj_okno({})
    dzis = dzis_lokalnie()
    assert od == dzis.replace(day=1)
    assert do == dzis
    assert preset == 'miesiac'


@pytest.mark.parametrize('preset', PRESETY_OKNA)
def test_kazdy_preset_okna_daje_poprawny_zakres(preset):
    from modules.reports.analiza_service import dzis_lokalnie
    od, do, zwrocony = parsuj_okno({'okno': preset})
    assert zwrocony == preset
    assert od <= do == dzis_lokalnie()


def test_preset_calosc_siega_2025_roku():
    # Dane zaczynaja sie 2025-05-05. „Calosc" ma je objac, ale nie siegac
    # w nieskonczonosc — MAKS_DNI_OKNA jest twarda granica.
    od, do, _ = parsuj_okno({'okno': 'calosc'})
    assert od <= date(2025, 5, 5)
    assert (do - od).days <= MAKS_DNI_OKNA


def test_okno_z_jawnymi_datami_wygrywa_z_presetem():
    od, do, preset = parsuj_okno({'od': '2026-03-01', 'do': '2026-03-31'})
    assert (od, do) == (date(2026, 3, 1), date(2026, 3, 31))
    assert preset == 'wlasne'


@pytest.mark.parametrize('argumenty, fragment', [
    ({'od': 'wczoraj', 'do': '2026-03-31'}, 'RRRR-MM-DD'),
    ({'od': '2026-03-31', 'do': '2026-03-01'}, 'późniejszy'),
    ({'od': '1999-12-31', 'do': '2026-03-01'}, 'wcześniejszy'),
    # Uwaga: brief podawał tu 'dłuższy niż' (rodzaj męski), ale komunikat ma
    # podmiot „okno" (rodzaj nijaki) — poprawna forma to „dłuższe". Zmiana
    # opisana w odchyleniach raportu zadania.
    ({'od': '2000-01-01', 'do': '2026-03-01'}, 'dłuższe niż'),
    ({'okno': 'dekada'}, 'nie jest zakresem'),
    ({'od': '2026-03-01'}, 'oba pola'),
])
def test_okno_odrzuca_zle_parametry(argumenty, fragment):
    with pytest.raises(ValueError) as blad:
        parsuj_okno(argumenty)
    assert fragment in str(blad.value)


def test_etykieta_okna_dla_presetow():
    assert etykieta_okna(date(2026, 9, 1), date(2026, 9, 22), 'miesiac') == 'Wrzesień 2026'
    assert etykieta_okna(date(2026, 7, 1), date(2026, 9, 22), 'kwartal') == 'III kwartał 2026'
    assert etykieta_okna(date(2026, 1, 1), date(2026, 9, 22), 'rok') == 'Rok 2026'
    assert etykieta_okna(date(2025, 1, 1), date(2026, 9, 22), 'calosc') == 'Cała historia'


def test_etykieta_wlasnego_zakresu_uzywa_opisu_z_dashboardu():
    # Jedno zrodlo prawdy o opisie okresu: ten sam napis, ktory pokazuje
    # pasek dashboardu.
    from modules.reports.analiza_service import opis_okresu
    od, do = date(2026, 3, 1), date(2026, 3, 15)
    assert etykieta_okna(od, do, 'wlasne') == opis_okresu(od, do)


# ===== formatowanie ====================================================

def test_kwota_ma_polskie_separatory_i_dwa_miejsca():
    assert sformatuj(Decimal('8704'), 'kwota') == '8 704,00'
    assert sformatuj(Decimal('1060.75'), 'kwota') == '1 060,75'


def test_objetosc_ma_szesc_miejsc():
    assert sformatuj(Decimal('0.0448'), 'objetosc') == '0,044800'


def test_liczba_calkowita_bez_miejsc_po_przecinku():
    assert sformatuj(3, 'liczba') == '3'


def test_data_i_znacznik_czasu():
    assert sformatuj(date(2026, 9, 18), 'data') == '18.09.2026'
    assert sformatuj(datetime(2026, 9, 18, 7, 42), 'znacznik') == '18.09.2026 07:42'


def test_wartosc_logiczna_po_polsku():
    assert sformatuj(True, 'logiczna') == 'tak'
    assert sformatuj(False, 'logiczna') == 'nie'


@pytest.mark.parametrize('typ', ['tekst', 'kwota', 'liczba', 'data', 'znacznik',
                                 'objetosc', 'logiczna', 'wybor'])
def test_pusta_wartosc_zawsze_daje_myslnik(typ):
    # Makieta pokazuje „—" w wyciszonej szarosci dla brakujacego wojewodztwa
    # i brakujacej daty sklejenia. Jeden znak, jedna regula, wszystkie typy.
    assert sformatuj(None, typ) == '—'


def test_pusty_tekst_tez_daje_myslnik():
    assert sformatuj('', 'tekst') == '—'


def test_tekst_przechodzi_bez_zmian():
    assert sformatuj('śląskie', 'tekst') == 'śląskie'


# ===== poprawka z przegladu Zadania 8 [WAZNE] ============================
# baselinker_order_id jest w modelu db.Integer, wiec bez wyjatku dostaje
# typ 'liczba': serwer formatuje go przez formatuj_liczbe(v, 0), co daje
# spacje co trzy cyfry ('50 854 536') i prawostronne wyrownanie w JS.
# Numer zamowienia w BaseLinkerze nie ma spacji — to JEDYNY identyfikator
# w rejestrze, ktory udaje miare.

def test_numer_zamowienia_bl_jest_tekstem_nie_liczba():
    assert kolumna_arkusza('baselinker_order_id')['typ'] == 'tekst'
    # 'liczbowa' steruje w JS klasami 'm'+'num' (monospace, wyrownanie do
    # prawej) — numer BL ma stac do lewej, tak jak w makiecie Arkusz.dc.html
    # (<td class="m ord">50854536</td>, bez klasy "num").
    assert kolumna_arkusza('baselinker_order_id')['liczbowa'] is False


def test_numer_zamowienia_bl_nie_dostaje_spacji_tysiecznych():
    # Bezposredni dowod na blad: gdyby typ zostal 'liczba', ta asercja
    # dostalaby '50 854 536' zamiast '50854536'.
    typ = kolumna_arkusza('baselinker_order_id')['typ']
    assert sformatuj(50854536, typ) == '50854536'
