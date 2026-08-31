# -*- coding: utf-8 -*-
"""
Panel handlowca na wycenie, która ma już zamówienie.

Ścieżka panelu (POST /baselinker/api/quote/<id>/create-order) nie sprawdzała
`base_linker_order_id`. Na wycenie zamówionej przez klienta drugie kliknięcie
tworzyło DRUGIE realne zamówienie, nadpisywało numer i — nowość tej gałęzi —
`baselinker_order_page`, czyli link, który klient JUŻ DOSTAŁ. Link zaczynał
wskazywać zamówienie, o którym klient nic nie wie, a pierwsze zostawało
osierocone.

BaselinkerService jest atrapą — żaden test nie dotyka BaseLinkera.
"""
import os
import sys
from datetime import datetime

import pytest
from flask import Flask
from sqlalchemy.pool import StaticPool

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from extensions import db  # noqa: E402
from modules.baselinker import baselinker_bp  # noqa: E402
from modules.baselinker import routers as bl_routers  # noqa: E402
from modules.baselinker.models import BaselinkerConfig, BaselinkerOrderLog  # noqa: E402
from modules.calculator.models import (  # noqa: E402
    Quote, QuoteItem, QuoteItemDetails, Price, Multiplier,
    FinishingOption, EdgeOption, CalculatorSetting, QuoteCounter, QuoteLog,
)
from modules.clients.models import Client  # noqa: E402
from modules.quotes.models import QuoteStatus  # noqa: E402
from modules.users.models import User  # noqa: E402

ZRODLO = 85727
EMAIL_HANDLOWCA = 'handlowiec@woodpower.pl'

_TABELE = [m.__table__ for m in (
    Price, Multiplier, FinishingOption, EdgeOption, CalculatorSetting, User, Client,
    Quote, QuoteItem, QuoteItemDetails, QuoteCounter, QuoteLog, QuoteStatus,
    BaselinkerConfig, BaselinkerOrderLog,
)]


@pytest.fixture()
def aplikacja(monkeypatch):
    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        'poolclass': StaticPool,
        'connect_args': {'check_same_thread': False},
    }
    app.config['SECRET_KEY'] = 'test'
    app.register_blueprint(baselinker_bp, url_prefix='/baselinker')
    db.init_app(app)

    # Uprawnienia sprawdza PermissionService (osobny moduł, własne testy) —
    # tutaj interesuje nas wyłącznie guard na już zamówionej wycenie.
    from modules.users.services.permission_service import PermissionService
    monkeypatch.setattr(PermissionService, 'user_has_module_access',
                        staticmethod(lambda user_id, module_key: True))

    with app.app_context():
        db.metadata.create_all(bind=db.engine, tables=_TABELE)
        yield app
        db.session.remove()


@pytest.fixture()
def klient_http(aplikacja):
    klient = aplikacja.test_client()
    with klient.session_transaction() as sesja:
        sesja['user_email'] = EMAIL_HANDLOWCA
    return klient


@pytest.fixture()
def serwis(monkeypatch):
    """Atrapa BaselinkerService podstawiona w routerze panelu."""
    wywolania = []

    class _Atrapa:
        def __init__(self, *a, **k):
            pass

        def create_order_from_quote(self, quote, user_id, config):
            wywolania.append(config)
            quote.base_linker_order_id = '888'
            quote.baselinker_order_page = 'https://blsklep.pl/z/888'
            db.session.commit()
            return {'success': True, 'order_id': 888}

    monkeypatch.setattr(bl_routers, 'BaselinkerService', _Atrapa)
    return wywolania


def _zasiej(base_linker_order_id=None, order_page=None):
    db.session.add(QuoteStatus(id=4, name='Złożone'))
    db.session.add(BaselinkerConfig(
        config_type='order_source', baselinker_id=ZRODLO, name='Dębuś VPS',
        is_default=False, is_active=True, sort_order=100,
        created_at=datetime(2026, 8, 30), updated_at=datetime(2026, 8, 30)))
    db.session.add(User(email=EMAIL_HANDLOWCA, first_name='Han', last_name='Dlowiec',
                        role='user', password='x', active=True))
    klient = Client(client_number='K-1', client_name='Jan Testowy',
                    email='jan@example.pl', phone='601234567')
    db.session.add(klient)
    db.session.flush()
    wycena = Quote(quote_number='420/08/26/W',
                   public_token='TOKENPANEL0000000000000000001',
                   status_id=3, client_id=klient.id, quote_type='brutto',
                   courier_name='DPD', shipping_cost_brutto=123.0,
                   base_linker_order_id=base_linker_order_id,
                   baselinker_order_page=order_page)
    db.session.add(wycena)
    db.session.flush()
    db.session.add(QuoteItem(
        quote_id=wycena.id, product_index=1, variant_code='dab-lity-ab',
        length_cm=100, width_cm=50, thickness_cm=3,
        price_netto=100.0, price_brutto=123.0, is_selected=True))
    db.session.commit()
    return wycena.id


def _config():
    return {'order_source_id': ZRODLO, 'payment_method': 'Przelew bankowy',
            'delivery_method': 'DPD', 'shipping_cost_override': 123.0}


class TestPanelNaWycenieZamowionej:
    def test_panel_nie_tworzy_drugiego_zamowienia(self, aplikacja, klient_http, serwis):
        id_wyceny = _zasiej(base_linker_order_id='501',
                            order_page='https://blsklep.pl/z/501')

        odpowiedz = klient_http.post(
            '/baselinker/api/quote/%d/create-order' % id_wyceny, json=_config())

        assert odpowiedz.status_code == 409
        assert serwis == [], 'drugie realne zamówienie w BaseLinkerze'

    def test_panel_nie_nadpisuje_linku_klienta(self, aplikacja, klient_http, serwis):
        id_wyceny = _zasiej(base_linker_order_id='501',
                            order_page='https://blsklep.pl/z/501')

        klient_http.post('/baselinker/api/quote/%d/create-order' % id_wyceny,
                         json=_config())

        with aplikacja.app_context():
            wycena = Quote.query.get(id_wyceny)
            assert wycena.base_linker_order_id == '501'
            assert wycena.baselinker_order_page == 'https://blsklep.pl/z/501'

    def test_odmowa_niesie_numer_istniejacego_zamowienia(self, aplikacja, klient_http,
                                                         serwis):
        # Handlowiec ma z komunikatu wiedzieć, że zamówienie już jest i które.
        id_wyceny = _zasiej(base_linker_order_id='501')

        body = klient_http.post('/baselinker/api/quote/%d/create-order' % id_wyceny,
                                json=_config()).get_json()

        assert body['success'] is False
        assert body['order_id'] == '501'
        assert '501' in body['error']

    def test_wycena_bez_zamowienia_dalej_daje_sie_zamowic(self, aplikacja, klient_http,
                                                          serwis):
        # Kontrola negatywna: guard nie może zablokować normalnej pracy panelu.
        id_wyceny = _zasiej()

        odpowiedz = klient_http.post(
            '/baselinker/api/quote/%d/create-order' % id_wyceny, json=_config())

        assert odpowiedz.status_code == 200
        assert odpowiedz.get_json()['success'] is True
        assert len(serwis) == 1
