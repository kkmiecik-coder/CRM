"""
Service: reject sztuk produktu z aktualnego stanowiska (formatowanie i wszystkie
stanowiska za nim: sklejanie, krawędzie, lakiernia, pakowanie).
Tworzy rekord doróbki w prod_products, decrementuje quantity oryginału,
zapisuje wpis w prod_rework_log. Wszystko w jednej transakcji z SELECT ... FOR UPDATE.
"""
from __future__ import annotations

from datetime import datetime
import logging

from extensions import db
from modules.production.models import (
    ProductionProduct,
    ProductionReworkLog,
    get_local_now,
)
from modules.production.services.station_catalog import STATION_PENDING_STATUS

logger = logging.getLogger(__name__)


VALID_REASONS = {
    'wymiary', 'jakosc_sklejenia', 'jakosc_produktu', 'inne',
    'jakosc_krawedzi', 'jakosc_lakierowania',
}

# Cięcie i składanie to początek trasy — doróbka i tak tam wraca, więc cofanie
# z nich nie ma sensu. Każde stanowisko może zgłosić każdą przyczynę; listę
# pokazywaną operatorowi filtruje aplikacja.
VALID_REJECT_STATIONS = {'formatting', 'gluing', 'edges', 'painting', 'packaging'}


class RejectError(Exception):
    """Domain error podczas rejectu — przekształcamy na HTTP w routerze."""

    def __init__(self, code: str, message: str, status: int = 400):
        self.code = code
        self.message = message
        self.status = status
        super().__init__(message)


def _determine_return_station(product: ProductionProduct) -> str:
    """
    Wyznacz stanowisko, na które wraca doróbka.
    Reguła: historia oryginału (cutting_completed_at / assembly_completed_at);
    fallback: parsed_technology.
    """
    if product.cutting_completed_at is not None:
        return 'cutting'
    if product.assembly_completed_at is not None:
        return 'assembly'
    # Fallback po technologii
    tech = (product.configuration.technology if product.configuration else None) or ''
    if tech == 'lite':
        return 'assembly'
    return 'cutting'  # mikrowczep i pozostałe → cutting


def _initial_status_for_return_station(station: str) -> str:
    return 'czeka_na_skladanie' if station == 'assembly' else 'czeka_na_wyciecie'


def _check_product_on_station(product: ProductionProduct, station: str) -> None:
    """
    Sztukę cofa tylko stanowisko, na którym ona teraz czeka.

    Formatowanie zachowuje stary kod błędu i stary status 'w_realizacji':
    APK sprzed rozszerzenia parsują 'product_not_in_formatting', a pozostałe
    stanowiska nigdy tego statusu nie miały, więc go nie dostają.
    """
    status = product.current_status
    if station == 'formatting':
        if status not in ('czeka_na_formatowanie', 'w_realizacji'):
            raise RejectError(
                'product_not_in_formatting',
                f'produkt ma status {status}, oczekiwano czeka_na_formatowanie',
                status=409,
            )
        return

    expected = STATION_PENDING_STATUS[station]
    if status != expected:
        raise RejectError(
            'product_not_on_station',
            f'produkt ma status {status}, oczekiwano {expected}',
            status=409,
        )


def reject_product_quantity(
    *,
    product_id: int,
    quantity: int,
    reason_category: str,
    rejected_at_station: str,
    user_id: int | None = None,
    device_id: str | None = None,
    worker_ids: list[int] | None = None,
) -> tuple[ProductionProduct, ProductionProduct, ProductionReworkLog]:
    """
    Wykonuje reject `quantity` sztuk z `product_id` na stanowisku `rejected_at_station`.

    Zwraca: (oryginał_po_update, doróbka, wpis_w_rework_log).
    Cały flow w jednej transakcji z SELECT ... FOR UPDATE na oryginale.

    worker_ids: profile wybrane na tablecie (nagłówek X-Worker-Ids). Doróbka NIE
    generuje eventu stanowiskowego — nie woła set_quantity_done() — więc nie ma
    do czego dopiąć atrybucji dzielonej. Zapisujemy wyłącznie PIERWSZEGO
    pracownika z listy w prod_rework_log.worker_id; to audyt, nie statystyka
    (docs/worker-profiles-backend.md §4.4).

    Raises: RejectError z `code` w {'invalid_quantity', 'invalid_reason',
            'invalid_station', 'product_not_found', 'product_not_in_formatting'
            (tylko formatowanie), 'product_not_on_station' (pozostałe)}.
    """
    if quantity is None or quantity < 1:
        raise RejectError('invalid_quantity', 'quantity musi być >= 1')

    if reason_category not in VALID_REASONS:
        raise RejectError(
            'invalid_reason',
            f'reason_category musi być jednym z {sorted(VALID_REASONS)}'
        )

    if rejected_at_station not in VALID_REJECT_STATIONS:
        raise RejectError(
            'invalid_station',
            f'cofać można tylko z: {sorted(VALID_REJECT_STATIONS)}'
        )

    # Pesymistyczna blokada wiersza oryginału
    original: ProductionProduct | None = (
        db.session.query(ProductionProduct)
        .filter(ProductionProduct.id == product_id)
        .with_for_update()
        .one_or_none()
    )
    if original is None:
        raise RejectError('product_not_found', f'product {product_id} nie istnieje', status=404)

    _check_product_on_station(original, rejected_at_station)

    # Cofnąć można tylko sztuki, których to stanowisko jeszcze nie oznaczyło
    # jako zrobione — te zrobione fizycznie poszły już dalej.
    qty_done_here = original.get_quantity_done(rejected_at_station) or 0
    available_to_reject = original.quantity - qty_done_here
    if quantity > available_to_reject:
        raise RejectError(
            'invalid_quantity',
            f'można cofnąć maksymalnie {available_to_reject} szt. (quantity={original.quantity}, zrobione na {rejected_at_station}={qty_done_here})',
        )

    now = get_local_now()
    return_station = _determine_return_station(original)
    rework_status = _initial_status_for_return_station(return_station)

    # Wartości używane przy kopiowaniu (przed decrementem)
    original_quantity_before = original.quantity
    unit_volume = (
        float(original.volume_m3) / original_quantity_before
        if original.volume_m3 and original_quantity_before
        else None
    )

    # 1. Update oryginału
    original.quantity = original_quantity_before - quantity
    if original.quantity == 0:
        original.current_status = 'anulowane'
    # quantity_done_* na poprzednich stanowiskach NIE są ruszane (statystyki zachowane)
    # quantity_done_<stanowisko cofające> też NIE — liczy sztuki, które poszły dalej
    original.updated_at = now

    # Stan druku etykiet trzyma numery LOKALNE 1..quantity. Po zmniejszeniu
    # ilości (realnie: cofnięcie z pakowania) numery spoza nowego zakresu
    # wskazywałyby sztuki, których pozycja już nie ma — należą teraz do
    # doróbki, która dostaje własny, pusty stan i wydrukuje je sama.
    # Nie wiemy, KTÓRĄ fizycznie sztukę cofnięto, więc przycinamy ogon —
    # tak samo interpretuje zbiór odczyt w wydrukowane_sztuki().
    if original.label_printed_units:
        from modules.production.services.label_print_service import (
            _zapisz_sztuki,
            wydrukowane_sztuki,
        )
        _zapisz_sztuki(original, wydrukowane_sztuki(original))

    # Powód odrzutu nie wynika ze zmiany pól, więc listener go nie zna —
    # dopisujemy zdarzenie jawnie, obok automatycznego status_change.
    # WAŻNE: Sprawdzamy dostępność tabeli audytu ZANIM dodajemy event do sesji.
    # Bez tego: db.session.add() zakolejkowuje, ale INSERT do prod_product_events
    # dzieje się dopiero przy flush() poza try/except — jeśli tabela nie istnieje,
    # wyjątek nie zostanie złapany i wysadzi CAŁĄ operację doróbki. Audyt nigdy
    # nie może przerwać operacji biznesowej, więc sprawdzenie jest tutaj.
    from modules.production.services.product_events import (
        current_actor,
        _audit_table_available,
    )

    if _audit_table_available():
        try:
            from modules.production.models import ProductionProductEvent

            actor = current_actor()
            db.session.add(ProductionProductEvent(
                production_item_id=original.id,
                event_type='rework',
                old_value=str(original_quantity_before),
                new_value=str(original.quantity),
                actor_type=actor.actor_type,
                user_id=user_id or actor.user_id,
                device_id=device_id or actor.device_id,
                source=actor.source,
                endpoint=actor.endpoint,
                ip_address=actor.ip_address,
                note=f'Doróbka {quantity} szt. z {rejected_at_station}: {reason_category}',
                created_at=now,
            ))
        except Exception:
            logger.error("Nie udało się zapisać zdarzenia doróbki", exc_info=True)

    # 2. Utworzenie rekordu doróbki
    rework = ProductionProduct(
        original_product_id=original.id,
        short_product_id=original.short_product_id,
        order_id=original.order_id,
        configuration_id=original.configuration_id,
        # parsed_* (species/wood_class/technology pochodzą z configuration_id)
        parsed_thickness_cm=original.parsed_thickness_cm,
        parsed_width_cm=original.parsed_width_cm,
        parsed_length_cm=original.parsed_length_cm,
        parsed_finish_type=original.parsed_finish_type,
        parsed_finish_state=original.parsed_finish_state,
        parsed_finish_color_type=original.parsed_finish_color_type,
        parsed_finish_color=original.parsed_finish_color,
        parsed_finish_gloss=original.parsed_finish_gloss,
        # parsed_edge_processing + parsed_finish_type + cut_to_size to KOMPLET pól,
        # z których complete_task() wylicza trasę po formatowaniu. Po rozdziale
        # Wykańczania na Krawędzie i Lakiernię doróbka zdjęta z produktu
        # olejowanego BEZ obróbki krawędzi ominie Krawędzie, choć oryginał
        # przeszedł jeszcze przez wykańczalnię. To świadomy skutek nowej trasy,
        # nie błąd kopiowania — nie „naprawiaj" go dopisując tu wyjątek.
        parsed_edge_processing=original.parsed_edge_processing,
        parsed_edge_type=original.parsed_edge_type,
        parsed_edge_radius=original.parsed_edge_radius,
        parsed_edge_angle=original.parsed_edge_angle,
        parsed_edge_letters=original.parsed_edge_letters,
        parsed_edges_groups=original.parsed_edges_groups,
        edge_svg=original.edge_svg,
        # `shape` nie decyduje o trasie, ale idzie do DTO tabletu
        # (mobile_api_service.py:1071) obok kopiowanego shape_svg. Bez niego
        # doróbka startowała z kolumnowym default 'rectangular' i pokazywała
        # operatorowi inny kształt niż oryginał, z którego powstała.
        shape=original.shape,
        shape_svg=original.shape_svg,
        shape_rotation=original.shape_rotation,
        quote_item_detail_id=original.quote_item_detail_id,
        product_sequence_in_order=original.product_sequence_in_order,
        baselinker_product_id=original.baselinker_product_id,
        original_product_name=original.original_product_name,
        cut_to_size=original.cut_to_size,
        thickness_group=original.thickness_group,
        volume_m3=(unit_volume * quantity) if unit_volume is not None else None,
        unit_price_net=original.unit_price_net,
        total_value_net=(
            (float(original.unit_price_net) * quantity)
            if original.unit_price_net is not None else None
        ),
        quantity=quantity,
        current_status=rework_status,
        deadline_date=original.deadline_date,
        created_at=now,
        updated_at=now,
    )
    db.session.add(rework)
    db.session.flush()  # potrzebne by mieć rework.id do logu

    # Najwyższy priorytet — żółta ramka, top kolejki
    rework.lock_priority(rank=1)

    # 3. Wpis w prod_rework_log
    log_entry = ProductionReworkLog(
        original_product_id=original.id,
        rework_product_id=rework.id,
        quantity=quantity,
        rejected_at_station=rejected_at_station,
        returned_to_station=return_station,
        reason_category=reason_category,
        created_at=now,
        user_id=user_id,
        worker_id=(worker_ids[0] if worker_ids else None),
        device_id=device_id,
    )
    db.session.add(log_entry)

    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        logger.exception(
            "Reject commit failed",
            extra={
                'product_id': original.id,
                'rework_id': rework.id if rework.id else None,
                'quantity': quantity,
                'reason': reason_category,
            },
        )
        raise

    logger.info(
        "Reject wykonany",
        extra={
            'product_id': original.id,
            'short_product_id': original.short_product_id,
            'rework_id': rework.id,
            'quantity': quantity,
            'reason': reason_category,
            'return_station': return_station,
            'user_id': user_id,
            'device_id': device_id,
        },
    )
    return original, rework, log_entry
