# -*- coding: utf-8 -*-
"""Etykiety paczek z danych zamówienia (logistyka etap 4, krok 4.2, spec 6.3 i 7.2)."""
from datetime import date, datetime
from types import SimpleNamespace

import pytest

from extensions import db
from modules.production.logistics import sposoby as s
from modules.production.logistics.models import Route, RouteStop
from modules.production.logistics.services import paczki_druk
from modules.production.models import LabelPrintJob, ProductionConfiguration, ProductionPackage
from modules.production.services import print_queue_service as pqs
from tests.logistyka_fixtures import app, zamowienie  # noqa: F401

AKTOR = {'type': 'device', 'id': 'TAB-1'}


@pytest.fixture()
def sygnaly(monkeypatch):
    wyslane = []
    monkeypatch.setattr(pqs.realtime_service, 'publish_print_signal',
                        lambda n: wyslane.append(n) or True)
    return wyslane


def _trasa(nazwa=u'Rzeszów', od=date(2026, 10, 7)):
    return SimpleNamespace(name=nazwa, date_from=od)


def _paczka(order, seq=1, **kolumny):
    p = ProductionPackage(order_id=order.id, seq=seq, kind=kolumny.pop('kind', 'paczka'),
                          declared_at=datetime(2026, 9, 30, 10, 0), **kolumny)
    db.session.add(p)
    db.session.flush()
    return p


@pytest.mark.parametrize('sposob, trasa, napis', [
    (s.KURIER, None, 'KURIER'),
    (s.ODBIOR, None, 'ODBIOR OSOBISTY'),
    (s.TRANSPORT, None, 'TRANSPORT WOODPOWER'),
    (None, None, 'NIE USTAWIONO'),
    ('cos_innego', None, 'NIE USTAWIONO'),
    (s.TRANSPORT, _trasa(), 'TRASA: Rzeszow 07.10'),
    (s.KURIER, _trasa(), 'KURIER'),                            # trasa liczy się tylko dla transportu
    (s.TRANSPORT, _trasa(u'Kraków + Tarnów + Nowy Sącz'), 'TRASA: Krakow + T... 07.10'),
    (s.TRANSPORT, _trasa(u'^XA~JA Łódź'), 'TRASA: XA JA Lodz 07.10'),
])
def test_napis_sposobu(sposob, trasa, napis):
    wynik = paczki_druk.napis_sposobu(SimpleNamespace(override_delivery_method=sposob), trasa)
    assert wynik == napis
    assert len(wynik) <= 26 and all(ord(z) < 128 for z in wynik)


def test_dane_etykiety_z_zamowienia(app):
    order = zamowienie(sposob=s.KURIER, statusy=('spakowane', 'spakowane', 'anulowane'),
                       delivery_fullname='Janusz Testowy', delivery_company='TESTBUD',
                       client_order_number='1234/2026')
    konfiguracja = ProductionConfiguration(species=u'dąb', technology='lity', wood_class='A/B')
    db.session.add(konfiguracja)
    db.session.flush()
    pierwsza, druga, _anulowana = sorted(order.products, key=lambda p: p.product_sequence_in_order)
    pierwsza.configuration = konfiguracja
    pierwsza.parsed_length_cm, pierwsza.parsed_width_cm, pierwsza.parsed_thickness_cm = 97, 29, 4
    pierwsza.parsed_finish_type, pierwsza.parsed_finish_gloss = 'lakierowane', 'matowy'
    pierwsza.packaging_completed_at = datetime(2026, 9, 29, 15, 0)
    druga.packaging_completed_at = datetime(2026, 9, 30, 9, 0)
    paczka = _paczka(order, seq=2, kind='paleta', pallet_type='niestandardowa',
                     length_cm=150, width_cm=100)
    db.session.commit()

    dane = paczki_druk.dane_etykiety(order, paczka, 3, 'KURIER')
    assert (dane.numer_zamowienia, dane.kod_paczki, dane.rodzaj, dane.numer, dane.z_ilu, dane.sposob) == \
        (order.internal_order_number, paczka.kod, 'paleta', 2, 3, 'KURIER')
    assert dane.odbiorca == 'Janusz Testowy'
    assert (dane.typ_palety, dane.dlugosc_cm, dane.szerokosc_cm) == ('niestandardowa', 150, 100)
    assert len(dane.pozycje) == 2                                  # anulowana nie trafia na etykietę
    p1 = dane.pozycje[0]
    assert (p1.gatunek, p1.technologia, p1.klasa, p1.wykonczenie, p1.ilosc) == \
        (u'dąb', 'lity', 'A/B', 'LAK MAT', 2)
    assert (p1.dlugosc_cm, p1.szerokosc_cm, p1.grubosc_cm) == (97.0, 29.0, 4.0)
    assert (dane.pozycje[1].gatunek, dane.pozycje[1].wykonczenie) == ('', None)   # bez konfiguracji, surowe
    assert dane.m3 == pytest.approx(0.096)                         # 2 × 0,024 m³ × 2 szt.
    assert dane.spakowano == date(2026, 9, 30)
    assert (dane.base_id, dane.zamowienie_klienta) == (order.baselinker_order_id, '1234/2026')


def test_konfiguracja_unknown_nie_trafia_na_etykiete(app):
    order = zamowienie(statusy=('spakowane',))
    order.products[0].configuration = ProductionConfiguration(
        species='unknown', technology='unknown', wood_class='unknown')
    paczka = _paczka(order)
    dane = paczki_druk.dane_etykiety(order, paczka, 1, 'KURIER')
    assert (dane.pozycje[0].gatunek, dane.pozycje[0].technologia, dane.pozycje[0].klasa) == ('', '', '')


@pytest.mark.parametrize('kolumny, odbiorca', [
    ({'delivery_fullname': 'Jan Nowak', 'delivery_company': 'Firma'}, 'Jan Nowak'),
    ({'delivery_fullname': '', 'delivery_company': 'TESTBUD'}, 'TESTBUD'),
    ({'delivery_fullname': None, 'delivery_company': None}, 'KLIENT'),
])
def test_odbiorca_osoba_firma_klient(app, kolumny, odbiorca):
    order = zamowienie(statusy=('spakowane',), **kolumny)
    dane = paczki_druk.dane_etykiety(order, _paczka(order), 1, 'KURIER')
    assert dane.odbiorca == (order.client_name if odbiorca == 'KLIENT' else odbiorca)


def test_paleta_eur_bez_wymiaru_na_danych(app):
    order = zamowienie(statusy=('spakowane',))
    paczka = _paczka(order, kind='paleta', pallet_type='eur', length_cm=120, width_cm=80)
    dane = paczki_druk.dane_etykiety(order, paczka, 1, 'KURIER')
    assert (dane.typ_palety, dane.dlugosc_cm, dane.szerokosc_cm) == ('eur', None, None)


def test_drukuj_etykiety_kolejkuje_na_drukarke_paczek(app, sygnaly):
    order = zamowienie(sposob=s.KURIER, statusy=('spakowane',))
    lista = [_paczka(order, seq=1), _paczka(order, seq=2)]
    teraz = datetime(2026, 9, 30, 10, 5)
    with app.test_request_context():
        assert paczki_druk.drukuj_etykiety(order, lista, 2, 'packaging', AKTOR, teraz) == 2
        db.session.commit()
        assert sygnaly == []                        # sygnał dopiero przez wyslij_zaplanowany_sygnal
        assert pqs.wyslij_zaplanowany_sygnal() == 2
    assert sygnaly == [2]
    zadania = LabelPrintJob.query.order_by(LabelPrintJob.id).all()
    assert [(z.printer, z.package_id, z.short_product_id, z.station_code, z.baselinker_order_id)
            for z in zadania] == [('wysylka', p.id, p.kod, 'packaging', order.baselinker_order_id)
                                  for p in lista]
    assert '^FDLA,%s^FS' % lista[0].kod in zadania[0].zpl_payload
    assert '^FR^FD1 / 2^FS' in zadania[0].zpl_payload and '^FR^FD2 / 2^FS' in zadania[1].zpl_payload
    assert '^FR^FDKURIER^FS' in zadania[1].zpl_payload
    assert all((p.label_printed_at, p.label_print_count, p.label_delivery_text) == (teraz, 1, 'KURIER')
               for p in lista)


def test_trasa_wykonana_nie_trafia_na_etykiete(app, sygnaly):
    order = zamowienie(sposob=s.TRANSPORT, statusy=('spakowane',))
    trasa = Route(name=u'Rzeszów', date_from=date(2026, 10, 7), date_to=date(2026, 10, 7),
                  status='wykonana')
    db.session.add(trasa)
    db.session.flush()
    db.session.add(RouteStop(route_id=trasa.id, order_id=order.id, position=1))
    paczka = _paczka(order)
    paczki_druk.drukuj_etykiety(order, [paczka], 1, 'packaging', AKTOR, datetime(2026, 9, 30, 10, 5))
    assert paczka.label_delivery_text == 'TRANSPORT WOODPOWER'
    trasa.status = 'zatwierdzona'
    db.session.flush()
    paczki_druk.drukuj_etykiety(order, [paczka], 1, 'packaging', AKTOR, datetime(2026, 9, 30, 10, 6))
    assert (paczka.label_delivery_text, paczka.label_print_count) == ('TRASA: Rzeszow 07.10', 2)


def test_sygnal_po_commicie_raz_na_zadanie(app, sygnaly):
    with app.test_request_context():
        pqs.zaplanuj_sygnal_po_commicie(2)
        pqs.zaplanuj_sygnal_po_commicie(1)
        assert pqs.wyslij_zaplanowany_sygnal() == 3
        assert pqs.wyslij_zaplanowany_sygnal() == 0
    assert sygnaly == [3]
