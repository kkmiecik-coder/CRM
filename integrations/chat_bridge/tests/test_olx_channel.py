# -*- coding: utf-8 -*-
# Testy kanalu OLX: wysylka musi byc poprzedzona mark-as-read — OLX od ~2026-07-14
# odrzuca (400 Bad Request, detail "Forbidden") wiadomosci do watkow z nieprzeczytanymi
# wiadomosciami (regresja produkcyjna: kolejka q#316-370, alerty w Chatwoocie).
from unittest import mock

import channels.olx as olx


def _fake_post_factory(calls, fail_commands=False):
    def fake_post(url, headers=None, json=None, timeout=None):
        calls.append((url, json))
        if url.endswith("/commands") and fail_commands:
            raise RuntimeError("mark-as-read niedostepny")
        r = mock.Mock()
        r.status_code = 204 if url.endswith("/commands") else 200
        r.text = ""
        return r
    return fake_post


def test_olx_send_mark_read_przed_wysylka(monkeypatch):
    calls = []
    monkeypatch.setattr(olx, "get_access_token", lambda force=False: "tok")
    monkeypatch.setattr(olx.requests, "post", _fake_post_factory(calls))
    r = olx.olx_send("123", "czesc")
    assert r.status_code == 200
    urls = [u for u, _ in calls]
    assert urls[0].endswith("/threads/123/commands"), "mark-as-read musi poprzedzac wysylke"
    assert calls[0][1] == {"command": "mark-as-read"}
    assert urls[1].endswith("/threads/123/messages")
    assert calls[1][1] == {"text": "czesc"}


def test_olx_send_dziala_mimo_bledu_mark_read(monkeypatch):
    # Awaria mark-as-read nie moze blokowac wysylki (best-effort, jak dotychczas po wysylce).
    calls = []
    monkeypatch.setattr(olx, "get_access_token", lambda force=False: "tok")
    monkeypatch.setattr(olx.requests, "post", _fake_post_factory(calls, fail_commands=True))
    r = olx.olx_send("123", "czesc")
    assert r.status_code == 200
    assert calls[-1][0].endswith("/threads/123/messages")
