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
    """Strona główna ustawień - przekierowanie do kalkulatora"""
    return redirect(url_for('settings.calculator'))


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
                          'thickness_max', 'length_min', 'length_max', 'price_per_m3']
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
    return redirect(url_for('settings.calculator_extras_finishing'))


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
    from modules.calculator.models import EdgeOption

    user_email = session.get('user_email')
    current_user = User.query.filter_by(email=user_email).first()

    edge_options = EdgeOption.query.order_by(EdgeOption.id).all()

    return render_template(
        'settings_index.html',
        current_user=current_user,
        edge_options=edge_options,
        active_tab='calculator',
        calculator_subtab='extras',
        extras_subtab='edges'
    )


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
