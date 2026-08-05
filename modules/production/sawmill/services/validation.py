# -*- coding: utf-8 -*-
"""
Walidacja pomiarów trakowni.

Tablet sprawdza to samo lokalnie (musi działać offline), ale serwer sprawdza
ZAWSZE i niezależnie — urządzenie może być stare, przerobione albo wysyłać
z kolejki sprzed zmiany limitów.
"""

from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation

MEASUREMENT_FIELDS = ('butt_d1_cm', 'butt_d2_cm', 'top_d1_cm', 'top_d2_cm', 'length_cm')
DIAMETER_FIELDS = ('butt_d1_cm', 'butt_d2_cm', 'top_d1_cm', 'top_d2_cm')

# Zegar tabletu spieszący się o kilka minut nie może kosztować pomiaru.
FUTURE_TOLERANCE = timedelta(minutes=5)
MAX_AGE = timedelta(days=30)


class SawmillValidationError(Exception):
    """Błąd walidacji z informacją, które pole zawiodło — mapowany na HTTP 422."""

    def __init__(self, field, detail):
        super().__init__('{}: {}'.format(field, detail))
        self.field = field
        self.detail = detail


def _to_decimal(value, field):
    if value is None or value == '':
        raise SawmillValidationError(field, u'pole jest wymagane')
    try:
        return Decimal(str(value).replace(',', '.'))
    except (InvalidOperation, ValueError):
        raise SawmillValidationError(field, u'wartość nie jest liczbą')


def _check_range(value, field, minimum, maximum):
    # Limit ustawiony na None znaczy „nie sprawdzaj". Porównanie z None
    # w Pythonie rzuca TypeError, więc trzeba to obsłużyć jawnie.
    if minimum is not None and value < Decimal(str(minimum)):
        raise SawmillValidationError(
            field, u'wartość {} poniżej minimum {}'.format(value, minimum))
    if maximum is not None and value > Decimal(str(maximum)):
        raise SawmillValidationError(
            field, u'wartość {} powyżej maksimum {}'.format(value, maximum))


def _check_precision(value, field, decimal_places):
    exponent = value.as_tuple().exponent
    if exponent < -int(decimal_places):
        raise SawmillValidationError(
            field, u'dopuszczalne maksymalnie {} miejsc po przecinku'.format(decimal_places))


def validate_measurements(payload, settings):
    """
    Sprawdza pięć wymiarów kłody. Zwraca słownik Decimal-i gotowy do zapisu.
    Rzuca SawmillValidationError przy pierwszym błędzie.
    """
    decimal_places = settings.get('decimal_places', 1)
    result = {}

    for field in MEASUREMENT_FIELDS:
        value = _to_decimal(payload.get(field), field)
        if value <= 0:
            raise SawmillValidationError(field, u'wartość musi być dodatnia')
        _check_precision(value, field, decimal_places)

        if field in DIAMETER_FIELDS:
            _check_range(value, field,
                         settings.get('min_diameter_cm'), settings.get('max_diameter_cm'))
        else:
            _check_range(value, field,
                         settings.get('min_length_cm'), settings.get('max_length_cm'))

        result[field] = value

    return result


def parse_measured_at(value, now=None):
    """
    Parsuje naiwny ISO-8601 czasu lokalnego, bez offsetu strefy.

    Przyszłość powyżej tolerancji jest PRZYCINANA do now, nie odrzucana —
    w kontrakcie API 422 znaczy „nie ponawiaj", więc odrzucenie z powodu
    dryfu zegara trwale zgubiłoby poprawny pomiar.
    """
    if now is None:
        now = datetime.now()

    if not value:
        raise SawmillValidationError('measured_at', u'pole jest wymagane')

    try:
        parsed = datetime.fromisoformat(str(value))
    except (ValueError, TypeError):
        raise SawmillValidationError(
            'measured_at', u'oczekiwano formatu RRRR-MM-DDTGG:MM:SS')

    if parsed.tzinfo is not None:
        raise SawmillValidationError(
            'measured_at', u'oczekiwano czasu lokalnego bez offsetu strefy')

    if parsed > now + FUTURE_TOLERANCE:
        return now

    if parsed < now - MAX_AGE:
        raise SawmillValidationError(
            'measured_at', u'pomiar starszy niż 30 dni')

    return parsed
