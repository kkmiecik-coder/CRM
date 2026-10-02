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
    trasa_po, zmieniono, zamknieta = dostawa.nie_dostarcz(t, order.id, 'brak_klienta', u' nikt  nie otworzył ',
                                                          worker_id=7, device_id=3, teraz=T1)
    db.session.commit()
    assert (zmieniono, zamknieta) == (True, False) and [st.order_id for st in trasa_po.stops] == [b[0].id]
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
    trasa_po, zmieniono, zamknieta = dostawa.nie_dostarcz(t, b[0].id, 'odmowa', worker_id=7, teraz=T2)
    db.session.commit()
    assert (zmieniono, zamknieta, trasa_po.status) == (True, True, 'wykonana')
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


def test_powtorka_niedostarczenia_bez_zmian(app):
    """Ruling 26: powtórka „Niedostarczone” (kolejka offline, nowy X-Operation-Id) po udanym zdjęciu przystanku — bez
    zmian zamiast 404 stop_not_found, także gdy to niedostarczenie zamknęło trasę; bez drugiego wpisu w logu."""
    a = _zaladowane()
    t = _w_trasie(a)
    dostawa.nie_dostarcz(t, a[0].id, 'odmowa', worker_id=7, teraz=T1)
    db.session.commit()
    assert t.status == 'wykonana'
    a[0].bl_status_pending_id = None   # dopychacz wysłał
    db.session.commit()
    trasa_po, zmieniono, zamknieta = dostawa.nie_dostarcz(t, a[0].id, 'brak_klienta', worker_id=8, teraz=T2)
    assert (zmieniono, zamknieta, trasa_po.status) == (False, False, 'wykonana')
    assert a[0].bl_status_pending_id is None
    assert LogisticsLog.query.filter_by(order_id=a[0].id, action='niedostarczone').count() == 1
    assert LogisticsLog.query.filter_by(order_id=a[0].id, action='trasa_usuniete').count() == 1


def test_brak_przystanku_bez_niedostarczenia_z_tej_trasy_to_404(app):
    """Ruling 26 — rozpoznanie powtórki jest wąskie: tylko gdy OSTATNI wpis logu zamówienia to niedostarczenie
    z TEJ trasy. Zamówienie spoza trasy, niedostarczone z innej trasy albo po niedostarczeniu dodane do nowej trasy
    — 404 stop_not_found jak dotąd."""
    a, b = _zaladowane(), _zaladowane()
    t = _w_trasie(a)
    druga = _w_trasie(b)
    assert _blad(dostawa.nie_dostarcz, t, b[0].id, 'inne').kod == 'stop_not_found'        # nigdy na tej trasie
    dostawa.nie_dostarcz(t, a[0].id, 'odmowa', worker_id=7, teraz=T1)
    db.session.commit()
    assert _blad(dostawa.nie_dostarcz, druga, a[0].id, 'inne').kod == 'stop_not_found'    # niedostarczone z innej
    nowa = trasa([], status='robocza')
    assert routes.dodaj_przystanki(nowa, [a[0].id])['dodane'] == [a[0].id]
    db.session.commit()
    e = _blad(dostawa.nie_dostarcz, t, a[0].id, 'inne')                                   # ostatni wpis: trasa_dodane
    assert (e.kod, e.status) == ('stop_not_found', 404)


@pytest.mark.parametrize('rozliczenie', ['odznaczenie', 'niedostarczone'])
def test_wycofanie_niezweryfikowanego_wraca_do_spakowanych(app, rozliczenie):
    """Ruling 25 (A): trasa odhaczona bez załadunku z zamówieniem niezweryfikowanym, cofnięte dostarczenie (pozycje
    'zaladowane', trasa w drodze), potem odznaczenie przy odhaczeniu albo „Niedostarczone” — pozycje wracają do
    'spakowane', nie 'zweryfikowane': weryfikacji nie było, a „zweryfikowane” ominęłoby bramkę załadunku. 417343 jak
    dotąd (było „załadowane”)."""
    order, _ = zamowienie_z_paczkami(statusy=('spakowane', 'spakowane'), zweryfikowane=False)
    t = trasa([order])
    dostawa.odhacz(t, [order.id], user_id=1, teraz=T0)
    db.session.commit()
    dostawa.cofnij_dostarczenie(t, order.id, user_id=1, teraz=T1)
    db.session.commit()
    assert [p.current_status for p in order.products] == ['zaladowane', 'zaladowane'] and t.status == 'w_trasie'
    if rozliczenie == 'odznaczenie':
        dostawa.odhacz(t, [], user_id=1, teraz=T2)
    else:
        dostawa.nie_dostarcz(t, order.id, 'odmowa', worker_id=7, teraz=T2)
    db.session.commit()
    assert [p.current_status for p in order.products] == ['spakowane', 'spakowane']
    assert order.verified_at is None and order.bl_status_pending_id == 417343
    assert routes.przystanek_zamowienia(order.id) is None


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


def test_cofniecie_dostarczenia_anulowanego_bez_wpisu_w_logu(app):
    """Przystanek zamówienia anulowanego w całości (odhaczony jako dostarczony, bez statusu Base.): cofnięcie zdejmuje
    znacznik dostarczenia, ale nie zapisuje „dostarczone → zaladowane” — żadna pozycja się nie zmieniła."""
    a = _zaladowane()
    d = zamowienie_z_paczkami(statusy=('anulowane',))
    t = _w_trasie(a, d)
    dostawa.odhacz(t, [a[0].id, d[0].id], user_id=1, teraz=T1)
    db.session.commit()
    trasa_po, zmieniono = dostawa.cofnij_dostarczenie(t, d[0].id, user_id=1, teraz=T2)
    db.session.commit()
    assert zmieniono is True and trasa_po.status == 'w_trasie'
    assert RouteStop.query.filter_by(order_id=d[0].id).one().delivered_at is None
    assert LogisticsLog.query.filter_by(order_id=d[0].id, action='dostarczenie_cofniete').count() == 0
    assert d[0].bl_status_pending_id is None


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


def test_odhaczenie_zamyka_anulowane_w_calosci(app):
    """Zamówienie anulowane w całości, którego anulowanie ominęło przeliczenie (otwarte), zaznaczone przy odhaczeniu:
    przystanek dostarczony bez statusu Base. i zamknięcie od razu — jak dawne routes.wykonaj."""
    a = _zaladowane()
    d = zamowienie_z_paczkami(statusy=('anulowane', 'anulowane'))
    t = _w_trasie(a, d)
    assert d[0].logistics_closed_at is None
    wynik = dostawa.odhacz(t, [a[0].id, d[0].id], user_id=1, teraz=T1)
    db.session.commit()
    assert wynik == {'dostarczone': [a[0].id, d[0].id], 'niedostarczone': []}
    assert d[0].logistics_closed_at == T1 and d[0].bl_status_pending_id is None
    assert RouteStop.query.filter_by(order_id=d[0].id).one().delivered_at == T1


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


def test_panel_ponowne_odhaczenie_wykonanej_409(app, client):
    """Powtórne „Odhacz” trasy już wykonanej (podwójne kliknięcie, druga karta) — 409 bez zmian, jak w etapie 3."""
    a = _zaladowane()
    t = _w_trasie(a)
    rid, oid = t.id, a[0].id
    assert client.post(BASE + '/routes/%d/complete' % rid, json={'delivered_order_ids': [oid]}).status_code == 200
    r = client.post(BASE + '/routes/%d/complete' % rid, json={'delivered_order_ids': [oid]})
    assert r.status_code == 409 and r.get_json()['success'] is False and u'wykonana' in r.get_json()['error']
    assert LogisticsLog.query.filter_by(order_id=oid, action='dostarczone').count() == 1


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
    """(trasa wczytana na nowo, licznik przelotek odśmiecania — test sprawdza, że odśmiecanie naprawdę zaszło)."""
    db.session.expunge_all()
    gc.collect()
    licznik = odsmiecaj_po_blokadach(monkeypatch)
    return db.session.get(Route, route_id), licznik


def test_dostarczenie_decyduje_na_zablokowanych_obiektach(app, monkeypatch):
    """Ostatnie dostarczenie (zamyka trasę: log `trasa_status` przy każdym przystanku)."""
    a, b = _zaladowane(), _zaladowane()
    t = _w_trasie(a, b)
    dostawa.dostarcz(t, b[0].id, worker_id=7, teraz=T0)
    db.session.commit()
    route_id, oid = t.id, a[0].id
    route, licznik = _odlacz_i_odsmiecaj(monkeypatch, route_id)
    with Zapytania() as z:
        trasa_po, zmieniono, zamknieta = dostawa.dostarcz(route, oid, worker_id=7, teraz=T1)
        db.session.flush()
    assert zwykle_odczyty_stanu(z) == [] and licznik['_wymagaj_statusu'] > 0 and licznik['zapisz_log'] > 0
    assert (zmieniono, zamknieta, trasa_po.status) == (True, True, 'wykonana')


def test_niedostarczenie_decyduje_na_zablokowanych_obiektach(app, monkeypatch):
    """Zdjęcie z trasy przez routes.usun_przystanek (`ProductionOrder.query.get` ma trafić w mapę tożsamości)
    i zamknięcie trasy po rozliczeniu ostatniego przystanku."""
    a, b = _zaladowane(), _zaladowane()
    t = _w_trasie(a, b)
    dostawa.dostarcz(t, b[0].id, worker_id=7, teraz=T0)
    db.session.commit()
    route_id, oid, zostaje_id = t.id, a[0].id, b[0].id
    route, licznik = _odlacz_i_odsmiecaj(monkeypatch, route_id)
    with Zapytania() as z:
        trasa_po, _zmieniono, zamknieta = dostawa.nie_dostarcz(route, oid, 'brak_klienta', worker_id=7, teraz=T1)
        db.session.flush()
    assert zwykle_odczyty_stanu(z) == [] and licznik['_wymagaj_statusu'] > 0 and licznik['zapisz_log'] > 0
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
    route, licznik = _odlacz_i_odsmiecaj(monkeypatch, route_id)
    with Zapytania() as z:
        wynik = dostawa.odhacz(route, [ids[1], ids[3]], user_id=1, teraz=T1)
        db.session.flush()
    assert zwykle_odczyty_stanu(z) == [] and licznik['_wymagaj_statusu'] > 0 and licznik['zapisz_log'] > 0
    assert wynik == {'dostarczone': [ids[0], ids[1], ids[3]], 'niedostarczone': [ids[2]]}


def test_cofniecie_dostarczenia_decyduje_na_zablokowanych_obiektach(app, monkeypatch):
    """Telefon cofa ostatnie dostarczenie zaraz po automatycznym zamknięciu trasy (wybór „ostatniego” po przystankach,
    trasa wraca do „w trasie”: log `trasa_status` przy każdym przystanku)."""
    a, b = _zaladowane(), _zaladowane()
    t = _w_trasie(a, b)
    dostawa.dostarcz(t, a[0].id, worker_id=7, teraz=T0)
    dostawa.dostarcz(t, b[0].id, worker_id=7, teraz=T1)
    db.session.commit()
    route_id, oid = t.id, b[0].id
    route, licznik = _odlacz_i_odsmiecaj(monkeypatch, route_id)
    with Zapytania() as z:
        trasa_po, zmieniono = dostawa.cofnij_dostarczenie(route, oid, z_telefonu=True, worker_id=7, teraz=T2)
        db.session.flush()
    assert zwykle_odczyty_stanu(z) == [] and licznik['_wymagaj_statusu'] > 0 and licznik['zapisz_log'] > 0
    assert (zmieniono, trasa_po.status) == (True, 'w_trasie')


# --- Fala końcowa kroku 4.4b (C1–C5) --------------------------------------------------------------------------

def _odczyty_logu(z):
    return [sql for sql, _p in z.lista if sql.startswith('SELECT') and 'FROM prod_logistics_log' in sql]


def test_powtorka_niedostarczenia_rozpoznana_odczytem_biezacym(app):
    """C1 (Ruling 26): ostatni wpis logu zamówienia czytamy odczytem BIEŻĄCYM (LOCK IN SHARE MODE), pod trzymanymi
    blokadami tras i zamówień trasy. Zwykły SELECT na MySQL widziałby migawkę sprzed czekania na blokady — w wyścigu
    z „Odhacz” albo drugim telefonem (albo przy zdublowanym X-Operation-Id) kierowca dostawał 404 zamiast 200 bez
    zmian. SQLite nie ma migawki, więc pilnujemy rodzaju odczytu."""
    a, b = _zaladowane(), _zaladowane()
    t = _w_trasie(a, b)
    dostawa.nie_dostarcz(t, a[0].id, 'odmowa', worker_id=7, teraz=T1)
    db.session.commit()
    with Zapytania() as z:
        _trasa_po, zmieniono, _zamknieta = dostawa.nie_dostarcz(t, a[0].id, 'brak_klienta', worker_id=8, teraz=T2)
    assert zmieniono is False
    odczyty = _odczyty_logu(z)
    assert odczyty and all(sql.endswith(' LOCK IN SHARE MODE') for sql in odczyty), odczyty


def test_przystanek_anulowanego_w_calosci_rozliczony_trasa_zamyka_sie(app):
    """C2: klient anulował zamówienie C w Base. po zakończeniu załadunku. Kierowca dostarcza A i B — liczniki
    pokazują „dostarczono 2/2”, więc trasa zamyka się sama: przystanek zamówienia anulowanego w całości liczy się jako
    rozliczony (nie musi mieć delivered_at)."""
    a, b = _zaladowane(), _zaladowane()
    c = zamowienie_z_paczkami(statusy=('anulowane', 'anulowane'))
    t = _w_trasie(a, b, c)
    dostawa.dostarcz(t, a[0].id, worker_id=7, teraz=T1)
    trasa_po, _zmieniono, zamknieta = dostawa.dostarcz(t, b[0].id, worker_id=7, teraz=T2)
    db.session.commit()
    assert zamknieta is True and (trasa_po.status, trasa_po.completed_at, trasa_po.completed_by) == ('wykonana', T2,
                                                                                                    None)
    assert RouteStop.query.filter_by(order_id=c[0].id).one().delivered_at is None
    # Niedostarczenie ostatniego aktywnego przystanku też zamyka trasę z przystankiem anulowanym.
    d, e = _zaladowane(), zamowienie_z_paczkami(statusy=('anulowane',))
    druga = _w_trasie(d, e)
    trasa_po, _zmieniono, zamknieta = dostawa.nie_dostarcz(druga, d[0].id, 'odmowa', worker_id=7, teraz=T2)
    db.session.commit()
    assert zamknieta is True and trasa_po.status == 'wykonana'


def test_dostarczenie_zdejmuje_flage_zostaje(app):
    """C3: przystanek z „Zostaje” zaznaczony jako dostarczony w „Odhacz” (trasa zatwierdzona w trakcie załadunku) traci
    flagę — inaczej po „Cofnij dostarczenie” trasa w drodze pokazywałaby „Zostaje: <powód>”, którego nie da się już
    zdjąć. Ślad w logu (`zostaje`: powód → brak) jak przy cofnięciu zatwierdzenia."""
    from modules.production.logistics.services import dostawa_widok
    a, b = zamowienie_z_paczkami(), zamowienie_z_paczkami()
    t = trasa([a[0], b[0]])
    stop = RouteStop.query.filter_by(order_id=a[0].id).one()
    stop.stays_reason, stop.stays_note = 'brak_miejsca', u'nie weszło'
    db.session.commit()
    dostawa.odhacz(t, [a[0].id, b[0].id], user_id=1, teraz=T1)
    db.session.commit()
    stop = RouteStop.query.filter_by(order_id=a[0].id).one()
    assert (stop.stays_reason, stop.stays_note) == (None, None)
    wpis = LogisticsLog.query.filter_by(order_id=a[0].id, action='zostaje').one()
    assert (wpis.old_value, wpis.new_value, wpis.note, wpis.user_id) == ('brak_miejsca', None,
                                                                         u'oznaczone jako dostarczone', 1)
    dostawa.cofnij_dostarczenie(t, a[0].id, user_id=1, teraz=T2)
    db.session.commit()
    widok = dostawa_widok.serializuj(*dostawa_widok.wczytaj(t.id))
    assert [s['stays'] for s in widok['stops'] if s['order_id'] == a[0].id] == [None]
    # Przystanek bez „Zostaje” — bez wpisu.
    assert LogisticsLog.query.filter_by(order_id=b[0].id, action='zostaje').count() == 0


def test_telefon_nie_cofa_dostarczenia_zaznaczonego_w_panelu(app):
    """C4: odhaczenie w panelu → „Cofnij dostarczenie” jednego przystanku w panelu (trasa wraca do „w trasie”,
    completed_by NULL) → telefon nie może cofnąć dostarczenia, które zaznaczył logistyk (delivered_by_worker_id NULL)
    — 409 route_status. Dostarczenie z telefonu telefon nadal cofa."""
    a, b = _zaladowane(), _zaladowane()
    t = _w_trasie(a, b)
    dostawa.odhacz(t, [a[0].id, b[0].id], user_id=1, teraz=T1)
    db.session.commit()
    assert [s.delivered_by_worker_id for s in RouteStop.query.order_by(RouteStop.id)] == [None, None]
    dostawa.cofnij_dostarczenie(t, b[0].id, user_id=1, teraz=T2)
    db.session.commit()
    assert (t.status, t.completed_by) == ('w_trasie', None)
    e = _blad(dostawa.cofnij_dostarczenie, t, a[0].id, z_telefonu=True, worker_id=7)
    assert (e.kod, e.status) == ('route_status', 409)
    assert e.komunikat == u'To dostarczenie zaznaczył logistyk w panelu — cofnąć może tylko panel.'
    assert RouteStop.query.filter_by(order_id=a[0].id).one().delivered_at == T1
    dostawa.dostarcz(t, b[0].id, worker_id=7, teraz=T2)                     # dostarczenie z telefonu
    db.session.commit()
    assert dostawa.cofnij_dostarczenie(t, b[0].id, z_telefonu=True, worker_id=7, teraz=T2)[1] is True


def test_telefon_nie_cofa_odhaczonego_w_panelu_przystanku_anulowanego(app):
    """C4 dla przystanku zamówienia anulowanego w całości (osiągalny cykl): „Odhacz” zaznacza go jako dostarczony bez
    kierowcy, logistyk cofa w panelu dostarczenie drugiego przystanku (trasa wraca do „w trasie”, completed_by NULL),
    a ostatnim dostarczeniem zostaje przystanek anulowanego z panelu — telefon go nie cofa (409 route_status)."""
    a = _zaladowane()
    d = zamowienie_z_paczkami(statusy=('anulowane',))
    t = _w_trasie(a, d)
    dostawa.odhacz(t, [a[0].id, d[0].id], user_id=1, teraz=T1)
    db.session.commit()
    stop = RouteStop.query.filter_by(order_id=d[0].id).one()
    assert (stop.delivered_at, stop.delivered_by_worker_id) == (T1, None)
    dostawa.cofnij_dostarczenie(t, a[0].id, user_id=1, teraz=T2)
    db.session.commit()
    assert (t.status, t.completed_by) == ('w_trasie', None)
    e = _blad(dostawa.cofnij_dostarczenie, t, d[0].id, z_telefonu=True, worker_id=7)
    assert (e.kod, e.status) == ('route_status', 409) and u'logistyk w panelu' in e.komunikat
    assert RouteStop.query.filter_by(order_id=d[0].id).one().delivered_at == T1


# --- Ruling 30.3: „Niedostarczone” z trasy załadowanej albo w drodze zawsze daje 417343 ---------------------------

def test_niedostarczenie_z_trasy_w_drodze_planowana_trasa_bez_wzgledu_na_pozycje(app):
    """W Base. zamówienie z trasy w drodze ma „Wysłane” (149763) albo „Załadowane” (524520) — także gdy jego pozycje
    cofnęła wcześniej zmiana z Base. albo dawny hurt. Zdjęcie z takiej trasy zawsze daje „Planowana trasa”, spójnie
    z doróbką."""
    a = zamowienie_z_paczkami(statusy=('spakowane', 'spakowane'), zweryfikowane=False)
    b = _zaladowane()
    t = _w_trasie(a, b)
    dostawa.nie_dostarcz(t, a[0].id, 'odmowa', worker_id=7, teraz=T1)
    db.session.commit()
    assert [p.current_status for p in a[0].products] == ['spakowane', 'spakowane']
    assert a[0].bl_status_pending_id == 417343


def test_odznaczenie_w_odhacz_z_trasy_zaladowanej_planowana_trasa_bez_wzgledu_na_pozycje(app):
    a = zamowienie_z_paczkami(statusy=('spakowane', 'spakowane'), zweryfikowane=False)
    b = _zaladowane()
    t = trasa([a[0], b[0]], status='zaladowana', loaded_at=T0)
    zaladuj_wprost(b[1], t)
    dostawa.odhacz(t, [b[0].id], user_id=1, teraz=T1)
    db.session.commit()
    assert a[0].bl_status_pending_id == 417343


def test_niedostarczenie_anulowanego_w_calosci_bez_statusu_base(app):
    """Zamówienie anulowane w całości ma w Base. status anulowania — zdjęcie z trasy w drodze go nie nadpisuje."""
    a = _zaladowane()
    d = zamowienie_z_paczkami(statusy=('anulowane', 'anulowane'))
    t = _w_trasie(a, d)
    dostawa.nie_dostarcz(t, d[0].id, 'inne', worker_id=7, teraz=T1)
    db.session.commit()
    assert d[0].bl_status_pending_id is None


def test_spoznione_dostarczone_po_odznaczeniu_w_panelu_ma_jasny_komunikat(app):
    """C5: kierowca potwierdził dostarczenie offline, a logistyk w tym czasie odhaczył trasę i odznaczył ten przystanek.
    Kod zostaje 404 stop_not_found (appka bez zmian), komunikat mówi, co się stało. Odczyt logu bieżący (jak C1)."""
    a, b = _zaladowane(), _zaladowane()
    t = _w_trasie(a, b)
    dostawa.odhacz(t, [b[0].id], user_id=1, teraz=T1)
    db.session.commit()
    with Zapytania() as z:
        e = _blad(dostawa.dostarcz, t, a[0].id, worker_id=7)
    assert (e.kod, e.status) == ('stop_not_found', 404)
    assert e.komunikat == u'Logistyk zdjął to zamówienie z trasy w panelu.'
    odczyty = _odczyty_logu(z)
    assert odczyty and all(sql.endswith(' LOCK IN SHARE MODE') for sql in odczyty), odczyty
    # Zamówienie, którego na trasie nie było, i niedostarczenie z telefonu — dawny komunikat.
    e = _blad(dostawa.dostarcz, t, zamowienie_z_paczkami(statusy=('zaladowane',))[0].id, worker_id=7)
    assert (e.kod, e.status) == ('stop_not_found', 404) and e.komunikat.startswith(u'Tego zamówienia nie ma na trasie')
    c, d = _zaladowane(), _zaladowane()
    druga = _w_trasie(c, d)
    dostawa.nie_dostarcz(druga, c[0].id, 'odmowa', worker_id=7, teraz=T1)
    db.session.commit()
    e = _blad(dostawa.dostarcz, druga, c[0].id, worker_id=7)
    assert e.komunikat.startswith(u'Tego zamówienia nie ma na trasie')
