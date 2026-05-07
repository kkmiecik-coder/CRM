"""
Synchronizacja statusu zamówienia z Baselinker.
================================================

Jeden właściciel logiki "kto i kiedy zmienia status zamówienia w BL".

Trzy momenty zmiany statusu w BL:

1. Po imporcie nowego zamówienia z BL (sync z "Nowe - opłacone"):
   set_status_for_imported_order() → "W produkcji - [wykończenie]"
   Wybór wykończenia:
   - wszystkie surowe → "W produkcji - surowe"
   - wszystkie olejowane → "W produkcji - olejowanie"
   - wszystkie lakierowane → "W produkcji - lakierowanie"
   - mieszanka → fallback "surowe"

2. Po ukończeniu ostatniego stanowiska produkcyjnego zamówienia:
   schedule_after_station_complete() → "Produkcja zakończona" (138620)
   Warunek: wszystkie pozycje zamówienia mają current_status w POSTPROD_STATUSES.

3. Po ukończeniu pakowania ostatniego produktu zamówienia:
   schedule_after_station_complete() → "Zamówienie spakowane" (138623)
   Warunek: wszystkie pozycje mają current_status == 'spakowane'.

Web ścieżka (complete_order_bulk) commituje sama → wywołuje flush_pending_syncs()
od razu po commit. Mobile ścieżka (with_idempotency) commituje w decoratorze →
decorator po commit wywołuje flush_pending_syncs(). W obu przypadkach handler
woła schedule_after_station_complete() przed return.

Retry przy błędzie API: threading.Timer z backoff 5/15/30/60/120/300/600s
(suma ~18 min). Daemon thread - nie blokuje shutdown procesu.
"""

import threading
from typing import List, Optional
from flask import g, current_app
from modules.logging import get_structured_logger

logger = get_structured_logger('production.baselinker_status_sync')

# Hardcoded ID statusów - potwierdzone przez biznes
PRODUCTION_COMPLETED_STATUS_ID = 138620
ORDER_PACKED_STATUS_ID = 138623
PRODUCTION_RAW_STATUS_ID = 138619  # fallback dla "W produkcji - surowe"

# Statusy lokalne CRM oznaczające "produkcja zakończona, czekamy na logistykę/pakowanie/po pakowaniu"
POSTPROD_STATUSES = frozenset({'czeka_na_logistyke', 'czeka_na_pakowanie', 'spakowane'})

# Stanowiska po których możemy hipotetycznie skończyć produkcję
# (gluing - tylko gdy cut_to_size=False; reszta - normalny flow)
PRODUCTION_STATIONS = frozenset({'gluing', 'formatting', 'finishing', 'painting'})

# Backoff dla retry po błędzie API. Daemon Timer odpala kolejne próby.
RETRY_DELAYS_S = (5, 15, 30, 60, 120, 300, 600)


# ============================================================================
# CASE 1: Po imporcie zamówienia z BL → "W produkcji - [wykończenie]"
# ============================================================================

def determine_production_status_by_finish(products: List) -> int:
    """
    Wybiera ID statusu BL "W produkcji - [wykończenie]" na podstawie produktów.

    Pobiera mapowanie nazwa→ID dynamicznie z baselinker_config (przez
    sync_service.get_baselinker_statuses_from_db) i dopasowuje wzorcem nazwy.
    Mieszanka wykończeń → fallback na "surowe".
    """
    from .sync_service import get_sync_service

    statuses_from_db = get_sync_service().get_baselinker_statuses_from_db()

    status_mapping = {}
    for status_id, status_info in statuses_from_db.items():
        name_lower = status_info['name'].lower()
        if 'olejowanie' in name_lower:
            status_mapping['oiling'] = status_id
        elif 'bejcowanie' in name_lower:
            status_mapping['staining'] = status_id
        elif 'lakierowanie' in name_lower:
            status_mapping['varnishing'] = status_id
        elif 'surowe' in name_lower:
            status_mapping['raw'] = status_id

    if not status_mapping:
        logger.warning("Brak statusów z bazy, używam hardcoded fallback")
        status_mapping = {
            'oiling': 148832,
            'staining': 148831,
            'varnishing': 148830,
            'raw': PRODUCTION_RAW_STATUS_ID,
        }

    default_status = status_mapping.get('raw', PRODUCTION_RAW_STATUS_ID)

    finishes = set()
    for product in products:
        finish_type = product.parsed_finish_type or 'surowe'
        if finish_type == 'surowe':
            finishes.add('raw')
        elif finish_type == 'olejowane':
            sid = status_mapping.get('oiling')
            finishes.add(sid if sid else 'raw')
        elif finish_type == 'lakierowane':
            sid = status_mapping.get('varnishing')
            finishes.add(sid if sid else 'raw')
        elif finish_type == 'bejcowane':
            sid = status_mapping.get('staining')
            finishes.add(sid if sid else 'raw')
        else:
            finishes.add('raw')

    if len(finishes) == 1:
        only = next(iter(finishes))
        if isinstance(only, int):
            logger.info("Określono status wykończenia", extra={
                'status_id': only,
                'products_count': len(products),
            })
            return only
        return default_status

    logger.info("Mieszanka wykończeń - fallback na surowe", extra={
        'finishes': list(finishes),
        'fallback_status': default_status,
    })
    return default_status


def set_status_for_imported_order(baselinker_order_id: int,
                                   products: Optional[List] = None) -> bool:
    """
    Ustawia status BL dla nowo zaimportowanego zamówienia ("W produkcji - X").

    Wywoływane z sync_service.process_orders_with_priority_logic() po pobraniu
    zamówienia z BL. Synchroniczne (jedna próba) - przy błędzie loguje, ale
    NIE retry'uje (sync może chodzić w pętli batch i sam ma error handling).
    """
    if products is None:
        from ..models import ProductionItem
        products = ProductionItem.query.filter_by(
            baselinker_order_id=baselinker_order_id
        ).all()

    if not products:
        logger.error("Brak produktów dla zamówienia - nie można ustawić statusu", extra={
            'baselinker_order_id': baselinker_order_id,
        })
        return False

    target_status = determine_production_status_by_finish(products)
    return _call_set_order_status(baselinker_order_id, target_status)


# ============================================================================
# CASE 2 & 3: Po ukończeniu stanowiska → "Produkcja zakończona" / "Spakowane"
# ============================================================================

def schedule_after_station_complete(internal_order_number: str,
                                     station_code: str) -> None:
    """
    Rejestruje sync do wykonania PO commit transakcji.

    Web (complete_order_bulk) wywołuje flush_pending_syncs() od razu po commit.
    Mobile (with_idempotency decorator) wywołuje flush po swoim commicie.

    Bezpieczne do wielokrotnego wywołania - duplikaty są deduplikowane.
    """
    if not internal_order_number or not station_code:
        return
    if station_code not in PRODUCTION_STATIONS and station_code != 'packaging':
        return  # inne stanowiska nie kończą zamówienia

    if not hasattr(g, 'pending_baselinker_syncs'):
        g.pending_baselinker_syncs = []

    entry = (internal_order_number, station_code)
    if entry not in g.pending_baselinker_syncs:
        g.pending_baselinker_syncs.append(entry)


def flush_pending_syncs() -> None:
    """
    Odpala wszystkie zaplanowane sync'i - WYWOŁYWAĆ PO db.session.commit().

    Każdy sync sprawdza warunek "wszystkie produkty zamówienia w odpowiednim
    stanie" - jeśli spełniony, wysyła setOrderStatus do BL (z retry przy błędzie).
    """
    pending = getattr(g, 'pending_baselinker_syncs', None)
    if not pending:
        return
    g.pending_baselinker_syncs = []  # zapobiega ponownemu wywołaniu w tym samym requeście

    app = current_app._get_current_object()
    for internal_order_number, station_code in pending:
        try:
            _process_pending(app, internal_order_number, station_code)
        except Exception as e:
            logger.error("Błąd przetwarzania pending BL sync", extra={
                'internal_order_number': internal_order_number,
                'station_code': station_code,
                'error': str(e),
            })


def _process_pending(app, internal_order_number: str, station_code: str) -> None:
    """Określa target_status i odpala próbę setOrderStatus."""
    from ..models import ProductionItem

    products = ProductionItem.query.filter_by(
        internal_order_number=internal_order_number
    ).all()
    if not products:
        return

    if station_code == 'packaging':
        if not all(p.current_status == 'spakowane' for p in products):
            return
        target = ORDER_PACKED_STATUS_ID
    elif station_code in PRODUCTION_STATIONS:
        if not all(p.current_status in POSTPROD_STATUSES for p in products):
            return
        target = PRODUCTION_COMPLETED_STATUS_ID
    else:
        return

    baselinker_order_id = products[0].baselinker_order_id
    if not baselinker_order_id:
        logger.warning("Brak baselinker_order_id - pomijam BL sync", extra={
            'internal_order_number': internal_order_number,
        })
        return

    # Pierwsza próba synchronicznie, retry async
    success = _call_set_order_status(baselinker_order_id, target)
    if success:
        logger.info("BL setOrderStatus po stanowisku OK", extra={
            'internal_order_number': internal_order_number,
            'station_code': station_code,
            'baselinker_order_id': baselinker_order_id,
            'target_status_id': target,
        })
        return

    # Niepowodzenie → schedule retry
    _schedule_retry(app, baselinker_order_id, target,
                    internal_order_number=internal_order_number,
                    attempt=0)


# ============================================================================
# Wywołanie API (via sync_service - współdzieli api_key, _make_api_request)
# ============================================================================

def _call_set_order_status(baselinker_order_id: int, target_status_id: int) -> bool:
    """Pojedyncza próba setOrderStatus przez sync_service. Zwraca True/False."""
    try:
        from .sync_service import get_sync_service
        sync_service = get_sync_service()
        if sync_service is None:
            logger.error("Brak sync_service - nie można wywołać BL")
            return False
        return sync_service._update_baselinker_order_status(
            baselinker_order_id, target_status_id
        )
    except Exception as e:
        logger.error("Wyjątek podczas BL setOrderStatus", extra={
            'baselinker_order_id': baselinker_order_id,
            'target_status_id': target_status_id,
            'error': str(e),
        })
        return False


def _schedule_retry(app, baselinker_order_id: int, target_status_id: int,
                    *, internal_order_number: str, attempt: int) -> None:
    """Planuje kolejną próbę przez threading.Timer (daemon)."""
    if attempt >= len(RETRY_DELAYS_S):
        logger.error("Wyczerpano retry dla BL setOrderStatus", extra={
            'internal_order_number': internal_order_number,
            'baselinker_order_id': baselinker_order_id,
            'target_status_id': target_status_id,
            'total_attempts': attempt,
        })
        return

    delay = RETRY_DELAYS_S[attempt]
    logger.warning("Plan retry BL setOrderStatus", extra={
        'internal_order_number': internal_order_number,
        'baselinker_order_id': baselinker_order_id,
        'target_status_id': target_status_id,
        'next_attempt': attempt + 1,
        'next_delay_s': delay,
    })

    timer = threading.Timer(
        delay,
        _retry_attempt,
        kwargs={
            'app': app,
            'baselinker_order_id': baselinker_order_id,
            'target_status_id': target_status_id,
            'internal_order_number': internal_order_number,
            'attempt': attempt + 1,
        },
    )
    timer.daemon = True
    timer.start()


def _retry_attempt(*, app, baselinker_order_id: int, target_status_id: int,
                   internal_order_number: str, attempt: int) -> None:
    """Wykonuje retry w app_context. Przy kolejnym błędzie planuje następny retry."""
    try:
        with app.app_context():
            success = _call_set_order_status(baselinker_order_id, target_status_id)
            if success:
                logger.info("BL setOrderStatus retry OK", extra={
                    'internal_order_number': internal_order_number,
                    'baselinker_order_id': baselinker_order_id,
                    'target_status_id': target_status_id,
                    'attempt': attempt,
                })
                return
    except Exception as e:
        logger.error("Wyjątek podczas BL retry", extra={
            'internal_order_number': internal_order_number,
            'attempt': attempt,
            'error': str(e),
        })

    _schedule_retry(app, baselinker_order_id, target_status_id,
                    internal_order_number=internal_order_number,
                    attempt=attempt)
