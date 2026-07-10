# -*- coding: utf-8 -*-
# Test warstwy stanu: backlog tematow (dedup, kolejnosc), oznaczanie uzytych, historia publikacji.
import importlib


def _fresh_store(tmp_path, monkeypatch):
    monkeypatch.setenv("BLOG_DB_PATH", str(tmp_path / "s.db"))
    import config; importlib.reload(config)
    store = importlib.import_module("store"); importlib.reload(store)
    store.init_db()
    return store


def test_add_i_dedup(tmp_path, monkeypatch):
    store = _fresh_store(tmp_path, monkeypatch)
    assert store.add_topic("Jak dbać o blat dębowy") is True
    assert store.add_topic("  jak dbać o BLAT  Dębowy ") is False  # ten sam po normalizacji
    assert store.backlog_count() == 1


def test_next_i_priorytet(tmp_path, monkeypatch):
    store = _fresh_store(tmp_path, monkeypatch)
    store.add_topic("Niski", priority=1)
    store.add_topic("Wysoki", priority=9)
    t = store.next_topic()
    assert t["title"] == "Wysoki"
    store.mark_topic_used(t["id"])
    assert store.next_topic()["title"] == "Niski"
    assert store.backlog_count() == 1


def test_historia_publikacji(tmp_path, monkeypatch):
    store = _fresh_store(tmp_path, monkeypatch)
    store.record_published("jak-dbac-o-blat", "Jak dbać o blat")
    assert store.slug_seen("jak-dbac-o-blat") is True
    assert store.slug_seen("inny") is False
    assert "Jak dbać o blat" in store.published_titles()


def test_add_topic_db_awaria_zwraca_false(tmp_path, monkeypatch):
    # Awaria polaczenia (db()) nie moze wywrocic add_topic — kontrakt: blad -> False
    store = _fresh_store(tmp_path, monkeypatch)
    def boom():
        raise RuntimeError("db locked")
    monkeypatch.setattr(store, "db", boom)
    assert store.add_topic("Cokolwiek") is False
