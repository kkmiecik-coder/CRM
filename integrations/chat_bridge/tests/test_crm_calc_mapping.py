# -*- coding: utf-8 -*-
# Test: mapowanie PL->variant_code, walidacja finishing_id, cache /options (mock requests).
import os, tempfile
os.environ.setdefault("OLX_CLIENT_ID", "x")
os.environ.setdefault("OLX_CLIENT_SECRET", "x")
os.environ.setdefault("OLX_REFRESH_TOKEN", "x")
os.environ["CRM_API_BASE"] = "https://crm.test"
os.environ["CRM_BOT_API_KEY"] = "KEY"
os.environ["BRIDGE_DB"] = os.path.join(tempfile.mkdtemp(), "bridge_crmc.db")
import importlib
import config; importlib.reload(config)
crm = importlib.import_module("bots.crm_calc"); importlib.reload(crm)


class _Resp:
    def __init__(self, status=200, payload=None):
        self.status_code = status
        self._payload = payload or {}
        self.text = ""
    def json(self):
        return self._payload


def test_variant_code_podstawowy():
    assert crm.variant_code("dąb", "lita", "A/B") == "dab-lity-ab"
    assert crm.variant_code("Dąb", "mikrowczep", "B/B") == "dab-micro-bb"
    assert crm.variant_code("jesion", "lity", "AB") == "jes-lity-ab"


def test_variant_code_niepelne_lub_nieistniejace():
    assert crm.variant_code("dąb", "", "A/B") is None          # brak technologii
    assert crm.variant_code("jesion", "lita", "B/B") is None    # kombinacja spoza mapy (jesion B/B)
    assert crm.variant_code("buk", "lita", "A/B lub B/B") is None  # niejednoznaczna klasa


def test_valid_finishing_id():
    opts = {"finishing_options": [{"id": 7, "full_path": "Olejowanie/Bezbarwne"},
                                  {"id": 9, "full_path": "Lakierowane/Mat"}]}
    assert crm.valid_finishing_id(7, opts) is True
    assert crm.valid_finishing_id(99, opts) is False


def test_get_options_cache(monkeypatch):
    calls = {"n": 0}
    def fake_get(url, headers=None, timeout=None):
        calls["n"] += 1
        assert headers.get("X-Bot-Api-Key") == "KEY"
        return _Resp(200, {"ok": True, "finishing_options": [], "client_types": ["Klient indywidualny"]})
    monkeypatch.setattr(crm.requests, "get", fake_get)
    crm._reset_cache()
    a = crm.get_options()
    b = crm.get_options()   # drugie z cache — bez kolejnego GET
    assert a is b or a == b
    assert calls["n"] == 1


def test_get_options_blad_zwraca_puste(monkeypatch):
    def fake_get(url, headers=None, timeout=None):
        return _Resp(500, {})
    monkeypatch.setattr(crm.requests, "get", fake_get)
    crm._reset_cache()
    assert crm.get_options() == {}
