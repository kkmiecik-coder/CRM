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
from sqlalchemy.orm import joinedload

from . import api_bp, logger, ProductionItem, ProductionSyncLog, get_local_now
from modules.production.models import ProductionConfiguration

from ...services.station_catalog import (
    STATION_LABELS, STATION_ORDER, station_choices, station_label,
)

# Jedno źródło nazw i kolejności — patrz services/station_catalog.py. Wcześniej
# ten moduł miał własną kopię etykiet ('Wycinanie'), a tabela pod widgetem brała
# je skądinąd ('Wycinanie - mikro') — w jednym widoku dwie nazwy tego samego.
VALID_STATIONS = set(STATION_ORDER)


def _parsuj_zakres_dat():
    """
    Wspólne parsowanie start_date/end_date dla raportów. Zwraca
    (start_date, end_date, error_response) — jak w reports_station_output,
    tylko wyciągnięte, żeby nie kopiować walidacji do raportu pracowników.
    """
    start_str = request.args.get('start_date', '').strip()
    end_str = request.args.get('end_date', '').strip()

    try:
        if start_str and end_str:
            start = datetime.strptime(start_str, '%Y-%m-%d').date()
            end = datetime.strptime(end_str, '%Y-%m-%d').date()
        else:
            # Domyślnie bieżący tydzień wstecz — sensowny zakres na wejściu
            end = date.today()
            start = end - timedelta(days=6)
    except ValueError:
        return None, None, (jsonify({
            'success': False,
            'error': 'Nieprawidłowy format daty (oczekiwane YYYY-MM-DD)'
        }), 400)

    return start, end, None


@api_bp.route('/reports/worker-output')
@login_required
def reports_worker_output():
    """
    GET /production/api/reports/worker-output
        ?start_date=YYYY-MM-DD&end_date=YYYY-MM-DD
        &station=all|<station_code>&worker_id=<opcjonalnie>
        &format=json|xlsx

    Wydajność pracowników liczona z atrybucji eventów stanowiskowych
    (docs/worker-profiles-backend.md §7.2). Jeden event dzieli się między
    pracowników przez share = 1/N, więc sumy są ułamkowe.

    Dane są POGLĄDOWE: wybór profilu na tablecie nie jest chroniony hasłem.
    Odpowiedź niesie attribution_coverage_pct — ile produkcji w okresie
    w ogóle da się komuś przypisać.
    """
    from ...services import worker_stats_service
    from ...services.worker_stats_service import ZakresError

    start_date, end_date, err = _parsuj_zakres_dat()
    if err:
        return err

    station = request.args.get('station', 'all').strip().lower() or 'all'
    if station != 'all' and station not in VALID_STATIONS:
        return jsonify({
            'success': False,
            'error': f'Nieprawidłowe stanowisko. Dozwolone: all, {sorted(VALID_STATIONS)}'
        }), 400

    worker_id = request.args.get('worker_id', '').strip()
    try:
        worker_id = int(worker_id) if worker_id else None
    except ValueError:
        return jsonify({'success': False, 'error': 'worker_id musi być liczbą'}), 400

    try:
        raport = worker_stats_service.raport_wydajnosci(
            start_date, end_date, station=station, worker_id=worker_id)
    except ZakresError as e:
        return jsonify({'success': False, 'error': str(e)}), 400

    if request.args.get('format', 'json').strip().lower() == 'xlsx':
        return _eksport_raportu_pracownikow(raport)

    return jsonify({'success': True, 'report': raport})


def _eksport_raportu_pracownikow(raport):
    """XLSX z dwoma arkuszami: podsumowanie per pracownik i pełne wiersze."""
    from io import BytesIO

    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font
    except ImportError:
        logger.warning("openpyxl niedostępne — eksport raportu pracowników odrzucony")
        return jsonify({'success': False,
                        'error': 'Eksport XLSX niedostępny (brak openpyxl)'}), 501

    wb = Workbook()

    ark = wb.active
    ark.title = 'Podsumowanie'
    ark.append(['Pracownik', 'Sztuki', 'm3', 'Godziny', 'Tempo (m3/h)', 'Stanowiska'])
    for komorka in ark[1]:
        komorka.font = Font(bold=True)
    for wiersz in raport['worker_totals']:
        ark.append([
            wiersz['worker_name'], wiersz['pieces'], wiersz['m3'],
            wiersz['hours'], wiersz['pace_m3_per_hour'],
            ', '.join(wiersz['stations']),
        ])

    podsumowanie = raport['summary']
    ark.append([])
    ark.append(['Nieprzypisane', podsumowanie['unassigned_pieces'],
                podsumowanie['unassigned_m3']])
    ark.append(['Pokrycie atrybucją (%)', podsumowanie['attribution_coverage_pct']])
    ark.append(['UWAGA: wybór profilu na tablecie nie jest chroniony hasłem — '
                'dane mają charakter poglądowy'])

    szczegoly = wb.create_sheet('Szczegóły')
    szczegoly.append(['Data', 'Pracownik', 'Stanowisko', 'Sztuki', 'm3'])
    for komorka in szczegoly[1]:
        komorka.font = Font(bold=True)
    for wiersz in raport['rows']:
        szczegoly.append([wiersz['work_date'], wiersz['worker_name'],
                          wiersz['station_label'], wiersz['pieces'], wiersz['m3']])
    for wiersz in raport['unassigned']:
        szczegoly.append([wiersz['work_date'], 'Nieprzypisane',
                          wiersz['station_label'], wiersz['pieces'], wiersz['m3']])

    strumien = BytesIO()
    wb.save(strumien)
    strumien.seek(0)

    from flask import Response
    nazwa = f"wydajnosc_pracownikow_{raport['start_date']}_{raport['end_date']}.xlsx"
    odpowiedz = Response(
        strumien.getvalue(),
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    odpowiedz.headers['Content-Disposition'] = f'attachment; filename={nazwa}'
    return odpowiedz


@api_bp.route('/reports/station-output')
@login_required
def reports_station_output():
    """
    GET /production/api/reports/station-output?station=<code|all>
        &start_date=YYYY-MM-DD&end_date=YYYY-MM-DD
        (lub: &date=YYYY-MM-DD — wsteczna kompat, pojedynczy dzień)

    Zwraca pozycje produkcyjne, na których wybrane stanowisko (lub
    dowolne stanowisko gdy station='all') wykonało jakąkolwiek operację
    w zakresie dat (włącznie).

    Dla każdej pozycji (wiersz per item × stanowisko):
    - quantity_done_eod: stan quantity_done_<station> po ostatnim evencie
      w zakresie — ile zostało wykonane na koniec zakresu
    - day_delta_sum: netto ruch w zakresie (suma delta) — np. +5,-1,+2 = +6
    - station_code, station_label: stanowisko, którego dotyczy wiersz
    - quantity: total szt. pozycji
    - volume_per_unit, volume_done_eod (m³)
    - meta: short_product_id, original_product_name, baselinker_order_id, status, gatunek/grubość

    Timeline: 48 bucketów po 30 min, sumy delta i delta*volume_m3
    (przez wszystkie stanowiska gdy station='all'). Frontend dzieli
    przez days_count żeby uzyskać średnią dzienną.

    Sortowanie: po ostatnim evencie w zakresie (najnowsze najpierw).
    """
    from ...models import ProductionStationEvent
    from sqlalchemy import and_

    station = request.args.get('station', '').strip().lower()
    start_date_str = request.args.get('start_date', '').strip()
    end_date_str = request.args.get('end_date', '').strip()
    date_str = request.args.get('date', '').strip()  # wsteczna kompat

    is_all_stations = station == 'all'
    if not is_all_stations and station not in VALID_STATIONS:
        return jsonify({
            'success': False,
            'error': f'Nieprawidłowe stanowisko. Dozwolone: all, {sorted(VALID_STATIONS)}'
        }), 400

    # Parsowanie zakresu: preferuj start_date/end_date, fallback na date.
    try:
        if start_date_str and end_date_str:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
        elif date_str:
            start_date = datetime.strptime(date_str, '%Y-%m-%d').date()
            end_date = start_date
        else:
            start_date = end_date = date.today()
    except ValueError:
        return jsonify({
            'success': False,
            'error': 'Nieprawidłowy format daty (oczekiwane YYYY-MM-DD)'
        }), 400

    if start_date > end_date:
        return jsonify({
            'success': False,
            'error': 'Data początkowa musi być wcześniejsza lub równa końcowej'
        }), 400

    days_count = (end_date - start_date).days + 1
    if days_count > 365:
        return jsonify({
            'success': False,
            'error': 'Maksymalny zakres to 365 dni'
        }), 400

    range_start = datetime.combine(start_date, datetime.min.time())
    range_end = datetime.combine(end_date, datetime.max.time())

    try:
        # Wspólne filtry zakresu czasu (+ ewentualnie konkretne stanowisko).
        # Filtr ZRODLA_AUTOMATU jest OBOWIĄZKOWY i wspólny ze
        # station_events_service oraz worker_stats_service: complete_task()
        # generuje sztuczne eventy dla stanowisk POMINIĘTYCH (produkt
        # nieprzycinany na wymiar przeskakuje formatowanie i wykańczanie).
        # Bez niego trzy widgety na jednym ekranie pokazywały trzy różne
        # odpowiedzi na pytanie "ile zrobiono na formatowaniu" — a różnicy
        # nie dawało się wytłumaczyć wierszem "Nieprzypisane", bo tych sztuk
        # w liczniku pracowniczym w ogóle nie ma.
        from ...services.station_events_service import ZRODLA_AUTOMATU

        time_filters = [
            ProductionStationEvent.created_at >= range_start,
            ProductionStationEvent.created_at <= range_end,
            ~ProductionStationEvent.source.in_(ZRODLA_AUTOMATU),
        ]
        if not is_all_stations:
            time_filters.append(ProductionStationEvent.station_code == station)

        # Ile sztuk automat przeskoczył w tym zakresie — pokazujemy to jawnie
        # w widgecie, żeby nikt nie szukał "brakujących" sztuk po zmianie.
        pominiete_filtry = [
            ProductionStationEvent.created_at >= range_start,
            ProductionStationEvent.created_at <= range_end,
            ProductionStationEvent.source.in_(ZRODLA_AUTOMATU),
        ]
        if not is_all_stations:
            pominiete_filtry.append(ProductionStationEvent.station_code == station)
        auto_pominiete = db.session.query(
            func.coalesce(func.sum(ProductionStationEvent.delta), 0)
        ).filter(*pominiete_filtry).scalar() or 0

        # Per (item, station) agregacja eventów w zakresie.
        # Group by zawsze po (item_id, station_code) — dla pojedynczego
        # stanowiska wszystkie wiersze i tak mają to samo station_code,
        # więc koszt jest zerowy a kod jest unifikowany.
        # day_delta_sum = SUM(delta) (mimo nazwy — to ruch w całym zakresie)
        # last_event_at = MAX(created_at)
        agg = db.session.query(
            ProductionStationEvent.production_item_id.label('item_id'),
            ProductionStationEvent.station_code.label('station_code'),
            func.sum(ProductionStationEvent.delta).label('day_delta_sum'),
            func.max(ProductionStationEvent.created_at).label('last_event_at'),
            func.count(ProductionStationEvent.id).label('event_count'),
        ).filter(*time_filters).group_by(
            ProductionStationEvent.production_item_id,
            ProductionStationEvent.station_code,
        ).subquery()

        # quantity_done_after z ostatniego eventu w zakresie per (item, station).
        # Join po (item, station, last_event_at) — w razie remisu created_at
        # join produkcyjnie zwróci wszystkie kolizje, później dedup w pętli.
        last_event = db.session.query(
            ProductionStationEvent.production_item_id.label('item_id'),
            ProductionStationEvent.station_code.label('station_code'),
            ProductionStationEvent.created_at.label('last_event_at'),
            ProductionStationEvent.quantity_done_after.label('quantity_done_eod'),
        ).filter(*time_filters).subquery()

        rows = db.session.query(
            ProductionItem,
            agg.c.station_code,
            agg.c.day_delta_sum,
            agg.c.last_event_at,
            agg.c.event_count,
            last_event.c.quantity_done_eod,
        ).options(
            joinedload(ProductionItem.order),
            joinedload(ProductionItem.configuration),
        ).join(
            agg, ProductionItem.id == agg.c.item_id
        ).join(
            last_event,
            and_(
                last_event.c.item_id == agg.c.item_id,
                last_event.c.station_code == agg.c.station_code,
                last_event.c.last_event_at == agg.c.last_event_at,
            )
        ).order_by(agg.c.last_event_at.desc()).all()

        items_payload = []
        sum_qty_done_eod = 0
        sum_volume_done_eod = 0.0
        sum_day_delta = 0

        # Dedup po (item_id, station_code) — w razie remisu created_at
        # na ostatnim evencie agregat i tak ten sam, bierzemy pierwszy zwrot.
        seen_keys = set()
        for item, station_code_row, day_delta_sum, last_event_at, event_count, qty_done_eod in rows:
            key = (item.id, station_code_row)
            if key in seen_keys:
                continue
            seen_keys.add(key)

            qty_done_eod = int(qty_done_eod or 0)
            day_delta_sum = int(day_delta_sum or 0)
            volume_per_unit = float(item.volume_m3 or 0)
            volume_done_eod = volume_per_unit * qty_done_eod

            sum_qty_done_eod += qty_done_eod
            sum_volume_done_eod += volume_done_eod
            sum_day_delta += day_delta_sum

            items_payload.append({
                'item_id': item.id,
                'short_product_id': item.short_product_id,
                'product_name': item.original_product_name,
                'baselinker_order_id': item.order.baselinker_order_id if item.order else None,
                'internal_order_number': item.order.internal_order_number if item.order else None,
                'current_status': item.current_status,
                'quantity': item.quantity,
                'quantity_done_eod': qty_done_eod,
                'day_delta_sum': day_delta_sum,
                'event_count': int(event_count or 0),
                'volume_per_unit_m3': round(volume_per_unit, 4),
                'volume_done_eod_m3': round(volume_done_eod, 4),
                'wood_species': item.configuration.species if item.configuration else None,
                'thickness_cm': float(item.parsed_thickness_cm) if item.parsed_thickness_cm else None,
                'last_event_at': last_event_at.isoformat() if last_event_at else None,
                'station_code': station_code_row,
                'station_label': STATION_LABELS.get(station_code_row, station_code_row),
            })

        # Timeline 48 bucketów po 30 minut (00:00, 00:30, ..., 23:30)
        # bucket_idx = floor((HOUR*60 + MINUTE) / 30) ∈ [0, 47]
        # Net delta per bucket (cofnięcia mogą dać wartość ujemną).
        # Sumowanie po wszystkich dniach w zakresie — frontend dzieli
        # przez days_count żeby uzyskać średnią dzienną gdy zakres > 1 dnia.
        bucket_idx_expr = func.floor(
            (func.hour(ProductionStationEvent.created_at) * 60
             + func.minute(ProductionStationEvent.created_at)) / 30
        ).label('bucket_idx')

        timeline_rows = db.session.query(
            bucket_idx_expr,
            func.sum(ProductionStationEvent.delta).label('pieces_sum'),
            func.sum(
                ProductionStationEvent.delta * ProductionItem.volume_m3
            ).label('m3_sum'),
        ).join(
            ProductionItem,
            ProductionItem.id == ProductionStationEvent.production_item_id
        ).filter(*time_filters).group_by(bucket_idx_expr).all()

        pieces_buckets = [0] * 48
        m3_buckets = [0.0] * 48
        for bucket_idx, pieces_sum, m3_sum in timeline_rows:
            idx = int(bucket_idx) if bucket_idx is not None else None
            if idx is None or idx < 0 or idx > 47:
                continue
            pieces_buckets[idx] = int(pieces_sum or 0)
            m3_buckets[idx] = round(float(m3_sum or 0.0), 4)

        bucket_labels = [
            f"{i // 2:02d}:{'30' if i % 2 else '00'}"
            for i in range(48)
        ]

        return jsonify({
            'success': True,
            'station': station,
            'station_label': 'Wszystkie stanowiska' if is_all_stations
                else STATION_LABELS.get(station, station),
            'is_all_stations': is_all_stations,
            # Wsteczna kompat: 'date' = start gdy pojedynczy dzień, inaczej None
            'date': start_date.isoformat() if days_count == 1 else None,
            'start_date': start_date.isoformat(),
            'end_date': end_date.isoformat(),
            'days_count': days_count,
            'items': items_payload,
            'summary': {
                'items_count': len(items_payload),
                'total_quantity_done_eod': sum_qty_done_eod,
                'total_day_delta': sum_day_delta,
                'total_volume_done_eod_m3': round(sum_volume_done_eod, 4),
                # Sztuki, które automat przeskoczył — NIE są wliczone powyżej.
                # Pokazujemy je jawnie, żeby nikt nie szukał różnicy między
                # tym widgetem a stanem quantity_done produktu.
                'auto_skipped_pieces': int(auto_pominiete),
            },
            'timeline': {
                'buckets': bucket_labels,
                'pieces': pieces_buckets,
                'volume_m3': m3_buckets,
                'days_count': days_count,
            },
        })

    except Exception as e:
        logger.error("Błąd /reports/station-output", extra={
            'user_id': current_user.id,
            'station': station,
            'start_date': start_date.isoformat() if 'start_date' in locals() else None,
            'end_date': end_date.isoformat() if 'end_date' in locals() else None,
            'error': str(e),
        })
        return jsonify({'success': False, 'error': str(e)}), 500


@api_bp.route('/reports-tab-content')
@login_required
def reports_tab_content():
    """
    Szkielet zakładki Raporty: pasek KPI + nawigacja podzakładek.

    Dane widgetów NIE jadą tędy — każda podzakładka pobiera swoje osobno
    (patrz /reports/sub/<nazwa>). Tutaj zostają dwa agregaty na trzy kafelki.
    """
    try:
        logger.info("AJAX: Ładowanie zawartości reports-tab", extra={
            'user_id': current_user.id,
            'user_role': getattr(current_user, 'role', 'unknown')
        })

        from ...models import ProductionItem

        today = date.today()

        # Kafelki KPI: ukończone i m³ z ostatnich 7 dni. Wcześniej liczyła to
        # pętla po dniach — 14 zapytań na dwie liczby, które i tak zaraz były
        # sumowane. Rozbicie dzienne nie miało konsumenta (ani szablon, ani JS
        # go nie czytały), więc jeden agregat na całym zakresie daje ten sam
        # wynik za jedno zapytanie.
        tydzien_start = datetime.combine(today - timedelta(days=6), datetime.min.time())
        tydzien_koniec = datetime.combine(today, datetime.max.time())

        tydzien_sztuk, tydzien_m3 = db.session.query(
            func.count(ProductionItem.id),
            func.sum(ProductionItem.volume_m3 * ProductionItem.quantity)
        ).filter(
            ProductionItem.current_status == 'spakowane',
            ProductionItem.packaging_completed_at >= tydzien_start,
            ProductionItem.packaging_completed_at <= tydzien_koniec
        ).one()

        # Osobny COUNT zamiast sumy po rozbiciu statusów: pasek KPI szkieletu
        # nie może zależeć od danych widgetu, który po przebudowie mieszka
        # w innej podzakładce i ładuje się dopiero po kliknięciu.
        total_in_system = db.session.query(func.count(ProductionItem.id)).filter(
            ProductionItem.current_status.isnot(None)
        ).scalar() or 0

        # Szkielet nie zna już danych widgetów — dostaje wyłącznie trzy liczby
        # do kafelków. Reszta jedzie przez /reports/sub/<nazwa>, każda porcja
        # dopiero wtedy, gdy ktoś na nią patrzy.
        rendered_html = render_template(
            'components/reports-tab-content.html',
            reports_summary={
                'week_completed': int(tydzien_sztuk or 0),
                'week_volume': float(tydzien_m3 or 0.0),
                'total_in_system': int(total_in_system),
            },
        )

        # Bez klucza 'data': jedyny konsument odpowiedzi (production-app-loader
        # loadReportsTab) czyta wyłącznie 'html', a kopia całego kompletu danych
        # dorzucała ~5 kB do każdego wejścia na zakładkę.
        return jsonify({
            'success': True,
            'html': rendered_html,
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


# ════════════════════════════════════════════════════════════════════════════
# Podzakładki zakładki Raporty
#
# Zakładka Raporty ładowała jednym strzałem komplet danych dla sześciu widgetów
# naraz — także tych, w które nikt nie patrzy. Podzakładka to fragment HTML
# pobierany dopiero przy kliknięciu, z własnym (i tylko własnym) kompletem
# zapytań.
# ════════════════════════════════════════════════════════════════════════════

def _kontekst_stanowiska():
    """Wykonanie stanowiska w dniu + wydajność dzienna. Zero SQL — oba widgety
    dociągają swoje liczby własnymi endpointami po stronie przeglądarki."""
    return {'station_choices': station_choices()}


def _kontekst_ludzie():
    """Wydajność pracowników. Jak wyżej: sam <select> stanowisk, dane z
    /reports/worker-output."""
    return {'station_choices': station_choices()}


def _kontekst_miks():
    """Rozkład wg statusów + analiza produktów.

    Sześć GROUP BY po całej tabeli, bez zakresu dat — najdroższa podzakładka
    i jednocześnie ta, w którą klika się najrzadziej. Dlatego liczy się dopiero
    tutaj, a nie przy każdym wejściu na Raporty.
    """
    # Raport statusów - dynamicznie ze wszystkich istniejących w bazie
    status_stats = db.session.query(
        ProductionItem.current_status,
        func.count(ProductionItem.id).label('count'),
        func.sum(ProductionItem.volume_m3 * ProductionItem.quantity).label('volume')
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

    # Species+technology breakdown per status
    species_by_status_raw = db.session.query(
        ProductionItem.current_status,
        ProductionConfiguration.species,
        ProductionConfiguration.technology,
        func.sum(ProductionItem.volume_m3 * ProductionItem.quantity).label('volume')
    ).join(ProductionConfiguration, ProductionItem.configuration_id == ProductionConfiguration.id).filter(
        ProductionItem.current_status.isnot(None),
        ProductionConfiguration.species.isnot(None)
    ).group_by(
        ProductionItem.current_status,
        ProductionConfiguration.species,
        ProductionConfiguration.technology
    ).all()

    species_by_status = {}
    for row in species_by_status_raw:
        status = row[0]
        species = row[1] or '—'
        tech = row[2] or ''
        label = f"{species} {tech}".strip()
        vol = float(row[3] or 0)
        if status not in species_by_status:
            species_by_status[status] = []
        species_by_status[status].append({'label': label, 'volume': round(vol, 3)})

    # Sort each status's species list by volume desc
    for status in species_by_status:
        species_by_status[status].sort(key=lambda x: -x['volume'])

    # Attach to status_report
    for item in status_report:
        item['species_breakdown'] = species_by_status.get(item['status'], [])

    # Rozkład według gatunków drewna
    species_stats = db.session.query(
        ProductionConfiguration.species,
        func.count(ProductionItem.id).label('count'),
        func.sum(ProductionItem.volume_m3 * ProductionItem.quantity).label('volume')
    ).join(ProductionConfiguration, ProductionItem.configuration_id == ProductionConfiguration.id).filter(
        ProductionConfiguration.species.isnot(None),
        ProductionItem.current_status != 'anulowane'
    ).group_by(ProductionConfiguration.species).all()

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
        func.sum(ProductionItem.volume_m3 * ProductionItem.quantity).label('volume')
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
        ProductionConfiguration.technology,
        func.count(ProductionItem.id).label('count'),
        func.sum(ProductionItem.volume_m3 * ProductionItem.quantity).label('volume')
    ).join(ProductionConfiguration, ProductionItem.configuration_id == ProductionConfiguration.id).filter(
        ProductionConfiguration.technology.isnot(None),
        ProductionItem.current_status != 'anulowane'
    ).group_by(ProductionConfiguration.technology).all()

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
        ProductionConfiguration.wood_class,
        func.count(ProductionItem.id).label('count'),
        func.sum(ProductionItem.volume_m3 * ProductionItem.quantity).label('volume')
    ).join(ProductionConfiguration, ProductionItem.configuration_id == ProductionConfiguration.id).filter(
        ProductionConfiguration.wood_class.isnot(None),
        ProductionConfiguration.wood_class != 'unknown',
        ProductionItem.current_status != 'anulowane'
    ).group_by(ProductionConfiguration.wood_class).all()

    wood_class_breakdown = [
        {
            'name': row[0] or 'Nieokreślona',
            'count': row[1],
            'volume': float(row[2] or 0)
        }
        for row in wood_class_stats
    ]

    return {
        'status_breakdown': status_report,
        'species_breakdown': species_breakdown,
        'thickness_breakdown': thickness_breakdown,
        'technology_breakdown': technology_breakdown,
        'wood_class_breakdown': wood_class_breakdown,
        # Mianownik kolumny "% całości" liczymy z tego, co już mamy w ręku:
        # status_report obejmuje wszystkie produkty z niepustym statusem, czyli
        # dokładnie tyle, ile liczy COUNT(*) w pasku KPI. Osobne zapytanie
        # dołożyłoby siódme na tę samą liczbę.
        'total_in_system': sum(poz['count'] for poz in status_report),
    }


def _kontekst_system():
    """Historia synchronizacji — jedno zapytanie, oglądane raz na miesiąc."""
    sync_history = ProductionSyncLog.query\
                                   .order_by(ProductionSyncLog.sync_started_at.desc())\
                                   .limit(10).all()
    return {
        'sync_history': [
            {
                'date': sync.sync_started_at.isoformat(),
                'status': sync.sync_status,  # POPRAWIONE: sync_status zamiast status
                'items_processed': (sync.products_created or 0) + (sync.products_updated or 0),
                'duration_seconds': sync.sync_duration_seconds or 0
            }
            for sync in sync_history
        ]
    }


# Jedna mapa zamiast osobnej trasy na podzakładkę: whitelist i router siedzą
# w tym samym miejscu, więc nowa podzakładka to jedna linia, a nieznany slug
# z URL-a nie ma jak dojechać do render_template.
_PODZAKLADKI = {
    'stanowiska': (_kontekst_stanowiska, 'components/reports/stations.html'),
    'ludzie': (_kontekst_ludzie, 'components/reports/workers.html'),
    'miks': (_kontekst_miks, 'components/reports/mix.html'),
    'system': (_kontekst_system, 'components/reports/system.html'),
}


@api_bp.route('/reports/sub/<nazwa>')
@login_required
def reports_subtab(nazwa):
    """
    Fragment HTML jednej podzakładki Raportów.

    Zwraca surowy text/html, nie kopertę JSON: markup widgetów jest renderowany
    w Jinja (tabele, legendy, dane przez |tojson), a skrypty i tak muszą jechać
    razem z nim — koperta niczego by nie uprościła, a doklejała martwe kilobajty.
    Błąd jednej podzakładki kończy się jej własnym komunikatem, a nie wywaloną
    całą zakładką (ten sam wzorzec co workers_tab_content).
    """
    wpis = _PODZAKLADKI.get(nazwa)
    if wpis is None:
        return (
            '<div class="alert alert-warning">Nieznana podzakładka raportów.</div>',
            404,
        )

    buduj_kontekst, szablon = wpis
    try:
        return render_template(szablon, **buduj_kontekst())
    except Exception as e:
        logger.error("Błąd podzakładki raportów", extra={
            'user_id': current_user.id,
            'podzakladka': nazwa,
            'error': str(e),
        })
        return (
            f'<div class="alert alert-danger">Błąd ładowania: {e}</div>',
            500,
        )
