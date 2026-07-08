# -*- coding: utf-8 -*-
# Test FAZA 0 zad. 4: kontrakt z LLM — response_format=json_object, logowanie finish_reason,
# zaostrzenie fallbacku _parse_llm (ucięty/uszkodzony JSON NIE idzie do klienta). PL-03, PL-04, TO-08.
import os, tempfile
os.environ.setdefault("OLX_CLIENT_ID", "x")
os.environ.setdefault("OLX_CLIENT_SECRET", "x")
os.environ.setdefault("OLX_REFRESH_TOKEN", "x")
os.environ["OPENAI_API_KEY"] = "sk-test"
os.environ.setdefault("BRIDGE_DB", os.path.join(tempfile.mkdtemp(), "bridge_llmc.db"))
import importlib
import pytest
llm = importlib.import_module("bots.llm")
qb = importlib.import_module("bots.quotebot")
lc = importlib.import_module("bots.livechat")


class FakeResp:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload
        self.text = "err"
    def json(self):
        return self._payload


def test_chat_przekazuje_response_format(monkeypatch):
    captured = {}
    monkeypatch.setattr(llm.requests, "post",
                        lambda url, **kw: captured.update(kw["json"]) or
                        FakeResp(200, {"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]}))
    llm.chat([{"role": "user", "content": "hej"}], response_format={"type": "json_object"})
    assert captured.get("response_format") == {"type": "json_object"}


def test_chat_bez_response_format_domyslnie(monkeypatch):
    captured = {}
    monkeypatch.setattr(llm.requests, "post",
                        lambda url, **kw: captured.update(kw["json"]) or
                        FakeResp(200, {"choices": [{"message": {"content": "ok"}}]}))
    llm.chat([{"role": "user", "content": "hej"}])
    assert "response_format" not in captured


def test_chat_nadal_zwraca_tresc(monkeypatch):
    monkeypatch.setattr(llm.requests, "post",
                        lambda url, **kw: FakeResp(200, {"choices": [{"message": {"content": "Dzień dobry"},
                                                                      "finish_reason": "length"}], "usage": {}}))
    # finish_reason != stop tylko logujemy; tresc nadal wraca
    assert llm.chat([{"role": "user", "content": "hej"}]) == "Dzień dobry"


@pytest.mark.parametrize("bot", [qb, lc])
def test_parse_llm_uciety_json_nie_idzie_do_klienta(bot):
    # Ucięty/uszkodzony JSON (limit tokenow) — musi rzucic (retry), nie wyslac surowca do klienta.
    with pytest.raises(RuntimeError):
        bot._parse_llm('{"odpowiedz": "Dziękuję za wiadomość, przygotuję', )
    with pytest.raises(RuntimeError):
        bot._parse_llm('tu jakis tekst a potem "pozycje": [ {"id": "1"')


@pytest.mark.parametrize("bot", [qb, lc])
def test_parse_llm_czysta_proza_dozwolona(bot):
    # Czysta proza bez markerow JSON — nadal dozwolona jako odpowiedz (tolerancja).
    out = bot._parse_llm("Dzień dobry, w czym mogę pomóc?")
    assert out["odpowiedz"] == "Dzień dobry, w czym mogę pomóc?"


@pytest.mark.parametrize("bot", [qb, lc])
def test_parse_llm_poprawny_json_dziala(bot):
    out = bot._parse_llm('{"odpowiedz":"ok","handoff":false,"pozycje":[],"wspolne":{}}')
    assert out["odpowiedz"] == "ok" and out["handoff"] is False
