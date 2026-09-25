# -*- coding: utf-8 -*-
import os

from extensions import db
from modules.production.logistics.models import OrderGeo
from tests.logistyka_fixtures import app, zamowienie  # noqa: F401

MIGRACJA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        'migrations', '2026-09-26-logistyka-geolokalizacja.sql')


def test_geo_zamowienia_zapisuje_sie(app):
    with app.app_context():
        order = zamowienie()
        db.session.add(OrderGeo(order_id=order.id, lat=50.062726, lng=19.93962,
                                source='gugik', quality='dokladna', address_hash='a' * 40))
        db.session.commit()
        geo = OrderGeo.query.get(order.id)
        assert float(geo.lat) == 50.062726 and geo.attempts == 0
        assert geo.address_changed_after_manual is False


def test_migracja_geo():
    sql = open(MIGRACJA, encoding='utf-8').read()
    assert 'CREATE TABLE IF NOT EXISTS prod_order_geo' in sql
    assert 'logistyka_geo_dzierzawa' in sql
    assert 'DELIMITER' not in sql
