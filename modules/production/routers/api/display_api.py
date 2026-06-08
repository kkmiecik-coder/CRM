"""Display-monitor endpoint.

Returns the production monitor payload as compact JSON.
Token-authenticated; not session-based.

Pollers (ESP8266 displays) hit this every ~60 s. Response is cached
in-process for 30 s so the DB is queried at most every 30 s regardless
of how many displays poll.
"""
import time

from flask import Blueprint, jsonify

from modules.logging import get_structured_logger
from modules.production.services.display_monitor_service import get_display_monitor_payload
from modules.production.utils.display_auth import require_display_token

logger = get_structured_logger('production.display_api')

display_bp = Blueprint('production_display', __name__)

_CACHE_TTL_SECONDS = 30
_cache = {'payload': None, 'expires_at': 0.0}


def _cached_payload():
    now = time.time()
    if _cache['payload'] is not None and now < _cache['expires_at']:
        return _cache['payload']
    payload = get_display_monitor_payload()
    _cache['payload'] = payload
    _cache['expires_at'] = now + _CACHE_TTL_SECONDS
    return payload


@display_bp.route('/api/display/monitor', methods=['GET'])
@require_display_token
def display_monitor():
    try:
        payload = _cached_payload()
        return jsonify(payload)
    except Exception as e:
        logger.exception('display_monitor failed', extra={'error': str(e)})
        return jsonify({'error': 'internal', 'reason': str(e)}), 500
