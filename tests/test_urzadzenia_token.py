# -*- coding: utf-8 -*-
"""Uwierzytelnianie urządzeń: pole `reason` w 401, MAC w heartbeacie, brak whitelisty IP (spec 2026-10-12, sekcja 6)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from extensions import db
from modules.production.models import ProductionDevice
from modules.production.services import device_access_service as dostep
from modules.production.services import mobile_api_service
from modules.production.services.mobile_api_service import generate_token
from tests.urzadzenia_fixtures import MAC_A, MAC_B, app, client, urzadzenie  # noqa: F401

URL = '/api/mobile/devices/heartbeat'
HEARTBEAT = {'battery_pct': 80, 'app_version_code': 47, 'app_version_name': '1.9.0'}


def _heartbeat(client, token, **pola):
    return client.post(URL, json={**HEARTBEAT, **pola}, headers={'Authorization': 'Bearer ' + token})


def _odmowa(r):
    assert r.status_code == 401, r.get_data()[:300]
    return r.get_json()


def test_wygasly(app, client):
    d = urzadzenie()
    app.config['API_MOBILE']['jwt_expiry_days'] = -1
    token = generate_token(d)
    assert _odmowa(_heartbeat(client, token)) == {
        'error': 'invalid_token', 'detail': 'Token wygasł', 'reason': 'expired'}


def test_nieprawidlowy(client):
    tresc = _odmowa(_heartbeat(client, 'to-nie-jest-jwt'))
    assert tresc['reason'] == 'invalid' and tresc['detail'].startswith('Token nieprawidłowy: ')


def test_nieznane_urzadzenie(client):
    d = urzadzenie()
    token = generate_token(d)
    db.session.delete(d)
    db.session.commit()
    assert _odmowa(_heartbeat(client, token)) == {
        'error': 'invalid_token', 'detail': 'Urządzenie nieznane', 'reason': 'unknown_device'}


def test_uniewazniony(client):
    d = urzadzenie()
    token = generate_token(d)
    d.revoke_tokens()
    db.session.commit()
    assert _odmowa(_heartbeat(client, token)) == {
        'error': 'invalid_token', 'detail': 'Token unieważniony (token_version mismatch)', 'reason': 'token_revoked'}


def test_zablokowany_ma_blocked_a_nie_token_revoked(client):
    """Blokada podbija token_version — mimo to odpowiedź ma mówić „zablokowane”, nie zapraszać do re-rejestracji."""
    d = urzadzenie()
    token = generate_token(d)
    dostep.ustaw_status(d, 'zablokowane', user_id=1)
    db.session.commit()
    assert _odmowa(_heartbeat(client, token)) == {
        'error': 'invalid_token', 'detail': 'Urządzenie zablokowane', 'reason': 'blocked'}


def test_niespojny_wiersz_jest_zablokowany(client):
    d = urzadzenie()
    token = generate_token(d)
    d.status = 'zablokowane'   # is_active zostaje True — stan po „odblokowaniu” starym kodem
    db.session.commit()
    assert _odmowa(_heartbeat(client, token))['reason'] == 'blocked'


def test_zablokowany_heartbeat_nie_zapisuje_mac(client):
    """Review Focus 4."""
    d = urzadzenie(mac=MAC_A)
    token = generate_token(d)
    dostep.ustaw_status(d, 'zablokowane', user_id=1)
    db.session.commit()
    assert _odmowa(_heartbeat(client, token, mac_address=MAC_B))['reason'] == 'blocked'
    d = ProductionDevice.query.populate_existing().get(d.id)
    assert (d.mac_address, d.mac_conflict) == (MAC_A, None)


def test_heartbeat_uzupelnia_mac(client):
    d = urzadzenie(mac=None)
    assert _heartbeat(client, generate_token(d), mac_address='a4:50:46:00:00:0a').status_code == 204
    assert ProductionDevice.query.populate_existing().get(d.id).mac_address == MAC_A


def test_heartbeat_inny_mac_to_konflikt(client):
    d = urzadzenie(mac=MAC_A)
    assert _heartbeat(client, generate_token(d), mac_address=MAC_B).status_code == 204
    d = ProductionDevice.query.populate_existing().get(d.id)
    assert (d.mac_address, d.mac_conflict) == (MAC_A, MAC_B)


@pytest.mark.parametrize('mac', ['02:00:00:00:00:00', 'zly', 12, None])
def test_heartbeat_zly_mac_nie_psuje_heartbeatu(client, mac):
    d = urzadzenie(mac=None)
    assert _heartbeat(client, generate_token(d), mac_address=mac).status_code == 204
    assert ProductionDevice.query.populate_existing().get(d.id).mac_address is None


def test_whitelisty_ip_nie_ma(app, client):
    app.config['API_MOBILE']['require_ip_whitelist'] = True
    app.config['API_MOBILE']['ip_whitelist'] = ['10.0.0.0/8']
    assert _heartbeat(client, generate_token(urzadzenie())).status_code == 204
    assert not hasattr(mobile_api_service, '_ip_in_whitelist')
