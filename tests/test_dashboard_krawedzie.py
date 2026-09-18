# -*- coding: utf-8 -*-
"""
Dashboard produkcji po podziale Wykańczania na Krawędzie i Lakiernię.

Do 09.2026 panel biura rysował JEDEN kafel „Wykańczanie" i nie znał lakierni
w ogóle — mimo że raport „Dni zapasu przed stanowiskiem" liczył ją od dawna
i to ona miała najdłuższą kolejkę hali. Po tej zmianie kafle są dwa.

Warstwa danych dashboardu (dashboard_api.py) jest naprawiona WCZEŚNIEJ, razem
z katalogiem stanowisk, i pilnuje jej tests/test_katalog_stanowisk_krawedzie.py.
Ten plik zajmuje się tym, co zostało: prezentacją (szablon, JS, CSS) oraz
czwartą kopią mapy stanowisko→status w main_routers.py.

Większość testów jest TEKSTOWA (czyta szablon, JS i CSS zamiast renderować
stronę) — dokładnie tak jak tests/test_sawmill_dashboard_tile.py. Powód: front
produkcji nie ma żadnego innego pokrycia na kody stanowisk, a pełne
uruchomienie dashboard_tab_content() wymagałoby DDL całego modułu produkcji,
telemetrii urządzeń i agregatów trakowni — nieproporcjonalnie dużo wobec tego,
co te testy mają wyłapać: rozjazd równoległych kopii listy stanowisk.

Ten plik nie zakłada tabeli prod_product_events, bo nie robi tego żaden inny
plik w pakiecie — listener audytu milczy w całym przebiegu i tak ma zostać.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

KORZEN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SZABLON = os.path.join(KORZEN, 'modules', 'production', 'templates',
                       'components', 'dashboard-tab-content.html')
DASHBOARD_JS = os.path.join(KORZEN, 'modules', 'production', 'static', 'js',
                            'modules', 'dashboard-module.js')
PANEL_CSS = os.path.join(KORZEN, 'modules', 'production', 'static', 'css',
                         'production-panel.css')
MAIN_ROUTERS = os.path.join(KORZEN, 'modules', 'production', 'routers',
                            'main_routers.py')
DASHBOARD_API = os.path.join(KORZEN, 'modules', 'production', 'routers', 'api',
                             'dashboard_api.py')


def _plik(sciezka):
    with open(sciezka, encoding='utf-8') as f:
        return f.read()


# ============================================================================
# TRASA GET /production (main_routers)
# ============================================================================

def test_main_routers_bierze_kolejki_z_katalogu():
    """
    Czwarta, ręczna kopia mapy stanowisko→status. Ta funkcja nie rysuje kafli
    (panel/dashboard.html ładuje zakładkę AJAX-em z dashboard_api, a zmiennej
    dashboard_stats używa wyłącznie do zbudowania adresu endpointu), ale
    buduje kontekst strony — bez wpisów Krawędzi i Lakierni tych kluczy
    w kontekście po prostu nie ma.

    Wyjątku tu nie ma i nie było: SQLAlchemy Enum domyślnie nie waliduje
    wartości po stronie Pythona, więc zapytanie o wycofany status zwraca
    zero zamiast się wywrócić. Dlatego rozjazd z katalogiem trzeba pilnować
    testem — sam się nie zgłosi.
    """
    zrodlo = _plik(MAIN_ROUTERS)

    assert 'from ..services.station_catalog import STATION_PENDING_STATUS' in zrodlo
    assert 'station_pending_status = {' not in zrodlo
    assert "'finishing'" not in zrodlo
    assert 'czeka_na_wykanczanie' not in zrodlo


# ============================================================================
# KAFLE W SZABLONIE
# ============================================================================

def test_kafel_krawedzi_zastapil_wykanczanie():
    """
    Identyfikatory DOM są kontraktem z dashboard-module.js — JS składa je
    szablonem `${station}-pending-m3`. Rozjazd nie daje błędu w konsoli,
    daje kafel zamrożony na wartościach z pierwszego renderu.
    """
    html = _plik(SZABLON)

    assert 'data-station="edges"' in html
    assert 'data-station="finishing"' not in html

    blok = html.split('data-station="edges"')[1].split('data-station=')[0]
    assert '>Krawędzie<' in blok
    assert "station_code='edges'" in blok
    assert 'dashboard_stats.stations.edges.' in blok
    # Pasek „postępu dnia" (edges-bar-fill / edges-bar-pct) ustąpił kolumnie
    # obciążenia — tamta miara miała ruchomy mianownik i rano zawsze
    # pokazywała zero. Kontrakt z JS to teraz `${station}-load`.
    for ident in ('edges-tablet-badge', 'edges-pending', 'edges-pending-m3',
                  'edges-completed-today', 'edges-today-m3', 'edges-load',
                  'edges-pending-orders'):
        assert 'id="{}"'.format(ident) in blok, ident


def test_szablon_dashboardu_nie_zna_juz_wykanczania():
    """
    Dopóki w szablonie stoi dashboard_stats.stations.finishing, cała zakładka
    oddaje HTTP 500 — po stronie danych tego klucza już nie ma, a Jinja
    z domyślnym Undefined rzuca UndefinedError na łańcuchu atrybutów, zanim
    dojdzie do filtra default().
    """
    html = _plik(SZABLON)

    assert 'finishing' not in html
    assert 'Wykańczanie' not in html


def test_kafel_lakierni_ma_komplet_identyfikatorow():
    """
    Lakiernia nie miała kafla nigdy — żyła jako zakładka tabletu Wykańczania,
    choć dane o jej kolejce dashboard liczy od warstwy katalogu. Kafel ma być
    pełnoprawny, z telemetrią tabletu włącznie.
    """
    html = _plik(SZABLON)

    assert 'data-station="painting"' in html

    blok = html.split('data-station="painting"')[1].split('data-station=')[0]
    assert '>Lakiernia<' in blok
    assert 'station_telemetry' in blok
    assert "station_code='painting'" in blok
    assert 'dashboard_stats.stations.painting.' in blok
    for ident in ('painting-tablet-badge', 'painting-pending',
                  'painting-pending-m3', 'painting-completed-today',
                  'painting-today-m3', 'painting-load',
                  'painting-pending-orders'):
        assert 'id="{}"'.format(ident) in blok, ident


def test_obciazenie_wchodzi_obiema_sciezkami_danych():
    """
    Kafel renderuje się RAZ Jinją (wejście na zakładkę) i RAZ ze skryptu
    (odświeżanie w tle). Gdyby obciążenie liczyła tylko jedna z tych ścieżek,
    liczba skakałaby po pierwszym odświeżeniu — albo, gorzej, znikała na „—"
    i wyglądała jak brak danych.
    """
    api = _plik(DASHBOARD_API)
    js = _plik(DASHBOARD_JS)

    # ścieżka szablonu (i initial_data — to ten sam słownik)
    assert "dashboard_stats['stations'][station_code]['obciazenie']" in api
    # ścieżka JSON odświeżania
    assert "'obciazenie': _obciazenie(" in api
    # front tylko WYŚWIETLA — wzór i progi zostają po stronie backendu
    assert 'updateStationLoad' in js
    assert 'updateStationProgress' not in js


def test_jednostka_nie_siedzi_w_elemencie_pisanym_przez_js():
    """
    dashboard-module.js odświeża wartości przez `textContent`, a to KASUJE
    dzieci elementu. Jednostka „m³" trzymana wewnątrz elementu z id znikała
    więc po pierwszym odświeżeniu w tle — była widoczna tylko przez chwilę
    po wczytaniu strony i wyglądało to na gubione dane.

    Ukończono nie miało tego objawu wyłącznie dlatego, że główna ścieżka
    odświeżania nie dotyka `-today-m3`. To przypadek, nie zabezpieczenie,
    więc test pilnuje obu.
    """
    html = _plik(SZABLON)

    for ident in ('cutting-pending-m3', 'cutting-today-m3',
                  'painting-pending-m3', 'painting-today-m3'):
        dopasowanie = re.search(r'id="%s">(.*?)</span>' % ident, html)
        assert dopasowanie is not None, ident
        assert '<small>' not in dopasowanie.group(1), (
            'jednostka w %s zostanie skasowana przez updateElementText' % ident)


def test_kolumna_zamowien_odswieza_sie_w_tle():
    """
    Kafel spoza ścieżki odświeżania ZAMRAŻA się na wartościach z pierwszego
    renderu — bez błędu w konsoli i bez żadnego innego sygnału. Nowa kolumna
    musi więc trafić do obu miejsc, które aktualizują wiersze.
    """
    js = _plik(DASHBOARD_JS)

    assert js.count('-pending-orders`') == 2, (
        'kolumna zamówień musi być odświeżana w obu ścieżkach')


def test_grid_czyta_sie_w_kolejnosci_drogi_produktu():
    """
    Kolejność kafli to kolejność hali: trakownia (surowiec) na wejściu, potem
    pipeline produktów, na końcu logistyka i pakowanie. Lakiernia stoi PO
    Krawędziach, bo produkt z obróbką krawędzi idzie do niej właśnie stamtąd.

    Pigułka alertu niżej w szablonie ma data-station składane Jinją, więc
    nie wpada w to wyrażenie regularne.
    """
    html = _plik(SZABLON)
    kolejnosc = re.findall(r'data-station="(\w+)"', html)

    assert kolejnosc == ['sawmill', 'cutting', 'assembly', 'gluing',
                         'formatting', 'edges', 'painting', 'logistics',
                         'packaging']


# ============================================================================
# AKTUALIZACJA W TLE (dashboard-module.js)
# ============================================================================

def test_lista_stanowisk_w_js_obejmuje_krawedzie_i_lakiernie():
    """
    Kafel spoza tej tablicy pokazuje liczby z pierwszego renderu i ZAMRAŻA
    się — bez błędu w konsoli i bez żadnego innego sygnału. To jedyne
    pokrycie testowe, jakie front produkcji ma na kody stanowisk.

    Trakownia świadomie poza tablicą: ma własny zestaw metryk i osobną
    gałąź updateSawmillStation() linijkę wyżej.
    """
    js = _plik(DASHBOARD_JS)

    dopasowanie = re.search(r"const stations = \[([^\]]*)\]", js)
    assert dopasowanie is not None, 'nie znaleziono tablicy stanowisk w JS'

    kody = re.findall(r"'(\w+)'", dopasowanie.group(1))
    assert kody == ['cutting', 'assembly', 'gluing', 'formatting', 'edges',
                    'painting', 'packaging']


def test_dashboard_js_nie_zna_juz_kodu_finishing():
    js = _plik(DASHBOARD_JS)

    assert "'finishing'" not in js


# ============================================================================
# KOLORY (production-panel.css)
# ============================================================================

def test_kafle_krawedzi_i_lakierni_maja_wlasny_kolor():
    """
    Po przejściu na szynę barwa stanowiska nie leży już na nagłówku kafla —
    niesie ją zmienna --st (linijka przy nazwie i węzeł na szynie) oraz
    wypełnienie paska postępu. Kodowanie zostało JEDNO, tylko ciszej, i nadal
    musi zgadzać się z pigułką alertu w prawej kolumnie.
    """
    css = _plik(PANEL_CSS)

    for selektor in ('.il-station[data-station="edges"] { --st: var(--il-station-fin); }',
                     '.il-station[data-station="edges"] .il-station-bar-fill',
                     '.il-station[data-station="painting"] { --st: var(--il-station-cmp); }',
                     '.il-station[data-station="painting"] .il-station-bar-fill'):
        assert selektor in css, selektor


def test_pigulka_alertu_ma_ten_sam_kolor_co_kafel():
    """
    Wymóg zapisany przy pigułkach: „pigułka Sklejanie ma być tym samym
    fioletem, co nagłówek kafelka sklejania, inaczej to dwa niezależne
    kodowania kolorem na jednym ekranie".
    """
    css = _plik(PANEL_CSS)

    assert '.il-alert-station[data-station="edges"]' in css
    assert '.il-alert-station[data-station="painting"]' in css
    # Lakiernia MA już kafelek w gridzie — stare uzasadnienie wolnego koloru
    # przestało obowiązywać.
    assert 'Lakiernia nie ma kafelka w gridzie' not in css


def test_panel_css_nie_zna_juz_kodu_stanowiska_finishing():
    """
    Zmienia się KOD stanowiska (data-station), a nie nazwy zmiennych.
    --il-station-fin (turkus po Wykańczaniu, dziś Krawędzie) i
    --il-station-cmp (indygo po wycofanej w 05.2026 kompletacji, dziś
    Lakiernia) zostają świadomie: przemianowanie ich rozlałoby migrację
    po całym arkuszu bez żadnej zmiany dla użytkownika. Ten test pilnuje
    obu stron tej decyzji naraz, żeby nikt nie „poprawił" jej w połowie.
    """
    css = _plik(PANEL_CSS)

    assert 'data-station="finishing"' not in css
    assert '--il-station-fin:' in css
    assert '--il-station-cmp:' in css


def test_wysokosc_wiersza_zgadza_sie_w_trzech_miejscach():
    """
    Wysokość wiersza 49 px jest zapisana w TRZECH miejscach naraz: w CSS
    (`.il-station`), w viewBox szyny w szablonie (`0 0 54 392` = osiem
    wierszy po 49) i w stałej WYSOKOSC_WIERSZA w dashboard-module.js, która
    liczy z niej pozycje węzłów.

    Rozjazd nie wywala niczego i nie zostawia śladu w konsoli — po prostu
    kropki przepływu przestają trafiać w kropki stanowisk, a szyna zaczyna
    prowadzić donikąd. Dlatego trzy źródła tej samej liczby pilnuje test,
    a nie komentarz.
    """
    css = _plik(PANEL_CSS)
    html = _plik(SZABLON)
    js = _plik(DASHBOARD_JS)

    blok = css.split('.il-station {')[1].split('}')[0]
    assert 'height: 49px;' in blok, 'CSS: wysokość wiersza'

    assert 'viewBox="0 0 54 392"' in html, 'szablon: viewBox szyny'
    assert 'const WYSOKOSC_WIERSZA = 49;' in js, 'JS: stała wysokości wiersza'


def test_lista_stanowisk_jest_kolumna_a_nazwa_klasy_zostaje():
    """
    Kafle ustąpiły wierszom, ale kontener zostaje pod nazwą
    `.il-stations-grid` CELOWO: dashboard-module.js wykrywa po niej aktywny
    szablon (`isIL`) i od tego zależy sposób renderowania ALERTÓW, nie
    stanowisk. Podmiana tej nazwy zepsułaby więc zupełnie inny widget niż
    ten, który się zmienia — stąd test trzyma obie strony naraz.
    """
    css = _plik(PANEL_CSS)
    js = _plik(DASHBOARD_JS)

    blok = css.split('.il-stations-grid {')[1].split('}')[0]
    assert 'flex-direction: column;' in blok, 'CSS: lista ma być kolumną'
    assert "querySelector('.il-stations-grid')" in js, 'JS: wykrywanie szablonu'


def test_logistyka_nie_udaje_stanowiska_na_hali():
    """
    Logistyka to bramka decyzji o wysyłce: nikt się na niej nie loguje, nie
    ma tabletu ani przerobu w m³. Stary kafel pokazywał wyłącznie liczbę
    czekających na decyzję i wiersz ma robić dokładnie to samo — wypełnianie
    sześciu kolumn zerami kłamałoby o tym, że coś się tam mierzy.
    """
    html = _plik(SZABLON)

    blok = html.split('data-station="logistics"')[1].split('data-station=')[0]
    assert 'id="logistics-pending"' in blok
    assert 'oczekuje na decyzję' in blok
    for czego_nie_ma in ('-bar-fill', '-tablet-badge', 'station_crew', 'today-m3'):
        assert czego_nie_ma not in blok, czego_nie_ma
