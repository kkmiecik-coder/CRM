# -*- coding: utf-8 -*-
"""
Serializer listy produktów (/products-tab-content) po rename stanowiska.

Nazwa klucza jest kontraktem z frontem: products-module.js czyta licznik
dynamicznie, jako product[`quantity_done_${station.code}`]
(products-module.js:4003) — przy kodzie 'edges' i kluczu
'quantity_done_finishing' dostanie undefined i pokaże 0/N bez żadnego błędu.

Ten plik nie zakłada tabeli prod_product_events, bo nie robi tego żaden inny
plik w pakiecie — listener audytu milczy w całym przebiegu i tak ma zostać.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests.krawedzie_fixtures import BASE, app, client, produkt  # noqa: F401


def _lista(client):
    r = client.get(BASE + '/products-tab-content')
    assert r.status_code == 200, r.get_data()[:500]
    dane = r.get_json()
    assert dane['success'] is True
    return dane['initial_data']['products']


def test_lista_oddaje_licznik_krawedzi(client, app):
    produkt(app, quantity=4, quantity_done_edges=3)
    pozycja = _lista(client)[0]
    assert pozycja['quantity_done_edges'] == 3


def test_lista_nie_zna_juz_licznika_wykanczania(client, app):
    produkt(app)
    pozycja = _lista(client)[0]
    assert 'quantity_done_finishing' not in pozycja


def test_lista_nadal_oddaje_licznik_lakierni_i_obrobke_krawedzi(client, app):
    """
    Oba pola są w tym serializerze od dawna (products_api.py:211 i :257) — po
    zmianie routingu parsed_edge_processing decyduje, czy produkt w ogóle
    wchodzi na Krawędzie, więc pilnujemy, żeby nie wypadło przy okazji.
    """
    produkt(app, edge_processing=True, quantity_done_painting=2)
    pozycja = _lista(client)[0]
    assert pozycja['quantity_done_painting'] == 2
    assert pozycja['parsed_edge_processing'] is True
