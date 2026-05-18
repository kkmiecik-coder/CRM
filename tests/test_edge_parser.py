"""Testy parsera obróbki krawędzi (modules.production.services.parser_service)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.production.services.parser_service import ProductNameParser


def _parser():
    return ProductNameParser()


def test_legacy_single_group_round():
    r = _parser()._parse_edge_processing("Klejonka jesion 100x50x3 zaokrąglenie R5 (A, B)")
    assert r['has_edge'] is True
    assert r['edge_type'] == 'zaokrąglenie'
    assert r['edge_radius'] == 5
    assert r['edge_angle'] is None
    assert r['edge_letters'] == ['A', 'B']
    assert r['edges_groups'] == [
        {'type': 'zaokrąglenie', 'radius': 5, 'angle': None, 'letters': ['A', 'B']}
    ]


def test_legacy_single_group_chamfer_with_angle():
    r = _parser()._parse_edge_processing("Klejonka dąb fazowanie R3 45° E, F, G, H")
    assert r['has_edge'] is True
    assert r['edge_type'] == 'fazowanie'
    assert r['edge_radius'] == 3
    assert r['edge_angle'] == 45
    assert r['edge_letters'] == ['E', 'F', 'G', 'H']
    assert len(r['edges_groups']) == 1
    assert r['edges_groups'][0]['letters'] == ['E', 'F', 'G', 'H']


def test_advanced_multi_group():
    name = "Klejonka jesion zaokrąglenie R3 (A, B); fazowanie R5 45° (C, D); zaokrąglenie R10 (E)"
    r = _parser()._parse_edge_processing(name)
    assert r['has_edge'] is True
    assert r['edge_type'] == 'mixed'
    assert r['edge_radius'] is None
    assert r['edge_angle'] is None
    # legacy 'edge_letters' = union wszystkich liter ze wszystkich grup (kolejność: A,B,C,D,E)
    assert sorted(r['edge_letters']) == ['A', 'B', 'C', 'D', 'E']
    assert r['edges_groups'] == [
        {'type': 'zaokrąglenie', 'radius': 3, 'angle': None, 'letters': ['A', 'B']},
        {'type': 'fazowanie',    'radius': 5, 'angle': 45,   'letters': ['C', 'D']},
        {'type': 'zaokrąglenie', 'radius': 10, 'angle': None, 'letters': ['E']},
    ]


def test_no_edge():
    r = _parser()._parse_edge_processing("Klejonka dąb 100x50x3")
    assert r['has_edge'] is False
    assert r['edges_groups'] == []
    assert r['edge_type'] is None


def test_keyword_fallback_no_pattern_match():
    r = _parser()._parse_edge_processing("Klejonka dąb z fazowaniem (do uzgodnienia)")
    assert r['has_edge'] is True
    assert r['edges_groups'] == []  # brak strukturalnych grup


def test_dynamic_edges_G_D_P():
    r = _parser()._parse_edge_processing("Klejonka kształt zaokrąglenie R3 (G1, G2, D1, D2, P1)")
    assert r['has_edge'] is True
    assert r['edges_groups'] == [
        {'type': 'zaokrąglenie', 'radius': 3, 'angle': None,
         'letters': ['G1', 'G2', 'D1', 'D2', 'P1']}
    ]
