# -*- coding: utf-8 -*-
# Test zrodla Trends: dwustopniowy przeplyw explore->relatedsearches z prefiksem ")]}',", never-raises.
import importlib
trends = importlib.import_module("signals.trends")


class _Resp:
    def __init__(self, text):
        self.text = text


_EXPLORE_TEXT = ")]}',\n" + (
    '{"widgets":[{"id":"RELATED_QUERIES","token":"TOK","request":{"foo":1}}]}')
_RELATED_TEXT = ")]}',\n" + (
    '{"default":{"rankedList":[{"rankedKeyword":[{"query":"blat debowy nowoczesny","value":100}]},'
    '{"rankedKeyword":[{"query":"blat debowy 2026","value":250}]}]}}')


def test_fetch_trends_parsuje(monkeypatch):
    monkeypatch.setattr(trends, "TRENDS_ENABLED", 1)
    calls = iter([_Resp(_EXPLORE_TEXT), _Resp(_RELATED_TEXT)])
    monkeypatch.setattr(trends.requests, "get", lambda *a, **k: next(calls))
    out = trends.fetch_trends(["blat dębowy"])
    qs = [c["query"] for c in out]
    assert "blat debowy 2026" in qs
    assert all(c["source"] == "trends" for c in out)


def test_fetch_trends_wylaczone(monkeypatch):
    monkeypatch.setattr(trends, "TRENDS_ENABLED", 0)
    assert trends.fetch_trends(["x"]) == []


def test_fetch_trends_blad_nie_rzuca(monkeypatch):
    monkeypatch.setattr(trends, "TRENDS_ENABLED", 1)
    def boom(*a, **k):
        raise RuntimeError("net down")
    monkeypatch.setattr(trends.requests, "get", boom)
    assert trends.fetch_trends(["x"]) == []   # never-raises
