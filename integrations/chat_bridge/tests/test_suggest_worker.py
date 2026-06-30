# -*- coding: utf-8 -*-
# Test: worker oznacza sukces (sent) oraz po wyczerpaniu prob -> failed + notatka bledu.
import os, tempfile
os.environ.setdefault("OLX_CLIENT_ID", "x")
os.environ.setdefault("OLX_CLIENT_SECRET", "x")
os.environ.setdefault("OLX_REFRESH_TOKEN", "x")
os.environ["BRIDGE_DB"] = os.path.join(tempfile.mkdtemp(), "bridge.db")
os.environ["BOT_MAX_ATTEMPTS"] = "2"
import importlib

import config; importlib.reload(config)
db_mod = importlib.import_module("core.db")
sw = importlib.import_module("suggest_worker"); importlib.reload(sw)
# Restore BOT_MAX_ATTEMPTS to default so other tests see the real default.
del os.environ["BOT_MAX_ATTEMPTS"]


def setup_function(_):
    db_mod.init_db()
    c = db_mod.db(); c.execute("DELETE FROM suggest_queue"); c.commit(); c.close()


def _add():
    c = db_mod.db()
    c.execute("INSERT INTO suggest_queue(conv_id, inbox_id, message_id, content, next_at) VALUES(?,?,?,?,0)",
              (5, "3", "m1", "hej"))
    c.commit(); c.close()


def _status():
    c = db_mod.db(); r = c.execute("SELECT status FROM suggest_queue LIMIT 1").fetchone(); c.close()
    return r["status"] if r else None


def test_sukces_oznacza_sent(monkeypatch):
    _add()
    monkeypatch.setattr(sw, "run_suggestion", lambda *a: None)
    assert sw.process_one(9999999999) is True
    assert _status() == "sent"


def test_pusta_kolejka_zwraca_false():
    assert sw.process_one(9999999999) is False


def test_po_wyczerpaniu_prob_failed_i_notatka(monkeypatch):
    _add()
    def boom(*a):
        raise RuntimeError("AI padlo")
    monkeypatch.setattr(sw, "run_suggestion", boom)
    notes = []
    monkeypatch.setattr(sw, "cw_note", lambda cid, text, *a, **kw: notes.append(text))
    # proba 1 -> retry (attempts=1 < 2), proba 2 -> failed (attempts=2 >= 2)
    sw.process_one(0)
    sw.process_one(100)
    assert _status() == "failed"
    assert len(notes) == 1
    assert "Nie udało się" in notes[0]
