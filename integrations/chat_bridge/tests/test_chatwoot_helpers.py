# -*- coding: utf-8 -*-
# Test: pomocnicy CW mapuja historie/kontakt/artykuly z odpowiedzi API.
import os
os.environ.setdefault("OLX_CLIENT_ID", "x")
os.environ.setdefault("OLX_CLIENT_SECRET", "x")
os.environ.setdefault("OLX_REFRESH_TOKEN", "x")
import importlib

cw = importlib.import_module("core.chatwoot")


class FakeResp:
    def __init__(self, payload):
        self._p = payload
        self.status_code = 200
        self.text = ""
    def json(self):
        return self._p


def test_cw_messages_mapuje_role_i_pomija_private(monkeypatch):
    resp_payload = {"payload": [
        {"content": "Pytanie klienta", "message_type": 0, "private": False},
        {"content": "Notatka", "message_type": 1, "private": True},
        {"content": "Odpowiedz agenta", "message_type": 1, "private": False},
        {"content": "", "message_type": 0, "private": False},
    ]}
    monkeypatch.setattr(cw, "cw", lambda m, p, payload=None: FakeResp(resp_payload))
    out = cw.cw_messages(99)
    assert out == [
        {"role": "user", "text": "Pytanie klienta"},
        {"role": "assistant", "text": "Odpowiedz agenta"},
    ]


def test_cw_contact_czyta_sender(monkeypatch):
    monkeypatch.setattr(cw, "cw", lambda m, p, payload=None:
                        FakeResp({"meta": {"sender": {"name": "Jan Kowalski", "identifier": "olx-1-2"}}}))
    assert cw.cw_contact(1) == {"name": "Jan Kowalski", "identifier": "olx-1-2"}


def test_cw_articles_pusty_slug_zwraca_liste():
    assert cw.cw_articles("") == []
