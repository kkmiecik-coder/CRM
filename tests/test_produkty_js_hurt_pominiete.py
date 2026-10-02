# -*- coding: utf-8 -*-
"""
Hurtowa zmiana statusu w products-module.js pokazuje zamówienia pominięte przez serwer (Ruling 30.7 fali końcowej
kroku 4.4b). Hurt odmawia per zamówienie (np. zamówienie na trasie załadowanej albo w drodze) i zwraca `success: true`
z komunikatami w `errors` i liczbą w `failed_count` — dotąd front pokazywał tylko liczbę zmienionych.

Frontu nie da się tu uruchomić (obraz testowy jest bez node'a) — sprawdzamy źródło (konwencja
tests/test_produkty_js_klasy_statusow.py). Komunikaty serwera niosą dane (numer zamówienia, nazwa trasy), a okienko
powiadomień (ToastSystem w shared-services.js) składa treść przez innerHTML — każdy komunikat musi przejść przez
escapeHtml.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests.krawedzie_fixtures import JS_PRODUKTY, KORZEN, zrodlo

SZABLON_DASHBOARDU = os.path.join(KORZEN, 'modules', 'production', 'templates', 'panel', 'dashboard.html')


def _metoda(naglowek):
    js = zrodlo(JS_PRODUKTY)
    assert naglowek in js, u'brak kotwicy: {}'.format(naglowek)
    metoda = js[js.index(naglowek):]
    return metoda[:metoda.index('\n    }\n')]


def test_zmiana_statusu_po_sukcesie_pokazuje_pominiete():
    metoda = _metoda('    async executeBulkStatusChange(selectedIds, newStatus) {')
    sukces = metoda[metoda.index('if (result.success) {'):metoda.index('} else {')]
    assert 'this.showBulkStatusSkipped(result);' in sukces


def test_pominiete_z_komunikatami_i_liczba_tylko_przez_escapowanie():
    metoda = _metoda('    showBulkStatusSkipped(result) {')
    assert 'result.errors' in metoda and 'result.failed_count' in metoda
    # Brak pominiętych — bez dodatkowego okienka.
    assert 'if (!komunikaty.length && !pominieto) return;' in metoda
    # Okienko powiadomień: każdy komunikat i nagłówek przez escapeHtml, bez surowych danych w szablonie HTML.
    toast = metoda[metoda.index('if (this.shared?.toastSystem) {'):metoda.index('} else {')]
    assert 'komunikaty.map((k) => this.escapeHtml(k))' in toast
    assert 'this.escapeHtml(naglowek)' in toast
    assert "'warning'" in toast and 'persistent: true' in toast
    assert not re.search(r'\$\{\s*k\s*\}|\$\{\s*komunikat', metoda)
    assert 'innerHTML' not in metoda
    # Okno alert dostaje czysty tekst (alert nie interpretuje HTML).
    assert "alert([naglowek, ...komunikaty].join('\\n'));" in metoda


def test_podbita_wersja_pliku_w_szablonie():
    szablon = zrodlo(SZABLON_DASHBOARDU)
    wpis = re.search(r"js/modules/products-module\.js'\) \}\}\?v=(\d+[a-z]?)", szablon)
    assert wpis is not None and wpis.group(1) >= '20261002a', wpis and wpis.group(1)
