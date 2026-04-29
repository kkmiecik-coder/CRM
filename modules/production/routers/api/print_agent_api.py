"""
Endpointy dla print-agenta (skrypt na hubie biura).
Autoryzacja: nagłówek `Authorization: Bearer <LABEL_PRINTER_AGENT_TOKEN>`.
NIE wymaga sesji webowej.

Polling pattern: agent co 5s woła GET /api/print-agent/jobs?limit=10,
drukuje lokalnie ZPL z pola zpl_payload, potem POST /api/print-agent/ack
z listą wyników.

TTL: pending starsze niż 1h są oznaczane jako 'expired' przy każdym
GET /jobs i nigdy nie drukowane. Operator powinien ponownie kliknąć.
"""
from datetime import datetime, timedelta
from functools import wraps

from flask import Blueprint, jsonify, request

from extensions import db
from modules.logging import get_structured_logger
from modules.production.models import LabelPrintJob, ProductionConfig

logger = get_structured_logger('production.print_agent')

print_agent_bp = Blueprint('print_agent', __name__)

_AGENT_JOB_TTL = timedelta(hours=1)


def _get_agent_token():
    row = ProductionConfig.query.filter_by(config_key='LABEL_PRINTER_AGENT_TOKEN').first()
    return (row.config_value or '').strip() if row else ''


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


def _expire_stale_pending():
    """Oznacza pending starsze niż _AGENT_JOB_TTL jako expired."""
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
