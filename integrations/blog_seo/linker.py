# -*- coding: utf-8 -*-
# Linker: dobiera trafne KATEGORIE do tematu (ranking slow, bez LLM) i sklada blok "Polecane kategorie".
# Kategorie sa stabilne (produkty znikaja); ranking po slowach tematu vs (name + link_rewrite).
import re
from config import LINK_CLASS

_STOP = {"jak", "dla", "czy", "the", "i", "w", "na", "o", "do", "z", "po", "co", "to", "a"}
# Uproszczona normalizacja polskich koncowek/odmiany do rankingu (nie do wyswietlania):
# usuwa diakrytyki i tnie slowo do 4 znakow, zeby "blat"~"blaty" i "debowy"~"debowe" sie pokrywaly.
_DIAKRYTYKI = str.maketrans("ąćęłńóśźż", "acelnoszz")


def render_link(anchor, url):
    return '<a href="%s" class="%s">%s</a>' % (url, LINK_CLASS, anchor)


def _words(text):
    return {w for w in re.findall(r"[a-ząćęłńóśźż]+", (text or "").lower()) if len(w) > 2 and w not in _STOP}


def _stems(words):
    # Rdzenie slow (do porownan rankingu) — bez diakrytykow, obciete do 4 znakow.
    return {w.translate(_DIAKRYTYKI)[:4] for w in words}


def topic_keywords(title):
    # Slowa tematu bez stopwordow — do wyszukiwania i rankingu kategorii.
    return sorted(_words(title))


def _cat_words(c):
    # Slowa kategorii = nazwa + link_rewrite (myslniki jako separatory slow).
    return _words((c.get("name") or "") + " " + (c.get("link_rewrite") or "").replace("-", " "))


def candidates(topic_title, categories):
    # Rankuje kategorie po LICZBIE trafionych rdzeni slow tematu (name+link_rewrite), malejaco.
    # Fallback: pierwsze kategorie gdy brak trafien. Dedup po URL.
    tw = _stems(_words(topic_title))
    scored = [(len(tw & _stems(_cat_words(c))), i, c) for i, c in enumerate(categories)]
    hit = [t for t in scored if t[0] > 0]
    hit.sort(key=lambda t: (-t[0], t[1]))  # malejaco po trafieniach, stabilnie po kolejnosci
    cats = [c for _, _, c in hit] or list(categories[:4])
    seen, uniq = set(), []
    for c in cats:
        if c.get("url") and c["url"] not in seen:
            seen.add(c["url"]); uniq.append(c)
    return uniq[:12]


def select_categories(topic_title, categories, k=3):
    # Deterministycznie k najtrafniejszych kategorii (pelne dicty). Bez LLM — ranking slow wystarcza.
    return candidates(topic_title, categories)[:k]


def render_category_block(categories):
    # Deterministyczny blok "Polecane kategorie": karty obraz+nazwa+link. Pomija bez image_url/url. "" gdy brak.
    cards = []
    for c in categories:
        if not c.get("image_url") or not c.get("url"):
            continue
        name = c.get("name") or ""
        cards.append(
            '<div class="blog-kategoria-karta">'
            '<a href="%s" class="%s"><img src="%s" alt="%s" loading="lazy"><span>%s</span></a></div>'
            % (c["url"], LINK_CLASS, c["image_url"], name, name))
    if not cards:
        return ""
    return ('\n<section class="blog-kategorie"><h2>Polecane kategorie</h2>%s</section>' % "".join(cards))
