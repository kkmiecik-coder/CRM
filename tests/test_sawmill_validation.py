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
    'butt_d1_cm': '42.0', 'butt_d2_cm': '38.0',
    'top_d1_cm': '41.0', 'top_d2_cm': '37.0',
    'length_cm': '410.0',
}


def test_poprawny_pomiar_zwraca_decimale():
    out = validate_measurements(dict(OK_PAYLOAD), DEFAULT_SETTINGS)
    assert out['butt_d1_cm'] == Decimal('42.0')
    assert out['length_cm'] == Decimal('410.0')
    assert all(isinstance(v, Decimal) for v in out.values())


def test_brak_pola():
    payload = dict(OK_PAYLOAD)
    del payload['top_d2_cm']
    with pytest.raises(SawmillValidationError) as exc:
        validate_measurements(payload, DEFAULT_SETTINGS)
    assert exc.value.field == 'top_d2_cm'


def test_srednica_ponizej_minimum():
    payload = dict(OK_PAYLOAD, butt_d1_cm='9.9')
    with pytest.raises(SawmillValidationError) as exc:
        validate_measurements(payload, DEFAULT_SETTINGS)
    assert exc.value.field == 'butt_d1_cm'


def test_srednica_powyzej_maksimum():
    payload = dict(OK_PAYLOAD, top_d1_cm='200.1')
    with pytest.raises(SawmillValidationError):
        validate_measurements(payload, DEFAULT_SETTINGS)


def test_dlugosc_ponizej_minimum():
    payload = dict(OK_PAYLOAD, length_cm='29.9')
    with pytest.raises(SawmillValidationError) as exc:
        validate_measurements(payload, DEFAULT_SETTINGS)
    assert exc.value.field == 'length_cm'


def test_za_duzo_miejsc_po_przecinku():
    payload = dict(OK_PAYLOAD, butt_d1_cm='40.25')
    with pytest.raises(SawmillValidationError) as exc:
        validate_measurements(payload, DEFAULT_SETTINGS)
    assert 'miejsc' in exc.value.detail.lower()


def test_limit_null_jest_pomijany():
    """Puste pole w konfiguracji znaczy 'nie sprawdzaj', nie 'porównaj z zerem'."""
    settings = dict(DEFAULT_SETTINGS, max_length_cm=None)
    out = validate_measurements(dict(OK_PAYLOAD, length_cm='99999.0'), settings)
    assert out['length_cm'] == Decimal('99999.0')


def test_limit_null_dla_minimum_tez_pomijany():
    settings = dict(DEFAULT_SETTINGS, min_diameter_cm=None)
    out = validate_measurements(dict(OK_PAYLOAD, butt_d1_cm='0.5'), settings)
    assert out['butt_d1_cm'] == Decimal('0.5')


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
