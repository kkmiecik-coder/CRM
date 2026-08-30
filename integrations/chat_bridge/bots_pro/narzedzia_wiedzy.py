# -*- coding: utf-8 -*-
"""
Narzędzie wiedzy — osobny moduł, żeby agent wyceny go nie widział (i żeby
narzedzia.py, importowany też przez agenta wyceny, nie ciągnął za sobą
bots_pro.wiedza bez potrzeby)."""
from agents import function_tool

from bots_pro import wiedza


@function_tool
def szukaj_w_bazie_wiedzy(pytanie: str) -> list:
    """Szuka odpowiedzi w bazie wiedzy WoodPower (czas realizacji, wykończenia,
    pielęgnacja, dostawa, czego nie wykonujemy). Odpowiadaj WYŁĄCZNIE na
    podstawie zwróconych fragmentów. Pusta lista znaczy: nie wiemy —
    wtedy oddaj rozmowę człowiekowi, nie zmyślaj i nie zbywaj."""
    return wiedza.szukaj(pytanie)
