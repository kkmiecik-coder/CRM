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
            
            # Formatowanie wymiarów w MM
            dimensions_text = ''
            if all([product.parsed_length_cm, product.parsed_width_cm, product.parsed_thickness_cm]):
                dimensions_text = f"{int(product.parsed_length_cm * 10)} × {int(product.parsed_width_cm * 10)} × {int(product.parsed_thickness_cm * 10)} mm"
            
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
# ROUTERS - STANOWISKO WYCINANIA
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
        orders_with_cutting = db.session.query(
            ProductionItem.internal_order_number
        ).filter(
            ProductionItem.current_status == 'czeka_na_wyciecie'
        ).distinct().all()

        order_numbers = [order[0] for order in orders_with_cutting if order[0]]

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

                # Wymiary w MM (mnożymy przez 10)
                dimensions_parts = []
                if product.parsed_length_cm:
                    dimensions_parts.append(str(int(product.parsed_length_cm * 10)))
                if product.parsed_width_cm:
                    dimensions_parts.append(str(int(product.parsed_width_cm * 10)))
                if product.parsed_thickness_cm:
                    dimensions_parts.append(str(int(product.parsed_thickness_cm * 10)))
                dimensions_text = '×'.join(dimensions_parts) + ' mm' if dimensions_parts else None

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
                    'product_sequence_in_order': product.product_sequence_in_order
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
                    'products': [],
                    'total_products': 0,
                    'total_volume': 0,
                    'best_priority_rank': 999,
                    'worst_deadline': None
                }

            order = orders_grouped[order_number]
            order['products'].append(product)
            order['total_products'] += 1
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

        # Statystyki stanowiska
        total_products = sum(order['total_products'] for order in orders_list)
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
        orders_with_assembly = db.session.query(
            ProductionItem.internal_order_number
        ).filter(
            ProductionItem.current_status == 'czeka_na_skladanie'
        ).distinct().all()

        order_numbers = [order[0] for order in orders_with_assembly if order[0]]

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

                # Wymiary w MM (mnożymy przez 10)
                dimensions_parts = []
                if product.parsed_length_cm:
                    dimensions_parts.append(str(int(product.parsed_length_cm * 10)))
                if product.parsed_width_cm:
                    dimensions_parts.append(str(int(product.parsed_width_cm * 10)))
                if product.parsed_thickness_cm:
                    dimensions_parts.append(str(int(product.parsed_thickness_cm * 10)))
                dimensions_text = '×'.join(dimensions_parts) + ' mm' if dimensions_parts else None

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
                    'product_sequence_in_order': product.product_sequence_in_order
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
                    'products': [],
                    'total_products': 0,
                    'total_volume': 0,
                    'best_priority_rank': 999,
                    'worst_deadline': None
                }

            order = orders_grouped[order_number]
            order['products'].append(product)
            order['total_products'] += 1
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

        # Statystyki stanowiska
        total_products = sum(order['total_products'] for order in orders_list)
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

                # Wymiary w MM (mnożymy przez 10)
                dimensions_parts = []
                if product.parsed_length_cm:
                    dimensions_parts.append(str(int(product.parsed_length_cm * 10)))
                if product.parsed_width_cm:
                    dimensions_parts.append(str(int(product.parsed_width_cm * 10)))
                if product.parsed_thickness_cm:
                    dimensions_parts.append(str(int(product.parsed_thickness_cm * 10)))
                dimensions_text = '×'.join(dimensions_parts) + ' mm' if dimensions_parts else None

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
                    'product_sequence_in_order': product.product_sequence_in_order
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
                    'products': [],
                    'total_products': 0,
                    'total_volume': 0,
                    'best_priority_rank': 999,
                    'worst_deadline': None
                }

            order = orders_grouped[order_number]
            order['products'].append(product)
            order['total_products'] += 1
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

        # Statystyki stanowiska
        total_products = sum(order['total_products'] for order in orders_list)
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

                # Wymiary w MM (mnożymy przez 10)
                dimensions_parts = []
                if product.parsed_length_cm:
                    dimensions_parts.append(str(int(product.parsed_length_cm * 10)))
                if product.parsed_width_cm:
                    dimensions_parts.append(str(int(product.parsed_width_cm * 10)))
                if product.parsed_thickness_cm:
                    dimensions_parts.append(str(int(product.parsed_thickness_cm * 10)))
                dimensions_text = '×'.join(dimensions_parts) + ' mm' if dimensions_parts else None

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
                    'product_sequence_in_order': product.product_sequence_in_order
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
                    'products': [],
                    'total_products': 0,
                    'total_volume': 0,
                    'best_priority_rank': 999,
                    'worst_deadline': None
                }

            order = orders_grouped[order_number]
            order['products'].append(product)
            order['total_products'] += 1
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

        # Statystyki stanowiska
        total_products = sum(order['total_products'] for order in orders_list)
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

                # Wymiary w MM (mnożymy przez 10)
                dimensions_parts = []
                if product.parsed_length_cm:
                    dimensions_parts.append(str(int(product.parsed_length_cm * 10)))
                if product.parsed_width_cm:
                    dimensions_parts.append(str(int(product.parsed_width_cm * 10)))
                if product.parsed_thickness_cm:
                    dimensions_parts.append(str(int(product.parsed_thickness_cm * 10)))
                dimensions_text = '×'.join(dimensions_parts) + ' mm' if dimensions_parts else None

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
                    'product_sequence_in_order': product.product_sequence_in_order
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
                    'products': [],
                    'total_products': 0,
                    'total_volume': 0,
                    'best_priority_rank': 999,
                    'worst_deadline': None
                }

            order = orders_grouped[order_number]
            order['products'].append(product)
            order['total_products'] += 1
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

        # Statystyki stanowiska
        total_products = sum(order['total_products'] for order in orders_list)
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
                
                # Wymiary w MM (mnożymy przez 10)
                dimensions_parts = []
                if product.parsed_length_cm:
                    dimensions_parts.append(str(int(product.parsed_length_cm * 10)))  # ×10
                if product.parsed_width_cm:
                    dimensions_parts.append(str(int(product.parsed_width_cm * 10)))   # ×10
                if product.parsed_thickness_cm:
                    dimensions_parts.append(str(int(product.parsed_thickness_cm * 10))) # ×10
                dimensions_text = '×'.join(dimensions_parts) + ' mm' if dimensions_parts else 'Brak wymiarów'
                
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
                    'products': [],
                    'total_products': 0,
                    'total_volume': 0,
                    'total_value': 0,
                    'best_priority_rank': 999,
                    'earliest_deadline': None,
                    'has_overdue': False,
                    'priority_label': 'Niski',
                    'priority_class': 'priority-low',
                    'display_deadline': 'Brak'
                }
            
            order = orders_grouped[order_number]
            order['products'].append(product)
            order['total_products'] += 1
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
        
        # Statystyki stanowiska
        total_products = len(products)
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
    
@station_bp.route('/ajax/orders/packaging')
def ajax_get_orders_packaging():
    """
    AJAX endpoint dla odświeżania ZAMÓWIEŃ na stanowisku pakowania
    
    RÓŻNICA od ajax_get_products:
    - Zwraca ZAMÓWIENIA (grouped) zamiast płaskiej listy produktów
    - Struktura identyczna z initial server-side render
    
    Query params:
        sort: priority|deadline|created_at (default: priority)
        limit: max liczba produktów (default: 50)
        
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
        limit = min(int(request.args.get('limit', 50)), 100)
        
        logger.debug("AJAX: Pobieranie zamówień packaging", extra={
            'sort_by': sort_by,
            'limit': limit,
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
        
        products = query.limit(limit).all()
        
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
                    'ready_count': 0,
                    'not_ready_count': 0,
                    'total_volume': 0,
                    'best_priority_rank': 999,
                    'worst_deadline': None
                }
            
            # Dodaj produkt do zamówienia
            product_data = {
                'id': product.short_product_id,
                'original_name': product.original_product_name or 'Brak nazwy',
                'volume_m3': float(product.volume_m3 or 0),
                'current_status': product.current_status,
                'priority_rank': product.priority_rank or 999,
                'deadline_date': product.deadline_date.isoformat() if product.deadline_date else None
            }
            
            orders_grouped[order_num]['products'].append(product_data)
            orders_grouped[order_num]['total_products'] += 1
            orders_grouped[order_num]['total_volume'] += float(product.volume_m3 or 0)

            # ✅ DODAJ TO: Weź baselinker_order_id z pierwszego produktu który go ma
            if not orders_grouped[order_num]['baselinker_order_id'] and product.baselinker_order_id:
                orders_grouped[order_num]['baselinker_order_id'] = product.baselinker_order_id
            
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

        # KROK 1: Znajdź zamówienia które mają choć 1 produkt do wycięcia
        orders_with_cutting = db.session.query(
            ProductionItem.internal_order_number
        ).filter(
            ProductionItem.current_status == 'czeka_na_wyciecie'
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
                'attachment_file_url': product.attachment_file_url
            }

            # Oblicz wymiary z parsowanych pól (w MM z jednostką)
            if product.parsed_length_cm and product.parsed_width_cm and product.parsed_thickness_cm:
                product_data['dimensions'] = f"{int(product.parsed_length_cm * 10)} × {int(product.parsed_width_cm * 10)} × {int(product.parsed_thickness_cm * 10)} mm"

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

    IDENTYCZNA LOGIKA jak cutting, ale dla statusu 'czeka_na_skladanie'

    Query params:
        sort: priority|deadline|created_at (default: priority)
        limit: max liczba produktów (default: 50)

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
        limit = min(int(request.args.get('limit', 50)), 100)

        logger.debug("AJAX: Pobieranie zamówień assembly", extra={
            'sort_by': sort_by,
            'limit': limit,
            'client_ip': request.remote_addr
        })

        # KROK 1: Znajdź zamówienia które mają choć 1 produkt do składania
        orders_with_assembly = db.session.query(
            ProductionItem.internal_order_number
        ).filter(
            ProductionItem.current_status == 'czeka_na_skladanie'
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

        products = query.limit(limit).all()

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
                'attachment_file_url': product.attachment_file_url
            }

            # Oblicz wymiary z parsowanych pól (w MM z jednostką)
            if product.parsed_length_cm and product.parsed_width_cm and product.parsed_thickness_cm:
                product_data['dimensions'] = f"{int(product.parsed_length_cm * 10)} × {int(product.parsed_width_cm * 10)} × {int(product.parsed_thickness_cm * 10)} mm"

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
    """
    AJAX endpoint dla odświeżania ZAMÓWIEŃ na stanowisku sklejania

    Query params:
        sort: priority|deadline|created_at (default: priority)
        limit: max liczba produktów (default: 50)

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
        limit = min(int(request.args.get('limit', 50)), 100)

        logger.debug("AJAX: Pobieranie zamówień gluing", extra={
            'sort_by': sort_by,
            'limit': limit,
            'client_ip': request.remote_addr
        })

        # KROK 1: Znajdź zamówienia które mają choć 1 produkt do sklejania
        orders_with_gluing = db.session.query(
            ProductionItem.internal_order_number
        ).filter(
            ProductionItem.current_status == 'czeka_na_sklejanie'
        ).distinct().all()

        order_numbers = [order[0] for order in orders_with_gluing]

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

        products = query.limit(limit).all()

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
                'attachment_file_url': product.attachment_file_url
            }

            # Oblicz wymiary z parsowanych pól (w MM z jednostką)
            if product.parsed_length_cm and product.parsed_width_cm and product.parsed_thickness_cm:
                product_data['dimensions'] = f"{int(product.parsed_length_cm * 10)} × {int(product.parsed_width_cm * 10)} × {int(product.parsed_thickness_cm * 10)} mm"

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
        logger.error("Błąd AJAX orders gluing", extra={
            'error': str(e),
            'traceback': traceback.format_exc()
        })

        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@station_bp.route('/ajax/orders/formatting')
def ajax_get_orders_formatting():
    """
    AJAX endpoint dla odświeżania ZAMÓWIEŃ na stanowisku formatowania

    Query params:
        sort: priority|deadline|created_at (default: priority)
        limit: max liczba produktów (default: 50)

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
        limit = min(int(request.args.get('limit', 50)), 100)

        logger.debug("AJAX: Pobieranie zamówień formatting", extra={
            'sort_by': sort_by,
            'limit': limit,
            'client_ip': request.remote_addr
        })

        # KROK 1: Znajdź zamówienia które mają choć 1 produkt do formatowania
        orders_with_formatting = db.session.query(
            ProductionItem.internal_order_number
        ).filter(
            ProductionItem.current_status == 'czeka_na_formatowanie'
        ).distinct().all()

        order_numbers = [order[0] for order in orders_with_formatting]

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

        products = query.limit(limit).all()

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
                'attachment_file_url': product.attachment_file_url
            }

            # Oblicz wymiary z parsowanych pól (w MM z jednostką)
            if product.parsed_length_cm and product.parsed_width_cm and product.parsed_thickness_cm:
                product_data['dimensions'] = f"{int(product.parsed_length_cm * 10)} × {int(product.parsed_width_cm * 10)} × {int(product.parsed_thickness_cm * 10)} mm"

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
        logger.error("Błąd AJAX orders formatting", extra={
            'error': str(e),
            'traceback': traceback.format_exc()
        })

        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@station_bp.route('/ajax/orders/finishing')
def ajax_get_orders_finishing():
    """
    AJAX endpoint dla odświeżania ZAMÓWIEŃ na stanowisku wykańczania

    Query params:
        sort: priority|deadline|created_at (default: priority)
        limit: max liczba produktów (default: 50)

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
        limit = min(int(request.args.get('limit', 50)), 100)

        logger.debug("AJAX: Pobieranie zamówień finishing", extra={
            'sort_by': sort_by,
            'limit': limit,
            'client_ip': request.remote_addr
        })

        # KROK 1: Znajdź zamówienia które mają choć 1 produkt do wykańczania
        orders_with_finishing = db.session.query(
            ProductionItem.internal_order_number
        ).filter(
            ProductionItem.current_status == 'czeka_na_wykanczanie'
        ).distinct().all()

        order_numbers = [order[0] for order in orders_with_finishing]

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

        products = query.limit(limit).all()

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
                'attachment_file_url': product.attachment_file_url
            }

            # Oblicz wymiary z parsowanych pól (w MM z jednostką)
            if product.parsed_length_cm and product.parsed_width_cm and product.parsed_thickness_cm:
                product_data['dimensions'] = f"{int(product.parsed_length_cm * 10)} × {int(product.parsed_width_cm * 10)} × {int(product.parsed_thickness_cm * 10)} mm"

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
        logger.error("Błąd AJAX orders finishing", extra={
            'error': str(e),
            'traceback': traceback.format_exc()
        })

        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

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
        expected_status_map = {
            'cutting': 'czeka_na_wyciecie',
            'assembly': 'czeka_na_skladanie',
            'gluing': 'czeka_na_sklejanie',
            'formatting': 'czeka_na_formatowanie',
            'finishing': 'czeka_na_wykanczanie',
            'packaging': 'czeka_na_pakowanie'
        }
        expected_status = expected_status_map[station]

        invalid_products = []
        for product in products:
            if product.current_status != expected_status:
                invalid_products.append({
                    'id': product.short_product_id,
                    'current_status': product.current_status,
                    'expected_status': expected_status
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

logger.info("Zainicjalizowano Station routers dla modułu production", extra={
    'blueprint_name': station_bp.name,
    'version': '1.3.0',
    'protected_by_ip': True,
    'tablet_optimized': True,
    'priority_system': 'priority_rank'
})