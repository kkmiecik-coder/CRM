# app/modules/settings/routers.py
"""
Routery modułu ustawień aplikacji
=================================

Endpointy:
- GET /settings/ - Strona główna ustawień (przekierowanie do pierwszej zakładki)
- GET /settings/sources - Zarządzanie źródłami wycen
- GET /settings/order-sources - Zarządzanie źródłami zamówień Baselinker
"""

from flask import render_template, redirect, url_for, session, flash, request, jsonify, current_app
from . import settings_bp
from modules.users.models import User


def require_admin(f):
    """Dekorator wymagający roli administratora"""
    from functools import wraps

    @wraps(f)
    def decorated_function(*args, **kwargs):
        user_email = session.get('user_email')
        if not user_email:
            flash('Wymagane zalogowanie.', 'error')
            return redirect(url_for('login'))

        user = User.query.filter_by(email=user_email).first()
        if not user or user.role != 'admin':
            flash('Brak uprawnień. Dostęp tylko dla administratorów.', 'error')
            return redirect(url_for('dashboard.index'))

        return f(*args, **kwargs)

    return decorated_function


@settings_bp.route('/')
@require_admin
def index():
    """Strona główna ustawień - przekierowanie do źródeł"""
    return redirect(url_for('settings.sources'))


@settings_bp.route('/sources')
@require_admin
def sources():
    """Zarządzanie źródłami wycen"""
    from modules.calculator.models import QuoteSource

    user_email = session.get('user_email')
    current_user = User.query.filter_by(email=user_email).first()

    # Pobierz wszystkie aktywne źródła posortowane
    all_sources = QuoteSource.query.filter_by(is_active=True).order_by(
        QuoteSource.sort_order
    ).all()

    return render_template(
        'settings_index.html',
        current_user=current_user,
        sources=all_sources,
        active_tab='sources'
    )


@settings_bp.route('/api/sources', methods=['GET'])
@require_admin
def api_get_sources():
    """API: Pobiera wszystkie źródła wycen"""
    from modules.calculator.models import QuoteSource

    try:
        sources = QuoteSource.query.filter_by(is_active=True).order_by(
            QuoteSource.sort_order
        ).all()

        return jsonify({
            'success': True,
            'sources': [s.to_dict() for s in sources]
        })
    except Exception as e:
        current_app.logger.error(f"[api_get_sources] Błąd: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@settings_bp.route('/api/sources/<int:source_id>', methods=['PUT'])
@require_admin
def api_update_source(source_id):
    """API: Aktualizuje źródło wyceny (nazwa, skip_contact_validation, allowed_roles)"""
    from modules.calculator.models import QuoteSource
    from extensions import db

    try:
        source = QuoteSource.query.get_or_404(source_id)
        data = request.get_json()

        if 'name' in data:
            name = data['name'].strip()
            if not name:
                return jsonify({'success': False, 'error': 'Nazwa nie może być pusta'}), 400
            source.name = name

        if 'skip_contact_validation' in data:
            source.skip_contact_validation = bool(data['skip_contact_validation'])

        # Aktualizuj allowed_roles (które role mogą używać źródła)
        if 'allowed_roles' in data:
            roles = data['allowed_roles']
            source.allowed_roles = roles if roles else None

        db.session.commit()

        return jsonify({
            'success': True,
            'source': source.to_dict()
        })
    except Exception as e:
        current_app.logger.error(f"[api_update_source] Błąd: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@settings_bp.route('/api/sources', methods=['POST'])
@require_admin
def api_create_source():
    """API: Tworzy nowe źródło wyceny"""
    from modules.calculator.models import QuoteSource
    from extensions import db

    try:
        data = request.get_json()

        name = data.get('name', '').strip()
        if not name:
            return jsonify({
                'success': False,
                'error': 'Nazwa jest wymagana'
            }), 400

        # Pobierz najwyższy sort_order i dodaj 1
        max_order = db.session.query(db.func.max(QuoteSource.sort_order)).scalar() or 0

        source = QuoteSource(
            name=name,
            sort_order=max_order + 1,
            is_active=True
        )

        db.session.add(source)
        db.session.commit()

        return jsonify({
            'success': True,
            'source': source.to_dict()
        }), 201
    except Exception as e:
        current_app.logger.error(f"[api_create_source] Błąd: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@settings_bp.route('/api/sources/<int:source_id>', methods=['DELETE'])
@require_admin
def api_delete_source(source_id):
    """API: Usuwa źródło wyceny"""
    from modules.calculator.models import QuoteSource
    from extensions import db

    try:
        source = QuoteSource.query.get_or_404(source_id)
        source_name = source.name

        db.session.delete(source)
        db.session.commit()

        return jsonify({
            'success': True,
            'message': f'Źródło "{source_name}" zostało usunięte'
        })
    except Exception as e:
        current_app.logger.error(f"[api_delete_source] Błąd: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@settings_bp.route('/api/sources/<int:source_id>/move', methods=['POST'])
@require_admin
def api_move_source(source_id):
    """API: Przesuwa źródło w górę lub w dół"""
    from modules.calculator.models import QuoteSource
    from extensions import db

    try:
        data = request.get_json()
        direction = data.get('direction')  # 'up' lub 'down'

        if direction not in ['up', 'down']:
            return jsonify({'success': False, 'error': 'Nieprawidłowy kierunek'}), 400

        # Pobierz wszystkie aktywne źródła posortowane
        sources = QuoteSource.query.filter_by(is_active=True).order_by(
            QuoteSource.sort_order
        ).all()

        # Znajdź indeks aktualnego źródła
        current_index = None
        for i, s in enumerate(sources):
            if s.id == source_id:
                current_index = i
                break

        if current_index is None:
            return jsonify({'success': False, 'error': 'Źródło nie znalezione'}), 404

        # Sprawdź czy można przesunąć
        if direction == 'up' and current_index == 0:
            return jsonify({'success': False, 'error': 'Źródło jest już na pierwszej pozycji'}), 400
        if direction == 'down' and current_index == len(sources) - 1:
            return jsonify({'success': False, 'error': 'Źródło jest już na ostatniej pozycji'}), 400

        # Zamień miejscami
        swap_index = current_index - 1 if direction == 'up' else current_index + 1

        # Zamień sort_order
        current_order = sources[current_index].sort_order
        swap_order = sources[swap_index].sort_order

        sources[current_index].sort_order = swap_order
        sources[swap_index].sort_order = current_order

        db.session.commit()

        return jsonify({'success': True})
    except Exception as e:
        current_app.logger.error(f"[api_move_source] Błąd: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


# =============================================
# ŹRÓDŁA ZAMÓWIEŃ BASELINKER
# =============================================

@settings_bp.route('/order-sources')
@require_admin
def order_sources():
    """Zarządzanie źródłami zamówień Baselinker"""
    from modules.baselinker.models import BaselinkerConfig

    user_email = session.get('user_email')
    current_user = User.query.filter_by(email=user_email).first()

    # Pobierz wszystkie źródła zamówień posortowane
    all_order_sources = BaselinkerConfig.query.filter_by(
        config_type='order_source',
        is_active=True
    ).order_by(BaselinkerConfig.sort_order).all()

    return render_template(
        'settings_index.html',
        current_user=current_user,
        order_sources=all_order_sources,
        active_tab='order_sources'
    )


@settings_bp.route('/api/order-sources', methods=['GET'])
@require_admin
def api_get_order_sources():
    """API: Pobiera wszystkie źródła zamówień Baselinker"""
    from modules.baselinker.models import BaselinkerConfig

    try:
        sources = BaselinkerConfig.query.filter_by(
            config_type='order_source',
            is_active=True
        ).order_by(BaselinkerConfig.sort_order).all()

        return jsonify({
            'success': True,
            'sources': [s.to_dict(include_config=True) for s in sources]
        })
    except Exception as e:
        current_app.logger.error(f"[api_get_order_sources] Błąd: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@settings_bp.route('/api/order-sources/<int:source_db_id>', methods=['PUT'])
@require_admin
def api_update_order_source(source_db_id):
    """API: Aktualizuje konfigurację źródła zamówień"""
    from modules.baselinker.models import BaselinkerConfig
    from extensions import db

    try:
        source = BaselinkerConfig.query.get_or_404(source_db_id)
        data = request.get_json()

        # Aktualizuj allowed_roles (kto może wybierać źródło)
        if 'allowed_roles' in data:
            roles = data['allowed_roles']
            source.allowed_roles = roles if roles else None

        # Aktualizuj visible_for_roles (widoczność w ustawieniach)
        if 'visible_for_roles' in data:
            roles = data['visible_for_roles']
            source.visible_for_roles = roles if roles else None

        # Aktualizuj assigned_user_ids (użytkownicy dla których źródło jest domyślne)
        if 'assigned_user_ids' in data:
            user_ids = data['assigned_user_ids']
            source.assigned_user_ids = user_ids if user_ids else None

        # Aktualizuj is_default
        if 'is_default' in data:
            # Jeśli ustawiamy nowe domyślne, usuń poprzednie
            if data['is_default']:
                BaselinkerConfig.query.filter_by(
                    config_type='order_source',
                    is_default=True
                ).update({'is_default': False})
            source.is_default = bool(data['is_default'])

        db.session.commit()

        return jsonify({
            'success': True,
            'source': source.to_dict(include_config=True)
        })
    except Exception as e:
        current_app.logger.error(f"[api_update_order_source] Błąd: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@settings_bp.route('/api/order-sources/<int:source_db_id>/move', methods=['POST'])
@require_admin
def api_move_order_source(source_db_id):
    """API: Przesuwa źródło zamówień w górę lub w dół"""
    from modules.baselinker.models import BaselinkerConfig
    from extensions import db

    try:
        data = request.get_json()
        direction = data.get('direction')  # 'up' lub 'down'

        if direction not in ['up', 'down']:
            return jsonify({'success': False, 'error': 'Nieprawidłowy kierunek'}), 400

        # Pobierz wszystkie źródła zamówień posortowane
        sources = BaselinkerConfig.query.filter_by(
            config_type='order_source',
            is_active=True
        ).order_by(BaselinkerConfig.sort_order).all()

        # Znajdź indeks aktualnego źródła
        current_index = None
        for i, s in enumerate(sources):
            if s.id == source_db_id:
                current_index = i
                break

        if current_index is None:
            return jsonify({'success': False, 'error': 'Źródło nie znalezione'}), 404

        # Sprawdź czy można przesunąć
        if direction == 'up' and current_index == 0:
            return jsonify({'success': False, 'error': 'Źródło jest już na pierwszej pozycji'}), 400
        if direction == 'down' and current_index == len(sources) - 1:
            return jsonify({'success': False, 'error': 'Źródło jest już na ostatniej pozycji'}), 400

        # Zamień miejscami
        swap_index = current_index - 1 if direction == 'up' else current_index + 1

        # Zamień sort_order
        current_order = sources[current_index].sort_order
        swap_order = sources[swap_index].sort_order

        sources[current_index].sort_order = swap_order
        sources[swap_index].sort_order = current_order

        db.session.commit()

        return jsonify({'success': True})
    except Exception as e:
        current_app.logger.error(f"[api_move_order_source] Błąd: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@settings_bp.route('/api/order-sources/<int:source_db_id>', methods=['DELETE'])
@require_admin
def api_delete_order_source(source_db_id):
    """API: Usuwa źródło zamówień (ustawia is_active=False)"""
    from modules.baselinker.models import BaselinkerConfig
    from extensions import db

    try:
        source = BaselinkerConfig.query.get_or_404(source_db_id)
        source_name = source.name

        # Soft delete - ustawiamy is_active=False
        source.is_active = False
        db.session.commit()

        return jsonify({
            'success': True,
            'message': f'Źródło "{source_name}" zostało usunięte'
        })
    except Exception as e:
        current_app.logger.error(f"[api_delete_order_source] Błąd: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@settings_bp.route('/api/order-sources/sync', methods=['POST'])
@require_admin
def api_sync_order_sources():
    """API: Synchronizuje źródła zamówień z Baselinker"""
    from modules.baselinker.models import BaselinkerConfig
    from modules.baselinker.service import BaselinkerService
    from extensions import db

    try:
        service = BaselinkerService()
        result = service.sync_order_sources()

        if result.get('success'):
            return jsonify({
                'success': True,
                'message': f"Zsynchronizowano {result.get('synced', 0)} źródeł",
                'synced': result.get('synced', 0)
            })
        else:
            return jsonify({
                'success': False,
                'error': result.get('error', 'Nieznany błąd synchronizacji')
            }), 500
    except Exception as e:
        current_app.logger.error(f"[api_sync_order_sources] Błąd: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500
