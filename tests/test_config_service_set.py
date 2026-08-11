# -*- coding: utf-8 -*-
"""
Zapis konfiguracji produkcji przez serwis.

Powód powstania: POST /production/api/update-config wołał
ProductionConfig.set_config(), czyli metodę, której model NIGDY nie miał —
każde wywołanie kończyło się błędem 500. Panel tego nie wykrył, bo używa
wariantu batch /update-configs. Te testy pilnują kontraktu, na którym
handler teraz stoi: pełny zestaw argumentów (z description i config_type)
oraz zwracany bool zamiast wyjątku.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from flask import Flask
from sqlalchemy.pool import StaticPool

from extensions import db
from modules.production.models import ProductionConfig
from modules.production.services.config_service import (
    get_config, get_config_service, invalidate_config_cache,
)
from modules.users.models import User
from modules.calculator.models import Multiplier  # noqa: F401
from modules.clients.models import Client  # noqa: F401
import modules.quotes.models  # noqa: F401

_TABLES = [m.__table__ for m in (User, ProductionConfig)]


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
        invalidate_config_cache()
        yield app
        db.session.remove()
        invalidate_config_cache()


def test_model_nie_ma_set_config(app):
    """
    Regresja wprost: gdyby ktoś znów sięgnął po metodę na modelu, handler
    /update-config wywali się dokładnie tak jak wcześniej.
    """
    assert not hasattr(ProductionConfig, 'set_config')


def test_serwis_tworzy_nowy_klucz_z_opisem_i_typem(app):
    """Dokładnie te argumenty, którymi woła go handler /update-config."""
    with app.app_context():
        wynik = get_config_service().set_config(
            key='TESTOWY_KLUCZ',
            value='true',
            user_id=None,
            description='Opis z formularza',
            config_type='boolean',
        )

        assert wynik is True
        wpis = ProductionConfig.query.filter_by(config_key='TESTOWY_KLUCZ').one()
        assert wpis.config_value == 'true'
        assert wpis.config_description == 'Opis z formularza'
        assert wpis.config_type == 'boolean'


def test_serwis_nadpisuje_istniejaca_wartosc_i_czysci_cache(app):
    with app.app_context():
        serwis = get_config_service()
        serwis.set_config(key='LICZBA', value=5, config_type='integer')
        assert get_config('LICZBA') == 5      # wchodzi do cache

        serwis.set_config(key='LICZBA', value=9, config_type='integer')

        # Bez invalidacji w set_config zobaczylibyśmy tu nadal 5.
        assert get_config('LICZBA') == 9
        assert ProductionConfig.query.filter_by(config_key='LICZBA').count() == 1


def test_serwis_zwraca_false_zamiast_rzucac(app):
    """
    Handler polega na tym, że odrzucony zapis wraca jako False — inaczej
    odpowiadałby sukcesem po nieudanej operacji.

    Walidacja w serwisie jest per-KLUCZ, nie po typie (patrz
    _validate_config_value), więc bierzemy klucz z zadeklarowanym zakresem:
    REFRESH_INTERVAL_SECONDS dopuszcza 5-300 sekund.
    """
    with app.app_context():
        wynik = get_config_service().set_config(
            key='REFRESH_INTERVAL_SECONDS', value=9999, config_type='integer')

        assert wynik is False
        assert ProductionConfig.query.filter_by(
            config_key='REFRESH_INTERVAL_SECONDS').count() == 0


@pytest.mark.parametrize('przyslane, oczekiwane', [
    ('false', 'false'),   # <select> z panelu przysyła TEKST
    ('true', 'true'),
    ('False', 'false'),
    ('0', 'false'),
    ('1', 'true'),
    ('on', 'true'),
    ('', 'false'),
    (False, 'false'),     # wartości natywne dalej mają działać
    (True, 'true'),
    (0, 'false'),
])
def test_boolean_z_panelu_zapisuje_sie_zgodnie_z_trescia(app, przyslane, oczekiwane):
    """
    Regresja: `'true' if value else 'false'` traktowało tekst 'false' jako
    prawdę, bo w Pythonie każdy niepusty string jest prawdziwy. Przełączniki
    w panelu dawały się wtedy tylko włączyć — w tym kill-switch
    WORKER_SELECTION_REQUIRED, który ma odblokowywać zatrzymaną halę.
    """
    with app.app_context():
        get_config_service().set_config(
            key='FLAGA', value=przyslane, config_type='boolean')

        wpis = ProductionConfig.query.filter_by(config_key='FLAGA').one()
        assert wpis.config_value == oczekiwane
        # Zapis i odczyt muszą się zgadzać — parsed_value używa tego samego zbioru.
        assert wpis.parsed_value is (oczekiwane == 'true')


def test_przelacznik_da_sie_wylaczyc_po_wlaczeniu(app):
    """Pełny cykl, którego wcześniej nie dało się zamknąć."""
    with app.app_context():
        serwis = get_config_service()
        serwis.set_config(key='WORKER_SELECTION_REQUIRED', value='true',
                          config_type='boolean')
        assert get_config('WORKER_SELECTION_REQUIRED') is True

        serwis.set_config(key='WORKER_SELECTION_REQUIRED', value='false',
                          config_type='boolean')
        assert get_config('WORKER_SELECTION_REQUIRED') is False


def test_wartosc_spoza_walidacji_przechodzi_bez_sprawdzenia(app):
    """
    Utrwalenie zastanego zachowania, żeby nie zaskoczyło przy czytaniu kodu:
    serwis waliduje TYLKO wymienione klucze. Dowolny inny klucz zapisze się
    z dowolną treścią — również taką, która nie jest poprawnym JSON-em,
    mimo config_type='json'.
    """
    with app.app_context():
        wynik = get_config_service().set_config(
            key='DOWOLNY_KLUCZ', value='{to nie jest json', config_type='json')

        assert wynik is True
        assert ProductionConfig.query.filter_by(config_key='DOWOLNY_KLUCZ').count() == 1
