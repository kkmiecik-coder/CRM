# -*- coding: utf-8 -*-
# Test warstwy LLM: parsowanie odpowiedzi OpenAI i Anthropic, dispatch po configu, brak wyjatkow.
import importlib
oai = importlib.import_module("llm.openai_provider")
ant = importlib.import_module("llm.anthropic_provider")
base = importlib.import_module("llm.base")
llm = importlib.import_module("llm")


class FakeResp:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload
        self.text = "err"
    def json(self):
        return self._payload


def test_openai_zwraca_tresc(monkeypatch):
    def fake_post(url, **kw):
        assert "chat/completions" in url
        return FakeResp(200, {"choices": [{"message": {"content": "Dzień dobry"}}]})
    monkeypatch.setattr(oai.requests, "post", fake_post)
    assert oai.chat_openai([{"role": "user", "content": "hej"}], False, None) == "Dzień dobry"


def test_openai_nie_wysyla_temperature_dla_gpt5(monkeypatch):
    captured = {}
    def fake_post(url, **kw):
        captured.update(kw["json"])
        return FakeResp(200, {"choices": [{"message": {"content": "ok"}}]})
    monkeypatch.setattr(oai.requests, "post", fake_post)
    oai.chat_openai([{"role": "user", "content": "x"}], False, None)
    assert "temperature" not in captured
    assert "max_tokens" not in captured
    assert captured["max_completion_tokens"] > 0


def test_openai_blad_zwraca_none(monkeypatch):
    monkeypatch.setattr(oai.requests, "post", lambda url, **kw: (_ for _ in ()).throw(RuntimeError("net")))
    assert oai.chat_openai([{"role": "user", "content": "x"}], False, None) is None


def test_anthropic_zwraca_tresc_i_wyodrebnia_system(monkeypatch):
    captured = {}
    def fake_post(url, **kw):
        assert url.endswith("/messages")
        captured.update(kw["json"])
        return FakeResp(200, {"content": [{"type": "text", "text": "Odpowiedź"}]})
    monkeypatch.setattr(ant.requests, "post", fake_post)
    out = ant.chat_anthropic(
        [{"role": "system", "content": "Jesteś botem"}, {"role": "user", "content": "hej"}],
        False, None)
    assert out == "Odpowiedź"
    assert captured["system"] == "Jesteś botem"           # system wyciagniety osobno
    assert captured["messages"] == [{"role": "user", "content": "hej"}]
    assert "temperature" not in captured                   # 400 na Opus 4.8 gdyby bylo
    assert "budget_tokens" not in str(captured)
    assert captured["max_tokens"] > 0


def test_anthropic_blad_zwraca_none(monkeypatch):
    monkeypatch.setattr(ant.requests, "post", lambda url, **kw: FakeResp(400, {}))
    assert ant.chat_anthropic([{"role": "user", "content": "x"}], False, None) is None


def test_anthropic_malformed_messages_zwraca_none():
    # messages nie-lista-slownikow nie moze wywrocic funkcji (kontrakt: blad -> None)
    assert ant.chat_anthropic("to nie lista slownikow", False, None) is None


def test_dispatch_openai(monkeypatch):
    monkeypatch.setattr(llm, "LLM_PROVIDER", "openai")
    monkeypatch.setattr(llm, "chat_openai", lambda m, j, mt: "OAI")
    monkeypatch.setattr(llm, "chat_anthropic", lambda m, j, mt: "ANT")
    assert llm.chat([{"role": "user", "content": "x"}]) == "OAI"


def test_dispatch_anthropic(monkeypatch):
    monkeypatch.setattr(llm, "LLM_PROVIDER", "anthropic")
    monkeypatch.setattr(llm, "chat_openai", lambda m, j, mt: "OAI")
    monkeypatch.setattr(llm, "chat_anthropic", lambda m, j, mt: "ANT")
    assert llm.chat([{"role": "user", "content": "x"}]) == "ANT"


def test_parse_json_z_fences():
    assert base.extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert base.extract_json('bla {"b": 2} bla') == {"b": 2}
    assert base.extract_json("brak jsona") is None
