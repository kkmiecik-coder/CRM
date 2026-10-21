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


def test_valid_finishing_id_zly_wpis_nie_rzuca():
    # Test: malformed catalog entries (id="abc", id=None) nie powinny rzucic wyjatku
    # Funkcja powinna przeskakiwac bledne wpisy i szukac pasujacych
    opts = {"finishing_options": [{"id": "abc"}, {"id": None}, {"id": 7, "full_path": "X"}]}
    assert crm.valid_finishing_id(7, opts) is True    # dobry wpis znaleziony mimo zepsutych
    assert crm.valid_finishing_id(9, opts) is False   # brak dopasowania, bez wyjatku


def _wariant(kod, pasma):
    return {"variant_code": kod, "thickness_bands": pasma}


def test_opis_dostepnosci_z_pasm_cennika():
    opis = crm.opis_dostepnosci({"variants": [
        _wariant("buk-lity-ab", [
            {"thickness_min": 0, "thickness_max": 2, "exact": False, "length_max": 240, "width_max": 120},
            {"thickness_min": 2.5, "thickness_max": 2.5, "exact": True, "length_max": 240, "width_max": 120},
            {"thickness_min": 2.8, "thickness_max": 2.8, "exact": True, "length_max": 240, "width_max": 120}]),
        _wariant("dab-lity-ab", [
            {"thickness_min": 3.01, "thickness_max": 12, "exact": False, "length_max": 265, "width_max": 120}]),
        _wariant("jes-micro-ab", [
            {"thickness_min": 3.01, "thickness_max": 4, "exact": False, "length_max": 500, "width_max": 120}]),
        _wariant("dab-micro-ab", [
            {"thickness_min": 1.8, "thickness_max": 12, "exact": False, "length_max": 500, "width_max": 120}]),
        _wariant("buk-micro-ab", []),                          # wyłączony w cenniku
    ]})
    assert "- buk lity A/B: grubość do 2 cm (długość do 240 cm); tylko 2,5 cm (długość do 240 cm); " \
           "tylko 2,8 cm (długość do 240 cm); szerokość do 120 cm" in opis
    assert "- dąb lity A/B: grubość od 4 do 12 cm (długość do 265 cm)" in opis
    assert "- jesion mikrowczep A/B: grubość 4 cm (długość do 500 cm)" in opis
    assert "- dąb mikrowczep A/B: grubość od 2 do 12 cm (długość do 500 cm)" in opis
    assert "- buk mikrowczep A/B: NIEDOSTĘPNY" in opis        # puste pasma
    assert "- jesion lity A/B: NIEDOSTĘPNY" in opis           # brak wariantu w /options
    assert "dąb lity B/B: NIEDOSTĘPNY" in opis


def test_opis_dostepnosci_pusty_gdy_awaria_crm_i_pomija_stary_crm_bez_pasm():
    assert crm.opis_dostepnosci({}) == ""
    # starszy CRM bez thickness_bands: nie twierdzimy niczego o wariancie, którego nie znamy
    opis = crm.opis_dostepnosci({"variants": [{"variant_code": "buk-lity-ab"}]})
    assert "buk lity" not in opis
