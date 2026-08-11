# -*- coding: utf-8 -*-
"""
Statystyki wydajności pracowników (docs/worker-profiles-backend.md §7.2).

Najważniejsze tu jest to, czego raport NIE liczy: eventów automatu
(auto_skip/system). Bez tego filtra sklejacz dostaje kredyt za formatowanie,
którego nikt nie wykonał — a taki błąd trafia prosto do rozmowy o premiach.
"""
import os
import sys
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from flask import Flask
from sqlalchemy.pool import StaticPool

from extensions import db
from modules.production.models import (
    ProductionConfig, ProductionConfiguration, ProductionDevice, ProductionOrder,
    ProductionProduct, ProductionStationEvent, ProductionStationEventWorker,
    ProductionWorker, ProductionWorkerSession, get_local_now,
)
from modules.production.services import worker_stats_service
from modules.production.services.worker_stats_service import ZakresError
from modules.users.models import User
from modules.calculator.models import Multiplier  # noqa: F401
from modules.clients.models import Client  # noqa: F401
import modules.quotes.models  # noqa: F401

_TABLES = [m.__table__ for m in (
    User, ProductionDevice, ProductionConfig, ProductionOrder, ProductionProduct,
    ProductionConfiguration, ProductionWorker, ProductionWorkerSession,
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
    db.init_app(app)
    with app.app_context():
        db.metadata.create_all(bind=db.engine, tables=_TABLES)
        yield app
        db.session.remove()


def _produkt(volume=0.5, quantity=100):
    order = ProductionOrder(baselinker_order_id=1, internal_order_number='26/00001')
    db.session.add(order)
    db.session.flush()
    produkt = ProductionProduct(
        order_id=order.id, short_product_id='26001_1', product_sequence_in_order=1,
        original_product_name='Blat', quantity=quantity,
        current_status='czeka_na_sklejanie', volume_m3=volume)
    db.session.add(produkt)
    db.session.commit()
    return produkt


def _pracownicy(ilu=2):
    dodani = [ProductionWorker(first_name=f'Imie{i}', last_name=f'Nazwisko{i}')
              for i in range(ilu)]
    db.session.add_all(dodani)
    db.session.commit()
    return dodani


def _dzis():
    return get_local_now().date()


# ============================================================================
# WYDAJNOŚĆ
# ============================================================================

def test_praca_dzieli_sie_miedzy_pracownikow(app):
    with app.app_context():
        produkt = _produkt(volume=0.5)
        adam, bartek = _pracownicy(2)

        produkt.set_quantity_done('gluing', 10, source='mobile',
                                  actor_worker_ids=[adam.id, bartek.id])
        db.session.commit()

        raport = worker_stats_service.raport_wydajnosci(_dzis(), _dzis())

        assert len(raport['rows']) == 2
        assert all(w['pieces'] == 5.0 for w in raport['rows'])      # 10 szt / 2 osoby
        assert all(w['m3'] == 2.5 for w in raport['rows'])          # 0.5 m³ × 10 × 0.5
        assert raport['summary']['pieces'] == 10.0
        assert raport['summary']['attribution_coverage_pct'] == 100.0


def test_eventy_automatu_nie_licza_sie_nikomu(app):
    """
    Pułapka nr 2: complete_task() generuje sztuczne eventy dla stanowisk
    pominiętych. Nikt ich nie wykonał, więc nie mogą trafić do raportu —
    nawet gdyby ktoś nieopatrznie dopiął im atrybucję.
    """
    with app.app_context():
        produkt = _produkt()
        adam, = _pracownicy(1)

        produkt.set_quantity_done('gluing', 10, source='mobile',
                                  actor_worker_ids=[adam.id])
        produkt.set_quantity_done('formatting', 10, source='auto_skip',
                                  actor_worker_ids=[adam.id])
        produkt.set_quantity_done('finishing', 10, source='system',
                                  actor_worker_ids=[adam.id])
        db.session.commit()

        raport = worker_stats_service.raport_wydajnosci(_dzis(), _dzis())

        stanowiska = {w['station_code'] for w in raport['rows']}
        assert stanowiska == {'gluing'}
        assert raport['summary']['pieces'] == 10.0


def test_praca_bez_atrybucji_trafia_do_nieprzypisanych(app):
    """Produkcja sprzed wdrożenia profili nie może zniknąć z sum."""
    with app.app_context():
        produkt = _produkt()
        adam, = _pracownicy(1)

        produkt.set_quantity_done('gluing', 4, source='mobile',
                                  actor_worker_ids=[adam.id])
        produkt.set_quantity_done('gluing', 10, source='mobile')   # bez profilu
        db.session.commit()

        raport = worker_stats_service.raport_wydajnosci(_dzis(), _dzis())

        assert raport['summary']['pieces'] == 4.0
        assert raport['summary']['unassigned_pieces'] == 6.0
        # 4 z 10 sztuk wiadomo komu przypisać
        assert raport['summary']['attribution_coverage_pct'] == 40.0


def test_filtr_stanowiska(app):
    with app.app_context():
        produkt = _produkt()
        adam, = _pracownicy(1)
        produkt.set_quantity_done('gluing', 6, source='mobile', actor_worker_ids=[adam.id])
        produkt.set_quantity_done('packaging', 8, source='mobile', actor_worker_ids=[adam.id])
        db.session.commit()

        raport = worker_stats_service.raport_wydajnosci(_dzis(), _dzis(), station='gluing')

        assert [w['station_code'] for w in raport['rows']] == ['gluing']
        assert raport['summary']['pieces'] == 6.0


def test_filtr_pracownika_pomija_nieprzypisane(app):
    """Przy raporcie jednej osoby sekcja "Nieprzypisane" nie ma sensu."""
    with app.app_context():
        produkt = _produkt()
        adam, bartek = _pracownicy(2)
        produkt.set_quantity_done('gluing', 4, source='mobile', actor_worker_ids=[adam.id])
        produkt.set_quantity_done('gluing', 10, source='mobile')  # bez profilu
        db.session.commit()

        raport = worker_stats_service.raport_wydajnosci(_dzis(), _dzis(), worker_id=adam.id)

        assert raport['unassigned'] == []
        assert {w['worker_id'] for w in raport['rows']} == {adam.id}


def test_stanowiska_maja_polskie_nazwy(app):
    with app.app_context():
        produkt = _produkt()
        adam, = _pracownicy(1)
        produkt.set_quantity_done('gluing', 2, source='mobile', actor_worker_ids=[adam.id])
        db.session.commit()

        raport = worker_stats_service.raport_wydajnosci(_dzis(), _dzis())

        assert raport['rows'][0]['station_label'] == 'Sklejanie'


# ============================================================================
# CZAS PRACY I TEMPO
# ============================================================================

def test_tempo_liczone_z_czasu_sesji(app):
    with app.app_context():
        produkt = _produkt(volume=0.5)
        adam, = _pracownicy(1)

        start = get_local_now() - timedelta(hours=2)
        db.session.add(ProductionWorkerSession(
            worker_id=adam.id, station_code='gluing', session_group='g',
            started_at=start, last_activity_at=start,
            ended_at=start + timedelta(hours=2), work_date=start.date()))
        produkt.set_quantity_done('gluing', 10, source='mobile',
                                  actor_worker_ids=[adam.id])
        db.session.commit()

        raport = worker_stats_service.raport_wydajnosci(start.date(), _dzis())
        podsumowanie = raport['worker_totals'][0]

        assert podsumowanie['minutes'] == 120
        assert podsumowanie['hours'] == 2.0
        # 5 m³ w 2 godziny
        assert podsumowanie['pace_m3_per_hour'] == 2.5


def test_bez_sesji_tempo_jest_puste_a_nie_zerowe(app):
    """Brak pomiaru czasu to nie to samo co zerowa wydajność."""
    with app.app_context():
        produkt = _produkt()
        adam, = _pracownicy(1)
        produkt.set_quantity_done('gluing', 10, source='mobile', actor_worker_ids=[adam.id])
        db.session.commit()

        raport = worker_stats_service.raport_wydajnosci(_dzis(), _dzis())

        assert raport['worker_totals'][0]['pace_m3_per_hour'] is None
        assert raport['worker_totals'][0]['minutes'] == 0


def test_czas_pracy_respektuje_filtr_stanowiska(app):
    """
    Licznik (m³ z jednego stanowiska) i mianownik (czas pracy) muszą być
    filtrowane tak samo — inaczej tempo m³/h zaniża się tym, którzy pracują
    na kilku stanowiskach.
    """
    with app.app_context():
        adam, = _pracownicy(1)
        start = get_local_now().replace(hour=8, minute=0, second=0, microsecond=0)
        for kod, godziny in (('gluing', 2), ('packaging', 3)):
            db.session.add(ProductionWorkerSession(
                worker_id=adam.id, station_code=kod, session_group=f'g-{kod}',
                started_at=start, last_activity_at=start,
                ended_at=start + timedelta(hours=godziny), work_date=start.date()))
        db.session.commit()

        wszystkie = worker_stats_service.czas_pracy(_dzis(), _dzis())
        tylko_klejenie = worker_stats_service.czas_pracy(_dzis(), _dzis(), station='gluing')

        assert wszystkie[(adam.id, _dzis().isoformat())] == 300     # 2h + 3h
        assert tylko_klejenie[(adam.id, _dzis().isoformat())] == 120


def test_zapomniana_sesja_nie_fabrykuje_setek_godzin(app):
    """
    Dopóki nie ma wpisu w crontabie domykającego sesje, w bazie będą wisieć
    sesje sprzed tygodni. Bez przycięcia do nocnego cutoffu jedna taka sesja
    dawała w raporcie kilkaset godzin w jednej dobie.
    """
    with app.app_context():
        adam, = _pracownicy(1)
        dawno = get_local_now() - timedelta(days=30)
        db.session.add(ProductionWorkerSession(
            worker_id=adam.id, station_code='gluing', session_group='zapomniana',
            started_at=dawno.replace(hour=8, minute=0, second=0, microsecond=0),
            last_activity_at=dawno, work_date=dawno.date()))
        db.session.commit()

        minuty = worker_stats_service.czas_pracy(dawno.date(), _dzis())

        # Od 8:00 do nocnego cutoffu 23:00 to 15 godzin, nie 30 dni
        assert minuty[(adam.id, dawno.date().isoformat())] == 15 * 60


def test_otwarta_sesja_liczy_sie_do_teraz(app):
    with app.app_context():
        adam, = _pracownicy(1)
        start = get_local_now() - timedelta(minutes=45)
        db.session.add(ProductionWorkerSession(
            worker_id=adam.id, station_code='gluing', session_group='g',
            started_at=start, last_activity_at=start, work_date=start.date()))
        db.session.commit()

        minuty = worker_stats_service.czas_pracy(start.date(), _dzis())

        assert minuty[(adam.id, start.date().isoformat())] >= 44


# ============================================================================
# ZAKRES DAT
# ============================================================================

def test_odwrocony_zakres_dat_odrzucony(app):
    with app.app_context():
        with pytest.raises(ZakresError):
            worker_stats_service.raport_wydajnosci(date(2026, 8, 11), date(2026, 8, 1))


def test_zbyt_dlugi_zakres_odrzucony(app):
    with app.app_context():
        with pytest.raises(ZakresError):
            worker_stats_service.raport_wydajnosci(date(2025, 1, 1), date(2026, 8, 11))


def test_praca_poza_zakresem_nie_wchodzi_do_raportu(app):
    with app.app_context():
        produkt = _produkt()
        adam, = _pracownicy(1)
        produkt.set_quantity_done('gluing', 10, source='mobile', actor_worker_ids=[adam.id])
        db.session.commit()

        wczoraj = _dzis() - timedelta(days=1)
        raport = worker_stats_service.raport_wydajnosci(wczoraj, wczoraj)

        assert raport['rows'] == []
        assert raport['summary']['attribution_coverage_pct'] is None


# ============================================================================
# KTO ZROBIŁ (§7.3)
# ============================================================================

def test_kto_zrobil_dla_wielu_produktow(app):
    with app.app_context():
        produkt = _produkt()
        adam, bartek = _pracownicy(2)
        produkt.set_quantity_done('gluing', 5, source='mobile',
                                  actor_worker_ids=[adam.id, bartek.id])
        produkt.set_quantity_done('packaging', 5, source='mobile',
                                  actor_worker_ids=[bartek.id])
        db.session.commit()

        mapa = worker_stats_service.get_workers_for_products([produkt.id])

        assert mapa[produkt.id]['gluing'] == ['Imie0 N.', 'Imie1 N.']
        assert mapa[produkt.id]['packaging'] == ['Imie1 N.']


def test_kto_zrobil_bez_produktow_nie_odpytuje_bazy(app):
    with app.app_context():
        assert worker_stats_service.get_workers_for_products([]) == {}


def test_kto_zrobil_pomija_eventy_automatu(app):
    with app.app_context():
        produkt = _produkt()
        adam, = _pracownicy(1)
        produkt.set_quantity_done('formatting', 5, source='auto_skip',
                                  actor_worker_ids=[adam.id])
        db.session.commit()

        assert worker_stats_service.get_workers_for_products([produkt.id]) == {}
