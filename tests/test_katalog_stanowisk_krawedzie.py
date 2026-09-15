# -*- coding: utf-8 -*-
"""
Katalog stanowisk po rozdziale Wykańczania na Krawędzie i Lakiernię.

Testy strukturalne, BEZ bazy i bez kontekstu Flaska — katalog
(modules/production/services/station_catalog.py) jest zwykłym modułem stałych
i to jest jego główna cecha: importują go routery, serwisy i szablony przez
kontekst, więc każdy import Flaska albo modeli robi z niego kandydata na cykl
importów. Po zmianie resolve_station_code będzie importowany także z models.py.

Ten plik nie zakłada tabeli prod_product_events, bo nie robi tego żaden inny
plik w pakiecie — listener audytu milczy w całym przebiegu i tak ma zostać.

Plik pilnuje czterech rzeczy:
1. katalog nie importuje Flaska ani modeli,
2. równoległe mapy katalogu nie rozjeżdżają się między sobą (docstring
   station_catalog.py:5-12 opisuje dokładnie tę chorobę),
3. tłumacz kodów przejściowych (resolve_station_code) ma przewidywalne
   zachowanie brzegowe — wołają go wszystkie warstwy, także z danymi prosto
   z JSON-a tabletu,
4. pakiet modules.production.routers wstaje po zmianie katalogu (Zadanie 6).
"""

import ast
from pathlib import Path


SCIEZKA_KATALOGU = (
    Path(__file__).resolve().parents[1]
    / 'modules' / 'production' / 'services' / 'station_catalog.py'
)

# Segmenty nazw modułów, których katalogowi importować nie wolno.
# Prefiks 'flask' łapie też flask_login i flask_sqlalchemy.
ZAKAZANE_SEGMENTY = {'models', 'extensions', 'sqlalchemy'}


def _importowane_moduly(sciezka):
    """Nazwy modułów importowanych przez plik — razem z importami względnymi."""
    drzewo = ast.parse(sciezka.read_text(encoding='utf-8'))
    nazwy = []
    for wezel in ast.walk(drzewo):
        if isinstance(wezel, ast.Import):
            nazwy.extend(alias.name for alias in wezel.names)
        elif isinstance(wezel, ast.ImportFrom):
            # 'from ..models import X' → '..models'; 'from . import y' → '.'
            nazwy.append('.' * (wezel.level or 0) + (wezel.module or ''))
    return nazwy


def _zakazane_importy(sciezka):
    """Importy łamiące zasadę „katalog bez Flaska i bez modeli"."""
    winne = []
    for nazwa in _importowane_moduly(sciezka):
        for segment in nazwa.lstrip('.').split('.'):
            if segment.startswith('flask') or segment in ZAKAZANE_SEGMENTY:
                winne.append(nazwa)
                break
    return winne


def test_katalog_nie_importuje_flaska_ani_modeli():
    """
    Docstring katalogu (station_catalog.py:14-15) obiecuje brak Flaska
    i modeli. Na tej obietnicy stoi to, że models.py może zaimportować
    resolve_station_code bez cyklu importów.
    """
    winne = _zakazane_importy(SCIEZKA_KATALOGU)
    assert winne == [], (
        'station_catalog importuje %s — katalog ma pozostać wolny od Flaska '
        'i modeli, inaczej import resolve_station_code w models.py robi cykl'
        % winne
    )


def test_kazde_stanowisko_ma_etykiete_i_status_kolejki():
    """
    Choroba opisana w docstringu katalogu (station_catalog.py:5-12) polegała
    na pięciu rozjeżdżających się kopiach nazw. Ten test pilnuje, żeby trzy
    mapy JEDNEGO źródła prawdy nie rozjechały się między sobą.
    """
    from modules.production.services.station_catalog import (
        STATION_LABELS,
        STATION_ORDER,
        STATION_PENDING_STATUS,
    )

    # 'sawmill' celowo stoi poza STATION_ORDER (rejestr surowca, własne tabele
    # prod_sawmill_*), ale MUSI mieć nazwę — pracownik ma tam sesje.
    assert set(STATION_LABELS) == set(STATION_ORDER) | {'sawmill'}
    assert set(STATION_PENDING_STATUS) == set(STATION_ORDER)

    for kod in STATION_ORDER:
        assert STATION_LABELS[kod], kod
        assert STATION_PENDING_STATUS[kod].startswith('czeka_na_'), kod


def test_statusy_kolejek_sa_unikalne():
    """Dwa stanowiska pod jednym statusem = kolejka liczona podwójnie."""
    from modules.production.services.station_catalog import STATION_PENDING_STATUS

    wartosci = list(STATION_PENDING_STATUS.values())
    assert len(wartosci) == len(set(wartosci)), wartosci


def test_alias_zamienia_finishing_na_edges():
    """Okres przejściowy: stary tablet i stary adres monitora mówią 'finishing'."""
    from modules.production.services.station_catalog import resolve_station_code

    assert resolve_station_code('finishing') == 'edges'


def test_alias_nie_rusza_kodow_kanonicznych():
    from modules.production.services.station_catalog import resolve_station_code

    for kod in ('cutting', 'assembly', 'gluing', 'formatting',
                'edges', 'painting', 'packaging', 'sawmill'):
        assert resolve_station_code(kod) == kod


def test_alias_nie_dziala_w_druga_strone():
    """'edges' NIE jest aliasem 'finishing' — tłumaczenie ma jeden kierunek."""
    from modules.production.services.station_catalog import (
        STATION_CODE_ALIASES,
        resolve_station_code,
    )

    assert resolve_station_code('edges') == 'edges'
    assert 'edges' not in STATION_CODE_ALIASES
    assert STATION_CODE_ALIASES['finishing'] == 'edges'


def test_nieznany_kod_wraca_bez_zmian():
    """Odsiewanie nieznanych kodów należy do bramek walidacji, nie do tłumacza."""
    from modules.production.services.station_catalog import resolve_station_code

    assert resolve_station_code('trakownia_pietro_2') == 'trakownia_pietro_2'
