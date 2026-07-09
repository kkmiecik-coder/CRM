# -*- coding: utf-8 -*-
# Test: quote-bot po komplecie i potwierdzeniu -> liczy cene i wysyla; z kontaktem zapisuje wycene.
import os, tempfile, json
os.environ.setdefault("OLX_CLIENT_ID", "x")
os.environ.setdefault("OLX_CLIENT_SECRET", "x")
os.environ.setdefault("OLX_REFRESH_TOKEN", "x")
os.environ["CRM_API_BASE"] = "https://crm.test"
os.environ["CRM_BOT_API_KEY"] = "KEY"
os.environ["BOT_QUOTE_CLIENT_TYPE"] = "Klient indywidualny"
os.environ["BOT_QUOTE_CW_AGENT_TOKEN"] = "TQ"
os.environ["BRIDGE_DB"] = os.path.join(tempfile.mkdtemp(), "bridge_qbot.db")
import importlib
import config; importlib.reload(config)
db_mod = importlib.import_module("core.db"); db_mod.init_db()
qb = importlib.import_module("bots.quotebot"); importlib.reload(qb)

_KOMPLET = {"pozycje": [{"id": "1", "produkt": "blat", "dlugosc": "200", "szerokosc": "60",
                         "grubosc": "4", "gatunek": "dąb", "technologia": "lita", "klasa": "A/B",
                         "ilosc": "2", "wykonczenie": "olejowane", "finishing_id": 7}],
            "wspolne": {}}


def _seed_state(conv_id, dane, awaiting=1):
    c = db_mod.db()
    c.execute("DELETE FROM quote_state WHERE conv_id=?", (conv_id,))
    c.execute("DELETE FROM quote_dane WHERE conv_id=?", (conv_id,))
    c.execute("INSERT INTO quote_dane(conv_id, dane_json) VALUES(?,?)",
              (conv_id, json.dumps(dane)))
    c.execute("INSERT INTO quote_state(conv_id, bot_turns, awaiting_confirm) VALUES(?,1,?)",
              (conv_id, awaiting))
    c.commit(); c.close()


def _patch_common(monkeypatch, replies):
    # run_quote_turn ZAWSZE woła chat()/retrieve()/cw_contact() zanim dojdzie do
    # deterministycznej ścieżki potwierdzenia — wszystkie muszą być zamockowane (zero sieci).
    monkeypatch.setattr(qb, "cw_conv_status", lambda c: "pending")
    monkeypatch.setattr(qb, "cw_messages", lambda c, n: [{"role": "user", "text": "tak"}])
    monkeypatch.setattr(qb, "cw_contact", lambda c: {"name": "", "identifier": ""})
    monkeypatch.setattr(qb, "cw_contact_full", lambda c: {"name": "", "identifier": "", "email": "", "phone": ""})
    monkeypatch.setattr(qb, "retrieve", lambda q: [])
    # LLM: brak zmian pozycji + handoff=false -> deterministyczne potwierdzenie („tak") wygrywa.
    monkeypatch.setattr(qb, "chat",
                        lambda messages, **kw: '{"odpowiedz":"","handoff":false,"pozycje":[],"wspolne":{}}')
    monkeypatch.setattr(qb, "cw_agent_reply",
                        lambda conv_id, text, **kw: replies.append((text, kw)) or True)
    monkeypatch.setattr(qb, "cw_note", lambda conv_id, text, **kw: True)
    monkeypatch.setattr(qb, "cw_bot_handoff", lambda conv_id, **kw: True)
    monkeypatch.setattr(qb.crm_calc, "get_options", lambda: {"finishing_options": [{"id": 7, "full_path": "Olejowanie"}]})
    # LS-01: lead zawsze zapisany, nawet bez kontaktu — find_or_create_client/create_quote
    # sa teraz wolane w kazdej turze z cena.
    monkeypatch.setattr(qb.crm_calc, "find_or_create_client",
                        lambda e, p, n, client_number=None: {"ok": True, "matched": False,
                                                             "created": True, "client": {"id": 1}})
    monkeypatch.setattr(qb.crm_calc, "create_quote",
                        lambda poz, o, cid, notes="": {"ok": True, "quote_number": "W/1",
                                                       "public_url": "https://crm/q/z"})


def test_potwierdzenie_bez_kontaktu_wysyla_cene_i_prosi_o_kontakt(monkeypatch):
    replies = []
    _patch_common(monkeypatch, replies)
    monkeypatch.setattr(qb.crm_calc, "calculate",
                        lambda pozycje, opts: {"ok": True, "totals": {"total_brutto": 1230.0, "total_netto": 1000.0}})
    _seed_state(77, _KOMPLET, awaiting=1)
    qb.run_quote_turn(77, 12, "m1", "tak, wszystko się zgadza")
    tekst = " ".join(t for t, _ in replies)
    assert "1230" in tekst or "1 230" in tekst          # cena w wiadomosci
    assert "mail" in tekst.lower() or "e-mail" in tekst.lower()  # miekka prosba o kontakt
    c = db_mod.db()
    row = c.execute("SELECT priced, awaiting_contact FROM quote_state WHERE conv_id=77").fetchone()
    c.close()
    assert row["priced"] == 1 and row["awaiting_contact"] == 1


def test_kontakt_ze_startu_zapisuje_wycene_i_link(monkeypatch):
    replies = []
    _patch_common(monkeypatch, replies)
    monkeypatch.setattr(qb, "cw_contact_full",
                        lambda c: {"name": "Jan", "identifier": "web1", "email": "jan@x.pl", "phone": ""})
    monkeypatch.setattr(qb.crm_calc, "calculate",
                        lambda pozycje, opts: {"ok": True, "totals": {"total_brutto": 1230.0, "total_netto": 1000.0}})
    monkeypatch.setattr(qb.crm_calc, "find_or_create_client",
                        lambda email, phone, name, client_number=None: {"ok": True, "client": {"id": 42}})
    monkeypatch.setattr(qb.crm_calc, "create_quote",
                        lambda pozycje, opts, client_id, notes="": {"ok": True, "quote_number": "W/1",
                                                                    "public_url": "https://crm/q/abc"})
    _seed_state(88, _KOMPLET, awaiting=1)
    qb.run_quote_turn(88, 12, "m2", "tak")
    tekst = " ".join(t for t, _ in replies)
    assert "crm/q/abc" in tekst                          # link do wyceny
    c = db_mod.db()
    row = c.execute("SELECT quote_saved FROM quote_state WHERE conv_id=88").fetchone()
    c.close()
    assert row["quote_saved"] == 1


def test_odpowiedzi_ida_tokenem_quote_bota(monkeypatch):
    replies = []
    _patch_common(monkeypatch, replies)
    monkeypatch.setattr(qb.crm_calc, "calculate",
                        lambda pozycje, opts: {"ok": True, "totals": {"total_brutto": 10.0, "total_netto": 8.0}})
    _seed_state(99, _KOMPLET, awaiting=1)
    qb.run_quote_turn(99, 12, "m3", "tak")
    assert replies, "bot powinien coś wysłać"
    assert all(kw.get("token") == "TQ" for _, kw in replies), "każda odpowiedź tokenem quote-bota"


def test_po_wycenie_niejednoznaczne_pytanie_nie_ponawia_podsumowania(monkeypatch):
    """Regresja: po wyslanej cenie (priced=1) i przy oczekiwaniu na kontakt (awaiting_contact=1,
    awaiting_confirm=0) niejednoznaczna wiadomosc klienta NIE moze ponownie odpalic podsumowania
    (co uzbrajaloby awaiting_confirm od nowa i pozwolilo poznieszemu "tak" przeliczyc cene jeszcze
    raz) — powinna dostac zwykla odpowiedz LLM."""
    replies = []
    _patch_common(monkeypatch, replies)
    monkeypatch.setattr(qb, "chat", lambda messages, **kw: json.dumps(
        {"odpowiedz": "Czas realizacji to zwykle 2-3 tygodnie.", "handoff": False,
         "pozycje": [], "wspolne": {}}))
    c = db_mod.db()
    c.execute("DELETE FROM quote_state WHERE conv_id=?", (111,))
    c.execute("DELETE FROM quote_dane WHERE conv_id=?", (111,))
    c.execute("INSERT INTO quote_dane(conv_id, dane_json) VALUES(?,?)",
              (111, json.dumps(_KOMPLET)))
    c.execute("INSERT INTO quote_state(conv_id, bot_turns, priced, awaiting_contact, awaiting_confirm) "
              "VALUES(?,1,1,1,0)", (111,))
    c.commit(); c.close()
    qb.run_quote_turn(111, 12, "m4", "a jaki macie czas realizacji?")
    teksty = [t for t, _ in replies]
    assert not any("Podsumowuję dane" in t for t in teksty), "nie wolno ponawiac podsumowania po cenie"
    assert any("2-3 tygodnie" in t for t in teksty), "normalna odpowiedz LLM powinna zostac wyslana"
