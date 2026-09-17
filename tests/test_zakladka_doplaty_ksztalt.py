# -*- coding: utf-8 -*-
"""Podzakładka „Dopłaty za kształt" — obie dopłaty w jednym miejscu.

Wczesniej lezaly osobno: kolo/owal w Wykonczeniach -> Obrobka krawedzi,
ksztalt nietypowy pod tabela Cennika drewna. Nikt nie widzial ich obok siebie
ani tego, ze sie WYKLUCZAJA (produkt ma jeden ksztalt). Te testy pilnuja, zeby
przy kolejnych porzadkach nie rozjechaly sie z powrotem.
"""
import io
import os
import re

KATALOG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SZABLON = os.path.join(KATALOG, 'modules', 'settings', 'templates', 'settings_index.html')
ROUTERY = os.path.join(KATALOG, 'modules', 'settings', 'routers.py')
JS = os.path.join(KATALOG, 'modules', 'settings', 'static', 'js', 'settings.js')


def _plik(sciezka):
    return io.open(sciezka, encoding='utf-8').read()


def test_trasa_podzakladki_istnieje():
    tresc = _plik(ROUTERY)
    assert "@settings_bp.route('/calculator/shape-surcharges')" in tresc
    assert 'def calculator_shape_surcharges(' in tresc


def test_trasa_podaje_obie_kwoty_do_szablonu():
    tresc = _plik(ROUTERY)
    blok = re.search(r'def calculator_shape_surcharges\(.*?\n\n\n', tresc, re.S)
    assert blok, 'Nie znaleziono ciala funkcji podzakladki'
    assert 'round_shape_surcharge_netto' in blok.group(0)
    assert 'custom_shape_surcharge_netto' in blok.group(0)
    assert "calculator_subtab='shape_surcharges'" in blok.group(0)


def test_zakladka_jest_w_nawigacji():
    tresc = _plik(SZABLON)
    assert "url_for('settings.calculator_shape_surcharges')" in tresc
    assert 'Dopłaty za kształt' in tresc


def _sekcje_podzakladek():
    """Dzieli szablon na sekcje po komentarzach `<!-- Podzakładka: ... -->`.

    Kotwiczymy sie na komentarzach, a NIE na `{% if calculator_subtab == ... %}`,
    bo ten sam warunek wystepuje takze w linkach nawigacji (klasa `active`)
    i regex lapal tam pusty fragment zamiast tresci sekcji.
    """
    tresc = _plik(SZABLON)
    kawalki = re.split(r'<!-- Podzakładka: (.+?) -->', tresc)
    # kawalki[0] to naglowek + nawigacja; dalej naprzemiennie nazwa, tresc
    return {kawalki[i].strip(): kawalki[i + 1] for i in range(1, len(kawalki) - 1, 2)}


def test_obie_kwoty_sa_w_tej_samej_podzakladce():
    sekcje = _sekcje_podzakladek()
    assert 'Dopłaty za kształt' in sekcje, f'Brak sekcji; sa: {list(sekcje)}'
    doplaty = sekcje['Dopłaty za kształt']
    assert 'id="roundSurchargeNetto"' in doplaty
    assert 'id="customShapeSurchargeNetto"' in doplaty


def test_kwoty_zniknely_ze_starych_miejsc():
    """Cennik drewna i Cennik dodatkowy nie moga juz trzymac tych pol."""
    sekcje = _sekcje_podzakladek()
    for nazwa in ('Cennik', 'Cennik dodatkowy'):
        assert nazwa in sekcje, f'Brak sekcji {nazwa}'
        assert 'roundSurchargeNetto' not in sekcje[nazwa], nazwa
        assert 'customShapeSurchargeNetto' not in sekcje[nazwa], nazwa


def test_jeden_przycisk_zapisuje_obie_kwoty():
    """Jedno zadanie = walidacja calosci po stronie backendu, bez czesciowego zapisu."""
    tresc = _plik(JS)
    assert "getElementById('saveShapeSurchargesBtn')" in tresc
    blok = re.search(r"saveShapeSurchargesBtn'\)\?\.addEventListener\((.+?)\n    \}\);", tresc, re.S)
    assert blok, 'Nie znaleziono handlera zapisu'
    assert 'round_shape_surcharge_netto' in blok.group(1)
    assert 'custom_shape_surcharge_netto' in blok.group(1)


def test_stare_handlery_usuniete():
    tresc = _plik(JS)
    assert 'saveRoundSurchargeBtn' not in tresc
    assert 'saveCustomShapeSurchargeBtn' not in tresc
