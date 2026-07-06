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


def test_incoming_kolejkuje_ture(monkeypatch):
    """Wiadomosc klienta -> 1 wpis w live_queue, BEZ natychmiastowego handoffu."""
    monkeypatch.setattr(wh, "persona_for", lambda inbox_id: "livechat")
    wh._process_livechat_bot(_payload())
    assert _count() == 1
    c = db_mod.db()
    row = c.execute("SELECT * FROM live_queue").fetchone()
    c.close()
    assert row["conv_id"] == 77
    assert row["content"] == "Szukam blatu"
    assert row["status"] == "pending"


def test_dedup_po_mid(monkeypatch):
    monkeypatch.setattr(wh, "persona_for", lambda inbox_id: "livechat")
    wh._process_livechat_bot(_payload(mid="dup"))
    wh._process_livechat_bot(_payload(mid="dup"))
    assert _count() == 1


def test_outgoing_i_private_ignorowane(monkeypatch):
    monkeypatch.setattr(wh, "persona_for", lambda inbox_id: "livechat")
    wh._process_livechat_bot(_payload(mtype=1))
    wh._process_livechat_bot(_payload(mtype="outgoing"))
    wh._process_livechat_bot(_payload(private=True))
    assert _count() == 0


def test_inny_event_ignorowany(monkeypatch):
    monkeypatch.setattr(wh, "persona_for", lambda inbox_id: "livechat")
    wh._process_livechat_bot(_payload(event="conversation_updated"))
    assert _count() == 0


def test_pusta_tresc_ignorowana(monkeypatch):
    """Live-bot bez tresci nie ma na co odpowiadac (inaczej niz podpowiadacz — tu zero handoffu)."""
    monkeypatch.setattr(wh, "persona_for", lambda inbox_id: "livechat")
    wh._process_livechat_bot(_payload(content="  "))
    assert _count() == 0


def test_inbox_bez_persony_livechat_ignorowany(monkeypatch):
    """Guard: inbox omylkowo przypiety (np. persona 'olx') -> bot live nie odpowiada publicznie."""
    monkeypatch.setattr(wh, "persona_for", lambda inbox_id: "olx")
    wh._process_livechat_bot(_payload())
    assert _count() == 0


def test_livechat_webhook_kolejkuje_obraz_bez_tekstu(monkeypatch):
    """Zdjecie bez tekstu tez ma zakolejkowac ture — filtr tylko obrazow (nie pliki/pdf)."""
    monkeypatch.setattr(wh, "persona_for", lambda inbox_id: "livechat")
    d = _payload(mid="mimg1", content="", inbox_id=9, conv_id=501)
    d["attachments"] = [{"data_url": "http://cw/img1.png", "file_type": "image"},
                         {"data_url": "http://cw/plik.pdf", "file_type": "file"}]
    wh._process_livechat_bot(d)
    c = db_mod.db()
    row = c.execute("SELECT content, attachments FROM live_queue WHERE conv_id=501").fetchone()
    c.close()
    assert row is not None, "obraz bez tekstu musi zakolejkowac ture"
    import json
    assert json.loads(row["attachments"]) == ["http://cw/img1.png"]  # tylko obrazy


def test_pusta_tresc_tylko_plik_nieobraz_ignorowana(monkeypatch):
    """Brak tresci + WYLACZNIE zalacznik nie-obrazowy (pdf/file) -> guard not content and not att -> brak kolejki."""
    monkeypatch.setattr(wh, "persona_for", lambda inbox_id: "livechat")
    d = _payload(mid="mplik1", content="", inbox_id=9, conv_id=502)
    d["attachments"] = [{"data_url": "http://cw/dokument.pdf", "file_type": "file"}]
    wh._process_livechat_bot(d)
    assert _count() == 0


def test_endpoint_wymaga_tokenu(monkeypatch):
    monkeypatch.setattr(wh, "persona_for", lambda inbox_id: "livechat")
    cl = app.test_client()
    assert cl.post("/agent-bot-live", json=_payload()).status_code == 401
    assert cl.post("/agent-bot-live?token=zly", json=_payload()).status_code == 401
    r = cl.post("/agent-bot-live?token=sekret-live", json=_payload(mid="m-http"))
    assert r.status_code == 200
    assert _count() == 1
