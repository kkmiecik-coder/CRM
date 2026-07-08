# -*- coding: utf-8 -*-
# Test FAZA 0 zad. 10: kontakt bez pulapek. SB-01 (kontakt+korekta), LS-02 (globalny przechwyt po
# cenie), API-13 (normalizacja e-mail/telefon).
import os, tempfile, json
os.environ.setdefault("OLX_CLIENT_ID", "x")
os.environ.setdefault("OLX_CLIENT_SECRET", "x")
os.environ.setdefault("OLX_REFRESH_TOKEN", "x")
os.environ["CRM_API_BASE"] = "https://crm.test"
os.environ["CRM_BOT_API_KEY"] = "KEY"
os.environ["BOT_QUOTE_CLIENT_TYPE"] = "Klient indywidualny"
os.environ["BOT_QUOTE_CW_AGENT_TOKEN"] = "TQ"
os.environ.setdefault("BRIDGE_DB", os.path.join(tempfile.mkdtemp(), "bridge_qcontact.db"))
import importlib
import config; importlib.reload(config)
db_mod = importlib.import_module("core.db"); db_mod.init_db()
qb = importlib.import_module("bots.quotebot"); importlib.reload(qb)
crm = importlib.import_module("bots.crm_calc")

_KOMPLET = {"pozycje": [{"id": "1", "produkt": "blat", "dlugosc": "200", "szerokosc": "60",
                         "grubosc": "4", "gatunek": "dąb", "technologia": "lita", "klasa": "A/B",
                         "ilosc": "1", "wykonczenie": "surowe"}], "wspolne": {}}


def _patch(monkeypatch, replies, saved):
    monkeypatch.setattr(qb, "cw_conv_status", lambda c: "pending")
    monkeypatch.setattr(qb, "cw_messages", lambda c, n: [{"role": "user", "text": "..."}])
    monkeypatch.setattr(qb, "cw_contact", lambda c: {"name": "", "identifier": ""})
    monkeypatch.setattr(qb, "cw_contact_full", lambda c: {"name": "Jan", "identifier": "", "email": "", "phone": ""})
    monkeypatch.setattr(qb, "retrieve", lambda q: [])
    monkeypatch.setattr(qb, "chat", lambda messages, **kw: '{"odpowiedz":"Jasne.","handoff":false,"pozycje":[],"wspolne":{}}')
    monkeypatch.setattr(qb, "cw_agent_reply", lambda conv_id, text, **kw: replies.append(text) or True)
    monkeypatch.setattr(qb, "cw_bot_handoff", lambda conv_id, **kw: True)
    monkeypatch.setattr(qb, "cw_note", lambda conv_id, text, **kw: True)
    monkeypatch.setattr(qb.crm_calc, "get_options", lambda: {"finishing_options": []})
    monkeypatch.setattr(qb.crm_calc, "find_or_create_client",
                        lambda e, p, n: saved.update(email=e, phone=p) or {"ok": True, "client": {"id": 1}})
    monkeypatch.setattr(qb.crm_calc, "create_quote",
                        lambda p, o, cid, notes="": {"ok": True, "quote_number": "W/1", "public_url": "https://crm/q/z"})


def _seed(conv_id, **flags):
    c = db_mod.db()
    c.execute("DELETE FROM quote_state WHERE conv_id=?", (conv_id,))
    c.execute("DELETE FROM quote_dane WHERE conv_id=?", (conv_id,))
    c.execute("INSERT INTO quote_dane(conv_id, dane_json) VALUES(?,?)", (conv_id, json.dumps(_KOMPLET)))
    cols = ["bot_turns"] + list(flags)
    c.execute("INSERT INTO quote_state(conv_id, %s) VALUES(%s)" % (",".join(cols), ",".join("?" * (len(cols) + 1))),
              tuple([conv_id, 1] + [flags[k] for k in flags]))
    c.commit(); c.close()


def test_sb01_kontakt_plus_korekta_nie_zapisuje_starej(monkeypatch):
    """SB-01: mail + korekta w jednej wiadomosci -> NIE zapisujemy starej wyceny; tura idzie dalej."""
    replies, saved = [], {}
    _patch(monkeypatch, replies, saved)
    _seed(6001, priced=1, awaiting_contact=1)
    qb.run_quote_turn(6001, 12, "m1", "mój mail to jan@kowalski.pl, ale najpierw zmieńcie dąb na jesion")
    assert not saved, "przy kontakcie+korekcie NIE zapisujemy od razu (stara wycena)"
    assert not any("crm/q/z" in r for r in replies), "brak linku do starej wyceny"


def test_sb01_sam_kontakt_zapisuje(monkeypatch):
    """Sam kontakt (bez korekty) w awaiting_contact -> zapis od razu (regresja)."""
    replies, saved = [], {}
    _patch(monkeypatch, replies, saved)
    _seed(6002, priced=1, awaiting_contact=1)
    qb.run_quote_turn(6002, 12, "m1", "jan@kowalski.pl")
    assert saved.get("email") == "jan@kowalski.pl"
    assert any("crm/q/z" in r for r in replies)


def test_ls02_globalny_przechwyt_po_cenie(monkeypatch):
    """LS-02: po cenie i po odmowie (awaiting_contact=0) spontaniczny mail -> i tak zapis wyceny."""
    replies, saved = [], {}
    _patch(monkeypatch, replies, saved)
    _seed(6003, priced=1)   # brak awaiting_contact (klient wczesniej odmowil)
    qb.run_quote_turn(6003, 12, "m1", "a jednak zapiszcie, jan.kowalski@gmail.com")
    assert saved.get("email") == "jan.kowalski@gmail.com", "spontaniczny kontakt po cenie zapisuje wycene"
    assert any("crm/q/z" in r for r in replies)


def test_api13_normalizacja_email_i_tel(monkeypatch):
    """API-13: e-mail -> lower, telefon -> 9 cyfr krajowych (dedup po dokladnym stringu dziala)."""
    captured = {}
    monkeypatch.setattr(crm, "_post", lambda path, body: captured.update(body) or {"ok": True, "client": {"id": 1}})
    crm.find_or_create_client("Jan.Kowalski@GMAIL.com", "+48 501 234 567", "Jan")
    assert captured["email"] == "jan.kowalski@gmail.com"
    assert captured["phone"] == "501234567"
