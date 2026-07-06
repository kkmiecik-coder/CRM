# -*- coding: utf-8 -*-
# Test: pobranie obrazu z Chatwoota do data-URI + doklejenie do wiadomosci multimodalnej.
import os
os.environ.setdefault("OLX_CLIENT_ID", "x")
os.environ.setdefault("OLX_CLIENT_SECRET", "x")
os.environ.setdefault("OLX_REFRESH_TOKEN", "x")
import importlib
vision = importlib.import_module("bots.vision")


class FakeResp:
    def __init__(self, content=b"", code=200, ctype="image/png"):
        self.content = content; self.status_code = code
        self.headers = {"Content-Type": ctype}


def test_to_data_uri_buduje_base64(monkeypatch):
    monkeypatch.setattr(vision.requests, "get", lambda u, headers=None, timeout=None: FakeResp(b"ABC"))
    du = vision.to_data_uri("http://cw/x.png")
    assert du == "data:image/png;base64,QUJD"  # base64('ABC')


def test_to_data_uri_kod_bledu_none(monkeypatch):
    monkeypatch.setattr(vision.requests, "get", lambda u, headers=None, timeout=None: FakeResp(code=404))
    assert vision.to_data_uri("http://cw/x.png") is None


def test_to_data_uri_wyjatek_none(monkeypatch):
    """requests.get rzuca (np. ConnectionError) -> None, nie propaguje (zasada mostka)."""
    def _boom(*a, **k):
        raise requests.exceptions.ConnectionError("brak sieci")
    monkeypatch.setattr(vision.requests, "get", _boom)
    assert vision.to_data_uri("http://cw/x.png") is None


def test_to_data_uri_za_duzy_obraz_none(monkeypatch):
    """Obraz powyzej _MAX_IMG_BYTES -> None (nie wysylamy gigantycznego base64 do OpenAI)."""
    big = b"x" * (vision._MAX_IMG_BYTES + 1)
    monkeypatch.setattr(vision.requests, "get", lambda u, headers=None, timeout=None: FakeResp(big))
    assert vision.to_data_uri("http://cw/big.png") is None


def test_attach_images_dokleja_wiadomosc_user(monkeypatch):
    monkeypatch.setattr(vision, "to_data_uri", lambda u: "data:image/png;base64,QUJD")
    msgs = [{"role": "system", "content": "S"}, {"role": "user", "content": "co to?"}]
    out = vision.attach_images(msgs, ["http://cw/1.png"])
    assert out[-1]["role"] == "user"
    assert out[-1]["content"][0]["type"] == "image_url"
    assert out[-1]["content"][0]["image_url"]["url"] == "data:image/png;base64,QUJD"


def test_attach_images_pusta_lista_bez_zmian(monkeypatch):
    msgs = [{"role": "user", "content": "x"}]
    assert vision.attach_images(msgs, []) == msgs


def test_attach_images_limit(monkeypatch):
    monkeypatch.setattr(vision, "to_data_uri", lambda u: "data:image/png;base64,QUJD")
    out = vision.attach_images([{"role": "user", "content": "x"}],
                               ["a", "b", "c"], limit=2)
    assert len(out[-1]["content"]) == 2
