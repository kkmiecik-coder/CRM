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
PRODUCTION_PANEL_CSS = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'modules', 'production', 'static', 'css', 'production-panel.css',
)
SAWMILL_CSS = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'modules', 'production', 'sawmill', 'static', 'css', 'sawmill.css',
)
SAWMILL_JS = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'modules', 'production', 'sawmill', 'static', 'js', 'sawmill.js',
)


def _szablon():
    with open(SZABLON, encoding='utf-8') as f:
        return f.read()


def _plik(sciezka):
    with open(sciezka, encoding='utf-8') as f:
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


# ── Testy naprawy po recenzji Zadania 12 ────────────────────────────────────
#
# Kafelek trakowni renderuje się na zakładce Dashboard, która jest
# prefetchowana od razu (jest w HOT_TABS production-app-loader.js), a
# sawmill.css/sawmill.js ładują się leniwie dopiero przy pierwszym wejściu na
# zakładkę Trakownia. Więc przy typowym pierwszym wejściu do panelu ani akcent
# wizualny kafelka, ani kliknięcie ikony "otwórz" nie mogą zależeć od plików
# trakowni. Nie mamy tu przeglądarki (brak renderowania CSS/wykonania JS), więc
# jedyny sposób obronić się przed nawrotem tych dwóch błędów to sprawdzić w
# testach *którego pliku* dotyczą reguły/listener — czy leżą w plikach
# ładowanych zawsze, a nie w leniwych sawmill.css/sawmill.js.

def test_akcent_kafelka_jest_w_arkuszu_ladowanym_zawsze():
    """.il-station-sawmill musi być w production-panel.css (ładowany zawsze
    z panelem produkcji), nie w sawmill.css (leniwy) — inaczej przy pierwszym
    wejściu na Dashboard kafelek trakowni nie ma akcentu (border-left)."""
    panel_css = _plik(PRODUCTION_PANEL_CSS)
    assert '.il-station-sawmill {' in panel_css, \
        u'brak reguły .il-station-sawmill w production-panel.css'
    assert '.il-station-sawmill .il-station-kind' in panel_css, \
        u'brak reguły .il-station-sawmill .il-station-kind w production-panel.css'


def test_akcent_kafelka_nie_jest_zdublowany_w_sawmill_css():
    """Ta sama selekcja nie może istnieć w obu arkuszach — kolejność
    ładowania decydowałaby wtedy o wyniku. sawmill.css ma zawierać wyłącznie
    style samej zakładki, nie kafelka na dashboardzie."""
    sawmill_css = _plik(SAWMILL_CSS)
    assert '.il-station-sawmill {' not in sawmill_css
    assert '.il-station-sawmill .il-station-header' not in sawmill_css
    assert '.il-station-sawmill .il-station-bar-fill' not in sawmill_css
    assert '.il-station-sawmill .il-station-kind' not in sawmill_css


def test_obsluga_goto_tab_jest_w_pliku_ladowanym_zawsze():
    """[data-goto-tab] musi być obsłużone w production-app-loader.js (ładowany
    zawsze), delegacją na document — nie na pojedynczych elementach, żeby
    działało też dla treści wstawianej AJAX-em (np. odświeżenie Dashboardu)."""
    loader_js = _plik(LOADER)
    assert "'[data-goto-tab]'" in loader_js, \
        u'brak selektora [data-goto-tab] w production-app-loader.js'
    # Delegacja: nasłuch musi wisieć na document, a nie na elemencie kafelka.
    assert "document.addEventListener('click', this.handleTabClick)" in loader_js


def test_obsluga_goto_tab_nie_jest_zdublowana_w_sawmill_js():
    """Drugi listener na [data-goto-tab] w sawmill.js oznaczałby podwójne
    przełączenie zakładki po wejściu na Trakownię (oba nasłuchy trafione tym
    samym kliknięciem)."""
    sawmill_js = _plik(SAWMILL_JS)
    assert 'bindGotoTabLinks' not in sawmill_js
    assert "closest('[data-goto-tab]')" not in sawmill_js
    assert "getAttribute('data-goto-tab')" not in sawmill_js
