# -*- coding: utf-8 -*-
"""API mobilne trakowni — kontrakt dla aplikacji Android."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json
from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest
from flask import Flask
from sqlalchemy.pool import StaticPool

from extensions import db
from modules.production.models import (
    ProcessedMobileOperation, ProductionConfig, ProductionDevice, get_local_now,
)
from modules.production.sawmill import sawmill_mobile_bp
from modules.production.sawmill.models import (
    STATUS_COMPLETED, STATUS_IN_PROGRESS, STATUS_NEW, STATUS_SETTLED,
    SawmillAudit, SawmillCounter, SawmillDelivery, SawmillLog,
    SawmillOrder, SawmillSpecies, SawmillSupplier,
)
from modules.production.services.mobile_api_service import generate_token
from modules.users.models import User
# Sam import User nie wystarcza — to samo uzasadnienie co w test_sawmill_orders.py
# i test_sawmill_numbering.py: modele trakowni mają ForeignKey('users.id')
# (np. SawmillSupplier.created_by_user_id, ProductionConfig.updated_by), więc
# `db.metadata.create_all(bind=..., tables=_TABLES)` wymaga, żeby tabela
# 'users' w ogóle istniała w db.metadata (inaczej NoReferencedTableError przy
# sortowaniu topologicznym FK) — samo dodanie User.__table__ do _TABLES nie
# rusza, dopóki klasa User nie zostanie zaimportowana. Dodatkowo User.multiplier_id
# ma relationship('Multiplier'), a Multiplier siedzi razem z Quote, które ma
# relationship('Client') i relationship('QuoteStatus'); configure_mappers()
# przy pierwszym flush/query próbuje skonfigurować CAŁY rejestr mapperów, więc
# te klasy też muszą być zaimportowane, mimo że sawmill ich w ogóle nie dotyka.
from modules.calculator.models import Multiplier  # noqa: F401
from modules.clients.models import Client  # noqa: F401
import modules.quotes.models  # noqa: F401
from modules.quotes.models import QuoteStatus  # noqa: F401

from modules.production.models import ProductionWorker, ProductionWorkerSession

_TABLES = [m.__table__ for m in (
    User, SawmillSupplier, SawmillSpecies, SawmillCounter, SawmillDelivery,
    SawmillOrder, SawmillLog, SawmillAudit,
    ProductionDevice, ProductionConfig, ProcessedMobileOperation,
    # Atrybucja pomiarów do pracownika — FK z prod_sawmill_logs.worker_id
    ProductionWorker, ProductionWorkerSession,
)]

SETTINGS = {
    'min_circumference_cm': 30.0, 'max_circumference_cm': None,
    'min_length_cm': 30.0, 'max_length_cm': 20000.0,
    'decimal_places': 1, 'deviation_threshold_pct': 5.0,
}

POMIAR = {
    'mid_circumference_cm': 125.6,
    'length_cm': 410.0,
}


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
    app.register_blueprint(sawmill_mobile_bp, url_prefix='/api/mobile/sawmill')
    db.init_app(app)
    with app.app_context():
        db.metadata.create_all(bind=db.engine, tables=_TABLES)
        db.session.add(ProductionConfig(
            config_key='sawmill_settings',
            config_value=json.dumps(SETTINGS),
            config_type='json',
        ))
        db.session.commit()
        yield app
        db.session.remove()


@pytest.fixture()
def client(app):
    return app.test_client()


def _urzadzenie(app, station_code='sawmill'):
    with app.app_context():
        device = ProductionDevice(
            device_id='TRAK-1', device_name='Trak', station_code=station_code)
        db.session.add(device)
        db.session.commit()
        return generate_token(device)


def _zlecenie(app, status=STATUS_NEW, deklaracja='80.000'):
    with app.app_context():
        supplier = SawmillSupplier(name='Tartak Nowak sp. z o.o.')
        species = SawmillSpecies(name='Dąb')
        db.session.add_all([supplier, species])
        db.session.flush()
        delivery = SawmillDelivery(
            supplier_id=supplier.id, delivery_date=date(2026, 8, 3),
            invoice_number='FV/2026/0451')
        db.session.add(delivery)
        db.session.flush()
        order = SawmillOrder(
            order_number='TRK/2026/007', delivery_id=delivery.id,
            species_id=species.id, declared_volume_m3=Decimal(deklaracja),
            price_per_m3=Decimal('1200.00'), status=status,
            notes='UWAGA: wg WZ 80 m3',
        )
        db.session.add(order)
        db.session.commit()
        return order.id


def _naglowki(token, operation_id=None, worker_ids=None):
    h = {'Authorization': 'Bearer ' + token, 'X-App-Version': '1.0.0'}
    if operation_id:
        h['X-Operation-Id'] = operation_id
    if worker_ids is not None:
        h['X-Worker-Ids'] = worker_ids
    return h


def _pracownik(app, imie='Jan', nazwisko='Trakowy'):
    with app.app_context():
        w = ProductionWorker(first_name=imie, last_name=nazwisko)
        db.session.add(w)
        db.session.commit()
        return w.id


# ── Autoryzacja ─────────────────────────────────────────────────────────────

def test_brak_tokenu(client, app):
    _zlecenie(app)
    assert client.get('/api/mobile/sawmill/orders').status_code == 401


def test_urzadzenie_innego_stanowiska_odrzucone(client, app):
    token = _urzadzenie(app, station_code='cutting')
    _zlecenie(app)
    r = client.get('/api/mobile/sawmill/orders', headers=_naglowki(token))
    assert r.status_code == 403
    assert r.get_json()['error'] == 'station_mismatch'


# ── Odczyt ──────────────────────────────────────────────────────────────────

def test_lista_otwartych_zlecen(client, app):
    token = _urzadzenie(app)
    _zlecenie(app)
    r = client.get('/api/mobile/sawmill/orders', headers=_naglowki(token))
    assert r.status_code == 200
    orders = r.get_json()['orders']
    assert len(orders) == 1
    assert orders[0]['order_number'] == 'TRK/2026/007'
    assert orders[0]['supplier_name'] == 'Tartak Nowak sp. z o.o.'


def test_lista_nie_zawiera_deklaracji(client, app):
    """Główny test bezpieczeństwa — na poziomie realnej odpowiedzi HTTP."""
    token = _urzadzenie(app)
    _zlecenie(app)
    r = client.get('/api/mobile/sawmill/orders', headers=_naglowki(token))
    surowo = r.get_data(as_text=True)
    for zakazane in ('declared_volume_m3', 'price_per_m3', 'declared_value',
                     'agreed_volume_m3', 'settlement_notes', 'WZ'):
        assert zakazane not in surowo


def test_zamkniete_zlecenia_nie_sa_na_liscie(client, app):
    token = _urzadzenie(app)
    _zlecenie(app, status=STATUS_COMPLETED)
    r = client.get('/api/mobile/sawmill/orders', headers=_naglowki(token))
    assert r.get_json()['orders'] == []


def test_config_zwraca_limity_bez_progu(client, app):
    token = _urzadzenie(app)
    r = client.get('/api/mobile/sawmill/config', headers=_naglowki(token))
    data = r.get_json()
    assert data['max_length_cm'] == 20000.0
    assert data['decimal_places'] == 1
    assert 'deviation_threshold_pct' not in data


# ── Zapis ───────────────────────────────────────────────────────────────────

def test_dodanie_pomiaru(client, app):
    token = _urzadzenie(app)
    oid = _zlecenie(app)
    body = dict(POMIAR, measured_at='2026-08-05T09:31:12')
    r = client.post('/api/mobile/sawmill/orders/{}/logs'.format(oid),
                    json=body, headers=_naglowki(token, 'op-1'))
    assert r.status_code == 201
    data = r.get_json()
    assert data['log']['volume_m3'] == 0.514699
    assert data['log']['sequence_no'] == 1
    assert data['order']['logs_count'] == 1
    assert data['order']['measured_volume_m3'] == 0.514699


def test_pierwszy_pomiar_przelacza_status(client, app):
    token = _urzadzenie(app)
    oid = _zlecenie(app)
    client.post('/api/mobile/sawmill/orders/{}/logs'.format(oid),
                json=dict(POMIAR, measured_at='2026-08-05T09:31:12'),
                headers=_naglowki(token, 'op-1'))
    with app.app_context():
        assert db.session.query(SawmillOrder).get(oid).status == STATUS_IN_PROGRESS


def test_walidacja_zwraca_422_z_polem(client, app):
    token = _urzadzenie(app)
    oid = _zlecenie(app)
    body = dict(POMIAR, mid_circumference_cm=5.0, measured_at='2026-08-05T09:31:12')
    r = client.post('/api/mobile/sawmill/orders/{}/logs'.format(oid),
                    json=body, headers=_naglowki(token, 'op-1'))
    assert r.status_code == 422
    data = r.get_json()
    assert data['error'] == 'validation_error'
    assert data['field'] == 'mid_circumference_cm'


def test_zapis_do_zamknietego_zlecenia_daje_409(client, app):
    token = _urzadzenie(app)
    oid = _zlecenie(app, status=STATUS_COMPLETED)
    r = client.post('/api/mobile/sawmill/orders/{}/logs'.format(oid),
                    json=dict(POMIAR, measured_at='2026-08-05T09:31:12'),
                    headers=_naglowki(token, 'op-1'))
    assert r.status_code == 409
    assert r.get_json()['error'] == 'order_not_open'


def test_409_nie_jest_zapisywane_w_idempotencji(client, app):
    """
    Sedno ścieżki ratunku: po cofnięciu zakończenia ten sam X-Operation-Id
    musi wykonać handler, a nie odtworzyć zapamiętane 409.
    """
    token = _urzadzenie(app)
    oid = _zlecenie(app, status=STATUS_COMPLETED)
    body = dict(POMIAR, measured_at='2026-08-05T09:31:12')

    r1 = client.post('/api/mobile/sawmill/orders/{}/logs'.format(oid),
                     json=body, headers=_naglowki(token, 'op-ratunek'))
    assert r1.status_code == 409
    with app.app_context():
        assert ProcessedMobileOperation.query.filter_by(
            operation_id='op-ratunek').first() is None
        order = db.session.query(SawmillOrder).get(oid)
        order.status = STATUS_IN_PROGRESS
        db.session.commit()

    r2 = client.post('/api/mobile/sawmill/orders/{}/logs'.format(oid),
                     json=body, headers=_naglowki(token, 'op-ratunek'))
    assert r2.status_code == 201
    with app.app_context():
        assert SawmillLog.query.count() == 1


def test_idempotencja_nie_duplikuje(client, app):
    token = _urzadzenie(app)
    oid = _zlecenie(app)
    body = dict(POMIAR, measured_at='2026-08-05T09:31:12')
    r1 = client.post('/api/mobile/sawmill/orders/{}/logs'.format(oid),
                     json=body, headers=_naglowki(token, 'op-dubel'))
    r2 = client.post('/api/mobile/sawmill/orders/{}/logs'.format(oid),
                     json=body, headers=_naglowki(token, 'op-dubel'))
    assert r1.status_code == r2.status_code == 201
    assert r1.get_json() == r2.get_json()
    with app.app_context():
        assert SawmillLog.query.count() == 1


def test_edycja_i_usuniecie_pomiaru(client, app):
    token = _urzadzenie(app)
    oid = _zlecenie(app)
    r = client.post('/api/mobile/sawmill/orders/{}/logs'.format(oid),
                    json=dict(POMIAR, measured_at='2026-08-05T09:31:12'),
                    headers=_naglowki(token, 'op-1'))
    log_id = r.get_json()['log']['id']

    r = client.patch('/api/mobile/sawmill/logs/{}'.format(log_id),
                     json=dict(POMIAR, length_cm=420.0),
                     headers=_naglowki(token, 'op-2'))
    assert r.status_code == 200
    assert r.get_json()['log']['length_cm'] == 420.0

    r = client.delete('/api/mobile/sawmill/logs/{}'.format(log_id),
                      headers=_naglowki(token, 'op-3'))
    assert r.status_code == 200
    assert r.get_json()['order']['logs_count'] == 0


def test_zakonczenie_zlecenia(client, app):
    token = _urzadzenie(app)
    oid = _zlecenie(app)
    client.post('/api/mobile/sawmill/orders/{}/logs'.format(oid),
                json=dict(POMIAR, measured_at='2026-08-05T09:31:12'),
                headers=_naglowki(token, 'op-1'))
    r = client.post('/api/mobile/sawmill/orders/{}/complete'.format(oid),
                    headers=_naglowki(token, 'op-2'))
    assert r.status_code == 200
    with app.app_context():
        order = db.session.query(SawmillOrder).get(oid)
        assert order.status == STATUS_COMPLETED
        assert order.completed_by_device == 'TRAK-1'


def test_zakonczenie_bez_pomiarow_daje_409(client, app):
    token = _urzadzenie(app)
    oid = _zlecenie(app)
    r = client.post('/api/mobile/sawmill/orders/{}/complete'.format(oid),
                    headers=_naglowki(token, 'op-1'))
    assert r.status_code == 409


def test_nieistniejace_zlecenie_daje_404(client, app):
    token = _urzadzenie(app)
    r = client.post('/api/mobile/sawmill/orders/9999/logs',
                    json=dict(POMIAR, measured_at='2026-08-05T09:31:12'),
                    headers=_naglowki(token, 'op-1'))
    assert r.status_code == 404
    assert r.get_json()['error'] == 'order_not_found'


def test_measured_at_z_przyszlosci_jest_przycinany(client, app):
    """
    Przycięcie idzie do get_local_now(), NIE do datetime.now() (czasu
    kontenera, UTC) — walidacja przycina naiwny czas LOKALNY z tabletu do
    „teraz" w tej samej strefie, patrz komentarz w
    services/validation.py:parse_measured_at(). Test budował kiedyś
    oczekiwanie na datetime.now() i przechodził tylko dlatego, że przycięcie
    było wtedy (błędnie) liczone tak samo — czyli zakładał zepsute
    zachowanie, które właśnie naprawiamy.
    """
    token = _urzadzenie(app)
    oid = _zlecenie(app)
    przyszlosc = (get_local_now() + timedelta(hours=6)).isoformat(timespec='seconds')
    r = client.post('/api/mobile/sawmill/orders/{}/logs'.format(oid),
                    json=dict(POMIAR, measured_at=przyszlosc),
                    headers=_naglowki(token, 'op-1'))
    assert r.status_code == 201
    with app.app_context():
        assert SawmillLog.query.first().measured_at <= get_local_now() + timedelta(minutes=1)


# ── ETag — GET /orders ───────────────────────────────────────────────────────
#
# Brief nie zawierał testów ETagu, mimo że to jeden z czterech punktów, które
# "muszą być dokładnie tak". Sedno ryzyka: prod_sawmill_orders.updated_at NIE
# rusza się przy dodaniu/edycji pomiaru (brak kolumny cache'ującej sumę), więc
# naiwny wzorzec `MAX(order.updated_at) + COUNT` z mobile_api.py dawałby 304
# z nieaktualną sumą m3. Poniższe testy pilnują, żeby ETag realnie reagował
# na PATCH pomiaru (nie tylko na zmianę COUNT) i nie wywalał się dla pustej
# listy zleceń ani zlecenia bez żadnego pomiaru.

def test_etag_pusta_lista_zlecen_nie_wywala_sie(client, app):
    token = _urzadzenie(app)
    r = client.get('/api/mobile/sawmill/orders', headers=_naglowki(token))
    assert r.status_code == 200
    assert r.get_json()['orders'] == []
    assert r.headers.get('ETag')


def test_etag_zlecenie_bez_pomiarow_nie_wywala_sie(client, app):
    token = _urzadzenie(app)
    _zlecenie(app)
    r = client.get('/api/mobile/sawmill/orders', headers=_naglowki(token))
    assert r.status_code == 200
    assert len(r.get_json()['orders']) == 1
    assert r.headers.get('ETag')


def test_etag_powtorzone_zapytanie_bez_zmian_daje_304(client, app):
    token = _urzadzenie(app)
    _zlecenie(app)
    r1 = client.get('/api/mobile/sawmill/orders', headers=_naglowki(token))
    etag = r1.headers['ETag']

    headers = _naglowki(token)
    headers['If-None-Match'] = etag
    r2 = client.get('/api/mobile/sawmill/orders', headers=headers)
    assert r2.status_code == 304


def test_etag_zmienia_sie_po_dodaniu_pomiaru(client, app):
    token = _urzadzenie(app)
    oid = _zlecenie(app)
    r1 = client.get('/api/mobile/sawmill/orders', headers=_naglowki(token))
    etag_przed = r1.headers['ETag']

    client.post('/api/mobile/sawmill/orders/{}/logs'.format(oid),
                json=dict(POMIAR, measured_at='2026-08-05T09:31:12'),
                headers=_naglowki(token, 'op-1'))

    headers = _naglowki(token)
    headers['If-None-Match'] = etag_przed
    r2 = client.get('/api/mobile/sawmill/orders', headers=headers)
    assert r2.status_code == 200
    assert r2.headers['ETag'] != etag_przed
    assert r2.get_json()['orders'][0]['measured_volume_m3'] == 0.514699


def test_etag_zmienia_sie_po_edycji_pomiaru_bez_zmiany_liczby_klod(client, app):
    """
    Serce Punktu 4 z briefu: PATCH nie zmienia ani order.updated_at (bo wiersz
    zlecenia nie jest tknięty), ani COUNT (nadal jedna kłoda) — jedynie
    log.updated_at. Bez COALESCE(log.updated_at, log.created_at) w zapytaniu
    ETag zmieniłby się WYŁĄCZNIE przez COUNT, więc ten PATCH zostałby
    niezauważony i tablet dostałby 304 z sumą m3 sprzed edycji.
    """
    token = _urzadzenie(app)
    oid = _zlecenie(app)
    r = client.post('/api/mobile/sawmill/orders/{}/logs'.format(oid),
                    json=dict(POMIAR, measured_at='2026-08-05T09:31:12'),
                    headers=_naglowki(token, 'op-1'))
    log_id = r.get_json()['log']['id']

    r1 = client.get('/api/mobile/sawmill/orders', headers=_naglowki(token))
    etag_przed = r1.headers['ETag']
    liczba_klod_przed = r1.get_json()['orders'][0]['logs_count']

    client.patch('/api/mobile/sawmill/logs/{}'.format(log_id),
                 json=dict(POMIAR, length_cm=420.0),
                 headers=_naglowki(token, 'op-2'))

    headers = _naglowki(token)
    headers['If-None-Match'] = etag_przed
    r2 = client.get('/api/mobile/sawmill/orders', headers=headers)

    assert r2.status_code == 200, (
        "PATCH zmienił tylko log.updated_at (nie order.updated_at ani COUNT) — "
        "ETag musiał mimo to się zmienić, inaczej to 304 z nieaktualną sumą."
    )
    liczba_klod_po = r2.get_json()['orders'][0]['logs_count']
    assert liczba_klod_po == liczba_klod_przed
    assert r2.headers['ETag'] != etag_przed


def test_etag_zmienia_sie_po_usunieciu_pomiaru(client, app):
    token = _urzadzenie(app)
    oid = _zlecenie(app)
    r = client.post('/api/mobile/sawmill/orders/{}/logs'.format(oid),
                    json=dict(POMIAR, measured_at='2026-08-05T09:31:12'),
                    headers=_naglowki(token, 'op-1'))
    log_id = r.get_json()['log']['id']

    r1 = client.get('/api/mobile/sawmill/orders', headers=_naglowki(token))
    etag_przed = r1.headers['ETag']

    client.delete('/api/mobile/sawmill/logs/{}'.format(log_id),
                  headers=_naglowki(token, 'op-2'))

    headers = _naglowki(token)
    headers['If-None-Match'] = etag_przed
    r2 = client.get('/api/mobile/sawmill/orders', headers=headers)
    assert r2.status_code == 200
    assert r2.headers['ETag'] != etag_przed
    assert r2.get_json()['orders'][0]['measured_volume_m3'] == 0.0


# ── Odpowiedź nie zdradza danych finansowych/prywatnych na pozostałych
#    endpointach mobilnych (bezpieczeństwo — nie tylko GET /orders) ──────────

def test_szczegoly_zlecenia_nie_zawieraja_deklaracji(client, app):
    token = _urzadzenie(app)
    oid = _zlecenie(app)
    r = client.get('/api/mobile/sawmill/orders/{}'.format(oid), headers=_naglowki(token))
    assert r.status_code == 200
    surowo = r.get_data(as_text=True)
    for zakazane in ('declared_volume_m3', 'price_per_m3', 'declared_value',
                     'agreed_volume_m3', 'settlement_notes', 'WZ'):
        assert zakazane not in surowo


def test_odpowiedz_dodania_pomiaru_nie_zawiera_deklaracji(client, app):
    token = _urzadzenie(app)
    oid = _zlecenie(app)
    r = client.post('/api/mobile/sawmill/orders/{}/logs'.format(oid),
                    json=dict(POMIAR, measured_at='2026-08-05T09:31:12'),
                    headers=_naglowki(token, 'op-1'))
    surowo = r.get_data(as_text=True)
    for zakazane in ('declared_volume_m3', 'price_per_m3', 'declared_value',
                     'agreed_volume_m3', 'settlement_notes', 'WZ'):
        assert zakazane not in surowo


# ── X-Operation-Id jest wymagany (przegląd całej gałęzi) ────────────────────

def test_brak_operation_id_daje_400_na_kazdym_endpoincie_mutujacym(client, app):
    """
    Kontrakt deklaruje nagłówek jako wymagany, ale serwer tego nie egzekwował.
    Bez tego pominięcie nagłówka po stronie appki tworzyłoby duplikat kłody
    przy każdym retry po timeoucie — na samym pomiarze nie ma unikatu,
    sequence_no nadaje serwer. Rozbieżność ujawniłaby się dopiero jako
    zawyżona objętość w rozliczeniu z dostawcą.
    """
    token = _urzadzenie(app)
    oid = _zlecenie(app)
    bez = _naglowki(token)

    zadania = [
        lambda: client.post('/api/mobile/sawmill/orders/{}/logs'.format(oid),
                            json=POMIAR, headers=bez),
        lambda: client.patch('/api/mobile/sawmill/logs/1', json=POMIAR, headers=bez),
        lambda: client.delete('/api/mobile/sawmill/logs/1', headers=bez),
        lambda: client.post('/api/mobile/sawmill/orders/{}/complete'.format(oid),
                            headers=bez),
    ]
    for wykonaj in zadania:
        r = wykonaj()
        assert r.status_code == 400
        assert r.get_json()['error'] == 'missing_operation_id'


def test_pusty_operation_id_tez_daje_400(client, app):
    """Nagłówek z samymi spacjami to brak nagłówka, nie poprawna wartość."""
    token = _urzadzenie(app)
    oid = _zlecenie(app)
    naglowki = _naglowki(token)
    naglowki['X-Operation-Id'] = '   '
    r = client.post('/api/mobile/sawmill/orders/{}/logs'.format(oid),
                    json=POMIAR, headers=naglowki)
    assert r.status_code == 400
    assert r.get_json()['error'] == 'missing_operation_id'


def test_zadne_dane_nie_powstaja_przy_braku_naglowka(client, app):
    """Sprawdzenie musi nastąpić PRZED handlerem, nie po zapisie."""
    from modules.production.sawmill.models import SawmillLog
    token = _urzadzenie(app)
    oid = _zlecenie(app)
    # Body MUSI być kompletne (z measured_at) — z niepełnym handler i tak
    # zwróciłby 422 i nic by nie zapisał, więc test przechodziłby również
    # przy usuniętym sprawdzeniu nagłówka.
    client.post('/api/mobile/sawmill/orders/{}/logs'.format(oid),
                json=dict(POMIAR, measured_at='2026-08-05T09:31:12'),
                headers=_naglowki(token))
    with app.app_context():
        assert SawmillLog.query.count() == 0


def test_z_naglowkiem_dziala_jak_dotad(client, app):
    """Regresja — wymóg nie może zepsuć poprawnego żądania."""
    token = _urzadzenie(app)
    oid = _zlecenie(app)
    r = client.post('/api/mobile/sawmill/orders/{}/logs'.format(oid),
                    json=dict(POMIAR, measured_at='2026-08-05T09:31:12'),
                    headers=_naglowki(token, 'op-wymog-1'))
    assert r.status_code == 201


# ── Atrybucja pracy do pracownika ───────────────────────────────────────────

def test_pomiar_zapisuje_kto_zmierzyl(client, app):
    """
    Na trakowni stoją dwa tablety i dwie osoby mierzą to samo zlecenie —
    samo device_id nie odpowiada na pytanie, kto zmierzył tę kłodę.
    """
    token = _urzadzenie(app)
    order_id = _zlecenie(app)
    worker_id = _pracownik(app)

    odp = client.post(f'/api/mobile/sawmill/orders/{order_id}/logs',
                      headers=_naglowki(token, operation_id='op-1',
                                        worker_ids=str(worker_id)),
                      json=dict(POMIAR, measured_at='2026-08-11T10:00:00'))

    assert odp.status_code == 201
    with app.app_context():
        klodа = SawmillLog.query.one()
        assert klodа.worker_id == worker_id
        # device_id zostaje — to dwie różne informacje, nie zamiennik
        assert klodа.device_id


def test_pomiar_bez_profilu_przechodzi_bez_atrybucji(client, app):
    """
    Kill-switch wyłączony: brak nagłówka nie może zablokować pomiaru.
    Trakownia ma działać tak samo jak przed wdrożeniem profili.
    """
    token = _urzadzenie(app)
    order_id = _zlecenie(app)

    odp = client.post(f'/api/mobile/sawmill/orders/{order_id}/logs',
                      headers=_naglowki(token, operation_id='op-2'),
                      json=dict(POMIAR, measured_at='2026-08-11T10:00:00'))

    assert odp.status_code == 201
    with app.app_context():
        assert SawmillLog.query.one().worker_id is None


def test_nieznany_pracownik_odrzucony(client, app):
    token = _urzadzenie(app)
    order_id = _zlecenie(app)

    odp = client.post(f'/api/mobile/sawmill/orders/{order_id}/logs',
                      headers=_naglowki(token, operation_id='op-3',
                                        worker_ids='999'),
                      json=dict(POMIAR, measured_at='2026-08-11T10:00:00'))

    assert odp.status_code == 404
    assert odp.get_json()['error'] == 'worker_not_found'
    with app.app_context():
        assert SawmillLog.query.count() == 0


def test_zamkniecie_zlecenia_zapisuje_kto_w_audycie(client, app):
    """
    Zamknięcie to DECYZJA (zmierzona objętość idzie do rozliczenia z dostawcą),
    więc jej autor trafia do śladu audytowego, a nie na samo zlecenie.
    """
    token = _urzadzenie(app)
    order_id = _zlecenie(app)
    worker_id = _pracownik(app)
    naglowki = _naglowki(token, operation_id='op-4', worker_ids=str(worker_id))

    client.post(f'/api/mobile/sawmill/orders/{order_id}/logs', headers=naglowki,
                json=dict(POMIAR, measured_at='2026-08-11T10:00:00'))
    odp = client.post(f'/api/mobile/sawmill/orders/{order_id}/complete',
                      headers=_naglowki(token, operation_id='op-5',
                                        worker_ids=str(worker_id)))

    assert odp.status_code == 200
    with app.app_context():
        zamkniecie = SawmillAudit.query.filter_by(action='order_complete').one()
        assert zamkniecie.worker_id == worker_id


def test_korekta_i_usuniecie_pomiaru_trafiaja_do_audytu_z_autorem(client, app):
    token = _urzadzenie(app)
    order_id = _zlecenie(app)
    worker_id = _pracownik(app)

    client.post(f'/api/mobile/sawmill/orders/{order_id}/logs',
                headers=_naglowki(token, operation_id='op-6',
                                  worker_ids=str(worker_id)),
                json=dict(POMIAR, measured_at='2026-08-11T10:00:00'))
    with app.app_context():
        log_id = SawmillLog.query.one().id

    client.patch(f'/api/mobile/sawmill/logs/{log_id}',
                 headers=_naglowki(token, operation_id='op-7',
                                   worker_ids=str(worker_id)),
                 json=dict(POMIAR, mid_circumference_cm=130.0,
                           measured_at='2026-08-11T10:05:00'))
    client.delete(f'/api/mobile/sawmill/logs/{log_id}',
                  headers=_naglowki(token, operation_id='op-8',
                                    worker_ids=str(worker_id)))

    with app.app_context():
        for akcja in ('log_update', 'log_delete'):
            wpis = SawmillAudit.query.filter_by(action=akcja).one()
            assert wpis.worker_id == worker_id, akcja
