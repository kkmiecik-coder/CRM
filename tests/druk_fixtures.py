# -*- coding: utf-8 -*-
"""
Wspólna apka testowa kolejki wydruku (logistyka etap 4, krok 4.1).

    from tests.druk_fixtures import app, zadanie  # noqa: F401

SQLite in-memory z tabelami kolejki i konfiguracji. Import modeli kalkulatora,
klientów i wycen jest potrzebny tylko dlatego, że configure_mappers() przy
pierwszym zapytaniu konfiguruje CAŁY rejestr mapperów (User ma relacje do nich).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from flask import Flask
from sqlalchemy.pool import StaticPool

from extensions import db
from modules.production.models import LabelPrintJob, ProductionConfig
from modules.users.models import User
from modules.calculator.models import Multiplier  # noqa: F401
from modules.clients.models import Client  # noqa: F401
import modules.quotes.models  # noqa: F401

TABLES = [m.__table__ for m in (User, ProductionConfig, LabelPrintJob)]


def nowa_apka(template_folder=None):
    """Goła apka Flask z SQLite in-memory (jedno połączenie na cały test)."""
    app = Flask(__name__, template_folder=template_folder)
    app.secret_key = 'test-druk'
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        'poolclass': StaticPool,
        'connect_args': {'check_same_thread': False},
    }
    return app


@pytest.fixture()
def app():
    app = nowa_apka()
    db.init_app(app)
    with app.app_context():
        db.metadata.create_all(bind=db.engine, tables=TABLES)
        yield app
        db.session.remove()


def zadanie(printer=None, status='pending', kod='900_1', zpl='^XA^XZ'):
    """Wiersz kolejki; printer=None = bez podania drukarki (wartość domyślna kolumny)."""
    kolumny = dict(short_product_id=kod, zpl_payload=zpl, station_code='packaging',
                   requested_by_type='user', requested_by_id='1', status=status)
    if printer is not None:
        kolumny['printer'] = printer
    job = LabelPrintJob(**kolumny)
    db.session.add(job)
    db.session.commit()
    return job
