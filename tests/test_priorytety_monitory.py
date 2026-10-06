# -*- coding: utf-8 -*-
"""
Monitory hali jako czytelnicy rangi (krok K4b programu „Priorytety produkcji”, spec 7.2).

Monitor stanowiska: karty zamówień po randze (doróbki pierwsze), stół „TERAZ” i „Odłożone” w trybie `stol`, gwiazdki
i plakietki szczebla; Lakiernia — kolejność listy tabletu (grupy wykończenia), nigdy stół. Monitor zbiorczy: po randze.
Telewizor odświeża co 30 s, więc monitory czytają KOLUMNY pamięci podręcznej (`priority_rank`, `priority_rung`,
`priority_stars`) i wiersze stołu — bez `policz()`, bez blokad, bez zapisów i bez dopełniania stołu.

Pułapka z tests/test_monitory_krawedzie.py: widok HTML i AJAX muszą mieć tę samą kolejność i te same pola (dawniej
dwie niezależne kopie map w monitors.py — teraz jedna funkcja). Kluczem karty jest `order_id`, nie numer zamówienia
(numer powtarza się co rok).

Fixture montuje station_bp pod /production (filtr IP przepuszcza 127.0.0.1 klienta testowego). Ten plik nie zakłada
tabeli prod_product_events (konwencja pakietu).
"""
import itertools
import os
import re
import sys
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from flask import Blueprint, Flask
from sqlalchemy import event
from sqlalchemy.pool import StaticPool

from extensions import db
from modules.production.logistics.models import Route, RouteStop, Vehicle
from modules.production.models import (
    ProductionConfig, ProductionConfiguration, ProductionOrder, ProductionProduct, ProductionWorker,
)
from modules.production.priorytety import stale
from modules.production.priorytety.models import PriorityLog, PriorityRung, StationDesk
from modules.production.priorytety.services import drabina, stol, widok
from modules.users.models import User
from modules.calculator.models import Multiplier  # noqa: F401
from modules.clients.models import Client  # noqa: F401
import modules.quotes.models  # noqa: F401
from tests.blokady_pomocnicze import Zapytania
from tests.priorytety_fixtures import czyste_ustawienia, drabina_domyslna, ustaw  # noqa: F401

KORZEN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SZABLONY = os.path.join(KORZEN, 'modules', 'production', 'templates')
STATYKA = os.path.join(KORZEN, 'modules', 'production', 'static')
JS_MONITORA = os.path.join(STATYKA, 'js', 'stations', 'station-monitor.js')
SZABLON_MONITORA = os.path.join(SZABLONY, 'stations', 'monitor_station.html')
SZABLON_ZBIORCZY = os.path.join(SZABLONY, 'stations', 'monitor.html')
CSS_MONITORA = (os.path.join(STATYKA, 'css', 'stations', 'station-monitor-v2.css'),
                os.path.join(STATYKA, 'css', 'stations', 'station-monitor.css'))

ProductionOrder.__table__.c.shipping_label_base64.type = db.Text()

TABELE = [m.__table__ for m in (
    User, ProductionConfig, ProductionOrder, ProductionProduct, ProductionConfiguration, ProductionWorker,
    Vehicle, Route, RouteStop, PriorityRung, PriorityLog, StationDesk,
)]
T_STOL = datetime(2026, 10, 5, 8, 0)
_licznik = itertools.count(1)


@pytest.fixture()
def app(czyste_ustawienia):
    from modules.production.routers.stations import station_bp

    app = Flask(__name__, template_folder=SZABLONY)
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        'poolclass': StaticPool,
        'connect_args': {'check_same_thread': False},
    }
    app.config['LOGIN_DISABLED'] = True
    produkcja = Blueprint('production', __name__, static_folder=STATYKA, static_url_path='/production-static')
    produkcja.register_blueprint(station_bp, url_prefix='/stations')
    app.register_blueprint(produkcja, url_prefix='/production')
    db.init_app(app)

    with app.app_context():
        db.metadata.create_all(bind=db.engine, tables=TABELE)
        drabina_domyslna()
        yield app
        db.session.remove()


@pytest.fixture()
def client(app):
    return app.test_client()


# ── pomocniki ────────────────────────────────────────────────────────────────────────────────────────────────

def zam(statusy=('czeka_na_sklejanie',), gwiazdki=0, ranga=None, numer=None, rung=None, **pozycja):
    """Zamówienie z pozycją na każdy status; kolumny rangi jak po `utrwal()`. Commituje."""
    n = next(_licznik)
    order = ProductionOrder(baselinker_order_id=880000 + n,
                            internal_order_number=numer if numer is not None else str(8000 + n),
                            client_name='Klient testowy', priority_stars=gwiazdki, priority_rank=ranga,
                            priority_rung=rung)
    db.session.add(order)
    db.session.flush()
    for i, status in enumerate(statusy, start=1):
        db.session.add(ProductionProduct(order_id=order.id, short_product_id='%d_%d' % (order.id, i),
                                         product_sequence_in_order=i, original_product_name='Blat',
                                         quantity=2, volume_m3=0.1, current_status=status, **pozycja))
    db.session.commit()
    return order


def indeks_widoczny(rodzaj, wartosc):
    for i, rung in enumerate(drabina.szczeble(), start=1):
        if rung.klucz == (rodzaj, wartosc):
            return i
    raise AssertionError((rodzaj, wartosc))


def kafel_stolu(stanowisko, obiekt, odlozony=None, zrodlo='kolejka', **kolumny):
    if isinstance(obiekt, ProductionOrder):
        dane = dict(order_id=obiekt.id, product_id=None, unit_key='o:%d' % obiekt.id)
    else:
        dane = dict(order_id=obiekt.order_id, product_id=obiekt.id, unit_key='p:%d' % obiekt.id)
    if odlozony is not None:
        dane.update(postponed_at=odlozony, postpone_reason='brak_materialu', postpone_note=u'czekamy na dąb')
    dane.update(kolumny)
    db.session.add(StationDesk(station_code=stanowisko, pulled_at=T_STOL, zrodlo=zrodlo, **dane))
    db.session.commit()


def ajax(client, sciezka):
    r = client.get('/production/stations' + sciezka)
    assert r.status_code == 200, r.get_data()[:400]
    dane = r.get_json()
    assert dane['success'] is True
    return dane


def html(client, sciezka):
    r = client.get('/production/stations' + sciezka)
    assert r.status_code == 200, r.get_data()[:400]
    return r.get_data(as_text=True)


def kolejnosc_html(tresc):
    return [int(x) for x in re.findall(r'data-order-id="(\d+)"', tresc)]


# ══ Task 6: monitory — backend ═══════════════════════════════════════════════════════════════════════════════

def test_monitor_stanowiska_po_randze_dorobki_pierwsze(client):
    trzy = zam(ranga=3)
    jeden = zam(ranga=1)
    bez = zam(ranga=None)
    z_dorobka = zam(ranga=9)
    oryginal = z_dorobka.products[0]
    db.session.add(ProductionProduct(order_id=z_dorobka.id, short_product_id='%d_9' % z_dorobka.id,
                                     product_sequence_in_order=9, original_product_name='Blat', quantity=1,
                                     volume_m3=0.1, current_status='czeka_na_sklejanie',
                                     original_product_id=oryginal.id))
    db.session.commit()

    orders = ajax(client, '/ajax/monitors/gluing')['orders']

    assert [o['order_id'] for o in orders] == [z_dorobka.id, jeden.id, trzy.id, bez.id]
    assert orders[0]['dorobka'] is True and orders[1]['dorobka'] is False


def test_monitor_html_i_ajax_ta_sama_kolejnosc(client):
    for ranga in (5, 2, None, 7, 1):
        zam(ranga=ranga)
    assert kolejnosc_html(html(client, '/monitors/gluing')) == [
        o['order_id'] for o in ajax(client, '/ajax/monitors/gluing')['orders']]
    assert kolejnosc_html(html(client, '/monitor')) == [o['order_id'] for o in ajax(client, '/ajax/monitor')['orders']]


def test_monitor_ogolny_po_randze(client):
    trzecie = zam(statusy=('czeka_na_wyciecie',), ranga=3)
    pierwsze = zam(statusy=('czeka_na_pakowanie',), ranga=1, gwiazdki=5, rung=indeks_widoczny('stars', 5))
    wstrzymane = zam(statusy=('wstrzymane',), ranga=1, gwiazdki=4, rung=indeks_widoczny('stars', 4))
    drugie = zam(statusy=('czeka_na_sklejanie',), ranga=2)

    orders = ajax(client, '/ajax/monitor')['orders']

    assert [o['order_id'] for o in orders] == [pierwsze.id, drugie.id, trzecie.id, wstrzymane.id]
    assert orders[0]['gwiazdki'] == 5 and orders[0]['ranga'] == 1
    ostatnie = orders[-1]
    assert (ostatnie['ranga'], ostatnie['szczebel'], ostatnie['plakietka']) == (None, None, None)


def test_monitor_grupuje_po_id_zamowienia(client):
    a = zam(numer='1503', ranga=1)
    b = zam(numer='1503', ranga=2)
    tresc = html(client, '/monitors/gluing')
    assert kolejnosc_html(tresc) == [a.id, b.id]
    assert [o['order_id'] for o in ajax(client, '/ajax/monitors/gluing')['orders']] == [a.id, b.id]
    assert sorted(o['order_id'] for o in ajax(client, '/ajax/monitor')['orders']) == sorted([a.id, b.id])
    assert kolejnosc_html(html(client, '/monitor')) == [a.id, b.id]


def test_monitor_stol_w_ajax_i_na_stole(client):
    ustaw(stale.klucz_tryb('gluing'), 'stol')
    kto = ProductionWorker(first_name='Adam', last_name='Kowalski', is_active=True)
    db.session.add(kto)
    db.session.commit()
    na_stole = zam(ranga=2)
    odlozone = zam(ranga=1)
    zam(ranga=3)
    kafel_stolu('gluing', na_stole.products[0])
    kafel_stolu('gluing', odlozone.products[0], odlozony=datetime(2026, 10, 5, 9, 40), postponed_by_worker_id=kto.id)

    dane = ajax(client, '/ajax/monitors/gluing')

    stol_monitora = dane['stol']
    assert stol_monitora['tryb'] == 'stol' and stol_monitora['blad'] is False
    assert [k['order_id'] for k in stol_monitora['stol']] == [na_stole.id]
    (odl,) = stol_monitora['odlozone']
    assert (odl['order_id'], odl['powod_etykieta'], odl['notatka']) == (odlozone.id, u'brak materiału', u'czekamy na dąb')
    assert stol_monitora['kolejka_dalej'] == 1
    na = {o['order_id']: o['na_stole'] for o in dane['orders']}
    assert na[na_stole.id] is True and na[odlozone.id] is False


def test_monitor_lakierni_kolejnosc_jak_lista_tabletu(client):
    from modules.production.priorytety.services import lista
    kolory = {1: ('lakierowane', 'bezbarwny', 'mat'), 2: ('olejowane', 'naturalny', None),
              3: ('lakierowane', 'bezbarwny', 'mat')}
    zamowienia = {}
    for ranga in (1, 2, 3):
        rodzaj, kolor, polysk = kolory[ranga]
        zamowienia[ranga] = zam(statusy=('czeka_na_lakiernie',), ranga=ranga, parsed_finish_type=rodzaj,
                                parsed_finish_color=kolor, parsed_finish_gloss=polysk,
                                priority_rank=ranga * 100 + 1)
    # doróbka w grupie olejowanych ciągnie ją na początek listy tabletu: kolejność 2, 1, 3
    olej = zamowienia[2]
    db.session.add(ProductionProduct(order_id=olej.id, short_product_id='%d_7' % olej.id, product_sequence_in_order=7,
                                     original_product_name='Blat', quantity=1, volume_m3=0.1,
                                     current_status='czeka_na_lakiernie', parsed_finish_type='olejowane',
                                     parsed_finish_color='naturalny', original_product_id=olej.products[0].id,
                                     priority_rank=0))
    db.session.commit()
    pozycje = ProductionProduct.query.filter_by(current_status='czeka_na_lakiernie').all()
    oczekiwane = []
    for p in lista.porzadek_listy('painting', pozycje):
        if p.order_id not in oczekiwane:
            oczekiwane.append(p.order_id)
    assert oczekiwane == [zamowienia[2].id, zamowienia[1].id, zamowienia[3].id]

    dane = ajax(client, '/ajax/monitors/painting')

    assert [o['order_id'] for o in dane['orders']] == oczekiwane
    assert kolejnosc_html(html(client, '/monitors/painting')) == oczekiwane
    assert dane['orders'][0]['grupa_wykonczenia'] == u'olejowane · naturalny'
    assert dane['orders'][1]['grupa_wykonczenia'] == u'lakierowane · bezbarwny · mat'


def test_monitor_lakierni_bez_stolu_mimo_trybu_stol(client, monkeypatch):
    ustaw(stale.klucz_tryb('painting'), 'stol')
    zam(statusy=('czeka_na_lakiernie',), ranga=1)
    wywolania = []
    oryginal = widok.stoly_panelu
    monkeypatch.setattr(widok, 'stoly_panelu', lambda *a, **k: wywolania.append(a) or oryginal(*a, **k))

    assert ajax(client, '/ajax/monitors/painting')['stol'] is None
    tresc = html(client, '/monitors/painting')
    assert u'TERAZ' not in tresc and u'Dalej w kolejce' not in tresc
    assert wywolania == []


def test_monitor_gwiazdki_i_plakietka_trasy(client):
    order = zam(gwiazdki=3, ranga=1)
    trasa = Route(name=u'Śląsk', date_from=date(2026, 10, 8), date_to=date(2026, 10, 9), status='robocza')
    db.session.add(trasa)
    db.session.flush()
    db.session.add(RouteStop(route_id=trasa.id, order_id=order.id, position=1))
    drabina.zapewnij_szczebel_trasy(trasa)
    db.session.commit()
    order.priority_rung = indeks_widoczny('route', trasa.id)
    db.session.commit()

    (karta,) = ajax(client, '/ajax/monitors/gluing')['orders']
    assert karta['gwiazdki'] == 3 and karta['plakietka'] == u'Trasa Śląsk · od 08.10'
    (zbiorcza,) = ajax(client, '/ajax/monitor')['orders']
    assert zbiorcza['plakietka'] == u'Trasa Śląsk · od 08.10'


def test_monitor_przezywa_blad_priorytetow(client, monkeypatch):
    ustaw(stale.klucz_tryb('gluing'), 'stol')
    zam(ranga=2)
    zam(ranga=1)

    def awaria(*a, **k):
        raise RuntimeError('brak tabeli prod_station_desk')
    monkeypatch.setattr(widok, 'stoly_panelu', awaria)
    monkeypatch.setattr(widok, 'priorytet_zamowien', awaria)

    dane = ajax(client, '/ajax/monitors/gluing')
    assert len(dane['orders']) == 2 and dane['stol']['blad'] is True
    assert all(o['plakietka'] is None for o in dane['orders'])
    assert len(ajax(client, '/ajax/monitor')['orders']) == 2
    assert html(client, '/monitors/gluing') and html(client, '/monitor')


@pytest.mark.parametrize('sciezka', ['/monitors/gluing', '/ajax/monitors/gluing', '/monitor', '/ajax/monitor'])
def test_monitory_bez_blokad_i_zapisow(client, sciezka):
    ustaw(stale.klucz_tryb('gluing'), 'stol')
    order = zam(statusy=('czeka_na_sklejanie', 'czeka_na_formatowanie'), ranga=1)
    kafel_stolu('gluing', order.products[0], odlozony=datetime(2026, 10, 5, 9, 0))
    zam(ranga=2)
    commity = []

    def po_commicie(sesja):
        commity.append(1)
    event.listen(db.session, 'after_commit', po_commicie)
    try:
        with Zapytania() as z:
            assert client.get('/production/stations' + sciezka).status_code == 200
    finally:
        event.remove(db.session, 'after_commit', po_commicie)

    sql = [wpis[0] for wpis in z.lista]
    assert len(sql) > 2
    assert not [s for s in sql if s.endswith((' FOR UPDATE', ' LOCK IN SHARE MODE'))]
    assert not [s for s in sql if s.startswith(('INSERT', 'UPDATE', 'DELETE'))]
    assert commity == []


def test_monitor_i_zakladka_nie_wolaja_dopelnij(client, monkeypatch):
    """Część monitorów (zakładka: tests/test_priorytety_czytelnicy.py). Stół dopełnia wyłącznie tablet."""
    ustaw(stale.klucz_tryb('gluing'), 'stol')
    zam(ranga=1)
    zam(ranga=2)
    wywolania = []
    monkeypatch.setattr(stol, 'dopelnij', lambda *a, **k: wywolania.append(a))
    for sciezka in ('/monitors/gluing', '/ajax/monitors/gluing', '/monitor', '/ajax/monitor'):
        assert client.get('/production/stations' + sciezka).status_code == 200
    assert wywolania == []
    db.session.rollback()
    assert StationDesk.query.count() == 0


# ══ Task 7: szablony, JS auto-odświeżania, style ═════════════════════════════════════════════════════════════

def _zrodlo(sciezka):
    with open(sciezka, encoding='utf-8') as f:
        return f.read()


def _funkcja(js, naglowek):
    """Ciało funkcji najwyższego poziomu w station-monitor.js (od nagłówka do zamykającego `}` w kolumnie 0)."""
    poczatek = js.index(naglowek)
    return js[poczatek:js.index('\n}\n', poczatek)]


def test_monitor_stol_teraz_i_odlozone(client):
    ustaw(stale.klucz_tryb('gluing'), 'stol')
    kto = ProductionWorker(first_name='Adam', last_name='Kowalski', is_active=True)
    db.session.add(kto)
    db.session.commit()
    na_stole = zam(ranga=2, numer='8501')
    odlozone = zam(ranga=1, numer='8502')
    kafel_stolu('gluing', na_stole.products[0])
    kafel_stolu('gluing', odlozone.products[0], odlozony=datetime(2026, 10, 5, 9, 40), postponed_by_worker_id=kto.id)

    tresc = html(client, '/monitors/gluing')

    assert 'id="monitor-stol"' in tresc and u'TERAZ' in tresc
    assert 'id="monitor-odlozone"' in tresc and u'Odłożone' in tresc
    stol_html = tresc[tresc.index('id="monitor-stol"'):tresc.index('id="monitor-odlozone"')]
    assert na_stole.products[0].short_product_id in stol_html
    odl_html = tresc[tresc.index('id="monitor-odlozone"'):tresc.index('class="orders-grid"')]
    assert u'brak materiału' in odl_html and u'czekamy na dąb' in odl_html and '09:40' in odl_html
    assert u'Dalej w kolejce' in tresc
    karta = tresc[tresc.index('data-order-id="%d"' % na_stole.id) - 80:]
    assert 'na-stole' in karta[:200]


def test_monitor_bez_stolu_bez_sekcji(client):
    zam(ranga=1)
    tresc = html(client, '/monitors/gluing')        # tryb `stary`, pusty stół
    assert 'id="monitor-stol"' not in tresc and u'TERAZ' not in tresc
    assert u'Dalej w kolejce' not in tresc.split('<script')[0] or 'id="kolejka-dalej" hidden' in tresc


def test_monitor_html_gwiazdki_i_plakietka_trasy(client):
    order = zam(gwiazdki=3, ranga=1)
    trasa = Route(name=u'Śląsk', date_from=date(2026, 10, 8), date_to=date(2026, 10, 9), status='robocza')
    db.session.add(trasa)
    db.session.flush()
    db.session.add(RouteStop(route_id=trasa.id, order_id=order.id, position=1))
    drabina.zapewnij_szczebel_trasy(trasa)
    db.session.commit()
    order.priority_rung = indeks_widoczny('route', trasa.id)
    db.session.commit()

    for sciezka in ('/monitors/gluing', '/monitor'):
        tresc = html(client, sciezka)
        assert u'★★★' in tresc and 'prio-gwiazdki' in tresc, sciezka
        assert 'prio-trasa' in tresc and u'Trasa Śląsk · od 08.10' in tresc, sciezka


def test_js_monitora_przestawia_karty_wg_kolejnosci_serwera():
    funkcja = _funkcja(_zrodlo(JS_MONITORA), 'function incrementalUpdateOrders(orders) {')
    po_aktualizacji = funkcja[funkcja.index('updateOrderCard('):]
    assert 'orders.forEach' in po_aktualizacji and 'grid.appendChild(' in po_aktualizacji
    przestawienie = po_aktualizacji[po_aktualizacji.index('3a'):]
    assert przestawienie.index('grid.appendChild(') < przestawienie.index('calculateGridDimensions()')


def test_js_monitora_escapuje_teksty_z_bazy():
    js = _zrodlo(JS_MONITORA)
    assert 'function escapeHtml(' in js
    ucieczka = _funkcja(js, 'function escapeHtml(')
    for znak in ('&amp;', '&lt;', '&gt;', '&quot;', '&#39;'):
        assert znak in ucieczka
    for nazwa in ('function generateOrderCardHTML(order) {', 'function renderStolSekcje(stol) {',
                  'function plakietkaHTML(order) {'):
        cialo = _funkcja(js, nazwa)
        for pole in ('order_number', 'client_order_number', 'plakietka', 'powod_etykieta', 'notatka', 'pracownik',
                     'short_id', 'numer', 'grupa_wykonczenia', 'status_label'):
            for obiekt in ('order', 'kafel'):
                assert '${%s.%s}' % (obiekt, pole) not in cialo, (nazwa, obiekt, pole)


def test_js_monitora_renderuje_stol_i_odlozone():
    js = _zrodlo(JS_MONITORA)
    assert 'renderStolSekcje(data.stol)' in _funkcja(js, 'async function refreshMonitorData() {')
    cialo = _funkcja(js, 'function renderStolSekcje(stol) {')
    assert "'monitor-stol'" in cialo and "'monitor-odlozone'" in cialo
    assert 'stol === undefined' in cialo and 'TERAZ' in cialo and 'kolejka-dalej' in cialo


def test_js_monitora_klucz_karty_to_order_id():
    js = _zrodlo(JS_MONITORA)
    assert 'card.dataset.orderId' in _funkcja(js, 'function initializeOrdersCache() {')
    aktualizacja = _funkcja(js, 'function incrementalUpdateOrders(orders) {')
    assert 'newOrdersMap.set(order.order_number' not in aktualizacja
    assert 'String(order.order_id)' in aktualizacja
    assert 'data-order-id=' in _funkcja(js, 'function generateOrderCardHTML(order) {')
    for szablon in (SZABLON_MONITORA, SZABLON_ZBIORCZY):
        assert 'data-order-id="{{ order.order_id }}"' in _zrodlo(szablon)


def test_szablony_monitorow_maja_gwiazdki_i_sekcje():
    stanowisko = _zrodlo(SZABLON_MONITORA)
    assert 'prio.gwiazdki' in stanowisko and 'monitor-stol' in stanowisko and 'monitor-odlozone' in stanowisko
    assert 'prio.plakietka' in stanowisko
    zbiorczy = _zrodlo(SZABLON_ZBIORCZY)
    assert 'prio.gwiazdki' in zbiorczy and 'prio.plakietka' in zbiorczy


def test_style_monitora_maja_klasy_prio():
    for sciezka in CSS_MONITORA:
        css = _zrodlo(sciezka)
        for klasa in ('.prio-gwiazdki', '.prio-plakietka', '.na-stole'):
            assert klasa in css, (sciezka, klasa)


# ══ Task 7a (karta): źródło kafla i pracownik „Adam K.” na monitorze ════════════════════════════════════════

def test_monitor_odlozone_pracownik_adam_k(client):
    """Spec 7.2 / 6.1, decyzja Konrada 5.10: na telewizorze imię + inicjał nazwiska, notatka widoczna."""
    ustaw(stale.klucz_tryb('gluing'), 'stol')
    kto = ProductionWorker(first_name='Adam', last_name='Kowalski', is_active=True)
    db.session.add(kto)
    db.session.commit()
    order = zam(ranga=1)
    kafel_stolu('gluing', order.products[0], odlozony=datetime(2026, 10, 5, 9, 40), postponed_by_worker_id=kto.id)

    (odl,) = ajax(client, '/ajax/monitors/gluing')['stol']['odlozone']
    assert odl['pracownik'] == u'Adam K.' and odl['notatka'] == u'czekamy na dąb'
    tresc = html(client, '/monitors/gluing')
    assert u'Adam K.' in tresc and u'Kowalski' not in tresc and u'czekamy na dąb' in tresc
    assert u'Kowalski' not in str(ajax(client, '/ajax/monitors/gluing'))


def test_monitor_zrodlo_kafla_plakietki(client):
    ustaw(stale.klucz_tryb('gluing'), 'stol')
    order = zam(statusy=('czeka_na_sklejanie',) * 3, ranga=1)
    kafel_stolu('gluing', order.products[0], zrodlo='biuro')
    kafel_stolu('gluing', order.products[1], zrodlo='start')
    kafel_stolu('gluing', order.products[2], zrodlo='kolejka')

    stol_ajax = ajax(client, '/ajax/monitors/gluing')['stol']['stol']
    assert [k['zrodlo'] for k in stol_ajax] == ['biuro', 'start', 'kolejka']
    tresc = html(client, '/monitors/gluing')
    sekcja = tresc[tresc.index('id="monitor-stol"'):tresc.index('class="orders-grid"')]
    assert u'wysłane przez biuro' in sekcja and 'zrodlo-biuro' in sekcja
    assert u'rozpoczęte przed startem' in sekcja and 'zrodlo-start' in sekcja
    assert 'zrodlo-kolejka' not in sekcja


def test_js_monitora_plakietka_zrodla():
    js = _zrodlo(JS_MONITORA)
    zrodla = _funkcja(js, 'function zrodloHTML(zrodlo) {')
    for klasa, tekst in (('biuro', u'wysłane przez biuro'), ('start', u'rozpoczęte przed startem'),
                         ('dorobka', u'doróbka')):
        assert klasa in zrodla and tekst in zrodla
    assert 'zrodlo-' in zrodla
    assert 'zrodloHTML(kafel.zrodlo)' in _funkcja(js, 'function renderStolSekcje(stol) {')
