# -*- coding: utf-8 -*-
# Writer: generuje artykul blogowy (tytul, pola SEO, tresc HTML) z realnymi produktami. Glos firmy
# (l. mnoga, bez myslnikow), fakty tylko z przekazanych danych. Braki pol uzupelniamy deterministycznie.
import re
import llm
from linker import render_link
from core.log import log

# Mapa polskich znakow na ascii dla slugow (PrestaShop url_alias).
_PL = str.maketrans("ąćęłńóśźżĄĆĘŁŃÓŚŹŻ", "acelnoszzACELNOSZZ")


def _s(v, fallback=""):
    # Zwraca oczyszczony string, gdy v to niepusty string; inaczej fallback (koercja odpowiedzi LLM).
    return v.strip() if isinstance(v, str) and v.strip() else fallback

_SYSTEM = (
    "Jesteś redaktorem bloga firmy WoodPower (drewniane blaty i schody). Piszesz artykuły pod SEO "
    "i marketing produktów. Zasady: głos firmy w liczbie mnogiej (\"doradzimy\", \"polecamy\"), "
    "BEZ myślników w tekście, po polsku. Nie wymyślaj cen, wymiarów, certyfikatów — opieraj się "
    "wyłącznie na przekazanych produktach. Treść to bogaty HTML (<section>, <h2>, <p>, <ul>), "
    "z sekcją FAQ i krótkim CTA na końcu. Wplataj podane linki naturalnie w treść. "
    "Zwracasz WYŁĄCZNIE JSON z polami: title, meta_title, meta_description, meta_keywords, "
    "short_description, category, body_html.")


def slugify(text):
    t = (text or "").translate(_PL).lower()
    t = re.sub(r"[^a-z0-9]+", "-", t).strip("-")
    return t[:200] or "artykul"


def _links_html(links):
    return " • ".join(render_link(l["anchor"], l["url"]) for l in links)


def write_article(topic_title, links, category_names):
    links_listing = "\n".join("- %s → %s" % (l["anchor"], l["url"]) for l in links) or "(brak)"
    cats = ", ".join(category_names) or "Poradniki"
    user = ("Temat: %s\n\nWpleć te linki wewnętrzne (użyj dokładnych URL, klasa CSS kontakt-link-descr, "
            "składnia <a href=... class=\"kontakt-link-descr\">tekst</a>):\n%s\n\n"
            "Wybierz kategorię bloga (pole category) z: %s.\n"
            "Napisz kompletny artykuł." % (topic_title, links_listing, cats))
    raw = llm.chat([{"role": "system", "content": _SYSTEM},
                    {"role": "user", "content": user}], want_json=True, max_tokens=6000)
    if raw is None:
        log("writer: LLM nie zwrocil odpowiedzi"); return None
    data = llm.parse_json(raw)
    body = data.get("body_html") if isinstance(data, dict) else None
    if not isinstance(body, str) or not body.strip():
        log("writer: brak poprawnego JSON/tresci"); return None
    title = _s(data.get("title"), topic_title)
    # Gwarancja obecnosci linkow: jesli model nie wplotl zadnego URL, dokladamy blok CTA.
    if links and not any(l["url"] in body for l in links):
        body += '\n<div class="blog-cta"><p>Zobacz też: %s</p></div>' % _links_html(links)

    category = data.get("category")
    if category not in category_names:
        category = category_names[0] if category_names else "Poradniki"

    meta_title = _s(data.get("meta_title"), title + " | WoodPower")[:255]
    meta_desc = _s(data.get("meta_description"), "Poradnik: " + title)[:255]
    meta_kw = _s(data.get("meta_keywords"), title)[:255]
    short = _s(data.get("short_description"), "")

    return {
        "title": title,
        "slug": slugify(title),
        "meta_title": meta_title,
        "meta_description": meta_desc,
        "meta_keywords": meta_kw,
        "short_description": short,
        "body_html": body,
        "category": category,
    }
