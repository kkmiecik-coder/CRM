# -*- coding: utf-8 -*-
"""
Wspólne narzędzia testów panelu po podziale Wykańczania na Krawędzie i Lakiernię.

Zwykły moduł pomocniczy, NIE conftest — konwencja tests/sawmill_fixtures.py.
Importuj w pliku testów:

    from tests.krawedzie_fixtures import BASE, app, client, produkt  # noqa: F401

Frontu nie da się tu uruchomić (obraz testowy jest bez node'a), więc pliki JS
i szablony sprawdzamy strukturalnie na źródle — konwencja tests/test_checkout_js.py.
Stąd obok fixture'ów Flaska stoją w tym module ścieżki do plików frontu.

Ten moduł nie zakłada tabeli prod_product_events, bo nie robi tego żaden inny
plik w pakiecie — listener audytu milczy w całym przebiegu i tak ma zostać.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from flask import Blueprint, Flask
from flask_login import AnonymousUserMixin, LoginManager
from sqlalchemy.pool import StaticPool

from extensions import db
from modules.production.models import (
    ProductionConfig, ProductionConfiguration, ProductionDevice, ProductionOrder,
    ProductionProduct, ProductionStationEvent,
    ProductionStationEventWorker, ProductionWorker, ProductionWorkerSession,
)
from modules.users.models import User
# configure_mappers() przy pierwszym zapytaniu konfiguruje CAŁY rejestr mapperów —
# bez tych importów wywala się na relationship('Multiplier')/('Client')/('QuoteStatus').
from modules.calculator.models import Multiplier  # noqa: F401
from modules.clients.models import Client  # noqa: F401
import modules.quotes.models  # noqa: F401

KORZEN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = '/production/api'

# LONGTEXT (MySQL) nie istnieje w SQLite — jak w tests/test_archive_tab.py
ProductionOrder.__table__.c.shipping_label_base64.type = db.Text()

TABLES = [m.__table__ for m in (
    User, ProductionDevice, ProductionConfig, ProductionOrder, ProductionProduct,
    ProductionConfiguration, ProductionWorker, ProductionWorkerSession,
    ProductionStationEvent, ProductionStationEventWorker,
)]

SZABLON_STANOWISK = os.path.join(KORZEN, 'modules', 'production', 'templates',
                                 'components', 'stations-tab-content.html')
SZABLON_PRODUKTOW = os.path.join(KORZEN, 'modules', 'production', 'templates',
                                 'components', 'products-tab-content.html')
JS_PRODUKTY = os.path.join(KORZEN, 'modules', 'production', 'static', 'js',
                           'modules', 'products-module.js')
JS_ARCHIWUM = os.path.join(KORZEN, 'modules', 'production', 'static', 'js',
                           'modules', 'archive-module.js')
PY_PRODUCTS_API = os.path.join(KORZEN, 'modules', 'production', 'routers', 'api',
                               'products_api.py')


def zrodlo(sciezka):
    """Treść pliku do sprawdzeń strukturalnych."""
    with open(sciezka, encoding='utf-8') as f:
        return f.read()


@pytest.fixture()
def app():
    """
    Minimalna apka z blueprintem API produkcji.

    LoginManager jest tu potrzebny naprawdę: stations_api.py:24 i products_api
    czytają current_user.id (a przy korekcie licznika także current_user.email)
    w logach, a bez zarejestrowanego managera flask_login rzuca AttributeError
    i endpoint oddaje 500. LOGIN_DISABLED przepuszcza login_required,
    a podmieniony anonymous_user udaje admina.
    """
    app = Flask(__name__, template_folder=os.path.join(
        KORZEN, 'modules', 'production', 'templates'))
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        'poolclass': StaticPool,
        'connect_args': {'check_same_thread': False},
    }
    app.config['LOGIN_DISABLED'] = True

    class _AdminTestowy(AnonymousUserMixin):
        id = 1
        email = 'test@woodpower.pl'
        role = 'admin'
        is_authenticated = True

    menedzer = LoginManager()
    menedzer.anonymous_user = _AdminTestowy
    menedzer.init_app(app)

    @menedzer.user_loader
    def _zaladuj_uzytkownika(user_id):
        return User.query.get(int(user_id))

    from modules.production.routers.api import api_bp

    # Szablon zakładki Stanowiska buduje adresy przez
    # url_for('production.production_stations.monitor_station'). Bez tej atrapy
    # render_template wywala się na BuildError, a endpoint oddaje 500.
    atrapa_stanowisk = Blueprint('production_stations', __name__)

    @atrapa_stanowisk.route('/monitors/<station_code>')
    def monitor_station(station_code):
        return ''

    produkcja = Blueprint('production', __name__)
    produkcja.register_blueprint(atrapa_stanowisk, url_prefix='/stations')
    produkcja.register_blueprint(api_bp, url_prefix='/api')
    app.register_blueprint(produkcja, url_prefix='/production')
    db.init_app(app)

    with app.app_context():
        db.metadata.create_all(bind=db.engine, tables=TABLES)
        db.session.add(User(id=1, email='test@woodpower.pl',
                            password='x', role='admin'))
        db.session.commit()
        yield app
        db.session.remove()


@pytest.fixture()
def client(app):
    return app.test_client()


def produkt(app, status='czeka_na_krawedzie', quantity=4, edge_processing=True,
            finish_state='surowe', numer='25/00001', **kolumny):
    """
    Zamówienie z jedną pozycją. Zwraca (id_produktu, short_product_id).

    short_product_id musi pasować do ^\\d+_\\d+$ (@validates, models.py:321-326),
    stąd ukośnik z numeru zamówienia wypada.
    kolumny — dodatkowe pola ProductionProduct, np. edges_completed_at=...
    """
    with app.app_context():
        order = ProductionOrder(
            baselinker_order_id=int(numer.replace('/', '')),
            internal_order_number=numer,
            client_name='Jan Kowalski',
        )
        db.session.add(order)
        db.session.flush()
        cfg = ProductionConfiguration.find_or_create('dąb', 'lity', 'A/B')
        db.session.flush()
        pozycja = ProductionProduct(
            order_id=order.id,
            configuration_id=cfg.id,
            short_product_id=numer.replace('/', '') + '_1',
            product_sequence_in_order=1,
            original_product_name='Blat dębowy',
            current_status=status,
            quantity=quantity,
            volume_m3=0.1,
            total_value_net=1000,
            parsed_thickness_cm=4.0,
            parsed_length_cm=200.0,
            parsed_width_cm=80.0,
            parsed_edge_processing=edge_processing,
            parsed_finish_state=finish_state,
            **kolumny
        )
        db.session.add(pozycja)
        db.session.commit()
        return pozycja.id, pozycja.short_product_id
