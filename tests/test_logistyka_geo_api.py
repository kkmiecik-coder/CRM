# -*- coding: utf-8 -*-
import pytest

from extensions import db
from modules.production.logistics.models import OrderGeo
from modules.production.logistics.services import bl_sync, geocoding
from tests.logistyka_fixtures import BASE, SEKRET_CRONA, app, client, zamowienie  # noqa: F401


@pytest.fixture(autouse=True)
def bez_watkow(monkeypatch):
    uruchomione = []
    monkeypatch.setattr(geocoding, 'uruchom_w_tle', lambda app_: uruchomione.append('geo') or True)
    monkeypatch.setattr(bl_sync, 'uruchom_w_tle', lambda app_: uruchomione.append('base') or True)
    return uruchomione


def test_lista_niesie_wspolrzedne_i_licznik(client, app):
    with app.app_context():
        a = zamowienie()
        zamowienie()
        a_id = a.id
        db.session.add(OrderGeo(order_id=a.id, lat=50.06, lng=19.94, source='gugik',
                                quality='dokladna', address_hash='x' * 40))
        db.session.commit()
    dane = client.get(BASE + '/orders').get_json()
    geo = {o['id']: o['geo'] for o in dane['orders']}
    assert geo[a_id] == {'lat': 50.06, 'lng': 19.94, 'quality': 'dokladna',
                         'source': 'gugik', 'adres_zmieniony': False}
    assert dane['bez_lokalizacji'] == 1
    assert dane['geokoder_dziala'] is False


def test_zlokalizuj_teraz_uruchamia_watek(client, bez_watkow):
    r = client.post(BASE + '/geocode')
    assert r.status_code == 202 and bez_watkow == ['geo']


def test_reczna_korekta_i_reset(client, app):
    with app.app_context():
        oid = zamowienie().id
    r = client.put(BASE + '/orders/%d/geo' % oid, json={'lat': 50.1, 'lng': 20.2})
    assert r.status_code == 200 and r.get_json()['order']['geo']['source'] == 'reczna'
    assert client.put(BASE + '/orders/%d/geo' % oid, json={'lat': 'x'}).status_code == 422
    assert client.put(BASE + '/orders/999999/geo', json={'lat': 1, 'lng': 1}).status_code == 404
    r = client.post(BASE + '/orders/%d/geo/reset' % oid)
    assert r.status_code == 200 and r.get_json()['order']['geo'] is None


@pytest.mark.parametrize('body', [[1, 2], 'x', 5])
def test_reczna_korekta_cialo_inne_niz_obiekt_to_422(client, app, body):
    """Decyzja 1: jak delivery_method() — tablica/skalar w ciele bez tego .get()
    rzuca AttributeError (500) zamiast czystego 422."""
    with app.app_context():
        oid = zamowienie().id
    assert client.put(BASE + '/orders/%d/geo' % oid, json=body).status_code == 422


def test_reczna_korekta_wyscig_z_geokoderem_w_tle(client, app, monkeypatch):
    """Decyzja 2: geokoder w tle mógł w międzyczasie wstawić ten sam wiersz
    (INSERT z SELECT ... FOR UPDATE) — commit żądania webowego dostaje
    IntegrityError. Ponawiamy raz (ustaw_recznie znowu, tym razem UPDATE)."""
    with app.app_context():
        oid = zamowienie().id

    from sqlalchemy.exc import IntegrityError
    oryginalny_commit = db.session.commit
    stan = {'wywolania': 0}

    def raz_awaryjny_commit():
        stan['wywolania'] += 1
        if stan['wywolania'] == 1:
            raise IntegrityError('insert', {}, Exception('duplicate key'))
        return oryginalny_commit()

    monkeypatch.setattr(db.session, 'commit', raz_awaryjny_commit)

    r = client.put(BASE + '/orders/%d/geo' % oid, json={'lat': 50.1, 'lng': 20.2})
    assert r.status_code == 200
    assert r.get_json()['order']['geo']['source'] == 'reczna'


def test_reczna_korekta_wyscig_druga_probka_tez_pada(client, app, monkeypatch):
    """Decyzja 2: gdy IntegrityError powtarza się przy ponowieniu — 409, nie 500."""
    with app.app_context():
        oid = zamowienie().id

    from sqlalchemy.exc import IntegrityError

    def zawsze_pada():
        raise IntegrityError('insert', {}, Exception('duplicate key'))

    monkeypatch.setattr(db.session, 'commit', zawsze_pada)

    r = client.put(BASE + '/orders/%d/geo' % oid, json={'lat': 50.1, 'lng': 20.2})
    assert r.status_code == 409
    assert r.get_json()['success'] is False


def test_cron_uruchamia_tez_geokoder(client, bez_watkow):
    r = client.post(BASE + '/cron', headers={'X-Cron-Secret': SEKRET_CRONA})
    assert r.get_json()['geokoder_uruchomiony'] is True
    assert sorted(bez_watkow) == ['base', 'geo']


def test_zakladka_zna_magazyn(client):
    html = client.get(BASE + '/tab-content').get_data(as_text=True)
    assert 'data-magazyn-lat="49.840438"' in html
