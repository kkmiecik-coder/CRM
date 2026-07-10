# -*- coding: utf-8 -*-
# Testy okna ciszy (debounce) quote-bota: enqueue_quote_turn wstawia lub SCALA ture w quote_queue
# (sliding-window). Serie szybkich wiadomosci -> jeden rekord pending, tresc akumulowana, next_at
# przesuwany na now+BOT_DEBOUNCE_SECONDS. Dedup po message_id robi wolajacy (nie helper).
import os, tempfile, json
os.environ.setdefault("OLX_CLIENT_ID", "x")
os.environ.setdefault("OLX_CLIENT_SECRET", "x")
os.environ.setdefault("OLX_REFRESH_TOKEN", "x")
os.environ.setdefault("BRIDGE_DB", os.path.join(tempfile.mkdtemp(), "bridge_intake.db"))
import importlib
import config
db_mod = importlib.import_module("core.db")
qi = importlib.import_module("bots.quote_intake")


def setup_function(_):
    db_mod.init_db()
    c = db_mod.db()
    c.execute("DELETE FROM quote_queue"); c.execute("DELETE FROM quote_seen")
    c.commit(); c.close()


def _rows(conv_id=None):
    c = db_mod.db()
    q = "SELECT conv_id, message_id, content, attachments, persona, status, next_at FROM quote_queue"
    if conv_id is not None:
        q += " WHERE conv_id=%d" % conv_id
    r = c.execute(q + " ORDER BY id").fetchall()
    c.close()
    return [dict(x) for x in r]


def test_pojedyncza_wiadomosc_insert_z_oknem_ciszy():
    qi.enqueue_quote_turn(5, 18, "m1", "cześć", persona="quote_olx", now=1000.0)
    rows = _rows(5)
    assert len(rows) == 1
    assert rows[0]["content"] == "cześć"
    assert rows[0]["persona"] == "quote_olx"
    assert rows[0]["status"] == "pending"
    assert rows[0]["next_at"] == 1000.0 + qi.BOT_DEBOUNCE_SECONDS   # nie 0 — czekamy na dopiski


def test_druga_wiadomosc_scala_i_przesuwa_next_at():
    qi.enqueue_quote_turn(5, 18, "m1", "poproszę wycenę", now=1000.0)
    qi.enqueue_quote_turn(5, 18, "m2", "blat dębowy 200x60", now=1003.0)
    rows = _rows(5)
    assert len(rows) == 1                              # scalone w jeden rekord
    assert rows[0]["content"] == "poproszę wycenę\nblat dębowy 200x60"
    assert rows[0]["message_id"] == "m2"              # najnowsza wiadomosc
    assert rows[0]["next_at"] == 1003.0 + qi.BOT_DEBOUNCE_SECONDS   # slizg do OSTATNIEJ


def test_rozne_rozmowy_nie_scalaja_sie():
    qi.enqueue_quote_turn(5, 18, "m1", "a", now=1000.0)
    qi.enqueue_quote_turn(6, 18, "m2", "b", now=1000.0)
    assert len(_rows()) == 2


def test_rekord_processing_nie_scala_tylko_insert():
    # Wiadomosc w trakcie tury bota (processing) -> nowa wiadomosc trafia jako osobny rekord.
    c = db_mod.db()
    c.execute("INSERT INTO quote_queue(conv_id, inbox_id, message_id, content, status, next_at) "
              "VALUES(?,?,?,?,?,?)", (5, 18, "m1", "w toku", "processing", 9e9))
    c.commit(); c.close()
    qi.enqueue_quote_turn(5, 18, "m2", "nowa", now=1000.0)
    rows = _rows(5)
    assert len(rows) == 2
    statusy = sorted(r["status"] for r in rows)
    assert statusy == ["pending", "processing"]


def test_attachments_lączone_unia():
    qi.enqueue_quote_turn(5, 18, "m1", "foto1", attachments=["http://a.jpg"], now=1000.0)
    qi.enqueue_quote_turn(5, 18, "m2", "foto2", attachments=["http://b.jpg"], now=1001.0)
    rows = _rows(5)
    assert len(rows) == 1
    assert json.loads(rows[0]["attachments"]) == ["http://a.jpg", "http://b.jpg"]


def test_zwraca_inserted_potem_coalesced():
    assert qi.enqueue_quote_turn(5, 18, "m1", "a", now=1000.0) == "inserted"
    assert qi.enqueue_quote_turn(5, 18, "m2", "b", now=1001.0) == "coalesced"


def test_dedup_ten_sam_message_id_atomowo():
    # Dedup jest w helperze (atomowy z enqueue): ten sam message_id -> 'duplicate', bez zmian.
    assert qi.enqueue_quote_turn(5, 18, "m1", "a", now=1000.0) == "inserted"
    assert qi.enqueue_quote_turn(5, 18, "m1", "znowu", now=1001.0) == "duplicate"
    rows = _rows(5)
    assert len(rows) == 1
    assert rows[0]["content"] == "a"   # duplikat nic nie dokleil
