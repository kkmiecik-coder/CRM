# -*- coding: utf-8 -*-
"""Cofnięcie sprawdzenia jednej paczki: POST /api/mobile/verification/packages/<id>/unverify
(logistyka etap 4, krok 4.3, spec 4.5 i 8.3)."""
import itertools
from datetime import datetime, timedelta

import pytest

from extensions import db
from modules.production.logistics import sposoby as s
from modules.production.logistics.models import LogisticsLog
from modules.production.logistics.services import weryfikacja
from modules.production.models import (ProcessedMobileOperation, ProductionDevice, ProductionOrder,
                                       ProductionPackage, get_local_now)
from modules.production.services.mobile_api_service import generate_token
from tests.logistyka_fixtures import app, client, pracownik, zamowienie  # noqa: F401
from tests.weryfikacja_pomocnicze import migawka_pozycji

BASE = '/api/mobile/verification'
T0 = datetime(2026, 10, 1, 8, 0)
_licznik = itertools.count(1)
_numery = itertools.count(3600)


@pytest.fixture(autouse=True)
def bez_statusow_base(monkeypatch):
    monkeypatch.setattr(
        'modules.production.services.baselinker_status_sync.schedule_after_station_complete',
        lambda *a, **k: None)


def _urzadzenie(stanowisko='verification'):
    device = ProductionDevice(device_id='TEL-%s-%d' % (stanowisko, next(_licznik)),
                              device_name='Telefon', station_code=stanowisko)
    db.session.add(device)
    db.session.commit()
    return device


def _naglowki(device, kto=None, op_id=None):
    naglowki = {'Authorization': 'Bearer ' + generate_token(device),
                'X-Operation-Id': op_id or 'op-cof-%d' % next(_licznik)}
    if kto is not None:
        naglowki['X-Worker-Ids'] = str(kto.id)
    return naglowki


def _z_paczkami(statusy=('spakowane', 'spakowane'), n=2, sprawdzone=(), sposob=s.KURIER, spakowano=None,
                kto=None, **kolumny):
    """Zamówienie z `n` paczkami; `sprawdzone` = numery (seq) paczek już sprawdzonych skanem."""
    order = zamowienie(sposob=sposob, statusy=statusy, numer_wewnetrzny=str(next(_numery)),
                       packages_declared_at=T0, **kolumny)
    # „Teraz”, nie stała data: zakres listy Weryfikacji (warunek_zakresu) liczy zamówienia zamknięte
    # w Logistyce od packaging_completed_at w oknie 7 dni — stała T0 wypadłaby z niego za tydzień.
    for p in order.products:
        p.packaging_completed_at = spakowano or get_local_now()
    lista = [ProductionPackage(order_id=order.id, seq=i, kind='paczka', declared_at=T0,
                               verified_at=T0 if i in sprawdzone else None,
                               verified_method='skan' if i in sprawdzone else None,
                               verified_by_worker_id=kto.id if i in sprawdzone and kto else None)
             for i in range(1, n + 1)]
    db.session.add_all(lista)
    db.session.commit()
    return order, lista


def _stary_kurier(statusy=('zweryfikowane', 'zweryfikowane'), dni=10, kto=None, **kolumny):
    """Kurier zamknięty w Logistyce, spakowany `dni` dni temu (okno listy to 7), obie paczki sprawdzone."""
    dawno = get_local_now() - timedelta(days=dni)
    zweryfikowane = statusy[0] == 'zweryfikowane'
    return _z_paczkami(statusy=statusy, sprawdzone=(1, 2), spakowano=dawno, logistics_closed_at=dawno, kto=kto,
                       verified_at=T0 if zweryfikowane else None, **kolumny)


def _verify(client, paczka, device, kto):
    return client.post('%s/packages/%d/verify' % (BASE, paczka.id), json={'method': 'skan'},
                       headers=_naglowki(device, kto))


def _unverify(client, paczka, device, kto, op_id=None):
    return client.post('%s/packages/%d/unverify' % (BASE, paczka.id), headers=_naglowki(device, kto, op_id))


def _wpisy(order, akcja='weryfikacja_cofnieta'):
    return LogisticsLog.query.filter_by(order_id=order.id, action=akcja).all()


def _stan(order):
    """Stan zamówienia i jego paczek z bazy (po wygaszeniu sesji) — do porównania „przed” i „po”."""
    db.session.expire_all()
    o = ProductionOrder.query.get(order.id)
    return ([p.current_status for p in o.products], o.verified_at, o.verified_by_worker_id, o.problem_at,
            o.logistics_closed_at,
            [(x.verified_at, x.verified_by_worker_id, x.verified_method)
             for x in ProductionPackage.query.filter_by(order_id=order.id).order_by(ProductionPackage.seq)])


def test_niesprawdzona_paczka_200_bez_zmian_i_bez_logu(app, client):
    kto, device = pracownik(), _urzadzenie()
    order, (p1, p2) = _z_paczkami(sprawdzone=(2,), kto=kto)
    przed = _stan(order)

    r = _unverify(client, p1, device, kto)
    assert r.status_code == 200, r.get_json()
    dane = r.get_json()
    assert (dane['changed'], dane['order_verified']) == (False, False)
    assert dane['message'] == u'P-%d nie była sprawdzona (1 / 2).' % p1.id
    assert dane['package']['id'] == p1.id and dane['package']['verified'] is False
    assert dane['order']['packages_verified'] == 1
    assert _stan(order) == przed
    assert _wpisy(order) == []


def test_jedna_z_dwoch_sprawdzonych_na_niezweryfikowanym_zamowieniu(app, client):
    kto, device = pracownik(), _urzadzenie()
    order, (p1, p2) = _z_paczkami(sprawdzone=(1, 2), kto=kto)

    r = _unverify(client, p1, device, kto)
    assert r.status_code == 200, r.get_json()
    dane = r.get_json()
    assert (dane['changed'], dane['order_verified']) == (True, False)
    assert dane['message'] == u'P-%d — cofnięto sprawdzenie (1 / 2).' % p1.id
    assert dane['package']['id'] == p1.id
    assert (dane['package']['verified'], dane['package']['verified_at'], dane['package']['verified_method']) \
        == (False, None, None)
    assert dane['order']['packages_verified'] == 1 and dane['order']['stage'] == 'spakowane'

    db.session.expire_all()
    a, b = ProductionPackage.query.get(p1.id), ProductionPackage.query.get(p2.id)
    assert (a.verified_at, a.verified_by_worker_id, a.verified_method) == (None, None, None)
    assert (b.verified_at, b.verified_by_worker_id, b.verified_method) == (T0, kto.id, 'skan')   # druga bez zmian
    assert [p.current_status for p in ProductionOrder.query.get(order.id).products] == ['spakowane', 'spakowane']
    wpis, = _wpisy(order)
    assert (wpis.old_value, wpis.new_value) == (u'P-%d sprawdzona' % p1.id, u'P-%d niesprawdzona' % p1.id)
    assert wpis.note == u'cofnięto sprawdzenie paczki'
    assert (wpis.worker_id, wpis.device_id) == (kto.id, device.id)


def test_cofniecie_na_zweryfikowanym_zamowieniu_a_potem_ponowny_skan(app, client):
    kto, device = pracownik(), _urzadzenie()
    order, (p1, p2) = _z_paczkami(logistics_closed_at=T0)
    _verify(client, p1, device, kto)
    assert _verify(client, p2, device, kto).get_json()['order_verified'] is True
    o = ProductionOrder.query.get(order.id)
    assert o.verified_at is not None and o.verified_by_worker_id == kto.id

    r = _unverify(client, p2, device, kto)
    assert r.status_code == 200, r.get_json()
    dane = r.get_json()
    assert (dane['changed'], dane['order_verified']) == (True, False)
    assert dane['message'] == u'P-%d — cofnięto sprawdzenie. Zamówienie %s wraca do sprawdzania (1 / 2).' % (
        p2.id, order.internal_order_number)
    assert dane['order']['stage'] == 'spakowane' and dane['order']['verified_at'] is None
    assert dane['order']['packages_verified'] == 1

    db.session.expire_all()
    o = ProductionOrder.query.get(order.id)
    assert [p.current_status for p in o.products] == ['spakowane', 'spakowane']
    assert (o.verified_at, o.verified_by_worker_id) == (None, None)
    assert o.logistics_closed_at == T0                                # kurier zostaje zamknięty
    assert ProductionPackage.query.get(p1.id).verified_at is not None      # druga paczka nadal sprawdzona
    assert ProductionPackage.query.get(p2.id).verified_at is None
    wpis, = _wpisy(order)
    assert wpis.note == u'cofnięto sprawdzenie paczki, zamówienie wraca do sprawdzania'
    assert (wpis.old_value, wpis.new_value) == (u'P-%d sprawdzona' % p2.id, u'P-%d niesprawdzona' % p2.id)

    ponownie = _verify(client, p2, device, kto)                       # ponowny skan domyka zamówienie
    assert ponownie.status_code == 200, ponownie.get_json()
    assert (ponownie.get_json()['changed'], ponownie.get_json()['order_verified']) == (True, True)
    db.session.expire_all()
    o = ProductionOrder.query.get(order.id)
    assert [p.current_status for p in o.products] == ['zweryfikowane', 'zweryfikowane']
    assert o.verified_at is not None
    assert len(_wpisy(order, 'weryfikacja')) == 2 and len(_wpisy(order)) == 1


def test_cofniecie_decyduje_na_biezacym_stanie_pozycji(app, client, monkeypatch):
    """Obiekty w sesji pokazują pozycje 'spakowane' (migawka), baza ma już 'zweryfikowane': zamówienie
    było zweryfikowane, więc cofnięcie ma je cofnąć (odczyt bieżący, nie migawka MySQL)."""
    kto, device = pracownik(), _urzadzenie()
    order, (p1, _p2) = _z_paczkami(statusy=('zweryfikowane', 'zweryfikowane'), sprawdzone=(1, 2), kto=kto,
                                   verified_at=T0)
    migawka_pozycji(monkeypatch, weryfikacja, 'cofnij_sprawdzenie_paczki', w_pamieci='spakowane')
    r = _unverify(client, p1, device, kto)
    assert r.status_code == 200, r.get_json()
    assert (r.get_json()['changed'], r.get_json()['order_verified']) == (True, False)
    assert u'wraca do sprawdzania' in r.get_json()['message']
    db.session.expire_all()
    o = ProductionOrder.query.get(order.id)
    assert [p.current_status for p in o.products] == ['spakowane', 'spakowane'] and o.verified_at is None
    assert _wpisy(order)[0].note.endswith(u'zamówienie wraca do sprawdzania')


def test_bez_zmiany_order_verified_to_stan_pozycji(app, client):
    """Bez zmiany `order_verified` jest prawdą tylko wtedy, gdy wszystkie aktywne pozycje są zweryfikowane."""
    kto, device = pracownik(), _urzadzenie()
    order, (_p1, p2) = _z_paczkami(statusy=('zweryfikowane', 'zweryfikowane'), sprawdzone=(1,), kto=kto,
                                   verified_at=T0)
    r = _unverify(client, p2, device, kto)                  # p2 niesprawdzona, pozycje zweryfikowane
    assert r.status_code == 200 and (r.get_json()['changed'], r.get_json()['order_verified']) == (False, True)
    assert _wpisy(order) == []


def test_paczka_niewazna_409_package_void(app, client):
    kto, device = pracownik(), _urzadzenie()
    order, (p1, _p2) = _z_paczkami(sprawdzone=(1, 2), kto=kto)
    p1.voided_at = T0
    db.session.commit()
    przed = _stan(order)
    r = _unverify(client, p1, device, kto)
    assert (r.status_code, r.get_json()['error']) == (409, 'package_void')
    assert r.get_json()['message'] == u'Etykieta nieaktualna — paczki zadeklarowano ponownie.'
    assert _stan(order) == przed
    assert ProcessedMobileOperation.query.count() == 0           # 409 niezapamiętane (BLEDY_DO_PONOWIENIA)
    assert _wpisy(order) == []


def test_brak_paczki_404_brak_pracownika_400_inne_stanowisko_403(app, client):
    kto = pracownik()
    order, (p1, _p2) = _z_paczkami(sprawdzone=(1,), kto=kto)
    brak = client.post(BASE + '/packages/999999/unverify', headers=_naglowki(_urzadzenie(), kto))
    assert (brak.status_code, brak.get_json()['error']) == (404, 'package_not_found')
    assert brak.get_json()['message'] == u'Nie ma paczki P-999999.'
    bez = client.post('%s/packages/%d/unverify' % (BASE, p1.id), headers=_naglowki(_urzadzenie()))
    assert (bez.status_code, bez.get_json()['error']) == (400, 'worker_required')
    obce = _unverify(client, p1, _urzadzenie('packaging'), kto)
    assert (obce.status_code, obce.get_json()['error']) == (403, 'station_not_allowed')
    assert ProductionPackage.query.get(p1.id).verified_at is not None        # nic nie ruszone
    assert _wpisy(order) == []


def test_zamowienie_spoza_listy_409_order_status_niezapamietane(app, client):
    kto, device = pracownik(), _urzadzenie()
    order, (p1, _p2) = _stary_kurier(kto=kto)
    przed = _stan(order)
    r = _unverify(client, p1, device, kto)
    assert (r.status_code, r.get_json()['error']) == (409, 'order_status'), r.get_json()
    assert u'poza listą Weryfikacji' in r.get_json()['message']
    assert order.internal_order_number in r.get_json()['message']
    assert _stan(order) == przed
    assert ProcessedMobileOperation.query.count() == 0           # 409 niezapamiętane (BLEDY_DO_PONOWIENIA)
    assert _wpisy(order) == []


def test_zamowienie_spoza_listy_niesprawdzona_paczka_to_200_bez_zmian(app, client):
    """Zakres listy dotyczy zapisu: cofnięcie, które niczego by nie zmieniło, daje 200 także poza listą."""
    kto, device = pracownik(), _urzadzenie()
    order, (p1, _p2) = _stary_kurier(statusy=('spakowane', 'spakowane'))
    p1.verified_at = p1.verified_method = None
    db.session.commit()
    przed = _stan(order)
    r = _unverify(client, p1, device, kto)
    assert r.status_code == 200 and r.get_json()['changed'] is False
    assert _stan(order) == przed and _wpisy(order) == []


@pytest.mark.parametrize('status, fragment', [('dostarczone', u'już dostarczone'), ('zaladowane', u'już załadowane')])
def test_zamowienie_dostarczone_albo_zaladowane_409_order_status(app, client, status, fragment):
    kto, device = pracownik(), _urzadzenie()
    order, (p1, _p2) = _z_paczkami(statusy=(status, status), sprawdzone=(1, 2), kto=kto, verified_at=T0)
    przed = _stan(order)
    r = _unverify(client, p1, device, kto)
    assert (r.status_code, r.get_json()['error']) == (409, 'order_status')
    assert fragment in r.get_json()['message']
    assert _stan(order) == przed
    assert ProcessedMobileOperation.query.count() == 0
    assert _wpisy(order) == []


def test_pozycja_wrocila_do_produkcji_409_order_not_packed(app, client, monkeypatch):
    """Pozycja wróciła do produkcji po migawce żądania (stan „w tle” spoza ORM): odczyt bieżący odmawia."""
    kto, device = pracownik(), _urzadzenie()
    order, (p1, _p2) = _z_paczkami(sprawdzone=(1, 2), kto=kto)
    migawka_pozycji(monkeypatch, weryfikacja, 'cofnij_sprawdzenie_paczki',
                    w_pamieci='spakowane', w_bazie='czeka_na_pakowanie')
    r = _unverify(client, p1, device, kto)
    assert (r.status_code, r.get_json()['error']) == (409, 'order_not_packed')
    assert ProcessedMobileOperation.query.count() == 0
    assert _wpisy(order) == []


def test_otwarty_problem_nie_blokuje_cofniecia(app, client):
    kto, device = pracownik(), _urzadzenie()
    order, (p1, p2) = _z_paczkami(sprawdzone=(1, 2), kto=kto, problem_reason='uszkodzenie', problem_at=T0)
    r = _unverify(client, p1, device, kto)
    assert r.status_code == 200, r.get_json()
    assert r.get_json()['changed'] is True
    db.session.expire_all()
    assert ProductionPackage.query.get(p1.id).verified_at is None
    assert ProductionPackage.query.get(p2.id).verified_at is not None
    o = ProductionOrder.query.get(order.id)
    assert (o.problem_reason, o.problem_at) == ('uszkodzenie', T0)           # problem zostaje otwarty
    assert len(_wpisy(order)) == 1


def test_powtorka_z_tym_samym_operation_id_ta_sama_odpowiedz_i_jeden_wpis(app, client):
    kto, device = pracownik(), _urzadzenie()
    order, (p1, _p2) = _z_paczkami(sprawdzone=(1, 2), kto=kto)
    pierwsza = _unverify(client, p1, device, kto, op_id='op-cof-powtorka')
    druga = _unverify(client, p1, device, kto, op_id='op-cof-powtorka')
    assert pierwsza.status_code == 200 and druga.status_code == 200
    assert druga.get_json() == pierwsza.get_json() and pierwsza.get_json()['changed'] is True
    assert len(_wpisy(order)) == 1


def test_drugie_cofniecie_z_nowym_operation_id_jest_bez_zmian(app, client):
    kto, device = pracownik(), _urzadzenie()
    order, (p1, _p2) = _z_paczkami(sprawdzone=(1, 2), kto=kto)
    assert _unverify(client, p1, device, kto).get_json()['changed'] is True
    drugie = _unverify(client, p1, device, kto)              # inny X-Operation-Id
    assert drugie.status_code == 200
    assert (drugie.get_json()['changed'], drugie.get_json()['order_verified']) == (False, False)
    assert drugie.get_json()['message'] == u'P-%d nie była sprawdzona (1 / 2).' % p1.id
    assert len(_wpisy(order)) == 1
