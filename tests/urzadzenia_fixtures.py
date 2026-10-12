# -*- coding: utf-8 -*-
"""
Wspólne fixtury testów dostępu urządzeń (spec 2026-10-12): Flask + SQLite in-memory z API mobilnym.

StaticPool — jedno współdzielone połączenie, żeby zapis z jednego request-contextu był widoczny w kolejnym zapytaniu
w tym samym teście (wzorzec: tests/test_mobile_api_uniewaznienie_tokenow.py).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from flask import Flask
from sqlalchemy.pool import StaticPool

from extensions import db
from modules.production.models import MobileAppRelease, ProductionDevice, get_local_now
from modules.production.routers.mobile_api import mobile_api_bp
from modules.users.models import User
# Importy rejestrujące mappery — configure_mappers() przy pierwszym query potrzebuje ich do rozwiązania
# relationshipów z modules/users/models.py.
from modules.calculator.models import Multiplier  # noqa: F401
from modules.clients.models import Client  # noqa: F401
import modules.quotes.models  # noqa: F401

TABELE = [User.__table__, ProductionDevice.__table__, MobileAppRelease.__table__]
MAC_A = 'A4:50:46:00:00:0A'
MAC_B = 'A4:50:46:00:00:0B'


def nowa_aplikacja(instance_path=None):
    app = Flask(__name__, instance_path=instance_path) if instance_path else Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        'poolclass': StaticPool,
        'connect_args': {'check_same_thread': False},
    }
    app.config['API_MOBILE'] = {
        'jwt_secret': 'x' * 64,
        'jwt_expiry_days': 365,
        'min_supported_app_version': '0.0.0',
    }
    app.register_blueprint(mobile_api_bp, url_prefix='/api/mobile')
    db.init_app(app)
    return app


@pytest.fixture()
def app():
    app = nowa_aplikacja()
    with app.app_context():
        db.metadata.create_all(bind=db.engine, tables=TABELE)
        yield app
        db.session.remove()


@pytest.fixture()
def client(app):
    return app.test_client()


def urzadzenie(device_id='TAB-1', station_code='packaging', status='zatwierdzone', mac=None, nazwa='Tablet', **pola):
    """Wiersz prod_devices w zadanym stanie, spójnie: is_active = (status == 'zatwierdzone')."""
    d = ProductionDevice(device_id=device_id, device_name=nazwa, station_code=station_code, status=status,
                         is_active=(status == 'zatwierdzone'), mac_address=mac, **pola)
    if status == 'oczekuje' and 'requested_at' not in pola:
        d.requested_at = get_local_now()
    db.session.add(d)
    db.session.commit()
    return d
