# modules/production/routers/stations/__init__.py
"""
Station Routers sub-package dla modulu Production
==================================================

Monitory hali (tylko GET, bez akcji) — interfejsy wykonawcze stanowisk
zostaly usuniete w Etapie 0 profili pracownikow (docs/worker-profiles-backend.md),
produkcja dziala wylacznie przez apke mobilna.

Sub-modules:
- monitors.py: Station monitors + monitor AJAX
"""

from flask import Blueprint, render_template, request, url_for
from datetime import datetime, date
from modules.logging import get_structured_logger
from sqlalchemy.orm import joinedload

# Blueprint definition
station_bp = Blueprint('production_stations', __name__)
logger = get_structured_logger('production.stations')


# ============================================================================
# BEFORE/AFTER REQUEST HANDLERS
# ============================================================================

@station_bp.before_request
def apply_station_security():
    """Sprawdza IP tylko dla interfejsow stanowisk"""
    from ... import apply_security
    return apply_security()


@station_bp.before_request
def log_station_access():
    """Loguje dostep do interfejsow stanowisk - ERROR ONLY"""
    try:
        from .. import log_route_access
        log_route_access(request)
    except Exception as e:
        logger.error("Blad logowania dostepu do stanowiska", extra={'error': str(e)})


@station_bp.after_request
def add_station_headers(response):
    """Dodaje naglowki do odpowiedzi interfejsow stanowisk"""
    try:
        from .. import apply_common_headers
        response = apply_common_headers(response)

        # Dodatkowe naglowki dla interfejsow stanowisk
        response.headers['X-Station-Interface'] = '1.3.0'
        response.headers['X-Robots-Tag'] = 'noindex, nofollow'

        # Cache control dla interfejsow (nie cache'uj)
        if request.endpoint and 'ajax' not in request.endpoint:
            response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
            response.headers['Pragma'] = 'no-cache'
            response.headers['Expires'] = '0'

        return response

    except Exception as e:
        logger.error("Blad dodawania naglowkow stanowiska", extra={'error': str(e)})
        return response


# ============================================================================
# CONTEXT PROCESSORS
# ============================================================================

@station_bp.context_processor
def inject_station_context():
    """
    Injektuje wspolny kontekst dla wszystkich templates stanowisk

    Returns:
        Dict[str, Any]: Kontekst dostepny w templates
    """
    try:
        # Podstawowe informacje
        context = {
            'current_time': datetime.utcnow(),
            'current_date': date.today(),
            'station_version': '1.3.0',
            'client_ip': request.remote_addr,
        }

        # Konfiguracja (uproszczona dla templates)
        config = get_station_config()
        context['station_config'] = {
            'refresh_interval': config['refresh_interval'],
            'auto_refresh_enabled': config['auto_refresh_enabled'],
            'debug_mode': config['debug_frontend']
        }

        return context

    except Exception as e:
        logger.error("Blad context processor stanowiska", extra={'error': str(e)})
        return {
            'current_time': datetime.utcnow(),
            'current_date': date.today(),
            'station_version': '1.3.0',
            'client_ip': request.remote_addr or 'unknown'
        }


# ============================================================================
# ERROR HANDLERS
# ============================================================================

@station_bp.errorhandler(403)
def station_access_denied(error):
    """Handler dla bledow dostepu IP"""
    logger.warning("Odrzucono dostep do interfejsu stanowiska", extra={
        'client_ip': request.remote_addr,
        'path': request.path,
        'user_agent': request.headers.get('User-Agent')
    })

    return render_template(
        'stations/access_denied.html',
        error_message="Dostep zabroniony",
        error_details="Twoj adres IP nie jest autoryzowany do dostepu do stanowisk produkcyjnych.",
        client_ip=request.remote_addr
    ), 403


@station_bp.errorhandler(500)
def station_server_error(error):
    """Handler dla bledow serwera w interfejsach stanowisk"""
    from ...services.error_service import log_production_error

    # Loguj do Python logger
    logger.error("Blad serwera w interfejsie stanowiska", extra={
        'client_ip': request.remote_addr,
        'path': request.path,
        'error': str(error)
    })

    # Zapisz do bazy danych prod_errors
    error_type = 'template_error' if 'template' in str(error).lower() or 'jinja' in str(error).lower() else 'api_error'

    log_production_error(
        error_type=error_type,
        error_message=f"Blad 500 w interfejsie stanowiska: {str(error)}",
        exception=error if isinstance(error, Exception) else None,
        error_details={
            'path': request.path,
            'station_type': request.path.split('/')[-1] if '/' in request.path else 'unknown'
        }
    )

    return render_template(
        'stations/error.html',
        error_message="Blad systemu",
        error_details="Wystapil nieoczekiwany blad. Sprobuj odswiezyc strone.",
        back_url=url_for('production.production_stations.station_select')
    ), 500


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def get_station_config():
    """
    Pobiera konfiguracje dla interfejsow stanowisk

    Returns:
        Dict[str, Any]: Konfiguracja interfejsow
    """
    try:
        from ...services.config_service import get_config

        config = {
            'refresh_interval': get_config('REFRESH_INTERVAL_SECONDS', 30),
            'auto_refresh_enabled': get_config('STATION_AUTO_REFRESH_ENABLED', True),
            'debug_frontend': get_config('DEBUG_PRODUCTION_FRONTEND', False),
            'show_detailed_info': get_config('STATION_SHOW_DETAILED_INFO', True),
            'max_products_display': get_config('STATION_MAX_PRODUCTS_DISPLAY', 50)
        }

        return config

    except Exception as e:
        logger.error("Blad pobierania konfiguracji stanowisk", extra={'error': str(e)})
        return {
            'refresh_interval': 30,
            'auto_refresh_enabled': True,
            'debug_frontend': False,
            'show_detailed_info': True,
            'max_products_display': 50
        }


def _format_dimension(value):
    """Formatuje wymiar - z przecinkiem tylko gdy część dziesiętna != 0 (np. 160, 5,5, 3,5)"""
    if value is None:
        return None
    v = float(value)
    if v == int(v):
        return str(int(v))
    return f"{v:.1f}".replace('.', ',')


# Funkcja get_station_summary() usunieta w Etapie 0 profili pracownikow -
# zasilala wylacznie stations/select.html (ekran wyboru panelu wykonawczego),
# a i tak znala tylko 3 stanowiska z 6. Podsumowania dla panelu CRM licza
# dashboard_api.py i reports_api.py.


# Mapowanie kodu stanowiska na status w bazie i etykiete
MONITOR_STATION_MAP = {
    'cutting': {
        'status': 'czeka_na_wyciecie',
        'quantity_col': 'quantity_done_cutting',
        'label': 'Wycinanie - mikro',
        'css_class': 'status-cutting',
    },
    'assembly': {
        'status': 'czeka_na_skladanie',
        'quantity_col': 'quantity_done_assembly',
        'label': 'Składanie - lite',
        'css_class': 'status-assembly',
    },
    'gluing': {
        'status': 'czeka_na_sklejanie',
        'quantity_col': 'quantity_done_gluing',
        'label': 'Sklejanie',
        'css_class': 'status-gluing',
    },
    'formatting': {
        'status': 'czeka_na_formatowanie',
        'quantity_col': 'quantity_done_formatting',
        'label': 'Formatowanie',
        'css_class': 'status-formatting',
    },
    'finishing': {
        'status': 'czeka_na_wykanczanie',
        'quantity_col': 'quantity_done_finishing',
        'label': 'Wykańczanie',
        'css_class': 'status-finishing',
    },
    'packaging': {
        'status': 'czeka_na_pakowanie',
        'quantity_col': 'quantity_done_packaging',
        'label': 'Pakowanie',
        'css_class': 'status-packaging',
    },
}


def _get_monitor_station_data(station_code):
    """
    Pobiera zamowienia i statystyki dla danego stanowiska monitora.
    Filtruje prod_items po current_status odpowiadajacym stanowisku.
    Returns: (orders, monitor_stats, species_stats)
    """
    from ...models import ProductionItem, ProductionOrder, ProductionProduct

    station_info = MONITOR_STATION_MAP[station_code]
    target_status = station_info['status']
    quantity_col = station_info['quantity_col']

    # Pobierz unikalne zamowienia na tym stanowisku
    items_on_station = (
        ProductionProduct.query
        .options(
            joinedload(ProductionProduct.order),
            joinedload(ProductionProduct.configuration),
        )
        .join(ProductionOrder)
        .filter(
            ProductionProduct.current_status == target_status,
            ProductionOrder.internal_order_number.isnot(None)
        )
        .all()
    )

    # Grupuj po zamowieniu
    orders_map = {}
    for item in items_on_station:
        key = item.order.internal_order_number if item.order else None
        if key not in orders_map:
            orders_map[key] = {
                'order_number': key,
                'baselinker_order_id': item.order.baselinker_order_id if item.order else None,
                'client_order_number': item.order.client_order_number if item.order else None,
                'items': [],
            }
        orders_map[key]['items'].append(item)

    orders = []
    for key, data in orders_map.items():
        items = data['items']
        total_products = sum(i.quantity for i in items)
        completed_products = sum(getattr(i, quantity_col, 0) for i in items)
        total_volume = sum(float(i.volume_m3 or 0) * i.quantity for i in items)

        # Pobierz gatunek/technologie/klase z pierwszego itemu
        first = items[0]
        wood_species = (first.configuration.species if first.configuration else None) or '—'
        technology = (first.configuration.technology if first.configuration else None) or '—'
        wood_class = (first.configuration.wood_class if first.configuration else None) or '—'

        orders.append({
            'order_number': data['order_number'],
            'baselinker_order_id': data['baselinker_order_id'],
            'client_order_number': data['client_order_number'],
            'total_products': total_products,
            'completed_products': completed_products,
            'total_volume': total_volume,
            'wood_species': wood_species,
            'technology': technology,
            'wood_class': wood_class,
            'status_label': station_info['label'],
            'status_class': station_info['css_class'],
        })

    # Sortuj: najpierw z najwyzszym postepem
    orders.sort(key=lambda x: (
        -x['completed_products'] / max(x['total_products'], 1),
        x['order_number']
    ))

    # Stats ogolne
    monitor_stats = {
        'total_orders': len(orders),
        'total_products': sum(o['total_products'] for o in orders),
        'total_volume': sum(o['total_volume'] for o in orders),
    }

    # Stats per gatunek+technologia
    species_map = {}
    for item in items_on_station:
        _species = (item.configuration.species if item.configuration else None) or '—'
        _tech = (item.configuration.technology if item.configuration else None) or '—'
        key = f"{_species}|{_tech}"
        if key not in species_map:
            species_map[key] = {'species': _species, 'technology': _tech, 'count': 0, 'volume': 0.0}
        species_map[key]['count'] += item.quantity
        species_map[key]['volume'] += float(item.volume_m3 or 0) * item.quantity

    species_stats = sorted(species_map.values(), key=lambda x: -x['count'])

    return orders, monitor_stats, species_stats


# ============================================================================
# IMPORT SUB-MODULES (must be at the end to avoid circular imports)
# ============================================================================
from . import monitors    # noqa: E402, F401
