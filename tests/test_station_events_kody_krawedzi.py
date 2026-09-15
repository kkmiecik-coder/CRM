# -*- coding: utf-8 -*-
"""
Kody stanowisk w station_events_service.

Serwis jest z założenia OGÓLNY — filtruje po dowolnym station_code, więc żaden
test danych nie złapie w nim martwego kodu: prod_station_events.station_code to
String(32) bez enuma i bez FK, a filtr po nieistniejącym kodzie oddaje zera bez
błędu. Jedyne, co da się tu przypiąć, to spisany kontrakt: lista kodów
w docstringu agregatu i brak śladu po 'finishing' w całym module.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.production.services import station_events_service
from modules.production.services.station_catalog import STATION_ORDER

KORZEN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ZRODLO = os.path.join(KORZEN, 'modules', 'production', 'services',
                      'station_events_service.py')


def _zrodlo():
    with open(ZRODLO, encoding='utf-8') as f:
        return f.read()


def test_docstring_wymienia_wszystkie_kody_katalogu():
    """
    Docstring jest jedyną dokumentacją tego, co wolno podać jako station_code.
    Przed rozdziałem wykańczania brakowało w nim lakierni, a po rozdziale
    brakowałoby też Krawędzi — czyli dwóch z siedmiu stanowisk.
    """
    opis = station_events_service.get_station_work_in_range.__doc__

    for kod in STATION_ORDER:
        assert f"'{kod}'" in opis, kod


def test_modul_nie_zna_juz_kodu_finishing():
    assert 'finishing' not in _zrodlo()
