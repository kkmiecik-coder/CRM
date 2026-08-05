# -*- coding: utf-8 -*-
"""
Eksporty i agregaty trakowni.

W Zadaniu 10 tylko `sawmill_dashboard_stats` (kafelek dashboardu) — reszta
tego pliku (eksporty CSV/PDF, kontrakt API dla sesji Android) powstaje
w Zadaniu 13.
"""

from datetime import datetime, time
from decimal import Decimal

from sqlalchemy import func

from extensions import db
from modules.production.sawmill.models import (
    OPEN_STATUSES, STATUS_COMPLETED, SawmillLog, SawmillOrder,
)


def sawmill_dashboard_stats():
    """
    Cztery liczby na kafelek dashboardu plus postęp realizacji.

    „Dziś" liczone po measured_at, NIE po created_at — tablet potrafi rano
    wysłać pomiary z wczorajszego popołudnia (kolejka offline), a mają się
    policzyć do dnia, w którym faktycznie powstały, inaczej statystyka
    wydajności traka jest bezwartościowa.
    """
    dzis = datetime.combine(datetime.now().date(), time.min)
    jutro = datetime.combine(datetime.now().date(), time.max)

    open_orders = SawmillOrder.query.filter(
        SawmillOrder.status.in_(OPEN_STATUSES)).count()
    to_settle = SawmillOrder.query.filter(
        SawmillOrder.status == STATUS_COMPLETED).count()

    dzis_row = (
        db.session.query(func.count(SawmillLog.id),
                         func.coalesce(func.sum(SawmillLog.volume_m3), 0))
        .filter(SawmillLog.is_deleted.is_(False))
        .filter(SawmillLog.measured_at >= dzis)
        .filter(SawmillLog.measured_at <= jutro)
        .one()
    )

    # Postęp realizacji otwartych zleceń — to widok admina, więc deklaracja
    # może się tu pojawić bez ryzyka; na tablet i tak nie idzie.
    otwarte = SawmillOrder.query.filter(SawmillOrder.status.in_(OPEN_STATUSES)).all()
    zadeklarowano = sum((Decimal(str(o.declared_volume_m3)) for o in otwarte), Decimal(0))
    zmierzono = Decimal(0)
    for order in otwarte:
        suma = (db.session.query(func.coalesce(func.sum(SawmillLog.volume_m3), 0))
                .filter(SawmillLog.order_id == order.id)
                .filter(SawmillLog.is_deleted.is_(False)).scalar())
        zmierzono += Decimal(str(suma))

    progress = float(zmierzono / zadeklarowano * 100) if zadeklarowano > 0 else 0.0

    return {
        'open_orders': open_orders,
        'logs_today': int(dzis_row[0]),
        'volume_today_m3': float(dzis_row[1]),
        'to_settle': to_settle,
        'progress_pct': round(min(progress, 100.0), 1),
    }
