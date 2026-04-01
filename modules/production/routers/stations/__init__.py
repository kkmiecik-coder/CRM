# modules/production/routers/stations/__init__.py
"""
Station Routers sub-package dla modulu Production
==================================================

Interfejsy stanowisk produkcyjnych zoptymalizowane pod tablety.

Sub-modules:
- interfaces.py: 6 station tablet interfaces
- monitors.py: Station monitors + monitor AJAX
- ajax.py: AJAX data endpoints
- shipping.py: Packaging/shipping API
"""

from flask import Blueprint, render_template, request, url_for, jsonify
from datetime import datetime, date, timedelta
from modules.logging import get_structured_logger
from extensions import db
import traceback

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

        # URL helpers dla navigation
        context['station_urls'] = {
            'select': url_for('production.production_stations.station_select'),
            'cutting': url_for('production.production_stations.cutting_station'),
            'assembly': url_for('production.production_stations.assembly_station'),
            'packaging': url_for('production.production_stations.packaging_station')
        }

        # AJAX URLs
        context['ajax_urls'] = {
            'products': lambda station: url_for('production.production_stations.ajax_get_products', station_code=station),
            'summary': url_for('production.production_stations.ajax_station_summary'),
            'config': url_for('production.production_stations.get_station_frontend_config')
        }

        # API URLs (dla complete-task)
        context['api_urls'] = {
            'complete_task': '/production/api/complete-task',
            'get_products': '/production/api/get-products'
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
# TEMPLATE FILTERS
# ============================================================================

@station_bp.app_template_filter('format_priority')
def format_priority_filter(priority_rank):
    """
    Template filter dla formatowania priorytetu
    POPRAWKA: bazuje na priority_rank (nizszy = lepszy)
    """
    if not priority_rank:
        priority_rank = 999

    if priority_rank <= 10:
        return f"🔴 #{priority_rank} (Krytyczny)"
    elif priority_rank <= 50:
        return f"🟠 #{priority_rank} (Wysoki)"
    elif priority_rank <= 100:
        return f"🟡 #{priority_rank} (Normalny)"
    else:
        return f"🟢 #{priority_rank} (Niski)"


@station_bp.app_template_filter('format_deadline')
def format_deadline_filter(deadline_date):
    """Template filter dla formatowania deadline"""
    if not deadline_date:
        return "Brak terminu"

    if isinstance(deadline_date, str):
        try:
            deadline_date = datetime.strptime(deadline_date, '%Y-%m-%d').date()
        except ValueError:
            return "Nieprawidlowa data"

    days_diff = (deadline_date - date.today()).days

    if days_diff < 0:
        return f"⚠️ Opoznione o {abs(days_diff)} dni"
    elif days_diff == 0:
        return "🔥 Dzis!"
    elif days_diff == 1:
        return "⚡ Jutro"
    elif days_diff <= 3:
        return f"🟡 Za {days_diff} dni"
    elif days_diff <= 7:
        return f"🟢 Za {days_diff} dni"
    else:
        return deadline_date.strftime("📅 %d.%m.%Y")


@station_bp.app_template_filter('format_volume')
def format_volume_filter(volume_m3):
    """Template filter dla formatowania objetosci"""
    if not volume_m3:
        return "—"

    try:
        volume = float(volume_m3)
        if volume >= 1.0:
            return f"{volume:.2f} m³"
        else:
            return f"{volume:.3f} m³"
    except (ValueError, TypeError):
        return "—"


@station_bp.app_template_filter('format_currency')
def format_currency_filter(amount):
    """Template filter dla formatowania kwot"""
    if not amount:
        return "—"

    try:
        amount = float(amount)
        return f"{amount:,.2f} PLN".replace(",", " ")
    except (ValueError, TypeError):
        return "—"


@station_bp.app_template_filter('truncate_smart')
def truncate_smart_filter(text, length=50):
    """Template filter dla inteligentnego skracania tekstu"""
    if not text or len(text) <= length:
        return text

    # Sprobuj skrocic na granicy slowa
    truncated = text[:length]
    last_space = truncated.rfind(' ')

    if last_space > length * 0.75:
        return truncated[:last_space] + "..."
    else:
        return truncated + "..."


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


def get_products_for_station(station_code, limit=50, sort_by='priority'):
    """
    Pobiera produkty dla konkretnego stanowiska

    Args:
        station_code (str): Kod stanowiska
        limit (int): Limit produktow
        sort_by (str): Sposob sortowania (priority|deadline|created_at)

    Returns:
        List[Dict]: Lista produktow z dodatkowymi informacjami
    """
    try:
        from ...models import ProductionItem
        from sqlalchemy import asc, desc

        # Mapowanie statusow na stanowiska
        status_map = {
            'cutting': 'czeka_na_wyciecie',
            'assembly': 'czeka_na_skladanie',
            'packaging': 'czeka_na_pakowanie'
        }

        if station_code not in status_map:
            logger.warning("Nieprawidlowy kod stanowiska", extra={'station_code': station_code})
            return []

        # Query podstawowy
        query = ProductionItem.query.filter_by(
            current_status=status_map[station_code]
        )

        # Sortowanie - POPRAWIONE POD NOWY MODEL (priority_rank)
        if sort_by == 'priority':
            query = query.order_by(asc(ProductionItem.priority_rank))
        elif sort_by == 'deadline':
            query = query.order_by(asc(ProductionItem.deadline_date))
        elif sort_by == 'created_at':
            query = query.order_by(asc(ProductionItem.created_at))
        else:
            query = query.order_by(asc(ProductionItem.priority_rank))

        # Wykonanie query
        products = query.limit(limit).all()

        # Przygotowanie danych z dodatkowymi informacjami
        products_data = []
        today = date.today()

        for product in products:
            # POPRAWKA: priority_rank zamiast priority_score
            priority_rank = product.priority_rank if product.priority_rank else 999

            # Obliczenie koloru priorytetu NA PODSTAWIE RANGI (nizszy rank = wyzszy priorytet)
            if priority_rank <= 10:
                priority_color = 'critical'
                priority_class = 'priority-critical'
                priority_label = 'Najwyzszy'
            elif priority_rank <= 50:
                priority_color = 'high'
                priority_class = 'priority-high'
                priority_label = 'Wysoki'
            elif priority_rank <= 100:
                priority_color = 'normal'
                priority_class = 'priority-normal'
                priority_label = 'Normalny'
            else:
                priority_color = 'low'
                priority_class = 'priority-low'
                priority_label = 'Niski'

            # Obliczenie koloru deadline
            if product.deadline_date:
                days_diff = (product.deadline_date - today).days
                if days_diff < 0:
                    deadline_color = 'overdue'
                    deadline_class = 'deadline-overdue'
                elif days_diff <= 1:
                    deadline_color = 'urgent'
                    deadline_class = 'deadline-urgent'
                elif days_diff <= 3:
                    deadline_color = 'soon'
                    deadline_class = 'deadline-soon'
                else:
                    deadline_color = 'normal'
                    deadline_class = 'deadline-normal'
            else:
                deadline_color = 'unknown'
                deadline_class = 'deadline-unknown'

            # Formatowanie wymiarow w CM
            dimensions_text = ''
            if all([product.parsed_length_cm, product.parsed_width_cm, product.parsed_thickness_cm]):
                dimensions_text = f"{_format_dimension(product.parsed_length_cm)} × {_format_dimension(product.parsed_width_cm)} × {_format_dimension(product.parsed_thickness_cm)} cm"

            # POPRAWKA: Bezpieczne pobieranie volume_m3
            try:
                volume_m3 = float(product.volume_m3) if product.volume_m3 else 0.0
            except (TypeError, ValueError):
                volume_m3 = 0.0

            # POPRAWKA: Bezpieczne pobieranie total_value_net
            try:
                total_value = float(product.total_value_net) if product.total_value_net else 0.0
            except (TypeError, ValueError):
                total_value = 0.0

            # Przygotowanie danych produktu
            product_data = {
                # Podstawowe ID
                'id': product.short_product_id,
                'internal_order': product.internal_order_number,
                'baselinker_order_id': product.baselinker_order_id,
                'original_name': product.original_product_name,
                'current_status': product.current_status,

                # POPRAWKA: priority_rank zamiast priority_score/priority_level
                'priority_rank': priority_rank,
                'priority_label': priority_label,
                'priority_color': priority_color,
                'priority_class': priority_class,

                # Deadline
                'deadline_date': product.deadline_date,
                'days_until_deadline': product.days_until_deadline,
                'is_overdue': product.is_overdue,
                'deadline_color': deadline_color,
                'deadline_class': deadline_class,

                # Dane finansowe i techniczne
                'volume_m3': volume_m3,
                'total_value_net': total_value,
                'created_at': product.created_at,
                'payment_date': product.payment_date,

                # Specyfikacja produktu
                'wood_species': product.parsed_wood_species,
                'technology': product.parsed_technology,
                'wood_class': product.parsed_wood_class,
                'dimensions': dimensions_text,
                'finish_state': product.parsed_finish_state,
                'thickness_group': product.thickness_group,

                # Klient
                'client_name': product.client_name,

                # Zalaczniki
                'attachment_file_name': product.attachment_file_name,
                'attachment_file_url': product.attachment_file_url,

                # Ilosc - nowy system quantity (2025-11)
                'quantity': product.quantity,
                'quantity_done': getattr(product, f'quantity_done_{station_code}', 0),
                'is_complete': getattr(product, f'quantity_done_{station_code}', 0) == product.quantity,
                'is_priority': product.is_priority,

                # Formatowane teksty dla UI
                'display_name': _format_product_display_name(product),
                'display_priority': f"#{priority_rank} - {priority_label}",
                'display_deadline': _format_deadline_display(product),
                'display_value': f"{total_value:.2f} PLN" if total_value > 0 else "—",
                'display_volume': f"{volume_m3:.3f} m³" if volume_m3 > 0 else "—"
            }

            products_data.append(product_data)

        return products_data

    except Exception as e:
        logger.error("Blad pobierania produktow dla stanowiska", extra={
            'station_code': station_code,
            'error': str(e),
            'traceback': traceback.format_exc()
        })
        return []


def _format_dimension(value):
    """Formatuje wymiar - zawsze z jednym miejscem po przecinku (np. 160.0, 5.5, 3.5)"""
    if value is None:
        return None
    return f"{float(value):.1f}"


def _format_product_display_name(product):
    """
    Formatuje nazwe produktu do wyswietlenia

    Args:
        product: Obiekt ProductionItem

    Returns:
        str: Sformatowana nazwa
    """
    parts = []

    if product.parsed_wood_species:
        parts.append(product.parsed_wood_species.title())

    if product.parsed_technology:
        parts.append(product.parsed_technology.title())

    if product.parsed_wood_class:
        parts.append(f"Klasa {product.parsed_wood_class}")

    if all([product.parsed_length_cm, product.parsed_width_cm, product.parsed_thickness_cm]):
        dimensions = f"{product.parsed_length_cm}×{product.parsed_width_cm}×{product.parsed_thickness_cm} cm"
        parts.append(dimensions)

    if product.parsed_finish_state and product.parsed_finish_state.lower() != 'surowe':
        parts.append(product.parsed_finish_state.title())

    if parts:
        return " | ".join(parts)
    else:
        # Fallback do oryginalnej nazwy (skroconej)
        original = product.original_product_name or "Brak nazwy"
        if len(original) > 60:
            return original[:57] + "..."
        return original


def _format_deadline_display(product):
    """
    Formatuje deadline do wyswietlenia

    Args:
        product: Obiekt ProductionItem

    Returns:
        str: Sformatowany deadline
    """
    if not product.deadline_date:
        return "Brak terminu"

    try:
        days_diff = (product.deadline_date - date.today()).days

        if days_diff < 0:
            return f"Opoznione o {abs(days_diff)} dni"
        elif days_diff == 0:
            return "Dzis!"
        elif days_diff == 1:
            return "Jutro"
        elif days_diff <= 7:
            return f"Za {days_diff} dni"
        else:
            return product.deadline_date.strftime("%d.%m.%Y")
    except Exception as e:
        logger.warning("Blad formatowania deadline", extra={'error': str(e)})
        return "Blad daty"


def get_station_summary():
    """
    Pobiera podsumowanie wszystkich stanowisk dla wyboru stanowiska

    Returns:
        Dict[str, Dict]: Podsumowanie per stanowisko
    """
    try:
        from ...models import ProductionItem
        from sqlalchemy import func

        # Query dla wszystkich statusow jednoczesnie - POPRAWKA: priority_rank zamiast priority_score
        summary_data = db.session.query(
            ProductionItem.current_status,
            func.count(ProductionItem.id).label('count'),
            func.sum(ProductionItem.volume_m3).label('volume'),
            func.avg(ProductionItem.priority_rank).label('avg_rank')
        ).filter(
            ProductionItem.current_status.in_([
                'czeka_na_wyciecie',
                'czeka_na_skladanie',
                'czeka_na_pakowanie'
            ])
        ).group_by(ProductionItem.current_status).all()

        # Mapowanie na stacje
        status_to_station = {
            'czeka_na_wyciecie': 'cutting',
            'czeka_na_skladanie': 'assembly',
            'czeka_na_pakowanie': 'packaging'
        }

        station_names = {
            'cutting': 'Wycinanie',
            'assembly': 'Skladanie',
            'packaging': 'Pakowanie'
        }

        summary = {}

        # Inicjalizacja wszystkich stacji
        for station_code, station_name in station_names.items():
            summary[station_code] = {
                'name': station_name,
                'count': 0,
                'volume_m3': 0.0,
                'avg_priority_rank': 999,
                'status_class': 'station-empty'
            }

        # Wypelnienie danymi
        for status, count, volume, avg_rank in summary_data:
            station_code = status_to_station.get(status)
            if station_code:
                summary[station_code].update({
                    'count': count,
                    'volume_m3': float(volume or 0),
                    'avg_priority_rank': round(float(avg_rank or 999), 1)
                })

                # Okreslenie klasy CSS na podstawie liczby zadan
                if count == 0:
                    summary[station_code]['status_class'] = 'station-empty'
                elif count <= 5:
                    summary[station_code]['status_class'] = 'station-low'
                elif count <= 15:
                    summary[station_code]['status_class'] = 'station-medium'
                else:
                    summary[station_code]['status_class'] = 'station-high'

        return summary

    except Exception as e:
        logger.error("Blad pobierania podsumowania stanowisk", extra={'error': str(e)})
        return {
            'cutting': {'name': 'Wycinanie', 'count': 0, 'volume_m3': 0.0, 'avg_priority_rank': 999, 'status_class': 'station-empty'},
            'assembly': {'name': 'Skladanie', 'count': 0, 'volume_m3': 0.0, 'avg_priority_rank': 999, 'status_class': 'station-empty'},
            'packaging': {'name': 'Pakowanie', 'count': 0, 'volume_m3': 0.0, 'avg_priority_rank': 999, 'status_class': 'station-empty'}
        }


# Mapowanie kodu stanowiska na status w bazie i etykiete
MONITOR_STATION_MAP = {
    'cutting': {
        'status': 'czeka_na_wyciecie',
        'quantity_col': 'quantity_done_cutting',
        'label': 'Wycinanie',
        'css_class': 'status-cutting',
    },
    'assembly': {
        'status': 'czeka_na_skladanie',
        'quantity_col': 'quantity_done_assembly',
        'label': 'Skladanie',
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
        'label': 'Wykonczanie',
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
    from ...models import ProductionItem

    station_info = MONITOR_STATION_MAP[station_code]
    target_status = station_info['status']
    quantity_col = station_info['quantity_col']

    # Pobierz unikalne zamowienia na tym stanowisku
    items_on_station = ProductionItem.query.filter(
        ProductionItem.current_status == target_status,
        ProductionItem.internal_order_number.isnot(None)
    ).all()

    # Grupuj po zamowieniu
    orders_map = {}
    for item in items_on_station:
        key = item.internal_order_number
        if key not in orders_map:
            orders_map[key] = {
                'order_number': key,
                'baselinker_order_id': item.baselinker_order_id,
                'client_order_number': item.client_order_number,
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
        wood_species = first.parsed_wood_species or '—'
        technology = first.parsed_technology or '—'
        wood_class = first.parsed_wood_class or '—'

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
        key = f"{item.parsed_wood_species or '—'}|{item.parsed_technology or '—'}"
        if key not in species_map:
            species_map[key] = {'species': item.parsed_wood_species or '—', 'technology': item.parsed_technology or '—', 'count': 0, 'volume': 0.0}
        species_map[key]['count'] += item.quantity
        species_map[key]['volume'] += float(item.volume_m3 or 0) * item.quantity

    species_stats = sorted(species_map.values(), key=lambda x: -x['count'])

    return orders, monitor_stats, species_stats


def _ajax_get_orders_simple(station_code: str, status_filter: str, quantity_done_field: str):
    """
    Generyczna funkcja AJAX dla stanowisk z prosta logika (gluing, formatting, finishing).

    Stanowiska z unikalnymi wymaganiami (packaging, cutting, assembly) maja osobne implementacje.

    Args:
        station_code: Kod stanowiska (gluing, formatting, finishing)
        status_filter: Status produktow do filtrowania (np. 'czeka_na_sklejanie')
        quantity_done_field: Nazwa atrybutu quantity_done_* (np. 'quantity_done_gluing')

    Returns:
        Flask Response z JSON
    """
    try:
        from ...models import ProductionItem
        from sqlalchemy import asc

        sort_by = request.args.get('sort', 'priority')

        # KROK 1: Znajdz zamowienia ktore maja choc 1 produkt do przetworzenia
        orders_with_products = db.session.query(
            ProductionItem.internal_order_number
        ).filter(
            ProductionItem.current_status == status_filter
        ).distinct().all()

        order_numbers = [order[0] for order in orders_with_products]

        if not order_numbers:
            return jsonify({
                'success': True,
                'data': {
                    'orders': [],
                    'stats': {
                        'total_orders': 0,
                        'total_products': 0,
                        'high_priority_count': 0,
                        'overdue_count': 0,
                        'total_volume': 0
                    }
                }
            }), 200

        # KROK 2: Pobierz WSZYSTKIE produkty z tych zamowien
        query = ProductionItem.query.filter(
            ProductionItem.internal_order_number.in_(order_numbers)
        )

        # Sortowanie
        if sort_by == 'priority':
            query = query.order_by(asc(ProductionItem.priority_rank))
        elif sort_by == 'deadline':
            query = query.order_by(asc(ProductionItem.deadline_date))
        elif sort_by == 'created_at':
            query = query.order_by(asc(ProductionItem.created_at))

        products = query.all()

        # KROK 3: Grupowanie produktow po zamowieniach
        orders_grouped = {}
        today = date.today()

        for product in products:
            order_num = product.internal_order_number

            if order_num not in orders_grouped:
                orders_grouped[order_num] = {
                    'order_number': order_num,
                    'baselinker_order_id': None,
                    'products': [],
                    'total_products': 0,
                    'total_volume': 0,
                    'best_priority_rank': 999,
                    'worst_deadline': None
                }

            # Pobierz quantity_done dla tego stanowiska
            quantity_done = getattr(product, quantity_done_field, 0) or 0

            # Dodaj produkt do zamowienia
            product_data = {
                'id': product.short_product_id,
                'short_product_id': product.short_product_id,
                'product_sequence_in_order': product.product_sequence_in_order,
                'original_name': product.original_product_name or 'Brak nazwy',
                'dimensions': None,
                'volume_m3': float(product.volume_m3 or 0),
                'wood_species': product.parsed_wood_species,
                'technology': product.parsed_technology,
                'wood_class': product.parsed_wood_class,
                'finish_state': product.parsed_finish_state,
                'current_status': product.current_status,
                'priority_rank': product.priority_rank or 999,
                'deadline_date': product.deadline_date.isoformat() if product.deadline_date else None,
                'attachment_file_name': product.attachment_file_name,
                'attachment_file_url': product.attachment_file_url,
                'quantity': product.quantity,
                'quantity_done': quantity_done,
                'is_complete': quantity_done == product.quantity,
                'is_priority': product.is_priority
            }

            # Oblicz wymiary z parsowanych pol
            if product.parsed_length_cm and product.parsed_width_cm and product.parsed_thickness_cm:
                product_data['dimensions'] = f"{_format_dimension(product.parsed_length_cm)} × {_format_dimension(product.parsed_width_cm)} × {_format_dimension(product.parsed_thickness_cm)} cm"

            orders_grouped[order_num]['products'].append(product_data)
            orders_grouped[order_num]['total_products'] += 1
            orders_grouped[order_num]['total_volume'] += float(product.volume_m3 or 0)

            if not orders_grouped[order_num]['baselinker_order_id'] and product.baselinker_order_id:
                orders_grouped[order_num]['baselinker_order_id'] = product.baselinker_order_id

            if product.priority_rank and product.priority_rank < orders_grouped[order_num]['best_priority_rank']:
                orders_grouped[order_num]['best_priority_rank'] = product.priority_rank

            if product.deadline_date:
                if orders_grouped[order_num]['worst_deadline'] is None:
                    orders_grouped[order_num]['worst_deadline'] = product.deadline_date
                elif product.deadline_date > orders_grouped[order_num]['worst_deadline']:
                    orders_grouped[order_num]['worst_deadline'] = product.deadline_date

        # KROK 4: Sortuj produkty wewnatrz kazdego zamowienia
        for order_num, order_data in orders_grouped.items():
            order_data['products'].sort(key=lambda p: p['product_sequence_in_order'])

        # KROK 5: Dodaj informacje wyswietlania
        for order_num, order_data in orders_grouped.items():
            rank = order_data['best_priority_rank']
            if rank <= 10:
                order_data['priority_class'] = 'priority-critical'
                order_data['priority_label'] = 'KRYTYCZNY'
            elif rank <= 50:
                order_data['priority_class'] = 'priority-high'
                order_data['priority_label'] = 'WYSOKI'
            elif rank <= 100:
                order_data['priority_class'] = 'priority-normal'
                order_data['priority_label'] = 'NORMALNY'
            else:
                order_data['priority_class'] = 'priority-low'
                order_data['priority_label'] = 'NISKI'

            deadline = order_data['worst_deadline']
            if deadline:
                days_diff = (deadline - today).days
                if days_diff < 0:
                    order_data['display_deadline'] = f"Opoznione o {abs(days_diff)} dni"
                elif days_diff == 0:
                    order_data['display_deadline'] = "Dzis!"
                elif days_diff == 1:
                    order_data['display_deadline'] = "Jutro"
                else:
                    order_data['display_deadline'] = f"Za {days_diff} dni"
            else:
                order_data['display_deadline'] = "Brak terminu"

            if order_data['worst_deadline']:
                order_data['deadline_date'] = order_data['worst_deadline'].isoformat()
                order_data['worst_deadline'] = order_data['worst_deadline'].isoformat()

        # KROK 6: Sortowanie zamowien
        orders_list = list(orders_grouped.values())
        if sort_by == 'priority':
            orders_list.sort(key=lambda x: x['best_priority_rank'])
        elif sort_by == 'deadline':
            orders_list.sort(key=lambda x: x['worst_deadline'] or '9999-12-31')

        # KROK 7: Statystyki
        high_priority_count = sum(1 for order in orders_list if order['best_priority_rank'] <= 50)
        overdue_count = sum(1 for order in orders_list
                           if order['worst_deadline'] and order['worst_deadline'] < today.isoformat())
        total_volume = sum(order['total_volume'] for order in orders_list)
        total_products = sum(order['total_products'] for order in orders_list)

        stats = {
            'total_orders': len(orders_list),
            'total_products': total_products,
            'high_priority_count': high_priority_count,
            'overdue_count': overdue_count,
            'total_volume': round(total_volume, 4)
        }

        return jsonify({
            'success': True,
            'data': {
                'orders': orders_list,
                'stats': stats
            }
        }), 200

    except Exception as e:
        logger.error(f"Blad AJAX orders {station_code}", extra={
            'error': str(e),
            'traceback': traceback.format_exc()
        })

        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


# ============================================================================
# ROUTES IN __init__.py
# ============================================================================

@station_bp.route('/config')
def get_station_frontend_config():
    """
    Endpoint dla konfiguracji JavaScript frontend

    Returns:
        JSON: Konfiguracja dla interfejsow stanowisk
    """
    try:
        config = get_station_config()

        # Dodaj dodatkowe informacje dla frontend
        frontend_config = {
            **config,
            'api_base_url': '/production/api',
            'ajax_base_url': '/production/ajax',
            'station_urls': {
                'cutting': url_for('production_stations.cutting_station'),
                'assembly': url_for('production_stations.assembly_station'),
                'packaging': url_for('production_stations.packaging_station'),
                'select': url_for('production_stations.station_select')
            },
            'timestamp': datetime.utcnow().isoformat()
        }

        return jsonify({
            'success': True,
            'config': frontend_config
        }), 200

    except Exception as e:
        logger.error("Blad pobierania konfiguracji frontend", extra={'error': str(e)})

        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@station_bp.route('/complete-order', methods=['POST'])
def complete_order_bulk():
    """
    POST /production/stations/complete-order

    Bulk completion endpoint dla order-based stations (cutting/assembly)

    Ukonca WSZYSTKIE produkty z danego zamowienia naraz (transakcyjnie).

    Request body:
    {
        "order_number": "25/123",
        "product_ids": ["25_00123_1", "25_00123_2", ...],
        "station": "cutting",
        "action": "complete"
    }

    Returns:
        JSON: {
            success: bool,
            data: {
                completed_count: int,
                order_number: str,
                next_status: str
            }
        }
    """
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'Brak danych JSON'}), 400

        order_number = data.get('order_number')
        product_ids = data.get('product_ids', [])
        station = data.get('station')
        action = data.get('action')

        # Walidacja inputow
        if not order_number or not product_ids or not station or not action:
            return jsonify({
                'success': False,
                'error': 'Wymagane pola: order_number, product_ids, station, action'
            }), 400

        if station not in ['cutting', 'assembly', 'gluing', 'formatting', 'finishing', 'packaging']:
            return jsonify({
                'success': False,
                'error': f'Nieprawidlowe stanowisko: {station}. Dozwolone: cutting, assembly, gluing, formatting, finishing, packaging'
            }), 400

        if action != 'complete':
            return jsonify({
                'success': False,
                'error': 'Tylko action="complete" jest wspierany'
            }), 400

        if not isinstance(product_ids, list) or len(product_ids) == 0:
            return jsonify({
                'success': False,
                'error': 'product_ids musi byc niepusta lista'
            }), 400

        from ...models import ProductionItem

        # KROK 1: Pobierz wszystkie produkty
        products = ProductionItem.query.filter(
            ProductionItem.short_product_id.in_(product_ids)
        ).all()

        if len(products) != len(product_ids):
            found_ids = [p.short_product_id for p in products]
            missing_ids = list(set(product_ids) - set(found_ids))
            return jsonify({
                'success': False,
                'error': f'Nie znaleziono produktow: {missing_ids}'
            }), 404

        # KROK 2: Walidacja ze wszystkie produkty naleza do tego samego zamowienia
        for product in products:
            if product.internal_order_number != order_number:
                return jsonify({
                    'success': False,
                    'error': f'Produkt {product.short_product_id} nie nalezy do zamowienia {order_number}'
                }), 400

        # KROK 3: Walidacja statusow
        expected_status_map = {
            'cutting': ['czeka_na_wyciecie', 'czeka_na_skladanie'],
            'assembly': ['czeka_na_wyciecie', 'czeka_na_skladanie'],
            'gluing': ['czeka_na_sklejanie'],
            'formatting': ['czeka_na_formatowanie'],
            'finishing': ['czeka_na_wykanczanie'],
            'packaging': ['czeka_na_pakowanie']
        }
        expected_statuses = expected_status_map[station]

        invalid_products = []
        for product in products:
            is_valid = False

            if station == 'cutting':
                if product.current_status == 'czeka_na_wyciecie':
                    is_valid = True
                elif product.current_status == 'czeka_na_skladanie' and product.cutting_completed_at is None:
                    is_valid = True
            elif station == 'assembly':
                if product.current_status in expected_statuses:
                    is_valid = True
            else:
                if product.current_status in expected_statuses:
                    is_valid = True

            if not is_valid:
                invalid_products.append({
                    'id': product.short_product_id,
                    'current_status': product.current_status,
                    'expected_statuses': expected_statuses
                })

        if invalid_products:
            return jsonify({
                'success': False,
                'error': 'Niektore produkty maja nieprawidlowy status',
                'invalid_products': invalid_products
            }), 400

        # KROK 4: Transakcyjne ukonczenie wszystkich produktow
        completed_count = 0
        next_status = None

        try:
            for product in products:
                old_status = product.current_status
                product.complete_task(station)
                next_status = product.current_status
                completed_count += 1

            # Commit transakcji
            db.session.commit()

            return jsonify({
                'success': True,
                'message': f'Ukonczono {completed_count} produktow z zamowienia {order_number}',
                'data': {
                    'completed_count': completed_count,
                    'order_number': order_number,
                    'next_status': next_status,
                    'product_ids': product_ids
                }
            }), 200

        except Exception as commit_error:
            db.session.rollback()
            logger.error("BULK: Blad podczas commit", extra={
                'order_number': order_number,
                'completed_before_error': completed_count,
                'error': str(commit_error),
                'traceback': traceback.format_exc()
            })
            raise commit_error

    except Exception as e:
        db.session.rollback()
        logger.error("BULK: Blad bulk completion", extra={
            'order_number': data.get('order_number') if 'data' in locals() else None,
            'station': data.get('station') if 'data' in locals() else None,
            'client_ip': request.remote_addr,
            'error': str(e),
            'traceback': traceback.format_exc()
        })

        return jsonify({
            'success': False,
            'error': f'Blad bulk completion: {str(e)}'
        }), 500


# ============================================================================
# IMPORT SUB-MODULES (must be at the end to avoid circular imports)
# ============================================================================
from . import interfaces  # noqa: E402, F401
from . import monitors    # noqa: E402, F401
from . import ajax        # noqa: E402, F401
from . import shipping    # noqa: E402, F401
