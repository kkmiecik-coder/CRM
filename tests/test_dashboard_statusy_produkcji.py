# -*- coding: utf-8 -*-
"""
Widget „Przegląd produkcji" na dashboardzie głównym.

chart_service.get_production_overview() trzyma JEDYNĄ w aplikacji mapę statusów
produkcji całkowicie odciętą od station_catalog — moduł dashboardu celowo nie
importuje modułu produkcji, więc nic nie pilnuje zgodności tych dwóch list.

Brakujący klucz nie wywala wykresu: segment dostaje SUROWY enum jako nazwę
('czeka_na_krawedzie' w legendzie) i szary kolor rezerwowy #94a3b8. Psuje się
po cichu, dlatego mapa potrzebuje testu, a nie tylko komentarza.

UWAGA przy pisaniu asercji: kolor rezerwowy #94a3b8 jest IDENTYCZNY z kolorem
przypisanym 'czeka_na_wyciecie', więc „brak koloru rezerwowego w wyniku" nie
jest wiarygodnym sitem. Sprawdzamy dokładną mapę nazwa → kolor.

Ten plik nie zakłada tabeli prod_product_events, bo nie robi tego żaden inny
plik w pakiecie — listener audytu milczy w całym przebiegu i tak ma zostać.
"""
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from flask import Flask
from sqlalchemy.pool import StaticPool

from extensions import db
from modules.dashboard.services import chart_service
from modules.production.models import (
    ProductionConfig, ProductionConfiguration, ProductionDevice, ProductionOrder,
    ProductionProduct, ProductionReworkLog,
    ProductionStationEvent, ProductionStationEventWorker, ProductionWorker,
    ProductionWorkerSession,
)
from modules.production.services.station_catalog import STATION_PENDING_STATUS
from modules.users.models import User
from modules.calculator.models import Multiplier  # noqa: F401
from modules.clients.models import Client  # noqa: F401
import modules.quotes.models  # noqa: F401

ProductionOrder.__table__.c.shipping_label_base64.type = db.Text()

TABELE = [m.__table__ for m in (
    User, ProductionDevice, ProductionConfig, ProductionOrder, ProductionProduct,
    ProductionConfiguration, ProductionWorker, ProductionWorkerSession,
    ProductionStationEvent, ProductionStationEventWorker, ProductionReworkLog,
)]

_licznik_zamowien = [0]


@pytest.fixture()
def app():
    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        'poolclass': StaticPool,
        'connect_args': {'check_same_thread': False},
    }
    db.init_app(app)
    with app.app_context():
        db.metadata.create_all(bind=db.engine, tables=TABELE)
        yield app
        db.session.remove()


def _produkt(status):
    _licznik_zamowien[0] += 1
    numer = _licznik_zamowien[0]
    order = ProductionOrder(baselinker_order_id=numer,
                            internal_order_number=f'26/{numer:05d}',
                            client_name='Klient Testowy')
    db.session.add(order)
    db.session.flush()
    produkt = ProductionProduct(
        order_id=order.id, short_product_id=f'26{numer:03d}_1',
        product_sequence_in_order=1, original_product_name='Blat',
        quantity=1, volume_m3=0.5, current_status=status,
        created_at=datetime(2026, 8, 10, 9, 0))
    db.session.add(produkt)
    db.session.commit()
    return produkt


def test_kazda_kolejka_stanowiska_ma_polska_nazwe(app):
    """
    Sygnatura brakującego klucza jest jednoznaczna: nazwą segmentu staje się
    surowy enum. Test porównuje zbiór nazw ze zbiorem enumów — przecięcie musi
    być puste.
    """
    with app.app_context():
        for status in STATION_PENDING_STATUS.values():
            _produkt(status)

        dane = chart_service.get_production_overview()

        nazwy = {s['name'] for s in dane['statuses']}
        assert not (nazwy & set(STATION_PENDING_STATUS.values())), nazwy
        assert len(nazwy) == len(STATION_PENDING_STATUS)
        assert dane['total_items'] == len(STATION_PENDING_STATUS)


def test_krawedzie_lakiernia_i_logistyka_maja_wlasne_nazwy_i_kolory(app):
    """
    Trzy segmenty, które po zmianie trasy urosną: Krawędzie (nowa nazwa),
    Lakiernia i Logistyka (dziś w ogóle nieznane tej mapie).
    """
    with app.app_context():
        _produkt('czeka_na_krawedzie')
        _produkt('czeka_na_lakiernie')
        _produkt('czeka_na_logistyke')

        dane = chart_service.get_production_overview()

        assert {s['name']: s['color'] for s in dane['statuses']} == {
            'Czeka na krawędzie': '#06b6d4',
            'Czeka na lakiernię': '#e11d48',
            'Czeka na logistykę': '#0d9488',
        }
