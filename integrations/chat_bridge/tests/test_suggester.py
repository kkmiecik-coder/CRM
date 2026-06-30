# -*- coding: utf-8 -*-
# Test: pelna sciezka podpowiedzi (mock CW + LLM) i sciezka bledu (model None -> wyjatek).
import os
os.environ.setdefault("OLX_CLIENT_ID", "x")
os.environ.setdefault("OLX_CLIENT_SECRET", "x")
os.environ.setdefault("OLX_REFRESH_TOKEN", "x")
os.environ["CHATWOOT_OLX_INBOX_ID"] = "3"
import importlib
import pytest

import config; importlib.reload(config)
import bots.registry as reg; importlib.reload(reg)
sug = importlib.import_module("bots.suggester"); importlib.reload(sug)


def _patch(monkeypatch, reply):
    monkeypatch.setattr(sug, "cw_messages", lambda cid, limit=12: [{"role": "user", "text": "Czas realizacji?"}])
    monkeypatch.setattr(sug, "cw_contact", lambda cid: {"name": "Jan", "identifier": "olx-1"})
    monkeypatch.setattr(sug, "retrieve", lambda q, k=None: ["Realizacja 14 dni."])
    monkeypatch.setattr(sug, "chat", lambda messages, **kw: reply)
    notes = []
    monkeypatch.setattr(sug, "cw_note", lambda cid, text, *a, **kw: notes.append((cid, text)))
    return notes


def test_publikuje_notatke_z_prefiksem(monkeypatch):
    notes = _patch(monkeypatch, "Dzień dobry Panie Janie, realizacja 14 dni.")
    sug.run_suggestion(10, "3", "m1", "Czas realizacji?")
    assert len(notes) == 1
    assert notes[0][0] == 10
    assert notes[0][1].startswith("🤖 Podpowiedź AI:")
    assert "14 dni" in notes[0][1]


def test_model_none_rzuca_wyjatek(monkeypatch):
    _patch(monkeypatch, None)
    with pytest.raises(Exception):
        sug.run_suggestion(10, "3", "m1", "Czas realizacji?")


def test_inbox_bez_bota_rzuca(monkeypatch):
    _patch(monkeypatch, "cokolwiek")
    with pytest.raises(Exception):
        sug.run_suggestion(10, "999", "m1", "hej")
