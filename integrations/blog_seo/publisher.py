# -*- coding: utf-8 -*-
# Publisher: zapisuje gotowy artykul jako NIEOPUBLIKOWANY szkic w module ETS Simple Blog.
# Sekwencja: INSERT ps_ets_blog_post (enabled=0) -> ps_ets_blog_post_lang (wiersz per jezyk) ->
# ps_ets_blog_post_category (relacja). Plik hero zapisujemy na dysk sklepu (img/ets_blog/post).
import os
import shop_db
from config import (PS_PREFIX, PS_SHOP_ID, PS_LANG_IDS, PS_AUTHOR_ID,
                    PS_DEFAULT_CATEGORY_ID, PS_IMG_DIR)
from core.log import log


def save_image(img_bytes, filename):
    # Zapisuje plik do katalogu obrazow modulu (tworzac go w razie potrzeby). Blad -> False.
    try:
        os.makedirs(PS_IMG_DIR, exist_ok=True)
        with open(os.path.join(PS_IMG_DIR, filename), "wb") as f:
            f.write(img_bytes)
        return True
    except Exception as e:
        log("save_image blad:", repr(e)); return False


def next_sort_order():
    rows = shop_db.query("SELECT COALESCE(MAX(sort_order),0)+1 AS n FROM %sets_blog_post" % PS_PREFIX)
    try:
        return int(rows[0]["n"]) if rows else 1
    except Exception:
        return 1


def resolve_category_id(name):
    # Zwraca id kategorii bloga po tytule (dowolny jezyk); fallback = domyslna kategoria z configu.
    rows = shop_db.query(
        "SELECT id_category FROM %sets_blog_category_lang WHERE title=%%s LIMIT 1" % PS_PREFIX, (name,))
    try:
        return int(rows[0]["id_category"]) if rows else PS_DEFAULT_CATEGORY_ID
    except Exception:
        return PS_DEFAULT_CATEGORY_ID


def insert_draft(article, image_name, thumb_name):
    # Zwraca id_post nowego szkicu (0 przy bledzie). enabled=0 => niewidoczny na froncie do akceptacji.
    # Cala trojka INSERT-ow (post + lang per jezyk + kategoria) atomowo w jednej transakcji: brak
    # osieroconych czesciowych szkicow gdy ktorys insert zawiedzie (rollback).
    p = PS_PREFIX
    cat_id = resolve_category_id(article.get("category"))
    so = next_sort_order()

    post_sql = ("INSERT INTO %sets_blog_post "
                "(id_shop, id_category_default, added_by, is_customer, modified_by, enabled, "
                " date_add, date_upd, sort_order) "
                "VALUES (%%s,%%s,%%s,%%s,%%s,%%s, NOW(), NOW(), %%s)" % p)
    lang_sql = ("INSERT INTO %sets_blog_post_lang "
                "(id_post, id_lang, title, url_alias, meta_title, description, short_description, "
                " meta_keywords, meta_description, thumb, image) "
                "VALUES (%%s,%%s,%%s,%%s,%%s,%%s,%%s,%%s,%%s,%%s,%%s)" % p)
    cat_sql = ("INSERT INTO %sets_blog_post_category (id_post, id_category, position) "
               "VALUES (%%s,%%s,%%s)" % p)

    try:
        with shop_db.transaction() as cur:
            cur.execute(post_sql, (PS_SHOP_ID, cat_id, PS_AUTHOR_ID, 0, PS_AUTHOR_ID, 0, so))
            id_post = cur.lastrowid
            for lang in PS_LANG_IDS:
                cur.execute(lang_sql, (
                    id_post, lang, article["title"], article["slug"], article["meta_title"],
                    article["body_html"], article.get("short_description") or "",
                    article["meta_keywords"], article["meta_description"],
                    thumb_name or "", image_name or ""))
            cur.execute(cat_sql, (id_post, cat_id, 1))
        log("insert_draft: utworzono szkic id_post=%s (enabled=0, kategoria=%s)" % (id_post, cat_id))
        return id_post
    except Exception as e:
        log("insert_draft blad (rollback):", repr(e)); return 0
