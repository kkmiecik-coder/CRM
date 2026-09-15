# -*- coding: utf-8 -*-
"""
Adresy monitorów w zakładce Stanowiska.

W szablonie stoją DWA bliźniacze słowniki stationUrls: jeden dla kliknięcia
w kafel (navigateToStation, :225-232), drugi dla „Pokaż wszystkie (N)"
(viewFullStationList, :246-253). Poprawienie jednego daje wersję, w której
kafel się klika, a przycisk pod listą jest martwy — bez żadnego błędu
w konsoli, bo obie funkcje kończą się cichym `if (stationUrls[stationKey])`.

Ten plik nie zakłada tabeli prod_product_events, bo nie robi tego żaden inny
plik w pakiecie — listener audytu milczy w całym przebiegu i tak ma zostać.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests.krawedzie_fixtures import SZABLON_STANOWISK, zrodlo

KODY = ('cutting', 'assembly', 'gluing', 'formatting',
        'edges', 'painting', 'packaging')


def _slowniki():
    """Ciała obu funkcji budujących mapę kodów na adresy monitorów."""
    html = zrodlo(SZABLON_STANOWISK)
    wynik = []
    for naglowek in ('function navigateToStation(stationKey) {',
                     'function viewFullStationList(stationKey) {'):
        assert naglowek in html, u'brak funkcji: {}'.format(naglowek)
        reszta = html[html.index(naglowek):]
        wynik.append(reszta[:reszta.index('\n}\n')])
    return wynik


def test_obie_kopie_znaja_wszystkie_siedem_stanowisk():
    for blok in _slowniki():
        kody = re.findall(r"^\s*'(\w+)':", blok, flags=re.MULTILINE)
        assert kody == list(KODY), u'kolejność/zestaw kodów: {}'.format(kody)


def test_zadna_kopia_nie_zna_juz_kodu_finishing():
    for blok in _slowniki():
        assert 'finishing' not in blok


def test_obie_kopie_buduja_adres_krawedzi_i_lakierni():
    for blok in _slowniki():
        assert 'station_code="edges"' in blok
        assert 'station_code="painting"' in blok
