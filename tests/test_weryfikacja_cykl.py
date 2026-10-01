# -*- coding: utf-8 -*-
"""Cykl zamówienia w logistyce po nowych statusach (logistyka etap 4, krok 4.3, spec 4.1, 4.2, 4.5, 4.6, 8.5)."""
from datetime import datetime

import pytest

from extensions import db
from modules.production.logistics import sposoby as s
from modules.production.logistics.models import LogisticsLog
from modules.production.logistics.services import bl_sync, delivery as d, paczki
from modules.production.models import ProductionOrder, ProductionPackage, ProductionProduct
from tests.logistyka_fixtures import BASE, app, client, produkt, zamowienie  # noqa: F401

T0 = datetime(2026, 10, 1, 8, 0)
T1 = datetime(2026, 10, 1, 9, 0)


def _paczki(order, n=2, zweryfikowane=False):
    lista = [ProductionPackage(order_id=order.id, seq=i, kind='paczka', declared_at=T0,
                               verified_at=T0 if zweryfikowane else None) for i in range(1, n + 1)]
    db.session.add_all(lista)
    order.packages_declared_at = T0
    db.session.commit()
    return lista


def test_spakowane_lub_dalej_i_dokladnie_spakowane(app):
    order = zamowienie(sposob=s.KURIER, statusy=('zweryfikowane', 'dostarczone', 'anulowane'))
    assert d.wszystkie_spakowane(order) is True
    assert d.wszystkie_w(order, ('spakowane',)) is False
    assert d.wszystkie_w(zamowienie(statusy=('anulowane',)), s.STATUSY_PO_SPAKOWANIU) is False
    assert d.STATUSY_PO_PRODUKCJI == ('czeka_na_pakowanie',) + s.STATUSY_PO_SPAKOWANIU


@pytest.mark.parametrize('sposob, statusy, kolumny, zamkniete', [
    (s.KURIER, ('zweryfikowane',), {}, True),
    (s.KURIER, ('spakowane', 'zweryfikowane'), {}, True),
    (s.KURIER, ('zweryfikowane', 'czeka_na_pakowanie'), {}, False),
    (s.TRANSPORT, ('zweryfikowane',), {}, False),          # transport zamyka trasa wykonana (decyzja 2)
    (s.ODBIOR, ('dostarczone',), {'handed_over_at': T0}, True),
])
def test_zamkniecie_po_nowych_statusach(app, sposob, statusy, kolumny, zamkniete):
    assert d.zamkniecie_wyliczone(zamowienie(sposob=sposob, statusy=statusy, **kolumny)) is zamkniete


@pytest.mark.parametrize('statusy', [('spakowane',), ('zweryfikowane',), ('spakowane', 'anulowane')])
def test_wydanie_klientowi_ustawia_dostarczone(app, statusy):
    order = zamowienie(sposob=s.ODBIOR, statusy=statusy)
    d.wydaj_klientowi(order, user_id=5, teraz=T0)
    assert [p.current_status for p in order.products] == \
        ['anulowane' if st == 'anulowane' else 'dostarczone' for st in statusy]
    assert (order.handed_over_at, order.bl_status_pending_id, order.logistics_closed_at) == \
        (T0, s.STATUS_ODEBRANE, T0)
    assert all(p.updated_at == T0 for p in order.products)


@pytest.mark.parametrize('statusy', [('czeka_na_pakowanie', 'spakowane'), ('zaladowane',)])
def test_wydanie_tylko_ze_spakowanego_albo_zweryfikowanego(app, statusy):
    with pytest.raises(d.LogistykaBlad):
        d.wydaj_klientowi(zamowienie(sposob=s.ODBIOR, statusy=statusy), teraz=T0)


def test_cofniecie_do_nie_ustawiono_odmawia_przy_zweryfikowanym(app):
    order = zamowienie(sposob=s.KURIER, statusy=('zweryfikowane',))
    with pytest.raises(d.LogistykaBlad) as e:
        d.ustaw_sposob_dostawy(order, s.BRAK, teraz=T0)
    # Spec 8.7: zamówienie w całości spakowane (także zweryfikowane) dostaje decyzję zamiast dawnego błędu
    # „nie da się cofnąć”; „Nie ustawiono” jest możliwe tylko razem z cofnięciem do pakowania.
    assert e.value.dane['kod'] == 'wymaga_decyzji_przepakowania'
    assert e.value.dane['opcje'] == ['przepakuj']


def test_przepakowanie_zweryfikowanego_uniewaznia_paczki_i_weryfikacje(app):
    order = zamowienie(sposob=s.TRANSPORT, statusy=('zweryfikowane', 'zweryfikowane'),
                       verified_at=T0, verified_by_worker_id=3)
    stare = _paczki(order, zweryfikowane=True)
    wynik = d.ustaw_sposob_dostawy(order, s.KURIER, user_id=7, teraz=T1, przepakowanie=True)
    db.session.commit()
    assert wynik['przepakowanie'] is True
    assert [p.current_status for p in order.products] == ['czeka_na_pakowanie', 'czeka_na_pakowanie']
    assert (order.repack_required, order.repack_reason) == (True, s.PRZEPAKUJ_NA_KURIERA)
    assert (order.verified_at, order.packages_declared_at) == (None, None)
    assert all(p.voided_at == T1 for p in ProductionPackage.query.filter_by(order_id=order.id))
    akcje = [w.action for w in LogisticsLog.query.filter_by(order_id=order.id).order_by(LogisticsLog.id)]
    assert akcje[:2] == ['sposob_dostawy', 'przepakowanie']
    assert set(akcje[2:]) == {'weryfikacja_cofnieta', 'paczki'}
    assert order.bl_status_pending_id == s.STATUS_PRODUKCJA_ZAKONCZONA


def test_zmiana_na_inny_niz_kurier_i_spakowanie_czyszcza_baner(app):
    order = zamowienie(sposob=s.KURIER, statusy=('czeka_na_pakowanie',), repack_required=True,
                       repack_reason=s.PRZEPAKUJ_NA_KURIERA)
    d.ustaw_sposob_dostawy(order, s.TRANSPORT, teraz=T0)
    assert (order.repack_required, order.repack_reason) == (False, None)
    drugie = zamowienie(sposob=s.KURIER, statusy=('spakowane',), repack_required=True,
                        repack_reason=u'Weryfikacja: Uszkodzenie')
    d.po_spakowaniu(drugie, T0)
    assert (drugie.repack_required, drugie.repack_reason) == (False, None)


@pytest.mark.parametrize('nowy', [s.TRANSPORT, s.ODBIOR])
def test_zmiana_sposobu_nie_kasuje_banera_z_weryfikacji(app, nowy):
    """Weryfikacja cofnęła zamówienie do pakowania („Uszkodzenie”) — zmiana sposobu przez logistyka
    nie może zabrać pakowaczowi tej informacji; czyści ją dopiero ponowne spakowanie."""
    tekst = u'Weryfikacja: Uszkodzenie: pęknięty blat'
    order = zamowienie(sposob=s.KURIER, statusy=('czeka_na_pakowanie',), repack_required=True, repack_reason=tekst)
    d.ustaw_sposob_dostawy(order, nowy, teraz=T0)
    assert (order.repack_required, order.repack_reason) == (True, tekst)
    for p in order.products:
        p.current_status = 'spakowane'
    d.po_spakowaniu(order, T1)
    assert (order.repack_required, order.repack_reason) == (False, None)


# --- Przepakowanie na kuriera a baner Weryfikacji (fala końcowa 4.3, F4) --------------------------

def test_przepakowanie_na_kuriera_nie_nadpisuje_banera_z_weryfikacji(app):
    """Zamówienie cofnięte z Weryfikacji z powodem („Uszkodzenie”), potem spakowane ponownie przy
    transporcie: zmiana na kuriera przepakowuje je, ale powód z Weryfikacji jest ważniejszy niż
    „Przepakuj na kuriera” — sposób „kurier” pakowacz widzi na tablecie i tak."""
    tekst = u'Weryfikacja: Uszkodzenie: pęknięty blat'
    order = zamowienie(sposob=s.TRANSPORT, statusy=('spakowane', 'spakowane'),
                       repack_required=True, repack_reason=tekst)
    wynik = d.ustaw_sposob_dostawy(order, s.KURIER, teraz=T1, przepakowanie=True)
    assert wynik['przepakowanie'] is True
    assert (order.repack_required, order.repack_reason) == (True, tekst)
    assert [p.current_status for p in order.products] == ['czeka_na_pakowanie', 'czeka_na_pakowanie']


@pytest.mark.parametrize('powod', [None, u'', s.PRZEPAKUJ_NA_KURIERA])
def test_przepakowanie_na_kuriera_bez_powodu_z_weryfikacji_ustawia_przepakuj_na_kuriera(app, powod):
    order = zamowienie(sposob=s.TRANSPORT, statusy=('spakowane',), repack_required=bool(powod),
                       repack_reason=powod)
    d.ustaw_sposob_dostawy(order, s.KURIER, teraz=T1, przepakowanie=True)
    assert (order.repack_required, order.repack_reason) == (True, s.PRZEPAKUJ_NA_KURIERA)


# --- Panel: zmiana sposobu dostawy na prawdziwych paczkach (fala końcowa 4.3, F6b) ----------------

@pytest.fixture()
def bez_base(monkeypatch):
    wywolane = []
    monkeypatch.setattr(bl_sync, 'po_zmianie', lambda ids: wywolane.append(list(ids)))
    return wywolane


def _zmien_sposob_w_panelu(client, order, sposob):
    # Wszystkie wołania w tym pliku to zmiana na kuriera z transportu na zamówieniu w całości spakowanym —
    # dawne automatyczne przepakowanie, od spec 8.7 jawna decyzja logistyka.
    return client.post(BASE + '/orders/delivery-method',
                       json={'order_ids': [order.id], 'sposob': sposob, 'przepakowanie': True})


def test_panel_transport_na_kuriera_uniewaznia_paczki_i_ustawia_powod(app, client, bez_base):
    """Styk zadań: POST panelu → ustaw_sposob_dostawy → prawdziwa reguła unieważnienia etapów."""
    order = zamowienie(sposob=s.TRANSPORT, statusy=('spakowane', 'spakowane'))
    _paczki(order, n=2, zweryfikowane=True)
    order_id = order.id
    r = _zmien_sposob_w_panelu(client, order, s.KURIER)
    assert r.status_code == 200, r.get_json()
    assert r.get_json()['przepakowanie'] == [order_id]
    db.session.expire_all()
    o = ProductionOrder.query.get(order_id)
    assert [p.current_status for p in o.products] == ['czeka_na_pakowanie', 'czeka_na_pakowanie']
    assert (o.repack_required, o.repack_reason) == (True, s.PRZEPAKUJ_NA_KURIERA)
    paczki_zamowienia = ProductionPackage.query.filter_by(order_id=order_id).all()
    assert len(paczki_zamowienia) == 2 and all(p.voided_at is not None for p in paczki_zamowienia)
    assert o.packages_declared_at is None and o.bl_status_pending_id == s.STATUS_PRODUKCJA_ZAKONCZONA
    assert 'paczki' in [w.action for w in LogisticsLog.query.filter_by(order_id=order_id)]


def test_panel_transport_na_kuriera_nie_nadpisuje_banera_weryfikacji(app, client, bez_base):
    tekst = u'Weryfikacja: Brak elementu: nóżka'
    order = zamowienie(sposob=s.TRANSPORT, statusy=('spakowane', 'spakowane'),
                       repack_required=True, repack_reason=tekst)
    _paczki(order, n=2)
    order_id = order.id
    assert _zmien_sposob_w_panelu(client, order, s.KURIER).status_code == 200
    db.session.expire_all()
    o = ProductionOrder.query.get(order_id)
    assert (o.repack_required, o.repack_reason) == (True, tekst)       # baner Weryfikacji zostaje
    assert [p.current_status for p in o.products] == ['czeka_na_pakowanie', 'czeka_na_pakowanie']
    assert all(p.voided_at is not None for p in ProductionPackage.query.filter_by(order_id=order_id))


def test_panel_zmiana_na_kuriera_po_zatwierdzonym_cofnij_weryfikacje_loguje_jedno_cofniecie(
        app, client, bez_base, monkeypatch):
    """F10: panel czyta zamówienie z migawki (zweryfikowane), a „Cofnij weryfikację” z telefonu zdążyło się
    już zatwierdzić. Zmiana sposobu na kuriera nie dopisuje drugiego `weryfikacja_cofnieta` — reguła
    potwierdza pracę na odczycie bieżącym. Przepakowanie wygrywa, paczki tracą ważność."""
    order = zamowienie(sposob=s.TRANSPORT, statusy=('zweryfikowane', 'zweryfikowane'),
                       verified_at=T0, verified_by_worker_id=3)
    _paczki(order, n=2, zweryfikowane=True)
    order_id = order.id
    oryginal = d.ustaw_sposob_dostawy

    def po_cudzym_cofnij_weryfikacje(zamowienie_panelu, *args, **kwargs):
        # Telefon zatwierdził „Cofnij weryfikację” po tym, jak panel wczytał zamówienie: surowe zapisy poza
        # ORM (w bazie stan nowy), a obiekty panelu w sesji zostają w starym stanie.
        assert zamowienie_panelu.verified_at == T0
        assert [p.current_status for p in zamowienie_panelu.products] == ['zweryfikowane', 'zweryfikowane']
        db.session.execute(ProductionOrder.__table__.update()
                           .where(ProductionOrder.__table__.c.id == order_id)
                           .values(verified_at=None, verified_by_worker_id=None))
        db.session.execute(ProductionProduct.__table__.update()
                           .where(ProductionProduct.__table__.c.order_id == order_id)
                           .values(current_status='spakowane'))
        db.session.execute(ProductionPackage.__table__.update()
                           .where(ProductionPackage.__table__.c.order_id == order_id)
                           .values(verified_at=None))
        db.session.execute(LogisticsLog.__table__.insert().values(
            order_id=order_id, action='weryfikacja_cofnieta', worker_id=3, note=u'Cofnij weryfikację',
            created_at=T1))
        return oryginal(zamowienie_panelu, *args, **kwargs)

    monkeypatch.setattr(d, 'ustaw_sposob_dostawy', po_cudzym_cofnij_weryfikacje)
    r = _zmien_sposob_w_panelu(client, order, s.KURIER)
    assert r.status_code == 200, r.get_json()
    db.session.expire_all()
    akcje = [w.action for w in LogisticsLog.query.filter_by(order_id=order_id).order_by(LogisticsLog.id)]
    assert akcje.count('weryfikacja_cofnieta') == 1                       # tylko wpis telefonu
    assert akcje.count('paczki') == 1 and akcje.count('przepakowanie') == 1
    o = ProductionOrder.query.get(order_id)
    assert o.verified_at is None and o.packages_declared_at is None
    assert [p.current_status for p in o.products] == ['czeka_na_pakowanie', 'czeka_na_pakowanie']
    assert (o.repack_required, o.repack_reason) == (True, s.PRZEPAKUJ_NA_KURIERA)
    assert all(p.voided_at is not None for p in ProductionPackage.query.filter_by(order_id=order_id))


def test_cofniecie_do_nie_ustawiono_nie_kasuje_banera_z_weryfikacji(app):
    tekst = u'Weryfikacja: Brak elementu: nóżka'
    order = zamowienie(sposob=s.KURIER, statusy=('czeka_na_pakowanie',), repack_required=True, repack_reason=tekst)
    d.ustaw_sposob_dostawy(order, s.BRAK, teraz=T0)
    assert order.override_delivery_method is None
    assert (order.repack_required, order.repack_reason) == (True, tekst)


@pytest.mark.parametrize('powod', [s.PRZEPAKUJ_NA_KURIERA, None, u''])
def test_cofniecie_do_nie_ustawiono_czysci_baner_przepakowania_na_kuriera(app, powod):
    """„Przepakuj na kuriera” (także stare repack_required bez tekstu) traci sens bez kuriera."""
    order = zamowienie(sposob=s.KURIER, statusy=('czeka_na_pakowanie',), repack_required=True, repack_reason=powod)
    d.ustaw_sposob_dostawy(order, s.BRAK, teraz=T0)
    assert (order.repack_required, order.repack_reason) == (False, None)


@pytest.mark.parametrize('powod', [None, u''])
def test_zmiana_na_transport_czysci_stare_przepakowanie_bez_tekstu(app, powod):
    order = zamowienie(sposob=s.KURIER, statusy=('czeka_na_pakowanie',), repack_required=True, repack_reason=powod)
    d.ustaw_sposob_dostawy(order, s.TRANSPORT, teraz=T0)
    assert (order.repack_required, order.repack_reason) == (False, None)


def test_zaladowane_nie_zmienia_sposobu(app):
    order = zamowienie(sposob=s.TRANSPORT, statusy=('zaladowane',))
    assert d.ustaw_sposob_dostawy(order, s.TRANSPORT, teraz=T0)['zmieniono'] is False  # bez zmiany = no-op
    with pytest.raises(d.LogistykaBlad) as e:
        d.ustaw_sposob_dostawy(order, s.KURIER, teraz=T0)
    assert e.value.status == 409


def test_cron_nie_otwiera_zweryfikowanego_i_czysci_etapy_po_nowej_pozycji(app):
    zweryfikowane = zamowienie(sposob=s.KURIER, statusy=('zweryfikowane',), logistics_closed_at=T0,
                               verified_at=T0)
    z_nowa = zamowienie(sposob=s.KURIER, statusy=('spakowane',), logistics_closed_at=T0)
    _paczki(z_nowa)
    produkt(z_nowa, status='czeka_na_wyciecie')
    db.session.commit()

    d.przelicz_otwarte(teraz=T1)
    db.session.commit()

    assert zweryfikowane.logistics_closed_at == T0 and zweryfikowane.verified_at == T0
    assert z_nowa.logistics_closed_at is None and z_nowa.packages_declared_at is None
    assert all(p.voided_at == T1 for p in ProductionPackage.query.filter_by(order_id=z_nowa.id))
    assert LogisticsLog.query.filter_by(order_id=z_nowa.id, action='paczki').one().note == u'kontrola cykliczna'


@pytest.mark.parametrize('status, fragment', [
    ('zweryfikowane', u'Cofnij weryfikację'), ('zaladowane', u'załadowane'), ('dostarczone', u'dostarczone')])
def test_deklaracja_po_weryfikacji_409(app, status, fragment):
    order = zamowienie(sposob=s.KURIER, statusy=(status, status))
    with pytest.raises(paczki.PaczkiBlad) as e:
        paczki.zadeklaruj(order, paczki.Deklaracja('paczka', 1), 'verification',
                          {'type': 'device', 'id': 'TEL-1'}, teraz=T0)
    assert (e.value.kod, e.value.status) == ('order_verified', 409) and fragment in e.value.komunikat


def test_deklaracja_dalej_wymaga_dokladnie_spakowanego(app):
    order = zamowienie(sposob=s.KURIER, statusy=('spakowane', 'czeka_na_pakowanie'))
    with pytest.raises(paczki.PaczkiBlad) as e:
        paczki.zadeklaruj(order, paczki.Deklaracja('paczka', 1), 'packaging',
                          {'type': 'device', 'id': 'TAB-1'}, teraz=T0)
    assert e.value.kod == 'order_not_packed'


def test_dorobka_uniewaznia_etapy(app):
    from modules.production.services import rework_service
    order = zamowienie(sposob=s.KURIER, statusy=('spakowane', 'czeka_na_pakowanie'))
    stare = _paczki(order, n=1)
    rework_service.reject_product_quantity(product_id=order.products[1].id, quantity=1,
                                           reason_category=sorted(rework_service.VALID_REASONS)[0],
                                           rejected_at_station='packaging')
    assert ProductionPackage.query.get(stare[0].id).voided_at is not None
    assert order.packages_declared_at is None


def test_nowa_pozycja_z_base_uniewaznia_etapy(app, monkeypatch):
    from modules.production.services.sync_service import BaselinkerSyncService
    order = zamowienie(sposob=s.KURIER, statusy=('zweryfikowane',), numer_wewnetrzny='1450',
                       verified_at=T0)
    stare = _paczki(order, n=1, zweryfikowane=True)
    serwis = BaselinkerSyncService()
    monkeypatch.setattr(serwis, 'get_order_from_baselinker', lambda _id: {
        'products': [{'order_product_id': '77', 'name': 'Blat', 'quantity': 1}]})
    monkeypatch.setattr('modules.production.services.parser_service.ProductNameParser.parse_product_name',
                        lambda self, nazwa: None)

    def nowa_pozycja(dane):
        return ProductionProduct(order_id=order.id, short_product_id=dane['short_product_id'],
                                 product_sequence_in_order=dane['product_sequence_in_order'],
                                 original_product_name=dane['original_product_name'], quantity=1,
                                 current_status='czeka_na_wyciecie')

    monkeypatch.setattr(serwis, '_create_production_product_from_data', nowa_pozycja)
    wynik = serwis.apply_baselinker_changes(order.baselinker_order_id,
                                            {'products_to_add': [{'order_product_id': '77'}]})
    assert wynik['success'] is True and wynik['added'] == 1
    db.session.expire_all()
    assert ProductionPackage.query.get(stare[0].id).voided_at is not None
    statusy = sorted(p.current_status for p in ProductionProduct.query.filter_by(order_id=order.id))
    assert statusy == ['czeka_na_wyciecie', 'spakowane']
