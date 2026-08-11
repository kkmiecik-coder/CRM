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
from sqlalchemy.orm import joinedload

from . import api_bp, logger, ProductionItem, ProductionSyncLog, get_local_now
from modules.production.models import ProductionConfiguration

VALID_STATIONS = {
    'cutting', 'assembly', 'gluing', 'formatting',
    'finishing', 'painting', 'packaging'
}

STATION_LABELS = {
    'cutting': 'Wycinanie',
    'assembly': 'Składanie',
    'gluing': 'Sklejanie',
    'formatting': 'Formatowanie',
    'finishing': 'Wykańczanie',
    'painting': 'Lakiernia',
    'packaging': 'Pakowanie',
}


def _parsuj_zakres_dat():
    """
    Wspólne parsowanie start_date/end_date dla raportów. Zwraca
    (start_date, end_date, error_response) — jak w reports_station_output,
    tylko wyciągnięte, żeby nie kopiować walidacji do raportu pracowników.
    """
    start_str = request.args.get('start_date', '').strip()
    end_str = request.args.get('end_date', '').strip()

    try:
        if start_str and end_str:
            start = datetime.strptime(start_str, '%Y-%m-%d').date()
            end = datetime.strptime(end_str, '%Y-%m-%d').date()
        else:
            # Domyślnie bieżący tydzień wstecz — sensowny zakres na wejściu
            end = date.today()
            start = end - timedelta(days=6)
    except ValueError:
        return None, None, (jsonify({
            'success': False,
            'error': 'Nieprawidłowy format daty (oczekiwane YYYY-MM-DD)'
        }), 400)

    return start, end, None


@api_bp.route('/reports/worker-output')
@login_required
def reports_worker_output():
    """
    GET /production/api/reports/worker-output
        ?start_date=YYYY-MM-DD&end_date=YYYY-MM-DD
        &station=all|<station_code>&worker_id=<opcjonalnie>
        &format=json|xlsx

    Wydajność pracowników liczona z atrybucji eventów stanowiskowych
    (docs/worker-profiles-backend.md §7.2). Jeden event dzieli się między
    pracowników przez share = 1/N, więc sumy są ułamkowe.

    Dane są POGLĄDOWE: wybór profilu na tablecie nie jest chroniony hasłem.
    Odpowiedź niesie attribution_coverage_pct — ile produkcji w okresie
    w ogóle da się komuś przypisać.
    """
    from ...services import worker_stats_service
    from ...services.worker_stats_service import ZakresError

    start_date, end_date, err = _parsuj_zakres_dat()
    if err:
        return err

    station = request.args.get('station', 'all').strip().lower() or 'all'
    if station != 'all' and station not in VALID_STATIONS:
        return jsonify({
            'success': False,
            'error': f'Nieprawidłowe stanowisko. Dozwolone: all, {sorted(VALID_STATIONS)}'
        }), 400

    worker_id = request.args.get('worker_id', '').strip()
    try:
        worker_id = int(worker_id) if worker_id else None
    except ValueError:
        return jsonify({'success': False, 'error': 'worker_id musi być liczbą'}), 400

    try:
        raport = worker_stats_service.raport_wydajnosci(
            start_date, end_date, station=station, worker_id=worker_id)
    except ZakresError as e:
        return jsonify({'success': False, 'error': str(e)}), 400

    if request.args.get('format', 'json').strip().lower() == 'xlsx':
        return _eksport_raportu_pracownikow(raport)

    return jsonify({'success': True, 'report': raport})


def _eksport_raportu_pracownikow(raport):
    """XLSX z dwoma arkuszami: podsumowanie per pracownik i pełne wiersze."""
    from io import BytesIO

    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font
    except ImportError:
        logger.warning("openpyxl niedostępne — eksport raportu pracowników odrzucony")
        return jsonify({'success': False,
                        'error': 'Eksport XLSX niedostępny (brak openpyxl)'}), 501

    wb = Workbook()

    ark = wb.active
    ark.title = 'Podsumowanie'
    ark.append(['Pracownik', 'Sztuki', 'm3', 'Godziny', 'Tempo (m3/h)', 'Stanowiska'])
    for komorka in ark[1]:
        komorka.font = Font(bold=True)
    for wiersz in raport['worker_totals']:
        ark.append([
            wiersz['worker_name'], wiersz['pieces'], wiersz['m3'],
            wiersz['hours'], wiersz['pace_m3_per_hour'],
            ', '.join(wiersz['stations']),
        ])

    podsumowanie = raport['summary']
    ark.append([])
    ark.append(['Nieprzypisane', podsumowanie['unassigned_pieces'],
                podsumowanie['unassigned_m3']])
    ark.append(['Pokrycie atrybucją (%)', podsumowanie['attribution_coverage_pct']])
    ark.append(['UWAGA: wybór profilu na tablecie nie jest chroniony hasłem — '
                'dane mają charakter poglądowy'])

    szczegoly = wb.create_sheet('Szczegóły')
    szczegoly.append(['Data', 'Pracownik', 'Stanowisko', 'Sztuki', 'm3'])
    for komorka in szczegoly[1]:
        komorka.font = Font(bold=True)
    for wiersz in raport['rows']:
        szczegoly.append([wiersz['work_date'], wiersz['worker_name'],
                          wiersz['station_label'], wiersz['pieces'], wiersz['m3']])
    for wiersz in raport['unassigned']:
        szczegoly.append([wiersz['work_date'], 'Nieprzypisane',
                          wiersz['station_label'], wiersz['pieces'], wiersz['m3']])

    strumien = BytesIO()
    wb.save(strumien)
    strumien.seek(0)

    from flask import Response
    nazwa = f"wydajnosc_pracownikow_{raport['start_date']}_{raport['end_date']}.xlsx"
    odpowiedz = Response(
        strumien.getvalue(),
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    odpowiedz.headers['Content-Disposition'] = f'attachment; filename={nazwa}'
    return odpowiedz


@api_bp.route('/reports/station-output')
@login_required
def reports_station_output():
    """
    GET /production/api/reports/station-output?station=<code|all>
        &start_date=YYYY-MM-DD&end_date=YYYY-MM-DD
        (lub: &date=YYYY-MM-DD — wsteczna kompat, pojedynczy dzień)

    Zwraca pozycje produkcyjne, na których wybrane stanowisko (lub
    dowolne stanowisko gdy station='all') wykonało jakąkolwiek operację
    w zakresie dat (włącznie).

    Dla każdej pozycji (wiersz per item × stanowisko):
    - quantity_done_eod: stan quantity_done_<station> po ostatnim evencie
      w zakresie — ile zostało wykonane na koniec zakresu
    - day_delta_sum: netto ruch w zakresie (suma delta) — np. +5,-1,+2 = +6
    - station_code, station_label: stanowisko, którego dotyczy wiersz
    - quantity: total szt. pozycji
    - volume_per_unit, volume_done_eod (m³)
    - meta: short_product_id, original_product_name, baselinker_order_id, status, gatunek/grubość

    Timeline: 48 bucketów po 30 min, sumy delta i delta*volume_m3
    (przez wszystkie stanowiska gdy station='all'). Frontend dzieli
    przez days_count żeby uzyskać średnią dzienną.

    Sortowanie: po ostatnim evencie w zakresie (najnowsze najpierw).
    """
    from ...models import ProductionStationEvent
    from sqlalchemy import and_

    station = request.args.get('station', '').strip().lower()
    start_date_str = request.args.get('start_date', '').strip()
    end_date_str = request.args.get('end_date', '').strip()
    date_str = request.args.get('date', '').strip()  # wsteczna kompat

    is_all_stations = station == 'all'
    if not is_all_stations and station not in VALID_STATIONS:
        return jsonify({
            'success': False,
            'error': f'Nieprawidłowe stanowisko. Dozwolone: all, {sorted(VALID_STATIONS)}'
        }), 400

    # Parsowanie zakresu: preferuj start_date/end_date, fallback na date.
    try:
        if start_date_str and end_date_str:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
        elif date_str:
            start_date = datetime.strptime(date_str, '%Y-%m-%d').date()
            end_date = start_date
        else:
            start_date = end_date = date.today()
    except ValueError:
        return jsonify({
            'success': False,
            'error': 'Nieprawidłowy format daty (oczekiwane YYYY-MM-DD)'
        }), 400

    if start_date > end_date:
        return jsonify({
            'success': False,
            'error': 'Data początkowa musi być wcześniejsza lub równa końcowej'
        }), 400

    days_count = (end_date - start_date).days + 1
    if days_count > 365:
        return jsonify({
            'success': False,
            'error': 'Maksymalny zakres to 365 dni'
        }), 400

    range_start = datetime.combine(start_date, datetime.min.time())
    range_end = datetime.combine(end_date, datetime.max.time())

    try:
        # Wspólne filtry zakresu czasu (+ ewentualnie konkretne stanowisko)
        time_filters = [
            ProductionStationEvent.created_at >= range_start,
            ProductionStationEvent.created_at <= range_end,
        ]
        if not is_all_stations:
            time_filters.append(ProductionStationEvent.station_code == station)

        # Per (item, station) agregacja eventów w zakresie.
        # Group by zawsze po (item_id, station_code) — dla pojedynczego
        # stanowiska wszystkie wiersze i tak mają to samo station_code,
        # więc koszt jest zerowy a kod jest unifikowany.
        # day_delta_sum = SUM(delta) (mimo nazwy — to ruch w całym zakresie)
        # last_event_at = MAX(created_at)
        agg = db.session.query(
            ProductionStationEvent.production_item_id.label('item_id'),
            ProductionStationEvent.station_code.label('station_code'),
            func.sum(ProductionStationEvent.delta).label('day_delta_sum'),
            func.max(ProductionStationEvent.created_at).label('last_event_at'),
            func.count(ProductionStationEvent.id).label('event_count'),
        ).filter(*time_filters).group_by(
            ProductionStationEvent.production_item_id,
            ProductionStationEvent.station_code,
        ).subquery()

        # quantity_done_after z ostatniego eventu w zakresie per (item, station).
        # Join po (item, station, last_event_at) — w razie remisu created_at
        # join produkcyjnie zwróci wszystkie kolizje, później dedup w pętli.
        last_event = db.session.query(
            ProductionStationEvent.production_item_id.label('item_id'),
            ProductionStationEvent.station_code.label('station_code'),
            ProductionStationEvent.created_at.label('last_event_at'),
            ProductionStationEvent.quantity_done_after.label('quantity_done_eod'),
        ).filter(*time_filters).subquery()

        rows = db.session.query(
            ProductionItem,
            agg.c.station_code,
            agg.c.day_delta_sum,
            agg.c.last_event_at,
            agg.c.event_count,
            last_event.c.quantity_done_eod,
        ).options(
            joinedload(ProductionItem.order),
            joinedload(ProductionItem.configuration),
        ).join(
            agg, ProductionItem.id == agg.c.item_id
        ).join(
            last_event,
            and_(
                last_event.c.item_id == agg.c.item_id,
                last_event.c.station_code == agg.c.station_code,
                last_event.c.last_event_at == agg.c.last_event_at,
            )
        ).order_by(agg.c.last_event_at.desc()).all()

        items_payload = []
        sum_qty_done_eod = 0
        sum_volume_done_eod = 0.0
        sum_day_delta = 0

        # Dedup po (item_id, station_code) — w razie remisu created_at
        # na ostatnim evencie agregat i tak ten sam, bierzemy pierwszy zwrot.
        seen_keys = set()
        for item, station_code_row, day_delta_sum, last_event_at, event_count, qty_done_eod in rows:
            key = (item.id, station_code_row)
            if key in seen_keys:
                continue
            seen_keys.add(key)

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
                'baselinker_order_id': item.order.baselinker_order_id if item.order else None,
                'internal_order_number': item.order.internal_order_number if item.order else None,
                'current_status': item.current_status,
                'quantity': item.quantity,
                'quantity_done_eod': qty_done_eod,
                'day_delta_sum': day_delta_sum,
                'event_count': int(event_count or 0),
                'volume_per_unit_m3': round(volume_per_unit, 4),
                'volume_done_eod_m3': round(volume_done_eod, 4),
                'wood_species': item.configuration.species if item.configuration else None,
                'thickness_cm': float(item.parsed_thickness_cm) if item.parsed_thickness_cm else None,
                'last_event_at': last_event_at.isoformat() if last_event_at else None,
                'station_code': station_code_row,
                'station_label': STATION_LABELS.get(station_code_row, station_code_row),
            })

        # Timeline 48 bucketów po 30 minut (00:00, 00:30, ..., 23:30)
        # bucket_idx = floor((HOUR*60 + MINUTE) / 30) ∈ [0, 47]
        # Net delta per bucket (cofnięcia mogą dać wartość ujemną).
        # Sumowanie po wszystkich dniach w zakresie — frontend dzieli
        # przez days_count żeby uzyskać średnią dzienną gdy zakres > 1 dnia.
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
        ).filter(*time_filters).group_by(bucket_idx_expr).all()

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
            'station_label': 'Wszystkie stanowiska' if is_all_stations
                else STATION_LABELS.get(station, station),
            'is_all_stations': is_all_stations,
            # Wsteczna kompat: 'date' = start gdy pojedynczy dzień, inaczej None
            'date': start_date.isoformat() if days_count == 1 else None,
            'start_date': start_date.isoformat(),
            'end_date': end_date.isoformat(),
            'days_count': days_count,
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
                'days_count': days_count,
            },
        })

    except Exception as e:
        logger.error("Błąd /reports/station-output", extra={
            'user_id': current_user.id,
            'station': station,
            'start_date': start_date.isoformat() if 'start_date' in locals() else None,
            'end_date': end_date.isoformat() if 'end_date' in locals() else None,
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
            ProductionConfiguration.species,
            ProductionConfiguration.technology,
            func.sum(ProductionItem.volume_m3 * ProductionItem.quantity).label('volume')
        ).join(ProductionConfiguration, ProductionItem.configuration_id == ProductionConfiguration.id).filter(
            ProductionItem.current_status.isnot(None),
            ProductionConfiguration.species.isnot(None)
        ).group_by(
            ProductionItem.current_status,
            ProductionConfiguration.species,
            ProductionConfiguration.technology
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
            ProductionConfiguration.species,
            func.count(ProductionItem.id).label('count'),
            func.sum(ProductionItem.volume_m3 * ProductionItem.quantity).label('volume')
        ).join(ProductionConfiguration, ProductionItem.configuration_id == ProductionConfiguration.id).filter(
            ProductionConfiguration.species.isnot(None),
            ProductionItem.current_status != 'anulowane'
        ).group_by(ProductionConfiguration.species).all()

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
            ProductionConfiguration.technology,
            func.count(ProductionItem.id).label('count'),
            func.sum(ProductionItem.volume_m3 * ProductionItem.quantity).label('volume')
        ).join(ProductionConfiguration, ProductionItem.configuration_id == ProductionConfiguration.id).filter(
            ProductionConfiguration.technology.isnot(None),
            ProductionItem.current_status != 'anulowane'
        ).group_by(ProductionConfiguration.technology).all()

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
            ProductionConfiguration.wood_class,
            func.count(ProductionItem.id).label('count'),
            func.sum(ProductionItem.volume_m3 * ProductionItem.quantity).label('volume')
        ).join(ProductionConfiguration, ProductionItem.configuration_id == ProductionConfiguration.id).filter(
            ProductionConfiguration.wood_class.isnot(None),
            ProductionConfiguration.wood_class != 'unknown',
            ProductionItem.current_status != 'anulowane'
        ).group_by(ProductionConfiguration.wood_class).all()

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



