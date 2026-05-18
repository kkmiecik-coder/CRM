"""
Backfill parsed_edges_groups dla istniejących prod_products.

Re-parsuje nazwy produktów przez aktualny parser i wypełnia nowe pole.
Bezpieczne do wielokrotnego uruchomienia (UPDATE tylko gdy pole NULL).

Użycie:
    python3 scripts/backfill_edges_groups.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from extensions import db
from modules.production.models import ProductionProduct
from modules.production.services.parser_service import ProductNameParser


def main():
    app = create_app()
    with app.app_context():
        parser = ProductNameParser()
        products = ProductionProduct.query.filter(ProductionProduct.parsed_edges_groups.is_(None)).all()
        print(f"Znaleziono {len(products)} produktów do backfillu")

        updated = 0
        for p in products:
            if not p.original_product_name:
                continue
            parsed = parser.parse_product_name(p.original_product_name)
            groups = parsed.get('edges_groups', [])
            if groups:
                p.parsed_edges_groups = groups
                updated += 1
                if updated % 100 == 0:
                    db.session.commit()
                    print(f"  ... {updated} zaktualizowanych")

        db.session.commit()
        print(f"Zakończono: {updated} produktów zaktualizowanych")


if __name__ == '__main__':
    main()
