# -*- coding: utf-8 -*-
"""
Objętość kłody — metoda Hubera: przekrój mierzony w połowie długości, bryła
traktowana jak walec o tym przekroju.

    V = pi/4 * (d / 100)^2 * (length_cm / 100)   [m3]

Pracownik podaje WYŁĄCZNIE dwie liczby: długość i średnicę na środku kłody —
metodyka ustalona przez zarząd. Pojedynczy przekrój w połowie długości
uśrednia zbieżność pnia.

Średnica to JEDEN odczyt, bez drugiego pomiaru w osi prostopadłej — owalność
kłody nie jest korygowana. To świadoma decyzja: trzecie pole na tablecie
spowalnia stanowisko bardziej, niż jest wart zysk na dokładności. Wcześniej
mierzony był obwód taśmą (obejmuje cały obrys, więc owalność uśrednia sama);
zmiana na średnicę to decyzja o metodzie pomiaru na hali, nie o wzorze —
matematycznie d = C / pi i obie drogi dają tę samą objętość dla tej samej
kłody.

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


def compute_log_volume_m3(mid_diameter_cm, length_cm):
    """Objętość kłody w m3, kwantyzowana do 6 miejsc po przecinku."""
    diameter = _to_decimal(mid_diameter_cm, 'mid_diameter_cm')
    length = _to_decimal(length_cm, 'length_cm')

    # Jedno wyrażenie zamiast liczenia najpierw pola przekroju — pośrednie
    # zaokrąglenie pola przenosiłoby się na objętość.
    area_factor = PI * (diameter / Decimal(100)) ** 2 / Decimal(4)
    volume = area_factor * (length / Decimal(100))
    return _quantize(volume)
