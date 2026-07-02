# -*- coding: utf-8 -*-
# Test: worker kolejki live-bota — sukces, retry z backoffem, awaria -> handoff z przeprosinami.
import os, tempfile
os.environ.setdefault("OLX_CLIENT_ID", "x")
os.environ.setdefault("OLX_CLIENT_SECRET", "x")
os.environ.setdefault("OLX_REFRESH_TOKEN", "x")
os.environ["BRIDGE_DB"] = os.path.join(tempfile.mkdtemp(), "bridge_livewrk.db")
import importlib

import config; importlib.reload(config)
db_mod = importlib.import_module("core.db")
lw = importlib.import_module("live_worker")


def setup_function(_):
    db_mod.init_db()
    c = db_mod.db()
    c.execute("DELETE FROM live_queue")
    c.commit(); c.close()


def _enqueue(conv_id=77, attempts=0):
    c = db_mod.db()
    c.execute("INSERT INTO live_queue(conv_id, inbox_id, message_id, content, attempts, next_at) "
              "VALUES(?, '12', 'm1', 'hej', ?, 0)", (conv_id, attempts))
    c.commit(); c.close()


def _row():
    c = db_mod.db()
    r = c.execute("SELECT * FROM live_queue").fetchone()
    c.close()
    return r


def test_sukces_oznacza_sent(monkeypatch):
    calls = []
    monkeypatch.setattr(lw, "run_livechat_turn", lambda *a: calls.append(a))
    _enqueue()

    assert lw.process_one(0) is True
    assert calls == [(77, "12", "m1", "hej")]
    assert _row()["status"] == "sent"


def test_pusta_kolejka_zwraca_false():
    assert lw.process_one(0) is False


def test_blad_planuje_retry_z_backoffem(monkeypatch):
    def boom(*a):
        raise RuntimeError("llm pad")
    monkeypatch.setattr(lw, "run_livechat_turn", boom)
    _enqueue()

    lw.process_one(100.0)
    r = _row()
    assert r["status"] == "pending"
    assert r["attempts"] == 1
    assert r["next_at"] > 100.0
    assert "llm pad" in r["last_error"]


def test_wyczerpane_proby_failed_i_przeprosiny(monkeypatch):
    def boom(*a):
        raise RuntimeError("llm pad")
    apologies = []
    monkeypatch.setattr(lw, "run_livechat_turn", boom)
    monkeypatch.setattr(lw, "handoff_with_apology", lambda cid: apologies.append(cid))
    _enqueue(attempts=config.BOT_MAX_ATTEMPTS - 1)

    lw.process_one(0)
    assert _row()["status"] == "failed"
    assert apologies == [77]
