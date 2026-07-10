# -*- coding: utf-8 -*-
# Test pipeline: linki = kategorie; blok "Polecane kategorie" i podpis atrybucji doklejone do body_html.
import importlib


def _prep(tmp_path, monkeypatch):
    monkeypatch.setenv("BLOG_DB_PATH", str(tmp_path / "r.db"))
    import config; importlib.reload(config)
    for m in ("store", "catalog", "topics", "linker", "writer", "images", "publisher"):
        importlib.reload(importlib.import_module(m))
    rd = importlib.import_module("run_daily"); importlib.reload(rd)
    import store; store.init_db()

    PRODS = [{"name": "Blat dębowy 100x100", "category": "Blaty"}]
    CATS = [{"id": 71, "name": "Dębowe", "link_rewrite": "blaty-debowe",
             "url": "https://woodpower.pl/71-blaty-debowe", "image_url": "https://woodpower.pl/img/c/71.jpg"}]
    monkeypatch.setattr(rd.catalog, "get_products", lambda limit=200: PRODS)
    monkeypatch.setattr(rd.catalog, "get_categories", lambda: CATS)
    monkeypatch.setattr(rd.catalog, "search_categories", lambda kws, limit=30: CATS)
    monkeypatch.setattr(rd.topics, "pick_topic", lambda s: {"id": 1, "title": "Jak dbać o blat dębowy"})
    monkeypatch.setattr(rd.writer, "write_article", lambda t, l, cn: {
        "title": "Jak dbać o blat dębowy", "slug": "jak-dbac-o-blat-debowy",
        "meta_title": "T", "meta_description": "D", "meta_keywords": "k",
        "short_description": "s", "body_html": "<section><p>x</p></section>", "category": "Poradniki"})
    monkeypatch.setattr(rd.images, "make_thumb", lambda b, max_w=600: b"THUMB")
    return rd, store


def test_linki_to_kategorie_i_blok_doklejony(tmp_path, monkeypatch):
    rd, store = _prep(tmp_path, monkeypatch)
    captured = {}
    def fake_write(t, links, cn):
        captured["links"] = links
        return {"title": "T", "slug": "jak-dbac-o-blat-debowy", "meta_title": "T", "meta_description": "D",
                "meta_keywords": "k", "short_description": "s", "body_html": "<section><p>x</p></section>",
                "category": "Poradniki"}
    monkeypatch.setattr(rd.writer, "write_article", fake_write)
    monkeypatch.setattr(rd.images, "acquire_hero", lambda q: None)  # bez hero w tym tescie
    saved = {}
    monkeypatch.setattr(rd.publisher, "insert_draft", lambda art, img, thumb: saved.update(art) or 777)
    out = rd.run(dry_run=False)
    assert out["ok"] is True and out["id_post"] == 777
    # linki pochodza z kategorii (url kategorii)
    assert captured["links"][0]["url"] == "https://woodpower.pl/71-blaty-debowe"
    # blok "Polecane kategorie" doklejony do tresci
    assert "Polecane kategorie" in saved["body_html"]
    assert "71-blaty-debowe" in saved["body_html"]


def test_podpis_atrybucji_doklejony(tmp_path, monkeypatch):
    rd, store = _prep(tmp_path, monkeypatch)
    monkeypatch.setattr(rd.images, "acquire_hero",
                        lambda q: (b"IMG", "jpg", {"photographer": "Jan Kowalski",
                            "photographer_url": "https://pexels.com/@jan",
                            "photo_url": "https://pexels.com/photo/1", "source": "Pexels"}))
    monkeypatch.setattr(rd.publisher, "save_image", lambda b, name: True)
    saved = {}
    monkeypatch.setattr(rd.publisher, "insert_draft", lambda art, img, thumb: saved.update(art) or 778)
    out = rd.run(dry_run=False)
    assert out["ok"] is True
    assert "Jan Kowalski" in saved["body_html"]
    assert "Pexels" in saved["body_html"]
    assert "blog-foto-autor" in saved["body_html"]


def test_hero_none_bez_podpisu(tmp_path, monkeypatch):
    rd, store = _prep(tmp_path, monkeypatch)
    monkeypatch.setattr(rd.images, "acquire_hero", lambda q: None)
    saved = {}
    monkeypatch.setattr(rd.publisher, "insert_draft", lambda art, img, thumb: saved.update(art) or 779)
    rd.run(dry_run=False)
    assert "blog-foto-autor" not in saved["body_html"]


def test_dry_run_nie_zapisuje(tmp_path, monkeypatch):
    # dry-run NIE moze dotykac sklepu: brak save_image/insert_draft/record_published
    rd, store = _prep(tmp_path, monkeypatch)
    called = {"save": 0, "insert": 0}
    monkeypatch.setattr(rd.images, "acquire_hero",
                        lambda q: (b"IMG", "jpg", {"photographer": "X", "source": "Pexels"}))
    monkeypatch.setattr(rd.publisher, "save_image",
                        lambda b, name: called.__setitem__("save", called["save"] + 1) or True)
    monkeypatch.setattr(rd.publisher, "insert_draft",
                        lambda *a: called.__setitem__("insert", called["insert"] + 1) or 1)
    out = rd.run(dry_run=True)
    assert out["ok"] is True and out["reason"] == "dry_run"
    assert called["save"] == 0 and called["insert"] == 0
    assert store.slug_seen("jak-dbac-o-blat-debowy") is False  # historia tez nie zapisana


def test_run_brak_tematu(tmp_path, monkeypatch):
    # gdy pick_topic zwroci None -> ok=False, reason=brak_tematu, bez wyjatku
    rd, store = _prep(tmp_path, monkeypatch)
    monkeypatch.setattr(rd.topics, "pick_topic", lambda s: None)
    out = rd.run(dry_run=False)
    assert out["ok"] is False and out["reason"] == "brak_tematu"
