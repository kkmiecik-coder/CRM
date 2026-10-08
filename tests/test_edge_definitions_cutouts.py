# -*- coding: utf-8 -*-
"""Krawędzie wycięć liczone z `cutouts` (elipsa = obwód) dla każdego kształtu
oraz ta sama cena na żywo (length_cm we wpisach) i przy zapisie (shape_data)."""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from modules.calculator.services.edge_calculator import _generate_edge_definitions
from modules.calculator.services.pricing_service import PricingData, calculate_edges_pricing
from modules.calculator.services.shape_geometry import ellipse_perimeter_cm

CENY = {'round': {'per_mb': 15.0, 'per_corner': 5.0},
        'chamfer': {'per_mb': 15.0, 'per_corner': 5.0},
        'sharp': {'per_mb': 0.0, 'per_corner': 0.0}}

PROSTOKAT = [[0, 0], [120, 0], [120, 60], [0, 60]]
ELIPSA = {'id': 'w1', 'type': 'ellipse', 'cx': 30, 'cy': 30, 'rx': 15, 'ry': 10, 'angle': 0}
KWADRAT = {'id': 'w2', 'type': 'polygon', 'points': [[60, 20], [80, 20], [80, 40], [60, 40]],
           'corners': [{'type': 'round', 'r_mm': 30}, None, None, None]}
# Pochodne holes ze spłaszczoną elipsą (72 punkty) — tak zapisuje kalkulator dla starych odbiorców
HOLES_ELIPSY = [[[30 + 15 * math.cos(2 * math.pi * k / 72), 30 + 10 * math.sin(2 * math.pi * k / 72)] for k in range(72)]]


def _ids(defs):
    return {d['id']: d for d in defs}


def test_elipsa_to_jedna_krawedz_obwodowa_bez_pionow():
    sd = {'vertices': PROSTOKAT, 'cutouts': [ELIPSA], 'holes': HOLES_ELIPSY}
    defs = _ids(_generate_edge_definitions('polygon', sd, 4))
    assert defs['H1.G1']['length_cm'] == pytest.approx(ellipse_perimeter_cm(15, 10))
    assert defs['H1.D1']['type_label'] == 'bottom'
    assert 'H1.G2' not in defs and 'H1.P1' not in defs


def test_wielokat_wyciecia_liczony_od_wierzcholka_do_wierzcholka():
    sd = {'vertices': PROSTOKAT, 'cutouts': [KWADRAT]}
    defs = _ids(_generate_edge_definitions('polygon', sd, 4))
    assert defs['H1.G1']['length_cm'] == pytest.approx(20)   # narożnik R30 nie skraca boku
    assert defs['H1.P1']['length_cm'] == pytest.approx(4)


def test_prostokat_i_kolo_tez_maja_krawedzie_wyciec():
    sd = {'vertices': PROSTOKAT, 'cutouts': [ELIPSA]}
    assert 'H1.G1' in _ids(_generate_edge_definitions('rectangular', sd, 4))
    sd_kola = {'params': {'diameter': 80}, 'vertices': None, 'cutouts': [ELIPSA]}
    assert 'H1.G1' in _ids(_generate_edge_definitions('circle', sd_kola, 4))


def test_stare_dane_z_holes_bez_zmian():
    sd = {'vertices': PROSTOKAT, 'holes': [[[10, 10], [30, 10], [30, 20]]]}
    defs = _ids(_generate_edge_definitions('polygon', sd, 4))
    assert defs['H1.G1']['length_cm'] == pytest.approx(20)
    assert defs['H1.P3']['type_label'] == 'vertical'


def _produkt(shape, sd, **kw):
    p = {'length': 120, 'width': 60, 'thickness': 4, 'quantity': 1, 'shape': shape, 'shape_data': sd}
    p.update(kw)
    return p


@pytest.mark.parametrize('shape', ['rectangular', 'polygon', 'circle'])
def test_ta_sama_cena_na_zywo_i_przy_zapisie(shape):
    sd = {'vertices': None if shape == 'circle' else PROSTOKAT, 'params': {'diameter': 60},
          'cutouts': [ELIPSA, KWADRAT], 'holes': HOLES_ELIPSY + [KWADRAT['points']]}
    obw = ellipse_perimeter_cm(15, 10)
    na_zywo = [  # /calculate: bez shape_data, długości z wpisów
        {'letter': 'H1.G1', 'type': 'round', 'r_value': 5, 'length_cm': round(obw, 2)},
        {'letter': 'H2.G1', 'type': 'round', 'r_value': 5, 'length_cm': 20},
        {'letter': 'H2.P1', 'type': 'round', 'r_value': 30},
    ]
    przy_zapisie = [{k: v for k, v in e.items() if k != 'length_cm'} for e in na_zywo]
    dane = PricingData(edge_prices=CENY)
    r1 = calculate_edges_pricing(na_zywo, _produkt(shape, None), dane)
    r2 = calculate_edges_pricing(przy_zapisie, _produkt(shape, sd), dane)
    assert r1['netto'] == r2['netto']
    assert r2['netto'] == pytest.approx(round(obw / 100 * 15 + 20 / 100 * 15 + 5, 2), abs=0.01)


@pytest.mark.parametrize('shape_data', ['null', '[]', '{zepsuty', 'tekst'])
def test_nieobiektowe_shape_data_nie_psuje_ceny_prostokata(shape_data):
    """Prostokąt dawniej ignorował shape_data — śmieciowa wartość nie może teraz wywalić wyceny."""
    wpisy = [{'letter': 'A', 'type': 'round', 'r_value': 5}]
    dane = PricingData(edge_prices=CENY)
    r = calculate_edges_pricing(wpisy, _produkt('rectangular', shape_data), dane)
    assert r['netto'] == pytest.approx(round(120 / 100 * 15, 2))


# --- Parytet cen: na żywo (/calculate, wpisy z PEŁNYMI długościami, bez shape_data) vs zapis (shape_data) ---
# Część JS przestała zaokrąglać length_cm wpisów, więc obie ścieżki dostają tę samą liczbę
# i ceny (netto i brutto, w obu trybach, dla ilości > 1) muszą się zgadzać co do grosza.

def _bok(p, q):
    return math.hypot(q[0] - p[0], q[1] - p[1])


def _wpis(litera, dlugosc=None, r=5):
    wpis = {'letter': litera, 'type': 'round', 'r_value': r}
    if dlugosc is not None:
        wpis['length_cm'] = dlugosc   # pełna precyzja, jak z JS
    return wpis


def _porownaj_na_zywo_i_zapis(shape, sd, wpisy, **produkt):
    """Ceny z wpisów z długościami (bez shape_data) i z shape_data (wpisy z zaokrąglonymi, nieaktualnymi
    długościami — tak je przysyła front). Zwraca (na_zywo, zapis)."""
    dane = PricingData(edge_prices=CENY)
    na_zywo = calculate_edges_pricing(wpisy, _produkt(shape, None, **produkt), dane)
    przy_zapisie = [dict(w, length_cm=round(w['length_cm'], 2)) if 'length_cm' in w else dict(w) for w in wpisy]
    zapis = calculate_edges_pricing(przy_zapisie, _produkt(shape, sd, **produkt), dane)
    return na_zywo, zapis


def _przypadek_prostokata():
    kwadrat = KWADRAT['points']
    sd = {'vertices': PROSTOKAT, 'cutouts': [ELIPSA, KWADRAT]}
    obw = ellipse_perimeter_cm(15, 10)
    wpisy = [
        _wpis('A'), _wpis('C'), _wpis('N1'), _wpis('H'),              # litery obrysu prostokąta
        _wpis('H1.G1', obw), _wpis('H1.D1', obw),                     # elipsa: obwód góra i dół
        _wpis('H2.G1', _bok(kwadrat[0], kwadrat[1])), _wpis('H2.G3', _bok(kwadrat[2], kwadrat[3])),
        _wpis('H2.D2', _bok(kwadrat[1], kwadrat[2])), _wpis('H2.P1', None, 30)]
    return 'rectangular', sd, wpisy


def _przypadek_kola():
    kwadrat = KWADRAT['points']
    sd = {'params': {'diameter': 60}, 'vertices': None, 'cutouts': [ELIPSA, KWADRAT]}
    obw = ellipse_perimeter_cm(15, 10)
    wpisy = [
        _wpis('KG'), _wpis('KD'),                                     # obwód koła z wymiarów
        _wpis('H1.G1', obw), _wpis('H1.D1', obw),
        _wpis('H2.G2', _bok(kwadrat[1], kwadrat[2])), _wpis('H2.D4', _bok(kwadrat[3], kwadrat[0])),
        _wpis('H2.P3', None, 30)]
    return 'circle', sd, wpisy


def _przypadek_wieloboku():
    trapez = [[0, 0], [120, 0], [90, 60], [10, 60]]
    sd = {'vertices': trapez, 'cutouts': [ELIPSA, KWADRAT]}
    kwadrat = KWADRAT['points']
    obw = ellipse_perimeter_cm(15, 10)
    wpisy = [
        _wpis('G1', _bok(trapez[0], trapez[1])), _wpis('G3', _bok(trapez[2], trapez[3])),
        _wpis('D2', _bok(trapez[1], trapez[2])), _wpis('D4', _bok(trapez[3], trapez[0])),
        _wpis('P1', None, 20),
        _wpis('H1.G1', obw), _wpis('H1.D1', obw),
        _wpis('H2.G4', _bok(kwadrat[3], kwadrat[0])), _wpis('H2.P2', None, 30)]
    return 'polygon', sd, wpisy


@pytest.mark.parametrize('przypadek', [_przypadek_prostokata, _przypadek_kola, _przypadek_wieloboku],
                         ids=['prostokat', 'kolo', 'wielokat'])
@pytest.mark.parametrize('tryb', ['basic', 'advanced'])
@pytest.mark.parametrize('ilosc', [1, 3, 7])
def test_parytet_na_zywo_i_zapis_litery_obrysu_obok_wyciec(przypadek, tryb, ilosc):
    shape, sd, wpisy = przypadek()
    na_zywo, zapis = _porownaj_na_zywo_i_zapis(shape, sd, wpisy, quantity=ilosc, edges_mode=tryb)
    assert na_zywo['netto'] == zapis['netto']
    assert na_zywo['brutto'] == zapis['brutto']
    assert zapis['netto'] > 0
    # Każda litera policzona w obu ścieżkach i każda z tą samą ceną
    assert [(d['letter'], d['price_netto'], d['price_brutto']) for d in na_zywo['details']] == \
           [(d['letter'], d['price_netto'], d['price_brutto']) for d in zapis['details']]


@pytest.mark.parametrize('tryb', ['basic', 'advanced'])
@pytest.mark.parametrize('ilosc', [1, 2, 10])
@pytest.mark.parametrize('rx, ry', [(1.05, 3.35), (4.15, 5.0), (7.35, 3.35), (0.55, 0.55), (12.85, 4.15)])
def test_parytet_elipsy_o_niewygodnych_polosiach(rx, ry, ilosc, tryb):
    # Przypadek recenzenta: półosie 1,05 i 3,35 dawały 4,43 zł z długości zaokrąglonej do 0,01 cm
    # i 4,44 zł z shape_data. Teraz wpis niesie pełną długość, więc ceny są równe.
    sd = {'vertices': PROSTOKAT, 'cutouts': [
        {'id': 'a', 'type': 'ellipse', 'cx': 30, 'cy': 30, 'rx': rx, 'ry': ry, 'angle': 0}]}
    obw = ellipse_perimeter_cm(rx, ry)
    wpisy = [_wpis('H1.G1', obw), _wpis('H1.D1', obw)]
    na_zywo, zapis = _porownaj_na_zywo_i_zapis('rectangular', sd, wpisy, quantity=ilosc, edges_mode=tryb)
    assert na_zywo['netto'] == zapis['netto'] and na_zywo['brutto'] == zapis['brutto']


def test_parytet_elipsy_na_calej_siatce_polosi():
    niezgodne = []
    for rx_20 in range(20, 200, 7):
        for ry in (3.35, 4.15, 5.0):
            rx = rx_20 / 20
            sd = {'vertices': PROSTOKAT, 'cutouts': [
                {'id': 'a', 'type': 'ellipse', 'cx': 30, 'cy': 30, 'rx': rx, 'ry': ry, 'angle': 0}]}
            obw = ellipse_perimeter_cm(rx, ry)
            wpisy = [_wpis('H1.G1', obw), _wpis('H1.D1', obw)]
            for ilosc in (1, 10):
                for tryb in ('basic', 'advanced'):
                    na_zywo, zapis = _porownaj_na_zywo_i_zapis('rectangular', sd, wpisy, quantity=ilosc, edges_mode=tryb)
                    if (na_zywo['netto'], na_zywo['brutto']) != (zapis['netto'], zapis['brutto']):
                        niezgodne.append((rx, ry, ilosc, tryb))
    assert niezgodne == []


# Stara elipsa: kalkulator zapisywał ją w `holes` jako 72-kąt, a litery krawędzi szły po jego bokach

def _stare_dane_z_elipsa_w_holes():
    return {'vertices': PROSTOKAT, 'holes': HOLES_ELIPSY}


def test_stara_elipsa_w_holes_ma_72_boki_wiec_istnieje_litera_H1_G72():
    defs = _ids(_generate_edge_definitions('rectangular', _stare_dane_z_elipsa_w_holes(), 4))
    pierscien = HOLES_ELIPSY[0]
    assert defs['H1.G72']['length_cm'] == pytest.approx(_bok(pierscien[71], pierscien[0]))
    assert defs['H1.D72']['type_label'] == 'bottom'
    assert defs['H1.P72']['length_cm'] == pytest.approx(4)


@pytest.mark.parametrize('tryb', ['basic', 'advanced'])
def test_stara_wycena_z_litera_H1_G72_liczy_sie_z_holes(tryb):
    pierscien = HOLES_ELIPSY[0]
    bok = _bok(pierscien[71], pierscien[0])
    wpisy = [_wpis('H1.G72', bok), _wpis('H1.D72', bok), _wpis('H1.P72', None, 5)]
    na_zywo, zapis = _porownaj_na_zywo_i_zapis('rectangular', _stare_dane_z_elipsa_w_holes(), wpisy,
                                               quantity=3, edges_mode=tryb)
    assert na_zywo['netto'] == zapis['netto'] and na_zywo['brutto'] == zapis['brutto']
    assert [d['letter'] for d in zapis['details']] == ['H1.G72', 'H1.D72', 'H1.P72']
    assert zapis['details'][0]['length_cm'] == pytest.approx(bok, abs=0.005)
    assert zapis['details'][2]['is_corner'] is True


def test_litera_H1_G72_znika_gdy_elipsa_jest_w_cutouts():
    # Po zapisie w nowym edytorze elipsa to jedna krawędź obwodowa (H1.G1); holes zostaje tylko dla
    # starszych odbiorców i nie dubluje krawędzi
    sd = {'vertices': PROSTOKAT, 'cutouts': [ELIPSA], 'holes': HOLES_ELIPSY}
    defs = _ids(_generate_edge_definitions('rectangular', sd, 4))
    assert 'H1.G72' not in defs and 'H1.G1' in defs
