# -*- coding: utf-8 -*-
"""Normalizacja kąta obrotu kształtu przed zapisem do bazy."""

import pytest

from modules.calculator.services.quote_service import _normalizuj_kat_obrotu


@pytest.mark.parametrize("wejscie,oczekiwane", [
    (0, 0),
    (37, 37),
    (359, 359),
    (360, 0),
    (370, 10),
    (-30, 330),
    ("45", 45),
    (45.4, 45),
])
def test_sprowadza_do_zakresu_0_359(wejscie, oczekiwane):
    assert _normalizuj_kat_obrotu(wejscie) == oczekiwane


@pytest.mark.parametrize("wejscie", [None, "", "abc", [], {}])
def test_smieci_daja_none(wejscie):
    assert _normalizuj_kat_obrotu(wejscie) is None
