# -*- coding: utf-8 -*-
"""Krok 4.3, spec 8.7: okno decyzji o przepakowaniu w zakładce Logistyka (testy statyczne frontu)."""
import os
import re

KATALOG = os.path.join(os.path.dirname(__file__), '..', 'modules', 'production', 'logistics')


def _plik(*czesci):
    with open(os.path.join(KATALOG, *czesci), encoding='utf-8') as f:
        return f.read()


def _funkcja(js, nazwa):
    """Treść funkcji z IIFE (wcięcie 4 spacje) — od nagłówka do zamykającej klamry."""
    start = js.index('function ' + nazwa + '(')
    return js[start:js.index('\n    }\n', start)]


def test_szablon_ma_okno_przepakowania():
    html = _plik('templates', 'logistics', 'tab_content.html')
    assert re.search(r'<dialog[^>]+data-lg="przepakowanie-dialog"', html)
    assert 'Cofnij do pakowania' in html and 'Anuluj' in html


def test_szablon_okna_ma_dostepnosc_i_trzy_przyciski():
    html = _plik('templates', 'logistics', 'tab_content.html')
    okno = html[html.index('data-lg="przepakowanie-dialog"'):]
    okno = okno[:okno.index('</dialog>')]
    assert 'aria-labelledby="lg-przepak-tytul"' in okno and 'id="lg-przepak-tytul"' in okno
    assert 'aria-live="polite"' in okno                       # zmiana treści między krokami
    # Anuluj pierwszy w kodzie (fokus startowy, bezpieczny wybór), główny „Cofnij” ostatni.
    kolejnosc = [okno.index('data-lg="przepak-' + p + '"') for p in ('anuluj', 'bez', 'cofnij')]
    assert kolejnosc == sorted(kolejnosc)
    assert 'Zmień bez przepakowania' in okno and 'lg-przycisk--glowny" data-lg="przepak-cofnij"' in okno
    # Bez `data-lg-akcja`: delegacja kliknięć zakładki nie może łapać przycisków okna.
    assert 'data-lg-akcja' not in okno


def test_js_wysyla_decyzje_i_obsluguje_kod_serwera():
    js = _plik('static', 'js', 'logistics.js')
    assert 'przepakowanie:' in js or "przepakowanie'" in js
    assert 'wymaga_decyzji_przepakowania' in js
    assert re.search(r'function przepakowanieObowiazkowe\(', js)
    assert re.search(r'function zapytajOPrzepakowanie\(', js)


def test_js_pole_przepakowanie_tylko_z_decyzja():
    js = _plik('static', 'js', 'logistics.js')
    wyslij = _funkcja(js, 'wyslijSposob')
    assert 'async function wyslijSposob(ids, sposob, przepakowanie)' in js
    assert 'if (przepakowanie !== undefined) dane.przepakowanie = przepakowanie;' in wyslij


def test_js_obowiazkowe_wg_spec_8_7():
    js = _plik('static', 'js', 'logistics.js')
    obowiazkowe = _funkcja(js, 'przepakowanieObowiazkowe')
    assert "sposob === 'brak'" in obowiazkowe
    assert "sposob === 'kurier_baselinker'" in obowiazkowe
    assert "w.sposob === 'transport_woodpower'" in obowiazkowe and "w.sposob === 'odbior_osobisty'" in obowiazkowe


def test_js_anuluj_nic_nie_wysyla():
    js = _plik('static', 'js', 'logistics.js')
    # Po null z okna (Anuluj) ścieżki select / dymek / hurt kończą się przed wyslijSposob.
    assert re.search(r'zapytajOPrzepakowanie\([^)]*\)[\s\S]{0,400}?if \(!decyzja\)', js)


def test_js_kazda_sciezka_zmiany_pyta_przed_wyslaniem():
    """Select w wierszu, dymek mapy i obie akcje hurtowe pytają o spakowane zamówienia PRZED żądaniem,
    a Anuluj (null) kończy ścieżkę bez niego."""
    js = _plik('static', 'js', 'logistics.js')
    for nazwa, wysylka in (('zmianaSelecta', 'wyslijSposobZDecyzja('), ('zmienSposobZMapy', 'wyslijSposobZDecyzja('),
                           ('hurtSposob', 'hurtowo('), ('hurtPodpowiedzi', 'hurtowo(')):
        f = _funkcja(js, nazwa)
        assert f.index('zapytajOPrzepakowanie(') < f.index('!decyzja') < f.rindex(wysylka), nazwa
    # Wiersz niespakowany albo bez zmiany sposobu nie dostaje okna.
    assert 'biezacy.spakowane && wartosc !== (biezacy.sposob || \'brak\')' in _funkcja(js, 'zmianaSelecta')
    assert 'if (w.spakowane) {' in _funkcja(js, 'zmienSposobZMapy')
    hurt = _funkcja(js, 'hurtSposob')
    assert "sposob !== (w.sposob || 'brak')" in hurt and 'zmieniane.filter((w) => w.spakowane)' in hurt


def test_js_anuluj_w_selecie_i_dymku_przywraca_wiersz():
    js = _plik('static', 'js', 'logistics.js')
    for nazwa in ('zmianaSelecta', 'zmienSposobZMapy'):
        f = _funkcja(js, nazwa)
        galaz = f[f.index('if (!decyzja) {'):]
        galaz = galaz[:galaz.index('przepakowanie = decyzja.przepakuj.length > 0;')]
        assert 'odswiezWiersz(id, false);' in galaz and 'return;' in galaz, nazwa


def test_js_ponowienie_po_kodzie_serwera_raz():
    js = _plik('static', 'js', 'logistics.js')
    f = _funkcja(js, 'wyslijSposobZDecyzja')
    # Odmowy z kodem wychodzą z listy błędów, okno pyta o te zamówienia, wysyłka idzie jeszcze raz.
    assert "b.kod === 'wymaga_decyzji_przepakowania'" in f
    assert "b.kod !== 'wymaga_decyzji_przepakowania'" in f
    assert 'dane.orders' in f and 'zapytajOPrzepakowanie(wiersze, sposob)' in f
    # Raz: drugie żądania to surowy wyslijSposob, bez kolejnego ponowienia.
    assert f.count('await wyslijSposob(') == 2 and 'wyslijSposobZDecyzja(' not in f.split('{', 1)[1]
    assert 'wynik.anulowane' in f and 'przepakowanie: true' in f and 'przepakowanie: false' in f


def test_js_hurt_lista_zadan_i_pominiete():
    js = _plik('static', 'js', 'logistics.js')
    hurt = _funkcja(js, 'hurtowo')
    assert 'async function hurtowo(zadania, opisAkcji, pominiete)' in js
    assert 'zadanie.przepakowanie' in hurt and 'LIMIT_HURTU' in hurt
    assert 'new Map([[sposob, ids]])' not in js
    zadania = _funkcja(js, 'zadaniaHurtu')
    assert 'przepakuj.has(id) ? true : (bez.has(id) ? false : undefined)' in zadania
    assert 'if (pomin.has(id)) return;' in zadania            # pominięte nie idą na serwer
    # Podpowiedzi: jedno okno dla partii, cel liczony per zamówienie.
    assert 'zapytajOPrzepakowanie(spakowane, (w) => w.podpowiedz' in _funkcja(js, 'hurtPodpowiedzi')
    podsumowanie = _funkcja(js, 'podsumujZmiany')
    assert "'Pominięto (wymagają cofnięcia do pakowania): '" in podsumowanie


def test_js_drugie_okno_hurtu_i_przyciski():
    js = _plik('static', 'js', 'logistics.js')
    assert 'function pokazKrokDrugi(' in js
    for tekst in ('Cofnij je do pakowania', 'Pomiń je', 'Cofnij do pakowania', 'Zmień bez przepakowania',
                  ' z nich ', 'cofnięcia do pakowania'):
        assert tekst in js, tekst
    # Lista numerów: do 10, potem „i N innych”.
    assert "numery.slice(0, 10)" in js and "' innych'" in js
    # Esc i klik w tło = Anuluj; po zamknięciu fokus wraca na element, który otworzył okno.
    assert "addEventListener('cancel'" in js[js.index('const dialogPrzepak'):]
    zamykanie = _funkcja(js, 'zamknijOkno')
    assert 'o.powrot' in zamykanie and zamykanie.index('.focus(') < zamykanie.index('o.rozwiaz(wynik)')


def test_js_komunikat_przepakowania_bez_kuriera():
    js = _plik('static', 'js', 'logistics.js')
    assert 'czeka na przepakowanie na kuriera' not in js
    podsumowanie = _funkcja(js, 'podsumujZmiany')
    assert "' wraca do pakowania.'" in podsumowanie and "'Wracają do pakowania: '" in podsumowanie
    html = _plik('templates', 'logistics', 'tab_content.html')
    assert 'czeka na przepakowanie na kuriera' not in html


def test_okno_bez_animacji_wejscia():
    css = _plik('static', 'css', 'logistics.css')
    blok = css[css.index('Okno decyzji o przepakowaniu'):css.index('Sortowanie z nagłówka')]
    assert 'animation' not in blok and 'transition' not in blok and '@keyframes' not in blok


def test_wersje_podbite_po_oknie_przepakowania():
    html = _plik('templates', 'logistics', 'tab_content.html')
    for plik in ('js/logistics.js', 'css/logistics.css'):
        m = re.search(r"filename='" + re.escape(plik) + r"'\) \}\}\?v=(\w+)", html)
        assert m and m.group(1) >= '20261001c', plik
