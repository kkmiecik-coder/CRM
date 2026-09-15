# -*- coding: utf-8 -*-
"""
Kody stanowisk i statusów zapisane WPROST w szablonach raportów.

W repozytorium nie ma runtime'u JS, więc te testy sprawdzają własności czytelne
ze źródła — konwencja tests/test_checkout_js.py.

Powód istnienia: front produkcji nie ma ŻADNEGO pokrycia na kody stanowisk.
Pętla w tests/test_reports_przeglad.py:278-300 wygląda jak strażnik literałów
w JS, ale porównuje katalog z dumpem JSON tego samego katalogu — jest zielona
przy każdym zestawie kodów.

Objaw braku klucza jest w obu szablonach ten sam i nie jest błędem: seria
wpada do puli rezerwowej (mix.html: '#64748b'; deadlines.html: DP_KOLORY_REZERWA
indeksowana pozycją serii) i potrafi mieć inny kolor po każdym odświeżeniu.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.production.services.station_catalog import (
    STATION_ORDER, STATION_PENDING_STATUS,
)

KORZEN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SZABLONY = os.path.join(KORZEN, 'modules', 'production', 'templates',
                        'components', 'reports')
MIX = os.path.join(SZABLONY, 'mix.html')
TERMINY = os.path.join(SZABLONY, 'deadlines.html')


def _zrodlo(sciezka):
    with open(sciezka, encoding='utf-8') as f:
        return f.read()


def _mapa(zrodlo, naglowek):
    """Ciało literału obiektowego zadeklarowanego tym nagłówkiem."""
    poczatek = zrodlo.index(naglowek)
    reszta = zrodlo[poczatek:]
    return reszta[:reszta.index('};')]


def test_miks_ma_kolor_dla_kazdej_kolejki_stanowiska():
    mapa = _mapa(_zrodlo(MIX), 'const colorMap = {')

    for status in STATION_PENDING_STATUS.values():
        assert f"'{status}'" in mapa, status


def test_miks_nie_zna_juz_starego_statusu():
    assert 'czeka_na_wykanczanie' not in _zrodlo(MIX)


def test_terminy_maja_kolor_dla_kazdego_stanowiska():
    mapa = _mapa(_zrodlo(TERMINY), 'const DP_KOLORY = {')

    for kod in STATION_ORDER:
        assert f'{kod}:' in mapa, kod


def test_terminy_nie_znaja_juz_kodu_finishing():
    assert 'finishing' not in _zrodlo(TERMINY)
