# modules/production/routers/api/logistics_api.py
"""
Logistics API endpoints — list orders awaiting logistics decision,
approve transport method, and update production notes.
"""

from flask import request, jsonify
from flask_login import login_required, current_user
from extensions import db
from sqlalchemy import func
from sqlalchemy.orm import joinedload

from . import api_bp
from ...models import ProductionItem, ProductionOrder, get_local_now
from modules.logging import get_structured_logger

logger = get_structured_logger('production.api.logistics')

VALID_TRANSPORT_METHODS = ('kurier_baselinker', 'transport_woodpower')


@api_bp.route('/logistics/orders')
@login_required
def logistics_orders():
    """
    GET /logistics/orders — List orders awaiting a logistics decision.

    Returns orders grouped by internal_order_number where at least one
    ProductionItem has current_status == 'czeka_na_logistyke'.
    Sorted by earliest deadline ascending.
    """
    try:
        items = (
            ProductionItem.query
            .options(
                joinedload(ProductionItem.order),
                joinedload(ProductionItem.configuration),
            )
            .filter(ProductionItem.current_status == 'czeka_na_logistyke')
            .order_by(db.case((ProductionItem.deadline_date.is_(None), 1), else_=0), ProductionItem.deadline_date.asc())
            .all()
        )

        # Group by internal_order_number
        orders_map = {}
        for item in items:
            order_number = item.order.internal_order_number if item.order else None
            if order_number not in orders_map:
                orders_map[order_number] = {
                    'order_number': order_number,
                    'baselinker_order_id': item.order.baselinker_order_id if item.order else None,
                    'client_name': item.order.client_name if item.order else None,
                    'delivery_method': item.order.delivery_method if item.order else None,
                    'delivery_address': {
                        'address': item.order.delivery_address if item.order else None,
                        'city': item.order.delivery_city if item.order else None,
                        'postcode': item.order.delivery_postcode if item.order else None,
                        'country_code': item.order.delivery_country_code if item.order else None,
                    },
                    'production_notes': item.production_notes,
                    'products': [],
                    'earliest_deadline': None,
                }

            entry = orders_map[order_number]

            entry['products'].append({
                'id': item.id,
                'short_product_id': item.short_product_id,
                'original_product_name': item.original_product_name,
                'volume_m3': float(item.volume_m3 or 0),
                'quantity': item.quantity,
            })

            # Track earliest deadline
            if item.deadline_date is not None:
                current_earliest = entry['earliest_deadline']
                if current_earliest is None or item.deadline_date < current_earliest:
                    entry['earliest_deadline'] = item.deadline_date

        # Build final list with computed aggregates, sorted by deadline
        orders = []
        for entry in orders_map.values():
            products = entry['products']
            entry['total_volume'] = round(sum(p['volume_m3'] * p.get('quantity', 1) for p in products), 4)
            entry['total_products'] = len(products)
            # Serialize deadline
            if entry['earliest_deadline'] is not None:
                entry['earliest_deadline'] = entry['earliest_deadline'].isoformat()
            orders.append(entry)

        # Sort: orders without a deadline go last
        orders.sort(key=lambda o: (o['earliest_deadline'] is None, o['earliest_deadline'] or ''))

        logger.info("Pobrano zamówienia czekające na logistykę", extra={
            'user_id': current_user.id,
            'count': len(orders),
        })

        return jsonify({
            'success': True,
            'orders': orders,
            'total': len(orders),
        })

    except Exception as e:
        logger.error("Błąd pobierania zamówień logistycznych", extra={
            'user_id': current_user.id,
            'error': str(e),
        })
        return jsonify({'success': False, 'error': str(e)}), 500


@api_bp.route('/logistics/approve', methods=['POST'])
@login_required
def logistics_approve():
    """
    POST /logistics/approve — Approve transport method for an order.

    Body: { order_number, transport_method }
    transport_method must be 'kurier_baselinker' or 'transport_woodpower'.

    Updates ProductionItems with matching internal_order_number:
      - override_delivery_method = transport_method (na WSZYSTKICH produktach
        zamówienia, niezależnie od statusu — decyzja o transporcie jest na
        poziomie zamówienia, nie pojedynczego produktu)
      - logistics_completed_at + status='czeka_na_pakowanie' tylko na tych
        produktach, które aktualnie są w 'czeka_na_logistyke'
    """
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'Brak danych JSON'}), 400

        order_number = data.get('order_number')
        transport_method = data.get('transport_method')

        if not order_number:
            return jsonify({'success': False, 'error': 'Wymagane pole: order_number'}), 400
        if not transport_method:
            return jsonify({'success': False, 'error': 'Wymagane pole: transport_method'}), 400
        if transport_method not in VALID_TRANSPORT_METHODS:
            return jsonify({
                'success': False,
                'error': f'Nieprawidłowa metoda transportu. Dozwolone: {list(VALID_TRANSPORT_METHODS)}',
            }), 400

        all_items = (
            ProductionItem.query.join(ProductionOrder)
            .filter(ProductionOrder.internal_order_number == order_number)
            .all()
        )

        waiting_items = [i for i in all_items if i.current_status == 'czeka_na_logistyke']

        if not waiting_items:
            return jsonify({
                'success': False,
                'error': f'Nie znaleziono produktów oczekujących na logistykę dla zamówienia {order_number}',
            }), 404

        now = get_local_now()

        for item in all_items:
            item.order.override_delivery_method = transport_method

        for item in waiting_items:
            item.order.logistics_completed_at = now
            item.current_status = 'czeka_na_pakowanie'

        db.session.commit()

        logger.info("Zatwierdzono transport dla zamówienia", extra={
            'user_id': current_user.id,
            'order_number': order_number,
            'transport_method': transport_method,
            'override_propagated_count': len(all_items),
            'advanced_to_packaging_count': len(waiting_items),
        })

        return jsonify({
            'success': True,
            'order_number': order_number,
            'transport_method': transport_method,
            'updated_products': len(waiting_items),
        })

    except Exception as e:
        db.session.rollback()
        logger.error("Błąd zatwierdzania transportu", extra={
            'user_id': current_user.id,
            'error': str(e),
        })
        return jsonify({'success': False, 'error': str(e)}), 500


@api_bp.route('/logistics/update-notes', methods=['POST'])
@login_required
def logistics_update_notes():
    """
    POST /logistics/update-notes — Update production notes for an order.

    Body: { order_number, notes }
    Updates production_notes on all ProductionItems with that
    internal_order_number.
    """
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'Brak danych JSON'}), 400

        order_number = data.get('order_number')
        notes = data.get('notes', '')

        if not order_number:
            return jsonify({'success': False, 'error': 'Wymagane pole: order_number'}), 400

        items = (
            ProductionItem.query.join(ProductionOrder)
            .filter(ProductionOrder.internal_order_number == order_number)
            .all()
        )

        if not items:
            return jsonify({
                'success': False,
                'error': f'Nie znaleziono produktów dla zamówienia {order_number}',
            }), 404

        for item in items:
            item.production_notes = notes

        db.session.commit()

        logger.info("Zaktualizowano notatki produkcyjne", extra={
            'user_id': current_user.id,
            'order_number': order_number,
            'updated_count': len(items),
        })

        return jsonify({
            'success': True,
            'order_number': order_number,
            'updated_products': len(items),
        })

    except Exception as e:
        db.session.rollback()
        logger.error("Błąd aktualizacji notatek", extra={
            'user_id': current_user.id,
            'error': str(e),
        })
        return jsonify({'success': False, 'error': str(e)}), 500
