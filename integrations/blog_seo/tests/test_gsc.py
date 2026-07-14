# -*- coding: utf-8 -*-
# Test zrodla GSC: filtr striking distance + prog wyswietlen, scoring, wylaczenie, never-raises.
import importlib
gsc = importlib.import_module("signals.gsc")


class _Resp:
    def __init__(self, payload):
        self._p = payload
    def json(self):
        return self._p


_ROWS = {"rows": [
    {"keys": ["blat debowy jak czyscic"], "impressions": 500, "position": 9.0},   # w zakresie -> wchodzi
    {"keys": ["blat debowy"], "impressions": 5, "position": 8.0},                  # za malo wyswietlen -> out
    {"keys": ["blaty drewniane"], "impressions": 900, "position": 2.0},           # pozycja < POS_MIN -> out
    {"keys": ["schody debowe cena"], "impressions": 300, "position": 25.0},       # pozycja > POS_MAX -> out
]}


def _enable(monkeypatch):
    monkeypatch.setattr(gsc, "GSC_ENABLED", 1)
    monkeypatch.setattr(gsc, "GSC_CREDENTIALS_JSON", "/tmp/key.json")
    monkeypatch.setattr(gsc, "GSC_MIN_IMPRESSIONS", 20)
    monkeypatch.setattr(gsc, "GSC_POS_MIN", 6)
    monkeypatch.setattr(gsc, "GSC_POS_MAX", 20)
    monkeypatch.setattr(gsc, "_access_token", lambda: "tok")


def test_fetch_filtruje_i_scoruje(monkeypatch):
    _enable(monkeypatch)
    monkeypatch.setattr(gsc.requests, "post", lambda *a, **k: _Resp(_ROWS))
    out = gsc.fetch_gsc_candidates()
    qs = [c["query"] for c in out]
    assert qs == ["blat debowy jak czyscic"]      # tylko wiersz w striking distance z progiem
    assert out[0]["source"] == "gsc" and out[0]["score"] > 0


def test_fetch_wylaczone(monkeypatch):
    monkeypatch.setattr(gsc, "GSC_ENABLED", 0)
    assert gsc.fetch_gsc_candidates() == []


def test_fetch_bez_kluczy(monkeypatch):
    monkeypatch.setattr(gsc, "GSC_ENABLED", 1)
    monkeypatch.setattr(gsc, "GSC_CREDENTIALS_JSON", None)
    assert gsc.fetch_gsc_candidates() == []       # brak konta uslugowego -> []


def test_fetch_blad_nie_rzuca(monkeypatch):
    _enable(monkeypatch)
    def boom(*a, **k):
        raise RuntimeError("api down")
    monkeypatch.setattr(gsc.requests, "post", boom)
    assert gsc.fetch_gsc_candidates() == []       # never-raises
