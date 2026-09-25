# -*- coding: utf-8 -*-
import pytest
from sqlalchemy.exc import IntegrityError

from extensions import db
from modules.production.logistics import sposoby as s
from modules.production.logistics.models import Route
from tests.logistyka_fixtures import BASE, app, client, kierowca, pojazd, zamowienie  # noqa: F401


@pytest.fixture(autouse=True)
def bez_ors(app):
    app.config.pop('OPENROUTESERVICE_API_KEY', None)


def _nowa(client, **dane):
    dane.setdefault('name', 'Kraków')
    dane.setdefault('date_from', '2026-10-01')
    return client.post(BASE + '/routes', json=dane)


def test_flota_crud(client):
    r = client.post(BASE + '/vehicles', json={'name': 'Iveco', 'capacity_kg': 1500})
    assert r.status_code == 201
    vid = r.get_json()['vehicle']['id']
    assert client.put(BASE + '/vehicles/%d' % vid, json={'name': 'Iveco Daily'}).status_code == 200
    assert client.post(BASE + '/vehicles/%d/active' % vid, json={'active': False}).get_json()['vehicle']['is_active'] is False
    assert client.get(BASE + '/vehicles?aktywne=1').get_json()['vehicles'] == []
    assert client.post(BASE + '/vehicles', json={'name': ''}).status_code == 422


def test_dostepnosc_i_konflikt(client, app):
    with app.app_context():
        vid = pojazd().id
    assert _nowa(client, vehicle_id=vid).status_code == 201
    d = client.get(BASE + '/availability?date_from=2026-10-01&date_to=2026-10-01').get_json()
    assert d['pojazdy'][0]['zajety'] is True and d['pojazdy'][0]['trasa'] == 'Kraków'
    r = _nowa(client, name='Druga', vehicle_id=vid)
    assert r.status_code == 409 and 'Kraków' in r.get_json()['error']


def test_pelny_cykl_trasy(client, app):
    with app.app_context():
        a = zamowienie(sposob=s.TRANSPORT, statusy=('spakowane',)).id
        b = zamowienie(sposob=s.TRANSPORT, statusy=('spakowane',)).id
    rid = _nowa(client).get_json()['route']['id']
    r = client.post(BASE + '/routes/%d/stops' % rid, json={'order_ids': [a, b]})
    assert r.get_json()['dodane'] == [a, b]
    trasa = r.get_json()['route']
    assert [p['zamowienie']['id'] for p in trasa['przystanki']] == [a, b]
    assert trasa['podsumowanie']['przystanki'] == 2
    assert client.put(BASE + '/routes/%d/stops/order' % rid, json={'order_ids': [b, a]}).status_code == 200
    assert client.post(BASE + '/routes/%d/approve' % rid).get_json()['route']['status'] == 'zatwierdzona'
    assert client.delete(BASE + '/routes/%d/stops/%d' % (rid, a)).status_code == 409
    r = client.post(BASE + '/routes/%d/complete' % rid, json={'delivered_order_ids': [b]})
    assert r.get_json()['wynik'] == {'dostarczone': [b], 'niedostarczone': [a]}
    assert client.post(BASE + '/routes/%d/restore' % rid).get_json()['route']['status'] == 'zatwierdzona'


def test_mapa_tras_aktywnych(client, app):
    with app.app_context():
        a = zamowienie(sposob=s.TRANSPORT).id
    rid = _nowa(client).get_json()['route']['id']
    client.post(BASE + '/routes/%d/stops' % rid, json={'order_ids': [a]})
    mapa = client.get(BASE + '/routes/map').get_json()['routes']
    assert mapa[0]['id'] == rid and mapa[0]['przystanki'][0]['order_id'] == a


def test_kierowcy(client, app):
    with app.app_context():
        kierowca(imie='Adam', nazwisko='Nowak')
    assert client.get(BASE + '/drivers').get_json()['drivers'][0]['nazwa'] == 'Adam Nowak'


def test_usuniecie_roboczej_i_404(client):
    rid = _nowa(client).get_json()['route']['id']
    assert client.delete(BASE + '/routes/%d' % rid).status_code == 200
    assert client.get(BASE + '/routes/%d' % rid).status_code == 404


# ── R8: co najwyżej jedno przeliczenie przebiegu na żądanie /routes/map ─────

def test_mapa_najwyzej_jeden_przelicz_na_zadanie(client, app):
    """
    Dwie aktywne trasy z przystankami, obie ze sztucznie „nieaktualnym" skrótem
    przebiegu (symulacja: geokoder w tle dopiero co uzupełnił współrzędne, więc
    cache w bazie jest stary). Pierwsze GET /routes/map ma przeliczyć TYLKO
    jedną z nich (i ją zacommitować) — druga zostaje nieaktualna do kolejnego
    żądania. Bez tej reguły dwie trasy bez klucza ORS (a z kluczem — N × 8 s
    zapytań do ORS) mogłyby razem przekroczyć timeout gunicorna (30 s).
    """
    with app.app_context():
        a = zamowienie(sposob=s.TRANSPORT).id
        b = zamowienie(sposob=s.TRANSPORT).id
    r1 = _nowa(client, name='Trasa A').get_json()['route']['id']
    r2 = _nowa(client, name='Trasa B').get_json()['route']['id']
    client.post(BASE + '/routes/%d/stops' % r1, json={'order_ids': [a]})
    client.post(BASE + '/routes/%d/stops' % r2, json={'order_ids': [b]})

    with app.app_context():
        for rid in (r1, r2):
            Route.query.get(rid).geometry_hash = 'nieaktualny'
        db.session.commit()

    client.get(BASE + '/routes/map')
    with app.app_context():
        swieze = [rid for rid in (r1, r2) if Route.query.get(rid).geometry_hash != 'nieaktualny']
    assert len(swieze) == 1

    client.get(BASE + '/routes/map')
    with app.app_context():
        assert all(Route.query.get(rid).geometry_hash != 'nieaktualny' for rid in (r1, r2))


# ── R9: walidacja wejścia — nigdy 500 na złych danych ────────────────────────

def test_lista_tras_zla_wartosc_filtrow(client):
    assert client.get(BASE + '/routes?status=nieznany').status_code == 422
    assert client.get(BASE + '/routes?od=nie-data').status_code == 422
    assert client.get(BASE + '/routes?do=nie-data').status_code == 422


def test_cialo_listowe_zamiast_obiektu_to_422(client):
    assert client.post(BASE + '/routes', json=[1, 2]).status_code == 422
    assert client.post(BASE + '/vehicles', json=[1, 2]).status_code == 422
    vid = client.post(BASE + '/vehicles', json={'name': 'X'}).get_json()['vehicle']['id']
    assert client.put(BASE + '/vehicles/%d' % vid, json=[1, 2]).status_code == 422


def test_dostepnosc_do_wczesniej_niz_od_to_422(client):
    r = client.get(BASE + '/availability?date_from=2026-10-05&date_to=2026-10-01')
    assert r.status_code == 422


def test_aktywnosc_pojazdu_wymaga_bool(client):
    vid = client.post(BASE + '/vehicles', json={'name': 'X'}).get_json()['vehicle']['id']
    r = client.post(BASE + '/vehicles/%d/active' % vid, json={'active': 'false'})
    assert r.status_code == 422


def test_za_duzo_zamowien_w_stopach_to_422(client):
    rid = _nowa(client).get_json()['route']['id']
    r = client.post(BASE + '/routes/%d/stops' % rid, json={'order_ids': list(range(1, 502))})
    assert r.status_code == 422


def test_konflikt_rownoczesnego_dodania_to_409(client, app, monkeypatch):
    """
    UNIQUE na prod_route_stops.order_id jako ostatnia linia obrony: dwie osoby
    dodają to samo zamówienie do dwóch różnych tras w tej samej chwili.
    """
    from modules.production.logistics.services import routes as routes_service
    with app.app_context():
        a = zamowienie(sposob=s.TRANSPORT, statusy=('spakowane',)).id
    rid = _nowa(client).get_json()['route']['id']

    def _wybuchnij(*args, **kwargs):
        raise IntegrityError('INSERT', {}, Exception('dup'))

    monkeypatch.setattr(routes_service, 'dodaj_przystanki', _wybuchnij)
    r = client.post(BASE + '/routes/%d/stops' % rid, json={'order_ids': [a]})
    assert r.status_code == 409
    assert 'odśwież listę' in r.get_json()['error']
