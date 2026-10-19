# -*- coding: utf-8 -*-
"""GET /api/mobile/manager/orders — lista zamówień i statystyki tabletu kierownika (kontrakt §5.1)."""
from datetime import datetime, timedelta

import pytest
from sqlalchemy import event

from extensions import db
from modules.production.kierownik.services import biala_lista
from modules.production.logistics.models import Route, RouteStop
from modules.production.models import get_local_now
from tests.kierownik_pomocnicze import API, ENDPOINTY_KIEROWNIKA, naglowki, tablet_kierownika
from tests.logistyka_fixtures import app, client, zamowienie  # noqa: F401

URL = API + '/orders'
ZAMKNIETE = datetime(2026, 9, 20, 12, 0, 0)


def test_trasa_jest_na_liscie_endpointow():
    assert ('GET', '/orders') in ENDPOINTY_KIEROWNIKA


@pytest.fixture()
def tablet(app):
    return tablet_kierownika()


def _pobierz(client, tablet, **parametry):
    device, kierownik = tablet
    r = client.get(URL, query_string=parametry, headers=naglowki(device, kierownik))
    return r


def _lista(client, tablet, **parametry):
    r = _pobierz(client, tablet, **parametry)
    assert r.status_code == 200, r.get_data()[:500]
    return r.get_json()


def _numery(odp):
    return [z['numer'] for z in odp['zamowienia']]


def _zamkniete(numer, bl_id, **kolumny):
    """Spakowane i zamknięte w Logistyce — archiwum."""
    return zamowienie(statusy=('spakowane',), numer_wewnetrzny=numer, bl_id=bl_id,
                      logistics_closed_at=kolumny.pop('logistics_closed_at', ZAMKNIETE), **kolumny)


def _zbior_mieszany():
    """(w produkcji, anulowane w całości, zamknięte w Logistyce, spakowane ale otwarte w Logistyce)."""
    w_produkcji = zamowienie(statusy=('czeka_na_wyciecie',), numer_wewnetrzny='26/00001', bl_id=900001)
    anulowane = zamowienie(statusy=('anulowane', 'anulowane'), numer_wewnetrzny='26/00002', bl_id=900002)
    zamkniete = _zamkniete('26/00003', 900003)
    otwarte = zamowienie(statusy=('spakowane',), numer_wewnetrzny='26/00004', bl_id=900004)
    return w_produkcji, anulowane, zamkniete, otwarte


# --- widoki -----------------------------------------------------------------------------------------------------

def test_lista_active_bez_archiwum(tablet, client):
    _zbior_mieszany()
    odp = _lista(client, tablet)   # domyślnie active
    assert odp['view'] == 'active'
    # Spakowane, ale jeszcze otwarte w Logistyce zostaje w bieżących; zamknięte i anulowane w całości nie.
    assert sorted(_numery(odp)) == ['26/00001', '26/00004']
    assert sorted(_numery(_lista(client, tablet, view='archive'))) == ['26/00002', '26/00003']


def test_lista_all_ma_oba_od_najnowszych(tablet, client):
    w_produkcji, anulowane, zamkniete, otwarte = _zbior_mieszany()
    odp = _lista(client, tablet, view='all')
    assert _numery(odp) == ['26/00004', '26/00003', '26/00002', '26/00001']   # id malejąco
    # Data zakończenia jest tylko przy zamówieniach archiwalnych.
    wg_numeru = {z['numer']: z for z in odp['zamowienia']}
    assert wg_numeru['26/00003']['zakonczono'] == ZAMKNIETE.isoformat()
    assert wg_numeru['26/00001']['zakonczono'] is None and wg_numeru['26/00004']['zakonczono'] is None


def test_active_wedlug_rangi_bez_rangi_na_koncu(tablet, client):
    drugie = zamowienie(statusy=('czeka_na_wyciecie',), numer_wewnetrzny='26/00011', bl_id=900011,
                        priority_rank=2)
    bez_rangi = zamowienie(statusy=('czeka_na_wyciecie',), numer_wewnetrzny='26/00012', bl_id=900012)
    pierwsze = zamowienie(statusy=('czeka_na_wyciecie',), numer_wewnetrzny='26/00013', bl_id=900013,
                          priority_rank=1)
    odp = _lista(client, tablet)
    assert _numery(odp) == ['26/00013', '26/00011', '26/00012']
    assert [z['ranga'] for z in odp['zamowienia']] == [1, 2, None]


def test_archiwum_od_najswiezej_zakonczonych_bez_rangi(tablet, client):
    starsze = _zamkniete('26/00021', 900021, logistics_closed_at=datetime(2026, 9, 1, 8, 0, 0), priority_rank=7)
    nowsze = _zamkniete('26/00022', 900022, logistics_closed_at=datetime(2026, 9, 5, 8, 0, 0))
    odp = _lista(client, tablet, view='archive')
    assert _numery(odp) == ['26/00022', '26/00021']
    assert [z['ranga'] for z in odp['zamowienia']] == [None, None]   # w archiwum bez miejsca w kolejce


# --- kształt zamówienia -----------------------------------------------------------------------------------------

def test_ksztalt_zamowienia(tablet, client):
    dzis = get_local_now().date()
    z = zamowienie('transport_woodpower', statusy=('czeka_na_formatowanie', 'czeka_na_wyciecie', 'anulowane'),
                   numer_wewnetrzny='26/00031', bl_id=900031, quote_number='W/2026/0912', order_source='shop',
                   priority_stars=2, priority_rank=14, delivery_fullname='Jan Kowalski',
                   delivery_company='Kowalski Meble Sp. z o.o.', miasto='Rzeszów')
    p1, p2, p3 = sorted(z.products, key=lambda p: p.product_sequence_in_order)
    p1.parsed_length_cm, p1.parsed_width_cm, p1.parsed_thickness_cm = 240, 65, 4
    p1.volume_m3, p1.quantity, p1.deadline_date = 0.0624, 1, dzis + timedelta(days=5)
    p2.deadline_date = dzis + timedelta(days=9)
    p3.deadline_date = dzis + timedelta(days=1)   # anulowana nie wyciąga terminu
    p3.quantity = 3
    p3.volume_m3 = 0.5
    p2.original_product_id = p1.id
    trasa = Route(name='Rzeszów czw.', date_from=dzis, date_to=dzis, status='zatwierdzona')
    db.session.add(trasa)
    db.session.flush()
    db.session.add(RouteStop(route_id=trasa.id, order_id=z.id, position=1))
    db.session.commit()

    odp = _lista(client, tablet)
    assert len(odp['zamowienia']) == 1
    w = odp['zamowienia'][0]
    assert w['order_id'] == z.id and w['numer'] == '26/00031' and w['baselinker_order_id'] == 900031
    assert w['quote_number'] == 'W/2026/0912' and w['zrodlo'] == 'Sklep'
    assert w['klient'] == {'nazwa': 'Jan Kowalski', 'firma': 'Kowalski Meble Sp. z o.o.', 'miasto': 'Rzeszów'}
    assert w['sposob'] == 'transport_woodpower' and w['sposob_etykieta'] == 'Transport WoodPower'
    assert w['termin'] == (dzis + timedelta(days=5)).isoformat() and w['dni_do_terminu'] == 5
    assert w['gwiazdki'] == 2 and w['ranga'] == 14
    assert w['status_zbiorczy']['status'] is None and w['status_zbiorczy']['etykieta'] == 'Różne (0/3)'
    assert w['etap_logistyki'] == {'kod': 'w_produkcji', 'etykieta': 'W produkcji'}
    assert w['trasa'] == {'id': trasa.id, 'nazwa': 'Rzeszów czw.', 'status': 'zatwierdzona'}
    assert w['zakonczono'] is None
    # Anulowana pozycja liczy się w `pozycji`, ale nie w `sztuk` i `m3`.
    assert w['pozycji'] == 3
    assert w['sztuk'] == 1 + 2
    assert w['m3'] == round(0.0624 * 1 + 0.024 * 2, 4)
    pozycje = w['pozycje']
    assert [p['short_product_id'] for p in pozycje] == [p1.short_product_id, p2.short_product_id, p3.short_product_id]
    assert pozycje[0] == {
        'product_id': p1.id, 'short_product_id': p1.short_product_id, 'nazwa': 'Blat dębowy 100x60x4',
        'wymiary': {'dlugosc_cm': 240.0, 'szerokosc_cm': 65.0, 'grubosc_cm': 4.0}, 'sztuk': 1,
        'status': 'czeka_na_formatowanie', 'status_etykieta': 'Czeka na formatowanie', 'm3': 0.0624,
        'dorobka': False}
    assert pozycje[1]['dorobka'] is True
    assert pozycje[1]['wymiary'] == {'dlugosc_cm': None, 'szerokosc_cm': None, 'grubosc_cm': None}


def test_status_zbiorczy_jeden_status_i_etap_po_spakowaniu(tablet, client):
    zamowienie(statusy=('czeka_na_krawedzie', 'czeka_na_krawedzie'), numer_wewnetrzny='26/00041', bl_id=900041)
    zamowienie(statusy=('spakowane',), numer_wewnetrzny='26/00042', bl_id=900042)
    wg_numeru = {z['numer']: z for z in _lista(client, tablet)['zamowienia']}
    assert wg_numeru['26/00041']['status_zbiorczy'] == {'status': 'czeka_na_krawedzie',
                                                        'etykieta': 'Czeka na krawędzie'}
    assert wg_numeru['26/00042']['status_zbiorczy'] == {'status': 'spakowane', 'etykieta': 'Spakowane'}
    assert wg_numeru['26/00042']['etap_logistyki']['kod'] == 'spakowane'
    assert wg_numeru['26/00042']['trasa'] is None


# --- szukanie i filtry ------------------------------------------------------------------------------------------

def test_search_po_numerze_base_i_firmie(tablet, client):
    zamowienie(statusy=('czeka_na_wyciecie',), numer_wewnetrzny='26/00051', bl_id=41188237,
               delivery_company='Kowalski Meble Sp. z o.o.')
    zamowienie(statusy=('czeka_na_wyciecie',), numer_wewnetrzny='26/00052', bl_id=900052,
               delivery_fullname='Anna Nowak')
    zamowienie(statusy=('czeka_na_wyciecie',), numer_wewnetrzny='26/00053', bl_id=900053)
    assert _numery(_lista(client, tablet, search='1188')) == ['26/00051']        # numer Base. jako tekst
    assert _numery(_lista(client, tablet, search='kowalski meb')) == ['26/00051']  # firma, wielkość liter bez znaczenia
    assert _numery(_lista(client, tablet, search='NOWAK')) == ['26/00052']       # imię i nazwisko odbiorcy
    assert _numery(_lista(client, tablet, search='26/00053')) == ['26/00053']    # numer wewnętrzny
    assert _numery(_lista(client, tablet, search='nie ma takiego')) == []
    # Znaki wieloznaczne LIKE są zwykłymi znakami.
    assert _numery(_lista(client, tablet, search='%')) == []


def test_search_po_pozycji_i_zwraca_cale_zamowienie(tablet, client):
    z = zamowienie(statusy=('czeka_na_wyciecie', 'czeka_na_krawedzie'), numer_wewnetrzny='26/00054', bl_id=900054)
    p1, p2 = sorted(z.products, key=lambda p: p.product_sequence_in_order)
    p2.original_product_name = 'Parapet jesionowy'
    db.session.commit()
    zamowienie(statusy=('czeka_na_wyciecie',), numer_wewnetrzny='26/00055', bl_id=900055)
    odp = _lista(client, tablet, search='jesionowy')
    assert _numery(odp) == ['26/00054']
    assert odp['zamowienia'][0]['pozycji'] == 2   # pasuje jedna pozycja, ale lista pokazuje całe zamówienie
    assert _numery(_lista(client, tablet, search=p2.short_product_id)) == ['26/00054']


def test_filtr_status(tablet, client):
    zamowienie(statusy=('czeka_na_wyciecie', 'wstrzymane'), numer_wewnetrzny='26/00061', bl_id=900061)
    zamowienie(statusy=('czeka_na_wyciecie',), numer_wewnetrzny='26/00062', bl_id=900062)
    odp = _lista(client, tablet, status='wstrzymane')
    assert _numery(odp) == ['26/00061']
    assert odp['zamowienia'][0]['pozycji'] == 2   # całe zamówienie, nie tylko pozycje w tym statusie
    r = _pobierz(client, tablet, status='nie_ma_takiego')
    assert r.status_code == 400 and r.get_json()['error'] == 'dane_niepoprawne' and r.get_json()['message']


@pytest.mark.parametrize('parametry', [
    {'view': 'wszystko'}, {'page': '0'}, {'page': 'x'}, {'per_page': '0'}, {'per_page': '101'},
    {'per_page': 'abc'}, {'view': 'archive', 'completed_from': '2026-13-40'},
    {'view': 'archive', 'completed_to': 'wczoraj'},
    {'view': 'archive', 'completed_from': '2026-09-10', 'completed_to': '2026-09-01'},
])
def test_zle_parametry_400(tablet, client, parametry):
    r = _pobierz(client, tablet, **parametry)
    assert r.status_code == 400, r.get_data()[:300]
    assert r.get_json()['error'] == 'dane_niepoprawne' and r.get_json()['message']


# --- statystyki -------------------------------------------------------------------------------------------------

def test_statystyki_na_calym_zbiorze_nie_stronie(tablet, client):
    for i in range(5):
        zamowienie(statusy=('czeka_na_wyciecie', 'czeka_na_krawedzie'), numer_wewnetrzny='26/%05d' % (70 + i),
                   bl_id=900070 + i)
    odp = _lista(client, tablet, per_page=1)
    assert len(odp['zamowienia']) == 1
    s = odp['statystyki']
    assert s['zamowien'] == 5 and s['pozycji'] == 10 and s['sztuk'] == 20
    assert s['m3'] == round(10 * 2 * 0.024, 4)
    assert s['wg_statusu'] == {
        'czeka_na_wyciecie': {'pozycji': 5, 'sztuk': 10, 'm3': 0.24},
        'czeka_na_krawedzie': {'pozycji': 5, 'sztuk': 10, 'm3': 0.24},
    }
    assert odp['strona'] == {'page': 1, 'per_page': 1, 'lacznie': 5, 'stron': 5}
    assert 'sredni_czas_realizacji_dni' not in s   # tylko archiwum


def test_stronicowanie_i_limity(tablet, client):
    for i in range(7):
        zamowienie(statusy=('czeka_na_wyciecie',), numer_wewnetrzny='26/%05d' % (80 + i), bl_id=900080 + i,
                   priority_rank=i + 1)
    druga = _lista(client, tablet, per_page=3, page=2)
    assert _numery(druga) == ['26/00083', '26/00084', '26/00085']
    assert druga['strona'] == {'page': 2, 'per_page': 3, 'lacznie': 7, 'stron': 3}
    ostatnia = _lista(client, tablet, per_page=3, page=3)
    assert _numery(ostatnia) == ['26/00086']
    poza = _lista(client, tablet, per_page=3, page=9)
    assert poza['zamowienia'] == [] and poza['strona']['lacznie'] == 7
    assert _lista(client, tablet, per_page=100)['strona']['per_page'] == 100
    assert _lista(client, tablet)['strona']['per_page'] == 50   # domyślnie


def test_pusty_zbior(tablet, client):
    odp = _lista(client, tablet)
    assert odp['zamowienia'] == [] and odp['statystyki']['zamowien'] == 0
    assert odp['statystyki']['wg_statusu'] == {}
    assert odp['statystyki']['sztuk_do_spakowania'] == 0 and odp['statystyki']['m3_do_spakowania'] == 0
    assert odp['strona'] == {'page': 1, 'per_page': 50, 'lacznie': 0, 'stron': 1}


def test_anulowane_w_pozycjach_nie_w_m3(tablet, client):
    z = zamowienie(statusy=('czeka_na_wyciecie', 'anulowane'), numer_wewnetrzny='26/00091', bl_id=900091)
    odp = _lista(client, tablet)
    s = odp['statystyki']
    assert s['pozycji'] == 2 and s['sztuk'] == 2 and s['m3'] == 0.048
    assert s['wg_statusu']['anulowane'] == {'pozycji': 1, 'sztuk': 0, 'm3': 0.0}
    assert s['wg_statusu']['czeka_na_wyciecie'] == {'pozycji': 1, 'sztuk': 2, 'm3': 0.048}
    w = odp['zamowienia'][0]
    assert (w['pozycji'], w['sztuk'], w['m3']) == (2, 2, 0.048)
    assert sum(v['sztuk'] for v in s['wg_statusu'].values()) == s['sztuk']


@pytest.fixture()
def z_webem(app, monkeypatch):
    """Dokłada do apki panel WWW produkcji, żeby porównać liczby z zakładką Produkty."""
    from modules.production.routers.api import api_bp, products_api
    monkeypatch.setattr(products_api, 'render_template', lambda *a, **k: '')
    app.register_blueprint(api_bp, url_prefix='/production/api')
    return app


def test_statystyki_zgodne_z_webem(z_webem, tablet, client):
    z1 = zamowienie(statusy=('czeka_na_wyciecie', 'czeka_na_krawedzie', 'anulowane'),
                    numer_wewnetrzny='26/00101', bl_id=900101)
    z2 = zamowienie(statusy=('spakowane', 'czeka_na_formatowanie'), numer_wewnetrzny='26/00102', bl_id=900102)
    z3 = zamowienie(statusy=('zweryfikowane',), numer_wewnetrzny='26/00103', bl_id=900103)
    _zamkniete('26/00104', 900104)   # archiwum — poza aktywnymi w obu miejscach
    # Częściowo spakowana pozycja: liczą się tylko niespakowane sztuki.
    czesciowa = sorted(z1.products, key=lambda p: p.product_sequence_in_order)[0]
    czesciowa.quantity = 5
    czesciowa.quantity_done_packaging = 2
    db.session.commit()

    web = client.get('/production/api/products-tab-content?view=active').get_json()
    assert web['success'] is True, web
    stats_web = web['initial_data']['stats']
    s = _lista(client, tablet)['statystyki']
    assert s['sztuk_do_spakowania'] == stats_web['total_quantity']
    assert s['m3_do_spakowania'] == pytest.approx(stats_web['total_volume'], abs=1e-4)
    assert s['sztuk_do_spakowania'] == 3 + 2 + 2   # (5-2) + krawędzie 2 + formatowanie 2
    # Archiwalne zamówienie nie wchodzi do żadnego z liczników.
    assert _lista(client, tablet, view='archive')['statystyki'].get('sztuk_do_spakowania') is None


def test_archiwum_zakres_dat_i_sredni_czas(tablet, client):
    utworzone = datetime(2026, 8, 20, 8, 0, 0)

    def zamkniete(numer, bl_id, zamkniecie, utworzono, **kolumny):
        z = _zamkniete(numer, bl_id, logistics_closed_at=zamkniecie, **kolumny)
        for p in z.products:
            p.created_at = utworzono
        db.session.commit()
        return z

    zamkniete('26/00111', 900111, datetime(2026, 9, 1, 8, 0, 0), utworzone)                      # 12 dni
    zamkniete('26/00112', 900112, datetime(2026, 9, 10, 23, 30, 0), utworzone)                   # 21,6 dnia
    zamkniete('26/00113', 900113, datetime(2026, 9, 25, 8, 0, 0), utworzone)                     # poza zakresem
    odp = _lista(client, tablet, view='archive', completed_from='2026-09-01', completed_to='2026-09-10')
    assert sorted(_numery(odp)) == ['26/00111', '26/00112']   # obie granice włącznie, do końca dnia 10.09
    assert odp['statystyki']['zamowien'] == 2
    sredni = odp['statystyki']['sredni_czas_realizacji_dni']
    assert sredni == round((round(12.0, 1) + round((datetime(2026, 9, 10, 23, 30) - utworzone).total_seconds()
                                                   / 86400, 1)) / 2, 1)
    assert 'sztuk_do_spakowania' not in odp['statystyki']
    # Bez zakresu — wszystkie trzy, a średnia z trzech.
    wszystkie = _lista(client, tablet, view='archive')
    assert wszystkie['statystyki']['zamowien'] == 3
    # Filtr szukania zawęża też średnią.
    zawezone = _lista(client, tablet, view='archive', search='26/00113')
    assert _numery(zawezone) == ['26/00113'] and zawezone['statystyki']['sredni_czas_realizacji_dni'] == 36.0


# --- dane wrażliwe ----------------------------------------------------------------------------------------------

def test_brak_kwot_i_kontaktow(tablet, client):
    z = zamowienie(statusy=('czeka_na_wyciecie',), numer_wewnetrzny='26/00121', bl_id=900121,
                   client_email='tajny@klient.pl', client_phone='600700800', shipping_price=45.5,
                   delivery_company='Firma')
    for p in z.products:
        p.total_value_net = 1234.56
        p.unit_price_net = 617.28
    db.session.commit()
    for widok in ('active', 'all', 'archive'):
        r = _pobierz(client, tablet, view=widok)
        assert r.status_code == 200
        assert biala_lista.zakazane_w(r.get_json()) == []
        tekst = r.get_data(as_text=True)
        for sekret in ('tajny@klient.pl', '600700800', '1234.56', '617.28', 'ul. Testowa'):
            assert sekret not in tekst


def test_inne_stanowisko_i_zwykly_pracownik_odmowa(app, client):
    from modules.production.models import ProductionWorker
    device, _k = tablet_kierownika()
    zwykly = ProductionWorker(first_name='Piotr', last_name='Zwykły', is_active=True, is_manager=False)
    db.session.add(zwykly)
    db.session.commit()
    r = client.get(URL, headers=naglowki(device, zwykly))
    assert r.status_code == 403 and r.get_json()['error'] == 'not_a_manager'
    assert client.get(URL, headers=naglowki(device)).get_json()['error'] == 'worker_required'


# --- pamięć podręczna -------------------------------------------------------------------------------------------

def test_etag_304(tablet, client):
    zamowienie(statusy=('czeka_na_wyciecie',), numer_wewnetrzny='26/00131', bl_id=900131)
    device, kierownik = tablet
    pierwsza = client.get(URL, headers=naglowki(device, kierownik))
    assert pierwsza.status_code == 200
    etag = pierwsza.headers['ETag']
    assert etag.startswith('W/"kier-zam:')
    assert pierwsza.headers['Cache-Control'] == 'private, max-age=15'

    naglowek = naglowki(device, kierownik)
    naglowek['If-None-Match'] = etag
    drugia = client.get(URL, headers=naglowek)
    assert drugia.status_code == 304 and drugia.get_data() == b''
    assert drugia.headers['ETag'] == etag

    # Inne parametry — inny ETag, więc stary nie pasuje.
    inna = client.get(URL, query_string={'per_page': 10}, headers=naglowek)
    assert inna.status_code == 200 and inna.headers['ETag'] != etag

    # Zmiana w pozycji unieważnia ETag.
    z = zamowienie(statusy=('czeka_na_wyciecie',), numer_wewnetrzny='26/00132', bl_id=900132)
    po_zmianie = client.get(URL, headers=naglowek)
    assert po_zmianie.status_code == 200 and po_zmianie.headers['ETag'] != etag


def test_etag_zmienia_sie_po_zmianie_statusu_pozycji(tablet, client):
    z = zamowienie(statusy=('czeka_na_wyciecie',), numer_wewnetrzny='26/00133', bl_id=900133)
    device, kierownik = tablet
    etag = client.get(URL, headers=naglowki(device, kierownik)).headers['ETag']
    z.products[0].current_status = 'wstrzymane'
    z.products[0].updated_at = datetime.now() + timedelta(seconds=5)
    db.session.commit()
    nowy = client.get(URL, headers=naglowki(device, kierownik))
    assert nowy.headers['ETag'] != etag
    assert nowy.get_json()['zamowienia'][0]['pozycje'][0]['status'] == 'wstrzymane'


# --- zapytania --------------------------------------------------------------------------------------------------

def _zapytania_listy(client, tablet, **parametry):
    device, kierownik = tablet
    naglowek = naglowki(device, kierownik)
    zapytania = []

    def zapisz(conn, cursor, statement, parameters, context, executemany):
        zapytania.append(statement)

    event.listen(db.engine, 'before_cursor_execute', zapisz)
    try:
        r = client.get(URL, query_string=parametry, headers=naglowek)
    finally:
        event.remove(db.engine, 'before_cursor_execute', zapisz)
    assert r.status_code == 200, r.get_data()[:300]
    return len(zapytania), r.get_json()


def _dodaj_zamowienia(od, do):
    dzis = get_local_now().date()
    for i in range(od, do):
        z = zamowienie(statusy=('czeka_na_wyciecie', 'czeka_na_krawedzie', 'spakowane'),
                       numer_wewnetrzny='26/%05d' % (1000 + i), bl_id=910000 + i, priority_rank=i,
                       delivery_company='Firma %d' % i)
        trasa = Route(name='Trasa %d' % i, date_from=dzis, date_to=dzis, status='robocza')
        db.session.add(trasa)
        db.session.flush()
        db.session.add(RouteStop(route_id=trasa.id, order_id=z.id, position=1))
        _zamkniete('26/%05d' % (3000 + i), 920000 + i)
    db.session.commit()


@pytest.mark.parametrize('widok', ['active', 'archive', 'all'])
def test_bez_n_plus_1(tablet, client, widok):
    _dodaj_zamowienia(0, 12)
    malo, odp_malo = _zapytania_listy(client, tablet, view=widok, per_page=50)
    _dodaj_zamowienia(12, 50)
    duzo, odp_duzo = _zapytania_listy(client, tablet, view=widok, per_page=50)
    assert len(odp_duzo['zamowienia']) > len(odp_malo['zamowienia'])
    assert duzo == malo, 'liczba zapytań rośnie z liczbą zamówień (%d -> %d)' % (malo, duzo)
    assert duzo <= 16
