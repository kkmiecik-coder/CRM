# -*- coding: utf-8 -*-
"""Runda 2 logistyki (spec 2.1): logistyka poza pipeline'em dashboardu produkcji — pasek pod
listą stanowisk zamiast bramki na szynie. Testy tekstowe jak tests/test_dashboard_krawedzie.py;
sam pasek renderujemy Jinją (fragment między znacznikami), bez całego dashboardu."""
import os
import re

import pytest
from jinja2 import Environment

KORZEN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROD = os.path.join(KORZEN, 'modules', 'production')
SZABLON = os.path.join(PROD, 'templates', 'components', 'dashboard-tab-content.html')
PANEL_HTML = os.path.join(PROD, 'templates', 'panel', 'dashboard.html')
DASHBOARD_JS = os.path.join(PROD, 'static', 'js', 'modules', 'dashboard-module.js')
PANEL_CSS = os.path.join(PROD, 'static', 'css', 'production-panel.css')


def _plik(sciezka):
    with open(sciezka, encoding='utf-8') as f:
        return f.read()


def _pasek():
    html = _plik(SZABLON)
    start = html.index("{# ─── LOGISTYKA: pasek pod pipeline'em")
    return html[start:html.index('{# ─── /LOGISTYKA ─── #}', start)]


@pytest.mark.parametrize('n, spokoj', [(0, True), (12, False)])
def test_pasek_pokazuje_liczbe_albo_spokoj(n, spokoj):
    html = Environment(autoescape=True).from_string(_pasek()).render(
        dashboard_stats={'logistics': {'pending_count': n}},
        url_for=lambda endpoint, **k: '/production/')
    assert ('il-logistyka--spokoj' in html) is spokoj
    assert 'id="logistics-pending">%d<' % n in html               # id zostaje w obu stanach
    assert 'bez sposobu dostawy' in html and 'wszystkie zamówienia mają sposób dostawy' in html
    assert 'href="/production/?tab=logistics"' in html and 'Otwórz Logistykę' in html


@pytest.mark.parametrize('do_weryfikacji, problemy', [(0, 0), (5, 2)])
def test_pasek_pokazuje_weryfikacje(do_weryfikacji, problemy):
    html = Environment(autoescape=True).from_string(_pasek()).render(
        dashboard_stats={'logistics': {'pending_count': 0, 'verification_pending': do_weryfikacji,
                                       'verification_problems': problemy}},
        url_for=lambda endpoint, **k: '/production/')
    assert 'id="verification-pending">%d<' % do_weryfikacji in html
    assert 'id="verification-problems">%d<' % problemy in html
    assert 'Do weryfikacji' in html and 'Problemy' in html


def test_odswiezanie_paska_weryfikacji():
    js = _plik(DASHBOARD_JS)
    assert 'updateVerification(' in js and 'data.data.verification' in js
    assert "getElementById('verification-pending')" in js
    assert "getElementById('verification-problems')" in js


def test_pasek_pod_pipelineem_w_tej_samej_karcie():
    html = _plik(SZABLON)
    assert 'data-station="logistics"' not in html and 'il-station--gate' not in html
    pasek = _pasek()
    karta = html[html.index('class="dashboard-card stations-card"'):html.index('{# ═══ RIGHT STACK ═══ #}')]
    assert pasek in karta
    assert karta.index('data-station="packaging"') < karta.index(pasek)
    assert '<span class="il-cat-count">7 stanowisk</span>' in html
    for czego_nie_ma in ('-bar-fill', '-tablet-badge', 'station_crew', 'today-m3', 'data-station='):
        assert czego_nie_ma not in pasek, czego_nie_ma


def test_szyna_bez_wezla_logistyki():
    js = _plik(DASHBOARD_JS)
    szyna = js[js.index('rysujSzyneProcesu() {'):js.index('uruchomPrzeplyw() {')]
    kody = re.findall(r"'(\w+)'", re.search(r"const kody = \[([^\]]*)\]", szyna).group(1))
    assert kody == ['cutting', 'assembly', 'gluing', 'formatting', 'edges', 'painting', 'packaging']
    assert 'logistics' not in szyna and '#6366f1' not in szyna and 'Y(7)' not in szyna
    assert 'Y(PAK)' in szyna


def test_css_bez_bramki_i_ze_stanem_spokoju():
    css = _plik(PANEL_CSS)
    assert '.il-rail-gate' not in css and '.il-station[data-station="logistics"]' not in css
    for selektor in ('.il-logistyka {', '.il-logistyka--spokoj', '.il-logistyka-otworz'):
        assert selektor in css, selektor


def test_wersje_zasobow_dashboardu_podbite():
    html = _plik(PANEL_HTML)
    m = re.search(r"filename='js/modules/dashboard-module\.js'\) \}\}\?v=(\w+)", html)
    assert m and m.group(1) != '20260410'
    assert re.search(r"filename='css/production-panel\.css'\) \}\}\?v=\w+", html)


# --- Błąd licznika Weryfikacji: „—” zamiast zera i brak alarmu (fala końcowa 4.3, F5, Ruling 18) ---------

def _pasek_z(**logistyka):
    return Environment(autoescape=True).from_string(_pasek()).render(
        dashboard_stats={'logistics': dict(pending_count=0, **logistyka)},
        url_for=lambda endpoint, **k: '/production/')


def test_pasek_z_bledem_licznika_pokazuje_kreski_bez_alarmu():
    html = _pasek_z(verification_pending=None, verification_problems=None)
    assert 'id="verification-pending">—<' in html and 'id="verification-problems">—<' in html
    assert 'is-alarm' not in html


@pytest.mark.parametrize('problemy, alarm', [(0, False), (1, True), (7, True)])
def test_pasek_alarm_tylko_przy_problemach_wiekszych_od_zera(problemy, alarm):
    html = _pasek_z(verification_pending=3, verification_problems=problemy)
    assert ('class="il-logistyka-weryfikacja-problemy is-alarm"' in html) is alarm
    assert 'id="verification-problems">%d<' % problemy in html


def test_pasek_z_jednym_licznikiem_none_nie_psuje_drugiego():
    html = _pasek_z(verification_pending=5, verification_problems=None)
    assert 'id="verification-pending">5<' in html and 'id="verification-problems">—<' in html
    assert 'is-alarm' not in html


def test_js_paska_weryfikacji_pokazuje_kreski_przy_bledzie_licznika():
    js = _plik(DASHBOARD_JS)
    fn = js[js.index('    updateVerification(dane) {'):]
    fn = fn[:fn.index('\n    }\n')]
    assert "if (!dane || typeof dane !== 'object') return;" not in fn   # null nie zostawia starych liczb
    assert fn.count("'—'") == 2                                         # „Do weryfikacji” i „Problemy”
    assert "classList.toggle('is-alarm', liczba(wartosci.problems) && wartosci.problems > 0)" in fn


def test_skrypt_dashboardu_ma_podbita_wersje():
    html = _plik(PANEL_HTML)
    m = re.search(r"js/modules/dashboard-module\.js'\) \}\}\?v=(\w+)", html)
    assert m and m.group(1) >= '20261001b'
