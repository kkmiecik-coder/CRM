# -*- coding: utf-8 -*-
"""Ponowny druk etykiet paczek (logistyka etap 4, krok 4.2, spec 7.3)."""
import itertools

import pytest

from extensions import db
from modules.production.logistics import sposoby as s
from modules.production.logistics.services import paczki
from modules.production.models import LabelPrintJob, ProductionDevice, ProductionPackage
from modules.production.services import print_queue_service as pqs
from modules.production.services.mobile_api_service import generate_token
from tests.logistyka_fixtures import app, client, zamowienie  # noqa: F401

_numery = itertools.count(1600)
_licznik = itertools.count(1)


@pytest.fixture()
def sygnaly(monkeypatch):
    wyslane = []
    monkeypatch.setattr(pqs.realtime_service, 'publish_print_signal',
                        lambda n: wyslane.append(n) or True)
    return wyslane


def _urzadzenie(stanowisko='packaging'):
    device = ProductionDevice(device_id='TAB-druk-%s-%d' % (stanowisko, next(_licznik)),
                              device_name='Tablet', station_code=stanowisko)
    db.session.add(device)
    db.session.commit()
    return device


def _naglowki(device, op_id=None):
    return {'Authorization': 'Bearer ' + generate_token(device),
            'X-Operation-Id': op_id or 'op-druk-%d' % next(_licznik)}


def _zadeklarowane(client, device, liczba, sposob=s.KURIER):
    order = zamowienie(sposob=sposob, statusy=('spakowane',), numer_wewnetrzny=str(next(_numery)))
    r = client.put('/api/mobile/orders/%s/packages' % order.internal_order_number,
                   json={'kind': 'paczka', 'count': liczba}, headers=_naglowki(device))
    assert r.status_code == 200, r.get_json()
    return order


def test_ponowny_druk_paczki_z_biezacymi_danymi(app, client, sygnaly):
    device = _urzadzenie()
    order = _zadeklarowane(client, device, 2, sposob=s.TRANSPORT)
    druga = paczki.aktualne_paczki(order.id)[1]
    assert druga.label_delivery_text == 'TRANSPORT WOODPOWER'
    order.override_delivery_method = s.ODBIOR          # logistyk zmienił sposób po druku
    db.session.commit()
    r = client.post('/api/mobile/packages/%d/print' % druga.id, headers=_naglowki(device))
    assert r.status_code == 200, r.get_json()
    dane = r.get_json()
    assert dane['success'] is True and dane['labels_queued'] == 1
    assert dane['package']['label_print_count'] == 2 and druga.kod in dane['message']
    zadanie = LabelPrintJob.query.order_by(LabelPrintJob.id.desc()).first()
    assert zadanie.package_id == druga.id and zadanie.printer == 'wysylka'
    assert '^FR^FD2 / 2^FS' in zadanie.zpl_payload and '^FR^FDODBIOR OSOBISTY^FS' in zadanie.zpl_payload
    p = ProductionPackage.query.get(druga.id)
    assert (p.label_print_count, p.label_delivery_text) == (2, 'ODBIOR OSOBISTY')
    assert sygnaly == [2, 1]


def test_uniewazniona_paczka_409(app, client, sygnaly):
    """Review Focus 3: stara etykieta po ponownej deklaracji."""
    device = _urzadzenie()
    order = _zadeklarowane(client, device, 2)
    stara = paczki.aktualne_paczki(order.id)[0]
    client.put('/api/mobile/orders/%s/packages' % order.internal_order_number,
               json={'kind': 'paczka', 'count': 1}, headers=_naglowki(device))
    r = client.post('/api/mobile/packages/%d/print' % stara.id, headers=_naglowki(device))
    assert r.status_code == 409 and r.get_json()['error'] == 'package_void'
    assert u'nieaktualna' in r.get_json()['message']
    assert LabelPrintJob.query.filter_by(package_id=stara.id).count() == 1


def test_nieznana_paczka_404(app, client, sygnaly):
    r = client.post('/api/mobile/packages/999999/print', headers=_naglowki(_urzadzenie()))
    assert r.status_code == 404 and r.get_json()['error'] == 'package_not_found'


def test_druk_wszystkich_paczek_zamowienia(app, client, sygnaly):
    device = _urzadzenie()
    order = _zadeklarowane(client, device, 3)
    r = client.post('/api/mobile/orders/%s/packages/print' % order.internal_order_number,
                    headers=_naglowki(device))
    assert r.status_code == 200, r.get_json()
    dane = r.get_json()
    assert dane['labels_queued'] == 3 and [p['seq'] for p in dane['packages']] == [1, 2, 3]
    assert all(p['label_print_count'] == 2 for p in dane['packages'])
    assert LabelPrintJob.query.count() == 6 and sygnaly == [3, 3]


def test_druk_wszystkich_bez_paczek_409(app, client, sygnaly):
    order = zamowienie(sposob=s.KURIER, statusy=('spakowane',), numer_wewnetrzny=str(next(_numery)))
    r = client.post('/api/mobile/orders/%s/packages/print' % order.internal_order_number,
                    headers=_naglowki(_urzadzenie()))
    assert r.status_code == 409 and r.get_json()['error'] == 'no_packages'
    assert r.get_json()['message'] and sygnaly == []


def test_druk_wszystkich_nieznane_zamowienie_404(app, client, sygnaly):
    r = client.post('/api/mobile/orders/999999/packages/print', headers=_naglowki(_urzadzenie()))
    assert r.status_code == 404 and r.get_json()['error'] == 'order_not_found'


def test_ponowny_druk_stanowisko_bez_prawa_403(app, client, sygnaly):
    order = _zadeklarowane(client, _urzadzenie(), 1)
    obcy = _urzadzenie('cutting')
    p = paczki.aktualne_paczki(order.id)[0]
    for url in ('/api/mobile/packages/%d/print' % p.id,
                '/api/mobile/orders/%s/packages/print' % order.internal_order_number):
        r = client.post(url, headers=_naglowki(obcy))
        assert r.status_code == 403 and r.get_json()['error'] == 'station_not_allowed'
    assert LabelPrintJob.query.count() == 1


def test_ponowny_druk_ten_sam_operation_id_drukuje_raz(app, client, sygnaly):
    """Review Focus 1."""
    device = _urzadzenie()
    order = _zadeklarowane(client, device, 1)
    p = paczki.aktualne_paczki(order.id)[0]
    for _ in range(2):
        r = client.post('/api/mobile/packages/%d/print' % p.id, headers=_naglowki(device, op_id='op-raz'))
        assert r.status_code == 200
    assert LabelPrintJob.query.filter_by(package_id=p.id).count() == 2      # deklaracja + jeden przedruk
    assert sygnaly == [1, 1]          # deklaracja + jeden przedruk; powtórka idzie bez sygnału
