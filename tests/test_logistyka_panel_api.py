# -*- coding: utf-8 -*-
from datetime import date, datetime

import pytest

from extensions import db
from modules.production.logistics import sposoby as s
from modules.production.logistics.services import bl_sync
from modules.production.models import ProductionOrder
from tests.logistyka_fixtures import BASE, app, client, zamowienie  # noqa: F401


@pytest.fixture(autouse=True)
def bez_base(monkeypatch):
    wywolane = []
    monkeypatch.setattr(bl_sync, 'po_zmianie', lambda ids: wywolane.append(list(ids)))
    return wywolane


def test_lista_otwartych_z_nieustawionymi_na_gorze(client, app):
    with app.app_context():
        a = zamowienie(sposob=s.KURIER)
        a.products[0].deadline_date = date(2026, 9, 26)
        b = zamowienie()
        b.products[0].deadline_date = date(2026, 10, 30)
        zamowienie(sposob=s.KURIER, statusy=('spakowane',),
                   logistics_closed_at=datetime(2026, 9, 1))  # zamknięte — niewidoczne
        db.session.commit()
        numery = [a.internal_order_number, b.internal_order_number]
    dane = client.get(BASE + '/orders').get_json()
    assert [o['numer'] for o in dane['orders']] == [numery[1], numery[0]]
    assert dane['liczniki']['brak'] == 1 and dane['liczniki'][s.KURIER] == 1


def test_wiersz_listy(client, app):
    with app.app_context():
        order = zamowienie(statusy=('czeka_na_lakiernie', 'czeka_na_pakowanie'),
                           delivery_method='Odbiór osobisty')
        order.products[0].label_printed_at = datetime(2026, 9, 24, 8, 0)
        order.override_delivery_method = s.KURIER
        order.delivery_method_set_at = datetime(2026, 9, 24, 9, 0)
        db.session.commit()
    wiersz = client.get(BASE + '/orders').get_json()['orders'][0]
    assert wiersz['sposob'] == s.KURIER and wiersz['sposob_etykieta'] == 'Kurier'
    assert wiersz['podpowiedz'] == s.ODBIOR
    assert wiersz['metoda_z_base'] == 'Odbiór osobisty'
    assert wiersz['etap']['status'] == 'czeka_na_lakiernie'
    assert wiersz['m3'] == pytest.approx(0.096)  # 2 pozycje × 0.024 × 2 szt.
    assert wiersz['etykiety_sprzed_zmiany'] is True


def test_filtr_i_wyszukiwarka(client, app):
    with app.app_context():
        zamowienie(sposob=s.KURIER, miasto='Tarnów')
        zamowienie(miasto='Rzeszów')
    assert len(client.get(BASE + '/orders?sposob=brak').get_json()['orders']) == 1
    assert client.get(BASE + '/orders?q=Tarn').get_json()['orders'][0]['miasto'] == 'Tarnów'


def test_zamkniete_tylko_z_wyszukiwaniem(client, app):
    with app.app_context():
        zamowienie(sposob=s.KURIER, statusy=('spakowane',), miasto='Gdańsk',
                   logistics_closed_at=datetime(2026, 9, 1))
    assert client.get(BASE + '/orders?zamkniete=1').status_code == 422
    dane = client.get(BASE + '/orders?zamkniete=1&q=Gda').get_json()
    assert dane['orders'][0]['zamkniete'] is True


def test_zamkniete_z_filtrem_sposobu_i_wyszukiwarka(client, app):
    """
    R3: w SQLAlchemy < 2.0 Query.filter() wołane PO limit() rzuca
    InvalidRequestError. `zamkniete=1` dokłada order_by/limit — filtry q i sposob
    muszą trafić do zapytania PRZED nimi, inaczej to żądanie (zamkniete razem
    z q i sposob naraz) skończyłoby się 500, nie 200 z poprawnie zawężoną listą.
    """
    with app.app_context():
        kurier = zamowienie(sposob=s.KURIER, statusy=('spakowane',), miasto='Gdynia',
                            logistics_closed_at=datetime(2026, 9, 2))
        brak = zamowienie(statusy=('spakowane',), miasto='Gdynia',
                          logistics_closed_at=datetime(2026, 9, 2))
        numer_kurier = kurier.internal_order_number
        numer_brak = brak.internal_order_number

    r = client.get(BASE + '/orders?zamkniete=1&q=Gdy&sposob=' + s.KURIER)
    assert r.status_code == 200
    assert [o['numer'] for o in r.get_json()['orders']] == [numer_kurier]

    r = client.get(BASE + '/orders?zamkniete=1&q=Gdy&sposob=brak')
    assert r.status_code == 200
    assert [o['numer'] for o in r.get_json()['orders']] == [numer_brak]


def test_hurtowe_ustawienie_sposobu(client, app, bez_base):
    with app.app_context():
        ids = [zamowienie().id, zamowienie().id]
    r = client.post(BASE + '/orders/delivery-method',
                    json={'order_ids': ids, 'sposob': s.TRANSPORT})
    dane = r.get_json()
    assert r.status_code == 200 and sorted(dane['zmienione']) == sorted(ids)
    assert bez_base == [sorted(ids)] or bez_base == [ids]
    with app.app_context():
        assert all(ProductionOrder.query.get(i).override_delivery_method == s.TRANSPORT
                   for i in ids)


def test_hurt_z_czesciowa_odmowa(client, app):
    with app.app_context():
        ok = zamowienie().id
        wydane = zamowienie(sposob=s.ODBIOR, statusy=('spakowane',),
                            handed_over_at=datetime(2026, 9, 20)).id
    dane = client.post(BASE + '/orders/delivery-method',
                       json={'order_ids': [ok, wydane], 'sposob': s.KURIER}).get_json()
    assert dane['zmienione'] == [ok]
    assert dane['bledy'][0]['order_id'] == wydane


@pytest.mark.parametrize('body', [
    {'order_ids': [], 'sposob': 'kurier_baselinker'},
    {'order_ids': [1], 'sposob': 'DPD'},
    {'order_ids': list(range(501)), 'sposob': 'kurier_baselinker'},
    # F1 (fix round 1): elementy order_ids inne niż int trafiały surowe do
    # Query.filter(ProductionOrder.id.in_(ids)) i SQLAlchemy rzucało
    # ProgrammingError z bazy (500) zamiast czystego 422.
    {'order_ids': [{'a': 1}], 'sposob': 'kurier_baselinker'},
    {'order_ids': ['abc'], 'sposob': 'kurier_baselinker'},
    {'order_ids': [None], 'sposob': 'kurier_baselinker'},
    {'order_ids': [True], 'sposob': 'kurier_baselinker'},
])
def test_walidacja_hurtu(client, body):
    assert client.post(BASE + '/orders/delivery-method', json=body).status_code == 422


def test_wydane_klientowi(client, app):
    with app.app_context():
        oid = zamowienie(sposob=s.ODBIOR, statusy=('spakowane',)).id
        nie = zamowienie(sposob=s.KURIER, statusy=('spakowane',)).id
    r = client.post(BASE + '/orders/%d/handed-over' % oid)
    assert r.status_code == 200 and r.get_json()['order']['wydane'] is not None
    r = client.post(BASE + '/orders/%d/handed-over' % nie)
    assert r.status_code == 409 and r.get_json()['success'] is False


def test_zakladka_renderuje_sie(client):
    r = client.get(BASE + '/tab-content')
    assert r.status_code == 200
    assert b'id="logistics-root"' in r.data
