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
from tests.logistyka_fixtures import app, client, zamowienie  # noqa: F401


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
                                     'vehicle_name': None, 'repack_required': False}
        assert dane['delivery_type'] == 'courier'  # heurystyka odbioru już nie decyduje
        z = zamowienie(sposob=s.ODBIOR, statusy=('czeka_na_pakowanie',))
        dane = serialize_order(z.products[0], station_code='packaging')
        assert dane['transport']['mode'] == 'odbior'
        assert dane['delivery_type'] == 'personal_pickup'


def test_ksztalt_odpowiedzi_podbity():
    assert mobile_api.KSZTALT_ODPOWIEDZI_KOLEJKI == 3


def test_pakowanie_bez_sposobu_to_409_z_komunikatem(app, client):
    token = _token(app)
    with app.app_context():
        order = zamowienie(statusy=('czeka_na_pakowanie',))
        pid, numer = order.products[0].id, order.internal_order_number
    r = client.post('/api/mobile/orders/%d/complete' % pid,
                    headers={'Authorization': 'Bearer ' + token, 'X-Operation-Id': 'op-1'})
    assert r.status_code == 409
    assert r.get_json()['error'] == 'delivery_method_not_set'
    assert numer in r.get_json()['message']
    with app.app_context():
        assert ProductionProduct.query.get(pid).current_status == 'czeka_na_pakowanie'


def test_to_samo_op_id_przechodzi_po_decyzji_logistyka(app, client):
    """409 nie jest zapamiętywane (BLEDY_DO_PONOWIENIA) — kolejka offline tabletu dośle akcję."""
    token = _token(app)
    naglowki = {'Authorization': 'Bearer ' + token, 'X-Operation-Id': 'op-2'}
    with app.app_context():
        order = zamowienie(statusy=('czeka_na_pakowanie',))
        pid, oid = order.products[0].id, order.id
    assert client.post('/api/mobile/orders/%d/complete' % pid, headers=naglowki).status_code == 409
    with app.app_context():
        from modules.production.models import ProductionOrder
        delivery.ustaw_sposob_dostawy(ProductionOrder.query.get(oid), s.KURIER)
        db.session.commit()
    r = client.post('/api/mobile/orders/%d/complete' % pid, headers=naglowki)
    assert r.status_code == 200
    assert r.get_json()['status'] == 'spakowane'


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
