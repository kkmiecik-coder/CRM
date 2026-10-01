# -*- coding: utf-8 -*-
"""Deklaracja paczek z tabletu pakowania (logistyka etap 4, krok 4.2, spec 7.2)."""
import io
import itertools
import os
from datetime import datetime, timedelta

import pytest
from flask import jsonify
from sqlalchemy import event

from extensions import db
from modules.production.logistics import sposoby as s
from modules.production.logistics.models import LogisticsLog
from modules.production.logistics.services import paczki
from modules.production.models import (LabelPrintJob, ProcessedMobileOperation, ProductionConfig,
                                       ProductionDevice, ProductionOrder, ProductionPackage,
                                       ProductionProduct, get_local_now)
from modules.production.routers import mobile_api
from modules.production.services import print_queue_service as pqs
from modules.production.services.mobile_api_service import generate_token, with_idempotency
from tests.logistyka_fixtures import app, client, pracownik, zamowienie  # noqa: F401
from tests.weryfikacja_pomocnicze import migawka_pozycji

_numery = itertools.count(1400)
T0 = datetime(2026, 10, 1, 8, 0)
_licznik = itertools.count(1)


@pytest.fixture(autouse=True)
def bez_statusow_base(monkeypatch):
    """Spakowanie odpala synchronizację statusu Base. po commicie — w testach jej nie chcemy."""
    monkeypatch.setattr(
        'modules.production.services.baselinker_status_sync.schedule_after_station_complete',
        lambda *a, **k: None)


@pytest.fixture()
def sygnaly(monkeypatch):
    wyslane = []
    monkeypatch.setattr(pqs.realtime_service, 'publish_print_signal',
                        lambda n: wyslane.append(n) or True)
    return wyslane


def _urzadzenie(stanowisko='packaging'):
    device = ProductionDevice(device_id='TAB-%s-%d' % (stanowisko, next(_licznik)),
                              device_name='Tablet', station_code=stanowisko)
    db.session.add(device)
    db.session.commit()
    return device


def _naglowki(device, op_id=None, **inne):
    naglowki = {'Authorization': 'Bearer ' + generate_token(device),
                'X-Operation-Id': op_id or 'op-paczki-%d' % next(_licznik)}
    naglowki.update(inne)
    return naglowki


def _spakowane(sposob=s.KURIER, statusy=('spakowane', 'spakowane'), **kolumny):
    return zamowienie(sposob=sposob, statusy=statusy, numer_wewnetrzny=str(next(_numery)), **kolumny)


def _url(order):
    return '/api/mobile/orders/%s/packages' % order.internal_order_number


def _put(client, order, device, dane, **naglowki):
    return client.put(_url(order), json=dane, headers=_naglowki(device, **naglowki))


def test_deklaracja_tworzy_paczki_i_kolejkuje_etykiety(app, client, sygnaly):
    order, device = _spakowane(), _urzadzenie()
    r = _put(client, order, device, {'kind': 'paczka', 'count': 3})
    assert r.status_code == 200, r.get_json()
    dane = r.get_json()
    nowe = ProductionPackage.query.filter_by(order_id=order.id).order_by(ProductionPackage.seq).all()
    assert [(p.seq, p.kind, p.pallet_type, p.voided_at) for p in nowe] == \
        [(1, 'paczka', None, None), (2, 'paczka', None, None), (3, 'paczka', None, None)]
    assert all((p.declared_device_id, p.label_print_count, p.label_delivery_text) == (device.id, 1, 'KURIER')
               for p in nowe)
    assert [p['code'] for p in dane['packages']] == [p.kod for p in nowe]
    assert dane['labels_queued'] == 3 and dane['internal_order_number'] == order.internal_order_number
    assert u'3 × paczka' in dane['message'] and dane['packages_declared_at']
    zadania = LabelPrintJob.query.order_by(LabelPrintJob.id).all()
    assert [(z.printer, z.package_id, z.short_product_id) for z in zadania] == \
        [('wysylka', p.id, p.kod) for p in nowe]
    assert '^FR^FD3 / 3^FS' in zadania[2].zpl_payload
    assert ProductionOrder.query.get(order.id).packages_declared_at is not None
    wpis = LogisticsLog.query.filter_by(order_id=order.id, action='paczki').one()
    assert (wpis.old_value, wpis.new_value, wpis.device_id) == (None, u'3 × paczka', device.id)
    assert sygnaly == [3]


@pytest.mark.parametrize('dane, zapisane, na_etykiecie', [
    ({'kind': 'paleta', 'count': 1, 'pallet_type': 'eur'}, ('paleta', 'eur', 120, 80), 'PALETA EUR 120x80'),
    ({'kind': 'paleta', 'count': 1, 'pallet_type': 'eur', 'length_cm': 100, 'width_cm': 100},
     ('paleta', 'eur', 120, 80), 'PALETA EUR 120x80'),
    ({'kind': 'paleta', 'count': 2, 'pallet_type': 'niestandardowa', 'length_cm': 150, 'width_cm': 100},
     ('paleta', 'niestandardowa', 150, 100), 'PALETA 150x100'),
    ({'kind': 'paczka', 'count': 1, 'pallet_type': 'eur', 'length_cm': 50},
     ('paczka', None, None, None), 'PACZKA'),
])
def test_rodzaje_i_wymiary(app, client, sygnaly, dane, zapisane, na_etykiecie):
    order = _spakowane()
    assert _put(client, order, _urzadzenie(), dane).status_code == 200
    p = paczki.aktualne_paczki(order.id)[0]
    assert (p.kind, p.pallet_type, p.length_cm, p.width_cm) == zapisane
    assert '^FD%s^FS' % na_etykiecie in LabelPrintJob.query.first().zpl_payload


@pytest.mark.parametrize('dane', [
    None, [], {}, {'kind': 'skrzynia', 'count': 1}, {'kind': 'paczka'},
    {'kind': 'paczka', 'count': 0}, {'kind': 'paczka', 'count': 11},
    {'kind': 'paczka', 'count': True}, {'kind': 'paczka', 'count': '2'}, {'kind': 'paczka', 'count': 1.5},
    {'kind': 'paleta', 'count': 1}, {'kind': 'paleta', 'count': 1, 'pallet_type': 'duza'},
    {'kind': 'paleta', 'count': 1, 'pallet_type': 'niestandardowa'},
    {'kind': 'paleta', 'count': 1, 'pallet_type': 'niestandardowa', 'length_cm': 19, 'width_cm': 100},
    {'kind': 'paleta', 'count': 1, 'pallet_type': 'niestandardowa', 'length_cm': 150, 'width_cm': 401},
    {'kind': 'paleta', 'count': 1, 'pallet_type': 'niestandardowa', 'length_cm': '150', 'width_cm': 100},
])
def test_zle_dane_422(app, client, sygnaly, dane):
    order = _spakowane()
    r = _put(client, order, _urzadzenie(), dane)
    assert r.status_code == 422 and r.get_json()['error'] == 'invalid_packages'
    assert r.get_json()['message']
    assert ProductionPackage.query.count() == 0 and LabelPrintJob.query.count() == 0 and sygnaly == []


@pytest.mark.parametrize('dane, ile, wymiar', [
    ({'kind': 'paczka', 'count': 2.0}, 2, (None, None)),
    ({'kind': 'paleta', 'count': 1, 'pallet_type': 'niestandardowa', 'length_cm': 150.0, 'width_cm': 100},
     1, (150, 100)),
])
def test_calkowite_liczby_zmiennoprzecinkowe_przechodza(app, client, sygnaly, dane, ile, wymiar):
    """422 jest zapamiętywane, czyli wyrzuca deklarację z kolejki offline tabletu (2.0 == 2)."""
    order = _spakowane()
    r = _put(client, order, _urzadzenie(), dane)
    assert r.status_code == 200, r.get_json()
    lista = paczki.aktualne_paczki(order.id)
    assert len(lista) == ile and (lista[0].length_cm, lista[0].width_cm) == wymiar
    assert isinstance(lista[0].seq, int) and sygnaly == [ile]


def test_niespakowane_zamowienie_409_i_ponowienie_po_spakowaniu(app, client, sygnaly):
    """Review Focus 2: kolejka appki nie gwarantuje, że ostatni COMPLETE przeszedł pierwszy."""
    order, device = _spakowane(statusy=('spakowane', 'czeka_na_pakowanie')), _urzadzenie()
    naglowki = _naglowki(device, op_id='op-rata')
    r = client.put(_url(order), json={'kind': 'paczka', 'count': 1}, headers=naglowki)
    assert r.status_code == 409 and r.get_json()['error'] == 'order_not_packed'
    assert order.internal_order_number in r.get_json()['message']
    assert ProductionPackage.query.count() == 0 and LabelPrintJob.query.count() == 0 and sygnaly == []
    for p in order.products:
        p.current_status = 'spakowane'
    db.session.commit()
    r = client.put(_url(order), json={'kind': 'paczka', 'count': 1}, headers=naglowki)
    assert r.status_code == 200 and ProductionPackage.query.count() == 1


# --- Deklaracja decyduje na stanie BIEŻĄCYM pozycji (fala końcowa 4.3, F8) ------------------------------
# Migawka MySQL (REPEATABLE READ) powstaje przed czekaniem na blokady, więc leniwe `order.products` pokazuje
# statusy sprzed cudzej weryfikacji. Przelotka migawka_pozycji wpycha do sesji ORM pozycje w starym stanie,
# a w bazie zostawia nowy (wzór z tests/test_weryfikacja_akcje.py) — strażnik ma zobaczyć bazę.

@pytest.mark.parametrize('w_bazie, kod', [
    ('zweryfikowane', 'order_verified'),        # równoległa weryfikacja zdążyła przed blokadą
    ('zaladowane', 'order_verified'),
    ('dostarczone', 'order_verified'),
    ('czeka_na_pakowanie', 'order_not_packed'), # pozycja wróciła „w tle” do pakowania
])
def test_deklaracja_decyduje_na_biezacym_stanie_pozycji(app, client, sygnaly, monkeypatch, w_bazie, kod):
    order, device = _spakowane(), _urzadzenie()
    migawka_pozycji(monkeypatch, paczki, 'zadeklaruj', w_pamieci='spakowane', w_bazie=w_bazie)
    r = _put(client, order, device, {'kind': 'paczka', 'count': 2})
    assert (r.status_code, r.get_json()['error']) == (409, kod), r.get_json()
    assert order.internal_order_number in r.get_json()['message']
    assert ProductionPackage.query.filter_by(order_id=order.id).count() == 0     # żadnych nowych paczek
    assert LabelPrintJob.query.count() == 0 and sygnaly == []
    assert ProductionOrder.query.get(order.id).packages_declared_at is None
    assert ProcessedMobileOperation.query.count() == 0                            # 409 niezapamiętane


def test_deklaracja_po_cichej_weryfikacji_nie_zostawia_zamowienia_zweryfikowanego_z_niesprawdzonymi_paczkami(
        app, client, sygnaly, monkeypatch):
    """Sedno F8: przegrany w wyścigu z weryfikacją deklarował nowe paczki PO weryfikacji. Jedyny dozwolony
    stan końcowy to brak nowej deklaracji: stare, sprawdzone paczki ważne, a zamówienie zweryfikowane."""
    kto = pracownik()
    order, device = _spakowane(statusy=('zweryfikowane', 'zweryfikowane'), verified_at=T0), _urzadzenie()
    stare = ProductionPackage(order_id=order.id, seq=1, kind='paczka', declared_at=T0, verified_at=T0,
                              verified_method='skan', verified_by_worker_id=kto.id)
    db.session.add(stare)
    order.packages_declared_at = T0
    db.session.commit()
    migawka_pozycji(monkeypatch, paczki, 'zadeklaruj', w_pamieci='spakowane', w_bazie='zweryfikowane')
    r = _put(client, order, device, {'kind': 'paczka', 'count': 3})
    assert (r.status_code, r.get_json()['error']) == (409, 'order_verified')
    aktualne = paczki.aktualne_paczki(order.id)
    assert [(p.id, p.verified_at) for p in aktualne] == [(stare.id, T0)]          # stara deklaracja ważna
    assert ProductionOrder.query.get(order.id).verified_at == T0


def test_deklaracja_na_aktualnym_stanie_nadal_przechodzi_gdy_baza_zgadza_sie_z_pamiecia(app, client, sygnaly,
                                                                                    monkeypatch):
    """Przelotka bez rozjazdu (pamięć = baza) niczego nie psuje: zwykła deklaracja przechodzi."""
    order, device = _spakowane(), _urzadzenie()
    migawka_pozycji(monkeypatch, paczki, 'zadeklaruj', w_pamieci='spakowane', w_bazie='spakowane')
    assert _put(client, order, device, {'kind': 'paczka', 'count': 2}).status_code == 200
    assert ProductionPackage.query.filter_by(order_id=order.id).count() == 2


# --- Wstępna odmowa order_not_packed z migawki, zanim zablokujemy pozycje (fala końcowa 4.3, F11) --------
# Powód: ostatni „ZAKOŃCZ” trzyma pozycję i sięga po zamówienie, a deklaracja trzyma zamówienie — czekanie na
# pozycje pod blokadą zamówienia dawało 1213 (MySQL, 19 z 20 przebiegów). SQLite nie ma blokad, więc pilnujemy
# kolejności i treści zapytań: przy odmowie z pamięci nie ma SELECT-u pozycji po PK (odczyt bieżący) ani paczek.

def _zapytania_zadania(client, order, device):
    """(odpowiedź, lista zapytań SQL) PUT-a deklaracji."""
    zapytania = []

    def zapamietaj(conn, cursor, statement, parameters, context, executemany):
        zapytania.append(' '.join(statement.split()))

    event.listen(db.engine, 'before_cursor_execute', zapamietaj)
    try:
        r = _put(client, order, device, {'kind': 'paczka', 'count': 1})
    finally:
        event.remove(db.engine, 'before_cursor_execute', zapamietaj)
    return r, zapytania


def _odczyt_biezacy_pozycji(zapytania):
    return [q for q in zapytania if q.startswith('SELECT') and 'FROM prod_products' in q
            and 'WHERE prod_products.id IN' in q and 'ORDER BY prod_products.id' in q]


def test_niespakowane_z_pamieci_odmawia_bez_odczytu_biezacego_pozycji(app, client, sygnaly):
    order, device = _spakowane(statusy=('spakowane', 'czeka_na_pakowanie')), _urzadzenie()
    r, zapytania = _zapytania_zadania(client, order, device)
    assert (r.status_code, r.get_json()['error']) == (409, 'order_not_packed')
    assert order.internal_order_number in r.get_json()['message']
    assert _odczyt_biezacy_pozycji(zapytania) == []                       # bez sięgania po pozycje po PK
    assert not [q for q in zapytania if 'FROM prod_packages' in q]        # i bez blokady paczek
    assert ProductionPackage.query.count() == 0 and LabelPrintJob.query.count() == 0 and sygnaly == []


def test_migawka_niespakowana_odmawia_wstepnie_choc_baza_ma_juz_spakowane(app, client, sygnaly, monkeypatch):
    """Migawka sprzed zatwierdzenia ostatniego „ZAKOŃCZ”: 409 order_not_packed (appka ponowi tę samą operację),
    bez czekania na pozycje."""
    order, device = _spakowane(), _urzadzenie()
    migawka_pozycji(monkeypatch, paczki, 'zadeklaruj', w_pamieci='czeka_na_pakowanie', w_bazie='spakowane')
    r, zapytania = _zapytania_zadania(client, order, device)
    assert (r.status_code, r.get_json()['error']) == (409, 'order_not_packed')
    assert _odczyt_biezacy_pozycji(zapytania) == []
    assert ProductionPackage.query.count() == 0 and ProcessedMobileOperation.query.count() == 0


def test_spakowane_z_pamieci_nadal_idzie_odczytem_biezacym(app, client, sygnaly):
    """Kontrola odwrotna: gdy migawka pokazuje spakowane, ostateczna decyzja zapada na odczycie bieżącym."""
    order, device = _spakowane(), _urzadzenie()
    r, zapytania = _zapytania_zadania(client, order, device)
    assert r.status_code == 200
    assert len(_odczyt_biezacy_pozycji(zapytania)) == 1


# --- Telefon Weryfikacji deklaruje tylko w zakresie listy (fala końcowa 4.3, F13) -----------------------

def _spakowane_dawno(dni, **kolumny):
    """Kurier zamknięty w Logistyce, spakowany `dni` dni temu (okno listy Weryfikacji to 7 dni)."""
    dawno = get_local_now() - timedelta(days=dni)
    order = _spakowane(logistics_closed_at=dawno, **kolumny)
    for p in order.products:
        p.packaging_completed_at = dawno
    db.session.commit()
    return order


def test_telefon_weryfikacji_poza_zakresem_listy_nie_deklaruje_paczek(app, client, sygnaly):
    order = _spakowane_dawno(10)
    r = _put(client, order, _urzadzenie('verification'), {'kind': 'paczka', 'count': 2})
    assert (r.status_code, r.get_json()['error']) == (409, 'order_status')
    assert u'poza listą Weryfikacji' in r.get_json()['message']
    assert ProductionPackage.query.count() == 0 and LabelPrintJob.query.count() == 0 and sygnaly == []
    assert ProductionOrder.query.get(order.id).packages_declared_at is None
    assert ProcessedMobileOperation.query.count() == 0                    # 409 niezapamiętane


def test_tablet_pakowania_na_tym_samym_zamowieniu_deklaruje_jak_dotad(app, client, sygnaly):
    order = _spakowane_dawno(10)
    r = _put(client, order, _urzadzenie('packaging'), {'kind': 'paczka', 'count': 2})
    assert r.status_code == 200, r.get_json()
    assert ProductionPackage.query.filter_by(order_id=order.id).count() == 2


def test_telefon_weryfikacji_w_zakresie_listy_deklaruje(app, client, sygnaly):
    order = _spakowane_dawno(1)
    r = _put(client, order, _urzadzenie('verification'), {'kind': 'paczka', 'count': 1})
    assert r.status_code == 200, r.get_json()
    assert ProductionPackage.query.filter_by(order_id=order.id).count() == 1


def test_telefon_weryfikacji_konkretniejszy_kod_wygrywa_z_zakresem(app, client, sygnaly):
    """Zamówienie poza zakresem i jeszcze niespakowane: 409 order_not_packed, nie order_status."""
    order = _spakowane_dawno(10, statusy=('spakowane', 'czeka_na_pakowanie'))
    r = _put(client, order, _urzadzenie('verification'), {'kind': 'paczka', 'count': 1})
    assert (r.status_code, r.get_json()['error']) == (409, 'order_not_packed')


def test_anulowana_pozycja_nie_blokuje_deklaracji(app, client, sygnaly):
    order = _spakowane(statusy=('spakowane', 'anulowane'))
    assert _put(client, order, _urzadzenie(), {'kind': 'paczka', 'count': 1}).status_code == 200


def test_zamowienie_calkiem_anulowane_409(app, client, sygnaly):
    r = _put(client, _spakowane(statusy=('anulowane',)), _urzadzenie(), {'kind': 'paczka', 'count': 1})
    assert r.status_code == 409 and r.get_json()['error'] == 'order_not_packed'


def test_ponowna_deklaracja_uniewaznia_poprzednia(app, client, sygnaly):
    order, device = _spakowane(), _urzadzenie()
    assert _put(client, order, device, {'kind': 'paczka', 'count': 2}).status_code == 200
    stare_id = [p.id for p in paczki.aktualne_paczki(order.id)]
    assert _put(client, order, device, {'kind': 'paleta', 'count': 1, 'pallet_type': 'eur'}).status_code == 200
    aktualne = paczki.aktualne_paczki(order.id)
    assert [(p.seq, p.kind) for p in aktualne] == [(1, 'paleta')]
    assert all(ProductionPackage.query.get(i).voided_at is not None for i in stare_id)
    assert LabelPrintJob.query.count() == 3 and sygnaly == [2, 1]
    wpisy = LogisticsLog.query.filter_by(order_id=order.id, action='paczki').order_by(LogisticsLog.id).all()
    assert [(w.old_value, w.new_value) for w in wpisy] == [(None, u'2 × paczka'), (u'2 × paczka', u'1 × EUR')]


def test_ponowna_deklaracja_wygasza_oczekujace_zadania_starych_paczek(app, client, sygnaly):
    """Agent druku pobiera `pending` — etykiety unieważnionych paczek nie mogą wyjść obok nowych."""
    order, device = _spakowane(), _urzadzenie()
    assert _put(client, order, device, {'kind': 'paczka', 'count': 2}).status_code == 200
    stare = LabelPrintJob.query.order_by(LabelPrintJob.id).all()
    assert [z.status for z in stare] == ['pending', 'pending']
    stare[1].status = 'printed'                   # ta etykieta już wyszła na drukarkę
    db.session.commit()
    assert _put(client, order, device, {'kind': 'paczka', 'count': 1}).status_code == 200
    stare_id = [z.id for z in stare]
    pierwsze, drugie = (LabelPrintJob.query.get(i) for i in stare_id)
    assert pierwsze.status == 'expired'
    assert pierwsze.error_message == u'Paczka unieważniona — nowa deklaracja paczek'
    assert drugie.status == 'printed' and drugie.error_message is None
    nowe = LabelPrintJob.query.filter(LabelPrintJob.id.notin_(stare_id)).all()
    assert [(z.status, z.package_id) for z in nowe] == [('pending', paczki.aktualne_paczki(order.id)[0].id)]


def test_pierwsza_deklaracja_nie_wygasza_cudzych_zadan(app, client, sygnaly):
    """Zadania bez paczki (etykiety produktów) i innych zamówień zostają nietknięte."""
    inne = _spakowane()
    assert _put(client, inne, _urzadzenie(), {'kind': 'paczka', 'count': 1}).status_code == 200
    db.session.add(LabelPrintJob(short_product_id='1_1', zpl_payload='^XA^XZ', station_code='labels',
                                 requested_by_type='device', requested_by_id='x', status='pending'))
    db.session.commit()
    order = _spakowane()
    assert _put(client, order, _urzadzenie(), {'kind': 'paczka', 'count': 1}).status_code == 200
    assert LabelPrintJob.query.filter_by(status='pending').count() == 3
    assert LabelPrintJob.query.filter_by(status='expired').count() == 0


def test_komunikat_ponownej_deklaracji_mowi_o_nieaktualnych_etykietach(app, client, sygnaly):
    order, device = _spakowane(), _urzadzenie()
    pierwsza = _put(client, order, device, {'kind': 'paczka', 'count': 2})
    assert pierwsza.status_code == 200 and 'Poprzednie' not in pierwsza.get_json()['message']
    druga = _put(client, order, device, {'kind': 'paleta', 'count': 1, 'pallet_type': 'eur'})
    assert druga.status_code == 200
    assert u'Poprzednie etykiety (2) są nieaktualne.' in druga.get_json()['message']


def test_ten_sam_operation_id_nie_deklaruje_drugi_raz(app, client, sygnaly):
    """Review Focus 1: powtórka z kolejki offline po timeoucie."""
    order, device = _spakowane(), _urzadzenie()
    pierwsza = _put(client, order, device, {'kind': 'paczka', 'count': 2}, op_id='op-powtorka')
    druga = _put(client, order, device, {'kind': 'paczka', 'count': 2}, op_id='op-powtorka')
    assert druga.status_code == 200 and druga.get_json() == pierwsza.get_json()
    assert ProductionPackage.query.count() == 2 and LabelPrintJob.query.count() == 2 and sygnaly == [2]


@pytest.mark.parametrize('stanowisko', ['cutting', 'edges', 'formatting'])
def test_stanowisko_bez_prawa_do_paczek_403(app, client, sygnaly, stanowisko):
    r = _put(client, _spakowane(), _urzadzenie(stanowisko), {'kind': 'paczka', 'count': 1})
    assert r.status_code == 403 and r.get_json()['error'] == 'station_not_allowed'
    assert ProductionPackage.query.count() == 0


def test_stanowiska_paczek():
    assert paczki.STANOWISKA_PACZEK == ('packaging', 'verification')


def test_nieznane_zamowienie_404(app, client, sygnaly):
    r = client.put('/api/mobile/orders/999999/packages', json={'kind': 'paczka', 'count': 1},
                   headers=_naglowki(_urzadzenie()))
    assert r.status_code == 404 and r.get_json()['error'] == 'order_not_found'


def test_deklaracja_podbija_updated_at_pozycji(app, client, sygnaly):
    order = _spakowane()
    for p in order.products:
        p.updated_at = datetime(2026, 9, 1)
    db.session.commit()
    assert _put(client, order, _urzadzenie(), {'kind': 'paczka', 'count': 1}).status_code == 200
    assert all(ProductionProduct.query.get(p.id).updated_at > datetime(2026, 9, 1) for p in order.products)


def test_pracownik_z_naglowka(app, client, sygnaly, monkeypatch):
    monkeypatch.setattr(mobile_api.worker_service, 'touch_sessions', lambda ids, **k: {})
    kto, order, device = pracownik(), _spakowane(), _urzadzenie()
    r = _put(client, order, device, {'kind': 'paczka', 'count': 1}, **{'X-Worker-Ids': str(kto.id)})
    assert r.status_code == 200
    assert paczki.aktualne_paczki(order.id)[0].declared_by_worker_id == kto.id
    assert LogisticsLog.query.filter_by(order_id=order.id, action='paczki').one().worker_id == kto.id


def test_sygnal_dla_agenta_dopiero_po_commicie(app, client, monkeypatch):
    """Review Focus 4."""
    kolejnosc = []
    monkeypatch.setattr(pqs.realtime_service, 'publish_print_signal',
                        lambda n: kolejnosc.append(('sygnal', n)) or True)

    def _po_commicie(sesja):
        kolejnosc.append('commit')

    order, device = _spakowane(), _urzadzenie()
    event.listen(db.session, 'after_commit', _po_commicie)
    try:
        assert _put(client, order, device, {'kind': 'paczka', 'count': 2}).status_code == 200
    finally:
        event.remove(db.session, 'after_commit', _po_commicie)
    assert kolejnosc[-2:] == ['commit', ('sygnal', 2)]
    assert kolejnosc.count(('sygnal', 2)) == 1


def _dwa_zamowienia_o_tym_samym_numerze():
    """Licznik numerów startuje co roku od nowa — numer się powtarza, a nowsze zamówienie ma wyższe id."""
    starsze = zamowienie(sposob=s.KURIER, statusy=('spakowane', 'spakowane'), numer_wewnetrzny='1777')
    nowsze = zamowienie(sposob=s.KURIER, statusy=('spakowane', 'spakowane'), numer_wewnetrzny='1777')
    assert nowsze.id > starsze.id and nowsze.internal_order_number == starsze.internal_order_number
    return starsze, nowsze


def test_put_przy_powtorzonym_numerze_trafia_w_nowsze_zamowienie(app, client, sygnaly):
    starsze, nowsze = _dwa_zamowienia_o_tym_samym_numerze()
    r = _put(client, nowsze, _urzadzenie(), {'kind': 'paczka', 'count': 2})
    assert r.status_code == 200, r.get_json()
    assert [p.order_id for p in ProductionPackage.query.all()] == [nowsze.id, nowsze.id]
    assert paczki.aktualne_paczki(starsze.id) == []
    assert ProductionOrder.query.get(starsze.id).packages_declared_at is None
    assert ProductionOrder.query.get(nowsze.id).packages_declared_at is not None
    assert LogisticsLog.query.filter_by(order_id=starsze.id, action='paczki').count() == 0


def test_get_przy_powtorzonym_numerze_czyta_nowsze_zamowienie(app, client, sygnaly):
    starsze, nowsze = _dwa_zamowienia_o_tym_samym_numerze()
    device = _urzadzenie()
    # Paczka starszego zamówienia nie może wyciec do odpowiedzi o numerze.
    db.session.add(ProductionPackage(order_id=starsze.id, seq=1, kind='paczka',
                                     declared_at=datetime(2026, 1, 5)))
    db.session.commit()
    assert client.get(_url(nowsze), headers=_naglowki(device)).get_json()['packages'] == []
    assert _put(client, nowsze, device, {'kind': 'paczka', 'count': 1}).status_code == 200
    dane = client.get(_url(nowsze), headers=_naglowki(device)).get_json()
    assert [p['id'] for p in dane['packages']] ==         [p.id for p in ProductionPackage.query.filter_by(order_id=nowsze.id)]
    assert dane['packages_declared_at']


def test_pracownicy_przed_blokada_zamowienia(app, client, sygnaly, monkeypatch):
    """Kolejność blokad: sesje pracowników (jak w order_complete) → blokada deklaracji paczek →
    blokada zamówienia — bez zakleszczenia."""
    kolejnosc = []
    pracownicy, zamowienie_po_numerze = mobile_api._resolve_workers, mobile_api._zamowienie_po_numerze
    blokada_paczek = paczki.zablokuj_deklaracje

    def _pracownicy():
        kolejnosc.append('pracownicy')
        return pracownicy()

    def _blokada_paczek():
        kolejnosc.append('blokada_paczek')
        return blokada_paczek()

    def _zamowienie(numer, do_zapisu=False):
        kolejnosc.append('blokada' if do_zapisu else 'odczyt')
        return zamowienie_po_numerze(numer, do_zapisu=do_zapisu)

    monkeypatch.setattr(mobile_api, '_resolve_workers', _pracownicy)
    monkeypatch.setattr(paczki, 'zablokuj_deklaracje', _blokada_paczek)
    monkeypatch.setattr(mobile_api, '_zamowienie_po_numerze', _zamowienie)
    assert _put(client, _spakowane(), _urzadzenie(), {'kind': 'paczka', 'count': 1}).status_code == 200
    assert kolejnosc == ['pracownicy', 'blokada_paczek', 'blokada']


def _wiersz_blokady():
    return ProductionConfig.query.filter_by(config_key=paczki.KLUCZ_BLOKADY).all()


def test_zablokuj_deklaracje_zwraca_wiersz_blokady(app):
    """Z wierszem w prod_config (zakłada go migracja) funkcja bierze na nim blokadę i go zwraca."""
    db.session.add(ProductionConfig(config_key=paczki.KLUCZ_BLOKADY, config_value='',
                                    config_type='string'))
    db.session.commit()
    wiersz = paczki.zablokuj_deklaracje()
    assert wiersz is not None and wiersz.config_key == 'logistyka_paczki_blokada'
    assert len(_wiersz_blokady()) == 1


def test_zablokuj_deklaracje_bez_wiersza_na_sqlite_nie_rzuca(app, client, sygnaly, monkeypatch):
    """Fixture testowy tworzy sam schemat, bez danych migracji: brak wiersza = fail-open
    (None, ostrzeżenie raz na proces, żadnego zakładania wiersza poza MySQL), a deklaracja przechodzi."""
    monkeypatch.setattr(paczki, '_blokada_ostrzezono', False)
    assert paczki._samonaprawa_blokady() is False
    assert paczki.zablokuj_deklaracje() is None
    assert paczki._blokada_ostrzezono is True
    assert _wiersz_blokady() == []
    order = _spakowane()
    assert _put(client, order, _urzadzenie(), {'kind': 'paczka', 'count': 2}).status_code == 200
    assert ProductionPackage.query.filter_by(order_id=order.id).count() == 2
    assert _wiersz_blokady() == []


def test_zablokuj_deklaracje_zaklada_brakujacy_wiersz_na_mysql(app, monkeypatch):
    """Baza, która wykonała migrację przed dodaniem wiersza (runner pamięta pliki po nazwie):
    na MySQL wiersz zakłada się sam w tej transakcji, a kolejne wywołanie go nie dubluje.
    Na SQLite testów samonaprawę włączamy ręcznie."""
    monkeypatch.setattr(paczki, '_samonaprawa_blokady', lambda: True)
    wiersz = paczki.zablokuj_deklaracje()
    assert wiersz is not None and wiersz.config_key == paczki.KLUCZ_BLOKADY
    assert paczki.zablokuj_deklaracje().id == wiersz.id
    db.session.commit()
    zapisane = _wiersz_blokady()
    assert len(zapisane) == 1 and zapisane[0].config_type == 'string'
    assert zapisane[0].config_description == paczki.OPIS_BLOKADY


MIGRACJA_BLOKADY = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                'migrations', '2026-09-30-logistyka-paczki-blokada.sql')


def test_migracja_blokady_paczek():
    """Plik istnieje, runner go rozpoznaje, zakłada wiersz blokady idempotentnie (INSERT IGNORE),
    a opis w migracji i w kodzie to ten sam napis."""
    from migrations.migration_service import MigrationService
    assert os.path.isfile(MIGRACJA_BLOKADY)
    assert MigrationService(db=None)._match(os.path.basename(MIGRACJA_BLOKADY)) is not None
    sql = io.open(MIGRACJA_BLOKADY, encoding='utf-8').read()
    assert 'INSERT IGNORE INTO prod_config' in sql and "'logistyka_paczki_blokada'" in sql
    assert paczki.OPIS_BLOKADY in sql and "'%s'" % paczki.KLUCZ_BLOKADY in sql
    assert 'delimiter' not in sql.lower()
    # jedno polecenie: komentarze nie mogą rozciąć wstawienia (średnik tylko na końcu)
    polecenia = MigrationService.split_statements(sql)
    assert len(polecenia) == 1 and polecenia[0].startswith('INSERT IGNORE INTO prod_config')


def test_get_zwraca_aktualne_paczki(app, client, sygnaly):
    order, device = _spakowane(), _urzadzenie()
    pusta = client.get(_url(order), headers=_naglowki(device))
    assert pusta.status_code == 200 and 'no-store' in pusta.headers['Cache-Control']
    assert pusta.get_json() == {'internal_order_number': order.internal_order_number,
                                'packages_declared_at': None, 'packages': []}
    _put(client, order, device, {'kind': 'paczka', 'count': 2})
    _put(client, order, device, {'kind': 'paczka', 'count': 1})
    dane = client.get(_url(order), headers=_naglowki(device)).get_json()
    assert [p['seq'] for p in dane['packages']] == [1] and dane['packages_declared_at']
    assert client.get('/api/mobile/orders/999999/packages', headers=_naglowki(device)).status_code == 404


def test_get_z_kazdego_stanowiska(app, client):
    order = _spakowane()
    assert client.get(_url(order), headers=_naglowki(_urzadzenie('cutting'))).status_code == 200


def test_stara_appka_pakuje_bez_deklaracji(app, client, sygnaly):
    """Spec 7.2: backend przyjmuje pakowanie bez deklaracji (stara appka, admin)."""
    order, device = _spakowane(statusy=('czeka_na_pakowanie',)), _urzadzenie()
    r = client.post('/api/mobile/orders/%d/complete' % order.products[0].id, headers=_naglowki(device))
    assert r.status_code == 200 and r.get_json()['status'] == 'spakowane'
    assert paczki.aktualne_paczki(order.id) == [] and LabelPrintJob.query.count() == 0


@pytest.mark.parametrize('argumenty, tekst', [
    (('paczka', 3), u'3 × paczka'),
    (('paleta', 1, 'eur', 120, 80), u'1 × EUR'),
    (('paleta', 2, 'niestandardowa', 150, 100), u'2 × paleta 150×100'),
])
def test_opis_deklaracji(argumenty, tekst):
    assert paczki.opis(*argumenty) == tekst


@pytest.mark.parametrize('status, sygnal', [
    (409, []),          # retryable_statuses: rollback, więc etykiet w kolejce nie ma
    (500, []),
    (200, [2]),
])
def test_dekorator_wysyla_zaplanowany_sygnal_tylko_po_udanym_commicie(app, sygnaly, status, sygnal):
    """Handler planuje sygnał ZANIM wiadomo, czy dekorator zatwierdzi transakcję."""
    @with_idempotency(retryable_statuses={409})
    def handler():
        pqs.zaplanuj_sygnal_po_commicie(2)
        return jsonify({'status': status}), status

    with app.test_request_context('/x', method='PUT', headers={'X-Operation-Id': 'op-sygnal-%d' % status}):
        _, zwrocony = handler()
    assert zwrocony == status
    assert sygnaly == sygnal
