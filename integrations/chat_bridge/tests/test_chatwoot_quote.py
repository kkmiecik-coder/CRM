# -*- coding: utf-8 -*-
# Test: cw_agent_reply przyjmuje token (nadpisuje domyslny), cw_contact_full czyta email/telefon.
import os, tempfile
os.environ.setdefault("OLX_CLIENT_ID", "x")
os.environ.setdefault("OLX_CLIENT_SECRET", "x")
os.environ.setdefault("OLX_REFRESH_TOKEN", "x")
os.environ["BRIDGE_DB"] = os.path.join(tempfile.mkdtemp(), "bridge_cwq.db")
import importlib
import config; importlib.reload(config)
cwmod = importlib.import_module("core.chatwoot"); importlib.reload(cwmod)


class _Resp:
    def __init__(self, status=200, payload=None):
        self.status_code = status
        self._payload = payload or {}
        self.text = ""
    def json(self):
        return self._payload


def test_agent_reply_uzywa_przekazanego_tokenu(monkeypatch):
    captured = {}
    def fake_post(url, headers=None, json=None, data=None, files=None, timeout=None):
        captured["token"] = headers.get("api_access_token")
        return _Resp(200)
    monkeypatch.setattr(cwmod, "requests", type("R", (), {"post": staticmethod(fake_post)}))
    ok = cwmod.cw_agent_reply(5, "cześć", token="TOKEN-QUOTE")
    assert ok is True
    assert captured["token"] == "TOKEN-QUOTE"


def test_contact_full_czyta_email_i_telefon(monkeypatch):
    payload = {"meta": {"sender": {"name": "Jan", "identifier": "web-1",
                                   "email": "jan@x.pl", "phone_number": "+48500"}}}
    monkeypatch.setattr(cwmod, "cw", lambda method, path: _Resp(200, payload))
    out = cwmod.cw_contact_full(5)
    assert out == {"name": "Jan", "identifier": "web-1",
                   "email": "jan@x.pl", "phone": "+48500"}


def test_contact_full_bez_danych_zwraca_puste(monkeypatch):
    monkeypatch.setattr(cwmod, "cw", lambda method, path: _Resp(200, {"meta": {}}))
    out = cwmod.cw_contact_full(9)
    assert out == {"name": "", "identifier": "", "email": "", "phone": ""}
