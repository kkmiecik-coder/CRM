# -*- coding: utf-8 -*-
# Test pipeline: przy podstawionych zaleznosciach powstaje szkic; dry-run nie zapisuje nic do sklepu.
import importlib


def _prep(tmp_path, monkeypatch):
    monkeypatch.setenv("BLOG_DB_PATH", str(tmp_path / "r.db"))
    import config; importlib.reload(config)
    for m in ("store", "catalog", "topics", "linker", "writer", "images", "publisher"):
        importlib.reload(importlib.import_module(m))
    rd = importlib.import_module("run_daily"); importlib.reload(rd)
    import store; store.init_db()

    PRODS = [{"id": 67, "name": "Blat dębowy", "category": "Blaty",
              "url": "https://woodpower.pl/67-blat", "image_url": None, "price": 1200.0}]
    CATS = [{"id": 11, "name": "Blaty", "url": "https://woodpower.pl/11-blaty"}]
    monkeypatch.setattr(rd.catalog, "get_products", lambda limit=200: PRODS)
    monkeypatch.setattr(rd.catalog, "get_categories", lambda: CATS)
    monkeypatch.setattr(rd.topics, "pick_topic", lambda s: {"id": 1, "title": "Jak dbać o blat dębowy"})
    monkeypatch.setattr(rd.linker, "select_links", lambda t, p, c, k=3:
                        [{"anchor": "blat dębowy", "url": "https://woodpower.pl/67-blat"}])
    monkeypatch.setattr(rd.writer, "write_article", lambda t, l, cn: {
        "title": "Jak dbać o blat dębowy", "slug": "jak-dbac-o-blat-debowy",
        "meta_title": "T", "meta_description": "D", "meta_keywords": "k",
        "short_description": "s", "body_html": "<section><p>67-blat</p></section>",
        "category": "Blaty"})
    monkeypatch.setattr(rd.images, "acquire_hero", lambda q: (b"IMG", "jpg"))
    monkeypatch.setattr(rd.images, "make_thumb", lambda b, max_w=600: b"THUMB")
    return rd, store


def test_run_tworzy_szkic(tmp_path, monkeypatch):
    rd, store = _prep(tmp_path, monkeypatch)
    saved = {}
    monkeypatch.setattr(rd.publisher, "save_image", lambda b, name: saved.setdefault(name, b) or True)
    monkeypatch.setattr(rd.publisher, "insert_draft", lambda art, img, thumb: 777)
    out = rd.run(dry_run=False)
    assert out["ok"] is True
    assert out["id_post"] == 777
    assert out["slug"] == "jak-dbac-o-blat-debowy"
    assert store.slug_seen("jak-dbac-o-blat-debowy") is True  # zapisane w historii
    assert len(saved) == 2  # hero + thumb


def test_dry_run_nie_zapisuje(tmp_path, monkeypatch):
    rd, store = _prep(tmp_path, monkeypatch)
    called = {"save": 0, "insert": 0}
    monkeypatch.setattr(rd.publisher, "save_image", lambda b, name: called.__setitem__("save", called["save"] + 1) or True)
    monkeypatch.setattr(rd.publisher, "insert_draft", lambda *a: called.__setitem__("insert", called["insert"] + 1) or 1)
    out = rd.run(dry_run=True)
    assert out["ok"] is True
    assert called["save"] == 0 and called["insert"] == 0
    assert store.slug_seen("jak-dbac-o-blat-debowy") is False  # dry-run nie zapisuje historii


def test_run_konczy_gdy_brak_tematu(tmp_path, monkeypatch):
    rd, store = _prep(tmp_path, monkeypatch)
    monkeypatch.setattr(rd.topics, "pick_topic", lambda s: None)
    out = rd.run(dry_run=False)
    assert out["ok"] is False and out["reason"] == "brak_tematu"
