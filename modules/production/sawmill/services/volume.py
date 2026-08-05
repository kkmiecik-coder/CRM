# -*- coding: utf-8 -*-
"""
Objętość kłody — metoda średniej z dwóch końców, bryła traktowana jak walec.

    d_śr = (butt_d1 + butt_d2 + top_d1 + top_d2) / 4   [cm]
    V    = pi/4 * (d_śr / 100)^2 * (length_cm / 100)   [m3]

Dwa prostopadłe pomiary na każdym czole eliminują błąd owalności kłody.
Bez potrąceń na korę i bez zaokrągleń wejścia — liczymy dokładnie to,
co wpisał pracownik.

Obliczenia na Decimal, nie float: te liczby trafiają do rozliczeń
finansowych z dostawcami i muszą być deterministyczne.
"""

from decimal import Decimal, ROUND_HALF_UP

# Dokładność wystarczająca dla Decimal o domyślnej precyzji 28 cyfr znaczących.
PI = Decimal('3.14159265358979323846')

# Objętość zapisujemy z dokładnością do 6 miejsc — kolumna DECIMAL(12,6).
_VOLUME_EXPONENT = Decimal('0.000001')


def _to_decimal(value, name):
    """Konwersja przez str, żeby nie wciągnąć błędu reprezentacji float."""
    try:
        result = Decimal(str(value))
    except Exception as exc:
        raise ValueError(u"{}: nieprawidłowa liczba ({!r})".format(name, value)) from exc
    if result <= 0:
        raise ValueError(u"{}: wartość musi być dodatnia (otrzymano {})".format(name, result))
    return result


def _quantize(value):
    """Kwantyzacja do 6 miejsc, ROUND_HALF_UP (nie bankierskie)."""
    return value.quantize(_VOLUME_EXPONENT, rounding=ROUND_HALF_UP)


def mean_diameter_cm(butt_d1, butt_d2, top_d1, top_d2):
    """Średnia arytmetyczna czterech pomiarów średnicy, w centymetrach."""
    values = [
        _to_decimal(butt_d1, 'butt_d1_cm'),
        _to_decimal(butt_d2, 'butt_d2_cm'),
        _to_decimal(top_d1, 'top_d1_cm'),
        _to_decimal(top_d2, 'top_d2_cm'),
    ]
    return sum(values) / Decimal(4)


def compute_log_volume_m3(butt_d1, butt_d2, top_d1, top_d2, length_cm):
    """Objętość kłody w m3, kwantyzowana do 6 miejsc po przecinku."""
    diameter_cm = mean_diameter_cm(butt_d1, butt_d2, top_d1, top_d2)
    length = _to_decimal(length_cm, 'length_cm')

    radius_factor = (diameter_cm / Decimal(100)) ** 2
    volume = PI / Decimal(4) * radius_factor * (length / Decimal(100))
    return _quantize(volume)
