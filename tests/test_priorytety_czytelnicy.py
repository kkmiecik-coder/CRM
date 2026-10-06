# -*- coding: utf-8 -*-
"""
Czytelnicy rangi (krok K4b programu „Priorytety produkcji”): wspólne odczyty `widok.py` i makra plakietek,
zakładka Stanowiska, dashboard, Konfiguracja (grupy „Terminy” i „Stół stanowisk”).

Czytelnicy NICZEGO nie piszą, nie blokują i nie dopełniają stołu (spec 5.2, 9.4) — pilnują tego testy
`*_bez_blokad_i_zapisow` na liście zapytań (`tests/blokady_pomocnicze.Zapytania`). Frontu nie da się uruchomić
w obrazie testowym, więc JS i szablony sprawdzamy strukturalnie na źródle (konwencja `tests/test_druk_panel_ui.py`).

Ten plik nie zakłada tabeli prod_product_events (konwencja pakietu).
"""
import itertools
import os
import sys
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from extensions import db
from modules.production.logistics.models import Route, RouteStop
from modules.production.models import ProductionOrder, ProductionWorker
from modules.production.priorytety import stale
from modules.production.priorytety.models import PriorityRung, StationDesk
from modules.production.priorytety.services import drabina, widok
from tests.krawedzie_fixtures import BASE, KORZEN, app as _app_krawedzi, zrodlo  # noqa: F401
from tests.logistyka_fixtures import produkt
from tests.priorytety_fixtures import (  # noqa: F401
    DZIS, czyste_ustawienia, drabina_domyslna, ustaw, zamrozony_dzien,
)

_licznik = itertools.count(1)
T_STOL = datetime(2026, 10, 5, 8, 0)
PO_TERMINIE = date(2026, 10, 1)
BLISKO = date(2026, 10, 6)
DALEKO = date(2026, 11, 30)


@pytest.fixture()
def app(_app_krawedzi, zamrozony_dzien, czyste_ustawienia):
    """Apka z API produkcji (`krawedzie_fixtures`) i domyślną drabiną (9 szczebli stałych)."""
    drabina_domyslna()
    return _app_krawedzi


@pytest.fixture()
def client(app):
    return app.test_client()


# ── pomocniki danych ─────────────────────────────────────────────────────────────────────────────────────────

def zam(statusy=('czeka_na_sklejanie',), gwiazdki=0, termin=DALEKO, numer=None, **kolumny):
    """Zamówienie z jedną pozycją na każdy status; wszystkie z terminem `termin`. Commituje."""
    n = next(_licznik)
    order = ProductionOrder(baselinker_order_id=700000 + n,
                            internal_order_number=numer if numer is not None else str(6000 + n),
                            client_name='Klient testowy %d' % n, priority_stars=gwiazdki, **kolumny)
    db.session.add(order)
    db.session.flush()
    for i, status in enumerate(statusy, start=1):
        produkt(order, status=status, sekwencja=i, deadline_date=termin)
    db.session.commit()
    return order


def trasa(nazwa=u'Śląsk', status='robocza', date_from=date(2026, 10, 8), zamowienia=()):
    """Trasa ze szczeblem w miejscu domyślnym (bez routes.utworz). Commituje."""
    r = Route(name=nazwa, date_from=date_from, date_to=date_from + timedelta(days=1), status='robocza')
    db.session.add(r)
    db.session.flush()
    for i, order in enumerate(zamowienia, start=1):
        db.session.add(RouteStop(route_id=r.id, order_id=order.id, position=i))
    drabina.zapewnij_szczebel_trasy(r)
    r.status = status
    db.session.commit()
    return r


def indeks_widoczny(rodzaj, wartosc):
    """Indeks (1-based) szczebla wśród WIDOCZNYCH — to, co K1 zapisuje w `priority_rung`."""
    for i, rung in enumerate(drabina.szczeble(), start=1):
        if rung.klucz == (rodzaj, wartosc):
            return i
    raise AssertionError('brak szczebla %r' % ((rodzaj, wartosc),))


def kafel_stolu(stanowisko, obiekt, odlozony=None, zrodlo='kolejka', pobrano=T_STOL, **kolumny):
    """Wiersz stołu dla pozycji albo zamówienia. `odlozony` — czas odłożenia (None = leży na stole). Commituje."""
    if isinstance(obiekt, ProductionOrder):
        dane = dict(order_id=obiekt.id, product_id=None, unit_key='o:%d' % obiekt.id)
    else:
        dane = dict(order_id=obiekt.order_id, product_id=obiekt.id, unit_key='p:%d' % obiekt.id)
    if odlozony is not None:
        dane.update(postponed_at=odlozony, postpone_reason='brak_materialu', postpone_note=u'czekamy na dąb')
    dane.update(kolumny)
    db.session.add(StationDesk(station_code=stanowisko, pulled_at=pobrano, zrodlo=zrodlo, **dane))
    db.session.commit()


def pracownik(imie='Adam', nazwisko='Kowalski'):
    kto = ProductionWorker(first_name=imie, last_name=nazwisko, is_active=True)
    db.session.add(kto)
    db.session.commit()
    return kto


def render(app, kod):
    return app.jinja_env.from_string(
        u"{% import 'components/_priorytet_plakietki.html' as prio %}" + kod).render()


# ══ Task 1: wspólne odczyty i makra plakietek ════════════════════════════════════════════════════════════════

def test_stoly_panelu_filtr_stanowisk(app):
    (jeden,) = widok.stoly_panelu(stanowiska=['gluing'])
    assert jeden['stanowisko'] == 'gluing'
    # bez filtra: sześć stanowisk ze stołem w kolejności procesu (Lakiernia nie ma stołu — K3 Task 5a)
    assert [s['stanowisko'] for s in widok.stoly_panelu()] == [
        'cutting', 'assembly', 'gluing', 'formatting', 'edges', 'packaging']
    assert widok.stoly_panelu(stanowiska=['painting']) == []


def test_liczba_pilnych_zamowien_szczeble(app):
    zam(gwiazdki=5)
    zam(gwiazdki=4)
    zam(termin=PO_TERMINIE)
    na_trasie = zam(gwiazdki=0)
    trasa(status='zatwierdzona', zamowienia=[na_trasie])
    zam(gwiazdki=3)
    zam(termin=BLISKO)
    zam()
    zam(statusy=('spakowane',), gwiazdki=5)

    assert widok.liczba_pilnych_zamowien() == 4


def test_priorytet_zamowien_z_kolumn(app):
    dwie = zam(gwiazdki=2)
    na_trasie = zam(gwiazdki=0)
    slask = trasa(nazwa=u'Śląsk', date_from=date(2026, 10, 8), zamowienia=[na_trasie])
    bez_rangi = zam(gwiazdki=1)
    dwie.priority_rung, dwie.priority_rank = indeks_widoczny('stars', 2), 5
    na_trasie.priority_rung, na_trasie.priority_rank = indeks_widoczny('route', slask.id), 1
    db.session.commit()

    wynik = widok.priorytet_zamowien([dwie.id, na_trasie.id, bez_rangi.id])

    assert wynik[dwie.id]['gwiazdki'] == 2 and wynik[dwie.id]['ranga'] == 5
    assert wynik[dwie.id]['szczebel']['rodzaj'] == 'gwiazdki'
    assert wynik[dwie.id]['plakietka'] is None
    assert wynik[na_trasie.id]['szczebel']['rodzaj'] == 'trasa'
    assert wynik[na_trasie.id]['plakietka'] == u'Trasa Śląsk · od 08.10'
    assert wynik[bez_rangi.id] == {'gwiazdki': 1, 'ranga': None, 'szczebel': None, 'plakietka': None}


def test_priorytet_zamowien_indeks_widoczny_nie_position(app):
    """`priority_rung` to indeks wśród szczebli WIDOCZNYCH (K1), nie kolumna `position` — ta numeruje też ukryte
    szczeble tras załadowanych. Trasa załadowana ma szczebel z `position` 0 (nad ★★★★★, ukryty)."""
    zaladowana = Route(name=u'Pomorze', date_from=date(2026, 10, 2), date_to=date(2026, 10, 3), status='zaladowana')
    db.session.add(zaladowana)
    db.session.flush()
    db.session.add(PriorityRung(kind='route', route_id=zaladowana.id, position=0))
    order = zam(termin=PO_TERMINIE)
    order.priority_rung, order.priority_rank = indeks_widoczny('tag', stale.TAG_PO_TERMINIE), 1
    db.session.commit()

    wynik = widok.priorytet_zamowien([order.id])[order.id]

    assert wynik['szczebel']['rodzaj'] == 'tag'
    assert wynik['plakietka'] == u'Po terminie'


def test_priorytet_zamowien_nieaktywne_bez_rangi(app):
    """Zamówienie bez pozycji w produkcji (same `wstrzymane`) ma w kolumnach rangę z ostatniego przeliczenia —
    czytelnik traktuje je jak zamówienie bez rangi (Doprecyzowania 8)."""
    order = zam(statusy=('wstrzymane', 'wstrzymane'), gwiazdki=3)
    order.priority_rung, order.priority_rank = indeks_widoczny('stars', 3), 3
    db.session.commit()

    wynik = widok.priorytet_zamowien([order.id])[order.id]

    assert wynik == {'gwiazdki': 3, 'ranga': None, 'szczebel': None, 'plakietka': None}


def test_priorytet_zamowien_indeks_poza_drabina(app):
    order = zam(gwiazdki=1)
    order.priority_rung, order.priority_rank = 99, 2
    db.session.commit()
    wynik = widok.priorytet_zamowien([order.id])[order.id]
    assert (wynik['ranga'], wynik['szczebel'], wynik['plakietka']) == (2, None, None)
    assert widok.priorytet_zamowien([]) == {}


def test_etykiety_powodow_pokrywaja_kody():
    assert set(stale.ETYKIETY_POWODOW_ODLOZENIA) == set(stale.POWODY_ODLOZENIA)
    assert stale.ETYKIETY_POWODOW_ODLOZENIA['brak_materialu'] == u'brak materiału'


def test_stoly_panelu_powod_etykieta(app):
    order = zam(statusy=('czeka_na_sklejanie',))
    kafel_stolu('gluing', order.products[0], odlozony=datetime(2026, 10, 5, 9, 40))
    (sklejanie,) = widok.stoly_panelu(stanowiska=['gluing'])
    (odlozony,) = sklejanie['odlozone']
    assert odlozony['powod_etykieta'] == u'brak materiału'


def test_makra_plakietek(app):
    assert render(app, u"{{ prio.gwiazdki(0) }}").strip() == ''
    trzy = render(app, u"{{ prio.gwiazdki(3) }}")
    assert trzy.count(u'★') == 3 and 'prio-gwiazdki' in trzy and 'title="3 gwiazdki"' in trzy
    po_terminie = render(app, u"{{ prio.plakietka({'rodzaj': 'tag', 'etykieta': 'Po terminie'}) }}")
    assert 'prio-po_terminie' in po_terminie and u'Po terminie' in po_terminie
    assert u'Doróbka' in render(app, u"{{ prio.plakietka(None, True) }}")
    assert 'prio-dorobka' in render(app, u"{{ prio.plakietka(None, True) }}")
    assert render(app, u"{{ prio.plakietka(None) }}").strip() == ''
    assert render(app, u"{{ prio.plakietka({'rodzaj': 'gwiazdki', 'etykieta': '★★'}) }}").strip() == ''
    trasa_html = render(app, u"{{ prio.plakietka({'rodzaj': 'trasa', 'etykieta': '<b>Śląsk</b>', "
                             u"'trasa': {'date_from': '2026-10-08'}}) }}")
    assert 'prio-trasa' in trasa_html and '<b>' not in trasa_html and '&lt;b&gt;' in trasa_html
    assert u'· od 08.10' in trasa_html


def test_makro_plakietki_zna_wszystkie_tagi(app):
    """Klasa tagu z etykiety (kafle kolejki niosą krótki szczebel bez kodu tagu) — mapa w makrze musi być
    odwrotnością `widok.ETYKIETY_TAGOW`."""
    for tag, etykieta in widok.ETYKIETY_TAGOW.items():
        html = render(app, u"{{ prio.plakietka({'rodzaj': 'tag', 'etykieta': '%s'}) }}" % etykieta)
        assert 'prio-%s' % tag in html, tag


# ══ Task 2: zakładka Stanowiska — stół, odłożone, niekompletne, 15 kafli kolejki ═════════════════════════════

from sqlalchemy import event  # noqa: E402

from modules.production.priorytety.services import lista, stol  # noqa: E402
from tests.blokady_pomocnicze import Zapytania  # noqa: E402
from tests.krawedzie_fixtures import SZABLON_STANOWISK  # noqa: E402

PY_STATIONS_API = os.path.join(KORZEN, 'modules', 'production', 'routers', 'api', 'stations_api.py')
SZABLON_PANELU = os.path.join(KORZEN, 'modules', 'production', 'templates', 'panel', 'dashboard.html')
JS_LOADER = os.path.join(KORZEN, 'modules', 'production', 'static', 'js', 'production-app-loader.js')


def zakladka(client):
    r = client.get(BASE + '/stations-tab-content')
    assert r.status_code == 200, r.get_data()[:500]
    dane = r.get_json()
    assert dane['success'] is True
    return dane


def karta_html(html, nazwa):
    """Fragment HTML karty stanowiska (od `data-stanowisko="<kod>"` do następnej karty)."""
    znacznik = 'data-stanowisko="%s"' % nazwa
    assert znacznik in html, nazwa
    reszta = html[html.index(znacznik):]
    koniec = reszta.find('data-stanowisko="', len(znacznik))
    return reszta if koniec < 0 else reszta[:koniec]


def test_zakladka_stanowisk_stol_i_odlozone_z_widoku(client):
    kto = pracownik('Adam', 'Kowalski')
    order = zam(statusy=('czeka_na_sklejanie',) * 3, gwiazdki=2, numer='7001')
    a, b, _c = order.products
    kafel_stolu('gluing', a)
    kafel_stolu('gluing', b, odlozony=datetime(2026, 10, 5, 9, 40), postponed_by_worker_id=kto.id)

    dane = zakladka(client)

    sklejanie = dane['data']['gluing']
    assert [k['unit_key'] for k in sklejanie['stol']] == ['p:%d' % a.id]
    assert [k['unit_key'] for k in sklejanie['odlozone']] == ['p:%d' % b.id]
    assert sklejanie['stats']['na_stole'] == 1 and sklejanie['stats']['odlozone'] == 1
    assert (sklejanie['stats']['miejsca'], sklejanie['stats']['limit_odlozen']) == (2, 10)
    assert sklejanie['tryb'] == 'stary' and sklejanie['jednostka'] == 'pozycja'
    html = karta_html(dane['html'], 'gluing')
    assert a.short_product_id in html and b.short_product_id in html
    assert u'brak materiału' in html and u'Adam Kowalski' in html and u'czekamy na dąb' in html
    assert u'Na stole' in html and u'Odłożone' in html


def test_zakladka_stanowisk_kolejka_15_z_kandydatow(client):
    order = zam(statusy=('czeka_na_sklejanie',) * 20)
    kafel_stolu('gluing', order.products[0])

    dane = zakladka(client)

    kolejka = dane['data']['gluing']['kolejka']
    assert len(kolejka) == 15
    db.session.rollback()
    oczekiwane = [k['product_id'] for k in widok.kolejka_stanowiska('gluing', 15)['kafle']]
    assert [k['product_id'] for k in kolejka] == oczekiwane
    assert order.products[0].id not in [k['product_id'] for k in kolejka]
    assert dane['data']['gluing']['stats']['kolejka_dalej'] == 19


def test_zakladka_formatowania_niekompletne_z_brakujacymi(client):
    order = zam(statusy=('czeka_na_formatowanie', 'czeka_na_sklejanie'), numer='7002')

    dane = zakladka(client)

    (wiersz,) = dane['data']['formatting']['niekompletne']
    assert (wiersz['order_id'], wiersz['na_stanowisku'], wiersz['pozycji']) == (order.id, 1, 2)
    html = karta_html(dane['html'], 'formatting')
    assert u'Niekompletne' in html and '1/2' in html and u'Sklejanie' in html
    assert order.products[1].short_product_id in html


def test_zakladka_lakierni_lista_bez_stolu(client, app):
    kolory = [('lakierowane', 'bezbarwny', 'mat'), ('olejowane', 'naturalny', None),
              ('lakierowane', 'bezbarwny', 'mat')]
    zamowienia = []
    for gwiazdki, (rodzaj, kolor, polysk) in zip((1, 5, 3), kolory):
        order = zam(statusy=('czeka_na_lakiernie',), gwiazdki=gwiazdki)
        p = order.products[0]
        p.parsed_finish_type, p.parsed_finish_color, p.parsed_finish_gloss = rodzaj, kolor, polysk
        zamowienia.append(order)
    for ranga, order in zip((3, 1, 2), zamowienia):
        order.products[0].priority_rank = ranga * 100 + 1
    db.session.commit()
    ustaw(stale.klucz_tryb('painting'), 'stol')

    dane = zakladka(client)

    lakiernia = dane['data']['painting']
    assert not {'stol', 'odlozone', 'tryb', 'niekompletne'} & set(lakiernia)
    db.session.rollback()
    from modules.production.models import ProductionProduct
    pozycje = ProductionProduct.query.filter_by(current_status='czeka_na_lakiernie').all()
    oczekiwane = [p.id for p in lista.porzadek_listy('painting', pozycje)][:15]
    assert [k['product_id'] for k in lakiernia['kolejka']] == oczekiwane
    assert lakiernia['kolejka'][0]['grupa'] == u'olejowane · naturalny'
    html = karta_html(dane['html'], 'painting')
    assert u'Na stole' not in html and 'Tryb:' not in html
    assert u'Dalej na liście' in html and u'olejowane · naturalny' in html


def test_zakladka_bez_progow_rangi_i_sekcji_priority():
    html = zrodlo(SZABLON_STANOWISK)
    for zakazane in ('priority-section', 'priority_rank <=', 'high_priority', 'startProcessing'):
        assert zakazane not in html, zakazane
    assert 'priority_rank <=' not in zrodlo(PY_STATIONS_API)
    assert 'high_priority' not in zrodlo(PY_STATIONS_API)


def test_zakladka_kropka_to_odlozone(client):
    order = zam(statusy=('czeka_na_sklejanie',) * 2)
    kafel_stolu('gluing', order.products[0], odlozony=datetime(2026, 10, 5, 9, 0))

    dane = zakladka(client)

    assert dane['html'].count(u'title="1 odłożonych"') == 1
    assert 'high-priority-dot' not in dane['html']


def test_zakladka_gwiazdki_i_plakietka_trasy(client):
    order = zam(statusy=('czeka_na_sklejanie',), gwiazdki=3)
    slask = trasa(nazwa=u'Śląsk', zamowienia=[order])
    order.priority_rung, order.priority_rank = indeks_widoczny('route', slask.id), 1
    db.session.commit()

    html = karta_html(zakladka(client)['html'], 'gluing')

    assert u'★★★' in html and 'prio-gwiazdki' in html
    assert 'prio-trasa' in html and u'Trasa Śląsk' in html


def test_zakladka_przezywa_blad_priorytetow(client, monkeypatch):
    zam(statusy=('czeka_na_sklejanie',) * 2)

    def awaria(*a, **k):
        raise RuntimeError('brak tabeli prod_station_desk')
    monkeypatch.setattr(widok, 'stoly_panelu', awaria)

    dane = zakladka(client)

    assert dane['data']['gluing']['stats']['total_pending'] == 2
    assert dane['data']['gluing']['blad_priorytetow'] is True
    assert u'Stół i kolejka chwilowo niedostępne' in dane['html']


def test_zakladka_stanowisk_bez_blokad_i_zapisow(client):
    order = zam(statusy=('czeka_na_sklejanie',) * 3)
    kafel_stolu('gluing', order.products[0], odlozony=datetime(2026, 10, 5, 9, 0))
    zam(statusy=('czeka_na_formatowanie', 'czeka_na_sklejanie'))
    zam(statusy=('czeka_na_lakiernie',))
    commity = []

    def po_commicie(sesja):
        commity.append(1)
    event.listen(db.session, 'after_commit', po_commicie)
    try:
        with Zapytania() as z:
            zakladka(client)
    finally:
        event.remove(db.session, 'after_commit', po_commicie)

    sql = [wpis[0] for wpis in z.lista]
    assert len(sql) > 5
    assert not [s for s in sql if s.endswith((' FOR UPDATE', ' LOCK IN SHARE MODE'))]
    assert not [s for s in sql if s.startswith(('INSERT', 'UPDATE', 'DELETE'))]
    assert commity == []


def test_monitor_i_zakladka_nie_wolaja_dopelnij(client, monkeypatch):
    """Część zakładki (monitory: tests/test_priorytety_monitory.py). Stół dopełnia wyłącznie tablet (spec 5.2)."""
    zam(statusy=('czeka_na_sklejanie',) * 3)
    wywolania = []
    monkeypatch.setattr(stol, 'dopelnij', lambda *a, **k: wywolania.append(a))
    ustaw(stale.klucz_tryb('gluing'), 'stol')

    zakladka(client)

    assert wywolania == []
    db.session.rollback()
    assert StationDesk.query.count() == 0


def test_panel_ma_zakladke_stanowisk():
    html = zrodlo(SZABLON_PANELU)
    assert 'id="stations-tab"' in html and 'id="stations-tab-content"' in html
    assert "css/stations-tab.css') }}?v=" in html
    loader = zrodlo(JS_LOADER)
    poczatek = loader.index('getInitialTabFromURL()')
    valid = loader[poczatek:loader.index('];', poczatek)]
    assert "'stations-tab'" in valid
    assert "case 'stations-tab': await this.loadStationsTab()" in loader
    assert 'async loadStationsTab()' in loader
    metoda = loader[loader.index('async loadStationsTab()'):]
    metoda = metoda[:metoda.index('\n    async ', 10)]
    assert 'fetch(' in metoda and 'X-Requested-With' in metoda and 'executeInlineScripts' in metoda
    assert 'getStationsTabContent' not in metoda
    # skróty Ctrl+1…7 bez Stanowisk (jak bez Pracowników)
    skroty = loader[loader.index("event.key <= '7'"):]
    skroty = skroty[:skroty.index('];')]
    assert 'stations-tab' not in skroty
    szablon = zrodlo(SZABLON_STANOWISK)
    assert 'window.loadTabContent' not in szablon
    assert "window.ProductionApp.loadTabContent('stations-tab')" in szablon
    timery = szablon[szablon.index('function initStationRefreshTimers()'):]
    timery = timery[:timery.index('\n}\n')]
    assert 'clearInterval(' in timery


# ══ Task 2a (karta): źródło kafla, „Zdejmij ze stołu”, stół dłuższy niż K, widma ═══════════════════════════

def test_stoly_panelu_widma_widoczne_do_zdjecia(app):
    """Raport K3, D2: kafel `o:` zamówienia, które nie ma już pozycji na stanowisku, i kafel `p:` pozycji, która
    zeszła ze stanowiska, liczą się do K, a dotąd nie było ich widać w panelu — biuro nie miało jak ich zdjąć."""
    zszedl = zam(statusy=('czeka_na_pakowanie',), numer='7101')
    kafel_stolu('formatting', zszedl)
    poszla = zam(statusy=('czeka_na_krawedzie', 'czeka_na_sklejanie'), numer='7102')
    kafel_stolu('gluing', poszla.products[0], zrodlo='start')
    zywe = zam(statusy=('czeka_na_sklejanie',))
    kafel_stolu('gluing', zywe.products[0])

    stoly = {s['stanowisko']: s for s in widok.stoly_panelu()}

    (widmo_o,) = stoly['formatting']['widma']
    assert (widmo_o['unit_key'], widmo_o['order_id'], widmo_o['numer']) == ('o:%d' % zszedl.id, zszedl.id, '7101')
    assert widmo_o['opis'] == u'zamówienie bez pozycji na stanowisku' and widmo_o['odlozony'] is False
    assert stoly['formatting']['stol'] == []
    (widmo_p,) = stoly['gluing']['widma']
    assert widmo_p['unit_key'] == 'p:%d' % poszla.products[0].id
    assert widmo_p['short_id'] == poszla.products[0].short_product_id
    assert widmo_p['opis'] == u'pozycja już nie czeka na stanowisku' and widmo_p['zrodlo'] == 'start'
    assert [k['unit_key'] for k in stoly['gluing']['stol']] == ['p:%d' % zywe.products[0].id]
    assert all(s['widma'] == [] for kod, s in stoly.items() if kod not in ('formatting', 'gluing'))


def test_stoly_panelu_widmo_innej_jednostki(app):
    order = zam(statusy=('czeka_na_formatowanie',), numer='7103')
    kafel_stolu('formatting', order.products[0], odlozony=datetime(2026, 10, 5, 9, 0))   # `p:` na stanowisku zamówień

    (formatowanie,) = widok.stoly_panelu(stanowiska=['formatting'])

    (widmo,) = formatowanie['widma']
    assert widmo['unit_key'] == 'p:%d' % order.products[0].id and widmo['odlozony'] is True
    assert widmo['opis'] == u'kafel innej jednostki (po zmianie ustawień)'
    assert formatowanie['odlozone'] == []


def test_stoly_panelu_wroci_przy_dopelnieniu(app):
    """D7 / pytanie 9 raportu K3: „Zdejmij” doróbki albo kafla, który stanąłby pierwszy w kolejce, jest pozorne —
    panel to opisuje. Kafel daleko w kolejce po zdjęciu nie wraca od razu."""
    pilne = zam(statusy=('czeka_na_sklejanie',), gwiazdki=5, numer='7201')
    zwykle = zam(statusy=('czeka_na_sklejanie',) * 3, numer='7202')
    oryginal = zwykle.products[2]
    dorobka = produkt(zwykle, status='czeka_na_sklejanie', sekwencja=4, deadline_date=DALEKO,
                      original_product_id=oryginal.id)
    for order, rung in ((pilne, indeks_widoczny('stars', 5)), (zwykle, indeks_widoczny('stars', 0))):
        order.priority_rung, order.priority_rank = rung, 1 if order is pilne else 2
    db.session.commit()
    kafel_stolu('gluing', pilne.products[0])                      # ★5 — po zdjęciu pierwszy w kolejce
    kafel_stolu('gluing', zwykle.products[1])                     # bez gwiazdek — za pozycją 0 tego samego zamówienia
    kafel_stolu('gluing', dorobka, zrodlo='dorobka')

    (sklejanie,) = widok.stoly_panelu(stanowiska=['gluing'])

    wroci = {k['unit_key']: k['wroci_przy_dopelnieniu'] for k in sklejanie['stol']}
    assert wroci == {'p:%d' % pilne.products[0].id: True, 'p:%d' % zwykle.products[1].id: False,
                     'p:%d' % dorobka.id: True}


def test_zakladka_zrodlo_kafla_plakietki(client):
    order = zam(statusy=('czeka_na_sklejanie',) * 4, numer='7301')
    p = order.products
    kafel_stolu('gluing', p[0], zrodlo='biuro', sent_by_user_id=1)
    kafel_stolu('gluing', p[1], zrodlo='start')
    kafel_stolu('gluing', p[2], zrodlo='dorobka')
    kafel_stolu('gluing', p[3], zrodlo='kolejka')

    html = karta_html(zakladka(client)['html'], 'gluing')

    assert u'wysłane przez biuro' in html and 'zrodlo-biuro' in html
    assert u'rozpoczęte przed startem' in html and 'zrodlo-start' in html
    assert 'zrodlo-dorobka' in html
    assert 'zrodlo-kolejka' not in html


def test_zakladka_zdejmij_ze_stolu(client):
    order = zam(statusy=('czeka_na_sklejanie',) * 4, gwiazdki=0, numer='7401')
    p = order.products
    order.priority_rung, order.priority_rank = indeks_widoczny('stars', 0), 1
    db.session.commit()
    kafel_stolu('gluing', p[0])
    kafel_stolu('gluing', p[3], odlozony=datetime(2026, 10, 5, 9, 0))
    widmo = zam(statusy=('czeka_na_pakowanie',), numer='7402')
    kafel_stolu('formatting', widmo)

    html = zakladka(client)['html']

    sklejanie = karta_html(html, 'gluing')
    assert "zdejmijZeStolu('gluing', 'p:%d'" % p[0].id in sklejanie
    assert "zdejmijZeStolu('gluing', 'p:%d'" % p[3].id in sklejanie
    assert "zdejmijZeStolu('formatting', 'o:%d'" % widmo.id in karta_html(html, 'formatting')
    assert u'zamówienie bez pozycji na stanowisku' in karta_html(html, 'formatting')
    # p[0] po zdjęciu stanie pierwszy (pozycja 1 zamówienia) — podpis; p[3] stoi za p[1] i p[2] — bez podpisu
    assert sklejanie.count(u'kafel wróci przy następnym dopełnieniu') == 1


def test_zakladka_stol_dluzszy_niz_k(client):
    order = zam(statusy=('czeka_na_sklejanie',) * 5)
    for p in order.products:
        kafel_stolu('gluing', p, zrodlo='start')

    dane = zakladka(client)

    assert len(dane['data']['gluing']['stol']) == 5
    html = karta_html(dane['html'], 'gluing')
    assert all(p.short_product_id in html for p in order.products)
    assert '5/2' in html and u'ponad K' in html


def _funkcja_js(zrodlo_html, naglowek):
    reszta = zrodlo_html[zrodlo_html.index(naglowek):]
    return reszta[:reszta.index('\n}\n')]


def test_zakladka_js_zdejmij_przez_post():
    funkcja = _funkcja_js(zrodlo(SZABLON_STANOWISK), 'async function zdejmijZeStolu(')
    assert "'/production/api/priorytety/stoly/'" in funkcja and "'/zdejmij'" in funkcja
    assert "method: 'POST'" in funkcja and 'unit_key' in funkcja
    assert 'confirm(' in funkcja and 'brak_kafla' in funkcja
    assert 'refreshWorkflowData()' in funkcja
    assert u'wróci przy następnym dopełnieniu' in funkcja
    # Napis JS w jednej linii: prawdziwy znak nowej linii w '…' to SyntaxError i cały skrypt zakładki nie działa
    # (wyszło na podglądzie). Każda linia skryptu zakładki ma parzystą liczbę apostrofów.
    skrypt = zrodlo(SZABLON_STANOWISK).split('<script>', 1)[1]
    for linia in skrypt.splitlines():
        assert linia.count("'") % 2 == 0, linia


# ══ Task 3: dashboard — pilne zamówienia na szczeblach drabiny ══════════════════════════════════════════════

PY_DASHBOARD_API = os.path.join(KORZEN, 'modules', 'production', 'routers', 'api', 'dashboard_api.py')


def statystyki(client):
    r = client.get(BASE + '/dashboard-stats')
    assert r.status_code == 200, r.get_data()[:500]
    dane = r.get_json()
    assert dane['success'] is True
    return dane


def _zestaw_pilnych():
    """★5 (trzy pozycje — liczy się raz), ★4, po terminie, na trasie zatwierdzonej; ★3, blisko terminu i bez
    gwiazdek się nie liczą."""
    zam(statusy=('czeka_na_sklejanie',) * 3, gwiazdki=5)
    zam(gwiazdki=4)
    zam(termin=PO_TERMINIE)
    na_trasie = zam()
    trasa(status='zatwierdzona', zamowienia=[na_trasie])
    zam(gwiazdki=3)
    zam(termin=BLISKO)
    zam()


def test_high_priority_count_to_zamowienia_na_szczeblach_pilnych(client):
    _zestaw_pilnych()
    assert statystyki(client)['stats']['high_priority_count'] == 4


def test_high_priority_count_rowny_sumie_licznikow_drabiny(client):
    _zestaw_pilnych()
    liczba = statystyki(client)['stats']['high_priority_count']
    db.session.rollback()
    suma = sum(s['w_produkcji'] for s in widok.drabina_panelu()['szczeble']
               if (s['rodzaj'] == 'gwiazdki' and s['gwiazdki'] in (5, 4))
               or (s['rodzaj'] == 'tag' and s['tag'] == stale.TAG_PO_TERMINIE) or s['rodzaj'] == 'trasa')
    assert liczba == suma == 4


def test_alert_pilnych_bez_progu_150(client):
    for _ in range(11):
        zam(gwiazdki=5)
    dane = statystyki(client)
    (alert,) = [a for a in dane['alerts'] if a['title'] == u'Dużo pilnych zamówień']
    assert alert['count'] == 11
    assert u'zamówień' in alert['message'] and u'★★★★★' in alert['message']
    tekst = str(dane)
    assert u'≥150' not in tekst and '>=150' not in tekst
    assert u'≥150' not in zrodlo(PY_DASHBOARD_API) and '>=150' not in zrodlo(PY_DASHBOARD_API)


def test_alert_pilnych_przy_dziesieciu_nie_ma(client):
    for _ in range(10):
        zam(gwiazdki=5)
    dane = statystyki(client)
    assert dane['stats']['high_priority_count'] == 10
    assert not [a for a in dane['alerts'] if a['title'] == u'Dużo pilnych zamówień']


def test_dashboard_stats_przezywa_blad_priorytetow(client, monkeypatch):
    for _ in range(11):
        zam(gwiazdki=5)

    def awaria():
        raise RuntimeError('brak tabeli prod_priority_rungs')
    monkeypatch.setattr(widok, 'liczba_pilnych_zamowien', awaria)

    dane = statystyki(client)

    assert dane['stats']['high_priority_count'] is None
    assert not [a for a in dane['alerts'] if a['title'] == u'Dużo pilnych zamówień']
    assert dane['stats']['total_products'] == 11


def test_dashboard_stats_bez_blokad_i_zapisow(client):
    _zestaw_pilnych()
    commity = []

    def po_commicie(sesja):
        commity.append(1)
    event.listen(db.session, 'after_commit', po_commicie)
    try:
        with Zapytania() as z:
            statystyki(client)
    finally:
        event.remove(db.session, 'after_commit', po_commicie)

    sql = [wpis[0] for wpis in z.lista]
    assert len(sql) > 5
    assert not [s for s in sql if s.endswith((' FOR UPDATE', ' LOCK IN SHARE MODE'))]
    assert not [s for s in sql if s.startswith(('INSERT', 'UPDATE', 'DELETE'))]
    assert commity == []


# ══ Task 4: Konfiguracja — jedna droga zapisu priorytetów i terminów, martwe klucze ═════════════════════════

PY_CONFIG_API = os.path.join(KORZEN, 'modules', 'production', 'routers', 'api', 'config_api.py')
PY_CONFIG_SERVICE = os.path.join(KORZEN, 'modules', 'production', 'services', 'config_service.py')
JS_KONFIGURACJA = os.path.join(KORZEN, 'modules', 'production', 'static', 'js', 'modules', 'config-module.js')
SZABLON_KONFIGURACJI = os.path.join(KORZEN, 'modules', 'production', 'templates', 'components',
                                    'config-tab-content.html')
XHR = {'X-Requested-With': 'XMLHttpRequest'}
MARTWE_KLUCZE = ('PRIORITY_RECALC_INTERVAL_HOURS', 'PRIORITY_ALGORITHM_VERSION', 'STATION_CUTTING_PRIORITY_SORT',
                 'STATION_ASSEMBLY_PRIORITY_SORT', 'STATION_PACKAGING_PRIORITY_SORT')


def wartosc_konfiguracji(klucz):
    from modules.production.models import ProductionConfig
    db.session.rollback()
    wiersz = ProductionConfig.query.filter_by(config_key=klucz).first()
    return wiersz.config_value if wiersz is not None else None


@pytest.mark.parametrize('klucz, wartosc', [
    ('DEADLINE_DEFAULT_DAYS', 10), ('DEADLINE_FINISHED_DAYS', 10), ('DEADLINE_DAY_TYPE', 'kalendarzowe'),
    ('priorytety_tryb_gluing', 'stol'), ('priorytety_blisko_terminu_dni', 5),
])
def test_update_configs_odrzuca_klucze_priorytetow_i_terminow(client, klucz, wartosc):
    ustaw(klucz, 'przed')
    r = client.post(BASE + '/update-configs', json={'configs': {klucz: wartosc}}, headers=XHR)
    assert r.status_code == 400
    assert u'Niepozwolone klucze konfiguracji' in r.get_json()['error']
    assert wartosc_konfiguracji(klucz) == 'przed'


@pytest.mark.parametrize('klucz', MARTWE_KLUCZE)
def test_update_configs_odrzuca_martwe_klucze(client, klucz):
    r = client.post(BASE + '/update-configs', json={'configs': {klucz: '1'}}, headers=XHR)
    assert r.status_code == 400
    assert wartosc_konfiguracji(klucz) is None


def test_update_configs_przyjmuje_pozostale(client):
    # Wiersz istnieje (jak na produkcji): `update_multiple_configs` przy samym wstawieniu nowego wiersza nie
    # commituje (licznik zmian liczy tylko UPDATE) — usterka sprzed K4b, poza zakresem (raport K4b).
    ustaw('REFRESH_INTERVAL_SECONDS', 30, 'integer')
    r = client.post(BASE + '/update-configs', json={'configs': {'REFRESH_INTERVAL_SECONDS': 45}}, headers=XHR)
    assert r.status_code == 200, r.get_data()[:300]
    assert wartosc_konfiguracji('REFRESH_INTERVAL_SECONDS') == '45'


@pytest.mark.parametrize('klucz', ['priorytety_tryb_gluing', 'DEADLINE_DAY_TYPE', 'DEADLINE_DEFAULT_DAYS'])
def test_update_config_pojedynczy_odrzuca_priorytety_i_terminy(client, klucz):
    ustaw(klucz, 'przed')
    r = client.post(BASE + '/update-config', json={'config_key': klucz, 'config_value': '10'})
    assert r.status_code == 400
    dane = r.get_json()
    assert dane['success'] is False and u'Stół stanowisk' in dane['error']
    assert '/production/api/priorytety/ustawienia' in dane['error']
    assert wartosc_konfiguracji(klucz) == 'przed'


def test_update_config_pojedynczy_przyjmuje_inne(client):
    r = client.post(BASE + '/update-config', json={'config_key': 'REFRESH_INTERVAL_SECONDS', 'config_value': '40',
                                                    'config_type': 'integer'})
    assert r.status_code == 200, r.get_data()[:300]
    assert wartosc_konfiguracji('REFRESH_INTERVAL_SECONDS') == '40'


def test_zakladka_konfiguracji_bez_prod_priority_config(client):
    """DROP `prod_priority_config` w K8 nie może położyć zakładki: fikstura nie ma tej tabeli."""
    from sqlalchemy import inspect
    assert 'prod_priority_config' not in inspect(db.engine).get_table_names()
    r = client.get(BASE + '/config-tab-content')
    assert r.status_code == 200, r.get_data()[:500]
    dane = r.get_json()
    assert dane['success'] is True
    assert 'priority_configs' not in dane['data']


def test_martwe_klucze_priorytetow_usuniete_z_kodu():
    for sciezka in (PY_CONFIG_API, PY_CONFIG_SERVICE, JS_KONFIGURACJA, SZABLON_KONFIGURACJI):
        tresc = zrodlo(sciezka)
        for klucz in ('PRIORITY_RECALC_INTERVAL_HOURS', 'PRIORITY_ALGORITHM_VERSION', '_PRIORITY_SORT'):
            assert klucz not in tresc, (sciezka, klucz)


# ══ Task 5: karty „Terminy” i „Stół stanowisk” w Konfiguracji ═══════════════════════════════════════════════

def _metoda_js(js, naglowek):
    """Ciało metody klasy w config-module.js: od nagłówka do zamknięcia na wcięciu klasy."""
    poczatek = js.index(naglowek)
    return js[poczatek:js.index('\n    }\n', poczatek)]


def _karta(html, znacznik, nastepny):
    poczatek = html.index(znacznik)
    return html[poczatek:html.index(nastepny, poczatek)]


def test_karty_terminow_i_stolu_w_szablonie(client):
    html = zrodlo(SZABLON_KONFIGURACJI)
    assert u'<!-- Terminy -->' in html and u'<!-- Stół stanowisk -->' in html
    for id_pola in ('prio_deadline_default_days', 'prio_deadline_finished_days', 'prio_deadline_day_type',
                    'prio_terminy_zapisz', 'prio_blisko_terminu_dni', 'prio_min_app_version_code', 'prio_stol_zapisz'):
        assert 'id="%s"' % id_pola in html, id_pola
    assert u'Dotyczy tylko zamówień importowanych po zmianie' in html
    assert u'0 = bez bramki wersji' in html
    for klasa in ('prio-tryb', 'prio-miejsca', 'prio-jednostka', 'prio-limit'):
        assert klasa in html

    r = client.get(BASE + '/config-tab-content')
    assert r.status_code == 200, r.get_data()[:500]
    wyrenderowany = r.get_json()['html']
    import re
    from modules.production.services.station_catalog import STATION_ORDER, station_label
    assert re.findall(r'data-stanowisko="(\w+)"', wyrenderowany) == list(STATION_ORDER)
    for kod in STATION_ORDER:
        assert station_label(kod) in wyrenderowany


def test_konfiguracja_lakierni_bez_wyboru_trybu(client):
    html = client.get(BASE + '/config-tab-content').get_json()['html']
    wiersz = html[html.index('data-stanowisko="painting"'):]
    wiersz = wiersz[:wiersz.index('</tr>')]
    assert u'Lista (bez stołu)' in wiersz
    for klasa in ('prio-tryb', 'prio-miejsca', 'prio-jednostka', 'prio-limit'):
        assert klasa not in wiersz
    gluing = html[html.index('data-stanowisko="gluing"'):]
    gluing = gluing[:gluing.index('</tr>')]
    assert 'prio-tryb' in gluing and 'prio-limit' in gluing
    # JS bierze wiersze tylko z polami — wiersz Lakierni nie trafi do ciała PUT
    js = zrodlo(JS_KONFIGURACJA)
    assert "stanowiska.painting" not in js and "'painting'" not in _metoda_js(js, 'zbierzZmianyPriorytetow(karta) {')
    assert "querySelector('.prio-tryb')" in _metoda_js(js, 'zbierzZmianyPriorytetow(karta) {')


def test_skrypt_obsluguje_403_przy_wczytaniu():
    metoda = _metoda_js(zrodlo(JS_KONFIGURACJA), 'async loadPriorytetyUstawienia() {')
    assert '403' in metoda and 'disabled' in metoda
    assert "'/production/api/priorytety/ustawienia'" in zrodlo(JS_KONFIGURACJA)


def test_karty_terminow_i_stolu_poza_pending_changes():
    html = zrodlo(SZABLON_KONFIGURACJI)
    karty = _karta(html, u'<!-- Terminy -->', u'<!-- System i Debug -->')
    assert 'configChanged(' not in karty and 'resetToDefault(' not in karty
    js = zrodlo(JS_KONFIGURACJA)
    mapy = [js.split('const fieldMappings = {')[1].split('};')[0],
            _metoda_js(js, 'updateFormField(key, value) {'),
            _metoda_js(js, 'getFieldIdFromConfigKey(configKey) {')]
    for mapa in mapy:
        assert 'prio_' not in mapa


def test_skrypt_zapisuje_przez_put_ustawienia():
    js = zrodlo(JS_KONFIGURACJA)
    metoda = _metoda_js(js, 'async savePriorytetyUstawienia(karta) {')
    assert 'ADRES_USTAWIEN_PRIORYTETOW' in metoda and "method: 'PUT'" in metoda
    assert "const ADRES_USTAWIEN_PRIORYTETOW = '/production/api/priorytety/ustawienia'" in js
    assert 'this.loadPriorytetyUstawienia()' in _metoda_js(js, 'loadOriginalValuesFromDOM() {')
    assert 'window.savePriorytetyUstawienia = function' in js
    # ciało = tylko pola różne od ostatnio wczytanych
    zbierz = _metoda_js(js, 'zbierzZmianyPriorytetow(karta) {')
    assert 'this.prioStan' in zbierz and '!==' in zbierz


def test_skrypt_obsluguje_403_i_pole_bledu():
    metoda = _metoda_js(zrodlo(JS_KONFIGURACJA), 'async savePriorytetyUstawienia(karta) {')
    assert '403' in metoda and 'result.pole' in metoda and 'is-invalid' in metoda
    assert u'Tylko administrator może zmieniać ustawienia priorytetów' in metoda


def test_brak_karty_priorytety_i_deadlines():
    html = zrodlo(SZABLON_KONFIGURACJI)
    for zakazane in ('Priorytety i Deadlines', 'id="deadline_days"', 'priority_recalc', 'priority_version',
                     'config_groups.priorities'):
        assert zakazane not in html, zakazane
    js = zrodlo(JS_KONFIGURACJA)
    assert 'DEADLINE_DEFAULT_DAYS' not in js and 'deadline_days' not in js


# ══ Task 5a (karta): Konfiguracja — sekcja „Start stołów” (spec 5.8) ════════════════════════════════════════

def _sekcja_startu(html):
    return _karta(html, u'<!-- Start stołów -->', u'<!-- System i Debug -->')


def test_sekcja_start_stolow_w_szablonie(client):
    sekcja = _sekcja_startu(zrodlo(SZABLON_KONFIGURACJI))
    for id_elementu in ('prio_start_podglad', 'prio_start_odswiez', 'prio_start_przygotuj', 'prio_start_wlacz'):
        assert 'id="%s"' % id_elementu in sekcja, id_elementu
    assert u'Przygotuj stoły' in sekcja and u'Włącz stoły' in sekcja
    # kolejność kroków startu (runbook K7): podgląd → Przygotuj → poprawki → Włącz → „Rozpoczęte” na szczyt
    kroki = [u'Podgląd', u'Przygotuj stoły', u'Wyślij na stanowisko', u'Włącz stoły', u'Rozpoczęte']
    lista_krokow = sekcja[sekcja.index('<ol'):sekcja.index('</ol>')]
    pozycje = [lista_krokow.index(krok) for krok in kroki]
    assert pozycje == sorted(pozycje)
    # sekcja leży w karcie „Stół stanowisk”
    html = zrodlo(SZABLON_KONFIGURACJI)
    assert html.index(u'<!-- Stół stanowisk -->') < html.index(u'<!-- Start stołów -->') < html.index(
        u'<!-- System i Debug -->')
    assert client.get(BASE + '/config-tab-content').status_code == 200


def test_skrypt_start_stolow_podglad():
    js = zrodlo(JS_KONFIGURACJA)
    assert "const ADRES_STARTU_STOLOW = '/production/api/priorytety/start'" in js
    metoda = _metoda_js(js, 'async loadStartStolow() {')
    assert 'ADRES_STARTU_STOLOW' in metoda and 'prio_start_podglad' in metoda
    assert 'this.loadStartStolow()' in _metoda_js(js, 'loadOriginalValuesFromDOM() {')
    # teksty z bazy (numer, short_id) przez textContent — bez innerHTML
    render = _metoda_js(js, 'renderStartStolow(podglad, stanowiska) {')
    assert 'textContent' in render and 'innerHTML' not in render
    assert 'window.odswiezStartStolow = function' in js


def test_skrypt_przygotuj_stoly_post_z_potwierdzeniem():
    js = zrodlo(JS_KONFIGURACJA)
    metoda = _metoda_js(js, 'async przygotujStoly() {')
    assert 'confirm(' in metoda and "ADRES_STARTU_STOLOW + '/przygotuj'" in metoda
    assert "method: 'POST'" in metoda and '403' in metoda and 'nieudane' in metoda
    assert metoda.index('confirm(') < metoda.index('fetch(')
    assert 'this.loadStartStolow()' in metoda
    assert 'window.przygotujStoly = function' in js


def test_skrypt_wlacz_stoly_jednym_put():
    js = zrodlo(JS_KONFIGURACJA)
    metoda = _metoda_js(js, 'async wlaczStoly() {')
    assert metoda.count('fetch(') == 1
    assert 'ADRES_USTAWIEN_PRIORYTETOW' in metoda and "method: 'PUT'" in metoda
    assert 'min_app_version_code' in metoda and "tryb: 'stol'" in metoda
    assert 'STANOWISKA_STOLOW' in metoda and "getElementById('prio_min_app_version_code')" in metoda
    assert 'confirm(' in metoda and metoda.index('confirm(') < metoda.index('fetch(')
    assert '403' in metoda and 'result.pole' in metoda
    import re
    stala = re.search(r"const STANOWISKA_STOLOW = \[([^\]]*)\]", js).group(1)
    assert re.findall(r"'(\w+)'", stala) == ['cutting', 'assembly', 'gluing', 'formatting', 'edges', 'packaging']
    assert 'window.wlaczStoly = function' in js


def test_start_stolow_poza_pending_changes():
    sekcja = _sekcja_startu(zrodlo(SZABLON_KONFIGURACJI))
    assert 'configChanged(' not in sekcja and 'saveAllChanges(' not in sekcja


def test_start_stolow_403_ukrywa_akcje_admina():
    """Podgląd startu widzi każdy z dostępem do produkcji (guard), „Przygotuj” i „Włącz” tylko admin."""
    metoda = _metoda_js(zrodlo(JS_KONFIGURACJA), 'async loadPriorytetyUstawienia() {')
    assert '#prio_start_przygotuj, #prio_start_wlacz' in metoda


# ══ Task 7a (karta): pracownik odłożenia skrócony dla hali ══════════════════════════════════════════════════

def test_stoly_panelu_pracownik_krotko(app):
    """Panel pokazuje pełne imię i nazwisko, telewizor „Adam K.” (spec 6.1, 7.2) — oba pola w odłożonym kaflu."""
    kto = pracownik('Adam', 'Kowalski')
    bez_nazwiska = pracownik('Ewa', '')
    order = zam(statusy=('czeka_na_sklejanie',) * 3)
    kafel_stolu('gluing', order.products[0], odlozony=datetime(2026, 10, 5, 9, 0), postponed_by_worker_id=kto.id)
    kafel_stolu('gluing', order.products[1], odlozony=datetime(2026, 10, 5, 9, 5),
                postponed_by_worker_id=bez_nazwiska.id)
    kafel_stolu('gluing', order.products[2], odlozony=datetime(2026, 10, 5, 9, 10))

    (sklejanie,) = widok.stoly_panelu(stanowiska=['gluing'])

    assert [(k['pracownik'], k['pracownik_krotko']) for k in sklejanie['odlozone']] == [
        (u'Adam Kowalski', u'Adam K.'), (u'Ewa', u'Ewa'), (None, None)]


# ══ Poprawki po przeglądzie końcowym K4b ═══════════════════════════════════════════════════════════════════

def test_stoly_panelu_wroci_przy_dopelnieniu_z_pozycja_omijajaca(app):
    """W1 przeglądu: na Formatowaniu pozycja bez docięcia (omija stanowisko) nie czyni zamówienia niekompletnym —
    kafel zamówienia po zdjęciu wróci przy dopełnieniu, więc panel musi to powiedzieć (raport K3, D7)."""
    order = zam(statusy=('czeka_na_formatowanie', 'czeka_na_sklejanie'), numer='7601')
    order.products[1].cut_to_size = False
    db.session.commit()
    kafel_stolu('formatting', order)

    (formatowanie,) = widok.stoly_panelu(stanowiska=['formatting'])

    (kafel,) = formatowanie['stol']
    assert kafel['unit_key'] == 'o:%d' % order.id
    assert kafel['wroci_przy_dopelnieniu'] is True


def test_zakladka_odswieza_sie_tylko_gdy_widoczna():
    """D2 przeglądu: timer 120 s żyje na `window` także po przejściu na inną zakładkę panelu — bez tej osłony każde
    okno, które raz pokazało Stanowiska, odpytywałoby ciężki endpoint co 2 minuty w tle."""
    funkcja = _funkcja_js(zrodlo(SZABLON_STANOWISK), 'function refreshWorkflowData(')
    assert 'document.hidden' in funkcja
    assert "classList.contains('active')" in funkcja
    assert funkcja.index('document.hidden') < funkcja.index('loadTabContent')


def test_wlacz_stoly_ostrzega_o_niezapisanych_zmianach():
    """D7 przeglądu: po „Włącz stoły” odpowiedź serwera nadpisuje pola karty — niezapisane zmiany K/limitu/jednostki
    przepadłyby po cichu. Pytanie potwierdzające mówi o tym, zanim cokolwiek pójdzie do serwera."""
    metoda = _metoda_js(zrodlo(JS_KONFIGURACJA), 'async wlaczStoly() {')
    assert "this.zbierzZmianyPriorytetow('stol')" in metoda
    assert metoda.index("zbierzZmianyPriorytetow('stol')") < metoda.index('confirm(')
    assert u'niezapisane' in metoda


# ══ K4-poprawka-1: „Włącz stoły” przy progu 0 pokazuje odmowę serwera ═════════════════════════════════════════

def test_wlacz_stoly_przy_progu_zero_komunikat_serwera():
    """Serwer odmawia `tryb=stol` przy progu wersji 0 (400 `prog_wersji_wymagany`, pole `min_app_version_code`).
    Przycisk nie pyta wtedy „Włączyć stoły?” (odpowiedź „tak” i tak nic by nie zmieniła) i nie ma już własnego
    ostrzeżenia — pokazuje komunikat serwera i podświetla pole progu."""
    metoda = _metoda_js(zrodlo(JS_KONFIGURACJA), 'async wlaczStoly() {')
    assert u'UWAGA: próg wersji 0' not in metoda
    assert 'if (wersja !== 0) {' in metoda
    assert metoda.index('if (wersja !== 0) {') < metoda.index('confirm(') < metoda.index('fetch(')
    assert "this.showToast(result.message ||" in metoda
    assert metoda.index('this.polePriorytetu(result.pole)') < metoda.index("this.showToast(result.message ||")
    assert "'prio_min_app_version_code'" in zrodlo(JS_KONFIGURACJA)
    # Przegląd: przy zastanym stole na sześciu stanowiskach i progu 0 serwer przepuszcza zapis bez zmian, a odpowiedź
    # nadpisuje pola karty — ostrzeżenie o niezapisanych zmianach obowiązuje też przy progu 0.
    assert metoda.index("this.zbierzZmianyPriorytetow('stol')") < metoda.index('if (wersja !== 0) {')
    assert '} else if (ostrzezenie && !confirm(ostrzezenie)) {' in metoda


def test_stoly_panelu_pakowanie_bez_sposobu_dostawy_wroci_i_liczy_sie(app):
    """Pakowanie bez sposobu dostawy jest zwykłym kandydatem (spec 5.1 po logistyce 4.6): kafel zdjęty ze stołu
    wraca przy dopełnieniu, a zamówienie w kolejce liczy się do `kolejka_dalej` (dawniej oba pomijane)."""
    pilne = zam(statusy=('czeka_na_pakowanie',), gwiazdki=5, numer='7601')
    zwykle = zam(statusy=('czeka_na_pakowanie',), numer='7602')
    for order, rung in ((pilne, indeks_widoczny('stars', 5)), (zwykle, indeks_widoczny('stars', 0))):
        order.priority_rung, order.priority_rank = rung, 1 if order is pilne else 2
    db.session.commit()
    kafel_stolu('packaging', pilne)

    (pakowanie,) = widok.stoly_panelu(stanowiska=['packaging'])

    assert pilne.override_delivery_method is None and zwykle.override_delivery_method is None
    assert [(k['unit_key'], k['wroci_przy_dopelnieniu']) for k in pakowanie['stol']] == [('o:%d' % pilne.id, True)]
    assert pakowanie['kolejka_dalej'] == 1
