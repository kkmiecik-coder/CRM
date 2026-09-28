# -*- coding: utf-8 -*-
"""Runda 2 (spec 2.2, 2.3, 2.7): sposób dostawy w dymku pinezki, odstęp pola wyboru, kółko
na mapce trasy."""
import os
import re

LOG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   'modules', 'production', 'logistics')


def _plik(*sciezka):
    return open(os.path.join(LOG, *sciezka), encoding='utf-8').read()


def _funkcja(js, nazwa):
    start = js.index('function ' + nazwa + '(')
    return js[start:js.index('\n    }\n', start)]


def _regula_css(css, selektor):
    start = css.index(selektor + ' {')
    return css[start:css.index('}', start)]


def _wersja(html, plik):
    m = re.search(r"filename='" + re.escape(plik) + r"'\) \}\}\?v=(\w+)", html)
    assert m, plik
    return m.group(1)


def _etykiety(js):
    blok = js[js.index('const ETYKIETY = {'):]
    return re.findall(r"(\w+): '([^']+)'", blok[:blok.index('};')])


def test_dymek_ma_wybor_sposobu_jak_wiersz_listy():
    mapa, lista = _plik('static', 'js', 'logistics-map.js'), _plik('static', 'js', 'logistics.js')
    dymek = _funkcja(mapa, 'dymekHtml')
    assert 'data-lg-mapa-sposob' in dymek and 'opcjeSposobu(sposob)' in dymek
    assert 'powodBlokadySposobu(z)' in dymek and 'Sposób dostawy zamówienia' in dymek
    # Te same podpisy i kolejność co select wiersza (selectSposobu: „Nie ustawiono” + SPOSOBY).
    assert _etykiety(mapa) == [('brak', 'Nie ustawiono')] + _etykiety(lista)
    assert "const NIE_USTAWIONO = 'Nie ustawiono';" in lista
    assert "['brak'].concat(SPOSOBY)" in _funkcja(mapa, 'opcjeSposobu')
    blokada = _funkcja(mapa, 'powodBlokadySposobu')
    for tekst in ('Zamówienie wydane klientowi. Sposobu dostawy nie można już zmienić.', 'Zamówienie anulowane.'):
        assert tekst in blokada and tekst in lista, tekst
    assert 'zapisywaneSposoby.has(z.id)' in blokada


def test_dymek_przerysowuje_wybor_po_kazdej_odpowiedzi():
    """Review Focus 3: odmowa w `bledy` przychodzi przy HTTP 200 — dymek zawsze od nowa z danych
    listy; select dymku nie może wyglądać dla delegacji listy jak select wiersza ani licznik."""
    mapa, lista = _plik('static', 'js', 'logistics-map.js'), _plik('static', 'js', 'logistics.js')
    dymek = _funkcja(mapa, 'dymekHtml')
    assert 'class="form-select form-select-sm lg-dymek-select"' in dymek
    assert not re.search(r'[" ]lg-sposob[" ]', dymek)
    assert 'data-lg-sposob' not in dymek and 'data-lg-akcja' not in dymek
    assert 'onSposob: onSposob' in mapa
    assert "addEventListener('change'" in _funkcja(mapa, 'podepnijDymek')
    wyslij = _funkcja(mapa, 'wyslijSposobZDymku')
    assert 'zapisywaneSposoby.add(id)' in wyslij and 'await cb(id, sposob)' in wyslij
    koniec = wyslij[wyslij.index('} finally {'):]
    assert 'zapisywaneSposoby.delete(id)' in koniec and 'odswiezDymek(id, fokus)' in koniec
    assert 'fetch(' not in wyslij and 'wyslij(' not in wyslij        # zapis tylko przez listę
    assert 'm.getPopup().update()' in _funkcja(mapa, 'odswiezDymek')
    assert 'm.onSposob(zmienSposobZMapy)' in _funkcja(lista, 'polaczZMapa')
    zmien = _funkcja(lista, 'zmienSposobZMapy')
    assert 'wyslijSposob([id], sposob)' in zmien and 'podsumujZmiany(wynik, true)' in zmien
    assert "pokazKomunikat('blad', 'Nie zmieniono sposobu dostawy zamówienia '" in zmien
    assert 'clearTimeout(oczekujaceSelecty.get(id))' in zmien


def test_pole_wyboru_ma_odstep_od_krawedzi():
    css = _plik('static', 'css', 'logistics.css')
    assert 'padding-left: 14px !important' in _regula_css(css, '.logistics-tab .lg-k-zaznacz')
    stan = _regula_css(css, '.logistics-tab .lg-tabela th.lg-k-stan,\n.logistics-tab .lg-tabela td.lg-k-stan')
    assert 'padding-right: 14px' in stan
    for prog, px in (('(max-width: 860px)', 12), ('(max-width: 760px)', 9)):
        blok = css[css.index('@container lg-tabela ' + prog):]
        blok = blok[:blok.index('\n}\n')]
        assert '.logistics-tab .lg-k-zaznacz { padding-left: %dpx !important; }' % px in blok, prog
        assert 'td.lg-k-stan { padding-right: %dpx; }' % px in blok, prog
    assert 'padding: 2px 14px 4px 66px;' in _regula_css(css, '.logistics-tab .lg-pozycje')


def test_mapka_trasy_przybliza_kolkiem_od_razu():
    trasy = _plik('static', 'js', 'logistics-routes.js')
    assert 'scrollWheelZoom: true' in _funkcja(trasy, 'zapewnijMapke')
    for fraza in ('scrollWheelZoom: false', 'scrollWheelZoom.enable', 'scrollWheelZoom.disable'):
        assert fraza not in trasy, fraza


def test_wersje_podbite():
    html = _plik('templates', 'logistics', 'tab_content.html')
    assert _wersja(html, 'css/logistics.css') != '20260925i'
    assert _wersja(html, 'js/logistics-map.js') != '20260926b'
    assert _wersja(html, 'js/logistics.js') not in ('20260928a', '20260928b')
    assert _wersja(html, 'js/logistics-routes.js') not in ('20260928b', '20260928c')
