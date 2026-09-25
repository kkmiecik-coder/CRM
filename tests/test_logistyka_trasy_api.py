# -*- coding: utf-8 -*-
from datetime import timedelta

import pytest
from sqlalchemy.exc import IntegrityError

from extensions import db
from modules.production.logistics import sposoby as s
from modules.production.logistics.models import Route
from modules.production.logistics.services import routes
from modules.production.models import get_local_now
from tests.logistyka_fixtures import BASE, app, client, kierowca, pojazd, zamowienie  # noqa: F401


@pytest.fixture(autouse=True)
def bez_ors(app):
    app.config.pop('OPENROUTESERVICE_API_KEY', None)


def _nowa(client, **dane):
    dane.setdefault('name', 'Kraków')
    dane.setdefault('date_from', '2026-10-01')
    return client.post(BASE + '/routes', json=dane)


def test_flota_crud(client):
    r = client.post(BASE + '/vehicles', json={'name': 'Iveco', 'capacity_kg': 1500})
    assert r.status_code == 201
    vid = r.get_json()['vehicle']['id']
    assert client.put(BASE + '/vehicles/%d' % vid, json={'name': 'Iveco Daily'}).status_code == 200
    assert client.post(BASE + '/vehicles/%d/active' % vid, json={'active': False}).get_json()['vehicle']['is_active'] is False
    assert client.get(BASE + '/vehicles?aktywne=1').get_json()['vehicles'] == []
    assert client.post(BASE + '/vehicles', json={'name': ''}).status_code == 422


def test_dostepnosc_i_konflikt(client, app):
    with app.app_context():
        vid = pojazd().id
    assert _nowa(client, vehicle_id=vid).status_code == 201
    d = client.get(BASE + '/availability?date_from=2026-10-01&date_to=2026-10-01').get_json()
    assert d['pojazdy'][0]['zajety'] is True and d['pojazdy'][0]['trasa'] == 'Kraków'
    r = _nowa(client, name='Druga', vehicle_id=vid)
    assert r.status_code == 409 and 'Kraków' in r.get_json()['error']


def test_pelny_cykl_trasy(client, app):
    with app.app_context():
        a = zamowienie(sposob=s.TRANSPORT, statusy=('spakowane',)).id
        b = zamowienie(sposob=s.TRANSPORT, statusy=('spakowane',)).id
    rid = _nowa(client).get_json()['route']['id']
    r = client.post(BASE + '/routes/%d/stops' % rid, json={'order_ids': [a, b]})
    assert r.get_json()['dodane'] == [a, b]
    trasa = r.get_json()['route']
    assert [p['zamowienie']['id'] for p in trasa['przystanki']] == [a, b]
    assert trasa['podsumowanie']['przystanki'] == 2
    assert client.put(BASE + '/routes/%d/stops/order' % rid, json={'order_ids': [b, a]}).status_code == 200
    assert client.post(BASE + '/routes/%d/approve' % rid).get_json()['route']['status'] == 'zatwierdzona'
    assert client.delete(BASE + '/routes/%d/stops/%d' % (rid, a)).status_code == 409
    r = client.post(BASE + '/routes/%d/complete' % rid, json={'delivered_order_ids': [b]})
    assert r.get_json()['wynik'] == {'dostarczone': [b], 'niedostarczone': [a]}
    assert client.post(BASE + '/routes/%d/restore' % rid).get_json()['route']['status'] == 'zatwierdzona'


def test_mapa_tras_aktywnych(client, app):
    with app.app_context():
        a = zamowienie(sposob=s.TRANSPORT).id
    rid = _nowa(client).get_json()['route']['id']
    client.post(BASE + '/routes/%d/stops' % rid, json={'order_ids': [a]})
    mapa = client.get(BASE + '/routes/map').get_json()['routes']
    assert mapa[0]['id'] == rid and mapa[0]['przystanki'][0]['order_id'] == a


def test_kierowcy(client, app):
    with app.app_context():
        kierowca(imie='Adam', nazwisko='Nowak')
    assert client.get(BASE + '/drivers').get_json()['drivers'][0]['nazwa'] == 'Adam Nowak'


def test_usuniecie_roboczej_i_404(client):
    rid = _nowa(client).get_json()['route']['id']
    assert client.delete(BASE + '/routes/%d' % rid).status_code == 200
    assert client.get(BASE + '/routes/%d' % rid).status_code == 404


# ── R8: co najwyżej jedno przeliczenie przebiegu na żądanie /routes/map ─────

def test_mapa_najwyzej_jeden_przelicz_na_zadanie(client, app):
    """
    Dwie aktywne trasy z przystankami, obie ze sztucznie „nieaktualnym" skrótem
    przebiegu (symulacja: geokoder w tle dopiero co uzupełnił współrzędne, więc
    cache w bazie jest stary). Pierwsze GET /routes/map ma przeliczyć TYLKO
    jedną z nich (i ją zacommitować) — druga zostaje nieaktualna do kolejnego
    żądania. Bez tej reguły dwie trasy bez klucza ORS (a z kluczem — N × 8 s
    zapytań do ORS) mogłyby razem przekroczyć timeout gunicorna (30 s).
    """
    with app.app_context():
        a = zamowienie(sposob=s.TRANSPORT).id
        b = zamowienie(sposob=s.TRANSPORT).id
    r1 = _nowa(client, name='Trasa A').get_json()['route']['id']
    r2 = _nowa(client, name='Trasa B').get_json()['route']['id']
    client.post(BASE + '/routes/%d/stops' % r1, json={'order_ids': [a]})
    client.post(BASE + '/routes/%d/stops' % r2, json={'order_ids': [b]})

    with app.app_context():
        for rid in (r1, r2):
            Route.query.get(rid).geometry_hash = 'nieaktualny'
        db.session.commit()

    client.get(BASE + '/routes/map')
    with app.app_context():
        swieze = [rid for rid in (r1, r2) if Route.query.get(rid).geometry_hash != 'nieaktualny']
    assert len(swieze) == 1

    client.get(BASE + '/routes/map')
    with app.app_context():
        assert all(Route.query.get(rid).geometry_hash != 'nieaktualny' for rid in (r1, r2))


def test_mapa_sortowanie_stabilne_przy_tym_samym_dniu(client, app):
    """M8: /routes/map sortuje po (date_from, id) — przy tym samym dniu kolejność
    (a więc i kolory tras w UI) musi być stabilna między żądaniami."""
    with app.app_context():
        a = zamowienie(sposob=s.TRANSPORT).id
        b = zamowienie(sposob=s.TRANSPORT).id
    r1 = _nowa(client, name='Pierwsza').get_json()['route']['id']
    r2 = _nowa(client, name='Druga').get_json()['route']['id']
    client.post(BASE + '/routes/%d/stops' % r1, json={'order_ids': [a]})
    client.post(BASE + '/routes/%d/stops' % r2, json={'order_ids': [b]})
    mapa = client.get(BASE + '/routes/map').get_json()['routes']
    assert [t['id'] for t in mapa] == sorted([r1, r2])


# ── R9: walidacja wejścia — nigdy 500 na złych danych ────────────────────────

def test_lista_tras_zla_wartosc_filtrow(client):
    assert client.get(BASE + '/routes?status=nieznany').status_code == 422
    assert client.get(BASE + '/routes?od=nie-data').status_code == 422
    assert client.get(BASE + '/routes?do=nie-data').status_code == 422


def test_cialo_listowe_zamiast_obiektu_to_422(client):
    assert client.post(BASE + '/routes', json=[1, 2]).status_code == 422
    assert client.post(BASE + '/vehicles', json=[1, 2]).status_code == 422
    vid = client.post(BASE + '/vehicles', json={'name': 'X'}).get_json()['vehicle']['id']
    assert client.put(BASE + '/vehicles/%d' % vid, json=[1, 2]).status_code == 422


def test_dostepnosc_do_wczesniej_niz_od_to_422(client):
    r = client.get(BASE + '/availability?date_from=2026-10-05&date_to=2026-10-01')
    assert r.status_code == 422


def test_aktywnosc_pojazdu_wymaga_bool(client):
    vid = client.post(BASE + '/vehicles', json={'name': 'X'}).get_json()['vehicle']['id']
    r = client.post(BASE + '/vehicles/%d/active' % vid, json={'active': 'false'})
    assert r.status_code == 422


def test_za_duzo_zamowien_w_stopach_to_422(client):
    rid = _nowa(client).get_json()['route']['id']
    r = client.post(BASE + '/routes/%d/stops' % rid, json={'order_ids': list(range(1, 502))})
    assert r.status_code == 422


def test_konflikt_rownoczesnego_dodania_to_409(client, app, monkeypatch):
    """
    UNIQUE na prod_route_stops.order_id jako ostatnia linia obrony: dwie osoby
    dodają to samo zamówienie do dwóch różnych tras w tej samej chwili.
    """
    from modules.production.logistics.services import routes as routes_service
    with app.app_context():
        a = zamowienie(sposob=s.TRANSPORT, statusy=('spakowane',)).id
    rid = _nowa(client).get_json()['route']['id']

    def _wybuchnij(*args, **kwargs):
        raise IntegrityError('INSERT', {}, Exception('dup'))

    monkeypatch.setattr(routes_service, 'dodaj_przystanki', _wybuchnij)
    r = client.post(BASE + '/routes/%d/stops' % rid, json={'order_ids': [a]})
    assert r.status_code == 409
    assert 'odśwież listę' in r.get_json()['error']


# ── Fix round 1 ───────────────────────────────────────────────────────────

def test_konflikt_tworzenia_trasy_ma_ogolny_komunikat(client, monkeypatch):
    """M6: IntegrityError na POST /routes (tworzenie) dostaje ogólny tekst —
    jedyny realny wyścig tam to FK na pojeździe/kierowcy, nie UNIQUE przystanku."""
    from modules.production.logistics.services import routes as routes_service

    def _wybuchnij(*args, **kwargs):
        raise IntegrityError('INSERT', {}, Exception('fk'))

    monkeypatch.setattr(routes_service, 'utworz', _wybuchnij)
    r = _nowa(client)
    assert r.status_code == 409
    assert 'Dane trasy zmieniły się' in r.get_json()['error']
    assert 'odśwież listę' not in r.get_json()['error']


def test_complete_cialo_niepoprawne_to_422_i_bez_zmian(client, app):
    """M1: ciało, które NIE jest poprawnym JSON-em (zły Content-Type albo zły
    JSON) nie może po cichu przejść jako „brak ciała" = „wszystko dostarczone”."""
    with app.app_context():
        a = zamowienie(sposob=s.TRANSPORT, statusy=('spakowane',)).id
        b = zamowienie(sposob=s.TRANSPORT, statusy=('spakowane',)).id
    rid = _nowa(client).get_json()['route']['id']
    client.post(BASE + '/routes/%d/stops' % rid, json={'order_ids': [a, b]})
    client.post(BASE + '/routes/%d/approve' % rid)
    r = client.post(BASE + '/routes/%d/complete' % rid, data='nie-json', content_type='text/plain')
    assert r.status_code == 422
    with app.app_context():
        trasa = Route.query.get(rid)
        assert trasa.status == 'zatwierdzona'
        assert {stop.order_id for stop in trasa.stops} == {a, b}


def test_wykonana_trasa_nie_przelicza_przebiegu(client, app):
    """M4 (spec 8.2): trasa WYKONANA jest tylko do odczytu — samo obejrzenie jej
    nie może nadpisać przebiegu/dystansu w cache."""
    with app.app_context():
        a = zamowienie(sposob=s.TRANSPORT, statusy=('spakowane',)).id
    rid = _nowa(client).get_json()['route']['id']
    client.post(BASE + '/routes/%d/stops' % rid, json={'order_ids': [a]})
    client.post(BASE + '/routes/%d/approve' % rid)
    client.post(BASE + '/routes/%d/complete' % rid)
    with app.app_context():
        trasa = Route.query.get(rid)
        trasa.geometry_hash = 'nieaktualny'
        trasa.distance_km = 123
        db.session.commit()
    assert client.get(BASE + '/routes/%d' % rid).status_code == 200
    with app.app_context():
        trasa = Route.query.get(rid)
        assert trasa.geometry_hash == 'nieaktualny' and float(trasa.distance_km) == 123


def test_lista_tras_bez_lawiny_zapytan(client, app):
    """I1: liczba zapytań na GET /routes NIE rośnie z liczbą tras/przystanków —
    selectinload zbiorczy zamiast R × (3 + S) zapytań osobno na trasę."""
    from sqlalchemy import event
    with app.app_context():
        for i in range(3):
            vid = pojazd().id
            trasa = routes.utworz({'name': 'Trasa %d' % i, 'date_from': '2026-10-01',
                                   'vehicle_id': vid})
            zam = [zamowienie(sposob=s.TRANSPORT, statusy=('spakowane',)).id for _ in range(3)]
            routes.dodaj_przystanki(trasa, zam)
            db.session.commit()
        engine = db.engine
    zapytania = []
    sluchacz = lambda *a, **k: zapytania.append(1)  # noqa: E731
    event.listen(engine, 'before_cursor_execute', sluchacz)
    try:
        r = client.get(BASE + '/routes?od=2026-01-01')
    finally:
        event.remove(engine, 'before_cursor_execute', sluchacz)
    assert r.status_code == 200 and len(r.get_json()['routes']) == 3
    # Stała liczba, niezależna od liczby tras/przystanków: trasy + selectinload
    # (przystanki, pojazd, kierowca), zamówienia + selectinload (pozycje,
    # konfiguracje), punkty geo.
    assert len(zapytania) <= 9, zapytania


def test_szczegoly_trasy_bez_lawiny_zapytan(client, app):
    """M2: szczegóły trasy ładują pozycje zamówień jednym zapytaniem (jak
    lista.pobierz), nie zamówienie po zamówieniu."""
    from sqlalchemy import event
    with app.app_context():
        zam = [zamowienie(sposob=s.TRANSPORT, statusy=('spakowane', 'czeka_na_wyciecie')).id
               for _ in range(4)]
    rid = _nowa(client).get_json()['route']['id']
    client.post(BASE + '/routes/%d/stops' % rid, json={'order_ids': zam})
    engine = db.engine
    zapytania = []
    sluchacz = lambda *a, **k: zapytania.append(1)  # noqa: E731
    event.listen(engine, 'before_cursor_execute', sluchacz)
    try:
        r = client.get(BASE + '/routes/%d' % rid)
    finally:
        event.remove(engine, 'before_cursor_execute', sluchacz)
    assert r.status_code == 200 and len(r.get_json()['route']['przystanki']) == 4
    assert len(zapytania) <= 8, zapytania


def test_lista_tras_domyslne_okno_wykonanych(client, app):
    """I1 (ruling okna domyślnego): bez `od` trasy WYKONANE starsze niż 30 dni
    znikają z listy, świeże i robocze/zatwierdzone (nawet bardzo stare) zostają;
    `od` jawnie podane wyłącza okno."""
    with app.app_context():
        dzis = get_local_now().date()
        a = zamowienie(sposob=s.TRANSPORT, statusy=('spakowane',)).id
        b = zamowienie(sposob=s.TRANSPORT, statusy=('spakowane',)).id

        stara = routes.utworz({'name': 'Stara wykonana',
                               'date_from': (dzis - timedelta(days=60)).isoformat()})
        routes.dodaj_przystanki(stara, [a])
        routes.zatwierdz(stara)
        routes.wykonaj(stara)
        db.session.commit()

        swieza = routes.utworz({'name': 'Świeża wykonana',
                                'date_from': (dzis - timedelta(days=5)).isoformat()})
        routes.dodaj_przystanki(swieza, [b])
        routes.zatwierdz(swieza)
        routes.wykonaj(swieza)
        db.session.commit()

        stara_robocza = routes.utworz({'name': 'Stara robocza',
                                       'date_from': (dzis - timedelta(days=400)).isoformat()})
        db.session.commit()
        sid, swid, srid = stara.id, swieza.id, stara_robocza.id

    bez_filtrow = {t['id'] for t in client.get(BASE + '/routes').get_json()['routes']}
    assert swid in bez_filtrow and srid in bez_filtrow and sid not in bez_filtrow

    tylko_wykonane = {t['id'] for t in client.get(BASE + '/routes?status=wykonana').get_json()['routes']}
    assert swid in tylko_wykonane and sid not in tylko_wykonane

    z_jawnym_od = {t['id'] for t in client.get(BASE + '/routes?od=2000-01-01').get_json()['routes']}
    assert sid in z_jawnym_od


def test_edycja_trasy_sukces_i_konflikty(client, app):
    """M7: PUT /routes/<id> — sukces na roboczej, 422 na ciele-liście, 409 na
    zajętym pojeździe, 409 na trasie zatwierdzonej."""
    with app.app_context():
        v1 = pojazd().id
        v2 = pojazd().id
        a = zamowienie(sposob=s.TRANSPORT, statusy=('spakowane',)).id
    rid = _nowa(client, vehicle_id=v1).get_json()['route']['id']

    r = client.put(BASE + '/routes/%d' % rid, json={'name': 'Nowa nazwa', 'date_from': '2026-10-01'})
    assert r.status_code == 200 and r.get_json()['route']['nazwa'] == 'Nowa nazwa'

    assert client.put(BASE + '/routes/%d' % rid, json=[1, 2]).status_code == 422

    _nowa(client, name='Druga', vehicle_id=v2)
    r = client.put(BASE + '/routes/%d' % rid,
                   json={'name': 'Nowa nazwa', 'date_from': '2026-10-01', 'vehicle_id': v2})
    assert r.status_code == 409

    client.post(BASE + '/routes/%d/stops' % rid, json={'order_ids': [a]})
    client.post(BASE + '/routes/%d/approve' % rid)
    r = client.put(BASE + '/routes/%d' % rid, json={'name': 'Inna', 'date_from': '2026-10-01'})
    assert r.status_code == 409


def test_cofniecie_zatwierdzenia(client, app):
    """M7: POST /routes/<id>/revert."""
    with app.app_context():
        a = zamowienie(sposob=s.TRANSPORT, statusy=('spakowane',)).id
    rid = _nowa(client).get_json()['route']['id']
    client.post(BASE + '/routes/%d/stops' % rid, json={'order_ids': [a]})
    client.post(BASE + '/routes/%d/approve' % rid)
    r = client.post(BASE + '/routes/%d/revert' % rid)
    assert r.status_code == 200 and r.get_json()['route']['status'] == 'robocza'


def test_usuniecie_przystanku_z_roboczej(client, app):
    """M7: skuteczne DELETE /routes/<id>/stops/<order_id> na trasie roboczej."""
    with app.app_context():
        a = zamowienie(sposob=s.TRANSPORT, statusy=('spakowane',)).id
    rid = _nowa(client).get_json()['route']['id']
    client.post(BASE + '/routes/%d/stops' % rid, json={'order_ids': [a]})
    r = client.delete(BASE + '/routes/%d/stops/%d' % (rid, a))
    assert r.status_code == 200
    assert r.get_json()['route']['podsumowanie']['przystanki'] == 0


def test_lista_tras_sortowanie_i_filtr_dat(client, app):
    """M7: GET /routes — kolejność (robocza, zatwierdzona, wykonana) po statusie,
    potem date_from; filtr od/do zawęża do zakresu."""
    with app.app_context():
        a = zamowienie(sposob=s.TRANSPORT, statusy=('spakowane',)).id
        b = zamowienie(sposob=s.TRANSPORT, statusy=('spakowane',)).id
    r_wyk = _nowa(client, name='Wykonana', date_from='2026-09-01').get_json()['route']['id']
    client.post(BASE + '/routes/%d/stops' % r_wyk, json={'order_ids': [a]})
    client.post(BASE + '/routes/%d/approve' % r_wyk)
    client.post(BASE + '/routes/%d/complete' % r_wyk)

    r_zatw = _nowa(client, name='Zatwierdzona', date_from='2026-10-05').get_json()['route']['id']
    client.post(BASE + '/routes/%d/stops' % r_zatw, json={'order_ids': [b]})
    client.post(BASE + '/routes/%d/approve' % r_zatw)

    r_rob = _nowa(client, name='Robocza', date_from='2026-10-02').get_json()['route']['id']

    trasy = client.get(BASE + '/routes?od=2026-01-01').get_json()['routes']
    assert [t['status'] for t in trasy] == ['robocza', 'zatwierdzona', 'wykonana']
    assert [t['id'] for t in trasy] == [r_rob, r_zatw, r_wyk]

    wynik = client.get(BASE + '/routes?od=2026-10-01&do=2026-10-31').get_json()['routes']
    assert sorted(t['id'] for t in wynik) == sorted([r_zatw, r_rob])


def test_dostepnosc_route_id_wyklucza_wlasna_trase(client, app):
    """M7: ?route_id= w /availability pomija zajętość własnej trasy (edycja)."""
    with app.app_context():
        vid = pojazd().id
    rid = _nowa(client, vehicle_id=vid).get_json()['route']['id']
    bez_wykluczenia = client.get(BASE + '/availability?date_from=2026-10-01&date_to=2026-10-01').get_json()
    assert bez_wykluczenia['pojazdy'][0]['zajety'] is True
    z_wykluczeniem = client.get(
        BASE + '/availability?date_from=2026-10-01&date_to=2026-10-01&route_id=%d' % rid).get_json()
    assert z_wykluczeniem['pojazdy'][0]['zajety'] is False


def test_dostepnosc_route_id_niepoprawny_to_422(client):
    """M8: ?route_id=abc ma być odmową, nie cichym zignorowaniem filtra."""
    r = client.get(BASE + '/availability?date_from=2026-10-01&date_to=2026-10-01&route_id=abc')
    assert r.status_code == 422


def test_404_nieznany_pojazd(client):
    """M7: 404 dla PUT/active na nieistniejącym pojeździe."""
    assert client.put(BASE + '/vehicles/999999', json={'name': 'X'}).status_code == 404
    assert client.post(BASE + '/vehicles/999999/active', json={'active': True}).status_code == 404


def test_404_akcje_na_nieznanej_trasie(client):
    """M7: 404 dla każdej akcji na nieistniejącej trasie."""
    nid = 999999
    assert client.get(BASE + '/routes/%d' % nid).status_code == 404
    assert client.put(BASE + '/routes/%d' % nid,
                      json={'name': 'X', 'date_from': '2026-10-01'}).status_code == 404
    assert client.delete(BASE + '/routes/%d' % nid).status_code == 404
    assert client.post(BASE + '/routes/%d/stops' % nid, json={'order_ids': [1]}).status_code == 404
    assert client.delete(BASE + '/routes/%d/stops/1' % nid).status_code == 404
    assert client.put(BASE + '/routes/%d/stops/order' % nid, json={'order_ids': [1]}).status_code == 404
    assert client.post(BASE + '/routes/%d/approve' % nid).status_code == 404
    assert client.post(BASE + '/routes/%d/revert' % nid).status_code == 404
    assert client.post(BASE + '/routes/%d/complete' % nid).status_code == 404
    assert client.post(BASE + '/routes/%d/restore' % nid).status_code == 404
