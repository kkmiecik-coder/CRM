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
import json
from datetime import datetime, time, timedelta, timezone
from functools import wraps
from pathlib import Path

import jwt
import pytz
from flask import current_app, g, jsonify, request
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from extensions import db
from modules.logging import get_structured_logger
from modules.production.models import (
    ProcessedMobileOperation,
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
# IDEMPOTENCY (X-Operation-Id)
# ============================================================================

def with_idempotency(f):
    """
    Decorator dla endpointów mutujących stan (POST /complete, PATCH /quantity).
    Obsługuje nagłówek X-Operation-Id:
    - brak → zachowanie bez zmian (decorator committuje 2xx/4xx, rollback 5xx)
    - istnieje w bazie → zwraca zapisany response, bez wywoływania handlera
    - nowy → wywołuje handler, zapisuje response w jednej transakcji (tylko 2xx/4xx)

    5xx i nieobsłużone wyjątki → rollback + re-raise, wpis NIE zapisywany
    (żeby klient mógł retry). Handler MUSI zwracać (response, status)
    i NIE MOŻE wewnątrz wywoływać db.session.commit() — zrobi to decorator.
    """
    @wraps(f)
    def wrapper(*args, **kwargs):
        op_id = request.headers.get('X-Operation-Id', '').strip()

        # Replay dla znanego op_id
        if op_id:
            existing = ProcessedMobileOperation.query.filter_by(
                operation_id=op_id
            ).first()
            if existing:
                logger.info("Mobile API idempotent replay", extra={
                    'operation_id': op_id,
                    'endpoint': existing.endpoint,
                    'original_status': existing.response_status,
                })
                try:
                    body = json.loads(existing.response_body)
                except (ValueError, TypeError):
                    body = {}
                return jsonify(body), existing.response_status

        # Handler wykonuje akcję (bez commit)
        try:
            result = f(*args, **kwargs)
        except Exception as e:
            db.session.rollback()
            logger.error("Mobile API handler exception", extra={
                'endpoint': request.endpoint,
                'operation_id': op_id or None,
                'error': str(e),
            })
            raise  # Flask error handler → 500, NIE zapisujemy w idempotency

        # Normalizacja wyniku
        if isinstance(result, tuple):
            response_obj = result[0]
            status_code = int(result[1]) if len(result) >= 2 else 200
        else:
            response_obj = result
            status_code = getattr(response_obj, 'status_code', 200)

        # 5xx → rollback, nie zapisuj (klient retry)
        if status_code >= 500:
            db.session.rollback()
            return response_obj, status_code

        # 2xx / 4xx — commit, zapisz operation_id w tej samej transakcji
        if op_id:
            try:
                body_dict = (
                    response_obj.get_json()
                    if hasattr(response_obj, 'get_json')
                    else response_obj
                )
                body_json = json.dumps(body_dict, ensure_ascii=False)
            except Exception:
                body_json = '{}'

            op_record = ProcessedMobileOperation(
                operation_id=op_id,
                endpoint=request.endpoint or 'unknown',
                order_id=kwargs.get('order_id'),
                device_id=g.device.device_id if hasattr(g, 'device') else None,
                response_status=status_code,
                response_body=body_json,
            )
            db.session.add(op_record)

            try:
                db.session.commit()
            except IntegrityError:
                # Race: równoczesny request z tym samym op_id zdążył commit pierwszy.
                # Rollback naszej sesji i zwróć zapisany przez rywala response.
                db.session.rollback()
                existing = ProcessedMobileOperation.query.filter_by(
                    operation_id=op_id
                ).first()
                if existing:
                    logger.info("Mobile API idempotent race resolved", extra={
                        'operation_id': op_id,
                        'winning_status': existing.response_status,
                    })
                    try:
                        body = json.loads(existing.response_body)
                    except (ValueError, TypeError):
                        body = {}
                    return jsonify(body), existing.response_status
                logger.error(
                    "Mobile API IntegrityError bez istniejącego wpisu",
                    extra={'operation_id': op_id},
                )
                return jsonify({'error': 'idempotency_conflict'}), 500
        else:
            db.session.commit()

        return response_obj, status_code
    return wrapper


def cleanup_old_operations(older_than_days=7):
    """
    Usuwa wpisy z processed_mobile_operations starsze niż older_than_days dni.
    Używane przez `flask cleanup-mobile-operations` CLI command.

    Returns:
        int: liczba usuniętych wierszy
    """
    cutoff = get_local_now() - timedelta(days=older_than_days)
    deleted = ProcessedMobileOperation.query.filter(
        ProcessedMobileOperation.processed_at < cutoff
    ).delete(synchronize_session=False)
    db.session.commit()
    logger.info("Mobile API: cleanup zakończony", extra={
        'deleted_count': deleted,
        'older_than_days': older_than_days,
        'cutoff': cutoff.isoformat(),
    })
    return deleted


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

_ATTACHMENT_MIME_BY_EXT = {
    'jpg': 'image/jpeg',
    'jpeg': 'image/jpeg',
    'png': 'image/png',
    'gif': 'image/gif',
    'webp': 'image/webp',
    'pdf': 'application/pdf',
}


def _build_attachments(item):
    """
    Lista załączników dla OrderDto.

    Etap 1.5: tylko załącznik z Baselinker (ProductionItem.attachment_file_url) —
    publiczny URL CDN, tablet pobiera bezpośrednio (bez Authorization). Quote
    attachments (quote_item_detail_id → Quote.attachment_stored_name) są pominięte
    — ich endpoint `/quotes/api/attachment/<name>` wymaga sesji Flask-Login,
    więc nieosiągalny z JWT tabletu. Wymagałby osobnego proxy pod require_device_token.

    size_bytes = 0 — Baselinker nie zwraca rozmiaru, a HEAD na każde serialize
    byłby zbyt drogi. Android użyje Content-Length z response przy pobieraniu.
    """
    url = (item.attachment_file_url or '').strip()
    if not url:
        return []

    name = (item.attachment_file_name or '').strip() or url.rsplit('/', 1)[-1]
    ext = name.rsplit('.', 1)[-1].lower() if '.' in name else ''
    mime_type = _ATTACHMENT_MIME_BY_EXT.get(ext, 'application/octet-stream')

    return [{
        'url': url,
        'name': name,
        'mime_type': mime_type,
        'size_bytes': 0,
    }]


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

    # Kategoria dostawy — kolejność warunków 1:1 z web-templatką
    # modules/production/templates/stations/packaging.html (delivery-badge-container).
    # Odrębna od property ProductionItem.delivery_type (zwracającej tylko 2 wartości).
    if item.override_delivery_method == 'transport_woodpower':
        delivery_type = 'transport_woodpower'
    elif item.override_delivery_method == 'kurier_baselinker':
        delivery_type = 'courier_baselinker'
    elif item.is_personal_pickup:
        delivery_type = 'personal_pickup'
    else:
        delivery_type = 'courier'

    return {
        'id': item.id,
        'short_id': item.short_product_id,
        'internal_order_number': item.internal_order_number,
        'baselinker_order_id': item.baselinker_order_id,
        'product_name': item.original_product_name,
        'client_name': item.client_name,
        'client_order_number': item.client_order_number,
        'delivery_type': delivery_type,
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
        'attachments': _build_attachments(item),
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


# ============================================================================
# APP VERSION / APK HOSTING
# ============================================================================

def get_app_version_info():
    """Metadane wersji appki Android (publiczne — appka pyta przed rejestracją)."""
    cfg = _get_config()
    apk_path = _resolve_apk_path()
    apk_size = apk_path.stat().st_size if (apk_path and apk_path.is_file()) else None

    return {
        'latest_version': cfg.get('current_app_version'),
        'min_supported_version': cfg.get('min_supported_app_version', '0.0.0'),
        'apk_url': '/api/mobile/app/apk',
        'apk_hosted': apk_size is not None,
        'apk_size_bytes': apk_size,
        'release_notes_url': cfg.get('release_notes_url'),
    }


def _resolve_apk_path():
    """Zwraca Path do hostowanego APK lub None."""
    cfg = _get_config()
    raw = cfg.get('apk_file_path')
    if not raw:
        return None
    path = Path(raw)
    if not path.is_absolute():
        path = Path(current_app.root_path) / path
    return path


def stream_apk_response():
    """Zwraca Flask response z plikiem APK lub 404 JSON."""
    from flask import send_file
    path = _resolve_apk_path()
    if not path or not path.is_file():
        return jsonify({
            'error': 'apk_not_hosted',
            'detail': 'Plik APK nie jest jeszcze udostępniony. Skontaktuj się z adminem.',
        }), 404
    return send_file(
        str(path),
        mimetype='application/vnd.android.package-archive',
        as_attachment=True,
        download_name=path.name,
    )


# ============================================================================
# SUMMARY (dashboard stanowiska)
# ============================================================================

def _today_range_warsaw():
    """(today_start, tomorrow_start) jako naive datetimes w strefie Warszawy."""
    now_pl = get_local_now()
    today_start = datetime.combine(now_pl.date(), time.min)
    tomorrow_start = today_start + timedelta(days=1)
    return today_start, tomorrow_start


def compute_station_summary(station_code):
    """
    Metryki stanowiska:
    - queue: count aktualnie oczekujących + łączne m³ + ile priorytetów
    - completed_today: count ukończonych dzisiaj + łączne m³ (na tym stanowisku)
    """
    status = STATION_STATUS_MAP.get(station_code)
    completed_field_name = STATION_COMPLETED_AT_FIELD.get(station_code)
    if not status or not completed_field_name:
        raise ValueError(f'Nieznane stanowisko: {station_code}')

    queue_agg = db.session.query(
        func.count(ProductionItem.id),
        func.coalesce(func.sum(ProductionItem.volume_m3 * ProductionItem.quantity), 0),
        func.sum(
            db.case(
                (ProductionItem.is_priority == True, 1),  # noqa: E712
                else_=0,
            )
        ),
    ).filter(ProductionItem.current_status == status).one()

    today_start, tomorrow_start = _today_range_warsaw()
    completed_field = getattr(ProductionItem, completed_field_name)
    completed_agg = db.session.query(
        func.count(ProductionItem.id),
        func.coalesce(func.sum(ProductionItem.volume_m3 * ProductionItem.quantity), 0),
    ).filter(
        completed_field >= today_start,
        completed_field < tomorrow_start,
    ).one()

    # Częstotliwość auto-refresh listy zleceń (klient mobilny używa jej zamiast
    # hardcoded 30s). Źródło: config_service z tabeli ProductionConfig,
    # fallback 30 zgodny z ProductionConfigService._default_values.
    from modules.production.services.config_service import get_config_service
    try:
        refresh_interval = int(
            get_config_service().get_config('REFRESH_INTERVAL_SECONDS', 30)
        )
    except Exception as e:
        logger.warning("Nie udało się pobrać REFRESH_INTERVAL_SECONDS, fallback 30", extra={
            'error': str(e)
        })
        refresh_interval = 30

    return {
        'station_code': station_code,
        'queue': {
            'count': int(queue_agg[0] or 0),
            'total_volume_m3': float(queue_agg[1] or 0),
            'priority_count': int(queue_agg[2] or 0),
        },
        'completed_today': {
            'count': int(completed_agg[0] or 0),
            'total_volume_m3': float(completed_agg[1] or 0),
        },
        'refresh_interval_seconds': refresh_interval,
        'server_time': get_local_now().isoformat(),
    }


# ============================================================================
# DELTA SYNC
# ============================================================================

def parse_since_ts(ts_str):
    """
    Parsuje ISO 8601 timestamp do naive datetime w strefie Warszawy.
    Akceptuje: '2026-04-23T14:00:00Z', '2026-04-23T14:00:00+00:00', '2026-04-23T14:00:00'.
    Timestamp bez strefy traktowany jako UTC.
    """
    if not ts_str:
        raise ValueError('ts is required')
    s = ts_str.strip().replace('Z', '+00:00')
    try:
        dt = datetime.fromisoformat(s)
    except ValueError as e:
        raise ValueError(f'Invalid ISO timestamp: {e}')

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    warsaw = pytz.timezone('Europe/Warsaw')
    return dt.astimezone(warsaw).replace(tzinfo=None)


def get_station_queue_delta(station_code, since_ts):
    """
    Delta sync dla stanowiska. Zwraca:
    - all_ids: lista wszystkich zleceń aktualnie w kolejce (do wykrycia usunięć po stronie klienta)
    - changed: pełne DTO dla zleceń z updated_at > since_ts

    Klient po otrzymaniu:
    - usuwa ze swojego cache'u te których nie ma w all_ids
    - aktualizuje DTO dla zleceń z listy changed
    """
    status = STATION_STATUS_MAP.get(station_code)
    if not status:
        raise ValueError(f'Nieznane stanowisko: {station_code}')

    base = ProductionItem.query.filter(ProductionItem.current_status == status)

    all_ids = [
        row[0] for row in base.with_entities(ProductionItem.id)
        .order_by(
            func.coalesce(ProductionItem.priority_rank, 999999).asc(),
            ProductionItem.created_at.asc(),
        ).all()
    ]

    changed_items = base.filter(
        ProductionItem.updated_at > since_ts
    ).order_by(
        func.coalesce(ProductionItem.priority_rank, 999999).asc(),
        ProductionItem.created_at.asc(),
    ).all()

    return {
        'station_code': station_code,
        'server_time': get_local_now().isoformat(),
        'since_ts': since_ts.isoformat(),
        'all_ids': all_ids,
        'changed': [serialize_order(it, station_code=station_code) for it in changed_items],
    }
