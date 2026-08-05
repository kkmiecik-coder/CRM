# -*- coding: utf-8 -*-
"""API panelu trakowni — słowniki i tworzenie dostaw."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from decimal import Decimal

from extensions import db
from modules.production.sawmill.models import (
    SawmillAudit, SawmillDelivery, SawmillOrder, SawmillSupplier,
)
from tests.sawmill_fixtures import BASE, app, client  # noqa: F401


def test_lista_gatunkow(client):
    r = client.get(BASE + '/species')
    assert r.status_code == 200
    assert [s['name'] for s in r.get_json()['species']] == ['Dąb']


def test_dodanie_dostawcy(client):
    r = client.post(BASE + '/suppliers', json={
        'name': 'Tartak Nowak sp. z o.o.', 'nip': '1234567890',
        'address_city': 'Kielce', 'phone': '600100200',
    })
    assert r.status_code == 201
    assert r.get_json()['supplier']['name'] == 'Tartak Nowak sp. z o.o.'


def test_dostawca_bez_nazwy_odrzucony(client):
    r = client.post(BASE + '/suppliers', json={'nip': '1234567890'})
    assert r.status_code == 422
    assert r.get_json()['field'] == 'name'


def test_duplikat_nazwy_dostawcy(client):
    client.post(BASE + '/suppliers', json={'name': 'Tartak Nowak'})
    r = client.post(BASE + '/suppliers', json={'name': 'Tartak Nowak'})
    assert r.status_code == 422


def test_kasowanie_dostawcy_jest_miekkie(client, app):
    r = client.post(BASE + '/suppliers', json={'name': 'Tartak Do Usuniecia'})
    sid = r.get_json()['supplier']['id']
    assert client.delete(BASE + '/suppliers/{}'.format(sid)).status_code == 200
    with app.app_context():
        dostawca = db.session.query(SawmillSupplier).get(sid)
        assert dostawca is not None
        assert dostawca.is_active is False


def test_nieaktywni_nie_sa_na_domyslnej_liscie(client):
    r = client.post(BASE + '/suppliers', json={'name': 'Nieaktywny'})
    sid = r.get_json()['supplier']['id']
    client.delete(BASE + '/suppliers/{}'.format(sid))
    nazwy = [s['name'] for s in client.get(BASE + '/suppliers').get_json()['suppliers']]
    assert 'Nieaktywny' not in nazwy


def _dostawca(client):
    return client.post(BASE + '/suppliers', json={'name': 'Tartak Nowak'}).get_json()['supplier']['id']


def _gatunek(client):
    return client.get(BASE + '/species').get_json()['species'][0]['id']


def test_dostawa_z_jedna_pozycja(client, app):
    r = client.post(BASE + '/deliveries', json={
        'supplier_id': _dostawca(client),
        'delivery_date': '2026-08-05',
        'invoice_number': 'FV/2026/0451',
        'invoice_date': '2026-08-04',
        'items': [{'species_id': _gatunek(client), 'declared_volume_m3': '80.000',
                   'declared_logs_count': 120, 'price_per_m3': '1200.00'}],
    })
    assert r.status_code == 201
    orders = r.get_json()['orders']
    assert len(orders) == 1
    assert orders[0]['order_number'] == 'TRK/2026/001'
    with app.app_context():
        # declared_value liczy serwer, nie przeglądarka.
        assert db.session.query(SawmillOrder).first().declared_value == Decimal('96000.00')


def test_dostawa_z_wieloma_pozycjami_daje_wiele_zlecen(client):
    r = client.post(BASE + '/deliveries', json={
        'supplier_id': _dostawca(client),
        'delivery_date': '2026-08-05',
        'items': [
            {'species_id': _gatunek(client), 'declared_volume_m3': '40.000'},
            {'species_id': _gatunek(client), 'declared_volume_m3': '30.000'},
        ],
    })
    assert r.status_code == 201
    assert [o['order_number'] for o in r.get_json()['orders']] == [
        'TRK/2026/001', 'TRK/2026/002']


def test_dostawa_bez_faktury_jest_ok(client):
    r = client.post(BASE + '/deliveries', json={
        'supplier_id': _dostawca(client),
        'delivery_date': '2026-08-05',
        'items': [{'species_id': _gatunek(client), 'declared_volume_m3': '40.000'}],
    })
    assert r.status_code == 201


def test_dostawa_bez_pozycji_odrzucona(client):
    r = client.post(BASE + '/deliveries', json={
        'supplier_id': _dostawca(client), 'delivery_date': '2026-08-05', 'items': [],
    })
    assert r.status_code == 422
    assert r.get_json()['field'] == 'items'


def test_pozycja_bez_deklaracji_odrzucona(client):
    r = client.post(BASE + '/deliveries', json={
        'supplier_id': _dostawca(client), 'delivery_date': '2026-08-05',
        'items': [{'species_id': _gatunek(client)}],
    })
    assert r.status_code == 422
    assert r.get_json()['field'] == 'declared_volume_m3'


def test_korekta_numeru_faktury_zapisuje_audyt(client, app):
    r = client.post(BASE + '/deliveries', json={
        'supplier_id': _dostawca(client), 'delivery_date': '2026-08-05',
        'invoice_number': 'FV/2026/0451',
        'items': [{'species_id': _gatunek(client), 'declared_volume_m3': '40.000'}],
    })
    did = r.get_json()['delivery']['id']
    r = client.patch(BASE + '/deliveries/{}'.format(did),
                     json={'invoice_number': 'FV/2026/0452'})
    assert r.status_code == 200
    with app.app_context():
        wpis = SawmillAudit.query.filter_by(action='delivery_update').first()
        assert wpis is not None
        assert '0452' in wpis.after_json


def test_bledna_druga_pozycja_nie_zostawia_smieci_w_bazie(client, app):
    """
    Weryfikacja rollbacku z delivery_create: błąd na DRUGIEJ pozycji (po tym,
    jak pierwsza już przeszła flush) nie może zostawić osieroconej dostawy
    ani pojedynczego zlecenia w bazie — cała dostawa jest odrzucana w całości.
    """
    r = client.post(BASE + '/deliveries', json={
        'supplier_id': _dostawca(client), 'delivery_date': '2026-08-05',
        'items': [
            {'species_id': _gatunek(client), 'declared_volume_m3': '40.000'},
            {'species_id': _gatunek(client)},  # brak declared_volume_m3
        ],
    })
    assert r.status_code == 422
    with app.app_context():
        assert db.session.query(SawmillDelivery).count() == 0
        assert db.session.query(SawmillOrder).count() == 0


def test_numer_zlecenia_nie_jest_tracony_po_nieudanej_probie(client):
    """
    next_order_number() rezerwuje numer bez commitu. Po rollbacku nieudanej
    dostawy (druga pozycja błędna) numer wraca do puli — poprawiona dostawa
    dostaje TRK/2026/001, a nie 002.
    """
    supplier_id = _dostawca(client)
    species_id = _gatunek(client)

    zla = client.post(BASE + '/deliveries', json={
        'supplier_id': supplier_id, 'delivery_date': '2026-08-05',
        'items': [
            {'species_id': species_id, 'declared_volume_m3': '40.000'},
            {'species_id': species_id},
        ],
    })
    assert zla.status_code == 422

    dobra = client.post(BASE + '/deliveries', json={
        'supplier_id': supplier_id, 'delivery_date': '2026-08-05',
        'items': [{'species_id': species_id, 'declared_volume_m3': '40.000'}],
    })
    assert dobra.status_code == 201
    assert dobra.get_json()['orders'][0]['order_number'] == 'TRK/2026/001'
