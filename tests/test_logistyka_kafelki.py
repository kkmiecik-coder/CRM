# -*- coding: utf-8 -*-
"""
Klucz CARTO Basemaps dla kafelków mapy logistyki (zadanie 9, poza planem etapu 2).

CARTO od 2026 wymaga klucza API dla kafelków rastrowych — bez niego kafelek
niesie znak wodny „API KEY REQUIRED". Klucz leży wyłącznie w config/core.json
(pole CARTO_BASEMAPS_KEY, jak PRODUCTION_CRON_SECRET czy CEIDG_JWT_TOKEN) —
repo jest publiczne, więc klucz nie trafia do kodu ani do tego pliku.

tab_content() czyta klucz z current_app.config i wstawia go do data-atrybutu
#logistics-map (autoescape Jinja, bez |safe). Bez klucza mapa dalej działa
(kafelki bez ?key=, ze znakiem wodnym CARTO), a serwer ostrzega w logu
najwyżej raz na proces (moduł-poziom flaga w panel_api.py) — stąd test (c)
zeruje ją monkeypatchem, żeby nie zależeć od kolejności innych testów, które
też renderują tę zakładkę bez klucza.

Dopisek (poza pierwotnym briefem, na życzenie właściciela): przełącznik
podkładu mapy w logistics-map.js (PODKLADY) — Voyager (domyślny), Positron
i OpenStreetMap. Klucz CARTO dokłada się tylko do dwóch pierwszych (`klucz:
true`); OSM nie wymaga klucza. Testy tu są statyczne (treść pliku JS) —
zachowanie samego przełącznika (localStorage, setUrl bez przebudowy mapy,
podgląd w przycisku) wymagałoby przeglądarki, więc pilnujemy tylko, że
wszystkie trzy style są zaszyte w kodzie i że żaden fragment nie wygląda jak
prawdziwy klucz CARTO.
"""
import os

import modules.production.logistics.routers.panel_api as panel_api
from tests.logistyka_fixtures import BASE, app, client  # noqa: F401

KATALOG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JS_MAPY = os.path.join(KATALOG, 'modules', 'production', 'logistics', 'static', 'js', 'logistics-map.js')


def test_klucz_carto_z_konfiguracji_trafia_do_atrybutu_szablonu(app, client):  # noqa: F811
    app.config['CARTO_BASEMAPS_KEY'] = 'klucz-testowy-carto'
    r = client.get(BASE + '/tab-content')
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert 'data-carto-key="klucz-testowy-carto"' in html


def test_brak_klucza_carto_daje_pusty_atrybut_i_200(app, client, monkeypatch):  # noqa: F811
    monkeypatch.setattr(panel_api, '_carto_key_ostrzezono', False)
    assert 'CARTO_BASEMAPS_KEY' not in app.config
    r = client.get(BASE + '/tab-content')
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert 'data-carto-key=""' in html


def test_ostrzezenie_o_braku_klucza_loguje_sie_raz_nie_dwa_razy(app, client, monkeypatch):  # noqa: F811
    monkeypatch.setattr(panel_api, '_carto_key_ostrzezono', False)
    wywolania = []
    monkeypatch.setattr(panel_api.logger, 'warning',
                        lambda *a, **k: wywolania.append((a, k)))

    assert client.get(BASE + '/tab-content').status_code == 200
    assert client.get(BASE + '/tab-content').status_code == 200

    assert len(wywolania) == 1


def test_pusty_string_traktowany_jak_brak_klucza(app, client, monkeypatch):  # noqa: F811
    monkeypatch.setattr(panel_api, '_carto_key_ostrzezono', False)
    app.config['CARTO_BASEMAPS_KEY'] = '   '
    r = client.get(BASE + '/tab-content')
    html = r.get_data(as_text=True)
    assert 'data-carto-key=""' in html


def test_js_mapy_sklada_adres_kafelkow_z_klucza_i_nie_niesie_prawdziwego_klucza():
    js = open(JS_MAPY, encoding='utf-8').read()
    assert 'rastertiles' in js
    assert 'key=' in js
    # cb_/cb1_ itp. — wzorzec prawdziwych kluczy CARTO; w repo publicznym nie może się pojawić.
    assert 'cb1_' not in js


def test_core_json_example_ma_puste_pole_klucza_carto():
    """M8: kto zakłada core.json z przykładu, widzi pole — puste (repo publiczne)."""
    import json
    with open(os.path.join(KATALOG, 'config', 'core.json.example'), encoding='utf-8') as f:
        przyklad = json.load(f)
    assert przyklad['CARTO_BASEMAPS_KEY'] == ''


def test_js_mapy_ma_trzy_podklady_i_zaden_prawdziwy_klucz():
    js = open(JS_MAPY, encoding='utf-8').read()
    # Voyager (domyślny), Positron i OpenStreetMap — identyfikatory stylów wpisane w PODKLADY.
    assert 'voyager' in js
    assert 'light_all' in js
    assert 'tile.openstreetmap.org' in js
    assert 'cb1_' not in js


def test_logo_base_podane_przez_url_for_i_serwowane(app, client):  # noqa: F811
    """UF5: adres logo z url_for w data-logo-base, statyka modułu oddaje PNG."""
    import re
    html = client.get(BASE + '/tab-content').get_data(as_text=True)
    m = re.search(r'data-logo-base="([^"?]+)\?v=\w+"', html)
    assert m and m.group(1).endswith('/img/base-logo.png')
    r = client.get(m.group(1))
    assert r.status_code == 200 and r.mimetype == 'image/png'
