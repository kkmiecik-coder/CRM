# -*- coding: utf-8 -*-
"""Test integracyjny GET /api/bot/quotes/by-token/<token> + round-trip product_type.

Konwencja jak test_finishing_flat_list.py: minimalny Flask + SQLAlchemy na SQLite
in-memory (bez pełnego create_app()). StaticPool — wspólne połączenie dla całej apki,
żeby dane zasiane w teście były widoczne dla requestu przez test_client (inaczej
sqlite ':memory:' daje osobną bazę per połączenie).

Importy modeli clients/quotes są potrzebne, by SQLAlchemy skonfigurowało mappery
(Quote.client / Quote.quote_status / QuoteItem.discount_reason) — inaczej pierwsze
query rzuca InvalidRequestError. modules.calculator.models transitively importuje
modules.users.models (User), więc tabela users też jest w metadanych.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime
from types import SimpleNamespace

import pytest
from flask import Flask
from sqlalchemy.pool import StaticPool

from extensions import db
from modules.calculator.models import (
    Quote, QuoteItem, QuoteItemDetails, Price, Multiplier,
    FinishingOption, EdgeOption, CalculatorSetting, QuoteCounter, QuoteLog,
)
from modules.calculator.routers.bot_api import bot_api_bp
from modules.calculator.services.quote_service import create_quote, update_quote
from modules.calculator.services.pricing_service import (
    VARIANT_MAPPING, invalidate_pricing_cache,
)
from modules.users.models import User
from modules.clients.models import Client

import modules.quotes.models   # noqa: F401 — rejestr mapperów

BOT_KEY = 'test-bot-key'
TOKEN = 'TESTTOKEN0000000000000000000001'  # 31 znaków — mieści się w String(32)

# Tworzymy TYLKO te tabele (nie db.create_all()) — inne moduły (produkcja/baselinker)
# rejestrują w globalnych metadanych modele z typem LONGTEXT, którego SQLite nie skompiluje.
_TABLES = [m.__table__ for m in (
    Price, Multiplier, FinishingOption, EdgeOption, CalculatorSetting, User, Client,
    Quote, QuoteItem, QuoteItemDetails, QuoteCounter, QuoteLog,
)]


@pytest.fixture()
def app():
    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'   # in-memory
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    # StaticPool: jedno wspólne połączenie => ta sama baza in-memory dla seedu i test_clienta.
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        'poolclass': StaticPool,
        'connect_args': {'check_same_thread': False},
    }
    app.config['BOT_API_KEY'] = BOT_KEY
    app.config['BOT_USER_ID'] = 1                 # konto bota podpisujące wyceny (POST /quotes)
    app.config['APP_BASE_URL'] = 'https://crm.woodpower.pl'
    app.register_blueprint(bot_api_bp, url_prefix='/api/bot')
    db.init_app(app)

    with app.app_context():
        db.metadata.create_all(bind=db.engine, tables=_TABLES)
        invalidate_pricing_cache()   # nie dziedzicz cache cennika z innych testów
        yield app
        db.session.remove()
        invalidate_pricing_cache()   # nie zostawiaj cache wskazującego na tę bazę (in-memory znika z silnikiem)


@pytest.fixture()
def client(app):
    return app.test_client()


def _auth(token=BOT_KEY):
    return {'X-Bot-Api-Key': token}


def _seed_quote_one_item(app):
    """Wycena z jedną wybraną pozycją (blat, dąb lity A/B, 2 szt.) + szczegóły."""
    with app.app_context():
        quote = Quote(quote_number='05/07/26/W', public_token=TOKEN,
                      created_at=datetime(2026, 7, 17, 10, 30, 0))
        db.session.add(quote)
        db.session.flush()
        db.session.add(QuoteItem(
            quote_id=quote.id, product_index=1, variant_code='dab-lity-ab',
            length_cm=100, width_cm=50, thickness_cm=3,
            price_netto=159.90, price_brutto=196.68, is_selected=True))
        db.session.add(QuoteItemDetails(
            quote_id=quote.id, product_index=1, product_type='blat', quantity=2,
            finishing_type='Lakierowane', finishing_variant='Bezbarwne',
            finishing_gloss_level='Matowy',
            # wykonczenie + krawedzie liczone per pozycja (za cala ilosc) — musza wejsc do total
            finishing_price_netto=120.0, finishing_price_brutto=147.60,
            edges_price_netto=36.0, edges_price_brutto=44.28,
            edges_config=[{'letter': 'A', 'type': 'round', 'r_value': 5, 'angle_value': None}],
            shape='rectangular'))
        db.session.commit()


# =============================================================================
# Odczyt (Zadanie 1) — trasa + realna kolumna + serializer + auth
# =============================================================================

def test_by_token_zwraca_pelna_wycene_z_product_type(app, client):
    _seed_quote_one_item(app)
    resp = client.get(f'/api/bot/quotes/by-token/{TOKEN}', headers=_auth())
    assert resp.status_code == 200
    body = resp.get_json()
    assert body['ok'] is True
    q = body['quote']
    assert q['quote_number'] == '05/07/26/W'
    assert q['created_at'] == '2026-07-17T10:30:00'
    assert len(q['items']) == 1
    item = q['items'][0]
    assert item['product_type'] == 'blat'           # round-trip konceptu sklepu
    assert item['selected_variant'] == 'dab-lity-ab'
    assert item['species'] == 'Dąb'
    assert item['length'] == 100.0 and item['width'] == 50.0 and item['thickness'] == 3.0
    assert item['quantity'] == 2
    assert item['finishing_type'] == 'Lakierowane'
    assert item['finishing_option_id'] is None
    assert item['edges'] == [{'letter': 'A', 'type': 'round', 'r_value': 5, 'angle_value': None}]
    # unit = material/szt.; total = material×ilosc + wykonczenie + krawedzie (jak strona klienta)
    assert item['unit_netto'] == 159.9
    assert item['finishing_netto'] == 120.0 and item['edges_netto'] == 36.0
    assert item['total_netto'] == 475.8          # 159.90*2 + 120.0 + 36.0
    assert item['total_brutto'] == 585.24        # 196.68*2 + 147.60 + 44.28
    assert q['totals'] == {'total_netto': 475.8, 'total_brutto': 585.24}


def test_by_token_pomija_niewybrane_warianty(app, client):
    _seed_quote_one_item(app)
    # Dokładamy drugi wariant tej samej pozycji, NIEwybrany — nie może trafić do items.
    with app.app_context():
        quote = Quote.query.filter_by(public_token=TOKEN).first()
        db.session.add(QuoteItem(
            quote_id=quote.id, product_index=1, variant_code='dab-lity-bb',
            length_cm=100, width_cm=50, thickness_cm=3,
            price_netto=140.0, price_brutto=172.2, is_selected=False))
        db.session.commit()
    resp = client.get(f'/api/bot/quotes/by-token/{TOKEN}', headers=_auth())
    body = resp.get_json()
    assert len(body['quote']['items']) == 1
    assert body['quote']['items'][0]['selected_variant'] == 'dab-lity-ab'


def test_by_token_nieznany_token_kontrakt_ok_false(app, client):
    resp = client.get('/api/bot/quotes/by-token/NIEISTNIEJACYTOKEN', headers=_auth())
    assert resp.status_code == 200          # kontrakt bota: ok/errors, nie kody HTTP
    body = resp.get_json()
    assert body['ok'] is False
    assert body['errors'][0]['code'] == 'NOT_FOUND'


def test_by_token_zly_klucz_api_401(app, client):
    _seed_quote_one_item(app)
    resp = client.get(f'/api/bot/quotes/by-token/{TOKEN}', headers=_auth('zly-klucz'))
    assert resp.status_code == 401          # 401 TYLKO przy złym kluczu API
    assert resp.get_json()['ok'] is False


def test_by_token_bez_klucza_api_401(app, client):
    _seed_quote_one_item(app)
    resp = client.get(f'/api/bot/quotes/by-token/{TOKEN}')
    assert resp.status_code == 401


# =============================================================================
# Zapis (Zadanie 2) — product_type utrwalany przez create_quote i PUT (update_quote)
# =============================================================================

def _seed_pricing_and_bot_user(app):
    with app.app_context():
        db.session.add(Price(species='Dąb', technology='Lity', wood_class='A/B',
                             thickness_min=2, thickness_max=6, length_min=20, length_max=450,
                             width_min=10, width_max=200, price_per_m3=8200))
        db.session.add(Multiplier(client_type='Detal+', multiplier=1.3))
        db.session.add(EdgeOption(id=1, type='round', name='Zaokrąglenie', price_per_mb=15,
                                  corner_price=5, r_min=2, r_max=20, r_default=5, is_active=True))
        db.session.add(User(id=1, email='bot@woodpower.pl', password='x', role='user'))
        db.session.commit()
        invalidate_pricing_cache()   # zbuduj cennik z DANYCH TEGO testu, nie z cache


def _bot_product(product_type, selected='dab-lity-ab'):
    """Produkt w formacie create_quote/update_quote (warianty rozwinięte jak z mostu bota)."""
    return {
        'index': 1, 'length': 100, 'width': 50, 'thickness': 3, 'quantity': 2,
        'shape': 'rectangular', 'finishing_type': 'Surowe', 'edges': [],
        'product_type': product_type,
        'variants': [{'variant_code': code, 'is_selected': code == selected}
                     for code in VARIANT_MAPPING],
    }


def test_create_quote_utrwala_product_type(app):
    _seed_pricing_and_bot_user(app)
    with app.app_context():
        data = {'client_id': 1, 'quote_client_type': 'Detal+',
                'products': [_bot_product('blat')]}
        result, status = create_quote(data, 'bot@woodpower.pl')
        assert status == 200, result
        detail = QuoteItemDetails.query.filter_by(
            quote_id=result['quote_id'], product_index=1).first()
        assert detail.product_type == 'blat'


def test_http_round_trip_quotes_do_by_token(app, client):
    """Pełny round-trip PRZEZ TRASY HTTP bota: find-or-create -> POST /quotes (z product_type)
    -> GET by-token. Pokrywa remapping payloadu w bot_create_quote (_products_with_all_variants,
    client_type) i potwierdza, że total zawiera krawędzie (a nie sam materiał)."""
    _seed_pricing_and_bot_user(app)
    cresp = client.post('/api/bot/clients/find-or-create',
                        json={'email': 'sklep@example.pl', 'name': 'Klient Sklep'}, headers=_auth())
    assert cresp.status_code == 200
    cid = cresp.get_json()['client']['id']

    qbody = {'client_id': cid, 'client_type': 'Detal+', 'products': [{
        'index': 1, 'length': 120, 'width': 60, 'thickness': 4, 'quantity': 2,
        'shape': 'rectangular', 'selected_variant': 'dab-lity-ab',
        'finishing_type': 'Surowe', 'edges': [{'letter': 'A', 'type': 'round', 'r_value': 5}],
        'edges_mode': 'basic', 'product_type': 'blat'}]}
    qresp = client.post('/api/bot/quotes', json=qbody, headers=_auth())
    assert qresp.status_code == 200 and qresp.get_json()['ok'] is True, qresp.get_json()
    token = qresp.get_json()['public_url'].rsplit('/', 1)[-1]

    bresp = client.get(f'/api/bot/quotes/by-token/{token}', headers=_auth())
    body = bresp.get_json()
    assert body['ok'] is True
    item = body['quote']['items'][0]
    assert item['product_type'] == 'blat'                       # round-trip przez realne trasy
    assert item['selected_variant'] == 'dab-lity-ab'
    assert item['finishing_netto'] == 0.0                       # Surowe = 0
    assert item['edges_netto'] > 0                              # krawędź round doliczona
    # total pozycji = material×ilość + wykończenie + krawędzie; totals wyceny = suma pozycji
    assert item['total_netto'] == round(item['unit_netto'] * 2 + item['edges_netto'], 2)
    assert body['quote']['totals']['total_netto'] == item['total_netto']


def test_update_quote_zachowuje_zmiane_product_type(app):
    """PUT (update_quote) też utrwala product_type — a że nadpisuje pozycje w całości,
    zmiana blat->schody musi być widoczna po edycji."""
    _seed_pricing_and_bot_user(app)
    with app.app_context():
        result, status = create_quote(
            {'client_id': 1, 'quote_client_type': 'Detal+',
             'products': [_bot_product('blat')]}, 'bot@woodpower.pl')
        assert status == 200, result
        quote = Quote.query.get(result['quote_id'])

        data = {'products': [_bot_product('schody')],
                'settings': {'clientType': 'Detal+', 'notes': ''}}
        upd, ustatus = update_quote(quote.edit_uuid, data,
                                    SimpleNamespace(id=1, role='admin'))
        assert ustatus == 200 and upd.get('success'), upd
        detail = QuoteItemDetails.query.filter_by(
            quote_id=quote.id, product_index=1).first()
        assert detail.product_type == 'schody'
