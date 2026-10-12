# -*- coding: utf-8 -*-
"""Serwis dostępu urządzeń — MAC i statusy (spec 2026-10-12, 3.3)."""
import os
import sys
from datetime import timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from extensions import db
from modules.production.models import ProductionDevice, get_local_now
from modules.production.services import device_access_service as dostep
from tests.urzadzenia_fixtures import MAC_A, MAC_B, app, urzadzenie  # noqa: F401


@pytest.mark.parametrize('wejscie, wynik', [
    ('A4:50:46:00:00:0A', MAC_A),
    ('a4:50:46:00:00:0a', MAC_A),
    ('a4-50-46-00-00-0a', MAC_A),
    ('A4504600000A', MAC_A),
    ('  a4:50:46:00:00:0a  ', MAC_A),
    ('02:00:00:00:00:00', None),   # atrapa Androida dla zwykłej appki
    ('00:00:00:00:00:00', None),
    ('A4:50:46:00:00', None),      # za krótki
    ('A4:50:46:00:00:0A:0B', None),
    ('G4:50:46:00:00:0A', None),   # znak spoza hex
    ('', None),
    (None, None),
    (5, None),
    (['A4:50:46:00:00:0A'], None),
])
def test_normalizuj_mac(wejscie, wynik):
    assert dostep.normalizuj_mac(wejscie) == wynik


def test_ustaw_status_zatwierdzone(app):
    d = urzadzenie(status='oczekuje', mac=MAC_A)
    dostep.ustaw_status(d, 'zatwierdzone', user_id=7)
    assert (d.status, d.is_active, d.approved_by) == ('zatwierdzone', True, 7)
    assert d.approved_at is not None


def test_ustaw_status_zablokowane_podbija_wersje_tokenu(app):
    d = urzadzenie()
    wersja = d.token_version
    dostep.ustaw_status(d, 'zablokowane', user_id=7)
    assert (d.status, d.is_active, d.blocked_by) == ('zablokowane', False, 7)
    assert d.token_version == wersja + 1
    assert d.blocked_at is not None


def test_odblokowanie_czysci_blokade_i_zostawia_pierwsze_zatwierdzenie(app):
    d = urzadzenie()
    pierwsze = d.approved_at = get_local_now() - timedelta(days=30)
    dostep.ustaw_status(d, 'zablokowane', user_id=7)
    dostep.ustaw_status(d, 'zatwierdzone', user_id=8)
    assert d.approved_at == pierwsze
    assert (d.blocked_at, d.blocked_by) == (None, None)


def test_ustaw_status_nieznany(app):
    with pytest.raises(ValueError):
        dostep.ustaw_status(urzadzenie(), 'usuniete')


def test_zgloszony_mac_uzupelnia_pusty(app):
    d = urzadzenie(mac=None)
    dostep.zapisz_zgloszony_mac(d, MAC_A)
    assert (d.mac_address, d.mac_conflict) == (MAC_A, None)


def test_zgloszony_ten_sam_mac_bez_zmian(app):
    d = urzadzenie(mac=MAC_A)
    dostep.zapisz_zgloszony_mac(d, MAC_A)
    assert (d.mac_address, d.mac_conflict) == (MAC_A, None)


def test_zgloszony_inny_mac_to_konflikt_nie_nadpisanie(app):
    d = urzadzenie(mac=MAC_A)
    dostep.zapisz_zgloszony_mac(d, MAC_B)
    assert (d.mac_address, d.mac_conflict) == (MAC_A, MAC_B)


def test_zgloszony_brak_mac_nic_nie_robi(app):
    d = urzadzenie(mac=MAC_A)
    dostep.zapisz_zgloszony_mac(d, None)
    assert (d.mac_address, d.mac_conflict) == (MAC_A, None)


def test_usun_przeterminowane_prosby(app):
    teraz = get_local_now()
    urzadzenie('STARA', status='oczekuje', mac=MAC_A, requested_at=teraz - timedelta(days=8))
    urzadzenie('SWIEZA', status='oczekuje', mac=MAC_B, requested_at=teraz - timedelta(days=6))
    urzadzenie('ZATW', requested_at=teraz - timedelta(days=30))
    assert dostep.usun_przeterminowane_prosby() == 1
    db.session.commit()
    assert sorted(d.device_id for d in ProductionDevice.query.all()) == ['SWIEZA', 'ZATW']
