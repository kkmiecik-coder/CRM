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


def test_cw_articles_przechodzi_wszystkie_strony(monkeypatch):
    # 60 artykulow: 25 + 25 + 10 na trzech stronach — musi zebrac wszystkie.
    def art(i):
        return {"id": i, "title": "T%d" % i, "content": "C%d" % i, "status": "published"}
    pages = {
        1: [art(i) for i in range(0, 25)],
        2: [art(i) for i in range(25, 50)],
        3: [art(i) for i in range(50, 60)],
    }

    def fake_cw(method, path, payload=None):
        page = 1
        if "page=" in path:
            page = int(path.split("page=")[1])
        return FakeResp({"payload": pages.get(page, [])})

    monkeypatch.setattr(cw, "cw", fake_cw)
    monkeypatch.setattr(cw, "html_to_text", lambda s: s)
    out = cw.cw_articles("woodpower")
    assert len(out) == 60
    assert out[0]["id"] == 0 and out[-1]["id"] == 59


def test_cw_agent_reply_bez_obrazu_json_post(monkeypatch):
    zapis = {}
    def fake_post(url, headers=None, json=None, timeout=None, **kw):
        zapis["json"] = json
        zapis["files"] = kw.get("files")
        return FakeResp({})  # status 200
    monkeypatch.setattr(cw.requests, "post", fake_post)
    ok = cw.cw_agent_reply(5, "cześć")
    assert ok is True
    assert zapis["json"] == {"content": "cześć", "message_type": "outgoing"}
    assert zapis["files"] is None


def test_cw_agent_reply_z_obrazem_multipart(monkeypatch, tmp_path):
    p = tmp_path / "probka.jpg"
    p.write_bytes(b"\xff\xd8\xffDANE")
    zapis = {}
    def fake_post(url, headers=None, data=None, files=None, timeout=None, **kw):
        zapis["data"] = data
        zapis["files"] = files
        return FakeResp({})
    monkeypatch.setattr(cw.requests, "post", fake_post)
    ok = cw.cw_agent_reply(5, "opis", image_path=str(p), image_name="probka.jpg", image_mime="image/jpeg")
    assert ok is True
    assert zapis["data"] == {"content": "opis", "message_type": "outgoing"}
    assert zapis["files"][0][0] == "attachments[]"
    assert zapis["files"][0][1][0] == "probka.jpg"
    assert zapis["files"][0][1][1] == b"\xff\xd8\xffDANE"


def test_cw_agent_reply_brak_pliku_fallback_json(monkeypatch):
    zapis = {}
    def fake_post(url, headers=None, json=None, timeout=None, **kw):
        zapis["json"] = json
        return FakeResp({})
    monkeypatch.setattr(cw.requests, "post", fake_post)
    ok = cw.cw_agent_reply(5, "opis", image_path="/nie/ma/pliku.jpg")
    assert ok is True
    assert zapis["json"] == {"content": "opis", "message_type": "outgoing"}
