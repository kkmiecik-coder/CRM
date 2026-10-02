# -*- coding: utf-8 -*-
"""
Wgranie APK w Ustawieniach domyślnie tworzy release NIEAKTYWNY.

Tło: tablety pytają /api/mobile/app/version o najnowszy AKTYWNY release
i same go instalują. Gdy upload tworzył release od razu aktywny, wgranie APK
oznaczało natychmiastowe wydanie na całą halę — nie dało się wgrać nowej
wersji appki z wyprzedzeniem (np. przed wdrożeniem backendu, którego
wymaga). Teraz release czeka nieaktywny, aż admin włączy przełącznik
„Aktywny” w historii albo zaznaczy przy uploadzie „Aktywuj od razu”.
"""
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from flask import Flask
from sqlalchemy.pool import StaticPool

from extensions import db
from modules.production.models import MobileAppRelease
from modules.production.routers.mobile_api import mobile_api_bp
from modules.production.services.mobile_api_service import (
    flaga_aktywacji,
    stream_apk_response,
)
from modules.settings import settings_bp
from modules.users.models import User
# Importy rejestrujące mappery — configure_mappers() przy pierwszym query
# potrzebuje ich do rozwiązania relationshipów z modules/users/models.py.
# Wzorzec i uzasadnienie jak w tests/test_sawmill_hooks.py.
from modules.calculator.models import Multiplier  # noqa: F401
from modules.clients.models import Client  # noqa: F401
import modules.quotes.models  # noqa: F401


_TABLES = [User.__table__, MobileAppRelease.__table__]

ADMIN_EMAIL = 'admin@test.local'


@pytest.fixture()
def app(tmp_path):
    """Flask + SQLite in-memory z blueprintami ustawień i API mobilnego.
    instance_path w tmp_path — tam ląduje wgrany plik APK."""
    flask_app = Flask(__name__, instance_path=str(tmp_path / 'instance'))
    flask_app.config['SECRET_KEY'] = 'test-' + 'x' * 40
    flask_app.config['TESTING'] = True
    flask_app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
    flask_app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    flask_app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        'poolclass': StaticPool,
        'connect_args': {'check_same_thread': False},
    }
    db.init_app(flask_app)
    flask_app.register_blueprint(settings_bp, url_prefix='/settings')
    flask_app.register_blueprint(mobile_api_bp, url_prefix='/api/mobile')
    with flask_app.app_context():
        db.metadata.create_all(bind=db.engine, tables=_TABLES)
        db.session.add(User(email=ADMIN_EMAIL, password='x', role='admin'))
        db.session.commit()
        yield flask_app
        db.session.remove()


@pytest.fixture()
def admin(app):
    """Klient zalogowany jako admin (require_admin patrzy w session['user_email'])."""
    client = app.test_client()
    with client.session_transaction() as sess:
        sess['user_email'] = ADMIN_EMAIL
    return client


def _wgraj(client, version_code, **extra):
    dane = {
        'apk': (io.BytesIO(b'PK\x03\x04 apk ' + str(version_code).encode()),
                f'app-{version_code}.apk'),
        'version_code': str(version_code),
        'version_name': f'1.{version_code}.0',
        'release_notes': 'test',
    }
    dane.update(extra)
    return client.post('/settings/api/mobile-releases/upload', data=dane,
                       content_type='multipart/form-data')


def _wersja_dla_tabletu(client):
    resp = client.get('/api/mobile/app/version')
    assert resp.status_code == 200
    return resp.get_json()['version_code']


# ---- upload --------------------------------------------------------------

def test_upload_bez_zaznaczenia_tworzy_nieaktywny_release(admin):
    resp = _wgraj(admin, 7)

    assert resp.status_code == 201, resp.get_json()
    assert resp.get_json()['release']['is_active'] is False
    assert MobileAppRelease.query.filter_by(version_code=7).one().is_active is False
    # Tablety nie widzą nieaktywnego release'u.
    assert _wersja_dla_tabletu(admin) == 0


def test_nieaktywny_upload_nie_przykrywa_aktywnej_wersji(admin):
    """Starsza aktywna wersja zostaje tą, którą pobierają tablety."""
    assert _wgraj(admin, 5, activate='1').status_code == 201
    assert _wgraj(admin, 6).status_code == 201

    assert _wersja_dla_tabletu(admin) == 5


def test_upload_z_zaznaczeniem_tworzy_aktywny_release(admin):
    resp = _wgraj(admin, 8, activate='1')

    assert resp.status_code == 201, resp.get_json()
    assert resp.get_json()['release']['is_active'] is True
    assert MobileAppRelease.query.filter_by(version_code=8).one().is_active is True
    assert _wersja_dla_tabletu(admin) == 8


def test_nieaktywny_release_nadal_blokuje_ten_sam_version_code(admin):
    """versionCode musi rosnąć także względem nieaktywnych release'ów."""
    assert _wgraj(admin, 9).status_code == 201

    resp = _wgraj(admin, 9, activate='1')

    assert resp.status_code == 400
    assert MobileAppRelease.query.count() == 1


@pytest.mark.parametrize('wartosc,oczekiwane', [
    (None, False), ('', False), ('0', False), ('false', False), ('nie', False),
    ('1', True), ('true', True), ('on', True), (' TAK ', True),
])
def test_flaga_aktywacji(wartosc, oczekiwane):
    assert flaga_aktywacji(wartosc) is oczekiwane


# ---- pobieranie APK i przełącznik „Aktywny” -----------------------------

def test_pobranie_apk_nieaktywnego_release_zwraca_404(app, admin):
    assert _wgraj(admin, 10).status_code == 201

    with app.test_request_context('/api/mobile/app/apk?version=10'):
        resp, status = stream_apk_response(10)

    assert status == 404
    assert resp.get_json()['error'] == 'release_not_found'


def test_przelacznik_aktywuje_nowy_nieaktywny_release(app, admin):
    assert _wgraj(admin, 11).status_code == 201
    release_id = MobileAppRelease.query.filter_by(version_code=11).one().id

    resp = admin.patch(f'/settings/api/mobile-releases/{release_id}/active',
                       json={'is_active': True})

    assert resp.status_code == 200, resp.get_json()
    assert resp.get_json()['release']['is_active'] is True
    assert _wersja_dla_tabletu(admin) == 11
    # Po włączeniu plik APK jest już do pobrania.
    with app.test_request_context('/api/mobile/app/apk?version=11'):
        resp = stream_apk_response(11)
        assert resp.status_code == 200
        resp.close()
