# -*- coding: utf-8 -*-
from datetime import datetime

import pytest

from extensions import db
from modules.production.logistics import sposoby as s
from modules.production.logistics.models import LogisticsLog
from modules.production.logistics.services import delivery as d
from tests.logistyka_fixtures import app, produkt, zamowienie  # noqa: F401

T0 = datetime(2026, 9, 25, 10, 0, 0)
T1 = datetime(2026, 9, 25, 11, 0, 0)


def test_ustawienie_sposobu_zapisuje_kto_kiedy_log_i_znacznik_base(app):
    with app.app_context():
        order = zamowienie(delivery_method='DPD')
        wynik = d.ustaw_sposob_dostawy(order, s.KURIER, user_id=7, teraz=T0)
        db.session.commit()
        assert wynik == {'zmieniono': True, 'przepakowanie': False}
        assert order.override_delivery_method == s.KURIER
        assert order.delivery_method_set_at == T0 and order.delivery_method_set_by == 7
        assert order.bl_delivery_method_pending is True
        assert order.bl_status_pending_id is None  # nic jeszcze nie spakowane
        log = LogisticsLog.query.filter_by(order_id=order.id).one()
        assert (log.action, log.old_value, log.new_value, log.user_id) == (
            'sposob_dostawy', None, s.KURIER, 7)


def test_ten_sam_sposob_to_brak_zmiany(app):
    with app.app_context():
        order = zamowienie(sposob=s.KURIER)
        assert d.ustaw_sposob_dostawy(order, s.KURIER, teraz=T0)['zmieniono'] is False
        assert LogisticsLog.query.count() == 0


def test_bez_zapytania_do_base_gdy_tekst_juz_sie_zgadza(app):
    with app.app_context():
        order = zamowienie(delivery_method='Odbiór osobisty')
        d.ustaw_sposob_dostawy(order, s.ODBIOR, teraz=T0)
        assert order.bl_delivery_method_pending is False


def test_nieznany_sposob_to_422(app):
    with app.app_context():
        order = zamowienie()
        with pytest.raises(d.LogistykaBlad) as e:
            d.ustaw_sposob_dostawy(order, 'DPD')
        assert e.value.status == 422


def test_zmiana_sposobu_podbija_updated_at_wszystkich_pozycji(app):
    with app.app_context():
        order = zamowienie(statusy=('czeka_na_wyciecie', 'czeka_na_pakowanie'))
        for p in order.products:
            p.updated_at = datetime(2026, 1, 1)
        db.session.commit()
        d.ustaw_sposob_dostawy(order, s.TRANSPORT, teraz=T1)
        db.session.commit()
        assert all(p.updated_at == T1 for p in order.products)


def test_zmiana_po_spakowaniu_ustawia_status_base_nowego_sposobu(app):
    with app.app_context():
        order = zamowienie(sposob=s.KURIER, statusy=('spakowane',))
        d.ustaw_sposob_dostawy(order, s.TRANSPORT, teraz=T0)
        assert order.bl_status_pending_id == s.STATUS_PLANOWANA_TRASA
        assert order.products[0].current_status == 'spakowane'  # bez przepakowania


def test_przepakowanie_na_kuriera(app):
    with app.app_context():
        order = zamowienie(sposob=s.TRANSPORT, statusy=('spakowane', 'spakowane'))
        wynik = d.ustaw_sposob_dostawy(order, s.KURIER, user_id=3, teraz=T0)
        db.session.commit()
        assert wynik['przepakowanie'] is True
        assert order.repack_required is True
        for p in order.products:
            assert p.current_status == 'czeka_na_pakowanie'
            assert p.quantity_done_packaging == 0
            assert p.packaging_completed_at is None
        assert order.bl_status_pending_id == s.STATUS_PRODUKCJA_ZAKONCZONA
        assert order.logistics_closed_at is None
        akcje = [l.action for l in LogisticsLog.query.order_by(LogisticsLog.id)]
        assert akcje == ['sposob_dostawy', 'przepakowanie']


def test_spakowanie_po_przepakowaniu_kasuje_zalegly_status_138620(app):
    """Review Focus 3: stary 138620 nie może nadpisać świeżego 138623."""
    with app.app_context():
        order = zamowienie(sposob=s.ODBIOR, statusy=('spakowane',))
        d.ustaw_sposob_dostawy(order, s.KURIER, teraz=T0)
        p = order.products[0]
        p.current_status = 'spakowane'
        d.po_spakowaniu(order, T1)
        assert order.repack_required is False
        assert order.bl_status_pending_id is None
        assert order.logistics_closed_at == T1  # kurier spakowany = koniec cyklu


def test_kurier_na_transport_po_spakowaniu_bez_przepakowania(app):
    with app.app_context():
        order = zamowienie(sposob=s.KURIER, statusy=('spakowane',))
        assert d.ustaw_sposob_dostawy(order, s.ODBIOR, teraz=T0)['przepakowanie'] is False
        assert order.repack_required is False
        assert order.bl_status_pending_id == s.STATUS_CZEKA_NA_ODBIOR
        assert order.logistics_closed_at is None  # odbiór czeka na wydanie


def test_wydanie_klientowi(app):
    with app.app_context():
        order = zamowienie(sposob=s.ODBIOR, statusy=('spakowane',))
        d.wydaj_klientowi(order, user_id=5, teraz=T0)
        assert order.handed_over_at == T0 and order.handed_over_by == 5
        assert order.bl_status_pending_id == s.STATUS_ODEBRANE
        assert order.logistics_closed_at == T0


@pytest.mark.parametrize('sposob, statusy', [
    (s.KURIER, ('spakowane',)),
    (s.ODBIOR, ('czeka_na_pakowanie',)),
])
def test_wydanie_tylko_dla_spakowanego_odbioru(app, sposob, statusy):
    with app.app_context():
        order = zamowienie(sposob=sposob, statusy=statusy)
        with pytest.raises(d.LogistykaBlad):
            d.wydaj_klientowi(order)


def test_po_wydaniu_nie_mozna_zmienic_sposobu(app):
    with app.app_context():
        order = zamowienie(sposob=s.ODBIOR, statusy=('spakowane',))
        d.wydaj_klientowi(order, teraz=T0)
        with pytest.raises(d.LogistykaBlad) as e:
            d.ustaw_sposob_dostawy(order, s.KURIER)
        assert e.value.status == 409


@pytest.mark.parametrize('sposob, statusy, kolumny, zamkniete', [
    (None, ('anulowane',), {}, True),
    (None, ('spakowane',), {}, False),
    (s.KURIER, ('spakowane', 'anulowane'), {}, True),
    (s.KURIER, ('spakowane', 'czeka_na_pakowanie'), {}, False),
    (s.KURIER, ('spakowane',), {'repack_required': True}, False),
    (s.ODBIOR, ('spakowane',), {}, False),
    (s.ODBIOR, ('spakowane',), {'handed_over_at': T0}, True),
    (s.TRANSPORT, ('spakowane',), {}, False),
])
def test_tabela_zamkniecia(app, sposob, statusy, kolumny, zamkniete):
    with app.app_context():
        order = zamowienie(sposob=sposob, statusy=statusy, **kolumny)
        assert d.zamkniecie_wyliczone(order) is zamkniete


def test_przelicz_zamkniecie_otwiera_i_zamyka(app):
    with app.app_context():
        order = zamowienie(sposob=s.KURIER, statusy=('spakowane',))
        assert d.przelicz_zamkniecie(order, T0) is True and order.logistics_closed_at == T0
        assert d.przelicz_zamkniecie(order, T1) is False and order.logistics_closed_at == T0
        produkt(order, status='czeka_na_wyciecie')
        assert d.przelicz_zamkniecie(order, T1) is True and order.logistics_closed_at is None


def test_wejscie_do_pakowania_ustawia_zeszlo_z_produkcji_dopiero_przy_ostatnim(app):
    with app.app_context():
        order = zamowienie(statusy=('czeka_na_pakowanie', 'czeka_na_lakiernie'))
        d.odnotuj_wejscie_do_pakowania(order, T0)
        assert order.logistics_completed_at is None
        order.products[1].current_status = 'czeka_na_pakowanie'
        d.odnotuj_wejscie_do_pakowania(order, T1)
        assert order.logistics_completed_at == T1
