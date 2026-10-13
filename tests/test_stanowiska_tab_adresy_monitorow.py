# -*- coding: utf-8 -*-
"""
Adresy monitorów w zakładce Stanowiska.

Każdy panel stanowiska ma w nagłówku odnośnik „Podgląd monitora” zbudowany przez
url_for('production.production_stations.monitor_station', …). Brakujący kod albo literówka
dawałaby martwy odnośnik bez żadnego błędu, więc sprawdzamy adres każdego z siedmiu stanowisk.

Dawniej adresy monitorów siedziały też w dwóch bliźniaczych mapach w JS (klik w kafel przepływu
i przycisk „Pokaż wszystkie”, który otwierał monitor). Po przejściu na podzakładki kafli nie ma,
a „Pokaż wszystkie” rozwija tabelę na miejscu, więc map już nie ma; test niżej pilnuje, żeby nie wróciły.

Ten plik nie zakłada tabeli prod_product_events, bo nie robi tego żaden inny
plik w pakiecie — listener audytu milczy w całym przebiegu i tak ma zostać.
"""
import os
import sys

from bs4 import BeautifulSoup

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests.krawedzie_fixtures import BASE, SZABLON_STANOWISK, app, client, zrodlo  # noqa: F401

KODY = ('cutting', 'assembly', 'gluing', 'formatting',
        'edges', 'painting', 'packaging')


def _panele(client):
    r = client.get(BASE + '/stations-tab-content')
    assert r.status_code == 200, r.get_data()[:500]
    zupa = BeautifulSoup(r.get_json()['html'], 'html.parser')
    return {panel['data-stanowisko']: panel for panel in zupa.select('section[data-stanowisko]')}


def test_kazdy_panel_ma_podglad_monitora_swojego_stanowiska(client, app):
    panele = _panele(client)
    assert tuple(panele) == KODY
    for kod, panel in panele.items():
        odnosnik = panel.select_one('a.stn-link')
        assert odnosnik is not None, kod
        assert odnosnik['href'].rstrip('/').endswith('/monitors/%s' % kod), (kod, odnosnik['href'])


def test_adresy_monitorow_nie_znaja_kodu_finishing(client, app):
    for kod, panel in _panele(client).items():
        assert 'finishing' not in panel.select_one('a.stn-link')['href'], kod


def test_martwe_mapy_adresow_zniknely():
    """navigateToStation obsługiwał kafle starego „Przepływu produkcji”, viewFullStationList otwierał monitor
    zamiast rozwinąć tabelę; nic ich już nie woła."""
    szablon = zrodlo(SZABLON_STANOWISK)
    for nazwa in ('navigateToStation', 'viewFullStationList', 'stationUrls', 'window.open('):
        assert nazwa not in szablon, nazwa
