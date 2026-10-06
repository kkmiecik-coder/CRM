# -*- coding: utf-8 -*-
"""
Termin zamówienia: dni robocze albo kalendarzowe (`DEADLINE_DAY_TYPE`) — plan K1, Task 5; spec 2026-10-04, 4.3.

Przełącznik działa wyłącznie przy NADAWANIU terminu nowym pozycjom. Zamówienia już zaimportowane zachowują
swój termin — nikt go nie przelicza wstecz (decyzja Konrada 4.10).

Plik nie zakłada tabeli prod_product_events (konwencja pakietu).
"""
import ast
import os
from datetime import date, datetime

import pytest

from modules.production.priorytety.services import ustawienia
from modules.production.services import config_service
from modules.production.services.sync_service import BaselinkerSyncService
from tests.logistyka_fixtures import app  # noqa: F401
from tests.priorytety_fixtures import czyste_ustawienia, ustaw  # noqa: F401

pytestmark = pytest.mark.usefixtures('app', 'czyste_ustawienia')

PONIEDZIALEK = date(2026, 10, 5)
PIATEK = date(2026, 10, 9)
ZRODLO_SYNC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           'modules', 'production', 'services', 'sync_service.py')


def _termin(dzien, serwis=None):
    """Termin zamówienia, które weszło w status „Nowe – opłacone” w południe dnia `dzien`."""
    zamowienie = {'date_in_status': int(datetime(dzien.year, dzien.month, dzien.day, 12, 0).timestamp())}
    return (serwis or BaselinkerSyncService())._calculate_deadline_date(zamowienie)


def _z_wykonczeniem(monkeypatch):
    serwis = BaselinkerSyncService()
    monkeypatch.setattr(serwis, '_order_has_finished_product', lambda order: True)
    return serwis


def test_domyslnie_dni_robocze_jak_dotad():
    # bez wierszy w prod_config: 10 dni roboczych (wartość awaryjna, decyzja Konrada 5.10)
    assert _termin(PONIEDZIALEK) == date(2026, 10, 19)
    ustaw('DEADLINE_DEFAULT_DAYS', '1', 'integer')
    assert _termin(PIATEK) == date(2026, 10, 12)        # piątek + 1 dzień roboczy = poniedziałek
    # jawne „robocze” to to samo
    ustaw('DEADLINE_DAY_TYPE', 'robocze')
    assert _termin(PIATEK) == date(2026, 10, 12)


def test_kalendarzowe_licza_soboty_i_niedziele():
    ustaw('DEADLINE_DAY_TYPE', 'kalendarzowe')
    assert _termin(PONIEDZIALEK) == date(2026, 10, 15)   # 5.10 + 10 dni
    ustaw('DEADLINE_DEFAULT_DAYS', '1', 'integer')
    assert _termin(PIATEK) == date(2026, 10, 10)         # piątek + 1 dzień = sobota


def test_nieznany_typ_dni_to_robocze_z_ostrzezeniem(monkeypatch):
    ostrzezenia = []

    class Szpieg(object):
        def warning(self, message, **kwargs):
            ostrzezenia.append(message)

        debug = info = error = lambda self, *a, **k: None

    monkeypatch.setattr(ustawienia, 'logger', Szpieg())
    ustaw('DEADLINE_DAY_TYPE', 'lunarne')
    assert _termin(PONIEDZIALEK) == date(2026, 10, 19)
    assert len(ostrzezenia) == 1


def test_zamowienie_z_wykonczeniem_bierze_finished_days_w_obu_trybach(monkeypatch):
    serwis = _z_wykonczeniem(monkeypatch)
    assert _termin(PONIEDZIALEK, serwis) == date(2026, 10, 23)     # 14 dni roboczych (wartość awaryjna)
    ustaw('DEADLINE_FINISHED_DAYS', '10', 'integer')
    assert _termin(PONIEDZIALEK, serwis) == date(2026, 10, 19)     # 10 dni roboczych
    ustaw('DEADLINE_DAY_TYPE', 'kalendarzowe')
    assert _termin(PONIEDZIALEK, serwis) == date(2026, 10, 15)     # 10 dni kalendarzowych
    # zamówienie surowe w tym samym trybie liczy dalej z DEADLINE_DEFAULT_DAYS (10 dni kalendarzowych)
    assert _termin(PONIEDZIALEK) == date(2026, 10, 15)


def test_blad_odczytu_typu_dni_zostawia_dni_robocze(monkeypatch):
    """Awaria odczytu ustawienia nie może wywrócić importu zamówienia — zostaje dzisiejsze zachowanie."""
    def awaria():
        raise RuntimeError('sztuczna awaria ustawien')
    monkeypatch.setattr(ustawienia, 'typ_dni_terminu', awaria)
    assert _termin(PONIEDZIALEK) == date(2026, 10, 19)


def test_deadline_date_nadawany_tylko_przy_tworzeniu_pozycji():
    """Strukturalnie na źródle: termin liczą wyłącznie dwie funkcje tworzące pozycje przy imporcie. Zmiany z Base.
    (`apply_baselinker_changes`) nie liczą terminu — nowa pozycja istniejącego zamówienia przejmuje termin
    istniejącej. Nie ma więc drogi, którą przełącznik przeliczyłby terminy wstecz."""
    with open(ZRODLO_SYNC, encoding='utf-8') as f:
        drzewo = ast.parse(f.read())
    klasa = next(n for n in drzewo.body if isinstance(n, ast.ClassDef) and n.name == 'BaselinkerSyncService')
    wolajacy = set()
    for funkcja in [n for n in klasa.body if isinstance(n, ast.FunctionDef)]:
        for wezel in ast.walk(funkcja):
            if (isinstance(wezel, ast.Call) and isinstance(wezel.func, ast.Attribute)
                    and wezel.func.attr == '_calculate_deadline_date'):
                wolajacy.add(funkcja.name)
    assert wolajacy == {'_create_product_from_order_data', '_process_single_order_enhanced'}
    assert 'apply_baselinker_changes' in {n.name for n in klasa.body if isinstance(n, ast.FunctionDef)}

    # Typ dni czyta wyłącznie _calculate_deadline_date (żaden inny kod produkcji nie sięga po przełącznik).
    czytajacy = set()
    for funkcja in [n for n in klasa.body if isinstance(n, ast.FunctionDef)]:
        for wezel in ast.walk(funkcja):
            if isinstance(wezel, ast.Attribute) and wezel.attr == 'typ_dni_terminu':
                czytajacy.add(funkcja.name)
    assert czytajacy == {'_calculate_deadline_date'}


def test_domyslna_wartosc_w_config_service():
    assert config_service.get_config_service()._default_values['DEADLINE_DAY_TYPE'] == 'robocze'
    assert config_service.get_config('DEADLINE_DAY_TYPE') == 'robocze'
    assert ustawienia.typ_dni_terminu() == 'robocze'


# ══ Terminy 10 / 14 dni w bazie i jako wartości awaryjne (decyzja Konrada 5.10, spec 4.3) ══════════════════════

def test_wartosci_awaryjne_terminow_10_i_14():
    """Gdy wiersza `prod_config` brak, wszystkie trzy miejsca kodu biorą 10 (surowe) i 14 (z wykończeniem) dni."""
    domyslne = config_service.get_config_service()._default_values
    assert (domyslne['DEADLINE_DEFAULT_DAYS'], domyslne['DEADLINE_FINISHED_DAYS']) == (10, 14)
    assert (ustawienia.termin_surowe_dni(), ustawienia.termin_wykonczone_dni()) == (10, 14)


def test_awaria_konfiguracji_terminu_daje_10_i_14_dni(monkeypatch):
    """Awaria odczytu konfiguracji przy imporcie nie wywraca importu — termin z wartości awaryjnych 10 / 14."""
    def awaria():
        raise RuntimeError('sztuczna awaria konfiguracji')
    surowy, wykonczony = BaselinkerSyncService(), _z_wykonczeniem(monkeypatch)
    # Awaria tylko na czas liczenia terminu — sprzątanie fikstur czyta konfigurację normalnie.
    with monkeypatch.context() as m:
        m.setattr(config_service, 'get_config_service', awaria)
        assert _termin(PONIEDZIALEK, surowy) == date(2026, 10, 19)       # 10 dni roboczych
        assert _termin(PONIEDZIALEK, wykonczony) == date(2026, 10, 23)   # 14 dni roboczych


def test_wartosci_z_bazy_wygrywaja_z_awaryjnymi(monkeypatch):
    ustaw('DEADLINE_DEFAULT_DAYS', '12', 'integer')
    ustaw('DEADLINE_FINISHED_DAYS', '20', 'integer')
    assert _termin(PONIEDZIALEK) == date(2026, 10, 21)                          # 12 dni roboczych
    assert _termin(PONIEDZIALEK, _z_wykonczeniem(monkeypatch)) == date(2026, 11, 2)    # 20 dni roboczych
