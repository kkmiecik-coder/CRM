# -*- coding: utf-8 -*-
"""
Wysyłka decyzji logistyki do Base. (spec, sekcja 6.3).

LIMIT API: 100 zapytań/min NA CAŁE KONTO, wspólny z synchronizacją CRM.
24.09.2026 skrypt bez odstępu zablokował token całego konta (memory:
feedback_baselinker_limit_api). Dlatego:
  - decyzja zapisuje w zamówieniu ZNACZNIKI (przeżywają restart gunicorna),
  - wysyła JEDEN wątek na cały serwer (dzierżawa, services/dzierzawa.py),
  - odstęp ODSTEP_S między zapytaniami (≤ 40/min),
  - „Query limit exceeded / token blocked until …” wstrzymuje wszystkie
    wysyłki logistyki do podanej chwili (zapisanej w prod_config).
TIMEOUT: sync worker gunicorna ma 30 s na żądanie — Base. wołamy WYŁĄCZNIE
z wątku w tle (uruchom_w_tle), nigdy w żądaniu HTTP.
"""
import json
import re
import threading
import time
from datetime import datetime, timedelta

from flask import current_app
from sqlalchemy import or_

from extensions import db
from modules.logging import get_structured_logger
from modules.production.logistics import sposoby
from modules.production.logistics.services import dzierzawa
from modules.production.models import ProductionOrder, get_local_now

logger = get_structured_logger('production.logistics.bl_sync')

ODSTEP_S = 1.5
CZAS_DZIERZAWY_S = 90
DOMYSLNA_PAUZA = timedelta(minutes=15)
KLUCZ_DZIERZAWY = 'logistyka_bl_dzierzawa'
KLUCZ_PAUZY = 'logistyka_bl_wstrzymane_do'
_WZOR_BLOKADY = re.compile(r'until\s+(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2}:\d{2})')


class LimitBase(Exception):
    """Base. odrzucił zapytanie z powodu limitu — nie pytamy do `do_kiedy`."""

    def __init__(self, do_kiedy):
        super().__init__(str(do_kiedy))
        self.do_kiedy = do_kiedy


# ── Pauza po limicie ───────────────────────────────────────────────────────

def wstrzymane_do(teraz=None):
    teraz = teraz or get_local_now()
    db.session.expire_all()
    try:
        chwila = datetime.fromisoformat(dzierzawa.wiersz(KLUCZ_PAUZY).config_value)
    except ValueError:
        return None
    return chwila if chwila > teraz else None


def wstrzymaj_do(chwila):
    rekord = dzierzawa.wiersz(KLUCZ_PAUZY)
    rekord.config_value = chwila.replace(microsecond=0).isoformat()
    db.session.commit()


# ── Pojedyncze zapytanie i zamówienie ─────────────────────────────────────

def _wywolaj(metoda, parametry):
    """True przy SUCCESS, False przy błędzie; LimitBase przy limicie konta."""
    from modules.production.services.sync_service import get_sync_service
    serwis = get_sync_service()
    if serwis is None or not getattr(serwis, 'api_key', None):
        logger.error("Brak klucza API Base. - wysylka logistyki pominieta")
        return False
    try:
        odpowiedz = serwis._make_api_request({
            'token': serwis.api_key, 'method': metoda,
            'parameters': json.dumps(parametry)})
    except Exception as e:  # SyncError po wyczerpaniu prób sieciowych
        logger.error("Blad sieci przy wysylce logistyki do Base.", extra={
            'metoda': metoda, 'error': str(e)})
        return False
    if odpowiedz.get('status') == 'SUCCESS':
        return True
    komunikat = odpowiedz.get('error_message') or ''
    if 'limit' in komunikat.lower() or 'blocked' in komunikat.lower():
        dopasowanie = _WZOR_BLOKADY.search(komunikat)
        if dopasowanie:
            do_kiedy = datetime.fromisoformat('{}T{}'.format(*dopasowanie.groups()))
        else:
            do_kiedy = get_local_now() + DOMYSLNA_PAUZA
        raise LimitBase(do_kiedy)
    logger.error("Base. odrzucil zapis logistyki", extra={
        'metoda': metoda, 'order_id': parametry.get('order_id'), 'error': komunikat})
    return False


def wyslij_zamowienie(order):
    """Wysyła znaczniki jednego zamówienia. Zwraca liczbę zapytań. NIE commituje."""
    if not order.baselinker_order_id:
        order.bl_delivery_method_pending = False
        order.bl_status_pending_id = None
        return 0
    zapytania = 0
    if order.bl_delivery_method_pending:
        tekst = sposoby.TEKST_BASE.get(sposoby.normalizuj(order.override_delivery_method))
        if tekst is None or (order.delivery_method or '').strip() == tekst:
            order.bl_delivery_method_pending = False
        else:
            zapytania += 1
            if _wywolaj('setOrderFields', {'order_id': order.baselinker_order_id,
                                           'delivery_method': tekst}):
                order.delivery_method = tekst
                order.bl_delivery_method_pending = False
    if order.bl_status_pending_id:
        zapytania += 1
        if _wywolaj('setOrderStatus', {'order_id': order.baselinker_order_id,
                                       'status_id': order.bl_status_pending_id}):
            order.bl_status_pending_id = None
    return zapytania


# ── Dopychacz ─────────────────────────────────────────────────────────────

def _czeka(order):
    return bool(order.bl_delivery_method_pending or order.bl_status_pending_id)


def dopychaj(limit_zapytan=None, limit_czasu_s=None, spij=time.sleep, zegar=time.monotonic):
    wynik = {'zamowienia': 0, 'zapytania': 0, 'wstrzymane': False, 'dzierzawa': False}
    if wstrzymane_do() is not None:
        wynik['wstrzymane'] = True
        return wynik
    znacznik = dzierzawa.przejmij(KLUCZ_DZIERZAWY, CZAS_DZIERZAWY_S)
    if znacznik is None:
        return wynik
    wynik['dzierzawa'] = True
    start = zegar()
    pominiete = []
    try:
        while True:
            if limit_zapytan is not None and wynik['zapytania'] >= limit_zapytan:
                break
            if limit_czasu_s is not None and zegar() - start >= limit_czasu_s:
                break
            zapytanie = ProductionOrder.query.filter(or_(
                ProductionOrder.bl_delivery_method_pending.is_(True),
                ProductionOrder.bl_status_pending_id.isnot(None)))
            if pominiete:
                zapytanie = zapytanie.filter(~ProductionOrder.id.in_(pominiete))
            order = zapytanie.order_by(ProductionOrder.id).first()
            if order is None:
                break
            try:
                zapytania = wyslij_zamowienie(order)
            except LimitBase as e:
                db.session.commit()  # to, co przeszło przed limitem, zostaje
                wstrzymaj_do(e.do_kiedy)
                logger.error("Limit API Base. - wysylki logistyki wstrzymane", extra={
                    'do_kiedy': e.do_kiedy.isoformat()})
                wynik['wstrzymane'] = True
                wynik['zapytania'] += 1
                break
            db.session.commit()
            wynik['zamowienia'] += 1
            wynik['zapytania'] += zapytania
            if _czeka(order):
                pominiete.append(order.id)  # nieudane — nie mielimy w kółko w tym przebiegu
            znacznik = dzierzawa.odnow(KLUCZ_DZIERZAWY, znacznik, CZAS_DZIERZAWY_S)
            if znacznik is None:
                break
            if zapytania:
                spij(ODSTEP_S)
    finally:
        if znacznik:
            dzierzawa.zwolnij(KLUCZ_DZIERZAWY, znacznik)
    return wynik


_watek = None
_blokada_watku = threading.Lock()


def uruchom_w_tle(app):
    """Jeden wątek na proces; między procesami porządku pilnuje dzierżawa."""
    global _watek
    with _blokada_watku:
        if _watek is not None and _watek.is_alive():
            return False

        def _praca():
            with app.app_context():
                try:
                    dopychaj()
                except Exception as e:
                    logger.error("Dopychacz logistyki przerwany", extra={'error': str(e)})
                finally:
                    db.session.remove()

        _watek = threading.Thread(target=_praca, name='logistyka-base', daemon=True)
        _watek.start()
        return True


def po_zmianie(order_ids):
    """Wołać PO commicie decyzji logistyka. Nigdy nie woła Base. w żądaniu (timeout 30 s)."""
    if not order_ids:
        return
    uruchom_w_tle(current_app._get_current_object())


# ── Furtka pod stanowisko kierowcy (etap „kierowca”, dziś NIEWOŁANE) ──────

def oznacz_wyslane(order):
    order.bl_status_pending_id = sposoby.STATUS_WYSLANE_TRANSPORT


def oznacz_dostarczone(order):
    order.bl_status_pending_id = sposoby.STATUS_DOSTARCZONE_TRANSPORT
