# -*- coding: utf-8 -*-
# Pipeline dzienny automatu blogowego: temat -> linki -> artykul -> obrazy -> szkic ETS Simple Blog.
# Odporny na bledy (kazdy krok moze zwrocic None/0 -> log + wyjscie). --dry-run pomija zapis do sklepu.
import sys
import store
import catalog
import topics
import linker
import writer
import images
import publisher
from core.log import log


def catalog_summary(products, categories):
    cat_names = ", ".join(c["name"] for c in categories[:20])
    prod_names = ", ".join(p["name"] for p in products[:30])
    return "Kategorie: %s\nProdukty: %s" % (cat_names, prod_names)


def run(dry_run=False):
    store.init_db()
    products = catalog.get_products(limit=200)
    categories = catalog.get_categories()
    summary = catalog_summary(products, categories)

    topic = topics.pick_topic(summary)
    if not topic:
        log("run: brak tematu"); return {"ok": False, "id_post": 0, "slug": "", "reason": "brak_tematu"}
    log("run: temat =", topic["title"])

    links = linker.select_links(topic["title"], products, categories, k=3)

    # Kategorie bloga do wyboru przez writera — pobrane z modulu (fallback: nazwa kategorii sklepu).
    blog_cats = _blog_category_names()
    article = writer.write_article(topic["title"], links, blog_cats)
    if not article:
        log("run: writer nie zwrocil artykulu"); return {"ok": False, "id_post": 0, "slug": "", "reason": "brak_artykulu"}

    # Dedup: jesli slug juz publikowany, oznacz temat uzyty i wyjdz (unikamy nadpisania).
    if store.slug_seen(article["slug"]):
        store.mark_topic_used(topic["id"])
        log("run: slug juz istnieje, pomijam:", article["slug"])
        return {"ok": False, "id_post": 0, "slug": article["slug"], "reason": "duplikat_slug"}

    # Obrazy: hero (stock->AI) + miniatura. Brak obrazu nie blokuje szkicu (pola pojda puste).
    image_name = thumb_name = ""
    hero = images.acquire_hero(topic["title"])
    if hero:
        data, ext = hero
        image_name = "%s.%s" % (article["slug"], ext)
        thumb_bytes = images.make_thumb(data) or data
        thumb_name = "%s-thumb.jpg" % article["slug"]
        if not dry_run:
            publisher.save_image(data, image_name)
            publisher.save_image(thumb_bytes, thumb_name)

    if dry_run:
        log("run: DRY-RUN — nie zapisuje. slug=%s, kategoria=%s, linki=%d"
            % (article["slug"], article["category"], len(links)))
        return {"ok": True, "id_post": 0, "slug": article["slug"], "reason": "dry_run"}

    id_post = publisher.insert_draft(article, image_name, thumb_name)
    if not id_post:
        return {"ok": False, "id_post": 0, "slug": article["slug"], "reason": "blad_zapisu"}

    store.mark_topic_used(topic["id"])
    store.record_published(article["slug"], article["title"])
    log("run: gotowe. szkic id_post=%s slug=%s" % (id_post, article["slug"]))
    return {"ok": True, "id_post": id_post, "slug": article["slug"], "reason": "ok"}


def _blog_category_names():
    # Nazwy kategorii bloga (do wyboru przez writera). Bezposredni odczyt tabeli modulu; fallback stały.
    from config import PS_PREFIX, PS_LANG_IDS
    import shop_db
    lang = PS_LANG_IDS[0] if PS_LANG_IDS else 1
    rows = shop_db.query("SELECT title FROM %sets_blog_category_lang WHERE id_lang=%%s" % PS_PREFIX, (lang,))
    names = [r["title"] for r in rows if r.get("title")]
    return names or ["Poradniki", "Trendy", "Edukacja", "Zrób to sam"]


def main():
    dry = "--dry-run" in sys.argv
    out = run(dry_run=dry)
    log("main: wynik =", out)
    sys.exit(0 if out["ok"] else 1)


if __name__ == "__main__":
    main()
