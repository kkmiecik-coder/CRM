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


def test_chat_return_meta_zwraca_tresc_i_metadane(monkeypatch):
    def fake_post(url, **kw):
        return FakeResp(200, {"choices": [{"message": {"content": "hej"}, "finish_reason": "stop"}],
                              "usage": {"total_tokens": 42}})
    monkeypatch.setattr(llm.requests, "post", fake_post)
    content, meta = llm.chat([{"role": "user", "content": "x"}], model="gpt-5.4-nano",
                             return_meta=True)
    assert content == "hej"
    assert meta["model"] == "gpt-5.4-nano"
    assert meta["usage"]["total_tokens"] == 42
    assert meta["finish_reason"] == "stop"
    assert meta["error_class"] is None
    assert isinstance(meta["ms"], int)


def test_chat_return_meta_429_zwraca_none_i_klase_bledu(monkeypatch):
    monkeypatch.setattr(llm.requests, "post", lambda url, **kw: FakeResp(429, {}))
    content, meta = llm.chat([{"role": "user", "content": "x"}], return_meta=True)
    assert content is None
    assert meta["error_class"] == "429"


def test_chat_return_meta_4xx_zwraca_klase_4xx(monkeypatch):
    monkeypatch.setattr(llm.requests, "post", lambda url, **kw: FakeResp(400, {}))
    content, meta = llm.chat([{"role": "user", "content": "x"}], return_meta=True)
    assert content is None
    assert meta["error_class"] == "4xx"


def test_chat_return_meta_5xx_zwraca_klase_5xx(monkeypatch):
    monkeypatch.setattr(llm.requests, "post", lambda url, **kw: FakeResp(503, {}))
    content, meta = llm.chat([{"role": "user", "content": "x"}], return_meta=True)
    assert content is None
    assert meta["error_class"] == "5xx"


def test_chat_return_meta_transport_blad(monkeypatch):
    def fake_post(url, **kw):
        raise RuntimeError("network")
    monkeypatch.setattr(llm.requests, "post", fake_post)
    content, meta = llm.chat([{"role": "user", "content": "x"}], return_meta=True)
    assert content is None
    assert meta["error_class"] == "transport"


# ---- Modele responses-only (gpt-5.6-luna): routing na /v1/responses ----

def _luna_ok(text="Dzień dobry"):
    # Minimalna poprawna odpowiedz Responses API (element reasoning + message).
    return {"status": "completed",
            "output": [
                {"type": "reasoning", "summary": []},
                {"type": "message", "role": "assistant",
                 "content": [{"type": "output_text", "text": text}]},
            ],
            "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}}


def test_chat_luna_uzywa_responses_api(monkeypatch):
    # gpt-5.6-luna nie dziala na chat.completions — payload ma isc na /responses
    # z parametrami w ksztalcie Responses API (input, max_output_tokens, reasoning, text).
    captured = {}
    def fake_post(url, **kw):
        captured["url"] = url
        captured["json"] = kw["json"]
        return FakeResp(200, _luna_ok())
    monkeypatch.setattr(llm.requests, "post", fake_post)
    assert llm.chat([{"role": "user", "content": "hej"}], model="gpt-5.6-luna") == "Dzień dobry"
    assert captured["url"].endswith("/responses")
    p = captured["json"]
    assert p["input"] == [{"role": "user", "content": "hej"}]
    assert "messages" not in p and "max_completion_tokens" not in p
    assert p["max_output_tokens"] == llm.BOT_MAX_TOKENS
    assert p["reasoning"] == {"effort": llm.BOT_REASONING_EFFORT}
    assert p["text"]["verbosity"] == llm.BOT_VERBOSITY


def test_chat_luna_json_format(monkeypatch):
    # response_format={"type":"json_object"} przenosi sie do text.format (Responses API).
    captured = {}
    def fake_post(url, **kw):
        captured.update(kw["json"])
        return FakeResp(200, _luna_ok('{"ok":1}'))
    monkeypatch.setattr(llm.requests, "post", fake_post)
    llm.chat([{"role": "user", "content": "x"}], model="gpt-5.6-luna",
             response_format={"type": "json_object"})
    assert captured["text"]["format"] == {"type": "json_object"}


def test_chat_luna_multimodalne_czesci(monkeypatch):
    # Czesci multimodalne chat.completions (image_url/text) tlumaczymy na input_image/input_text.
    captured = {}
    def fake_post(url, **kw):
        captured.update(kw["json"])
        return FakeResp(200, _luna_ok())
    monkeypatch.setattr(llm.requests, "post", fake_post)
    llm.chat([{"role": "system", "content": "persona"},
              {"role": "user", "content": [
                  {"type": "text", "text": "co to?"},
                  {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAA"}}]}],
             model="gpt-5.6-luna")
    inp = captured["input"]
    assert inp[0] == {"role": "system", "content": "persona"}
    assert inp[1]["content"] == [
        {"type": "input_text", "text": "co to?"},
        {"type": "input_image", "image_url": "data:image/png;base64,AAA"}]


def test_chat_luna_meta_i_finish(monkeypatch):
    # completed -> finish_reason "stop"; usage przechodzi do meta bez zmian.
    monkeypatch.setattr(llm.requests, "post", lambda url, **kw: FakeResp(200, _luna_ok()))
    content, meta = llm.chat([{"role": "user", "content": "x"}], model="gpt-5.6-luna",
                             return_meta=True)
    assert content == "Dzień dobry"
    assert meta["finish_reason"] == "stop"
    assert meta["usage"]["total_tokens"] == 15
    assert meta["error_class"] is None


def test_chat_luna_incomplete_to_length(monkeypatch):
    # Uciety limit tokenow (incomplete/max_output_tokens) mapujemy na "length" —
    # spojnie z semantyka chat.completions (PL-04 patrzy na finish w logach).
    payload = _luna_ok("poczatek...")
    payload["status"] = "incomplete"
    payload["incomplete_details"] = {"reason": "max_output_tokens"}
    monkeypatch.setattr(llm.requests, "post", lambda url, **kw: FakeResp(200, payload))
    content, meta = llm.chat([{"role": "user", "content": "x"}], model="gpt-5.6-luna",
                             return_meta=True)
    assert content == "poczatek..."
    assert meta["finish_reason"] == "length"


def test_chat_luna_blad_http_zwraca_none(monkeypatch):
    monkeypatch.setattr(llm.requests, "post", lambda url, **kw: FakeResp(429, {}))
    content, meta = llm.chat([{"role": "user", "content": "x"}], model="gpt-5.6-luna",
                             return_meta=True)
    assert content is None
    assert meta["error_class"] == "429"


def test_embed_zwraca_wektory(monkeypatch):
    def fake_post(url, **kw):
        assert "embeddings" in url
        return FakeResp(200, {"data": [{"embedding": [0.1, 0.2]}, {"embedding": [0.3, 0.4]}]})
    monkeypatch.setattr(llm.requests, "post", fake_post)
    assert llm.embed(["a", "b"]) == [[0.1, 0.2], [0.3, 0.4]]


def test_embed_blad_zwraca_none(monkeypatch):
    monkeypatch.setattr(llm.requests, "post", lambda url, **kw: FakeResp(500, {}))
    assert llm.embed(["a"]) is None
