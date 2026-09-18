# -*- coding: utf-8 -*-
"""
Cofanie stanu druku po zadaniach, które nie trafiły na papier.

Stan rośnie przy WKŁADANIU do kolejki agenta, nie po wydruku — i tak ma
zostać, bo panel kafelków ustawia go bezwzględnie i musi zobaczyć skutek
natychmiast. Gdyby czekał na potwierdzenie, operator nacisnąłby drugi raz
i to samo zakolejkowałoby się podwójnie.

Ceną jest sztuka oznaczona jako wydrukowana, której nie ma na paczce — czyli
brak, którego nikt nie szuka. Na produkcji we wrześniu 2026 wygasło 51 zadań,
każde zostawiając ślad po etykiecie, która nie wyszła.

Prostujemy więc w drugą stronę: sztuka zdjęta ze zbioru wróci do wydrukowania,
co jest widoczne i tanie.

`label_index` niesie numer sztuki do odznaczenia i jest ustawiany TYLKO dla
zadań, które faktycznie zmieniły stan. Przedruk ma go pustego — jego porażka
nie może odznaczać sztuki, która leży już na paczce.
"""
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from extensions import db
from modules.production.models import (
    ProductionConfiguration, ProductionOrder, ProductionProduct,
)
from modules.production.services.label_print_service import (
    rollback_label_count_for_jobs,
)

from tests.krawedzie_fixtures import app  # noqa: F401


def _pozycja(licznik, ilosc=4, short='900_1'):
    # baselinker_order_id jest UNIQUE — wyprowadzamy je z numeru w short_id,
    # żeby dwie pozycje w jednym teście nie zderzyły się na tym kluczu.
    numer = short.split('_')[0]
    order = ProductionOrder(
        baselinker_order_id=int(numer) * 1000,
        internal_order_number=numer,
        client_name='Jan Kowalski',
    )
    db.session.add(order)
    db.session.flush()
    cfg = ProductionConfiguration.find_or_create('dąb', 'lity', 'A/B')
    db.session.flush()
    sztuki = list(range(1, min(licznik, ilosc) + 1))
    p = ProductionProduct(
        order_id=order.id,
        configuration_id=cfg.id,
        short_product_id=short,
        product_sequence_in_order=1,
        original_product_name='Blat dębowy',
        current_status='czeka_na_pakowanie',
        quantity=ilosc,
        label_print_count=len(sztuki),
        label_printed_units=sztuki,
    )
    db.session.add(p)
    db.session.commit()
    return p


def test_odznacza_dokladnie_wskazane_sztuki(app):
    """Nie ogon zbioru, tylko te sztuki, których dotyczyły nieudane zadania."""
    with app.app_context():
        p = _pozycja(licznik=4)

        rollback_label_count_for_jobs([
            SimpleNamespace(product_id=p.id, label_index=2),
            SimpleNamespace(product_id=p.id, label_index=4),
        ])
        db.session.commit()

        assert p.label_printed_units == [1, 3]
        assert p.label_print_count == 2


def test_odznaczenie_sztuki_spoza_zbioru_nic_nie_psuje(app):
    """
    Zadanie mogło dotyczyć sztuki, którą w międzyczasie zdjął już inny przebieg
    sprzątania. Ma to być bezczynność, a nie ujemny stan.
    """
    with app.app_context():
        p = _pozycja(licznik=2)

        rollback_label_count_for_jobs([
            SimpleNamespace(product_id=p.id, label_index=4),
        ])
        db.session.commit()

        assert p.label_printed_units == [1, 2]
        assert p.label_print_count == 2


def test_przedruk_bez_indeksu_nie_rusza_zbioru(app):
    """
    Nieudany przedruk. Sztuka wyszła wcześniej i leży na paczce — zdjęcie jej
    kazałoby operatorowi wydrukować coś, co już ma.
    """
    with app.app_context():
        p = _pozycja(licznik=3)

        dotkniete = rollback_label_count_for_jobs([
            SimpleNamespace(product_id=p.id, label_index=None),
        ])
        db.session.commit()

        assert dotkniete == 0
        assert p.label_printed_units == [1, 2, 3]


def test_zadania_bez_product_id_sa_pomijane(app):
    """
    Zadania sprzed migracji nie wiedzą, której pozycji dotyczyły —
    short_product_id dzielą oryginał i doróbka. Zgadywanie odznaczyłoby
    sztukę losowemu z dwóch wierszy.
    """
    with app.app_context():
        p = _pozycja(licznik=3)

        dotkniete = rollback_label_count_for_jobs([
            SimpleNamespace(product_id=None, label_index=1),
        ])
        db.session.commit()

        assert dotkniete == 0
        assert p.label_printed_units == [1, 2, 3]


def test_rozdziela_odznaczenia_miedzy_pozycje(app):
    """Jedno ACK potrafi nieść porażki kilku pozycji naraz."""
    with app.app_context():
        a = _pozycja(licznik=4, short='900_1')
        b = _pozycja(licznik=2, short='901_1')

        rollback_label_count_for_jobs([
            SimpleNamespace(product_id=a.id, label_index=1),
            SimpleNamespace(product_id=a.id, label_index=2),
            SimpleNamespace(product_id=b.id, label_index=2),
        ])
        db.session.commit()

        assert a.label_printed_units == [3, 4]
        assert b.label_printed_units == [1]
