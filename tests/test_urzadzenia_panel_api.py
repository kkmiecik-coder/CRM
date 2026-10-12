# -*- coding: utf-8 -*-
"""HTTP zakładki „Urządzenia mobilne” — /production/api/devices/* (spec 2026-10-12, sekcja 5)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from extensions import db
from modules.production.models import ProductionDevice
from tests.urzadzenia_fixtures import (
    BASE_PANELU as BASE, MAC_A, TABELE, Admin, Pracownik, aplikacja_panelu, urzadzenie,
)

KORZEN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KONCOWKI = [
    ('GET', '/tab-content'), ('GET', '/lista'), ('POST', '/<int:pk>/zatwierdz'), ('POST', '/<int:pk>/odrzuc'),
    ('POST', '/<int:pk>/zablokuj'), ('POST', '/<int:pk>/odblokuj'), ('PATCH', '/<int:pk>/nazwa'),
    ('POST', '/<int:pk>/przyjmij-mac'), ('GET', '/bez-mac'), ('POST', '/zablokuj-bez-mac'),
    ('POST', '/releases'), ('PATCH', '/releases/<int:release_id>/active'),
]


@pytest.fixture()
def admin(monkeypatch, tmp_path):
    app = aplikacja_panelu(monkeypatch, tmp_path, Admin)
    with app.app_context():
        db.metadata.create_all(bind=db.engine, tables=TABELE)
        yield app.test_client()
        db.session.remove()


@pytest.fixture()
def pracownik(monkeypatch, tmp_path):
    app = aplikacja_panelu(monkeypatch, tmp_path, Pracownik)
    with app.app_context():
        db.metadata.create_all(bind=db.engine, tables=TABELE)
        yield app.test_client()
        db.session.remove()


def test_zestaw_koncowek(admin):
    reguly = {(m, r.rule[len(BASE):]) for r in admin.application.url_map.iter_rules()
              if r.rule.startswith(BASE + '/') for m in r.methods - {'HEAD', 'OPTIONS'}}
    assert reguly == set(KONCOWKI)


def test_blueprint_zarejestrowany_w_app():
    with open(os.path.join(KORZEN, 'app.py'), encoding='utf-8') as f:
        zrodlo = f.read()
    assert 'from modules.production.routers.devices_panel import devices_panel_bp' in zrodlo
    assert "app.register_blueprint(devices_panel_bp, url_prefix='/production/api/devices')" in zrodlo


@pytest.mark.parametrize('metoda, sciezka', KONCOWKI)
def test_nie_admin_403(pracownik, metoda, sciezka):
    adres = BASE + sciezka.replace('<int:pk>', '1').replace('<int:release_id>', '1')
    assert pracownik.open(adres, method=metoda, json={}).status_code == 403


def test_lista_json(admin):
    urzadzenie('Z1', nazwa='Pakowanie 1')
    tresc = admin.get(BASE + '/lista').get_json()
    assert tresc['success'] is True
    assert [u['nazwa'] for u in tresc['urzadzenia']] == ['Pakowanie 1']


def test_zatwierdz_przez_http(admin):
    d = urzadzenie('P1', status='oczekuje', mac=MAC_A)
    r = admin.post(f'{BASE}/{d.id}/zatwierdz', json={'nazwa': 'Pakowanie 2'})
    assert (r.status_code, r.get_json()) == (200, {'success': True, 'zastapione': []})
    d = ProductionDevice.query.populate_existing().get(d.id)
    assert (d.status, d.device_name, d.approved_by) == ('zatwierdzone', 'Pakowanie 2', 1)


def test_odmowa_ma_format_panelu(admin):
    d = urzadzenie('Z1')
    r = admin.post(f'{BASE}/{d.id}/odrzuc')
    assert r.status_code == 409
    assert r.get_json()['success'] is False and r.get_json()['error'] == 'stan_zmieniony'
    assert r.get_json()['message']


def test_brak_urzadzenia_404(admin):
    r = admin.post(f'{BASE}/999/zablokuj')
    assert (r.status_code, r.get_json()['error']) == (404, 'nie_znaleziono')


@pytest.mark.parametrize('cialo', [{}, {'ids': 'x'}, {'ids': [1, 'a']}, {'ids': [True]}])
def test_zablokuj_bez_mac_waliduje_ids(admin, cialo):
    r = admin.post(BASE + '/zablokuj-bez-mac', json=cialo)
    assert (r.status_code, r.get_json()['error']) == (400, 'ids_niepoprawne')


def test_zablokuj_bez_mac(admin):
    d = urzadzenie('BEZ', mac=None)
    r = admin.post(BASE + '/zablokuj-bez-mac', json={'ids': [d.id]})
    assert r.get_json() == {'success': True, 'zablokowane': [d.id], 'pominiete': []}


def test_zakladka_html(admin):
    urzadzenie('TAJNE-URZ-ID-77', status='oczekuje', mac=MAC_A)
    r = admin.get(BASE + '/tab-content')
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    for tekst in ('Prośby o dostęp', 'Urządzenia', 'Zablokowane', 'Wgraj nowy release', 'apkUploadForm', MAC_A):
        assert tekst in html
    assert 'TAJNE-URZ-ID-77' not in html   # device_id nie trafia do przeglądarki
