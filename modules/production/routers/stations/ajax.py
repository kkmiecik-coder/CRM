# modules/production/routers/stations/ajax.py
"""
AJAX data endpoints for station interfaces
"""

from flask import request, jsonify
from flask_login import current_user, login_required
from datetime import datetime, date
from extensions import db
from sqlalchemy.orm import joinedload
from ...services.station_heartbeat import record_heartbeat
from ...services import label_print_service
from ...services.label_print_service import StationNotAllowed
from ...models import ProductionItem, ProductionOrder, ProductionProduct
import traceback

from . import station_bp, logger, get_products_for_station, _format_dimension, _ajax_get_orders_simple


# ============================================================================
# AJAX ENDPOINTS DLA INTERFEJSOW STANOWISK
# ============================================================================

@station_bp.route('/ajax/products/<station_code>')
def ajax_get_products(station_code):
    """
    AJAX endpoint dla odswiezania listy produktow

    Args:
        station_code: cutting|assembly|packaging

    Query params:
        sort: priority|deadline|created_at
        limit: max liczba produktow

    Returns:
        JSON: Lista produktow
    """
    try:
        if station_code not in ['cutting', 'assembly', 'finishing', 'painting', 'packaging']:
            return jsonify({
                'success': False,
                'error': 'Invalid station code'
            }), 400

        record_heartbeat(station_code)
        sort_by = request.args.get('sort', 'priority')
        limit = min(int(request.args.get('limit', 50)), 100)

        # Pobranie produktow
        products = get_products_for_station(station_code, limit, sort_by)

        # Statystyki - POPRAWKA: priority_rank zamiast priority_score
        total_products = len(products)
        high_priority_count = sum(1 for p in products if p['priority_rank'] <= 50)
        overdue_count = sum(1 for p in products if p['is_overdue'])
        total_volume = sum(p['volume_m3'] * p.get('quantity', 1) for p in products)

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

        return jsonify(result), 200

    except Exception as e:
        logger.error("Blad AJAX pobierania produktow", extra={
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
    AJAX endpoint dla odswiezania podsumowania stanowisk

    Returns:
        JSON: Podsumowanie wszystkich stanowisk
    """
    try:
        from . import get_station_summary

        # Pobranie podsumowania
        summary = get_station_summary()

        result = {
            'success': True,
            'data': {
                'stations': summary,
                'last_updated': datetime.utcnow().isoformat()
            }
        }

        return jsonify(result), 200

    except Exception as e:
        logger.error("Blad AJAX podsumowania stanowisk", extra={'error': str(e)})

        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


# ============================================================================
# AJAX ORDERS ENDPOINTS
# ============================================================================

@station_bp.route('/ajax/orders/packaging')
def ajax_get_orders_packaging():
    """
    AJAX endpoint dla odswiezania ZAMOWIEN na stanowisku pakowania

    ROZNICA od ajax_get_products:
    - Zwraca ZAMOWIENIA (grouped) zamiast plaskiej listy produktow
    - Struktura identyczna z initial server-side render (bez limitu)

    Query params:
        sort: priority|deadline|created_at (default: priority)

    Returns:
        JSON: {
            success: bool,
            data: {
                orders: [...],
                stats: {...}
            }
        }
    """
    try:
        from ...models import ProductionItem, ProductionOrder, ProductionProduct
        from sqlalchemy import asc, desc

        sort_by = request.args.get('sort', 'priority')

        # KROK 1: Znajdz zamowienia ktore maja choc 1 produkt do pakowania
        orders_with_packaging = db.session.query(
            ProductionOrder.internal_order_number
        ).join(
            ProductionProduct, ProductionProduct.order_id == ProductionOrder.id
        ).filter(
            ProductionProduct.current_status == 'czeka_na_pakowanie'
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

        # KROK 2: Pobierz WSZYSTKIE produkty z tych zamowien (bez limitu)
        query = (
            ProductionProduct.query
            .options(
                joinedload(ProductionProduct.order),
                joinedload(ProductionProduct.configuration),
            )
            .join(ProductionOrder)
            .filter(
                ProductionOrder.internal_order_number.in_(order_numbers)
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

        # KROK 3: Grupowanie produktow po zamowieniach
        orders_grouped = {}
        today = date.today()

        for product in products:
            order_num = product.order.internal_order_number if product.order else None

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
                    # DANE WYSYLKI KURIERSKIEJ (2025-12)
                    'shipping_package_id': None,
                    'shipping_tracking_number': None,
                    'shipping_courier_name': None,
                    'shipping_price': None,
                    'shipping_label_base64': None,
                    'shipping_created_at': None,
                }

            # Wymiary w CM (taka sama logika jak przy poczatkowym renderowaniu)
            dimensions_parts = []
            if product.parsed_length_cm:
                dimensions_parts.append(_format_dimension(product.parsed_length_cm))
            if product.parsed_width_cm:
                dimensions_parts.append(_format_dimension(product.parsed_width_cm))
            if product.parsed_thickness_cm:
                dimensions_parts.append(_format_dimension(product.parsed_thickness_cm))
            dimensions_text = '×'.join(dimensions_parts) + ' cm' if dimensions_parts else None

            # Dodaj produkt do zamowienia
            product_data = {
                'id': product.short_product_id,
                'original_name': product.original_product_name or 'Brak nazwy',
                'volume_m3': float(product.volume_m3 or 0),
                'current_status': product.current_status,
                'priority_rank': product.priority_rank or 999,
                'deadline_date': product.deadline_date.isoformat() if product.deadline_date else None,
                'quantity': product.quantity,
                'quantity_done': product.quantity_done_packaging,
                'is_complete': product.is_station_complete('packaging'),
                'is_priority': product.is_priority,
                # Pola potrzebne do renderowania badges
                'wood_species': product.configuration.species if product.configuration else None,
                'technology': product.configuration.technology if product.configuration else None,
                'wood_class': product.configuration.wood_class if product.configuration else None,
                'finish_state': product.parsed_finish_state,
                'dimensions': dimensions_text,
                'attachment_file_url': product.order.attachment_file_url if product.order else None,
                'attachment_file_name': product.order.attachment_file_name if product.order else None,
                'order_notes': product.order.order_notes if product.order else None,
                'production_notes': product.production_notes,
                # WYMIARY SUROWE DO OBLICZEN WYSYLKI (2025-12)
                'parsed_length_cm': float(product.parsed_length_cm) if product.parsed_length_cm else 0,
                'parsed_width_cm': float(product.parsed_width_cm) if product.parsed_width_cm else 0,
                'parsed_thickness_cm': float(product.parsed_thickness_cm) if product.parsed_thickness_cm else 0,
                # DANE DOSTAWY (2025-12)
                'delivery_method': product.order.delivery_method if product.order else None,
                'delivery_fullname': product.order.delivery_fullname if product.order else None,
                'delivery_company': product.order.delivery_company if product.order else None,
                'delivery_address': product.order.delivery_address if product.order else None,
                'delivery_city': product.order.delivery_city if product.order else None,
                'delivery_postcode': product.order.delivery_postcode if product.order else None,
                'delivery_country_code': product.order.delivery_country_code if product.order else None,
                'is_personal_pickup': product.order.is_personal_pickup if product.order else None,
                'delivery_type': product.order.delivery_type if product.order else None,
            }

            orders_grouped[order_num]['products'].append(product_data)
            orders_grouped[order_num]['total_products'] += 1
            orders_grouped[order_num]['total_volume'] += float(product.volume_m3 or 0) * (product.quantity or 1)
            orders_grouped[order_num]['total_quantity'] += product.quantity or 1
            orders_grouped[order_num]['total_quantity_done'] += product.quantity_done_packaging or 0

            # Wez baselinker_order_id z pierwszego produktu ktory go ma
            if not orders_grouped[order_num]['baselinker_order_id'] and product.order and product.order.baselinker_order_id:
                orders_grouped[order_num]['baselinker_order_id'] = product.order.baselinker_order_id

            # Wez client_order_number z pierwszego produktu ktory go ma
            if not orders_grouped[order_num]['client_order_number'] and product.order and product.order.client_order_number:
                orders_grouped[order_num]['client_order_number'] = product.order.client_order_number

            # Pobierz dane dostawy z pierwszego produktu (2025-12)
            if orders_grouped[order_num]['delivery_method'] is None and product.order:
                orders_grouped[order_num]['delivery_method'] = product.order.delivery_method
                orders_grouped[order_num]['delivery_fullname'] = product.order.delivery_fullname
                orders_grouped[order_num]['delivery_company'] = product.order.delivery_company
                orders_grouped[order_num]['delivery_address'] = product.order.delivery_address
                orders_grouped[order_num]['delivery_city'] = product.order.delivery_city
                orders_grouped[order_num]['delivery_postcode'] = product.order.delivery_postcode
                orders_grouped[order_num]['delivery_country_code'] = product.order.delivery_country_code
                orders_grouped[order_num]['is_personal_pickup'] = product.order.is_personal_pickup
                orders_grouped[order_num]['delivery_type'] = product.order.delivery_type

            # Pobierz dane wysylki z pierwszego produktu ktory je ma (2025-12)
            if orders_grouped[order_num]['shipping_package_id'] is None and product.order and product.order.shipping_package_id:
                orders_grouped[order_num]['shipping_package_id'] = product.order.shipping_package_id
                orders_grouped[order_num]['shipping_tracking_number'] = product.order.shipping_tracking_number
                orders_grouped[order_num]['shipping_courier_name'] = product.order.shipping_courier_name
                orders_grouped[order_num]['shipping_price'] = float(product.order.shipping_price) if product.order.shipping_price else None
                orders_grouped[order_num]['shipping_label_base64'] = product.order.shipping_label_base64
                orders_grouped[order_num]['shipping_created_at'] = product.order.shipping_created_at.isoformat() if product.order.shipping_created_at else None

            # Liczniki gotowosci
            if product.current_status == 'czeka_na_pakowanie':
                orders_grouped[order_num]['ready_count'] += 1
            else:
                orders_grouped[order_num]['not_ready_count'] += 1

            # Najlepszy priorytet w zamowieniu
            if product.priority_rank and product.priority_rank < orders_grouped[order_num]['best_priority_rank']:
                orders_grouped[order_num]['best_priority_rank'] = product.priority_rank

            # Najgorszy deadline w zamowieniu
            if product.deadline_date:
                if orders_grouped[order_num]['worst_deadline'] is None:
                    orders_grouped[order_num]['worst_deadline'] = product.deadline_date
                elif product.deadline_date > orders_grouped[order_num]['worst_deadline']:
                    orders_grouped[order_num]['worst_deadline'] = product.deadline_date

        # KROK 4: Dodaj informacje wyswietlania do kazdego zamowienia
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
                    order_data['display_deadline'] = f"Opoznione o {abs(days_diff)} dni"
                elif days_diff == 0:
                    order_data['display_deadline'] = "Dzis!"
                elif days_diff == 1:
                    order_data['display_deadline'] = "Jutro"
                else:
                    order_data['display_deadline'] = f"Za {days_diff} dni"
            else:
                order_data['display_deadline'] = "Brak terminu"

            # Konwertuj deadline na string dla JSON
            if order_data['worst_deadline']:
                order_data['worst_deadline'] = order_data['worst_deadline'].isoformat()

        # KROK 5: Sortowanie zamowien
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

        return jsonify({
            'success': True,
            'data': {
                'orders': orders_list,
                'stats': stats
            }
        }), 200

    except Exception as e:
        logger.error("Blad AJAX orders packaging", extra={
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
    AJAX endpoint dla odswiezania PRODUKTOW na stanowisku wycinania.
    Zwraca plaska liste produktow (bez grupowania po zamowieniach).

    Query params:
        sort: priority|deadline|created_at (default: priority)

    Returns:
        JSON: { success, data: { products: [...], stats: {...} } }
    """
    try:
        from ...models import ProductionItem
        from sqlalchemy import asc

        sort_by = request.args.get('sort', 'priority')

        # Wycinanie widzi tylko produkty ze statusem czeka_na_wyciecie (technologia mikrowczep)
        query = ProductionItem.query.options(
            joinedload(ProductionItem.order),
            joinedload(ProductionItem.configuration),
        ).filter(
            ProductionItem.current_status == 'czeka_na_wyciecie'
        )

        # Sortowanie
        if sort_by == 'priority':
            query = query.order_by(asc(ProductionItem.priority_rank))
        elif sort_by == 'deadline':
            query = query.order_by(asc(ProductionItem.deadline_date))
        elif sort_by == 'created_at':
            query = query.order_by(asc(ProductionItem.created_at))

        products = query.all()

        if not products:
            return jsonify({
                'success': True,
                'data': {
                    'products': [],
                    'stats': {
                        'total_products': 0,
                        'high_priority_count': 0,
                        'overdue_count': 0,
                        'total_volume': 0
                    }
                }
            }), 200

        # KROK 2: Budowanie plaskiej listy produktow z polami wyswietlania
        products_list = []
        today = date.today()

        for product in products:
            rank = product.priority_rank or 999

            # Oblicz wymiary z parsowanych pol (w CM z jednostka)
            dimensions_text = None
            if product.parsed_length_cm and product.parsed_width_cm and product.parsed_thickness_cm:
                dimensions_text = f"{_format_dimension(product.parsed_length_cm)} × {_format_dimension(product.parsed_width_cm)} × {_format_dimension(product.parsed_thickness_cm)} cm"

            # Klasa i etykieta priorytetu per produkt
            if rank <= 10:
                priority_class = 'priority-critical'
                priority_label = 'KRYTYCZNY'
            elif rank <= 50:
                priority_class = 'priority-high'
                priority_label = 'WYSOKI'
            elif rank <= 100:
                priority_class = 'priority-normal'
                priority_label = 'NORMALNY'
            else:
                priority_class = 'priority-low'
                priority_label = 'NISKI'

            # Wyswietlany termin per produkt
            if product.deadline_date:
                days_diff = (product.deadline_date - today).days
                if days_diff < 0:
                    display_deadline = f"Opoznione o {abs(days_diff)} dni"
                elif days_diff == 0:
                    display_deadline = "Dzis!"
                elif days_diff == 1:
                    display_deadline = "Jutro"
                else:
                    display_deadline = f"Za {days_diff} dni"
            else:
                display_deadline = "Brak terminu"

            product_data = {
                'id': product.short_product_id,
                'short_product_id': product.short_product_id,
                'product_sequence_in_order': product.product_sequence_in_order,
                'internal_order_number': product.order.internal_order_number if product.order else None,
                'original_name': product.original_product_name or 'Brak nazwy',
                'dimensions': dimensions_text,
                'volume_m3': float(product.volume_m3 or 0),
                'wood_species': product.configuration.species if product.configuration else None,
                'technology': product.configuration.technology if product.configuration else None,
                'wood_class': product.configuration.wood_class if product.configuration else None,
                'finish_state': product.parsed_finish_state,
                'current_status': product.current_status,
                'priority_rank': rank,
                'priority_class': priority_class,
                'priority_label': priority_label,
                'display_deadline': display_deadline,
                'deadline_date': product.deadline_date.isoformat() if product.deadline_date else None,
                'attachment_file_name': product.order.attachment_file_name if product.order else None,
                'attachment_file_url': product.order.attachment_file_url if product.order else None,
                'quantity': product.quantity,
                'quantity_done': product.quantity_done_cutting,
                'quantity_done_assembly': product.quantity_done_assembly,
                'assembly_completed_at': product.assembly_completed_at.isoformat() if product.assembly_completed_at else None,
                'is_complete': product.is_station_complete('cutting'),
                'is_priority': product.is_priority,
                'order_notes': product.order.order_notes if product.order else None,
                'production_notes': product.production_notes,
                'client_order_number': product.order.client_order_number if product.order else None,
                'baselinker_order_id': product.order.baselinker_order_id if product.order else None,
            }

            products_list.append(product_data)

        # KROK 3: Statystyki
        high_priority_count = sum(1 for p in products_list if p['priority_rank'] <= 50)
        overdue_count = sum(1 for p in products_list
                           if p['deadline_date'] and p['deadline_date'] < today.isoformat())
        total_volume = sum(p['volume_m3'] * p.get('quantity', 1) for p in products_list)

        stats = {
            'total_products': len(products_list),
            'high_priority_count': high_priority_count,
            'overdue_count': overdue_count,
            'total_volume': round(total_volume, 4)
        }

        return jsonify({
            'success': True,
            'data': {
                'products': products_list,
                'stats': stats
            }
        }), 200

    except Exception as e:
        logger.error("Blad AJAX orders cutting", extra={
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
    AJAX endpoint dla odswiezania PRODUKTOW na stanowisku skladania.
    Zwraca plaska liste produktow (bez grupowania po zamowieniach).

    Query params:
        sort: priority|deadline|created_at (default: priority)

    Returns:
        JSON: { success, data: { products: [...], stats: {...} } }
    """
    try:
        from ...models import ProductionItem
        from sqlalchemy import asc

        sort_by = request.args.get('sort', 'priority')

        # Składanie widzi tylko produkty ze statusem czeka_na_skladanie (technologia lity)
        query = ProductionItem.query.options(
            joinedload(ProductionItem.order),
            joinedload(ProductionItem.configuration),
        ).filter(
            ProductionItem.current_status == 'czeka_na_skladanie'
        )

        # Sortowanie
        if sort_by == 'priority':
            query = query.order_by(asc(ProductionItem.priority_rank))
        elif sort_by == 'deadline':
            query = query.order_by(asc(ProductionItem.deadline_date))
        elif sort_by == 'created_at':
            query = query.order_by(asc(ProductionItem.created_at))

        products = query.all()

        if not products:
            return jsonify({
                'success': True,
                'data': {
                    'products': [],
                    'stats': {
                        'total_products': 0,
                        'high_priority_count': 0,
                        'overdue_count': 0,
                        'total_volume': 0
                    }
                }
            }), 200

        # KROK 2: Budowanie plaskiej listy produktow z polami wyswietlania
        products_list = []
        today = date.today()

        for product in products:
            rank = product.priority_rank or 999

            # Oblicz wymiary z parsowanych pol (w CM z jednostka)
            dimensions_text = None
            if product.parsed_length_cm and product.parsed_width_cm and product.parsed_thickness_cm:
                dimensions_text = f"{_format_dimension(product.parsed_length_cm)} × {_format_dimension(product.parsed_width_cm)} × {_format_dimension(product.parsed_thickness_cm)} cm"

            # Klasa i etykieta priorytetu per produkt
            if rank <= 10:
                priority_class = 'priority-critical'
                priority_label = 'KRYTYCZNY'
            elif rank <= 50:
                priority_class = 'priority-high'
                priority_label = 'WYSOKI'
            elif rank <= 100:
                priority_class = 'priority-normal'
                priority_label = 'NORMALNY'
            else:
                priority_class = 'priority-low'
                priority_label = 'NISKI'

            # Wyswietlany termin per produkt
            if product.deadline_date:
                days_diff = (product.deadline_date - today).days
                if days_diff < 0:
                    display_deadline = f"Opoznione o {abs(days_diff)} dni"
                elif days_diff == 0:
                    display_deadline = "Dzis!"
                elif days_diff == 1:
                    display_deadline = "Jutro"
                else:
                    display_deadline = f"Za {days_diff} dni"
            else:
                display_deadline = "Brak terminu"

            product_data = {
                'id': product.short_product_id,
                'short_product_id': product.short_product_id,
                'product_sequence_in_order': product.product_sequence_in_order,
                'internal_order_number': product.order.internal_order_number if product.order else None,
                'original_name': product.original_product_name or 'Brak nazwy',
                'dimensions': dimensions_text,
                'volume_m3': float(product.volume_m3 or 0),
                'wood_species': product.configuration.species if product.configuration else None,
                'technology': product.configuration.technology if product.configuration else None,
                'wood_class': product.configuration.wood_class if product.configuration else None,
                'finish_state': product.parsed_finish_state,
                'current_status': product.current_status,
                'priority_rank': rank,
                'priority_class': priority_class,
                'priority_label': priority_label,
                'display_deadline': display_deadline,
                'deadline_date': product.deadline_date.isoformat() if product.deadline_date else None,
                'attachment_file_name': product.order.attachment_file_name if product.order else None,
                'attachment_file_url': product.order.attachment_file_url if product.order else None,
                'quantity': product.quantity,
                'quantity_done': product.quantity_done_assembly,
                # Pola specyficzne dla skladania
                'quantity_done_cutting': product.quantity_done_cutting or 0,
                'cutting_completed_at': product.cutting_completed_at.isoformat() if product.cutting_completed_at else None,
                'is_complete': product.is_station_complete('assembly'),
                'is_priority': product.is_priority,
                'order_notes': product.order.order_notes if product.order else None,
                'production_notes': product.production_notes,
                'client_order_number': product.order.client_order_number if product.order else None,
                'baselinker_order_id': product.order.baselinker_order_id if product.order else None,
            }

            products_list.append(product_data)

        # KROK 3: Statystyki
        high_priority_count = sum(1 for p in products_list if p['priority_rank'] <= 50)
        overdue_count = sum(1 for p in products_list
                           if p['deadline_date'] and p['deadline_date'] < today.isoformat())
        total_volume = sum(p['volume_m3'] * p.get('quantity', 1) for p in products_list)

        stats = {
            'total_products': len(products_list),
            'high_priority_count': high_priority_count,
            'overdue_count': overdue_count,
            'total_volume': round(total_volume, 4)
        }

        return jsonify({
            'success': True,
            'data': {
                'products': products_list,
                'stats': stats
            }
        }), 200

    except Exception as e:
        logger.error("Blad AJAX orders assembly", extra={
            'error': str(e),
            'traceback': traceback.format_exc()
        })

        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@station_bp.route('/ajax/orders/completion')
def ajax_get_orders_completion():
    """
    AJAX endpoint dla odswiezania PRODUKTOW na stanowisku kompletacji.
    Zwraca plaska liste produktow (bez grupowania po zamowieniach).

    Query params:
        sort: priority|deadline|created_at (default: priority)

    Returns:
        JSON: { success, data: { products: [...], stats: {...} } }
    """
    try:
        from ...models import ProductionItem
        from sqlalchemy import asc

        sort_by = request.args.get('sort', 'priority')

        # KROK 1: Pobierz produkty czekajace na kompletacje
        query = ProductionItem.query.options(
            joinedload(ProductionItem.order),
            joinedload(ProductionItem.configuration),
        ).filter(
            ProductionItem.current_status == 'czeka_na_kompletacje'
        )

        # Sortowanie
        if sort_by == 'priority':
            query = query.order_by(asc(ProductionItem.priority_rank))
        elif sort_by == 'deadline':
            query = query.order_by(asc(ProductionItem.deadline_date))
        elif sort_by == 'created_at':
            query = query.order_by(asc(ProductionItem.created_at))

        products = query.all()

        if not products:
            return jsonify({
                'success': True,
                'data': {
                    'products': [],
                    'stats': {
                        'total_products': 0,
                        'high_priority_count': 0,
                        'overdue_count': 0,
                        'total_volume': 0
                    }
                }
            }), 200

        # KROK 2: Budowanie plaskiej listy produktow z polami wyswietlania
        products_list = []
        today = date.today()

        for product in products:
            rank = product.priority_rank or 999

            # Oblicz wymiary z parsowanych pol (w CM z jednostka)
            dimensions_text = None
            if product.parsed_length_cm and product.parsed_width_cm and product.parsed_thickness_cm:
                dimensions_text = f"{_format_dimension(product.parsed_length_cm)} × {_format_dimension(product.parsed_width_cm)} × {_format_dimension(product.parsed_thickness_cm)} cm"

            # Klasa i etykieta priorytetu per produkt
            if rank <= 10:
                priority_class = 'priority-critical'
                priority_label = 'KRYTYCZNY'
            elif rank <= 50:
                priority_class = 'priority-high'
                priority_label = 'WYSOKI'
            elif rank <= 100:
                priority_class = 'priority-normal'
                priority_label = 'NORMALNY'
            else:
                priority_class = 'priority-low'
                priority_label = 'NISKI'

            # Wyswietlany termin per produkt
            if product.deadline_date:
                days_diff = (product.deadline_date - today).days
                if days_diff < 0:
                    display_deadline = f"Opoznione o {abs(days_diff)} dni"
                elif days_diff == 0:
                    display_deadline = "Dzis!"
                elif days_diff == 1:
                    display_deadline = "Jutro"
                else:
                    display_deadline = f"Za {days_diff} dni"
            else:
                display_deadline = "Brak terminu"

            product_data = {
                'id': product.short_product_id,
                'short_product_id': product.short_product_id,
                'product_sequence_in_order': product.product_sequence_in_order,
                'internal_order_number': product.order.internal_order_number if product.order else None,
                'original_name': product.original_product_name or 'Brak nazwy',
                'dimensions': dimensions_text,
                'volume_m3': float(product.volume_m3 or 0),
                'wood_species': product.configuration.species if product.configuration else None,
                'technology': product.configuration.technology if product.configuration else None,
                'wood_class': product.configuration.wood_class if product.configuration else None,
                'finish_state': product.parsed_finish_state,
                'current_status': product.current_status,
                'priority_rank': rank,
                'priority_class': priority_class,
                'priority_label': priority_label,
                'display_deadline': display_deadline,
                'deadline_date': product.deadline_date.isoformat() if product.deadline_date else None,
                'attachment_file_name': product.order.attachment_file_name if product.order else None,
                'attachment_file_url': product.order.attachment_file_url if product.order else None,
                'quantity': product.quantity,
                'quantity_done': product.quantity_done_completion,
                'is_complete': product.is_station_complete('completion'),
                'is_priority': product.is_priority,
                'order_notes': product.order.order_notes if product.order else None,
                'production_notes': product.production_notes,
                'client_order_number': product.order.client_order_number if product.order else None,
                'baselinker_order_id': product.order.baselinker_order_id if product.order else None,
            }

            products_list.append(product_data)

        # KROK 3: Statystyki
        high_priority_count = sum(1 for p in products_list if p['priority_rank'] <= 50)
        overdue_count = sum(1 for p in products_list
                           if p['deadline_date'] and p['deadline_date'] < today.isoformat())
        total_volume = sum(p['volume_m3'] * p.get('quantity', 1) for p in products_list)

        stats = {
            'total_products': len(products_list),
            'high_priority_count': high_priority_count,
            'overdue_count': overdue_count,
            'total_volume': round(total_volume, 4)
        }

        return jsonify({
            'success': True,
            'data': {
                'products': products_list,
                'stats': stats
            }
        }), 200

    except Exception as e:
        logger.error("Blad AJAX orders completion", extra={
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
    AJAX endpoint dla odswiezania PRODUKTOW na stanowisku sklejania.
    Zwraca plaska liste produktow (bez grupowania po zamowieniach).
    NIE uzywa _ajax_get_orders_simple — ta funkcja zostaje dla formatting/finishing.

    Query params:
        sort: priority|deadline|created_at (default: priority)

    Returns:
        JSON: { success, data: { products: [...], stats: {...} } }
    """
    try:
        from ...models import ProductionItem
        from sqlalchemy import asc

        sort_by = request.args.get('sort', 'priority')

        # KROK 1: Pobierz produkty czekajace na sklejanie
        query = ProductionItem.query.options(
            joinedload(ProductionItem.order),
            joinedload(ProductionItem.configuration),
        ).filter(
            ProductionItem.current_status == 'czeka_na_sklejanie'
        )

        # Sortowanie
        if sort_by == 'priority':
            query = query.order_by(asc(ProductionItem.priority_rank))
        elif sort_by == 'deadline':
            query = query.order_by(asc(ProductionItem.deadline_date))
        elif sort_by == 'created_at':
            query = query.order_by(asc(ProductionItem.created_at))

        products = query.all()

        if not products:
            return jsonify({
                'success': True,
                'data': {
                    'products': [],
                    'stats': {
                        'total_products': 0,
                        'high_priority_count': 0,
                        'overdue_count': 0,
                        'total_volume': 0
                    }
                }
            }), 200

        # KROK 2: Budowanie plaskiej listy produktow z polami wyswietlania
        products_list = []
        today = date.today()

        for product in products:
            rank = product.priority_rank or 999

            # Oblicz wymiary z parsowanych pol (w CM z jednostka)
            dimensions_text = None
            if product.parsed_length_cm and product.parsed_width_cm and product.parsed_thickness_cm:
                dimensions_text = f"{_format_dimension(product.parsed_length_cm)} × {_format_dimension(product.parsed_width_cm)} × {_format_dimension(product.parsed_thickness_cm)} cm"

            # Klasa i etykieta priorytetu per produkt
            if rank <= 10:
                priority_class = 'priority-critical'
                priority_label = 'KRYTYCZNY'
            elif rank <= 50:
                priority_class = 'priority-high'
                priority_label = 'WYSOKI'
            elif rank <= 100:
                priority_class = 'priority-normal'
                priority_label = 'NORMALNY'
            else:
                priority_class = 'priority-low'
                priority_label = 'NISKI'

            # Wyswietlany termin per produkt
            if product.deadline_date:
                days_diff = (product.deadline_date - today).days
                if days_diff < 0:
                    display_deadline = f"Opoznione o {abs(days_diff)} dni"
                elif days_diff == 0:
                    display_deadline = "Dzis!"
                elif days_diff == 1:
                    display_deadline = "Jutro"
                else:
                    display_deadline = f"Za {days_diff} dni"
            else:
                display_deadline = "Brak terminu"

            product_data = {
                'id': product.short_product_id,
                'short_product_id': product.short_product_id,
                'product_sequence_in_order': product.product_sequence_in_order,
                'internal_order_number': product.order.internal_order_number if product.order else None,
                'original_name': product.original_product_name or 'Brak nazwy',
                'dimensions': dimensions_text,
                'volume_m3': float(product.volume_m3 or 0),
                'wood_species': product.configuration.species if product.configuration else None,
                'technology': product.configuration.technology if product.configuration else None,
                'wood_class': product.configuration.wood_class if product.configuration else None,
                'finish_state': product.parsed_finish_state,
                'current_status': product.current_status,
                'priority_rank': rank,
                'priority_class': priority_class,
                'priority_label': priority_label,
                'display_deadline': display_deadline,
                'deadline_date': product.deadline_date.isoformat() if product.deadline_date else None,
                'attachment_file_name': product.order.attachment_file_name if product.order else None,
                'attachment_file_url': product.order.attachment_file_url if product.order else None,
                'quantity': product.quantity,
                'quantity_done': product.quantity_done_gluing,
                'is_complete': product.is_station_complete('gluing'),
                'is_priority': product.is_priority,
                'order_notes': product.order.order_notes if product.order else None,
                'production_notes': product.production_notes,
                'client_order_number': product.order.client_order_number if product.order else None,
                'baselinker_order_id': product.order.baselinker_order_id if product.order else None,
            }

            products_list.append(product_data)

        # KROK 3: Statystyki
        high_priority_count = sum(1 for p in products_list if p['priority_rank'] <= 50)
        overdue_count = sum(1 for p in products_list
                           if p['deadline_date'] and p['deadline_date'] < today.isoformat())
        total_volume = sum(p['volume_m3'] * p.get('quantity', 1) for p in products_list)

        stats = {
            'total_products': len(products_list),
            'high_priority_count': high_priority_count,
            'overdue_count': overdue_count,
            'total_volume': round(total_volume, 4)
        }

        return jsonify({
            'success': True,
            'data': {
                'products': products_list,
                'stats': stats
            }
        }), 200

    except Exception as e:
        logger.error("Blad AJAX orders gluing", extra={
            'error': str(e),
            'traceback': traceback.format_exc()
        })

        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@station_bp.route('/ajax/orders/formatting')
def ajax_get_orders_formatting():
    """AJAX endpoint dla odswiezania ZAMOWIEN na stanowisku formatowania"""
    return _ajax_get_orders_simple('formatting', 'czeka_na_formatowanie', 'quantity_done_formatting')


@station_bp.route('/ajax/orders/finishing')
def ajax_get_orders_finishing():
    """AJAX endpoint dla odswiezania ZAMOWIEN na stanowisku wykonczania"""
    return _ajax_get_orders_simple('finishing', 'czeka_na_wykanczanie', 'quantity_done_finishing')


@station_bp.route('/ajax/station-today-m3/<station_code>')
def ajax_station_today_m3(station_code):
    """
    AJAX endpoint dla dzisiejszych m3 wykonanych na danym stanowisku

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
        if station_code not in ['cutting', 'assembly', 'completion', 'gluing', 'formatting', 'finishing', 'painting', 'packaging']:
            return jsonify({
                'success': False,
                'error': f'Nieprawidlowy station_code. Dozwolone: cutting, assembly, completion, gluing, formatting, finishing, packaging'
            }), 400

        record_heartbeat(station_code)

        from datetime import timedelta
        from ...services.station_events_service import get_station_work_in_range

        # Okresl zakres czasowy dla "dzisiaj"
        today = date.today()
        today_start = datetime.combine(today, datetime.min.time())
        tomorrow_start = today_start + timedelta(days=1)

        # Faktyczna praca dziś — z prod_station_events (uwzględnia partial work)
        try:
            work = get_station_work_in_range(station_code, today_start, tomorrow_start)
            today_m3 = float(work['m3_done'])
        except Exception as e:
            logger.warning(f"Nie udało się pobrać station_events dla {station_code}", extra={
                'station_code': station_code, 'error': str(e)
            })
            today_m3 = 0.0

        result = {
            'success': True,
            'data': {
                'station_code': station_code,
                'today_m3': round(today_m3, 4),
                'today_date': today.isoformat(),
                'last_updated': datetime.utcnow().isoformat()
            }
        }

        return jsonify(result), 200

    except Exception as e:
        logger.error("Blad AJAX station-today-m3", extra={
            'station_code': station_code,
            'error': str(e),
            'traceback': traceback.format_exc()
        })

        return jsonify({
            'success': False,
            'error': f'Blad pobierania danych: {str(e)}'
        }), 500


# ============================================================================
# DRUKOWANIE ETYKIET
# ============================================================================


def _resolve_print_station_code():
    payload = request.get_json(silent=True) or {}
    return (payload.get('station_code') or request.args.get('station_code') or '').strip()


@station_bp.route('/ajax/print-label/<short_product_id>', methods=['POST'])
@login_required
def print_label_single(short_product_id):
    station_code = _resolve_print_station_code()
    if not station_code:
        return jsonify({'success': False, 'message': 'Brak parametru station_code'}), 400
    try:
        result = label_print_service.print_labels_batch(
            [short_product_id],
            station_code,
            {'type': 'user', 'id': current_user.id},
        )
    except StationNotAllowed as e:
        return jsonify({'success': False, 'message': str(e)}), 403

    if result['connection_error']:
        return jsonify(result), 502
    return jsonify(result), 200


@station_bp.route('/ajax/print-labels-for-order/<int:baselinker_order_id>', methods=['POST'])
@login_required
def print_labels_for_order(baselinker_order_id):
    station_code = _resolve_print_station_code()
    if not station_code:
        return jsonify({'success': False, 'message': 'Brak parametru station_code'}), 400

    items = (ProductionItem.query
             .join(ProductionOrder)
             .filter(ProductionOrder.baselinker_order_id == baselinker_order_id)
             .order_by(ProductionItem.product_sequence_in_order)
             .all())
    if not items:
        return jsonify({
            'success': False, 'success_count': 0, 'failed_count': 0,
            'connection_error': False, 'results': [],
            'message': 'Brak produktów w zamówieniu.',
        }), 404

    short_ids = [i.short_product_id for i in items]
    try:
        result = label_print_service.print_labels_batch(
            short_ids,
            station_code,
            {'type': 'user', 'id': current_user.id},
        )
    except StationNotAllowed as e:
        return jsonify({'success': False, 'message': str(e)}), 403

    if result['connection_error']:
        return jsonify(result), 502
    return jsonify(result), 200


@station_bp.route('/ajax/print-job-status', methods=['GET'])
@login_required
def print_job_status():
    """
    GET /production/stations/ajax/print-job-status?ids=1,2,3
    Zwraca status zadań drukowania z prod_print_queue.
    Używane przez frontend do śledzenia 'pending → printed/failed/expired'.
    """
    from modules.production.models import LabelPrintJob

    raw = (request.args.get('ids') or '').strip()
    if not raw:
        return jsonify({'jobs': []}), 200

    try:
        ids = [int(x) for x in raw.split(',') if x.strip().isdigit()]
    except ValueError:
        return jsonify({'error': 'invalid_ids'}), 400

    if not ids:
        return jsonify({'jobs': []}), 200

    jobs = LabelPrintJob.query.filter(LabelPrintJob.id.in_(ids)).all()
    return jsonify({
        'jobs': [
            {
                'id': j.id,
                'status': j.status,
                'short_product_id': j.short_product_id,
                'printed_at': j.printed_at.isoformat() if j.printed_at else None,
                'error_message': j.error_message,
            }
            for j in jobs
        ],
    }), 200
