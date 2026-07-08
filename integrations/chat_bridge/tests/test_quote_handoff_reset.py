# -*- coding: utf-8 -*-
# Test FAZA 0 zad. 8: miekki reset przy handoffie (MS-03/SB-10), atomowa kolejnosc (API-05),
# dedykowany komunikat przy limicie tur (LS-11).
import os, tempfile, json
os.environ.setdefault("OLX_CLIENT_ID", "x")
os.environ.setdefault("OLX_CLIENT_SECRET", "x")
os.environ.setdefault("OLX_REFRESH_TOKEN", "x")
os.environ["CRM_API_BASE"] = "https://crm.test"
os.environ["CRM_BOT_API_KEY"] = "KEY"
os.environ["BOT_QUOTE_CLIENT_TYPE"] = "Klient indywidualny"
os.environ["BOT_QUOTE_CW_AGENT_TOKEN"] = "TQ"
os.environ.setdefault("BRIDGE_DB", os.path.join(tempfile.mkdtemp(), "bridge_qhoff.db"))
import importlib
import pytest
import config; importlib.reload(config)
db_mod = importlib.import_module("core.db"); db_mod.init_db()
qb = importlib.import_module("bots.quotebot"); importlib.reload(qb)

_DANE = {"pozycje": [{"id": "1", "produkt": "blat", "gatunek": "dąb"}], "wspolne": {}}


def test_miekki_reset_zachowuje_dane_i_kontakt(monkeypatch):
    monkeypatch.setattr(qb, "cw_bot_handoff", lambda conv_id, **kw: True)
    monkeypatch.setattr(qb, "cw_note", lambda conv_id, text, **kw: True)
    monkeypatch.setattr(qb, "cw_agent_reply", lambda conv_id, text, **kw: True)
    monkeypatch.setattr(qb.crm_calc, "get_options", lambda: {"finishing_options": []})
    c = db_mod.db()
    c.execute("DELETE FROM quote_state WHERE conv_id=?", (4001,))
    c.execute("DELETE FROM quote_dane WHERE conv_id=?", (4001,))
    c.execute("INSERT INTO quote_dane(conv_id, dane_json) VALUES(?,?)", (4001, json.dumps(_DANE)))
    c.execute("INSERT INTO quote_state(conv_id, bot_turns, awaiting_confirm, awaiting_contact, "
              "human_deflected, reject_count, contact_email, quote_edit_uuid, sent_images, priced) "
              "VALUES(?,5,1,1,1,2,?,?,?,1)", (4001, "a@b.pl", "uuid-123", json.dumps(["cmp:1"])))
    c.commit(); c.close()

    qb._do_handoff(4001, "klient prosi o konsultanta", _DANE)

    c = db_mod.db()
    dane_row = c.execute("SELECT dane_json FROM quote_dane WHERE conv_id=4001").fetchone()
    st = c.execute("SELECT bot_turns, awaiting_confirm, awaiting_contact, human_deflected, reject_count, "
                   "contact_email, quote_edit_uuid, sent_images FROM quote_state WHERE conv_id=4001").fetchone()
    c.close()
    assert dane_row and dane_row["dane_json"], "quote_dane ZACHOWANE (nie amnezja)"
    assert st["quote_edit_uuid"] == "uuid-123", "edit_uuid zachowany (brak wyceny-sieroty)"
    assert st["contact_email"] == "a@b.pl", "kontakt zachowany"
    assert st["sent_images"], "sent_images zachowane"
    assert st["bot_turns"] == 0 and st["awaiting_confirm"] == 0 and st["awaiting_contact"] == 0
    assert st["human_deflected"] == 0 and st["reject_count"] == 0


def test_handoff_atomowy_toggle_ostatni(monkeypatch):
    """API-05: gdy cw_note padnie, toggle statusu NIE moze sie wykonac (retry czysty, status pending)."""
    toggled = {"n": 0}
    monkeypatch.setattr(qb, "cw_bot_handoff", lambda conv_id, **kw: toggled.__setitem__("n", toggled["n"] + 1) or True)
    def boom(conv_id, text, **kw):
        raise RuntimeError("cw_note timeout")
    monkeypatch.setattr(qb, "cw_note", boom)
    monkeypatch.setattr(qb, "cw_agent_reply", lambda conv_id, text, **kw: True)
    monkeypatch.setattr(qb.crm_calc, "get_options", lambda: {"finishing_options": []})
    with pytest.raises(RuntimeError):
        qb._do_handoff(4002, "powod", _DANE)
    assert toggled["n"] == 0, "toggle statusu jest OSTATNIM krokiem — nie wykonany przy padzie notatki"


def test_limit_tur_dedykowany_komunikat(monkeypatch):
    """LS-11: handoff z limitu tur ma dedykowany komunikat, nie 'Dziękuję za informacje!'."""
    replies = []
    monkeypatch.setattr(qb, "cw_conv_status", lambda c: "pending")
    monkeypatch.setattr(qb, "cw_bot_handoff", lambda conv_id, **kw: True)
    monkeypatch.setattr(qb, "cw_note", lambda conv_id, text, **kw: True)
    monkeypatch.setattr(qb, "cw_agent_reply", lambda conv_id, text, **kw: replies.append(text) or True)
    monkeypatch.setattr(qb.crm_calc, "get_options", lambda: {"finishing_options": []})
    c = db_mod.db()
    c.execute("DELETE FROM quote_state WHERE conv_id=?", (4003,))
    c.execute("DELETE FROM quote_dane WHERE conv_id=?", (4003,))
    c.execute("INSERT INTO quote_state(conv_id, bot_turns) VALUES(?,?)", (4003, qb.BOT_QUOTE_MAX_TURNS))
    c.commit(); c.close()
    qb.run_quote_turn(4003, 12, "m1", "tak, zgadza się")
    tekst = " ".join(replies)
    assert "Dziękuję za informacje" not in tekst
    assert "konsultant" in tekst.lower()
