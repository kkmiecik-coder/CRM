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
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from flask import Blueprint, Flask
from sqlalchemy.pool import StaticPool

from extensions import db
from modules.production.models import (
    LabelPrintJob, ProcessedMobileOperation, ProductionConfig, ProductionConfiguration,
    ProductionDevice, ProductionOrder, ProductionPackage, ProductionProduct,
    ProductionReworkLog, ProductionStationEvent, ProductionWorker, ProductionWorkerSession,
)
from modules.production.logistics.models import LogisticsLog, OrderGeo, Route, RouteStop, Vehicle
from modules.production.logistics.services import bl_sync as _bl_sync
from modules.users.models import User
from modules.calculator.models import Multiplier  # noqa: F401
from modules.clients.models import Client  # noqa: F401
import modules.quotes.models  # noqa: F401
from modules.quotes.models import QuoteStatus  # noqa: F401

BASE = '/production/api/logistics'
SEKRET_CRONA = 'sekret-testowy-logistyki'
# (M8) „Dziś” tras logistyki (routes.dzis) zamrożone na dzień powstania testów: daty
# wpisane w testach (np. '2026-10-01') muszą mieścić się w granicach dat tras
# (dziś − 1 rok … dziś + 2 lata) także za rok — inaczej testy zaczęłyby padać same.
DZIS_TESTOW = date(2026, 9, 26)
STATYKA_PRODUKCJI = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                 'modules', 'production', 'static')

TABLES = [m.__table__ for m in (
    User, ProductionDevice, ProductionConfig, ProcessedMobileOperation,
    ProductionOrder, ProductionProduct, ProductionConfiguration,
    ProductionReworkLog, ProductionStationEvent, ProductionWorker, LogisticsLog, OrderGeo,
    Vehicle, Route, RouteStop, LabelPrintJob, ProductionPackage,
    ProductionWorkerSession,   # touch_sessions (API Weryfikacji) czyta sesje pracowników
)]

# LONGTEXT nie istnieje w SQLite — ten sam zabieg co w tests/test_routing_krawedzie.py.
ProductionOrder.__table__.c.shipping_label_base64.type = db.Text()

_licznik = itertools.count(1)
# Prawdziwy start wątku dopychacza Base. — fikstura `app` podmienia tylko jego (patrz komentarz w `app`).
_URUCHOM_W_TLE = _bl_sync.uruchom_w_tle


@pytest.fixture()
def app(monkeypatch):
    import modules.users.decorators as decorators
    monkeypatch.setattr(decorators, 'require_module_access',
                        lambda *a, **k: (lambda f: f))
    from modules.production.logistics.services import routes as uslugi_tras
    monkeypatch.setattr(uslugi_tras, 'dzis', lambda: DZIS_TESTOW)
    # Zapisy logistyki (panel tras, telefony) planują dopychacz Base. po commicie: bl_sync.po_zmianie →
    # uruchom_w_tle. Prawdziwy wątek dopychacza pracowałby w testach na tym samym połączeniu StaticPool co test
    # i losowo psuł jego transakcję — podmieniamy sam start wątku. po_zmianie i lista w `g` działają jak dotąd.
    # Tylko gdy nikt go jeszcze nie podmienił: fikstura pliku testów, która liczy starty, mogła zrobić to
    # wcześniej (autouse bez zależności od `app`); późniejsze podmiany i tak wygrywają.
    if _bl_sync.uruchom_w_tle is _URUCHOM_W_TLE:
        monkeypatch.setattr(_bl_sync, 'uruchom_w_tle', lambda app_: True)

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
    from modules.production.logistics.routers.weryfikacja_api import weryfikacja_mobile_bp
    app.register_blueprint(weryfikacja_mobile_bp, url_prefix='/api/mobile/verification')
    from modules.production.logistics.routers.dostawa_api import dostawa_mobile_bp
    app.register_blueprint(dostawa_mobile_bp, url_prefix='/api/mobile/delivery')
    # Szablon zakładki bierze Leaflet przez url_for('production.static') — stawiamy
    # sam folder statyczny modułu produkcji pod tym samym adresem co w aplikacji,
    # bez rejestrowania całego modułu produkcji.
    app.register_blueprint(Blueprint(
        'production', __name__, static_folder=STATYKA_PRODUKCJI,
        static_url_path='/production/static', url_prefix='/production'))
    db.init_app(app)

    with app.app_context():
        db.metadata.create_all(bind=db.engine, tables=TABLES)
        yield app
        db.session.remove()


@pytest.fixture()
def client(app):
    return app.test_client()


def zamowienie(sposob=None, statusy=('czeka_na_wyciecie',), delivery_method='Kurier DPD',
               miasto='Kraków', bl_id=None, numer_wewnetrzny=None, **kolumny):
    """Zamówienie z jednym produktem na każdy podany status (quantity=2).

    `numer_wewnetrzny` — same cyfry jak na produkcji; potrzebne tam, gdzie numer idzie
    w ścieżce URL (endpointy paczek).
    """
    numer = next(_licznik)
    order = ProductionOrder(
        baselinker_order_id=bl_id if bl_id is not None else 700000 + numer,
        internal_order_number=(numer_wewnetrzny if numer_wewnetrzny is not None
                               else '26/%05d' % numer),
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


def pojazd(name=None, capacity_kg=None, is_active=True, registration=None):
    """Pojazd floty."""
    numer = next(_licznik)
    v = Vehicle(name=name or 'Pojazd %d' % numer, registration=registration or 'KR %05d' % numer,
                capacity_kg=capacity_kg, is_active=is_active)
    db.session.add(v)
    db.session.commit()
    return v


def kierowca(imie='Jan', nazwisko=None, aktywny=True):
    """Kierowca trasy: pracownik produkcji ZE znacznikiem is_driver (runda 2 — tylko taki
    jest w wyborze kierowcy i przechodzi walidację nowego przypisania do trasy)."""
    k = ProductionWorker(first_name=imie, last_name=nazwisko or 'Kierowca %d' % next(_licznik),
                         is_active=aktywny, is_driver=True)
    db.session.add(k)
    db.session.commit()
    return k


def pracownik(imie='Piotr', nazwisko=None, aktywny=True):
    """Pracownik produkcji BEZ znacznika kierowcy (kandydat na kierowcę)."""
    p = ProductionWorker(first_name=imie, last_name=nazwisko or 'Pracownik %d' % next(_licznik),
                         is_active=aktywny, is_driver=False)
    db.session.add(p)
    db.session.commit()
    return p
