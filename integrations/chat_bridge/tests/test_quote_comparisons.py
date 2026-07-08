# -*- coding: utf-8 -*-
# Test FAZA 0 zad. 5: porownania bez slepych zaulkow — zamiast pustej odpowiedzi -> RuntimeError
# -> 3 retry -> handoff (MS-02) albo cichego konca tury (SB-04), bot daje deterministyczna odpowiedz.
import os, tempfile, json
os.environ.setdefault("OLX_CLIENT_ID", "x")
os.environ.setdefault("OLX_CLIENT_SECRET", "x")
os.environ.setdefault("OLX_REFRESH_TOKEN", "x")
os.environ["CRM_API_BASE"] = "https://crm.test"
os.environ["CRM_BOT_API_KEY"] = "KEY"
os.environ["BOT_QUOTE_CLIENT_TYPE"] = "Klient indywidualny"
os.environ["BOT_QUOTE_CW_AGENT_TOKEN"] = "TQ"
os.environ.setdefault("BRIDGE_DB", os.path.join(tempfile.mkdtemp(), "bridge_qcmp.db"))
import importlib
import config; importlib.reload(config)
db_mod = importlib.import_module("core.db"); db_mod.init_db()
qb = importlib.import_module("bots.quotebot"); importlib.reload(qb)


def _patch(monkeypatch, replies, chat_json):
    monkeypatch.setattr(qb, "cw_conv_status", lambda c: "pending")
    monkeypatch.setattr(qb, "cw_messages", lambda c, n: [{"role": "user", "text": "a ile w jesionie?"}])
    monkeypatch.setattr(qb, "cw_contact", lambda c: {"name": "", "identifier": ""})
    monkeypatch.setattr(qb, "cw_contact_full", lambda c: {"name": "", "identifier": "", "email": "", "phone": ""})
    monkeypatch.setattr(qb, "retrieve", lambda q: [])
    monkeypatch.setattr(qb, "chat", lambda messages, **kw: chat_json)
    monkeypatch.setattr(qb, "cw_agent_reply", lambda conv_id, text, **kw: replies.append(text) or True)
    monkeypatch.setattr(qb, "cw_bot_handoff", lambda conv_id, **kw: replies.append("__HANDOFF__") or True)
    monkeypatch.setattr(qb, "cw_note", lambda conv_id, text, **kw: True)
    monkeypatch.setattr(qb.crm_calc, "get_options", lambda: {"finishing_options": []})


def _reset(conv_id, dane, **flags):
    c = db_mod.db()
    c.execute("DELETE FROM quote_state WHERE conv_id=?", (conv_id,))
    c.execute("DELETE FROM quote_dane WHERE conv_id=?", (conv_id,))
    if dane is not None:
        c.execute("INSERT INTO quote_dane(conv_id, dane_json) VALUES(?,?)", (conv_id, json.dumps(dane)))
    cols = ["bot_turns"] + list(flags.keys())
    vals = [1] + [flags[k] for k in flags]
    c.execute("INSERT INTO quote_state(conv_id, %s) VALUES(%s)" % (",".join(cols), ",".join("?" * (len(cols) + 1))),
              tuple([conv_id] + vals))
    c.commit(); c.close()


_POROWNANIE = '{"odpowiedz":"","handoff":false,"pozycje":[],"wspolne":{},"porownania":[{"id":"1","gatunek":"jesion"}]}'


def test_porownanie_przed_pierwsza_cena_nie_handoff(monkeypatch):
    """MS-02: klient pyta o porownanie w trakcie zbierania (brak ceny) — LLM daje puste 'odpowiedz'
    + 'porownania'. Zamiast RuntimeError->handoff bot deterministycznie odpowiada."""
    replies = []
    _patch(monkeypatch, replies, _POROWNANIE)
    dane = {"pozycje": [{"id": "1", "produkt": "blat", "gatunek": "dąb"}], "wspolne": {}}  # niekompletne, brak ceny
    _reset(1001, dane)
    qb.run_quote_turn(1001, 12, "m1", "a ile w jesionie?")
    assert replies, "bot musi cos odpowiedziec (nie cisza/handoff)"
    assert "__HANDOFF__" not in replies
    assert any("wycen" in t.lower() for t in replies), "deterministyczna info o porownaniu po wycenie"


def test_porownanie_po_cenie_ale_druga_pozycja_niekompletna(monkeypatch):
    """SB-04: cena wyslana (priced), ale inna pozycja niekompletna -> _czy_porownanie False.
    Bot NIE moze zamilknac — dopytuje o braki zamiast cichego return."""
    replies = []
    _patch(monkeypatch, replies, _POROWNANIE)
    dane = {"pozycje": [
        {"id": "1", "produkt": "blat", "dlugosc": "200", "szerokosc": "60", "grubosc": "4",
         "gatunek": "dąb", "technologia": "lita", "klasa": "A/B", "ilosc": "1", "wykonczenie": "surowe"},
        {"id": "2", "produkt": "parapet"}], "wspolne": {}}  # pozycja 2 niekompletna
    _reset(1002, dane, priced=1)
    qb.run_quote_turn(1002, 12, "m1", "a ile ten blat w jesionie?")
    assert replies, "bot nie moze zamilknac"
    assert "__HANDOFF__" not in replies
