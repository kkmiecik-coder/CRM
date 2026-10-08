# -*- coding: utf-8 -*-
"""DXF dla CNC: łuki narożników (bulge), ścięcia, wycięcia (CIRCLE/ELLIPSE/polilinia)."""
import io
import json
import math
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ezdxf
import pytest
from ezdxf.math import Vec2, bulge_to_arc

from modules.calculator.services.dxf_service import generate_product_dxf, generate_single_dxf

PROSTOKAT = [[0, 0], [100, 0], [100, 50], [0, 50]]
# Ten sam prostokąt w kolejności zgodnej z ruchem wskazówek zegara (np. stary wielokąt po obrocie)
PROSTOKAT_CW = [[0, 0], [0, 50], [100, 50], [100, 0]]
# Litera L: wierzchołek 3 (50, 50) jest rogiem wklęsłym
L_CCW = [[0, 0], [100, 0], [100, 50], [50, 50], [50, 100], [0, 100]]
L_CW = list(reversed(L_CCW))


def _item(**kw):
    dane = dict(length_cm=100, width_cm=50, thickness_cm=4, variant_code='dab-lity-ab')
    dane.update(kw)
    return SimpleNamespace(**dane)


def _details(shape, sd, edges_config=None):
    return SimpleNamespace(shape=shape, shape_data=json.dumps(sd) if sd is not None else None,
                           quantity=1, edges_type=None, edges_r_value=None, edges_angle_value=None,
                           edges_config=edges_config)


def _msp_z_bufora(bufor):
    return ezdxf.read(io.StringIO(bufor.getvalue().decode('utf-8'))).modelspace()


def _msp(item, details):
    return _msp_z_bufora(generate_product_dxf(item, details))


def _ciecie(msp, typ):
    return [e for e in msp.query(typ) if e.dxf.layer == 'CUT']


def _srodki_lukow(punkty):
    """Środki łuków zamkniętej polilinii (x, y, bulge): odcinek i → i+1 niesie bulge punktu i."""
    srodki = []
    for i, (x, y, b) in enumerate(punkty):
        if abs(b) < 1e-9:
            continue
        nx, ny, _ = punkty[(i + 1) % len(punkty)]
        srodek, _, _, promien = bulge_to_arc(Vec2(x, y), Vec2(nx, ny), b)
        srodki.append((round(srodek.x, 3), round(srodek.y, 3), round(promien, 3)))
    return srodki


def test_prostokat_bez_narozników_jak_dotad():
    msp = _msp(_item(), _details('rectangular', {'vertices': PROSTOKAT}))
    polilinie = _ciecie(msp, 'LWPOLYLINE')
    assert len(polilinie) == 1
    punkty = polilinie[0].get_points('xyb')
    assert [(round(x), round(y), b) for x, y, b in punkty] == [(0, 0, 0), (1000, 0, 0), (1000, 500, 0), (0, 500, 0)]


def test_luki_narozników_jako_bulge():
    sd = {'vertices': PROSTOKAT, 'corners': [{'type': 'round', 'r_mm': 50}] * 4}
    punkty = _ciecie(_msp(_item(), _details('rectangular', sd)), 'LWPOLYLINE')[0].get_points('xyb')
    assert len(punkty) == 8
    wybrzuszenia = [b for _, _, b in punkty if abs(b) > 1e-9]
    assert len(wybrzuszenia) == 4
    assert all(b == pytest.approx(math.tan(math.radians(22.5))) for b in wybrzuszenia)


@pytest.mark.parametrize('wierzcholki', [PROSTOKAT, PROSTOKAT_CW], ids=['ccw', 'cw'])
def test_luki_narozników_wypuklych_leza_wewnatrz_blatu_dla_obu_kierunkow(wierzcholki):
    # Znak bulge zależy od kierunku obrysu: łuk ma ściąć róg (środek wewnątrz blatu),
    # a nie wypchnąć go na zewnątrz — także dla wielokąta zapisanego zgodnie z zegarem
    sd = {'vertices': wierzcholki, 'corners': [{'type': 'round', 'r_mm': 50}] * 4}
    punkty = _ciecie(_msp(_item(), _details('rectangular', sd)), 'LWPOLYLINE')[0].get_points('xyb')
    assert sorted(_srodki_lukow(punkty)) == sorted([
        (50.0, 50.0, 50.0), (950.0, 50.0, 50.0), (950.0, 450.0, 50.0), (50.0, 450.0, 50.0)])
    # Wszystkie punkty obrysu leżą w prostokącie blatu
    assert all(-1e-6 <= x <= 1000 + 1e-6 and -1e-6 <= y <= 500 + 1e-6 for x, y, _ in punkty)


@pytest.mark.parametrize('wierzcholki', [L_CCW, L_CW], ids=['ccw', 'cw'])
def test_luk_w_rogu_wklesłym_dokłada_materiał_dla_obu_kierunkow(wierzcholki):
    # Róg wklęsły L (50, 50) cm: środek łuku r = 10 mm leży w pustym klinie, na zewnątrz blatu
    indeks = wierzcholki.index([50, 50])
    narozniki = [None] * len(wierzcholki)
    narozniki[indeks] = {'type': 'round', 'r_mm': 10}
    sd = {'vertices': wierzcholki, 'corners': narozniki}
    punkty = _ciecie(_msp(_item(), _details('rectangular', sd)), 'LWPOLYLINE')[0].get_points('xyb')
    assert _srodki_lukow(punkty) == [(510.0, 510.0, 10.0)]


def test_fazowanie_jako_odcinek():
    sd = {'vertices': PROSTOKAT, 'corners': [{'type': 'chamfer', 'r_mm': 20}, None, None, None]}
    punkty = _ciecie(_msp(_item(), _details('rectangular', sd)), 'LWPOLYLINE')[0].get_points('xyb')
    assert len(punkty) == 5
    xy = {(round(x, 3), round(y, 3)) for x, y, _ in punkty}
    assert (0.0, 20.0) in xy and (20.0, 0.0) in xy
    assert all(b == 0 for _, _, b in punkty)


def test_wyciecia_na_warstwie_ciecia():
    sd = {'vertices': PROSTOKAT, 'cutouts': [
        {'id': 'a', 'type': 'ellipse', 'cx': 30, 'cy': 30, 'rx': 10, 'ry': 10, 'angle': 0},
        {'id': 'b', 'type': 'ellipse', 'cx': 60, 'cy': 25, 'rx': 15, 'ry': 10, 'angle': 0},
        {'id': 'c', 'type': 'polygon', 'points': [[80, 10], [95, 10], [95, 40], [80, 40]],
         'corners': [None, {'type': 'round', 'r_mm': 30}, None, None]},
    ]}
    msp = _msp(_item(), _details('rectangular', sd))
    kola = _ciecie(msp, 'CIRCLE')
    assert len(kola) == 1 and kola[0].dxf.radius == pytest.approx(100)
    elipsy = _ciecie(msp, 'ELLIPSE')
    assert len(elipsy) == 1
    assert elipsy[0].dxf.ratio == pytest.approx(10 / 15)
    assert elipsy[0].dxf.major_axis.magnitude == pytest.approx(150)
    polilinie = _ciecie(msp, 'LWPOLYLINE')
    assert len(polilinie) == 2   # obrys + wycięcie prostokątne
    assert any(abs(b) > 1e-9 for _, _, b in polilinie[1].get_points('xyb'))


def test_elipsa_obrocona_i_pionowa_oś_dluzsza():
    sd = {'vertices': PROSTOKAT, 'cutouts': [
        # rx > ry, obrót 90°: dłuższa półoś (15 cm) leży wzdłuż osi Y
        {'id': 'a', 'type': 'ellipse', 'cx': 30, 'cy': 25, 'rx': 15, 'ry': 10, 'angle': 90},
        # rx < ry, bez obrotu: dłuższa półoś (15 cm) leży wzdłuż osi Y
        {'id': 'b', 'type': 'ellipse', 'cx': 70, 'cy': 25, 'rx': 10, 'ry': 15, 'angle': 0},
    ]}
    elipsy = _ciecie(_msp(_item(), _details('rectangular', sd)), 'ELLIPSE')
    assert len(elipsy) == 2
    for e in elipsy:
        os_glowna = e.dxf.major_axis
        assert abs(os_glowna.x) < 1e-6 and abs(os_glowna.y) == pytest.approx(150)
        assert e.dxf.ratio == pytest.approx(10 / 15)


def test_wyciecie_ze_starego_pola_holes_trafia_na_warstwe_ciecia():
    # Stare wyceny trzymają tylko `holes` (bez `cutouts`) — wycięcie ma być w pliku dla CNC
    sd = {'vertices': PROSTOKAT, 'holes': [[[10, 10], [20, 10], [20, 20], [10, 20]]]}
    polilinie = _ciecie(_msp(_item(), _details('rectangular', sd)), 'LWPOLYLINE')
    assert len(polilinie) == 2
    assert sorted((round(x), round(y)) for x, y, _ in polilinie[1].get_points('xyb')) == [
        (100, 100), (100, 200), (200, 100), (200, 200)]


def test_kolo_srednica_z_wymiaru_produktu_i_wyciecie():
    # params.diameter = 80 to domyślna wartość, której edytor nie aktualizował dla koła
    sd = {'params': {'diameter': 80}, 'vertices': None,
          'cutouts': [{'id': 'a', 'type': 'ellipse', 'cx': 30, 'cy': 30, 'rx': 5, 'ry': 5, 'angle': 0}]}
    msp = _msp(_item(length_cm=60, width_cm=60), _details('circle', sd))
    promienie = sorted(e.dxf.radius for e in _ciecie(msp, 'CIRCLE'))
    assert promienie == [pytest.approx(50), pytest.approx(300)]


def test_kolo_bez_shape_data_i_bez_wymiaru_uzywa_parametru():
    # Brak shape_data: średnica z wymiaru produktu, bez wyjątku przy rysowaniu wycięć
    kola = _ciecie(_msp(_item(length_cm=60, width_cm=60), _details('circle', None)), 'CIRCLE')
    assert [e.dxf.radius for e in kola] == [pytest.approx(300)]
    # Brak length_cm: awaryjnie parametr z shape_data
    kola = _ciecie(_msp(_item(length_cm=None, width_cm=None),
                        _details('circle', {'params': {'diameter': 80}, 'vertices': None})), 'CIRCLE')
    assert [e.dxf.radius for e in kola] == [pytest.approx(400)]


def test_wyciecia_przesuniete_o_offset_w_pliku_ze_wszystkimi_produktami():
    sd = {'vertices': PROSTOKAT, 'cutouts': [
        {'id': 'a', 'type': 'ellipse', 'cx': 30, 'cy': 30, 'rx': 10, 'ry': 10, 'angle': 0}]}
    items = [(_item(), _details('rectangular', {'vertices': PROSTOKAT})),
             (_item(), _details('rectangular', sd))]
    msp = _msp_z_bufora(generate_single_dxf(SimpleNamespace(), items))
    kola = _ciecie(msp, 'CIRCLE')
    assert len(kola) == 1
    # Drugi produkt zaczyna się po szerokości pierwszego (1000 mm) i odstępie 50 mm
    assert kola[0].dxf.center.x == pytest.approx(1050 + 300)
    assert kola[0].dxf.center.y == pytest.approx(300)


# --- P1: stare wyceny mają narożniki tylko w edges_config ---

def _wpis(litera, typ='round', r=20):
    return {'letter': litera, 'type': typ, 'r_value': r}


def _obrys(msp):
    return _ciecie(msp, 'LWPOLYLINE')[0].get_points('xyb')


@pytest.mark.parametrize('jako_tekst', [False, True], ids=['lista', 'json'])
def test_stara_wycena_prostokat_naroza_z_krawedzi_maja_luki(jako_tekst):
    # N1→v0, N2→v1, N4→v2, N3→v3 — jak pullCornersFromEdges na froncie
    wpisy = [_wpis('N1', r=10), _wpis('N2', r=20), _wpis('N3', r=40), _wpis('N4', r=30)]
    msp = _msp(_item(), _details('rectangular', {'vertices': PROSTOKAT},
                                 json.dumps(wpisy) if jako_tekst else wpisy))
    punkty = _obrys(msp)
    assert len(punkty) == 8
    assert sorted(_srodki_lukow(punkty)) == sorted([
        (10.0, 10.0, 10.0), (980.0, 20.0, 20.0), (970.0, 470.0, 30.0), (40.0, 460.0, 40.0)])


def test_stara_wycena_4787_prostokat_n1_n4_r20_ma_cztery_luki():
    wpisy = [_wpis(f'N{i}', r=20) for i in (1, 2, 3, 4)]
    punkty = _obrys(_msp(_item(), _details('rectangular', {'vertices': PROSTOKAT}, wpisy)))
    assert sum(1 for _, _, b in punkty if abs(b) > 1e-9) == 4


def test_stara_wycena_prostokat_bez_shape_data_tez_dostaje_luki():
    # Najstarsze wyceny nie mają shape_data w ogóle — kontur idzie z wymiarów produktu
    wpisy = [_wpis(f'N{i}', r=20) for i in (1, 2, 3, 4)]
    punkty = _obrys(_msp(_item(), _details('rectangular', None, wpisy)))
    assert sorted(_srodki_lukow(punkty)) == sorted([
        (20.0, 20.0, 20.0), (980.0, 20.0, 20.0), (980.0, 480.0, 20.0), (20.0, 480.0, 20.0)])


def test_stara_wycena_wielokat_litery_P_na_trojkacie():
    trojkat = [[0, 0], [100, 0], [0, 100]]
    wpisy = [_wpis('P1', r=10), _wpis('P3', 'chamfer', 20)]
    punkty = _obrys(_msp(_item(), _details('polygon', {'vertices': trojkat}, wpisy)))
    # v0: łuk (2 punkty), v1: ostry (1), v2: ścięcie (2 punkty)
    assert len(punkty) == 5
    assert _srodki_lukow(punkty) == [(10.0, 10.0, 10.0)]


@pytest.mark.parametrize('litera', ['P0', 'P7', 'N1', 'H3.P1', 'H1.P9'])
def test_litery_spoza_zakresu_nie_daja_naroznika(litera):
    trojkat = [[0, 0], [100, 0], [0, 100]]
    sd = {'vertices': trojkat, 'cutouts': [
        {'id': 'a', 'type': 'polygon', 'points': [[10, 10], [30, 10], [30, 30]]},
        {'id': 'b', 'type': 'polygon', 'points': [[40, 10], [50, 10], [50, 20]]}]}
    polilinie = _ciecie(_msp(_item(), _details('polygon', sd, [_wpis(litera)])), 'LWPOLYLINE')
    assert [len(p) for p in polilinie] == [3, 3, 3]
    assert all(abs(b) < 1e-9 for p in polilinie for _, _, b in p.get_points('xyb'))


def test_narozniki_z_shape_data_wygrywaja_z_krawedziami_w_dxf():
    sd = {'vertices': PROSTOKAT, 'corners': [None, {'type': 'chamfer', 'r_mm': 20}, None, None]}
    punkty = _obrys(_msp(_item(), _details('rectangular', sd, [_wpis('N1', r=50)])))
    assert len(punkty) == 5 and all(b == 0 for _, _, b in punkty)


def test_stare_wyciecie_wielokatne_dostaje_naroznik_z_litery_H_P():
    sd = {'vertices': PROSTOKAT, 'cutouts': [
        {'id': 'a', 'type': 'polygon', 'points': [[80, 10], [95, 10], [95, 40], [80, 40]]}]}
    polilinie = _ciecie(_msp(_item(), _details('rectangular', sd, [_wpis('H1.P3', r=30)])), 'LWPOLYLINE')
    assert _srodki_lukow(polilinie[1].get_points('xyb')) == [(920.0, 370.0, 30.0)]


# --- P2: narożniki przycinane do geometrii (dla danych z edytora to no-op) ---

def test_narozniki_wieksze_niz_bok_sa_przycinane_i_obrys_nie_cofa_sie():
    sd = {'vertices': PROSTOKAT, 'corners': [{'type': 'round', 'r_mm': 800}, None, None, None]}
    punkty = _obrys(_msp(_item(), _details('rectangular', sd)))
    # Krótszy bok ma 500 mm — łuk R800 wyprowadziłby punkty styczności poza blat
    assert all(-1e-6 <= x <= 1000 + 1e-6 and -1e-6 <= y <= 500 + 1e-6 for x, y, _ in punkty)
    assert _srodki_lukow(punkty) == [(500.0, 500.0, 500.0)]


def test_narozniki_wyciecia_wiekszy_niz_bok_tez_przyciete():
    sd = {'vertices': PROSTOKAT, 'cutouts': [
        {'id': 'a', 'type': 'polygon', 'points': [[10, 10], [14, 10], [14, 14], [10, 14]],
         'corners': [{'type': 'round', 'r_mm': 900}, None, None, None]}]}
    polilinia = _ciecie(_msp(_item(), _details('rectangular', sd)), 'LWPOLYLINE')[1]
    assert all(100 - 1e-6 <= x <= 140 + 1e-6 and 100 - 1e-6 <= y <= 140 + 1e-6
               for x, y, _ in polilinia.get_points('xyb'))


def test_edytorowe_narozniki_nie_zmieniaja_sie_po_przycieciu():
    # No-op dla danych z edytora: ten sam wynik co przed dodaniem przycinania
    sd = {'vertices': PROSTOKAT, 'corners': [{'type': 'round', 'r_mm': 50}] * 4}
    assert sorted(_srodki_lukow(_obrys(_msp(_item(), _details('rectangular', sd))))) == sorted([
        (50.0, 50.0, 50.0), (950.0, 50.0, 50.0), (950.0, 450.0, 50.0), (50.0, 450.0, 50.0)])


# --- P3: zepsute shape_data nie wywala pliku DXF ---

_P = [[0, 0], [100, 0], [100, 50], [0, 50]]
_TRI = [[0, 0], [10, 0], [0, 10]]
_ZLE_SHAPE_DATA = {
    'vertices tekst': {'vertices': 'abcd'},
    'vertices 2 punkty': {'vertices': [[0, 0], [1, 1]]},
    'vertices z tekstem': {'vertices': [[0, 'a'], [1, 2], [3, 4]]},
    'vertices krotkie punkty': {'vertices': [[0], [1], [2]]},
    'vertices z null': {'vertices': [[0, 0], None, [1, 2]]},
    'vertices NaN': {'vertices': [[0, 0], [float('nan'), 1], [3, 4]]},
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
    'corners r_mm Infinity': {'vertices': _P, 'corners': [{'type': 'round', 'r_mm': float('inf')}, None, None, None]},
    'corners r_mm True': {'vertices': _P, 'corners': [{'type': 'round', 'r_mm': True}, None, None, None]},
    'params null': {'params': None, 'vertices': _P},
    'params srednica tekst': {'params': {'diameter': 'x'}, 'vertices': None},
    'params srednica NaN': {'params': {'diameter': float('nan')}, 'vertices': None,
                            'cutouts': [{'type': 'ellipse', 'cx': 3, 'cy': 3, 'rx': 1, 'ry': 1}]},
}


@pytest.mark.parametrize('ksztalt', ['rectangular', 'circle', 'polygon'])
@pytest.mark.parametrize('nazwa', list(_ZLE_SHAPE_DATA))
def test_zepsute_shape_data_nie_wywala_dxf(nazwa, ksztalt):
    msp = _msp(_item(), _details(ksztalt, _ZLE_SHAPE_DATA[nazwa], [_wpis('N1'), _wpis('P2'), _wpis('H1.P1')]))
    # Zawsze zostaje jakiś kontur do cięcia: koło albo prostokąt (z wierzchołków lub z wymiarów)
    assert _ciecie(msp, 'LWPOLYLINE') or _ciecie(msp, 'CIRCLE')


@pytest.mark.parametrize('surowe', ['[1, 2]', '"tekst"', '5', 'true', '{zepsuty'])
def test_shape_data_niebedace_obiektem_daje_prostokat_z_wymiarow(surowe):
    det = SimpleNamespace(shape='rectangular', shape_data=surowe, quantity=1, edges_type=None,
                          edges_r_value=None, edges_angle_value=None, edges_config=None)
    punkty = _obrys(_msp(_item(), det))
    assert [(round(x), round(y)) for x, y, _ in punkty] == [(0, 0), (1000, 0), (1000, 500), (0, 500)]


def test_blad_przy_rysowaniu_wyciec_cofa_wszystkie_wyciecia_i_loguje_ostrzezenie(monkeypatch, caplog):
    # Pierwsze wycięcie (okrąg) rysuje się poprawnie, drugie (elipsa) rzuca wyjątek:
    # plik ma zawierać sam obrys, bez połowy wycięć
    def zepsute_add_ellipse(self, *args, **kwargs):
        raise RuntimeError('ezdxf nie przyjął elipsy')
    monkeypatch.setattr('ezdxf.layouts.BaseLayout.add_ellipse', zepsute_add_ellipse)
    sd = {'vertices': PROSTOKAT, 'cutouts': [
        {'id': 'a', 'type': 'ellipse', 'cx': 20, 'cy': 25, 'rx': 5, 'ry': 5, 'angle': 0},
        {'id': 'b', 'type': 'ellipse', 'cx': 60, 'cy': 25, 'rx': 10, 'ry': 5, 'angle': 0}]}
    with caplog.at_level('WARNING'):
        msp = _msp(_item(), _details('rectangular', sd))
    assert len(_ciecie(msp, 'LWPOLYLINE')) == 1
    assert _ciecie(msp, 'CIRCLE') == [] and _ciecie(msp, 'ELLIPSE') == []
    assert any('wyci' in r.getMessage().lower() for r in caplog.records)


def test_blad_przy_budowie_narozy_daje_obrys_z_ostrymi_rogami_i_ostrzezenie(monkeypatch, caplog):
    def zepsute_contour(*args, **kwargs):
        raise ValueError('zepsuta geometria')
    monkeypatch.setattr('modules.calculator.services.dxf_service._contour_xyb', zepsute_contour)
    sd = {'vertices': PROSTOKAT, 'corners': [{'type': 'round', 'r_mm': 50}] * 4}
    with caplog.at_level('WARNING'):
        punkty = _obrys(_msp(_item(), _details('rectangular', sd)))
    assert [(round(x), round(y), b) for x, y, b in punkty] == [(0, 0, 0), (1000, 0, 0), (1000, 500, 0), (0, 500, 0)]
    assert any('narożnik' in r.getMessage().lower() for r in caplog.records)


# --- P6: koło — wycięcia przesunięte, gdy średnica produktu różni się od params.diameter ---

def _srodek_wyciecia_kola(sd, **item_kw):
    msp = _msp(_item(**item_kw), _details('circle', sd))
    wyciecia = [e for e in _ciecie(msp, 'CIRCLE') if e.dxf.radius < 100]
    assert len(wyciecia) == 1
    return (round(wyciecia[0].dxf.center.x, 3), round(wyciecia[0].dxf.center.y, 3))


def _kolo_z_wycieciem(srednica_param):
    return {'params': {'diameter': srednica_param}, 'vertices': None,
            'cutouts': [{'id': 'a', 'type': 'ellipse', 'cx': 30, 'cy': 30, 'rx': 5, 'ry': 5, 'angle': 0}]}


def test_kolo_wyciecie_przesuniete_o_roznice_promieni():
    # Rysunek miał koło Ø 80 (środek 40, 40), produkt ma Ø 60 (środek 30, 30): wycięcie w (30, 30)
    # leży 10 cm na lewo i w dół od środka rysunku, więc w produkcie ląduje w (20, 20) cm
    assert _srodek_wyciecia_kola(_kolo_z_wycieciem(80), length_cm=60, width_cm=60) == (200.0, 200.0)


def test_kolo_wyciecie_bez_przesuniecia_gdy_srednice_rowne():
    assert _srodek_wyciecia_kola(_kolo_z_wycieciem(60), length_cm=60, width_cm=60) == (300.0, 300.0)


def test_kolo_wyciecie_przesuniete_w_gore_gdy_produkt_wiekszy():
    assert _srodek_wyciecia_kola(_kolo_z_wycieciem(40), length_cm=60, width_cm=60) == (400.0, 400.0)


def test_kolo_bez_wymiaru_produktu_nie_przesuwa_wyciec():
    # Brak length_cm: średnica z parametru, więc oba koła są tym samym kołem
    assert _srodek_wyciecia_kola(_kolo_z_wycieciem(60), length_cm=None, width_cm=None) == (300.0, 300.0)


def test_kolo_przesuniecie_wyciec_w_pliku_ze_wszystkimi_produktami():
    items = [(_item(), _details('rectangular', {'vertices': PROSTOKAT})),
             (_item(length_cm=60, width_cm=60), _details('circle', _kolo_z_wycieciem(80)))]
    msp = _msp_z_bufora(generate_single_dxf(SimpleNamespace(), items))
    wyciecie = [e for e in _ciecie(msp, 'CIRCLE') if e.dxf.radius < 100][0]
    # Koło zaczyna się po prostokącie 1000 mm i odstępie 50 mm; wycięcie: (30-10) cm = 200 mm od krawędzi koła
    assert wyciecie.dxf.center.x == pytest.approx(1050 + 200)
    assert wyciecie.dxf.center.y == pytest.approx(200)


# --- P7: drobiazgi ---

def test_prawie_kolo_to_elipsa_a_dokladne_kolo_to_okrag():
    sd = {'vertices': PROSTOKAT, 'cutouts': [
        {'id': 'a', 'type': 'ellipse', 'cx': 20, 'cy': 20, 'rx': 5, 'ry': 5, 'angle': 0},
        {'id': 'b', 'type': 'ellipse', 'cx': 40, 'cy': 20, 'rx': 5, 'ry': 5 + 1e-9, 'angle': 0},
        {'id': 'c', 'type': 'ellipse', 'cx': 60, 'cy': 20, 'rx': 5, 'ry': 5.04, 'angle': 0}]}
    msp = _msp(_item(), _details('rectangular', sd))
    # Różnica 0,4 mm to już elipsa — dawny próg 0,5 mm spłaszczał ją do okręgu
    assert len(_ciecie(msp, 'CIRCLE')) == 2
    assert len(_ciecie(msp, 'ELLIPSE')) == 1


def test_wyciecie_w_prostokacie_bez_wierzcholkow_tez_trafia_do_dxf():
    sd = {'cutouts': [{'id': 'a', 'type': 'ellipse', 'cx': 30, 'cy': 25, 'rx': 10, 'ry': 10, 'angle': 0},
                      {'id': 'b', 'type': 'polygon', 'points': [[60, 10], [80, 10], [80, 30]]}]}
    msp = _msp(_item(), _details('rectangular', sd))
    assert [e.dxf.radius for e in _ciecie(msp, 'CIRCLE')] == [pytest.approx(100)]
    assert len(_ciecie(msp, 'LWPOLYLINE')) == 2


@pytest.mark.parametrize('os_zla', [{'rx': 0}, {'ry': 0}, {'rx': -1, 'ry': -1}])
def test_polos_zerowa_albo_ujemna_nie_daje_wyciecia(os_zla):
    elipsa = {'id': 'a', 'type': 'ellipse', 'cx': 30, 'cy': 25, 'rx': 5, 'ry': 5, 'angle': 0}
    elipsa.update(os_zla)
    msp = _msp(_item(), _details('rectangular', {'vertices': PROSTOKAT, 'cutouts': [elipsa]}))
    assert _ciecie(msp, 'CIRCLE') == [] and _ciecie(msp, 'ELLIPSE') == []


@pytest.mark.parametrize('wierzcholki', [
    [[50, 10], [80, 10], [80, 40], [50, 40]],     # przeciwnie do ruchu wskazówek zegara
    [[50, 10], [50, 40], [80, 40], [80, 10]],     # zgodnie z ruchem wskazówek zegara
], ids=['ccw', 'cw'])
def test_wyciecie_wielokatne_z_narozem_dla_obu_kierunkow(wierzcholki):
    # Narożnik wycięcia w (80, 40): łuk R3 mm ma środek 3 mm w głąb wycięcia
    narozniki = [{'type': 'round', 'r_mm': 30} if w == [80, 40] else None for w in wierzcholki]
    sd = {'vertices': PROSTOKAT, 'cutouts': [
        {'id': 'a', 'type': 'polygon', 'points': wierzcholki, 'corners': narozniki}]}
    polilinie = _ciecie(_msp(_item(), _details('rectangular', sd)), 'LWPOLYLINE')
    assert _srodki_lukow(polilinie[1].get_points('xyb')) == [(770.0, 370.0, 30.0)]


# Zwykłe kształty bez wycięć i narożników: encje takie same jak w wersji sprzed gałęzi (31a0b014)
def _encje(msp):
    wynik = []
    for e in msp:
        typ = e.dxftype()
        if typ == 'LWPOLYLINE':
            wynik.append((typ, e.dxf.layer, bool(e.closed),
                          [tuple(round(float(v), 6) for v in p) for p in e.get_points('xyb')]))
        elif typ == 'CIRCLE':
            wynik.append((typ, e.dxf.layer, tuple(round(float(v), 6) for v in e.dxf.center),
                          round(float(e.dxf.radius), 6)))
        elif typ == 'TEXT':
            wynik.append((typ, e.dxf.text, tuple(round(float(v), 6) for v in e.dxf.insert)))
        elif typ == 'DIMENSION':
            wynik.append((typ, tuple(round(float(v), 6) for v in e.dxf.defpoint), round(e.get_measurement(), 6)))
        else:
            wynik.append((typ,))
    return wynik


def _details_z_krawedzia(shape, sd):
    return SimpleNamespace(shape=shape, shape_data=json.dumps(sd) if sd is not None else None, quantity=2,
                           edges_type='round', edges_r_value=5, edges_angle_value=None)


_PROSTOKAT_ENCJE = [
    ('LWPOLYLINE', 'CUT', True, [(0.0, 0.0, 0.0), (1000.0, 0.0, 0.0), (1000.0, 500.0, 0.0), (0.0, 500.0, 0.0)]),
    ('DIMENSION', (0.0, -50.0, 0.0), 1000.0), ('DIMENSION', (-50.0, 0.0, 0.0), 500.0),
    ('TEXT', 'Dąb Lity A/B', (500.0, 658.5, 0.0)), ('TEXT', 'Grubość: 40mm', (500.0, 626.5, 0.0)),
    ('TEXT', 'Ilość: 2 szt.', (500.0, 594.5, 0.0)), ('TEXT', 'Krawędzie: Frezowanie R5mm', (500.0, 562.5, 0.0))]

OCZEKIWANE_ZWYKLE = {
    'prostokat': (
        _item(), 'rectangular', {'params': {}, 'vertices': PROSTOKAT, 'holes': []}, _PROSTOKAT_ENCJE),
    'trojkat': (
        _item(), 'polygon', {'params': {}, 'vertices': [[0, 0], [80, 0], [30, 60]], 'holes': []},
        [('LWPOLYLINE', 'CUT', True, [(0.0, 0.0, 0.0), (800.0, 0.0, 0.0), (300.0, 600.0, 0.0)]),
         ('DIMENSION', (0.0, -60.0, 0.0), 800.0), ('DIMENSION', (-60.0, 0.0, 0.0), 600.0),
         ('TEXT', 'Dąb Lity A/B', (400.0, 790.2, 0.0)), ('TEXT', 'Grubość: 40mm', (400.0, 751.8, 0.0)),
         ('TEXT', 'Ilość: 2 szt.', (400.0, 713.4, 0.0)), ('TEXT', 'Krawędzie: Frezowanie R5mm', (400.0, 675.0, 0.0))]),
    'kolo': (
        _item(length_cm=60, width_cm=60), 'circle', {'params': {'diameter': 60}, 'vertices': None, 'holes': []},
        [('CIRCLE', 'CUT', (300.0, 300.0, 0.0), 300.0),
         ('DIMENSION', (512.132034, 512.132034, 0.0), 600.0),
         ('TEXT', 'Dąb Lity A/B', (300.0, 790.2, 0.0)), ('TEXT', 'Grubość: 40mm', (300.0, 751.8, 0.0)),
         ('TEXT', 'Ilość: 2 szt.', (300.0, 713.4, 0.0)), ('TEXT', 'Krawędzie: Frezowanie R5mm', (300.0, 675.0, 0.0))]),
    'awaryjny': (_item(), 'rectangular', None, _PROSTOKAT_ENCJE),
}


@pytest.mark.parametrize('nazwa', list(OCZEKIWANE_ZWYKLE))
def test_zwykle_ksztalty_bez_wyciec_i_narozy_jak_przed_galezia(nazwa):
    item, ksztalt, sd, oczekiwane = OCZEKIWANE_ZWYKLE[nazwa]
    assert _encje(_msp(item, _details_z_krawedzia(ksztalt, sd))) == oczekiwane


# --- Ponowna recenzja: gałąź awaryjna DXF z ostrzeżeniem w logu ---

def test_zepsute_wierzcholki_obrysu_daja_prostokat_z_wymiarow_i_ostrzezenie(caplog):
    with caplog.at_level('WARNING'):
        punkty = _obrys(_msp(_item(), _details('rectangular', {'vertices': [[0, 0], [1, 1]]})))
    assert [(round(x), round(y)) for x, y, _ in punkty] == [(0, 0), (1000, 0), (1000, 500), (0, 500)]
    assert any('zepsute wierzchołki' in r.getMessage() for r in caplog.records)


def test_brak_wierzcholkow_w_shape_data_bez_ostrzezenia(caplog):
    # Stare wyceny bez wierzchołków to zwykła droga (prostokąt z wymiarów), nie błąd danych
    with caplog.at_level('WARNING'):
        _msp(_item(), _details('rectangular', {'params': {}}))
    assert not any('zepsute wierzchołki' in r.getMessage() for r in caplog.records)
