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
from modules.production.logistics.services import bl_sync, dostawa
from modules.production.logistics.services.delivery import LogistykaBlad
from modules.production.models import ProductionDevice, ProductionPackage, ProductionProduct
from modules.production.services import rework_service
from modules.production.services.sync_service import BaselinkerSyncService
from tests.blokady_pomocnicze import (
    Zapytania, blokada_pozycji, blokada_zamowien, indeks_blokady_tras, odczyt_przystankow, zapis)
from tests.dostawa_pomocnicze import (T0, naglowki, telefon_kierowcy, trasa, zaladuj_wprost,
                                      zamowienie_z_paczkami)
from tests.logistyka_fixtures import BASE, DZIS_TESTOW, app, client  # noqa: F401

API = '/api/mobile/delivery'

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


@pytest.mark.parametrize('status_trasy', ['zaladowana', 'zatwierdzona'])
def test_dorobka_blokuje_trasy_przed_zamowieniem_i_pozycjami(app, status_trasy):
    """Kolejność blokad doróbki: blokada tras → przystanek zamówienia (odczyt blokujący) → zamówienia → pozycje →
    pierwszy zapis. Na trasie załadowanej albo w drodze — blokady Dostawy CAŁEJ trasy (zamówienia rosnąco, Ruling 30:
    zamknięcie trasy po doróbce decyduje na zablokowanych zamówieniach wszystkich przystanków); na trasie zatwierdzonej
    — jak dotąd samo zamówienie doróbki."""
    order, _paczki, _t, drugie = _na_trasie(status_trasy, zaladowane=status_trasy == 'zaladowana')
    order_id, drugie_id, pozycja_id = order.id, drugie.id, _w_pakowaniu(order).id

    with Zapytania() as z:
        _odrzuc(pozycja_id)

    trasy = indeks_blokady_tras(z)
    zamowienia, pozycje, pierwszy_zapis = z.pierwsze(blokada_zamowien), z.pierwsze(blokada_pozycji), z.pierwsze(zapis)
    przystanki = z.pierwsze(odczyt_przystankow)
    assert trasy < przystanki < zamowienia < pozycje < pierwszy_zapis
    oczekiwane = sorted([order_id, drugie_id]) if status_trasy == 'zaladowana' else [order_id]
    assert list(z.lista[zamowienia][1]) == oczekiwane
    # Przed blokadą tras doróbka niczego nie blokuje i niczego nie zapisuje.
    assert not [sql for sql, _p in z.lista[:trasy] if sql.endswith((' FOR UPDATE', ' LOCK IN SHARE MODE'))
                or zapis(sql)]


def test_dorobka_przez_api_uruchamia_dopychacz_base_po_commicie(app, client, monkeypatch):
    """Ścieżka tabletu (POST /api/mobile/orders/<id>/reject): „Planowana trasa” idzie do Base. dopychaczem po
    commicie."""
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


# --- Ruling 30 (runda 2 fali końcowej 4.4b) -------------------------------------------------------------------

def _sam_na_trasie(status_trasy='zaladowana', kierowca=None):
    """(zamówienie z pozycją w pakowaniu — jedyny przystanek trasy, trasa) z paczkami na aucie."""
    order, paczki_a = zamowienie_z_paczkami(statusy=('zaladowane', 'czeka_na_pakowanie'))
    t = trasa([order], status=status_trasy, nazwa=u'Pusta po doróbce', loaded_at=T0,
              kierowca_id=kierowca.id if kierowca is not None else None, od=DZIS_TESTOW)
    zaladuj_wprost(paczki_a, t, kto_id=7)
    return order, t


def test_pusta_trasa_po_dorobce_odmowa_ruszam_i_odhaczenie_w_panelu(app, client):
    """Ruling 30.1: doróbka na jedynym przystanku trasy załadowanej zostawia trasę bez przystanków. „Ruszam” odmawia
    (trasa w drodze bez przystanków nie zamknęłaby się sama), a „Odhacz” w panelu zamyka ją jako wykonaną — bez wpisów
    logu (nie ma zamówień) i bez Base."""
    device, k = telefon_kierowcy()
    order, t = _sam_na_trasie(kierowca=k)
    rid = t.id
    _odrzuc(_w_pakowaniu(order).id)
    db.session.expire_all()
    assert (db.session.get(Route, rid).status, db.session.get(Route, rid).stops) == ('zaladowana', [])

    r = client.post(API + '/routes/%d/depart' % rid, headers=naglowki(device, k))
    assert r.status_code == 409, r.get_data()[:300]
    assert r.get_json() == {'error': 'route_status', 'message': u'Trasa nie ma przystanków — logistyk cofnie '
                                                                u'załadunek albo odhaczy ją w panelu tras.'}
    db.session.expire_all()
    assert db.session.get(Route, rid).status == 'zaladowana'

    r = client.post(BASE + '/routes/%d/complete' % rid, json={'delivered_order_ids': []})
    assert r.status_code == 200, r.get_data()[:300]
    assert r.get_json()['wynik'] == {'dostarczone': [], 'niedostarczone': []}
    db.session.expire_all()
    trasa_po = db.session.get(Route, rid)
    assert trasa_po.status == 'wykonana' and trasa_po.completed_at is not None
    assert LogisticsLog.query.filter_by(route_id=rid, action='trasa_status').count() == 0


def test_pusta_trasa_zaladowana_cofniecie_zaladunku(app, client):
    """Ruling 30.1: druga droga wyjścia z pustej trasy załadowanej — „Cofnij załadunek” (potem „Cofnij zatwierdzenie”
    i usunięcie trasy)."""
    order, t = _sam_na_trasie()
    rid = t.id
    _odrzuc(_w_pakowaniu(order).id)
    r = client.post(BASE + '/routes/%d/unload' % rid)
    assert r.status_code == 200, r.get_data()[:300]
    assert r.get_json()['route']['status'] == 'zatwierdzona'


def test_odhaczenie_pustej_trasy_tylko_zaladowanej_i_w_drodze(app):
    """Ruling 30.1: pustą trasę załadowaną albo w drodze „Odhacz” zamyka (lista dostarczonych pusta, inne id → 422);
    roboczej i zatwierdzonej bez przystanków — jak dotąd 422 (tę logistyk usuwa)."""
    w_drodze = trasa([], status='w_trasie')
    assert dostawa.odhacz(w_drodze, [], user_id=1, teraz=T0) == {'dostarczone': [], 'niedostarczone': []}
    db.session.commit()
    assert (w_drodze.status, w_drodze.completed_at, w_drodze.completed_by) == ('wykonana', T0, 1)
    zaladowana = trasa([], status='zaladowana')
    with pytest.raises(LogistykaBlad) as e:
        dostawa.odhacz(zaladowana, [987654], user_id=1)
    assert e.value.status == 422
    db.session.rollback()
    for status in ('robocza', 'zatwierdzona'):
        with pytest.raises(LogistykaBlad) as e:
            dostawa.odhacz(trasa([], status=status), [], user_id=1)
        assert e.value.status == 422 and u'nie ma przystanków' in e.value.komunikat
        db.session.rollback()


def test_zamkniecie_trasy_po_dorobce_liczy_przystanek_anulowanego_jako_rozliczony(app):
    """Ruling 30.4 (C2 w doróbce): trasa w drodze z przystankiem dostarczonym i przystankiem zamówienia anulowanego
    w całości — doróbka zdejmuje ostatni nierozliczony przystanek i trasa zamyka się, jak po „Niedostarczone”."""
    order, _paczki, t, drugie = _na_trasie('w_trasie')
    anulowane, _p = zamowienie_z_paczkami(statusy=('anulowane', 'anulowane'))
    db.session.add(RouteStop(route_id=t.id, order_id=anulowane.id, position=3))
    stop = RouteStop.query.filter_by(order_id=drugie.id).one()
    stop.delivered_at, stop.delivered_by_worker_id = T0, 7
    for p in drugie.products:
        p.current_status = 'dostarczone'
    db.session.commit()
    route_id = t.id

    _odrzuc(_w_pakowaniu(order).id, worker_ids=[7])

    db.session.expire_all()
    trasa_po = db.session.get(Route, route_id)
    assert trasa_po.status == 'wykonana'
    assert RouteStop.query.filter_by(order_id=anulowane.id).one().delivered_at is None


@pytest.mark.parametrize('zrodlo', ['dorobka', 'zmiana_base'])
def test_spoznione_dostarczone_po_powrocie_do_produkcji_ma_jasny_komunikat(app, monkeypatch, zrodlo):
    """Ruling 30.5: zamówienie zdjęte z trasy w drodze przez doróbkę albo zmianę z Base.; kolejka telefonu dosyła potem
    „Dostarczone” — kod bez zmian (404 stop_not_found), komunikat mówi, co się stało (ostatni wpis logu, odczyt
    bieżący jak C5)."""
    order, _paczki, t, _drugie = _na_trasie('w_trasie')
    order_id, route_id = order.id, t.id
    if zrodlo == 'dorobka':
        _odrzuc(_w_pakowaniu(order).id)
    else:
        wynik = _serwis_z_nowa_pozycja(monkeypatch, order).apply_baselinker_changes(
            order.baselinker_order_id, {'products_to_add': [{'order_product_id': '77'}]})
        assert wynik['success'] is True, wynik
    with pytest.raises(dostawa.DostawaBlad) as e:
        dostawa.dostarcz(db.session.get(Route, route_id), order_id, worker_id=7)
    assert (e.value.kod, e.value.status) == ('stop_not_found', 404)
    assert e.value.komunikat == u'Zamówienie wróciło do produkcji i zostało zdjęte z trasy.'


# --- Zmiana z Base. na zamówieniu z trasy załadowanej albo w drodze (Ruling 30.2) -----------------------------

def _serwis_z_nowa_pozycja(monkeypatch, order):
    """Serwis z Base. podmienionym na odpowiedź z jedną nową pozycją (bez sieci, bez parsera nazw)."""
    serwis = BaselinkerSyncService()

    order_id = order.id

    def nowa_pozycja(dane):
        # Numer wewnętrzny zamówień testowych ma ukośnik („26/00001”), a short_product_id musi być N_S.
        return ProductionProduct(order_id=order_id,
                                 short_product_id='%d_%d' % (order_id, dane['product_sequence_in_order']),
                                 product_sequence_in_order=dane['product_sequence_in_order'],
                                 original_product_name=dane['original_product_name'], quantity=1,
                                 current_status='czeka_na_wyciecie')

    monkeypatch.setattr(serwis, 'get_order_from_baselinker',
                        lambda _id: {'products': [{'order_product_id': '77', 'name': 'Blat', 'quantity': 1}]})
    monkeypatch.setattr(serwis, '_create_production_product_from_data', nowa_pozycja)
    monkeypatch.setattr('modules.production.services.parser_service.ProductNameParser.parse_product_name',
                        lambda self, nazwa: None)
    return serwis


@pytest.mark.parametrize('status_trasy', ['zaladowana', 'w_trasie'])
def test_zmiana_z_base_cofajaca_do_produkcji_zdejmuje_zamowienie_z_trasy(app, monkeypatch, status_trasy):
    """Ruling 30.2: nowa pozycja z Base. (produkcja) na zamówieniu z trasy załadowanej albo w drodze — jak doróbka:
    przystanek zdjęty, znaczniki załadunku czyszczone, Base. 417343, log `niedostarczone` z powodem `zmiana_base`."""
    order, paczki_a = zamowienie_z_paczkami(statusy=('zaladowane', 'zaladowane'))
    drugie, paczki_b = zamowienie_z_paczkami(statusy=('zaladowane', 'zaladowane'))
    t = trasa([order, drugie], status=status_trasy, loaded_at=T0)
    zaladuj_wprost(paczki_a + paczki_b, t, kto_id=7)
    order_id, drugie_id, route_id, paczki_ids = order.id, drugie.id, t.id, [p.id for p in paczki_a]

    wynik = _serwis_z_nowa_pozycja(monkeypatch, order).apply_baselinker_changes(
        order.baselinker_order_id, {'products_to_add': [{'order_product_id': '77'}]})

    assert wynik['success'] is True and wynik['added'] == 1, wynik
    db.session.expire_all()
    trasa_po = db.session.get(Route, route_id)
    assert [s.order_id for s in trasa_po.stops] == [drugie_id] and trasa_po.status == status_trasy
    pozycje = ProductionProduct.query.filter_by(order_id=order_id).order_by(ProductionProduct.id).all()
    assert [p.current_status for p in pozycje] == ['spakowane', 'spakowane', 'czeka_na_wyciecie']
    assert pozycje[0].order.bl_status_pending_id == STATUS_PLANOWANA_TRASA
    assert all(db.session.get(ProductionPackage, i).loaded_route_id is None for i in paczki_ids)
    wpisy = _wpisy(order_id)
    assert ('trasa_usuniete', None, u'zmiana z Base.', route_id) in wpisy
    assert wpisy[-1] == ('niedostarczone', 'zmiana_base', u'Zmiana z Base. — wraca do produkcji', route_id)


def test_zmiana_z_base_bez_powrotu_do_produkcji_zostawia_przystanek(app):
    """Zmiana z Base., która nie cofa zamówienia do produkcji (np. ilość), nie zdejmuje go z trasy w drodze."""
    order, paczki_a = zamowienie_z_paczkami(statusy=('zaladowane', 'zaladowane'))
    t = trasa([order], status='w_trasie', loaded_at=T0)
    zaladuj_wprost(paczki_a, t, kto_id=7)
    pierwsza = order.products[0]
    order_id, route_id = order.id, t.id
    zmiany = {'products_to_update': [{'id': pierwsza.id, 'short_product_id': pierwsza.short_product_id,
                                      'changes': [{'field': 'quantity', 'new_value': 5}]}]}

    wynik = BaselinkerSyncService().apply_baselinker_changes(order.baselinker_order_id, zmiany)

    assert wynik['success'] is True, wynik
    db.session.expire_all()
    assert [s.order_id for s in db.session.get(Route, route_id).stops] == [order_id]
    assert 'niedostarczone' not in [w[0] for w in _wpisy(order_id)]


def test_zmiana_z_base_na_trasie_zatwierdzonej_jak_dotad(app, monkeypatch):
    order, _paczki = zamowienie_z_paczkami(statusy=('zweryfikowane', 'zweryfikowane'))
    t = trasa([order], status='zatwierdzona')
    order_id, route_id = order.id, t.id

    wynik = _serwis_z_nowa_pozycja(monkeypatch, order).apply_baselinker_changes(
        order.baselinker_order_id, {'products_to_add': [{'order_product_id': '77'}]})

    assert wynik['success'] is True, wynik
    db.session.expire_all()
    assert [s.order_id for s in db.session.get(Route, route_id).stops] == [order_id]
    assert db.session.get(ProductionProduct, order.products[0].id).order.bl_status_pending_id is None


def test_zmiana_z_base_blokuje_trasy_przed_zamowieniami_po_wywolaniu_base(app, monkeypatch):
    """Ruling 30.2 — kolejność: wywołanie Base. (HTTP) → COMMIT → blokada tras → przystanek (odczyt blokujący) →
    zamówienia CAŁEJ trasy w drodze rosnąco → pozycje → pierwszy zapis. Między COMMIT-em a blokadą zamówień same
    odczyty blokujące (żaden nie zakłada migawki REPEATABLE READ — zwykłe odczyty pod blokadą widzą stan bieżący)."""
    from sqlalchemy import event
    order, paczki_a = zamowienie_z_paczkami(statusy=('zaladowane', 'zaladowane'))
    drugie, paczki_b = zamowienie_z_paczkami(statusy=('zaladowane',))
    t = trasa([drugie, order], status='zaladowana', loaded_at=T0)
    zaladuj_wprost(paczki_a + paczki_b, t, kto_id=7)
    ids = sorted([order.id, drugie.id])
    serwis = _serwis_z_nowa_pozycja(monkeypatch, order)
    oryginal = serwis.get_order_from_baselinker

    with Zapytania() as z:
        def pobierz(_id):
            z.lista.append(('BASE', None))
            return oryginal(_id)
        serwis.get_order_from_baselinker = pobierz

        def commit(_polaczenie):
            z.lista.append(('COMMIT', None))
        event.listen(db.engine, 'commit', commit)
        try:
            wynik = serwis.apply_baselinker_changes(order.baselinker_order_id,
                                                    {'products_to_add': [{'order_product_id': '77'}]})
        finally:
            event.remove(db.engine, 'commit', commit)

    assert wynik['success'] is True, wynik
    base = z.lista.index(('BASE', None))
    commit = z.lista.index(('COMMIT', None), base)
    trasy = indeks_blokady_tras(z)
    przystanki, zamowienia = z.pierwsze(odczyt_przystankow), z.pierwsze(blokada_zamowien)
    pozycje, pierwszy_zapis = z.pierwsze(blokada_pozycji), z.pierwsze(zapis)
    assert base < commit < trasy < przystanki < zamowienia < pozycje < pierwszy_zapis
    assert list(z.lista[zamowienia][1]) == ids
    po_commicie = [sql for sql, _p in z.lista[commit + 1:zamowienia + 1]]
    assert all(sql.endswith((' FOR UPDATE', ' LOCK IN SHARE MODE')) for sql in po_commicie), po_commicie
