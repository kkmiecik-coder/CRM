# -*- coding: utf-8 -*-
"""
U10 (decyzja Konrada 2.10, Ruling 32): „Niedostarczone” zostaje na trasie do jej końca.

Przystanek niedostarczony (pola `not_delivered_*`) zostaje na trasie w drodze: pozycje 'zaladowane', paczki na aucie,
Base. „Wysłane” bez zmian. Kierowca może go jeszcze dostarczyć albo cofnąć niedostarczenie. Do puli „bez trasy”
zamówienie schodzi przy zamknięciu trasy (każdy przystanek dostarczony albo niedostarczony) albo gdy logistyk zdejmie
je w panelu — dopiero wtedy Base. 417343, pozycje 'zweryfikowane', znaczniki załadunku czyszczone. Historia zdjętych
zostaje w logu (`dostawa.niedostarczone_zdjete`).
"""
import gc

import pytest

from extensions import db
from modules.production.logistics import sposoby as s
from modules.production.logistics.models import LogisticsLog, Route, RouteStop
from modules.production.logistics.services import delivery, dostawa, lista, routes
from modules.production.logistics.services.delivery import LogistykaBlad
from tests.blokady_pomocnicze import Zapytania
from tests.dostawa_pomocnicze import (T0, odsmiecaj_po_blokadach, trasa, zaladuj_wprost, zamowienie_z_paczkami,
                                     zwykle_odczyty_stanu)
from tests.logistyka_fixtures import app  # noqa: F401

T1 = T0.replace(hour=9)
T2 = T0.replace(hour=10)
T3 = T0.replace(hour=11)
WYSLANE, PLANOWANA, DOSTARCZONE = 149763, 417343, 149778


def _blad(funkcja, *args, wyjatek=dostawa.DostawaBlad, **kwargs):
    with pytest.raises(wyjatek) as e:
        funkcja(*args, **kwargs)
    db.session.rollback()
    return e.value


def _zaladowane(**kolumny):
    """(zamówienie z pozycjami załadowanymi i Base. „Wysłane”, [paczki])."""
    order, lista_paczek = zamowienie_z_paczkami(statusy=('zaladowane', 'zaladowane'), **kolumny)
    order.bl_status_pending_id = WYSLANE
    db.session.commit()
    return order, lista_paczek


def _w_trasie(*zamowienia):
    t = trasa([o for o, _ in zamowienia], status='w_trasie', loaded_at=T0, departed_at=T0)
    for _o, lista_paczek in zamowienia:
        zaladuj_wprost(lista_paczek, t, kto_id=7)
    return t


def _stop(order):
    return RouteStop.query.filter_by(order_id=order.id).first()


def _wpisy(order, akcja):
    return LogisticsLog.query.filter_by(order_id=order.id, action=akcja).order_by(LogisticsLog.id).all()


# --- Oznaczenie, zmiana powodu, dostarczenie i cofnięcie ------------------------------------------------------

def test_niedostarczone_zostaje_na_trasie(app):
    a, b = _zaladowane(), _zaladowane()
    t = _w_trasie(a, b)
    order, lista_paczek = a
    trasa_po, zmieniono, zamknieta = dostawa.nie_dostarcz(t, order.id, 'brak_klienta', u' nikt  nie otworzył ',
                                                          worker_id=7, device_id=3, teraz=T1)
    db.session.commit()
    assert (zmieniono, zamknieta, trasa_po.status) == (True, False, 'w_trasie')
    assert [st.order_id for st in trasa_po.stops] == [order.id, b[0].id]
    stop = _stop(order)
    assert (stop.not_delivered_at, stop.not_delivered_reason, stop.not_delivered_note,
            stop.not_delivered_by_worker_id, stop.delivered_at) == (T1, 'brak_klienta', u'nikt nie otworzył', 7, None)
    assert [p.current_status for p in order.products] == ['zaladowane', 'zaladowane']
    assert all(p.loaded_route_id == t.id for p in lista_paczek)
    assert order.bl_status_pending_id == WYSLANE                 # Base. zostaje „Wysłane” do końca trasy
    wpis, = _wpisy(order, 'niedostarczone')
    assert (wpis.new_value, wpis.note, wpis.worker_id, wpis.device_id, wpis.route_id) == \
        ('brak_klienta', u'Brak klienta: nikt nie otworzył', 7, 3, t.id)
    assert _wpisy(order, 'trasa_usuniete') == []


def test_niedostarczone_ten_sam_powod_bez_zmian_inny_aktualizuje(app):
    a, b = _zaladowane(), _zaladowane()
    t = _w_trasie(a, b)
    dostawa.nie_dostarcz(t, a[0].id, 'odmowa', u'nie chce', worker_id=7, teraz=T1)
    db.session.commit()
    assert dostawa.nie_dostarcz(t, a[0].id, 'odmowa', u'nie chce', worker_id=8, teraz=T2)[1:] == (False, False)
    db.session.commit()
    assert len(_wpisy(a[0], 'niedostarczone')) == 1 and _stop(a[0]).not_delivered_at == T1
    assert dostawa.nie_dostarcz(t, a[0].id, 'brak_dojazdu', worker_id=8, teraz=T2)[1:] == (True, False)
    db.session.commit()
    stop = _stop(a[0])
    assert (stop.not_delivered_at, stop.not_delivered_reason, stop.not_delivered_note,
            stop.not_delivered_by_worker_id) == (T2, 'brak_dojazdu', None, 8)
    assert [w.new_value for w in _wpisy(a[0], 'niedostarczone')] == ['odmowa', 'brak_dojazdu']


def test_dostarczone_wprost_z_niedostarczonego(app):
    a, b = _zaladowane(), _zaladowane()
    t = _w_trasie(a, b)
    dostawa.nie_dostarcz(t, a[0].id, 'brak_klienta', worker_id=7, teraz=T1)
    db.session.commit()
    _t, zmieniono, zamknieta = dostawa.dostarcz(t, a[0].id, worker_id=7, teraz=T2)
    db.session.commit()
    assert (zmieniono, zamknieta) == (True, False)
    stop = _stop(a[0])
    assert (stop.delivered_at, stop.not_delivered_at, stop.not_delivered_reason, stop.not_delivered_note,
            stop.not_delivered_by_worker_id) == (T2, None, None, None, None)
    assert [p.current_status for p in a[0].products] == ['dostarczone', 'dostarczone']
    assert a[0].bl_status_pending_id == DOSTARCZONE


def test_cofniecie_niedostarczenia(app):
    a, b = _zaladowane(), _zaladowane()
    t = _w_trasie(a, b)
    dostawa.nie_dostarcz(t, a[0].id, 'odmowa', u'za drogo', worker_id=7, teraz=T1)
    db.session.commit()
    trasa_po, zmieniono = dostawa.cofnij_niedostarczenie(t, a[0].id, worker_id=8, device_id=4, teraz=T2)
    db.session.commit()
    assert zmieniono is True and trasa_po.status == 'w_trasie'
    stop = _stop(a[0])
    assert (stop.not_delivered_at, stop.not_delivered_reason, stop.not_delivered_note) == (None, None, None)
    wpis, = _wpisy(a[0], 'niedostarczenie_cofniete')
    assert (wpis.old_value, wpis.new_value, wpis.worker_id, wpis.device_id, wpis.route_id) == \
        ('odmowa', None, 8, 4, t.id)
    assert [p.current_status for p in a[0].products] == ['zaladowane', 'zaladowane']
    assert a[0].bl_status_pending_id == WYSLANE                  # Base. bez zmian
    # Powtórka (przystanek nie jest już niedostarczony) i przystanek dostarczony — bez zmian.
    assert dostawa.cofnij_niedostarczenie(t, a[0].id, worker_id=8, teraz=T2)[1] is False
    dostawa.dostarcz(t, b[0].id, worker_id=7, teraz=T2)
    db.session.commit()
    assert dostawa.cofnij_niedostarczenie(t, b[0].id, user_id=1, teraz=T3)[1] is False
    assert len(_wpisy(a[0], 'niedostarczenie_cofniete')) == 1


def test_cofniecie_niedostarczenia_po_zejsciu_do_puli_404_z_komunikatem(app):
    a, b = _zaladowane(), _zaladowane()
    t = _w_trasie(a, b)
    dostawa.dostarcz(t, b[0].id, worker_id=7, teraz=T1)
    dostawa.nie_dostarcz(t, a[0].id, 'odmowa', worker_id=7, teraz=T2)    # ostatni rozliczony — trasa zamknięta
    db.session.commit()
    assert t.status == 'wykonana' and _stop(a[0]) is None
    e = _blad(dostawa.cofnij_niedostarczenie, t, a[0].id, worker_id=7)
    assert (e.kod, e.status) == ('stop_not_found', 404)
    assert e.komunikat == u'Zamówienie rozliczone jako niedostarczone zeszło już z trasy — jest w puli bez trasy.'


# --- Zamknięcie trasy: niedostarczone schodzą do puli ---------------------------------------------------------

def test_zamkniecie_ostatnim_dostarczeniem_zdejmuje_niedostarczone(app):
    a, b, c = _zaladowane(), _zaladowane(), _zaladowane()
    t = _w_trasie(a, b, c)
    dostawa.nie_dostarcz(t, a[0].id, 'brak_klienta', worker_id=7, teraz=T1)
    dostawa.dostarcz(t, b[0].id, worker_id=7, teraz=T1)
    db.session.commit()
    assert t.status == 'w_trasie'
    trasa_po, zmieniono, zamknieta = dostawa.dostarcz(t, c[0].id, worker_id=9, device_id=5, teraz=T2)
    db.session.commit()
    assert (zmieniono, zamknieta, trasa_po.status, trasa_po.completed_by) == (True, True, 'wykonana', None)
    assert [st.order_id for st in trasa_po.stops] == [b[0].id, c[0].id]
    order, lista_paczek = a
    assert _stop(order) is None
    assert [p.current_status for p in order.products] == ['zweryfikowane', 'zweryfikowane']
    assert all(p.loaded_at is None and p.loaded_route_id is None for p in lista_paczek)
    assert order.bl_status_pending_id == PLANOWANA and order.logistics_closed_at is None
    usuniete, = _wpisy(order, 'trasa_usuniete')
    assert (usuniete.note, usuniete.worker_id, usuniete.device_id, usuniete.route_id) == \
        ('niedostarczone', 9, 5, t.id)
    assert len(_wpisy(order, 'niedostarczone')) == 1
    # `trasa_status` (w drodze → wykonana) tylko przy przystankach, które zostały.
    assert _wpisy(order, 'trasa_status') == []
    assert [w.new_value for w in _wpisy(c[0], 'trasa_status')] == ['wykonana']


def test_zamkniecie_ostatnim_niedostarczeniem(app):
    a, b = _zaladowane(), _zaladowane()
    t = _w_trasie(a, b)
    dostawa.dostarcz(t, a[0].id, worker_id=7, teraz=T1)
    trasa_po, zmieniono, zamknieta = dostawa.nie_dostarcz(t, b[0].id, 'odmowa', worker_id=7, teraz=T2)
    db.session.commit()
    assert (zmieniono, zamknieta, trasa_po.status) == (True, True, 'wykonana')
    assert [st.order_id for st in trasa_po.stops] == [a[0].id]
    assert b[0].bl_status_pending_id == PLANOWANA and routes.przystanek_zamowienia(b[0].id) is None


def test_trasa_z_samymi_niedostarczonymi_zamyka_sie(app):
    a, b = _zaladowane(), _zaladowane()
    t = _w_trasie(a, b)
    dostawa.nie_dostarcz(t, a[0].id, 'odmowa', worker_id=7, teraz=T1)
    db.session.commit()
    assert t.status == 'w_trasie' and len(t.stops) == 2
    trasa_po, _z, zamknieta = dostawa.nie_dostarcz(t, b[0].id, 'brak_dojazdu', worker_id=7, teraz=T2)
    db.session.commit()
    assert zamknieta is True and trasa_po.status == 'wykonana' and trasa_po.stops == []
    assert [o.bl_status_pending_id for o in (a[0], b[0])] == [PLANOWANA, PLANOWANA]


def test_finalizacja_ruling_25_i_anulowane_bez_base(app):
    """Zdjęcie do puli przy zamknięciu: bez weryfikacji pozycje wracają do 'spakowane' (Ruling 25), zamówienie
    anulowane w całości nie dostaje 417343 (Base. ma status anulowania), a reguła 417343 z trasy w drodze działa
    także dla pozycji cofniętych wcześniej (Ruling 30)."""
    a = _zaladowane(zweryfikowane=False)
    d = zamowienie_z_paczkami(statusy=('anulowane', 'anulowane'))
    e = zamowienie_z_paczkami(statusy=('spakowane', 'spakowane'), zweryfikowane=False)
    t = _w_trasie(a, d, e)
    for order in (a[0], d[0], e[0]):
        dostawa.nie_dostarcz(t, order.id, 'inne', worker_id=7, teraz=T1)
    db.session.commit()
    assert t.status == 'wykonana'
    assert [p.current_status for p in a[0].products] == ['spakowane', 'spakowane']
    assert a[0].bl_status_pending_id == PLANOWANA
    assert d[0].bl_status_pending_id is None
    assert e[0].bl_status_pending_id == PLANOWANA


def test_powtorka_niedostarczenia_po_zejsciu_do_puli_bez_zmian(app):
    """Ruling 26 i 32: powtórka „Niedostarczone” (kolejka offline, nowy X-Operation-Id) po zamknięciu trasy — bez
    zmian zamiast 404, choć po wpisie `niedostarczone` zamknięcie dopisało `trasa_usuniete` (liczy się ostatni wpis
    rozliczenia). Odczyt logu bieżący (C1)."""
    a = _zaladowane()
    t = _w_trasie(a)
    dostawa.nie_dostarcz(t, a[0].id, 'odmowa', worker_id=7, teraz=T1)
    db.session.commit()
    assert t.status == 'wykonana'
    a[0].bl_status_pending_id = None   # dopychacz wysłał
    db.session.commit()
    with Zapytania() as z:
        trasa_po, zmieniono, zamknieta = dostawa.nie_dostarcz(t, a[0].id, 'brak_klienta', worker_id=8, teraz=T2)
    assert (zmieniono, zamknieta, trasa_po.status) == (False, False, 'wykonana')
    odczyty = [sql for sql, _p in z.lista if sql.startswith('SELECT') and 'FROM prod_logistics_log' in sql]
    assert odczyty and all(sql.endswith(' LOCK IN SHARE MODE') for sql in odczyty), odczyty
    assert a[0].bl_status_pending_id is None
    assert len(_wpisy(a[0], 'niedostarczone')) == 1 and len(_wpisy(a[0], 'trasa_usuniete')) == 1


def test_brak_przystanku_bez_niedostarczenia_z_tej_trasy_to_404(app):
    a, b = _zaladowane(), _zaladowane()
    t = _w_trasie(a)
    druga = _w_trasie(b)
    assert _blad(dostawa.nie_dostarcz, t, b[0].id, 'inne').kod == 'stop_not_found'        # nigdy na tej trasie
    dostawa.nie_dostarcz(t, a[0].id, 'odmowa', worker_id=7, teraz=T1)                      # zamyka t, a → pula
    db.session.commit()
    assert _blad(dostawa.nie_dostarcz, druga, a[0].id, 'inne').kod == 'stop_not_found'    # niedostarczone z innej
    nowa = trasa([], status='robocza')
    assert routes.dodaj_przystanki(nowa, [a[0].id])['dodane'] == [a[0].id]
    db.session.commit()
    e = _blad(dostawa.nie_dostarcz, t, a[0].id, 'inne')                                   # ostatni: trasa_dodane
    assert (e.kod, e.status) == ('stop_not_found', 404)


def test_spoznione_dostarczone_po_zejsciu_do_puli_404_z_komunikatem(app):
    a, b = _zaladowane(), _zaladowane()
    t = _w_trasie(a, b)
    dostawa.nie_dostarcz(t, a[0].id, 'brak_klienta', worker_id=7, teraz=T1)
    dostawa.dostarcz(t, b[0].id, worker_id=7, teraz=T2)
    db.session.commit()
    e = _blad(dostawa.dostarcz, t, a[0].id, worker_id=7)
    assert (e.kod, e.status) == ('stop_not_found', 404)
    assert u'zeszło już z trasy' in e.komunikat


def test_niedostarczenie_mozliwe_tylko_w_drodze(app):
    stoi, _ = _zaladowane()
    zaladowana = trasa([stoi], status='zaladowana')
    assert _blad(dostawa.nie_dostarcz, zaladowana, stoi.id, 'inne').kod == 'route_status'
    a, b = _zaladowane(), _zaladowane()
    t = _w_trasie(a, b)
    dostawa.dostarcz(t, a[0].id, worker_id=7, teraz=T1)
    db.session.commit()
    assert _blad(dostawa.nie_dostarcz, t, a[0].id, 'inne').kod == 'stop_delivered'


# --- Panel: „Odhacz”, „Cofnij dostarczenie”, „Zdejmij z trasy” ------------------------------------------------

def test_odhacz_niedostarczone(app):
    """Odznaczony do dostarczenia → niedostarczony z powodem `odhaczone_w_panelu`; odznaczony niedostarczony przez
    kierowcę zachowuje jego powód (bez drugiego wpisu); zaznaczony niedostarczony → dostarczony. Odhaczenie zamyka
    trasę, więc wszystkie niedostarczone od razu schodzą do puli (417343), a historia zostaje."""
    a, b, c, d = _zaladowane(), _zaladowane(), _zaladowane(), _zaladowane()
    t = _w_trasie(a, b, c, d)
    dostawa.nie_dostarcz(t, a[0].id, 'brak_klienta', worker_id=7, teraz=T1)
    dostawa.nie_dostarcz(t, b[0].id, 'odmowa', worker_id=7, teraz=T1)
    db.session.commit()
    wynik = dostawa.odhacz(t, [b[0].id, d[0].id], user_id=1, teraz=T2)
    db.session.commit()
    assert wynik == {'dostarczone': [b[0].id, d[0].id], 'niedostarczone': [a[0].id, c[0].id]}
    assert (t.status, t.completed_by) == ('wykonana', 1)
    assert [st.order_id for st in t.stops] == [b[0].id, d[0].id]
    assert _stop(b[0]).not_delivered_at is None and b[0].bl_status_pending_id == DOSTARCZONE
    assert [w.new_value for w in _wpisy(a[0], 'niedostarczone')] == ['brak_klienta']
    wpis, = _wpisy(c[0], 'niedostarczone')
    assert (wpis.new_value, wpis.note, wpis.user_id) == ('odhaczone_w_panelu', u'Odhaczone w panelu', 1)
    assert [o.bl_status_pending_id for o in (a[0], c[0])] == [PLANOWANA, PLANOWANA]
    historia = dostawa.niedostarczone_zdjete([t])[t.id]
    assert [(h['order_id'], h['powod'], h['etykieta']) for h in historia] == [
        (a[0].id, 'brak_klienta', u'Brak klienta'), (c[0].id, 'odhaczone_w_panelu', u'Odhaczone w panelu')]


def test_cofnij_dostarczenie_nie_przywraca_zdjetych_niedostarczonych(app):
    a, b = _zaladowane(), _zaladowane()
    t = _w_trasie(a, b)
    dostawa.nie_dostarcz(t, a[0].id, 'odmowa', worker_id=7, teraz=T1)
    dostawa.dostarcz(t, b[0].id, worker_id=7, teraz=T2)
    db.session.commit()
    trasa_po, zmieniono = dostawa.cofnij_dostarczenie(t, b[0].id, z_telefonu=True, worker_id=7, teraz=T3)
    db.session.commit()
    assert (zmieniono, trasa_po.status) == (True, 'w_trasie')
    assert [st.order_id for st in trasa_po.stops] == [b[0].id]
    assert routes.przystanek_zamowienia(a[0].id) is None and a[0].bl_status_pending_id == PLANOWANA
    assert [h['order_id'] for h in dostawa.niedostarczone_zdjete([trasa_po])[t.id]] == [a[0].id]


def test_zdejmij_niedostarczone_w_panelu(app):
    a, b = _zaladowane(), _zaladowane()
    t = _w_trasie(a, b)
    dostawa.nie_dostarcz(t, a[0].id, 'brak_klienta', worker_id=7, teraz=T1)
    db.session.commit()
    trasa_po = dostawa.zdejmij_niedostarczone(t, a[0].id, user_id=1, teraz=T2)
    db.session.commit()
    assert trasa_po.status == 'w_trasie' and [st.order_id for st in trasa_po.stops] == [b[0].id]
    assert [p.current_status for p in a[0].products] == ['zweryfikowane', 'zweryfikowane']
    assert a[0].bl_status_pending_id == PLANOWANA and all(p.loaded_at is None for p in a[1])
    usuniete, = _wpisy(a[0], 'trasa_usuniete')
    assert (usuniete.note, usuniete.user_id) == ('niedostarczone', 1)
    # Odmowy: nie niedostarczony (409), brak przystanku (404), trasa nie w drodze (409).
    e = _blad(dostawa.zdejmij_niedostarczone, t, b[0].id, user_id=1, wyjatek=LogistykaBlad)
    assert e.status == 409 and u'tylko przystanek niedostarczony' in e.komunikat
    assert _blad(dostawa.zdejmij_niedostarczone, t, a[0].id, user_id=1).status == 404
    stoi, _ = _zaladowane()
    zaladowana = trasa([stoi], status='zaladowana')
    assert _blad(dostawa.zdejmij_niedostarczone, zaladowana, stoi.id, user_id=1).kod == 'route_status'
    # Powtórka „Niedostarczone” z telefonu po zdjęciu w panelu — bez zmian (Ruling 26).
    assert dostawa.nie_dostarcz(t, a[0].id, 'brak_klienta', worker_id=7, teraz=T3)[1] is False


def test_dorobka_na_niedostarczonym_zdejmuje_od_razu(app):
    """Ruling 30 bez zmian (R32.6): doróbka na niedostarczonym przystanku trasy w drodze zdejmuje go od razu z powodem
    `dorobka` (ten powód trafia do historii). Gdy to zamyka trasę, inne niedostarczone też schodzą do puli."""
    from modules.production.services import rework_service
    a = zamowienie_z_paczkami(statusy=('zaladowane', 'zaladowane'))
    b, c = _zaladowane(), _zaladowane()
    t = _w_trasie(a, b, c)
    dostawa.nie_dostarcz(t, a[0].id, 'uszkodzenie', worker_id=7, teraz=T1)
    dostawa.nie_dostarcz(t, b[0].id, 'odmowa', worker_id=7, teraz=T1)
    dostawa.dostarcz(t, c[0].id, worker_id=7, teraz=T1)
    db.session.commit()
    assert t.status == 'wykonana'      # wszystko rozliczone — zamknięcie zdjęło a i b do puli
    assert routes.przystanek_zamowienia(a[0].id) is None
    # Druga trasa: doróbka na niedostarczonym zdejmuje go od razu, a trasa zostaje w drodze.
    d = zamowienie_z_paczkami(statusy=('zaladowane', 'zaladowane'))
    e = _zaladowane()
    t2 = _w_trasie(d, e)
    dostawa.nie_dostarcz(t2, d[0].id, 'uszkodzenie', worker_id=7, teraz=T1)
    db.session.commit()
    pozycja_id = d[0].products[0].id
    d[0].products[0].current_status = 'czeka_na_pakowanie'
    db.session.commit()
    rework_service.reject_product_quantity(product_id=pozycja_id, quantity=1, reason_category='inne',
                                           rejected_at_station='packaging', worker_ids=[7])
    db.session.expire_all()
    t2 = db.session.get(Route, t2.id)
    assert t2.status == 'w_trasie' and [st.order_id for st in t2.stops] == [e[0].id]
    assert [h['powod'] for h in dostawa.niedostarczone_zdjete([t2])[t2.id]] == ['dorobka']


def test_historia_niedostarczonych_trasy(app):
    """Zdjęte jako niedostarczone są w historii; niedostarczony jeszcze na trasie, dostarczony po niedostarczeniu,
    z cofniętym niedostarczeniem i trasa robocza — nie."""
    a, b, c, d = _zaladowane(), _zaladowane(), _zaladowane(), _zaladowane()
    t = _w_trasie(a, b, c, d)
    dostawa.nie_dostarcz(t, a[0].id, 'brak_klienta', u'zadzwonić', worker_id=7, teraz=T1)
    dostawa.nie_dostarcz(t, b[0].id, 'odmowa', worker_id=7, teraz=T1)
    dostawa.dostarcz(t, b[0].id, worker_id=7, teraz=T2)
    dostawa.nie_dostarcz(t, c[0].id, 'odmowa', worker_id=7, teraz=T1)
    dostawa.cofnij_niedostarczenie(t, c[0].id, worker_id=7, teraz=T2)
    db.session.commit()
    assert dostawa.niedostarczone_zdjete([t]) == {t.id: []}           # a jeszcze na trasie
    dostawa.zdejmij_niedostarczone(t, a[0].id, user_id=1, teraz=T3)
    db.session.commit()
    historia, = dostawa.niedostarczone_zdjete([t])[t.id]
    assert historia == {'order_id': a[0].id, 'powod': 'brak_klienta', 'etykieta': u'Brak klienta',
                        'notatka': u'zadzwonić', 'kiedy': T1}
    robocza = trasa([], status='robocza')
    assert dostawa.niedostarczone_zdjete([robocza]) == {robocza.id: []}


def test_rozbierz_opis():
    assert dostawa.rozbierz_opis('brak_klienta', u'Brak klienta: nikt: nie') == (u'Brak klienta', u'nikt: nie')
    assert dostawa.rozbierz_opis('odmowa', u'Odmowa przyjęcia') == (u'Odmowa przyjęcia', None)
    assert dostawa.rozbierz_opis('dorobka', u'Doróbka — wraca do produkcji') == (u'Doróbka — wraca do produkcji',
                                                                                 None)
    assert dostawa.rozbierz_opis('odhaczone_w_panelu', None) == (u'Odhaczone w panelu', None)


# --- Decyzje na zablokowanych obiektach (Ruling P2) ---------------------------------------------------------

def _odlacz_i_odsmiecaj(monkeypatch, route_id):
    db.session.expunge_all()
    gc.collect()
    licznik = odsmiecaj_po_blokadach(monkeypatch)
    return db.session.get(Route, route_id), licznik


def test_zamkniecie_z_niedostarczonymi_decyduje_na_zablokowanych_obiektach(app, monkeypatch):
    a, b = _zaladowane(), _zaladowane()
    t = _w_trasie(a, b)
    dostawa.nie_dostarcz(t, a[0].id, 'odmowa', worker_id=7, teraz=T1)
    db.session.commit()
    route_id, oid, zostaje = t.id, b[0].id, b[0].id
    route, licznik = _odlacz_i_odsmiecaj(monkeypatch, route_id)
    with Zapytania() as z:
        trasa_po, _zmieniono, zamknieta = dostawa.dostarcz(route, oid, worker_id=7, teraz=T2)
        db.session.flush()
    assert zwykle_odczyty_stanu(z) == [] and licznik['_wymagaj_statusu'] > 0 and licznik['zapisz_log'] > 0
    assert zamknieta is True and [st.order_id for st in trasa_po.stops] == [zostaje]


def test_cofniecie_i_zdjecie_decyduja_na_zablokowanych_obiektach(app, monkeypatch):
    c, d = _zaladowane(), _zaladowane()
    t = _w_trasie(c, d)
    dostawa.nie_dostarcz(t, c[0].id, 'odmowa', worker_id=7, teraz=T1)
    db.session.commit()
    route_id, cid = t.id, c[0].id
    route, licznik = _odlacz_i_odsmiecaj(monkeypatch, route_id)
    with Zapytania() as z:
        _t, zmieniono = dostawa.cofnij_niedostarczenie(route, cid, worker_id=7, teraz=T2)
        dostawa.nie_dostarcz(route, cid, 'inne', worker_id=7, teraz=T2)
        trasa_po = dostawa.zdejmij_niedostarczone(route, cid, user_id=1, teraz=T3)
        db.session.flush()
    assert zmieniono is True and len(trasa_po.stops) == 1
    assert zwykle_odczyty_stanu(z) == [] and licznik['_wymagaj_statusu'] > 0 and licznik['zapisz_log'] > 0


# --- Postęp, lista Logistyki, zmiany zamówienia z trasy ----------------------------------------------------

def test_postep_liczy_niedostarczone_i_zdjete(app):
    from modules.production.logistics.services import paczki
    a, b, c = _zaladowane(), _zaladowane(), _zaladowane()
    t = _w_trasie(a, b, c)
    dostawa.nie_dostarcz(t, a[0].id, 'odmowa', worker_id=7, teraz=T1)
    dostawa.nie_dostarcz(t, b[0].id, 'odmowa', worker_id=7, teraz=T1)
    db.session.commit()
    dostawa.zdejmij_niedostarczone(t, b[0].id, user_id=1, teraz=T2)
    db.session.commit()
    zamowienia = routes.zamowienia_trasy(t)
    pakunki = paczki.aktualne_paczki_zamowien([o.id for o in zamowienia])
    zdjete = dostawa.niedostarczone_zdjete([t])[t.id]
    assert routes.postep(t, zamowienia, pakunki, zdjete) == {
        'przystanki': 2, 'zaladowane': 2, 'dostarczone': 0, 'niedostarczone': 2, 'zdjete': 1}
    assert routes.postep(t, zamowienia, pakunki)['niedostarczone'] == 1


def test_etap_w_trasie_niedostarczone_na_liscie(app):
    a, b = _zaladowane(), _zaladowane()
    t = _w_trasie(a, b)
    dostawa.nie_dostarcz(t, a[0].id, 'odmowa', worker_id=7, teraz=T1)
    db.session.commit()
    assert lista.serializuj(a[0], None, t)['etap'] == {'status': 'w_trasie', 'nazwa': u'W trasie — niedostarczone'}
    assert lista.serializuj(b[0], None, t)['etap'] == {'status': 'w_trasie', 'nazwa': u'W trasie'}
    assert {w['id'] for w in lista.pobierz(etap='w_trasie')} >= {a[0].id, b[0].id}


@pytest.mark.parametrize('zmiana', ['adres', 'pinezka'])
def test_zmiana_zamowienia_niedostarczonego_na_trasie_409(app, zmiana):
    a, b = _zaladowane(), _zaladowane()
    t = _w_trasie(a, b)
    dostawa.nie_dostarcz(t, a[0].id, 'odmowa', worker_id=7, teraz=T1)
    db.session.commit()
    with pytest.raises(LogistykaBlad) as e:
        if zmiana == 'adres':
            delivery.zmien_adres(a[0], u'ul. Nowa 1', '35-001', u'Rzeszów')
        else:
            delivery.sprawdz_trase_przed_zmiana(a[0], u'zmiana punktu na mapie')
    assert e.value.status == 409
    assert u'jest niedostarczone na trasie „{}”'.format(t.name) in e.value.komunikat
    assert u'po zakończeniu trasy albo po zdjęciu go z trasy w panelu tras' in e.value.komunikat


def test_cron_nie_rusza_niedostarczonego_na_trasie(app):
    a, b = _zaladowane(), _zaladowane()
    t = _w_trasie(a, b)
    dostawa.nie_dostarcz(t, a[0].id, 'odmowa', worker_id=7, teraz=T1)
    db.session.commit()
    delivery.przelicz_otwarte(T2)
    db.session.commit()
    assert _stop(a[0]).not_delivered_at == T1
    assert [p.current_status for p in a[0].products] == ['zaladowane', 'zaladowane']
    assert a[0].logistics_closed_at is None
