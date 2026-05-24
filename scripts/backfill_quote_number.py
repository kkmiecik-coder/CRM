"""
Backfill numerów wyceny ze starych notatek (Wycena X - Y) do osobnej kolumny.

Użycie:
    python3 scripts/backfill_quote_number.py --dry-run   # tylko pokaż co by się stało
    python3 scripts/backfill_quote_number.py             # właściwy commit

Idempotentny: filtruje quote_number IS NULL.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from extensions import db
from modules.production.models import ProductionOrder

PATTERN = re.compile(r'^Wycena\s+(\S+?)(?:\s*-\s*(.*))?$', re.DOTALL)
DRY_RUN = '--dry-run' in sys.argv


def main():
    app = create_app()
    with app.app_context():
        orders = ProductionOrder.query.filter(
            ProductionOrder.quote_number.is_(None),
            ProductionOrder.order_notes.isnot(None)
        ).all()

        print(f"Znaleziono {len(orders)} zamówień z order_notes i pustym quote_number")
        if DRY_RUN:
            print("Tryb --dry-run: BRAK commitów do bazy.\n")

        updated = skipped = 0
        for o in orders:
            notes = (o.order_notes or '').strip()
            m = PATTERN.match(notes)
            if not m:
                skipped += 1
                continue
            quote_num = m.group(1).strip()[:16]
            remaining_note = (m.group(2) or '').strip()

            if DRY_RUN:
                print(f"[DRY] BL={o.baselinker_order_id} #{o.internal_order_number}: "
                      f"quote={quote_num!r}, new_notes={remaining_note!r}")
            else:
                o.quote_number = quote_num
                o.order_notes = remaining_note or None
            updated += 1

        if not DRY_RUN:
            db.session.commit()
            print(f"\nUpdated: {updated}, Skipped (brak prefiksu 'Wycena'): {skipped}")
        else:
            print(f"\n[DRY] Would update: {updated}, Skipped (brak prefiksu): {skipped}")


if __name__ == '__main__':
    main()
