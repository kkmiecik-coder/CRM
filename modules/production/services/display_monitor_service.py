"""Aggregator for the production monitor display payload.

Returns a compact dict (JSON-serializable) describing current production
state across 7 stations x N configured species.

KONTRAKT CRM <-> FIRMWARE (kolejnosc kanoniczna ekranow):

    idx  kod   kolumny w prod_products                    status oczekiwania
    ---  ----  -----------------------------------------  ----------------------
     0   cut   quantity_done_cutting/cutting_completed_at      czeka_na_wyciecie
     1   asm   quantity_done_assembly/assembly_completed_at    czeka_na_skladanie
     2   glu   quantity_done_gluing/gluing_completed_at        czeka_na_sklejanie
     3   fmt   quantity_done_formatting/formatting_completed_at czeka_na_formatowanie
     4   edg   quantity_done_edges/edges_completed_at          czeka_na_krawedzie
     5   pnt   quantity_done_painting/painting_completed_at    czeka_na_lakiernie
     6   pkg   quantity_done_packaging/packaging_completed_at  czeka_na_pakowanie

Ta kolejnosc MUSI byc identyczna z enumem StationIdx w
tools/production-monitor/firmware/src/data_model.h oraz z lista strcmp()
w json_parser.cpp. Nieznany kod ekranu NIE zglasza bledu — parser robi
`continue`, a StationData jest zero-initowane, wiec rozjazd objawia sie
ZERAMI na wyswietlaczu, nie awaria. Zgodnosci pilnuje
tests/test_monitory_krawedzie.py::test_kontrakt_wyswietlacza_zyje_w_sledzonych_plikach.

Opis zyje TUTAJ, a nie w osobnym dokumencie planu: katalog planow jest
ignorowany przez git (repo jest publiczne), wiec na czystym klonie tamtego
pliku po prostu nie ma.

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
# Pozycja 4 to dawne 'fin' (Wykanczanie). Po podziale stanowiska kod ekranu
# brzmi 'edg' (Krawedzie); 'pnt' (Lakiernia) bylo tu od poczatku, wiec liczba
# ekranow nadal wynosi 7. Wyswietlacze TRZEBA przeflashowac: nieznany kod wpada
# w `if (idx < 0) continue` (json_parser.cpp:57), a StationData jest
# zero-initowane, wiec ekran pokaze ZERA zamiast zglosic blad.
# Drugi element krotki jest WKLEJANY DOSLOWNIE do surowego SQL (:59-63, :68-70)
# jako nazwa kolumny quantity_done_<suffix> / <suffix>_completed_at.
# (code, db_suffix, waiting_status)
STATION_CODES = [
    ('cut', 'cutting',    'czeka_na_wyciecie'),
    ('asm', 'assembly',   'czeka_na_skladanie'),
    ('glu', 'gluing',     'czeka_na_sklejanie'),
    ('fmt', 'formatting', 'czeka_na_formatowanie'),
    ('edg', 'edges',      'czeka_na_krawedzie'),
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


# Liczone RAZ, przy imporcie modulu — nazwy kolumn zamrazaja sie w tym stringu
# na cale zycie procesu gunicorna. deploy.sh migruje baze PRZED restartem
# (linia 50 vs 69), wiec miedzy migracja a restartem kazdy poll
# /api/display/monitor wali 500. Normalnie kilka sekund; jesli restart
# supervisora padnie (dzienny log jako root -> gunicorn bez prawa zapisu),
# stan 500 jest TRWALY. To ryzyko R6 specyfikacji.
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
