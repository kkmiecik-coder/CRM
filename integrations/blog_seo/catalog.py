# -*- coding: utf-8 -*-
# Odczyt katalogu PrestaShop. Linkujemy KATEGORIE (stabilne, /{id}-{link_rewrite} → 200, obrazy /img/c/).
# Produkty tylko do generowania tematow (nazwy). URL/obraz produktow swiadomie nie budujemy.
import re
import shop_db
from config import SHOP_BASE_URL, PS_PREFIX, PS_LANG_IDS

# Rdzenie gatunkow, ktorym link_rewrite gubi polskie znaki (np. "debowe" -> "dębowe", "wiazowe" -> "wiązowe").
# UWAGA: podmiana po granicy slowa (\b) — gdyby doszla kategoria nie-gatunkowa zaczynajaca sie od "deb"/"wiaz"
# (np. "debata"), rozszerz warunek. W sklepie z drewnem takie kolizje sa nierealne.
_PL_RDZENIE = (("deb", "dęb"), ("wiaz", "wiąz"))

_LANG = PS_LANG_IDS[0] if PS_LANG_IDS else 1  # jezyk tresci = pierwszy (PL)


def category_url(id_category, link_rewrite):
    return "%s/%s-%s" % (SHOP_BASE_URL, id_category, link_rewrite)


def category_image_url(id_category):
    # Obraz kategorii serwowany przez PrestaShop: /img/c/{id}.jpg (zweryfikowane 200).
    return "%s/img/c/%s.jpg" % (SHOP_BASE_URL, id_category)


def _restore_pl(s):
    # Przywraca polskie znaki w rdzeniach gatunkow (link_rewrite jest bez diakrytykow): "debowe" -> "dębowe".
    out = s
    for bad, good in _PL_RDZENIE:
        out = re.sub(r"\b" + bad, good, out)
    return out


def _display_name(link_rewrite, name):
    # Etykieta rozroznialna z link_rewrite (myslniki->spacje, przywrocone diakrytyki, kapitalizacja) — bo sama
    # nazwa-lisc bywa niejednoznaczna (kilka podkategorii "Bukowe"): blaty-debowe -> "Blaty dębowe". Fallback: name.
    lr = (link_rewrite or "").replace("-", " ").strip()
    return _restore_pl(lr).capitalize() if lr else (name or "")


def _map_categories(rows):
    return [{"id": r["id_category"], "name": r["name"], "link_rewrite": r["link_rewrite"],
             "display_name": _display_name(r["link_rewrite"], r["name"]),
             "url": category_url(r["id_category"], r["link_rewrite"]),
             "image_url": category_image_url(r["id_category"])} for r in rows]


def get_categories():
    # Aktywne kategorie (nie root/home) w PL: id, nazwa, link_rewrite, URL, URL obrazu.
    p = PS_PREFIX
    sql = ("SELECT c.id_category, cl.name, cl.link_rewrite "
           "FROM %scategory c JOIN %scategory_lang cl "
           "ON c.id_category=cl.id_category AND cl.id_lang=%%s "
           "WHERE c.active=1 AND c.id_category>2 "
           "ORDER BY c.id_category" % (p, p))
    return _map_categories(shop_db.query(sql, (_LANG,)))


def search_categories(keywords, limit=30):
    # Aktywne kategorie, ktorych nazwa LUB link_rewrite pasuje do ktoregokolwiek slowa tematu.
    # Szuka po CALYM drzewie (nie probce). Ten sam ksztalt co get_categories.
    kws = [k for k in (keywords or []) if k]
    if not kws:
        return []
    p = PS_PREFIX
    like = " OR ".join(["cl.name LIKE %s OR cl.link_rewrite LIKE %s"] * len(kws))
    params = [_LANG]
    for k in kws:
        params += ["%" + k + "%", "%" + k + "%"]
    params.append(int(limit))
    sql = ("SELECT c.id_category, cl.name, cl.link_rewrite "
           "FROM %scategory c JOIN %scategory_lang cl "
           "ON c.id_category=cl.id_category AND cl.id_lang=%%s "
           "WHERE c.active=1 AND c.id_category>2 AND (%s) "
           "ORDER BY c.id_category LIMIT %%s" % (p, p, like))
    return _map_categories(shop_db.query(sql, tuple(params)))


def get_products(limit=200):
    # Aktywne produkty w PL — TYLKO nazwy + kategoria (do generowania tematow). Nie linkujemy produktow.
    p = PS_PREFIX
    sql = ("SELECT pl.name, ccl.name AS category "
           "FROM %sproduct pr "
           "JOIN %sproduct_lang pl ON pr.id_product=pl.id_product AND pl.id_lang=%%s "
           "LEFT JOIN %scategory_lang ccl ON pr.id_category_default=ccl.id_category AND ccl.id_lang=%%s "
           "WHERE pr.active=1 ORDER BY pr.id_product DESC LIMIT %%s" % (p, p, p))
    rows = shop_db.query(sql, (_LANG, _LANG, int(limit)))
    return [{"name": r["name"], "category": r.get("category") or ""} for r in rows]
