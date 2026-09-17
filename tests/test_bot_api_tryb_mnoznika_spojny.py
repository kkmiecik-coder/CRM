# -*- coding: utf-8 -*-
"""auto_multiplier ma znaczyć to samo na WSZYSTKICH trzech endpointach bota.

Do 2026-09-15 flagę respektował wyłącznie /calculate. POST /quotes i
PUT /quotes/<edit_uuid> ustawiały auto_multiplier=True na sztywno i payloadu
w ogóle nie czytały. Kontrakt obiecywał sklepowi, że `auto_multiplier: false`
daje ceny wg grupy cenowej — a to była prawda tylko w podglądzie.

Realny skutek: konfigurator pokazywał jedną kwotę, a zapisana wycena miała
drugą. Rozjazd wychodził dopiero w mailu z linkiem do wyceny, czyli u klienta.

Domyślny tryb pozostaje automatyczny, więc bot (nie wysyła flagi) i sklep
(też nie wysyła) niczego nie zauważą.

Konwencja fixtures jak test_bot_api_client_type_opcjonalny.py.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from flask import Flask
from sqlalchemy.pool import StaticPool

from extensions import db
from modules.calculator.models import Price, Multiplier, Quote, QuoteItem
from modules.calculator.routers.bot_api import bot_api_bp
from modules.calculator.services.pricing_service import invalidate_pricing_cache

import modules.clients.models   # noqa: F401
import modules.quotes.models    # noqa: F401
import modules.users.models     # noqa: F401

from modules.clients.models import Client
from modules.users.models import User

BOT_KEY = 'test-bot-key'
BOT_USER_ID = 1

# 1,00 x 0,50 x 0,03 m = 0,015 m3 x 8200 zl = 123 zl bazy netto (ponizej progu 1000).
CENA_ZA_M3 = 8200
MNOZNIK_GRUPY = 1.3           # "Detal+"
AUTO_UNIT_NETTO = 123.0 * 1.5     # tryb automatyczny: ponizej progu
GRUPA_UNIT_NETTO = 123.0 * MNOZNIK_GRUPY


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
    app.config['BOT_USER_ID'] = BOT_USER_ID
    app.register_blueprint(bot_api_bp, url_prefix='/api/bot')
    db.init_app(app)

    with app.app_context():
        db.create_all()
        db.session.add(Price(species='Dąb', technology='Lity', wood_class='A/B',
                             thickness_min=2, thickness_max=6,
                             length_min=20, length_max=450,
                             width_min=10, width_max=200, price_per_m3=CENA_ZA_M3))
        db.session.add(Multiplier(client_type='Detal+', multiplier=MNOZNIK_GRUPY))
        db.session.add(User(id=BOT_USER_ID, email='bot@woodpower.pl', password='x', role='user'))
        db.session.add(Client(id=1, client_number='chat-1', client_name='Klient Sklep'))
        db.session.commit()
        invalidate_pricing_cache()
        yield app
        db.session.remove()
        invalidate_pricing_cache()


@pytest.fixture()
def client(app):
    return app.test_client()


def _auth():
    return {'X-Bot-Api-Key': BOT_KEY}


def _produkt():
    return {'index': 1, 'length': 100, 'width': 50, 'thickness': 3, 'quantity': 2,
            'shape': 'rectangular', 'selected_variant': 'dab-lity-ab',
            'finishing_type': 'Surowe', 'edges': []}


def _zapisana_pozycja(quote_id):
    """Wybrany wariant zapisanej wyceny — to on trafia do maila i do koszyka."""
    return QuoteItem.query.filter_by(quote_id=quote_id, variant_code='dab-lity-ab').first()


def _utworz(client, **nadpisz):
    body = {'client_id': 1, 'products': [_produkt()]}
    body.update(nadpisz)
    resp = client.post('/api/bot/quotes', json=body, headers=_auth())
    assert resp.status_code == 200, resp.get_data(as_text=True)
    return resp.get_json()


def _braki_client_type(body):
    return [m['field'] for m in body.get('missing_fields') or []]


# =============================================================================
# Sedno: podglad i zapis musza dac TE SAMA kwote
# =============================================================================

def test_calculate_i_quotes_daja_te_sama_cene_przy_recznym_mnozniku(app, client):
    """Ten test opisuje faktyczny blad: konfigurator pokazywal cene wg grupy
    cenowej, a zapisana wycena byla policzona automatycznie."""
    payload = {'products': [_produkt()], 'auto_multiplier': False,
               'client_type': 'Detal+'}

    podglad = client.post('/api/bot/calculate', json=payload, headers=_auth()).get_json()
    assert podglad['ok'] is True, podglad
    cena_z_podgladu = [v for v in podglad['products'][0]['variants']
                       if v['variant_code'] == 'dab-lity-ab'][0]['unit_netto']

    zapis = _utworz(client, auto_multiplier=False, client_type='Detal+')
    assert zapis['ok'] is True, zapis

    with app.app_context():
        pozycja = _zapisana_pozycja(zapis['quote_id'])
        assert abs(float(pozycja.price_netto) - cena_z_podgladu) < 0.01, (
            'Podglad %s vs zapis %s — klient zobaczy rozjazd w mailu'
            % (cena_z_podgladu, pozycja.price_netto))
        assert abs(float(pozycja.price_netto) - GRUPA_UNIT_NETTO) < 0.01


# =============================================================================
# POST /quotes
# =============================================================================

def test_quotes_respektuje_auto_multiplier_false(app, client):
    body = _utworz(client, auto_multiplier=False, client_type='Detal+')
    assert body['ok'] is True, body
    with app.app_context():
        assert abs(float(_zapisana_pozycja(body['quote_id']).multiplier) - MNOZNIK_GRUPY) < 0.01
        # Panel wycen czyta Quote.quote_multiplier (quotes.js:960) — w trybie wg
        # grupy ma tam byc konkretna wartosc, a nie NULL zarezerwowany dla auto.
        assert abs(float(Quote.query.get(body['quote_id']).quote_multiplier)
                   - MNOZNIK_GRUPY) < 0.01


def test_quotes_bez_flagi_dalej_liczy_automatycznie(app, client):
    """Domyslny tryb sie NIE zmienia — bot i sklep nie wysylaja flagi."""
    body = _utworz(client, client_type='Detal+')
    assert body['ok'] is True, body
    with app.app_context():
        pozycja = _zapisana_pozycja(body['quote_id'])
        assert abs(float(pozycja.multiplier) - 1.5) < 0.01
        assert abs(float(pozycja.price_netto) - AUTO_UNIT_NETTO) < 0.01
        # Tryb auto: jedna wartosc dla calej wyceny nie istnieje (kontrakt, sekcja 0)
        assert Quote.query.get(body['quote_id']).quote_multiplier is None


def test_quotes_przy_false_bez_grupy_prosi_o_grupe(client):
    """Skoro flaga dziala, to i walidacja musi za nia isc — inaczej zapis
    przewrocilby sie na blednym kodzie zamiast poprosic o brakujace pole."""
    resp = client.post('/api/bot/quotes',
                       json={'client_id': 1, 'products': [_produkt()],
                             'auto_multiplier': False},
                       headers=_auth())
    body = resp.get_json()
    assert body['ok'] is False
    assert _braki_client_type(body) == ['client_type']


# =============================================================================
# PUT /quotes/<edit_uuid>
# =============================================================================

def test_put_respektuje_auto_multiplier_false(app, client):
    utworzona = _utworz(client, client_type='Detal+')
    resp = client.put('/api/bot/quotes/%s' % utworzona['edit_uuid'],
                      json={'products': [_produkt()], 'auto_multiplier': False,
                            'client_type': 'Detal+'}, headers=_auth())
    body = resp.get_json()
    assert body['ok'] is True, body
    with app.app_context():
        assert abs(float(_zapisana_pozycja(body['quote_id']).multiplier) - MNOZNIK_GRUPY) < 0.01


def test_put_przy_false_bierze_grupe_zapisana_na_wycenie(app, client):
    """Aktualizacja nie powtarza calego kontekstu wyceny. Skoro grupa jest juz
    na wycenie, PUT bez niej ma jej uzyc, a nie wywrocic sie na braku."""
    utworzona = _utworz(client, client_type='Detal+')
    resp = client.put('/api/bot/quotes/%s' % utworzona['edit_uuid'],
                      json={'products': [_produkt()], 'auto_multiplier': False},
                      headers=_auth())
    body = resp.get_json()
    assert body['ok'] is True, body
    with app.app_context():
        assert abs(float(_zapisana_pozycja(body['quote_id']).multiplier) - MNOZNIK_GRUPY) < 0.01
        assert Quote.query.get(body['quote_id']).quote_client_type == 'Detal+'


def test_put_przy_false_bez_grupy_gdziekolwiek_prosi_o_grupe(app, client):
    utworzona = _utworz(client)          # wycena bez grupy cenowej
    resp = client.put('/api/bot/quotes/%s' % utworzona['edit_uuid'],
                      json={'products': [_produkt()], 'auto_multiplier': False},
                      headers=_auth())
    body = resp.get_json()
    assert body['ok'] is False
    assert _braki_client_type(body) == ['client_type']


def test_put_bez_flagi_dalej_liczy_automatycznie(app, client):
    utworzona = _utworz(client, client_type='Detal+')
    resp = client.put('/api/bot/quotes/%s' % utworzona['edit_uuid'],
                      json={'products': [_produkt()]}, headers=_auth())
    body = resp.get_json()
    assert body['ok'] is True, body
    with app.app_context():
        assert abs(float(_zapisana_pozycja(body['quote_id']).multiplier) - 1.5) < 0.01
