# -*- coding: utf-8 -*-
import os

KATALOG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG = os.path.join(KATALOG, 'modules', 'production', 'logistics')


def _plik(*sciezka):
    return open(os.path.join(*sciezka), encoding='utf-8').read()


def _js():
    katalog = os.path.join(LOG, 'static', 'js')
    return ''.join(_plik(katalog, f) for f in os.listdir(katalog) if f.endswith('.js'))


def test_szablon_laduje_leaflet_z_repo():
    html = _plik(LOG, 'templates', 'logistics', 'tab_content.html')
    assert 'vendor/leaflet/leaflet.js' in html
    assert 'vendor/leaflet-markercluster/leaflet.markercluster.js' in html
    assert 'id="logistics-map"' in html
    for cdn in ('unpkg.com', 'cdn.jsdelivr', 'cdnjs'):
        assert cdn not in html


def test_js_mapy_obsluguje_korekte_i_lokalizowanie():
    js = _js()
    for fraza in ('/geocode', '/geo/reset', "method: 'PUT'", 'basemaps.cartocdn.com',
                  'markerClusterGroup', 'window.LogisticsMap', 'bez_lokalizacji'):
        assert fraza in js, fraza
    assert 'unpkg.com' not in js and 'BaseLinker' not in js
