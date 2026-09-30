# -*- coding: utf-8 -*-
"""Stanowisko Weryfikacja: rejestracja, lista „Do weryfikacji” z ETag i szczegóły zamówienia
(logistyka etap 4, krok 4.3, spec 8.1–8.2, decyzja Konrada 30.09 o zakresie listy)."""
import itertools
from datetime import date, timedelta

import pytest

from extensions import db
from modules.production.logistics import sposoby as s
from modules.production.logistics.models import Route, RouteStop
from modules.production.logistics.services import weryfikacja
from modules.production.models import ProductionConfig, ProductionDevice, ProductionPackage, get_local_now
from modules.production.services.mobile_api_service import generate_token
from tests.logistyka_fixtures import app, client, zamowienie  # noqa: F401

URL = '/api/mobile/verification/orders'
_licznik = itertools.count(1)
_numery = itertools.count(2100)


def _urzadzenie(stanowisko='verification'):
    device = ProductionDevice(device_id='TEL-%s-%d' % (stanowisko, next(_licznik)),
                              device_name='Telefon', station_code=stanowisko)
    db.session.add(device)
    db.session.commit()
    return device


def _naglowki(device, **inne):
    naglowki = {'Authorization': 'Bearer ' + generate_token(device)}
    naglowki.update(inne)
    return naglowki


def _zam(sposob=s.KURIER, statusy=('spakowane',), spakowano=None, zamkniete=True, **kolumny):
    teraz = get_local_now()
    order = zamowienie(sposob=sposob, statusy=statusy, numer_wewnetrzny=str(next(_numery)),
                       logistics_closed_at=teraz if zamkniete else None, **kolumny)
    for p in order.products:
        if p.current_status != 'anulowane':
            p.packaging_completed_at = spakowano or teraz
    db.session.commit()
    return order


def _trasa(order, dzien, nazwa=u'Rzeszów', status='zatwierdzona'):
    """Trasa z jednym przystankiem = `order` (wzór: tests/test_paczki_panel.py)."""
    trasa = Route(name=nazwa, date_from=dzien, date_to=dzien, status=status)
    db.session.add(trasa)
    db.session.flush()
    db.session.add(RouteStop(route_id=trasa.id, order_id=order.id, position=1))
    db.session.commit()
    return trasa


def _wdrozenie(chwila):
    db.session.add(ProductionConfig(config_key=weryfikacja.KLUCZ_OD, config_type='string',
                                    config_value=chwila.strftime('%Y-%m-%d %H:%M:%S')))
    db.session.commit()


def _numery_listy(client, device):
    r = client.get(URL, headers=_naglowki(device))
    assert r.status_code == 200, r.get_json()
    return [o['internal_order_number'] for o in r.get_json()['orders']]


def test_rejestracja_telefonu_na_weryfikacji(app, client):
    r = client.post('/api/mobile/register', json={'device_id': 'TEL-W-1', 'station_code': 'verification'})
    assert r.status_code == 200 and r.get_json()['station_code'] == 'verification'


def test_inne_stanowisko_nie_widzi_listy(app, client):
    r = client.get(URL, headers=_naglowki(_urzadzenie('packaging')))
    assert r.status_code == 403 and r.get_json()['error'] == 'station_not_allowed'


def test_zakres_listy(app, client):
    teraz = get_local_now()
    _wdrozenie(teraz - timedelta(days=1))
    swieze = _zam()                                                     # kurier, zamknięty, dziś
    stare = _zam(spakowano=teraz - timedelta(days=10))                  # poza oknem 7 dni
    przed_wdrozeniem = _zam(spakowano=teraz - timedelta(days=2))        # w oknie, ale przed wdrożeniem
    otwarte = _zam(sposob=s.TRANSPORT, spakowano=teraz - timedelta(days=20), zamkniete=False)
    problem = _zam(statusy=('dostarczone',), spakowano=teraz - timedelta(days=30),
                   problem_reason='uszkodzenie', problem_at=teraz)
    zweryfikowane = _zam(statusy=('zweryfikowane',), verified_at=teraz)
    w_pakowaniu = _zam(statusy=('spakowane', 'czeka_na_pakowanie'))
    anulowane = _zam(statusy=('anulowane',))

    numery = set(_numery_listy(client, _urzadzenie()))

    assert {swieze.internal_order_number, otwarte.internal_order_number, problem.internal_order_number,
            zweryfikowane.internal_order_number} == numery
    for poza in (stare, przed_wdrozeniem, w_pakowaniu, anulowane):
        assert poza.internal_order_number not in numery
    assert weryfikacja.liczba_do_weryfikacji(teraz) == 2                 # świeże + otwarte (tylko 'spakowane')
    assert weryfikacja.liczba_problemow() == 1


def test_bez_daty_wdrozenia_samo_okno_dni(app, client):
    teraz = get_local_now()
    trzy_dni = _zam(spakowano=teraz - timedelta(days=3))
    assert _numery_listy(client, _urzadzenie()) == [trzy_dni.internal_order_number]
    assert weryfikacja.poczatek_okna(teraz) == teraz - timedelta(days=weryfikacja.DNI_LISTY)


def test_kolejnosc_trasy_wg_daty_potem_spakowanie(app, client):
    teraz = get_local_now()
    pozniej_spakowane = _zam(spakowano=teraz - timedelta(hours=1))
    wczesniej_spakowane = _zam(spakowano=teraz - timedelta(hours=5))
    na_trasie_pozniej = _zam(sposob=s.TRANSPORT, zamkniete=False)
    na_trasie_wczesniej = _zam(sposob=s.TRANSPORT, zamkniete=False)
    _trasa(na_trasie_pozniej, date(2026, 10, 9))
    _trasa(na_trasie_wczesniej, date(2026, 10, 2))
    assert _numery_listy(client, _urzadzenie()) == [
        na_trasie_wczesniej.internal_order_number, na_trasie_pozniej.internal_order_number,
        wczesniej_spakowane.internal_order_number, pozniej_spakowane.internal_order_number]


def test_zamowienie_na_liscie(app, client):
    teraz = get_local_now()
    order = _zam(sposob=s.TRANSPORT, zamkniete=False, spakowano=teraz, packages_declared_at=teraz,
                 problem_reason='etykieta', problem_note=u'nieczytelna', problem_at=teraz,
                 problem_by_worker_id=4)
    _trasa(order, date(2026, 10, 2), nazwa=u'Kraków + Tarnów')
    p1 = ProductionPackage(order_id=order.id, seq=1, kind='paczka', declared_at=teraz,
                           verified_at=teraz, verified_method='skan', verified_by_worker_id=4)
    p2 = ProductionPackage(order_id=order.id, seq=2, kind='paczka', declared_at=teraz)
    db.session.add_all([p1, p2])
    db.session.commit()

    wiersz = client.get(URL, headers=_naglowki(_urzadzenie())).get_json()['orders'][0]

    assert (wiersz['internal_order_number'], wiersz['stage'], wiersz['stage_label']) == \
        (order.internal_order_number, 'spakowane', u'Spakowane — czeka na weryfikację')
    assert (wiersz['packages_total'], wiersz['packages_verified'], wiersz['no_packages']) == (2, 1, False)
    assert [(p['code'], p['verified'], p['verified_method']) for p in wiersz['packages']] == \
        [(p1.kod, True, 'skan'), (p2.kod, False, None)]
    assert wiersz['transport']['mode'] == 'wlasny' and wiersz['transport']['trip_name'] == u'Kraków + Tarnów'
    assert wiersz['problem'] == {'reason': 'etykieta', 'reason_label': 'Etykieta', 'note': u'nieczytelna',
                                 'at': teraz.isoformat(), 'by_worker_id': 4}
    assert wiersz['packed_at'] == teraz.isoformat() and wiersz['verified_at'] is None


def test_bez_paczek_to_plakietka(app, client):
    order = _zam()
    wiersz = client.get(URL, headers=_naglowki(_urzadzenie())).get_json()['orders'][0]
    assert wiersz['internal_order_number'] == order.internal_order_number
    assert (wiersz['no_packages'], wiersz['packages']) == (True, [])


def test_etag_i_304(app, client):
    order = _zam()
    device = _urzadzenie()
    pierwsza = client.get(URL, headers=_naglowki(device))
    etag = pierwsza.headers['ETag']
    assert client.get(URL, headers=_naglowki(device, **{'If-None-Match': etag})).status_code == 304
    order.products[0].updated_at = get_local_now() + timedelta(seconds=5)
    db.session.commit()
    druga = client.get(URL, headers=_naglowki(device, **{'If-None-Match': etag}))
    assert druga.status_code == 200 and druga.headers['ETag'] != etag


def test_szczegoly_z_pozycjami(app, client):
    order = _zam(statusy=('spakowane', 'anulowane'))
    r = client.get(URL + '/' + order.internal_order_number, headers=_naglowki(_urzadzenie()))
    assert r.status_code == 200 and 'no-store' in r.headers['Cache-Control']
    pozycje = r.get_json()['order']['items']
    assert [(p['status'], p['status_label']) for p in pozycje] == \
        [('spakowane', u'Spakowane — czeka na weryfikację'), ('anulowane', 'Anulowane')]
    brak = client.get(URL + '/999999', headers=_naglowki(_urzadzenie()))
    assert brak.status_code == 404 and brak.get_json()['error'] == 'order_not_found'
