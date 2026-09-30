# -*- coding: utf-8 -*-
"""Akcje telefonu Weryfikacji: weryfikacja paczki, „Zweryfikuj wszystkie”, „Cofnij weryfikację”
(logistyka etap 4, krok 4.3, spec 4.4, 4.5 i 8.3)."""
import itertools
from datetime import datetime

import pytest

from extensions import db
from modules.production.logistics import sposoby as s
from modules.production.logistics.models import LogisticsLog
from modules.production.models import ProcessedMobileOperation, ProductionDevice, ProductionOrder, ProductionPackage
from modules.production.services.mobile_api_service import generate_token
from tests.logistyka_fixtures import app, client, pracownik, zamowienie  # noqa: F401

BASE = '/api/mobile/verification'
T0 = datetime(2026, 10, 1, 8, 0)
_licznik = itertools.count(1)
_numery = itertools.count(2600)


@pytest.fixture(autouse=True)
def bez_statusow_base(monkeypatch):
    monkeypatch.setattr(
        'modules.production.services.baselinker_status_sync.schedule_after_station_complete',
        lambda *a, **k: None)


def _urzadzenie(stanowisko='verification'):
    device = ProductionDevice(device_id='TEL-%s-%d' % (stanowisko, next(_licznik)),
                              device_name='Telefon', station_code=stanowisko)
    db.session.add(device)
    db.session.commit()
    return device


def _naglowki(device, kto=None, op_id=None, **inne):
    naglowki = {'Authorization': 'Bearer ' + generate_token(device),
                'X-Operation-Id': op_id or 'op-wer-%d' % next(_licznik)}
    if kto is not None:
        naglowki['X-Worker-Ids'] = str(kto.id)
    naglowki.update(inne)
    return naglowki


def _z_paczkami(statusy=('spakowane', 'spakowane'), n=2, sposob=s.KURIER, **kolumny):
    order = zamowienie(sposob=sposob, statusy=statusy, numer_wewnetrzny=str(next(_numery)),
                       packages_declared_at=T0, **kolumny)
    lista = [ProductionPackage(order_id=order.id, seq=i, kind='paczka', declared_at=T0)
             for i in range(1, n + 1)]
    db.session.add_all(lista)
    db.session.commit()
    return order, lista


def _verify(client, paczka, device, kto, **body):
    return client.post('%s/packages/%d/verify' % (BASE, paczka.id), json=body or {'method': 'skan'},
                       headers=_naglowki(device, kto))


def test_ostatnia_paczka_weryfikuje_zamowienie(app, client):
    kto, device = pracownik(), _urzadzenie()
    order, (p1, p2) = _z_paczkami(logistics_closed_at=T0)

    pierwsza = _verify(client, p1, device, kto)
    assert pierwsza.status_code == 200, pierwsza.get_json()
    assert (pierwsza.get_json()['changed'], pierwsza.get_json()['order_verified']) == (True, False)
    assert pierwsza.get_json()['order']['packages_verified'] == 1
    assert [p.current_status for p in ProductionOrder.query.get(order.id).products] == ['spakowane', 'spakowane']

    druga = _verify(client, p2, device, kto).get_json()
    assert (druga['changed'], druga['order_verified']) == (True, True)
    o = ProductionOrder.query.get(order.id)
    assert [p.current_status for p in o.products] == ['zweryfikowane', 'zweryfikowane']
    assert o.verified_by_worker_id == kto.id and o.verified_at is not None
    assert o.logistics_closed_at == T0                        # kurier zostaje zamknięty
    assert [(p.verified_method, p.verified_by_worker_id) for p in ProductionPackage.query.order_by(ProductionPackage.seq)] \
        == [('skan', kto.id), ('skan', kto.id)]
    wpis = LogisticsLog.query.filter_by(order_id=order.id, action='weryfikacja').one()
    assert (wpis.new_value, wpis.note, wpis.worker_id, wpis.device_id) == (u'2 × paczka', 'skan', kto.id, device.id)
    assert druga['order']['stage'] == 'zweryfikowane'


def test_ponowny_skan_bez_zmian(app, client):
    kto, device = pracownik(), _urzadzenie()
    order, (p1,) = _z_paczkami(n=1)
    assert _verify(client, p1, device, kto).get_json()['order_verified'] is True
    ponowny = _verify(client, p1, device, kto)
    assert ponowny.status_code == 200
    assert (ponowny.get_json()['changed'], ponowny.get_json()['order_verified']) == (False, True)
    assert LogisticsLog.query.filter_by(order_id=order.id, action='weryfikacja').count() == 1


@pytest.mark.parametrize('ustaw, kod', [
    (lambda o, p: setattr(p, 'voided_at', T0), 'package_void'),
    (lambda o, p: (setattr(o, 'problem_reason', 'uszkodzenie'), setattr(o, 'problem_at', T0)), 'problem_open'),
    (lambda o, p: setattr(o.products[1], 'current_status', 'czeka_na_pakowanie'), 'order_not_packed'),
    (lambda o, p: [setattr(x, 'current_status', 'dostarczone') for x in o.products], 'order_status'),
])
def test_odmowy_409(app, client, ustaw, kod):
    kto, device = pracownik(), _urzadzenie()
    order, (p1, _p2) = _z_paczkami()
    ustaw(order, p1)
    db.session.commit()
    r = _verify(client, p1, device, kto)
    assert (r.status_code, r.get_json()['error']) == (409, kod)
    assert r.get_json()['message']
    assert ProductionPackage.query.get(p1.id).verified_at is None
    assert ProcessedMobileOperation.query.count() == 0           # 409 niezapamiętane (BLEDY_DO_PONOWIENIA)


def test_bez_pracownika_400_i_bez_zmian(app, client):
    order, (p1, _p2) = _z_paczkami()
    r = client.post('%s/packages/%d/verify' % (BASE, p1.id), json={'method': 'skan'},
                    headers=_naglowki(_urzadzenie()))
    assert (r.status_code, r.get_json()['error']) == (400, 'worker_required')
    assert ProductionPackage.query.get(p1.id).verified_at is None


def test_inne_stanowisko_403_zla_metoda_422_brak_paczki_404(app, client):
    kto = pracownik()
    order, (p1, _p2) = _z_paczkami()
    assert _verify(client, p1, _urzadzenie('packaging'), kto).status_code == 403
    zla = _verify(client, p1, _urzadzenie(), kto, method='laser')
    assert (zla.status_code, zla.get_json()['error']) == (422, 'invalid_method')
    brak = client.post(BASE + '/packages/999999/verify', json={}, headers=_naglowki(_urzadzenie(), kto))
    assert (brak.status_code, brak.get_json()['error']) == (404, 'package_not_found')


def test_powtorka_operacji_nie_weryfikuje_drugi_raz(app, client):
    kto, device = pracownik(), _urzadzenie()
    order, (p1,) = _z_paczkami(n=1)
    naglowki = _naglowki(device, kto, op_id='op-wer-powtorka')
    url = '%s/packages/%d/verify' % (BASE, p1.id)
    pierwsza = client.post(url, json={'method': 'skan'}, headers=naglowki)
    druga = client.post(url, json={'method': 'skan'}, headers=naglowki)
    assert druga.get_json() == pierwsza.get_json()
    assert LogisticsLog.query.filter_by(order_id=order.id, action='weryfikacja').count() == 1


def test_zweryfikuj_wszystkie(app, client):
    kto, device = pracownik(), _urzadzenie()
    order, (p1, p2) = _z_paczkami()
    _verify(client, p1, device, kto)
    url = '%s/orders/%s/verify-all' % (BASE, order.internal_order_number)
    r = client.post(url, headers=_naglowki(device, kto))
    assert r.status_code == 200 and r.get_json()['order_verified'] is True and r.get_json()['changed'] is True
    assert [p.verified_method for p in ProductionPackage.query.order_by(ProductionPackage.seq)] == ['skan', 'reczne']
    assert LogisticsLog.query.filter_by(order_id=order.id, action='weryfikacja').one().note == u'ręcznie'
    ponownie = client.post(url, headers=_naglowki(device, kto))
    assert ponownie.status_code == 200 and ponownie.get_json()['changed'] is False


def test_zweryfikuj_wszystkie_bez_paczek_409(app, client):
    order = zamowienie(sposob=s.KURIER, statusy=('spakowane',), numer_wewnetrzny=str(next(_numery)))
    r = client.post('%s/orders/%s/verify-all' % (BASE, order.internal_order_number),
                    headers=_naglowki(_urzadzenie(), pracownik()))
    assert (r.status_code, r.get_json()['error']) == (409, 'no_packages')


def test_cofnij_weryfikacje(app, client):
    kto, device = pracownik(), _urzadzenie()
    order, (p1, p2) = _z_paczkami()
    client.post('%s/orders/%s/verify-all' % (BASE, order.internal_order_number), headers=_naglowki(device, kto))
    r = client.post('%s/orders/%s/unverify' % (BASE, order.internal_order_number), headers=_naglowki(device, kto))
    assert r.status_code == 200 and r.get_json()['changed'] is True
    o = ProductionOrder.query.get(order.id)
    assert [p.current_status for p in o.products] == ['spakowane', 'spakowane'] and o.verified_at is None
    assert all(p.verified_at is None and p.verified_method is None
               for p in ProductionPackage.query.filter_by(order_id=order.id))
    assert LogisticsLog.query.filter_by(order_id=order.id, action='weryfikacja_cofnieta').one().worker_id == kto.id
    drugi_raz = client.post('%s/orders/%s/unverify' % (BASE, order.internal_order_number),
                            headers=_naglowki(device, kto))
    assert (drugi_raz.status_code, drugi_raz.get_json()['error']) == (409, 'order_not_verified')


def test_telefon_deklaruje_paczki_zamowieniu_bez_paczek(app, client, monkeypatch):
    """Spec 7.2: „BEZ PACZEK” (stara appka, admin) — weryfikator deklaruje paczki tym samym PUT."""
    from modules.production.services import print_queue_service as pqs
    monkeypatch.setattr(pqs.realtime_service, 'publish_print_signal', lambda n: True)
    order = zamowienie(sposob=s.KURIER, statusy=('spakowane',), numer_wewnetrzny=str(next(_numery)))
    r = client.put('/api/mobile/orders/%s/packages' % order.internal_order_number,
                   json={'kind': 'paczka', 'count': 1}, headers=_naglowki(_urzadzenie(), pracownik()))
    assert r.status_code == 200, r.get_json()
    assert ProductionPackage.query.filter_by(order_id=order.id).one().declared_device_id is not None


def test_deklaracja_po_weryfikacji_z_telefonu_409(app, client):
    kto, device = pracownik(), _urzadzenie()
    order, (p1,) = _z_paczkami(n=1)
    _verify(client, p1, device, kto)
    r = client.put('/api/mobile/orders/%s/packages' % order.internal_order_number,
                   json={'kind': 'paczka', 'count': 2}, headers=_naglowki(device, kto))
    assert (r.status_code, r.get_json()['error']) == (409, 'order_verified')
