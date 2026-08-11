# -*- coding: utf-8 -*-
"""
Test regresyjny dla Etapu 0 profili pracownikow (docs/worker-profiles-backend.md, 3.3).

Po usunieciu webowych paneli wykonawczych stanowisk jedyna sciezka zamykania
stanowiska to POST /api/mobile/orders/<id>/complete. Ten test pilnuje, ze ta
sciezka nadal rejestruje wpis w kolejce synchronizacji statusow Baselinkera
(mobile_api_service.mark_order_complete() -> schedule_after_station_complete()) -
bez tego zamowienia przestalyby dostawac status "Produkcja zakonczona" /
"Zamowienie spakowane" w BL.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from flask import Flask
from sqlalchemy.pool import StaticPool

from extensions import db
from modules.production.models import (
    ProcessedMobileOperation, ProductionConfig, ProductionConfiguration,
    ProductionDevice, ProductionOrder, ProductionProduct, ProductionReworkLog,
)
from modules.production.routers.mobile_api import mobile_api_bp
from modules.production.services.mobile_api_service import generate_token
from modules.users.models import User
# Import wymagany, zeby topologiczne sortowanie FK w create_all znalazlo
# tabele 'users' w metadata (ProductionConfig.updated_by, ProductionReworkLog.user_id
# itp. maja ForeignKey('users.id')) - ten sam powod co w test_sawmill_mobile_api.py.
from modules.calculator.models import Multiplier  # noqa: F401
from modules.clients.models import Client  # noqa: F401
import modules.quotes.models  # noqa: F401
from modules.quotes.models import QuoteStatus  # noqa: F401

_TABLES = [m.__table__ for m in (
    User, ProductionDevice, ProductionConfig, ProcessedMobileOperation,
    ProductionOrder, ProductionProduct, ProductionConfiguration, ProductionReworkLog,
)]

# SQLite (tylko testy) nie zna typu MySQL LONGTEXT (ProductionOrder.shipping_label_base64) -
# ten sam problem i to samo obejście co ProcessedMobileOperation.response_body w models.py
# (LONGTEXT().with_variant(Text(), 'sqlite')), tylko zrobione tu zamiast w modelu produkcyjnym.
ProductionOrder.__table__.c.shipping_label_base64.type = db.Text()


@pytest.fixture()
def app():
    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        'poolclass': StaticPool,
        'connect_args': {'check_same_thread': False},
    }
    app.config['API_MOBILE'] = {
        'jwt_secret': 'x' * 64,
        'token_ttl_days': 365,
        'ip_whitelist': [],
        'min_supported_app_version': '0.0.0',
    }
    app.register_blueprint(mobile_api_bp, url_prefix='/api/mobile')
    db.init_app(app)
    with app.app_context():
        db.metadata.create_all(bind=db.engine, tables=_TABLES)
        yield app
        db.session.remove()


@pytest.fixture()
def client(app):
    return app.test_client()


def _urzadzenie(app, station_code='packaging'):
    with app.app_context():
        device = ProductionDevice(
            device_id='TABLET-1', device_name='Tablet pakowania', station_code=station_code)
        db.session.add(device)
        db.session.commit()
        return generate_token(device)


def _zlecenie_gotowe_do_pakowania(app):
    """Zamowienie z jednym produktem czekajacym na pakowanie."""
    with app.app_context():
        order = ProductionOrder(
            baselinker_order_id=990001,
            internal_order_number='26/00042',
        )
        db.session.add(order)
        db.session.flush()

        product = ProductionProduct(
            order_id=order.id,
            short_product_id='26042_1',
            product_sequence_in_order=1,
            original_product_name='Deska tarasowa 200x15x2.5',
            quantity=1,
            current_status='czeka_na_pakowanie',
        )
        db.session.add(product)
        db.session.commit()
        return product.id, order.internal_order_number


def test_zamkniecie_stanowiska_przez_mobile_api_zostawia_wpis_w_kolejce_sync_bl(
    client, app, monkeypatch
):
    """
    POST /api/mobile/orders/<id>/complete (stanowisko 'packaging') musi wywolac
    schedule_after_station_complete(internal_order_number, 'packaging') -
    to jest jedyny mechanizm pilnujacy integracji z BL po usunieciu paneli webowych.
    """
    token = _urzadzenie(app, station_code='packaging')
    product_id, internal_order_number = _zlecenie_gotowe_do_pakowania(app)

    zaplanowane_synchronizacje = []

    def fake_schedule(order_number, station_code):
        zaplanowane_synchronizacje.append((order_number, station_code))

    monkeypatch.setattr(
        'modules.production.services.baselinker_status_sync.schedule_after_station_complete',
        fake_schedule,
    )

    response = client.post(
        '/api/mobile/orders/{}/complete'.format(product_id),
        headers={'Authorization': 'Bearer ' + token, 'X-App-Version': '1.0.0'},
        json={},
    )

    assert response.status_code == 200
    assert zaplanowane_synchronizacje == [(internal_order_number, 'packaging')]

    with app.app_context():
        refreshed = ProductionProduct.query.get(product_id)
        assert refreshed.current_status == 'spakowane'
