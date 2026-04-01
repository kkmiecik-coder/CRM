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

        # Podstawowe statystyki - zgodnie z PRD API response structure
        dashboard_stats = {
            'stations': {},
            'today_totals': {
                'completed_orders': 0,
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
        today_end = datetime.combine(today, datetime.max.time())

        heartbeat_statuses = get_all_statuses()

        # Cutting
        cutting_pending = ProductionItem.query.filter_by(current_status='czeka_na_wyciecie').count()
        cutting_today_m3 = db.session.query(db.func.sum(ProductionItem.volume_m3))\
                                    .filter(ProductionItem.cutting_completed_at >= today_start)\
                                    .scalar() or 0.0
        cutting_completed_today = ProductionItem.query.filter(
            ProductionItem.cutting_completed_at >= today_start,
            ProductionItem.cutting_completed_at <= today_end
        ).count()
        cutting_pending_m3 = db.session.query(
            db.func.coalesce(db.func.sum(ProductionItem.volume_m3), 0)
        ).filter(ProductionItem.current_status == 'czeka_na_wyciecie').scalar() or 0.0

        # Assembly
        assembly_pending = ProductionItem.query.filter_by(current_status='czeka_na_skladanie').count()
        assembly_today_m3 = db.session.query(db.func.sum(ProductionItem.volume_m3))\
                                     .filter(ProductionItem.assembly_completed_at >= today_start)\
                                     .scalar() or 0.0
        assembly_completed_today = ProductionItem.query.filter(
            ProductionItem.assembly_completed_at >= today_start,
            ProductionItem.assembly_completed_at <= today_end
        ).count()
        assembly_pending_m3 = db.session.query(
            db.func.coalesce(db.func.sum(ProductionItem.volume_m3), 0)
        ).filter(ProductionItem.current_status == 'czeka_na_skladanie').scalar() or 0.0

        # Gluing
        gluing_pending = ProductionItem.query.filter_by(current_status='czeka_na_sklejanie').count()
        gluing_today_m3 = 0.0
        gluing_completed_today = 0
        gluing_pending_m3 = 0.0
        try:
            gluing_today_m3 = db.session.query(db.func.sum(ProductionItem.volume_m3))\
                                        .filter(ProductionItem.gluing_completed_at >= today_start)\
                                        .scalar() or 0.0
            gluing_completed_today = ProductionItem.query.filter(
                ProductionItem.gluing_completed_at >= today_start,
                ProductionItem.gluing_completed_at <= today_end
            ).count()
            gluing_pending_m3 = db.session.query(
                db.func.coalesce(db.func.sum(ProductionItem.volume_m3), 0)
            ).filter(ProductionItem.current_status == 'czeka_na_sklejanie').scalar() or 0.0
        except AttributeError:
            pass

        # Formatting
        formatting_pending = ProductionItem.query.filter_by(current_status='czeka_na_formatowanie').count()
        formatting_today_m3 = 0.0
        formatting_completed_today = 0
        formatting_pending_m3 = 0.0
        try:
            formatting_today_m3 = db.session.query(db.func.sum(ProductionItem.volume_m3))\
                                            .filter(ProductionItem.formatting_completed_at >= today_start)\
                                            .scalar() or 0.0
            formatting_completed_today = ProductionItem.query.filter(
                ProductionItem.formatting_completed_at >= today_start,
                ProductionItem.formatting_completed_at <= today_end
            ).count()
            formatting_pending_m3 = db.session.query(
                db.func.coalesce(db.func.sum(ProductionItem.volume_m3), 0)
            ).filter(ProductionItem.current_status == 'czeka_na_formatowanie').scalar() or 0.0
        except AttributeError:
            pass

        # Finishing
        finishing_pending = ProductionItem.query.filter_by(current_status='czeka_na_wykanczanie').count()
        finishing_today_m3 = 0.0
        finishing_completed_today = 0
        finishing_pending_m3 = 0.0
        try:
            finishing_today_m3 = db.session.query(db.func.sum(ProductionItem.volume_m3))\
                                           .filter(ProductionItem.finishing_completed_at >= today_start)\
                                           .scalar() or 0.0
            finishing_completed_today = ProductionItem.query.filter(
                ProductionItem.finishing_completed_at >= today_start,
                ProductionItem.finishing_completed_at <= today_end
            ).count()
            finishing_pending_m3 = db.session.query(
                db.func.coalesce(db.func.sum(ProductionItem.volume_m3), 0)
            ).filter(ProductionItem.current_status == 'czeka_na_wykanczanie').scalar() or 0.0
        except AttributeError:
            pass

        # Packaging
        packaging_pending = ProductionItem.query.filter_by(current_status='czeka_na_pakowanie').count()
        packaging_today_m3 = db.session.query(db.func.sum(ProductionItem.volume_m3))\
                                      .filter(ProductionItem.packaging_completed_at >= today_start)\
                                      .scalar() or 0.0
        packaging_completed_today = ProductionItem.query.filter(
            ProductionItem.packaging_completed_at >= today_start,
            ProductionItem.packaging_completed_at <= today_end
        ).count()
        packaging_pending_m3 = db.session.query(
            db.func.coalesce(db.func.sum(ProductionItem.volume_m3), 0)
        ).filter(ProductionItem.current_status == 'czeka_na_pakowanie').scalar() or 0.0

        # Aktualizacja statystyk stacji
        dashboard_stats['stations']['cutting'] = {
            'pending_count': cutting_pending,
            'today_m3': float(cutting_today_m3),
            'completed_today': cutting_completed_today,
            'pending_m3': float(cutting_pending_m3),
            'status': 'active' if cutting_pending > 0 else 'idle',
            'status_class': 'station-active' if cutting_pending > 0 else 'station-idle',
            'tablet_status': heartbeat_statuses.get('cutting', {'active': False, 'last_seen': None, 'status_label': 'Niedostępne'})
        }
        dashboard_stats['stations']['assembly'] = {
            'pending_count': assembly_pending,
            'today_m3': float(assembly_today_m3),
            'completed_today': assembly_completed_today,
            'pending_m3': float(assembly_pending_m3),
            'status': 'active' if assembly_pending > 0 else 'idle',
            'status_class': 'station-active' if assembly_pending > 0 else 'station-idle',
            'tablet_status': heartbeat_statuses.get('assembly', {'active': False, 'last_seen': None, 'status_label': 'Niedostępne'})
        }
        dashboard_stats['stations']['gluing'] = {
            'pending_count': gluing_pending,
            'today_m3': float(gluing_today_m3),
            'completed_today': gluing_completed_today,
            'pending_m3': float(gluing_pending_m3),
            'status': 'active' if gluing_pending > 0 else 'idle',
            'status_class': 'station-active' if gluing_pending > 0 else 'station-idle',
            'tablet_status': heartbeat_statuses.get('gluing', {'active': False, 'last_seen': None, 'status_label': 'Niedostępne'})
        }
        dashboard_stats['stations']['formatting'] = {
            'pending_count': formatting_pending,
            'today_m3': float(formatting_today_m3),
            'completed_today': formatting_completed_today,
            'pending_m3': float(formatting_pending_m3),
            'status': 'active' if formatting_pending > 0 else 'idle',
            'status_class': 'station-active' if formatting_pending > 0 else 'station-idle',
            'tablet_status': heartbeat_statuses.get('formatting', {'active': False, 'last_seen': None, 'status_label': 'Niedostępne'})
        }
        dashboard_stats['stations']['finishing'] = {
            'pending_count': finishing_pending,
            'today_m3': float(finishing_today_m3),
            'completed_today': finishing_completed_today,
            'pending_m3': float(finishing_pending_m3),
            'status': 'active' if finishing_pending > 0 else 'idle',
            'status_class': 'station-active' if finishing_pending > 0 else 'station-idle',
            'tablet_status': heartbeat_statuses.get('finishing', {'active': False, 'last_seen': None, 'status_label': 'Niedostępne'})
        }
        dashboard_stats['stations']['packaging'] = {
            'pending_count': packaging_pending,
            'today_m3': float(packaging_today_m3),
            'completed_today': packaging_completed_today,
            'pending_m3': float(packaging_pending_m3),
            'status': 'active' if packaging_pending > 0 else 'idle',
            'status_class': 'station-active' if packaging_pending > 0 else 'station-idle',
            'tablet_status': heartbeat_statuses.get('packaging', {'active': False, 'last_seen': None, 'status_label': 'Niedostępne'})
        }

        # Dzisiejsze ukończone zamówienia
        completed_today = ProductionItem.query.filter(
            ProductionItem.current_status == 'spakowane',
            ProductionItem.packaging_completed_at >= today_start
        ).count()

        total_m3_today = float(cutting_today_m3 + assembly_today_m3 + packaging_today_m3)

        dashboard_stats['today_totals'] = {
            'completed_orders': completed_today,
            'total_m3': total_m3_today,
            'avg_deadline_distance': 7.0  # Placeholder - będzie obliczane
        }

        # "In production now" — items currently being processed (not finished, not cancelled)
        mr_active_statuses = [
            'czeka_na_wyciecie', 'czeka_na_skladanie', 'czeka_na_sklejanie',
            'czeka_na_formatowanie', 'czeka_na_wykanczanie', 'czeka_na_pakowanie',
            'w_realizacji'
        ]
        in_prod_items = ProductionItem.query.filter(
            ProductionItem.current_status.in_(mr_active_statuses)
        ).all()
        in_prod_order_ids = set(
            item.baselinker_order_id for item in in_prod_items if item.baselinker_order_id
        )
        dashboard_stats['in_production'] = {
            'orders': len(in_prod_order_ids),
            'products': len(in_prod_items),
            'm3': round(sum(float(item.volume_m3 or 0) for item in in_prod_items), 2)
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
                'client_name': alert.client_name or 'Brak danych',
                'client_order_number': alert.client_order_number or '',
                'baselinker_order_id': alert.baselinker_order_id,
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
            'products_url': url_for('production.production_main.products_list'), 
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
            'products_url': '#', 
            'config_url': '#'
        }

logger.info("Zainicjalizowano Main routers zgodnie z PRD", extra={
    'blueprint_name': main_bp.name,
    'routers_count': 3,  # dashboard, products, config
    'prd_compliance': True
})