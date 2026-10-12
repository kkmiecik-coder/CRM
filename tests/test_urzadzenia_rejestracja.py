# -*- coding: utf-8 -*-
"""POST /api/mobile/register — maszyna stanów (spec 2026-10-12, sekcja 4; kontrakt, sekcja 3)."""
import os
import sys
from datetime import timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from extensions import db
from modules.production.models import ProductionDevice, get_local_now
from modules.production.services import device_access_service as dostep
from modules.production.services.mobile_api_service import validate_token
from tests.urzadzenia_fixtures import MAC_A, MAC_B, app, client, urzadzenie  # noqa: F401

URL = '/api/mobile/register'
_BRAK = object()


def _cialo(**zmiany):
    cialo = {'device_id': 'TAB-NOWY', 'device_name': 'Pakowanie 1', 'station_code': 'packaging',
             'mac_address': 'a4-50-46-00-00-0a', 'device_model': 'BAH2-W19'}
    cialo.update(zmiany)
    return {k: v for k, v in cialo.items() if v is not _BRAK}


def _wiersz(device_id='TAB-NOWY'):
    return ProductionDevice.query.filter_by(device_id=device_id).populate_existing().first()


def test_nowe_urzadzenie_zaklada_prosbe(client):
    r = client.post(URL, json=_cialo(), headers={'X-App-Version': '1.9.0'})
    assert r.status_code == 202, r.get_json()
    assert r.get_json() == {'status': 'pending', 'device_id': 'TAB-NOWY', 'mac_address': MAC_A, 'retry_after_s': 5}
    d = _wiersz()
    assert (d.status, d.is_active, d.mac_address, d.device_model, d.device_name, d.station_code, d.app_version) == (
        'oczekuje', False, MAC_A, 'BAH2-W19', 'Pakowanie 1', 'packaging', '1.9.0')
    assert d.requested_at is not None and d.last_ip


def test_odpytywanie_odswieza_prosbe(client):
    stara = get_local_now() - timedelta(days=2)
    urzadzenie('TAB-NOWY', status='oczekuje', mac=MAC_A, nazwa='stara', requested_at=stara)
    r = client.post(URL, json=_cialo(station_code='gluing', device_name='Sklejanie 2'))
    assert r.status_code == 202
    d = _wiersz()
    assert (d.station_code, d.device_name, d.status) == ('gluing', 'Sklejanie 2', 'oczekuje')
    assert d.requested_at > stara


def test_zatwierdzone_dostaje_token_zmienia_stanowisko_nie_nazwe(app, client):
    urzadzenie('TAB-1', station_code='packaging', nazwa='Pakowanie 1 (admin)', mac=MAC_A)
    r = client.post(URL, json=_cialo(device_id='TAB-1', station_code='gluing', device_name='gg'))
    assert r.status_code == 200, r.get_json()
    tresc = r.get_json()
    assert (tresc['status'], tresc['device_id'], tresc['station_code'], tresc['device_name']) == (
        'approved', 'TAB-1', 'gluing', 'Pakowanie 1 (admin)')
    device, _claims = validate_token(tresc['token'])
    assert device.device_id == 'TAB-1'
    assert (_wiersz('TAB-1').device_name, _wiersz('TAB-1').station_code) == ('Pakowanie 1 (admin)', 'gluing')


def test_stara_appka_bez_mac_na_zatwierdzonym_dostaje_token(client):
    urzadzenie('TAB-1')
    r = client.post(URL, json=_cialo(device_id='TAB-1', mac_address=_BRAK, device_model=_BRAK))
    assert r.status_code == 200
    assert _wiersz('TAB-1').mac_address is None


def test_zatwierdzone_uzupelnia_mac(client):
    urzadzenie('TAB-1', mac=None)
    assert client.post(URL, json=_cialo(device_id='TAB-1')).status_code == 200
    assert _wiersz('TAB-1').mac_address == MAC_A


def test_zatwierdzone_z_innym_mac_ma_konflikt(client):
    urzadzenie('TAB-1', mac=MAC_B)
    assert client.post(URL, json=_cialo(device_id='TAB-1')).status_code == 200
    d = _wiersz('TAB-1')
    assert (d.mac_address, d.mac_conflict) == (MAC_B, MAC_A)


def test_zablokowane_403_i_bez_zmian(client):
    urzadzenie('TAB-1', status='zablokowane', station_code='packaging', token_version=3)
    r = client.post(URL, json=_cialo(device_id='TAB-1', station_code='gluing'))
    assert r.status_code == 403
    assert r.get_json() == {'error': 'device_blocked', 'retry_after_s': 30}
    d = _wiersz('TAB-1')
    assert (d.status, d.is_active, d.station_code, d.token_version) == ('zablokowane', False, 'packaging', 3)


def test_niespojny_wiersz_po_wycofaniu_jest_zablokowany(client):
    """Stary kod mógł ustawić is_active = 1 na zablokowanym — status i tak wygrywa."""
    d = urzadzenie('TAB-1', status='zablokowane')
    d.is_active = True
    db.session.commit()
    assert client.post(URL, json=_cialo(device_id='TAB-1')).status_code == 403


def test_nowe_bez_mac_400(client):
    r = client.post(URL, json=_cialo(mac_address=_BRAK))
    assert (r.status_code, r.get_json()) == (400, {'error': 'mac_required'})
    assert _wiersz() is None


def test_oczekujace_bez_mac_400(client):
    urzadzenie('TAB-NOWY', status='oczekuje', mac=MAC_A)
    r = client.post(URL, json=_cialo(mac_address=_BRAK))
    assert (r.status_code, r.get_json()) == (400, {'error': 'mac_required'})


@pytest.mark.parametrize('mac', ['02:00:00:00:00:00', 'nie-mac', 5])
def test_zly_mac_400(client, mac):
    r = client.post(URL, json=_cialo(mac_address=mac))
    assert (r.status_code, r.get_json()) == (400, {'error': 'mac_invalid'})


@pytest.mark.parametrize('cialo', [
    {'device_id': 123, 'station_code': 'packaging', 'mac_address': MAC_A},
    {'device_id': 'TAB-X', 'station_code': ['packaging'], 'mac_address': MAC_A},
    [1, 2, 3],
    'tekst',
])
def test_pola_nie_tekstowe_400(client, cialo):
    """Review Focus 1: śmieciowe typy w body to 400, nigdy 500."""
    r = client.post(URL, json=cialo)
    assert r.status_code == 400
    assert r.get_json()['error'] == 'missing_fields'


@pytest.mark.parametrize('pole, wartosc', [
    ('device_id', 'x' * 65), ('device_name', 'x' * 129), ('device_model', 'x' * 65)])
def test_za_dlugie_pole_400(client, pole, wartosc):
    r = client.post(URL, json=_cialo(**{pole: wartosc}))
    assert (r.status_code, r.get_json()) == (400, {'error': 'field_too_long', 'field': pole})


def test_limit_oczekujacych_429(client):
    for i in range(dostep.MAX_OCZEKUJACYCH):
        urzadzenie(f'CZEKA-{i}', status='oczekuje', mac=MAC_B)
    r = client.post(URL, json=_cialo())
    assert (r.status_code, r.get_json()) == (429, {'error': 'too_many_pending', 'retry_after_s': 60})
    assert ProductionDevice.query.filter_by(status='oczekuje').count() == dostep.MAX_OCZEKUJACYCH


def test_przeterminowane_zwalniaja_limit(client):
    dawno = get_local_now() - timedelta(days=dostep.WAZNOSC_PROSBY_DNI + 1)
    for i in range(dostep.MAX_OCZEKUJACYCH):
        urzadzenie(f'CZEKA-{i}', status='oczekuje', mac=MAC_B, requested_at=dawno)
    assert client.post(URL, json=_cialo()).status_code == 202
    assert ProductionDevice.query.filter_by(status='oczekuje').count() == 1


def test_wyscig_dwoch_pierwszych_zadan(client, monkeypatch):
    """Równoległe pierwsze żądanie zdążyło założyć wiersz — nasz INSERT dostaje IntegrityError, odpowiadamy wg stanu."""
    def rownolegla_prosba(teraz=None):
        db.session.add(ProductionDevice(device_id='TAB-NOWY', station_code='packaging', status='oczekuje',
                                        is_active=False, mac_address=MAC_A, requested_at=get_local_now()))
        db.session.commit()
        return 0
    monkeypatch.setattr(dostep, 'usun_przeterminowane_prosby', rownolegla_prosba)
    r = client.post(URL, json=_cialo())
    assert r.status_code == 202, r.get_json()
    assert ProductionDevice.query.filter_by(device_id='TAB-NOWY').count() == 1


def test_nieznany_kod_stanowiska_przed_mac(client):
    r = client.post(URL, json=_cialo(station_code='wykanczanie', mac_address=_BRAK))
    assert (r.status_code, r.get_json()['error']) == (400, 'invalid_station_code')
