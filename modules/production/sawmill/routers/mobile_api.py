# -*- coding: utf-8 -*-
"""
API mobilne trakowni — /api/mobile/sawmill/*

Reużywa autoryzację i idempotencję modułu produkcji. NIE używa
STATION_STATUS_MAP ani device_can_access_station — trakownia nie ma statusów
produktów, więc mapowanie stanowisko→status jest tu bez sensu.

Handlery NIE commitują — robi to dekorator idempotencji.
"""

from functools import wraps

from flask import g, jsonify, request
from sqlalchemy.orm import joinedload

from extensions import db
from modules.logging import get_structured_logger
from modules.production.sawmill import sawmill_mobile_bp
from modules.production.sawmill.models import (
    OPEN_STATUSES, SawmillLog, SawmillOrder,
)
from modules.production.sawmill.services.orders import (
    SawmillStateError, add_log, complete_order, delete_log, order_totals,
    update_log,
)
from modules.production.sawmill.services.serializers import (
    serialize_log_for_device, serialize_order_for_device,
)
from modules.production.sawmill.services.settings import (
    get_sawmill_settings, mobile_config_payload,
)
from modules.production.sawmill.services.validation import (
    SawmillValidationError, parse_measured_at, validate_measurements,
)
from modules.production.services.mobile_api_service import (
    require_device_token, with_idempotency,
)
from modules.production.utils.cache import (
    cached_json, if_none_match, make_weak_etag, not_modified,
)

logger = get_structured_logger('production.sawmill.mobile_api')

STATION_CODE = 'sawmill'


def require_sawmill_device(f):
    """
    Urządzenie musi być zarejestrowane jako trak. Bez aliasów stanowisk —
    w odróżnieniu od device_can_access_station() z modułu głównego (który
    zna np. grupę finishing/painting), tu station_code musi się zgadzać
    dokładnie, bo trakownia nie dzieli kolejki z żadnym innym stanowiskiem.
    """
    @wraps(f)
    def wrapper(*args, **kwargs):
        # g.device ustawia require_device_token, który przy braku/złym tokenie
        # zwraca 401 i tu w ogóle nie wchodzi. Wcześniejsza gałąź obronna na
        # `g.device is None` i tak wywalała się linijkę niżej na
        # `getattr(g.device, ...)` (AttributeError zamiast 403), czyli udawała
        # zabezpieczenie, którym nie była.
        device = g.device
        if device.station_code != STATION_CODE:
            return jsonify({
                'error': 'station_mismatch',
                'device_station': device.station_code,
                'required_station': STATION_CODE,
            }), 403
        return f(*args, **kwargs)
    return wrapper


def _validation_response(exc):
    return jsonify({
        'error': 'validation_error',
        'field': exc.field,
        'detail': exc.detail,
    }), 422


def _order_payload(order):
    count, volume = order_totals(order.id)
    return serialize_order_for_device(order, count, volume)


def _load_order(order_id):
    return (
        db.session.query(SawmillOrder)
        .options(joinedload(SawmillOrder.delivery), joinedload(SawmillOrder.species))
        .get(order_id)
    )


# ── Odczyt ──────────────────────────────────────────────────────────────────

@sawmill_mobile_bp.route('/orders', methods=['GET'])
@require_device_token
@require_sawmill_device
def sawmill_orders():
    """
    Lista zleceń otwartych. Z ETagiem — tablet odpytuje często.

    Brak kolumn cache'ujących sumę pomiarów na zleceniu (żaden trigger nie
    aktualizuje prod_sawmill_orders.updated_at przy dodaniu/edycji kłody,
    dopóki nie zmieni się status zlecenia), więc ETag jest liczony osobno
    dla każdego zlecenia jako MAX(order.updated_at, MAX(COALESCE(log.updated_at,
    log.created_at))) po jego pomiarach — nie samo order.updated_at.

    COALESCE jest konieczny: w MySQL GREATEST/MAX z NULL-em w argumentach
    daje NULL, a logs.updated_at pozostaje puste dla nieedytowanych kłód
    (onupdate odpala się tylko przy realnym UPDATE-cie wiersza). Bez tego
    ETag zmieniałby się wyłącznie przez COUNT i sam PATCH pomiaru (bez
    zmiany liczby kłód) nie unieważniłby cache'u.
    """
    orders = (
        db.session.query(SawmillOrder)
        .options(joinedload(SawmillOrder.delivery), joinedload(SawmillOrder.species))
        .filter(SawmillOrder.status.in_(OPEN_STATUSES))
        .order_by(SawmillOrder.order_number)
        .all()
    )

    total = 0
    stamps = []
    for order in orders:
        count, _ = order_totals(order.id)
        total += count

        newest_log_stamp = (
            db.session.query(db.func.max(
                db.func.coalesce(SawmillLog.updated_at, SawmillLog.created_at)))
            .filter(SawmillLog.order_id == order.id)
            .scalar()
        )
        # Zlecenie bez żadnego pomiaru → newest_log_stamp is None, filter(None, ...)
        # niżej go odsieje; order.updated_at też bywa None (onupdate nie odpalił
        # się jeszcze ani razu) — wtedy dla tego zlecenia nie ma żadnego znacznika
        # czasu i to jest OK, liczy się globalnie razem z total/len(orders).
        candidates = [ts for ts in (order.updated_at, newest_log_stamp) if ts is not None]
        stamps.append(max(candidates) if candidates else None)

    known_stamps = [s for s in stamps if s is not None]
    newest_overall = max(known_stamps) if known_stamps else 0
    etag = make_weak_etag('sawmill-orders', newest_overall, total, len(orders))
    if if_none_match(etag):
        return not_modified(etag)

    return cached_json({'orders': [_order_payload(o) for o in orders]}, etag)


@sawmill_mobile_bp.route('/orders/<int:order_id>', methods=['GET'])
@require_device_token
@require_sawmill_device
def sawmill_order_details(order_id):
    order = _load_order(order_id)
    if order is None:
        return jsonify({'error': 'order_not_found'}), 404

    logs = (
        db.session.query(SawmillLog)
        .filter(SawmillLog.order_id == order_id)
        .filter(SawmillLog.is_deleted.is_(False))
        .order_by(SawmillLog.sequence_no)
        .all()
    )
    return jsonify({
        'order': _order_payload(order),
        'logs': [serialize_log_for_device(l) for l in logs],
    })


@sawmill_mobile_bp.route('/config', methods=['GET'])
@require_device_token
@require_sawmill_device
def sawmill_config():
    """Limity walidacji, żeby appka odrzucała bzdury lokalnie, bez sieci."""
    return jsonify(mobile_config_payload())


# ── Zapis ───────────────────────────────────────────────────────────────────

@sawmill_mobile_bp.route('/orders/<int:order_id>/logs', methods=['POST'])
@require_device_token
@require_sawmill_device
@with_idempotency(retryable_statuses={409}, require_operation_id=True)
def sawmill_add_log(order_id):
    order = _load_order(order_id)
    if order is None:
        return jsonify({'error': 'order_not_found'}), 404

    payload = request.get_json(silent=True) or {}
    settings = get_sawmill_settings()
    try:
        measurements = validate_measurements(payload, settings)
        measured_at = parse_measured_at(payload.get('measured_at'))
    except SawmillValidationError as exc:
        return _validation_response(exc)

    try:
        log = add_log(order, measurements, measured_at, device_id=g.device.device_id)
    except SawmillStateError as exc:
        return jsonify({'error': 'order_not_open', 'detail': exc.detail}), 409

    db.session.flush()
    return jsonify({
        'log': serialize_log_for_device(log),
        'order': _order_payload(order),
    }), 201


@sawmill_mobile_bp.route('/logs/<int:log_id>', methods=['PATCH'])
@require_device_token
@require_sawmill_device
@with_idempotency(retryable_statuses={409}, require_operation_id=True)
def sawmill_update_log(log_id):
    log = db.session.query(SawmillLog).get(log_id)
    if log is None or log.is_deleted:
        return jsonify({'error': 'log_not_found'}), 404

    order = _load_order(log.order_id)
    payload = request.get_json(silent=True) or {}
    try:
        measurements = validate_measurements(payload, get_sawmill_settings())
    except SawmillValidationError as exc:
        return _validation_response(exc)

    try:
        update_log(log, measurements, device_id=g.device.device_id)
    except SawmillStateError as exc:
        return jsonify({'error': 'order_not_open', 'detail': exc.detail}), 409

    db.session.flush()
    return jsonify({
        'log': serialize_log_for_device(log),
        'order': _order_payload(order),
    }), 200


@sawmill_mobile_bp.route('/logs/<int:log_id>', methods=['DELETE'])
@require_device_token
@require_sawmill_device
@with_idempotency(retryable_statuses={409}, require_operation_id=True)
def sawmill_delete_log(log_id):
    log = db.session.query(SawmillLog).get(log_id)
    if log is None or log.is_deleted:
        return jsonify({'error': 'log_not_found'}), 404

    order = _load_order(log.order_id)
    try:
        delete_log(log, device_id=g.device.device_id)
    except SawmillStateError as exc:
        return jsonify({'error': 'order_not_open', 'detail': exc.detail}), 409

    db.session.flush()
    return jsonify({'order': _order_payload(order)}), 200


@sawmill_mobile_bp.route('/orders/<int:order_id>/complete', methods=['POST'])
@require_device_token
@require_sawmill_device
@with_idempotency(retryable_statuses={409}, require_operation_id=True)
def sawmill_complete_order(order_id):
    order = _load_order(order_id)
    if order is None:
        return jsonify({'error': 'order_not_found'}), 404

    try:
        complete_order(order, device_id=g.device.device_id)
    except SawmillStateError as exc:
        return jsonify({'error': 'order_not_open', 'detail': exc.detail}), 409

    db.session.flush()
    return jsonify({'order': _order_payload(order)}), 200
