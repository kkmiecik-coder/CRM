# -*- coding: utf-8 -*-
"""Wzór objętości kłody — średnica w połowie długości, bryła jako walec (Huber)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from decimal import Decimal

import pytest

from modules.production.sawmill.services.volume import compute_log_volume_m3


def test_przyklad_kontrolny():
    """d = 40 cm, L = 410 cm -> V = pi/4 * 0.4^2 * 4.1 m3."""
    v = compute_log_volume_m3('40.0', '410.0')
    assert v == Decimal('0.515221')


def test_wynik_ma_zawsze_szesc_miejsc():
    v = compute_log_volume_m3('40.0', '100.0')
    assert v.as_tuple().exponent == -6


def test_walec_o_znanej_objetosci():
    """d = 100 cm (1 m), L = 100 cm (1 m) -> V = pi/4 m3."""
    v = compute_log_volume_m3('100.0', '100.0')
    assert v == Decimal('0.785398')


def test_dwukrotna_srednica_daje_czterokrotna_objetosc():
    """
    Przekrój rośnie z kwadratem średnicy — kontrola, że wzór nie zgubił potęgi.

    Tolerancja 1e-6, bo oba wyniki są kwantyzowane osobno do 6 miejsc:
    poczwórna wartość zaokrąglona w dół nie musi trafić co do ostatniej cyfry
    w zaokrąglony w górę wynik podwojonej średnicy.
    """
    pojedyncza = compute_log_volume_m3('50.0', '400.0')
    podwojna = compute_log_volume_m3('100.0', '400.0')
    assert abs(podwojna - pojedyncza * 4) <= Decimal('0.000001')


def test_srednica_nie_jest_mylona_z_obwodem():
    """
    Ten sam odczyt liczony jako średnica daje pi^2/4 (~2.47) razy więcej niż
    liczony jako obwód. Gdyby ktoś przy refaktorze przywrócił stary wzór,
    testy wyżej przeszłyby z inną stałą — ten nie przejdzie.
    """
    jako_srednica = compute_log_volume_m3('100.0', '100.0')
    jako_obwod = Decimal('0.079577')  # (C/100)^2 / (4*pi) * (L/100)
    assert jako_srednica > jako_obwod * 9


def test_zaokraglanie_w_gore_na_polowie():
    """ROUND_HALF_UP, nie bankierskie — wynik musi być deterministyczny."""
    from modules.production.sawmill.services.volume import _quantize
    assert _quantize(Decimal('0.0000005')) == Decimal('0.000001')
    assert _quantize(Decimal('0.0000015')) == Decimal('0.000002')


def test_przyjmuje_rozne_typy_wejscia():
    z_str = compute_log_volume_m3('40.0', '410.0')
    z_dec = compute_log_volume_m3(Decimal('40.0'), Decimal('410.0'))
    z_float = compute_log_volume_m3(40.0, 410.0)
    assert z_str == z_dec == z_float


def test_odrzuca_wartosci_niedodatnie():
    with pytest.raises(ValueError):
        compute_log_volume_m3('0', '410.0')
    with pytest.raises(ValueError):
        compute_log_volume_m3('40.0', '0')
    with pytest.raises(ValueError):
        compute_log_volume_m3('-1', '410.0')
