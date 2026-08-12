"""
Agregacje pracy stanowiskowej z prod_station_events.

Źródło prawdy dla metryk "ile faktycznie zrobiono" w okresie czasu.
W odróżnieniu od ProductionItem.<station>_completed_at (które ustawia się
dopiero gdy WSZYSTKIE sztuki pozycji są wykonane), eventy logują każdy
ruch quantity_done_<station> (zarówno + jak i -), więc:

- partial work (np. 30/100 sztuk wykonane danego dnia) jest widoczny
- cofnięcia są odejmowane (SUM(delta) daje netto)
- sumowanie m³ wynika z faktycznie wykonanych sztuk × volume_m3 jednostki

Strefa czasowa: prod_station_events.created_at zapisywany przez
get_local_now() (czas lokalny PL) — ten sam, którego używają write paths
i pozostałe metryki dashboardu. Filtry datowe operują na naive datetime
w strefie Warszawy.
"""

from datetime import date, datetime

from sqlalchemy import func, distinct

from extensions import db
from ..models import ProductionItem, ProductionOrder, ProductionStationEvent

# Eventy, których NIKT fizycznie nie wykonał: complete_task() generuje je dla
# stanowisk pomijanych — produkt nieprzycinany na wymiar przeskakuje
# formatowanie i wykańczanie, surowy bez obróbki krawędzi przeskakuje
# wykańczanie. Do 2026-08 wchodziły do wszystkich metryk przerobu, więc
# formatowanie i wykańczanie miały w raportach sztuki, których nie tknął żaden
# człowiek. Filtr jest wspólny z worker_stats_service — trzy widgety na jednym
# ekranie muszą mieć JEDNĄ definicję słowa "zrobione".
ZRODLA_AUTOMATU = ('auto_skip', 'system')


def _na_date(wartosc):
    """
    func.date() oddaje obiekt `date` w MySQL, a TEKST w SQLite. Bez normalizacji
    get_station_work_per_day() łamie własny kontrakt („Returns: dict[date]")
    na jednym z dwóch silników, a konsument sięgający po `slownik[jakas_data]`
    dostaje pustkę zamiast liczby — cicho, bo .get() ma wartość domyślną.
    """
    if wartosc is None:
        return None
    if isinstance(wartosc, datetime):
        return wartosc.date()
    if isinstance(wartosc, date):
        return wartosc
    return datetime.strptime(str(wartosc)[:10], '%Y-%m-%d').date()


def get_station_work_in_range(station_code, range_start, range_end):
    """
    Faktyczna praca na stanowisku w przedziale czasu (range_start <= t < range_end).

    Liczone z prod_station_events:
      - pieces_done = SUM(delta)              # netto sztuk (uwzględnia cofnięcia)
      - m3_done     = SUM(volume_m3 * delta)  # netto m³
      - items_count = COUNT(DISTINCT item_id) gdzie SUM(delta) > 0
      - orders_count = COUNT(DISTINCT baselinker_order_id) gdzie SUM(delta) > 0

    Args:
        station_code: kod stanowiska ('cutting', 'assembly', 'gluing',
                      'formatting', 'finishing', 'packaging')
        range_start, range_end: naive datetime (czas lokalny)

    Returns:
        dict: {pieces_done, m3_done, items_count, orders_count}
    """
    totals = db.session.query(
        func.coalesce(func.sum(ProductionStationEvent.delta), 0).label('pieces'),
        func.coalesce(
            func.sum(ProductionItem.volume_m3 * ProductionStationEvent.delta), 0
        ).label('m3'),
    ).join(
        ProductionItem, ProductionItem.id == ProductionStationEvent.production_item_id
    ).filter(
        ProductionStationEvent.station_code == station_code,
        ProductionStationEvent.created_at >= range_start,
        ProductionStationEvent.created_at < range_end,
        ~ProductionStationEvent.source.in_(ZRODLA_AUTOMATU),
    ).one()

    # items_count i orders_count — tylko pozycje z dodatnim netto
    items_subq = db.session.query(
        ProductionStationEvent.production_item_id.label('item_id'),
        func.sum(ProductionStationEvent.delta).label('net_delta'),
    ).filter(
        ProductionStationEvent.station_code == station_code,
        ProductionStationEvent.created_at >= range_start,
        ProductionStationEvent.created_at < range_end,
        ~ProductionStationEvent.source.in_(ZRODLA_AUTOMATU),
    ).group_by(ProductionStationEvent.production_item_id).subquery()

    counts = db.session.query(
        func.count(distinct(items_subq.c.item_id)).label('items'),
        func.count(distinct(ProductionOrder.baselinker_order_id)).label('orders'),
    ).join(
        ProductionItem, ProductionItem.id == items_subq.c.item_id
    ).join(
        ProductionOrder, ProductionItem.order_id == ProductionOrder.id
    ).filter(items_subq.c.net_delta > 0).one()

    return {
        'pieces_done': int(totals.pieces or 0),
        'm3_done': float(totals.m3 or 0),
        'items_count': int(counts.items or 0),
        'orders_count': int(counts.orders or 0),
    }


def get_station_work_per_day(station_code, start_date, end_date):
    """
    Praca dzienna na stanowisku (do wykresów wieloresnych).

    Args:
        station_code: kod stanowiska
        start_date, end_date: date (włącznie)

    Returns:
        dict[date] = {pieces, m3, value_net}
    """
    rows = db.session.query(
        func.date(ProductionStationEvent.created_at).label('day'),
        func.coalesce(func.sum(ProductionStationEvent.delta), 0).label('pieces'),
        func.coalesce(
            func.sum(ProductionItem.volume_m3 * ProductionStationEvent.delta), 0
        ).label('m3'),
        func.coalesce(
            func.sum(
                ProductionItem.total_value_net * ProductionStationEvent.delta
                / ProductionItem.quantity
            ), 0
        ).label('value_net'),
    ).join(
        ProductionItem, ProductionItem.id == ProductionStationEvent.production_item_id
    ).filter(
        ProductionStationEvent.station_code == station_code,
        func.date(ProductionStationEvent.created_at) >= start_date,
        func.date(ProductionStationEvent.created_at) <= end_date,
        ~ProductionStationEvent.source.in_(ZRODLA_AUTOMATU),
    ).group_by(
        func.date(ProductionStationEvent.created_at)
    ).all()

    return {
        _na_date(row.day): {
            'pieces': int(row.pieces or 0),
            'm3': float(row.m3 or 0),
            'value_net': float(row.value_net or 0),
        }
        for row in rows
    }
