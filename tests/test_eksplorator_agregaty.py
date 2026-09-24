# -*- coding: utf-8 -*-
"""Agregaty Eksploratora: panel miar i panel przestawienia.

Pilnowane niezmienniki:
1. „Klienci" i „nowi klienci" licza sie po DISTINCT kliencie, nie po zamowieniu.
   Klient z trzema zamowieniami w kanale to jeden klient, nie trzy.
2. Przestawienie po miesiacu dziala na obu dialektach — grupowanie idzie przez
   db.extract, nie przez DATE_FORMAT (MySQL) ani strftime (SQLite).
3. Zmiana procentowa liczy sie miedzy PIERWSZA I OSTATNIA niepusta kolumna,
   a przy zerowej bazie jest None, a nie nieskonczonoscia.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import date, timedelta
from decimal import Decimal

import pytest
from flask import Flask
from sqlalchemy.pool import StaticPool

from extensions import db
from modules.reports.explorer import (
    KLUCZ_POZOSTALE, MAKS_KOLUMN, MAKS_WIERSZY, PRZESTAWIENIE_MIESIAC,
    klienci_wg_wymiaru, przestawienie,
)
from modules.reports.analiza_service import (
    ETYKIETY_WARTOSCI, MIARY_PANELU, dane_eksploratora, opis_z_etykietami,
)
from modules.reports.models_sales import SalesClient, SalesOrder, SalesOrderItem

from modules.calculator.models import (  # noqa: F401 — rejestr mapperów
    Quote, QuoteItem, QuoteItemDetails, Price, Multiplier,
    FinishingOption, EdgeOption, CalculatorSetting, QuoteCounter, QuoteLog,
)
from modules.users.models import User  # noqa: F401 — rejestr mapperów
from modules.clients.models import Client  # noqa: F401 — rejestr mapperów
import modules.quotes.models  # noqa: F401 — rejestr mapperów
from modules.quotes.models import QuoteStatus

_TABLES = [m.__table__ for m in (
    Price, Multiplier, FinishingOption, EdgeOption, CalculatorSetting, User, Client,
    Quote, QuoteItem, QuoteItemDetails, QuoteCounter, QuoteLog, QuoteStatus,
    SalesClient, SalesOrder, SalesOrderItem,
)]


@pytest.fixture()
def app():
    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        'poolclass': StaticPool, 'connect_args': {'check_same_thread': False}}
    db.init_app(app)
    with app.app_context():
        db.metadata.create_all(bind=db.engine, tables=_TABLES)
        yield app
        db.session.remove()


def _klient(first_order_at=None):
    k = SalesClient(orders_count=1, lifetime_net=Decimal('0'),
                    first_order_at=first_order_at, display_name='Klient')
    db.session.add(k)
    db.session.flush()
    return k


def _zamowienie(bl_id, dzien, netto, kanal='shop', klient=None, objetosc='0.50',
                grupa='towar', gatunek='dab', technologia='lity', klasa='A/B',
                saldo='0', pochodzenie=None, grubosc=None, transport=False):
    zam = SalesOrder(baselinker_order_id=bl_id, date_created=dzien,
                     order_source=kanal, balance_due=Decimal(saldo),
                     client_origin=pochodzenie, own_transport=transport,
                     client_id=None if klient is None else klient.id)
    db.session.add(zam)
    db.session.flush()
    db.session.add(SalesOrderItem(
        order_id=zam.id, value_net=Decimal(netto),
        total_volume=Decimal(objetosc), group_type=grupa,
        wood_species=gatunek, technology=technologia, wood_class=klasa,
        thickness_cm=None if grubosc is None else Decimal(grubosc), quantity=1))
    return zam


# --- klienci w przekroju wymiaru --------------------------------------------

def test_klient_z_trzema_zamowieniami_liczy_sie_raz(app):
    with app.app_context():
        k = _klient(first_order_at=date(2026, 9, 1))
        for i in range(3):
            _zamowienie(i + 1, date(2026, 9, 2 + i), '100.00', klient=k)
        db.session.commit()

        wynik = klienci_wg_wymiaru('order_source', date(2026, 9, 1), date(2026, 9, 30))

        assert wynik['shop']['klienci'] == 1


def test_nowy_klient_to_taki_ktorego_pierwsze_zamowienie_jest_w_okresie(app):
    with app.app_context():
        stary = _klient(first_order_at=date(2025, 5, 1))
        nowy = _klient(first_order_at=date(2026, 9, 3))
        _zamowienie(1, date(2026, 9, 3), '100.00', klient=stary)
        _zamowienie(2, date(2026, 9, 4), '100.00', klient=nowy)
        db.session.commit()

        wynik = klienci_wg_wymiaru('order_source', date(2026, 9, 1), date(2026, 9, 30))

        assert wynik['shop'] == {'klienci': 2, 'nowi': 1}


def test_zamowienie_bez_klienta_nie_psuje_licznika(app):
    with app.app_context():
        _zamowienie(1, date(2026, 9, 3), '100.00', klient=None)
        db.session.commit()

        assert klienci_wg_wymiaru('order_source', date(2026, 9, 1), date(2026, 9, 30)) \
            == {'shop': {'klienci': 0, 'nowi': 0}}


def test_klienci_wg_wymiaru_odrzuca_nazwe_spoza_rejestru(app):
    with app.app_context():
        with pytest.raises(ValueError):
            klienci_wg_wymiaru('payment_date', date(2026, 9, 1), date(2026, 9, 30))


# --- przestawienie ----------------------------------------------------------

def test_przestawienie_po_miesiacu_daje_kolumny_w_kolejnosci(app):
    with app.app_context():
        _zamowienie(1, date(2026, 7, 5), '100.00', kanal='shop')
        _zamowienie(2, date(2026, 8, 5), '200.00', kanal='shop')
        _zamowienie(3, date(2026, 9, 5), '300.00', kanal='shop')
        db.session.commit()

        wynik = przestawienie('order_source', PRZESTAWIENIE_MIESIAC, 'netto',
                              date(2026, 7, 1), date(2026, 9, 30))

        assert [k['etykieta'] for k in wynik['kolumny']] == ['lip', 'sie', 'wrz']
        assert wynik['wiersze'][0]['szereg'] == [Decimal('100.00'), Decimal('200.00'),
                                                 Decimal('300.00')]


def test_przestawienie_liczy_zmiane_miedzy_pierwsza_a_ostatnia_kolumna(app):
    with app.app_context():
        _zamowienie(1, date(2026, 7, 5), '100.00')
        _zamowienie(2, date(2026, 9, 5), '267.00')
        db.session.commit()

        wiersz = przestawienie('order_source', PRZESTAWIENIE_MIESIAC, 'netto',
                               date(2026, 7, 1), date(2026, 9, 30))['wiersze'][0]

        assert wiersz['zmiana'] == Decimal('167.0')


def test_przestawienie_przy_zerowej_bazie_nie_zwraca_nieskonczonosci(app):
    """Os ma TRZY kolumny (lip, sie, wrz), bo budujemy ja z zakresu, nie
    z danych. Pierwsza jest zerowa, wiec zmiana jest nieokreslona — gdyby os
    powstawala z danych, byla by jedna kolumna i test nie sprawdzalby niczego."""
    with app.app_context():
        _zamowienie(1, date(2026, 9, 5), '300.00')
        db.session.commit()

        wiersz = przestawienie('order_source', PRZESTAWIENIE_MIESIAC, 'netto',
                               date(2026, 7, 1), date(2026, 9, 30))['wiersze'][0]

        assert wiersz['szereg'][0] == Decimal('0')
        assert wiersz['zmiana'] is None


def test_przestawienie_ma_wiersz_sumy(app):
    with app.app_context():
        _zamowienie(1, date(2026, 9, 5), '100.00', kanal='shop')
        _zamowienie(2, date(2026, 9, 6), '200.00', kanal='allegro')
        db.session.commit()

        wynik = przestawienie('order_source', PRZESTAWIENIE_MIESIAC, 'netto',
                              date(2026, 9, 1), date(2026, 9, 30))

        assert wynik['suma']['suma'] == Decimal('300.00')


def test_przestawienie_po_drugim_wymiarze_a_nie_miesiacu(app):
    with app.app_context():
        _zamowienie(1, date(2026, 9, 5), '100.00', kanal='shop')
        _zamowienie(2, date(2026, 9, 6), '200.00', kanal='allegro')
        db.session.commit()

        wynik = przestawienie('order_source', 'wood_species', 'netto',
                              date(2026, 9, 1), date(2026, 9, 30))

        assert [k['etykieta'] for k in wynik['kolumny']] == ['dab']


def test_przestawienie_w_miarze_objetosc_wyklucza_uslugi(app):
    with app.app_context():
        _zamowienie(1, date(2026, 9, 5), '800.00', objetosc='88.00', grupa='usługa')
        db.session.commit()

        wynik = przestawienie('order_source', PRZESTAWIENIE_MIESIAC, 'objetosc',
                              date(2026, 9, 1), date(2026, 9, 30))

        assert wynik['suma']['suma'] == Decimal('0')


def test_przestawienie_odrzuca_nieznana_miare(app):
    with app.app_context():
        with pytest.raises(ValueError):
            przestawienie('order_source', PRZESTAWIENIE_MIESIAC, 'saldo',
                          date(2026, 9, 1), date(2026, 9, 30))


def test_przestawienie_odrzuca_kolumny_spoza_rejestru(app):
    with app.app_context():
        with pytest.raises(ValueError):
            przestawienie('order_source', 'payment_date', 'netto',
                          date(2026, 9, 1), date(2026, 9, 30))


def test_przestawienie_ma_kolumne_takze_dla_pustego_miesiaca(app):
    """Dziura w osi skleilaby lipiec z wrzesniem i pokazala w iskierce wzrost,
    ktorego nie bylo — ta sama klasa bledu, ktora zamyka szereg_miesieczny."""
    with app.app_context():
        _zamowienie(1, date(2026, 7, 5), '100.00')
        _zamowienie(2, date(2026, 9, 5), '300.00')
        db.session.commit()

        wynik = przestawienie('order_source', PRZESTAWIENIE_MIESIAC, 'netto',
                              date(2026, 7, 1), date(2026, 9, 30))

        assert [k['etykieta'] for k in wynik['kolumny']] == ['lip', 'sie', 'wrz']
        assert wynik['wiersze'][0]['szereg'] == [Decimal('100.00'), Decimal('0'),
                                                 Decimal('300.00')]


def test_etykieta_kolumny_dostaje_rok_po_przejsciu_przez_granice_roku(app):
    """Preset „calosc" siega trzy lata wstecz. Trzy kolumny podpisane `lip`
    byłyby nie do odroznienia."""
    with app.app_context():
        _zamowienie(1, date(2025, 12, 5), '100.00')
        _zamowienie(2, date(2026, 1, 5), '200.00')
        db.session.commit()

        wynik = przestawienie('order_source', PRZESTAWIENIE_MIESIAC, 'netto',
                              date(2025, 12, 1), date(2026, 1, 31))

        assert [k['etykieta'] for k in wynik['kolumny']] == ['gru 25', 'sty 26']


def test_klienci_wg_wymiaru_dziala_dla_wymiaru_zlozonego(app):
    """Kluczem jest krotka skladowych — ta sama umowa co w wg_wymiaru,
    inaczej dane_eksploratora nie dopasowaloby licznikow do wierszy."""
    with app.app_context():
        k = _klient(first_order_at=date(2026, 9, 1))
        _zamowienie(1, date(2026, 9, 2), '100.00', klient=k)
        db.session.commit()

        wynik = klienci_wg_wymiaru('konfiguracja', date(2026, 9, 1), date(2026, 9, 30))

        assert wynik[('dab', 'lity', 'A/B')] == {'klienci': 1, 'nowi': 1}


def test_przestawienie_po_wymiarze_zlozonym_w_wierszach(app):
    with app.app_context():
        _zamowienie(1, date(2026, 9, 5), '100.00', technologia='lity')
        _zamowienie(2, date(2026, 9, 6), '200.00', technologia='mikrowczep')
        db.session.commit()

        wynik = przestawienie('konfiguracja', PRZESTAWIENIE_MIESIAC, 'netto',
                              date(2026, 9, 1), date(2026, 9, 30))

        assert len(wynik['wiersze']) == 2
        assert wynik['wiersze'][0]['wartosc'] == ('dab', 'mikrowczep', 'A/B')
        assert wynik['wiersze'][0]['etykieta'] == 'dab · mikrowczep · A/B'


def test_filtr_zaweza_panel_miar(app):
    with app.app_context():
        _zamowienie(1, date(2026, 9, 2), '300.00', gatunek='dab')
        _zamowienie(2, date(2026, 9, 3), '700.00', gatunek='jesion')
        db.session.commit()

        wynik = dane_eksploratora('order_source', PRZESTAWIENIE_MIESIAC, 'netto',
                                  date(2026, 9, 1), date(2026, 9, 30),
                                  filtr={'wood_species': ['dab']})

        assert wynik['miary']['suma']['netto'] == Decimal('300.00')
        assert wynik['liczniki'] == {'zamowienia': 1, 'pozycje': 1}
        assert wynik['filtr']['tekst'] == 'wood_species:dab'


def test_filtr_zaweza_przestawienie(app):
    with app.app_context():
        _zamowienie(1, date(2026, 9, 2), '300.00', kanal='shop')
        _zamowienie(2, date(2026, 9, 3), '700.00', kanal='allegro')
        db.session.commit()

        wynik = przestawienie('order_source', PRZESTAWIENIE_MIESIAC, 'netto',
                              date(2026, 9, 1), date(2026, 9, 30),
                              filtr={'order_source': ['shop']})

        assert [w['etykieta'] for w in wynik['wiersze']] == ['shop']
        assert wynik['suma']['suma'] == Decimal('300.00')


def test_filtr_po_polu_pozycji_nie_powiela_licznika_zamowien(app):
    """Licznik zamowien w naglowku panelu idzie po SalesOrder — filtr po polu
    pozycji wchodzi tam EXISTS-em, wiec zamowienie z dwunastoma pozycjami
    liczy sie RAZ."""
    with app.app_context():
        zam = SalesOrder(baselinker_order_id=1, date_created=date(2026, 9, 2),
                         order_source='shop', balance_due=Decimal('0'))
        db.session.add(zam)
        db.session.flush()
        for _ in range(12):
            db.session.add(SalesOrderItem(
                order_id=zam.id, value_net=Decimal('100.00'),
                total_volume=Decimal('0.01'), group_type='towar',
                wood_species='dab', technology='lity', wood_class='A/B', quantity=1))
        db.session.commit()

        wynik = dane_eksploratora('order_source', PRZESTAWIENIE_MIESIAC, 'netto',
                                  date(2026, 9, 1), date(2026, 9, 30),
                                  filtr={'wood_species': ['dab']})

        assert wynik['liczniki'] == {'zamowienia': 1, 'pozycje': 12}
        assert wynik['miary']['wiersze'][0]['zamowienia'] == 1


def test_dane_eksploratora_niosa_wymiary_do_filtrowania(app):
    """Popover filtra dostaje TYLKO wymiary proste — po zlozonym nie filtrujemy."""
    with app.app_context():
        _zamowienie(1, date(2026, 9, 2), '500.00')
        db.session.commit()

        wynik = dane_eksploratora('order_source', PRZESTAWIENIE_MIESIAC, 'netto',
                                  date(2026, 9, 1), date(2026, 9, 30))

        nazwy_filtra = {w['nazwa'] for w in wynik['wymiary_filtra']}
        nazwy_osi = {w['nazwa'] for w in wynik['wymiary_dostepne']}
        assert 'konfiguracja' in nazwy_osi
        assert 'konfiguracja' not in nazwy_filtra
        assert wynik['filtr'] == {'tekst': '', 'opis': 'brak'}


# --- panel miar -------------------------------------------------------------

def test_panel_miar_ma_osiem_kolumn_i_wiersz_sumy(app):
    with app.app_context():
        k = _klient(first_order_at=date(2026, 9, 2))
        _zamowienie(1, date(2026, 9, 2), '750.00', kanal='shop', klient=k)
        _zamowienie(2, date(2026, 9, 3), '250.00', kanal='allegro')
        db.session.commit()

        wynik = dane_eksploratora('order_source', PRZESTAWIENIE_MIESIAC, 'netto',
                                  date(2026, 9, 1), date(2026, 9, 30))

        assert MIARY_PANELU == ('netto', 'udzial', 'objetosc', 'zamowienia',
                                'srednie_zamowienie', 'cena_za_m3', 'klienci', 'nowi_klienci')
        wiersz = wynik['miary']['wiersze'][0]
        for miara in MIARY_PANELU:
            assert miara in wiersz
        assert wiersz['netto'] == Decimal('750.00')
        assert wiersz['udzial'] == Decimal('75.0')
        assert wiersz['klienci'] == 1
        assert wiersz['nowi_klienci'] == 1
        assert wynik['miary']['suma']['netto'] == Decimal('1000.00')
        assert wynik['miary']['suma']['udzial'] == Decimal('100.0')


def test_panel_miar_przy_zerowej_objetosci_daje_None_zamiast_dzielenia(app):
    with app.app_context():
        _zamowienie(1, date(2026, 9, 2), '500.00', objetosc='0.00')
        db.session.commit()

        wiersz = dane_eksploratora('order_source', PRZESTAWIENIE_MIESIAC, 'netto',
                                   date(2026, 9, 1), date(2026, 9, 30))['miary']['wiersze'][0]

        assert wiersz['cena_za_m3'] is None


def test_dane_eksploratora_niosa_naglowki_i_liczniki(app):
    with app.app_context():
        _zamowienie(1, date(2026, 9, 2), '500.00')
        db.session.commit()

        wynik = dane_eksploratora('order_source', PRZESTAWIENIE_MIESIAC, 'netto',
                                  date(2026, 9, 1), date(2026, 9, 30))

        assert wynik['wymiar'] == {'nazwa': 'order_source', 'etykieta': 'Kanał sprzedaży'}
        assert wynik['liczniki'] == {'zamowienia': 1, 'pozycje': 1}
        assert wynik['przestawienie']['miara'] == 'netto'


# --- siatka przestawienia: NULL kontra pusty napis ---------------------------

def test_null_i_pusty_napis_w_kolumnie_sumuja_sie_zamiast_nadpisywac(app):
    """_tekst_wartosci mapuje NULL i '' na TEN SAM klucz kolumny (''), a petla
    wypelniajaca siatke przypisywala zamiast dodawac — jedna z dwoch grup
    znikala bez sladu z komorki, z sumy wiersza i z wiersza „Razem".

    Dzis utajone (w zrzucie produkcji zadna kolumna wymiarowa nie ma naraz
    NULL-i i pustych napisow), ale client_origin to dokladnie ta kolumna,
    ktora pierwszy backfill moze zapisac oboma sposobami naraz."""
    with app.app_context():
        _zamowienie(1, date(2026, 9, 5), '1000.00', pochodzenie=None)
        _zamowienie(2, date(2026, 9, 6), '2000.00', pochodzenie='')
        db.session.commit()

        wynik = przestawienie('order_source', 'client_origin', 'netto',
                              date(2026, 9, 1), date(2026, 9, 30))

        assert [k['klucz'] for k in wynik['kolumny']] == ['']
        assert wynik['wiersze'][0]['komorki'][''] == Decimal('3000.00')
        assert wynik['wiersze'][0]['suma'] == Decimal('3000.00')
        assert wynik['suma']['suma'] == Decimal('3000.00')


def test_null_i_pusty_napis_w_WIERSZU_tez_sie_sumuja(app):
    """Ta sama para po stronie wierszy: klucz wiersza to wartosc surowa, wiec
    NULL i '' sa dwoma wierszami — ale suma calosci ma sie zgadzac."""
    with app.app_context():
        _zamowienie(1, date(2026, 9, 5), '1000.00', pochodzenie=None)
        _zamowienie(2, date(2026, 9, 6), '2000.00', pochodzenie='')
        db.session.commit()

        wynik = przestawienie('client_origin', PRZESTAWIENIE_MIESIAC, 'netto',
                              date(2026, 9, 1), date(2026, 9, 30))

        assert wynik['suma']['suma'] == Decimal('3000.00')


# --- kolejnosc kolumn --------------------------------------------------------

def test_kolumny_sortuja_sie_po_wartosci_a_nie_po_jej_zapisie(app):
    """Leksykalnie grubosci szly '0.50', '1.00', '10.00', '2.00', '27.00',
    '3.00' — nikt nie znajdzie tej, ktorej szuka."""
    with app.app_context():
        for i, grubosc in enumerate(['10.00', '2.00', '27.00', '3.00'], start=1):
            _zamowienie(i, date(2026, 9, 5), '100.00', grubosc=grubosc)
        db.session.commit()

        wynik = przestawienie('order_source', 'thickness_cm', 'netto',
                              date(2026, 9, 1), date(2026, 9, 30))

        assert [k['etykieta'] for k in wynik['kolumny']] == \
            ['2.00', '3.00', '10.00', '27.00']


def test_kolumna_pustej_wartosci_idzie_pierwsza(app):
    with app.app_context():
        _zamowienie(1, date(2026, 9, 5), '100.00', grubosc='3.00')
        _zamowienie(2, date(2026, 9, 6), '100.00', grubosc=None)
        db.session.commit()

        wynik = przestawienie('order_source', 'thickness_cm', 'netto',
                              date(2026, 9, 1), date(2026, 9, 30))

        assert [k['etykieta'] for k in wynik['kolumny']] == ['(brak)', '3.00']


# --- limity siatki -----------------------------------------------------------

def test_kolumny_ponad_limit_zwijaja_sie_w_jedna_zbiorcza(app):
    """„Data" jest normalna pozycja w selektorze przestawienia, wiec bez limitu
    przestawienie=Data na produkcyjnych danych daje 406 kolumn i 7,8 MB
    odpowiedzi. Ogon ma sie ZWINAC, nie zniknac — suma musi sie zgadzac."""
    with app.app_context():
        for i in range(MAKS_KOLUMN + 6):
            _zamowienie(i + 1, date(2026, 9, 1) + timedelta(days=i), '100.00')
        db.session.commit()

        wynik = przestawienie('order_source', 'date_created', 'netto',
                              date(2026, 9, 1), date(2026, 9, 30))

        assert len(wynik['kolumny']) == MAKS_KOLUMN + 1
        ostatnia = wynik['kolumny'][-1]
        assert ostatnia['klucz'] == KLUCZ_POZOSTALE
        assert ostatnia['etykieta'] == 'Pozostałe (6)'
        assert ostatnia['zbiorcza'] is True
        # Zadna zlotowka nie zginela.
        assert wynik['suma']['suma'] == Decimal('3000.00')
        assert wynik['wiersze'][0]['komorki'][KLUCZ_POZOSTALE] == Decimal('600.00')


def test_kolumny_ponizej_limitu_nie_dostaja_kolumny_zbiorczej(app):
    with app.app_context():
        for i in range(3):
            _zamowienie(i + 1, date(2026, 9, 1) + timedelta(days=i), '100.00')
        db.session.commit()

        wynik = przestawienie('order_source', 'date_created', 'netto',
                              date(2026, 9, 1), date(2026, 9, 30))

        assert len(wynik['kolumny']) == 3
        assert all('zbiorcza' not in k for k in wynik['kolumny'])


def test_wiersze_ponad_limit_zwijaja_sie_w_jeden_zbiorczy(app):
    """Wymiar „Data" po stronie wierszy to te same 406 pozycji."""
    with app.app_context():
        for i in range(MAKS_WIERSZY + 5):
            _zamowienie(i + 1, date(2026, 9, 1) + timedelta(days=i), '100.00')
        db.session.commit()

        wynik = przestawienie('date_created', PRZESTAWIENIE_MIESIAC, 'netto',
                              date(2026, 9, 1), date(2026, 11, 30))

        assert len(wynik['wiersze']) == MAKS_WIERSZY
        ogon = wynik['wiersze'][-1]
        assert ogon['zbiorczy'] is True
        assert ogon['etykieta'] == 'Pozostałe (6)'
        assert ogon['suma'] == Decimal('600.00')
        # Suma calosci zostaje nietknieta — ogon jest ZWINIETY, nie uciety.
        assert wynik['suma']['suma'] == Decimal('4500.00')


def test_dwa_wymiary_czasowe_nie_wysadzaja_siatki(app):
    """Data x Data to przypadek, ktory zawieszal przegladarke."""
    with app.app_context():
        for i in range(60):
            _zamowienie(i + 1, date(2026, 9, 1) + timedelta(days=i), '100.00')
        db.session.commit()

        wynik = przestawienie('date_created', 'date_created', 'netto',
                              date(2026, 9, 1), date(2026, 11, 30))

        assert len(wynik['wiersze']) <= MAKS_WIERSZY
        assert len(wynik['kolumny']) <= MAKS_KOLUMN + 1
        assert wynik['suma']['suma'] == Decimal('6000.00')


# --- trend tylko na osi czasu ------------------------------------------------

def test_przy_drugim_wymiarze_nie_ma_trendu_ani_zmiany(app):
    """„Trend" i „Zmiana" licza sie z pierwszej kolumny kontra ostatnia. Przy
    osi, ktora nie jest czasem, to porownanie sprzedazy jednego opiekuna
    ze sprzedaza drugiego — podane jako wzrost, na zielono (zmierzone:
    +310,7% dla wiersza „personal" i +656,9% dla „Razem")."""
    with app.app_context():
        _zamowienie(1, date(2026, 9, 5), '100.00', gatunek='dab')
        _zamowienie(2, date(2026, 9, 6), '800.00', gatunek='jesion')
        db.session.commit()

        wynik = przestawienie('order_source', 'wood_species', 'netto',
                              date(2026, 9, 1), date(2026, 9, 30))

        assert wynik['trend'] is False
        assert wynik['wiersze'][0]['zmiana'] is None
        assert wynik['wiersze'][0]['szereg'] is None
        assert wynik['suma']['zmiana'] is None
        assert wynik['suma']['szereg'] is None


def test_na_osi_miesiecznej_trend_i_zmiana_zostaja(app):
    with app.app_context():
        _zamowienie(1, date(2026, 8, 5), '100.00')
        _zamowienie(2, date(2026, 9, 6), '300.00')
        db.session.commit()

        wynik = przestawienie('order_source', PRZESTAWIENIE_MIESIAC, 'netto',
                              date(2026, 8, 1), date(2026, 9, 30))

        assert wynik['trend'] is True
        assert wynik['wiersze'][0]['zmiana'] == Decimal('200.0')
        assert wynik['wiersze'][0]['szereg'] == [Decimal('100.00'), Decimal('300.00')]


# --- niezmiennik MIEDZYPANELOWY: ta sama wartosc -> ta sama etykieta --------
#
# Pojedyncze testy panelu przechodzily, bo kazdy sprawdzal tylko siebie.
# Dokladnie ta luka przepuscila caly klaster „shop" kontra „Sklep".

def _mapa_etykiet_miar(dane):
    return {str(w['wartosc']): w['etykieta'] for w in dane['miary']['wiersze']}


def test_przestawienie_pokazuje_te_same_etykiety_co_panel_miar(app):
    """Ten sam ekran pokazywal „Sklep / Reczne w BL / Allegro" u gory
    i „shop / personal / allegro" na dole (ogledziny 22.09.2026)."""
    with app.app_context():
        _zamowienie(1, date(2026, 9, 2), '300.00', kanal='shop')
        _zamowienie(2, date(2026, 9, 3), '700.00', kanal='personal')
        _zamowienie(3, date(2026, 9, 4), '200.00', kanal='allegro')
        db.session.commit()

        dane = dane_eksploratora('order_source', PRZESTAWIENIE_MIESIAC, 'netto',
                                 date(2026, 9, 1), date(2026, 9, 30))

        miary = _mapa_etykiet_miar(dane)
        assert miary['shop'] == 'Sklep'
        for wiersz in dane['przestawienie']['wiersze']:
            assert wiersz['etykieta'] == miary[str(wiersz['wartosc'])]


def test_naglowki_kolumn_przestawienia_tez_ida_przez_mape_etykiet(app):
    """Druga os tej samej klasy bledu: kolumny wracaly jako ['allegro', 'shop'],
    a przy own_transport/picked_up jako angielskie 'False'."""
    with app.app_context():
        _zamowienie(1, date(2026, 9, 2), '300.00', kanal='shop')
        _zamowienie(2, date(2026, 9, 3), '700.00', kanal='personal')
        db.session.commit()

        dane = dane_eksploratora('caretaker', 'order_source', 'netto',
                                 date(2026, 9, 1), date(2026, 9, 30))

        etykiety = [k['etykieta'] for k in dane['przestawienie']['kolumny']]
        assert 'Ręczne w BL' in etykiety and 'Sklep' in etykiety
        assert 'shop' not in etykiety and 'personal' not in etykiety


def test_kolumna_logiczna_nie_pokazuje_angielskiego_False(app):
    with app.app_context():
        _zamowienie(1, date(2026, 9, 2), '300.00', transport=True)
        _zamowienie(2, date(2026, 9, 3), '700.00', transport=False)
        db.session.commit()

        dane = dane_eksploratora('order_source', 'own_transport', 'netto',
                                 date(2026, 9, 1), date(2026, 9, 30))

        etykiety = sorted(k['etykieta'] for k in dane['przestawienie']['kolumny'])
        assert etykiety == ['Nie', 'Tak']


def test_os_miesieczna_zachowuje_wlasne_etykiety(app):
    """Miesiac nie jest wymiarem z rejestru — przemapowanie zepsuloby 'wrz'."""
    with app.app_context():
        _zamowienie(1, date(2026, 8, 5), '100.00')
        _zamowienie(2, date(2026, 9, 6), '300.00')
        db.session.commit()

        dane = dane_eksploratora('order_source', PRZESTAWIENIE_MIESIAC, 'netto',
                                 date(2026, 8, 1), date(2026, 9, 30))

        assert [k['etykieta'] for k in dane['przestawienie']['kolumny']] == ['sie', 'wrz']


def test_niezmiennik_dla_kazdego_wymiaru_z_mapa_etykiet(app):
    """Przebieg po WSZYSTKICH wymiarach ze slownikiem etykiet — zamyka klase
    bledu, a nie pojedynczy przypadek."""
    with app.app_context():
        _zamowienie(1, date(2026, 9, 2), '300.00', kanal='shop', transport=True)
        _zamowienie(2, date(2026, 9, 3), '700.00', kanal='personal', transport=False)
        db.session.commit()

        for wymiar in ETYKIETY_WARTOSCI:
            dane = dane_eksploratora(wymiar, PRZESTAWIENIE_MIESIAC, 'netto',
                                     date(2026, 9, 1), date(2026, 9, 30))
            miary = _mapa_etykiet_miar(dane)
            for wiersz in dane['przestawienie']['wiersze']:
                assert wiersz['etykieta'] == miary[str(wiersz['wartosc'])], wymiar


def test_wiersz_zlozony_z_samych_pustych_skladowych_ma_czytelna_etykiete(app):
    """Straznik `tekst if tekst.strip()` nie lapal napisu zlozonego z samych
    separatorow — panel przestawienia pokazywal ' ·  · ' (gole kropki)."""
    with app.app_context():
        _zamowienie(1, date(2026, 9, 2), '300.00',
                    gatunek=None, technologia=None, klasa=None)
        db.session.commit()

        dane = dane_eksploratora('konfiguracja', PRZESTAWIENIE_MIESIAC, 'netto',
                                 date(2026, 9, 1), date(2026, 9, 30))

        assert dane['przestawienie']['wiersze'][0]['etykieta'] == '(brak) · (brak) · (brak)'
        assert dane['miary']['wiersze'][0]['etykieta'] == '(brak) · (brak) · (brak)'


def test_opis_filtra_eksploratora_jest_w_tym_samym_jezyku_co_chip(app):
    """Kontrolka „Filtr" pokazywala 'Kanał sprzedaży: shop, personal', a chip
    segmentu na dashboardzie 'Kanał sprzedaży: Sklep, Ręczne w BL'."""
    with app.app_context():
        _zamowienie(1, date(2026, 9, 2), '300.00', kanal='shop')
        db.session.commit()

        dane = dane_eksploratora('caretaker', PRZESTAWIENIE_MIESIAC, 'netto',
                                 date(2026, 9, 1), date(2026, 9, 30),
                                 filtr={'order_source': ['shop', 'personal']})

        assert dane['filtr']['opis'] == 'Kanał sprzedaży: Sklep, Ręczne w BL'
        assert dane['filtr']['opis'] == opis_z_etykietami(
            {'order_source': ['shop', 'personal']})


def test_etykieta_logiczna_dziala_dla_wartosci_z_adresu(app):
    """Wartosci filtra ZAWSZE przychodza z adresu jako napisy, a mapa jest
    kluczowana boolem — chip pokazywal 'Transport własny: False'."""
    assert opis_z_etykietami({'own_transport': ['False']}) == 'Transport własny: Nie'
    assert opis_z_etykietami({'own_transport': ['true']}) == 'Transport własny: Tak'
    assert opis_z_etykietami({'picked_up': ['0']}) == 'Odebrane: Nieodebrane'


def test_eksplorator_tez_pokazuje_stan_na_w_czasie_polskim(app):
    import pytz
    from datetime import datetime as _dt

    strefa = pytz.timezone('Europe/Warsaw')
    with app.app_context():
        przed = _dt.now(strefa).strftime('%H:%M')
        dane = dane_eksploratora('order_source', PRZESTAWIENIE_MIESIAC, 'netto',
                                 date(2026, 9, 1), date(2026, 9, 30))
        po = _dt.now(strefa).strftime('%H:%M')

    assert dane['okres']['stan_na'] in (przed, po)


# --- jednostki --------------------------------------------------------------

def test_payload_eksploratora_niesie_etykiety_miar_z_jednostkami(app):
    """Naglowek kolumny i naglowek eksportu CSV maja mowic to samo — CSV
    bierze `miary.etykiety` wprost, wiec jednostka musi tam byc."""
    from modules.reports.analiza_service import JEDNOSTKI_MIAR

    with app.app_context():
        _zamowienie(1, date(2026, 9, 2), '500.00')
        db.session.commit()

        wynik = dane_eksploratora('order_source', PRZESTAWIENIE_MIESIAC, 'netto',
                                  date(2026, 9, 1), date(2026, 9, 30))

        assert set(wynik['miary']['jednostki']) == set(MIARY_PANELU)
        for miara in MIARY_PANELU:
            jednostka = JEDNOSTKI_MIAR[miara]
            assert wynik['miary']['jednostki'][miara] == jednostka
            assert wynik['miary']['etykiety'][miara].endswith(jednostka), (
                f"{miara}: etykieta {wynik['miary']['etykiety'][miara]!r} "
                f"nie konczy sie jednostka {jednostka!r}"
            )


def test_przestawienie_podpisuje_miare_raz_w_tytule_panelu(app):
    """Komorki przestawienia to jedna miara powtorzona w kilkunastu kolumnach
    miesiecy — jednostka nalezy sie raz, a nie przy kazdej liczbie."""
    with app.app_context():
        _zamowienie(1, date(2026, 9, 2), '500.00')
        db.session.commit()

        for miara, oczekiwana in (('netto', 'Netto\u00a0zł'),
                                  ('objetosc', 'Objętość\u00a0m³'),
                                  ('zamowienia', 'Zamówienia\u00a0szt.')):
            wynik = dane_eksploratora('order_source', PRZESTAWIENIE_MIESIAC, miara,
                                      date(2026, 9, 1), date(2026, 9, 30))
            assert wynik['przestawienie']['etykieta_miary'] == oczekiwana


def test_selektor_miary_przestawienia_pokazuje_jednostke(app):
    with app.app_context():
        _zamowienie(1, date(2026, 9, 2), '500.00')
        db.session.commit()

        wynik = dane_eksploratora('order_source', PRZESTAWIENIE_MIESIAC, 'netto',
                                  date(2026, 9, 1), date(2026, 9, 30))

        for pozycja in wynik['miary_przestawienia']:
            assert '\u00a0' in pozycja['etykieta'], pozycja
