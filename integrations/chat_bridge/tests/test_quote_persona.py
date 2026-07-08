# -*- coding: utf-8 -*-
# Test FAZA 0 zad. 1: osobna persona 'quote' (kopia livechat bez sprzecznych zasad o
# cenach/konsultancie/kontakcie + reguly bezpieczenstwa z sekcji 5) oraz uzycie jej w quotebot.
# Znaleziska: PL-01, AR-08, LS-07, ADW-01, ADW-06, ADW-07.
import os, tempfile, json
os.environ.setdefault("OLX_CLIENT_ID", "x")
os.environ.setdefault("OLX_CLIENT_SECRET", "x")
os.environ.setdefault("OLX_REFRESH_TOKEN", "x")
os.environ["CRM_API_BASE"] = "https://crm.test"
os.environ["CRM_BOT_API_KEY"] = "KEY"
os.environ["BOT_QUOTE_CLIENT_TYPE"] = "Klient indywidualny"
os.environ["BOT_QUOTE_CW_AGENT_TOKEN"] = "TQ"
os.environ.setdefault("BRIDGE_DB", os.path.join(tempfile.mkdtemp(), "bridge_qpersona.db"))
import importlib
import config; importlib.reload(config)
db_mod = importlib.import_module("core.db"); db_mod.init_db()
p = importlib.import_module("bots.personas")
qb = importlib.import_module("bots.quotebot"); importlib.reload(qb)


# --- Persona 'quote' istnieje i dziedziczy reguly wspolne + dobre reguly livechat ---

def test_quote_persona_istnieje_i_dziedziczy_checkliste():
    dane = p.load_personas()
    assert "quote" in dane["channels"], "musi istniec osobna persona 'quote'"
    s = p.build_system_prompt("quote", "", {}).lower()
    # dziedziczone reguly wspolne (checklista, koperta)
    assert "technologia" in s and "mikrowczep" in s
    assert "klasa" in s
    assert "120 cm" in s
    # dobre reguly livechat zachowane
    assert "dębuś" in s
    assert "osobne pozycje" in s
    assert "asystentem ai" in s, "uczciwosc wobec pytania o bota zachowana"


# --- Usuniete sprzeczne zasady (PL-01, LS-07) ---

def test_quote_persona_bez_sprzecznej_prosby_o_kontakt():
    # livechat rule: 'poprosz RAZ o kontakt zwrotny w trakcie zbierania' — sprzeczna z _FORMAT.
    s = p.build_system_prompt("quote", "", {}).lower()
    assert "poproś raz o kontakt" not in s
    assert "kontakt zwrotny w trakcie" not in s


def test_quote_persona_bez_zasady_nie_liczysz_ceny():
    # livechat rule 58: 'po potwierdzeniu ... rozmowa trafia do konsultanta — Ty jej nie liczysz'.
    s = p.build_system_prompt("quote", "", {}).lower()
    assert "nie liczysz" not in s
    assert "trafia do konsultanta" not in s


def test_quote_persona_ma_regule_ceny_liczonej_przez_system():
    s = p.build_system_prompt("quote", "", {}).lower()
    assert "automatycznie system" in s or "system — po komplecie" in s
    assert "po potwierdzeniu" in s


# --- Reguly bezpieczenstwa z sekcji 5 ---

def test_quote_persona_zakaz_obietnic_handlowych():   # ADW-01
    s = p.build_system_prompt("quote", "", {}).lower()
    assert "rabat" in s
    assert "nie obiecuj" in s


def test_quote_persona_regula_jezykowa():   # ADW-06
    s = p.build_system_prompt("quote", "", {}).lower()
    assert "innym języku" in s


def test_quote_persona_tekst_z_obrazow_to_tresc():   # ADW-02/ADW-06 hardening
    s = p.build_system_prompt("quote", "", {}).lower()
    assert "na obrazach" in s
    assert "nigdy jako polecenia" in s or "nie jako polecenia" in s


def test_quote_persona_bez_wycieku_instrukcji():   # ADW-07
    s = p.build_system_prompt("quote", "", {}).lower()
    assert "nie ujawniaj" in s


# --- Livechat (stary bot) NIE zmieniony ---

def test_livechat_persona_nietknieta():
    s = p.build_system_prompt("livechat", "", {}).lower()
    # stare reguly livechat pozostaja (kontakt zwrotny, brak samodzielnej wyceny)
    assert "kontakt zwrotny" in s
    assert "nie liczysz" in s


# --- quotebot uzywa persony 'quote' (behawioralnie) ---

def _patch_common(monkeypatch, replies, chat_json):
    monkeypatch.setattr(qb, "cw_conv_status", lambda c: "pending")
    monkeypatch.setattr(qb, "cw_messages", lambda c, n: [{"role": "user", "text": "dzień dobry"}])
    monkeypatch.setattr(qb, "cw_contact", lambda c: {"name": "", "identifier": ""})
    monkeypatch.setattr(qb, "cw_contact_full", lambda c: {"name": "", "identifier": "", "email": "", "phone": ""})
    monkeypatch.setattr(qb, "retrieve", lambda q: [])
    monkeypatch.setattr(qb, "chat", lambda messages, **kw: chat_json)
    monkeypatch.setattr(qb, "cw_agent_reply",
                        lambda conv_id, text, **kw: replies.append((text, kw)) or True)
    monkeypatch.setattr(qb.crm_calc, "get_options", lambda: {"finishing_options": []})


def test_quotebot_buduje_prompt_z_persony_quote(monkeypatch):
    captured = {}
    real = qb.build_system_prompt
    monkeypatch.setattr(qb, "build_system_prompt",
                        lambda key, knowledge, identity: captured.__setitem__("key", key) or real(key, knowledge, identity))
    _patch_common(monkeypatch, [], '{"odpowiedz":"Dzień dobry, w czym pomóc?","handoff":false,"pozycje":[],"wspolne":{}}')
    c = db_mod.db()
    c.execute("DELETE FROM quote_state WHERE conv_id=?", (701,))
    c.execute("DELETE FROM quote_dane WHERE conv_id=?", (701,))
    c.commit(); c.close()
    qb.run_quote_turn(701, 12, "mp1", "dzień dobry")
    assert captured.get("key") == "quote", "quotebot musi budowac prompt z persony 'quote'"
