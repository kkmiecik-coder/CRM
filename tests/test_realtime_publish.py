"""Testy sygnału realtime (Centrifugo) — publish nie może wywrócić akcji operatora."""
import os
import sys

import pytest
from flask import Flask

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.production.services import realtime_service


def _app(realtime_config):
    app = Flask(__name__)
    app.config['REALTIME'] = realtime_config
    return app


ENABLED_CONFIG = {
    'enabled': True,
    'api_url': 'http://127.0.0.1:8091/api/publish',
    'api_key': 'test-key',
    'token_hmac_secret': 'test-secret',
    'token_ttl_seconds': 900,
    'sse_url': 'https://crm.woodpower.pl/realtime/connection/uni_sse',
}


class _FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = {} if payload is None else payload
        self.content = b'{}'

    def json(self):
        return self._payload


@pytest.fixture(autouse=True)
def _reset_failure_counter():
    realtime_service._consecutive_failures = 0
    yield
    realtime_service._consecutive_failures = 0


def test_publish_wylaczony_nie_wola_http(monkeypatch):
    called = []
    monkeypatch.setattr(realtime_service.requests, 'post', lambda *a, **kw: called.append(1))

    with _app({'enabled': False}).app_context():
        assert realtime_service.publish('print:agent', {'kind': 'print'}) is False
    assert called == []


def test_publish_wysyla_kanal_i_klucz(monkeypatch):
    captured = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        captured.update(url=url, json=json, headers=headers, timeout=timeout)
        return _FakeResponse()

    monkeypatch.setattr(realtime_service.requests, 'post', fake_post)

    with _app(ENABLED_CONFIG).app_context():
        assert realtime_service.publish_print_signal(3) is True

    assert captured['url'] == 'http://127.0.0.1:8091/api/publish'
    assert captured['json'] == {'channel': 'print:agent', 'data': {'kind': 'print', 'count': 3}}
    assert captured['headers']['X-API-Key'] == 'test-key'
    # Krótki timeout to wymóg, nie detal: zawieszony broker nie może zawiesić
    # kliknięcia operatora.
    connect_timeout, read_timeout = captured['timeout']
    assert connect_timeout <= 1.0 and read_timeout <= 2.0


def test_publish_nie_rzuca_gdy_broker_padl(monkeypatch):
    def boom(*args, **kwargs):
        raise OSError('connection refused')

    monkeypatch.setattr(realtime_service.requests, 'post', boom)

    with _app(ENABLED_CONFIG).app_context():
        assert realtime_service.publish('print:agent', {'kind': 'print'}) is False


def test_publish_nie_rzuca_gdy_timeout(monkeypatch):
    def hang(*args, **kwargs):
        raise TimeoutError('read timed out')

    monkeypatch.setattr(realtime_service.requests, 'post', hang)

    with _app(ENABLED_CONFIG).app_context():
        assert realtime_service.publish('print:agent', {'kind': 'print'}) is False


def test_publish_traktuje_blad_w_ciele_jako_porazke(monkeypatch):
    """Centrifugo zwraca HTTP 200 także dla błędów logicznych (np. nieznany
    namespace kanału) — błąd siedzi w ciele odpowiedzi."""
    monkeypatch.setattr(
        realtime_service.requests, 'post',
        lambda *a, **kw: _FakeResponse(200, {'error': {'code': 102, 'message': 'unknown channel'}}),
    )

    with _app(ENABLED_CONFIG).app_context():
        assert realtime_service.publish('nieznany:kanal', {'kind': 'print'}) is False


def test_publish_bez_klucza_api_nie_wola_http(monkeypatch):
    called = []
    monkeypatch.setattr(realtime_service.requests, 'post', lambda *a, **kw: called.append(1))

    cfg = dict(ENABLED_CONFIG, api_key='')
    with _app(cfg).app_context():
        assert realtime_service.publish('print:agent', {'kind': 'print'}) is False
    assert called == []


def test_alert_do_sentry_tylko_przy_pierwszej_awarii(monkeypatch):
    alerts = []
    monkeypatch.setattr(realtime_service, '_alert', lambda msg, extra: alerts.append(msg))
    monkeypatch.setattr(realtime_service.requests, 'post',
                        lambda *a, **kw: (_ for _ in ()).throw(OSError('down')))

    with _app(ENABLED_CONFIG).app_context():
        for _ in range(5):
            realtime_service.publish('print:agent', {'kind': 'print'})

    assert len(alerts) == 1, 'seria wydruków przy padniętym brokerze nie może zalać Sentry'


def test_licznik_awarii_resetuje_sie_po_sukcesie(monkeypatch):
    with _app(ENABLED_CONFIG).app_context():
        monkeypatch.setattr(realtime_service.requests, 'post',
                            lambda *a, **kw: (_ for _ in ()).throw(OSError('down')))
        realtime_service.publish('print:agent', {'kind': 'print'})
        assert realtime_service._consecutive_failures == 1

        monkeypatch.setattr(realtime_service.requests, 'post', lambda *a, **kw: _FakeResponse())
        realtime_service.publish('print:agent', {'kind': 'print'})
        assert realtime_service._consecutive_failures == 0


def test_token_ma_kanal_i_wygasa(monkeypatch):
    import jwt

    with _app(ENABLED_CONFIG).app_context():
        token, ttl = realtime_service.issue_connection_token('print-agent', ['print:agent'])

    assert ttl == 900
    claims = jwt.decode(token, 'test-secret', algorithms=['HS256'])
    assert claims['sub'] == 'print-agent'
    # Kanały muszą przyjechać w tokenie — klient unidirectional nie umie
    # subskrybować sam.
    assert claims['channels'] == ['print:agent']
    assert claims['exp'] - claims['iat'] == 900


def test_token_bez_sekretu_rzuca():
    with _app(dict(ENABLED_CONFIG, token_hmac_secret='')).app_context():
        with pytest.raises(RuntimeError):
            realtime_service.issue_connection_token('print-agent', ['print:agent'])
