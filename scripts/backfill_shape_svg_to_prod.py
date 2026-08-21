#!/usr/bin/env python3
"""
Backfill shape_svg dla prod_products które mają NULL ale ich wycena ma SVG.

Użycie:
    python3 scripts/backfill_shape_svg_to_prod.py            # dry-run
    python3 scripts/backfill_shape_svg_to_prod.py --apply    # zapisz zmiany
"""
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app import create_app
from extensions import db
from modules.production.models import ProductionOrder, ProductionProduct
from modules.calculator.models import Quote, QuoteItemDetails


def main():
    apply_changes = '--apply' in sys.argv

    app = create_app()
    with app.app_context():
        products = (
            db.session.query(ProductionProduct, ProductionOrder)
            .join(ProductionOrder, ProductionProduct.order_id == ProductionOrder.id)
            .filter(ProductionProduct.shape_svg.is_(None))
            .filter(ProductionProduct.baselinker_product_id.isnot(None))
            .all()
        )

        print(f"[backfill] kandydatów: {len(products)}")

        matched = 0
        updated = 0
        no_quote = 0
        no_detail = 0
        no_svg = 0

        for pp, po in products:
            quote = Quote.query.filter_by(
                base_linker_order_id=str(po.baselinker_order_id)
            ).first()

            if not quote:
                no_quote += 1
                continue

            try:
                bl_product_id = int(pp.baselinker_product_id)
            except (TypeError, ValueError):
                no_detail += 1
                continue

            detail = QuoteItemDetails.query.filter_by(
                quote_id=quote.id,
                baselinker_order_product_id=bl_product_id
            ).first()

            if not detail:
                no_detail += 1
                continue

            matched += 1

            if not detail.shape_svg:
                no_svg += 1
                continue

            print(f"  [match] pp.id={pp.id} short={pp.short_product_id} "
                  f"← qid={detail.id} (svg {len(detail.shape_svg)}B, "
                  f"rotation={detail.shape_rotation})")

            if apply_changes:
                pp.shape_svg = detail.shape_svg
                if detail.shape_rotation is not None:
                    pp.shape_rotation = detail.shape_rotation
                pp.quote_item_detail_id = detail.id
                updated += 1

        if apply_changes:
            db.session.commit()
            print(f"\n[backfill] APPLIED — updated {updated} produktów")
        else:
            print(f"\n[backfill] DRY-RUN — bez --apply nic nie zapisano")

        print(f"  matched detail: {matched}")
        print(f"  brak quote (sklepowe?): {no_quote}")
        print(f"  brak detail w quote:    {no_detail}")
        print(f"  detail bez shape_svg:   {no_svg}")


if __name__ == '__main__':
    main()
