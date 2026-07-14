# -*- coding: utf-8 -*-
# Klasyfikacja typu tresci bloga wg intencji frazy + kara za dominacje typu (miekki limit backlogu).
# UWAGA: typ NIE wyznacza juz kategorii bloga — kategorie wybiera model (writer) z podanej listy.
# Ten modul sluzy wylacznie do priorytetyzacji tematow w backlogu (rownowazenie typow zapytan).
# Bez LLM, bez zaleznosci — czyste regexy.
import re

# Slugi typow uzywane w priorytetyzacji: poradnik / trendy / edukacja / zrob-to-sam.
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
