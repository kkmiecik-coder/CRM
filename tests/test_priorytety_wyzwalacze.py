# -*- coding: utf-8 -*-
"""
Wyzwalacze `kolejka.utrwal()` w logistyce (plan K1, Task 6; spec 2026-10-04, sekcja 9.3): po akcjach tras, zmianie
sposobu dostawy, „Wydane klientowi”, zapisach telefonu kierowcy, „Cofnij do pakowania” z telefonu Weryfikacji
i w cronie. Zawsze PO commicie, nigdy w transakcji; błąd przeliczenia nie psuje odpowiedzi.

Wyzwalacze panelu produktów (hurtowa zmiana statusu, zmiany z Base.): tests/test_priorytety_wyzwalacze_produkty.py.
Plik nie zakłada tabeli prod_product_events (konwencja pakietu).
"""
from datetime import date

import pytest
from flask import g
from sqlalchemy import event
from sqlalchemy.exc import OperationalError

from extensions import db
from modules.production.logistics import sposoby as s
from modules.production.logistics.models import Route
from modules.production.logistics.services import bl_sync, dostawa, geocoding
from modules.production.models import (
    ProductionDevice, ProductionOrder, ProductionPackage, ProductionProduct, get_local_now)
from modules.production.priorytety.models import PriorityRung
from modules.production.priorytety.services import drabina, kolejka
from modules.production.services.mobile_api_service import generate_token
from tests.blokady_pomocnicze import Zapytania, blokada_zamowien, indeks_blokady_tras
from tests.dostawa_pomocnicze import T0, naglowki, telefon_kierowcy, trasa, zaladuj_wprost, zamowienie_z_paczkami
from tests.logistyka_fixtures import (  # noqa: F401
    BASE, DZIS_TESTOW, SEKRET_CRONA, app, client, pracownik, zamowienie)
from tests.priorytety_fixtures import (  # noqa: F401
    czyste_ustawienia, drabina_domyslna, szpieg_utrwal, zamrozony_dzien)

pytestmark = pytest.mark.usefixtures('zamrozony_dzien', 'czyste_ustawienia')

API_DOSTAWY = '/api/mobile/delivery'
API_WERYFIKACJI = '/api/mobile/verification'
NAGLOWEK_CRONA = {'X-Cron-Secret': SEKRET_CRONA}


@pytest.fixture(autouse=True)
def bez_statusow_base(monkeypatch):
    monkeypatch.setattr(
        'modules.production.services.baselinker_status_sync.schedule_after_station_complete',
        lambda *a, **k: None)


@pytest.fixture()
def watki(monkeypatch):
    """Cron startuje dopychacz Base. i geokoder w tle — w testach tylko notujemy starty (StaticPool)."""
    uruchomione = []
    monkeypatch.setattr(bl_sync, 'uruchom_w_tle', lambda app_: uruchomione.append('base') or True)
    monkeypatch.setattr(geocoding, 'uruchom_w_tle', lambda app_: uruchomione.append('geo') or True)
    return uruchomione


def _w_produkcji(termin=date(2026, 11, 20), **kolumny):
    """Zamówienie na transport własny z jedną pozycją na Sklejaniu."""
    order = zamowienie(sposob=s.TRANSPORT, statusy=('czeka_na_sklejanie',), **kolumny)
    for p in order.products:
        p.deadline_date = termin
    db.session.commit()
    return order.id


def _ranga(order_id):
    db.session.rollback()
    db.session.expire_all()
    order = db.session.get(ProductionOrder, order_id)
    return order.priority_rank, order.priority_rung


def _nowa_trasa(client, nazwa='Śląsk'):
    r = client.post(BASE + '/routes', json={'name': nazwa, 'date_from': '2026-10-01'})
    assert r.status_code == 201, r.get_data()[:300]
    return r.get_json()['route']['id']


# ── Licznik „po commicie” ─────────────────────────────────────────────────────────────────────────────────────

def test_szpieg_utrwal_wykrywa_zflushowany_niezatwierdzony_zapis(app, szpieg_utrwal):
    """Na MySQL `utrwal` wołane, gdy `db.session` trzyma zflushowany, niezatwierdzony zapis zamówienia, czeka na
    własne blokady do limitu serwera. SQLite tego nie pokaże, więc pilnuje tego licznik: sam `flush()` czyści
    `db.session.new/dirty`, a transakcja dalej jest otwarta — „czysta” znaczy „żadnego zapisu od ostatniego commitu”."""
    drabina_domyslna()
    order_id = _w_produkcji()

    db.session.get(ProductionOrder, order_id).order_notes = 'zapis bez commitu'
    db.session.flush()
    assert not (db.session.new or db.session.dirty or db.session.deleted)
    kolejka.utrwal()
    assert szpieg_utrwal[-1]['czysta'] is False

    db.session.rollback()
    kolejka.utrwal()
    assert szpieg_utrwal[-1]['czysta'] is True

    # zapis poza ORM (Core) też jest niezatwierdzoną pracą
    db.session.execute(ProductionOrder.__table__.update().where(ProductionOrder.id == order_id)
                       .values(order_notes='zapis Core'))
    kolejka.utrwal()
    assert szpieg_utrwal[-1]['czysta'] is False
    db.session.commit()
    kolejka.utrwal()
    assert szpieg_utrwal[-1]['czysta'] is True


# ── Panel tras ────────────────────────────────────────────────────────────────────────────────────────────────

def test_route_create_zaklada_szczebel_i_utrwala_po_commicie(app, client, szpieg_utrwal):
    drabina_domyslna()
    order_id = _w_produkcji()
    route_id = _nowa_trasa(client)
    assert PriorityRung.query.filter_by(route_id=route_id).one().position == 2
    assert len(szpieg_utrwal) == 1
    assert szpieg_utrwal[0]['czysta'] is True and szpieg_utrwal[0]['zrodlo'] is None
    assert szpieg_utrwal[0]['raport']['success'] is True
    # zamówienie spoza trasy: „bez gwiazdek” to teraz szczebel 10 (nad nim doszedł szczebel trasy)
    assert _ranga(order_id) == (1, 10)


def test_dodanie_przystanku_utrwala_po_commicie(app, client, szpieg_utrwal):
    drabina_domyslna()
    order_id, inne_id = _w_produkcji(), _w_produkcji(termin=date(2026, 10, 30))
    route_id = _nowa_trasa(client)
    assert _ranga(order_id) == (2, 10) and _ranga(inne_id) == (1, 10)
    del szpieg_utrwal[:]

    r = client.post(BASE + '/routes/%d/stops' % route_id, json={'order_ids': [order_id]})

    assert r.status_code == 200, r.get_data()[:300]
    assert len(szpieg_utrwal) == 1 and szpieg_utrwal[0]['czysta'] is True
    # po żądaniu zamówienie stoi na szczeblu trasy (2) i wyprzedza pilniejsze spoza trasy
    assert _ranga(order_id) == (1, 2)
    assert _ranga(inne_id) == (2, 10)
    pozycja = ProductionProduct.query.filter_by(order_id=order_id).one()
    assert pozycja.priority_rank == 101

    # zdjęcie przystanku: zamówienie wraca na szczebel gwiazdek
    assert client.delete(BASE + '/routes/%d/stops/%d' % (route_id, order_id)).status_code == 200
    assert len(szpieg_utrwal) == 2
    assert _ranga(order_id) == (2, 10) and _ranga(inne_id) == (1, 10)


def test_zatwierdzenie_i_cofniecie_utrwalaja(app, client, szpieg_utrwal):
    drabina_domyslna()
    order_id = _w_produkcji()
    route_id = _nowa_trasa(client)
    client.post(BASE + '/routes/%d/stops' % route_id, json={'order_ids': [order_id]})
    del szpieg_utrwal[:]
    assert client.post(BASE + '/routes/%d/approve' % route_id).status_code == 200
    assert len(szpieg_utrwal) == 1
    assert client.post(BASE + '/routes/%d/revert' % route_id).status_code == 200
    assert len(szpieg_utrwal) == 2
    assert all(w['czysta'] for w in szpieg_utrwal)
    assert _ranga(order_id) == (1, 2)
    # odmowa (trasa już robocza) niczego nie przelicza
    assert client.post(BASE + '/routes/%d/revert' % route_id).status_code in (409, 422)
    assert len(szpieg_utrwal) == 2


def test_route_delete_utrwala(app, client, szpieg_utrwal):
    drabina_domyslna()
    order_id = _w_produkcji()
    route_id = _nowa_trasa(client)
    client.post(BASE + '/routes/%d/stops' % route_id, json={'order_ids': [order_id]})
    assert _ranga(order_id) == (1, 2)
    del szpieg_utrwal[:]

    assert client.delete(BASE + '/routes/%d' % route_id).status_code == 200

    assert len(szpieg_utrwal) == 1 and szpieg_utrwal[0]['czysta'] is True
    assert PriorityRung.query.filter_by(route_id=route_id).count() == 0
    # szczebel trasy zniknął: „bez gwiazdek” wraca na pozycję 9
    assert _ranga(order_id) == (1, 9)
    # trasa, której nie ma → 404 bez przeliczenia
    assert client.delete(BASE + '/routes/%d' % route_id).status_code == 404
    assert len(szpieg_utrwal) == 1


def test_dwa_zadania_w_jednym_tescie_utrwalaja_dwa_razy(app, client, szpieg_utrwal):
    """Fikstura trzyma jeden kontekst aplikacji, więc `g` jest wspólne dla żądań klienta testowego — znacznik
    „już przeliczone w tym żądaniu” wyłączyłby drugie przeliczenie."""
    drabina_domyslna()
    order_id = _w_produkcji()
    route_id = _nowa_trasa(client)
    assert _ranga(order_id) == (1, 10)
    assert client.delete(BASE + '/routes/%d' % route_id).status_code == 200
    assert len(szpieg_utrwal) == 2
    assert _ranga(order_id) == (1, 9)


def test_wyjatek_w_utrwal_po_commicie_nie_psuje_odpowiedzi(app, client, monkeypatch):
    drabina_domyslna()
    bledy = []

    class Szpieg(object):
        def error(self, message, **kwargs):
            bledy.append(message)

        debug = info = warning = lambda self, *a, **k: None

    def wybuch(*args, **kwargs):
        raise RuntimeError('sztuczna awaria utrwal')

    monkeypatch.setattr(kolejka, 'utrwal', wybuch)
    monkeypatch.setattr(kolejka, 'logger', Szpieg())
    route_id = _nowa_trasa(client)                                         # 201 mimo wyjątku
    assert len(bledy) == 1
    assert client.delete(BASE + '/routes/%d' % route_id).status_code == 200
    assert len(bledy) == 2
    assert Route.query.get(route_id) is None                               # zapis trasy został zatwierdzony


# ── Panel Logistyki: sposób dostawy, „Wydane klientowi” ───────────────────────────────────────────────────────

def test_delivery_method_utrwala_po_commicie(app, client, szpieg_utrwal):
    drabina_domyslna()
    order_id = _w_produkcji()
    route_id = _nowa_trasa(client)
    client.post(BASE + '/routes/%d/stops' % route_id, json={'order_ids': [order_id]})
    assert _ranga(order_id) == (1, 2)
    del szpieg_utrwal[:]

    r = client.post(BASE + '/orders/delivery-method', json={'order_ids': [order_id], 'sposob': s.KURIER})

    assert r.status_code == 200 and r.get_json()['zmienione'] == [order_id]
    assert len(szpieg_utrwal) == 1 and szpieg_utrwal[0]['czysta'] is True
    # zmiana z transportu zdjęła zamówienie z trasy roboczej → szczebel gwiazdek
    assert _ranga(order_id) == (1, 10)
    # złe dane → 422 bez przeliczenia
    assert client.post(BASE + '/orders/delivery-method', json={'order_ids': [], 'sposob': s.KURIER}).status_code == 422
    assert len(szpieg_utrwal) == 1


def test_handed_over_utrwala(app, client, szpieg_utrwal):
    drabina_domyslna()
    odbior = zamowienie(sposob=s.ODBIOR, statusy=('spakowane',)).id
    kurier = zamowienie(sposob=s.KURIER, statusy=('spakowane',)).id
    assert client.post(BASE + '/orders/%d/handed-over' % odbior).status_code == 200
    assert len(szpieg_utrwal) == 1 and szpieg_utrwal[0]['czysta'] is True
    # odmowa (to nie odbiór osobisty) — bez przeliczenia
    assert client.post(BASE + '/orders/%d/handed-over' % kurier).status_code == 409
    assert len(szpieg_utrwal) == 1


# ── Telefon kierowcy (API mobilne: handler planuje, dekorator wykonuje po commicie) ───────────────────────────

def _trasa_do_zaladunku():
    """(telefon, kierowca, trasa zatwierdzona z jednym zamówieniem, paczki) — paczki jeszcze nie załadowane."""
    device, k = telefon_kierowcy()
    order, paczki = zamowienie_z_paczkami()
    t = trasa([order], kierowca_id=k.id, od=DZIS_TESTOW)
    return device, k, t, paczki


def test_zapis_dostawy_planuje_utrwal_a_dekorator_wykonuje_po_commicie(app, client, szpieg_utrwal, monkeypatch):
    monkeypatch.setattr(bl_sync, 'po_zmianie', lambda ids: None)
    drabina_domyslna()
    device, k, t, paczki = _trasa_do_zaladunku()
    rid = t.id

    # odmowa 409 (paczki nie załadowane): handler niczego nie planuje
    r = client.post(API_DOSTAWY + '/routes/%d/finish-loading' % rid, headers=naglowki(device, k))
    assert r.status_code == 409
    assert szpieg_utrwal == [] and not g.get(kolejka._PLAN_W_G)

    zaladuj_wprost(paczki, t, kto_id=k.id)
    commity = []

    def przy_commicie(conn):
        commity.append(len(szpieg_utrwal))

    event.listen(db.engine, 'commit', przy_commicie)
    try:
        r = client.post(API_DOSTAWY + '/routes/%d/finish-loading' % rid, headers=naglowki(device, k))
    finally:
        event.remove(db.engine, 'commit', przy_commicie)
    assert r.status_code == 200, r.get_data()[:300]
    assert r.get_json()['route']['status'] == 'zaladowana'
    # dokładnie jedno przeliczenie, po commicie dekoratora, na czystej sesji; plan zdjęty z `g`
    assert len(szpieg_utrwal) == 1 and szpieg_utrwal[0]['czysta'] is True
    assert commity and commity[0] == 0, 'utrwal poszlo przed commitem zapisu'
    assert not g.get(kolejka._PLAN_W_G)

    # powtórka idempotentna (ten sam X-Operation-Id): handler się nie wykonuje, nic nie przeliczamy
    naglowek = naglowki(device, k, op_id='op-prio-1')
    assert client.post(API_DOSTAWY + '/routes/%d/depart' % rid, headers=naglowek).status_code == 200
    assert len(szpieg_utrwal) == 2
    assert client.post(API_DOSTAWY + '/routes/%d/depart' % rid, headers=naglowek).status_code == 200
    assert len(szpieg_utrwal) == 2


def test_ponowienie_1213_w_dostawie_porzuca_plan_i_planuje_od_nowa(app, client, szpieg_utrwal, monkeypatch):
    monkeypatch.setattr(bl_sync, 'po_zmianie', lambda ids: None)
    drabina_domyslna()
    device, k, t, paczki = _trasa_do_zaladunku()
    zaladuj_wprost(paczki, t, kto_id=k.id)
    rid = t.id
    oryginal = dostawa.zakoncz_zaladunek
    proby, plany = [], []

    def z_zakleszczeniem(*args, **kwargs):
        proby.append(1)
        plany.append(bool(g.get(kolejka._PLAN_W_G)))
        wynik = oryginal(*args, **kwargs)
        if len(proby) == 1:
            db.session.flush()
            # pierwsza próba zdążyła zaplanować przeliczenie (jak po udanym flushu) i dostaje 1213
            kolejka.zaplanuj_po_commicie()
            raise OperationalError('UPDATE prod_products SET ...', {}, Exception(1213, 'Deadlock found'))
        return wynik

    monkeypatch.setattr(dostawa, 'zakoncz_zaladunek', z_zakleszczeniem)

    r = client.post(API_DOSTAWY + '/routes/%d/finish-loading' % rid, headers=naglowki(device, k))

    assert r.status_code == 200, r.get_data()[:300]
    assert len(proby) == 2
    # druga próba zaczyna bez planu pierwszej (porzucony razem z rollbackiem) i planuje od nowa
    assert plany == [False, False]
    assert len(szpieg_utrwal) == 1 and szpieg_utrwal[0]['czysta'] is True
    assert not g.get(kolejka._PLAN_W_G)


def test_wykonaj_zaplanowane_zdejmuje_plan_z_g(app, szpieg_utrwal):
    drabina_domyslna()
    # poza żądaniem planowanie nic nie robi (cron, skrypty wołają utrwal wprost)
    kolejka.zaplanuj_po_commicie()
    assert kolejka.wykonaj_zaplanowane() is None and szpieg_utrwal == []
    with app.test_request_context('/'):
        assert kolejka.wykonaj_zaplanowane() is None            # nic nie zaplanowano
        kolejka.zaplanuj_po_commicie()
        kolejka.zaplanuj_po_commicie()                           # dwa razy = dalej jedno przeliczenie
        raport = kolejka.wykonaj_zaplanowane()
        assert raport['success'] is True and len(szpieg_utrwal) == 1
        assert kolejka.wykonaj_zaplanowane() is None and len(szpieg_utrwal) == 1
        kolejka.zaplanuj_po_commicie()
        kolejka.porzuc_zaplanowane()
        assert kolejka.wykonaj_zaplanowane() is None and len(szpieg_utrwal) == 1
        kolejka.porzuc_zaplanowane()                             # bez planu — bez błędu


# ── Telefon Weryfikacji: „Cofnij do pakowania” ────────────────────────────────────────────────────────────────

def _spakowane_z_paczkami(numer, statusy=('spakowane', 'spakowane')):
    order = zamowienie(sposob=s.KURIER, statusy=statusy, numer_wewnetrzny=numer, packages_declared_at=T0)
    for p in order.products:
        p.packaging_completed_at = get_local_now()
        p.priority_rank = 4711                                   # ranga z dawnego przeliczenia
    order.priority_rank, order.priority_rung = 47, 9
    db.session.add_all([ProductionPackage(order_id=order.id, seq=i, kind='paczka', declared_at=T0)
                        for i in (1, 2)])
    db.session.commit()
    return order


def _telefon_weryfikacji():
    device = ProductionDevice(device_id='TEL-WERYFIKACJA-PRIO', device_name='Telefon', station_code='verification')
    db.session.add(device)
    db.session.commit()
    return device


_operacje = iter(range(1, 10 ** 6))


def _cofnij(client, order, device, kto, **body):
    naglowki_telefonu = {'Authorization': 'Bearer ' + generate_token(device),
                         'X-Operation-Id': 'op-prio-wer-%d' % next(_operacje), 'X-Worker-Ids': str(kto.id)}
    return client.post('%s/orders/%s/revert-to-packing' % (API_WERYFIKACJI, order.internal_order_number), json=body,
                       headers=naglowki_telefonu)


def test_cofnij_do_pakowania_planuje_utrwal_a_dekorator_wykonuje_po_commicie(app, client, szpieg_utrwal,
                                                                            monkeypatch):
    monkeypatch.setattr(bl_sync, 'uruchom_w_tle', lambda app_: True)
    drabina_domyslna()
    kto, device = pracownik(), _telefon_weryfikacji()
    inne_id = _w_produkcji()
    kolejka.utrwal()
    del szpieg_utrwal[:]
    assert _ranga(inne_id) == (1, 9)
    order = _spakowane_z_paczkami('3901')
    order_id = order.id

    # odmowy: brak powodu (422, zapamiętane) i zamówienie nie w całości spakowane (409) — bez przeliczenia
    assert _cofnij(client, order, device, kto).status_code == 422
    niespakowane = _spakowane_z_paczkami('3902', statusy=('spakowane', 'czeka_na_pakowanie'))
    assert _cofnij(client, niespakowane, device, kto, reason='inne').status_code == 409
    assert szpieg_utrwal == [] and not g.get(kolejka._PLAN_W_G)
    # zamówienie częściowo w pakowaniu jest aktywne — porządkujemy rangi przed właściwym pomiarem
    kolejka.utrwal()
    del szpieg_utrwal[:]

    r = _cofnij(client, order, device, kto, reason='inne')

    assert r.status_code == 200, r.get_data()[:300]
    assert len(szpieg_utrwal) == 1 and szpieg_utrwal[0]['czysta'] is True
    assert not g.get(kolejka._PLAN_W_G)
    # zamówienie znów aktywne: rangi z policz(), a nie z dawnego przeliczenia
    db.session.rollback()
    db.session.expire_all()
    pozycje = ProductionProduct.query.filter_by(order_id=order_id).order_by(ProductionProduct.id).all()
    assert [p.current_status for p in pozycje] == ['czeka_na_pakowanie', 'czeka_na_pakowanie']
    # „bez gwiazdek”: zamówienie z terminem pierwsze, potem bez terminu po numerze (3901 przed 3902)
    assert _ranga(order_id) == (2, 9) and _ranga(inne_id) == (1, 9)
    pozycje = ProductionProduct.query.filter_by(order_id=order_id).order_by(ProductionProduct.id).all()
    assert [p.priority_rank for p in pozycje] == [201, 202]
    # rangi zamówień aktywnych są unikatowe
    aktywne = {p.order_id for p in ProductionProduct.query.filter(
        ProductionProduct.current_status.in_(('czeka_na_sklejanie', 'czeka_na_pakowanie')))}
    rangi = [db.session.get(ProductionOrder, oid).priority_rank for oid in aktywne]
    assert sorted(rangi) == list(range(1, len(aktywne) + 1))


# ── Cron logistyki ────────────────────────────────────────────────────────────────────────────────────────────

def test_cron_ma_faze_priorytety_utrwalone(app, client, watki, szpieg_utrwal):
    drabina_domyslna()
    order_id = _w_produkcji()
    t = trasa([db.session.get(ProductionOrder, order_id)], status='robocza')      # trasa sprzed migracji: bez szczebla
    route_id = t.id
    assert PriorityRung.query.filter_by(route_id=route_id).count() == 0

    r = client.post(BASE + '/cron', headers=NAGLOWEK_CRONA)

    assert r.status_code == 200
    dane = r.get_json()
    assert dane['szczeble_uzupelnione'] == 1
    raport = dane['priorytety_utrwalone']
    assert raport['success'] is True and raport['zmienione_zamowienia'] == 1 and raport['ostrzezenia'] == []
    # klucze logistyki bez zmian, wątki w tle uruchomione
    for klucz in ('success', 'przeniesione_z_logistyki', 'wydane_dostarczone', 'przeliczone',
                  'dopychacz_uruchomiony', 'geokoder_uruchomiony', 'base_wstrzymane_do'):
        assert klucz in dane
    assert dane['success'] is True and watki == ['base', 'geo']
    assert len(szpieg_utrwal) == 1 and szpieg_utrwal[0]['czysta'] is True
    assert PriorityRung.query.filter_by(route_id=route_id).one().position == 2
    assert _ranga(order_id) == (1, 2)
    # drugi przebieg: nic do dopisania, nic do zmiany
    dane = client.post(BASE + '/cron', headers=NAGLOWEK_CRONA).get_json()
    assert dane['szczeble_uzupelnione'] == 0
    assert dane['priorytety_utrwalone']['zmienione_zamowienia'] == 0


def test_cron_uzupelnia_pod_blokada_tras_przed_utrwal(app, client, watki):
    drabina_domyslna()
    order_id = _w_produkcji()
    trasa([db.session.get(ProductionOrder, order_id)], status='robocza')
    with Zapytania() as z:
        def przy_commicie(conn):
            z.lista.append(('commit', None))

        event.listen(db.engine, 'commit', przy_commicie)
        try:
            assert client.post(BASE + '/cron', headers=NAGLOWEK_CRONA).status_code == 200
        finally:
            event.remove(db.engine, 'commit', przy_commicie)
    wstawka = z.pierwsze(lambda sql: sql.startswith('INSERT INTO prod_priority_rungs'))
    blokady_tras = [i for i, (sql, parametry) in enumerate(z.lista)
                    if sql.startswith('SELECT') and 'FROM prod_config' in sql and sql.endswith(' FOR UPDATE')
                    and 'logistyka_trasy_blokada' in tuple(parametry or ())]
    # szczebel dopisany pod blokadą tras wziętą w TEJ fazie (po commitach faz logistyki)
    assert indeks_blokady_tras(z) < wstawka
    ostatnia_blokada_tras = max(i for i in blokady_tras if i < wstawka)
    commity = [i for i, (sql, _p) in enumerate(z.lista) if sql == 'commit']
    assert not [i for i in commity if ostatnia_blokada_tras < i < wstawka]
    # utrwal blokuje zamówienia dopiero PO commicie szczebli (własna sesja nie może czekać na db.session crona)
    commit_szczebli = min(i for i in commity if i > wstawka)
    blokady_rang = [i for i, (sql, _p) in enumerate(z.lista)
                    if blokada_zamowien(sql) and 'priority_rank' in sql and i > wstawka]
    assert blokady_rang and min(blokady_rang) > commit_szczebli
    # wątki w tle startują przed fazą priorytetów
    assert watki == ['base', 'geo']


def test_cron_blad_priorytetow_nie_zatrzymuje_logistyki(app, client, watki, monkeypatch):
    """Fazy logistyki są już zatwierdzone, dopychacz Base. i geokoder ruszyły — błąd priorytetów daje 200."""
    from modules.production.logistics.routers import cron_api
    bledy = []

    def wybuch(*args, **kwargs):
        raise RuntimeError('sztuczna awaria drabiny')

    monkeypatch.setattr(drabina, 'uzupelnij', wybuch)
    oryginal_error = cron_api.logger.error
    monkeypatch.setattr(cron_api.logger, 'error', lambda *a, **k: (bledy.append(a), oryginal_error(*a, **k))[1])

    r = client.post(BASE + '/cron', headers=NAGLOWEK_CRONA)

    assert r.status_code == 200
    dane = r.get_json()
    assert dane['success'] is True
    assert dane['szczeble_uzupelnione'] is None and dane['priorytety_utrwalone'] is None
    assert watki == ['base', 'geo'] and len(bledy) == 1


def test_cron_nieudane_utrwal_to_dalej_200(app, client, watki, monkeypatch):
    """`utrwal`, które się nie powiodło, nie jest wyjątkiem: raport z `success: False` trafia do odpowiedzi."""
    drabina_domyslna()
    monkeypatch.setattr(kolejka, 'utrwal', lambda *a, **k: {'success': False, 'error': 'sztuczna awaria'})
    r = client.post(BASE + '/cron', headers=NAGLOWEK_CRONA)
    assert r.status_code == 200
    dane = r.get_json()
    assert dane['success'] is True and dane['szczeble_uzupelnione'] == 0
    assert dane['priorytety_utrwalone'] == {'success': False, 'error': 'sztuczna awaria'}


# ── K3-poprawka-1: sygnały `station:packaging` po cofnięciu do pakowania (spec 5.4) ───────────────────────────

@pytest.fixture()
def sygnaly_stanowisk(app, monkeypatch):
    """Zdarzenia w kolejności: 'FLUSH' przy każdym zapisie `db.session` do bazy, 'COMMIT' przy każdym commicie
    połączenia i kod stanowiska przy każdym sygnale. Sygnał wysłany, gdy sesja ma niezapisane zmiany, zostawia
    dodatkowo 'NIEZAPISANE' — po commicie sesja jest czysta."""
    from modules.production.priorytety.services import sygnaly
    from modules.production.services import realtime_service
    zdarzenia = []

    def sygnal(kod):
        if db.session.new or db.session.dirty or db.session.deleted:
            zdarzenia.append('NIEZAPISANE')
        zdarzenia.append(kod)
        return True

    def po_commicie(_polaczenie):
        zdarzenia.append('COMMIT')

    def po_flushu(_sesja, _kontekst):
        zdarzenia.append('FLUSH')

    monkeypatch.setattr(realtime_service, 'publish_station_signal', sygnal)
    event.listen(db.engine, 'commit', po_commicie)
    event.listen(db.session, 'after_flush', po_flushu)
    g.pop(sygnaly._PLAN_W_G, None)
    yield zdarzenia
    g.pop(sygnaly._PLAN_W_G, None)
    event.remove(db.session, 'after_flush', po_flushu)
    event.remove(db.engine, 'commit', po_commicie)


def _kody(zdarzenia):
    return [z for z in zdarzenia if z not in ('COMMIT', 'FLUSH', 'NIEZAPISANE')]


def _tuz_po_commicie(zdarzenia, kod):
    """Sygnał poszedł po commicie zapisu, a nie w transakcji: bezpośrednio przed nim jest COMMIT poprzedzony
    zapisem do bazy, a sesja nie miała wtedy niezapisanych zmian."""
    i = zdarzenia.index(kod)
    return zdarzenia[i - 1] == 'COMMIT' and 'FLUSH' in zdarzenia[:i - 1] and 'NIEZAPISANE' not in zdarzenia


def test_cofnij_do_pakowania_sygnal_packaging_po_commicie(app, client, sygnaly_stanowisk, monkeypatch):
    """„Cofnij do pakowania” (Weryfikacja) dokłada pracę Pakowaniu: handler planuje sygnał, `with_idempotency`
    wysyła go po commicie zapisu — nigdy w transakcji."""
    monkeypatch.setattr(bl_sync, 'uruchom_w_tle', lambda app_: True)
    drabina_domyslna()
    kto, device = pracownik(), _telefon_weryfikacji()
    order = _spakowane_z_paczkami('3911')
    del sygnaly_stanowisk[:]

    r = _cofnij(client, order, device, kto, reason='inne')

    assert r.status_code == 200, r.get_data()[:300]
    assert _kody(sygnaly_stanowisk) == ['packaging']
    assert _tuz_po_commicie(sygnaly_stanowisk, 'packaging'), sygnaly_stanowisk
    db.session.rollback()
    assert {p.current_status for p in ProductionProduct.query.filter_by(order_id=order.id)} == {'czeka_na_pakowanie'}


def test_cofnij_do_pakowania_odmowa_bez_sygnalu(app, client, sygnaly_stanowisk, monkeypatch):
    monkeypatch.setattr(bl_sync, 'uruchom_w_tle', lambda app_: True)
    kto, device = pracownik(), _telefon_weryfikacji()
    order = _spakowane_z_paczkami('3912')
    niespakowane = _spakowane_z_paczkami('3913', statusy=('spakowane', 'czeka_na_pakowanie'))
    del sygnaly_stanowisk[:]

    assert _cofnij(client, order, device, kto).status_code == 422                       # brak powodu
    assert _cofnij(client, niespakowane, device, kto, reason='inne').status_code == 409  # rollback
    assert client.post('%s/orders/%s/revert-to-packing' % (API_WERYFIKACJI, 'nie-ma-takiego'),
                       json={'reason': 'inne'},
                       headers={'Authorization': 'Bearer ' + generate_token(device),
                                'X-Operation-Id': 'op-prio-wer-%d' % next(_operacje),
                                'X-Worker-Ids': str(kto.id)}).status_code == 404

    from modules.production.priorytety.services import sygnaly
    assert _kody(sygnaly_stanowisk) == [] and not g.get(sygnaly._PLAN_W_G)


def test_przepakowanie_z_panelu_sygnal_packaging(app, client, sygnaly_stanowisk, monkeypatch):
    """Zmiana sposobu dostawy, która cofa spakowane zamówienie do pakowania: sygnał `station:packaging` po commicie
    routera. Jeden sygnał na żądanie, także przy hurcie."""
    monkeypatch.setattr(bl_sync, 'uruchom_w_tle', lambda app_: True)
    drabina_domyslna()
    pierwsze, drugie = _spakowane_z_paczkami('3921'), _spakowane_z_paczkami('3922')
    ids = [pierwsze.id, drugie.id]
    del sygnaly_stanowisk[:]

    r = client.post(BASE + '/orders/delivery-method',
                    json={'order_ids': ids, 'sposob': s.ODBIOR, 'przepakowanie': True})

    assert r.status_code == 200, r.get_data()[:300]
    assert r.get_json()['przepakowanie'] == ids
    assert _kody(sygnaly_stanowisk) == ['packaging']
    assert _tuz_po_commicie(sygnaly_stanowisk, 'packaging'), sygnaly_stanowisk


def test_zmiana_sposobu_bez_przepakowania_bez_sygnalu(app, client, sygnaly_stanowisk, monkeypatch):
    """Sygnał idzie tylko, gdy coś wróciło do pakowania: zmiana sposobu „bez przepakowania”, odmowa (brak decyzji)
    i zmiana na zamówieniu w produkcji go nie wysyłają."""
    monkeypatch.setattr(bl_sync, 'uruchom_w_tle', lambda app_: True)
    drabina_domyslna()
    spakowane = _spakowane_z_paczkami('3931')
    w_produkcji = _w_produkcji()
    del sygnaly_stanowisk[:]

    r = client.post(BASE + '/orders/delivery-method', json={'order_ids': [spakowane.id], 'sposob': s.ODBIOR})
    assert r.status_code == 200 and r.get_json()['zmienione'] == [] and r.get_json()['bledy']
    r = client.post(BASE + '/orders/delivery-method',
                    json={'order_ids': [spakowane.id], 'sposob': s.ODBIOR, 'przepakowanie': False})
    assert r.status_code == 200 and r.get_json()['zmienione'] == [spakowane.id]
    assert r.get_json()['przepakowanie'] == []
    r = client.post(BASE + '/orders/delivery-method', json={'order_ids': [w_produkcji], 'sposob': s.KURIER})
    assert r.status_code == 200 and r.get_json()['zmienione'] == [w_produkcji]

    assert _kody(sygnaly_stanowisk) == []
