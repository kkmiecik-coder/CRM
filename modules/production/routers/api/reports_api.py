# modules/production/routers/api/reports_api.py
"""
Reports tab content endpoints.
Extracted from api_routers.py.
"""

from datetime import datetime, date, timedelta
from flask import request, jsonify, render_template
from flask_login import login_required, current_user
from extensions import db
from sqlalchemy import func

from . import api_bp, logger, ProductionItem, ProductionSyncLog, get_local_now

VALID_STATIONS = {
    'cutting', 'assembly', 'completion', 'gluing', 'formatting',
    'finishing', 'painting', 'packaging'
}

STATION_LABELS = {
    'cutting': 'Wycinanie',
    'assembly': 'Składanie',
    'completion': 'Kompletacja',
    'gluing': 'Sklejanie',
    'formatting': 'Formatowanie',
    'finishing': 'Wykańczanie',
    'painting': 'Lakiernia',
    'packaging': 'Pakowanie',
}


@api_bp.route('/reports/station-output')
@login_required
def reports_station_output():
    """
    GET /production/api/reports/station-output?station=<code>&date=YYYY-MM-DD

    Zwraca pozycje produkcyjne, na których stanowisko <station> wykonało
    jakąkolwiek operację (delta != 0) w ciągu wybranego dnia.

    Dla każdej pozycji:
    - quantity_done_eod: stan quantity_done_<station> na koniec tego dnia
      (z ostatniego eventu w tym dniu) — to jest "ile zostało wykonane"
    - day_delta_sum: netto ruch w ciągu dnia (suma delta) — np. +5,-1,+2 = +6
    - quantity: total szt. pozycji
    - volume_per_unit, volume_done_eod (m³)
    - meta: short_product_id, original_product_name, baselinker_order_id, status, gatunek/grubość

    Sortowanie: po ostatnim evencie w dniu (najnowsze najpierw).
    """
    from ...models import ProductionStationEvent
    from sqlalchemy import and_

    station = request.args.get('station', '').strip().lower()
    date_str = request.args.get('date', '').strip()

    if station not in VALID_STATIONS:
        return jsonify({
            'success': False,
            'error': f'Nieprawidłowe stanowisko. Dozwolone: {sorted(VALID_STATIONS)}'
        }), 400

    try:
        target_date = datetime.strptime(date_str, '%Y-%m-%d').date() if date_str else date.today()
    except ValueError:
        return jsonify({
            'success': False,
            'error': 'Nieprawidłowy format daty (oczekiwane YYYY-MM-DD)'
        }), 400

    day_start = datetime.combine(target_date, datetime.min.time())
    day_end = datetime.combine(target_date, datetime.max.time())

    try:
        # Per-item agregacja eventów z wybranego dnia
        # day_delta_sum = SUM(delta), last_event_at = MAX(created_at)
        agg = db.session.query(
            ProductionStationEvent.production_item_id.label('item_id'),
            func.sum(ProductionStationEvent.delta).label('day_delta_sum'),
            func.max(ProductionStationEvent.created_at).label('last_event_at'),
            func.count(ProductionStationEvent.id).label('event_count'),
        ).filter(
            ProductionStationEvent.station_code == station,
            ProductionStationEvent.created_at >= day_start,
            ProductionStationEvent.created_at <= day_end,
        ).group_by(ProductionStationEvent.production_item_id).subquery()

        # Pobierz quantity_done_after z ostatniego eventu w dniu (per item).
        # Trick: order by created_at desc, group_by item_id z LIMIT — w MySQL
        # nie działa wprost; używamy correlated subquery przez JOIN po (item, last_event_at).
        last_event = db.session.query(
            ProductionStationEvent.production_item_id.label('item_id'),
            ProductionStationEvent.created_at.label('last_event_at'),
            ProductionStationEvent.quantity_done_after.label('quantity_done_eod'),
        ).filter(
            ProductionStationEvent.station_code == station,
            ProductionStationEvent.created_at >= day_start,
            ProductionStationEvent.created_at <= day_end,
        ).subquery()

        rows = db.session.query(
            ProductionItem,
            agg.c.day_delta_sum,
            agg.c.last_event_at,
            agg.c.event_count,
            last_event.c.quantity_done_eod,
        ).join(
            agg, ProductionItem.id == agg.c.item_id
        ).join(
            last_event,
            and_(
                last_event.c.item_id == agg.c.item_id,
                last_event.c.last_event_at == agg.c.last_event_at,
            )
        ).order_by(agg.c.last_event_at.desc()).all()

        items_payload = []
        sum_qty_done_eod = 0
        sum_volume_done_eod = 0.0
        sum_day_delta = 0

        # Dedup po item_id (w razie remisu created_at na ostatnim evencie
        # join produkcyjnie wybierze pierwszy zwrot — agregat i tak ten sam)
        seen_ids = set()
        for item, day_delta_sum, last_event_at, event_count, qty_done_eod in rows:
            if item.id in seen_ids:
                continue
            seen_ids.add(item.id)

            qty_done_eod = int(qty_done_eod or 0)
            day_delta_sum = int(day_delta_sum or 0)
            volume_per_unit = float(item.volume_m3 or 0)
            volume_done_eod = volume_per_unit * qty_done_eod

            sum_qty_done_eod += qty_done_eod
            sum_volume_done_eod += volume_done_eod
            sum_day_delta += day_delta_sum

            items_payload.append({
                'item_id': item.id,
                'short_product_id': item.short_product_id,
                'product_name': item.original_product_name,
                'baselinker_order_id': item.baselinker_order_id,
                'internal_order_number': item.internal_order_number,
                'current_status': item.current_status,
                'quantity': item.quantity,
                'quantity_done_eod': qty_done_eod,
                'day_delta_sum': day_delta_sum,
                'event_count': int(event_count or 0),
                'volume_per_unit_m3': round(volume_per_unit, 4),
                'volume_done_eod_m3': round(volume_done_eod, 4),
                'wood_species': item.parsed_wood_species,
                'thickness_cm': float(item.parsed_thickness_cm) if item.parsed_thickness_cm else None,
                'last_event_at': last_event_at.isoformat() if last_event_at else None,
            })

        # Timeline 48 bucketów po 30 minut (00:00, 00:30, ..., 23:30)
        # bucket_idx = floor((HOUR*60 + MINUTE) / 30) ∈ [0, 47]
        # Net delta per bucket (cofnięcia mogą dać wartość ujemną).
        bucket_idx_expr = func.floor(
            (func.hour(ProductionStationEvent.created_at) * 60
             + func.minute(ProductionStationEvent.created_at)) / 30
        ).label('bucket_idx')

        timeline_rows = db.session.query(
            bucket_idx_expr,
            func.sum(ProductionStationEvent.delta).label('pieces_sum'),
            func.sum(
                ProductionStationEvent.delta * ProductionItem.volume_m3
            ).label('m3_sum'),
        ).join(
            ProductionItem,
            ProductionItem.id == ProductionStationEvent.production_item_id
        ).filter(
            ProductionStationEvent.station_code == station,
            ProductionStationEvent.created_at >= day_start,
            ProductionStationEvent.created_at <= day_end,
        ).group_by(bucket_idx_expr).all()

        pieces_buckets = [0] * 48
        m3_buckets = [0.0] * 48
        for bucket_idx, pieces_sum, m3_sum in timeline_rows:
            idx = int(bucket_idx) if bucket_idx is not None else None
            if idx is None or idx < 0 or idx > 47:
                continue
            pieces_buckets[idx] = int(pieces_sum or 0)
            m3_buckets[idx] = round(float(m3_sum or 0.0), 4)

        bucket_labels = [
            f"{i // 2:02d}:{'30' if i % 2 else '00'}"
            for i in range(48)
        ]

        return jsonify({
            'success': True,
            'station': station,
            'station_label': STATION_LABELS.get(station, station),
            'date': target_date.isoformat(),
            'items': items_payload,
            'summary': {
                'items_count': len(items_payload),
                'total_quantity_done_eod': sum_qty_done_eod,
                'total_day_delta': sum_day_delta,
                'total_volume_done_eod_m3': round(sum_volume_done_eod, 4),
            },
            'timeline': {
                'buckets': bucket_labels,
                'pieces': pieces_buckets,
                'volume_m3': m3_buckets,
            },
        })

    except Exception as e:
        logger.error("Błąd /reports/station-output", extra={
            'user_id': current_user.id,
            'station': station,
            'date': date_str,
            'error': str(e),
        })
        return jsonify({'success': False, 'error': str(e)}), 500


@api_bp.route('/reports-tab-content')
@login_required
def reports_tab_content():
    """
    AJAX endpoint dla zawartości taba Raporty - POPRAWIONY
    """
    try:
        logger.info("AJAX: Ładowanie zawartości reports-tab", extra={
            'user_id': current_user.id,
            'user_role': getattr(current_user, 'role', 'unknown')
        })
        
        from ...models import ProductionItem, ProductionSyncLog
        
        # Przygotuj dane dla raportów
        today = date.today()
        week_ago = today - timedelta(days=7)
        month_ago = today - timedelta(days=30)
        
        # Raporty wydajności
        daily_stats = []
        for i in range(7):
            day = today - timedelta(days=i)
            day_start = datetime.combine(day, datetime.min.time())
            day_end = datetime.combine(day, datetime.max.time())
            
            completed = ProductionItem.query.filter(
                ProductionItem.current_status == 'spakowane',
                ProductionItem.packaging_completed_at >= day_start,
                ProductionItem.packaging_completed_at <= day_end
            ).count()
            
            volume = db.session.query(db.func.sum(ProductionItem.volume_m3 * ProductionItem.quantity))\
                              .filter(
                                  ProductionItem.current_status == 'spakowane',
                                  ProductionItem.packaging_completed_at >= day_start,
                                  ProductionItem.packaging_completed_at <= day_end
                              ).scalar() or 0.0
            
            daily_stats.append({
                'date': day.isoformat(),
                'completed_orders': completed,
                'total_volume': float(volume)
            })
        
        # Raport statusów - dynamicznie ze wszystkich istniejących w bazie
        status_stats = db.session.query(
            ProductionItem.current_status,
            func.count(ProductionItem.id).label('count'),
            func.sum(ProductionItem.volume_m3 * ProductionItem.quantity).label('volume')
        ).filter(
            ProductionItem.current_status.isnot(None)
        ).group_by(ProductionItem.current_status).all()

        status_report = [
            {
                'status': row[0],
                'count': row[1],
                'volume': float(row[2] or 0)
            }
            for row in status_stats
        ]

        # Species+technology breakdown per status
        species_by_status_raw = db.session.query(
            ProductionItem.current_status,
            ProductionItem.parsed_wood_species,
            ProductionItem.parsed_technology,
            func.sum(ProductionItem.volume_m3 * ProductionItem.quantity).label('volume')
        ).filter(
            ProductionItem.current_status.isnot(None),
            ProductionItem.parsed_wood_species.isnot(None)
        ).group_by(
            ProductionItem.current_status,
            ProductionItem.parsed_wood_species,
            ProductionItem.parsed_technology
        ).all()

        species_by_status = {}
        for row in species_by_status_raw:
            status = row[0]
            species = row[1] or '—'
            tech = row[2] or ''
            label = f"{species} {tech}".strip()
            vol = float(row[3] or 0)
            if status not in species_by_status:
                species_by_status[status] = []
            species_by_status[status].append({'label': label, 'volume': round(vol, 3)})

        # Sort each status's species list by volume desc
        for status in species_by_status:
            species_by_status[status].sort(key=lambda x: -x['volume'])

        # Attach to status_report
        for item in status_report:
            item['species_breakdown'] = species_by_status.get(item['status'], [])

        # Historia synchronizacji (ostatnie 10)
        sync_history = ProductionSyncLog.query\
                                       .order_by(ProductionSyncLog.sync_started_at.desc())\
                                       .limit(10).all()

        # Rozkład według gatunków drewna
        species_stats = db.session.query(
            ProductionItem.parsed_wood_species,
            func.count(ProductionItem.id).label('count'),
            func.sum(ProductionItem.volume_m3 * ProductionItem.quantity).label('volume')
        ).filter(
            ProductionItem.parsed_wood_species.isnot(None),
            ProductionItem.current_status != 'anulowane'
        ).group_by(ProductionItem.parsed_wood_species).all()

        species_breakdown = [
            {
                'name': row[0] or 'Nieokreślony',
                'count': row[1],
                'volume': float(row[2] or 0)
            }
            for row in species_stats
        ]

        # Rozkład według grubości
        thickness_stats = db.session.query(
            ProductionItem.parsed_thickness_cm,
            func.count(ProductionItem.id).label('count'),
            func.sum(ProductionItem.volume_m3 * ProductionItem.quantity).label('volume')
        ).filter(
            ProductionItem.parsed_thickness_cm.isnot(None),
            ProductionItem.current_status != 'anulowane'
        ).group_by(ProductionItem.parsed_thickness_cm).all()

        thickness_breakdown = [
            {
                'thickness': float(row[0]) if row[0] else 0,
                'count': row[1],
                'volume': float(row[2] or 0)
            }
            for row in thickness_stats
        ]
        # Sortowanie po grubości
        thickness_breakdown.sort(key=lambda x: x['thickness'])

        # Rozkład według technologii
        technology_stats = db.session.query(
            ProductionItem.parsed_technology,
            func.count(ProductionItem.id).label('count'),
            func.sum(ProductionItem.volume_m3 * ProductionItem.quantity).label('volume')
        ).filter(
            ProductionItem.parsed_technology.isnot(None),
            ProductionItem.current_status != 'anulowane'
        ).group_by(ProductionItem.parsed_technology).all()

        technology_breakdown = [
            {
                'name': row[0] or 'Nieokreślona',
                'count': row[1],
                'volume': float(row[2] or 0)
            }
            for row in technology_stats
        ]

        # Rozkład według klasy drewna
        wood_class_stats = db.session.query(
            ProductionItem.parsed_wood_class,
            func.count(ProductionItem.id).label('count'),
            func.sum(ProductionItem.volume_m3 * ProductionItem.quantity).label('volume')
        ).filter(
            ProductionItem.parsed_wood_class.isnot(None),
            ProductionItem.parsed_wood_class != '',
            ProductionItem.current_status != 'anulowane'
        ).group_by(ProductionItem.parsed_wood_class).all()

        wood_class_breakdown = [
            {
                'name': row[0] or 'Nieokreślona',
                'count': row[1],
                'volume': float(row[2] or 0)
            }
            for row in wood_class_stats
        ]

        # Przygotuj dane jako dict dla JSON response
        reports_data_dict = {
            'daily_performance': daily_stats,
            'status_breakdown': status_report,
            'species_breakdown': species_breakdown,
            'thickness_breakdown': thickness_breakdown,
            'technology_breakdown': technology_breakdown,
            'wood_class_breakdown': wood_class_breakdown,
            'sync_history': [
                {
                    'date': sync.sync_started_at.isoformat(),
                    'status': sync.sync_status,  # POPRAWIONE: sync_status zamiast status
                    'items_processed': (sync.products_created or 0) + (sync.products_updated or 0),
                    'duration_seconds': sync.sync_duration_seconds or 0
                }
                for sync in sync_history
            ],
            'summary': {
                'week_completed': sum(day['completed_orders'] for day in daily_stats),
                'week_volume': sum(day['total_volume'] for day in daily_stats),
                'total_in_system': sum(item['count'] for item in status_report)
            }
        }

        # Renderuj komponent - używamy dict z bracket notation w Jinja
        rendered_html = render_template('components/reports-tab-content.html',
                              reports_data=reports_data_dict)
        
        return jsonify({
            'success': True,
            'html': rendered_html,
            'data': reports_data_dict,  # Zwracamy dict dla JSON
            'last_updated': get_local_now().isoformat()
        })
        
    except Exception as e:
        logger.error("Błąd AJAX reports-tab-content", extra={
            'user_id': current_user.id,
            'error': str(e)
        })
        
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500



