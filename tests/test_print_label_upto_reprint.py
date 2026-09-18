# -*- coding: utf-8 -*-
"""
Druk wybranych sztuk pozycji — kontrakt panelu kafelków aplikacji stanowiskowej.

Endpoint adresuje pozycję po `id`, NIE po short_product_id: ten drugi dzielą
oryginał i doróbka, więc żądanie trafiałoby w losowy z dwóch wierszy. Przy
`upTo`, które USTAWIA licznik, operator widziałby brak reakcji i naciskał dalej.

Numery w żądaniu są GLOBALNE — takie, jakie wychodzą na papier i jakie operator
widzi na kafelku. `offsetSeen` to offset, na którym aplikacja je policzyła:
rozbieżność znaczy, że skład zamówienia zmienił się między odczytem kolejki
a naciśnięciem przycisku, i kończy się 409 zamiast cichym wydrukiem nie tych
sztuk.

Sam wydruk jest tu podmieniony atrapą — te testy pilnują reguł kontraktu
(zakresy, licznik, 409), a nie tego, czy drukarka odpowiada.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from flask import Flask
from sqlalchemy.pool import StaticPool

from extensions import db
from modules.production.models import (
    ProcessedMobileOperation, ProductionConfig, ProductionConfiguration,
    ProductionDevice, ProductionOrder, ProductionProduct,
    ProductionReworkLog, ProductionStationEvent, ProductionStationEventWorker,
    ProductionWorker, ProductionWorkerSession,
)
from modules.production.routers import mobile_api as router
from modules.production.routers.mobile_api import mobile_api_bp
from modules.production.services.mobile_api_service import generate_token
from modules.users.models import User
from modules.calculator.models import Multiplier  # noqa: F401
from modules.clients.models import Client  # noqa: F401
import modules.quotes.models  # noqa: F401

# LONGTEXT jest typem MySQL-a i nie buduje się na SQLite — ta sama podmiana
# co w tests/test_mobile_api_alias_krawedzi.py.
ProductionOrder.__table__.c.shipping_label_base64.type = db.Text()

_TABLES = [m.__table__ for m in (
    User, ProductionDevice, ProductionConfig, ProcessedMobileOperation,
    ProductionOrder, ProductionProduct, ProductionConfiguration,
    ProductionReworkLog, ProductionWorker, ProductionWorkerSession,
    ProductionStationEvent, ProductionStationEventWorker,
)]


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
def atrapa_druku(monkeypatch):
    """Podstawia druk; zapamiętuje, o które sztuki poproszono."""
    wywolania = []

    def _drukuj(ids, station_code, actor, units_by_item=None,
                aktualizuj_licznik=True):
        wywolania.append({
            'ids': list(ids), 'units': units_by_item,
            'aktualizuj_licznik': aktualizuj_licznik,
        })
        return {
            'success': True, 'success_count': 1, 'failed_count': 0,
            'connection_error': False, 'message': 'OK', 'results': [],
        }

    monkeypatch.setattr(router.label_print_service, 'print_labels_batch', _drukuj)
    return wywolania


def _pozycja(app, ilosc=8, licznik=0, poprzednik_sztuk=0):
    """
    Zamówienie z opcjonalną pozycją poprzedzającą, żeby offset był niezerowy —
    inaczej numer globalny zrównałby się z lokalnym i testy przechodziłyby
    także przy pomylonym przeliczeniu.
    """
    with app.app_context():
        order = ProductionOrder(baselinker_order_id=555000,
                                internal_order_number='555',
                                client_name='Jan Kowalski')
        db.session.add(order)
        db.session.flush()
        cfg = ProductionConfiguration.find_or_create('dąb', 'lity', 'A/B')
        db.session.flush()

        if poprzednik_sztuk:
            db.session.add(ProductionProduct(
                order_id=order.id, configuration_id=cfg.id,
                short_product_id='555_1', product_sequence_in_order=1,
                original_product_name='Blat', current_status='czeka_na_pakowanie',
                quantity=poprzednik_sztuk,
            ))
            db.session.flush()

        poz = ProductionProduct(
            order_id=order.id, configuration_id=cfg.id,
            short_product_id='555_2', product_sequence_in_order=2,
            original_product_name='Blat', current_status='czeka_na_pakowanie',
            quantity=ilosc, label_print_count=licznik,
        )
        db.session.add(poz)
        db.session.commit()
        return poz.id


def _token(app, station_code='packaging'):
    with app.app_context():
        d = ProductionDevice(device_id='TABLET-1', device_name='Tablet',
                             station_code=station_code)
        db.session.add(d)
        db.session.commit()
        return generate_token(d)


def _naglowki(token):
    return {'Authorization': 'Bearer ' + token, 'X-App-Version': '1.6.1'}


def _post(client, token, pid, cialo):
    return client.post(f'/api/mobile/products/by-id/{pid}/print-label',
                       json=cialo, headers=_naglowki(token))


def test_upto_drukuje_od_pierwszej_nieoznaczonej_do_wskazanej(app, client, atrapa_druku):
    # Poprzednik ma 3 szt., więc offset = 3: sztuka lokalna 1 to globalna 4.
    pid = _pozycja(app, ilosc=8, licznik=2, poprzednik_sztuk=3)
    token = _token(app)

    odp = _post(client, token, pid, {'upTo': 8, 'offsetSeen': 3})

    assert odp.status_code == 200
    # Globalne 8 to lokalne 5; wydrukowane były 2, więc idą sztuki 3, 4 i 5.
    assert atrapa_druku[0]['units'] == {pid: [3, 4, 5]}
    # Licznik USTAWIAMY na wartość lokalną, nie dodajemy.
    with app.app_context():
        assert db.session.get(ProductionProduct, pid).label_print_count == 5


def test_reprint_drukuje_jedna_sztuke_i_nie_rusza_licznika(app, client, atrapa_druku):
    pid = _pozycja(app, ilosc=8, licznik=5, poprzednik_sztuk=3)
    token = _token(app)

    odp = _post(client, token, pid, {'reprint': 6, 'offsetSeen': 3})

    assert odp.status_code == 200
    assert atrapa_druku[0]['units'] == {pid: [3]}  # globalna 6 → lokalna 3
    with app.app_context():
        assert db.session.get(ProductionProduct, pid).label_print_count == 5


def test_rozbiezny_offset_konczy_sie_409_z_aktualnymi_wartosciami(app, client, atrapa_druku):
    """
    Skład zamówienia zmienił się między odczytem kolejki a naciśnięciem.
    Bez tego sprawdzenia druk poszedłby po cichu na inne sztuki, niż widział
    operator — a 409 z aktualnymi wartościami pozwala panelowi przerysować się
    bez dodatkowej rundy po kolejkę.
    """
    pid = _pozycja(app, ilosc=8, licznik=0, poprzednik_sztuk=3)
    token = _token(app)

    odp = _post(client, token, pid, {'upTo': 8, 'offsetSeen': 2})

    assert odp.status_code == 409
    assert odp.get_json()['label_offset'] == 3
    assert odp.get_json()['label_total'] == 11
    assert atrapa_druku == []  # nic nie poszło do druku


def test_numer_spoza_zakresu_pozycji_jest_odrzucany(app, client, atrapa_druku):
    pid = _pozycja(app, ilosc=8, licznik=0, poprzednik_sztuk=3)
    token = _token(app)

    # Globalna 12 to lokalna 9, a pozycja ma 8 sztuk.
    odp = _post(client, token, pid, {'upTo': 12, 'offsetSeen': 3})

    assert odp.status_code == 400
    assert atrapa_druku == []


def test_upto_ponizej_licznika_jest_bezpiecznym_no_opem(app, client, atrapa_druku):
    """
    Powtórzone `upTo` przy niezmienionym liczniku nie ma czego wydrukować.
    Ma oddać sukces z zerem kopii, nie błąd i nie udawany wydruk — panel
    pokaże „nic do wydrukowania". Do przedruku służy `reprint`.
    """
    pid = _pozycja(app, ilosc=8, licznik=5, poprzednik_sztuk=3)
    token = _token(app)

    odp = _post(client, token, pid, {'upTo': 7, 'offsetSeen': 3})

    assert odp.status_code == 200
    assert odp.get_json()['copies_printed'] == 0
    assert atrapa_druku == []


def test_upto_i_reprint_naraz_sa_odrzucane(app, client, atrapa_druku):
    pid = _pozycja(app, ilosc=8, poprzednik_sztuk=3)
    token = _token(app)

    odp = _post(client, token, pid, {'upTo': 8, 'reprint': 5, 'offsetSeen': 3})

    assert odp.status_code == 400
    assert atrapa_druku == []


def test_bez_parametrow_zachowuje_sie_jak_stary_druk(app, client, atrapa_druku):
    """Brak upTo i reprint = całą pozycję, licznikiem zarządza serwis."""
    pid = _pozycja(app, ilosc=8, poprzednik_sztuk=3)
    token = _token(app)

    odp = _post(client, token, pid, {})

    assert odp.status_code == 200
    assert atrapa_druku[0]['units'] is None
    assert atrapa_druku[0]['aktualizuj_licznik'] is True


def test_nieznana_pozycja_konczy_sie_404(app, client, atrapa_druku):
    token = _token(app)
    odp = _post(client, token, 999999, {'upTo': 1, 'offsetSeen': 0})
    assert odp.status_code == 404
