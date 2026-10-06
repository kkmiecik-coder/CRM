# -*- coding: utf-8 -*-
"""
Mapy pól i statusów stanowisk w products-module.js — trzy niezależne kopie.

generateQuantityProgress (:4037-4088) NIE MA dziś lakierni w ogóle, mimo że
getStationsForProduct potrafi ją zwrócić — procent w nagłówku modalu wychodzi
przez to zaniżony. getTimelineState (:4093-4162) ma te same mapy w trzeciej
kopii, plus własną kolejność stanowisk. historyAccent (:4387-4405) indeksuje
po station_code Z BAZY, więc po migracji historii bez tej zmiany wpisy pracy
na Krawędziach zszarzeją (fallback '--il-border').

Nazwy zmiennych CSS ('--il-finishing') zostają pod starymi nazwami — rename
arkuszy jest osobnym zadaniem.

Ten plik nie zakłada tabeli prod_product_events, bo nie robi tego żaden inny
plik w pakiecie — listener audytu milczy w całym przebiegu i tak ma zostać.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests.krawedzie_fixtures import JS_PRODUKTY, zrodlo

KODY = ['cutting', 'assembly', 'gluing', 'formatting',
        'edges', 'painting', 'logistics', 'packaging']


def _blok(naglowek, domkniecie):
    js = zrodlo(JS_PRODUKTY)
    assert naglowek in js, u'brak kotwicy: {}'.format(naglowek)
    poczatek = js.index(naglowek)
    reszta = js[poczatek:]
    return reszta[:reszta.index(domkniecie)]


def _funkcja(naglowek):
    return _blok(naglowek, '\n    }\n')


def test_postep_ilosciowy_zna_oba_nowe_stanowiska():
    blok = _funkcja('    generateQuantityProgress(modalElement, product) {')
    assert "'edges': 'edges_completed_at'" in blok
    assert "'painting': 'painting_completed_at'" in blok
    assert "'edges': 'czeka_na_krawedzie'" in blok
    assert "'painting': 'czeka_na_lakiernie'" in blok
    assert 'finishing' not in blok


def test_stan_timeline_ma_krawedzie_w_kolejnosci_przed_lakiernia():
    blok = _funkcja('    getTimelineState(station, product) {')
    kolejnosc = re.findall(r"const stationOrder = \[([^\]]+)\]", blok)[0]
    assert re.findall(r"'(\w+)'", kolejnosc) == KODY


def test_stan_timeline_zna_pola_i_statusy_obu_stanowisk():
    blok = _funkcja('    getTimelineState(station, product) {')
    assert "'edges': 'edges_completed_at'" in blok
    assert "'edges': 'czeka_na_krawedzie'" in blok
    assert "'painting': 'painting_completed_at'" in blok
    assert "'painting': 'czeka_na_lakiernie'" in blok
    assert 'finishing' not in blok


def test_kolor_wpisu_historii_liczy_sie_z_kodu_edges():
    """Klucz to station_code Z BAZY — po migracji historii to już 'edges'."""
    blok = _funkcja('    historyAccent(entry) {')
    assert "edges: '--il-finishing'" in blok
    assert 'finishing:' not in blok
