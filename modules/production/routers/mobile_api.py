"""
Mobile API router — endpointy REST dla natywnej aplikacji Android.

Blueprint zarejestrowany w app.py pod prefixem `/api/mobile`.
Logika biznesowa w `services/mobile_api_service.py` — router jest cienki.
"""

from flask import Blueprint, g, jsonify, request
from sqlalchemy import func

from extensions import db
from modules.logging import get_structured_logger
from modules.production.models import ProductionDevice, ProductionItem
from modules.production.services.mobile_api_service import (
    STATION_STATUS_MAP,
    compute_station_summary,
    device_can_access_station,
    get_app_version_info,
    get_station_queue_delta,
    mark_order_complete,
    parse_since_ts,
    register_device,
    require_device_token,
    serialize_order,
    stream_apk_response,
    update_order_quantity,
    with_idempotency,
)


def _resolve_station_code(requested):
    """
    Rozstrzyga station_code dla operacji mutującej. Gdy klient nie poda
    `station_code` w body, używamy `g.device.station_code` (BC). Zwraca
    (station_code, error_response) — gdy error_response != None, wywołujący
    powinien zwrócić go natychmiast.
    """
    code = (requested or g.device.station_code or '').strip()
    if not code:
        return None, (jsonify({'error': 'missing_station_code'}), 400)
    if code not in STATION_STATUS_MAP:
        return None, (jsonify({'error': 'unknown_station'}), 404)
    if not device_can_access_station(g.device, code):
        return None, (jsonify({
            'error': 'station_mismatch',
            'device_station': g.device.station_code,
            'requested_station': code,
        }), 403)
    return code, None

logger = get_structured_logger('production.mobile_api.routes')

mobile_api_bp = Blueprint('mobile_api', __name__)


# ============================================================================
# REJESTRACJA URZĄDZENIA
# ============================================================================

@mobile_api_bp.route('/register', methods=['POST'])
def register():
    """
    POST /api/mobile/register

    Body JSON: { device_id: str, device_name: str?, station_code: str }
    Response: { token: str, device_id: str, station_code: str }

    Idempotentne — powtórna rejestracja tego samego device_id aktualizuje
    wpis (nowe station_code / device_name) i zwraca nowy token.
    """
    data = request.get_json(silent=True) or {}
    device_id = (data.get('device_id') or '').strip()
    device_name = (data.get('device_name') or '').strip()
    station_code = (data.get('station_code') or '').strip()

    if not device_id or not station_code:
        return jsonify({
            'error': 'missing_fields',
            'required': ['device_id', 'station_code'],
        }), 400

    if station_code not in ProductionDevice.VALID_STATION_CODES:
        return jsonify({
            'error': 'invalid_station_code',
            'allowed': sorted(ProductionDevice.VALID_STATION_CODES),
        }), 400

    try:
        device, token = register_device(device_id, device_name, station_code)
    except Exception as e:
        db.session.rollback()
        logger.error("Mobile API register failed", extra={
            'device_id': device_id,
            'error': str(e),
        })
        return jsonify({'error': 'registration_failed', 'detail': str(e)}), 500

    return jsonify({
        'token': token,
        'device_id': device.device_id,
        'station_code': device.station_code,
    }), 200


# ============================================================================
# ZLECENIA
# ============================================================================

@mobile_api_bp.route('/stations/<station_code>/orders', methods=['GET'])
@require_device_token
def station_orders(station_code):
    """
    GET /api/mobile/stations/<station_code>/orders

    Zwraca WSZYSTKIE pozycje z zamówień, w których cokolwiek wisi na danym
    stanowisku — także pozycje sąsiednich stanowisk z tego samego zamówienia.
    Pozwala mobile renderować pełny stan zamówienia z badge'em sąsiada
    (parytet z webem, templates/stations/*.html).

    Urządzenie musi być zarejestrowane pod TEGO stanowiska.
    """
    if station_code not in STATION_STATUS_MAP:
        return jsonify({'error': 'unknown_station'}), 404

    if not device_can_access_station(g.device, station_code):
        return jsonify({
            'error': 'station_mismatch',
            'device_station': g.device.station_code,
            'requested_station': station_code,
        }), 403

    status = STATION_STATUS_MAP[station_code]

    # Zamówienia (po internal_order_number), w których jakakolwiek pozycja
    # ma current_status pasujący do tego stanowiska. Następnie pobieramy
    # wszystkie pozycje z tych zamówień — także te z innych statusów
    # (sąsiednich stanowisk lub już ukończone), żeby mobile mogło pokazać
    # pełną grupę z badge'em.
    order_numbers_subq = db.session.query(
        ProductionItem.internal_order_number
    ).filter(
        ProductionItem.current_status == status
    ).distinct().subquery()

    items = ProductionItem.query.filter(
        ProductionItem.internal_order_number.in_(
            db.session.query(order_numbers_subq.c.internal_order_number)
        )
    ).order_by(
        func.coalesce(ProductionItem.priority_rank, 999999).asc(),
        ProductionItem.internal_order_number.asc(),
        ProductionItem.id.asc(),
    ).all()

    return jsonify({
        'station_code': station_code,
        'count': len(items),
        'orders': [serialize_order(it, station_code=station_code) for it in items],
    }), 200


@mobile_api_bp.route('/orders/<int:order_id>', methods=['GET'])
@require_device_token
def order_details(order_id):
    """GET /api/mobile/orders/<id> — szczegóły zlecenia."""
    item = ProductionItem.query.get(order_id)
    if not item:
        return jsonify({'error': 'order_not_found'}), 404

    return jsonify(serialize_order(item, station_code=g.device.station_code)), 200


@mobile_api_bp.route('/orders/<int:order_id>/complete', methods=['POST'])
@require_device_token
@with_idempotency
def order_complete(order_id):
    """
    POST /api/mobile/orders/<id>/complete

    Body JSON (opcjonalny): { station_code: str } — gdy pominięte, używane
    jest `device.station_code` (BC). Tablet w wykańczalni przekazuje
    `station_code='painting'` żeby ukończyć pozycję z lakierni.

    Pełna tranzycja statusu (z regułami specjalnymi, np. lakiernia
    dla olejowanych/lakierowanych, skip finishing dla surowych bez krawędzi)
    jest delegowana do `ProductionItem.complete_task()` — tej samej metody
    której używa web.

    Idempotency: przy nagłówku X-Operation-Id powtórne wywołanie zwraca
    zapisany response (nie wykonuje akcji drugi raz).
    """
    data = request.get_json(silent=True) or {}
    station_code, err = _resolve_station_code(data.get('station_code'))
    if err:
        return err

    item = ProductionItem.query.get(order_id)
    if not item:
        return jsonify({'error': 'order_not_found'}), 404

    try:
        mark_order_complete(item, station_code)
    except ValueError as e:
        return jsonify({'error': 'invalid_station', 'detail': str(e)}), 400
    except Exception as e:
        logger.error("Mobile API complete failed", extra={
            'order_id': order_id,
            'station_code': station_code,
            'error': str(e),
        })
        return jsonify({'error': 'complete_failed', 'detail': str(e)}), 500

    logger.info("Mobile API: order completed", extra={
        'order_id': order_id,
        'station_code': station_code,
        'device_id': g.device.device_id,
    })

    return jsonify(serialize_order(item, station_code=station_code)), 200


@mobile_api_bp.route('/orders/<int:order_id>/quantity', methods=['PATCH'])
@require_device_token
@with_idempotency
def order_quantity(order_id):
    """
    PATCH /api/mobile/orders/<id>/quantity

    Body JSON: { quantity_done: int } — liczba ukończonych sztuk na stanowisku.
    Waliduje 0 <= quantity_done <= item.quantity.

    Idempotency: przy nagłówku X-Operation-Id powtórne wywołanie zwraca
    zapisany response (nie wykonuje akcji drugi raz).
    """
    data = request.get_json(silent=True) or {}
    quantity_done = data.get('quantity_done')
    if not isinstance(quantity_done, int):
        return jsonify({'error': 'missing_or_invalid_quantity_done'}), 400

    station_code, err = _resolve_station_code(data.get('station_code'))
    if err:
        return err

    item = ProductionItem.query.get(order_id)
    if not item:
        return jsonify({'error': 'order_not_found'}), 404

    try:
        update_order_quantity(item, station_code, quantity_done)
    except ValueError as e:
        return jsonify({'error': 'invalid_quantity', 'detail': str(e)}), 400
    except Exception as e:
        logger.error("Mobile API quantity update failed", extra={
            'order_id': order_id,
            'error': str(e),
        })
        return jsonify({'error': 'update_failed', 'detail': str(e)}), 500

    return jsonify(serialize_order(item, station_code=station_code)), 200


# ============================================================================
# SUMMARY (metryki stanowiska)
# ============================================================================

@mobile_api_bp.route('/stations/<station_code>/summary', methods=['GET'])
@require_device_token
def station_summary(station_code):
    """
    GET /api/mobile/stations/<station_code>/summary

    Metryki stanowiska: queue (count, m³, priorytety) + completed_today (count, m³).
    """
    if station_code not in STATION_STATUS_MAP:
        return jsonify({'error': 'unknown_station'}), 404

    if not device_can_access_station(g.device, station_code):
        return jsonify({
            'error': 'station_mismatch',
            'device_station': g.device.station_code,
            'requested_station': station_code,
        }), 403

    try:
        return jsonify(compute_station_summary(station_code)), 200
    except Exception as e:
        logger.error("Mobile API summary failed", extra={
            'station_code': station_code,
            'error': str(e),
        })
        return jsonify({'error': 'summary_failed', 'detail': str(e)}), 500


# ============================================================================
# DELTA SYNC (zmiany od timestamp)
# ============================================================================

@mobile_api_bp.route('/stations/<station_code>/orders/since', methods=['GET'])
@require_device_token
def station_orders_since(station_code):
    """
    GET /api/mobile/stations/<station_code>/orders/since?ts=<ISO 8601>

    Delta sync. Zwraca:
    - all_ids: wszystkie zlecenia aktualnie w kolejce (klient wykrywa usunięte)
    - changed: pełne DTO dla zleceń z updated_at > ts
    """
    if station_code not in STATION_STATUS_MAP:
        return jsonify({'error': 'unknown_station'}), 404

    if not device_can_access_station(g.device, station_code):
        return jsonify({
            'error': 'station_mismatch',
            'device_station': g.device.station_code,
            'requested_station': station_code,
        }), 403

    ts_raw = request.args.get('ts', '').strip()
    if not ts_raw:
        return jsonify({
            'error': 'missing_ts',
            'detail': 'Wymagany parametr ?ts=<ISO 8601 timestamp>',
        }), 400

    try:
        since_ts = parse_since_ts(ts_raw)
    except ValueError as e:
        return jsonify({'error': 'invalid_ts', 'detail': str(e)}), 400

    try:
        return jsonify(get_station_queue_delta(station_code, since_ts)), 200
    except Exception as e:
        logger.error("Mobile API delta failed", extra={
            'station_code': station_code,
            'since_ts': ts_raw,
            'error': str(e),
        })
        return jsonify({'error': 'delta_failed', 'detail': str(e)}), 500


# ============================================================================
# APP VERSION / APK (publiczne — appka pyta przed rejestracją)
# ============================================================================

@mobile_api_bp.route('/app/version', methods=['GET'])
def app_version():
    """
    GET /api/mobile/app/version

    Metadane wersji appki. Bez auth (appka sprawdza przed rejestracją).
    """
    return jsonify(get_app_version_info()), 200


@mobile_api_bp.route('/app/apk', methods=['GET'])
def app_apk():
    """
    GET /api/mobile/app/apk

    Streaming pliku APK. Ścieżka do pliku w config: API_MOBILE.apk_file_path.
    Bez auth. Dopóki APK nie jest hostowany → 404 z komunikatem.
    """
    return stream_apk_response()
