# -*- coding: utf-8 -*-
"""Problem przy weryfikacji, „Cofnij do pakowania” i baner repack_reason na tablecie pakowania
(logistyka etap 4, krok 4.3, spec 4.5, 8.3 i 8.4)."""
import itertools
from datetime import date, datetime

import pytest
from flask import g, jsonify

from extensions import db
from modules.production.logistics import sposoby as s
from modules.production.logistics.models import LogisticsLog, Route, RouteStop
from modules.production.logistics.routers import weryfikacja_api
from modules.production.logistics.services import bl_sync, weryfikacja
from modules.production.models import (ProcessedMobileOperation, ProductionDevice, ProductionOrder,
                                       ProductionPackage)
from modules.production.routers import mobile_api
from modules.production.services.mobile_api_service import generate_token
from tests.logistyka_fixtures import app, client, pracownik, zamowienie  # noqa: F401
from tests.weryfikacja_pomocnicze import migawka_pozycji

BASE = '/api/mobile/verification'
T0 = datetime(2026, 10, 1, 8, 0)
_licznik = itertools.count(1)
_numery = itertools.count(3100)


@pytest.fixture(autouse=True)
def bez_statusow_base(monkeypatch):
    monkeypatch.setattr(
        'modules.production.services.baselinker_status_sync.schedule_after_station_complete',
        lambda *a, **k: None)


@pytest.fixture()
def dopychacz(app, monkeypatch):
    wolania = []
    monkeypatch.setattr(bl_sync, 'uruchom_w_tle', lambda app: wolania.append('start') or True)
    # `g` jest w testach wspólny dla żądań (testowy klient wchodzi w app_context fixtury) — lista
    # „do wysłania po commicie” nie może przeciekać między testami ani między żądaniami.
    g.pop('_logistyka_bl_po_commicie', None)
    yield wolania
    g.pop('_logistyka_bl_po_commicie', None)


def _urzadzenie(stanowisko='verification'):
    device = ProductionDevice(device_id='TEL-%s-%d' % (stanowisko, next(_licznik)),
                              device_name='Telefon', station_code=stanowisko)
    db.session.add(device)
    db.session.commit()
    return device


def _naglowki(device, kto=None, op_id=None):
    naglowki = {'Authorization': 'Bearer ' + generate_token(device),
                'X-Operation-Id': op_id or 'op-prob-%d' % next(_licznik)}
    if kto is not None:
        naglowki['X-Worker-Ids'] = str(kto.id)
    return naglowki


def _z_paczkami(statusy=('spakowane', 'spakowane'), n=2, sposob=s.KURIER, zweryfikowane=False, **kolumny):
    order = zamowienie(sposob=sposob, statusy=statusy, numer_wewnetrzny=str(next(_numery)),
                       packages_declared_at=T0, **kolumny)
    for p in order.products:
        p.packaging_completed_at = T0
    db.session.add_all([ProductionPackage(order_id=order.id, seq=i, kind='paczka', declared_at=T0,
                                          verified_at=T0 if zweryfikowane else None,
                                          verified_method='skan' if zweryfikowane else None)
                        for i in range(1, n + 1)])
    db.session.commit()
    return order


def _post(client, order, akcja, device, kto, **body):
    return client.post('%s/orders/%s/%s' % (BASE, order.internal_order_number, akcja), json=body,
                       headers=_naglowki(device, kto))


def _akcje(order):
    return [w.action for w in LogisticsLog.query.filter_by(order_id=order.id).order_by(LogisticsLog.id)]


def test_problem_na_spakowanym(app, client):
    kto, device = pracownik(), _urzadzenie()
    order = _z_paczkami()
    r = _post(client, order, 'problem', device, kto, reason='brak_elementu', note=u'  brak   nóżki ')
    assert r.status_code == 200, r.get_json()
    o = ProductionOrder.query.get(order.id)
    assert (o.problem_reason, o.problem_note, o.problem_by_worker_id) == ('brak_elementu', u'brak nóżki', kto.id)
    assert r.get_json()['order']['problem']['reason_label'] == u'Brak elementu'
    assert _akcje(order) == ['problem']


def test_problem_na_zweryfikowanym_cofa_weryfikacje(app, client):
    kto, device = pracownik(), _urzadzenie()
    order = _z_paczkami(statusy=('zweryfikowane', 'zweryfikowane'), zweryfikowane=True, verified_at=T0)
    assert _post(client, order, 'problem', device, kto, reason='uszkodzenie').status_code == 200
    o = ProductionOrder.query.get(order.id)
    assert [p.current_status for p in o.products] == ['spakowane', 'spakowane'] and o.verified_at is None
    assert all(p.verified_at is None for p in ProductionPackage.query.filter_by(order_id=order.id))
    assert _akcje(order) == ['weryfikacja_cofnieta', 'problem']
    assert LogisticsLog.query.filter_by(order_id=order.id, action='weryfikacja_cofnieta').one().note == \
        u'problem: Uszkodzenie'


def test_ponowny_problem_nadpisuje(app, client):
    kto, device = pracownik(), _urzadzenie()
    order = _z_paczkami()
    _post(client, order, 'problem', device, kto, reason='etykieta')
    _post(client, order, 'problem', device, kto, reason='opakowanie', note='x' * 300)
    o = ProductionOrder.query.get(order.id)
    assert o.problem_reason == 'opakowanie' and len(o.problem_note) == 255
    wpis = LogisticsLog.query.filter_by(order_id=order.id, action='problem').order_by(LogisticsLog.id.desc()).first()
    assert (wpis.old_value, wpis.new_value) == ('etykieta', 'opakowanie')


def test_zly_powod_422_zapamietany(app, client):
    r = _post(client, _z_paczkami(), 'problem', _urzadzenie(), pracownik(), reason='pogoda')
    assert (r.status_code, r.get_json()['error']) == (422, 'invalid_problem')
    assert ProcessedMobileOperation.query.count() == 1


@pytest.mark.parametrize('akcja', ['problem', 'revert-to-packing'])
def test_powod_innego_typu_niz_tekst_to_422_a_nie_500(app, client, akcja, dopychacz):
    """Lista w `reason` nie jest hashowalna (TypeError → 500 → telefon ponawia bez końca); ciało
    JSON niebędące obiektem też nie może wywalić endpointu."""
    kto, device = pracownik(), _urzadzenie()
    order = _z_paczkami()
    r = _post(client, order, akcja, device, kto, reason=['brak_elementu'])
    assert (r.status_code, r.get_json()['error']) == (422, 'invalid_problem')
    r = client.post('%s/orders/%s/%s' % (BASE, order.internal_order_number, akcja), json=['x'],
                    headers=_naglowki(device, kto))
    assert (r.status_code, r.get_json()['error']) == (422, 'invalid_problem')
    assert ProductionOrder.query.get(order.id).problem_at is None and dopychacz == []


@pytest.mark.parametrize('statusy, kod', [(('dostarczone',), 'order_status'),
                                          (('spakowane', 'czeka_na_pakowanie'), 'order_not_packed')])
def test_problem_odmowy(app, client, statusy, kod):
    r = _post(client, _z_paczkami(statusy=statusy), 'problem', _urzadzenie(), pracownik(), reason='inne')
    assert (r.status_code, r.get_json()['error']) == (409, kod)
    assert ProcessedMobileOperation.query.count() == 0           # 409 niezapamiętane (BLEDY_DO_PONOWIENIA)


def test_rozwiazanie_problemu(app, client):
    kto, device = pracownik(), _urzadzenie()
    order = _z_paczkami(problem_reason='etykieta', problem_at=T0)
    r = _post(client, order, 'problem/resolve', device, kto)
    assert r.status_code == 200 and r.get_json()['changed'] is True
    o = ProductionOrder.query.get(order.id)
    assert (o.problem_reason, o.problem_note, o.problem_at, o.problem_by_worker_id) == (None, None, None, None)
    wpis = LogisticsLog.query.filter_by(order_id=order.id, action='problem_rozwiazany').one()
    assert (wpis.old_value, wpis.worker_id) == ('etykieta', kto.id)
    bez = _post(client, order, 'problem/resolve', device, kto)
    assert bez.status_code == 200 and bez.get_json()['changed'] is False


def test_cofniecie_do_pakowania(app, client, dopychacz):
    kto, device = pracownik(), _urzadzenie()
    order = _z_paczkami(statusy=('zweryfikowane', 'zweryfikowane'), zweryfikowane=True, verified_at=T0,
                        logistics_closed_at=T0)
    r = _post(client, order, 'revert-to-packing', device, kto, reason='brak_elementu', note=u'brak nóżki')
    assert r.status_code == 200, r.get_json()
    o = ProductionOrder.query.get(order.id)
    assert [(p.current_status, p.quantity_done_packaging, p.packaging_completed_at) for p in o.products] == \
        [('czeka_na_pakowanie', 0, None), ('czeka_na_pakowanie', 0, None)]
    assert (o.repack_required, o.repack_reason) == (True, u'Weryfikacja: Brak elementu: brak nóżki')
    assert (o.verified_at, o.packages_declared_at, o.logistics_closed_at) == (None, None, None)
    assert o.bl_status_pending_id == s.STATUS_PRODUKCJA_ZAKONCZONA
    assert all(p.voided_at is not None for p in ProductionPackage.query.filter_by(order_id=order.id))
    assert 'cofniete_do_pakowania' in _akcje(order)
    assert dopychacz == ['start']                         # dopychacz Base. dopiero po commicie


def test_cofniecie_przenosi_problem_do_banera(app, client, dopychacz):
    kto, device = pracownik(), _urzadzenie()
    order = _z_paczkami(problem_reason='uszkodzenie', problem_note=u'pęknięty blat', problem_at=T0)
    assert _post(client, order, 'revert-to-packing', device, kto).status_code == 200
    o = ProductionOrder.query.get(order.id)
    assert o.repack_reason == u'Weryfikacja: Uszkodzenie: pęknięty blat' and o.problem_at is None
    assert LogisticsLog.query.filter_by(order_id=order.id, action='problem_rozwiazany').one().note == \
        u'przeniesiony do banera pakowania'


def test_cofniecie_bez_powodu_i_bez_problemu_422(app, client, dopychacz):
    r = _post(client, _z_paczkami(), 'revert-to-packing', _urzadzenie(), pracownik())
    assert (r.status_code, r.get_json()['error']) == (422, 'invalid_problem')
    assert dopychacz == []


def test_zamowienie_na_trasie_zostaje_na_niej(app, client, dopychacz):
    order = _z_paczkami(sposob=s.TRANSPORT)
    trasa = Route(name=u'Rzeszów', date_from=date(2026, 10, 7), date_to=date(2026, 10, 7), status='zatwierdzona')
    db.session.add(trasa)
    db.session.flush()
    db.session.add(RouteStop(route_id=trasa.id, order_id=order.id, position=1))
    db.session.commit()
    assert _post(client, order, 'revert-to-packing', _urzadzenie(), pracownik(), reason='inne').status_code == 200
    assert RouteStop.query.filter_by(order_id=order.id).one().route_id == trasa.id


def test_baner_na_tablecie_i_ponowne_spakowanie(app, client, dopychacz):
    order = _z_paczkami()
    _post(client, order, 'revert-to-packing', _urzadzenie(), pracownik(), reason='opakowanie')
    tablet = _urzadzenie('packaging')
    r = client.get('/api/mobile/stations/packaging/orders', headers={'Authorization': 'Bearer ' + generate_token(tablet)})
    transport = r.get_json()['orders'][0]['transport']
    assert (transport['repack_required'], transport['repack_reason']) == (True, u'Weryfikacja: Opakowanie')
    assert mobile_api.KSZTALT_ODPOWIEDZI_KOLEJKI == 5
    o = ProductionOrder.query.get(order.id)
    for p in o.products:
        p.complete_task('packaging')
    db.session.commit()
    o = ProductionOrder.query.get(order.id)
    assert (o.repack_required, o.repack_reason) == (False, None)
    assert [p.current_status for p in o.products] == ['spakowane', 'spakowane']


def test_problem_na_zamowieniu_z_czescia_sprawdzonych_paczek(app, client):
    """Zamówienie jeszcze 'spakowane', ale jedna paczka już sprawdzona — problem czyści znacznik."""
    kto, device = pracownik(), _urzadzenie()
    order = _z_paczkami()
    ProductionPackage.query.filter_by(order_id=order.id, seq=1).one().verified_at = T0
    db.session.commit()
    assert _post(client, order, 'problem', device, kto, reason='etykieta').status_code == 200
    assert all(p.verified_at is None and p.verified_by_worker_id is None and p.verified_method is None
               for p in ProductionPackage.query.filter_by(order_id=order.id))
    assert _akcje(order) == ['weryfikacja_cofnieta', 'problem']


def test_cofniecie_do_pakowania_przenosi_notatke_problemu_przy_podanym_powodzie(app, client, dopychacz):
    """M1: żądanie ma `reason`, ale nie `note` — notatka otwartego problemu też trafia do banera."""
    order = _z_paczkami(problem_reason='uszkodzenie', problem_note=u'pęknięty blat', problem_at=T0)
    r = _post(client, order, 'revert-to-packing', _urzadzenie(), pracownik(), reason='brak_elementu')
    assert r.status_code == 200, r.get_json()
    o = ProductionOrder.query.get(order.id)
    assert o.repack_reason == u'Weryfikacja: Brak elementu: pęknięty blat' and o.problem_at is None
    # notatka z żądania wygrywa z notatką problemu
    drugie = _z_paczkami(problem_reason='uszkodzenie', problem_note=u'pęknięty blat', problem_at=T0)
    _post(client, drugie, 'revert-to-packing', _urzadzenie(), pracownik(), reason='inne', note=u'do wymiany')
    assert ProductionOrder.query.get(drugie.id).repack_reason == u'Weryfikacja: Inne: do wymiany'


def test_cofniecie_409_nie_uruchamia_dopychacza_i_nie_jest_zapamietane(app, client, dopychacz):
    order = _z_paczkami(statusy=('spakowane', 'czeka_na_pakowanie'))
    r = _post(client, order, 'revert-to-packing', _urzadzenie(), pracownik(), reason='inne')
    assert (r.status_code, r.get_json()['error']) == (409, 'order_not_packed')
    assert dopychacz == [] and not g.get('_logistyka_bl_po_commicie')
    assert ProcessedMobileOperation.query.count() == 0


def test_powtorka_cofniecia_nie_uruchamia_dopychacza_drugi_raz(app, client, dopychacz):
    kto, device = pracownik(), _urzadzenie()
    order = _z_paczkami()
    naglowki = _naglowki(device, kto, op_id='op-prob-powtorka')
    url = '%s/orders/%s/revert-to-packing' % (BASE, order.internal_order_number)
    pierwsze = client.post(url, json={'reason': 'inne'}, headers=naglowki)
    assert pierwsze.status_code == 200 and dopychacz == ['start']
    druga = client.post(url, json={'reason': 'inne'}, headers=naglowki)
    assert druga.get_json() == pierwsze.get_json()
    assert dopychacz == ['start']                               # powtórka idempotentna nie startuje drugi raz
    assert LogisticsLog.query.filter_by(order_id=order.id, action='cofniete_do_pakowania').count() == 1


def test_rollback_po_zaplanowaniu_nie_uruchamia_dopychacza(app, client, dopychacz, monkeypatch):
    """Handler zdążył zaplanować dopychacz, ale odpowiedź jest 409 (rollback) — nic nie startuje."""
    monkeypatch.setattr(weryfikacja_api, '_odpowiedz',
                        lambda *a, **k: (jsonify({'error': 'test', 'message': 'x'}), 409))
    order = _z_paczkami()
    r = _post(client, order, 'revert-to-packing', _urzadzenie(), pracownik(), reason='inne')
    assert r.status_code == 409
    assert dopychacz == []
    assert not ProductionOrder.query.get(order.id).repack_required      # zapis cofnięty


# --- Zapisy decydują na bieżącym stanie pozycji (migawka MySQL odtworzona przelotką) ---------------

def test_problem_po_cichym_przepakowaniu_to_409(app, client, monkeypatch):
    order = _z_paczkami()
    migawka_pozycji(monkeypatch, weryfikacja, 'zglos_problem', w_pamieci='spakowane', w_bazie='czeka_na_pakowanie')
    r = _post(client, order, 'problem', _urzadzenie(), pracownik(), reason='inne')
    assert (r.status_code, r.get_json()['error']) == (409, 'order_not_packed')


def test_problem_cofa_weryfikacje_na_biezacych_statusach(app, client, monkeypatch):
    """Pozycje w pamięci 'spakowane', w bazie już 'zweryfikowane': decyzja o cofnięciu i przestawienie
    pozycji idą na bieżącym stanie — inaczej weryfikacja zamówienia znika, a pozycje zostają zweryfikowane."""
    kto, device = pracownik(), _urzadzenie()
    order = _z_paczkami(statusy=('zweryfikowane', 'zweryfikowane'), zweryfikowane=True, verified_at=T0)
    migawka_pozycji(monkeypatch, weryfikacja, 'zglos_problem', w_pamieci='spakowane')
    assert _post(client, order, 'problem', device, kto, reason='uszkodzenie').status_code == 200
    o = ProductionOrder.query.get(order.id)
    assert [p.current_status for p in o.products] == ['spakowane', 'spakowane'] and o.verified_at is None
    assert _akcje(order) == ['weryfikacja_cofnieta', 'problem']


def test_cofniecie_do_pakowania_po_cichym_wydaniu_to_409(app, client, dopychacz, monkeypatch):
    order = _z_paczkami(statusy=('zweryfikowane', 'zweryfikowane'), zweryfikowane=True, verified_at=T0)
    migawka_pozycji(monkeypatch, weryfikacja, 'cofnij_do_pakowania',
                    w_pamieci='zweryfikowane', w_bazie='dostarczone')
    r = _post(client, order, 'revert-to-packing', _urzadzenie(), pracownik(), reason='inne')
    assert (r.status_code, r.get_json()['error']) == (409, 'order_status')
    assert dopychacz == []


def test_cofniecie_do_pakowania_przestawia_pozycje_z_biezacego_stanu(app, client, dopychacz, monkeypatch):
    """Pozycje przestawione 'w tle' z 'zweryfikowane' na 'spakowane' też wracają do czeka_na_pakowanie,
    a licznik pakowania zeruje się od bieżącej wartości."""
    order = _z_paczkami(statusy=('zweryfikowane', 'zweryfikowane'), zweryfikowane=True, verified_at=T0)
    for p in order.products:
        p.quantity_done_packaging = p.quantity
    db.session.commit()
    migawka_pozycji(monkeypatch, weryfikacja, 'cofnij_do_pakowania', w_pamieci='zweryfikowane', w_bazie='spakowane')
    assert _post(client, order, 'revert-to-packing', _urzadzenie(), pracownik(), reason='inne').status_code == 200
    o = ProductionOrder.query.get(order.id)
    assert [(p.current_status, p.quantity_done_packaging) for p in o.products] == \
        [('czeka_na_pakowanie', 0), ('czeka_na_pakowanie', 0)]
