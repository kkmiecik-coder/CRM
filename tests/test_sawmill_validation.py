# -*- coding: utf-8 -*-
"""Walidacja pomiarów trakowni i obsługa ustawień."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from modules.production.sawmill.services.settings import DEFAULT_SETTINGS
from modules.production.sawmill.services.validation import (
    SawmillValidationError,
    parse_measured_at,
    validate_measurements,
)

OK_PAYLOAD = {
    'mid_circumference_cm': '125.6',
    'length_cm': '410.0',
}


def test_poprawny_pomiar_zwraca_decimale():
    out = validate_measurements(dict(OK_PAYLOAD), DEFAULT_SETTINGS)
    assert out['mid_circumference_cm'] == Decimal('125.6')
    assert out['length_cm'] == Decimal('410.0')
    assert all(isinstance(v, Decimal) for v in out.values())


def test_brak_pola():
    payload = dict(OK_PAYLOAD)
    del payload['mid_circumference_cm']
    with pytest.raises(SawmillValidationError) as exc:
        validate_measurements(payload, DEFAULT_SETTINGS)
    assert exc.value.field == 'mid_circumference_cm'


def test_obwod_ponizej_minimum():
    payload = dict(OK_PAYLOAD, mid_circumference_cm='29.9')
    with pytest.raises(SawmillValidationError) as exc:
        validate_measurements(payload, DEFAULT_SETTINGS)
    assert exc.value.field == 'mid_circumference_cm'


def test_obwod_domyslnie_bez_gornego_limitu():
    """Decyzja biznesowa: nietypowo gruba kłoda ma przejść bez interwencji."""
    assert DEFAULT_SETTINGS['max_circumference_cm'] is None
    out = validate_measurements(dict(OK_PAYLOAD, mid_circumference_cm='900.0'),
                                DEFAULT_SETTINGS)
    assert out['mid_circumference_cm'] == Decimal('900.0')


def test_obwod_powyzej_maksimum_gdy_limit_ustawiony():
    settings = dict(DEFAULT_SETTINGS, max_circumference_cm=630.0)
    payload = dict(OK_PAYLOAD, mid_circumference_cm='630.1')
    with pytest.raises(SawmillValidationError) as exc:
        validate_measurements(payload, settings)
    assert exc.value.field == 'mid_circumference_cm'


def test_dlugosc_ponizej_minimum():
    payload = dict(OK_PAYLOAD, length_cm='29.9')
    with pytest.raises(SawmillValidationError) as exc:
        validate_measurements(payload, DEFAULT_SETTINGS)
    assert exc.value.field == 'length_cm'


def test_za_duzo_miejsc_po_przecinku():
    payload = dict(OK_PAYLOAD, mid_circumference_cm='125.65')
    with pytest.raises(SawmillValidationError) as exc:
        validate_measurements(payload, DEFAULT_SETTINGS)
    assert 'miejsc' in exc.value.detail.lower()


def test_limit_null_jest_pomijany():
    """Puste pole w konfiguracji znaczy 'nie sprawdzaj', nie 'porównaj z zerem'."""
    settings = dict(DEFAULT_SETTINGS, max_length_cm=None)
    out = validate_measurements(dict(OK_PAYLOAD, length_cm='99999.0'), settings)
    assert out['length_cm'] == Decimal('99999.0')


def test_limit_null_dla_minimum_tez_pomijany():
    settings = dict(DEFAULT_SETTINGS, min_circumference_cm=None)
    out = validate_measurements(dict(OK_PAYLOAD, mid_circumference_cm='0.5'), settings)
    assert out['mid_circumference_cm'] == Decimal('0.5')


def test_wartosc_nieliczbowa():
    payload = dict(OK_PAYLOAD, length_cm='cztery metry')
    with pytest.raises(SawmillValidationError) as exc:
        validate_measurements(payload, DEFAULT_SETTINGS)
    assert exc.value.field == 'length_cm'


# ── measured_at ─────────────────────────────────────────────────────────────

NOW = datetime(2026, 8, 5, 12, 0, 0)


def test_measured_at_normalny():
    assert parse_measured_at('2026-08-05T09:31:12', now=NOW) == datetime(2026, 8, 5, 9, 31, 12)


def test_measured_at_lekko_z_przyszlosci_jest_przyjmowany():
    """Tolerancja +5 min — dryf zegara tabletu nie może kosztować pomiaru."""
    wartosc = (NOW + timedelta(minutes=3)).isoformat()
    assert parse_measured_at(wartosc, now=NOW) == NOW + timedelta(minutes=3)


def test_measured_at_mocno_z_przyszlosci_jest_przycinany():
    """Powyżej tolerancji przycinamy do now, NIE odrzucamy — 422 znaczy 'nie ponawiaj'."""
    wartosc = (NOW + timedelta(hours=6)).isoformat()
    assert parse_measured_at(wartosc, now=NOW) == NOW


def test_measured_at_starszy_niz_30_dni_odrzucony():
    wartosc = (NOW - timedelta(days=31)).isoformat()
    with pytest.raises(SawmillValidationError) as exc:
        parse_measured_at(wartosc, now=NOW)
    assert exc.value.field == 'measured_at'


def test_measured_at_29_dni_wstecz_ok():
    wartosc = (NOW - timedelta(days=29)).isoformat()
    assert parse_measured_at(wartosc, now=NOW) == NOW - timedelta(days=29)


def test_measured_at_z_offsetem_strefy_odrzucony():
    """Kontrakt mówi: naiwny ISO bez offsetu."""
    with pytest.raises(SawmillValidationError):
        parse_measured_at('2026-08-05T09:31:12+02:00', now=NOW)


def test_measured_at_brak_wartosci():
    with pytest.raises(SawmillValidationError) as exc:
        parse_measured_at(None, now=NOW)
    assert exc.value.field == 'measured_at'


def test_nan_i_infinity_daja_422_a_nie_500():
    """
    Decimal('NaN') i Decimal('Infinity') powstają BEZ wyjątku, a wybuchają
    dopiero przy porównaniu zakresu / kontroli precyzji. Na ścieżce mobilnej
    5xx nie trafia do tabeli idempotencji, więc taki rekord z kolejki offline
    byłby ponawiany bez końca.
    """
    for wartosc in ('NaN', 'Infinity', '-Infinity'):
        payload = dict(OK_PAYLOAD, mid_circumference_cm=wartosc)
        with pytest.raises(SawmillValidationError) as exc:
            validate_measurements(payload, DEFAULT_SETTINGS)
        assert exc.value.field == 'mid_circumference_cm', wartosc
