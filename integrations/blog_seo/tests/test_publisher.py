# -*- coding: utf-8 -*-
# Test publishera: zapis pliku hero na dysk oraz sekwencja INSERT szkicu (enabled=0, oba jezyki,
# relacja kategorii) — z podstawiona funkcja shop_db.execute (przechwytujemy SQL i parametry).
import importlib
publisher = importlib.import_module("publisher")

ART = {"title": "Jak dbać o blat dębowy", "slug": "jak-dbac-o-blat-debowy",
       "meta_title": "Jak dbać o blat dębowy | WoodPower",
       "meta_description": "Poradnik.", "meta_keywords": "blat,pielęgnacja",
       "short_description": "Zajawka.", "body_html": "<section><p>x</p></section>",
       "category": "Poradniki"}


def test_save_image_zapisuje(tmp_path, monkeypatch):
    monkeypatch.setattr(publisher, "PS_IMG_DIR", str(tmp_path / "post"))
    assert publisher.save_image(b"\x89PNG dane", "hero.jpg") is True
    assert (tmp_path / "post" / "hero.jpg").read_bytes() == b"\x89PNG dane"


def test_insert_draft_sekwencja(monkeypatch):
    calls = []
    def fake_execute(sql, params=()):
        calls.append((sql, params))
        return 555 if "INTO %sets_blog_post " % publisher.PS_PREFIX in sql or "ets_blog_post (" in sql else 1
    monkeypatch.setattr(publisher.shop_db, "execute", fake_execute)
    monkeypatch.setattr(publisher, "next_sort_order", lambda: 10)
    monkeypatch.setattr(publisher, "resolve_category_id", lambda name: 2)
    monkeypatch.setattr(publisher, "PS_LANG_IDS", [1, 2])

    pid = publisher.insert_draft(ART, "hero.jpg", "thumb.jpg")
    assert pid == 555

    joined = " ".join(sql for sql, _ in calls)
    assert "ets_blog_post" in joined
    assert "ets_blog_post_lang" in joined
    assert "ets_blog_post_category" in joined
    # enabled=0 w insercie posta:
    post_call = next(p for sql, p in calls if "ets_blog_post " in sql or "ets_blog_post(" in sql or "ets_blog_post (" in sql)
    assert 0 in post_call  # enabled=0 przekazane w parametrach
    # dwa wiersze _lang (po jednym na jezyk):
    lang_calls = [1 for sql, _ in calls if "ets_blog_post_lang" in sql]
    assert len(lang_calls) == 2
