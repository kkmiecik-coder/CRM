# -*- coding: utf-8 -*-
"""Spojnosc nawigacji po przemianowaniu zakladki.

Sidebar jest wlaczany przez KAZDA zakladke aplikacji, w tym Klientow, ktorzy
nie maja ani jednego testu. Bledna nazwa endpointu w url_for() wywalilaby
BuildError na kazdej stronie, a 1960 zielonych testow nic by o tym nie
powiedzialo. Dlatego sprawdzamy nazwy endpointow wprost ze zrodla szablonu.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from flask import Flask

from modules.reports import reports_bp

KORZEN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SIDEBAR = os.path.join(KORZEN, 'modules', 'sidebar', 'sidebar.html')
REPORTS_JS = os.path.join(KORZEN, 'modules', 'reports', 'static', 'js', 'reports.js')
REPORTS_HTML = os.path.join(KORZEN, 'modules', 'reports', 'templates', 'reports.html')


@pytest.fixture()
def zrodlo_sidebara():
    return open(SIDEBAR, encoding='utf-8').read()


@pytest.fixture()
def endpointy_reports():
    """Wszystkie endpointy, ktore blueprint reports faktycznie rejestruje."""
    app = Flask(__name__)
    app.register_blueprint(reports_bp)
    return {r.endpoint for r in app.url_map.iter_rules()}


def test_sidebar_ma_nowa_nazwe_w_obu_miejscach(zrodlo_sidebara):
    """Desktop i mobile — spec 6.6 mowi wprost o dwoch miejscach.

    Trzy wystapienia, nie dwa: wersja desktopowa ma i tooltip, i etykiete,
    a mobilna sama etykiete."""
    assert zrodlo_sidebara.count('Analiza sprzedażowa') == 3
    assert zrodlo_sidebara.count('data-sidebar-tooltip="Analiza sprzedażowa"') == 1
    assert zrodlo_sidebara.count('>Analiza sprzedażowa<') == 2


def test_sidebar_nie_ma_juz_starej_nazwy(zrodlo_sidebara):
    assert 'Raport sprzedażowy' not in zrodlo_sidebara
    assert '<span>Raport</span>' not in zrodlo_sidebara


def test_sidebar_prowadzi_do_dashboardu_a_nie_do_starej_tabeli(zrodlo_sidebara):
    assert zrodlo_sidebara.count("url_for('reports.analiza')") == 2
    assert "url_for('reports.reports_home')" not in zrodlo_sidebara


def test_kazdy_endpoint_reports_wolany_z_sidebara_istnieje(zrodlo_sidebara, endpointy_reports):
    """Test, ktory lapie literowke, zanim wywali sie cala aplikacja."""
    wolane = set(re.findall(r"url_for\('(reports\.[a-z_]+)'", zrodlo_sidebara))
    assert wolane, 'sidebar przestal wolac cokolwiek z reports — sprawdz zmiane'
    for endpoint in wolane:
        assert endpoint in endpointy_reports, f'sidebar wola nieistniejacy {endpoint}'


LISTA_AKTYWNYCH = ("request.endpoint in ['reports.analiza', 'reports.eksplorator', "
                   "'reports.arkusz', 'reports.reports_home']")


def test_stan_aktywny_obejmuje_cala_zakladke(zrodlo_sidebara):
    """Eksplorator, arkusz i STARA tabela to jedna pozycja menu — kazda z nich
    ma ja podswietlac.

    reports_home jest tu, bo stara zakladka wciaz jest osiagalna: przyciskami
    „Pobierz zamowienia" i „Otworz mape wojewodztw" z dashboardu oraz „Otworz
    dotychczasowa tabele" z arkusza. Bez tego wpisu na /reports/ nie
    podswietlala sie ani jedna pozycja menu (zweryfikowane renderem: 0
    aktywnych <li>, przy 1 na /reports/analiza i /reports/arkusz)."""
    assert LISTA_AKTYWNYCH in zrodlo_sidebara
    assert zrodlo_sidebara.count(LISTA_AKTYWNYCH) == 2


def test_sidebar_podswietla_stara_tabele_ale_do_niej_nie_prowadzi(zrodlo_sidebara):
    assert "'reports.reports_home'" in LISTA_AKTYWNYCH
    assert "url_for('reports.reports_home')" not in zrodlo_sidebara


def test_stara_trasa_nadal_istnieje(endpointy_reports):
    """Plan B nie rusza starej zakladki — zastepuje ja Plan C."""
    assert 'reports.reports_home' in endpointy_reports


def test_wszystkie_nowe_trasy_sa_zarejestrowane(endpointy_reports):
    for endpoint in ('reports.analiza', 'reports.eksplorator', 'reports.arkusz',
                     'reports.api_analytics', 'reports.api_eksplorator'):
        assert endpoint in endpointy_reports


def _hak_mapy(js):
    """Fragment reports.js, ktory obsluguje wejscie /reports/?mapa=1."""
    znacznik = "parametry.get('mapa') === '1'"
    assert znacznik in js, 'reports.js przestal obslugiwac ?mapa=1'
    # Od obiektu, na ktorym wisi nasluch, az do wywolania modala. Cofamy sie
    # o kilkanascie znakow, zeby zlapac `window.` / `document.` przed nazwa.
    poczatek = js.rindex('addEventListener', 0, js.index(znacznik))
    return js[max(0, poczatek - 16):js.index(znacznik) + 400]


def test_stara_zakladka_otwiera_mape_na_zadanie():
    """Wyjscie „Otworz mape wojewodztw" prowadzi do /reports/?mapa=1 — stara
    strona ma na to zareagowac, inaczej tekst przycisku klamie."""
    js = open(REPORTS_JS, encoding='utf-8').read()
    assert 'openVoivodeshipsModal' in _hak_mapy(js)
    assert 'URLSearchParams' in js


def test_hak_mapy_czeka_na_load_a_nie_na_DOMContentLoaded():
    """Sam grep po stringach swieci na zielono nad funkcja, ktora NIE DZIALA.

    reports.js idzie <script src> w reports.html PRZED inline'owym blokiem,
    ktory wola reportsManager.init() — a dopiero init() tworzy
    window.voivodeshipsManager. Nasluchy DOMContentLoaded odpalaja sie
    w kolejnosci rejestracji, wiec hak z reports.js bylby PIERWSZY: menedzera
    jeszcze nie ma, openVoivodeshipsModal() wpada w galaz `else` i tylko
    wypisuje blad w konsoli. Modal nigdy sie nie otwiera.

    'load' odpala sie po obu naslachach DOMContentLoaded — i tylko dlatego
    wejscie z dashboardu dziala."""
    js = open(REPORTS_JS, encoding='utf-8').read()
    hak = _hak_mapy(js)
    assert "window.addEventListener('load'" in hak
    assert 'DOMContentLoaded' not in hak


def test_kolejnosc_skryptow_w_reports_html_uzasadnia_nasluch_na_load():
    """Gdyby inline'owy init() przeniesiono PRZED reports.js, powyzszy test
    przestalby cokolwiek chronic — pilnujemy wiec zalozenia, nie tylko
    wniosku."""
    html = open(REPORTS_HTML, encoding='utf-8').read()
    assert html.index("filename='js/reports.js'") < html.index('reportsManager.init()')
