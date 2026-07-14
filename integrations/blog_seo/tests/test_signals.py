# -*- coding: utf-8 -*-
# Test agregatora: kolejnosc zrodel (GSC>Trends>Autocomplete), dedup po norm, odsiew opublikowanych.
import importlib
signals = importlib.import_module("signals")


def test_collect_kolejnosc_dedup_i_odsiew(monkeypatch):
    monkeypatch.setattr(signals, "fetch_gsc_candidates",
                        lambda: [{"query": "blat debowy jak czyscic", "score": 1000.0, "source": "gsc"}])
    monkeypatch.setattr(signals, "fetch_trends",
                        lambda seeds: [{"query": "blat debowy 2026", "score": 250.0, "source": "trends"}])
    monkeypatch.setattr(signals, "fetch_suggestions",
                        lambda seeds: [{"query": "Blat Debowy Jak Czyscic", "score": 0.0, "source": "autocomplete"},
                                       {"query": "olejowanie blatu", "score": 0.0, "source": "autocomplete"}])
    out = signals.collect_candidates(["blat dębowy"], published_norms={"schody debowe"})
    qs = [c["query"] for c in out]
    # GSC pierwszy, potem trends, potem autocomplete; duplikat "Blat Debowy Jak Czyscic" (=gsc po norm) usuniety
    assert qs == ["blat debowy jak czyscic", "blat debowy 2026", "olejowanie blatu"]


def test_collect_odsiewa_published(monkeypatch):
    monkeypatch.setattr(signals, "fetch_gsc_candidates",
                        lambda: [{"query": "Jak dbać o blat", "score": 5.0, "source": "gsc"}])
    monkeypatch.setattr(signals, "fetch_trends", lambda seeds: [])
    monkeypatch.setattr(signals, "fetch_suggestions", lambda seeds: [])
    out = signals.collect_candidates([], published_norms={"jak dbać o blat"})
    assert out == []   # juz opublikowany


def test_collect_blad_nie_rzuca(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("boom")
    monkeypatch.setattr(signals, "fetch_gsc_candidates", boom)
    assert signals.collect_candidates([], set()) == []   # never-raises
