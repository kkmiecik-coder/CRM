"""Testy endpointu tokena realtime i throttlingu sprzątania kolejki wydruków."""
import os
import sys

import jwt
import pytest
from flask import Flask

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.production.routers.api import print_agent_api

AGENT_TOKEN = 'agent-token-z-prod-config'
REALTIME_CONFIG = {
    'enabled': True,
    'api_key': 'test-key',
    'token_hmac_secret': 'test-secret',
    'token_ttl_seconds': 3600,
    'sse_url': 'https://crm.woodpower.pl/realtime/connection/uni_sse',
}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(print_agent_api, '_get_agent_token', lambda: AGENT_TOKEN)
    app = Flask(__name__)
    app.config['REALTIME'] = dict(REALTIME_CONFIG)
    app.register_blueprint(print_agent_api.print_agent_bp, url_prefix='/api/print-agent')
    return app.test_client()


def _auth(token=AGENT_TOKEN):
    return {'Authorization': f'Bearer {token}'}


def test_token_wymaga_bearera(client):
    assert client.get('/api/print-agent/realtime-token').status_code == 401


def test_token_odrzuca_zly_bearer(client):
    resp = client.get('/api/print-agent/realtime-token', headers=_auth('nie-ten-token'))
    assert resp.status_code == 401


def test_token_zwraca_jwt_z_kanalem(client):
    resp = client.get('/api/print-agent/realtime-token', headers=_auth())
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['enabled'] is True
    assert data['channel'] == 'print:agent'
    assert data['sse_url'] == REALTIME_CONFIG['sse_url']
    assert data['expires_in'] == 3600

    claims = jwt.decode(data['token'], 'test-secret', algorithms=['HS256'])
    assert claims['channels'] == ['print:agent']


def test_token_503_gdy_realtime_wylaczony(client, monkeypatch):
    monkeypatch.setattr(print_agent_api.realtime_service, 'is_enabled', lambda: False)
    resp = client.get('/api/print-agent/realtime-token', headers=_auth())
    # 503 to dla agenta sygnał "jedź na pollingu", a nie awaria do zalogowania.
    assert resp.status_code == 503
    assert resp.get_json()['enabled'] is False


def test_token_503_gdy_brak_sekretu(monkeypatch):
    monkeypatch.setattr(print_agent_api, '_get_agent_token', lambda: AGENT_TOKEN)
    app = Flask(__name__)
    app.config['REALTIME'] = dict(REALTIME_CONFIG, token_hmac_secret='')
    app.register_blueprint(print_agent_api.print_agent_bp, url_prefix='/api/print-agent')

    resp = app.test_client().get('/api/print-agent/realtime-token', headers=_auth())
    assert resp.status_code == 503


# === Throttling sprzątania wygasłych zadań ===

class _FakeColumn:
    """Kolumna, którą da się porównać bez SQLAlchemy."""
    def __eq__(self, other):
        return True

    def __lt__(self, other):
        return True

    def __hash__(self):
        return 0


class _FakeQuery:
    def __init__(self, counter):
        self._counter = counter

    def filter(self, *args, **kwargs):
        return self

    def update(self, *args, **kwargs):
        self._counter.append(1)
        return 0


@pytest.fixture
def expire_calls(monkeypatch):
    calls = []

    class _FakeModel:
        status = _FakeColumn()
        requested_at = _FakeColumn()
        query = _FakeQuery(calls)

    monkeypatch.setattr(print_agent_api, 'LabelPrintJob', _FakeModel)
    monkeypatch.setattr(print_agent_api, '_last_expire_at', None)
    return calls


def test_sprzatanie_nie_powtarza_sie_w_kolko(expire_calls):
    """TTL to godzina — przy sygnale push /jobs potrafi być wołane kilkanaście
    razy w minutę i każde z nich robiło UPDATE."""
    for _ in range(10):
        print_agent_api._expire_stale_pending()

    assert len(expire_calls) == 1


def test_swiezy_worker_sprzata_od_razu(expire_calls):
    """time.monotonic() bywa liczone od startu procesu — zero jako 'dawno temu'
    uciszałoby sprzątanie przez pierwszą minutę życia workera."""
    print_agent_api._expire_stale_pending()
    assert len(expire_calls) == 1


def test_sprzatanie_wykonuje_sie_po_uplywie_throttle(expire_calls, monkeypatch):
    print_agent_api._expire_stale_pending()
    assert len(expire_calls) == 1

    # Symulujemy upływ czasu, cofając znacznik ostatniego przebiegu.
    monkeypatch.setattr(
        print_agent_api, '_last_expire_at',
        print_agent_api._last_expire_at - print_agent_api._EXPIRE_THROTTLE_SECONDS - 1,
    )
    print_agent_api._expire_stale_pending()
    assert len(expire_calls) == 2


def test_force_omija_throttle(expire_calls):
    print_agent_api._expire_stale_pending()
    print_agent_api._expire_stale_pending(force=True)
    assert len(expire_calls) == 2
