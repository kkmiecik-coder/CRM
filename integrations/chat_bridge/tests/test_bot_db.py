# -*- coding: utf-8 -*-
# Test: init_db tworzy tabele potrzebne botom AI.
import os, tempfile
os.environ.setdefault("OLX_CLIENT_ID", "x")
os.environ.setdefault("OLX_CLIENT_SECRET", "x")
os.environ.setdefault("OLX_REFRESH_TOKEN", "x")
os.environ["BRIDGE_DB"] = os.path.join(tempfile.mkdtemp(), "bridge.db")
import importlib

db_mod = importlib.import_module("core.db")


def _tables():
    db_mod.init_db()
    c = db_mod.db()
    rows = c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    c.close()
    return {r["name"] for r in rows}


def test_tabele_botow_istnieja():
    t = _tables()
    assert {"suggest_queue", "bot_seen", "kb_chunks"} <= t


def test_kolumny_suggest_queue():
    db_mod.init_db()
    c = db_mod.db()
    cols = {r["name"] for r in c.execute("PRAGMA table_info(suggest_queue)").fetchall()}
    c.close()
    assert {"id", "conv_id", "inbox_id", "message_id", "content",
            "attempts", "status", "next_at", "last_error"} <= cols
