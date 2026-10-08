# -*- coding: utf-8 -*-
"""
GET /api/mobile/stations/<S>/summary?worker_id=<id> — „Wykonałeś dziś" w nagłówku tabletu.

completed_today_worker liczy się jak completed_today (prod_station_events z dziś, bez źródeł automatu, netto
z cofnięciami), ale każdy event wchodzi z udziałem pracownika: delta × share z prod_station_event_workers
(wiersze dopinane przy complete / complete-partial z nagłówka X-Worker-Ids) — ta sama reguła co panel
„Wydajność pracowników". Bez parametru odpowiedź i ETag mają zostać takie jak przed zmianą.

Eventy zakładamy przez ProductionProduct.set_quantity_done(..., actor_worker_ids=...) — tę samą ścieżkę, którą
idą ZAKOŃCZ i zakończenie częściowe (mark_order_complete / mobile_api_service).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from decimal import Decimal

import pytest
from flask import Flask
from sqlalchemy.pool import StaticPool

from extensions import db
from modules.production.models import (
    ProcessedMobileOperation, ProductionConfig, ProductionConfiguration,
    ProductionDevice, ProductionOrder, ProductionProduct,
    ProductionStationEvent, ProductionStationEventWorker,
    ProductionWorker, ProductionWorkerSession,
)
from modules.production.routers.mobile_api import mobile_api_bp
from modules.production.services.mobile_api_service import generate_token
from modules.users.models import User
# Importy rejestrujące mappery — jak w tests/test_mobile_api_alias_krawedzi.py.
from modules.calculator.models import Multiplier  # noqa: F401
from modules.clients.models import Client  # noqa: F401
import modules.quotes.models  # noqa: F401

_TABLES = [m.__table__ for m in (
    User, ProductionDevice, ProductionConfig, ProcessedMobileOperation,
    ProductionOrder, ProductionProduct, ProductionConfiguration,
    ProductionWorker, ProductionWorkerSession,
    ProductionStationEvent, ProductionStationEventWorker,
)]

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
        'jwt_expiry_days': 365,
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
    from modules.production.services.config_service import invalidate_config_cache
    invalidate_config_cache()
    yield
    invalidate_config_cache()


def _token(app, station_code='edges'):
    with app.app_context():
        device = ProductionDevice(device_id='TABLET-1', device_name='Tablet',
                                  station_code=station_code)
        db.session.add(device)
        db.session.commit()
        return generate_token(device)


def _naglowki(token, **dodatkowe):
    naglowki = {'Authorization': 'Bearer ' + token, 'X-App-Version': '1.0.0'}
    naglowki.update(dodatkowe)
    return naglowki


def _pracownik(app, imie):
    with app.app_context():
        pracownik = ProductionWorker(first_name=imie, last_name='Test',
                                     is_active=True, sort_order=0)
        db.session.add(pracownik)
        db.session.commit()
        return pracownik.id


_licznik_zamowien = [0]


def _produkt(app, quantity=5, volume_m3='0.100000', status='czeka_na_krawedzie'):
    with app.app_context():
        _licznik_zamowien[0] += 1
        nr = _licznik_zamowien[0]
        order = ProductionOrder(
            baselinker_order_id=880000 + nr,
            internal_order_number='26/{:05d}'.format(nr),
            delivery_method='Kurier DPD',
            delivery_address='ul. Testowa 1',
            delivery_city='Warszawa',
            delivery_postcode='00-001',
        )
        db.session.add(order)
        db.session.flush()
        produkt = ProductionProduct(
            order_id=order.id, short_product_id='{}_1'.format(nr),
            product_sequence_in_order=1, original_product_name='Blat dębowy',
            quantity=quantity, current_status=status,
            parsed_finish_type='surowe', parsed_edge_processing=True,
            volume_m3=Decimal(volume_m3),
        )
        db.session.add(produkt)
        db.session.commit()
        return produkt.id


def _odbij(app, produkt_id, stanowisko, ile, pracownicy):
    """Zakończenie (pełne albo częściowe) z atrybucją — jak ZAKOŃCZ z nagłówkiem X-Worker-Ids."""
    with app.app_context():
        produkt = ProductionProduct.query.get(produkt_id)
        produkt.increment_quantity_done(stanowisko, ile, source='mobile',
                                        actor_device_id='TABLET-1',
                                        actor_worker_ids=pracownicy)
        db.session.commit()


def _summary(client, token, stanowisko='edges', query=''):
    odp = client.get('/api/mobile/stations/{}/summary{}'.format(stanowisko, query),
                     headers=_naglowki(token))
    assert odp.status_code == 200, odp.get_json()
    return odp


# ============================================================================
# completed_today_worker
# ============================================================================

def test_pracownik_z_zakonczeniami_dostaje_swoje_metryki(client, app):
    token = _token(app)
    ewa = _pracownik(app, 'Ewa')
    p1 = _produkt(app, quantity=3, volume_m3='0.100000')
    p2 = _produkt(app, quantity=4, volume_m3='0.250000')
    _odbij(app, p1, 'edges', 3, [ewa])           # pełne zakończenie
    _odbij(app, p2, 'edges', 2, [ewa])           # zakończenie częściowe 2/4

    dane = _summary(client, token, query='?worker_id={}'.format(ewa)).get_json()

    assert dane['completed_today_worker']['count'] == 2
    assert dane['completed_today_worker']['total_volume_m3'] == pytest.approx(0.3 + 0.5)
    # Ta sama metoda co całe stanowisko: tu cała praca stanowiska to praca Ewy.
    assert dane['completed_today_worker'] == dane['completed_today']


def test_zakonczenie_innego_pracownika_sie_nie_wlicza(client, app):
    token = _token(app)
    ewa = _pracownik(app, 'Ewa')
    jan = _pracownik(app, 'Jan')
    p1 = _produkt(app, quantity=2, volume_m3='0.100000')
    p2 = _produkt(app, quantity=2, volume_m3='0.300000')
    _odbij(app, p1, 'edges', 2, [ewa])
    _odbij(app, p2, 'edges', 2, [jan])

    dane = _summary(client, token, query='?worker_id={}'.format(ewa)).get_json()

    assert dane['completed_today_worker'] == {'count': 1, 'total_volume_m3': pytest.approx(0.2)}
    # completed_today nadal liczy całe stanowisko.
    assert dane['completed_today']['count'] == 2


def test_zamowienie_10_sztuk_robione_przez_trzy_osoby_3_3_4(client, app):
    """Każdy kończy częściowo pod własnym profilem — każdy widzi swoje sztuki."""
    token = _token(app)
    ewa = _pracownik(app, 'Ewa')
    jan = _pracownik(app, 'Jan')
    ola = _pracownik(app, 'Ola')
    p1 = _produkt(app, quantity=10, volume_m3='0.100000')
    _odbij(app, p1, 'edges', 3, [ewa])
    _odbij(app, p1, 'edges', 3, [jan])
    _odbij(app, p1, 'edges', 4, [ola])

    wyniki = {}
    for kto in (ewa, jan, ola):
        dane = _summary(client, token, query='?worker_id={}'.format(kto)).get_json()
        wyniki[kto] = dane['completed_today_worker']
        assert wyniki[kto]['count'] == 1

    assert wyniki[ewa]['total_volume_m3'] == pytest.approx(0.3)
    assert wyniki[jan]['total_volume_m3'] == pytest.approx(0.3)
    assert wyniki[ola]['total_volume_m3'] == pytest.approx(0.4)
    # Suma wkładów = całe stanowisko.
    assert sum(w['total_volume_m3'] for w in wyniki.values()) == pytest.approx(
        dane['completed_today']['total_volume_m3'])


def test_zakonczenie_zespolowe_dzieli_sie_po_rowno(client, app):
    """Jedno ZAKOŃCZ z trzema profilami: nic więcej o podziale nie wiadomo → share = 1/3."""
    token = _token(app)
    ewa = _pracownik(app, 'Ewa')
    jan = _pracownik(app, 'Jan')
    ola = _pracownik(app, 'Ola')
    p1 = _produkt(app, quantity=3, volume_m3='0.300000')
    _odbij(app, p1, 'edges', 3, [ewa, jan, ola])

    for kto in (ewa, jan, ola):
        dane = _summary(client, token, query='?worker_id={}'.format(kto)).get_json()
        assert dane['completed_today_worker']['count'] == 1
        assert dane['completed_today_worker']['total_volume_m3'] == pytest.approx(0.3, abs=1e-5)


def test_zespol_i_osobne_zakonczenie_skladaja_sie(client, app):
    """Ewa: 2 sztuki sama + połowa z 4 sztuk zrobionych z Janem = 4 sztuki."""
    token = _token(app)
    ewa = _pracownik(app, 'Ewa')
    jan = _pracownik(app, 'Jan')
    p1 = _produkt(app, quantity=6, volume_m3='0.100000')
    _odbij(app, p1, 'edges', 2, [ewa])
    _odbij(app, p1, 'edges', 4, [ewa, jan])

    ewy = _summary(client, token, query='?worker_id={}'.format(ewa)).get_json()['completed_today_worker']
    jana = _summary(client, token, query='?worker_id={}'.format(jan)).get_json()['completed_today_worker']

    assert ewy == {'count': 1, 'total_volume_m3': pytest.approx(0.4)}
    assert jana == {'count': 1, 'total_volume_m3': pytest.approx(0.2)}


def test_zakonczenie_na_innym_stanowisku_sie_nie_wlicza(client, app):
    token = _token(app)
    ewa = _pracownik(app, 'Ewa')
    p1 = _produkt(app, quantity=2, volume_m3='0.100000')
    p2 = _produkt(app, quantity=2, volume_m3='0.100000', status='czeka_na_lakiernie')
    _odbij(app, p1, 'edges', 2, [ewa])
    _odbij(app, p2, 'painting', 2, [ewa])

    dane = _summary(client, token, query='?worker_id={}'.format(ewa)).get_json()

    assert dane['completed_today_worker'] == {'count': 1, 'total_volume_m3': pytest.approx(0.2)}


def test_zakonczenie_bez_atrybucji_sie_nie_wlicza(client, app):
    token = _token(app)
    ewa = _pracownik(app, 'Ewa')
    p1 = _produkt(app, quantity=2)
    _odbij(app, p1, 'edges', 2, None)   # bramka wyłączona, tablet bez nagłówka

    dane = _summary(client, token, query='?worker_id={}'.format(ewa)).get_json()

    assert dane['completed_today']['count'] == 1
    assert dane['completed_today_worker'] == {'count': 0, 'total_volume_m3': 0.0}


def test_pracownik_bez_zakonczen_dostaje_zera(client, app):
    token = _token(app)
    ewa = _pracownik(app, 'Ewa')
    jan = _pracownik(app, 'Jan')
    _odbij(app, _produkt(app, quantity=2), 'edges', 2, [jan])

    dane = _summary(client, token, query='?worker_id={}'.format(ewa)).get_json()

    assert 'completed_today_worker' in dane
    assert dane['completed_today_worker'] == {'count': 0, 'total_volume_m3': 0.0}
    assert isinstance(dane['completed_today_worker']['total_volume_m3'], float)


def test_cofniecie_odejmuje_jak_w_completed_today(client, app):
    token = _token(app)
    ewa = _pracownik(app, 'Ewa')
    p1 = _produkt(app, quantity=4, volume_m3='0.100000')
    _odbij(app, p1, 'edges', 3, [ewa])
    _odbij(app, p1, 'edges', -1, [ewa])

    dane = _summary(client, token, query='?worker_id={}'.format(ewa)).get_json()

    assert dane['completed_today_worker'] == {'count': 1, 'total_volume_m3': pytest.approx(0.2)}
    assert dane['completed_today_worker'] == dane['completed_today']


# ============================================================================
# Bez parametru / niepoprawny parametr — odpowiedź jak dziś
# ============================================================================

@pytest.mark.parametrize('query', ['', '?worker_id=', '?worker_id=abc', '?worker_id=0',
                                   '?worker_id=-3', '?worker_id=1.5'])
def test_bez_parametru_albo_z_niepoprawnym_pola_nie_ma(client, app, query):
    token = _token(app)
    ewa = _pracownik(app, 'Ewa')
    _odbij(app, _produkt(app, quantity=2), 'edges', 2, [ewa])

    odp = _summary(client, token, query=query)
    dane = odp.get_json()

    assert 'completed_today_worker' not in dane
    assert set(dane) == {'station_code', 'queue', 'completed_today',
                         'refresh_interval_seconds', 'server_time'}
    assert dane['completed_today']['count'] == 1
    # ETag bez parametru ma zostać taki jak przed zmianą (bez segmentu pracownika).
    assert ':w' not in odp.headers['ETag']


# ============================================================================
# ETag
# ============================================================================

def test_etag_rozroznia_pracownikow(client, app):
    token = _token(app)
    ewa = _pracownik(app, 'Ewa')
    jan = _pracownik(app, 'Jan')
    _odbij(app, _produkt(app, quantity=2), 'edges', 2, [ewa])

    bez = _summary(client, token).headers['ETag']
    etag_ewy = _summary(client, token, query='?worker_id={}'.format(ewa)).headers['ETag']
    etag_jana = _summary(client, token, query='?worker_id={}'.format(jan)).headers['ETag']

    assert len({bez, etag_ewy, etag_jana}) == 3

    # ETag Ewy przysłany w zapytaniu Jana nie może dać 304 z cudzą odpowiedzią.
    odp = client.get('/api/mobile/stations/edges/summary?worker_id={}'.format(jan),
                     headers=_naglowki(token, **{'If-None-Match': etag_ewy}))
    assert odp.status_code == 200
    assert odp.get_json()['completed_today_worker']['count'] == 0

    # Ten sam pracownik ze swoim ETagiem dostaje 304.
    odp = client.get('/api/mobile/stations/edges/summary?worker_id={}'.format(ewa),
                     headers=_naglowki(token, **{'If-None-Match': etag_ewy}))
    assert odp.status_code == 304
