# -*- coding: utf-8 -*-
# Test linkera: slowa tematu, ranking kategorii (deb > buk po name+link_rewrite), top-k, blok kart.
import importlib
linker = importlib.import_module("linker")

CATS = [
    {"id": 73, "name": "Bukowe", "link_rewrite": "blaty-bukowe", "display_name": "Blaty bukowe",
     "url": "https://woodpower.pl/73-blaty-bukowe", "image_url": "https://woodpower.pl/img/c/73.jpg"},
    {"id": 71, "name": "Dębowe", "link_rewrite": "blaty-debowe", "display_name": "Blaty debowe",
     "url": "https://woodpower.pl/71-blaty-debowe", "image_url": "https://woodpower.pl/img/c/71.jpg"},
    {"id": 66, "name": "Schody", "link_rewrite": "schody", "display_name": "Schody",
     "url": "https://woodpower.pl/66-schody", "image_url": "https://woodpower.pl/img/c/66.jpg"},
]


def test_topic_keywords():
    kws = linker.topic_keywords("Jak dbać o blat dębowy")
    assert "blat" in kws and "dębowy" in kws
    assert "jak" not in kws  # stopword


def test_candidates_ranking_deb_bije_buk():
    # temat o blacie debowym: "blaty-debowe" trafia blat+debowy (2) > "blaty-bukowe" trafia blat (1)
    out = linker.candidates("Jak dbać o blat dębowy w kuchni", CATS)
    assert out[0]["url"] == "https://woodpower.pl/71-blaty-debowe"


def test_select_categories_topk():
    out = linker.select_categories("blat dębowy", CATS, k=2)
    assert len(out) == 2
    assert out[0]["url"] == "https://woodpower.pl/71-blaty-debowe"


def test_select_categories_fallback_bez_trafien():
    # temat bez wspolnych slow -> fallback do pierwszych kategorii, nie wywraca sie
    out = linker.select_categories("xyz abc", CATS, k=2)
    assert len(out) >= 1


def test_render_category_block():
    html = linker.render_category_block(CATS[:2])
    assert "Polecane kategorie" in html
    assert '<img src="https://woodpower.pl/img/c/73.jpg"' in html
    assert 'href="https://woodpower.pl/71-blaty-debowe"' in html
    assert 'class="kontakt-link-descr"' in html
    # etykieta rozroznialna z display_name, nie gola nazwa-lisc "Bukowe"
    assert "<span>Blaty bukowe</span>" in html


def test_render_category_block_pomija_bez_obrazu():
    cats = [{"id": 9, "name": "X", "url": "https://woodpower.pl/9-x", "image_url": ""}]
    assert linker.render_category_block(cats) == ""


def test_render_link():
    assert 'class="kontakt-link-descr"' in linker.render_link("kat", "https://woodpower.pl/71-x")


def test_ranking_rzeczownik_dab_wybiera_debowe():
    # temat rzeczownikowy "z dębu" (nie przymiotnik) tez ma wskazac kategorie debowa, nie bukowa.
    # "blat" wspolny dla obu kategorii (blaty-*), zeby obie trafily do rankingu i porownanie mialo sens.
    out = linker.candidates("Jak dbać o blat z dębu w kuchni", CATS)
    urls = [c["url"] for c in out]
    # debowa przed bukowa
    assert urls.index("https://woodpower.pl/71-blaty-debowe") < urls.index("https://woodpower.pl/73-blaty-bukowe")


def test_ranking_rzeczownik_buk():
    # "z buku" -> kategoria bukowa trafiona (rdzen buk == bukowe)
    out = linker.select_categories("Stół z buku do kuchni", CATS, k=1)
    assert out[0]["url"] == "https://woodpower.pl/73-blaty-bukowe"
