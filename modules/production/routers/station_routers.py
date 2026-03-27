# modules/production/routers/station_routers.py
"""
Station Routers dla modułu Production
=====================================

Interfejsy stanowisk produkcyjnych zoptymalizowane pod tablety:
- Wybór stanowiska (station-select)
- Stanowisko wycinania (cutting)
- Stanowisko składania (assembly) 
- Stanowisko pakowania (packaging)

Wszystkie interfejsy są:
- Zabezpieczone IP whitelist (bez logowania)
- Zoptymalizowane pod ekrany dotykowe
- Auto-refresh co 30 sekund
- Responsive design dla tabletów

Autor: Konrad Kmiecik
Wersja: 1.3 (Poprawki pod nowy model priority_rank)
Data: 2025-01-29
"""

from flask import Blueprint, render_template, request, redirect, url_for, jsonify, flash
from datetime import datetime, date, timedelta
from modules.logging import get_structured_logger
from extensions import db
from modules.production.services.station_heartbeat import record_heartbeat
import traceback

# Utworzenie Blueprint dla interfejsów stanowisk
station_bp = Blueprint('production_stations', __name__)
logger = get_structured_logger('production.stations')

@station_bp.before_request
def apply_station_security():
    """Sprawdza IP tylko dla interfejsów stanowisk"""
    from .. import apply_security
    return apply_security()

# ============================================================================
# HELPERS I UTILITIES
# ============================================================================

def get_station_config():
    """
    Pobiera konfigurację dla interfejsów stanowisk
    
    Returns:
        Dict[str, Any]: Konfiguracja interfejsów
    """
    try:
        from ..services.config_service import get_config
        
        config = {
            'refresh_interval': get_config('REFRESH_INTERVAL_SECONDS', 30),
            'auto_refresh_enabled': get_config('STATION_AUTO_REFRESH_ENABLED', True),
            'debug_frontend': get_config('DEBUG_PRODUCTION_FRONTEND', False),
            'show_detailed_info': get_config('STATION_SHOW_DETAILED_INFO', True),
            'max_products_display': get_config('STATION_MAX_PRODUCTS_DISPLAY', 50)
        }
        
        return config
        
    except Exception as e:
        logger.error("Błąd pobierania konfiguracji stanowisk", extra={'error': str(e)})
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
        limit (int): Limit produktów
        sort_by (str): Sposób sortowania (priority|deadline|created_at)
        
    Returns:
        List[Dict]: Lista produktów z dodatkowymi informacjami
    """
    try:
        from ..models import ProductionItem
        from sqlalchemy import asc, desc
        
        # Mapowanie statusów na stanowiska
        status_map = {
            'cutting': 'czeka_na_wyciecie',
            'assembly': 'czeka_na_skladanie',
            'packaging': 'czeka_na_pakowanie'
        }
        
        if station_code not in status_map:
            logger.warning("Nieprawidłowy kod stanowiska", extra={'station_code': station_code})
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
            
            # Obliczenie koloru priorytetu NA PODSTAWIE RANGI (niższy rank = wyższy priorytet)
            if priority_rank <= 10:
                priority_color = 'critical'
                priority_class = 'priority-critical'
                priority_label = 'Najwyższy'
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
            
            # Formatowanie wymiarów w CM
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

                # Załączniki
                'attachment_file_name': product.attachment_file_name,
                'attachment_file_url': product.attachment_file_url,

                # Ilość - nowy system quantity (2025-11)
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

        logger.debug("Pobrano produkty dla stanowiska", extra={
            'station_code': station_code,
            'products_count': len(products_data),
            'sort_by': sort_by
        })
        
        return products_data
        
    except Exception as e:
        logger.error("Błąd pobierania produktów dla stanowiska", extra={
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
    Formatuje nazwę produktu do wyświetlenia

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
        # Fallback do oryginalnej nazwy (skróconej)
        original = product.original_product_name or "Brak nazwy"
        if len(original) > 60:
            return original[:57] + "..."
        return original

def _format_deadline_display(product):
    """
    Formatuje deadline do wyświetlenia
    
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
            return f"Opóźnione o {abs(days_diff)} dni"
        elif days_diff == 0:
            return "Dziś!"
        elif days_diff == 1:
            return "Jutro"
        elif days_diff <= 7:
            return f"Za {days_diff} dni"
        else:
            return product.deadline_date.strftime("%d.%m.%Y")
    except Exception as e:
        logger.warning("Błąd formatowania deadline", extra={'error': str(e)})
        return "Błąd daty"

def get_station_summary():
    """
    Pobiera podsumowanie wszystkich stanowisk dla wyboru stanowiska
    
    Returns:
        Dict[str, Dict]: Podsumowanie per stanowisko
    """
    try:
        from ..models import ProductionItem
        from sqlalchemy import func
        
        # Query dla wszystkich statusów jednocześnie - POPRAWKA: priority_rank zamiast priority_score
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
            'assembly': 'Składanie',
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
        
        # Wypełnienie danymi
        for status, count, volume, avg_rank in summary_data:
            station_code = status_to_station.get(status)
            if station_code:
                summary[station_code].update({
                    'count': count,
                    'volume_m3': float(volume or 0),
                    'avg_priority_rank': round(float(avg_rank or 999), 1)
                })
                
                # Określenie klasy CSS na podstawie liczby zadań
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
        logger.error("Błąd pobierania podsumowania stanowisk", extra={'error': str(e)})
        return {
            'cutting': {'name': 'Wycinanie', 'count': 0, 'volume_m3': 0.0, 'avg_priority_rank': 999, 'status_class': 'station-empty'},
            'assembly': {'name': 'Składanie', 'count': 0, 'volume_m3': 0.0, 'avg_priority_rank': 999, 'status_class': 'station-empty'},
            'packaging': {'name': 'Pakowanie', 'count': 0, 'volume_m3': 0.0, 'avg_priority_rank': 999, 'status_class': 'station-empty'}
        }

# ============================================================================
# ROUTERS - WYBÓR STANOWISKA
# ============================================================================

@station_bp.route('/')
@station_bp.route('/station-select')
def station_select():
    """
    Interfejs wyboru stanowiska (strona główna dla stanowisk)
    
    Returns:
        HTML: Interfejs wyboru stanowiska
    """
    try:
        logger.info("Dostęp do wyboru stanowiska", extra={
            'client_ip': request.remote_addr,
            'user_agent': request.headers.get('User-Agent', 'Unknown')
        })
        
        # Pobranie podsumowania stanowisk
        stations_summary = get_station_summary()
        
        # Konfiguracja interfejsu
        config = get_station_config()
        
        # Czas ostatniej aktualizacji
        last_updated = datetime.utcnow()
        
        return render_template(
            'stations/select.html',
            stations=stations_summary,
            config=config,
            last_updated=last_updated,
            page_title="Wybór stanowiska produkcyjnego"
        )
        
    except Exception as e:
        logger.error("Błąd interfejsu wyboru stanowiska", extra={
            'client_ip': request.remote_addr,
            'error': str(e)
        })
        
        # Fallback template z błędem
        return render_template(
            'stations/access_denied.html',
            error_message="Błąd ładowania interfejsu wyboru stanowiska",
            error_details=str(e),
            back_url=None
        ), 500

# ============================================================================
# ROUTERS - MONITORING ZLECEŃ
# ============================================================================

@station_bp.route('/monitors')
@station_bp.route('/monitors/')
def monitors_select():
    """Wybór stanowiska do monitoringu zleceń na TV"""
    try:
        logger.info("Dostęp do wyboru monitoringu", extra={
            'client_ip': request.remote_addr
        })
        return render_template('stations/monitors_select.html')
    except Exception as e:
        logger.error("Błąd wyboru monitoringu", extra={
            'error': str(e)
        })
        return render_template(
            'stations/access_denied.html',
            error_message="Błąd ładowania wyboru monitoringu",
            error_details=str(e),
            back_url=None
        ), 500


# Mapowanie kodu stanowiska na status w bazie i etykietę
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
        'label': 'Składanie',
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
    Pobiera zamówienia i statystyki dla danego stanowiska monitora.
    Filtruje prod_items po current_status odpowiadającym stanowisku.
    Returns: (orders, monitor_stats, species_stats)
    """
    from ..models import ProductionItem

    station_info = MONITOR_STATION_MAP[station_code]
    target_status = station_info['status']
    quantity_col = station_info['quantity_col']

    # Pobierz unikalne zamówienia na tym stanowisku
    items_on_station = ProductionItem.query.filter(
        ProductionItem.current_status == target_status,
        ProductionItem.internal_order_number.isnot(None)
    ).all()

    # Grupuj po zamówieniu
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
        total_volume = sum((i.volume_m3 or 0) * i.quantity for i in items)

        # Pobierz gatunek/technologię/klasę z pierwszego itemu
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

    # Sortuj: najpierw z najwyższym postępem
    orders.sort(key=lambda x: (
        -x['completed_products'] / max(x['total_products'], 1),
        x['order_number']
    ))

    # Stats ogólne
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
        species_map[key]['volume'] += (item.volume_m3 or 0) * item.quantity

    species_stats = sorted(species_map.values(), key=lambda x: -x['count'])

    return orders, monitor_stats, species_stats


@station_bp.route('/monitors/<station_code>')
def monitor_station(station_code):
    """Monitor zleceń dla konkretnego stanowiska (widok TV)"""
    try:
        if station_code not in MONITOR_STATION_MAP:
            return render_template(
                'stations/access_denied.html',
                error_message=f"Nieznane stanowisko: {station_code}",
                error_details="Dostępne: cutting, assembly, gluing, formatting, finishing, packaging",
                back_url=url_for('production.production_stations.monitors_select')
            ), 404

        station_info = MONITOR_STATION_MAP[station_code]
        orders, monitor_stats, species_stats = _get_monitor_station_data(station_code)
        config = get_station_config()
        now = datetime.utcnow()

        return render_template(
            'stations/monitor_station.html',
            orders=orders,
            monitor_stats=monitor_stats,
            species_stats=species_stats,
            station_code=station_code,
            station_label=station_info['label'],
            station_css_class=station_info['css_class'],
            config=config,
            now=now,
            page_title=f"Monitor — {station_info['label']}"
        )

    except Exception as e:
        logger.error("Błąd monitora stanowiska", extra={
            'station': station_code,
            'error': str(e),
            'traceback': traceback.format_exc()
        })
        return render_template(
            'stations/error.html',
            error_message=f"Błąd monitora stanowiska {station_code}",
            error_details=str(e),
            back_url=url_for('production.production_stations.monitors_select')
        ), 500


@station_bp.route('/ajax/monitors/<station_code>')
def ajax_monitor_station_data(station_code):
    """AJAX endpoint dla monitora stanowiska — zwraca JSON z zamówieniami i stats"""
    try:
        if station_code not in MONITOR_STATION_MAP:
            return jsonify({'success': False, 'error': f'Unknown station: {station_code}'}), 404

        orders, monitor_stats, species_stats = _get_monitor_station_data(station_code)

        return jsonify({
            'success': True,
            'orders': orders,
            'stats': monitor_stats,
            'species_stats': species_stats,
            'last_updated': datetime.utcnow().isoformat()
        })

    except Exception as e:
        logger.error("Błąd AJAX monitor stanowiska", extra={
            'station': station_code,
            'error': str(e),
            'traceback': traceback.format_exc()
        })
        return jsonify({'success': False, 'error': str(e)}), 500


# ============================================================================
# ROUTERS - STANOWISKO WYCINANIA (CUTTING)
# ============================================================================

@station_bp.route('/cutting')
def cutting_station():
    """
    Interfejs stanowiska wycinania - ORDER-BASED VERSION

    Pokazuje CAŁE zamówienia (grouped by internal_order_number)

    Query params:
        sort: priority|deadline|created_at (default: priority)

    Returns:
        HTML: Interfejs stanowiska wycinania z pogrupowanymi zamówieniami
    """
    try:
        from ..models import ProductionItem
        from sqlalchemy import asc, desc

        sort_by = request.args.get('sort', 'priority')

        logger.info("Dostęp do stanowiska wycinania", extra={
            'client_ip': request.remote_addr,
            'sort_by': sort_by
        })

        # NOWA LOGIKA: Znajdź zamówienia które mają choć 1 produkt do wycięcia
        # Wycinanie widzi: czeka_na_wyciecie ORAZ czeka_na_skladanie (gdzie cutting_completed_at IS NULL)
        orders_with_cutting = db.session.query(
            ProductionItem.internal_order_number
        ).filter(
            db.or_(
                ProductionItem.current_status == 'czeka_na_wyciecie',
                db.and_(
                    ProductionItem.current_status == 'czeka_na_skladanie',
                    ProductionItem.cutting_completed_at.is_(None)
                )
            )
        ).distinct().all()

        order_numbers = [order[0] for order in orders_with_cutting if order[0]]

        if not order_numbers:
            products = []
        else:
            # Pobierz produkty z tych zamówień które pasują do kryteriów wycinania
            # (czeka_na_wyciecie LUB czeka_na_skladanie z cutting_completed_at IS NULL)
            query = ProductionItem.query.filter(
                ProductionItem.internal_order_number.in_(order_numbers),
                db.or_(
                    ProductionItem.current_status == 'czeka_na_wyciecie',
                    db.and_(
                        ProductionItem.current_status == 'czeka_na_skladanie',
                        ProductionItem.cutting_completed_at.is_(None)
                    )
                )
            )

            # Sortowanie
            if sort_by == 'priority':
                query = query.order_by(asc(ProductionItem.priority_rank))
            elif sort_by == 'deadline':
                query = query.order_by(asc(ProductionItem.deadline_date))
            else:
                query = query.order_by(asc(ProductionItem.created_at))

            products_db = query.all()

            # Przygotuj dane produktów
            products = []
            today = date.today()

            for product in products_db:
                priority_rank = product.priority_rank if product.priority_rank else 999

                # Wymiary w CM
                dimensions_parts = []
                if product.parsed_length_cm:
                    dimensions_parts.append(_format_dimension(product.parsed_length_cm))
                if product.parsed_width_cm:
                    dimensions_parts.append(_format_dimension(product.parsed_width_cm))
                if product.parsed_thickness_cm:
                    dimensions_parts.append(_format_dimension(product.parsed_thickness_cm))
                dimensions_text = '×'.join(dimensions_parts) + ' cm' if dimensions_parts else None

                volume_m3 = float(product.volume_m3) if product.volume_m3 else 0.0

                product_data = {
                    'id': product.short_product_id,
                    'internal_order': product.internal_order_number,
                    'baselinker_order_id': product.baselinker_order_id,
                    'original_name': product.original_product_name,
                    'current_status': product.current_status,
                    'priority_rank': priority_rank,
                    'deadline_date': product.deadline_date,
                    'volume_m3': volume_m3,
                    'wood_species': product.parsed_wood_species,
                    'technology': product.parsed_technology,
                    'wood_class': product.parsed_wood_class,
                    'finish_state': product.parsed_finish_state,
                    'dimensions': dimensions_text,
                    'attachment_file_name': product.attachment_file_name,
                    'attachment_file_url': product.attachment_file_url,
                    'product_sequence_in_order': product.product_sequence_in_order,
                    'quantity': product.quantity,
                    'quantity_done': product.quantity_done_cutting,
                    'quantity_done_assembly': product.quantity_done_assembly,
                    'assembly_completed_at': product.assembly_completed_at,
                    'is_complete': product.quantity_done_cutting == product.quantity,
                    'is_priority': product.is_priority,
                    'order_notes': product.order_notes,
                    'client_order_number': product.client_order_number
                }

                products.append(product_data)

        # Grupowanie produktów po zamówieniach
        orders_grouped = {}
        for product in products:
            order_number = product['internal_order']
            if order_number not in orders_grouped:
                orders_grouped[order_number] = {
                    'order_number': order_number,
                    'baselinker_order_id': product.get('baselinker_order_id'),
                    'client_order_number': product.get('client_order_number'),
                    'products': [],
                    'total_products': 0,
                    'total_quantity': 0,
                    'total_quantity_done': 0,
                    'total_volume': 0,
                    'best_priority_rank': 999,
                    'worst_deadline': None
                }

            order = orders_grouped[order_number]
            order['products'].append(product)
            order['total_products'] += 1
            order['total_quantity'] += product.get('quantity', 1) or 1
            order['total_quantity_done'] += product.get('quantity_done', 0) or 0
            order['total_volume'] += product['volume_m3'] or 0

            # Najlepszy priorytet z zamówienia
            if product['priority_rank'] < order['best_priority_rank']:
                order['best_priority_rank'] = product['priority_rank']

            # Najgorszy deadline (najpóźniejszy)
            if product['deadline_date']:
                if order['worst_deadline'] is None or product['deadline_date'] > order['worst_deadline']:
                    order['worst_deadline'] = product['deadline_date']

        # Sortuj produkty wewnątrz zamówienia po product_sequence_in_order
        for order in orders_grouped.values():
            order['products'].sort(key=lambda p: p['product_sequence_in_order'])

        # Dodaj display_deadline do każdego zamówienia
        today = date.today()
        for order in orders_grouped.values():
            if order['worst_deadline']:
                days_diff = (order['worst_deadline'] - today).days
                if days_diff < 0:
                    order['display_deadline'] = f"Opóźnione o {abs(days_diff)} dni"
                elif days_diff == 0:
                    order['display_deadline'] = "Dziś!"
                elif days_diff == 1:
                    order['display_deadline'] = "Jutro"
                else:
                    order['display_deadline'] = f"Za {days_diff} dni"
            else:
                order['display_deadline'] = "Brak terminu"

        # Sortowanie zamówień
        if sort_by == 'priority':
            orders_list = sorted(orders_grouped.values(), key=lambda x: x['best_priority_rank'])
        elif sort_by == 'deadline':
            orders_list = sorted(orders_grouped.values(), key=lambda x: x['worst_deadline'] or date(9999, 12, 31))
        else:
            orders_list = list(orders_grouped.values())

        # Konfiguracja interfejsu
        config = get_station_config()

        # Statystyki stanowiska - liczba sztuk (total_quantity), nie pozycji
        total_products = sum(order['total_quantity'] for order in orders_list)
        high_priority_count = sum(1 for order in orders_list if order['best_priority_rank'] <= 50)

        station_stats = {
            'total_products': total_products,
            'total_orders': len(orders_list),
            'high_priority_count': high_priority_count
        }

        now = datetime.utcnow()

        return render_template(
            'stations/cutting.html',
            orders_grouped=orders_list,
            products=products,  # Dla kompatybilności wstecznej
            station_code='cutting',
            station_name='Wycinanie',
            station_stats=station_stats,
            config=config,
            sort_by=sort_by,
            now=now,
            last_updated=datetime.utcnow(),
            page_title="Stanowisko Wycinania"
        )

    except Exception as e:
        logger.error("Błąd interfejsu wycinania", extra={
            'client_ip': request.remote_addr,
            'error': str(e)
        })

        return render_template(
            'stations/error.html',
            error_message="Błąd ładowania stanowiska wycinania",
            error_details=str(e),
            back_url=url_for('production.production_stations.station_select')
        ), 500

# ============================================================================
# ROUTERS - STANOWISKO SKŁADANIA
# ============================================================================

@station_bp.route('/assembly')
def assembly_station():
    """
    Interfejs stanowiska składania - ORDER-BASED VERSION

    Pokazuje CAŁE zamówienia (grouped by internal_order_number)

    Query params:
        sort: priority|deadline|created_at (default: priority)

    Returns:
        HTML: Interfejs stanowiska składania z pogrupowanymi zamówieniami
    """
    try:
        from ..models import ProductionItem
        from sqlalchemy import asc, desc

        sort_by = request.args.get('sort', 'priority')

        logger.info("Dostęp do stanowiska składania", extra={
            'client_ip': request.remote_addr,
            'sort_by': sort_by
        })

        # NOWA LOGIKA: Znajdź zamówienia które mają choć 1 produkt do składania
        # Składanie widzi: czeka_na_wyciecie ORAZ czeka_na_skladanie (wszystkie)
        orders_with_assembly = db.session.query(
            ProductionItem.internal_order_number
        ).filter(
            db.or_(
                ProductionItem.current_status == 'czeka_na_wyciecie',
                ProductionItem.current_status == 'czeka_na_skladanie'
            )
        ).distinct().all()

        order_numbers = [order[0] for order in orders_with_assembly if order[0]]

        if not order_numbers:
            products = []
        else:
            # Pobierz produkty z tych zamówień które pasują do kryteriów składania
            # (czeka_na_wyciecie LUB czeka_na_skladanie)
            query = ProductionItem.query.filter(
                ProductionItem.internal_order_number.in_(order_numbers),
                db.or_(
                    ProductionItem.current_status == 'czeka_na_wyciecie',
                    ProductionItem.current_status == 'czeka_na_skladanie'
                )
            )

            # Sortowanie
            if sort_by == 'priority':
                query = query.order_by(asc(ProductionItem.priority_rank))
            elif sort_by == 'deadline':
                query = query.order_by(asc(ProductionItem.deadline_date))
            else:
                query = query.order_by(asc(ProductionItem.created_at))

            products_db = query.all()

            # Przygotuj dane produktów
            products = []
            today = date.today()

            for product in products_db:
                priority_rank = product.priority_rank if product.priority_rank else 999

                # Wymiary w CM
                dimensions_parts = []
                if product.parsed_length_cm:
                    dimensions_parts.append(_format_dimension(product.parsed_length_cm))
                if product.parsed_width_cm:
                    dimensions_parts.append(_format_dimension(product.parsed_width_cm))
                if product.parsed_thickness_cm:
                    dimensions_parts.append(_format_dimension(product.parsed_thickness_cm))
                dimensions_text = '×'.join(dimensions_parts) + ' cm' if dimensions_parts else None

                volume_m3 = float(product.volume_m3) if product.volume_m3 else 0.0

                product_data = {
                    'id': product.short_product_id,
                    'internal_order': product.internal_order_number,
                    'baselinker_order_id': product.baselinker_order_id,
                    'original_name': product.original_product_name,
                    'current_status': product.current_status,
                    'priority_rank': priority_rank,
                    'deadline_date': product.deadline_date,
                    'volume_m3': volume_m3,
                    'wood_species': product.parsed_wood_species,
                    'technology': product.parsed_technology,
                    'wood_class': product.parsed_wood_class,
                    'finish_state': product.parsed_finish_state,
                    'dimensions': dimensions_text,
                    'attachment_file_name': product.attachment_file_name,
                    'attachment_file_url': product.attachment_file_url,
                    'product_sequence_in_order': product.product_sequence_in_order,
                    'quantity': product.quantity,
                    'quantity_done': product.quantity_done_assembly,
                    'quantity_done_cutting': product.quantity_done_cutting or 0,
                    'cutting_completed_at': product.cutting_completed_at,
                    'is_complete': product.quantity_done_assembly == product.quantity,
                    'is_priority': product.is_priority,
                    'order_notes': product.order_notes,
                    'client_order_number': product.client_order_number
                }

                products.append(product_data)

        # Grupowanie produktów po zamówieniach
        orders_grouped = {}
        for product in products:
            order_number = product['internal_order']
            if order_number not in orders_grouped:
                orders_grouped[order_number] = {
                    'order_number': order_number,
                    'baselinker_order_id': product.get('baselinker_order_id'),
                    'client_order_number': product.get('client_order_number'),
                    'products': [],
                    'total_products': 0,
                    'total_quantity': 0,
                    'total_quantity_done': 0,
                    'total_volume': 0,
                    'best_priority_rank': 999,
                    'worst_deadline': None
                }

            order = orders_grouped[order_number]
            order['products'].append(product)
            order['total_products'] += 1
            order['total_quantity'] += product.get('quantity', 1) or 1
            order['total_quantity_done'] += product.get('quantity_done', 0) or 0
            order['total_volume'] += product['volume_m3'] or 0

            # Najlepszy priorytet z zamówienia
            if product['priority_rank'] < order['best_priority_rank']:
                order['best_priority_rank'] = product['priority_rank']

            # Najgorszy deadline (najpóźniejszy)
            if product['deadline_date']:
                if order['worst_deadline'] is None or product['deadline_date'] > order['worst_deadline']:
                    order['worst_deadline'] = product['deadline_date']

        # Sortuj produkty wewnątrz zamówienia po product_sequence_in_order
        for order in orders_grouped.values():
            order['products'].sort(key=lambda p: p['product_sequence_in_order'])

        # Dodaj display_deadline do każdego zamówienia
        today = date.today()
        for order in orders_grouped.values():
            if order['worst_deadline']:
                days_diff = (order['worst_deadline'] - today).days
                if days_diff < 0:
                    order['display_deadline'] = f"Opóźnione o {abs(days_diff)} dni"
                elif days_diff == 0:
                    order['display_deadline'] = "Dziś!"
                elif days_diff == 1:
                    order['display_deadline'] = "Jutro"
                else:
                    order['display_deadline'] = f"Za {days_diff} dni"
            else:
                order['display_deadline'] = "Brak terminu"

        # Sortowanie zamówień
        if sort_by == 'priority':
            orders_list = sorted(orders_grouped.values(), key=lambda x: x['best_priority_rank'])
        elif sort_by == 'deadline':
            orders_list = sorted(orders_grouped.values(), key=lambda x: x['worst_deadline'] or date(9999, 12, 31))
        else:
            orders_list = list(orders_grouped.values())

        # Konfiguracja interfejsu
        config = get_station_config()

        # Statystyki stanowiska - liczba sztuk (total_quantity), nie pozycji
        total_products = sum(order['total_quantity'] for order in orders_list)
        high_priority_count = sum(1 for order in orders_list if order['best_priority_rank'] <= 50)

        station_stats = {
            'total_products': total_products,
            'total_orders': len(orders_list),
            'high_priority_count': high_priority_count
        }

        now = datetime.utcnow()

        return render_template(
            'stations/assembly.html',
            orders_grouped=orders_list,
            products=products,  # Dla kompatybilności wstecznej
            station_code='assembly',
            station_name='Składanie',
            station_stats=station_stats,
            config=config,
            sort_by=sort_by,
            now=now,
            last_updated=datetime.utcnow(),
            page_title="Stanowisko Składania"
        )

    except Exception as e:
        logger.error("Błąd interfejsu składania", extra={
            'client_ip': request.remote_addr,
            'error': str(e),
            'traceback': traceback.format_exc()
        })

        return render_template(
            'stations/error.html',
            error_message="Błąd ładowania stanowiska składania",
            error_details=str(e),
            back_url=url_for('production.production_stations.station_select')
        ), 500

# ============================================================================
# ROUTERS - NOWE STANOWISKA (Gluing, Formatting, Finishing)
# ============================================================================

@station_bp.route('/gluing')
def gluing_station():
    """
    Interfejs stanowiska sklejania - ORDER-BASED VERSION
    Pokazuje CAŁE zamówienia (grouped by internal_order_number)

    Query params:
        sort: priority|deadline|created_at (default: priority)

    Returns:
        HTML: Interfejs stanowiska sklejania z pogrupowanymi zamówieniami
    """
    try:
        from ..models import ProductionItem
        from sqlalchemy import asc, desc

        sort_by = request.args.get('sort', 'priority')

        logger.info("Dostęp do stanowiska sklejania", extra={
            'client_ip': request.remote_addr,
            'sort_by': sort_by
        })

        # Znajdź zamówienia które mają choć 1 produkt do sklejania
        orders_with_gluing = db.session.query(
            ProductionItem.internal_order_number
        ).filter(
            ProductionItem.current_status == 'czeka_na_sklejanie'
        ).distinct().all()

        order_numbers = [order[0] for order in orders_with_gluing if order[0]]

        if not order_numbers:
            products = []
        else:
            # Pobierz WSZYSTKIE produkty z tych zamówień
            query = ProductionItem.query.filter(
                ProductionItem.internal_order_number.in_(order_numbers)
            )

            # Sortowanie
            if sort_by == 'priority':
                query = query.order_by(asc(ProductionItem.priority_rank))
            elif sort_by == 'deadline':
                query = query.order_by(asc(ProductionItem.deadline_date))
            else:
                query = query.order_by(asc(ProductionItem.created_at))

            products_db = query.all()

            # Przygotuj dane produktów
            products = []
            today = date.today()

            for product in products_db:
                priority_rank = product.priority_rank if product.priority_rank else 999

                # Wymiary w CM
                dimensions_parts = []
                if product.parsed_length_cm:
                    dimensions_parts.append(_format_dimension(product.parsed_length_cm))
                if product.parsed_width_cm:
                    dimensions_parts.append(_format_dimension(product.parsed_width_cm))
                if product.parsed_thickness_cm:
                    dimensions_parts.append(_format_dimension(product.parsed_thickness_cm))
                dimensions_text = '×'.join(dimensions_parts) + ' cm' if dimensions_parts else None

                volume_m3 = float(product.volume_m3) if product.volume_m3 else 0.0

                product_data = {
                    'id': product.short_product_id,
                    'internal_order': product.internal_order_number,
                    'baselinker_order_id': product.baselinker_order_id,
                    'original_name': product.original_product_name,
                    'current_status': product.current_status,
                    'priority_rank': priority_rank,
                    'deadline_date': product.deadline_date,
                    'volume_m3': volume_m3,
                    'wood_species': product.parsed_wood_species,
                    'technology': product.parsed_technology,
                    'wood_class': product.parsed_wood_class,
                    'finish_state': product.parsed_finish_state,
                    'dimensions': dimensions_text,
                    'attachment_file_name': product.attachment_file_name,
                    'attachment_file_url': product.attachment_file_url,
                    'product_sequence_in_order': product.product_sequence_in_order,
                    'quantity': product.quantity,
                    'quantity_done': product.quantity_done_gluing,
                    'is_complete': product.quantity_done_gluing == product.quantity,
                    'is_priority': product.is_priority,
                    'order_notes': product.order_notes,
                    'client_order_number': product.client_order_number
                }

                products.append(product_data)

        # Grupowanie produktów po zamówieniach
        orders_grouped = {}
        for product in products:
            order_number = product['internal_order']
            if order_number not in orders_grouped:
                orders_grouped[order_number] = {
                    'order_number': order_number,
                    'baselinker_order_id': product.get('baselinker_order_id'),
                    'client_order_number': product.get('client_order_number'),
                    'products': [],
                    'total_products': 0,
                    'total_quantity': 0,
                    'total_quantity_done': 0,
                    'total_volume': 0,
                    'best_priority_rank': 999,
                    'worst_deadline': None
                }

            order = orders_grouped[order_number]
            order['products'].append(product)
            order['total_products'] += 1
            order['total_quantity'] += product.get('quantity', 1) or 1
            order['total_quantity_done'] += product.get('quantity_done', 0) or 0
            order['total_volume'] += product['volume_m3'] or 0

            # Najlepszy priorytet z zamówienia
            if product['priority_rank'] < order['best_priority_rank']:
                order['best_priority_rank'] = product['priority_rank']

            # Najgorszy deadline (najpóźniejszy)
            if product['deadline_date']:
                if order['worst_deadline'] is None or product['deadline_date'] > order['worst_deadline']:
                    order['worst_deadline'] = product['deadline_date']

        # Sortuj produkty wewnątrz zamówienia po product_sequence_in_order
        for order in orders_grouped.values():
            order['products'].sort(key=lambda p: p['product_sequence_in_order'])

        # Dodaj display_deadline do każdego zamówienia
        today = date.today()
        for order in orders_grouped.values():
            if order['worst_deadline']:
                days_diff = (order['worst_deadline'] - today).days
                if days_diff < 0:
                    order['display_deadline'] = f"Opóźnione o {abs(days_diff)} dni"
                elif days_diff == 0:
                    order['display_deadline'] = "Dziś!"
                elif days_diff == 1:
                    order['display_deadline'] = "Jutro"
                else:
                    order['display_deadline'] = f"Za {days_diff} dni"
            else:
                order['display_deadline'] = "Brak terminu"

        # Sortowanie zamówień
        if sort_by == 'priority':
            orders_list = sorted(orders_grouped.values(), key=lambda x: x['best_priority_rank'])
        elif sort_by == 'deadline':
            orders_list = sorted(orders_grouped.values(), key=lambda x: x['worst_deadline'] or date(9999, 12, 31))
        else:
            orders_list = list(orders_grouped.values())

        # Konfiguracja interfejsu
        config = get_station_config()

        # Statystyki stanowiska - liczba sztuk (total_quantity), nie pozycji
        total_products = sum(order['total_quantity'] for order in orders_list)
        high_priority_count = sum(1 for order in orders_list if order['best_priority_rank'] <= 50)

        station_stats = {
            'total_products': total_products,
            'total_orders': len(orders_list),
            'high_priority_count': high_priority_count
        }

        now = datetime.utcnow()

        return render_template(
            'stations/gluing.html',
            orders_grouped=orders_list,
            products=products,
            station_code='gluing',
            station_name='Sklejanie',
            station_stats=station_stats,
            config=config,
            sort_by=sort_by,
            now=now,
            last_updated=datetime.utcnow(),
            page_title="Stanowisko Sklejania"
        )

    except Exception as e:
        logger.error("Błąd interfejsu sklejania", extra={
            'client_ip': request.remote_addr,
            'error': str(e),
            'traceback': traceback.format_exc()
        })

        return render_template(
            'stations/error.html',
            error_message="Błąd ładowania stanowiska sklejania",
            error_details=str(e),
            back_url=url_for('production.production_stations.station_select')
        ), 500


@station_bp.route('/formatting')
def formatting_station():
    """
    Interfejs stanowiska formatowania - ORDER-BASED VERSION
    Pokazuje CAŁE zamówienia (grouped by internal_order_number)

    Query params:
        sort: priority|deadline|created_at (default: priority)

    Returns:
        HTML: Interfejs stanowiska formatowania z pogrupowanymi zamówieniami
    """
    try:
        from ..models import ProductionItem
        from sqlalchemy import asc, desc

        sort_by = request.args.get('sort', 'priority')

        logger.info("Dostęp do stanowiska formatowania", extra={
            'client_ip': request.remote_addr,
            'sort_by': sort_by
        })

        # Znajdź zamówienia które mają choć 1 produkt do formatowania
        orders_with_formatting = db.session.query(
            ProductionItem.internal_order_number
        ).filter(
            ProductionItem.current_status == 'czeka_na_formatowanie'
        ).distinct().all()

        order_numbers = [order[0] for order in orders_with_formatting if order[0]]

        if not order_numbers:
            products = []
        else:
            # Pobierz WSZYSTKIE produkty z tych zamówień
            query = ProductionItem.query.filter(
                ProductionItem.internal_order_number.in_(order_numbers)
            )

            # Sortowanie
            if sort_by == 'priority':
                query = query.order_by(asc(ProductionItem.priority_rank))
            elif sort_by == 'deadline':
                query = query.order_by(asc(ProductionItem.deadline_date))
            else:
                query = query.order_by(asc(ProductionItem.created_at))

            products_db = query.all()

            # Przygotuj dane produktów
            products = []
            today = date.today()

            for product in products_db:
                priority_rank = product.priority_rank if product.priority_rank else 999

                # Wymiary w CM
                dimensions_parts = []
                if product.parsed_length_cm:
                    dimensions_parts.append(_format_dimension(product.parsed_length_cm))
                if product.parsed_width_cm:
                    dimensions_parts.append(_format_dimension(product.parsed_width_cm))
                if product.parsed_thickness_cm:
                    dimensions_parts.append(_format_dimension(product.parsed_thickness_cm))
                dimensions_text = '×'.join(dimensions_parts) + ' cm' if dimensions_parts else None

                volume_m3 = float(product.volume_m3) if product.volume_m3 else 0.0

                product_data = {
                    'id': product.short_product_id,
                    'internal_order': product.internal_order_number,
                    'baselinker_order_id': product.baselinker_order_id,
                    'original_name': product.original_product_name,
                    'current_status': product.current_status,
                    'priority_rank': priority_rank,
                    'deadline_date': product.deadline_date,
                    'volume_m3': volume_m3,
                    'wood_species': product.parsed_wood_species,
                    'technology': product.parsed_technology,
                    'wood_class': product.parsed_wood_class,
                    'finish_state': product.parsed_finish_state,
                    'dimensions': dimensions_text,
                    'attachment_file_name': product.attachment_file_name,
                    'attachment_file_url': product.attachment_file_url,
                    'product_sequence_in_order': product.product_sequence_in_order,
                    'quantity': product.quantity,
                    'quantity_done': product.quantity_done_formatting,
                    'is_complete': product.quantity_done_formatting == product.quantity,
                    'is_priority': product.is_priority,
                    'order_notes': product.order_notes,
                    'client_order_number': product.client_order_number
                }

                products.append(product_data)

        # Grupowanie produktów po zamówieniach
        orders_grouped = {}
        for product in products:
            order_number = product['internal_order']
            if order_number not in orders_grouped:
                orders_grouped[order_number] = {
                    'order_number': order_number,
                    'baselinker_order_id': product.get('baselinker_order_id'),
                    'client_order_number': product.get('client_order_number'),
                    'products': [],
                    'total_products': 0,
                    'total_quantity': 0,
                    'total_quantity_done': 0,
                    'total_volume': 0,
                    'best_priority_rank': 999,
                    'worst_deadline': None
                }

            order = orders_grouped[order_number]
            order['products'].append(product)
            order['total_products'] += 1
            order['total_quantity'] += product.get('quantity', 1) or 1
            order['total_quantity_done'] += product.get('quantity_done', 0) or 0
            order['total_volume'] += product['volume_m3'] or 0

            # Najlepszy priorytet z zamówienia
            if product['priority_rank'] < order['best_priority_rank']:
                order['best_priority_rank'] = product['priority_rank']

            # Najgorszy deadline (najpóźniejszy)
            if product['deadline_date']:
                if order['worst_deadline'] is None or product['deadline_date'] > order['worst_deadline']:
                    order['worst_deadline'] = product['deadline_date']

        # Sortuj produkty wewnątrz zamówienia po product_sequence_in_order
        for order in orders_grouped.values():
            order['products'].sort(key=lambda p: p['product_sequence_in_order'])

        # Dodaj display_deadline do każdego zamówienia
        today = date.today()
        for order in orders_grouped.values():
            if order['worst_deadline']:
                days_diff = (order['worst_deadline'] - today).days
                if days_diff < 0:
                    order['display_deadline'] = f"Opóźnione o {abs(days_diff)} dni"
                elif days_diff == 0:
                    order['display_deadline'] = "Dziś!"
                elif days_diff == 1:
                    order['display_deadline'] = "Jutro"
                else:
                    order['display_deadline'] = f"Za {days_diff} dni"
            else:
                order['display_deadline'] = "Brak terminu"

        # Sortowanie zamówień
        if sort_by == 'priority':
            orders_list = sorted(orders_grouped.values(), key=lambda x: x['best_priority_rank'])
        elif sort_by == 'deadline':
            orders_list = sorted(orders_grouped.values(), key=lambda x: x['worst_deadline'] or date(9999, 12, 31))
        else:
            orders_list = list(orders_grouped.values())

        # Konfiguracja interfejsu
        config = get_station_config()

        # Statystyki stanowiska - liczba sztuk (total_quantity), nie pozycji
        total_products = sum(order['total_quantity'] for order in orders_list)
        high_priority_count = sum(1 for order in orders_list if order['best_priority_rank'] <= 50)

        station_stats = {
            'total_products': total_products,
            'total_orders': len(orders_list),
            'high_priority_count': high_priority_count
        }

        now = datetime.utcnow()

        return render_template(
            'stations/formatting.html',
            orders_grouped=orders_list,
            products=products,
            station_code='formatting',
            station_name='Formatowanie',
            station_stats=station_stats,
            config=config,
            sort_by=sort_by,
            now=now,
            last_updated=datetime.utcnow(),
            page_title="Stanowisko Formatowania"
        )

    except Exception as e:
        logger.error("Błąd interfejsu formatowania", extra={
            'client_ip': request.remote_addr,
            'error': str(e),
            'traceback': traceback.format_exc()
        })

        return render_template(
            'stations/error.html',
            error_message="Błąd ładowania stanowiska formatowania",
            error_details=str(e),
            back_url=url_for('production.production_stations.station_select')
        ), 500


@station_bp.route('/finishing')
def finishing_station():
    """
    Interfejs stanowiska wykańczania - ORDER-BASED VERSION
    Pokazuje CAŁE zamówienia (grouped by internal_order_number)

    Query params:
        sort: priority|deadline|created_at (default: priority)

    Returns:
        HTML: Interfejs stanowiska wykańczania z pogrupowanymi zamówieniami
    """
    try:
        from ..models import ProductionItem
        from sqlalchemy import asc, desc

        sort_by = request.args.get('sort', 'priority')

        logger.info("Dostęp do stanowiska wykańczania", extra={
            'client_ip': request.remote_addr,
            'sort_by': sort_by
        })

        # Znajdź zamówienia które mają choć 1 produkt do wykańczania
        orders_with_finishing = db.session.query(
            ProductionItem.internal_order_number
        ).filter(
            ProductionItem.current_status == 'czeka_na_wykanczanie'
        ).distinct().all()

        order_numbers = [order[0] for order in orders_with_finishing if order[0]]

        if not order_numbers:
            products = []
        else:
            # Pobierz WSZYSTKIE produkty z tych zamówień
            query = ProductionItem.query.filter(
                ProductionItem.internal_order_number.in_(order_numbers)
            )

            # Sortowanie
            if sort_by == 'priority':
                query = query.order_by(asc(ProductionItem.priority_rank))
            elif sort_by == 'deadline':
                query = query.order_by(asc(ProductionItem.deadline_date))
            else:
                query = query.order_by(asc(ProductionItem.created_at))

            products_db = query.all()

            # Przygotuj dane produktów
            products = []
            today = date.today()

            for product in products_db:
                priority_rank = product.priority_rank if product.priority_rank else 999

                # Wymiary w CM
                dimensions_parts = []
                if product.parsed_length_cm:
                    dimensions_parts.append(_format_dimension(product.parsed_length_cm))
                if product.parsed_width_cm:
                    dimensions_parts.append(_format_dimension(product.parsed_width_cm))
                if product.parsed_thickness_cm:
                    dimensions_parts.append(_format_dimension(product.parsed_thickness_cm))
                dimensions_text = '×'.join(dimensions_parts) + ' cm' if dimensions_parts else None

                volume_m3 = float(product.volume_m3) if product.volume_m3 else 0.0

                product_data = {
                    'id': product.short_product_id,
                    'internal_order': product.internal_order_number,
                    'baselinker_order_id': product.baselinker_order_id,
                    'original_name': product.original_product_name,
                    'current_status': product.current_status,
                    'priority_rank': priority_rank,
                    'deadline_date': product.deadline_date,
                    'volume_m3': volume_m3,
                    'wood_species': product.parsed_wood_species,
                    'technology': product.parsed_technology,
                    'wood_class': product.parsed_wood_class,
                    'finish_state': product.parsed_finish_state,
                    'dimensions': dimensions_text,
                    'attachment_file_name': product.attachment_file_name,
                    'attachment_file_url': product.attachment_file_url,
                    'product_sequence_in_order': product.product_sequence_in_order,
                    'quantity': product.quantity,
                    'quantity_done': product.quantity_done_finishing,
                    'is_complete': product.quantity_done_finishing == product.quantity,
                    'is_priority': product.is_priority,
                    'order_notes': product.order_notes,
                    'client_order_number': product.client_order_number
                }

                products.append(product_data)

        # Grupowanie produktów po zamówieniach
        orders_grouped = {}
        for product in products:
            order_number = product['internal_order']
            if order_number not in orders_grouped:
                orders_grouped[order_number] = {
                    'order_number': order_number,
                    'baselinker_order_id': product.get('baselinker_order_id'),
                    'client_order_number': product.get('client_order_number'),
                    'products': [],
                    'total_products': 0,
                    'total_quantity': 0,
                    'total_quantity_done': 0,
                    'total_volume': 0,
                    'best_priority_rank': 999,
                    'worst_deadline': None
                }

            order = orders_grouped[order_number]
            order['products'].append(product)
            order['total_products'] += 1
            order['total_quantity'] += product.get('quantity', 1) or 1
            order['total_quantity_done'] += product.get('quantity_done', 0) or 0
            order['total_volume'] += product['volume_m3'] or 0

            # Najlepszy priorytet z zamówienia
            if product['priority_rank'] < order['best_priority_rank']:
                order['best_priority_rank'] = product['priority_rank']

            # Najgorszy deadline (najpóźniejszy)
            if product['deadline_date']:
                if order['worst_deadline'] is None or product['deadline_date'] > order['worst_deadline']:
                    order['worst_deadline'] = product['deadline_date']

        # Sortuj produkty wewnątrz zamówienia po product_sequence_in_order
        for order in orders_grouped.values():
            order['products'].sort(key=lambda p: p['product_sequence_in_order'])

        # Dodaj display_deadline do każdego zamówienia
        today = date.today()
        for order in orders_grouped.values():
            if order['worst_deadline']:
                days_diff = (order['worst_deadline'] - today).days
                if days_diff < 0:
                    order['display_deadline'] = f"Opóźnione o {abs(days_diff)} dni"
                elif days_diff == 0:
                    order['display_deadline'] = "Dziś!"
                elif days_diff == 1:
                    order['display_deadline'] = "Jutro"
                else:
                    order['display_deadline'] = f"Za {days_diff} dni"
            else:
                order['display_deadline'] = "Brak terminu"

        # Sortowanie zamówień
        if sort_by == 'priority':
            orders_list = sorted(orders_grouped.values(), key=lambda x: x['best_priority_rank'])
        elif sort_by == 'deadline':
            orders_list = sorted(orders_grouped.values(), key=lambda x: x['worst_deadline'] or date(9999, 12, 31))
        else:
            orders_list = list(orders_grouped.values())

        # Konfiguracja interfejsu
        config = get_station_config()

        # Statystyki stanowiska - liczba sztuk (total_quantity), nie pozycji
        total_products = sum(order['total_quantity'] for order in orders_list)
        high_priority_count = sum(1 for order in orders_list if order['best_priority_rank'] <= 50)

        station_stats = {
            'total_products': total_products,
            'total_orders': len(orders_list),
            'high_priority_count': high_priority_count
        }

        now = datetime.utcnow()

        return render_template(
            'stations/finishing.html',
            orders_grouped=orders_list,
            products=products,
            station_code='finishing',
            station_name='Wykańczanie',
            station_stats=station_stats,
            config=config,
            sort_by=sort_by,
            now=now,
            last_updated=datetime.utcnow(),
            page_title="Stanowisko Wykańczania"
        )

    except Exception as e:
        logger.error("Błąd interfejsu wykańczania", extra={
            'client_ip': request.remote_addr,
            'error': str(e),
            'traceback': traceback.format_exc()
        })

        return render_template(
            'stations/error.html',
            error_message="Błąd ładowania stanowiska wykańczania",
            error_details=str(e),
            back_url=url_for('production.production_stations.station_select')
        ), 500


# ============================================================================
# ROUTERS - STANOWISKO PAKOWANIA
# ============================================================================

@station_bp.route('/packaging')
def packaging_station():
    """
    Interfejs stanowiska pakowania
    
    ZMIANA: Pokazuje CAŁE zamówienia jeśli choć 1 produkt jest w statusie czeka_na_pakowanie
    
    Query params:
        sort: priority|deadline|created_at (default: priority)
        view: grid|list (default: list) - pakowanie używa widoku listy

    Returns:
        HTML: Interfejs stanowiska pakowania
    """
    try:
        from ..models import ProductionItem
        from sqlalchemy import asc, desc

        sort_by = request.args.get('sort', 'priority')
        view_mode = request.args.get('view', 'list')

        logger.info("Dostęp do stanowiska pakowania", extra={
            'client_ip': request.remote_addr,
            'sort_by': sort_by,
            'view_mode': view_mode
        })
        
        # NOWA LOGIKA: Znajdź zamówienia które mają choć 1 produkt do pakowania
        orders_with_packaging = db.session.query(
            ProductionItem.internal_order_number
        ).filter(
            ProductionItem.current_status == 'czeka_na_pakowanie'
        ).distinct().all()
        
        order_numbers = [order[0] for order in orders_with_packaging if order[0]]
        
        if not order_numbers:
            products = []
        else:
            # Pobierz WSZYSTKIE produkty z tych zamówień (niezależnie od statusu)
            query = ProductionItem.query.filter(
                ProductionItem.internal_order_number.in_(order_numbers)
            )
            
            # Sortowanie
            if sort_by == 'priority':
                query = query.order_by(asc(ProductionItem.priority_rank))
            elif sort_by == 'deadline':
                query = query.order_by(asc(ProductionItem.deadline_date))
            else:
                query = query.order_by(asc(ProductionItem.created_at))
            
            products_db = query.all()
            
            # Przygotuj dane produktów (używając tej samej logiki co get_products_for_station)
            products = []
            today = date.today()
            
            for product in products_db:
                priority_rank = product.priority_rank if product.priority_rank else 999
                
                # Kolor priorytetu
                if priority_rank <= 10:
                    priority_label = 'Najwyższy'
                    priority_color = '#dc3545'
                    priority_class = 'priority-critical'
                elif priority_rank <= 50:
                    priority_label = 'Wysoki'
                    priority_color = '#fd7e14'
                    priority_class = 'priority-high'
                elif priority_rank <= 100:
                    priority_label = 'Normalny'
                    priority_color = '#ffc107'
                    priority_class = 'priority-normal'
                else:
                    priority_label = 'Niski'
                    priority_color = '#28a745'
                    priority_class = 'priority-low'
                
                # Deadline
                if product.deadline_date:
                    days_diff = (product.deadline_date - today).days
                    if days_diff < 0:
                        display_deadline = f"{abs(days_diff)} dni temu"
                        deadline_color = '#dc3545'
                        deadline_class = 'deadline-overdue'
                    elif days_diff == 0:
                        display_deadline = "Dziś!"
                        deadline_color = '#dc3545'
                        deadline_class = 'deadline-today'
                    elif days_diff == 1:
                        display_deadline = "Jutro"
                        deadline_color = '#fd7e14'
                        deadline_class = 'deadline-tomorrow'
                    elif days_diff <= 7:
                        display_deadline = f"Za {days_diff} dni"
                        deadline_color = '#ffc107'
                        deadline_class = 'deadline-week'
                    else:
                        display_deadline = product.deadline_date.strftime("%d.%m.%Y")
                        deadline_color = '#28a745'
                        deadline_class = 'deadline-normal'
                else:
                    display_deadline = "Brak"
                    deadline_color = '#6c757d'
                    deadline_class = 'deadline-none'
                
                # Wymiary w CM
                dimensions_parts = []
                if product.parsed_length_cm:
                    dimensions_parts.append(_format_dimension(product.parsed_length_cm))
                if product.parsed_width_cm:
                    dimensions_parts.append(_format_dimension(product.parsed_width_cm))
                if product.parsed_thickness_cm:
                    dimensions_parts.append(_format_dimension(product.parsed_thickness_cm))
                dimensions_text = '×'.join(dimensions_parts) + ' cm' if dimensions_parts else 'Brak wymiarów'
                
                volume_m3 = float(product.volume_m3) if product.volume_m3 else 0.0
                total_value = float(product.total_value_net) if product.total_value_net else 0.0
                
                product_data = {
                    'id': product.short_product_id,
                    'internal_order': product.internal_order_number,
                    'baselinker_order_id': product.baselinker_order_id,
                    'original_name': product.original_product_name,
                    'current_status': product.current_status,  # KLUCZOWE!
                    'priority_rank': priority_rank,
                    'priority_label': priority_label,
                    'priority_color': priority_color,
                    'priority_class': priority_class,
                    'deadline_date': product.deadline_date,
                    'days_until_deadline': product.days_until_deadline,
                    'is_overdue': product.is_overdue,
                    'deadline_color': deadline_color,
                    'deadline_class': deadline_class,
                    'volume_m3': volume_m3,
                    'total_value_net': total_value,
                    'created_at': product.created_at,
                    'payment_date': product.payment_date,
                    'wood_species': product.parsed_wood_species,
                    'technology': product.parsed_technology,
                    'wood_class': product.parsed_wood_class,
                    'dimensions': dimensions_text,
                    'finish_state': product.parsed_finish_state,
                    'thickness_group': product.thickness_group,
                    'client_name': product.client_name,
                    'display_deadline': display_deadline,
                    'quantity': product.quantity,
                    'quantity_done': product.quantity_done_packaging,
                    'is_complete': product.quantity_done_packaging == product.quantity,
                    'is_priority': product.is_priority,
                    'order_notes': product.order_notes,
                    'client_order_number': product.client_order_number,
                    # WYMIARY SUROWE DO OBLICZEŃ WYSYŁKI (2025-12)
                    'parsed_length_cm': float(product.parsed_length_cm) if product.parsed_length_cm else 0,
                    'parsed_width_cm': float(product.parsed_width_cm) if product.parsed_width_cm else 0,
                    'parsed_thickness_cm': float(product.parsed_thickness_cm) if product.parsed_thickness_cm else 0,
                    # DANE DOSTAWY (2025-12)
                    'delivery_method': product.delivery_method,
                    'delivery_fullname': product.delivery_fullname,
                    'delivery_company': product.delivery_company,
                    'delivery_address': product.delivery_address,
                    'delivery_city': product.delivery_city,
                    'delivery_postcode': product.delivery_postcode,
                    'delivery_country_code': product.delivery_country_code,
                    'is_personal_pickup': product.is_personal_pickup,
                    'delivery_type': product.delivery_type,
                    # DANE WYSYŁKI KURIERSKIEJ (2025-12)
                    'shipping_package_id': product.shipping_package_id,
                    'shipping_tracking_number': product.shipping_tracking_number,
                    'shipping_courier_name': product.shipping_courier_name,
                    'shipping_price': float(product.shipping_price) if product.shipping_price else None,
                    'shipping_label_base64': product.shipping_label_base64,
                    'shipping_created_at': product.shipping_created_at.isoformat() if product.shipping_created_at else None,
                }

                products.append(product_data)

        # Grupowanie produktów po zamówieniach (PACKAGING)
        orders_grouped = {}
        for product in products:
            order_number = product['internal_order']
            if order_number not in orders_grouped:
                orders_grouped[order_number] = {
                    'order_number': order_number,
                    'baselinker_order_id': product.get('baselinker_order_id'),
                    'client_order_number': product.get('client_order_number'),
                    'products': [],
                    'total_products': 0,
                    'total_quantity': 0,
                    'total_quantity_done': 0,
                    'total_volume': 0,
                    'total_value': 0,
                    'best_priority_rank': 999,
                    'earliest_deadline': None,
                    'has_overdue': False,
                    'priority_label': 'Niski',
                    'priority_class': 'priority-low',
                    'display_deadline': 'Brak',
                    # DANE DOSTAWY (2025-12) - z pierwszego produktu
                    'delivery_method': None,
                    'delivery_fullname': None,
                    'delivery_company': None,
                    'delivery_address': None,
                    'delivery_city': None,
                    'delivery_postcode': None,
                    'delivery_country_code': None,
                    'is_personal_pickup': None,
                    'delivery_type': None,
                    # DANE WYSYŁKI KURIERSKIEJ (2025-12)
                    'shipping_package_id': None,
                    'shipping_tracking_number': None,
                    'shipping_courier_name': None,
                    'shipping_price': None,
                    'shipping_label_base64': None,
                    'shipping_created_at': None,
                }

            order = orders_grouped[order_number]
            order['products'].append(product)
            order['total_products'] += 1
            order['total_quantity'] += product.get('quantity', 1) or 1
            order['total_quantity_done'] += product.get('quantity_done', 0) or 0
            order['total_volume'] += product['volume_m3'] or 0
            order['total_value'] += product['total_value_net'] or 0

            # Najlepszy priorytet z zamówienia
            if product['priority_rank'] < order['best_priority_rank']:
                order['best_priority_rank'] = product['priority_rank']
                order['priority_label'] = product['priority_label']
                order['priority_class'] = product['priority_class']

            # Najwcześniejszy deadline
            if product['deadline_date']:
                if order['earliest_deadline'] is None or product['deadline_date'] < order['earliest_deadline']:
                    order['earliest_deadline'] = product['deadline_date']
                    order['display_deadline'] = product['display_deadline']

            if product['is_overdue']:
                order['has_overdue'] = True

            # Pobierz dane dostawy z pierwszego produktu w zamówieniu (2025-12)
            if order['delivery_method'] is None:
                order['delivery_method'] = product.get('delivery_method')
                order['delivery_fullname'] = product.get('delivery_fullname')
                order['delivery_company'] = product.get('delivery_company')
                order['delivery_address'] = product.get('delivery_address')
                order['delivery_city'] = product.get('delivery_city')
                order['delivery_postcode'] = product.get('delivery_postcode')
                order['delivery_country_code'] = product.get('delivery_country_code')
                order['is_personal_pickup'] = product.get('is_personal_pickup')
                order['delivery_type'] = product.get('delivery_type')

            # Pobierz dane wysyłki z pierwszego produktu który je ma (2025-12)
            if order['shipping_package_id'] is None and product.get('shipping_package_id'):
                order['shipping_package_id'] = product.get('shipping_package_id')
                order['shipping_tracking_number'] = product.get('shipping_tracking_number')
                order['shipping_courier_name'] = product.get('shipping_courier_name')
                order['shipping_price'] = product.get('shipping_price')
                order['shipping_label_base64'] = product.get('shipping_label_base64')
                order['shipping_created_at'] = product.get('shipping_created_at')

        # Sortowanie grup zamówień
        if sort_by == 'priority':
            orders_list = sorted(orders_grouped.values(), key=lambda x: x['best_priority_rank'])
        elif sort_by == 'deadline':
            orders_list = sorted(orders_grouped.values(),
                               key=lambda x: x['earliest_deadline'] or date.max)
        else:
            orders_list = list(orders_grouped.values())

        # Konfiguracja interfejsu
        config = get_station_config()

        # Statystyki stanowiska - liczba sztuk (total_quantity), nie pozycji
        total_products = sum(order['total_quantity'] for order in orders_list)
        total_orders = len(orders_grouped)
        high_priority_count = sum(1 for p in products if p['priority_rank'] <= 50)
        overdue_count = sum(1 for p in products if p['is_overdue'])

        station_stats = {
            'total_products': total_products,
            'total_orders': total_orders,
            'high_priority_count': high_priority_count,
            'overdue_count': overdue_count,
            'avg_priority_rank': sum(p['priority_rank'] for p in products) / len(products) if products else 999
        }

        now = datetime.utcnow()
        
        return render_template(
            'stations/packaging.html',
            products=products,
            orders_grouped=orders_list,
            station_code='packaging',
            station_name='Pakowanie',
            station_stats=station_stats,
            config=config,
            sort_by=sort_by,
            now=now,
            view_mode=view_mode,
            last_updated=datetime.utcnow(),
            page_title="Stanowisko Pakowania"
        )
        
    except Exception as e:
        logger.error("Błąd interfejsu pakowania", extra={
            'client_ip': request.remote_addr,
            'error': str(e)
        })
        
        return render_template(
            'stations/error.html',
            error_message="Błąd ładowania stanowiska pakowania",
            error_details=str(e),
            back_url=url_for('production.production_stations.station_select')
        ), 500


# ============================================================================
# MONITOR PRODUKCJI
# ============================================================================

@station_bp.route('/monitor')
def production_monitor():
    """
    Monitor produkcji - widok wszystkich zamówień z postępem na bieżącym stanowisku

    Wyświetla zamówienia z:
    - Postępem (X/Y) bazującym na quantity_done dla bieżącego stanowiska
    - Statusem zamówienia
    - Objętością

    Returns:
        HTML: Interfejs monitora produkcji
    """
    try:
        from ..models import ProductionItem
        from sqlalchemy import func, case, and_

        logger.info("Dostęp do monitora produkcji", extra={
            'client_ip': request.remote_addr
        })

        # Mapowanie statusu na stanowisko i kolumnę quantity_done
        status_to_station = {
            'czeka_na_wyciecie': ('cutting', 'quantity_done_cutting'),
            'czeka_na_skladanie': ('assembly', 'quantity_done_assembly'),
            'czeka_na_sklejanie': ('gluing', 'quantity_done_gluing'),
            'czeka_na_formatowanie': ('formatting', 'quantity_done_formatting'),
            'czeka_na_wykanczanie': ('finishing', 'quantity_done_finishing'),
            'czeka_na_pakowanie': ('packaging', 'quantity_done_packaging'),
        }

        status_labels = {
            'czeka_na_wyciecie': 'Wycinanie',
            'czeka_na_skladanie': 'Składanie',
            'czeka_na_sklejanie': 'Sklejanie',
            'czeka_na_formatowanie': 'Formatowanie',
            'czeka_na_wykanczanie': 'Wykańczanie',
            'czeka_na_pakowanie': 'Pakowanie',
            'spakowane': 'Spakowane',
        }

        status_class_map = {
            'czeka_na_wyciecie': 'status-cutting',
            'czeka_na_skladanie': 'status-assembly',
            'czeka_na_sklejanie': 'status-gluing',
            'czeka_na_formatowanie': 'status-formatting',
            'czeka_na_wykanczanie': 'status-finishing',
            'czeka_na_pakowanie': 'status-packaging',
            'spakowane': 'status-completed',
        }

        # Pobierz wszystkie aktywne zamówienia (nie spakowane)
        active_orders = db.session.query(
            ProductionItem.internal_order_number,
            ProductionItem.baselinker_order_id,
            ProductionItem.client_order_number
        ).filter(
            ProductionItem.current_status != 'spakowane',
            ProductionItem.internal_order_number.isnot(None)
        ).distinct().all()

        orders = []

        for order_row in active_orders:
            order_number = order_row[0]
            baselinker_id = order_row[1]
            client_order_number = order_row[2]

            # Pobierz wszystkie produkty tego zamówienia
            products = ProductionItem.query.filter(
                ProductionItem.internal_order_number == order_number
            ).all()

            if not products:
                continue

            # Oblicz statystyki zamówienia - NOWA LOGIKA Z QUANTITY
            total_products = sum(p.quantity for p in products)  # Suma wszystkich sztuk
            total_volume = sum((p.volume_m3 or 0) * p.quantity for p in products)  # Objętość * ilość

            # Znajdź dominujący status (status z największą liczbą produktów)
            status_counts = {}
            for p in products:
                status = p.current_status or 'unknown'
                status_counts[status] = status_counts.get(status, 0) + p.quantity

            # Dominujący status = ten z największą liczbą produktów
            dominant_status = max(status_counts, key=status_counts.get)

            # Oblicz completed_products na podstawie quantity_done dla dominującego stanowiska
            completed_products = 0
            if dominant_status in status_to_station:
                station_code, quantity_done_col = status_to_station[dominant_status]
                # Suma quantity_done dla wszystkich pozycji na tym stanowisku
                for p in products:
                    completed_products += getattr(p, quantity_done_col, 0)
            elif dominant_status == 'spakowane':
                # Wszystkie produkty są gotowe
                completed_products = total_products

            orders.append({
                'order_number': order_number,
                'baselinker_order_id': baselinker_id,
                'client_order_number': client_order_number,
                'total_products': total_products,
                'completed_products': completed_products,
                'total_volume': total_volume,
                'status_label': status_labels.get(dominant_status, dominant_status),
                'status_class': status_class_map.get(dominant_status, 'status-unknown'),
                'dominant_status': dominant_status
            })

        # Sortuj zamówienia (najpierw te z najwyższym postępem, potem alfabetycznie)
        orders.sort(key=lambda x: (-x['completed_products'] / max(x['total_products'], 1), x['order_number']))

        # Statystyki monitora
        monitor_stats = {
            'total_orders': len(orders),
            'completed_orders': sum(1 for o in orders if o['dominant_status'] == 'spakowane'),
            'total_products': sum(o['total_products'] for o in orders),
            'total_volume': sum(o['total_volume'] for o in orders)
        }

        config = get_station_config()
        now = datetime.utcnow()

        return render_template(
            'stations/monitor.html',
            orders=orders,
            monitor_stats=monitor_stats,
            config=config,
            now=now,
            page_title="Monitor Produkcji"
        )

    except Exception as e:
        logger.error("Błąd monitora produkcji", extra={
            'client_ip': request.remote_addr,
            'error': str(e),
            'traceback': traceback.format_exc()
        })

        return render_template(
            'stations/error.html',
            error_message="Błąd ładowania monitora produkcji",
            error_details=str(e),
            back_url=url_for('production.production_stations.station_select')
        ), 500


# ============================================================================
# AJAX ENDPOINTS DLA INTERFEJSÓW STANOWISK
# ============================================================================

@station_bp.route('/ajax/products/<station_code>')
def ajax_get_products(station_code):
    """
    AJAX endpoint dla odświeżania listy produktów

    Args:
        station_code: cutting|assembly|packaging

    Query params:
        sort: priority|deadline|created_at
        limit: max liczba produktów

    Returns:
        JSON: Lista produktów
    """
    try:
        if station_code not in ['cutting', 'assembly', 'packaging']:
            return jsonify({
                'success': False,
                'error': 'Invalid station code'
            }), 400

        record_heartbeat(station_code)
        sort_by = request.args.get('sort', 'priority')
        limit = min(int(request.args.get('limit', 50)), 100)
        
        # Pobranie produktów
        products = get_products_for_station(station_code, limit, sort_by)
        
        # Statystyki - POPRAWKA: priority_rank zamiast priority_score
        total_products = len(products)
        high_priority_count = sum(1 for p in products if p['priority_rank'] <= 50)
        overdue_count = sum(1 for p in products if p['is_overdue'])
        total_volume = sum(p['volume_m3'] for p in products)
        
        result = {
            'success': True,
            'data': {
                'products': products,
                'stats': {
                    'total_products': total_products,
                    'high_priority_count': high_priority_count,
                    'overdue_count': overdue_count,
                    'total_volume': total_volume,
                    'avg_priority_rank': sum(p['priority_rank'] for p in products) / len(products) if products else 999
                },
                'last_updated': datetime.utcnow().isoformat(),
                'station_code': station_code,
                'sort_by': sort_by
            }
        }
        
        logger.debug("AJAX: Pobrano produkty dla stanowiska", extra={
            'station_code': station_code,
            'products_count': len(products),
            'client_ip': request.remote_addr
        })
        
        return jsonify(result), 200
        
    except Exception as e:
        logger.error("Błąd AJAX pobierania produktów", extra={
            'station_code': station_code,
            'error': str(e)
        })
        
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@station_bp.route('/ajax/summary')
def ajax_station_summary():
    """
    AJAX endpoint dla odświeżania podsumowania stanowisk
    
    Returns:
        JSON: Podsumowanie wszystkich stanowisk
    """
    try:
        # Pobranie podsumowania
        summary = get_station_summary()
        
        result = {
            'success': True,
            'data': {
                'stations': summary,
                'last_updated': datetime.utcnow().isoformat()
            }
        }
        
        logger.debug("AJAX: Pobrano podsumowanie stanowisk", extra={
            'client_ip': request.remote_addr
        })
        
        return jsonify(result), 200
        
    except Exception as e:
        logger.error("Błąd AJAX podsumowania stanowisk", extra={'error': str(e)})
        
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


# ============================================================================
# GENERYCZNA FUNKCJA AJAX DLA PROSTYCH STANOWISK
# ============================================================================

def _ajax_get_orders_simple(station_code: str, status_filter: str, quantity_done_field: str):
    """
    Generyczna funkcja AJAX dla stanowisk z prostą logiką (gluing, formatting, finishing).

    Stanowiska z unikalnymi wymaganiami (packaging, cutting, assembly) mają osobne implementacje.

    Args:
        station_code: Kod stanowiska (gluing, formatting, finishing)
        status_filter: Status produktów do filtrowania (np. 'czeka_na_sklejanie')
        quantity_done_field: Nazwa atrybutu quantity_done_* (np. 'quantity_done_gluing')

    Returns:
        Flask Response z JSON
    """
    try:
        from ..models import ProductionItem
        from sqlalchemy import asc

        sort_by = request.args.get('sort', 'priority')

        logger.debug(f"AJAX: Pobieranie zamówień {station_code}", extra={
            'sort_by': sort_by,
            'client_ip': request.remote_addr
        })

        # KROK 1: Znajdź zamówienia które mają choć 1 produkt do przetworzenia
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

        # KROK 2: Pobierz WSZYSTKIE produkty z tych zamówień
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

        # KROK 3: Grupowanie produktów po zamówieniach
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

            # Dodaj produkt do zamówienia
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

            # Oblicz wymiary z parsowanych pól
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

        # KROK 4: Sortuj produkty wewnątrz każdego zamówienia
        for order_num, order_data in orders_grouped.items():
            order_data['products'].sort(key=lambda p: p['product_sequence_in_order'])

        # KROK 5: Dodaj informacje wyświetlania
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
                    order_data['display_deadline'] = f"Opóźnione o {abs(days_diff)} dni"
                elif days_diff == 0:
                    order_data['display_deadline'] = "Dziś!"
                elif days_diff == 1:
                    order_data['display_deadline'] = "Jutro"
                else:
                    order_data['display_deadline'] = f"Za {days_diff} dni"
            else:
                order_data['display_deadline'] = "Brak terminu"

            if order_data['worst_deadline']:
                order_data['deadline_date'] = order_data['worst_deadline'].isoformat()
                order_data['worst_deadline'] = order_data['worst_deadline'].isoformat()

        # KROK 6: Sortowanie zamówień
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
        logger.error(f"Błąd AJAX orders {station_code}", extra={
            'error': str(e),
            'traceback': traceback.format_exc()
        })

        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@station_bp.route('/ajax/orders/packaging')
def ajax_get_orders_packaging():
    """
    AJAX endpoint dla odświeżania ZAMÓWIEŃ na stanowisku pakowania

    RÓŻNICA od ajax_get_products:
    - Zwraca ZAMÓWIENIA (grouped) zamiast płaskiej listy produktów
    - Struktura identyczna z initial server-side render (bez limitu)

    Query params:
        sort: priority|deadline|created_at (default: priority)

    Returns:
        JSON: {
            success: bool,
            data: {
                orders: [...],  # Pogrupowane zamówienia
                stats: {...}    # Statystyki
            }
        }
    """
    try:
        from ..models import ProductionItem
        from sqlalchemy import asc, desc

        sort_by = request.args.get('sort', 'priority')

        logger.debug("AJAX: Pobieranie zamówień packaging", extra={
            'sort_by': sort_by,
            'client_ip': request.remote_addr
        })
        
        # KROK 1: Znajdź zamówienia które mają choć 1 produkt do pakowania
        orders_with_packaging = db.session.query(
            ProductionItem.internal_order_number
        ).filter(
            ProductionItem.current_status == 'czeka_na_pakowanie'
        ).distinct().all()

        order_numbers = [order[0] for order in orders_with_packaging]

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

        # KROK 2: Pobierz WSZYSTKIE produkty z tych zamówień (bez limitu)
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

        # KROK 3: Grupowanie produktów po zamówieniach
        orders_grouped = {}
        today = date.today()
        
        for product in products:
            order_num = product.internal_order_number
            
            if order_num not in orders_grouped:
                orders_grouped[order_num] = {
                    'order_number': order_num,
                    'baselinker_order_id': None,
                    'client_order_number': None,
                    'products': [],
                    'total_products': 0,
                    'total_quantity': 0,
                    'total_quantity_done': 0,
                    'ready_count': 0,
                    'not_ready_count': 0,
                    'total_volume': 0,
                    'best_priority_rank': 999,
                    'worst_deadline': None,
                    # DANE DOSTAWY (2025-12)
                    'delivery_method': None,
                    'delivery_fullname': None,
                    'delivery_company': None,
                    'delivery_address': None,
                    'delivery_city': None,
                    'delivery_postcode': None,
                    'delivery_country_code': None,
                    'is_personal_pickup': None,
                    'delivery_type': None,
                    # DANE WYSYŁKI KURIERSKIEJ (2025-12)
                    'shipping_package_id': None,
                    'shipping_tracking_number': None,
                    'shipping_courier_name': None,
                    'shipping_price': None,
                    'shipping_label_base64': None,
                    'shipping_created_at': None,
                }

            # Wymiary w CM (taka sama logika jak przy początkowym renderowaniu)
            dimensions_parts = []
            if product.parsed_length_cm:
                dimensions_parts.append(_format_dimension(product.parsed_length_cm))
            if product.parsed_width_cm:
                dimensions_parts.append(_format_dimension(product.parsed_width_cm))
            if product.parsed_thickness_cm:
                dimensions_parts.append(_format_dimension(product.parsed_thickness_cm))
            dimensions_text = '×'.join(dimensions_parts) + ' cm' if dimensions_parts else None

            # Dodaj produkt do zamówienia
            product_data = {
                'id': product.short_product_id,
                'original_name': product.original_product_name or 'Brak nazwy',
                'volume_m3': float(product.volume_m3 or 0),
                'current_status': product.current_status,
                'priority_rank': product.priority_rank or 999,
                'deadline_date': product.deadline_date.isoformat() if product.deadline_date else None,
                'quantity': product.quantity,
                'quantity_done': product.quantity_done_packaging,
                'is_complete': product.quantity_done_packaging == product.quantity,
                'is_priority': product.is_priority,
                # Pola potrzebne do renderowania badges (dodane dla spójności z initial render)
                'wood_species': product.parsed_wood_species,
                'technology': product.parsed_technology,
                'wood_class': product.parsed_wood_class,
                'finish_state': product.parsed_finish_state,
                'dimensions': dimensions_text,
                'attachment_file_url': product.attachment_file_url,
                'attachment_file_name': product.attachment_file_name,
                'order_notes': product.order_notes,
                # WYMIARY SUROWE DO OBLICZEŃ WYSYŁKI (2025-12)
                'parsed_length_cm': float(product.parsed_length_cm) if product.parsed_length_cm else 0,
                'parsed_width_cm': float(product.parsed_width_cm) if product.parsed_width_cm else 0,
                'parsed_thickness_cm': float(product.parsed_thickness_cm) if product.parsed_thickness_cm else 0,
                # DANE DOSTAWY (2025-12)
                'delivery_method': product.delivery_method,
                'delivery_fullname': product.delivery_fullname,
                'delivery_company': product.delivery_company,
                'delivery_address': product.delivery_address,
                'delivery_city': product.delivery_city,
                'delivery_postcode': product.delivery_postcode,
                'delivery_country_code': product.delivery_country_code,
                'is_personal_pickup': product.is_personal_pickup,
                'delivery_type': product.delivery_type,
            }

            orders_grouped[order_num]['products'].append(product_data)
            orders_grouped[order_num]['total_products'] += 1
            orders_grouped[order_num]['total_volume'] += float(product.volume_m3 or 0)
            orders_grouped[order_num]['total_quantity'] += product.quantity or 1
            orders_grouped[order_num]['total_quantity_done'] += product.quantity_done_packaging or 0

            # Weź baselinker_order_id z pierwszego produktu który go ma
            if not orders_grouped[order_num]['baselinker_order_id'] and product.baselinker_order_id:
                orders_grouped[order_num]['baselinker_order_id'] = product.baselinker_order_id

            # Weź client_order_number z pierwszego produktu który go ma
            if not orders_grouped[order_num]['client_order_number'] and product.client_order_number:
                orders_grouped[order_num]['client_order_number'] = product.client_order_number

            # Pobierz dane dostawy z pierwszego produktu (2025-12)
            if orders_grouped[order_num]['delivery_method'] is None:
                orders_grouped[order_num]['delivery_method'] = product.delivery_method
                orders_grouped[order_num]['delivery_fullname'] = product.delivery_fullname
                orders_grouped[order_num]['delivery_company'] = product.delivery_company
                orders_grouped[order_num]['delivery_address'] = product.delivery_address
                orders_grouped[order_num]['delivery_city'] = product.delivery_city
                orders_grouped[order_num]['delivery_postcode'] = product.delivery_postcode
                orders_grouped[order_num]['delivery_country_code'] = product.delivery_country_code
                orders_grouped[order_num]['is_personal_pickup'] = product.is_personal_pickup
                orders_grouped[order_num]['delivery_type'] = product.delivery_type

            # Pobierz dane wysyłki z pierwszego produktu który je ma (2025-12)
            if orders_grouped[order_num]['shipping_package_id'] is None and product.shipping_package_id:
                orders_grouped[order_num]['shipping_package_id'] = product.shipping_package_id
                orders_grouped[order_num]['shipping_tracking_number'] = product.shipping_tracking_number
                orders_grouped[order_num]['shipping_courier_name'] = product.shipping_courier_name
                orders_grouped[order_num]['shipping_price'] = float(product.shipping_price) if product.shipping_price else None
                orders_grouped[order_num]['shipping_label_base64'] = product.shipping_label_base64
                orders_grouped[order_num]['shipping_created_at'] = product.shipping_created_at.isoformat() if product.shipping_created_at else None

            # Liczniki gotowości
            if product.current_status == 'czeka_na_pakowanie':
                orders_grouped[order_num]['ready_count'] += 1
            else:
                orders_grouped[order_num]['not_ready_count'] += 1
            
            # Najlepszy priorytet w zamówieniu
            if product.priority_rank and product.priority_rank < orders_grouped[order_num]['best_priority_rank']:
                orders_grouped[order_num]['best_priority_rank'] = product.priority_rank
            
            # Najgorszy deadline w zamówieniu
            if product.deadline_date:
                if orders_grouped[order_num]['worst_deadline'] is None:
                    orders_grouped[order_num]['worst_deadline'] = product.deadline_date
                elif product.deadline_date > orders_grouped[order_num]['worst_deadline']:
                    orders_grouped[order_num]['worst_deadline'] = product.deadline_date
        
        # KROK 4: Dodaj informacje wyświetlania do każdego zamówienia
        for order_num, order_data in orders_grouped.items():
            # Priority class i label
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
            
            # Display deadline
            deadline = order_data['worst_deadline']
            if deadline:
                days_diff = (deadline - today).days
                if days_diff < 0:
                    order_data['display_deadline'] = f"Opóźnione o {abs(days_diff)} dni"
                elif days_diff == 0:
                    order_data['display_deadline'] = "Dziś!"
                elif days_diff == 1:
                    order_data['display_deadline'] = "Jutro"
                else:
                    order_data['display_deadline'] = f"Za {days_diff} dni"
            else:
                order_data['display_deadline'] = "Brak terminu"
            
            # Konwertuj deadline na string dla JSON
            if order_data['worst_deadline']:
                order_data['worst_deadline'] = order_data['worst_deadline'].isoformat()
        
        # KROK 5: Sortowanie zamówień
        orders_list = list(orders_grouped.values())
        if sort_by == 'priority':
            orders_list.sort(key=lambda x: x['best_priority_rank'])
        elif sort_by == 'deadline':
            orders_list.sort(key=lambda x: x['worst_deadline'] or '9999-12-31')
        
        # KROK 6: Statystyki
        high_priority_count = sum(1 for order in orders_list if order['best_priority_rank'] <= 50)
        overdue_count = sum(1 for order in orders_list 
                           if order['worst_deadline'] and order['worst_deadline'] < today.isoformat())
        total_volume = sum(order['total_volume'] for order in orders_list)
        total_products = sum(order['ready_count'] for order in orders_list)
        
        stats = {
            'total_orders': len(orders_list),
            'total_products': total_products,
            'high_priority_count': high_priority_count,
            'overdue_count': overdue_count,
            'total_volume': round(total_volume, 4)
        }
        
        logger.debug("AJAX: Zwracam zamówienia packaging", extra={
            'orders_count': len(orders_list),
            'total_products': stats['total_products']
        })
        
        return jsonify({
            'success': True,
            'data': {
                'orders': orders_list,
                'stats': stats
            }
        }), 200
        
    except Exception as e:
        logger.error("Błąd AJAX orders packaging", extra={
            'error': str(e),
            'traceback': traceback.format_exc()
        })
        
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@station_bp.route('/ajax/orders/cutting')
def ajax_get_orders_cutting():
    """
    AJAX endpoint dla odświeżania ZAMÓWIEŃ na stanowisku wycinania

    IDENTYCZNA LOGIKA jak packaging, ale dla statusu 'czeka_na_wyciecie'

    Query params:
        sort: priority|deadline|created_at (default: priority)

    Returns:
        JSON: {
            success: bool,
            data: {
                orders: [...],  # Pogrupowane zamówienia
                stats: {...}    # Statystyki
            }
        }
    """
    try:
        from ..models import ProductionItem
        from sqlalchemy import asc, desc

        sort_by = request.args.get('sort', 'priority')

        logger.debug("AJAX: Pobieranie zamówień cutting", extra={
            'sort_by': sort_by,
            'client_ip': request.remote_addr
        })

        # KROK 1: Znajdź zamówienia które mają choć 1 produkt do wycięcia (AJAX CUTTING)
        # Wycinanie widzi: czeka_na_wyciecie ORAZ czeka_na_skladanie (gdzie cutting_completed_at IS NULL)
        orders_with_cutting = db.session.query(
            ProductionItem.internal_order_number
        ).filter(
            db.or_(
                ProductionItem.current_status == 'czeka_na_wyciecie',
                db.and_(
                    ProductionItem.current_status == 'czeka_na_skladanie',
                    ProductionItem.cutting_completed_at.is_(None)
                )
            )
        ).distinct().all()

        order_numbers = [order[0] for order in orders_with_cutting]

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

        # KROK 2: Pobierz produkty z tych zamówień które pasują do kryteriów wycinania
        # (czeka_na_wyciecie LUB czeka_na_skladanie z cutting_completed_at IS NULL)
        query = ProductionItem.query.filter(
            ProductionItem.internal_order_number.in_(order_numbers),
            db.or_(
                ProductionItem.current_status == 'czeka_na_wyciecie',
                db.and_(
                    ProductionItem.current_status == 'czeka_na_skladanie',
                    ProductionItem.cutting_completed_at.is_(None)
                )
            )
        )

        # Sortowanie
        if sort_by == 'priority':
            query = query.order_by(asc(ProductionItem.priority_rank))
        elif sort_by == 'deadline':
            query = query.order_by(asc(ProductionItem.deadline_date))
        elif sort_by == 'created_at':
            query = query.order_by(asc(ProductionItem.created_at))

        products = query.all()

        # KROK 3: Grupowanie produktów po zamówieniach (AJAX)
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

            # Dodaj produkt do zamówienia z WSZYSTKIMI polami z PRD
            product_data = {
                'id': product.short_product_id,
                'short_product_id': product.short_product_id,
                'product_sequence_in_order': product.product_sequence_in_order,
                'original_name': product.original_product_name or 'Brak nazwy',
                'dimensions': None,  # Będzie obliczone poniżej
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
                'quantity_done': product.quantity_done_cutting,
                'quantity_done_assembly': product.quantity_done_assembly,
                'assembly_completed_at': product.assembly_completed_at.isoformat() if product.assembly_completed_at else None,
                'is_complete': product.quantity_done_cutting == product.quantity,
                'is_priority': product.is_priority
            }

            # Oblicz wymiary z parsowanych pól (w CM z jednostką)
            if product.parsed_length_cm and product.parsed_width_cm and product.parsed_thickness_cm:
                product_data['dimensions'] = f"{_format_dimension(product.parsed_length_cm)} × {_format_dimension(product.parsed_width_cm)} × {_format_dimension(product.parsed_thickness_cm)} cm"

            orders_grouped[order_num]['products'].append(product_data)
            orders_grouped[order_num]['total_products'] += 1
            orders_grouped[order_num]['total_volume'] += float(product.volume_m3 or 0)

            # Weź baselinker_order_id z pierwszego produktu który go ma
            if not orders_grouped[order_num]['baselinker_order_id'] and product.baselinker_order_id:
                orders_grouped[order_num]['baselinker_order_id'] = product.baselinker_order_id

            # Najlepszy priorytet w zamówieniu
            if product.priority_rank and product.priority_rank < orders_grouped[order_num]['best_priority_rank']:
                orders_grouped[order_num]['best_priority_rank'] = product.priority_rank

            # Najgorszy deadline w zamówieniu
            if product.deadline_date:
                if orders_grouped[order_num]['worst_deadline'] is None:
                    orders_grouped[order_num]['worst_deadline'] = product.deadline_date
                elif product.deadline_date > orders_grouped[order_num]['worst_deadline']:
                    orders_grouped[order_num]['worst_deadline'] = product.deadline_date

        # KROK 4: Sortuj produkty wewnątrz każdego zamówienia po product_sequence_in_order
        for order_num, order_data in orders_grouped.items():
            order_data['products'].sort(key=lambda p: p['product_sequence_in_order'])

        # KROK 5: Dodaj informacje wyświetlania do każdego zamówienia
        for order_num, order_data in orders_grouped.items():
            # Priority class i label
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

            # Display deadline
            deadline = order_data['worst_deadline']
            if deadline:
                days_diff = (deadline - today).days
                if days_diff < 0:
                    order_data['display_deadline'] = f"Opóźnione o {abs(days_diff)} dni"
                elif days_diff == 0:
                    order_data['display_deadline'] = "Dziś!"
                elif days_diff == 1:
                    order_data['display_deadline'] = "Jutro"
                else:
                    order_data['display_deadline'] = f"Za {days_diff} dni"
            else:
                order_data['display_deadline'] = "Brak terminu"

            # Konwertuj deadline na string dla JSON
            if order_data['worst_deadline']:
                order_data['deadline_date'] = order_data['worst_deadline'].isoformat()
                order_data['worst_deadline'] = order_data['worst_deadline'].isoformat()

        # KROK 6: Sortowanie zamówień
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

        logger.debug("AJAX: Zwracam zamówienia cutting", extra={
            'orders_count': len(orders_list),
            'total_products': stats['total_products']
        })

        return jsonify({
            'success': True,
            'data': {
                'orders': orders_list,
                'stats': stats
            }
        }), 200

    except Exception as e:
        logger.error("Błąd AJAX orders cutting", extra={
            'error': str(e),
            'traceback': traceback.format_exc()
        })

        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@station_bp.route('/ajax/orders/assembly')
def ajax_get_orders_assembly():
    """
    AJAX endpoint dla odświeżania ZAMÓWIEŃ na stanowisku składania

    IDENTYCZNA LOGIKA jak główna strona assembly_station (bez limitu)

    Query params:
        sort: priority|deadline|created_at (default: priority)

    Returns:
        JSON: {
            success: bool,
            data: {
                orders: [...],  # Pogrupowane zamówienia
                stats: {...}    # Statystyki
            }
        }
    """
    try:
        from ..models import ProductionItem
        from sqlalchemy import asc, desc

        sort_by = request.args.get('sort', 'priority')

        logger.debug("AJAX: Pobieranie zamówień assembly", extra={
            'sort_by': sort_by,
            'client_ip': request.remote_addr
        })

        # KROK 1: Znajdź zamówienia które mają choć 1 produkt do składania
        # Składanie widzi: czeka_na_wyciecie ORAZ czeka_na_skladanie (wszystkie)
        orders_with_assembly = db.session.query(
            ProductionItem.internal_order_number
        ).filter(
            db.or_(
                ProductionItem.current_status == 'czeka_na_wyciecie',
                ProductionItem.current_status == 'czeka_na_skladanie'
            )
        ).distinct().all()

        order_numbers = [order[0] for order in orders_with_assembly]

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

        # KROK 2: Pobierz produkty z tych zamówień które pasują do kryteriów składania
        # (czeka_na_wyciecie LUB czeka_na_skladanie)
        query = ProductionItem.query.filter(
            ProductionItem.internal_order_number.in_(order_numbers),
            db.or_(
                ProductionItem.current_status == 'czeka_na_wyciecie',
                ProductionItem.current_status == 'czeka_na_skladanie'
            )
        )

        # Sortowanie
        if sort_by == 'priority':
            query = query.order_by(asc(ProductionItem.priority_rank))
        elif sort_by == 'deadline':
            query = query.order_by(asc(ProductionItem.deadline_date))
        elif sort_by == 'created_at':
            query = query.order_by(asc(ProductionItem.created_at))

        products = query.all()

        # KROK 3: Grupowanie produktów po zamówieniach
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

            # Dodaj produkt do zamówienia z WSZYSTKIMI polami z PRD
            product_data = {
                'id': product.short_product_id,
                'short_product_id': product.short_product_id,
                'product_sequence_in_order': product.product_sequence_in_order,
                'original_name': product.original_product_name or 'Brak nazwy',
                'dimensions': None,  # Będzie obliczone poniżej
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
                'quantity_done': product.quantity_done_assembly,
                'quantity_done_cutting': product.quantity_done_cutting or 0,
                'cutting_completed_at': product.cutting_completed_at.isoformat() if product.cutting_completed_at else None,
                'is_complete': product.quantity_done_assembly == product.quantity,
                'is_priority': product.is_priority
            }

            # Oblicz wymiary z parsowanych pól (w MM z jednostką)
            if product.parsed_length_cm and product.parsed_width_cm and product.parsed_thickness_cm:
                product_data['dimensions'] = f"{_format_dimension(product.parsed_length_cm)} × {_format_dimension(product.parsed_width_cm)} × {_format_dimension(product.parsed_thickness_cm)} cm"

            orders_grouped[order_num]['products'].append(product_data)
            orders_grouped[order_num]['total_products'] += 1
            orders_grouped[order_num]['total_volume'] += float(product.volume_m3 or 0)

            # Weź baselinker_order_id z pierwszego produktu który go ma
            if not orders_grouped[order_num]['baselinker_order_id'] and product.baselinker_order_id:
                orders_grouped[order_num]['baselinker_order_id'] = product.baselinker_order_id

            # Najlepszy priorytet w zamówieniu
            if product.priority_rank and product.priority_rank < orders_grouped[order_num]['best_priority_rank']:
                orders_grouped[order_num]['best_priority_rank'] = product.priority_rank

            # Najgorszy deadline w zamówieniu
            if product.deadline_date:
                if orders_grouped[order_num]['worst_deadline'] is None:
                    orders_grouped[order_num]['worst_deadline'] = product.deadline_date
                elif product.deadline_date > orders_grouped[order_num]['worst_deadline']:
                    orders_grouped[order_num]['worst_deadline'] = product.deadline_date

        # KROK 4: Sortuj produkty wewnątrz każdego zamówienia po product_sequence_in_order
        for order_num, order_data in orders_grouped.items():
            order_data['products'].sort(key=lambda p: p['product_sequence_in_order'])

        # KROK 5: Dodaj informacje wyświetlania do każdego zamówienia
        for order_num, order_data in orders_grouped.items():
            # Priority class i label
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

            # Display deadline
            deadline = order_data['worst_deadline']
            if deadline:
                days_diff = (deadline - today).days
                if days_diff < 0:
                    order_data['display_deadline'] = f"Opóźnione o {abs(days_diff)} dni"
                elif days_diff == 0:
                    order_data['display_deadline'] = "Dziś!"
                elif days_diff == 1:
                    order_data['display_deadline'] = "Jutro"
                else:
                    order_data['display_deadline'] = f"Za {days_diff} dni"
            else:
                order_data['display_deadline'] = "Brak terminu"

            # Konwertuj deadline na string dla JSON
            if order_data['worst_deadline']:
                order_data['deadline_date'] = order_data['worst_deadline'].isoformat()
                order_data['worst_deadline'] = order_data['worst_deadline'].isoformat()

        # KROK 6: Sortowanie zamówień
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

        logger.debug("AJAX: Zwracam zamówienia assembly", extra={
            'orders_count': len(orders_list),
            'total_products': stats['total_products']
        })

        return jsonify({
            'success': True,
            'data': {
                'orders': orders_list,
                'stats': stats
            }
        }), 200

    except Exception as e:
        logger.error("Błąd AJAX orders assembly", extra={
            'error': str(e),
            'traceback': traceback.format_exc()
        })

        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@station_bp.route('/ajax/orders/gluing')
def ajax_get_orders_gluing():
    """AJAX endpoint dla odświeżania ZAMÓWIEŃ na stanowisku sklejania"""
    return _ajax_get_orders_simple('gluing', 'czeka_na_sklejanie', 'quantity_done_gluing')


@station_bp.route('/ajax/orders/formatting')
def ajax_get_orders_formatting():
    """AJAX endpoint dla odświeżania ZAMÓWIEŃ na stanowisku formatowania"""
    return _ajax_get_orders_simple('formatting', 'czeka_na_formatowanie', 'quantity_done_formatting')


@station_bp.route('/ajax/orders/finishing')
def ajax_get_orders_finishing():
    """AJAX endpoint dla odświeżania ZAMÓWIEŃ na stanowisku wykańczania"""
    return _ajax_get_orders_simple('finishing', 'czeka_na_wykanczanie', 'quantity_done_finishing')


@station_bp.route('/ajax/station-today-m3/<station_code>')
def ajax_station_today_m3(station_code):
    """
    AJAX endpoint dla dzisiejszych m³ wykonanych na danym stanowisku

    Zwraca sumę volume_m3 dla produktów ukończonych dzisiaj na danym stanowisku.
    Używa tej samej logiki co dashboard dla spójności danych.

    Args:
        station_code: cutting|assembly|gluing|formatting|finishing|packaging

    Returns:
        JSON: {
            success: bool,
            data: {
                station_code: str,
                today_m3: float,
                today_date: str (ISO format),
                last_updated: str (ISO format)
            }
        }
    """
    try:
        # Walidacja station_code
        if station_code not in ['cutting', 'assembly', 'gluing', 'formatting', 'finishing', 'packaging']:
            return jsonify({
                'success': False,
                'error': f'Nieprawidłowy station_code. Dozwolone: cutting, assembly, gluing, formatting, finishing, packaging'
            }), 400

        record_heartbeat(station_code)

        from ..models import ProductionItem

        # Określ zakres czasowy dla "dzisiaj"
        today = date.today()
        today_start = datetime.combine(today, datetime.min.time())
        today_end = datetime.combine(today, datetime.max.time())

        # Mapowanie station_code na pole completed_at z try-except dla nowych pól
        try:
            completed_at_field_map = {
                'cutting': ProductionItem.cutting_completed_at,
                'assembly': ProductionItem.assembly_completed_at,
                'gluing': ProductionItem.gluing_completed_at,
                'formatting': ProductionItem.formatting_completed_at,
                'finishing': ProductionItem.finishing_completed_at,
                'packaging': ProductionItem.packaging_completed_at
            }

            completed_at_field = completed_at_field_map[station_code]

            # Query dla dzisiejszych m³ (identyczna logika jak w dashboard)
            today_m3 = db.session.query(
                db.func.coalesce(db.func.sum(ProductionItem.volume_m3), 0)
            ).filter(
                completed_at_field >= today_start,
                completed_at_field <= today_end
            ).scalar() or 0.0
        except AttributeError:
            # Pole nie istnieje jeszcze w modelu - zwróć 0
            logger.warning(f"Pole {station_code}_completed_at nie istnieje w modelu", extra={
                'station_code': station_code
            })
            today_m3 = 0.0
        
        # Konwersja na float dla JSON
        today_m3 = float(today_m3)
        
        result = {
            'success': True,
            'data': {
                'station_code': station_code,
                'today_m3': round(today_m3, 4),
                'today_date': today.isoformat(),
                'last_updated': datetime.utcnow().isoformat()
            }
        }
        
        logger.debug("AJAX: Pobrano dzisiejsze m³ dla stanowiska", extra={
            'station_code': station_code,
            'today_m3': today_m3,
            'client_ip': request.remote_addr
        })
        
        return jsonify(result), 200
        
    except Exception as e:
        logger.error("Błąd AJAX station-today-m3", extra={
            'station_code': station_code,
            'error': str(e),
            'traceback': traceback.format_exc()
        })
        
        return jsonify({
            'success': False,
            'error': f'Błąd pobierania danych: {str(e)}'
        }), 500


@station_bp.route('/ajax/monitor')
def ajax_monitor_data():
    """
    AJAX endpoint dla monitora produkcji

    Zwraca listę zamówień z postępem (quantity_done) dla bieżącego stanowiska.

    Returns:
        JSON: {
            success: bool,
            orders: [...],
            stats: {...}
        }
    """
    try:
        from ..models import ProductionItem

        logger.debug("AJAX monitor - pobieranie danych")

        # Mapowanie statusu na kolumnę quantity_done
        status_to_station = {
            'czeka_na_wyciecie': ('cutting', 'quantity_done_cutting'),
            'czeka_na_skladanie': ('assembly', 'quantity_done_assembly'),
            'czeka_na_sklejanie': ('gluing', 'quantity_done_gluing'),
            'czeka_na_formatowanie': ('formatting', 'quantity_done_formatting'),
            'czeka_na_wykanczanie': ('finishing', 'quantity_done_finishing'),
            'czeka_na_pakowanie': ('packaging', 'quantity_done_packaging'),
        }

        status_labels = {
            'czeka_na_wyciecie': 'Wycinanie',
            'czeka_na_skladanie': 'Skladanie',
            'czeka_na_sklejanie': 'Sklejanie',
            'czeka_na_formatowanie': 'Formatowanie',
            'czeka_na_wykanczanie': 'Wykonczanie',
            'czeka_na_pakowanie': 'Pakowanie',
            'spakowane': 'Spakowane',
        }

        status_class_map = {
            'czeka_na_wyciecie': 'status-cutting',
            'czeka_na_skladanie': 'status-assembly',
            'czeka_na_sklejanie': 'status-gluing',
            'czeka_na_formatowanie': 'status-formatting',
            'czeka_na_wykanczanie': 'status-finishing',
            'czeka_na_pakowanie': 'status-packaging',
            'spakowane': 'status-completed',
        }

        # Pobierz wszystkie aktywne zamówienia (nie spakowane)
        active_orders = db.session.query(
            ProductionItem.internal_order_number,
            ProductionItem.baselinker_order_id
        ).filter(
            ProductionItem.current_status != 'spakowane',
            ProductionItem.internal_order_number.isnot(None)
        ).distinct().all()

        orders = []

        for order_row in active_orders:
            order_number = order_row[0]
            baselinker_id = order_row[1]

            # Pobierz wszystkie produkty tego zamówienia
            products = ProductionItem.query.filter(
                ProductionItem.internal_order_number == order_number
            ).all()

            if not products:
                continue

            # Oblicz statystyki zamówienia - NOWA LOGIKA Z QUANTITY
            total_products = sum(p.quantity for p in products)  # Suma wszystkich sztuk
            total_volume = sum((p.volume_m3 or 0) * p.quantity for p in products)

            # Znajdź dominujący status
            status_counts = {}
            for p in products:
                status = p.current_status or 'unknown'
                status_counts[status] = status_counts.get(status, 0) + p.quantity

            dominant_status = max(status_counts, key=status_counts.get)

            # Oblicz completed_products na podstawie quantity_done
            completed_products = 0
            if dominant_status in status_to_station:
                station_code, quantity_done_col = status_to_station[dominant_status]
                for p in products:
                    completed_products += getattr(p, quantity_done_col, 0)
            elif dominant_status == 'spakowane':
                completed_products = total_products

            orders.append({
                'order_number': order_number,
                'baselinker_order_id': baselinker_id,
                'total_products': total_products,
                'completed_products': completed_products,
                'total_volume': total_volume,
                'status_label': status_labels.get(dominant_status, dominant_status),
                'status_class': status_class_map.get(dominant_status, 'status-unknown'),
                'dominant_status': dominant_status
            })

        # Sortuj zamówienia
        orders.sort(key=lambda x: (-x['completed_products'] / max(x['total_products'], 1), x['order_number']))

        # Statystyki
        stats = {
            'total_orders': len(orders),
            'completed_orders': sum(1 for o in orders if o['dominant_status'] == 'spakowane'),
            'total_products': sum(o['total_products'] for o in orders),
            'total_volume': sum(o['total_volume'] for o in orders)
        }

        return jsonify({
            'success': True,
            'orders': orders,
            'stats': stats,
            'last_updated': datetime.utcnow().isoformat()
        })

    except Exception as e:
        logger.error("Błąd AJAX monitor", extra={
            'error': str(e),
            'traceback': traceback.format_exc()
        })

        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


# ============================================================================
# BULK COMPLETION ENDPOINT - Order-based stations (all 6 stations)
# ============================================================================

@station_bp.route('/complete-order', methods=['POST'])
def complete_order_bulk():
    """
    POST /production/stations/complete-order

    Bulk completion endpoint dla order-based stations (cutting/assembly)

    Ukończa WSZYSTKIE produkty z danego zamówienia naraz (transakcyjnie).

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

    Logika:
    - Transakcyjna (all-or-nothing)
    - Walidacja że wszystkie produkty należą do tego samego zamówienia
    - Walidacja że wszystkie produkty mają odpowiedni status
    - Rollback w razie błędu
    """
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'Brak danych JSON'}), 400

        order_number = data.get('order_number')
        product_ids = data.get('product_ids', [])
        station = data.get('station')
        action = data.get('action')

        # Walidacja inputów
        if not order_number or not product_ids or not station or not action:
            return jsonify({
                'success': False,
                'error': 'Wymagane pola: order_number, product_ids, station, action'
            }), 400

        if station not in ['cutting', 'assembly', 'gluing', 'formatting', 'finishing', 'packaging']:
            return jsonify({
                'success': False,
                'error': f'Nieprawidłowe stanowisko: {station}. Dozwolone: cutting, assembly, gluing, formatting, finishing, packaging'
            }), 400

        if action != 'complete':
            return jsonify({
                'success': False,
                'error': 'Tylko action="complete" jest wspierany'
            }), 400

        if not isinstance(product_ids, list) or len(product_ids) == 0:
            return jsonify({
                'success': False,
                'error': 'product_ids musi być niepustą listą'
            }), 400

        logger.info("BULK: Rozpoczęcie bulk completion", extra={
            'order_number': order_number,
            'product_ids_count': len(product_ids),
            'station': station,
            'client_ip': request.remote_addr
        })

        from ..models import ProductionItem

        # KROK 1: Pobierz wszystkie produkty
        products = ProductionItem.query.filter(
            ProductionItem.short_product_id.in_(product_ids)
        ).all()

        if len(products) != len(product_ids):
            found_ids = [p.short_product_id for p in products]
            missing_ids = list(set(product_ids) - set(found_ids))
            return jsonify({
                'success': False,
                'error': f'Nie znaleziono produktów: {missing_ids}'
            }), 404

        # KROK 2: Walidacja że wszystkie produkty należą do tego samego zamówienia
        for product in products:
            if product.internal_order_number != order_number:
                return jsonify({
                    'success': False,
                    'error': f'Produkt {product.short_product_id} nie należy do zamówienia {order_number}'
                }), 400

        # KROK 3: Walidacja statusów
        # Cutting i Assembly mają specjalną logikę - oba widzą produkty czeka_na_wyciecie i czeka_na_skladanie
        expected_status_map = {
            'cutting': ['czeka_na_wyciecie', 'czeka_na_skladanie'],  # Cutting widzi oba statusy
            'assembly': ['czeka_na_wyciecie', 'czeka_na_skladanie'],  # Assembly widzi oba statusy
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
                # Cutting: akceptuje czeka_na_wyciecie LUB czeka_na_skladanie (gdzie cutting_completed_at IS NULL)
                if product.current_status == 'czeka_na_wyciecie':
                    is_valid = True
                elif product.current_status == 'czeka_na_skladanie' and product.cutting_completed_at is None:
                    is_valid = True
            elif station == 'assembly':
                # Assembly: akceptuje czeka_na_wyciecie LUB czeka_na_skladanie
                if product.current_status in expected_statuses:
                    is_valid = True
            else:
                # Pozostałe stanowiska - standardowa walidacja
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
                'error': 'Niektóre produkty mają nieprawidłowy status',
                'invalid_products': invalid_products
            }), 400

        # KROK 4: Transakcyjne ukończenie wszystkich produktów
        completed_count = 0
        next_status = None

        try:
            for product in products:
                old_status = product.current_status
                product.complete_task(station)
                next_status = product.current_status
                completed_count += 1

                logger.debug("BULK: Ukończono produkt", extra={
                    'product_id': product.short_product_id,
                    'old_status': old_status,
                    'new_status': next_status
                })

            # Commit transakcji
            db.session.commit()

            logger.info("BULK: Sukces bulk completion", extra={
                'order_number': order_number,
                'completed_count': completed_count,
                'station': station,
                'next_status': next_status,
                'client_ip': request.remote_addr
            })

            return jsonify({
                'success': True,
                'message': f'Ukończono {completed_count} produktów z zamówienia {order_number}',
                'data': {
                    'completed_count': completed_count,
                    'order_number': order_number,
                    'next_status': next_status,
                    'product_ids': product_ids
                }
            }), 200

        except Exception as commit_error:
            db.session.rollback()
            logger.error("BULK: Błąd podczas commit", extra={
                'order_number': order_number,
                'completed_before_error': completed_count,
                'error': str(commit_error),
                'traceback': traceback.format_exc()
            })
            raise commit_error

    except Exception as e:
        db.session.rollback()
        logger.error("BULK: Błąd bulk completion", extra={
            'order_number': data.get('order_number') if 'data' in locals() else None,
            'station': data.get('station') if 'data' in locals() else None,
            'client_ip': request.remote_addr,
            'error': str(e),
            'traceback': traceback.format_exc()
        })

        return jsonify({
            'success': False,
            'error': f'Błąd bulk completion: {str(e)}'
        }), 500

# ============================================================================
# UTILITY ROUTERS
# ============================================================================

@station_bp.route('/config')
def get_station_frontend_config():
    """
    Endpoint dla konfiguracji JavaScript frontend
    
    Returns:
        JSON: Konfiguracja dla interfejsów stanowisk
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
        logger.error("Błąd pobierania konfiguracji frontend", extra={'error': str(e)})
        
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

# ============================================================================
# ERROR HANDLERS
# ============================================================================

@station_bp.errorhandler(403)
def station_access_denied(error):
    """Handler dla błędów dostępu IP"""
    logger.warning("Odrzucono dostęp do interfejsu stanowiska", extra={
        'client_ip': request.remote_addr,
        'path': request.path,
        'user_agent': request.headers.get('User-Agent')
    })
    
    return render_template(
        'stations/access_denied.html',
        error_message="Dostęp zabroniony",
        error_details="Twój adres IP nie jest autoryzowany do dostępu do stanowisk produkcyjnych.",
        client_ip=request.remote_addr
    ), 403

@station_bp.errorhandler(500)
def station_server_error(error):
    """Handler dla błędów serwera w interfejsach stanowisk"""
    from ..services.error_service import log_production_error

    # Loguj do Python logger
    logger.error("Błąd serwera w interfejsie stanowiska", extra={
        'client_ip': request.remote_addr,
        'path': request.path,
        'error': str(error)
    })

    # Zapisz do bazy danych prod_errors
    error_type = 'template_error' if 'template' in str(error).lower() or 'jinja' in str(error).lower() else 'api_error'

    log_production_error(
        error_type=error_type,
        error_message=f"Błąd 500 w interfejsie stanowiska: {str(error)}",
        exception=error if isinstance(error, Exception) else None,
        error_details={
            'path': request.path,
            'station_type': request.path.split('/')[-1] if '/' in request.path else 'unknown'
        }
    )

    return render_template(
        'stations/error.html',
        error_message="Błąd systemu",
        error_details="Wystąpił nieoczekiwany błąd. Spróbuj odświeżyć stronę.",
        back_url=url_for('production.production_stations.station_select')
    ), 500

# ============================================================================
# BEFORE/AFTER REQUEST HANDLERS
# ============================================================================

@station_bp.before_request
def log_station_access():
    """Loguje dostęp do interfejsów stanowisk"""
    try:
        from . import log_route_access
        log_route_access(request)
        
        # Dodatkowe logowanie dla interfejsów stanowisk
        logger.debug("Dostęp do interfejsu stanowiska", extra={
            'path': request.path,
            'method': request.method,
            'client_ip': request.remote_addr,
            'user_agent': request.headers.get('User-Agent', 'Unknown'),
            'endpoint': request.endpoint
        })
        
    except Exception as e:
        logger.error("Błąd logowania dostępu do stanowiska", extra={'error': str(e)})

@station_bp.after_request
def add_station_headers(response):
    """Dodaje nagłówki do odpowiedzi interfejsów stanowisk"""
    try:
        from . import apply_common_headers
        response = apply_common_headers(response)
        
        # Dodatkowe nagłówki dla interfejsów stanowisk
        response.headers['X-Station-Interface'] = '1.3.0'
        response.headers['X-Robots-Tag'] = 'noindex, nofollow'
        
        # Cache control dla interfejsów (nie cache'uj)
        if request.endpoint and 'ajax' not in request.endpoint:
            response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
            response.headers['Pragma'] = 'no-cache'
            response.headers['Expires'] = '0'
        
        return response
        
    except Exception as e:
        logger.error("Błąd dodawania nagłówków stanowiska", extra={'error': str(e)})
        return response

# ============================================================================
# CONTEXT PROCESSORS
# ============================================================================

@station_bp.context_processor
def inject_station_context():
    """
    Injektuje wspólny kontekst dla wszystkich templates stanowisk
    
    Returns:
        Dict[str, Any]: Kontekst dostępny w templates
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
        logger.error("Błąd context processor stanowiska", extra={'error': str(e)})
        return {
            'current_time': datetime.utcnow(),
            'current_date': date.today(),
            'station_version': '1.3.0',
            'client_ip': request.remote_addr or 'unknown'
        }

# ============================================================================
# HELPER FUNCTIONS DLA TEMPLATES
# ============================================================================

@station_bp.app_template_filter('format_priority')
def format_priority_filter(priority_rank):
    """
    Template filter dla formatowania priorytetu
    POPRAWKA: bazuje na priority_rank (niższy = lepszy)
    
    Args:
        priority_rank (int): Ranga priorytetu
        
    Returns:
        str: Sformatowany priorytet
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
    """
    Template filter dla formatowania deadline
    
    Args:
        deadline_date (date): Data deadline
        
    Returns:
        str: Sformatowany deadline
    """
    if not deadline_date:
        return "Brak terminu"
    
    if isinstance(deadline_date, str):
        try:
            deadline_date = datetime.strptime(deadline_date, '%Y-%m-%d').date()
        except ValueError:
            return "Nieprawidłowa data"
    
    days_diff = (deadline_date - date.today()).days
    
    if days_diff < 0:
        return f"⚠️ Opóźnione o {abs(days_diff)} dni"
    elif days_diff == 0:
        return "🔥 Dziś!"
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
    """
    Template filter dla formatowania objętości
    
    Args:
        volume_m3 (float): Objętość w m³
        
    Returns:
        str: Sformatowana objętość
    """
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
    """
    Template filter dla formatowania kwot
    
    Args:
        amount (float): Kwota
        
    Returns:
        str: Sformatowana kwota
    """
    if not amount:
        return "—"
    
    try:
        amount = float(amount)
        return f"{amount:,.2f} PLN".replace(",", " ")
    except (ValueError, TypeError):
        return "—"

@station_bp.app_template_filter('truncate_smart')
def truncate_smart_filter(text, length=50):
    """
    Template filter dla inteligentnego skracania tekstu
    
    Args:
        text (str): Tekst do skrócenia
        length (int): Maksymalna długość
        
    Returns:
        str: Skrócony tekst
    """
    if not text or len(text) <= length:
        return text
    
    # Spróbuj skrócić na granicy słowa
    truncated = text[:length]
    last_space = truncated.rfind(' ')
    
    if last_space > length * 0.75:
        return truncated[:last_space] + "..."
    else:
        return truncated + "..."

# ============================================================================
# DEBUGGING I DEVELOPMENT HELPERS
# ============================================================================

@station_bp.route('/debug/station-info')
def debug_station_info():
    """
    Debug endpoint z informacjami o stanie stanowisk (tylko w trybie debug)
    
    Returns:
        JSON: Informacje debugowe
    """
    try:
        # Sprawdź czy debug jest włączony
        config = get_station_config()
        if not config.get('debug_frontend', False):
            return jsonify({
                'error': 'Debug mode is disabled'
            }), 403
        
        from ..services.security_service import IPSecurityService
        
        debug_info = {
            'timestamp': datetime.utcnow().isoformat(),
            'client_info': {
                'ip': request.remote_addr,
                'user_agent': request.headers.get('User-Agent'),
                'ip_allowed': IPSecurityService.is_ip_allowed(request.remote_addr)
            },
            'station_summary': get_station_summary(),
            'config': config,
            'request_info': {
                'method': request.method,
                'path': request.path,
                'endpoint': request.endpoint,
                'headers': dict(request.headers)
            }
        }
        
        return jsonify({
            'success': True,
            'debug_info': debug_info
        }), 200
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

# ============================================================================
# SHIPPING / COURIER API ENDPOINTS (2025-12)
# ============================================================================

@station_bp.route('/api/packaging/ship/<order_id>', methods=['POST'])
def create_shipment(order_id):
    """
    Tworzy przesyłkę kurierską dla zamówienia.

    Workflow z logowaniem:
    1. Pobierz produkty zamówienia
    2. Generuj warianty pakowania (lub użyj przekazanych wymiarów)
    3. Zapytaj GlobKurier o ceny
    4. Porównaj i wybierz najtańszą opcję
    5. Utwórz przesyłkę przez Baselinker
    6. Pobierz etykietę

    Request Body:
        {
            "length": int (cm),
            "width": int (cm),
            "height": int (cm),
            "weight": float (kg)
        }

    Returns:
        JSON: {
            success: bool,
            courier_name: str,
            service_name: str,
            price: float,
            tracking_number: str,
            package_id: int,
            label_base64: str
        }
        lub
        {
            success: false,
            failed_step: str,
            error: str
        }
    """
    logger.info(f"[Shipping] === ENDPOINT START: /api/packaging/ship/{order_id} ===")
    current_step = 'init'

    try:
        # Importy wewnątrz try-except żeby złapać błędy importu
        current_step = 'import'
        logger.debug("[Shipping] Importowanie modułów...")
        from ..models import ProductionItem
        from ..services.shipping_service import ShippingService
        from modules.baselinker.service import BaselinkerService
        logger.debug("[Shipping] Importy zakończone pomyślnie")

        current_step = 'dimensions'

        # Pobierz dane z requestu
        data = request.get_json() or {}
        dimensions = {
            'length': int(data.get('length', 0)),
            'width': int(data.get('width', 0)),
            'height': int(data.get('height', 0)),
            'weight': float(data.get('weight', 0))
        }

        logger.info(f"[Shipping] ===== START: Zamówienie {order_id} =====",
                   order_id=order_id,
                   dimensions=str(dimensions))

        logger.info(f"[Shipping] Wymiary: {dimensions['length']}x{dimensions['width']}x{dimensions['height']} cm, {dimensions['weight']} kg")

        # KROK 1: Pobierz produkty zamówienia
        logger.info(f"[Shipping] Krok: {current_step} - pobieranie produktów")

        products = ProductionItem.query.filter(
            ProductionItem.baselinker_order_id == str(order_id)
        ).all()

        if not products:
            # Spróbuj po internal_order_number
            products = ProductionItem.query.filter(
                ProductionItem.internal_order_number == str(order_id)
            ).all()

        if not products:
            raise ValueError(f"Nie znaleziono produktów dla zamówienia {order_id}")

        # Pobierz dane dostawy z pierwszego produktu
        first_product = products[0]
        receiver_postcode = first_product.delivery_postcode
        receiver_address = first_product.delivery_address
        receiver_city = first_product.delivery_city
        receiver_name = first_product.delivery_fullname
        receiver_country = first_product.delivery_country_code or 'PL'

        # Pobierz baselinker_order_id dla createPackage
        baselinker_order_id = first_product.baselinker_order_id

        logger.info(f"[Shipping] Odbiorca: {receiver_name}, {receiver_postcode} {receiver_city}",
                   receiver_postcode=receiver_postcode,
                   baselinker_order_id=baselinker_order_id)

        if not receiver_postcode:
            raise ValueError("Brak kodu pocztowego odbiorcy")

        # KROK 2: Generuj warianty pakowania (informacyjnie)
        current_step = 'variants'
        logger.info(f"[Shipping] Krok: {current_step} - generowanie wariantów")

        shipping_service = ShippingService()
        variants = shipping_service.generate_packaging_variants(products)
        valid_variants = [v for v in variants if v['valid']]

        logger.info(f"[Shipping] Wygenerowano {len(variants)} wariantów, {len(valid_variants)} prawidłowych")

        # KROK 3: Zapytaj GlobKurier o ceny
        current_step = 'prices'
        logger.info(f"[Shipping] Krok: {current_step} - pobieranie cen z GlobKurier")

        # Użyj wymiarów podanych przez użytkownika
        quotes = shipping_service.get_quotes_for_package(
            package=dimensions,
            receiver_postcode=receiver_postcode,
            sender_postcode='36-068'  # Bachórz
        )

        logger.info(f"[Shipping] Otrzymano {len(quotes)} ofert od GlobKurier")

        if not quotes:
            raise ValueError("Nie znaleziono dostępnych ofert kurierskich")

        # KROK 4: Porównaj i wybierz najtańszą
        current_step = 'compare'
        logger.info(f"[Shipping] Krok: {current_step} - porównywanie ofert")

        # Już przefiltrowane w get_quotes_for_package (bez automatów)
        if not quotes:
            raise ValueError("Brak ofert kurierskich door-to-door (tylko automaty paczkowe)")

        # Sortuj po cenie
        cheapest = min(quotes, key=lambda x: x.get('price', float('inf')))

        logger.info(f"[Shipping] Najtańsza oferta: {cheapest.get('courier_name')} - {cheapest.get('service_name')} = {cheapest.get('price')} zł")

        # KROK 5: Utwórz przesyłkę przez Baselinker
        current_step = 'create'
        logger.info(f"[Shipping] Krok: {current_step} - tworzenie przesyłki w Baselinker")

        # Mapowanie nazw kurierów z GlobKurier API na kody dla Baselinker
        # Bazowane na getCourierFields -> pole "courier" -> options
        COURIER_NAME_TO_CODE = {
            'inpost': 'inpost',
            'inpost-kurier': 'inpost',
            'dpd': 'dpd',
            'dhl': 'dhl',
            'dhl de': 'dhl-de',
            'dhl pop': 'dhl pop',
            'gls': 'gls',
            'ups': 'ups',
            'fedex': 'fedex',
            'poczta polska': 'poczta',
            'poczta': 'poczta',
            'ambro': 'ambro',
            'ambroexpress': 'ambro',
            'globkurier': 'Globkurier',
            'geodis': 'GEODIS',
            'hellmann': 'Hellmann',
            'cargus': 'cargus',
            'orlen paczka': 'ruch',
            'ruch': 'ruch',
            'postnord': 'PostNord',
            'spring': 'Spring',
            'colissimo': 'Colissimo',
        }

        # Znajdź kod kuriera na podstawie nazwy
        courier_name_lower = (cheapest.get('courier_name') or '').lower().strip()
        selected_courier_code = COURIER_NAME_TO_CODE.get(courier_name_lower)

        # Jeśli nie znaleziono bezpośrednio, spróbuj częściowego dopasowania
        if not selected_courier_code:
            for name_part, code in COURIER_NAME_TO_CODE.items():
                if name_part in courier_name_lower or courier_name_lower in name_part:
                    selected_courier_code = code
                    break

        if not selected_courier_code:
            raise ValueError(f"Nie można zmapować kuriera '{cheapest.get('courier_name')}' na kod Baselinker")

        logger.info(f"[Shipping] Zmapowano kuriera: '{cheapest.get('courier_name')}' -> '{selected_courier_code}'")

        # Oblicz łączną wartość netto zamówienia (suma total_value_net wszystkich produktów)
        total_order_value = sum(
            float(p.total_value_net or 0) for p in products
        )
        logger.info(f"[Shipping] Łączna wartość netto zamówienia: {total_order_value} PLN")

        # Oblicz datę odbioru: dzisiaj jeśli przed 14:00, jutro jeśli po 14:00
        now = datetime.now()
        cutoff_hour = 14

        if now.hour < cutoff_hour:
            pickup_date = now.date()
        else:
            pickup_date = (now + timedelta(days=1)).date()

        # Format daty jako timestamp Unix (wymagany przez Baselinker)
        pickup_timestamp = int(datetime.combine(pickup_date, datetime.min.time()).timestamp())
        logger.info(f"[Shipping] Data odbioru: {pickup_date} (timestamp: {pickup_timestamp}), godzina zgłoszenia: {now.hour}:{now.minute}")

        package_fields = [
            {'id': 'courier', 'value': selected_courier_code},  # Kod kuriera z mapowania (np. 'inpost', 'dpd')
            {'id': 'count_package', 'value': '1'},
            {'id': 'reference_number', 'value': str(baselinker_order_id)},
            {'id': 'package_description', 'value': 'Klejonka drewniana'},
            {'id': 'value_price', 'value': str(round(total_order_value, 2))},
            {'id': 'pickup_date', 'value': str(pickup_timestamp)},
        ]

        # Tablica paczek z wymiarami
        packages_data = [
            {
                'weight': float(dimensions['weight']),
                'height': int(dimensions['height']),
                'length': int(dimensions['length']),
                'width': int(dimensions['width'])
            }
        ]

        logger.info(f"[Shipping] Pola dla createPackage: {package_fields}")
        logger.info(f"[Shipping] Paczki: {packages_data}")

        baselinker = BaselinkerService()
        package_result = baselinker.create_package(
            order_id=int(baselinker_order_id),
            courier_code='globkurier',
            account_id=11364,
            fields=package_fields,
            packages=packages_data
        )

        if not package_result.get('success'):
            raise ValueError(f"Błąd Baselinker: {package_result.get('error', 'Nieznany błąd')}")

        package_id = package_result.get('package_id')
        tracking_number = package_result.get('courier_package_nr', '')

        logger.info(f"[Shipping] Utworzono przesyłkę: package_id={package_id}, tracking={tracking_number}")

        # KROK 6: Pobierz etykietę
        current_step = 'label'
        logger.info(f"[Shipping] Krok: {current_step} - pobieranie etykiety")

        label_result = baselinker.get_label(
            courier_code='globkurier',
            package_id=package_id
        )

        if not label_result.get('success'):
            logger.warning(f"[Shipping] Nie udało się pobrać etykiety: {label_result.get('error')}")
            label_base64 = ''
        else:
            label_base64 = label_result.get('label', '')

        logger.info(f"[Shipping] Pobrano etykietę, rozmiar: {len(label_base64)} znaków")

        # KROK 7: Zapisz dane wysyłki w bazie danych
        current_step = 'save'
        logger.info(f"[Shipping] Krok: {current_step} - zapisywanie danych wysyłki w bazie")

        shipping_price = cheapest.get('price', 0)
        courier_name = cheapest.get('courier_name', '')

        # Zapisz dane wysyłki dla wszystkich produktów w zamówieniu
        for product in products:
            product.shipping_package_id = package_id
            product.shipping_tracking_number = tracking_number
            product.shipping_courier_name = courier_name
            product.shipping_price = shipping_price
            product.shipping_label_base64 = label_base64
            product.shipping_created_at = datetime.now()

        db.session.commit()
        logger.info(f"[Shipping] Zapisano dane wysyłki dla {len(products)} produktów")
        logger.info(f"[Shipping] ===== SUKCES: Zamówienie {order_id} =====")

        return jsonify({
            'success': True,
            'courier_name': courier_name,
            'service_name': cheapest.get('service_name'),
            'price': shipping_price,
            'tracking_number': tracking_number,
            'package_id': package_id,
            'label_base64': label_base64
        }), 200

    except Exception as e:
        logger.error(f"[Shipping] BŁĄD w kroku '{current_step}': {str(e)}",
                    order_id=order_id,
                    current_step=current_step,
                    error=str(e),
                    traceback_info=traceback.format_exc())

        return jsonify({
            'success': False,
            'failed_step': current_step,
            'error': str(e)
        }), 200  # 200 bo frontend oczekuje JSON z błędem


@station_bp.route('/api/packaging/check-shipping/<order_id>')
def check_shipping_availability(order_id):
    """
    Sprawdza czy zamówienie może być wysłane kurierem.

    Returns:
        JSON: {
            can_ship: bool,
            is_personal_pickup: bool,
            dimensions: {...},
            within_limits: bool,
            limit_issues: [...]
        }
    """
    try:
        from ..models import ProductionItem
        from ..services.shipping_service import ShippingService

        products = ProductionItem.query.filter(
            ProductionItem.baselinker_order_id == str(order_id)
        ).all()

        if not products:
            products = ProductionItem.query.filter(
                ProductionItem.internal_order_number == str(order_id)
            ).all()

        if not products:
            return jsonify({
                'success': False,
                'error': f'Nie znaleziono produktów dla zamówienia {order_id}'
            }), 404

        first_product = products[0]

        # Sprawdź typ dostawy
        is_pickup = first_product.is_personal_pickup

        if is_pickup:
            return jsonify({
                'success': True,
                'can_ship': False,
                'is_personal_pickup': True,
                'reason': 'Zamówienie przeznaczone do odbioru osobistego'
            }), 200

        # Oblicz wymiary
        shipping_service = ShippingService()
        dimensions = shipping_service.calculate_package_dimensions(products)

        can_ship = dimensions['within_limits']

        return jsonify({
            'success': True,
            'can_ship': can_ship,
            'is_personal_pickup': False,
            'dimensions': dimensions,
            'within_limits': dimensions['within_limits'],
            'limit_issues': dimensions.get('limit_issues', [])
        }), 200

    except Exception as e:
        logger.error("[Shipping] Błąd sprawdzania dostępności wysyłki", extra={
            'order_id': order_id,
            'error': str(e)
        })

        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@station_bp.route('/api/packaging/quote/<order_id>', methods=['POST'])
def get_shipping_quote(order_id):
    """
    Pobiera wycenę przesyłki BEZ jej tworzenia.
    Zwraca najlepszą opcję (single lub multi-package).

    Request Body:
        {
            "length": int (cm),
            "width": int (cm),
            "height": int (cm),
            "weight": float (kg)
        }

    Returns:
        JSON: {
            success: bool,
            quote: {
                courier_name: str,
                service_name: str,
                price: float,
                is_multi_package: bool,
                total_packages: int,
                packages: [...]  // szczegóły każdej paczki jeśli multi
            }
        }
    """
    logger.info(f"[Shipping] === GET QUOTE: /api/packaging/quote/{order_id} ===")

    try:
        from ..models import ProductionItem
        from ..services.shipping_service import ShippingService

        # Pobierz dane z requestu
        data = request.get_json() or {}
        dimensions = {
            'length': int(data.get('length', 0)),
            'width': int(data.get('width', 0)),
            'height': int(data.get('height', 0)),
            'weight': float(data.get('weight', 0))
        }

        logger.info(f"[Shipping] Wymiary dla wyceny: {dimensions}")

        # Walidacja wymiarów
        if dimensions['length'] <= 0 or dimensions['width'] <= 0 or dimensions['height'] <= 0 or dimensions['weight'] <= 0:
            return jsonify({
                'success': False,
                'error': 'Nieprawidłowe wymiary paczki'
            }), 400

        # Pobierz produkty zamówienia
        products = ProductionItem.query.filter(
            ProductionItem.baselinker_order_id == str(order_id)
        ).all()

        if not products:
            products = ProductionItem.query.filter(
                ProductionItem.internal_order_number == str(order_id)
            ).all()

        if not products:
            return jsonify({
                'success': False,
                'error': f'Nie znaleziono produktów dla zamówienia {order_id}'
            }), 404

        first_product = products[0]
        receiver_postcode = first_product.delivery_postcode

        if not receiver_postcode:
            return jsonify({
                'success': False,
                'error': 'Brak kodu pocztowego odbiorcy'
            }), 400

        # Inicjalizacja ShippingService
        shipping_service = ShippingService()

        # Pobierz wyceny dla podanych wymiarów (pojedyncza paczka)
        quotes = shipping_service.get_quotes_for_package(
            package=dimensions,
            receiver_postcode=receiver_postcode,
            sender_postcode='36-068'
        )

        if not quotes:
            return jsonify({
                'success': False,
                'error': 'Brak dostępnych ofert kurierskich dla tych wymiarów'
            }), 400

        # Znajdź najtańszą opcję
        cheapest = min(quotes, key=lambda x: x.get('price', float('inf')))

        logger.info(f"[Shipping] Najtańsza oferta: {cheapest.get('courier_name')} - {cheapest.get('service_name')} = {cheapest.get('price')} zł")

        # Przygotuj odpowiedź
        quote_response = {
            'courier_name': cheapest.get('courier_name', 'Nieznany'),
            'service_name': cheapest.get('service_name', ''),
            'price': cheapest.get('price', 0),
            'service_id': cheapest.get('service_id', ''),
            'is_multi_package': False,
            'total_packages': 1,
            'packages': [{
                'length': dimensions['length'],
                'width': dimensions['width'],
                'height': dimensions['height'],
                'weight': dimensions['weight'],
                'courier_name': cheapest.get('courier_name'),
                'price': cheapest.get('price')
            }]
        }

        return jsonify({
            'success': True,
            'quote': quote_response
        }), 200

    except Exception as e:
        logger.error(f"[Shipping] Błąd pobierania wyceny: {str(e)}")
        import traceback
        logger.debug(f"[Shipping] Stack trace: {traceback.format_exc()}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@station_bp.route('/api/packaging/refresh-tracking/<order_id>')
def refresh_tracking_number(order_id):
    """
    Pobiera i aktualizuje numer śledzenia z Baselinker (getOrderPackages).
    GlobKurier może nie zwracać numeru tracking od razu - trzeba odpytać później.

    Returns:
        JSON: {
            success: bool,
            tracking_number: str,
            tracking_url: str
        }
    """
    try:
        from ..models import ProductionItem
        from modules.baselinker.service import BaselinkerService

        logger.info(f"[Shipping] Odświeżanie numeru śledzenia dla zamówienia {order_id}")

        # Znajdź produkty zamówienia
        products = ProductionItem.query.filter(
            ProductionItem.baselinker_order_id == str(order_id)
        ).all()

        if not products:
            products = ProductionItem.query.filter(
                ProductionItem.internal_order_number == str(order_id)
            ).all()

        if not products:
            return jsonify({
                'success': False,
                'error': f'Nie znaleziono produktów dla zamówienia {order_id}'
            }), 404

        # Pobierz baselinker_order_id
        baselinker_order_id = products[0].baselinker_order_id
        if not baselinker_order_id:
            return jsonify({
                'success': False,
                'error': 'Brak baselinker_order_id dla tego zamówienia'
            }), 400

        # Pobierz paczki z Baselinker
        baselinker = BaselinkerService()
        result = baselinker.get_order_packages(int(baselinker_order_id))

        if not result.get('success'):
            return jsonify({
                'success': False,
                'error': result.get('error', 'Błąd pobierania paczek z Baselinker')
            }), 500

        packages = result.get('packages', [])

        if not packages:
            return jsonify({
                'success': True,
                'tracking_number': '',
                'tracking_url': '',
                'message': 'Brak paczek dla tego zamówienia'
            }), 200

        # Znajdź paczkę z numerem śledzenia (pierwsza z listy)
        package = packages[0]
        tracking_number = package.get('courier_package_nr', '')
        tracking_url = package.get('tracking_url', '')

        logger.info(f"[Shipping] Pobrano numer śledzenia: {tracking_number}")

        # Aktualizuj w bazie danych jeśli jest numer
        if tracking_number:
            for product in products:
                product.shipping_tracking_number = tracking_number

            db.session.commit()
            logger.info(f"[Shipping] Zaktualizowano numer śledzenia dla {len(products)} produktów")

        return jsonify({
            'success': True,
            'tracking_number': tracking_number,
            'tracking_url': tracking_url,
            'package_id': package.get('package_id'),
            'courier_code': package.get('courier_code')
        }), 200

    except Exception as e:
        logger.error(f"[Shipping] Błąd odświeżania numeru śledzenia: {str(e)}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@station_bp.route('/api/packaging/refresh-label/<order_id>')
def refresh_label(order_id):
    """
    Ponownie pobiera etykietę z Baselinker i aktualizuje w bazie danych.
    Używane gdy etykieta została obcięta lub uszkodzona.

    Returns:
        JSON: {
            success: bool,
            label_base64: str,
            label_size: int
        }
    """
    try:
        from ..models import ProductionItem
        from modules.baselinker.service import BaselinkerService

        logger.info(f"[Shipping] Ponowne pobieranie etykiety dla zamówienia {order_id}")

        # Znajdź produkty zamówienia
        products = ProductionItem.query.filter(
            ProductionItem.baselinker_order_id == str(order_id)
        ).all()

        if not products:
            products = ProductionItem.query.filter(
                ProductionItem.internal_order_number == str(order_id)
            ).all()

        if not products:
            return jsonify({
                'success': False,
                'error': f'Nie znaleziono produktów dla zamówienia {order_id}'
            }), 404

        first_product = products[0]

        # Sprawdź czy mamy package_id
        package_id = first_product.shipping_package_id
        if not package_id:
            return jsonify({
                'success': False,
                'error': 'Brak package_id - przesyłka nie została jeszcze zgłoszona'
            }), 400

        # Pobierz etykietę z Baselinker
        baselinker = BaselinkerService()
        label_result = baselinker.get_label(
            courier_code='globkurier',
            package_id=package_id
        )

        if not label_result.get('success'):
            return jsonify({
                'success': False,
                'error': f"Błąd pobierania etykiety: {label_result.get('error')}"
            }), 500

        label_base64 = label_result.get('label', '')
        label_size = len(label_base64)

        logger.info(f"[Shipping] Pobrano etykietę, rozmiar: {label_size} znaków")

        # Aktualizuj w bazie danych
        for product in products:
            product.shipping_label_base64 = label_base64

        db.session.commit()
        logger.info(f"[Shipping] Zaktualizowano etykietę dla {len(products)} produktów")

        return jsonify({
            'success': True,
            'label_base64': label_base64,
            'label_size': label_size,
            'message': f'Etykieta pobrana pomyślnie ({label_size} znaków)'
        }), 200

    except Exception as e:
        logger.error(f"[Shipping] Błąd ponownego pobierania etykiety: {str(e)}")
        import traceback
        logger.debug(f"[Shipping] Stack trace: {traceback.format_exc()}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@station_bp.route('/api/packaging/debug/courier-fields')
def debug_courier_fields():
    """
    Endpoint debugowy - pobiera pola formularza dla GlobKurier.
    Użyj w przeglądarce: /production/stations/api/packaging/debug/courier-fields
    """
    try:
        from modules.baselinker.service import BaselinkerService

        baselinker = BaselinkerService()
        result = baselinker.get_courier_fields('globkurier')

        return jsonify(result), 200

    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@station_bp.route('/api/packaging/debug/courier-accounts')
def debug_courier_accounts():
    """
    Endpoint debugowy - pobiera konta kurierskie.
    Użyj w przeglądarce: /production/stations/api/packaging/debug/courier-accounts
    """
    try:
        from modules.baselinker.service import BaselinkerService

        baselinker = BaselinkerService()
        response = baselinker._make_request('getCourierAccounts', {})

        return jsonify(response), 200

    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


logger.info("Zainicjalizowano Station routers dla modułu production", extra={
    'blueprint_name': station_bp.name,
    'version': '1.3.0',
    'protected_by_ip': True,
    'tablet_optimized': True,
    'priority_system': 'priority_rank'
})