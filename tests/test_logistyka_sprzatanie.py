# -*- coding: utf-8 -*-
import os

KATALOG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _plik(*sciezka):
    return open(os.path.join(KATALOG, *sciezka), encoding='utf-8').read()


def test_stara_logistyka_usunieta():
    assert not os.path.exists(os.path.join(KATALOG, 'modules', 'production', 'routers',
                                           'api', 'logistics_api.py'))
    assert not os.path.exists(os.path.join(KATALOG, 'modules', 'production', 'templates',
                                           'logistics', 'logistics.html'))
    assert 'logistics_api' not in _plik('modules', 'production', 'routers', 'api', '__init__.py')


def test_lista_hurtowa_nie_oferuje_logistyki():
    assert 'value="czeka_na_logistyke"' not in _plik(
        'modules', 'production', 'templates', 'components', 'products-tab-content.html')
    js = _plik('modules', 'production', 'static', 'js', 'modules', 'products-module.js')
    assert "{ value: 'czeka_na_logistyke'" not in js
    assert "commonStations.push('logistics'" not in js


def test_bramka_dashboardu_liczy_brak_sposobu():
    html = _plik('modules', 'production', 'templates', 'components', 'dashboard-tab-content.html')
    blok = html.split('data-station="logistics"')[1].split('data-station=')[0]
    assert 'id="logistics-pending"' in blok
    assert 'bez sposobu dostawy' in blok
    assert '?tab=logistics' in blok


def test_bulk_action_odrzuca_logistyke():
    kod = _plik('modules', 'production', 'routers', 'api', 'products_api.py')
    assert "- {'czeka_na_logistyke'}" in kod
