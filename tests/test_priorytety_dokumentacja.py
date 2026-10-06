# -*- coding: utf-8 -*-
"""
Dokumentacja priorytetów produkcji (krok K5) — testy strukturalne na źródle.

CLAUDE.md jest instrukcją dla każdej następnej sesji pracującej w repo. Sekcja „Priorytety produkcji” niesie
kontrakt blokad rang i stołu, którego testy na SQLite nie pilnują (zakleszczenie MySQL 1213 widać dopiero
w wyścigach na prawdziwej bazie). Testy są tanie: pilnują, że sekcja istnieje i wymienia nazwy, po których szuka
się kodu, oraz że akapit o pisarzach pozycji i docstring `blokady_zamowien` nie opisują już końcówek usuniętych
w P1 (przeciąganie, hurtowa i ręczna zmiana priorytetu) — martwy opis myli bardziej niż jego brak.

Spec programu leży w `docs/superpowers/`, który jest śledzony tylko na gałęziach programu. Gdy pliku nie ma
(np. po scaleniu bez dokumentów programu), test specu jest pomijany, a nie czerwony.
"""
import os
import re

import pytest

KORZEN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLAUDE_MD = os.path.join(KORZEN, 'CLAUDE.md')
SPEC = os.path.join(KORZEN, 'docs', 'superpowers', 'specs', '2026-10-04-priorytety-produkcji-design.md')
BLOKADY = os.path.join(KORZEN, 'modules', 'production', 'services', 'blokady_zamowien.py')

NAGLOWEK_SEKCJI = '### Priorytety produkcji'
NAGLOWEK_ARCHITEKTURY = '## Architecture'


def _zrodlo(sciezka):
    with open(sciezka, encoding='utf-8') as f:
        return f.read()


def _plasko(tekst):
    """Tekst bez rozróżniania wielkości liter i łamania wierszy — CLAUDE.md łamie wiersze w środku zdań."""
    return ' '.join(tekst.split()).lower()


def _miedzy(tekst, poczatek, koniec):
    start = tekst.index(poczatek)
    return tekst[start:tekst.index(koniec, start + len(poczatek))]


def _sekcja_priorytetow():
    return _miedzy(_zrodlo(CLAUDE_MD), NAGLOWEK_SEKCJI + '\n', '\n' + NAGLOWEK_ARCHITEKTURY)


def test_claude_md_ma_sekcje_priorytety_produkcji():
    tresc = _zrodlo(CLAUDE_MD)

    assert tresc.count(NAGLOWEK_SEKCJI + '\n') == 1
    assert tresc.index(NAGLOWEK_SEKCJI + '\n') < tresc.index('\n' + NAGLOWEK_ARCHITEKTURY)

    sekcja = ' '.join(_sekcja_priorytetow().split())      # nazwy wielowyrazowe nie zależą od łamania wierszy
    for nazwa in (
        # rangi i ich przeliczanie
        'kolejka.utrwal', 'kolejka.policz', 'priority_service',
        # stół stanowiska: blokada, dopełnianie, uzgadnianie, bramka
        'priorytety_blokada_', 'stol.dopelnij', 'zdejmij_nieaktualne', 'LOCK IN SHARE MODE',
        'nie_na_stole', 'pozycja_poza_stanowiskiem', 'STANOWISKA_BEZ_STOLU',
        # sygnały
        'station:<kod>', '/api/mobile/realtime-token',
        # ustawienia i start stołów
        'priorytety_tryb_', 'priorytety_min_app_version_code', 'prog_wersji_wymagany',
        '/production/api/priorytety/ustawienia', '/production/api/priorytety/start/przygotuj',
        # cron
        'szczeble_uzupelnione', 'priorytety_utrwalone',
    ):
        assert nazwa in sekcja, nazwa


def test_claude_md_opisuje_limit_czekania_i_desk_w_trybie_stary():
    """Dwie reguły, które zmieniły się w kartach naprawczych i których nie ma w planach kroków."""
    sekcja = _plasko(_sekcja_priorytetow())

    assert sekcja.count('najwyżej 5 s') >= 2             # limit czekania `utrwal` i limit dopełniania stołu
    assert 'w trybie `stary` `get desk` tylko czyta' in sekcja


def test_claude_md_bez_martwych_pisarzy_priorytetow():
    tresc = _plasko(_zrodlo(CLAUDE_MD))

    for martwe in (
        'przeciąganie `update-priority`',
        'hurtowa i ręczna zmiana priorytetu',
        'przeciąganie i przeliczenie priorytetów',
    ):
        assert martwe not in tresc, martwe


def test_claude_md_cron_i_logistyka_odsylaja_do_priorytetow():
    tresc = _zrodlo(CLAUDE_MD)

    cron = _plasko(_miedzy(tresc, '### Zadania cykliczne (cron)\n', '\n## Deployment'))
    assert 'szczeble_uzupelnione' in cron
    assert 'priorytety_utrwalone' in cron
    assert 'priorytety produkcji' in cron

    logistyka = _plasko(_miedzy(tresc, '- **Logistyka równoległa:**',
                                '- **Trasy logistyki — jeden piszący naraz:**'))
    assert 'priorytety produkcji' in logistyka
    assert 'utrwal_po_commicie' in logistyka


def test_docstring_blokad_zamowien_zna_kolejnosc_priorytetow():
    """`kolejka.utrwal` blokuje zamówienia przed pozycjami — nie jest już pisarzem pozycji bez blokady zamówienia."""
    zrodlo = _zrodlo(BLOKADY)
    docstring = zrodlo[zrodlo.index('"""'):zrodlo.index('"""', zrodlo.index('"""') + 3)]

    assert 'liczniki sztuk, priorytety, druk tcp' not in _plasko(docstring)
    assert 'kolejka.utrwal' in docstring
    assert 'stol.dopelnij' in docstring


def test_spec_ma_sekcje_16_i_prog_3():
    if not os.path.exists(SPEC):
        pytest.skip('spec programu (docs/superpowers) nie jest częścią tego drzewa')
    tresc = _zrodlo(SPEC)

    assert '\n## 16. Doprecyzowania z realizacji' in tresc
    assert '\n### 16.8 Wyniki K5' in tresc
    # Próg „Blisko terminu”: decyzja 5.10 — 3 dni robocze. Fraza „domyślnie 2” zostaje w 5.1 jako domyślne K.
    sekcja_4_3 = _plasko(_miedzy(tresc, '\n### 4.3 ', '\n### 4.4 '))
    assert re.search(r'domyślnie \**2\**(?!\d)', sekcja_4_3) is None      # „domyślnie 21” to co innego
    assert 'domyślnie **3**' in sekcja_4_3
    sekcja_13 = _plasko(_miedzy(tresc, '\n## 13. ', '\n## 14. '))
    assert 'seed 8 szczebli' not in sekcja_13
