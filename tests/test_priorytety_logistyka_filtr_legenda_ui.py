# -*- coding: utf-8 -*-
"""
Logistyka, dashboard (decyzja Konrada 6.10, program „Priorytety produkcji”): filtr listy zamówień po jednej trasie
i legenda ikon jako przycisk z dymkiem. Tylko panel — JS, szablon, CSS; backend bez zmian.

Kontrakt danych, na którym stoi filtr (pole `trasa` wiersza listy i daty w `GET /routes`), sprawdzamy klientem
testowym (tests/logistyka_fixtures.py). Frontu nie da się tu uruchomić (obraz testowy jest bez node'a), więc
`logistics.js`, szablon i CSS sprawdzamy strukturalnie na źródle (konwencja tests/test_logistyka_*_ui.py).
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.production.logistics import sposoby as s
from tests.logistyka_fixtures import BASE, app, client, zamowienie  # noqa: F401

KORZEN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SZABLON = os.path.join(KORZEN, 'modules', 'production', 'logistics', 'templates', 'logistics', 'tab_content.html')
JS = os.path.join(KORZEN, 'modules', 'production', 'logistics', 'static', 'js', 'logistics.js')
CSS = os.path.join(KORZEN, 'modules', 'production', 'logistics', 'static', 'css', 'logistics.css')


def _zrodlo(sciezka):
    with open(sciezka, encoding='utf-8') as plik:
        return plik.read()


def _funkcja(js, naglowek):
    """Ciało funkcji w IIFE pliku logistyki (wcięcie 4 spacje) od nagłówka do zamykającego `}`."""
    assert naglowek in js, naglowek
    reszta = js[js.index(naglowek):]
    return reszta[:reszta.index('\n    }\n') + 6]


def _wersja(szablon, plik):
    znalezione = re.search(re.escape(plik) + r"'\) \}\}\?v=(\w+)\"", szablon)
    assert znalezione, plik
    return znalezione.group(1)


# ── Filtr po trasie: kontrakt danych (bez zmian backendu) ───────────────────────────────────────────────────────

def test_lista_niesie_trase_zamowienia_a_lista_tras_daty(app, client):
    """Filtr czyta `trasa` {id, nazwa, status} z wiersza listy, a etykietę opcji (nazwa + data) z GET /routes."""
    with app.app_context():
        na_trasie = zamowienie(sposob=s.TRANSPORT)
        bez_trasy = zamowienie(sposob=s.TRANSPORT)
        a, b = na_trasie.id, bez_trasy.id

    odp = client.post(BASE + '/routes', json={'name': 'Kraków', 'date_from': '2026-10-08', 'date_to': '2026-10-09'})
    rid = odp.get_json()['route']['id']
    assert client.post(BASE + '/routes/%d/stops' % rid, json={'order_ids': [a]}).status_code == 200

    wiersze = {w['id']: w for w in client.get(BASE + '/orders').get_json()['orders']}
    assert wiersze[a]['trasa'] == {'id': rid, 'nazwa': 'Kraków', 'status': 'robocza'}
    assert wiersze[b]['trasa'] is None

    trasy = {t['id']: t for t in client.get(BASE + '/routes').get_json()['routes']}
    assert trasy[rid]['nazwa'] == 'Kraków' and trasy[rid]['status'] == 'robocza'
    assert trasy[rid]['date_from'] == '2026-10-08' and trasy[rid]['date_to'] == '2026-10-09'


# ── Filtr po trasie: szablon i logika listy ─────────────────────────────────────────────────────────────────────

def test_szablon_ma_liste_wyboru_trasy_nad_lista():
    szablon = _zrodlo(SZABLON)
    sterowanie = szablon[szablon.index('<div class="lg-narzedzia">'):szablon.index('{# ─── MAPA ───')]
    assert 'data-lg="trasa"' in sterowanie
    pole = sterowanie[sterowanie.index('lg-trasa-filtr'):]
    pole = pole[:pole.index('</label>')]
    assert '<span>Trasa</span>' in pole
    assert 'aria-label="Filtr trasy"' in pole
    assert '<option value="">Wszystkie trasy</option>' in pole
    # Stoi przy pozostałych filtrach listy po stronie przeglądarki (etap, lokalizacja).
    assert sterowanie.index('data-lg="geo"') < sterowanie.index('data-lg="trasa"') < \
        sterowanie.index('data-lg-sposob="bez_trasy"')


def test_opcje_filtra_trasy():
    js = _zrodlo(JS)
    # Statusy tras w filtrze: robocza, zatwierdzona, załadowana, w trasie (jak STATUSY_TRASY_AKTYWNE w models.py).
    assert "const STATUSY_TRAS_FILTRA = ['robocza', 'zatwierdzona', 'zaladowana', 'w_trasie'];" in js
    assert "const BEZ_TRASY = 'brak';" in js
    trasa = _funkcja(js, '    function trasaWiersza(w) {')
    assert 'STATUSY_TRAS_FILTRA.includes(w.trasa.status)' in trasa
    render = _funkcja(js, '    function renderujFiltrTras() {')
    assert "el('trasa')" in render
    assert '<option value="">Wszystkie trasy</option>' in render
    assert "'<option value=\"' + BEZ_TRASY + '\"'" in render and "'Bez trasy (' + bez + ')'" in render
    # Etykieta: nazwa + data (zakres dat trasy), liczba zamówień z listy — jak przy etapie.
    etykieta = _funkcja(js, '    function etykietaTrasy(t) {')
    assert 'dataKrotka(t.date_from)' in etykieta and 'dataKrotka(t.date_to)' in etykieta
    assert 'esc(' in render and "' (' + (ile.get(id) || 0) + ')'" in render
    # Wybrana trasa zostaje na liście, nawet gdy zniknęła z odczytu (jak wybrany etap).
    assert 'stan.filtr.trasa' in render and 'dataset.nazwa' in render
    assert "select.classList.toggle('is-aktywny', !!stan.filtr.trasa);" in render


def test_trasy_filtra_z_istniejacego_api_bez_psucia_listy():
    js = _zrodlo(JS)
    odczyt = _funkcja(js, '    async function wczytajTrasyFiltra(signal) {')
    assert "zapytanie('/routes', { signal: signal })" in odczyt
    assert 'STATUSY_TRAS_FILTRA.includes(t.status)' in odczyt
    # Błąd odczytu tras nie psuje listy: zostaje poprzedni odczyt albo nazwy z wierszy.
    assert 'catch (e)' in odczyt and 'return null;' in odczyt
    wczytaj = _funkcja(js, '    async function wczytaj(tryb) {')
    assert 'Promise.all([' in wczytaj and 'wczytajTrasyFiltra(kontroler.signal)' in wczytaj
    assert 'if (trasy) stan.trasy = trasy;' in wczytaj
    # Bez zmian w backendzie: parametru trasy nie wysyłamy (filtr po stronie przeglądarki, jak etap).
    assert "params.set('trasa'" not in wczytaj
    renderuj = _funkcja(js, '    function renderujWszystko() {')
    assert renderuj.index('renderujEtapy();') < renderuj.index('renderujFiltrTras();') < renderuj.index('renderujTabele();')


def test_filtr_trasy_laczy_sie_z_innymi_i_ogranicza_mape():
    js = _zrodlo(JS)
    filtr = _funkcja(js, '    function poTrasie(wiersze) {')
    assert 'stan.filtr.trasa === BEZ_TRASY' in filtr and '!trasaWiersza(w)' in filtr
    assert 'Number(stan.filtr.trasa)' in filtr
    # Iloczyn z etapem i lokalizacją: widoczne wiersze idą przez trasę, etap, potem lokalizację.
    lista = _funkcja(js, '    function poEtapieITrasie() {')
    assert 'poTrasie(stan.wiersze)' in lista and 'stan.filtr.etap' in lista
    assert 'poEtapie(' not in js
    assert 'const wiersze = poEtapieITrasie();' in _funkcja(js, '    function widoczneWiersze() {')
    # Mapa pokazuje wiersze z tabeli (stan.naLiscie z widoczneWiersze) — filtr trasy zawęża też pinezki.
    assert 'stan.naLiscie = widoczne.map((w) => w.id);' in _funkcja(js, '    function renderujTabele() {')
    assert 'stan.naLiscie' in _funkcja(js, '    function przekazDoMapy() {')
    ustaw = _funkcja(js, '    function ustawFiltrTrasy(wartosc) {')
    for kawalek in ('stan.filtr.trasa = wartosc;', 'stan.dopasujMape = true;', 'mapaNaZamowienia();',
                    'renderujFiltrTras();', 'renderujGeo();', 'renderujTabele();'):
        assert kawalek in ustaw, kawalek
    zmiana = js[js.index("root.addEventListener('change'"):]
    zmiana = zmiana[:zmiana.index('\n    });\n')]
    assert "t === el('trasa')" in zmiana and 'ustawFiltrTrasy(t.value);' in zmiana
    assert "filtr: { sposob: '', etap: '', q: '', zamkniete: false, geo: '', woj: [], stan: '', trasa: '' }" in js


def test_filtr_trasy_w_licznikach_pustym_stanie_i_zdejmowaniu():
    js = _zrodlo(JS)
    assert 'stan.filtr.trasa' in js[js.index('const zawezonyWidok'):js.index('const bezGeoWWidoku')]
    assert 'stan.filtr.trasa' in _funkcja(js, '    function renderujIle() {')
    pusty = _funkcja(js, '    function pustyStan() {')
    galaz = pusty[pusty.index('} else if (f.trasa && stan.wiersze.length) {'):]
    galaz = galaz[:galaz.index('} else if', 10)]
    assert "'Na liście nie ma zamówień bez trasy'" in galaz
    assert "przyciskStanu('wszystkie-trasy', 'Pokaż wszystkie trasy')" in galaz
    # Trasa przed etapem: przy obu filtrach komunikat mówi o trasie, a nie twierdzi, że etap jest pusty.
    assert pusty.index('f.trasa && stan.wiersze.length') < pusty.index('f.etap && stan.wiersze.length')
    klik = js[js.index("root.addEventListener('click'"):]
    klik = klik[:klik.index('\n    });\n')]
    blok = klik[klik.index("case 'wszystkie-trasy':"):]
    assert "ustawFiltrTrasy('');" in blok[:blok.index('break;')]
    assert "stan.filtr.trasa = '';" in _funkcja(js, '    function zdejmijFiltry() {')


def test_filtr_trasy_bez_zapamietywania_i_z_polskimi_etykietami():
    js = _zrodlo(JS)
    for naglowek in ('    function renderujFiltrTras() {', '    function ustawFiltrTrasy(wartosc) {',
                     '    function poTrasie(wiersze) {', '    async function wczytajTrasyFiltra(signal) {',
                     '    function etykietaTrasy(t) {'):
        cialo = _funkcja(js, naglowek)
        assert 'localStorage' not in cialo, naglowek
        assert 'BaseLinker' not in cialo, naglowek


def test_filtr_trasy_styl_i_wersje():
    css = _zrodlo(CSS)
    assert '.logistics-tab .lg-trasa-filtr .form-select {' in css
    regula = css[css.index('.logistics-tab .lg-trasa-filtr .form-select {'):]
    assert 'max-width:' in regula[:regula.index('}')]
    szablon = _zrodlo(SZABLON)
    assert _wersja(szablon, 'js/logistics.js') > '20261005a'
    assert _wersja(szablon, 'css/logistics.css') > '20261005b'


# ── Legenda ikon: przycisk „Legenda” z dymkiem ──────────────────────────────────────────────────────────────────

# (znacznik ikony w szablonie, objaśnienie) — treść objaśnień bez zmian względem legendy ciągiem tekstu.
WIERSZE_LEGENDY = [
    ('fa-box-open lg-ikona--przepakowanie', 'wróciło do pakowania, czeka na ponowne spakowanie'),
    ('fa-tags lg-ikona--etykiety', 'etykiety wydrukowane przed zmianą sposobu'),
    ('fa-box lg-ikona--etykiety', 'etykiety paczek sprzed zmiany sposobu lub trasy'),
    ('<i class="fas fa-hourglass-half"></i>czeka na weryfikację', 'spakowane, paczki czekają na sprawdzenie'),
    ('fa-triangle-exclamation lg-ikona--problem', 'problem zgłoszony przy weryfikacji paczek'),
    ('<span class="lg-bez-paczek" aria-hidden="true">BEZ PACZEK</span>', 'spakowane, ale bez zadeklarowanych paczek'),
    ('fa-cloud-arrow-up lg-ikona--base', 'Base.: czeka na wysłanie'),
    ("filename='img/base-logo.png'", 'podpowiedź sposobu z metody w Base.'),
    ('fa-map-location-dot lg-ikona--adres', 'adres zmieniony po ręcznym ustawieniu punktu'),
]
SKROT_LEGENDY = ('Klik w wiersz rozwija pozycje, pinezka przy numerze pokazuje zamówienie na mapie, '
                 'Shift + klik zaznacza zakres, dwuklik w adres go poprawia')


def _legenda(szablon):
    poczatek = szablon.index('<div class="lg-legenda" data-lg="legenda">')
    return szablon[poczatek:szablon.index('{# ─── PASEK AKCJI HURTOWYCH', poczatek)]


def test_legenda_to_przycisk_z_dymkiem_pod_lista():
    szablon = _zrodlo(SZABLON)
    legenda = _legenda(szablon)
    # Pod tabelą zamówień, przed paskiem akcji hurtowych.
    assert szablon.index('data-lg="wiersze"') < szablon.index('data-lg="legenda"')
    przycisk = legenda[legenda.index('<button'):legenda.index('</button>')]
    for kawalek in ('type="button"', 'data-lg="legenda-przycisk"', 'aria-expanded="false"',
                    'aria-controls="lg-legenda-dymek"', 'fa-circle-info', '<span>Legenda</span>'):
        assert kawalek in przycisk, kawalek
    dymek = legenda[legenda.index('<div class="lg-legenda-dymek"'):]
    pierwsza = dymek[:dymek.index('\n')]
    assert 'id="lg-legenda-dymek"' in pierwsza and 'data-lg="legenda-dymek"' in pierwsza
    assert pierwsza.endswith(' hidden>')
    assert 'aria-label="Legenda ikon listy zamówień"' in pierwsza


def test_legenda_dwie_kolumny_ikona_i_objasnienie_bez_zmian_tresci():
    legenda = _legenda(_zrodlo(SZABLON))
    siatka = legenda[legenda.index('<div class="lg-legenda-siatka">'):]
    wiersze = re.findall(r'<div class="lg-legenda-wiersz"><span class="lg-legenda-ikona">(.*?)</span>'
                         r'<span class="lg-legenda-opis">([^<]*)</span></div>', siatka)
    assert len(wiersze) == len(WIERSZE_LEGENDY) == 9
    for (ikona, opis), (znacznik, tekst) in zip(wiersze, WIERSZE_LEGENDY):
        assert znacznik in ikona, (znacznik, ikona)
        assert opis == tekst
    # Wskazówki obsługi listy — osobny wiersz pod siatką, tekst bez zmian.
    assert '<p class="lg-legenda-skrot">' + SKROT_LEGENDY + '</p>' in legenda
    assert 'BaseLinker' not in legenda


def test_legenda_otwieranie_i_zamykanie():
    js = _zrodlo(JS)
    for nazwa in ("el('legenda')", "el('legenda-przycisk')", "el('legenda-dymek')"):
        assert nazwa in js, nazwa
    otworz = _funkcja(js, '    function otworzLegende(przypnij) {')
    assert 'legendaDymek.hidden = false;' in otworz and "setAttribute('aria-expanded', 'true')" in otworz
    zamknij = _funkcja(js, '    function zamknijLegende(oddajFokus) {')
    assert 'legendaDymek.hidden = true;' in zamknij and "setAttribute('aria-expanded', 'false')" in zamknij
    assert 'legendaPrzypieta = false;' in zamknij and 'legendaPrzycisk.focus()' in zamknij
    sekcja = js[js.index('// ── Legenda ikon'):]
    sekcja = sekcja[:sekcja.index('\n    // ── ', 10)]
    # Najechanie myszą otwiera, zjechanie zamyka (chyba że przypięta albo fokus z klawiatury).
    assert "legenda.addEventListener('pointerenter'" in sekcja and "legenda.addEventListener('pointerleave'" in sekcja
    assert sekcja.count("e.pointerType === 'mouse'") >= 2
    # Klik / dotyk (tablet biura): przypina; drugi klik zamyka. Mysz najechaniem już otworzyła.
    klik = sekcja[sekcja.index("legendaPrzycisk.addEventListener('click'"):]
    klik = klik[:klik.index('});')]
    assert 'otworzLegende(true)' in klik and 'zamknijLegende(false)' in klik
    # Fokus z klawiatury otwiera, wyjście fokusem poza legendę zamyka.
    assert "legendaPrzycisk.addEventListener('focus'" in sekcja and ':focus-visible' in sekcja
    assert "legenda.addEventListener('focusout'" in sekcja and '!legenda.contains(e.relatedTarget)' in sekcja
    klawisz = _funkcja(js, '    function naKlawiszLegendy(e) {')
    assert "e.key === 'Escape'" in klawisz and '!legendaDymek.hidden' in klawisz and 'zamknijLegende(' in klawisz
    poza = _funkcja(js, '    function naWskaznikLegendy(e) {')
    assert '!legenda.contains(e.target)' in poza and 'zamknijLegende(false)' in poza
    assert "document.addEventListener('keydown', naKlawiszLegendy)" in js
    assert "document.addEventListener('pointerdown', naWskaznikLegendy, true)" in js
    zniszcz = _funkcja(js, '    function zniszcz() {')
    assert "document.removeEventListener('keydown', naKlawiszLegendy)" in zniszcz
    assert "document.removeEventListener('pointerdown', naWskaznikLegendy, true)" in zniszcz
    assert 'localStorage' not in sekcja


def _regula(css, selektor):
    assert selektor + ' {' in css, selektor
    reszta = css[css.index(selektor + ' {'):]
    return reszta[:reszta.index('}')]


def test_legenda_styl_dymku():
    css = _zrodlo(CSS)
    dymek = _regula(css, '.logistics-tab .lg-legenda-dymek')
    assert 'position: absolute;' in dymek and 'bottom: calc(100% + 6px);' in dymek
    assert 'z-index: 1010;' in dymek and 'max-width: min(' in dymek and 'calc(100vw - 32px)' in dymek
    assert 'display: none;' in _regula(css, '.logistics-tab .lg-legenda-dymek[hidden]')
    # Mostek nad szczeliną między przyciskiem a dymkiem — zjazd myszą do dymku go nie zamyka.
    assert 'top: 100%;' in _regula(css, '.logistics-tab .lg-legenda-dymek::after')
    siatka = _regula(css, '.logistics-tab .lg-legenda-siatka')
    assert 'display: grid;' in siatka and 'grid-template-columns: max-content minmax(0, 1fr);' in siatka
    assert 'display: contents;' in _regula(css, '.logistics-tab .lg-legenda-wiersz')
    assert '.logistics-tab .lg-legenda-przycisk:focus-visible' in css
    assert '.logistics-tab .lg-legenda-przycisk[aria-expanded="true"]' in css
    # Stary układ ciągiem (flex z zawijaniem) zniknął.
    assert 'flex-wrap: wrap;' not in _regula(css, '.logistics-tab .lg-legenda')
    szablon = _zrodlo(SZABLON)
    assert _wersja(szablon, 'js/logistics.js') > '20261006a'
    assert _wersja(szablon, 'css/logistics.css') > '20261006a'
