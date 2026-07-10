# -*- coding: utf-8 -*-
# Test: quote_worker.process_one bierze rekord z quote_queue i wola run_quote_turn.
import os, tempfile
import pytest
os.environ.setdefault("OLX_CLIENT_ID", "x")
os.environ.setdefault("OLX_CLIENT_SECRET", "x")
os.environ.setdefault("OLX_REFRESH_TOKEN", "x")
os.environ["BRIDGE_DB"] = os.path.join(tempfile.mkdtemp(), "bridge_qw.db")
import importlib
import config; importlib.reload(config)
db_mod = importlib.import_module("core.db"); db_mod.init_db()
qw = importlib.import_module("quote_worker"); importlib.reload(qw)


@pytest.fixture(autouse=True)
def _circuit_state_isolation():
    """Stan circuit-breakera (TO-04) zyje w tabeli meta GLOBALNEJ dla calego (dzielonego
    miedzy plikami testow) bridge.db — bez resetu lezaly obwod z innego pliku testow
    zablokowalby tu process_one niezaleznie od intencji tego testu (code review Task 7,
    angle C)."""
    from core.db import meta_set
    meta_set(qw._META_CIRCUIT_UNTIL, 0)
    meta_set(qw._META_CIRCUIT_FAILS, 0)
    yield
    meta_set(qw._META_CIRCUIT_UNTIL, 0)
    meta_set(qw._META_CIRCUIT_FAILS, 0)


def _enqueue(conv_id=5):
    c = db_mod.db()
    c.execute("DELETE FROM quote_queue")
    c.execute("INSERT INTO quote_queue(conv_id, inbox_id, message_id, content, next_at) "
              "VALUES(?,?,?,?,0)", (conv_id, 18, "m1", "tak"))
    c.commit(); c.close()


def test_process_one_wola_run_i_oznacza_sent(monkeypatch):
    wolane = {}
    monkeypatch.setattr(qw, "run_quote_turn",
                        lambda conv_id, inbox_id, mid, content, attachments=None, persona="quote":
                        wolane.update(conv=conv_id, persona=persona))
    _enqueue(5)
    assert qw.process_one(9_999_999_999) is True
    assert wolane["conv"] == 5
    assert wolane["persona"] == "quote"   # rekord bez kolumny persona -> domyslnie quote (livechat)
    c = db_mod.db()
    st = c.execute("SELECT status FROM quote_queue WHERE conv_id=5").fetchone()["status"]
    c.close()
    assert st == "sent"


def test_process_one_pusta_kolejka():
    c = db_mod.db(); c.execute("DELETE FROM quote_queue"); c.commit(); c.close()
    assert qw.process_one(9_999_999_999) is False
