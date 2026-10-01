# -*- coding: utf-8 -*-
"""
„Zamówienie najpierw” (logistyka etap 4, krok 4.4a): ZAKOŃCZ i wejście do pakowania na tablecie oraz cron
osieroconych blokują wiersz zamówienia przed pozycjami i decydują na odczycie bieżącym.

SQLite nie ma blokad wierszy ani migawki MySQL. Kolejność blokad sprawdzamy na kolejności zapytań
(tests/blokady_pomocnicze.py), a odczyt bieżący — obiektami zostawionymi w sesji w starym stanie, podczas gdy
w bazie leży już cudzy zapis (surowy UPDATE poza ORM). Stan „migawki” wstrzykujemy przelotką na
mobile_api._resolve_workers: to ostatni krok handlera przed odczytem pozycji, już po commicie
require_device_token (commit wygasza obiekty sesji, więc wcześniej wczytany stan by nie przetrwał).
"""
import itertools

import pytest

from extensions import db
from modules.production.logistics import sposoby as s
from modules.production.logistics.services import delivery
from modules.production.models import ProductionDevice, ProductionOrder, ProductionProduct
from modules.production.routers import mobile_api
from modules.production.services import blokady_zamowien
from modules.production.services.mobile_api_service import generate_token
from tests.blokady_pomocnicze import Zapytania, blokada_pozycji, blokada_zamowien, zapis
from tests.logistyka_fixtures import app, client, zamowienie  # noqa: F401

_licznik = itertools.count(1)
_ZAMOWIENIA = ProductionOrder.__table__
_POZYCJE = ProductionProduct.__table__


@pytest.fixture(autouse=True)
def bez_statusow_base(monkeypatch):
    """Spakowanie i wyjście z produkcji planują status Base. po commicie — w testach go nie wysyłamy."""
    monkeypatch.setattr(
        'modules.production.services.baselinker_status_sync.schedule_after_station_complete',
        lambda *a, **k: None)


def _naglowki(stanowisko='packaging'):
    """Nagłówki tabletu danego stanowiska. Wołać PRZED przygotowaniem migawki: commit wygasza sesję."""
    device = ProductionDevice(device_id='TAB-BLK-%d' % next(_licznik), device_name='Tablet',
                              station_code=stanowisko)
    db.session.add(device)
    db.session.commit()
    return {'Authorization': 'Bearer ' + generate_token(device),
            'X-Operation-Id': 'op-blk-%d' % next(_licznik)}


def _zakoncz(client, pozycja_id, naglowki, stanowisko='packaging'):
    return client.post('/api/mobile/orders/%d/complete' % pozycja_id, headers=naglowki,
                       json={'station_code': stanowisko})


def _migawka_przed_zapisem(monkeypatch, order_id, zamowienie_w_bazie=None, pozycje_w_bazie=None):
    """
    Przelotka na mobile_api._resolve_workers: po prawdziwym wywołaniu wczytuje zamówienie i jego pozycje do sesji
    („migawka” żądania), a potem surowym UPDATE zapisuje w bazie cudzą zmianę (`zamowienie_w_bazie` — kolumny
    zamówienia, `pozycje_w_bazie` — {id pozycji: status}). Obiekty w sesji zostają stare: zmianę zobaczy tylko
    odczyt bieżący (populate_existing).
    """
    oryginal = mobile_api._resolve_workers

    def przelotka():
        wynik = oryginal()
        order = db.session.get(ProductionOrder, order_id)
        stare = (order.override_delivery_method, [p.current_status for p in order.products])
        if zamowienie_w_bazie:
            db.session.execute(_ZAMOWIENIA.update().where(_ZAMOWIENIA.c.id == order_id)
                               .values(**zamowienie_w_bazie))
        for pid, status in (pozycje_w_bazie or {}).items():
            db.session.execute(_POZYCJE.update().where(_POZYCJE.c.id == pid).values(current_status=status))
        assert (order.override_delivery_method, [p.current_status for p in order.products]) == stare
        return wynik

    monkeypatch.setattr(mobile_api, '_resolve_workers', przelotka)


def _po_zadaniu(order_id):
    db.session.expire_all()
    return db.session.get(ProductionOrder, order_id)


# --- Moduł blokad ---------------------------------------------------------------------------------------

def test_zablokuj_zamowienia_rosnaco_bez_pustych_i_brakujacych(app):
    a, b = zamowienie(), zamowienie()
    assert blokady_zamowien.zablokuj_zamowienia([]) == []
    assert blokady_zamowien.zablokuj_zamowienia([None]) == []
    wynik = blokady_zamowien.zablokuj_zamowienia([b.id, a.id, b.id, None, 987654])
    assert [o.id for o in wynik] == sorted([a.id, b.id])


def test_zablokuj_zamowienie_pozycji_czyta_biezaco(app):
    """Zamówienie i pozycje w sesji są nieświeże (migawka), a w bazie leży cudzy zapis — po blokadzie obiekty
    mają wartości z bazy."""
    order = zamowienie(sposob=s.KURIER, statusy=('czeka_na_pakowanie', 'czeka_na_pakowanie'))
    pierwsza, druga = order.products
    assert (order.override_delivery_method, pierwsza.current_status) == (s.KURIER, 'czeka_na_pakowanie')
    db.session.execute(_ZAMOWIENIA.update().where(_ZAMOWIENIA.c.id == order.id)
                       .values(override_delivery_method=s.ODBIOR))
    db.session.execute(_POZYCJE.update().where(_POZYCJE.c.id == pierwsza.id).values(current_status='spakowane'))
    assert (order.override_delivery_method, pierwsza.current_status) == (s.KURIER, 'czeka_na_pakowanie')
    assert blokady_zamowien.zablokuj_zamowienie_pozycji(druga.id) is druga
    assert (order.override_delivery_method, pierwsza.current_status) == (s.ODBIOR, 'spakowane')


def test_zablokuj_zamowienie_pozycji_bez_pozycji(app):
    assert blokady_zamowien.zablokuj_zamowienie_pozycji(987654) is None
    assert blokady_zamowien.zablokuj_zamowienie(987654) is None


# --- ZAKOŃCZ i wejście do pakowania ---------------------------------------------------------------------

def test_zakoncz_blokuje_zamowienie_przed_pozycjami_przed_zapisem(app, client):
    order = zamowienie(sposob=s.KURIER, statusy=('spakowane', 'czeka_na_pakowanie'))
    order_id = order.id
    pozycje = sorted(p.id for p in order.products)
    naglowki = _naglowki()
    with Zapytania() as z:
        r = _zakoncz(client, pozycje[1], naglowki)
    assert r.status_code == 200, r.get_data()[:300]
    zamowienia, blokada, pierwszy_zapis = z.pierwsze(blokada_zamowien), z.pierwsze(blokada_pozycji), z.pierwsze(zapis)
    assert zamowienia < blokada < pierwszy_zapis
    assert list(z.lista[zamowienia][1]) == [order_id]
    assert sorted(z.lista[blokada][1]) == pozycje


def test_ostatnie_zakoncz_decyduje_na_biezacym_sposobie_dostawy(app, client, monkeypatch):
    """Spec 8.7 („Współbieżność”) i 4.6 („Siatka w cronie”): logistyk zmienił w panelu kuriera na odbiór w chwili
    ostatniego ZAKOŃCZ. Na MySQL tablet widział sposób z migawki i zamykał cykl odbioru, którego nikt nie wydał
    (11 z 62 przebiegów). ZAKOŃCZ czyta sposób bieżąco: odbiór czeka na „Wydane klientowi”."""
    order = zamowienie(sposob=s.KURIER, statusy=('spakowane', 'czeka_na_pakowanie'))
    order_id, ostatnia = order.id, order.products[1].id
    naglowki = _naglowki()
    _migawka_przed_zapisem(monkeypatch, order_id, zamowienie_w_bazie={'override_delivery_method': s.ODBIOR})
    r = _zakoncz(client, ostatnia, naglowki)
    assert r.status_code == 200, r.get_data()[:300]
    order = _po_zadaniu(order_id)
    assert order.override_delivery_method == s.ODBIOR
    assert [p.current_status for p in order.products] == ['spakowane', 'spakowane']
    assert order.logistics_closed_at is None


def test_ostatnie_zakoncz_widzi_biezace_statusy_pozostalych_pozycji(app, client, monkeypatch):
    """Dwa tablety kończą ostatnie dwie pozycje zamówienia kurierskiego. Drugi czekał na blokadę zamówienia, a jego
    migawka pokazuje pierwszą pozycję jeszcze w pakowaniu — bez odczytu bieżącego cykl nie zamknąłby się wcale."""
    order = zamowienie(sposob=s.KURIER, statusy=('czeka_na_pakowanie', 'czeka_na_pakowanie'))
    order_id = order.id
    pierwsza, druga = [p.id for p in order.products]
    naglowki = _naglowki()
    _migawka_przed_zapisem(monkeypatch, order_id, pozycje_w_bazie={pierwsza: 'spakowane'})
    r = _zakoncz(client, druga, naglowki)
    assert r.status_code == 200, r.get_data()[:300]
    order = _po_zadaniu(order_id)
    assert [p.current_status for p in order.products] == ['spakowane', 'spakowane']
    assert order.logistics_closed_at is not None


def test_wejscie_do_pakowania_widzi_biezace_statusy_pozostalych_pozycji(app, client, monkeypatch):
    """„Zeszło z produkcji” (logistics_completed_at) zapada przy wejściu OSTATNIEJ pozycji do pakowania — także
    gdy pierwszą przesunął w tej samej chwili inny tablet, a migawka pokazuje ją jeszcze na Krawędziach."""
    order = zamowienie(sposob=s.KURIER, statusy=('czeka_na_krawedzie', 'czeka_na_krawedzie'))
    order_id = order.id
    pierwsza, druga = [p.id for p in order.products]
    naglowki = _naglowki('edges')
    _migawka_przed_zapisem(monkeypatch, order_id, pozycje_w_bazie={pierwsza: 'czeka_na_pakowanie'})
    r = _zakoncz(client, druga, naglowki, stanowisko='edges')
    assert r.status_code == 200, r.get_data()[:300]
    order = _po_zadaniu(order_id)
    assert [p.current_status for p in order.products] == ['czeka_na_pakowanie', 'czeka_na_pakowanie']
    assert order.logistics_completed_at is not None


def test_zakoncz_brak_pozycji_404(app, client):
    r = _zakoncz(client, 987654, _naglowki())
    assert r.status_code == 404 and r.get_json()['error'] == 'order_not_found'


# --- Cron: przeniesienie osieroconych ---------------------------------------------------------------------

def test_cron_osieroconych_blokuje_zamowienia_przed_zapisem_pozycji(app):
    a = zamowienie(sposob=s.KURIER, statusy=('czeka_na_logistyke',))
    b = zamowienie(sposob=s.KURIER, statusy=('spakowane', 'czeka_na_logistyke'))
    ids = sorted([a.id, b.id])
    with Zapytania() as z:
        assert delivery.przenies_osierocone_z_logistyki() == 2
        db.session.flush()
    zamowienia, blokada, pierwszy_zapis = z.pierwsze(blokada_zamowien), z.pierwsze(blokada_pozycji), z.pierwsze(zapis)
    assert zamowienia < blokada < pierwszy_zapis
    assert list(z.lista[zamowienia][1]) == ids
