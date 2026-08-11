# -*- coding: utf-8 -*-
"""
Profile pracowników — katalog, sesje i atrybucja pracy.

Projekt: docs/worker-profiles-backend.md (etapy 1-3).

Najważniejszy test w tym pliku to
test_complete_tworzy_event_z_atrybucja: pilnuje naprawy z §8 (pułapka nr 1).
Przed nią mobilne /orders/<id>/complete NIE tworzyło żadnego wpisu
w prod_station_events, więc po usunięciu paneli webowych statystyki stanowisk
gubiłyby całą pracę zamykaną przyciskiem "gotowe".
"""
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from flask import Flask
from sqlalchemy.pool import StaticPool

from extensions import db
from modules.production.models import (
    ProcessedMobileOperation, ProductionConfig, ProductionConfiguration,
    ProductionDevice, ProductionOrder, ProductionProduct, ProductionReworkLog,
    ProductionStationEvent, ProductionStationEventWorker, ProductionWorker,
    ProductionWorkerSession, get_local_now,
)
from modules.production.routers.mobile_api import mobile_api_bp
from modules.production.services import worker_service
from modules.production.services.mobile_api_service import generate_token
from modules.users.models import User
# Import wymagany, żeby topologiczne sortowanie FK w create_all znalazło
# tabelę 'users' — ten sam powód co w test_mobile_complete_bl_sync_queue.py.
from modules.calculator.models import Multiplier  # noqa: F401
from modules.clients.models import Client  # noqa: F401
import modules.quotes.models  # noqa: F401

_TABLES = [m.__table__ for m in (
    User, ProductionDevice, ProductionConfig, ProcessedMobileOperation,
    ProductionOrder, ProductionProduct, ProductionConfiguration, ProductionReworkLog,
    ProductionWorker, ProductionWorkerSession, ProductionStationEvent,
    ProductionStationEventWorker,
)]

# SQLite nie zna LONGTEXT — to samo obejście co w pozostałych testach mobilnych.
ProductionOrder.__table__.c.shipping_label_base64.type = db.Text()


@pytest.fixture()
def app():
    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        'poolclass': StaticPool,
        'connect_args': {'check_same_thread': False},
    }
    app.config['API_MOBILE'] = {
        'jwt_secret': 'x' * 64,
        'token_ttl_days': 365,
        'ip_whitelist': [],
        'min_supported_app_version': '0.0.0',
    }
    app.register_blueprint(mobile_api_bp, url_prefix='/api/mobile')
    db.init_app(app)
    with app.app_context():
        db.metadata.create_all(bind=db.engine, tables=_TABLES)
        yield app
        db.session.remove()


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture(autouse=True)
def czysty_cache_configu():
    """
    ProductionConfigService trzyma konfigurację w singletonie z cache'em —
    bez tego wartość ustawiona w jednym teście przeciekłaby do następnego.
    """
    from modules.production.services.config_service import invalidate_config_cache
    invalidate_config_cache()
    yield
    invalidate_config_cache()


# ============================================================================
# POMOCNICZE
# ============================================================================

def _token(app, station_code='gluing', device_id='TABLET-1'):
    with app.app_context():
        device = ProductionDevice(device_id=device_id, device_name='Tablet',
                                  station_code=station_code)
        db.session.add(device)
        db.session.commit()
        return generate_token(device)


def _naglowki(token, worker_ids=None, operation_id=None):
    naglowki = {'Authorization': 'Bearer ' + token, 'X-App-Version': '1.0.0'}
    if worker_ids is not None:
        naglowki['X-Worker-Ids'] = worker_ids
    if operation_id:
        naglowki['X-Operation-Id'] = operation_id
    return naglowki


def _pracownicy(app, ilu=2, aktywni=True):
    with app.app_context():
        dodani = []
        for i in range(ilu):
            w = ProductionWorker(first_name=f'Imie{i}', last_name=f'Nazwisko{i}',
                                 is_active=aktywni, sort_order=i)
            db.session.add(w)
            dodani.append(w)
        db.session.commit()
        return [w.id for w in dodani]


def _produkt(app, status='czeka_na_sklejanie', quantity=10):
    with app.app_context():
        order = ProductionOrder(baselinker_order_id=990001,
                                internal_order_number='26/00042')
        db.session.add(order)
        db.session.flush()
        produkt = ProductionProduct(
            order_id=order.id, short_product_id='26042_1',
            product_sequence_in_order=1, original_product_name='Blat dębowy',
            quantity=quantity, current_status=status)
        db.session.add(produkt)
        db.session.commit()
        return produkt.id


def _ustaw_config(app, klucz, wartosc, typ='boolean'):
    from modules.production.services.config_service import invalidate_config_cache
    with app.app_context():
        wpis = ProductionConfig.query.filter_by(config_key=klucz).first()
        if wpis:
            wpis.config_value = str(wartosc)
        else:
            db.session.add(ProductionConfig(config_key=klucz, config_value=str(wartosc),
                                            config_type=typ))
        db.session.commit()
    invalidate_config_cache()


# ============================================================================
# KATALOG
# ============================================================================

def test_katalog_zwraca_aktywnych_i_konfiguracje(client, app):
    token = _token(app)
    _pracownicy(app, 2)
    with app.app_context():
        db.session.add(ProductionWorker(first_name='Zwolniony', last_name='Kowalski',
                                        is_active=False))
        db.session.commit()

    odp = client.get('/api/mobile/workers', headers=_naglowki(token))

    assert odp.status_code == 200
    dane = odp.get_json()
    assert [w['first_name'] for w in dane['workers']] == ['Imie0', 'Imie1']
    # Apka nie hardkoduje żadnej z tych wartości — muszą przyjść z katalogiem.
    assert dane['selection_required'] is False
    assert dane['idle_timeout_minutes'] == 120
    assert dane['night_cutoff'] == '23:00'
    assert dane['quick_pick_count'] == 8
    assert dane['catalog_version']


def test_katalog_zwraca_inicjaly_i_kolor_bez_zdjecia(client, app):
    token = _token(app)
    _pracownicy(app, 1)

    dane = client.get('/api/mobile/workers', headers=_naglowki(token)).get_json()
    kafelek = dane['workers'][0]

    assert kafelek['initials'] == 'IN'
    assert kafelek['avatar_url'] is None
    assert kafelek['color_hex'].startswith('#')
    assert kafelek['allowed_stations'] == []   # brak ograniczeń = wszystkie


def test_katalog_odpowiada_304_gdy_nic_sie_nie_zmienilo(client, app):
    token = _token(app)
    _pracownicy(app, 1)

    pierwsza = client.get('/api/mobile/workers', headers=_naglowki(token))
    etag = pierwsza.headers['ETag']

    naglowki = _naglowki(token)
    naglowki['If-None-Match'] = etag
    druga = client.get('/api/mobile/workers', headers=naglowki)

    assert druga.status_code == 304


# ============================================================================
# SESJE
# ============================================================================

def test_start_sesji_tworzy_wiersz_na_pracownika(client, app):
    token = _token(app)
    ids = _pracownicy(app, 2)

    odp = client.post('/api/mobile/sessions/start', headers=_naglowki(token),
                      json={'worker_ids': ids, 'session_group': 'grupa-1'})

    assert odp.status_code == 201
    dane = odp.get_json()
    assert dane['session_group'] == 'grupa-1'
    assert len(dane['sessions']) == 2

    with app.app_context():
        sesje = ProductionWorkerSession.query.all()
        assert len(sesje) == 2
        assert {s.worker_id for s in sesje} == set(ids)
        assert all(s.station_code == 'gluing' for s in sesje)
        assert all(s.work_date == s.started_at.date() for s in sesje)
        urzadzenie = ProductionDevice.query.first()
        assert urzadzenie.last_worker_session_at is not None


def test_start_sesji_domyka_poprzednia_obsade_jako_replaced(client, app):
    token = _token(app)
    ids = _pracownicy(app, 2)

    client.post('/api/mobile/sessions/start', headers=_naglowki(token),
                json={'worker_ids': [ids[0]], 'session_group': 'zmiana-1'})
    client.post('/api/mobile/sessions/start', headers=_naglowki(token),
                json={'worker_ids': [ids[1]], 'session_group': 'zmiana-2'})

    with app.app_context():
        pierwsza = ProductionWorkerSession.query.filter_by(session_group='zmiana-1').one()
        druga = ProductionWorkerSession.query.filter_by(session_group='zmiana-2').one()
        assert pierwsza.ended_at is not None
        assert pierwsza.end_reason == 'replaced'
        assert druga.ended_at is None


def test_start_sesji_nie_przyjmuje_czasu_z_przyszlosci(client, app):
    """started_at przycinane do min(client, now) — tablet mógł mieć zły zegar."""
    token = _token(app)
    ids = _pracownicy(app, 1)
    przyszlosc = (get_local_now() + timedelta(days=2)).isoformat()

    client.post('/api/mobile/sessions/start', headers=_naglowki(token),
                json={'worker_ids': ids, 'session_group': 'g', 'started_at': przyszlosc})

    with app.app_context():
        sesja = ProductionWorkerSession.query.one()
        assert sesja.started_at <= get_local_now() + timedelta(minutes=1)


def test_started_at_bez_strefy_jest_czytany_jako_utc(client, app):
    """
    KONTRAKT Z APKĄ: timestamp bez offsetu jest interpretowany jako UTC
    (parse_since_ts, tak samo jak w delta sync). Apka MUSI wysyłać ISO
    z offsetem albo z 'Z' — inaczej sesja rozpoczęta o 6:12 czasu lokalnego
    zapisze się jako 8:12 i zawyży czas pracy o różnicę stref.
    """
    token = _token(app)
    ids = _pracownicy(app, 1)

    client.post('/api/mobile/sessions/start', headers=_naglowki(token),
                json={'worker_ids': ids, 'session_group': 'g',
                      'started_at': '2026-08-11T06:12:00+02:00'})

    with app.app_context():
        sesja = ProductionWorkerSession.query.one()
        assert sesja.started_at == datetime(2026, 8, 11, 6, 12)
        assert sesja.work_date == datetime(2026, 8, 11).date()


def test_start_sesji_odrzuca_nieaktywnego_pracownika(client, app):
    token = _token(app)
    ids = _pracownicy(app, 1, aktywni=False)

    odp = client.post('/api/mobile/sessions/start', headers=_naglowki(token),
                      json={'worker_ids': ids, 'session_group': 'g'})

    assert odp.status_code == 409
    assert odp.get_json()['error'] == 'worker_inactive'


def test_start_sesji_jest_idempotentny(client, app):
    token = _token(app)
    ids = _pracownicy(app, 1)
    naglowki = _naglowki(token, operation_id='op-123')

    pierwsza = client.post('/api/mobile/sessions/start', headers=naglowki,
                           json={'worker_ids': ids, 'session_group': 'g'})
    druga = client.post('/api/mobile/sessions/start', headers=naglowki,
                        json={'worker_ids': ids, 'session_group': 'g'})

    assert pierwsza.status_code == 201
    assert druga.status_code == 201
    with app.app_context():
        assert ProductionWorkerSession.query.count() == 1


def test_koniec_sesji_domyka_cala_grupe(client, app):
    token = _token(app)
    ids = _pracownicy(app, 2)
    client.post('/api/mobile/sessions/start', headers=_naglowki(token),
                json={'worker_ids': ids, 'session_group': 'grupa-x'})

    odp = client.post('/api/mobile/sessions/end', headers=_naglowki(token),
                      json={'session_group': 'grupa-x', 'reason': 'manual'})

    assert odp.status_code == 204
    with app.app_context():
        sesje = ProductionWorkerSession.query.all()
        assert all(s.ended_at is not None and s.end_reason == 'manual' for s in sesje)


def test_koniec_sesji_odrzuca_powody_zarezerwowane_dla_backendu(client, app):
    token = _token(app)
    ids = _pracownicy(app, 1)
    client.post('/api/mobile/sessions/start', headers=_naglowki(token),
                json={'worker_ids': ids, 'session_group': 'g'})

    for powod in ('replaced', 'admin'):
        odp = client.post('/api/mobile/sessions/end', headers=_naglowki(token),
                          json={'session_group': 'g', 'reason': powod})
        assert odp.status_code == 422, powod
        assert odp.get_json()['error'] == 'invalid_end_reason'


def test_aktywne_sesje_po_restarcie_apki(client, app):
    token = _token(app)
    ids = _pracownicy(app, 2)
    client.post('/api/mobile/sessions/start', headers=_naglowki(token),
                json={'worker_ids': ids, 'session_group': 'g'})

    dane = client.get('/api/mobile/sessions/active',
                      headers=_naglowki(token)).get_json()

    assert dane['session_group'] == 'g'
    assert len(dane['sessions']) == 2
    assert dane['sessions'][0]['worker_name'] == 'Imie0 Nazwisko0'


# ============================================================================
# WALIDACJA X-Worker-Ids
# ============================================================================

def test_bez_naglowka_przy_wlaczonej_bramce_jest_400(client, app):
    token = _token(app)
    _ustaw_config(app, 'WORKER_SELECTION_REQUIRED', 'true')
    produkt_id = _produkt(app)

    odp = client.patch(f'/api/mobile/orders/{produkt_id}/quantity',
                       headers=_naglowki(token), json={'quantity_done': 3})

    assert odp.status_code == 400
    assert odp.get_json()['error'] == 'worker_ids_required'


def test_bez_naglowka_przy_wylaczonej_bramce_akcja_przechodzi(client, app):
    token = _token(app)
    produkt_id = _produkt(app)

    odp = client.patch(f'/api/mobile/orders/{produkt_id}/quantity',
                       headers=_naglowki(token), json={'quantity_done': 3})

    assert odp.status_code == 200
    with app.app_context():
        assert ProductionStationEvent.query.count() == 1
        assert ProductionStationEventWorker.query.count() == 0


def test_pusty_naglowek_to_422_nie_kill_switch(client, app):
    token = _token(app)
    produkt_id = _produkt(app)

    odp = client.patch(f'/api/mobile/orders/{produkt_id}/quantity',
                       headers=_naglowki(token, worker_ids=''),
                       json={'quantity_done': 3})

    assert odp.status_code == 422
    assert odp.get_json()['error'] == 'invalid_worker_ids'


def test_smieci_w_naglowku_to_422(client, app):
    token = _token(app)
    produkt_id = _produkt(app)

    odp = client.patch(f'/api/mobile/orders/{produkt_id}/quantity',
                       headers=_naglowki(token, worker_ids='abc,def'),
                       json={'quantity_done': 3})

    assert odp.status_code == 422


def test_nieznany_pracownik_to_404(client, app):
    token = _token(app)
    produkt_id = _produkt(app)

    odp = client.patch(f'/api/mobile/orders/{produkt_id}/quantity',
                       headers=_naglowki(token, worker_ids='999'),
                       json={'quantity_done': 3})

    assert odp.status_code == 404
    assert odp.get_json()['error'] == 'worker_not_found'


def test_dezaktywowany_pracownik_to_409(client, app):
    token = _token(app)
    ids = _pracownicy(app, 1)
    produkt_id = _produkt(app)
    with app.app_context():
        ProductionWorker.query.get(ids[0]).deactivate()
        db.session.commit()

    odp = client.patch(f'/api/mobile/orders/{produkt_id}/quantity',
                       headers=_naglowki(token, worker_ids=str(ids[0])),
                       json={'quantity_done': 3})

    assert odp.status_code == 409
    assert odp.get_json()['error'] == 'worker_inactive'


# ============================================================================
# ATRYBUCJA
# ============================================================================

def test_complete_tworzy_event_z_atrybucja(client, app):
    """
    Naprawa pułapki nr 1 (§8): przed nią complete wołał wyłącznie
    complete_task(), które NIE tworzy eventu dla zamykanego stanowiska —
    praca zamknięta przyciskiem "gotowe" nie zostawiała żadnego śladu.
    """
    token = _token(app)
    ids = _pracownicy(app, 2)
    produkt_id = _produkt(app, quantity=10)

    odp = client.post(f'/api/mobile/orders/{produkt_id}/complete',
                      headers=_naglowki(token, worker_ids=f'{ids[0]},{ids[1]}'),
                      json={})

    assert odp.status_code == 200
    with app.app_context():
        event = ProductionStationEvent.query.filter_by(station_code='gluing').one()
        assert event.delta == 10
        assert event.source == 'mobile'

        atrybucje = ProductionStationEventWorker.query.filter_by(event_id=event.id).all()
        assert {a.worker_id for a in atrybucje} == set(ids)
        assert all(str(a.share) == '0.500000' for a in atrybucje)
        assert sum(a.share for a in atrybucje) == 1
        # Atrybucja wskazuje sesję tylko wtedy, gdy sesja istnieje — tu jej nie ma.
        assert all(a.session_id is None for a in atrybucje)


def test_complete_wiaze_atrybucje_z_otwarta_sesja(client, app):
    token = _token(app)
    ids = _pracownicy(app, 1)
    produkt_id = _produkt(app)
    client.post('/api/mobile/sessions/start', headers=_naglowki(token),
                json={'worker_ids': ids, 'session_group': 'g'})

    client.post(f'/api/mobile/orders/{produkt_id}/complete',
                headers=_naglowki(token, worker_ids=str(ids[0])), json={})

    with app.app_context():
        sesja = ProductionWorkerSession.query.one()
        atrybucja = ProductionStationEventWorker.query.one()
        assert atrybucja.session_id == sesja.id
        # Akcja produkcyjna przedłuża sesję — nie ma osobnego heartbeatu.
        assert sesja.last_activity_at >= sesja.started_at


def test_jeden_pracownik_dostaje_caly_udzial(client, app):
    token = _token(app)
    ids = _pracownicy(app, 1)
    produkt_id = _produkt(app)

    client.patch(f'/api/mobile/orders/{produkt_id}/quantity',
                 headers=_naglowki(token, worker_ids=str(ids[0])),
                 json={'quantity_done': 4})

    with app.app_context():
        atrybucja = ProductionStationEventWorker.query.one()
        assert str(atrybucja.share) == '1.000000'


def test_complete_po_odbiciu_wszystkich_sztuk_nie_dubluje_eventu(client, app):
    """delta = 0 nie tworzy eventu, więc statystyki nie liczą pracy dwa razy."""
    token = _token(app)
    ids = _pracownicy(app, 1)
    produkt_id = _produkt(app, quantity=5)

    client.patch(f'/api/mobile/orders/{produkt_id}/quantity',
                 headers=_naglowki(token, worker_ids=str(ids[0])),
                 json={'quantity_done': 5})
    client.post(f'/api/mobile/orders/{produkt_id}/complete',
                headers=_naglowki(token, worker_ids=str(ids[0])), json={})

    with app.app_context():
        eventy = ProductionStationEvent.query.filter_by(station_code='gluing').all()
        assert len(eventy) == 1
        assert eventy[0].delta == 5


def test_complete_nie_cofa_sztuk_gdy_quantity_spadlo(client, app):
    """
    quantity potrafi SPAŚĆ poniżej już odbitych sztuk: doróbka zabiera sztuki
    oryginałowi, sync Baselinkera koryguje zamówienie w dół. Wcześniej
    mark_order_complete() przypisywał quantity twardo, więc kolejne "gotowe"
    dawało delta < 0 — kasowało historyczny quantity_done, wpisywało do audytu
    fałszywe "cofnięcie" i odejmowało pracownikowi sztuki w raporcie imiennym.
    """
    token = _token(app)
    ids = _pracownicy(app, 1)
    produkt_id = _produkt(app, quantity=10)
    naglowki = _naglowki(token, worker_ids=str(ids[0]))

    client.post(f'/api/mobile/orders/{produkt_id}/complete', headers=naglowki, json={})

    with app.app_context():
        produkt = ProductionProduct.query.get(produkt_id)
        produkt.quantity = 7            # doróbka / korekta zamówienia
        db.session.commit()

    client.post(f'/api/mobile/orders/{produkt_id}/complete', headers=naglowki, json={})

    with app.app_context():
        eventy = ProductionStationEvent.query.filter_by(station_code='gluing').all()
        assert all(e.delta > 0 for e in eventy), \
            f'ujemne delty: {[e.delta for e in eventy]}'
        # Drugie "gotowe" nie ma czego dodać, więc nie powstaje nowy event
        assert len(eventy) == 1
        assert eventy[0].delta == 10
        # Historyczny dorobek stanowiska zostaje nietknięty
        assert ProductionProduct.query.get(produkt_id).quantity_done_gluing == 10


def test_complete_domyka_brakujace_sztuki_normalnie(client, app):
    """Kontrola do testu wyżej: przy niepełnym odbiciu complete dalej dolicza resztę."""
    token = _token(app)
    ids = _pracownicy(app, 1)
    produkt_id = _produkt(app, quantity=10)
    naglowki = _naglowki(token, worker_ids=str(ids[0]))

    client.patch(f'/api/mobile/orders/{produkt_id}/quantity',
                 headers=naglowki, json={'quantity_done': 4})
    client.post(f'/api/mobile/orders/{produkt_id}/complete', headers=naglowki, json={})

    with app.app_context():
        eventy = ProductionStationEvent.query.filter_by(
            station_code='gluing').order_by(ProductionStationEvent.id).all()
        assert [e.delta for e in eventy] == [4, 6]
        assert ProductionProduct.query.get(produkt_id).quantity_done_gluing == 10


def test_reject_zapisuje_pierwszego_pracownika_w_audycie(client, app):
    token = _token(app, station_code='formatting')
    ids = _pracownicy(app, 2)
    produkt_id = _produkt(app, status='czeka_na_formatowanie', quantity=10)

    odp = client.post(f'/api/mobile/orders/{produkt_id}/reject',
                      headers=_naglowki(token, worker_ids=f'{ids[0]},{ids[1]}'),
                      json={'quantity': 2, 'reason_category': 'wymiary'})

    assert odp.status_code == 200
    with app.app_context():
        wpis = ProductionReworkLog.query.one()
        assert wpis.worker_id == ids[0]
        # Doróbka nie generuje eventu stanowiskowego, więc nie ma atrybucji dzielonej.
        assert ProductionStationEventWorker.query.count() == 0


def test_complete_nadal_kolejkuje_sync_baselinkera(client, app, monkeypatch):
    """
    Regresja po zmianie kolejności w mark_order_complete: hook BL musi zostać.
    Duplikuje intencję test_mobile_complete_bl_sync_queue.py, ale tutaj
    z atrybucją w tle — to ta ścieżka się zmieniła.
    """
    token = _token(app, station_code='packaging')
    ids = _pracownicy(app, 1)
    produkt_id = _produkt(app, status='czeka_na_pakowanie')

    zaplanowane = []
    monkeypatch.setattr(
        'modules.production.services.baselinker_status_sync.schedule_after_station_complete',
        lambda numer, stanowisko: zaplanowane.append((numer, stanowisko)))

    client.post(f'/api/mobile/orders/{produkt_id}/complete',
                headers=_naglowki(token, worker_ids=str(ids[0])), json={})

    assert zaplanowane == [('26/00042', 'packaging')]


# ============================================================================
# DOMYKANIE ZAPOMNIANYCH SESJI (cron)
# ============================================================================

def test_cron_domyka_sesje_po_bezczynnosci(app):
    ids = _pracownicy(app, 1)
    with app.app_context():
        teraz = datetime(2026, 8, 11, 14, 0)
        db.session.add(ProductionWorkerSession(
            worker_id=ids[0], station_code='gluing', session_group='g',
            started_at=teraz - timedelta(hours=5),
            last_activity_at=teraz - timedelta(hours=4),
            work_date=teraz.date()))
        db.session.commit()

        wynik = worker_service.close_stale_sessions(now=teraz)

        sesja = ProductionWorkerSession.query.one()
        assert wynik['idle_timeout'] == 1
        assert sesja.end_reason == 'idle_timeout'
        # Koniec ustawiony na moment faktycznego wygaśnięcia, nie na czas
        # uruchomienia crona — opóźniony cron nie zawyża czasu pracy.
        assert sesja.ended_at == teraz - timedelta(hours=2)


def test_cron_domyka_sesje_po_nocnym_cutoffie(app):
    ids = _pracownicy(app, 1)
    with app.app_context():
        wczoraj = datetime(2026, 8, 10, 20, 0)
        db.session.add(ProductionWorkerSession(
            worker_id=ids[0], station_code='gluing', session_group='g',
            started_at=wczoraj, last_activity_at=wczoraj,
            work_date=wczoraj.date()))
        db.session.commit()

        wynik = worker_service.close_stale_sessions(now=datetime(2026, 8, 11, 6, 0))

        sesja = ProductionWorkerSession.query.one()
        assert wynik['night_cutoff'] == 1
        assert sesja.end_reason == 'night_cutoff'
        assert sesja.ended_at == datetime(2026, 8, 10, 23, 0)


def test_cron_nie_rusza_swiezych_sesji(app):
    ids = _pracownicy(app, 1)
    with app.app_context():
        teraz = datetime(2026, 8, 11, 14, 0)
        db.session.add(ProductionWorkerSession(
            worker_id=ids[0], station_code='gluing', session_group='g',
            started_at=teraz - timedelta(minutes=30),
            last_activity_at=teraz - timedelta(minutes=5),
            work_date=teraz.date()))
        db.session.commit()

        wynik = worker_service.close_stale_sessions(now=teraz)

        assert wynik == {'night_cutoff': 0, 'idle_timeout': 0}
        assert ProductionWorkerSession.query.one().ended_at is None


def test_cron_jest_idempotentny(app):
    ids = _pracownicy(app, 1)
    with app.app_context():
        teraz = datetime(2026, 8, 11, 14, 0)
        db.session.add(ProductionWorkerSession(
            worker_id=ids[0], station_code='gluing', session_group='g',
            started_at=teraz - timedelta(hours=5),
            last_activity_at=teraz - timedelta(hours=4),
            work_date=teraz.date()))
        db.session.commit()

        worker_service.close_stale_sessions(now=teraz)
        drugi_przebieg = worker_service.close_stale_sessions(now=teraz)

        assert drugi_przebieg == {'night_cutoff': 0, 'idle_timeout': 0}


# ============================================================================
# KATALOG — CRUD I DEZAKTYWACJA
# ============================================================================

def test_dezaktywacja_domyka_otwarte_sesje(app):
    ids = _pracownicy(app, 1)
    with app.app_context():
        worker_service.start_session(ids, 'gluing', device_id='TABLET-1',
                                     session_group='g')

        worker_service.deactivate_worker(ids[0])

        pracownik = ProductionWorker.query.get(ids[0])
        sesja = ProductionWorkerSession.query.one()
        assert pracownik.is_active is False
        assert pracownik.deactivated_at is not None
        assert sesja.end_reason == 'admin'


def test_walidacja_nieznanego_stanowiska_w_katalogu(app):
    with app.app_context():
        with pytest.raises(worker_service.WorkerError) as exc:
            worker_service.create_worker('Adam', 'Kowalski',
                                         allowed_stations=['nieistniejace'])
        assert exc.value.error_code == 'invalid_station_code'


def test_pracownik_z_ograniczeniem_stanowisk(app):
    with app.app_context():
        worker = worker_service.create_worker('Adam', 'Kowalski',
                                              allowed_stations=['gluing', 'assembly'])
        assert worker.allowed_stations == 'gluing,assembly'
        assert worker.can_work_at('gluing') is True
        assert worker.can_work_at('packaging') is False


# ============================================================================
# ZAKŁADKA PANELU CRM
# ============================================================================

def test_zakladka_pracownikow_renderuje_sie(app):
    """
    Renderowanie templatki zakładki — łapie błędy Jinja (literówki w polach,
    tojson na obiekcie), których testy API nie dotykają, bo zwracają JSON.
    """
    from flask import render_template
    from modules.production.routers.api.workers_api import _serialize_worker

    ids = _pracownicy(app, 1)
    with app.app_context():
        worker_service.start_session(ids, 'gluing', device_id='TABLET-1',
                                     session_group='g')
        pracownicy = [_serialize_worker(w) for w in worker_service.list_workers(True)]
        sesje = [worker_service.serialize_session_for_panel(s)
                 for s in worker_service.get_active_sessions()]
        konfiguracja = worker_service.get_worker_config()

    szablonowa_app = Flask(
        __name__,
        template_folder=os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'modules', 'production', 'templates'))

    with szablonowa_app.test_request_context():
        html = render_template('components/workers-tab-content.html',
                               workers=pracownicy, active_sessions=sesje,
                               config=konfiguracja,
                               station_choices=[('gluing', 'Sklejanie'),
                                                ('packaging', 'Pakowanie')],
                               crm_users=[{'id': 1, 'label': 'admin@woodpower.pl'}])

    assert 'Imie0 Nazwisko0' in html
    assert 'IN' in html                      # kafelek z inicjałami
    assert 'TABLET-1' in html                # sekcja "kto teraz na hali"
    assert 'Dodaj pracownika' in html
    # Komunikat o kill-switchu ma być po ludzku i odsyłać do konkretnego miejsca
    # w panelu — bez nazw kluczy konfiguracyjnych, których nikt na hali nie zna.
    assert 'Wybór pracownika na tablecie jest teraz dobrowolny' in html
    assert 'Wymagaj wyboru pracownika' in html
    assert 'WORKER_SELECTION_REQUIRED' not in html
    assert 'Robota z 7 dni' in html
    assert 'Konto CRM' in html
    # Stanowiska po polsku — użytkownik panelu nie musi znać kodów z API
    assert 'Sklejanie' in html
    assert '>gluing<' not in html


def test_etykiety_stanowisk_sa_po_polsku(app):
    with app.app_context():
        assert worker_service.station_label('gluing') == 'Sklejanie'
        assert worker_service.station_label('cutting') == 'Wycinanie - mikro'
        assert worker_service.station_label('packaging') == 'Pakowanie'
        assert worker_service.station_label('sawmill') == 'Trakownia'
        # Nieznany kod nie wywraca widoku — pokazujemy go surowo
        assert worker_service.station_label('cos_nowego') == 'cos_nowego'
        assert worker_service.station_label(None) == '—'

        kody = [kod for kod, _ in worker_service.station_choices()]
        # Kolejność procesu, nie alfabetyczna
        assert kody[:3] == ['cutting', 'assembly', 'gluing']
        assert all(nazwa != kod for kod, nazwa in worker_service.station_choices())


def test_podsumowanie_roboty_liczy_udzialy_i_pomija_eventy_automatu(app):
    """
    Kolumna "robota z 7 dni" musi dzielić sztuki wg share i pomijać eventy
    stanowisk pominiętych (auto_skip/system) — inaczej sklejacz dostałby
    kredyt za formatowanie, którego nikt nie wykonał.
    """
    ids = _pracownicy(app, 2)
    produkt_id = _produkt(app, quantity=10)

    with app.app_context():
        produkt = ProductionProduct.query.get(produkt_id)
        produkt.volume_m3 = 0.5
        produkt.set_quantity_done('gluing', 8, source='mobile', actor_worker_ids=ids)
        # Event automatu — z atrybucją, żeby sprawdzić, że filtr działa po
        # source, a nie po samym braku wiersza atrybucji.
        produkt.set_quantity_done('formatting', 10, source='auto_skip',
                                  actor_worker_ids=[ids[0]])
        db.session.commit()

        podsumowanie = worker_service.get_workers_activity_summary()

        assert podsumowanie[ids[0]]['pieces'] == 4.0      # 8 sztuk / 2 osoby
        assert podsumowanie[ids[1]]['pieces'] == 4.0
        assert podsumowanie[ids[0]]['m3'] == 2.0          # 0.5 m³ × 8 × 0.5
