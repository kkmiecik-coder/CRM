# -*- coding: utf-8 -*-
# Test: cw_agent_reply (publiczna odpowiedz live-bota), cw_conv_status, cw_bot_handoff z tokenem.
import os, tempfile
os.environ.setdefault("OLX_CLIENT_ID", "x")
os.environ.setdefault("OLX_CLIENT_SECRET", "x")
os.environ.setdefault("OLX_REFRESH_TOKEN", "x")
os.environ["BOT_LIVE_CW_AGENT_TOKEN"] = "live-tok"
os.environ["BRIDGE_DB"] = os.path.join(tempfile.mkdtemp(), "bridge_livecw.db")
import importlib

import config; importlib.reload(config)
cwm = importlib.import_module("core.chatwoot"); importlib.reload(cwm)


class _Resp:
    def __init__(self, code=200, payload=None):
        self.status_code = code
        self.text = ""
        self._payload = payload or {}
    def json(self):
        return self._payload


def test_cw_agent_reply_wysyla_outgoing_tokenem_live_bota(monkeypatch):
    """cw_agent_reply: POST /messages z message_type=outgoing i tokenem live-bota."""
    calls = []
    def fake_post(url, headers=None, json=None, timeout=None):
        calls.append({"url": url, "headers": headers, "json": json})
        return _Resp(200)
    monkeypatch.setattr(cwm.requests, "post", fake_post)

    ok = cwm.cw_agent_reply(77, "Dzień dobry!")

    assert ok is True
    assert len(calls) == 1
    assert "/conversations/77/messages" in calls[0]["url"]
    assert calls[0]["json"]["message_type"] == "outgoing"
    assert calls[0]["json"]["content"] == "Dzień dobry!"
    assert calls[0]["json"].get("private") is not True
    assert calls[0]["headers"]["api_access_token"] == "live-tok"


def test_cw_agent_reply_blad_http_zwraca_false(monkeypatch):
    """Kod != 200 -> False, bez wyjatku."""
    monkeypatch.setattr(cwm.requests, "post", lambda *a, **k: _Resp(500))
    assert cwm.cw_agent_reply(77, "x") is False


def test_cw_agent_reply_wyjatek_zwraca_false(monkeypatch):
    """Wyjatek sieci -> False, bez wyjatku."""
    def boom(*a, **k):
        raise RuntimeError("siec")
    monkeypatch.setattr(cwm.requests, "post", boom)
    assert cwm.cw_agent_reply(77, "x") is False


def test_cw_conv_status_zwraca_status(monkeypatch):
    """cw_conv_status czyta pole status z GET /conversations/:id."""
    monkeypatch.setattr(cwm, "cw", lambda m, p, payload=None: _Resp(200, {"status": "pending"}))
    assert cwm.cw_conv_status(77) == "pending"


def test_cw_conv_status_blad_zwraca_none(monkeypatch):
    """Blad API -> None (wolajacy decyduje co dalej)."""
    def boom(*a, **k):
        raise RuntimeError("siec")
    monkeypatch.setattr(cwm, "cw", boom)
    assert cwm.cw_conv_status(77) is None


def test_cw_bot_handoff_uzywa_przekazanego_tokenu(monkeypatch):
    """cw_bot_handoff(conv, token=...) uzywa tokenu z parametru, nie domyslnego."""
    seen = {}
    def fake_post(url, headers=None, json=None, timeout=None):
        seen["headers"] = headers; seen["json"] = json
        return _Resp(200)
    monkeypatch.setattr(cwm.requests, "post", fake_post)

    assert cwm.cw_bot_handoff(77, token="live-tok") is True
    assert seen["headers"]["api_access_token"] == "live-tok"
    assert seen["json"] == {"status": "open"}
