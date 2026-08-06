# -*- coding: utf-8 -*-
"""Kafelek trakowni na dashboardzie produkcji."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import re

SZABLON = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'modules', 'production', 'templates', 'components', 'dashboard-tab-content.html',
)
LOADER = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'modules', 'production', 'static', 'js', 'production-app-loader.js',
)


def _szablon():
    with open(SZABLON, encoding='utf-8') as f:
        return f.read()


def test_kafelek_trakowni_jest_pierwszy():
    """Trakownia to wejście w produkcję — stoi na początku gridu."""
    html = _szablon()
    kolejnosc = re.findall(r'data-station="(\w+)"', html)
    assert kolejnosc[0] == 'sawmill', u'kolejność kafelków: {}'.format(kolejnosc)


def test_kafelek_ma_wlasne_statystyki():
    html = _szablon()
    for klucz in ('sawmill.open_orders', 'sawmill.logs_today',
                  'sawmill.volume_today_m3', 'sawmill.to_settle'):
        assert klucz in html, u'brak {}'.format(klucz)


def test_kafelek_nie_uzywa_statystyk_produktowych():
    """Trakownia nie ma pending_count ani completed_today — to nie pipeline."""
    html = _szablon()
    blok = html.split('data-station="sawmill"')[1].split('data-station=')[0]
    assert 'pending_count' not in blok
    assert 'completed_today' not in blok


def test_kafelek_ma_telemetrie():
    html = _szablon()
    blok = html.split('data-station="sawmill"')[1].split('data-station=')[0]
    assert 'station_telemetry' in blok


def test_link_prowadzi_do_zakladki_nie_do_stanowiska():
    """Trakownia nie ma UI web — ikona przełącza zakładkę."""
    html = _szablon()
    blok = html.split('data-station="sawmill"')[1].split('data-station=')[0]
    assert 'production_stations' not in blok
    assert 'sawmill-tab' in blok


def test_loader_zna_zakladke_i_szeroki_zakres_skrotow():
    with open(LOADER, encoding='utf-8') as f:
        js = f.read()
    assert js.count("'sawmill-tab'") >= 3
    assert "event.key <= '6'" in js
    assert "event.key <= '5'" not in js
