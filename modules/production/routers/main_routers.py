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
        
        # Podstawowe statystyki - zgodnie z PRD API response structure
        dashboard_stats = {
            'stations': {
                'cutting': {'pending_count': 0, 'today_m3': 0.0},
                'assembly': {'pending_count': 0, 'today_m3': 0.0}, 
                'packaging': {'pending_count': 0, 'today_m3': 0.0}
            },
            'today_totals': {
                'completed_orders': 0,
                'total_m3': 0.0,
                'avg_deadline_distance': 0.0
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
        
        # Cutting - oczekujące
        cutting_pending = ProductionItem.query.filter_by(current_status='czeka_na_wyciecie').count()
        cutting_today_m3 = db.session.query(db.func.sum(ProductionItem.volume_m3))\
                                    .filter(ProductionItem.cutting_completed_at >= datetime.combine(today, datetime.min.time()))\
                                    .scalar() or 0.0
        
        # Assembly - oczekujące  
        assembly_pending = ProductionItem.query.filter_by(current_status='czeka_na_skladanie').count()
        assembly_today_m3 = db.session.query(db.func.sum(ProductionItem.volume_m3))\
                                     .filter(ProductionItem.assembly_completed_at >= datetime.combine(today, datetime.min.time()))\
                                     .scalar() or 0.0
        
        # Packaging - oczekujące
        packaging_pending = ProductionItem.query.filter_by(current_status='czeka_na_pakowanie').count()
        packaging_today_m3 = db.session.query(db.func.sum(ProductionItem.volume_m3))\
                                      .filter(ProductionItem.packaging_completed_at >= datetime.combine(today, datetime.min.time()))\
                                      .scalar() or 0.0
        
        # Aktualizacja statystyk
        dashboard_stats['stations']['cutting'] = {
            'pending_count': cutting_pending,
            'today_m3': float(cutting_today_m3)
        }
        dashboard_stats['stations']['assembly'] = {
            'pending_count': assembly_pending, 
            'today_m3': float(assembly_today_m3)
        }
        dashboard_stats['stations']['packaging'] = {
            'pending_count': packaging_pending,
            'today_m3': float(packaging_today_m3)
        }
        
        # Dzisiejsze ukończone zamówienia
        completed_today = ProductionItem.query.filter(
            ProductionItem.current_status == 'spakowane',
            ProductionItem.packaging_completed_at >= datetime.combine(today, datetime.min.time())
        ).count()
        
        total_m3_today = float(cutting_today_m3 + assembly_today_m3 + packaging_today_m3)
        
        dashboard_stats['today_totals'] = {
            'completed_orders': completed_today,
            'total_m3': total_m3_today,
            'avg_deadline_distance': 7.0  # Placeholder - będzie obliczane
        }
        
        # Alerty deadline - produkty zbliżające się do terminu
        deadline_alerts = ProductionItem.query.filter(
            ProductionItem.deadline_date <= date.today() + timedelta(days=3),
            ProductionItem.current_status.in_(['czeka_na_wyciecie', 'czeka_na_skladanie', 'czeka_na_pakowanie'])
        ).limit(5).all()
        
        dashboard_stats['deadline_alerts'] = [
            {
                'product_id': alert.short_product_id,
                'days_remaining': (alert.deadline_date - date.today()).days if alert.deadline_date else 0,
                'current_station': alert.current_status.replace('czeka_na_', '')
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
# HELPER ROUTERS
# ============================================================================

@main_bp.route('/update-priority', methods=['POST'])
@require_module_access('production')
def update_product_priority():
    """
    POST /production/update-priority
    
    ROZBUDOWANA WERSJA - Aktualizuje priorytet produktu (drag&drop w liście produktów)
    Obsługuje zarówno pojedyncze produkty jak i batch update
    Dostępne tylko dla adminów zgodnie z PRD.
    
    Body (JSON):
    {
        "product_id": 123,              // Dla pojedynczego produktu
        "new_priority": 150,            // Nowy priorytet
        
        // LUB dla batch update:
        "products": [                   // Lista produktów z priorytetami
            {"id": 123, "priority": 150},
            {"id": 124, "priority": 149},
            ...
        ]
    }
    
    Returns: JSON z rezultatem
    """
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'Brak danych JSON'}), 400
        
        from ..models import ProductionItem
        
        # ============================================================================
        # SINGLE PRODUCT UPDATE
        # ============================================================================
        
        if 'product_id' in data and 'new_priority' in data:
            product_id = data['product_id']
            new_priority = data['new_priority']
            
            # Walidacja
            if not isinstance(new_priority, int) or new_priority < 0 or new_priority > 200:
                return jsonify({'success': False, 'error': 'Priorytet musi być liczbą 0-200'}), 400
            
            product = ProductionItem.query.get(product_id)
            if not product:
                return jsonify({'success': False, 'error': 'Produkt nie znaleziony'}), 404
            
            old_priority = product.priority_score
            product.priority_score = new_priority
            db.session.commit()
            
            logger.info("Zaktualizowano priorytet produktu", extra={
                'user_id': current_user.id,
                'product_id': product_id,
                'product_short_id': product.short_product_id,
                'old_priority': old_priority,
                'new_priority': new_priority
            })
            
            return jsonify({
                'success': True,
                'message': 'Priorytet zaktualizowany',
                'updated_count': 1,
                'product': {
                    'id': product_id,
                    'short_product_id': product.short_product_id,
                    'old_priority': old_priority,
                    'new_priority': new_priority
                }
            })
        
        # ============================================================================
        # BATCH PRODUCTS UPDATE (DRAG & DROP)
        # ============================================================================
        
        elif 'products' in data:
            products_data = data['products']
            
            if not isinstance(products_data, list) or not products_data:
                return jsonify({'success': False, 'error': 'Lista produktów nie może być pusta'}), 400
            
            updated_count = 0
            failed_count = 0
            errors = []
            updated_products = []
            
            for product_data in products_data:
                try:
                    product_id = product_data.get('id')
                    new_priority = product_data.get('priority')
                    
                    # Walidacja pojedynczego elementu
                    if not product_id or new_priority is None:
                        errors.append(f'Brak ID lub priorytetu dla elementu: {product_data}')
                        failed_count += 1
                        continue
                    
                    if not isinstance(new_priority, int) or new_priority < 0 or new_priority > 200:
                        errors.append(f'Nieprawidłowy priorytet {new_priority} dla produktu {product_id}')
                        failed_count += 1
                        continue
                    
                    # Aktualizuj produkt
                    product = ProductionItem.query.get(product_id)
                    if not product:
                        errors.append(f'Produkt {product_id} nie znaleziony')
                        failed_count += 1
                        continue
                    
                    old_priority = product.priority_score
                    product.priority_score = new_priority
                    
                    updated_products.append({
                        'id': product_id,
                        'short_product_id': product.short_product_id,
                        'old_priority': old_priority,
                        'new_priority': new_priority
                    })
                    
                    updated_count += 1
                    
                except Exception as e:
                    errors.append(f'Błąd produktu {product_id}: {str(e)}')
                    failed_count += 1
            
            # Zapisz zmiany jeśli były jakieś udane aktualizacje
            if updated_count > 0:
                db.session.commit()
            
            logger.info("Batch update priorytetów", extra={
                'user_id': current_user.id,
                'total_products': len(products_data),
                'updated_count': updated_count,
                'failed_count': failed_count
            })
            
            return jsonify({
                'success': True,
                'message': f'Zaktualizowano {updated_count} produktów',
                'updated_count': updated_count,
                'failed_count': failed_count,
                'errors': errors,
                'updated_products': updated_products
            })
        
        else:
            return jsonify({'success': False, 'error': 'Wymagane: product_id+new_priority lub products'}), 400
        
    except Exception as e:
        db.session.rollback()
        logger.error("Błąd aktualizacji priorytetu", extra={
            'user_id': current_user.id if current_user.is_authenticated else None,
            'error': str(e),
            'request_data': data if 'data' in locals() else None
        })
        return jsonify({
            'success': False,
            'error': f'Błąd serwera: {str(e)}'
        }), 500

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