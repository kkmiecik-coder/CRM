"""
Service: reject sztuk produktu z aktualnego stanowiska (MVP: formatting).
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

logger = logging.getLogger(__name__)


VALID_REASONS = {'wymiary', 'jakosc_sklejenia', 'jakosc_produktu', 'inne'}
VALID_REJECT_STATIONS = {'formatting'}  # MVP


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


def reject_product_quantity(
    *,
    product_id: int,
    quantity: int,
    reason_category: str,
    reason_note: str | None,
    rejected_at_station: str,
    user_id: int | None = None,
    device_id: str | None = None,
) -> tuple[ProductionProduct, ProductionProduct, ProductionReworkLog]:
    """
    Wykonuje reject `quantity` sztuk z `product_id` na stanowisku `rejected_at_station`.

    Zwraca: (oryginał_po_update, doróbka, wpis_w_rework_log).
    Cały flow w jednej transakcji z SELECT ... FOR UPDATE na oryginale.

    Raises: RejectError z `code` w {'invalid_quantity', 'invalid_reason',
            'invalid_station', 'product_not_found', 'product_not_in_formatting'}.
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
            f'MVP wspiera tylko: {sorted(VALID_REJECT_STATIONS)}'
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

    if original.current_status not in ('czeka_na_formatowanie', 'w_realizacji'):
        raise RejectError(
            'product_not_in_formatting',
            f'produkt ma status {original.current_status}, oczekiwano czeka_na_formatowanie',
            status=409,
        )

    qty_done_formatting = original.quantity_done_formatting or 0
    available_to_reject = original.quantity - qty_done_formatting
    if quantity > available_to_reject:
        raise RejectError(
            'invalid_quantity',
            f'można cofnąć maksymalnie {available_to_reject} szt. (quantity={original.quantity}, sformatowane={qty_done_formatting})',
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
    # quantity_done_formatting NIE jest ruszany
    original.updated_at = now

    # 2. Utworzenie rekordu doróbki
    rework = ProductionProduct(
        original_product_id=original.id,
        short_product_id=original.short_product_id,
        order_id=original.order_id,
        configuration_id=original.configuration_id,
        # parsed_*
        parsed_wood_species=original.parsed_wood_species,
        parsed_wood_class=original.parsed_wood_class,
        parsed_technology=original.parsed_technology,
        parsed_thickness_cm=original.parsed_thickness_cm,
        parsed_width_cm=original.parsed_width_cm,
        parsed_length_cm=original.parsed_length_cm,
        parsed_finish_type=original.parsed_finish_type,
        parsed_finish_state=original.parsed_finish_state,
        parsed_finish_color_type=original.parsed_finish_color_type,
        parsed_finish_color=original.parsed_finish_color,
        parsed_finish_gloss=original.parsed_finish_gloss,
        parsed_edge_processing=original.parsed_edge_processing,
        parsed_edge_type=original.parsed_edge_type,
        parsed_edge_radius=original.parsed_edge_radius,
        parsed_edge_angle=original.parsed_edge_angle,
        parsed_edge_letters=original.parsed_edge_letters,
        edge_svg=original.edge_svg,
        shape_svg=original.shape_svg,
        lamella_direction=original.lamella_direction,
        quote_item_detail_id=original.quote_item_detail_id,
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
        reason_note=reason_note,
        created_at=now,
        user_id=user_id,
        device_id=device_id,
    )
    db.session.add(log_entry)

    db.session.commit()

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
