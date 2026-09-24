# -*- coding: utf-8 -*-
"""Mapper surowego zamowienia z BaseLinkera na kolumny sales_*.

Czyste funkcje, zero bazy — dlatego ten plik nie buduje aplikacji Flaska
ani nie tworzy tabel. Blok importow „rejestr mapperow" jest mimo to
potrzebny: import modules.reports.ingest wykonuje modules/reports/__init__.py
-> routers.py -> modules.users, a User ma relationship('Multiplier') podana
stringiem. Bez calego grafu modeli SQLAlchemy nie skonfiguruje mapperow
i pierwsza instancjacja jakiegokolwiek modelu w procesie testowym rzuci
InvalidRequestError. Ten sam gotcha co w tests/test_sales_models.py.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import date
from decimal import Decimal

import pytest

from modules.reports.ingest import mapuj_pozycje, mapuj_zamowienie, typ_ceny
from modules.reports.models import BaselinkerReportOrder
from modules.reports.models_sales import SalesOrder, SalesOrderItem
from modules.reports.service import STATUSY_BASELINKER, czy_usluga, kwota_netto

from modules.calculator.models import (  # noqa: F401 — rejestr mapperów
    Quote, QuoteItem, QuoteItemDetails, Price, Multiplier,
    FinishingOption, EdgeOption, CalculatorSetting, QuoteCounter, QuoteLog,
)
from modules.clients.models import Client  # noqa: F401 — rejestr mapperów
import modules.quotes.models  # noqa: F401 — rejestr mapperów

# 2026-09-18 07:00 UTC = 09:00 w Warszawie. Ta sama data w obu strefach,
# wiec ten timestamp nie rozstrzyga niczego o zegarze.
TS_18_09 = 1789714800

# 2026-09-18 23:30 UTC = 2026-09-19 01:30 w Warszawie. DWIE ROZNE DATY —
# tym timestampem sprawdzamy, ktorego zegara uzywa mapper.
TS_NOCNY = 1789774200


def zamowienie(**nadpisania):
    """Surowe zamowienie z getOrders, w ksztalcie, ktory naprawde przychodzi."""
    baza = {
        'order_id': 50854536,
        'date_add': TS_18_09,
        'date_confirmed': TS_18_09,
        'order_status_id': 138619,
        'extra_field_1': 'WP-2026-0912',
        'delivery_fullname': 'Jan Przykładowy',
        'delivery_company': '',
        'user_login': 'jprzykladowy',
        'email': 'jan.przykladowy@example.com',
        'phone': '+48 601 202 303',
        'delivery_address': 'Lipowa 12',
        'delivery_postcode': '40-100',
        'delivery_city': 'Katowice',
        'delivery_state': 'śląskie',
        'delivery_method': 'Kurier DPD',
        'delivery_price': 123.00,
        'payment_method': 'Przelew',
        'payment_done': 8704.00,
        'admin_comments': 'Klient prosi o telefon przed dostawą',
        'order_source': 'shop',
        'order_source_id': 12,
        'custom_extra_fields': {'105623': 'Łukasz Próbny', '106169': 'brutto'},
        'products': [
            {'order_product_id': 991, 'name': 'Blat dębowy lity A/B 160x70x4 cm surowy',
             'quantity': 1, 'price_brutto': 1060.75},
        ],
    }
    baza.update(nadpisania)
    return baza


@pytest.mark.parametrize('pole, oczekiwane', [
    ({'106169': 'netto'}, 'netto'),
    ({'106169': ' Brutto '}, 'brutto'),
    ({'106169': ''}, ''),
    ({}, ''),
])
def test_typ_ceny_czyta_pole_dodatkowe_106169(pole, oczekiwane):
    assert typ_ceny(zamowienie(custom_extra_fields=pole)) == oczekiwane


def test_typ_ceny_przezywa_brak_custom_extra_fields():
    zam = zamowienie()
    del zam['custom_extra_fields']
    assert typ_ceny(zam) == ''


@pytest.mark.parametrize('kwota, typ, oczekiwane', [
    (123.0, 'netto', 123.0),
    (123.0, 'brutto', 100.0),
    (123.0, '', 100.0),
    (None, 'brutto', 0.0),
])
def test_kwota_netto_dzieli_przez_vat_poza_zamowieniami_netto(kwota, typ, oczekiwane):
    assert kwota_netto(kwota, typ) == pytest.approx(oczekiwane)


def test_mapuje_pola_zamowienia_z_surowego_slownika():
    wynik = mapuj_zamowienie(zamowienie())
    assert wynik['baselinker_order_id'] == 50854536
    assert wynik['date_created'] == date(2026, 9, 18)
    assert wynik['internal_order_number'] == 'WP-2026-0912'
    assert wynik['customer_name'] == 'Jan Przykładowy'
    assert wynik['email'] == 'jan.przykladowy@example.com'
    assert wynik['phone'] == '+48 601 202 303'
    assert wynik['delivery_address'] == 'Lipowa 12'
    assert wynik['delivery_city'] == 'Katowice'
    assert wynik['delivery_method'] == 'Kurier DPD'
    assert wynik['payment_method'] == 'Przelew'
    assert wynik['order_source'] == 'shop'
    assert wynik['order_source_id'] == 12
    assert wynik['current_status'] == 'W produkcji - surowe'
    assert wynik['baselinker_status_id'] == 138619
    assert wynik['notes'] == 'Klient prosi o telefon przed dostawą'


def test_nazwa_klienta_spada_kaskadowo_gdy_brak_delivery_fullname():
    zam = zamowienie(delivery_fullname='', delivery_company='Stolarnia sp. z o.o.')
    assert mapuj_zamowienie(zam)['customer_name'] == 'Stolarnia sp. z o.o.'


def test_nazwa_klienta_bez_zadnego_zrodla_to_nieznany_klient():
    zam = zamowienie(delivery_fullname='', delivery_company='', user_login='')
    assert mapuj_zamowienie(zam)['customer_name'] == 'Nieznany klient'


def test_opiekun_i_typ_ceny_ida_z_custom_extra_fields():
    wynik = mapuj_zamowienie(zamowienie())
    assert wynik['caretaker'] == 'Łukasz Próbny'
    assert wynik['price_type'] == 'brutto'


def test_brak_opiekuna_daje_brak_danych_a_nie_none():
    # Spójność z 7938 wierszami backfillu: stara synchronizacja wpisywała
    # dosłownie „Brak danych". None zrobiłby drugi kubełek dla tego samego
    # zjawiska na karcie „Sprzedaż według opiekuna".
    zam = zamowienie(custom_extra_fields={'106169': 'brutto'})
    assert mapuj_zamowienie(zam)['caretaker'] == 'Brak danych'


# ===== wojewodztwo: postac zapisu =======================================
#
# ZNALEZISKO KRYTYCZNE (przeglad Zadania 6). Mapper sprowadzal wojewodztwo
# do MALYCH liter, powolujac sie na „wszystkie wiersze w bazie maja male".
# Zmierzone na woodpower_crm_local 22.09.2026 jest DOKLADNIE ODWROTNIE:
#
#   sales_orders             3028 wierszy z WIELKIEJ litery, 0 z malej
#                            (+ 296 pustych)
#   baselinker_reports_orders 6543 wierszy z WIELKIEJ litery, 0 z malej
#                            (+ 1395 pustych)
#
# Male litery rozbilyby slownik wojewodztw na „Mazowieckie" i „mazowieckie",
# czyli karta „Wojewodztwo" pokazalaby dwa wiersze dla jednego regionu.
# Postac kanoniczna wymusza w danych historycznych
# BaselinkerReportOrder.normalize_delivery_state i to z nia porownujemy —
# to ta sama funkcja, ktora policzyla KAZDY istniejacy wiersz.

def _postac_historyczna(wartosc: str) -> str:
    """Wojewodztwo tak, jak zapisalaby je stara synchronizacja."""
    wiersz = BaselinkerReportOrder(delivery_state=wartosc)
    wiersz.normalize_delivery_state()
    return wiersz.delivery_state


@pytest.mark.parametrize('z_baselinkera, oczekiwane', [
    ('śląskie', 'Śląskie'),
    ('ŚLĄSKIE', 'Śląskie'),
    ('mazowieckie', 'Mazowieckie'),
    ('kujawsko-pomorskie', 'Kujawsko-Pomorskie'),
    ('warminsko-mazurskie', 'Warmińsko-Mazurskie'),
    ('dolnoslaskie', 'Dolnośląskie'),
])
def test_wojewodztwo_zapisuje_sie_w_postaci_ktora_ma_cala_baza(z_baselinkera, oczekiwane):
    zapisane = mapuj_zamowienie(zamowienie(delivery_state=z_baselinkera))['delivery_state']
    assert zapisane == oczekiwane
    # Ta sama postac, ktora wyprodukowala 9571 istniejacych wierszy.
    assert zapisane == _postac_historyczna(z_baselinkera)
    assert zapisane[0].isupper()


def test_wojewodztwo_z_kodu_pocztowego_ma_te_sama_postac_co_z_baselinkera():
    # DRUGA SCIEZKA: wartosci nie ma w zamowieniu i dorabia ja
    # PostcodeToStateMapper. Gdyby tylko jedna z dwoch sciezek pisala
    # wielka litera, slownik i tak rozjechalby sie na dwa kubelki.
    z_kodu = mapuj_zamowienie(
        zamowienie(delivery_state='', delivery_postcode='00-950'))['delivery_state']
    z_bl = mapuj_zamowienie(zamowienie(delivery_state='mazowieckie'))['delivery_state']
    assert z_kodu == 'Mazowieckie'
    assert z_kodu == z_bl == _postac_historyczna('mazowieckie')


def test_wojewodztwo_nie_do_ustalenia_zostaje_puste():
    # ZNALEZISKO WAZNE (przeglad Zadania 1): dawniej `is None`. Baza po
    # backfillu (3324 zamowienia) nie ma ani jednego NULL-a w delivery_state
    # (296 wierszy ma pusty napis) — stara synchronizacja zawsze pisala '',
    # nigdy None. `aggregates.wg_wymiaru` grupuje po surowej kolumnie w SQL,
    # wiec NULL obok '' dla tego samego "brak wartosci" rozbijalby karte
    # "Wojewodztwo" na dwa wiersze pustki zamiast jednego.
    zam = zamowienie(delivery_state='', delivery_postcode='')
    assert mapuj_zamowienie(zam)['delivery_state'] == ''


def test_puste_pola_tekstowe_zamowienia_ida_jako_pusty_napis_nie_none():
    # ZNALEZISKO WAZNE (przeglad Zadania 1): _tekst() zamienial pusty napis
    # na None, a w sales_orders po backfillu (3324 zamowienia) te kolumny
    # NIE MAJA ani jednego NULL-a: internal_order_number 128 wierszy '',
    # email 224, phone 140, delivery_address 326, payment_method 91.
    # Filtry (filters.py:207-209) sa odporne na NULL i '', ale karty
    # agregatow licza po surowej kolumnie w SQL i rozbilyby sie na dwa
    # wiersze pustki. Mapper musi pisac ta sama strona, co dane historyczne.
    zam = zamowienie(extra_field_1='', email='', phone='', delivery_address='',
                     payment_method='')
    wynik = mapuj_zamowienie(zam)
    for pole in ('internal_order_number', 'email', 'phone', 'delivery_address',
                'payment_method'):
        assert wynik[pole] == ''
        assert wynik[pole] is not None


def test_pozycja_dostaje_bl_order_product_id():
    # Bez tego identyfikatora setOrderProductFields nie ma jak zadzialac,
    # a ceny i ilosci nie da sie odeslac do BaseLinkera.
    assert mapuj_pozycje(zamowienie())[0]['bl_order_product_id'] == 991


def test_pozycja_dostaje_rozbior_nazwy_z_parsera():
    pozycja = mapuj_pozycje(zamowienie())[0]
    assert pozycja['wood_species'] == 'dąb'
    assert pozycja['technology'] == 'lity'
    assert pozycja['wood_class'] == 'A/B'
    assert pozycja['finish_state'] == 'surowy'
    assert pozycja['length_cm'] == Decimal('160.00')
    assert pozycja['width_cm'] == Decimal('70.00')
    assert pozycja['thickness_cm'] == Decimal('4.00')
    assert pozycja['raw_product_name'] == 'Blat dębowy lity A/B 160x70x4 cm surowy'


def test_ceny_pozycji_dla_zamowienia_brutto():
    pozycja = mapuj_pozycje(zamowienie())[0]
    assert pozycja['price_gross'] == Decimal('1060.75')
    assert pozycja['price_net'] == Decimal('862.40')
    assert pozycja['value_net'] == Decimal('862.40')


def test_ceny_pozycji_dla_zamowienia_netto_nie_dziela_sie_przez_vat():
    zam = zamowienie(custom_extra_fields={'106169': 'netto'},
                     products=[{'order_product_id': 1, 'name': 'Blat dębowy lity A/B 160x70x4 cm',
                                'quantity': 2, 'price_brutto': 500.00}])
    pozycja = mapuj_pozycje(zam)[0]
    assert pozycja['price_net'] == Decimal('500.00')
    assert pozycja['price_gross'] == Decimal('615.00')
    assert pozycja['value_net'] == Decimal('1000.00')


@pytest.mark.parametrize('nazwa', [
    'Suszenie usługowe 88m3',
    'Docięcie do wymiaru - usługa',
    'Klejenie płyty',
])
def test_pozycja_uslugowa_dostaje_group_type_usluga(nazwa):
    zam = zamowienie(products=[{'order_product_id': 1, 'name': nazwa,
                                'quantity': 1, 'price_brutto': 100.0}])
    assert mapuj_pozycje(zam)[0]['group_type'] == 'usługa'
    assert czy_usluga(nazwa) is True


def test_pozycja_towarowa_dostaje_group_type_towar():
    assert mapuj_pozycje(zamowienie())[0]['group_type'] == 'towar'


def test_pozycja_bez_wymiarow_nie_wywala_mappera():
    zam = zamowienie(products=[{'order_product_id': 7, 'name': 'Dopłata do transportu',
                                'quantity': 1, 'price_brutto': 50.0}])
    pozycja = mapuj_pozycje(zam)[0]
    assert pozycja['length_cm'] is None
    assert pozycja['total_volume'] is None
    assert pozycja['total_surface_m2'] is None
    assert pozycja['price_per_m3'] is None


def test_objetosc_i_powierzchnia_mnoza_sie_przez_ilosc():
    zam = zamowienie(products=[{'order_product_id': 1,
                                'name': 'Blat dębowy lity A/B 100x50x2 cm',
                                'quantity': 3, 'price_brutto': 123.0}])
    pozycja = mapuj_pozycje(zam)[0]
    assert pozycja['volume_per_piece'] == Decimal('0.010000')
    assert pozycja['total_volume'] == Decimal('0.030000')
    # 2 * (1,00*0,50 + 1,00*0,02 + 0,50*0,02) = 1,06 m2 na sztuke, razy 3.
    assert pozycja['total_surface_m2'] == Decimal('3.1800')


# ===== powierzchnia: ten sam wzor, co dane historyczne ==================
#
# ZNALEZISKO KRYTYCZNE (przeglad Zadania 6). Mapper liczyl
# `(L/100) * (W/100) * ilosc`, czyli JEDNA sciane, a wszystkie istniejace
# wiersze w tej samej kolumnie niosa pole CALEGO prostopadloscianu
# (BaselinkerReportOrder.calculate_surface_area, models.py:431-462).
# Zmierzone na woodpower_crm_local (7911 pozycji z wypelniona kolumna):
#   suma historyczna        19 096,25 m2
#   wzor szescioscienny     19 096,25 m2   <- zgodnosc co do grosza
#   wzor jednoscienny        8 563,81 m2   <- to, co liczyl mapper
# Po cutoverze jedna kolumna nioslaby dwa nieporownywalne znaczenia.

def _powierzchnia_historyczna(dlugosc, szerokosc, grubosc, ilosc):
    """Powierzchnia tak, jak liczyla ja stara synchronizacja."""
    wiersz = BaselinkerReportOrder(length_cm=dlugosc, width_cm=szerokosc,
                                   thickness_cm=grubosc, quantity=ilosc)
    return wiersz.calculate_surface_area()


@pytest.mark.parametrize('nazwa, ilosc, dlugosc, szerokosc, grubosc', [
    ('Blat dębowy lity A/B 100x50x2 cm', 3, 100, 50, 2),
    ('Blat dębowy lity A/B 160x70x4 cm surowy', 1, 160, 70, 4),
    ('Blat dębowy lity A/B 203x15,5x4,3 cm', 7, 203, 15.5, 4.3),
])
def test_powierzchnia_zgadza_sie_ze_wzorem_danych_historycznych(
        nazwa, ilosc, dlugosc, szerokosc, grubosc):
    zam = zamowienie(products=[{'order_product_id': 1, 'name': nazwa,
                                'quantity': ilosc, 'price_brutto': 500.0}])
    z_mappera = mapuj_pozycje(zam)[0]['total_surface_m2']
    z_historii = _powierzchnia_historyczna(dlugosc, szerokosc, grubosc, ilosc)
    assert z_mappera == Decimal(str(z_historii)).quantize(Decimal('0.0001'))


def test_powierzchnia_nie_jest_juz_polem_jednej_sciany():
    # Kontrola negatywna: gdyby ktos „poprawil" wzor z powrotem na jedna
    # sciane, ta asercja wylapie to od razu. 100x50x2 cm, 3 sztuki:
    # jedna sciana dalaby 1,5000 m2, calosc daje 3,1800 m2.
    zam = zamowienie(products=[{'order_product_id': 1,
                                'name': 'Blat dębowy lity A/B 100x50x2 cm',
                                'quantity': 3, 'price_brutto': 123.0}])
    assert mapuj_pozycje(zam)[0]['total_surface_m2'] != Decimal('1.5000')


@pytest.mark.parametrize('dlugosc, szerokosc, grubosc', [
    (100, 50, None),   # brak grubosci — dawny wzor liczyl mimo to (jedna sciana)
    (100, None, 2),
    (None, 50, 2),
    (100, 50, 0),      # zero jest tak samo bezuzyteczne jak brak
])
def test_powierzchnia_bez_kompletu_wymiarow_jest_none(dlugosc, szerokosc, grubosc):
    # Bez KTOREGOKOLWIEK z trzech wymiarow wzoru szesciosciennego policzyc
    # sie nie da. Dawny mapper grubosci nie potrzebowal, wiec przy samych
    # L i W wpisywal pole jednej sciany — liczba nieporownywalna z reszta
    # kolumny wchodzila do tego samego SUM. Historyczna
    # `calculate_surface_area` zwraca w tej sytuacji 0.0; bierzemy None,
    # bo dla SUM jest nierozroznialne, a nie udaje wyniku (114 takich pozycji
    # w bazie dzieli sie zreszta na 87 zer i 27 NULL-i — dane historyczne
    # same nie sa tu jednorodne).
    from modules.reports.ingest import _powierzchnia_m2
    assert _powierzchnia_m2(dlugosc, szerokosc, grubosc, 3) is None
    assert _powierzchnia_historyczna(dlugosc, szerokosc, grubosc, 3) == 0.0


def test_powierzchnia_pozycji_bez_wymiarow_w_nazwie_jest_none():
    # `analyze_product_for_volume_and_attributes` czyta z tej nazwy objetosc
    # wprost, ale wymiarow nie zna — powierzchnia zostaje nieznana.
    zam = zamowienie(products=[{'order_product_id': 1,
                                'name': 'Tarcica jesionowa 0,96m3',
                                'quantity': 1, 'price_brutto': 1200.0}])
    pozycja = mapuj_pozycje(zam)[0]
    assert pozycja['total_surface_m2'] is None
    assert pozycja['total_volume'] == Decimal('0.960000')


def test_objetosc_liczy_sie_precyzyjnie_z_wymiarow_nie_z_gotowca_parsera():
    # ZNALEZISKO WAZNE (przeglad Zadania 1): `rozbior['volume_per_piece']`
    # z parsera jest juz zaokraglony do 4 miejsc (parser.py:_calculate_volume
    # quantize('0.0001')), a kolumna sales_order_items ma 6 miejsc liczonych
    # DOKLADNIE z L*W*T. 203x15,5x4,3 cm daje precyzyjnie 0,01352995 m3:
    # parser zaokragla to do 4 miejsc na 0,0135, a dawny (bledny) mapper
    # tylko dopisywal zera do 6 miejsc -> 0,013500. Poprawny wynik, liczony
    # wprost z wymiarow i skwantyzowany raz do 6 miejsc, to 0,013530 — tak
    # jak realne zamowienie 51106786 (0,013600 bylo bledem, powinno byc
    # 0,013500 — ten sam mechanizm psuje wartosc w obie strony zaleznie od
    # konkretnych wymiarow).
    zam = zamowienie(products=[{'order_product_id': 1,
                                'name': 'Klejonka dębowa lity A/B 203x15,5x4,3 cm',
                                'quantity': 1, 'price_brutto': 500.0}])
    pozycja = mapuj_pozycje(zam)[0]
    assert pozycja['volume_per_piece'] == Decimal('0.013530')
    assert pozycja['total_volume'] == Decimal('0.013530')


def test_objetosc_bez_wymiarow_czyta_sie_z_liczby_wprost_w_nazwie():
    # ZNALEZISKO KRYTYCZNE (przeglad Zadania 1): "Tarcica jesionowa 0,96m3"
    # nie ma trzech wymiarow w nazwie (rozbior['volume_per_piece'] to None),
    # wiec dawny mapper gubil te objetosc calkowicie — zmierzone: 50 wierszy
    # group_type='towar' bez wymiarow niesie 46,099 m3, czyli 14,2% calej
    # objetosci towaru na woodpower_crm_local. Stara synchronizacja czytala
    # ja przez analyze_product_for_volume_and_attributes z
    # analysis_type='volume_only' (service.py:1468-1480) — ta sama sciezka
    # tutaj, wiec towar sprzedawany na m3 nie wypada z KPI.
    zam = zamowienie(products=[{'order_product_id': 1,
                                'name': 'Tarcica jesionowa 0,96m3',
                                'quantity': 1, 'price_brutto': 1200.0}])
    pozycja = mapuj_pozycje(zam)[0]
    assert pozycja['total_volume'] == Decimal('0.960000')
    assert pozycja['volume_per_piece'] == Decimal('0.960000')
    assert pozycja['group_type'] == 'towar'


def test_objetosc_z_nazwy_nie_mnozy_sie_przez_ilosc_dzieli_na_sztuke():
    # service.py:414-417 ("NIE MNOZ!"/"PODZIEL!"): objetosc z nazwy to juz
    # objetosc CALEJ pozycji, nie objetosc jednej sztuki — total_volume
    # bierze ja wprost, volume_per_piece dzieli przez ilosc.
    zam = zamowienie(products=[{'order_product_id': 1,
                                'name': 'Tarcica jesionowa 0,65m3',
                                'quantity': 2, 'price_brutto': 800.0}])
    pozycja = mapuj_pozycje(zam)[0]
    assert pozycja['total_volume'] == Decimal('0.650000')
    assert pozycja['volume_per_piece'] == Decimal('0.325000')


def test_saldo_liczy_sie_raz_na_zamowieniu_a_nie_na_pozycji():
    # Pulapka, przez ktora poprzednik zawyzal saldo 7,58x: pola poziomu
    # zamowienia powielone na kazdej pozycji. Mapper pozycji NIE MA prawa
    # zwrocic ani salda, ani wplaty.
    pozycje = mapuj_pozycje(zamowienie())
    assert 'balance_due' not in pozycje[0]
    assert 'paid_amount' not in pozycje[0]
    assert 'balance_due' in mapuj_zamowienie(zamowienie())


def test_saldo_zamowienia_brutto_dzieli_kurier_przez_vat():
    # netto produktow 862,40 + kurier 123,00/1,23 = 100,00 -> do zaplaty 962,40
    # zaplacono netto 8704,00/1,23 = 7076,42 -> saldo -6114,02
    wynik = mapuj_zamowienie(zamowienie())
    assert wynik['paid_amount'] == Decimal('7076.42')
    assert wynik['balance_due'] == Decimal('-6114.02')


def test_saldo_zamowienia_netto_dolicza_kurier_bez_dzielenia():
    zam = zamowienie(custom_extra_fields={'106169': 'netto'}, payment_done=0,
                     delivery_price=100.00,
                     products=[{'order_product_id': 1,
                                'name': 'Blat dębowy lity A/B 160x70x4 cm',
                                'quantity': 1, 'price_brutto': 900.00}])
    wynik = mapuj_zamowienie(zam)
    assert wynik['paid_amount'] == Decimal('0.00')
    assert wynik['balance_due'] == Decimal('1000.00')


def test_usluga_wchodzi_do_kwoty_do_zaplaty():
    # FALA 6. Do 22.09.2026 saldo pomijalo pozycje uslugowe, powolujac sie na
    # to, ze tak policzone sa dane w bazie. POMIAR TO OBALIL — patrz
    # `ingest.oblicz_saldo`. Usluga wchodzi do salda: klient jest nam winien
    # takze za suszenie.
    zam = zamowienie(payment_done=0, delivery_price=0,
                     custom_extra_fields={'106169': 'netto'},
                     products=[
                         {'order_product_id': 1, 'name': 'Blat dębowy lity A/B 100x50x2 cm',
                          'quantity': 1, 'price_brutto': 800.00},
                         {'order_product_id': 2, 'name': 'Suszenie usługowe 4m3',
                          'quantity': 1, 'price_brutto': 200.00},
                     ])
    assert mapuj_zamowienie(zam)['balance_due'] == Decimal('1000.00')


def test_kwota_do_zaplaty_idzie_za_danymi_lezacymi_w_bazie():
    # W service.py sa DWIE sprzeczne definicje order_amount_net: :1590 liczy
    # pozycje NIE-uslugowe, a :528 wszystkie. Wybor rozstrzyga POMIAR na
    # woodpower_crm_local (3324 zamowienia): wariant ze wszystkimi pozycjami
    # odtwarza SUM(balance_due) co do 99,73 zl (0,014%), wariant bez uslug
    # myli sie o 82 695 zl. Ten test przybija wybor „wszystkie pozycje",
    # zeby za rok nikt nie „poprawil" tego z powrotem.
    zam = zamowienie(payment_done=0, delivery_price=0,
                     custom_extra_fields={'106169': 'netto'},
                     products=[
                         {'order_product_id': 1, 'quantity': 1, 'price_brutto': 1000.00,
                          'name': 'Blat dębowy lity A/B 100x50x2 cm'},
                         {'order_product_id': 2, 'quantity': 1, 'price_brutto': 250.00,
                          'name': 'Suszenie usługowe 4m3'},
                     ])
    # Wariant „wszystkie pozycje" daje 1250,00. Wariant „bez uslug" dalby 1000,00.
    assert mapuj_zamowienie(zam)['balance_due'] == Decimal('1250.00')


def test_data_platnosci_tylko_gdy_cos_zaplacono():
    assert mapuj_zamowienie(zamowienie())['payment_date'] == date(2026, 9, 18)
    assert mapuj_zamowienie(zamowienie(payment_done=0))['payment_date'] is None


def test_zamowienie_bez_produktow_daje_puste_pozycje():
    zam = zamowienie(products=[])
    # netto towarow 0 + kurier 123,00/1,23 = 100,00 - zaplacono 7076,42
    assert mapuj_pozycje(zam) == []
    assert mapuj_zamowienie(zam)['balance_due'] == Decimal('-6976.42')


def test_status_bierze_sie_z_mapy_wspolnej_ze_stara_zakladka():
    assert STATUSY_BASELINKER[155824] == 'Nowe - opłacone'
    zam = zamowienie(order_status_id=417343)
    assert mapuj_zamowienie(zam)['current_status'] == 'Status 417343'


@pytest.mark.parametrize('status_z_bl', [None, '', 'nie-liczba'])
def test_brak_statusu_zapisuje_sie_jako_null_a_nie_napis_status_none(status_z_bl):
    # ZNALEZISKO WAZNE (przeglad Zadania 6): przy braku order_status_id
    # do current_status wchodzil doslowny napis „Status None". Kolumna jest
    # indeksowana i widoczna w arkuszu — uzytkownik zobaczylby ten napis
    # wprost w komorce, a karty grupujace po statusie zrobilyby z niego
    # osobny kubelek. Brak wartosci to NULL.
    zam = zamowienie(order_status_id=status_z_bl)
    wynik = mapuj_zamowienie(zam)
    assert wynik['current_status'] is None
    assert wynik['baselinker_status_id'] is None


# ===== numer zamowienia BaseLinkera =====================================

@pytest.mark.parametrize('nadpisania', [
    {'order_id': None},
    {'order_id': ''},
    {'order_id': 0},
    {'order_id': 'abc'},
])
def test_brak_numeru_baselinkera_daje_none_a_nigdy_zera(nadpisania):
    # ZNALEZISKO WAZNE (przeglad Zadania 6): mapper liczyl tu
    # `_calkowita(order.get('order_id'), 0)`, czyli brak numeru zapisywal
    # sie jako 0. Kolumna baselinker_order_id jest UNIQUE, wiec PIERWSZE
    # takie zamowienie zajmowaloby slot 0 na stale, a DRUGIE wywracaloby
    # zapis na duplikacie klucza zamiast zostac pominiete.
    assert mapuj_zamowienie(zamowienie(**nadpisania))['baselinker_order_id'] is None


def test_numer_baselinkera_czyta_sie_takze_z_klucza_id():
    zam = zamowienie()
    zam['id'] = zam.pop('order_id')
    assert mapuj_zamowienie(zam)['baselinker_order_id'] == 50854536


def test_numer_baselinkera_zmiennoprzecinkowy_obcina_sie_do_int():
    assert mapuj_zamowienie(zamowienie(order_id=12.9))['baselinker_order_id'] == 12


# ===== zegar ============================================================

def test_data_zamowienia_liczy_sie_w_strefie_warszawskiej_nie_w_utc():
    # ZNALEZISKO WAZNE (przeglad Zadania 6): `datetime.fromtimestamp` bez
    # strefy bierze zegar KONTENERA (UTC), a fallback `_dzis()` liczy juz
    # Europe/Warsaw (analiza_service.dzis_lokalnie, commit a5c68aa). Jedna
    # kolumna date_created dostawala dwa rozne zegary. TS_NOCNY to
    # 2026-09-18 23:30 UTC, czyli 2026-09-19 01:30 w Polsce — zamowienie
    # z nocy 19 wrzesnia ladowalo w sprzedazy 18 wrzesnia.
    wynik = mapuj_zamowienie(zamowienie(date_add=TS_NOCNY, date_confirmed=TS_NOCNY))
    assert wynik['date_created'] == date(2026, 9, 19)
    assert wynik['payment_date'] == date(2026, 9, 19)


def test_data_zamowienia_bez_date_add_spada_na_ten_sam_zegar_co_reszta():
    from modules.reports.analiza_service import dzis_lokalnie
    zam = zamowienie(date_add=None)
    assert mapuj_zamowienie(zam)['date_created'] == dzis_lokalnie()


# ===== zakres kolumn ====================================================

def test_cena_za_m3_poza_zakresem_kolumny_zapisuje_sie_jako_null():
    # price_per_m3 to DECIMAL(10,2) — maksimum 99 999 999,99. Jest ilorazem,
    # wiec pozycja o znikomej objetosci potrafi ten zakres przebic, a MySQL
    # w trybie scislym odrzuca wtedy CALY INSERT bledem 1264. Pojedyncza
    # felerna pozycja wyrzucalaby z analityki komplet danych zamowienia.
    zam = zamowienie(custom_extra_fields={'106169': 'netto'},
                     products=[{'order_product_id': 1,
                                'name': 'Probka debowa lita A/B 1x1x0,1 cm',
                                'quantity': 1, 'price_brutto': 500.0}])
    pozycja = mapuj_pozycje(zam)[0]
    # 1x1x0,1 cm to 0,0000001 m3 — w kolumnie o szesciu miejscach 0,000000.
    assert pozycja['total_volume'] == Decimal('0.000000')
    # 500,00 / 0,0000001 m3 = 5 000 000 000, czyli grubo poza DECIMAL(10,2).
    assert pozycja['price_per_m3'] is None


def test_wartosci_wyliczane_miesczace_sie_w_kolumnie_nie_sa_kasowane():
    # Kontrola negatywna dla powyzszego: normalna pozycja ma wypelnione
    # wszystkie cztery kolumny wyliczane, zadnej nie gubimy „przy okazji".
    pozycja = mapuj_pozycje(zamowienie())[0]
    for kolumna in ('volume_per_piece', 'total_volume', 'total_surface_m2',
                    'price_per_m3'):
        assert pozycja[kolumna] is not None


def test_kolumny_wyliczane_miesczace_sie_w_deklaracji_modelu():
    # Niezmiennik: skala i zakres uzyte w mapperze musza zgadzac sie
    # z deklaracja kolumny. Inaczej guard z `_kwota_w_zakresie` chronilby
    # przed zlym progiem i MySQL i tak odrzucilby INSERT.
    pozycja = mapuj_pozycje(zamowienie())[0]
    for kolumna in ('volume_per_piece', 'total_volume', 'total_surface_m2',
                    'price_per_m3'):
        typ = SalesOrderItem.__table__.c[kolumna].type
        assert abs(pozycja[kolumna]) < Decimal(10) ** (typ.precision - typ.scale)
        assert -pozycja[kolumna].as_tuple().exponent <= typ.scale


def test_mapper_zwraca_wylacznie_nazwy_kolumn_modelu():
    # Niezmiennik, ktory chroni przed literowka w kluczu slownika: upsert
    # z Zadania 2 robi setattr po tych nazwach, wiec literowka nie wywala
    # sie glosno, tylko po cichu nie zapisuje kolumny.
    from modules.reports.models_sales import SalesOrderItem
    kolumny_zam = {k.name for k in SalesOrder.__table__.columns}
    kolumny_poz = {k.name for k in SalesOrderItem.__table__.columns}
    assert set(mapuj_zamowienie(zamowienie())) <= kolumny_zam
    assert set(mapuj_pozycje(zamowienie())[0]) <= kolumny_poz
