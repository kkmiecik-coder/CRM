# -*- coding: utf-8 -*-
# Testy przeplywu wysylki w run_quote_turn (fix/quotebot-wysylka-kontakt):
#  #1 e-mail + kod pocztowy w JEDNEJ wiadomosci -> zapis wyceny ORAZ oszacowanie wysylki
#     (kod nie ginie przez return bramki kontaktu przed bramka kodu pocztowego).
#  #2 pytanie o wysylke po cenie ("wycenisz wysylke?") -> deterministyczny przeplyw wysylki
#     (prosba o kod), NIE porownanie/LLM (LLM na to pytanie wypelnial 'porownania' -> off-topic).
import os, tempfile, json
os.environ.setdefault("OLX_CLIENT_ID", "x")
os.environ.setdefault("OLX_CLIENT_SECRET", "x")
os.environ.setdefault("OLX_REFRESH_TOKEN", "x")
os.environ["CRM_API_BASE"] = "https://crm.test"
os.environ["CRM_BOT_API_KEY"] = "KEY"
os.environ["BOT_QUOTE_CLIENT_TYPE"] = "Klient indywidualny"
os.environ["BOT_QUOTE_CW_AGENT_TOKEN"] = "TQ"
os.environ.setdefault("BRIDGE_DB", os.path.join(tempfile.mkdtemp(), "bridge_qship.db"))
import importlib
import config; importlib.reload(config)
db_mod = importlib.import_module("core.db"); db_mod.init_db()
qb = importlib.import_module("bots.quotebot"); importlib.reload(qb)

_KOMPLET = {"pozycje": [{"id": "1", "produkt": "blat", "dlugosc": "200", "szerokosc": "60",
                         "grubosc": "4", "gatunek": "dąb", "technologia": "lita", "klasa": "A/B",
                         "ilosc": "1", "wykonczenie": "surowe"}], "wspolne": {}}


def _patch(monkeypatch, replies, saved, chat_called):
    monkeypatch.setattr(qb, "cw_conv_status", lambda c: "pending")
    monkeypatch.setattr(qb, "cw_messages", lambda c, n: [{"role": "user", "text": "..."}])
    monkeypatch.setattr(qb, "cw_contact", lambda c: {"name": "", "identifier": ""})
    monkeypatch.setattr(qb, "cw_contact_full", lambda c: {"name": "Jan", "identifier": "", "email": "", "phone": ""})
    monkeypatch.setattr(qb, "retrieve", lambda q: [])
    # LLM (nano) na pytanie o wysylke blednie wypelnia 'porownania' — fix ma NIE dopuscic go do glosu.
    monkeypatch.setattr(qb, "chat", lambda messages, **kw: chat_called.append(1) or
                        ('{"odpowiedz":"","handoff":false,"pozycje":[],"wspolne":{},'
                         '"porownania":[{"id":"1","gatunek":"dąb"}]}', {"error_class": None}))
    monkeypatch.setattr(qb, "cw_agent_reply", lambda conv_id, text, **kw: replies.append(text) or True)
    monkeypatch.setattr(qb, "cw_bot_handoff", lambda conv_id, **kw: True)
    monkeypatch.setattr(qb, "cw_note", lambda conv_id, text, **kw: True)
    monkeypatch.setattr(qb.crm_calc, "get_options", lambda: {"finishing_options": []})
    monkeypatch.setattr(qb.crm_calc, "find_or_create_client",
                        lambda e, p, n, client_number=None: saved.update(email=e, phone=p) or
                        {"ok": True, "client": {"id": 1}})
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


# --- Fix #1: e-mail + kod pocztowy w jednej wiadomosci ---

def test_email_plus_kod_pocztowy_w_jednej_wiadomosci_liczy_wysylke(monkeypatch):
    replies, saved, chat_called = [], {}, []
    _patch(monkeypatch, replies, saved, chat_called)
    shipping = {}
    monkeypatch.setattr(qb.crm_calc, "shipping_quote",
                        lambda p, kod, o=None: shipping.update(kod=kod) or
                        {"ok": True, "carriers": 3, "carrier_name": "InPost",
                         "shipping_netto": 84.55, "shipping_brutto": 104.0})
    _seed(6101, priced=1, awaiting_contact=1, awaiting_postcode=1)
    qb.run_quote_turn(6101, 12, "m1", "jan@kowalski.pl 35-330")
    assert saved.get("email") == "jan@kowalski.pl", "e-mail zapisany (wycena)"
    assert shipping.get("kod") == "35-330", "kod z tej samej wiadomosci policzony do wysylki"
    assert any("InPost" in r and "104,00 zł" in r for r in replies), "komunikat o wysylce wyslany"


def test_sam_email_bez_kodu_nie_wola_wysylki(monkeypatch):
    """Regresja: sam e-mail (bez kodu) w awaiting_postcode NIE wola shipping_quote."""
    replies, saved, chat_called = [], {}, []
    _patch(monkeypatch, replies, saved, chat_called)
    called = []
    monkeypatch.setattr(qb.crm_calc, "shipping_quote", lambda p, kod, o=None: called.append(kod) or {"ok": False})
    _seed(6103, priced=1, awaiting_contact=1, awaiting_postcode=1)
    qb.run_quote_turn(6103, 12, "m1", "jan@kowalski.pl")
    assert saved.get("email") == "jan@kowalski.pl"
    assert not called, "bez kodu pocztowego nie liczymy wysylki"


# --- Fix #2: pytanie o wysylke nie odpala porownania/LLM ---

def test_pytanie_o_wysylke_prosi_o_kod_nie_porownanie(monkeypatch):
    replies, saved, chat_called = [], {}, []
    _patch(monkeypatch, replies, saved, chat_called)
    _seed(6102, priced=1)   # klient wczesniej nie podal kodu
    qb.run_quote_turn(6102, 12, "m1", "a wycenisz wysyłkę?")
    assert not chat_called, "pytanie o wysylke NIE idzie do LLM (a wiec nie do porownan)"
    combined = " ".join(replies).lower()
    assert "informacyjnie" not in combined, "brak off-topic porownania"
    assert "kod pocztow" in combined or "00-000" in combined, "bot (po)prosil o kod pocztowy"


def test_pytanie_o_wysylke_z_kodem_liczy_od_razu(monkeypatch):
    replies, saved, chat_called = [], {}, []
    _patch(monkeypatch, replies, saved, chat_called)
    shipping = {}
    monkeypatch.setattr(qb.crm_calc, "shipping_quote",
                        lambda p, kod, o=None: shipping.update(kod=kod) or
                        {"ok": True, "carriers": 2, "carrier_name": "DPD", "shipping_netto": 70.0,
                         "shipping_brutto": 86.1})
    _seed(6104, priced=1)
    qb.run_quote_turn(6104, 12, "m1", "policz wysyłkę na 35-330")
    assert not chat_called
    assert shipping.get("kod") == "35-330"
    assert any("DPD" in r for r in replies)


def test_korekta_z_wysylka_idzie_do_llm(monkeypatch):
    """Zabezpieczenie: wiadomosc z JAWNA korekta pozycji (mimo slowa 'wysylka') idzie do LLM,
    nie jest przechwycona przez bramke wysylki."""
    replies, saved, chat_called = [], {}, []
    _patch(monkeypatch, replies, saved, chat_called)
    _seed(6105, priced=1)
    qb.run_quote_turn(6105, 12, "m1", "zmień blat na jesion, a przy okazji ile wysyłka?")
    assert chat_called, "korekta pozycji ma pierwszenstwo — idzie do LLM"
