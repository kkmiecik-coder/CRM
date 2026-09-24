# -*- coding: utf-8 -*-
"""
Kolejka do przeliczania priorytetów po rozdzieleniu wykańczania.

priority_service trzyma TRZY równoległe kopie listy statusów „w toku":
active_statuses w konstruktorze kalkulatora oraz dwa literały w
get_priority_statistics(). Każda pominięta kopia to pozycje, które po cichu
wypadają z przeliczania priorytetów — bez błędu i bez logu.

Przy okazji domykamy błąd istniejący przed tą zmianą: żadna z trzech list nie
zawierała 'czeka_na_lakiernie'. Po zmianie trasy (produkt olejowany bez obróbki
krawędzi idzie z formatowania PROSTO do Lakierni) ta populacja rośnie.

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
from modules.production.models import (
    ProductionConfig, ProductionConfiguration, ProductionDevice, ProductionOrder,
    ProductionProduct, ProductionReworkLog,
    ProductionStationEvent, ProductionStationEventWorker, ProductionWorker,
    ProductionWorkerSession,
)
from modules.production.services import priority_service
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
        product_sequence_in_order=1, original_product_name='Blat',
        quantity=1, volume_m3=0.5, current_status=status,
        created_at=datetime(2026, 8, 10, 9, 0))
    db.session.add(produkt)
    db.session.commit()
    return produkt


def test_kalkulator_zna_obie_kolejki_po_rozdziale():
    aktywne = priority_service.NewPriorityCalculator().active_statuses

    assert 'czeka_na_krawedzie' in aktywne
    assert 'czeka_na_lakiernie' in aktywne
    assert 'czeka_na_wykanczanie' not in aktywne


def test_statystyki_licza_pozycje_krawedzi_i_lakierni(app):
    """Druga kopia listy — active_count w get_priority_statistics()."""
    with app.app_context():
        _produkt('czeka_na_krawedzie')
        _produkt('czeka_na_lakiernie')
        _produkt('spakowane')

        stat = priority_service.get_priority_statistics()

        # get_priority_statistics() połyka wyjątki i oddaje zera z kluczem
        # 'error' — bez tej asercji zielony wynik nic by nie znaczył.
        assert 'error' not in stat, stat
        assert stat['active_products_count'] == 2


def test_statystyki_licza_reczne_nadpisania_na_nowych_stanowiskach(app):
    """Trzecia kopia listy — manual_overrides w get_priority_statistics()."""
    with app.app_context():
        produkt = _produkt('czeka_na_lakiernie')
        produkt.priority_manual_override = True
        db.session.commit()

        stat = priority_service.get_priority_statistics()

        assert 'error' not in stat, stat
        assert stat['manual_overrides_count'] == 1


# ===== nieudane przeliczanie nie zostawia brudnej sesji =================
#
# ZNALEZISKO (kontrola adwersaryjna 22.09.2026): `recalculate_all_priorities`
# na sciezce bledu NIE robilo rollbacku, a KROK 2
# (`update_thickness_groups_batch`) zdazyl juz pozmieniac obiekty ORM-a.
# Awaria zostawiala wiec `db.session` BRUDNA: z polowa przeliczonych
# priorytetow wiszaca w sesji, gotowa do zatwierdzenia przez pierwszy lepszy
# commit kogos innego.
#
# Skutek uboczny byl gorszy od samego brudu: dopoki analityka sprzedazowa
# pisala po WSPOLDZIELONEJ sesji, jej straznik odrzucal wtedy CALA paczke
# i liczyl ja jako pominieta. „Pobieranie na produkcji zasila analityke"
# przestawalo dzialac bez zadnego widocznego bledu.

def _produkt_z_gruboscia():
    """Pozycja w kolejce z `parsed_thickness_cm`, ale BEZ `thickness_group`.

    Taki uklad sprawia, ze `update_thickness_groups_batch` naprawde cos
    zmieni (None -> '2.6-3.5') i sesja zrobi sie brudna.
    """
    _licznik_zamowien[0] += 1
    numer = _licznik_zamowien[0]
    order = ProductionOrder(baselinker_order_id=numer,
                            internal_order_number='26/%05d' % numer,
                            client_name='Klient Testowy')
    db.session.add(order)
    db.session.flush()
    produkt = ProductionProduct(
        order_id=order.id, short_product_id='26%03d_1' % numer,
        product_sequence_in_order=1, original_product_name='Blat',
        quantity=1, volume_m3=0.5, current_status='czeka_na_wyciecie',
        parsed_thickness_cm=3.0, thickness_group=None,
        created_at=datetime(2026, 8, 10, 9, 0))
    db.session.add(produkt)
    db.session.commit()
    return produkt


def test_nieudane_przeliczanie_priorytetow_czysci_sesje(app, monkeypatch):
    with app.app_context():
        produkt = _produkt_z_gruboscia()
        id_produktu = produkt.id

        kalkulator = priority_service.NewPriorityCalculator()
        # `get_active_products_for_prioritization` sortuje przez `func.isnull`,
        # ktorego SQLite nie zna — podstawiamy sama liste pozycji, zeby reszta
        # metody (w tym KROK 2 brudzacy sesje) wykonala sie NAPRAWDE.
        monkeypatch.setattr(kalkulator, 'get_active_products_for_prioritization',
                            lambda: [produkt])

        def wybuch(produkty):
            raise RuntimeError('sztuczna awaria przeliczania')

        monkeypatch.setattr(kalkulator, 'group_products_by_weeks', wybuch)

        wynik = kalkulator.recalculate_all_priorities()

        assert wynik['success'] is False
        assert 'sztuczna awaria' in wynik['error']
        # Sedno: sesja jest czysta, a niedokonczona zmiana nie czeka
        # na cudzy commit.
        assert list(db.session.dirty) == []
        assert list(db.session.new) == []

    with app.app_context():
        db.session.remove()
        zapisany = db.session.query(ProductionProduct).get(id_produktu)
        assert zapisany.thickness_group is None
