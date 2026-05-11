# modules/production/routers/main_routers.py
"""
Main Routers dla modułu Production
==================================

Główne interfejsy zarządzania zgodne z PRD Section 6.1:
- GET /production → dashboard główny
- GET /production/products → szczegółowa lista produktów  
- GET /production/config → panel konfiguracji (tylko admin)

Wszystkie endpointy wymagają autoryzacji (login_required).
Interfejsy zoptymalizowane pod desktop/laptop.

Autor: Konrad Kmiecik
Wersja: 1.1 (Poprawione URL routing)
Data: 2025-09-10
"""

from datetime import datetime, date, timedelta
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from modules.logging import get_structured_logger
from extensions import db
from modules.users.decorators import require_module_access

# Utworzenie Blueprint dla głównych routów
main_bp = Blueprint('production_main', __name__)
logger = get_structured_logger('production.main')

# ============================================================================
# ROUTERS - zgodnie z PRD Section 6.1
# ============================================================================

@main_bp.route('/')
@require_module_access('production')
def dashboard():
    """
    GET /production - Dashboard główny (PRD Section 6.1)
    
    Dashboard z podstawowymi statystykami:
    - Karty przeglądowe (nie szczegółowe listy)
    - Statystyki stanowisk
    - Alerty deadline
    - System health
    
    Autoryzacja: user, admin
    Returns: HTML dashboard
    """
    try:
        logger.info("Dostęp do dashboard główny", extra={
            'user_id': current_user.id,
            'user_role': getattr(current_user, 'role', 'unknown')
        })
        
        from ..models import ProductionItem
        from modules.production.services.station_heartbeat import get_all_statuses
        from modules.production.services.station_events_service import get_station_work_in_range

        # Podstawowe statystyki - zgodnie z PRD API response structure
        dashboard_stats = {
            'stations': {},
            'today_totals': {
                'completed_orders': 0,
                'completed_items': 0,
                'completed_products': 0,
                'total_m3': 0.0,
                'avg_deadline_distance': 0.0
            },
            'in_production': {
                'orders': 0,
                'products': 0,
                'm3': 0.0
            },
            'deadline_alerts': [],
            'system_health': {
                'last_sync': None,
                'sync_status': 'unknown',
                'errors_24h': 0,
                'database_status': 'connected'
            }
        }

        # Statystyki per stanowisko
        today = date.today()
        today_start = datetime.combine(today, datetime.min.time())
        tomorrow_start = today_start + timedelta(days=1)

        heartbeat_statuses = get_all_statuses()

        # Mapowanie stanowisko → status czekania (kolejka)
        station_pending_status = {
            'cutting': 'czeka_na_wyciecie',
            'assembly': 'czeka_na_skladanie',
            'completion': 'czeka_na_kompletacje',
            'gluing': 'czeka_na_sklejanie',
            'formatting': 'czeka_na_formatowanie',
            'finishing': 'czeka_na_wykanczanie',
            'packaging': 'czeka_na_pakowanie',
        }

        for station_code, pending_status in station_pending_status.items():
            # Kolejka (current_status = czeka_na_*) — stan bieżący
            pending_count = ProductionItem.query.filter(
                ProductionItem.current_status == pending_status
            ).count()
            pending_m3 = db.session.query(
                db.func.coalesce(db.func.sum(ProductionItem.volume_m3 * ProductionItem.quantity), 0)
            ).filter(ProductionItem.current_status == pending_status).scalar() or 0.0

            # Faktyczna praca dziś — z prod_station_events (uwzględnia partial work)
            try:
                work = get_station_work_in_range(station_code, today_start, tomorrow_start)
            except Exception as e:
                logger.warning("Nie udało się pobrać station_events", extra={
                    'station': station_code, 'error': str(e)
                })
                work = {'pieces_done': 0, 'm3_done': 0.0, 'items_count': 0, 'orders_count': 0}

            dashboard_stats['stations'][station_code] = {
                'pending_count': pending_count,
                'today_m3': float(work['m3_done']),
                'completed_today': int(work['items_count']),
                'pending_m3': float(pending_m3),
                'status': 'active' if pending_count > 0 else 'idle',
                'status_class': 'station-active' if pending_count > 0 else 'station-idle',
                'tablet_status': heartbeat_statuses.get(station_code, {
                    'active': False, 'last_seen': None, 'status_label': 'Niedostępne'
                })
            }

        # Dzisiejsze ukończone — agregat z eventów stanowiska pakowania
        # (faktyczne sztuki/pozycje/zamówienia, na których pakowanie zrobiło ruch dziś)
        try:
            packaging_work = get_station_work_in_range('packaging', today_start, tomorrow_start)
        except Exception as e:
            logger.warning("Nie udało się pobrać packaging events", extra={'error': str(e)})
            packaging_work = {'pieces_done': 0, 'm3_done': 0.0, 'items_count': 0, 'orders_count': 0}

        dashboard_stats['today_totals'] = {
            'completed_orders': int(packaging_work['orders_count']),
            'completed_items': int(packaging_work['items_count']),
            'completed_products': int(packaging_work['pieces_done']),
            'total_m3': float(packaging_work['m3_done']),
            'avg_deadline_distance': 7.0  # Placeholder - będzie obliczane
        }

        # "In production now" — liczone per niespakowana sztuka.
        # Wykluczamy pozycje już spakowane i anulowane; dla pozostałych liczymy
        # remaining = quantity - quantity_done_packaging.
        in_prod_items = ProductionItem.query.filter(
            ProductionItem.current_status.notin_(('spakowane', 'anulowane')),
            db.func.coalesce(ProductionItem.quantity_done_packaging, 0) < ProductionItem.quantity
        ).all()
        in_prod_order_ids = set()
        items_count = 0
        pieces_remaining = 0
        m3_remaining = 0.0
        for item in in_prod_items:
            qty = int(item.quantity or 0)
            done = int(item.quantity_done_packaging or 0)
            remaining = qty - done
            if remaining <= 0:
                continue
            items_count += 1
            pieces_remaining += remaining
            m3_remaining += float(item.volume_m3 or 0) * remaining
            if item.order and item.order.baselinker_order_id:
                in_prod_order_ids.add(item.order.baselinker_order_id)
        dashboard_stats['in_production'] = {
            'orders': len(in_prod_order_ids),
            'items': items_count,
            'products': pieces_remaining,
            'm3': round(m3_remaining, 2)
        }

        # Alerty deadline - produkty zbliżające się do terminu
        deadline_alerts = ProductionItem.query.filter(
            ProductionItem.deadline_date <= date.today() + timedelta(days=3),
            ProductionItem.current_status != 'spakowane'
        ).order_by(ProductionItem.deadline_date.asc()).limit(5).all()

        dashboard_stats['deadline_alerts'] = [
            {
                'product_id': alert.short_product_id,
                'short_product_id': alert.short_product_id,
                'days_remaining': (alert.deadline_date - date.today()).days if alert.deadline_date else 0,
                'deadline_date': alert.deadline_date.isoformat() if alert.deadline_date else None,
                'deadline_date_formatted': alert.deadline_date.strftime('%d.%m.%Y') if alert.deadline_date else '',
                'current_station': alert.current_status.replace('czeka_na_', '') if alert.current_status else 'unknown',
                'client_name': (alert.order.client_name if alert.order else None) or 'Brak danych',
                'client_order_number': (alert.order.client_order_number if alert.order else None) or '',
                'baselinker_order_id': alert.order.baselinker_order_id if alert.order else None,
                'product_name': alert.original_product_name or '',
                'quantity': alert.quantity or 1
            }
            for alert in deadline_alerts
        ]
        
        return render_template(
            'panel/dashboard.html',
            dashboard_stats=dashboard_stats,
            page_title="Dashboard Produkcji"
        )
        
    except Exception as e:
        logger.error("Błąd dashboard główny", extra={
            'user_id': current_user.id if current_user.is_authenticated else None,
            'error': str(e)
        })
        flash(f'Błąd ładowania dashboard: {str(e)}', 'error')
        return render_template('panel/dashboard.html',
                            dashboard_stats={}, 
                            page_title="Dashboard Produkcji")


@main_bp.route('/logistics')
@login_required
def logistics():
    """Strona stanowiska Logistyka — decyzja o transporcie"""
    return render_template('logistics/logistics.html')


@main_bp.route('/config')
@require_module_access('production')
def config_panel():
    """
    GET /production/config - Panel konfiguracji (PRD Section 6.1)
    
    Panel konfiguracji z funkcjami zgodnie z PRD:
    - Konfiguracja kryteriów priorytetu
    - Częstotliwość odświeżania 
    - Ustawienia debug
    - Zarządzanie IP
    
    Autoryzacja: tylko admin
    Returns: HTML panel konfiguracji
    """
    try:
        logger.info("Dostęp do panelu konfiguracji", extra={
            'user_id': current_user.id
        })
        
        from ..models import ProductionConfig, ProductionPriorityConfig
        
        # Podstawowe konfiguracje zgodnie z PRD
        config_keys = [
            'STATION_ALLOWED_IPS',
            'REFRESH_INTERVAL_SECONDS',
            'DEBUG_PRODUCTION_BACKEND', 
            'DEBUG_PRODUCTION_FRONTEND'
        ]
        
        configs = {}
        for key in config_keys:
            config = ProductionConfig.query.filter_by(config_key=key).first()
            configs[key] = {
                'value': config.config_value if config else '',
                'description': config.config_description if config else '',
                'type': config.config_type if config else 'string'
            }
        
        # Konfiguracje priorytetów - drag&drop zgodnie z PRD
        priority_configs = ProductionPriorityConfig.query.filter_by(is_active=True)\
                                                         .order_by(ProductionPriorityConfig.display_order).all()
        
        return render_template(
            'panel/config.html',
            configs=configs,
            priority_configs=priority_configs,
            page_title="Konfiguracja Produkcji"
        )
        
    except Exception as e:
        logger.error("Błąd panelu konfiguracji", extra={
            'user_id': current_user.id,
            'error': str(e)
        })
        flash(f'Błąd ładowania konfiguracji: {str(e)}', 'error')
        # POPRAWIONE: Dodano prefix production.
        return redirect(url_for('production.production_main.dashboard'))

# ============================================================================
# ERROR HANDLERS
# ============================================================================

@main_bp.errorhandler(404)
def not_found(error):
    """Handler dla błędów 404"""
    flash('Nie znaleziono żądanej strony', 'error')
    # POPRAWIONE: Dodano prefix production.
    return redirect(url_for('production.production_main.dashboard'))

@main_bp.errorhandler(500) 
def server_error(error):
    """Handler dla błędów serwera"""
    logger.error("Błąd serwera w main routers", extra={
        'user_id': current_user.id if current_user.is_authenticated else None,
        'error': str(error),
        'path': request.path
    })
    flash('Wystąpił błąd systemu', 'error')
    # POPRAWIONE: Dodano prefix production.
    return redirect(url_for('production.production_main.dashboard'))

# ============================================================================
# CONTEXT PROCESSORS
# ============================================================================

@main_bp.context_processor
def inject_main_context():
    """Injektuje kontekst dla głównych templates"""
    try:
        return {
            'current_time': datetime.utcnow(),
            'current_user_role': getattr(current_user, 'role', 'unknown') if current_user.is_authenticated else None,
            'dashboard_url': url_for('production.production_main.dashboard'),
            'config_url': url_for('production.production_main.config_panel'),
            # Dodatkowe URL dla API
            'api_dashboard_stats': url_for('production.production_api.dashboard_stats'),
            'api_manual_sync': url_for('production.production_api.manual_sync')
        }
    except Exception as e:
        logger.error("Błąd context processor main", extra={'error': str(e)})
        return {
            'current_time': datetime.utcnow(),
            'dashboard_url': '#',
            'config_url': '#'
        }

logger.info("Zainicjalizowano Main routers zgodnie z PRD", extra={
    'blueprint_name': main_bp.name,
    'routers_count': 3,  # dashboard, products, config
    'prd_compliance': True
})