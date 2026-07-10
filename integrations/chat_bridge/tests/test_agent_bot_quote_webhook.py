# -*- coding: utf-8 -*-
# Test: endpoint /agent-bot-quote — kolejkowanie tur do quote_queue, dedup, guard persony, autoryzacja.
import os, tempfile
os.environ.setdefault("OLX_CLIENT_ID", "x")
os.environ.setdefault("OLX_CLIENT_SECRET", "x")
os.environ.setdefault("OLX_REFRESH_TOKEN", "x")
os.environ["BOT_QUOTE_AGENT_WEBHOOK_TOKEN"] = "sekret-quote"
os.environ["BRIDGE_DB"] = os.path.join(tempfile.mkdtemp(), "bridge_qwh.db")
import importlib
import config; importlib.reload(config)
db_mod = importlib.import_module("core.db")
wh = importlib.import_module("webhooks"); importlib.reload(wh)
from flask import Flask
app = Flask(__name__); app.register_blueprint(wh.bp)


def setup_function(_):
    db_mod.init_db()
    c = db_mod.db(); c.execute("DELETE FROM quote_queue"); c.execute("DELETE FROM quote_seen")
    c.commit(); c.close()


def _count():
    c = db_mod.db(); n = c.execute("SELECT COUNT(*) n FROM quote_queue").fetchone()["n"]; c.close()
    return n


def _payload(mid="m1", content="Wycena blatu", inbox_id=18, conv_id=77, mtype=0,
             private=False, event="message_created"):
    return {"event": event, "message_type": mtype, "id": mid, "content": content,
            "private": private, "conversation": {"id": conv_id, "inbox_id": inbox_id}}


def test_kolejkuje_ture(monkeypatch):
    monkeypatch.setattr(wh, "persona_for", lambda inbox_id: "livechat")
    wh._process_quotebot(_payload())
    assert _count() == 1


def test_dedup(monkeypatch):
    monkeypatch.setattr(wh, "persona_for", lambda inbox_id: "livechat")
    wh._process_quotebot(_payload(mid="d")); wh._process_quotebot(_payload(mid="d"))
    assert _count() == 1


def test_coalesce_dwie_wiadomosci_jedna_tura(monkeypatch):
    # Okno ciszy: dwie wiadomosci tej samej rozmowy (rozne mid) -> jeden rekord, tresc polaczona.
    monkeypatch.setattr(wh, "persona_for", lambda inbox_id: "livechat")
    wh._process_quotebot(_payload(mid="c1", content="poproszę wycenę"))
    wh._process_quotebot(_payload(mid="c2", content="blat dębowy"))
    assert _count() == 1
    c = db_mod.db(); row = c.execute("SELECT content FROM quote_queue").fetchone(); c.close()
    assert row["content"] == "poproszę wycenę\nblat dębowy"


def test_guard_persony(monkeypatch):
    monkeypatch.setattr(wh, "persona_for", lambda inbox_id: "olx")
    wh._process_quotebot(_payload())
    assert _count() == 0


def test_token(monkeypatch):
    monkeypatch.setattr(wh, "persona_for", lambda inbox_id: "livechat")
    cl = app.test_client()
    assert cl.post("/agent-bot-quote", json=_payload()).status_code == 401
    assert cl.post("/agent-bot-quote?token=zly", json=_payload()).status_code == 401
    assert cl.post("/agent-bot-quote?token=sekret-quote", json=_payload(mid="ok")).status_code == 200
    assert _count() == 1
