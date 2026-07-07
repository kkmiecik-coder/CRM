# -*- coding: utf-8 -*-
# Testy walidacji kodu pocztowego odbiorcy w API wysylki bota.
from modules.calculator.routers.bot_api import _valid_receiver_postcode


def test_valid_receiver_postcode_poprawne():
    assert _valid_receiver_postcode("36-068") is True
    assert _valid_receiver_postcode(" 35-068 ") is True   # spacje ucinane


def test_valid_receiver_postcode_bledne():
    assert _valid_receiver_postcode("Kraków") is False
    assert _valid_receiver_postcode("36068") is False
    assert _valid_receiver_postcode("360-68") is False
    assert _valid_receiver_postcode("") is False
    assert _valid_receiver_postcode(None) is False
