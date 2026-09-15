# -*- coding: utf-8 -*-
"""
Trasa doróbki po rozdziale Wykańczania na Krawędzie i Lakiernię.

Doróbka jedzie linią od nowa, a jej trasa po formatowaniu wynika WYŁĄCZNIE
z pól skopiowanych z oryginału: parsed_edge_processing, parsed_finish_type
i cut_to_size. Doróbka zdjęta z produktu olejowanego BEZ obróbki krawędzi
ominie Krawędzie, choć oryginał przeszedł jeszcze przez wykańczalnię —
to świadomy skutek nowej trasy, nie błąd kopiowania.

Do kompletu należy `shape`: nie decyduje o trasie, ale idzie do DTO tabletu
(mobile_api_service.py:1071) obok kopiowanego shape_svg. Bez niego doróbka
startuje z kolumnowym default='rectangular' (models.py:257) i pokazuje
operatorowi inny kształt niż oryginał.

Ten plik nie zakłada tabeli prod_product_events, bo nie robi tego żaden inny
plik w pakiecie — listener audytu milczy w całym przebiegu i tak ma zostać.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from flask import Flask
from sqlalchemy.pool import StaticPool

from extensions import db
from modules.production.models import (
    ProductionConfiguration, ProductionOrder, ProductionProduct,
    ProductionReworkLog, ProductionStationEvent,
)
from modules.production.services.rework_service import (
    RejectError, VALID_REJECT_STATIONS, reject_product_quantity,
)
from modules.users.models import User
# Importy wymagane, żeby topologiczne sortowanie FK w create_all znalazło tabelę
# 'users' — ten sam powód co w tests/test_mobile_complete_bl_sync_queue.py.
from modules.calculator.models import Multiplier  # noqa: F401
from modules.clients.models import Client  # noqa: F401
import modules.quotes.models  # noqa: F401

_TABLES = [m.__table__ for m in (
    User, ProductionOrder, ProductionProduct, ProductionConfiguration,
    ProductionReworkLog, ProductionStationEvent,
)]

# SQLite nie zna typu MySQL LONGTEXT — to samo obejście co w pozostałych
# testach dotykających ProductionOrder.
ProductionOrder.__table__.c.shipping_label_base64.type = db.Text()


@pytest.fixture()
def app():
    aplikacja = Flask(__name__)
    aplikacja.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
    aplikacja.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    aplikacja.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        'poolclass': StaticPool,
        'connect_args': {'check_same_thread': False},
    }
    db.init_app(aplikacja)
    with aplikacja.app_context():
        db.metadata.create_all(bind=db.engine, tables=_TABLES)
        yield aplikacja
        db.session.remove()


def _oryginal(app, **nadpisania):
    """Produkt stojący na formatowaniu, gotowy do zdjęcia doróbki."""
    with app.app_context():
        order = ProductionOrder(
            baselinker_order_id=990003,
            internal_order_number='26/00045',
            delivery_method='Kurier DPD',
            delivery_address='ul. Dębowa 1',
            delivery_city='Poznań',
            delivery_postcode='61-001',
        )
        db.session.add(order)
        db.session.flush()

        dane = dict(
            order_id=order.id,
            short_product_id='26045_1',
            product_sequence_in_order=1,
            original_product_name='Blat dębowy 200x60x4',
            quantity=3,
            current_status='czeka_na_formatowanie',
            parsed_finish_type='surowe',
            parsed_edge_processing=True,
            cut_to_size=True,
            shape='round',
        )
        dane.update(nadpisania)
        product = ProductionProduct(**dane)
        db.session.add(product)
        db.session.commit()
        return product.id


def test_dorobka_dziedziczy_pola_decydujace_o_trasie(app):
    product_id = _oryginal(
        app, parsed_finish_type='lakierowane', parsed_edge_processing=True, shape='round')

    with app.app_context():
        _org, dorobka, _log = reject_product_quantity(
            product_id=product_id,
            quantity=1,
            reason_category='wymiary',
            rejected_at_station='formatting',
        )

        assert dorobka.parsed_edge_processing is True
        assert dorobka.parsed_finish_type == 'lakierowane'
        assert dorobka.cut_to_size is True
        # Nie decyduje o trasie, ale idzie do DTO tabletu. Bez kopiowania
        # doróbka dostaje kolumnowy default 'rectangular'.
        assert dorobka.shape == 'round'


def test_dorobka_olejowanego_bez_krawedzi_omija_krawedzie(app):
    """Nowa gałąź routingu: formatowanie → Lakiernia, z pominięciem Krawędzi."""
    product_id = _oryginal(
        app, parsed_finish_type='olejowane', parsed_edge_processing=False)

    with app.app_context():
        _org, dorobka, _log = reject_product_quantity(
            product_id=product_id,
            quantity=1,
            reason_category='jakosc_produktu',
            rejected_at_station='formatting',
        )

        dorobka.complete_task('formatting')
        db.session.commit()

        assert dorobka.current_status == 'czeka_na_lakiernie'
        assert dorobka.quantity_done_edges == dorobka.quantity
        assert dorobka.edges_completed_at is not None


def test_dorobka_z_krawedziami_staje_na_krawedziach(app):
    product_id = _oryginal(
        app, parsed_finish_type='surowe', parsed_edge_processing=True)

    with app.app_context():
        _org, dorobka, _log = reject_product_quantity(
            product_id=product_id,
            quantity=1,
            reason_category='jakosc_sklejenia',
            rejected_at_station='formatting',
        )

        dorobka.complete_task('formatting')
        db.session.commit()

        assert dorobka.current_status == 'czeka_na_krawedzie'
        assert dorobka.quantity_done_edges == 0
        assert dorobka.edges_completed_at is None


def test_reject_nie_przyjmuje_kodu_krawedzi(app):
    """
    Enum prod_rework_log.rejected_at_station ma jedynego writera:
    mobile_api.py:452 przekazuje tam station_code z routera. Po wprowadzeniu
    aliasu trafia tam kod kanoniczny, więc teoretycznie mogłoby to być 'edges'.

    Enum SQLAlchemy NIE zatrzymałby takiej wartości przy zapisie (validate_strings
    jest domyślnie False — LookupError pojawia się dopiero przy ODCZYCIE wartości
    spoza enuma z bazy), więc jedyną realną barierą jest VALID_REJECT_STATIONS,
    które zatrzymuje wszystko poza formatowaniem. ALTER enuma w migracji jest
    więc defensywny, nie warunkowy; ten strażnik pilnuje, żeby nikt nie rozszerzył
    zbioru bez świadomej decyzji.
    """
    assert VALID_REJECT_STATIONS == {'formatting'}

    product_id = _oryginal(app)

    with app.app_context():
        for kod in ('edges', 'finishing'):
            with pytest.raises(RejectError) as wyjatek:
                reject_product_quantity(
                    product_id=product_id,
                    quantity=1,
                    reason_category='inne',
                    rejected_at_station=kod,
                )
            assert wyjatek.value.code == 'invalid_station'


def test_dorobka_dziedziczy_shape_gdy_oryginal_ma_inny_ksztalt_niz_default(app):
    """
    Wzmocnienie: 'round' bywa jednocześnie wartością testowanej kolumny i tym,
    co dostałaby doróbka BEZ kopiowania, gdyby ktoś (błędnie) ustawił nowy
    default kolumny na 'round' zamiast 'rectangular'. Powtarzamy asercję
    z niestandardowym kształtem 'trapezoid', żeby przypadkowa zgodność
    z defaultem nie mogła ukryć brakującego przypisania shape=original.shape.
    """
    product_id = _oryginal(app, shape='trapezoid')

    with app.app_context():
        _org, dorobka, _log = reject_product_quantity(
            product_id=product_id,
            quantity=1,
            reason_category='wymiary',
            rejected_at_station='formatting',
        )

        assert dorobka.shape == 'trapezoid'
