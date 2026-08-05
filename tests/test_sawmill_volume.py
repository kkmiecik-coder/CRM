# -*- coding: utf-8 -*-
"""Wzór objętości kłody — średnia z czterech średnic, bryła jako walec."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from decimal import Decimal

import pytest

from modules.production.sawmill.services.volume import (
    compute_log_volume_m3,
    mean_diameter_cm,
)


def test_srednia_z_czterech_srednic():
    assert mean_diameter_cm('42.0', '38.0', '41.0', '37.0') == Decimal('39.5')


def test_przyklad_kontrolny_ze_specyfikacji():
    """Wartość wyliczona, nie oszacowana — patrz sekcja 5 specyfikacji."""
    v = compute_log_volume_m3('42.0', '38.0', '41.0', '37.0', '410.0')
    assert v == Decimal('0.502421')


def test_wynik_ma_zawsze_szesc_miejsc():
    v = compute_log_volume_m3('40.0', '40.0', '40.0', '40.0', '100.0')
    assert v.as_tuple().exponent == -6


def test_walec_o_znanej_objetosci():
    """d = 100 cm (1 m), L = 100 cm (1 m) -> V = pi/4 m3."""
    v = compute_log_volume_m3('100.0', '100.0', '100.0', '100.0', '100.0')
    assert v == Decimal('0.785398')


def test_zaokraglanie_w_gore_na_polowie():
    """ROUND_HALF_UP, nie bankierskie — wynik musi być deterministyczny."""
    from modules.production.sawmill.services.volume import _quantize
    assert _quantize(Decimal('0.0000005')) == Decimal('0.000001')
    assert _quantize(Decimal('0.0000015')) == Decimal('0.000002')


def test_przyjmuje_rozne_typy_wejscia():
    z_str = compute_log_volume_m3('42.0', '38.0', '41.0', '37.0', '410.0')
    z_dec = compute_log_volume_m3(
        Decimal('42.0'), Decimal('38.0'), Decimal('41.0'), Decimal('37.0'), Decimal('410.0')
    )
    z_int = compute_log_volume_m3(42, 38, 41, 37, 410)
    assert z_str == z_dec == z_int


def test_odrzuca_wartosci_niedodatnie():
    with pytest.raises(ValueError):
        compute_log_volume_m3('0', '38.0', '41.0', '37.0', '410.0')
    with pytest.raises(ValueError):
        compute_log_volume_m3('42.0', '38.0', '41.0', '37.0', '0')
    with pytest.raises(ValueError):
        compute_log_volume_m3('42.0', '-1', '41.0', '37.0', '410.0')
