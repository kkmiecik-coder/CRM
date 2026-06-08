"""Aggregator for the production monitor display payload.

Returns a compact dict (JSON-serializable) describing current production
state across 7 stations x N configured species.

Shape is documented in docs/superpowers/plans/2026-06-08-production-monitor-display.md
under "JSON Format Specification".
"""
import json
import time
from datetime import datetime, date

from sqlalchemy import func, and_

from extensions import db
from modules.production.models import (
    ProductionProduct, ProductionConfiguration, ProductionConfig,
)

# Canonical order - MUST match firmware's screen order.
# (code, db_suffix, waiting_status)
STATION_CODES = [
    ('cut', 'cutting',    'czeka_na_wyciecie'),
    ('asm', 'assembly',   'czeka_na_skladanie'),
    ('glu', 'gluing',     'czeka_na_sklejanie'),
    ('fmt', 'formatting', 'czeka_na_formatowanie'),
    ('fin', 'finishing',  'czeka_na_wykanczanie'),
    ('pnt', 'painting',   'czeka_na_lakiernie'),
    ('pkg', 'packaging',  'czeka_na_pakowanie'),
]

_TERMINAL_STATUSES = ('spakowane', 'anulowane', 'wstrzymane')
_DONE_STATUSES = ('spakowane', 'anulowane')


def _get_species_list():
    row = ProductionConfig.query.filter_by(config_key='DISPLAY_MONITOR_SPECIES').first()
    if row and row.config_value:
        # Prefer the model's parsed_value when config_type='json' is set;
        # fall back to raw json.loads for resilience.
        try:
            value = row.parsed_value if hasattr(row, 'parsed_value') else None
            if isinstance(value, list):
                return [str(s) for s in value]
            v = json.loads(row.config_value)
            if isinstance(v, list):
                return [str(s) for s in v]
        except (ValueError, TypeError):
            pass
    return ['dąb', 'jesion', 'buk']


def _today_start_local():
    """Local midnight as a naive datetime, matching how completed_at is stored."""
    return datetime.combine(date.today(), datetime.min.time())


def get_display_monitor_payload():
    """Aggregate production data into the compact display payload."""
    species_list = _get_species_list()
    today_start = _today_start_local()
    today = date.today()

    # --- Overall stats -------------------------------------------------------
    in_progress = db.session.query(func.count(ProductionProduct.id)).filter(
        ~ProductionProduct.current_status.in_(_TERMINAL_STATUSES)
    ).scalar() or 0

    queued = db.session.query(func.count(ProductionProduct.id)).filter(
        ProductionProduct.current_status == 'czeka_na_wyciecie'
    ).scalar() or 0

    done_today = db.session.query(func.count(ProductionProduct.id)).filter(
        ProductionProduct.packaging_completed_at >= today_start
    ).scalar() or 0

    value_ip = db.session.query(func.coalesce(func.sum(ProductionProduct.total_value_net), 0)).filter(
        ~ProductionProduct.current_status.in_(_TERMINAL_STATUSES)
    ).scalar() or 0

    value_done_today = db.session.query(func.coalesce(func.sum(ProductionProduct.total_value_net), 0)).filter(
        ProductionProduct.packaging_completed_at >= today_start
    ).scalar() or 0

    overdue = db.session.query(func.count(ProductionProduct.id)).filter(
        and_(
            ProductionProduct.deadline_date < today,
            ~ProductionProduct.current_status.in_(_DONE_STATUSES),
        )
    ).scalar() or 0

    overall = [
        int(in_progress),
        int(queued),
        int(done_today),
        int(value_ip),
        int(value_done_today),
        int(overdue),
    ]

    # --- Stations ------------------------------------------------------------
    stations = []
    for code, suffix, waiting_status in STATION_CODES:
        qty_done_col = getattr(ProductionProduct, f'quantity_done_{suffix}')
        completed_at_col = getattr(ProductionProduct, f'{suffix}_completed_at')

        # in_progress at this station: started but not yet complete here, AND not terminal
        ip = db.session.query(func.count(ProductionProduct.id)).filter(
            and_(
                qty_done_col > 0,
                qty_done_col < ProductionProduct.quantity,
                ~ProductionProduct.current_status.in_(_TERMINAL_STATUSES),
            )
        ).scalar() or 0

        d = db.session.query(func.count(ProductionProduct.id)).filter(
            completed_at_col >= today_start
        ).scalar() or 0

        q = db.session.query(func.count(ProductionProduct.id)).filter(
            ProductionProduct.current_status == waiting_status
        ).scalar() or 0

        # by-species breakdown
        bs = []
        for sp in species_list:
            sp_ip = db.session.query(func.count(ProductionProduct.id)).join(
                ProductionConfiguration,
                ProductionProduct.configuration_id == ProductionConfiguration.id,
            ).filter(
                and_(
                    ProductionConfiguration.species == sp,
                    qty_done_col > 0,
                    qty_done_col < ProductionProduct.quantity,
                    ~ProductionProduct.current_status.in_(_TERMINAL_STATUSES),
                )
            ).scalar() or 0

            sp_d = db.session.query(func.count(ProductionProduct.id)).join(
                ProductionConfiguration,
                ProductionProduct.configuration_id == ProductionConfiguration.id,
            ).filter(
                and_(
                    ProductionConfiguration.species == sp,
                    completed_at_col >= today_start,
                )
            ).scalar() or 0

            sp_q = db.session.query(func.count(ProductionProduct.id)).join(
                ProductionConfiguration,
                ProductionProduct.configuration_id == ProductionConfiguration.id,
            ).filter(
                and_(
                    ProductionConfiguration.species == sp,
                    ProductionProduct.current_status == waiting_status,
                )
            ).scalar() or 0

            bs.append([int(sp_ip), int(sp_d), int(sp_q)])

        stations.append({
            'c': code,
            'ip': int(ip),
            'd': int(d),
            'q': int(q),
            'bs': bs,
        })

    return {
        't': int(time.time()),
        'o': overall,
        'sp': species_list,
        'st': stations,
    }
