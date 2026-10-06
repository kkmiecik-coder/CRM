# modules/production/routers/stations/monitors.py
"""
Station monitors + monitor AJAX endpoints
"""

from flask import render_template, request, url_for, jsonify, redirect
from datetime import datetime, date
from extensions import db
import traceback

from . import (station_bp, logger, get_station_config, MONITOR_STATION_MAP, _get_monitor_station_data,
               _stol_monitora, priorytety_zamowien_monitora, _klucz_rangi)
from ...services.station_catalog import resolve_station_code
from modules.production.logistics import sposoby


# ============================================================================
# WYBOR STANOWISKA
# ============================================================================

@station_bp.route('/')
@station_bp.route('/station-select')
def station_select():
    """
    Panele wykonawcze stanowisk zniknely w Etapie 0 profili pracownikow
    (docs/worker-profiles-backend.md) - przekierowanie na wybor monitora hali.
    """
    return redirect(url_for('production.production_stations.monitors_select'))


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
        # Okres przejsciowy: telewizory maja wbity stary adres /monitors/finishing.
        # Zdjac razem z STATION_CODE_ALIASES (krok 20 kolejnosci wdrozenia).
        station_code = resolve_station_code(station_code)

        if station_code not in MONITOR_STATION_MAP:
            return render_template(
                'stations/access_denied.html',
                error_message=f"Nieznane stanowisko: {station_code}",
                error_details="Dostepne: " + ", ".join(MONITOR_STATION_MAP),
                back_url=url_for('production.production_stations.monitors_select')
            ), 404

        station_info = MONITOR_STATION_MAP[station_code]
        # Stół i odłożone (priorytety, spec 7.2) — Lakiernia: None. Monitor nigdy nie dopełnia stołu.
        stol = _stol_monitora(station_code)
        orders, monitor_stats, species_stats = _get_monitor_station_data(station_code, stol=stol)
        config = get_station_config()
        now = datetime.utcnow()

        return render_template(
            'stations/monitor_station.html',
            orders=orders,
            monitor_stats=monitor_stats,
            species_stats=species_stats,
            stol=stol,
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
        # Ten sam alias co w widoku HTML — inaczej monitor wszedlby po staremu,
        # a pierwsze auto-odswiezenie dostaloby 404.
        station_code = resolve_station_code(station_code)

        if station_code not in MONITOR_STATION_MAP:
            return jsonify({'success': False, 'error': f'Unknown station: {station_code}'}), 404

        stol = _stol_monitora(station_code)
        orders, monitor_stats, species_stats = _get_monitor_station_data(station_code, stol=stol)

        return jsonify({
            'success': True,
            'orders': orders,
            'stats': monitor_stats,
            'species_stats': species_stats,
            'stol': stol,
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

# Status pozycji → (stanowisko, kolumna licznika sztuk), etykieta i klasa CSS — JEDNA kopia dla widoku HTML
# i AJAX-a (dawniej dwie niezależne kopie dawały „dobrze po wejściu, źle po pierwszym auto-odświeżeniu”).
STATUS_TO_STATION = {
    'czeka_na_wyciecie': ('cutting', 'quantity_done_cutting'),
    'czeka_na_skladanie': ('assembly', 'quantity_done_assembly'),
    'czeka_na_sklejanie': ('gluing', 'quantity_done_gluing'),
    'czeka_na_formatowanie': ('formatting', 'quantity_done_formatting'),
    'czeka_na_krawedzie': ('edges', 'quantity_done_edges'),
    'czeka_na_lakiernie': ('painting', 'quantity_done_painting'),
    'czeka_na_pakowanie': ('packaging', 'quantity_done_packaging'),
}

STATUS_LABELS = {
    'czeka_na_wyciecie': 'Wycinanie - mikro',
    'czeka_na_skladanie': 'Składanie - lite',
    'czeka_na_sklejanie': 'Sklejanie',
    'czeka_na_formatowanie': 'Formatowanie',
    'czeka_na_krawedzie': 'Krawędzie',
    'czeka_na_lakiernie': 'Lakiernia',
    'czeka_na_pakowanie': 'Pakowanie',
    'spakowane': 'Spakowane',
    'zweryfikowane': 'Zweryfikowane',
    'zaladowane': 'Załadowane',
    'dostarczone': 'Dostarczone',
}

STATUS_CLASS_MAP = {
    'czeka_na_wyciecie': 'status-cutting',
    'czeka_na_skladanie': 'status-assembly',
    'czeka_na_sklejanie': 'status-gluing',
    'czeka_na_formatowanie': 'status-formatting',
    'czeka_na_krawedzie': 'status-edges',
    'czeka_na_lakiernie': 'status-painting',
    'czeka_na_pakowanie': 'status-packaging',
    'spakowane': 'status-completed',
    'zweryfikowane': 'status-completed',
    'zaladowane': 'status-completed',
    'dostarczone': 'status-completed',
}


def _zamowienia_monitora_ogolnego():
    """
    Zamówienia monitora zbiorczego (wszystkie z pozycją przed spakowaniem) z postępem na dominującym stanowisku,
    gwiazdkami i plakietką szczebla — JEDNA funkcja dla widoku HTML i AJAX-a. Grupowanie po `ProductionOrder.id`
    (numer powtarza się co rok). Trzy zapytania zamiast N+1: id zamówień, ich pozycje, dane zamówień; priorytety
    z kolumn (`priorytety_zamowien_monitora`). Kolejność: ranga zamówienia (NULLS LAST), numer.
    Returns: (orders, stats)
    """
    from ...models import ProductionOrder, ProductionProduct

    ids = [wiersz[0] for wiersz in (
        db.session.query(ProductionOrder.id)
        .join(ProductionProduct, ProductionProduct.order_id == ProductionOrder.id)
        .filter(ProductionProduct.current_status.notin_(sposoby.STATUSY_PO_SPAKOWANIU),
                ProductionOrder.internal_order_number.isnot(None))
        .distinct().all())]
    if not ids:
        return [], {'total_orders': 0, 'completed_orders': 0, 'total_products': 0, 'total_volume': 0}
    ids.sort()
    dane_zamowien = {wiersz[0]: wiersz for wiersz in (
        db.session.query(ProductionOrder.id, ProductionOrder.internal_order_number,
                         ProductionOrder.baselinker_order_id, ProductionOrder.client_order_number)
        .filter(ProductionOrder.id.in_(ids)).all())}
    pozycje = {}
    for produkt in (ProductionProduct.query.filter(ProductionProduct.order_id.in_(ids))
                    .order_by(ProductionProduct.id).all()):
        pozycje.setdefault(produkt.order_id, []).append(produkt)
    priorytety = priorytety_zamowien_monitora(ids)

    orders = []
    for order_id in ids:
        products = pozycje.get(order_id)
        if not products:
            continue
        _id, order_number, baselinker_id, client_order_number = dane_zamowien[order_id]

        # Oblicz statystyki zamowienia - NOWA LOGIKA Z QUANTITY
        total_products = sum(p.quantity for p in products)  # Suma wszystkich sztuk
        total_volume = sum((p.volume_m3 or 0) * p.quantity for p in products)  # Objetosc * ilosc

        # Dominujacy status = ten z najwieksza liczba produktow
        status_counts = {}
        for p in products:
            status = p.current_status or 'unknown'
            status_counts[status] = status_counts.get(status, 0) + p.quantity
        dominant_status = max(status_counts, key=status_counts.get)

        # completed_products na podstawie quantity_done dla dominujacego stanowiska
        completed_products = 0
        if dominant_status in STATUS_TO_STATION:
            _station_code, quantity_done_col = STATUS_TO_STATION[dominant_status]
            for p in products:
                completed_products += getattr(p, quantity_done_col, 0)
        elif dominant_status in sposoby.STATUSY_PO_SPAKOWANIU:
            completed_products = total_products

        priorytet = priorytety.get(order_id) or {}
        orders.append({
            'order_id': order_id,
            'order_number': order_number,
            'baselinker_order_id': baselinker_id,
            'client_order_number': client_order_number,
            'total_products': total_products,
            'completed_products': completed_products,
            'total_volume': total_volume,
            'status_label': STATUS_LABELS.get(dominant_status, dominant_status),
            'status_class': STATUS_CLASS_MAP.get(dominant_status, 'status-unknown'),
            'dominant_status': dominant_status,
            'gwiazdki': priorytet.get('gwiazdki', 0),
            'ranga': priorytet.get('ranga'),
            'szczebel': priorytet.get('szczebel'),
            'plakietka': priorytet.get('plakietka'),
        })

    # Kolejność po randze zamówienia (priorytety, spec 7.2), nie po postępie
    orders.sort(key=_klucz_rangi)

    stats = {
        'total_orders': len(orders),
        'completed_orders': sum(1 for o in orders if o['dominant_status'] in sposoby.STATUSY_PO_SPAKOWANIU),
        'total_products': sum(o['total_products'] for o in orders),
        'total_volume': sum(o['total_volume'] for o in orders)
    }
    return orders, stats


@station_bp.route('/monitor')
def production_monitor():
    """
    Monitor produkcji - widok wszystkich zamowien z postepem na biezacym stanowisku

    Wyswietla zamowienia z:
    - Postepem (X/Y) bazujacym na quantity_done dla biezacego stanowiska
    - Statusem zamowienia
    - Objetoscia
    - Gwiazdkami i plakietka szczebla (kolejnosc po randze)

    Returns:
        HTML: Interfejs monitora produkcji
    """
    try:
        orders, monitor_stats = _zamowienia_monitora_ogolnego()
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
    AJAX endpoint dla monitora produkcji — te same dane co widok HTML (`_zamowienia_monitora_ogolnego`).

    Returns:
        JSON: {
            success: bool,
            orders: [...],
            stats: {...}
        }
    """
    try:
        orders, stats = _zamowienia_monitora_ogolnego()

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
