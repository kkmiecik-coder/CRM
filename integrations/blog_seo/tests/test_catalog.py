# -*- coding: utf-8 -*-
# Test katalogu: URL kategorii + obrazu, mapowanie get_categories/search_categories, uproszczone produkty.
import importlib
catalog = importlib.import_module("catalog")


def test_category_url():
    assert catalog.category_url(71, "blaty-debowe") == "https://woodpower.pl/71-blaty-debowe"


def test_category_image_url():
    assert catalog.category_image_url(73) == "https://woodpower.pl/img/c/73.jpg"


def test_get_categories_mapuje(monkeypatch):
    rows = [{"id_category": 71, "name": "Dębowe", "link_rewrite": "blaty-debowe"}]
    monkeypatch.setattr(catalog.shop_db, "query", lambda sql, params=(): rows)
    out = catalog.get_categories()
    assert out[0]["url"] == "https://woodpower.pl/71-blaty-debowe"
    assert out[0]["image_url"] == "https://woodpower.pl/img/c/71.jpg"
    assert out[0]["link_rewrite"] == "blaty-debowe"
    assert out[0]["name"] == "Dębowe"


def test_search_categories_pyta_po_slowach(monkeypatch):
    captured = {}
    def fake_query(sql, params=()):
        captured["sql"] = sql; captured["params"] = params
        return [{"id_category": 71, "name": "Dębowe", "link_rewrite": "blaty-debowe"}]
    monkeypatch.setattr(catalog.shop_db, "query", fake_query)
    out = catalog.search_categories(["blat", "debowy"], limit=10)
    assert out[0]["url"] == "https://woodpower.pl/71-blaty-debowe"
    # zapytanie musi filtrowac po slowach (LIKE) i miec je w parametrach
    assert "LIKE" in captured["sql"]
    assert any("blat" in str(p) for p in captured["params"])
    assert any("debowy" in str(p) for p in captured["params"])


def test_search_categories_puste_slowa_zwraca_puste(monkeypatch):
    monkeypatch.setattr(catalog.shop_db, "query", lambda sql, params=(): [{"x": 1}])
    assert catalog.search_categories([]) == []


def test_get_products_uproszczony(monkeypatch):
    rows = [{"name": "Blat dębowy 100x100", "category": "Blaty"}]
    monkeypatch.setattr(catalog.shop_db, "query", lambda sql, params=(): rows)
    out = catalog.get_products(limit=10)
    assert out[0] == {"name": "Blat dębowy 100x100", "category": "Blaty"}
