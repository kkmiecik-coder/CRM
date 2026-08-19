# -*- coding: utf-8 -*-
"""
Alerty terminów na dashboardzie produkcji — grupowanie po zamówieniu
i wybór stanowiska pokazywanego w kaflu.

Sedno: alert dotyczy CAŁEGO zamówienia, a jego pozycje potrafią stać na
różnych stanowiskach. Pokazujemy to NAJMNIEJ zaawansowane — bo to ono
blokuje wysyłkę. Gdyby serwis pokazywał którekolwiek inne (np. pierwsze
z brzegu albo najdalej posunięte), planista czytałby z dashboardu, że
zamówienie jest przy pakowaniu, podczas gdy połowa desek leży jeszcze
przed wycinarką.
"""
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from flask import Flask
from sqlalchemy.pool import StaticPool

from extensions import db
from modules.production.models import (
    ProductionConfiguration, ProductionOrder, ProductionProduct,
)
from modules.users.models import User
# Bez tych importów configure_mappers() wywala się na relationship('Multiplier')
# / ('Client') / ('QuoteStatus') — jak w tests/test_archive_tab.py.
from modules.calculator.models import Multiplier  # noqa: F401
from modules.clients.models import Client  # noqa: F401
import modules.quotes.models  # noqa: F401

from modules.production.services.dashboard_alerts import build_deadline_alerts

# LONGTEXT (MySQL) nie istnieje w SQLite
ProductionOrder.__table__.c.shipping_label_base64.type = db.Text()

TABLES = [m.__table__ for m in (
    User, ProductionOrder, ProductionProduct, ProductionConfiguration,
)]


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
        db.metadata.create_all(bind=db.engine, tables=TABLES)
        yield app
        db.session.remove()


def _zamowienie(bl_id, pozycje, client_name='Jan Kowalski'):
    """
    pozycje: lista dictów z kluczami `status` i `deadline` (dni od dziś).
    """
    cfg = ProductionConfiguration.query.first()
    if not cfg:
        cfg = ProductionConfiguration(species='dąb', technology='lity',
                                      wood_class='A/B')
        db.session.add(cfg)
        db.session.flush()

    order = ProductionOrder(
        baselinker_order_id=bl_id,
        internal_order_number=f'{bl_id}/2026',
        client_name=client_name,
    )
    db.session.add(order)
    db.session.flush()

    for idx, poz in enumerate(pozycje, start=1):
        db.session.add(ProductionProduct(
            order_id=order.id,
            configuration_id=cfg.id,
            short_product_id=f'{bl_id}_{idx}',
            product_sequence_in_order=idx,
            original_product_name='Blat dębowy',
            current_status=poz['status'],
            deadline_date=date.today() + timedelta(days=poz.get('deadline', 1)),
            quantity=1,
        ))
    db.session.commit()
    return order


def test_zamowienie_jednolite_pokazuje_swoje_stanowisko(app):
    with app.app_context():
        _zamowienie(1001, [
            {'status': 'czeka_na_sklejanie'},
            {'status': 'czeka_na_sklejanie'},
        ])

        alerty = build_deadline_alerts()

        assert len(alerty) == 1
        assert alerty[0]['station_code'] == 'gluing'
        assert alerty[0]['station_label'] == 'Sklejanie'
        # Jednolite zamówienie nie ma czego doliczać — brak "+N" w kaflu.
        assert alerty[0]['other_stations_count'] == 0


def test_zamowienie_mieszane_pokazuje_waskie_gardlo(app):
    with app.app_context():
        _zamowienie(1002, [
            {'status': 'czeka_na_pakowanie'},
            {'status': 'czeka_na_wyciecie'},
        ])

        alerty = build_deadline_alerts()

        assert alerty[0]['station_code'] == 'cutting'
        assert alerty[0]['other_stations_count'] == 1
        assert alerty[0]['products_count'] == 2


def test_wstrzymane_bije_kazde_stanowisko(app):
    with app.app_context():
        _zamowienie(1003, [
            {'status': 'czeka_na_pakowanie'},
            {'status': 'wstrzymane'},
        ])

        alerty = build_deadline_alerts()

        assert alerty[0]['station_code'] == 'hold'
        assert alerty[0]['station_label'] == 'Wstrzymane'


def test_liczy_tylko_rozne_stanowiska_a_nie_pozycje(app):
    """
    Licznik "+N" mówi o STANOWISKACH, nie o pozycjach. Trzy deski czekające
    razem przy pakowaniu to jedno dodatkowe miejsce na hali, nie trzy.
    """
    with app.app_context():
        _zamowienie(1004, [
            {'status': 'czeka_na_wyciecie'},
            {'status': 'czeka_na_pakowanie'},
            {'status': 'czeka_na_pakowanie'},
            {'status': 'czeka_na_pakowanie'},
        ])

        alerty = build_deadline_alerts()

        assert alerty[0]['other_stations_count'] == 1
        assert alerty[0]['products_count'] == 4


def test_grupowanie_bierze_najwczesniejszy_deadline(app):
    with app.app_context():
        _zamowienie(1005, [
            {'status': 'czeka_na_wyciecie', 'deadline': 3},
            {'status': 'czeka_na_pakowanie', 'deadline': -2},
        ])

        alerty = build_deadline_alerts()

        assert alerty[0]['days_remaining'] == -2
        assert alerty[0]['deadline_date'] == date.today() - timedelta(days=2)
        assert alerty[0]['deadline_date_formatted'] == (
            date.today() - timedelta(days=2)).strftime('%d.%m.%Y')


def test_pomija_spakowane_anulowane_i_odlegle_terminy(app):
    """
    Anulowane zamówienie nie ma terminu do dotrzymania. Dopóki wchodziło do
    alertów, siedziało na górze kafla z czerwonym „-68 DNI" i spychało w dół
    zamówienia, które ktoś realnie musi zdążyć zrobić.
    """
    with app.app_context():
        _zamowienie(1006, [{'status': 'spakowane', 'deadline': 0}])
        _zamowienie(1007, [{'status': 'czeka_na_wyciecie', 'deadline': 30}])
        _zamowienie(1008, [{'status': 'czeka_na_wyciecie', 'deadline': 2}])
        _zamowienie(1013, [{'status': 'anulowane', 'deadline': -60}])

        alerty = build_deadline_alerts()

        assert [a['baselinker_order_id'] for a in alerty] == [1008]


def test_anulowana_pozycja_nie_zabiera_miejsca_w_zamowieniu(app):
    """
    Zamówienie żyje dalej, gdy anulowano JEDNĄ z jego pozycji — ale licznik
    produktów i wybór stanowiska mają wtedy widzieć tylko to, co zostało.
    """
    with app.app_context():
        _zamowienie(1014, [
            {'status': 'anulowane'},
            {'status': 'czeka_na_pakowanie'},
        ])

        alerty = build_deadline_alerts()

        assert alerty[0]['products_count'] == 1
        assert alerty[0]['station_code'] == 'packaging'
        assert alerty[0]['other_stations_count'] == 0


def test_sortuje_po_pozostalych_dniach_i_respektuje_limit(app):
    with app.app_context():
        _zamowienie(1009, [{'status': 'czeka_na_wyciecie', 'deadline': 2}])
        _zamowienie(1010, [{'status': 'czeka_na_wyciecie', 'deadline': -5}])
        _zamowienie(1011, [{'status': 'czeka_na_wyciecie', 'deadline': 0}])

        wszystkie = build_deadline_alerts()
        assert [a['baselinker_order_id'] for a in wszystkie] == [1010, 1011, 1009]

        assert [a['baselinker_order_id'] for a in build_deadline_alerts(limit=2)] == [1010, 1011]


def test_nieznany_status_nie_wywraca_kafla(app):
    """
    Enum dopuszcza statusy spoza pipeline'u ('w_realizacji'). Kafel ma je
    przeżyć z czytelną etykietą, a nie zniknąć albo pokazać surowy enum.
    """
    with app.app_context():
        _zamowienie(1012, [{'status': 'w_realizacji'}])

        alerty = build_deadline_alerts()

        assert alerty[0]['station_code'] == 'unknown'
        assert alerty[0]['station_label'] == 'W realizacji'
