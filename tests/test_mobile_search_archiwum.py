# -*- coding: utf-8 -*-
"""
Wyszukiwarka tabletu (GET /api/mobile/orders/search) a archiwum.

Spakowane zamówienia są w wynikach celowo — tablet otwiera je tylko do
podglądu. Muszą jednak iść ZA aktywnymi: pozycje spakowane zachowują
priority_rank z czasów produkcji (nikt go nie zeruje), a sortowanie po nim
wypychało stare zamówienia z rangą 1 na górę i zjadało limit, zanim trafiło
się cokolwiek w produkcji.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime

import pytest
from flask import Flask
from sqlalchemy.pool import StaticPool

from extensions import db
from modules.production.models import (
    ProcessedMobileOperation, ProductionConfig, ProductionConfiguration,
    ProductionDevice, ProductionOrder, ProductionProduct, ProductionReworkLog,
)
from modules.production.routers.mobile_api import mobile_api_bp
from modules.production.services.mobile_api_service import (
    generate_token, search_orders_global,
)
from modules.users.models import User
# Importy rejestrujące mappery — ten sam powód co w
# tests/test_mobile_api_alias_krawedzi.py.
from modules.calculator.models import Multiplier  # noqa: F401
from modules.clients.models import Client  # noqa: F401
import modules.quotes.models  # noqa: F401

_TABLES = [m.__table__ for m in (
    User, ProductionDevice, ProductionConfig, ProcessedMobileOperation,
    ProductionOrder, ProductionProduct, ProductionConfiguration, ProductionReworkLog,
)]

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
        'jwt_expiry_days': 365,
        'ip_whitelist': [],
        'min_supported_app_version': '0.0.0',
    }
    app.register_blueprint(mobile_api_bp, url_prefix='/api/mobile')
    db.init_app(app)
    with app.app_context():
        db.metadata.create_all(bind=db.engine, tables=_TABLES)
        yield app
        db.session.remove()


@pytest.fixture(autouse=True)
def czysty_cache_configu():
    from modules.production.services.config_service import invalidate_config_cache
    invalidate_config_cache()
    yield
    invalidate_config_cache()


_licznik = {'bl': 880000}


def _zamowienie(app, numer, pozycje, klient='Jan Kowalski'):
    """
    Zamówienie z pozycjami podanymi jako lista słowników pól produktu.
    Zwraca numer wewnętrzny.
    """
    with app.app_context():
        _licznik['bl'] += 1
        order = ProductionOrder(
            baselinker_order_id=_licznik['bl'],
            internal_order_number=numer,
            client_name=klient,
            delivery_method='Kurier DPD',
            delivery_address='ul. Testowa 1',
            delivery_city='Warszawa',
            delivery_postcode='00-001',
        )
        db.session.add(order)
        db.session.flush()
        for i, pola in enumerate(pozycje, start=1):
            dane = dict(
                order_id=order.id,
                short_product_id='{}_{}'.format(numer, i),
                product_sequence_in_order=i,
                original_product_name='Blat dębowy',
                quantity=1,
            )
            dane.update(pola)
            db.session.add(ProductionProduct(**dane))
        db.session.commit()
        return numer


def _numery(items):
    """Numery zamówień w kolejności pierwszego wystąpienia — tak grupuje apka."""
    wynik = []
    for it in items:
        if it.order.internal_order_number not in wynik:
            wynik.append(it.order.internal_order_number)
    return wynik


def test_aktywne_ida_przed_archiwum_mimo_starej_rangi_spakowanych(app):
    _zamowienie(app, '100', [dict(current_status='spakowane', priority_rank=1,
                                  packaging_completed_at=datetime(2026, 9, 1, 12))])
    _zamowienie(app, '200', [dict(current_status='czeka_na_formatowanie', priority_rank=40)])
    _zamowienie(app, '300', [dict(current_status='czeka_na_wyciecie', priority_rank=None)])

    with app.app_context():
        items, has_more, total = search_orders_global('Kowalski', limit=50)

    assert _numery(items) == ['200', '300', '100']
    assert (has_more, total) == (False, 3)


def test_archiwum_nie_zjada_limitu_przed_aktywnymi(app):
    for n in range(5):
        _zamowienie(app, '10{}'.format(n), [dict(
            current_status='spakowane', priority_rank=1,
            packaging_completed_at=datetime(2026, 9, 1 + n, 12))])
    _zamowienie(app, '900', [dict(current_status='czeka_na_lakiernie', priority_rank=77)])

    with app.app_context():
        items, has_more, total = search_orders_global('Kowalski', limit=2)

    # Aktywne pierwsze, potem najświeżej spakowane; reszta archiwum w has_more.
    assert _numery(items) == ['900', '104']
    assert (has_more, total) == (True, 6)


def test_archiwum_od_najswiezej_spakowanego_a_bez_daty_na_koncu(app):
    _zamowienie(app, '1010', [dict(current_status='spakowane',
                                packaging_completed_at=datetime(2026, 9, 10, 8))])
    _zamowienie(app, '1020', [dict(current_status='spakowane',
                                packaging_completed_at=datetime(2026, 9, 21, 8))])
    _zamowienie(app, '1030', [dict(current_status='spakowane', packaging_completed_at=None)])
    _zamowienie(app, '1040', [dict(current_status='anulowane')])

    with app.app_context():
        items, _more, _total = search_orders_global('Kowalski', limit=50)

    assert _numery(items) == ['1020', '1010', '1030', '1040']


def test_zamowienie_czesciowo_spakowane_jest_aktywne(app):
    """
    Zamówienie z jedną pozycją spakowaną i jedną w produkcji jest w produkcji.
    Jego priorytet liczy się z pozycji aktywnej — stara ranga spakowanej
    (1) nie może go wynieść ponad zamówienie z rangą 5.
    """
    _zamowienie(app, '500', [
        dict(current_status='spakowane', priority_rank=1,
             packaging_completed_at=datetime(2026, 9, 20, 8)),
        dict(current_status='czeka_na_krawedzie', priority_rank=30),
    ])
    _zamowienie(app, '600', [dict(current_status='czeka_na_krawedzie', priority_rank=5)])

    with app.app_context():
        items, _more, _total = search_orders_global('Kowalski', limit=50)

    assert _numery(items) == ['600', '500']
    # Całe zamówienie, łącznie z pozycją spakowaną — apka pokazuje całą grupę.
    assert sorted(it.current_status for it in items
                  if it.order.internal_order_number == '500') == [
        'czeka_na_krawedzie', 'spakowane']


def test_endpoint_oznacza_spakowane_data_i_bez_stanowiska(app):
    _zamowienie(app, '700', [
        dict(current_status='spakowane',
             packaging_completed_at=datetime(2026, 9, 21, 14, 30)),
        dict(current_status='spakowane', packaging_completed_at=None),
    ])
    _zamowienie(app, '800', [dict(current_status='czeka_na_pakowanie',
                                  packaging_completed_at=None)])

    with app.app_context():
        device = ProductionDevice(device_id='TAB-S', device_name='Tablet',
                                  station_code='formatting')
        db.session.add(device)
        db.session.commit()
        token = generate_token(device)

    odp = app.test_client().get(
        '/api/mobile/orders/search?q=Kowalski',
        headers={'Authorization': 'Bearer ' + token, 'X-App-Version': '1.0.0'},
    )

    assert odp.status_code == 200, odp.get_json()
    dane = odp.get_json()
    statusy = [(o['status'], o['packed_at'], o['current_station']) for o in dane['orders']]

    assert len(statusy) == 3
    assert statusy[0] == ('czeka_na_pakowanie', None, 'packaging')
    assert ('spakowane', '2026-09-21T14:30:00', None) in statusy
    assert ('spakowane', None, None) in statusy
