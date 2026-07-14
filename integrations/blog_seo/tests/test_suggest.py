# -*- coding: utf-8 -*-
# Test zrodla Autocomplete: parsowanie odpowiedzi suggestqueries, never-raises, respekt flagi.
import importlib
suggest = importlib.import_module("signals.suggest")


class _Resp:
    def __init__(self, payload):
        self._p = payload
    def json(self):
        return self._p


def test_fetch_suggestions_parsuje(monkeypatch):
    monkeypatch.setattr(suggest, "SUGGEST_ENABLED", 1)
    monkeypatch.setattr(suggest.requests, "get",
                        lambda *a, **k: _Resp(["blat dębowy", ["blat dębowy jak czyścić", "blat dębowy olej"]]))
    out = suggest.fetch_suggestions(["blat dębowy"])
    qs = [c["query"] for c in out]
    assert "blat dębowy jak czyścić" in qs and "blat dębowy olej" in qs
    assert all(c["source"] == "autocomplete" for c in out)


def test_fetch_suggestions_wylaczone(monkeypatch):
    monkeypatch.setattr(suggest, "SUGGEST_ENABLED", 0)
    assert suggest.fetch_suggestions(["x"]) == []


def test_fetch_suggestions_blad_nie_rzuca(monkeypatch):
    monkeypatch.setattr(suggest, "SUGGEST_ENABLED", 1)
    def boom(*a, **k):
        raise RuntimeError("net down")
    monkeypatch.setattr(suggest.requests, "get", boom)
    assert suggest.fetch_suggestions(["x"]) == []   # never-raises
