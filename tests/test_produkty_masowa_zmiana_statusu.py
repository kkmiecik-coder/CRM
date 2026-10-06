# -*- coding: utf-8 -*-
"""
Masowa zmiana statusu produktów.

Dziś ten endpoint NIE MA żadnej walidacji — przypisuje surowy string
z requestu do product.current_status (products_api.py:1286) — a
db.session.commit() stoi POZA pętlą try (:1316). Enum SQLAlchemy nie sprawdza
wartości po stronie Pythona przy ZAPISIE (validate_strings domyślnie False),
więc błąd nie pojawia się w kodzie, tylko w bazie: po zwężeniu enuma
(czeka_na_wykanczanie -> czeka_na_krawedzie) wysłanie starego statusu wywala
na MySQL-u CAŁY batch błędem 1265 (Data truncated), łącznie z pozycjami,
które w ogóle nie były problemem.

Na SQLite Enum ma create_constraint=False (domyślne w SQLAlchemy 1.4), więc
baza nic nie sprawdzi — sprawdzone na kontenerze: dziś taki request kończy
się HTTP 200 i processed_count=1. Właśnie dlatego walidacja musi siedzieć
w kodzie i mieć własny test.

Ten plik nie zakłada tabeli prod_product_events, bo nie robi tego żaden inny
plik w pakiecie — listener audytu milczy w całym przebiegu i tak ma zostać.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from extensions import db
from modules.production.models import ProductionProduct
from tests.krawedzie_fixtures import BASE, app, client, produkt  # noqa: F401


def _masowo(client, ids, status):
    return client.post(BASE + '/products/bulk-action', json={
        'action': 'update_status',
        'product_ids': ids,
        'parameters': {'new_status': status},
    })


def test_nieznany_status_odrzucony_przed_zapisem(client, app):
    pid, _ = produkt(app, status='czeka_na_krawedzie')
    r = _masowo(client, [pid], 'czeka_na_wykanczanie')
    assert r.status_code == 400, r.get_data()[:500]
    assert r.get_json()['success'] is False
    with app.app_context():
        assert db.session.get(ProductionProduct, pid).current_status == 'czeka_na_krawedzie'


def test_jeden_zly_status_nie_psuje_calego_batcha(client, app):
    """Walidacja stoi PRZED pętlą — żadna pozycja nie zostaje ruszona."""
    a, _ = produkt(app, status='czeka_na_krawedzie', numer='25/00001')
    b, _ = produkt(app, status='czeka_na_krawedzie', numer='25/00002')
    r = _masowo(client, [a, b], 'zupelnie_nieistniejacy_status')
    assert r.status_code == 400
    with app.app_context():
        for pid in (a, b):
            assert db.session.get(ProductionProduct, pid).current_status == 'czeka_na_krawedzie'


def test_status_krawedzi_przechodzi(client, app):
    pid, _ = produkt(app, status='czeka_na_formatowanie')
    r = _masowo(client, [pid], 'czeka_na_krawedzie')
    assert r.status_code == 200, r.get_data()[:500]
    assert r.get_json()['processed_count'] == 1
    with app.app_context():
        assert db.session.get(ProductionProduct, pid).current_status == 'czeka_na_krawedzie'


def test_status_lakierni_przechodzi(client, app):
    pid, _ = produkt(app, status='czeka_na_formatowanie')
    r = _masowo(client, [pid], 'czeka_na_lakiernie')
    assert r.status_code == 200, r.get_data()[:500]
    with app.app_context():
        assert db.session.get(ProductionProduct, pid).current_status == 'czeka_na_lakiernie'


def test_inne_akcje_nie_wymagaja_statusu(client, app):
    """Walidacja obowiązuje wyłącznie akcję update_status."""
    pid, _ = produkt(app)
    r = client.post(BASE + '/products/bulk-action', json={
        'action': 'update_priority',
        'product_ids': [pid],
        'parameters': {'new_priority': 42},
    })
    assert r.status_code == 200, r.get_data()[:500]
    with app.app_context():
        assert db.session.get(ProductionProduct, pid).priority_rank == 42
