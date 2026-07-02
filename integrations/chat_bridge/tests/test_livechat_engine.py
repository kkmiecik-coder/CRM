# -*- coding: utf-8 -*-
# Test: silnik live-bota — parsowanie JSON LLM, wyzwalacze handoffu A-E,
# cisza gdy status != pending, licznik tur (bezpiecznik D), sciezka awaryjna.
import os, tempfile, json
os.environ.setdefault("OLX_CLIENT_ID", "x")
os.environ.setdefault("OLX_CLIENT_SECRET", "x")
os.environ.setdefault("OLX_REFRESH_TOKEN", "x")
os.environ["BRIDGE_DB"] = os.path.join(tempfile.mkdtemp(), "bridge_liveng.db")
os.environ["BOT_LIVE_CW_AGENT_TOKEN"] = "live-tok-eng"
import importlib

import config; importlib.reload(config)
db_mod = importlib.import_module("core.db")
# import przez test_live_worker moze nastapic wczesniej (kolejnosc alfabetyczna) i
# zamrozic bots.livechat na starym config (from-import); reload wiaze token z aktualnego config
lc = importlib.import_module("bots.livechat"); importlib.reload(lc)


def setup_function(_):
    db_mod.init_db()
    c = db_mod.db()
    c.execute("DELETE FROM live_state")
    c.commit(); c.close()


def _mock_env(monkeypatch, status="pending", llm_json=None, llm_raw=None):
    """Wspolny zestaw mockow: API Chatwoota + LLM. Zwraca slownik zebranych wywolan."""
    calls = {"reply": [], "note": [], "handoff": [], "chat": []}
    monkeypatch.setattr(lc, "cw_conv_status", lambda cid: status)
    monkeypatch.setattr(lc, "cw_messages", lambda cid, lim: [{"role": "user", "text": "hej"}])
    monkeypatch.setattr(lc, "cw_contact", lambda cid: {"name": "Jan", "identifier": ""})
    monkeypatch.setattr(lc, "retrieve", lambda q: ["wiedza"])
    monkeypatch.setattr(lc, "cw_agent_reply", lambda cid, t: calls["reply"].append(t) or True)
    monkeypatch.setattr(lc, "cw_note", lambda cid, t: calls["note"].append(t))
    monkeypatch.setattr(lc, "cw_bot_handoff",
                        lambda cid, token=None: calls["handoff"].append(token) or True)
    raw = llm_raw if llm_raw is not None else json.dumps(llm_json or {})
    def fake_chat(messages, **kw):
        calls["chat"].append(messages)
        return raw
    monkeypatch.setattr(lc, "chat", fake_chat)
    return calls


def test_normalna_tura_publiczna_odpowiedz_bez_handoffu(monkeypatch):
    """LLM: handoff=false -> publiczna odpowiedz, zero handoffu, licznik tur +1."""
    calls = _mock_env(monkeypatch, llm_json={
        "odpowiedz": "Jaki gatunek Pana interesuje?", "handoff": False, "powod": "", "dane": {}})

    lc.run_livechat_turn(77, "12", "m1", "Szukam blatu")

    assert calls["reply"] == ["Jaki gatunek Pana interesuje?"]
    assert calls["handoff"] == []
    assert lc._bot_turns(77) == 1


def test_llm_handoff_true_przekazuje_z_notatka(monkeypatch):
    """LLM: handoff=true (wyzwalacze B/C) -> domkniecie + notatka-podsumowanie + toggle open."""
    calls = _mock_env(monkeypatch, llm_json={
        "odpowiedz": "", "handoff": True, "powod": "komplet danych",
        "dane": {"produkt": "blat", "wymiary": "200x80", "ilosc": "1", "termin": "", "kontakt": "jan@x.pl"}})

    lc.run_livechat_turn(77, "12", "m1", "To wszystko")

    assert calls["reply"] == [lc.CLOSING_MSG]
    assert len(calls["handoff"]) == 1
    assert calls["handoff"][0] == config.BOT_LIVE_CW_AGENT_TOKEN
    assert len(calls["note"]) == 1
    assert "komplet danych" in calls["note"][0]
    assert "200x80" in calls["note"][0]


def test_twarde_slowo_cena_wymusza_handoff_bez_llm(monkeypatch):
    """Wyzwalacz E: slowo o cenie w tresci klienta -> handoff BEZ wolania LLM."""
    calls = _mock_env(monkeypatch)

    lc.run_livechat_turn(77, "12", "m1", "Ile kosztuje taki blat?")

    assert calls["chat"] == [], "LLM nie powinien byc wolany przy twardym wyzwalaczu"
    assert calls["reply"] == [lc.CLOSING_MSG]
    assert len(calls["handoff"]) == 1


def test_twarde_slowo_konsultant_wymusza_handoff(monkeypatch):
    """Wyzwalacz A: prosba o czlowieka -> handoff bez LLM."""
    calls = _mock_env(monkeypatch)

    lc.run_livechat_turn(77, "12", "m1", "Chcę rozmawiać z konsultantem")

    assert calls["chat"] == []
    assert len(calls["handoff"]) == 1


def test_status_open_bot_milczy(monkeypatch):
    """Cisza po handoffie: status != pending -> zero odpowiedzi/handoffu/LLM."""
    calls = _mock_env(monkeypatch, status="open")

    lc.run_livechat_turn(77, "12", "m1", "Halo?")

    assert calls["reply"] == []
    assert calls["handoff"] == []
    assert calls["chat"] == []


def test_licznik_tur_wymusza_handoff(monkeypatch):
    """Bezpiecznik D: po BOT_LIVE_MAX_TURNS turach -> wymuszony handoff bez LLM."""
    calls = _mock_env(monkeypatch)
    c = db_mod.db()
    c.execute("INSERT INTO live_state(conv_id, bot_turns) VALUES(77, ?)",
              (config.BOT_LIVE_MAX_TURNS,))
    c.commit(); c.close()

    lc.run_livechat_turn(77, "12", "m1", "A jeszcze jedno pytanie")

    assert calls["chat"] == []
    assert calls["reply"] == [lc.CLOSING_MSG]
    assert len(calls["handoff"]) == 1
    assert "limit tur" in calls["note"][0].lower()


def test_zly_json_traktowany_jako_tekst(monkeypatch):
    """Fallback: LLM zwraca goly tekst (nie-JSON) -> wysylamy go jako odpowiedz, bez handoffu."""
    calls = _mock_env(monkeypatch, llm_raw="Dzień dobry, w czym mogę pomóc?")

    lc.run_livechat_turn(77, "12", "m1", "hej")

    assert calls["reply"] == ["Dzień dobry, w czym mogę pomóc?"]
    assert calls["handoff"] == []


def test_json_w_plocie_markdown_parsowany(monkeypatch):
    """LLM opakowal JSON w ```json ...``` -> parsujemy poprawnie."""
    payload = json.dumps({"odpowiedz": "OK", "handoff": False, "powod": "", "dane": {}})
    calls = _mock_env(monkeypatch, llm_raw="```json\n" + payload + "\n```")

    lc.run_livechat_turn(77, "12", "m1", "hej")

    assert calls["reply"] == ["OK"]


def test_brak_odpowiedzi_llm_rzuca(monkeypatch):
    """LLM zwraca None -> RuntimeError (retry w workerze)."""
    import pytest
    calls = _mock_env(monkeypatch)
    monkeypatch.setattr(lc, "chat", lambda m, **kw: None)

    with pytest.raises(RuntimeError):
        lc.run_livechat_turn(77, "12", "m1", "hej")
    assert calls["reply"] == [], "przy bledzie LLM nie wysylamy nic klientowi (retry w workerze)"


def test_handoff_with_apology(monkeypatch):
    """Awaryjne przekazanie: uprzejma wiadomosc + handoff + notatka."""
    calls = _mock_env(monkeypatch)

    lc.handoff_with_apology(77)

    assert calls["reply"] == [lc.APOLOGY_MSG]
    assert len(calls["handoff"]) == 1
    assert len(calls["note"]) == 1


def test_nieudany_toggle_rzuca_i_nic_nie_wysyla(monkeypatch):
    """Porazka toggle_status -> RuntimeError PRZED wyslaniem czegokolwiek do klienta (retry w workerze)."""
    import pytest
    calls = _mock_env(monkeypatch)
    monkeypatch.setattr(lc, "cw_bot_handoff", lambda cid, token=None: False)

    with pytest.raises(RuntimeError):
        lc.run_livechat_turn(77, "12", "m1", "Ile kosztuje blat?")

    assert calls["reply"] == [], "klient nie moze dostac 'przekazuje' gdy handoff padl"
    assert calls["note"] == []
