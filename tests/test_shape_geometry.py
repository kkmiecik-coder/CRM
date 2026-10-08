# -*- coding: utf-8 -*-
"""Geometria narożników (frezowanie = łuk, fazowanie = ścięcie) i wycięć po stronie serwera.

Przypadki z tests/fixtures/narozniki_przypadki.json sprawdza też JS (zadanie 2 planu),
więc obie strony liczą to samo.
"""
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from modules.calculator.services import shape_geometry as sg

KORZEN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PRZYPADKI = os.path.join(KORZEN, 'tests', 'fixtures', 'narozniki_przypadki.json')
PROSTOKAT = [[0, 0], [100, 0], [100, 50], [0, 50]]


def _przypadki():
    with open(PRZYPADKI, encoding='utf-8') as plik:
        return json.load(plik)


@pytest.mark.parametrize('p', _przypadki()['narozniki'], ids=lambda p: p['nazwa'])
def test_pole_i_liczba_segmentow_obrysu(p):
    assert sg.contour_area(p['ring'], p['corners']) == pytest.approx(p['pole'], abs=1e-3)
    assert len(sg.contour_segments(p['ring'], p['corners'])) == p['liczba_segmentow']


@pytest.mark.parametrize('p', _przypadki()['limity'], ids=lambda p: p['nazwa'])
def test_limit_naroznika(p):
    assert sg.max_corner_mm(p['ring'], p['corners'], p['index'], p['type']) == p['max_mm']


@pytest.mark.parametrize('p', _przypadki()['jednolity'], ids=lambda p: p['nazwa'])
def test_limit_jednakowy_dla_wszystkich_rogow(p):
    assert sg.max_uniform_mm(p['ring'], p['type']) == p['max_mm']


@pytest.mark.parametrize('p', _przypadki()['elipsy'], ids=lambda p: p['nazwa'])
def test_elipsa_obwod_i_pole(p):
    c = p['cutout']
    assert sg.ellipse_perimeter_cm(c['rx'], c['ry']) == pytest.approx(p['obwod'], abs=1e-4)
    assert sg.cutout_area(c) == pytest.approx(p['pole'], abs=1e-4)


@pytest.mark.parametrize('p', _przypadki()['zaokraglenie'], ids=lambda p: p['nazwa'])
def test_zaokraglenie_polowek_jak_w_js(p):
    assert sg.normalize_corners(p['corners'], p['n']) == p['oczekiwane']


@pytest.mark.parametrize('p', _przypadki()['przyciecie'], ids=lambda p: p['nazwa'])
def test_przyciecie_przypiete(p):
    assert sg.clamp_corners(p['ring'], p['corners']) == p['oczekiwane']


def test_fazowanie_tnie_symetrycznie_wzdluz_bokow():
    g = sg.corner_geometry([0, 50], [0, 0], [100, 0], {'type': 'chamfer', 'r_mm': 20})
    assert g['t1'] == pytest.approx((0, 2))
    assert g['t2'] == pytest.approx((2, 0))
    assert 'center' not in g


def test_luk_ma_srodek_na_dwusiecznej_i_skreca_w_lewo():
    g = sg.corner_geometry([0, 0], [100, 0], [100, 50], {'type': 'round', 'r_mm': 50})
    assert g['center'] == pytest.approx((95, 5))
    assert g['radius'] == pytest.approx(5)
    assert g['ccw'] is True
    luk = [s for s in sg.contour_segments(PROSTOKAT, [None, {'type': 'round', 'r_mm': 50}, None, None])
           if s['type'] == 'arc'][0]
    assert sg.arc_bulge(luk) == pytest.approx(0.41421356, abs=1e-8)


def test_wklesly_naroznik_ma_ujemne_wybrzuszenie():
    ring = [[0, 0], [100, 0], [100, 40], [40, 40], [40, 80], [0, 80]]
    corners = [None, None, None, {'type': 'round', 'r_mm': 50}, None, None]
    luk = [s for s in sg.contour_segments(ring, corners) if s['type'] == 'arc'][0]
    assert luk['ccw'] is False
    assert sg.arc_bulge(luk) < 0


def test_prawie_prosty_kat_nie_dostaje_naroznika():
    ring = [[0, 0], [50, 0.5], [100, 0], [100, 50], [0, 50]]
    assert sg.corner_geometry(ring[0], ring[1], ring[2], {'type': 'round', 'r_mm': 10}) is None
    assert sg.max_corner_mm(ring, [None] * 5, 1, 'round') == 0


def test_przyciecie_narozników_miesci_sie_w_bokach():
    duze = [{'type': 'round', 'r_mm': 300}] * 4
    wynik = sg.clamp_corners(PROSTOKAT, duze)
    n = len(PROSTOKAT)
    for i in range(n):
        j = (i + 1) % n
        bok = math.hypot(PROSTOKAT[j][0] - PROSTOKAT[i][0], PROSTOKAT[j][1] - PROSTOKAT[i][1])
        gi = sg.corner_geometry(PROSTOKAT[i - 1], PROSTOKAT[i], PROSTOKAT[(i + 1) % n], wynik[i])
        gj = sg.corner_geometry(PROSTOKAT[j - 1], PROSTOKAT[j], PROSTOKAT[(j + 1) % n], wynik[j])
        zuzyte = (gi['extent'] if gi else 0) + (gj['extent'] if gj else 0)
        assert zuzyte <= bok + 1e-9


def test_normalizacja_odrzuca_bledne_narozniki():
    surowe = [{'type': 'x', 'r_mm': 5}, {'type': 'round', 'r_mm': 0}, None, {'type': 'chamfer', 'r_mm': 12.4}]
    assert sg.normalize_corners(surowe, 4) == [None, None, None, {'type': 'chamfer', 'r_mm': 12}]
    assert sg.normalize_corners(None, 3) == [None, None, None]


def test_stare_dane_wyciecia_z_holes():
    wynik = sg.cutouts_from_shape_data({'holes': [[[1, 1], [5, 1], [5, 5]]]})
    assert len(wynik) == 1
    assert wynik[0]['type'] == 'polygon'
    assert wynik[0]['corners'] == [None, None, None]


def test_cutouts_maja_pierwszenstwo_przed_holes():
    sd = {'cutouts': [{'id': 'a', 'type': 'ellipse', 'cx': 10, 'cy': 10, 'rx': 3, 'ry': 3, 'angle': 0}],
          'holes': [[[0, 0], [1, 0], [1, 1]]] * 3}
    wynik = sg.cutouts_from_shape_data(sd)
    assert [c['type'] for c in wynik] == ['ellipse']


def test_splaszczenie_luku_co_5_stopni():
    corners = [{'type': 'round', 'r_mm': 50}, None, None, None]
    punkty = sg.flatten_segments(sg.contour_segments(PROSTOKAT, corners))
    # 4 odcinki (po punkcie startowym) + łuk 90° co 5° = 18 punktów
    assert len(punkty) == 22


# --- Walidacja wycięć jak w JS (ShapeCutouts.normalize): numeracja H{n} musi się zgadzać ---

def _elipsa(**kw):
    dane = {'id': 'a', 'type': 'ellipse', 'cx': 10, 'cy': 10, 'rx': 3, 'ry': 2, 'angle': 0}
    dane.update(kw)
    return dane


@pytest.mark.parametrize('zla', [
    {'rx': 0}, {'ry': 0}, {'rx': -3, 'ry': -3}, {'rx': float('nan')}, {'ry': float('nan')},
    {'rx': float('inf')}, {'ry': float('inf')}, {'cx': float('nan')}, {'cy': float('inf')},
    {'rx': 'abc'}, {'cx': None}], ids=str)
def test_elipsa_o_zlych_wymiarach_jest_pomijana(zla):
    # JS odrzuca takie elipsy (nie ma ich w `cutouts`), więc kolejne wycięcie dostaje ten sam numer H{n}
    drugie = _elipsa(id='b', rx=4, ry=4)
    wynik = sg.cutouts_from_shape_data({'cutouts': [_elipsa(**zla), drugie]})
    assert [(c['rx'], c['ry']) for c in wynik] == [(4.0, 4.0)]


def test_zepsute_wycięcia_i_holes_nie_rzucaja_wyjatku():
    smieci = {'cutouts': [
        {'type': 'polygon', 'points': [[1], [2], [3]]},
        {'type': 'polygon', 'points': 'abcd'},
        {'type': 'polygon', 'points': [[0, 0], [1, 1], None]},
        {'type': 'polygon', 'points': {'a': 1, 'b': 2, 'c': 3}},
        {'type': 'polygon', 'points': [[0, 0], [float('nan'), 1], [1, 1]]},
        {'type': 'polygon', 'points': [[0, 0], [4, 0], [4, 4]], 'corners': 'xyz'},
        'tekst', None, 5]}
    wynik = sg.cutouts_from_shape_data(smieci)
    assert len(wynik) == 1 and wynik[0]['corners'] == [None, None, None]
    for holes in ('abcd', [[1, 2, 3]], [None, [[0, 0], [1, 0], [0, 1]]], [['ab', 'cd', 'ef']]):
        assert len(sg.cutouts_from_shape_data({'holes': holes})) <= 1


def test_normalizacja_naroznikow_odrzuca_nieskonczonosc_i_bool():
    surowe = [{'type': 'round', 'r_mm': float('inf')}, {'type': 'round', 'r_mm': float('nan')},
              {'type': 'round', 'r_mm': True}, {'type': 'chamfer', 'r_mm': 3}]
    assert sg.normalize_corners(surowe, 4) == [None, None, None, {'type': 'chamfer', 'r_mm': 3}]


# --- Narożniki ze starych wpisów krawędzi (jak pullCornersFromEdges w JS) ---

def _wpis(litera, typ='round', r=20):
    return {'letter': litera, 'type': typ, 'r_value': r}


def test_narozniki_prostokata_z_krawedzi_mapuja_N1_N2_N4_N3_na_v0_v1_v2_v3():
    wpisy = [_wpis('N1', r=10), _wpis('N2', r=20), _wpis('N3', 'chamfer', 30), _wpis('N4', r=40)]
    obrys, wyciecia = sg.corners_from_edges('rectangular', wpisy, 4, {})
    assert obrys == [{'type': 'round', 'r_mm': 10}, {'type': 'round', 'r_mm': 20},
                     {'type': 'round', 'r_mm': 40}, {'type': 'chamfer', 'r_mm': 30}]
    assert wyciecia == {}


def test_narozniki_wieloboku_z_liter_P():
    wpisy = [_wpis('P1', r=5), _wpis('P3', 'chamfer', 8)]
    obrys, _ = sg.corners_from_edges('polygon', wpisy, 3, {})
    assert obrys == [{'type': 'round', 'r_mm': 5}, None, {'type': 'chamfer', 'r_mm': 8}]


def test_narozniki_wyciecia_z_liter_H_P():
    wpisy = [_wpis('H2.P3', r=7), _wpis('H1.P1', 'chamfer', 6)]
    obrys, wyciecia = sg.corners_from_edges('rectangular', wpisy, 4, {0: 4, 1: 3})
    assert obrys == [None] * 4
    assert wyciecia == {0: [{'type': 'chamfer', 'r_mm': 6}, None, None, None],
                        1: [None, None, {'type': 'round', 'r_mm': 7}]}


@pytest.mark.parametrize('litera', ['P0', 'P7', 'N5', 'H3.P1', 'H0.P1', 'H1.P0', 'H1.P9', 'A', 'G1', 'H1.G1', 'KG', ''])
def test_litery_spoza_zakresu_sa_ignorowane(litera):
    # pięciokąt i dwa wycięcia (trójkąt, czworokąt); P7 / H3 / H1.P9 nie wskazują żadnego narożnika
    obrys, wyciecia = sg.corners_from_edges('polygon', [_wpis(litera)], 5, {0: 3, 1: 4})
    assert obrys == [None] * 5
    assert wyciecia == {0: [None] * 3, 1: [None] * 4}


def test_litery_P_nie_dzialaja_na_prostokacie_a_N_na_wieloboku():
    assert sg.corners_from_edges('rectangular', [_wpis('P1')], 4, {})[0] == [None] * 4
    assert sg.corners_from_edges('polygon', [_wpis('N1')], 4, {})[0] == [None] * 4


@pytest.mark.parametrize('wpis', [
    {'letter': 'N1', 'type': 'sharp', 'r_value': 20},
    {'letter': 'N1', 'type': 'round', 'r_value': 0},
    {'letter': 'N1', 'type': 'round', 'r_value': 0.4},
    {'letter': 'N1', 'type': 'round', 'r_value': None},
    {'letter': 'N1', 'type': 'round', 'r_value': 'abc'},
    {'letter': 'N1', 'type': 'round', 'r_value': float('inf')},
    {'letter': 'N1', 'type': 'bevel', 'r_value': 5},
    'tekst', None, 7])
def test_nieprawidlowe_wpisy_krawedzi_nie_daja_naroznika(wpis):
    assert sg.corners_from_edges('rectangular', [wpis], 4, {})[0] == [None] * 4


def test_wpisy_krawedzi_jako_json_i_litera_z_pola_id():
    tekst = json.dumps([{'id': 'n2', 'type': 'round', 'r_value': 12.5}])
    obrys, _ = sg.corners_from_edges('rectangular', tekst, 4, {})
    assert obrys == [None, {'type': 'round', 'r_mm': 13}, None, None]
    assert sg.corners_from_edges('rectangular', '{zepsuty', 4, {}) == ([None] * 4, {})
    assert sg.corners_from_edges('rectangular', None, 4, {}) == ([None] * 4, {})
    assert sg.corners_from_edges('circle', [_wpis('N1')], 0, {}) == (None, {})


# --- Narożniki gotowe do rysowania: shape_data wygrywa, stare wyceny dostają je z krawędzi, wszystko przycięte ---

def test_stara_wycena_dostaje_narozniki_z_krawedzi():
    sd = {'vertices': PROSTOKAT}
    obrys, wyciecia = sg.resolve_corners('rectangular', PROSTOKAT, sd, [_wpis('N1', r=20), _wpis('N3', r=20)])
    assert obrys == [{'type': 'round', 'r_mm': 20}, None, None, {'type': 'round', 'r_mm': 20}]
    assert wyciecia == []


def test_narozniki_z_shape_data_wygrywaja_z_krawedziami():
    sd = {'vertices': PROSTOKAT, 'corners': [None, {'type': 'chamfer', 'r_mm': 15}, None, None]}
    obrys, _ = sg.resolve_corners('rectangular', PROSTOKAT, sd, [_wpis('N1', r=20)])
    assert obrys == [None, {'type': 'chamfer', 'r_mm': 15}, None, None]


def test_narozniki_wyciecia_z_shape_data_tez_wygrywaja_z_krawedziami():
    # Wystarczy jeden narożnik wycięcia w shape_data — wtedy krawędzi nie czytamy w ogóle
    sd = {'vertices': PROSTOKAT, 'cutouts': [
        {'id': 'a', 'type': 'polygon', 'points': [[10, 10], [30, 10], [30, 30]],
         'corners': [{'type': 'round', 'r_mm': 20}, None, None]}]}
    obrys, wyciecia = sg.resolve_corners('rectangular', PROSTOKAT, sd, [_wpis('N1', r=20)])
    assert obrys == [None] * 4
    assert wyciecia[0]['corners'] == [{'type': 'round', 'r_mm': 20}, None, None]


def test_narozniki_wyciec_ze_starych_wpisow():
    sd = {'vertices': PROSTOKAT, 'cutouts': [
        {'id': 'a', 'type': 'ellipse', 'cx': 20, 'cy': 20, 'rx': 5, 'ry': 5, 'angle': 0},
        {'id': 'b', 'type': 'polygon', 'points': [[50, 10], [80, 10], [80, 40], [50, 40]]}]}
    # Elipsa jest wycięciem nr 1, wielokąt nr 2 — H2.P3 to jego trzeci wierzchołek
    _, wyciecia = sg.resolve_corners('rectangular', PROSTOKAT, sd, [_wpis('H2.P3', r=30), _wpis('H1.P1', r=5)])
    assert wyciecia[0]['type'] == 'ellipse'
    assert wyciecia[1]['corners'] == [None, None, {'type': 'round', 'r_mm': 30}, None]


def test_kolo_bierze_z_krawedzi_tylko_narozniki_wyciec():
    sd = {'params': {'diameter': 60}, 'vertices': None, 'cutouts': [
        {'id': 'b', 'type': 'polygon', 'points': [[20, 20], [30, 20], [30, 30]]}]}
    obrys, wyciecia = sg.resolve_corners('circle', None, sd, [_wpis('N1', r=5), _wpis('H1.P2', r=10)])
    assert obrys is None
    assert wyciecia[0]['corners'] == [None, {'type': 'round', 'r_mm': 10}, None]


def test_resolve_przycina_narozniki_do_bokow():
    # R 800 mm na boku 50 cm: bez przycięcia punkt styczności wypadłby poza blat
    sd = {'vertices': PROSTOKAT, 'corners': [{'type': 'round', 'r_mm': 800}, None, None, None]}
    obrys, _ = sg.resolve_corners('rectangular', PROSTOKAT, sd, None)
    assert obrys[0]['r_mm'] == 500
    # to samo dla narożnika wycięcia, także gdy pochodzi z krawędzi
    sd = {'vertices': PROSTOKAT, 'cutouts': [
        {'id': 'b', 'type': 'polygon', 'points': [[10, 10], [14, 10], [14, 14], [10, 14]]}]}
    _, wyciecia = sg.resolve_corners('rectangular', PROSTOKAT, sd, [_wpis('H1.P1', r=900)])
    assert wyciecia[0]['corners'][0] == {'type': 'round', 'r_mm': 40}


def test_resolve_bez_shape_data():
    assert sg.resolve_corners('rectangular', None, None, [_wpis('N1')]) == (None, [])
    obrys, _ = sg.resolve_corners('rectangular', PROSTOKAT, None, [_wpis('N1', r=20)])
    assert obrys[0] == {'type': 'round', 'r_mm': 20}
