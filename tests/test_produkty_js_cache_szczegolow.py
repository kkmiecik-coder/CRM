# -*- coding: utf-8 -*-
"""
Wykrywanie kompletnego rekordu w cache modalu szczegółów.

Warunek hasNewStationFields (products-module.js:3554-3558) rozstrzyga, czy
modal użyje rekordu z pamięci, czy dociągnie /products/<id>/details. Musi więc
pytać o pola, które ma WYŁĄCZNIE bogatszy serializer
(_serialize_production_item), a których nie ma uboższa lista
z /products-tab-content (_serialize_product).

Pytanie o *_started_at było zawsze bez sensu: ProductionProduct nie ma takich
kolumn, więc pola serializowały się jako None (klucz był, wartość nie). Po
Zadaniu 5 'finishing_started_at' znika z odpowiedzi w ogóle i warunek
przestałby cokolwiek rozstrzygać.

Ten plik nie zakłada tabeli prod_product_events, bo nie robi tego żaden inny
plik w pakiecie — listener audytu milczy w całym przebiegu i tak ma zostać.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests.krawedzie_fixtures import JS_PRODUKTY, PY_PRODUCTS_API, zrodlo


def _warunek():
    js = zrodlo(JS_PRODUKTY)
    poczatek = js.index('const hasNewStationFields = product && (')
    return js[poczatek:js.index(');', poczatek)]


def test_warunek_pyta_o_daty_domkniecia_a_nie_o_start():
    blok = _warunek()
    assert "hasOwnProperty('gluing_completed_at')" in blok
    assert "hasOwnProperty('formatting_completed_at')" in blok
    assert "hasOwnProperty('edges_completed_at')" in blok
    assert '_started_at' not in blok


def test_pola_z_warunku_naprawde_rozrozniaja_oba_serializery():
    """
    Gdyby uboższy _serialize_product też je oddawał, warunek byłby zawsze
    prawdziwy i modal na zawsze zostałby na niepełnych danych z cache.
    Slice kończymy na najbliższej definicji najwyższego poziomu, żeby nie
    przeczesywać przy okazji 2000 linii cudzego kodu.
    """
    kod = zrodlo(PY_PRODUCTS_API)
    poczatek = kod.index('def _serialize_product(')
    lista = kod[poczatek:kod.index('\ndef ', poczatek + 1)]
    for pole in ('gluing_completed_at', 'formatting_completed_at',
                 'edges_completed_at'):
        assert "'{}'".format(pole) not in lista, \
            u'pole {} przestalo rozrozniac serializery'.format(pole)
