# modules/production/routers/api/products_api.py
"""
Products tab content + CRUD + task completion + station progress endpoints.
Extracted from api_routers.py.
"""

import json
import math
import traceback
from datetime import datetime, date, timedelta
from flask import request, jsonify, render_template, current_app
from flask_login import login_required, current_user
from extensions import db
from sqlalchemy import or_, func, distinct, cast, String
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import joinedload

from . import api_bp, logger, ProductionItem, ProductionError, get_local_now
from .common_api import _format_status, _validate_config_value
from modules.production.models import ProductionOrder, ProductionConfiguration
from modules.production.logistics import sposoby
from modules.production.services import blokady_zamowien, zmiana_statusu
from modules.production.services.archiwum_zamowien import (
    warunek_archiwum as _archived_order_condition,
    data_zakonczenia_expr as _archive_completed_expr,
    zapytanie_archiwum as _archive_orders_query,
    statystyki_archiwum as _archive_stats,
    etapy_zamowien as _archive_order_stages,
)


# Ile zamówień archiwalnych na stronę.
# Do archiwum wchodzi się po konkretne zamówienie (reklamacja, "co dokładnie
# im wysłaliśmy w marcu"), a nie żeby przewijać historię firmy — dlatego liczy
# się szybka pierwsza strona i filtry, nie długość listy. 25 kart to ok. dwa
# ekrany scrolla i ~70 pozycji produktowych, czyli ~200 KB odpowiedzi.
ARCHIVE_ORDERS_PER_PAGE = 25


# ============================================================================
# HELPERY WSPÓLNE DLA WIDOKÓW LISTY PRODUKTÓW
# ============================================================================


def _parse_date_arg(raw):
    """'YYYY-MM-DD' → datetime; nieparsowalne / puste → None (filtr nieaktywny)."""
    raw = (raw or '').strip()
    if not raw:
        return None
    try:
        return datetime.strptime(raw, '%Y-%m-%d')
    except ValueError:
        return None


def _format_thickness_option(value):
    """
    Etykieta grubości dla filtra, np. 4.0 → '4cm', 1.5 → '1.5cm'.

    Format musi być taki, jaki JS-owy `${p.parsed_thickness_cm}cm` wyprodukowałby
    z liczby po JSON.parse — inaczej opcja z listy nigdy nie trafi w produkt
    (JS renderuje 4.0 jako '4', Python jako '4.0').
    """
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if f <= 0:
        return None
    return f'{f:g}cm'


def _parse_thickness_option(label):
    """Odwrotność `_format_thickness_option` — '4cm' → 4.0. Śmieci → None."""
    try:
        return float(str(label).strip().lower().replace('cm', ''))
    except (TypeError, ValueError):
        return None


def _product_counts_by_order(order_ids):
    """
    {order_id: liczba pozycji} jednym GROUP BY zamiast COUNT-a per produkt.

    Wcześniej serializer robił osobne `SELECT COUNT(*) WHERE order_id = ?` dla
    każdego produktu — na archiwum dawało to 2315 zapytań z 3152.
    """
    ids = [oid for oid in set(order_ids) if oid]
    if not ids:
        return {}
    rows = db.session.query(
        ProductionItem.order_id, func.count(ProductionItem.id)
    ).filter(ProductionItem.order_id.in_(ids)).group_by(ProductionItem.order_id).all()
    return {oid: cnt for oid, cnt in rows}


def _workers_for_products(product_ids):
    """
    Kto pracował przy produktach — JEDNO zapytanie na całą listę, nie jedno
    na produkt (docs/worker-profiles-backend.md §7.3). Awaria tej części nie
    może wywrócić listy produktów: brak nazwisk jest znośny, brak listy nie.
    Rollback jest tu konieczny — bez niego sesja zostaje w stanie failed
    i wywraca DOPIERO kolejne zapytanie, w zupełnie innym miejscu kodu.
    """
    try:
        from ...services.worker_stats_service import get_workers_for_products
        return get_workers_for_products(product_ids)
    except Exception as e:
        db.session.rollback()
        logger.warning("Nie udało się pobrać atrybucji pracowników do listy",
                       extra={'error': str(e)})
        return {}


def _serialize_product(product, workers_by_product, product_counts_by_order):
    """
    Produkt → dict dla frontendu. Wyciągnięte z pętli endpointu, żeby widok
    archiwum i widok aktywnych korzystały z jednego formatu.

    `product.order` i `product.configuration` MUSZĄ być tu już doczytane
    (joinedload) — inaczej każde odwołanie do sąsiedniej tabeli to osobny SELECT.
    """
    def get_attr(obj, attr_name, default=None):
        return getattr(obj, attr_name, default) if hasattr(obj, attr_name) else default

    # Oblicz dni do deadline
    days_to_deadline = None
    if hasattr(product, 'deadline_date') and product.deadline_date:
        try:
            deadline = product.deadline_date
            if isinstance(deadline, str):
                deadline = datetime.strptime(deadline, '%Y-%m-%d').date()
            days_to_deadline = (deadline - date.today()).days
        except Exception:
            days_to_deadline = None

    # Bezpieczne pobieranie objętości
    volume_m3 = 0.0
    try:
        vol = get_attr(product, 'volume_m3', 0)
        volume_m3 = float(vol) if vol is not None else 0.0
    except (ValueError, TypeError):
        volume_m3 = 0.0

    # Bezpieczne pobieranie wartości netto
    total_value_net = 0.0
    try:
        val = get_attr(product, 'total_value_net', 0)
        total_value_net = float(val) if val is not None else 0.0
    except (ValueError, TypeError):
        total_value_net = 0.0

    # Bezpieczne pobieranie ceny jednostkowej
    unit_price_net = 0.0
    try:
        price = get_attr(product, 'unit_price_net', 0)
        unit_price_net = float(price) if price is not None else 0.0
    except (ValueError, TypeError):
        unit_price_net = 0.0

    # Bezpieczne pobieranie parsowanych wymiarów
    parsed_length_cm = 0.0
    parsed_width_cm = 0.0
    parsed_thickness_cm = 0.0
    try:
        if get_attr(product, 'parsed_length_cm') is not None:
            parsed_length_cm = float(get_attr(product, 'parsed_length_cm', 0))
        if get_attr(product, 'parsed_width_cm') is not None:
            parsed_width_cm = float(get_attr(product, 'parsed_width_cm', 0))
        if get_attr(product, 'parsed_thickness_cm') is not None:
            parsed_thickness_cm = float(get_attr(product, 'parsed_thickness_cm', 0))
    except (ValueError, TypeError):
        pass

    order = product.order
    config = product.configuration

    return {
        # Podstawowe dane
        'id': product.id,
        'short_product_id': get_attr(product, 'short_product_id', ''),
        'original_product_name': get_attr(product, 'original_product_name', ''),
        'current_status': get_attr(product, 'current_status', 'czeka_na_wyciecie'),
        'priority_rank': get_attr(product, 'priority_rank', None),
        'priority_manual_override': get_attr(product, 'priority_manual_override', False),

        # {station_code: ['Adam K.', ...]} — puste dla produktów sprzed
        # wdrożenia profili i dla pracy bez wybranego profilu na tablecie
        'workers_by_station': workers_by_product.get(product.id, {}),

        # Wymiary i wartości
        'volume_m3': volume_m3,
        'total_value_net': total_value_net,
        'unit_price_net': unit_price_net,

        # Deadline
        'deadline_date': get_attr(product, 'deadline_date').isoformat() if get_attr(product, 'deadline_date') else None,
        'days_until_deadline': days_to_deadline,

        # Dane klienta
        'client_name': (order.client_name if order else None) or '',
        'client_email': (order.client_email if order else None) or '',
        'client_phone': (order.client_phone if order else None) or '',
        'delivery_address': (order.delivery_address if order else None) or '',

        # Dane zamówienia
        'internal_order_number': (order.internal_order_number if order else None) or '',
        # Gwiazdki zamówienia (priorytety produkcji, K4a): Lista produkcyjna czyta je zamiast `is_priority`
        # pozycji, który zostaje dla innych czytelników. Zamówienie już doczytane (`joinedload`) — bez zapytań.
        'order_id': product.order_id,
        'order_priority_stars': int(order.priority_stars or 0) if order else 0,
        'baselinker_order_id': order.baselinker_order_id if order else None,
        'baselinker_product_id': get_attr(product, 'baselinker_product_id', ''),
        'product_sequence_in_order': get_attr(product, 'product_sequence_in_order', 1),
        'total_products_in_order': product_counts_by_order.get(product.order_id, 1) if product.order_id else 1,

        # POPRAWIONE: Specyfikacja produktu - PARSOWANE POLA z bazy danych
        'parsed_wood_species': config.species if config else None,
        'parsed_technology': config.technology if config else None,
        'parsed_wood_class': config.wood_class if config else None,
        'parsed_length_cm': parsed_length_cm,
        'parsed_width_cm': parsed_width_cm,
        'parsed_thickness_cm': parsed_thickness_cm,
        'parsed_finish_state': get_attr(product, 'parsed_finish_state', None),
        'parsed_edge_processing': get_attr(product, 'parsed_edge_processing', False),
        'cut_to_size': bool(get_attr(product, 'cut_to_size', True)),
        'shape': get_attr(product, 'shape', None),

        # Produkcja - statusy i czasami
        'cutting_started_at': get_attr(product, 'cutting_started_at').isoformat() if get_attr(product, 'cutting_started_at') else None,
        'cutting_completed_at': get_attr(product, 'cutting_completed_at').isoformat() if get_attr(product, 'cutting_completed_at') else None,
        'cutting_duration_minutes': get_attr(product, 'cutting_duration_minutes', None),
        'assembly_started_at': get_attr(product, 'assembly_started_at').isoformat() if get_attr(product, 'assembly_started_at') else None,
        'assembly_completed_at': get_attr(product, 'assembly_completed_at').isoformat() if get_attr(product, 'assembly_completed_at') else None,
        'assembly_duration_minutes': get_attr(product, 'assembly_duration_minutes', None),
        'packaging_started_at': get_attr(product, 'packaging_started_at').isoformat() if get_attr(product, 'packaging_started_at') else None,
        'packaging_completed_at': get_attr(product, 'packaging_completed_at').isoformat() if get_attr(product, 'packaging_completed_at') else None,
        'packaging_duration_minutes': get_attr(product, 'packaging_duration_minutes', None),

        # Logistyka
        'logistics_completed_at': order.logistics_completed_at.isoformat() if order and order.logistics_completed_at else None,
        'painting_completed_at': get_attr(product, 'painting_completed_at').isoformat() if get_attr(product, 'painting_completed_at') else None,
        'override_delivery_method': order.override_delivery_method if order else None,
        'is_personal_pickup': order.is_personal_pickup if order else None,

        # Przypisani pracownicy
        'cutting_assigned_worker_id': get_attr(product, 'cutting_assigned_worker_id', None),
        'assembly_assigned_worker_id': get_attr(product, 'assembly_assigned_worker_id', None),
        'packaging_assigned_worker_id': get_attr(product, 'packaging_assigned_worker_id', None),

        # Notatki i problemy
        'production_notes': get_attr(product, 'production_notes', ''),
        'quality_issues': get_attr(product, 'quality_issues', ''),

        # Timestampy
        'created_at': product.created_at.isoformat() if hasattr(product, 'created_at') and product.created_at else None,
        'updated_at': product.updated_at.isoformat() if hasattr(product, 'updated_at') and product.updated_at else None,
        'sync_source': order.sync_source if order else None,

        # Załączniki
        'attachment_file_name': order.attachment_file_name if order else None,
        'attachment_file_url': order.attachment_file_url if order else None,

        # NOWE: Quantity fields (2025-11)
        'quantity': get_attr(product, 'quantity', 1),
        'quantity_done_cutting': get_attr(product, 'quantity_done_cutting', 0),
        'quantity_done_assembly': get_attr(product, 'quantity_done_assembly', 0),
        'quantity_done_gluing': get_attr(product, 'quantity_done_gluing', 0),
        'quantity_done_formatting': get_attr(product, 'quantity_done_formatting', 0),
        'quantity_done_edges': get_attr(product, 'quantity_done_edges', 0),
        'quantity_done_painting': get_attr(product, 'quantity_done_painting', 0),
        'quantity_done_packaging': get_attr(product, 'quantity_done_packaging', 0),

        # Dodatkowe pola z zamówienia
        'client_order_number': order.client_order_number if order else None,
        'quote_number': order.quote_number if order else None,
        'order_notes': order.order_notes if order else None,

        # Źródło zamówienia (kanał sprzedaży z BaseLinkera)
        'order_source': order.order_source if order else None,
        'order_source_id': order.order_source_id if order else None,
        'order_source_name': order.order_source_name if order else None,
        'order_source_display': order.order_source_display if order else None,

        # Priorytet ręczny (gwiazdka)
        'is_priority': get_attr(product, 'is_priority', False),

        # Unique identifier dla frontend
        'unique_id': f"{get_attr(product, 'short_product_id', '')}-{product.id}"
    }


# ============================================================================
# WIDOK ARCHIWUM — filtry + paginacja po stronie serwera
# ============================================================================


def _archive_filter_options(completed_from_dt, completed_to_dt, wdrozenie=None):
    """
    Listy wartości do multiselectów — JEDNO zapytanie DISTINCT po zakresie
    archiwum (z uwzględnieniem zakresu dat, bez pozostałych filtrów, żeby dało
    się filtr zdjąć). Przy paginacji nie da się ich już zebrać z załadowanych
    zamówień — widać tylko jedną stronę.
    """
    ion_subq = _archive_orders_query(completed_from_dt, completed_to_dt, wdrozenie=wdrozenie).subquery()

    rows = db.session.query(
        ProductionConfiguration.species,
        ProductionConfiguration.technology,
        ProductionConfiguration.wood_class,
        ProductionItem.parsed_thickness_cm,
        ProductionItem.current_status,
    ).select_from(ProductionItem).join(
        ProductionOrder, ProductionItem.order_id == ProductionOrder.id
    ).outerjoin(
        ProductionConfiguration,
        ProductionItem.configuration_id == ProductionConfiguration.id
    ).filter(
        ProductionOrder.internal_order_number.in_(db.session.query(ion_subq.c.ion))
    ).distinct().all()

    species, technologies, wood_classes, thicknesses, statuses = set(), set(), set(), set(), set()
    for row in rows:
        if row.species:
            species.add(row.species)
        if row.technology:
            technologies.add(row.technology)
        if row.wood_class:
            wood_classes.add(row.wood_class)
        label = _format_thickness_option(row.parsed_thickness_cm)
        if label:
            thicknesses.add(label)
        if row.current_status:
            statuses.add(row.current_status)

    return {
        'wood_species': sorted(species),
        'technologies': sorted(technologies),
        'wood_classes': sorted(wood_classes),
        'thicknesses': sorted(thicknesses, key=lambda x: _parse_thickness_option(x) or 0),
        'statuses': sorted(statuses),
    }


def _archive_sort_key_split(rows):
    """
    Sortowanie zgodne z `sortOrdersByCompletedDesc()`: data zakończenia malejąco,
    zamówienia bez daty na końcu. Numer zamówienia jako drugi klucz — JS go nie
    miał, ale bez deterministycznego remisu ta sama pozycja potrafiłaby wypaść
    na dwóch stronach naraz albo zniknąć.
    """
    z_data = [r for r in rows if r.completed_at is not None]
    bez_daty = [r for r in rows if r.completed_at is None]
    z_data.sort(key=lambda r: (r.completed_at, r.ion or ''), reverse=True)
    bez_daty.sort(key=lambda r: (r.ion or ''), reverse=True)
    return z_data + bez_daty


def _archive_tab_content():
    """
    GET /production/api/products-tab-content?view=archive

    Zwraca JEDNĄ stronę zamówień archiwalnych: filtry i paginacja liczone
    w bazie, statystyki i listy wartości filtrów — dla całego przefiltrowanego
    zbioru, nie dla widocznej strony.
    """
    completed_from_dt = _parse_date_arg(request.args.get('completed_from'))
    completed_to_raw = (request.args.get('completed_to') or '').strip()
    completed_to_dt = _parse_date_arg(completed_to_raw)
    if completed_to_dt is not None:
        # "do" włącznie — porównujemy z początkiem następnego dnia
        completed_to_dt = completed_to_dt + timedelta(days=1)

    thickness_values = [
        v for v in (_parse_thickness_option(t) for t in request.args.getlist('thickness'))
        if v is not None
    ]
    filters = {
        'search': (request.args.get('search') or '').strip(),
        'wood_species': [v for v in request.args.getlist('wood_species') if v],
        'technologies': [v for v in request.args.getlist('technology') if v],
        'wood_classes': [v for v in request.args.getlist('wood_class') if v],
        'thicknesses': thickness_values,
    }

    # Jeden odczyt znacznika na żądanie — data „Zakończono” zamknięć historycznych (spec 10).
    from modules.production.logistics.services import weryfikacja
    wdrozenie = weryfikacja.data_wdrozenia()

    order_rows = _archive_orders_query(completed_from_dt, completed_to_dt, filters, wdrozenie).all()
    stats_data = _archive_stats(order_rows)

    try:
        page = int(request.args.get('page', 1))
    except (TypeError, ValueError):
        page = 1
    total_pages = max(1, math.ceil(len(order_rows) / ARCHIVE_ORDERS_PER_PAGE))
    page = min(max(1, page), total_pages)

    sorted_rows = _archive_sort_key_split(order_rows)
    offset = (page - 1) * ARCHIVE_ORDERS_PER_PAGE
    page_rows = sorted_rows[offset:offset + ARCHIVE_ORDERS_PER_PAGE]
    page_ions = [r.ion for r in page_rows]
    completed_by_ion = {r.ion: r.completed_at for r in page_rows}

    products = []
    if page_ions:
        # joinedload jest tu obowiązkowy: bez niego każde `product.order` /
        # `product.configuration` w serializerze to osobny SELECT (823 zapytania
        # na pełnym archiwum).
        products = ProductionItem.query.options(
            joinedload(ProductionItem.order),
            joinedload(ProductionItem.configuration),
        ).filter(
            ProductionItem.order_id.in_(
                db.session.query(ProductionOrder.id).filter(
                    ProductionOrder.internal_order_number.in_(page_ions)
                )
            )
        ).order_by(
            ProductionItem.product_sequence_in_order.asc(),
            ProductionItem.id.asc()
        ).all()

        # Kolejność zamówień musi odpowiadać posortowanej stronie — frontend
        # grupuje karty w kolejności napotkania produktów.
        ion_order = {ion: idx for idx, ion in enumerate(page_ions)}
        products.sort(key=lambda p: (
            ion_order.get(p.order.internal_order_number if p.order else None, 10 ** 6),
            p.product_sequence_in_order or 0,
            p.id,
        ))

    workers_by_product = _workers_for_products([p.id for p in products])
    product_counts = _product_counts_by_order([p.order_id for p in products])

    stages_by_ion = _archive_order_stages(products)

    products_data = []
    for product in products:
        product_dict = _serialize_product(product, workers_by_product, product_counts)
        completed_at = completed_by_ion.get(product_dict['internal_order_number'])
        product_dict['order_completed_at'] = completed_at.isoformat() if completed_at else None
        stage_status, stage_label = stages_by_ion.get(
            product_dict['internal_order_number'], (None, None))
        product_dict['order_stage_status'] = stage_status
        product_dict['order_stage_label'] = stage_label
        products_data.append(product_dict)

    filters_data = _archive_filter_options(completed_from_dt, completed_to_dt, wdrozenie)

    logger.info("Archiwum: zwrócono stronę zamówień", extra={
        'page': page,
        'total_pages': total_pages,
        'orders_after_filters': len(order_rows),
        'products_on_page': len(products_data),
    })

    return jsonify({
        'success': True,
        'html': render_template('components/archive-tab-content.html'),
        'initial_data': {
            'products': products_data,
            'stats': stats_data,
            'filters': filters_data,
            'pagination': {
                'page': page,
                'per_page': ARCHIVE_ORDERS_PER_PAGE,
                'total_orders': len(order_rows),
                'total_pages': total_pages,
                'has_prev': page > 1,
                'has_next': page < total_pages,
            },
            'total_count': len(products_data),
            'load_all': False,
        },
        'products_count': len(products_data),
    })


# ============================================================================
# API ROUTERS - PRD Section 6.3 (CRON i Synchronizacja)
# ============================================================================


@api_bp.route('/products-tab-content', methods=['GET'])
@login_required  
def products_tab_content():
    """
    Zawartość zakładki produktów (widoki active / all) oraz archiwum.

    active/all zwracają wszystkie pasujące pozycje naraz — to zbiór rzędu setek
    pozycji w toku, który mieści się w jednej odpowiedzi. Archiwum rośnie bez
    końca (cała historia firmy), więc ma osobną ścieżkę z paginacją i filtrami
    liczonymi w bazie — patrz `_archive_tab_content`.
    """
    try:
        # Tryb widoku: active (default) | archive | all
        # active  → ukrywa zamówienia archiwalne (zamknięte w Logistyce albo w całości anulowane)
        # archive → pokazuje wyłącznie te zamówienia
        # all     → bez filtra
        view_mode = request.args.get('view', 'active').lower()
        if view_mode not in ('active', 'archive', 'all'):
            view_mode = 'active'

        # Archiwum ma własną ścieżkę: filtry i paginacja po stronie bazy.
        # Bez tego całe 2300+ spakowanych pozycji ładowałoby się do jednego HTML-a.
        if view_mode == 'archive':
            return _archive_tab_content()

        # Pobierz podstawowe parametry
        status_filter = request.args.get('status', 'all')
        search_query = request.args.get('search', '')
        load_all = request.args.get('load_all', 'true').lower() == 'true'

        # Pobierz produkty z bazy danych - BEZ LIMITU
        # Zawsze joinujemy ProductionOrder — potrzebne do filtrowania i wyszukiwania po polach order-level
        # joinedload: serializer sięga do product.order i product.configuration przy
        # KAŻDEJ pozycji — bez eager loadingu to setki dodatkowych SELECT-ów.
        products_query = ProductionItem.query.join(ProductionOrder).options(
            joinedload(ProductionItem.order),
            joinedload(ProductionItem.configuration),
        )

        # active: odetnij zamówienia archiwalne (zamknięte w Logistyce albo wszystkie
        # pozycje anulowane) — ten sam warunek co w widoku archiwum. Spakowane, ale
        # otwarte w Logistyce zostają tu, aż Logistyka zamknie cykl (krok 4.5).
        if view_mode == 'active':
            archived_subq = db.session.query(
                ProductionOrder.internal_order_number.label('ion')
            ).join(
                ProductionItem, ProductionItem.order_id == ProductionOrder.id
            ).filter(
                ProductionOrder.internal_order_number.isnot(None)
            ).group_by(
                ProductionOrder.internal_order_number
            ).having(_archived_order_condition()).subquery()

            products_query = products_query.filter(
                ~ProductionOrder.internal_order_number.in_(
                    db.session.query(archived_subq.c.ion)
                )
            )

        # Filtrowanie po statusie
        if status_filter and status_filter != 'all':
            products_query = products_query.filter(ProductionItem.current_status == status_filter)
        
        # Wyszukiwanie - bezpieczne sprawdzenie atrybutów
        if search_query:
            search_pattern = f"%{search_query}%"
            search_conditions = []
            
            if hasattr(ProductionItem, 'original_product_name'):
                search_conditions.append(ProductionItem.original_product_name.ilike(search_pattern))
            if hasattr(ProductionItem, 'short_product_id'):
                search_conditions.append(ProductionItem.short_product_id.ilike(search_pattern))
            # order-level fields via ProductionOrder (join already present)
            search_conditions.append(ProductionOrder.client_name.ilike(search_pattern))
            search_conditions.append(ProductionOrder.internal_order_number.ilike(search_pattern))
            search_conditions.append(ProductionOrder.client_order_number.ilike(search_pattern))
            search_conditions.append(ProductionOrder.quote_number.ilike(search_pattern))
            search_conditions.append(cast(ProductionOrder.baselinker_order_id, String).ilike(search_pattern))

            if search_conditions:
                products_query = products_query.filter(or_(*search_conditions))

        # Obsługa parametrów sortowania
        sort_by = request.args.get('sort_by', 'priority_rank')  # ZMIANA: domyślnie priority_rank
        sort_order = request.args.get('sort_order', 'asc' if sort_by == 'priority_rank' else 'desc')
        
        # Sortowanie z obsługą parametrów
        sort_column = None
        if sort_by == 'priority_rank' and hasattr(ProductionItem, 'priority_rank'):
            sort_column = ProductionItem.priority_rank
        elif sort_by == 'created_at' and hasattr(ProductionItem, 'created_at'):
            sort_column = ProductionItem.created_at
        elif sort_by == 'deadline_date' and hasattr(ProductionItem, 'deadline_date'):
            sort_column = ProductionItem.deadline_date
            
        if sort_column is not None:
            if sort_order == 'desc':
                products_query = products_query.order_by(sort_column.desc())
            else:
                products_query = products_query.order_by(sort_column.asc())
        else:
            # Fallback - domyślnie priority_rank ASC
            if hasattr(ProductionItem, 'priority_rank'):
                products_query = products_query.order_by(ProductionItem.priority_rank.asc())
            else:
                products_query = products_query.order_by(ProductionItem.id.desc())
        
        # ZMIANA: Pobierz WSZYSTKIE produkty (usuń limit)
        products = products_query.all()

        logger.info(f"Pobranych produktów: {len(products)} (bez limitu, view={view_mode})")

        # Pre-agregacja po zamówieniu: MAX(packaging_completed_at) i MIN(created_at)
        # potrzebne do pola order_completed_at oraz do statystyk archiwum.
        order_aggregates = {}
        for p in products:
            ion = p.order.internal_order_number if p.order else None
            if not ion:
                continue
            agg = order_aggregates.setdefault(ion, {'completed_at': None, 'created_at': None})
            pkg = getattr(p, 'packaging_completed_at', None)
            if pkg is not None and (agg['completed_at'] is None or pkg > agg['completed_at']):
                agg['completed_at'] = pkg
            crt = getattr(p, 'created_at', None)
            if crt is not None and (agg['created_at'] is None or crt < agg['created_at']):
                agg['created_at'] = crt

        workers_by_product = _workers_for_products([p.id for p in products])
        product_counts = _product_counts_by_order([p.order_id for p in products])

        html_content = render_template('components/products-tab-content.html')

        # Przygotuj dane produktów z bezpiecznym dostępem do atrybutów
        products_data = []
        for product in products:
            product_dict = _serialize_product(product, workers_by_product, product_counts)

            # Data zakończenia zamówienia (MAX packaging_completed_at po wszystkich pozycjach
            # tego samego internal_order_number).
            ion = product_dict['internal_order_number']
            agg = order_aggregates.get(ion) if ion else None
            product_dict['order_completed_at'] = (
                agg['completed_at'].isoformat() if agg and agg['completed_at'] else None
            )

            products_data.append(product_dict)
        
        # Statystyki liczone per niespakowana sztuka
        # (remaining = quantity - quantity_done_packaging). Pozycje w pełni spakowane
        # są ignorowane mimo że należą do nieukończonych jeszcze zamówień.
        # Archiwum ma własne statystyki — patrz `_archive_stats`.
        total_volume = 0.0
        total_value = 0.0
        total_quantity = 0
        total_count = 0
        stats_breakdown_source = []
        for p in products_data:
            if p.get('current_status') in sposoby.STATUSY_PO_SPAKOWANIU + ('anulowane',):
                continue
            qty = int(p.get('quantity') or 0)
            done = int(p.get('quantity_done_packaging') or 0)
            remaining = qty - done
            if remaining <= 0:
                continue
            ratio = remaining / qty if qty else 0
            total_volume += float(p.get('volume_m3') or 0) * remaining
            total_value += float(p.get('total_value_net') or 0) * ratio
            total_quantity += remaining
            total_count += 1
            stats_breakdown_source.append(p)

        # Oblicz pilne produkty (deadline <= 3 dni) — tylko z policzonych pozycji
        urgent_count = 0
        for p in stats_breakdown_source:
            if p['days_until_deadline'] is not None and p['days_until_deadline'] <= 3:
                urgent_count += 1

        # Breakdown statusów
        status_breakdown = {}
        for p in stats_breakdown_source:
            status = p['current_status']
            status_breakdown[status] = status_breakdown.get(status, 0) + 1

        stats_data = {
            'total_count': total_count,
            'total_quantity': total_quantity,
            'total_volume': round(total_volume, 4),
            'total_value': round(total_value, 2),
            'urgent_count': urgent_count,
            'status_breakdown': status_breakdown
        }

        # Przygotuj opcje filtrów z produktów
        filters_data = {
            'wood_species': list(set(p['parsed_wood_species'] for p in products_data if p['parsed_wood_species'])),
            'technologies': list(set(p['parsed_technology'] for p in products_data if p['parsed_technology'])),
            'wood_classes': list(set(p['parsed_wood_class'] for p in products_data if p['parsed_wood_class'])),
            'thicknesses': list({label for label in (
                _format_thickness_option(p['parsed_thickness_cm']) for p in products_data
            ) if label}),
            'statuses': list(set(p['current_status'] for p in products_data if p['current_status'])),
            # Źródło filtrujemy po gotowej etykiecie, a nie po surowym kanale:
            # w `personal` istotne jest rozróżnienie Detal / Stały B2B / Dębuś VPS,
            # które w samym kluczu kanału by zniknęło.
            'order_sources': list({
                p['order_source_display'] for p in products_data if p.get('order_source_display')
            }),
        }

        # Sortuj opcje filtrów
        filters_data['wood_species'].sort()
        filters_data['technologies'].sort()
        filters_data['wood_classes'].sort()
        filters_data['thicknesses'].sort(key=lambda x: _parse_thickness_option(x) or 0)
        filters_data['statuses'].sort()
        filters_data['order_sources'].sort()
        
        logger.info(f"Statystyki: {stats_data}")
        logger.info(f"Opcje filtrów: gatunki={len(filters_data['wood_species'])}, technologie={len(filters_data['technologies'])}")
        
        return jsonify({
            'success': True,
            'html': html_content,
            'initial_data': {
                'products': products_data,
                'stats': stats_data,
                'filters': filters_data,
                'total_count': len(products_data),
                'load_all': load_all
            },
            'products_count': len(products),
            'debug_info': {
                'status_filter': status_filter,
                'search_query': search_query,
                'products_returned': len(products_data),
                'load_all': load_all,
                'query_without_limit': True,
                'parsed_fields_included': True,
                'filters_data_included': True
            }
        })
        
    except Exception as e:
        # Szczegółowe logowanie błędu
        error_traceback = traceback.format_exc()
        logger.error(f"Błąd endpoint products-tab-content: {str(e)}")
        logger.error(f"Traceback: {error_traceback}")
        
        return jsonify({
            'success': False,
            'error': str(e),
            'traceback': error_traceback if current_app.debug else None
        }), 500


# Dla paginowanych zapytań

@api_bp.route('/products-paginated', methods=['GET'])
@login_required
def products_paginated():
    """
    Endpoint dla paginowanych produktów - dla bardzo dużych zbiorów danych
    """
    try:
        # Parametry paginacji
        page = int(request.args.get('page', 1))
        per_page = min(int(request.args.get('per_page', 50)), 800)  # Max 800 na stronę
        
        # Filtry
        status_filter = request.args.get('status', 'all')
        search_query = request.args.get('search', '')
        
        # Query builder — join ProductionOrder needed for order-level field searches
        products_query = ProductionItem.query.join(ProductionOrder)

        if status_filter and status_filter != 'all':
            products_query = products_query.filter(ProductionItem.current_status == status_filter)

        if search_query:
            search_pattern = f"%{search_query}%"
            search_conditions = []

            if hasattr(ProductionItem, 'original_product_name'):
                search_conditions.append(ProductionItem.original_product_name.ilike(search_pattern))
            if hasattr(ProductionItem, 'short_product_id'):
                search_conditions.append(ProductionItem.short_product_id.ilike(search_pattern))
            # order-level fields via ProductionOrder (join already present)
            search_conditions.append(ProductionOrder.client_name.ilike(search_pattern))
            search_conditions.append(ProductionOrder.internal_order_number.ilike(search_pattern))
            search_conditions.append(ProductionOrder.client_order_number.ilike(search_pattern))
            search_conditions.append(ProductionOrder.quote_number.ilike(search_pattern))
            search_conditions.append(cast(ProductionOrder.baselinker_order_id, String).ilike(search_pattern))

            if search_conditions:
                products_query = products_query.filter(or_(*search_conditions))

        # Sortowanie
        products_query = products_query.order_by(ProductionItem.priority_rank.asc())
        
        # Paginacja
        paginated = products_query.paginate(
            page=page, 
            per_page=per_page, 
            error_out=False
        )
        
        # Przygotuj dane
        products_data = []
        for product in paginated.items:
            # Używamy tej samej logiki co w głównym endpoint
            product_dict = {
                'id': product.id,
                'short_product_id': getattr(product, 'short_product_id', ''),
                'original_product_name': getattr(product, 'original_product_name', ''),
                'current_status': getattr(product, 'current_status', 'nieznany'),
                'priority_rank': getattr(product, 'priority_rank', None),
                'unique_id': f"{getattr(product, 'short_product_id', '')}-{product.id}"
                # ... reszta pól
            }
            products_data.append(product_dict)
        
        return jsonify({
            'success': True,
            'products': products_data,
            'pagination': {
                'page': page,
                'per_page': per_page,
                'total': paginated.total,
                'pages': paginated.pages,
                'has_next': paginated.has_next,
                'has_prev': paginated.has_prev
            }
        })
        
    except Exception as e:
        logger.error(f"Błąd endpoint products-paginated: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


# ============================================================================
# API ADMIN - Update Quantity Done (Panel admina - bez restrykcji IP)
# ============================================================================


@api_bp.route('/admin/update-quantity-done', methods=['POST'])
@login_required
def admin_update_quantity_done():
    """
    POST /api/admin/update-quantity-done - Zmiana ilości wykonanych sztuk z panelu admina

    Body JSON:
    {
        "product_id": "25_05248_1",
        "station": "cutting",
        "action": "increment" | "decrement" | "increment10" | "decrement10" | "set",
        "value": 5  // tylko dla action="set"
    }

    Akcje:
    - increment: quantity_done += 1 (max = quantity)
    - decrement: quantity_done -= 1 (min = 0)
    - increment10: quantity_done += 10 (max = quantity)
    - decrement10: quantity_done -= 10 (min = 0)
    - set: quantity_done = value (0 <= value <= quantity)

    Autoryzacja: login_required (panel admina)
    Returns: JSON ze zaktualizowanymi wartościami
    """
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'Brak danych JSON'}), 400

        product_id = data.get('product_id')
        station = data.get('station')
        action = data.get('action')
        value = data.get('value')

        # Walidacja wymaganych pól
        if not product_id or not station or not action:
            return jsonify({
                'success': False,
                'error': 'Wymagane pola: product_id, station, action'
            }), 400

        # Walidacja station
        valid_stations = ['cutting', 'assembly', 'gluing', 'formatting', 'edges', 'painting', 'packaging']
        if station not in valid_stations:
            return jsonify({
                'success': False,
                'error': f'Nieprawidłowy station. Dozwolone: {valid_stations}'
            }), 400

        # Walidacja action
        valid_actions = ['increment', 'decrement', 'increment10', 'decrement10', 'set']
        if action not in valid_actions:
            return jsonify({
                'success': False,
                'error': f'Nieprawidłowa akcja. Dozwolone: {valid_actions}'
            }), 400

        logger.info("API Admin: Update quantity done", extra={
            'product_id': product_id,
            'station': station,
            'action': action,
            'value': value,
            'user_id': current_user.id,
            'user_email': current_user.email
        })

        from ...models import ProductionItem

        # Znajdź produkt - preferuj record_id (PK) gdy obecny (disambig dla doróbek)
        record_id = data.get('record_id')
        if record_id is not None:
            product = ProductionItem.query.filter_by(id=int(record_id)).first()
        else:
            # Fallback do short_product_id (legacy)
            product = ProductionItem.query.filter_by(short_product_id=product_id).first()
        if not product:
            return jsonify({
                'success': False,
                'error': f'Produkt {product_id} nie znaleziony'
            }), 404

        # Akcja z panelu admina — autor: zalogowany user
        actor_kwargs = {
            'actor_user_id': current_user.id if current_user.is_authenticated else None,
            'source': 'admin',
        }

        # Wykonaj akcję
        if action == 'increment':
            new_value = product.increment_quantity_done(station, 1, **actor_kwargs)
        elif action == 'decrement':
            new_value = product.decrement_quantity_done(station, 1, **actor_kwargs)
        elif action == 'increment10':
            new_value = product.increment_quantity_done(station, 10, **actor_kwargs)
        elif action == 'decrement10':
            new_value = product.decrement_quantity_done(station, 10, **actor_kwargs)
        elif action == 'set':
            # Ustaw konkretną wartość
            if value is None:
                return jsonify({
                    'success': False,
                    'error': 'Akcja "set" wymaga pola "value"'
                }), 400
            value = int(value)
            if value < 0 or value > product.quantity:
                return jsonify({
                    'success': False,
                    'error': f'Wartość musi być między 0 a {product.quantity}'
                }), 400
            new_value = product.set_quantity_done(station, value, **actor_kwargs)

        db.session.commit()

        is_complete = (new_value == product.quantity)

        # Zbierz wszystkie wartości quantity_done
        all_quantity_done = {
            'quantity_done_cutting': product.quantity_done_cutting or 0,
            'quantity_done_assembly': product.quantity_done_assembly or 0,
            'quantity_done_gluing': product.quantity_done_gluing or 0,
            'quantity_done_formatting': product.quantity_done_formatting or 0,
            'quantity_done_edges': product.quantity_done_edges or 0,
            'quantity_done_painting': product.quantity_done_painting or 0,
            'quantity_done_packaging': product.quantity_done_packaging or 0
        }

        logger.info("API Admin: Quantity done updated", extra={
            'product_id': product_id,
            'station': station,
            'action': action,
            'quantity_done': new_value,
            'quantity': product.quantity,
            'is_complete': is_complete
        })

        return jsonify({
            'success': True,
            'product_id': product_id,
            'station': station,
            'quantity_done': new_value,
            'quantity': product.quantity,
            'is_complete': is_complete,
            'all_quantity_done': all_quantity_done
        }), 200

    except Exception as e:
        db.session.rollback()
        logger.error("API Admin: Błąd update quantity done", extra={
            'product_id': data.get('product_id') if 'data' in locals() else None,
            'station': data.get('station') if 'data' in locals() else None,
            'error': str(e)
        })
        return jsonify({
            'success': False,
            'error': f'Błąd serwera: {str(e)}'
        }), 500


# ============================================================================
# API ADMIN - Baselinker Order Comparison & Update
# ============================================================================


@api_bp.route('/admin/compare-baselinker-order', methods=['POST'])
@login_required
def admin_compare_baselinker_order():
    """
    POST /api/admin/compare-baselinker-order - Porównuje zamówienie z danymi z Baselinker

    Body JSON:
    {
        "baselinker_order_id": 25208907
    }

    Returns: JSON ze strukturą zmian do przeglądu
    """
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'Brak danych JSON'}), 400

        baselinker_order_id = data.get('baselinker_order_id')
        if not baselinker_order_id:
            return jsonify({
                'success': False,
                'error': 'Wymagane pole: baselinker_order_id'
            }), 400

        # Konwertuj na int
        try:
            baselinker_order_id = int(baselinker_order_id)
        except (ValueError, TypeError):
            return jsonify({
                'success': False,
                'error': 'baselinker_order_id musi być liczbą'
            }), 400

        logger.info("API Admin: Porównanie z Baselinker", extra={
            'baselinker_order_id': baselinker_order_id,
            'user_id': current_user.id
        })

        from ...services.sync_service import BaselinkerSyncService

        sync_service = BaselinkerSyncService()
        result = sync_service.compare_order_with_baselinker(baselinker_order_id)

        return jsonify(result), 200

    except Exception as e:
        logger.error("API Admin: Błąd porównania z Baselinker", extra={
            'baselinker_order_id': data.get('baselinker_order_id') if 'data' in locals() else None,
            'error': str(e)
        })
        return jsonify({
            'success': False,
            'error': f'Błąd serwera: {str(e)}'
        }), 500



@api_bp.route('/admin/apply-baselinker-changes', methods=['POST'])
@login_required
def admin_apply_baselinker_changes():
    """
    POST /api/admin/apply-baselinker-changes - Aplikuje zmiany z Baselinker do bazy

    Body JSON:
    {
        "baselinker_order_id": 25208907,
        "changes": {
            "products_to_add": [...],
            "products_to_remove": [...],
            "products_to_update": [...],
            "order_level": [...]
        }
    }

    Returns: JSON z wynikiem operacji
    """
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'Brak danych JSON'}), 400

        baselinker_order_id = data.get('baselinker_order_id')
        changes = data.get('changes')

        if not baselinker_order_id or not changes:
            return jsonify({
                'success': False,
                'error': 'Wymagane pola: baselinker_order_id, changes'
            }), 400

        # Konwertuj na int
        try:
            baselinker_order_id = int(baselinker_order_id)
        except (ValueError, TypeError):
            return jsonify({
                'success': False,
                'error': 'baselinker_order_id musi być liczbą'
            }), 400

        logger.info("API Admin: Aplikowanie zmian z Baselinker", extra={
            'baselinker_order_id': baselinker_order_id,
            'user_id': current_user.id,
            'changes_summary': {
                'to_add': len(changes.get('products_to_add', [])),
                'to_remove': len(changes.get('products_to_remove', [])),
                'to_update': len(changes.get('products_to_update', []))
            }
        })

        from ...services.sync_service import BaselinkerSyncService

        sync_service = BaselinkerSyncService()
        # Użytkownik PRZED serwisem: serwis commituje po wywołaniu Base., a po commicie current_user.id byłby zwykłym
        # SELECT-em w nowej transakcji (migawka przed blokadami). Trafia do logów logistyki (Ruling 31).
        user_id = current_user.id
        result = sync_service.apply_baselinker_changes(baselinker_order_id, changes, user_id=user_id)
        if result.get('success'):
            # Logistyka (Ruling 30): zamówienie zdjęte z trasy w drodze czeka na „Planowana trasa” w Base. — dopychacz
            # rusza dopiero po commicie zapisu (apply_baselinker_changes commituje sam).
            from modules.production.logistics.services import bl_sync
            bl_sync.wyslij_zaplanowane()
            # Priorytety produkcji (spec 2026-10-04, 9.3): zmiany z Base. dodają i usuwają pozycje — rangi przeliczamy
            # po commicie serwisu (własna sesja kolejka.utrwal; błąd przeliczenia trafia tylko do logu).
            from modules.production.priorytety.services import kolejka
            kolejka.utrwal_po_commicie()
            # Sygnały dla tabletów (spec 5.4), po commicie serwisu: stanowiska, z których zdjęto kafel, oraz
            # Wycinanie, gdy doszła nowa pozycja (zaczyna od `czeka_na_wyciecie`).
            from modules.production.priorytety.services import sygnaly
            sygnaly.wyslij(*(list(result.get('zdjete_stanowiska') or [])
                             + (['cutting'] if result.get('added') else [])))

        return jsonify(result), 200

    except Exception as e:
        db.session.rollback()
        logger.error("API Admin: Błąd aplikowania zmian z Baselinker", extra={
            'baselinker_order_id': data.get('baselinker_order_id') if 'data' in locals() else None,
            'error': str(e)
        })
        return jsonify({
            'success': False,
            'error': f'Błąd serwera: {str(e)}'
        }), 500



def _zapisz_zmiane_statusu(product_ids, nowy_status, user_id):
    """
    Hurtowa zmiana statusu w jednej transakcji panelu: `zmiana_statusu.zmien_status` (blokady, pętla statusów, reguła
    unieważniania etapów) i commit po sukcesie. Serwis sam niczego nie commituje ani nie cofa (woła go też tablet
    kierownika), więc zamknięcie transakcji jest tutaj: przy odmowie dla wszystkich zaznaczonych pozycji
    (`success: False`) nic się nie zapisuje — rollback, a `bulk_action` odpowiada 409. Zwraca słownik serwisu albo
    None, gdy po blokadzie nie ma żadnej z zaznaczonych pozycji (404). Ponowienie po zakleszczeniu 1213 jest w
    `bulk_action` i woła tę funkcję od nowa (wynik liczy się od zera).
    """
    results = zmiana_statusu.zmien_status(product_ids, nowy_status, user_id=user_id)
    if results is None:
        return None
    if results['success']:
        db.session.commit()
    else:
        db.session.rollback()
    return results


@api_bp.route('/products/bulk-action', methods=['POST'])
@login_required
def bulk_action():
    """
    POST /production/api/products/bulk-action
    
    Wykonuje masowe operacje na produktach
    
    Body (JSON):
    {
        "action": "update_status|export|delete",
        "product_ids": [1, 2, 3, ...],
        "parameters": {
            "new_status": "czeka_na_wyciecie",
            "export_format": "excel"
        }
    }
    
    Returns: JSON z rezultatem operacji
    """
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'Brak danych JSON'}), 400
        
        action = data.get('action')
        product_ids = data.get('product_ids', [])
        parameters = data.get('parameters', {})
        
        # Walidacja
        if not action or not product_ids:
            return jsonify({'success': False, 'error': 'Wymagane: action i product_ids'}), 400
        
        # Hurtowej zmiany rangi (`update_priority`) nie ma od kroku K2 priorytetów: rangę liczy kolejka.utrwal.
        valid_actions = ['update_status', 'export', 'delete']
        if action not in valid_actions:
            return jsonify({'success': False, 'error': f'Nieprawidłowa akcja. Dostępne: {valid_actions}'}), 400
        
        from ...models import ProductionItem
        
        # Walidacja statusu PRZED pętlą po produktach. Dotąd surowy string
        # z requestu szedł prosto do product.current_status, a commit stoi
        # POZA pętlą try (niżej, przy `if action in [...]`). Enum SQLAlchemy
        # nie sprawdza wartości przy zapisie po stronie Pythona, więc taki
        # string dociera do bazy i na MySQL-u wywraca CAŁY batch błędem 1265
        # (Data truncated). Po zwężeniu enuma (czeka_na_wykanczanie ->
        # czeka_na_krawedzie) zapisany link albo nieodświeżony dropdown
        # trafia w to bardzo łatwo.
        if action == 'update_status':
            nowy_status = parameters.get('new_status')
            # 'czeka_na_logistyke' zostaje w ENUM do sprzątania, ale nie jest już
            # etapem pipeline'u — logistyka żyje równolegle na zamówieniu.
            # Statusy po spakowaniu nadaje tylko logistyka (spec 8.6) — ręcznie ich nie ustawiamy.
            if nowy_status not in zmiana_statusu.DOZWOLONE_STATUSY:
                return jsonify({
                    'success': False,
                    'error': 'Nieprawidłowy status "{}". Dozwolone: {}'.format(
                        nowy_status, sorted(zmiana_statusu.DOZWOLONE_STATUSY))
                }), 400

        # PRZED pierwszą próbą zapisu i przed jakimkolwiek commitem albo rollbackiem: po nich `current_user.id`
        # byłby zwykłym SELECT-em (obiekty sesji wygasają), czyli odczytem spoza blokad.
        user_id = current_user.id

        if action == 'update_status':
            # Zmiana statusu może zmienić zamówienie (reguła uniewaznij_etapy), więc zapis blokuje najpierw
            # zamówienia, potem pozycje, obie listy bieżącym odczytem (patrz zmiana_statusu.zablokuj_zamowienia_i_pozycje), a przed
            # nimi — globalną blokadę tras (decyzja Konrada 2.10, A2: odmowa dla zamówień z trasy w drodze).
            # Jedno automatyczne ponowienie po zakleszczeniu MySQL 1213, tym samym wzorem co zmiana sposobu
            # dostawy w panelu Logistyki: ścieżki spoza zasady „zamówienie najpierw” (ręczna synchronizacja
            # z force_update dopisuje pozycje bez blokady zamówienia) mogą rzadko zakleszczyć hurt. Żądanie jest
            # bezpieczne do powtórzenia: nowy status jest jawny w ciele, a druga próba blokuje zamówienia od
            # nowa i decyduje na stanie spod nowych blokad. Wynik liczy się od zera w każdej próbie. Drugie
            # 1213 i każdy inny błąd idą dalej do `except Exception` niżej (rollback i 500).
            try:
                results = _zapisz_zmiane_statusu(product_ids, nowy_status, user_id)
            except OperationalError as e:
                if blokady_zamowien.kod_mysql(e) != 1213:
                    raise
                db.session.rollback()
                logger.warning("Hurtowa zmiana statusu: zakleszczenie 1213, ponawiam raz", extra={
                    'user_id': user_id, 'product_count': len(product_ids)})
                results = _zapisz_zmiane_statusu(product_ids, nowy_status, user_id)
            if results is None:
                return jsonify({'success': False, 'error': 'Nie znaleziono produktów'}), 404
            # Klucze serwisu dla tabletu kierownika (`pozycje` to obiekty ORM, nie serializują się): odpowiedź
            # panelu zostaje taka, jak była. `zdjete_stanowiska` panel dostaje tylko przy sukcesie.
            for klucz in ('pozycje', 'nieznane', 'nowe_stanowisko'):
                results.pop(klucz, None)
            if not results['success']:
                results.pop('zdjete_stanowiska', None)
                # Decyzja Konrada 2.10 (A2): wszystkie zaznaczone pozycje są w zamówieniach z trasy załadowanej albo
                # w drodze — odmowa bez zapisów, z komunikatem w `error` (panel pokazuje go w oknie błędu).
                return jsonify(results), 409
        else:
            products = ProductionItem.query.filter(ProductionItem.id.in_(product_ids)).all()

            if not products:
                return jsonify({'success': False, 'error': 'Nie znaleziono produktów'}), 404

            results = {
                'success': True,
                'action': action,
                'processed_count': 0,
                'failed_count': 0,
                'errors': []
            }

            # Wykonaj akcję na każdym produkcie
            for product in products:
                try:
                    if action == 'delete':
                        # Tylko admin może usuwać
                        if not (hasattr(current_user, 'role') and current_user.role.lower() in ['admin', 'administrator']):
                            results['errors'].append(f'Brak uprawnień do usunięcia produktu {product.id}')
                            results['failed_count'] += 1
                            continue

                        db.session.delete(product)
                        results['processed_count'] += 1

                    elif action == 'export':
                        # Export będzie obsłużony w osobnym endpoincie
                        results['processed_count'] += 1

                except Exception as e:
                    logger.error(f"Błąd bulk action dla produktu {product.id}", extra={'error': str(e)})
                    results['errors'].append(f'Błąd produktu {product.id}: {str(e)}')
                    results['failed_count'] += 1

            # Zapisz zmiany dla akcji modyfikujących (update_status commituje w _zapisz_zmiane_statusu)
            if action == 'delete':
                db.session.commit()

        logger.info("Bulk action wykonana", extra={
            'user_id': user_id,
            'action': action,
            'product_count': len(product_ids),
            'processed': results['processed_count'],
            'failed': results['failed_count']
        })
        
        if action == 'update_status' and results.get('success'):
            # Priorytety produkcji (spec 2026-10-04, 9.3): hurtowa zmiana statusu zabiera zamówienia z kolejki
            # (wstrzymanie, anulowanie) albo je do niej przywraca — rangi przeliczamy po commicie zapisu
            # (_zapisz_zmiane_statusu commituje sam). Hurtowa zmiana priorytetu i usuwanie nie przeliczają.
            from modules.production.priorytety.services import kolejka
            kolejka.utrwal_po_commicie()
            # Sygnały dla tabletów (spec 5.4), po commicie zapisu: stanowiska, z których zdjęto kafel, i stanowisko,
            # na które pozycje trafiły nowym statusem (doszła mu praca).
            from modules.production.priorytety.services import stol, sygnaly
            sygnaly.wyslij(*(list(results.get('zdjete_stanowiska') or [])
                             + [stol.STANOWISKO_STATUSU.get(nowy_status)]))

        return jsonify(results)
        
    except Exception as e:
        db.session.rollback()
        logger.error("Błąd bulk action", extra={
            'user_id': current_user.id if current_user.is_authenticated else None,
            'error': str(e)
        })
        return jsonify({
            'success': False,
            'error': f'Błąd serwera: {str(e)}'
        }), 500


# 3. EXPORT PRODUKTÓW ENDPOINT

@api_bp.route('/products/export', methods=['POST'])
@login_required
def export_products():
    """
    POST /production/api/products/export

    Generuje export produktów w różnych formatach (Excel, CSV, PDF)

    Body (JSON):
    {
        "format": "excel|csv|pdf",
        "product_ids": [1, 2, 3] | "all" | "filtered",
        "filters": {...},
        "report_type": "full|summary"  // dla PDF
    }

    Returns: Plik do pobrania
    """
    try:
        import io
        import csv
        from datetime import datetime
        from flask import send_file, make_response

        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'Brak danych JSON'}), 400

        export_format = data.get('format', 'excel').lower()
        product_selection = data.get('product_ids', 'all')
        filters = data.get('filters', {})
        report_type = data.get('report_type', 'full')

        # Walidacja formatu
        valid_formats = ['excel', 'csv', 'pdf']
        if export_format not in valid_formats:
            return jsonify({'success': False, 'error': f'Nieprawidłowy format. Dostępne: {valid_formats}'}), 400

        from ...models import ProductionItem

        # Buduj query na podstawie selekcji
        query = ProductionItem.query

        if isinstance(product_selection, list):
            query = query.filter(ProductionItem.id.in_(product_selection))
        elif product_selection == "filtered":
            if filters.get('status'):
                query = query.filter(ProductionItem.current_status == filters['status'])
            if filters.get('search'):
                search_term = f"%{filters['search']}%"
                query = query.filter(
                    db.or_(
                        ProductionItem.short_product_id.ilike(search_term),
                        ProductionItem.original_product_name.ilike(search_term)
                    )
                )

        # Sortuj po priorytecie (MariaDB nie obsługuje NULLS LAST)
        # NULL-e na końcu: COALESCE(priority_rank, 999999)
        query = query.order_by(
            func.coalesce(ProductionItem.priority_rank, 999999).asc(),
            ProductionItem.created_at.desc()
        )
        products = query.all()

        if not products:
            return jsonify({'success': False, 'error': 'Brak produktów do eksportu'}), 404

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

        # =====================================================================
        # EXPORT CSV
        # =====================================================================
        if export_format == 'csv':
            return _export_csv(products, timestamp)

        # =====================================================================
        # EXPORT EXCEL (z openpyxl)
        # =====================================================================
        elif export_format == 'excel':
            return _export_excel(products, timestamp)

        # =====================================================================
        # EXPORT PDF (z reportlab)
        # =====================================================================
        elif export_format == 'pdf':
            return _export_pdf(products, timestamp, report_type)

    except Exception as e:
        logger.error("Błąd eksportu produktów", extra={
            'user_id': current_user.id if current_user.is_authenticated else None,
            'error': str(e),
            'traceback': traceback.format_exc()
        })
        return jsonify({
            'success': False,
            'error': f'Błąd eksportu: {str(e)}'
        }), 500



def _export_csv(products, timestamp):
    """Eksport do CSV"""
    import io
    import csv
    from flask import make_response

    output = io.StringIO()

    fieldnames = ['ID', 'Zamówienie', 'Nr klienta', 'Nazwa', 'Status', 'Priorytet',
                  'Ilość', 'Gatunek', 'Technologia', 'Klasa', 'Wymiary',
                  'Objętość m³', 'Klient', 'Data utworzenia']

    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()

    for p in products:
        writer.writerow({
            'ID': p.short_product_id,
            'Zamówienie': p.order.internal_order_number if p.order else None,
            'Nr klienta': (p.order.client_order_number if p.order else None) or '',
            'Nazwa': p.original_product_name,
            'Status': _format_status(p.current_status),
            'Priorytet': p.priority_rank or '-',
            'Ilość': p.quantity,
            'Gatunek': (p.configuration.species if p.configuration else None) or '',
            'Technologia': (p.configuration.technology if p.configuration else None) or '',
            'Klasa': (p.configuration.wood_class if p.configuration else None) or '',
            'Wymiary': f"{p.parsed_length_cm or 0}×{p.parsed_width_cm or 0}×{p.parsed_thickness_cm or 0}",
            'Objętość m³': float(p.volume_m3) if p.volume_m3 else 0,
            'Klient': (p.order.client_name if p.order else None) or '',
            'Data utworzenia': p.created_at.strftime('%Y-%m-%d %H:%M') if p.created_at else ''
        })

    response = make_response(output.getvalue())
    response.headers['Content-Type'] = 'text/csv; charset=utf-8'
    response.headers['Content-Disposition'] = f'attachment; filename=raport_produkcji_{timestamp}.csv'

    logger.info("Export CSV wygenerowany", extra={
        'user_id': current_user.id,
        'products_count': len(products)
    })

    return response



def _export_excel(products, timestamp):
    """Eksport do Excel z pełnymi danymi analitycznymi w wielu arkuszach"""
    import io
    from collections import defaultdict

    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
        from openpyxl.utils import get_column_letter
        from openpyxl.chart import PieChart, BarChart, Reference
        from openpyxl.chart.label import DataLabelList
    except ImportError:
        logger.warning("openpyxl niedostępne, używam CSV jako fallback")
        return _export_csv(products, timestamp)

    wb = Workbook()

    # =========================================================================
    # STYLE WSPÓLNE
    # =========================================================================
    header_font = Font(bold=True, color="FFFFFF", size=11)
    header_fill = PatternFill(start_color="2E7D32", end_color="2E7D32", fill_type="solid")
    header_fill_blue = PatternFill(start_color="1565C0", end_color="1565C0", fill_type="solid")
    header_alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    cell_alignment = Alignment(horizontal="left", vertical="center")
    number_alignment = Alignment(horizontal="right", vertical="center")
    thin_border = Border(
        left=Side(style='thin', color='CCCCCC'),
        right=Side(style='thin', color='CCCCCC'),
        top=Side(style='thin', color='CCCCCC'),
        bottom=Side(style='thin', color='CCCCCC')
    )

    status_colors = {
        'czeka_na_wyciecie': 'FFF3E0',
        'czeka_na_skladanie': 'E3F2FD',
        'czeka_na_sklejanie': 'F3E5F5',
        'czeka_na_formatowanie': 'E8F5E9',
        'czeka_na_krawedzie': 'FFF8E1',
        'czeka_na_lakiernie': 'FCE4EC',
        'czeka_na_pakowanie': 'E0F7FA',
        'spakowane': 'C8E6C9',
        'zweryfikowane': 'A5D6A7',
        'zaladowane': 'B3E5FC',
        'dostarczone': 'D7CCC8',
        'anulowane': 'FFCDD2',
        'wstrzymane': 'CFD8DC'
    }

    # =========================================================================
    # PRZYGOTOWANIE DANYCH ANALITYCZNYCH
    # =========================================================================
    total_volume = sum(float(p.volume_m3 or 0) * (p.quantity or 1) for p in products)
    total_qty = sum(p.quantity for p in products)

    # Agregacje
    status_stats = defaultdict(lambda: {'count': 0, 'qty': 0, 'volume': 0.0})
    species_stats = defaultdict(lambda: {'count': 0, 'qty': 0, 'volume': 0.0})
    technology_stats = defaultdict(lambda: {'count': 0, 'qty': 0, 'volume': 0.0})
    wood_class_stats = defaultdict(lambda: {'count': 0, 'qty': 0, 'volume': 0.0})
    thickness_stats = defaultdict(lambda: {'count': 0, 'qty': 0, 'volume': 0.0})

    for p in products:
        vol = float(p.volume_m3 or 0)
        qty = p.quantity or 1

        status_stats[p.current_status]['count'] += 1
        status_stats[p.current_status]['qty'] += qty
        status_stats[p.current_status]['volume'] += vol * qty

        species = (p.configuration.species if p.configuration else None) or 'Nieokreślony'
        species_stats[species]['count'] += 1
        species_stats[species]['qty'] += qty
        species_stats[species]['volume'] += vol * qty

        tech = (p.configuration.technology if p.configuration else None) or 'Nieokreślona'
        technology_stats[tech]['count'] += 1
        technology_stats[tech]['qty'] += qty
        technology_stats[tech]['volume'] += vol * qty

        wood_class = (p.configuration.wood_class if p.configuration else None) or 'Nieokreślona'
        wood_class_stats[wood_class]['count'] += 1
        wood_class_stats[wood_class]['qty'] += qty
        wood_class_stats[wood_class]['volume'] += vol * qty

        thickness = f"{float(p.parsed_thickness_cm):.1f} cm" if p.parsed_thickness_cm else 'Nieokreślona'
        thickness_stats[thickness]['count'] += 1
        thickness_stats[thickness]['qty'] += qty
        thickness_stats[thickness]['volume'] += vol * qty

    # =========================================================================
    # ARKUSZ 1: PODSUMOWANIE
    # =========================================================================
    ws_summary = wb.active
    ws_summary.title = "Podsumowanie"

    # Tytuł
    ws_summary.merge_cells('A1:F1')
    ws_summary['A1'] = f"RAPORT PRODUKCJI - {datetime.now().strftime('%d.%m.%Y %H:%M')}"
    ws_summary['A1'].font = Font(bold=True, size=18, color="2E7D32")
    ws_summary['A1'].alignment = Alignment(horizontal="center")
    ws_summary.row_dimensions[1].height = 40

    # Główne podsumowanie
    ws_summary['A3'] = "PODSUMOWANIE OGÓLNE"
    ws_summary['A3'].font = Font(bold=True, size=14, color="1565C0")

    summary_data = [
        ['Parametr', 'Wartość'],
        ['Liczba pozycji', len(products)],
        ['Łączna ilość sztuk', total_qty],
        ['Łączna objętość (m³)', round(total_volume, 3)],
    ]

    for row_idx, row_data in enumerate(summary_data, 5):
        for col_idx, value in enumerate(row_data, 1):
            cell = ws_summary.cell(row=row_idx, column=col_idx, value=value)
            cell.border = thin_border
            if row_idx == 5:
                cell.font = header_font
                cell.fill = header_fill
            cell.alignment = number_alignment if col_idx == 2 and row_idx > 5 else cell_alignment

    # Rozkład statusów
    ws_summary['A11'] = "ROZKŁAD WEDŁUG STATUSÓW"
    ws_summary['A11'].font = Font(bold=True, size=14, color="1565C0")

    status_headers = ['Status', 'Pozycje', 'Sztuki', 'Objętość (m³)', '% pozycji']
    for col_idx, header in enumerate(status_headers, 1):
        cell = ws_summary.cell(row=13, column=col_idx, value=header)
        cell.font = header_font
        cell.fill = header_fill_blue
        cell.border = thin_border
        cell.alignment = header_alignment

    row_idx = 14
    for status, data in sorted(status_stats.items(), key=lambda x: x[1]['count'], reverse=True):
        pct = (data['count'] / len(products) * 100) if products else 0
        row_data = [_format_status(status), data['count'], data['qty'], round(data['volume'], 3), round(pct, 1)]
        status_color = status_colors.get(status, 'FFFFFF')
        row_fill = PatternFill(start_color=status_color, end_color=status_color, fill_type="solid")

        for col_idx, value in enumerate(row_data, 1):
            cell = ws_summary.cell(row=row_idx, column=col_idx, value=value)
            cell.border = thin_border
            cell.fill = row_fill
            cell.alignment = number_alignment if col_idx > 1 else cell_alignment
        row_idx += 1

    # Szerokości kolumn
    ws_summary.column_dimensions['A'].width = 25
    ws_summary.column_dimensions['B'].width = 12
    ws_summary.column_dimensions['C'].width = 12
    ws_summary.column_dimensions['D'].width = 15
    ws_summary.column_dimensions['E'].width = 12

    # =========================================================================
    # ARKUSZ 2: ANALIZA GATUNKÓW
    # =========================================================================
    ws_species = wb.create_sheet("Gatunki drewna")
    ws_species['A1'] = "ANALIZA WEDŁUG GATUNKÓW DREWNA"
    ws_species['A1'].font = Font(bold=True, size=14, color="2E7D32")

    species_headers = ['Gatunek', 'Pozycje', 'Sztuki', 'Objętość (m³)', '% objętości']
    for col_idx, header in enumerate(species_headers, 1):
        cell = ws_species.cell(row=3, column=col_idx, value=header)
        cell.font = header_font
        cell.fill = header_fill
        cell.border = thin_border

    row_idx = 4
    for species, data in sorted(species_stats.items(), key=lambda x: x[1]['volume'], reverse=True):
        pct = (data['volume'] / total_volume * 100) if total_volume else 0
        row_data = [species, data['count'], data['qty'], round(data['volume'], 3), round(pct, 1)]
        for col_idx, value in enumerate(row_data, 1):
            cell = ws_species.cell(row=row_idx, column=col_idx, value=value)
            cell.border = thin_border
            cell.alignment = number_alignment if col_idx > 1 else cell_alignment
        row_idx += 1

    for col in ['A', 'B', 'C', 'D', 'E']:
        ws_species.column_dimensions[col].width = 18

    # =========================================================================
    # ARKUSZ 3: ANALIZA TECHNOLOGII
    # =========================================================================
    ws_tech = wb.create_sheet("Technologie")
    ws_tech['A1'] = "ANALIZA WEDŁUG TECHNOLOGII"
    ws_tech['A1'].font = Font(bold=True, size=14, color="2E7D32")

    tech_headers = ['Technologia', 'Pozycje', 'Sztuki', 'Objętość (m³)', '% objętości']
    for col_idx, header in enumerate(tech_headers, 1):
        cell = ws_tech.cell(row=3, column=col_idx, value=header)
        cell.font = header_font
        cell.fill = header_fill
        cell.border = thin_border

    row_idx = 4
    for tech, data in sorted(technology_stats.items(), key=lambda x: x[1]['volume'], reverse=True):
        pct = (data['volume'] / total_volume * 100) if total_volume else 0
        row_data = [tech, data['count'], data['qty'], round(data['volume'], 3), round(pct, 1)]
        for col_idx, value in enumerate(row_data, 1):
            cell = ws_tech.cell(row=row_idx, column=col_idx, value=value)
            cell.border = thin_border
            cell.alignment = number_alignment if col_idx > 1 else cell_alignment
        row_idx += 1

    for col in ['A', 'B', 'C', 'D', 'E']:
        ws_tech.column_dimensions[col].width = 18

    # =========================================================================
    # ARKUSZ 4: ANALIZA KLAS DREWNA
    # =========================================================================
    ws_class = wb.create_sheet("Klasy drewna")
    ws_class['A1'] = "ANALIZA WEDŁUG KLAS DREWNA"
    ws_class['A1'].font = Font(bold=True, size=14, color="2E7D32")

    class_headers = ['Klasa', 'Pozycje', 'Sztuki', 'Objętość (m³)', '% objętości']
    for col_idx, header in enumerate(class_headers, 1):
        cell = ws_class.cell(row=3, column=col_idx, value=header)
        cell.font = header_font
        cell.fill = header_fill
        cell.border = thin_border

    row_idx = 4
    for wood_class, data in sorted(wood_class_stats.items(), key=lambda x: x[1]['volume'], reverse=True):
        pct = (data['volume'] / total_volume * 100) if total_volume else 0
        row_data = [wood_class, data['count'], data['qty'], round(data['volume'], 3), round(pct, 1)]
        for col_idx, value in enumerate(row_data, 1):
            cell = ws_class.cell(row=row_idx, column=col_idx, value=value)
            cell.border = thin_border
            cell.alignment = number_alignment if col_idx > 1 else cell_alignment
        row_idx += 1

    for col in ['A', 'B', 'C', 'D', 'E']:
        ws_class.column_dimensions[col].width = 18

    # =========================================================================
    # ARKUSZ 5: ANALIZA GRUBOŚCI
    # =========================================================================
    ws_thick = wb.create_sheet("Grubości")
    ws_thick['A1'] = "ANALIZA WEDŁUG GRUBOŚCI"
    ws_thick['A1'].font = Font(bold=True, size=14, color="2E7D32")

    thick_headers = ['Grubość', 'Pozycje', 'Sztuki', 'Objętość (m³)', '% objętości']
    for col_idx, header in enumerate(thick_headers, 1):
        cell = ws_thick.cell(row=3, column=col_idx, value=header)
        cell.font = header_font
        cell.fill = header_fill
        cell.border = thin_border

    row_idx = 4
    # Sortuj po grubości numerycznie
    sorted_thickness = sorted(thickness_stats.items(),
                              key=lambda x: float(x[0].replace(' cm', '').replace('Nieokreślona', '0')))
    for thickness, data in sorted_thickness:
        pct = (data['volume'] / total_volume * 100) if total_volume else 0
        row_data = [thickness, data['count'], data['qty'], round(data['volume'], 3), round(pct, 1)]
        for col_idx, value in enumerate(row_data, 1):
            cell = ws_thick.cell(row=row_idx, column=col_idx, value=value)
            cell.border = thin_border
            cell.alignment = number_alignment if col_idx > 1 else cell_alignment
        row_idx += 1

    for col in ['A', 'B', 'C', 'D', 'E']:
        ws_thick.column_dimensions[col].width = 18

    # =========================================================================
    # ARKUSZ 6: LISTA PRODUKTÓW (szczegółowa)
    # =========================================================================
    ws_products = wb.create_sheet("Lista produktów")

    ws_products.merge_cells('A1:P1')
    ws_products['A1'] = f"SZCZEGÓŁOWA LISTA PRODUKTÓW - {len(products)} pozycji"
    ws_products['A1'].font = Font(bold=True, size=14, color="2E7D32")
    ws_products['A1'].alignment = Alignment(horizontal="center")

    # „Źródło" na końcu, a nie przy „Kliencie": numery kolumn wyrównywanych do
    # prawej są niżej wypisane wprost, więc wstawienie w środku przesunęłoby je
    # wszystkie.
    headers = ['Lp.', 'ID Produktu', 'Zamówienie', 'Nr Baselinker', 'Nr klienta',
               'Nazwa produktu', 'Status', 'Priorytet', 'Ilość', 'Gatunek',
               'Technologia', 'Klasa', 'Wymiary (cm)', 'Objętość (m³)', 'Klient',
               'Źródło']

    for col, header in enumerate(headers, 1):
        cell = ws_products.cell(row=3, column=col, value=header)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = header_alignment
        cell.border = thin_border

    for idx, product in enumerate(products, 1):
        row = 3 + idx
        status_color = status_colors.get(product.current_status, 'FFFFFF')
        row_fill = PatternFill(start_color=status_color, end_color=status_color, fill_type="solid")

        data = [
            idx,
            product.short_product_id,
            product.order.internal_order_number if product.order else None,
            (product.order.baselinker_order_id if product.order else None) or '',
            (product.order.client_order_number if product.order else None) or '',
            (product.original_product_name[:50] + '...') if len(product.original_product_name or '') > 50 else (product.original_product_name or ''),
            _format_status(product.current_status),
            product.priority_rank or '-',
            product.quantity,
            (product.configuration.species if product.configuration else None) or '',
            (product.configuration.technology if product.configuration else None) or '',
            (product.configuration.wood_class if product.configuration else None) or '',
            f"{product.parsed_length_cm or 0}×{product.parsed_width_cm or 0}×{product.parsed_thickness_cm or 0}",
            float(product.volume_m3) if product.volume_m3 else 0,
            (product.order.client_name if product.order else None) or '',
            (product.order.order_source_display if product.order else None) or ''
        ]

        for col, value in enumerate(data, 1):
            cell = ws_products.cell(row=row, column=col, value=value)
            cell.border = thin_border
            cell.fill = row_fill
            # Kolumny wyrównane do prawej: Lp.(1), Nr Baselinker(4), Priorytet(8), Ilość(9), Objętość(14)
            if col in [1, 4, 8, 9, 14]:
                cell.alignment = number_alignment
                if col == 14:
                    cell.number_format = '0.000'
            else:
                cell.alignment = cell_alignment

    column_widths = [5, 14, 12, 14, 14, 40, 18, 10, 8, 12, 14, 8, 18, 12, 25, 16]
    for col, width in enumerate(column_widths, 1):
        ws_products.column_dimensions[get_column_letter(col)].width = width

    # =========================================================================
    # ZAPISZ I ZWRÓĆ
    # =========================================================================
    output = io.BytesIO()
    wb.save(output)
    output.seek(0)

    logger.info("Export Excel wygenerowany (pełny raport)", extra={
        'user_id': current_user.id,
        'products_count': len(products),
        'sheets': ['Podsumowanie', 'Gatunki', 'Technologie', 'Klasy', 'Grubości', 'Lista produktów']
    })

    from flask import Response
    response = Response(
        output.getvalue(),
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response.headers['Content-Disposition'] = f'attachment; filename=raport_produkcji_{timestamp}.xlsx'
    return response



def _export_pdf(products, timestamp, report_type='full'):
    """Eksport do PDF — czytelny raport produkcji"""
    import io
    import os
    from collections import defaultdict

    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import cm
        from reportlab.platypus import (SimpleDocTemplate, Table, TableStyle,
                                        Paragraph, Spacer, PageBreak, KeepTogether)
        from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
    except ImportError:
        logger.error("reportlab niedostępne")
        return jsonify({'success': False, 'error': 'Biblioteka PDF niedostępna'}), 501

    # Font z polskimi znakami
    font_name = 'Helvetica'
    for path in ['/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
                 '/usr/share/fonts/dejavu/DejaVuSans.ttf',
                 'C:/Windows/Fonts/arial.ttf']:
        if os.path.exists(path):
            try:
                pdfmetrics.registerFont(TTFont('DejaVuSans', path))
                font_name = 'DejaVuSans'
                break
            except Exception:
                pass

    output = io.BytesIO()
    doc = SimpleDocTemplate(output, pagesize=landscape(A4),
                            rightMargin=1.2*cm, leftMargin=1.2*cm,
                            topMargin=1.2*cm, bottomMargin=1.2*cm)

    # -- Kolory i style --
    C_PRIMARY = colors.HexColor('#1a1a2e')
    C_HEADER = colors.HexColor('#2c5530')
    C_SECTION = colors.HexColor('#334155')
    C_BORDER = colors.HexColor('#e2e5ea')
    C_ALT_ROW = colors.HexColor('#f8f9fa')
    C_MUTED = colors.HexColor('#64748b')

    styles = getSampleStyleSheet()
    s_title = ParagraphStyle('T', parent=styles['Heading1'], fontName=font_name,
                             fontSize=18, textColor=C_PRIMARY, alignment=TA_LEFT, spaceAfter=2)
    s_subtitle = ParagraphStyle('ST', parent=styles['Normal'], fontName=font_name,
                                fontSize=9, textColor=C_MUTED, spaceAfter=14)
    s_section = ParagraphStyle('S', parent=styles['Heading2'], fontName=font_name,
                               fontSize=11, textColor=C_SECTION, spaceBefore=14, spaceAfter=6,
                               borderWidth=0, leading=14)
    s_footer = ParagraphStyle('F', parent=styles['Normal'], fontName=font_name,
                              fontSize=7, textColor=C_MUTED, alignment=TA_RIGHT)

    def _table_style(header_color=C_HEADER):
        return TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), header_color),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTNAME', (0, 0), (-1, -1), font_name),
            ('FONTSIZE', (0, 0), (-1, 0), 8),
            ('FONTSIZE', (0, 1), (-1, -1), 8),
            ('ALIGN', (1, 0), (-1, -1), 'RIGHT'),
            ('ALIGN', (0, 0), (0, -1), 'LEFT'),
            ('LINEBELOW', (0, 0), (-1, 0), 1, header_color),
            ('LINEBELOW', (0, 1), (-1, -2), 0.3, C_BORDER),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, C_ALT_ROW]),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ('LEFTPADDING', (0, 0), (-1, -1), 6),
            ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ])

    # -- Dane analityczne --
    total_volume = sum(float(p.volume_m3 or 0) * (p.quantity or 1) for p in products)
    total_qty = sum(p.quantity or 1 for p in products)
    total_value = sum(float(p.total_value_net or 0) for p in products)

    buckets = {
        'status': defaultdict(lambda: {'count': 0, 'qty': 0, 'volume': 0.0}),
        'species': defaultdict(lambda: {'count': 0, 'qty': 0, 'volume': 0.0}),
        'technology': defaultdict(lambda: {'count': 0, 'qty': 0, 'volume': 0.0}),
        'wood_class': defaultdict(lambda: {'count': 0, 'qty': 0, 'volume': 0.0}),
        'thickness': defaultdict(lambda: {'count': 0, 'qty': 0, 'volume': 0.0}),
    }

    for p in products:
        vol = float(p.volume_m3 or 0)
        qty = p.quantity or 1
        for key, field in [('status', p.current_status),
                           ('species', (p.configuration.species if p.configuration else None) or 'Nieokreslony'),
                           ('technology', (p.configuration.technology if p.configuration else None) or 'Nieokreslona'),
                           ('wood_class', (p.configuration.wood_class if p.configuration else None) or 'Nieokreslona'),
                           ('thickness', f"{float(p.parsed_thickness_cm):.1f} cm" if p.parsed_thickness_cm else 'Nieokreslona')]:
            buckets[key][field]['count'] += 1
            buckets[key][field]['qty'] += qty
            buckets[key][field]['volume'] += vol * qty

    elements = []

    # ===================== STRONA 1: PODSUMOWANIE =====================
    elements.append(Paragraph("Raport produkcji — WoodPower", s_title))
    elements.append(Paragraph(
        f"{datetime.now().strftime('%d.%m.%Y %H:%M')}  |  "
        f"{len(products)} pozycji  |  {total_qty} szt.  |  "
        f"{total_volume:.3f} m\u00b3  |  "
        f"{total_value:,.2f} PLN".replace(',', ' '),
        s_subtitle))

    # -- KPI --
    kpi_data = [
        ['Pozycje', 'Sztuki', 'Objetosc m\u00b3', 'Wartosc netto'],
        [str(len(products)), str(total_qty), f"{total_volume:.3f}", f"{total_value:,.2f} PLN".replace(',', ' ')]
    ]
    kpi = Table(kpi_data, colWidths=[6*cm, 5*cm, 5*cm, 6.5*cm])
    kpi.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), C_HEADER),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, -1), font_name),
        ('FONTSIZE', (0, 0), (-1, 0), 8),
        ('FONTSIZE', (0, 1), (-1, 1), 14),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('LINEBELOW', (0, 0), (-1, 0), 1, C_HEADER),
    ]))
    elements.append(kpi)
    elements.append(Spacer(1, 0.6*cm))

    # -- Statusy --
    elements.append(Paragraph("Rozklad wedlug stanowisk", s_section))
    rows = [['Stanowisko', 'Pozycje', 'Sztuki', 'Objetosc m\u00b3', '% obj.']]
    for status, d in sorted(buckets['status'].items(), key=lambda x: -x[1]['volume']):
        pct = (d['volume'] / total_volume * 100) if total_volume else 0
        rows.append([_format_status(status), str(d['count']), str(d['qty']),
                     f"{d['volume']:.3f}", f"{pct:.1f}%"])
    t = Table(rows, colWidths=[6.5*cm, 3*cm, 3*cm, 4.5*cm, 3*cm])
    t.setStyle(_table_style())
    elements.append(KeepTogether([t]))
    elements.append(Spacer(1, 0.4*cm))

    # -- Helper dla tabel analitycznych --
    def _analysis_section(title, data_dict, label='Kategoria'):
        s_rows = [[label, 'Poz.', 'Szt.', 'Obj. m\u00b3', '% obj.']]
        for name, d in sorted(data_dict.items(), key=lambda x: -x[1]['volume']):
            pct = (d['volume'] / total_volume * 100) if total_volume else 0
            s_rows.append([name[:25], str(d['count']), str(d['qty']),
                          f"{d['volume']:.3f}", f"{pct:.1f}%"])
        tbl = Table(s_rows, colWidths=[6.5*cm, 2.5*cm, 2.5*cm, 4*cm, 3*cm])
        tbl.setStyle(_table_style(C_SECTION))
        return KeepTogether([Paragraph(title, s_section), tbl, Spacer(1, 0.3*cm)])

    elements.append(_analysis_section("Gatunki drewna", buckets['species'], 'Gatunek'))
    elements.append(_analysis_section("Technologie", buckets['technology'], 'Technologia'))
    elements.append(_analysis_section("Klasy drewna", buckets['wood_class'], 'Klasa'))
    elements.append(_analysis_section("Grubosci", buckets['thickness'], 'Grubosc'))

    # ===================== STRONA 2+: LISTA PRODUKTÓW =====================
    elements.append(PageBreak())
    elements.append(Paragraph("Lista produktow", s_section))

    hdr = ['Lp.', 'ID', 'Zamowienie', 'Nazwa', 'Status', 'Prio.', 'Szt.', 'Gatunek', 'Wymiary', 'Obj. m\u00b3']
    tdata = [hdr]
    for i, p in enumerate(products, 1):
        name = (p.original_product_name or '')[:35]
        if len(p.original_product_name or '') > 35:
            name += '...'
        dims = f"{p.parsed_length_cm or 0}x{p.parsed_width_cm or 0}x{p.parsed_thickness_cm or 0}"
        tdata.append([
            str(i), p.short_product_id or '', (p.order.internal_order_number if p.order else None) or '',
            Paragraph(name, ParagraphStyle('cell', fontName=font_name, fontSize=7, leading=9)),
            _format_status(p.current_status),
            str(p.priority_rank) if p.priority_rank else '-',
            str(p.quantity or 1),
            ((p.configuration.species if p.configuration else None) or '')[:12],
            dims,
            f"{float(p.volume_m3 or 0):.3f}"
        ])

    cw = [0.9*cm, 2.2*cm, 2.2*cm, 5.5*cm, 2.8*cm, 1*cm, 0.9*cm, 2.2*cm, 3.2*cm, 1.8*cm]
    mt = Table(tdata, colWidths=cw, repeatRows=1, splitInRow=1)
    mt.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), C_HEADER),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, -1), font_name),
        ('FONTSIZE', (0, 0), (-1, 0), 7),
        ('FONTSIZE', (0, 1), (-1, -1), 7),
        ('ALIGN', (0, 0), (0, -1), 'CENTER'),
        ('ALIGN', (5, 0), (6, -1), 'CENTER'),
        ('ALIGN', (-1, 0), (-1, -1), 'RIGHT'),
        ('LINEBELOW', (0, 0), (-1, 0), 1, C_HEADER),
        ('LINEBELOW', (0, 1), (-1, -2), 0.3, C_BORDER),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, C_ALT_ROW]),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ('LEFTPADDING', (0, 0), (-1, -1), 4),
        ('RIGHTPADDING', (0, 0), (-1, -1), 4),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
    ]))
    elements.append(mt)

    # Stopka
    elements.append(Spacer(1, 0.8*cm))
    elements.append(Paragraph(
        f"WoodPower CRM | {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}",
        s_footer))

    doc.build(elements)
    output.seek(0)

    from flask import Response
    response = Response(output.getvalue(), mimetype='application/pdf')
    response.headers['Content-Disposition'] = f'attachment; filename=raport_produkcji_{timestamp}.pdf'
    return response



@api_bp.route('/products/<int:product_id>/history', methods=['GET'])
@login_required
def product_history(product_id):
    """
    GET /production/api/products/<id>/history

    Zwraca autorów domknięcia stanowisk (flow) i scaloną oś czasu (history).
    Modal robi jedno żądanie i zasila z niego obie sekcje.
    """
    try:
        from ...services.product_history_service import build_product_history

        if not ProductionItem.query.get(product_id):
            return jsonify({'success': False, 'error': 'Nie znaleziono produktu'}), 404

        return jsonify({'success': True, **build_product_history(product_id)}), 200

    except Exception as e:
        logger.error("API: Błąd pobierania historii produktu", extra={
            'product_id': product_id,
            'error': str(e),
        })
        return jsonify({'success': False, 'error': str(e)}), 500


@api_bp.route('/products/filters-data', methods=['GET'])
@login_required
def get_filters_data():
    """
    GET /production/api/products/filters-data
    
    Zwraca unikalne wartości dla dropdownów filtrów
    
    Returns: JSON z listami unikalnych wartości
    """
    try:
        from ...models import ProductionItem
        from sqlalchemy import func, distinct
        
        # Pobierz unikalne wartości dla filtrów
        
        # Statusy - z enum w modelu
        statuses = [
            {'value': 'czeka_na_wyciecie', 'label': 'Czeka na wycięcie'},
            {'value': 'czeka_na_skladanie', 'label': 'Czeka na składanie'},
            {'value': 'czeka_na_pakowanie', 'label': 'Czeka na pakowanie'},
            {'value': 'spakowane', 'label': 'Spakowane'},
            {'value': 'zweryfikowane', 'label': 'Zweryfikowane'},
            {'value': 'zaladowane', 'label': 'Załadowane'},
            {'value': 'dostarczone', 'label': 'Dostarczone'},
            {'value': 'wstrzymane', 'label': 'Wstrzymane'}
        ]
        
        # Gatunki drewna
        wood_species_query = db.session.query(distinct(ProductionConfiguration.species))\
                                      .filter(ProductionConfiguration.species.isnot(None))\
                                      .filter(ProductionConfiguration.species != 'unknown')\
                                      .all()
        wood_species = [{'value': item[0], 'label': item[0]} for item in wood_species_query]

        # Technologie
        technology_query = db.session.query(distinct(ProductionConfiguration.technology))\
                                    .filter(ProductionConfiguration.technology.isnot(None))\
                                    .filter(ProductionConfiguration.technology != 'unknown')\
                                    .all()
        technologies = [{'value': item[0], 'label': item[0]} for item in technology_query]

        # Klasy drewna
        wood_class_query = db.session.query(distinct(ProductionConfiguration.wood_class))\
                                    .filter(ProductionConfiguration.wood_class.isnot(None))\
                                    .filter(ProductionConfiguration.wood_class != 'unknown')\
                                    .all()
        wood_classes = [{'value': item[0], 'label': item[0]} for item in wood_class_query]
        
        # Zakres priorytetów
        priority_stats = db.session.query(
            func.min(ProductionItem.priority_rank),
            func.max(ProductionItem.priority_rank),
            func.avg(ProductionItem.priority_rank)
        ).filter(ProductionItem.priority_rank.isnot(None)).first()
        
        priority_range = {
            'min': int(priority_stats[0]) if priority_stats[0] else 0,
            'max': int(priority_stats[1]) if priority_stats[1] else 200,
            'avg': int(priority_stats[2]) if priority_stats[2] else 100
        }
        
        # Ostatnie 30 dni dla date picker
        from datetime import datetime, timedelta
        date_suggestions = {
            'today': datetime.now().date().isoformat(),
            'yesterday': (datetime.now() - timedelta(days=1)).date().isoformat(),
            'week_ago': (datetime.now() - timedelta(days=7)).date().isoformat(),
            'month_ago': (datetime.now() - timedelta(days=30)).date().isoformat()
        }
        
        filters_data = {
            'statuses': statuses,
            'wood_species': wood_species,
            'technologies': technologies,
            'wood_classes': wood_classes,
            'priority_range': priority_range,
            'date_suggestions': date_suggestions,
            'total_products': ProductionItem.query.count()
        }
        
        logger.info("Pobrano dane filtrów", extra={
            'user_id': current_user.id,
            'wood_species_count': len(wood_species),
            'technologies_count': len(technologies),
            'total_products': filters_data['total_products']
        })
        
        return jsonify({
            'success': True,
            'filters_data': filters_data
        })
        
    except Exception as e:
        logger.error("Błąd pobierania danych filtrów", extra={
            'user_id': current_user.id if current_user.is_authenticated else None,
            'error': str(e)
        })
        return jsonify({
            'success': False,
            'error': f'Błąd pobierania filtrów: {str(e)}'
        }), 500


def _serialize_production_item(item, today=None):
    """
    Serializuje pojedynczy ProductionItem do słownika używanego przez endpointy listy i szczegółów.

    Współdzielone między /products-filtered (wiele rekordów) i /products/<id>/details (jeden rekord)
    żeby oba endpointy zwracały spójny kształt danych (w szczególności pola stacji gluing/formatting/edges,
    które modal szczegółów sprawdza przez hasOwnProperty).
    """
    if today is None:
        today = date.today()

    days_to_deadline = None
    deadline_date = getattr(item, 'deadline_date', None)
    if deadline_date:
        days_to_deadline = (deadline_date - today).days

    product_data = {
        'id': item.id,
        'short_product_id': getattr(item, 'short_product_id', f'ID-{item.id}'),
        'internal_order_number': (item.order.internal_order_number if item.order else None) or '',
        # Gwiazdki zamówienia (priorytety produkcji, K4a) — te same pola co w `_serialize_product`.
        'order_id': item.order_id,
        'order_priority_stars': int(item.order.priority_stars or 0) if item.order else 0,
        'product_name': getattr(item, 'original_product_name', getattr(item, 'product_name', 'Brak nazwy')),
        'original_product_name': getattr(item, 'original_product_name', getattr(item, 'product_name', 'Brak nazwy')),
        'client_name': (item.order.client_name if item.order else None) or '',
        'current_status': getattr(item, 'current_status', 'unknown'),
        'priority_rank': getattr(item, 'priority_rank', None),
        'volume_m3': float(getattr(item, 'volume_m3', 0) or 0),
        'total_value_net': float(getattr(item, 'total_value_net', getattr(item, 'total_value', 0)) or 0),
        'total_value': float(getattr(item, 'total_value_net', getattr(item, 'total_value', 0)) or 0),
        'order_date': getattr(item, 'order_date', getattr(item, 'created_at', None)),
        'deadline_date': deadline_date.isoformat() if deadline_date else None,
        'days_to_deadline': days_to_deadline,
        'days_until_deadline': days_to_deadline,
        'is_overdue': days_to_deadline < 0 if days_to_deadline is not None else False,
        'baselinker_order_id': item.order.baselinker_order_id if item.order else None,
        'created_at': getattr(item, 'created_at', None),
        'attachment_file_name': item.order.attachment_file_name if item.order else None,
        'attachment_file_url': item.order.attachment_file_url if item.order else None,
        'parsed_wood_species': item.configuration.species if item.configuration else None,
        'parsed_technology': item.configuration.technology if item.configuration else None,
        'parsed_wood_class': item.configuration.wood_class if item.configuration else None,
        'parsed_finish_state': getattr(item, 'parsed_finish_state', None),
        # Po podziale Wykańczania to JEDYNY przełącznik między Krawędziami
        # a Lakiernią (ProductionProduct.should_skip_edges). Bez tego pola
        # modal ZAWSZE policzy „brak krawędzi" i wytnie stanowisko z trasy.
        'parsed_edge_processing': bool(getattr(item, 'parsed_edge_processing', False)),
        'cut_to_size': bool(getattr(item, 'cut_to_size', True)),
        'shape': getattr(item, 'shape', None),
        'parsed_width_cm': getattr(item, 'parsed_width_cm', None),
        'parsed_length_cm': getattr(item, 'parsed_length_cm', None),
        'parsed_thickness_cm': getattr(item, 'parsed_thickness_cm', None),
        'client_email': (item.order.client_email if item.order else None) or '',
        'client_phone': (item.order.client_phone if item.order else None) or '',
        'product_sequence_in_order': getattr(item, 'product_sequence_in_order', None),
        'total_products_in_order': db.session.query(db.func.count(ProductionItem.id)).filter(
            ProductionItem.order_id == item.order_id
        ).scalar() if item.order_id else None,
        # Przepływ produkcji - wszystkie 6 stanowisk
        'cutting_started_at': getattr(item, 'cutting_started_at', None),
        'cutting_completed_at': getattr(item, 'cutting_completed_at', None),
        'cutting_duration_minutes': getattr(item, 'cutting_duration_minutes', None),
        'assembly_started_at': getattr(item, 'assembly_started_at', None),
        'assembly_completed_at': getattr(item, 'assembly_completed_at', None),
        'assembly_duration_minutes': getattr(item, 'assembly_duration_minutes', None),
        'gluing_started_at': getattr(item, 'gluing_started_at', None),
        'gluing_completed_at': getattr(item, 'gluing_completed_at', None),
        'gluing_duration_minutes': getattr(item, 'gluing_duration_minutes', None),
        'formatting_started_at': getattr(item, 'formatting_started_at', None),
        'formatting_completed_at': getattr(item, 'formatting_completed_at', None),
        'formatting_duration_minutes': getattr(item, 'formatting_duration_minutes', None),
        # Krawędzie i Lakiernia: ProductionProduct NIE MA kolumn *_started_at
        # ani *_duration_minutes, więc serializujemy wyłącznie moment domknięcia.
        'edges_completed_at': getattr(item, 'edges_completed_at', None),
        'painting_completed_at': getattr(item, 'painting_completed_at', None),
        'packaging_started_at': getattr(item, 'packaging_started_at', None),
        'packaging_completed_at': getattr(item, 'packaging_completed_at', None),
        'packaging_duration_minutes': getattr(item, 'packaging_duration_minutes', None),
        'logistics_completed_at': item.order.logistics_completed_at.isoformat() if item.order and item.order.logistics_completed_at else None,
        'override_delivery_method': item.order.override_delivery_method if item.order else None,
        'is_personal_pickup': item.order.is_personal_pickup if item.order else False,
        'quantity': getattr(item, 'quantity', 1),
        'quantity_done_cutting': getattr(item, 'quantity_done_cutting', 0),
        'quantity_done_assembly': getattr(item, 'quantity_done_assembly', 0),
        'quantity_done_gluing': getattr(item, 'quantity_done_gluing', 0),
        'quantity_done_formatting': getattr(item, 'quantity_done_formatting', 0),
        'quantity_done_edges': getattr(item, 'quantity_done_edges', 0),
        'quantity_done_painting': getattr(item, 'quantity_done_painting', 0),
        'quantity_done_packaging': getattr(item, 'quantity_done_packaging', 0),
        'client_order_number': item.order.client_order_number if item.order else None,
        'quote_number': item.order.quote_number if item.order else None,
        'unit_price_net': float(getattr(item, 'unit_price_net', 0) or 0),
        'updated_at': item.updated_at.isoformat() if getattr(item, 'updated_at', None) else None,
        'sync_source': item.order.sync_source if item.order else None,
        'delivery_address': (item.order.delivery_address if item.order else None) or '',
        'order_notes': item.order.order_notes if item.order else None,

        # Źródło zamówienia (kanał sprzedaży z BaseLinkera)
        'order_source': item.order.order_source if item.order else None,
        'order_source_id': item.order.order_source_id if item.order else None,
        'order_source_name': item.order.order_source_name if item.order else None,
        'order_source_display': item.order.order_source_display if item.order else None,
    }

    if product_data['order_date'] and hasattr(product_data['order_date'], 'isoformat'):
        product_data['order_date'] = product_data['order_date'].isoformat()
    if product_data['created_at'] and hasattr(product_data['created_at'], 'isoformat'):
        product_data['created_at'] = product_data['created_at'].isoformat()

    station_fields = ['cutting', 'assembly', 'gluing', 'formatting', 'edges',
                      'painting', 'packaging']
    for station in station_fields:
        started_field = f'{station}_started_at'
        completed_field = f'{station}_completed_at'
        if product_data.get(started_field) and hasattr(product_data[started_field], 'isoformat'):
            product_data[started_field] = product_data[started_field].isoformat()
        if product_data.get(completed_field) and hasattr(product_data[completed_field], 'isoformat'):
            product_data[completed_field] = product_data[completed_field].isoformat()

    return product_data


@api_bp.route('/products-filtered', methods=['GET', 'POST'])
@login_required
def products_filtered():
    """
    API endpoint dla filtrowania produktów - ZMODYFIKOWANY DLA priority_rank
    """
    try:
        # Pobierz parametry filtrów
        status_filter = request.args.get('status', 'all')
        search_query = request.args.get('search', '').strip()
        page = int(request.args.get('page', 1))
        per_page = min(int(request.args.get('per_page', 50)), 200)
        # ZMIANA: domyślnie sortuj po priority_rank zamiast priority_score
        sort_by = request.args.get('sort_by', 'priority_rank')
        # ZMIANA: dla priority_rank używamy ASC (1,2,3...)
        default_order = 'asc' if sort_by == 'priority_rank' else 'desc'
        sort_order = request.args.get('sort_order', default_order)
        
        # Rozpocznij query od wszystkich produktów — join ProductionOrder dla pól order-level
        query = ProductionItem.query.join(ProductionOrder)

        # Filtrowanie po statusie
        if status_filter and status_filter != 'all':
            query = query.filter(ProductionItem.current_status == status_filter)

        # Wyszukiwanie - bez zmian
        if search_query:
            search_pattern = f"%{search_query}%"
            search_conditions = []

            if hasattr(ProductionItem, 'original_product_name'):
                search_conditions.append(ProductionItem.original_product_name.ilike(search_pattern))
            if hasattr(ProductionItem, 'short_product_id'):
                search_conditions.append(ProductionItem.short_product_id.ilike(search_pattern))
            # order-level fields via ProductionOrder (join already present)
            search_conditions.append(ProductionOrder.internal_order_number.ilike(search_pattern))
            search_conditions.append(ProductionOrder.client_name.ilike(search_pattern))
            # Wyszukiwanie po numerze zamówienia klienta (np. "1617/2025")
            search_conditions.append(ProductionOrder.client_order_number.ilike(search_pattern))
            # Wyszukiwanie po numerze wyceny (np. "226/04/26/W")
            search_conditions.append(ProductionOrder.quote_number.ilike(search_pattern))
            # Wyszukiwanie po numerze Baselinker — Integer, cast do String
            search_conditions.append(cast(ProductionOrder.baselinker_order_id, String).ilike(search_pattern))

            if search_conditions:
                query = query.filter(or_(*search_conditions))
        
        # ZMIANA: Sortowanie - priority_rank jako główne sortowanie
        sort_column = None
        if sort_by == 'priority_rank' and hasattr(ProductionItem, 'priority_rank'):
            sort_column = ProductionItem.priority_rank
        elif sort_by == 'deadline_date' and hasattr(ProductionItem, 'deadline_date'):
            sort_column = ProductionItem.deadline_date
        elif sort_by == 'created_at' and hasattr(ProductionItem, 'created_at'):
            sort_column = ProductionItem.created_at
        elif sort_by == 'short_product_id' and hasattr(ProductionItem, 'short_product_id'):
            sort_column = ProductionItem.short_product_id
        
        if sort_column is not None:
            if sort_order == 'desc':
                query = query.order_by(sort_column.desc())
            else:
                query = query.order_by(sort_column.asc())
        else:
            # ZMIANA: domyślne sortowanie po priority_rank ASC zamiast ID
            if hasattr(ProductionItem, 'priority_rank'):
                query = query.order_by(ProductionItem.priority_rank.asc())
            else:
                query = query.order_by(ProductionItem.id.desc())
        
        # Paginacja - bez zmian
        paginated = query.paginate(
            page=page,
            per_page=per_page,
            error_out=False
        )
        
        # Przygotuj dane produktów - delegacja do wspólnego helpera
        today = date.today()
        products_data = [_serialize_production_item(item, today) for item in paginated.items]
        
        # ZMIANA: Statystyki oparte na priority_rank
        stats = {
            'total_filtered': paginated.total,
            'total_volume': sum(float(p['volume_m3']) * p.get('quantity', 1) for p in products_data),
            'total_value': sum(float(p['total_value']) for p in products_data),
            # ZMIANA: avg_priority_rank zamiast avg_priority_score
            'avg_priority_rank': sum(float(p['priority_rank'] or 0) for p in products_data) / len(products_data) if products_data else 0,
            'avg_priority': sum(float(p['priority_rank'] or 0) for p in products_data) / len(products_data) if products_data else 0,
            'overdue_count': len([p for p in products_data if p['days_to_deadline'] is not None and p['days_to_deadline'] < 0])
        }
        
        # Informacje o paginacji - bez zmian
        pagination_info = {
            'page': paginated.page,
            'per_page': paginated.per_page,
            'total': paginated.total,
            'pages': paginated.pages,
            'has_prev': paginated.has_prev,
            'has_next': paginated.has_next,
            'prev_num': paginated.prev_num,
            'next_num': paginated.next_num
        }
        
        return jsonify({
            'success': True,
            'products': products_data,
            'pagination': pagination_info,
            'stats': stats,
            'filters_applied': {
                'status': status_filter,
                'search': search_query,
                'sort_by': sort_by,
                'sort_order': sort_order
            }
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'Błąd filtrowania produktów: {str(e)}',
            'products': [],
            'pagination': {'page': 1, 'pages': 1, 'total': 0},
            'stats': {},
            'traceback': traceback.format_exc()
        }), 500


@api_bp.route('/products/<int:product_id>/details', methods=['GET'])
@login_required
def product_details(product_id):
    """
    Zwraca pełne dane pojedynczego produktu (te same pola co /products-filtered).

    Używane przez modal szczegółów w products-module.js - zastępuje wcześniejsze
    pobieranie całej strony listy (domyślnie 50 rekordów), które gubiło produkty
    poza pierwszą stroną i nadpisywało cache frontendu.
    """
    try:
        item = ProductionItem.query.get(product_id)
        if not item:
            return jsonify({
                'success': False,
                'error': f'Nie znaleziono produktu o ID {product_id}'
            }), 404

        return jsonify({
            'success': True,
            'product': _serialize_production_item(item)
        })
    except Exception as e:
        logger.exception('Błąd pobierania szczegółów produktu', extra={'product_id': product_id})
        return jsonify({
            'success': False,
            'error': f'Błąd pobierania szczegółów produktu: {str(e)}',
            'traceback': traceback.format_exc()
        }), 500


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================



# ============================================================================
# ERROR HANDLERS
# ============================================================================


@api_bp.route('/products/<int:product_id>/notes', methods=['PUT'])
@login_required
def update_product_notes(product_id):
    """
    PUT /production/api/products/<id>/notes
    
    Aktualizuje notatki produkcyjne dla produktu
    
    Body JSON:
    {
        "notes": "Nowa treść notatki"
    }
    
    Returns: JSON z rezultatem operacji
    """
    try:
        from ...models import ProductionItem
        
        # Pobierz dane z request
        data = request.get_json()
        if not data:
            return jsonify({
                'success': False, 
                'error': 'Brak danych JSON'
            }), 400
        
        new_notes = data.get('notes', '').strip()
        
        # Znajdź produkt
        product = ProductionItem.query.get_or_404(product_id)
        
        # Zapisz stare notatki dla logowania
        old_notes = product.production_notes or ''
        
        # Aktualizuj notatki
        product.production_notes = new_notes
        product.updated_at = get_local_now()
        
        db.session.commit()
        
        logger.info("API: Zaktualizowano notatki produktu", extra={
            'product_id': product_id,
            'short_product_id': product.short_product_id,
            'user_id': current_user.id,
            'old_notes_length': len(old_notes),
            'new_notes_length': len(new_notes),
            'client_ip': request.remote_addr
        })
        
        return jsonify({
            'success': True,
            'message': 'Notatki zostały zaktualizowane',
            'data': {
                'product_id': product_id,
                'short_product_id': product.short_product_id,
                'notes': new_notes,
                'updated_at': product.updated_at.isoformat()
            }
        }), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error("API: Błąd aktualizacji notatek", extra={
            'product_id': product_id,
            'user_id': current_user.id,
            'error': str(e),
            'client_ip': request.remote_addr
        })
        
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500



@api_bp.route('/products/<int:product_id>/order-products', methods=['GET'])
@login_required  
def get_order_products(product_id):
    """
    GET /production/api/products/<id>/order-products
    
    Zwraca wszystkie produkty z tego samego zamówienia Baselinker
    dla paska produktów w modal
    
    Returns: JSON z listą produktów z zamówienia
    """
    try:
        from ...models import ProductionItem
        
        # Znajdź produkt
        product = ProductionItem.query.get_or_404(product_id)

        product_baselinker_id = product.order.baselinker_order_id if product.order else None
        if not product_baselinker_id:
            return jsonify({
                'success': True,
                'products': [_format_product_for_navigation(product)],
                'total_count': 1,
                'current_product_id': product_id
            }), 200

        # Znajdź wszystkie produkty z tego zamówienia
        order_products = ProductionItem.query.join(ProductionOrder).filter(
            ProductionOrder.baselinker_order_id == product_baselinker_id
        ).order_by(ProductionItem.product_sequence_in_order.asc()).all()

        # Formatuj produkty dla nawigacji
        formatted_products = []
        for p in order_products:
            formatted_products.append(_format_product_for_navigation(p))

        logger.info("API: Pobrano produkty zamówienia", extra={
            'product_id': product_id,
            'baselinker_order_id': product_baselinker_id,
            'products_count': len(formatted_products),
            'user_id': current_user.id
        })

        return jsonify({
            'success': True,
            'products': formatted_products,
            'total_count': len(formatted_products),
            'current_product_id': product_id,
            'baselinker_order_id': product_baselinker_id
        }), 200
        
    except Exception as e:
        logger.error("API: Błąd pobierania produktów zamówienia", extra={
            'product_id': product_id,
            'user_id': current_user.id,
            'error': str(e)
        })
        
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@api_bp.route('/order-timeline/<int:baselinker_order_id>', methods=['GET'])
@login_required
def get_order_timeline(baselinker_order_id):
    """
    GET /production/api/order-timeline/<baselinker_order_id>

    Zwraca linię czasu stanowisk produkcyjnych i status zamówienia
    dla bloku 'Zamówienie' w modalu szczegółów wyceny.
    """
    try:
        from sqlalchemy.orm import joinedload
        from ...models import ProductionProduct, ProductionOrder
        from ...services.order_timeline_service import (
            build_timeline_payload, order_status_badge,
        )

        products = (ProductionProduct.query
                    .join(ProductionOrder)
                    .options(joinedload(ProductionProduct.configuration))
                    .filter(ProductionOrder.baselinker_order_id == baselinker_order_id)
                    .order_by(ProductionProduct.product_sequence_in_order.asc())
                    .all())

        active = [p for p in products if p.current_status != 'anulowane']
        if not active:
            return jsonify({'success': True, 'has_data': False}), 200

        return jsonify({
            'success': True,
            'has_data': True,
            'order_status': order_status_badge(products),
            'stations': build_timeline_payload(products),
        }), 200

    except Exception as e:
        logger.error("API: Błąd budowy linii czasu zamówienia", extra={
            'user_id': current_user.id,
            'baselinker_order_id': baselinker_order_id,
            'error': str(e),
        })
        return jsonify({'success': False, 'has_data': False, 'error': str(e)}), 500


def _format_product_for_navigation(product):
    """
    Formatuje produkt dla nawigacji w modal (pasek produktów)
    
    Format: [Gatunek] [Technologia] [Klasa] [Wymiary] [Wykończenie]
    """
    # Buduj specyfikację produktu
    spec_parts = []
    
    # Gatunek drewna
    if product.configuration and product.configuration.species:
        spec_parts.append(product.configuration.species)

    # Technologia
    if product.configuration and product.configuration.technology:
        spec_parts.append(product.configuration.technology)

    # Klasa drewna
    if product.configuration and product.configuration.wood_class:
        spec_parts.append(product.configuration.wood_class)
    
    # Wymiary
    dimensions = []
    if product.parsed_width_cm:
        dimensions.append(f"{int(product.parsed_width_cm)}")
    if product.parsed_thickness_cm:
        dimensions.append(f"{int(product.parsed_thickness_cm)}")
    if product.parsed_length_cm:
        dimensions.append(f"{int(product.parsed_length_cm)}")
    
    if dimensions:
        spec_parts.append("×".join(dimensions))
    
    # Wykończenie
    if product.parsed_finish_state:
        spec_parts.append(product.parsed_finish_state)
    
    # Połącz specyfikację
    specification = " ".join(spec_parts) if spec_parts else product.original_product_name
    
    # Wymiary jako osobne pole
    dim_parts = []
    if product.parsed_width_cm:
        dim_parts.append(f"{int(product.parsed_width_cm)}")
    if product.parsed_thickness_cm:
        dim_parts.append(f"{int(product.parsed_thickness_cm)}")
    if product.parsed_length_cm:
        dim_parts.append(f"{int(product.parsed_length_cm)}")
    dimensions_str = "×".join(dim_parts) + " cm" if dim_parts else ''

    return {
        'id': product.id,
        'short_product_id': product.short_product_id,
        'specification': specification,
        'dimensions': dimensions_str,
        'sequence': product.product_sequence_in_order,
        'status': product.current_status,
        'priority': product.priority_rank or 100
    }


@api_bp.route('/get-order-products-count/<order_number>')
@login_required
def get_order_products_count(order_number: str):
    """
    GET /production/api/get-order-products-count/<order_number>

    Pobiera liczbę produktów w zamówieniu (używane do decyzji o wyświetlaniu tooltipa).

    Returns:
        JSON: Liczba produktów w zamówieniu
    """
    try:
        count = (
            ProductionItem.query
            .join(ProductionOrder, ProductionItem.order_id == ProductionOrder.id)
            .filter(ProductionOrder.internal_order_number == order_number)
            .count()
        )

        return jsonify({
            'success': True,
            'order_number': order_number,
            'products_count': count
        })

    except Exception as e:
        logger.error("Błąd pobierania liczby produktów", extra={
            'order_number': order_number,
            'error': str(e)
        })

        return jsonify({
            'success': False,
            'error': f'Błąd serwera: {str(e)}'
        }), 500
