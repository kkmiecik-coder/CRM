# -*- coding: utf-8 -*-
from datetime import date
from types import SimpleNamespace as NS

import pytest

from modules.production.logistics import sposoby as s


@pytest.mark.parametrize('wartosc, oczekiwane', [
    (None, None), ('', None), ('  kurier_baselinker ', 'kurier_baselinker'),
    ('transport_woodpower', 'transport_woodpower'), ('odbior_osobisty', 'odbior_osobisty'),
    ('DPD', None),
])
def test_normalizuj(wartosc, oczekiwane):
    assert s.normalizuj(wartosc) == oczekiwane


def test_etykiety():
    assert s.etykieta(None) == 'Nie ustawiono'
    assert s.etykieta(s.KURIER) == 'Kurier'
    assert s.etykieta(s.ODBIOR) == 'Odbiór osobisty'
    assert s.etykieta(s.TRANSPORT) == 'Transport WoodPower'
    assert s.etykieta(s.TRANSPORT, nazwa_trasy='Kraków + Tarnów') == 'Kraków + Tarnów'
    # Nazwa trasy nie przykrywa innego sposobu.
    assert s.etykieta(s.KURIER, nazwa_trasy='Kraków') == 'Kurier'


def test_legacy_delivery_type_ma_tylko_stare_wartosci():
    assert s.legacy_delivery_type(None) == 'courier'
    assert s.legacy_delivery_type(s.KURIER) == 'courier'
    assert s.legacy_delivery_type(s.TRANSPORT) == 'transport_woodpower'
    assert s.legacy_delivery_type(s.ODBIOR) == 'personal_pickup'


def test_transport_bez_sposobu_i_bez_trasy():
    order = NS(override_delivery_method=None, repack_required=False)
    assert s.transport_payload(order) == {
        'mode': None, 'trip_name': None, 'trip_date': None,
        'vehicle_name': None, 'repack_required': False}


def test_transport_z_trasa_i_przepakowaniem():
    order = NS(override_delivery_method=s.TRANSPORT, repack_required=True)
    trasa = NS(name='Kraków + Tarnów', date_from=date(2026, 9, 30),
               vehicle=NS(name='Iveco KR 12345'))
    assert s.transport_payload(order, trasa) == {
        'mode': 'wlasny', 'trip_name': 'Kraków + Tarnów', 'trip_date': '2026-09-30',
        'vehicle_name': 'Iveco KR 12345', 'repack_required': True}


def test_transport_dla_braku_zamowienia_to_nadal_obiekt():
    """Nowy backend ZAWSZE wysyła obiekt — appka odróżnia po nim stary backend."""
    assert s.transport_payload(None)['mode'] is None


def test_statusy_po_spakowaniu():
    assert s.STATUS_PO_SPAKOWANIU == {s.KURIER: 138623, s.TRANSPORT: 417343, s.ODBIOR: 149777}


@pytest.mark.parametrize('metoda, pickup, oczekiwane', [
    ('Odbiór osobisty', True, 'odbior_osobisty'),
    ('Transport WoodPower', False, 'transport_woodpower'),
    ('dopłata za nasz transport 350 zł', False, 'transport_woodpower'),
    ('Transport własny', False, 'transport_woodpower'),
    ('Kurier', False, 'kurier_baselinker'),
    ('InPost-Kurier', False, 'kurier_baselinker'),
])
def test_podpowiedz_z_base(metoda, pickup, oczekiwane):
    order = NS(delivery_method=metoda, is_personal_pickup=pickup)
    assert s.podpowiedz(order) == oczekiwane
