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


# --- _shipping_settings: mapowanie pol wysylki na settings update_quote ---

def test_shipping_settings_mapuje_kuriera():
    from modules.calculator.routers.bot_api import _shipping_settings
    out = _shipping_settings({'courier_name': 'InPost',
                              'shipping_netto': 84.55, 'shipping_brutto': 104.0})
    assert out == {'courierName': 'InPost', 'shippingNetto': 84.55, 'shippingBrutto': 104.0}


def test_shipping_settings_puste_bez_kuriera():
    from modules.calculator.routers.bot_api import _shipping_settings
    assert _shipping_settings({'products': []}) == {}
