# -*- coding: utf-8 -*-
"""
Wspólna apka testowa logistyki. Importuj w pliku testów:

    from tests.logistyka_fixtures import BASE, app, client, zamowienie, produkt  # noqa: F401

Rejestruje panel logistyki i API mobilne na jednej minimalnej apce (SQLite
in-memory). Dekorator dostępu do modułu podmieniamy na przelotkę — tak samo
i z tych samych powodów co tests/sawmill_fixtures.py.
"""
import itertools
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
    ProductionStationEvent, ProductionWorker,
)
from modules.production.logistics.models import LogisticsLog
from modules.users.models import User
from modules.calculator.models import Multiplier  # noqa: F401
from modules.clients.models import Client  # noqa: F401
import modules.quotes.models  # noqa: F401
from modules.quotes.models import QuoteStatus  # noqa: F401

BASE = '/production/api/logistics'
SEKRET_CRONA = 'sekret-testowy-logistyki'

TABLES = [m.__table__ for m in (
    User, ProductionDevice, ProductionConfig, ProcessedMobileOperation,
    ProductionOrder, ProductionProduct, ProductionConfiguration,
    ProductionReworkLog, ProductionStationEvent, ProductionWorker, LogisticsLog,
)]

# LONGTEXT nie istnieje w SQLite — ten sam zabieg co w tests/test_routing_krawedzie.py.
ProductionOrder.__table__.c.shipping_label_base64.type = db.Text()

_licznik = itertools.count(1)


@pytest.fixture()
def app(monkeypatch):
    import modules.users.decorators as decorators
    monkeypatch.setattr(decorators, 'require_module_access',
                        lambda *a, **k: (lambda f: f))

    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        'poolclass': StaticPool,
        'connect_args': {'check_same_thread': False},
    }
    app.config['LOGIN_DISABLED'] = True
    app.config['PRODUCTION_CRON_SECRET'] = SEKRET_CRONA
    app.config['API_MOBILE'] = {
        'jwt_secret': 'x' * 64, 'token_ttl_days': 365,
        'ip_whitelist': [], 'min_supported_app_version': '0.0.0',
    }

    from modules.production.logistics import logistics_panel_bp
    from modules.production.routers.mobile_api import mobile_api_bp
    app.register_blueprint(logistics_panel_bp, url_prefix=BASE)
    app.register_blueprint(mobile_api_bp, url_prefix='/api/mobile')
    db.init_app(app)

    with app.app_context():
        db.metadata.create_all(bind=db.engine, tables=TABLES)
        yield app
        db.session.remove()


@pytest.fixture()
def client(app):
    return app.test_client()


def zamowienie(sposob=None, statusy=('czeka_na_wyciecie',), delivery_method='Kurier DPD',
               miasto='Kraków', bl_id=None, **kolumny):
    """Zamówienie z jednym produktem na każdy podany status (quantity=2)."""
    numer = next(_licznik)
    order = ProductionOrder(
        baselinker_order_id=bl_id if bl_id is not None else 700000 + numer,
        internal_order_number='26/%05d' % numer,
        client_name='Klient %d' % numer,
        delivery_method=delivery_method,
        delivery_address='ul. Testowa %d' % numer,
        delivery_city=miasto,
        delivery_postcode='30-001',
        override_delivery_method=sposob,
        **kolumny)
    db.session.add(order)
    db.session.flush()
    for i, status in enumerate(statusy, start=1):
        produkt(order, status=status, sekwencja=i)
    db.session.commit()
    return order


def produkt(order, status='czeka_na_wyciecie', sekwencja=None, quantity=2, **kolumny):
    sekwencja = sekwencja or (len(order.products) + 1)
    p = ProductionProduct(
        # `order=order` (nie `order_id=order.id`): back_populates trzyma
        # `order.products` w pamięci w zgodzie z bazą od razu, bez odświeżania.
        order=order,
        short_product_id='%d_%d' % (order.id, sekwencja),
        product_sequence_in_order=sekwencja,
        original_product_name='Blat dębowy 100x60x4',
        quantity=quantity,
        volume_m3=0.024,
        current_status=status,
        **kolumny)
    db.session.add(p)
    db.session.flush()
    if status == 'spakowane':
        p.quantity_done_packaging = quantity
    return p
