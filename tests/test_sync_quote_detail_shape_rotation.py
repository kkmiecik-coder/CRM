# -*- coding: utf-8 -*-
"""Kopiowanie pól wizualnych z wyceny do pozycji produkcyjnej.

Ta funkcja nie miała pokrycia i dlatego zmiana nazwy kolumny w wycenach
(lamella_direction -> shape_rotation) wywaliła synchronizację z BaseLinkera
po cichu — pakiet testów przeszedł na zielono. Test pilnuje kontraktu
między QuoteItemDetails a prod_products.
"""

from types import SimpleNamespace

from modules.production.services.sync_service import BaselinkerSyncService


def _detail(**nadpisania):
    dane = dict(
        id=42,
        shape_svg="<svg/>",
        shape="polygon",
        shape_rotation=37,
        edges_type=None,
        edges_r_value=None,
        edges_angle_value=None,
        edges_svg=None,
    )
    dane.update(nadpisania)
    return SimpleNamespace(**dane)


def test_kopiuje_kat_obrotu_z_wyceny():
    service = BaselinkerSyncService()
    product_data = {}

    service._apply_quote_detail_to_product_data(product_data, _detail())

    assert product_data["shape_rotation"] == 37
    assert product_data["shape_svg"] == "<svg/>"
    assert product_data["shape"] == "polygon"
    assert product_data["quote_item_detail_id"] == 42


def test_brak_kata_nie_dodaje_klucza():
    service = BaselinkerSyncService()
    product_data = {}

    service._apply_quote_detail_to_product_data(product_data, _detail(shape_rotation=None))

    assert "shape_rotation" not in product_data


def test_zero_stopni_jest_kopiowane():
    """0 to prawidłowy kąt (brak obrotu), nie brak wartości — warunek
    musi sprawdzać `is not None`, a nie prawdziwość."""
    service = BaselinkerSyncService()
    product_data = {}

    service._apply_quote_detail_to_product_data(product_data, _detail(shape_rotation=0))

    assert product_data["shape_rotation"] == 0
