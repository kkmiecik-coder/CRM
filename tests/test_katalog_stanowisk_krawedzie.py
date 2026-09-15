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

Plik pilnuje pięciu rzeczy:
1. katalog nie importuje Flaska ani modeli,
2. równoległe mapy katalogu nie rozjeżdżają się między sobą (docstring
   station_catalog.py:5-12 opisuje dokładnie tę chorobę),
3. tłumacz kodów przejściowych (resolve_station_code) ma przewidywalne
   zachowanie brzegowe — wołają go wszystkie warstwy, także z danymi prosto
   z JSON-a tabletu,
4. pakiet modules.production.routers wstaje po zmianie katalogu (Zadanie 6),
5. każde stanowisko katalogu da się obsadzić tabletem — zbiór kodów
   przyjmowanych przez ProductionDevice nie zostaje w tyle za STATION_ORDER.
"""

import ast
import re
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

    Po przemianowaniu katalogu (Zadanie 5/6) 'edges' jest już pełnoprawnym
    stanowiskiem w STATION_ORDER, więc strażnik porównuje wprost z katalogiem
    — bez żadnego tymczasowego dopuszczenia.
    """
    from modules.production.services.station_catalog import (
        STATION_CODE_ALIASES,
        STATION_ORDER,
    )

    kody_kanoniczne = set(STATION_ORDER)
    for stary_kod, nowy_kod in STATION_CODE_ALIASES.items():
        assert nowy_kod in kody_kanoniczne, (stary_kod, nowy_kod)


def test_katalog_ma_krawedzie_zamiast_wykanczania():
    """Rename musi wejść w trzy mapy naraz — połowiczny rozjeżdża moduł po cichu."""
    from modules.production.services.station_catalog import (
        STATION_LABELS,
        STATION_ORDER,
        STATION_PENDING_STATUS,
        station_label,
    )

    assert 'edges' in STATION_ORDER
    assert 'finishing' not in STATION_ORDER
    # Pozycja w procesie bez zmian: między formatowaniem a lakiernią.
    assert STATION_ORDER.index('edges') == STATION_ORDER.index('formatting') + 1
    assert STATION_ORDER.index('painting') == STATION_ORDER.index('edges') + 1
    assert len(STATION_ORDER) == 7

    assert STATION_LABELS['edges'] == 'Krawędzie'
    assert STATION_LABELS['painting'] == 'Lakiernia'
    assert 'finishing' not in STATION_LABELS
    assert station_label('edges') == 'Krawędzie'

    assert STATION_PENDING_STATUS['edges'] == 'czeka_na_krawedzie'
    assert STATION_PENDING_STATUS['painting'] == 'czeka_na_lakiernie'
    assert 'finishing' not in STATION_PENDING_STATUS
    assert 'czeka_na_wykanczanie' not in STATION_PENDING_STATUS.values()


def test_alias_wskazuje_na_istniejace_stanowisko():
    """Alias bez celu w katalogu przepuszczałby martwy kod dalej, do bazy."""
    from modules.production.services.station_catalog import (
        STATION_CODE_ALIASES,
        STATION_LABELS,
        STATION_ORDER,
        resolve_station_code,
    )

    for stary, nowy in STATION_CODE_ALIASES.items():
        assert nowy in STATION_ORDER, nowy
        assert nowy in STATION_LABELS, nowy
        assert stary not in STATION_ORDER, stary
        assert resolve_station_code(stary) == nowy


def test_is_production_station_po_rename():
    """
    'finishing' przestaje być stanowiskiem produkcyjnym — świadomie.
    Alias ma być rozwijany ZANIM kod dojdzie do tej bramki.
    """
    from modules.production.services.station_catalog import (
        is_production_station,
        resolve_station_code,
        station_choices,
    )

    assert is_production_station('edges') is True
    assert is_production_station('painting') is True
    assert is_production_station('finishing') is False
    assert is_production_station(resolve_station_code('finishing')) is True

    kody = [kod for kod, _ in station_choices()]
    assert kody == ['cutting', 'assembly', 'gluing', 'formatting',
                    'edges', 'painting', 'packaging']


# Drugi plik pilnowany strukturalnie: to w nim siedzą kopie zestawu stanowisk,
# które po renamie katalogu wywracają import całego pakietu routerów.
SCIEZKA_DASHBOARDU = (
    Path(__file__).resolve().parents[1]
    / 'modules' / 'production' / 'routers' / 'api' / 'dashboard_api.py'
)


def _literaly_stringow(sciezka):
    """Wszystkie literały napisowe pliku (komentarzy AST nie widzi)."""
    drzewo = ast.parse(sciezka.read_text(encoding='utf-8'))
    return {w.value for w in ast.walk(drzewo)
            if isinstance(w, ast.Constant) and isinstance(w.value, str)}


def test_pakiet_routerow_produkcji_wstaje_po_zmianie_katalogu():
    """
    CAŁA racja bytu tego testu: dashboard_api buduje swoją mapę statusów
    indeksując katalog literałami kodów stanowisk, więc rename katalogu
    wywala KeyError PRZY IMPORCIE modułu. routers/__init__.py:39-43 łapie
    wyłącznie ImportError (KeyError nie jest jego podklasą), więc przewraca
    się import całego pakietu modules.production.routers — a wtedy testy
    API mobilnego i panelu nie dają się nawet ZEBRAĆ.

    Sam brak wyjątku nie wystarcza: gdyby to był ImportError, pakiet wstałby
    z api_bp = None i aplikacja po cichu straciłaby wszystkie endpointy.
    Dlatego sprawdzamy też, że blueprinty naprawdę są.
    """
    import importlib

    routers = importlib.import_module('modules.production.routers')

    assert routers.api_bp is not None, (
        'modules.production.routers wstało bez api_bp — import blueprintu API '
        'padł i został połknięty przez except ImportError'
    )
    assert routers.station_bp is not None


def test_dashboard_zna_kazde_stanowisko_katalogu():
    """
    Dashboard miał własny, WĘŻSZY zestaw stanowisk (sześć kafelków, bez
    lakierni) używany do liczenia kolejek, heartbeatu i średniej do
    deadline'u. Test pilnuje, żeby ten wewnętrzny zestaw pokrywał się z
    katalogiem — kafelki w szablonie to osobna warstwa (dokłada je dopiero
    Warstwa 5) i nie są tu sprawdzane.
    """
    import importlib

    from modules.production.services.station_catalog import (
        STATION_ORDER,
        STATION_PENDING_STATUS,
    )

    dashboard_api = importlib.import_module(
        'modules.production.routers.api.dashboard_api')

    assert set(dashboard_api._DASHBOARD_STATIONS) == set(STATION_ORDER)
    assert dashboard_api._STATION_PENDING_STATUS == dict(STATION_PENDING_STATUS)


def test_dashboard_nie_ma_juz_literalu_starego_stanowiska():
    """
    W dashboard_api stały CZTERY kopie zestawu stanowisk (krotka kafelków,
    ręczny słownik liczników, zaszyta lista pętli heartbeatu, lista statusów
    do średniego deadline'u) plus klucz koloru krzywej. Każda z nich po
    renamie albo wywalała KeyError, albo cicho gubiła stanowisko. Test
    pilnuje, żeby po tym zadaniu nie został ani jeden literał starego kodu
    ani starego statusu.
    """
    literaly = _literaly_stringow(SCIEZKA_DASHBOARDU)

    assert 'finishing' not in literaly
    assert 'czeka_na_wykanczanie' not in literaly
# ============================================================================
# REJESTRACJA TABLETÓW — zbiór kodów przyjmowanych przez ProductionDevice
# ============================================================================

SCIEZKA_MODELI = (
    Path(__file__).resolve().parents[1]
    / 'modules' / 'production' / 'models.py'
)


def _blok_kodow_urzadzen():
    """
    Tekst literału VALID_STATION_CODES razem z komentarzami w środku.

    AST tu nie wystarczy: interesują nas właśnie KOMENTARZE, których drzewo
    składniowe nie widzi, a to one niosą marker okresu przejściowego.
    """
    tekst = SCIEZKA_MODELI.read_text(encoding='utf-8')
    poczatek = tekst.index('VALID_STATION_CODES = {')
    koniec = tekst.index('}', poczatek)
    return tekst[poczatek:koniec + 1]


def _wpisy_kodow_urzadzen():
    """
    Wiersze zbioru rozbite na część z kodem i część z komentarzem.

    Rozdział jest tu istotą rzeczy, nie ozdobą: w tym samym zbiorze stoi wiersz
    `'edges',  # dawne 'finishing' ...` i całe zdania komentarza o starym
    tablecie. Szukanie `'finishing'` w surowym wierszu trafiałoby w nie
    wszystkie naraz, zamiast we wpis, o który chodzi.
    """
    for linia in _blok_kodow_urzadzen().splitlines():
        kod, _, komentarz = linia.partition('#')
        yield kod, komentarz


def test_urzadzenia_moga_sie_rejestrowac_na_kazdym_stanowisku():
    """
    Różnica zbiorów, nie lista kodów: stanowisko z katalogu bez wpisu
    w VALID_STATION_CODES to stanowisko, na którym nie da się postawić
    tabletu (mobile_api.py:187) ani przypisać pracownika
    (worker_service.py:313 — ta sama krotka, 422 przy zapisie profilu).
    """
    from modules.production.models import ProductionDevice
    from modules.production.services.station_catalog import (
        STATION_ORDER, resolve_station_code)

    brakujace = sorted(set(STATION_ORDER) - set(ProductionDevice.VALID_STATION_CODES))
    assert brakujace == [], (
        'Stanowiska z katalogu, na których nie da się zarejestrować tabletu: {}'
        .format(brakujace))

    # Trakownia stoi poza STATION_ORDER (własne tabele prod_sawmill_*),
    # ale tablet tam jest — regresja obok zmienianej krotki.
    assert 'sawmill' in ProductionDevice.VALID_STATION_CODES

    # OKRES PRZEJŚCIOWY: stary tablet wykańczalni ma dojechać do końca życia
    # na swojej rejestracji, a alias ma go przekładać na kod z katalogu.
    # Obie asercje znikają w kroku 20 wdrożenia razem z aliasem — i wtedy
    # mają zapalić się CELOWO.
    assert 'finishing' in ProductionDevice.VALID_STATION_CODES
    assert resolve_station_code('finishing') in ProductionDevice.VALID_STATION_CODES


def test_przejsciowy_kod_starego_tabletu_jest_oznaczony_w_zrodle():
    """
    Sam fakt, że 'finishing' siedzi w zbiorze, niczego nie mówi czytającemu:
    wygląda identycznie jak przeoczenie przy rozdziale stanowiska. Tekst
    źródłowy ma więc nieść marker, po którym widać, że ta wartość ZOSTAJE
    świadomie i ma wyznaczony moment usunięcia (krok 20 wdrożenia).

    Marker jest kotwicą dla późniejszego przeglądu resztek po 'finishing'
    w module produkcji — bez niego każdy taki przegląd albo zgłasza ten wpis
    jako regresję, albo musi go omijać z palca.

    W kroku 20 wdrożenia wpis znika razem z markerem, więc ten test zapala
    się wtedy CELOWO — tak samo jak asercje okresu przejściowego w teście
    powyżej.
    """
    wpisy = [(kod, komentarz) for kod, komentarz in _wpisy_kodow_urzadzen()
             if "'finishing'" in kod]

    assert len(wpisy) == 1, (
        'Kod przejściowy ma być w zbiorze dokładnie jednym wpisem, znaleziono: {}'
        .format([kod for kod, _ in wpisy]))
    assert 'finishing-ZOSTAJE' in wpisy[0][1], (
        'Wpis okresu przejściowego bez markera — po takim wierszu nie widać, '
        'czy to świadoma decyzja, czy resztka po rozdziale stanowiska: {!r}'
        .format(wpisy[0][0] + '#' + wpisy[0][1]))


def test_kazde_stanowisko_ma_telemetrie():
    """
    build_devices_telemetry buduje slownik WYLACZNIE po
    _STATION_CODES_WITH_TABLETS. Stanowisko spoza tej krotki nie dostaje
    klucza, wiec kafel na dashboardzie zostaje 'Niedostepne' i wyszarzony
    niezaleznie od tego, jak zywy jest tablet. Awaria bezglosna, nie do
    odroznienia od padnietego sprzetu.
    """
    from modules.production.services.mobile_api_service import (
        _STATION_CODES_WITH_TABLETS, build_devices_telemetry)
    from modules.production.services.station_catalog import STATION_ORDER

    brakujace = sorted(set(STATION_ORDER) - set(_STATION_CODES_WITH_TABLETS))
    assert brakujace == [], (
        'Stanowiska bez telemetrii — kafel zostanie "Niedostepne" na zawsze: {}'
        .format(brakujace))

    # Trakownia jest w krotce, choc nie ma jej w STATION_ORDER (tablet na
    # niej stoi, ale statusow ProductionProduct nie ma). Regresja obok.
    assert 'sawmill' in _STATION_CODES_WITH_TABLETS

    # Dowod, ze krotka faktycznie steruje wyjsciem, a nie tylko lezy obok.
    pusta_flota = build_devices_telemetry([])
    assert set(pusta_flota) == set(_STATION_CODES_WITH_TABLETS)
    for kod in STATION_ORDER:
        assert pusta_flota[kod]['status_label'] == 'Niedostępne', kod
        assert pusta_flota[kod]['active'] is False, kod


# ============================================================================
# KOLORY KRZYWYCH WYKRESU — mapa rownolegla do katalogu
# ============================================================================


def test_kazde_stanowisko_ma_kolor_wykresu():
    """
    Wykres 'Wydajnosc dzienna' w trybie zbiorczym rysuje krzywa dla kazdego
    kodu ze STATION_ORDER (dashboard_api.py:613, petla po kody_stanowisk).
    Brak wpisu w mapie kolorow nie wywraca widgetu (uzycia ida przez .get
    z KOLOR_REZERWOWY), tylko daje SZARA krzywa nie do odroznienia od
    sasiedniej — wykres, ktory klamie po cichu.
    """
    import importlib

    from modules.production.services.station_catalog import STATION_ORDER

    dashboard_api = importlib.import_module(
        'modules.production.routers.api.dashboard_api')

    kolory = dashboard_api.STATION_CHART_COLORS

    brakujace = sorted(set(STATION_ORDER) - set(kolory))
    assert brakujace == [], 'Stanowiska bez wlasnego koloru krzywej: {}'.format(brakujace)

    nadmiarowe = sorted(set(kolory) - set(STATION_ORDER))
    assert nadmiarowe == [], 'Kolory dla kodow spoza katalogu: {}'.format(nadmiarowe)

    for kod in STATION_ORDER:
        assert set(kolory[kod]) == {'border', 'bg'}, kod
        assert kolory[kod]['border'].startswith('#'), kod

    # Dwie krzywe w tym samym kolorze to ten sam blad co brak wpisu,
    # tylko trudniejszy do zauwazenia.
    obramowania = [kolory[kod]['border'] for kod in STATION_ORDER]
    assert len(set(obramowania)) == len(obramowania), obramowania

    # Kolor rezerwowy jest wylacznie dla kodow SPOZA katalogu.
    assert dashboard_api.KOLOR_REZERWOWY not in kolory.values()


# ============================================================================
# ALERTY TERMINOW — mapa rang rownolegla do katalogu
# ============================================================================


def test_kazde_stanowisko_ma_range_w_alertach_terminow():
    """
    Kafel 'Alerty terminow' sortuje zamowienia po randze statusu
    (_STATUS_RANK). Status kolejki spoza tej mapy dostaje _UNKNOWN_RANK
    i kod 'unknown' (dashboard_alerts.py:72-73) — pozycja laduje na koncu
    listy z nazwa, ktorej nikt na hali nie rozpozna.

    Petle ida po KATALOGU, wiec osme stanowisko zapali ten test samo.
    """
    from modules.production.services import dashboard_alerts
    from modules.production.services.station_catalog import (
        STATION_ORDER, STATION_PENDING_STATUS)

    ranking = dashboard_alerts._STATUS_RANK

    bez_rangi = sorted(
        status for status in STATION_PENDING_STATUS.values() if status not in ranking)
    assert bez_rangi == [], (
        'Statusy kolejek bez rangi w alertach terminow: {}'.format(bez_rangi))

    # Ranga ma wskazywac na TEN kod stanowiska, nie na dowolny.
    for kod, status in STATION_PENDING_STATUS.items():
        _, kod_w_rankingu = ranking[status]
        assert kod_w_rankingu == kod, (status, kod, kod_w_rankingu)

    # Zaden martwy kod nie moze zostac w mapie po rename. _station_of
    # (dashboard_alerts.py:76) oddaje taki kod wprost do station_short_label,
    # a ta nieznany kod zwraca SUROWO — pigulka alertu podpisuje sie wtedy
    # 'finishing' obok kafli 'Krawedzie' i nie lapie zadnej reguly
    # .il-alert-station[data-station=...] w production-panel.css, wiec
    # dodatkowo szarzeje. 'hold' i 'logistics' nie sa stanowiskami, maja
    # wlasne etykiety w _EXTRA_LABELS.
    martwe = sorted(
        status for status, (_, kod) in ranking.items()
        if kod not in STATION_ORDER and kod not in dashboard_alerts._EXTRA_LABELS)
    assert martwe == [], 'Rangi dla kodow spoza katalogu: {}'.format(martwe)

    # Kolejnosc rang ma odwzorowywac droge produktu przez hale.
    rangi = [ranking[STATION_PENDING_STATUS[kod]][0] for kod in STATION_ORDER]
    assert rangi == sorted(rangi), rangi


# ============================================================================
# STRAŻNIK DOKOŃCZENIA MIGRACJI
# ============================================================================

KORZEN = Path(__file__).resolve().parents[1]
KATALOG_PRODUKCJI = KORZEN / 'modules' / 'production'

# Komentarz-marker przy każdym wystąpieniu kodu 'finishing', które ZOSTAJE
# w module produkcji świadomie. Marker zamiast listy fragmentów linii:
# fragment rozjedzie się przy pierwszym przeformatowaniu pliku, marker nie.
#
# Sam marker nie wpada w WZORCE_UZYCIA (po słowie 'finishing' stoi w nim
# minus, nie cudzysłów ani dwukropek), więc nie zapala sam siebie.
MARKER = 'finishing-ZOSTAJE'

# Pliki, w których oczekujemy przynajmniej jednego oznaczonego wystąpienia.
# Wpis wskazujący na plik bez żadnego trafienia znaczy, że lista zgniła —
# osobna asercja niżej to łapie.
#
# TA MAPA MA SIĘ KURCZYĆ. W kroku 20 wdrożenia (zdjęcie okresu przejściowego,
# gdy cała flota chodzi na nowym buildzie) znikają cztery pierwsze wpisy.
# Zostaje wyłącznie products-module.js: nazwy klas CSS przy etykietach
# historycznych statusów, które 423 wiersze prod_product_events trzymają
# jako zwykły tekst.
DOZWOLONE_MARKERY = frozenset({
    # OKRES PRZEJŚCIOWY — znikają w kroku 20 wdrożenia.
    'services/station_catalog.py',        # STATION_CODE_ALIASES
    'models.py',                          # ProductionDevice.VALID_STATION_CODES
    'services/baselinker_status_sync.py', # PRODUCTION_STATIONS
    'services/mobile_api_service.py',     # docstring device_can_access_station
    # LEGACY — zostaje na stałe: nazwa klasy CSS przy etykiecie statusu
    # kolejki Krawędzi; klasa .status-finishing / .badge-finishing żyje
    # w arkuszach i w 423 wierszach historii prod_product_events.
    'static/js/modules/products-module.js',
})


# Co uznajemy za UŻYCIE kodu stanowiska, a nie za prozę o nim.
# Cudzysłów zaraz przy słowie odróżni literał kodu od nazwy klasy CSS
# ('finishing-theme', 'badge-finishing') i od przymiotnika w komentarzu.
WZORCE_UZYCIA = (
    re.compile(r"""['"]finishing['"]"""),        # literał kodu stanowiska
    re.compile(r"\bfinishing\s*:"),               # klucz obiektu JS bez cudzysłowów
    re.compile(
        r"\b(?:quantity_done_finishing"
        r"|finishing_completed_at"
        r"|finishing_started_at"
        r"|finishing_duration_minutes"
        r"|should_skip_finishing)\b"
    ),
)


def _linia_to_komentarz(linia):
    """
    Linie BĘDĄCE W CAŁOŚCI komentarzem pomijamy — proza o starym kodzie
    ('dawniej finishing', 'alias finishing -> edges') jest dokumentacją
    zmiany, nie jej niedokończeniem. Docstringów NIE pomijamy: opis
    zachowania endpointu ma mówić aktualnymi nazwami, a tam gdzie mówi
    o okresie przejściowym — nosić marker.
    """
    s = linia.strip()
    return s.startswith('#') or s.startswith('//') or s.startswith('*') or s.startswith('/*')


def _pliki_modulu_produkcji():
    """
    Skanujemy WYŁĄCZNIE poddrzewo modules/production liczone od korzenia repo.
    .claude/worktrees/ leży poza tym poddrzewem, więc rglob nigdy tam nie
    wejdzie — wykluczenie niżej jest zabezpieczeniem na wypadek, gdyby ktoś
    podniósł korzeń skanu do KORZEN. W tym katalogu siedzi OSIEROCONA kopia
    całego repo (91 MB, ostatnia zmiana 10.07, `git worktree list` jej nie
    zna, wskaźnik .git prowadzi do nieistniejącej ścieżki) — czytana przez
    skaner nigdy by nie zzieleniała.
    """
    for sciezka in sorted(KATALOG_PRODUKCJI.rglob('*')):
        if not sciezka.is_file() or sciezka.suffix not in ('.py', '.js'):
            continue
        czesci = sciezka.parts
        if '.claude' in czesci or '__pycache__' in czesci or 'vendor' in czesci:
            continue
        yield sciezka


def test_zaden_modul_produkcji_nie_zna_juz_kodu_finishing():
    winne = []
    oznaczone_w_pliku = {}

    for sciezka in _pliki_modulu_produkcji():
        klucz = sciezka.relative_to(KATALOG_PRODUKCJI).as_posix()
        tekst = sciezka.read_text(encoding='utf-8', errors='replace')
        for nr, linia in enumerate(tekst.splitlines(), start=1):
            if _linia_to_komentarz(linia):
                continue
            if not any(wzorzec.search(linia) for wzorzec in WZORCE_UZYCIA):
                continue
            if MARKER in linia and klucz in DOZWOLONE_MARKERY:
                oznaczone_w_pliku[klucz] = oznaczone_w_pliku.get(klucz, 0) + 1
                continue
            winne.append('{}:{}: {}'.format(klucz, nr, linia.strip()))

    assert winne == [], (
        'Kod stanowiska "finishing" został w modułach produkcji bez zgody.\n'
        'Albo dokończ rename, albo — jeśli to wystąpienie ma zostać — dopisz\n'
        'na końcu linii komentarz "{}: powód" i dodaj plik do DOZWOLONE_MARKERY:\n  '
        .format(MARKER) + '\n  '.join(winne))

    # Strażnik samej mapy: wpis, który nie ma już ani jednego oznaczonego
    # wystąpienia, znaczy, że lista zgniła i przestała cokolwiek przepuszczać
    # świadomie. Po kroku 20 wdrożenia ta asercja wymusi skrócenie mapy.
    zgnile = sorted(set(DOZWOLONE_MARKERY) - set(oznaczone_w_pliku))
    assert zgnile == [], (
        'DOZWOLONE_MARKERY wymienia pliki bez żadnego oznaczonego wystąpienia '
        '— usuń je z mapy: {}'.format(zgnile))
