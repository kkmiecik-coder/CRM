# -*- coding: utf-8 -*-
"""
Doróbka na zamówieniu z trasy załadowanej albo w drodze (decyzja Konrada 2.10, A2 fali końcowej kroku 4.4b).

Doróbki nie da się odmówić (stanowisko zgłasza wadę fizycznie), więc zamówienie schodzi z trasy jak przy
„Niedostarczone”: pozycje idą do produkcji jak dotąd (reguła unieważniania etapów), przystanek zdjęty
(`routes.usun_przystanek` z logiem), znaczniki załadunku wyczyszczone, Base. 417343 „Planowana trasa”, log
`niedostarczone` z powodem `dorobka`. Na trasie roboczej i zatwierdzonej — jak dotąd (reguła unieważniania, przystanek
zostaje). Kolejność blokad: doróbka bierze NAJPIERW blokadę tras (`routes.zablokuj_trasy`), potem zamówienie i jego
pozycje (tests/blokady_pomocnicze.py — SQLite pomija FOR UPDATE, pilnujemy kolejności zapytań).
"""
import pytest

from extensions import db
from modules.production.logistics.models import LogisticsLog, Route, RouteStop
from modules.production.logistics.services import bl_sync
from modules.production.models import ProductionDevice, ProductionPackage, ProductionProduct
from modules.production.services import rework_service
from tests.blokady_pomocnicze import (
    Zapytania, blokada_pozycji, blokada_zamowien, indeks_blokady_tras, odczyt_przystankow, zapis)
from tests.dostawa_pomocnicze import T0, naglowki, trasa, zaladuj_wprost, zamowienie_z_paczkami
from tests.logistyka_fixtures import app, client  # noqa: F401

STATUS_PLANOWANA_TRASA = 417343


def _odrzuc(pozycja_id, stanowisko='packaging', **kwargs):
    return rework_service.reject_product_quantity(product_id=pozycja_id, quantity=1, reason_category='inne',
                                                  rejected_at_station=stanowisko, **kwargs)


def _w_pakowaniu(order):
    return next(p for p in order.products if p.current_status == 'czeka_na_pakowanie')


def _na_trasie(status_trasy, statusy=('zaladowane', 'czeka_na_pakowanie'), zaladowane=True):
    """
    (zamówienie z pozycją w pakowaniu, jego paczki, trasa, drugie zamówienie trasy). Drugie zamówienie jest
    załadowane i jedzie dalej. Paczki obu na aucie, gdy `zaladowane`.
    """
    order, paczki_a = zamowienie_z_paczkami(statusy=statusy)
    drugie, paczki_b = zamowienie_z_paczkami(statusy=('zaladowane', 'zaladowane'))
    t = trasa([order, drugie], status=status_trasy, nazwa=u'Rzeszów 02.10', loaded_at=T0)
    if zaladowane:
        zaladuj_wprost(paczki_a + paczki_b, t, kto_id=7)
    return order, paczki_a, t, drugie


def _wpisy(order_id):
    return [(w.action, w.new_value, w.note, w.route_id)
            for w in LogisticsLog.query.filter_by(order_id=order_id).order_by(LogisticsLog.id)]


@pytest.mark.parametrize('status_trasy', ['zaladowana', 'w_trasie'])
def test_dorobka_zdejmuje_zamowienie_z_trasy_w_drodze(app, status_trasy):
    order, paczki_a, t, drugie = _na_trasie(status_trasy)
    order_id, drugie_id, route_id = order.id, drugie.id, t.id
    paczki_ids = [p.id for p in paczki_a]

    _odrzuc(_w_pakowaniu(order).id, worker_ids=[7])

    db.session.expire_all()
    trasa_po = db.session.get(Route, route_id)
    assert [s.order_id for s in trasa_po.stops] == [drugie_id]               # przystanek zdjęty
    assert trasa_po.status == status_trasy                                     # reszta trasy jedzie dalej
    pozycje = ProductionProduct.query.filter_by(order_id=order_id).order_by(ProductionProduct.id).all()
    assert [p.current_status for p in pozycje] == ['spakowane', 'czeka_na_pakowanie', 'czeka_na_wyciecie']
    paczki_po = [db.session.get(ProductionPackage, i) for i in paczki_ids]
    assert all(p.loaded_at is None and p.loaded_route_id is None for p in paczki_po)
    zamowienie = pozycje[0].order
    assert zamowienie.bl_status_pending_id == STATUS_PLANOWANA_TRASA
    assert zamowienie.verified_at is None
    wpisy = _wpisy(order_id)
    assert ('trasa_usuniete', None, u'doróbka', route_id) in wpisy
    assert wpisy[-1] == ('niedostarczone', 'dorobka', u'Doróbka — wraca do produkcji', route_id)   # ostatni wpis
    ostatni = LogisticsLog.query.filter_by(order_id=order_id).order_by(LogisticsLog.id.desc()).first()
    assert ostatni.worker_id == 7
    # Drugie zamówienie trasy bez zmian.
    assert [p.current_status for p in ProductionProduct.query.filter_by(order_id=drugie_id)] == ['zaladowane',
                                                                                                  'zaladowane']


def test_dorobka_zamowienia_juz_cofnietego_do_produkcji_wysyla_planowana_trase(app):
    """Stan po zmianie z Base. albo dawnym hurcie (audyt T8, b): zamówienie na trasie załadowanej, pozycje już cofnięte
    do produkcji, paczki unieważnione — przystanek został, a w Base. wisiało „Załadowane”. Doróbka zdejmuje przystanek
    i daje Base. „Planowana trasa”, choć reguła unieważniania nie ma już pracy."""
    order, _paczki, t, drugie = _na_trasie('zaladowana', statusy=('spakowane', 'czeka_na_pakowanie'),
                                           zaladowane=False)
    order.verified_at = None
    order.packages_declared_at = None
    for p in _paczki:
        p.voided_at = T0
    db.session.commit()
    order_id, route_id, drugie_id = order.id, t.id, drugie.id

    _odrzuc(_w_pakowaniu(order).id)

    db.session.expire_all()
    assert [s.order_id for s in db.session.get(Route, route_id).stops] == [drugie_id]
    pozycje = ProductionProduct.query.filter_by(order_id=order_id).order_by(ProductionProduct.id).all()
    assert pozycje[0].order.bl_status_pending_id == STATUS_PLANOWANA_TRASA
    assert _wpisy(order_id)[-1][:2] == ('niedostarczone', 'dorobka')


@pytest.mark.parametrize('status_trasy', ['robocza', 'zatwierdzona'])
def test_dorobka_na_trasie_roboczej_i_zatwierdzonej_jak_dotad(app, status_trasy):
    """Na trasie roboczej i zatwierdzonej bez zmian: reguła unieważniania, przystanek zostaje, bez statusu Base.
    i bez wpisu niedostarczenia."""
    order, _paczki, t, _drugie = _na_trasie(status_trasy, statusy=('zweryfikowane', 'czeka_na_pakowanie'),
                                            zaladowane=False)
    order_id, route_id = order.id, t.id

    _odrzuc(_w_pakowaniu(order).id)

    db.session.expire_all()
    assert order_id in [s.order_id for s in db.session.get(Route, route_id).stops]
    pozycje = ProductionProduct.query.filter_by(order_id=order_id).order_by(ProductionProduct.id).all()
    assert [p.current_status for p in pozycje] == ['spakowane', 'czeka_na_pakowanie', 'czeka_na_wyciecie']
    assert pozycje[0].order.bl_status_pending_id is None
    assert [w[0] for w in _wpisy(order_id)] == ['weryfikacja_cofnieta', 'paczki']


def test_dorobka_nie_zdejmuje_przystanku_juz_dostarczonego(app):
    """Przystanek dostarczony na trasie w drodze (pozycje dostarczone, Base. dołożył potem pozycję): dostarczenie to
    historia — doróbka go nie zdejmuje (spec 4.5: doróbka w zamówieniu z pozycjami dostarczonymi — obsługa ręczna)."""
    order, _paczki, t, _drugie = _na_trasie('w_trasie', statusy=('dostarczone', 'czeka_na_pakowanie'))
    stop = RouteStop.query.filter_by(order_id=order.id).one()
    stop.delivered_at, stop.delivered_by_worker_id = T0, 7
    db.session.commit()
    order_id, route_id = order.id, t.id

    _odrzuc(_w_pakowaniu(order).id)

    db.session.expire_all()
    assert order_id in [s.order_id for s in db.session.get(Route, route_id).stops]
    assert 'niedostarczone' not in [w[0] for w in _wpisy(order_id)]


def test_dorobka_ostatniego_nierozliczonego_przystanku_zamyka_trase(app):
    """Jak „Niedostarczone”: zdjęcie ostatniego nierozliczonego przystanku trasy w drodze zamyka ją (wykonana, bez
    użytkownika — zamknięcie automatyczne)."""
    order, _paczki, t, drugie = _na_trasie('w_trasie')
    stop = RouteStop.query.filter_by(order_id=drugie.id).one()
    stop.delivered_at, stop.delivered_by_worker_id = T0, 7
    for p in drugie.products:
        p.current_status = 'dostarczone'
    db.session.commit()
    route_id, drugie_id = t.id, drugie.id

    _odrzuc(_w_pakowaniu(order).id, worker_ids=[7])

    db.session.expire_all()
    trasa_po = db.session.get(Route, route_id)
    assert (trasa_po.status, trasa_po.completed_by) == ('wykonana', None)
    assert [s.order_id for s in trasa_po.stops] == [drugie_id]
    wpis = LogisticsLog.query.filter_by(order_id=drugie_id, action='trasa_status').one()
    assert (wpis.old_value, wpis.new_value) == ('w_trasie', 'wykonana')


def test_dorobka_blokuje_trasy_przed_zamowieniem_i_pozycjami(app):
    """Kolejność blokad doróbki: blokada tras → zamówienie → wszystkie jego pozycje → pierwszy zapis; przystanek
    czytany odczytem blokującym dopiero pod blokadą tras."""
    order, _paczki, _t, _drugie = _na_trasie('zaladowana')
    order_id, pozycja_id = order.id, _w_pakowaniu(order).id

    with Zapytania() as z:
        _odrzuc(pozycja_id)

    trasy = indeks_blokady_tras(z)
    zamowienia, pozycje, pierwszy_zapis = z.pierwsze(blokada_zamowien), z.pierwsze(blokada_pozycji), z.pierwsze(zapis)
    przystanki = z.pierwsze(odczyt_przystankow)
    assert trasy < zamowienia < pozycje < pierwszy_zapis
    assert trasy < przystanki
    assert list(z.lista[zamowienia][1]) == [order_id]
    # Przed blokadą tras doróbka niczego nie blokuje i niczego nie zapisuje.
    assert not [sql for sql, _p in z.lista[:trasy] if sql.endswith((' FOR UPDATE', ' LOCK IN SHARE MODE'))
                or zapis(sql)]


def test_dorobka_przez_api_uruchamia_dopychacz_base_po_commicie(app, client, monkeypatch):
    """Ścieżka tabletu (POST /api/mobile/orders/<id>/reject): „Planowana trasa” idzie do Base. dopychaczem po commicie."""
    wywolania = []
    monkeypatch.setattr(bl_sync, 'po_zmianie', lambda ids: wywolania.append(sorted(ids)))
    order, _paczki, t, drugie = _na_trasie('w_trasie')
    tablet = ProductionDevice(device_id='TAB-PAKOWANIE-1', device_name='Tablet pakowania', station_code='packaging')
    db.session.add(tablet)
    db.session.commit()
    order_id, pozycja_id, route_id, drugie_id = order.id, _w_pakowaniu(order).id, t.id, drugie.id

    r = client.post('/api/mobile/orders/%d/reject' % pozycja_id, headers=naglowki(tablet),
                    json={'quantity': 1, 'reason_category': 'inne'})

    assert r.status_code == 200, r.get_data()[:300]
    assert wywolania == [[order_id]]
    db.session.expire_all()
    assert [s.order_id for s in db.session.get(Route, route_id).stops] == [drugie_id]
