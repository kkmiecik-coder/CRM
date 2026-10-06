# -*- coding: utf-8 -*-
import json

import pytest

from extensions import db
from modules.production.logistics.models import OrderGeo
from modules.production.logistics.services import bl_sync, dzierzawa, geocoding
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
    assert dane['geokoder_postep'] is None


def test_lista_niesie_postep_geokodera(client, app):
    """UF3: przycisk „Zlokalizuj teraz” pokazuje postęp trwającego przebiegu."""
    with app.app_context():
        zamowienie()
        dzierzawa.zapisz(geocoding.KLUCZ_POSTEPU, json.dumps(
            {'wszystkie': 5, 'zrobione': 2, 'od': '2026-09-25T10:00:00'}))
    # wpis bez żywej dzierżawy (osierocony po padniętym procesie) — brak postępu
    assert client.get(BASE + '/orders').get_json()['geokoder_postep'] is None
    with app.app_context():
        assert dzierzawa.przejmij(geocoding.KLUCZ_DZIERZAWY, geocoding.CZAS_DZIERZAWY_S)
    dane = client.get(BASE + '/orders').get_json()
    assert dane['geokoder_dziala'] is True
    assert dane['geokoder_postep'] == {'zrobione': 2, 'wszystkie': 5}


def test_zlokalizuj_teraz_uruchamia_watek(client, bez_watkow):
    r = client.post(BASE + '/geocode')
    assert r.status_code == 202 and bez_watkow == ['geo']


def test_pinezka_bierze_blokade_tras_przed_odczytem_przystanku(client, app, monkeypatch):
    """fix-2, N1: PUT /orders/<id>/geo (ustaw_recznie -> sprawdz_trase_przed_zmiana
    -> _przystanek_do_zmiany) bierze globalną blokadę tras PRZED odczytem
    przystanku — sam powód i kolejność co PUT /orders/<id>/address (patrz
    test_logistyka_poprawki_panelu.py); ta sama ścieżka domyka Task 4 (pinezka
    mapy)."""
    from modules.production.logistics.services import routes
    kolejnosc = []
    oryg_blokuj = routes.zablokuj_trasy
    oryg_przystanek = routes.przystanek_zamowienia

    def podglad_blokuj(route=None):
        kolejnosc.append('blokada')
        return oryg_blokuj(route)

    def podglad_przystanek(order_id, aktualny=False):
        kolejnosc.append('przystanek')
        return oryg_przystanek(order_id, aktualny=aktualny)

    monkeypatch.setattr(routes, 'zablokuj_trasy', podglad_blokuj)
    monkeypatch.setattr(routes, 'przystanek_zamowienia', podglad_przystanek)
    with app.app_context():
        oid = zamowienie().id
    r = client.put(BASE + '/orders/%d/geo' % oid, json={'lat': 50.1, 'lng': 20.2})
    assert r.status_code == 200
    assert kolejnosc == ['blokada', 'przystanek']


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


def test_reczna_korekta_bool_to_nie_wspolrzedne(client, app):
    """M1: bool to podklasa int — true/false przeszłyby jako 1.0/0.0."""
    with app.app_context():
        oid = zamowienie().id
    r = client.put(BASE + '/orders/%d/geo' % oid, json={'lat': True, 'lng': False})
    assert r.status_code == 422
    with app.app_context():
        assert OrderGeo.query.get(oid) is None


def test_reczna_korekta_wyscig_z_geokoderem_w_tle(client, app, monkeypatch):
    """Decyzja 2: geokoder w tle mógł w międzyczasie wstawić ten sam wiersz
    (INSERT z SELECT ... FOR UPDATE) — commit żądania webowego dostaje
    IntegrityError. Ponawiamy raz (ustaw_recznie znowu, tym razem UPDATE).

    M9: fałszywy commit zasiewa wiersz geokodera (jak zrobiłby równoległy proces),
    więc ponowienie naprawdę idzie ścieżką UPDATE istniejącego wiersza."""
    with app.app_context():
        order = zamowienie()
        oid, skrot = order.id, geocoding.skrot_adresu(order)

    from sqlalchemy.exc import IntegrityError
    oryginalny_commit = db.session.commit
    stan = {'wywolania': 0}

    def raz_awaryjny_commit():
        stan['wywolania'] += 1
        if stan['wywolania'] == 1:
            # Geokoder w tle zdążył zapisać swój punkt: nasz INSERT dostałby duplicate key.
            db.session.rollback()
            db.session.add(OrderGeo(order_id=oid, lat=49.0, lng=21.0, source='gugik',
                                    quality='dokladna', address_hash=skrot))
            oryginalny_commit()
            raise IntegrityError('insert', {}, Exception('duplicate key'))
        return oryginalny_commit()

    monkeypatch.setattr(db.session, 'commit', raz_awaryjny_commit)

    r = client.put(BASE + '/orders/%d/geo' % oid, json={'lat': 50.1, 'lng': 20.2})
    assert r.status_code == 200
    assert r.get_json()['order']['geo']['source'] == 'reczna'
    with app.app_context():
        db.session.expire_all()
        punkty = OrderGeo.query.filter_by(order_id=oid).all()
        assert len(punkty) == 1
        assert (punkty[0].source, float(punkty[0].lat), float(punkty[0].lng)) == ('reczna', 50.1, 20.2)


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
