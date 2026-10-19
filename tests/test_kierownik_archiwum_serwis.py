# -*- coding: utf-8 -*-
"""
Serwis `archiwum_zamowien` — jedna definicja archiwum dla panelu WWW i tabletu kierownika.

Tablet kierownika hali musi pokazywać „archiwalne” dokładnie tak samo jak zakładka Produkty
(`view=archive`), więc definicja żyje w serwisie, a nie w routerze. Ten test pilnuje, że
serwis i widok WWW wybierają te same zamówienia — gdyby ktoś kiedyś zmienił jedną stronę,
test pęknie.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timedelta

from extensions import db
from modules.production.models import ProductionConfiguration, ProductionOrder
from modules.production.models import ProductionProduct as ProductionItem
from modules.production.services import archiwum_zamowien

# Fixtury `app` i `client` oraz pomocnicy zbioru testowego współdzielone z testami zakładki.
from tests.test_archive_tab import (  # noqa: F401
    _aktywne, _archiwum, _numery, _zamowienie, app, client,
)


def _zbior_mieszany(app):
    """Zamknięte w Logistyce, anulowane w całości, spakowane otwarte i zamknięte z pozycją w produkcji."""
    baza = datetime(2026, 5, 10, 12, 0, 0)
    # Zamknięte w Logistyce — archiwum.
    _zamowienie(app, '26/00001', [{'packaging_completed_at': baza}],
                bl_id=555001, closed_at=baza)
    # W całości anulowane, jeszcze niezamknięte — archiwum.
    _zamowienie(app, '26/00002', [{'status': 'anulowane'}, {'status': 'anulowane'}],
                bl_id=555002, closed_at=None)
    # Spakowane, ale otwarte w Logistyce — aktywne.
    _zamowienie(app, '26/00003', [{'packaging_completed_at': baza}],
                bl_id=555003, closed_at=None)
    # Zamknięte, ale pozycja wróciła do produkcji — aktywne.
    _zamowienie(app, '26/00004', [{'packaging_completed_at': baza},
                                  {'status': 'czeka_na_wyciecie'}],
                bl_id=555004, closed_at=baza)
    # W produkcji — aktywne.
    _zamowienie(app, '26/00005', [{'status': 'czeka_na_wyciecie'}],
                bl_id=555005, closed_at=None)
    # Drugie zamknięte, nowsze — archiwum.
    _zamowienie(app, '26/00006', [{'packaging_completed_at': baza + timedelta(days=2)}],
                bl_id=555006, closed_at=baza + timedelta(days=2))


def test_web_i_serwis_ta_sama_definicja(app, client):
    """`warunek_archiwum()` i `zapytanie_archiwum()` dają te same numery co `view=archive`."""
    _zbior_mieszany(app)

    web = set(_numery(_archiwum(client)))
    assert web == {'26/00001', '26/00002', '26/00006'}

    with app.app_context():
        z_zapytania = {r.ion for r in archiwum_zamowien.zapytanie_archiwum().all()}

        z_warunku = {
            r.ion for r in db.session.query(ProductionOrder.internal_order_number.label('ion'))
            .join(ProductionItem, ProductionItem.order_id == ProductionOrder.id)
            .filter(ProductionOrder.internal_order_number.isnot(None))
            .group_by(ProductionOrder.internal_order_number)
            .having(archiwum_zamowien.warunek_archiwum())
            .all()
        }

    assert z_zapytania == web
    assert z_warunku == web

    # Reszta jest dokładnie dopełnieniem: widok „aktywne” nie pokazuje żadnego archiwalnego.
    aktywne = set(_aktywne(client))
    assert aktywne == {'26/00003', '26/00004', '26/00005'}
    assert aktywne.isdisjoint(web)


def test_statystyki_i_etapy_z_serwisu(app, client):
    """`statystyki_archiwum` liczy po wierszach zapytania, `etapy_zamowien` po pozycjach."""
    _zbior_mieszany(app)

    with app.app_context():
        wiersze = archiwum_zamowien.zapytanie_archiwum().all()
        statystyki = archiwum_zamowien.statystyki_archiwum(wiersze)
        assert statystyki['archive']['orders_count'] == 3

        pozycje = ProductionItem.query.join(ProductionOrder).filter(
            ProductionOrder.internal_order_number.in_(['26/00001', '26/00002'])
        ).all()
        etapy = archiwum_zamowien.etapy_zamowien(pozycje)
        assert set(etapy) == {'26/00001', '26/00002'}
        assert etapy['26/00002'][0] == 'anulowane'


def test_data_zakonczenia_expr_bez_znacznika(app, client):
    """Bez znacznika wdrożenia data „Zakończono” zamknięcia to `logistics_closed_at`."""
    baza = datetime(2026, 5, 10, 12, 0, 0)
    _zamowienie(app, '26/00001', [{'packaging_completed_at': baza - timedelta(days=3)}],
                bl_id=555001, closed_at=baza)
    with app.app_context():
        wiersze = archiwum_zamowien.zapytanie_archiwum(wdrozenie=None).all()
        assert [r.completed_at for r in wiersze] == [baza]
