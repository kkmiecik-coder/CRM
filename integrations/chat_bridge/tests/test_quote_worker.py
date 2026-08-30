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


def test_persona_pro_wola_bots_pro_tura_uruchom_nie_run_quote_turn(monkeypatch):
    """Task 7: rekord persony 'pro' MA isc do bots_pro.tura.uruchom (silnik Agents SDK),
    a NIE do run_quote_turn (legacy silnik) — to rozgalezienie jest sercem podpiecia
    Debusia Pro pod istniejacy worker kolejki."""
    pytest.importorskip("agents")
    from bots_pro import tura as tura_pro
    wolane_pro = []
    monkeypatch.setattr(tura_pro, "uruchom",
                        lambda conv_id, inbox_id, tresc, zalaczniki=None, persona="pro":
                        wolane_pro.append((conv_id, inbox_id, tresc, zalaczniki, persona)))
    wolane_legacy = []
    monkeypatch.setattr(qw, "run_quote_turn",
                        lambda *a, **k: wolane_legacy.append((a, k)))

    c = db_mod.db()
    c.execute("DELETE FROM quote_queue")
    c.execute("INSERT INTO quote_queue(conv_id, inbox_id, message_id, content, persona, next_at) "
              "VALUES(?,?,?,?,?,0)", (7001, "42", "mX", "czesc, ile kosztuje blat?", "pro"))
    c.commit(); c.close()

    assert qw.process_one(9_999_999_999) is True
    assert wolane_legacy == []
    assert len(wolane_pro) == 1
    conv_id, inbox_id, tresc, zalaczniki, persona = wolane_pro[0]
    # inbox_id ma kolumne TEXT (core/db.py) - SQLite przechowuje ja jako string,
    # wiec porownujemy string, nie int (round-trip przez baze, nie tylko przez Pythona).
    assert (conv_id, inbox_id, tresc, persona) == (7001, "42", "czesc, ile kosztuje blat?", "pro")

    c = db_mod.db()
    st = c.execute("SELECT status FROM quote_queue WHERE conv_id=7001").fetchone()["status"]
    c.close()
    assert st == "sent"
