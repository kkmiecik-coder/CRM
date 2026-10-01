# -*- coding: utf-8 -*-
"""Załadunek trasy (logistyka etap 4, krok 4.4, spec 9.3–9.4 i 4.5): skan paczek z bramką weryfikacji, „Zostaje”,
zakończenie załadunku, wyjazd, „Cofnij załadunek” z panelu i „Cofnij zatwierdzenie” w trakcie załadunku (Ruling 21b)
— serwis services/dostawa.py."""
import gc

import pytest
from sqlalchemy import event

from extensions import db
from modules.production.logistics.models import LogisticsLog, Route, RouteStop
from modules.production.logistics.services import dostawa, routes
from modules.production.models import ProductionPackage
from tests.blokady_pomocnicze import Zapytania, blokada_pozycji, blokada_zamowien, klauzula_blokady, zapis
from tests.dostawa_pomocnicze import (T0, odsmiecaj_po_blokadach, trasa, zaladuj_wprost, zamowienie_z_paczkami,
                                     zwykle_odczyty_stanu)
from tests.logistyka_fixtures import BASE, app, client  # noqa: F401


def _blad(funkcja, *args, **kwargs):
    with pytest.raises(dostawa.DostawaBlad) as e:
        funkcja(*args, **kwargs)
    db.session.rollback()
    return e.value


def _akcje(order):
    return [w.action for w in LogisticsLog.query.filter_by(order_id=order.id).order_by(LogisticsLog.id)]


# --- Skan paczki --------------------------------------------------------------------------------------

def test_zaladunek_paczki_skanem(app):
    order, (p1, p2) = zamowienie_z_paczkami()
    t = trasa([order])
    paczka, zmieniono = dostawa.zaladuj_paczke(t, p1.id, 'skan', worker_id=7, device_id=3, teraz=T0)
    db.session.commit()
    assert zmieniono is True and paczka is p1
    assert (p1.loaded_at, p1.loaded_by_worker_id, p1.loaded_method, p1.loaded_route_id) == (T0, 7, 'skan', t.id)
    assert p2.loaded_at is None
    # Pozycje zostają zweryfikowane — „zaladowane” dostają dopiero przy zakończeniu załadunku.
    assert [p.current_status for p in order.products] == ['zweryfikowane', 'zweryfikowane']


def test_ponowny_skan_bez_zmian(app):
    """Review Focus 4: powtórka z kolejki offline z nowym X-Operation-Id — bez zmian, pierwszy zapis zostaje."""
    order, (p1, _p2) = zamowienie_z_paczkami()
    t = trasa([order])
    dostawa.zaladuj_paczke(t, p1.id, 'skan', worker_id=7, teraz=T0)
    db.session.commit()
    _paczka, zmieniono = dostawa.zaladuj_paczke(t, p1.id, 'reczne', worker_id=8)
    assert zmieniono is False
    assert (p1.loaded_method, p1.loaded_by_worker_id, p1.loaded_at) == ('skan', 7, T0)


def test_zaladunek_odmowy(app):
    order, (p1, _p2) = zamowienie_z_paczkami()
    t = trasa([order])
    e = _blad(dostawa.zaladuj_paczke, t, 987654)
    assert (e.kod, e.status) == ('package_not_found', 404)
    e = _blad(dostawa.zaladuj_paczke, t, p1.id, 'palcem')
    assert (e.kod, e.status) == ('invalid_method', 422)
    inne, (q1, _q2) = zamowienie_z_paczkami()
    trasa([inne], nazwa=u'Lublin 03.10')
    e = _blad(dostawa.zaladuj_paczke, t, q1.id)
    assert e.kod == 'package_not_on_route' and u'Lublin 03.10' in e.komunikat
    assert e.dane == {'route_name': u'Lublin 03.10'}
    bez_trasy, (b1, _b2) = zamowienie_z_paczkami()
    e = _blad(dostawa.zaladuj_paczke, t, b1.id)
    assert e.kod == 'package_not_on_route' and u'bez trasy' in e.komunikat and e.dane == {'route_name': None}


def test_zaladunek_tylko_na_trasie_zatwierdzonej(app):
    order, (p1, _p2) = zamowienie_z_paczkami()
    for status in ('robocza', 'zaladowana', 'w_trasie', 'wykonana'):
        t = trasa([order], status=status)
        e = _blad(dostawa.zaladuj_paczke, t, p1.id)
        assert (e.kod, e.status) == ('route_status', 409), status
        RouteStop.query.filter_by(order_id=order.id).delete()
        db.session.commit()


def test_skan_po_zakonczeniu_zaladunku_mowi_o_statusie_trasy(app):
    """Po zakończeniu załadunku pozycje są 'zaladowane'. Wstępna odmowa z migawki sprawdza to samo i w tej samej
    kolejności co decyzja pod blokadami (najpierw status trasy), więc skan dostaje route_status, a nie mylące
    „nie jest zweryfikowane” o towarze, który już jest na aucie."""
    order, (p1, _p2) = zamowienie_z_paczkami(statusy=('zaladowane', 'zaladowane'))
    t = trasa([order], status='zaladowana')
    zaladuj_wprost([p1], t)
    assert _blad(dostawa.zaladuj_paczke, t, p1.id).kod == 'route_status'


def test_zaladunek_niewaznej_paczki_i_niezweryfikowanego_zamowienia(app):
    order, (p1, p2) = zamowienie_z_paczkami()
    t = trasa([order])
    p1.voided_at = T0
    db.session.commit()
    assert _blad(dostawa.zaladuj_paczke, t, p1.id).kod == 'package_void'
    niezweryfikowane, (n1, _n2) = zamowienie_z_paczkami(statusy=('spakowane', 'spakowane'), zweryfikowane=False)
    t2 = trasa([niezweryfikowane])
    e = _blad(dostawa.zaladuj_paczke, t2, n1.id)
    assert e.kod == 'order_not_verified' and niezweryfikowane.internal_order_number in e.komunikat
    assert p2.loaded_at is None and n1.loaded_at is None


def test_wstepna_odmowa_niezweryfikowanego_bez_blokad(app, monkeypatch):
    """Odmowę widoczną już w migawce dajemy przed blokadami (lekcja 1213 z kroku 4.3: nie czekamy na blokady,
    skoro i tak odmówimy)."""
    order, (p1,) = zamowienie_z_paczkami(statusy=('spakowane',), paczek=1, zweryfikowane=False)
    t = trasa([order])

    def _nie_wolno(*a, **k):
        raise AssertionError('blokady przed wstępną odmową')

    monkeypatch.setattr(routes, 'zablokuj_trasy', _nie_wolno)
    assert _blad(dostawa.zaladuj_paczke, t, p1.id).kod == 'order_not_verified'


def test_skan_paczki_z_innej_trasy_mowi_o_trasie(app):
    """Wstępna odmowa „niezweryfikowane” tylko dla zamówienia z TEJ trasy: paczka z innej trasy dostaje odmowę
    z nazwą tamtej trasy (spec 9.3), także gdy tamto zamówienie nie jest jeszcze zweryfikowane."""
    order, _ = zamowienie_z_paczkami()
    t = trasa([order])
    obce, (o1,) = zamowienie_z_paczkami(statusy=('spakowane',), paczek=1, zweryfikowane=False)
    trasa([obce], nazwa=u'Krosno 05.10')
    e = _blad(dostawa.zaladuj_paczke, t, o1.id)
    assert e.kod == 'package_not_on_route' and u'Krosno 05.10' in e.komunikat


def test_skan_przystanku_zostaje_409(app):
    order, (p1, _p2) = zamowienie_z_paczkami()
    t = trasa([order])
    dostawa.ustaw_zostaje(t, order.id, 'brak_miejsca', worker_id=7)
    db.session.commit()
    e = _blad(dostawa.zaladuj_paczke, t, p1.id)
    assert e.kod == 'stop_stays' and u'Brak miejsca' in e.komunikat
    assert p1.loaded_at is None


def test_rozladunek_cofa_pomylke(app):
    order, (p1, _p2) = zamowienie_z_paczkami()
    t = trasa([order])
    zaladuj_wprost([p1], t, kto_id=7)
    _paczka, zmieniono = dostawa.rozladuj_paczke(t, p1.id, worker_id=7)
    db.session.commit()
    assert zmieniono is True and (p1.loaded_at, p1.loaded_route_id, p1.loaded_method) == (None, None, None)
    assert dostawa.rozladuj_paczke(t, p1.id)[1] is False


# --- „Zostaje” ---------------------------------------------------------------------------------------

def test_zostaje_czysci_zaladunek_przystanku_i_daje_sie_zdjac(app):
    order, lista_paczek = zamowienie_z_paczkami()
    t = trasa([order])
    zaladuj_wprost(lista_paczek, t, kto_id=7)
    assert dostawa.ustaw_zostaje(t, order.id, 'uszkodzone', u'  pęknięta  deska ', worker_id=7) is True
    db.session.commit()
    stop = RouteStop.query.filter_by(order_id=order.id).one()
    assert (stop.stays_reason, stop.stays_note) == ('uszkodzone', u'pęknięta deska')
    assert all(p.loaded_at is None for p in lista_paczek)
    assert dostawa.ustaw_zostaje(t, order.id, 'uszkodzone', u'pęknięta deska') is False
    assert dostawa.zdejmij_zostaje(t, order.id, worker_id=7) is True
    db.session.commit()
    assert (stop.stays_reason, stop.stays_note) == (None, None)
    assert dostawa.zdejmij_zostaje(t, order.id) is False


def test_zostaje_odmowy(app):
    order, _ = zamowienie_z_paczkami()
    t = trasa([order])
    e = _blad(dostawa.ustaw_zostaje, t, order.id, 'nie_chce')
    assert (e.kod, e.status) == ('invalid_reason', 422)
    e = _blad(dostawa.ustaw_zostaje, t, order.id, ['inne'])          # lista z JSON-a — 422, nie 500
    assert e.kod == 'invalid_reason'
    e = _blad(dostawa.ustaw_zostaje, t, 987654, 'inne')
    assert (e.kod, e.status) == ('stop_not_found', 404)
    jedzie, _ = zamowienie_z_paczkami(statusy=('zaladowane',))
    w_trasie = trasa([jedzie], status='w_trasie')
    assert _blad(dostawa.ustaw_zostaje, w_trasie, jedzie.id, 'inne').kod == 'route_status'


# --- Zakończenie załadunku ---------------------------------------------------------------------------

def test_zakonczenie_zaladunku(app):
    jedzie, paczki_jedzie = zamowienie_z_paczkami()
    zostaje, _ = zamowienie_z_paczkami()
    t = trasa([jedzie, zostaje])
    zaladuj_wprost(paczki_jedzie, t, kto_id=7)
    dostawa.ustaw_zostaje(t, zostaje.id, 'brak_miejsca', u'za długie')
    db.session.commit()
    trasa_po, usuniete = dostawa.zakoncz_zaladunek(t, worker_id=7, device_id=3, teraz=T0)
    db.session.commit()
    assert trasa_po.status == 'zaladowana' and (trasa_po.loaded_at, trasa_po.loaded_by_worker_id) == (T0, 7)
    assert [s.order_id for s in trasa_po.stops] == [jedzie.id]
    assert usuniete == [{'order_id': zostaje.id, 'internal_order_number': zostaje.internal_order_number,
                         'reason': 'brak_miejsca'}]
    assert [p.current_status for p in jedzie.products] == ['zaladowane', 'zaladowane']
    assert jedzie.bl_status_pending_id == 524520
    assert [p.current_status for p in zostaje.products] == ['zweryfikowane', 'zweryfikowane']   # bez zmian
    assert zostaje.bl_status_pending_id is None
    assert RouteStop.query.filter_by(order_id=zostaje.id).first() is None
    wpis = LogisticsLog.query.filter_by(order_id=zostaje.id, action='zostaje').one()
    assert (wpis.new_value, wpis.note, wpis.worker_id, wpis.device_id) == \
        ('brak_miejsca', u'Brak miejsca: za długie', 7, 3)
    assert LogisticsLog.query.filter_by(order_id=zostaje.id, action='trasa_usuniete').one().worker_id == 7
    zaladunek = LogisticsLog.query.filter_by(order_id=jedzie.id, action='zaladunek').one()
    assert (zaladunek.old_value, zaladunek.new_value, zaladunek.note) == (None, 'zaladowane', u'2 × paczka')
    status = LogisticsLog.query.filter_by(order_id=jedzie.id, action='trasa_status').one()
    assert (status.old_value, status.new_value, status.worker_id) == ('zatwierdzona', 'zaladowana', 7)


def test_zakonczenie_zdejmuje_anulowane(app):
    jedzie, paczki_jedzie = zamowienie_z_paczkami()
    anulowane, _ = zamowienie_z_paczkami(statusy=('anulowane',))
    t = trasa([jedzie, anulowane])
    zaladuj_wprost(paczki_jedzie, t)
    _trasa, usuniete = dostawa.zakoncz_zaladunek(t, worker_id=7)
    db.session.commit()
    assert usuniete == [{'order_id': anulowane.id, 'internal_order_number': anulowane.internal_order_number,
                         'reason': 'anulowane'}]
    assert RouteStop.query.filter_by(order_id=anulowane.id).first() is None


def test_zakonczenie_lista_brakow(app):
    czesc, (c1, _c2) = zamowienie_z_paczkami()
    bez_paczek, _ = zamowienie_z_paczkami(paczek=0)
    t = trasa([czesc, bez_paczek])
    zaladuj_wprost([c1], t)
    e = _blad(dostawa.zakoncz_zaladunek, t, worker_id=7)
    assert (e.kod, e.status) == ('loading_incomplete', 409)
    assert e.dane == {'braki': [
        {'order_id': czesc.id, 'internal_order_number': czesc.internal_order_number, 'reason': 'niezaladowane',
         'loaded': 1, 'total': 2},
        {'order_id': bez_paczek.id, 'internal_order_number': bez_paczek.internal_order_number,
         'reason': 'bez_paczek', 'loaded': 0, 'total': 0}]}
    assert czesc.internal_order_number in e.komunikat
    assert routes.przystanek_zamowienia(czesc.id).route.status == 'zatwierdzona'


def test_zakonczenie_odmawia_gdy_zamowienie_przestalo_byc_zweryfikowane(app):
    """Review Focus 2: paczki zostały na aucie, ale pozycje nie są już zweryfikowane — zakończenie nie przepuszcza
    takiego zamówienia jako załadowanego."""
    order, lista_paczek = zamowienie_z_paczkami()
    t = trasa([order])
    zaladuj_wprost(lista_paczek, t)
    for p in order.products:
        p.current_status = 'spakowane'
    db.session.commit()
    e = _blad(dostawa.zakoncz_zaladunek, t)
    assert e.dane['braki'][0]['reason'] == 'niezweryfikowane'


def test_zakonczenie_bez_zaladowanych_409(app):
    order, _ = zamowienie_z_paczkami()
    t = trasa([order], nazwa=u'Jasło 06.10')
    dostawa.ustaw_zostaje(t, order.id, 'inne')
    db.session.commit()
    e = _blad(dostawa.zakoncz_zaladunek, t)
    assert e.kod == 'nothing_loaded' and u'Jasło 06.10' in e.komunikat
    assert RouteStop.query.filter_by(order_id=order.id).one().stays_reason == 'inne'   # nic nie zdjęte


# --- Wyjazd i cofnięcie załadunku ------------------------------------------------------------------------

def test_ruszam(app):
    order, _ = zamowienie_z_paczkami(statusy=('zaladowane', 'zaladowane'))
    t = trasa([order], status='zaladowana')
    trasa_po, zmieniono = dostawa.ruszaj(t, worker_id=7, device_id=3, teraz=T0)
    db.session.commit()
    assert zmieniono is True and trasa_po.status == 'w_trasie'
    assert (trasa_po.departed_at, trasa_po.departed_by_worker_id) == (T0, 7)
    assert order.bl_status_pending_id == 149763
    wpis = LogisticsLog.query.filter_by(order_id=order.id, action='wyjazd').one()
    assert (wpis.old_value, wpis.new_value, wpis.worker_id) == ('zaladowana', 'w_trasie', 7)


def test_ponowne_ruszam_bez_zmian(app):
    """Review Focus 4: drugie „Ruszam” nie wysyła drugi raz 149763 ani nie dopisuje logu."""
    order, _ = zamowienie_z_paczkami(statusy=('zaladowane',))
    t = trasa([order], status='zaladowana')
    dostawa.ruszaj(t, worker_id=7, teraz=T0)
    db.session.commit()
    order.bl_status_pending_id = None   # dopychacz wysłał
    db.session.commit()
    _trasa, zmieniono = dostawa.ruszaj(t, worker_id=7)
    assert zmieniono is False and order.bl_status_pending_id is None
    assert _akcje(order).count('wyjazd') == 1


def test_ruszam_wymaga_zakonczonego_zaladunku(app):
    order, _ = zamowienie_z_paczkami()
    t = trasa([order])
    assert _blad(dostawa.ruszaj, t).kod == 'route_status'


def test_cofnij_zaladunek_z_panelu(app):
    order, lista_paczek = zamowienie_z_paczkami(statusy=('zaladowane', 'zaladowane'))
    t = trasa([order], status='zaladowana', loaded_at=T0, loaded_by_worker_id=7)
    zaladuj_wprost(lista_paczek, t, kto_id=7)
    trasa_po = dostawa.cofnij_zaladunek(t, user_id=1, teraz=T0)
    db.session.commit()
    assert trasa_po.status == 'zatwierdzona' and (trasa_po.loaded_at, trasa_po.loaded_by_worker_id) == (None, None)
    assert [p.current_status for p in order.products] == ['zweryfikowane', 'zweryfikowane']
    assert all(p.loaded_at is None for p in lista_paczek)
    assert order.bl_status_pending_id == 417343
    wpis = LogisticsLog.query.filter_by(order_id=order.id, action='zaladunek').one()
    assert (wpis.old_value, wpis.new_value, wpis.user_id) == ('zaladowane', None, 1)
    assert _blad(dostawa.cofnij_zaladunek, trasa_po).kod == 'route_status'


# --- „Cofnij zatwierdzenie” w trakcie załadunku (Ruling 21b) --------------------------------------------

def _znacznik(paczka):
    return (paczka.loaded_at, paczka.loaded_by_worker_id, paczka.loaded_method, paczka.loaded_route_id)


def test_cofniecie_zatwierdzenia_czysci_zaladunek_tej_trasy(app):
    """Kierowca załadował część paczek (pozycje dalej zweryfikowane), logistyk cofa zatwierdzenie (np. zastępstwo
    kierowcy, decyzja Konrada 5): znaczniki tej trasy znikają, log `zaladunek` tylko przy zamówieniu, któremu coś
    wyczyszczono; status trasy i log `trasa_status` jak dotąd."""
    a, (a1, a2) = zamowienie_z_paczkami()
    b, _ = zamowienie_z_paczkami()
    t = trasa([a, b])
    dostawa.zaladuj_paczke(t, a1.id, worker_id=7, teraz=T0)
    db.session.commit()
    trasa_po = dostawa.cofnij_zatwierdzenie(t, user_id=1, teraz=T0)
    db.session.commit()
    assert (trasa_po.status, trasa_po.approved_at, trasa_po.approved_by) == ('robocza', None, None)
    assert _znacznik(a1) == _znacznik(a2) == (None, None, None, None)
    assert [p.current_status for p in a.products] == ['zweryfikowane', 'zweryfikowane']
    wpis = LogisticsLog.query.filter_by(order_id=a.id, action='zaladunek').one()
    assert (wpis.old_value, wpis.new_value, wpis.note, wpis.user_id, wpis.route_id) == (
        'zaladowane', None, u'cofnięte zatwierdzenie trasy', 1, t.id)
    assert LogisticsLog.query.filter_by(order_id=b.id, action='zaladunek').count() == 0
    for order in (a, b):
        status = LogisticsLog.query.filter_by(order_id=order.id, action='trasa_status').one()
        assert (status.old_value, status.new_value, status.user_id) == ('zatwierdzona', 'robocza', 1)


def test_cofniecie_zatwierdzenia_nie_rusza_znacznika_innej_trasy(app):
    """Czyścimy tylko znaczniki TEJ trasy: nieaktualny znacznik innej trasy na paczce zamówienia z tej trasy i paczki
    zamówienia z innej trasy zostają."""
    a, (a1, a2) = zamowienie_z_paczkami()
    c, (c1, _c2) = zamowienie_z_paczkami()
    t = trasa([a])
    inna = trasa([c])
    zaladuj_wprost([a1], t, kto_id=7)
    zaladuj_wprost([a2, c1], inna, kto_id=8)
    dostawa.cofnij_zatwierdzenie(t, user_id=1)
    db.session.commit()
    assert _znacznik(a1) == (None, None, None, None)
    assert _znacznik(a2) == _znacznik(c1) == (T0, 8, 'skan', inna.id)
    assert inna.status == 'zatwierdzona'


def test_cofniecie_zatwierdzenia_bez_znacznikow_tylko_blokada_tras(app):
    """Bez znaczników tej trasy (znacznik innej trasy się nie liczy) — jak dotąd: blokada tras i sama trasa, bez
    blokady deklaracji, zamówień i pozycji."""
    order, (p1, _p2) = zamowienie_z_paczkami()
    t = trasa([order])
    inna = trasa([], status='zatwierdzona')
    zaladuj_wprost([p1], inna)
    with Zapytania() as z:
        dostawa.cofnij_zatwierdzenie(t, user_id=1)
        db.session.flush()
    blokujace = [(sql, tuple(par or ())) for sql, par in z.lista
                 if sql.endswith((' FOR UPDATE', ' LOCK IN SHARE MODE'))]
    assert blokujace and all(('FROM prod_config' in sql and 'logistyka_trasy_blokada' in par)
                             or 'FROM prod_routes' in sql for sql, par in blokujace)
    assert t.status == 'robocza' and p1.loaded_route_id == inna.id


def test_cofniecie_zatwierdzenia_kolejnosc_blokad(app):
    """Ze znacznikami: blokada tras → blokada deklaracji → zamówienia trasy rosnąco → paczki → pozycje → pierwszy
    zapis (kolejność zapisu Dostawy, Ruling 20)."""
    a, paczki_a = zamowienie_z_paczkami()
    b, paczki_b = zamowienie_z_paczkami()
    t = trasa([b, a])
    zaladuj_wprost(paczki_a[:1] + paczki_b[:1], t)
    with Zapytania() as z:
        dostawa.cofnij_zatwierdzenie(t, user_id=1)
        db.session.flush()

    def blokada(klucz):
        return next(i for i, (sql, par) in enumerate(z.lista)
                    if 'FROM prod_config' in sql and klucz in tuple(par or ()))

    zamowienia_i = z.pierwsze(blokada_zamowien)
    paczki_i = z.pierwsze(lambda sql: 'FROM prod_packages' in sql and sql.endswith(' FOR UPDATE'))
    assert (blokada('logistyka_trasy_blokada') < blokada('logistyka_paczki_blokada') < zamowienia_i < paczki_i
            < z.pierwsze(blokada_pozycji) < z.pierwsze(zapis))
    assert list(z.lista[zamowienia_i][1]) == sorted([a.id, b.id])
    assert all(p.loaded_route_id is None for p in paczki_a + paczki_b)


def test_api_cofniecie_zatwierdzenia_czysci_zaladunek(app, client):
    """POST /routes/<id>/revert: odpowiedź jak dotąd (trasa robocza), znaczniki tej trasy wyczyszczone."""
    order, (p1, _p2) = zamowienie_z_paczkami()
    t = trasa([order])
    zaladuj_wprost([p1], t, kto_id=7)
    rid, pid = t.id, p1.id
    r = client.post(BASE + '/routes/%d/revert' % rid)
    assert r.status_code == 200, r.get_data()[:300]
    odpowiedz = r.get_json()
    assert odpowiedz['success'] is True and odpowiedz['route']['status'] == 'robocza' and 'wynik' not in odpowiedz
    assert db.session.get(ProductionPackage, pid).loaded_route_id is None


def test_api_cofniecie_zatwierdzenia_migawka_pod_blokada_tras(app, client, monkeypatch):
    """Znaczniki sprawdza zwykły odczyt, więc żądanie zaczyna transakcję od nowa (commit) i pierwszym poleceniem
    nowej bierze blokadę tras — migawka powstaje dopiero pod nią i widzi każdy zacommitowany załadunek
    (panel_api._zapis_pod_blokada)."""
    order, _ = zamowienie_z_paczkami()
    rid = trasa([order]).id
    zdarzenia = []

    def zapytanie(conn, cursor, statement, parameters, context, executemany):
        blokada = klauzula_blokady(context)
        zdarzenia.append(' '.join(statement.split()) + (' ' + blokada if blokada else ''))

    oryginal = db.session.commit
    monkeypatch.setattr(db.session, 'commit', lambda: (zdarzenia.append('COMMIT'), oryginal())[1])
    event.listen(db.engine, 'before_cursor_execute', zapytanie)
    try:
        r = client.post(BASE + '/routes/%d/revert' % rid)
    finally:
        event.remove(db.engine, 'before_cursor_execute', zapytanie)
    assert r.status_code == 200, r.get_data()[:300]
    assert zdarzenia[0] == 'COMMIT'
    assert 'FROM prod_config' in zdarzenia[1] and zdarzenia[1].endswith(' FOR UPDATE')


# --- Kolejność blokad --------------------------------------------------------------------------------

def test_kolejnosc_blokad_zapisu_dostawy(app):
    """Blokada tras → blokada deklaracji → zamówienia (rosnąco) → paczki → pozycje → zapis. SQLite pomija FOR UPDATE,
    więc pilnujemy kolejności zapytań (wiersze blokad rozpoznajemy po kluczu w parametrach)."""
    a, paczki_a = zamowienie_z_paczkami()
    b, paczki_b = zamowienie_z_paczkami()
    t = trasa([b, a])
    zaladuj_wprost(paczki_a + paczki_b, t)
    with Zapytania() as z:
        dostawa.zakoncz_zaladunek(t, worker_id=7)
        db.session.flush()

    def blokada(klucz):
        return next(i for i, (sql, par) in enumerate(z.lista)
                    if 'FROM prod_config' in sql and klucz in tuple(par or ()))

    zamowienia_i = z.pierwsze(blokada_zamowien)
    paczki_i = z.pierwsze(lambda sql: sql.startswith('SELECT') and 'FROM prod_packages' in sql)
    assert (blokada('logistyka_trasy_blokada') < blokada('logistyka_paczki_blokada') < zamowienia_i < paczki_i
            < z.pierwsze(blokada_pozycji) < z.pierwsze(zapis))
    assert list(z.lista[zamowienia_i][1]) == sorted([a.id, b.id])


# --- Decyzje na zablokowanych obiektach (krok 4.4a, przyczyna A) ---------------------------------------

def test_skan_decyduje_na_zablokowanych_obiektach(app, monkeypatch):
    """Ruling P2 (przyczyna A kroku 4.4a): skan trzyma wynik zablokuj (trasa, zamówienia, paczki) do decyzji
    i odpowiedzi. Po odśmieceniu pamięci między blokadami a decyzją nie idzie żaden zwykły odczyt zamówienia
    ani leniwe wczytanie pozycji."""
    order, (p1, _p2) = zamowienie_z_paczkami()
    t = trasa([order])
    route_id, paczka_id = t.id, p1.id
    db.session.expunge_all()     # obiekty testu odłączone: zablokowane przeżyją tylko dzięki referencjom zapisu
    gc.collect()
    odsmiecaj_po_blokadach(monkeypatch)
    route = db.session.get(Route, route_id)
    with Zapytania() as z:
        paczka, zmieniono = dostawa.zaladuj_paczke(route, paczka_id, worker_id=7, teraz=T0)
        db.session.flush()
    assert zwykle_odczyty_stanu(z) == []
    assert zmieniono is True and (paczka.id, paczka.loaded_route_id, paczka.loaded_at) == (paczka_id, route_id, T0)


def test_zakonczenie_decyduje_na_zablokowanych_obiektach(app, monkeypatch):
    """Ruling P2 dla zakończenia załadunku (wiele zamówień, zdjęcia z trasy przez routes.usun_przystanek): po
    odśmieceniu pamięci po blokadach i przy każdym wpisie logu żaden zwykły odczyt zamówienia ani leniwe
    wczytanie pozycji — decyzje i zapisy idą na obiektach z odczytu bieżącego."""
    jedzie, paczki_jedzie = zamowienie_z_paczkami()
    zostaje, _ = zamowienie_z_paczkami()
    anulowane, _ = zamowienie_z_paczkami(statusy=('anulowane',))
    t = trasa([jedzie, zostaje, anulowane])
    zaladuj_wprost(paczki_jedzie, t)
    dostawa.ustaw_zostaje(t, zostaje.id, 'inne')
    db.session.commit()
    route_id, ids = t.id, (jedzie.id, zostaje.id, anulowane.id)
    db.session.expunge_all()
    gc.collect()
    odsmiecaj_po_blokadach(monkeypatch)
    route = db.session.get(Route, route_id)
    with Zapytania() as z:
        trasa_po, usuniete = dostawa.zakoncz_zaladunek(route, worker_id=7, teraz=T0)
        db.session.flush()
    assert zwykle_odczyty_stanu(z) == []
    assert [s.order_id for s in trasa_po.stops] == [ids[0]]
    assert [(u['order_id'], u['reason']) for u in usuniete] == [(ids[1], 'inne'), (ids[2], 'anulowane')]
