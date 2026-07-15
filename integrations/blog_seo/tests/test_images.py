# -*- coding: utf-8 -*-
# Test obrazow: stock zwraca 3-krotke z atrybucja; hero przenosi atrybucje; fallback AI attribution=None.
import io
import importlib
from PIL import Image
stock = importlib.import_module("stock")
images = importlib.import_module("images")


def _png_bytes(w=1000, h=800):
    buf = io.BytesIO(); Image.new("RGB", (w, h), (120, 90, 60)).save(buf, "PNG"); return buf.getvalue()


class FakeResp:
    def __init__(self, status_code, payload=None, content=b""):
        self.status_code = status_code; self._p = payload; self.content = content
    def json(self): return self._p


def test_stock_pexels_zwraca_atrybucje(monkeypatch):
    monkeypatch.setattr(stock, "STOCK_API_KEY", "key")
    monkeypatch.setattr(stock, "STOCK_PROVIDER", "pexels")
    def fake_get(url, **kw):
        if "search" in url:
            return FakeResp(200, {"photos": [{"src": {"large": "https://img/x.jpg"},
                "photographer": "Jan Kowalski", "photographer_url": "https://pexels.com/@jan",
                "url": "https://pexels.com/photo/1"}]})
        return FakeResp(200, content=_png_bytes())
    monkeypatch.setattr(stock.requests, "get", fake_get)
    out = stock.search_photo("blat dębowy")
    assert out is not None
    data, ext, attr = out
    assert data and ext in ("jpg", "png")
    assert attr["photographer"] == "Jan Kowalski"
    assert attr["photographer_url"] == "https://pexels.com/@jan"
    assert attr["photo_url"] == "https://pexels.com/photo/1"
    assert attr["source"] == "Pexels"


def test_stock_bez_klucza_none(monkeypatch):
    monkeypatch.setattr(stock, "STOCK_API_KEY", None)
    assert stock.search_photo("x") is None


def test_hero_przenosi_atrybucje(monkeypatch):
    monkeypatch.setattr(images.stock, "search_photo",
                        lambda q, exclude=None: (_png_bytes(), "jpg", {"photographer": "X", "source": "Pexels"}))
    out = images.acquire_hero("blat")
    assert out[2]["photographer"] == "X"


def test_hero_fallback_ai_attribution_none(monkeypatch):
    monkeypatch.setattr(images.stock, "search_photo", lambda q, exclude=None: None)
    monkeypatch.setattr(images, "IMAGE_PROVIDER", "openai")
    monkeypatch.setattr(images, "_openai_image", lambda q: (_png_bytes(), "png", None))
    out = images.acquire_hero("blat")
    assert out is not None and out[2] is None


def test_hero_bez_fallbacku_none(monkeypatch):
    monkeypatch.setattr(images.stock, "search_photo", lambda q, exclude=None: None)
    monkeypatch.setattr(images, "IMAGE_PROVIDER", "none")
    assert images.acquire_hero("x") is None


def test_stock_query_mapuje_produkt():
    # Polski temat -> trafna angielska fraza (koniec falszywego przyjaciela "parapet").
    assert images._stock_query("Parapety drewniane na wymiar jak wybrać") == "wooden window sill interior"
    assert images._stock_query("Blaty dębowe do kuchni") == "wooden kitchen countertop"
    assert images._stock_query("Stopnie na schody jakie wybrać") == "wooden staircase interior"
    assert images._stock_query("Trepy dębowe") == "wooden staircase interior"
    assert images._stock_query("Coś zupełnie innego") == "oak wood interior"     # fallback
    assert images._stock_query("") == "oak wood interior"
    # granica slowa: "schod" nie moze trafiac w "wschod" (wschod) -> fallback, nie schody
    assert images._stock_query("Meble inspirowane stylem ze wschodu") == "oak wood interior"


def test_hero_przekazuje_exclude_do_stocku(monkeypatch):
    seen = {}
    def fake_search(q, exclude=None):
        seen["q"] = q; seen["exclude"] = exclude
        return (_png_bytes(), "jpg", {"photographer": "X", "source": "Pexels"})
    monkeypatch.setattr(images.stock, "search_photo", fake_search)
    images.acquire_hero("Parapety drewniane na wymiar", exclude={"https://pexels.com/photo/1"})
    assert seen["q"] == "wooden window sill interior"                # zbudowane EN, nie polski tytul
    assert seen["exclude"] == {"https://pexels.com/photo/1"}


def test_stock_pomija_uzyte(monkeypatch):
    monkeypatch.setattr(stock, "STOCK_API_KEY", "key")
    monkeypatch.setattr(stock, "STOCK_PROVIDER", "pexels")
    def fake_get(url, **kw):
        if "search" in url:
            return FakeResp(200, {"photos": [
                {"src": {"large": "https://img/1.jpg"}, "photographer": "A",
                 "photographer_url": "https://p/@a", "url": "https://pexels.com/photo/1"},
                {"src": {"large": "https://img/2.jpg"}, "photographer": "B",
                 "photographer_url": "https://p/@b", "url": "https://pexels.com/photo/2"}]})
        return FakeResp(200, content=_png_bytes())
    monkeypatch.setattr(stock.requests, "get", fake_get)
    out = stock.search_photo("blat", exclude={"https://pexels.com/photo/1"})
    assert out is not None
    assert out[2]["photo_url"] == "https://pexels.com/photo/2"   # pierwszy pominiety, wybrany drugi


def test_stock_wszystkie_uzyte_none(monkeypatch):
    monkeypatch.setattr(stock, "STOCK_API_KEY", "key")
    monkeypatch.setattr(stock, "STOCK_PROVIDER", "pexels")
    def fake_get(url, **kw):
        if "search" in url:
            return FakeResp(200, {"photos": [
                {"src": {"large": "https://img/1.jpg"}, "url": "https://pexels.com/photo/1"}]})
        return FakeResp(200, content=_png_bytes())
    monkeypatch.setattr(stock.requests, "get", fake_get)
    assert stock.search_photo("blat", exclude={"https://pexels.com/photo/1"}) is None  # brak nieuzytych


def test_make_thumb_zmniejsza():
    out = images.make_thumb(_png_bytes(1200, 900), max_w=600)
    im = Image.open(io.BytesIO(out))
    assert im.width == 600
