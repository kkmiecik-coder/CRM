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


# === Breakdown dopłaty za kształt nietypowy (dla UI kalkulatora i bota Dębusia) ===

DATA_Z_DOPLATA = PricingData(
    price_entries=CENNIK, multipliers={'Detal+': 1.3},
    edge_prices={'round': {'per_mb': 15.0, 'per_corner': 5.0}},
    custom_shape_surcharge_netto=120.0,
)


def test_breakdown_doplaty_za_ksztalt_nietypowy():
    r = calculate_quote(_payload(shape='triangle_right'), DATA_Z_DOPLATA)
    assert r['ok'] is True
    doplata = r['products'][0]['shape_surcharge']
    assert doplata['per_unit_netto'] == 120.0
    assert doplata['total_netto'] == 240.0          # 120 × 2 szt.
    assert doplata['total_brutto'] == 295.2
    assert 'nietypowy kształt' in doplata['note']   # gotowe zdanie PL dla bota


def test_doplata_za_ksztalt_wliczona_w_sume_wyceny():
    # breakdown jest informacyjny — kwota MUSI już siedzieć w totalach
    bez = calculate_quote(_payload(shape='triangle_right'), DATA)
    z_doplata = calculate_quote(_payload(shape='triangle_right'), DATA_Z_DOPLATA)
    roznica = z_doplata['totals']['order_netto'] - bez['totals']['order_netto']
    assert abs(roznica - 240.0) < 0.001   # odejmowanie floatów, stąd tolerancja


def test_brak_breakdownu_dla_ksztaltow_standardowych():
    for shape in ('rectangular', 'round', 'circle'):
        r = calculate_quote(_payload(shape=shape), DATA_Z_DOPLATA)
        assert r['products'][0]['shape_surcharge'] is None, shape


def test_breakdown_pusty_gdy_produkt_ma_bledy_walidacji():
    # gałąź błędu też musi mieć klucz — front czyta go bezwarunkowo
    r = calculate_quote(_payload(shape='polygon', length=700), DATA_Z_DOPLATA)
    assert r['ok'] is False
    assert r['products'][0]['shape_surcharge'] is None


# === Automatyczny dobór mnożnika (wyceny bota Dębusia) ===

from modules.calculator.services.pricing_service import auto_multiplier_for_base

# cennik z dwiema cenami za m³: tania (baza < 1000) i droga (baza >= 1000)
CENNIK_PROG = [
    {'species': 'Dąb', 'technology': 'Lity', 'wood_class': 'A/B',
     'thickness_min': 3, 'thickness_max': 4, 'length_min': 20, 'length_max': 450,
     'width_min': 10, 'width_max': 120, 'price_per_m3': 8000.0},   # 0.015 m³ -> baza 120
    {'species': 'Buk', 'technology': 'Lity', 'wood_class': 'A/B',
     'thickness_min': 3, 'thickness_max': 4, 'length_min': 20, 'length_max': 450,
     'width_min': 10, 'width_max': 120, 'price_per_m3': 80000.0},  # 0.015 m³ -> baza 1200
]
DATA_PROG = PricingData(price_entries=CENNIK_PROG, multipliers={'Detal+': 1.3},
                        edge_prices={'round': {'per_mb': 15.0, 'per_corner': 5.0}})


def _payload_prog(**kw):
    p = {'index': 1, 'length': 100, 'width': 50, 'thickness': 3, 'quantity': 1,
         'shape': 'rectangular', 'holes_count': 0, 'selected_variant': 'dab-lity-ab',
         'finishing_type': 'Surowe', 'edges': []}
    p.update(kw)
    return {'client_type': 'Detal+', 'auto_multiplier': True, 'products': [p]}


def test_prog_mnoznika_na_cenie_bazowej():
    assert auto_multiplier_for_base(999.99) == 1.5
    assert auto_multiplier_for_base(1000.0) == 1.1    # rowno 1000 -> "od progu"
    assert auto_multiplier_for_base(1000.01) == 1.1
    assert auto_multiplier_for_base(0.0) == 1.5


def test_tanszy_produkt_dostaje_15_drozszy_11():
    r = calculate_quote(_payload_prog(), DATA_PROG)
    assert r['ok'] is True
    warianty = {v['variant_code']: v for v in r['products'][0]['variants'] if v.get('available')}

    tani = warianty['dab-lity-ab']       # baza 120 zl -> ponizej progu
    assert tani['base_unit_netto'] == 120.0
    assert tani['multiplier'] == 1.5
    assert abs(tani['unit_netto'] - 180.0) < 0.001

    drogi = warianty['buk-lity-ab']      # baza 1200 zl -> od progu
    assert drogi['base_unit_netto'] == 1200.0
    assert drogi['multiplier'] == 1.1
    assert abs(drogi['unit_netto'] - 1320.0) < 0.001


def test_mnoznik_dobierany_per_wariant_a_nie_per_produkt():
    # ten sam produkt, dwa warianty, DWA rozne mnozniki w jednej odpowiedzi
    r = calculate_quote(_payload_prog(), DATA_PROG)
    uzyte = {v['multiplier'] for v in r['products'][0]['variants'] if v.get('available')}
    assert uzyte == {1.5, 1.1}


def test_grupa_cenowa_nie_wplywa_na_cene_bota():
    # Detal+ (1.3) vs Hurt (1.1) — w trybie auto cena MUSI byc identyczna
    dane = PricingData(price_entries=CENNIK_PROG,
                       multipliers={'Detal+': 1.3, 'Hurt': 1.1},
                       edge_prices={'round': {'per_mb': 15.0, 'per_corner': 5.0}})
    a = calculate_quote(_payload_prog(), dane)
    p = _payload_prog()
    p['client_type'] = 'Hurt'
    b = calculate_quote(p, dane)
    assert a['totals']['order_netto'] == b['totals']['order_netto']
    assert a['multiplier'] is None and a['multiplier_mode'] == 'auto'


def test_tryb_auto_dziala_bez_grupy_cenowej():
    # mnoznik dobiera kod, wiec brak client_type nie moze blokowac wyceny
    p = _payload_prog()
    p.pop('client_type')
    r = calculate_quote(p, DATA_PROG)
    assert r['ok'] is True


def test_bez_flagi_dziala_po_staremu_grupa_cenowa():
    p = _payload_prog()
    p['auto_multiplier'] = False
    r = calculate_quote(p, DATA_PROG)
    tani = next(v for v in r['products'][0]['variants'] if v['variant_code'] == 'dab-lity-ab')
    assert tani['multiplier'] == 1.3                  # Detal+, nie 1.5
    assert r['multiplier_mode'] == 'client_type'


def test_doplaty_doliczane_po_dobranym_mnozniku():
    # dopłata za kształt nietypowy NIE wchodzi do bazy, od ktorej liczy sie prog
    dane = PricingData(price_entries=CENNIK_PROG, multipliers={'Detal+': 1.3},
                       edge_prices={'round': {'per_mb': 15.0, 'per_corner': 5.0}},
                       custom_shape_surcharge_netto=120.0)
    r = calculate_quote(_payload_prog(shape='polygon'), dane)
    tani = next(v for v in r['products'][0]['variants'] if v['variant_code'] == 'dab-lity-ab')
    assert tani['base_unit_netto'] == 120.0           # baza bez doplaty
    assert tani['multiplier'] == 1.5
    assert abs(tani['unit_netto'] - 300.0) < 0.001    # 120*1.5 + 120


def test_jawne_wylaczenie_trybu_auto_wraca_do_grupy_cenowej():
    """Sklep dzieli z botem endpoint /calculate i klucz API, wiec musi miec furtke:
    jawne auto_multiplier=false ma wrocic do liczenia wg grupy cenowej."""
    p = _payload_prog()
    p['auto_multiplier'] = False
    r = calculate_quote(p, DATA_PROG)
    tani = next(v for v in r['products'][0]['variants'] if v['variant_code'] == 'dab-lity-ab')
    assert tani['multiplier'] == 1.3
    assert r['multiplier_mode'] == 'client_type'
