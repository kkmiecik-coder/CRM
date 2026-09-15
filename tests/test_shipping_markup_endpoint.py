# -*- coding: utf-8 -*-
"""
Trasy wysyłki — rejestracja pod właściwymi ścieżkami.

Bez pełnej aplikacji: register_routes montujemy na gołym Blueprintcie
(konwencja tests/test_api_content_type.py). Testy serwisu sprawdzają
matematykę, te sprawdzają adres — literówka w ścieżce jest dla tamtych
niewidoczna, a front trafia wtedy w 404.
"""
import inspect
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Blueprint, Flask

from modules.calculator.routers.shipping_routers import register_routes


def _sciezki():
    bp = Blueprint('calculator', __name__)
    register_routes(bp)
    app = Flask(__name__)
    app.register_blueprint(bp, url_prefix='/calculator')
    return {str(regula) for regula in app.url_map.iter_rules()}


def test_trasa_przeliczania_narzutu_jest_zarejestrowana():
    assert '/calculator/api/shipping-markup' in _sciezki()


def test_stara_trasa_wyceny_kuriera_dalej_istnieje():
    """Nowy endpoint jest dodatkiem, nie zamiennikiem — cache w localStorage
    dalej karmi się surowymi cenami z /shipping_quote."""
    assert '/calculator/shipping_quote' in _sciezki()


def test_endpoint_narzutu_wymaga_wariantu_json():
    """Bez as_json=True wygasła sesja dostaje przekierowanie 302 na /login
    (HTML), nie 401 JSON. Przeglądarka idzie za przekierowaniem i widzi
    200 OK ze stroną logowania — response.ok we fetchShippingMarkup wychodzi
    `true`, a błąd ujawnia się dopiero jako SyntaxError z response.json().
    Mechanizm opisany w docstringu require_module_access
    (modules/users/decorators/permission_required.py)."""
    zrodlo = inspect.getsource(register_routes)
    poczatek = zrodlo.index('def shipping_markup():')
    dekorator = zrodlo[:poczatek]
    dekorator = dekorator[dekorator.rindex("@bp.route('/api/shipping-markup'"):]
    assert 'as_json=True' in dekorator, \
        'shipping_markup stracił as_json=True — wygasła sesja znów wróci jako HTML 200'
