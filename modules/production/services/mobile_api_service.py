"""
Mobile API service — JWT, rejestracja urządzeń, serializacja DTO.

Obsługuje warstwę logiki dla blueprintu mobile_api_bp (natywna appka Android).
Router (`routers/mobile_api.py`) powinien być cienki — walidacja wejścia
i wywołanie funkcji z tego modułu.

Etap 1 MVP: obsługujemy packaging end-to-end (z tranzycją statusu), pozostałe
stanowiska tylko bump quantity_done + completed_at (workflow transitions
między stanowiskami zostają przy istniejącym web-handlerze).
"""

import ipaddress
from datetime import datetime, timedelta
from functools import wraps

import jwt
from flask import current_app, g, jsonify, request

from extensions import db
from modules.logging import get_structured_logger
from modules.production.models import (
    ProductionDevice,
    ProductionItem,
    get_local_now,
)

logger = get_structured_logger('production.mobile_api')

# ============================================================================
# MAPOWANIE STANOWISK
# ============================================================================

# station_code → current_status w bazie (queue filter)
STATION_STATUS_MAP = {
    'packaging': 'czeka_na_pakowanie',
    'cutting': 'czeka_na_wyciecie',
    'assembly': 'czeka_na_skladanie',
    'gluing': 'czeka_na_sklejanie',
    'formatting': 'czeka_na_formatowanie',
    'finishing': 'czeka_na_wykanczanie',
}

# station_code → nazwa kolumny z licznikiem wykonanych sztuk
STATION_QUANTITY_FIELD = {
    'packaging': 'quantity_done_packaging',
    'cutting': 'quantity_done_cutting',
    'assembly': 'quantity_done_assembly',
    'gluing': 'quantity_done_gluing',
    'formatting': 'quantity_done_formatting',
    'finishing': 'quantity_done_finishing',
}

# station_code → nazwa kolumny z timestampem ukończenia
STATION_COMPLETED_AT_FIELD = {
    'packaging': 'packaging_completed_at',
    'cutting': 'cutting_completed_at',
    'assembly': 'assembly_completed_at',
    'gluing': 'gluing_completed_at',
    'formatting': 'formatting_completed_at',
    'finishing': 'finishing_completed_at',
}

# Tranzycja statusu po ukończeniu stanowiska.
# Etap 1: tylko packaging. Pozostałe stanowiska obsługuje istniejący web-handler.
STATION_NEXT_STATUS = {
    'packaging': 'spakowane',
}


# ============================================================================
# KONFIGURACJA
# ============================================================================

def _get_config():
    return current_app.config.get('API_MOBILE', {})


def _get_jwt_secret():
    secret = _get_config().get('jwt_secret')
    if not secret or secret == 'WYGENERUJ_64_ZNAKOWY_LOSOWY_CIAG':
        raise RuntimeError(
            "API_MOBILE.jwt_secret nie jest skonfigurowany w config/core.json. "
            "Wygeneruj losowy 64-znakowy string."
        )
    return secret


# ============================================================================
# JWT
# ============================================================================

def generate_token(device):
    """Generuje JWT dla urządzenia. Domyślny expiry: 365 dni."""
    expiry_days = _get_config().get('jwt_expiry_days', 365)
    now = datetime.utcnow()
    payload = {
        'device_id': device.device_id,
        'station_code': device.station_code,
        'token_version': device.token_version,
        'iat': now,
        'exp': now + timedelta(days=expiry_days),
    }
    return jwt.encode(payload, _get_jwt_secret(), algorithm='HS256')


def validate_token(token):
    """
    Waliduje JWT. Zwraca (device, claims) lub rzuca ValueError.

    Sprawdza: podpis, exp, istnienie i aktywność urządzenia, zgodność token_version.
    token_version w claimach musi być równy wartości w bazie — jeśli admin
    zbumpował token_version (np. po kradzieży tabletu), wszystkie stare JWT
    przestają działać natychmiast.
    """
    try:
        claims = jwt.decode(token, _get_jwt_secret(), algorithms=['HS256'])
    except jwt.ExpiredSignatureError:
        raise ValueError('Token wygasł')
    except jwt.InvalidTokenError as e:
        raise ValueError(f'Token nieprawidłowy: {e}')

    device_id = claims.get('device_id')
    if not device_id:
        raise ValueError('Token bez device_id')

    device = ProductionDevice.query.filter_by(device_id=device_id).first()
    if not device:
        raise ValueError('Urządzenie nieznane')
    if not device.is_active:
        raise ValueError('Urządzenie zablokowane')
    if device.token_version != claims.get('token_version'):
        raise ValueError('Token unieważniony (token_version mismatch)')

    return device, claims


# ============================================================================
# IP WHITELIST (opcjonalny)
# ============================================================================

def _ip_in_whitelist(ip_str):
    """True gdy IP jest w whitelist LUB whitelist jest wyłączony w configu."""
    config = _get_config()
    if not config.get('require_ip_whitelist', False):
        return True
    whitelist = config.get('ip_whitelist', []) or []
    if not whitelist:
        return True
    try:
        ip = ipaddress.ip_address(ip_str)
    except (ValueError, TypeError):
        return False
    for cidr in whitelist:
        try:
            network = ipaddress.ip_network(cidr, strict=False)
            if ip in network:
                return True
        except ValueError:
            continue
    return False


def _version_too_old(actual, minimum):
    """SemVer comparison. True gdy actual < minimum."""
    try:
        a = tuple(int(x) for x in actual.split('.')[:3])
        m = tuple(int(x) for x in minimum.split('.')[:3])
        return a < m
    except (ValueError, AttributeError):
        return False


# ============================================================================
# DEKORATOR
# ============================================================================

def require_device_token(f):
    """
    Wymaga `Authorization: Bearer <JWT>`. Opcjonalnie sprawdza IP whitelist
    i minimalną wersję appki z `X-App-Version`.

    Po sukcesie wypełnia `g.device` i `g.claims`, touch'uje `last_seen_at`.
    """
    @wraps(f)
    def wrapper(*args, **kwargs):
        ip = request.environ.get('HTTP_X_FORWARDED_FOR', request.remote_addr)
        if ip and ',' in ip:
            ip = ip.split(',')[0].strip()

        if not _ip_in_whitelist(ip or ''):
            logger.warning("Mobile API: IP poza whitelist", extra={'ip': ip})
            return jsonify({'error': 'ip_not_allowed'}), 403

        auth_header = request.headers.get('Authorization', '')
        if not auth_header.startswith('Bearer '):
            return jsonify({'error': 'missing_token'}), 401
        token = auth_header[7:].strip()

        try:
            device, claims = validate_token(token)
        except ValueError as e:
            logger.warning("Mobile API: token invalid", extra={
                'ip': ip,
                'error': str(e)
            })
            return jsonify({'error': 'invalid_token', 'detail': str(e)}), 401

        app_version = request.headers.get('X-App-Version', '').strip()
        min_version = _get_config().get('min_supported_app_version', '0.0.0')
        if app_version and _version_too_old(app_version, min_version):
            return jsonify({
                'error': 'app_version_too_old',
                'min_supported': min_version,
                'your_version': app_version,
            }), 426

        try:
            device.touch(ip=ip, app_version=app_version or None)
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            logger.error("Mobile API: touch device failed", extra={'error': str(e)})

        g.device = device
        g.claims = claims
        return f(*args, **kwargs)
    return wrapper


# ============================================================================
# REJESTRACJA URZĄDZENIA
# ============================================================================

def register_device(device_id, device_name, station_code):
    """
    Idempotentna rejestracja urządzenia po device_id.
    Re-rejestracja: aktualizuje station_code/device_name, reaktywuje is_active.
    Zwraca (device, token).
    """
    device = ProductionDevice.query.filter_by(device_id=device_id).first()
    if device:
        device.station_code = station_code
        if device_name:
            device.device_name = device_name
        device.is_active = True
        logger.info("Mobile API: re-registration", extra={
            'device_id': device_id,
            'station_code': station_code,
        })
    else:
        device = ProductionDevice(
            device_id=device_id,
            device_name=device_name or None,
            station_code=station_code,
        )
        db.session.add(device)
        logger.info("Mobile API: new device registered", extra={
            'device_id': device_id,
            'station_code': station_code,
        })

    db.session.commit()
    token = generate_token(device)
    return device, token


# ============================================================================
# SERIALIZER: ProductionItem → OrderDto
# ============================================================================

def serialize_order(item, station_code=None):
    """
    ProductionItem → dict (OrderDto).
    Gdy podano station_code, dokłada quantity_done dla tego stanowiska.
    """
    def _num(value):
        return float(value) if value is not None else None

    def _iso(dt):
        return dt.isoformat() if dt else None

    dimensions = None
    if any([item.parsed_length_cm, item.parsed_width_cm, item.parsed_thickness_cm]):
        def _mm(cm):
            return int(float(cm) * 10) if cm is not None else None
        dimensions = {
            'length_mm': _mm(item.parsed_length_cm),
            'width_mm': _mm(item.parsed_width_cm),
            'thickness_mm': _mm(item.parsed_thickness_cm),
        }

    finish = None
    if item.parsed_finish_type and item.parsed_finish_type != 'surowe':
        finish = {
            'type': item.parsed_finish_type,
            'color_type': item.parsed_finish_color_type,
            'color': item.parsed_finish_color,
            'gloss': item.parsed_finish_gloss,
        }

    edge = None
    if item.parsed_edge_processing:
        edge = {
            'type': item.parsed_edge_type,
            'radius': item.parsed_edge_radius,
            'angle': item.parsed_edge_angle,
            'letters': item.parsed_edge_letters,
        }

    quantity_done = None
    if station_code and station_code in STATION_QUANTITY_FIELD:
        quantity_done = getattr(item, STATION_QUANTITY_FIELD[station_code], None)

    return {
        'id': item.id,
        'short_id': item.short_product_id,
        'internal_order_number': item.internal_order_number,
        'baselinker_order_id': item.baselinker_order_id,
        'product_name': item.original_product_name,
        'client_name': item.client_name,
        'client_order_number': item.client_order_number,
        'wood_species': item.parsed_wood_species,
        'wood_class': item.parsed_wood_class,
        'technology': item.parsed_technology,
        'dimensions': dimensions,
        'volume_m3': _num(item.volume_m3),
        'quantity_ordered': item.quantity,
        'quantity_done': quantity_done,
        'priority_rank': item.priority_rank,
        'is_priority': item.is_priority,
        'status': item.current_status,
        'status_display': item.status_display_name,
        'finish': finish,
        'edge': edge,
        'delivery_city': item.delivery_city,
        'delivery_postcode': item.delivery_postcode,
        'deadline': _iso(item.deadline_date) if item.deadline_date else None,
        'order_notes': item.order_notes,
        'updated_at': _iso(item.updated_at),
    }


# ============================================================================
# AKCJE NA ZLECENIACH
# ============================================================================

def mark_order_complete(item, station_code):
    """
    Oznacza zlecenie jako ukończone na danym stanowisku.

    Packaging (Etap 1 MVP): pełna tranzycja — quantity_done = quantity,
    completed_at = now, current_status = 'spakowane'.

    Pozostałe stanowiska: tylko quantity_done i completed_at. Zmiany statusu
    między stanowiskami są w obowiązku istniejącego web-handlera
    (endpoint `/production/stations/api/complete-task`) — nie duplikujemy
    tej logiki tu, dopóki Android nie obsługuje tych stanowisk.
    """
    quantity_field = STATION_QUANTITY_FIELD.get(station_code)
    completed_field = STATION_COMPLETED_AT_FIELD.get(station_code)
    if not quantity_field or not completed_field:
        raise ValueError(f'Nieznane stanowisko: {station_code}')

    setattr(item, quantity_field, item.quantity)
    setattr(item, completed_field, get_local_now())

    next_status = STATION_NEXT_STATUS.get(station_code)
    if next_status:
        item.current_status = next_status

    item.updated_at = get_local_now()


def update_order_quantity(item, station_code, quantity_done):
    """Aktualizuje liczbę ukończonych sztuk na stanowisku (0 <= qd <= item.quantity)."""
    quantity_field = STATION_QUANTITY_FIELD.get(station_code)
    if not quantity_field:
        raise ValueError(f'Nieznane stanowisko: {station_code}')

    if quantity_done < 0:
        raise ValueError('quantity_done nie może być ujemny')
    if quantity_done > item.quantity:
        raise ValueError(
            f'quantity_done ({quantity_done}) > quantity ({item.quantity})'
        )

    setattr(item, quantity_field, quantity_done)
    item.updated_at = get_local_now()

    if quantity_done == item.quantity:
        completed_field = STATION_COMPLETED_AT_FIELD.get(station_code)
        if completed_field and not getattr(item, completed_field, None):
            setattr(item, completed_field, get_local_now())
