# -*- coding: utf-8 -*-
"""Modele trakowni — nazwy tabel, kolumny, ograniczenia."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from flask import Flask
from sqlalchemy.pool import StaticPool
from sqlalchemy import Column, Integer, String, Boolean, DateTime

from extensions import db
from modules.production.sawmill.models import (
    AUDIT_ACTIONS,
    OPEN_STATUSES,
    PANEL_WRITABLE_STATUSES,
    STATUS_COMPLETED,
    STATUS_IN_PROGRESS,
    STATUS_NEW,
    STATUS_SETTLED,
    SawmillAudit,
    SawmillCounter,
    SawmillDelivery,
    SawmillLog,
    SawmillOrder,
    SawmillSpecies,
    SawmillSupplier,
)


# Makieta tabeli users do testów
class User(db.Model):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)
    username = Column(String(120), unique=True, nullable=False)
    email = Column(String(120), unique=True, nullable=False)
    password = Column(String(255))
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime)


SAWMILL_TABLES = [m.__table__ for m in (
    User, SawmillSupplier, SawmillSpecies, SawmillCounter,
    SawmillDelivery, SawmillOrder, SawmillLog, SawmillAudit,
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
        db.metadata.create_all(bind=db.engine, tables=SAWMILL_TABLES)
        yield app
        db.session.remove()


def test_nazwy_tabel():
    assert SawmillSupplier.__tablename__ == 'prod_sawmill_suppliers'
    assert SawmillSpecies.__tablename__ == 'prod_sawmill_species'
    assert SawmillCounter.__tablename__ == 'prod_sawmill_counters'
    assert SawmillDelivery.__tablename__ == 'prod_sawmill_deliveries'
    assert SawmillOrder.__tablename__ == 'prod_sawmill_orders'
    assert SawmillLog.__tablename__ == 'prod_sawmill_logs'
    assert SawmillAudit.__tablename__ == 'prod_sawmill_audit'


def test_statusy():
    assert OPEN_STATUSES == (STATUS_NEW, STATUS_IN_PROGRESS)
    assert PANEL_WRITABLE_STATUSES == (STATUS_NEW, STATUS_IN_PROGRESS, STATUS_COMPLETED)
    assert STATUS_SETTLED not in PANEL_WRITABLE_STATUSES


def test_akcje_audytu_komplet():
    """Każda operacja zmieniająca stan ma swoją akcję — patrz sekcja 4.7 spec."""
    assert AUDIT_ACTIONS == frozenset({
        'log_create', 'log_create_manual', 'log_update', 'log_delete',
        'order_create', 'order_update', 'order_delete',
        'order_complete', 'order_reopen', 'order_settle', 'order_unsettle',
        'delivery_update', 'delivery_delete',
    })


def test_deklarowana_objetosc_jest_wymagana(app):
    """Bez faktury zlecenie może istnieć, bez deklaracji nie — sekcja 4.5."""
    assert SawmillOrder.__table__.c.declared_volume_m3.nullable is False
    assert SawmillDelivery.__table__.c.invoice_number.nullable is True
    assert SawmillDelivery.__table__.c.invoice_date.nullable is True
    assert SawmillDelivery.__table__.c.delivery_date.nullable is False


def test_unikalnosc_numeru_kolody_w_zleceniu(app):
    with app.app_context():
        constraint_cols = set()
        for uc in SawmillLog.__table__.constraints:
            if uc.__class__.__name__ == 'UniqueConstraint':
                constraint_cols = {c.name for c in uc.columns}
        assert constraint_cols == {'order_id', 'sequence_no'}


def test_audyt_nie_ma_klucza_obcego_na_zleceniu(app):
    """Wpisy audytu przeżywają usunięcie zlecenia — sekcja 4.7."""
    assert list(SawmillAudit.__table__.c.order_id.foreign_keys) == []


def test_zapis_i_odczyt_pelnego_lancucha(app):
    from datetime import date, datetime
    from decimal import Decimal
    with app.app_context():
        supplier = SawmillSupplier(name='Tartak Testowy')
        species = SawmillSpecies(name='Dąb', short_code='DB', sort_order=10)
        db.session.add_all([supplier, species])
        db.session.flush()

        delivery = SawmillDelivery(
            supplier_id=supplier.id,
            delivery_date=date(2026, 8, 5),
            invoice_number=None,
        )
        db.session.add(delivery)
        db.session.flush()

        order = SawmillOrder(
            order_number='TRK/2026/001',
            delivery_id=delivery.id,
            species_id=species.id,
            declared_volume_m3=Decimal('80.000'),
            status=STATUS_NEW,
        )
        db.session.add(order)
        db.session.flush()

        log = SawmillLog(
            order_id=order.id, sequence_no=1,
            butt_d1_cm=Decimal('42.0'), butt_d2_cm=Decimal('38.0'),
            top_d1_cm=Decimal('41.0'), top_d2_cm=Decimal('37.0'),
            length_cm=Decimal('410.0'), volume_m3=Decimal('0.502421'),
            measured_at=datetime(2026, 8, 5, 9, 31, 12),
            created_at=datetime(2026, 8, 5, 9, 31, 15),
        )
        db.session.add(log)
        db.session.commit()

        assert SawmillLog.query.count() == 1
        assert SawmillLog.query.first().is_deleted is False
