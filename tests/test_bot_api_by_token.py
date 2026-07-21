# -*- coding: utf-8 -*-
"""Bot API — odczyt wyceny po publicznym tokenie (GET /api/bot/quotes/by-token/<token>).

Serializacja jest czystą funkcją (DB pobiera router), więc testujemy ją bez app/DB —
obiekty item/detail podajemy jako lekkie SimpleNamespace (jak MagicMock w innych testach bota).
"""
from datetime import datetime
from types import SimpleNamespace

from modules.calculator.routers.bot_api import (
    _holes_count_from_shape_data,
    _edges_for_shop,
    _serialize_item_for_shop,
    _serialize_quote_for_shop,
    _shop_quote_status_fields,
)


# --- _holes_count_from_shape_data: liczba otworów jak w _payload_to_calc_request ---

def test_holes_count_brak_danych():
    assert _holes_count_from_shape_data(None) == 0
    assert _holes_count_from_shape_data('') == 0


def test_holes_count_z_dict():
    assert _holes_count_from_shape_data({'holes': [{'x': 1}, {'x': 2}]}) == 2


def test_holes_count_z_json_stringa():
    assert _holes_count_from_shape_data('{"holes": [{"x": 1}]}') == 1


def test_holes_count_bez_klucza_holes():
    assert _holes_count_from_shape_data({'params': {}}) == 0


def test_holes_count_zepsuty_json_nie_wywala():
    assert _holes_count_from_shape_data('{niepoprawny') == 0


# --- _edges_for_shop: mapowanie zapisanych krawędzi na format /calculate ---

def test_edges_for_shop_brak():
    assert _edges_for_shop(None) == []
    assert _edges_for_shop([]) == []


def test_edges_for_shop_nie_lista():
    assert _edges_for_shop({'letter': 'A'}) == []


def test_edges_for_shop_normalizuje_klucze():
    src = [{'letter': 'A', 'type': 'round', 'r_value': 5, 'angle_value': None,
            'length_cm': 99, 'extra': 'x'}]
    assert _edges_for_shop(src) == [
        {'letter': 'A', 'type': 'round', 'r_value': 5, 'angle_value': None}]


def test_edges_for_shop_letter_z_id_gdy_brak_letter():
    src = [{'id': 'KG', 'type': 'chamfer', 'angle_value': 45}]
    out = _edges_for_shop(src)
    assert out[0]['letter'] == 'KG'
    assert out[0]['type'] == 'chamfer'
    assert out[0]['angle_value'] == 45
    assert out[0]['r_value'] is None


# --- _serialize_item_for_shop: jedna wybrana pozycja w formacie /calculate ---

def _item(**kw):
    base = dict(variant_code='dab-lity-ab', length_cm=100, width_cm=50, thickness_cm=3,
                price_netto=159.90, price_brutto=196.68, product_index=1)
    base.update(kw)
    return SimpleNamespace(**base)


def _detail(**kw):
    base = dict(product_type='blat', quantity=2, shape='rectangular', shape_data=None,
                finishing_type='Lakierowane', finishing_variant='Bezbarwne',
                finishing_gloss_level='Matowy',
                finishing_price_netto=0.0, finishing_price_brutto=0.0,
                edges_price_netto=0.0, edges_price_brutto=0.0,
                edges_config=[{'letter': 'A', 'type': 'round', 'r_value': 5, 'angle_value': None}])
    base.update(kw)
    return SimpleNamespace(**base)


def test_serialize_item_pelne_dane():
    # Wykonczenie + krawedzie doliczane do total (QuoteItem.price_* to sam material).
    out = _serialize_item_for_shop(_item(), _detail(
        finishing_price_netto=120.0, finishing_price_brutto=147.60,
        edges_price_netto=36.0, edges_price_brutto=44.28))
    assert out['product_type'] == 'blat'
    assert out['length'] == 100.0 and out['width'] == 50.0 and out['thickness'] == 3.0
    assert out['quantity'] == 2
    assert out['selected_variant'] == 'dab-lity-ab'
    # rozkład wariantu z VARIANT_MAPPING (pole pomocnicze do renderu strony)
    assert out['species'] == 'Dąb'
    assert out['technology'] == 'Lity'
    assert out['wood_class'] == 'A/B'
    assert out['shape'] == 'rectangular'
    assert out['holes_count'] == 0
    assert out['finishing_type'] == 'Lakierowane'
    assert out['finishing_variant'] == 'Bezbarwne'
    assert out['finishing_option_id'] is None      # nieprzechowywane w CRM
    assert out['finishing_gloss_level'] == 'Matowy'
    assert out['edges'] == [{'letter': 'A', 'type': 'round', 'r_value': 5, 'angle_value': None}]
    # unit = material/szt.; finishing/edges = za cala pozycje; total = material×ilosc + finishing + edges
    assert out['unit_netto'] == 159.9
    assert out['unit_brutto'] == 196.68
    assert out['finishing_netto'] == 120.0 and out['finishing_brutto'] == 147.6
    assert out['edges_netto'] == 36.0 and out['edges_brutto'] == 44.28
    assert out['total_netto'] == 475.8            # 159.90*2 + 120.0 + 36.0
    assert out['total_brutto'] == 585.24          # 196.68*2 + 147.60 + 44.28


def test_serialize_item_bez_detalu():
    """Pozycja bez QuoteItemDetails (np. wycena spoza sklepu) — bezpieczne wartości domyślne."""
    out = _serialize_item_for_shop(
        _item(variant_code='buk-micro-ab', price_netto=100.0, price_brutto=123.0), None)
    assert out['product_type'] is None
    assert out['quantity'] == 1
    assert out['shape'] == 'rectangular'
    assert out['holes_count'] == 0
    assert out['finishing_type'] is None
    assert out['finishing_variant'] is None
    assert out['finishing_gloss_level'] is None
    assert out['edges'] == []
    assert out['finishing_netto'] == 0.0 and out['edges_netto'] == 0.0
    assert out['species'] == 'Buk'
    assert out['technology'] == 'Mikrowczep'
    assert out['wood_class'] == 'A/B'
    assert out['total_netto'] == 100.0            # sam material (bez detalu = bez wykonczenia/krawedzi)
    assert out['total_brutto'] == 123.0


def test_serialize_item_nieznany_wariant_daje_none_w_rozkladzie():
    out = _serialize_item_for_shop(_item(variant_code='cos-dziwnego'), _detail())
    assert out['selected_variant'] == 'cos-dziwnego'
    assert out['species'] is None
    assert out['technology'] is None
    assert out['wood_class'] is None


def test_serialize_item_holes_z_shape_data():
    out = _serialize_item_for_shop(
        _item(), _detail(shape_data='{"holes": [{"x": 1}, {"x": 2}, {"x": 3}]}'))
    assert out['holes_count'] == 3


# --- _serialize_quote_for_shop: pełna wycena (tylko wybrane warianty) + sumy ---

def test_serialize_quote_dwie_pozycje_i_sumy():
    items = [_item(product_index=1), _item(product_index=2, variant_code='dab-micro-ab',
                                           price_netto=200.0, price_brutto=246.0)]
    # Pozycja 1: material + wykonczenie 10/12.30 + krawedzie 5/6.15 ; pozycja 2: sam material.
    details = {1: _detail(product_type='blat',
                          finishing_price_netto=10.0, finishing_price_brutto=12.30,
                          edges_price_netto=5.0, edges_price_brutto=6.15),
               2: _detail(product_type='schody', quantity=1,
                          edges_config=None, finishing_type=None,
                          finishing_variant=None, finishing_gloss_level=None)}
    out = _serialize_quote_for_shop('05/07/26/W', datetime(2026, 7, 17, 10, 30, 0),
                                    items, details)
    assert out['quote_number'] == '05/07/26/W'
    assert out['created_at'] == '2026-07-17T10:30:00'
    assert len(out['items']) == 2
    assert out['items'][0]['product_type'] == 'blat'
    assert out['items'][0]['finishing_netto'] == 10.0 and out['items'][0]['edges_netto'] == 5.0
    assert out['items'][1]['product_type'] == 'schody'
    assert out['items'][1]['quantity'] == 1
    assert out['items'][1]['edges'] == []
    # sumy = suma total pozycji (material×ilosc + wykonczenie + krawedzie, BEZ wysylki):
    # poz1 = 159.90*2 + 10 + 5 = 334.8 ; poz2 = 200.0*1 = 200.0
    assert out['totals']['total_netto'] == 534.8
    # poz1 = 196.68*2 + 12.30 + 6.15 = 411.81 ; poz2 = 246.0
    assert out['totals']['total_brutto'] == 657.81


def test_serialize_quote_created_at_none():
    out = _serialize_quote_for_shop('01/01/26/W', None, [], {})
    assert out['created_at'] is None
    assert out['items'] == []
    assert out['totals'] == {'total_netto': 0.0, 'total_brutto': 0.0}


# --- _shop_quote_status_fields: status / is_ordered / order_reference dla sklepu ---

def _quote_ns(**kw):
    base = dict(base_linker_order_id=None, status_id=1,
                quote_status=SimpleNamespace(name='Nowa wycena'))
    base.update(kw)
    return SimpleNamespace(**base)


def test_status_fields_niezamowiona():
    out = _shop_quote_status_fields(_quote_ns())
    assert out == {'status': 'Nowa wycena', 'is_ordered': False, 'order_reference': None}


def test_status_fields_zamowiona_po_base_linker_order_id():
    # Zaakceptowana (status 3), ale ma już zamówienie BL => is_ordered + referencja.
    out = _shop_quote_status_fields(_quote_ns(
        base_linker_order_id='WP123', status_id=3,
        quote_status=SimpleNamespace(name='Zaakceptowane')))
    assert out['is_ordered'] is True
    assert out['order_reference'] == 'WP123'
    assert out['status'] == 'Zaakceptowane'


def test_status_fields_zamowiona_po_statusie_4_bez_order_id():
    # Status „Zamówione" (id=4) bez base_linker_order_id => is_ordered, ale bez referencji.
    out = _shop_quote_status_fields(_quote_ns(
        status_id=4, quote_status=SimpleNamespace(name='Zamówione')))
    assert out['is_ordered'] is True
    assert out['order_reference'] is None


def test_status_fields_brak_relacji_statusu():
    out = _shop_quote_status_fields(_quote_ns(quote_status=None))
    assert out['status'] is None
    assert out['is_ordered'] is False
