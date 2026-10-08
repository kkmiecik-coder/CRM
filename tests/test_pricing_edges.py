"""Parytet krawędzi z edges.js (recalculateEdgesForForm) — NIE z edge_calculator.py."""
import json

import pytest

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


def test_naroznik_fazowany_z_rysunku_liczony_za_sztuke():
    edges = [{'letter': 'N1', 'type': 'chamfer', 'r_value': 20, 'angle_value': 45}]
    r = calculate_edges_pricing(edges, _product(quantity=1), PricingData(edge_prices=CENY))
    assert r['netto'] == 5.0


def test_naroznik_wyciecia_liczony_za_sztuke():
    sd = {'vertices': [[0, 0], [100, 0], [100, 50], [0, 50]],
          'cutouts': [{'id': 'a', 'type': 'polygon', 'points': [[10, 10], [30, 10], [30, 30], [10, 30]],
                       'corners': [{'type': 'round', 'r_mm': 30}, None, None, None]}]}
    edges = [{'letter': 'H1.P1', 'type': 'round', 'r_value': 30}]
    r = calculate_edges_pricing(edges, _product(shape_data=sd, quantity=1), PricingData(edge_prices=CENY))
    assert r['netto'] == 5.0


# --- Zepsute shape_data nie może wywalić wyceny (zapis wyceny i /api/bot/calculate) ---

_P = [[0, 0], [100, 0], [100, 50], [0, 50]]
_TRI = [[0, 0], [10, 0], [0, 10]]
_ZLE_SHAPE_DATA = {
    'vertices 2 punkty': {'vertices': [[0, 0], [1, 1]]},
    'vertices tekst': {'vertices': 'abcd'},
    'vertices z tekstem': {'vertices': [[0, 'a'], [1, 2], [3, 4]]},
    'vertices krotkie punkty': {'vertices': [[0], [1], [2]]},
    'vertices z null': {'vertices': [[0, 0], None, [1, 2]]},
    'cutouts dict': {'vertices': _P, 'cutouts': {'a': 1}},
    'cutouts punkty 1-el': {'vertices': _P, 'cutouts': [{'type': 'polygon', 'points': [[1], [2], [3]]}]},
    'cutouts punkty tekst': {'vertices': _P, 'cutouts': [{'type': 'polygon', 'points': 'abcd'}]},
    'cutouts punkty z null': {'vertices': _P, 'cutouts': [{'type': 'polygon', 'points': [[0, 0], [1, 1], None]}]},
    'cutouts punkty dict': {'vertices': _P, 'cutouts': [{'type': 'polygon', 'points': {'a': 1, 'b': 2, 'c': 3}}]},
    'cutouts corners tekst': {'vertices': _P, 'cutouts': [{'type': 'polygon', 'points': _TRI, 'corners': 'xyz'}]},
    'cutouts r_mm Infinity': {'vertices': _P, 'cutouts': [{'type': 'polygon', 'points': _TRI,
                                                             'corners': [{'type': 'round', 'r_mm': float('inf')}, None, None]}]},
    'elipsa tekst': {'vertices': _P, 'cutouts': [{'type': 'ellipse', 'cx': 'a', 'cy': 1, 'rx': 1, 'ry': 1}]},
    'elipsa rx 0': {'vertices': _P, 'cutouts': [{'type': 'ellipse', 'cx': 10, 'cy': 10, 'rx': 0, 'ry': 5}]},
    'elipsa ujemna': {'vertices': _P, 'cutouts': [{'type': 'ellipse', 'cx': 10, 'cy': 10, 'rx': -3, 'ry': -3}]},
    'elipsa NaN': {'vertices': _P, 'cutouts': [{'type': 'ellipse', 'cx': 10, 'cy': 10, 'rx': float('nan'), 'ry': 3}]},
    'elipsa kat tekst': {'vertices': _P, 'cutouts': [{'type': 'ellipse', 'cx': 10, 'cy': 10, 'rx': 3, 'ry': 2, 'angle': 'x'}]},
    'holes tekst': {'vertices': _P, 'holes': 'abcd'},
    'holes liczby': {'vertices': _P, 'holes': [[1, 2, 3]]},
    'holes z null': {'vertices': _P, 'holes': [None, [[0, 0], [1, 0], [0, 1]]]},
    'holes punkty tekst': {'vertices': _P, 'holes': [['ab', 'cd', 'ef']]},
    'corners tekst': {'vertices': _P, 'corners': 'abcd'},
    'params null': {'params': None, 'vertices': _P},
    'params srednica tekst': {'params': {'diameter': 'x'}, 'vertices': None},
}
_WPISY_ZEPSUTE = [{'letter': 'A', 'type': 'round', 'r_value': 5},
                  {'letter': 'G1', 'type': 'round', 'r_value': 5, 'length_cm': 10},
                  {'letter': 'H1.G1', 'type': 'round', 'r_value': 5, 'length_cm': 10},
                  {'letter': 'H1.P1', 'type': 'round', 'r_value': 5}]


@pytest.mark.parametrize('kodowanie', ['dict', 'json'])
@pytest.mark.parametrize('ksztalt', ['rectangular', 'circle', 'polygon'])
@pytest.mark.parametrize('nazwa', list(_ZLE_SHAPE_DATA))
def test_zepsute_shape_data_nie_wywala_wyceny_krawedzi(nazwa, ksztalt, kodowanie):
    sd = _ZLE_SHAPE_DATA[nazwa]
    arg = sd if kodowanie == 'dict' else json.dumps(sd)
    r = calculate_edges_pricing(_WPISY_ZEPSUTE, _product(shape=ksztalt, shape_data=arg, quantity=1),
                                PricingData(edge_prices=CENY))
    assert r['netto'] >= 0 and r['brutto'] >= 0
    # Wpis z jawną długością (G1 / H1.G1) zawsze się liczy, a litery obrysu z wymiarów produktu też
    assert {d['letter'] for d in r['details']} >= {'A', 'H1.P1'}


@pytest.mark.parametrize('nazwa, ksztalt', [
    ('vertices tekst', 'polygon'), ('vertices z null', 'polygon'), ('vertices krotkie punkty', 'rectangular'),
    ('params null', 'circle'), ('params srednica tekst', 'circle')])
def test_zepsute_shape_data_liczy_jak_bez_shape_data_i_loguje(nazwa, ksztalt, caplog):
    dane = PricingData(edge_prices=CENY)
    wzor = calculate_edges_pricing(_WPISY_ZEPSUTE, _product(shape=ksztalt, shape_data=None, quantity=1), dane)
    with caplog.at_level('WARNING'):
        r = calculate_edges_pricing(_WPISY_ZEPSUTE,
                                    _product(shape=ksztalt, shape_data=_ZLE_SHAPE_DATA[nazwa], quantity=1), dane)
    assert r == wzor
    assert any('shape_data' in rec.getMessage() for rec in caplog.records)
