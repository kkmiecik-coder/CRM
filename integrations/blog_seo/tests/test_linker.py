# -*- coding: utf-8 -*-
# Test linkera: render HTML linku, filtr kandydatow po slowach, walidacja wyboru LLM wzgledem URL-i.
import importlib
linker = importlib.import_module("linker")

PRODS = [{"id": 67, "name": "Blat dębowy lity", "category": "Blaty",
          "url": "https://woodpower.pl/67-blat-debowy", "image_url": None, "price": 1200.0},
         {"id": 80, "name": "Schody jesionowe", "category": "Schody",
          "url": "https://woodpower.pl/80-schody", "image_url": None, "price": 5000.0}]
CATS = [{"id": 11, "name": "Blaty", "url": "https://woodpower.pl/11-blaty"}]


def test_render_link():
    html = linker.render_link("blat dębowy", "https://woodpower.pl/67-blat-debowy")
    assert 'href="https://woodpower.pl/67-blat-debowy"' in html
    assert 'class="kontakt-link-descr"' in html
    assert ">blat dębowy<" in html


def test_candidates_dopasowuje_slowa():
    c = linker.candidates("Jak olejować blat dębowy", PRODS, CATS)
    urls = [x["url"] for x in c]
    assert "https://woodpower.pl/67-blat-debowy" in urls
    assert "https://woodpower.pl/80-schody" not in urls  # schody nietrafione


def test_select_links_waliduje_url(monkeypatch):
    # LLM podaje jeden poprawny URL i jeden zmyslony — zmyslony ma zostac odrzucony.
    monkeypatch.setattr(linker.llm, "chat", lambda *a, **k:
        '{"links":[{"anchor":"blat dębowy","url":"https://woodpower.pl/67-blat-debowy"},'
        '{"anchor":"fejk","url":"https://woodpower.pl/999-fejk"}]}')
    out = linker.select_links("Jak olejować blat dębowy", PRODS, CATS, k=3)
    assert {"anchor": "blat dębowy", "url": "https://woodpower.pl/67-blat-debowy"} in out
    assert all(l["url"] != "https://woodpower.pl/999-fejk" for l in out)


def test_select_links_fallback_bez_llm(monkeypatch):
    monkeypatch.setattr(linker.llm, "chat", lambda *a, **k: None)  # LLM padł
    out = linker.select_links("Jak olejować blat dębowy", PRODS, CATS, k=2)
    assert len(out) >= 1
    assert all("url" in l and "anchor" in l for l in out)


def test_select_links_links_nie_slowniki_nie_rzuca(monkeypatch):
    # LLM zwraca poprawny JSON, ale elementy links to stringi, nie slowniki -> brak wyjatku, fallback
    monkeypatch.setattr(linker.llm, "chat", lambda *a, **k: '{"links":["https://woodpower.pl/67-blat-debowy"]}')
    out = linker.select_links("Jak olejować blat dębowy", PRODS, CATS, k=2)
    assert isinstance(out, list)
    assert all(isinstance(x, dict) and "url" in x and "anchor" in x for x in out)
