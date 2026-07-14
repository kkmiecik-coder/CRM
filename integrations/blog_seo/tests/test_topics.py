# -*- coding: utf-8 -*-
# Test silnika tematow: sciezka sygnalow (frazy->typ->szlif LLM), fallback do LLM, seedowanie backlogu.
import importlib


def _fresh(tmp_path, monkeypatch):
    monkeypatch.setenv("BLOG_DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setenv("BLOG_MIN_BACKLOG", "3")
    import config; importlib.reload(config)
    store = importlib.import_module("store"); importlib.reload(store); store.init_db()
    importlib.reload(importlib.import_module("content_type"))
    import signals; importlib.reload(signals)
    topics = importlib.import_module("topics"); importlib.reload(topics)
    return topics, store


def test_replenish_z_sygnalow_zapisuje_typ_i_priorytet(tmp_path, monkeypatch):
    topics, store = _fresh(tmp_path, monkeypatch)
    monkeypatch.setattr(topics.signals, "collect_candidates",
                        lambda seeds, published, limit=30:
                        [{"query": "jak dbać o blat dębowy", "source": "gsc"}])
    monkeypatch.setattr(topics, "_polish_title", lambda q, ct: "Jak zadbać o blat dębowy")
    added = topics.replenish("kategorie: Blaty", [], count=5)
    assert added == 1
    t = store.next_topic()
    assert t["content_type"] == "poradnik"       # classify("jak dbać...") -> poradnik


def test_replenish_fallback_do_llm_gdy_brak_sygnalow(tmp_path, monkeypatch):
    topics, store = _fresh(tmp_path, monkeypatch)
    monkeypatch.setattr(topics.signals, "collect_candidates", lambda seeds, published, limit=30: [])
    called = {"n": 0}
    monkeypatch.setattr(topics, "_replenish_llm",
                        lambda summary, count: called.__setitem__("n", called["n"] + 1) or 2)
    assert topics.replenish("kategorie: Blaty", [], count=5) == 2
    assert called["n"] == 1                        # uzyto fallbacku


def test_replenish_llm_dedupuje(tmp_path, monkeypatch):
    topics, store = _fresh(tmp_path, monkeypatch)
    store.add_topic("Jak dbać o blat dębowy")
    monkeypatch.setattr(topics.llm, "chat",
                        lambda *a, **k: '{"topics":["Jak dbać o blat dębowy","Olejowanie blatu krok po kroku"]}')
    added = topics._replenish_llm("kategorie: Blaty", count=5)
    assert added == 1                              # pierwszy duplikat
    assert store.backlog_count() == 2


def test_pick_seeduje_pusty_backlog(tmp_path, monkeypatch):
    topics, store = _fresh(tmp_path, monkeypatch)
    monkeypatch.setattr(topics.signals, "collect_candidates", lambda seeds, published, limit=30: [])
    monkeypatch.setattr(topics.llm, "chat", lambda *a, **k: '{"topics":[]}')
    t = topics.pick_topic("kategorie: Blaty", [])
    assert t is not None and t["title"]            # z TOPIC_SEEDS


def test_pick_zwraca_najwyzszy_priorytet(tmp_path, monkeypatch):
    topics, store = _fresh(tmp_path, monkeypatch)
    store.add_topic("Zwykly", priority=1)
    store.add_topic("Wazny", priority=9)
    monkeypatch.setattr(topics.signals, "collect_candidates", lambda seeds, published, limit=30: [])
    monkeypatch.setattr(topics.llm, "chat", lambda *a, **k: '{"topics":[]}')
    assert topics.pick_topic("x", [])["title"] == "Wazny"


def test_replenish_llm_topics_nie_lista_nie_rzuca(tmp_path, monkeypatch):
    topics, store = _fresh(tmp_path, monkeypatch)
    monkeypatch.setattr(topics.llm, "chat", lambda *a, **k: '{"topics": 5}')
    assert topics._replenish_llm("kategorie: Blaty", count=5) == 0
