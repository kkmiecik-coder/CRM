# -*- coding: utf-8 -*-
"""
Ręczna korekta licznika sztuk z panelu admina.

To drugie — obok tabletu — wejście do set_quantity_done/increment/decrement
(products_api.py:1022-1043). Router podaje surowy `station` prosto do modelu,
więc lista valid_stations (:976) jest tu jedyną bramką na poziomie panelu.
Lakierni w niej dziś nie ma wcale: admin nie może skorygować licznika
stanowiska, które od tego wdrożenia jest pełnoprawne.

Ten plik nie zakłada tabeli prod_product_events, bo nie robi tego żaden inny
plik w pakiecie — listener audytu milczy w całym przebiegu i tak ma zostać.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from extensions import db
from modules.production.models import ProductionProduct
from tests.krawedzie_fixtures import BASE, app, client, produkt  # noqa: F401


def _koryguj(client, pid, short, station, action='increment', value=None):
    tresc = {'record_id': pid, 'product_id': short,
             'station': station, 'action': action}
    if value is not None:
        tresc['value'] = value
    return client.post(BASE + '/admin/update-quantity-done', json=tresc)


def test_admin_koryguje_licznik_krawedzi(client, app):
    pid, short = produkt(app, quantity=4)
    r = _koryguj(client, pid, short, 'edges', action='set', value=3)
    assert r.status_code == 200, r.get_data()[:500]
    assert r.get_json()['quantity_done'] == 3
    with app.app_context():
        assert db.session.get(ProductionProduct, pid).quantity_done_edges == 3


def test_admin_koryguje_licznik_lakierni(client, app):
    """Dziś endpoint odrzuca 'painting' jako nieprawidłowe stanowisko."""
    pid, short = produkt(app, quantity=4)
    r = _koryguj(client, pid, short, 'painting', action='set', value=2)
    assert r.status_code == 200, r.get_data()[:500]
    with app.app_context():
        assert db.session.get(ProductionProduct, pid).quantity_done_painting == 2


def test_odpowiedz_niesie_liczniki_obu_nowych_stanowisk(client, app):
    pid, short = produkt(app, quantity=4)
    r = _koryguj(client, pid, short, 'edges')
    assert r.status_code == 200, r.get_data()[:500]
    liczniki = r.get_json()['all_quantity_done']
    assert liczniki['quantity_done_edges'] == 1
    assert liczniki['quantity_done_painting'] == 0
    assert 'quantity_done_finishing' not in liczniki


def test_nieznane_stanowisko_dalej_odrzucane(client, app):
    pid, short = produkt(app, quantity=4)
    r = _koryguj(client, pid, short, 'krawedzie')
    assert r.status_code == 400
