"""Straznik: plakietka dopłaty musi znikac, gdy dopłaty nie ma.

Regresja z 2026-09-15: `.shape-surcharge-badge` ma `display: inline-flex`, a ta
regula z arkusza AUTORA bije `[hidden] { display: none }` z arkusza przegladarki.
Skutek: przy prostokacie (czyli zawsze, gdy doplaty nie ma) w naglowku
„Kalkulacja" wisiala pusta pomaranczowa pigulka — zmierzone 22x10 px, sama ramka
i tlo, bez tekstu. Samo ustawienie atrybutu `hidden` w JS tego NIE zalatwia.
"""
import io
import os
import re

KATALOG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSS = os.path.join(KATALOG, 'modules', 'calculator', 'static', 'css',
                   'calculator_variants.css')
SZABLON = os.path.join(KATALOG, 'modules', 'calculator', 'templates', 'calculator.html')


def _css():
    return io.open(CSS, encoding='utf-8').read()


def test_regula_ukrywajaca_plakietke_istnieje():
    tresc = _css()
    blok = re.search(
        r'\.shape-surcharge-badge\[hidden\]\s*\{([^}]*)\}', tresc)
    assert blok, (
        'Brak reguly .shape-surcharge-badge[hidden] — bez niej atrybut hidden '
        'nie dziala i w naglowku wisi pusta pigulka.')
    assert 'display' in blok.group(1) and 'none' in blok.group(1)


def test_plakietka_w_szablonie_startuje_ukryta():
    """Przed pierwszym przeliczeniem plakietka nie ma tresci — ma byc niewidoczna."""
    tresc = io.open(SZABLON, encoding='utf-8').read()
    znacznik = re.search(r'<span[^>]*data-shape-surcharge-badge[^>]*>', tresc)
    assert znacznik, 'Zniknal znacznik plakietki z naglowka Kalkulacji'
    assert 'hidden' in znacznik.group(0), 'Plakietka musi startowac z atrybutem hidden'


def test_kazda_regula_display_ma_pare_w_postaci_hidden():
    """Gdyby ktos dolozyl kolejny selektor ustawiajacy display na plakietce,
    regula [hidden] musi nadal wystepowac PO nim, inaczej wroci ten sam bug."""
    tresc = _css()
    pozycja_hidden = tresc.find('.shape-surcharge-badge[hidden]')
    assert pozycja_hidden != -1
    # selektory ustawiajace display na plakietce PO regule [hidden] sa podejrzane
    ogon = tresc[pozycja_hidden + 1:]
    for dopasowanie in re.finditer(
            r'\.shape-surcharge-badge(?!\[hidden\])[^{]*\{([^}]*)\}', ogon):
        assert 'display' not in dopasowanie.group(1), (
            'Selektor ustawiajacy display na plakietce pojawil sie PO regule '
            '[hidden] — przeslania ja i przywraca bug pustej pigulki.')
