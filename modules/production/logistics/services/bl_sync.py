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
import traceback
from datetime import datetime, timedelta

from flask import current_app
from sqlalchemy import or_, text

from extensions import db
from modules.logging import get_structured_logger
from modules.production.logistics import sposoby
from modules.production.logistics.services import dzierzawa
from modules.production.models import ProductionOrder, get_local_now

logger = get_structured_logger('production.logistics.bl_sync')

ODSTEP_S = 1.5
# Prawdziwy _make_api_request (sync_service.py) ponawia 3x z timeoutem 30 s i uśpieniem
# 5/10 s między próbami — jedno wywołanie w najgorszym razie trwa ~105 s. Dzierżawa musi
# przeżyć choć jedno takie wywołanie z zapasem (odnawiamy ją dopiero MIĘDZY zamówieniami,
# nie w trakcie pojedynczego wywołania) — stąd > 2x najgorszy pojedynczy czas (R2/F2a).
CZAS_DZIERZAWY_S = 300
DOMYSLNA_PAUZA = timedelta(minutes=15)
KLUCZ_DZIERZAWY = 'logistyka_bl_dzierzawa'
KLUCZ_PAUZY = 'logistyka_bl_wstrzymane_do'
_WZOR_BLOKADY = re.compile(r'until\s+(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2}:\d{2})')


class LimitBase(Exception):
    """Base. odrzucił zapytanie z powodu limitu — nie pytamy do `do_kiedy`."""

    def __init__(self, do_kiedy):
        super().__init__(str(do_kiedy))
        self.do_kiedy = do_kiedy


class BladPolaczenia(Exception):
    """
    Nie wiemy, czy zapytanie dotarło do Base. (brak klucza API, timeout, wyjątek
    transportu) — w odróżnieniu od `LimitBase` to NIE jest odpowiedź Base. o limicie,
    więc nie zapisujemy pauzy. Mimo to przerywamy CAŁY przebieg dopychacza (nie tylko
    to zamówienie): skoro sieć/konfiguracja nie działa teraz, kolejne zamówienia w tym
    samym przebiegu i tak by padły tym samym błędem (R2/F2b).
    """


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
    """
    True przy SUCCESS, False przy odpowiedzi Base. z błędem (np. zły order_id — to
    zamówienie zostaje z niewysłanym znacznikiem, reszta przebiegu jedzie dalej).
    LimitBase przy limicie konta (Base. odpowiedziało, ale odmówiło). BladPolaczenia,
    gdy nie ma jak wysłać (brak klucza) albo nie wiadomo, co się stało (wyjątek sieci) —
    to przerywa CAŁY przebieg dopychacza, patrz docstring `BladPolaczenia` (F2b).
    """
    from modules.production.services.sync_service import get_sync_service
    serwis = get_sync_service()
    if serwis is None or not getattr(serwis, 'api_key', None):
        logger.error("Brak klucza API Base. - wysylka logistyki pominieta")
        raise BladPolaczenia('Brak klucza API Base.')
    try:
        odpowiedz = serwis._make_api_request({
            'token': serwis.api_key, 'method': metoda,
            'parameters': json.dumps(parametry)})
    except Exception as e:  # SyncError po wyczerpaniu prób sieciowych (retry w sync_service)
        # StructuredLogger.error ignoruje exc_info (tylko doklejaloby tekst "exc_info=True"
        # do wiadomosci, patrz modules/logging/structured_logger.py) — traceback wprost w
        # extra, zeby faktycznie trafil do logu (fix round 2, Minor)
        logger.error("Blad sieci przy wysylce logistyki do Base.", extra={
            'metoda': metoda, 'error': str(e), 'traceback': traceback.format_exc()})
        # timeout NIE oznacza porazki po stronie Base. — moglo sie udac; zgadywanie dalej
        # bez wiedzy o stanie po drugiej stronie jest gorsze niz przerwanie przebiegu
        raise BladPolaczenia(str(e))
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


def _wyczysc_metode(order, sposob_wyslany):
    """
    Czyści `bl_delivery_method_pending` TYLKO gdy `override_delivery_method` w bazie
    wciąż jest tym samym sposobem, który właśnie wysłaliśmy do Base. (F3/R3). Jeśli
    logistyk zmienił decyzję W TRAKCIE trwania zapytania HTTP (setOrderFields), znacznik
    ma zostać — inaczej nowsza decyzja przepadłaby bez wysyłki. Warunkowy UPDATE (nie
    zwykłe przypisanie w Pythonie), żeby sprawdzić bazę TAKĄ, jaka jest TERAZ, a nie
    z chwili, gdy wczytaliśmy `order` na początku pętli dopychacza.
    """
    wynik = db.session.execute(
        text('UPDATE prod_orders SET bl_delivery_method_pending = 0 '
             'WHERE id = :id AND override_delivery_method = :sposob'),
        {'id': order.id, 'sposob': sposob_wyslany})
    if wynik.rowcount == 1:
        order.bl_delivery_method_pending = False
        return True
    # ktoś nadpisał decyzję w trakcie wywołania — odświeżamy (wygaszamy) w pamięci, żeby
    # kolejna próba w TYM SAMYM przebiegu dopychacza zobaczyła nową wartość, nie starą
    db.session.expire(order, ['override_delivery_method', 'bl_delivery_method_pending'])
    return False


def _wyczysc_status(order, wyslany_status_id):
    """Jak `_wyczysc_metode`, ale dla statusu Base. (np. stanowisko kierowcy może
    ustawić nowy `bl_status_pending_id` w trakcie trwania naszego zapytania)."""
    wynik = db.session.execute(
        text('UPDATE prod_orders SET bl_status_pending_id = NULL '
             'WHERE id = :id AND bl_status_pending_id = :wyslany'),
        {'id': order.id, 'wyslany': wyslany_status_id})
    if wynik.rowcount == 1:
        order.bl_status_pending_id = None
        return True
    db.session.expire(order, ['bl_status_pending_id'])
    return False


def _swiezy_status(order_id):
    """
    Wartość `bl_status_pending_id` z bazy TERAZ — tuż przed setOrderStatus.

    Znacznik wczytany na początku pętli dopychacza mógł się zmienić w trakcie
    setOrderFields (do ~105 s): pakowacz skończył przepakowanie i `po_spakowaniu`
    skasował 138620, logistyk kliknął „Wydane klientowi” (149779). Wysłanie wartości
    z pamięci cofnęłoby Base. do nieaktualnego statusu.

    Zwykły SELECT kolumny na OSOBNYM, krótkim połączeniu z puli, nie przez sesję:
      - w MySQL (REPEATABLE READ) SELECT w transakcji sesji czytałby migawkę z jej
        pierwszego odczytu — czyli z chwili wczytania zamówienia, tę samą starą
        wartość, którą mamy w pamięci; nowe połączenie = nowa migawka po commitach
        innych procesów,
      - bez blokady (nie FOR UPDATE / FOR SHARE), a połączenie zamykamy od razu,
        więc nic nie trzyma wiersza w czasie drugiego wywołania HTTP,
      - bez flush zmian zamówienia (połączenie z silnika, nie sesja ORM) — między
        dwoma wywołaniami Base. nadal nie ma żadnego zapisu do prod_orders.
    """
    with db.engine.connect() as polaczenie:
        return polaczenie.execute(
            text('SELECT bl_status_pending_id FROM prod_orders WHERE id = :id'),
            {'id': order_id}).scalar()


def wyslij_zamowienie(order):
    """
    Wysyła znaczniki jednego zamówienia. Zwraca liczbę zapytań. NIE commituje.

    WAŻNE (fix round 2, Important z re-review): między DWOMA wywołaniami HTTP do Base.
    (setOrderFields, setOrderStatus) nie wykonujemy ŻADNEGO zapisu do prod_orders.
    InnoDB blokuje wyłącznie KAŻDY wiersz PRZEJRZANY przez UPDATE, niezależnie od
    tego, czy WHERE finalnie dopasuje (`_wyczysc_metode`/`_wyczysc_status` i tak
    trafiają w ten wiersz przez `id` w WHERE) — gdyby taki UPDATE poszedł zaraz po
    setOrderFields, blokada trwałaby przez czas DRUGIEGO wywołania (realnie do ~105 s
    przy retry w `sync_service`). Każda transakcja webowa/tabletowa pisząca to samo
    zamówienie (`ustaw_sposob_dostawy`, `wydaj_klientowi`, `po_spakowaniu` przez
    `complete_task`) czekałaby wtedy do `innodb_lock_wait_timeout` (50 s) > timeout
    gunicorna (30 s) — WORKER TIMEOUT/502 i zgubiona zmiana użytkownika. Dlatego:
    NAJPIERW oba wywołania HTTP (wyniki tylko w pamięci Pythona — `metoda_wynik`/
    `status_wynik`, zero zapisu do bazy), i DOPIERO w `finally` — czyli też wtedy,
    gdy setOrderStatus rzuci `LimitBase`/`BladPolaczenia` — stosujemy oba warunkowe
    UPDATE-y na raz, tuż przed tym, jak wywołujący (`dopychaj`) zacommituje.

    Status do wysłania czytamy z bazy tuż przed setOrderStatus (`_swiezy_status`),
    nie z pamięci — mógł się zmienić w trakcie setOrderFields.

    `order._bl_niepowodzenie` (atrybut przejściowy — NIE kolumna, nic go nie persystuje)
    sygnalizuje dopychaczowi PRAWDZIWĄ porażkę wywołania Base. (dla `pominiete` — nie
    mielimy zamówienia w kółko). Odróżniamy ją od sytuacji, gdy zapytanie się udało, ale
    kod pominął czyszczenie znacznika, bo ktoś nadpisał decyzję w międzyczasie (F3) —
    to NIE jest porażka, zamówienie ma zostać wybrane ponownie w tym samym przebiegu.
    """
    order._bl_niepowodzenie = False
    if not order.baselinker_order_id:
        order.bl_delivery_method_pending = False
        order.bl_status_pending_id = None
        return 0
    zapytania = 0
    # Wyniki UDANYCH wywołań HTTP — same wartości w Pythonie, żadnego zapisu do bazy
    # dopóki oba wywołania (albo próba drugiego) się nie zakończą (patrz docstring wyżej).
    metoda_wynik = None  # (sposob_wyslany, tekst) gdy setOrderFields się udało, inaczej None
    status_wynik = None  # wyslany_status_id gdy setOrderStatus się udało, inaczej None
    try:
        if order.bl_delivery_method_pending:
            # sposob_wyslany ZAPAMIĘTUJEMY sprzed wywołania — to on (nie ewentualna nowsza
            # wartość) idzie do warunku czyszczącego znacznik po odpowiedzi Base.
            sposob_wyslany = sposoby.normalizuj(order.override_delivery_method)
            tekst = sposoby.TEKST_BASE.get(sposob_wyslany)
            if tekst is None or (order.delivery_method or '').strip() == tekst:
                order.bl_delivery_method_pending = False
            else:
                zapytania += 1
                if _wywolaj('setOrderFields', {'order_id': order.baselinker_order_id,
                                               'delivery_method': tekst}):
                    metoda_wynik = (sposob_wyslany, tekst)
                else:
                    order._bl_niepowodzenie = True
        if order.bl_status_pending_id:
            # Świeża wartość z bazy, nie z pamięci (patrz _swiezy_status). None = ktoś
            # w międzyczasie uznał status za załatwiony → nic nie wysyłamy.
            wyslany_status = _swiezy_status(order.id)
            if wyslany_status:
                zapytania += 1
                if _wywolaj('setOrderStatus', {'order_id': order.baselinker_order_id,
                                               'status_id': wyslany_status}):
                    # warunkowe czyszczenie porównuje z FAKTYCZNIE wysłaną wartością
                    status_wynik = wyslany_status
                else:
                    order._bl_niepowodzenie = True
        return zapytania
    finally:
        # Zapisy do bazy DOPIERO TERAZ — po obu wywołaniach HTTP (albo po wyjątku
        # z drugiego, patrz LimitBase/BladPolaczenia w setOrderStatus powyżej): udana
        # zmiana metody ma zostać zastosowana, zanim wywołujący zacommituje, zamiast
        # przepaść razem z wyjątkiem z drugiego zapytania.
        if metoda_wynik is not None:
            sposob_wyslany, tekst = metoda_wynik
            # tekst, który Base. FAKTYCZNIE dostało — zapisujemy zawsze, niezależnie
            # od tego, czy w międzyczasie ktoś zmienił decyzję logistyka
            order.delivery_method = tekst
            _wyczysc_metode(order, sposob_wyslany)
        if status_wynik is not None:
            _wyczysc_status(order, status_wynik)


# ── Dopychacz ─────────────────────────────────────────────────────────────

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
            except BladPolaczenia as e:
                # awaria sieci/konfiguracji — to NIE limit API (nie zapisujemy pauzy w
                # prod_config), ale próbowanie kolejnych zamówień w tym przebiegu i tak
                # by padło tym samym błędem, więc przerywamy cały przebieg od razu (F2b/c)
                db.session.commit()  # to, co przeszło przed błędem, zostaje
                logger.error("Blad polaczenia z Base. - przebieg dopychacza przerwany",
                            extra={'error': str(e), 'traceback': traceback.format_exc()})
                wynik['zapytania'] += 1
                break
            db.session.commit()
            wynik['zamowienia'] += 1
            wynik['zapytania'] += zapytania
            if getattr(order, '_bl_niepowodzenie', False):
                # PRAWDZIWA porażka Base. (nie nadpisana w międzyczasie decyzja, patrz
                # F3) — nie mielimy tego zamówienia w kółko w tym samym przebiegu
                pominiete.append(order.id)
            znacznik = dzierzawa.odnow(KLUCZ_DZIERZAWY, znacznik, CZAS_DZIERZAWY_S)
            if znacznik is None:
                break
            if zapytania:
                # odstęp PROPORCJONALNY do liczby zapytań w TYM zamówieniu — metoda i
                # status mogą iść jedno po drugim, więc dwa zapytania w jednym obiegu
                # pętli też muszą zmieścić się w limicie ≤ 40/min (F1)
                spij(ODSTEP_S * zapytania)
    finally:
        if znacznik:
            # sesja mogła trafić w stan błędu (nieobsłużony wyjątek nad tym try) —
            # bez rollbacku samo zwolnienie dzierżawy by się wywróciło (PendingRollback)
            # i przepadłaby na 300 s zamiast zostać zwolniona od razu (F2d)
            try:
                if not db.session.is_active:
                    db.session.rollback()
                dzierzawa.zwolnij(KLUCZ_DZIERZAWY, znacznik)
            except Exception as e:
                # nigdy nie maskujemy oryginalnego wyjątku (jeśli jakiś leci) — tylko log
                logger.error("Nie udalo sie zwolnic dzierzawy wysylki do Base.",
                            extra={'error': str(e), 'traceback': traceback.format_exc()})
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
                    # StructuredLogger.error ignoruje exc_info (patrz komentarz w _wywolaj)
                    # — traceback wprost w extra, zeby watek w tle zostawil slad. To
                    # jedyne miejsce, w ktorym ktokolwiek zobaczylby ten wyjatek (fix round 2, Minor)
                    logger.error("Dopychacz logistyki przerwany", extra={
                        'error': str(e), 'traceback': traceback.format_exc()})
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
