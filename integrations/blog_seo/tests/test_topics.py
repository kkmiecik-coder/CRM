# -*- coding: utf-8 -*-
# Test silnika tematow: auto-uzupelnianie z dedupem oraz wybor tematu z seedowaniem pustego backlogu.
import importlib


def _fresh(tmp_path, monkeypatch):
    monkeypatch.setenv("BLOG_DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setenv("BLOG_MIN_BACKLOG", "3")
    import config; importlib.reload(config)
    store = importlib.import_module("store"); importlib.reload(store); store.init_db()
    topics = importlib.import_module("topics"); importlib.reload(topics)
    return topics, store


def test_replenish_dedupuje(tmp_path, monkeypatch):
    topics, store = _fresh(tmp_path, monkeypatch)
    store.add_topic("Jak dbać o blat dębowy")
    monkeypatch.setattr(topics.llm, "chat",
                        lambda *a, **k: '{"topics":["Jak dbać o blat dębowy","Olejowanie blatu krok po kroku"]}')
    added = topics.replenish("kategorie: Blaty", count=5)
    assert added == 1  # pierwszy to duplikat
    assert store.backlog_count() == 2


def test_pick_seeduje_pusty_backlog(tmp_path, monkeypatch):
    topics, store = _fresh(tmp_path, monkeypatch)
    monkeypatch.setattr(topics.llm, "chat", lambda *a, **k: '{"topics":[]}')  # LLM nic nie dodaje
    t = topics.pick_topic("kategorie: Blaty")
    assert t is not None  # z TOPIC_SEEDS
    assert t["title"]


def test_pick_zwraca_najwyzszy_priorytet(tmp_path, monkeypatch):
    topics, store = _fresh(tmp_path, monkeypatch)
    store.add_topic("Zwykly", priority=1)
    store.add_topic("Wazny", priority=9)
    monkeypatch.setattr(topics.llm, "chat", lambda *a, **k: '{"topics":[]}')
    assert topics.pick_topic("x")["title"] == "Wazny"


def test_replenish_topics_nie_lista_nie_rzuca(tmp_path, monkeypatch):
    topics, store = _fresh(tmp_path, monkeypatch)
    monkeypatch.setattr(topics.llm, "chat", lambda *a, **k: '{"topics": 5}')
    assert topics.replenish("kategorie: Blaty", count=5) == 0  # brak wyjatku, nic nie dodano
