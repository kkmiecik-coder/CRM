# -*- coding: utf-8 -*-
"""
Statusy w module archiwum.

Cały kod statusów archiwum siedzi w JS — grep po 'finishing'
w archive-tab-content.html daje ZERO. Archiwum pokazuje pozycje sprzed
podziału, więc stary klucz zostaje: bez niego zamiast nazwy statusu wyjdzie
surowy enum (getStatusDisplayName :931 ma fallback na wartość).

Ten plik nie zakłada tabeli prod_product_events, bo nie robi tego żaden inny
plik w pakiecie — listener audytu milczy w całym przebiegu i tak ma zostać.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests.krawedzie_fixtures import JS_ARCHIWUM, zrodlo


def _blok(naglowek, domkniecie):
    js = zrodlo(JS_ARCHIWUM)
    assert naglowek in js, u'brak kotwicy: {}'.format(naglowek)
    poczatek = js.index(naglowek)
    reszta = js[poczatek:]
    return reszta[:reszta.index(domkniecie)]


def test_archiwum_nazywa_status_krawedzi():
    blok = _blok('const STATUS_DISPLAY_NAMES = {', '\n};\n')
    assert "'czeka_na_krawedzie': 'Czeka na krawędzie'" in blok


def test_archiwum_zachowuje_stara_nazwe_dla_pozycji_sprzed_podzialu():
    blok = _blok('const STATUS_DISPLAY_NAMES = {', '\n};\n')
    assert "'czeka_na_wykanczanie'" in blok
    assert 'archiwalne' in blok


def test_archiwum_ma_klase_stanowiska_dla_krawedzi():
    blok = _blok('    getStationClassFromStatus(status) {', '\n    }\n')
    assert "'czeka_na_krawedzie': 'status-finishing'" in blok
    assert "'czeka_na_wykanczanie'" not in blok


def test_archiwum_ma_klase_pigulki_dla_krawedzi():
    blok = _blok('    getStatusBadgeClass(status) {', '\n    }\n')
    assert "'czeka_na_krawedzie': 'badge-finishing'" in blok
    assert "'czeka_na_wykanczanie'" not in blok
