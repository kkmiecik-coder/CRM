# -*- coding: utf-8 -*-
# Test FAZA 0 zad. 7: rozgalezienie bledow /calculate (API-03) + negatywny cache get_options (API-08).
import os, tempfile, json
os.environ.setdefault("OLX_CLIENT_ID", "x")
os.environ.setdefault("OLX_CLIENT_SECRET", "x")
os.environ.setdefault("OLX_REFRESH_TOKEN", "x")
os.environ["CRM_API_BASE"] = "https://crm.test"
os.environ["CRM_BOT_API_KEY"] = "KEY"
os.environ["BOT_QUOTE_CLIENT_TYPE"] = "Klient indywidualny"
os.environ["BOT_QUOTE_CW_AGENT_TOKEN"] = "TQ"
os.environ.setdefault("BRIDGE_DB", os.path.join(tempfile.mkdtemp(), "bridge_qcalc.db"))
import importlib
import pytest
import config; importlib.reload(config)
db_mod = importlib.import_module("core.db"); db_mod.init_db()
qb = importlib.import_module("bots.quotebot"); importlib.reload(qb)
crm = importlib.import_module("bots.crm_calc")

_KOMPLET = {"pozycje": [{"id": "1", "produkt": "blat", "dlugosc": "200", "szerokosc": "60",
                         "grubosc": "4", "gatunek": "dąb", "technologia": "lita", "klasa": "A/B",
                         "ilosc": "1", "wykonczenie": "surowe"}], "wspolne": {}}


def _seed(conv_id):
    c = db_mod.db()
    c.execute("DELETE FROM quote_state WHERE conv_id=?", (conv_id,))
    c.execute("DELETE FROM quote_dane WHERE conv_id=?", (conv_id,))
    c.execute("INSERT INTO quote_dane(conv_id, dane_json) VALUES(?,?)", (conv_id, json.dumps(_KOMPLET)))
    c.execute("INSERT INTO quote_state(conv_id, bot_turns, awaiting_confirm) VALUES(?,1,1)", (conv_id,))
    c.commit(); c.close()


def _patch(monkeypatch, replies, calc_result):
    monkeypatch.setattr(qb, "cw_conv_status", lambda c: "pending")
    monkeypatch.setattr(qb, "cw_messages", lambda c, n: [{"role": "user", "text": "tak"}])
    monkeypatch.setattr(qb, "cw_contact", lambda c: {"name": "", "identifier": ""})
    monkeypatch.setattr(qb, "cw_contact_full", lambda c: {"name": "", "identifier": "", "email": "", "phone": ""})
    monkeypatch.setattr(qb, "retrieve", lambda q: [])
    monkeypatch.setattr(qb, "chat", lambda messages, **kw:
                        ('{"odpowiedz":"","handoff":false,"pozycje":[],"wspolne":{}}', {"error_class": None}))
    monkeypatch.setattr(qb, "cw_agent_reply", lambda conv_id, text, **kw: replies.append(text) or True)
    monkeypatch.setattr(qb, "cw_bot_handoff", lambda conv_id, **kw: replies.append("__HANDOFF__") or True)
    monkeypatch.setattr(qb, "cw_note", lambda conv_id, text, **kw: True)
    monkeypatch.setattr(qb.crm_calc, "get_options", lambda: {"finishing_options": []})
    monkeypatch.setattr(qb.crm_calc, "calculate", lambda pozycje, opts: calc_result)


def test_transport_error_rzuca_dla_retry(monkeypatch):
    """API-03: awaria CRM (TRANSPORT) -> RuntimeError (retry workera), nie mylny komunikat o lakierze."""
    replies = []
    _patch(monkeypatch, replies, {"ok": False, "errors": [{"code": "TRANSPORT", "message": "Błąd połączenia"}]})
    _seed(3001)
    with pytest.raises(RuntimeError):
        qb.run_quote_turn(3001, 12, "m1", "tak")
    assert not any("lakier" in t.lower() for t in replies), "brak mylnego pytania o lakier przy awarii"


def test_missing_fields_pyta_polskim_hintem(monkeypatch):
    """API-03: missing_fields z bot_api -> pytanie z polskim hintem, nie _PROSBA_DOPRECYZ."""
    replies = []
    _patch(monkeypatch, replies, {"ok": False, "errors": [],
                                  "missing_fields": [{"product_index": 1, "field": "length", "hint": "długość w cm"}]})
    _seed(3002)
    qb.run_quote_turn(3002, 12, "m1", "tak")
    tekst = " ".join(replies)
    assert "długość w cm" in tekst
    assert "połysk" not in tekst.lower(), "nie mieszamy z komunikatem o lakierze/polysku"


def test_braki_mapowania_prosba_doprecyz(monkeypatch):
    """API-03: braki_mapowania (wykonczenie) -> dopiero wtedy _PROSBA_DOPRECYZ."""
    replies = []
    _patch(monkeypatch, replies, {"ok": False, "errors": [], "missing_fields": [],
                                  "braki_mapowania": [{"powod": "wykończenie lakierowane wymaga wariantu"}]})
    _seed(3003)
    qb.run_quote_turn(3003, 12, "m1", "tak")
    assert any("połysk" in t.lower() for t in replies), "braki mapowania -> pytanie o kolor/polysk"


def test_get_options_negatywny_cache(monkeypatch):
    """API-08: po bledzie get_options cache'uje pusty wynik na krotko — brak wielu blokujacych wywolan."""
    crm._reset_cache()
    calls = {"n": 0}
    class R:
        status_code = 500
        text = "err"
        def json(self): return {}
    def fake_get(url, **kw):
        calls["n"] += 1
        return R()
    monkeypatch.setattr(crm.requests, "get", fake_get)
    assert crm.get_options() == {}
    assert crm.get_options() == {}   # drugie wywolanie z negatywnego cache
    assert calls["n"] == 1, "negatywny wynik cache'owany — tylko jedno wywolanie sieciowe"
    crm._reset_cache()
