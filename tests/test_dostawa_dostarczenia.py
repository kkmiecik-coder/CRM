# -*- coding: utf-8 -*-
"""Dostarczenia (logistyka etap 4, krok 4.4, spec 9.5, 9.7, 4.5 i 4.6): „Dostarczone”, „Niedostarczone”, cofnięcie
dostarczenia z telefonu i z panelu, automatyczne zamknięcie trasy, odhaczenie z panelu ze statusami Base. i reguła
zamknięcia transportu po „dostarczone”."""
import gc

import pytest

from extensions import db
from modules.production.logistics import sposoby as s
from modules.production.logistics.models import LogisticsLog, Route, RouteStop
from modules.production.logistics.services import bl_sync, delivery, dostawa, routes
from tests.blokady_pomocnicze import Zapytania
from tests.dostawa_pomocnicze import (T0, odsmiecaj_po_blokadach, trasa, zaladuj_wprost, zamowienie_z_paczkami,
                                     zwykle_odczyty_stanu)
from tests.logistyka_fixtures import BASE, app, client, pojazd, zamowienie  # noqa: F401

T1 = T0.replace(hour=9)
T2 = T0.replace(hour=10)


def _blad(funkcja, *args, **kwargs):
    with pytest.raises(dostawa.DostawaBlad) as e:
        funkcja(*args, **kwargs)
    db.session.rollback()
    return e.value


def _zaladowane():
    """(zamówienie z pozycjami załadowanymi, [paczki])."""
    return zamowienie_z_paczkami(statusy=('zaladowane', 'zaladowane'))


def _w_trasie(*zamowienia):
    """Trasa w drodze z zamówieniami (order, paczki) — paczki na aucie."""
    t = trasa([o for o, _ in zamowienia], status='w_trasie', loaded_at=T0, departed_at=T0)
    for _o, lista_paczek in zamowienia:
        zaladuj_wprost(lista_paczek, t, kto_id=7)
    return t


# --- „Dostarczone” --------------------------------------------------------------------------------------

def test_dostarczenie(app):
    a, b = _zaladowane(), _zaladowane()
    t = _w_trasie(a, b)
    order = a[0]
    trasa_po, zmieniono, zamknieta = dostawa.dostarcz(t, order.id, worker_id=7, device_id=3, teraz=T1)
    db.session.commit()
    assert (zmieniono, zamknieta, trasa_po.status) == (True, False, 'w_trasie')
    assert [p.current_status for p in order.products] == ['dostarczone', 'dostarczone']
    stop = RouteStop.query.filter_by(order_id=order.id).one()
    assert (stop.delivered_at, stop.delivered_by_worker_id) == (T1, 7)
    assert order.bl_status_pending_id == 149778 and order.logistics_closed_at == T1
    wpis = LogisticsLog.query.filter_by(order_id=order.id, action='dostarczone').one()
    assert (wpis.old_value, wpis.new_value, wpis.worker_id, wpis.device_id) == ('zaladowane', 'dostarczone', 7, 3)


def test_ostatnie_dostarczenie_zamyka_trase(app):
    a, b = _zaladowane(), _zaladowane()
    t = _w_trasie(a, b)
    dostawa.dostarcz(t, a[0].id, worker_id=7, teraz=T1)
    trasa_po, _zmieniono, zamknieta = dostawa.dostarcz(t, b[0].id, worker_id=7, teraz=T2)
    db.session.commit()
    assert zamknieta is True and trasa_po.status == 'wykonana'
    assert (trasa_po.completed_at, trasa_po.completed_by) == (T2, None)   # zamknął telefon
    for order, _ in (a, b):
        wpis = LogisticsLog.query.filter_by(order_id=order.id, action='trasa_status').one()
        assert (wpis.old_value, wpis.new_value, wpis.worker_id) == ('w_trasie', 'wykonana', 7)


def test_ponowne_dostarczenie_bez_zmian(app):
    """Review Focus 4: powtórka „Dostarczone” — także po zamknięciu trasy tym dostarczeniem — bez zmian, bez drugiego
    statusu Base. i drugiego wpisu w logu."""
    a = _zaladowane()
    t = _w_trasie(a)
    dostawa.dostarcz(t, a[0].id, worker_id=7, teraz=T1)
    db.session.commit()
    a[0].bl_status_pending_id = None   # dopychacz wysłał
    db.session.commit()
    trasa_po, zmieniono, zamknieta = dostawa.dostarcz(t, a[0].id, worker_id=8, teraz=T2)
    assert (zmieniono, zamknieta, trasa_po.status) == (False, False, 'wykonana')
    assert a[0].bl_status_pending_id is None
    assert LogisticsLog.query.filter_by(order_id=a[0].id, action='dostarczone').count() == 1


@pytest.mark.parametrize('statusy', [('zaladowane', 'czeka_na_wyciecie'), ('anulowane', 'anulowane')])
def test_dostarczenie_zamowienia_spoza_zaladunku_409(app, statusy):
    """Review Focus 5: zamówienie wróciło do produkcji (doróbka) albo zostało anulowane w trakcie jazdy —
    „Dostarczone” 409 order_status; przystanek rozlicza się „Niedostarczone”."""
    order, lista_paczek = zamowienie_z_paczkami(statusy=statusy)
    t = _w_trasie((order, lista_paczek))
    e = _blad(dostawa.dostarcz, t, order.id, worker_id=7)
    assert e.kod == 'order_status' and order.internal_order_number in e.komunikat
    assert RouteStop.query.filter_by(order_id=order.id).one().delivered_at is None


def test_dostarczenie_wymaga_trasy_w_drodze(app):
    order, _ = _zaladowane()
    t = trasa([order], status='zaladowana')
    assert _blad(dostawa.dostarcz, t, order.id).kod == 'route_status'
    e = _blad(dostawa.dostarcz, t, 987654)
    assert (e.kod, e.status) == ('stop_not_found', 404)


# --- „Niedostarczone” ------------------------------------------------------------------------------------

def test_niedostarczenie_wraca_zamowienie_do_puli(app):
    a, b = _zaladowane(), _zaladowane()
    t = _w_trasie(a, b)
    order, lista_paczek = a
    trasa_po, zamknieta = dostawa.nie_dostarcz(t, order.id, 'brak_klienta', u' nikt  nie otworzył ', worker_id=7,
                                               device_id=3, teraz=T1)
    db.session.commit()
    assert zamknieta is False and [st.order_id for st in trasa_po.stops] == [b[0].id]
    assert [p.current_status for p in order.products] == ['zweryfikowane', 'zweryfikowane']
    assert all(p.loaded_at is None and p.loaded_route_id is None for p in lista_paczek)
    assert order.bl_status_pending_id == 417343 and order.logistics_closed_at is None
    wpis = LogisticsLog.query.filter_by(order_id=order.id, action='niedostarczone').one()
    assert (wpis.new_value, wpis.note, wpis.worker_id) == ('brak_klienta', u'Brak klienta: nikt nie otworzył', 7)
    usuniete = LogisticsLog.query.filter_by(order_id=order.id, action='trasa_usuniete').one()
    assert (usuniete.note, usuniete.worker_id, usuniete.device_id) == ('niedostarczone', 7, 3)
    assert routes.przystanek_zamowienia(order.id) is None


def test_rozliczenie_ostatniego_przystanku_niedostarczeniem_zamyka_trase(app):
    a, b = _zaladowane(), _zaladowane()
    t = _w_trasie(a, b)
    dostawa.dostarcz(t, a[0].id, worker_id=7, teraz=T1)
    trasa_po, zamknieta = dostawa.nie_dostarcz(t, b[0].id, 'odmowa', worker_id=7, teraz=T2)
    db.session.commit()
    assert zamknieta is True and trasa_po.status == 'wykonana'
    assert [st.order_id for st in trasa_po.stops] == [a[0].id]


def test_niedostarczenie_odmowy(app):
    a, b = _zaladowane(), _zaladowane()
    t = _w_trasie(a, b)
    e = _blad(dostawa.nie_dostarcz, t, a[0].id, 'zgubione')
    assert (e.kod, e.status) == ('invalid_reason', 422)
    dostawa.dostarcz(t, a[0].id, worker_id=7)
    db.session.commit()
    assert _blad(dostawa.nie_dostarcz, t, a[0].id, 'inne').kod == 'stop_delivered'
    stoi, _ = _zaladowane()
    zaladowana = trasa([stoi], status='zaladowana')
    assert _blad(dostawa.nie_dostarcz, zaladowana, stoi.id, 'inne').kod == 'route_status'


# --- „Cofnij dostarczenie” ---------------------------------------------------------------------------------

def test_telefon_cofa_tylko_ostatnie_dostarczenie(app):
    a, b, c = _zaladowane(), _zaladowane(), _zaladowane()
    t = _w_trasie(a, b, c)
    dostawa.dostarcz(t, a[0].id, worker_id=7, teraz=T1)
    dostawa.dostarcz(t, b[0].id, worker_id=7, teraz=T2)
    db.session.commit()
    assert _blad(dostawa.cofnij_dostarczenie, t, a[0].id, z_telefonu=True, worker_id=7).kod == 'not_last_delivery'
    order = b[0]
    trasa_po, zmieniono = dostawa.cofnij_dostarczenie(t, order.id, z_telefonu=True, worker_id=7, device_id=3,
                                                      teraz=T2)
    db.session.commit()
    assert zmieniono is True and trasa_po.status == 'w_trasie'
    assert [p.current_status for p in order.products] == ['zaladowane', 'zaladowane']
    stop = RouteStop.query.filter_by(order_id=order.id).one()
    assert (stop.delivered_at, stop.delivered_by_worker_id) == (None, None)
    assert order.bl_status_pending_id == 149763 and order.logistics_closed_at is None
    wpis = LogisticsLog.query.filter_by(order_id=order.id, action='dostarczenie_cofniete').one()
    assert (wpis.old_value, wpis.new_value, wpis.worker_id) == ('dostarczone', 'zaladowane', 7)
    assert dostawa.cofnij_dostarczenie(t, order.id, z_telefonu=True)[1] is False   # powtórka bez zmian


def test_remis_chwili_dostarczenia_rozstrzyga_kolejnosc_przystankow(app):
    """DATETIME bez ułamków sekundy: dwa dostarczenia w tej samej sekundzie — ostatni jest dalszy przystanek."""
    a, b, c = _zaladowane(), _zaladowane(), _zaladowane()
    t = _w_trasie(a, b, c)
    dostawa.dostarcz(t, b[0].id, worker_id=7, teraz=T1)
    dostawa.dostarcz(t, a[0].id, worker_id=7, teraz=T1)
    db.session.commit()
    assert _blad(dostawa.cofnij_dostarczenie, t, a[0].id, z_telefonu=True).kod == 'not_last_delivery'
    assert dostawa.cofnij_dostarczenie(t, b[0].id, z_telefonu=True)[1] is True


def test_telefon_cofa_ostatnie_dostarczenie_takze_po_zamknieciu_trasy(app):
    """Review Focus 1, decyzja Konrada 3: ostatnie „Dostarczone” zamknęło trasę, a kierowca pomylił przystanek —
    telefon cofa je, trasa wraca do „w trasie”."""
    a = _zaladowane()
    t = _w_trasie(a)
    dostawa.dostarcz(t, a[0].id, worker_id=7, teraz=T1)
    db.session.commit()
    assert t.status == 'wykonana'
    trasa_po, zmieniono = dostawa.cofnij_dostarczenie(t, a[0].id, z_telefonu=True, worker_id=7, teraz=T2)
    db.session.commit()
    assert zmieniono is True
    assert (trasa_po.status, trasa_po.completed_at, trasa_po.completed_by) == ('w_trasie', None, None)
    assert a[0].logistics_closed_at is None
    assert [w.new_value for w in LogisticsLog.query.filter_by(order_id=a[0].id, action='trasa_status')
            .order_by(LogisticsLog.id)] == ['wykonana', 'w_trasie']


def test_telefon_nie_cofa_po_odhaczeniu_w_panelu(app):
    """Review Focus 1: trasę odhaczoną w panelu (completed_by = użytkownik) cofa tylko panel."""
    a = _zaladowane()
    t = _w_trasie(a)
    dostawa.odhacz(t, [a[0].id], user_id=1, teraz=T1)
    db.session.commit()
    e = _blad(dostawa.cofnij_dostarczenie, t, a[0].id, z_telefonu=True, worker_id=7)
    assert e.kod == 'route_status' and u'panelu' in e.komunikat
    assert dostawa.cofnij_dostarczenie(t, a[0].id, user_id=1)[1] is True


def test_panel_cofa_dowolne_dostarczenie_bez_sprawdzania_zajetosci(app):
    """Cofnięcie dostarczenia to korekta, nie planowanie — zajęty w tych dniach pojazd go nie blokuje
    (dawne „Przywróć trasę” sprawdzało zajętość)."""
    v = pojazd()
    a, b = _zaladowane(), _zaladowane()
    t = _w_trasie(a, b)
    t.vehicle_id = v.id
    db.session.commit()
    dostawa.dostarcz(t, a[0].id, worker_id=7, teraz=T1)
    dostawa.dostarcz(t, b[0].id, worker_id=7, teraz=T2)
    db.session.commit()
    trasa([], status='zatwierdzona', vehicle_id=v.id)   # ten sam pojazd, ten sam dzień
    trasa_po, zmieniono = dostawa.cofnij_dostarczenie(t, a[0].id, user_id=1, teraz=T2)   # nie ostatnie
    db.session.commit()
    assert zmieniono is True and trasa_po.status == 'w_trasie'
    wpis = LogisticsLog.query.filter_by(order_id=a[0].id, action='dostarczenie_cofniete').one()
    assert (wpis.user_id, wpis.worker_id) == (1, None)


# --- „Odhacz jako wykonaną” ------------------------------------------------------------------------------

def test_odhaczenie_trasy_w_drodze_ze_statusami_base(app):
    """Spec 9.7: zaznaczone → jak „Dostarczone” (149778), odznaczone → jak „Niedostarczone” z powodem
    odhaczone_w_panelu (417343, bo było załadowane); przystanek dostarczony z telefonu zostaje dostarczony."""
    a, b, c = _zaladowane(), _zaladowane(), _zaladowane()
    t = _w_trasie(a, b, c)
    dostawa.dostarcz(t, a[0].id, worker_id=7, teraz=T0)
    db.session.commit()
    wynik = dostawa.odhacz(t, [b[0].id], user_id=1, teraz=T1)
    db.session.commit()
    assert wynik == {'dostarczone': [a[0].id, b[0].id], 'niedostarczone': [c[0].id]}
    assert (t.status, t.completed_at, t.completed_by) == ('wykonana', T1, 1)
    assert [p.current_status for p in b[0].products] == ['dostarczone', 'dostarczone']
    assert b[0].bl_status_pending_id == 149778 and b[0].logistics_closed_at == T1
    assert RouteStop.query.filter_by(order_id=b[0].id).one().delivered_at == T1
    assert RouteStop.query.filter_by(order_id=a[0].id).one().delivered_at == T0          # bez zmian
    assert [p.current_status for p in c[0].products] == ['zweryfikowane', 'zweryfikowane']
    assert c[0].bl_status_pending_id == 417343 and all(p.loaded_at is None for p in c[1])
    wpis = LogisticsLog.query.filter_by(order_id=c[0].id, action='niedostarczone').one()
    assert (wpis.new_value, wpis.note, wpis.user_id) == ('odhaczone_w_panelu', u'Odhaczone w panelu', 1)


def test_odhaczenie_trasy_zatwierdzonej_bez_zaladunku(app):
    """Praca bez telefonu (jak w etapie 3): spakowane prosto na „dostarczone”; odznaczone wraca do puli bez 417343
    (nie było załadowane, a 417343 ma od spakowania)."""
    a = zamowienie_z_paczkami(statusy=('spakowane',), zweryfikowane=False)
    b = zamowienie_z_paczkami(statusy=('spakowane',), zweryfikowane=False)
    t = trasa([a[0], b[0]])
    dostawa.odhacz(t, [a[0].id], user_id=1, teraz=T1)
    db.session.commit()
    assert [p.current_status for p in a[0].products] == ['dostarczone']
    assert a[0].bl_status_pending_id == 149778 and a[0].logistics_closed_at == T1
    wpis = LogisticsLog.query.filter_by(order_id=a[0].id, action='dostarczone').one()
    assert (wpis.old_value, wpis.user_id) == ('spakowane', 1)
    assert [p.current_status for p in b[0].products] == ['spakowane'] and b[0].bl_status_pending_id is None


# --- Reguła transportu ------------------------------------------------------------------------------------

@pytest.mark.parametrize('statusy, zamkniete', [
    (('dostarczone', 'dostarczone'), True),
    (('dostarczone', 'anulowane'), True),
    (('dostarczone', 'zaladowane'), False),
    (('zaladowane',), False),
])
def test_regula_transportu_po_dostarczonych(app, statusy, zamkniete):
    """Spec 4.6 (krok 4.4): transport własny zamyka się po „dostarczone” — reguła nie czyta tras."""
    order = zamowienie(sposob=s.TRANSPORT, statusy=statusy)
    trasa([order], status='wykonana')
    assert delivery.zamkniecie_wyliczone(order) is zamkniete


# --- Panel tras (API) ---------------------------------------------------------------------------------------

def test_panel_cofniecie_dostarczenia_przez_api(app, client):
    a, b = _zaladowane(), _zaladowane()
    t = _w_trasie(a, b)
    dostawa.dostarcz(t, a[0].id, worker_id=7, teraz=T1)
    dostawa.dostarcz(t, b[0].id, worker_id=7, teraz=T2)
    db.session.commit()
    rid, oid = t.id, a[0].id
    r = client.post(BASE + '/routes/%d/stops/%d/undo-delivered' % (rid, oid))
    assert r.status_code == 200, r.get_data()[:300]
    assert r.get_json()['route']['status'] == 'w_trasie'
    r = client.post(BASE + '/routes/%d/stops/%d/undo-delivered' % (rid, 987654))
    assert r.status_code == 404 and r.get_json()['success'] is False
    assert client.post(BASE + '/routes/%d/restore' % rid).status_code == 404   # „Przywróć trasę” zniknęło


def test_panel_uruchamia_dopychacz_base_po_odhaczeniu(app, client, monkeypatch):
    """Odhaczenie z panelu wysyła statusy Base. (zmiana względem etapu 3) — dopychacz rusza po commicie."""
    wywolania = []
    monkeypatch.setattr(bl_sync, 'po_zmianie', lambda ids: wywolania.append(sorted(ids)))
    a = _zaladowane()
    t = _w_trasie(a)
    rid, oid = t.id, a[0].id
    r = client.post(BASE + '/routes/%d/complete' % rid, json={'delivered_order_ids': [oid]})
    assert r.status_code == 200, r.get_data()[:300]
    assert wywolania == [[oid]]


# --- Decyzje na zablokowanych obiektach (Ruling P2, przyczyna A kroku 4.4a) ------------------------------
# Obiekty testu odłączone (expunge_all): zablokowane zamówienia przeżyją tylko dzięki referencjom, które trzyma
# zapis Dostawy. Po odśmieceniu pamięci tuż po blokadach i przy każdym wpisie logu żaden zwykły odczyt zamówienia,
# pozycji, paczek ani tras — decyzje i zapisy idą na obiektach z odczytu bieżącego.

def _odlacz_i_odsmiecaj(monkeypatch, route_id):
    db.session.expunge_all()
    gc.collect()
    odsmiecaj_po_blokadach(monkeypatch)
    return db.session.get(Route, route_id)


def test_dostarczenie_decyduje_na_zablokowanych_obiektach(app, monkeypatch):
    """Ostatnie dostarczenie (zamyka trasę: log `trasa_status` przy każdym przystanku)."""
    a, b = _zaladowane(), _zaladowane()
    t = _w_trasie(a, b)
    dostawa.dostarcz(t, b[0].id, worker_id=7, teraz=T0)
    db.session.commit()
    route_id, oid = t.id, a[0].id
    route = _odlacz_i_odsmiecaj(monkeypatch, route_id)
    with Zapytania() as z:
        trasa_po, zmieniono, zamknieta = dostawa.dostarcz(route, oid, worker_id=7, teraz=T1)
        db.session.flush()
    assert zwykle_odczyty_stanu(z) == []
    assert (zmieniono, zamknieta, trasa_po.status) == (True, True, 'wykonana')


def test_niedostarczenie_decyduje_na_zablokowanych_obiektach(app, monkeypatch):
    """Zdjęcie z trasy przez routes.usun_przystanek (`ProductionOrder.query.get` ma trafić w mapę tożsamości)
    i zamknięcie trasy po rozliczeniu ostatniego przystanku."""
    a, b = _zaladowane(), _zaladowane()
    t = _w_trasie(a, b)
    dostawa.dostarcz(t, b[0].id, worker_id=7, teraz=T0)
    db.session.commit()
    route_id, oid, zostaje_id = t.id, a[0].id, b[0].id
    route = _odlacz_i_odsmiecaj(monkeypatch, route_id)
    with Zapytania() as z:
        trasa_po, zamknieta = dostawa.nie_dostarcz(route, oid, 'brak_klienta', worker_id=7, teraz=T1)
        db.session.flush()
    assert zwykle_odczyty_stanu(z) == []
    assert zamknieta is True and [st.order_id for st in trasa_po.stops] == [zostaje_id]


def test_odhaczenie_decyduje_na_zablokowanych_obiektach(app, monkeypatch):
    """Odhaczenie: przystanek dostarczony z telefonu, zaznaczony, odznaczony (zdjęcie z trasy) i zamówienie
    anulowane w całości."""
    a, b, c = _zaladowane(), _zaladowane(), _zaladowane()
    d = zamowienie_z_paczkami(statusy=('anulowane',))
    t = _w_trasie(a, b, c, d)
    dostawa.dostarcz(t, a[0].id, worker_id=7, teraz=T0)
    db.session.commit()
    route_id, ids = t.id, [a[0].id, b[0].id, c[0].id, d[0].id]
    route = _odlacz_i_odsmiecaj(monkeypatch, route_id)
    with Zapytania() as z:
        wynik = dostawa.odhacz(route, [ids[1], ids[3]], user_id=1, teraz=T1)
        db.session.flush()
    assert zwykle_odczyty_stanu(z) == []
    assert wynik == {'dostarczone': [ids[0], ids[1], ids[3]], 'niedostarczone': [ids[2]]}
