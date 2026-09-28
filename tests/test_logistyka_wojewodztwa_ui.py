# -*- coding: utf-8 -*-
"""Runda 2 (spec 2.4, 2.5), interfejs: panel województw i przełączanie mapy przy filtrach."""
import os
import re

from modules.production.logistics import wojewodztwa
from tests.logistyka_fixtures import BASE, app, client  # noqa: F401

LOG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   'modules', 'production', 'logistics')


def _plik(*sciezka):
    return open(os.path.join(LOG, *sciezka), encoding='utf-8').read()


def _funkcja(js, nazwa):
    start = js.index('function ' + nazwa + '(')
    return js[start:js.index('\n    }\n', start)]


def _wersja(html, plik):
    m = re.search(r"filename='" + re.escape(plik) + r"'\) \}\}\?v=(\w+)", html)
    assert m, plik
    return m.group(1)


def test_panel_wojewodztw_w_szablonie(client):  # noqa: F811
    html = client.get(BASE + '/tab-content').get_data(as_text=True)
    panel = html[html.index('data-lg-woj="panel"'):]
    panel = panel[:panel.index('data-lg-woj="wyczysc"')]
    assert re.findall(r'data-lg-woj-pole value="([\w-]+)"', panel) == [i for i, _ in wojewodztwa.opcje()]
    assert re.findall(r'data-lg-woj-pole value="[\w-]+"><span>([^<]+)</span>', panel) == \
        [n for _, n in wojewodztwa.opcje()]
    assert 'wg kodu pocztowego, w przybliżeniu' in panel
    narzedzia = html[html.index('class="lg-narzedzia"'):html.index('data-lg="ile"')]
    assert narzedzia.index('data-lg-sposob="bez_trasy"') < narzedzia.index('data-lg-woj="przycisk"')
    assert 'aria-expanded="false"' in narzedzia and 'aria-controls="lg-woj-panel"' in narzedzia
    m = re.search(r'="([^"?]+js/logistics-wojewodztwa\.js)\?v=\w+"', html)
    assert m
    statyka = client.get(m.group(1))
    assert statyka.status_code == 200
    statyka.close()


def test_modul_wojewodztw_wysyla_zdarzenie_a_lista_filtruje():
    woj = _plik('static', 'js', 'logistics-wojewodztwa.js')
    lista = _plik('static', 'js', 'logistics.js')
    assert "new CustomEvent('logistics:wojewodztwa'" in _funkcja(woj, 'ogloszZmiane')
    assert "'Województwa (' + n + ')'" in _funkcja(woj, 'renderujPrzycisk')
    assert "e.key === 'Escape'" in woj and "'pointerdown'" in woj and "'focusout'" in woj
    assert 'localStorage' not in woj                                  # bez zapamiętywania (spec 2.5)
    assert 'window.LogisticsWojewodztwa && typeof window.LogisticsWojewodztwa.zniszcz' in woj
    assert 'delete window.LogisticsWojewodztwa' in woj
    assert "document.addEventListener('logistics:wojewodztwa', naWojewodztwa)" in lista
    assert "document.removeEventListener('logistics:wojewodztwa', naWojewodztwa)" in _funkcja(lista, 'zniszcz')
    assert "stan.filtr.woj.forEach((w) => params.append('woj', w))" in _funkcja(lista, 'wczytaj')
    assert 'stan.filtr.woj.length' in lista[lista.index('const zawezonyWidok'):][:200]
    assert "przyciskStanu('wyczysc-wojewodztwa', 'Wyczyść województwa')" in _funkcja(lista, 'pustyStan')
    zdejmij = _funkcja(lista, 'zdejmijFiltry')
    assert 'stan.filtr.woj = [];' in zdejmij and 'wyczyscWojewodztwa({ cicho: true })' in zdejmij


def test_filtry_przelaczaja_mape_a_wyszukiwarka_nie():
    """Review Focus 5: każda zmiana filtra zamówień (także zdjęcie) pokazuje na mapie zamówienia;
    wyszukiwarka i „także zamknięte” nie; nic nie wraca samo na „Trasy”."""
    js = _plik('static', 'js', 'logistics.js')
    mapa = _funkcja(js, 'mapaNaZamowienia')
    assert "m.widok() === 'trasy'" in mapa and "m.ustawWidok('zamowienia')" in mapa
    assert "ustawWidok('trasy')" not in js
    for nazwa in ('ustawSposobFiltra', 'ustawFiltrGeo', 'naWojewodztwa', 'zdejmijFiltry'):
        assert 'mapaNaZamowienia();' in _funkcja(js, nazwa), nazwa
    assert 'mapaNaZamowienia' not in _funkcja(js, 'zmianaFrazy')
    zmiana = js[js.index("root.addEventListener('change'"):]
    zmiana = zmiana[:zmiana.index('\n    });\n')]
    assert 'mapaNaZamowienia();' in zmiana[zmiana.index("t === el('etap')"):zmiana.index("t === el('geo')")]
    assert 'mapaNaZamowienia' not in zmiana[zmiana.index("t === el('zamkniete')"):zmiana.index("t === el('etap')")]
    klik = js[js.index("root.addEventListener('click'"):]
    klik = klik[:klik.index('\n    });\n')]
    for przypadek, jest in (("case 'pokaz-wszystkie':", True), ("case 'wszystkie-etapy':", True),
                            ("case 'wyczysc-wojewodztwa':", True), ("case 'szukaj-zamkniete':", False)):
        blok = klik[klik.index(przypadek):]
        assert ('mapaNaZamowienia();' in blok[:blok.index('break;')]) is jest, przypadek


def test_wersje_podbite():
    html = _plik('templates', 'logistics', 'tab_content.html')
    assert _wersja(html, 'js/logistics.js') != '20260928a'
    assert _wersja(html, 'css/logistics-trasy.css') not in ('20260926c', '20260928a')
    assert _wersja(html, 'js/logistics-wojewodztwa.js')
    assert html.index("filename='js/logistics.js'") < html.index("filename='js/logistics-wojewodztwa.js'")
