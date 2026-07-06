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


# =============================================================================
# Tryb ADVANCED (edges.js applyEdges:1546-1577) — per-edge rounding, brutto
# liczone z RAW, suma ZAOKRĄGLONYCH wartości. Różni się od trybu basic (powyżej),
# który sumuje wartości NIEzaokrąglone i zaokrągla raz na końcu.
# =============================================================================


def test_advanced_mieszane_typy_krawedzi():
    # A round: length 100cm -> raw 15.0 -> netto_i=15.00, brutto_i=round2(15.0*1.23)=18.45
    # C chamfer: width 33.3cm -> raw 4.995 -> netto_i=round2(4.995)=5.00,
    #            brutto_i=round2(4.995*1.23)=round2(6.14385)=6.14 (z RAW, nie z 5.00!)
    # N1 chamfer: narożnik -> raw=per_corner=5.0 -> netto_i=5.00, brutto_i=round2(5.0*1.23)=6.15
    # suma zaokraglonych: netto 15.00+5.00+5.00=25.00; brutto 18.45+6.14+6.15=30.74
    # qty=2 -> total_netto=round2(25.00*2)=50.0; total_brutto=round2(30.74*2)=61.48
    edges = [
        {'letter': 'A', 'type': 'round', 'r_value': 5},
        {'letter': 'C', 'type': 'chamfer', 'angle_value': 45},
        {'letter': 'N1', 'type': 'chamfer', 'angle_value': 45},
    ]
    p = _product(width=33.3, quantity=2, edges_mode='advanced')
    r = calculate_edges_pricing(edges, p, PricingData(edge_prices=CENY))
    assert r['netto'] == 50.0
    assert r['brutto'] == 61.48


def test_basic_vs_advanced_roznica_zaokraglen():
    # 3x krawędź C (33.3cm, per_mb=15.0): raw per krawędź = 4.995
    edges = [{'letter': 'C', 'type': 'round', 'r_value': 5}] * 3
    p_basic = _product(width=33.3, quantity=1)
    p_advanced = _product(width=33.3, quantity=1, edges_mode='advanced')

    r_basic = calculate_edges_pricing(edges, p_basic, PricingData(edge_prices=CENY))
    r_advanced = calculate_edges_pricing(edges, p_advanced, PricingData(edge_prices=CENY))

    # basic: round2(3*4.995) = round2(14.985) = 14.99
    assert r_basic['netto'] == 14.99
    # advanced: 3*round2(4.995) = 3*5.00 = 15.00
    assert r_advanced['netto'] == 15.00


def test_brak_wymiaru_zwraca_zero():
    edges = [{'letter': 'A', 'type': 'round', 'r_value': 5}]
    p = _product(width=None)
    r = calculate_edges_pricing(edges, p, PricingData(edge_prices=CENY))
    assert r['netto'] == 0.0
    assert r['brutto'] == 0.0
    assert r['details'] == []
