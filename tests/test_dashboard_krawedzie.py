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
    for ident in ('edges-tablet-badge', 'edges-pending', 'edges-pending-m3',
                  'edges-completed-today', 'edges-today-m3',
                  'edges-bar-fill', 'edges-bar-pct'):
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
                  'painting-today-m3', 'painting-bar-fill', 'painting-bar-pct'):
        assert 'id="{}"'.format(ident) in blok, ident


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
    css = _plik(PANEL_CSS)

    for selektor in ('.il-station[data-station="edges"] .il-station-header',
                     '.il-station[data-station="edges"] .il-station-bar-fill',
                     '.il-station[data-station="painting"] .il-station-header',
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


def test_siatka_stanowisk_uklada_sie_sama_i_ma_staly_kafel():
    """
    Kafli jest dziewięć: trakownia, pięć stanowisk pipeline'u, lakiernia,
    logistyka i pakowanie. Siatka nie ma sztywno wpisanej liczby kolumn —
    układa się sama przez `repeat(auto-fit, minmax(min(380px, 100%), 1fr))`,
    żeby na
    szerszych ekranach zawijała się w kolejną kolumnę bez ręcznego progu.
    380px w minmax to dolna granica szerokości kafla — wartość ZADANA przez
    właściciela na podstawie tego, jak kafel wygląda naprawdę (nie wyliczona
    z layoutu; pełne wyjaśnienie i wyliczenie progów kolumn dla tej wartości
    jest w komentarzu nad regułą w CSS). Test nie sprawdza, ile dokładnie
    kolumn wychodzi na jakiej szerokości — pilnuje tylko, że mechanizm
    auto-fit/minmax(380px) w ogóle tam jest, żeby nikt nie wrócił po cichu do
    sztywnej liczby kolumn ani nie podmienił wartości bez świadomej decyzji.

    `align-content: start` jest tu WARUNKIEM, nie kosmetyką, i to JEGO
    pilnowanie jest ważniejsze niż kształt grid-template-columns — już raz
    padło ofiarą "poprawki", więc ten test przypina je osobnym assertem.
    Siatka ma `flex: 1`, więc rośnie do wysokości, jaką odda jej karta po
    wyrównaniu z prawą kolumną w `.production-dashboard-grid`. Domyślne
    `align-content` rozdziela ten nadmiar na WIERSZE, więc kafel robi się
    wyższy od własnej treści — i tym bardziej, im wyższa jest prawa kolumna.
    Raz już się to wydarzyło: zdjęcie sztywnego `max-height` z listy alertów
    powiększyło nadmiar i kafle urosły. Bez pakowania wierszy od góry
    wysokość kafla zależy od tego, co dzieje się obok siatki, a nie tylko od
    własnej treści.

    Zejście do jednej kolumny poniżej 900 px zostaje jako sieć bezpieczeństwa
    (auto-fit i tak by tam zeszło niżej, patrz wyliczenie w CSS) i jest tu
    sprawdzane, żeby nikt go nie usunął w ramach "sprzątania" auto-fit.
    """
    css = _plik(PANEL_CSS)

    blok = css.split('.il-stations-grid {')[1].split('}')[0]
    assert 'grid-template-columns: repeat(auto-fit, minmax(min(380px, 100%), 1fr));' in blok
    assert 'align-content: start;' in blok

    waski = css.split('@media (max-width: 900px)')[1][:800]
    assert '.il-stations-grid { grid-template-columns: 1fr; }' in waski
