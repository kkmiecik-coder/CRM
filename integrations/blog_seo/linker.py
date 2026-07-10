# -*- coding: utf-8 -*-
# Linker: dobiera trafne KATEGORIE do tematu (ranking slow, bez LLM) i sklada blok "Polecane kategorie".
# Kategorie sa stabilne (produkty znikaja); ranking po slowach tematu vs (name + link_rewrite).
import re
from config import LINK_CLASS

_STOP = {"jak", "dla", "czy", "the", "i", "w", "na", "o", "do", "z", "po", "co", "to", "a"}
# Uproszczona normalizacja polskich koncowek/odmiany do rankingu (nie do wyswietlania):
# usuwa diakrytyki i tnie slowo do 4 znakow, zeby "blat"~"blaty" i "debowy"~"debowe" sie pokrywaly.
_DIAKRYTYKI = str.maketrans("ąćęłńóśźż", "acelnoszz")

# Kanonizacja rdzeni gatunkow drewna: rzeczownik i przymiotnik do jednego rdzenia
# (dąb/dębu/dębowy/dębowe -> DAB; buk/bukowy -> BUK; jesion/jesionowy -> JES). Rozwiazuje obocznosc
# a/e (dab vs debowy), ktorej samo obciecie prefiksu nie laczy. Reszta slow: rdzen = 4 znaki bez diakrytykow.
_GATUNKI = (("dab", "DAB"), ("deb", "DAB"), ("buk", "BUK"), ("jesi", "JES"), ("jeso", "JES"))


def _stem(w):
    # Rdzen pojedynczego slowa: bez diakrytykow; gatunki drewna kanonizowane, reszta obcieta do 4 znakow.
    s = w.translate(_DIAKRYTYKI)
    for pref, canon in _GATUNKI:
        if s.startswith(pref):
            return canon
    return s[:4]


def render_link(anchor, url):
    return '<a href="%s" class="%s">%s</a>' % (url, LINK_CLASS, anchor)


def _words(text):
    return {w for w in re.findall(r"[a-ząćęłńóśźż]+", (text or "").lower()) if len(w) > 2 and w not in _STOP}


def _stems(words):
    # Zbior rdzeni slow (do porownan rankingu).
    return {_stem(w) for w in words}


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


# Samowystarczalny CSS bloku (jedzie w tresci posta — niezalezny od motywu sklepu). Klasy prefiksowane
# blog-* wiec nie koliduja z reszta strony. Siatka responsywna (auto-fill), obraz 4:3, hover, podpis autora.
_BLOK_CSS = (
    "<style>"
    ".blog-kategorie{margin:2.5rem 0}"
    ".blog-kategorie>h2{margin:0 0 1rem}"
    ".blog-kategorie-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:1rem}"
    ".blog-kategoria-karta{display:block;text-decoration:none;color:inherit;border:1px solid #e6e6e6;"
    "border-radius:12px;overflow:hidden;background:#fff;transition:box-shadow .2s,transform .2s}"
    ".blog-kategoria-karta:hover{box-shadow:0 6px 18px rgba(0,0,0,.10);transform:translateY(-2px)}"
    ".blog-kategoria-karta img{width:100%;aspect-ratio:4/3;object-fit:cover;display:block}"
    ".blog-kategoria-karta span{display:block;padding:.7rem .9rem;font-weight:600}"
    ".blog-foto-autor{font-size:.85rem;color:#888;margin:.6rem 0 0}"
    ".blog-foto-autor a{color:#888}"
    "</style>")


def render_category_block(categories):
    # Deterministyczny blok "Polecane kategorie": siatka kart (obraz+nazwa+link) + samowystarczalny CSS.
    # Pomija kategorie bez image_url/url. "" gdy brak kart.
    cards = []
    for c in categories:
        if not c.get("image_url") or not c.get("url"):
            continue
        name = c.get("display_name") or c.get("name") or ""
        cards.append(
            '<a class="blog-kategoria-karta" href="%s"><img src="%s" alt="%s" loading="lazy">'
            '<span>%s</span></a>' % (c["url"], c["image_url"], name, name))
    if not cards:
        return ""
    return ('\n<section class="blog-kategorie">%s<h2>Polecane kategorie</h2>'
            '<div class="blog-kategorie-grid">%s</div></section>' % (_BLOK_CSS, "".join(cards)))
