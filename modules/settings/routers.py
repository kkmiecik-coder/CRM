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
from .models import AppSetting
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
            return redirect(url_for('dashboard.dashboard'))

        return f(*args, **kwargs)

    return decorated_function


@settings_bp.route('/')
@require_admin
def index():
    """Strona główna ustawień - przekierowanie do ogólnych"""
    return redirect(url_for('settings.general'))


@settings_bp.route('/general')
@require_admin
def general():
    """Zakładka Ogólne - tryb konserwacji itp."""
    maintenance_enabled = AppSetting.get_value('maintenance_mode', 'false') == 'true'
    return render_template('settings_index.html',
                           active_tab='general',
                           maintenance_enabled=maintenance_enabled)


@settings_bp.route('/api/maintenance', methods=['POST'])
@require_admin
def api_toggle_maintenance():
    """API: Włącz/wyłącz tryb konserwacji"""
    from extensions import db
    from modules.dashboard.models import UserSession

    try:
        from datetime import datetime
        data = request.get_json()
        enabled = data.get('enabled', False)

        AppSetting.set_value('maintenance_mode',
                             'true' if enabled else 'false',
                             'Tryb konserwacji (maintenance mode)')

        # Jeśli włączamy — wyloguj wszystkich nie-adminów
        if enabled:
            active_sessions = UserSession.query.filter_by(is_active=True).all()
            for user_session in active_sessions:
                if user_session.user and not user_session.user.is_admin():
                    user_session.is_active = False
                    user_session.logout_time = datetime.utcnow()
            db.session.commit()

        return jsonify({
            'success': True,
            'enabled': enabled,
            'message': 'Tryb konserwacji włączony. Nie-adminowie zostali wylogowani.' if enabled
                       else 'Tryb konserwacji wyłączony.'
        })
    except Exception as e:
        current_app.logger.error(f"[Settings] Błąd przełączania trybu konserwacji: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


# =============================================
# APLIKACJA PRODUKCJA (mobile APK releases)
# =============================================

@settings_bp.route('/production-app')
@require_admin
def production_app():
    """Zakładka: zarządzanie release'ami APK aplikacji stanowiskowej."""
    from modules.production.services.mobile_api_service import list_releases

    user_email = session.get('user_email')
    current_user = User.query.filter_by(email=user_email).first()

    try:
        releases = list_releases()
    except Exception as e:
        current_app.logger.error(f"[production_app] Błąd listowania release'ów: {e}")
        releases = []

    return render_template(
        'settings_index.html',
        current_user=current_user,
        active_tab='production_app',
        mobile_releases=releases,
    )


@settings_bp.route('/api/mobile-releases/upload', methods=['POST'])
@require_admin
def api_mobile_release_upload():
    """Upload nowego APK + automatyczna rejestracja release'u."""
    from modules.production.services.mobile_api_service import register_release

    apk_file = request.files.get('apk')
    if apk_file is None:
        return jsonify({'success': False, 'error': 'Brak pliku APK'}), 400

    version_name = request.form.get('version_name', '').strip()
    release_notes = request.form.get('release_notes', '').strip()

    user_email = session.get('user_email')
    user = User.query.filter_by(email=user_email).first()

    try:
        release = register_release(
            file_storage=apk_file,
            version_name_override=version_name,
            release_notes=release_notes,
            user_id=user.id if user else None,
        )
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    except Exception as e:
        current_app.logger.error(f"[api_mobile_release_upload] Błąd: {e}")
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


@settings_bp.route('/api/mobile-releases/<int:release_id>/active', methods=['PATCH'])
@require_admin
def api_mobile_release_toggle_active(release_id):
    """Toggle is_active dla release'u APK."""
    from modules.production.services.mobile_api_service import set_release_active

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
        current_app.logger.error(f"[api_mobile_release_toggle_active] Błąd: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

    return jsonify({
        'success': True,
        'release': {
            'id': release.id,
            'version_code': release.version_code,
            'is_active': release.is_active,
        },
    }), 200


@settings_bp.route('/sources')
@require_admin
def sources():
    """Przekierowanie starych linków do nowej lokalizacji"""
    return redirect(url_for('settings.calculator_sources'))


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


# =============================================
# KALKULATOR
# =============================================

@settings_bp.route('/calculator')
@require_admin
def calculator():
    """Przekierowanie do pierwszej podzakładki kalkulatora"""
    return redirect(url_for('settings.calculator_prices'))


@settings_bp.route('/calculator/sources')
@require_admin
def calculator_sources():
    """Zarządzanie źródłami wycen - podzakładka kalkulatora"""
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
        active_tab='calculator',
        calculator_subtab='sources'
    )


@settings_bp.route('/calculator/prices')
@require_admin
def calculator_prices():
    """Zarządzanie cennikiem - tabela prices"""
    from modules.calculator.models import Price

    user_email = session.get('user_email')
    current_user = User.query.filter_by(email=user_email).first()

    # Pobierz wszystkie ceny posortowane
    all_prices = Price.query.order_by(
        Price.species,
        Price.technology,
        Price.wood_class,
        Price.width_min,
        Price.thickness_min
    ).all()

    # Pobierz unikalne wartości dla filtrów
    species_list = sorted(set(p.species for p in all_prices))
    technology_list = sorted(set(p.technology for p in all_prices))
    wood_class_list = sorted(set(p.wood_class for p in all_prices))

    return render_template(
        'settings_index.html',
        current_user=current_user,
        prices=all_prices,
        species_list=species_list,
        technology_list=technology_list,
        wood_class_list=wood_class_list,
        active_tab='calculator',
        calculator_subtab='prices'
    )


@settings_bp.route('/api/prices', methods=['GET'])
@require_admin
def api_get_prices():
    """API: Pobiera wszystkie ceny"""
    from modules.calculator.models import Price

    try:
        prices = Price.query.order_by(
            Price.species,
            Price.technology,
            Price.wood_class,
            Price.width_min,
            Price.thickness_min
        ).all()

        return jsonify({
            'success': True,
            'prices': [p.to_dict() for p in prices]
        })
    except Exception as e:
        current_app.logger.error(f"[api_get_prices] Błąd: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@settings_bp.route('/api/prices/<int:price_id>', methods=['PUT'])
@require_admin
def api_update_price(price_id):
    """API: Aktualizuje cenę"""
    from modules.calculator.models import Price
    from extensions import db
    from decimal import Decimal, InvalidOperation

    try:
        price = Price.query.get_or_404(price_id)
        data = request.get_json()

        # Walidacja i aktualizacja pól
        if 'species' in data:
            species = data['species'].strip()
            if not species:
                return jsonify({'success': False, 'error': 'Gatunek nie może być pusty'}), 400
            price.species = species

        if 'technology' in data:
            technology = data['technology'].strip()
            if not technology:
                return jsonify({'success': False, 'error': 'Technologia nie może być pusta'}), 400
            price.technology = technology

        if 'wood_class' in data:
            wood_class = data['wood_class'].strip()
            if not wood_class:
                return jsonify({'success': False, 'error': 'Klasa drewna nie może być pusta'}), 400
            price.wood_class = wood_class

        if 'thickness_min' in data:
            try:
                price.thickness_min = Decimal(str(data['thickness_min']))
            except (InvalidOperation, ValueError):
                return jsonify({'success': False, 'error': 'Nieprawidłowa wartość grubości min'}), 400

        if 'thickness_max' in data:
            try:
                price.thickness_max = Decimal(str(data['thickness_max']))
            except (InvalidOperation, ValueError):
                return jsonify({'success': False, 'error': 'Nieprawidłowa wartość grubości max'}), 400

        if 'length_min' in data:
            try:
                price.length_min = Decimal(str(data['length_min']))
            except (InvalidOperation, ValueError):
                return jsonify({'success': False, 'error': 'Nieprawidłowa wartość długości min'}), 400

        if 'length_max' in data:
            try:
                price.length_max = Decimal(str(data['length_max']))
            except (InvalidOperation, ValueError):
                return jsonify({'success': False, 'error': 'Nieprawidłowa wartość długości max'}), 400

        if 'width_min' in data:
            try:
                price.width_min = Decimal(str(data['width_min']))
            except (InvalidOperation, ValueError):
                return jsonify({'success': False, 'error': 'Nieprawidłowa wartość szerokości min'}), 400

        if 'width_max' in data:
            try:
                price.width_max = Decimal(str(data['width_max']))
            except (InvalidOperation, ValueError):
                return jsonify({'success': False, 'error': 'Nieprawidłowa wartość szerokości max'}), 400

        if 'price_per_m3' in data:
            try:
                price.price_per_m3 = Decimal(str(data['price_per_m3']))
            except (InvalidOperation, ValueError):
                return jsonify({'success': False, 'error': 'Nieprawidłowa wartość ceny'}), 400

        db.session.commit()

        return jsonify({
            'success': True,
            'price': price.to_dict()
        })
    except Exception as e:
        current_app.logger.error(f"[api_update_price] Błąd: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@settings_bp.route('/api/prices', methods=['POST'])
@require_admin
def api_create_price():
    """API: Tworzy nową cenę"""
    from modules.calculator.models import Price
    from extensions import db
    from decimal import Decimal, InvalidOperation

    try:
        data = request.get_json()

        # Walidacja wymaganych pól
        required_fields = ['species', 'technology', 'wood_class', 'thickness_min',
                          'thickness_max', 'length_min', 'length_max',
                          'width_min', 'width_max', 'price_per_m3']
        for field in required_fields:
            if field not in data or data[field] is None or str(data[field]).strip() == '':
                return jsonify({
                    'success': False,
                    'error': f'Pole {field} jest wymagane'
                }), 400

        try:
            price = Price(
                species=data['species'].strip(),
                technology=data['technology'].strip(),
                wood_class=data['wood_class'].strip(),
                thickness_min=Decimal(str(data['thickness_min'])),
                thickness_max=Decimal(str(data['thickness_max'])),
                length_min=Decimal(str(data['length_min'])),
                length_max=Decimal(str(data['length_max'])),
                width_min=Decimal(str(data['width_min'])),
                width_max=Decimal(str(data['width_max'])),
                price_per_m3=Decimal(str(data['price_per_m3']))
            )
        except (InvalidOperation, ValueError) as e:
            return jsonify({
                'success': False,
                'error': f'Nieprawidłowe wartości liczbowe: {str(e)}'
            }), 400

        db.session.add(price)
        db.session.commit()

        return jsonify({
            'success': True,
            'price': price.to_dict()
        }), 201
    except Exception as e:
        current_app.logger.error(f"[api_create_price] Błąd: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@settings_bp.route('/api/prices/<int:price_id>', methods=['DELETE'])
@require_admin
def api_delete_price(price_id):
    """API: Usuwa cenę"""
    from modules.calculator.models import Price
    from extensions import db

    try:
        price = Price.query.get_or_404(price_id)
        price_info = f"{price.species} {price.technology} {price.wood_class}"

        db.session.delete(price)
        db.session.commit()

        return jsonify({
            'success': True,
            'message': f'Cena "{price_info}" została usunięta'
        })
    except Exception as e:
        current_app.logger.error(f"[api_delete_price] Błąd: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


# =============================================
# CENNIK DODATKOWY (WYKOŃCZENIE + OBRÓBKA KRAWĘDZI)
# =============================================

@settings_bp.route('/calculator/extras')
@require_admin
def calculator_extras():
    """Przekierowanie do pierwszej podzakładki cennika dodatkowego"""
    return redirect(url_for('settings.calculator_finishing_tree'))


@settings_bp.route('/calculator/extras/finishing')
@require_admin
def calculator_extras_finishing():
    """Cennik wykończenia"""
    from modules.calculator.models import FinishingTypePrice

    user_email = session.get('user_email')
    current_user = User.query.filter_by(email=user_email).first()

    finishing_prices = FinishingTypePrice.query.order_by(FinishingTypePrice.id).all()

    return render_template(
        'settings_index.html',
        current_user=current_user,
        finishing_prices=finishing_prices,
        active_tab='calculator',
        calculator_subtab='extras',
        extras_subtab='finishing'
    )


@settings_bp.route('/calculator/extras/edges')
@require_admin
def calculator_extras_edges():
    """Cennik obróbki krawędzi"""
    from modules.calculator.models import EdgeOption, CalculatorSetting

    user_email = session.get('user_email')
    current_user = User.query.filter_by(email=user_email).first()

    edge_options = EdgeOption.query.order_by(EdgeOption.id).all()
    round_surcharge = CalculatorSetting.get_value('round_shape_surcharge_netto', '50.00')

    return render_template(
        'settings_index.html',
        current_user=current_user,
        edge_options=edge_options,
        round_surcharge=round_surcharge,
        active_tab='calculator',
        calculator_subtab='extras',
        extras_subtab='edges'
    )


@settings_bp.route('/api/calculator-settings', methods=['PUT'])
@require_admin
def api_update_calculator_settings():
    """API: Aktualizuje ustawienia kalkulatora"""
    from modules.calculator.models import CalculatorSetting
    from decimal import Decimal, InvalidOperation

    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'Brak danych'}), 400

        if 'round_shape_surcharge_netto' in data:
            try:
                value = Decimal(str(data['round_shape_surcharge_netto']))
                if value < 0:
                    return jsonify({'success': False, 'error': 'Dopłata nie może być ujemna'}), 400
                CalculatorSetting.set_value('round_shape_surcharge_netto', str(value))
            except (InvalidOperation, ValueError):
                return jsonify({'success': False, 'error': 'Nieprawidłowa wartość dopłaty'}), 400

        return jsonify({'success': True})
    except Exception as e:
        current_app.logger.error(f"[api_update_calculator_settings] Błąd: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@settings_bp.route('/api/finishing-prices/<int:price_id>', methods=['PUT'])
@require_admin
def api_update_finishing_price(price_id):
    """API: Aktualizuje cenę wykończenia"""
    from modules.calculator.models import FinishingTypePrice
    from extensions import db
    from decimal import Decimal, InvalidOperation

    try:
        price = FinishingTypePrice.query.get_or_404(price_id)
        data = request.get_json()

        if 'price_netto' in data:
            try:
                price.price_netto = Decimal(str(data['price_netto']))
            except (InvalidOperation, ValueError):
                return jsonify({'success': False, 'error': 'Nieprawidłowa wartość ceny'}), 400

        if 'is_active' in data:
            price.is_active = bool(data['is_active'])

        db.session.commit()

        return jsonify({
            'success': True,
            'price': price.to_dict()
        })
    except Exception as e:
        current_app.logger.error(f"[api_update_finishing_price] Błąd: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@settings_bp.route('/api/edge-options/<int:option_id>', methods=['PUT'])
@require_admin
def api_update_edge_option(option_id):
    """API: Aktualizuje opcję obróbki krawędzi"""
    from modules.calculator.models import EdgeOption
    from extensions import db
    from decimal import Decimal, InvalidOperation

    try:
        option = EdgeOption.query.get_or_404(option_id)
        data = request.get_json()

        if 'price_per_mb' in data:
            try:
                option.price_per_mb = Decimal(str(data['price_per_mb']))
            except (InvalidOperation, ValueError):
                return jsonify({'success': False, 'error': 'Nieprawidłowa wartość ceny za mb'}), 400

        if 'corner_price' in data:
            try:
                option.corner_price = Decimal(str(data['corner_price']))
            except (InvalidOperation, ValueError):
                return jsonify({'success': False, 'error': 'Nieprawidłowa wartość ceny za narożnik'}), 400

        if 'r_min' in data:
            option.r_min = int(data['r_min']) if data['r_min'] is not None else None

        if 'r_max' in data:
            option.r_max = int(data['r_max']) if data['r_max'] is not None else None

        if 'r_default' in data:
            option.r_default = int(data['r_default']) if data['r_default'] is not None else None

        if 'is_active' in data:
            option.is_active = bool(data['is_active'])

        db.session.commit()

        return jsonify({
            'success': True,
            'option': option.to_dict()
        })
    except Exception as e:
        current_app.logger.error(f"[api_update_edge_option] Błąd: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


# =============================================
# HIERARCHICZNE OPCJE WYKOŃCZEŃ (DRZEWKO)
# =============================================

@settings_bp.route('/calculator/extras/finishing-tree')
@require_admin
def calculator_finishing_tree():
    """Panel administracyjny dla hierarchicznych opcji wykończeń"""
    from modules.calculator.models import FinishingOption

    user_email = session.get('user_email')
    current_user = User.query.filter_by(email=user_email).first()

    # Pobierz płaską listę z głębokością dla renderowania
    finishing_options = FinishingOption.get_flat_list(include_inactive=False)

    return render_template(
        'settings_index.html',
        current_user=current_user,
        finishing_options=finishing_options,
        active_tab='calculator',
        calculator_subtab='extras',
        extras_subtab='finishing_tree'
    )


@settings_bp.route('/api/finishing-options', methods=['GET'])
@require_admin
def api_get_finishing_options():
    """API: Pobiera hierarchiczne opcje wykończeń"""
    from modules.calculator.models import FinishingOption

    try:
        tree = FinishingOption.get_tree()
        flat = FinishingOption.get_flat_list(include_inactive=False)

        return jsonify({
            'success': True,
            'tree': tree,
            'flat': flat
        })
    except Exception as e:
        current_app.logger.error(f"[api_get_finishing_options] Błąd: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@settings_bp.route('/api/finishing-options', methods=['POST'])
@require_admin
def api_create_finishing_option():
    """API: Tworzy nową opcję wykończenia"""
    from modules.calculator.models import FinishingOption
    from extensions import db
    from decimal import Decimal, InvalidOperation

    try:
        data = request.get_json()

        name = data.get('name', '').strip()
        if not name:
            return jsonify({'success': False, 'error': 'Nazwa jest wymagana'}), 400

        parent_id = data.get('parent_id')
        level = 0

        if parent_id:
            parent = FinishingOption.query.get(parent_id)
            if not parent:
                return jsonify({'success': False, 'error': 'Rodzic nie istnieje'}), 400
            level = parent.level + 1

        # Pobierz najwyższy sort_order dla rodzeństwa
        max_sort = db.session.query(db.func.max(FinishingOption.sort_order)).filter_by(
            parent_id=parent_id
        ).scalar() or 0

        # Przetwórz cenę
        price_netto = None
        if data.get('price_netto') is not None and str(data.get('price_netto')).strip() != '':
            try:
                price_netto = Decimal(str(data['price_netto']))
            except (InvalidOperation, ValueError):
                return jsonify({'success': False, 'error': 'Nieprawidłowa wartość ceny'}), 400

        option = FinishingOption(
            parent_id=parent_id,
            level=level,
            name=name,
            code=data.get('code', '').strip() or None,
            price_netto=price_netto,
            image_path=data.get('image_path', '').strip() or None,
            is_active=True,
            sort_order=max_sort + 1
        )

        db.session.add(option)
        db.session.commit()

        return jsonify({
            'success': True,
            'option': option.to_dict()
        }), 201
    except Exception as e:
        current_app.logger.error(f"[api_create_finishing_option] Błąd: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@settings_bp.route('/api/finishing-options/<int:option_id>', methods=['PUT'])
@require_admin
def api_update_finishing_option(option_id):
    """API: Aktualizuje opcję wykończenia"""
    from modules.calculator.models import FinishingOption
    from extensions import db
    from decimal import Decimal, InvalidOperation

    try:
        option = FinishingOption.query.get_or_404(option_id)
        data = request.get_json()

        if 'name' in data:
            name = data['name'].strip()
            if not name:
                return jsonify({'success': False, 'error': 'Nazwa nie może być pusta'}), 400
            option.name = name

        if 'code' in data:
            option.code = data['code'].strip() if data['code'] else None

        if 'price_netto' in data:
            if data['price_netto'] is None or str(data['price_netto']).strip() == '':
                option.price_netto = None
            else:
                try:
                    option.price_netto = Decimal(str(data['price_netto']))
                except (InvalidOperation, ValueError):
                    return jsonify({'success': False, 'error': 'Nieprawidłowa wartość ceny'}), 400

        if 'image_path' in data:
            option.image_path = data['image_path'].strip() if data['image_path'] else None

        if 'is_active' in data:
            option.is_active = bool(data['is_active'])

        db.session.commit()

        return jsonify({
            'success': True,
            'option': option.to_dict()
        })
    except Exception as e:
        current_app.logger.error(f"[api_update_finishing_option] Błąd: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@settings_bp.route('/api/finishing-options/<int:option_id>', methods=['DELETE'])
@require_admin
def api_delete_finishing_option(option_id):
    """API: Usuwa opcję wykończenia (soft delete - dezaktywacja)"""
    from modules.calculator.models import FinishingOption
    from extensions import db

    try:
        option = FinishingOption.query.get_or_404(option_id)
        option_name = option.name

        # Soft delete - dezaktywuj tę opcję i wszystkie dzieci rekurencyjnie
        def deactivate_recursive(opt):
            opt.is_active = False
            for child in opt.children:
                deactivate_recursive(child)

        deactivate_recursive(option)
        db.session.commit()

        return jsonify({
            'success': True,
            'message': f'Opcja "{option_name}" została usunięta'
        })
    except Exception as e:
        current_app.logger.error(f"[api_delete_finishing_option] Błąd: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@settings_bp.route('/api/finishing-options/<int:option_id>/move', methods=['POST'])
@require_admin
def api_move_finishing_option(option_id):
    """API: Przesuwa opcję wykończenia w górę lub w dół wśród rodzeństwa"""
    from modules.calculator.models import FinishingOption
    from extensions import db

    try:
        data = request.get_json()
        direction = data.get('direction')

        if direction not in ['up', 'down']:
            return jsonify({'success': False, 'error': 'Nieprawidłowy kierunek'}), 400

        option = FinishingOption.query.get_or_404(option_id)

        # Pobierz rodzeństwo (ten sam parent_id)
        siblings = FinishingOption.query.filter_by(
            parent_id=option.parent_id,
            is_active=True
        ).order_by(FinishingOption.sort_order).all()

        # Znajdź indeks aktualnej opcji
        current_index = None
        for i, s in enumerate(siblings):
            if s.id == option_id:
                current_index = i
                break

        if current_index is None:
            return jsonify({'success': False, 'error': 'Opcja nie znaleziona'}), 404

        # Sprawdź czy można przesunąć
        if direction == 'up' and current_index == 0:
            return jsonify({'success': False, 'error': 'Opcja jest już na pierwszej pozycji'}), 400
        if direction == 'down' and current_index == len(siblings) - 1:
            return jsonify({'success': False, 'error': 'Opcja jest już na ostatniej pozycji'}), 400

        # Zamień sort_order
        swap_index = current_index - 1 if direction == 'up' else current_index + 1

        current_order = siblings[current_index].sort_order
        swap_order = siblings[swap_index].sort_order

        siblings[current_index].sort_order = swap_order
        siblings[swap_index].sort_order = current_order

        db.session.commit()

        return jsonify({'success': True})
    except Exception as e:
        current_app.logger.error(f"[api_move_finishing_option] Błąd: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@settings_bp.route('/api/finishing-options/<int:option_id>/upload-image', methods=['POST'])
@require_admin
def api_upload_finishing_option_image(option_id):
    """API: Upload obrazka dla opcji wykończenia"""
    from modules.calculator.models import FinishingOption
    from extensions import db
    import os
    from werkzeug.utils import secure_filename

    try:
        option = FinishingOption.query.get_or_404(option_id)

        if 'image' not in request.files:
            return jsonify({'success': False, 'error': 'Brak pliku obrazka'}), 400

        file = request.files['image']
        if file.filename == '':
            return jsonify({'success': False, 'error': 'Nie wybrano pliku'}), 400

        # Sprawdź rozszerzenie
        allowed_extensions = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
        ext = file.filename.rsplit('.', 1)[1].lower() if '.' in file.filename else ''
        if ext not in allowed_extensions:
            return jsonify({
                'success': False,
                'error': f'Niedozwolone rozszerzenie pliku. Dozwolone: {", ".join(allowed_extensions)}'
            }), 400

        # Utwórz bezpieczną nazwę pliku
        filename = secure_filename(f"finishing_{option_id}_{option.name}.{ext}")

        # Ścieżka do zapisu
        upload_dir = os.path.join(current_app.root_path, 'modules', 'calculator', 'static', 'images', 'finishes')
        os.makedirs(upload_dir, exist_ok=True)

        filepath = os.path.join(upload_dir, filename)
        file.save(filepath)

        # Zapisz ścieżkę względną
        relative_path = f"images/finishes/{filename}"
        option.image_path = relative_path
        db.session.commit()

        return jsonify({
            'success': True,
            'image_path': relative_path,
            'option': option.to_dict()
        })
    except Exception as e:
        current_app.logger.error(f"[api_upload_finishing_option_image] Błąd: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


# =============================================
# BULK SAVE ENDPOINTS
# =============================================

@settings_bp.route('/api/order-sources/bulk', methods=['PUT'])
@require_admin
def api_bulk_update_order_sources():
    """API: Zapisuje wiele źródeł zamówień naraz"""
    from modules.baselinker.models import BaselinkerConfig
    from extensions import db

    try:
        data = request.get_json()
        items = data.get('items', [])

        if not items:
            return jsonify({'success': False, 'error': 'Brak danych do zapisania'}), 400

        updated = 0
        for item in items:
            source_id = item.get('id')
            if not source_id:
                continue

            source = BaselinkerConfig.query.get(source_id)
            if not source:
                continue

            if 'allowed_roles' in item:
                roles = item['allowed_roles']
                source.allowed_roles = roles if roles else None

            updated += 1

        db.session.commit()

        return jsonify({
            'success': True,
            'updated': updated
        })
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"[api_bulk_update_order_sources] Błąd: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@settings_bp.route('/api/prices/bulk', methods=['PUT'])
@require_admin
def api_bulk_update_prices():
    """API: Zapisuje wiele cen naraz"""
    from modules.calculator.models import Price
    from extensions import db
    from decimal import Decimal, InvalidOperation

    try:
        data = request.get_json()
        items = data.get('items', [])

        if not items:
            return jsonify({'success': False, 'error': 'Brak danych do zapisania'}), 400

        updated = 0
        errors = []

        for item in items:
            price_id = item.get('id')
            if not price_id:
                continue

            price = Price.query.get(price_id)
            if not price:
                errors.append(f"Cena o ID {price_id} nie istnieje")
                continue

            try:
                if 'species' in item:
                    price.species = item['species'].strip()
                if 'technology' in item:
                    price.technology = item['technology'].strip()
                if 'wood_class' in item:
                    price.wood_class = item['wood_class'].strip()
                if 'thickness_min' in item:
                    price.thickness_min = Decimal(str(item['thickness_min']))
                if 'thickness_max' in item:
                    price.thickness_max = Decimal(str(item['thickness_max']))
                if 'length_min' in item:
                    price.length_min = Decimal(str(item['length_min']))
                if 'length_max' in item:
                    price.length_max = Decimal(str(item['length_max']))
                if 'width_min' in item:
                    price.width_min = Decimal(str(item['width_min']))
                if 'width_max' in item:
                    price.width_max = Decimal(str(item['width_max']))
                if 'price_per_m3' in item:
                    price.price_per_m3 = Decimal(str(item['price_per_m3']))

                updated += 1
            except (InvalidOperation, ValueError) as e:
                errors.append(f"Błąd dla ID {price_id}: {str(e)}")

        db.session.commit()

        result = {'success': True, 'updated': updated}
        if errors:
            result['warnings'] = errors

        return jsonify(result)
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"[api_bulk_update_prices] Błąd: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@settings_bp.route('/api/finishing-options/bulk', methods=['PUT'])
@require_admin
def api_bulk_update_finishing_options():
    """API: Zapisuje wiele opcji wykończeń naraz"""
    from modules.calculator.models import FinishingOption
    from extensions import db
    from decimal import Decimal, InvalidOperation

    try:
        data = request.get_json()
        items = data.get('items', [])

        if not items:
            return jsonify({'success': False, 'error': 'Brak danych do zapisania'}), 400

        updated = 0
        errors = []

        for item in items:
            option_id = item.get('id')
            if not option_id:
                continue

            option = FinishingOption.query.get(option_id)
            if not option:
                errors.append(f"Opcja o ID {option_id} nie istnieje")
                continue

            try:
                if 'name' in item:
                    name = item['name'].strip()
                    if not name:
                        errors.append(f"Pusta nazwa dla ID {option_id}")
                        continue
                    option.name = name

                if 'code' in item:
                    option.code = item['code'].strip() if item['code'] else None

                if 'price_netto' in item:
                    if item['price_netto'] is None or str(item['price_netto']).strip() == '':
                        option.price_netto = None
                    else:
                        option.price_netto = Decimal(str(item['price_netto']))

                updated += 1
            except (InvalidOperation, ValueError) as e:
                errors.append(f"Błąd dla ID {option_id}: {str(e)}")

        db.session.commit()

        result = {'success': True, 'updated': updated}
        if errors:
            result['warnings'] = errors

        return jsonify(result)
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"[api_bulk_update_finishing_options] Błąd: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@settings_bp.route('/api/edge-options/bulk', methods=['PUT'])
@require_admin
def api_bulk_update_edge_options():
    """API: Zapisuje wiele opcji krawędzi naraz"""
    from modules.calculator.models import EdgeOption
    from extensions import db
    from decimal import Decimal, InvalidOperation

    try:
        data = request.get_json()
        items = data.get('items', [])

        if not items:
            return jsonify({'success': False, 'error': 'Brak danych do zapisania'}), 400

        updated = 0
        errors = []

        for item in items:
            option_id = item.get('id')
            if not option_id:
                continue

            option = EdgeOption.query.get(option_id)
            if not option:
                errors.append(f"Opcja o ID {option_id} nie istnieje")
                continue

            try:
                if 'price_per_mb' in item:
                    option.price_per_mb = Decimal(str(item['price_per_mb']))
                if 'corner_price' in item:
                    option.corner_price = Decimal(str(item['corner_price']))
                if 'r_min' in item:
                    option.r_min = int(item['r_min']) if item['r_min'] is not None else None
                if 'r_max' in item:
                    option.r_max = int(item['r_max']) if item['r_max'] is not None else None
                if 'r_default' in item:
                    option.r_default = int(item['r_default']) if item['r_default'] is not None else None

                # Kąty fazowania (tylko dla typu 'chamfer')
                if 'chamfer_angles' in item:
                    angles = item['chamfer_angles']
                    if angles is not None:
                        # Walidacja: musi być lista liczb 1-89
                        if not isinstance(angles, list):
                            errors.append(f"ID {option_id}: chamfer_angles musi być listą")
                            continue
                        for angle in angles:
                            if not isinstance(angle, int) or angle <= 0 or angle >= 90:
                                errors.append(f"ID {option_id}: kąty muszą być liczbami 1-89")
                                continue
                    option.chamfer_angles = angles

                if 'angle_default' in item:
                    angle_def = item['angle_default']
                    if angle_def is not None:
                        angle_def = int(angle_def)
                        # Walidacja: musi być w liście dozwolonych kątów
                        if option.chamfer_angles and angle_def not in option.chamfer_angles:
                            errors.append(f"ID {option_id}: domyślny kąt musi być na liście dozwolonych")
                            continue
                    option.angle_default = angle_def

                updated += 1
            except (InvalidOperation, ValueError) as e:
                errors.append(f"Błąd dla ID {option_id}: {str(e)}")

        db.session.commit()

        result = {'success': True, 'updated': updated}
        if errors:
            result['warnings'] = errors

        return jsonify(result)
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"[api_bulk_update_edge_options] Błąd: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@settings_bp.route('/api/sources/bulk', methods=['PUT'])
@require_admin
def api_bulk_update_sources():
    """API: Zapisuje wiele źródeł wycen naraz"""
    from modules.calculator.models import QuoteSource
    from extensions import db

    try:
        data = request.get_json()
        items = data.get('items', [])

        if not items:
            return jsonify({'success': False, 'error': 'Brak danych do zapisania'}), 400

        updated = 0
        errors = []

        for item in items:
            source_id = item.get('id')
            if not source_id:
                continue

            source = QuoteSource.query.get(source_id)
            if not source:
                errors.append(f"Źródło o ID {source_id} nie istnieje")
                continue

            try:
                if 'name' in item:
                    name = item['name'].strip()
                    if not name:
                        errors.append(f"Pusta nazwa dla ID {source_id}")
                        continue
                    source.name = name

                if 'allowed_roles' in item:
                    roles = item['allowed_roles']
                    source.allowed_roles = roles if roles else None

                if 'skip_contact_validation' in item:
                    source.skip_contact_validation = bool(item['skip_contact_validation'])

                updated += 1
            except Exception as e:
                errors.append(f"Błąd dla ID {source_id}: {str(e)}")

        db.session.commit()

        result = {'success': True, 'updated': updated}
        if errors:
            result['warnings'] = errors

        return jsonify(result)
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"[api_bulk_update_sources] Błąd: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500
