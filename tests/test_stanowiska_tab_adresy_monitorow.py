# -*- coding: utf-8 -*-
"""
Adresy monitorów w zakładce Stanowiska.

W szablonie stoi słownik stationUrls dla „Pokaż wszystkie (N)"
(viewFullStationList). Brakujący kod daje martwy przycisk pod listą — bez żadnego
błędu w konsoli, bo funkcja kończy się cichym `if (stationUrls[stationKey])`.

Dawniej były dwie bliźniacze mapy (drugą miał klikany kafel przepływu,
navigateToStation). Po przejściu na podzakładki kafla nie ma, a „Podgląd monitora"
to zwykły odnośnik z url_for, więc została jedna mapa.

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


def _slownik():
    """Ciało funkcji budującej mapę kodów na adresy monitorów."""
    html = zrodlo(SZABLON_STANOWISK)
    naglowek = 'function viewFullStationList(stationKey) {'
    assert naglowek in html, u'brak funkcji: {}'.format(naglowek)
    reszta = html[html.index(naglowek):]
    return reszta[:reszta.index('\n}\n')]


def test_mapa_zna_wszystkie_siedem_stanowisk():
    kody = re.findall(r"^\s*'(\w+)':", _slownik(), flags=re.MULTILINE)
    assert kody == list(KODY), u'kolejność/zestaw kodów: {}'.format(kody)


def test_mapa_nie_zna_juz_kodu_finishing():
    assert 'finishing' not in _slownik()


def test_mapa_buduje_adres_krawedzi_i_lakierni():
    blok = _slownik()
    assert 'station_code="edges"' in blok
    assert 'station_code="painting"' in blok


def test_martwy_kafel_przeplywu_zniknal():
    """navigateToStation obsługiwał kafle starego „Przepływu produkcji"; nic go już nie woła."""
    assert 'navigateToStation' not in zrodlo(SZABLON_STANOWISK)
