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


def test_used_images_dedup(tmp_path, monkeypatch):
    store = _fresh_store(tmp_path, monkeypatch)
    assert store.used_image_keys() == set()
    store.mark_image_used("https://pexels.com/photo/1")
    store.mark_image_used("https://pexels.com/photo/1")   # powtorka nie rzuca (INSERT OR IGNORE)
    store.mark_image_used("")                             # pusty klucz pomijany
    store.mark_image_used(None)                           # None pomijany
    store.mark_image_used("https://pexels.com/photo/2")
    assert store.used_image_keys() == {"https://pexels.com/photo/1", "https://pexels.com/photo/2"}


def test_add_topic_db_awaria_zwraca_false(tmp_path, monkeypatch):
    # Awaria polaczenia (db()) nie moze wywrocic add_topic — kontrakt: blad -> False
    store = _fresh_store(tmp_path, monkeypatch)
    def boom():
        raise RuntimeError("db locked")
    monkeypatch.setattr(store, "db", boom)
    assert store.add_topic("Cokolwiek") is False


def test_content_type_zapamietany(tmp_path, monkeypatch):
    store = _fresh_store(tmp_path, monkeypatch)
    assert store.add_topic("Nowoczesne blaty 2026", content_type="trendy") is True
    t = store.next_topic()
    assert t["title"] == "Nowoczesne blaty 2026"
    assert t["content_type"] == "trendy"


def test_published_norms_i_recent_types(tmp_path, monkeypatch):
    store = _fresh_store(tmp_path, monkeypatch)
    store.record_published("s1", "Jak dbać o blat", content_type="poradnik")
    store.record_published("s2", "Rodzaje drewna", content_type="edukacja")
    assert "jak dbać o blat" in store.published_norms()
    # najnowsze pierwsze (ORDER BY id DESC)
    assert store.recent_published_types(8) == ["edukacja", "poradnik"]


def test_record_published_bez_typu_kompatybilny(tmp_path, monkeypatch):
    store = _fresh_store(tmp_path, monkeypatch)
    store.record_published("s3", "Bez typu")   # stara sygnatura nadal dziala
    assert store.recent_published_types() == []  # None odfiltrowane
