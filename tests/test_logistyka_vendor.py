# -*- coding: utf-8 -*-
import os

VENDOR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      'modules', 'production', 'static', 'vendor')
PLIKI = ['leaflet/leaflet.js', 'leaflet/leaflet.css', 'leaflet/LICENSE',
         'leaflet/images/marker-icon.png', 'leaflet/images/marker-icon-2x.png',
         'leaflet/images/marker-shadow.png', 'leaflet/images/layers.png',
         'leaflet/images/layers-2x.png',
         'leaflet-markercluster/leaflet.markercluster.js',
         'leaflet-markercluster/MarkerCluster.css',
         'leaflet-markercluster/MarkerCluster.Default.css',
         'leaflet-markercluster/LICENSE']


def test_biblioteki_mapy_sa_w_repo():
    for plik in PLIKI:
        sciezka = os.path.join(VENDOR, *plik.split('/'))
        assert os.path.getsize(sciezka) > 0, plik
    assert '1.9.4' in open(os.path.join(VENDOR, 'leaflet', 'leaflet.js'), encoding='utf-8').read(2000)
