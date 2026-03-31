# modules/production/routers/api/config_api.py
"""
Config tab content + config management endpoints.
Extracted from api_routers.py.
"""

import json
import traceback
from datetime import datetime, date, timedelta
from flask import request, jsonify, render_template
from flask_login import login_required, current_user
from extensions import db

from . import api_bp, logger, ProductionItem, ProductionConfig, ProductionPriorityConfig, get_local_now
from .common_api import admin_required, _validate_config_value


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
        
        from ...models import ProductionConfig
        
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

        from ...models import ProductionConfig, ProductionPriorityConfig
        from ...services.config_service import get_config_service

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
        
        from ...services.config_service import ProductionConfigService
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
        from ...services.config_service import get_config_service
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
        from ...services.config_service import get_config_service
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
        from ...services.config_service import get_config_service
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
        from ...models import ProductionConfig
        from ...services.config_service import get_config_service
        
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


# ============================================================================
# PRIORITY STAR ENDPOINTS - Gwiazdka priorytetu dla produktów
# ============================================================================


