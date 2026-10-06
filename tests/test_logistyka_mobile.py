# -*- coding: utf-8 -*-
from datetime import datetime

import pytest

from extensions import db
from modules.production.logistics import sposoby as s
from modules.production.logistics.services import delivery
from modules.production.models import ProductionDevice, ProductionProduct
from modules.production.routers import mobile_api
from modules.production.services.mobile_api_service import generate_token, serialize_order
from modules.production.services.label_print_service import _format_delivery_label
from tests.logistyka_fixtures import BASE, app, client, zamowienie  # noqa: F401


@pytest.fixture(autouse=True)
def bez_statusow_base(monkeypatch):
    """Spakowanie odpala synchronizację statusu Base. po commicie — w testach jej nie chcemy
    (ten sam zabieg co tests/test_mobile_complete_bl_sync_queue.py)."""
    monkeypatch.setattr(
        'modules.production.services.baselinker_status_sync.schedule_after_station_complete',
        lambda *a, **k: None)


def _token(app, stanowisko='packaging'):
    with app.app_context():
        device = ProductionDevice(device_id='TAB-%s' % stanowisko,
                                  device_name='Tablet', station_code=stanowisko)
        db.session.add(device)
        db.session.commit()
        return generate_token(device)


def test_serializer_zawsze_ma_obiekt_transport_i_stare_delivery_type(app):
    with app.app_context():
        bez = zamowienie(statusy=('czeka_na_pakowanie',), delivery_method='Odbiór osobisty')
        dane = serialize_order(bez.products[0], station_code='packaging')
        assert dane['transport'] == {'mode': None, 'trip_name': None, 'trip_date': None,
                                     'vehicle_name': None, 'repack_required': False,
                                     'repack_reason': None}
        assert dane['delivery_type'] == 'courier'  # heurystyka odbioru już nie decyduje
        z = zamowienie(sposob=s.ODBIOR, statusy=('czeka_na_pakowanie',))
        dane = serialize_order(z.products[0], station_code='packaging')
        assert dane['transport']['mode'] == 'odbior'
        assert dane['delivery_type'] == 'personal_pickup'


def test_ksztalt_odpowiedzi_podbity():
    assert mobile_api.KSZTALT_ODPOWIEDZI_KOLEJKI == 6   # 6 — priorytet (priorytety produkcji, krok K3)


def test_pakowanie_bez_sposobu_przechodzi(app, client):
    """Krok 4.6 (decyzja Konrada 5.10): dawne 409 delivery_method_not_set zniknęło — ZAKOŃCZ pakuje."""
    token = _token(app)
    with app.app_context():
        order = zamowienie(statusy=('czeka_na_pakowanie',))
        pid = order.products[0].id
    r = client.post('/api/mobile/orders/%d/complete' % pid,
                    headers={'Authorization': 'Bearer ' + token, 'X-Operation-Id': 'op-1'})
    assert r.status_code == 200
    assert r.get_json()['status'] == 'spakowane'
    with app.app_context():
        assert ProductionProduct.query.get(pid).current_status == 'spakowane'


def test_po_nie_ustawiono_z_przepakowaniem_tablet_pakuje_bez_sposobu(app, client):
    """Spec 8.7 + krok 4.6: „Nie ustawiono” z cofnięciem do pakowania zostawia sposób NULL i `repack_required`.
    Tablet pakuje mimo to (bez 409), spakowanie zdejmuje baner, a zamówienie zostaje otwarte w Logistyce."""
    token = _token(app)
    naglowki = {'Authorization': 'Bearer ' + token, 'X-Operation-Id': 'op-4'}
    with app.app_context():
        order = zamowienie(sposob=s.KURIER, statusy=('spakowane',))
        pid, oid = order.products[0].id, order.id
    panel = client.post(BASE + '/orders/delivery-method',
                        json={'order_ids': [oid], 'sposob': s.BRAK, 'przepakowanie': True})
    assert panel.status_code == 200 and panel.get_json()['przepakowanie'] == [oid]
    with app.app_context():
        from modules.production.models import ProductionOrder
        wiersz = ProductionOrder.query.get(oid)
        assert wiersz.override_delivery_method is None and wiersz.repack_required is True
        assert ProductionProduct.query.get(pid).current_status == 'czeka_na_pakowanie'
    r = client.post('/api/mobile/orders/%d/complete' % pid, headers=naglowki)
    assert r.status_code == 200
    assert r.get_json()['status'] == 'spakowane'
    with app.app_context():
        from modules.production.models import ProductionOrder
        wiersz = ProductionOrder.query.get(oid)
        assert wiersz.repack_required is False and wiersz.repack_reason is None
        assert wiersz.logistics_closed_at is None


def test_inne_stanowiska_nie_sa_blokowane(app, client):
    token = _token(app, stanowisko='cutting')
    with app.app_context():
        order = zamowienie(statusy=('czeka_na_wyciecie',))
        pid = order.products[0].id
    r = client.post('/api/mobile/orders/%d/complete' % pid,
                    headers={'Authorization': 'Bearer ' + token, 'X-Operation-Id': 'op-3'})
    assert r.status_code == 200


def test_kolejka_pakowania_zmienia_etag_po_zmianie_sposobu(app, client):
    """Review Focus 4."""
    token = _token(app)
    naglowki = {'Authorization': 'Bearer ' + token}
    with app.app_context():
        order = zamowienie(statusy=('czeka_na_pakowanie',))
        order.products[0].updated_at = datetime(2026, 9, 1)
        db.session.commit()
        oid = order.id
    pierwszy = client.get('/api/mobile/stations/packaging/orders', headers=naglowki)
    etag = pierwszy.headers['ETag']
    with app.app_context():
        from modules.production.models import ProductionOrder
        delivery.ustaw_sposob_dostawy(ProductionOrder.query.get(oid), s.TRANSPORT,
                                      teraz=datetime(2026, 9, 25, 12, 0))
        db.session.commit()
    drugi = client.get('/api/mobile/stations/packaging/orders',
                       headers=dict(naglowki, **{'If-None-Match': etag}))
    assert drugi.status_code == 200


def test_etykieta_druku_ma_ten_sam_tekst_co_tablet(app):
    with app.app_context():
        bez = zamowienie(delivery_method='DPD')
        assert _format_delivery_label(bez.products[0]) == 'Nie ustawiono'
        z = zamowienie(sposob=s.TRANSPORT)
        assert _format_delivery_label(z.products[0]) == 'Transport WoodPower'
