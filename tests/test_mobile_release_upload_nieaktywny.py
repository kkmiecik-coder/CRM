# -*- coding: utf-8 -*-
"""
Wgranie APK domyślnie tworzy release NIEAKTYWNY — od 2026-10-12 w zakładce produkcji „Urządzenia mobilne”
(/production/api/devices/releases), dawniej w Ustawieniach.

Tło: tablety pytają /api/mobile/app/version o najnowszy AKTYWNY release i same go instalują. Gdy upload tworzył
release od razu aktywny, wgranie APK oznaczało natychmiastowe wydanie na całą halę — nie dało się wgrać nowej wersji
appki z wyprzedzeniem. Release czeka nieaktywny, aż admin włączy przełącznik „Aktywny” albo zaznaczy „Aktywuj od razu”.
"""
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from extensions import db
from modules.production.models import MobileAppRelease
from modules.production.services.mobile_api_service import flaga_aktywacji, stream_apk_response
from modules.settings import settings_bp
from modules.users.models import User
from tests.urzadzenia_fixtures import BASE_PANELU as BASE, TABELE, Admin, aplikacja_panelu

ADMIN_EMAIL = 'admin@test.local'


@pytest.fixture()
def app(monkeypatch, tmp_path):
    app = aplikacja_panelu(monkeypatch, tmp_path, Admin)
    app.register_blueprint(settings_bp, url_prefix='/settings')
    with app.app_context():
        db.metadata.create_all(bind=db.engine, tables=TABELE)
        db.session.add(User(email=ADMIN_EMAIL, password='x', role='admin'))
        db.session.commit()
        yield app
        db.session.remove()


@pytest.fixture()
def admin(app):
    """Panel produkcji przepuszcza _Admin; Ustawienia (require_admin) czytają session['user_email']."""
    client = app.test_client()
    with client.session_transaction() as sess:
        sess['user_email'] = ADMIN_EMAIL
    return client


def _wgraj(client, version_code, **extra):
    dane = {
        'apk': (io.BytesIO(b'PK\x03\x04 apk ' + str(version_code).encode()), f'app-{version_code}.apk'),
        'version_code': str(version_code),
        'version_name': f'1.{version_code}.0',
        'release_notes': 'test',
    }
    dane.update(extra)
    return client.post(BASE + '/releases', data=dane, content_type='multipart/form-data')


def _wersja_dla_tabletu(client):
    resp = client.get('/api/mobile/app/version')
    assert resp.status_code == 200
    return resp.get_json()['version_code']


def test_upload_bez_zaznaczenia_tworzy_nieaktywny_release(admin):
    resp = _wgraj(admin, 7)
    assert resp.status_code == 201, resp.get_json()
    assert resp.get_json()['release']['is_active'] is False
    assert MobileAppRelease.query.filter_by(version_code=7).one().is_active is False
    assert _wersja_dla_tabletu(admin) == 0


def test_nieaktywny_upload_nie_przykrywa_aktywnej_wersji(admin):
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
    assert _wgraj(admin, 9).status_code == 201
    resp = _wgraj(admin, 9, activate='1')
    assert resp.status_code == 400
    assert MobileAppRelease.query.count() == 1


def test_pobranie_apk_nieaktywnego_release_zwraca_404(app, admin):
    assert _wgraj(admin, 10).status_code == 201

    with app.test_request_context('/api/mobile/app/apk?version=10'):
        odpowiedz, status = stream_apk_response(10)

    assert status == 404
    assert odpowiedz.get_json()['error'] == 'release_not_found'


def test_przelacznik_aktywny(app, admin):
    _wgraj(admin, 10)
    release = MobileAppRelease.query.filter_by(version_code=10).one()
    resp = admin.patch(f'{BASE}/releases/{release.id}/active', json={'is_active': True})
    assert resp.status_code == 200 and resp.get_json()['release']['is_active'] is True
    assert _wersja_dla_tabletu(admin) == 10
    # Po włączeniu plik APK jest już do pobrania.
    with app.test_request_context('/api/mobile/app/apk?version=10'):
        odpowiedz = stream_apk_response(10)
        assert odpowiedz.status_code == 200
        odpowiedz.close()
    assert admin.patch(f'{BASE}/releases/{release.id}/active', json={'is_active': 'tak'}).status_code == 400
    assert admin.patch(f'{BASE}/releases/999/active', json={'is_active': True}).status_code == 404


def test_ustawienia_przekierowuja_na_zakladke(admin):
    resp = admin.get('/settings/production-app')
    assert resp.status_code == 302
    assert resp.headers['Location'].endswith('/production/?tab=devices')


@pytest.mark.parametrize('metoda, adres', [
    ('POST', '/settings/api/mobile-releases/upload'), ('PATCH', '/settings/api/mobile-releases/1/active')])
def test_stare_koncowki_ustawien_nie_istnieja(admin, metoda, adres):
    assert admin.open(adres, method=metoda).status_code == 404


@pytest.mark.parametrize('wartosc,oczekiwane', [
    (None, False), ('', False), ('0', False), ('false', False), ('nie', False),
    ('1', True), ('true', True), ('on', True), (' TAK ', True),
])
def test_flaga_aktywacji(wartosc, oczekiwane):
    assert flaga_aktywacji(wartosc) is oczekiwane
