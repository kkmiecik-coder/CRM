# -*- coding: utf-8 -*-
"""Podpowiedź paczek w kolejce pakowania i odczyty paczek (logistyka etap 4, krok 4.2, spec 7.1)."""
from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest

from extensions import db
from modules.production.logistics import sposoby as s
from modules.production.logistics.services import paczki, routes
from modules.production.models import ProductionDevice, ProductionPackage
from modules.production.routers import mobile_api
from modules.production.services.mobile_api_service import generate_token, serialize_order
from tests.logistyka_fixtures import app, client, zamowienie  # noqa: F401

PACZKA = {'kind': 'paczka', 'count': 1, 'pallet_type': None}
PALETA = {'kind': 'paleta', 'count': 1, 'pallet_type': 'eur'}


def _poz(m3, ilosc=1, status='czeka_na_pakowanie', order_id=1):
    return SimpleNamespace(volume_m3=Decimal(str(m3)) if m3 is not None else None,
                           quantity=ilosc, current_status=status, order_id=order_id)


def _token(app, stanowisko='packaging'):
    device = ProductionDevice(device_id='TAB-podpowiedz-%s' % stanowisko,
                              device_name='Tablet', station_code=stanowisko)
    db.session.add(device)
    db.session.commit()
    return generate_token(device)


def _paczka(order, seq, voided=False, **kolumny):
    p = ProductionPackage(order_id=order.id, seq=seq, kind=kolumny.pop('kind', 'paczka'),
                          declared_at=datetime(2026, 9, 30, 10, 0),
                          voided_at=datetime(2026, 9, 30, 11, 0) if voided else None, **kolumny)
    db.session.add(p)
    db.session.commit()
    return p


@pytest.mark.parametrize('pozycje, oczekiwane', [
    ([_poz(0.024, 2)], dict(PACZKA, weight_kg=38)),              # 0,048 m³ × 800 = 38,4 kg
    ([_poz(0.373)], dict(PALETA, weight_kg=298)),                # wzór ze specu 7.1
    ([_poz(0.05)], dict(PACZKA, weight_kg=40)),                  # dokładnie próg — jeszcze paczka
    ([_poz(0.0513)], dict(PALETA, weight_kg=41)),
    ([_poz(0.3, status='anulowane'), _poz(0.01)], dict(PACZKA, weight_kg=8)),
    ([_poz(None, 3)], dict(PACZKA, weight_kg=0)),                # pozycja bez objętości
    ([], dict(PACZKA, weight_kg=0)),
])
def test_podpowiedz_pakowania(pozycje, oczekiwane):
    assert paczki.podpowiedz_pakowania(pozycje) == oczekiwane


def test_podpowiedzi_zamowien_grupuje_po_zamowieniu():
    mapa = paczki.podpowiedzi_zamowien([_poz(0.03, status='spakowane', order_id=1),
                                        _poz(0.01, order_id=2), _poz(0.03, order_id=1)])
    assert mapa == {1: dict(PALETA, weight_kg=48), 2: dict(PACZKA, weight_kg=8)}


def test_kolejka_pakowania_niesie_podpowiedz_calego_zamowienia(app, client):
    # 2 pozycje × 0,024 m³ × 2 szt. = 0,096 m³ = 77 kg — liczy się też pozycja już spakowana
    order = zamowienie(sposob=s.KURIER, statusy=('spakowane', 'czeka_na_pakowanie'))
    dane = client.get('/api/mobile/stations/packaging/orders',
                      headers={'Authorization': 'Bearer ' + _token(app)}).get_json()
    pozycje = [o for o in dane['orders'] if o['internal_order_number'] == order.internal_order_number]
    assert len(pozycje) == 2
    assert all(o['packing_hint'] == dict(PALETA, weight_kg=77) for o in pozycje)


def test_etag_kolejki_niesie_ksztalt_4(app, client):
    zamowienie(sposob=s.KURIER, statusy=('czeka_na_pakowanie',))
    r = client.get('/api/mobile/stations/packaging/orders',
                   headers={'Authorization': 'Bearer ' + _token(app)})
    assert mobile_api.KSZTALT_ODPOWIEDZI_KOLEJKI == 4
    assert r.headers['ETag'].endswith(':4"')


def test_wyszukiwarka_niesie_podpowiedz(app, client):
    order = zamowienie(sposob=s.KURIER, statusy=('spakowane',))
    order.products[0].volume_m3 = 0.01
    db.session.commit()
    dane = client.get('/api/mobile/orders/search', query_string={'q': order.client_name},
                      headers={'Authorization': 'Bearer ' + _token(app)}).get_json()
    trafienie = next(o for o in dane['orders'] if o['internal_order_number'] == order.internal_order_number)
    assert trafienie['packing_hint'] == dict(PACZKA, weight_kg=16)


def test_pojedyncza_pozycja_liczy_podpowiedz_z_calego_zamowienia(app):
    order = zamowienie(sposob=s.KURIER, statusy=('spakowane', 'czeka_na_pakowanie', 'anulowane'))
    dane = serialize_order(order.products[1], station_code='packaging')
    assert dane['packing_hint'] == dict(PALETA, weight_kg=77)     # anulowana się nie liczy


def test_trasy_licza_ta_sama_gestoscia():
    assert routes.WAGA_KG_NA_M3 == s.WAGA_KG_NA_M3


def test_aktualne_paczki_bez_uniewaznionych_po_numerach(app):
    order = zamowienie(statusy=('spakowane',))
    _paczka(order, 1, voided=True)
    druga, pierwsza = _paczka(order, 2), _paczka(order, 1)
    assert [p.id for p in paczki.aktualne_paczki(order.id)] == [pierwsza.id, druga.id]
    assert [p.id for p in paczki.aktualne_paczki(order.id, do_zapisu=True)] == [pierwsza.id, druga.id]
    inne = zamowienie(statusy=('spakowane',))
    _paczka(inne, 1)
    mapa = paczki.aktualne_paczki_zamowien([order.id, inne.id, 999999])
    assert [p.id for p in mapa[order.id]] == [pierwsza.id, druga.id]
    assert len(mapa[inne.id]) == 1 and 999999 not in mapa
    assert paczki.aktualne_paczki_zamowien([]) == {}


def test_serializuj_paczke(app):
    p = _paczka(zamowienie(statusy=('spakowane',)), 1, kind='paleta', pallet_type='eur',
                length_cm=120, width_cm=80, label_print_count=2,
                label_printed_at=datetime(2026, 9, 30, 12, 5))
    assert paczki.serializuj_paczke(p) == {
        'id': p.id, 'code': 'P-%d' % p.id, 'seq': 1, 'kind': 'paleta', 'pallet_type': 'eur',
        'length_cm': 120, 'width_cm': 80, 'label_print_count': 2,
        'label_printed_at': '2026-09-30T12:05:00'}
