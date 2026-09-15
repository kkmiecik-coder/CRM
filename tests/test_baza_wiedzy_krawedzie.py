# -*- coding: utf-8 -*-
"""
Baza wiedzy asystenta AI po rozdzieleniu wykańczania.

To JEDYNE miejsce w tym zadaniu, gdzie rename realnie zmienia ODPOWIEDZI bota:
KnowledgeLoader.get_relevant_context (loader.py:76-85) dopasowuje sekcje po
`keywords`/`synonyms` z front matteru, a dopiero gdy żadne słowo kluczowe nie
trafi — punktowo po zawartości. Pytanie „co się dzieje na krawędziach" bez
wpisu w keywords trafiało w najlepszym razie w fallback punktowy, a w najgorszym
w zupełnie inną sekcję.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from modules.ai_assistant.knowledge.loader import KnowledgeLoader

KORZEN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DANE = os.path.join(KORZEN, 'modules', 'ai_assistant', 'knowledge', 'data')
PRODUKCJA = os.path.join(DANE, 'produkcja.md')
MODULY = os.path.join(DANE, 'moduly_crm.md')


def _zrodlo(sciezka):
    with open(sciezka, encoding='utf-8') as f:
        return f.read()


@pytest.fixture()
def baza():
    """KnowledgeLoader jest singletonem — load() przeładowuje sekcje z dysku."""
    loader = KnowledgeLoader()
    loader.load(DANE)
    return loader


def test_produkcja_opisuje_siedem_stanowisk():
    tresc = _zrodlo(PRODUKCJA)

    assert '### 7 stanowisk (w kolejności)' in tresc
    assert '**Krawędzie**' in tresc
    assert '**Lakiernia**' in tresc
    assert '**Wykańczanie**' not in tresc


def test_moduly_crm_opisuja_siedem_stanowisk():
    tresc = _zrodlo(MODULY)

    assert 'krawędzie' in tresc
    assert 'lakiernia' in tresc
    assert 'wykańczanie' not in tresc


def test_pytanie_o_krawedzie_trafia_w_sekcje_produkcji(baza):
    kontekst = baza.get_relevant_context('Co się dzieje na krawędziach?')

    assert '**Krawędzie**' in kontekst


def test_pytanie_o_lakiernie_trafia_w_sekcje_produkcji(baza):
    kontekst = baza.get_relevant_context('Ile trwa lakiernia?')

    assert '**Lakiernia**' in kontekst
