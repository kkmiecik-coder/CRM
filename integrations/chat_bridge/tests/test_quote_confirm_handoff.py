# -*- coding: utf-8 -*-
# Test FAZA 0 zad. 2: rozdzielenie potwierdzenia od handoffu (pole 'potwierdzono' sprawdzane
# PRZED out['handoff'] w stanie awaiting). Znaleziska: PL-02, RX-09.
import os, tempfile, json
os.environ.setdefault("OLX_CLIENT_ID", "x")
os.environ.setdefault("OLX_CLIENT_SECRET", "x")
os.environ.setdefault("OLX_REFRESH_TOKEN", "x")
os.environ["CRM_API_BASE"] = "https://crm.test"
os.environ["CRM_BOT_API_KEY"] = "KEY"
os.environ["BOT_QUOTE_CLIENT_TYPE"] = "Klient indywidualny"
os.environ["BOT_QUOTE_CW_AGENT_TOKEN"] = "TQ"
os.environ.setdefault("BRIDGE_DB", os.path.join(tempfile.mkdtemp(), "bridge_qconfirm.db"))
import importlib
import config; importlib.reload(config)
db_mod = importlib.import_module("core.db"); db_mod.init_db()
qb = importlib.import_module("bots.quotebot"); importlib.reload(qb)

_KOMPLET = {"pozycje": [{"id": "1", "produkt": "blat", "dlugosc": "200", "szerokosc": "60",
                         "grubosc": "4", "gatunek": "dąb", "technologia": "lita", "klasa": "A/B",
                         "ilosc": "2", "wykonczenie": "olejowane", "finishing_id": 7}],
            "wspolne": {}}


def _seed(conv_id, dane, awaiting=1):
    c = db_mod.db()
    c.execute("DELETE FROM quote_state WHERE conv_id=?", (conv_id,))
    c.execute("DELETE FROM quote_dane WHERE conv_id=?", (conv_id,))
    c.execute("INSERT INTO quote_dane(conv_id, dane_json) VALUES(?,?)", (conv_id, json.dumps(dane)))
    c.execute("INSERT INTO quote_state(conv_id, bot_turns, awaiting_confirm) VALUES(?,1,?)",
              (conv_id, awaiting))
    c.commit(); c.close()


def _patch(monkeypatch, replies, chat_json):
    monkeypatch.setattr(qb, "cw_conv_status", lambda c: "pending")
    monkeypatch.setattr(qb, "cw_messages", lambda c, n: [{"role": "user", "text": "..."}])
    monkeypatch.setattr(qb, "cw_contact", lambda c: {"name": "", "identifier": ""})
    monkeypatch.setattr(qb, "cw_contact_full", lambda c: {"name": "", "identifier": "", "email": "", "phone": ""})
    monkeypatch.setattr(qb, "retrieve", lambda q: [])
    monkeypatch.setattr(qb, "chat", lambda messages, **kw: (chat_json, {"error_class": None}))
    monkeypatch.setattr(qb, "cw_agent_reply", lambda conv_id, text, **kw: replies.append(text) or True)
    monkeypatch.setattr(qb, "cw_bot_handoff", lambda conv_id, **kw: replies.append("__HANDOFF__") or True)
    monkeypatch.setattr(qb, "cw_note", lambda conv_id, text, **kw: True)
    monkeypatch.setattr(qb.crm_calc, "get_options", lambda: {"finishing_options": [{"id": 7, "full_path": "Olejowanie"}]})
    monkeypatch.setattr(qb.crm_calc, "calculate",
                        lambda pozycje, opts: {"ok": True, "totals": {"total_brutto": 1230.0, "total_netto": 1000.0}})
    # LS-01: lead zawsze zapisany, nawet bez kontaktu (identity w tych testach jest pusta) —
    # find_or_create_client/create_quote sa teraz wolane w kazdej turze z cena.
    monkeypatch.setattr(qb.crm_calc, "find_or_create_client",
                        lambda e, p, n, client_number=None: {"ok": True, "matched": False,
                                                             "created": True, "client": {"id": 1}})
    monkeypatch.setattr(qb.crm_calc, "create_quote",
                        lambda poz, o, cid, notes="": {"ok": True, "quote_number": "W/1",
                                                       "public_url": "https://crm/q/z"})


def test_potwierdzenie_z_blednym_handoff_konsultant_liczy_cene(monkeypatch):
    """PL-02: awaiting + komplet, klient potwierdza, a LLM (parafrazujac persone) ustawia
    handoff=true z powodem zawierajacym 'konsultant'. Bez fixu _POWOD_PRZEPUSC lapie 'konsultant'
    i oddaje rozmowe czlowiekowi zamiast policzyc cene. Po fixie: potwierdzenie ma pierwszenstwo."""
    replies = []
    _patch(monkeypatch, replies,
           '{"odpowiedz":"","handoff":true,"powod":"klient potwierdził dane, przekazuję do konsultanta","pozycje":[],"wspolne":{}}')
    _seed(201, _KOMPLET, awaiting=1)
    qb.run_quote_turn(201, 12, "m1", "Wszystko się zgadza, proszę działać")
    tekst = " ".join(replies)
    assert "__HANDOFF__" not in replies, "potwierdzona wycena NIE moze uciekac do czlowieka"
    assert "1230" in tekst or "1 230" in tekst, "cena powinna zostac policzona i wyslana"
    c = db_mod.db()
    row = c.execute("SELECT priced FROM quote_state WHERE conv_id=201").fetchone()
    c.close()
    assert row and row["priced"] == 1


def test_pole_potwierdzono_liczy_cene_bez_regexu(monkeypatch):
    """Pole 'potwierdzono'=true od LLM liczy cene nawet gdy tresc nie pasuje do _POTW_RE
    (potwierdzenie naturalne, ktorego regex nie lapie)."""
    replies = []
    _patch(monkeypatch, replies,
           '{"odpowiedz":"","handoff":false,"potwierdzono":true,"pozycje":[],"wspolne":{}}')
    _seed(202, _KOMPLET, awaiting=1)
    qb.run_quote_turn(202, 12, "m2", "no to ruszamy z tym")
    tekst = " ".join(replies)
    assert "1230" in tekst or "1 230" in tekst
    assert "__HANDOFF__" not in replies


def test_korekta_w_awaiting_nie_liczy_ceny_mimo_potwierdzono(monkeypatch):
    """Gdy klient w stanie awaiting koryguje pozycje (zmienione), nie wolno liczyc ceny na
    starych danych — nawet jesli LLM ustawi potwierdzono=true; system wysyla nowe podsumowanie."""
    replies = []
    _patch(monkeypatch, replies,
           '{"odpowiedz":"","handoff":false,"potwierdzono":true,'
           '"pozycje":[{"id":"1","dlugosc":"180"}],"wspolne":{}}')
    _seed(203, _KOMPLET, awaiting=1)
    qb.run_quote_turn(203, 12, "m3", "zmień długość na 180")
    tekst = " ".join(replies)
    assert any("Podsumowuję dane" in t for t in replies), "korekta -> nowe podsumowanie"
    assert "1230" not in tekst and "1 230" not in tekst, "nie liczymy ceny na skorygowanych danych"


def test_prawdziwa_prosba_o_czlowieka_w_awaiting_nadal_oddaje(monkeypatch):
    """Regresja: jawna prosba o konsultanta w stanie awaiting nadal oddaje rozmowe (bramka
    prosby o czlowieka jest PRZED bramka potwierdzenia)."""
    replies = []
    _patch(monkeypatch, replies,
           '{"odpowiedz":"","handoff":false,"pozycje":[],"wspolne":{}}')
    _seed(204, _KOMPLET, awaiting=1)
    qb.run_quote_turn(204, 12, "m4", "proszę połączyć mnie z konsultantem")
    assert "__HANDOFF__" in replies, "jawna prosba o czlowieka nadal oddaje rozmowe"
