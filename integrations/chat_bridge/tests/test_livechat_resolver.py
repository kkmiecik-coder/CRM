# -*- coding: utf-8 -*-
# Test: resolver rozpoznaje Channel::WebWidget -> persona "livechat";
# personas.json ma kanal livechat z guardrailami.
import os, tempfile
os.environ.setdefault("OLX_CLIENT_ID", "x")
os.environ.setdefault("OLX_CLIENT_SECRET", "x")
os.environ.setdefault("OLX_REFRESH_TOKEN", "x")
os.environ.setdefault("BRIDGE_DB", os.path.join(tempfile.mkdtemp(), "bridge_liveres.db"))
import importlib

import config; importlib.reload(config)
cr = importlib.import_module("bots.channel_resolver")
personas = importlib.import_module("bots.personas")


def test_webwidget_daje_persone_livechat(monkeypatch):
    """Channel::WebWidget -> 'livechat' (niezaleznie od nazwy inboxu)."""
    monkeypatch.setattr(cr, "cw_inboxes", lambda: [
        {"id": 12, "name": "Test agenta CRM", "channel_type": "Channel::WebWidget"},
    ])
    cr._CACHE = {}; cr._CACHE_TS = 0.0
    assert cr.persona_for(12) == "livechat"


def test_email_i_api_bez_zmian(monkeypatch):
    """Regresja: Email -> mail, Api+allegro -> allegro, Api inne -> None."""
    monkeypatch.setattr(cr, "cw_inboxes", lambda: [
        {"id": 8, "name": "Biuro", "channel_type": "Channel::Email"},
        {"id": 4, "name": "Allegro - Wiadomosci", "channel_type": "Channel::Api"},
        {"id": 99, "name": "Inne", "channel_type": "Channel::Api"},
    ])
    cr._CACHE = {}; cr._CACHE_TS = 0.0
    assert cr.persona_for(8) == "mail"
    assert cr.persona_for(4) == "allegro"
    assert cr.persona_for(99) is None


def test_personas_json_ma_kanal_livechat():
    """personas.json zawiera kanal livechat z opisem i zasadami (on-topic)."""
    dane = personas.load_personas()
    live = dane["channels"].get("livechat")
    assert live, "brak kanalu livechat w personas.json"
    assert live.get("opis")
    zasady = " ".join(live.get("zasady") or []).lower()
    assert "woodpower" in zasady, "guardrail on-topic musi wymuszac tematy WoodPower"


def test_build_system_prompt_dziala_dla_livechat():
    """build_system_prompt nie wywala sie dla persony livechat i zawiera zasady kanalu."""
    prompt = personas.build_system_prompt("livechat", "wiedza-x", {"name": "Jan", "identifier": ""})
    assert "wiedza-x" in prompt
    assert "Jan" in prompt
