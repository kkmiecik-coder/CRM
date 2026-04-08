# modules/production/routers/stations/monitors.py
"""
Station monitors + monitor AJAX endpoints
"""

from flask import render_template, request, url_for, jsonify
from datetime import datetime, date
from extensions import db
import traceback

from . import station_bp, logger, get_station_config, get_station_summary, MONITOR_STATION_MAP, _get_monitor_station_data


# ============================================================================
# WYBOR STANOWISKA
# ============================================================================

@station_bp.route('/')
@station_bp.route('/station-select')
def station_select():
    """
    Interfejs wyboru stanowiska (strona glowna dla stanowisk)

    Returns:
        HTML: Interfejs wyboru stanowiska
    """
    try:
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
            page_title="Wybor stanowiska produkcyjnego"
        )

    except Exception as e:
        logger.error("Blad interfejsu wyboru stanowiska", extra={
            'client_ip': request.remote_addr,
            'error': str(e)
        })

        # Fallback template z bledem
        return render_template(
            'stations/access_denied.html',
            error_message="Blad ladowania interfejsu wyboru stanowiska",
            error_details=str(e),
            back_url=None
        ), 500


# ============================================================================
# MONITORING ZLECEN
# ============================================================================

@station_bp.route('/monitors')
@station_bp.route('/monitors/')
def monitors_select():
    """Wybor stanowiska do monitoringu zlecen na TV"""
    try:
        return render_template('stations/monitors_select.html')
    except Exception as e:
        logger.error("Blad wyboru monitoringu", extra={
            'error': str(e)
        })
        return render_template(
            'stations/access_denied.html',
            error_message="Blad ladowania wyboru monitoringu",
            error_details=str(e),
            back_url=None
        ), 500


@station_bp.route('/monitors/<station_code>')
def monitor_station(station_code):
    """Monitor zlecen dla konkretnego stanowiska (widok TV)"""
    try:
        if station_code not in MONITOR_STATION_MAP:
            return render_template(
                'stations/access_denied.html',
                error_message=f"Nieznane stanowisko: {station_code}",
                error_details="Dostepne: cutting, assembly, gluing, formatting, finishing, packaging",
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
        logger.error("Blad monitora stanowiska", extra={
            'station': station_code,
            'error': str(e),
            'traceback': traceback.format_exc()
        })
        return render_template(
            'stations/error.html',
            error_message=f"Blad monitora stanowiska {station_code}",
            error_details=str(e),
            back_url=url_for('production.production_stations.monitors_select')
        ), 500


@station_bp.route('/ajax/monitors/<station_code>')
def ajax_monitor_station_data(station_code):
    """AJAX endpoint dla monitora stanowiska -- zwraca JSON z zamowieniami i stats"""
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
        logger.error("Blad AJAX monitor stanowiska", extra={
            'station': station_code,
            'error': str(e),
            'traceback': traceback.format_exc()
        })
        return jsonify({'success': False, 'error': str(e)}), 500


# ============================================================================
# MONITOR PRODUKCJI (OGOLNY)
# ============================================================================

@station_bp.route('/monitor')
def production_monitor():
    """
    Monitor produkcji - widok wszystkich zamowien z postepem na biezacym stanowisku

    Wyswietla zamowienia z:
    - Postepem (X/Y) bazujacym na quantity_done dla biezacego stanowiska
    - Statusem zamowienia
    - Objetoscia

    Returns:
        HTML: Interfejs monitora produkcji
    """
    try:
        from ...models import ProductionItem
        from sqlalchemy import func, case, and_

        # Mapowanie statusu na stanowisko i kolumne quantity_done
        status_to_station = {
            'czeka_na_wyciecie': ('cutting', 'quantity_done_cutting'),
            'czeka_na_skladanie': ('assembly', 'quantity_done_assembly'),
            'czeka_na_sklejanie': ('gluing', 'quantity_done_gluing'),
            'czeka_na_formatowanie': ('formatting', 'quantity_done_formatting'),
            'czeka_na_wykanczanie': ('finishing', 'quantity_done_finishing'),
            'czeka_na_pakowanie': ('packaging', 'quantity_done_packaging'),
        }

        status_labels = {
            'czeka_na_wyciecie': 'Wycinanie - mikro',
            'czeka_na_skladanie': 'Składanie - lite',
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

        # Pobierz wszystkie aktywne zamowienia (nie spakowane)
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

            # Pobierz wszystkie produkty tego zamowienia
            products = ProductionItem.query.filter(
                ProductionItem.internal_order_number == order_number
            ).all()

            if not products:
                continue

            # Oblicz statystyki zamowienia - NOWA LOGIKA Z QUANTITY
            total_products = sum(p.quantity for p in products)  # Suma wszystkich sztuk
            total_volume = sum((p.volume_m3 or 0) * p.quantity for p in products)  # Objetosc * ilosc

            # Znajdz dominujacy status (status z najwieksza liczba produktow)
            status_counts = {}
            for p in products:
                status = p.current_status or 'unknown'
                status_counts[status] = status_counts.get(status, 0) + p.quantity

            # Dominujacy status = ten z najwieksza liczba produktow
            dominant_status = max(status_counts, key=status_counts.get)

            # Oblicz completed_products na podstawie quantity_done dla dominujacego stanowiska
            completed_products = 0
            if dominant_status in status_to_station:
                station_code, quantity_done_col = status_to_station[dominant_status]
                # Suma quantity_done dla wszystkich pozycji na tym stanowisku
                for p in products:
                    completed_products += getattr(p, quantity_done_col, 0)
            elif dominant_status == 'spakowane':
                # Wszystkie produkty sa gotowe
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

        # Sortuj zamowienia (najpierw te z najwyzszym postepem, potem alfabetycznie)
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
        logger.error("Blad monitora produkcji", extra={
            'client_ip': request.remote_addr,
            'error': str(e),
            'traceback': traceback.format_exc()
        })

        return render_template(
            'stations/error.html',
            error_message="Blad ladowania monitora produkcji",
            error_details=str(e),
            back_url=url_for('production.production_stations.station_select')
        ), 500


@station_bp.route('/ajax/monitor')
def ajax_production_monitor():
    """
    AJAX endpoint dla monitora produkcji

    Zwraca liste zamowien z postepem (quantity_done) dla biezacego stanowiska.

    Returns:
        JSON: {
            success: bool,
            orders: [...],
            stats: {...}
        }
    """
    try:
        from ...models import ProductionItem

        # Mapowanie statusu na kolumne quantity_done
        status_to_station = {
            'czeka_na_wyciecie': ('cutting', 'quantity_done_cutting'),
            'czeka_na_skladanie': ('assembly', 'quantity_done_assembly'),
            'czeka_na_sklejanie': ('gluing', 'quantity_done_gluing'),
            'czeka_na_formatowanie': ('formatting', 'quantity_done_formatting'),
            'czeka_na_wykanczanie': ('finishing', 'quantity_done_finishing'),
            'czeka_na_pakowanie': ('packaging', 'quantity_done_packaging'),
        }

        status_labels = {
            'czeka_na_wyciecie': 'Wycinanie - mikro',
            'czeka_na_skladanie': 'Składanie - lite',
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

        # Pobierz wszystkie aktywne zamowienia (nie spakowane)
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

            # Pobierz wszystkie produkty tego zamowienia
            products = ProductionItem.query.filter(
                ProductionItem.internal_order_number == order_number
            ).all()

            if not products:
                continue

            # Oblicz statystyki zamowienia - NOWA LOGIKA Z QUANTITY
            total_products = sum(p.quantity for p in products)
            total_volume = sum((p.volume_m3 or 0) * p.quantity for p in products)

            # Znajdz dominujacy status
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

        # Sortuj zamowienia
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
        logger.error("Blad AJAX monitor", extra={
            'error': str(e),
            'traceback': traceback.format_exc()
        })

        return jsonify({
            'success': False,
            'error': str(e)
        }), 500
