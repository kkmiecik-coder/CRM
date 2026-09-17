# -*- coding: utf-8 -*-
"""
Odczyt konfiguracji wysyłki z tabeli calculator_settings.

Osobny plik od test_shipping_pricing.py, bo ten wymaga bazy (SQLite in-memory),
a tamten jest czysty. Konwencja fixture'a jak w tests/test_sawmill_settings.py.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from flask import Flask
from sqlalchemy.pool import StaticPool

from extensions import db
from modules.calculator.models import CalculatorSetting
from modules.calculator.services.shipping_pricing import (
    DEFAULT_CONFIG, SIDE_ABOVE, load_shipping_config,
)
# Importy poniżej wymagane tylko dla konfiguracji mapperów SQLAlchemy.
# CalculatorSetting sam w sobie nie zależy od Quote/Client, ale importując
# z modules.calculator.models, SQLAlchemy konfiguruje CAŁY rejestr mapperów
# naraz, więc wszystkie relacje (Quote.client) muszą być możliwe do rozwiązania.
from modules.clients.models import Client  # noqa: F401
import modules.quotes.models  # noqa: F401

_TABLES = [CalculatorSetting.__table__]


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


def test_pusta_tabela_daje_wartosci_domyslne(app):
    """Brak wierszy = zachowanie sprzed zmiany. Migracja nie jest warunkiem
    działania aplikacji, tylko wygody w panelu."""
    with app.app_context():
        assert load_shipping_config() == DEFAULT_CONFIG


def test_odczytuje_zapisane_wartosci(app):
    with app.app_context():
        CalculatorSetting.set_value('shipping_markup_percent', '27.5')
        CalculatorSetting.set_value('shipping_threshold_brutto', '150.00')
        CalculatorSetting.set_value('shipping_surcharge_brutto', '24.60')
        CalculatorSetting.set_value('shipping_surcharge_side', 'above')

        assert load_shipping_config() == {
            'percent': 27.5,
            'threshold_brutto': 150.0,
            'surcharge_brutto': 24.6,
            'side': SIDE_ABOVE,
        }


def test_uszkodzony_wiersz_degraduje_sie_do_domyslnego(app):
    """Ktoś wpisał tekst przez phpMyAdmin — wycena ma dalej działać."""
    with app.app_context():
        CalculatorSetting.set_value('shipping_markup_percent', 'trzydziesci')
        CalculatorSetting.set_value('shipping_surcharge_brutto', '24.60')

        config = load_shipping_config()
        assert config['percent'] == DEFAULT_CONFIG['percent']
        assert config['surcharge_brutto'] == 24.6
