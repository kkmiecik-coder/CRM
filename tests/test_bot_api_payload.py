"""Bot API — wykrywanie brakujących pól, żeby LLM wiedział o co dopytać klienta."""
from modules.calculator.routers.bot_api import _missing_fields, _quote_level_missing


def test_brakujace_pola():
    assert _missing_fields({'length': 100}) == ['width', 'thickness', 'quantity', 'selected_variant']


def test_komplet():
    p = {'length': 100, 'width': 50, 'thickness': 3, 'quantity': 1,
         'selected_variant': 'dab-lity-ab'}
    assert _missing_fields(p) == []


# --- _quote_level_missing: client_type na poziomie całej wyceny (nie produktu) ---

def test_brak_client_type_bez_alt_field():
    """/calculate — sam klucz 'client_type'."""
    missing = _quote_level_missing({})
    assert missing == [{'product_index': None, 'field': 'client_type',
                        'hint': 'grupa cenowa (client_types z /options)'}]


def test_client_type_obecny_bez_alt_field():
    assert _quote_level_missing({'client_type': 'Bazowy'}) == []


def test_brak_client_type_z_alt_field():
    """/quotes — akceptuje 'client_type' LUB 'quote_client_type'; brak obu = brakujące."""
    missing = _quote_level_missing({}, alt_field='quote_client_type')
    assert missing == [{'product_index': None, 'field': 'client_type',
                        'hint': 'grupa cenowa (client_types z /options)'}]


def test_quote_client_type_wystarcza_jako_alt_field():
    assert _quote_level_missing({'quote_client_type': 'Bazowy'},
                                 alt_field='quote_client_type') == []


def test_client_type_wystarcza_nawet_z_alt_field():
    assert _quote_level_missing({'client_type': 'Bazowy'},
                                 alt_field='quote_client_type') == []
