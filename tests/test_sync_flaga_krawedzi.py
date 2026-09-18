# -*- coding: utf-8 -*-
"""
Rozjazd między wyceną a flagą obróbki krawędzi na pozycji produkcyjnej.

Po rozdziale Wykańczania na Krawędzie i Lakiernię parsed_edge_processing jest
JEDYNYM przełącznikiem trasy: should_skip_edges() pyta wyłącznie o niego.
Fałszywy negatyw parsera wysyła produkt z formatowania prosto do Lakierni
i obróbka krawędzi nigdy się fizycznie nie wykonuje. Wcześniej taki rozjazd
gubił tylko rysunek krawędzi, więc nikt go nie zauważał.

Flagi NIE podnosimy z wyceny — źródłem prawdy dla produkcji jest parser nazwy
produktu. Rozjazd ma być jednak głośny w logach.

Testy operują na czystym dictcie, bez bazy i bez ProductionProduct. Ten plik nie
zakłada tabeli prod_product_events, bo nie robi tego żaden inny plik w pakiecie —
listener audytu milczy w całym przebiegu i tak ma zostać.

KOLEJNOŚĆ W TEŚCIE JEST ISTOTNA: BaselinkerSyncService() wołamy PRZED podmianą
loggera. Konstruktor wywołuje _load_config() (sync_service.py:49), które poza
kontekstem aplikacji wpada w except i loguje własne logger.warning('Próba
fallback...'). Atrapa założona wcześniej zliczyłaby to ostrzeżenie jako nasze.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from types import SimpleNamespace

from modules.production.services import sync_service
from modules.production.services.sync_service import BaselinkerSyncService


class _LoggerSzpieg:
    """Podmiana za structured logger — zapamiętuje wyłącznie ostrzeżenia."""

    def __init__(self):
        self.ostrzezenia = []

    def debug(self, message, **kwargs):
        pass

    def info(self, message, **kwargs):
        pass

    def warning(self, message, **kwargs):
        self.ostrzezenia.append((message, kwargs))

    def error(self, message, **kwargs):
        pass


def _detail(**nadpisania):
    dane = dict(
        id=77,
        shape_svg=None,
        shape=None,
        shape_rotation=None,
        edges_type='round',
        edges_r_value=5,
        edges_angle_value=None,
        edges_mode='basic',
        edges_config=[{'letter': 'A'}],
        edges_svg=None,
    )
    dane.update(nadpisania)
    return SimpleNamespace(**dane)


def test_wycena_z_krawedziami_przy_wylaczonej_fladze_daje_ostrzezenie(monkeypatch):
    service = BaselinkerSyncService()
    szpieg = _LoggerSzpieg()
    monkeypatch.setattr(sync_service, 'logger', szpieg)
    product_data = {'parsed_edge_processing': False, 'short_product_id': '26044_1'}

    service._apply_quote_detail_to_product_data(product_data, _detail())

    assert len(szpieg.ostrzezenia) == 1
    assert 'Krawędzie' in szpieg.ostrzezenia[0][0]
    assert szpieg.ostrzezenia[0][1]['extra']['short_product_id'] == '26044_1'
    # Flaga NIE jest podnoszona — wycena nie zmienia trasy fizycznej sztuki.
    assert product_data['parsed_edge_processing'] is False
    assert 'parsed_edge_type' not in product_data


def test_zgodna_flaga_nie_daje_ostrzezenia(monkeypatch):
    service = BaselinkerSyncService()
    szpieg = _LoggerSzpieg()
    monkeypatch.setattr(sync_service, 'logger', szpieg)
    product_data = {'parsed_edge_processing': True, 'short_product_id': '26044_2'}

    service._apply_quote_detail_to_product_data(product_data, _detail())

    assert szpieg.ostrzezenia == []
    assert product_data['parsed_edge_type'] == 'zaokrąglenie'


def test_wycena_bez_krawedzi_nie_daje_ostrzezenia(monkeypatch):
    service = BaselinkerSyncService()
    szpieg = _LoggerSzpieg()
    monkeypatch.setattr(sync_service, 'logger', szpieg)
    product_data = {'parsed_edge_processing': False, 'short_product_id': '26044_3'}

    service._apply_quote_detail_to_product_data(
        product_data, _detail(edges_type=None, edges_config=None, edges_r_value=None))

    assert szpieg.ostrzezenia == []


def test_sama_konfiguracja_liter_bez_typu_tez_daje_ostrzezenie(monkeypatch):
    """
    Wzmocnienie: warunek jest sumą logiczną (edges_type LUB edges_config), nie
    koniunkcją. Wycena w trybie advanced potrafi mieć edges_config (litery +
    grupy) bez wypełnionego top-level edges_type — implementacja napisana
    z 'and' zamiast 'or' przeszłaby oba testy z brief (bo tam oba pola są
    razem truthy albo razem falsy), a tutaj by ją złapało.
    """
    service = BaselinkerSyncService()
    szpieg = _LoggerSzpieg()
    monkeypatch.setattr(sync_service, 'logger', szpieg)
    product_data = {'parsed_edge_processing': False, 'short_product_id': '26044_4'}

    service._apply_quote_detail_to_product_data(
        product_data, _detail(edges_type=None, edges_r_value=None))

    assert len(szpieg.ostrzezenia) == 1


def test_sam_typ_krawedzi_bez_konfiguracji_liter_tez_daje_ostrzezenie(monkeypatch):
    """Symetryczne wzmocnienie: edges_type ustawiony, edges_config puste."""
    service = BaselinkerSyncService()
    szpieg = _LoggerSzpieg()
    monkeypatch.setattr(sync_service, 'logger', szpieg)
    product_data = {'parsed_edge_processing': False, 'short_product_id': '26044_5'}

    service._apply_quote_detail_to_product_data(
        product_data, _detail(edges_config=None))

    assert len(szpieg.ostrzezenia) == 1
