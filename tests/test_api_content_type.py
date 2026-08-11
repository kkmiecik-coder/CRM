# -*- coding: utf-8 -*-
"""
Nagłówki odpowiedzi blueprintu API produkcji.

Powód powstania: after_request stemplował KAŻDĄ odpowiedź nagłówkiem
Content-Type: application/json — także eksporty plików (/products/export
i raport wydajności pracowników) oraz endpointy *-tab-content zwracające HTML.
Przeglądarka dostawała plik XLSX opisany jako JSON.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from flask import Blueprint, Flask, Response, jsonify

from modules.production.routers.api.common_api import register_middleware


@pytest.fixture()
def client():
    app = Flask(__name__)
    bp = Blueprint('testowy_api', __name__)

    @bp.route('/json')
    def zwroc_json():
        return jsonify({'ok': True})

    @bp.route('/plik')
    def zwroc_plik():
        return Response(
            b'PK\x03\x04udawany-xlsx',
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

    @bp.route('/html')
    def zwroc_html():
        return '<div>zawartosc zakladki</div>'

    register_middleware(bp)
    app.register_blueprint(bp)
    return app.test_client()


def test_json_dostaje_naglowek_json_z_charsetem(client):
    odp = client.get('/json')
    assert odp.headers['Content-Type'] == 'application/json; charset=utf-8'


def test_plik_zachowuje_swoj_typ(client):
    """Bez tego przeglądarka dostaje XLSX opisany jako JSON."""
    odp = client.get('/plik')
    assert odp.headers['Content-Type'].startswith(
        'application/vnd.openxmlformats-officedocument')
    assert odp.get_data().startswith(b'PK')


def test_html_nie_jest_podawany_jako_json(client):
    odp = client.get('/html')
    assert odp.headers['Content-Type'].startswith('text/html')


def test_naglowki_diagnostyczne_zostaja(client):
    odp = client.get('/plik')
    assert odp.headers['X-API-Version'] == '1.0'
    assert odp.headers['X-Production-Module'] == 'WoodPower-Production-API'
