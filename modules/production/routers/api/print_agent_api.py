"""
Endpointy dla print-agenta (skrypt na hubie biura).
Autoryzacja: nagłówek `Authorization: Bearer <LABEL_PRINTER_AGENT_TOKEN>`.
NIE wymaga sesji webowej.

Wzorzec: agent budzi się na sygnał push (Centrifugo, kanał `print:agent`),
woła GET /api/print-agent/jobs?limit=10, drukuje lokalnie ZPL z pola
zpl_payload, potem POST /api/print-agent/ack z listą wyników. Polling został
jako siatka bezpieczeństwa — 60 s gdy kanał push żyje, 10 s gdy padł.
Token do połączenia z brokerem agent bierze z GET /realtime-token.

TTL: pending starsze niż 1h są oznaczane jako 'expired' i nigdy nie drukowane
(operator powinien kliknąć ponownie). Sprzątanie jest throttlowane — patrz
_expire_stale_pending().
"""
import time
from datetime import datetime, timedelta
from functools import wraps

from flask import Blueprint, jsonify, request
from sqlalchemy.exc import NoSuchColumnError, OperationalError, ResourceClosedError

from extensions import db
from modules.logging import get_structured_logger
from modules.production.models import LabelPrintJob, ProductionConfig
from modules.production.services import realtime_service

logger = get_structured_logger('production.print_agent')

print_agent_bp = Blueprint('print_agent', __name__)

_AGENT_JOB_TTL = timedelta(hours=1)

# Minimalny odstęp między przebiegami sprzątania wygasłych zadań.
# None = jeszcze nie sprzątaliśmy w tym workerze. Celowo None, a nie 0.0:
# time.monotonic() bywa liczone od startu procesu (tak jest na macOS), więc
# zero jako "dawno temu" oznaczałoby, że świeży worker przez pierwszą minutę
# nie sprząta w ogóle.
_EXPIRE_THROTTLE_SECONDS = 60
_last_expire_at = None

# Wyjątki które wskazują na padnięte połączenie z poola — agent puka co 5s,
# więc co jakiś czas trafia na martwy socket mimo pool_pre_ping.
_TRANSIENT_DB_ERRORS = (NoSuchColumnError, OperationalError, ResourceClosedError)


def _query_agent_token():
    row = ProductionConfig.query.filter_by(config_key='LABEL_PRINTER_AGENT_TOKEN').first()
    return (row.config_value or '').strip() if row else ''


def _get_agent_token():
    """Pobiera token agenta z prod_config; przy padniętym połączeniu robi
    rollback+invalidate i ponawia raz. Brak tokena = '' (agent dostanie 401)."""
    try:
        return _query_agent_token()
    except _TRANSIENT_DB_ERRORS as e:
        logger.warning("Padnięte połączenie podczas odczytu tokena agenta — retry",
                       extra={'error_type': type(e).__name__})
        try:
            db.session.rollback()
        except Exception:
            pass
        try:
            db.session.invalidate()
        except Exception:
            pass
        try:
            return _query_agent_token()
        except Exception as e2:
            logger.error("Retry tokena agenta nie powiódł się",
                         extra={'error_type': type(e2).__name__, 'error': str(e2)})
            return ''


def require_agent_token(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        header = request.headers.get('Authorization', '')
        prefix = 'Bearer '
        if not header.startswith(prefix):
            return jsonify({'error': 'unauthorized', 'reason': 'missing bearer'}), 401
        token = header[len(prefix):].strip()
        expected = _get_agent_token()
        if not expected or not token or token != expected:
            return jsonify({'error': 'unauthorized', 'reason': 'invalid token'}), 401
        return view(*args, **kwargs)
    return wrapper


def _expire_stale_pending(force=False):
    """Oznacza pending starsze niż _AGENT_JOB_TTL jako expired.

    Throttlowane do raz na _EXPIRE_THROTTLE_SECONDS: TTL to godzina, więc
    sprzątanie przy każdym GET /jobs było marnotrawstwem już przy pollingu co
    10 s, a przy sygnale push kadencja przestała być przewidywalna — seria
    wydruków potrafi zawołać /jobs kilkanaście razy w minutę.

    Licznik jest per-worker gunicorna. To wystarcza: kilku workerów oznacza
    kilka przebiegów na minutę zamiast jednego, a sam UPDATE jest idempotentny.
    """
    global _last_expire_at
    now = time.monotonic()
    if not force and _last_expire_at is not None and (now - _last_expire_at) < _EXPIRE_THROTTLE_SECONDS:
        return 0
    _last_expire_at = now

    cutoff = datetime.utcnow() - _AGENT_JOB_TTL
    expired_count = (LabelPrintJob.query
                     .filter(LabelPrintJob.status == 'pending',
                             LabelPrintJob.requested_at < cutoff)
                     .update({'status': 'expired',
                              'error_message': f'TTL: pending starsze niż {_AGENT_JOB_TTL}'},
                             synchronize_session=False))
    if expired_count:
        db.session.commit()
        logger.info("Expired stale print jobs", extra={'count': expired_count})
    return expired_count


@print_agent_bp.route('/jobs', methods=['GET'])
@require_agent_token
def list_jobs():
    """
    GET /api/print-agent/jobs?limit=10
    Zwraca listę pending zadań ZPL do wydrukowania (w kolejności FIFO).
    Przy okazji oznacza zadania starsze niż 1h jako expired.
    """
    _expire_stale_pending()

    try:
        limit = max(1, min(int(request.args.get('limit', 10)), 50))
    except (TypeError, ValueError):
        limit = 10

    jobs = (LabelPrintJob.query
            .filter_by(status='pending')
            .order_by(LabelPrintJob.requested_at.asc())
            .limit(limit)
            .all())

    return jsonify({
        'jobs': [
            {
                'id': j.id,
                'short_product_id': j.short_product_id,
                'baselinker_order_id': j.baselinker_order_id,
                'station_code': j.station_code,
                'zpl_payload': j.zpl_payload,
                'requested_at': j.requested_at.isoformat() if j.requested_at else None,
            }
            for j in jobs
        ],
        'count': len(jobs),
    }), 200


@print_agent_bp.route('/ack', methods=['POST'])
@require_agent_token
def ack_jobs():
    """
    POST /api/print-agent/ack
    Body: {"results": [{"id": 1, "success": true} | {"id": 2, "success": false, "error": "..."}]}
    Aktualizuje status zadań w kolejce.
    """
    data = request.get_json(silent=True) or {}
    results = data.get('results') or []
    if not isinstance(results, list):
        return jsonify({'error': 'invalid_results', 'reason': 'expected list'}), 400

    updated = 0
    for r in results:
        try:
            job_id = int(r.get('id'))
        except (TypeError, ValueError, AttributeError):
            continue
        success = bool(r.get('success'))
        error = (r.get('error') or '')[:1000] if not success else None
        job = LabelPrintJob.query.get(job_id)
        if not job or job.status != 'pending':
            continue
        job.status = 'printed' if success else 'failed'
        if success:
            job.printed_at = datetime.utcnow()
        else:
            job.error_message = error
        updated += 1

    if updated:
        db.session.commit()
        logger.info("Print agent ACK processed", extra={'updated': updated})

    return jsonify({'updated': updated}), 200


@print_agent_bp.route('/realtime-token', methods=['GET'])
@require_agent_token
def realtime_token():
    """
    GET /api/print-agent/realtime-token

    Wymienia stały Bearer agenta (LABEL_PRINTER_AGENT_TOKEN z prod_config) na
    krótkotrwały JWT do Centrifugo. Dzięki temu na hubie biura nie ląduje żaden
    dodatkowy sekret — agent ma dalej jedno hasło, to samo co do REST API.

    Zwraca 503 gdy realtime jest wyłączony albo nieskonfigurowany. Agent traktuje
    to jako "brak pusha" i spada na polling — bez błędu, bez retry-spamu.

    Response 200:
        {"enabled": true, "token": "<JWT>", "channel": "print:agent",
         "sse_url": "https://crm.woodpower.pl/realtime/connection/uni_sse",
         "expires_in": 3600}
    """
    if not realtime_service.is_enabled():
        return jsonify({'enabled': False, 'reason': 'realtime disabled'}), 503

    try:
        token, ttl = realtime_service.issue_connection_token(
            'print-agent', [realtime_service.CHANNEL_PRINT_AGENT],
        )
    except RuntimeError as e:
        logger.error("Nie udało się wystawić tokena realtime dla agenta",
                     extra={'error': str(e)})
        return jsonify({'enabled': False, 'reason': 'misconfigured'}), 503

    return jsonify({
        'enabled': True,
        'token': token,
        'channel': realtime_service.CHANNEL_PRINT_AGENT,
        'sse_url': realtime_service.sse_url(),
        'expires_in': ttl,
    }), 200
