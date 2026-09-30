# -*- coding: utf-8 -*-
"""GET /api/print-agent/jobs z filtrem drukarek (logistyka etap 4, krok 4.1, spec 6.1)."""
import pytest

from modules.production.models import LabelPrintJob
from modules.production.routers.api import print_agent_api
from tests.druk_fixtures import app, zadanie  # noqa: F401

TOKEN = 'token-agenta-testowy'
NAGLOWKI = {'Authorization': 'Bearer ' + TOKEN}


@pytest.fixture()
def client(app, monkeypatch):
    monkeypatch.setattr(print_agent_api, '_get_agent_token', lambda: TOKEN)
    app.register_blueprint(print_agent_api.print_agent_bp, url_prefix='/api/print-agent')
    return app.test_client()


def _jobs(client, zapytanie=''):
    resp = client.get('/api/print-agent/jobs' + zapytanie, headers=NAGLOWKI)
    assert resp.status_code == 200
    return resp.get_json()['jobs']


def test_stary_agent_bez_parametru_dostaje_tylko_etykiety(client):
    """Agent sprzed etapu 4 nie wysyła ?printers= — etykieta 100x150 wysłana na
    drukarkę 60x40 zmarnowałaby etykiety i zadanie."""
    a = zadanie()
    zadanie(printer='wysylka', kod='P-1')
    jobs = _jobs(client)
    assert [j['id'] for j in jobs] == [a.id]
    assert jobs[0]['printer'] == 'etykiety'


def test_agent_drukarki_wysylki_dostaje_tylko_swoje(client):
    zadanie()
    b = zadanie(printer='wysylka', kod='P-1')
    jobs = _jobs(client, '?printers=wysylka')
    assert [j['id'] for j in jobs] == [b.id]
    assert jobs[0]['printer'] == 'wysylka'


def test_lista_drukarek_w_kolejnosci_fifo(client):
    a = zadanie()
    b = zadanie(printer='wysylka', kod='P-1')
    c = zadanie(kod='900_2')
    assert [j['id'] for j in _jobs(client, '?printers=etykiety,wysylka')] == [a.id, b.id, c.id]


@pytest.mark.parametrize('zapytanie', ['?printers=', '?printers=nieznana', '?printers=%20,%20'])
def test_nieznane_albo_puste_drukarki_nie_dostaja_niczego(client, zapytanie):
    zadanie()
    zadanie(printer='wysylka', kod='P-1')
    assert _jobs(client, zapytanie) == []


def test_wielkosc_liter_i_spacje_w_parametrze(client):
    b = zadanie(printer='wysylka', kod='P-1')
    assert [j['id'] for j in _jobs(client, '?printers=%20WYSYLKA%20')] == [b.id]


def test_limit_liczy_po_filtrze(client):
    for i in range(3):
        zadanie(printer='wysylka', kod='P-%d' % i)
    zadanie()
    assert len(_jobs(client, '?printers=wysylka&limit=2')) == 2


def test_tylko_oczekujace(client):
    zadanie(printer='wysylka', kod='P-1', status='printed')
    assert _jobs(client, '?printers=wysylka') == []


def test_nieudany_wydruk_paczki_nie_rusza_pozycji(client):
    """Zadanie bez product_id (etykieta paczki, wydruk próbny) po błędzie drukarki
    ma status failed, a cofanie licznika etykiet produktów je pomija."""
    b = zadanie(printer='wysylka', kod='P-1')
    resp = client.post('/api/print-agent/ack', headers=NAGLOWKI,
                       json={'results': [{'id': b.id, 'success': False, 'error': 'brak papieru'}]})
    assert resp.status_code == 200 and resp.get_json()['updated'] == 1
    job = LabelPrintJob.query.get(b.id)
    assert job.status == 'failed' and job.error_message == 'brak papieru'
