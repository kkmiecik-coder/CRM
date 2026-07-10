# -*- coding: utf-8 -*-
# Test obrazow: klient stock (Pexels) pobiera zdjecie, hero robi fallback na AI, miniatura przez Pillow.
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


def test_stock_pobiera_zdjecie(monkeypatch):
    monkeypatch.setattr(stock, "STOCK_API_KEY", "key")
    monkeypatch.setattr(stock, "STOCK_PROVIDER", "pexels")
    def fake_get(url, **kw):
        if "search" in url:
            return FakeResp(200, {"photos": [{"src": {"large": "https://img/x.jpg"}}]})
        return FakeResp(200, content=_png_bytes())
    monkeypatch.setattr(stock.requests, "get", fake_get)
    out = stock.search_photo("blat dębowy")
    assert out is not None
    data, ext = out
    assert data and ext in ("jpg", "jpeg", "png")


def test_stock_bez_klucza_zwraca_none(monkeypatch):
    monkeypatch.setattr(stock, "STOCK_API_KEY", None)
    assert stock.search_photo("x") is None


def test_hero_fallback_na_ai(monkeypatch):
    monkeypatch.setattr(images.stock, "search_photo", lambda q: None)  # stock pusty
    monkeypatch.setattr(images, "IMAGE_PROVIDER", "openai")
    monkeypatch.setattr(images, "_openai_image", lambda q: (_png_bytes(), "png"))
    out = images.acquire_hero("blat dębowy")
    assert out is not None and out[1] == "png"


def test_hero_bez_fallbacku_zwraca_none(monkeypatch):
    monkeypatch.setattr(images.stock, "search_photo", lambda q: None)
    monkeypatch.setattr(images, "IMAGE_PROVIDER", "none")
    assert images.acquire_hero("x") is None


def test_make_thumb_zmniejsza(monkeypatch):
    out = images.make_thumb(_png_bytes(1200, 900), max_w=600)
    assert out is not None
    im = Image.open(io.BytesIO(out))
    assert im.width == 600
