# -*- coding: utf-8 -*-
# Test FAZA 0 zad. 9: MS-05 (komunikat przy nieudanym zapisie), MS-12 (kontrola wysylki wysylki),
# MS-04 (brak drugiej ceny po retry), atomowy claim + szeregowanie per conv (API-09/AR-04/API-06).
import os, tempfile, json
os.environ.setdefault("OLX_CLIENT_ID", "x")
os.environ.setdefault("OLX_CLIENT_SECRET", "x")
os.environ.setdefault("OLX_REFRESH_TOKEN", "x")
os.environ["CRM_API_BASE"] = "https://crm.test"
os.environ["CRM_BOT_API_KEY"] = "KEY"
os.environ["BOT_QUOTE_CLIENT_TYPE"] = "Klient indywidualny"
os.environ["BOT_QUOTE_CW_AGENT_TOKEN"] = "TQ"
os.environ.setdefault("BRIDGE_DB", os.path.join(tempfile.mkdtemp(), "bridge_qidem.db"))
import importlib
import pytest
import config; importlib.reload(config)
db_mod = importlib.import_module("core.db"); db_mod.init_db()
qb = importlib.import_module("bots.quotebot"); importlib.reload(qb)
qw = importlib.import_module("quote_worker"); importlib.reload(qw)

_KOMPLET = {"pozycje": [{"id": "1", "produkt": "blat", "dlugosc": "200", "szerokosc": "60",
                         "grubosc": "4", "gatunek": "dąb", "technologia": "lita", "klasa": "A/B",
                         "ilosc": "1", "wykonczenie": "surowe"}], "wspolne": {}}


def _patch(monkeypatch, replies):
    monkeypatch.setattr(qb, "cw_conv_status", lambda c: "pending")
    monkeypatch.setattr(qb, "cw_messages", lambda c, n: [{"role": "user", "text": "tak"}])
    monkeypatch.setattr(qb, "cw_contact", lambda c: {"name": "", "identifier": ""})
    monkeypatch.setattr(qb, "cw_contact_full", lambda c: {"name": "", "identifier": "", "email": "", "phone": ""})
    monkeypatch.setattr(qb, "retrieve", lambda q: [])
    monkeypatch.setattr(qb, "chat", lambda messages, **kw:
                        ('{"odpowiedz":"","handoff":false,"pozycje":[],"wspolne":{}}', {"error_class": None}))
    monkeypatch.setattr(qb, "cw_agent_reply", lambda conv_id, text, **kw: replies.append(text) or True)
    monkeypatch.setattr(qb, "cw_bot_handoff", lambda conv_id, **kw: replies.append("__HANDOFF__") or True)
    monkeypatch.setattr(qb, "cw_note", lambda conv_id, text, **kw: True)
    monkeypatch.setattr(qb.crm_calc, "get_options", lambda: {"finishing_options": []})


def test_ms05_zapis_padl_komunikat_i_handoff(monkeypatch):
    """MS-05: klient podaje mail, find_or_create pada -> klient dostaje komunikat + handoff (nie cisza)."""
    replies = []
    _patch(monkeypatch, replies)
    monkeypatch.setattr(qb.crm_calc, "find_or_create_client",
                        lambda e, p, n, client_number=None: {"ok": False, "client": {}})
    c = db_mod.db()
    c.execute("DELETE FROM quote_state WHERE conv_id=?", (5001,))
    c.execute("DELETE FROM quote_dane WHERE conv_id=?", (5001,))
    c.execute("INSERT INTO quote_dane(conv_id, dane_json) VALUES(?,?)", (5001, json.dumps(_KOMPLET)))
    c.execute("INSERT INTO quote_state(conv_id, bot_turns, priced, awaiting_contact) VALUES(?,1,1,1)", (5001,))
    c.commit(); c.close()
    qb.run_quote_turn(5001, 12, "m1", "jan@kowalski.pl")
    assert any("problem techniczny z zapisem" in r for r in replies), "koniec ciszy po podanym mailu"
    assert "__HANDOFF__" in replies


def test_ms12_wysylka_pad_rzuca_flaga_zostaje(monkeypatch):
    """MS-12: pad POST z kosztem wysylki -> RuntimeError, awaiting_postcode NIE gasnie."""
    replies = []
    _patch(monkeypatch, replies)
    monkeypatch.setattr(qb, "cw_agent_reply", lambda conv_id, text, **kw: False)  # kazda wysylka pada
    monkeypatch.setattr(qb.crm_calc, "shipping_quote",
                        lambda poz, kod, opts: {"ok": True, "carriers": [1], "carrier_name": "X",
                                                "shipping_brutto": 50})
    c = db_mod.db()
    c.execute("DELETE FROM quote_state WHERE conv_id=?", (5002,))
    c.execute("DELETE FROM quote_dane WHERE conv_id=?", (5002,))
    c.execute("INSERT INTO quote_dane(conv_id, dane_json) VALUES(?,?)", (5002, json.dumps(_KOMPLET)))
    c.execute("INSERT INTO quote_state(conv_id, bot_turns, awaiting_postcode) VALUES(?,1,1)", (5002,))
    c.commit(); c.close()
    with pytest.raises(RuntimeError):
        qb.run_quote_turn(5002, 12, "m1", "kod 30-059")
    c = db_mod.db()
    row = c.execute("SELECT awaiting_postcode FROM quote_state WHERE conv_id=5002").fetchone()
    c.close()
    assert row["awaiting_postcode"] == 1, "flaga zostaje -> retry ponowi z kodem"


def test_ms04_po_cenie_brak_drugiej_ceny(monkeypatch):
    """MS-04: priced=1, LLM znow zglasza handoff-komplet -> NIE druga cena/podsumowanie."""
    replies = []
    _patch(monkeypatch, replies)
    monkeypatch.setattr(qb, "chat", lambda messages, **kw:
                        ('{"odpowiedz":"Proszę bardzo.","handoff":true,"powod":"klient potwierdził dane do wyceny","pozycje":[],"wspolne":{}}',
                         {"error_class": None}))
    calc = {"n": 0}
    def _calc(poz, opts):
        calc["n"] += 1
        return {"ok": True, "totals": {"total_brutto": 100.0, "total_netto": 80.0}}
    monkeypatch.setattr(qb.crm_calc, "calculate", _calc)
    c = db_mod.db()
    c.execute("DELETE FROM quote_state WHERE conv_id=?", (5003,))
    c.execute("DELETE FROM quote_dane WHERE conv_id=?", (5003,))
    c.execute("INSERT INTO quote_dane(conv_id, dane_json) VALUES(?,?)", (5003, json.dumps(_KOMPLET)))
    # priced=1, awaiting_confirm=0 (cena juz poszla, czekamy na kontakt)
    c.execute("INSERT INTO quote_state(conv_id, bot_turns, priced, awaiting_contact) VALUES(?,1,1,1)", (5003,))
    c.commit(); c.close()
    qb.run_quote_turn(5003, 12, "m1", "no i co dalej")
    assert calc["n"] == 0, "po cenie NIE liczymy drugiej ceny"
    assert not any("Podsumowuję dane" in r for r in replies)


# ---- worker: atomowy claim + szeregowanie per conv ----

def _ins_queue(qid, conv_id, status="pending", next_at=0):
    c = db_mod.db()
    c.execute("INSERT OR REPLACE INTO quote_queue(id, conv_id, inbox_id, message_id, content, "
              "attachments, status, attempts, next_at) VALUES(?,?,?,?,?,?,?,0,?)",
              (qid, conv_id, 1, "m%s" % qid, "tresc", None, status, next_at))
    c.commit(); c.close()


def test_worker_claim_oznacza_sent(monkeypatch):
    c = db_mod.db(); c.execute("DELETE FROM quote_queue"); c.commit(); c.close()
    _ins_queue(1, 900)
    monkeypatch.setattr(qw, "run_quote_turn", lambda *a, **k: None)
    assert qw.process_one(1000.0) is True
    c = db_mod.db()
    st = c.execute("SELECT status FROM quote_queue WHERE id=1").fetchone()["status"]
    c.close()
    assert st == "sent"


def test_worker_szereguje_per_conv(monkeypatch):
    """API-06: nowszy rekord rozmowy nie jest brany, gdy starszy tej samej rozmowy czeka (retry)."""
    c = db_mod.db(); c.execute("DELETE FROM quote_queue"); c.commit(); c.close()
    _ins_queue(1, 901, status="pending", next_at=99999)   # starszy, czeka na retry (przyszlosc)
    _ins_queue(2, 901, status="pending", next_at=0)        # nowszy, gotowy
    monkeypatch.setattr(qw, "run_quote_turn", lambda *a, **k: None)
    # id=1 nie gotowy (next_at przyszlosc), id=2 zablokowany przez starszego -> nic gotowego
    assert qw.process_one(1000.0) is False
    c = db_mod.db()
    st2 = c.execute("SELECT status FROM quote_queue WHERE id=2").fetchone()["status"]
    c.close()
    assert st2 == "pending", "nowszy rekord czeka na starszy tej samej rozmowy"
