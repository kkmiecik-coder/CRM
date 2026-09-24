# -*- coding: utf-8 -*-
from datetime import datetime

import pytest

from extensions import db
from modules.production.logistics import sposoby as s
from modules.production.logistics.services import bl_sync
from modules.production.models import ProductionOrder
from tests.logistyka_fixtures import BASE, SEKRET_CRONA, app, client, produkt, zamowienie  # noqa: F401

NAGLOWEK = {'X-Cron-Secret': SEKRET_CRONA}


@pytest.fixture()
def watki(monkeypatch):
    uruchomione = []
    monkeypatch.setattr(bl_sync, 'uruchom_w_tle', lambda app_: uruchomione.append(1) or True)
    return uruchomione


def test_cron_bez_sekretu_to_403(client, watki):
    assert client.post(BASE + '/cron').status_code == 403
    assert watki == []


def test_cron_uruchamia_dopychacz_i_odpowiada_od_razu(client, watki):
    r = client.post(BASE + '/cron', headers=NAGLOWEK)
    assert r.status_code == 200
    assert r.get_json()['dopychacz_uruchomiony'] is True
    assert watki == [1]


def test_cron_zwraca_pauze(client, app, watki):
    """Review Focus 2 — pauza jest widoczna w odpowiedzi crona (log crontaba)."""
    with app.app_context():
        bl_sync.wstrzymaj_do(datetime(2099, 1, 1))
    assert client.post(BASE + '/cron', headers=NAGLOWEK).get_json()['base_wstrzymane_do'] \
        == '2099-01-01T00:00:00'


def test_cron_otwiera_zamowienie_z_nowa_aktywna_pozycja(client, app, watki):
    """Review Focus 5: Base. dołożył pozycję do zamkniętego zamówienia kurierskiego."""
    with app.app_context():
        order = zamowienie(sposob=s.KURIER, statusy=('spakowane',),
                           logistics_closed_at=datetime(2026, 9, 20))
        produkt(order, status='czeka_na_wyciecie')
        db.session.commit()
        order_id = order.id
    r = client.post(BASE + '/cron', headers=NAGLOWEK)
    assert r.get_json()['przeliczone'] == 1
    with app.app_context():
        assert ProductionOrder.query.get(order_id).logistics_closed_at is None


def test_cron_blad_zwraca_500_bez_uruchamiania_dopychacza(client, monkeypatch, watki):
    """Błąd w przeliczaniu nie uruchamia dopychacza i zwraca 500 ze strukturą JSON."""
    from modules.production.logistics.services import delivery
    monkeypatch.setattr(delivery, 'przelicz_otwarte', lambda: (_ for _ in ()).throw(RuntimeError('boom')))

    r = client.post(BASE + '/cron', headers=NAGLOWEK)
    assert r.status_code == 500
    j = r.get_json()
    assert j['success'] is False
    assert 'boom' in j['error']
    # dopychacz nie powinien być uruchomiony
    assert watki == []
