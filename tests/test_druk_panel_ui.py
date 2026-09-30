# -*- coding: utf-8 -*-
"""Panel Konfiguracja: drukarka paczek (logistyka etap 4, krok 4.1). Testy tekstu źródła —
repo nie ma runnera JS, a szablon renderuje się tylko w pełnej apce."""
import os
import re

KORZEN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SZABLON = os.path.join(KORZEN, 'modules', 'production', 'templates', 'components', 'config-tab-content.html')
SKRYPT = os.path.join(KORZEN, 'modules', 'production', 'static', 'js', 'modules', 'config-module.js')
PANEL = os.path.join(KORZEN, 'modules', 'production', 'templates', 'panel', 'dashboard.html')
POLA = (('PACKAGE_LABEL_OFFSET_X_DOTS', 'package_label_offset_x'),
        ('PACKAGE_LABEL_OFFSET_Y_DOTS', 'package_label_offset_y'))


def _czytaj(sciezka):
    with open(sciezka, encoding='utf-8') as plik:
        return plik.read()


def test_pola_przesuniecia_w_szablonie():
    html = _czytaj(SZABLON)
    for klucz, pole in POLA:
        assert 'id="%s"' % pole in html
        assert "configChanged('%s', parseInt(this.value))" % klucz in html
        assert "resetToDefault('%s')" % klucz in html
        assert 'config_groups.printer.%s.value|default(0)' % klucz in html
        # zakres sprawdzany osobno dla każdego pola (baza szablonu ma już jedno takie pole)
        pole_input = re.search(r'<input[^>]*id="%s"[^>]*>' % pole, html, re.S)
        assert pole_input, pole
        assert 'min="-120"' in pole_input.group(0)
        assert 'max="120"' in pole_input.group(0)


def test_przyciski_wydruku_probnego():
    html = _czytaj(SZABLON)
    assert "wydrukProbny('etykiety')" in html and "wydrukProbny('wysylka')" in html


def test_skrypt_zna_pola_i_wydruk():
    js = _czytaj(SKRYPT)
    for klucz, pole in POLA:
        assert "'%s': 0" % klucz in js                     # defaultValues
        assert "'%s': '%s'" % (pole, klucz) in js          # odczyt wartości z formularza
        assert js.count("'%s': '%s'" % (klucz, pole)) == 2  # updateFormField + mapa odwrotna
    assert "fetch('/production/api/print-test'" in js
    assert 'async wydrukProbny(drukarka)' in js
    assert 'window.wydrukProbny = function' in js
    # jeden komunikat po wydruku: ostrzeżenie zamiast sukcesu przy niezapisanym przesunięciu,
    # a odpowiedź nie-JSON (502, logowanie) nie może wywalić parsowania
    poczatek = js.index('async wydrukProbny(drukarka)')
    metoda = js[poczatek:js.index('// CACHE MANAGEMENT', poczatek)]
    assert "'warning'" in metoda
    assert 'response.json().catch(' in metoda


def test_nowa_wersja_skryptu_konfiguracji():
    assert "js/modules/config-module.js') }}?v=20260930" in _czytaj(PANEL)
