# -*- coding: utf-8 -*-
"""API telefonu kierowcy (logistyka etap 4, krok 4.4, spec 9): bramka stanowiska i kierowcy, „Moje trasy”, trasa
z ETagiem, załadunek, „Zostaje”, zakończenie załadunku, wyjazd, dostarczenia i cofnięcie — kontrakt z planu 4.4b."""
import gc
from datetime import timedelta

from sqlalchemy import text

from extensions import db
from modules.production.logistics import sposoby
from modules.production.logistics.models import LogisticsLog, OrderGeo, RouteStop
from modules.production.logistics.services import bl_sync, dostawa, dostawa_widok, routes
from modules.production.logistics.services.delivery import LogistykaBlad
from modules.production.models import ProcessedMobileOperation, ProductionDevice
from tests.blokady_pomocnicze import Zapytania
from tests.dostawa_pomocnicze import (T0, naglowki, odsmiecaj_po_blokadach, telefon_kierowcy, trasa,
                                      zaladuj_wprost, zamowienie_z_paczkami, zwykle_odczyty_stanu)
from tests.logistyka_fixtures import DZIS_TESTOW, app, client, kierowca, pracownik  # noqa: F401

API = '/api/mobile/delivery'


def _trasa_kierowcy(k, zamowienia, **kolumny):
    kolumny.setdefault('od', DZIS_TESTOW)
    return trasa(zamowienia, kierowca_id=k.id, **kolumny)


# --- Bramka -------------------------------------------------------------------------------------------

def test_api_wymaga_stanowiska_dostawy(app, client):
    _device, k = telefon_kierowcy()
    obcy = ProductionDevice(device_id='TEL-WERYF', device_name='Telefon biura', station_code='verification')
    db.session.add(obcy)
    db.session.commit()
    r = client.get(API + '/routes', headers=naglowki(obcy, k))
    assert r.status_code == 403 and r.get_json()['error'] == 'station_not_allowed'


def test_api_wymaga_kierowcy(app, client):
    device, _k = telefon_kierowcy()
    r = client.get(API + '/routes', headers=naglowki(device))
    assert r.status_code == 400 and r.get_json()['error'] == 'worker_required'
    r = client.get(API + '/routes', headers=naglowki(device, pracownik()))
    assert r.status_code == 403 and r.get_json()['error'] == 'not_a_driver'
    obcy = dict(naglowki(device), **{'X-Worker-Ids': '987654'})
    r = client.get(API + '/routes', headers=obcy)
    assert r.status_code == 404 and r.get_json()['error'] == 'worker_not_found'


# --- Odczyty -------------------------------------------------------------------------------------------

def test_moje_trasy_zakres(app, client):
    """Review Focus 3: zatwierdzone od dziś, a załadowane i w drodze bez względu na datę — rozpoczęta trasa nie
    znika z telefonu o północy. Robocze, wykonane i cudze — nie."""
    device, k = telefon_kierowcy()
    wczoraj = DZIS_TESTOW - timedelta(days=1)
    dzisiejsza = _trasa_kierowcy(k, [zamowienie_z_paczkami()[0]], nazwa=u'Dziś')
    jutrzejsza = _trasa_kierowcy(k, [zamowienie_z_paczkami()[0]], nazwa=u'Jutro', od=DZIS_TESTOW + timedelta(days=1))
    _trasa_kierowcy(k, [zamowienie_z_paczkami()[0]], nazwa=u'Wczorajsza', od=wczoraj)
    zaladowana = _trasa_kierowcy(k, [zamowienie_z_paczkami(statusy=('zaladowane',))[0]], nazwa=u'Stoi',
                                 status='zaladowana', od=wczoraj)
    w_trasie = _trasa_kierowcy(k, [zamowienie_z_paczkami(statusy=('zaladowane',))[0]], nazwa=u'Jedzie',
                               status='w_trasie', od=wczoraj - timedelta(days=1))
    _trasa_kierowcy(k, [zamowienie_z_paczkami()[0]], nazwa=u'Robocza', status='robocza')
    _trasa_kierowcy(k, [zamowienie_z_paczkami(statusy=('dostarczone',))[0]], nazwa=u'Wykonana', status='wykonana')
    trasa([zamowienie_z_paczkami()[0]], kierowca_id=kierowca().id, nazwa=u'Cudza', od=DZIS_TESTOW)
    r = client.get(API + '/routes', headers=naglowki(device, k))
    assert r.status_code == 200, r.get_data()[:300]
    assert r.headers['Cache-Control'] == 'no-store'
    dane = r.get_json()
    assert [t['id'] for t in dane['routes']] == [w_trasie.id, zaladowana.id, dzisiejsza.id, jutrzejsza.id]
    assert dane['count'] == 4
    pierwsza = dane['routes'][0]
    assert (pierwsza['status'], pierwsza['status_label']) == ('w_trasie', u'W trasie')
    assert set(pierwsza) == {'id', 'name', 'date_from', 'date_to', 'status', 'status_label', 'vehicle_name',
                             'stops_total', 'stops_delivered', 'packages_total', 'packages_loaded'}


def test_trasa_ksztalt_i_stany(app, client):
    device, k = telefon_kierowcy()
    gotowe, (g1, g2) = zamowienie_z_paczkami(delivery_fullname=u'Anna Nowak', client_phone='600100200',
                                             order_notes=u'Brama od podwórza')
    niezweryfikowane, _ = zamowienie_z_paczkami(statusy=('spakowane',), zweryfikowane=False,
                                                delivery_company=u'Stolarnia Sp. z o.o.')
    problem, _ = zamowienie_z_paczkami(problem_at=T0, problem_reason='uszkodzenie', problem_note=u'pęknięta')
    niespakowane, _ = zamowienie_z_paczkami(statusy=('zweryfikowane', 'czeka_na_lakiernie'))
    anulowane, _ = zamowienie_z_paczkami(statusy=('anulowane',))
    t = _trasa_kierowcy(k, [gotowe, niezweryfikowane, problem, niespakowane, anulowane], nazwa=u'Rzeszów 02.10')
    zaladuj_wprost([g1], t, kto_id=k.id)
    db.session.add(OrderGeo(order_id=gotowe.id, lat=50.04, lng=22.0, source='gugik', quality='dokladna',
                            address_hash='x' * 40))
    db.session.add(OrderGeo(order_id=niezweryfikowane.id, lat=50.0, lng=21.9, source='nominatim',
                            quality='przyblizona', address_hash='y' * 40))
    dostawa.ustaw_zostaje(t, niespakowane.id, 'niespakowane')
    db.session.commit()
    r = client.get(API + '/routes/%d' % t.id, headers=naglowki(device, k))
    assert r.status_code == 200, r.get_data()[:300]
    trasa_ = r.get_json()['route']
    assert (trasa_['name'], trasa_['status_label'], trasa_['stops_total'], trasa_['packages_loaded']) == \
        (u'Rzeszów 02.10', u'Zatwierdzona', 4, 1)
    assert trasa_['completed_by_panel'] is False
    stopy = {s['order_id']: s for s in trasa_['stops']}
    s = stopy[gotowe.id]
    assert (s['position'], s['recipient'], s['phone'], s['order_notes']) == \
        (1, u'Anna Nowak', '600100200', u'Brama od podwórza')
    assert s['geo'] == {'lat': 50.04, 'lng': 22.0}
    assert (s['state'], s['state_label'], s['packages_total'], s['packages_loaded']) == \
        ('zweryfikowane', u'Zweryfikowane', 2, 1)
    assert [p['code'] for p in s['packages']] == ['P-%d' % g1.id, 'P-%d' % g2.id]
    assert [p['loaded'] for p in s['packages']] == [True, False]
    assert set(s['address']) == {'street', 'postcode', 'city', 'country_code'}
    assert stopy[niezweryfikowane.id]['geo'] is None                      # tylko punkt dokładny
    assert stopy[niezweryfikowane.id]['recipient'] == u'Stolarnia Sp. z o.o.'
    assert (stopy[niezweryfikowane.id]['state'], stopy[niezweryfikowane.id]['state_label']) == \
        ('niezweryfikowane', u'NIEZWERYFIKOWANE')
    assert stopy[problem.id]['state'] == 'problem' and stopy[problem.id]['state_label'].startswith(u'PROBLEM: ')
    assert stopy[problem.id]['problem']['reason'] == 'uszkodzenie'
    assert (stopy[niespakowane.id]['state'], stopy[niespakowane.id]['state_label']) == \
        ('niespakowane', u'NIESPAKOWANE')
    assert stopy[niespakowane.id]['stays'] == {'reason': 'niespakowane', 'reason_label': u'Niespakowane',
                                               'note': None}
    assert (stopy[anulowane.id]['position'], stopy[anulowane.id]['state']) == (None, 'anulowane')


def test_trasa_etag_i_304(app, client):
    device, k = telefon_kierowcy()
    order, (p1, _p2) = zamowienie_z_paczkami()
    t = _trasa_kierowcy(k, [order])
    r = client.get(API + '/routes/%d' % t.id, headers=naglowki(device, k))
    etag = r.headers['ETag']
    assert etag.startswith('W/"dostawa:1:%d:' % t.id)
    assert r.headers['Cache-Control'] == 'private, max-age=0'
    r = client.get(API + '/routes/%d' % t.id, headers=dict(naglowki(device, k), **{'If-None-Match': etag}))
    assert r.status_code == 304
    assert client.post(API + '/routes/%d/packages/%d/load' % (t.id, p1.id), headers=naglowki(device, k),
                       json={'method': 'skan'}).status_code == 200
    r = client.get(API + '/routes/%d' % t.id, headers=dict(naglowki(device, k), **{'If-None-Match': etag}))
    assert r.status_code == 200 and r.headers['ETag'] != etag


def test_trasa_robocza_i_nieznana_404(app, client):
    device, k = telefon_kierowcy()
    robocza = _trasa_kierowcy(k, [zamowienie_z_paczkami()[0]], status='robocza')
    for rid in (robocza.id, 987654):
        r = client.get(API + '/routes/%d' % rid, headers=naglowki(device, k))
        assert r.status_code == 404 and r.get_json()['error'] == 'route_not_found'


# --- Zapisy ------------------------------------------------------------------------------------------------

def test_zaladunek_przez_api_i_idempotencja(app, client):
    device, k = telefon_kierowcy()
    order, (p1, _p2) = zamowienie_z_paczkami()
    t = _trasa_kierowcy(k, [order])
    adres = API + '/routes/%d/packages/%d/load' % (t.id, p1.id)
    h = naglowki(device, k, op_id='op-load-1')
    r = client.post(adres, headers=h, json={'method': 'skan'})
    assert r.status_code == 200, r.get_data()[:300]
    dane = r.get_json()
    assert (dane['changed'], dane['package']['code'], dane['package']['loaded']) == (True, 'P-%d' % p1.id, True)
    assert dane['route']['stops'][0]['packages_loaded'] == 1 and dane['message']
    assert client.post(adres, headers=h, json={'method': 'skan'}).get_json() == dane      # powtórka op_id
    r = client.post(adres, headers=naglowki(device, k), json={})                         # nowy op_id
    assert r.status_code == 200 and r.get_json()['changed'] is False


def test_odmowy_409_nie_sa_zapamietywane_a_422_tak(app, client):
    device, k = telefon_kierowcy()
    order, (p1,) = zamowienie_z_paczkami(statusy=('spakowane',), paczek=1, zweryfikowane=False)
    t = _trasa_kierowcy(k, [order])
    adres = API + '/routes/%d/packages/%d/load' % (t.id, p1.id)
    h = naglowki(device, k, op_id='op-load-409')
    r = client.post(adres, headers=h, json={})
    assert r.status_code == 409 and r.get_json()['error'] == 'order_not_verified'
    for p in order.products:
        p.current_status = 'zweryfikowane'
    db.session.commit()
    assert client.post(adres, headers=h, json={}).status_code == 200      # to samo X-Operation-Id przechodzi
    h422 = naglowki(device, k, op_id='op-load-422')
    assert client.post(adres, headers=h422, json={'method': 'palcem'}).status_code == 422
    r = client.post(adres, headers=h422, json={'method': 'skan'})
    assert r.status_code == 422 and r.get_json()['error'] == 'invalid_method'   # odtworzone z idempotencji


def test_paczka_z_innej_trasy_ma_nazwe_trasy(app, client):
    device, k = telefon_kierowcy()
    t = _trasa_kierowcy(k, [zamowienie_z_paczkami()[0]])
    inne, (q1, _q2) = zamowienie_z_paczkami()
    trasa([inne], nazwa=u'Lublin 03.10')
    r = client.post(API + '/routes/%d/packages/%d/load' % (t.id, q1.id), headers=naglowki(device, k), json={})
    dane = r.get_json()
    assert r.status_code == 409 and (dane['error'], dane['route_name']) == ('package_not_on_route', u'Lublin 03.10')


def test_zostaje_zakonczenie_i_wyjazd_przez_api(app, client, monkeypatch):
    wywolania = []
    monkeypatch.setattr(bl_sync, 'po_zmianie', lambda ids: wywolania.append(sorted(ids)))
    device, k = telefon_kierowcy()
    jedzie, (j1, j2) = zamowienie_z_paczkami()
    zostaje, _ = zamowienie_z_paczkami()
    t = _trasa_kierowcy(k, [jedzie, zostaje])
    rid = t.id
    r = client.post(API + '/routes/%d/packages/%d/load' % (rid, j1.id), headers=naglowki(device, k), json={})
    assert r.status_code == 200
    r = client.post(API + '/routes/%d/finish-loading' % rid, headers=naglowki(device, k))
    dane = r.get_json()
    assert r.status_code == 409 and dane['error'] == 'loading_incomplete'
    assert [b['reason'] for b in dane['braki']] == ['niezaladowane', 'niezaladowane']
    r = client.post(API + '/routes/%d/stops/%d/stays' % (rid, zostaje.id), headers=naglowki(device, k),
                    json={'reason': 'brak_miejsca', 'note': u'za długie'})
    assert r.status_code == 200 and r.get_json()['changed'] is True
    assert client.post(API + '/routes/%d/stops/%d/stays' % (rid, zostaje.id), headers=naglowki(device, k),
                       json={'reason': 'zle'}).status_code == 422
    client.post(API + '/routes/%d/packages/%d/load' % (rid, j2.id), headers=naglowki(device, k), json={})
    r = client.post(API + '/routes/%d/finish-loading' % rid, headers=naglowki(device, k))
    assert r.status_code == 200, r.get_data()[:300]
    dane = r.get_json()
    assert dane['route']['status'] == 'zaladowana' and [s['order_id'] for s in dane['route']['stops']] == [jedzie.id]
    assert dane['removed'] == [{'order_id': zostaje.id, 'internal_order_number': zostaje.internal_order_number,
                                'reason': 'brak_miejsca'}]
    r = client.post(API + '/routes/%d/depart' % rid, headers=naglowki(device, k))
    assert r.status_code == 200 and r.get_json()['route']['status'] == 'w_trasie'
    assert [jedzie.id] in wywolania                                   # dopychacz Base. po commicie


def test_api_cofniecie_po_automatycznym_zamknieciu(app, client):
    """Review Focus 1: ostatnie „Dostarczone” zamyka trasę, telefon od razu cofa pomyłkę."""
    device, k = telefon_kierowcy()
    order, lista_paczek = zamowienie_z_paczkami(statusy=('zaladowane', 'zaladowane'))
    t = _trasa_kierowcy(k, [order], status='w_trasie', loaded_at=T0, departed_at=T0)
    zaladuj_wprost(lista_paczek, t, kto_id=k.id)
    rid = t.id
    r = client.post(API + '/routes/%d/stops/%d/delivered' % (rid, order.id), headers=naglowki(device, k))
    assert r.status_code == 200, r.get_data()[:300]
    dane = r.get_json()
    assert (dane['changed'], dane['route_completed'], dane['route']['status']) == (True, True, 'wykonana')
    r = client.post(API + '/routes/%d/stops/%d/undo-delivered' % (rid, order.id), headers=naglowki(device, k))
    assert r.status_code == 200 and r.get_json()['route']['status'] == 'w_trasie'
    assert RouteStop.query.filter_by(order_id=order.id).one().delivered_at is None


def test_niedostarczenie_przez_api(app, client):
    device, k = telefon_kierowcy()
    a, paczki_a = zamowienie_z_paczkami(statusy=('zaladowane', 'zaladowane'))
    b, paczki_b = zamowienie_z_paczkami(statusy=('zaladowane', 'zaladowane'))
    t = _trasa_kierowcy(k, [a, b], status='w_trasie')
    zaladuj_wprost(paczki_a + paczki_b, t)
    rid = t.id
    adres = API + '/routes/%d/stops/%d/not-delivered' % (rid, a.id)
    assert client.post(adres, headers=naglowki(device, k), json={'reason': 'nie_wiem'}).status_code == 422
    r = client.post(adres, headers=naglowki(device, k), json={'reason': 'brak_klienta', 'note': u'nie odbiera'})
    assert r.status_code == 200, r.get_data()[:300]
    dane = r.get_json()
    assert dane['route_completed'] is False and [s['order_id'] for s in dane['route']['stops']] == [b.id]
    r = client.post(adres, headers=naglowki(device, k), json={'reason': 'brak_klienta'})
    assert r.status_code == 404 and r.get_json()['error'] == 'stop_not_found'      # przystanku już nie ma


def test_zastepca_zapisuje_na_cudzej_trasie(app, client):
    """Akcje na trasie przyjmujemy od każdego aktywnego kierowcy (zastępstwo); „Moje trasy” są tylko jego."""
    device, wlasciciel = telefon_kierowcy()
    zastepca = kierowca()
    order, (p1, _p2) = zamowienie_z_paczkami()
    t = _trasa_kierowcy(wlasciciel, [order])
    r = client.post(API + '/routes/%d/packages/%d/load' % (t.id, p1.id), headers=naglowki(device, zastepca),
                    json={})
    assert r.status_code == 200
    assert p1.loaded_by_worker_id == zastepca.id
    assert client.get(API + '/routes', headers=naglowki(device, zastepca)).get_json()['count'] == 0


# --- Poza briefem: kontrakt, Ruling 23, trasa skasowana, przepływ end-to-end ------------------------------------

# Kształty z sekcji „Kontrakt API Dostawy” planu 4.4b.
KLUCZE_TRASY_KROTKO = {'id', 'name', 'date_from', 'date_to', 'status', 'status_label', 'vehicle_name',
                       'stops_total', 'stops_delivered', 'packages_total', 'packages_loaded'}
KLUCZE_TRASY = KLUCZE_TRASY_KROTKO | {'vehicle_registration', 'notes', 'loaded_at', 'departed_at', 'completed_at',
                                      'completed_by_panel', 'stops'}
KLUCZE_PRZYSTANKU = {'position', 'order_id', 'internal_order_number', 'client_name', 'recipient', 'phone',
                     'address', 'geo', 'order_notes', 'm3', 'weight_kg', 'packages', 'packages_total',
                     'packages_loaded', 'state', 'state_label', 'problem', 'stays', 'delivered_at'}
KLUCZE_PACZKI = {'id', 'code', 'seq', 'kind', 'pallet_type', 'length_cm', 'width_cm', 'verified', 'loaded',
                 'loaded_at', 'loaded_method'}


def _pelna_trasa(dane):
    """Odpowiedź zapisu niesie pełną trasę (ten sam kształt co GET) i komunikat — także przy changed: false."""
    assert set(dane['route']) == KLUCZE_TRASY, set(dane['route']) ^ KLUCZE_TRASY
    for s in dane['route']['stops']:
        assert set(s) == KLUCZE_PRZYSTANKU, set(s) ^ KLUCZE_PRZYSTANKU
        for p in s['packages']:
            assert set(p) == KLUCZE_PACZKI, set(p) ^ KLUCZE_PACZKI
    assert isinstance(dane['message'], str) and dane['message']
    return dane


def test_api_nieaktywny_kierowca_403(app, client):
    """Kontrakt: „nie kierowca albo nieaktywny → 403 not_a_driver” (a nie 409 worker_inactive z WorkerError);
    403 jest w BLEDY_DO_PONOWIENIA — akcja zostaje w kolejce offline."""
    device, k = telefon_kierowcy()
    byly = kierowca(aktywny=False)
    r = client.get(API + '/routes', headers=naglowki(device, byly))
    assert r.status_code == 403 and r.get_json()['error'] == 'not_a_driver' and r.get_json()['message']
    order, (p1, _p2) = zamowienie_z_paczkami()
    t = _trasa_kierowcy(k, [order])
    r = client.post(API + '/routes/%d/packages/%d/load' % (t.id, p1.id),
                    headers=naglowki(device, byly, op_id='op-nieaktywny'), json={})
    assert r.status_code == 403 and r.get_json()['error'] == 'not_a_driver'
    assert p1.loaded_at is None and ProcessedMobileOperation.query.get('op-nieaktywny') is None


def test_rozladunek_i_zdjecie_zostaje_przez_api(app, client):
    device, k = telefon_kierowcy()
    order, (p1, _p2) = zamowienie_z_paczkami()
    drugie, _ = zamowienie_z_paczkami()
    t = _trasa_kierowcy(k, [order, drugie])
    zaladuj_wprost([p1], t, kto_id=k.id)
    adres = API + '/routes/%d/packages/%d/unload' % (t.id, p1.id)
    r = client.post(adres, headers=naglowki(device, k))
    assert r.status_code == 200, r.get_data()[:300]
    dane = _pelna_trasa(r.get_json())
    assert (dane['changed'], dane['package']['code'], dane['package']['loaded']) == (True, 'P-%d' % p1.id, False)
    assert dane['route']['packages_loaded'] == 0 and p1.loaded_at is None
    r = client.post(adres, headers=naglowki(device, k))
    assert r.status_code == 200 and _pelna_trasa(r.get_json())['changed'] is False
    zostaje = API + '/routes/%d/stops/%d/stays' % (t.id, drugie.id)
    assert client.post(zostaje, headers=naglowki(device, k), json={'reason': 'uszkodzone'}).status_code == 200
    r = client.delete(zostaje, headers=naglowki(device, k))
    assert r.status_code == 200, r.get_data()[:300]
    dane = _pelna_trasa(r.get_json())
    assert dane['changed'] is True
    assert {s['order_id']: s['stays'] for s in dane['route']['stops']}[drugie.id] is None
    r = client.delete(zostaje, headers=naglowki(device, k))
    assert r.status_code == 200 and _pelna_trasa(r.get_json())['changed'] is False


def test_powtorka_zakonczenia_zaladunku_200_bez_zmian(app, client, monkeypatch):
    """Ruling 23: „Zakończ załadunek” na trasie już załadowanej albo w drodze (kolejka offline, nowy X-Operation-Id)
    → 200 {changed: false, removed: []} z pełną trasą i komunikatem; bez logu, bez statusu Base. i dopychacza."""
    wywolania = []
    monkeypatch.setattr(bl_sync, 'po_zmianie', lambda ids: wywolania.append(sorted(ids)))
    device, k = telefon_kierowcy()
    for status in ('zaladowana', 'w_trasie'):
        order, lista = zamowienie_z_paczkami(statusy=('zaladowane', 'zaladowane'))
        t = _trasa_kierowcy(k, [order], status=status, loaded_at=T0)
        zaladuj_wprost(lista, t, kto_id=k.id)
        r = client.post(API + '/routes/%d/finish-loading' % t.id, headers=naglowki(device, k))
        assert r.status_code == 200, r.get_data()[:300]
        dane = _pelna_trasa(r.get_json())
        assert (dane['changed'], dane['removed']) == (False, [])
        assert dane['route']['status'] == status and [s['order_id'] for s in dane['route']['stops']] == [order.id]
        assert order.bl_status_pending_id is None
    assert wywolania == []
    assert LogisticsLog.query.filter(LogisticsLog.action.in_(('zaladunek', 'trasa_status'))).count() == 0


def test_powtorka_wyjazdu_200_bez_zmian(app, client, monkeypatch):
    """Ruling 23: „Ruszam” na trasie w drodze albo już wykonanej → 200 changed: false z pełną trasą i komunikatem."""
    wywolania = []
    monkeypatch.setattr(bl_sync, 'po_zmianie', lambda ids: wywolania.append(sorted(ids)))
    device, k = telefon_kierowcy()
    for status, statusy in (('w_trasie', ('zaladowane',)), ('wykonana', ('dostarczone',))):
        order, lista = zamowienie_z_paczkami(statusy=statusy, paczek=1)
        t = _trasa_kierowcy(k, [order], status=status, loaded_at=T0, departed_at=T0)
        zaladuj_wprost(lista, t, kto_id=k.id)
        r = client.post(API + '/routes/%d/depart' % t.id, headers=naglowki(device, k))
        assert r.status_code == 200, r.get_data()[:300]
        dane = _pelna_trasa(r.get_json())
        assert dane['changed'] is False and dane['route']['status'] == status
        assert order.bl_status_pending_id is None
    assert wywolania == []
    assert LogisticsLog.query.filter_by(action='wyjazd').count() == 0


def test_trasa_skasowana_przed_blokada_404_z_kodem(app, client, monkeypatch):
    """Trasa skasowana (np. w panelu) między odczytem routera a blokadą tras: dostawa.zablokuj zamienia to na
    DostawaBlad route_not_found → 404 z kodem, niezapamiętane (ponowienie z tym samym X-Operation-Id przechodzi,
    gdy trasa jest). Robocza i nieistniejąca → 404 już w routerze. Odmowa bez kodu nie wychodzi jako 500."""
    device, k = telefon_kierowcy()
    order, (p1, _p2) = zamowienie_z_paczkami()
    t = _trasa_kierowcy(k, [order])
    rid = t.id
    oryginal = routes.zablokuj_trasy

    def skasuj_i_zablokuj(route=None):
        if route is not None:
            db.session.execute(text('DELETE FROM prod_route_stops WHERE route_id = :r'), {'r': rid})
            db.session.execute(text('DELETE FROM prod_routes WHERE id = :r'), {'r': rid})
        return oryginal(route)

    monkeypatch.setattr(routes, 'zablokuj_trasy', skasuj_i_zablokuj)
    zapisy = [('post', '/routes/%d/packages/%d/load' % (rid, p1.id)),
              ('post', '/routes/%d/packages/%d/unload' % (rid, p1.id)),
              ('post', '/routes/%d/stops/%d/stays' % (rid, order.id)),
              ('delete', '/routes/%d/stops/%d/stays' % (rid, order.id)),
              ('post', '/routes/%d/finish-loading' % rid),
              ('post', '/routes/%d/depart' % rid),
              ('post', '/routes/%d/stops/%d/delivered' % (rid, order.id)),
              ('post', '/routes/%d/stops/%d/not-delivered' % (rid, order.id)),
              ('post', '/routes/%d/stops/%d/undo-delivered' % (rid, order.id))]
    for i, (metoda, sciezka) in enumerate(zapisy):
        op = 'op-skasowana-%d' % i
        r = getattr(client, metoda)(API + sciezka, headers=naglowki(device, k, op_id=op),
                                    json={'reason': 'inne'})
        assert r.status_code == 404, (sciezka, r.get_data()[:300])
        assert r.get_json()['error'] == 'route_not_found' and r.get_json()['message'], sciezka
        assert ProcessedMobileOperation.query.get(op) is None, sciezka
    monkeypatch.setattr(routes, 'zablokuj_trasy', oryginal)
    r = client.post(API + zapisy[0][1], headers=naglowki(device, k, op_id='op-skasowana-0'), json={})
    assert r.status_code == 200 and r.get_json()['changed'] is True       # trasa jest (rollback) — ponowienie OK

    robocza = _trasa_kierowcy(k, [zamowienie_z_paczkami()[0]], status='robocza')
    for rid_ in (robocza.id, 987654):
        r = client.post(API + '/routes/%d/depart' % rid_, headers=naglowki(device, k))
        assert r.status_code == 404 and r.get_json()['error'] == 'route_not_found'

    def odmowa_bez_kodu(*a, **k_):
        raise LogistykaBlad(u'Odmowa bez kodu.', status=409)

    monkeypatch.setattr(dostawa, 'ruszaj', odmowa_bez_kodu)
    r = client.post(API + '/routes/%d/depart' % rid, headers=naglowki(device, k))
    assert r.status_code == 409 and r.get_json() == {'error': 'route_status', 'message': u'Odmowa bez kodu.'}


def test_przeplyw_kierowcy_z_powtorkami(app, client, monkeypatch):
    """Dzień kierowcy przez HTTP: załadunek obu paczek → zakończenie → wyjazd → dostarczenie (zamyka trasę) →
    cofnięcie. Każdy krok: powtórka z tym samym X-Operation-Id (odpowiedź z idempotencji — ta sama, bez drugiego
    wywołania i bez drugiego dopychacza Base.) i z nowym (kolejka offline: 200 changed false, pełna trasa i komunikat).
    Dopychacz Base. rusza dopiero po commicie: zapis idempotencji (ten sam commit) jest już w bazie."""
    biezaca = {}
    wywolania = []
    monkeypatch.setattr(bl_sync, 'po_zmianie', lambda ids: wywolania.append(
        (sorted(ids), ProcessedMobileOperation.query.get(biezaca['op']) is not None)))
    device, k = telefon_kierowcy()
    order, (p1, p2) = zamowienie_z_paczkami()
    t = _trasa_kierowcy(k, [order])
    rid, oid = t.id, order.id

    def krok(metoda, sciezka, op, **kw):
        biezaca['op'] = op
        r = getattr(client, metoda)(API + sciezka, headers=naglowki(device, k, op_id=op), **kw)
        assert r.status_code == 200, (sciezka, r.get_data()[:300])
        dane = _pelna_trasa(r.get_json())
        przed = len(wywolania)
        r = getattr(client, metoda)(API + sciezka, headers=naglowki(device, k, op_id=op), **kw)
        assert (r.status_code, r.get_json()) == (200, dane), sciezka           # odtworzone z idempotencji
        assert len(wywolania) == przed, sciezka                                # bez drugiego dopychacza
        biezaca['op'] = op + '-offline'
        r = getattr(client, metoda)(API + sciezka, headers=naglowki(device, k, op_id=op + '-offline'), **kw)
        assert r.status_code == 200, (sciezka, r.get_data()[:300])
        powtorka = _pelna_trasa(r.get_json())
        assert powtorka['changed'] is False and powtorka['route']['status'] == dane['route']['status'], sciezka
        assert len(wywolania) == przed, sciezka
        return dane, powtorka

    for p in (p1, p2):
        dane, _ = krok('post', '/routes/%d/packages/%d/load' % (rid, p.id), 'e2e-load-%d' % p.id,
                       json={'method': 'reczne'})
        assert dane['changed'] is True and dane['package']['loaded_method'] == 'reczne'
    assert dane['route']['packages_loaded'] == 2

    dane, powtorka = krok('post', '/routes/%d/finish-loading' % rid, 'e2e-finish')
    assert (dane['changed'], dane['removed'], dane['route']['status']) == (True, [], 'zaladowana')
    assert powtorka['removed'] == []
    assert wywolania[-1] == ([oid], True)

    dane, _ = krok('post', '/routes/%d/depart' % rid, 'e2e-depart')
    assert (dane['changed'], dane['route']['status']) == (True, 'w_trasie')
    assert wywolania[-1] == ([oid], True)

    dane, powtorka = krok('post', '/routes/%d/stops/%d/delivered' % (rid, oid), 'e2e-delivered')
    assert (dane['changed'], dane['route_completed'], dane['route']['status']) == (True, True, 'wykonana')
    assert dane['route']['stops'][0]['state'] == 'dostarczone' and dane['route']['stops_delivered'] == 1
    assert (powtorka['route_completed'], powtorka['route']['status']) == (False, 'wykonana')
    assert wywolania[-1] == ([oid], True)

    dane, _ = krok('post', '/routes/%d/stops/%d/undo-delivered' % (rid, oid), 'e2e-undo')
    assert (dane['changed'], dane['route']['status']) == (True, 'w_trasie')
    assert dane['route']['stops'][0]['delivered_at'] is None
    assert wywolania[-1] == ([oid], True)

    assert len(wywolania) == 4                    # zakończenie, wyjazd, dostarczenie, cofnięcie — po jednym razie
    assert {p.current_status for p in order.products} == {'zaladowane'}
    assert order.bl_status_pending_id == sposoby.STATUS_WYSLANE_TRANSPORT
    akcje = [w.action for w in LogisticsLog.query.filter_by(order_id=oid).order_by(LogisticsLog.id)]
    for akcja in ('zaladunek', 'wyjazd', 'dostarczone', 'dostarczenie_cofniete'):
        assert akcje.count(akcja) == 1, (akcja, akcje)


def test_zapisy_przez_api_decyduja_i_odpowiadaja_na_zablokowanych_obiektach(app, client, monkeypatch):
    """Ruling P2 na ścieżce HTTP: od pierwszej blokady zamówień do końca serializacji odpowiedzi
    (dostawa_widok.trasa_po_zapisie) żaden zwykły SELECT zamówień, pozycji, paczek ani tras — decyzje serwisu
    i pełna trasa w odpowiedzi idą na obiektach z odczytu bieżącego (na MySQL zwykły odczyt to migawka sprzed
    czekania na blokady). Przed każdym żądaniem obiekty testu odłączone (expunge_all), pamięć odśmiecana po
    blokadach i przy każdym wpisie logu (odsmiecaj_po_blokadach)."""
    device, k = telefon_kierowcy()
    a, (pa,) = zamowienie_z_paczkami(paczek=1)
    b, (pb,) = zamowienie_z_paczkami(paczek=1)
    c, _ = zamowienie_z_paczkami(paczek=1)
    t = _trasa_kierowcy(k, [a, b, c])
    rid, ia, ib, ic, pa_id, pb_id = t.id, a.id, b.id, c.id, pa.id, pb.id
    h = naglowki(device, k)
    licznik = odsmiecaj_po_blokadach(monkeypatch)
    biezace = {}
    oryginal = dostawa_widok.trasa_po_zapisie

    def po_zapisie(trasa_):
        wynik = oryginal(trasa_)
        biezace['koniec'] = len(biezace['z'].lista)
        return wynik

    monkeypatch.setattr(dostawa_widok, 'trasa_po_zapisie', po_zapisie)
    kroki = [('post', '/routes/%d/packages/%d/load' % (rid, pa_id), {}),
             ('post', '/routes/%d/packages/%d/load' % (rid, pb_id), {'method': 'reczne'}),
             ('post', '/routes/%d/stops/%d/stays' % (rid, ic), {'reason': 'brak_miejsca'}),
             ('delete', '/routes/%d/stops/%d/stays' % (rid, ic), None),
             ('post', '/routes/%d/stops/%d/stays' % (rid, ic), {'reason': 'uszkodzone'}),
             ('post', '/routes/%d/packages/%d/unload' % (rid, pb_id), None),
             ('post', '/routes/%d/packages/%d/load' % (rid, pb_id), {}),
             ('post', '/routes/%d/finish-loading' % rid, None),
             ('post', '/routes/%d/depart' % rid, None),
             ('post', '/routes/%d/stops/%d/delivered' % (rid, ia), None),
             ('post', '/routes/%d/stops/%d/not-delivered' % (rid, ib), {'reason': 'odmowa'}),
             ('post', '/routes/%d/stops/%d/undo-delivered' % (rid, ia), None)]
    for i, (metoda, sciezka, cialo) in enumerate(kroki):
        db.session.expunge_all()
        gc.collect()
        biezace.pop('koniec', None)
        with Zapytania() as z:
            biezace['z'] = z
            r = getattr(client, metoda)(API + sciezka, headers=dict(h, **{'X-Operation-Id': 'op-p2-%d' % i}),
                                        json=cialo)
        assert r.status_code == 200, (sciezka, r.get_data()[:300])
        do_odpowiedzi = Zapytania()
        do_odpowiedzi.lista = z.lista[:biezace['koniec']]          # decyzja i serializacja, bez commitu i po nim
        assert zwykle_odczyty_stanu(do_odpowiedzi) == [], sciezka
    assert r.get_json()['route']['status'] == 'w_trasie'
    assert [s['order_id'] for s in r.get_json()['route']['stops']] == [ia]
    assert licznik['_wymagaj_statusu'] > 0 and licznik['zapisz_log'] > 0
