# -*- coding: utf-8 -*-
# Test: quote_worker.process_one bierze rekord z quote_queue i wola run_quote_turn.
import os, tempfile
os.environ.setdefault("OLX_CLIENT_ID", "x")
os.environ.setdefault("OLX_CLIENT_SECRET", "x")
os.environ.setdefault("OLX_REFRESH_TOKEN", "x")
os.environ["BRIDGE_DB"] = os.path.join(tempfile.mkdtemp(), "bridge_qw.db")
import importlib
import config; importlib.reload(config)
db_mod = importlib.import_module("core.db"); db_mod.init_db()
qw = importlib.import_module("quote_worker"); importlib.reload(qw)


def _enqueue(conv_id=5):
    c = db_mod.db()
    c.execute("DELETE FROM quote_queue")
    c.execute("INSERT INTO quote_queue(conv_id, inbox_id, message_id, content, next_at) "
              "VALUES(?,?,?,?,0)", (conv_id, 18, "m1", "tak"))
    c.commit(); c.close()


def test_process_one_wola_run_i_oznacza_sent(monkeypatch):
    wolane = {}
    monkeypatch.setattr(qw, "run_quote_turn",
                        lambda conv_id, inbox_id, mid, content, attachments=None: wolane.update(conv=conv_id))
    _enqueue(5)
    assert qw.process_one(9_999_999_999) is True
    assert wolane["conv"] == 5
    c = db_mod.db()
    st = c.execute("SELECT status FROM quote_queue WHERE conv_id=5").fetchone()["status"]
    c.close()
    assert st == "sent"


def test_process_one_pusta_kolejka():
    c = db_mod.db(); c.execute("DELETE FROM quote_queue"); c.commit(); c.close()
    assert qw.process_one(9_999_999_999) is False
