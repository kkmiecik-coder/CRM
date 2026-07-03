# -*- coding: utf-8 -*-
# Test: schemat tabel live-bota (live_queue, live_seen, live_state).
import os, tempfile
os.environ.setdefault("OLX_CLIENT_ID", "x")
os.environ.setdefault("OLX_CLIENT_SECRET", "x")
os.environ.setdefault("OLX_REFRESH_TOKEN", "x")
os.environ["BRIDGE_DB"] = os.path.join(tempfile.mkdtemp(), "bridge_livedb.db")
import importlib

import config; importlib.reload(config)
db_mod = importlib.import_module("core.db")


def test_init_db_tworzy_tabele_live():
    """init_db tworzy live_queue, live_seen i live_state."""
    db_mod.init_db()
    c = db_mod.db()
    tables = {r["name"] for r in c.execute(
        "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    c.close()
    assert "live_queue" in tables
    assert "live_seen" in tables
    assert "live_state" in tables


def test_live_queue_ma_kolumny_kolejki():
    """live_queue ma kolumny zgodne ze wzorcem suggest_queue."""
    db_mod.init_db()
    c = db_mod.db()
    cols = {r["name"] for r in c.execute("PRAGMA table_info(live_queue)").fetchall()}
    c.close()
    assert {"id", "conv_id", "inbox_id", "message_id", "content",
            "attempts", "status", "next_at", "last_error"} <= cols


def test_live_seen_dedup_po_mid():
    """live_seen: drugi INSERT tego samego mid rzuca IntegrityError (PRIMARY KEY)."""
    import sqlite3
    db_mod.init_db()
    c = db_mod.db()
    c.execute("DELETE FROM live_seen"); c.commit()
    c.execute("INSERT INTO live_seen(mid) VALUES('m1')"); c.commit()
    try:
        c.execute("INSERT INTO live_seen(mid) VALUES('m1')")
        c.commit()
        assert False, "Expected IntegrityError"
    except sqlite3.IntegrityError:
        pass  # Expected
    c.close()


def test_live_state_ma_kolumne_awaiting_confirm():
    """Stan potwierdzenia podsumowania wyceny zyje w live_state (migracja ALTER)."""
    from core import db as db_mod
    db_mod.init_db()
    c = db_mod.db()
    cols = {r["name"] for r in c.execute("PRAGMA table_info(live_state)").fetchall()}
    c.close()
    assert "awaiting_confirm" in cols
