# -*- coding: utf-8 -*-
"""
Ustawienia trakowni (sawmill_settings w prod_config) — zachowanie, nie tylko import stałej.

Cztery rzeczy, które musi tu pilnować:
1. decimal_places jest STAŁĄ (1), nigdy nie pochodzi z bazy ani z save_sawmill_settings.
2. mobile_config_payload() NIE wystawia deviation_threshold_pct (tablet nie zna deklaracji).
3. save_sawmill_settings zapisuje edytowalny limit, get_sawmill_settings go odczytuje —
   ale save_sawmill_settings NIE commituje, commit robi wywołujący.
4. Pusta wartość zapisuje None ('nie sprawdzaj limitu'), nie 0.0 ('wszystko > 0 jest błędem'),
   brakujące klucze w bazie są uzupełniane domyślnymi, a uszkodzony JSON degraduje się do
   domyślnych zamiast wywalać wyjątek.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json

import pytest
from flask import Flask
from sqlalchemy.pool import StaticPool

from extensions import db
from modules.production.models import ProductionConfig
from modules.production.sawmill.services.settings import (
    CONFIG_KEY,
    DEFAULT_SETTINGS,
    MOBILE_KEYS,
    get_sawmill_settings,
    mobile_config_payload,
    save_sawmill_settings,
)
from modules.users.models import User
# Sam import User nie wystarcza — to samo uzasadnienie co w test_sawmill_models.py /
# test_sawmill_numbering.py: configure_mappers() przy pierwszym query/flush konfiguruje
# CAŁY rejestr mapperów, więc User.multiplier_id (FK do multipliers) i dalsze relacje
# (Quote.client, Quote.quote_status) muszą dać się rozwiązać, mimo że trakownia ich nie dotyka.
from modules.calculator.models import Multiplier  # noqa: F401
from modules.clients.models import Client  # noqa: F401
import modules.quotes.models  # noqa: F401
from modules.quotes.models import QuoteStatus  # noqa: F401

_TABLES = [User.__table__, ProductionConfig.__table__]


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


def _dodaj_wiersz(config_value):
    """Wstawia surowy wiersz sawmill_settings, jakby ktoś zapisał go poza save_sawmill_settings."""
    row = ProductionConfig(
        config_key=CONFIG_KEY,
        config_value=config_value,
        config_type='json',
    )
    db.session.add(row)
    db.session.commit()
    return row


# ── 1. decimal_places jest stałą ────────────────────────────────────────────

def test_decimal_places_ignoruje_wartosc_zapisana_w_bazie(app):
    """Nawet jeśli w bazie leży decimal_places=2, odczyt ma wymusić 1."""
    with app.app_context():
        _dodaj_wiersz(json.dumps({'decimal_places': 2, 'min_circumference_cm': 12.0}))
        wynik = get_sawmill_settings()
        assert wynik['decimal_places'] == 1
        # inne pola z bazy nadal są respektowane — nadpisywana jest tylko ta jedna stała
        assert wynik['min_circumference_cm'] == 12.0


def test_decimal_places_nie_da_sie_ustawic_przez_save(app):
    """Próba przesłania 2 do save_sawmill_settings nie ma prawa się przyjąć."""
    with app.app_context():
        wynik = save_sawmill_settings({'decimal_places': 2, 'min_circumference_cm': '15.0'})
        assert wynik['decimal_places'] == 1
        # edytowalny klucz przekazany w tym samym wywołaniu działa normalnie
        assert wynik['min_circumference_cm'] == 15.0


def test_decimal_places_stala_takze_przy_braku_wiersza(app):
    with app.app_context():
        assert get_sawmill_settings()['decimal_places'] == 1


# ── 2. mobile_config_payload() nie wystawia deviation_threshold_pct ────────

def test_mobile_payload_nie_zawiera_progu_odchylenia(app):
    with app.app_context():
        payload = mobile_config_payload()
        assert 'deviation_threshold_pct' not in payload


def test_mobile_payload_zawiera_dokladnie_klucze_mobilne(app):
    """Payload tabletu to dokładnie MOBILE_KEYS — ani mniej, ani więcej (wyciek pól to główne ryzyko)."""
    with app.app_context():
        _dodaj_wiersz(json.dumps({'deviation_threshold_pct': 12.5, 'min_circumference_cm': 11.0}))
        payload = mobile_config_payload()
        assert set(payload.keys()) == set(MOBILE_KEYS)
        assert payload['min_circumference_cm'] == 11.0
        assert payload['decimal_places'] == 1


# ── 3. round-trip zapisu/odczytu, bez auto-commitu w save_sawmill_settings ─

def test_round_trip_zapisu_i_odczytu(app):
    with app.app_context():
        zwrocone = save_sawmill_settings({'max_circumference_cm': '150.5', 'min_length_cm': '25.0'})
        assert zwrocone['max_circumference_cm'] == 150.5
        assert zwrocone['min_length_cm'] == 25.0

        # commit robi wywołujący — tu symulujemy dokładnie to zachowanie
        db.session.commit()

        wczytane = get_sawmill_settings()
        assert wczytane['max_circumference_cm'] == 150.5
        assert wczytane['min_length_cm'] == 25.0
        # pola nieedytowane w tym wywołaniu zostają domyślne
        assert wczytane['max_length_cm'] == DEFAULT_SETTINGS['max_length_cm']


def test_save_nie_wykonuje_commit(app):
    """Bez jawnego commit() wywołującego zmiana nie ma prawa przetrwać rollbacku."""
    with app.app_context():
        assert ProductionConfig.query.filter_by(config_key=CONFIG_KEY).first() is None

        save_sawmill_settings({'max_circumference_cm': '150.5'})
        # świadomie NIE commitujemy — symulacja wywołującego, który np. oberwał wyjątkiem
        db.session.rollback()

        assert ProductionConfig.query.filter_by(config_key=CONFIG_KEY).first() is None


def test_save_na_istniejacym_wierszu_tez_nie_commituje(app):
    """Ta sama gwarancja dla update'u istniejącego wiersza, nie tylko dla pierwszego insertu."""
    with app.app_context():
        _dodaj_wiersz(json.dumps(dict(DEFAULT_SETTINGS)))
        db.session.commit()

        save_sawmill_settings({'max_circumference_cm': '999.0'})
        db.session.rollback()

        wynik = get_sawmill_settings()
        assert wynik['max_circumference_cm'] == DEFAULT_SETTINGS['max_circumference_cm']


# ── 4. pusta wartość → None, braki i uszkodzony JSON degradują do domyślnych ─

def test_pusta_wartosc_zapisuje_none_a_nie_zero(app):
    """'' oznacza 'nie sprawdzaj tego limitu' — None, nie 0.0 ('wszystko powyżej zera jest błędem')."""
    with app.app_context():
        wynik = save_sawmill_settings({'max_length_cm': ''})
        assert wynik['max_length_cm'] is None
        assert wynik['max_length_cm'] != 0.0


def test_wartosc_none_tez_zapisuje_none(app):
    with app.app_context():
        wynik = save_sawmill_settings({'max_length_cm': None})
        assert wynik['max_length_cm'] is None


def test_brak_wiersza_zwraca_wartosci_domyslne(app):
    with app.app_context():
        assert get_sawmill_settings() == DEFAULT_SETTINGS


def test_brakujace_klucze_w_bazie_uzupelniane_domyslnymi(app):
    """Wiersz w bazie ma tylko jeden klucz — reszta ma spaść do DEFAULT_SETTINGS."""
    with app.app_context():
        _dodaj_wiersz(json.dumps({'min_circumference_cm': 8.0}))
        wynik = get_sawmill_settings()
        assert wynik['min_circumference_cm'] == 8.0
        assert wynik['max_circumference_cm'] == DEFAULT_SETTINGS['max_circumference_cm']
        assert wynik['min_length_cm'] == DEFAULT_SETTINGS['min_length_cm']
        assert wynik['max_length_cm'] == DEFAULT_SETTINGS['max_length_cm']
        assert wynik['deviation_threshold_pct'] == DEFAULT_SETTINGS['deviation_threshold_pct']


def test_uszkodzony_json_degraduje_do_domyslnych_bez_wyjatku(app):
    with app.app_context():
        _dodaj_wiersz('{to nie jest poprawny json')
        wynik = get_sawmill_settings()  # nie ma wywalić wyjątku
        assert wynik == DEFAULT_SETTINGS
