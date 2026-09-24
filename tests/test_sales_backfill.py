# -*- coding: utf-8 -*-
"""Backfill z baselinker_reports_orders do trzech nowych tabel.

Najwazniejszy test to ten, ktory pilnuje, ze sumy sie zgadzaja przed i po.
Backfill, ktory po cichu gubi 2% sprzedazy, jest gorszy niz brak backfillu —
nikt go nie zauwazy, dopoki ktos nie porowna raportu z ksiegowoscia.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import date, datetime
from decimal import Decimal

import pytest
from flask import Flask
from sqlalchemy.pool import StaticPool

from extensions import db
from modules.reports.models import BaselinkerReportOrder
from modules.reports.models_sales import SalesClient, SalesOrder, SalesOrderItem

# Import czegokolwiek z modules.reports wykonuje modules/reports/__init__.py
# -> routers.py -> podpakiet modules.users, a User ma relacje db.relationship('Multiplier')
# podana stringiem. SQLAlchemy nie rozwiaze jej, dopoki caly graf modeli nie jest
# zaimportowany — ten sam gotcha i to samo rozwiazanie co w
# tests/test_bot_api_by_token_integration.py. Po zadaniu 5 tabela nazywa sie `leads`,
# ale KLASA dalej nazywa sie Client, wiec ten import jest poprawny takze wtedy.
from modules.calculator.models import (  # noqa: F401 — rejestr mapperów
    Quote, QuoteItem, QuoteItemDetails, Price, Multiplier,
    FinishingOption, EdgeOption, CalculatorSetting, QuoteCounter, QuoteLog,
)
from modules.clients.models import Client  # noqa: F401 — rejestr mapperów
import modules.quotes.models  # noqa: F401 — rejestr mapperów

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'scripts'))
from backfill_sales_tables import porownaj_sumy, przenies_wiersze  # noqa: E402

_TABLES = [m.__table__ for m in
           (BaselinkerReportOrder, SalesClient, SalesOrder, SalesOrderItem)]


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


def _stary_wiersz(bl_id, netto, objetosc, saldo, email, gatunek='dąb', updated_at=None):
    """Wiersz w starym ksztalcie: pola zamowienia POWIELONE na kazdej pozycji."""
    w = BaselinkerReportOrder(
        date_created=date(2026, 9, 1),
        baselinker_order_id=bl_id,
        customer_name='Jan Makietowy',
        email=email,
        phone='500200300',
        caretaker='Łukasz Próbny',
        order_source='shop',
        delivery_state='śląskie',
        value_net=Decimal(str(netto)),
        total_volume=Decimal(str(objetosc)),
        balance_due=Decimal(str(saldo)),
        paid_amount_net=Decimal('0'),
        wood_species=gatunek,
        technology='lity',
        wood_class='A/B',
        group_type='towar',
        quantity=1,
    )
    if updated_at is not None:
        # Jawne ustawienie updated_at — potrzebne do testowania deterministycznego
        # sortowania po świeżości; kolumna ma onupdate, więc default z modelu
        # zadziałałby dopiero przy UPDATE, nie przy pierwszym INSERT.
        w.updated_at = updated_at
    return w


def test_trzy_pozycje_jednego_zamowienia_daja_jedno_zamowienie(app):
    with app.app_context():
        for _ in range(3):
            db.session.add(_stary_wiersz(50854536, '100.00', '0.01', '9969.32',
                                         'jan@example.com'))
        db.session.commit()

        przenies_wiersze(BaselinkerReportOrder.query.all())
        db.session.commit()

        assert SalesOrder.query.count() == 1
        assert SalesOrderItem.query.count() == 3


def test_saldo_nie_jest_powielane(app):
    """Trzy pozycje x 9969,32 w starej tabeli = 9969,32 w nowej. Nie 29907,96."""
    with app.app_context():
        for _ in range(3):
            db.session.add(_stary_wiersz(1, '100.00', '0.01', '9969.32', 'a@b.pl'))
        db.session.commit()

        przenies_wiersze(BaselinkerReportOrder.query.all())
        db.session.commit()

        assert SalesOrder.query.one().balance_due == Decimal('9969.32')


def test_netto_i_objetosc_sumuja_sie_z_pozycji(app):
    with app.app_context():
        db.session.add(_stary_wiersz(1, '862.40', '0.0448', '0', 'a@b.pl'))
        db.session.add(_stary_wiersz(1, '491.04', '0.0288', '0', 'a@b.pl'))
        db.session.commit()

        przenies_wiersze(BaselinkerReportOrder.query.all())
        db.session.commit()

        raport = porownaj_sumy()
        assert raport['stare_netto'] == raport['nowe_netto'] == Decimal('1353.44')
        assert raport['zgodne'] is True


def test_klienci_sa_deduplikowani_po_mailu(app):
    with app.app_context():
        db.session.add(_stary_wiersz(1, '100.00', '0.01', '0', 'JAN@example.com'))
        db.session.add(_stary_wiersz(2, '200.00', '0.02', '0', 'jan@EXAMPLE.com'))
        db.session.commit()

        przenies_wiersze(BaselinkerReportOrder.query.all())
        db.session.commit()

        assert SalesClient.query.count() == 1
        assert SalesOrder.query.count() == 2
        klient = SalesClient.query.one()
        assert klient.orders_count == 2
        assert klient.lifetime_net == Decimal('300.00')


def test_ponowne_uruchomienie_nie_duplikuje(app):
    """Backfill musi dac sie powtorzyc — pierwsze przejscie moze paść w polowie."""
    with app.app_context():
        db.session.add(_stary_wiersz(1, '100.00', '0.01', '0', 'a@b.pl'))
        db.session.commit()

        przenies_wiersze(BaselinkerReportOrder.query.all())
        db.session.commit()
        przenies_wiersze(BaselinkerReportOrder.query.all())
        db.session.commit()

        assert SalesOrder.query.count() == 1
        assert SalesOrderItem.query.count() == 1


def test_raport_wykrywa_rozjazd(app):
    with app.app_context():
        db.session.add(_stary_wiersz(1, '100.00', '0.01', '0', 'a@b.pl'))
        db.session.commit()
        # Nowa tabela pusta — backfillu nie uruchamiamy.
        raport = porownaj_sumy()
        assert raport['zgodne'] is False
        assert raport['roznica_netto'] == Decimal('100.00')


def test_wiersz_bez_numeru_bl_nie_jest_migrowany(app):
    """Wiersz reczny (bez baselinker_order_id) nie da sie przeniesc idempotentnie
    — nie ma kolumny wiazacej z rekordem zrodlowym. Skrypt go liczy i pomija,
    zamiast migrowac polowicznie."""
    with app.app_context():
        db.session.add(_stary_wiersz(None, '100.00', '0.01', '0', 'a@b.pl'))
        db.session.commit()

        stat = przenies_wiersze(BaselinkerReportOrder.query.all())
        db.session.commit()

        assert SalesOrder.query.count() == 0
        assert SalesOrderItem.query.count() == 0
        assert stat['bez_numeru_bl'] == 1
        assert stat['zamowienia'] == 0


def test_rozbiezne_saldo_wygrywa_najswiezszy_wiersz(app):
    """Przy rozbieznym balance_due w duplikatach wygrywa wartosc z wiersza
    o najpozniejszym updated_at, a rozbieznosc jest odnotowana w statystykach —
    nie cichy wybor MAX-a jak w starym kodzie.

    Najswiezszy wiersz (200.00, updated_at 09-05) ma celowo NAJNIZSZE saldo
    z trojki (800.00, 500.00, 200.00) — gdyby test dobrac tak, ze najswiezszy
    jest jednoczesnie maksimum, asercja przeszlaby zarowno dla nowej logiki
    (najswiezszy), jak i dla starej, blednej (MAX), i nie lapalaby regresji.
    """
    with app.app_context():
        db.session.add(_stary_wiersz(1, '100.00', '0.01', '800.00', 'a@b.pl',
                                     updated_at=datetime(2026, 9, 1, 10, 0, 0)))
        db.session.add(_stary_wiersz(1, '100.00', '0.01', '500.00', 'a@b.pl',
                                     updated_at=datetime(2026, 9, 3, 10, 0, 0)))
        db.session.add(_stary_wiersz(1, '100.00', '0.01', '200.00', 'a@b.pl',
                                     updated_at=datetime(2026, 9, 5, 10, 0, 0)))
        db.session.commit()

        stat = przenies_wiersze(BaselinkerReportOrder.query.all())
        db.session.commit()

        assert SalesOrder.query.one().balance_due == Decimal('200.00')
        assert stat['rozbiezne_saldo'] == 1


def test_anulowane_i_nieoplacone_nie_wchodza_do_licznikow_klienta(app):
    """Partia E, punkt E5: denormalizacja klienta liczy wyłącznie sprzedaż.
    Zamówienie anulowane i nieopłacone przenosimy (Arkusz ma je pokazać),
    ale do `orders_count`, `lifetime_net` i dat klienta nie wchodzą."""
    with app.app_context():
        oplacone = _stary_wiersz(1, '100.00', '0.01', '0', 'jan@example.com')
        oplacone.baselinker_status_id = 138624
        oplacone.date_created = date(2026, 9, 5)
        anulowane = _stary_wiersz(2, '200.00', '0.02', '0', 'jan@example.com')
        anulowane.baselinker_status_id = 138625
        anulowane.date_created = date(2026, 9, 1)
        nieoplacone = _stary_wiersz(3, '400.00', '0.04', '400.00', 'jan@example.com')
        nieoplacone.baselinker_status_id = 105112
        nieoplacone.date_created = date(2026, 9, 9)
        tylko_anulowane = _stary_wiersz(4, '50.00', '0.01', '0', 'ewa@example.com')
        tylko_anulowane.baselinker_status_id = 138625
        # Inny telefon — deduplikacja łączy klientów także po numerze telefonu.
        tylko_anulowane.phone = '501502503'
        db.session.add_all([oplacone, anulowane, nieoplacone, tylko_anulowane])
        db.session.commit()

        przenies_wiersze(BaselinkerReportOrder.query.all())
        db.session.commit()

        assert SalesOrder.query.count() == 4
        jan = SalesClient.query.filter_by(email_norm='jan@example.com').one()
        assert jan.orders_count == 1
        assert jan.lifetime_net == Decimal('100.00')
        assert jan.first_order_at == date(2026, 9, 5)
        assert jan.last_order_at == date(2026, 9, 5)
        ewa = SalesClient.query.filter_by(email_norm='ewa@example.com').one()
        assert (ewa.orders_count, ewa.lifetime_net, ewa.first_order_at) == (0, Decimal('0'), None)
