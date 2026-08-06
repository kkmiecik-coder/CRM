# -*- coding: utf-8 -*-
"""Wzór objętości kłody — obwód w połowie długości, bryła jako walec (Huber)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from decimal import Decimal

import pytest

from modules.production.sawmill.services.volume import compute_log_volume_m3


def test_przyklad_kontrolny_ze_specyfikacji():
    """Wartość wyliczona, nie oszacowana — patrz sekcja 5 specyfikacji."""
    v = compute_log_volume_m3('125.6', '410.0')
    assert v == Decimal('0.514699')


def test_wynik_ma_zawsze_szesc_miejsc():
    v = compute_log_volume_m3('125.6', '100.0')
    assert v.as_tuple().exponent == -6


def test_walec_o_znanej_objetosci():
    """C = 100 cm (1 m), L = 100 cm (1 m) -> V = 1/(4*pi) m3."""
    v = compute_log_volume_m3('100.0', '100.0')
    assert v == Decimal('0.079577')


def test_dwukrotny_obwod_daje_czterokrotna_objetosc():
    """Przekrój rośnie z kwadratem obwodu — kontrola, że wzór nie zgubił potęgi."""
    pojedynczy = compute_log_volume_m3('100.0', '400.0')
    podwojny = compute_log_volume_m3('200.0', '400.0')
    assert podwojny == pojedynczy * 4


def test_zaokraglanie_w_gore_na_polowie():
    """ROUND_HALF_UP, nie bankierskie — wynik musi być deterministyczny."""
    from modules.production.sawmill.services.volume import _quantize
    assert _quantize(Decimal('0.0000005')) == Decimal('0.000001')
    assert _quantize(Decimal('0.0000015')) == Decimal('0.000002')


def test_przyjmuje_rozne_typy_wejscia():
    z_str = compute_log_volume_m3('125.6', '410.0')
    z_dec = compute_log_volume_m3(Decimal('125.6'), Decimal('410.0'))
    z_float = compute_log_volume_m3(125.6, 410.0)
    assert z_str == z_dec == z_float


def test_odrzuca_wartosci_niedodatnie():
    with pytest.raises(ValueError):
        compute_log_volume_m3('0', '410.0')
    with pytest.raises(ValueError):
        compute_log_volume_m3('125.6', '0')
    with pytest.raises(ValueError):
        compute_log_volume_m3('-1', '410.0')
