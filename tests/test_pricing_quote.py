"""Agregacja i walidacja calculate_quote — komunikaty PL pod LLM."""
from modules.calculator.services.pricing_service import PricingData, calculate_quote

CENNIK = [{'species': 'Dąb', 'technology': 'Lity', 'wood_class': 'A/B',
           'thickness_min': 3, 'thickness_max': 4, 'length_min': 20, 'length_max': 450,
           'width_min': 10, 'width_max': 120, 'price_per_m3': 8200.0}]
DATA = PricingData(price_entries=CENNIK, multipliers={'Detal+': 1.3},
                   edge_prices={'round': {'per_mb': 15.0, 'per_corner': 5.0}})


def _payload(**product_kw):
    p = {'index': 1, 'length': 100, 'width': 50, 'thickness': 3, 'quantity': 2,
         'shape': 'rectangular', 'holes_count': 0, 'selected_variant': 'dab-lity-ab',
         'finishing_type': 'Surowe', 'edges': [], 'cut_to_size': True}
    p.update(product_kw)
    return {'client_type': 'Detal+', 'products': [p]}


def test_happy_path_totals():
    r = calculate_quote(_payload(), DATA)
    assert r['ok'] is True
    assert r['totals']['order_netto'] == 319.8    # z Task 2: round(159.9*2)
    assert r['totals']['total_brutto'] == 393.36


def test_blad_wymiaru_max():
    r = calculate_quote(_payload(length=700), DATA)
    assert r['ok'] is False
    err = r['errors'][0]
    assert err['field'] == 'length'
    assert err['code'] == 'MAX_EXCEEDED'
    assert err['limit'] == 450 and err['given'] == 700
    assert '450' in err['message'] and '700' in err['message']  # komunikat PL dla LLM


def test_nieznana_grupa_cenowa():
    payload = _payload()
    payload['client_type'] = 'NieMaTakiej'
    r = calculate_quote(payload, DATA)
    assert r['ok'] is False
    assert r['errors'][0]['code'] == 'UNKNOWN_CLIENT_TYPE'


def test_brak_pol():
    payload = {'client_type': 'Detal+', 'products': [{'index': 1, 'length': 100}]}
    r = calculate_quote(payload, DATA)
    assert r['ok'] is False
    codes = {e['field'] for e in r['errors']}
    assert 'width' in codes and 'thickness' in codes


def test_wybrany_wariant_poza_zakresem_ale_inne_licza():
    # jesion nie ma wpisu w cenniku -> wybrany niedostępny, ale wynik zawiera warianty
    r = calculate_quote(_payload(selected_variant='jes-lity-ab'), DATA)
    assert r['ok'] is False
    assert r['errors'][0]['code'] == 'VARIANT_UNAVAILABLE'
    assert any(v['available'] for v in r['products'][0]['variants'])


def test_length_niepoprawny_string_daje_invalid_type_a_nie_crash():
    # Review Taska 5 (krytyczne dla bota): LLM może przysłać length jako
    # nienumeryczny string ("abc") — validate_product NIE ma crashować
    # ValueError, tylko zwrócić błąd INVALID_TYPE.
    r = calculate_quote(_payload(length='abc'), DATA)
    assert r['ok'] is False
    err = r['errors'][0]
    assert err['code'] == 'INVALID_TYPE'
    assert err['field'] == 'length'
    assert 'abc' in err['message']


def test_quantity_niepoprawny_string_daje_invalid_type():
    r = calculate_quote(_payload(quantity='dwa'), DATA)
    assert r['ok'] is False
    err = next(e for e in r['errors'] if e['field'] == 'quantity')
    assert err['code'] == 'INVALID_TYPE'
    assert 'dwa' in err['message']
