# -*- coding: utf-8 -*-
"""
Trasy wysyłki — rejestracja pod właściwymi ścieżkami.

Bez pełnej aplikacji: register_routes montujemy na gołym Blueprintcie
(konwencja tests/test_api_content_type.py). Testy serwisu sprawdzają
matematykę, te sprawdzają adres — literówka w ścieżce jest dla tamtych
niewidoczna, a front trafia wtedy w 404.
"""
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
