# modules/production/routers/stations/interfaces.py
"""
Station tablet interfaces: cutting, assembly, gluing, formatting, finishing, packaging
"""

from flask import render_template, request, url_for
from datetime import datetime, date
from extensions import db
from sqlalchemy.orm import joinedload
import traceback

from . import station_bp, logger, get_station_config, _format_dimension



# ============================================================================
# STANOWISKO WYCINANIA (CUTTING)
# ============================================================================

@station_bp.route('/cutting')
def cutting_station():
    """
    Interfejs stanowiska wycinania - FLAT PRODUCT LIST VERSION

    Zwraca splaszczona liste produktow (bez grupowania po zamowieniu).

    Query params:
        sort: priority|deadline|created_at (default: priority)

    Returns:
        HTML: Interfejs stanowiska wycinania z lista produktow
    """
    try:
        from ...models import ProductionItem, ProductionOrder, ProductionProduct
        from sqlalchemy import asc, desc

        sort_by = request.args.get('sort', 'priority')

        # Wycinanie widzi tylko produkty ze statusem czeka_na_wyciecie (technologia mikrowczep)
        orders_with_cutting = db.session.query(
            ProductionOrder.internal_order_number
        ).join(
            ProductionProduct, ProductionProduct.order_id == ProductionOrder.id
        ).filter(
            ProductionProduct.current_status == 'czeka_na_wyciecie'
        ).distinct().all()

        order_numbers = [order[0] for order in orders_with_cutting if order[0]]

        if not order_numbers:
            products = []
        else:
            query = (
                ProductionProduct.query
                .options(
                    joinedload(ProductionProduct.order),
                    joinedload(ProductionProduct.configuration),
                )
                .join(ProductionOrder)
                .filter(
                    ProductionOrder.internal_order_number.in_(order_numbers),
                    ProductionProduct.current_status == 'czeka_na_wyciecie'
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

            # Przygotuj dane produktow
            products = []

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
                    'internal_order': product.order.internal_order_number if product.order else None,
                    'baselinker_order_id': product.order.baselinker_order_id if product.order else None,
                    'original_name': product.original_product_name,
                    'current_status': product.current_status,
                    'priority_rank': priority_rank,
                    'deadline_date': product.deadline_date,
                    'volume_m3': volume_m3,
                    'wood_species': product.configuration.species if product.configuration else None,
                    'technology': product.configuration.technology if product.configuration else None,
                    'wood_class': product.configuration.wood_class if product.configuration else None,
                    'finish_state': product.parsed_finish_state,
                    'finish_type': product.parsed_finish_type,
                    'dimensions': dimensions_text,
                    'attachment_file_name': product.order.attachment_file_name if product.order else None,
                    'attachment_file_url': product.order.attachment_file_url if product.order else None,
                    'product_sequence_in_order': product.product_sequence_in_order,
                    'quantity': product.quantity,
                    'quantity_done': product.quantity_done_cutting,
                    'quantity_done_assembly': product.quantity_done_assembly,
                    'assembly_completed_at': product.assembly_completed_at,
                    'is_complete': product.quantity_done_cutting == product.quantity,
                    'is_priority': product.is_priority,
                    'order_notes': product.order.order_notes if product.order else None,
                    'production_notes': product.production_notes,
                    'client_order_number': product.order.client_order_number if product.order else None
                }

                products.append(product_data)

        # =========================================
        # KROK 4: Flat product list (no order grouping)
        # Enriches each product dict in-place with display fields,
        # then assigns products_flat = products (same list, no copy needed).
        # =========================================
        today = date.today()

        for product in products:
            # Display deadline per product
            if product['deadline_date']:
                days_diff = (product['deadline_date'] - today).days
                if days_diff < 0:
                    product['display_deadline'] = f"Opóźnione o {abs(days_diff)} dni"
                elif days_diff == 0:
                    product['display_deadline'] = "Dziś!"
                elif days_diff == 1:
                    product['display_deadline'] = "Jutro"
                else:
                    product['display_deadline'] = f"Za {days_diff} dni"
            else:
                product['display_deadline'] = "Brak terminu"

            # Priority class per product
            rank = product['priority_rank']
            if rank <= 10:
                product['priority_class'] = 'priority-critical'
                product['priority_label'] = 'KRYTYCZNY'
            elif rank <= 50:
                product['priority_class'] = 'priority-high'
                product['priority_label'] = 'WYSOKI'
            elif rank <= 100:
                product['priority_class'] = 'priority-normal'
                product['priority_label'] = 'NORMALNY'
            else:
                product['priority_class'] = 'priority-low'
                product['priority_label'] = 'NISKI'

        products_flat = products

        # Sort flat products
        if sort_by == 'priority':
            products_flat.sort(key=lambda x: x['priority_rank'])
        elif sort_by == 'deadline':
            products_flat.sort(key=lambda x: x['deadline_date'] or date(9999, 12, 31))

        # =========================================
        # KROK 5: Station statistics
        # =========================================
        config = get_station_config()

        station_stats = {
            'total_products': sum((p.get('quantity', 1) or 1) for p in products_flat),
            'total_tiles': len(products_flat),
            'high_priority_count': sum(1 for p in products_flat if p['priority_rank'] <= 50),
            'total_volume': sum((p.get('volume_m3', 0) or 0) * (p.get('quantity', 1) or 1) for p in products_flat)
        }

        now = datetime.utcnow()

        return render_template(
            'stations/cutting.html',
            products_flat=products_flat,
            station_code='cutting',
            station_name='Wycinanie - mikro',
            station_stats=station_stats,
            config=config,
            sort_by=sort_by,
            now=now,
            last_updated=datetime.utcnow(),
            page_title="Stanowisko Wycinania - mikro"
        )

    except Exception as e:
        logger.error("Blad interfejsu wycinania", extra={
            'client_ip': request.remote_addr,
            'error': str(e)
        })

        return render_template(
            'stations/error.html',
            error_message="Blad ladowania stanowiska wycinania",
            error_details=str(e),
            back_url=url_for('production.production_stations.station_select')
        ), 500


# ============================================================================
# STANOWISKO SKLADANIA (ASSEMBLY)
# ============================================================================

@station_bp.route('/assembly')
def assembly_station():
    """
    Interfejs stanowiska skladania - FLAT PRODUCT LIST VERSION

    Zwraca splaszczona liste produktow (bez grupowania po zamowieniu).

    Query params:
        sort: priority|deadline|created_at (default: priority)

    Returns:
        HTML: Interfejs stanowiska skladania z lista produktow
    """
    try:
        from ...models import ProductionItem, ProductionOrder, ProductionProduct
        from sqlalchemy import asc, desc

        sort_by = request.args.get('sort', 'priority')

        # Składanie widzi tylko produkty ze statusem czeka_na_skladanie (technologia lity)
        orders_with_assembly = db.session.query(
            ProductionOrder.internal_order_number
        ).join(
            ProductionProduct, ProductionProduct.order_id == ProductionOrder.id
        ).filter(
            ProductionProduct.current_status == 'czeka_na_skladanie'
        ).distinct().all()

        order_numbers = [order[0] for order in orders_with_assembly if order[0]]

        if not order_numbers:
            products = []
        else:
            query = (
                ProductionProduct.query
                .options(
                    joinedload(ProductionProduct.order),
                    joinedload(ProductionProduct.configuration),
                )
                .join(ProductionOrder)
                .filter(
                    ProductionOrder.internal_order_number.in_(order_numbers),
                    ProductionProduct.current_status == 'czeka_na_skladanie'
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

            # Przygotuj dane produktow
            products = []

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
                    'internal_order': product.order.internal_order_number if product.order else None,
                    'baselinker_order_id': product.order.baselinker_order_id if product.order else None,
                    'original_name': product.original_product_name,
                    'current_status': product.current_status,
                    'priority_rank': priority_rank,
                    'deadline_date': product.deadline_date,
                    'volume_m3': volume_m3,
                    'wood_species': product.configuration.species if product.configuration else None,
                    'technology': product.configuration.technology if product.configuration else None,
                    'wood_class': product.configuration.wood_class if product.configuration else None,
                    'finish_state': product.parsed_finish_state,
                    'finish_type': product.parsed_finish_type,
                    'dimensions': dimensions_text,
                    'attachment_file_name': product.order.attachment_file_name if product.order else None,
                    'attachment_file_url': product.order.attachment_file_url if product.order else None,
                    'product_sequence_in_order': product.product_sequence_in_order,
                    'quantity': product.quantity,
                    'quantity_done': product.quantity_done_assembly,
                    'quantity_done_cutting': product.quantity_done_cutting or 0,
                    'cutting_completed_at': product.cutting_completed_at,
                    'is_complete': product.quantity_done_assembly == product.quantity,
                    'is_priority': product.is_priority,
                    'order_notes': product.order.order_notes if product.order else None,
                    'production_notes': product.production_notes,
                    'client_order_number': product.order.client_order_number if product.order else None
                }

                products.append(product_data)

        # =========================================
        # KROK 4: Flat product list (no order grouping)
        # Enriches each product dict in-place with display fields,
        # then assigns products_flat = products (same list, no copy needed).
        # =========================================
        today = date.today()

        for product in products:
            # Display deadline per product
            if product['deadline_date']:
                days_diff = (product['deadline_date'] - today).days
                if days_diff < 0:
                    product['display_deadline'] = f"Opóźnione o {abs(days_diff)} dni"
                elif days_diff == 0:
                    product['display_deadline'] = "Dziś!"
                elif days_diff == 1:
                    product['display_deadline'] = "Jutro"
                else:
                    product['display_deadline'] = f"Za {days_diff} dni"
            else:
                product['display_deadline'] = "Brak terminu"

            # Priority class per product
            rank = product['priority_rank']
            if rank <= 10:
                product['priority_class'] = 'priority-critical'
                product['priority_label'] = 'KRYTYCZNY'
            elif rank <= 50:
                product['priority_class'] = 'priority-high'
                product['priority_label'] = 'WYSOKI'
            elif rank <= 100:
                product['priority_class'] = 'priority-normal'
                product['priority_label'] = 'NORMALNY'
            else:
                product['priority_class'] = 'priority-low'
                product['priority_label'] = 'NISKI'

        products_flat = products

        # Sort flat products
        if sort_by == 'priority':
            products_flat.sort(key=lambda x: x['priority_rank'])
        elif sort_by == 'deadline':
            products_flat.sort(key=lambda x: x['deadline_date'] or date(9999, 12, 31))

        # =========================================
        # KROK 5: Station statistics
        # =========================================
        config = get_station_config()

        station_stats = {
            'total_products': sum((p.get('quantity', 1) or 1) for p in products_flat),
            'total_tiles': len(products_flat),
            'high_priority_count': sum(1 for p in products_flat if p['priority_rank'] <= 50),
            'total_volume': sum((p.get('volume_m3', 0) or 0) * (p.get('quantity', 1) or 1) for p in products_flat)
        }

        now = datetime.utcnow()

        return render_template(
            'stations/assembly.html',
            products_flat=products_flat,
            station_code='assembly',
            station_name='Składanie - lite',
            station_stats=station_stats,
            config=config,
            sort_by=sort_by,
            now=now,
            last_updated=datetime.utcnow(),
            page_title="Stanowisko Składania - lite"
        )

    except Exception as e:
        logger.error("Blad interfejsu skladania", extra={
            'client_ip': request.remote_addr,
            'error': str(e),
            'traceback': traceback.format_exc()
        })

        return render_template(
            'stations/error.html',
            error_message="Blad ladowania stanowiska skladania",
            error_details=str(e),
            back_url=url_for('production.production_stations.station_select')
        ), 500


# ============================================================================
# STANOWISKO SKLEJANIA (GLUING)
# ============================================================================

@station_bp.route('/completion')
def completion_station():
    """Interfejs stanowiska kompletacji - bramka kompletnosci po szlifierce.
    Domyslny tab dla zamowien swiezo przyjetych z cutting/assembly."""
    return _render_completion_or_gluing(active_tab='completion')


@station_bp.route('/gluing')
def gluing_station():
    """Interfejs stanowiska sklejania - drugi tab w widoku stanowiska sklejania."""
    return _render_completion_or_gluing(active_tab='gluing')


def _render_completion_or_gluing(active_tab):
    """
    Wspolny render dla tabow 'completion' i 'gluing'. Filtruje produkty po
    statusie odpowiadajacym aktywnemu tabowi i dostarcza liczniki obu kolejek
    do tab-bara.
    """
    try:
        from ...models import ProductionItem
        from sqlalchemy import asc

        sort_by = request.args.get('sort', 'priority')

        TAB_CONFIG = {
            'completion': {
                'status': 'czeka_na_kompletacje',
                'quantity_field': 'quantity_done_completion',
                'station_code': 'completion',
                'station_name': 'Kompletacja',
                'page_title': 'Stanowisko Kompletacji',
                'error_message': 'Blad ladowania stanowiska kompletacji',
                'log_message': 'Blad interfejsu kompletacji',
            },
            'gluing': {
                'status': 'czeka_na_sklejanie',
                'quantity_field': 'quantity_done_gluing',
                'station_code': 'gluing',
                'station_name': 'Sklejanie',
                'page_title': 'Stanowisko Sklejania',
                'error_message': 'Blad ladowania stanowiska sklejania',
                'log_message': 'Blad interfejsu sklejania',
            },
        }
        cfg = TAB_CONFIG[active_tab]

        completion_count = ProductionItem.query.filter(
            ProductionItem.current_status == 'czeka_na_kompletacje'
        ).count()
        gluing_count = ProductionItem.query.filter(
            ProductionItem.current_status == 'czeka_na_sklejanie'
        ).count()

        query = ProductionItem.query.filter(
            ProductionItem.current_status == cfg['status']
        )
        if sort_by == 'priority':
            query = query.order_by(asc(ProductionItem.priority_rank))
        elif sort_by == 'deadline':
            query = query.order_by(asc(ProductionItem.deadline_date))
        else:
            query = query.order_by(asc(ProductionItem.created_at))

        products_db = query.all()
        products = []
        for product in products_db:
            priority_rank = product.priority_rank if product.priority_rank else 999
            dimensions_parts = []
            if product.parsed_length_cm:
                dimensions_parts.append(_format_dimension(product.parsed_length_cm))
            if product.parsed_width_cm:
                dimensions_parts.append(_format_dimension(product.parsed_width_cm))
            if product.parsed_thickness_cm:
                dimensions_parts.append(_format_dimension(product.parsed_thickness_cm))
            dimensions_text = '×'.join(dimensions_parts) + ' cm' if dimensions_parts else None
            volume_m3 = float(product.volume_m3) if product.volume_m3 else 0.0
            qty_done = getattr(product, cfg['quantity_field'])

            products.append({
                'id': product.short_product_id,
                'internal_order': product.order.internal_order_number if product.order else None,
                'baselinker_order_id': product.order.baselinker_order_id if product.order else None,
                'original_name': product.original_product_name,
                'current_status': product.current_status,
                'priority_rank': priority_rank,
                'deadline_date': product.deadline_date,
                'volume_m3': volume_m3,
                'wood_species': product.configuration.species if product.configuration else None,
                'technology': product.configuration.technology if product.configuration else None,
                'wood_class': product.configuration.wood_class if product.configuration else None,
                'finish_state': product.parsed_finish_state,
                'finish_type': product.parsed_finish_type,
                'dimensions': dimensions_text,
                'attachment_file_name': product.order.attachment_file_name if product.order else None,
                'attachment_file_url': product.order.attachment_file_url if product.order else None,
                'product_sequence_in_order': product.product_sequence_in_order,
                'quantity': product.quantity,
                'quantity_done': qty_done,
                'is_complete': qty_done == product.quantity,
                'is_priority': product.is_priority,
                'order_notes': product.order.order_notes if product.order else None,
                'production_notes': product.production_notes,
                'client_order_number': product.order.client_order_number if product.order else None,
            })

        today = date.today()
        for product in products:
            if product['deadline_date']:
                days_diff = (product['deadline_date'] - today).days
                if days_diff < 0:
                    product['display_deadline'] = f"Opóźnione o {abs(days_diff)} dni"
                elif days_diff == 0:
                    product['display_deadline'] = "Dziś!"
                elif days_diff == 1:
                    product['display_deadline'] = "Jutro"
                else:
                    product['display_deadline'] = f"Za {days_diff} dni"
            else:
                product['display_deadline'] = "Brak terminu"

            rank = product['priority_rank']
            if rank <= 10:
                product['priority_class'] = 'priority-critical'
                product['priority_label'] = 'KRYTYCZNY'
            elif rank <= 50:
                product['priority_class'] = 'priority-high'
                product['priority_label'] = 'WYSOKI'
            elif rank <= 100:
                product['priority_class'] = 'priority-normal'
                product['priority_label'] = 'NORMALNY'
            else:
                product['priority_class'] = 'priority-low'
                product['priority_label'] = 'NISKI'

        products_flat = products
        if sort_by == 'priority':
            products_flat.sort(key=lambda x: x['priority_rank'])
        elif sort_by == 'deadline':
            products_flat.sort(key=lambda x: x['deadline_date'] or date(9999, 12, 31))

        config = get_station_config()
        station_stats = {
            'total_products': sum((p.get('quantity', 1) or 1) for p in products_flat),
            'total_tiles': len(products_flat),
            'high_priority_count': sum(1 for p in products_flat if p['priority_rank'] <= 50),
            'total_volume': sum((p.get('volume_m3', 0) or 0) * (p.get('quantity', 1) or 1) for p in products_flat),
        }

        now = datetime.utcnow()

        return render_template(
            'stations/gluing.html',
            products_flat=products_flat,
            station_code=cfg['station_code'],
            station_name=cfg['station_name'],
            active_tab=active_tab,
            completion_count=completion_count,
            gluing_count=gluing_count,
            station_stats=station_stats,
            config=config,
            sort_by=sort_by,
            now=now,
            last_updated=datetime.utcnow(),
            page_title=cfg['page_title'],
        )

    except Exception as e:
        logger.error(cfg['log_message'] if 'cfg' in locals() else 'Blad interfejsu kompletacja/sklejanie', extra={
            'client_ip': request.remote_addr,
            'error': str(e),
            'traceback': traceback.format_exc()
        })

        return render_template(
            'stations/error.html',
            error_message=cfg['error_message'] if 'cfg' in locals() else 'Blad ladowania stanowiska',
            error_details=str(e),
            back_url=url_for('production.production_stations.station_select')
        ), 500


# ============================================================================
# STANOWISKO FORMATOWANIA (FORMATTING)
# ============================================================================

@station_bp.route('/formatting')
def formatting_station():
    """
    Interfejs stanowiska formatowania - ORDER-BASED VERSION
    Pokazuje CALE zamowienia (grouped by internal_order_number)

    Query params:
        sort: priority|deadline|created_at (default: priority)

    Returns:
        HTML: Interfejs stanowiska formatowania z pogrupowanymi zamowieniami
    """
    try:
        from ...models import ProductionItem, ProductionOrder, ProductionProduct
        from sqlalchemy import asc, desc

        sort_by = request.args.get('sort', 'priority')

        # Znajdz zamowienia ktore maja choc 1 produkt do formatowania
        orders_with_formatting = db.session.query(
            ProductionOrder.internal_order_number
        ).join(
            ProductionProduct, ProductionProduct.order_id == ProductionOrder.id
        ).filter(
            ProductionProduct.current_status == 'czeka_na_formatowanie'
        ).distinct().all()

        order_numbers = [order[0] for order in orders_with_formatting if order[0]]

        if not order_numbers:
            products = []
        else:
            # Pobierz WSZYSTKIE produkty z tych zamowien
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

            if sort_by == 'priority':
                query = query.order_by(asc(ProductionItem.priority_rank))
            elif sort_by == 'deadline':
                query = query.order_by(asc(ProductionItem.deadline_date))
            else:
                query = query.order_by(asc(ProductionItem.created_at))

            products_db = query.all()

            products = []
            today = date.today()

            for product in products_db:
                priority_rank = product.priority_rank if product.priority_rank else 999

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
                    'internal_order': product.order.internal_order_number if product.order else None,
                    'baselinker_order_id': product.order.baselinker_order_id if product.order else None,
                    'original_name': product.original_product_name,
                    'current_status': product.current_status,
                    'priority_rank': priority_rank,
                    'deadline_date': product.deadline_date,
                    'volume_m3': volume_m3,
                    'wood_species': product.configuration.species if product.configuration else None,
                    'technology': product.configuration.technology if product.configuration else None,
                    'wood_class': product.configuration.wood_class if product.configuration else None,
                    'finish_state': product.parsed_finish_state,
                    'finish_type': product.parsed_finish_type,
                    'dimensions': dimensions_text,
                    'attachment_file_name': product.order.attachment_file_name if product.order else None,
                    'attachment_file_url': product.order.attachment_file_url if product.order else None,
                    'product_sequence_in_order': product.product_sequence_in_order,
                    'quantity': product.quantity,
                    'quantity_done': product.quantity_done_formatting,
                    'is_complete': product.quantity_done_formatting == product.quantity,
                    'is_priority': product.is_priority,
                    'order_notes': product.order.order_notes if product.order else None,
                    'production_notes': product.production_notes,
                    'client_order_number': product.order.client_order_number if product.order else None,
                    'parsed_edge_processing': product.parsed_edge_processing,
                    'parsed_edge_type': product.parsed_edge_type,
                    'parsed_edge_radius': product.parsed_edge_radius,
                    'parsed_edge_angle': product.parsed_edge_angle,
                    'parsed_edge_letters': product.parsed_edge_letters,
                    'edge_svg': product.edge_svg,
                    'shape_svg': product.shape_svg,
                    'lamella_direction': product.lamella_direction,
                    'has_visual_data': bool(product.shape_svg or product.edge_svg),
                }

                products.append(product_data)

        # Grupowanie produktow po zamowieniach
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
            order['total_volume'] += (product['volume_m3'] or 0) * (product.get('quantity', 1) or 1)

            if product['priority_rank'] < order['best_priority_rank']:
                order['best_priority_rank'] = product['priority_rank']

            if product['deadline_date']:
                if order['worst_deadline'] is None or product['deadline_date'] > order['worst_deadline']:
                    order['worst_deadline'] = product['deadline_date']

        for order in orders_grouped.values():
            order['products'].sort(key=lambda p: p['product_sequence_in_order'])

        today = date.today()
        for order in orders_grouped.values():
            if order['worst_deadline']:
                days_diff = (order['worst_deadline'] - today).days
                if days_diff < 0:
                    order['display_deadline'] = f"Opoznione o {abs(days_diff)} dni"
                elif days_diff == 0:
                    order['display_deadline'] = "Dzis!"
                elif days_diff == 1:
                    order['display_deadline'] = "Jutro"
                else:
                    order['display_deadline'] = f"Za {days_diff} dni"
            else:
                order['display_deadline'] = "Brak terminu"

        if sort_by == 'priority':
            orders_list = sorted(orders_grouped.values(), key=lambda x: x['best_priority_rank'])
        elif sort_by == 'deadline':
            orders_list = sorted(orders_grouped.values(), key=lambda x: x['worst_deadline'] or date(9999, 12, 31))
        else:
            orders_list = list(orders_grouped.values())

        config = get_station_config()

        total_products = sum(order['total_quantity'] for order in orders_list)
        high_priority_count = sum(1 for order in orders_list if order['best_priority_rank'] <= 50)

        station_stats = {
            'total_products': total_products,
            'total_orders': len(orders_list),
            'high_priority_count': high_priority_count,
            'total_volume': sum((p.get('volume_m3', 0) or 0) * (p.get('quantity', 1) or 1) for p in products)
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
        logger.error("Blad interfejsu formatowania", extra={
            'client_ip': request.remote_addr,
            'error': str(e),
            'traceback': traceback.format_exc()
        })

        return render_template(
            'stations/error.html',
            error_message="Blad ladowania stanowiska formatowania",
            error_details=str(e),
            back_url=url_for('production.production_stations.station_select')
        ), 500


# ============================================================================
# STANOWISKO WYKONCZANIA (FINISHING)
# ============================================================================

@station_bp.route('/finishing')
def finishing_station():
    """
    Interfejs stanowiska wykańczania — podzielony na zakładki Produkcja / Lakiernia.
    Obie zakładki renderują produkty jako osobne kafelki (flat, jak cutting).

    Query params:
        tab: production|painting (default: production)
        sort: priority|deadline|created_at (default: priority)
    """
    try:
        from ...models import ProductionItem
        from sqlalchemy import asc, func

        tab = request.args.get('tab', 'production')
        sort_by = request.args.get('sort', 'priority')

        # Filtruj wg zakładki
        if tab == 'painting':
            status_filter = 'czeka_na_lakiernie'
            station_code = 'painting'
            quantity_done_field = 'quantity_done_painting'
        else:
            status_filter = 'czeka_na_wykanczanie'
            station_code = 'finishing'
            quantity_done_field = 'quantity_done_finishing'

        # Zliczaj produkty w obu zakładkach (do wyświetlenia w belce)
        production_count = ProductionItem.query.filter(
            ProductionItem.current_status == 'czeka_na_wykanczanie'
        ).count()
        painting_count = ProductionItem.query.filter(
            ProductionItem.current_status == 'czeka_na_lakiernie'
        ).count()

        # Pobierz produkty dla aktywnej zakładki
        query = ProductionItem.query.filter(
            ProductionItem.current_status == status_filter
        )

        if sort_by == 'priority':
            query = query.order_by(asc(ProductionItem.priority_rank))
        elif sort_by == 'deadline':
            query = query.order_by(asc(ProductionItem.deadline_date))
        else:
            query = query.order_by(asc(ProductionItem.created_at))

        products_db = query.all()

        products_flat = []
        today = date.today()

        for product in products_db:
            priority_rank = product.priority_rank if product.priority_rank else 999

            dimensions_parts = []
            if product.parsed_length_cm:
                dimensions_parts.append(_format_dimension(product.parsed_length_cm))
            if product.parsed_width_cm:
                dimensions_parts.append(_format_dimension(product.parsed_width_cm))
            if product.parsed_thickness_cm:
                dimensions_parts.append(_format_dimension(product.parsed_thickness_cm))
            dimensions_text = '×'.join(dimensions_parts) + ' cm' if dimensions_parts else None

            volume_m3 = float(product.volume_m3) if product.volume_m3 else 0.0

            qty_done = getattr(product, quantity_done_field, 0) or 0

            # Buduj edge_description z danych strukturalnych
            edge_description = None
            if product.parsed_edge_processing and product.parsed_edge_type:
                parts = [product.parsed_edge_type.capitalize()]
                if product.parsed_edge_radius:
                    parts.append(f'R{product.parsed_edge_radius}')
                if product.parsed_edge_angle:
                    parts.append(f'{product.parsed_edge_angle}°')
                edge_description = ' '.join(parts)

            if product.deadline_date:
                days_diff = (product.deadline_date - today).days
                if days_diff < 0:
                    display_deadline = f"Opóźnione o {abs(days_diff)} dni"
                    priority_class = 'overdue'
                elif days_diff == 0:
                    display_deadline = "Dziś!"
                    priority_class = 'urgent'
                elif days_diff == 1:
                    display_deadline = "Jutro"
                    priority_class = 'warning'
                elif days_diff <= 3:
                    display_deadline = f"Za {days_diff} dni"
                    priority_class = 'warning'
                else:
                    display_deadline = f"Za {days_diff} dni"
                    priority_class = 'normal'
            else:
                display_deadline = "Brak terminu"
                priority_class = 'none'

            product_data = {
                'id': product.short_product_id,
                'internal_order': product.order.internal_order_number if product.order else None,
                'baselinker_order_id': product.order.baselinker_order_id if product.order else None,
                'original_name': product.original_product_name,
                'current_status': product.current_status,
                'priority_rank': priority_rank,
                'deadline_date': product.deadline_date,
                'display_deadline': display_deadline,
                'priority_class': priority_class,
                'volume_m3': volume_m3,
                'wood_species': product.configuration.species if product.configuration else None,
                'technology': product.configuration.technology if product.configuration else None,
                'wood_class': product.configuration.wood_class if product.configuration else None,
                'finish_state': product.parsed_finish_state,
                'finish_type': product.parsed_finish_type,
                'dimensions': dimensions_text,
                'attachment_file_name': product.order.attachment_file_name if product.order else None,
                'attachment_file_url': product.order.attachment_file_url if product.order else None,
                'quantity': product.quantity,
                'quantity_done': qty_done,
                'is_complete': qty_done == product.quantity,
                'is_priority': product.is_priority,
                'order_notes': product.order.order_notes if product.order else None,
                'production_notes': product.production_notes,
                'client_order_number': product.order.client_order_number if product.order else None,
                'parsed_edge_processing': product.parsed_edge_processing,
                'edge_description': edge_description,
                'parsed_edge_type': product.parsed_edge_type,
                'parsed_edge_radius': product.parsed_edge_radius,
                'parsed_edge_angle': product.parsed_edge_angle,
                'parsed_edge_letters': product.parsed_edge_letters,
                'edge_svg': product.edge_svg,
                'shape_svg': product.shape_svg,
                'lamella_direction': product.lamella_direction,
                'has_visual_data': bool(product.shape_svg or product.edge_svg),
                'quantity_done_assembly': product.quantity_done_assembly,
            }

            products_flat.append(product_data)

        config = get_station_config()

        total_products = sum(p['quantity'] for p in products_flat)

        station_stats = {
            'total_products': total_products,
            'total_count': len(products_flat),
            'total_volume': sum((p.get('volume_m3', 0) or 0) * (p.get('quantity', 1) or 1) for p in products_flat)
        }

        now = datetime.utcnow()

        return render_template(
            'stations/finishing.html',
            products_flat=products_flat,
            station_code=station_code,
            station_name='Wykańczanie',
            station_stats=station_stats,
            config=config,
            sort_by=sort_by,
            tab=tab,
            production_count=production_count,
            painting_count=painting_count,
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
# STANOWISKO PAKOWANIA (PACKAGING)
# ============================================================================

@station_bp.route('/packaging')
def packaging_station():
    """
    Interfejs stanowiska pakowania

    ZMIANA: Pokazuje CALE zamowienia jesli choc 1 produkt jest w statusie czeka_na_pakowanie

    Query params:
        sort: priority|deadline|created_at (default: priority)
        view: grid|list (default: list) - pakowanie uzywa widoku listy

    Returns:
        HTML: Interfejs stanowiska pakowania
    """
    try:
        from ...models import ProductionItem, ProductionOrder, ProductionProduct
        from sqlalchemy import asc, desc

        sort_by = request.args.get('sort', 'priority')
        view_mode = request.args.get('view', 'list')

        # NOWA LOGIKA: Znajdz zamowienia ktore maja choc 1 produkt do pakowania
        orders_with_packaging = db.session.query(
            ProductionOrder.internal_order_number
        ).join(
            ProductionProduct, ProductionProduct.order_id == ProductionOrder.id
        ).filter(
            ProductionProduct.current_status == 'czeka_na_pakowanie'
        ).distinct().all()

        order_numbers = [order[0] for order in orders_with_packaging if order[0]]

        if not order_numbers:
            products = []
        else:
            # Pobierz WSZYSTKIE produkty z tych zamowien (niezaleznie od statusu)
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
            else:
                query = query.order_by(asc(ProductionItem.created_at))

            products_db = query.all()

            # Przygotuj dane produktow (uzywajac tej samej logiki co get_products_for_station)
            products = []
            today = date.today()

            for product in products_db:
                priority_rank = product.priority_rank if product.priority_rank else 999

                # Kolor priorytetu
                if priority_rank <= 10:
                    priority_label = 'Najwyzszy'
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
                        display_deadline = "Dzis!"
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
                dimensions_text = '×'.join(dimensions_parts) + ' cm' if dimensions_parts else 'Brak wymiarow'

                volume_m3 = float(product.volume_m3) if product.volume_m3 else 0.0
                total_value = float(product.total_value_net) if product.total_value_net else 0.0

                product_data = {
                    'id': product.short_product_id,
                    'internal_order': product.order.internal_order_number if product.order else None,
                    'baselinker_order_id': product.order.baselinker_order_id if product.order else None,
                    'original_name': product.original_product_name,
                    'current_status': product.current_status,
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
                    'payment_date': product.order.payment_date if product.order else None,
                    'wood_species': product.configuration.species if product.configuration else None,
                    'technology': product.configuration.technology if product.configuration else None,
                    'wood_class': product.configuration.wood_class if product.configuration else None,
                    'dimensions': dimensions_text,
                    'finish_state': product.parsed_finish_state,
                    'finish_type': product.parsed_finish_type,
                    'thickness_group': product.thickness_group,
                    'client_name': product.order.client_name if product.order else None,
                    'display_deadline': display_deadline,
                    'quantity': product.quantity,
                    'quantity_done': product.quantity_done_packaging,
                    'is_complete': product.quantity_done_packaging == product.quantity,
                    'is_priority': product.is_priority,
                    'order_notes': product.order.order_notes if product.order else None,
                    'production_notes': product.production_notes,
                    'client_order_number': product.order.client_order_number if product.order else None,
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
                    'override_delivery_method': product.order.override_delivery_method if product.order else None,
                    # DANE WYSYLKI KURIERSKIEJ (2025-12)
                    'shipping_package_id': product.order.shipping_package_id if product.order else None,
                    'shipping_tracking_number': product.order.shipping_tracking_number if product.order else None,
                    'shipping_courier_name': product.order.shipping_courier_name if product.order else None,
                    'shipping_price': float(product.order.shipping_price) if product.order and product.order.shipping_price else None,
                    'shipping_label_base64': product.order.shipping_label_base64 if product.order else None,
                    'shipping_created_at': product.order.shipping_created_at.isoformat() if product.order and product.order.shipping_created_at else None,
                    'parsed_edge_processing': product.parsed_edge_processing,
                    'parsed_edge_type': product.parsed_edge_type,
                    'parsed_edge_radius': product.parsed_edge_radius,
                    'parsed_edge_angle': product.parsed_edge_angle,
                    'parsed_edge_letters': product.parsed_edge_letters,
                    'edge_svg': product.edge_svg,
                    'shape_svg': product.shape_svg,
                    'lamella_direction': product.lamella_direction,
                    'has_visual_data': bool(product.shape_svg or product.edge_svg),
                }

                products.append(product_data)

        # Grupowanie produktow po zamowieniach (PACKAGING)
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
                    'override_delivery_method': None,
                    # DANE WYSYLKI KURIERSKIEJ (2025-12)
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
            order['total_volume'] += (product['volume_m3'] or 0) * (product.get('quantity', 1) or 1)
            order['total_value'] += product['total_value_net'] or 0

            # Najlepszy priorytet z zamowienia
            if product['priority_rank'] < order['best_priority_rank']:
                order['best_priority_rank'] = product['priority_rank']
                order['priority_label'] = product['priority_label']
                order['priority_class'] = product['priority_class']

            # Najwczesniejszy deadline
            if product['deadline_date']:
                if order['earliest_deadline'] is None or product['deadline_date'] < order['earliest_deadline']:
                    order['earliest_deadline'] = product['deadline_date']
                    order['display_deadline'] = product['display_deadline']

            if product['is_overdue']:
                order['has_overdue'] = True

            # Pobierz dane dostawy z pierwszego produktu w zamowieniu (2025-12)
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

            # override_delivery_method jest decyzja na poziomie zamowienia,
            # ale historycznie zapisywano go tylko na produktach w statusie
            # czeka_na_logistyke. Aby pakowanie nie pokazywalo zlego badge'a
            # gdy pierwszy iterowany produkt nie przeszedl jeszcze logistyki,
            # bierzemy dowolna niepusta wartosc z produktow zamowienia.
            if not order.get('override_delivery_method') and product.get('override_delivery_method'):
                order['override_delivery_method'] = product.get('override_delivery_method')

            # Pobierz dane wysylki z pierwszego produktu ktory je ma (2025-12)
            if order['shipping_package_id'] is None and product.get('shipping_package_id'):
                order['shipping_package_id'] = product.get('shipping_package_id')
                order['shipping_tracking_number'] = product.get('shipping_tracking_number')
                order['shipping_courier_name'] = product.get('shipping_courier_name')
                order['shipping_price'] = product.get('shipping_price')
                order['shipping_label_base64'] = product.get('shipping_label_base64')
                order['shipping_created_at'] = product.get('shipping_created_at')

        # Sortowanie grup zamowien
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
            'avg_priority_rank': sum(p['priority_rank'] for p in products) / len(products) if products else 999,
            'total_volume': sum((p.get('volume_m3', 0) or 0) * (p.get('quantity', 1) or 1) for p in products)
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
        logger.error("Blad interfejsu pakowania", extra={
            'client_ip': request.remote_addr,
            'error': str(e)
        })

        return render_template(
            'stations/error.html',
            error_message="Blad ladowania stanowiska pakowania",
            error_details=str(e),
            back_url=url_for('production.production_stations.station_select')
        ), 500
