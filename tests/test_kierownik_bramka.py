# -*- coding: utf-8 -*-
"""Bramka tabletu kierownika hali (kontrakt §2.1) i biała lista pól odpowiedzi (spec 2.6).

Bramkę ćwiczy trasa testowa pod /test-kierownik — poza /api/mobile/manager, żeby test pełności listy endpointów
porównywał tylko prawdziwe trasy blueprintu."""
import pytest
from flask import Blueprint, g, jsonify

from extensions import db
from modules.production.kierownik.services import biala_lista
from modules.production.kierownik.services.bramka import wymaga_kierownika
from modules.production.models import ProductionDevice, ProductionWorker
from modules.production.services.mobile_api_service import require_device_token
from tests.kierownik_pomocnicze import API, ENDPOINTY_KIEROWNIKA, naglowki, tablet_kierownika
from tests.logistyka_fixtures import app, client  # noqa: F401

TESTOWA = '/test-kierownik/gate'


@pytest.fixture()
def bramka(app):
    """Trasa testowa za require_device_token → wymaga_kierownika; zwraca to, co bramka ustawiła w `g`."""
    bp = Blueprint('test_kierownik_bramka', __name__)

    @bp.route('/gate')
    @require_device_token
    @wymaga_kierownika
    def gate():
        return jsonify({'kierownik_id': g.kierownik.id, 'worker_ids': g.worker_ids})

    app.register_blueprint(bp, url_prefix='/test-kierownik')
    return app


def _odmowa(r, status, kod):
    assert r.status_code == status and r.get_json()['error'] == kod, r.get_data()[:300]
    assert r.get_json()['message']   # zdanie po polsku do pokazania


def test_bramka_inne_stanowisko_403(bramka, client):
    _device, k = tablet_kierownika()
    obcy = ProductionDevice(device_id='TAB-OBCY', device_name='Formatowanie', station_code='formatting')
    db.session.add(obcy)
    db.session.commit()
    _odmowa(client.get(TESTOWA, headers=naglowki(obcy, k)), 403, 'station_not_allowed')


def test_bramka_bez_naglowka_pracownika_400(bramka, client):
    device, _k = tablet_kierownika()
    _odmowa(client.get(TESTOWA, headers=naglowki(device)), 400, 'worker_required')


@pytest.mark.parametrize('surowy', ['', ' , ', 'abc', '0', '-3'])
def test_bramka_zly_naglowek_pracownika_422(bramka, client, surowy):
    device, _k = tablet_kierownika()
    naglowek = naglowki(device)
    naglowek['X-Worker-Ids'] = surowy
    _odmowa(client.get(TESTOWA, headers=naglowek), 422, 'invalid_worker_ids')


def test_bramka_pracownik_bez_flagi_403(bramka, client):
    device, _k = tablet_kierownika()
    zwykly = ProductionWorker(first_name='Piotr', last_name='Zwykły', is_active=True, is_manager=False)
    db.session.add(zwykly)
    db.session.commit()
    _odmowa(client.get(TESTOWA, headers=naglowki(device, zwykly)), 403, 'not_a_manager')


def test_bramka_kierownik_nieaktywny_403(bramka, client):
    device, k = tablet_kierownika()
    k.is_active = False
    db.session.commit()
    _odmowa(client.get(TESTOWA, headers=naglowki(device, k)), 403, 'not_a_manager')


def test_bramka_nieznany_pracownik_404(bramka, client):
    device, k = tablet_kierownika()
    naglowek = naglowki(device)
    naglowek['X-Worker-Ids'] = str(k.id + 1000)
    _odmowa(client.get(TESTOWA, headers=naglowek), 404, 'worker_not_found')


def test_bramka_ustawia_g_worker_ids(bramka, client):
    device, k = tablet_kierownika()
    r = client.get(TESTOWA, headers=naglowki(device, k))
    assert r.status_code == 200, r.get_data()[:300]
    assert r.get_json() == {'kierownik_id': k.id, 'worker_ids': [k.id]}


def test_bramka_bez_tokenu_401(bramka, client):
    """Kroki 1 i 2 kontraktu (401) należą do require_device_token — bramka kierownika nie jest nawet wołana."""
    r = client.get(TESTOWA)
    assert r.status_code == 401 and r.get_json()['error'] == 'missing_token'


def test_zakazane_w_znajduje_zagniezdzone():
    assert biala_lista.zakazane_w({'a': [{'client_phone': 1}], 'b': {'price_per_m3': 2}}) == \
        ['a[0].client_phone', 'b.price_per_m3']


def test_zakazane_w_czysta_odpowiedz():
    assert biala_lista.zakazane_w({'id': 1, 'zamowienia': [{'numer': '26/00001', 'm3': 0.048}], 'x': None}) == []


def test_lista_endpointow_bramek_jest_pelna(app):
    reguly = {(metoda, r.rule[len(API):]) for r in app.url_map.iter_rules() if r.rule.startswith(API + '/')
              for metoda in r.methods - {'HEAD', 'OPTIONS'}}
    assert reguly == set(ENDPOINTY_KIEROWNIKA)
