# -*- coding: utf-8 -*-
"""Schemat U10 (logistyka etap 4, krok 4.4b, Ruling 32): niedostarczony przystanek zostaje na trasie do jej końca —
kolumny `not_delivered_*` przystanku, akcja logu `niedostarczenie_cofniete` i indeks `route_id` logu (historia
niedostarczonych trasy)."""
import os
import re
from datetime import date, datetime

from extensions import db
from migrations.migration_service import MigrationService
from modules.production.logistics.models import AKCJE_LOGU, LogisticsLog, Route, RouteStop
from tests.logistyka_fixtures import app, zamowienie  # noqa: F401

MIGRACJA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        'migrations', '2026-10-02-logistyka-niedostarczone-na-trasie.sql')


def _polecenia():
    with open(MIGRACJA, encoding='utf-8') as f:
        sql = f.read()
    return sql, [' '.join(p.split()) for p in MigrationService.split_statements(sql)]


def test_akcja_cofniecia_niedostarczenia_na_koncu():
    assert list(AKCJE_LOGU)[-2:] == ['dostarczenie_cofniete', 'niedostarczenie_cofniete']


def test_kolumny_niedostarczenia_przystanku(app):
    chwila = datetime(2026, 10, 2, 14, 5)
    trasa = Route(name=u'Rzeszów', date_from=date(2026, 10, 2), date_to=date(2026, 10, 2), status='w_trasie')
    db.session.add(trasa)
    db.session.flush()
    order = zamowienie()
    db.session.add(RouteStop(route_id=trasa.id, order_id=order.id, position=1, not_delivered_at=chwila,
                             not_delivered_reason='brak_klienta', not_delivered_note=u'nikt nie otworzył',
                             not_delivered_by_worker_id=7))
    db.session.commit()
    db.session.expire_all()
    s = Route.query.get(trasa.id).stops[0]
    assert (s.not_delivered_at, s.not_delivered_reason, s.not_delivered_note, s.not_delivered_by_worker_id) == \
        (chwila, 'brak_klienta', u'nikt nie otworzył', 7)


def test_indeks_route_id_logu():
    assert LogisticsLog.__table__.c.route_id.index is True
    assert 'ix_prod_logistics_log_route_id' in {i.name for i in LogisticsLog.__table__.indexes}


def test_migracja():
    sql, polecenia = _polecenia()
    for kolumna in ('not_delivered_at DATETIME NULL', 'not_delivered_reason VARCHAR(32) NULL',
                    'not_delivered_note VARCHAR(255) NULL', 'not_delivered_by_worker_id INT NULL'):
        assert 'ALTER TABLE prod_route_stops ADD COLUMN %s' % kolumna in sql, kolumna
    assert sql.count('FROM information_schema.COLUMNS') == 4
    assert 'ALTER TABLE prod_logistics_log ADD INDEX ix_prod_logistics_log_route_id (route_id)' in sql
    assert sql.count('FROM information_schema.STATISTICS') == 1
    assert sql.count('PREPARE krok FROM @sql') == 5   # każdy ALTER dodający coś — osłonięty (idempotencja)
    log = next(p for p in polecenia if p.startswith('ALTER TABLE prod_logistics_log MODIFY action'))
    wartosci = re.findall(r"'([a-z_]+)'", log.split('ENUM(', 1)[1].split(')', 1)[0])
    assert wartosci == list(AKCJE_LOGU)   # pełna lista: brakująca wartość skasowałaby akcję wpisom w logu
    assert 'COLLATE utf8mb4_unicode_ci NOT NULL' in log
    assert 'DELIMITER' not in sql.upper()
