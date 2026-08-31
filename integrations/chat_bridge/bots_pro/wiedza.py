# -*- coding: utf-8 -*-
"""
Wiedza za stałym interfejsem.

Implementacja jest wymienna (dziś: indeks mostka; jutro ewentualnie vector
store dostawcy albo pgvector, który już stoi na VPS). Agent widzi wyłącznie
szukaj() — dlatego podmiana backendu nie dotyka agentów, a inwariant
przenośności zostaje zachowany: żadnego narzędzia hostowanego przez dostawcę
w liście tools.
"""
from bots.knowledge import retrieve


def szukaj(pytanie):
    """Fragmenty bazy wiedzy pasujące do pytania.

    Pusta lista NIE jest trybem pracy — jest stanem błędu. Agent wiedzy ma
    wtedy oddać rozmowę człowiekowi, a nie odpowiadać „sprawdzimy i wrócimy".
    """
    return [{"tytul": "", "tresc": fragment, "article_id": None}
            for fragment in retrieve(pytanie)]
