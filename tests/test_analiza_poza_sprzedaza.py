# -*- coding: utf-8 -*-
"""Zamówienia anulowane i nieopłacone NIE są sprzedażą (partia E, punkt E5).

Decyzja użytkownika z 23.09.2026: zamówienia o statusie BaseLinkera
„Zamówienie anulowane" (138625) i „Nowe - nieopłacone" (105112) nie liczą się
do żadnej liczby Analizy sprzedażowej — pulpitu, segmentu porównawczego,
Eksploratora, kubełków klientów i nowych klientów. Stary moduł raportów
wykluczał je zawsze; nowy do tej partii nie patrzył na status wcale.

Arkusz pokazuje je dalej (zastępuje Excela i anulowanie ma tam być widać),
ale jego stopka ich nie sumuje — ma się zgadzać z pulpitem.

FIKSTURA (wrzesień 2026, okres 1–21):
  Z1  K1  Dostarczona   shop    Anna  Mazowieckie  netto 1000, saldo 100, kurier 20
  Z2  K2  ANULOWANE     allegro Bartek Śląskie     netto  300, saldo -40, kurier 15
  Z3  K3  NIEOPŁACONE   shop    Anna  Mazowieckie  netto  500, saldo 500, kurier 25
  Z4  K3  Dostarczona   shop    Anna  Mazowieckie  netto  200
  Z5  K1  status NULL   shop    —     —            netto   70
  Z6  —   NIEOPŁACONE, ale z nazwą statusu „W produkcji" (styczeń, saldo 999)
Liczy się Z1 + Z4 + Z5: netto 1270, trzy zamówienia, saldo 100.
Bez warunku byłoby 2070 zł i pięć zamówień.
"""
import os
import sys
from datetime import date, datetime
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from flask import Flask
from sqlalchemy.dialects.mysql import LONGTEXT
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.pool import StaticPool

from extensions import db
from modules.reports import analytics, explorer
from modules.reports.aggregates import (
    kpi, nadplaty, naleznosci_wg_wieku, naleznosci_wg_wymiaru, wg_wymiaru,
)
from modules.reports.analiza_service import (
    dane_dashboardu, dane_eksploratora, formatuj_liczbe, wartosci_wymiaru,
)
from modules.reports.filters import (
    liczy_sie_do_sprzedazy, warunek_sprzedazy, warunki_pozycji, warunki_zamowienia,
)
from modules.reports.ingest import _przelicz_klienta
from modules.reports.models_sales import SalesClient, SalesOrder, SalesOrderItem
from modules.reports.service import STATUSY_POZA_SPRZEDAZA
from modules.reports.uklad import KATALOG, Instancja

from modules.calculator.models import (  # noqa: F401 — rejestr mapperów
    Quote, QuoteItem, QuoteItemDetails, Price, Multiplier,
    FinishingOption, EdgeOption, CalculatorSetting, QuoteCounter, QuoteLog,
)


@compiles(LONGTEXT, 'sqlite')
def _longtext_jako_text(typ, kompilator, **kw):
    return 'TEXT'


from modules.production.models import ProductionOrder  # noqa: F401,E402 — rejestr mapperów
from modules.users.models import User  # noqa: F401,E402 — rejestr mapperów
from modules.clients.models import Client  # noqa: F401,E402 — rejestr mapperów
import modules.quotes.models  # noqa: F401,E402 — rejestr mapperów

OD, DO = date(2026, 9, 1), date(2026, 9, 21)
ANULOWANE, NIEOPLACONE, DOSTARCZONA = 138625, 105112, 138624


def _zamowienie(bl_id, dzien, status_id, status, klient, pozycje, *, kanal='shop',
                opiekun='Anna', wojewodztwo='Mazowieckie', saldo='0', kurier=None):
    """pozycje: lista krotek (value_net, total_volume, wood_species)."""
    zam = SalesOrder(baselinker_order_id=bl_id, date_created=dzien,
                     baselinker_status_id=status_id, current_status=status,
                     client_id=klient.id if klient else None, order_source=kanal,
                     caretaker=opiekun, delivery_state=wojewodztwo,
                     balance_due=Decimal(saldo),
                     delivery_cost=None if kurier is None else Decimal(kurier))
    db.session.add(zam)
    db.session.flush()
    for netto, objetosc, gatunek in pozycje:
        db.session.add(SalesOrderItem(
            order_id=zam.id, value_net=Decimal(netto), total_volume=Decimal(objetosc),
            group_type='blat', wood_species=gatunek, finish_state='surowy', quantity=1))
    return zam


@pytest.fixture()
def app():
    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        'poolclass': StaticPool, 'connect_args': {'check_same_thread': False}}
    db.init_app(app)
    with app.app_context():
        db.create_all()
        k1 = SalesClient(display_name='K1', email_norm='k1@example.com')
        k2 = SalesClient(display_name='K2', email_norm='k2@example.com')
        k3 = SalesClient(display_name='K3', email_norm='k3@example.com')
        db.session.add_all([k1, k2, k3])
        db.session.flush()

        _zamowienie(1, date(2026, 9, 10), DOSTARCZONA, 'Dostarczona - kurier', k1,
                    [('1000.00', '0.100000', 'dąb')], saldo='100.00', kurier='20.00')
        _zamowienie(2, date(2026, 9, 11), ANULOWANE, 'Zamówienie anulowane', k2,
                    [('300.00', '0.030000', 'dąb')], kanal='allegro', opiekun='Bartek',
                    wojewodztwo='Śląskie', saldo='-40.00', kurier='15.00')
        _zamowienie(3, date(2026, 9, 12), NIEOPLACONE, 'Nowe - nieopłacone', k3,
                    [('500.00', '0.050000', 'buk')], saldo='500.00', kurier='25.00')
        _zamowienie(4, date(2026, 9, 15), DOSTARCZONA, 'Dostarczona - kurier', k3,
                    [('200.00', '0.020000', 'dąb')])
        _zamowienie(5, date(2026, 9, 16), None, None, k1,
                    [('70.00', '0.007000', 'dąb')], opiekun='Brak danych',
                    wojewodztwo=None)
        # Dane niespójne celowo: identyfikator mówi „nieopłacone", nazwa —
        # „W produkcji". Jedyny sposób, żeby sprawdzić, że ostrzeżenie o saldzie
        # też dostało warunek (patrzy na nazwę statusu, nie na identyfikator).
        _zamowienie(6, date(2026, 1, 10), NIEOPLACONE, 'W produkcji - surowe', None,
                    [('999.00', '0.090000', 'dąb')], saldo='999.00')
        db.session.flush()
        for klient in (k1, k2, k3):
            _przelicz_klienta(klient, db.session)
        db.session.commit()
        yield app
        db.session.remove()


# --- jedna stała, jedno miejsce --------------------------------------------

def test_stala_to_dokladnie_anulowane_i_nieoplacone():
    assert set(STATUSY_POZA_SPRZEDAZA) == {ANULOWANE, NIEOPLACONE}


def test_liczy_sie_do_sprzedazy_w_pythonie():
    assert liczy_sie_do_sprzedazy(DOSTARCZONA)
    assert liczy_sie_do_sprzedazy(None)
    assert not liczy_sie_do_sprzedazy(ANULOWANE)
    assert not liczy_sie_do_sprzedazy(NIEOPLACONE)


# --- warstwa warunków ------------------------------------------------------

def test_warunek_sprzedazy_jest_w_warunkach_bez_filtra(app):
    """Warunek STAŁY: jedzie także wtedy, gdy użytkownik nie wybrał filtra.
    Dlatego siedzi w warstwie, przez którą idą wszystkie agregaty."""
    for warunki in (warunki_pozycji(None), warunki_zamowienia(None)):
        assert len(warunki) == 1
        sql = str(warunki[0].compile(compile_kwargs={'literal_binds': True}))
        assert 'baselinker_status_id' in sql
        assert str(ANULOWANE) in sql and str(NIEOPLACONE) in sql


def test_warunek_sprzedazy_idzie_na_koniec_listy(app):
    """Filtr użytkownika zostaje pierwszy — E4 (pola wykluczeń) dołoży się
    istniejącym mechanizmem filtra, a warunek stały koniunkcją obok."""
    warunki = warunki_zamowienia({'order_source': ['shop']})
    assert len(warunki) == 2
    assert 'order_source' in str(warunki[0])
    assert 'baselinker_status_id' in str(warunki[1])


def test_arkusz_moze_poprosic_o_warunki_bez_warunku_sprzedazy(app):
    assert warunki_pozycji(None, tylko_sprzedaz=False) == []
    assert warunki_zamowienia(None, tylko_sprzedaz=False) == []


def test_brak_identyfikatora_statusu_liczy_sie_do_sprzedazy(app):
    """`NOT IN` na kolumnie z NULL-em daje w SQL-u NULL, czyli odrzucenie
    wiersza. Zamówienie bez statusu ma się liczyć — nic nie mówi, że
    zostało anulowane."""
    liczba = SalesOrder.query.filter(warunek_sprzedazy(),
                                     SalesOrder.baselinker_order_id == 5).count()
    assert liczba == 1


# --- pulpit: KPI, wymiary, trend, mapa, kurier, należności ------------------

def test_kpi_nie_liczy_anulowanych_ani_nieoplaconych(app):
    wynik = kpi(OD, DO)
    assert wynik['netto'] == Decimal('1270.00')
    assert wynik['zamowienia'] == 3
    assert wynik['saldo'] == Decimal('100.00')
    assert wynik['objetosc'] == Decimal('0.127000')


def test_wymiar_nie_ma_wiersza_z_samych_wykluczonych(app):
    wiersze = {w['wartosc']: w for w in wg_wymiaru('order_source', OD, DO)}
    assert set(wiersze) == {'shop'}
    assert wiersze['shop']['netto'] == Decimal('1270.00')
    assert wiersze['shop']['zamowienia'] == 3


def test_szereg_miesieczny_bez_wykluczonych(app):
    wrzesien = analytics.szereg_miesieczny(OD, DO)[0]
    assert wrzesien['netto'] == Decimal('1270.00')
    assert wrzesien['zamowienia'] == 3


def test_mapa_bez_wykluczonych(app):
    mapa = analytics.sprzedaz_wg_wojewodztw(OD, DO)
    assert mapa['obszary']['mazowieckie']['netto'] == Decimal('1200.00')
    assert mapa['obszary']['mazowieckie']['zamowienia'] == 2
    assert mapa['obszary']['slaskie']['zamowienia'] == 0


def test_koszt_kuriera_bez_wykluczonych(app):
    assert analytics.suma_kosztu_kuriera(OD, DO) == Decimal('20.00')


def test_naleznosci_bez_wykluczonych(app):
    kubelki = naleznosci_wg_wieku(date(2026, 9, 21))
    assert sum(k['saldo'] for k in kubelki) == Decimal('100.00')
    assert sum(k['zamowienia'] for k in kubelki) == 1

    wymiar = naleznosci_wg_wymiaru('order_source', OD, DO)
    assert [(w['wartosc'], w['saldo']) for w in wymiar] == [('shop', Decimal('100.00'))]


def test_nadplata_anulowanego_zamowienia_nie_jest_nadplata(app):
    assert nadplaty() == {'zamowienia': 0, 'saldo': Decimal('0')}


def test_ostrzezenie_salda_tez_dostaje_warunek(app):
    assert analytics.ostrzezenie_salda(date(2026, 9, 21)) == {
        'zamowienia': 0, 'saldo': Decimal('0')}


# --- klienci: kubełki, nowi, konwersja --------------------------------------

def test_denormalizacja_klienta_pomija_wykluczone(app):
    k2 = SalesClient.query.filter_by(display_name='K2').one()
    k3 = SalesClient.query.filter_by(display_name='K3').one()
    assert (k2.orders_count, k2.lifetime_net, k2.first_order_at) == (0, Decimal('0'), None)
    assert (k3.orders_count, k3.lifetime_net) == (1, Decimal('200.00'))
    assert k3.first_order_at == date(2026, 9, 15)


def test_klient_z_jedynym_zamowieniem_anulowanym_nie_wpada_do_kubelka(app):
    kubelki = {k['kubelek']: k for k in analytics.klienci_wg_liczby_zamowien()}
    assert kubelki['1 zam.']['klienci'] == 1          # tylko K3 (Z4)
    assert kubelki['1 zam.']['netto'] == Decimal('200.00')
    assert kubelki['2–3']['klienci'] == 1             # K1 (Z1 + Z5)
    assert kubelki['2–3']['netto'] == Decimal('1070.00')


def test_klient_z_jedynym_zamowieniem_anulowanym_nie_jest_nowym(app):
    assert analytics.nowi_klienci(OD, DO) == 2


def test_konwersja_liczy_tylko_kupujacych(app):
    """Klient, którego jedyne zamówienie anulowano, nie jest kupującym —
    mianownik konwersji ma być tą samą liczbą, co suma kubełków."""
    konwersja = analytics.konwersja_lead_klient()
    kubelki = analytics.klienci_wg_liczby_zamowien()
    assert konwersja['klientow'] == 2
    assert konwersja['klientow'] == sum(k['klienci'] for k in kubelki)


# --- lejek -----------------------------------------------------------------

def test_lejek_nie_uznaje_anulowanego_za_oplacone(app):
    """Anulowane zamówienie ma saldo ≤ 0, więc bez warunku liczyło się
    w stopniu „Opłacone"."""
    db.session.add(Quote(quote_number='W/1', created_at=datetime(2026, 9, 5, 10, 0),
                         base_linker_order_id='2'))
    db.session.add(Quote(quote_number='W/2', created_at=datetime(2026, 9, 6, 10, 0),
                         base_linker_order_id='4'))
    db.session.commit()
    lejek = analytics.lejek_wycen(OD, DO)
    stopnie = {s['klucz']: s['liczba'] for s in lejek['stopnie']}
    assert stopnie['zamowione'] == 2        # numer na wycenie — stan wyceny
    assert stopnie['oplacone'] == 1         # tylko Z4
    assert lejek['dopasowanych'] == 1
    assert lejek['mediana_probka'] == 1


def test_lejek_nie_uznaje_anulowanego_za_bedace_w_realizacji(app):
    """Weryfikacja partii E (Z4): stopień „W realizacji" patrzy na `prod_orders`,
    a produkcja nie dowiaduje się o anulowaniu — zlecenie zostaje. Wycena 3934
    dowiązana do anulowanego BL 46680062 liczyła się tam w sierpniu 2026.
    Zamówienie, którego w tabeli sprzedaży NIE MA wcale (np. sprzed jej
    zakresu), dalej się liczy: nie wiemy o nim nic, co by je wykluczało."""
    db.session.add(Quote(quote_number='W/1', created_at=datetime(2026, 9, 5, 10, 0),
                         base_linker_order_id='2'))     # Z2 — anulowane
    db.session.add(Quote(quote_number='W/2', created_at=datetime(2026, 9, 6, 10, 0),
                         base_linker_order_id='4'))     # Z4 — dostarczone
    db.session.add(Quote(quote_number='W/3', created_at=datetime(2026, 9, 7, 10, 0),
                         base_linker_order_id='777'))   # spoza tabeli sprzedaży
    for bl_id, numer in ((2, 'P/2'), (4, 'P/4'), (777, 'P/777')):
        db.session.add(ProductionOrder(baselinker_order_id=bl_id,
                                       internal_order_number=numer))
    db.session.commit()
    stopnie = {s['klucz']: s['liczba'] for s in analytics.lejek_wycen(OD, DO)['stopnie']}
    assert stopnie['w_realizacji'] == 2     # Z4 i 777, bez anulowanego Z2


# --- Eksplorator -----------------------------------------------------------

def test_eksplorator_bez_wykluczonych(app):
    klienci = explorer.klienci_wg_wymiaru('order_source', OD, DO)
    assert set(klienci) == {'shop'}
    assert klienci['shop'] == {'klienci': 2, 'nowi': 2}

    przestawienie = explorer.przestawienie('order_source', 'miesiac', 'netto', OD, DO)
    assert przestawienie['suma']['suma'] == Decimal('1270.00')

    dane = dane_eksploratora('order_source', 'miesiac', 'netto', OD, DO)
    assert dane['miary']['suma']['netto'] == Decimal('1270.00')
    assert dane['miary']['suma']['zamowienia'] == 3
    assert dane['miary']['suma']['klienci'] == 2
    assert dane['liczniki'] == {'zamowienia': 3, 'pozycje': 3}


def test_lista_wartosci_filtra_bez_wartosci_z_samych_wykluczonych(app):
    wartosci = wartosci_wymiaru('order_source', OD, DO)['wartosci']
    assert [w['wartosc'] for w in wartosci] == ['shop']


# --- pulpit w całości: każdy kafelek i segment porównawczy -------------------

def _uklad_wszystkich_typow():
    return [Instancja(klucz, typ.domyslny_wymiar if typ.wymiarowy else None)
            for klucz, typ in KATALOG.items()]


def test_pulpit_i_segment_porownawczy_bez_wykluczonych(app):
    dane = dane_dashboardu(OD, DO, _uklad_wszystkich_typow(),
                           na_dzien=date(2026, 9, 21),
                           porownanie={'caretaker': ['Anna']})
    assert dane['kpi']['netto'] == Decimal('1270.00')
    assert dane['kpi']['zamowienia'] == 3
    assert dane['trend']['biezacy'][8]['netto'] == Decimal('1270.00')
    assert dane['dostawa_koszt_kuriera'] == Decimal('20.00')
    # Segment „Anna": Z1 + Z4, bez nieopłaconego Z3.
    assert dane['porownanie']['kpi']['netto'] == Decimal('1200.00')
    assert dane['porownanie']['kpi']['zamowienia'] == 2
    klienci = dane['karty']['klienci:liczba_zamowien']
    assert klienci['nowi_w_okresie'] == 2
    assert klienci['konwersja']['klientow'] == 2
    naleznosci = dane['karty']['naleznosci:wiek_zamowienia']
    assert sum(k['saldo'] for k in naleznosci['kubelki']) == Decimal('100.00')
    assert naleznosci['nadplaty']['zamowienia'] == 0


# --- Arkusz: pokazuje wszystko, stopka sumuje sprzedaż ----------------------

def test_arkusz_pokazuje_wykluczone_ze_statusem(app):
    from modules.reports.arkusz_service import dane_arkusza

    dane = dane_arkusza(OD, DO)
    po_numerze = {z['bl_id']: z for z in dane['zamowienia']}
    assert set(po_numerze) == {1, 2, 3, 4, 5}
    assert dane['stronicowanie']['zamowien_lacznie'] == 5

    assert po_numerze[1]['poza_sprzedaza'] is None
    assert po_numerze[5]['poza_sprzedaza'] is None
    assert 'Zamówienie anulowane' in po_numerze[2]['poza_sprzedaza']
    assert 'Nowe - nieopłacone' in po_numerze[3]['poza_sprzedaza']
    # Wiersze wykluczone dalej niosą swoje pozycje — Arkusz zastępuje Excela.
    assert len(po_numerze[2]['pozycje']) == 1


def test_stopka_arkusza_zgadza_sie_z_pulpitem(app):
    from modules.reports.arkusz_service import dane_arkusza

    podsumowanie = dane_arkusza(OD, DO)['podsumowanie']
    assert podsumowanie['netto'] == formatuj_liczbe(kpi(OD, DO)['netto'], 2)
    assert podsumowanie['zamowienia'] == 3
    assert podsumowanie['pozycje'] == 3


def test_arkusz_z_filtrem_pozycji_pokazuje_wykluczone_ale_ich_nie_sumuje(app):
    from modules.reports.arkusz_service import dane_arkusza

    dane = dane_arkusza(OD, DO, filtr={'wood_species': ['buk']})
    assert [z['bl_id'] for z in dane['zamowienia']] == [3]
    assert len(dane['zamowienia'][0]['pozycje']) == 1
    assert dane['podsumowanie']['netto'] == formatuj_liczbe(0, 2)
    assert dane['podsumowanie']['zamowienia'] == 0
