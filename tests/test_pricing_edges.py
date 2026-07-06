"""Parytet krawędzi z edges.js (recalculateEdgesForForm) — NIE z edge_calculator.py."""
from modules.calculator.services.pricing_service import PricingData, calculate_edges_pricing

CENY = {'round': {'per_mb': 15.0, 'per_corner': 5.0},
        'chamfer': {'per_mb': 15.0, 'per_corner': 5.0},
        'sharp': {'per_mb': 0.0, 'per_corner': 0.0}}


def _product(**kw):
    base = {'length': 100, 'width': 50, 'thickness': 3, 'quantity': 2,
            'shape': 'rectangular', 'shape_data': None}
    base.update(kw)
    return base


def test_prostokat_krawedzie_i_narozniki():
    edges = [
        {'letter': 'A', 'type': 'round', 'r_value': 5},   # długość: length 100cm -> 1mb -> 15.00
        {'letter': 'C', 'type': 'round', 'r_value': 5},   # width 50cm -> 0.5mb -> 7.50
        {'letter': 'N1', 'type': 'round', 'r_value': 5},  # narożnik flat 5.00
    ]
    r = calculate_edges_pricing(edges, _product(), PricingData(edge_prices=CENY))
    # suma niezaokrąglona 27.50 * qty 2 = 55.00; brutto = 27.50*1.23*2 = 67.65
    assert r['netto'] == 55.0
    assert r['brutto'] == 67.65


def test_suma_z_niezaokraglonych():
    # per krawędź NIE zaokrąglamy przed sumą (JS 2110-2131): 3 x 33.3cm x 15/mb
    edges = [{'letter': 'C', 'type': 'round', 'r_value': 5}] * 3
    p = _product(width=33.3, quantity=1)
    r = calculate_edges_pricing(edges, p, PricingData(edge_prices=CENY))
    # 3 * 4.995 = 14.985 -> 14.99 (a nie 3*5.00=15.00)
    assert r['netto'] == 14.99


def test_nieregularny_pion_jak_naroznik():
    # kwadrat 40x40 z shape_data; P* = flat per_corner (JS 2095-2097), G*/D* per mb
    shape_data = {'vertices': [[0, 0], [40, 0], [40, 40], [0, 40]], 'params': {}}
    edges = [
        {'id': 'G1', 'type': 'round', 'r_value': 5},   # 40cm -> 6.00
        {'id': 'P1', 'type': 'round', 'r_value': 5},   # pion -> flat 5.00
    ]
    p = _product(shape='irregular', shape_data=shape_data, quantity=1)
    r = calculate_edges_pricing(edges, p, PricingData(edge_prices=CENY))
    assert r['netto'] == 11.0


def test_okragly_obwod_elipsy():
    import math
    edges = [{'letter': 'KG', 'type': 'round', 'r_value': 5}]
    p = _product(shape='circle', quantity=1)
    a, b = 50.0, 25.0  # półosie w cm
    per_cm = math.pi * (3 * (a + b) - math.sqrt((3 * a + b) * (a + 3 * b)))
    expected = round(per_cm / 100 * 15.0 * 100) / 100
    r = calculate_edges_pricing(edges, p, PricingData(edge_prices=CENY))
    assert abs(r['netto'] - expected) <= 0.01


def test_sharp_bez_kosztu():
    edges = [{'letter': 'A', 'type': 'sharp'}]
    r = calculate_edges_pricing(edges, _product(), PricingData(edge_prices=CENY))
    assert r['netto'] == 0.0
