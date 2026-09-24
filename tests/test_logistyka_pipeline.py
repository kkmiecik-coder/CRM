# -*- coding: utf-8 -*-
import pytest

from extensions import db
from modules.production.logistics import sposoby as s
from modules.production.services import baselinker_status_sync as bl
from tests.logistyka_fixtures import app, zamowienie  # noqa: F401


@pytest.mark.parametrize('stanowisko, status, kolumny', [
    ('edges', 'czeka_na_krawedzie', {'parsed_edge_processing': True}),
    ('painting', 'czeka_na_lakiernie', {'parsed_finish_type': 'olejowane'}),
    ('formatting', 'czeka_na_formatowanie', {'parsed_edge_processing': False}),
    ('gluing', 'czeka_na_sklejanie', {'cut_to_size': False}),
])
def test_kazde_wyjscie_z_produkcji_prowadzi_do_pakowania(app, stanowisko, status, kolumny):
    with app.app_context():
        order = zamowienie(statusy=(status,))
        p = order.products[0]
        for k, v in kolumny.items():
            setattr(p, k, v)
        p.complete_task(stanowisko)
        db.session.commit()
        assert p.current_status == 'czeka_na_pakowanie'
        assert order.logistics_completed_at is not None


def test_odbior_osobisty_nie_omija_logistyki_i_nie_dostaje_sposobu(app):
    with app.app_context():
        order = zamowienie(statusy=('czeka_na_krawedzie',), delivery_method='Odbiór osobisty')
        p = order.products[0]
        p.parsed_edge_processing = True
        p.complete_task('edges')
        assert p.current_status == 'czeka_na_pakowanie'
        assert order.override_delivery_method is None


def test_spakowanie_kuriera_zamyka_cykl(app):
    with app.app_context():
        order = zamowienie(sposob=s.KURIER, statusy=('czeka_na_pakowanie',))
        order.products[0].complete_task('packaging')
        assert order.products[0].current_status == 'spakowane'
        assert order.logistics_closed_at is not None


def test_postprod_bez_logistyki():
    assert bl.POSTPROD_STATUSES == frozenset({'czeka_na_pakowanie', 'spakowane'})


@pytest.mark.parametrize('sposob, status', [
    (s.KURIER, 138623), (s.TRANSPORT, 417343), (s.ODBIOR, 149777), (None, 138623),
])
def test_status_base_po_spakowaniu_tylko_z_decyzji_logistyki(app, sposob, status):
    with app.app_context():
        # Heurystyka odbioru z Base. już NIE decyduje — tylko override.
        order = zamowienie(sposob=sposob, delivery_method='Odbiór osobisty')
        assert bl._determine_packaging_target_status(order) == status
