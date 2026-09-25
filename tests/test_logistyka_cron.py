# -*- coding: utf-8 -*-
from datetime import datetime

import pytest

from extensions import db
from modules.production.logistics import sposoby as s
from modules.production.logistics.services import bl_sync, geocoding
from modules.production.models import ProductionOrder
from tests.logistyka_fixtures import BASE, SEKRET_CRONA, app, client, produkt, zamowienie  # noqa: F401

NAGLOWEK = {'X-Cron-Secret': SEKRET_CRONA}


@pytest.fixture()
def watki(monkeypatch):
    """Etap 2: cron uruchamia też geokoder w tle — bez mocka odpalałby PRAWDZIWY
    wątek na tym samym połączeniu SQLite (StaticPool) co żądanie testowe i gubił
    się z nim o transakcję (wyścig, nie coś do naprawienia w kodzie produkcyjnym)."""
    uruchomione = []
    monkeypatch.setattr(bl_sync, 'uruchom_w_tle', lambda app_: uruchomione.append(1) or True)
    monkeypatch.setattr(geocoding, 'uruchom_w_tle', lambda app_: uruchomione.append(1) or True)
    return uruchomione


def test_cron_bez_sekretu_to_403(client, watki):
    assert client.post(BASE + '/cron').status_code == 403
    assert watki == []


def test_cron_uruchamia_dopychacz_i_odpowiada_od_razu(client, watki):
    r = client.post(BASE + '/cron', headers=NAGLOWEK)
    assert r.status_code == 200
    dane = r.get_json()
    assert dane['dopychacz_uruchomiony'] is True
    assert dane['geokoder_uruchomiony'] is True
    assert watki == [1, 1]  # dopychacz Base. i geokoder — oba uruchomione


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


# ── I2 (przegląd gałęzi): produkty zapisane przez stary kod w oknie wdrożenia ──────
# deploy.sh robi migrate → przeliczenie klientów (do 300 s) → restart; przez ten czas
# stary kod wciąż zapisuje `czeka_na_logistyke`. Po restarcie taki produkt nie ma
# kolejki na tablecie ani filtra na liście — cron przenosi go do pakowania.

class LoggerSzpieg(object):
    def __init__(self):
        self.ostrzezenia = []

    def debug(self, message, **kwargs):
        pass

    info = error = debug

    def warning(self, message, **kwargs):
        self.ostrzezenia.append((message, kwargs))


def test_cron_przenosi_osierocone_z_logistyki_do_pakowania(client, app, watki, monkeypatch):
    from modules.production.logistics.routers import cron_api
    szpieg = LoggerSzpieg()
    monkeypatch.setattr(cron_api, 'logger', szpieg)
    with app.app_context():
        order = zamowienie(sposob=s.KURIER, statusy=('czeka_na_pakowanie', 'czeka_na_logistyke'))
        for p in order.products:
            p.updated_at = datetime(2026, 1, 1)
        db.session.commit()
        order_id = order.id
        osierocony_id = order.products[1].id
        assert order.products[1].current_status == 'czeka_na_logistyke'
        assert order.logistics_completed_at is None
    r = client.post(BASE + '/cron', headers=NAGLOWEK)
    assert r.status_code == 200
    assert r.get_json()['przeniesione_z_logistyki'] == 1
    assert len(szpieg.ostrzezenia) == 1
    with app.app_context():
        order = ProductionOrder.query.get(order_id)
        assert [p.current_status for p in order.products] == ['czeka_na_pakowanie'] * 2
        assert order.logistics_completed_at is not None  # ostatni produkt wszedł do pakowania
        # przeniesiona pozycja ma świeży updated_at — ETag kolejki pakowania na tablecie
        podbite = {p.id for p in order.products if p.updated_at > datetime(2026, 1, 1)}
        assert podbite == {osierocony_id}
    # idempotentnie: drugi przebieg nic nie przenosi i nie ostrzega
    assert client.post(BASE + '/cron', headers=NAGLOWEK).get_json()['przeniesione_z_logistyki'] == 0
    assert len(szpieg.ostrzezenia) == 1


def test_przeniesienie_nie_ustawia_zeszlo_z_produkcji_przedwczesnie(app):
    from modules.production.logistics.services import delivery
    with app.app_context():
        order = zamowienie(statusy=('czeka_na_logistyke', 'czeka_na_lakiernie'))
        assert delivery.przenies_osierocone_z_logistyki() == 1
        db.session.commit()
        assert order.products[0].current_status == 'czeka_na_pakowanie'
        assert order.logistics_completed_at is None


def test_przeniesienie_przelicza_zamkniecie(app):
    """Zamówienie zamknięte (np. kurier) z produktem w `czeka_na_logistyke` otwiera się."""
    from modules.production.logistics.services import delivery
    with app.app_context():
        order = zamowienie(sposob=s.KURIER, statusy=('spakowane', 'czeka_na_logistyke'),
                           logistics_closed_at=datetime(2026, 9, 20))
        assert delivery.przenies_osierocone_z_logistyki() == 1
        db.session.commit()
        assert order.logistics_closed_at is None
