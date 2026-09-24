# -*- coding: utf-8 -*-
"""
Test regresyjny dla Etapu 0 profili pracownikow (docs/worker-profiles-backend.md, 3.3).

Po usunieciu webowych paneli wykonawczych stanowisk jedyna sciezka zamykania
stanowiska to POST /api/mobile/orders/<id>/complete. Ten test pilnuje, ze ta
sciezka nadal rejestruje wpis w kolejce synchronizacji statusow Baselinkera
(mobile_api_service.mark_order_complete() -> schedule_after_station_complete()) -
bez tego zamowienia przestalyby dostawac status "Produkcja zakonczona" /
"Zamowienie spakowane" w BL.
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
    ProductionDevice, ProductionOrder, ProductionProduct, ProductionReworkLog,
    ProductionStationEvent,
)
from modules.production.routers.mobile_api import mobile_api_bp
from modules.production.services.mobile_api_service import generate_token
from modules.users.models import User
# Import wymagany, zeby topologiczne sortowanie FK w create_all znalazlo
# tabele 'users' w metadata (ProductionConfig.updated_by, ProductionReworkLog.user_id
# itp. maja ForeignKey('users.id')) - ten sam powod co w test_sawmill_mobile_api.py.
from modules.calculator.models import Multiplier  # noqa: F401
from modules.clients.models import Client  # noqa: F401
import modules.quotes.models  # noqa: F401
from modules.quotes.models import QuoteStatus  # noqa: F401

_TABLES = [m.__table__ for m in (
    User, ProductionDevice, ProductionConfig, ProcessedMobileOperation,
    ProductionOrder, ProductionProduct, ProductionConfiguration, ProductionReworkLog,
    # prod_station_events doszło, bo mark_order_complete() domyka teraz sztuki
    # przez set_quantity_done() i zostawia event stanowiskowy — patrz naprawa
    # pułapki nr 1 w docs/worker-profiles-backend.md §8.
    ProductionStationEvent,
)]

# SQLite (tylko testy) nie zna typu MySQL LONGTEXT (ProductionOrder.shipping_label_base64) -
# ten sam problem i to samo obejście co ProcessedMobileOperation.response_body w models.py
# (LONGTEXT().with_variant(Text(), 'sqlite')), tylko zrobione tu zamiast w modelu produkcyjnym.
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


def _urzadzenie(app, station_code='packaging'):
    with app.app_context():
        device = ProductionDevice(
            device_id='TABLET-1', device_name='Tablet pakowania', station_code=station_code)
        db.session.add(device)
        db.session.commit()
        return generate_token(device)


def _zlecenie_gotowe_do_pakowania(app):
    """Zamowienie z jednym produktem czekajacym na pakowanie."""
    with app.app_context():
        order = ProductionOrder(
            baselinker_order_id=990001,
            internal_order_number='26/00042',
        )
        db.session.add(order)
        db.session.flush()

        product = ProductionProduct(
            order_id=order.id,
            short_product_id='26042_1',
            product_sequence_in_order=1,
            original_product_name='Deska tarasowa 200x15x2.5',
            quantity=1,
            current_status='czeka_na_pakowanie',
        )
        db.session.add(product)
        db.session.commit()
        return product.id, order.internal_order_number


def test_zamkniecie_stanowiska_przez_mobile_api_zostawia_wpis_w_kolejce_sync_bl(
    client, app, monkeypatch
):
    """
    POST /api/mobile/orders/<id>/complete (stanowisko 'packaging') musi wywolac
    schedule_after_station_complete(internal_order_number, 'packaging') -
    to jest jedyny mechanizm pilnujacy integracji z BL po usunieciu paneli webowych.
    """
    token = _urzadzenie(app, station_code='packaging')
    product_id, internal_order_number = _zlecenie_gotowe_do_pakowania(app)

    zaplanowane_synchronizacje = []

    def fake_schedule(order_number, station_code):
        zaplanowane_synchronizacje.append((order_number, station_code))

    monkeypatch.setattr(
        'modules.production.services.baselinker_status_sync.schedule_after_station_complete',
        fake_schedule,
    )

    response = client.post(
        '/api/mobile/orders/{}/complete'.format(product_id),
        headers={'Authorization': 'Bearer ' + token, 'X-App-Version': '1.0.0'},
        json={},
    )

    assert response.status_code == 200
    assert zaplanowane_synchronizacje == [(internal_order_number, 'packaging')]

    with app.app_context():
        refreshed = ProductionProduct.query.get(product_id)
        assert refreshed.current_status == 'spakowane'


class _LoggerSzpieg:
    """Podmiana za structured logger modulu sync BL - zlicza, co zostalo zalogowane."""

    def __init__(self):
        self.ostrzezenia = []
        self.bledy = []
        self.informacje = []

    def debug(self, message, **kwargs):
        pass

    def info(self, message, **kwargs):
        self.informacje.append((message, kwargs))

    def warning(self, message, **kwargs):
        self.ostrzezenia.append((message, kwargs))

    def error(self, message, **kwargs):
        self.bledy.append((message, kwargs))


def _zlecenie_gotowe_na_krawedziach(app):
    """Zamowienie z jednym produktem surowym Z obrobka krawedzi, stojacym na Krawedziach.

    Adres dostawy jest ustawiony CELOWO: ProductionOrder.is_personal_pickup
    (models.py:172-183) zwraca True, gdy zamowienie nie ma ani adresu, ani
    miasta, ani kodu pocztowego. Bez adresu complete_task() zamienilby
    logistyke na pakowanie i test badalby inna sciezke niz opisana w tytule.
    """
    with app.app_context():
        order = ProductionOrder(
            baselinker_order_id=990002,
            internal_order_number='26/00043',
            delivery_method='Kurier DPD',
            delivery_address='ul. Debowa 1',
            delivery_city='Poznan',
            delivery_postcode='61-001',
        )
        db.session.add(order)
        db.session.flush()

        product = ProductionProduct(
            order_id=order.id,
            short_product_id='26043_1',
            product_sequence_in_order=1,
            original_product_name='Blat debowy 200x60x4 z fazowaniem',
            quantity=2,
            parsed_finish_type='surowe',
            parsed_edge_processing=True,
            current_status='czeka_na_krawedzie',
        )
        db.session.add(product)
        db.session.commit()
        return product.id, order.baselinker_order_id


def test_complete_na_krawedziach_zamyka_produkcje_w_baselinkerze(client, app, monkeypatch):
    """
    Produkt surowy Z obrobka krawedzi konczy produkcje na Krawedziach i stamtad
    idzie do logistyki.

    Test opisuje CICHA awarie: jesli 'edges' nie ma w PRODUCTION_STATIONS, guard
    w schedule_after_station_complete (baselinker_status_sync.py:175) robi zwykly
    return. Trzy asercje ponizej opisuja ten sam brak z trzech stron: zero wywolan
    API, HTTP 200 (zero wyjatkow - tablet widzi sukces) i pusty logger (zero
    ostrzezen, zero bledow). Zamowienie po prostu nigdy nie dostaje statusu
    "Produkcja zakonczona" (138620) i nikt sie o tym nie dowiaduje.

    Test idzie CALA sciezka: tablet -> complete -> kolejka -> flush ->
    setOrderStatus, zeby zlapac regresje takze w mobile_api_service
    (flush_pending_syncs wywoluje sie z dekoratora with_idempotency dopiero
    po commicie, mobile_api_service.py:580-581).
    """
    token = _urzadzenie(app, station_code='edges')
    product_id, baselinker_order_id = _zlecenie_gotowe_na_krawedziach(app)

    wywolania = []
    szpieg = _LoggerSzpieg()

    def fake_set_status(bl_order_id, target_status_id):
        wywolania.append((bl_order_id, target_status_id))
        return True

    monkeypatch.setattr(
        'modules.production.services.baselinker_status_sync._call_set_order_status',
        fake_set_status,
    )
    monkeypatch.setattr(
        'modules.production.services.baselinker_status_sync.logger', szpieg)

    response = client.post(
        '/api/mobile/orders/{}/complete'.format(product_id),
        headers={'Authorization': 'Bearer ' + token, 'X-App-Version': '1.0.0'},
        json={},
    )

    # Brak wyjatku: przy cichej awarii tablet TEZ dostaje 200 - to nie jest dowod
    # poprawnosci, tylko opis objawu.
    assert response.status_code == 200
    # Brak logu: guard nie loguje niczego, wiec ani ostrzezenie, ani blad nie
    # zdradzilyby awarii w produkcyjnym logu.
    assert szpieg.ostrzezenia == []
    assert szpieg.bledy == []
    # Brak wywolania API: jedyna obserwowalna roznica miedzy dzialaniem a awaria.
    # 138620 wpisane wprost, a nie przez stala - to jest kontrakt z BL, nie detal kodu.
    assert wywolania == [(baselinker_order_id, 138620)]

    with app.app_context():
        refreshed = ProductionProduct.query.get(product_id)
        assert refreshed.current_status == 'czeka_na_pakowanie'
        assert refreshed.quantity_done_edges == 2
        assert refreshed.edges_completed_at is not None


def test_kod_spoza_zbioru_wychodzi_bez_sladu(app, monkeypatch):
    """
    Utrwalenie mechanizmu, ktory robi z brakujacego kodu CICHA awarie.

    Guard dla stanowiska ze srodka linii wychodzi bez wyjatku, bez wpisu
    w kolejce i bez jednej linijki logu. Ten test ma byc zielony zawsze - jest
    po to, zeby nikt nie uznal milczenia guardu za dowod, ze wszystko dziala:
    kazdy brakujacy kod w PRODUCTION_STATIONS wyglada dokladnie tak samo.
    """
    from flask import g

    from modules.production.services import baselinker_status_sync as bl

    szpieg = _LoggerSzpieg()
    monkeypatch.setattr(bl, 'logger', szpieg)

    with app.app_context():
        bl.schedule_after_station_complete('26/00043', 'cutting')

        assert getattr(g, 'pending_baselinker_syncs', []) == []

    assert szpieg.ostrzezenia == []
    assert szpieg.bledy == []
