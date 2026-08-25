# -*- coding: utf-8 -*-
"""
Agregat i eksport dziennego raportu produkcji.

Testy pilnują tego, na czym raport stoi i co już raz wywróciło się w projekcie:
filtr auto_skip/system, cofnięcia niewidoczne w netto, praca bez atrybucji,
oraz różnica między pustą komórką a zerem.
"""
import os
import sys
from datetime import date, datetime, time, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from flask import Flask
from sqlalchemy.pool import StaticPool

from extensions import db
from modules.production.models import (
    ProductionConfig, ProductionConfiguration, ProductionDevice, ProductionOrder,
    ProductionProduct, ProductionReworkLog, ProductionStationEvent,
    ProductionStationEventWorker, ProductionWorker, ProductionWorkerSession,
)
from modules.production.sawmill.models import (
    SawmillCounter, SawmillDelivery, SawmillLog, SawmillOrder,
    SawmillSpecies, SawmillSupplier,
)
from modules.production.services import daily_report_service
from modules.users.models import User
from modules.calculator.models import Multiplier  # noqa: F401
from modules.clients.models import Client  # noqa: F401
import modules.quotes.models  # noqa: F401

_TABLES = [m.__table__ for m in (
    User, ProductionDevice, ProductionConfig, ProductionOrder, ProductionProduct,
    ProductionConfiguration, ProductionWorker, ProductionWorkerSession,
    ProductionStationEvent, ProductionStationEventWorker, ProductionReworkLog,
    SawmillSupplier, SawmillSpecies, SawmillCounter, SawmillDelivery,
    SawmillOrder, SawmillLog,
)]

# shipping_label_base64 jest typem MySQL-owym (LONGTEXT) — SQLite go nie zna.
# Ta sama podmiana co w tests/test_reports_service.py:51.
ProductionOrder.__table__.c.shipping_label_base64.type = db.Text()

# Data odniesienia. Stała, nie get_local_now(): raport kubełkuje po dobach,
# więc test liczony „od dziś" przechodziłby przez inne gałęzie w poniedziałek
# niż w sobotę.
PONIEDZIALEK = date(2026, 8, 10)


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
        db.metadata.create_all(bind=db.engine, tables=_TABLES)
        yield app
        db.session.remove()


# ============================================================================
# POMOCNICZE
# ============================================================================

_licznik_zamowien = [0]


def _produkt(status='czeka_na_sklejanie', volume=0.5, quantity=10,
             deadline=None, wartosc=1000.0):
    """Zamówienie + pozycja. Własny licznik, bo baselinker_order_id jest UNIQUE."""
    _licznik_zamowien[0] += 1
    numer = _licznik_zamowien[0]
    order = ProductionOrder(baselinker_order_id=numer,
                            internal_order_number=f'26/{numer:05d}',
                            client_name='Klient Testowy')
    db.session.add(order)
    db.session.flush()
    produkt = ProductionProduct(
        order_id=order.id, short_product_id=f'26{numer:03d}_1',
        product_sequence_in_order=1,
        original_product_name='Blat', quantity=quantity, volume_m3=volume,
        total_value_net=wartosc,
        current_status=status, deadline_date=deadline,
        created_at=datetime.combine(PONIEDZIALEK, time(9, 0)))
    db.session.add(produkt)
    db.session.commit()
    return produkt


def _event(produkt, station, delta, kiedy, source='mobile', worker=None):
    ev = ProductionStationEvent(
        production_item_id=produkt.id, station_code=station, delta=delta,
        quantity_done_after=max(0, delta), created_at=kiedy, source=source)
    db.session.add(ev)
    db.session.flush()
    if worker is not None:
        db.session.add(ProductionStationEventWorker(
            event_id=ev.id, worker_id=worker.id, share=1.0))
    db.session.commit()
    return ev


def _pracownik(imie='Adam'):
    w = ProductionWorker(first_name=imie, last_name='Nowak')
    db.session.add(w)
    db.session.commit()
    return w


def _sesja(pracownik, station, dzien, od=time(8, 0), godzin=8):
    start = datetime.combine(dzien, od)
    sesja = ProductionWorkerSession(
        worker_id=pracownik.id, station_code=station,
        session_group=f'g-{station}-{dzien}',
        started_at=start, last_activity_at=start,
        ended_at=start + timedelta(hours=godzin), work_date=dzien)
    db.session.add(sesja)
    db.session.commit()
    return sesja


def _stanowisko(dane, kod):
    """Wiersz stanowiska z wyniku zbierz_dane()."""
    return next(s for s in dane['stanowiska'] if s['kod'] == kod)


# ============================================================================
# PRZERÓB PER STANOWISKO
# ============================================================================

def test_przerob_per_stanowisko(app):
    with app.app_context():
        p = _produkt()
        _event(p, 'gluing', 6, datetime.combine(PONIEDZIALEK, time(10, 0)))

        dane = daily_report_service.zbierz_dane(PONIEDZIALEK)

        gluing = _stanowisko(dane, 'gluing')
        assert gluing['sztuki'] == 6
        assert gluing['m3'] == pytest.approx(3.0)          # 6 × 0.5
        assert gluing['wartosc_netto'] == pytest.approx(600.0)  # 1000 × 6/10


def test_zdarzenia_automatu_nie_licza_sie_do_przerobu(app):
    """
    complete_task() generuje eventy dla stanowisk POMIJANYCH (cut_to_size=False
    przeskakuje formatowanie i wykańczanie). Bez filtra formatowanie dostaje
    sztuki, których nikt nie tknął.
    """
    with app.app_context():
        p = _produkt()
        _event(p, 'formatting', 10, datetime.combine(PONIEDZIALEK, time(11, 0)),
               source='auto_skip')
        _event(p, 'finishing', 10, datetime.combine(PONIEDZIALEK, time(11, 0)),
               source='system')

        dane = daily_report_service.zbierz_dane(PONIEDZIALEK)

        assert _stanowisko(dane, 'formatting')['sztuki'] == 0
        assert _stanowisko(dane, 'finishing')['sztuki'] == 0


def test_wszystkie_stanowiska_obecne_takze_bez_pracy(app):
    """
    Arkusz ma stały układ wierszy — stanowisko bez pracy pokazuje zera,
    a nie znika. Kolejność 1:1 z procesem produkcyjnym.
    """
    with app.app_context():
        dane = daily_report_service.zbierz_dane(PONIEDZIALEK)

        kody = [s['kod'] for s in dane['stanowiska']]
        assert kody == ['cutting', 'assembly', 'gluing', 'formatting',
                        'finishing', 'painting', 'packaging']
        assert all(s['sztuki'] == 0 for s in dane['stanowiska'])


def test_praca_z_sasiedniego_dnia_nie_wchodzi(app):
    """Granica doby: 23:59:59 należy do dnia, 00:00:00 do następnego."""
    with app.app_context():
        p = _produkt()
        _event(p, 'gluing', 3, datetime.combine(PONIEDZIALEK, time(23, 59, 59)))
        _event(p, 'gluing', 5,
               datetime.combine(PONIEDZIALEK + timedelta(days=1), time(0, 0, 0)))

        dane = daily_report_service.zbierz_dane(PONIEDZIALEK)

        assert _stanowisko(dane, 'gluing')['sztuki'] == 3
