# -*- coding: utf-8 -*-
"""client_type wymagany DOKŁADNIE wtedy, gdy wpływa na cenę.

Od 2026-09-15 mnożnik marży dobiera CRM per wariant (`auto_multiplier`, domyślnie
włączony), więc grupa cenowa nie ustala już ceny — a mimo to walidacja jej żądała.
Sklep PrestaShop musiał wysyłać wartość, która nic nie robi, i trzymać w backoffice
ustawienie „Grupa cenowa", które tylko myliło.

Przy `auto_multiplier: false` mnożnik nadal bierze się z grupy cenowej
(pricing_service.calculate_material_variants, gałąź `else multiplier`) — bez niej
ta ścieżka nie ma z czego policzyć ceny, więc tam wymóg zostaje.

Testy idą PRZEZ TRASĘ HTTP, nie po samym walidatorze: w bot_calculate() domyślne
`auto_multiplier` ustawiane jest osobnym `setdefault`, więc sama kolejność tych
dwóch kroków decyduje, czy walidator w ogóle wie, w jakim jest trybie. Test
jednostkowy walidatora tego nie złapie.

Konwencja fixtures jak test_bot_api_options_edges.py: minimalny Flask + SQLite
in-memory na StaticPool.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from flask import Flask
from sqlalchemy.pool import StaticPool

from extensions import db
from modules.calculator.models import (
    Price, Multiplier, FinishingOption, EdgeOption, CalculatorSetting, Quote,
)
from modules.calculator.routers.bot_api import bot_api_bp
from modules.calculator.services.pricing_service import invalidate_pricing_cache

# Rejestr mapperów — jak w pozostałych testach bot_api (relacje Quote -> Client/Status)
import modules.clients.models   # noqa: F401
import modules.quotes.models    # noqa: F401
import modules.users.models     # noqa: F401

from modules.clients.models import Client
from modules.users.models import User

BOT_KEY = 'test-bot-key'
BOT_USER_ID = 1

_TABLES = None  # ustawiane w fixture (create_all dla całej metadata bywa za szerokie)

# Cennik dobrany tak, żeby oba tryby dały RÓŻNE kwoty — inaczej test nie odróżni,
# który mnożnik zadziałał. 1,00 x 0,50 x 0,03 m = 0,015 m3 x 8200 zł = 123 zł bazy.
CENA_ZA_M3 = 8200
BAZA_NETTO = 123.0                      # 0.015 m3 * 8200
AUTO_UNIT_NETTO = BAZA_NETTO * 1.5      # poniżej progu 1000 zł -> mnożnik automatyczny 1.5
GRUPA_UNIT_NETTO = BAZA_NETTO * 1.3     # mnożnik grupy cenowej "Detal+"


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
        db.session.add(Multiplier(client_type='Detal+', multiplier=1.3))
        db.session.add(User(id=BOT_USER_ID, email='bot@woodpower.pl', password='x', role='user'))
        db.session.add(Client(id=1, client_number='chat-1', client_name='Klient Sklep'))
        db.session.commit()
        invalidate_pricing_cache()   # cennik z danych TEGO testu, nie z cache innego
        yield app
        db.session.remove()
        invalidate_pricing_cache()


@pytest.fixture()
def client(app):
    return app.test_client()


def _auth():
    return {'X-Bot-Api-Key': BOT_KEY}


def _produkt():
    """Komplet pól wymaganych per produkt — braki mają wynikać TYLKO z client_type."""
    return {'index': 1, 'length': 100, 'width': 50, 'thickness': 3, 'quantity': 2,
            'shape': 'rectangular', 'selected_variant': 'dab-lity-ab',
            'finishing_type': 'Surowe', 'edges': []}


def _wybrany_wariant(body):
    warianty = body['products'][0]['variants']
    return next(w for w in warianty if w['variant_code'] == 'dab-lity-ab')


def _braki_client_type(body):
    return [m for m in body.get('missing_fields') or [] if m['field'] == 'client_type']


# =============================================================================
# /calculate — sprawdzian dla sklepu: bez client_type mają wrócić ceny
# =============================================================================

def test_calculate_bez_client_type_w_trybie_auto_zwraca_ceny(client):
    """SPRAWDZIAN, na który czeka sesja sklepowa przed swoją zmianą.

    To jest ten test, który łapie pułapkę kolejności: gdyby walidacja braków
    stała PRZED ustaleniem trybu, walidator nie wiedziałby, że pole jest zbędne,
    i odesłałby ok:false + missing_fields — czyli wywalił każde przeliczenie
    w konfiguratorze sklepu.
    """
    resp = client.post('/api/bot/calculate', json={'products': [_produkt()]}, headers=_auth())
    assert resp.status_code == 200, resp.get_data(as_text=True)
    body = resp.get_json()

    assert body['ok'] is True, body
    assert body['missing_fields'] == []
    assert body['multiplier_mode'] == 'auto'

    wariant = _wybrany_wariant(body)
    assert wariant['multiplier'] == 1.5
    assert abs(wariant['unit_netto'] - AUTO_UNIT_NETTO) < 0.01
    assert body['totals']['total_netto'] > 0


def test_calculate_bez_client_type_przy_recznym_mnozniku_prosi_o_grupe(client):
    """auto_multiplier: false — cena bierze się z grupy cenowej, więc bez niej
    nie ma z czego liczyć. Wymóg MUSI tu zostać."""
    resp = client.post('/api/bot/calculate',
                       json={'products': [_produkt()], 'auto_multiplier': False},
                       headers=_auth())
    assert resp.status_code == 200, resp.get_data(as_text=True)
    body = resp.get_json()

    assert body['ok'] is False
    assert _braki_client_type(body) == [
        {'product_index': None, 'field': 'client_type',
         'hint': 'grupa cenowa (client_types z /options)'}]


def test_calculate_z_client_type_przy_recznym_mnozniku_liczy_wg_grupy(client):
    """Furtka przejściowa dla sklepu ma dalej działać — i liczyć INNĄ kwotę niż auto."""
    resp = client.post('/api/bot/calculate',
                       json={'products': [_produkt()], 'auto_multiplier': False,
                             'client_type': 'Detal+'},
                       headers=_auth())
    body = resp.get_json()

    assert body['ok'] is True, body
    assert body['multiplier_mode'] == 'client_type'
    wariant = _wybrany_wariant(body)
    assert wariant['multiplier'] == 1.3
    assert abs(wariant['unit_netto'] - GRUPA_UNIT_NETTO) < 0.01


def test_calculate_braki_produktu_wciaz_raportowane_bez_client_type(client):
    """Zniesienie wymogu grupy cenowej nie może wyłączyć reszty walidacji."""
    produkt = _produkt()
    del produkt['length']
    resp = client.post('/api/bot/calculate', json={'products': [produkt]}, headers=_auth())
    body = resp.get_json()

    assert body['ok'] is False
    assert [m['field'] for m in body['missing_fields']] == ['length']


# =============================================================================
# /quotes — zapis wyceny bez grupy cenowej (quote_client_type zostaje NULL)
# =============================================================================

def test_quotes_zapisuje_wycene_bez_client_type(app, client):
    """/quotes ma auto_multiplier=True na sztywno, więc grupa cenowa jest tam
    opcjonalna ZAWSZE. Quote.quote_client_type wolno zostawić NULL — kolumna jest
    nullable, a log tworzenia wyceny już to znosi ('brak grupy')."""
    resp = client.post('/api/bot/quotes',
                       json={'client_id': 1, 'products': [_produkt()]}, headers=_auth())
    assert resp.status_code == 200, resp.get_data(as_text=True)
    body = resp.get_json()

    assert body['ok'] is True, body
    with app.app_context():
        quote = Quote.query.get(body['quote_id'])
        assert quote.quote_client_type is None
        assert quote.quote_multiplier is None      # tryb auto: jedna wartość nie istnieje


def test_put_bez_client_type_nie_kasuje_zapisanej_grupy(app, client):
    """Pominięcie opcjonalnego pola nie może KASOWAĆ danych.

    PUT buduje settings['clientType'] z payloadu, a update_quote przypisuje je
    bezwarunkowo — więc aktualizacja bez grupy zerowała grupę zapisaną wcześniej.
    Do tej pory nieosiągalne w praktyce (sklep i bot zawsze wysyłały pole),
    ale od kiedy pole jest opcjonalne, to normalny przebieg sklepu."""
    utworz = client.post('/api/bot/quotes',
                         json={'client_id': 1, 'client_type': 'Detal+',
                               'products': [_produkt()]}, headers=_auth())
    body = utworz.get_json()
    assert body['ok'] is True, body
    edit_uuid, quote_id = body['edit_uuid'], body['quote_id']

    produkt = _produkt()
    produkt['quantity'] = 3
    resp = client.put('/api/bot/quotes/%s' % edit_uuid,
                      json={'products': [produkt]}, headers=_auth())
    assert resp.status_code == 200, resp.get_data(as_text=True)
    assert resp.get_json()['ok'] is True, resp.get_json()

    with app.app_context():
        assert Quote.query.get(quote_id).quote_client_type == 'Detal+'


def test_put_z_client_type_nadal_zmienia_grupe(app, client):
    """Jawnie podana grupa ma dalej nadpisywać — to nie jest pole tylko-do-zapisu."""
    utworz = client.post('/api/bot/quotes',
                         json={'client_id': 1, 'client_type': 'Detal+',
                               'products': [_produkt()]}, headers=_auth())
    body = utworz.get_json()
    assert body['ok'] is True, body

    resp = client.put('/api/bot/quotes/%s' % body['edit_uuid'],
                      json={'client_type': 'Hurt', 'products': [_produkt()]},
                      headers=_auth())
    assert resp.get_json()['ok'] is True, resp.get_json()

    with app.app_context():
        assert Quote.query.get(body['quote_id']).quote_client_type == 'Hurt'
