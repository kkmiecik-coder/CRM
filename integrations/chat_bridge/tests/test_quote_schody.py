# -*- coding: utf-8 -*-
# Test: schody wyceniane jak deski (wymiary stopnia + ilosc = liczba stopni), podstopnice osobno,
# nie-prostokatne/zdjecie -> handoff. Plus fix: pytanie o tozsamosc nie konczy sie handoffem.
import os, tempfile, json
os.environ.setdefault("OLX_CLIENT_ID", "x")
os.environ.setdefault("OLX_CLIENT_SECRET", "x")
os.environ.setdefault("OLX_REFRESH_TOKEN", "x")
os.environ["CRM_API_BASE"] = "https://crm.test"
os.environ["CRM_BOT_API_KEY"] = "KEY"
os.environ["BOT_QUOTE_CLIENT_TYPE"] = "Klient indywidualny"
os.environ["BOT_QUOTE_CW_AGENT_TOKEN"] = "TQ"
os.environ.setdefault("BRIDGE_DB", os.path.join(tempfile.mkdtemp(), "bridge_qschody.db"))
import importlib
import config; importlib.reload(config)
db_mod = importlib.import_module("core.db"); db_mod.init_db()
qb = importlib.import_module("bots.quotebot"); importlib.reload(qb)

_SCHODY = {"id": "1", "produkt": "schody", "dlugosc": "90", "szerokosc": "30", "grubosc": "4",
           "gatunek": "dąb", "technologia": "lita", "klasa": "A/B", "ilosc": "12", "wykonczenie": "surowe"}


# --- straznik kompletnosci: schody wymagaja wymiarow stopnia ---

def test_schody_z_wymiarami_stopnia_kompletne():
    assert qb._brakujace_pozycji(_SCHODY) == []


def test_schody_bez_wymiarow_dopytuje_o_wymiary():
    poz = {"produkt": "schody", "gatunek": "dąb", "technologia": "lita", "klasa": "A/B",
           "ilosc": "12", "wykonczenie": "surowe"}
    brak = qb._brakujace_pozycji(poz)
    assert "dlugosc" in brak and "szerokosc" in brak and "grubosc" in brak


def _patch(monkeypatch, replies, chat_json):
    monkeypatch.setattr(qb, "cw_conv_status", lambda c: "pending")
    monkeypatch.setattr(qb, "cw_messages", lambda c, n: [{"role": "user", "text": "..."}])
    monkeypatch.setattr(qb, "cw_contact", lambda c: {"name": "", "identifier": ""})
    monkeypatch.setattr(qb, "cw_contact_full", lambda c: {"name": "", "identifier": "", "email": "", "phone": ""})
    monkeypatch.setattr(qb, "retrieve", lambda q: [])
    monkeypatch.setattr(qb, "chat", lambda messages, **kw: chat_json)
    monkeypatch.setattr(qb, "cw_agent_reply", lambda conv_id, text, **kw: replies.append(text) or True)
    monkeypatch.setattr(qb, "cw_bot_handoff", lambda conv_id, **kw: replies.append("__HANDOFF__") or True)
    monkeypatch.setattr(qb, "cw_note", lambda conv_id, text, **kw: replies.append("__NOTE__:" + text) or True)
    monkeypatch.setattr(qb.crm_calc, "get_options", lambda: {"finishing_options": []})


def _seed(conv_id, dane, **flags):
    c = db_mod.db()
    c.execute("DELETE FROM quote_state WHERE conv_id=?", (conv_id,))
    c.execute("DELETE FROM quote_dane WHERE conv_id=?", (conv_id,))
    if dane is not None:
        c.execute("INSERT INTO quote_dane(conv_id, dane_json) VALUES(?,?)", (conv_id, json.dumps(dane)))
    cols = ["bot_turns"] + list(flags)
    c.execute("INSERT INTO quote_state(conv_id, %s) VALUES(%s)" % (",".join(cols), ",".join("?" * (len(cols) + 1))),
              tuple([conv_id, 1] + [flags[k] for k in flags]))
    c.commit(); c.close()


def test_schody_prostokatne_liczy_cene(monkeypatch):
    """Prostokatne schody z wymiarami stopnia + 'tak' -> CENA (12 desek), nie handoff."""
    replies = []
    _patch(monkeypatch, replies, '{"odpowiedz":"","handoff":false,"pozycje":[],"wspolne":{}}')
    monkeypatch.setattr(qb.crm_calc, "calculate",
                        lambda poz, opts: {"ok": True, "totals": {"total_brutto": 5000.0, "total_netto": 4065.0}})
    _seed(7101, {"pozycje": [_SCHODY], "wspolne": {}}, awaiting_confirm=1)
    qb.run_quote_turn(7101, 12, "m1", "tak, zgadza się")
    tekst = " ".join(replies)
    assert "5000" in tekst or "5 000" in tekst, "schody prostokatne -> cena"
    assert "__HANDOFF__" not in replies


def test_schody_krecone_handoff(monkeypatch):
    """Schody kręcone (nie-prostokat) -> handoff, nie wycena."""
    replies = []
    _patch(monkeypatch, replies, '{"odpowiedz":"Dobrze","handoff":false,"pozycje":[{"id":"1","produkt":"schody"}],"wspolne":{}}')
    _seed(7102, None)
    qb.run_quote_turn(7102, 12, "m1", "chcę schody kręcone dębowe, 14 stopni")
    assert "__HANDOFF__" in replies
    assert any("nietypow" in r.lower() for r in replies if r.startswith("__NOTE__"))


def test_pytanie_o_bota_nie_konczy_handoffem(monkeypatch):
    """'Czy jesteś botem?' -> bot odpowiada uczciwie, NIE oddaje rozmowy (nawet gdy LLM ustawi handoff)."""
    replies = []
    _patch(monkeypatch, replies,
           '{"odpowiedz":"","handoff":true,"powod":"klient pyta czy bot, przekazuję do konsultanta","pozycje":[],"wspolne":{}}')
    _seed(7103, None)
    qb.run_quote_turn(7103, 12, "m1", "czy jesteś botem?")
    tekst = " ".join(replies)
    assert "__HANDOFF__" not in replies, "pytanie o bota NIE moze oddawac rozmowy"
    assert "asysten" in tekst.lower() or "ai" in tekst.lower(), "bot odpowiada uczciwie"
