# modules/production/routers/api/reports_api.py
"""
Reports tab content endpoints.
Extracted from api_routers.py.
"""

from datetime import datetime, date, timedelta
from flask import request, jsonify, render_template
from flask_login import login_required, current_user
from extensions import db
from sqlalchemy import func

from . import api_bp, logger, ProductionItem, ProductionSyncLog, get_local_now


@api_bp.route('/reports-tab-content')
@login_required
def reports_tab_content():
    """
    AJAX endpoint dla zawartości taba Raporty - POPRAWIONY
    """
    try:
        logger.info("AJAX: Ładowanie zawartości reports-tab", extra={
            'user_id': current_user.id,
            'user_role': getattr(current_user, 'role', 'unknown')
        })
        
        from ...models import ProductionItem, ProductionSyncLog
        
        # Przygotuj dane dla raportów
        today = date.today()
        week_ago = today - timedelta(days=7)
        month_ago = today - timedelta(days=30)
        
        # Raporty wydajności
        daily_stats = []
        for i in range(7):
            day = today - timedelta(days=i)
            day_start = datetime.combine(day, datetime.min.time())
            day_end = datetime.combine(day, datetime.max.time())
            
            completed = ProductionItem.query.filter(
                ProductionItem.current_status == 'spakowane',
                ProductionItem.packaging_completed_at >= day_start,
                ProductionItem.packaging_completed_at <= day_end
            ).count()
            
            volume = db.session.query(db.func.sum(ProductionItem.volume_m3))\
                              .filter(
                                  ProductionItem.current_status == 'spakowane',
                                  ProductionItem.packaging_completed_at >= day_start,
                                  ProductionItem.packaging_completed_at <= day_end
                              ).scalar() or 0.0
            
            daily_stats.append({
                'date': day.isoformat(),
                'completed_orders': completed,
                'total_volume': float(volume)
            })
        
        # Raport statusów - dynamicznie ze wszystkich istniejących w bazie
        status_stats = db.session.query(
            ProductionItem.current_status,
            func.count(ProductionItem.id).label('count'),
            func.sum(ProductionItem.volume_m3).label('volume')
        ).filter(
            ProductionItem.current_status.isnot(None)
        ).group_by(ProductionItem.current_status).all()

        status_report = [
            {
                'status': row[0],
                'count': row[1],
                'volume': float(row[2] or 0)
            }
            for row in status_stats
        ]
        
        # Historia synchronizacji (ostatnie 10)
        sync_history = ProductionSyncLog.query\
                                       .order_by(ProductionSyncLog.sync_started_at.desc())\
                                       .limit(10).all()

        # Rozkład według gatunków drewna
        species_stats = db.session.query(
            ProductionItem.parsed_wood_species,
            func.count(ProductionItem.id).label('count'),
            func.sum(ProductionItem.volume_m3).label('volume')
        ).filter(
            ProductionItem.parsed_wood_species.isnot(None),
            ProductionItem.current_status != 'anulowane'
        ).group_by(ProductionItem.parsed_wood_species).all()

        species_breakdown = [
            {
                'name': row[0] or 'Nieokreślony',
                'count': row[1],
                'volume': float(row[2] or 0)
            }
            for row in species_stats
        ]

        # Rozkład według grubości
        thickness_stats = db.session.query(
            ProductionItem.parsed_thickness_cm,
            func.count(ProductionItem.id).label('count'),
            func.sum(ProductionItem.volume_m3).label('volume')
        ).filter(
            ProductionItem.parsed_thickness_cm.isnot(None),
            ProductionItem.current_status != 'anulowane'
        ).group_by(ProductionItem.parsed_thickness_cm).all()

        thickness_breakdown = [
            {
                'thickness': float(row[0]) if row[0] else 0,
                'count': row[1],
                'volume': float(row[2] or 0)
            }
            for row in thickness_stats
        ]
        # Sortowanie po grubości
        thickness_breakdown.sort(key=lambda x: x['thickness'])

        # Rozkład według technologii
        technology_stats = db.session.query(
            ProductionItem.parsed_technology,
            func.count(ProductionItem.id).label('count'),
            func.sum(ProductionItem.volume_m3).label('volume')
        ).filter(
            ProductionItem.parsed_technology.isnot(None),
            ProductionItem.current_status != 'anulowane'
        ).group_by(ProductionItem.parsed_technology).all()

        technology_breakdown = [
            {
                'name': row[0] or 'Nieokreślona',
                'count': row[1],
                'volume': float(row[2] or 0)
            }
            for row in technology_stats
        ]

        # Rozkład według klasy drewna
        wood_class_stats = db.session.query(
            ProductionItem.parsed_wood_class,
            func.count(ProductionItem.id).label('count'),
            func.sum(ProductionItem.volume_m3).label('volume')
        ).filter(
            ProductionItem.parsed_wood_class.isnot(None),
            ProductionItem.parsed_wood_class != '',
            ProductionItem.current_status != 'anulowane'
        ).group_by(ProductionItem.parsed_wood_class).all()

        wood_class_breakdown = [
            {
                'name': row[0] or 'Nieokreślona',
                'count': row[1],
                'volume': float(row[2] or 0)
            }
            for row in wood_class_stats
        ]

        # Przygotuj dane jako dict dla JSON response
        reports_data_dict = {
            'daily_performance': daily_stats,
            'status_breakdown': status_report,
            'species_breakdown': species_breakdown,
            'thickness_breakdown': thickness_breakdown,
            'technology_breakdown': technology_breakdown,
            'wood_class_breakdown': wood_class_breakdown,
            'sync_history': [
                {
                    'date': sync.sync_started_at.isoformat(),
                    'status': sync.sync_status,  # POPRAWIONE: sync_status zamiast status
                    'items_processed': (sync.products_created or 0) + (sync.products_updated or 0),
                    'duration_seconds': sync.sync_duration_seconds or 0
                }
                for sync in sync_history
            ],
            'summary': {
                'week_completed': sum(day['completed_orders'] for day in daily_stats),
                'week_volume': sum(day['total_volume'] for day in daily_stats),
                'total_in_system': sum(item['count'] for item in status_report)
            }
        }

        # Renderuj komponent - używamy dict z bracket notation w Jinja
        rendered_html = render_template('components/reports-tab-content.html',
                              reports_data=reports_data_dict)
        
        return jsonify({
            'success': True,
            'html': rendered_html,
            'data': reports_data_dict,  # Zwracamy dict dla JSON
            'last_updated': get_local_now().isoformat()
        })
        
    except Exception as e:
        logger.error("Błąd AJAX reports-tab-content", extra={
            'user_id': current_user.id,
            'error': str(e)
        })
        
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500



