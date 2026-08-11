# modules/production/routers/api/common_api.py
"""
Common decorators, error handlers, middleware, and utility functions
shared across all API sub-modules.

Extracted from api_routers.py.
"""

from functools import wraps
from flask import request, jsonify
from flask_login import login_required, current_user
from modules.logging import get_structured_logger

logger = get_structured_logger('production.api')


# ============================================================================
# DECORATORS
# ============================================================================

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
        from flask import current_app
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

# Dekorator ip_validation_required() usunięto w Etapie 0 profili pracowników -
# jego jedynym użytkownikiem był POST /production/api/complete-task z panelu
# webowego stanowiska. Mobile API ma własną autoryzację (JWT), a monitory hali
# chroni ip_security_middleware() podpięty pod station_bp.


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
    import json
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


def _format_status(status):
    """Formatuje status do czytelnej postaci"""
    status_names = {
        'czeka_na_wyciecie': 'Czeka na wycięcie',
        'czeka_na_skladanie': 'Czeka na składanie',
        'czeka_na_sklejanie': 'Czeka na sklejanie',
        'czeka_na_formatowanie': 'Czeka na formatowanie',
        'czeka_na_wykanczanie': 'Czeka na wykańczanie',
        'czeka_na_pakowanie': 'Czeka na pakowanie',
        'spakowane': 'Spakowane',
        'anulowane': 'Anulowane',
        'wstrzymane': 'Wstrzymane',
        'w_realizacji': 'W realizacji'
    }
    return status_names.get(status, status)


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
        from . import get_local_now
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
# ERROR HANDLERS & MIDDLEWARE (registered via functions)
# ============================================================================

def register_error_handlers(bp):
    """Register all API error handlers on the given blueprint."""

    @bp.errorhandler(400)
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

    @bp.errorhandler(401)
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

    @bp.errorhandler(403)
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

    @bp.errorhandler(404)
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

    @bp.errorhandler(405)
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

    @bp.errorhandler(500)
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


def register_middleware(bp):
    """Register before_request / after_request hooks on the given blueprint."""

    @bp.before_request
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

    @bp.after_request
    def add_api_headers(response):
        """Dodaje nagłówki do wszystkich odpowiedzi API"""
        try:
            # Nagłówki dla API
            response.headers['Content-Type'] = 'application/json; charset=utf-8'
            response.headers['X-API-Version'] = '1.0'
            response.headers['X-Production-Module'] = 'WoodPower-Production-API'

            return response
        except Exception as e:
            logger.error("Błąd dodawania nagłówków API", extra={'error': str(e)})
            return response
