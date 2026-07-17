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


# --- _products_with_all_variants: rozwija selected_variant na pelna liste wariantow ---

def test_products_with_all_variants_rozwija_i_zaznacza():
    from modules.calculator.routers.bot_api import _products_with_all_variants
    out = _products_with_all_variants({'products': [
        {'index': 1, 'length': 140, 'selected_variant': 'dab-micro-ab'}]})
    p = out[0]
    assert p['index'] == 1 and p['length'] == 140
    assert len(p['variants']) == 8                       # wszystkie warianty drewna
    selected = [v for v in p['variants'] if v['is_selected']]
    assert len(selected) == 1 and selected[0]['variant_code'] == 'dab-micro-ab'


def test_products_with_all_variants_zachowuje_istniejace_variants():
    from modules.calculator.routers.bot_api import _products_with_all_variants
    prod = {'index': 1, 'variants': [{'variant_code': 'x', 'is_selected': True}]}
    out = _products_with_all_variants({'products': [prod]})
    assert out[0]['variants'] == [{'variant_code': 'x', 'is_selected': True}]


def test_products_with_all_variants_zachowuje_product_type():
    """product_type (koncept sklepu) musi przetrwać handoff bot->serwis (POST i PUT),
    inaczej create_quote/_update_or_create_product nie zapiszą go do QuoteItemDetails."""
    from modules.calculator.routers.bot_api import _products_with_all_variants
    out = _products_with_all_variants({'products': [
        {'index': 1, 'length': 140, 'selected_variant': 'dab-micro-ab',
         'product_type': 'parapet'}]})
    assert out[0]['product_type'] == 'parapet'
