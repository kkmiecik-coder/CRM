"""Mapowanie payloadu save_quote -> calculate_quote i wstrzykiwanie cen backendu."""
from modules.calculator.services.quote_service import (
    _payload_to_calc_request, _inject_backend_prices,
)


def test_mapowanie_payloadu_frontu():
    frontend_product = {
        'index': 1, 'length': 100, 'width': 50, 'thickness': 3, 'quantity': 2,
        'shape': 'rectangular', 'cut_to_size': True,
        'finishing_type': 'Lakierowanie', 'finishing_variant': 'Bezbarwne',
        'finishing_gloss_level': 'Mat', 'finishing_option_id': 7,
        'edges': [{'letter': 'A', 'type': 'round', 'r_value': 5}],
        'edges_mode': 'basic',
        # ceny z frontu — mają być ZIGNOROWANE
        'finishing_netto': 999.0, 'edges_netto': 999.0,
        'variants': [{'variant_code': 'dab-lity-ab', 'is_selected': True,
                      'final_price_netto': 999.0}],
    }
    calc = _payload_to_calc_request({'quote_client_type': 'Detal+',
                                     'products': [frontend_product]})
    assert calc['client_type'] == 'Detal+'
    p = calc['products'][0]
    assert p['selected_variant'] == 'dab-lity-ab'
    assert p['finishing_option_id'] == 7
    assert 'finishing_netto' not in p  # ceny frontu nie przechodzą dalej


def test_mapowanie_payloadu_formatu_a_edycji():
    """Format A (z load_quote_for_edit / edycji): finishing dict {type,variant,color,gloss},
    edges dict {config,type,mode}. Ceny (priceNetto/netto) mają być ZIGNOROWANE."""
    frontend_product = {
        'index': 1, 'length': 100, 'width': 50, 'thickness': 3, 'quantity': 2,
        'shape': 'rectangular', 'cut_to_size': True,
        'finishing': {
            'type': 'Lakierowanie', 'variant': 'Bezbarwne',
            'color': None, 'gloss': 'Mat',
            'priceNetto': 999.0, 'priceBrutto': 999.0,
        },
        'edges': {
            'config': [{'letter': 'A', 'type': 'round', 'r_value': 5}],
            'type': 'round', 'mode': 'basic',
            'netto': 999.0, 'brutto': 999.0,
        },
        'variants': [{'variant_code': 'dab-lity-ab', 'is_selected': True,
                      'unit_price_netto': 999.0}],
    }
    calc = _payload_to_calc_request({'quote_client_type': 'Detal+',
                                     'products': [frontend_product]})
    p = calc['products'][0]
    assert p['selected_variant'] == 'dab-lity-ab'
    assert p['finishing_type'] == 'Lakierowanie'
    assert p['finishing_variant'] == 'Bezbarwne'
    assert p['finishing_gloss_level'] == 'Mat'
    assert p['edges'] == [{'letter': 'A', 'type': 'round', 'r_value': 5}]
    assert p['edges_mode'] == 'basic'
    assert 'finishing_netto' not in p
    assert 'priceNetto' not in p


def test_mapowanie_formatu_edycji():
    """Test z brief Taska 11 (Step 2) - mapowanie produktu w formacie edycji."""
    product = {'index': 1, 'length': 100, 'width': 50, 'thickness': 3, 'quantity': 1,
               'finishing': {'type': 'Olejowanie', 'variant': None, 'gloss': None},
               'edges': {'config': [{'letter': 'A', 'type': 'round'}], 'mode': 'basic'},
               'variants': [{'variant_code': 'dab-lity-ab', 'is_selected': True}]}
    calc = _payload_to_calc_request({'quote_client_type': 'Detal+', 'products': [product]})
    p = calc['products'][0]
    assert p['finishing_type'] == 'Olejowanie'
    assert p['edges'] == [{'letter': 'A', 'type': 'round'}]
    assert p['edges_mode'] == 'basic'


def test_mapowanie_ustawien_zagniezdzonych_w_settings_edycja():
    """update_quote (edycja) wysyła client_type/multiplier/shipping zagnieżdżone
    w 'settings' (patrz save_quote.js payload.settings.{clientType, multiplier,
    shippingNetto, shippingBrutto}) - BEZ płaskich kluczy quote_client_type/
    quote_multiplier/shipping_cost_netto/shipping_cost_brutto na górnym poziomie.
    _payload_to_calc_request musi czytać z 'settings' gdy jest obecne,
    inaczej client_type wychodzi None i calculate_quote zwraca błąd MISSING."""
    payload = {
        'products': [{
            'index': 1, 'length': 100, 'width': 50, 'thickness': 3, 'quantity': 1,
            'finishing': {'type': 'Olejowanie'},
            'edges': {'config': None},
            'variants': [{'variant_code': 'dab-lity-ab', 'is_selected': True}],
        }],
        'settings': {
            'clientType': 'Detal+',
            'multiplier': 1.5,
            'shippingNetto': 20.0,
            'shippingBrutto': 24.6,
        },
    }
    calc = _payload_to_calc_request(payload)
    assert calc['client_type'] == 'Detal+'
    assert calc['shipping'] == {'netto': 20.0, 'brutto': 24.6}
    # is_partner_fixed nie jest wysyłany w edycji -> multiplier ma być
    # rozstrzygnięty przez resolve_multiplier na podstawie client_type,
    # NIE nadpisany na sztywno przez 'settings.multiplier'.
    assert calc['multiplier'] is None


def test_inject_backend_prices_nadpisuje_zawyzone_ceny_frontu():
    """_inject_backend_prices: payload z zawyżonymi cenami frontu ma zostać
    nadpisany wynikami calculate_quote (ceny/volume/price_per_m3/multiplier)."""
    products = [{
        'index': 1,
        'finishing_netto': 999.0, 'finishing_brutto': 999.0,
        'edges_netto': 999.0, 'edges_brutto': 999.0,
        'variants': [
            {'variant_code': 'dab-lity-ab', 'final_price_netto': 999.0,
             'final_price_brutto': 999.0, 'volume_m3': 999.0,
             'price_per_m3': 999.0, 'multiplier': 999.0},
        ],
    }]
    calc = {
        'ok': True, 'errors': [],
        'multiplier': 1.3,
        'products': [{
            'index': 1,
            'finishing': {'netto': 10.0, 'brutto': 12.3},
            'edges': {'netto': 5.0, 'brutto': 6.15},
            'variants': [
                {'variant_code': 'dab-lity-ab', 'available': True,
                 'total_netto': 319.8, 'total_brutto': 393.36,
                 'volume_m3': 0.15, 'price_per_m3': 8200.0, 'multiplier': 1.3},
            ],
        }],
        'totals': {'total_brutto': 411.81},
    }

    _inject_backend_prices(products, calc)

    product = products[0]
    assert product['finishing_netto'] == 10.0
    assert product['finishing_brutto'] == 12.3
    assert product['edges_netto'] == 5.0
    assert product['edges_brutto'] == 6.15

    variant = product['variants'][0]
    assert variant['final_price_netto'] == 319.8
    assert variant['final_price_brutto'] == 393.36
    assert variant['volume_m3'] == 0.15
    assert variant['price_per_m3'] == 8200.0
    assert variant['multiplier'] == 1.3
