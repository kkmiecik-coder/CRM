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
    monkeypatch.setattr(qb, "chat", lambda messages, **kw: (chat_json, {"error_class": None}))
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


_KOMPLET_CMP = {"pozycje": [{"id": "1", "produkt": "blat", "dlugosc": "200", "szerokosc": "60",
                             "grubosc": "4", "gatunek": "dąb", "technologia": "lita", "klasa": "A/B",
                             "ilosc": "1", "wykonczenie": "surowe"}], "wspolne": {}}


def test_potwierdzenie_z_bledna_porownania_liczy_cene(monkeypatch):
    """REGRESJA (prod 08.07): na 'tak' model bezpodstawnie wrzucił 'porownania' -> bot uciekał w
    komunikat o porównaniu zamiast policzyć cenę. Teraz potwierdzenie wygrywa, cena leci."""
    replies = []
    _patch(monkeypatch, replies,
           '{"odpowiedz":"","handoff":false,"pozycje":[],"wspolne":{},"porownania":[{"id":"1","gatunek":"jesion"}]}')
    monkeypatch.setattr(qb.crm_calc, "calculate",
                        lambda poz, opts: {"ok": True, "totals": {"total_brutto": 1230.0, "total_netto": 1000.0}})
    _reset(1005, _KOMPLET_CMP, awaiting_confirm=1)   # komplet, przed ceną (NIE priced)
    qb.run_quote_turn(1005, 12, "m1", "tak, wszystko się zgadza")
    tekst = " ".join(replies)
    assert "1230" in tekst or "1 230" in tekst, "na 'tak' bot MUSI policzyć cenę"
    assert "dokończmy dane" not in tekst and "policzę zaraz po" not in tekst, "żadnej ucieczki w porównanie"


def test_po_zebraniu_danych_bledna_porownania_daje_podsumowanie(monkeypatch):
    """REGRESJA: po skompletowaniu danych model wrzuca 'porownania' -> bot ma wysłać PODSUMOWANIE,
    nie komunikat 'najpierw dokończmy dane' (dane są komplet)."""
    replies = []
    _patch(monkeypatch, replies,
           '{"odpowiedz":"Pokażę porównanie z innymi wariantami.","handoff":false,'
           '"pozycje":[{"id":"1","produkt":"blat","dlugosc":"200","szerokosc":"60","grubosc":"4",'
           '"gatunek":"dąb","technologia":"lita","klasa":"A/B","ilosc":"1","wykonczenie":"surowe"}],'
           '"wspolne":{},"porownania":[{"id":"1","gatunek":"jesion"}]}')
    _reset(1006, {"pozycje": [], "wspolne": {}})   # pusto -> ta tura kompletuje dane
    qb.run_quote_turn(1006, 12, "m1", "blat dąb lity A/B surowy 200x60x4, 1 szt")
    assert any("Podsumowuję dane" in t for t in replies), "komplet -> podsumowanie, nie ucieczka w porównanie"
    assert not any("dokończmy dane" in t for t in replies)


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
