# -*- coding: utf-8 -*-
# Test: init_db tworzy tabele quote_* z wymaganymi kolumnami (izolacja od live_*).
import os, tempfile
os.environ.setdefault("OLX_CLIENT_ID", "x")
os.environ.setdefault("OLX_CLIENT_SECRET", "x")
os.environ.setdefault("OLX_REFRESH_TOKEN", "x")
os.environ["BRIDGE_DB"] = os.path.join(tempfile.mkdtemp(), "bridge_qdb.db")
import importlib
import config; importlib.reload(config)
db_mod = importlib.import_module("core.db")


def _cols(table):
    db_mod.init_db()
    c = db_mod.db()
    rows = c.execute("PRAGMA table_info(%s)" % table).fetchall()
    c.close()
    return {r["name"] for r in rows}


def test_quote_queue_ma_kolumny():
    assert {"id", "conv_id", "inbox_id", "message_id", "content",
            "attempts", "status", "next_at", "last_error", "attachments"} <= _cols("quote_queue")


def test_quote_state_ma_flagi_wyceny():
    cols = _cols("quote_state")
    assert {"conv_id", "bot_turns", "awaiting_confirm", "priced",
            "awaiting_contact", "quote_saved", "sent_images"} <= cols


def test_quote_dane_i_seen_istnieja():
    assert "dane_json" in _cols("quote_dane")
    assert "mid" in _cols("quote_seen")
