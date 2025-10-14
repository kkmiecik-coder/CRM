# modules/production/routers/admin_routers.py
"""
Admin Routers dla modułu Production
===================================

Panel administracyjny dla zarządzania systemem produkcyjnym:
- Dashboard z przeglądem systemu
- Zarządzanie konfiguracją modułu
- Zarządzanie priorytetami i regułami
- Przegląd logów synchronizacji
- Zarządzanie błędami systemu
- Statystyki i raporty produkcyjne
- Zarządzanie użytkownikami stanowisk

Wszystkie endpointy wymagają roli admin.
Interfejsy są responsywne i zoptymalizowane pod desktop/laptop.

Autor: Konrad Kmiecik
Wersja: 1.2 (Finalna - z zabezpieczeniami)
Data: 2025-01-08
"""

import json
from datetime import datetime, date, timedelta
from flask import Blueprint, render_template, request, redirect, url_for, jsonify, flash, current_app
from flask_login import login_required, current_user
from functools import wraps
from modules.logging import get_structured_logger
from extensions import db
import pytz
from modules.users.decorators import require_module_access

# Utworzenie Blueprint dla panelu admin
admin_bp = Blueprint('production_admin', __name__)
logger = get_structured_logger('production.admin')

# ============================================================================
# DECORATORS I HELPERS
# ============================================================================

def get_local_now():
    """
    Zwraca aktualny czas w strefie czasowej Polski
    Zastępuje datetime.utcnow() dla poprawnego wyświetlania czasu
    """
    poland_tz = pytz.timezone('Europe/Warsaw')
    return datetime.now(poland_tz).replace(tzinfo=None)  # Remove timezone info for MySQL compatibility

def get_admin_dashboard_data():
    """
    Pobiera dane dla dashboardu administratora
    
    Returns:
        Dict[str, Any]: Dane dashboardu
    """
    try:
        from ..models import ProductionItem, ProductionSyncLog, ProductionError
        from sqlalchemy import func, and_
        
        # Podstawowe statystyki
        total_products = ProductionItem.query.count()
        active_products = ProductionItem.query.filter(
            ProductionItem.current_status.in_([
                'czeka_na_wyciecie', 'czeka_na_skladanie', 'czeka_na_pakowanie'
            ])
        ).count()
        
        completed_today = ProductionItem.query.filter(
            and_(
                ProductionItem.current_status == 'spakowane',
                ProductionItem.packaging_completed_at >= get_local_now().replace(hour=0, minute=0, second=0, microsecond=0)
            )
        ).count()
        
        # Statystyki błędów
        total_errors = ProductionError.query.count()
        unresolved_errors = ProductionError.query.filter_by(is_resolved=False).count()
        
        errors_last_24h = ProductionError.query.filter(
            ProductionError.error_occurred_at >= get_local_now() - timedelta(hours=24)
        ).count()
        
        # Statystyki synchronizacji
        last_sync = ProductionSyncLog.query.order_by(
            ProductionSyncLog.sync_started_at.desc()
        ).first()
        
        syncs_last_24h = ProductionSyncLog.query.filter(
            ProductionSyncLog.sync_started_at >= get_local_now() - timedelta(hours=24)
        ).count()
        
        failed_syncs_last_24h = ProductionSyncLog.query.filter(
            and_(
                ProductionSyncLog.sync_started_at >= get_local_now() - timedelta(hours=24),
                ProductionSyncLog.sync_status == 'failed'
            )
        ).count()
        
        # Status systemu
        system_health = 'healthy'
        health_issues = []
        
        if unresolved_errors > 10:
            system_health = 'warning'
            health_issues.append(f"{unresolved_errors} nierozwiązanych błędów")
        
        if last_sync and last_sync.sync_started_at < get_local_now() - timedelta(hours=25):
            system_health = 'warning'
            health_issues.append("Ostatnia synchronizacja ponad 25h temu")
        
        if failed_syncs_last_24h > 2:
            system_health = 'critical'
            health_issues.append(f"{failed_syncs_last_24h} błędnych synchronizacji w 24h")
        
        # Produkty o wysokim priorytecie
        high_priority_products = ProductionItem.query.filter(
            and_(
                ProductionItem.priority_score >= 150,
                ProductionItem.current_status.in_([
                    'czeka_na_wyciecie', 'czeka_na_skladanie', 'czeka_na_pakowanie'
                ])
            )
        ).count()
        
        # Produkty przeterminowane
        overdue_products = ProductionItem.query.filter(
            and_(
                ProductionItem.deadline_date < date.today(),
                ProductionItem.current_status.in_([
                    'czeka_na_wyciecie', 'czeka_na_skladanie', 'czeka_na_pakowanie'
                ])
            )
        ).count()
        
        dashboard_data = {
            'system_health': system_health,
            'health_issues': health_issues,
            'stats': {
                'total_products': total_products,
                'active_products': active_products,
                'completed_today': completed_today,
                'high_priority_products': high_priority_products,
                'overdue_products': overdue_products,
                'total_errors': total_errors,
                'unresolved_errors': unresolved_errors,
                'errors_last_24h': errors_last_24h,
                'syncs_last_24h': syncs_last_24h,
                'failed_syncs_last_24h': failed_syncs_last_24h
            },
            'last_sync': {
                'timestamp': last_sync.sync_started_at if last_sync else None,
                'status': last_sync.sync_status if last_sync else None,
                'products_created': last_sync.products_created if last_sync else 0,
                'error_count': last_sync.error_count if last_sync else 0
            } if last_sync else None,
            'generated_at': get_local_now()
        }
        
        return dashboard_data
        
    except Exception as e:
        logger.error("Błąd pobierania danych dashboardu", extra={'error': str(e)})
        return {
            'system_health': 'error',
            'health_issues': [f'Błąd pobierania danych: {str(e)}'],
            'stats': {},
            'last_sync': None,
            'generated_at': get_local_now()
        }

# ============================================================================
# ROUTERS - DASHBOARD
# ============================================================================

@admin_bp.route('/')
@admin_bp.route('/dashboard')
@require_module_access('production')
def dashboard():
    """
    Dashboard administratora produkcji
    
    Returns:
        HTML: Dashboard z przeglądem systemu
    """
    try:
        logger.info("Dostęp do dashboardu admin produkcji", extra={
            'user_id': current_user.id,
            'user_email': getattr(current_user, 'email', 'unknown')
        })
        
        # Pobranie danych dashboardu
        dashboard_data = get_admin_dashboard_data()
        
        # Status synchronizacji
        from ..services.sync_service import get_sync_status
        sync_status = get_sync_status()
        
        # Statystyki per stanowisko (ostatnie 7 dni)
        from ..models import ProductionItem
        from sqlalchemy import func, and_
        
        week_ago = get_local_now() - timedelta(days=7)
        station_stats = {}
        
        for station in ['cutting', 'assembly', 'packaging']:
            completed_field = f'{station}_completed_at'
            duration_field = f'{station}_duration_minutes'
            
            stats = db.session.query(
                func.count(ProductionItem.id).label('completed_count'),
                func.avg(getattr(ProductionItem, duration_field)).label('avg_duration'),
                func.sum(getattr(ProductionItem, duration_field)).label('total_duration')
            ).filter(
                and_(
                    getattr(ProductionItem, completed_field) >= week_ago,
                    getattr(ProductionItem, duration_field).isnot(None)
                )
            ).first()
            
            station_stats[station] = {
                'completed_count': stats.completed_count or 0,
                'avg_duration_minutes': float(stats.avg_duration or 0),
                'total_duration_minutes': stats.total_duration or 0
            }
        
        return render_template(
            'production/admin/dashboard.html',
            dashboard_data=dashboard_data,
            sync_status=sync_status,
            station_stats=station_stats,
            page_title="Dashboard Produkcji"
        )
        
    except Exception as e:
        logger.error("Błąd dashboardu admin", extra={
            'user_id': current_user.id if current_user.is_authenticated else None,
            'error': str(e)
        })
        flash(f'Błąd ładowania dashboardu: {str(e)}', 'error')
        return redirect(url_for('main.dashboard'))

# ============================================================================
# ROUTERS - ZARZĄDZANIE KONFIGURACJĄ
# ============================================================================

@admin_bp.route('/config')
@require_module_access('production')
def config_management():
    """
    Panel zarządzania konfiguracją modułu production
    
    Returns:
        HTML: Interfejs zarządzania konfiguracją
    """
    try:
        logger.info("Dostęp do zarządzania konfiguracją", extra={
            'user_id': current_user.id
        })
        
        from ..services.config_service import get_config_service
        
        config_service = get_config_service()
        
        # Pobranie wszystkich konfiguracji
        all_configs = config_service.get_all_configs()
        
        # Grupowanie konfiguracji po kategoriach
        config_groups = {
            'sync': {},
            'stations': {},
            'priorities': {},
            'system': {},
            'other': {}
        }
        
        for key, config in all_configs.items():
            if 'SYNC' in key or 'BASELINKER' in key:
                config_groups['sync'][key] = config
            elif 'STATION' in key or 'REFRESH' in key:
                config_groups['stations'][key] = config
            elif 'PRIORITY' in key or 'DEADLINE' in key:
                config_groups['priorities'][key] = config
            elif 'DEBUG' in key or 'CACHE' in key or 'EMAIL' in key:
                config_groups['system'][key] = config
            else:
                config_groups['other'][key] = config
        
        # Statystyki cache
        cache_stats = config_service.get_cache_stats()
        
        return render_template(
            'production/admin/config.html',
            config_groups=config_groups,
            cache_stats=cache_stats,
            page_title="Konfiguracja Produkcji"
        )
        
    except Exception as e:
        logger.error("Błąd zarządzania konfiguracją", extra={
            'user_id': current_user.id,
            'error': str(e)
        })
        flash(f'Błąd ładowania konfiguracji: {str(e)}', 'error')
        return redirect(url_for('production_admin.dashboard'))

@admin_bp.route('/config/update', methods=['POST'])
@require_module_access('production')
def update_config():
    """
    Aktualizuje konfigurację modułu production
    
    Form data:
        config_key: klucz konfiguracji
        config_value: nowa wartość
        config_type: typ konfiguracji
        config_description: opis (opcjonalny)
    
    Returns:
        Redirect: Powrót do zarządzania konfiguracją
    """
    try:
        config_key = request.form.get('config_key')
        config_value = request.form.get('config_value')
        config_type = request.form.get('config_type', 'string')
        config_description = request.form.get('config_description', '')
        
        if not config_key or config_value is None:
            flash('Brak wymaganych pól: klucz lub wartość', 'error')
            return redirect(url_for('production_admin.config_management'))
        
        from ..services.config_service import get_config_service
        
        config_service = get_config_service()
        
        # Aktualizacja konfiguracji
        success = config_service.set_config(
            key=config_key,
            value=config_value,
            user_id=current_user.id,
            description=config_description,
            config_type=config_type
        )
        
        if success:
            logger.info("Zaktualizowano konfigurację", extra={
                'config_key': config_key,
                'config_type': config_type,
                'user_id': current_user.id
            })
            flash(f'Zaktualizowano konfigurację {config_key}', 'success')
        else:
            flash(f'Błąd aktualizacji konfiguracji {config_key}', 'error')
        
        return redirect(url_for('production_admin.config_management'))
        
    except Exception as e:
        logger.error("Błąd aktualizacji konfiguracji", extra={
            'config_key': request.form.get('config_key'),
            'user_id': current_user.id,
            'error': str(e)
        })
        flash(f'Błąd aktualizacji konfiguracji: {str(e)}', 'error')
        return redirect(url_for('production_admin.config_management'))

@admin_bp.route('/config/cache/clear', methods=['POST'])
@require_module_access('production')
def clear_config_cache():
    """
    Czyści cache konfiguracji
    
    Returns:
        Redirect: Powrót do zarządzania konfiguracją
    """
    try:
        from ..services.config_service import get_config_service
        
        config_service = get_config_service()
        config_service.invalidate_cache()
        
        logger.info("Wyczyszczono cache konfiguracji", extra={
            'user_id': current_user.id
        })
        flash('Wyczyszczono cache konfiguracji', 'success')
        
    except Exception as e:
        logger.error("Błąd czyszczenia cache konfiguracji", extra={
            'user_id': current_user.id,
            'error': str(e)
        })
        flash(f'Błąd czyszczenia cache: {str(e)}', 'error')
    
    return redirect(url_for('production_admin.config_management'))

# ============================================================================
# ROUTERS - ZARZĄDZANIE PRIORYTETAMI
# ============================================================================

@admin_bp.route('/priorities')
@require_module_access('production')
def priority_management():
    """
    Panel zarządzania priorytetami i regułami priorytetyzacji
    
    Returns:
        HTML: Interfejs zarządzania priorytetami
    """
    try:
        logger.info("Dostęp do zarządzania priorytetami", extra={
            'user_id': current_user.id
        })
        
        from ..models import ProductionPriorityConfig
        
        # Pobranie wszystkich konfiguracji priorytetów
        priority_configs = ProductionPriorityConfig.query.order_by(
            ProductionPriorityConfig.display_order
        ).all()
        
        # Sprawdzenie sum wag
        total_weight = sum(config.weight_percentage for config in priority_configs if config.is_active)
        
        # Statystyki priorytetów produktów
        from ..models import ProductionItem
        from sqlalchemy import func
        
        priority_stats = db.session.query(
            func.count(ProductionItem.id).label('total'),
            func.avg(ProductionItem.priority_rank).label('avg_priority'),
            func.min(ProductionItem.priority_rank).label('min_priority'),
            func.max(ProductionItem.priority_rank).label('max_priority')
        ).filter(
            ProductionItem.current_status.in_([
                'czeka_na_wyciecie', 'czeka_na_skladanie', 'czeka_na_pakowanie'
            ])
        ).first()
        
        # Rozkład priorytetów
        priority_distribution = db.session.query(
            func.count(ProductionItem.id).label('count'),
            func.case([
                (ProductionItem.priority_rank <= 10, 'critical'),    # ZMIANA: rank 1-10 = critical
                (ProductionItem.priority_rank <= 50, 'high'),       # ZMIANA: rank 11-50 = high  
                (ProductionItem.priority_rank <= 100, 'normal')     # ZMIANA: rank 51-100 = normal
            ], else_='low').label('priority_level')
        ).filter(
            ProductionItem.current_status.in_([
                'czeka_na_wyciecie', 'czeka_na_skladanie', 'czeka_na_pakowanie'
            ])
        ).group_by(
            func.case([
                (ProductionItem.priority_score >= 200, 'critical'),
                (ProductionItem.priority_score >= 150, 'high'),
                (ProductionItem.priority_score >= 100, 'normal')
            ], else_='low')
        ).all()
        
        distribution_dict = {level: count for count, level in priority_distribution}
        
        return render_template(
            'production/admin/priorities.html',
            priority_configs=priority_configs,
            total_weight=total_weight,
            priority_stats={
                'total': priority_stats.total or 0,
                'avg_priority': float(priority_stats.avg_priority or 100),
                'min_priority': priority_stats.min_priority or 0,
                'max_priority': priority_stats.max_priority or 0
            },
            priority_distribution=distribution_dict,
            page_title="Zarządzanie Priorytetami"
        )
        
    except Exception as e:
        logger.error("Błąd zarządzania priorytetami", extra={
            'user_id': current_user.id,
            'error': str(e)
        })
        flash(f'Błąd ładowania zarządzania priorytetami: {str(e)}', 'error')
        return redirect(url_for('production_admin.dashboard'))

@admin_bp.route('/priorities/update/<int:config_id>', methods=['POST'])
@require_module_access('production')
def update_priority_config(config_id):
    """
    Aktualizuje konfigurację priorytetu
    
    Args:
        config_id (int): ID konfiguracji priorytetu
        
    Form data:
        config_name: nazwa konfiguracji
        weight_percentage: waga procentowa
        is_active: czy aktywna
        criteria_json: kryteria w JSON
    
    Returns:
        Redirect: Powrót do zarządzania priorytetami
    """
    try:
        from ..models import ProductionPriorityConfig
        
        config = ProductionPriorityConfig.query.get_or_404(config_id)
        
        config_name = request.form.get('config_name')
        weight_percentage = request.form.get('weight_percentage')
        is_active = request.form.get('is_active') == 'on'
        criteria_json_str = request.form.get('criteria_json')
        
        if not config_name or not weight_percentage:
            flash('Brak wymaganych pól', 'error')
            return redirect(url_for('production_admin.priority_management'))
        
        # Walidacja wagi
        try:
            weight = int(weight_percentage)
            if not 0 <= weight <= 100:
                raise ValueError("Waga musi być między 0 a 100")
        except ValueError as e:
            flash(f'Nieprawidłowa waga: {str(e)}', 'error')
            return redirect(url_for('production_admin.priority_management'))
        
        # Walidacja JSON
        try:
            criteria_json = json.loads(criteria_json_str) if criteria_json_str else {}
        except json.JSONDecodeError as e:
            flash(f'Nieprawidłowy format JSON: {str(e)}', 'error')
            return redirect(url_for('production_admin.priority_management'))
        
        # Aktualizacja konfiguracji
        config.config_name = config_name
        config.weight_percentage = weight
        config.is_active = is_active
        config.criteria_json = criteria_json
        config.updated_at = get_local_now()
        
        db.session.commit()
        
        # Invalidacja cache priorytetów
        from ..services.priority_service import invalidate_priority_cache
        invalidate_priority_cache()
        
        logger.info("Zaktualizowano konfigurację priorytetu", extra={
            'config_id': config_id,
            'config_name': config_name,
            'weight_percentage': weight,
            'user_id': current_user.id
        })
        
        flash(f'Zaktualizowano konfigurację priorytetu "{config_name}"', 'success')
        
    except Exception as e:
        db.session.rollback()
        logger.error("Błąd aktualizacji konfiguracji priorytetu", extra={
            'config_id': config_id,
            'user_id': current_user.id,
            'error': str(e)
        })
        flash(f'Błąd aktualizacji konfiguracji priorytetu: {str(e)}', 'error')
    
    return redirect(url_for('production_admin.priority_management'))

@admin_bp.route('/priorities/recalculate', methods=['POST'])
@require_module_access('production')
def recalculate_all_priorities():
    """
    Przelicza priorytety wszystkich aktywnych produktów
    
    Returns:
        Redirect: Powrót do zarządzania priorytetami
    """
    try:
        from ..models import ProductionItem
        from ..services.priority_service import get_priority_calculator
        
        priority_calc = get_priority_calculator()
        if not priority_calc:
            flash('Kalkulator priorytetów niedostępny', 'error')
            return redirect(url_for('production_admin.priority_management'))
        
        # Pobierz aktywne produkty
        active_products = ProductionItem.query.filter(
            ProductionItem.current_status.in_([
                'czeka_na_wyciecie',
                'czeka_na_skladanie', 
                'czeka_na_pakowanie'
            ])
        ).all()
        
        updated_count = 0
        error_count = 0
        
        for product in active_products:
            try:
                # Przygotowanie danych do obliczenia
                product_data = {
                    'deadline_date': product.deadline_date,
                    'total_value_net': float(product.total_value_net or 0),
                    'volume_m3': float(product.volume_m3 or 0),
                    'created_at': product.created_at,
                    'wood_class': product.parsed_wood_class
                }
                
                # Obliczenie nowego priorytetu
                new_priority = priority_calc.calculate_priority(product_data)
                
                if new_priority != product.priority_score:
                    product.priority_score = new_priority
                    product.updated_at = get_local_now()
                    updated_count += 1
                    
            except Exception as e:
                error_count += 1
                logger.warning("Błąd przeliczania priorytetu produktu", extra={
                    'product_id': product.short_product_id,
                    'error': str(e)
                })
                continue
        
        db.session.commit()
        
        logger.info("Przeliczono priorytety produktów", extra={
            'total_products': len(active_products),
            'updated_count': updated_count,
            'error_count': error_count,
            'user_id': current_user.id
        })
        
        if error_count > 0:
            flash(f'Przeliczono priorytety: {updated_count} zaktualizowanych, {error_count} błędów', 'warning')
        else:
            flash(f'Przeliczono priorytety: {updated_count} produktów zaktualizowanych z {len(active_products)} sprawdzonych', 'success')
        
    except Exception as e:
        db.session.rollback()
        logger.error("Błąd przeliczania priorytetów", extra={
            'user_id': current_user.id,
            'error': str(e)
        })
        flash(f'Błąd przeliczania priorytetów: {str(e)}', 'error')
    
    return redirect(url_for('production_admin.priority_management'))

# ============================================================================
# ROUTERS - LOGI SYNCHRONIZACJI
# ============================================================================

@admin_bp.route('/sync-logs')
@require_module_access('production')
def sync_logs():
    """
    Przegląd logów synchronizacji z Baselinker
    
    Query params:
        page: strona paginacji (default: 1)
        status: filtr po statusie (optional)
        type: filtr po typie sync (optional)
        
    Returns:
        HTML: Lista logów synchronizacji
    """
    try:
        page = request.args.get('page', 1, type=int)
        status_filter = request.args.get('status')
        type_filter = request.args.get('type')
        
        logger.info("Dostęp do logów synchronizacji", extra={
            'user_id': current_user.id,
            'page': page,
            'status_filter': status_filter,
            'type_filter': type_filter
        })
        
        from ..models import ProductionSyncLog
        
        # Query podstawowy
        query = ProductionSyncLog.query
        
        # Filtrowanie
        if status_filter:
            query = query.filter(ProductionSyncLog.sync_status == status_filter)
        
        if type_filter:
            query = query.filter(ProductionSyncLog.sync_type == type_filter)
        
        # Paginacja i sortowanie
        pagination = query.order_by(
            ProductionSyncLog.sync_started_at.desc()
        ).paginate(
            page=page,
            per_page=20,
            error_out=False
        )
        
        sync_logs = pagination.items
        
        # Statystyki logów
        from sqlalchemy import func
        
        log_stats = db.session.query(
            ProductionSyncLog.sync_status,
            func.count(ProductionSyncLog.id).label('count'),
            func.sum(ProductionSyncLog.products_created).label('total_created'),
            func.sum(ProductionSyncLog.error_count).label('total_errors')
        ).group_by(ProductionSyncLog.sync_status).all()
        
        stats_dict = {
            status: {
                'count': count,
                'total_created': total_created or 0,
                'total_errors': total_errors or 0
            }
            for status, count, total_created, total_errors in log_stats
        }
        
        # Status synchronizacji
        from ..services.sync_service import get_sync_status
        current_sync_status = get_sync_status()
        
        return render_template(
            'production/admin/sync_logs.html',
            pagination=pagination,
            sync_logs=sync_logs,
            log_stats=stats_dict,
            current_sync_status=current_sync_status,
            status_filter=status_filter,
            type_filter=type_filter,
            page_title="Logi Synchronizacji"
        )
        
    except Exception as e:
        logger.error("Błąd logów synchronizacji", extra={
            'user_id': current_user.id,
            'error': str(e)
        })
        flash(f'Błąd ładowania logów synchronizacji: {str(e)}', 'error')
        return redirect(url_for('production_admin.dashboard'))

@admin_bp.route('/sync-logs/<int:log_id>')
@require_module_access('production')
def sync_log_detail(log_id):
    """
    Szczegóły konkretnego logu synchronizacji
    
    Args:
        log_id (int): ID logu synchronizacji
        
    Returns:
        HTML: Szczegóły logu synchronizacji
    """
    try:
        from ..models import ProductionSyncLog
        
        sync_log = ProductionSyncLog.query.get_or_404(log_id)
        
        # Parsowanie szczegółów błędów
        error_details = []
        if sync_log.error_details:
            try:
                error_details = json.loads(sync_log.error_details)
                if isinstance(error_details, dict):
                    error_details = [error_details]
            except json.JSONDecodeError:
                error_details = []
        
        logger.info("Wyświetlenie szczegółów logu sync", extra={
            'user_id': current_user.id,
            'log_id': log_id
        })
        
        return render_template(
            'production/admin/sync_log_detail.html',
            sync_log=sync_log,
            error_details=error_details,
            page_title=f"Szczegóły synchronizacji {log_id}"
        )
        
    except Exception as e:
        logger.error("Błąd szczegółów logu synchronizacji", extra={
            'user_id': current_user.id,
            'log_id': log_id,
            'error': str(e)
        })
        flash(f'Błąd ładowania szczegółów logu: {str(e)}', 'error')
        return redirect(url_for('production_admin.sync_logs'))

@admin_bp.route('/sync/trigger', methods=['POST'])
@require_module_access('production')
def trigger_manual_sync():
    """
    Uruchamia ręczną synchronizację z Baselinker
    
    Returns:
        Redirect: Powrót do logów synchronizacji
    """
    try:
        from ..services.sync_service import sync_orders_from_baselinker, get_sync_status
        
        # Sprawdzenie czy synchronizacja już nie jest w toku
        status = get_sync_status()
        if status.get('is_running'):
            flash('Synchronizacja jest już w toku', 'warning')
            return redirect(url_for('production_admin.sync_logs'))
        
        # Wykonanie synchronizacji
        result = sync_orders_from_baselinker('manual_trigger')
        
        logger.info("Uruchomiono ręczną synchronizację", extra={
            'user_id': current_user.id,
            'sync_result': result
        })
        
        if result['success']:
            flash(f'Synchronizacja ukończona: {result["products_created"]} nowych produktów, {result["products_updated"]} zaktualizowanych', 'success')
        else:
            flash(f'Błąd synchronizacji: {result.get("error", "Nieznany błąd")}', 'error')
        
    except Exception as e:
        logger.error("Błąd uruchamiania ręcznej synchronizacji", extra={
            'user_id': current_user.id,
            'error': str(e)
        })
        flash(f'Błąd uruchamiania synchronizacji: {str(e)}', 'error')
    
    return redirect(url_for('production_admin.sync_logs'))

@admin_bp.route('/sync-logs/cleanup', methods=['POST'])
@require_module_access('production')
def cleanup_sync_logs():
    """
    Czyści stare logi synchronizacji
    
    Form data:
        days_to_keep: liczba dni do zachowania (default: 30)
        
    Returns:
        Redirect: Powrót do logów synchronizacji
    """
    try:
        days_to_keep = int(request.form.get('days_to_keep', 30))
        
        if days_to_keep < 7:
            flash('Nie można zachować mniej niż 7 dni logów', 'error')
            return redirect(url_for('production_admin.sync_logs'))
        
        from ..services.sync_service import cleanup_old_sync_logs
        
        cleanup_old_sync_logs(days_to_keep)
        
        logger.info("Wyczyszczono stare logi synchronizacji", extra={
            'user_id': current_user.id,
            'days_to_keep': days_to_keep
        })
        
        flash(f'Wyczyszczono logi starsze niż {days_to_keep} dni', 'success')
        
    except Exception as e:
        logger.error("Błąd czyszczenia logów synchronizacji", extra={
            'user_id': current_user.id,
            'error': str(e)
        })
        flash(f'Błąd czyszczenia logów: {str(e)}', 'error')
    
    return redirect(url_for('production_admin.sync_logs'))

# ============================================================================
# ROUTERS - ZARZĄDZANIE BŁĘDAMI
# ============================================================================

@admin_bp.route('/errors')
@require_module_access('production')
def error_management():
    """
    Panel zarządzania błędami systemu
    
    Query params:
        page: strona paginacji (default: 1)
        resolved: true|false|all (default: false)
        error_type: typ błędu (optional)
        
    Returns:
        HTML: Lista błędów systemu
    """
    try:
        page = request.args.get('page', 1, type=int)
        resolved_filter = request.args.get('resolved', 'false')
        error_type_filter = request.args.get('error_type')
        
        logger.info("Dostęp do zarządzania błędami", extra={
            'user_id': current_user.id,
            'page': page,
            'resolved_filter': resolved_filter,
            'error_type_filter': error_type_filter
        })
        
        from ..models import ProductionError
        
        # Query podstawowy
        query = ProductionError.query
        
        # Filtrowanie po statusie rozwiązania
        if resolved_filter == 'true':
            query = query.filter(ProductionError.is_resolved == True)
        elif resolved_filter == 'false':
            query = query.filter(ProductionError.is_resolved == False)
        # 'all' nie filtruje
        
        # Filtrowanie po typie błędu
        if error_type_filter:
            query = query.filter(ProductionError.error_type == error_type_filter)
        
        # Paginacja i sortowanie
        pagination = query.order_by(
            ProductionError.error_occurred_at.desc()
        ).paginate(
            page=page,
            per_page=25,
            error_out=False
        )
        
        errors = pagination.items
        
        # Statystyki błędów
        from sqlalchemy import func
        
        error_stats = db.session.query(
            ProductionError.error_type,
            func.count(ProductionError.id).label('total_count'),
            func.sum(func.case([(ProductionError.is_resolved == False, 1)], else_=0)).label('unresolved_count')
        ).group_by(ProductionError.error_type).all()
        
        stats_dict = {
            error_type: {
                'total_count': total_count,
                'unresolved_count': unresolved_count
            }
            for error_type, total_count, unresolved_count in error_stats
        }
        
        # Błędy z ostatnich 24h
        from sqlalchemy import and_
        
        recent_errors_count = ProductionError.query.filter(
            ProductionError.error_occurred_at >= get_local_now() - timedelta(hours=24)
        ).count()
        
        return render_template(
            'production/admin/errors.html',
            pagination=pagination,
            errors=errors,
            error_stats=stats_dict,
            recent_errors_count=recent_errors_count,
            resolved_filter=resolved_filter,
            error_type_filter=error_type_filter,
            page_title="Zarządzanie Błędami"
        )
        
    except Exception as e:
        logger.error("Błąd zarządzania błędami", extra={
            'user_id': current_user.id,
            'error': str(e)
        })
        flash(f'Błąd ładowania zarządzania błędami: {str(e)}', 'error')
        return redirect(url_for('production_admin.dashboard'))

@admin_bp.route('/errors/<int:error_id>')
@require_module_access('production')
def error_detail(error_id):
    """
    Szczegóły konkretnego błędu
    
    Args:
        error_id (int): ID błędu
        
    Returns:
        HTML: Szczegóły błędu
    """
    try:
        from ..models import ProductionError
        
        error = ProductionError.query.get_or_404(error_id)
        
        # POPRAWKA: Parsowanie szczegółów błędu z error_details_json
        error_details_parsed = {}
        if error.error_details_json:  # ← ZMIENIONE z error.error_details
            try:
                # error_details_json może być już dict (JSON) lub string
                if isinstance(error.error_details_json, str):
                    error_details_parsed = json.loads(error.error_details_json)
                else:
                    error_details_parsed = error.error_details_json
            except (json.JSONDecodeError, TypeError):
                error_details_parsed = {}
        
        logger.info("Wyświetlenie szczegółów błędu", extra={
            'user_id': current_user.id,
            'error_id': error_id
        })
        
        return render_template(
            'production/admin/error_detail.html',
            error=error,
            error_details_parsed=error_details_parsed,
            page_title=f"Szczegóły błędu {error_id}"
        )
        
    except Exception as e:
        logger.error("Błąd szczegółów błędu", extra={
            'user_id': current_user.id,
            'error_id': error_id,
            'error': str(e)
        })
        flash(f'Błąd ładowania szczegółów błędu: {str(e)}', 'error')
        return redirect(url_for('production_admin.error_management'))

@admin_bp.route('/errors/<int:error_id>/resolve', methods=['POST'])
@require_module_access('production')
def resolve_error(error_id):
    """
    Oznacza błąd jako rozwiązany
    
    Args:
        error_id (int): ID błędu
        
    Form data:
        resolution_notes: notatki rozwiązania
        
    Returns:
        Redirect: Powrót do zarządzania błędami
    """
    try:
        from ..models import ProductionError
        
        error = ProductionError.query.get_or_404(error_id)
        
        if error.is_resolved:
            flash('Błąd jest już rozwiązany', 'warning')
            return redirect(url_for('production_admin.error_detail', error_id=error_id))
        
        resolution_notes = request.form.get('resolution_notes', '')
        
        # Oznacz jako rozwiązany
        error.resolve(current_user.id, resolution_notes)
        
        db.session.commit()
        
        logger.info("Rozwiązano błąd", extra={
            'error_id': error_id,
            'error_type': error.error_type,
            'resolved_by': current_user.id
        })
        
        flash(f'Błąd {error_id} został oznaczony jako rozwiązany', 'success')
        
        # Sprawdź czy przekierować do listy czy szczegółów
        if request.form.get('return_to') == 'list':
            return redirect(url_for('production_admin.error_management'))
        else:
            return redirect(url_for('production_admin.error_detail', error_id=error_id))
        
    except Exception as e:
        db.session.rollback()
        logger.error("Błąd rozwiązywania błędu", extra={
            'error_id': error_id,
            'user_id': current_user.id,
            'error': str(e)
        })
        flash(f'Błąd rozwiązywania błędu: {str(e)}', 'error')
        return redirect(url_for('production_admin.error_detail', error_id=error_id))

@admin_bp.route('/errors/bulk-resolve', methods=['POST'])
@require_module_access('production')
def bulk_resolve_errors():
    """
    Oznacza wiele błędów jako rozwiązanych
    
    Form data:
        error_ids: lista ID błędów (checkbox values)
        bulk_resolution_notes: wspólne notatki rozwiązania
        
    Returns:
        Redirect: Powrót do zarządzania błędami
    """
    try:
        error_ids = request.form.getlist('error_ids')
        bulk_resolution_notes = request.form.get('bulk_resolution_notes', '')
        
        if not error_ids:
            flash('Nie wybrano żadnych błędów do rozwiązania', 'warning')
            return redirect(url_for('production_admin.error_management'))
        
        from ..models import ProductionError
        
        resolved_count = 0
        already_resolved_count = 0
        
        for error_id_str in error_ids:
            try:
                error_id = int(error_id_str)
                error = ProductionError.query.get(error_id)
                
                if not error:
                    continue
                
                if error.is_resolved:
                    already_resolved_count += 1
                    continue
                
                error.resolve(current_user.id, bulk_resolution_notes)
                resolved_count += 1
                
            except (ValueError, TypeError):
                continue
        
        db.session.commit()
        
        logger.info("Rozwiązano błędy bulk", extra={
            'resolved_count': resolved_count,
            'already_resolved_count': already_resolved_count,
            'total_requested': len(error_ids),
            'user_id': current_user.id
        })
        
        if resolved_count > 0:
            flash(f'Rozwiązano {resolved_count} błędów', 'success')
        
        if already_resolved_count > 0:
            flash(f'{already_resolved_count} błędów było już rozwiązanych', 'info')
        
    except Exception as e:
        db.session.rollback()
        logger.error("Błąd bulk rozwiązywania błędów", extra={
            'user_id': current_user.id,
            'error': str(e)
        })
        flash(f'Błąd rozwiązywania błędów: {str(e)}', 'error')
    
    return redirect(url_for('production_admin.error_management'))

# ============================================================================
# ROUTERS - STATYSTYKI I RAPORTY
# ============================================================================

@admin_bp.route('/stats')
@login_required
def detailed_stats():
    """
    Szczegółowe statystyki i raporty produkcji
    
    Query params:
        period: today|week|month|quarter|year (default: week)
        chart_type: bar|line|pie (default: bar)
        
    Returns:
        HTML: Szczegółowe statystyki
    """
    try:
        period = request.args.get('period', 'week')
        chart_type = request.args.get('chart_type', 'bar')
        
        logger.info("Dostęp do szczegółowych statystyk", extra={
            'user_id': current_user.id,
            'period': period,
            'chart_type': chart_type
        })
        
        from ..models import ProductionItem
        from sqlalchemy import func, and_, extract
        
        # Określenie zakresu czasowego
        now = get_local_now()
        if period == 'today':
            start_date = now.replace(hour=0, minute=0, second=0, microsecond=0)
        elif period == 'week':
            start_date = now - timedelta(days=7)
        elif period == 'month':
            start_date = now - timedelta(days=30)
        elif period == 'quarter':
            start_date = now - timedelta(days=90)
        elif period == 'year':
            start_date = now - timedelta(days=365)
        else:
            start_date = now - timedelta(days=7)
        
        # Statystyki podstawowe
        total_stats = db.session.query(
            func.count(ProductionItem.id).label('total_products'),
            func.sum(ProductionItem.volume_m3).label('total_volume'),
            func.sum(ProductionItem.total_value_net).label('total_value')
        ).filter(
            ProductionItem.created_at >= start_date
        ).first()
        
        # Produkty ukończone w okresie
        completed_stats = db.session.query(
            func.count(ProductionItem.id).label('completed_count'),
            func.sum(ProductionItem.volume_m3).label('completed_volume'),
            func.sum(ProductionItem.total_value_net).label('completed_value'),
            func.avg(ProductionItem.total_production_time_minutes).label('avg_production_time')
        ).filter(
            and_(
                ProductionItem.current_status == 'spakowane',
                ProductionItem.packaging_completed_at >= start_date
            )
        ).first()
        
        # Wydajność per stanowisko
        station_performance = {}
        for station in ['cutting', 'assembly', 'packaging']:
            completed_field = f'{station}_completed_at'
            duration_field = f'{station}_duration_minutes'
            
            perf_stats = db.session.query(
                func.count(ProductionItem.id).label('completed_tasks'),
                func.avg(getattr(ProductionItem, duration_field)).label('avg_duration'),
                func.sum(getattr(ProductionItem, duration_field)).label('total_duration'),
                func.sum(ProductionItem.volume_m3).label('total_volume_processed')
            ).filter(
                and_(
                    getattr(ProductionItem, completed_field) >= start_date,
                    getattr(ProductionItem, duration_field).isnot(None)
                )
            ).first()
            
            station_performance[station] = {
                'completed_tasks': perf_stats.completed_tasks or 0,
                'avg_duration_minutes': float(perf_stats.avg_duration or 0),
                'total_duration_minutes': perf_stats.total_duration or 0,
                'total_volume_processed': float(perf_stats.total_volume_processed or 0),
                'productivity_m3_per_hour': (
                    float(perf_stats.total_volume_processed or 0) / 
                    ((perf_stats.total_duration or 1) / 60)
                ) if perf_stats.total_duration else 0
            }
        
        # Trendy dzienne (ostatnie 30 dni)
        if period in ['month', 'quarter', 'year']:
            daily_trends = db.session.query(
                func.date(ProductionItem.packaging_completed_at).label('completion_date'),
                func.count(ProductionItem.id).label('daily_completed'),
                func.sum(ProductionItem.volume_m3).label('daily_volume')
            ).filter(
                and_(
                    ProductionItem.current_status == 'spakowane',
                    ProductionItem.packaging_completed_at >= now - timedelta(days=30),
                    ProductionItem.packaging_completed_at.isnot(None)
                )
            ).group_by(
                func.date(ProductionItem.packaging_completed_at)
            ).order_by(
                func.date(ProductionItem.packaging_completed_at)
            ).all()
        else:
            daily_trends = []
        
        # Top produkty po priorytecie
        top_priority_products = ProductionItem.query.filter(
            ProductionItem.current_status.in_([
                'czeka_na_wyciecie', 'czeka_na_skladanie', 'czeka_na_pakowanie'
            ])
        ).order_by(ProductionItem.priority_score.desc()).limit(10).all()
        
        # Statystyki per gatunek drewna
        wood_species_stats = db.session.query(
            ProductionItem.parsed_wood_species,
            func.count(ProductionItem.id).label('count'),
            func.sum(ProductionItem.volume_m3).label('volume'),
            func.avg(ProductionItem.priority_score).label('avg_priority')
        ).filter(
            and_(
                ProductionItem.parsed_wood_species.isnot(None),
                ProductionItem.created_at >= start_date
            )
        ).group_by(ProductionItem.parsed_wood_species).all()
        
        # Statystyki błędów w okresie
        from ..models import ProductionError
        
        error_trends = db.session.query(
            ProductionError.error_type,
            func.count(ProductionError.id).label('error_count')
        ).filter(
            ProductionError.error_occurred_at >= start_date
        ).group_by(ProductionError.error_type).all()
        
        stats_data = {
            'period': period,
            'period_start': start_date,
            'period_end': now,
            'total_stats': {
                'total_products': total_stats.total_products or 0,
                'total_volume': float(total_stats.total_volume or 0),
                'total_value': float(total_stats.total_value or 0)
            },
            'completed_stats': {
                'completed_count': completed_stats.completed_count or 0,
                'completed_volume': float(completed_stats.completed_volume or 0),
                'completed_value': float(completed_stats.completed_value or 0),
                'avg_production_time': float(completed_stats.avg_production_time or 0)
            },
            'station_performance': station_performance,
            'daily_trends': [
                {
                    'date': trend.completion_date.isoformat(),
                    'completed': trend.daily_completed,
                    'volume': float(trend.daily_volume or 0)
                }
                for trend in daily_trends
            ],
            'top_priority_products': [
                {
                    'id': p.short_product_id,
                    'name': p.original_product_name[:50] + '...' if len(p.original_product_name) > 50 else p.original_product_name,
                    'priority': p.priority_score,
                    'status': p.current_status,
                    'deadline': p.deadline_date.isoformat() if p.deadline_date else None
                }
                for p in top_priority_products
            ],
            'wood_species_stats': {
                species: {
                    'count': count,
                    'volume': float(volume or 0),
                    'avg_priority': float(avg_priority or 100)
                }
                for species, count, volume, avg_priority in wood_species_stats if species
            },
            'error_trends': {
                error_type: error_count
                for error_type, error_count in error_trends
            }
        }
        
        return render_template(
            'production/admin/stats.html',
            stats_data=stats_data,
            chart_type=chart_type,
            page_title="Szczegółowe Statystyki Produkcji"
        )
        
    except Exception as e:
        logger.error("Błąd szczegółowych statystyk", extra={
            'user_id': current_user.id,
            'period': request.args.get('period'),
            'error': str(e)
        })
        flash(f'Błąd ładowania statystyk: {str(e)}', 'error')
        return redirect(url_for('production_admin.dashboard'))

# ============================================================================
# ROUTERS - ZARZĄDZANIE UŻYTKOWNIKAMI STANOWISK
# ============================================================================

@admin_bp.route('/users')
@require_module_access('production')
def user_management():
    """
    Panel zarządzania użytkownikami stanowisk
    
    Returns:
        HTML: Lista użytkowników z przypisaniami do stanowisk
    """
    try:
        logger.info("Dostęp do zarządzania użytkownikami stanowisk", extra={
            'user_id': current_user.id
        })
        
        # Import modelu User z głównej aplikacji
        from app.models import User
        
        # Pobierz wszystkich użytkowników z rolą związaną z produkcją
        production_users = User.query.filter(
            User.role.in_(['user', 'admin', 'partner'])
        ).all()
        
        # Pobierz przypisania do stanowisk (jeśli pole istnieje)
        station_assignments = {}
        for user in production_users:
            if hasattr(user, 'assigned_workstation_id') and user.assigned_workstation_id:
                station_assignments[user.id] = user.assigned_workstation_id
        
        # Statystyki użytkowników per stanowisko (z logów aktywności)
        from ..models import ProductionItem
        from sqlalchemy import func
        
        user_stats = {}
        for station in ['cutting', 'assembly', 'packaging']:
            assigned_field = f'{station}_assigned_worker_id'
            completed_field = f'{station}_completed_at'
            
            # Statystyki aktywności użytkowników na stanowisku
            station_user_stats = db.session.query(
                getattr(ProductionItem, assigned_field).label('user_id'),
                func.count(ProductionItem.id).label('tasks_completed'),
                func.sum(ProductionItem.volume_m3).label('volume_processed')
            ).filter(
                and_(
                    getattr(ProductionItem, assigned_field).isnot(None),
                    getattr(ProductionItem, completed_field) >= get_local_now() - timedelta(days=30)
                )
            ).group_by(getattr(ProductionItem, assigned_field)).all()
            
            user_stats[station] = {
                stat.user_id: {
                    'tasks_completed': stat.tasks_completed,
                    'volume_processed': float(stat.volume_processed or 0)
                }
                for stat in station_user_stats
            }
        
        return render_template(
            'production/admin/users.html',
            production_users=production_users,
            station_assignments=station_assignments,
            user_stats=user_stats,
            page_title="Zarządzanie Użytkownikami Stanowisk"
        )
        
    except Exception as e:
        logger.error("Błąd zarządzania użytkownikami", extra={
            'user_id': current_user.id,
            'error': str(e)
        })
        flash(f'Błąd ładowania zarządzania użytkownikami: {str(e)}', 'error')
        return redirect(url_for('production_admin.dashboard'))

# ============================================================================
# UTILITY ROUTERS
# ============================================================================

@admin_bp.route('/export/config')
@require_module_access('production')
def export_config():
    """
    Eksportuje konfigurację modułu do JSON
    
    Returns:
        JSON: Plik z eksportem konfiguracji
    """
    try:
        from ..services.config_service import get_config_service
        from flask import make_response
        
        config_service = get_config_service()
        export_data = config_service.export_configs(include_sensitive=False)
        
        # Dodaj metadane eksportu
        export_data['exported_by'] = current_user.id
        export_data['exported_by_email'] = getattr(current_user, 'email', 'unknown')
        
        response = make_response(json.dumps(export_data, indent=2, ensure_ascii=False))
        response.headers['Content-Type'] = 'application/json; charset=utf-8'
        response.headers['Content-Disposition'] = f'attachment; filename=production_config_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json'
        
        logger.info("Wyeksportowano konfigurację", extra={
            'user_id': current_user.id,
            'configs_count': export_data.get('configs_count', 0)
        })
        
        return response
        
    except Exception as e:
        logger.error("Błąd eksportu konfiguracji", extra={
            'user_id': current_user.id,
            'error': str(e)
        })
        flash(f'Błąd eksportu konfiguracji: {str(e)}', 'error')
        return redirect(url_for('production_admin.config_management'))

@admin_bp.route('/cache/clear-all', methods=['POST'])
@require_module_access('production')
def clear_all_caches():
    """
    Czyści wszystkie cache serwisów production
    
    Returns:
        Redirect: Powrót do dashboardu
    """
    try:
        from ..services import invalidate_caches
        
        invalidate_caches()
        
        logger.info("Wyczyszczono wszystkie cache", extra={
            'user_id': current_user.id
        })
        
        flash('Wyczyszczono wszystkie cache serwisów production', 'success')
        
    except Exception as e:
        logger.error("Błąd czyszczenia cache", extra={
            'user_id': current_user.id,
            'error': str(e)
        })
        flash(f'Błąd czyszczenia cache: {str(e)}', 'error')
    
    return redirect(url_for('production_admin.dashboard'))

# ============================================================================
# ERROR HANDLERS
# ============================================================================

@admin_bp.errorhandler(403)
def admin_forbidden(error):
    """Handler dla błędów dostępu admin"""
    flash('Brak uprawnień administratora', 'error')
    return redirect(url_for('main.dashboard'))

@admin_bp.errorhandler(404)
def admin_not_found(error):
    """Handler dla błędów 404 w panelu admin"""
    flash('Nie znaleziono żądanej strony', 'error')
    return redirect(url_for('production_admin.dashboard'))

@admin_bp.errorhandler(500)
def admin_server_error(error):
    """Handler dla błędów serwera w panelu admin"""
    logger.error("Błąd serwera w panelu admin", extra={
        'user_id': current_user.id if current_user.is_authenticated else None,
        'error': str(error),
        'path': request.path
    })
    flash('Wystąpił błąd systemu. Skontaktuj się z administratorem.', 'error')
    return redirect(url_for('production_admin.dashboard'))

# ============================================================================
# BEFORE/AFTER REQUEST HANDLERS
# ============================================================================

@admin_bp.before_request
def log_admin_access():
    """Loguje dostęp do panelu admin"""
    try:
        from . import log_route_access
        log_route_access(request)
        
        # Dodatkowe logowanie dla panelu admin
        logger.info("Dostęp do panelu admin", extra={
            'path': request.path,
            'method': request.method,
            'user_id': current_user.id if current_user.is_authenticated else None,
            'user_email': getattr(current_user, 'email', 'unknown') if current_user.is_authenticated else None,
            'endpoint': request.endpoint
        })
        
    except Exception as e:
        logger.error("Błąd logowania dostępu admin", extra={'error': str(e)})

@admin_bp.after_request
def add_admin_headers(response):
    """Dodaje nagłówki do odpowiedzi panelu admin"""
    try:
        from . import apply_common_headers
        response = apply_common_headers(response)
        
        # Dodatkowe nagłówki dla panelu admin
        response.headers['X-Admin-Panel'] = '1.2.0'
        response.headers['X-Robots-Tag'] = 'noindex, nofollow'  # Nie indeksuj panelu admin
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'  # Nie cache'uj panelu admin
        
        return response
        
    except Exception as e:
        logger.error("Błąd dodawania nagłówków admin", extra={'error': str(e)})
        return response

# ============================================================================
# CONTEXT PROCESSORS
# ============================================================================

@admin_bp.context_processor
def inject_admin_context():
    """
    Injektuje wspólny kontekst dla wszystkich templates panelu admin
    
    Returns:
        Dict[str, Any]: Kontekst dostępny w templates
    """
    try:
        # Podstawowe informacje
        context = {
            'current_time': get_local_now(),
            'current_date': date.today(),
            'admin_version': '1.2.0',
            'current_admin_user': current_user if current_user.is_authenticated else None
        }
        
        # URL helpers dla nawigacji admin
        context['admin_urls'] = {
            'dashboard': url_for('production_admin.dashboard'),
            'config': url_for('production_admin.config_management'),
            'priorities': url_for('production_admin.priority_management'),
            'sync_logs': url_for('production_admin.sync_logs'),
            'errors': url_for('production_admin.error_management'),
            'stats': url_for('production_admin.detailed_stats'),
            'users': url_for('production_admin.user_management')
        }
        
        # Szybkie statystyki dla nawigacji
        try:
            from ..models import ProductionError
            
            unresolved_errors = ProductionError.query.filter_by(is_resolved=False).count()
            context['quick_stats'] = {
                'unresolved_errors': unresolved_errors
            }
        except Exception as e:
            logger.debug("Błąd szybkich statystyk admin", extra={'error': str(e)})
            context['quick_stats'] = {'unresolved_errors': 0}
        
        return context
        
    except Exception as e:
        logger.error("Błąd context processor admin", extra={'error': str(e)})
        return {
            'current_time': get_local_now(),
            'current_date': date.today(),
            'admin_version': '1.2.0'
        }

# ============================================================================
# TEMPLATE FILTERS DLA PANELU ADMIN
# ============================================================================

@admin_bp.app_template_filter('format_datetime')
def format_datetime_filter(dt):
    """
    Template filter dla formatowania datetime
    
    Args:
        dt (datetime): Datetime do sformatowania
        
    Returns:
        str: Sformatowany datetime
    """
    if not dt:
        return "—"
    
    try:
        if isinstance(dt, str):
            dt = datetime.fromisoformat(dt.replace('Z', '+00:00'))
        
        now = get_local_now()
        diff = now - dt
        
        if diff.days > 7:
            return dt.strftime("%d.%m.%Y %H:%M")
        elif diff.days > 0:
            return f"{diff.days} dni temu"
        elif diff.seconds > 3600:
            hours = diff.seconds // 3600
            return f"{hours} godz. temu"
        elif diff.seconds > 60:
            minutes = diff.seconds // 60
            return f"{minutes} min. temu"
        else:
            return "Przed chwilą"
    except (ValueError, TypeError):
        return str(dt)

@admin_bp.app_template_filter('format_duration')
def format_duration_filter(seconds):
    """
    Template filter dla formatowania czasu trwania
    
    Args:
        seconds (int): Czas w sekundach
        
    Returns:
        str: Sformatowany czas
    """
    if not seconds:
        return "—"
    
    try:
        seconds = int(seconds)
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        secs = seconds % 60
        
        if hours > 0:
            return f"{hours}h {minutes}m {secs}s"
        elif minutes > 0:
            return f"{minutes}m {secs}s"
        else:
            return f"{secs}s"
    except (ValueError, TypeError):
        return str(seconds)

@admin_bp.app_template_filter('format_file_size')
def format_file_size_filter(bytes_size):
    """
    Template filter dla formatowania rozmiaru plików
    
    Args:
        bytes_size (int): Rozmiar w bajtach
        
    Returns:
        str: Sformatowany rozmiar
    """
    if not bytes_size:
        return "0 B"
    
    try:
        bytes_size = int(bytes_size)
        
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if bytes_size < 1024.0:
                return f"{bytes_size:.1f} {unit}"
            bytes_size /= 1024.0
        
        return f"{bytes_size:.1f} PB"
    except (ValueError, TypeError):
        return str(bytes_size)

@admin_bp.app_template_filter('format_percentage')
def format_percentage_filter(value, total=None):
    """
    Template filter dla formatowania procentów
    
    Args:
        value (float): Wartość
        total (float, optional): Wartość całkowita (jeśli nie podano, value traktowane jako procent)
        
    Returns:
        str: Sformatowany procent
    """
    if not value:
        return "0%"
    
    try:
        if total:
            percentage = (float(value) / float(total)) * 100
        else:
            percentage = float(value)
        
        return f"{percentage:.1f}%"
    except (ValueError, TypeError, ZeroDivisionError):
        return "0%"

@admin_bp.app_template_filter('status_badge_class')
def status_badge_class_filter(status):
    """
    Template filter dla klas CSS badge'ów statusów
    
    Args:
        status (str): Status
        
    Returns:
        str: Klasa CSS
    """
    status_classes = {
        # Statusy synchronizacji
        'completed': 'badge-success',
        'running': 'badge-primary',
        'failed': 'badge-danger',
        'partial': 'badge-warning',
        
        # Statusy błędów
        'resolved': 'badge-success',
        'unresolved': 'badge-danger',
        
        # Statusy systemu
        'healthy': 'badge-success',
        'warning': 'badge-warning',
        'critical': 'badge-danger',
        'error': 'badge-danger',
        
        # Statusy produktów
        'czeka_na_wyciecie': 'badge-info',
        'czeka_na_skladanie': 'badge-warning',
        'czeka_na_pakowanie': 'badge-primary',
        'spakowane': 'badge-success',
        'anulowane': 'badge-secondary',
        'wstrzymane': 'badge-dark'
    }
    
    return status_classes.get(status, 'badge-secondary')

@admin_bp.app_template_filter('highlight_json')
def highlight_json_filter(json_data):
    """
    Template filter dla podświetlania JSON
    
    Args:
        json_data: Dane JSON do podświetlenia
        
    Returns:
        str: JSON z podświetleniem HTML
    """
    if not json_data:
        return ""
    
    try:
        if isinstance(json_data, str):
            # Już jest stringiem JSON
            json_str = json_data
        else:
            # Konwertuj obiekt na JSON
            json_str = json.dumps(json_data, indent=2, ensure_ascii=False)
        
        # Proste podświetlanie składni
        import re
        
        # Klucze
        json_str = re.sub(r'"([^"]+)"\s*:', r'<span class="json-key">"\1"</span>:', json_str)
        
        # Wartości string
        json_str = re.sub(r':\s*"([^"]*)"', r': <span class="json-string">"\1"</span>', json_str)
        
        # Wartości numeryczne
        json_str = re.sub(r':\s*(\d+\.?\d*)', r': <span class="json-number">\1</span>', json_str)
        
        # Wartości boolean
        json_str = re.sub(r':\s*(true|false)', r': <span class="json-boolean">\1</span>', json_str)
        
        # Wartości null
        json_str = re.sub(r':\s*(null)', r': <span class="json-null">\1</span>', json_str)
        
        return json_str
        
    except Exception as e:
        return str(json_data)

# ============================================================================
# AJAX ENDPOINTS DLA PANELU ADMIN
# ============================================================================

@admin_bp.route('/ajax/dashboard-stats')
@require_module_access('production')
def ajax_dashboard_stats():
    """
    AJAX endpoint dla odświeżania statystyk dashboardu
    
    Returns:
        JSON: Aktualne statystyki dashboardu
    """
    try:
        dashboard_data = get_admin_dashboard_data()
        
        return jsonify({
            'success': True,
            'data': dashboard_data
        }), 200
        
    except Exception as e:
        logger.error("Błąd AJAX statystyk dashboardu", extra={
            'user_id': current_user.id,
            'error': str(e)
        })
        
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@admin_bp.route('/ajax/system-errors')
@require_module_access('production')
def ajax_system_errors():
    """
    AJAX endpoint dla pobierania błędów systemu do wyświetlenia w modalboxie
    
    Returns:
        JSON: Lista błędów z opisami zrozumiałymi dla użytkownika nietechnicznego
    """
    try:
        from ..models import ProductionError
        
        # Pobierz nierozwiązane błędy z ostatnich 7 dni
        from datetime import datetime, timedelta
        week_ago = get_local_now() - timedelta(days=7)
        
        errors = ProductionError.query.filter(
            ProductionError.error_occurred_at >= week_ago
        ).order_by(
            ProductionError.is_resolved.asc(),  # Nierozwiązane na początku
            ProductionError.error_occurred_at.desc()
        ).limit(50).all()  # Maksymalnie 50 błędów
        
        # Formatuj błędy dla użytkownika
        formatted_errors = []
        
        for error in errors:
            # POPRAWKA: użyj error_details_json zamiast error_details
            error_details = {}
            if error.error_details_json:  # ← ZMIENIONE z error.error_details
                try:
                    # error_details_json może być już dict (JSON) lub string
                    if isinstance(error.error_details_json, str):
                        error_details = json.loads(error.error_details_json)
                    else:
                        error_details = error.error_details_json
                except (json.JSONDecodeError, TypeError):
                    error_details = {}
            
            formatted_error = {
                'id': error.id,
                'error_type': error.error_type,
                'error_message': error.error_message,
                'error_details': error_details,
                'error_occurred_at': error.error_occurred_at.isoformat() if error.error_occurred_at else None,
                'is_resolved': error.is_resolved,
                'related_product_id': error.related_product_id,
                'related_order_id': error.related_order_id
                # USUNIĘTO: error_location - nie istnieje w bazie danych prod_errors
            }
            
            formatted_errors.append(formatted_error)
        
        logger.info("Pobrano błędy systemu dla modala", extra={
            'user_id': current_user.id,
            'errors_count': len(formatted_errors)
        })
        
        return jsonify({
            'success': True,
            'errors': formatted_errors,
            'total_count': len(formatted_errors)
        }), 200
        
    except Exception as e:
        logger.error("Błąd pobierania błędów systemu", extra={
            'user_id': current_user.id,
            'error': str(e)
        })
        
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@admin_bp.route('/ajax/clear-system-errors', methods=['POST'])
@require_module_access('production')
def ajax_clear_system_errors():
    """
    AJAX endpoint dla czyszczenia błędów systemu
    Oznacza wszystkie nierozwiązane błędy jako rozwiązane
    
    Returns:
        JSON: Status operacji czyszczenia
    """
    try:
        from ..models import ProductionError
        
        # Znajdź wszystkie nierozwiązane błędy
        unresolved_errors = ProductionError.query.filter(
            ProductionError.is_resolved == False
        ).all()
        
        cleared_count = 0
        
        # Oznacz każdy błąd jako rozwiązany
        for error in unresolved_errors:
            error.resolve(
                user_id=current_user.id,
                resolution_notes="Błąd wyczyszczony masowo przez administratora"
            )
            cleared_count += 1
        
        # Zapisz zmiany w bazie
        db.session.commit()
        
        logger.info("Wyczyszczono błędy systemu", extra={
            'user_id': current_user.id,
            'cleared_count': cleared_count
        })
        
        return jsonify({
            'success': True,
            'message': f'Wyczyszczono {cleared_count} błędów systemu',
            'cleared_count': cleared_count
        }), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error("Błąd czyszczenia błędów systemu", extra={
            'user_id': current_user.id,
            'error': str(e)
        })
        
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


# Modyfikacja istniejącego endpointu ajax_system_health - dodanie pola błędów
@admin_bp.route('/ajax/system-health')
@require_module_access('production')
def ajax_system_health():
    """
    AJAX endpoint dla sprawdzania zdrowia systemu
    ZMODYFIKOWANY - dodane informacje o błędach
    
    Returns:
        JSON: Status zdrowia systemu z informacjami o błędach
    """
    try:
        from ..services.sync_service import get_sync_status
        from ..models import ProductionError
        
        # Status synchronizacji
        sync_status = get_sync_status()
        
        # Nierozwiązane błędy z ostatnich 24h
        from datetime import datetime, timedelta
        day_ago = get_local_now() - timedelta(hours=24)
        
        unresolved_errors_24h = ProductionError.query.filter(
            ProductionError.error_occurred_at >= day_ago,
            ProductionError.is_resolved == False
        ).count()
        
        # Wszystkie nierozwiązane błędy
        total_unresolved_errors = ProductionError.query.filter(
            ProductionError.is_resolved == False
        ).count()
        
        # Sprawdzenie statusu bazy danych
        try:
            db.session.execute('SELECT 1')
            database_status = 'ok'
        except Exception:
            database_status = 'error'
        
        # Ostatnia synchronizacja
        from ..models import ProductionSyncLog
        last_sync_log = ProductionSyncLog.query.order_by(
            ProductionSyncLog.sync_started_at.desc()
        ).first()
        
        last_sync = last_sync_log.sync_started_at.isoformat() if last_sync_log and last_sync_log.sync_started_at else None
        sync_status_str = last_sync_log.sync_status if last_sync_log else 'never_run'
        
        health_data = {
            'database_status': database_status,
            'sync_status': sync_status_str,
            'last_sync': last_sync,
            'errors_24h': unresolved_errors_24h,
            'total_unresolved_errors': total_unresolved_errors,
            'baselinker_api_avg_ms': sync_status.get('api_response_time_ms', 0) if sync_status else 0
        }
        
        logger.info("Pobrano system health", extra={
            'user_id': current_user.id,
            'errors_24h': unresolved_errors_24h,
            'total_errors': total_unresolved_errors
        })
        
        return jsonify({
            'success': True,
            'health': health_data
        }), 200
        
    except Exception as e:
        logger.error("Błąd sprawdzania system health", extra={
            'user_id': current_user.id,
            'error': str(e)
        })
        
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

# ============================================================================
# DEBUGGING I DEVELOPMENT
# ============================================================================

@admin_bp.route('/debug/module-info')
@require_module_access('production')
def debug_module_info():
    """
    Debug endpoint z informacjami o module production
    
    Returns:
        JSON: Informacje debugowe o module
    """
    try:
        from ..services import health_check
        from .. import __version__, get_production_status_summary, is_sync_running
        
        # Health check wszystkich serwisów
        services_health = health_check()
        
        # Informacje o module
        module_info = {
            'version': __version__,
            'services_health': services_health,
            'production_summary': get_production_status_summary(),
            'sync_running': is_sync_running(),
            'current_user': {
                'id': current_user.id,
                'role': getattr(current_user, 'role', 'unknown'),
                'email': getattr(current_user, 'email', 'unknown')
            },
            'request_info': {
                'method': request.method,
                'path': request.path,
                'endpoint': request.endpoint,
                'remote_addr': request.remote_addr
            },
            'timestamp': get_local_now().isoformat()
        }
        
        return jsonify({
            'success': True,
            'debug_info': module_info
        }), 200
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@admin_bp.route('/security-events')
@require_module_access('production')
def security_events():
    """
    Panel przeglądania zdarzeń bezpieczeństwa
    """
    try:
        from ..models import ProductionSecurityEvent
        
        page = request.args.get('page', 1, type=int)
        event_type_filter = request.args.get('event_type')
        
        query = ProductionSecurityEvent.query
        
        if event_type_filter:
            query = query.filter(ProductionSecurityEvent.event_type == event_type_filter)
        
        pagination = query.order_by(
            ProductionSecurityEvent.created_at.desc()
        ).paginate(page=page, per_page=50, error_out=False)
        
        return render_template(
            'production/admin/security_events.html',
            pagination=pagination,
            events=pagination.items,
            event_type_filter=event_type_filter,
            page_title="Zdarzenia Bezpieczeństwa"
        )
        
    except Exception as e:
        logger.error("Błąd ładowania security events", extra={
            'user_id': current_user.id,
            'error': str(e)
        })
        flash(f'Błąd: {str(e)}', 'error')
        return redirect(url_for('production_admin.dashboard'))
   