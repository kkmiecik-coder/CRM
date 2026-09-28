# -*- coding: utf-8 -*-
"""Runda 2 (spec 2.6): kierowcy tras jako wyróżnieni pracownicy (prod_workers.is_driver)."""
from datetime import date

import pytest

from extensions import db
from modules.production.logistics import sposoby as s
from modules.production.logistics.services import fleet, routes
from modules.production.logistics.services.delivery import LogistykaBlad
from tests.logistyka_fixtures import BASE, app, client, kierowca, pracownik, zamowienie  # noqa: F401


def _trasa(nazwa='Kraków', od='2026-10-01', do=None, **dane):
    trasa = routes.utworz(dict(dane, name=nazwa, date_from=od, date_to=do or od))
    db.session.commit()
    return trasa


# ── Serwis ─────────────────────────────────────────────────────────────────

def test_kierowcy_i_kandydaci(app):
    with app.app_context():
        k = kierowca(imie='Adam', nazwisko='Nowak')
        kierowca(imie='Ex', nazwisko='Kierowca', aktywny=False)
        p = pracownik(imie='Piotr', nazwisko='Zwykły')
        pracownik(imie='Stary', nazwisko='Odszedł', aktywny=False)
        assert fleet.kierowcy() == [{'id': k.id, 'nazwa': 'Adam Nowak'}]
        assert fleet.kandydaci_na_kierowcow() == [{'id': p.id, 'nazwa': 'Piotr Zwykły'}]


def test_dodanie_i_zdjecie_znacznika_idempotentne(app):
    with app.app_context():
        p = pracownik()
        for _ in range(2):
            fleet.dodaj_kierowce(p.id)
            db.session.commit()
            assert p.is_driver is True
        assert [k['id'] for k in fleet.kierowcy()] == [p.id]
        for _ in range(2):
            fleet.usun_kierowce(str(p.id))
            db.session.commit()
            assert p.is_driver is False and p.is_active is True      # pracownik zostaje
        assert fleet.kierowcy() == []


def test_dodanie_nieistniejacego_i_nieaktywnego(app):
    with app.app_context():
        for funkcja in (fleet.dodaj_kierowce, fleet.usun_kierowce):
            with pytest.raises(LogistykaBlad) as e:
                funkcja(999999)
            assert e.value.status == 404
        p = pracownik(aktywny=False)
        with pytest.raises(LogistykaBlad) as e:
            fleet.dodaj_kierowce(p.id)
        assert e.value.status == 409 and p.is_driver is False


@pytest.mark.parametrize('wartosc', [None, '', 'abc', True, False, 1.0, 0, -3, '²', '9' * 20,
                                     10 ** 12, [1], {'id': 1}])
def test_zly_identyfikator_pracownika_422(app, wartosc):
    with app.app_context():
        with pytest.raises(LogistykaBlad) as e:
            fleet.dodaj_kierowce(wartosc)
        assert e.value.status == 422


def test_trasy_kierowcy_tylko_aktywne(app):
    with app.app_context():
        k = kierowca()
        _trasa('Robocza', od='2026-10-05', driver_worker_id=k.id)
        z = _trasa('Zatwierdzona', od='2026-10-01', driver_worker_id=k.id)
        w = _trasa('Wykonana', od='2026-10-10', driver_worker_id=k.id)
        z.status, w.status = 'zatwierdzona', 'wykonana'
        db.session.commit()
        assert fleet.trasy_kierowcow([k.id]) == {k.id: ['Zatwierdzona', 'Robocza']}
        assert fleet.kierowcy_z_trasami() == [{'id': k.id, 'nazwa': fleet.nazwa_pracownika(k),
                                              'trasy': ['Zatwierdzona', 'Robocza']}]


# ── Zapis trasy ────────────────────────────────────────────────────────────

def test_nowy_albo_zmieniony_kierowca_bez_znacznika_to_409(app):
    with app.app_context():
        p = pracownik(imie='Piotr', nazwisko='Zwykły')
        with pytest.raises(LogistykaBlad) as e:
            routes.utworz({'name': 'A', 'date_from': '2026-10-01', 'driver_worker_id': p.id})
        assert e.value.status == 409 and 'Piotr Zwykły nie jest kierowcą' in e.value.komunikat
        db.session.rollback()
        t = _trasa(driver_worker_id=kierowca().id)
        with pytest.raises(LogistykaBlad) as e:
            routes.edytuj(t, {'name': 'A', 'date_from': '2026-10-01', 'driver_worker_id': p.id})
        assert e.value.status == 409


def test_kierowca_bez_znacznika_zostaje_na_swojej_trasie(app):
    """Review Focus 2 (rozstrzygnięcie 33): zdjęcie znacznika nie psuje tras, na których
    kierowca już jest — edycja i przywrócenie przechodzą, wybór pokazuje go tylko w jego
    trasie (`nie_kierowca`), a po zmianie na innego kierowcę nie da się do niego wrócić."""
    with app.app_context():
        k = kierowca(imie='Adam', nazwisko='Nowak')
        inny = kierowca()
        t = _trasa('Kraków', od='2026-10-01', driver_worker_id=k.id)
        obca = _trasa('Rzeszów', od='2026-10-07', driver_worker_id=inny.id)
        w = _trasa('Tarnów', od='2026-10-03', driver_worker_id=k.id)
        a = zamowienie(sposob=s.TRANSPORT, statusy=('spakowane',))
        routes.dodaj_przystanki(w, [a.id])
        routes.zatwierdz(w)
        routes.wykonaj(w, [a.id])
        db.session.commit()

        fleet.usun_kierowce(k.id)
        db.session.commit()

        routes.edytuj(t, {'name': 'Kraków 2', 'date_from': '2026-10-01', 'driver_worker_id': k.id})
        db.session.commit()
        assert (t.name, t.driver_worker_id) == ('Kraków 2', k.id)
        routes.przywroc(w)
        db.session.commit()
        assert w.status == 'zatwierdzona'

        dzien = date(2026, 10, 1)
        assert {'id': k.id, 'nazwa': 'Adam Nowak', 'nie_kierowca': True, 'zajety': False,
                'trasa': None} in routes.dostepnosc(dzien, dzien, t.id)['kierowcy']
        for route_id in (None, obca.id):                  # nowa trasa i cudza trasa — bez niego
            assert k.id not in [x['id'] for x in routes.dostepnosc(dzien, dzien, route_id)['kierowcy']]

        routes.edytuj(t, {'name': 'Kraków 2', 'date_from': '2026-10-01', 'driver_worker_id': inny.id})
        db.session.commit()
        with pytest.raises(LogistykaBlad) as e:
            routes.edytuj(t, {'name': 'Kraków 2', 'date_from': '2026-10-01', 'driver_worker_id': k.id})
        assert e.value.status == 409


def test_dostepnosc_bez_nieaktywnego_kierowcy_trasy(app):
    """Nieaktywnego nie dokładamy — UI pokazuje go z danych trasy jako „(nieaktywny)”."""
    with app.app_context():
        k = kierowca()
        t = _trasa(driver_worker_id=k.id)
        k.is_active, k.is_driver = False, False
        db.session.commit()
        dzien = date(2026, 10, 1)
        assert routes.dostepnosc(dzien, dzien, t.id)['kierowcy'] == []


# ── API ────────────────────────────────────────────────────────────────────

def test_api_kandydaci_dodanie_i_zdjecie(client, app):
    with app.app_context():
        pid = pracownik(imie='Piotr', nazwisko='Zwykły').id
    assert client.get(BASE + '/drivers').get_json()['drivers'] == []
    assert client.get(BASE + '/drivers/candidates').get_json()['candidates'] == \
        [{'id': pid, 'nazwa': 'Piotr Zwykły'}]
    for _ in range(2):                                           # idempotentne
        r = client.post(BASE + '/drivers', json={'worker_id': pid})
        assert r.status_code == 200
        assert r.get_json()['drivers'] == [{'id': pid, 'nazwa': 'Piotr Zwykły', 'trasy': []}]
    assert client.get(BASE + '/drivers/candidates').get_json()['candidates'] == []
    for _ in range(2):
        r = client.delete(BASE + '/drivers/%d' % pid)
        assert r.status_code == 200 and r.get_json()['drivers'] == []
    assert r.get_json()['driver'] == {'id': pid, 'nazwa': 'Piotr Zwykły', 'is_driver': False,
                                      'trasy': []}


@pytest.mark.parametrize('cialo, status', [
    ({'worker_id': 999999}, 404), ({}, 422), ({'worker_id': 'abc'}, 422),
    ({'worker_id': True}, 422), ([1, 2], 422),
])
def test_api_dodanie_bledy(client, cialo, status):
    r = client.post(BASE + '/drivers', json=cialo)
    assert r.status_code == status
    assert r.get_json()['success'] is False and r.get_json()['error']


def test_api_nieaktywny_zle_cialo_i_brak(client, app):
    with app.app_context():
        pid = pracownik(aktywny=False).id
    assert client.post(BASE + '/drivers', json={'worker_id': pid}).status_code == 409
    assert client.post(BASE + '/drivers', data='nie-json',
                       content_type='application/json').status_code == 422
    assert client.delete(BASE + '/drivers/999999').status_code == 404


def test_api_trasy_kierowcy_i_zapis_trasy(client, app):
    with app.app_context():
        kid = kierowca(imie='Adam', nazwisko='Nowak').id
        pid = pracownik().id
    rid = client.post(BASE + '/routes', json={'name': 'Kraków', 'date_from': '2026-10-01',
                                              'driver_worker_id': kid}).get_json()['route']['id']
    assert client.get(BASE + '/drivers').get_json()['drivers'][0]['trasy'] == ['Kraków']
    r = client.post(BASE + '/routes', json={'name': 'B', 'date_from': '2026-10-05',
                                            'driver_worker_id': pid})
    assert r.status_code == 409 and 'nie jest kierowcą' in r.get_json()['error']
    assert client.delete(BASE + '/drivers/%d' % kid).get_json()['driver']['trasy'] == ['Kraków']
    d = client.get(BASE + '/availability?date_from=2026-10-01&route_id=%d' % rid).get_json()
    assert [k for k in d['kierowcy'] if k['id'] == kid][0]['nie_kierowca'] is True
    d = client.get(BASE + '/availability?date_from=2026-10-01').get_json()
    assert kid not in [k['id'] for k in d['kierowcy']]
    assert client.put(BASE + '/routes/%d' % rid, json={'name': 'Kraków 2', 'date_from': '2026-10-01',
                                                       'driver_worker_id': kid}).status_code == 200
