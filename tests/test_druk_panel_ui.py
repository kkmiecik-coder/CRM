# -*- coding: utf-8 -*-
"""Ustawienia drukarek w zakładce „Drukarki” (agent druku v2): po końcu okresu przejściowego (23.10.2026) zostało
tylko pole stanowisk uprawnionych w „Ustawieniach druku”; karta starego agenta i przełącznik obsługi zniknęły.
Testy tekstu źródła — repo nie ma runnera JS; render zakładki sprawdza tests/test_drukarki_panel.py."""
import os
import re

KORZEN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROD = os.path.join(KORZEN, 'modules', 'production')
KONFIGURACJA = os.path.join(PROD, 'templates', 'components', 'config-tab-content.html')
DRUKARKI = os.path.join(PROD, 'templates', 'components', 'printers-tab-content.html')
SKRYPT_KONFIGURACJI = os.path.join(PROD, 'static', 'js', 'modules', 'config-module.js')
SKRYPT_DRUKAREK = os.path.join(PROD, 'static', 'js', 'modules', 'printers-tab.js')
LOADER = os.path.join(PROD, 'static', 'js', 'production-app-loader.js')
STYL_KONFIGURACJI = os.path.join(PROD, 'static', 'css', 'config-tab.css')
STYL_DRUKAREK = os.path.join(PROD, 'static', 'css', 'printers-tab.css')
PANEL = os.path.join(PROD, 'templates', 'panel', 'dashboard.html')

# Pola dawnej karty „Drukarka etykiet”: id pola -> klucz prod_config
POLA_DAWNEJ_KARTY = {
    'label_printer_ip': 'LABEL_PRINTER_IP',
    'label_printer_port': 'LABEL_PRINTER_PORT',
    'label_printer_timeout': 'LABEL_PRINTER_TIMEOUT_SECONDS',
    'label_printer_retry': 'LABEL_PRINTER_RETRY_COUNT',
    'label_printer_allowed_stations': 'LABEL_PRINTER_ALLOWED_STATIONS',
    'label_printer_use_agent': 'LABEL_PRINTER_USE_AGENT',
    'label_printer_agent_token': 'LABEL_PRINTER_AGENT_TOKEN',
}
POLA_PRZESUNIEC = ('label_printer_offset_lt', 'label_printer_offset_ls', 'package_label_offset_x',
                   'package_label_offset_y')


def _czytaj(sciezka):
    with open(sciezka, encoding='utf-8') as plik:
        return plik.read()


def test_konfiguracja_bez_karty_drukarki():
    """Karta „Drukarka etykiet” zniknęła z Konfiguracji całkowicie (decyzja Konrada 22.10) — wszystko o drukarkach
    jest w zakładce „Drukarki”; po kracie „Pracownicy na tabletach” od razu „Terminy”."""
    html = _czytaj(KONFIGURACJA)
    for pole in list(POLA_DAWNEJ_KARTY) + list(POLA_PRZESUNIEC) + ['drukarka_wybor']:
        assert 'id="%s"' % pole not in html, pole
    assert 'LABEL_PRINTER_' not in html and 'PACKAGE_LABEL_' not in html
    assert 'wydrukProbny' not in html
    assert 'Drukarka etykiet' not in html and 'data-goto-tab="printers-tab"' not in html
    assert html.index('<h4>Pracownicy na tabletach</h4>') < html.index('<h4>Terminy</h4>')


def test_skrypt_konfiguracji_bez_drukarki():
    js = _czytaj(SKRYPT_KONFIGURACJI)
    for slowo in ('label_printer_', 'package_label_', 'LABEL_PRINTER_', 'PACKAGE_LABEL_', 'wydrukProbny',
                  'wybierzDrukarke', 'drukarka_wybor', '/production/api/print-test'):
        assert slowo not in js, slowo


def test_ustawienia_druku_w_zakladce_drukarki():
    """Z dawnej karty zostało tylko pole stanowisk uprawnionych (strażnik druku, stan drukarki etykiet na tabletach);
    tryb TCP, przełącznik trybu agenta i token starego agenta zniknęły z UI (backend i klucze zostają)."""
    html = _czytaj(DRUKARKI)
    poczatek = html.index('id="drk-panel-ustawienia"')
    karta = html[poczatek:html.index('<!-- Okno: dodanie agenta', poczatek)]
    assert 'Ustawienia druku' in html and 'data-sub="ustawienia"' in html
    znacznik = re.search(r'<input[^>]*id="label_printer_allowed_stations"[^>]*>', karta, re.S)
    assert znacznik and 'data-klucz="LABEL_PRINTER_ALLOWED_STATIONS"' in znacznik.group(0)
    assert 'drk-ust' in znacznik.group(0)
    for pole, klucz in POLA_DAWNEJ_KARTY.items():
        if klucz == 'LABEL_PRINTER_ALLOWED_STATIONS':
            continue
        assert 'id="%s"' % pole not in html and klucz not in html, pole
    # przesunięcia tylko w formularzu dokumentu konfiguracji agenta
    for pole in POLA_PRZESUNIEC:
        assert pole not in html, pole
    for sciezka in ('przesuniecia.etykiety.lt', 'przesuniecia.etykiety.ls', 'przesuniecia.wysylka.dx',
                    'przesuniecia.wysylka.dy'):
        assert 'data-sciezka="%s"' % sciezka in html
    assert 'change-me-in-prod' not in html
    # bez śladów okresu przejściowego
    for slad in ('drk-panel-stary', 'drk-stan-stary', 'drk-obsluga', 'drk-modal-obsluga', 'data-agent=',
                 'Stary agent', 'stary agent', 'Dotyczy trybu bez agenta druku'):
        assert slad not in html, slad


def test_style_bez_starego_agenta():
    css = _czytaj(STYL_DRUKAREK)
    for slad in ('drk-obsluga', 'drk-stan--stary', 'drk-karta-stary'):
        assert slad not in css, slad
    assert '.drk-karta-ustawienia' in css
    assert 'config-drukarka-' not in _czytaj(STYL_KONFIGURACJI)


def test_skrypt_zakladki_drukarki():
    js = _czytaj(SKRYPT_DRUKAREK)
    # „Ustawienia druku” zapisują jak pasek Konfiguracji
    assert "const ADRES_USTAWIEN = '/production/api/update-configs'" in js
    assert "'X-Requested-With': 'XMLHttpRequest'" in js
    assert "$('drk-ustawienia-zapisz')" in js
    # odświeżanie co 15 s tylko przy widocznej zakładce
    assert 'const ODSWIEZANIE_MS = 15000' in js
    assert "getElementById('printers-tab-content')" in js and 'document.hidden' in js
    # token czyszczony przy zamknięciu okna; jedyne miejsce, gdzie trafia do strony, to pole okna
    assert "addEventListener('hidden.bs.modal'" in js
    assert re.search(r"hidden\.bs\.modal'[^}]*\$\('drk-token'\)\.value = ''", js, re.S)
    # bez przełącznika obsługi i karty starego agenta
    for slad in ('nowy_agent_offline', 'drukarka_poza_konfiguracja', 'PRZELACZANIE_S', 'CISZA_STAREGO_S', '/obsluga/',
                 'stary_agent', 'drk-stary', 'drk-obsluga', "'obsluga'", 'rysujStaregoAgenta'):
        assert slad not in js, slad
    assert 'BaseLinker' not in js


def test_zakladka_w_panelu_i_loaderze():
    panel = _czytaj(PANEL)
    urzadzenia = panel.index('id="devices-tab"')
    drukarki = panel.index('id="printers-tab"')
    konfiguracja = panel.index('id="config-tab"')
    assert urzadzenia < drukarki < konfiguracja
    # przycisk widoczny dla każdego: poza blokiem {% if %} admina (ten zamyka się przed przyciskiem)
    assert panel.rindex('{% endif %}', urzadzenia, drukarki) > urzadzenia
    assert 'fas fa-print me-2"></i>Drukarki' in panel
    assert "css/printers-tab.css') }}?v=" in panel
    assert "js/modules/printers-tab.js') }}?v=" in panel
    assert "js/modules/config-module.js') }}?v=20261022a\"" in panel
    loader = _czytaj(LOADER)
    assert "'printers-tab'" in loader
    assert "case 'printers-tab': await this.loadPrintersTab(); break;" in loader
    assert "fetch('/production/api/drukarki/tab-content'" in loader
