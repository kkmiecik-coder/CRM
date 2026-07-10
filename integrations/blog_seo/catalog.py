# -*- coding: utf-8 -*-
# Odczyt katalogu PrestaShop: kategorie produktowe i produkty + budowa przyjaznych URL i URL obrazkow.
# URL w konwencji sklepu: {SHOP_BASE_URL}/{id}-{link_rewrite} (jak w istniejacych linkach bloga).
import shop_db
from config import SHOP_BASE_URL, PS_PREFIX, PS_LANG_IDS

_LANG = PS_LANG_IDS[0] if PS_LANG_IDS else 1  # jezyk tresci = pierwszy (PL)


def product_url(id_product, link_rewrite):
    return "%s/%s-%s" % (SHOP_BASE_URL, id_product, link_rewrite)


def category_url(id_category, link_rewrite):
    return "%s/%s-%s" % (SHOP_BASE_URL, id_category, link_rewrite)


def _image_url(img_name):
    # Zdjecia produktow serwowane przez PrestaShop; uzywamy pola link_rewrite obrazu jesli jest,
    # w innym wypadku pomijamy (None). img_name pochodzi z zapytania (moze byc puste).
    if not img_name:
        return None
    return "%s/img/p/%s.jpg" % (SHOP_BASE_URL, img_name)


def get_categories():
    # Aktywne kategorie produktowe (nie root/nie home) w jezyku PL. Pomijamy id 1,2 (root/home).
    p = PS_PREFIX
    sql = ("SELECT c.id_category, cl.name, cl.link_rewrite "
           "FROM %scategory c JOIN %scategory_lang cl "
           "ON c.id_category=cl.id_category AND cl.id_lang=%%s "
           "WHERE c.active=1 AND c.id_category>2 "
           "ORDER BY c.id_category" % (p, p))
    rows = shop_db.query(sql, (_LANG,))
    return [{"id": r["id_category"], "name": r["name"],
             "url": category_url(r["id_category"], r["link_rewrite"])} for r in rows]


def get_products(limit=200):
    # Aktywne produkty w jezyku PL: nazwa, kategoria domyslna, cena, obrazek okladkowy.
    p = PS_PREFIX
    sql = ("SELECT pr.id_product, pl.name, pl.link_rewrite, "
           "       ccl.name AS category, pr.price, "
           "       CONCAT_WS('-', im.id_image, iml.legend) AS img "
           "FROM %sproduct pr "
           "JOIN %sproduct_lang pl ON pr.id_product=pl.id_product AND pl.id_lang=%%s "
           "LEFT JOIN %scategory_lang ccl ON pr.id_category_default=ccl.id_category AND ccl.id_lang=%%s "
           "LEFT JOIN %simage im ON pr.id_product=im.id_product AND im.cover=1 "
           "LEFT JOIN %simage_lang iml ON im.id_image=iml.id_image AND iml.id_lang=%%s "
           "WHERE pr.active=1 "
           "ORDER BY pr.id_product DESC LIMIT %%s" % (p, p, p, p, p))
    rows = shop_db.query(sql, (_LANG, _LANG, _LANG, int(limit)))
    out = []
    for r in rows:
        out.append({
            "id": r["id_product"], "name": r["name"],
            "category": r.get("category") or "",
            "url": product_url(r["id_product"], r["link_rewrite"]),
            "image_url": _image_url(r.get("img")),
            "price": float(r["price"]) if r.get("price") is not None else None,
        })
    return out
