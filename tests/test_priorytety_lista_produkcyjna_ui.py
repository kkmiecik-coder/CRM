# -*- coding: utf-8 -*-
"""
Lista produkcyjna (priorytety produkcji, krok K4a; spec 7.1): zakładka „Lista produktów” nazywa się „Lista
produkcyjna”, karty idą po randze zamówienia z `GET /production/api/priorytety/kolejka`, gwiazdki 0–5 ustawia się
z modalu priorytetu i hurtem, a drabinę z modalu „Drabina priorytetów”. Stara gwiazdka true/false, przeciąganie
wierszy i `POST /set-priority` znikają.

Frontu nie da się tu uruchomić (obraz testowy jest bez node'a), więc wspólny komponent `priorytety.js`,
`products-module.js` i szablony sprawdzamy strukturalnie na źródle (konwencja tests/test_produkty_js_hurt_pominiete.py
i tests/krawedzie_fixtures.py). Pola listy produktów (`order_id`, `order_priority_stars`) i usunięcie końcówki
sprawdzamy klientem testowym na SQLite.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from extensions import db
from modules.production.models import ProductionOrder, ProductionProduct
from tests.blokady_pomocnicze import Zapytania
from tests.krawedzie_fixtures import (  # noqa: F401
    BASE, JS_ARCHIWUM, JS_PRODUKTY, KORZEN, SZABLON_PRODUKTOW, app, client, produkt, zrodlo,
)

SZABLON_DASHBOARDU = os.path.join(KORZEN, 'modules', 'production', 'templates', 'panel', 'dashboard.html')


# ── Task 1: nazwa zakładki i pola gwiazdek w liście produktów ──────────────────────────────────────────────────

def test_zakladka_nazywa_sie_lista_produkcyjna():
    dashboard = zrodlo(SZABLON_DASHBOARDU)
    przycisk = dashboard[dashboard.index('id="products-tab"'):]
    przycisk = przycisk[:przycisk.index('</button>')]
    assert 'Lista produkcyjna' in przycisk
    for sciezka in (SZABLON_DASHBOARDU, SZABLON_PRODUKTOW, JS_ARCHIWUM):
        assert u'Lista produktów' not in zrodlo(sciezka), sciezka
    szablon = zrodlo(SZABLON_PRODUKTOW)
    naglowek = re.search(r'<div class="il-lista-naglowek">(.*?)</div>', szablon, re.S)
    assert naglowek is not None and 'Lista produkcyjna' in naglowek.group(1)


def _gwiazdki_zamowienia(app, product_id, gwiazdki):
    with app.app_context():
        order_id = db.session.get(ProductionProduct, product_id).order_id
        db.session.get(ProductionOrder, order_id).priority_stars = gwiazdki
        db.session.commit()
        return order_id


def test_lista_produkcyjna_ma_order_id_i_gwiazdki(app, client):
    product_id, _short = produkt(app, status='czeka_na_sklejanie')
    order_id = _gwiazdki_zamowienia(app, product_id, 3)

    odpowiedz = client.get(BASE + '/products-tab-content')
    assert odpowiedz.status_code == 200, odpowiedz.get_data(as_text=True)[:300]
    pozycja = next(p for p in odpowiedz.get_json()['initial_data']['products'] if p['id'] == product_id)
    assert pozycja['order_id'] == order_id
    assert pozycja['order_priority_stars'] == 3
    # Stare pola zostają dla innych czytelników (archiwum, K8).
    assert 'is_priority' in pozycja and 'priority_rank' in pozycja

    szczegoly = client.get(BASE + '/products/%d/details' % product_id)
    assert szczegoly.status_code == 200
    assert szczegoly.get_json()['product']['order_id'] == order_id
    assert szczegoly.get_json()['product']['order_priority_stars'] == 3


def _dodaj_zamowienia(app, ile, start):
    for i in range(ile):
        numer = '25/%05d' % (start + i)
        product_id, _short = produkt(app, status='czeka_na_sklejanie', numer=numer)
        with app.app_context():
            order_id = db.session.get(ProductionProduct, product_id).order_id
            druga = ProductionProduct(
                order_id=order_id, configuration_id=db.session.get(ProductionProduct, product_id).configuration_id,
                short_product_id=numer.replace('/', '') + '_2', product_sequence_in_order=2,
                original_product_name='Blat dębowy', current_status='czeka_na_sklejanie', quantity=1,
                volume_m3=0.1, total_value_net=100)
            db.session.add(druga)
            db.session.commit()


def _zapytania_listy(app, client):
    with app.app_context():
        with Zapytania() as z:
            odpowiedz = client.get(BASE + '/products-tab-content')
    assert odpowiedz.status_code == 200
    return len(z.lista), len(odpowiedz.get_json()['initial_data']['products'])


def test_lista_produkcyjna_bez_dodatkowych_zapytan(app, client):
    """Łączna liczba zapytań nie rośnie z liczbą zamówień: nowe pola biorą zamówienie z `joinedload`."""
    _dodaj_zamowienia(app, 1, start=100)
    jedno, pozycji_jedno = _zapytania_listy(app, client)
    _dodaj_zamowienia(app, 2, start=200)
    trzy, pozycji_trzy = _zapytania_listy(app, client)
    assert (pozycji_jedno, pozycji_trzy) == (2, 6)
    assert jedno == trzy, (jedno, trzy)


# ── Task 2: wspólny komponent priorytety.js i modal priorytetu ────────────────────────────────────────────────

JS_PRIORYTETY = os.path.join(KORZEN, 'modules', 'production', 'priorytety', 'static', 'js', 'priorytety.js')
CSS_PRIORYTETY = os.path.join(KORZEN, 'modules', 'production', 'priorytety', 'static', 'css', 'priorytety.css')
SZABLON_LOGISTYKI = os.path.join(KORZEN, 'modules', 'production', 'logistics', 'templates', 'logistics',
                                 'tab_content.html')
JS_LOGISTYKA = os.path.join(KORZEN, 'modules', 'production', 'logistics', 'static', 'js', 'logistics.js')
JS_TRASY = os.path.join(KORZEN, 'modules', 'production', 'logistics', 'static', 'js', 'logistics-routes.js')


def _funkcja(js, naglowek):
    """Ciało funkcji najwyższego poziomu w IIFE `priorytety.js` (wcięcie 4 spacje) od nagłówka do zamykającego `}`."""
    assert naglowek in js, u'brak kotwicy: {}'.format(naglowek)
    reszta = js[js.index(naglowek):]
    return reszta[:reszta.index('\n    }\n') + 6]


def _sekcja(js, poczatek, koniec):
    """Fragment pliku między dwoma komentarzami-separatorami sekcji."""
    assert poczatek in js and koniec in js, (poczatek, koniec)
    return js[js.index(poczatek):js.index(koniec)]


def test_priorytety_js_ladowany_w_dashboardzie():
    dashboard = zrodlo(SZABLON_DASHBOARDU)
    skrypt = "url_for('priorytety_panel.static', filename='js/priorytety.js') }}?v="
    styl = "url_for('priorytety_panel.static', filename='css/priorytety.css') }}?v="
    assert skrypt in dashboard and styl in dashboard
    assert dashboard.index(skrypt) < dashboard.index("js/modules/products-module.js')")
    # Zakładka Logistyki renderuje się w fiksturach bez blueprintu priorytetów — żadnego url_for do jego statyki.
    assert 'priorytety_panel' not in zrodlo(SZABLON_LOGISTYKI)


def test_statyka_priorytetow_serwowana():
    from flask import Flask
    from modules.production.priorytety import priorytety_panel_bp
    apka = Flask(__name__)
    apka.register_blueprint(priorytety_panel_bp, url_prefix='/production/api/priorytety')
    klient = apka.test_client()
    for plik in ('js/priorytety.js', 'css/priorytety.css'):
        odpowiedz = klient.get('/production/api/priorytety/static/priorytety/' + plik)
        assert odpowiedz.status_code == 200, plik
        odpowiedz.close()


def test_priorytety_js_koncowki_i_api():
    js = zrodlo(JS_PRIORYTETY)
    for tekst in ('window.Priorytety', "'/production/api/priorytety'", "'/zamowienia/gwiazdki'", "'/kolejka'",
                  "'/odlozenia'", "'/priorytet'", 'LIMIT_HURTU: 500', "'priorytety:zmiana'",
                  "credentials: 'same-origin'"):
        assert tekst in js, tekst
    for zakazane in ('BaseLinker', 'unpkg.com', 'cdn.'):
        assert zakazane not in js, zakazane
    # Idempotentny: drugi raz wczytany plik nie nadpisuje komponentu.
    assert 'if (window.Priorytety) return;' in js


def test_gwiazdki_jedna_droga_zapisu():
    js = zrodlo(JS_PRIORYTETY)
    assert js.count("'/zamowienia/gwiazdki'") == 1
    assert "'/zamowienia/gwiazdki'" in _funkcja(js, '    async function ustawGwiazdki(')
    for sciezka in (JS_PRODUKTY, JS_LOGISTYKA, JS_TRASY):
        tresc = zrodlo(sciezka)
        assert '/priorytety/' not in tresc and '/zamowienia/gwiazdki' not in tresc, sciezka


def test_modal_priorytetu_sekcje():
    modal = _sekcja(zrodlo(JS_PRIORYTETY), '// ── Modal priorytetu', '// ── Drabina priorytetów')
    assert 'showModal' in modal and 'async function otworzModalPriorytetu(' in modal
    for naglowek in ('Gwiazdki', 'Szczebel', 'Termin', u'Gdzie leży', u'Odłożenia', 'Historia'):
        assert "sekcja('" + naglowek + "'" in modal, naglowek
    assert re.search(r"'szczebel ' \+ [^;]*' z '", modal)
    assert 'aktywne === false' in modal and u'poza kolejką produkcji' in modal
    assert 'AKCJE_HISTORII' in modal and "gwiazdki: " in zrodlo(JS_PRIORYTETY)
    assert 'Bez gwiazdek' in modal
    assert u'Nie ma takiego zamówienia.' in modal
    # Jeden zapis naraz: kolejne kliknięcia w trakcie zapisu są ignorowane.
    klik = _funkcja(modal, '    async function zapiszGwiazdkiModalu(')
    assert klik.index('if (zapisTrwa) return;') < klik.index('zapisTrwa = true;')
    assert 'finally' in klik and 'zapisTrwa = false;' in klik[klik.index('finally'):]


def test_przeliczenie_nieudane_ostrzega():
    js = zrodlo(JS_PRIORYTETY)
    zapis = _funkcja(js, '    async function ustawGwiazdki(')
    galaz = zapis[zapis.index("przeliczenie === 'nieudane'"):]
    assert u'przeliczy się' in galaz and "'warning'" in galaz
    powiadom = _funkcja(js, '    function powiadom(')
    assert 'toastSystem' in powiadom and '.show(esc(' in powiadom


def test_priorytety_js_dane_z_api_tylko_przez_esc():
    """
    Każde odwołanie do pola z API niosącego tekst (`.klient`, `.nazwa`, `.etykieta`, `.notatka`, `.pracownik`,
    `.message`, `.numer`, `.kto`, `.short_id`) w linii, która składa HTML (zawiera `'<`, `"<`, `innerHTML` albo
    `insertAdjacentHTML`), stoi w łańcuchu argumentu `esc(` — np. `esc(d.zamowienie.klient)`. Linie bez HTML
    (`textContent =`, składanie zwykłego tekstu do `title` przez esc w innym miejscu) nie są sprawdzane.
    """
    js = zrodlo(JS_PRIORYTETY)
    pole = re.compile(r'\.(klient|nazwa|etykieta|notatka|pracownik|message|numer|kto|short_id)\b')
    for numer, linia in enumerate(js.splitlines(), start=1):
        if not ("'<" in linia or '"<' in linia or 'innerHTML' in linia or 'insertAdjacentHTML' in linia):
            continue
        for trafienie in pole.finditer(linia):
            przed = linia[:trafienie.start()]
            lancuch = re.search(r'[\w\.\[\]\?]*$', przed).group(0)
            poczatek = przed[:len(przed) - len(lancuch)]
            assert poczatek.endswith('esc('), u'linia {}: {}'.format(numer, linia.strip())
    funkcja_esc = _funkcja(js, '    function esc(')
    assert "/[&<>\"']/g" in funkcja_esc


# ── Task 3: modal „Drabina priorytetów” ───────────────────────────────────────────────────────────────────────

def _drabina():
    return _sekcja(zrodlo(JS_PRIORYTETY), '// ── Drabina priorytetów', '// ── Eksport')


def test_przycisk_drabiny_w_naglowku_zakladki():
    szablon = zrodlo(SZABLON_PRODUKTOW)
    naglowek = szablon[szablon.index('<div class="il-lista-naglowek">'):]
    naglowek = naglowek[:naglowek.index('</div>')]
    assert 'data-priorytety="drabina"' in naglowek and u'Drabina priorytetów' in naglowek
    assert 'otworzDrabine: otworzDrabine' in zrodlo(JS_PRIORYTETY)


def test_drabina_strzalki_tylko_dla_ruchomych():
    wiersz = _funkcja(_drabina(), '    function wierszDrabiny(')
    ruchomy = wiersz[wiersz.index('if (s.ruchomy) {'):wiersz.index('} else {')]
    staly = wiersz[wiersz.index('} else {'):]
    assert 'data-pr-drabina="gora"' in ruchomy and 'data-pr-drabina="dol"' in ruchomy
    assert "i === 0 ? ' disabled' : ''" in ruchomy and "i === n - 1 ? ' disabled' : ''" in ruchomy
    assert ruchomy.count('aria-label="\' + esc(') == 2
    assert 'data-pr-drabina' not in staly
    assert u'title="Szczebel gwiazdek jest stały"' in staly and 'fa-lock' in staly and u'stały' in staly


def test_drabina_wysyla_oczekiwane_i_obsluguje_409():
    js = zrodlo(JS_PRIORYTETY)
    # Jedna droga zapisu drabiny (DoD p. 5).
    assert js.count("'/drabina/kolejnosc'") == 1
    zapis = _funkcja(_drabina(), '    async function przesunSzczebel(')
    assert "'/drabina/kolejnosc'" in zapis and "metoda: 'PUT'" in zapis
    for klucz in ('szczebel_id:', 'pozycja:', 'oczekiwane: stanDrabiny.szczeble.map('):
        assert klucz in zapis, klucz
    galaz = zapis[zapis.index("e.kod === 'drabina_zmieniona'"):]
    assert 'await wczytajDrabine();' in galaz
    # Po odczycie od nowa fokus wraca na strzałkę tego samego szczebla (oględziny K4a: spadał na body).
    assert galaz.index('await wczytajDrabine();') < galaz.index('przywrocFokus(id, kierunek);') < galaz.index('} else {')
    assert 'komunikatDrabiny(KOMUNIKAT_DRABINA_ZMIENIONA)' in galaz
    assert u"KOMUNIKAT_DRABINA_ZMIENIONA = 'Drabina zmieniła się w międzyczasie. Sprawdź i spróbuj jeszcze raz.'" \
        in _drabina()
    assert "odp.przeliczenie === 'nieudane'" in zapis and "'warning'" in zapis
    assert "emituj('drabina'" in zapis
    assert "zapytanie('/drabina')" in _funkcja(_drabina(), '    async function wczytajDrabine(')


def test_jeden_zapis_naraz():
    zapis = _funkcja(_drabina(), '    async function przesunSzczebel(')
    cialo = zapis[zapis.index('{') + 1:].lstrip()
    assert cialo.startswith('if (zapisTrwa) return;')
    assert zapis.index('zapisTrwa = true;') < zapis.index('finally')
    assert 'zapisTrwa = false;' in zapis[zapis.index('finally'):]
    # Strzałki w trakcie zapisu: aria-disabled (fokus zostaje), klik ignorowany.
    obsluga = _funkcja(_drabina(), '    function obsluzKlikDrabiny(')
    assert "getAttribute('aria-disabled') === 'true'" in obsluga


def test_drabina_liczniki_ostrzezenia_i_trasy():
    drabina = _drabina()
    wiersz = _funkcja(drabina, '    function wierszDrabiny(')
    assert "' w produkcji'" in wiersz and 'w_produkcji === 0' in wiersz and 'pr-szczebel--pusty' in wiersz
    assert 'date_from' in wiersz and 'date_to' in wiersz and 'trasa.status' in wiersz
    render = _funkcja(drabina, '    function renderujDrabine(')
    assert 'ostrzezenia' in render and 'role="status"' in render and 'esc(o.message)' in render
    assert 'uzupelniono > 0' in render
    assert u'Zamówienie z trasy bierze szczebel trasy.' in drabina


# ── Task 3a: „Wyślij na stanowisko” i „Zdejmij ze stołu” w modalu priorytetu (karta K4a, spec 5.7) ────────────

def _modal():
    return _sekcja(zrodlo(JS_PRIORYTETY), '// ── Modal priorytetu', '// ── Drabina priorytetów')


def test_modal_wyslij_przy_kazdym_stanowisku():
    gdzie = _funkcja(_modal(), '    function htmlGdzieLezy(')
    assert 'data-pr-akcja="wyslij"' in gdzie and 'data-stanowisko="' in gdzie
    assert u'Wyślij na stanowisko' in gdzie
    assert 'STANOWISKA_BEZ_STOLU.includes(s.stanowisko)' in gdzie and u'bez stołu' in gdzie
    assert "STANOWISKA_BEZ_STOLU = ['painting']" in zrodlo(JS_PRIORYTETY)


def test_wyslij_i_zdejmij_jedna_droga():
    js = zrodlo(JS_PRIORYTETY)
    assert js.count("'/wyslij'") == 1 and js.count("'/zdejmij'") == 1
    wyslij = _funkcja(js, '    async function wyslijNaStanowisko(')
    assert "'/wyslij'" in wyslij and "metoda: 'POST'" in wyslij and 'order_id:' in wyslij
    zdejmij = _funkcja(js, '    async function zdejmijZeStolu(')
    assert "'/zdejmij'" in zdejmij and "metoda: 'POST'" in zdejmij and 'unit_key:' in zdejmij
    assert "emituj('stol'" in wyslij and "emituj('stol'" in zdejmij
    for nazwa in ('wyslijNaStanowisko: wyslijNaStanowisko', 'zdejmijZeStolu: zdejmijZeStolu',
                  'komunikatStolu: komunikatStolu'):
        assert nazwa in js, nazwa
    for sciezka in (JS_PRODUKTY, JS_LOGISTYKA, JS_TRASY):
        assert '/stoly/' not in zrodlo(sciezka), sciezka


def test_zdejmij_z_kluczem_z_stolow():
    modal = _modal()
    wczytaj = _funkcja(modal, '    async function wczytajStoly(')
    assert "zapytanie('/stoly')" in wczytaj and 'order_id === ' in wczytaj
    warunek = _funkcja(modal, '    function trzebaStolow(')
    assert '(s.na_stole || []).length' in warunek and '(s.odlozone || []).length' in warunek
    kafel = _funkcja(modal, '    function htmlKaflaStolu(')
    assert 'data-pr-akcja="zdejmij"' in kafel and 'data-unit-key="\' + esc(k.unit_key)' in kafel
    assert 'data-stanowisko="\' + esc(kod)' in kafel
    # Kafle na stole i odłożone mają ten sam przycisk.
    assert 'htmlKaflaStolu(' in _funkcja(modal, '    function htmlGdzieLezy(')
    assert 'htmlKaflaStolu(' in _funkcja(modal, '    function htmlOdlozen(')


def test_komunikaty_wszystkich_kodow_stolu():
    js = zrodlo(JS_PRIORYTETY)
    slownik = js[js.index('const KOMUNIKATY_STOLU = {'):]
    slownik = slownik[:slownik.index('\n    };\n')]
    for kod in ('dane_niepoprawne', 'stanowisko_nieznane', 'zamowienie_nieznane', 'brak_na_stanowisku',
                'stanowisko_bez_stolu', 'brak_kafla', 'blad_serwera'):
        assert '    ' + kod + ':' in slownik, kod
    # „Wyślij” na Pakowanie nie odmawia już bez sposobu dostawy (spec 5.1 po logistyce 4.6) — kod zniknął z serwera.
    assert 'delivery_method_not_set' not in slownik
    akcja = _funkcja(_modal(), '    async function akcjaStolu(')
    assert 'komunikatModalu(komunikatStolu(' in akcja
    # Komunikat trafia do modalu przez textContent (komunikatModalu), nie przez innerHTML.
    assert 'el.textContent = tresc' in _funkcja(_modal(), '    function komunikatModalu(')


def test_zdejmij_opis_powrotu():
    js = zrodlo(JS_PRIORYTETY)
    tekst = u'Kafel wróci przy następnym dopełnieniu stołu'
    kafel = _funkcja(js, '    function htmlKaflaStolu(')
    assert "k.dorobka || k.zrodlo === 'dorobka'" in kafel and 'WROCI_PRZY_DOPELNIENIU' in kafel
    assert u"WROCI_PRZY_DOPELNIENIU = '" + tekst in js
    zdejmij = _funkcja(js, '    async function zdejmijZeStolu(')
    assert "'/kolejka?stanowisko=' + encodeURIComponent(kod) + '&limit=1'" in zdejmij
    assert 'wroci' in zdejmij
    akcja = _funkcja(_modal(), '    async function akcjaStolu(')
    assert 'WROCI_PRZY_DOPELNIENIU' in akcja


def test_historia_akcje_stolu():
    js = zrodlo(JS_PRIORYTETY)
    akcje = js[js.index('const AKCJE_HISTORII = {'):]
    akcje = akcje[:akcje.index('\n    };\n')]
    for akcja in ('gwiazdki', 'wyslanie', 'zdjecie', 'odlozenie', 'odlozenie_zamkniete', 'start_stolow'):
        assert '    ' + akcja + ": '" in akcje, akcja
    historia = _funkcja(_modal(), '    function htmlHistorii(')
    assert "sekcja('Historia'" in _modal()
    # Pełne imię i nazwisko pracownika i użytkownika — bez skracania (Konrad 5.10).
    for pole in ('h.kto', 'o.pracownik', 'k.pracownik'):
        assert pole + '.split(' not in js
    assert 'esc(h.kto' in historia


def test_akcje_stolu_jeden_zapis_naraz():
    akcja = _funkcja(_modal(), '    async function akcjaStolu(')
    cialo = akcja[akcja.index('{') + 1:].lstrip()
    assert cialo.startswith('if (zapisTrwa) return;')
    assert akcja.index('zapisTrwa = true;') < akcja.index('finally')
    assert 'zapisTrwa = false;' in akcja[akcja.index('finally'):]
    sukces = akcja[:akcja.index('catch')]
    assert 'await wczytajModal(' in sukces
    obsluga = _funkcja(_modal(), '    function obsluzAkcjeModalu(')
    assert "akcja === 'wyslij' || akcja === 'zdejmij'" in obsluga and 'akcjaStolu(przycisk)' in obsluga


# ── Task 4: Lista produkcyjna — karty po randze, przycisk gwiazdek, plakietki, hurt; bez martwego kodu ──────────

CSS_PRODUKTOW = os.path.join(KORZEN, 'modules', 'production', 'static', 'css', 'products-tab.css')
JS_DRAG = os.path.join(KORZEN, 'modules', 'production', 'static', 'js', 'modules', 'products-dragdrop.js')


def _metoda(naglowek):
    """Ciało metody klasy ProductsModule (wcięcie 4 spacje) od nagłówka do zamykającego `}`."""
    js = zrodlo(JS_PRODUKTY)
    assert naglowek in js, u'brak kotwicy: {}'.format(naglowek)
    reszta = js[js.index(naglowek):]
    return reszta[:reszta.index('\n    }\n') + 6]


def test_brak_przeciagania_na_liscie():
    assert not os.path.exists(JS_DRAG)
    assert 'products-dragdrop' not in zrodlo(SZABLON_DASHBOARDU)
    js = zrodlo(JS_PRODUKTY)
    for tekst in ('ProductsDragDrop', 'dragDrop', 'il-drag-handle', 'draggable', 'dragstart'):
        assert tekst not in js, tekst
    assert 'il-drag-handle' not in zrodlo(SZABLON_PRODUKTOW)


def test_brak_starej_gwiazdki_i_progow_rangi():
    js = zrodlo(JS_PRODUKTY)
    for tekst in ('showEditPriorityModal', 'handleStarClick', 'getPriorityClass', 'updatePriorityColor',
                  'toggleProductPriority', 'toggleOrderPriority', '_sendPriorityUpdate', 'refreshStarUI',
                  'set-priority', 'is_priority', 'priority-critical', "'partial'", 'bulk-set-priority'):
        assert tekst not in js, tekst
    # `priority_rank` zostaje wyłącznie jako `sort_by` zapytania listy: kolejność pozycji WEWNĄTRZ karty
    # (ranga zamówienia × 100 + sekwencja, spec 9.5). Kolejność kart liczy się z /kolejka.
    bez_sortu = js.replace("sort_by: 'priority_rank'", '')
    assert 'priority_rank' not in bez_sortu
    szablon = zrodlo(SZABLON_PRODUKTOW)
    for tekst in ('il-product-star', 'il-star-btn', 'bulk-priority-form', 'data-action="set-priority"',
                  'priority-indicator'):
        assert tekst not in szablon, tekst
    css = zrodlo(CSS_PRODUKTOW)
    assert '.il-star-btn' not in css and '.il-drag-handle' not in css


def test_sortowanie_kart_po_randze_z_kolejki():
    sortuj = _metoda('    sortOrders() {')
    domyslna = sortuj[sortuj.index('if (!col) {'):sortuj.index('this.state.filteredOrders.sort((a, b) => {\n            let valA')]
    assert 'this.state.priorytetyBlad' in domyslna and 'this.state.priorytety.get(' in domyslna
    assert '.ranga' in domyslna and 'Infinity' in domyslna and 'deadline' in domyslna
    blad = domyslna[domyslna.index('if (this.state.priorytetyBlad) {'):domyslna.index('} else {')]
    assert 'deadline' in blad and 'ranga' not in blad


def test_blad_priorytetow_nie_psuje_listy():
    wczytaj = _metoda('    async wczytajPriorytety() {')
    assert 'try {' in wczytaj and 'catch (e)' in wczytaj
    galaz = wczytaj[wczytaj.index('catch (e)'):]
    assert 'this.state.priorytetyBlad = true;' in galaz and 'throw' not in wczytaj
    assert 'window.Priorytety' in wczytaj
    szablon = zrodlo(SZABLON_PRODUKTOW)
    ostrzezenie = re.search(r'<div id="il-priorytety-ostrzezenie"[^>]*>(.*?)</div>', szablon, re.S)
    assert ostrzezenie is not None and 'hidden' in ostrzezenie.group(0)
    assert u'Kolejność wg terminu: nie udało się wczytać priorytetów' in ostrzezenie.group(1)
    for naglowek in ('    async showLoadingAndLoadProducts() {', '    async refresh() {'):
        metoda = _metoda(naglowek)
        assert metoda.index('await this.loadProductsData();') < metoda.index('await this.wczytajPriorytety();')


def test_karta_ma_range_przycisk_gwiazdek_i_plakietki():
    szablon = zrodlo(SZABLON_PRODUKTOW)
    karta = szablon[szablon.index('<template id="il-order-template">'):]
    naglowek = karta[karta.index('<div class="il-order-header">'):karta.index('<div class="il-order-info">')]
    dzieci = re.findall(r'^\s*<(span|input|button)[^>]*class="([^"]+)"', naglowek, re.M)
    assert [d[1].split()[0] for d in dzieci[:4]] == ['il-order-ranga', 'il-order-checkbox', 'il-priorytet-btn',
                                                    'il-order-expand']
    assert 'aria-haspopup="dialog"' in naglowek
    kolumny = szablon[szablon.index('<div class="il-orders-header">'):]
    kolumny = kolumny[:kolumny.index('\n  </div>')]
    spany = re.findall(r'<span[^>]*>(.*?)</span>', kolumny, re.S)
    assert len(spany) == 11 and spany[0] == '#' and spany[2] == u'★'
    naglowek_js = _metoda('    populateOrderHeader(header, order) {')
    assert 'Priorytety.gwiazdkiHtml(' in naglowek_js and 'this.plakietkiPriorytetuHtml(order)' in naglowek_js
    assert 'il-order-ranga' in naglowek_js
    zdarzenia = _metoda('    attachOrderEventListeners(card, order) {')
    assert 'Priorytety.otworzModalPriorytetu(order.orderId)' in zdarzenia
    assert "e.target.closest('.il-priorytet-btn')" in zdarzenia and "e.target.closest('.il-prio-tag')" in zdarzenia


def test_plakietki_karty_przez_esc():
    plakietki = _metoda('    plakietkiPriorytetuHtml(order) {')
    for klasa in ('il-prio-tag--trasa', 'il-prio-tag--odlozone', 'il-prio-tag--${'):
        assert klasa in plakietki, klasa
    css = zrodlo(CSS_PRODUKTOW)
    for klasa in ('il-prio-tag--trasa', 'il-prio-tag--po_terminie', 'il-prio-tag--blisko_terminu',
                  'il-prio-tag--rozpoczete', 'il-prio-tag--odlozone'):
        assert '.' + klasa in css, klasa
    assert 'this.escapeHtml(t.nazwa)' in plakietki
    assert 'this.escapeHtml(P.etykietaTagu(' in plakietki and 'this.escapeHtml(P.etykietaOdlozenia(' in plakietki
    for metoda in (plakietki, _metoda('    populateOrderHeader(header, order) {')):
        for atrybut in re.finditer(r'(title|aria-label)="', metoda):
            dalej = metoda[atrybut.end():atrybut.end() + 25]
            assert dalej.startswith('${this.escapeAttr('), metoda[atrybut.start():atrybut.end() + 40]


def test_klawisze_listy_pomijaja_okna_priorytetow():
    klawisze = _metoda('    handleKeydown(e) {')
    pierwsza = klawisze[klawisze.index('{') + 1:].strip().splitlines()[0]
    assert pierwsza == "if (document.querySelector('dialog[open], .pr-wybierak')) return;"


def test_hurt_gwiazdek_unikalne_zamowienia_i_limit():
    szablon = zrodlo(SZABLON_PRODUKTOW)
    pasek = szablon[szablon.index('id="il-bulk-bar"'):]
    pasek = pasek[:pasek.index('</div>')]
    assert 'data-action="stars"' in pasek and 'Ustaw gwiazdki' in pasek
    assert pasek.index('data-action="stars"') < pasek.index('data-action="export"')
    assert "case 'stars':" in _metoda('    handleBulkAction(actionType) {')
    assert "case 'stars':" in _metoda('    toggleBulkActionsVisibility() {')
    hurt = _metoda('    async showBulkStarsPicker(selectedIds) {')
    assert 'new Set(' in hurt and 'order_id' in hurt
    assert hurt.index('P.LIMIT_HURTU') < hurt.index('P.ustawGwiazdki(')
    assert hurt.count('ustawGwiazdki(') == 1 and 'fetch(' not in hurt
    assert u'Gwiazdki dotyczą całych zamówień' in hurt
    # Po udanym zapisie selekcja jest czyszczona (poprawka zaznaczeń 6.10) — test niżej.


def test_nasluch_zmiany_priorytetow():
    js = zrodlo(JS_PRODUKTY)
    ustaw = _metoda('    setupEventListeners() {')
    assert re.search(r"this\._odpinijPriorytety = \w+\.on\('priorytety:zmiana'", ustaw)
    assert 'this._odpinijPriorytety()' in _metoda('    async unload() {')
    assert "off('priorytety:zmiana'" not in js
    handler = _metoda('    async poZmianiePriorytetow(zmiana) {')
    assert handler.index('await this.wczytajPriorytety();') < handler.index('this.applyAllFilters();')
    # Przycisk „Drabina priorytetów” w nagłówku zakładki.
    assert '[data-priorytety="drabina"]' in ustaw and 'Priorytety.otworzDrabine()' in ustaw


def test_podbite_wersje_listy():
    dashboard = zrodlo(SZABLON_DASHBOARDU)
    js = re.search(r"js/modules/products-module\.js'\) \}\}\?v=(\d+[a-z]?)\"", dashboard)
    css = re.search(r"css/products-tab\.css'\) \}\}\?v=(\d+[a-z]?)\"", dashboard)
    assert js and js.group(1) > '20261002a', js and js.group(1)
    assert css and css.group(1) > '20260805', css and css.group(1)
    for plik in ('js/priorytety.js', 'css/priorytety.css'):
        wpis = re.search(re.escape(plik) + r"'\) \}\}\?v=(\d+[a-z]?)\"", dashboard)
        assert wpis and wpis.group(1) > '20261005a', plik


# ── Task 5: usunięcie POST /production/api/set-priority ───────────────────────────────────────────────────────

def test_set_priority_usuniete(app, client):
    reguly = {r.rule for r in app.url_map.iter_rules()}
    assert '/production/api/set-priority' not in reguly
    # Żadna inna reguła nie łapie tej ścieżki: 404 (nie 405).
    assert client.post(BASE + '/set-priority', json={'mode': 'order', 'is_priority': True}).status_code == 404
    from tests.krawedzie_fixtures import PY_PRODUCTS_API
    assert 'set_product_priority' not in zrodlo(PY_PRODUCTS_API)


def test_fokus_po_zamknieciu_modalu_wraca_na_karte():
    """Oględziny K4a: po „Zdejmij”/gwiazdkach lista przerysowuje karty, więc przycisk, który otworzył modal, znika —
    fokus wraca wtedy na przycisk okna tej samej karty (`[data-order-id]`), a nie na body."""
    przywroc = _funkcja(zrodlo(JS_PRIORYTETY), '    function przywrocFokusModalu() {')
    assert 'document.contains(opener)' in przywroc
    assert '\'[data-order-id="\' + ' in przywroc and '[aria-haspopup="dialog"]' in przywroc


def test_esc_zamyka_okna_bez_polegania_na_close():
    """Zdarzenie `close` <dialog> przychodzi z następną klatką animacji — w karcie w tle albo po przełączeniu okna
    nie przychodzi wcale. Esc (`cancel`) zamyka więc okno sam i od razu oddaje fokus (oba modale)."""
    js = zrodlo(JS_PRIORYTETY)
    priorytet = _funkcja(js, '    function dialogPriorytetu() {')
    assert "addEventListener('cancel'" in priorytet and 'zamknijModalPriorytetu()' in priorytet
    drabina = _funkcja(js, '    function dialogDrabiny() {')
    assert "addEventListener('cancel'" in drabina and 'zamknijDrabine()' in drabina
    # Fokus oddawany raz, choćby `close` przyszło później.
    przywroc = _funkcja(js, '    function przywrocFokusModalu() {')
    assert 'if (!stanModalu.doPrzywrocenia) return;' in przywroc


# ── Przegląd końcowy K4a: poprawki (I1, M1, M4) ───────────────────────────────────────────────────────────────

def test_wybierak_zamyka_sie_przy_resize_i_przewijaniu_bez_wyjatku():
    """I1: `resize` ma własny handler (e.target to window — `dymek.contains(window)` rzucał TypeError), a przewinięcie
    (capture na document — lista Logistyki ma własny suwak) zamyka dymek, żeby nie stał obok innego wiersza."""
    wybierak = _funkcja(zrodlo(JS_PRIORYTETY), '    function wybierzGwiazdki(')
    assert "window.addEventListener('resize', klikObok)" not in wybierak
    assert "window.addEventListener('resize', zamknijPrzyZmianie)" in wybierak
    assert "document.addEventListener('scroll', zamknijPrzyZmianie, true)" in wybierak
    assert "document.removeEventListener('scroll', zamknijPrzyZmianie, true)" in wybierak
    assert "window.removeEventListener('resize', zamknijPrzyZmianie)" in wybierak
    assert 'const zamknijPrzyZmianie = () => zamknijWybierak(null);' in wybierak


def test_spoznione_odczyty_kolejki_odrzucane():
    """M1: kilka zdarzeń pod rząd (strzałki drabiny) daje kilka odczytów /kolejka — wynik starszego, który wrócił
    później, nie nadpisuje nowszego."""
    wczytaj = _metoda('    async wczytajPriorytety() {')
    assert 'const numer = ++this._numerPriorytetow;' in wczytaj
    assert wczytaj.count('if (numer !== this._numerPriorytetow) return;') >= 2


def test_opis_powrotu_z_pola_stolow():
    """M4: `GET /stoly` liczy `wroci_przy_dopelnieniu` (doróbka albo kafel, który wejdzie przy dopełnieniu) — modal
    pokazuje opis przed kliknięciem tak samo jak zakładka Stanowiska."""
    kafel = _funkcja(zrodlo(JS_PRIORYTETY), '    function htmlKaflaStolu(')
    assert "k.wroci_przy_dopelnieniu || k.dorobka || k.zrodlo === 'dorobka'" in kafel


# ── K4-poprawka-1: hurt „Ustaw gwiazdki” z potwierdzeniem ─────────────────────────────────────────────────────

def test_hurt_gwiazdek_potwierdzenie_przy_zdjeciu_albo_ponad_progu():
    """Decyzja Konrada 5.10 (pytanie 3 raportu K4a): wybierak startuje na „Bez gwiazdek”, więc mimowolny Enter
    zdjąłby gwiazdki wszystkim zaznaczonym. Okno potwierdzenia przy zdjęciu gwiazdek albo hurcie ponad 10 zamówień,
    z liczbą zamówień i docelową liczbą gwiazdek; odmowa = brak zapisu."""
    js = zrodlo(JS_PRODUKTY)
    assert re.search(r'^const PROG_POTWIERDZENIA_HURTU = 10;$', js, re.M)
    hurt = _metoda('    async showBulkStarsPicker(selectedIds) {')
    warunek = 'if (n === 0 || ids.size > PROG_POTWIERDZENIA_HURTU) {'
    assert warunek in hurt
    assert hurt.index('P.wybierzGwiazdki(') < hurt.index(warunek) < hurt.index('P.potwierdz(') \
        < hurt.index('P.ustawGwiazdki(')
    potwierdzenie = hurt[hurt.index(warunek):hurt.index('P.ustawGwiazdki(')]
    assert 'if (!potwierdzone) return;' in potwierdzenie
    # Liczba zamówień i docelowa liczba gwiazdek w treści okna.
    assert '${ids.size}' in potwierdzenie and 'P.opisGwiazdek(n)' in potwierdzenie
    assert u'Zdjąć gwiazdki' in potwierdzenie
    assert hurt.count('ustawGwiazdki(') == 1 and 'confirm(' not in hurt


def test_okno_potwierdzenia_fokus_na_anuluj():
    """Enter wciśnięty jeszcze w wybieraku (albo przytrzymany) nie zatwierdza: okno otwiera się z fokusem na
    „Anuluj”, przycisk zatwierdzający nie ma autofocusu. Esc (`cancel`) i „Anuluj” = odmowa, fokus wraca od razu
    (bez czekania na `close`). Treść tylko przez textContent."""
    js = zrodlo(JS_PRIORYTETY)
    okno = _funkcja(js, '    function potwierdz(opcje) {')
    assert "createElement('dialog')" in okno and 'showModal()' in okno
    assert 'data-pr-potwierdz="nie"' in okno and 'data-pr-potwierdz="tak"' in okno
    assert okno.index('data-pr-potwierdz="nie"') < okno.index('data-pr-potwierdz="tak"')
    assert 'autofocus' not in okno
    assert okno.index('showModal()') < okno.index("""querySelector('[data-pr-potwierdz="nie"]').focus()""")
    assert "addEventListener('cancel'" in okno and 'e.preventDefault()' in okno and 'zakoncz(false)' in okno
    assert "zakoncz(p.dataset.prPotwierdz === 'tak')" in okno
    assert 'opener.focus()' in okno and 'd.remove()' in okno
    for pole in ('o.tytul', 'o.tresc', 'o.zatwierdz'):
        assert re.search(r'\.textContent = ' + re.escape(pole), okno), pole
    assert '${' not in okno
    assert 'potwierdz: potwierdz,' in js
    # Klawisze listy dalej pomijają otwarte okna (okno potwierdzenia też jest <dialog>).
    klawisze = _metoda('    handleKeydown(e) {')
    assert "dialog[open]" in klawisze
    assert '.pr-modal--potwierdzenie' in zrodlo(CSS_PRIORYTETY)


def test_podbite_wersje_po_potwierdzeniu_hurtu():
    dashboard = zrodlo(SZABLON_DASHBOARDU)
    for plik, przed in (("js/priorytety.js", '20261005d'), ("css/priorytety.css", '20261005c'),
                        ("js/modules/products-module.js", '20261005b')):
        wpis = re.search(re.escape(plik) + r"'\) \}\}\?v=(\d+[a-z]?)\"", dashboard)
        assert wpis and wpis.group(1) > przed, plik


# ── Poprawka zaznaczeń 6.10 (pełny przebieg E2E, znalezisko 1) ───────────────────────────────────────────────

def test_przerysowanie_przelicza_pola_zamowien():
    """Po hurcie gwiazdek karty przestawiają się według rangi i rysują od nowa z szablonu — pole wyboru zamówienia
    wychodziło puste, a pozycje w zwiniętych wierszach dalej zaznaczone (niewidoczne zaznaczenie, pasek „2 zaznaczone”).
    `syncAllCheckboxes` (woła je każde rysowanie listy) przelicza więc także pole każdej karty z selekcji."""
    sync = _metoda('    syncAllCheckboxes() {')
    assert "document.querySelectorAll('.il-order-card')" in sync
    assert "card.getAttribute('data-order-key')" in sync
    assert 'this.state.filteredOrders.find(' in sync
    assert 'this._updateOrderCheckboxState(' in sync
    # Rysowanie listy kończy się synchronizacją pól.
    rysuj = _metoda('    renderOrdersList() {')
    assert rysuj.index('container.appendChild(fragment);') < rysuj.index('this.syncAllCheckboxes();')


def test_hurt_gwiazdek_czysci_zaznaczenie_po_zapisie():
    """Rekomendacja centrali 6.10: po udanym zapisie hurtu zaznaczenie znika w całości (licznik 0, pasek schowany),
    żeby następna akcja hurtowa nie objęła zamówienia, które przeskoczyło w inne miejsce listy. Błąd zapisu
    zostawia zaznaczenie do ponowienia."""
    hurt = _metoda('    async showBulkStarsPicker(selectedIds) {')
    proba = hurt[hurt.index('P.ustawGwiazdki('):hurt.index('} catch (e) {')]
    blad = hurt[hurt.index('} catch (e) {'):]
    assert 'this.state.selectedProducts.clear();' in proba
    assert proba.index('this.state.selectedProducts.clear();') < proba.index('this.syncAllCheckboxes();')         < proba.index('this.toggleBulkActionsVisibility();')
    assert 'selectedProducts.clear()' not in blad
    # Przed zapisem (anulowany wybierak, odmowa w oknie potwierdzenia, limit) selekcja zostaje.
    assert 'selectedProducts.clear()' not in hurt[:hurt.index('P.ustawGwiazdki(')]


def test_pozostale_hurty_czyszcza_zaznaczenie_po_zapisie():
    """Zmiana statusu i usuwanie czyszczą selekcję i przerysowują listę (`refresh`), a przerysowanie przelicza pola
    zamówień (test wyżej). Eksport niczego nie zmienia na liście i zostawia zaznaczenie."""
    for naglowek in ('    async executeBulkStatusChange(selectedIds, newStatus) {',
                     '    async showBulkDeleteConfirmation(selectedIds) {'):
        cialo = _metoda(naglowek)
        assert cialo.index('this.state.selectedProducts.clear();') < cialo.index('await this.refresh();'), naglowek
    assert 'selectedProducts.clear()' not in _metoda('    async handleExportSelected(selectedIds) {')
