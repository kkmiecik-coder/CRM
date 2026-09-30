# -*- coding: utf-8 -*-
"""Deklaracja paczek z tabletu pakowania (logistyka etap 4, krok 4.2, spec 7.2)."""
import itertools
from datetime import datetime

import pytest
from sqlalchemy import event

from extensions import db
from modules.production.logistics import sposoby as s
from modules.production.logistics.models import LogisticsLog
from modules.production.logistics.services import paczki
from modules.production.models import (LabelPrintJob, ProductionDevice, ProductionOrder,
                                       ProductionPackage, ProductionProduct)
from modules.production.routers import mobile_api
from modules.production.services import print_queue_service as pqs
from modules.production.services.mobile_api_service import generate_token
from tests.logistyka_fixtures import app, client, pracownik, zamowienie  # noqa: F401

_numery = itertools.count(1400)
_licznik = itertools.count(1)


@pytest.fixture(autouse=True)
def bez_statusow_base(monkeypatch):
    """Spakowanie odpala synchronizację statusu Base. po commicie — w testach jej nie chcemy."""
    monkeypatch.setattr(
        'modules.production.services.baselinker_status_sync.schedule_after_station_complete',
        lambda *a, **k: None)


@pytest.fixture()
def sygnaly(monkeypatch):
    wyslane = []
    monkeypatch.setattr(pqs.realtime_service, 'publish_print_signal',
                        lambda n: wyslane.append(n) or True)
    return wyslane


def _urzadzenie(stanowisko='packaging'):
    device = ProductionDevice(device_id='TAB-%s-%d' % (stanowisko, next(_licznik)),
                              device_name='Tablet', station_code=stanowisko)
    db.session.add(device)
    db.session.commit()
    return device


def _naglowki(device, op_id=None, **inne):
    naglowki = {'Authorization': 'Bearer ' + generate_token(device),
                'X-Operation-Id': op_id or 'op-paczki-%d' % next(_licznik)}
    naglowki.update(inne)
    return naglowki


def _spakowane(sposob=s.KURIER, statusy=('spakowane', 'spakowane'), **kolumny):
    return zamowienie(sposob=sposob, statusy=statusy, numer_wewnetrzny=str(next(_numery)), **kolumny)


def _url(order):
    return '/api/mobile/orders/%s/packages' % order.internal_order_number


def _put(client, order, device, dane, **naglowki):
    return client.put(_url(order), json=dane, headers=_naglowki(device, **naglowki))


def test_deklaracja_tworzy_paczki_i_kolejkuje_etykiety(app, client, sygnaly):
    order, device = _spakowane(), _urzadzenie()
    r = _put(client, order, device, {'kind': 'paczka', 'count': 3})
    assert r.status_code == 200, r.get_json()
    dane = r.get_json()
    nowe = ProductionPackage.query.filter_by(order_id=order.id).order_by(ProductionPackage.seq).all()
    assert [(p.seq, p.kind, p.pallet_type, p.voided_at) for p in nowe] == \
        [(1, 'paczka', None, None), (2, 'paczka', None, None), (3, 'paczka', None, None)]
    assert all((p.declared_device_id, p.label_print_count, p.label_delivery_text) == (device.id, 1, 'KURIER')
               for p in nowe)
    assert [p['code'] for p in dane['packages']] == [p.kod for p in nowe]
    assert dane['labels_queued'] == 3 and dane['internal_order_number'] == order.internal_order_number
    assert u'3 × paczka' in dane['message'] and dane['packages_declared_at']
    zadania = LabelPrintJob.query.order_by(LabelPrintJob.id).all()
    assert [(z.printer, z.package_id, z.short_product_id) for z in zadania] == \
        [('wysylka', p.id, p.kod) for p in nowe]
    assert '^FR^FD3 / 3^FS' in zadania[2].zpl_payload
    assert ProductionOrder.query.get(order.id).packages_declared_at is not None
    wpis = LogisticsLog.query.filter_by(order_id=order.id, action='paczki').one()
    assert (wpis.old_value, wpis.new_value, wpis.device_id) == (None, u'3 × paczka', device.id)
    assert sygnaly == [3]


@pytest.mark.parametrize('dane, zapisane, na_etykiecie', [
    ({'kind': 'paleta', 'count': 1, 'pallet_type': 'eur'}, ('paleta', 'eur', 120, 80), 'PALETA EUR 120x80'),
    ({'kind': 'paleta', 'count': 1, 'pallet_type': 'eur', 'length_cm': 100, 'width_cm': 100},
     ('paleta', 'eur', 120, 80), 'PALETA EUR 120x80'),
    ({'kind': 'paleta', 'count': 2, 'pallet_type': 'niestandardowa', 'length_cm': 150, 'width_cm': 100},
     ('paleta', 'niestandardowa', 150, 100), 'PALETA 150x100'),
    ({'kind': 'paczka', 'count': 1, 'pallet_type': 'eur', 'length_cm': 50},
     ('paczka', None, None, None), 'PACZKA'),
])
def test_rodzaje_i_wymiary(app, client, sygnaly, dane, zapisane, na_etykiecie):
    order = _spakowane()
    assert _put(client, order, _urzadzenie(), dane).status_code == 200
    p = paczki.aktualne_paczki(order.id)[0]
    assert (p.kind, p.pallet_type, p.length_cm, p.width_cm) == zapisane
    assert '^FD%s^FS' % na_etykiecie in LabelPrintJob.query.first().zpl_payload


@pytest.mark.parametrize('dane', [
    None, [], {}, {'kind': 'skrzynia', 'count': 1}, {'kind': 'paczka'},
    {'kind': 'paczka', 'count': 0}, {'kind': 'paczka', 'count': 11},
    {'kind': 'paczka', 'count': True}, {'kind': 'paczka', 'count': '2'}, {'kind': 'paczka', 'count': 1.5},
    {'kind': 'paleta', 'count': 1}, {'kind': 'paleta', 'count': 1, 'pallet_type': 'duza'},
    {'kind': 'paleta', 'count': 1, 'pallet_type': 'niestandardowa'},
    {'kind': 'paleta', 'count': 1, 'pallet_type': 'niestandardowa', 'length_cm': 19, 'width_cm': 100},
    {'kind': 'paleta', 'count': 1, 'pallet_type': 'niestandardowa', 'length_cm': 150, 'width_cm': 401},
    {'kind': 'paleta', 'count': 1, 'pallet_type': 'niestandardowa', 'length_cm': '150', 'width_cm': 100},
])
def test_zle_dane_422(app, client, sygnaly, dane):
    order = _spakowane()
    r = _put(client, order, _urzadzenie(), dane)
    assert r.status_code == 422 and r.get_json()['error'] == 'invalid_packages'
    assert r.get_json()['message']
    assert ProductionPackage.query.count() == 0 and LabelPrintJob.query.count() == 0 and sygnaly == []


def test_niespakowane_zamowienie_409_i_ponowienie_po_spakowaniu(app, client, sygnaly):
    """Review Focus 2: kolejka appki nie gwarantuje, że ostatni COMPLETE przeszedł pierwszy."""
    order, device = _spakowane(statusy=('spakowane', 'czeka_na_pakowanie')), _urzadzenie()
    naglowki = _naglowki(device, op_id='op-rata')
    r = client.put(_url(order), json={'kind': 'paczka', 'count': 1}, headers=naglowki)
    assert r.status_code == 409 and r.get_json()['error'] == 'order_not_packed'
    assert order.internal_order_number in r.get_json()['message']
    assert ProductionPackage.query.count() == 0 and LabelPrintJob.query.count() == 0 and sygnaly == []
    for p in order.products:
        p.current_status = 'spakowane'
    db.session.commit()
    r = client.put(_url(order), json={'kind': 'paczka', 'count': 1}, headers=naglowki)
    assert r.status_code == 200 and ProductionPackage.query.count() == 1


def test_anulowana_pozycja_nie_blokuje_deklaracji(app, client, sygnaly):
    order = _spakowane(statusy=('spakowane', 'anulowane'))
    assert _put(client, order, _urzadzenie(), {'kind': 'paczka', 'count': 1}).status_code == 200


def test_zamowienie_calkiem_anulowane_409(app, client, sygnaly):
    r = _put(client, _spakowane(statusy=('anulowane',)), _urzadzenie(), {'kind': 'paczka', 'count': 1})
    assert r.status_code == 409 and r.get_json()['error'] == 'order_not_packed'


def test_ponowna_deklaracja_uniewaznia_poprzednia(app, client, sygnaly):
    order, device = _spakowane(), _urzadzenie()
    assert _put(client, order, device, {'kind': 'paczka', 'count': 2}).status_code == 200
    stare_id = [p.id for p in paczki.aktualne_paczki(order.id)]
    assert _put(client, order, device, {'kind': 'paleta', 'count': 1, 'pallet_type': 'eur'}).status_code == 200
    aktualne = paczki.aktualne_paczki(order.id)
    assert [(p.seq, p.kind) for p in aktualne] == [(1, 'paleta')]
    assert all(ProductionPackage.query.get(i).voided_at is not None for i in stare_id)
    assert LabelPrintJob.query.count() == 3 and sygnaly == [2, 1]
    wpisy = LogisticsLog.query.filter_by(order_id=order.id, action='paczki').order_by(LogisticsLog.id).all()
    assert [(w.old_value, w.new_value) for w in wpisy] == [(None, u'2 × paczka'), (u'2 × paczka', u'1 × EUR')]


def test_ten_sam_operation_id_nie_deklaruje_drugi_raz(app, client, sygnaly):
    """Review Focus 1: powtórka z kolejki offline po timeoucie."""
    order, device = _spakowane(), _urzadzenie()
    pierwsza = _put(client, order, device, {'kind': 'paczka', 'count': 2}, op_id='op-powtorka')
    druga = _put(client, order, device, {'kind': 'paczka', 'count': 2}, op_id='op-powtorka')
    assert druga.status_code == 200 and druga.get_json() == pierwsza.get_json()
    assert ProductionPackage.query.count() == 2 and LabelPrintJob.query.count() == 2 and sygnaly == [2]


@pytest.mark.parametrize('stanowisko', ['cutting', 'edges', 'formatting'])
def test_stanowisko_bez_prawa_do_paczek_403(app, client, sygnaly, stanowisko):
    r = _put(client, _spakowane(), _urzadzenie(stanowisko), {'kind': 'paczka', 'count': 1})
    assert r.status_code == 403 and r.get_json()['error'] == 'station_not_allowed'
    assert ProductionPackage.query.count() == 0


def test_stanowiska_paczek():
    assert paczki.STANOWISKA_PACZEK == ('packaging', 'verification')


def test_nieznane_zamowienie_404(app, client, sygnaly):
    r = client.put('/api/mobile/orders/999999/packages', json={'kind': 'paczka', 'count': 1},
                   headers=_naglowki(_urzadzenie()))
    assert r.status_code == 404 and r.get_json()['error'] == 'order_not_found'


def test_deklaracja_podbija_updated_at_pozycji(app, client, sygnaly):
    order = _spakowane()
    for p in order.products:
        p.updated_at = datetime(2026, 9, 1)
    db.session.commit()
    assert _put(client, order, _urzadzenie(), {'kind': 'paczka', 'count': 1}).status_code == 200
    assert all(ProductionProduct.query.get(p.id).updated_at > datetime(2026, 9, 1) for p in order.products)


def test_pracownik_z_naglowka(app, client, sygnaly, monkeypatch):
    monkeypatch.setattr(mobile_api.worker_service, 'touch_sessions', lambda ids, **k: {})
    kto, order, device = pracownik(), _spakowane(), _urzadzenie()
    r = _put(client, order, device, {'kind': 'paczka', 'count': 1}, **{'X-Worker-Ids': str(kto.id)})
    assert r.status_code == 200
    assert paczki.aktualne_paczki(order.id)[0].declared_by_worker_id == kto.id
    assert LogisticsLog.query.filter_by(order_id=order.id, action='paczki').one().worker_id == kto.id


def test_sygnal_dla_agenta_dopiero_po_commicie(app, client, monkeypatch):
    """Review Focus 4."""
    kolejnosc = []
    monkeypatch.setattr(pqs.realtime_service, 'publish_print_signal',
                        lambda n: kolejnosc.append(('sygnal', n)) or True)

    def _po_commicie(sesja):
        kolejnosc.append('commit')

    order, device = _spakowane(), _urzadzenie()
    event.listen(db.session, 'after_commit', _po_commicie)
    try:
        assert _put(client, order, device, {'kind': 'paczka', 'count': 2}).status_code == 200
    finally:
        event.remove(db.session, 'after_commit', _po_commicie)
    assert kolejnosc[-2:] == ['commit', ('sygnal', 2)]
    assert kolejnosc.count(('sygnal', 2)) == 1


def test_get_zwraca_aktualne_paczki(app, client, sygnaly):
    order, device = _spakowane(), _urzadzenie()
    pusta = client.get(_url(order), headers=_naglowki(device))
    assert pusta.status_code == 200 and 'no-store' in pusta.headers['Cache-Control']
    assert pusta.get_json() == {'internal_order_number': order.internal_order_number,
                                'packages_declared_at': None, 'packages': []}
    _put(client, order, device, {'kind': 'paczka', 'count': 2})
    _put(client, order, device, {'kind': 'paczka', 'count': 1})
    dane = client.get(_url(order), headers=_naglowki(device)).get_json()
    assert [p['seq'] for p in dane['packages']] == [1] and dane['packages_declared_at']
    assert client.get('/api/mobile/orders/999999/packages', headers=_naglowki(device)).status_code == 404


def test_get_z_kazdego_stanowiska(app, client):
    order = _spakowane()
    assert client.get(_url(order), headers=_naglowki(_urzadzenie('cutting'))).status_code == 200


def test_stara_appka_pakuje_bez_deklaracji(app, client, sygnaly):
    """Spec 7.2: backend przyjmuje pakowanie bez deklaracji (stara appka, admin)."""
    order, device = _spakowane(statusy=('czeka_na_pakowanie',)), _urzadzenie()
    r = client.post('/api/mobile/orders/%d/complete' % order.products[0].id, headers=_naglowki(device))
    assert r.status_code == 200 and r.get_json()['status'] == 'spakowane'
    assert paczki.aktualne_paczki(order.id) == [] and LabelPrintJob.query.count() == 0


@pytest.mark.parametrize('argumenty, tekst', [
    (('paczka', 3), u'3 × paczka'),
    (('paleta', 1, 'eur', 120, 80), u'1 × EUR'),
    (('paleta', 2, 'niestandardowa', 150, 100), u'2 × paleta 150×100'),
])
def test_opis_deklaracji(argumenty, tekst):
    assert paczki.opis(*argumenty) == tekst
