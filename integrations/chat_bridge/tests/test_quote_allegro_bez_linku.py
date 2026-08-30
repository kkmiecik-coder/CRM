# -*- coding: utf-8 -*-
# Komunikaty z LINKIEM omijaja persone: sa sklejane w Pythonie, nie generowane przez model.
# Persona 'quote_allegro' zakazuje kierowania kupujacego poza platforme (w tym linku do wyceny),
# wiec zakaz musi byc egzekwowany na caps kanalu (ALLEGRO_CAPS['links'] = False). Inaczej link
# trafialby do notatki, ktora agent kopiuje w calosci, a sanitize.py blokowalby potem jej
# wysylke na Allegro — "gotowa tresc do wyslania" zamieniala sie w regularnie blokowana wklejke.
# OLX link ZACHOWUJE — tam jest glownym sposobem przekazania szczegolow.
import os, tempfile, json
os.environ.setdefault("OLX_CLIENT_ID", "x")
os.environ.setdefault("OLX_CLIENT_SECRET", "x")
os.environ.setdefault("OLX_REFRESH_TOKEN", "x")
os.environ["CRM_API_BASE"] = "https://crm.test"
os.environ["CRM_BOT_API_KEY"] = "KEY"
os.environ["BOT_QUOTE_CLIENT_TYPE"] = "Klient indywidualny"
os.environ["BOT_QUOTE_CW_AGENT_TOKEN"] = "TQ"
os.environ.setdefault("BRIDGE_DB", os.path.join(tempfile.mkdtemp(), "bridge_alg_link.db"))
import importlib
import config; importlib.reload(config)
db_mod = importlib.import_module("core.db"); db_mod.init_db()
qb = importlib.import_module("bots.quotebot"); importlib.reload(qb)
from bots.channel_caps import caps_for, DEFAULT_CAPS


def _poz(**kw):
    base = {"id": "1", "produkt": "blat", "dlugosc": "200", "szerokosc": "60", "grubosc": "4",
            "gatunek": "dąb", "technologia": "lity", "klasa": "A/B", "ilosc": "1",
            "wykonczenie": "surowe", "finishing_id": ""}
    base.update(kw); return base


def _patch_cena(monkeypatch, replies):
    """Minimalny harness sciezki 'policz cene i zapisz wycene' (bez sieci)."""
    monkeypatch.setattr(qb, "cw_agent_reply", lambda c, t, **kw: replies.append(t) or True)
    monkeypatch.setattr(qb, "cw_note", lambda c, t, **kw: True)
    monkeypatch.setattr(qb, "cw_bot_handoff", lambda c, **kw: True)
    monkeypatch.setattr(qb.crm_calc, "get_options", lambda: {"finishing_options": []})
    monkeypatch.setattr(qb.crm_calc, "calculate",
                        lambda p, o: {"ok": True, "products": [{}],
                                      "totals": {"total_brutto": 1000.0, "total_netto": 813.0}})
    monkeypatch.setattr(qb.crm_calc, "find_or_create_client",
                        lambda e, p, n, client_number=None:
                        {"ok": True, "matched": False, "created": True, "client": {"id": 99}})
    monkeypatch.setattr(qb.crm_calc, "create_quote",
                        lambda p, o, cid, notes="": {"ok": True, "quote_number": "W/7",
                                                     "public_url": "https://crm.woodpower.pl/q/abc",
                                                     "edit_uuid": "UU7"})


# --- caps kanalu ---

def test_caps_allegro_zabraniaja_linkow():
    """Allegro = jedyny kanal z zakazem; OLX i livechat linki dopuszczaja."""
    assert caps_for("quote_allegro")["links"] is False
    assert caps_for("allegro")["links"] is False
    assert caps_for("quote_olx")["links"] is True
    assert caps_for("quote")["links"] is True
    assert DEFAULT_CAPS["links"] is True


def test_caps_allegro_zachowuja_reszte_ograniczen_marketplace():
    """Zakaz linkow to DODATEK do formatu marketplace, nie jego zamiennik."""
    caps = caps_for("quote_allegro")
    assert caps["markdown"] is False and caps["emoji"] is False and caps["max_len"] == 2000


def test_wolno_linkowac_czyta_caps_tury():
    t = qb._reply_caps.set(caps_for("quote_allegro"))
    try:
        assert qb._wolno_linkowac() is False
    finally:
        qb._reply_caps.reset(t)
    t = qb._reply_caps.set(caps_for("quote_olx"))
    try:
        assert qb._wolno_linkowac() is True
    finally:
        qb._reply_caps.reset(t)


# --- 1. prosba o kontakt po cenie (bez kontaktu klienta) ---

def test_allegro_po_cenie_nie_prosi_o_mail_ani_nie_obiecuje_linku(monkeypatch):
    replies = []
    _patch_cena(monkeypatch, replies)
    t = qb._reply_caps.set(caps_for("quote_allegro"))
    try:
        qb._wyslij_cene_i_kontakt(7101, {"pozycje": [_poz()], "wspolne": {}}, {})
    finally:
        qb._reply_caps.reset(t)
    tekst = " ".join(replies).lower()
    assert "e-mail" not in tekst and "link" not in tekst and "http" not in tekst


def test_olx_po_cenie_nadal_prosi_o_kontakt_i_link(monkeypatch):
    """Kontrola pozytywna: na OLX komunikat zostaje bez zmian."""
    replies = []
    _patch_cena(monkeypatch, replies)
    t = qb._reply_caps.set(caps_for("quote_olx"))
    try:
        qb._wyslij_cene_i_kontakt(7102, {"pozycje": [_poz()], "wspolne": {}}, {})
    finally:
        qb._reply_caps.reset(t)
    tekst = " ".join(replies).lower()
    assert "e-mail" in tekst and "link" in tekst


# --- 2. wiadomosc z zapisana wycena (klient podal kontakt) ---

def test_allegro_zapis_wyceny_bez_adresu_url(monkeypatch):
    replies = []
    _patch_cena(monkeypatch, replies)
    t = qb._reply_caps.set(caps_for("quote_allegro"))
    try:
        qb._zapisz_wycene(7103, {"pozycje": [_poz()], "wspolne": {}}, {"finishing_options": []},
                          "jan@kowalski.pl", "", "Jan")
    finally:
        qb._reply_caps.reset(t)
    tekst = " ".join(replies)
    assert "crm.woodpower.pl" not in tekst and "http" not in tekst
    assert "W/7" in tekst, "numer wyceny zostaje — agent i kupujacy maja sie do czego odniesc"


def test_olx_zapis_wyceny_nadal_z_linkiem(monkeypatch):
    replies = []
    _patch_cena(monkeypatch, replies)
    t = qb._reply_caps.set(caps_for("quote_olx"))
    try:
        qb._zapisz_wycene(7104, {"pozycje": [_poz()], "wspolne": {}}, {"finishing_options": []},
                          "jan@kowalski.pl", "", "Jan")
    finally:
        qb._reply_caps.reset(t)
    assert any("https://crm.woodpower.pl/q/abc" in r for r in replies)


# --- 3. wycena wariantowa (tabela porownania gatunkow) ---

def _patch_wariantowa(monkeypatch, replies):
    monkeypatch.setattr(qb, "cw_agent_reply", lambda c, t, **kw: replies.append(t) or True)
    monkeypatch.setattr(qb, "_czy_wycena_wariantowa", lambda conv_id, poz: True)
    monkeypatch.setattr(qb, "_gatunki_pozycji", lambda poz: ["dąb", "jesion"])
    monkeypatch.setattr(qb, "_wycena_wariantowa_msg", lambda poz, prod, gat: "TABELA CEN")
    monkeypatch.setattr(qb.crm_calc, "get_options", lambda: {"finishing_options": []})
    monkeypatch.setattr(qb.crm_calc, "calculate",
                        lambda p, o: {"ok": True, "products": [{}], "totals": {}})


def test_allegro_wariantowa_nie_obiecuje_linku(monkeypatch):
    replies = []
    _patch_wariantowa(monkeypatch, replies)
    t = qb._reply_caps.set(caps_for("quote_allegro"))
    try:
        assert qb._obsluz_wyceny_wariantowej(7105, {"pozycje": [_poz()]}) is True
    finally:
        qb._reply_caps.reset(t)
    tekst = " ".join(replies).lower()
    assert "link" not in tekst and "e-mail" not in tekst
    assert "gatunek" in tekst, "prosba o wybor gatunku musi zostac"


def test_olx_wariantowa_nadal_obiecuje_link(monkeypatch):
    replies = []
    _patch_wariantowa(monkeypatch, replies)
    t = qb._reply_caps.set(caps_for("quote_olx"))
    try:
        assert qb._obsluz_wyceny_wariantowej(7106, {"pozycje": [_poz()]}) is True
    finally:
        qb._reply_caps.reset(t)
    tekst = " ".join(replies).lower()
    assert "link" in tekst and "e-mail" in tekst


# --- 4. komunikat MS-05 (nieudany zapis wyceny po podanym kontakcie) ---

def test_allegro_komunikat_bledu_zapisu_bez_obietnicy_linku():
    t = qb._reply_caps.set(caps_for("quote_allegro"))
    try:
        assert "link" not in qb._save_fail_msg().lower()
    finally:
        qb._reply_caps.reset(t)
    t = qb._reply_caps.set(caps_for("quote_olx"))
    try:
        assert "link" in qb._save_fail_msg().lower()
    finally:
        qb._reply_caps.reset(t)
