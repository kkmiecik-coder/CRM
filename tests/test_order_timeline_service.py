"""Testy serwisu linii czasu produkcji (order_timeline_service)."""
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.production.services import order_timeline_service as ots


def _cfg(species='Dąb', technology='lity', wood_class='A/B'):
    return SimpleNamespace(species=species, technology=technology, wood_class=wood_class)


def _prod(status, cut_to_size=True, finish='lakierowane', edge=False,
          spid='25_05248_1', length=200, width=80, thickness=4, cfg=None):
    return SimpleNamespace(
        current_status=status,
        cut_to_size=cut_to_size,
        parsed_finish_type=finish,
        parsed_edge_processing=edge,
        short_product_id=spid,
        parsed_length_cm=length,
        parsed_width_cm=width,
        parsed_thickness_cm=thickness,
        configuration=cfg or _cfg(),
    )


# --- trasa produktu ---

def test_route_full_path_when_cut_to_size_and_painted():
    p = _prod('czeka_na_wyciecie', cut_to_size=True, finish='lakierowane')
    assert ots.product_in_route(p, 'entry') is True
    assert ots.product_in_route(p, 'gluing') is True
    assert ots.product_in_route(p, 'formatting') is True
    assert ots.product_in_route(p, 'finishing') is True
    assert ots.product_in_route(p, 'painting') is True
    assert ots.product_in_route(p, 'packaging') is True


def test_route_skips_formatting_and_finishing_when_not_cut_to_size():
    p = _prod('czeka_na_wyciecie', cut_to_size=False, finish='surowe')
    assert ots.product_in_route(p, 'formatting') is False
    assert ots.product_in_route(p, 'finishing') is False
    assert ots.product_in_route(p, 'painting') is False
    assert ots.product_in_route(p, 'packaging') is True


def test_route_skips_finishing_when_raw_without_edge():
    p = _prod('czeka_na_wyciecie', cut_to_size=True, finish='surowe', edge=False)
    assert ots.product_in_route(p, 'formatting') is True
    assert ots.product_in_route(p, 'finishing') is False
    assert ots.product_in_route(p, 'painting') is False


def test_route_keeps_finishing_when_raw_with_edge():
    p = _prod('czeka_na_wyciecie', cut_to_size=True, finish='surowe', edge=True)
    assert ots.product_in_route(p, 'finishing') is True
    assert ots.product_in_route(p, 'painting') is False


# --- kolor kropki ---

def test_color_gray_when_none_arrived():
    products = [_prod('czeka_na_wyciecie'), _prod('czeka_na_wyciecie')]
    assert ots.station_color('finishing', products) == 'gray'


def test_color_green_when_all_left():
    products = [_prod('spakowane'), _prod('spakowane')]
    assert ots.station_color('gluing', products) == 'green'


def test_color_yellow_when_one_currently_there():
    products = [_prod('czeka_na_sklejanie'), _prod('spakowane')]
    assert ots.station_color('gluing', products) == 'yellow'


def test_color_yellow_when_mixed_left_and_before_none_at():
    products = [_prod('czeka_na_formatowanie'), _prod('czeka_na_wyciecie')]
    assert ots.station_color('gluing', products) == 'yellow'


def test_color_none_hidden_when_no_product_routed():
    products = [_prod('czeka_na_wyciecie', cut_to_size=True, finish='surowe', edge=False)]
    routed = [p for p in products if ots.product_in_route(p, 'finishing')]
    assert ots.station_color('finishing', routed) is None


# --- payload + status zamówienia ---

def test_build_payload_hides_empty_stations_and_marks_active():
    products = [
        _prod('czeka_na_sklejanie', cut_to_size=False, finish='surowe', spid='25_1_1'),
    ]
    stations = ots.build_timeline_payload(products)
    keys = [s['code'] for s in stations]
    assert 'formatting' not in keys and 'finishing' not in keys and 'painting' not in keys
    gluing = next(s for s in stations if s['code'] == 'gluing')
    assert gluing['color'] == 'yellow'
    assert gluing['active'] is True
    assert gluing['products_here'][0]['short_product_id'] == '25_1_1'


def test_products_here_only_on_active_station():
    products = [_prod('czeka_na_sklejanie', spid='25_1_1')]
    stations = ots.build_timeline_payload(products)
    entry = next(s for s in stations if s['code'] == 'entry')
    assert entry['active'] is False
    assert entry['products_here'] == []


def test_order_status_single():
    products = [_prod('czeka_na_sklejanie'), _prod('czeka_na_sklejanie')]
    badge = ots.order_status_badge(products)
    assert badge['label'] == 'Czeka na sklejanie'
    assert badge['badge_class'] == 'badge-gluing'


def test_order_status_mixed():
    products = [_prod('spakowane'), _prod('czeka_na_sklejanie'), _prod('czeka_na_wyciecie')]
    badge = ots.order_status_badge(products)
    assert badge['label'] == 'Różne (1/3)'
    assert badge['badge_class'] == 'badge-mixed'


def test_anulowane_excluded_from_timeline():
    products = [_prod('anulowane'), _prod('czeka_na_sklejanie', spid='25_1_2')]
    stations = ots.build_timeline_payload(products)
    gluing = next(s for s in stations if s['code'] == 'gluing')
    assert [p['short_product_id'] for p in gluing['products_here']] == ['25_1_2']


def test_format_dimension_polish_comma():
    assert ots.format_dimension(2.5) == '2,5'
    assert ots.format_dimension(180) == '180'
    assert ots.format_dimension(None) == '-'
