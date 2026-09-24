# -*- coding: utf-8 -*-
from datetime import datetime, timedelta

import pytest

from extensions import db
from modules.production.logistics import sposoby as s
from modules.production.logistics.services import bl_sync, dzierzawa
from modules.production.models import ProductionOrder
from tests.logistyka_fixtures import app, zamowienie  # noqa: F401


class FakeBase(object):
    """Podstawka pod get_sync_service(): zapisuje wywołania, odpowiada skryptem."""

    def __init__(self, odpowiedzi=None):
        self.api_key = 'token'
        self.wywolania = []
        self.odpowiedzi = list(odpowiedzi or [])

    def _make_api_request(self, dane):
        import json
        self.wywolania.append((dane['method'], json.loads(dane['parameters'])))
        if self.odpowiedzi:
            return self.odpowiedzi.pop(0)
        return {'status': 'SUCCESS'}


@pytest.fixture()
def base(monkeypatch):
    fake = FakeBase()
    import modules.production.services.sync_service as ss
    monkeypatch.setattr(ss, 'get_sync_service', lambda: fake)
    return fake


def test_wysylka_metody_i_statusu_czysci_znaczniki(app, base):
    with app.app_context():
        order = zamowienie(sposob=s.TRANSPORT, delivery_method='Kurier',
                           bl_delivery_method_pending=True, bl_status_pending_id=417343)
        assert bl_sync.wyslij_zamowienie(order) == 2
        assert base.wywolania == [
            ('setOrderFields', {'order_id': order.baselinker_order_id,
                                'delivery_method': 'Transport WoodPower'}),
            ('setOrderStatus', {'order_id': order.baselinker_order_id, 'status_id': 417343}),
        ]
        assert order.bl_delivery_method_pending is False
        assert order.bl_status_pending_id is None
        assert order.delivery_method == 'Transport WoodPower'


def test_brak_zapytania_gdy_tekst_juz_zgodny(app, base):
    with app.app_context():
        order = zamowienie(sposob=s.KURIER, delivery_method='Kurier',
                           bl_delivery_method_pending=True)
        assert bl_sync.wyslij_zamowienie(order) == 0
        assert base.wywolania == [] and order.bl_delivery_method_pending is False


def test_blad_base_zostawia_znacznik(app, base):
    base.odpowiedzi = [{'status': 'ERROR', 'error_message': 'Invalid order_id'}]
    with app.app_context():
        order = zamowienie(sposob=s.KURIER, bl_delivery_method_pending=True)
        bl_sync.wyslij_zamowienie(order)
        assert order.bl_delivery_method_pending is True


def test_limit_base_wstrzymuje_i_zostawia_znaczniki(app, base):
    """Review Focus 2."""
    base.odpowiedzi = [{'status': 'ERROR', 'error_message':
                        'Query limit exceeded, token blocked until 2099-01-01 15:40:05'}]
    with app.app_context():
        a = zamowienie(sposob=s.KURIER, bl_delivery_method_pending=True)
        b = zamowienie(sposob=s.ODBIOR, bl_delivery_method_pending=True)
        wynik = bl_sync.dopychaj(spij=lambda _: None)
        assert wynik['wstrzymane'] is True
        assert bl_sync.wstrzymane_do() == datetime(2099, 1, 1, 15, 40, 5)
        db.session.expire_all()
        assert ProductionOrder.query.get(a.id).bl_delivery_method_pending is True
        assert ProductionOrder.query.get(b.id).bl_delivery_method_pending is True
        assert len(base.wywolania) == 1  # po limicie nie pytamy dalej


def test_pauza_blokuje_dopychacz(app, base):
    """Review Focus 2."""
    with app.app_context():
        zamowienie(sposob=s.KURIER, bl_delivery_method_pending=True)
        bl_sync.wstrzymaj_do(datetime(2099, 1, 1))
        assert bl_sync.dopychaj(spij=lambda _: None)['wstrzymane'] is True
        assert base.wywolania == []


def test_druga_dzierzawa_jest_odrzucona(app):
    """Review Focus 1: jeden nadawca na cały serwer."""
    with app.app_context():
        teraz = datetime(2026, 9, 25, 12, 0, 0)
        klucz = bl_sync.KLUCZ_DZIERZAWY
        assert dzierzawa.przejmij(klucz, 90, teraz) is not None
        assert dzierzawa.przejmij(klucz, 90, teraz + timedelta(seconds=10)) is None
        # Po wygaśnięciu dzierżawy (proces padł) ktoś inny może ją przejąć.
        assert dzierzawa.przejmij(klucz, 90, teraz + timedelta(seconds=91)) is not None


def test_dzierzawy_o_roznych_kluczach_sa_niezalezne(app):
    with app.app_context():
        teraz = datetime(2026, 9, 25, 12, 0, 0)
        assert dzierzawa.przejmij('logistyka_bl_dzierzawa', 90, teraz)
        assert dzierzawa.przejmij('logistyka_geo_dzierzawa', 90, teraz)


def test_dopychacz_ma_odstep_i_zwalnia_dzierzawe(app, base):
    przerwy = []
    with app.app_context():
        for _ in range(3):
            zamowienie(sposob=s.TRANSPORT, bl_delivery_method_pending=True)
        wynik = bl_sync.dopychaj(spij=przerwy.append)
        assert wynik['zapytania'] == 3
        assert przerwy == [bl_sync.ODSTEP_S] * 3
        assert dzierzawa.przejmij(bl_sync.KLUCZ_DZIERZAWY, 90) is not None  # zwolniona


def test_limit_zapytan_przebiegu(app, base):
    with app.app_context():
        for _ in range(5):
            zamowienie(sposob=s.TRANSPORT, bl_delivery_method_pending=True)
        assert bl_sync.dopychaj(limit_zapytan=2, spij=lambda _: None)['zapytania'] == 2


def test_nieudane_zamowienie_nie_mieli_sie_w_kolko(app, base):
    base.odpowiedzi = [{'status': 'ERROR', 'error_message': 'x'}] * 10
    with app.app_context():
        zamowienie(sposob=s.TRANSPORT, bl_delivery_method_pending=True)
        wynik = bl_sync.dopychaj(spij=lambda _: None)
        assert wynik['zapytania'] == 1


def test_zamowienie_bez_id_base_czysci_znaczniki_bez_zapytania(app, base):
    with app.app_context():
        order = zamowienie(sposob=s.KURIER, bl_delivery_method_pending=True)
        order.baselinker_order_id = 0
        assert bl_sync.wyslij_zamowienie(order) == 0
        assert order.bl_delivery_method_pending is False and base.wywolania == []


def test_po_zmianie_uruchamia_dopychacz_w_tle_bez_zapytan_w_zadaniu(app, base, monkeypatch):
    """Timeout gunicorna 30 s: żądanie HTTP nigdy nie czeka na Base."""
    uruchomione = []
    monkeypatch.setattr(bl_sync, 'uruchom_w_tle', lambda app_: uruchomione.append(1))
    with app.app_context():
        order = zamowienie(sposob=s.TRANSPORT, bl_delivery_method_pending=True)
        bl_sync.po_zmianie([order.id])
        assert base.wywolania == [] and uruchomione == [1]


def test_po_zmianie_bez_zamowien_nic_nie_robi(app, monkeypatch):
    uruchomione = []
    monkeypatch.setattr(bl_sync, 'uruchom_w_tle', lambda app_: uruchomione.append(1))
    with app.app_context():
        bl_sync.po_zmianie([])
        assert uruchomione == []


def test_furtka_kierowcy_ustawia_znaczniki():
    from types import SimpleNamespace as NS
    order = NS(bl_status_pending_id=None)
    bl_sync.oznacz_wyslane(order)
    assert order.bl_status_pending_id == 149763
    bl_sync.oznacz_dostarczone(order)
    assert order.bl_status_pending_id == 149778
