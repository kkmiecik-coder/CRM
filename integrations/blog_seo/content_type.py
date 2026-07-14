# -*- coding: utf-8 -*-
# Klasyfikacja typu tresci bloga wg intencji frazy + kara za dominacje typu (miekki limit),
# oraz mapowanie typu na realna kategorie modulu bloga. Bez LLM, bez zaleznosci — czyste regexy.
import re

TYPES = ("poradnik", "trendy", "edukacja", "zrob-to-sam")

TYPE_TO_CATEGORY = {
    "poradnik": "Poradniki",
    "trendy": "Trendy",
    "edukacja": "Edukacja",
    "zrob-to-sam": "Zrób to sam",
}

# Opis konwencji przekazywany writerowi jako twarde ograniczenie stylu.
TYPE_ANGLE = {
    "poradnik": "praktyczny poradnik krok po kroku (jak zrobić/zadbać)",
    "trendy": "artykuł o trendach, inspiracjach i aranżacjach",
    "edukacja": "artykuł edukacyjny wyjaśniający pojęcia i różnice",
    "zrob-to-sam": "instrukcja DIY zrób to sam dla majsterkowicza",
}

# Kolejnosc ma znaczenie: najmocniejsza intencja (DIY) najpierw, neutralny poradnik na koncu.
_PATTERNS = [
    ("zrob-to-sam", r"(samemu|własnoręcznie|wlasnorecznie|\bdiy\b|zrób|zrob|krok po kroku|jak zrobić|jak zrobic)"),
    ("trendy", r"(nowoczesn|modn|trend|inspiracj|aranżacj|aranzacj|202[0-9]|w stylu)"),
    ("edukacja", r"(co to|czym jest|rodzaj|różnic|roznic|porówn|porown|\bjakie\b|który|ktory)"),
    ("poradnik", r"(jak dbać|jak dbac|pielęgnac|pielegnac|czyścić|czyscic|konserwac|olejowan|\bjak\b|\bczym\b)"),
]


def classify(query):
    # Zwraca slug typu wg pierwszego dopasowanego wzorca; domyslnie 'edukacja'.
    q = (query or "").lower()
    for ctype, pat in _PATTERNS:
        if re.search(pat, q):
            return ctype
    return "edukacja"


def type_penalty(ctype, recent_types, step=5):
    # Kara priorytetu = ile razy ten typ wystapil w ostatnich publikacjach * step (miekki limit).
    try:
        return list(recent_types or []).count(ctype) * int(step)
    except Exception:
        return 0


def category_for_type(ctype, available_names):
    # Dopasowuje tytul kategorii bloga do typu (casefold-contains). Fallback: pierwsza dostepna / "Poradniki".
    want = TYPE_TO_CATEGORY.get(ctype, "")
    for n in (available_names or []):
        if n and want and want.casefold() in n.casefold():
            return n
    return (available_names[0] if available_names else "Poradniki")
