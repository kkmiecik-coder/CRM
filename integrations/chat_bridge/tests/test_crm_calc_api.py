# -*- coding: utf-8 -*-
# Test: build_products + wywolania /calculate /clients /quotes (mock requests).
import os, tempfile
os.environ.setdefault("OLX_CLIENT_ID", "x")
os.environ.setdefault("OLX_CLIENT_SECRET", "x")
os.environ.setdefault("OLX_REFRESH_TOKEN", "x")
os.environ["CRM_API_BASE"] = "https://crm.test"
os.environ["CRM_BOT_API_KEY"] = "KEY"
os.environ["BOT_QUOTE_CLIENT_TYPE"] = "Klient indywidualny"
os.environ["BRIDGE_DB"] = os.path.join(tempfile.mkdtemp(), "bridge_crma.db")
import importlib
import config; importlib.reload(config)
crm = importlib.import_module("bots.crm_calc"); importlib.reload(crm)

_OPTS = {"finishing_options": [{"id": 7, "full_path": "Olejowanie/Bezbarwne"}],
         "client_types": ["Klient indywidualny"]}


class _Resp:
    def __init__(self, status=200, payload=None):
        self.status_code = status; self._payload = payload or {}; self.text = ""
    def json(self): return self._payload


def _poz(**kw):
    base = {"id": "1", "produkt": "blat", "dlugosc": "200", "szerokosc": "60",
            "grubosc": "4", "gatunek": "dąb", "technologia": "lita", "klasa": "A/B",
            "ilosc": "2", "wykonczenie": "olejowane", "finishing_id": 7}
    base.update(kw); return base


def test_build_products_mapuje_pozycje():
    products, braki = crm.build_products([_poz()], _OPTS)
    assert braki == []
    p = products[0]
    assert p["length"] == 200.0 and p["width"] == 60.0 and p["thickness"] == 4.0
    assert p["quantity"] == 2
    assert p["selected_variant"] == "dab-lity-ab"
    assert p["finishing_option_id"] == 7
    assert p["finishing_type"] == "Olejowane"
    assert p["index"] == 1


def test_build_products_surowe_bez_id():
    products, braki = crm.build_products([_poz(wykonczenie="surowe", finishing_id=None)], _OPTS)
    assert braki == []
    assert products[0]["finishing_type"] == "Surowe"
    assert products[0].get("finishing_option_id") in (None, 0)


def test_build_products_zle_finishing_id_daje_brak():
    products, braki = crm.build_products([_poz(finishing_id=999)], _OPTS)
    assert any("wykończ" in powod.lower() or "finishing" in powod.lower() for _, powod in braki)


_OPTS_LAKIER = {"finishing_options": [
    {"id": 7, "full_path": "Olejowanie/Bezbarwne"},
    {"id": 21, "full_path": "Lakierowanie/Połysk", "price_netto": 81.30},
    {"id": 22, "full_path": "Lakierowanie/Bez ceny"},  # brak price_netto -> nie moze wycenic
], "client_types": ["Klient indywidualny"]}


def test_build_products_lakier_z_wyceniona_opcja_ustawia_gloss_level():
    products, braki = crm.build_products(
        [_poz(wykonczenie="lakierowane", finishing_id=21)], _OPTS_LAKIER)
    assert braki == []
    p = products[0]
    assert p["finishing_type"] == "Lakierowane"
    assert p["finishing_option_id"] == 21
    assert str(p.get("finishing_gloss_level") or "").strip()   # truthy -> guard w calculate_finishing przejdzie


def test_build_products_lakier_bez_ceny_daje_brak_i_brak_produktu():
    products, braki = crm.build_products(
        [_poz(wykonczenie="lakierowane", finishing_id=22)], _OPTS_LAKIER)
    assert products == []
    assert any("lakier" in powod.lower() for _, powod in braki)


def test_calculate_wysyla_client_type_i_zwraca_json(monkeypatch):
    captured = {}
    def fake_post(url, headers=None, json=None, timeout=None):
        captured["url"] = url; captured["body"] = json
        return _Resp(200, {"ok": True, "totals": {"total_brutto": 1230.0}, "missing_fields": []})
    monkeypatch.setattr(crm.requests, "post", fake_post)
    out = crm.calculate([_poz()], _OPTS)
    assert out["ok"] is True
    assert captured["body"]["client_type"] == "Klient indywidualny"
    assert captured["url"].endswith("/api/bot/calculate")


def test_find_or_create_client(monkeypatch):
    def fake_post(url, headers=None, json=None, timeout=None):
        assert url.endswith("/api/bot/clients/find-or-create")
        return _Resp(200, {"ok": True, "client": {"id": 42}})
    monkeypatch.setattr(crm.requests, "post", fake_post)
    out = crm.find_or_create_client("a@b.pl", None, "Jan")
    assert out["client"]["id"] == 42


def test_create_quote(monkeypatch):
    def fake_post(url, headers=None, json=None, timeout=None):
        assert url.endswith("/api/bot/quotes")
        assert json["client_id"] == 42
        assert json["quote_client_type"] == "Klient indywidualny" or json["client_type"] == "Klient indywidualny"
        return _Resp(200, {"ok": True, "quote_number": "W/2026/1", "public_url": "https://crm/q/abc"})
    monkeypatch.setattr(crm.requests, "post", fake_post)
    out = crm.create_quote([_poz()], _OPTS, client_id=42)
    assert out["public_url"].endswith("/q/abc")
