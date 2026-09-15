# -*- coding: utf-8 -*-
"""
Mapy nazw statusów w products-module.js — trzy niezależne kopie w jednym pliku.

STATUS_TRANSLATIONS (:31-44) renderuje także HISTORIĘ statusów
z prod_product_events (translateStatus :4558 <- renderHistoryEntry), a te 423
wiersze trzymają string 'czeka_na_wykanczanie' jako TEKST — stary klucz musi
zostać, inaczej w historii produktu pojawi się surowy enum.

STATUS_CONFIG (:47-66) i jej rozwinięta bliźniaczka w getStatusConfig
(:4565-4674) to mapy DECYZYJNE — tam stary klucz jest martwy i znika, razem
z całkiem martwym 'w_trakcie_wykanczania' (models.py nie zna żadnego
statusu 'w_trakcie_*').

W repozytorium nie ma runtime'u JS (obraz testowy bez node'a), więc
sprawdzamy własności czytelne ze źródła — konwencja tests/test_checkout_js.py.

Ten plik nie zakłada tabeli prod_product_events, bo nie robi tego żaden inny
plik w pakiecie — listener audytu milczy w całym przebiegu i tak ma zostać.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests.krawedzie_fixtures import JS_PRODUKTY, zrodlo


def _blok(naglowek, domkniecie='\n    };\n'):
    js = zrodlo(JS_PRODUKTY)
    assert naglowek in js, u'brak kotwicy: {}'.format(naglowek)
    poczatek = js.index(naglowek)
    reszta = js[poczatek:]
    return reszta[:reszta.index(domkniecie)]


def test_tlumaczenia_znaja_krawedzie():
    blok = _blok('static STATUS_TRANSLATIONS = {')
    assert "'czeka_na_krawedzie': 'Krawędzie'" in blok


def test_tlumaczenia_zachowuja_klucz_archiwalny():
    """423 wiersze prod_product_events trzymają stary status jako tekst."""
    blok = _blok('static STATUS_TRANSLATIONS = {')
    assert "'czeka_na_wykanczanie'" in blok
    assert 'archiwalne' in blok


def test_konfiguracja_statusow_zna_krawedzie():
    blok = _blok('static STATUS_CONFIG = {')
    assert "'czeka_na_krawedzie':" in blok
    assert "displayName: 'Krawędzie'" in blok
    assert "'czeka_na_wykanczanie':" not in blok


def test_blizniacza_kopia_konfiguracji_tez_zna_krawedzie():
    """getStatusConfig() ma własną, rozwiniętą kopię tej samej mapy."""
    blok = _blok('    getStatusConfig(status) {', '\n    }\n')
    assert "'czeka_na_krawedzie': {" in blok
    assert "displayName: 'Krawędzie'" in blok
    assert "'czeka_na_wykanczanie': {" not in blok


def test_martwy_status_w_trakcie_wykanczania_znika_z_calego_pliku():
    """models.py nie zna żadnego 'w_trakcie_*' — nie przenosimy go pod nową nazwą."""
    js = zrodlo(JS_PRODUKTY)
    assert 'w_trakcie_wykanczania' not in js
    assert 'w_trakcie_krawedzi' not in js
