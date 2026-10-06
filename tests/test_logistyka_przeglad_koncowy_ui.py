# -*- coding: utf-8 -*-
"""
Fala poprawek FRONTENDU po przeglądzie całej gałęzi logistyki, przeglądzie Task 5 i oględzinach
rundy 2 (28.09.2026). Punkt przeglądu (W1, D1, …) w nagłówku każdej sekcji.

Frontu nie da się tu uruchomić (obraz testowy jest bez node'a), więc JS, CSS i szablony
sprawdzamy na źródle — kolejność i warunki, a nie sama obecność napisu. D6 dodatkowo przez API
cyklicznego odświeżania dashboardu produkcji.
"""
import os
import re

import pytest
from flask import Flask
from sqlalchemy.pool import StaticPool

from extensions import db
from modules.production.logistics import sposoby as s
from modules.production.models import (
    ProductionConfiguration, ProductionDevice, ProductionError, ProductionOrder, ProductionProduct,
    ProductionStationEvent, ProductionStationEventWorker, ProductionWorker, ProductionWorkerSession,
)
from modules.users.models import User
# configure_mappers() przy pierwszym zapytaniu konfiguruje CAŁY rejestr mapperów.
from modules.calculator.models import Multiplier  # noqa: F401
from modules.clients.models import Client  # noqa: F401
import modules.quotes.models  # noqa: F401
from tests.logistyka_fixtures import zamowienie

KORZEN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROD = os.path.join(KORZEN, 'modules', 'production')
LOG = os.path.join(PROD, 'logistics')


def _plik(*sciezka):
    with open(os.path.join(*sciezka), encoding='utf-8') as f:
        return f.read()


def _js(nazwa):
    return _plik(LOG, 'static', 'js', nazwa)


def _css():
    return _plik(LOG, 'static', 'css', 'logistics.css')


def _zakladka():
    return _plik(LOG, 'templates', 'logistics', 'tab_content.html')


def _panel():
    return _plik(PROD, 'templates', 'panel', 'dashboard.html')


def _funkcja(js, nazwa):
    """Treść funkcji z IIFE (wcięcie 4 spacje) — od nagłówka do zamykającej klamry."""
    start = js.index('function ' + nazwa + '(')
    return js[start:js.index('\n    }\n', start)]


def _metoda(js, nazwa):
    """Treść metody klasy (wcięcie 4 spacje): production-app-loader.js, dashboard-module.js."""
    start = js.index('\n    ' + nazwa + '(')
    return js[start:js.index('\n    }\n', start + 1)]


def _wersja(html, plik):
    m = re.search(r"filename='" + re.escape(plik) + r"'\) \}\}\?v=(\w+)", html)
    assert m, plik
    return m.group(1)


def _okno_kierowcy():
    html = _zakladka()
    start = html.index('data-lg="kierowca-dialog"')
    return html[start:html.index('</dialog>', start)]


# ── W1: skróty Ctrl+1…7 przy otwartym oknie modalnym i w polach ─────────────

def test_w1_skroty_zakladek_pomijaja_okno_modalne_i_pola_edycyjne():
    """Skrót przełączał zakładkę pod otwartym <dialog> — okno znikało razem z zakładką, a strona
    zostawała zablokowana (inert). Obie straże stoją przed wszystkim, co zjada klawisz."""
    skroty = _metoda(_plik(PROD, 'static', 'js', 'production-app-loader.js'), 'handleKeyboardShortcuts')
    # C-1 (przegląd końcowy 4.10): :modal w try/catch z zapasem dialog[open], straż = 'if (modalne) return;'.
    okno = skroty.index('if (modalne) return;')
    pole = skroty.index("closest('input, textarea, select, [contenteditable]')")
    for dalej in ('event.ctrlKey', 'event.preventDefault()', 'this.switchToTab('):
        assert okno < skroty.index(dalej) and pole < skroty.index(dalej), dalej
    assert 'return;' in skroty[pole:skroty.index('event.ctrlKey')]
    assert _wersja(_panel(), 'js/production-app-loader.js') >= '20260928a'


# ── D1: wybór w dymku, gdy dla zamówienia trwa zapis z wiersza, hurtu, „Wydane” ─

def test_d1_dymek_wie_o_zapisie_z_listy_i_blokuje_wybor():
    mapa, lista = _js('logistics-map.js'), _js('logistics.js')
    blokada = _funkcja(mapa, 'powodBlokadySposobu')
    wlasny = blokada.index("if (zapisywaneSposoby.has(z.id)) return 'Zapisywanie…';")
    z_listy = blokada.index("if (zapisWLiscie(z.id)) return 'Zapisuje się poprzednia zmiana…';")
    assert wlasny < z_listy < blokada.index("return '';")
    assert 'czyZapisywaneWLiscie(id)' in _funkcja(mapa, 'zapisWLiscie')
    assert 'czyZapisywaneWLiscie = null;' in _funkcja(mapa, 'zniszcz')
    api = mapa[mapa.index('const api = {'):]
    api = api[:api.index('};')]
    assert 'ustawCzyZapisywane: ustawCzyZapisywane,' in api
    assert 'odswiezDymek: (id) =>' in api and 'odswiezDymek(id, fokusWDymku(id))' in api
    # Lista podaje mapie swój stan zapisu (stan.wysylane: wiersz, hurt, „Wydane klientowi”)…
    assert 'const czyZapisywane = (id) => stan.wysylane.has(id);' in lista
    assert 'm.ustawCzyZapisywane(czyZapisywane)' in _funkcja(lista, 'polaczZMapa')
    assert 'm.odswiezDymek(id)' in _funkcja(lista, 'odswiezDymkiMapy')
    # …i przerysowuje otwarty dymek, gdy zapis się zaczyna i kiedy się kończy.
    wyslij = _funkcja(lista, 'wyslijSposob')
    assert wyslij.index('stan.wysylane.add(id)') < wyslij.index('odswiezDymkiMapy(ids)') < \
        wyslij.index('await zapytanie(')
    koniec = wyslij[wyslij.index('} finally {'):]
    assert koniec.index('stan.wysylane.delete(id)') < koniec.index('odswiezDymkiMapy(ids)')
    wydaj = _funkcja(lista, 'wydaj')
    assert wydaj.index('stan.wysylane.add(id)') < wydaj.index('odswiezDymkiMapy([id])') < \
        wydaj.index('await zapytanie(')
    # Zewnętrzny catch = ostatni (wewnętrzny łapie 409 „wymaga_potwierdzenia_problemu”, decyzja Konrada 4.10).
    sukces = wydaj[wydaj.index('podmienWiersze([dane.order]);'):wydaj.rindex('} catch (e) {')]
    assert 'odswiezDymkiMapy([id]);' in sukces                        # dymek zna już „wydane”
    assert 'odswiezDymkiMapy([id]);' in wydaj[wydaj.rindex('} catch (e) {'):]


def test_d1_wybor_z_dymku_w_trakcie_zapisu_mowi_poczekaj():
    """Dawniej cichy `return` — wybór ginął bez słowa, select wracał sam."""
    mapa, lista = _js('logistics-map.js'), _js('logistics.js')
    zmien = _funkcja(lista, 'zmienSposobZMapy')
    assert 'stan.wysylane.has(id)) return;' not in zmien
    galaz = zmien[zmien.index('if (stan.wysylane.has(id)) {'):]
    galaz = galaz[:galaz.index('\n        }\n')]
    assert ("pokazKomunikat('info', 'Poczekaj, aż zapisze się poprzednia zmiana zamówienia ' + w.numer + '.'"
            in galaz)
    assert 'return;' in galaz
    assert zmien.index('if (stan.wysylane.has(id)) {') < zmien.index('wyslijSposobZDecyzja([id], sposob, przepakowanie)')
    # Po odpowiedzi listy (także tej odmowie) dymek rysuje się od nowa z danych serwera.
    koniec = _funkcja(mapa, 'wyslijSposobZDymku')
    assert 'odswiezDymek(id, fokus)' in koniec[koniec.index('} finally {'):]


# ── D2: województwa zaznaczone, zanim wykonał się logistics.js ──────────────

def test_d2_pierwsze_pobranie_listy_bierze_wojewodztwa_z_panelu():
    lista = _js('logistics.js')
    start = lista[lista.index('// ── Start'):]
    assert start.index('stan.filtr.woj = wojewodztwaZPanelu();') < start.rindex("wczytaj('uzytkownik');")
    panel = _funkcja(lista, 'wojewodztwaZPanelu')
    assert 'w.root === root' in panel and "typeof w.wybrane === 'function'" in panel
    assert "querySelectorAll('input[data-lg-woj-pole]:checked')" in panel


# ── Oględziny rundy 2, pkt 6: komunikat pod oknem modalnym ──────────────────

def test_komunikat_dodania_kierowcy_nie_ginie_pod_otwartym_oknem():
    """Okno „Dodaj kierowcę” ma własne potwierdzenie; komunikat zakładki leżał pod nim."""
    flota = _js('logistics-fleet.js')
    dodaj = _funkcja(flota, 'dodajKierowce')
    assert re.search(r"if \(!\(dialogKierowcy && dialogKierowcy\.open\)\) \{?\s*"
                     r"komunikat\('ok', 'Dodano kierowcę „'", dodaj)
    assert dodaj.index('stan.ostatnioDodany = k.nazwa;') < dodaj.index("komunikat('ok'")
    assert "teksty.push('Dodano „' + stan.ostatnioDodany + '” do kierowców.')" in \
        _funkcja(flota, 'renderujKandydatow')


# ── D3: select sposobu w wierszu oddaje fokus klawiatury po zapisie ─────────

def test_d3_select_wiersza_oddaje_fokus_klawiatury_po_zapisie():
    lista = _js('logistics.js')
    zmiana = _funkcja(lista, 'zmianaSelecta')
    assert zmiana.index('const fokus = fokusKlawiaturyNaSelecie(id);') < \
        zmiana.index('await wyslijSposobZDecyzja([id], wartosc, przepakowanie)')
    oddanie = zmiana.index('if (fokus && !zniszczona) oddajFokusSelectowi(id);')
    assert oddanie > zmiana.index('podsumujZmiany(wynik, true)')
    assert oddanie > zmiana.index("pokazKomunikat('blad', 'Nie zmieniono sposobu dostawy zamówienia '")
    fokus = _funkcja(lista, 'fokusKlawiaturyNaSelecie')
    # Tylko klawiatura (:focus-visible) — klik myszą działa jak dotąd.
    assert "matches(':focus-visible')" in fokus and "classList.contains('lg-sposob')" in fokus
    oddaj = _funkcja(lista, 'oddajFokusSelectowi')
    # Fokus, który użytkownik przeniósł w trakcie zapisu, zostaje; nieaktywny select go nie dostaje.
    assert oddaj.index('document.body') < oddaj.index('.focus(')
    assert 'if (s && !s.disabled) s.focus(' in oddaj


# ── D4: odmiana w podpowiedzi klastra ───────────────────────────────────────

def test_d4_podpowiedz_klastra_z_odmiana():
    mapa, lista = _js('logistics-map.js'), _js('logistics.js')
    klaster = _funkcja(mapa, 'ikonaKlastra')
    assert "ile + ' ' + odmiana(ile, ['zamówienie', 'zamówienia', 'zamówień']) + ' w tym miejscu." in klaster
    assert "ile + ' zamówień w tym miejscu" not in klaster
    # Ta sama reguła co w liście: 1 zamówienie, 2–4 zamówienia, 5+ i 12–14 zamówień.
    assert _funkcja(mapa, 'odmiana') == _funkcja(lista, 'odmiana')


# ── D5: products-module.js z podbitym ?v= ───────────────────────────────────

def test_d5_products_module_z_podbita_wersja():
    assert _wersja(_panel(), 'js/modules/products-module.js') >= '20260928a'


# ── D6: licznik logistyki odświeża się razem z dashboardem produkcji ────────

TABELE_DASHBOARDU = [m.__table__ for m in (
    User, ProductionDevice, ProductionOrder, ProductionProduct, ProductionConfiguration,
    ProductionError, ProductionWorker, ProductionWorkerSession, ProductionStationEvent,
    ProductionStationEventWorker,
)]


@pytest.fixture()
def dashboard(monkeypatch):
    """
    Minimalna apka z API produkcji (GET /dashboard-data). Endpoint loguje current_user.id —
    podmieniamy go w module jak tests/test_reports_zbieznosc.py.
    """
    from modules.production.routers.api import api_bp, dashboard_api
    monkeypatch.setattr(dashboard_api, 'current_user',
                        type('UzytkownikTestowy', (), {'id': 1, 'role': 'admin'})())
    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        'poolclass': StaticPool,
        'connect_args': {'check_same_thread': False},
    }
    app.config['LOGIN_DISABLED'] = True
    app.register_blueprint(api_bp, url_prefix='/production/api')
    db.init_app(app)
    with app.app_context():
        db.metadata.create_all(bind=db.engine, tables=TABELE_DASHBOARDU)
        yield app.test_client()
        db.session.remove()


def test_d6_odswiezenie_dashboardu_niesie_liczbe_bez_sposobu(dashboard):
    zamowienie(statusy=('czeka_na_pakowanie',))                           # bez sposobu — liczy się
    zamowienie(sposob=s.KURIER, statusy=('czeka_na_pakowanie',))          # ma sposób
    zamowienie(statusy=('anulowane',))                                    # same anulowane
    dane = dashboard.get('/production/api/dashboard-data').get_json()
    assert dane['success'] is True and dane['data']['logistics_pending'] == 1
    zamowienie()
    # Liczone przy każdym odświeżeniu (np. po synchronizacji z Base.), nie tylko przy renderze.
    assert dashboard.get('/production/api/dashboard-data').get_json()['data']['logistics_pending'] == 2


def test_d6_blad_licznika_nie_kladzie_odswiezenia_stanowisk(dashboard, monkeypatch):
    from modules.production.logistics.services import lista

    def awaria():
        raise RuntimeError('brak tabeli logistyki')

    monkeypatch.setattr(lista, 'liczba_bez_sposobu', awaria)
    r = dashboard.get('/production/api/dashboard-data')
    dane = r.get_json()
    assert r.status_code == 200 and dane['success'] is True
    assert dane['data']['logistics_pending'] is None and len(dane['data']['stations']) == 7


def test_d6_dashboard_aktualizuje_liczbe_i_stan_spokoju():
    js = _plik(PROD, 'static', 'js', 'modules', 'dashboard-module.js')
    stacje = js[js.index("registerRefreshHandler('stations'"):js.index("registerRefreshHandler('totals'")]
    assert 'this.updateLogisticsPending(data.data.logistics_pending);' in stacje
    metoda = _metoda(js, 'updateLogisticsPending')
    # Brak liczby (serwer jej nie policzył) zostawia ostatnią, zamiast pokazać zero.
    assert metoda.index("typeof liczba !== 'number'") < metoda.index('.textContent = ')
    assert "document.getElementById('logistics-pending')" in metoda
    assert "closest('.il-logistyka')" in metoda
    assert "classList.toggle('il-logistyka--spokoj', liczba === 0)" in metoda
    # Ten sam element i ta sama klasa co w szablonie paska.
    szablon = _plik(PROD, 'templates', 'components', 'dashboard-tab-content.html')
    assert 'id="logistics-pending"' in szablon and "' il-logistyka--spokoj' if not lg_n" in szablon
    assert _wersja(_panel(), 'js/modules/dashboard-module.js') >= '20260928b'


# ── D7: „Dodaj kierowcę” po błędzie wczytania kandydatów ────────────────────

def test_d7_blad_wczytania_kandydatow_to_tylko_blad_i_ponowienie():
    flota = _js('logistics-fleet.js')
    kandydaci = _funkcja(flota, 'renderujKandydatow')
    bez_bledu = kandydaci[kandydaci.index('if (!stan.kandydaciBlad) {'):]
    bez_bledu = bez_bledu[:bez_bledu.index('\n        }\n')]
    for tekst in ('Wszyscy aktywni pracownicy są już kierowcami.', 'Wczytywanie pracowników…',
                  "teksty.push('Dodano „'"):
        assert tekst in bez_bledu, tekst
    assert 'kandydaciPonowBtn.hidden = !stan.kandydaciBlad;' in kandydaci
    wczytaj = _funkcja(flota, 'wczytajKandydatow')
    blad = wczytaj[wczytaj.index('} catch (e) {'):]
    assert "stan.kandydaciBlad = 'Nie wczytano pracowników. ' + e.message;" in blad
    assert 'pokazBladKierowcy(stan.kandydaciBlad);' in blad
    # Nowa próba zdejmuje TYLKO błąd wczytania (odmowa „Dodaj” zostaje w oknie).
    przed = wczytaj[:wczytaj.index("zapytanie('/drivers/candidates'")]
    assert 'if (stan.kandydaciBlad) {' in przed and 'stan.kandydaciBlad = null;' in przed
    okno = _okno_kierowcy()
    ponow = okno[okno.rindex('<button', 0, okno.index('data-lg-flota-akcja="kandydaci-ponow"')):]
    ponow = ponow[:ponow.index('>')]
    assert 'data-lg-flota="kandydaci-ponow"' in ponow and ' hidden' in ponow
    klik = flota[flota.index("dialogKierowcy.addEventListener('click'"):]
    klik = klik[:klik.index('}, naSluch);')]
    galaz = klik[klik.index("akcja === 'kandydaci-ponow'"):]
    assert 'wczytajKandydatow();' in galaz[:galaz.index('}')]


# ── D8: edytor trasy — osoba, której zdjęto znacznik w trakcie edycji ───────

def test_d8_niezapisany_wybor_bez_znacznika_nie_jest_nieaktywny():
    selecty = _funkcja(_js('logistics-routes.js'), 'renderujSelecty')
    # „(nieaktywny)” tylko dla kierowcy ZAPISANEGO na trasie (dostępność nie zna nieaktywnych).
    nieaktywny = selecty.index("' (nieaktywny)'")
    warunek = selecty[selecty.rindex('if (', 0, nieaktywny):nieaktywny]
    assert 'zapisany' in warunek[:warunek.index('{')]
    assert 'const zapisany = !!(t && t.kierowca && String(t.kierowca.id) === wK);' in selecty
    # Niezapisany wybór (albo nowa trasa): „(nie jest już kierowcą)”, bez „zostaje na tej trasie”.
    niezapisany = selecty[selecty.index('} else if (wK && !kierowca) {'):]
    niezapisany = niezapisany[:niezapisany.index('} else if (', 1)]
    assert "' (nie jest już kierowcą)'" in niezapisany
    assert "uwagaK = 'Nie jest już kierowcą (zmiana we Flocie). Wybierz innego kierowcę.';" in niezapisany
    assert 'Zostaje na tej trasie' not in niezapisany and 'aktywnym pracownikiem' not in niezapisany
    assert 'nazwyKierowcow.get(wK)' in niezapisany
    assert 'nazwyKierowcow.set(String(k.id), k.nazwa);' in selecty


def test_d8_bez_kierowcow_podpowiedz_flota():
    selecty = _funkcja(_js('logistics-routes.js'), 'renderujSelecty')
    brak = selecty.index('} else if (!(d.kierowcy || []).some((k) => !k.nie_kierowca)) {')
    assert "uwagaK = 'Brak kierowców do wyboru. Dodaj kierowców we Flocie.';" in selecty[brak:]
    assert "ikonaK = 'fa-circle-info';" in selecty[brak:]
    assert 'ustawUwage(uwagaKierowcyEl, uwagaK, ikonaK);' in selecty
    assert "(ikona || 'fa-triangle-exclamation')" in _funkcja(_js('logistics-routes.js'), 'ustawUwage')


# ── D9: kursor „w toku” w dymku tylko na czas zapisu ────────────────────────

def test_d9_kursor_postepu_tylko_w_trakcie_zapisu():
    css = _css()
    assert '.logistics-tab .lg-dymek-select:disabled { cursor: progress; }' not in css
    assert '.logistics-tab .lg-dymek-select:disabled { cursor: not-allowed; }' in css
    assert '.logistics-tab .lg-dymek-select:disabled[aria-busy="true"] { cursor: progress; }' in css
    dymek = _funkcja(_js('logistics-map.js'), 'dymekHtml')
    assert 'const zapisTrwa = !!blokada && (zapisywaneSposoby.has(z.id) || zapisWLiscie(z.id));' in dymek
    assert "(zapisTrwa ? ' aria-busy=\"true\"' : '')" in dymek


# ── D11: Flota — pojazdy i kierowcy niezależnie ─────────────────────────────

def test_d11_blad_kierowcow_nie_chowa_pojazdow():
    flota = _js('logistics-fleet.js')
    wczytaj = _funkcja(flota, 'wczytaj')
    assert 'Promise.all(' not in wczytaj and 'Promise.allSettled([' in wczytaj
    pojazdy = wczytaj[wczytaj.index('if (bladP) {'):wczytaj.index('if (bladK) {')]
    assert 'stan.pojazdy = ' in pojazdy and 'stan.kierowcy' not in pojazdy
    kierowcy = wczytaj[wczytaj.index('if (bladK) {'):]
    assert 'stan.kierowcyBlad = bladK.message;' in kierowcy and 'stan.kierowcy = ' in kierowcy
    assert 'stan.pojazdy' not in kierowcy
    assert "'Nie odświeżono ' + nieodswiezone.map((n) => n[0]).join(' ani ')" in wczytaj


def test_d11_blad_kierowcow_w_panelu_zamiast_pustej_listy():
    flota = _js('logistics-fleet.js')
    kierowcy = _funkcja(flota, 'renderujKierowcow')
    blad = kierowcy.index('if (stan.kierowcyBlad && !stan.kierowcyWczytani) {')
    assert blad < kierowcy.index('Dodaj kierowców spośród pracowników.')
    galaz = kierowcy[blad:kierowcy.index('} else if (stan.kierowcyWczytani) {')]
    for fraza in ('Nie udało się pobrać kierowców.', 'esc(stan.kierowcyBlad)', 'data-lg-flota-akcja="ponow"',
                  'class="lg-kierowcy-blad"'):
        assert fraza in galaz, fraza
    assert 'stan.kierowcyWczytani ? String(stan.kierowcy.length)' in kierowcy
    przyjmij = _funkcja(flota, 'przyjmijKierowcow')
    assert 'stan.kierowcyWczytani = true;' in przyjmij and 'stan.kierowcyBlad = null;' in przyjmij
    assert '.logistics-tab .lg-kierowcy li.lg-kierowcy-blad {' in _css()


# ── ?v= każdego zmienionego pliku statycznego zakładki ──────────────────────

def test_wersje_podbite_w_zakladce():
    html = _zakladka()
    for plik, minimum in (('js/logistics.js', '20260928d'), ('js/logistics-map.js', '20260928b'),
                          ('js/logistics-routes.js', '20260928e'), ('js/logistics-fleet.js', '20260928b'),
                          ('css/logistics.css', '20260928b')):
        assert _wersja(html, plik) >= minimum, plik
