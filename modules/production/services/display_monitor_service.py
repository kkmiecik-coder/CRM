"""Aggregator for the production monitor display payload.

Returns a compact dict (JSON-serializable) describing current production
state across 7 stations x N configured species.

Shape is documented in docs/superpowers/plans/2026-06-08-production-monitor-display.md
under "JSON Format Specification".

ONE SQL query — groups by species, uses conditional SUM(CASE WHEN) for all
metrics. Earlier implementation issued ~90 sequential queries per call which
correlated with pymysql connection-pool corruption ("Packet sequence number
wrong") under Passenger's threaded workers, breaking unrelated endpoints.
"""
import json
import time
from datetime import datetime, date

from sqlalchemy import text

from extensions import db
from modules.production.models import ProductionConfig

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


def _build_aggregation_sql():
    """Build a single SELECT that returns one row per species bucket.

    Each row contains, for THAT species:
      - q_<code>, ip_<code>, d_<code> for every station (21 metrics)
      - overall_ip / overall_value_ip / overall_value_done_today / overall_overdue
        (each row's contribution; Python sums across rows)

    Column/value names are built from constants in STATION_CODES — no user input
    is interpolated. Status values are bound as parameters.
    """
    parts = ["SELECT COALESCE(pc.species, '__none__') AS species"]

    # queue per station: count of rows with matching waiting status
    for code, _, _ in STATION_CODES:
        parts.append(
            f", SUM(CASE WHEN pp.current_status = :status_{code} "
            f"THEN 1 ELSE 0 END) AS q_{code}"
        )

    # in-progress per station: started here but not complete, AND product is still active
    for code, suffix, _ in STATION_CODES:
        parts.append(
            f", SUM(CASE WHEN pp.quantity_done_{suffix} > 0 "
            f"AND pp.quantity_done_{suffix} < pp.quantity "
            f"AND pp.current_status NOT IN ('spakowane','anulowane','wstrzymane') "
            f"THEN 1 ELSE 0 END) AS ip_{code}"
        )

    # done-today per station: completed_at >= today_start
    for code, suffix, _ in STATION_CODES:
        parts.append(
            f", SUM(CASE WHEN pp.{suffix}_completed_at >= :today_start "
            f"THEN 1 ELSE 0 END) AS d_{code}"
        )

    # overall metrics (per-species contribution; Python sums)
    parts.append(
        ", SUM(CASE WHEN pp.current_status NOT IN ('spakowane','anulowane','wstrzymane') "
        "THEN 1 ELSE 0 END) AS overall_ip"
    )
    parts.append(
        ", COALESCE(SUM(CASE WHEN pp.current_status NOT IN ('spakowane','anulowane','wstrzymane') "
        "THEN COALESCE(pp.total_value_net, 0) ELSE 0 END), 0) AS overall_value_ip"
    )
    parts.append(
        ", COALESCE(SUM(CASE WHEN pp.packaging_completed_at >= :today_start "
        "THEN COALESCE(pp.total_value_net, 0) ELSE 0 END), 0) AS overall_value_done_today"
    )
    parts.append(
        ", SUM(CASE WHEN pp.deadline_date < :today "
        "AND pp.current_status NOT IN ('spakowane','anulowane') "
        "THEN 1 ELSE 0 END) AS overall_overdue"
    )

    parts.append(
        " FROM prod_products pp"
        " LEFT JOIN prod_configurations pc ON pp.configuration_id = pc.id"
        " GROUP BY COALESCE(pc.species, '__none__')"
    )
    return "".join(parts)


_AGGREGATION_SQL = _build_aggregation_sql()


def _get_species_list():
    row = ProductionConfig.query.filter_by(config_key='DISPLAY_MONITOR_SPECIES').first()
    if row and row.config_value:
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
    """Aggregate production data into the compact display payload.

    Single SQL round-trip. Returns N rows (one per species bucket including
    '__none__' for products without a configuration); Python folds them into
    the canonical payload shape.
    """
    species_list = _get_species_list()
    today_start = _today_start_local()
    today = date.today()

    params = {'today_start': today_start, 'today': today}
    for code, _, waiting_status in STATION_CODES:
        params[f'status_{code}'] = waiting_status

    result = db.session.execute(text(_AGGREGATION_SQL), params)
    rows = result.mappings().all()

    # Aggregators
    overall_ip = 0
    overall_value_ip = 0
    overall_value_done_today = 0
    overall_overdue = 0
    station_totals = {code: {'ip': 0, 'd': 0, 'q': 0} for code, _, _ in STATION_CODES}
    by_species = {}  # species -> {code: {'ip', 'd', 'q'}}

    for row in rows:
        sp = row['species']
        bucket = {}
        for code, _, _ in STATION_CODES:
            ip = int(row[f'ip_{code}'] or 0)
            d  = int(row[f'd_{code}'] or 0)
            q  = int(row[f'q_{code}'] or 0)
            station_totals[code]['ip'] += ip
            station_totals[code]['d']  += d
            station_totals[code]['q']  += q
            bucket[code] = {'ip': ip, 'd': d, 'q': q}
        by_species[sp] = bucket
        overall_ip               += int(row['overall_ip'] or 0)
        overall_value_ip         += int(row['overall_value_ip'] or 0)
        overall_value_done_today += int(row['overall_value_done_today'] or 0)
        overall_overdue          += int(row['overall_overdue'] or 0)

    # queued = waiting for first station (cutting)
    overall_queued = station_totals['cut']['q']
    # done_today = fully finished today = packaging_completed_at today
    overall_done_today = station_totals['pkg']['d']

    overall = [
        overall_ip,
        overall_queued,
        overall_done_today,
        overall_value_ip,
        overall_value_done_today,
        overall_overdue,
    ]

    stations = []
    for code, _, _ in STATION_CODES:
        bs = []
        for sp in species_list:
            cell = by_species.get(sp, {}).get(code, {'ip': 0, 'd': 0, 'q': 0})
            bs.append([cell['ip'], cell['d'], cell['q']])
        stations.append({
            'c': code,
            'ip': station_totals[code]['ip'],
            'd': station_totals[code]['d'],
            'q': station_totals[code]['q'],
            'bs': bs,
        })

    return {
        't': int(time.time()),
        'o': overall,
        'sp': species_list,
        'st': stations,
    }
