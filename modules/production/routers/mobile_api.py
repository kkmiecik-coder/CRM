"""
Mobile API router — endpointy REST dla natywnej aplikacji Android.

Blueprint zarejestrowany w app.py pod prefixem `/api/mobile`.
Logika biznesowa w `services/mobile_api_service.py` — router jest cienki.
"""

from datetime import datetime, time, timedelta

from flask import Blueprint, g, jsonify, request
from sqlalchemy import func, or_
from sqlalchemy.orm import joinedload

from extensions import db
from modules.logging import get_structured_logger
from modules.production.models import ProductionConfig, ProductionDevice, ProductionItem, ProductionOrder
from modules.production.utils.cache import (
    cached_json,
    if_none_match,
    make_weak_etag,
    not_modified,
)
from modules.production.services import label_print_service, worker_service
from modules.production.services.label_print_service import StationNotAllowed
from modules.production.services.worker_service import WorkerError
from modules.production.services.mobile_api_service import (
    STATION_STATUS_MAP,
    STATUS_TO_STATION,
    compute_station_summary,
    device_can_access_station,
    get_app_version_info,
    get_station_queue_delta,
    mark_order_complete,
    parse_since_ts,
    register_device,
    require_device_token,
    search_orders_global,
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

# Kody, po których wpis MUSI zostać w kolejce offline zamiast zostać zapamiętany
# przez @with_idempotency. Wszystkie trzy wychodzą z walidacji profilu
# (_resolve_workers) i wszystkie są odwracalne bez udziału tabletu:
#   400 worker_ids_required — admin wyłącza kill-switch,
#   404 worker_not_found    — katalog się odświeża,
#   409 worker_inactive     — admin przywraca pracownika.
# Bez tego dekorator zapisuje odpowiedź pod X-Operation-Id i przy ponowieniu
# ODTWARZA ją bez wywołania handlera — wykonana robota przepada bezpowrotnie,
# mimo że przyczyna błędu już nie istnieje. Trakownia używa tego mechanizmu
# z dokładnie tego powodu (sawmill/routers/mobile_api.py:185).
BLEDY_DO_PONOWIENIA = {400, 404, 409}


def _resolve_workers():
    """
    Czyta nagłówek X-Worker-Ids, waliduje i odświeża sesje.

    Zwraca (worker_ids, session_ids, error_response). Gdy error_response != None,
    wywołujący ma go zwrócić natychmiast. Pusta lista worker_ids znaczy
    "bramka wyłączona i tablet nie przysłał nagłówka" — akcja przechodzi
    bez atrybucji.

    Sesje odświeżamy po samym device_id, nie po station_code: tablet
    wykańczalni zamyka też pozycje z lakierni (station_code='painting'),
    a sesja jest założona na stanowisku z JWT.
    """
    try:
        worker_ids = worker_service.resolve_worker_ids(
            request.headers.get('X-Worker-Ids'))
    except WorkerError as e:
        return None, None, _worker_error_response(e)

    # Audyt zmian statusu (product_events.current_actor) czyta to z g —
    # dzięki temu prod_product_events.worker_id wypełnia się bez przekazywania
    # listy przez cały łańcuch wywołań aż do listenera SQLAlchemy.
    g.worker_ids = worker_ids

    session_ids = worker_service.touch_sessions(
        worker_ids, device_id=g.device.device_id) if worker_ids else {}
    return worker_ids, session_ids, None


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


@mobile_api_bp.route('/orders/search', methods=['GET'])
@require_device_token
def orders_search():
    """
    GET /api/mobile/orders/search?q=<query>&limit=<n>

    Globalne wyszukiwanie zamówień po wszystkich stanowiskach (bez
    ograniczeń per device.station_code — operator może znaleźć "cudze"
    zamówienie). Match tekstowy (internal_order_number, baselinker_order_id,
    client_order_number, client_name) LUB wymiarowy (1-3 liczby cm, multiset
    z tolerancją ±5 mm). Zwraca wszystkie pozycje pasujących zamówień,
    każda z dodatkowym polem `current_station` (mapowanie current_status →
    kod stanowiska, lub null gdy pozycja poza produkcją).
    """
    q_raw = request.args.get('q', '')
    q = q_raw.strip()
    if len(q) < 3:
        return jsonify({'error': 'Query too short'}), 400

    limit_raw = request.args.get('limit', '50').strip()
    try:
        limit = int(limit_raw)
    except (TypeError, ValueError):
        limit = 50
    if limit < 1:
        limit = 1
    elif limit > 100:
        limit = 100

    try:
        items, has_more, _total = search_orders_global(q, limit=limit)
    except Exception as e:
        logger.error("Mobile API global search failed", extra={
            'q': q, 'limit': limit, 'error': str(e),
        })
        return jsonify({'error': 'search_failed', 'detail': str(e)}), 500

    serialized = []
    for it in items:
        dto = serialize_order(it)
        dto['current_station'] = STATUS_TO_STATION.get(it.current_status)
        serialized.append(dto)

    return jsonify({
        'query': q,
        'count': len(serialized),
        'has_more': has_more,
        'orders': serialized,
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
@with_idempotency(retryable_statuses=BLEDY_DO_PONOWIENIA)
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

    worker_ids, session_ids, err = _resolve_workers()
    if err:
        return err

    item = ProductionItem.query.get(order_id)
    if not item:
        return jsonify({'error': 'order_not_found'}), 404

    try:
        mark_order_complete(item, station_code, device_id=g.device.device_id,
                            worker_ids=worker_ids, session_ids=session_ids)
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
@with_idempotency(retryable_statuses=BLEDY_DO_PONOWIENIA)
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

    worker_ids, session_ids, err = _resolve_workers()
    if err:
        return err

    item = ProductionItem.query.get(order_id)
    if not item:
        return jsonify({'error': 'order_not_found'}), 404

    try:
        update_order_quantity(item, station_code, quantity_done,
                              device_id=g.device.device_id,
                              worker_ids=worker_ids, session_ids=session_ids)
    except ValueError as e:
        return jsonify({'error': 'invalid_quantity', 'detail': str(e)}), 400
    except Exception as e:
        logger.error("Mobile API quantity update failed", extra={
            'order_id': order_id,
            'error': str(e),
        })
        return jsonify({'error': 'update_failed', 'detail': str(e)}), 500

    return jsonify(serialize_order(item, station_code=station_code)), 200


@mobile_api_bp.route('/orders/<int:order_id>/reject', methods=['POST'])
@require_device_token
@with_idempotency(retryable_statuses=BLEDY_DO_PONOWIENIA)
def order_reject(order_id):
    """
    POST /api/mobile/orders/<id>/reject

    Body JSON: {
        quantity: int,
        reason_category: 'wymiary' | 'jakosc_sklejenia' | 'jakosc_produktu' | 'inne',
        station_code: 'formatting' (opcjonalne, domyślnie z g.device.station_code)
    }

    Response: { original: serialized, rework: serialized, rework_log_id: int }
    """
    from modules.production.services.rework_service import (
        reject_product_quantity,
        RejectError,
    )

    data = request.get_json(silent=True) or {}

    station_code, err = _resolve_station_code(data.get('station_code'))
    if err is not None:
        return err

    quantity = data.get('quantity')
    reason_category = (data.get('reason_category') or '').strip()

    worker_ids, _sesje, err = _resolve_workers()
    if err:
        return err

    try:
        original, rework, log_entry = reject_product_quantity(
            product_id=order_id,
            quantity=int(quantity) if quantity is not None else None,
            reason_category=reason_category,
            rejected_at_station=station_code,
            user_id=None,  # mobile API używa device, nie user
            device_id=g.device.device_id,
            worker_ids=worker_ids,
        )
    except RejectError as e:
        logger.warning(
            "Mobile API reject odrzucony",
            extra={
                'product_id': order_id,
                'code': e.code,
                'device_id': g.device.device_id,
            },
        )
        return jsonify({'error': e.code, 'detail': e.message}), e.status
    except Exception as e:
        logger.error(
            "Mobile API reject błąd",
            extra={'product_id': order_id, 'device_id': g.device.device_id},
            exc_info=True,
        )
        db.session.rollback()
        return jsonify({'error': 'reject_failed', 'detail': str(e)}), 500

    logger.info(
        "Mobile API: reject wykonany",
        extra={
            'product_id': original.id,
            'rework_id': rework.id,
            'quantity': log_entry.quantity,
            'reason': log_entry.reason_category,
            'device_id': g.device.device_id,
        },
    )

    return jsonify({
        'original': serialize_order(original, station_code=station_code),
        'rework': serialize_order(rework, station_code=station_code),
        'rework_log_id': log_entry.id,
    }), 200


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
    # Payload zawiera refresh_interval_seconds z prod_config — bez tego segmentu
    # zmiany konfigu nie unieważniają ETag i tablet (OkHttp) serwuje stale 304.
    config_max_updated = db.session.query(
        func.max(ProductionConfig.updated_at)
    ).scalar()
    config_etag_ts = int(config_max_updated.timestamp()) if config_max_updated else 0
    etag = make_weak_etag(
        'summary', station_code, today_start.date().isoformat(),
        etag_ts, total_count or 0, config_etag_ts,
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


# ============================================================================
# DEVICES — heartbeat / telemetria
# ============================================================================

@mobile_api_bp.route('/devices/heartbeat', methods=['POST'])
@require_device_token
def device_heartbeat():
    """
    Tablet wysyła co 15 min telemetrię (bateria/temp/wersja APK/IP).
    Brak idempotency — każdy heartbeat nadpisuje pola na ProductionDevice.
    """
    from modules.production.services.mobile_api_service import (
        validate_heartbeat_payload,
        get_local_now,
    )

    payload = request.get_json(silent=True) or {}
    err = validate_heartbeat_payload(payload)
    if err:
        return jsonify({'error': 'validation', 'detail': err}), 422

    device = g.device
    device.last_heartbeat_at = get_local_now()
    device.last_battery_pct = payload.get('battery_pct')
    device.last_battery_charging = payload.get('battery_charging')
    device.last_temperature_c = payload.get('temperature_c')
    device.last_app_version_code = payload['app_version_code']
    device.app_version = payload['app_version_name']
    ip_addr = payload.get('ip_address')
    if ip_addr:
        device.last_ip = ip_addr

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.error("Mobile API: heartbeat commit failed", extra={
            'device_id': device.device_id,
            'station_code': device.station_code,
            'error': str(e),
        })
        return jsonify({'error': 'internal'}), 500

    logger.info("Mobile API: heartbeat OK", extra={
        'event': 'device_heartbeat',
        'device_id': device.device_id,
        'station_code': device.station_code,
        'battery_pct': payload.get('battery_pct'),
        'battery_charging': payload.get('battery_charging'),
        'temperature_c': payload.get('temperature_c'),
        'app_version_code': payload['app_version_code'],
        'app_version_name': payload['app_version_name'],
    })

    return '', 204


# ============================================================================
# PROFILE PRACOWNIKÓW
# docs/worker-profiles-backend.md §6
# ============================================================================

def _worker_error_response(e):
    """WorkerError → (JSON, status) w konwencji mobile API ({error, detail})."""
    payload, status = e.as_response()
    return jsonify(payload), status


@mobile_api_bp.route('/workers', methods=['GET'])
@require_device_token
def workers_catalog():
    """
    GET /api/mobile/workers

    Katalog aktywnych pracowników do ekranu wyboru profilu, razem z PEŁNĄ
    konfiguracją (selection_required, idle_timeout_minutes, night_cutoff,
    quick_pick_count) — apka nie hardkoduje żadnej z tych wartości i nie
    pobiera ich osobnym requestem.

    recent_on_station liczone dla stanowiska z JWT urządzenia — zasila sekcję
    "szybki wybór".

    ETag: catalog_version = MAX(updated_at) z katalogu. Apka wysyła
    If-None-Match przy starcie i przy pustej zmianie dostaje 304.
    """
    station_code = g.device.station_code

    # catalog_version to MAX(prod_workers.updated_at), a payload niesie też
    # selection_required / idle_timeout_minutes / night_cutoff / quick_pick_count
    # z prod_config. Bez segmentu konfiguracji zmiana samego przełącznika nie
    # unieważnia ETag i tablet (OkHttp) dostaje 304 ze starym ustawieniem —
    # ten sam błąd naprawiono wcześniej w /stations/<code>/summary.
    config_max_updated = db.session.query(func.max(ProductionConfig.updated_at)).scalar()
    config_etag_ts = int(config_max_updated.timestamp()) if config_max_updated else 0

    etag = make_weak_etag('workers', station_code,
                          worker_service.get_catalog_version(), config_etag_ts)
    if if_none_match(etag):
        return not_modified(etag)

    katalog = worker_service.build_mobile_catalog(station_code=station_code)
    return cached_json(katalog, etag)


@mobile_api_bp.route('/sessions/start', methods=['POST'])
@require_device_token
@with_idempotency(retryable_statuses=BLEDY_DO_PONOWIENIA)
def session_start():
    """
    POST /api/mobile/sessions/start

    Body JSON: {
        worker_ids: [int],        wymagane
        station_code: str,        opcjonalne — domyślnie stanowisko z JWT
        session_group: str,       UUID wygenerowany w apce (klucz encji w Room)
        started_at: ISO8601       opcjonalne — sesja mogła zacząć się offline
    }

    UWAGA na strefę: started_at bez offsetu jest czytany jako UTC (parse_since_ts,
    ta sama konwencja co delta sync). Apka musi wysyłać ISO z offsetem albo z 'Z',
    inaczej sesja zapisze się przesunięta o różnicę stref.

    Poprzednie sesje TEGO urządzenia są domykane z end_reason='replaced' —
    zmiana obsady to koniec poprzedniej sesji, nie jej modyfikacja.

    Idempotency: powtórka z tym samym X-Operation-Id zwraca zapisaną odpowiedź,
    nie zakłada drugiego kompletu sesji.
    """
    data = request.get_json(silent=True) or {}

    worker_ids = data.get('worker_ids')
    if not isinstance(worker_ids, list) or not worker_ids:
        return jsonify({'error': 'invalid_worker_ids',
                        'detail': 'worker_ids musi być niepustą listą'}), 422
    try:
        worker_ids = [int(w) for w in worker_ids]
    except (TypeError, ValueError):
        return jsonify({'error': 'invalid_worker_ids',
                        'detail': 'worker_ids musi zawierać liczby'}), 422

    station_code, err = _resolve_station_code(data.get('station_code'))
    if err:
        return err

    started_at = None
    if data.get('started_at'):
        try:
            started_at = parse_since_ts(data['started_at'])
        except ValueError as e:
            return jsonify({'error': 'invalid_started_at', 'detail': str(e)}), 422

    try:
        sesje = worker_service.start_session(
            worker_ids, station_code,
            device_id=g.device.device_id,
            session_group=data.get('session_group'),
            started_at=started_at,
            source='mobile',
            commit=False,          # commit robi @with_idempotency
        )
    except WorkerError as e:
        return _worker_error_response(e)

    pierwsza = sesje[0]
    wygasa = pierwsza.started_at + timedelta(
        minutes=worker_service.get_idle_timeout_minutes())

    return jsonify({
        'session_group': pierwsza.session_group,
        'sessions': [
            {'id': s.id, 'worker_id': s.worker_id, 'started_at': s.started_at.isoformat()}
            for s in sesje
        ],
        'expires_at': wygasa.isoformat(),
    }), 201


@mobile_api_bp.route('/sessions/end', methods=['POST'])
@require_device_token
@with_idempotency
def session_end():
    """
    POST /api/mobile/sessions/end

    Body JSON: { session_group: str, ended_at: ISO8601, reason: str }

    Dozwolone reason od klienta: manual, idle_timeout, night_cutoff. Apka
    egzekwuje timeouty lokalnie, żeby UX był natychmiastowy, i raportuje powód —
    serwer go przyjmuje zamiast nadpisywać własnym. 'replaced' i 'admin'
    ustawia wyłącznie backend, więc przysłane z tabletu dają 422.
    """
    data = request.get_json(silent=True) or {}

    session_group = (data.get('session_group') or '').strip()
    if not session_group:
        return jsonify({'error': 'missing_session_group'}), 422

    ended_at = None
    if data.get('ended_at'):
        try:
            ended_at = parse_since_ts(data['ended_at'])
        except ValueError as e:
            return jsonify({'error': 'invalid_ended_at', 'detail': str(e)}), 422

    try:
        worker_service.end_session(
            session_group,
            ended_at=ended_at,
            reason=(data.get('reason') or 'manual'),
            device_id=g.device.device_id,
            commit=False,          # commit robi @with_idempotency
        )
    except WorkerError as e:
        return _worker_error_response(e)

    return '', 204


@mobile_api_bp.route('/sessions/active', methods=['GET'])
@require_device_token
def sessions_active():
    """
    GET /api/mobile/sessions/active

    Otwarte sesje TEGO urządzenia. Apka woła to po restarcie albo crashu, żeby
    nie zmuszać brygady do ponownego wybierania profili.
    """
    sesje = worker_service.get_active_sessions(device_id=g.device.device_id)

    return jsonify({
        'station_code': g.device.station_code,
        'session_group': sesje[0].session_group if sesje else None,
        'idle_timeout_minutes': worker_service.get_idle_timeout_minutes(),
        'sessions': [
            {
                'id': s.id,
                'worker_id': s.worker_id,
                'worker_name': s.worker.full_name if s.worker else None,
                'initials': s.worker.initials if s.worker else None,
                'color_hex': s.worker.tile_color if s.worker else None,
                'station_code': s.station_code,
                'started_at': s.started_at.isoformat() if s.started_at else None,
                'last_activity_at': (s.last_activity_at.isoformat()
                                     if s.last_activity_at else None),
            }
            for s in sesje
        ],
    }), 200
