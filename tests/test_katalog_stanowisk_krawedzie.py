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


def test_alias_przycina_biale_znaki():
    """
    Kontrakt (ograniczenia-globalne.md): string wejściowy jest przycinany `.strip()`
    PRZED mapowaniem przez alias i przed zwróceniem. Naiwny jednolinijkowiec
    `STATION_CODE_ALIASES.get(code, code)` w ogóle nie przycina, więc dla kodu
    z białymi znakami zwróciłby go z tymi znakami — nawet gdy po przycięciu
    trafia dokładnie w alias.
    """
    from modules.production.services.station_catalog import resolve_station_code

    assert resolve_station_code('  finishing  ') == 'edges'
    assert resolve_station_code('\tcutting\n') == 'cutting'


def test_alias_przepuszcza_wartosci_niestringowe_bez_wyjatku():
    """
    Kontrakt: wartość nie-stringowa (w tym `None`) wraca bez zmian i BEZ WYJĄTKU.

    Sam `None` niczego nie odróżnia — jako klucz haszowalny nieobecny w słowniku
    wraca identycznie z naiwnego `STATION_CODE_ALIASES.get(code, code)` i z
    obowiązującego kontraktu. Dowodem kontraktu jest to, co dzieje się dalej:
    naiwna wersja wywala się `TypeError` na liście i słowniku, bo `dict.get`
    próbuje użyć ich jako klucza (nie da się ich zahaszować) — dokładnie ten
    przypadek, dla którego istnieje bramka `isinstance` w resolve_station_code
    (patrz docstring funkcji: products_api/order_details podają tu surowe dane
    z JSON-a).
    """
    from modules.production.services.station_catalog import resolve_station_code

    lista = ['finishing']
    slownik = {'finishing': 'edges'}

    assert resolve_station_code(None) is None
    assert resolve_station_code(lista) is lista
    assert resolve_station_code(slownik) is slownik


def test_alias_rozroznia_wielkosc_liter():
    """
    Kontrakt: alias rozróżnia wielkość liter — mapowane jest wyłącznie dokładne
    'finishing' (małymi literami, po przycięciu), nigdy jego warianty wielkości
    liter.

    Sama wielkość liter, bez białych znaków, niczego by nie odróżniła od
    naiwnego jednolinijkowca — żadna z dwóch wersji nie zmienia wielkości liter,
    więc obie zwróciłyby np. 'FINISHING' bez zmian. Test celowo łączy wielkość
    liter z białymi znakami: to brak `.strip()` w wersji naiwnej ujawnia się
    tutaj (wróci wartość z białymi znakami), podczas gdy kontrakt przycina biały
    znak i NADAL nie mapuje wariantu innego niż dokładne 'finishing'.
    """
    from modules.production.services.station_catalog import resolve_station_code

    assert resolve_station_code('  FINISHING  ') == 'FINISHING'
    assert resolve_station_code('  Finishing  ') == 'Finishing'


def test_resolve_pustego_i_bialego_znaku_zwraca_pusty_string():
    """
    Kontrakt (ograniczenia-globalne.md): string wraca ZAWSZE przycięty.
    Dla '' i '   ' wynikiem jest '' — wartość FAŁSZYWA, ale NIE None; wołający
    odróżnia „brak kodu po wyczyszczeniu" od „brak kodu w ogóle" wyłącznie
    po typie (`is None` kontra `== ''`).

    Naiwna implementacja `STATION_CODE_ALIASES.get(code, code)` (bez .strip()
    na wejściu) zwróciłaby dla '   ' wartość '   ' z białymi znakami z powrotem
    — bo '   ' nie jest kluczem w mapie i wraca jako domyślne `code`, nie
    `code.strip()`. Test by to złapał na `'   ' == ''`.
    """
    from modules.production.services.station_catalog import resolve_station_code

    assert resolve_station_code('') == ''
    assert resolve_station_code('   ') == ''
    assert resolve_station_code('   ') is not None


def test_resolve_jest_idempotentne():
    """
    Kontrakt (ograniczenia-globalne.md): funkcja jest idempotentna — warstwy
    wołają ją kaskadowo (router -> serwis -> model), więc drugie wywołanie
    NA WYNIKU pierwszego nie ma prawa niczego zmienić. Dziś ta własność
    wynika dopiero ze złożenia osobnych asercji rozsianych po innych testach
    (alias, przycinanie, wielkość liter) — tutaj dostaje jawną nazwę i własny
    test, tak jak wymienia ją kontrakt wprost.

    Złapałaby implementację, która sprawdza alias PRZED przycięciem białych
    znaków, z przyciętym stringiem jako wartością domyślną, np.:
    `STATION_CODE_ALIASES.get(code, code.strip())`. Dla '  finishing  ' taka
    wersja za PIERWSZYM razem nie trafia kluczem ze spacjami w alias i zwraca
    tylko przycięte 'finishing'; za DRUGIM razem (już na czystym 'finishing')
    trafia w alias i zwraca 'edges' — dwa wywołania, dwa różne wyniki.
    """
    from modules.production.services.station_catalog import resolve_station_code

    for wejscie in ('finishing', '  finishing  ', 'edges', ' painting',
                    '', '   ', None, 7):
        pierwszy_wynik = resolve_station_code(wejscie)
        assert resolve_station_code(pierwszy_wynik) == pierwszy_wynik, wejscie


def test_wartosci_aliasow_sa_kodami_kanonicznymi():
    """
    Strażnik nad mapą, w stylu testów Zadań 1-2 (test_kazde_stanowisko_ma_etykiete...,
    test_statusy_kolejek_sa_unikalne): nic dziś nie sprawdza, że WARTOŚCI w
    STATION_CODE_ALIASES są prawdziwymi kodami stanowisk. Kolejny dopisany
    alias mógłby literówką wskazać 'paintng' albo polską nazwę zamiast kodu
    ('lakiernia') i żaden test by nie pisnął — dopóki ten strażnik nie istnieje.

    'edges' celowo NIE jest jeszcze w STATION_ORDER — przemianowanie katalogu
    (Zadanie 6, patrz docstring modułu testowego pkt 4) to osobne zadanie
    dalszej warstwy. Do czasu tej zmiany dopuszczamy 'edges' jawnie, żeby
    strażnik nie blokował Zadania 4, zanim katalog nadąży.
    """
    from modules.production.services.station_catalog import (
        STATION_CODE_ALIASES,
        STATION_ORDER,
    )

    kody_kanoniczne = set(STATION_ORDER) | {'edges'}
    for stary_kod, nowy_kod in STATION_CODE_ALIASES.items():
        assert nowy_kod in kody_kanoniczne, (stary_kod, nowy_kod)
