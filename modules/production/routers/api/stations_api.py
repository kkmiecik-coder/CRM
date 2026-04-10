# modules/production/routers/api/stations_api.py
"""
Stations tab content endpoints.
Extracted from api_routers.py.
"""

from datetime import datetime, date, timedelta
from flask import request, jsonify, render_template
from flask_login import login_required, current_user
from extensions import db

from . import api_bp, logger, ProductionItem, get_local_now


@api_bp.route('/stations-tab-content')
@login_required  
def stations_tab_content():
    """
    AJAX endpoint dla zawartości taba Stanowiska - POPRAWIONY
    """
    try:
        logger.info("AJAX: Ładowanie zawartości stations-tab", extra={
            'user_id': current_user.id,
            'user_role': getattr(current_user, 'role', 'unknown')
        })
        
        from ...models import ProductionItem
        
        # Dane dla każdego stanowiska
        stations_data = {}
        stations = ['cutting', 'assembly', 'gluing', 'formatting', 'finishing', 'packaging']
        
        for station in stations:
            status_map = {
                'cutting': 'czeka_na_wyciecie',
                'assembly': 'czeka_na_skladanie',
                'gluing': 'czeka_na_sklejanie',
                'formatting': 'czeka_na_formatowanie',
                'finishing': 'czeka_na_wykanczanie',
                'packaging': 'czeka_na_pakowanie'
            }
            
            status = status_map[station]
            
            # Produkty oczekujące na danym stanowisku
            pending_products = ProductionItem.query\
                                           .filter_by(current_status=status)\
                                           .order_by(ProductionItem.priority_rank.asc())\
                                           .limit(20).all()

            # Statystyki stanowiska
            total_pending = ProductionItem.query.filter_by(current_status=status).count()
            high_priority = ProductionItem.query.filter(
                ProductionItem.current_status == status,
                ProductionItem.priority_rank <= 100
            ).count()
            
            # Dzisiejsze wykonania
            today = date.today()
            today_start = datetime.combine(today, datetime.min.time())

            # TYMCZASOWE: Pola gluing/formatting/finishing_completed_at nie istnieją jeszcze w modelu
            # Zostaną dodane w Zadaniu 2 (Backend Integration)
            completed_field_map = {
                'cutting': 'cutting_completed_at',
                'assembly': 'assembly_completed_at',
                'gluing': 'gluing_completed_at',
                'formatting': 'formatting_completed_at',
                'finishing': 'finishing_completed_at',
                'packaging': 'packaging_completed_at'
            }

            field_name = completed_field_map[station]

            # Sprawdź czy pole istnieje w modelu
            try:
                completed_field = getattr(ProductionItem, field_name)
                today_completed = ProductionItem.query.filter(
                    completed_field >= today_start
                ).count()

                today_volume = db.session.query(db.func.sum(ProductionItem.volume_m3 * ProductionItem.quantity))\
                                       .filter(completed_field >= today_start)\
                                       .scalar() or 0.0
            except AttributeError:
                # Pole nie istnieje jeszcze w modelu - zwróć 0
                today_completed = 0
                today_volume = 0.0
            
            # POPRAWIONE: twórz słowniki zamiast obiektów z .days_diff
            stations_data[station] = {
                'name': {
                    'cutting': 'Wycinanie - mikro',
                    'assembly': 'Składanie - lite',
                    'gluing': 'Sklejanie',
                    'formatting': 'Formatowanie',
                    'finishing': 'Wykańczanie',
                    'packaging': 'Pakowanie'
                }[station],
                'icon': {
                    'cutting': '🪚',
                    'assembly': '🔧',
                    'gluing': '🧲',
                    'formatting': '📐',
                    'finishing': '✨',
                    'packaging': '📦'
                }[station],
                'pending_products': [
                    {
                        'short_id': p.short_product_id,
                        'product_name': p.original_product_name[:50] + '...' if len(p.original_product_name or '') > 50 else (p.original_product_name or ''),
                        'priority_rank': p.priority_rank,
                        'deadline_date': p.deadline_date.isoformat() if p.deadline_date else None,
                        'days_remaining': (p.deadline_date - today).days if p.deadline_date else 0,
                        'volume_m3': float(p.volume_m3 or 0),
                        'internal_order_number': p.internal_order_number
                    }
                    for p in pending_products
                ],
                'stats': {
                    'total_pending': total_pending,
                    'high_priority': high_priority,
                    'today_completed': today_completed,
                    'today_volume': float(today_volume)
                }
            }
        
        # Renderuj komponent
        rendered_html = render_template('components/stations-tab-content.html',
                              stations_data=stations_data)
        
        return jsonify({
            'success': True,
            'html': rendered_html,
            'data': stations_data,
            'last_updated': get_local_now().isoformat()
        })
        
    except Exception as e:
        logger.error("Błąd AJAX stations-tab-content", extra={
            'user_id': current_user.id,
            'error': str(e)
        })
        
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500
  

