"""Bearer-token auth for the display monitor endpoint.

Token is stored in prod_config row with key='DISPLAY_MONITOR_TOKEN'.
Mirrors the pattern used by print_agent_api but with a generic name
since this is not coupled to printing.
"""
import hmac
from functools import wraps

from flask import jsonify, request
from sqlalchemy.exc import NoSuchColumnError, OperationalError, ResourceClosedError

from extensions import db
from modules.logging import get_structured_logger
from modules.production.models import ProductionConfig

logger = get_structured_logger('production.display_auth')

_TRANSIENT_DB_ERRORS = (NoSuchColumnError, OperationalError, ResourceClosedError)


def _query_display_token():
    row = ProductionConfig.query.filter_by(config_key='DISPLAY_MONITOR_TOKEN').first()
    return (row.config_value or '').strip() if row else ''


def _get_display_token():
    """Read DISPLAY_MONITOR_TOKEN with one retry on transient DB errors."""
    try:
        return _query_display_token()
    except _TRANSIENT_DB_ERRORS as e:
        logger.warning('Display token read failed, retrying', extra={'error_type': type(e).__name__})
        try:
            db.session.rollback()
        except Exception:
            pass
        try:
            db.session.invalidate()
        except Exception:
            pass
        try:
            return _query_display_token()
        except Exception as e2:
            logger.error('Display token retry failed',
                         extra={'error_type': type(e2).__name__, 'error': str(e2)})
            return ''


def require_display_token(view):
    """Require Authorization: Bearer <DISPLAY_MONITOR_TOKEN>. Returns 401 JSON otherwise."""
    @wraps(view)
    def wrapper(*args, **kwargs):
        header = request.headers.get('Authorization', '')
        prefix = 'Bearer '
        if not header.startswith(prefix):
            return jsonify({'error': 'unauthorized', 'reason': 'missing bearer'}), 401
        token = header[len(prefix):].strip()
        expected = _get_display_token()
        if not expected or not token:
            return jsonify({'error': 'unauthorized', 'reason': 'invalid token'}), 401
        if not hmac.compare_digest(token, expected):
            return jsonify({'error': 'unauthorized', 'reason': 'invalid token'}), 401
        return view(*args, **kwargs)
    return wrapper
