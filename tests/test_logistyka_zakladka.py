# -*- coding: utf-8 -*-
import os
import re

KATALOG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _plik(*sciezka):
    return open(os.path.join(KATALOG, *sciezka), encoding='utf-8').read()


def test_zakladka_stoi_przed_trakownia():
    html = _plik('modules', 'production', 'templates', 'panel', 'dashboard.html')
    kolejnosc = re.findall(r'id="(\w+)-tab"\s', html)
    assert kolejnosc.index('logistics') == kolejnosc.index('sawmill') - 1
    assert 'id="logistics-tab-content"' in html


def test_loader_zna_zakladke():
    js = _plik('modules', 'production', 'static', 'js', 'production-app-loader.js')
    assert js.count("'logistics-tab'") >= 3  # dwa validTabs + switch
    assert 'async loadLogisticsTab()' in js
    assert '/production/api/logistics/tab-content' in js


def test_js_zakladki_uzywa_api_i_nazwy_base():
    js = _plik('modules', 'production', 'logistics', 'static', 'js', 'logistics.js')
    for sciezka in ('/orders/delivery-method', '/handed-over', 'zamkniete'):
        assert sciezka in js, sciezka
    tekst = js + _plik('modules', 'production', 'logistics', 'templates', 'logistics',
                       'tab_content.html')
    assert 'BaseLinker' not in tekst and 'Base.' in tekst


def test_brak_cdn_w_zakladce():
    tekst = _plik('modules', 'production', 'logistics', 'templates', 'logistics',
                  'tab_content.html')
    assert 'unpkg.com' not in tekst and 'cdn.jsdelivr' not in tekst
