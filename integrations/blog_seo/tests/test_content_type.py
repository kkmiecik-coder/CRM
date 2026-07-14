# -*- coding: utf-8 -*-
# Test klasyfikatora typu tresci: intencja frazy, kara za dominacje, mapowanie na kategorie bloga.
import importlib
ct = importlib.import_module("content_type")


def test_classify_intencje():
    assert ct.classify("Jak dbać o blat dębowy") == "poradnik"
    assert ct.classify("Nowoczesne blaty drewniane 2026") == "trendy"
    assert ct.classify("Co to jest mikrowczep") == "edukacja"
    assert ct.classify("Jak zrobić blat samemu krok po kroku") == "zrob-to-sam"


def test_classify_domyslnie_edukacja():
    assert ct.classify("blat dębowy") == "edukacja"      # brak sygnalu intencji -> neutralny typ
    assert ct.classify("") == "edukacja"


def test_type_angle_bez_meta_etykiet():
    # TYPE_ANGLE nie moze zawierac slow, ktore model cytuje w prozie jako etykieta ("artykuł", "poradnik").
    for v in ct.TYPE_ANGLE.values():
        low = v.lower()
        assert "artykuł" not in low and "poradnik" not in low


def test_type_penalty_rosnie_z_dominacja():
    assert ct.type_penalty("poradnik", []) == 0
    assert ct.type_penalty("poradnik", ["poradnik", "poradnik", "trendy"]) == 10  # 2 * 5


def test_category_for_type_mapuje():
    names = ["Poradniki", "Trendy", "Edukacja", "Zrób to sam"]
    assert ct.category_for_type("trendy", names) == "Trendy"
    assert ct.category_for_type("zrob-to-sam", names) == "Zrób to sam"
    assert ct.category_for_type("poradnik", []) == "Poradniki"   # fallback bez listy
