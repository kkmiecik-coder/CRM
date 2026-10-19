# modules/production/services/archiwum_zamowien.py
"""
Definicja „zamówienia archiwalnego” i zapytania zbudowane na niej.

Jedno źródło prawdy dla zakładki Produkty (widok archiwum) i dla tabletu kierownika hali:
oba muszą uznawać za archiwalne dokładnie te same zamówienia. Ciała funkcji przeniesione
z `routers/api/products_api.py` bez zmian (refaktor bez zmiany zachowania).
"""

from sqlalchemy import and_, or_, func, cast, literal, String, case

from extensions import db
from modules.production.models import (
    ProductionOrder, ProductionItem, ProductionConfiguration,
)
from modules.production.logistics import sposoby


def warunek_archiwum():
    """
    Zamówienie należy do archiwum (logistyka etap 4, krok 4.5, spec 10), gdy:
     - jest ZAMKNIĘTE W LOGISTYCE (`prod_orders.logistics_closed_at IS NOT NULL`) i żadna pozycja
       nie wróciła do produkcji, LUB
     - WSZYSTKIE pozycje mają status 'anulowane' (całe zamówienie anulowane).
    Spakowane, ale otwarte w Logistyce (transport czeka na trasę albo w drodze, odbiór niewydany,
    brak sposobu dostawy) zostaje w aktywnych — panel produkcji i zakładka Logistyka widzą je razem.
    Drugi człon zamkniętych („bez pozycji w produkcji”) to bezpiecznik na chwilę między doróbką
    a przeliczeniem cyklu (cron `przelicz_otwarte`): pozycja w produkcji nie może zniknąć z aktywnych.
    Warunek działa w HAVING nad GROUP BY internal_order_number; gdyby pod jednym numerem było kilka
    wierszy prod_orders, zamknięte muszą być wszystkie.
    """
    closed_in_logistics = func.sum(
        case((ProductionOrder.logistics_closed_at.is_(None), 1), else_=0)
    ) == 0
    nothing_in_production = func.sum(
        case((ProductionItem.current_status.notin_(sposoby.STATUSY_PO_SPAKOWANIU + ('anulowane',)), 1),
             else_=0)
    ) == 0
    fully_cancelled = func.sum(
        case((ProductionItem.current_status != 'anulowane', 1), else_=0)
    ) == 0
    return or_(and_(closed_in_logistics, nothing_in_production), fully_cancelled)


def data_zakonczenia_expr(wdrozenie=None):
    """
    Data „Zakończono” zamówienia archiwalnego (spec 10) — jedno wyrażenie dla listy, sortowania,
    filtra dat, statystyk i opcji filtrów:
     - zamknięte w Logistyce po wdrożeniu kroku 4.3 → `logistics_closed_at` (kurier: spakowanie,
       odbiór: wydanie, transport: dostarczenie),
     - zamknięte NIE PÓŹNIEJ niż znacznik `logistyka_weryfikacja_od` (`wdrozenie`) → jak przed
       krokiem 4.5, MAX(packaging_completed_at). Takie zamknięcia nadała hurtem migracja etapu 1
       (`NOW()` przy wdrożeniu), więc ich `logistics_closed_at` to data wdrożenia, nie spakowania.
       Danych nie przepisujemy migracją (spec 10, rozstrzygnięcie 2),
     - niezamknięte, w całości anulowane → MAX(updated_at) pozycji (ostatnia zmiana, czyli
       w praktyce anulowanie); cron logistyki zamyka je przy najbliższym przebiegu i od tej chwili
       obowiązuje `logistics_closed_at`.
    Bez znacznika (baza bez migracji 4.3) każde zamknięcie liczy się jako bieżące.
    """
    closed_at = func.max(ProductionOrder.logistics_closed_at)
    all_closed = func.sum(
        case((ProductionOrder.logistics_closed_at.is_(None), 1), else_=0)
    ) == 0
    branches = []
    if wdrozenie is not None:
        branches.append((and_(all_closed, closed_at <= wdrozenie),
                         func.max(ProductionItem.packaging_completed_at)))
    branches.append((all_closed, closed_at))
    return case(*branches, else_=func.max(ProductionItem.updated_at))


def _any_product_matches(condition):
    """
    HAVING-owy odpowiednik JS-owego `order.products.some(...)`.

    Warunek MUSI iść do HAVING, nie do WHERE: filtr wybiera CAŁE zamówienia
    mające choć jedną pasującą pozycję, a w WHERE obciąłby pozostałe pozycje
    i zafałszował sumy objętości/wartości oraz licznik pozycji.
    """
    return func.sum(case((condition, 1), else_=0)) > 0


def zapytanie_archiwum(completed_from_dt=None, completed_to_dt=None, filters=None, wdrozenie=None):
    """
    Agregat "jedno zamówienie = jeden wiersz", kluczowany po internal_order_number
    (tak samo, jak UI skleja karty zamówień). `wdrozenie` — znacznik kroku 4.3
    (`weryfikacja.data_wdrozenia()`), patrz `data_zakonczenia_expr`.

    `filters` (opcjonalne) to dict z kluczami search / wood_species / technologies /
    wood_classes / thicknesses — każdy filtr to osobne HAVING, więc filtry łączą
    się przez AND, a wartości w obrębie jednego filtra przez OR (IN). Dokładnie
    tak, jak działa dziś `orderPassesFilters()` w archive-module.js.
    """
    completed_expr = data_zakonczenia_expr(wdrozenie)
    q = db.session.query(
        ProductionOrder.internal_order_number.label('ion'),
        completed_expr.label('completed_at'),
        func.min(ProductionItem.created_at).label('created_at'),
        func.count(ProductionItem.id).label('products_count'),
        func.sum(ProductionItem.quantity).label('quantity'),
        func.sum(ProductionItem.volume_m3 * ProductionItem.quantity).label('volume'),
        func.sum(ProductionItem.total_value_net).label('value'),
    ).select_from(ProductionOrder).join(
        ProductionItem, ProductionItem.order_id == ProductionOrder.id
    ).outerjoin(
        ProductionConfiguration,
        ProductionItem.configuration_id == ProductionConfiguration.id
    ).filter(
        ProductionOrder.internal_order_number.isnot(None)
    ).group_by(
        ProductionOrder.internal_order_number
    ).having(warunek_archiwum())

    # Zakres dat liczony na poziomie zamówienia (data „Zakończono”), nie pojedynczej sztuki
    if completed_from_dt is not None:
        q = q.having(completed_expr >= completed_from_dt)
    if completed_to_dt is not None:
        q = q.having(completed_expr < completed_to_dt)

    filters = filters or {}

    search_query = (filters.get('search') or '').strip()
    if search_query:
        pattern = f"%{search_query}%"
        # Te same pola, po których szuka dziś JS. baselinker_order_id sklejamy
        # z prefiksem 'bl-', bo w JS haystackiem jest właśnie `bl-<id>` —
        # dzięki temu i "bl-252" i samo "25208907" nadal trafiają.
        # Sklejanie przez operator `+` na typie String, nie przez func.concat():
        # SQLAlchemy renderuje je jako CONCAT() na MySQL i `||` na SQLite
        # (którego używają testy) — func.concat() wywraca się na SQLite.
        bl_label = literal('bl-') + cast(ProductionOrder.baselinker_order_id, String)
        q = q.having(_any_product_matches(or_(
            ProductionOrder.client_name.ilike(pattern),
            ProductionOrder.internal_order_number.ilike(pattern),
            ProductionOrder.client_order_number.ilike(pattern),
            ProductionOrder.quote_number.ilike(pattern),
            bl_label.ilike(pattern),
            ProductionItem.original_product_name.ilike(pattern),
            ProductionItem.short_product_id.ilike(pattern),
        )))

    if filters.get('wood_species'):
        q = q.having(_any_product_matches(
            ProductionConfiguration.species.in_(filters['wood_species'])))
    if filters.get('technologies'):
        q = q.having(_any_product_matches(
            ProductionConfiguration.technology.in_(filters['technologies'])))
    if filters.get('wood_classes'):
        q = q.having(_any_product_matches(
            ProductionConfiguration.wood_class.in_(filters['wood_classes'])))
    if filters.get('thicknesses'):
        q = q.having(_any_product_matches(
            ProductionItem.parsed_thickness_cm.in_(filters['thicknesses'])))

    return q


def statystyki_archiwum(rows):
    """
    Statystyki nagłówka archiwum liczone na CAŁYM przefiltrowanym wyniku
    (nie na bieżącej stronie) — inaczej liczniki zmieniałyby się przy przewijaniu.
    Zaokrąglenia per zamówienie odtwarzają to, co robił dotąd JS.
    """
    orders_count = len(rows)
    products_count = 0
    total_quantity = 0
    total_volume = 0.0
    total_value = 0.0
    durations = []

    for r in rows:
        products_count += int(r.products_count or 0)
        total_quantity += int(r.quantity or 0)
        total_volume += round(float(r.volume or 0), 4)
        total_value += round(float(r.value or 0), 2)
        if r.completed_at and r.created_at:
            delta = (r.completed_at - r.created_at).total_seconds()
            if delta >= 0:
                durations.append(round(delta / 86400.0, 1))

    avg_days = round(sum(durations) / len(durations), 1) if durations else None

    return {
        'total_count': products_count,
        'total_quantity': total_quantity,
        'total_volume': round(total_volume, 4),
        'total_value': round(total_value, 2),
        'urgent_count': 0,
        'status_breakdown': {},
        'archive': {
            'orders_count': orders_count,
            'products_count': products_count,
            'total_volume': round(total_volume, 4),
            'total_value': round(total_value, 2),
            'avg_realization_days': avg_days,
        }
    }


def etapy_zamowien(products):
    """
    {internal_order_number: (status, napis)} — prawdziwy etap zamówienia na karcie archiwum
    (Spakowane, Zweryfikowane, Załadowane, Dostarczone, Anulowane; dawniej stałe „Spakowane”).
    Etap = najbardziej zaległa niezanulowana pozycja (`weryfikacja.etap`), napis = jej
    `status_display_name` — bez dopisku „czeka na weryfikację” z panelu Logistyki, bo w archiwum
    leżą zamówienia zamknięte. Liczone z pozycji już wczytanych na stronę, bez zapytań.
    """
    from modules.production.logistics.services import weryfikacja
    by_ion = {}
    for p in products:
        ion = p.order.internal_order_number if p.order else None
        if ion:
            by_ion.setdefault(ion, []).append(p)
    stages = {}
    for ion, items in by_ion.items():
        active = [p for p in items if p.current_status != 'anulowane']
        status, label = weryfikacja.etap(active)
        if active:
            label = next(p.status_display_name for p in active if p.current_status == status)
        stages[ion] = (status, label)
    return stages
