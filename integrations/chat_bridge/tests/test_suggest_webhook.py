# -*- coding: utf-8 -*-
# Test: _enqueue_suggestion wpisuje INCOMING z inboxu z botem; dedup; pomija puste/wylaczone.
import os, tempfile
os.environ.setdefault("OLX_CLIENT_ID", "x")
os.environ.setdefault("OLX_CLIENT_SECRET", "x")
os.environ.setdefault("OLX_REFRESH_TOKEN", "x")
os.environ["CHATWOOT_OLX_INBOX_ID"] = "3"
os.environ["BRIDGE_DB"] = os.path.join(tempfile.mkdtemp(), "bridge.db")
import importlib

import config; importlib.reload(config)
db_mod = importlib.import_module("core.db")
import bots.registry as reg; importlib.reload(reg)
wh = importlib.import_module("webhooks"); importlib.reload(wh)


def setup_function(_):
    db_mod.init_db()
    c = db_mod.db()
    c.execute("DELETE FROM suggest_queue"); c.execute("DELETE FROM bot_seen"); c.commit(); c.close()


def _count():
    c = db_mod.db(); n = c.execute("SELECT COUNT(*) n FROM suggest_queue").fetchone()["n"]; c.close()
    return n


def _payload(mid="m1", content="Czas realizacji?", inbox="3"):
    return {"id": mid, "content": content,
            "conversation": {"id": 77, "inbox_id": int(inbox)}}


def test_enqueue_dodaje_zadanie():
    wh._enqueue_suggestion(_payload())
    assert _count() == 1


def test_dedup_po_message_id():
    wh._enqueue_suggestion(_payload())
    wh._enqueue_suggestion(_payload())
    assert _count() == 1


def test_pomija_inbox_bez_bota():
    wh._enqueue_suggestion(_payload(inbox="6"))   # Allegro-Dyskusje
    assert _count() == 0


def test_pomija_pusta_tresc():
    wh._enqueue_suggestion(_payload(content="   "))
    assert _count() == 0
