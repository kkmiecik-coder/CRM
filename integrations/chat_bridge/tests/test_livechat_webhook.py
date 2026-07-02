# -*- coding: utf-8 -*-
# Test: endpoint /agent-bot-live — kolejkowanie tur, dedup, filtry outgoing/private/event, autoryzacja.
import os, tempfile
os.environ.setdefault("OLX_CLIENT_ID", "x")
os.environ.setdefault("OLX_CLIENT_SECRET", "x")
os.environ.setdefault("OLX_REFRESH_TOKEN", "x")
os.environ["BOT_LIVE_AGENT_WEBHOOK_TOKEN"] = "sekret-live"
os.environ["BRIDGE_DB"] = os.path.join(tempfile.mkdtemp(), "bridge_livewh.db")
import importlib

import config; importlib.reload(config)
db_mod = importlib.import_module("core.db")
wh = importlib.import_module("webhooks"); importlib.reload(wh)

from flask import Flask
app = Flask(__name__)
app.register_blueprint(wh.bp)


def setup_function(_):
    db_mod.init_db()
    c = db_mod.db()
    c.execute("DELETE FROM live_queue")
    c.execute("DELETE FROM live_seen")
    c.commit(); c.close()


def _count():
    c = db_mod.db()
    n = c.execute("SELECT COUNT(*) n FROM live_queue").fetchone()["n"]
    c.close()
    return n


def _payload(mid="m1", content="Szukam blatu", inbox_id=12, conv_id=77, mtype=0,
             private=False, event="message_created"):
    return {"event": event, "message_type": mtype, "id": mid, "content": content,
            "private": private, "conversation": {"id": conv_id, "inbox_id": inbox_id}}


def test_incoming_kolejkuje_ture():
    """Wiadomosc klienta -> 1 wpis w live_queue, BEZ natychmiastowego handoffu."""
    wh._process_livechat_bot(_payload())
    assert _count() == 1
    c = db_mod.db()
    row = c.execute("SELECT * FROM live_queue").fetchone()
    c.close()
    assert row["conv_id"] == 77
    assert row["content"] == "Szukam blatu"
    assert row["status"] == "pending"


def test_dedup_po_mid():
    wh._process_livechat_bot(_payload(mid="dup"))
    wh._process_livechat_bot(_payload(mid="dup"))
    assert _count() == 1


def test_outgoing_i_private_ignorowane():
    wh._process_livechat_bot(_payload(mtype=1))
    wh._process_livechat_bot(_payload(mtype="outgoing"))
    wh._process_livechat_bot(_payload(private=True))
    assert _count() == 0


def test_inny_event_ignorowany():
    wh._process_livechat_bot(_payload(event="conversation_updated"))
    assert _count() == 0


def test_pusta_tresc_ignorowana():
    """Live-bot bez tresci nie ma na co odpowiadac (inaczej niz podpowiadacz — tu zero handoffu)."""
    wh._process_livechat_bot(_payload(content="  "))
    assert _count() == 0


def test_endpoint_wymaga_tokenu():
    cl = app.test_client()
    assert cl.post("/agent-bot-live", json=_payload()).status_code == 401
    assert cl.post("/agent-bot-live?token=zly", json=_payload()).status_code == 401
    r = cl.post("/agent-bot-live?token=sekret-live", json=_payload(mid="m-http"))
    assert r.status_code == 200
    assert _count() == 1
