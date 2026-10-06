# -*- coding: utf-8 -*-
"""Krok 4.6 (decyzja Konrada 5.10): Pakowanie przyjmuje zamówienia BEZ ustawionego sposobu dostawy.

ZAKOŃCZ przechodzi, Base. nie dostaje statusu po spakowaniu, zamówienie zostaje otwarte w Logistyce
(„Nie ustawiono”), a pierwsze ustawienie sposobu idzie przez okno 8.7 i dopiero wtedy wysyła status
po spakowaniu. Etykieta z pasem „NIE USTAWIONO” zapala potem ikonę „etykiety sprzed zmiany”.
"""
from datetime import datetime

import pytest

from extensions import db
from modules.production.logistics import sposoby as s
from modules.production.logistics.services import delivery as d
from modules.production.logistics.services import lista, paczki_druk
from modules.production.models import ProductionDevice, ProductionOrder, ProductionPackage, ProductionProduct
from modules.production.services import baselinker_status_sync as bl
from modules.production.services.mobile_api_service import generate_token
from tests.logistyka_fixtures import BASE, app, client, zamowienie  # noqa: F401

T0 = datetime(2026, 10, 5, 9, 0)
T1 = datetime(2026, 10, 5, 10, 0)


@pytest.fixture(autouse=True)
def bez_statusow_base(monkeypatch):
    """Spakowanie odpala synchronizację statusu Base. po commicie — w testach ZAKOŃCZ jej nie chcemy."""
    monkeypatch.setattr(
        'modules.production.services.baselinker_status_sync.schedule_after_station_complete',
        lambda *a, **k: None)


def _naglowki(app, op=None):
    with app.app_context():
        device = ProductionDevice(device_id='TAB-pak', device_name='Tablet', station_code='packaging')
        db.session.add(device)
        db.session.commit()
        naglowki = {'Authorization': 'Bearer ' + generate_token(device)}
    if op:
        naglowki['X-Operation-Id'] = op
    return naglowki


def _zakoncz(client, naglowki, pid):
    return client.post('/api/mobile/orders/%d/complete' % pid, headers=naglowki)


def test_kolejka_pakowania_pokazuje_zamowienie_bez_sposobu(app, client):
    with app.app_context():
        order = zamowienie(statusy=('czeka_na_pakowanie',))
        numer = order.internal_order_number
    dane = client.get('/api/mobile/stations/packaging/orders', headers=_naglowki(app)).get_json()
    [pozycja] = [o for o in dane['orders'] if o['internal_order_number'] == numer]
    assert pozycja['transport']['mode'] is None


def test_zakoncz_bez_sposobu_pakuje_i_zostawia_zamowienie_otwarte(app, client):
    with app.app_context():
        order = zamowienie(statusy=('czeka_na_pakowanie',))
        pid, oid = order.products[0].id, order.id
    r = _zakoncz(client, _naglowki(app, 'op-46-1'), pid)
    assert r.status_code == 200
    assert r.get_json()['status'] == 'spakowane'
    with app.app_context():
        wiersz = ProductionOrder.query.get(oid)
        assert ProductionProduct.query.get(pid).current_status == 'spakowane'
        assert wiersz.override_delivery_method is None
        # Spec 6.2: sposób None → zamówienie otwarte, liczy się w „Nie ustawiono” i na pasku dashboardu.
        assert wiersz.logistics_closed_at is None
        assert wiersz.bl_status_pending_id is None
        assert lista.liczba_bez_sposobu() == 1
    zamowienia = client.get(BASE + '/orders?sposob=brak').get_json()['orders']
    assert [o['id'] for o in zamowienia] == [oid]


def test_status_base_po_spakowaniu_bez_sposobu_to_brak_statusu(app):
    with app.app_context():
        order = zamowienie(statusy=('spakowane', 'zweryfikowane'))
        assert bl._determine_packaging_target_status(order) is None
        assert bl._cel_po_stanowisku(list(order.products), 'packaging') is None
        order.override_delivery_method = s.TRANSPORT
        assert bl._cel_po_stanowisku(list(order.products), 'packaging') == s.STATUS_PLANOWANA_TRASA


def test_zalegly_138620_zostaje_przy_spakowaniu_bez_sposobu(app):
    """„Nie ustawiono” z cofnięciem do pakowania (138620) i ponowne spakowanie bez sposobu: ścieżka pakowania nic
    nie wysyła, więc 138620 zostaje (inaczej Base. zostałby na statusie po spakowaniu sprzed cofnięcia)."""
    with app.app_context():
        order = zamowienie(sposob=s.TRANSPORT, statusy=('spakowane',))
        d.ustaw_sposob_dostawy(order, s.BRAK, teraz=T0, przepakowanie=True)
        assert order.bl_status_pending_id == s.STATUS_PRODUKCJA_ZAKONCZONA
        order.products[0].current_status = 'spakowane'
        d.po_spakowaniu(order, T1)
        assert order.bl_status_pending_id == s.STATUS_PRODUKCJA_ZAKONCZONA
        assert order.repack_required is False
        assert order.logistics_closed_at is None


def test_ponowienie_138620_idzie_dla_spakowanego_bez_sposobu(app):
    with app.app_context():
        order = zamowienie(statusy=('spakowane',))
        numer = order.internal_order_number
        # Warunek stanowiska produkcyjnego dalej spełniony (spakowane ∈ POSTPROD), a status po spakowaniu nie poszedł.
        assert bl._powod_pominiecia_ponowienia(numer, 'edges', bl.PRODUCTION_COMPLETED_STATUS_ID) is None
        order.override_delivery_method = s.KURIER
        db.session.commit()
        assert bl._powod_pominiecia_ponowienia(
            numer, 'edges', bl.PRODUCTION_COMPLETED_STATUS_ID) == 'zamówienie już spakowane'


@pytest.mark.parametrize('nowy', [s.KURIER, s.TRANSPORT, s.ODBIOR])
def test_pierwsze_ustawienie_na_spakowanym_wymaga_decyzji_z_obiema_opcjami(app, nowy):
    with app.app_context():
        order = zamowienie(statusy=('spakowane', 'zweryfikowane'))
        with pytest.raises(d.LogistykaBlad) as e:
            d.ustaw_sposob_dostawy(order, nowy, teraz=T0)
        assert e.value.dane == {'kod': 'wymaga_decyzji_przepakowania',
                                'opcje': ['przepakuj', 'bez_przepakowania']}
        assert order.override_delivery_method is None


@pytest.mark.parametrize('nowy', [s.KURIER, s.TRANSPORT, s.ODBIOR])
def test_pierwsze_ustawienie_bez_przepakowania_wysyla_status_po_spakowaniu(app, nowy):
    with app.app_context():
        order = zamowienie(statusy=('spakowane',))
        wynik = d.ustaw_sposob_dostawy(order, nowy, teraz=T0, przepakowanie=False)
        assert wynik['zmieniono'] is True and wynik['przepakowanie'] is False
        assert order.bl_status_pending_id == s.STATUS_PO_SPAKOWANIU[nowy]
        assert order.products[0].current_status == 'spakowane'
        # Kurier spakowany zamyka cykl, transport i odbiór zostają otwarte (spec 6.2).
        assert (order.logistics_closed_at is not None) is (nowy == s.KURIER)


def test_pierwsze_ustawienie_z_przepakowaniem_cofa_do_pakowania(app):
    with app.app_context():
        order = zamowienie(statusy=('spakowane',))
        wynik = d.ustaw_sposob_dostawy(order, s.KURIER, teraz=T0, przepakowanie=True)
        assert wynik['przepakowanie'] is True
        assert order.products[0].current_status == 'czeka_na_pakowanie'
        assert order.repack_required is True
        assert order.bl_status_pending_id == s.STATUS_PRODUKCJA_ZAKONCZONA


def test_okno_8_7_przez_endpoint_panelu(app, client):
    with app.app_context():
        order = zamowienie(statusy=('spakowane',))
        oid = order.id
    j = client.post(BASE + '/orders/delivery-method', json={'order_ids': [oid], 'sposob': s.KURIER}).get_json()
    assert j['zmienione'] == []
    [b] = j['bledy']
    assert b['kod'] == 'wymaga_decyzji_przepakowania' and b['opcje'] == ['przepakuj', 'bez_przepakowania']
    j = client.post(BASE + '/orders/delivery-method',
                    json={'order_ids': [oid], 'sposob': s.KURIER, 'przepakowanie': False}).get_json()
    assert j['zmienione'] == [oid] and j['przepakowanie'] == []
    with app.app_context():
        wiersz = ProductionOrder.query.get(oid)
        assert wiersz.bl_status_pending_id == s.STATUS_SPAKOWANE
        assert wiersz.logistics_closed_at is not None


def test_czesciowo_spakowane_bez_sposobu_ustawienie_bez_okna_i_bez_statusu(app):
    """Spakowane częściowo: okna 8.7 nie ma (dotyczy tylko spakowanych w całości), spakowana pozycja zostaje,
    a status po spakowaniu wyśle ścieżka pakowania po ostatniej pozycji — już dla wybranego sposobu."""
    with app.app_context():
        order = zamowienie(statusy=('spakowane', 'czeka_na_pakowanie'))
        wynik = d.ustaw_sposob_dostawy(order, s.KURIER, teraz=T0)
        assert wynik['zmieniono'] is True and wynik['przepakowanie'] is False
        assert [p.current_status for p in order.products] == ['spakowane', 'czeka_na_pakowanie']
        assert order.bl_status_pending_id is None
        order.products[1].current_status = 'spakowane'
        assert bl._cel_po_stanowisku(list(order.products), 'packaging') == s.STATUS_SPAKOWANE


def test_czesciowo_spakowane_bez_sposobu_nie_ustawiono_to_brak_zmiany(app):
    with app.app_context():
        order = zamowienie(statusy=('spakowane', 'czeka_na_pakowanie'))
        assert d.ustaw_sposob_dostawy(order, s.BRAK, teraz=T0)['zmieniono'] is False


def test_etykieta_nie_ustawiono_zapala_ikone_po_ustawieniu_sposobu(app):
    with app.app_context():
        order = zamowienie(statusy=('spakowane',))
        napis = paczki_druk.napis_sposobu(order, None)
        assert napis == 'NIE USTAWIONO'
        paczka = ProductionPackage(order_id=order.id, seq=1, kind='paczka', declared_at=T0,
                                   label_printed_at=T0, label_print_count=1, label_delivery_text=napis)
        db.session.add(paczka)
        db.session.commit()
        assert lista._etykiety_paczek_sprzed_zmiany(order, None, [paczka]) is False
        d.ustaw_sposob_dostawy(order, s.ODBIOR, teraz=T1, przepakowanie=False)
        db.session.commit()
        assert lista._etykiety_paczek_sprzed_zmiany(order, None, [paczka]) is True


# ── Dopiski po przeglądzie kroku 4.6 ──────────────────────────────────────────

@pytest.fixture()
def base(monkeypatch):
    """Wywołania Base. i timer ponowień podmienione (jak w tests/test_logistyka_timer_statusu.py)."""
    stan = {'wyslane': [], 'zaplanowane': [], 'w_trakcie': None, 'dopychacz': 0}

    def wywolaj(baselinker_order_id, status_id):
        stan['wyslane'].append(status_id)
        if stan['w_trakcie']:
            stan['w_trakcie']()
        return True

    monkeypatch.setattr(bl, '_call_set_order_status', wywolaj)
    monkeypatch.setattr(bl, '_schedule_retry', lambda *a, **k: stan['zaplanowane'].append(k))
    monkeypatch.setattr('modules.production.logistics.services.bl_sync.uruchom_w_tle',
                        lambda app_: stan.__setitem__('dopychacz', stan['dopychacz'] + 1))
    return stan


def test_sciezka_pakowania_bez_sposobu_nic_nie_wysyla_i_nie_planuje(app, base):
    with app.app_context():
        order = zamowienie(statusy=('spakowane', 'spakowane'))
        bl._process_pending(app, order.internal_order_number, 'packaging')
    assert base['wyslane'] == [] and base['zaplanowane'] == []


def test_zweryfikowane_bez_sposobu_zmiana_bez_przepakowania_zostawia_weryfikacje(app):
    with app.app_context():
        order = zamowienie(statusy=('zweryfikowane', 'zweryfikowane'), verified_at=T0)
        d.ustaw_sposob_dostawy(order, s.TRANSPORT, teraz=T1, przepakowanie=False)
        assert [p.current_status for p in order.products] == ['zweryfikowane', 'zweryfikowane']
        assert order.verified_at == T0
        assert order.bl_status_pending_id == s.STATUS_PLANOWANA_TRASA
        assert order.logistics_closed_at is None


def test_cofniecie_z_weryfikacji_bez_sposobu_i_ponowne_spakowanie_zostawia_138620(app):
    from modules.production.logistics.services import weryfikacja
    with app.app_context():
        order = zamowienie(statusy=('spakowane',))
        order.products[0].packaging_completed_at = T1
        db.session.commit()
        weryfikacja.cofnij_do_pakowania(order, powod=sorted(weryfikacja.POWODY_PROBLEMU)[0], teraz=T1)
        assert order.bl_status_pending_id == s.STATUS_PRODUKCJA_ZAKONCZONA
        assert order.products[0].current_status == 'czeka_na_pakowanie'
        order.products[0].current_status = 'spakowane'
        d.po_spakowaniu(order, T1)
        assert order.bl_status_pending_id == s.STATUS_PRODUKCJA_ZAKONCZONA
        assert order.repack_required is False and order.logistics_closed_at is None


def test_czesciowo_spakowane_z_138620_po_ustawieniu_sposobu_i_spakowaniu_kasuje_138620(app):
    with app.app_context():
        order = zamowienie(statusy=('spakowane', 'czeka_na_pakowanie'),
                           bl_status_pending_id=s.STATUS_PRODUKCJA_ZAKONCZONA)
        d.ustaw_sposob_dostawy(order, s.ODBIOR, teraz=T0)
        order.products[1].current_status = 'spakowane'
        d.po_spakowaniu(order, T1)
        assert order.bl_status_pending_id is None   # status po spakowaniu wysyła ścieżka pakowania
        assert bl._cel_po_stanowisku(list(order.products), 'packaging') == s.STATUS_CZEKA_NA_ODBIOR


def test_okno_8_7_przez_endpoint_z_przepakowaniem(app, client):
    with app.app_context():
        oid = zamowienie(statusy=('spakowane',)).id
    j = client.post(BASE + '/orders/delivery-method',
                    json={'order_ids': [oid], 'sposob': s.KURIER, 'przepakowanie': True}).get_json()
    assert j['zmienione'] == [oid] and j['przepakowanie'] == [oid]
    with app.app_context():
        wiersz = ProductionOrder.query.get(oid)
        assert wiersz.override_delivery_method == s.KURIER and wiersz.repack_required is True
        assert wiersz.products[0].current_status == 'czeka_na_pakowanie'
        assert wiersz.bl_status_pending_id == s.STATUS_PRODUKCJA_ZAKONCZONA


def test_spoznione_138620_po_ustawieniu_sposobu_stawia_znacznik_ponownie(app, base):
    """Ponowienie 138620 (spakowane bez sposobu) trwa; w tym czasie logistyk ustawia kuriera, a dopychacz wysyła
    status po spakowaniu i zdejmuje znacznik. Spóźnione 138620 cofnęłoby Base. — znacznik wraca, dopychacz rusza."""
    with app.app_context():
        order = zamowienie(statusy=('spakowane',))
        oid, numer, bl_id = order.id, order.internal_order_number, order.baselinker_order_id

    def logistyk_w_trakcie():
        db.session.execute(db.text("UPDATE prod_orders SET override_delivery_method=:m, bl_status_pending_id=NULL "
                                   "WHERE id=:o"), {'m': s.KURIER, 'o': oid})
        db.session.commit()
    base['w_trakcie'] = logistyk_w_trakcie
    bl._retry_attempt(app=app, baselinker_order_id=bl_id, target_status_id=bl.PRODUCTION_COMPLETED_STATUS_ID,
                      internal_order_number=numer, attempt=1, station_code='edges')
    assert base['wyslane'] == [bl.PRODUCTION_COMPLETED_STATUS_ID]
    assert base['dopychacz'] == 1
    with app.app_context():
        assert ProductionOrder.query.get(oid).bl_status_pending_id == s.STATUS_SPAKOWANE


@pytest.mark.parametrize('sposob, znacznik', [(None, None), (s.KURIER, s.STATUS_PRODUKCJA_ZAKONCZONA)])
def test_spoznione_138620_bez_zmiany_gdy_nie_ma_czego_poprawiac(app, base, sposob, znacznik):
    with app.app_context():
        order = zamowienie(sposob=sposob, statusy=('spakowane',), bl_status_pending_id=znacznik)
        oid, numer = order.id, order.internal_order_number
    bl._po_spoznionym_138620(app, numer)
    assert base['dopychacz'] == 0
    with app.app_context():
        assert ProductionOrder.query.get(oid).bl_status_pending_id == znacznik
