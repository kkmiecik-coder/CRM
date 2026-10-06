# -*- coding: utf-8 -*-
"""Runda 2 (spec 2.6), interfejs: kierowcy we Flocie i wybór kierowcy w edytorze trasy."""
import os
import re

from tests.logistyka_fixtures import BASE, app, client  # noqa: F401

LOG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   'modules', 'production', 'logistics')


def _plik(*sciezka):
    return open(os.path.join(LOG, *sciezka), encoding='utf-8').read()


def _funkcja(js, nazwa):
    """Treść funkcji z IIFE (wcięcie 4 spacje) — od nagłówka do zamykającej klamry."""
    start = js.index('function ' + nazwa + '(')
    return js[start:js.index('\n    }\n', start)]


def _wersja(html, plik):
    m = re.search(r"filename='" + re.escape(plik) + r"'\) \}\}\?v=(\w+)", html)
    assert m, plik
    return m.group(1)


def test_panel_kierowcow_we_flocie():
    html = _plik('templates', 'logistics', 'tab_content.html')
    sekcja = html[html.index('class="lg-flota-kierowcy"'):]
    sekcja = sekcja[:sekcja.index('</section>')]
    assert '>Kierowcy</h2>' in sekcja
    # „Dodaj kierowcę” nad listą.
    assert sekcja.index('data-lg-flota-akcja="dodaj-kierowce"') < sekcja.index('data-lg-flota="kierowcy"')
    assert 'każdy aktywny pracownik' not in html
    flota = _plik('static', 'js', 'logistics-fleet.js')
    wiersz = _funkcja(flota, 'kierowcaHtml')
    assert 'fa-trash-can' in wiersz and 'data-lg-flota-akcja="usun-kierowce"' in wiersz
    assert 'lg-kierowca-usun' in wiersz and "odmiana(trasy.length, ['trasa', 'trasy', 'tras'])" in wiersz
    assert 'Dodaj kierowców spośród pracowników.' in _funkcja(flota, 'renderujKierowcow')
    assert 'renderujKierowcow();' in _funkcja(flota, 'renderuj')
    css = _plik('static', 'css', 'logistics-trasy.css')
    assert '.logistics-tab .lg-kierowca-usun {' in css


def test_okno_dodawania_kierowcy():
    html = _plik('templates', 'logistics', 'tab_content.html')
    start = html.index('data-lg="kierowca-dialog"')
    znacznik = html[html.rindex('<dialog', 0, start):html.index('>', start)]
    assert 'class="lg-dialog lg-dialog--kierowca"' in znacznik and 'aria-labelledby=' in znacznik
    okno = html[start:html.index('</dialog>', start)]
    for fraza in ('data-lg-flota="kandydaci-q"', 'type="search"', 'data-lg-flota="kandydaci"',
                  'data-lg-flota="kandydaci-stan"', 'id="lg-kierowca-blad"', 'data-lg-flota-akcja="kierowca-zamknij"'):
        assert fraza in okno, fraza
    flota = _plik('static', 'js', 'logistics-fleet.js')
    assert "zapytanie('/drivers/candidates'" in _funkcja(flota, 'wczytajKandydatow')
    dodaj = _funkcja(flota, 'dodajKierowce')
    assert "zapytanie('/drivers', { metoda: 'POST', dane: { worker_id: id } })" in dodaj
    assert 'przyjmijKierowcow(odp.drivers)' in dodaj
    assert 'bezOgonkow(k.nazwa).includes(q)' in _funkcja(flota, 'renderujKandydatow')
    assert "new CustomEvent('logistics:flota-zmieniona'" in _funkcja(flota, 'przyjmijKierowcow')
    css = _plik('static', 'css', 'logistics-trasy.css')
    assert '.logistics-tab .lg-dialog--kierowca [hidden]' in css


def test_zdjecie_kierowcy_z_potwierdzeniem_tras():
    flota = _plik('static', 'js', 'logistics-fleet.js')
    usun = _funkcja(flota, 'usunKierowce')
    assert 'window.confirm(potwierdzenieUsuniecia(k))' in usun and "metoda: 'DELETE'" in usun
    assert usun.index('window.confirm(') < usun.index("metoda: 'DELETE'")
    potwierdz = _funkcja(flota, 'potwierdzenieUsuniecia')
    assert 'k.trasy' in potwierdz and 'dalej będzie kierowcą' in potwierdz


def test_wybor_kierowcy_trasy():
    trasy = _plik('static', 'js', 'logistics-routes.js')
    selecty = _funkcja(trasy, 'renderujSelecty')
    assert "' (nie jest już kierowcą)'" in selecty
    assert '!!k.zajety || !!k.nie_kierowca' in selecty          # widoczny, ale bez ponownego wyboru
    assert 'kierowca && kierowca.nie_kierowca' in selecty
    blad = trasy[trasy.index('const bladZasobu'):]
    assert 'nie jest kierowcą' in blad[:blad.index(';\n')]


def test_zakladka_renderuje_sie_z_oknem_kierowcy(client):  # noqa: F811
    r = client.get(BASE + '/tab-content')
    assert r.status_code == 200 and 'data-lg="kierowca-dialog"' in r.get_data(as_text=True)


def test_wersje_podbite():
    html = _plik('templates', 'logistics', 'tab_content.html')
    assert _wersja(html, 'js/logistics-fleet.js') != '20260926a'
    assert _wersja(html, 'js/logistics-routes.js') != '20260928b'
    assert _wersja(html, 'css/logistics-trasy.css') != '20260926c'
