"""
Smoke test rejectu lokalnie. Tworzy produkt testowy, wykonuje reject częściowy
i reject całości, weryfikuje stan oryginału i doróbki.

Uruchomienie: venv/bin/python3 scripts/smoke_test_rework.py

Skrypt sprząta po sobie (DELETE w finally).
"""
import os
import sys

# Dodaj root projektu do sys.path (skrypt uruchamiany jako `python3 scripts/...`)
_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from app import create_app
from extensions import db
from modules.production.models import (
    ProductionProduct,
    ProductionOrder,
    ProductionConfiguration,
    ProductionReworkLog,
    get_local_now,
)
from modules.production.services.rework_service import reject_product_quantity, RejectError


SMOKE_BL_ORDER_ID = 999999
SMOKE_INTERNAL_NO = 'SMOKE/REWORK'


def make_test_order_and_product(quantity=5, formatting_done=2, technology='lite'):
    cfg = ProductionConfiguration.find_or_create(
        species='dab', technology=technology, wood_class='A/B'
    )

    order = ProductionOrder(
        baselinker_order_id=SMOKE_BL_ORDER_ID,
        internal_order_number=SMOKE_INTERNAL_NO,
        client_name='SMOKE TEST',
    )
    db.session.add(order)
    db.session.flush()

    product = ProductionProduct(
        short_product_id='99999_99',
        order_id=order.id,
        configuration_id=cfg.id,
        product_sequence_in_order=1,
        original_product_name='SMOKE TEST PRODUCT',
        parsed_finish_type='surowe',
        parsed_edge_processing=False,
        cut_to_size=True,
        quantity=quantity,
        current_status='czeka_na_formatowanie',
        cutting_completed_at=None,
        assembly_completed_at=get_local_now(),  # przeszedł przez assembly
        quantity_done_assembly=quantity,
        quantity_done_completion=quantity,
        quantity_done_gluing=quantity,
        quantity_done_formatting=formatting_done,
        created_at=get_local_now(),
    )
    db.session.add(product)
    db.session.commit()
    return order, product


def cleanup(order_id):
    """Usuń doróbki, log, oryginały i zamówienie po teście."""
    # Jeśli poprzedni krok zostawił sesję w stanie błędu, rollback najpierw
    try:
        db.session.rollback()
    except Exception:
        pass
    product_ids = [pid for (pid,) in db.session.query(ProductionProduct.id).filter_by(order_id=order_id).all()]
    if product_ids:
        ProductionReworkLog.query.filter(
            ProductionReworkLog.original_product_id.in_(product_ids)
        ).delete(synchronize_session=False)
    # Najpierw rekordy z original_product_id (doróbki), potem oryginały
    ProductionProduct.query.filter(
        ProductionProduct.order_id == order_id,
        ProductionProduct.original_product_id.isnot(None),
    ).delete(synchronize_session=False)
    ProductionProduct.query.filter_by(order_id=order_id).delete(synchronize_session=False)
    ProductionOrder.query.filter_by(id=order_id).delete(synchronize_session=False)
    db.session.commit()


def cleanup_stale():
    """Wyczyść pozostałości z poprzedniego runa (gdyby skrypt się wywalił)."""
    stale = ProductionOrder.query.filter_by(baselinker_order_id=SMOKE_BL_ORDER_ID).all()
    for o in stale:
        cleanup(o.id)


def main():
    app = create_app()
    with app.app_context():
        cleanup_stale()

        # === Scenariusz 1: reject częściowy (1 z 5) ===
        order, product = make_test_order_and_product(quantity=5, formatting_done=2, technology='lite')
        order_id = order.id
        product_id = product.id

        try:
            original, rework, log = reject_product_quantity(
                product_id=product_id,
                quantity=1,
                reason_category='wymiary',
                reason_note='smoke test',
                rejected_at_station='formatting',
                device_id='SMOKE',
            )
            assert original.quantity == 4, f"oryginał quantity {original.quantity}, oczekiwano 4"
            assert original.current_status == 'czeka_na_formatowanie', f"status {original.current_status}"
            assert original.quantity_done_gluing == 5, "gluing licznik nieruszony"
            assert rework.quantity == 1
            assert rework.original_product_id == original.id
            assert rework.current_status == 'czeka_na_skladanie', f"rework status {rework.current_status}"  # assembly_completed_at → assembly
            assert rework.short_product_id == original.short_product_id
            assert rework.is_priority
            assert rework.priority_rank == 1
            assert log.quantity == 1
            assert log.reason_category == 'wymiary'
            assert log.returned_to_station == 'assembly'
            assert log.closed_at is None
            print("OK Reject czesciowy")
        finally:
            cleanup(order_id)

        # === Scenariusz 2: reject całości (3 z 3) ===
        order, product = make_test_order_and_product(quantity=3, formatting_done=0, technology='lite')
        order_id = order.id
        product_id = product.id

        try:
            original, rework, log = reject_product_quantity(
                product_id=product_id,
                quantity=3,
                reason_category='jakosc_sklejenia',
                reason_note=None,
                rejected_at_station='formatting',
                device_id='SMOKE',
            )
            assert original.quantity == 0
            assert original.current_status == 'anulowane', f"status {original.current_status}"
            assert rework.quantity == 3
            print("OK Reject calosci (oryginal anulowany)")
        finally:
            cleanup(order_id)

        # === Scenariusz 3: błąd — quantity > available ===
        order, product = make_test_order_and_product(quantity=5, formatting_done=2, technology='lite')
        order_id = order.id
        product_id = product.id

        try:
            try:
                reject_product_quantity(
                    product_id=product_id,
                    quantity=4,  # ale dostępne jest tylko 3 (5-2)
                    reason_category='wymiary',
                    reason_note=None,
                    rejected_at_station='formatting',
                    device_id='SMOKE',
                )
                raise AssertionError('Powinien byc blad invalid_quantity')
            except RejectError as e:
                assert e.code == 'invalid_quantity', f"oczekiwano invalid_quantity, dostalem {e.code}"
                print("OK Walidacja quantity > available")
        finally:
            cleanup(order_id)

        print("\n=== ALL SMOKE TESTS PASSED ===")


if __name__ == '__main__':
    main()
