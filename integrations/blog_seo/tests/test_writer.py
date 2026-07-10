# -*- coding: utf-8 -*-
# Test writera: slugify polskich znakow oraz zlozenie artykulu z odpowiedzi LLM (atrapa), wraz z
# wstawieniem linkow i uzupelnieniem brakow pol SEO.
import importlib
writer = importlib.import_module("writer")

LINKS = [{"anchor": "blat dębowy", "url": "https://woodpower.pl/67-blat-debowy"}]


def test_slugify_polskie_znaki():
    assert writer.slugify("Jak dbać o blat dębowy?") == "jak-dbac-o-blat-debowy"
    assert writer.slugify("  Wiele   spacji  ") == "wiele-spacji"


def _fake_article_json():
    return ('{"title":"Jak dbać o blat dębowy",'
            '"meta_title":"Jak dbać o blat dębowy | WoodPower",'
            '"meta_description":"Praktyczny poradnik pielęgnacji.",'
            '"meta_keywords":"blat dębowy,pielęgnacja",'
            '"short_description":"Krótka zajawka.",'
            '"category":"Poradniki",'
            '"body_html":"<section><p>Treść o blacie.</p></section>"}')


def test_write_article_sklada_pola(monkeypatch):
    monkeypatch.setattr(writer.llm, "chat", lambda *a, **k: _fake_article_json())
    art = writer.write_article("Jak dbać o blat dębowy", LINKS, ["Poradniki", "Edukacja"])
    assert art["title"] == "Jak dbać o blat dębowy"
    assert art["slug"] == "jak-dbac-o-blat-debowy"       # zbudowany z tytulu
    assert art["category"] == "Poradniki"
    assert art["meta_keywords"]
    assert "<section>" in art["body_html"]
    # Link produktowy musi znalezc sie w tresci (wpleciony przez model lub dolozony w CTA).
    assert "67-blat-debowy" in art["body_html"]


def test_write_article_llm_pada(monkeypatch):
    monkeypatch.setattr(writer.llm, "chat", lambda *a, **k: None)
    assert writer.write_article("temat", LINKS, ["Poradniki"]) is None


def test_write_article_uzupelnia_braki(monkeypatch):
    # Model zwraca tylko title i body — reszta ma byc uzupelniona (slug, meta_*).
    monkeypatch.setattr(writer.llm, "chat", lambda *a, **k:
        '{"title":"Olejowanie blatu","body_html":"<p>x</p>"}')
    art = writer.write_article("Olejowanie blatu", LINKS, ["Poradniki"])
    assert art["slug"] == "olejowanie-blatu"
    assert art["meta_title"]
    assert art["meta_description"]
    assert art["meta_keywords"]
    assert art["category"] == "Poradniki"  # fallback = pierwsza kategoria


def test_write_article_body_nie_string_zwraca_none(monkeypatch):
    # body_html jako lista (poprawny JSON, zly typ) -> None, bez wyjatku
    monkeypatch.setattr(writer.llm, "chat", lambda *a, **k: '{"title":"T","body_html":["<p>x</p>"]}')
    assert writer.write_article("temat", LINKS, ["Poradniki"]) is None


def test_write_article_pola_nie_string_nie_rzuca(monkeypatch):
    # title/meta jako nie-stringi przy poprawnym body -> brak wyjatku, pola sensowne
    monkeypatch.setattr(writer.llm, "chat", lambda *a, **k:
        '{"title":12345,"meta_title":["a","b"],"body_html":"<section><p>67-blat-debowy</p></section>"}')
    art = writer.write_article("Olejowanie blatu", LINKS, ["Poradniki"])
    assert art is not None
    assert isinstance(art["title"], str) and art["title"]
    assert isinstance(art["meta_title"], str)
    assert isinstance(art["slug"], str) and art["slug"]
