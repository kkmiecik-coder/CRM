# -*- coding: utf-8 -*-
import os
import re
from datetime import date

import pytest
from sqlalchemy.exc import IntegrityError

from extensions import db
from modules.production.logistics.models import Route, RouteStop, Vehicle
from modules.production.models import ProductionWorker
from tests.logistyka_fixtures import app, kierowca, pojazd, zamowienie  # noqa: F401

MIGRACJA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        'migrations', '2026-09-27-logistyka-trasy-flota.sql')
MIGRACJA_KIEROWCOW = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                  'migrations', '2026-09-28-logistyka-kierowcy.sql')


def test_trasa_z_przystankami_w_kolejnosci(app):
    with app.app_context():
        v, k = pojazd(), kierowca()
        trasa = Route(name='Kraków', date_from=date(2026, 10, 1), date_to=date(2026, 10, 2),
                      vehicle_id=v.id, driver_worker_id=k.id)
        db.session.add(trasa)
        db.session.flush()
        a, b = zamowienie(), zamowienie()
        db.session.add_all([RouteStop(route_id=trasa.id, order_id=b.id, position=2),
                            RouteStop(route_id=trasa.id, order_id=a.id, position=1)])
        db.session.commit()
        assert trasa.status == 'robocza'
        assert [s.order_id for s in trasa.stops] == [a.id, b.id]
        assert trasa.vehicle.name == v.name and trasa.driver.first_name == 'Jan'


def test_zamowienie_na_jednej_trasie(app):
    with app.app_context():
        o = zamowienie()
        t1 = Route(name='A', date_from=date(2026, 10, 1), date_to=date(2026, 10, 1))
        t2 = Route(name='B', date_from=date(2026, 10, 1), date_to=date(2026, 10, 1))
        db.session.add_all([t1, t2])
        db.session.flush()
        db.session.add_all([RouteStop(route_id=t1.id, order_id=o.id, position=1),
                            RouteStop(route_id=t2.id, order_id=o.id, position=1)])
        with pytest.raises(IntegrityError):
            db.session.commit()


def test_migracja_tras():
    sql = open(MIGRACJA, encoding='utf-8').read()
    for tabela in ('prod_vehicles', 'prod_routes', 'prod_route_stops'):
        assert 'CREATE TABLE IF NOT EXISTS {}'.format(tabela) in sql
    assert 'LONGTEXT' in sql and 'DELIMITER' not in sql
    # fix-1, Ruling A1: wiersz blokady zapisów tras w prod_config.
    assert 'INSERT IGNORE INTO prod_config' in sql and "'logistyka_trasy_blokada'" in sql


def test_pracownik_domyslnie_nie_jest_kierowca(app):
    with app.app_context():
        p = ProductionWorker(first_name='Ala', last_name='Nowa')
        db.session.add(p)
        db.session.commit()
        assert p.is_driver is False


def test_migracja_kierowcow():
    sql = open(MIGRACJA_KIEROWCOW, encoding='utf-8').read()
    assert "TABLE_NAME = 'prod_workers'" in sql and "COLUMN_NAME = 'is_driver'" in sql
    assert 'ADD COLUMN is_driver TINYINT(1) NOT NULL DEFAULT 0' in sql
    assert 'PREPARE krok FROM @sql' in sql and 'DELIMITER' not in sql
    assert not re.search(r'^\s*ALTER TABLE', sql, re.MULTILINE)   # ALTER tylko w PREPARE
