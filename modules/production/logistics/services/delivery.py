# -*- coding: utf-8 -*-
"""
Cykl życia zamówienia w logistyce (spec, sekcje 6.2 i 6.4).

Funkcje NIE commitują — robi to wołający (router, model, cron), żeby zmiana
sposobu dostawy, przepakowanie i log szły w jednej transakcji.
"""
from sqlalchemy.orm import selectinload

from extensions import db
from modules.production.logistics import sposoby
from modules.production.logistics.models import LogisticsLog
from modules.production.models import get_local_now

STATUSY_PO_PRODUKCJI = ('czeka_na_pakowanie', 'spakowane')


class LogistykaBlad(Exception):
    """Odmowa z komunikatem dla człowieka. status = kod HTTP (409 stan, 422 dane)."""

    def __init__(self, komunikat, status=409):
        super().__init__(komunikat)
        self.komunikat = komunikat
        self.status = status


def aktywne_produkty(order):
    return [p for p in order.products if p.current_status != 'anulowane']


def wszystkie_spakowane(order):
    aktywne = aktywne_produkty(order)
    return bool(aktywne) and all(p.current_status == 'spakowane' for p in aktywne)


def zapisz_log(order, akcja, stara=None, nowa=None, user_id=None, note=None,
               route_id=None, teraz=None):
    db.session.add(LogisticsLog(
        order_id=order.id, action=akcja, old_value=stara, new_value=nowa,
        user_id=user_id, note=note, route_id=route_id,
        created_at=teraz or get_local_now()))


def podbij_pozycje(order, teraz):
    """ETag kolejek tabletów liczy się z MAX(updated_at) pozycji — bez tego tablet dostanie 304."""
    for p in order.products:
        p.updated_at = teraz


def zamkniecie_wyliczone(order):
    """Tabela z sekcji 6.2 specu. Transport własny zamyka dopiero trasa wykonana (etap 3)."""
    aktywne = aktywne_produkty(order)
    if not aktywne:
        return True
    sposob = sposoby.normalizuj(order.override_delivery_method)
    if sposob is None or order.repack_required:
        return False
    if sposob == sposoby.KURIER:
        return all(p.current_status == 'spakowane' for p in aktywne)
    if sposob == sposoby.ODBIOR:
        return order.handed_over_at is not None
    return False


def przelicz_zamkniecie(order, teraz=None):
    """Ustawia albo czyści logistics_closed_at. Zwraca True, gdy stan się zmienił."""
    zamkniete = zamkniecie_wyliczone(order)
    if zamkniete and order.logistics_closed_at is None:
        order.logistics_closed_at = teraz or get_local_now()
        return True
    if not zamkniete and order.logistics_closed_at is not None:
        order.logistics_closed_at = None
        return True
    return False


def odnotuj_wejscie_do_pakowania(order, teraz):
    """„Zeszło z produkcji” (Arkusz): chwila, gdy OSTATNI aktywny produkt wszedł do pakowania."""
    if order.logistics_completed_at is not None:
        return
    aktywne = aktywne_produkty(order)
    if aktywne and all(p.current_status in STATUSY_PO_PRODUKCJI for p in aktywne):
        order.logistics_completed_at = teraz


def po_spakowaniu(order, teraz):
    """Wołane z complete_task('packaging'). Kończy przepakowanie i przelicza cykl."""
    if wszystkie_spakowane(order):
        # Zaległe 138620 z przepakowania nie może nadpisać statusu po spakowaniu,
        # który właśnie wysyła ścieżka pakowania (baselinker_status_sync).
        # NIEZALEŻNIE od flagi przepakowania: kurier (przepakowanie, 138620) →
        # z powrotem transport kasuje flagę, a znacznik 138620 zostaje.
        if order.bl_status_pending_id == sposoby.STATUS_PRODUKCJA_ZAKONCZONA:
            order.bl_status_pending_id = None
        if order.repack_required:
            order.repack_required = False
            podbij_pozycje(order, teraz)
    przelicz_zamkniecie(order, teraz)


def ustaw_sposob_dostawy(order, sposob, user_id=None, teraz=None):
    nowy = sposoby.normalizuj(sposob)
    if nowy is None:
        raise LogistykaBlad(u'Nieznany sposób dostawy: {}'.format(sposob), status=422)
    if order.handed_over_at is not None:
        raise LogistykaBlad(u'Zamówienie {} zostało już wydane klientowi.'.format(
            order.internal_order_number))
    if not aktywne_produkty(order):
        raise LogistykaBlad(u'Zamówienie {} jest anulowane.'.format(order.internal_order_number))

    stary = sposoby.normalizuj(order.override_delivery_method)
    if stary == nowy:
        return {'zmieniono': False, 'przepakowanie': False}

    teraz = teraz or get_local_now()
    order.override_delivery_method = nowy
    order.delivery_method_set_at = teraz
    order.delivery_method_set_by = user_id
    zapisz_log(order, 'sposob_dostawy', stary, nowy, user_id=user_id, teraz=teraz)

    spakowane = [p for p in aktywne_produkty(order) if p.current_status == 'spakowane']
    przepakowanie = (nowy == sposoby.KURIER
                     and stary in (sposoby.TRANSPORT, sposoby.ODBIOR)
                     and bool(spakowane))
    nowy_status = False
    if przepakowanie:
        order.repack_required = True
        for p in spakowane:
            # Zdarzenie systemowe bez atrybucji: cofnięcie spakowania nie jest
            # niczyją pracą, a statystyki pierwotnego pakowacza zostają.
            p.set_quantity_done('packaging', 0, source='system')
            p.packaging_completed_at = None
            p.current_status = 'czeka_na_pakowanie'
        if all(p.current_status in STATUSY_PO_PRODUKCJI for p in aktywne_produkty(order)):
            order.bl_status_pending_id = sposoby.STATUS_PRODUKCJA_ZAKONCZONA
            nowy_status = True
        zapisz_log(order, 'przepakowanie', stary, nowy, user_id=user_id, teraz=teraz)
    elif wszystkie_spakowane(order):
        order.bl_status_pending_id = sposoby.STATUS_PO_SPAKOWANIU[nowy]
        nowy_status = True

    if (not nowy_status
            and order.bl_status_pending_id in sposoby.STATUS_PO_SPAKOWANIU.values()
            and not wszystkie_spakowane(order)):
        # Niewysłany jeszcze status po spakowaniu poprzedniego sposobu (np. 149777
        # „Czeka na odbiór”), a zamówienie nie jest już w całości spakowane (Base.
        # dołożył pozycję, przepakowanie) — dopychacz wysłałby nieaktualny status.
        # Właściwy status po spakowaniu wyśle ścieżka pakowania, gdy wszystko się spakuje.
        order.bl_status_pending_id = None

    if (order.delivery_method or '').strip() != sposoby.TEKST_BASE[nowy]:
        order.bl_delivery_method_pending = True

    if nowy != sposoby.KURIER:
        # Zmiana na sposób inny niż kurier zamyka ewentualne przepakowanie:
        # towar już wrócił do pakowania i po prostu się pakuje, baner
        # „PRZEPAKUJ NA KURIERA” dla transportu/odbioru nie ma sensu.
        order.repack_required = False

    podbij_pozycje(order, teraz)
    przelicz_zamkniecie(order, teraz)
    return {'zmieniono': True, 'przepakowanie': przepakowanie}


def wydaj_klientowi(order, user_id=None, teraz=None):
    if sposoby.normalizuj(order.override_delivery_method) != sposoby.ODBIOR:
        raise LogistykaBlad(u'„Wydane klientowi” dotyczy tylko odbioru osobistego.')
    if order.handed_over_at is not None:
        raise LogistykaBlad(u'Zamówienie {} jest już wydane.'.format(order.internal_order_number))
    if not wszystkie_spakowane(order):
        raise LogistykaBlad(u'Zamówienie {} nie jest jeszcze w całości spakowane.'.format(
            order.internal_order_number))
    teraz = teraz or get_local_now()
    order.handed_over_at = teraz
    order.handed_over_by = user_id
    order.bl_status_pending_id = sposoby.STATUS_ODEBRANE
    zapisz_log(order, 'wydane', user_id=user_id, teraz=teraz)
    podbij_pozycje(order, teraz)
    przelicz_zamkniecie(order, teraz)


def przelicz_otwarte(teraz=None):
    """
    Siatka bezpieczeństwa dla crona: przelicza zamówienia otwarte oraz zamknięte,
    które znów mają aktywne produkty (Base. dołożył pozycję, doróbka).
    """
    from modules.production.models import ProductionOrder, ProductionProduct
    teraz = teraz or get_local_now()
    otwarte = (ProductionOrder.query.options(selectinload(ProductionOrder.products))
               .filter(ProductionOrder.logistics_closed_at.is_(None)).all())
    do_otwarcia = (ProductionOrder.query.options(selectinload(ProductionOrder.products))
                   .filter(ProductionOrder.logistics_closed_at.isnot(None))
                   .filter(ProductionOrder.products.any(
                       ProductionProduct.current_status.notin_(('spakowane', 'anulowane'))))
                   .all())
    return sum(1 for order in otwarte + do_otwarcia if przelicz_zamkniecie(order, teraz))
