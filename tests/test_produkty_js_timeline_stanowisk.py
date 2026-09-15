# -*- coding: utf-8 -*-
"""
Trasa produktu i definicje timeline w modalu szczegółów.

Definicja stanowiska 'painting' (:3956-3966) to jedyne miejsce w panelu, które
wprost twierdzi „lakiernia to podkrok wykańczania" (isSubstep: true + kolor
dziedziczony 'finishing-theme'). Po podziale Lakiernia jest pełnoprawnym
stanowiskiem, a Krawędzie wchodzą do trasy wyłącznie wtedy, gdy produkt ma
obróbkę krawędzi — to samo kryterium co ProductionProduct.should_skip_edges.

Klasy '.painting-theme' i zmienna '--il-painting' istnieją w products-tab.css
od dawna (:45, :1864, :1883, :1935-1936), więc własny kolor nie wymaga CSS.

Ten plik nie zakłada tabeli prod_product_events, bo nie robi tego żaden inny
plik w pakiecie — listener audytu milczy w całym przebiegu i tak ma zostać.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests.krawedzie_fixtures import JS_PRODUKTY, zrodlo


def _trasa():
    js = zrodlo(JS_PRODUKTY)
    poczatek = js.index('    getStationsForProduct(product) {')
    reszta = js[poczatek:]
    return reszta[:reszta.index('\n    }\n')]


def _definicja(kod):
    """Obiekt definicji stanowiska z tablicy timeline'u."""
    js = zrodlo(JS_PRODUKTY)
    znacznik = "                code: '{}',".format(kod)
    assert znacznik in js, u'brak definicji stanowiska {}'.format(kod)
    poczatek = js.index(znacznik)
    return js[poczatek:js.index('\n            }', poczatek)]


def test_krawedzie_wchodza_do_trasy_tylko_przy_obrobce_krawedzi():
    blok = _trasa()
    assert 'product.parsed_edge_processing' in blok
    assert "commonStations.push('edges')" in blok
    # Stała lista wspólnych stanowisk nie może już zawierać wykańczania.
    assert "const commonStations = ['gluing', 'formatting'];" in blok
    assert 'finishing' not in blok


def test_lakiernia_nadal_zalezy_od_wykonczenia():
    blok = _trasa()
    assert 'needsPainting' in blok
    assert "commonStations.push('painting')" in blok


def test_definicja_krawedzi_uzywa_wlasnej_kolumny_daty():
    blok = _definicja('edges')
    assert "name: 'Krawędzie'" in blok
    assert "status: 'czeka_na_krawedzie'" in blok
    assert "endField: 'edges_completed_at'" in blok
    # ProductionProduct nie ma kolumn *_started_at ani *_duration_minutes.
    assert 'startField: null' in blok
    assert 'durationField: null' in blok


def test_lakiernia_przestaje_byc_podkrokiem_wykanczania():
    blok = _definicja('painting')
    assert 'isSubstep' not in blok
    assert "color: 'painting-theme'" in blok
    assert "endField: 'painting_completed_at'" in blok


def test_timeline_nie_zna_juz_stanowiska_finishing():
    js = zrodlo(JS_PRODUKTY)
    assert "code: 'finishing'," not in js
