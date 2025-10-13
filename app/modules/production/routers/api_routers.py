# modules/production/routers/api_routers.py
"""
API Routers dla modułu Production
=================================

REST API endpoints zgodne z PRD Section 6:
- GET /api/dashboard-stats → statystyki dla dashboard
- POST /api/complete-task → oznaczenie zadania jako wykonane
- POST /api/cron-sync → endpoint synchronizacji CRON
- POST /api/manual-sync → trigger ręcznej synchronizacji
- POST /api/update-config → aktualizacja konfiguracji
- GET /api/health → health check
- POST /api/complete-packaging → ukończenie pakowania z Baselinker update

Zwraca JSON responses z odpowiednimi kodami HTTP.
Autoryzacja zależna od endpointu.

Autor: Konrad Kmiecik
Wersja: 1.0 (Podstawowa zgodnie z PRD)
Data: 2025-01-09
"""

import json
from datetime import datetime, date, timedelta
from flask import Blueprint, request, jsonify, current_app, render_template, render_template_string
from flask_login import login_required, current_user
from functools import wraps
from modules.logging import get_structured_logger
from typing import Dict, Any
from extensions import db
from sqlalchemy import and_, or_, text, func, distinct
import traceback
import pytz

# Utworzenie Blueprint dla API
api_bp = Blueprint('production_api', __name__)
logger = get_structured_logger('production.api')

# Import modeli produkcji
try:
    from ..models import ProductionItem, ProductionError, ProductionSyncLog, ProductionConfig, ProductionPriorityConfig
except ImportError:
    from modules.production.models import ProductionItem, ProductionError, ProductionSyncLog, ProductionConfig, ProductionPriorityConfig

# ============================================================================
# DECORATORS - zabezpieczenia dla różnych typów endpointów
# ============================================================================

def get_local_now():
    """
    Zwraca aktualny czas w strefie czasowej Polski
    Zastępuje datetime.utcnow() dla poprawnego wyświetlania czasu
    """
    poland_tz = pytz.timezone('Europe/Warsaw')
    return datetime.now(poland_tz).replace(tzinfo=None)  # Remove timezone info for MySQL compatibility

def admin_required(f):
    """
    Dekorator dla endpointów wymagających roli admin
    Używany dla: manual-sync, update-config, priority management (NOWE)
    """
    @wraps(f)
    @login_required
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return jsonify({'success': False, 'error': 'Wymagana autoryzacja'}), 401
        
        if not hasattr(current_user, 'role') or current_user.role.lower() not in ['admin', 'administrator']:
            logger.warning("API: Odmowa dostępu admin", extra={
                'user_id': current_user.id,
                'endpoint': request.endpoint,
                'client_ip': request.remote_addr
            })
            return jsonify({'success': False, 'error': 'Brak uprawnień administratora'}), 403
        
        return f(*args, **kwargs)
    return decorated_function

def cron_secret_required(f):
    """
    Dekorator dla endpointów CRON wymagających sekretu
    Używany dla: cron-sync
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        cron_secret = request.headers.get('X-Cron-Secret')
        
        # Pobierz secret z konfiguracji
        expected_secret = current_app.config.get('PRODUCTION_CRON_SECRET', 'prod_sync_secret_key_2025')
        
        if not cron_secret or cron_secret != expected_secret:
            logger.warning("CRON: Nieprawidłowy secret", extra={
                'provided_secret_length': len(cron_secret) if cron_secret else 0,
                'client_ip': request.remote_addr,
                'endpoint': request.endpoint
            })
            return jsonify({'success': False, 'error': 'Nieprawidłowy CRON secret'}), 403
        
        return f(*args, **kwargs)
    return decorated_function

def ip_validation_required(f):
    """
    Dekorator dla walidacji IP stanowisk
    Używany dla: complete-task, complete-packaging
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        try:
            from ..services.security_service import IPSecurityService
            
            client_ip = IPSecurityService.get_client_ip(request)
            
            if not IPSecurityService.is_ip_allowed(client_ip):
                logger.warning("IP validation failed", extra={
                    'client_ip': client_ip,
                    'endpoint': request.endpoint,
                    'user_agent': request.headers.get('User-Agent', 'Unknown')
                })
                return jsonify({'success': False, 'error': 'IP nie autoryzowany'}), 403
            
            logger.debug("IP validation success", extra={
                'client_ip': client_ip,
                'endpoint': request.endpoint
            })
            
        except Exception as e:
            logger.error("IP validation error", extra={
                'error': str(e),
                'client_ip': request.remote_addr,
                'endpoint': request.endpoint
            })
            return jsonify({'success': False, 'error': 'Błąd walidacji IP'}), 500
        
        return f(*args, **kwargs)
    return decorated_function

# ============================================================================
# API ROUTERS - PRD Section 6.1 (Dashboard)
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
        
        from ..models import ProductionItem
        from sqlalchemy import func, desc
        from datetime import datetime, timedelta
        
        # ============================================================================
        # PODSTAWOWE STATYSTYKI (istniejące)
        # ============================================================================
        
        # Statystyki per status
        status_stats = db.session.query(
            ProductionItem.current_status,
            func.count(ProductionItem.id).label('count'),
            func.avg(ProductionItem.priority_score).label('avg_priority')
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
        
        # ============================================================================
        # DODATKOWE STATYSTYKI (nowe)
        # ============================================================================
        
        # Produkty z wysokim priorytetem (>=150)
        high_priority_count = ProductionItem.query.filter(
            ProductionItem.priority_score >= 150
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
                desc(ProductionItem.priority_score),
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
                    'priority_score': product.priority_score or 0,
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
    
          
@api_bp.route('/chart-data')
@login_required
def chart_data():
    """
    AJAX endpoint dla danych wykresów wydajności dziennej (tylko admin)
    
    Query params:
        period: int - liczba dni do pobrania (7, 14, 30, 90, 180, 365)
        
    Returns:
        JSON: Dane wydajności per stanowisko i okres dla Chart.js
    """
    try:
        period = request.args.get('period', 7, type=int)
        
        # Walidacja okresu - ROZSZERZONA
        if period not in [7, 14, 30, 90, 180, 365]:
            return jsonify({
                'success': False,
                'error': 'Nieprawidłowy okres. Dozwolone: 7, 14, 30, 90, 180, 365 dni'
            }), 400
            
        logger.info(f"AJAX: Pobieranie danych wykresów dla {period} dni", extra={
            'user_id': current_user.id,
            'period': period
        })
        
        from ..models import ProductionItem
        from sqlalchemy import and_, func
        from datetime import datetime, timedelta, date
        
        # Oblicz zakres dat
        end_date = date.today()
        start_date = end_date - timedelta(days=period - 1)
        
        # Mapowanie statusów na stanowiska dla zakończonych zadań
        station_completion_mapping = {
            'cutting': 'cutting_completed_at',
            'assembly': 'assembly_completed_at', 
            'packaging': 'packaging_completed_at'
        }
        
        chart_data = {
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
                    'label': 'Pakowanie',
                    'data': [],
                    'borderColor': '#28a745',
                    'backgroundColor': 'rgba(40, 167, 69, 0.1)',
                    'tension': 0.4,
                    'fill': True
                }
            ]
        }
        
        # NOWE: Określ typ agregacji na podstawie okresu
        if period <= 30:
            aggregation_type = 'daily'
        elif period == 90:
            aggregation_type = 'weekly'
        else:  # 180, 365
            aggregation_type = 'monthly'
        
        # Pobierz dane wydajności dla każdego stanowiska
        daily_data = {}
        
        for station, completion_field in station_completion_mapping.items():
            completion_attr = getattr(ProductionItem, completion_field)
            
            # Zapytanie o sumę objętości per dzień dla stanowiska
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
            
            # Wypełnij dane dla stanowiska
            for completion_date, total_volume in daily_volumes:
                if completion_date not in daily_data:
                    daily_data[completion_date] = {
                        'cutting': 0.0,
                        'assembly': 0.0,
                        'packaging': 0.0
                    }
                daily_data[completion_date][station] = float(total_volume or 0)
        
        # NOWE: Agreguj dane według typu
        if aggregation_type == 'daily':
            # Agregacja dzienna (7, 14, 30 dni)
            current_date = start_date
            while current_date <= end_date:
                label = current_date.strftime('%Y-%m-%d')
                chart_data['labels'].append(label)
                
                if current_date not in daily_data:
                    daily_data[current_date] = {'cutting': 0.0, 'assembly': 0.0, 'packaging': 0.0}
                
                chart_data['datasets'][0]['data'].append(daily_data[current_date]['cutting'])
                chart_data['datasets'][1]['data'].append(daily_data[current_date]['assembly'])
                chart_data['datasets'][2]['data'].append(daily_data[current_date]['packaging'])
                current_date += timedelta(days=1)
                
        elif aggregation_type == 'weekly':
            # Agregacja tygodniowa (90 dni)
            from collections import defaultdict
            weekly_data = defaultdict(lambda: {'cutting': 0.0, 'assembly': 0.0, 'packaging': 0.0})
            
            # Grupuj dane dzienne po tygodniach
            for day_date, volumes in daily_data.items():
                # Oblicz początek tygodnia (poniedziałek)
                week_start = day_date - timedelta(days=day_date.weekday())
                for station in ['cutting', 'assembly', 'packaging']:
                    weekly_data[week_start][station] += volumes[station]
            
            # Generuj etykiety tygodniowe
            current_date = start_date - timedelta(days=start_date.weekday())
            while current_date <= end_date:
                week_label = current_date.strftime('%Y-%m-%d')
                chart_data['labels'].append(week_label)
                chart_data['datasets'][0]['data'].append(weekly_data[current_date]['cutting'])
                chart_data['datasets'][1]['data'].append(weekly_data[current_date]['assembly'])
                chart_data['datasets'][2]['data'].append(weekly_data[current_date]['packaging'])
                current_date += timedelta(weeks=1)
                
        elif aggregation_type == 'monthly':
            # Agregacja miesięczna (180, 365 dni)
            from collections import defaultdict
            monthly_data = defaultdict(lambda: {'cutting': 0.0, 'assembly': 0.0, 'packaging': 0.0})
            
            # Grupuj dane dzienne po miesiącach
            for day_date, volumes in daily_data.items():
                month_start = date(day_date.year, day_date.month, 1)
                for station in ['cutting', 'assembly', 'packaging']:
                    monthly_data[month_start][station] += volumes[station]
            
            # Generuj etykiety miesięczne
            current_month = date(start_date.year, start_date.month, 1)
            end_month = date(end_date.year, end_date.month, 1)
            
            while current_month <= end_month:
                month_label = current_month.strftime('%Y-%m-01')
                chart_data['labels'].append(month_label)
                chart_data['datasets'][0]['data'].append(monthly_data[current_month]['cutting'])
                chart_data['datasets'][1]['data'].append(monthly_data[current_month]['assembly'])
                chart_data['datasets'][2]['data'].append(monthly_data[current_month]['packaging'])
                
                # Przejdź do następnego miesiąca
                if current_month.month == 12:
                    current_month = date(current_month.year + 1, 1, 1)
                else:
                    current_month = date(current_month.year, current_month.month + 1, 1)
        
        # Oblicz statystyki podsumowujące
        total_volumes = {
            'cutting': sum(chart_data['datasets'][0]['data']),
            'assembly': sum(chart_data['datasets'][1]['data']),
            'packaging': sum(chart_data['datasets'][2]['data'])
        }
        
        # ZMIENIONE: avg per okres (nie tylko dzienny)
        num_periods = len(chart_data['labels']) if chart_data['labels'] else 1
        avg_per_period = {
            'cutting': total_volumes['cutting'] / num_periods,
            'assembly': total_volumes['assembly'] / num_periods,
            'packaging': total_volumes['packaging'] / num_periods
        }
        
        # Znajdź najlepszy okres
        best_period_idx = 0
        best_period_total = 0
        for i in range(len(chart_data['labels'])):
            period_total = (chart_data['datasets'][0]['data'][i] + 
                          chart_data['datasets'][1]['data'][i] + 
                          chart_data['datasets'][2]['data'][i])
            if period_total > best_period_total:
                best_period_total = period_total
                best_period_idx = i
        
        summary = {
            'period_days': period,
            'aggregation_type': aggregation_type,  # NOWE
            'total_volumes': total_volumes,
            'avg_per_period': {k: round(v, 2) for k, v in avg_per_period.items()},  # ZMIENIONE
            'best_period': {  # ZMIENIONE: z best_day
                'label': chart_data['labels'][best_period_idx] if chart_data['labels'] else None,
                'volume': round(best_period_total, 2)
            },
            'total_period_volume': round(sum(total_volumes.values()), 2)
        }
        
        response_data = {
            'success': True,
            'chart_data': chart_data,
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
            'aggregation': aggregation_type,  # NOWE
            'total_volume': summary['total_period_volume'],
            'data_points': len(chart_data['labels'])
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
# API ROUTERS - PRD Section 6.2 (Stanowiska)
# ============================================================================

@api_bp.route('/complete-task', methods=['POST'])
@ip_validation_required
def complete_task():
    """
    POST /api/complete-task - Oznaczenie zadania jako wykonane (PRD Section 6.2)
    
    Body JSON zgodny z PRD:
    {
        "product_id": "25_05248_1",
        "station_code": "cutting"
    }
    
    Akcje:
    1. Sprawdza czy produkt istnieje i ma odpowiedni status
    2. Oznacza zadanie jako ukończone w modelu
    3. Automatycznie zmienia status na następny w workflow
    4. Loguje operację
    
    Autoryzacja: Brak (walidacja IP)
    Returns: JSON status operacji
    """
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'Brak danych JSON'}), 400
        
        product_id = data.get('product_id')
        station_code = data.get('station_code')
        
        if not product_id or not station_code:
            return jsonify({
                'success': False, 
                'error': 'Wymagane pola: product_id, station_code'
            }), 400
        
        # Walidacja station_code
        valid_stations = ['cutting', 'assembly', 'packaging']
        if station_code not in valid_stations:
            return jsonify({
                'success': False,
                'error': f'Nieprawidłowy station_code. Dozwolone: {valid_stations}'
            }), 400
        
        logger.info("API: Próba ukończenia zadania", extra={
            'product_id': product_id,
            'station_code': station_code,
            'client_ip': request.remote_addr
        })
        
        from ..models import ProductionItem
        
        # Znajdź produkt
        product = ProductionItem.query.filter_by(short_product_id=product_id).first()
        if not product:
            return jsonify({
                'success': False,
                'error': f'Produkt {product_id} nie znaleziony'
            }), 404
        
        # Sprawdź czy produkt jest w odpowiednim statusie dla danego stanowiska
        expected_status_map = {
            'cutting': 'czeka_na_wyciecie',
            'assembly': 'czeka_na_skladanie', 
            'packaging': 'czeka_na_pakowanie'
        }
        
        expected_status = expected_status_map[station_code]
        if product.current_status != expected_status:
            return jsonify({
                'success': False,
                'error': f'Produkt ma status "{product.current_status}", oczekiwano "{expected_status}"'
            }), 400
        
        # Ukończ zadanie używając metody z modelu
        old_status = product.current_status
        product.complete_task(station_code)
        
        db.session.commit()
        
        logger.info("API: Ukończono zadanie", extra={
            'product_id': product_id,
            'station_code': station_code,
            'old_status': old_status,
            'new_status': product.current_status,
            'client_ip': request.remote_addr
        })
        
        return jsonify({
            'success': True,
            'message': f'Zadanie {station_code} dla produktu {product_id} ukończone',
            'data': {
                'product_id': product.short_product_id,
                'old_status': old_status,
                'new_status': product.current_status,
                'completed_at': get_local_now().isoformat()
            }
        }), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error("API: Błąd ukończenia zadania", extra={
            'product_id': data.get('product_id') if 'data' in locals() else None,
            'station_code': data.get('station_code') if 'data' in locals() else None,
            'client_ip': request.remote_addr,
            'error': str(e)
        })
        
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


# ============================================================================
# API ROUTERS - PRD Section 6.3 (CRON i Synchronizacja)
# ============================================================================

@api_bp.route('/sync-cron', methods=['GET'])
@cron_secret_required
def cron_sync():
    try:
        dry_run = request.args.get('dry_run', 'false').lower() == 'true'
        limit = int(request.args.get('limit', 100))
        
        logger.info("CRON: Rozpoczęcie synchronizacji", extra={
            'client_ip': request.remote_addr,
            'timestamp': get_local_now().isoformat(),
            'dry_run': dry_run,
            'limit': limit
        })
        
        from ..services.sync_service import get_sync_service
        
        sync_service = get_sync_service()
        
        if dry_run or limit < 100:
            sync_params = {
                'target_statuses': [155824],
                'period_days': 7,
                'limit_per_page': limit,
                'dry_run': dry_run,
                'force_update': False,
                'debug_mode': True,
                'skip_validation': False,
                'auto_status_change': not dry_run,
                'recalculate_priorities': not dry_run
            }
            sync_result = sync_service.manual_sync_with_filtering(sync_params)
            stats_section = sync_result.get('data', {}).get('stats', {})
            error_details = []
            orders_done = []
        else:
            sync_result = sync_service.sync_paid_orders_only()
            stats_section = sync_result
            error_details = sync_result.get('error_details', [])
            
            # ✅ DODAJ: Wyciągnij listę przetworzonych zamówień
            orders_done = sync_result.get('orders_processed_list', [])
        
        if sync_result and sync_result.get('success'):
            if dry_run or limit < 100:
                status_changes_count = 0
            else:
                status_changes_dict = sync_result.get('status_changes', {})
                status_changes_count = status_changes_dict.get('orders_moved_to_production', 0)
            
            logger.info("CRON: Synchronizacja zakończona pomyślnie", extra={
                'duration_seconds': sync_result.get('duration_seconds', 0),
                'products_created': stats_section.get('products_created', 0),
                'orders_processed': stats_section.get('orders_processed', 0),
                'dry_run': dry_run
            })
            
            return jsonify({
                'success': True,
                'trigger': 'cron',
                'mode': 'DRY_RUN' if dry_run else 'PRODUCTION',
                'timestamp': get_local_now().isoformat(),
                'summary': f'CRON synchronizacja zakończona pomyślnie ({"TEST MODE" if dry_run else "PRODUKCJA"})',
                'orders_done': orders_done,  # ✅ Lista order_id które przeszły
                'stats': {
                    'orders_processed': stats_section.get('orders_processed', 0),
                    'products_created': stats_section.get('products_created', 0),
                    'status_changes': status_changes_count,
                    'errors': stats_section.get('errors_count', 0)
                },
                'validation_errors': error_details,  # ✅ Pełna lista błędów
                'test_params': {
                    'dry_run': dry_run,
                    'limit': limit
                } if (dry_run or limit < 100) else None,
                'next_run': 'za 1 godzinę'
            }), 200
        else:
            error_msg = sync_result.get('error', 'Nieznany błąd') if sync_result else 'Brak odpowiedzi'
            
            logger.error("CRON: Synchronizacja zakończona błędem", extra={'error': error_msg})
            
            return jsonify({
                'success': False,
                'trigger': 'cron',
                'timestamp': get_local_now().isoformat(),
                'error': error_msg,
                'next_run': 'za 1 godzinę (retry)'
            }), 500
        
    except Exception as e:
        logger.error("CRON: Nieoczekiwany błąd synchronizacji", extra={
            'error': str(e),
            'client_ip': request.remote_addr
        })
        
        return jsonify({
            'success': False,
            'error': str(e),
            'timestamp': get_local_now().isoformat()
        }), 500

@api_bp.route('/sync/baselinker', methods=['POST'])
@login_required
def baselinker_manual_sync_modal():
    """Endpoint obsługujący manualną synchronizację z Baselinkerem z poziomu modalu."""

    try:
        payload = request.get_json() or {}

        logger.info(
            "API: Rozpoczęcie ręcznej synchronizacji Baselinker (modal)",
            extra={
                'user_id': getattr(current_user, 'id', None),
                'target_statuses': payload.get('target_statuses'),
                'period_days': payload.get('period_days'),
                'limit_per_page': payload.get('limit_per_page'),
                'dry_run': payload.get('dry_run', False),
                'force_update': payload.get('force_update', False)
            }
        )

        from ..services.sync_service import manual_sync_with_filtering as run_manual_sync_with_filtering

        result = run_manual_sync_with_filtering(payload)

        error_message = (result.get('error') or '').lower()
        status_code = 200 if result.get('success') else (500 if 'nieoczekiwany' in error_message else 400)

        logger.info(
            "API: Zakończono synchronizację Baselinker (modal)",
            extra={
                'user_id': getattr(current_user, 'id', None),
                'success': result.get('success'),
                'orders_processed': result.get('data', {}).get('stats', {}).get('orders_processed'),
                'products_created': result.get('data', {}).get('stats', {}).get('products_created'),
                'errors_count': result.get('data', {}).get('stats', {}).get('errors_count')
            }
        )

        return jsonify(result), status_code

    except Exception as exc:
        logger.exception(
            "API: Błąd ręcznej synchronizacji Baselinker (modal)",
            extra={'user_id': getattr(current_user, 'id', None)}
        )

        return jsonify({
            'success': False,
            'error': str(exc),
            'data': {
                'status': 'failed',
                'started_at': get_local_now().isoformat()
            }
        }), 500

@api_bp.route('/manual-sync', methods=['POST'])
@login_required
def manual_sync():
    """
    POST /api/manual-sync - Enhanced ręczna synchronizacja (ROZSZERZONY)
    
    NAPRAWIONO:
    - Użycie manual_sync_with_filtering
    - Proper parameter mapping
    - Safe response handling
    """
    try:
        data = request.get_json() or {}
        
        # ZACHOWANE parametry
        sync_type = data.get('sync_type', 'incremental')
        target_statuses = data.get('target_status_ids', [])
        limit = data.get('limit', 1000)
        
        # NOWE parametry z domyślnymi wartościami
        recalculate_priorities = data.get('recalculate_priorities', True)
        auto_status_change = data.get('auto_status_change', True) 
        respect_manual_overrides = data.get('respect_manual_overrides', True)
        
        logger.info("API: Enhanced ręczna synchronizacja", extra={
            'user_id': current_user.id,
            'sync_type': sync_type,
            'target_statuses': target_statuses,
            'limit': limit,
            'recalculate_priorities': recalculate_priorities,
            'auto_status_change': auto_status_change,
            'respect_manual_overrides': respect_manual_overrides
        })
        
        # ZACHOWANA walidacja parametrów
        valid_sync_types = ['full', 'incremental']
        if sync_type not in valid_sync_types:
            return jsonify({
                'success': False,
                'error': f'Nieprawidłowy sync_type. Dozwolone: {valid_sync_types}'
            }), 400
            
        if limit and (not isinstance(limit, int) or limit < 1 or limit > 5000):
            return jsonify({
                'success': False,
                'error': 'Limit musi być liczbą między 1 a 5000'
            }), 400
        
        from ..services.sync_service import get_sync_service
        
        # Sprawdź czy synchronizacja już nie jest w toku
        sync_service = get_sync_service()
        current_status = sync_service.get_sync_status()
        if current_status.get('is_running'):
            return jsonify({
                'success': False,
                'error': 'Synchronizacja jest już w toku',
                'current_sync_status': current_status
            }), 409
        
        # NAPRAWIONA LOGIKA: Użyj manual_sync_with_filtering
        sync_params = {
            'target_statuses': target_statuses if target_statuses else [155824],  # Domyślnie "Nowe - opłacone"
            'period_days': 7,  # Ostatnie 7 dni
            'limit_per_page': min(limit, 100),
            'dry_run': False,
            'force_update': True,
            'debug_mode': False,
            'skip_validation': False,
            'recalculate_priorities': recalculate_priorities,
            'auto_status_change': auto_status_change,
            'respect_manual_overrides': respect_manual_overrides
        }
        
        # Wywołaj synchronizację używając istniejącej metody
        sync_result = sync_service.manual_sync_with_filtering(sync_params)
        
        logger.info("API: Enhanced synchronizacja zakończona", extra={
            'user_id': current_user.id,
            'sync_success': sync_result.get('success', False) if sync_result else False,
            'products_created': sync_result.get('data', {}).get('stats', {}).get('products_created', 0) if sync_result else 0
        })
        
        # BEZPIECZNA obsługa response
        if sync_result is None:
            return jsonify({
                'success': False,
                'error': 'Brak odpowiedzi z serwisu synchronizacji',
                'data': {
                    'status': 'failed',
                    'initiated_by': current_user.id
                }
            }), 500
        
        # ROZSZERZONY RESPONSE (zachowana kompatybilność)
        if sync_result.get('success'):
            data_section = sync_result.get('data', {})
            stats_section = data_section.get('stats', {}) if isinstance(data_section, dict) else {}
            
            response_data = {
                'success': True,
                'message': 'Ręczna synchronizacja zakończona pomyślnie',
                'data': {
                    'sync_id': f'manual_{int(get_local_now().timestamp())}',
                    'status': 'completed' if stats_section.get('error_count', 0) == 0 else 'partial',
                    'initiated_at': get_local_now().isoformat(),
                    'initiated_by': current_user.id,
                    'duration_seconds': data_section.get('duration_seconds', 0),
                    
                    # ZACHOWANE stats (backward compatibility)
                    'stats': {
                        'orders_fetched': stats_section.get('orders_fetched', 0),
                        'products_created': stats_section.get('products_created', 0),
                        'products_updated': stats_section.get('products_updated', 0),
                        'products_skipped': stats_section.get('products_skipped', 0),
                        'error_count': stats_section.get('error_count', 0)
                    },
                    
                    # NOWE sekcje - additive
                    'status_changes': {
                        'orders_moved_to_production': stats_section.get('orders_processed', 0),
                        'status_change_errors': 0  # TODO: dodaj do sync_service
                    },
                    
                    'priority_recalculation': {
                        'enabled': recalculate_priorities,
                        'products_updated': 0,  # TODO: dodaj do sync_service
                        'manual_overrides_preserved': 0,  # TODO: dodaj do sync_service
                        'calculation_duration': '00:00:00'  # TODO: dodaj do sync_service
                    }
                }
            }
            
            return jsonify(response_data), 200
        else:
            return jsonify({
                'success': False,
                'error': sync_result.get('error', 'Nieznany błąd synchronizacji'),
                'data': {
                    'sync_id': f'manual_failed_{int(get_local_now().timestamp())}',
                    'status': 'failed',
                    'initiated_at': get_local_now().isoformat(),
                    'initiated_by': current_user.id,
                    'error_count': 1
                }
            }), 500
        
    except Exception as e:
        logger.error("API: Błąd enhanced ręcznej synchronizacji", extra={
            'user_id': current_user.id,
            'error': str(e),
            'traceback': traceback.format_exc()
        })
        
        return jsonify({
            'success': False,
            'error': str(e),
            'data': {
                'status': 'failed',
                'initiated_by': current_user.id
            }
        }), 500


# ============================================================================
# API ROUTERS - PRD Section 6.4 (Konfiguracja i Monitoring)
# ============================================================================

@api_bp.route('/update-config', methods=['POST'])
@admin_required
def update_config():
    """
    POST /api/update-config - Aktualizacja konfiguracji systemu (PRD Section 6.4)
    
    Body JSON zgodny z PRD:
    {
        "config_key": "STATION_ALLOWED_IPS",
        "config_value": "192.168.1.100,192.168.1.101"
    }
    
    Opcjonalne pola:
    {
        "config_description": "Opis konfiguracji",
        "config_type": "string"  // string, integer, boolean, json, ip_list
    }
    
    Autoryzacja: admin
    Returns: JSON status operacji
    """
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'Brak danych JSON'}), 400
        
        config_key = data.get('config_key')
        config_value = data.get('config_value')
        config_description = data.get('config_description')
        config_type = data.get('config_type', 'string')
        
        if not config_key or config_value is None:
            return jsonify({
                'success': False,
                'error': 'Wymagane pola: config_key, config_value'
            }), 400
        
        # Walidacja config_type
        valid_types = ['string', 'integer', 'boolean', 'json', 'ip_list']
        if config_type not in valid_types:
            return jsonify({
                'success': False,
                'error': f'Nieprawidłowy config_type. Dozwolone: {valid_types}'
            }), 400
        
        # Walidacja wartości zgodnie z typem
        validation_result = _validate_config_value(config_value, config_type)
        if not validation_result['valid']:
            return jsonify({
                'success': False,
                'error': f'Nieprawidłowa wartość dla typu {config_type}: {validation_result["error"]}'
            }), 400
        
        logger.info("API: Aktualizacja konfiguracji", extra={
            'config_key': config_key,
            'config_type': config_type,
            'user_id': current_user.id
        })
        
        from ..models import ProductionConfig
        
        # Użycie metody z modelu dla aktualizacji konfiguracji
        ProductionConfig.set_config(
            key=config_key,
            value=config_value,
            user_id=current_user.id,
            description=config_description,
            config_type=config_type
        )
        
        logger.info("API: Zaktualizowano konfigurację", extra={
            'config_key': config_key,
            'user_id': current_user.id,
            'config_type': config_type
        })
        
        return jsonify({
            'success': True,
            'message': f'Konfiguracja {config_key} zaktualizowana',
            'data': {
                'config_key': config_key,
                'config_value': config_value,
                'config_type': config_type,
                'updated_at': get_local_now().isoformat(),
                'updated_by': current_user.id
            }
        }), 200
        
    except Exception as e:
        logger.error("API: Błąd aktualizacji konfiguracji", extra={
            'config_key': data.get('config_key') if 'data' in locals() else None,
            'user_id': current_user.id,
            'error': str(e)
        })
        
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500
    

@api_bp.route('/baselinker-health')
@login_required
def baselinker_health():
    """
    Lightweight sprawdzenie statusu Baselinker API
    Używa minimalnego requesta aby nie obciążać API
    
    Returns:
        JSON: {
            'status': 'connected'|'slow'|'error'|'unknown',
            'response_time': float|None,
            'error': str|None
        }
    """
    try:
        import time
        import requests
        from flask import current_app
        
        logger.info("API: Sprawdzanie statusu Baselinker", extra={
            'user_id': current_user.id,
            'endpoint': 'baselinker-health'
        })
        
        start_time = time.time()
        
        # Pobierz konfigurację API
        api_config = current_app.config.get('API_BASELINKER', {})
        api_key = api_config.get('api_key')
        endpoint = api_config.get('endpoint', 'https://api.baselinker.com/connector.php')
        
        if not api_key:
            logger.warning("Brak klucza API Baselinker")
            return jsonify({
                'status': 'error', 
                'error': 'Brak skonfigurowanego klucza API',
                'response_time': None
            })
        
        # Minimalny request - sprawdź tylko dostępność
        # Używamy getInventories bo to jeden z najmniejszych requestów
        payload = {
            'method': 'getInventories'
        }
        
        headers = {
            'X-BLToken': api_key,
            'Content-Type': 'application/x-www-form-urlencoded'
        }
        
        response = requests.post(
            endpoint,
            data=payload,
            headers=headers,
            timeout=10  # 10 sekund timeout
        )
        
        response_time = time.time() - start_time
        
        logger.info(f"Baselinker API response: {response.status_code}, time: {response_time:.2f}s")
        
        if response.status_code == 200:
            try:
                data = response.json()
                
                # Sprawdź czy API zwróciło błąd
                if 'error' in data and data['error']:
                    logger.warning(f"Baselinker API error: {data['error']}")
                    return jsonify({
                        'status': 'error',
                        'error': f"API Error: {data['error']}",
                        'response_time': response_time
                    })
                
                # API działa poprawnie
                # Określ status na podstawie czasu odpowiedzi
                if response_time > 5.0:
                    status = 'slow'
                elif response_time > 3.0:
                    status = 'slow'
                else:
                    status = 'connected'
                
                logger.info(f"Baselinker status: {status}")
                
                return jsonify({
                    'status': status,
                    'response_time': response_time,
                    'error': None
                })
                
            except ValueError as e:
                # Błąd parsowania JSON
                logger.error(f"Baselinker JSON parse error: {str(e)}")
                return jsonify({
                    'status': 'error',
                    'error': 'Nieprawidłowa odpowiedź API (JSON)',
                    'response_time': response_time
                })
        else:
            # HTTP error
            logger.warning(f"Baselinker HTTP error: {response.status_code}")
            return jsonify({
                'status': 'error',
                'error': f'HTTP {response.status_code}: {response.reason}',
                'response_time': response_time
            })
            
    except requests.exceptions.Timeout:
        logger.warning("Baselinker API timeout")
        return jsonify({
            'status': 'error',
            'error': 'Timeout połączenia (>10s)',
            'response_time': None
        })
        
    except requests.exceptions.ConnectionError:
        logger.error("Baselinker connection error")
        return jsonify({
            'status': 'error',
            'error': 'Błąd połączenia z API',
            'response_time': None
        })
        
    except Exception as e:
        logger.error(f"Baselinker health check error: {str(e)}", extra={
            'error': str(e),
            'user_id': current_user.id
        })
        return jsonify({
            'status': 'error',
            'error': f'Nieoczekiwany błąd: {str(e)}',
            'response_time': None
        })
    
@api_bp.route('/station-health')
def station_health_check():
    """
    GET /production/api/station-health - Uproszczony health check dla stanowisk produkcyjnych
    
    Prosty endpoint do wykrywania połączenia przez Connection Monitor w station-common.js.
    Bez autoryzacji - publiczny endpoint używany przez heartbeat monitoring.
    
    Używany przez:
    - station-common.js → checkHealth() → heartbeat co 15s
    - Wszystkie stanowiska: cutting, assembly, packaging
    
    Returns:
        JSON: {"status": "OK"} jeśli backend działa i DB połączona
        JSON: {"status": "ERROR", "message": "..."} jeśli błąd
    """
    try:
        # Prosty test połączenia z bazą danych (timeout po stronie DB)
        db.session.execute(text('SELECT 1')).scalar()
        
        # Sukces - backend działa, DB połączona
        response = jsonify({"status": "OK"})
        
        # Wyłącz cache dla health checks (wymaganie PRD)
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
        
        logger.debug("Station health check: OK")
        return response, 200
        
    except Exception as e:
        # Błąd - backend nie działa lub DB niedostępna
        logger.error("Station health check failed", extra={
            'error': str(e),
            'endpoint': '/production/api/station-health'
        })
        
        response = jsonify({
            "status": "ERROR",
            "message": "Service unavailable"
        })
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        
        return response, 500

@api_bp.route('/health')
def health_check():
    """
    GET /api/health - Health check endpoint (PRD Section 6.4)
    
    Sprawdza stan systemu produkcyjnego:
    - Status bazy danych
    - Status synchronizacji Baselinker
    - Status cache
    - Liczba nierozwiązanych błędów
    - Wydajność API Baselinker
    
    Autoryzacja: user, admin
    Returns: JSON zgodny z PRD spec
    """
    try:
        logger.debug("API: Health check", extra={
            'user_id': current_user.id
        })
        
        health_data = {
            'status': 'healthy',
            'timestamp': get_local_now().isoformat(),
            'last_sync': None,
            'database': 'disconnected',
            'baselinker_api': 'unknown',
            'cache': 'inactive',
            'pending_errors': 0
        }
        
        # Test połączenia z bazą danych
        try:
            from ..models import ProductionItem
            
            # Proste zapytanie testowe
            db.session.execute(db.text('SELECT 1')).scalar()
            health_data['database'] = 'connected'
            
            # Sprawdzenie liczby oczekujących błędów
            from ..models import ProductionError
            pending_errors = ProductionError.query.filter_by(is_resolved=False).count()
            health_data['pending_errors'] = pending_errors
            
        except Exception as e:
            health_data['database'] = 'error'
            health_data['status'] = 'unhealthy'
            logger.warning("Health check: Błąd bazy danych", extra={'error': str(e)})
        
        # Status ostatniej synchronizacji
        try:
            from ..services.sync_service import get_sync_status
            
            sync_status = get_sync_status()
            if sync_status.get('last_sync'):
                health_data['last_sync'] = sync_status['last_sync']['timestamp']
                
                # Status API Baselinker na podstawie ostatniej synchronizacji
                if sync_status.get('sync_enabled'):
                    last_sync_status = sync_status['last_sync'].get('status')
                    if last_sync_status == 'completed':
                        health_data['baselinker_api'] = 'responsive'
                    elif last_sync_status == 'failed':
                        health_data['baselinker_api'] = 'error'
                        health_data['status'] = 'degraded'
                    else:
                        health_data['baselinker_api'] = 'unknown'
                else:
                    health_data['baselinker_api'] = 'disabled'
            
        except Exception as e:
            health_data['baselinker_api'] = 'error'
            logger.warning("Health check: Błąd sprawdzania sync", extra={'error': str(e)})
        
        # Status cache (sprawdzenie config_service)
        try:
            from ..services.config_service import get_config_service
            
            config_service = get_config_service()
            if config_service:
                # Test cache - pobierz dowolną konfigurację
                test_config = config_service.get_config('STATION_ALLOWED_IPS', 'test')
                health_data['cache'] = 'active'
            else:
                health_data['cache'] = 'inactive'
                
        except Exception as e:
            health_data['cache'] = 'error'
            logger.warning("Health check: Błąd sprawdzania cache", extra={'error': str(e)})
        
        # Określenie ogólnego stanu zdrowia
        if health_data['database'] == 'error':
            health_data['status'] = 'unhealthy'
        elif health_data['pending_errors'] > 10:
            health_data['status'] = 'degraded'
        elif health_data['baselinker_api'] == 'error':
            health_data['status'] = 'degraded'
        
        # Dodatkowe informacje diagnostyczne dla adminów
        if hasattr(current_user, 'role') and current_user.role.lower() in ['admin', 'administrator']:
            try:
                from ..models import ProductionItem
                
                # Statystyki produktów
                active_products = ProductionItem.query.filter(
                    ProductionItem.current_status.in_([
                        'czeka_na_wyciecie', 'czeka_na_skladanie', 'czeka_na_pakowanie'
                    ])
                ).count()
                
                completed_today = ProductionItem.query.filter(
                    ProductionItem.current_status == 'spakowane',
                    ProductionItem.packaging_completed_at >= datetime.combine(date.today(), datetime.min.time())
                ).count()
                
                health_data['diagnostics'] = {
                    'active_products': active_products,
                    'completed_today': completed_today,
                    'database_tables_accessible': True
                }
                
            except Exception as e:
                health_data['diagnostics'] = {
                    'error': str(e),
                    'database_tables_accessible': False
                }
        
        return jsonify(health_data), 200
        
    except Exception as e:
        logger.error("API: Błąd health check", extra={
            'user_id': current_user.id if current_user.is_authenticated else None,
            'error': str(e)
        })
        
        return jsonify({
            'status': 'error',
            'timestamp': get_local_now().isoformat(),
            'error': str(e),
            'database': 'unknown',
            'baselinker_api': 'unknown',
            'cache': 'unknown',
            'pending_errors': 'unknown'
        }), 500

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def _validate_config_value(value, config_type):
    """
    Waliduje wartość konfiguracji zgodnie z jej typem
    
    Args:
        value: Wartość do walidacji
        config_type (str): Typ konfiguracji
        
    Returns:
        Dict[str, Any]: Wynik walidacji
    """
    try:
        if config_type == 'integer':
            int(value)
        elif config_type == 'boolean':
            if str(value).lower() not in ['true', 'false', '1', '0', 'yes', 'no', 'on', 'off']:
                return {'valid': False, 'error': 'Wartość boolean musi być: true/false, 1/0, yes/no, on/off'}
        elif config_type == 'json':
            json.loads(str(value))
        elif config_type == 'ip_list':
            import ipaddress
            ips = [ip.strip() for ip in str(value).split(',') if ip.strip()]
            for ip in ips:
                ipaddress.ip_address(ip)  # Walidacja każdego IP
        # string - zawsze prawidłowy
        
        return {'valid': True}
        
    except ValueError as e:
        return {'valid': False, 'error': str(e)}
    except Exception as e:
        return {'valid': False, 'error': f'Błąd walidacji: {str(e)}'}


# ============================================================================
# API ROUTERS - PRD Section 6.2 (Complete Packaging z Baselinker Update)
# ============================================================================

@api_bp.route('/complete-packaging', methods=['POST'])
@ip_validation_required
def complete_packaging():
    """
    POST /api/complete-packaging - Ukończenie pakowania z aktualizacją Baselinker (PRD Section 6.2)
    
    Body JSON zgodny z PRD:
    {
        "internal_order_number": "25_05248",
        "completed_products": [
            {"product_id": "25_05248_1", "confirmed": true},
            {"product_id": "25_05248_2", "confirmed": true}
        ]
    }
    
    Działanie:
    1. Zmienia status produktów na 'spakowane'
    2. Wysyła API call do Baselinker zmieniający status zamówienia na 138623
    
    Autoryzacja: Brak (walidacja IP)
    Returns: JSON status operacji i potwierdzenie aktualizacji Baselinker
    """
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'Brak danych JSON'}), 400
        
        internal_order_number = data.get('internal_order_number')
        completed_products = data.get('completed_products', [])
        
        if not internal_order_number:
            return jsonify({
                'success': False,
                'error': 'Wymagane pole: internal_order_number'
            }), 400
        
        if not completed_products or not isinstance(completed_products, list):
            return jsonify({
                'success': False,
                'error': 'Wymagane pole: completed_products (lista produktów)'
            }), 400
        
        logger.info("API: Próba ukończenia pakowania", extra={
            'internal_order_number': internal_order_number,
            'products_count': len(completed_products),
            'client_ip': request.remote_addr
        })
        
        from ..models import ProductionItem
        from ..services.sync_service import update_order_status_in_baselinker
        
        # Walidacja i przygotowanie listy produktów do aktualizacji
        products_to_complete = []
        validation_errors = []
        
        for product_data in completed_products:
            product_id = product_data.get('product_id')
            confirmed = product_data.get('confirmed', False)
            
            if not product_id:
                validation_errors.append('Brak product_id w jednym z produktów')
                continue
            
            if not confirmed:
                validation_errors.append(f'Produkt {product_id} nie jest potwierdzony (confirmed: false)')
                continue
            
            # Znajdź produkt w bazie
            product = ProductionItem.query.filter_by(short_product_id=product_id).first()
            if not product:
                validation_errors.append(f'Produkt {product_id} nie znaleziony')
                continue
            
            # Sprawdź czy produkt należy do danego zamówienia
            if product.internal_order_number != internal_order_number:
                validation_errors.append(f'Produkt {product_id} nie należy do zamówienia {internal_order_number}')
                continue
            
            # Sprawdź czy produkt jest w statusie czeka_na_pakowanie
            if product.current_status != 'czeka_na_pakowanie':
                validation_errors.append(f'Produkt {product_id} ma status "{product.current_status}", oczekiwano "czeka_na_pakowanie"')
                continue
            
            products_to_complete.append(product)
        
        # Jeśli są błędy walidacji, zwróć je
        if validation_errors:
            return jsonify({
                'success': False,
                'error': 'Błędy walidacji produktów',
                'validation_errors': validation_errors
            }), 400
        
        if not products_to_complete:
            return jsonify({
                'success': False,
                'error': 'Brak produktów do ukończenia po walidacji'
            }), 400
        
        # Wykonaj ukończenie pakowania dla wszystkich produktów
        completed_products_list = []
        packaging_errors = []
        
        for product in products_to_complete:
            try:
                old_status = product.current_status
                product.complete_task('packaging')
                
                completed_products_list.append({
                    'product_id': product.short_product_id,
                    'old_status': old_status,
                    'new_status': product.current_status,
                    'completed_at': product.packaging_completed_at.isoformat() if product.packaging_completed_at else None
                })
                
                logger.debug("Ukończono pakowanie produktu", extra={
                    'product_id': product.short_product_id,
                    'old_status': old_status,
                    'new_status': product.current_status
                })
                
            except Exception as e:
                packaging_errors.append({
                    'product_id': product.short_product_id,
                    'error': str(e)
                })
                logger.error("Błąd ukończenia pakowania produktu", extra={
                    'product_id': product.short_product_id,
                    'error': str(e)
                })
        
        # Commit zmian w bazie danych
        db.session.commit()
        
        # Sprawdź czy wszystkie produkty z zamówienia są spakowane i zaktualizuj Baselinker
        baselinker_update_success = False
        baselinker_error = None
        
        try:
            # Sprawdź czy wszystkie produkty z tego zamówienia są teraz spakowane
            all_products_in_order = ProductionItem.query.filter_by(
                internal_order_number=internal_order_number
            ).all()
            
            all_packed = all(p.current_status == 'spakowane' for p in all_products_in_order)
            
            if all_packed:
                logger.info("Wszystkie produkty spakowane - aktualizacja Baselinker", extra={
                    'internal_order_number': internal_order_number,
                    'total_products': len(all_products_in_order)
                })
                
                # Aktualizuj status w Baselinker
                baselinker_update_success = update_order_status_in_baselinker(internal_order_number)
                
                if not baselinker_update_success:
                    baselinker_error = "Nie udało się zaktualizować statusu w Baselinker"
            else:
                packed_count = sum(1 for p in all_products_in_order if p.current_status == 'spakowane')
                logger.info("Nie wszystkie produkty spakowane - brak aktualizacji Baselinker", extra={
                    'internal_order_number': internal_order_number,
                    'packed_count': packed_count,
                    'total_count': len(all_products_in_order)
                })
                
        except Exception as e:
            baselinker_error = str(e)
            logger.error("Błąd aktualizacji Baselinker", extra={
                'internal_order_number': internal_order_number,
                'error': str(e)
            })
        
        # Przygotuj response
        response_data = {
            'success': True,
            'message': f'Ukończono pakowanie {len(completed_products_list)} produktów',
            'data': {
                'internal_order_number': internal_order_number,
                'completed_products': completed_products_list,
                'packaging_errors': packaging_errors,
                'baselinker_update': {
                    'attempted': len(completed_products_list) > 0,
                    'success': baselinker_update_success,
                    'error': baselinker_error
                },
                'completed_at': get_local_now().isoformat()
            }
        }
        
        # Jeśli były błędy pakowania, ale część się udała
        if packaging_errors:
            response_data['success'] = len(completed_products_list) > 0
            response_data['message'] += f', {len(packaging_errors)} błędów'
        
        logger.info("API: Ukończono pakowanie zamówienia", extra={
            'internal_order_number': internal_order_number,
            'completed_count': len(completed_products_list),
            'error_count': len(packaging_errors),
            'baselinker_success': baselinker_update_success,
            'client_ip': request.remote_addr
        })
        
        return jsonify(response_data), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error("API: Błąd ukończenia pakowania", extra={
            'internal_order_number': data.get('internal_order_number') if 'data' in locals() else None,
            'client_ip': request.remote_addr,
            'error': str(e)
        })
        
        return jsonify({
            'success': False,
            'error': str(e),
            'data': {
                'completed_at': get_local_now().isoformat(),
                'rollback_performed': True
            }
        }), 500

# ============================================================================
# ERROR HANDLERS
# ============================================================================

@api_bp.errorhandler(400)
def bad_request(error):
    """Handler dla błędów 400 Bad Request"""
    logger.warning("API: Bad Request", extra={
        'error': str(error),
        'endpoint': request.endpoint,
        'client_ip': request.remote_addr
    })
    
    return jsonify({
        'success': False,
        'error': 'Nieprawidłowe żądanie',
        'status_code': 400
    }), 400

@api_bp.errorhandler(401)
def unauthorized(error):
    """Handler dla błędów 401 Unauthorized"""
    logger.warning("API: Unauthorized", extra={
        'error': str(error),
        'endpoint': request.endpoint,
        'client_ip': request.remote_addr
    })
    
    return jsonify({
        'success': False,
        'error': 'Wymagana autoryzacja',
        'status_code': 401
    }), 401

@api_bp.errorhandler(403)
def forbidden(error):
    """Handler dla błędów 403 Forbidden"""
    logger.warning("API: Forbidden", extra={
        'error': str(error),
        'endpoint': request.endpoint,
        'client_ip': request.remote_addr,
        'user_id': current_user.id if current_user.is_authenticated else None
    })
    
    return jsonify({
        'success': False,
        'error': 'Brak uprawnień',
        'status_code': 403
    }), 403

@api_bp.errorhandler(404)
def not_found(error):
    """Handler dla błędów 404 Not Found"""
    logger.warning("API: Not Found", extra={
        'error': str(error),
        'endpoint': request.endpoint,
        'client_ip': request.remote_addr
    })
    
    return jsonify({
        'success': False,
        'error': 'Endpoint nie znaleziony',
        'status_code': 404
    }), 404

@api_bp.errorhandler(405)
def method_not_allowed(error):
    """Handler dla błędów 405 Method Not Allowed"""
    logger.warning("API: Method Not Allowed", extra={
        'error': str(error),
        'method': request.method,
        'endpoint': request.endpoint,
        'client_ip': request.remote_addr
    })
    
    return jsonify({
        'success': False,
        'error': f'Metoda {request.method} nie dozwolona',
        'status_code': 405
    }), 405

@api_bp.errorhandler(500)
def internal_server_error(error):
    """Handler dla błędów 500 Internal Server Error"""
    logger.error("API: Internal Server Error", extra={
        'error': str(error),
        'endpoint': request.endpoint,
        'client_ip': request.remote_addr,
        'user_id': current_user.id if current_user.is_authenticated else None
    })
    
    return jsonify({
        'success': False,
        'error': 'Błąd wewnętrzny serwera',
        'status_code': 500
    }), 500

# ============================================================================
# CONTEXT PROCESSORS I BEFORE/AFTER REQUEST
# ============================================================================

@api_bp.before_request
def log_api_request():
    """Loguje wszystkie żądania API"""
    try:
        logger.debug("API Request", extra={
            'method': request.method,
            'path': request.path,
            'endpoint': request.endpoint,
            'client_ip': request.remote_addr,
            'user_agent': request.headers.get('User-Agent', 'Unknown'),
            'content_type': request.headers.get('Content-Type'),
            'user_id': current_user.id if current_user.is_authenticated else None
        })
    except Exception as e:
        logger.error("Błąd logowania API request", extra={'error': str(e)})

@api_bp.after_request
def add_api_headers(response):
    """Dodaje nagłówki do wszystkich odpowiedzi API"""
    try:
        # Nagłówki dla API
        response.headers['Content-Type'] = 'application/json; charset=utf-8'
        response.headers['X-API-Version'] = '1.0'
        response.headers['X-Production-Module'] = 'WoodPower-Production-API'
        
        # Nagłówki CORS (jeśli potrzebne)
        # response.headers['Access-Control-Allow-Origin'] = '*'
        # response.headers['Access-Control-Allow-Methods'] = 'GET, POST, PUT, DELETE, OPTIONS'
        
        return response
    except Exception as e:
        logger.error("Błąd dodawania nagłówków API", extra={'error': str(e)})
        return response
    
# ============================================================================
# NOWE ENDPOINTY AJAX DLA SYSTEMU TABÓW
# Dodaj te funkcje do istniejącego api_routers.py
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
        # Sprawdź czy to pierwsze ładowanie template
        initial_load = request.args.get('initial_load', 'false').lower() == 'true'
        
        logger.info("AJAX: dashboard-tab-content", extra={
            'user_id': current_user.id,
            'user_role': getattr(current_user, 'role', 'unknown'),
            'initial_load': initial_load
        })
        
        if not initial_load:
            # Dla odświeżania danych - przekieruj do dashboard-data
            from flask import redirect, url_for
            return redirect(url_for('production.production_api.dashboard_data'))
        
        # PIERWSZE ŁADOWANIE - zwróć pełny HTML template
        from ..models import ProductionItem, ProductionError, ProductionSyncLog
        
        today = date.today()
        
        # Pobierz dane dashboard (identycznie jak w dashboard-data)
        dashboard_stats = {}
        
        # Statystyki stacji - POPRAWIONA STRUKTURA dla template
        cutting_count = ProductionItem.query.filter(ProductionItem.current_status == 'czeka_na_wyciecie').count()
        assembly_count = ProductionItem.query.filter(ProductionItem.current_status == 'czeka_na_skladanie').count()
        packaging_count = ProductionItem.query.filter(ProductionItem.current_status == 'czeka_na_pakowanie').count()
        
        # Oblicz dzisiejsze m3 dla każdej stacji
        today_start = datetime.combine(today, datetime.min.time())
        today_end = datetime.combine(today, datetime.max.time())
        
        cutting_m3_today = 0.0
        assembly_m3_today = 0.0
        packaging_m3_today = 0.0
        
        try:
            # M3 wyciętych dzisiaj
            cutting_m3_today = db.session.query(
                db.func.coalesce(db.func.sum(ProductionItem.volume_m3), 0)
            ).filter(
                ProductionItem.cutting_completed_at >= today_start,
                ProductionItem.cutting_completed_at <= today_end
            ).scalar() or 0.0
            
            # M3 składanych dzisiaj
            assembly_m3_today = db.session.query(
                db.func.coalesce(db.func.sum(ProductionItem.volume_m3), 0)
            ).filter(
                ProductionItem.assembly_completed_at >= today_start,
                ProductionItem.assembly_completed_at <= today_end
            ).scalar() or 0.0
            
            # M3 pakowanych dzisiaj
            packaging_m3_today = db.session.query(
                db.func.coalesce(db.func.sum(ProductionItem.volume_m3), 0)
            ).filter(
                ProductionItem.packaging_completed_at >= today_start,
                ProductionItem.packaging_completed_at <= today_end
            ).scalar() or 0.0
            
        except Exception as volume_error:
            logger.warning("Nie udało się pobrać volume_m3 dla stacji", extra={'error': str(volume_error)})
        
        # STRUKTURA ZGODNA Z TEMPLATE - jako słownik, nie lista
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
            'packaging': {
                'pending_count': packaging_count,
                'today_m3': float(packaging_m3_today),
                'status': 'active' if packaging_count > 0 else 'idle',
                'status_class': 'station-active' if packaging_count > 0 else 'station-idle'
            }
        }
        
        # Dzisiejsze sumy
        today_start = datetime.combine(today, datetime.min.time())
        today_end = datetime.combine(today, datetime.max.time())
        
        completed_today = ProductionItem.query.filter(
            ProductionItem.current_status == 'spakowane',
            ProductionItem.packaging_completed_at >= today_start,
            ProductionItem.packaging_completed_at <= today_end
        ).count()
        
        total_m3_today = 0.0
        try:
            total_m3_today = db.session.query(
                db.func.coalesce(db.func.sum(ProductionItem.volume_m3), 0)
            ).filter(
                ProductionItem.packaging_completed_at >= today_start,
                ProductionItem.packaging_completed_at <= today_end
            ).scalar() or 0.0
        except:
            total_m3_today = 0.0
        
        dashboard_stats['today_totals'] = {
            'completed_orders': completed_today,
            'total_m3': float(total_m3_today),
            'total_orders': ProductionItem.query.count()
        }
        
        # Alerty terminów
        deadline_alerts = ProductionItem.query.filter(
            ProductionItem.deadline_date <= (today + timedelta(days=3)),
            ProductionItem.current_status != 'spakowane'
        ).order_by(ProductionItem.deadline_date.asc()).limit(5).all()
        
        dashboard_stats['deadline_alerts'] = [
            {
                'short_product_id': alert.short_product_id,
                'deadline_date': alert.deadline_date.isoformat() if alert.deadline_date else None,
                'days_remaining': (alert.deadline_date - today).days if alert.deadline_date else 0,
                'current_station': alert.current_status.replace('czeka_na_', '') if alert.current_status else 'unknown'
            }
            for alert in deadline_alerts
        ]
        
        # System health
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
        
        # Renderuj template
        rendered_html = render_template(
            'components/dashboard-tab-content.html', 
            dashboard_stats=dashboard_stats
        )
        
        return jsonify({
            'success': True,
            'html': rendered_html,
            'initial_data': dashboard_stats,  # NOWE - dane początkowe dla frontend
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


@api_bp.route('/products-tab-content', methods=['GET'])
@login_required  
def products_tab_content():
    """
    Endpoint zwracający zawartość taba produktów - NAPRAWIONY
    BUGFIX: Usuwa limit 100 produktów, zwraca wszystkie produkty z parsowanymi polami
    """
    try:
        # Pobierz podstawowe parametry
        status_filter = request.args.get('status', 'all')
        search_query = request.args.get('search', '')
        load_all = request.args.get('load_all', 'true').lower() == 'true'
                
        # Pobierz produkty z bazy danych - BEZ LIMITU
        products_query = ProductionItem.query
        
        # Filtrowanie po statusie
        if status_filter and status_filter != 'all':
            products_query = products_query.filter(ProductionItem.current_status == status_filter)
        
        # Wyszukiwanie - bezpieczne sprawdzenie atrybutów
        if search_query:
            search_pattern = f"%{search_query}%"
            search_conditions = []
            
            if hasattr(ProductionItem, 'original_product_name'):
                search_conditions.append(ProductionItem.original_product_name.ilike(search_pattern))
            if hasattr(ProductionItem, 'short_product_id'):
                search_conditions.append(ProductionItem.short_product_id.ilike(search_pattern))
            if hasattr(ProductionItem, 'client_name'):
                search_conditions.append(ProductionItem.client_name.ilike(search_pattern))
                
            if search_conditions:
                products_query = products_query.filter(or_(*search_conditions))
        
        # Obsługa parametrów sortowania
        sort_by = request.args.get('sort_by', 'priority_rank')  # ZMIANA: domyślnie priority_rank
        sort_order = request.args.get('sort_order', 'asc' if sort_by == 'priority_rank' else 'desc')
        
        # Sortowanie z obsługą parametrów
        sort_column = None
        if sort_by == 'priority_rank' and hasattr(ProductionItem, 'priority_rank'):
            sort_column = ProductionItem.priority_rank
        elif sort_by == 'priority_score' and hasattr(ProductionItem, 'priority_score'):
            sort_column = ProductionItem.priority_score
        elif sort_by == 'created_at' and hasattr(ProductionItem, 'created_at'):
            sort_column = ProductionItem.created_at
        elif sort_by == 'deadline_date' and hasattr(ProductionItem, 'deadline_date'):
            sort_column = ProductionItem.deadline_date
            
        if sort_column is not None:
            if sort_order == 'desc':
                products_query = products_query.order_by(sort_column.desc())
            else:
                products_query = products_query.order_by(sort_column.asc())
        else:
            # Fallback - domyślnie priority_rank ASC
            if hasattr(ProductionItem, 'priority_rank'):
                products_query = products_query.order_by(ProductionItem.priority_rank.asc())
            else:
                products_query = products_query.order_by(ProductionItem.id.desc())
        
        # ZMIANA: Pobierz WSZYSTKIE produkty (usuń limit)
        products = products_query.all()
        
        logger.info(f"[BUGFIX] Pobranych produktów: {len(products)} (bez limitu)")
        
        # Renderuj HTML template
        html_content = render_template('components/products-tab-content.html')
        
        # Przygotuj dane produktów z bezpiecznym dostępem do atrybutów
        products_data = []
        for product in products:
            # Bezpieczne pobieranie wartości z fallback
            def get_attr(obj, attr_name, default=None):
                return getattr(obj, attr_name, default) if hasattr(obj, attr_name) else default
            
            # Oblicz dni do deadline
            days_to_deadline = None
            if hasattr(product, 'deadline_date') and product.deadline_date:
                try:
                    deadline = product.deadline_date
                    if isinstance(deadline, str):
                        deadline = datetime.strptime(deadline, '%Y-%m-%d').date()
                    days_to_deadline = (deadline - date.today()).days
                except:
                    days_to_deadline = None
            
            # Bezpieczne pobieranie objętości
            volume_m3 = 0.0
            try:
                vol = get_attr(product, 'volume_m3', 0)
                volume_m3 = float(vol) if vol is not None else 0.0
            except (ValueError, TypeError):
                volume_m3 = 0.0
            
            # Bezpieczne pobieranie wartości netto
            total_value_net = 0.0
            try:
                val = get_attr(product, 'total_value_net', 0)
                total_value_net = float(val) if val is not None else 0.0
            except (ValueError, TypeError):
                total_value_net = 0.0
            
            # Bezpieczne pobieranie ceny jednostkowej
            unit_price_net = 0.0
            try:
                price = get_attr(product, 'unit_price_net', 0)
                unit_price_net = float(price) if price is not None else 0.0
            except (ValueError, TypeError):
                unit_price_net = 0.0
            
            # Bezpieczne pobieranie parsowanych wymiarów
            parsed_length_cm = 0.0
            parsed_width_cm = 0.0
            parsed_thickness_cm = 0.0
            try:
                if get_attr(product, 'parsed_length_cm') is not None:
                    parsed_length_cm = float(get_attr(product, 'parsed_length_cm', 0))
                if get_attr(product, 'parsed_width_cm') is not None:
                    parsed_width_cm = float(get_attr(product, 'parsed_width_cm', 0))
                if get_attr(product, 'parsed_thickness_cm') is not None:
                    parsed_thickness_cm = float(get_attr(product, 'parsed_thickness_cm', 0))
            except (ValueError, TypeError):
                pass
            
            product_dict = {
                # Podstawowe dane
                'id': product.id,
                'short_product_id': get_attr(product, 'short_product_id', ''),
                'original_product_name': get_attr(product, 'original_product_name', ''),
                'current_status': get_attr(product, 'current_status', 'czeka_na_wyciecie'),
                'priority_rank': get_attr(product, 'priority_rank', None),
                'priority_manual_override': get_attr(product, 'priority_manual_override', False),

                # Wymiary i wartości
                'volume_m3': volume_m3,
                'total_value_net': total_value_net,
                'unit_price_net': unit_price_net,
                
                # Deadline
                'deadline_date': get_attr(product, 'deadline_date').isoformat() if get_attr(product, 'deadline_date') else None,
                'days_until_deadline': days_to_deadline,
                
                # Dane klienta
                'client_name': get_attr(product, 'client_name', ''),
                'client_email': get_attr(product, 'client_email', ''),
                'client_phone': get_attr(product, 'client_phone', ''),
                'delivery_address': get_attr(product, 'delivery_address', ''),
                
                # Dane zamówienia
                'internal_order_number': get_attr(product, 'internal_order_number', ''),
                'baselinker_order_id': get_attr(product, 'baselinker_order_id', None),
                'baselinker_product_id': get_attr(product, 'baselinker_product_id', ''),
                'product_sequence_in_order': get_attr(product, 'product_sequence_in_order', 1),
                
                # POPRAWIONE: Specyfikacja produktu - PARSOWANE POLA z bazy danych
                'parsed_wood_species': get_attr(product, 'parsed_wood_species', None),
                'parsed_technology': get_attr(product, 'parsed_technology', None),
                'parsed_wood_class': get_attr(product, 'parsed_wood_class', None),
                'parsed_length_cm': parsed_length_cm,
                'parsed_width_cm': parsed_width_cm,
                'parsed_thickness_cm': parsed_thickness_cm,
                'parsed_finish_state': get_attr(product, 'parsed_finish_state', None),
                
                # Produkcja - statusy i czasami
                'cutting_started_at': get_attr(product, 'cutting_started_at').isoformat() if get_attr(product, 'cutting_started_at') else None,
                'cutting_completed_at': get_attr(product, 'cutting_completed_at').isoformat() if get_attr(product, 'cutting_completed_at') else None,
                'cutting_duration_minutes': get_attr(product, 'cutting_duration_minutes', None),
                'assembly_started_at': get_attr(product, 'assembly_started_at').isoformat() if get_attr(product, 'assembly_started_at') else None,
                'assembly_completed_at': get_attr(product, 'assembly_completed_at').isoformat() if get_attr(product, 'assembly_completed_at') else None,
                'assembly_duration_minutes': get_attr(product, 'assembly_duration_minutes', None),
                'packaging_started_at': get_attr(product, 'packaging_started_at').isoformat() if get_attr(product, 'packaging_started_at') else None,
                'packaging_completed_at': get_attr(product, 'packaging_completed_at').isoformat() if get_attr(product, 'packaging_completed_at') else None,
                'packaging_duration_minutes': get_attr(product, 'packaging_duration_minutes', None),
                
                # Przypisani pracownicy
                'cutting_assigned_worker_id': get_attr(product, 'cutting_assigned_worker_id', None),
                'assembly_assigned_worker_id': get_attr(product, 'assembly_assigned_worker_id', None),
                'packaging_assigned_worker_id': get_attr(product, 'packaging_assigned_worker_id', None),
                
                # Notatki i problemy
                'production_notes': get_attr(product, 'production_notes', ''),
                'quality_issues': get_attr(product, 'quality_issues', ''),
                
                # Timestampy
                'created_at': product.created_at.isoformat() if hasattr(product, 'created_at') and product.created_at else None,
                'updated_at': product.updated_at.isoformat() if hasattr(product, 'updated_at') and product.updated_at else None,
                'sync_source': get_attr(product, 'sync_source', None),
                
                # Unique identifier dla frontend
                'unique_id': f"{get_attr(product, 'short_product_id', '')}-{product.id}"
            }
            products_data.append(product_dict)
        
        # Przygotuj statystyki
        total_volume = sum(p['volume_m3'] for p in products_data)
        total_value = sum(p['total_value_net'] for p in products_data)
        
        # Oblicz pilne produkty (deadline <= 3 dni)
        urgent_count = 0
        for p in products_data:
            if p['days_until_deadline'] is not None and p['days_until_deadline'] <= 3:
                urgent_count += 1
        
        # Breakdown statusów
        status_breakdown = {}
        for p in products_data:
            status = p['current_status']
            status_breakdown[status] = status_breakdown.get(status, 0) + 1
        
        stats_data = {
            'total_count': len(products_data),
            'total_volume': round(total_volume, 3),
            'total_value': round(total_value, 2),
            'urgent_count': urgent_count,
            'status_breakdown': status_breakdown
        }
        
        # Przygotuj opcje filtrów z produktów
        filters_data = {
            'wood_species': list(set(p['parsed_wood_species'] for p in products_data if p['parsed_wood_species'])),
            'technologies': list(set(p['parsed_technology'] for p in products_data if p['parsed_technology'])),
            'wood_classes': list(set(p['parsed_wood_class'] for p in products_data if p['parsed_wood_class'])),
            'thicknesses': list(set(f"{p['parsed_thickness_cm']}cm" for p in products_data if p['parsed_thickness_cm'] and p['parsed_thickness_cm'] > 0)),
            'statuses': list(set(p['current_status'] for p in products_data if p['current_status']))
        }
        
        # Sortuj opcje filtrów
        filters_data['wood_species'].sort()
        filters_data['technologies'].sort()
        filters_data['wood_classes'].sort()
        filters_data['thicknesses'].sort(key=lambda x: float(x.replace('cm', '')))
        filters_data['statuses'].sort()
        
        logger.info(f"[BUGFIX] Statystyki: {stats_data}")
        logger.info(f"[BUGFIX] Opcje filtrów: gatunki={len(filters_data['wood_species'])}, technologie={len(filters_data['technologies'])}")
        
        return jsonify({
            'success': True,
            'html': html_content,
            'initial_data': {
                'products': products_data,
                'stats': stats_data,
                'filters': filters_data,
                'total_count': len(products_data),
                'load_all': load_all
            },
            'products_count': len(products),
            'debug_info': {
                'status_filter': status_filter,
                'search_query': search_query,
                'products_returned': len(products_data),
                'load_all': load_all,
                'query_without_limit': True,
                'parsed_fields_included': True,
                'filters_data_included': True
            }
        })
        
    except Exception as e:
        # Szczegółowe logowanie błędu
        error_traceback = traceback.format_exc()
        logger.error(f"Błąd endpoint products-tab-content: {str(e)}")
        logger.error(f"Traceback: {error_traceback}")
        
        return jsonify({
            'success': False,
            'error': str(e),
            'traceback': error_traceback if current_app.debug else None
        }), 500


# Dla paginowanych zapytań
@api_bp.route('/products-paginated', methods=['GET'])
@login_required
def products_paginated():
    """
    Endpoint dla paginowanych produktów - dla bardzo dużych zbiorów danych
    """
    try:
        # Parametry paginacji
        page = int(request.args.get('page', 1))
        per_page = min(int(request.args.get('per_page', 50)), 800)  # Max 800 na stronę
        
        # Filtry
        status_filter = request.args.get('status', 'all')
        search_query = request.args.get('search', '')
        
        # Query builder
        products_query = ProductionItem.query
        
        if status_filter and status_filter != 'all':
            products_query = products_query.filter(ProductionItem.current_status == status_filter)
            
        if search_query:
            search_pattern = f"%{search_query}%"
            search_conditions = []
            
            if hasattr(ProductionItem, 'original_product_name'):
                search_conditions.append(ProductionItem.original_product_name.ilike(search_pattern))
            if hasattr(ProductionItem, 'short_product_id'):
                search_conditions.append(ProductionItem.short_product_id.ilike(search_pattern))
                
            if search_conditions:
                products_query = products_query.filter(or_(*search_conditions))
        
        # Sortowanie
        if hasattr(ProductionItem, 'priority_score'):
            products_query = products_query.order_by(ProductionItem.priority_score.desc())
        
        # Paginacja
        paginated = products_query.paginate(
            page=page, 
            per_page=per_page, 
            error_out=False
        )
        
        # Przygotuj dane
        products_data = []
        for product in paginated.items:
            # Używamy tej samej logiki co w głównym endpoint
            product_dict = {
                'id': product.id,
                'short_product_id': getattr(product, 'short_product_id', ''),
                'original_product_name': getattr(product, 'original_product_name', ''),
                'current_status': getattr(product, 'current_status', 'nieznany'),
                'priority_score': getattr(product, 'priority_score', 0),
                'unique_id': f"{getattr(product, 'short_product_id', '')}-{product.id}"
                # ... reszta pól
            }
            products_data.append(product_dict)
        
        return jsonify({
            'success': True,
            'products': products_data,
            'pagination': {
                'page': page,
                'per_page': per_page,
                'total': paginated.total,
                'pages': paginated.pages,
                'has_next': paginated.has_next,
                'has_prev': paginated.has_prev
            }
        })
        
    except Exception as e:
        logger.error(f"Błąd endpoint products-paginated: {str(e)}")
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
        
        from ..models import ProductionItem, ProductionSyncLog
        
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
            
            volume = db.session.query(db.func.sum(ProductionItem.volume_m3))\
                              .filter(
                                  ProductionItem.packaging_completed_at >= day_start,
                                  ProductionItem.packaging_completed_at <= day_end
                              ).scalar() or 0.0
            
            daily_stats.append({
                'date': day.isoformat(),
                'completed_orders': completed,
                'total_volume': float(volume)
            })
        
        # Raport statusów
        status_report = []
        statuses = ['czeka_na_wyciecie', 'czeka_na_skladanie', 'czeka_na_pakowanie', 'spakowane', 'wstrzymane']
        for status in statuses:
            count = ProductionItem.query.filter_by(current_status=status).count()
            volume = db.session.query(db.func.sum(ProductionItem.volume_m3))\
                              .filter_by(current_status=status).scalar() or 0.0
            
            status_report.append({
                'status': status,
                'count': count,
                'volume': float(volume)
            })
        
        # Historia synchronizacji
        sync_history = ProductionSyncLog.query\
                                       .order_by(ProductionSyncLog.sync_started_at.desc())\
                                       .limit(20).all()
        
        reports_data = {
            'daily_performance': daily_stats,
            'status_breakdown': status_report,
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
        
        # Renderuj komponent
        rendered_html = render_template('components/reports-tab-content.html',
                              reports_data=reports_data)
        
        return jsonify({
            'success': True,
            'html': rendered_html,
            'data': reports_data,
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



@api_bp.route('/stations-tab-content')
@login_required  
def stations_tab_content():
    """
    AJAX endpoint dla zawartości taba Stanowiska - POPRAWIONY
    """
    try:
        logger.info("AJAX: Ładowanie zawartości stations-tab", extra={
            'user_id': current_user.id,
            'user_role': getattr(current_user, 'role', 'unknown')
        })
        
        from ..models import ProductionItem
        
        # Dane dla każdego stanowiska
        stations_data = {}
        stations = ['cutting', 'assembly', 'packaging']
        
        for station in stations:
            status_map = {
                'cutting': 'czeka_na_wyciecie',
                'assembly': 'czeka_na_skladanie', 
                'packaging': 'czeka_na_pakowanie'
            }
            
            status = status_map[station]
            
            # Produkty oczekujące na danym stanowisku
            pending_products = ProductionItem.query\
                                           .filter_by(current_status=status)\
                                           .order_by(ProductionItem.priority_score.desc())\
                                           .limit(20).all()
            
            # Statystyki stanowiska
            total_pending = ProductionItem.query.filter_by(current_status=status).count()
            high_priority = ProductionItem.query.filter(
                ProductionItem.current_status == status,
                ProductionItem.priority_score >= 150
            ).count()
            
            # Dzisiejsze wykonania
            today = date.today()
            today_start = datetime.combine(today, datetime.min.time())
            
            completed_field_map = {
                'cutting': ProductionItem.cutting_completed_at,
                'assembly': ProductionItem.assembly_completed_at,
                'packaging': ProductionItem.packaging_completed_at
            }
            
            completed_field = completed_field_map[station]
            today_completed = ProductionItem.query.filter(
                completed_field >= today_start
            ).count()
            
            today_volume = db.session.query(db.func.sum(ProductionItem.volume_m3))\
                                   .filter(completed_field >= today_start)\
                                   .scalar() or 0.0
            
            # POPRAWIONE: twórz słowniki zamiast obiektów z .days_diff
            stations_data[station] = {
                'name': {
                    'cutting': 'Wycinanie',
                    'assembly': 'Składanie',
                    'packaging': 'Pakowanie'
                }[station],
                'icon': {
                    'cutting': '🪚',
                    'assembly': '🔧', 
                    'packaging': '📦'
                }[station],
                'pending_products': [
                    {
                        'short_id': p.short_product_id,
                        'product_name': p.original_product_name[:50] + '...' if len(p.original_product_name or '') > 50 else (p.original_product_name or ''),
                        'priority_rank': p.priority_rank,
                        'deadline_date': p.deadline_date.isoformat() if p.deadline_date else None,
                        'days_remaining': (p.deadline_date - today).days if p.deadline_date else 0,  # DODANO: days_remaining
                        'volume_m3': float(p.volume_m3 or 0),
                        'internal_order_number': p.internal_order_number
                    }
                    for p in pending_products
                ],
                'stats': {
                    'total_pending': total_pending,
                    'high_priority': high_priority,
                    'today_completed': today_completed,
                    'today_volume': float(today_volume)
                }
            }
        
        # Renderuj komponent
        rendered_html = render_template('components/stations-tab-content.html',
                              stations_data=stations_data)
        
        return jsonify({
            'success': True,
            'html': rendered_html,
            'data': stations_data,
            'last_updated': get_local_now().isoformat()
        })
        
    except Exception as e:
        logger.error("Błąd AJAX stations-tab-content", extra={
            'user_id': current_user.id,
            'error': str(e)
        })
        
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500
  

@api_bp.route('/config-tab-content')
@login_required  
def config_tab_content():
    """
    AJAX endpoint dla zawartości taba Konfiguracja (tylko admin)

    Zmiany:
    - Pobieranie wszystkich kluczy bezpośrednio z bazy (ProductionConfig -> prod_config)
    - Parsowanie wartości wg config_type (boolean/integer/json/ip_list/string)
    - Budowa mapy {config_key: {...}} + grup tematycznych
    - Dodatkowo eksport grup jako SimpleNamespace (kropkowy dostęp w Jinja)
    """
    try:
        logger.info("AJAX: Ładowanie zawartości config-tab", extra={
            'user_id': current_user.id,
            'user_role': getattr(current_user, 'role', 'unknown')
        })

        from types import SimpleNamespace
        import json

        from ..models import ProductionConfig, ProductionPriorityConfig
        from ..services.config_service import get_config_service

        def _parse_value(raw_value: str, cfg_type: str):
            """Konwersja wartości z bazy na Pythonowe typy."""
            try:
                t = (cfg_type or '').lower()
                if t == 'boolean':
                    # akceptuj 'true'/'false', '1'/'0'
                    v = str(raw_value).strip().lower()
                    return v in ('true', '1', 'yes')
                elif t == 'integer':
                    return int(str(raw_value).strip())
                elif t == 'json':
                    return json.loads(raw_value) if raw_value not in (None, '', 'null') else None
                elif t == 'ip_list':
                    # lista IP rozdzielona przecinkami
                    return [ip.strip() for ip in str(raw_value).split(',') if ip.strip()]
                else:
                    # domyślnie string
                    return raw_value
            except Exception:
                # W razie błędu parsowania – zwróć surową wartość
                return raw_value

        # 1) Pobierz WSZYSTKIE wpisy z prod_config
        configs_q = ProductionConfig.query.order_by(ProductionConfig.config_key.asc()).all()

        # 2) Zbuduj mapę po kluczu
        all_configs = {}
        for c in configs_q:
            parsed = _parse_value(c.config_value, c.config_type)
            all_configs[c.config_key] = {
                'key': c.config_key,
                'value': parsed,
                'raw_value': c.config_value,
                'type': c.config_type,
                'description': getattr(c, 'config_description', None),
                'updated_at': getattr(c, 'updated_at', None),
                'created_at': getattr(c, 'created_at', None),
            }

        # 3) Pogrupuj klucze tematycznie
        EXPECTED = {
            # Sync/Baselinker (grupa w HTML: "Synchronizacja i Baselinker")
            'SYNC_ENABLED':                 ('sync',        True,        'boolean'),
            'MAX_SYNC_ITEMS_PER_BATCH':     ('sync',        1000,        'integer'),
            'BASELINKER_TARGET_STATUS_COMPLETED': ('sync', 138623,       'integer'),
            'SYNC_RETRY_COUNT':             ('sync',        3,           'integer'),

            # Stations (Stanowiska produkcyjne)
            'STATION_ALLOWED_IPS':          ('stations',    '192.168.1.100,192.168.1.101', 'ip_list'),
            'REFRESH_INTERVAL_SECONDS':     ('stations',    30,          'integer'),
            'STATION_AUTO_REFRESH_ENABLED': ('stations',    True,        'boolean'),
            'STATION_MAX_PRODUCTS_DISPLAY': ('stations',    50,          'integer'),

            # Priorytety i Deadlines
            'DEADLINE_DEFAULT_DAYS':        ('priorities',  14,          'integer'),
            'PRIORITY_RECALC_INTERVAL_HOURS': ('priorities', 24,         'integer'),
            'PRIORITY_ALGORITHM_VERSION':   ('priorities',  '2.0',       'string'),

            # System i Debug
            'DEBUG_PRODUCTION_BACKEND':     ('system',      False,       'boolean'),
            'DEBUG_PRODUCTION_FRONTEND':    ('system',      False,       'boolean'),
            'CACHE_DURATION_SECONDS':       ('system',      3600,        'integer'),
            'ADMIN_EMAIL_NOTIFICATIONS':    ('system',      'admin@woodpower.pl', 'string'),
            'ERROR_NOTIFICATION_THRESHOLD': ('system',      10,          'integer'),

            # Cache i Inne (UWAGA: mimo "BASELINKER" klucz ma być w OTHER, zgodnie z HTML)
            'BASELINKER_STATUSES_CACHE':    ('other',       '{"id": 105112, "name": "Nowe - opłacone", "color": "ffffff"}', 'json'),
            'MAX_PRODUCTS_PER_ORDER':       ('other',       999,         'integer'),
        }

        # --- 3b) Uzupełnij brakujące klucze domyślnymi wpisami ---
        for key, (grp, default_val, default_type) in EXPECTED.items():
            if key not in all_configs:
                all_configs[key] = {
                    'key': key,
                    'value': _parse_value(default_val if isinstance(default_val, str) else str(default_val), default_type),
                    'raw_value': str(default_val),
                    'type': default_type,
                    'description': f'Default injected ({grp})',
                    'updated_at': None,
                    'created_at': None,
                }

        # --- 3c) Grupowanie: najpierw whitelist, potem heurystyka dla reszty ---
        config_groups = {'sync': {}, 'stations': {}, 'priorities': {}, 'system': {}, 'other': {}}

        def assign_group(key: str) -> str:
            if key in EXPECTED:
                return EXPECTED[key][0]  # grupa z whitelisty
            k = key.upper()
            if any(s in k for s in ('SYNC', 'BASELINKER')):
                return 'sync'
            if any(s in k for s in ('STATION', 'REFRESH')):
                return 'stations'
            if any(s in k for s in ('PRIORITY', 'DEADLINE')):
                return 'priorities'
            if any(s in k for s in ('DEBUG', 'CACHE', 'EMAIL', 'ERROR', 'LOG', 'NOTIFICATION')):
                return 'system'
            return 'other'

        for key, cfg in all_configs.items():
            config_groups[assign_group(key)][key] = cfg

        # (opcjonalnie: diagnostyka co gdzie wpadło)
        logger.debug("Config keys by group", extra={
            'sync': list(config_groups['sync'].keys()),
            'stations': list(config_groups['stations'].keys()),
            'priorities': list(config_groups['priorities'].keys()),
            'system': list(config_groups['system'].keys()),
            'other': list(config_groups['other'].keys()),
        })

        # 4) Namespace do kropkowego dostępu w Jinja
        from types import SimpleNamespace
        def to_ns(d: dict) -> SimpleNamespace:
            return SimpleNamespace(**d)

        config_groups_ns = {
            group: to_ns({k: v for k, v in items.items()})
            for group, items in config_groups.items()
        }

        # 5) Konfiguracje priorytetów (drag & drop)
        priority_configs = (
            ProductionPriorityConfig.query
            .filter_by(is_active=True)
            .order_by(ProductionPriorityConfig.display_order)
            .all()
        )

        # 6) Statystyki cache (zostawiamy bez zmian)
        config_service = get_config_service()
        cache_stats = config_service.get_cache_stats()

        # 7) Dane do frontu
        config_data = {
            'all_configs': all_configs,     # dict -> OK do JSON
            'config_groups': config_groups, # dict -> OK do JSON
            'priority_configs': [
                {
                    'id': pc.id,
                    'criterion_name': pc.criterion_name,
                    'weight': pc.weight,
                    'display_order': pc.display_order,
                    'is_active': pc.is_active
                } for pc in priority_configs
            ],
            'cache_stats': cache_stats
        }

        # 8) Render
        rendered_html = render_template(
            'components/config-tab-content.html',
            config_data=config_data,
            # Dla kompatybilności z istniejącym szablonem:
            config_groups=config_groups_ns,   # <- PODSTAWIAMY wersję kropkową, żeby działał dot-access
            priority_configs=priority_configs,
            cache_stats=cache_stats
        )

        return jsonify({
            'success': True,
            'html': rendered_html,
            'data': config_data,
            'last_updated': get_local_now().isoformat()
        })

    except Exception as e:
        logger.error("Błąd AJAX config-tab-content", extra={
            'user_id': current_user.id,
            'error': str(e)
        })
        return jsonify({'success': False, 'error': str(e)}), 500

# 1. BULK OPERATIONS ENDPOINT
@api_bp.route('/products/bulk-action', methods=['POST'])
@login_required
def bulk_action():
    """
    POST /production/api/products/bulk-action
    
    Wykonuje masowe operacje na produktach
    
    Body (JSON):
    {
        "action": "update_status|update_priority|export|delete",
        "product_ids": [1, 2, 3, ...],
        "parameters": {
            "new_status": "czeka_na_wyciecie",
            "new_priority": 150,
            "export_format": "excel"
        }
    }
    
    Returns: JSON z rezultatem operacji
    """
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'Brak danych JSON'}), 400
        
        action = data.get('action')
        product_ids = data.get('product_ids', [])
        parameters = data.get('parameters', {})
        
        # Walidacja
        if not action or not product_ids:
            return jsonify({'success': False, 'error': 'Wymagane: action i product_ids'}), 400
        
        valid_actions = ['update_status', 'update_priority', 'export', 'delete']
        if action not in valid_actions:
            return jsonify({'success': False, 'error': f'Nieprawidłowa akcja. Dostępne: {valid_actions}'}), 400
        
        from ..models import ProductionItem
        
        # Pobierz produkty
        products = ProductionItem.query.filter(ProductionItem.id.in_(product_ids)).all()
        
        if not products:
            return jsonify({'success': False, 'error': 'Nie znaleziono produktów'}), 404
        
        results = {
            'success': True,
            'action': action,
            'processed_count': 0,
            'failed_count': 0,
            'errors': []
        }
        
        # Wykonaj akcję na każdym produkcie
        for product in products:
            try:
                if action == 'update_status':
                    new_status = parameters.get('new_status')
                    if new_status and hasattr(ProductionItem, 'current_status'):
                        product.current_status = new_status
                        results['processed_count'] += 1
                
                elif action == 'update_priority':
                    new_priority = parameters.get('new_priority')
                    if new_priority is not None:
                        product.priority_score = int(new_priority)
                        results['processed_count'] += 1
                
                elif action == 'delete':
                    # Tylko admin może usuwać
                    if not (hasattr(current_user, 'role') and current_user.role.lower() in ['admin', 'administrator']):
                        results['errors'].append(f'Brak uprawnień do usunięcia produktu {product.id}')
                        results['failed_count'] += 1
                        continue
                    
                    db.session.delete(product)
                    results['processed_count'] += 1
                
                elif action == 'export':
                    # Export będzie obsłużony w osobnym endpoincie
                    results['processed_count'] += 1
                
            except Exception as e:
                logger.error(f"Błąd bulk action dla produktu {product.id}", extra={'error': str(e)})
                results['errors'].append(f'Błąd produktu {product.id}: {str(e)}')
                results['failed_count'] += 1
        
        # Zapisz zmiany dla akcji modyfikujących
        if action in ['update_status', 'update_priority', 'delete']:
            db.session.commit()
        
        logger.info("Bulk action wykonana", extra={
            'user_id': current_user.id,
            'action': action,
            'product_count': len(product_ids),
            'processed': results['processed_count'],
            'failed': results['failed_count']
        })
        
        return jsonify(results)
        
    except Exception as e:
        db.session.rollback()
        logger.error("Błąd bulk action", extra={
            'user_id': current_user.id if current_user.is_authenticated else None,
            'error': str(e)
        })
        return jsonify({
            'success': False,
            'error': f'Błąd serwera: {str(e)}'
        }), 500


# 3. EXPORT PRODUKTÓW ENDPOINT
@api_bp.route('/products/export', methods=['POST'])
@login_required
def export_products():
    """
    POST /production/api/products/export
    
    Generuje export produktów w różnych formatach
    
    Body (JSON):
    {
        "format": "excel|csv|pdf",
        "product_ids": [1, 2, 3] | "all" | "filtered",
        "filters": {...},  // Jeśli product_ids == "filtered"
        "columns": ["id", "name", "status", ...]
    }
    
    Returns: JSON z URL do pobrania pliku
    """
    try:
        import io
        import csv
        from datetime import datetime
        from flask import send_file, make_response
        
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'Brak danych JSON'}), 400
        
        export_format = data.get('format', 'excel').lower()
        product_selection = data.get('product_ids', 'all')
        selected_columns = data.get('columns', [])
        filters = data.get('filters', {})
        
        # Walidacja formatu
        valid_formats = ['excel', 'csv', 'pdf']
        if export_format not in valid_formats:
            return jsonify({'success': False, 'error': f'Nieprawidłowy format. Dostępne: {valid_formats}'}), 400
        
        from ..models import ProductionItem
        
        # Buduj query na podstawie selekcji
        query = ProductionItem.query
        
        if isinstance(product_selection, list):
            # Konkretne IDs
            query = query.filter(ProductionItem.id.in_(product_selection))
        elif product_selection == "filtered":
            # Zastosuj filtry
            if filters.get('status'):
                query = query.filter(ProductionItem.current_status == filters['status'])
            if filters.get('search'):
                search_term = f"%{filters['search']}%"
                query = query.filter(
                    db.or_(
                        ProductionItem.short_product_id.ilike(search_term),
                        ProductionItem.original_product_name.ilike(search_term)
                    )
                )
        # "all" - bez dodatkowych filtrów
        
        products = query.all()
        
        if not products:
            return jsonify({'success': False, 'error': 'Brak produktów do eksportu'}), 404
        
        # Przygotuj dane do eksportu
        export_data = []
        for product in products:
            row = {
                'ID Produktu': product.short_product_id,
                'Zamówienie': product.internal_order_number,
                'Baselinker ID': product.baselinker_order_id,
                'Nazwa Produktu': product.original_product_name,
                'Status': product.current_status,
                'Priorytet': product.priority_score,
                'Deadline': product.deadline_date.strftime('%Y-%m-%d') if product.deadline_date else '',
                'Gatunek': product.parsed_wood_species or '',
                'Technologia': product.parsed_technology or '',
                'Klasa': product.parsed_wood_class or '',
                'Wymiary': f"{product.parsed_length_cm or 0}×{product.parsed_width_cm or 0}×{product.parsed_thickness_cm or 0}cm",
                'Objętość m³': product.volume_m3 or 0,
                'Cena netto': product.unit_price_net or 0,
                'Wartość całkowita': product.total_value_net or 0,
                'Data utworzenia': product.created_at.strftime('%Y-%m-%d %H:%M') if product.created_at else ''
            }
            
            # Filtruj kolumny jeśli określone
            if selected_columns:
                row = {k: v for k, v in row.items() if k in selected_columns}
            
            export_data.append(row)
        
        # Generuj plik na podstawie formatu
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        
        if export_format == 'csv':
            output = io.StringIO()
            if export_data:
                writer = csv.DictWriter(output, fieldnames=export_data[0].keys())
                writer.writeheader()
                writer.writerows(export_data)
            
            response = make_response(output.getvalue())
            response.headers['Content-Type'] = 'text/csv; charset=utf-8'
            response.headers['Content-Disposition'] = f'attachment; filename=produkty_{timestamp}.csv'
            
            logger.info("Export CSV wygenerowany", extra={
                'user_id': current_user.id,
                'products_count': len(products),
                'format': export_format
            })
            
            return response
        
        elif export_format == 'excel':
            # Dla Excel będziemy potrzebować pandas/openpyxl
            # Na razie zwrócimy CSV z odpowiednim Content-Type
            output = io.StringIO()
            if export_data:
                writer = csv.DictWriter(output, fieldnames=export_data[0].keys())
                writer.writeheader()
                writer.writerows(export_data)
            
            response = make_response(output.getvalue())
            response.headers['Content-Type'] = 'application/vnd.ms-excel'
            response.headers['Content-Disposition'] = f'attachment; filename=produkty_{timestamp}.xls'
            
            return response
        
        elif export_format == 'pdf':
            # PDF export będzie wymagał reportlab lub podobnej biblioteki
            # Na razie zwracamy błąd z informacją
            return jsonify({
                'success': False,
                'error': 'Export PDF będzie dostępny w przyszłej wersji'
            }), 501
        
    except Exception as e:
        logger.error("Błąd eksportu produktów", extra={
            'user_id': current_user.id if current_user.is_authenticated else None,
            'error': str(e)
        })
        return jsonify({
            'success': False,
            'error': f'Błąd eksportu: {str(e)}'
        }), 500


# 4. DANE FILTRÓW ENDPOINT
@api_bp.route('/products/filters-data', methods=['GET'])
@login_required
def get_filters_data():
    """
    GET /production/api/products/filters-data
    
    Zwraca unikalne wartości dla dropdownów filtrów
    
    Returns: JSON z listami unikalnych wartości
    """
    try:
        from ..models import ProductionItem
        from sqlalchemy import func, distinct
        
        # Pobierz unikalne wartości dla filtrów
        
        # Statusy - z enum w modelu
        statuses = [
            {'value': 'czeka_na_wyciecie', 'label': 'Czeka na wycięcie'},
            {'value': 'czeka_na_skladanie', 'label': 'Czeka na składanie'},
            {'value': 'czeka_na_pakowanie', 'label': 'Czeka na pakowanie'},
            {'value': 'spakowane', 'label': 'Spakowane'},
            {'value': 'wstrzymane', 'label': 'Wstrzymane'}
        ]
        
        # Gatunki drewna
        wood_species_query = db.session.query(distinct(ProductionItem.parsed_wood_species))\
                                      .filter(ProductionItem.parsed_wood_species.isnot(None))\
                                      .filter(ProductionItem.parsed_wood_species != '')\
                                      .all()
        wood_species = [{'value': item[0], 'label': item[0]} for item in wood_species_query]
        
        # Technologie
        technology_query = db.session.query(distinct(ProductionItem.parsed_technology))\
                                    .filter(ProductionItem.parsed_technology.isnot(None))\
                                    .filter(ProductionItem.parsed_technology != '')\
                                    .all()
        technologies = [{'value': item[0], 'label': item[0]} for item in technology_query]
        
        # Klasy drewna
        wood_class_query = db.session.query(distinct(ProductionItem.parsed_wood_class))\
                                    .filter(ProductionItem.parsed_wood_class.isnot(None))\
                                    .filter(ProductionItem.parsed_wood_class != '')\
                                    .all()
        wood_classes = [{'value': item[0], 'label': item[0]} for item in wood_class_query]
        
        # Zakres priorytetów
        priority_stats = db.session.query(
            func.min(ProductionItem.priority_score),
            func.max(ProductionItem.priority_score),
            func.avg(ProductionItem.priority_score)
        ).filter(ProductionItem.priority_score.isnot(None)).first()
        
        priority_range = {
            'min': int(priority_stats[0]) if priority_stats[0] else 0,
            'max': int(priority_stats[1]) if priority_stats[1] else 200,
            'avg': int(priority_stats[2]) if priority_stats[2] else 100
        }
        
        # Ostatnie 30 dni dla date picker
        from datetime import datetime, timedelta
        date_suggestions = {
            'today': datetime.now().date().isoformat(),
            'yesterday': (datetime.now() - timedelta(days=1)).date().isoformat(),
            'week_ago': (datetime.now() - timedelta(days=7)).date().isoformat(),
            'month_ago': (datetime.now() - timedelta(days=30)).date().isoformat()
        }
        
        filters_data = {
            'statuses': statuses,
            'wood_species': wood_species,
            'technologies': technologies,
            'wood_classes': wood_classes,
            'priority_range': priority_range,
            'date_suggestions': date_suggestions,
            'total_products': ProductionItem.query.count()
        }
        
        logger.info("Pobrano dane filtrów", extra={
            'user_id': current_user.id,
            'wood_species_count': len(wood_species),
            'technologies_count': len(technologies),
            'total_products': filters_data['total_products']
        })
        
        return jsonify({
            'success': True,
            'filters_data': filters_data
        })
        
    except Exception as e:
        logger.error("Błąd pobierania danych filtrów", extra={
            'user_id': current_user.id if current_user.is_authenticated else None,
            'error': str(e)
        })
        return jsonify({
            'success': False,
            'error': f'Błąd pobierania filtrów: {str(e)}'
        }), 500


# 5. UPDATE PRIORYTETU POJEDYNCZEGO PRODUKTU
@api_bp.route('/products/<int:product_id>/priority', methods=['PUT'])
@login_required
def update_single_product_priority(product_id):
    """
    PUT /production/api/products/<id>/priority
    
    Aktualizuje priorytet pojedynczego produktu - ZMODYFIKOWANY DLA priority_rank
    
    Body (JSON):
    {
        "priority": 5  // priority_rank (1,2,3,4... gdzie 1 = najwyższy)
    }
    
    Returns: JSON z rezultatem
    """
    try:
        data = request.get_json()
        if not data or 'priority' not in data:
            return jsonify({'success': False, 'error': 'Wymagany parametr: priority'}), 400
        
        new_priority = data['priority']
        
        # Walidacja priority_rank (1,2,3,4...)
        if not isinstance(new_priority, int) or new_priority < 1:
            return jsonify({'success': False, 'error': 'Priority rank musi być liczbą >= 1'}), 400
        
        from ..models import ProductionItem
        
        product = ProductionItem.query.get_or_404(product_id)
        old_priority = product.priority_rank
        
        # Używaj metody lock_priority() z modelu zamiast bezpośredniego ustawienia
        product.lock_priority(new_priority)
        db.session.commit()
        
        logger.info("Zaktualizowano priorytet produktu", extra={
            'user_id': current_user.id,
            'product_id': product_id,
            'product_short_id': product.short_product_id,
            'old_priority_rank': old_priority,
            'new_priority_rank': new_priority
        })
        
        return jsonify({
            'success': True,
            'message': 'Priorytet zaktualizowany',
            'product_id': product_id,
            'old_priority_rank': old_priority,
            'new_priority_rank': new_priority
        })
        
    except Exception as e:
        db.session.rollback()
        logger.error("Błąd aktualizacji priorytetu", extra={
            'user_id': current_user.id if current_user.is_authenticated else None,
            'product_id': product_id,
            'error': str(e)
        })
        return jsonify({
            'success': False,
            'error': f'Błąd aktualizacji priorytetu: {str(e)}'
        }), 500


@api_bp.route('/products-filtered', methods=['GET', 'POST'])
@login_required
def products_filtered():
    """
    API endpoint dla filtrowania produktów - ZMODYFIKOWANY DLA priority_rank
    """
    try:
        # Pobierz parametry filtrów
        status_filter = request.args.get('status', 'all')
        search_query = request.args.get('search', '').strip()
        page = int(request.args.get('page', 1))
        per_page = min(int(request.args.get('per_page', 50)), 200)
        # ZMIANA: domyślnie sortuj po priority_rank zamiast priority_score
        sort_by = request.args.get('sort_by', 'priority_rank')
        # ZMIANA: dla priority_rank używamy ASC (1,2,3...)
        default_order = 'asc' if sort_by == 'priority_rank' else 'desc'
        sort_order = request.args.get('sort_order', default_order)
        
        # Rozpocznij query od wszystkich produktów
        query = ProductionItem.query
        
        # Filtrowanie po statusie
        if status_filter and status_filter != 'all':
            query = query.filter(ProductionItem.current_status == status_filter)
        
        # Wyszukiwanie - bez zmian
        if search_query:
            search_pattern = f"%{search_query}%"
            search_conditions = []
            
            if hasattr(ProductionItem, 'original_product_name'):
                search_conditions.append(ProductionItem.original_product_name.ilike(search_pattern))
            if hasattr(ProductionItem, 'short_product_id'):
                search_conditions.append(ProductionItem.short_product_id.ilike(search_pattern))
            if hasattr(ProductionItem, 'internal_order_number'):
                search_conditions.append(ProductionItem.internal_order_number.ilike(search_pattern))
            if hasattr(ProductionItem, 'client_name'):
                search_conditions.append(ProductionItem.client_name.ilike(search_pattern))
            
            if search_conditions:
                query = query.filter(or_(*search_conditions))
        
        # ZMIANA: Sortowanie - priority_rank jako główne sortowanie
        sort_column = None
        if sort_by == 'priority_rank' and hasattr(ProductionItem, 'priority_rank'):
            sort_column = ProductionItem.priority_rank
        elif sort_by == 'priority_score' and hasattr(ProductionItem, 'priority_score'):
            # KOMPATYBILNOŚĆ: nadal obsługuj priority_score requests
            sort_column = ProductionItem.priority_score
        elif sort_by == 'deadline_date' and hasattr(ProductionItem, 'deadline_date'):
            sort_column = ProductionItem.deadline_date
        elif sort_by == 'created_at' and hasattr(ProductionItem, 'created_at'):
            sort_column = ProductionItem.created_at
        elif sort_by == 'short_product_id' and hasattr(ProductionItem, 'short_product_id'):
            sort_column = ProductionItem.short_product_id
        
        if sort_column is not None:
            if sort_order == 'desc':
                query = query.order_by(sort_column.desc())
            else:
                query = query.order_by(sort_column.asc())
        else:
            # ZMIANA: domyślne sortowanie po priority_rank ASC zamiast ID
            if hasattr(ProductionItem, 'priority_rank'):
                query = query.order_by(ProductionItem.priority_rank.asc())
            else:
                query = query.order_by(ProductionItem.id.desc())
        
        # Paginacja - bez zmian
        paginated = query.paginate(
            page=page,
            per_page=per_page,
            error_out=False
        )
        
        # ZMIANA: Przygotuj dane produktów - dodaj priority_rank do response
        products_data = []
        today = date.today()
        
        for item in paginated.items:
            # Oblicz dni do deadline
            days_to_deadline = None
            deadline_date = getattr(item, 'deadline_date', None)
            if deadline_date:
                days_to_deadline = (deadline_date - today).days
            
            # ZMIANA: dodaj priority_rank do danych
            product_data = {
                'id': item.id,
                'short_product_id': getattr(item, 'short_product_id', f'ID-{item.id}'),
                'internal_order_number': getattr(item, 'internal_order_number', ''),
                'product_name': getattr(item, 'original_product_name', getattr(item, 'product_name', 'Brak nazwy')),
                'client_name': getattr(item, 'client_name', ''),
                'current_status': getattr(item, 'current_status', 'unknown'),
                # ZMIANA: priority_rank jako główne pole priorytetów
                'priority_rank': getattr(item, 'priority_rank', None),
                # KOMPATYBILNOŚĆ: zachowaj priority_score dla starych klientów
                'priority_score': float(getattr(item, 'priority_score', 0) or 0),
                'volume_m3': float(getattr(item, 'volume_m3', 0) or 0),
                'total_value': float(getattr(item, 'total_value_net', getattr(item, 'total_value', 0)) or 0),
                'order_date': getattr(item, 'order_date', getattr(item, 'created_at', None)),
                'deadline_date': deadline_date.isoformat() if deadline_date else None,
                'days_to_deadline': days_to_deadline,
                'baselinker_order_id': getattr(item, 'baselinker_order_id', None),
                'created_at': getattr(item, 'created_at', None)
            }
            
            # Konwertuj daty na ISO string
            if product_data['order_date'] and hasattr(product_data['order_date'], 'isoformat'):
                product_data['order_date'] = product_data['order_date'].isoformat()
            if product_data['created_at'] and hasattr(product_data['created_at'], 'isoformat'):
                product_data['created_at'] = product_data['created_at'].isoformat()
            
            products_data.append(product_data)
        
        # ZMIANA: Statystyki oparte na priority_rank
        stats = {
            'total_filtered': paginated.total,
            'total_volume': sum(float(p['volume_m3']) for p in products_data),
            'total_value': sum(float(p['total_value']) for p in products_data),
            # ZMIANA: avg_priority_rank zamiast avg_priority_score
            'avg_priority_rank': sum(float(p['priority_rank'] or 0) for p in products_data) / len(products_data) if products_data else 0,
            # KOMPATYBILNOŚĆ: zachowaj dla starych dashboardów
            'avg_priority': sum(float(p['priority_score']) for p in products_data) / len(products_data) if products_data else 0,
            'overdue_count': len([p for p in products_data if p['days_to_deadline'] is not None and p['days_to_deadline'] < 0])
        }
        
        # Informacje o paginacji - bez zmian
        pagination_info = {
            'page': paginated.page,
            'per_page': paginated.per_page,
            'total': paginated.total,
            'pages': paginated.pages,
            'has_prev': paginated.has_prev,
            'has_next': paginated.has_next,
            'prev_num': paginated.prev_num,
            'next_num': paginated.next_num
        }
        
        return jsonify({
            'success': True,
            'products': products_data,
            'pagination': pagination_info,
            'stats': stats,
            'filters_applied': {
                'status': status_filter,
                'search': search_query,
                'sort_by': sort_by,
                'sort_order': sort_order
            }
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'Błąd filtrowania produktów: {str(e)}',
            'products': [],
            'pagination': {'page': 1, 'pages': 1, 'total': 0},
            'stats': {},
            'traceback': traceback.format_exc()
        }), 500


@api_bp.route('/update-priority', methods=['POST'])
@login_required
def update_priority():
    """
    API endpoint dla aktualizacji priorytetów produktów - ZMODYFIKOWANY
    
    Obsługuje oba formaty:
    - Stary: priority_score
    - Nowy: priority_rank (z drag & drop)
    """
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'Brak danych JSON'}), 400
        
        updated_products = []
        
        if 'products' in data:
            # ZMIANA: Batch update dla drag & drop (używa priority_rank)
            products_data = data.get('products', [])
            
            for product_data in products_data:
                product_id = product_data.get('id')
                # ZMIANA: obsłuż zarówno priority_rank jak i priority (kompatybilność)
                new_priority_rank = product_data.get('priority_rank')
                new_priority_score = product_data.get('priority')  # fallback
                
                if product_id is None:
                    continue
                
                product = ProductionItem.query.get(product_id)
                if product:
                    # ZMIANA: priorytet dla priority_rank
                    if new_priority_rank is not None:
                        product.priority_rank = new_priority_rank
                        product.priority_manual_override = True  # Drag&drop = manual
                        updated_products.append({
                            'id': product_id, 
                            'new_priority_rank': new_priority_rank
                        })
                    # KOMPATYBILNOŚĆ: stary system priority_score
                    elif new_priority_score is not None and hasattr(product, 'priority_score'):
                        product.priority_score = new_priority_score
                        updated_products.append({
                            'id': product_id, 
                            'new_priority': new_priority_score
                        })
        
        elif 'product_id' in data:
            # Pojedynczy produkt - zachowaj istniejącą logikę
            product_id = data.get('product_id')
            new_priority = data.get('new_priority')
            
            if product_id is None or new_priority is None:
                return jsonify({'success': False, 'error': 'Wymagane: product_id i new_priority'}), 400
            
            product = ProductionItem.query.get(product_id)
            if not product:
                return jsonify({'success': False, 'error': f'Produkt {product_id} nie znaleziony'}), 404
            
            if hasattr(product, 'priority_score'):
                product.priority_score = new_priority
                updated_products.append({'id': product_id, 'new_priority': new_priority})
        
        else:
            return jsonify({'success': False, 'error': 'Wymagane: product_id+new_priority LUB products'}), 400
        
        # Zapisz zmiany
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': f'Zaktualizowano priorytety {len(updated_products)} produktów',
            'updated_count': len(updated_products),
            'updated_products': updated_products
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'error': f'Błąd aktualizacji priorytetów: {str(e)}'
        }), 500

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def calculate_duration(start_time, end_time):
    """
    Oblicza czas trwania między dwoma timestampami
    
    Args:
        start_time: datetime początkowy
        end_time: datetime końcowy (może być None)
    
    Returns:
        dict: {'hours': int, 'minutes': int, 'total_minutes': int}
    """
    if not start_time:
        return None
    
    if not end_time:
        end_time = get_local_now()
    
    duration = end_time - start_time
    total_minutes = int(duration.total_seconds() / 60)
    hours = total_minutes // 60
    minutes = total_minutes % 60
    
    return {
        'hours': hours,
        'minutes': minutes,
        'total_minutes': total_minutes,
        'formatted': f"{hours}h {minutes}m"
    }

# ============================================================================
# POBIERANIE ZAMÓWIEŃ MODAL PRODUCTION - PANEL ZARZĄDZANIA
# ============================================================================

@api_bp.route('/baselinker_statuses', methods=['GET'])
@login_required
def baselinker_statuses():
    """
    GET /api/baselinker_statuses - Pobieranie statusów Baselinker z cache
    
    Endpoint dla nowego modalu synchronizacji - pobiera statusy z Baselinker API
    z 7-dniowym cache w tabeli prod_config.
    
    Workflow:
    1. Sprawdź cache w prod_config (klucz: baselinker_statuses_cache)
    2. Jeśli cache ważny (< 7 dni) - zwróć dane z cache
    3. Jeśli cache przedawniony - pobierz z API i zapisz do cache
    4. W przypadku błędu API - zwróć fallback statusy
    
    Cache structure w prod_config:
    - key: 'baselinker_statuses_cache' 
    - value: JSON z listą statusów + timestamp
    - type: 'json'
    
    Returns:
        JSON: {
            'success': True,
            'statuses': [{'id': int, 'name': str}, ...],
            'cached': bool,
            'cache_age_hours': float
        }
    """
    try:
        logger.info("API: Pobieranie statusów Baselinker z cache", extra={
            'user_id': current_user.id,
            'endpoint': 'baselinker_statuses'
        })
        
        # Użyj dedykowanego serwisu cache statusów
        from ..services.baselinker_status_service import get_baselinker_statuses
        
        statuses, cached, cache_age_hours = get_baselinker_statuses(user_id=current_user.id)
        
        logger.info("API: Zwrócono statusy Baselinker", extra={
            'statuses_count': len(statuses),
            'cached': cached,
            'cache_age_hours': round(cache_age_hours, 2),
            'user_id': current_user.id
        })
        
        return jsonify({
            'success': True,
            'statuses': statuses,
            'cached': cached,
            'cache_age_hours': round(cache_age_hours, 2),
            'count': len(statuses),
            'cache_info': {
                'ttl_days': 7,
                'expired': cache_age_hours >= (7 * 24) if cache_age_hours else None,
                'last_refresh': 'just_now' if not cached else f'{cache_age_hours:.1f}h ago'
            }
        }), 200
        
    except Exception as e:
        logger.error("API: Błąd endpoint baselinker_statuses", extra={
            'user_id': current_user.id,
            'error': str(e),
            'traceback': traceback.format_exc()
        })
        
        # Fallback w przypadku błędu
        fallback_statuses = [
            {'id': 138618, 'name': 'W produkcji'},
            {'id': 138619, 'name': 'Gotowe'},
            {'id': 138623, 'name': 'Spakowane'},
            {'id': 155824, 'name': 'Nowe - opłacone'}
        ]
        
        return jsonify({
            'success': False,
            'error': str(e),
            'fallback_statuses': fallback_statuses,
            'cached': False,
            'cache_age_hours': 0
        }), 500


@api_bp.route('/get_config_days_range', methods=['GET'])
@login_required 
def get_config_days_range():
    """
    GET /api/get_config_days_range - Pobieranie zakresu dni synchronizacji z konfiguracji
    
    Endpoint dla nowego modalu synchronizacji - pobiera skonfigurowany zakres dni
    z tabeli prod_config (klucz: 'baselinker_sync_days_range').
    
    Returns:
        JSON: {
            'success': True,
            'days_range': int,
            'source': 'config'|'default'
        }
    """
    try:
        logger.info("API: Pobieranie zakresu dni synchronizacji", extra={
            'user_id': current_user.id,
            'endpoint': 'get_config_days_range'
        })
        
        from ..services.config_service import ProductionConfigService
        config_service = ProductionConfigService()
        
        # Pobierz zakres dni z konfiguracji (domyślnie 7)
        days_range = config_service.get_config('baselinker_sync_days_range', default=7)
        
        # Konwertuj na int jeśli to string
        if isinstance(days_range, str):
            try:
                days_range = int(days_range)
            except ValueError:
                days_range = 7
        
        # Walidacja zakresu (1-30 dni)
        if not isinstance(days_range, int) or days_range < 1 or days_range > 30:
            logger.warning("API: Nieprawidłowy zakres dni w config", extra={
                'days_range': days_range,
                'user_id': current_user.id
            })
            days_range = 7
            source = 'default'
        else:
            source = 'config'
        
        logger.info("API: Zwrócono zakres dni", extra={
            'days_range': days_range,
            'source': source,
            'user_id': current_user.id
        })
        
        return jsonify({
            'success': True,
            'days_range': days_range,
            'source': source
        }), 200
        
    except Exception as e:
        logger.error("API: Błąd endpoint get_config_days_range", extra={
            'user_id': current_user.id,
            'error': str(e),
            'traceback': traceback.format_exc()
        })
        
        return jsonify({
            'success': True,  # Nie blokuj UI - zwróć domyślną wartość
            'days_range': 7,
            'source': 'fallback',
            'error': str(e)
        }), 200


@api_bp.route('/fetch_orders_preview', methods=['POST'])
@login_required
def fetch_orders_preview():
    """
    POST /api/fetch_orders_preview - Pobieranie zamówień bez zapisu (preview)
    
    Endpoint dla nowego modalu synchronizacji - pobiera zamówienia z Baselinker
    bez zapisywania ich do bazy danych. Służy do preview listy zamówień.
    
    Body:
    {
        "days_range": int,        # Zakres dni wstecz (1-30)
        "status_ids": [int, ...]  # Lista ID statusów do pobrania
    }
    
    Returns:
        JSON: {
            'success': True,
            'orders': [...],         # Lista zamówień
            'pages_processed': int,  # Ilość stron API
            'total_count': int,      # Łączna liczba zamówień
            'filtered_count': int    # Liczba zamówień po filtrowaniu
        }
    """
    try:
        data = request.get_json() or {}
        days_range = data.get('days_range', 7)
        status_ids = data.get('status_ids', [])
        
        logger.info("API: Pobieranie zamówień preview", extra={
            'user_id': current_user.id,
            'days_range': days_range,
            'status_ids': status_ids,
            'endpoint': 'fetch_orders_preview'
        })
        
        # Walidacja parametrów
        if not isinstance(days_range, int) or days_range < 1 or days_range > 30:
            return jsonify({
                'success': False,
                'error': 'days_range musi być liczbą między 1 a 30'
            }), 400
            
        if not isinstance(status_ids, list) or len(status_ids) == 0:
            return jsonify({
                'success': False,
                'error': 'status_ids musi być niepustą listą'
            }), 400
        
        # Konwersja dat
        date_to = get_local_now()
        date_from = date_to - timedelta(days=days_range)
        
        logger.info("API: Zakres dat pobierania", extra={
            'date_from': date_from.isoformat(),
            'date_to': date_to.isoformat(),
            'days_range': days_range
        })
        
        # Użyj serwisu z modułu reports dla spójności
        from modules.reports.service import get_reports_service
        reports_service = get_reports_service()
        
        if not reports_service:
            raise Exception('Nie można zainicjować serwisu raportów Baselinker')
        
        # Pobierz zamówienia z Baselinker (bez zapisu)
        fetch_result = reports_service.fetch_orders_from_date_range(
            date_from=date_from,
            date_to=date_to,
            get_all_statuses=True,  # Pobierz wszystkie statusy, przefiltrujemy później
            limit_per_page=100      # Standardowy limit
        )
        
        if not fetch_result.get('success'):
            raise Exception(fetch_result.get('error', 'Nie udało się pobrać zamówień z Baselinker'))
        
        all_orders = fetch_result.get('orders', []) or []
        pages_processed = fetch_result.get('pages_processed') or 0
        
        # Filtruj zamówienia po statusach
        status_ids_set = set(status_ids)
        filtered_orders = []
        
        for order in all_orders:
            order_status = order.get('order_status_id') or order.get('status_id')
            if order_status in status_ids_set:
                # Dodaj dodatkowe pola dla frontendu
                order['id'] = order.get('order_id')
                order['customer_name'] = order.get('delivery_fullname') or order.get('buyer_name') or 'Brak nazwy'
                order['baselinker_order_id'] = order.get('order_id')
                order['status_id'] = order_status
                order['order_date'] = order.get('date_add')
                
                # Przetwórz produkty
                if 'products' in order and order['products']:
                    processed_products = []
                    for product in order['products']:
                        processed_products.append({
                            'name': product.get('name', 'Bez nazwy'),
                            'sku': product.get('sku', ''),
                            'variant': product.get('variant', ''),
                            'quantity': float(product.get('quantity', 0)),
                            'price': float(product.get('price_brutto', 0)),
                            'unit': product.get('unit', 'szt.')
                        })
                    order['products'] = processed_products
                
                filtered_orders.append(order)
        
        logger.info("API: Zamówienia pobrane pomyślnie", extra={
            'total_orders': len(all_orders),
            'filtered_orders': len(filtered_orders),
            'pages_processed': pages_processed,
            'user_id': current_user.id
        })
        
        return jsonify({
            'success': True,
            'orders': filtered_orders,
            'pages_processed': pages_processed,
            'total_count': len(all_orders),
            'filtered_count': len(filtered_orders),
            'date_range': {
                'from': date_from.isoformat(),
                'to': date_to.isoformat(),
                'days': days_range
            }
        }), 200
        
    except Exception as e:
        logger.error("API: Błąd endpoint fetch_orders_preview", extra={
            'user_id': current_user.id,
            'error': str(e),
            'traceback': traceback.format_exc(),
            'request_data': data if 'data' in locals() else None
        })
        
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@api_bp.route('/save_selected_orders', methods=['POST'])
@login_required
def save_selected_orders():
    """
    POST /production/api/save_selected_orders - Zapis wybranych zamówień do produkcji
    
    NAPRAWIONO:
    - Endpoint dostępny z podkreślnikami w URL
    - Dostępny dla wszystkich zalogowanych użytkowników (nie tylko admin)
    - Proper error handling
    """
    try:
        data = request.get_json() or {}
        order_ids = data.get('order_ids', [])
        days_range = data.get('days_range', 7)
        status_ids = data.get('status_ids', [])
        
        logger.info("API: Zapis wybranych zamówień", extra={
            'user_id': current_user.id,
            'order_ids': order_ids,
            'order_count': len(order_ids),
            'days_range': days_range,
            'status_ids': status_ids,
            'endpoint': 'save_selected_orders'
        })
        
        # Walidacja parametrów
        if not isinstance(order_ids, list) or len(order_ids) == 0:
            return jsonify({
                'success': False,
                'error': 'order_ids musi być niepustą listą'
            }), 400
            
        if len(order_ids) > 100:
            return jsonify({
                'success': False,
                'error': 'Maksymalnie 100 zamówień na raz'
            }), 400
        
        # Sprawdź czy sync service jest dostępny
        try:
            from ..services.sync_service import manual_sync_with_filtering, get_sync_service
            
            # Test czy serwis się inicjalizuje
            sync_service_test = get_sync_service()
            if not sync_service_test:
                logger.error("API: Sync service niedostępny", extra={
                    'user_id': current_user.id,
                    'order_ids': order_ids
                })
                return jsonify({
                    'success': False,
                    'error': 'Serwis synchronizacji jest obecnie niedostępny',
                    'orders_created': 0,
                    'products_created': 0,
                    'products_skipped': 0,
                    'summary': 'Synchronizacja niemożliwa - serwis niedostępny'
                }), 503
            
        except ImportError as import_error:
            logger.error("API: Import error sync service", extra={
                'user_id': current_user.id,
                'error': str(import_error)
            })
            return jsonify({
                'success': False,
                'error': 'Błąd wewnętrzny - nie można załadować serwisu synchronizacji',
                'orders_created': 0,
                'products_created': 0,
                'products_skipped': 0,
                'summary': 'Synchronizacja niemożliwa - błąd systemu'
            }), 500

        # Przygotuj payload dla sync service  
        sync_payload = {
            'target_statuses': status_ids,
            'period_days': days_range,
            'limit_per_page': 100,
            'dry_run': False,
            'force_update': True,
            'debug_mode': False,
            'skip_validation': False,
            'filter_order_ids': order_ids,  # Lista wybranych zamówień
            'selected_orders_only': True,   # Flaga dla sync service
            'auto_status_change': True,     # Zmiana statusu po zapisaniu
            'recalculate_priorities': True  # Przelicz priorytety
        }

        logger.info("API: Wywołanie manual_sync_with_filtering", extra={
            'sync_payload': sync_payload,
            'user_id': current_user.id,
            'sync_service_available': True
        })
        
        # Wywołaj synchronizację
        try:
            sync_result = manual_sync_with_filtering(sync_payload)
        except Exception as sync_exception:
            logger.error("API: Exception podczas manual_sync_with_filtering", extra={
                'user_id': current_user.id,
                'sync_payload': sync_payload,
                'exception': str(sync_exception)
            })
            return jsonify({
                'success': False,
                'error': f'Błąd wywołania synchronizacji: {str(sync_exception)}',
                'orders_created': 0,
                'products_created': 0,
                'products_skipped': 0,
                'summary': 'Synchronizacja nie została wykonana z powodu błędu'
            }), 500

        # ROZSZERZONE sprawdzanie sync_result
        if sync_result is None:
            logger.error("API: sync_result is None", extra={
                'user_id': current_user.id,
                'sync_payload': sync_payload
            })
            return jsonify({
                'success': False,
                'error': 'Błąd synchronizacji - serwis zwrócił None',
                'orders_created': 0,
                'products_created': 0,
                'products_skipped': 0,
                'summary': 'Synchronizacja nie została wykonana'
            }), 500

        # Sprawdź czy sync_result jest dictem
        if not isinstance(sync_result, dict):
            logger.error("API: sync_result nie jest dict", extra={
                'user_id': current_user.id,
                'sync_result_type': type(sync_result).__name__,
                'sync_result_str': str(sync_result)[:200]
            })
            return jsonify({
                'success': False,
                'error': f'Błąd synchronizacji - nieprawidłowy typ wyniku: {type(sync_result).__name__}',
                'orders_created': 0,
                'products_created': 0,
                'products_skipped': 0,
                'summary': 'Synchronizacja zwróciła nieprawidłowy wynik'
            }), 500

        # Sprawdź czy ma wymagane pola
        if 'success' not in sync_result:
            logger.error("API: sync_result brak pola 'success'", extra={
                'user_id': current_user.id,
                'sync_result_keys': list(sync_result.keys()),
                'sync_result': str(sync_result)[:300]
            })
            return jsonify({
                'success': False,
                'error': 'Błąd synchronizacji - wynik nie zawiera pola success',
                'orders_created': 0,
                'products_created': 0,
                'products_skipped': 0,
                'summary': 'Synchronizacja zwróciła niepełny wynik'
            }), 500
        
        # Bezpieczne pobieranie wyników z poprawionej struktury
        success = sync_result.get('success', False)
        data_section = sync_result.get('data', {})
        stats_section = data_section.get('stats', {}) if isinstance(data_section, dict) else {}

        # Dodatkowe sprawdzenie - jeśli stats_section jest puste, spróbuj bezpośrednio z sync_result
        if not stats_section and isinstance(sync_result, dict):
            # Fallback - niektóre funkcje mogą zwracać stats bezpośrednio
            for key in ['products_created', 'products_skipped', 'orders_processed']:
                if key in sync_result:
                    stats_section[key] = sync_result[key]

        logger.info("API: Parsowanie sync_result", extra={
            'user_id': current_user.id,
            'success': success,
            'stats_section': stats_section,
            'data_section_keys': list(data_section.keys()) if data_section else []
        })

        if success:
            products_created = stats_section.get('products_created', 0)
            products_skipped = stats_section.get('products_skipped', 0) 
            orders_processed = stats_section.get('orders_processed', 0)
            
            response_data = {
                'success': True,
                'orders_created': len(order_ids),  # Liczba wybranych zamówień
                'products_created': products_created,
                'products_skipped': products_skipped,
                'orders_processed': orders_processed,
                'status_changes': orders_processed,  # Status zmieniany dla przetworzonych zamówień
                'summary': f'Przetworzono {orders_processed} z {len(order_ids)} wybranych zamówień, utworzono {products_created} produktów'
            }
            
            logger.info("API: save_selected_orders sukces", extra={
                'user_id': current_user.id,
                'response_data': response_data
            })
            
            return jsonify(response_data), 200
        else:
            error_message = sync_result.get('error', 'Nieznany błąd synchronizacji')
            
            logger.error("API: save_selected_orders błąd", extra={
                'user_id': current_user.id,
                'error': error_message,
                'sync_result': sync_result
            })
            
            return jsonify({
                'success': False,
                'error': error_message,
                'orders_created': 0,
                'products_created': 0,
                'products_skipped': 0,
                'summary': f'Błąd przetwarzania zamówień: {error_message}'
            }), 500
        
    except Exception as e:
        logger.error("API: Błąd endpoint save_selected_orders", extra={
            'user_id': current_user.id,
            'error': str(e),
            'traceback': traceback.format_exc(),
            'request_data': data if 'data' in locals() else 'unknown'
        })
        
        return jsonify({
            'success': False,
            'error': str(e),
            'orders_created': 0,
            'products_created': 0,
            'products_skipped': 0,
            'summary': 'Wystąpił błąd podczas przetwarzania zamówień'
        }), 500


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
        
        from ..models import ProductionItem, ProductionError
        
        # Pobierz dane stacji produkcyjnych
        stations_data = []
        
        # Stacja wycinania
        cutting_count = ProductionItem.query.filter(
            ProductionItem.current_status == 'czeka_na_wyciecie'
        ).count()
        
        stations_data.append({
            'code': 'cutting',
            'name': 'Wycinanie',
            'status': 'active' if cutting_count > 0 else 'idle',
            'status_class': 'station-active' if cutting_count > 0 else 'station-idle',
            'active_orders': cutting_count
        })
        
        # Stacja składania
        assembly_count = ProductionItem.query.filter(
            ProductionItem.current_status == 'czeka_na_skladanie'
        ).count()
        
        stations_data.append({
            'code': 'assembly', 
            'name': 'Składanie',
            'status': 'active' if assembly_count > 0 else 'idle',
            'status_class': 'station-active' if assembly_count > 0 else 'station-idle',
            'active_orders': assembly_count
        })
        
        # Stacja pakowania
        packaging_count = ProductionItem.query.filter(
            ProductionItem.current_status == 'czeka_na_pakowanie'
        ).count()
        
        stations_data.append({
            'code': 'packaging',
            'name': 'Pakowanie', 
            'status': 'active' if packaging_count > 0 else 'idle',
            'status_class': 'station-active' if packaging_count > 0 else 'station-idle',
            'active_orders': packaging_count
        })
        
        # Alerty systemowe
        alerts_data = []
        
        # Sprawdź błędy z ostatnich 24h
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
        
        # Sprawdź opóźnione zamówienia
        today = date.today()
        deadline_alerts = ProductionItem.query.filter(
            ProductionItem.deadline_date <= (today + timedelta(days=3)),
            ProductionItem.current_status != 'spakowane'
        ).order_by(ProductionItem.deadline_date.asc()).limit(10).all()
        
        alerts_data = [
            {
                'short_product_id': alert.short_product_id,
                'deadline_date': alert.deadline_date.isoformat() if alert.deadline_date else None,
                'days_remaining': (alert.deadline_date - today).days if alert.deadline_date else 0,
                'current_station': alert.current_status.replace('czeka_na_', '') if alert.current_status else 'unknown'
            }
            for alert in deadline_alerts
        ]
        
        # Zwróć dane w formacie JSON
        response_data = {
            'stations': stations_data,
            'alerts': alerts_data,  # ZMIENIONA STRUKTURA
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
        
        from ..models import ProductionItem, ProductionSyncLog
        
        # Sprawdź aktywność produkcji
        active_orders = ProductionItem.query.filter(
            ProductionItem.current_status.in_([
                'czeka_na_wyciecie',
                'czeka_na_skladanie', 
                'czeka_na_pakowanie'
            ])
        ).count()
        
        # Sprawdź ostatnią synchronizację
        last_sync = ProductionSyncLog.query.order_by(
            ProductionSyncLog.sync_started_at.desc()
        ).first()
        
        # Określ status systemu
        if active_orders > 0:
            status = 'active'
            status_text = f'Produkcja aktywna ({active_orders} zamówień)'
            indicator_class = 'status-active'
        else:
            status = 'idle'
            status_text = 'Produkcja w trybie oczekiwania'
            indicator_class = 'status-idle'
        
        # Sprawdź czy są problemy synchronizacji
        if last_sync:
            sync_age_hours = (get_local_now() - last_sync.sync_started_at).total_seconds() / 3600
            if sync_age_hours > 2:  # Jeśli ostatnia sync była > 2h temu
                status = 'warning'
                status_text = 'Problemy z synchronizacją'
                indicator_class = 'status-warning'
        
        # Przygotuj odpowiedź
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
        
        from ..models import ProductionItem, ProductionError
        
        today = date.today()
        today_start = datetime.combine(today, datetime.min.time())
        today_end = datetime.combine(today, datetime.max.time())
        
        # === DEBUGGING COMPLETED TODAY ===
        logger.debug("=== DEBUGGING COMPLETED TODAY ===")
        
        # Sprawdź wszystkie statusy
        all_statuses = db.session.query(
            ProductionItem.current_status, 
            db.func.count(ProductionItem.id)
        ).group_by(ProductionItem.current_status).all()
        
        logger.debug(f"Wszystkie statusy w bazie: {all_statuses}")
        
        # Sprawdź czy pole packaging_completed_at istnieje i ma dane
        try:
            test_packaging = ProductionItem.query.filter(
                ProductionItem.packaging_completed_at.isnot(None)
            ).limit(5).all()
            logger.debug(f"Znaleziono {len(test_packaging)} rekordów z packaging_completed_at")
            
            for item in test_packaging:
                logger.debug(f"Item {item.id}: packaging_completed_at={item.packaging_completed_at}")
        except Exception as e:
            logger.debug(f"Błąd packaging_completed_at: {e}")
        
        # Sprawdź alternatywne pola dat
        try:
            spakowane_items = ProductionItem.query.filter(
                ProductionItem.current_status == 'spakowane'
            ).limit(5).all()
            logger.debug(f"Znaleziono {len(spakowane_items)} rekordów ze statusem 'spakowane'")
            
            for item in spakowane_items:
                # Sprawdź wszystkie możliwe pola dat
                created_at = getattr(item, 'created_at', None)
                updated_at = getattr(item, 'updated_at', None)
                packaging_completed_at = getattr(item, 'packaging_completed_at', None)
                
                logger.debug(f"Item {item.id}: status={item.current_status}, created_at={created_at}, updated_at={updated_at}, packaging_completed_at={packaging_completed_at}")
        except Exception as e:
            logger.debug(f"Błąd sprawdzania statusów: {e}")
        
        # Całkowita liczba zamówień w systemie
        total_orders = ProductionItem.query.count()
        
        # ORYGINALNA LOGIKA - zamówienia ukończone dzisiaj
        completed_today_original = ProductionItem.query.filter(
            ProductionItem.current_status == 'spakowane',
            ProductionItem.packaging_completed_at >= today_start,
            ProductionItem.packaging_completed_at <= today_end
        ).count()
        
        # ALTERNATYWNA LOGIKA - wszystkie spakowane (bez filtra daty)
        completed_today_alternative = ProductionItem.query.filter(
            ProductionItem.current_status == 'spakowane'
        ).count()
        
        # ALTERNATYWNA LOGIKA 2 - używając updated_at zamiast packaging_completed_at
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
        
        # Użyj alternatywnej logiki jeśli oryginalna zwraca 0
        if completed_today_original == 0 and completed_today_alternative > 0:
            logger.warning("Używam alternatywnej logiki - brak packaging_completed_at lub problem z datami")
            completed_today = completed_today_updated_at if completed_today_updated_at > 0 else completed_today_alternative
        else:
            completed_today = completed_today_original
        
        # Zamówienia priorytetowe oczekujące
        pending_priority = ProductionItem.query.filter(
            ProductionItem.current_status.in_([
                'czeka_na_wyciecie',
                'czeka_na_skladanie', 
                'czeka_na_pakowanie'
            ])
        ).filter(
            ProductionItem.deadline_date <= (today + timedelta(days=3))
        ).count()
        
        # Błędy z ostatnich 24h
        errors_24h = ProductionError.query.filter(
            ProductionError.error_occurred_at >= (get_local_now() - timedelta(hours=24)),
            ProductionError.is_resolved == False
        ).count()
        
        # Łączna objętość dzisiaj ukończona
        total_volume_today = 0.0
        try:
            if completed_today_original > 0:
                # Użyj oryginalnej logiki jeśli działa
                volume_result = db.session.query(
                    db.func.coalesce(db.func.sum(ProductionItem.volume_m3), 0)
                ).filter(
                    ProductionItem.current_status == 'spakowane',
                    ProductionItem.packaging_completed_at >= today_start,
                    ProductionItem.packaging_completed_at <= today_end
                ).scalar()
            else:
                # Użyj alternatywnej logiki
                volume_result = db.session.query(
                    db.func.coalesce(db.func.sum(ProductionItem.volume_m3), 0)
                ).filter(
                    ProductionItem.current_status == 'spakowane'
                ).scalar()
            
            total_volume_today = float(volume_result) if volume_result else 0.0
            
        except Exception as volume_error:
            logger.warning("Nie udało się pobrać volume_m3", extra={'error': str(volume_error)})
            total_volume_today = 0.0
        
        # Przygotuj statystyki
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


@api_bp.route('/products/<int:product_id>/notes', methods=['PUT'])
@login_required
def update_product_notes(product_id):
    """
    PUT /production/api/products/<id>/notes
    
    Aktualizuje notatki produkcyjne dla produktu
    
    Body JSON:
    {
        "notes": "Nowa treść notatki"
    }
    
    Returns: JSON z rezultatem operacji
    """
    try:
        from ..models import ProductionItem
        
        # Pobierz dane z request
        data = request.get_json()
        if not data:
            return jsonify({
                'success': False, 
                'error': 'Brak danych JSON'
            }), 400
        
        new_notes = data.get('notes', '').strip()
        
        # Znajdź produkt
        product = ProductionItem.query.get_or_404(product_id)
        
        # Zapisz stare notatki dla logowania
        old_notes = product.production_notes or ''
        
        # Aktualizuj notatki
        product.production_notes = new_notes
        product.updated_at = get_local_now()
        
        db.session.commit()
        
        logger.info("API: Zaktualizowano notatki produktu", extra={
            'product_id': product_id,
            'short_product_id': product.short_product_id,
            'user_id': current_user.id,
            'old_notes_length': len(old_notes),
            'new_notes_length': len(new_notes),
            'client_ip': request.remote_addr
        })
        
        return jsonify({
            'success': True,
            'message': 'Notatki zostały zaktualizowane',
            'data': {
                'product_id': product_id,
                'short_product_id': product.short_product_id,
                'notes': new_notes,
                'updated_at': product.updated_at.isoformat()
            }
        }), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error("API: Błąd aktualizacji notatek", extra={
            'product_id': product_id,
            'user_id': current_user.id,
            'error': str(e),
            'client_ip': request.remote_addr
        })
        
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@api_bp.route('/products/<int:product_id>/order-products', methods=['GET'])
@login_required  
def get_order_products(product_id):
    """
    GET /production/api/products/<id>/order-products
    
    Zwraca wszystkie produkty z tego samego zamówienia Baselinker
    dla paska produktów w modal
    
    Returns: JSON z listą produktów z zamówienia
    """
    try:
        from ..models import ProductionItem
        
        # Znajdź produkt
        product = ProductionItem.query.get_or_404(product_id)
        
        if not product.baselinker_order_id:
            return jsonify({
                'success': True,
                'products': [_format_product_for_navigation(product)],
                'total_count': 1,
                'current_product_id': product_id
            }), 200
        
        # Znajdź wszystkie produkty z tego zamówienia
        order_products = ProductionItem.query.filter_by(
            baselinker_order_id=product.baselinker_order_id
        ).order_by(ProductionItem.product_sequence_in_order.asc()).all()
        
        # Formatuj produkty dla nawigacji
        formatted_products = []
        for p in order_products:
            formatted_products.append(_format_product_for_navigation(p))
        
        logger.info("API: Pobrano produkty zamówienia", extra={
            'product_id': product_id,
            'baselinker_order_id': product.baselinker_order_id,
            'products_count': len(formatted_products),
            'user_id': current_user.id
        })
        
        return jsonify({
            'success': True,
            'products': formatted_products,
            'total_count': len(formatted_products),
            'current_product_id': product_id,
            'baselinker_order_id': product.baselinker_order_id
        }), 200
        
    except Exception as e:
        logger.error("API: Błąd pobierania produktów zamówienia", extra={
            'product_id': product_id,
            'user_id': current_user.id,
            'error': str(e)
        })
        
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


def _format_product_for_navigation(product):
    """
    Formatuje produkt dla nawigacji w modal (pasek produktów)
    
    Format: [Gatunek] [Technologia] [Klasa] [Wymiary] [Wykończenie]
    """
    # Buduj specyfikację produktu
    spec_parts = []
    
    # Gatunek drewna
    if product.parsed_wood_species:
        spec_parts.append(product.parsed_wood_species)
    
    # Technologia
    if product.parsed_technology:
        spec_parts.append(product.parsed_technology)
    
    # Klasa drewna
    if product.parsed_wood_class:
        spec_parts.append(product.parsed_wood_class)
    
    # Wymiary
    dimensions = []
    if product.parsed_width_cm:
        dimensions.append(f"{int(product.parsed_width_cm)}")
    if product.parsed_thickness_cm:
        dimensions.append(f"{int(product.parsed_thickness_cm)}")
    if product.parsed_length_cm:
        dimensions.append(f"{int(product.parsed_length_cm)}")
    
    if dimensions:
        spec_parts.append("×".join(dimensions))
    
    # Wykończenie
    if product.parsed_finish_state:
        spec_parts.append(product.parsed_finish_state)
    
    # Połącz specyfikację
    specification = " ".join(spec_parts) if spec_parts else product.original_product_name
    
    return {
        'id': product.id,
        'short_product_id': product.short_product_id,
        'specification': specification,
        'sequence': product.product_sequence_in_order,
        'status': product.current_status,
        'priority': product.priority_score or 100
    }


logger.info("Zainicjalizowano API routers modułu production", extra={
    'blueprint_name': api_bp.name,
    'total_endpoints': 7,  # dashboard-stats, complete-task, cron-sync, manual-sync, update-config, health, complete-packaging
    'prd_compliance': True
})

# ============================================================================
# API ROUTERS - NOWE ENDPOINTY - ENHANCED PRIORITY SYSTEM
# ============================================================================

@api_bp.route('/recalculate-all-priorities', methods=['POST'])
@login_required
def reset_all_priorities():
    """
    POST /api/recalculate-all-priorities - Reset wszystkich priorytetów
    
    Endpoint dla admina do resetowania wszystkich priorytetów (przycisk w UI).
    Ustawia priority_manual_override = FALSE dla wszystkich produktów
    i wywołuje pełne przeliczenie priorytetów.
    
    Body (opcjonalny):
    {
        "confirm_reset": true  // Potwierdzenie operacji (wymagane)
    }
    
    Autoryzacja: admin
    Returns: JSON z szczegółowym raportem przeliczenia
    """
    try:
        data = request.get_json() or {}
        confirm_reset = data.get('confirm_reset', False)
        
        # Wymagaj potwierdzenia dla bezpieczeństwa
        if not confirm_reset:
            return jsonify({
                'success': False,
                'error': 'Wymagane potwierdzenie reset operacji (confirm_reset: true)'
            }), 400
        
        logger.info("API: Rozpoczęcie reset wszystkich priorytetów", extra={
            'user_id': current_user.id,
            'endpoint': 'recalculate-all-priorities',
            'client_ip': request.remote_addr
        })
        
        from ..services.priority_service import get_priority_calculator
        from ..models import ProductionItem
        
        # Sprawdź ile produktów ma manual override przed resetem
        manual_overrides_before = ProductionItem.query.filter_by(priority_manual_override=True).count()
        
        # Resetuj wszystkie manual overrides
        updated_count = db.session.query(ProductionItem)\
                                .filter_by(priority_manual_override=True)\
                                .update({'priority_manual_override': False})
        db.session.commit()
        
        logger.info("API: Zresetowano manual overrides", extra={
            'manual_overrides_reset': updated_count,
            'user_id': current_user.id
        })
        
        # Wywołaj pełne przeliczenie priorytetów
        priority_calculator = get_priority_calculator()
        calculation_result = priority_calculator.recalculate_all_priorities()
        
        if calculation_result.get('success'):
            logger.info("API: Reset priorytetów zakończony pomyślnie", extra={
                'user_id': current_user.id,
                'products_updated': calculation_result.get('products_updated', 0),
                'calculation_duration': calculation_result.get('calculation_duration', '00:00:00'),
                'manual_overrides_reset': updated_count
            })
            
            return jsonify({
                'success': True,
                'message': f'Zresetowano priorytety {calculation_result.get("products_updated", 0)} produktów',
                'data': {
                    'reset_performed_at': get_local_now().isoformat(),
                    'reset_by': current_user.id,
                    'manual_overrides_reset': updated_count,
                    'manual_overrides_before': manual_overrides_before,
                    
                    'priority_recalculation': {
                        'products_updated': calculation_result.get('products_updated', 0),
                        'calculation_duration': calculation_result.get('calculation_duration', '00:00:00'),
                        'weeks_processed': calculation_result.get('weeks_processed', 0),
                        'algorithm': 'payment_date_weekly_grouping'
                    },
                    
                    'statistics': calculation_result.get('statistics', {}),
                    'performance_metrics': calculation_result.get('performance_metrics', {})
                }
            }), 200
        else:
            # Rollback manual overrides jeśli przeliczenie nie powiodło się
            db.session.rollback()
            
            logger.error("API: Błąd przeliczenia po reset", extra={
                'user_id': current_user.id,
                'error': calculation_result.get('error', 'Unknown error')
            })
            
            return jsonify({
                'success': False,
                'error': f'Błąd przeliczenia priorytetów: {calculation_result.get("error", "Unknown error")}',
                'data': {
                    'reset_rolled_back': True,
                    'manual_overrides_preserved': manual_overrides_before
                }
            }), 500
        
    except Exception as e:
        db.session.rollback()
        logger.error("API: Błąd reset priorytetów", extra={
            'user_id': current_user.id,
            'error': str(e),
            'client_ip': request.remote_addr
        })
        
        return jsonify({
            'success': False,
            'error': str(e),
            'data': {
                'reset_rolled_back': True
            }
        }), 500


@api_bp.route('/products/<int:product_id>/set-manual-priority', methods=['POST'])
@login_required
def set_manual_product_priority(product_id):
    """
    POST /api/products/<id>/set-manual-priority - Ręczne ustawienie priorytetu
    
    Endpoint dla admina do ustawienia ręcznego priorytetu dla konkretnego produktu.
    Sprawdza czy numer nie jest zajęty i ustawia manual_override = TRUE.
    
    Body (JSON):
    {
        "priority_rank": 5,       // Wymagane: numer priorytetu (1-1000)
        "reason": "Pilne zlecenie" // Opcjonalne: powód zmiany
    }
    
    Autoryzacja: admin
    Returns: JSON z rezultatem operacji
    """
    try:
        data = request.get_json()
        if not data or 'priority_rank' not in data:
            return jsonify({
                'success': False,
                'error': 'Wymagany parametr: priority_rank (liczba 1-1000)'
            }), 400
        
        priority_rank = data.get('priority_rank')
        reason = data.get('reason', '').strip()
        
        # Walidacja priority_rank
        if not isinstance(priority_rank, int) or priority_rank < 1 or priority_rank > 1000:
            return jsonify({
                'success': False,
                'error': 'priority_rank musi być liczbą między 1 a 1000'
            }), 400
        
        from ..models import ProductionItem
        
        # Znajdź produkt
        product = ProductionItem.query.get_or_404(product_id)
        
        # Sprawdź czy rank nie jest już zajęty przez inny produkt
        existing_product = ProductionItem.query.filter(
            ProductionItem.priority_rank == priority_rank,
            ProductionItem.priority_manual_override == True,
            ProductionItem.id != product_id
        ).first()
        
        if existing_product:
            return jsonify({
                'success': False,
                'error': f'Priorytet {priority_rank} jest już zajęty przez produkt {existing_product.short_product_id}',
                'conflict_product': {
                    'id': existing_product.id,
                    'short_product_id': existing_product.short_product_id,
                    'product_name': existing_product.original_product_name
                }
            }), 409
        
        # Zapisz stare wartości dla logowania
        old_priority_rank = product.priority_rank
        old_priority_score = product.priority_score
        old_manual_override = product.priority_manual_override
        
        # Ustaw nowy priorytet używając metody z modelu
        product.lock_priority(priority_rank)
        
        # Dodaj informację o powodzie zmiany (jeśli model to obsługuje)
        if hasattr(product, 'priority_change_reason') and reason:
            product.priority_change_reason = reason
        
        product.updated_at = get_local_now()
        db.session.commit()
        
        logger.info("API: Ustawiono ręczny priorytet produktu", extra={
            'user_id': current_user.id,
            'product_id': product_id,
            'product_short_id': product.short_product_id,
            'old_priority_rank': old_priority_rank,
            'new_priority_rank': priority_rank,
            'old_priority_score': old_priority_score,
            'new_priority_score': product.priority_score,
            'reason': reason,
            'client_ip': request.remote_addr
        })
        
        return jsonify({
            'success': True,
            'message': f'Ustawiono priorytet {priority_rank} dla produktu {product.short_product_id}',
            'data': {
                'product_id': product_id,
                'short_product_id': product.short_product_id,
                'old_priority': {
                    'rank': old_priority_rank,
                    'score': old_priority_score,
                    'manual_override': old_manual_override
                },
                'new_priority': {
                    'rank': product.priority_rank,
                    'score': product.priority_score,
                    'manual_override': product.priority_manual_override
                },
                'reason': reason,
                'set_by': current_user.id,
                'set_at': product.updated_at.isoformat()
            }
        }), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error("API: Błąd ustawienia ręcznego priorytetu", extra={
            'user_id': current_user.id,
            'product_id': product_id,
            'error': str(e),
            'client_ip': request.remote_addr
        })
        
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@api_bp.route('/priority-statistics', methods=['GET'])
@login_required  # Nie musi być admin - może wszyscy użytkownicy
def get_priority_statistics():
    """
    GET /api/priority-statistics - Statystyki systemu priorytetów
    
    Zwraca statystyki nowego systemu priorytetów dla UI i monitoringu.
    
    Query params:
        include_details: true|false - czy dołączyć szczegóły (default: false)
        
    Autoryzacja: login_required
    Returns: JSON ze statystykami priorytetów
    """
    try:
        include_details = request.args.get('include_details', 'false').lower() == 'true'
        
        logger.info("API: Pobieranie statystyk priorytetów", extra={
            'user_id': current_user.id,
            'include_details': include_details,
            'endpoint': 'priority-statistics'
        })
        
        from ..models import ProductionItem
        from sqlalchemy import func, desc
        from datetime import datetime, timedelta
        
        # Podstawowe statystyki
        total_products = ProductionItem.query.count()
        products_in_queue = ProductionItem.query.filter(
            ProductionItem.current_status.in_([
                'czeka_na_wyciecie', 'czeka_na_skladanie', 'czeka_na_pakowanie', 'w_realizacji'
            ])
        ).count()
        
        # Manual overrides
        manual_overrides_count = ProductionItem.query.filter_by(priority_manual_override=True).count()
        
        # Statystyki payment_date
        payment_date_stats = db.session.query(
            func.count(ProductionItem.id).label('total'),
            func.count(ProductionItem.payment_date).label('with_payment_date'),
            func.min(ProductionItem.payment_date).label('oldest_payment'),
            func.max(ProductionItem.payment_date).label('newest_payment')
        ).first()
        
        # Rozkład po tygodniach
        weekly_distribution = []
        if include_details and payment_date_stats.with_payment_date > 0:
            # Grupuj po tygodniach
            weekly_query = db.session.query(
                func.year(ProductionItem.payment_date).label('year'),
                func.week(ProductionItem.payment_date).label('week'),
                func.count(ProductionItem.id).label('count')
            ).filter(
                ProductionItem.payment_date.isnot(None),
                ProductionItem.current_status.in_([
                    'czeka_na_wyciecie', 'czeka_na_skladanie', 'czeka_na_pakowanie', 'w_realizacji'
                ])
            ).group_by(
                func.year(ProductionItem.payment_date),
                func.week(ProductionItem.payment_date)
            ).order_by(
                func.year(ProductionItem.payment_date).asc(),
                func.week(ProductionItem.payment_date).asc()
            ).limit(10).all()
            
            for year, week, count in weekly_query:
                weekly_distribution.append({
                    'year': year,
                    'week': week,
                    'week_label': f'{year}-W{week:02d}',
                    'products_count': count
                })
        
        # Rozkład priority_rank
        priority_rank_stats = db.session.query(
            func.min(ProductionItem.priority_rank).label('min_rank'),
            func.max(ProductionItem.priority_rank).label('max_rank'),
            func.avg(ProductionItem.priority_rank).label('avg_rank'),
            func.count(ProductionItem.priority_rank).label('products_with_rank')
        ).filter(ProductionItem.priority_rank.isnot(None)).first()
        
        # Ostatnia aktualizacja priorytetów (przybliżone)
        last_priority_update = None
        try:
            # Szukaj ostatniego produktu z aktualną datą updated_at
            last_updated_product = ProductionItem.query.filter(
                ProductionItem.updated_at.isnot(None)
            ).order_by(ProductionItem.updated_at.desc()).first()
            
            if last_updated_product:
                last_priority_update = last_updated_product.updated_at.isoformat()
        except:
            pass
        
        # Przygotuj response
        statistics_data = {
            'system_overview': {
                'total_products': total_products,
                'products_in_queue': products_in_queue,
                'manual_overrides_count': manual_overrides_count,
                'manual_override_percentage': round((manual_overrides_count / max(total_products, 1)) * 100, 1),
                'algorithm': 'payment_date_weekly_grouping_v2'
            },
            
            'payment_date_coverage': {
                'total_products': payment_date_stats.total,
                'with_payment_date': payment_date_stats.with_payment_date,
                'coverage_percentage': round((payment_date_stats.with_payment_date / max(payment_date_stats.total, 1)) * 100, 1),
                'date_range': {
                    'oldest': payment_date_stats.oldest_payment.isoformat() if payment_date_stats.oldest_payment else None,
                    'newest': payment_date_stats.newest_payment.isoformat() if payment_date_stats.newest_payment else None
                }
            },
            
            'priority_ranking': {
                'min_rank': priority_rank_stats.min_rank,
                'max_rank': priority_rank_stats.max_rank,
                'avg_rank': round(priority_rank_stats.avg_rank, 1) if priority_rank_stats.avg_rank else None,
                'products_with_rank': priority_rank_stats.products_with_rank,
                'ranking_coverage': round((priority_rank_stats.products_with_rank / max(products_in_queue, 1)) * 100, 1)
            },

            'system_info': {
                'priority_system_version': '2.0_rank_only',
                'uses_priority_score': False,
                'uses_priority_rank': True,
                'supports_unlimited_products': True
            },
            
            'last_updated': last_priority_update,
            'statistics_generated_at': get_local_now().isoformat()
        }
        
        # Dodaj szczegóły jeśli requested
        if include_details:
            statistics_data['weekly_distribution'] = weekly_distribution
            
            # Top manual overrides
            manual_override_products = ProductionItem.query.filter_by(
                priority_manual_override=True
            ).order_by(ProductionItem.priority_rank.asc()).limit(10).all()
            
            statistics_data['manual_overrides_details'] = [
                {
                    'id': p.id,
                    'short_product_id': p.short_product_id,
                    'priority_rank': p.priority_rank,
                    'current_status': p.current_status,
                    'manual_override': p.priority_manual_override,
                    'updated_at': p.updated_at.isoformat() if p.updated_at else None
                }
                for p in manual_override_products
            ]
        
        logger.info("API: Statystyki priorytetów pobrane", extra={
            'user_id': current_user.id,
            'total_products': total_products,
            'products_in_queue': products_in_queue,
            'manual_overrides': manual_overrides_count,
            'include_details': include_details
        })
        
        return jsonify({
            'success': True,
            'statistics': statistics_data
        }), 200
        
    except Exception as e:
        logger.error("API: Błąd pobierania statystyk priorytetów", extra={
            'user_id': current_user.id,
            'error': str(e),
            'client_ip': request.remote_addr
        })
        
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500
    
@api_bp.route('/update-configs', methods=['POST'])
@login_required
def update_configs():
    """
    POST /production/api/update-configs
    
    Batch update konfiguracji systemu produkcyjnego
    
    Body JSON:
    {
        "configs": {
            "SYNC_ENABLED": true,
            "MAX_SYNC_ITEMS_PER_BATCH": 1000,
            "STATION_ALLOWED_IPS": "192.168.1.100,192.168.1.101"
        }
    }
    
    Returns:
        JSON: Status operacji z szczegółami
    """
    try:
        # Sprawdź nagłówki CSRF
        if not request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({
                'success': False,
                'error': 'Invalid request headers'
            }), 400
        
        # Pobierz dane z requestu
        data = request.get_json()
        if not data:
            return jsonify({
                'success': False,
                'error': 'Brak danych JSON w requestcie'
            }), 400
        
        configs_dict = data.get('configs', {})
        if not configs_dict:
            return jsonify({
                'success': False,
                'error': 'Brak konfiguracji do aktualizacji'
            }), 400
        
        # Walidacja - sprawdź czy są to dozwolone klucze konfiguracji
        allowed_config_keys = {
            'SYNC_ENABLED', 'MAX_SYNC_ITEMS_PER_BATCH', 'BASELINKER_TARGET_STATUS_COMPLETED',
            'BASELINKER_SOURCE_STATUS_PAID', 'BASELINKER_TARGET_STATUS_PRODUCTION', 'SYNC_RETRY_COUNT',
            'STATION_ALLOWED_IPS', 'REFRESH_INTERVAL_SECONDS', 'STATION_AUTO_REFRESH_ENABLED',
            'STATION_SHOW_DETAILED_INFO', 'STATION_MAX_PRODUCTS_DISPLAY', 'DEADLINE_DEFAULT_DAYS',
            'PRIORITY_RECALC_INTERVAL_HOURS', 'PRIORITY_ALGORITHM_VERSION', 'DEBUG_PRODUCTION_BACKEND',
            'DEBUG_PRODUCTION_FRONTEND', 'CACHE_DURATION_SECONDS', 'ADMIN_EMAIL_NOTIFICATIONS',
            'ERROR_NOTIFICATION_THRESHOLD', 'BASELINKER_STATUSES_CACHE', 'MAX_PRODUCTS_PER_ORDER',
            'STATION_IP_CACHE_DURATION_MINUTES', 'STATION_CUTTING_PRIORITY_SORT',
            'STATION_ASSEMBLY_PRIORITY_SORT', 'STATION_PACKAGING_PRIORITY_SORT'
        }
        
        invalid_keys = set(configs_dict.keys()) - allowed_config_keys
        if invalid_keys:
            return jsonify({
                'success': False,
                'error': f'Niepozwolone klucze konfiguracji: {", ".join(invalid_keys)}'
            }), 400
        
        logger.info("Rozpoczęto batch update konfiguracji", extra={
            'user_id': current_user.id,
            'configs_count': len(configs_dict),
            'config_keys': list(configs_dict.keys())
        })
        
        # Pobierz serwis konfiguracji
        from ..services.config_service import get_config_service
        config_service = get_config_service()
        
        # Walidacja przed zapisem
        validation_result = config_service.validate_config_batch(configs_dict)
        
        if validation_result['invalid']:
            logger.warning("Walidacja konfiguracji nie powiodła się", extra={
                'user_id': current_user.id,
                'invalid_configs': validation_result['invalid']
            })
            
            return jsonify({
                'success': False,
                'error': 'Błędy walidacji konfiguracji',
                'validation_errors': validation_result['invalid']
            }), 400
        
        # Wykonaj batch update
        update_result = config_service.update_multiple_configs(
            configs_dict=configs_dict,
            user_id=current_user.id
        )
        
        if not update_result['success']:
            return jsonify({
                'success': False,
                'error': update_result.get('error', 'Nieznany błąd aktualizacji')
            }), 500
        
        logger.info("Batch update konfiguracji zakończony pomyślnie", extra={
            'user_id': current_user.id,
            'total_changes': update_result['total_changes'],
            'updated_count': len(update_result['updated']),
            'failed_count': len(update_result['failed'])
        })
        
        # Zwróć wynik
        response_data = {
            'success': True,
            'message': f"Zaktualizowano {update_result['total_changes']} konfiguracji",
            'updated': update_result['updated'],
            'failed': update_result['failed'],
            'total_changes': update_result['total_changes'],
            'warnings': validation_result.get('warnings', []),
            'updated_at': get_local_now().isoformat()
        }
        
        return jsonify(response_data)
        
    except Exception as e:
        logger.error("Błąd endpointu update-configs", extra={
            'user_id': current_user.id,
            'error': str(e)
        })
        
        return jsonify({
            'success': False,
            'error': f'Błąd serwera: {str(e)}'
        }), 500


@api_bp.route('/clear-cache', methods=['POST'])
@login_required  
def clear_cache():
    """
    POST /production/api/clear-cache
    
    Czyści cache konfiguracji systemu produkcyjnego
    
    Returns:
        JSON: Status operacji
    """
    try:
        # Sprawdź nagłówki CSRF
        if not request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({
                'success': False,
                'error': 'Invalid request headers'
            }), 400
        
        logger.info("Rozpoczęto czyszczenie cache konfiguracji", extra={
            'user_id': current_user.id
        })
        
        # Pobierz serwis konfiguracji
        from ..services.config_service import get_config_service
        config_service = get_config_service()
        
        # Pobierz statystyki przed czyszczeniem
        stats_before = config_service.get_cache_stats()
        
        # Wyczyść cache
        clear_result = config_service.clear_all_cache(user_id=current_user.id)
        
        if not clear_result['success']:
            return jsonify({
                'success': False,
                'error': clear_result.get('error', 'Nieznany błąd czyszczenia cache')
            }), 500
        
        logger.info("Cache konfiguracji wyczyszczony pomyślnie", extra={
            'user_id': current_user.id,
            'keys_cleared': clear_result['keys_cleared']
        })
        
        # Pobierz nowe statystyki
        stats_after = config_service.get_cache_stats()
        
        return jsonify({
            'success': True,
            'message': f"Cache wyczyszczony - usunięto {clear_result['keys_cleared']} kluczy",
            'keys_cleared': clear_result['keys_cleared'],
            'cleared_at': clear_result['cleared_at'],
            'stats_before': stats_before,
            'stats_after': stats_after
        })
        
    except Exception as e:
        logger.error("Błąd endpointu clear-cache", extra={
            'user_id': current_user.id,
            'error': str(e)
        })
        
        return jsonify({
            'success': False,
            'error': f'Błąd serwera: {str(e)}'
        }), 500


@api_bp.route('/reset-configs', methods=['POST'])
@login_required
def reset_configs():
    """
    POST /production/api/reset-configs
    
    Przywraca wszystkie konfiguracje do wartości domyślnych
    
    Returns:
        JSON: Status operacji
    """
    try:
        # Sprawdź nagłówki CSRF
        if not request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({
                'success': False,
                'error': 'Invalid request headers'
            }), 400
        
        logger.warning("Rozpoczęto reset konfiguracji do domyślnych", extra={
            'user_id': current_user.id
        })
        
        # Pobierz serwis konfiguracji  
        from ..services.config_service import get_config_service
        config_service = get_config_service()
        
        # Wykonaj reset
        reset_result = config_service.reset_to_defaults(user_id=current_user.id)
        
        if not reset_result['success']:
            return jsonify({
                'success': False,
                'error': reset_result.get('error', 'Nieznany błąd resetu')
            }), 500
        
        logger.warning("Reset konfiguracji zakończony", extra={
            'user_id': current_user.id,
            'reset_count': reset_result['reset_count'],
            'failed_count': len(reset_result['failed'])
        })
        
        return jsonify({
            'success': True,
            'message': f"Zresetowano {reset_result['reset_count']} konfiguracji do wartości domyślnych",
            'reset_count': reset_result['reset_count'],
            'failed': reset_result['failed']
        })
        
    except Exception as e:
        logger.error("Błąd endpointu reset-configs", extra={
            'user_id': current_user.id,
            'error': str(e)
        })
        
        return jsonify({
            'success': False,
            'error': f'Błąd serwera: {str(e)}'
        }), 500


@api_bp.route('/validate-config', methods=['POST'])
@login_required
def validate_config():
    """
    POST /production/api/validate-config
    
    Waliduje konfigurację bez zapisywania
    
    Body JSON:
    {
        "key": "STATION_ALLOWED_IPS", 
        "value": "192.168.1.100,192.168.1.101",
        "type": "ip_list"
    }
    
    Returns:
        JSON: Wynik walidacji
    """
    try:
        data = request.get_json()
        if not data:
            return jsonify({
                'success': False,
                'error': 'Brak danych JSON'
            }), 400
        
        config_key = data.get('key')
        config_value = data.get('value')
        config_type = data.get('type', 'string')
        
        if not config_key or config_value is None:
            return jsonify({
                'success': False,
                'error': 'Wymagane pola: key, value'
            }), 400
        
        # Pobierz serwis konfiguracji
        from ..services.config_service import get_config_service
        config_service = get_config_service()
        
        # Waliduj pojedynczą konfigurację
        validation_result = config_service.validate_config_batch({config_key: config_value})
        
        if validation_result['invalid']:
            return jsonify({
                'success': False,
                'valid': False,
                'errors': validation_result['invalid']
            })
        
        return jsonify({
            'success': True,
            'valid': True,
            'validated_value': validation_result['valid'][0]['serialized'] if validation_result['valid'] else config_value,
            'detected_type': validation_result['valid'][0]['type'] if validation_result['valid'] else config_type
        })
        
    except Exception as e:
        logger.error("Błąd walidacji konfiguracji", extra={
            'error': str(e)
        })
        
        return jsonify({
            'success': False,
            'error': f'Błąd walidacji: {str(e)}'
        }), 500


@api_bp.route('/config-info/<config_key>')
@login_required
def get_config_info(config_key: str):
    """
    GET /production/api/config-info/<config_key>
    
    Pobiera szczegółowe informacje o konfiguracji
    
    Returns:
        JSON: Informacje o konfiguracji
    """
    try:
        from ..models import ProductionConfig
        from ..services.config_service import get_config_service
        
        config_service = get_config_service()
        
        # Pobierz konfigurację z bazy
        config = ProductionConfig.query.filter_by(config_key=config_key).first()
        
        if not config:
            return jsonify({
                'success': False,
                'error': 'Konfiguracja nie została znaleziona'
            }), 404
        
        # Pobierz wartość domyślną
        default_value = config_service._default_values.get(config_key, 'Brak')
        
        # Sprawdź czy wartość jest w cache
        cached_value = config_service._get_config_value(config_key)
        is_cached = cached_value is not None
        
        return jsonify({
            'success': True,
            'config': {
                'key': config.config_key,
                'value': config.config_value,
                'parsed_value': config.parsed_value,
                'type': config.config_type,
                'description': config.config_description,
                'default_value': default_value,
                'is_cached': is_cached,
                'updated_by': config.updated_by,
                'updated_at': config.updated_at.isoformat() if config.updated_at else None,
                'created_at': config.created_at.isoformat() if config.created_at else None
            }
        })
        
    except Exception as e:
        logger.error("Błąd pobierania info o konfiguracji", extra={
            'config_key': config_key,
            'error': str(e)
        })
        
        return jsonify({
            'success': False,
            'error': f'Błąd serwera: {str(e)}'
        }), 500