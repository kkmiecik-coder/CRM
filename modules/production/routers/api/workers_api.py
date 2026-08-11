# modules/production/routers/api/workers_api.py
"""
Profile pracowników — zakładka panelu CRM, CRUD i endpoint crona.

Projekt: docs/worker-profiles-backend.md (§7.1, §5.3)

Mobilna część katalogu i sesji NIE jest tutaj — siedzi w routers/mobile_api.py
pod /api/mobile, bo ma inną autoryzację (JWT urządzenia zamiast sesji CRM).
"""

import traceback

from flask import jsonify, render_template, request
from flask_login import current_user, login_required

from . import api_bp, logger
from .common_api import admin_required, cron_secret_required
from ...models import ProductionDevice
from ...services import worker_service
from ...services.worker_service import WorkerError


def _blad(e):
    """WorkerError → odpowiedź JSON w konwencji panelu ({success, error})."""
    payload, status = e.as_response()
    return jsonify({'success': False, 'error': payload.get('detail') or payload['error'],
                    'code': payload['error']}), status


def _serialize_worker(worker, statystyki=None):
    dane = {
        'id': worker.id,
        'first_name': worker.first_name,
        'last_name': worker.last_name,
        'full_name': worker.full_name,
        'initials': worker.initials,
        'color_hex': worker.tile_color,
        'color_hex_raw': worker.color_hex,
        'allowed_stations': worker.allowed_stations_list,
        'is_active': bool(worker.is_active),
        'sort_order': worker.sort_order or 0,
        'user_id': worker.user_id,
        'worker_code': worker.worker_code,
        'deactivated_at': worker.deactivated_at.isoformat() if worker.deactivated_at else None,
    }
    if statystyki:
        dane.update(statystyki.get(worker.id, {}))
    return dane


# ============================================================================
# ZAKŁADKA
# ============================================================================

@api_bp.route('/workers/tab-content')
@login_required
def workers_tab_content():
    """
    Zawartość zakładki Pracownicy. Zwraca gotowy HTML (nie JSON) — ten sam
    wzorzec co trakownia, patrz loadSawmillTab() w production-app-loader.js.
    """
    try:
        pracownicy = worker_service.list_workers(include_inactive=True)
        sesje = worker_service.get_active_sessions()

        return render_template(
            'components/workers-tab-content.html',
            workers=[_serialize_worker(w) for w in pracownicy],
            active_sessions=[worker_service.serialize_session_for_panel(s) for s in sesje],
            config=worker_service.get_worker_config(),
            station_codes=sorted(ProductionDevice.VALID_STATION_CODES),
        )
    except Exception as e:
        logger.error("Błąd zakładki pracowników", extra={
            'error': str(e), 'traceback': traceback.format_exc()})
        return f'<div class="alert alert-danger">Błąd ładowania: {e}</div>', 500


# ============================================================================
# CRUD
# ============================================================================

@api_bp.route('/workers', methods=['GET'])
@login_required
def workers_list():
    include_inactive = request.args.get('include_inactive', 'true').lower() == 'true'
    pracownicy = worker_service.list_workers(include_inactive=include_inactive)
    return jsonify({
        'success': True,
        'workers': [_serialize_worker(w) for w in pracownicy],
        'catalog_version': worker_service.get_catalog_version(),
    })


@api_bp.route('/workers', methods=['POST'])
@admin_required
def workers_create():
    dane = request.get_json(silent=True) or {}
    try:
        worker = worker_service.create_worker(
            dane.get('first_name'), dane.get('last_name'),
            color_hex=dane.get('color_hex'),
            allowed_stations=dane.get('allowed_stations'),
            sort_order=dane.get('sort_order', 0),
            user_id=dane.get('user_id'),
            worker_code=dane.get('worker_code'),
        )
    except WorkerError as e:
        return _blad(e)

    logger.info("Panel: dodano pracownika", extra={
        'worker_id': worker.id, 'user_id': getattr(current_user, 'id', None)})
    return jsonify({'success': True, 'worker': _serialize_worker(worker)}), 201


@api_bp.route('/workers/<int:worker_id>', methods=['PATCH'])
@admin_required
def workers_update(worker_id):
    dane = request.get_json(silent=True) or {}
    dozwolone = {'first_name', 'last_name', 'color_hex', 'allowed_stations',
                 'sort_order', 'user_id', 'worker_code'}
    pola = {k: v for k, v in dane.items() if k in dozwolone}
    try:
        worker = worker_service.update_worker(worker_id, **pola)
    except WorkerError as e:
        return _blad(e)
    return jsonify({'success': True, 'worker': _serialize_worker(worker)})


@api_bp.route('/workers/<int:worker_id>', methods=['DELETE'])
@admin_required
def workers_deactivate(worker_id):
    """
    Dezaktywacja, NIE kasowanie — statystyki historyczne muszą przetrwać,
    a FK z prod_station_event_workers i tak by kasowania nie pozwolił.
    """
    try:
        worker = worker_service.deactivate_worker(worker_id)
    except WorkerError as e:
        return _blad(e)
    return jsonify({'success': True, 'worker': _serialize_worker(worker)})


@api_bp.route('/workers/<int:worker_id>/reactivate', methods=['POST'])
@admin_required
def workers_reactivate(worker_id):
    try:
        worker = worker_service.reactivate_worker(worker_id)
    except WorkerError as e:
        return _blad(e)
    return jsonify({'success': True, 'worker': _serialize_worker(worker)})


# ============================================================================
# KTO TERAZ NA HALI
# ============================================================================

@api_bp.route('/workers/active-sessions', methods=['GET'])
@login_required
def workers_active_sessions():
    sesje = worker_service.get_active_sessions(
        station_code=request.args.get('station') or None)
    return jsonify({
        'success': True,
        'sessions': [worker_service.serialize_session_for_panel(s) for s in sesje],
    })


@api_bp.route('/workers/sessions/<int:session_id>/close', methods=['POST'])
@admin_required
def workers_close_session(session_id):
    try:
        sesja = worker_service.close_session_by_admin(session_id)
    except WorkerError as e:
        return _blad(e)
    return jsonify({'success': True,
                    'session': worker_service.serialize_session_for_panel(sesja)})


# ============================================================================
# CRON
# ============================================================================

@api_bp.route('/workers/close-stale-sessions', methods=['POST', 'GET'])
@cron_secret_required
def workers_close_stale_sessions():
    """
    Domyka sesje po bezczynności i po nocnym cutoffie.

    Wołane cronem hostingu co 5 min — w aplikacji NIE MA schedulera
    (scheduler_daemon.py usunięty w 2026-05-18), więc wpis w crontabie trzeba
    dodać ręcznie przy wdrożeniu. Wzorzec autoryzacji: /production/api/sync-cron
    (token, nie @login_required — cron nie ma sesji).

    Idempotentne: działa wyłącznie na wierszach z ended_at IS NULL.
    """
    try:
        wynik = worker_service.close_stale_sessions()
    except Exception as e:
        logger.error("CRON: błąd domykania sesji pracowników", extra={
            'error': str(e), 'traceback': traceback.format_exc()})
        return jsonify({'success': False, 'error': str(e)}), 500

    return jsonify({'success': True, 'closed': wynik})
