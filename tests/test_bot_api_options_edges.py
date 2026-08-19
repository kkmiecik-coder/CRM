# -*- coding: utf-8 -*-
"""GET /api/bot/options — edge_types musi oddawać zakresy geometrii krawędzi.

Sklep (wp_quotewizard) miał promienie i kąty fazowania zaszyte na sztywno
w views/js/front/edges.js, bo API ich nie zwracało — i rozjechały się
z produkcją (klienci zamawiali fazowanie R10, którego nie robimy). Ten test
pilnuje, że komplet parametrów z EdgeOption dociera do bota i do sklepu.

Konwencja jak test_bot_api_by_token_integration.py: minimalny Flask + SQLite
in-memory na StaticPool (wspólne połączenie dla seedu i test_clienta).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from flask import Flask
from sqlalchemy.pool import StaticPool

from extensions import db
from modules.calculator.models import (
    Price, Multiplier, FinishingOption, EdgeOption, CalculatorSetting,
)
from modules.calculator.routers.bot_api import bot_api_bp
from modules.calculator.services.pricing_service import invalidate_pricing_cache

# Rejestr mapperów: modules.calculator.models trzyma też Quote, którego relacje
# wskazują na Client/QuoteStatus — bez tych importów pierwsze query rzuca
# InvalidRequestError, mimo że sam /options ich nie dotyka.
import modules.clients.models   # noqa: F401
import modules.quotes.models    # noqa: F401
import modules.users.models     # noqa: F401

BOT_KEY = 'test-bot-key'

_TABLES = [m.__table__ for m in (
    Price, Multiplier, FinishingOption, EdgeOption, CalculatorSetting,
)]

# Odzwierciedla produkcyjne edge_options: ostre bez geometrii, fazowanie po kątach,
# zaokrąglenie po promieniach.
_KRAWEDZIE = [
    dict(type='sharp', name='Ostre', price_per_mb=0, corner_price=0,
         r_min=None, r_max=None, r_default=None, chamfer_angles=None, angle_default=None),
    dict(type='chamfer', name='Fazowanie', price_per_mb=12, corner_price=4,
         r_min=None, r_max=None, r_default=None, chamfer_angles=[15, 30, 45], angle_default=45),
    dict(type='round', name='Zaokrąglenie', price_per_mb=15, corner_price=5,
         r_min=2, r_max=8, r_default=5, chamfer_angles=None, angle_default=None),
]


@pytest.fixture()
def app():
    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        'poolclass': StaticPool,
        'connect_args': {'check_same_thread': False},
    }
    app.config['BOT_API_KEY'] = BOT_KEY
    app.register_blueprint(bot_api_bp, url_prefix='/api/bot')
    db.init_app(app)

    with app.app_context():
        db.metadata.create_all(bind=db.engine, tables=_TABLES)
        for k in _KRAWEDZIE:
            db.session.add(EdgeOption(is_active=True, **k))
        db.session.commit()
        invalidate_pricing_cache()   # nie dziedzicz cache cennika z innych testów
        yield app
        db.session.remove()
        invalidate_pricing_cache()   # baza in-memory znika razem z silnikiem


@pytest.fixture()
def client(app):
    return app.test_client()


def _edge_types(client):
    r = client.get('/api/bot/options', headers={'X-Bot-Api-Key': BOT_KEY})
    assert r.status_code == 200, r.get_data(as_text=True)
    dane = r.get_json()
    assert dane['ok'] is True
    return {e['type']: e for e in dane['edge_types']}


def test_options_zwraca_komplet_pol_dla_wszystkich_typow(client):
    edges = _edge_types(client)
    assert set(edges) == {'sharp', 'chamfer', 'round'}

    wymagane = {'type', 'per_mb', 'per_corner',
                'r_min', 'r_max', 'r_default', 'chamfer_angles', 'angle_default'}
    for typ, e in edges.items():
        assert wymagane <= set(e), f'{typ}: brakuje {wymagane - set(e)}'


def test_options_oddaje_wartosci_geometrii_z_bazy(client):
    edges = _edge_types(client)

    # Zaokrąglenie: zakres promienia — to on rozjechał się ze sklepem (R10 poza zakresem)
    assert (edges['round']['r_min'], edges['round']['r_max'],
            edges['round']['r_default']) == (2, 8, 5)

    # Fazowanie: lista kątów + domyślny
    assert edges['chamfer']['chamfer_angles'] == [15, 30, 45]
    assert edges['chamfer']['angle_default'] == 45

    # Ostre: brak geometrii, ale klucze OBECNE (sklep nie może zgadywać z braku pola)
    assert edges['sharp']['r_max'] is None
    assert edges['sharp']['chamfer_angles'] is None


def test_options_zachowuje_klucze_cen_czytane_przez_sklep(client):
    edges = _edge_types(client)
    assert edges['round']['per_mb'] == 15.0
    assert edges['round']['per_corner'] == 5.0
    assert edges['sharp']['per_mb'] == 0.0
