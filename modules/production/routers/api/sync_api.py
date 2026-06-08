# modules/production/routers/api/sync_api.py
"""
Sync/cron, health checks, baselinker operations, cache clear endpoints.
Extracted from api_routers.py.
"""

import traceback
from datetime import datetime, date, timedelta
from flask import request, jsonify, current_app
from flask_login import login_required, current_user
from extensions import db
from sqlalchemy import text

from . import api_bp, logger, ProductionItem, ProductionError, ProductionSyncLog, ProductionConfig, get_local_now
from .common_api import admin_required, cron_secret_required
from modules.production.services.parser_service import parse_product_name, is_non_production_item


def order_has_blocking_parsing_error(processed_products):
    """
    Czy zamówienie ma blokujący błąd parsowania w podglądzie synchronizacji.

    Blokujemy tylko, gdy któryś NOWY produkt produkcyjny ma błąd parsowania.
    Pozycje usługowe/dopłaty (is_service_item) oraz produkty już w bazie
    (already_in_db) są pomijane — nie powinny blokować całego zamówienia.
    """
    return any(
        p.get('has_parsing_error', False) for p in processed_products
        if not p.get('already_in_db', False) and not p.get('is_service_item', False)
    )


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
        
        from ...services.sync_service import get_sync_service
        
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

        from ...services.sync_service import manual_sync_with_filtering as run_manual_sync_with_filtering

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
        
        from ...services.sync_service import get_sync_service
        
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
            from ...models import ProductionItem
            
            # Proste zapytanie testowe
            db.session.execute(db.text('SELECT 1')).scalar()
            health_data['database'] = 'connected'
            
            # Sprawdzenie liczby oczekujących błędów
            from ...models import ProductionError
            pending_errors = ProductionError.query.filter_by(is_resolved=False).count()
            health_data['pending_errors'] = pending_errors
            
        except Exception as e:
            health_data['database'] = 'error'
            health_data['status'] = 'unhealthy'
            logger.warning("Health check: Błąd bazy danych", extra={'error': str(e)})
        
        # Status ostatniej synchronizacji
        try:
            from ...services.sync_service import get_sync_status
            
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
            from ...services.config_service import get_config_service
            
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
                from ...models import ProductionItem
                
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
        from ...services.baselinker_status_service import get_baselinker_statuses
        
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

        # Pobierz istniejące zamówienia z bazy danych
        from ...models import ProductionItem, ProductionOrder

        # Zbierz wszystkie baselinker_order_id z pobranych zamówień
        baselinker_ids = [order.get('order_id') for order in all_orders if order.get('order_id')]

        # Pobierz istniejące produkty z bazy pogrupowane po baselinker_order_id
        existing_products_query = db.session.query(
            ProductionOrder.baselinker_order_id,
            ProductionItem.original_product_name
        ).join(ProductionOrder, ProductionItem.order_id == ProductionOrder.id).filter(
            ProductionOrder.baselinker_order_id.in_(baselinker_ids)
        ).all()

        # Stwórz mapę: baselinker_order_id -> set(nazwy produktów)
        existing_orders_map = {}
        for bl_id, product_name in existing_products_query:
            if bl_id not in existing_orders_map:
                existing_orders_map[bl_id] = set()
            if product_name:
                existing_orders_map[bl_id].add(product_name.strip().lower())

        orders_skipped_complete = 0
        orders_with_missing_products = 0

        for order in all_orders:
            order_status = order.get('order_status_id') or order.get('status_id')
            if order_status in status_ids_set:
                baselinker_order_id = order.get('order_id')

                # Sprawdź czy zamówienie istnieje w bazie
                existing_product_names = existing_orders_map.get(baselinker_order_id, set())

                # Przetwórz produkty i sprawdź które już istnieją
                if 'products' in order and order['products']:
                    processed_products = []
                    has_new_products = False

                    for product in order['products']:
                        product_name = product.get('name', 'Bez nazwy')
                        product_name_lower = product_name.strip().lower()

                        # Sprawdź czy produkt już istnieje w bazie
                        already_exists = product_name_lower in existing_product_names

                        if not already_exists:
                            has_new_products = True

                        # Parsuj dane produktu z nazwy
                        parsed_result = parse_product_name(product_name)
                        parsed_technology = parsed_result.get('technology')
                        parsed_wood_species = parsed_result.get('wood_species')
                        parsed_wood_class = parsed_result.get('wood_class')
                        parsed_finish_type = parsed_result.get('finish_type')
                        parsed_finish_display = parsed_result.get('finish_state')

                        # Wymiary sformatowane
                        length = parsed_result.get('length_cm')
                        width = parsed_result.get('width_cm')
                        thickness = parsed_result.get('thickness_cm')
                        parsed_dimensions = None
                        if length and width and thickness:
                            def fmt(v):
                                v = float(v)
                                return str(int(v)) if v == int(v) else str(v)
                            parsed_dimensions = f"{fmt(length)}×{fmt(width)}×{fmt(thickness)}"

                        # Walidacja
                        is_valid_technology = parsed_technology in ('mikrowczep', 'lity')
                        is_valid_species = parsed_wood_species is not None
                        is_valid_class = parsed_wood_class is not None
                        is_valid_dimensions = parsed_dimensions is not None
                        is_valid_finish = parsed_finish_type is not None

                        has_parsing_error = not all([
                            is_valid_technology, is_valid_species, is_valid_class,
                            is_valid_dimensions, is_valid_finish
                        ])

                        # Pozycja usługowa/dopłata (np. "Docięcie do wymiaru - usługa...")
                        # — fraza usługi ORAZ brak wymiarów. Takie pozycje nie są produktem
                        # do produkcji i nie powinny blokować zamówienia jako błąd parsowania.
                        is_service_item = is_non_production_item(product_name) and not is_valid_dimensions

                        processed_products.append({
                            'name': product_name,
                            'sku': product.get('sku', ''),
                            'variant': product.get('variant', ''),
                            'quantity': float(product.get('quantity', 0)),
                            'price': float(product.get('price_brutto', 0)),
                            'unit': product.get('unit', 'szt.'),
                            'already_in_db': already_exists,
                            'is_service_item': is_service_item,
                            'parsed_technology': parsed_technology,
                            'parsed_wood_species': parsed_wood_species,
                            'parsed_wood_class': parsed_wood_class,
                            'parsed_dimensions': parsed_dimensions,
                            'parsed_finish_type': parsed_finish_type,
                            'parsed_finish_display': parsed_finish_display,
                            'unknown_technology': not is_valid_technology,
                            'unknown_species': not is_valid_species,
                            'unknown_class': not is_valid_class,
                            'unknown_dimensions': not is_valid_dimensions,
                            'unknown_finish': not is_valid_finish,
                            'has_parsing_error': has_parsing_error,
                        })

                    order['products'] = processed_products

                    # Jeśli wszystkie produkty już istnieją - pomiń zamówienie
                    if existing_product_names and not has_new_products:
                        orders_skipped_complete += 1
                        continue

                    # Oznacz zamówienie jako częściowo istniejące
                    if existing_product_names and has_new_products:
                        order['partially_exists'] = True
                        order['existing_products_count'] = len(existing_product_names)
                        orders_with_missing_products += 1
                    else:
                        order['partially_exists'] = False
                        order['existing_products_count'] = 0

                # Zamówienie ma błąd parsowania tylko jeśli któryś NOWY produkt
                # produkcyjny (nie usługa) jest nieparsowalny. Pozycje usługowe
                # nie blokują zamówienia.
                has_parsing_error = order_has_blocking_parsing_error(processed_products)
                order['parsing_error'] = has_parsing_error
                # Backwards compatibility
                order['technology_error'] = has_parsing_error

                # Dodaj dodatkowe pola dla frontendu
                order['id'] = baselinker_order_id
                order['customer_name'] = order.get('delivery_fullname') or order.get('buyer_name') or 'Brak nazwy'
                order['baselinker_order_id'] = baselinker_order_id
                order['status_id'] = order_status
                order['order_date'] = order.get('date_add')

                filtered_orders.append(order)
        
        logger.info("API: Zamówienia pobrane pomyślnie", extra={
            'total_orders': len(all_orders),
            'filtered_orders': len(filtered_orders),
            'orders_skipped_complete': orders_skipped_complete,
            'orders_with_missing_products': orders_with_missing_products,
            'pages_processed': pages_processed,
            'user_id': current_user.id
        })

        return jsonify({
            'success': True,
            'orders': filtered_orders,
            'pages_processed': pages_processed,
            'total_count': len(all_orders),
            'filtered_count': len(filtered_orders),
            'orders_skipped_complete': orders_skipped_complete,
            'orders_with_missing_products': orders_with_missing_products,
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
            from ...services.sync_service import manual_sync_with_filtering, get_sync_service
            
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
        from ...services.config_service import get_config_service
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



