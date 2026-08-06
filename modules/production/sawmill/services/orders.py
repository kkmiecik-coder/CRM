# -*- coding: utf-8 -*-
"""
Logika zleceń trakowania: pomiary, przejścia statusów, audyt, różnice.

Żadna funkcja tutaj NIE commituje — transakcją steruje warstwa routera,
bo endpointy mobilne są owinięte dekoratorem idempotencji, który commituje
sam i wymaga, żeby handler tego nie robił.
"""

import json
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from extensions import db
from modules.production.sawmill.models import (
    OPEN_STATUSES, PANEL_WRITABLE_STATUSES, STATUS_COMPLETED, STATUS_IN_PROGRESS,
    STATUS_NEW, STATUS_SETTLED, SawmillAudit, SawmillLog, SawmillOrder,
)
from modules.production.sawmill.services.volume import compute_log_volume_m3

MEASUREMENT_FIELDS = ('mid_circumference_cm', 'length_cm')

_M3 = Decimal('0.001')
_PCT = Decimal('0.01')
_PLN = Decimal('0.01')


class SawmillStateError(Exception):
    """Operacja niedozwolona w bieżącym statusie — mapowana na HTTP 409."""

    def __init__(self, detail):
        super().__init__(detail)
        self.detail = detail


# ── Sumy ────────────────────────────────────────────────────────────────────

def order_totals(order_id):
    """Zwraca (liczba pomiarów, suma m3) z pominięciem soft-skasowanych."""
    row = (
        db.session.query(
            func.count(SawmillLog.id),
            func.coalesce(func.sum(SawmillLog.volume_m3), 0),
        )
        .filter(SawmillLog.order_id == order_id)
        .filter(SawmillLog.is_deleted.is_(False))
        .one()
    )
    return int(row[0]), Decimal(str(row[1]))


def compute_differences(order, measured_volume_m3, threshold_pct):
    """
    Różnica zawsze względem declared_volume_m3. Znak ujemny = zmierzono mniej.
    agreed_volume_m3 nie zastępuje deklaracji, jest trzecią liczbą obok niej.

    difference_pct liczy się z JUŻ ZAOKRĄGLONEJ difference_m3, nie z surowej
    różnicy — inaczej procent pokazywany w panelu mógłby nie odpowiadać
    różnicy m3 wyświetlanej tuż obok niego.

    Osłona na declared == 0: routery (order_update, delivery_create) od dawna
    odrzucają deklarację niedodatnią kodem 422, więc w normalnym obrocie zero
    tu nie dotrze — ale ta funkcja liczy się przy KAŻDYM odczycie listy
    zleceń (_panel_payload w orders_list), więc jeden wiersz zapisany kiedyś
    inną drogą (np. wprost w bazie) nie może wywrócić dzieleniem przez zero
    odczytu CAŁEJ listy. Przy declared == 0 różnica procentowa jest
    matematycznie nieokreślona (brak punktu odniesienia) — zostaje więc
    None (pusta komórka w UI), zamiast zmyślonej liczby. is_deviation
    ustawiamy mimo to na True, niezależnie od progu: sama obecność zerowej
    deklaracji to zawsze anomalia danych wymagająca uwagi biura, więc wiersz
    ma zostać widoczny również pod filtrem „tylko odchylenia", a nie zniknąć
    z niego tylko dlatego, że procent nie dał się policzyć.

    Zlecenie OTWARTE (new/in_progress) nie ma jeszcze żadnej różnicy — pomiar
    trwa. Liczenie jej wtedy dawało „-100%" i czerwoną flagę na każdym świeżo
    utworzonym zleceniu, czyli alarm w momencie, w którym z definicji nie ma
    o czym alarmować. Różnica pojawia się dopiero, gdy pracownik zamknie
    zlecenie na tablecie (`completed`) — to pierwszy moment, w którym system
    wie, że więcej kłód nie będzie. Do tego czasu wszystkie trzy wartości są
    None, a `differences_pending` mówi interfejsowi, że pusto jest CELOWO,
    nie z powodu braku danych.
    """
    if order.status in OPEN_STATUSES:
        return {
            'difference_m3': None,
            'difference_pct': None,
            'difference_value': None,
            'is_deviation': False,
            'differences_pending': True,
        }

    declared = Decimal(str(order.declared_volume_m3))
    measured = Decimal(str(measured_volume_m3))

    difference_m3 = (measured - declared).quantize(_M3, rounding=ROUND_HALF_UP)

    if declared == 0:
        difference_pct = None
        is_deviation = True
    else:
        difference_pct = (difference_m3 / declared * 100).quantize(_PCT, rounding=ROUND_HALF_UP)
        is_deviation = abs(difference_pct) > Decimal(str(threshold_pct))

    difference_value = None
    if order.price_per_m3 is not None:
        difference_value = (difference_m3 * Decimal(str(order.price_per_m3))
                            ).quantize(_PLN, rounding=ROUND_HALF_UP)

    return {
        'difference_m3': difference_m3,
        'difference_pct': difference_pct,
        'difference_value': difference_value,
        'is_deviation': is_deviation,
        'differences_pending': False,
    }


# ── Audyt ───────────────────────────────────────────────────────────────────

def _log_snapshot(log):
    return {
        'sequence_no': log.sequence_no,
        'mid_circumference_cm': str(log.mid_circumference_cm),
        'length_cm': str(log.length_cm),
        'volume_m3': str(log.volume_m3),
    }


def write_audit(order_id, action, log_id=None, before=None, after=None,
                device_id=None, user_id=None):
    """Dopisuje wpis audytowy. Nie commituje."""
    entry = SawmillAudit(
        order_id=order_id,
        log_id=log_id,
        action=action,
        # `is not None`, nie samo `if before` — pusty słownik {} bywałby
        # poprawną wartością audytową i nie powinien po cichu zamienić się
        # w NULL tylko dlatego, że jest "falszywy" w sensie Pythona.
        before_json=json.dumps(before, ensure_ascii=False) if before is not None else None,
        after_json=json.dumps(after, ensure_ascii=False) if after is not None else None,
        device_id=device_id,
        user_id=user_id,
        created_at=datetime.now(),
    )
    db.session.add(entry)
    return entry


# ── Pomiary ─────────────────────────────────────────────────────────────────

def next_sequence_no(order_id):
    """
    Kolejny numer kłody. Maksimum liczone po WSZYSTKICH wierszach, także
    soft-skasowanych — numer usuniętej kłody nie jest reużywany.
    """
    highest = (
        db.session.query(func.max(SawmillLog.sequence_no))
        .filter(SawmillLog.order_id == order_id)
        .scalar()
    )
    return (highest or 0) + 1


def _apply_measurements(log, measurements):
    for field in MEASUREMENT_FIELDS:
        setattr(log, field, measurements[field])
    log.volume_m3 = compute_log_volume_m3(
        measurements['mid_circumference_cm'],
        measurements['length_cm'],
    )


def add_log(order, measurements, measured_at, device_id=None, user_id=None, manual=False):
    """
    Dodaje pomiar. Insert idzie w SAVEPOINT — po IntegrityError na kolizji
    sequence_no sesja jest nieużywalna, a zwykły rollback skasowałby też wpis
    audytowy i zwolnił blokadę, po czym dekorator i tak zrobiłby commit
    odpowiedzi 201, za którą nic nie stoi.
    """
    _guard_writable(order, panel=manual)

    log = SawmillLog(
        order_id=order.id,
        sequence_no=next_sequence_no(order.id),
        device_id=device_id,
        measured_at=measured_at,
        created_at=datetime.now(),
    )
    _apply_measurements(log, measurements)

    try:
        with db.session.begin_nested():
            db.session.add(log)
            db.session.flush()
    except IntegrityError:
        # Kolizja numeru — NIE ma tu żadnej blokady FOR UPDATE na wierszu
        # zlecenia (i nigdy nie było). Ten blok łapie PIERWSZĄ kolizję i
        # ponawia insert raz, z odświeżonym next_sequence_no() — to zwykle
        # wystarcza. Gdyby kolizja trafiła się też przy TYM ponowieniu
        # (dwa niemal jednoczesne zapisy trafiające w ten sam numer drugi
        # raz z rzędu), wyjątek już nie jest tu łapany i leci dalej jako 500.
        # Ratuje wtedy dekorator idempotencji: nie zapisuje odpowiedzi 5xx
        # jako obsłużonej, więc tablet ponawia żądanie z tym samym
        # X-Operation-Id i trafia w świeżą transakcję z nowym
        # next_sequence_no(). Unikat (order_id, sequence_no) gwarantuje przy
        # tym, że duplikat nigdy się nie zapisze — w najgorszym razie klient
        # płaci jeden dodatkowy round-trip, nie utratę pomiaru. Łapiemy
        # WYŁĄCZNIE IntegrityError — szerszy `except Exception` połknąłby
        # też inne błędy zapisu (zerwane połączenie, błąd sterownika) i
        # błędnie zinterpretował je jako kolizję numeru, ukrywając prawdziwą
        # przyczynę awarii pod fałszywym ponowieniem.
        log.sequence_no = next_sequence_no(order.id)
        with db.session.begin_nested():
            db.session.add(log)
            db.session.flush()

    if order.status == STATUS_NEW:
        order.status = STATUS_IN_PROGRESS
        order.started_at = measured_at

    write_audit(order.id, 'log_create_manual' if manual else 'log_create',
                log_id=log.id, after=_log_snapshot(log),
                device_id=device_id, user_id=user_id)
    return log


def update_log(log, measurements, device_id=None, user_id=None):
    # Rozstrzygnięcie panel/tablet po tym, który argument jest różny od None:
    # w całym zaprojektowanym systemie tablet przekazuje WYŁĄCZNIE device_id
    # (z g.device.device_id, po require_device_token), a panel WYŁĄCZNIE
    # user_id (z current_user, zawsze zalogowanego dzięki
    # require_module_access) — nigdy oba naraz, nigdy żadne. Kontrakt funkcji
    # jest zamrożony (kolejne zadania na nim polegają), więc nie da się tego
    # rozstrzygnąć jawnym parametrem tak jak w add_log(..., manual=...).
    # panel=True pozwala pisać także w statusie completed, tablet już nie.
    _guard_writable(_order_of(log), panel=user_id is not None)
    before = _log_snapshot(log)
    _apply_measurements(log, measurements)
    db.session.flush()
    write_audit(log.order_id, 'log_update', log_id=log.id,
                before=before, after=_log_snapshot(log),
                device_id=device_id, user_id=user_id)
    return log


def delete_log(log, device_id=None, user_id=None):
    _guard_writable(_order_of(log), panel=user_id is not None)
    before = _log_snapshot(log)
    log.is_deleted = True
    log.deleted_at = datetime.now()
    db.session.flush()
    write_audit(log.order_id, 'log_delete', log_id=log.id, before=before,
                device_id=device_id, user_id=user_id)


def _order_of(log):
    return db.session.query(SawmillOrder).get(log.order_id)


def _guard_writable(order, panel=False):
    """
    Tablet pisze tylko w statusach otwartych, panel także w completed.

    Porównanie idzie przez PANEL_WRITABLE_STATUSES/OPEN_STATUSES z models.py
    (jedno źródło prawdy dla obu warstw — routerów i tego serwisu), nie przez
    wyliczanie `order.status == STATUS_SETTLED` na sztywno.
    """
    allowed = PANEL_WRITABLE_STATUSES if panel else OPEN_STATUSES
    if order.status not in allowed:
        detail = (u'zlecenie rozliczone — wymagane cofnięcie rozliczenia' if panel
                  else u'zlecenie nie jest otwarte')
        raise SawmillStateError(detail)


# ── Przejścia statusów ──────────────────────────────────────────────────────

def complete_order(order, device_id):
    if order.status not in OPEN_STATUSES:
        raise SawmillStateError(u'zlecenie nie jest otwarte')
    count, _ = order_totals(order.id)
    if count == 0:
        raise SawmillStateError(u'nie można zakończyć zlecenia bez pomiarów')

    order.status = STATUS_COMPLETED
    order.completed_at = datetime.now()
    order.completed_by_device = device_id
    write_audit(order.id, 'order_complete', device_id=device_id)


def reopen_order(order, user_id):
    if order.status != STATUS_COMPLETED:
        raise SawmillStateError(u'cofnąć można tylko zlecenie zakończone')
    order.status = STATUS_IN_PROGRESS
    order.completed_at = None
    order.completed_by_device = None
    write_audit(order.id, 'order_reopen', user_id=user_id)


def settle_order(order, agreed_volume_m3, notes, user_id):
    if order.status != STATUS_COMPLETED:
        raise SawmillStateError(u'rozliczyć można tylko zlecenie zakończone')
    if agreed_volume_m3 is None:
        raise SawmillStateError(u'uzgodniona objętość jest wymagana')

    order.agreed_volume_m3 = Decimal(str(agreed_volume_m3))
    order.settlement_notes = notes
    order.status = STATUS_SETTLED
    order.settled_at = datetime.now()
    order.settled_by_user_id = user_id
    write_audit(order.id, 'order_settle', user_id=user_id,
                after={'agreed_volume_m3': str(order.agreed_volume_m3)})


def unsettle_order(order, user_id):
    """
    Wraca do completed, nie do in_progress — cofamy decyzję biura, nie
    otwieramy stanowiska. agreed_volume_m3 i notatka ZOSTAJĄ, bo admin
    zwykle koryguje szczegół, a nie zaczyna od zera.
    """
    if order.status != STATUS_SETTLED:
        raise SawmillStateError(u'zlecenie nie jest rozliczone')
    order.status = STATUS_COMPLETED
    order.settled_at = None
    order.settled_by_user_id = None
    write_audit(order.id, 'order_unsettle', user_id=user_id)
