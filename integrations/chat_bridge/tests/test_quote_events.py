# -*- coding: utf-8 -*-
# Test: telemetria leja sprzedazowego quote-bota (LS-08/TO-05/TO-06/TO-09).
import os, tempfile, json
os.environ.setdefault("OLX_CLIENT_ID", "x")
os.environ.setdefault("OLX_CLIENT_SECRET", "x")
os.environ.setdefault("OLX_REFRESH_TOKEN", "x")
os.environ["CRM_API_BASE"] = "https://crm.test"
os.environ["CRM_BOT_API_KEY"] = "KEY"
os.environ["BOT_QUOTE_CLIENT_TYPE"] = "Klient indywidualny"
os.environ["BOT_QUOTE_CW_AGENT_TOKEN"] = "TQ"
os.environ.setdefault("BRIDGE_DB", os.path.join(tempfile.mkdtemp(), "bridge_events.db"))
import importlib
import config; importlib.reload(config)
db_mod = importlib.import_module("core.db"); db_mod.init_db()
ev = importlib.import_module("core.events"); importlib.reload(ev)
qb = importlib.import_module("bots.quotebot"); importlib.reload(qb)


def _poz(**kw):
    base = {"id": "1", "produkt": "blat", "dlugosc": "200", "szerokosc": "60", "grubosc": "4",
            "gatunek": "dąb", "technologia": "lity", "klasa": "A/B", "ilosc": "1",
            "wykonczenie": "surowe", "finishing_id": ""}
    base.update(kw); return base


def test_log_event_zapisuje_i_serializuje_meta():
    ev.log_event(123, "priced", {"kwota": 1230.0})
    c = db_mod.db()
    row = c.execute("SELECT conv_id, event, meta FROM quote_events ORDER BY id DESC LIMIT 1").fetchone()
    c.close()
    assert row["conv_id"] == 123 and row["event"] == "priced"
    assert json.loads(row["meta"])["kwota"] == 1230.0


def test_log_event_bez_meta():
    ev.log_event(124, "summary_sent")
    c = db_mod.db()
    row = c.execute("SELECT meta FROM quote_events WHERE conv_id=124").fetchone()
    c.close()
    assert row["meta"] is None


def test_priced_loguje_event_z_kwota(monkeypatch):
    monkeypatch.setattr(qb, "cw_agent_reply", lambda c, t, **kw: True)
    monkeypatch.setattr(qb, "cw_note", lambda c, t, **kw: True)
    monkeypatch.setattr(qb.crm_calc, "get_options", lambda: {"finishing_options": []})
    monkeypatch.setattr(qb.crm_calc, "calculate",
                        lambda p, o: {"ok": True, "products": [{}],
                                      "totals": {"total_brutto": 1230.0, "total_netto": 1000.0}})
    monkeypatch.setattr(qb.crm_calc, "find_or_create_client",
                        lambda e, p, n, client_number=None: {"ok": True, "matched": False,
                                                             "created": True, "client": {"id": 1}})
    monkeypatch.setattr(qb.crm_calc, "create_quote",
                        lambda p, o, cid, notes="": {"ok": True, "quote_number": "W/1",
                                                     "public_url": "https://crm/q/a", "edit_uuid": "UU"})
    qb._wyslij_cene_i_kontakt(1001, {"pozycje": [_poz()], "wspolne": {}}, {})
    c = db_mod.db()
    row = c.execute("SELECT event, meta FROM quote_events WHERE conv_id=1001 AND event='priced'").fetchone()
    c.close()
    assert json.loads(row["meta"])["kwota"] == 1230.0


def test_quote_saved_loguje_event_z_numerem(monkeypatch):
    monkeypatch.setattr(qb, "cw_agent_reply", lambda c, t, **kw: True)
    monkeypatch.setattr(qb, "cw_note", lambda c, t, **kw: True)
    monkeypatch.setattr(qb.crm_calc, "find_or_create_client",
                        lambda e, p, n, client_number=None: {"ok": True, "matched": False,
                                                             "created": True, "client": {"id": 1}})
    monkeypatch.setattr(qb.crm_calc, "create_quote",
                        lambda p, o, cid, notes="": {"ok": True, "quote_number": "W/42",
                                                     "public_url": "https://crm/q/a", "edit_uuid": "UU"})
    qb._zapisz_wycene(1002, {"pozycje": [_poz()], "wspolne": {}}, {"finishing_options": []},
                      "jan@x.pl", None, "Jan")
    c = db_mod.db()
    row = c.execute("SELECT meta FROM quote_events WHERE conv_id=1002 AND event='quote_saved'").fetchone()
    c.close()
    assert json.loads(row["meta"])["nr"] == "W/42"


def test_handoff_loguje_event_z_powodem(monkeypatch):
    monkeypatch.setattr(qb, "cw_agent_reply", lambda c, t, **kw: True)
    monkeypatch.setattr(qb, "cw_note", lambda c, t, **kw: True)
    monkeypatch.setattr(qb, "cw_bot_handoff", lambda c, **kw: True)
    qb._do_handoff(1003, "test powod", {"pozycje": [], "wspolne": {}})
    c = db_mod.db()
    row = c.execute("SELECT meta FROM quote_events WHERE conv_id=1003 AND event='handoff'").fetchone()
    c.close()
    assert json.loads(row["meta"])["powod"] == "test powod"


def test_contact_given_i_refused_loguja_eventy(monkeypatch):
    monkeypatch.setattr(qb, "cw_conv_status", lambda c: "pending")
    monkeypatch.setattr(qb, "cw_agent_reply", lambda c, t, **kw: True)
    monkeypatch.setattr(qb, "cw_note", lambda c, t, **kw: True)
    monkeypatch.setattr(qb, "cw_contact_full", lambda c: {"name": "Jan", "email": "", "phone": ""})
    monkeypatch.setattr(qb.crm_calc, "find_or_create_client",
                        lambda e, p, n, client_number=None: {"ok": True, "matched": False,
                                                             "created": True, "client": {"id": 1}})
    monkeypatch.setattr(qb.crm_calc, "create_quote",
                        lambda p, o, cid, notes="": {"ok": True, "quote_number": "W/1",
                                                     "public_url": "https://crm/q/a", "edit_uuid": "UU"})
    qb._set_awaiting_contact(1004, True)
    qb._zapisz_dane(1004, {"pozycje": [_poz()], "wspolne": {}})
    qb.run_quote_turn(1004, 5, "m1", "jan@kowalski.pl")
    c = db_mod.db()
    row = c.execute("SELECT * FROM quote_events WHERE conv_id=1004 AND event='contact_given'").fetchone()
    c.close()
    assert row is not None

    qb._set_awaiting_contact(1005, True)
    qb._zapisz_dane(1005, {"pozycje": [_poz()], "wspolne": {}})
    qb.run_quote_turn(1005, 5, "m1", "nie, dziękuję")
    c = db_mod.db()
    row = c.execute("SELECT * FROM quote_events WHERE conv_id=1005 AND event='contact_refused'").fetchone()
    c.close()
    assert row is not None
