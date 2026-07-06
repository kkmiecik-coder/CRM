"""Testy parytetu liczenia materiału z JS (calculator-core.js updatePrices)."""
from modules.calculator.services.pricing_service import round_grosze


def test_round_grosze_polowki_w_gore():
    # JS Math.round zaokrągla .5 w górę — Python round() by tu dał 0.12/0.14 (bankers)
    assert round_grosze(0.125) == 0.13
    assert round_grosze(0.135) == 0.14
    assert round_grosze(1.005) == 1.01  # klasyczny float trap — EPSILON w JS to łata


def test_round_grosze_zwykle():
    assert round_grosze(123.456) == 123.46
    assert round_grosze(0.0) == 0.0
