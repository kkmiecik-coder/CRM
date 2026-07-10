# -*- coding: utf-8 -*-
# Test katalogu: budowa przyjaznych URL PrestaShop oraz mapowanie wierszy zapytan (polaczenie atrapa).
import importlib
catalog = importlib.import_module("catalog")


def test_product_url():
    assert catalog.product_url(67, "blaty-drewniane") == "https://woodpower.pl/67-blaty-drewniane"


def test_category_url():
    assert catalog.category_url(11, "blaty") == "https://woodpower.pl/11-blaty"


def test_get_products_mapuje_wiersze(monkeypatch):
    rows = [{"id_product": 67, "name": "Blat dębowy", "link_rewrite": "blaty-drewniane",
             "category": "Blaty", "price": 1200.0, "img": "67-home_default"}]
    monkeypatch.setattr(catalog.shop_db, "query", lambda sql, params=(): rows)
    out = catalog.get_products(limit=10)
    assert out[0]["url"] == "https://woodpower.pl/67-blaty-drewniane"
    assert out[0]["name"] == "Blat dębowy"
    assert out[0]["category"] == "Blaty"
    assert "http" in out[0]["image_url"]


def test_get_categories_mapuje_wiersze(monkeypatch):
    rows = [{"id_category": 11, "name": "Blaty", "link_rewrite": "blaty"}]
    monkeypatch.setattr(catalog.shop_db, "query", lambda sql, params=(): rows)
    out = catalog.get_categories()
    assert out[0]["url"] == "https://woodpower.pl/11-blaty"
    assert out[0]["name"] == "Blaty"
