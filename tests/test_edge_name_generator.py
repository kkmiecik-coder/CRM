"""Testy generatora opisu krawędzi w nazwie produktu BL."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from types import SimpleNamespace
from modules.baselinker.service import BaselinkerService


def _svc():
    return BaselinkerService.__new__(BaselinkerService)  # bypass __init__


def _fd(mode, type_, r, angle, config):
    return SimpleNamespace(
        edges_mode=mode,
        edges_type=type_,
        edges_r_value=r,
        edges_angle_value=angle,
        edges_config=config,
    )


def test_basic_round():
    fd = _fd('basic', 'round', 5, None, [
        {'letter': 'A', 'type': 'round', 'r_value': 5},
        {'letter': 'B', 'type': 'round', 'r_value': 5},
    ])
    s = _svc()._translate_edges_to_description(fd)
    assert s == "zaokrąglenie R5 (A, B)"


def test_basic_chamfer_with_angle():
    fd = _fd('basic', 'chamfer', 3, 45, [
        {'letter': 'E', 'type': 'chamfer', 'r_value': 3, 'angle_value': 45},
        {'letter': 'F', 'type': 'chamfer', 'r_value': 3, 'angle_value': 45},
    ])
    s = _svc()._translate_edges_to_description(fd)
    assert s == "fazowanie R3 45° (E, F)"


def test_advanced_multi_group_sorted():
    fd = _fd('advanced', 'mixed', None, None, [
        {'letter': 'E', 'type': 'round', 'r_value': 10},
        {'letter': 'A', 'type': 'round', 'r_value': 3},
        {'letter': 'B', 'type': 'round', 'r_value': 3},
        {'letter': 'C', 'type': 'chamfer', 'r_value': 5, 'angle_value': 45},
        {'letter': 'D', 'type': 'chamfer', 'r_value': 5, 'angle_value': 45},
    ])
    s = _svc()._translate_edges_to_description(fd)
    # Sortowanie: typ asc, R asc -> chamfer R5, round R3, round R10
    assert s == "fazowanie R5 45° (C, D); zaokrąglenie R3 (A, B); zaokrąglenie R10 (E)"


def test_empty_returns_none():
    fd = _fd(None, None, None, None, None)
    assert _svc()._translate_edges_to_description(fd) is None
    fd2 = _fd('basic', 'round', 5, None, [])
    assert _svc()._translate_edges_to_description(fd2) is None


def test_legacy_no_mode_still_works():
    # Stare wyceny w DB mają edges_mode=NULL; legacy basic behavior
    fd = SimpleNamespace(
        edges_mode=None,
        edges_type='round',
        edges_r_value=5,
        edges_angle_value=None,
        edges_config=[{'letter': 'A', 'type': 'round', 'r_value': 5}],
    )
    s = _svc()._translate_edges_to_description(fd)
    assert s == "zaokrąglenie R5 (A)"
