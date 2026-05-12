# modules/production/routers/admin_routers.py
"""
Admin AJAX endpoints for Production module.

Provides system health, dashboard stats, and error management
endpoints consumed by the production dashboard frontend.
"""

import json
from datetime import date, timedelta

from flask import Blueprint, request, jsonify
from flask_login import current_user
from sqlalchemy import and_, text

from modules.logging import get_structured_logger
from extensions import db
from modules.users.decorators import require_module_access
from ..models import get_local_now

# Blueprint — name must stay 'production_admin' (referenced via url_for)
admin_bp = Blueprint('production_admin', __name__)
logger = get_structured_logger('production.admin')


# ============================================================================
# BEFORE / AFTER REQUEST
# ============================================================================

@admin_bp.before_request
def log_admin_access():
    """Log access and apply route-level tracking."""
    try:
        from . import log_route_access
        log_route_access(request)
    except Exception as e:
        logger.error("Błąd logowania dostępu admin", extra={'error': str(e)})


@admin_bp.after_request
def add_admin_headers(response):
    """Add security / cache headers to every admin response."""
    try:
        from . import apply_common_headers
        response = apply_common_headers(response)
        response.headers['X-Robots-Tag'] = 'noindex, nofollow'
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        return response
    except Exception as e:
        logger.error("Błąd dodawania nagłówków admin", extra={'error': str(e)})
        return response


# ============================================================================
# ERROR HANDLERS
# ============================================================================

@admin_bp.errorhandler(403)
def admin_forbidden(error):
    return jsonify({'success': False, 'error': 'Brak uprawnień administratora'}), 403


@admin_bp.errorhandler(404)
def admin_not_found(error):
    return jsonify({'success': False, 'error': 'Nie znaleziono żądanego zasobu'}), 404


@admin_bp.errorhandler(500)
def admin_server_error(error):
    logger.error("Błąd serwera w panelu admin", extra={
        'user_id': current_user.id if current_user.is_authenticated else None,
        'error': str(error),
        'path': request.path
    })
    return jsonify({'success': False, 'error': 'Wystąpił błąd systemu'}), 500


# ============================================================================
# HELPER
# ============================================================================

def _get_admin_dashboard_data():
    """Gather dashboard statistics for the admin panel."""
    try:
        from ..models import ProductionItem, ProductionSyncLog, ProductionError

        now = get_local_now()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        day_ago = now - timedelta(hours=24)

        active_statuses = ['czeka_na_wyciecie', 'czeka_na_skladanie', 'czeka_na_pakowanie']

        total_products = ProductionItem.query.count()
        active_products = ProductionItem.query.filter(
            ProductionItem.current_status.in_(active_statuses)
        ).count()
        completed_today = ProductionItem.query.filter(
            and_(
                ProductionItem.current_status == 'spakowane',
                ProductionItem.packaging_completed_at >= today_start
            )
        ).count()

        total_errors = ProductionError.query.count()
        unresolved_errors = ProductionError.query.filter_by(is_resolved=False).count()
        errors_last_24h = ProductionError.query.filter(
            ProductionError.error_occurred_at >= day_ago
        ).count()

        last_sync = ProductionSyncLog.query.order_by(
            ProductionSyncLog.sync_started_at.desc()
        ).first()
        syncs_last_24h = ProductionSyncLog.query.filter(
            ProductionSyncLog.sync_started_at >= day_ago
        ).count()
        failed_syncs_last_24h = ProductionSyncLog.query.filter(
            and_(
                ProductionSyncLog.sync_started_at >= day_ago,
                ProductionSyncLog.sync_status == 'failed'
            )
        ).count()

        # System health assessment
        system_health = 'healthy'
        health_issues = []

        if unresolved_errors > 10:
            system_health = 'warning'
            health_issues.append(f"{unresolved_errors} nierozwiązanych błędów")
        if last_sync and last_sync.sync_started_at < now - timedelta(hours=25):
            system_health = 'warning'
            health_issues.append("Ostatnia synchronizacja ponad 25h temu")
        if failed_syncs_last_24h > 2:
            system_health = 'critical'
            health_issues.append(f"{failed_syncs_last_24h} błędnych synchronizacji w 24h")

        high_priority_products = ProductionItem.query.filter(
            and_(
                ProductionItem.priority_rank.isnot(None),
                ProductionItem.priority_rank <= 10,
                ProductionItem.current_status.in_(active_statuses)
            )
        ).count()

        overdue_products = ProductionItem.query.filter(
            and_(
                ProductionItem.deadline_date < date.today(),
                ProductionItem.current_status.in_(active_statuses)
            )
        ).count()

        return {
            'system_health': system_health,
            'health_issues': health_issues,
            'stats': {
                'total_products': total_products,
                'active_products': active_products,
                'completed_today': completed_today,
                'high_priority_products': high_priority_products,
                'overdue_products': overdue_products,
                'total_errors': total_errors,
                'unresolved_errors': unresolved_errors,
                'errors_last_24h': errors_last_24h,
                'syncs_last_24h': syncs_last_24h,
                'failed_syncs_last_24h': failed_syncs_last_24h
            },
            'last_sync': {
                'timestamp': last_sync.sync_started_at,
                'status': last_sync.sync_status,
                'products_created': last_sync.products_created,
                'error_count': last_sync.error_count
            } if last_sync else None,
            'generated_at': now
        }

    except Exception as e:
        logger.error("Błąd pobierania danych dashboardu", extra={'error': str(e)})
        return {
            'system_health': 'error',
            'health_issues': [f'Błąd pobierania danych: {str(e)}'],
            'stats': {},
            'last_sync': None,
            'generated_at': get_local_now()
        }


# ============================================================================
# AJAX ENDPOINTS
# ============================================================================

@admin_bp.route('/ajax/dashboard-stats')
@require_module_access('production')
def ajax_dashboard_stats():
    """AJAX endpoint for refreshing dashboard statistics."""
    try:
        dashboard_data = _get_admin_dashboard_data()
        return jsonify({'success': True, 'data': dashboard_data}), 200
    except Exception as e:
        logger.error("Błąd AJAX statystyk dashboardu", extra={
            'user_id': current_user.id,
            'error': str(e)
        })
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_bp.route('/ajax/system-errors')
@require_module_access('production')
def ajax_system_errors():
    """AJAX endpoint for fetching system errors (last 7 days, max 50)."""
    try:
        from ..models import ProductionError

        week_ago = get_local_now() - timedelta(days=7)

        errors = ProductionError.query.filter(
            ProductionError.error_occurred_at >= week_ago
        ).order_by(
            ProductionError.is_resolved.asc(),
            ProductionError.error_occurred_at.desc()
        ).limit(50).all()

        formatted_errors = []
        for error in errors:
            error_details = {}
            if error.error_details_json:
                try:
                    if isinstance(error.error_details_json, str):
                        error_details = json.loads(error.error_details_json)
                    else:
                        error_details = error.error_details_json
                except (json.JSONDecodeError, TypeError):
                    error_details = {}

            formatted_errors.append({
                'id': error.id,
                'error_type': error.error_type,
                'error_message': error.error_message,
                'error_details': error_details,
                'error_occurred_at': error.error_occurred_at.isoformat() if error.error_occurred_at else None,
                'is_resolved': error.is_resolved,
                'related_product_id': error.related_product_id,
                'related_order_id': error.related_order_id
            })

        return jsonify({
            'success': True,
            'errors': formatted_errors,
            'total_count': len(formatted_errors)
        }), 200

    except Exception as e:
        logger.error("Błąd pobierania błędów systemu", extra={
            'user_id': current_user.id,
            'error': str(e)
        })
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_bp.route('/ajax/clear-system-errors', methods=['POST'])
@require_module_access('production')
def ajax_clear_system_errors():
    """AJAX endpoint to mark all unresolved errors as resolved."""
    try:
        from ..models import ProductionError

        unresolved_errors = ProductionError.query.filter(
            ProductionError.is_resolved == False
        ).all()

        cleared_count = 0
        for error in unresolved_errors:
            error.resolve(
                user_id=current_user.id,
                resolution_notes="Błąd wyczyszczony masowo przez administratora"
            )
            cleared_count += 1

        db.session.commit()

        return jsonify({
            'success': True,
            'message': f'Wyczyszczono {cleared_count} błędów systemu',
            'cleared_count': cleared_count
        }), 200

    except Exception as e:
        db.session.rollback()
        logger.error("Błąd czyszczenia błędów systemu", extra={
            'user_id': current_user.id,
            'error': str(e)
        })
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_bp.route('/ajax/system-health')
@require_module_access('production')
def ajax_system_health():
    """AJAX endpoint for system health check (sync, DB, errors)."""
    try:
        from ..services.sync_service import get_sync_status
        from ..models import ProductionError, ProductionSyncLog

        sync_status = get_sync_status()

        day_ago = get_local_now() - timedelta(hours=24)

        unresolved_errors_24h = ProductionError.query.filter(
            ProductionError.error_occurred_at >= day_ago,
            ProductionError.is_resolved == False
        ).count()

        total_unresolved_errors = ProductionError.query.filter(
            ProductionError.is_resolved == False
        ).count()

        try:
            db.session.execute(text('SELECT 1'))
            database_status = 'ok'
        except Exception:
            database_status = 'error'

        last_sync_log = ProductionSyncLog.query.order_by(
            ProductionSyncLog.sync_started_at.desc()
        ).first()

        last_sync = last_sync_log.sync_started_at.isoformat() if last_sync_log and last_sync_log.sync_started_at else None
        sync_status_str = last_sync_log.sync_status if last_sync_log else 'never_run'

        health_data = {
            'database_status': database_status,
            'sync_status': sync_status_str,
            'last_sync': last_sync,
            'errors_24h': unresolved_errors_24h,
            'total_unresolved_errors': total_unresolved_errors,
            'baselinker_api_avg_ms': sync_status.get('api_response_time_ms', 0) if sync_status else 0
        }

        return jsonify({'success': True, 'health': health_data}), 200

    except Exception as e:
        logger.error("Błąd sprawdzania system health", extra={
            'user_id': current_user.id,
            'error': str(e)
        })
        return jsonify({'success': False, 'error': str(e)}), 500


# ============================================================================
# MOBILE APP RELEASES (auto-update APK dla tabletów stanowiskowych)
# ============================================================================

@admin_bp.route('/mobile/releases', methods=['GET'])
@require_module_access('production')
def mobile_releases_list():
    """GET /production/admin/mobile/releases — lista wszystkich release'ów APK."""
    from ..services.mobile_api_service import list_releases
    try:
        return jsonify({'success': True, 'releases': list_releases()}), 200
    except Exception as e:
        logger.error("Błąd listowania mobile releases", extra={
            'user_id': current_user.id,
            'error': str(e),
        })
        return jsonify({'success': False, 'error': str(e)}), 500


@admin_bp.route('/mobile/upload-apk', methods=['POST'])
@require_module_access('production')
def mobile_upload_apk():
    """
    POST /production/admin/mobile/upload-apk

    Multipart form: pole `apk` (plik), `version_code` (wymagane, int > 0,
    z build.gradle.kts), `version_name` (wymagane, string, max 32 znaki),
    `release_notes` (opcjonalnie). Backend waliduje versionCode
    > max(istniejących) i zapisuje plik do instance/mobile_apk/.
    """
    from ..services.mobile_api_service import register_release

    apk_file = request.files.get('apk')
    if apk_file is None:
        return jsonify({'success': False, 'error': 'Brak pola `apk` w formularzu'}), 400

    version_code_raw = request.form.get('version_code', '').strip()
    version_name = request.form.get('version_name', '').strip()
    release_notes = request.form.get('release_notes', '').strip()

    if not version_code_raw:
        return jsonify({'success': False, 'error': 'Pole `version_code` jest wymagane (z build.gradle.kts)'}), 400
    try:
        version_code = int(version_code_raw)
    except ValueError:
        return jsonify({'success': False, 'error': f'Pole `version_code` musi być liczbą całkowitą (otrzymano: {version_code_raw!r})'}), 400
    if version_code <= 0:
        return jsonify({'success': False, 'error': 'Pole `version_code` musi być większe od 0'}), 400

    if not version_name:
        return jsonify({'success': False, 'error': 'Pole `version_name` jest wymagane (z build.gradle.kts)'}), 400
    if len(version_name) > 32:
        return jsonify({'success': False, 'error': 'Pole `version_name` może mieć maksymalnie 32 znaki'}), 400

    try:
        release = register_release(
            file_storage=apk_file,
            version_code=version_code,
            version_name=version_name,
            release_notes=release_notes,
            user_id=current_user.id,
        )
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    except Exception as e:
        logger.error("Błąd uploadu APK", extra={
            'user_id': current_user.id,
            'error': str(e),
        })
        return jsonify({'success': False, 'error': str(e)}), 500

    return jsonify({
        'success': True,
        'release': {
            'id': release.id,
            'version_code': release.version_code,
            'version_name': release.version_name,
            'sha256': release.sha256,
            'file_size_bytes': release.file_size_bytes,
            'is_active': release.is_active,
        },
    }), 201


@admin_bp.route('/mobile/releases/<int:release_id>/active', methods=['PATCH'])
@require_module_access('production')
def mobile_release_toggle_active(release_id):
    """
    PATCH /production/admin/mobile/releases/<id>/active

    Body JSON: { is_active: bool } — pozwala wycofać/aktywować release.
    """
    from ..services.mobile_api_service import set_release_active

    data = request.get_json(silent=True) or {}
    if 'is_active' not in data or not isinstance(data['is_active'], bool):
        return jsonify({
            'success': False,
            'error': 'Wymagane pole boolean `is_active` w body JSON',
        }), 400

    try:
        release = set_release_active(release_id, data['is_active'])
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 404
    except Exception as e:
        logger.error("Błąd toggle is_active mobile release", extra={
            'release_id': release_id,
            'user_id': current_user.id,
            'error': str(e),
        })
        return jsonify({'success': False, 'error': str(e)}), 500

    return jsonify({
        'success': True,
        'release': {
            'id': release.id,
            'version_code': release.version_code,
            'is_active': release.is_active,
        },
    }), 200
