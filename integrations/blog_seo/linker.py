# -*- coding: utf-8 -*-
# Linker: dobiera 2-4 trafne produkty/kategorie do tematu i zwraca linki do wplecenia w tresc.
# Kandydatow wybieramy prostym dopasowaniem slow (bez embeddingow — dziala na obu dostawcach LLM),
# a finalny wybor robi model tekstowy. Render w stylu firmy (klasa kontakt-link-descr).
import re
import llm
from config import LINK_CLASS
from core.log import log

_STOP = {"jak", "dla", "czy", "the", "i", "w", "na", "o", "do", "z", "po", "co", "to", "a"}


def render_link(anchor, url):
    return '<a href="%s" class="%s">%s</a>' % (url, LINK_CLASS, anchor)


def _words(text):
    return {w for w in re.findall(r"[a-ząćęłńóśźż]+", (text or "").lower()) if len(w) > 2 and w not in _STOP}


def candidates(topic_title, products, categories):
    # Pozycje, ktorych nazwa/kategoria dzieli slowo z tematem. Fallback: pierwsze kategorie.
    tw = _words(topic_title)
    hits = []
    for p in products:
        if tw & (_words(p.get("name")) | _words(p.get("category"))):
            hits.append({"anchor": p["name"], "url": p["url"]})
    for c in categories:
        if tw & _words(c.get("name")):
            hits.append({"anchor": c["name"], "url": c["url"]})
    if not hits:
        hits = [{"anchor": c["name"], "url": c["url"]} for c in categories[:4]]
    # Dedup po URL, zachowujac kolejnosc.
    seen, uniq = set(), []
    for h in hits:
        if h["url"] not in seen:
            seen.add(h["url"]); uniq.append(h)
    return uniq[:12]


def select_links(topic_title, products, categories, k=3):
    # LLM wybiera do k najtrafniejszych z listy kandydatow; walidujemy URL wzgledem kandydatow.
    cands = candidates(topic_title, products, categories)
    if not cands:
        return []
    allowed = {c["url"] for c in cands}
    listing = "\n".join("- %s | %s" % (c["anchor"], c["url"]) for c in cands)
    system = ("Wybierasz do %d najtrafniejszych linków wewnętrznych do wplecenia w artykuł. "
              "Zwracasz WYŁĄCZNIE JSON {\"links\":[{\"anchor\":\"...\",\"url\":\"...\"}]}. "
              "URL MUSI pochodzić z podanej listy. anchor = naturalna fraza po polsku." % k)
    raw = llm.chat([{"role": "system", "content": system},
                    {"role": "user", "content": "Temat: %s\n\nKandydaci:\n%s" % (topic_title, listing)}],
                   want_json=True)
    data = llm.parse_json(raw) or {}
    out = []
    raw_links = data.get("links")
    for l in (raw_links if isinstance(raw_links, list) else []):
        if not isinstance(l, dict):
            continue
        url = l.get("url"); anchor = l.get("anchor")
        if url in allowed and anchor:
            out.append({"anchor": anchor, "url": url})
    if not out:
        log("linker: fallback na kandydatow (LLM nie zwrocil trafnych linkow)")
        out = cands[:k]
    return out[:k]
