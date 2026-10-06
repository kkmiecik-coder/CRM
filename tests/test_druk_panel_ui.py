# -*- coding: utf-8 -*-
"""Panel Konfiguracja: karta drukarki z wyborem drukarki i przesunięciem paczek
(logistyka etap 4, krok 4.1). Testy tekstu źródła — repo nie ma runnera JS,
a szablon renderuje się tylko w pełnej apce."""
import os
import re

KORZEN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SZABLON = os.path.join(KORZEN, 'modules', 'production', 'templates', 'components', 'config-tab-content.html')
SKRYPT = os.path.join(KORZEN, 'modules', 'production', 'static', 'js', 'modules', 'config-module.js')
STYL = os.path.join(KORZEN, 'modules', 'production', 'static', 'css', 'config-tab.css')
PANEL = os.path.join(KORZEN, 'modules', 'production', 'templates', 'panel', 'dashboard.html')
POLA = (('PACKAGE_LABEL_OFFSET_X_DOTS', 'package_label_offset_x'),
        ('PACKAGE_LABEL_OFFSET_Y_DOTS', 'package_label_offset_y'))
# 11 pozycji karty drukarki i grupa, do której każda należy (po id pola wejściowego)
GRUPY_POL = {
    'etykiety': ('label_printer_ip', 'label_printer_port', 'label_printer_timeout',
                 'label_printer_retry', 'label_printer_offset_lt', 'label_printer_offset_ls',
                 'label_printer_allowed_stations'),
    'wysylka': ('package_label_offset_x', 'package_label_offset_y'),
    'wspolne': ('label_printer_use_agent', 'label_printer_agent_token'),
}


def _czytaj(sciezka):
    with open(sciezka, encoding='utf-8') as plik:
        return plik.read()


def _karta_drukarki(html):
    """Fragment szablonu z kartą drukarki: od jej komentarza do następnej karty."""
    poczatek = html.index('<!-- Drukarka etykiet -->')
    return html[poczatek:html.index('<!-- Terminy -->', poczatek)]


def _otwarcie_grupy(karta, nazwa):
    """Znacznik otwierający kontener grupy (z ewentualnym atrybutem hidden)."""
    znaleziono = re.search(
        r'<div class="config-drukarka-grupa" data-drukarka="%s"[^>]*>' % nazwa, karta)
    assert znaleziono, nazwa
    return znaleziono


def _grupa(karta, nazwa):
    """Cały kontener grupy: od jego otwarcia do znacznika zamknięcia, który stoi tuż za </div>."""
    poczatek = _otwarcie_grupy(karta, nazwa).start()
    koniec = karta.index('<!-- /grupa %s -->' % nazwa, poczatek)
    fragment = karta[poczatek:koniec]
    # znacznik faktycznie zamyka kontener grupy, a nie któryś wewnętrzny div
    assert fragment.count('<div') == fragment.count('</div>'), nazwa
    assert fragment.rstrip().endswith('</div>'), nazwa
    return fragment


def _metoda(js, naglowek):
    """Ciało metody klasy w config-module.js: od nagłówka do zamknięcia na wcięciu klasy."""
    poczatek = js.index(naglowek)
    return js[poczatek:js.index('\n    }\n', poczatek)]


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


def test_lista_wyboru_drukarki_na_gorze_karty():
    karta = _karta_drukarki(_czytaj(SZABLON))
    lista = re.search(r'<select[^>]*id="drukarka_wybor"[^>]*>(.*?)</select>', karta, re.S)
    assert lista, 'brak <select id="drukarka_wybor">'
    opcje = re.findall(r'<option value="([^"]+)"[^>]*>([^<]*)</option>', lista.group(1))
    assert opcje == [('etykiety', 'Etykiety produktów (60×40)'),
                     ('wysylka', 'Paczki (100×150)')]
    # domyślnie etykiety; opcja paczek nie jest wstępnie wybrana
    assert re.search(r'<option value="etykiety"[^>]*\bselected\b', lista.group(1))
    assert not re.search(r'<option value="wysylka"[^>]*\bselected\b', lista.group(1))
    # etykieta „Drukarka” powiązana z listą
    assert re.search(r'<label[^>]*for="drukarka_wybor"[^>]*>\s*Drukarka\s*</label>', karta)
    # lista nie jest kluczem konfiguracji: nie zgłasza zmiany do paska zapisu ani do resetu
    tag_listy = re.search(r'<select[^>]*id="drukarka_wybor"[^>]*>', karta).group(0)
    assert 'configChanged' not in tag_listy and 'resetToDefault' not in tag_listy
    assert 'onchange="wybierzDrukarke(this.value)"' in tag_listy
    # lista jest pierwszym elementem treści karty, przed wszystkimi grupami
    assert karta.index('id="drukarka_wybor"') < karta.index('data-drukarka="etykiety"')


def test_kazda_pozycja_karty_lezy_w_jednej_grupie():
    karta = _karta_drukarki(_czytaj(SZABLON))
    grupy = {nazwa: _grupa(karta, nazwa) for nazwa in GRUPY_POL}
    for nazwa, pola in GRUPY_POL.items():
        for pole in pola:
            wpis = 'id="%s"' % pole
            assert karta.count(wpis) == 1, pole
            assert wpis in grupy[nazwa], '%s poza grupą %s' % (pole, nazwa)
            for inna, fragment in grupy.items():
                if inna != nazwa:
                    assert wpis not in fragment, '%s także w grupie %s' % (pole, inna)
    # 11 pozycji w grupach; poza nimi tylko wybór drukarki i „Wydruk próbny”
    w_grupach = sum(f.count('<div class="config-item">') for f in grupy.values())
    assert w_grupach == 11
    assert karta.count('<div class="config-item">') == 11 + 2


def test_grupy_ukrywane_atrybutem_hidden():
    karta = _karta_drukarki(_czytaj(SZABLON))
    # stan początkowy zgodny z domyślną listą (etykiety): paczki ukryte, reszta widoczna
    assert ' hidden' in _otwarcie_grupy(karta, 'wysylka').group(0)
    assert ' hidden' not in _otwarcie_grupy(karta, 'etykiety').group(0)
    assert ' hidden' not in _otwarcie_grupy(karta, 'wspolne').group(0)
    # nagłówek grupy wspólnej
    assert 'Agent druku — wspólne dla obu drukarek' in _grupa(karta, 'wspolne')
    # opis trybu bezpośredniego stoi przed pozycjami, których agent druku nie używa
    etykiety = _grupa(karta, 'etykiety')
    assert 'Dotyczy trybu bez agenta druku' in etykiety
    assert etykiety.index('Dotyczy trybu bez agenta druku') < etykiety.index('id="label_printer_ip"')


def test_jeden_przycisk_wydruku_probnego():
    html = _czytaj(SZABLON)
    karta = _karta_drukarki(html)
    # dwa przyciski z zadania 5 zniknęły; został jeden, wołający funkcję czytającą listę
    assert "wydrukProbny('etykiety')" not in html and "wydrukProbny('wysylka')" not in html
    assert re.findall(r'onclick="(wydruk[^"]*)"', karta) == ['wydrukProbnyWybranej()']
    przycisk = re.search(r'<button[^>]*onclick="wydrukProbnyWybranej\(\)"[^>]*>(.*?)</button>', karta, re.S)
    assert przycisk
    assert 'type="button"' in przycisk.group(0)
    assert 'fas fa-print' in przycisk.group(1)
    assert 'Wydruk próbny' in przycisk.group(1)
    # widoczny dla obu drukarek: poza grupami wybranej drukarki
    for nazwa in GRUPY_POL:
        assert 'wydrukProbnyWybranej' not in _grupa(karta, nazwa)
    # opis pozycji jest neutralny wobec wybranej drukarki
    assert 'Wysyła etykietę testową wybranej drukarki' in karta


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
    metoda = _metoda(js, 'async wydrukProbny(drukarka) {')
    assert "'warning'" in metoda
    assert 'response.json().catch(' in metoda


def test_wybor_drukarki_w_skrypcie():
    js = _czytaj(SKRYPT)
    # wybór pamiętany w localStorage pod jednym kluczem; odczyt i zapis w try/catch
    assert "'konfiguracja.drukarka'" in js
    for naglowek in ('odczytajZapamietanaDrukarke() {', 'zapamietajDrukarke(drukarka) {'):
        cialo = _metoda(js, naglowek)
        assert 'localStorage' in cialo, naglowek
        assert cialo.index('try {') < cialo.index('localStorage') < cialo.index('catch'), naglowek
    # nieznana wartość wraca do etykiet
    assert "const DRUKARKA_DOMYSLNA = 'etykiety'" in js
    assert "const DRUKARKI = ['etykiety', 'wysylka']" in js
    assert 'DRUKARKI.includes(' in _metoda(js, 'normalizujDrukarke(wartosc) {')
    # grupy pokazywane i ukrywane bez przeładowania; wspólna zawsze widoczna
    pokaz = _metoda(js, 'pokazGrupeDrukarki(drukarka) {')
    assert "'wspolne'" in pokaz and '.hidden' in pokaz
    # stan początkowy ustawiany po załadowaniu zakładki (treść przychodzi przez AJAX),
    # a nie na DOMContentLoaded
    assert 'this.initWyborDrukarki()' in _metoda(js, 'loadOriginalValuesFromDOM() {')
    assert 'this.pokazGrupeDrukarki(' in _metoda(js, 'initWyborDrukarki() {')
    # lista nie jest kluczem konfiguracji: poza mapą pól czytaną do originalValues
    assert 'drukarka_wybor' not in js.split('const fieldMappings = {')[1].split('};')[0]
    assert 'window.wybierzDrukarke = function' in js
    # jedna ścieżka wydruku: przycisk -> wydrukProbnyWybranej -> wydrukProbny(<wartość listy>)
    assert 'window.wydrukProbnyWybranej = function' in js
    wybrana = _metoda(js, 'wydrukProbnyWybranej() {')
    assert "getElementById('drukarka_wybor')" in wybrana
    assert 'this.wydrukProbny(' in wybrana


def test_ostrzezenie_o_niezapisanych_przesunieciach_zalezy_od_drukarki():
    js = _czytaj(SKRYPT)
    metoda = _metoda(js, 'async wydrukProbny(drukarka) {')
    # sprawdzane są tylko klucze wybranej drukarki
    assert "drukarka === 'wysylka'" in metoda
    assert "'PACKAGE_LABEL_OFFSET_'" in metoda and "'LABEL_PRINTER_OFFSET_'" in metoda
    assert "klucz.startsWith('PACKAGE_LABEL_OFFSET_') || klucz.startsWith('LABEL_PRINTER_OFFSET_')" not in js


def test_nowa_wersja_skryptu_i_stylu_konfiguracji():
    panel = _czytaj(PANEL)
    assert "js/modules/config-module.js') }}?v=20261005c\"" in panel
    assert "css/config-tab.css') }}?v=20261005\"" in panel
    # style nagłówków grup istnieją
    assert '.config-drukarka-naglowek' in _czytaj(STYL)
