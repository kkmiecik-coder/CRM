# -*- coding: utf-8 -*-
"""Agregaty Analizy sprzedazowej.

Test regresyjny na blad, ktory istnial w poprzedniku: saldo i kwota wplaty
byly wartosciami poziomu ZAMOWIENIA powielonymi na kazdej pozycji, wiec
SUM() po wierszach mnozyl je przez liczbe pozycji. Na produkcji 21.09.2026
dawalo to 5 618 320 zl zamiast 741 279 zl.

Tutaj saldo zyje w sales_orders, wiec blad jest niemozliwy z definicji —
ale test pilnuje, ze nikt nie przeniesie go z powrotem na poziom pozycji.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import date
from decimal import Decimal

import pytest
from flask import Flask
from sqlalchemy.pool import StaticPool

from extensions import db
from modules.reports.aggregates import kpi, nadplaty, naleznosci_wg_wieku, wg_wymiaru
from modules.reports.models_sales import SalesClient, SalesOrder, SalesOrderItem

# Import czegokolwiek z modules.reports wykonuje modules/reports/__init__.py
# -> routers.py -> podpakiet modules.users, a User ma relacje db.relationship('Multiplier')
# podana stringiem. SQLAlchemy nie rozwiaze jej, dopoki caly graf modeli nie jest
# zaimportowany — ten sam gotcha i to samo rozwiazanie co w
# tests/test_bot_api_by_token_integration.py.
from modules.calculator.models import (  # noqa: F401 — rejestr mapperów
    Quote, QuoteItem, QuoteItemDetails, Price, Multiplier,
    FinishingOption, EdgeOption, CalculatorSetting, QuoteCounter, QuoteLog,
)
from modules.clients.models import Client  # noqa: F401 — rejestr mapperów
import modules.quotes.models  # noqa: F401 — rejestr mapperów

_TABLES = [m.__table__ for m in (SalesClient, SalesOrder, SalesOrderItem)]


@pytest.fixture()
def app():
    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        'poolclass': StaticPool,
        'connect_args': {'check_same_thread': False},
    }
    db.init_app(app)
    with app.app_context():
        db.metadata.create_all(bind=db.engine, tables=_TABLES)
        yield app
        db.session.remove()


def _zamowienie(bl_id, dzien, saldo, kanal, pozycje):
    """pozycje: lista krotek (value_net, total_volume, group_type)."""
    zam = SalesOrder(baselinker_order_id=bl_id, date_created=dzien,
                     balance_due=Decimal(str(saldo)), order_source=kanal,
                     caretaker='Łukasz Próbny')
    db.session.add(zam)
    db.session.flush()
    for netto, objetosc, grupa in pozycje:
        db.session.add(SalesOrderItem(
            order_id=zam.id, value_net=Decimal(str(netto)),
            total_volume=Decimal(str(objetosc)), group_type=grupa,
            wood_species='dąb', quantity=1))
    return zam


def test_saldo_liczone_raz_na_zamowienie(app):
    """Zamowienie z 34 pozycjami i saldem 9969,32 ma dac 9969,32 — nie 34x tyle."""
    with app.app_context():
        _zamowienie(38623765, date(2026, 10, 5), '9969.32', 'shop',
                    [('100.00', '0.01', 'towar')] * 34)
        db.session.commit()

        wynik = kpi(date(2026, 10, 1), date(2026, 10, 31))
        assert wynik['saldo'] == Decimal('9969.32')


def test_kpi_sumuje_netto_i_objetosc_z_pozycji(app):
    with app.app_context():
        _zamowienie(1, date(2026, 10, 5), '0', 'shop',
                    [('862.40', '0.0448', 'towar'), ('491.04', '0.0288', 'towar')])
        _zamowienie(2, date(2026, 10, 6), '0', 'personal',
                    [('1088.10', '0.0540', 'towar')])
        db.session.commit()

        wynik = kpi(date(2026, 10, 1), date(2026, 10, 31))
        assert wynik['netto'] == Decimal('2441.54')
        assert wynik['objetosc'] == Decimal('0.127600')
        assert wynik['zamowienia'] == 2
        # 2441,54 / 0,1276 m³ = 19 134,33 zł/m³ (zaokrąglone do groszy)
        assert wynik['cena_za_m3'] == Decimal('19134.33')


def test_objetosc_wyklucza_uslugi(app):
    """„Suszenie uslugowe 88m3" to jeden rekord, ktory sam przewracal wykres:
    wrzesien 2025 pokazywal 167 m3 zamiast realnych ~12."""
    with app.app_context():
        _zamowienie(1, date(2026, 10, 5), '0', 'shop',
                    [('862.40', '0.0448', 'towar'), ('14308.94', '88.0', 'usługa')])
        db.session.commit()

        wynik = kpi(date(2026, 10, 1), date(2026, 10, 31))
        assert wynik['objetosc'] == Decimal('0.044800')
        # Netto usługi NIE wypada — usługa też jest sprzedażą.
        assert wynik['netto'] == Decimal('15171.34')


def test_srednie_zamowienie_dzieli_przez_liczbe_zamowien(app):
    with app.app_context():
        _zamowienie(1, date(2026, 10, 5), '0', 'shop', [('1000.00', '0.05', 'towar')] * 3)
        _zamowienie(2, date(2026, 10, 6), '0', 'shop', [('2000.00', '0.10', 'towar')])
        db.session.commit()

        wynik = kpi(date(2026, 10, 1), date(2026, 10, 31))
        assert wynik['zamowienia'] == 2
        assert wynik['srednie_zamowienie'] == Decimal('2500.00')


def test_zakres_dat_odcina_zamowienia_spoza(app):
    with app.app_context():
        _zamowienie(1, date(2026, 9, 30), '0', 'shop', [('999.00', '0.05', 'towar')])
        _zamowienie(2, date(2026, 10, 1), '0', 'shop', [('100.00', '0.01', 'towar')])
        db.session.commit()

        wynik = kpi(date(2026, 10, 1), date(2026, 10, 31))
        assert wynik['netto'] == Decimal('100.00')


def test_wg_wymiaru_grupuje_po_kanale(app):
    with app.app_context():
        _zamowienie(1, date(2026, 10, 5), '0', 'shop', [('1000.00', '0.05', 'towar')])
        _zamowienie(2, date(2026, 10, 6), '0', 'shop', [('500.00', '0.02', 'towar')])
        _zamowienie(3, date(2026, 10, 7), '0', 'personal', [('300.00', '0.01', 'towar')])
        db.session.commit()

        wiersze = wg_wymiaru('order_source', date(2026, 10, 1), date(2026, 10, 31))
        wg_nazwy = {w['wartosc']: w for w in wiersze}
        assert wg_nazwy['shop']['netto'] == Decimal('1500.00')
        assert wg_nazwy['shop']['zamowienia'] == 2
        assert wg_nazwy['personal']['netto'] == Decimal('300.00')


def test_wg_wymiaru_grupuje_po_gatunku_czyli_po_pozycji(app):
    with app.app_context():
        zam = _zamowienie(1, date(2026, 10, 5), '0', 'shop', [])
        db.session.add(SalesOrderItem(order_id=zam.id, wood_species='dąb',
                                      value_net=Decimal('1000.00'),
                                      total_volume=Decimal('0.05'),
                                      group_type='towar', quantity=1))
        db.session.add(SalesOrderItem(order_id=zam.id, wood_species='buk',
                                      value_net=Decimal('400.00'),
                                      total_volume=Decimal('0.03'),
                                      group_type='towar', quantity=1))
        db.session.commit()

        wiersze = wg_wymiaru('wood_species', date(2026, 10, 1), date(2026, 10, 31))
        wg_nazwy = {w['wartosc']: w for w in wiersze}
        assert wg_nazwy['dąb']['netto'] == Decimal('1000.00')
        assert wg_nazwy['buk']['netto'] == Decimal('400.00')


def test_wg_wymiaru_odrzuca_nieznany_wymiar(app):
    with app.app_context():
        with pytest.raises(ValueError, match='nie jest wymiarem'):
            wg_wymiaru('paid_cash', date(2026, 10, 1), date(2026, 10, 31))


def test_naleznosci_wg_wieku(app):
    with app.app_context():
        _zamowienie(1, date(2026, 10, 1), '1000.00', 'shop', [('1000.00', '0.05', 'towar')])
        _zamowienie(2, date(2026, 6, 1), '5000.00', 'shop', [('5000.00', '0.20', 'towar')])
        _zamowienie(3, date(2026, 10, 1), '0', 'shop', [('300.00', '0.01', 'towar')])
        db.session.commit()

        kubelki = {k['kubelek']: k for k in naleznosci_wg_wieku(date(2026, 10, 10))}
        assert kubelki['0-14 dni']['saldo'] == Decimal('1000.00')
        assert kubelki['>90 dni']['saldo'] == Decimal('5000.00')
        # Zamowienie z saldem 0 nie jest naleznoscia.
        assert sum(k['zamowienia'] for k in kubelki.values()) == 2


# --- nadplaty -----------------------------------------------------------

def test_nadplaty_liczy_zamowienia_z_saldem_ujemnym(app):
    """Nadplata wraca jako kwota DODATNIA ('nadplacono X zl') — znak jest
    odwrocony wzgledem surowego balance_due, ktory jest ujemny."""
    with app.app_context():
        _zamowienie(1, date(2026, 10, 1), '-100.00', 'shop', [('100.00', '0.05', 'towar')])
        _zamowienie(2, date(2026, 6, 1), '-50.82', 'shop', [('50.00', '0.02', 'towar')])
        _zamowienie(3, date(2026, 10, 1), '200.00', 'shop', [('300.00', '0.01', 'towar')])
        _zamowienie(4, date(2026, 10, 1), '0', 'shop', [('50.00', '0.01', 'towar')])
        db.session.commit()

        wynik = nadplaty()

        assert wynik['zamowienia'] == 2
        assert wynik['saldo'] == Decimal('150.82')


def test_nadplaty_na_pustej_bazie_nie_wywraca_sie(app):
    with app.app_context():
        assert nadplaty() == {'zamowienia': 0, 'saldo': Decimal('0')}


def test_niezmiennik_naleznosci_minus_nadplaty_rowna_sie_saldo(app):
    """Niezmiennik, ktory pojedyncze testy kart (naleznosci_wg_wieku osobno,
    kpi osobno) nie wychwycily by: suma kubelkow wieku (WYLACZNIE salda
    dodatnie, z definicji `naleznosci_wg_wieku`) minus nadplaty MUSI dac to
    samo, co `kpi()['saldo']` (suma WSZYSTKICH sald, dodatnich i ujemnych),
    kiedy oba zapytania obejmuja ten sam zbior zamowien.

    Zmierzone na zrzucie produkcji 21.09.2026: 741 279,02 (kubelki) minus
    8 860,82 (nadplaty, 13 zamowien) = 732 418,20 (KPI 'Saldo').
    """
    with app.app_context():
        _zamowienie(1, date(2026, 1, 5), '1000.00', 'shop', [('1000.00', '0.10', 'towar')])
        _zamowienie(2, date(2026, 6, 1), '5000.00', 'shop', [('5000.00', '0.20', 'towar')])
        _zamowienie(3, date(2026, 9, 1), '-800.00', 'shop', [('300.00', '0.05', 'towar')])
        _zamowienie(4, date(2026, 9, 5), '-60.82', 'shop', [('120.00', '0.02', 'towar')])
        _zamowienie(5, date(2026, 9, 10), '0', 'shop', [('50.00', '0.01', 'towar')])
        db.session.commit()

        na_dzien = date(2026, 9, 21)
        suma_naleznosci = sum((k['saldo'] for k in naleznosci_wg_wieku(na_dzien)), Decimal('0'))
        suma_nadplat = nadplaty()['saldo']
        saldo_kpi = kpi(date(2026, 1, 1), na_dzien)['saldo']

        assert suma_naleznosci == Decimal('6000.00')
        assert suma_nadplat == Decimal('860.82')
        assert saldo_kpi == Decimal('5139.18')
        assert suma_naleznosci - suma_nadplat == saldo_kpi
