# -*- coding: utf-8 -*-
"""
Gwiazdki zamówień w Logistyce (priorytety produkcji, krok K4a; spec 7.2): kolumna „★” w liście zamówień z wyborem
0–5 przez wspólny komponent `window.Priorytety` i gwiazdki przy przystankach w edytorze trasy (tylko odczyt).

Pole `gwiazdki` w JSON listy i przystanków sprawdzamy klientem testowym (tests/logistyka_fixtures.py). Frontu nie da
się tu uruchomić (obraz testowy jest bez node'a), więc `logistics.js`, `logistics-routes.js` i szablon zakładki
sprawdzamy strukturalnie na źródle (konwencja tests/test_logistyka_*_ui.py).
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from extensions import db
from modules.production.logistics import sposoby as s
from tests.logistyka_fixtures import BASE, app, client, zamowienie  # noqa: F401


# ── Task 1: pole `gwiazdki` w JSON Logistyki ──────────────────────────────────────────────────────────────────

def test_lista_logistyki_i_przystanki_maja_gwiazdki(app, client):
    with app.app_context():
        z_gwiazdkami = zamowienie(sposob=s.TRANSPORT, priority_stars=2)
        bez_gwiazdek = zamowienie(sposob=s.TRANSPORT)
        a, b = z_gwiazdkami.id, bez_gwiazdek.id

    lista = client.get(BASE + '/orders')
    assert lista.status_code == 200
    wiersze = {w['id']: w for w in lista.get_json()['orders']}
    assert wiersze[a]['gwiazdki'] == 2
    assert wiersze[b]['gwiazdki'] == 0

    rid = client.post(BASE + '/routes', json={'name': 'Kraków', 'date_from': '2026-10-01'}).get_json()['route']['id']
    assert client.post(BASE + '/routes/%d/stops' % rid, json={'order_ids': [a]}).status_code == 200
    trasa = client.get(BASE + '/routes/%d' % rid).get_json()['route']
    assert trasa['przystanki'][0]['zamowienie']['gwiazdki'] == 2


# ── Task 6: kolumna „★” w liście Logistyki i gwiazdki przy przystankach ───────────────────────────────────────

KORZEN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SZABLON_LOGISTYKI = os.path.join(KORZEN, 'modules', 'production', 'logistics', 'templates', 'logistics',
                                 'tab_content.html')
JS_LOGISTYKA = os.path.join(KORZEN, 'modules', 'production', 'logistics', 'static', 'js', 'logistics.js')
JS_TRASY = os.path.join(KORZEN, 'modules', 'production', 'logistics', 'static', 'js', 'logistics-routes.js')
CSS_LOGISTYKI = os.path.join(KORZEN, 'modules', 'production', 'logistics', 'static', 'css', 'logistics.css')
CSS_TRAS = os.path.join(KORZEN, 'modules', 'production', 'logistics', 'static', 'css', 'logistics-trasy.css')


def _zrodlo(sciezka):
    with open(sciezka, encoding='utf-8') as plik:
        return plik.read()


def _funkcja(js, naglowek):
    """Ciało funkcji w IIFE pliku logistyki (wcięcie 4 spacje) od nagłówka do zamykającego `}`."""
    assert naglowek in js, naglowek
    reszta = js[js.index(naglowek):]
    return reszta[:reszta.index('\n    }\n') + 6]


def test_tabela_logistyki_kolumna_gwiazdek_i_colspan():
    szablon = _zrodlo(SZABLON_LOGISTYKI)
    tabela = szablon[szablon.index('<table class="lg-tabela">'):]
    naglowek = tabela[:tabela.index('</thead>')]
    assert naglowek.count('<th scope="col"') == 11
    assert naglowek.index('lg-k-numer') < naglowek.index('lg-k-gwiazdki') < naglowek.index('lg-k-klient')
    assert 'data-lg-sort="gwiazdki"' in naglowek and 'data-nazwa="Gwiazdki"' in naglowek
    assert 'colspan="10"' not in szablon and 'colspan="11"' in szablon and 'colspan="5"' in szablon
    js = _zrodlo(JS_LOGISTYKA)
    assert 'colspan="10"' not in js and js.count('colspan="11"') == 2
    wiersz = _funkcja(js, '    function wierszHtml(w) {')
    assert (wiersz.index('<td class="lg-k-numer">') < wiersz.index('<td class="lg-k-gwiazdki">') <
            wiersz.index('<td class="lg-k-klient">'))
    sortowanie = js[js.index('const KOLUMNY_SORTOWANIA = {'):]
    sortowanie = sortowanie[:sortowanie.index('\n    };\n')]
    assert 'gwiazdki: {' in sortowanie
    fokus = js[js.index('const KLASY_FOKUSU = ['):]
    assert "'lg-gwiazdki'" in fokus[:fokus.index('];')]
    css = _zrodlo(CSS_LOGISTYKI)
    assert '.logistics-tab .lg-k-gwiazdki' in css and '.lg-gwiazdki:focus-visible' in css


def test_logistyka_gwiazdki_przez_wspolny_komponent():
    js = _zrodlo(JS_LOGISTYKA)
    komorka = _funkcja(js, '    function komorkaGwiazdek(w, anulowane) {')
    assert 'data-lg-akcja="gwiazdki"' in komorka and 'window.Priorytety' in komorka
    galaz = komorka[komorka.index('if (!P || w.zamkniete || anulowane || w.wydane)'):]
    assert 'is-tylko-odczyt' in galaz.splitlines()[0]
    assert "aria-disabled=\"true\"" in komorka and 'aria-label="\' + esc(' in komorka
    assert "case 'gwiazdki':" in js
    zmiana = _funkcja(js, '    async function zmienGwiazdki(w, przycisk) {')
    assert 'Priorytety.wybierzGwiazdki(' in zmiana.replace('P.wybierzGwiazdki(', 'Priorytety.wybierzGwiazdki(')
    assert zmiana.count('ustawGwiazdki(') == 1
    assert "getAttribute('aria-disabled') === 'true'" in zmiana and 'stan.wysylane.has(w.id)' in zmiana
    assert "pokazKomunikat('blad'" in zmiana and 'finally' in zmiana
    assert 'stan.wysylane.delete(w.id);' in zmiana[zmiana.index('finally'):]
    # Lista obiektów mogła się w trakcie zapisu podmienić — gwiazdki trafiają do bieżącego wiersza.
    assert 'const biezacy = znajdz(w.id);' in zmiana
    # Zmiana z innego miejsca (Lista produkcyjna) aktualizuje wiersz bez przeładowania listy.
    assert re.search(r"\.on\('priorytety:zmiana'", js) and "off('priorytety:zmiana'" not in js
    zniszcz = js[js.index('function zniszcz('):]
    assert 'odpinijPriorytety()' in zniszcz[:zniszcz.index('\n    }\n')]
    assert 'fetch(' not in zmiana and '/priorytety/' not in js


def test_przystanek_pokazuje_gwiazdki():
    przystanek = _funkcja(_zrodlo(JS_TRASY), '    function przystanekHtml(z, indeks, ile, numer, edyt, status) {')
    galaz = przystanek[przystanek.index('z.gwiazdki > 0'):]
    galaz = galaz[:galaz.index(": '')")]
    assert 'lg-przystanek-gwiazdki' in galaz and "esc('Gwiazdki zamówienia: ' + z.gwiazdki)" in galaz
    assert '<button' not in galaz and 'Priorytety' not in przystanek
    assert '.lg-przystanek-gwiazdki' in _zrodlo(CSS_TRAS)


def test_wersje_skryptow_logistyki_podbite():
    szablon = _zrodlo(SZABLON_LOGISTYKI)
    js = re.search(r"js/logistics\.js'\) \}\}\?v=(\w+)\"", szablon)
    trasy = re.search(r"js/logistics-routes\.js'\) \}\}\?v=(\w+)\"", szablon)
    assert js and js.group(1) > '20261004a', js and js.group(1)
    assert trasy and trasy.group(1) > '20261004b1', trasy and trasy.group(1)


# ── K4-poprawka-1: kolumna „★” chowana w wąskim widoku ────────────────────────────────────────────────────────

def _blok_container(css, naglowek):
    """Ciało reguły `@container …` od nagłówka do zamykającej `}` w pierwszej kolumnie."""
    assert naglowek in css, naglowek
    reszta = css[css.index(naglowek):]
    return reszta[:reszta.index('\n}\n') + 2]


def test_kolumna_gwiazdek_chowana_gdy_tabela_przewija_sie_w_bok():
    """Decyzja Konrada 5.10 (pytanie 1 raportu K4a): w wąskim widoku (lista obok mapy przy 1100–1440 px, mapa nad
    listą, tablet) kolumna ★ znika. Próg = najwęższa ramka tabeli (kontener `lg-tabela`), w której tabela z ★ mieści
    się bez przewijania w bok: pomiar K4-poprawka-1 na kopii danych — 1016 px widocznej ramki (węziej tabela z ★
    potrzebuje 858–1016 px) plus pionowy suwak, który zapytanie kontenera wlicza (do 17 px) → 1035 px. Szeroki widok bez zmian (1920 px okna: lista ~1070–1230 px); gwiazdki zostają w Liście
    produkcyjnej i przy przystankach trasy."""
    css = _zrodlo(CSS_LOGISTYKI)
    szeroki = _blok_container(css, '@container lg-tabela (min-width: 1100px) {')
    assert 'lg-k-gwiazdki' not in szeroki
    waski = _blok_container(css, '@container lg-tabela (max-width: 1035px) {')
    regula = re.search(r'\.logistics-tab \.lg-tabela th\.lg-k-gwiazdki,\s*'
                       r'\.logistics-tab \.lg-tabela td\.lg-k-gwiazdki \{ display: none; \}', waski)
    assert regula, waski
    # Jedyne chowanie kolumny ★ — reszta arkusza jej nie ukrywa, a stare zwężenie ★ w bloku ≤ 860 px znika
    # (kolumny tam już nie ma).
    assert len(re.findall(r'lg-k-gwiazdki[^{}]*\{[^}]*display:\s*none', css)) == 1
    assert 'lg-k-gwiazdki' not in _blok_container(css, '@container lg-tabela (max-width: 860px) {')
    # Wiersze szczegółów i stanu dalej na 11 kolumn (ukryta kolumna jak `lg-k-adres` w wąskim układzie).
    assert _zrodlo(JS_LOGISTYKA).count('colspan="11"') == 2
    szablon = _zrodlo(SZABLON_LOGISTYKI)
    wersja = re.search(r"css/logistics\.css'\) \}\}\?v=(\w+)\"", szablon)
    assert wersja and wersja.group(1) > '20261005a', wersja and wersja.group(1)
