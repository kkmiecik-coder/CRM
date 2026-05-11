"""
Mobile API router — endpointy REST dla natywnej aplikacji Android.

Blueprint zarejestrowany w app.py pod prefixem `/api/mobile`.
Logika biznesowa w `services/mobile_api_service.py` — router jest cienki.
"""

from datetime import datetime, time

from flask import Blueprint, g, jsonify, request
from sqlalchemy import func, or_
from sqlalchemy.orm import joinedload

from extensions import db
from modules.logging import get_structured_logger
from modules.production.models import ProductionDevice, ProductionItem, ProductionOrder
from modules.production.utils.cache import (
    cached_json,
    if_none_match,
    make_weak_etag,
    not_modified,
)
from modules.production.services import label_print_service
from modules.production.services.label_print_service import StationNotAllowed
from modules.production.services.station_heartbeat import record_heartbeat
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

    record_heartbeat(station_code)

    status = STATION_STATUS_MAP[station_code]

    # Zamówienia (po internal_order_number), w których jakakolwiek pozycja
    # ma current_status pasujący do tego stanowiska. Następnie pobieramy
    # wszystkie pozycje z tych zamówień — także te z innych statusów
    # (sąsiednich stanowisk lub już ukończone), żeby mobile mogło pokazać
    # pełną grupę z badge'em.
    order_numbers_subq = db.session.query(
        ProductionOrder.internal_order_number
    ).join(ProductionItem, ProductionItem.order_id == ProductionOrder.id).filter(
        ProductionItem.current_status == status
    ).distinct().subquery()

    items_filter = ProductionOrder.internal_order_number.in_(
        db.session.query(order_numbers_subq.c.internal_order_number)
    )

    max_updated, total_count = db.session.query(
        func.max(ProductionItem.updated_at),
        func.count(ProductionItem.id),
    ).join(ProductionOrder, ProductionItem.order_id == ProductionOrder.id).filter(items_filter).first()
    etag_ts = int(max_updated.timestamp()) if max_updated else 0
    etag = make_weak_etag('orders', station_code, etag_ts, total_count or 0)
    if if_none_match(etag):
        return not_modified(etag)

    items = ProductionItem.query.options(
        joinedload(ProductionItem.order),
        joinedload(ProductionItem.configuration),
    ).join(
        ProductionOrder, ProductionItem.order_id == ProductionOrder.id
    ).filter(items_filter).order_by(
        func.coalesce(ProductionItem.priority_rank, 999999).asc(),
        ProductionOrder.internal_order_number.asc(),
        ProductionItem.id.asc(),
    ).all()

    return cached_json({
        'station_code': station_code,
        'count': len(items),
        'orders': [serialize_order(it, station_code=station_code) for it in items],
    }, etag)


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
        update_order_quantity(item, station_code, quantity_done, device_id=g.device.device_id)
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

    # ETag: MAX(updated_at) + COUNT po pozycjach z kolejki LUB ukończonych
    # dziś na tym stanowisku (completed_today resetuje się o północy, dlatego
    # data lokalna trafia do klucza).
    status = STATION_STATUS_MAP[station_code]
    today_start = datetime.combine(datetime.now().date(), time.min)
    completed_attr = getattr(ProductionItem, f'{station_code}_completed_at', None)
    cache_filter = (ProductionItem.current_status == status)
    if completed_attr is not None:
        cache_filter = or_(cache_filter, completed_attr >= today_start)

    max_updated, total_count = db.session.query(
        func.max(ProductionItem.updated_at),
        func.count(ProductionItem.id),
    ).filter(cache_filter).first()
    etag_ts = int(max_updated.timestamp()) if max_updated else 0
    etag = make_weak_etag(
        'summary', station_code, today_start.date().isoformat(),
        etag_ts, total_count or 0,
    )
    if if_none_match(etag):
        return not_modified(etag)

    try:
        return cached_json(compute_station_summary(station_code), etag)
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

    record_heartbeat(station_code)

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

    Metadane najnowszego aktywnego release'u APK. Publiczne (klient woła
    przed rejestracją do sanity-check'u). Gdy w bazie nie ma żadnego release'u,
    zwraca {"version_code": 0} — klient interpretuje "brak update'ów".
    """
    return jsonify(get_app_version_info()), 200


@mobile_api_bp.route('/app/apk', methods=['GET'])
@require_device_token
def app_apk():
    """
    GET /api/mobile/app/apk?version=<int>

    Streaming pliku APK dla zadanego version_code. Wymaga JWT (tablet musi
    być zarejestrowany). 400 gdy brak/zły parametr `version`, 404 gdy release
    nie istnieje lub jest nieaktywny.
    """
    version_raw = request.args.get('version', '').strip()
    if not version_raw:
        return jsonify({
            'error': 'missing_version',
            'detail': 'Wymagany parametr ?version=<int> (version_code z APK).',
        }), 400
    try:
        version_code = int(version_raw)
    except ValueError:
        return jsonify({
            'error': 'invalid_version',
            'detail': f'version_code musi być liczbą, otrzymano: {version_raw!r}',
        }), 400

    return stream_apk_response(version_code)


# ============================================================================
# DRUKOWANIE ETYKIET (MOBILE)
# ============================================================================


@mobile_api_bp.route('/products/<short_product_id>/print-label', methods=['POST'])
@require_device_token
def mobile_print_label_single(short_product_id):
    station_code = (g.device.station_code or '').strip()
    try:
        result = label_print_service.print_labels_batch(
            [short_product_id],
            station_code,
            {'type': 'device', 'id': g.device.device_id},
        )
    except StationNotAllowed as e:
        return jsonify({'success': False, 'message': str(e)}), 403

    if result['connection_error']:
        return jsonify({'success': False, 'message': result['message']}), 502
    return jsonify({'success': result['success'], 'message': result['message']}), 200


@mobile_api_bp.route('/orders/<int:baselinker_order_id>/print-labels', methods=['POST'])
@require_device_token
def mobile_print_labels_for_order(baselinker_order_id):
    station_code = (g.device.station_code or '').strip()
    items = (ProductionItem.query
             .join(ProductionOrder)
             .filter(ProductionOrder.baselinker_order_id == baselinker_order_id)
             .order_by(ProductionItem.product_sequence_in_order)
             .all())
    if not items:
        return jsonify({'success': False, 'message': 'Brak produktów w zamówieniu.'}), 404

    short_ids = [i.short_product_id for i in items]
    try:
        result = label_print_service.print_labels_batch(
            short_ids,
            station_code,
            {'type': 'device', 'id': g.device.device_id},
        )
    except StationNotAllowed as e:
        return jsonify({'success': False, 'message': str(e)}), 403

    if result['connection_error']:
        return jsonify({
            'success': False,
            'success_count': 0,
            'failed_count': len(short_ids),
            'message': result['message'],
        }), 502
    return jsonify({
        'success': result['success'],
        'success_count': result['success_count'],
        'failed_count': result['failed_count'],
        'message': result['message'],
    }), 200
