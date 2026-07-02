# -*- coding: utf-8 -*-
# Test: wrapper OpenAI parsuje odpowiedz chat/embeddings i nie rzuca wyjatkow przy bledzie.
import os
os.environ.setdefault("OLX_CLIENT_ID", "x")
os.environ.setdefault("OLX_CLIENT_SECRET", "x")
os.environ.setdefault("OLX_REFRESH_TOKEN", "x")
os.environ["OPENAI_API_KEY"] = "sk-test"
import importlib

llm = importlib.import_module("bots.llm")


class FakeResp:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload
        self.text = "err"
    def json(self):
        return self._payload


def test_chat_zwraca_tresc(monkeypatch):
    def fake_post(url, **kw):
        assert "chat/completions" in url
        return FakeResp(200, {"choices": [{"message": {"content": "Dzień dobry"}}]})
    monkeypatch.setattr(llm.requests, "post", fake_post)
    assert llm.chat([{"role": "user", "content": "hej"}]) == "Dzień dobry"


def test_chat_blad_zwraca_none(monkeypatch):
    def fake_post(url, **kw):
        raise RuntimeError("network")
    monkeypatch.setattr(llm.requests, "post", fake_post)
    assert llm.chat([{"role": "user", "content": "hej"}]) is None


def test_chat_gpt5_payload(monkeypatch):
    # Dla GPT-5: brak temperature, jest max_completion_tokens + reasoning_effort + verbosity.
    captured = {}
    def fake_post(url, **kw):
        captured.update(kw["json"])
        return FakeResp(200, {"choices": [{"message": {"content": "ok"}}]})
    monkeypatch.setattr(llm.requests, "post", fake_post)
    llm.chat([{"role": "user", "content": "hej"}], model="gpt-5-nano")
    assert "temperature" not in captured
    assert "max_tokens" not in captured
    assert captured["max_completion_tokens"] == llm.BOT_MAX_TOKENS
    assert captured["reasoning_effort"] == llm.BOT_REASONING_EFFORT
    assert captured["verbosity"] == llm.BOT_VERBOSITY


def test_chat_stary_model_payload(monkeypatch):
    # Dla gpt-4.1-mini: jest temperature, brak parametrow GPT-5.
    captured = {}
    def fake_post(url, **kw):
        captured.update(kw["json"])
        return FakeResp(200, {"choices": [{"message": {"content": "ok"}}]})
    monkeypatch.setattr(llm.requests, "post", fake_post)
    llm.chat([{"role": "user", "content": "hej"}], model="gpt-4.1-mini")
    assert captured["temperature"] == 0.3
    assert captured["max_completion_tokens"] == llm.BOT_MAX_TOKENS
    assert "reasoning_effort" not in captured
    assert "verbosity" not in captured


def test_embed_zwraca_wektory(monkeypatch):
    def fake_post(url, **kw):
        assert "embeddings" in url
        return FakeResp(200, {"data": [{"embedding": [0.1, 0.2]}, {"embedding": [0.3, 0.4]}]})
    monkeypatch.setattr(llm.requests, "post", fake_post)
    assert llm.embed(["a", "b"]) == [[0.1, 0.2], [0.3, 0.4]]


def test_embed_blad_zwraca_none(monkeypatch):
    monkeypatch.setattr(llm.requests, "post", lambda url, **kw: FakeResp(500, {}))
    assert llm.embed(["a"]) is None
