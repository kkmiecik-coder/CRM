"""Bot API — wykrywanie brakujących pól, żeby LLM wiedział o co dopytać klienta."""
from modules.calculator.routers.bot_api import _missing_fields, _quote_level_missing


def test_brakujace_pola():
    assert _missing_fields({'length': 100}) == ['width', 'thickness', 'quantity', 'selected_variant']


def test_komplet():
    p = {'length': 100, 'width': 50, 'thickness': 3, 'quantity': 1,
         'selected_variant': 'dab-lity-ab'}
    assert _missing_fields(p) == []


# --- _quote_level_missing: client_type na poziomie całej wyceny (nie produktu) ---
#
# Wymagany DOKŁADNIE wtedy, gdy wpływa na cenę, czyli tylko przy auto_multiplier=False.
# W trybie automatycznym (domyślnym) mnożnik dobiera kod per wariant i grupa cenowa
# nie ma na cenę wpływu — żądanie jej od sklepu było proszeniem o wartość do kosza.

_BRAK_CLIENT_TYPE = {'product_index': None, 'field': 'client_type',
                     'hint': 'grupa cenowa (client_types z /options)'}


def test_brak_client_type_w_trybie_auto_nie_jest_brakiem():
    """Tryb domyślny: cena nie zależy od grupy cenowej, więc nie ma o co dopytywać."""
    assert _quote_level_missing({}, auto_multiplier=True) == []


def test_brak_client_type_z_alt_field_w_trybie_auto_nie_jest_brakiem():
    assert _quote_level_missing({}, alt_field='quote_client_type',
                                auto_multiplier=True) == []


def test_brak_client_type_przy_recznym_mnozniku():
    """auto_multiplier=False — mnożnik bierze się z grupy cenowej, więc bez niej
    nie ma z czego policzyć ceny. Tu wymóg zostaje."""
    assert _quote_level_missing({}, auto_multiplier=False) == [_BRAK_CLIENT_TYPE]


def test_client_type_obecny_bez_alt_field():
    assert _quote_level_missing({'client_type': 'Bazowy'}, auto_multiplier=False) == []


def test_brak_client_type_z_alt_field():
    """/quotes — akceptuje 'client_type' LUB 'quote_client_type'; brak obu = brakujące."""
    assert _quote_level_missing({}, alt_field='quote_client_type',
                                auto_multiplier=False) == [_BRAK_CLIENT_TYPE]


def test_quote_client_type_wystarcza_jako_alt_field():
    assert _quote_level_missing({'quote_client_type': 'Bazowy'},
                                 alt_field='quote_client_type',
                                 auto_multiplier=False) == []


def test_client_type_wystarcza_nawet_z_alt_field():
    assert _quote_level_missing({'client_type': 'Bazowy'},
                                 alt_field='quote_client_type',
                                 auto_multiplier=False) == []


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
