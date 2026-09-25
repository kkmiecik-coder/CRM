# -*- coding: utf-8 -*-
import os
import re

from tests.logistyka_fixtures import BASE, app, client  # noqa: F401

LOG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   'modules', 'production', 'logistics')


def _plik(*sciezka):
    return open(os.path.join(LOG, *sciezka), encoding='utf-8').read()


def _js():
    katalog = os.path.join(LOG, 'static', 'js')
    return ''.join(open(os.path.join(katalog, f), encoding='utf-8').read()
                   for f in os.listdir(katalog) if f.endswith('.js'))


def test_podzakladki_i_widoki():
    html = _plik('templates', 'logistics', 'tab_content.html')
    for widok in ('dashboard', 'routes', 'fleet'):
        assert 'data-logistics-view="{}"'.format(widok) in html
        assert 'data-lg-widok="{}"'.format(widok) in html
    assert 'data-skrypt-trasy=' in html
    assert 'js/logistics-fleet.js' in html and 'css/logistics-trasy.css' in html
    for cdn in ('unpkg.com', 'cdn.jsdelivr', 'cdnjs'):
        assert cdn not in html


def test_mapa_ma_widok_tras_i_fabryke_podkladu():
    mapa = _plik('static', 'js', 'logistics-map.js')
    for fraza in ('ustawWidok', 'renderTrasy', 'onWyborTrasy', 'nowaWarstwaPodkladu'):
        assert fraza in mapa, fraza


def test_js_uzywa_api_tras_i_floty():
    js = _js()
    for fraza in ('/routes/map', '/availability', '/stops/order', '/approve', '/revert',
                  '/complete', '/restore', '/routimo', '/vehicles', '/drivers',
                  'bez_trasy', 'hurt-trasa', 'usunieto_z_trasy', 'dragstart', '(zajęty',
                  'window.LogisticsRoutes', 'window.LogisticsFleet', 'komunikat:', 'pokazWidok'):
        assert fraza in js, fraza
    assert 'BaseLinker' not in js and 'unpkg.com' not in js


# ─── Poza briefem: szablon renderuje się z nowymi adresami i pliki istnieją ───

def test_zakladka_renderuje_sie_z_trasami_i_flota(client):  # noqa: F811
    """Błąd Jinja albo literówka w url_for nowego pliku wyszłaby dopiero na produkcji."""
    r = client.get(BASE + '/tab-content')
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    for plik in ('js/logistics-routes.js', 'js/logistics-fleet.js', 'css/logistics-trasy.css'):
        m = re.search(r'="([^"?]+' + re.escape(plik) + r')\?v=\w+"', html)
        assert m, plik
        statyka = client.get(m.group(1))
        assert statyka.status_code == 200, plik
        statyka.close()
    # Obecna treść Dashboardu w całości w panelu „dashboard”, przed panelem tras.
    assert html.index('data-logistics-view="dashboard"') < html.index('class="lg-liczniki"') \
        < html.index('class="lg-uklad"') < html.index('data-logistics-view="routes"')
    # Przełącznik widoków mapy stoi w dotychczas pustym miejscu nagłówka mapy.
    widoki = html[html.index('data-lg-mapa="widoki"'):]
    widoki = widoki[:widoki.index('</div>')]
    assert 'data-lg-mapa-widok="zamowienia"' in widoki and 'data-lg-mapa-widok="trasy"' in widoki


def test_zakladki_maja_role_i_klawiature():
    html = _plik('templates', 'logistics', 'tab_content.html')
    naglowek = html[html.index('class="lg-podzakladki"'):]
    naglowek = naglowek[:naglowek.index('</div>')]
    assert naglowek.count('role="tab"') == 3 and naglowek.count('aria-selected=') == 3
    for widok in ('dashboard', 'routes', 'fleet'):
        assert 'aria-controls="lg-widok-{}"'.format(widok) in naglowek
        assert 'id="lg-widok-{}"'.format(widok) in html
    lista = _plik('static', 'js', 'logistics.js')
    assert "'logistyka.widok'" in lista          # ostatnia podzakładka w localStorage
    assert 'ArrowRight' in lista and 'ArrowLeft' in lista


def test_okna_tras_i_floty_to_natywne_dialogi():
    html = _plik('templates', 'logistics', 'tab_content.html')
    for okno in ('trasa-dodaj-dialog', 'trasa-wykonaj-dialog', 'pojazd-dialog'):
        start = html.index('data-lg="{}"'.format(okno))
        znacznik = html[html.rindex('<dialog', 0, start):html.index('>', start)]
        assert 'class="lg-dialog' in znacznik and 'aria-labelledby=' in znacznik, okno
    # Poza panelami podzakładek — „Dodaj do trasy…” otwiera się ze schowanymi Trasami.
    assert html.index('data-lg="trasa-dodaj-dialog"') > html.index('data-logistics-view="fleet"')


def test_wykonanie_trasy_zawsze_wysyla_liste_dostarczonych():
    """Addendum do Task 3: bez klucza API uznałby za dostarczone wszystkie bieżące przystanki."""
    js = _plik('static', 'js', 'logistics-routes.js')
    assert 'delivered_order_ids:' in js


def test_nowe_pliki_sprzataja_po_sobie():
    trasy = _plik('static', 'js', 'logistics-routes.js')
    flota = _plik('static', 'js', 'logistics-fleet.js')
    for js, nazwa in ((trasy, 'LogisticsRoutes'), (flota, 'LogisticsFleet')):
        assert 'window.{0} && typeof window.{0}.zniszcz'.format(nazwa) in js, nazwa
        assert 'delete window.{}'.format(nazwa) in js, nazwa
    assert 'mapka.remove()' in trasy            # mapka edytora niszczona razem z edytorem
    assert "credentials: 'same-origin'" in trasy and "credentials: 'same-origin'" in flota
