# -*- coding: utf-8 -*-
"""Schemat etapu 1 logistyki: kolumny zamówienia, log, migracja."""
import os
import re

from extensions import db
from modules.production.logistics.models import LogisticsLog
from modules.production.models import ProductionOrder
from tests.logistyka_fixtures import app, zamowienie  # noqa: F401

KATALOG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MIGRACJA = os.path.join(KATALOG, 'migrations', '2026-09-25-logistyka-sposob-dostawy.sql')


def test_nowe_zamowienie_ma_domyslne_wartosci_logistyki(app):
    with app.app_context():
        order = zamowienie()
        assert order.override_delivery_method is None
        assert order.repack_required is False
        assert order.bl_delivery_method_pending is False
        assert order.bl_status_pending_id is None
        assert order.logistics_closed_at is None
        assert order.handed_over_at is None


def test_log_logistyki_zapisuje_sie(app):
    with app.app_context():
        order = zamowienie()
        db.session.add(LogisticsLog(order_id=order.id, action='sposob_dostawy',
                                    old_value=None, new_value='kurier_baselinker'))
        db.session.commit()
        assert LogisticsLog.query.filter_by(order_id=order.id).count() == 1


def test_migracja_zawiera_wszystkie_kroki():
    sql = open(MIGRACJA, encoding='utf-8').read()
    for kolumna in ('delivery_method_set_at', 'delivery_method_set_by', 'handed_over_at',
                    'handed_over_by', 'repack_required', 'logistics_closed_at',
                    'bl_delivery_method_pending', 'bl_status_pending_id'):
        assert kolumna in sql, kolumna
    assert 'CREATE TABLE IF NOT EXISTS prod_logistics_log' in sql
    assert "SET current_status = 'czeka_na_pakowanie'" in sql
    assert 'logistyka_bl_dzierzawa' in sql and 'logistyka_bl_wstrzymane_do' in sql
    assert 'DELIMITER' not in sql
    # Każdy ALTER musi być osłonięty (idempotencja przy każdym deployu).
    assert not re.search(r'^\s*ALTER TABLE', sql, re.MULTILINE)
