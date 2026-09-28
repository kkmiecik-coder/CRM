# -*- coding: utf-8 -*-
"""
Poprawki backendu po przeglądzie całej gałęzi logistyki (28.09.2026). Punkt przeglądu
(I1, M3, …) w nagłówku każdej sekcji.
"""
import re
from datetime import datetime

import pytest
from sqlalchemy import event, text
from sqlalchemy.orm.exc import StaleDataError

from extensions import db
from modules.production.logistics import sposoby as s
from modules.production.logistics.models import LogisticsLog, OrderGeo
from modules.production.logistics.services import (
    bl_sync, delivery, geocoding, routes, routing,
)
from modules.production.models import ProductionOrder
from tests.logistyka_fixtures import BASE, app, client, zamowienie  # noqa: F401


@pytest.fixture(autouse=True)
def bez_tla(monkeypatch):
    """Bez wysyłki do Base. i bez wątków w tle — testy sprawdzają sam zapis."""
    monkeypatch.setattr(bl_sync, 'po_zmianie', lambda ids: None)
    monkeypatch.setattr(bl_sync, 'uruchom_w_tle', lambda app_: True)
    monkeypatch.setattr(geocoding, 'uruchom_w_tle', lambda app_: True)


# ── I1: zapis zamówienia z panelu = commit → blokada tras → dopiero odczyt ───

_ODCZYT_ZAMOWIEN = re.compile(r'^SELECT\b.*\bFROM PROD_ORDERS\b')


@pytest.fixture()
def dziennik(app, monkeypatch):
    """
    Zdarzenia żądania w kolejności: 'commit' (db.session.commit zakończony),
    'blokada' (wejście w routes.zablokuj_trasy), 'odczyt_zamowienia' (SELECT … FROM
    prod_orders wysłany do bazy) i 'sql' (każde inne zapytanie). SQLite nie odtworzy
    migawki REPEATABLE READ z MySQL, więc przypinamy samą kolejność.
    """
    zdarzenia = []
    oryg_commit = db.session.commit
    oryg_blokada = routes.zablokuj_trasy

    def commit():
        wynik = oryg_commit()
        zdarzenia.append('commit')
        return wynik

    def blokada(route=None):
        zdarzenia.append('blokada')
        return oryg_blokada(route)

    def nasluch(conn, cursor, statement, parameters, context, executemany):
        tekst = ' '.join(statement.upper().split())
        zdarzenia.append('odczyt_zamowienia' if _ODCZYT_ZAMOWIEN.search(tekst) else 'sql')

    monkeypatch.setattr(db.session, 'commit', commit)
    monkeypatch.setattr(routes, 'zablokuj_trasy', blokada)
    silnik = db.engine
    event.listen(silnik, 'before_cursor_execute', nasluch)
    yield zdarzenia
    event.remove(silnik, 'before_cursor_execute', nasluch)


def _sprawdz_kolejnosc(dziennik):
    zdarzenia = [z for z in dziennik if z != 'sql']
    assert zdarzenia[:3] == ['commit', 'blokada', 'odczyt_zamowienia'], dziennik
    # Między commitem a blokadą ani jednego zapytania: każdy zwykły SELECT (także
    # dociągnięcie wygaszonego atrybutu ORM) utworzyłby migawkę jeszcze przed blokadą.
    assert dziennik[dziennik.index('commit') + 1] == 'blokada', dziennik


def _sposob(client, oid):
    return client.post(BASE + '/orders/delivery-method', json={'order_ids': [oid], 'sposob': s.TRANSPORT})


def _wydanie(client, oid):
    return client.post(BASE + '/orders/%d/handed-over' % oid)


def _adres(client, oid):
    return client.put(BASE + '/orders/%d/address' % oid,
                      json={'adres': 'Nowa 1', 'kod': '30-001', 'miasto': 'Kraków'})


@pytest.mark.parametrize('zadanie, kolumny', [
    (_sposob, {}),
    (_wydanie, {'sposob': s.ODBIOR, 'statusy': ('spakowane',)}),
    (_adres, {}),
], ids=['sposob-dostawy', 'wydane-klientowi', 'adres'])
def test_i1_zapis_commit_blokada_potem_odczyt_zamowienia(client, app, dziennik, zadanie, kolumny):
    """I1: migawka REPEATABLE READ powstaje przy pierwszym zwykłym odczycie transakcji
    (w aplikacji już w before_request) — zapis zaczyna transakcję od nowa, bierze blokadę
    tras i dopiero wtedy czyta zamówienie, więc widzi zmiany poprzedniego piszącego."""
    with app.app_context():
        oid = zamowienie(**kolumny).id
    dziennik.clear()
    r = zadanie(client, oid)
    assert r.status_code == 200, r.get_json()
    _sprawdz_kolejnosc(dziennik)


def test_i1_hurt_kilku_zamowien_tez_zaczyna_od_commitu_i_blokady(client, app, dziennik):
    with app.app_context():
        ids = [zamowienie().id, zamowienie().id]
    dziennik.clear()
    r = client.post(BASE + '/orders/delivery-method', json={'order_ids': ids, 'sposob': s.KURIER})
    assert r.status_code == 200 and sorted(r.get_json()['zmienione']) == sorted(ids)
    _sprawdz_kolejnosc(dziennik)


def test_i1_wydane_klientowi_bierze_blokade_tras(client, app, monkeypatch):
    """I1: „Wydane klientowi” brało decyzję bez blokady — na stanie sprzed równoległej
    zmiany sposobu (np. na kuriera z przepakowaniem) mogło wydać i zamknąć zamówienie."""
    wywolania = []
    oryginal = routes.zablokuj_trasy

    def podglad(route=None):
        wywolania.append(route)
        return oryginal(route)

    monkeypatch.setattr(routes, 'zablokuj_trasy', podglad)
    with app.app_context():
        oid = zamowienie(sposob=s.ODBIOR, statusy=('spakowane',)).id
    r = client.post(BASE + '/orders/%d/handed-over' % oid)
    assert r.status_code == 200 and r.get_json()['order']['wydane'] is not None
    assert wywolania == [None]


def test_i1_wydanie_nieznanego_zamowienia_to_dalej_404(client):
    assert client.post(BASE + '/orders/999999/handed-over').status_code == 404


@pytest.mark.parametrize('zadanie', [
    lambda c, oid: c.post(BASE + '/orders/delivery-method', json={'order_ids': [], 'sposob': s.KURIER}),
    lambda c, oid: c.post(BASE + '/orders/delivery-method', json=[1, 2]),
    lambda c, oid: c.put(BASE + '/orders/%d/address' % oid, json=[1, 2]),
], ids=['pusty-hurt', 'hurt-lista', 'adres-lista'])
def test_i1_zle_cialo_odrzucone_przed_commitem_i_blokada(client, app, dziennik, zadanie):
    """Walidacja ciała żądania idzie PRZED pomocnikiem — złe dane nie biorą blokady tras."""
    with app.app_context():
        oid = zamowienie().id
    dziennik.clear()
    assert zadanie(client, oid).status_code == 422
    assert 'commit' not in dziennik and 'blokada' not in dziennik


# ── M3: sposób dostawy przy utworzonej przesyłce ────────────────────────────

KOMUNIKAT_PRZESYLKI = u'ma już utworzoną przesyłkę'


@pytest.mark.parametrize('przesylka', [{'shipping_package_id': 555},
                                       {'shipping_tracking_number': '000123'}],
                         ids=['paczka', 'numer-nadania'])
@pytest.mark.parametrize('nowy', [s.ODBIOR, s.TRANSPORT])
def test_m3_zmiana_sposobu_zamowienia_z_przesylka_to_409(app, przesylka, nowy):
    """M3: kurier z nadaną przesyłką → odbiór dawał w Base. 149777 „Czeka na odbiór”."""
    with app.app_context():
        order = zamowienie(sposob=s.KURIER, statusy=('spakowane',),
                           logistics_closed_at=datetime(2026, 9, 20), **przesylka)
        with pytest.raises(delivery.LogistykaBlad) as blad:
            delivery.ustaw_sposob_dostawy(order, nowy)
        assert blad.value.status == 409
        assert blad.value.komunikat == (
            u'Zamówienie {} ma już utworzoną przesyłkę — sposób dostawy zmień u kuriera '
            u'i w Base.'.format(order.internal_order_number))
        assert order.override_delivery_method == s.KURIER
        assert order.bl_status_pending_id is None and order.repack_required is False
        assert order.logistics_closed_at == datetime(2026, 9, 20)
        assert LogisticsLog.query.filter_by(order_id=order.id).count() == 0


def test_m3_cofniecie_do_nie_ustawiono_przy_przesylce_to_409(app):
    with app.app_context():
        order = zamowienie(sposob=s.KURIER, statusy=('czeka_na_pakowanie',), shipping_package_id=7)
        with pytest.raises(delivery.LogistykaBlad) as blad:
            delivery.ustaw_sposob_dostawy(order, s.BRAK)
        assert blad.value.status == 409 and KOMUNIKAT_PRZESYLKI in blad.value.komunikat
        assert order.override_delivery_method == s.KURIER


def test_m3_ten_sam_sposob_przy_przesylce_to_dalej_no_op(app):
    with app.app_context():
        order = zamowienie(sposob=s.KURIER, statusy=('spakowane',),
                           shipping_tracking_number='000123')
        assert delivery.ustaw_sposob_dostawy(order, s.KURIER) == {
            'zmieniono': False, 'przepakowanie': False, 'usunieto_z_trasy': None}


def test_m3_hurt_odmowa_przesylki_w_bledach_reszta_zmieniona(client, app):
    with app.app_context():
        ok = zamowienie(sposob=s.KURIER, statusy=('czeka_na_pakowanie',)).id
        z_przesylka = zamowienie(sposob=s.KURIER, statusy=('spakowane',),
                                 shipping_package_id=555).id
    r = client.post(BASE + '/orders/delivery-method',
                    json={'order_ids': [ok, z_przesylka], 'sposob': s.ODBIOR})
    dane = r.get_json()
    assert r.status_code == 200 and dane['zmienione'] == [ok]
    assert [b['order_id'] for b in dane['bledy']] == [z_przesylka]
    assert KOMUNIKAT_PRZESYLKI in dane['bledy'][0]['komunikat']
    with app.app_context():
        order = ProductionOrder.query.get(z_przesylka)
        assert order.override_delivery_method == s.KURIER and order.bl_status_pending_id is None
        assert ProductionOrder.query.get(ok).override_delivery_method == s.ODBIOR


# ── M6: ogromna liczba we współrzędnych pinezki ─────────────────────────────

@pytest.mark.parametrize('cialo', [{'lat': 10 ** 400, 'lng': 20},
                                   {'lat': 50, 'lng': -10 ** 400}],
                         ids=['lat', 'lng'])
def test_m6_ogromna_liczba_we_wspolrzednych_to_422(client, app, cialo):
    """M6: float(10**400) rzuca OverflowError (nie ValueError) — było 500."""
    with app.app_context():
        oid = zamowienie().id
    r = client.put(BASE + '/orders/%d/geo' % oid, json=cialo)
    assert r.status_code == 422
    assert r.get_json()['error'] == u'Nieprawidłowe współrzędne.'
    with app.app_context():
        assert OrderGeo.query.get(oid) is None


# ── M7: kod pocztowy PL tylko z cyfr ASCII ──────────────────────────────────

@pytest.mark.parametrize('kod', [u'٣٥٣١٠', u'٣٥-٣١٠', u'３５３１０', u'３５-３１０'],
                         ids=['arabskie', 'arabskie-z-kreska', 'pelnej-szerokosci',
                              'pelnej-szerokosci-z-kreska'])
def test_m7_kod_pl_z_cyfr_spoza_ascii_to_422(client, app, kod):
    """M7: `\\d` i str.isdigit() przepuszczały cyfry Unicode — taki kod szedł do Base."""
    with app.app_context():
        oid = zamowienie().id
    r = client.put(BASE + '/orders/%d/address' % oid,
                   json={'adres': 'Nowa 1', 'kod': kod, 'miasto': 'Kraków'})
    assert r.status_code == 422
    assert r.get_json()['error'] == u'Kod pocztowy w formacie 00-000.'
    with app.app_context():
        order = ProductionOrder.query.get(oid)
        assert order.delivery_postcode == '30-001' and order.bl_address_pending is False


def test_m7_kod_z_cyfr_ascii_dalej_przechodzi(app):
    with app.app_context():
        order = zamowienie()
        assert delivery.zmien_adres(order, 'Nowa 1', '35310', 'Rzeszów') is True
        assert order.delivery_postcode == '35-310'


# ── M11: szczegóły trasy usuniętej w trakcie GET ────────────────────────────

def _robocza_z_przystankiem(client, app):
    with app.app_context():
        oid = zamowienie(sposob=s.TRANSPORT, statusy=('spakowane',)).id
    r = client.post(BASE + '/routes', json={'name': 'Kraków', 'date_from': '2026-10-01'})
    rid = r.get_json()['route']['id']
    assert client.post(BASE + '/routes/%d/stops' % rid, json={'order_ids': [oid]}).status_code == 200
    return rid


def _usun_trase_obok_orm(route_id):
    """Symulacja równoległego usunięcia trasy: surowy DELETE, o którym sesja ORM nie wie."""
    db.session.execute(text('DELETE FROM prod_route_stops WHERE route_id = :id'), {'id': route_id})
    db.session.execute(text('DELETE FROM prod_routes WHERE id = :id'), {'id': route_id})


def _sprawdz_404(odpowiedz):
    assert odpowiedz.status_code == 404
    assert odpowiedz.get_json() == {'success': False, 'error': u'Nie ma takiej trasy.'}


def test_m11_szczegoly_trasy_stale_data_to_404(client, app, monkeypatch):
    rid = _robocza_z_przystankiem(client, app)

    def przelicz(route, punkty, **kwargs):
        raise StaleDataError(u"UPDATE statement on table 'prod_routes' expected to update "
                             u"1 row(s); 0 were matched.")

    monkeypatch.setattr(routing, 'przelicz', przelicz)
    _sprawdz_404(client.get(BASE + '/routes/%d' % rid))


def test_m11_trasa_usunieta_przed_zapisem_przebiegu_to_404(client, app, monkeypatch):
    """UPDATE przebiegu nie trafia w wiersz usuniętej trasy → StaleDataError przy commicie."""
    rid = _robocza_z_przystankiem(client, app)

    def przelicz(route, punkty, **kwargs):
        _usun_trase_obok_orm(route.id)
        route.geometry_hash = 'po-usunieciu'
        return True

    monkeypatch.setattr(routing, 'przelicz', przelicz)
    _sprawdz_404(client.get(BASE + '/routes/%d' % rid))


def test_m11_trasa_usunieta_po_zapisie_przebiegu_to_404(client, app, monkeypatch):
    """Commit przeszedł, a trasy już nie ma — dociągnięcie wygaszonej trasy przy serializacji
    nie znajduje wiersza → ObjectDeletedError."""
    rid = _robocza_z_przystankiem(client, app)

    def przelicz(route, punkty, **kwargs):
        _usun_trase_obok_orm(route.id)
        return True

    monkeypatch.setattr(routing, 'przelicz', przelicz)
    _sprawdz_404(client.get(BASE + '/routes/%d' % rid))
