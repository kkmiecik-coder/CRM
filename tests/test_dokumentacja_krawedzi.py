# -*- coding: utf-8 -*-
"""
Dokumentacja profili pracowników — opis sztucznych eventów auto-pomijania.

docs/worker-profiles-backend.md §„Pułapka nr 2" jest jedynym spisanym
uzasadnieniem filtra ZRODLA_AUTOMATU i trafia do każdej analizy raportów
pracowniczych. Po rozdzieleniu wykańczania opisywał przeskok
`formatting → finishing`, czyli trasę, która w kodzie już nie istnieje —
a to dokładnie ten rodzaj dokumentacji, który myli bardziej niż jej brak.

Test jest tani i jednorazowy: pilnuje, że sekcja mówi o Krawędziach i o nowej,
trzeciej gałęzi (formatowanie → Lakiernia), a nie o martwym kodzie.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

KORZEN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOK = os.path.join(KORZEN, 'docs', 'worker-profiles-backend.md')


def _sekcja_pulapka_2():
    with open(DOK, encoding='utf-8') as f:
        tresc = f.read()
    poczatek = tresc.index('### Pułapka nr 2')
    return tresc[poczatek:poczatek + 1200]


def test_pulapka_2_opisuje_przeskok_na_krawedzie():
    sekcja = _sekcja_pulapka_2()

    assert 'formatting → edges' in sekcja
    assert 'formatting → finishing' not in sekcja


def test_pulapka_2_opisuje_trzecia_galaz_do_lakierni():
    """
    Nowa gałąź (olejowany/lakierowany bez krawędzi idzie z formatowania prosto
    do Lakierni) też generuje event source='system' — bez wzmianki o niej opis
    filtra jest niepełny dokładnie w tym miejscu, które zmiana wprowadza.
    """
    assert 'painting' in _sekcja_pulapka_2()
