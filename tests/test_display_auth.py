"""Tests for the display-monitor token decorator."""
import json
import pytest
from flask import Flask, jsonify

from modules.production.utils.display_auth import require_display_token


@pytest.fixture
def app(monkeypatch):
    """Minimal app with a mocked token store."""
    test_token = 'test-token-abc-123'

    def fake_get_token():
        return test_token

    monkeypatch.setattr(
        'modules.production.utils.display_auth._get_display_token',
        fake_get_token,
    )

    app = Flask(__name__)

    @app.route('/protected')
    @require_display_token
    def protected():
        return jsonify({'ok': True})

    app._test_token = test_token
    return app


def test_missing_authorization_header_returns_401(app):
    with app.test_client() as c:
        r = c.get('/protected')
        assert r.status_code == 401
        assert r.json['error'] == 'unauthorized'


def test_wrong_token_returns_401(app):
    with app.test_client() as c:
        r = c.get('/protected', headers={'Authorization': 'Bearer wrong'})
        assert r.status_code == 401


def test_non_bearer_scheme_returns_401(app):
    with app.test_client() as c:
        r = c.get('/protected', headers={'Authorization': 'Basic abc'})
        assert r.status_code == 401


def test_correct_token_passes(app):
    with app.test_client() as c:
        r = c.get('/protected', headers={'Authorization': f'Bearer {app._test_token}'})
        assert r.status_code == 200
        assert r.json == {'ok': True}


def test_empty_stored_token_rejects_any_request(app, monkeypatch):
    monkeypatch.setattr(
        'modules.production.utils.display_auth._get_display_token',
        lambda: '',
    )
    with app.test_client() as c:
        r = c.get('/protected', headers={'Authorization': 'Bearer anything'})
        assert r.status_code == 401
