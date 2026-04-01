# modules/production/routers/api/dashboard_api.py
"""
Dashboard tab content + data endpoints.
Extracted from api_routers.py.
"""

import traceback
from datetime import datetime, date, timedelta
from flask import request, jsonify, render_template
from flask_login import login_required, current_user
from extensions import db
from sqlalchemy import func, and_

from . import api_bp, logger, ProductionItem, ProductionError, ProductionSyncLog, get_local_now


# ============================================================================
# DASHBOARD STATS
# ============================================================================

@api_bp.route('/dashboard-stats', methods=['GET'])
@login_required
def dashboard_stats():
    """
    GET /production/api/dashboard-stats

    ROZBUDOWANA WERSJA - Zwraca statystyki dla dashboard z dodatkowymi metrykami

    Query params:
        include_products: true|false - czy dołączyć listę produktów (default: false)
        limit: liczba produktów do zwrócenia (default: 10, max: 50)

    Returns: JSON ze statystykami + opcjonalnie produktami
    """
    try:
        # Parametry opcjonalne
        include_products = request.args.get('include_products', 'false').lower() == 'true'
        limit = min(request.args.get('limit', 10, type=int), 50)

        from ...models import ProductionItem
        from sqlalchemy import func, desc
        from datetime import datetime, timedelta

        # ============================================================================
        # PODSTAWOWE STATYSTYKI (istniejące)
        # ============================================================================

        # Statystyki per status
        status_stats = db.session.query(
            ProductionItem.current_status,
            func.count(ProductionItem.id).label('count'),
            func.avg(ProductionItem.priority_rank).label('avg_priority')
        ).group_by(ProductionItem.current_status).all()

        stations_stats = {}
        total_products = 0

        for status, count, avg_priority in status_stats:
            total_products += count

            if status == 'czeka_na_wyciecie':
                stations_stats['cutting'] = {
                    'waiting_count': count,
                    'avg_priority': round(avg_priority or 0, 1)
                }
            elif status == 'czeka_na_skladanie':
                stations_stats['assembly'] = {
                    'waiting_count': count,
                    'avg_priority': round(avg_priority or 0, 1)
                }
            elif status == 'czeka_na_pakowanie':
                stations_stats['packaging'] = {
                    'waiting_count': count,
                    'avg_priority': round(avg_priority or 0, 1)
                }
            elif status == 'czeka_na_logistyke':
                stations_stats['logistics'] = {
                    'waiting_count': count,
                    'avg_priority': round(avg_priority or 0, 1)
                }

        # ============================================================================
        # DODATKOWE STATYSTYKI (nowe)
        # ============================================================================

        # Produkty z wysokim priorytetem (>=150)
        high_priority_count = ProductionItem.query.filter(
            ProductionItem.priority_rank.isnot(None), ProductionItem.priority_rank <= 10
        ).count()

        # Produkty przeterminowane
        today = datetime.now().date()
        overdue_count = ProductionItem.query.filter(
            ProductionItem.deadline_date < today,
            ProductionItem.current_status != 'spakowane'
        ).count()

        # Produkty spakowane dzisiaj
        today_start = datetime.combine(today, datetime.min.time())
        today_end = datetime.combine(today, datetime.max.time())

        completed_today = ProductionItem.query.filter(
            ProductionItem.current_status == 'spakowane',
            ProductionItem.packaging_completed_at >= today_start,
            ProductionItem.packaging_completed_at <= today_end
        ).count() if hasattr(ProductionItem, 'packaging_completed_at') else 0

        # Produkty utworzone w tym tygodniu
        week_ago = today - timedelta(days=7)
        week_start = datetime.combine(week_ago, datetime.min.time())

        new_this_week = ProductionItem.query.filter(
            ProductionItem.created_at >= week_start
        ).count()

        # Średnia objętość w produkcji
        avg_volume = db.session.query(func.avg(ProductionItem.volume_m3)).filter(
            ProductionItem.volume_m3.isnot(None),
            ProductionItem.current_status != 'spakowane'
        ).scalar()

        # ============================================================================
        # ALERTY I OSTRZEŻENIA (nowe)
        # ============================================================================

        alerts = []

        # Alert o przeterminowanych produktach
        if overdue_count > 0:
            alerts.append({
                'type': 'danger',
                'title': 'Produkty przeterminowane',
                'message': f'{overdue_count} produktów przekroczyło deadline',
                'count': overdue_count,
                'priority': 'high'
            })

        # Alert o produktach z wysokim priorytetem
        if high_priority_count > 10:
            alerts.append({
                'type': 'warning',
                'title': 'Dużo produktów wysokiego priorytetu',
                'message': f'{high_priority_count} produktów z priorytetem ≥150',
                'count': high_priority_count,
                'priority': 'medium'
            })

        # Alert o zastoju w produkcji
        cutting_backlog = stations_stats.get('cutting', {}).get('waiting_count', 0)
        if cutting_backlog > 50:
            alerts.append({
                'type': 'info',
                'title': 'Duża kolejka w wycinaniu',
                'message': f'{cutting_backlog} produktów czeka na wycięcie',
                'count': cutting_backlog,
                'priority': 'low'
            })

        # ============================================================================
        # PRZYGOTOWANIE ODPOWIEDZI
        # ============================================================================

        dashboard_data = {
            'success': True,
            'stats': {
                'total_products': total_products,
                'high_priority_count': high_priority_count,
                'overdue_count': overdue_count,
                'completed_today': completed_today,
                'new_this_week': new_this_week,
                'avg_volume_m3': round(avg_volume or 0, 2),
                'stations': stations_stats
            },
            'alerts': alerts,
            'last_updated': get_local_now().isoformat()
        }

        # ============================================================================
        # OPCJONALNE PRODUKTY
        # ============================================================================

        if include_products:
            # Najwyższy priorytet + najbliższe deadline
            priority_products = ProductionItem.query.filter(
                ProductionItem.current_status != 'spakowane'
            ).order_by(
                ProductionItem.priority_rank.asc(),
                ProductionItem.deadline_date.asc()
            ).limit(limit).all()

            products_data = []
            for product in priority_products:
                days_to_deadline = None
                if product.deadline_date:
                    days_to_deadline = (product.deadline_date - today).days

                products_data.append({
                    'id': product.id,
                    'short_product_id': product.short_product_id,
                    'internal_order_number': product.internal_order_number,
                    'original_product_name': product.original_product_name[:50] + '...' if len(product.original_product_name) > 50 else product.original_product_name,
                    'current_status': product.current_status,
                    'priority_rank': product.priority_rank or 0,
                    'deadline_date': product.deadline_date.isoformat() if product.deadline_date else None,
                    'days_to_deadline': days_to_deadline,
                    'is_overdue': days_to_deadline is not None and days_to_deadline < 0,
                    'is_urgent': days_to_deadline is not None and days_to_deadline <= 2
                })

            dashboard_data['products'] = products_data

        logger.info("Dashboard stats - rozbudowane", extra={
            'user_id': current_user.id,
            'include_products': include_products,
            'total_products': total_products,
            'alerts_count': len(alerts)
        })

        return jsonify(dashboard_data)

    except Exception as e:
        logger.error("Błąd dashboard stats - rozbudowanych", extra={
            'user_id': current_user.id if current_user.is_authenticated else None,
            'error': str(e)
        })
        return jsonify({
            'success': False,
            'error': f'Błąd pobierania statystyk: {str(e)}'
        }), 500


# ============================================================================
# CHART DATA
# ============================================================================

@api_bp.route('/chart-data')
@login_required
def chart_data():
    """
    AJAX endpoint dla danych wykresów wydajności dziennej (tylko admin)

    Query params:
        period: int - liczba dni do pobrania (7, 14, 30, 90, 180, 365)
        station: str - opcjonalnie konkretne stanowisko (cutting, assembly, etc.)
                       Gdy podane, zwraca 2 datasety: objętość i ilość sztuk
                       Gdy 'all' lub puste - zwraca 6 datasetów tylko z objętością

    Returns:
        JSON: Dane wydajności per stanowisko i okres dla Chart.js
    """
    try:
        period = request.args.get('period', 7, type=int)
        station_filter = request.args.get('station', 'all', type=str)

        # Walidacja okresu - ROZSZERZONA
        if period not in [7, 14, 30, 90, 180, 365]:
            return jsonify({
                'success': False,
                'error': 'Nieprawidłowy okres. Dozwolone: 7, 14, 30, 90, 180, 365 dni'
            }), 400

        # Walidacja stanowiska
        valid_stations = ['all', 'cutting', 'assembly', 'gluing', 'formatting', 'finishing', 'packaging']
        if station_filter not in valid_stations:
            return jsonify({
                'success': False,
                'error': f'Nieprawidłowe stanowisko. Dozwolone: {valid_stations}'
            }), 400

        logger.info(f"AJAX: Pobieranie danych wykresów dla {period} dni, stanowisko: {station_filter}", extra={
            'user_id': current_user.id,
            'period': period,
            'station': station_filter
        })

        from ...models import ProductionItem
        from sqlalchemy import and_, func
        from datetime import datetime, timedelta, date

        # Oblicz zakres dat
        end_date = date.today()
        start_date = end_date - timedelta(days=period - 1)

        # Mapowanie stanowisk
        station_completion_mapping = {
            'cutting': 'cutting_completed_at',
            'assembly': 'assembly_completed_at',
            'gluing': 'gluing_completed_at',
            'formatting': 'formatting_completed_at',
            'finishing': 'finishing_completed_at',
            'packaging': 'packaging_completed_at'
        }

        station_quantity_mapping = {
            'cutting': 'quantity_done_cutting',
            'assembly': 'quantity_done_assembly',
            'gluing': 'quantity_done_gluing',
            'formatting': 'quantity_done_formatting',
            'finishing': 'quantity_done_finishing',
            'packaging': 'quantity_done_packaging'
        }

        station_labels = {
            'cutting': 'Wycinanie',
            'assembly': 'Składanie',
            'gluing': 'Sklejanie',
            'formatting': 'Formatowanie',
            'finishing': 'Wykańczanie',
            'packaging': 'Pakowanie'
        }

        station_colors = {
            'cutting': {'border': '#fd7e14', 'bg': 'rgba(253, 126, 20, 0.1)'},
            'assembly': {'border': '#007bff', 'bg': 'rgba(0, 123, 255, 0.1)'},
            'gluing': {'border': '#9c27b0', 'bg': 'rgba(156, 39, 176, 0.1)'},
            'formatting': {'border': '#ff5722', 'bg': 'rgba(255, 87, 34, 0.1)'},
            'finishing': {'border': '#00bcd4', 'bg': 'rgba(0, 188, 212, 0.1)'},
            'packaging': {'border': '#28a745', 'bg': 'rgba(40, 167, 69, 0.1)'}
        }

        # NOWE: Określ typ agregacji na podstawie okresu
        if period <= 30:
            aggregation_type = 'daily'
        elif period == 90:
            aggregation_type = 'weekly'
        else:  # 180, 365
            aggregation_type = 'monthly'

        # =====================================================================
        # TRYB: Pojedyncze stanowisko (3 krzywe: objętość + ilość + wartość netto)
        # =====================================================================
        if station_filter != 'all':
            completion_field = station_completion_mapping[station_filter]
            quantity_field = station_quantity_mapping[station_filter]
            station_label = station_labels[station_filter]
            station_color = station_colors[station_filter]

            # Sprawdź czy pola istnieją
            try:
                completion_attr = getattr(ProductionItem, completion_field)
                quantity_attr = getattr(ProductionItem, quantity_field)
            except AttributeError:
                return jsonify({
                    'success': False,
                    'error': f'Stanowisko {station_filter} nie ma jeszcze zaimplementowanych pól w bazie'
                }), 400

            # Zapytanie o sumę objętości, ilości i wartości netto per dzień
            daily_stats = db.session.query(
                func.date(completion_attr).label('completion_date'),
                func.sum(ProductionItem.volume_m3).label('total_volume'),
                func.sum(quantity_attr).label('total_quantity'),
                func.sum(ProductionItem.total_value_net).label('total_value')
            ).filter(
                and_(
                    completion_attr.isnot(None),
                    func.date(completion_attr) >= start_date,
                    func.date(completion_attr) <= end_date
                )
            ).group_by(
                func.date(completion_attr)
            ).all()

            # Wypełnij dane
            daily_data = {}
            for completion_date, total_volume, total_quantity, total_value in daily_stats:
                daily_data[completion_date] = {
                    'volume': float(total_volume or 0),
                    'quantity': int(total_quantity or 0),
                    'value': float(total_value or 0)
                }

            # Przygotuj chart_data dla pojedynczego stanowiska
            chart_data_result = {
                'labels': [],
                'datasets': [
                    {
                        'label': f'{station_label} - Objętość (m³)',
                        'data': [],
                        'borderColor': '#007bff',
                        'backgroundColor': 'rgba(0, 123, 255, 0.1)',
                        'tension': 0.4,
                        'fill': True,
                        'yAxisID': 'y'
                    },
                    {
                        'label': f'{station_label} - Ilość (szt.)',
                        'data': [],
                        'borderColor': '#fd7e14',
                        'backgroundColor': 'rgba(253, 126, 20, 0.1)',
                        'tension': 0.4,
                        'fill': True,
                        'yAxisID': 'y1',
                        'borderDash': [5, 5]
                    },
                    {
                        'label': f'{station_label} - Wartość netto (PLN)',
                        'data': [],
                        'borderColor': '#28a745',
                        'backgroundColor': 'rgba(40, 167, 69, 0.1)',
                        'tension': 0.4,
                        'fill': True,
                        'yAxisID': 'y2',
                        'borderDash': [2, 2]
                    }
                ]
            }

            # Agregacja danych
            if aggregation_type == 'daily':
                current_date = start_date
                while current_date <= end_date:
                    label = current_date.strftime('%Y-%m-%d')
                    chart_data_result['labels'].append(label)
                    data = daily_data.get(current_date, {'volume': 0.0, 'quantity': 0, 'value': 0.0})
                    chart_data_result['datasets'][0]['data'].append(data['volume'])
                    chart_data_result['datasets'][1]['data'].append(data['quantity'])
                    chart_data_result['datasets'][2]['data'].append(data['value'])
                    current_date += timedelta(days=1)

            elif aggregation_type == 'weekly':
                from collections import defaultdict
                weekly_data = defaultdict(lambda: {'volume': 0.0, 'quantity': 0, 'value': 0.0})
                for day_date, data in daily_data.items():
                    week_start = day_date - timedelta(days=day_date.weekday())
                    weekly_data[week_start]['volume'] += data['volume']
                    weekly_data[week_start]['quantity'] += data['quantity']
                    weekly_data[week_start]['value'] += data['value']

                current_date = start_date - timedelta(days=start_date.weekday())
                while current_date <= end_date:
                    week_label = current_date.strftime('%Y-%m-%d')
                    chart_data_result['labels'].append(week_label)
                    chart_data_result['datasets'][0]['data'].append(weekly_data[current_date]['volume'])
                    chart_data_result['datasets'][1]['data'].append(weekly_data[current_date]['quantity'])
                    chart_data_result['datasets'][2]['data'].append(weekly_data[current_date]['value'])
                    current_date += timedelta(weeks=1)

            elif aggregation_type == 'monthly':
                from collections import defaultdict
                monthly_data = defaultdict(lambda: {'volume': 0.0, 'quantity': 0, 'value': 0.0})
                for day_date, data in daily_data.items():
                    month_start = date(day_date.year, day_date.month, 1)
                    monthly_data[month_start]['volume'] += data['volume']
                    monthly_data[month_start]['quantity'] += data['quantity']
                    monthly_data[month_start]['value'] += data['value']

                current_month = date(start_date.year, start_date.month, 1)
                end_month = date(end_date.year, end_date.month, 1)
                while current_month <= end_month:
                    month_label = current_month.strftime('%Y-%m-01')
                    chart_data_result['labels'].append(month_label)
                    chart_data_result['datasets'][0]['data'].append(monthly_data[current_month]['volume'])
                    chart_data_result['datasets'][1]['data'].append(monthly_data[current_month]['quantity'])
                    chart_data_result['datasets'][2]['data'].append(monthly_data[current_month]['value'])
                    if current_month.month == 12:
                        current_month = date(current_month.year + 1, 1, 1)
                    else:
                        current_month = date(current_month.year, current_month.month + 1, 1)

            # Statystyki dla pojedynczego stanowiska
            total_volume = sum(chart_data_result['datasets'][0]['data'])
            total_quantity = sum(chart_data_result['datasets'][1]['data'])
            total_value = sum(chart_data_result['datasets'][2]['data'])
            num_periods = len(chart_data_result['labels']) if chart_data_result['labels'] else 1

            summary = {
                'period_days': period,
                'aggregation_type': aggregation_type,
                'station': station_filter,
                'station_label': station_label,
                'total_volume': round(total_volume, 2),
                'total_quantity': total_quantity,
                'total_value': round(total_value, 2),
                'avg_volume_per_period': round(total_volume / num_periods, 2),
                'avg_quantity_per_period': round(total_quantity / num_periods, 1),
                'avg_value_per_period': round(total_value / num_periods, 2)
            }

            response_data = {
                'success': True,
                'chart_data': chart_data_result,
                'summary': summary,
                'period': period,
                'station': station_filter,
                'mode': 'single_station',
                'date_range': {
                    'start': start_date.isoformat(),
                    'end': end_date.isoformat()
                },
                'generated_at': get_local_now().isoformat()
            }

            return jsonify(response_data)

        # =====================================================================
        # TRYB: Wszystkie stanowiska (6 krzywych, tylko objętość)
        # =====================================================================
        chart_data_result = {
            'labels': [],
            'datasets': [
                {
                    'label': 'Wycinanie',
                    'data': [],
                    'borderColor': '#fd7e14',
                    'backgroundColor': 'rgba(253, 126, 20, 0.1)',
                    'tension': 0.4,
                    'fill': True
                },
                {
                    'label': 'Składanie',
                    'data': [],
                    'borderColor': '#007bff',
                    'backgroundColor': 'rgba(0, 123, 255, 0.1)',
                    'tension': 0.4,
                    'fill': True
                },
                {
                    'label': 'Sklejanie',
                    'data': [],
                    'borderColor': '#9c27b0',
                    'backgroundColor': 'rgba(156, 39, 176, 0.1)',
                    'tension': 0.4,
                    'fill': True
                },
                {
                    'label': 'Formatowanie',
                    'data': [],
                    'borderColor': '#ff5722',
                    'backgroundColor': 'rgba(255, 87, 34, 0.1)',
                    'tension': 0.4,
                    'fill': True
                },
                {
                    'label': 'Wykańczanie',
                    'data': [],
                    'borderColor': '#00bcd4',
                    'backgroundColor': 'rgba(0, 188, 212, 0.1)',
                    'tension': 0.4,
                    'fill': True
                },
                {
                    'label': 'Pakowanie',
                    'data': [],
                    'borderColor': '#28a745',
                    'backgroundColor': 'rgba(40, 167, 69, 0.1)',
                    'tension': 0.4,
                    'fill': True
                }
            ]
        }

        # Pobierz dane wydajności dla każdego stanowiska
        daily_data = {}

        for station, completion_field in station_completion_mapping.items():
            try:
                completion_attr = getattr(ProductionItem, completion_field)
            except AttributeError:
                continue

            daily_volumes = db.session.query(
                func.date(completion_attr).label('completion_date'),
                func.sum(ProductionItem.volume_m3).label('total_volume')
            ).filter(
                and_(
                    completion_attr.isnot(None),
                    func.date(completion_attr) >= start_date,
                    func.date(completion_attr) <= end_date
                )
            ).group_by(
                func.date(completion_attr)
            ).all()

            for completion_date, total_volume in daily_volumes:
                if completion_date not in daily_data:
                    daily_data[completion_date] = {
                        'cutting': 0.0,
                        'assembly': 0.0,
                        'gluing': 0.0,
                        'formatting': 0.0,
                        'finishing': 0.0,
                        'packaging': 0.0
                    }
                daily_data[completion_date][station] = float(total_volume or 0)

        # NOWE: Agreguj dane według typu
        if aggregation_type == 'daily':
            current_date = start_date
            while current_date <= end_date:
                label = current_date.strftime('%Y-%m-%d')
                chart_data_result['labels'].append(label)

                if current_date not in daily_data:
                    daily_data[current_date] = {
                        'cutting': 0.0, 'assembly': 0.0, 'gluing': 0.0,
                        'formatting': 0.0, 'finishing': 0.0, 'packaging': 0.0
                    }

                chart_data_result['datasets'][0]['data'].append(daily_data[current_date]['cutting'])
                chart_data_result['datasets'][1]['data'].append(daily_data[current_date]['assembly'])
                chart_data_result['datasets'][2]['data'].append(daily_data[current_date]['gluing'])
                chart_data_result['datasets'][3]['data'].append(daily_data[current_date]['formatting'])
                chart_data_result['datasets'][4]['data'].append(daily_data[current_date]['finishing'])
                chart_data_result['datasets'][5]['data'].append(daily_data[current_date]['packaging'])
                current_date += timedelta(days=1)

        elif aggregation_type == 'weekly':
            from collections import defaultdict
            weekly_data = defaultdict(lambda: {
                'cutting': 0.0, 'assembly': 0.0, 'gluing': 0.0,
                'formatting': 0.0, 'finishing': 0.0, 'packaging': 0.0
            })

            for day_date, volumes in daily_data.items():
                week_start = day_date - timedelta(days=day_date.weekday())
                for station in ['cutting', 'assembly', 'gluing', 'formatting', 'finishing', 'packaging']:
                    weekly_data[week_start][station] += volumes[station]

            current_date = start_date - timedelta(days=start_date.weekday())
            while current_date <= end_date:
                week_label = current_date.strftime('%Y-%m-%d')
                chart_data_result['labels'].append(week_label)
                chart_data_result['datasets'][0]['data'].append(weekly_data[current_date]['cutting'])
                chart_data_result['datasets'][1]['data'].append(weekly_data[current_date]['assembly'])
                chart_data_result['datasets'][2]['data'].append(weekly_data[current_date]['gluing'])
                chart_data_result['datasets'][3]['data'].append(weekly_data[current_date]['formatting'])
                chart_data_result['datasets'][4]['data'].append(weekly_data[current_date]['finishing'])
                chart_data_result['datasets'][5]['data'].append(weekly_data[current_date]['packaging'])
                current_date += timedelta(weeks=1)

        elif aggregation_type == 'monthly':
            from collections import defaultdict
            monthly_data = defaultdict(lambda: {
                'cutting': 0.0, 'assembly': 0.0, 'gluing': 0.0,
                'formatting': 0.0, 'finishing': 0.0, 'packaging': 0.0
            })

            for day_date, volumes in daily_data.items():
                month_start = date(day_date.year, day_date.month, 1)
                for station in ['cutting', 'assembly', 'gluing', 'formatting', 'finishing', 'packaging']:
                    monthly_data[month_start][station] += volumes[station]

            current_month = date(start_date.year, start_date.month, 1)
            end_month = date(end_date.year, end_date.month, 1)

            while current_month <= end_month:
                month_label = current_month.strftime('%Y-%m-01')
                chart_data_result['labels'].append(month_label)
                chart_data_result['datasets'][0]['data'].append(monthly_data[current_month]['cutting'])
                chart_data_result['datasets'][1]['data'].append(monthly_data[current_month]['assembly'])
                chart_data_result['datasets'][2]['data'].append(monthly_data[current_month]['gluing'])
                chart_data_result['datasets'][3]['data'].append(monthly_data[current_month]['formatting'])
                chart_data_result['datasets'][4]['data'].append(monthly_data[current_month]['finishing'])
                chart_data_result['datasets'][5]['data'].append(monthly_data[current_month]['packaging'])

                if current_month.month == 12:
                    current_month = date(current_month.year + 1, 1, 1)
                else:
                    current_month = date(current_month.year, current_month.month + 1, 1)

        # Oblicz statystyki podsumowujące
        total_volumes = {
            'cutting': sum(chart_data_result['datasets'][0]['data']),
            'assembly': sum(chart_data_result['datasets'][1]['data']),
            'gluing': sum(chart_data_result['datasets'][2]['data']),
            'formatting': sum(chart_data_result['datasets'][3]['data']),
            'finishing': sum(chart_data_result['datasets'][4]['data']),
            'packaging': sum(chart_data_result['datasets'][5]['data'])
        }

        num_periods = len(chart_data_result['labels']) if chart_data_result['labels'] else 1
        avg_per_period = {
            'cutting': total_volumes['cutting'] / num_periods,
            'assembly': total_volumes['assembly'] / num_periods,
            'packaging': total_volumes['packaging'] / num_periods
        }

        # Znajdź najlepszy okres
        best_period_idx = 0
        best_period_total = 0
        for i in range(len(chart_data_result['labels'])):
            period_total = (chart_data_result['datasets'][0]['data'][i] +
                          chart_data_result['datasets'][1]['data'][i] +
                          chart_data_result['datasets'][2]['data'][i])
            if period_total > best_period_total:
                best_period_total = period_total
                best_period_idx = i

        summary = {
            'period_days': period,
            'aggregation_type': aggregation_type,
            'total_volumes': total_volumes,
            'avg_per_period': {k: round(v, 2) for k, v in avg_per_period.items()},
            'best_period': {
                'label': chart_data_result['labels'][best_period_idx] if chart_data_result['labels'] else None,
                'volume': round(best_period_total, 2)
            },
            'total_period_volume': round(sum(total_volumes.values()), 2)
        }

        response_data = {
            'success': True,
            'chart_data': chart_data_result,
            'summary': summary,
            'period': period,
            'date_range': {
                'start': start_date.isoformat(),
                'end': end_date.isoformat()
            },
            'generated_at': get_local_now().isoformat()
        }

        logger.info("Pomyślnie wygenerowano dane wykresów", extra={
            'user_id': current_user.id,
            'period': period,
            'aggregation': aggregation_type,
            'total_volume': summary['total_period_volume'],
            'data_points': len(chart_data_result['labels'])
        })

        return jsonify(response_data)

    except Exception as e:
        logger.error("Błąd generowania danych wykresów", extra={
            'user_id': current_user.id,
            'period': request.args.get('period'),
            'error': str(e)
        })

        return jsonify({
            'success': False,
            'error': f'Błąd pobierania danych wykresów: {str(e)}'
        }), 500


# ============================================================================
# DASHBOARD TAB CONTENT (AJAX)
# ============================================================================

@api_bp.route('/dashboard-tab-content')
@login_required
def dashboard_tab_content():
    """
    AJAX endpoint dla zawartości taba Dashboard
    - initial_load=true: zwraca pełny HTML template + początkowe dane
    - initial_load=false/brak: przekierowuje do dashboard-data (tylko JSON)
    """
    try:
        initial_load = request.args.get('initial_load', 'false').lower() == 'true'

        logger.info("AJAX: dashboard-tab-content", extra={
            'user_id': current_user.id,
            'user_role': getattr(current_user, 'role', 'unknown'),
            'initial_load': initial_load
        })

        if not initial_load:
            from flask import redirect, url_for
            return redirect(url_for('production.production_api.dashboard_data'))

        # PIERWSZE ŁADOWANIE - zwróć pełny HTML template
        from ...models import ProductionItem, ProductionError, ProductionSyncLog

        today = date.today()

        dashboard_stats = {}

        # Statystyki stacji
        cutting_count = ProductionItem.query.filter(ProductionItem.current_status == 'czeka_na_wyciecie').count()
        assembly_count = ProductionItem.query.filter(ProductionItem.current_status == 'czeka_na_skladanie').count()
        gluing_count = ProductionItem.query.filter(ProductionItem.current_status == 'czeka_na_sklejanie').count()
        formatting_count = ProductionItem.query.filter(ProductionItem.current_status == 'czeka_na_formatowanie').count()
        finishing_count = ProductionItem.query.filter(ProductionItem.current_status == 'czeka_na_wykanczanie').count()
        packaging_count = ProductionItem.query.filter(ProductionItem.current_status == 'czeka_na_pakowanie').count()

        today_start = datetime.combine(today, datetime.min.time())
        today_end = datetime.combine(today, datetime.max.time())

        cutting_m3_today = 0.0
        assembly_m3_today = 0.0
        gluing_m3_today = 0.0
        formatting_m3_today = 0.0
        finishing_m3_today = 0.0
        packaging_m3_today = 0.0

        try:
            cutting_m3_today = db.session.query(
                db.func.coalesce(db.func.sum(ProductionItem.volume_m3), 0)
            ).filter(
                ProductionItem.cutting_completed_at >= today_start,
                ProductionItem.cutting_completed_at <= today_end
            ).scalar() or 0.0

            assembly_m3_today = db.session.query(
                db.func.coalesce(db.func.sum(ProductionItem.volume_m3), 0)
            ).filter(
                ProductionItem.assembly_completed_at >= today_start,
                ProductionItem.assembly_completed_at <= today_end
            ).scalar() or 0.0

            try:
                gluing_m3_today = db.session.query(
                    db.func.coalesce(db.func.sum(ProductionItem.volume_m3), 0)
                ).filter(
                    ProductionItem.gluing_completed_at >= today_start,
                    ProductionItem.gluing_completed_at <= today_end
                ).scalar() or 0.0
            except AttributeError:
                gluing_m3_today = 0.0

            try:
                formatting_m3_today = db.session.query(
                    db.func.coalesce(db.func.sum(ProductionItem.volume_m3), 0)
                ).filter(
                    ProductionItem.formatting_completed_at >= today_start,
                    ProductionItem.formatting_completed_at <= today_end
                ).scalar() or 0.0
            except AttributeError:
                formatting_m3_today = 0.0

            try:
                finishing_m3_today = db.session.query(
                    db.func.coalesce(db.func.sum(ProductionItem.volume_m3), 0)
                ).filter(
                    ProductionItem.finishing_completed_at >= today_start,
                    ProductionItem.finishing_completed_at <= today_end
                ).scalar() or 0.0
            except AttributeError:
                finishing_m3_today = 0.0

            packaging_m3_today = db.session.query(
                db.func.coalesce(db.func.sum(ProductionItem.volume_m3), 0)
            ).filter(
                ProductionItem.packaging_completed_at >= today_start,
                ProductionItem.packaging_completed_at <= today_end
            ).scalar() or 0.0

        except Exception as volume_error:
            logger.warning("Nie udało się pobrać volume_m3 dla stacji", extra={'error': str(volume_error)})

        dashboard_stats['stations'] = {
            'cutting': {
                'pending_count': cutting_count,
                'today_m3': float(cutting_m3_today),
                'status': 'active' if cutting_count > 0 else 'idle',
                'status_class': 'station-active' if cutting_count > 0 else 'station-idle'
            },
            'assembly': {
                'pending_count': assembly_count,
                'today_m3': float(assembly_m3_today),
                'status': 'active' if assembly_count > 0 else 'idle',
                'status_class': 'station-active' if assembly_count > 0 else 'station-idle'
            },
            'gluing': {
                'pending_count': gluing_count,
                'today_m3': float(gluing_m3_today),
                'status': 'active' if gluing_count > 0 else 'idle',
                'status_class': 'station-active' if gluing_count > 0 else 'station-idle'
            },
            'formatting': {
                'pending_count': formatting_count,
                'today_m3': float(formatting_m3_today),
                'status': 'active' if formatting_count > 0 else 'idle',
                'status_class': 'station-active' if formatting_count > 0 else 'station-idle'
            },
            'finishing': {
                'pending_count': finishing_count,
                'today_m3': float(finishing_m3_today),
                'status': 'active' if finishing_count > 0 else 'idle',
                'status_class': 'station-active' if finishing_count > 0 else 'station-idle'
            },
            'packaging': {
                'pending_count': packaging_count,
                'today_m3': float(packaging_m3_today),
                'status': 'active' if packaging_count > 0 else 'idle',
                'status_class': 'station-active' if packaging_count > 0 else 'station-idle'
            }
        }

        # Heartbeat status per station
        from modules.production.services.station_heartbeat import get_all_statuses
        heartbeat_statuses = get_all_statuses()

        for st_code in ['cutting', 'assembly', 'gluing', 'formatting', 'finishing', 'packaging']:
            dashboard_stats['stations'][st_code]['tablet_status'] = heartbeat_statuses.get(st_code, {'active': False, 'last_seen': None, 'status_label': 'Niedostępne'})

        # completed_today and pending_m3 per station
        cutting_completed_today = ProductionItem.query.filter(
            ProductionItem.cutting_completed_at >= today_start,
            ProductionItem.cutting_completed_at <= today_end
        ).count()
        cutting_pending_m3 = db.session.query(
            db.func.coalesce(db.func.sum(ProductionItem.volume_m3), 0)
        ).filter(
            ProductionItem.current_status == 'czeka_na_wyciecie'
        ).scalar() or 0.0
        dashboard_stats['stations']['cutting']['completed_today'] = cutting_completed_today
        dashboard_stats['stations']['cutting']['pending_m3'] = float(cutting_pending_m3)

        assembly_completed_today = ProductionItem.query.filter(
            ProductionItem.assembly_completed_at >= today_start,
            ProductionItem.assembly_completed_at <= today_end
        ).count()
        assembly_pending_m3 = db.session.query(
            db.func.coalesce(db.func.sum(ProductionItem.volume_m3), 0)
        ).filter(
            ProductionItem.current_status == 'czeka_na_skladanie'
        ).scalar() or 0.0
        dashboard_stats['stations']['assembly']['completed_today'] = assembly_completed_today
        dashboard_stats['stations']['assembly']['pending_m3'] = float(assembly_pending_m3)

        gluing_completed_today = 0
        gluing_pending_m3 = 0.0
        try:
            gluing_completed_today = ProductionItem.query.filter(
                ProductionItem.gluing_completed_at >= today_start,
                ProductionItem.gluing_completed_at <= today_end
            ).count()
            gluing_pending_m3 = db.session.query(
                db.func.coalesce(db.func.sum(ProductionItem.volume_m3), 0)
            ).filter(
                ProductionItem.current_status == 'czeka_na_sklejanie'
            ).scalar() or 0.0
        except AttributeError:
            pass
        dashboard_stats['stations']['gluing']['completed_today'] = gluing_completed_today
        dashboard_stats['stations']['gluing']['pending_m3'] = float(gluing_pending_m3)

        formatting_completed_today = 0
        formatting_pending_m3 = 0.0
        try:
            formatting_completed_today = ProductionItem.query.filter(
                ProductionItem.formatting_completed_at >= today_start,
                ProductionItem.formatting_completed_at <= today_end
            ).count()
            formatting_pending_m3 = db.session.query(
                db.func.coalesce(db.func.sum(ProductionItem.volume_m3), 0)
            ).filter(
                ProductionItem.current_status == 'czeka_na_formatowanie'
            ).scalar() or 0.0
        except AttributeError:
            pass
        dashboard_stats['stations']['formatting']['completed_today'] = formatting_completed_today
        dashboard_stats['stations']['formatting']['pending_m3'] = float(formatting_pending_m3)

        finishing_completed_today = 0
        finishing_pending_m3 = 0.0
        try:
            finishing_completed_today = ProductionItem.query.filter(
                ProductionItem.finishing_completed_at >= today_start,
                ProductionItem.finishing_completed_at <= today_end
            ).count()
            finishing_pending_m3 = db.session.query(
                db.func.coalesce(db.func.sum(ProductionItem.volume_m3), 0)
            ).filter(
                ProductionItem.current_status == 'czeka_na_wykanczanie'
            ).scalar() or 0.0
        except AttributeError:
            pass
        dashboard_stats['stations']['finishing']['completed_today'] = finishing_completed_today
        dashboard_stats['stations']['finishing']['pending_m3'] = float(finishing_pending_m3)

        packaging_completed_today = ProductionItem.query.filter(
            ProductionItem.packaging_completed_at >= today_start,
            ProductionItem.packaging_completed_at <= today_end
        ).count()
        packaging_pending_m3 = db.session.query(
            db.func.coalesce(db.func.sum(ProductionItem.volume_m3), 0)
        ).filter(
            ProductionItem.current_status == 'czeka_na_pakowanie'
        ).scalar() or 0.0
        dashboard_stats['stations']['packaging']['completed_today'] = packaging_completed_today
        dashboard_stats['stations']['packaging']['pending_m3'] = float(packaging_pending_m3)

        logistics_pending = ProductionItem.query.filter(
            ProductionItem.current_status == 'czeka_na_logistyke'
        ).count()
        dashboard_stats['logistics'] = {
            'pending_count': logistics_pending
        }

        # Dzisiejsze sumy
        today_start = datetime.combine(today, datetime.min.time())
        today_end = datetime.combine(today, datetime.max.time())

        completed_orders_today = db.session.query(
            db.func.count(db.func.distinct(ProductionItem.internal_order_number))
        ).filter(
            ProductionItem.current_status == 'spakowane',
            ProductionItem.packaging_completed_at >= today_start,
            ProductionItem.packaging_completed_at <= today_end
        ).scalar() or 0

        total_m3_today = 0.0
        try:
            total_m3_today = db.session.query(
                db.func.coalesce(db.func.sum(ProductionItem.volume_m3), 0)
            ).filter(
                ProductionItem.current_status == 'spakowane',
                ProductionItem.packaging_completed_at >= today_start,
                ProductionItem.packaging_completed_at <= today_end
            ).scalar() or 0.0
        except:
            total_m3_today = 0.0

        avg_deadline_distance = 0.0
        try:
            active_products = ProductionItem.query.filter(
                ProductionItem.current_status.in_([
                    'czeka_na_wyciecie', 'czeka_na_skladanie', 'czeka_na_sklejanie',
                    'czeka_na_formatowanie', 'czeka_na_wykanczanie', 'czeka_na_pakowanie',
                    'w_realizacji'
                ]),
                ProductionItem.deadline_date.isnot(None)
            ).all()

            if active_products:
                total_days = sum(
                    (product.deadline_date.date() - today).days
                    for product in active_products
                )
                avg_deadline_distance = total_days / len(active_products)
        except Exception as e:
            print(f"[Dashboard] Błąd obliczania średniego deadline: {e}")
            avg_deadline_distance = 0.0

        dashboard_stats['today_totals'] = {
            'completed_orders': completed_orders_today,
            'total_m3': float(total_m3_today),
            'avg_deadline_distance': round(avg_deadline_distance, 1),
            'total_orders': ProductionItem.query.count()
        }

        active_statuses = [
            'czeka_na_wyciecie', 'czeka_na_skladanie', 'czeka_na_sklejanie',
            'czeka_na_formatowanie', 'czeka_na_wykanczanie', 'czeka_na_pakowanie',
            'w_realizacji'
        ]
        in_production_items = ProductionItem.query.filter(
            ProductionItem.current_status.in_(active_statuses)
        ).all()

        in_production_order_ids = set(
            item.baselinker_order_id for item in in_production_items
            if item.baselinker_order_id
        )

        dashboard_stats['in_production'] = {
            'orders': len(in_production_order_ids),
            'products': len(in_production_items),
            'm3': round(sum(float(item.volume_m3 or 0) for item in in_production_items), 2)
        }

        deadline_items = ProductionItem.query.filter(
            ProductionItem.deadline_date <= (today + timedelta(days=3)),
            ProductionItem.current_status != 'spakowane'
        ).order_by(ProductionItem.deadline_date.asc()).all()

        # Group by order (baselinker_order_id)
        orders_map = {}
        for item in deadline_items:
            oid = item.baselinker_order_id or item.short_product_id
            if oid not in orders_map:
                orders_map[oid] = {
                    'baselinker_order_id': item.baselinker_order_id,
                    'client_name': item.client_name or 'Brak danych',
                    'deadline_date': item.deadline_date,
                    'deadline_date_formatted': item.deadline_date.strftime('%d.%m.%Y') if item.deadline_date else '',
                    'days_remaining': (item.deadline_date - today).days if item.deadline_date else 0,
                    'products_count': 0,
                }
            orders_map[oid]['products_count'] += 1
            # Use earliest deadline for the order
            if item.deadline_date and (orders_map[oid]['deadline_date'] is None or item.deadline_date < orders_map[oid]['deadline_date']):
                orders_map[oid]['deadline_date'] = item.deadline_date
                orders_map[oid]['deadline_date_formatted'] = item.deadline_date.strftime('%d.%m.%Y')
                orders_map[oid]['days_remaining'] = (item.deadline_date - today).days

        dashboard_stats['deadline_alerts'] = sorted(orders_map.values(), key=lambda x: x.get('days_remaining', 0))

        errors_24h = ProductionError.query.filter(
            ProductionError.error_occurred_at >= (get_local_now() - timedelta(hours=24)),
            ProductionError.is_resolved == False
        ).count()

        last_sync = ProductionSyncLog.query.order_by(ProductionSyncLog.sync_started_at.desc()).first()

        dashboard_stats['system_health'] = {
            'last_sync': last_sync.sync_started_at.isoformat() if last_sync else None,
            'sync_status': 'success' if last_sync and last_sync.sync_status == 'completed' else 'warning',
            'errors_24h': errors_24h,
            'database_status': 'connected'
        }

        rendered_html = render_template(
            'components/dashboard-tab-content.html',
            dashboard_stats=dashboard_stats
        )

        return jsonify({
            'success': True,
            'html': rendered_html,
            'initial_data': dashboard_stats,
            'last_updated': get_local_now().isoformat()
        })

    except Exception as e:
        logger.error("Błąd AJAX dashboard-tab-content", extra={
            'user_id': current_user.id,
            'error': str(e),
            'initial_load': initial_load if 'initial_load' in locals() else 'unknown'
        })

        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


# ============================================================================
# DASHBOARD DATA (JSON only, no HTML)
# ============================================================================

@api_bp.route('/dashboard-data', methods=['GET'])
@login_required
def dashboard_data():
    """
    Zwraca TYLKO dane dla dashboard (bez HTML)
    Używane do odświeżania danych bez przeładowywania template
    """
    try:
        logger.info("API: dashboard-data - pobieranie danych", extra={
            'user_id': current_user.id,
            'user_role': getattr(current_user, 'role', 'unknown')
        })

        from ...models import ProductionItem, ProductionError
        from modules.production.services.station_heartbeat import get_all_statuses as _get_all_heartbeat_statuses

        heartbeat_statuses = _get_all_heartbeat_statuses()

        stations_data = []

        today_dd = date.today()
        today_start_dd = datetime.combine(today_dd, datetime.min.time())
        today_end_dd = datetime.combine(today_dd, datetime.max.time())

        # Stacja wycinania
        cutting_count = ProductionItem.query.filter(
            ProductionItem.current_status == 'czeka_na_wyciecie'
        ).count()
        cutting_completed_today_dd = ProductionItem.query.filter(
            ProductionItem.cutting_completed_at >= today_start_dd,
            ProductionItem.cutting_completed_at <= today_end_dd
        ).count()
        cutting_pending_m3_dd = db.session.query(
            db.func.coalesce(db.func.sum(ProductionItem.volume_m3), 0)
        ).filter(
            ProductionItem.current_status == 'czeka_na_wyciecie'
        ).scalar() or 0.0

        stations_data.append({
            'code': 'cutting',
            'name': 'Wycinanie',
            'status': 'active' if cutting_count > 0 else 'idle',
            'status_class': 'station-active' if cutting_count > 0 else 'station-idle',
            'active_orders': cutting_count,
            'completed_today': cutting_completed_today_dd,
            'pending_m3': float(cutting_pending_m3_dd),
            'tablet_status': heartbeat_statuses.get('cutting', {'active': False, 'last_seen': None, 'status_label': 'Niedostępne'})
        })

        # Stacja składania
        assembly_count = ProductionItem.query.filter(
            ProductionItem.current_status == 'czeka_na_skladanie'
        ).count()
        assembly_completed_today_dd = ProductionItem.query.filter(
            ProductionItem.assembly_completed_at >= today_start_dd,
            ProductionItem.assembly_completed_at <= today_end_dd
        ).count()
        assembly_pending_m3_dd = db.session.query(
            db.func.coalesce(db.func.sum(ProductionItem.volume_m3), 0)
        ).filter(
            ProductionItem.current_status == 'czeka_na_skladanie'
        ).scalar() or 0.0

        stations_data.append({
            'code': 'assembly',
            'name': 'Składanie',
            'status': 'active' if assembly_count > 0 else 'idle',
            'status_class': 'station-active' if assembly_count > 0 else 'station-idle',
            'active_orders': assembly_count,
            'completed_today': assembly_completed_today_dd,
            'pending_m3': float(assembly_pending_m3_dd),
            'tablet_status': heartbeat_statuses.get('assembly', {'active': False, 'last_seen': None, 'status_label': 'Niedostępne'})
        })

        # Stacja sklejania
        gluing_count = ProductionItem.query.filter(
            ProductionItem.current_status == 'czeka_na_sklejanie'
        ).count()
        gluing_completed_today_dd = 0
        gluing_pending_m3_dd = 0.0
        try:
            gluing_completed_today_dd = ProductionItem.query.filter(
                ProductionItem.gluing_completed_at >= today_start_dd,
                ProductionItem.gluing_completed_at <= today_end_dd
            ).count()
            gluing_pending_m3_dd = db.session.query(
                db.func.coalesce(db.func.sum(ProductionItem.volume_m3), 0)
            ).filter(
                ProductionItem.current_status == 'czeka_na_sklejanie'
            ).scalar() or 0.0
        except AttributeError:
            pass

        stations_data.append({
            'code': 'gluing',
            'name': 'Sklejanie',
            'status': 'active' if gluing_count > 0 else 'idle',
            'status_class': 'station-active' if gluing_count > 0 else 'station-idle',
            'active_orders': gluing_count,
            'completed_today': gluing_completed_today_dd,
            'pending_m3': float(gluing_pending_m3_dd),
            'tablet_status': heartbeat_statuses.get('gluing', {'active': False, 'last_seen': None, 'status_label': 'Niedostępne'})
        })

        # Stacja formatowania
        formatting_count = ProductionItem.query.filter(
            ProductionItem.current_status == 'czeka_na_formatowanie'
        ).count()
        formatting_completed_today_dd = 0
        formatting_pending_m3_dd = 0.0
        try:
            formatting_completed_today_dd = ProductionItem.query.filter(
                ProductionItem.formatting_completed_at >= today_start_dd,
                ProductionItem.formatting_completed_at <= today_end_dd
            ).count()
            formatting_pending_m3_dd = db.session.query(
                db.func.coalesce(db.func.sum(ProductionItem.volume_m3), 0)
            ).filter(
                ProductionItem.current_status == 'czeka_na_formatowanie'
            ).scalar() or 0.0
        except AttributeError:
            pass

        stations_data.append({
            'code': 'formatting',
            'name': 'Formatowanie',
            'status': 'active' if formatting_count > 0 else 'idle',
            'status_class': 'station-active' if formatting_count > 0 else 'station-idle',
            'active_orders': formatting_count,
            'completed_today': formatting_completed_today_dd,
            'pending_m3': float(formatting_pending_m3_dd),
            'tablet_status': heartbeat_statuses.get('formatting', {'active': False, 'last_seen': None, 'status_label': 'Niedostępne'})
        })

        # Stacja wykańczania
        finishing_count = ProductionItem.query.filter(
            ProductionItem.current_status == 'czeka_na_wykanczanie'
        ).count()
        finishing_completed_today_dd = 0
        finishing_pending_m3_dd = 0.0
        try:
            finishing_completed_today_dd = ProductionItem.query.filter(
                ProductionItem.finishing_completed_at >= today_start_dd,
                ProductionItem.finishing_completed_at <= today_end_dd
            ).count()
            finishing_pending_m3_dd = db.session.query(
                db.func.coalesce(db.func.sum(ProductionItem.volume_m3), 0)
            ).filter(
                ProductionItem.current_status == 'czeka_na_wykanczanie'
            ).scalar() or 0.0
        except AttributeError:
            pass

        stations_data.append({
            'code': 'finishing',
            'name': 'Wykańczanie',
            'status': 'active' if finishing_count > 0 else 'idle',
            'status_class': 'station-active' if finishing_count > 0 else 'station-idle',
            'active_orders': finishing_count,
            'completed_today': finishing_completed_today_dd,
            'pending_m3': float(finishing_pending_m3_dd),
            'tablet_status': heartbeat_statuses.get('finishing', {'active': False, 'last_seen': None, 'status_label': 'Niedostępne'})
        })

        # Stacja pakowania
        packaging_count = ProductionItem.query.filter(
            ProductionItem.current_status == 'czeka_na_pakowanie'
        ).count()
        packaging_completed_today_dd = ProductionItem.query.filter(
            ProductionItem.packaging_completed_at >= today_start_dd,
            ProductionItem.packaging_completed_at <= today_end_dd
        ).count()
        packaging_pending_m3_dd = db.session.query(
            db.func.coalesce(db.func.sum(ProductionItem.volume_m3), 0)
        ).filter(
            ProductionItem.current_status == 'czeka_na_pakowanie'
        ).scalar() or 0.0

        stations_data.append({
            'code': 'packaging',
            'name': 'Pakowanie',
            'status': 'active' if packaging_count > 0 else 'idle',
            'status_class': 'station-active' if packaging_count > 0 else 'station-idle',
            'active_orders': packaging_count,
            'completed_today': packaging_completed_today_dd,
            'pending_m3': float(packaging_pending_m3_dd),
            'tablet_status': heartbeat_statuses.get('packaging', {'active': False, 'last_seen': None, 'status_label': 'Niedostępne'})
        })

        # Alerty systemowe
        alerts_data = []

        errors_24h = ProductionError.query.filter(
            ProductionError.error_occurred_at >= (get_local_now() - timedelta(hours=24)),
            ProductionError.is_resolved == False
        ).count()

        if errors_24h > 0:
            alerts_data.append({
                'type': 'error',
                'icon': 'exclamation-triangle',
                'message': f'Znaleziono {errors_24h} błędów systemowych',
                'time': 'ostatnie 24h'
            })

        today = date.today()
        deadline_items = ProductionItem.query.filter(
            ProductionItem.deadline_date <= (today + timedelta(days=3)),
            ProductionItem.current_status != 'spakowane'
        ).order_by(ProductionItem.deadline_date.asc()).all()

        # Group by order (baselinker_order_id)
        orders_map = {}
        for item in deadline_items:
            oid = item.baselinker_order_id or item.short_product_id
            if oid not in orders_map:
                orders_map[oid] = {
                    'baselinker_order_id': item.baselinker_order_id,
                    'client_name': item.client_name or 'Brak danych',
                    'deadline_date': item.deadline_date.isoformat() if item.deadline_date else None,
                    'deadline_date_formatted': item.deadline_date.strftime('%d.%m.%Y') if item.deadline_date else '',
                    'days_remaining': (item.deadline_date - today).days if item.deadline_date else 0,
                    'products_count': 0,
                }
            orders_map[oid]['products_count'] += 1
            # Use earliest deadline for the order
            if item.deadline_date and item.deadline_date.isoformat() < (orders_map[oid]['deadline_date'] or '9999'):
                orders_map[oid]['deadline_date'] = item.deadline_date.isoformat()
                orders_map[oid]['deadline_date_formatted'] = item.deadline_date.strftime('%d.%m.%Y')
                orders_map[oid]['days_remaining'] = (item.deadline_date - today).days

        alerts_data = sorted(orders_map.values(), key=lambda x: x.get('days_remaining', 0))

        in_production_active_statuses = [
            'czeka_na_wyciecie', 'czeka_na_skladanie', 'czeka_na_sklejanie',
            'czeka_na_formatowanie', 'czeka_na_wykanczanie', 'czeka_na_pakowanie',
            'w_realizacji'
        ]
        in_production_items_dd = ProductionItem.query.filter(
            ProductionItem.current_status.in_(in_production_active_statuses)
        ).all()

        in_production_order_ids_dd = set(
            item.baselinker_order_id for item in in_production_items_dd
            if item.baselinker_order_id
        )

        in_production_stats = {
            'orders': len(in_production_order_ids_dd),
            'products': len(in_production_items_dd),
            'm3': round(sum(float(item.volume_m3 or 0) for item in in_production_items_dd), 2)
        }

        response_data = {
            'stations': stations_data,
            'alerts': alerts_data,
            'in_production': in_production_stats,
            'errors_count': errors_24h,
            'timestamp': get_local_now().isoformat()
        }

        logger.debug("API: dashboard-data - dane pobrane", extra={
            'stations_count': len(stations_data),
            'alerts_count': len(alerts_data),
            'errors_24h': errors_24h
        })

        return jsonify({
            'success': True,
            'data': response_data
        })

    except Exception as e:
        logger.error("API: Błąd dashboard-data", extra={
            'user_id': current_user.id,
            'error': str(e),
            'traceback': traceback.format_exc()
        })

        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


# ============================================================================
# PRODUCTION STATUS DATA
# ============================================================================

@api_bp.route('/production-status-data', methods=['GET'])
@login_required
def production_status_data():
    """
    Zwraca TYLKO status produkcji (bez HTML)
    Używane do odświeżania wskaźnika statusu w header dashboard
    """
    try:
        logger.info("API: production-status-data - pobieranie statusu", extra={
            'user_id': current_user.id,
            'user_role': getattr(current_user, 'role', 'unknown')
        })

        from ...models import ProductionItem, ProductionSyncLog

        active_orders = ProductionItem.query.filter(
            ProductionItem.current_status.in_([
                'czeka_na_wyciecie',
                'czeka_na_skladanie',
                'czeka_na_pakowanie'
            ])
        ).count()

        last_sync = ProductionSyncLog.query.order_by(
            ProductionSyncLog.sync_started_at.desc()
        ).first()

        if active_orders > 0:
            status = 'active'
            status_text = f'Produkcja aktywna ({active_orders} zamówień)'
            indicator_class = 'status-active'
        else:
            status = 'idle'
            status_text = 'Produkcja w trybie oczekiwania'
            indicator_class = 'status-idle'

        sync_age_hours = None
        if last_sync:
            sync_age_hours = (get_local_now() - last_sync.sync_started_at).total_seconds() / 3600
            if sync_age_hours > 2:
                status = 'warning'
                status_text = 'Problemy z synchronizacją'
                indicator_class = 'status-warning'

        response_data = {
            'status': status,
            'status_text': status_text,
            'indicator_class': indicator_class,
            'active_orders': active_orders,
            'last_sync': last_sync.sync_started_at.isoformat() if last_sync else None,
            'last_update': get_local_now().isoformat()
        }

        logger.debug("API: production-status-data - status określony", extra={
            'status': status,
            'active_orders': active_orders,
            'last_sync_age_hours': sync_age_hours if last_sync else None
        })

        return jsonify({
            'success': True,
            'data': response_data
        })

    except Exception as e:
        logger.error("API: Błąd production-status-data", extra={
            'user_id': current_user.id,
            'error': str(e),
            'traceback': traceback.format_exc()
        })

        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


# ============================================================================
# DASHBOARD STATS DATA (numbers only)
# ============================================================================

@api_bp.route('/dashboard-stats-data', methods=['GET'])
@login_required
def dashboard_stats_data():
    """
    Zwraca TYLKO statystyki liczbowe dla dashboard (bez HTML)
    Używane do odświeżania widgetów z liczbami
    """
    try:
        logger.info("API: dashboard-stats-data - pobieranie statystyk", extra={
            'user_id': current_user.id,
            'user_role': getattr(current_user, 'role', 'unknown')
        })

        from ...models import ProductionItem, ProductionError

        today = date.today()
        today_start = datetime.combine(today, datetime.min.time())
        today_end = datetime.combine(today, datetime.max.time())

        all_statuses = db.session.query(
            ProductionItem.current_status,
            db.func.count(ProductionItem.id)
        ).group_by(ProductionItem.current_status).all()

        logger.debug(f"Wszystkie statusy w bazie: {all_statuses}")

        try:
            test_packaging = ProductionItem.query.filter(
                ProductionItem.packaging_completed_at.isnot(None)
            ).limit(5).all()
            logger.debug(f"Znaleziono {len(test_packaging)} rekordów z packaging_completed_at")

            for item in test_packaging:
                logger.debug(f"Item {item.id}: packaging_completed_at={item.packaging_completed_at}")
        except Exception as e:
            logger.debug(f"Błąd packaging_completed_at: {e}")

        try:
            spakowane_items = ProductionItem.query.filter(
                ProductionItem.current_status == 'spakowane'
            ).limit(5).all()
            logger.debug(f"Znaleziono {len(spakowane_items)} rekordów ze statusem 'spakowane'")

            for item in spakowane_items:
                created_at = getattr(item, 'created_at', None)
                updated_at = getattr(item, 'updated_at', None)
                packaging_completed_at = getattr(item, 'packaging_completed_at', None)

                logger.debug(f"Item {item.id}: status={item.current_status}, created_at={created_at}, updated_at={updated_at}, packaging_completed_at={packaging_completed_at}")
        except Exception as e:
            logger.debug(f"Błąd sprawdzania statusów: {e}")

        total_orders = ProductionItem.query.count()

        completed_today_original = ProductionItem.query.filter(
            ProductionItem.current_status == 'spakowane',
            ProductionItem.packaging_completed_at >= today_start,
            ProductionItem.packaging_completed_at <= today_end
        ).count()

        completed_today_alternative = ProductionItem.query.filter(
            ProductionItem.current_status == 'spakowane'
        ).count()

        completed_today_updated_at = 0
        try:
            completed_today_updated_at = ProductionItem.query.filter(
                ProductionItem.current_status == 'spakowane',
                ProductionItem.updated_at >= today_start,
                ProductionItem.updated_at <= today_end
            ).count()
        except Exception as e:
            logger.debug(f"Błąd updated_at: {e}")

        logger.debug(f"Completed today (oryginalna logika): {completed_today_original}")
        logger.debug(f"Completed today (wszystkie spakowane): {completed_today_alternative}")
        logger.debug(f"Completed today (updated_at): {completed_today_updated_at}")
        logger.debug(f"Today start: {today_start}, Today end: {today_end}")

        if completed_today_original == 0 and completed_today_alternative > 0:
            logger.warning("Używam alternatywnej logiki - brak packaging_completed_at lub problem z datami")
            completed_today = completed_today_updated_at if completed_today_updated_at > 0 else completed_today_alternative
        else:
            completed_today = completed_today_original

        pending_priority = ProductionItem.query.filter(
            ProductionItem.current_status.in_([
                'czeka_na_wyciecie',
                'czeka_na_skladanie',
                'czeka_na_pakowanie'
            ])
        ).filter(
            ProductionItem.deadline_date <= (today + timedelta(days=3))
        ).count()

        errors_24h = ProductionError.query.filter(
            ProductionError.error_occurred_at >= (get_local_now() - timedelta(hours=24)),
            ProductionError.is_resolved == False
        ).count()

        total_volume_today = 0.0
        try:
            if completed_today_original > 0:
                volume_result = db.session.query(
                    db.func.coalesce(db.func.sum(ProductionItem.volume_m3), 0)
                ).filter(
                    ProductionItem.current_status == 'spakowane',
                    ProductionItem.packaging_completed_at >= today_start,
                    ProductionItem.packaging_completed_at <= today_end
                ).scalar()
            else:
                volume_result = db.session.query(
                    db.func.coalesce(db.func.sum(ProductionItem.volume_m3), 0)
                ).filter(
                    ProductionItem.current_status == 'spakowane'
                ).scalar()

            total_volume_today = float(volume_result) if volume_result else 0.0

        except Exception as volume_error:
            logger.warning("Nie udało się pobrać volume_m3", extra={'error': str(volume_error)})
            total_volume_today = 0.0

        stats_data = {
            'total_orders': total_orders,
            'completed_today': completed_today,
            'pending_priority': pending_priority,
            'errors_24h': errors_24h,
            'total_volume_today_m3': total_volume_today,
            'completion_rate_today': round((completed_today / max(total_orders, 1)) * 100, 1),
            'last_updated': get_local_now().isoformat()
        }

        logger.debug("API: dashboard-stats-data - FINALNE statystyki", extra={
            'total_orders': total_orders,
            'completed_today': completed_today,
            'completed_today_original': completed_today_original,
            'completed_today_alternative': completed_today_alternative,
            'completed_today_updated_at': completed_today_updated_at,
            'pending_priority': pending_priority,
            'errors_24h': errors_24h,
            'total_volume_today': total_volume_today
        })

        return jsonify({
            'success': True,
            'data': stats_data
        })

    except Exception as e:
        logger.error("API: Błąd dashboard-stats-data", extra={
            'user_id': current_user.id,
            'error': str(e),
            'traceback': traceback.format_exc()
        })

        return jsonify({
            'success': False,
            'error': str(e)
        }), 500
