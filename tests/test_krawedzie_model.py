# -*- coding: utf-8 -*-
"""
Model produkcji po podziale Wykańczania na Krawędzie i Lakiernię.

Warstwa W1: enum statusu, nazwy kolumn licznika i znacznika czasu, normalizacja
przejściowego kodu 'finishing' oraz zbiory kodów stanowisk. Routing produktu ma
własny plik — tests/test_routing_krawedzie.py.

UWAGA (zweryfikowane empirycznie na SQLAlchemy 1.4.54): Enum NIE waliduje
wartości po stronie Pythona przy ZAPISIE (validate_strings domyślnie False),
a na SQLite kolumna to zwykły VARCHAR bez CHECK. Zapis wartości spoza enuma
przechodzi bez błędu; LookupError pojawia się dopiero przy ODCZYCIE wartości
spoza enuma z bazy. Zestaw wartości sprawdzamy więc WYŁĄCZNIE na definicji
kolumny w modelu. Zielony test NIE dowodzi, że migracja MySQL powstała.

Ten plik nie zakłada tabeli prod_product_events, bo nie robi tego żaden inny
plik w pakiecie — listener audytu milczy w całym przebiegu i tak ma zostać.
"""
import itertools
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from flask import Flask
from sqlalchemy.pool import StaticPool

from extensions import db
from modules.production.models import (
    ProductionConfiguration, ProductionDevice, ProductionOrder,
    ProductionProduct, ProductionReworkLog,
    ProductionStationEvent, ProductionWorker,
)
from modules.production.services.station_catalog import (
    STATION_ORDER, STATION_PENDING_STATUS,
)
from modules.users.models import User
from modules.calculator.models import Multiplier  # noqa: F401
from modules.clients.models import Client  # noqa: F401
import modules.quotes.models  # noqa: F401

_TABELE = [m.__table__ for m in (
    User, ProductionDevice, ProductionOrder, ProductionProduct,
    ProductionConfiguration, ProductionWorker, ProductionStationEvent,
    ProductionReworkLog,
)]

# LONGTEXT nie istnieje w SQLite — ten sam zabieg co w tests/test_worker_stats.py.
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
        db.metadata.create_all(bind=db.engine, tables=_TABELE)
        yield app
        db.session.remove()


_licznik = itertools.count(1)


def _produkt(finish='surowe', edge=False, cut_to_size=True, quantity=10,
             status='czeka_na_formatowanie'):
    """Produkt z zamówieniem KURIERSKIM.

    Adres, miasto i kod pocztowy są obowiązkowe: ProductionOrder.is_personal_pickup
    (models.py:171-183) uznaje zamówienie BEZ żadnego z tych pól za odbiór osobisty,
    co po cichu zamieniłoby logistykę na pakowanie.
    """
    numer = next(_licznik)
    zamowienie = ProductionOrder(
        baselinker_order_id=numer,
        internal_order_number='26/%05d' % numer,
        delivery_method='Kurier DPD',
        delivery_address='ul. Testowa 1',
        delivery_city='Warszawa',
        delivery_postcode='00-001')
    db.session.add(zamowienie)
    db.session.flush()
    produkt = ProductionProduct(
        order_id=zamowienie.id,
        short_product_id='26%03d_1' % numer,
        product_sequence_in_order=1,
        original_product_name='Blat dębowy',
        quantity=quantity,
        current_status=status,
        parsed_finish_type=finish,
        parsed_edge_processing=edge,
        cut_to_size=cut_to_size)
    db.session.add(produkt)
    db.session.commit()
    return produkt


# ============================================================================
# ENUM STATUSU
# ============================================================================

def test_enum_statusu_zna_krawedzie_a_nie_wykanczanie():
    wartosci = list(ProductionProduct.__table__.c.current_status.type.enums)
    assert 'czeka_na_krawedzie' in wartosci
    assert 'czeka_na_wykanczanie' not in wartosci


def test_enum_statusu_ma_dokladnie_dwanascie_wartosci_bez_duplikatow():
    """
    Wzmocnienie testu porządku poniżej: `index(krawedzie) == index(formatowanie) + 1`
    sprawdza WYŁĄCZNIE pozycję względną, więc przepuściłby literówkę wstawiającą
    'czeka_na_krawedzie' DRUGI raz gdzieś dalej w liście (np. przez kopiuj-wklej
    całego bloku) — pierwsze wystąpienie nadal siedziałoby na właściwym miejscu,
    a `index()` zwraca zawsze PIERWSZE dopasowanie, więc duplikat by się nie ujawnił.
    Tu liczymy elementy wprost i porównujemy z zbiorem, żeby taki duplikat złapać.
    """
    wartosci = list(ProductionProduct.__table__.c.current_status.type.enums)
    assert len(wartosci) == 12
    assert len(wartosci) == len(set(wartosci))


def test_status_krawedzi_stoi_miedzy_formatowaniem_a_lakiernia():
    """Kolejność wartości to kontrakt z ostatnim ALTER-em migracji (sekcja 6)."""
    wartosci = list(ProductionProduct.__table__.c.current_status.type.enums)
    assert wartosci.index('czeka_na_krawedzie') == wartosci.index('czeka_na_formatowanie') + 1
    assert wartosci.index('czeka_na_lakiernie') == wartosci.index('czeka_na_krawedzie') + 1


def test_kazdy_status_kolejki_z_katalogu_jest_w_enumie_produktu():
    """
    Sprzęgło katalog ↔ model. station_catalog (W0) już mówi 'czeka_na_krawedzie';
    dopóki enum modelu o tym nie wie, dashboard i raporty filtrują po wartości,
    której nie da się zapisać. Rozjazd MUSI być czerwony, a nie cichy.
    """
    wartosci = set(ProductionProduct.__table__.c.current_status.type.enums)
    for kod in STATION_ORDER:
        assert STATION_PENDING_STATUS[kod] in wartosci, kod


def test_nazwa_statusu_krawedzi_jest_po_polsku():
    produkt = ProductionProduct(current_status='czeka_na_krawedzie')
    assert produkt.status_display_name == 'Czeka na krawędzie'


def test_archiwalny_status_wykanczania_dalej_ma_nazwe():
    """
    prod_product_events trzyma 'czeka_na_wykanczanie' jako ZWYKŁY TEKST
    w old_value/new_value (423 wiersze na produkcji). Historia produktu nie może
    po zmianie pokazywać surowego kodu, więc etykieta zostaje mimo zdjęcia
    wartości z enuma.
    """
    produkt = ProductionProduct(current_status='czeka_na_wykanczanie')
    assert produkt.status_display_name == 'Czeka na wykańczanie (archiwalne)'
