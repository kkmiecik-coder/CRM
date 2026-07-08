# -*- coding: utf-8 -*-
# Test: obraz pomocniczy (kontekstowy: wymiary/krawedzie/kolory) wysylany PO tekscie bota, nie przed.
import os, tempfile, json
os.environ.setdefault("OLX_CLIENT_ID", "x")
os.environ.setdefault("OLX_CLIENT_SECRET", "x")
os.environ.setdefault("OLX_REFRESH_TOKEN", "x")
os.environ["CRM_API_BASE"] = "https://crm.test"
os.environ["CRM_BOT_API_KEY"] = "KEY"
os.environ["BOT_QUOTE_CLIENT_TYPE"] = "Klient indywidualny"
os.environ["BOT_QUOTE_CW_AGENT_TOKEN"] = "TQ"
os.environ.setdefault("BRIDGE_DB", os.path.join(tempfile.mkdtemp(), "bridge_qimgord.db"))
import importlib
import config; importlib.reload(config)
db_mod = importlib.import_module("core.db"); db_mod.init_db()
qb = importlib.import_module("bots.quotebot"); importlib.reload(qb)


def test_obraz_kontekstowy_po_tekscie(monkeypatch):
    events = []
    monkeypatch.setattr(qb, "cw_conv_status", lambda c: "pending")
    monkeypatch.setattr(qb, "cw_messages", lambda c, n: [{"role": "user", "text": "chcę blat dębowy"}])
    monkeypatch.setattr(qb, "cw_contact", lambda c: {"name": "", "identifier": ""})
    monkeypatch.setattr(qb, "cw_contact_full", lambda c: {"name": "", "identifier": "", "email": "", "phone": ""})
    monkeypatch.setattr(qb, "retrieve", lambda q: [])
    # LLM: normalna odpowiedz proszaca o wymiary (dane niekompletne -> sciezka zwyklej odpowiedzi)
    monkeypatch.setattr(qb, "chat", lambda messages, **kw:
                        '{"odpowiedz":"Dzień dobry! Proszę podać wymiary blatu.","handoff":false,'
                        '"pozycje":[{"id":"1","produkt":"blat","gatunek":"dąb"}],"wspolne":{}}')
    monkeypatch.setattr(qb, "cw_agent_reply", lambda conv_id, text, **kw: events.append(("TEXT", text)) or True)
    # obraz kontekstowy zamockowany na marker — sprawdzamy TYLKO kolejnosc
    monkeypatch.setattr(qb, "_obrazy_kontekstowe", lambda c, content, dane: events.append(("IMG", None)))
    monkeypatch.setattr(qb.crm_calc, "get_options", lambda: {"finishing_options": []})
    c = db_mod.db()
    c.execute("DELETE FROM quote_state WHERE conv_id=?", (8801,))
    c.execute("DELETE FROM quote_dane WHERE conv_id=?", (8801,))
    c.commit(); c.close()

    qb.run_quote_turn(8801, 12, "m1", "chcę blat dębowy")

    kinds = [k for k, _ in events]
    assert "TEXT" in kinds and "IMG" in kinds, "powinien pojść tekst i obraz kontekstowy"
    assert kinds.index("TEXT") < kinds.index("IMG"), "obraz kontekstowy MUSI być PO tekście bota"
