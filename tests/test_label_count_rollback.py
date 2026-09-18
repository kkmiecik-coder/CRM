# -*- coding: utf-8 -*-
"""
Cofanie licznika wydrukowanych etykiet po zadaniach, które nie trafiły na papier.

Licznik rośnie przy WKŁADANIU do kolejki agenta, nie po wydruku — i tak ma
zostać, bo aplikacja stanowiskowa ustawia go bezwzględnie („drukuj do ósmej")
i musi zobaczyć skutek natychmiast. Gdyby czekał na potwierdzenie, operator
nacisnąłby drugi raz i to samo zakolejkowałoby się podwójnie.

Ceną jest zawyżony licznik po nieudanym zadaniu. Zawyżony znaczy „etykieta
jest" — czyli brak, którego nikt nie szuka. Na produkcji we wrześniu 2026
wygasło 51 zadań, każde zostawiając licznik podniesiony.

Dlatego prostujemy w drugą stronę: zaniżony licznik powoduje ponowny wydruk,
co jest widoczne i tanie.
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
    p = ProductionProduct(
        order_id=order.id,
        configuration_id=cfg.id,
        short_product_id=short,
        product_sequence_in_order=1,
        original_product_name='Blat dębowy',
        current_status='czeka_na_pakowanie',
        quantity=ilosc,
        label_print_count=licznik,
    )
    db.session.add(p)
    db.session.commit()
    return p


def test_cofa_licznik_o_liczbe_nieudanych_etykiet(app):
    with app.app_context():
        p = _pozycja(licznik=4)

        # Jedno zadanie = jedna etykieta, więc dwa nieudane to dwie sztuki.
        rollback_label_count_for_jobs([
            SimpleNamespace(product_id=p.id),
            SimpleNamespace(product_id=p.id),
        ])
        db.session.commit()

        assert p.label_print_count == 2


def test_nie_schodzi_ponizej_zera(app):
    """
    Zadania sprzed poprawki mogą się wygaszać jeszcze po jej wdrożeniu,
    a licznik mógł być w międzyczasie wyzerowany z panelu. Ujemna liczba
    wydrukowanych etykiet nie znaczy nic i wywróciłaby kafelki.
    """
    with app.app_context():
        p = _pozycja(licznik=1)

        rollback_label_count_for_jobs([
            SimpleNamespace(product_id=p.id),
            SimpleNamespace(product_id=p.id),
            SimpleNamespace(product_id=p.id),
        ])
        db.session.commit()

        assert p.label_print_count == 0


def test_zadania_bez_product_id_sa_pomijane(app):
    """
    Zadania sprzed migracji 2026-09-18 nie wiedzą, której pozycji dotyczyły —
    short_product_id dzielą oryginał i doróbka. Zgadywanie cofnęłoby licznik
    losowemu z dwóch wierszy, więc lepiej nie ruszać żadnego.
    """
    with app.app_context():
        p = _pozycja(licznik=3)

        dotkniete = rollback_label_count_for_jobs([
            SimpleNamespace(product_id=None),
            SimpleNamespace(product_id=None),
        ])
        db.session.commit()

        assert dotkniete == 0
        assert p.label_print_count == 3


def test_rozdziela_ubytek_miedzy_pozycje(app):
    """Jedno zadanie ACK potrafi nieść porażki kilku pozycji naraz."""
    with app.app_context():
        a = _pozycja(licznik=5, short='900_1')
        b = _pozycja(licznik=2, short='901_1')

        rollback_label_count_for_jobs([
            SimpleNamespace(product_id=a.id),
            SimpleNamespace(product_id=a.id),
            SimpleNamespace(product_id=b.id),
        ])
        db.session.commit()

        assert a.label_print_count == 3
        assert b.label_print_count == 1
