# modules/production/routers/api/dashboard_api.py
"""
Dashboard tab content + data endpoints.
Extracted from api_routers.py.
"""

import traceback
from datetime import datetime, date, timedelta
from flask import request, jsonify, render_template
from flask_login import login_required, current_user
from extensions import db
from sqlalchemy import func, and_
from sqlalchemy.orm import joinedload

from . import api_bp, logger, ProductionItem, ProductionError, ProductionSyncLog, get_local_now
from modules.production.models import ProductionOrder
from ...services.station_events_service import (
    get_station_work_in_range,
    get_station_work_per_day,
)
from ...services.station_catalog import (
    STATION_ORDER, STATION_PENDING_STATUS,
    station_label as station_label_catalog,
)
from ...services.dashboard_alerts import build_deadline_alerts


# Mapowanie stanowisko → status czekania (kolejka).
#
# Same nazwy statusów mieszkają w station_catalog.STATION_PENDING_STATUS —
# to jedyne źródło, wspólne z mobile_api_service i z raportami. Wcześniej
# dashboard miał własną kopię i przy pierwszej zmianie nazwy statusu kafelki
# rozjechałyby się z resztą aplikacji po cichu.
#
# ZESTAW stanowisk jest tu WĘŻSZY niż w katalogu i to jest jawna decyzja, nie
# przeoczenie: dashboard rysuje sześć kafelków i nie zna lakierni (nie ma jej
# ani w _station_count_map niżej, ani w szablonie). Raport „Dni zapasu przed
# stanowiskiem" pokazuje wszystkie siedem i to właśnie lakiernia ma dziś
# najdłuższą kolejkę — dołożenie jej tutaj wymaga decyzji właściciela i zmiany
# szablonu dashboardu, więc idzie osobnym zadaniem.
_DASHBOARD_STATIONS = (
    'cutting', 'assembly', 'gluing', 'formatting', 'finishing', 'packaging',
)
_STATION_PENDING_STATUS = {
    kod: STATION_PENDING_STATUS[kod] for kod in _DASHBOARD_STATIONS
}


def _safe_station_work(station_code, day_start, day_end):
    """Helper: pobiera agregat pracy stanowiska w przedziale, z fallbackiem na zera."""
    try:
        return get_station_work_in_range(station_code, day_start, day_end)
    except Exception as e:
        logger.warning("Nie udało się pobrać station_events", extra={
            'station': station_code, 'error': str(e)
        })
        return {'pieces_done': 0, 'm3_done': 0.0, 'items_count': 0, 'orders_count': 0}


def _safe_sawmill_stats():
    """
    Ten sam wzorzec co _safe_station_work() wyżej, zastosowany do agregatów
    trakowni. Bez tej osłony błąd w sawmill_dashboard_stats() (np. brakująca
    tabela prod_sawmill_*, gdyby DDL nie poszedł przed deployem, albo
    uszkodzony wiersz) leciałby jako wyjątek nieobsłużony w tym miejscu i
    trafiał w `except Exception` na zewnątrz dashboard_tab_content(), które
    zwraca 500 dla CAŁEGO dashboardu — kładąc kafelki wszystkich sześciu
    pozostałych, w pełni sprawnych stanowisk produkcyjnych, nie tylko
    trakowni. Fallback na zera zamienia więc „dashboard down" w „kafelek
    trakowni pokazuje zera", zgodnie z tym, jak reszta stanowisk już się
    zachowuje.
    """
    from modules.production.sawmill.services.exports import sawmill_dashboard_stats
    try:
        return sawmill_dashboard_stats()
    except Exception as e:
        logger.warning("Nie udało się pobrać sawmill_dashboard_stats", extra={
            'error': str(e)
        })
        return {'open_orders': 0, 'logs_today': 0, 'volume_today_m3': 0.0,
                'to_settle': 0, 'progress_pct': 0.0}


# ============================================================================
# DASHBOARD STATS
# ============================================================================

@api_bp.route('/dashboard-stats', methods=['GET'])
@login_required
def dashboard_stats():
    """
    GET /production/api/dashboard-stats

    ROZBUDOWANA WERSJA - Zwraca statystyki dla dashboard z dodatkowymi metrykami

    Query params:
        include_products: true|false - czy dołączyć listę produktów (default: false)
        limit: liczba produktów do zwrócenia (default: 10, max: 50)

    Returns: JSON ze statystykami + opcjonalnie produktami
    """
    try:
        # Parametry opcjonalne
        include_products = request.args.get('include_products', 'false').lower() == 'true'
        limit = min(request.args.get('limit', 10, type=int), 50)

        from ...models import ProductionItem
        from sqlalchemy import func, desc
        from datetime import datetime, timedelta

        # ============================================================================
        # PODSTAWOWE STATYSTYKI (istniejące)
        # ============================================================================

        # Statystyki per status
        status_stats = db.session.query(
            ProductionItem.current_status,
            func.count(ProductionItem.id).label('count'),
            func.avg(ProductionItem.priority_rank).label('avg_priority')
        ).group_by(ProductionItem.current_status).all()

        stations_stats = {}
        total_products = 0

        for status, count, avg_priority in status_stats:
            total_products += count

            if status == 'czeka_na_wyciecie':
                stations_stats['cutting'] = {
                    'waiting_count': count,
                    'avg_priority': round(avg_priority or 0, 1)
                }
            elif status == 'czeka_na_skladanie':
                stations_stats['assembly'] = {
                    'waiting_count': count,
                    'avg_priority': round(avg_priority or 0, 1)
                }
            elif status == 'czeka_na_pakowanie':
                stations_stats['packaging'] = {
                    'waiting_count': count,
                    'avg_priority': round(avg_priority or 0, 1)
                }
            elif status == 'czeka_na_logistyke':
                stations_stats['logistics'] = {
                    'waiting_count': count,
                    'avg_priority': round(avg_priority or 0, 1)
                }

        # ============================================================================
        # DODATKOWE STATYSTYKI (nowe)
        # ============================================================================

        # Produkty z wysokim priorytetem (>=150)
        high_priority_count = ProductionItem.query.filter(
            ProductionItem.priority_rank.isnot(None), ProductionItem.priority_rank <= 10
        ).count()

        # Produkty przeterminowane
        today = datetime.now().date()
        overdue_count = ProductionItem.query.filter(
            ProductionItem.deadline_date < today,
            ProductionItem.current_status != 'spakowane'
        ).count()

        # Produkty spakowane dzisiaj
        today_start = datetime.combine(today, datetime.min.time())
        today_end = datetime.combine(today, datetime.max.time())

        # Faktycznie ukończone dziś — agregat z eventów stanowiska pakowania
        # (uwzględnia partial work; "pozycji" = items_count z dodatnim netto delta)
        tomorrow_start = today_start + timedelta(days=1)
        _packaging_today = _safe_station_work('packaging', today_start, tomorrow_start)
        completed_today = int(_packaging_today['items_count'])

        # Produkty utworzone w tym tygodniu
        week_ago = today - timedelta(days=7)
        week_start = datetime.combine(week_ago, datetime.min.time())

        new_this_week = ProductionItem.query.filter(
            ProductionItem.created_at >= week_start
        ).count()

        # Średnia objętość w produkcji
        avg_volume = db.session.query(func.avg(ProductionItem.volume_m3)).filter(
            ProductionItem.volume_m3.isnot(None),
            ProductionItem.current_status != 'spakowane'
        ).scalar()

        # ============================================================================
        # ALERTY I OSTRZEŻENIA (nowe)
        # ============================================================================

        alerts = []

        # Alert o przeterminowanych produktach
        if overdue_count > 0:
            alerts.append({
                'type': 'danger',
                'title': 'Produkty przeterminowane',
                'message': f'{overdue_count} produktów przekroczyło deadline',
                'count': overdue_count,
                'priority': 'high'
            })

        # Alert o produktach z wysokim priorytetem
        if high_priority_count > 10:
            alerts.append({
                'type': 'warning',
                'title': 'Dużo produktów wysokiego priorytetu',
                'message': f'{high_priority_count} produktów z priorytetem ≥150',
                'count': high_priority_count,
                'priority': 'medium'
            })

        # Alert o zastoju w produkcji
        cutting_backlog = stations_stats.get('cutting', {}).get('waiting_count', 0)
        if cutting_backlog > 50:
            alerts.append({
                'type': 'info',
                'title': 'Duża kolejka w wycinaniu',
                'message': f'{cutting_backlog} produktów czeka na wycięcie',
                'count': cutting_backlog,
                'priority': 'low'
            })

        # ============================================================================
        # PRZYGOTOWANIE ODPOWIEDZI
        # ============================================================================

        dashboard_data = {
            'success': True,
            'stats': {
                'total_products': total_products,
                'high_priority_count': high_priority_count,
                'overdue_count': overdue_count,
                'completed_today': completed_today,
                'new_this_week': new_this_week,
                'avg_volume_m3': round(avg_volume or 0, 2),
                'stations': stations_stats
            },
            'alerts': alerts,
            'last_updated': get_local_now().isoformat()
        }

        # ============================================================================
        # OPCJONALNE PRODUKTY
        # ============================================================================

        if include_products:
            # Najwyższy priorytet + najbliższe deadline
            priority_products = ProductionItem.query.filter(
                ProductionItem.current_status != 'spakowane'
            ).order_by(
                ProductionItem.priority_rank.asc(),
                ProductionItem.deadline_date.asc()
            ).limit(limit).all()

            products_data = []
            for product in priority_products:
                days_to_deadline = None
                if product.deadline_date:
                    days_to_deadline = (product.deadline_date - today).days

                products_data.append({
                    'id': product.id,
                    'short_product_id': product.short_product_id,
                    'internal_order_number': product.order.internal_order_number if product.order else None,
                    'original_product_name': product.original_product_name[:50] + '...' if len(product.original_product_name) > 50 else product.original_product_name,
                    'current_status': product.current_status,
                    'priority_rank': product.priority_rank or 0,
                    'deadline_date': product.deadline_date.isoformat() if product.deadline_date else None,
                    'days_to_deadline': days_to_deadline,
                    'is_overdue': days_to_deadline is not None and days_to_deadline < 0,
                    'is_urgent': days_to_deadline is not None and days_to_deadline <= 2
                })

            dashboard_data['products'] = products_data

        logger.info("Dashboard stats - rozbudowane", extra={
            'user_id': current_user.id,
            'include_products': include_products,
            'total_products': total_products,
            'alerts_count': len(alerts)
        })

        return jsonify(dashboard_data)

    except Exception as e:
        logger.error("Błąd dashboard stats - rozbudowanych", extra={
            'user_id': current_user.id if current_user.is_authenticated else None,
            'error': str(e)
        })
        return jsonify({
            'success': False,
            'error': f'Błąd pobierania statystyk: {str(e)}'
        }), 500


# ============================================================================
# CHART DATA
# ============================================================================

@api_bp.route('/chart-data')
@login_required
def chart_data():
    """
    AJAX endpoint dla danych wykresów wydajności dziennej (tylko admin)

    Query params:
        period: int - liczba dni do pobrania (7, 14, 30, 90, 180, 365)
        station: str - opcjonalnie konkretne stanowisko (cutting, assembly, etc.)
                       Gdy podane, zwraca 2 datasety: objętość i ilość sztuk
                       Gdy 'all' lub puste - zwraca 6 datasetów tylko z objętością

    Returns:
        JSON: Dane wydajności per stanowisko i okres dla Chart.js
    """
    try:
        from datetime import datetime, timedelta, date

        # Bez type=int: przy błędzie konwersji Flask oddaje wartość DOMYŚLNĄ,
        # więc ?period=abc stawało się cichym „7 dni" JESZCZE PRZED białą listą
        # niżej — podczas gdy ?period=0 dostawało uczciwe 400. To samo złe
        # wejście, dwa różne kody odpowiedzi.
        period_raw = (request.args.get('period') or '').strip()
        if period_raw and not period_raw.isdigit():
            return jsonify({
                'success': False,
                'error': 'Nieprawidłowy okres. Dozwolone: 7, 14, 30, 90, 180, 365 dni'
            }), 400
        period = int(period_raw) if period_raw else 7
        station_filter = request.args.get('station', 'all', type=str)
        start_date_param = request.args.get('start_date', type=str)
        end_date_param = request.args.get('end_date', type=str)

        # Niepełna para dat to błąd, nie zaproszenie do zakresu domyślnego —
        # ta sama reguła co w reports_api._parsuj_zakres_dat(). Wcześniej
        # ?start_date=2026-05-01 oddawało 200 z ostatnim tygodniem.
        if bool(start_date_param) != bool(end_date_param):
            return jsonify({
                'success': False,
                'error': 'Podaj obie daty zakresu (start_date i end_date) albo żadnej'
            }), 400

        # Walidacja stanowiska — lista z jednego katalogu (services/station_catalog),
        # żeby nie rozjeżdżała się z listami rozwijanymi. Wcześniej brakowało tu
        # lakierni, przez co „Wydajność dzienna" jako jedyny widget jej nie znała.
        valid_stations = ['all'] + list(STATION_ORDER)
        if station_filter not in valid_stations:
            return jsonify({
                'success': False,
                'error': f'Nieprawidłowe stanowisko. Dozwolone: {valid_stations}'
            }), 400

        # Tryb własnego przedziału dat
        if start_date_param and end_date_param:
            try:
                start_date = datetime.strptime(start_date_param, '%Y-%m-%d').date()
                end_date = datetime.strptime(end_date_param, '%Y-%m-%d').date()
            except ValueError:
                return jsonify({
                    'success': False,
                    'error': 'Nieprawidłowy format daty. Wymagany: YYYY-MM-DD'
                }), 400

            if start_date > end_date:
                return jsonify({
                    'success': False,
                    'error': 'Data początkowa musi być wcześniejsza lub równa dacie końcowej'
                }), 400

            period = (end_date - start_date).days + 1

            if period > 1825:
                return jsonify({
                    'success': False,
                    'error': 'Maksymalny zakres to 5 lat (1825 dni)'
                }), 400
        else:
            # Walidacja okresu - tryb predefiniowany
            if period not in [7, 14, 30, 90, 180, 365]:
                return jsonify({
                    'success': False,
                    'error': 'Nieprawidłowy okres. Dozwolone: 7, 14, 30, 90, 180, 365 dni'
                }), 400

            # get_local_now(), NIE date.today(): kontener chodzi na UTC, więc
            # między północą a 02:00 czasu polskiego preset „30 dni" kończył
            # się na wczorajszej dacie, a widgety obok liczyły z lokalnej.
            end_date = get_local_now().date()
            start_date = end_date - timedelta(days=period - 1)

        logger.info(f"AJAX: Pobieranie danych wykresów dla {period} dni, stanowisko: {station_filter}", extra={
            'user_id': current_user.id,
            'period': period,
            'station': station_filter,
            'start_date': start_date.isoformat(),
            'end_date': end_date.isoformat()
        })

        from ...models import ProductionItem
        from sqlalchemy import and_, func

        # ŹRÓDŁEM listy stanowisk jest KATALOG, nie literał w tym pliku.
        # Wcześniej były tu trzy równoległe listy sześciu kodów (mapa etykiet,
        # zaszyte datasety trybu 'all', trzy gałęzie agregacji) — wszystkie bez
        # lakierni, mimo że walidacja wyżej przepuszcza siedem stanowisk
        # ze STATION_ORDER i tyle samo pozycji ma lista rozwijana. Skutek:
        # „Wydajność dzienna" w trybie zbiorczym rysowała SZEŚĆ krzywych
        # zamiast siedmiu i gubiła 1.164 m³ z 94.895 m³ na oknie 30-dniowym —
        # akurat na stanowisku, które ma dziś 15,1 dnia zapasu, czyli
        # najdłuższą kolejkę hali.
        kody_stanowisk = list(STATION_ORDER)

        station_colors = {
            'cutting': {'border': '#fd7e14', 'bg': 'rgba(253, 126, 20, 0.1)'},
            'assembly': {'border': '#007bff', 'bg': 'rgba(0, 123, 255, 0.1)'},
            'gluing': {'border': '#9c27b0', 'bg': 'rgba(156, 39, 176, 0.1)'},
            'formatting': {'border': '#ff5722', 'bg': 'rgba(255, 87, 34, 0.1)'},
            'finishing': {'border': '#00bcd4', 'bg': 'rgba(0, 188, 212, 0.1)'},
            'painting': {'border': '#e91e63', 'bg': 'rgba(233, 30, 99, 0.1)'},
            'packaging': {'border': '#28a745', 'bg': 'rgba(40, 167, 69, 0.1)'}
        }
        KOLOR_REZERWOWY = {'border': '#6c757d', 'bg': 'rgba(108, 117, 125, 0.1)'}

        # NOWE: Określ typ agregacji na podstawie okresu
        if period <= 31:
            aggregation_type = 'daily'
        elif period <= 120:
            aggregation_type = 'weekly'
        else:
            aggregation_type = 'monthly'

        # =====================================================================
        # TRYB: Pojedyncze stanowisko (3 krzywe: objętość + ilość + wartość netto)
        # =====================================================================
        if station_filter != 'all':
            # Etykieta z katalogu, nie z lokalnej mapy: walidacja wyżej
            # przepuszcza wszystkie siedem stanowisk (STATION_ORDER), a ta mapa
            # ma sześć — wybranie „Lakierni" w liście rozwijanej kończyło się
            # KeyError('painting') i HTTP 500 zamiast wykresu. Zmierzone na
            # kopii produkcyjnej: wykres „Obsada vs przerób" pokazuje dla
            # lakierni 0.368 m³ / 9 szt. w tygodniu 05-11.08, a „Wydajność
            # dzienna" tego samego stanowiska w ogóle nie umiała narysować.
            from ...services.station_catalog import station_label as _etykieta
            station_label = _etykieta(station_filter)
            # Kolor jest wyłącznie prezentacją — brak wpisu ma dać szarą
            # krzywą, a nie wywrócić cały widget.
            station_color = station_colors.get(station_filter, KOLOR_REZERWOWY)

            # Faktyczna praca per dzień — z prod_station_events (uwzględnia partial work)
            try:
                per_day = get_station_work_per_day(station_filter, start_date, end_date)
            except Exception as e:
                logger.error("Błąd get_station_work_per_day", extra={
                    'station': station_filter, 'error': str(e)
                })
                return jsonify({
                    'success': False,
                    # Bez treści wyjątku — patrz komentarz przy handlerze
                    # na końcu tej funkcji.
                    'error': 'Nie udało się pobrać danych stanowiska. '
                             'Szczegóły w logach serwera.'
                }), 500

            daily_data = {
                day: {
                    'volume': stats['m3'],
                    'quantity': stats['pieces'],
                    'value': stats['value_net'],
                }
                for day, stats in per_day.items()
            }

            # Przygotuj chart_data dla pojedynczego stanowiska
            chart_data_result = {
                'labels': [],
                'datasets': [
                    {
                        'label': f'{station_label} - Objętość (m³)',
                        'data': [],
                        'borderColor': '#007bff',
                        'backgroundColor': 'rgba(0, 123, 255, 0.1)',
                        'tension': 0.4,
                        'fill': True,
                        'yAxisID': 'y'
                    },
                    {
                        'label': f'{station_label} - Ilość (szt.)',
                        'data': [],
                        'borderColor': '#fd7e14',
                        'backgroundColor': 'rgba(253, 126, 20, 0.1)',
                        'tension': 0.4,
                        'fill': True,
                        'yAxisID': 'y1',
                        'borderDash': [5, 5]
                    },
                    {
                        'label': f'{station_label} - Wartość netto (PLN)',
                        'data': [],
                        'borderColor': '#28a745',
                        'backgroundColor': 'rgba(40, 167, 69, 0.1)',
                        'tension': 0.4,
                        'fill': True,
                        'yAxisID': 'y2',
                        'borderDash': [2, 2]
                    }
                ]
            }

            # Agregacja danych
            if aggregation_type == 'daily':
                current_date = start_date
                while current_date <= end_date:
                    label = current_date.strftime('%Y-%m-%d')
                    chart_data_result['labels'].append(label)
                    data = daily_data.get(current_date, {'volume': 0.0, 'quantity': 0, 'value': 0.0})
                    chart_data_result['datasets'][0]['data'].append(data['volume'])
                    chart_data_result['datasets'][1]['data'].append(data['quantity'])
                    chart_data_result['datasets'][2]['data'].append(data['value'])
                    current_date += timedelta(days=1)

            elif aggregation_type == 'weekly':
                from collections import defaultdict
                weekly_data = defaultdict(lambda: {'volume': 0.0, 'quantity': 0, 'value': 0.0})
                for day_date, data in daily_data.items():
                    week_start = day_date - timedelta(days=day_date.weekday())
                    weekly_data[week_start]['volume'] += data['volume']
                    weekly_data[week_start]['quantity'] += data['quantity']
                    weekly_data[week_start]['value'] += data['value']

                current_date = start_date - timedelta(days=start_date.weekday())
                while current_date <= end_date:
                    week_label = current_date.strftime('%Y-%m-%d')
                    chart_data_result['labels'].append(week_label)
                    chart_data_result['datasets'][0]['data'].append(weekly_data[current_date]['volume'])
                    chart_data_result['datasets'][1]['data'].append(weekly_data[current_date]['quantity'])
                    chart_data_result['datasets'][2]['data'].append(weekly_data[current_date]['value'])
                    current_date += timedelta(weeks=1)

            elif aggregation_type == 'monthly':
                from collections import defaultdict
                monthly_data = defaultdict(lambda: {'volume': 0.0, 'quantity': 0, 'value': 0.0})
                for day_date, data in daily_data.items():
                    month_start = date(day_date.year, day_date.month, 1)
                    monthly_data[month_start]['volume'] += data['volume']
                    monthly_data[month_start]['quantity'] += data['quantity']
                    monthly_data[month_start]['value'] += data['value']

                current_month = date(start_date.year, start_date.month, 1)
                end_month = date(end_date.year, end_date.month, 1)
                while current_month <= end_month:
                    month_label = current_month.strftime('%Y-%m-01')
                    chart_data_result['labels'].append(month_label)
                    chart_data_result['datasets'][0]['data'].append(monthly_data[current_month]['volume'])
                    chart_data_result['datasets'][1]['data'].append(monthly_data[current_month]['quantity'])
                    chart_data_result['datasets'][2]['data'].append(monthly_data[current_month]['value'])
                    if current_month.month == 12:
                        current_month = date(current_month.year + 1, 1, 1)
                    else:
                        current_month = date(current_month.year, current_month.month + 1, 1)

            # Statystyki dla pojedynczego stanowiska
            total_volume = sum(chart_data_result['datasets'][0]['data'])
            total_quantity = sum(chart_data_result['datasets'][1]['data'])
            total_value = sum(chart_data_result['datasets'][2]['data'])
            num_periods = len(chart_data_result['labels']) if chart_data_result['labels'] else 1

            summary = {
                'period_days': period,
                'aggregation_type': aggregation_type,
                'station': station_filter,
                'station_label': station_label,
                # Ile DÓB w zakresie ma choć jedno zdarzenie. Bez tego front
                # nie odróżniał „nikt nic nie zrobił" od „narysowaliśmy zera":
                # zakres w przyszłości, niedziela i okres sprzed pierwszego
                # produktu dawały identyczny obraz płaskiej linii na zerze,
                # podczas gdy każdy inny widget zakładki ma jawny pusty stan.
                'days_with_events': len(per_day),
                'total_volume': round(total_volume, 2),
                'total_quantity': total_quantity,
                'total_value': round(total_value, 2),
                'avg_volume_per_period': round(total_volume / num_periods, 2),
                'avg_quantity_per_period': round(total_quantity / num_periods, 1),
                'avg_value_per_period': round(total_value / num_periods, 2)
            }

            response_data = {
                'success': True,
                'chart_data': chart_data_result,
                'summary': summary,
                'period': period,
                'station': station_filter,
                'mode': 'single_station',
                'date_range': {
                    'start': start_date.isoformat(),
                    'end': end_date.isoformat()
                },
                'generated_at': get_local_now().isoformat()
            }

            return jsonify(response_data)

        # =====================================================================
        # TRYB: Wszystkie stanowiska (po jednej krzywej objętości na stanowisko)
        #
        # Datasety i agregacja lecą Z PĘTLI po katalogu, nie z zaszytej listy.
        # Trzy równoległe listy literałów (etykiety, datasety, kody w trzech
        # gałęziach agregacji) miały po sześć pozycji przy siedmiu stanowiskach
        # w katalogu — i nikt tego nie zauważył, bo test regresyjny iterował
        # `station={kod}`, a `station=all` nie był wołany ani razu.
        # =====================================================================
        chart_data_result = {
            'labels': [],
            'datasets': [
                {
                    'label': station_label_catalog(kod),
                    'data': [],
                    'borderColor': station_colors.get(kod, KOLOR_REZERWOWY)['border'],
                    'backgroundColor': station_colors.get(kod, KOLOR_REZERWOWY)['bg'],
                    'tension': 0.4,
                    'fill': True,
                    'stationCode': kod,
                }
                for kod in kody_stanowisk
            ],
        }

        # Pobierz dane wydajności dla każdego stanowiska — z prod_station_events
        daily_data = {}
        pusty_dzien = {kod: 0.0 for kod in kody_stanowisk}

        for station in kody_stanowisk:
            try:
                per_day = get_station_work_per_day(station, start_date, end_date)
            except Exception as e:
                logger.warning("Błąd get_station_work_per_day", extra={
                    'station': station, 'error': str(e)
                })
                continue

            for completion_date, stats in per_day.items():
                if completion_date not in daily_data:
                    daily_data[completion_date] = dict(pusty_dzien)
                daily_data[completion_date][station] = float(stats['m3'])

        def dosyp(klucz_okresu, zrodlo):
            """Dokłada jeden punkt na każdą krzywą — po kolejności katalogu."""
            chart_data_result['labels'].append(klucz_okresu)
            for idx, kod in enumerate(kody_stanowisk):
                chart_data_result['datasets'][idx]['data'].append(zrodlo.get(kod, 0.0))

        if aggregation_type == 'daily':
            current_date = start_date
            while current_date <= end_date:
                dosyp(current_date.strftime('%Y-%m-%d'),
                      daily_data.get(current_date, pusty_dzien))
                current_date += timedelta(days=1)

        elif aggregation_type == 'weekly':
            from collections import defaultdict
            weekly_data = defaultdict(lambda: dict(pusty_dzien))

            for day_date, volumes in daily_data.items():
                week_start = day_date - timedelta(days=day_date.weekday())
                for kod in kody_stanowisk:
                    weekly_data[week_start][kod] += volumes[kod]

            current_date = start_date - timedelta(days=start_date.weekday())
            while current_date <= end_date:
                dosyp(current_date.strftime('%Y-%m-%d'), weekly_data[current_date])
                current_date += timedelta(weeks=1)

        elif aggregation_type == 'monthly':
            from collections import defaultdict
            monthly_data = defaultdict(lambda: dict(pusty_dzien))

            for day_date, volumes in daily_data.items():
                month_start = date(day_date.year, day_date.month, 1)
                for kod in kody_stanowisk:
                    monthly_data[month_start][kod] += volumes[kod]

            current_month = date(start_date.year, start_date.month, 1)
            end_month = date(end_date.year, end_date.month, 1)
            while current_month <= end_month:
                dosyp(current_month.strftime('%Y-%m-01'), monthly_data[current_month])
                if current_month.month == 12:
                    current_month = date(current_month.year + 1, 1, 1)
                else:
                    current_month = date(current_month.year, current_month.month + 1, 1)


        # Oblicz statystyki podsumowujące
        total_volumes = {
            kod: sum(chart_data_result['datasets'][idx]['data'])
            for idx, kod in enumerate(kody_stanowisk)
        }

        num_periods = len(chart_data_result['labels']) if chart_data_result['labels'] else 1
        avg_per_period = {kod: suma / num_periods
                          for kod, suma in total_volumes.items()}

        # Znajdź najlepszy okres — po SUMIE WSZYSTKICH stanowisk, nie po trzech
        # pierwszych krzywych. Poprzednia wersja sumowała datasety 0-2, czyli
        # wycinanie + składanie + sklejanie, i „najlepszy okres" był najlepszy
        # wyłącznie dla początku procesu.
        best_period_idx = 0
        best_period_total = 0
        for i in range(len(chart_data_result['labels'])):
            period_total = sum(ds['data'][i] for ds in chart_data_result['datasets'])
            if period_total > best_period_total:
                best_period_total = period_total
                best_period_idx = i

        summary = {
            'period_days': period,
            'aggregation_type': aggregation_type,
            # Patrz komentarz w gałęzi pojedynczego stanowiska — front rysuje
            # pusty stan zamiast siedmiu krzywych leżących na zerze.
            'days_with_events': len(daily_data),
            'total_volumes': total_volumes,
            'avg_per_period': {k: round(v, 2) for k, v in avg_per_period.items()},
            'best_period': {
                'label': chart_data_result['labels'][best_period_idx] if chart_data_result['labels'] else None,
                'volume': round(best_period_total, 2)
            },
            'total_period_volume': round(sum(total_volumes.values()), 2)
        }

        response_data = {
            'success': True,
            'chart_data': chart_data_result,
            'summary': summary,
            'period': period,
            'date_range': {
                'start': start_date.isoformat(),
                'end': end_date.isoformat()
            },
            'generated_at': get_local_now().isoformat()
        }

        logger.info("Pomyślnie wygenerowano dane wykresów", extra={
            'user_id': current_user.id,
            'period': period,
            'aggregation': aggregation_type,
            'total_volume': summary['total_period_volume'],
            'data_points': len(chart_data_result['labels'])
        })

        return jsonify(response_data)

    except Exception as e:
        logger.error("Błąd generowania danych wykresów", extra={
            'user_id': current_user.id,
            'period': request.args.get('period'),
            'error': str(e)
        })

        # Treść wyjątku zostaje w logu. Przy błędzie SQLAlchemy str(e) niesie
        # pełne zapytanie z parametrami (nazwy klientów i produktów
        # z BaseLinkera), a endpoint ma wyłącznie @login_required — do tego
        # front wstawia `data.error` do innerHTML.
        return jsonify({
            'success': False,
            'error': 'Nie udało się pobrać danych wykresu. Szczegóły w logach serwera.'
        }), 500


# ============================================================================
# DASHBOARD TAB CONTENT (AJAX)
# ============================================================================

@api_bp.route('/dashboard-tab-content')
@login_required
def dashboard_tab_content():
    """
    AJAX endpoint dla zawartości taba Dashboard
    - initial_load=true: zwraca pełny HTML template + początkowe dane
    - initial_load=false/brak: przekierowuje do dashboard-data (tylko JSON)
    """
    try:
        initial_load = request.args.get('initial_load', 'false').lower() == 'true'

        logger.info("AJAX: dashboard-tab-content", extra={
            'user_id': current_user.id,
            'user_role': getattr(current_user, 'role', 'unknown'),
            'initial_load': initial_load
        })

        if not initial_load:
            from flask import redirect, url_for
            return redirect(url_for('production.production_api.dashboard_data'))

        # PIERWSZE ŁADOWANIE - zwróć pełny HTML template
        from ...models import ProductionItem, ProductionError, ProductionSyncLog

        today = date.today()

        dashboard_stats = {}

        # Statystyki stacji
        cutting_count = ProductionItem.query.filter(ProductionItem.current_status == 'czeka_na_wyciecie').count()
        assembly_count = ProductionItem.query.filter(ProductionItem.current_status == 'czeka_na_skladanie').count()
        gluing_count = ProductionItem.query.filter(ProductionItem.current_status == 'czeka_na_sklejanie').count()
        formatting_count = ProductionItem.query.filter(ProductionItem.current_status == 'czeka_na_formatowanie').count()
        finishing_count = ProductionItem.query.filter(ProductionItem.current_status == 'czeka_na_wykanczanie').count()
        packaging_count = ProductionItem.query.filter(ProductionItem.current_status == 'czeka_na_pakowanie').count()

        today_start = datetime.combine(today, datetime.min.time())
        today_end = datetime.combine(today, datetime.max.time())
        tomorrow_start = today_start + timedelta(days=1)

        # Faktyczna praca dziś — z prod_station_events (uwzględnia partial work)
        station_work_today = {
            code: _safe_station_work(code, today_start, tomorrow_start)
            for code in _STATION_PENDING_STATUS.keys()
        }

        _station_count_map = {
            'cutting': cutting_count,
            'assembly': assembly_count,
            'gluing': gluing_count,
            'formatting': formatting_count,
            'finishing': finishing_count,
            'packaging': packaging_count,
        }
        dashboard_stats['stations'] = {
            code: {
                'pending_count': _station_count_map[code],
                'today_m3': float(station_work_today[code]['m3_done']),
                'status': 'active' if _station_count_map[code] > 0 else 'idle',
                'status_class': (
                    'station-active' if _station_count_map[code] > 0 else 'station-idle'
                ),
            }
            for code in _STATION_PENDING_STATUS.keys()
        }

        # Trakownia nie ma statusów ProductionItem, więc nie da się jej policzyć
        # ze słownika _STATION_PENDING_STATUS jak pozostałych stanowisk —
        # ma własne agregaty na tabelach prod_sawmill_*. Gałąź musi zostać
        # zbudowana PRZED pętlą przypisującą tablet_status niżej (klucz
        # 'sawmill' musi już istnieć w dashboard_stats['stations'], inaczej
        # pętla wywali KeyError i popsuje dashboard wszystkim stanowiskom).
        sawmill = _safe_sawmill_stats()
        dashboard_stats['stations']['sawmill'] = {
            'open_orders': sawmill['open_orders'],
            'logs_today': sawmill['logs_today'],
            'volume_today_m3': sawmill['volume_today_m3'],
            'to_settle': sawmill['to_settle'],
            'progress_pct': sawmill['progress_pct'],
            'tablet_status': {'active': False, 'last_seen': None,
                              'status_label': 'Niedostępne'},
        }

        # Heartbeat status per station
        from modules.production.services.mobile_api_service import get_devices_telemetry
        heartbeat_statuses = get_devices_telemetry()

        for st_code in ['sawmill', 'cutting', 'assembly', 'gluing',
                        'formatting', 'finishing', 'packaging']:
            dashboard_stats['stations'][st_code]['tablet_status'] = heartbeat_statuses.get(st_code, {'active': False, 'last_seen': None, 'status_label': 'Niedostępne'})

        # completed_today (count distinct items z dodatnim netto delta)
        # i pending_m3 (kolejka — stan bieżący po current_status) per stanowisko
        for station_code, pending_status in _STATION_PENDING_STATUS.items():
            pending_m3 = db.session.query(
                db.func.coalesce(db.func.sum(ProductionItem.volume_m3 * ProductionItem.quantity), 0)
            ).filter(ProductionItem.current_status == pending_status).scalar() or 0.0
            dashboard_stats['stations'][station_code]['completed_today'] = int(
                station_work_today[station_code]['items_count']
            )
            dashboard_stats['stations'][station_code]['pending_m3'] = float(pending_m3)

        logistics_pending = db.session.query(
            db.func.count(db.func.distinct(ProductionOrder.internal_order_number))
        ).join(ProductionItem, ProductionItem.order_id == ProductionOrder.id).filter(
            ProductionItem.current_status == 'czeka_na_logistyke'
        ).scalar() or 0
        dashboard_stats['logistics'] = {
            'pending_count': logistics_pending
        }

        # Dzisiejsze sumy — z eventów stanowiska pakowania (faktyczna fizyczna praca)
        packaging_today = station_work_today.get('packaging', {
            'pieces_done': 0, 'm3_done': 0.0, 'items_count': 0, 'orders_count': 0
        })
        completed_orders_today = packaging_today['orders_count']
        completed_items_today = packaging_today['items_count']
        completed_products_today = packaging_today['pieces_done']
        total_m3_today = packaging_today['m3_done']

        avg_deadline_distance = 0.0
        try:
            active_products = ProductionItem.query.filter(
                ProductionItem.current_status.in_([
                    'czeka_na_wyciecie', 'czeka_na_skladanie',
                    'czeka_na_sklejanie', 'czeka_na_formatowanie', 'czeka_na_wykanczanie',
                    'czeka_na_pakowanie', 'w_realizacji'
                ]),
                ProductionItem.deadline_date.isnot(None)
            ).all()

            if active_products:
                # deadline_date to Column(Date) → datetime.date, więc odejmujemy bez .date()
                total_days = sum(
                    (product.deadline_date - today).days
                    for product in active_products
                )
                avg_deadline_distance = total_days / len(active_products)
        except Exception as e:
            logger.warning("Błąd obliczania średniego deadline", extra={'error': str(e)})
            avg_deadline_distance = 0.0

        dashboard_stats['today_totals'] = {
            'completed_orders': int(completed_orders_today),
            'completed_items': int(completed_items_today),
            'completed_products': int(completed_products_today),
            'total_m3': float(total_m3_today),
            'avg_deadline_distance': round(avg_deadline_distance, 1),
            'total_orders': ProductionItem.query.count()
        }

        # "In production now" — liczone per niespakowana sztuka.
        # Wykluczamy spakowane i anulowane.
        in_production_items = ProductionItem.query.options(
            joinedload(ProductionItem.order),
        ).filter(
            ProductionItem.current_status.notin_(('spakowane', 'anulowane')),
            db.func.coalesce(ProductionItem.quantity_done_packaging, 0) < ProductionItem.quantity
        ).all()

        in_production_order_ids = set()
        ip_items_count = 0
        ip_pieces_remaining = 0
        ip_m3_remaining = 0.0
        for item in in_production_items:
            qty = int(item.quantity or 0)
            done = int(item.quantity_done_packaging or 0)
            remaining = qty - done
            if remaining <= 0:
                continue
            ip_items_count += 1
            ip_pieces_remaining += remaining
            ip_m3_remaining += float(item.volume_m3 or 0) * remaining
            if item.order and item.order.baselinker_order_id:
                in_production_order_ids.add(item.order.baselinker_order_id)

        dashboard_stats['in_production'] = {
            'orders': len(in_production_order_ids),
            'items': ip_items_count,
            'products': ip_pieces_remaining,
            'm3': round(ip_m3_remaining, 2)
        }

        # Grupowanie po zamówieniu i wybór stanowiska siedzą w serwisie —
        # ten sam kod obsługuje pierwszy render strony (main_routers).
        dashboard_stats['deadline_alerts'] = build_deadline_alerts()

        errors_24h = ProductionError.query.filter(
            ProductionError.error_occurred_at >= (get_local_now() - timedelta(hours=24)),
            ProductionError.is_resolved == False
        ).count()

        last_sync = ProductionSyncLog.query.order_by(ProductionSyncLog.sync_started_at.desc()).first()

        dashboard_stats['system_health'] = {
            'last_sync': last_sync.sync_started_at.isoformat() if last_sync else None,
            'sync_status': 'success' if last_sync and last_sync.sync_status == 'completed' else 'warning',
            'errors_24h': errors_24h,
            'database_status': 'connected'
        }

        rendered_html = render_template(
            'components/dashboard-tab-content.html',
            dashboard_stats=dashboard_stats
        )

        return jsonify({
            'success': True,
            'html': rendered_html,
            'initial_data': dashboard_stats,
            'last_updated': get_local_now().isoformat()
        })

    except Exception as e:
        logger.error("Błąd AJAX dashboard-tab-content", extra={
            'user_id': current_user.id,
            'error': str(e),
            'initial_load': initial_load if 'initial_load' in locals() else 'unknown'
        })

        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


# ============================================================================
# DASHBOARD DATA (JSON only, no HTML)
# ============================================================================

@api_bp.route('/dashboard-data', methods=['GET'])
@login_required
def dashboard_data():
    """
    Zwraca TYLKO dane dla dashboard (bez HTML)
    Używane do odświeżania danych bez przeładowywania template
    """
    try:
        logger.info("API: dashboard-data - pobieranie danych", extra={
            'user_id': current_user.id,
            'user_role': getattr(current_user, 'role', 'unknown')
        })

        from ...models import ProductionItem, ProductionError
        from modules.production.services.mobile_api_service import get_devices_telemetry as _get_all_heartbeat_statuses

        heartbeat_statuses = _get_all_heartbeat_statuses()

        stations_data = []

        today_dd = date.today()
        today_start_dd = datetime.combine(today_dd, datetime.min.time())
        tomorrow_start_dd = today_start_dd + timedelta(days=1)

        # Per stanowisko: kolejka (current_status), pending_m3 (kolejka),
        # completed_today (faktyczne pozycje ruszane dziś — z prod_station_events)
        # Jedno źródło nazw stanowisk — patrz services/station_catalog.py
        from ...services.station_catalog import station_label
        for station_code, pending_status in _STATION_PENDING_STATUS.items():
            count = ProductionItem.query.filter(
                ProductionItem.current_status == pending_status
            ).count()
            pending_m3 = db.session.query(
                db.func.coalesce(db.func.sum(ProductionItem.volume_m3 * ProductionItem.quantity), 0)
            ).filter(ProductionItem.current_status == pending_status).scalar() or 0.0
            work = _safe_station_work(station_code, today_start_dd, tomorrow_start_dd)

            stations_data.append({
                'code': station_code,
                'name': station_label(station_code),
                'status': 'active' if count > 0 else 'idle',
                'status_class': 'station-active' if count > 0 else 'station-idle',
                'active_orders': count,
                'completed_today': int(work['items_count']),
                'pending_m3': float(pending_m3),
                'tablet_status': heartbeat_statuses.get(station_code, {
                    'active': False, 'last_seen': None, 'status_label': 'Niedostępne'
                }),
            })

        # Alerty systemowe
        alerts_data = []

        errors_24h = ProductionError.query.filter(
            ProductionError.error_occurred_at >= (get_local_now() - timedelta(hours=24)),
            ProductionError.is_resolved == False
        ).count()

        if errors_24h > 0:
            alerts_data.append({
                'type': 'error',
                'icon': 'exclamation-triangle',
                'message': f'Znaleziono {errors_24h} błędów systemowych',
                'time': 'ostatnie 24h'
            })

        today = date.today()
        deadline_items = ProductionItem.query.options(
            joinedload(ProductionItem.order),
        ).filter(
            ProductionItem.deadline_date <= (today + timedelta(days=3)),
            ProductionItem.current_status != 'spakowane'
        ).order_by(ProductionItem.deadline_date.asc()).all()

        # Group by order (baselinker_order_id)
        orders_map = {}
        for item in deadline_items:
            oid = (item.order.baselinker_order_id if item.order else None) or item.short_product_id
            if oid not in orders_map:
                orders_map[oid] = {
                    'baselinker_order_id': item.order.baselinker_order_id if item.order else None,
                    'client_name': (item.order.client_name if item.order else None) or 'Brak danych',
                    'deadline_date': item.deadline_date.isoformat() if item.deadline_date else None,
                    'deadline_date_formatted': item.deadline_date.strftime('%d.%m.%Y') if item.deadline_date else '',
                    'days_remaining': (item.deadline_date - today).days if item.deadline_date else 0,
                    'products_count': 0,
                }
            orders_map[oid]['products_count'] += 1
            # Use earliest deadline for the order
            if item.deadline_date and item.deadline_date.isoformat() < (orders_map[oid]['deadline_date'] or '9999'):
                orders_map[oid]['deadline_date'] = item.deadline_date.isoformat()
                orders_map[oid]['deadline_date_formatted'] = item.deadline_date.strftime('%d.%m.%Y')
                orders_map[oid]['days_remaining'] = (item.deadline_date - today).days

        alerts_data = sorted(orders_map.values(), key=lambda x: x.get('days_remaining', 0))

        # "In production now" — liczone per niespakowana sztuka.
        # Wykluczamy spakowane i anulowane.
        in_production_items_dd = ProductionItem.query.filter(
            ProductionItem.current_status.notin_(('spakowane', 'anulowane')),
            db.func.coalesce(ProductionItem.quantity_done_packaging, 0) < ProductionItem.quantity
        ).all()

        in_production_order_ids_dd = set()
        dd_items_count = 0
        dd_pieces_remaining = 0
        dd_m3_remaining = 0.0
        for item in in_production_items_dd:
            qty = int(item.quantity or 0)
            done = int(item.quantity_done_packaging or 0)
            remaining = qty - done
            if remaining <= 0:
                continue
            dd_items_count += 1
            dd_pieces_remaining += remaining
            dd_m3_remaining += float(item.volume_m3 or 0) * remaining
            if item.order and item.order.baselinker_order_id:
                in_production_order_ids_dd.add(item.order.baselinker_order_id)

        in_production_stats = {
            'orders': len(in_production_order_ids_dd),
            'items': dd_items_count,
            'products': dd_pieces_remaining,
            'm3': round(dd_m3_remaining, 2)
        }

        response_data = {
            'stations': stations_data,
            'alerts': alerts_data,
            'in_production': in_production_stats,
            'errors_count': errors_24h,
            'timestamp': get_local_now().isoformat()
        }

        logger.debug("API: dashboard-data - dane pobrane", extra={
            'stations_count': len(stations_data),
            'alerts_count': len(alerts_data),
            'errors_24h': errors_24h
        })

        return jsonify({
            'success': True,
            'data': response_data
        })

    except Exception as e:
        logger.error("API: Błąd dashboard-data", extra={
            'user_id': current_user.id,
            'error': str(e),
            'traceback': traceback.format_exc()
        })

        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


# ============================================================================
# PRODUCTION STATUS DATA
# ============================================================================

@api_bp.route('/production-status-data', methods=['GET'])
@login_required
def production_status_data():
    """
    Zwraca TYLKO status produkcji (bez HTML)
    Używane do odświeżania wskaźnika statusu w header dashboard
    """
    try:
        logger.info("API: production-status-data - pobieranie statusu", extra={
            'user_id': current_user.id,
            'user_role': getattr(current_user, 'role', 'unknown')
        })

        from ...models import ProductionItem, ProductionSyncLog

        active_orders = ProductionItem.query.filter(
            ProductionItem.current_status.in_([
                'czeka_na_wyciecie',
                'czeka_na_skladanie',
                'czeka_na_pakowanie'
            ])
        ).count()

        last_sync = ProductionSyncLog.query.order_by(
            ProductionSyncLog.sync_started_at.desc()
        ).first()

        if active_orders > 0:
            status = 'active'
            status_text = f'Produkcja aktywna ({active_orders} zamówień)'
            indicator_class = 'status-active'
        else:
            status = 'idle'
            status_text = 'Produkcja w trybie oczekiwania'
            indicator_class = 'status-idle'

        sync_age_hours = None
        if last_sync:
            sync_age_hours = (get_local_now() - last_sync.sync_started_at).total_seconds() / 3600
            if sync_age_hours > 2:
                status = 'warning'
                status_text = 'Problemy z synchronizacją'
                indicator_class = 'status-warning'

        response_data = {
            'status': status,
            'status_text': status_text,
            'indicator_class': indicator_class,
            'active_orders': active_orders,
            'last_sync': last_sync.sync_started_at.isoformat() if last_sync else None,
            'last_update': get_local_now().isoformat()
        }

        logger.debug("API: production-status-data - status określony", extra={
            'status': status,
            'active_orders': active_orders,
            'last_sync_age_hours': sync_age_hours if last_sync else None
        })

        return jsonify({
            'success': True,
            'data': response_data
        })

    except Exception as e:
        logger.error("API: Błąd production-status-data", extra={
            'user_id': current_user.id,
            'error': str(e),
            'traceback': traceback.format_exc()
        })

        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


# ============================================================================
# DASHBOARD STATS DATA (numbers only)
# ============================================================================

@api_bp.route('/dashboard-stats-data', methods=['GET'])
@login_required
def dashboard_stats_data():
    """
    Zwraca TYLKO statystyki liczbowe dla dashboard (bez HTML)
    Używane do odświeżania widgetów z liczbami
    """
    try:
        logger.info("API: dashboard-stats-data - pobieranie statystyk", extra={
            'user_id': current_user.id,
            'user_role': getattr(current_user, 'role', 'unknown')
        })

        from ...models import ProductionItem, ProductionError

        today = date.today()
        today_start = datetime.combine(today, datetime.min.time())
        today_end = datetime.combine(today, datetime.max.time())

        all_statuses = db.session.query(
            ProductionItem.current_status,
            db.func.count(ProductionItem.id)
        ).group_by(ProductionItem.current_status).all()

        logger.debug(f"Wszystkie statusy w bazie: {all_statuses}")

        try:
            test_packaging = ProductionItem.query.filter(
                ProductionItem.packaging_completed_at.isnot(None)
            ).limit(5).all()
            logger.debug(f"Znaleziono {len(test_packaging)} rekordów z packaging_completed_at")

            for item in test_packaging:
                logger.debug(f"Item {item.id}: packaging_completed_at={item.packaging_completed_at}")
        except Exception as e:
            logger.debug(f"Błąd packaging_completed_at: {e}")

        try:
            spakowane_items = ProductionItem.query.filter(
                ProductionItem.current_status == 'spakowane'
            ).limit(5).all()
            logger.debug(f"Znaleziono {len(spakowane_items)} rekordów ze statusem 'spakowane'")

            for item in spakowane_items:
                created_at = getattr(item, 'created_at', None)
                updated_at = getattr(item, 'updated_at', None)
                packaging_completed_at = getattr(item, 'packaging_completed_at', None)

                logger.debug(f"Item {item.id}: status={item.current_status}, created_at={created_at}, updated_at={updated_at}, packaging_completed_at={packaging_completed_at}")
        except Exception as e:
            logger.debug(f"Błąd sprawdzania statusów: {e}")

        total_orders = ProductionItem.query.count()

        # Faktyczna praca dziś na pakowaniu — z prod_station_events
        # (uwzględnia partial work, cofnięcia; "stan fizyczny")
        tomorrow_start = today_start + timedelta(days=1)
        packaging_today = _safe_station_work('packaging', today_start, tomorrow_start)
        completed_today = int(packaging_today['items_count'])
        completed_orders_today = int(packaging_today['orders_count'])
        completed_products_today = int(packaging_today['pieces_done'])
        total_volume_today = float(packaging_today['m3_done'])

        pending_priority = ProductionItem.query.filter(
            ProductionItem.current_status.in_([
                'czeka_na_wyciecie',
                'czeka_na_skladanie',
                'czeka_na_pakowanie'
            ])
        ).filter(
            ProductionItem.deadline_date <= (today + timedelta(days=3))
        ).count()

        errors_24h = ProductionError.query.filter(
            ProductionError.error_occurred_at >= (get_local_now() - timedelta(hours=24)),
            ProductionError.is_resolved == False
        ).count()

        stats_data = {
            'total_orders': total_orders,
            'completed_today': completed_today,
            'completed_orders': completed_orders_today,
            'completed_items': completed_today,
            'completed_products': completed_products_today,
            'total_m3': total_volume_today,
            'pending_priority': pending_priority,
            'errors_24h': errors_24h,
            'total_volume_today_m3': total_volume_today,
            'completion_rate_today': round((completed_today / max(total_orders, 1)) * 100, 1),
            'last_updated': get_local_now().isoformat()
        }

        logger.debug("API: dashboard-stats-data - FINALNE statystyki", extra={
            'total_orders': total_orders,
            'completed_today': completed_today,
            'pending_priority': pending_priority,
            'errors_24h': errors_24h,
            'total_volume_today': total_volume_today,
        })

        return jsonify({
            'success': True,
            'data': stats_data
        })

    except Exception as e:
        logger.error("API: Błąd dashboard-stats-data", extra={
            'user_id': current_user.id,
            'error': str(e),
            'traceback': traceback.format_exc()
        })

        return jsonify({
            'success': False,
            'error': str(e)
        }), 500
