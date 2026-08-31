# -*- coding: utf-8 -*-
"""
W6 — zapora: ścieżka Dębusia Pro nie wolno wołać funkcji `core/chatwoot.py`,
które piszą do rozmowy TOKENEM ADMINA.

Trzy funkcje zapisujące nie przyjmują parametru `token` i mają token admina
zaszyty w nagłówku: `cw_reopen`, `cw_incoming`, `cw_mark_failed`. Wołanie
którejkolwiek z nich ze ścieżki Pro zostawiłoby w rozmowie ślad podpisany
kontem administratora zamiast tożsamością Dębusia Pro — a to jest dokładnie
ta izolacja, na której stoi cały slot kandydata.

DLACZEGO TEST, A NIE ZMIANA SYGNATUR: `core/` jest współdzielone ze starym
silnikiem, który obsługuje dziś żywy ruch (livechat, OLX, Allegro). W tej
gałęzi zmiany w plikach współdzielonych już dwa razy wywołały regresję na
produkcji, więc sygnatur nie ruszamy. Zamiast tego pilnujemy GRANICY: dziś
żadna z tych funkcji nie jest wołana ze ścieżki Pro (stan zastany, sprawdzony
grepem) i ten test ma się zaczerwienić, gdy ktoś takie wywołanie doda.

STAN ZASTANY, ŚWIADOMIE ZAAKCEPTOWANY: ODCZYTY Pro idą tokenem admina, bo
`cw_conv_status`, `cw_messages` i `cw_pending_conversations` w ogóle nie
przyjmują tokenu (`bots_pro/stan.py`, `pro_watchdog.py`). To nie jest do
naprawy — odczyt nie zostawia w rozmowie żadnego śladu, więc nie miesza
tożsamości botów. Ta zapora dotyczy wyłącznie ZAPISÓW.
"""
import ast
import os

import pytest

_KATALOG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Funkcje `core/chatwoot.py`, ktore PISZA do rozmowy i NIE przyjmuja tokenu —
# zawsze uzywaja CW_TOKEN (konto admina).
_ZAKAZANE = ("cw_reopen", "cw_incoming", "cw_mark_failed")


def _pliki_sciezki_pro():
    """Wszystkie pliki zrodlowe skladajace sie na sciezke Debusia Pro."""
    pliki = [os.path.join(_KATALOG, "pro_watchdog.py")]
    katalog_pro = os.path.join(_KATALOG, "bots_pro")
    for nazwa in sorted(os.listdir(katalog_pro)):
        if nazwa.endswith(".py"):
            pliki.append(os.path.join(katalog_pro, nazwa))
    return pliki


def _nazwy_wolanych(drzewo):
    """Nazwy wszystkich wolanych funkcji — i `foo(...)`, i `modul.foo(...)`."""
    nazwy = set()
    for wezel in ast.walk(drzewo):
        if not isinstance(wezel, ast.Call):
            continue
        cel = wezel.func
        if isinstance(cel, ast.Name):
            nazwy.add(cel.id)
        elif isinstance(cel, ast.Attribute):
            nazwy.add(cel.attr)
    return nazwy


def _nazwy_importowane(drzewo):
    """Nazwy sciagniete z `core.chatwoot` (sam import to juz sygnal ostrzegawczy)."""
    nazwy = set()
    for wezel in ast.walk(drzewo):
        if isinstance(wezel, ast.ImportFrom) and (wezel.module or "").endswith("chatwoot"):
            for alias in wezel.names:
                nazwy.add(alias.name)
    return nazwy


def _drzewo(sciezka):
    with open(sciezka, encoding="utf-8") as f:
        return ast.parse(f.read(), filename=sciezka)


@pytest.mark.parametrize("sciezka", _pliki_sciezki_pro(),
                         ids=lambda s: os.path.relpath(s, _KATALOG))
def test_sciezka_pro_nie_wola_funkcji_tokenu_admina(sciezka):
    wolane = _nazwy_wolanych(_drzewo(sciezka))
    zakazane_uzyte = sorted(set(_ZAKAZANE) & wolane)
    assert not zakazane_uzyte, (
        "%s wola %s z core/chatwoot.py — te funkcje nie przyjmuja tokenu i pisza "
        "do rozmowy KONTEM ADMINA, wiec slad zostalby podpisany cudza tozsamoscia. "
        "Uzyj odpowiednika przyjmujacego token (cw_agent_reply / cw_bot_handoff / "
        "cw_note z token=BOT_PRO_CW_AGENT_TOKEN)."
        % (os.path.relpath(sciezka, _KATALOG), ", ".join(zakazane_uzyte)))


@pytest.mark.parametrize("sciezka", _pliki_sciezki_pro(),
                         ids=lambda s: os.path.relpath(s, _KATALOG))
def test_sciezka_pro_nie_importuje_funkcji_tokenu_admina(sciezka):
    """Sam import jeszcze niczego nie psuje, ale nie ma po co go robic — a jego
    obecnosc oznacza, ze ktos zaraz zawola (albo juz wola posrednio)."""
    importowane = sorted(set(_ZAKAZANE) & _nazwy_importowane(_drzewo(sciezka)))
    assert not importowane, (
        "%s importuje %s z core/chatwoot.py — patrz docstring tego pliku."
        % (os.path.relpath(sciezka, _KATALOG), ", ".join(importowane)))


def test_zapora_widzi_wszystkie_pliki_sciezki_pro():
    """Kontrola samej zapory: gdyby `_pliki_sciezki_pro` zwrocilo pusta liste
    (przeniesiony katalog, zmiana nazwy), parametryzacja przestalaby cokolwiek
    sprawdzac, a suite dalej swiecilby na zielono."""
    pliki = _pliki_sciezki_pro()
    assert len(pliki) > 5
    nazwy = {os.path.basename(p) for p in pliki}
    for wymagany in ("pro_watchdog.py", "stan.py", "notatki.py", "narzedzia.py",
                     "tura.py", "podsumowanie.py"):
        assert wymagany in nazwy
