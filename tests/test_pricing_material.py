"""Testy parytetu liczenia materiału z JS (calculator-core.js updatePrices)."""
from modules.calculator.services.pricing_service import (
    round_grosze, PricingData, calculate_material_variants,
)


def test_round_grosze_polowki_w_gore():
    # JS Math.round zaokrągla .5 w górę — Python round() by tu dał 0.12/0.14 (bankers)
    assert round_grosze(0.125) == 0.13
    assert round_grosze(0.135) == 0.14
    assert round_grosze(1.005) == 1.01  # klasyczny float trap — EPSILON w JS to łata


def test_round_grosze_zwykle():
    assert round_grosze(123.456) == 123.46
    assert round_grosze(0.0) == 0.0


CENNIK = [
    # jak Price.to_dict()
    {'species': 'Dąb', 'technology': 'Lity', 'wood_class': 'A/B',
     'thickness_min': 3, 'thickness_max': 4, 'length_min': 20, 'length_max': 450,
     'width_min': 10, 'width_max': 120, 'price_per_m3': 8200.0},
    {'species': 'Dąb', 'technology': 'Mikrowczep', 'wood_class': 'A/B',
     'thickness_min': 3, 'thickness_max': 4, 'length_min': 20, 'length_max': 450,
     'width_min': 10, 'width_max': 120, 'price_per_m3': 7100.0},
]


def _data(**kw):
    return PricingData(price_entries=CENNIK, **kw)


def test_material_prostokat_podstawowy():
    # JS: volume = 1.0*0.5*ceil(3)/100 = 0.015; unit = 0.015*8200*1.3 = 159.9
    product = {'length': 100, 'width': 50, 'thickness': 3, 'quantity': 2,
               'shape': 'rectangular', 'holes_count': 0}
    variants = calculate_material_variants(product, 1.3, _data())
    v = next(x for x in variants if x['variant_code'] == 'dab-lity-ab')
    assert v['available'] is True
    assert v['volume_m3'] == 0.015
    assert abs(v['unit_netto'] - 159.9) < 0.001       # niezaokrąglone
    assert v['unit_brutto'] == 196.68                  # round(159.9*1.23)
    assert v['total_netto'] == 319.8                   # round(159.9*2)
    assert v['total_brutto'] == 393.36                 # round(196.68*2)


def test_material_grubosc_ceil():
    # grubość 3.2 -> ceil 4: do dopasowania cennika ORAZ objętości (JS linie 286-298, 498)
    product = {'length': 100, 'width': 50, 'thickness': 3.2, 'quantity': 1,
               'shape': 'rectangular', 'holes_count': 0}
    v = calculate_material_variants(product, 1.0, _data())[0]
    assert v['volume_m3'] == 0.02  # 1.0*0.5*0.04


def test_material_doplaty_po_mnozniku():
    # dopłata za okrągły i wycięcia dodawane PO mnożniku, per sztuka (JS 546-556)
    product = {'length': 100, 'width': 50, 'thickness': 3, 'quantity': 1,
               'shape': 'circle', 'holes_count': 2}
    data = _data(round_surcharge_netto=50.0, cutout_price_netto=81.30)
    v = next(x for x in calculate_material_variants(product, 2.0, data)
             if x['variant_code'] == 'dab-lity-ab')
    # 0.015*8200*2.0 = 246.0 + 50 + 2*81.30 = 458.6
    assert abs(v['unit_netto'] - 458.6) < 0.001


def test_material_poza_zakresem():
    product = {'length': 700, 'width': 50, 'thickness': 3, 'quantity': 1,
               'shape': 'rectangular', 'holes_count': 0}
    variants = calculate_material_variants(product, 1.0, _data())
    assert all(v['available'] is False for v in variants)
