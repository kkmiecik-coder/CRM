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
