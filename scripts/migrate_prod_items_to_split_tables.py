#!/usr/bin/env python3
"""
Migracja danych: prod_items → prod_orders + prod_products + prod_configurations.

UŻYCIE:
    python3 scripts/migrate_prod_items_to_split_tables.py --dry-run   # tylko raport
    python3 scripts/migrate_prod_items_to_split_tables.py --confirm   # właściwa migracja

Skrypt zakłada że:
- prod_items istnieje i ma dane
- Trzy nowe tabele już istnieją (uruchom create_split_tables.sql przed)
- Trzy nowe tabele są puste

Po migracji:
- prod_items zostaje zrenamowane na prod_items_legacy_YYYYMMDD
- Liczniki AUTO_INCREMENT prod_products ustawione na MAX(id)+1
"""

import argparse
import sys
from datetime import datetime
from pathlib import Path

# Setup ścieżek żeby zaimportować app
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app import create_app
from extensions import db
from sqlalchemy import text


def run_migration(dry_run: bool) -> int:
    """Główna funkcja migracji. Zwraca exit code (0=OK, 1=error)."""
    app = create_app()
    with app.app_context():
        conn = db.session.connection()

        # KROK 1: pre-check
        items_count = conn.execute(text("SELECT COUNT(*) FROM prod_items")).scalar()
        configs_count = conn.execute(text("SELECT COUNT(*) FROM prod_configurations")).scalar()
        orders_count = conn.execute(text("SELECT COUNT(*) FROM prod_orders")).scalar()
        products_count = conn.execute(text("SELECT COUNT(*) FROM prod_products")).scalar()

        print(f"[PRE-CHECK]")
        print(f"  prod_items:          {items_count}")
        print(f"  prod_configurations: {configs_count}")
        print(f"  prod_orders:         {orders_count}")
        print(f"  prod_products:       {products_count}")

        if configs_count > 0 or orders_count > 0 or products_count > 0:
            print("ERROR: nowe tabele nie są puste. Przerwane.")
            return 1
        if items_count == 0:
            print("ERROR: prod_items jest puste. Nic do migracji.")
            return 1

        # KROK 2: seed konfiguracji
        print(f"\n[STEP 1/4] Seed prod_configurations")
        conn.execute(text("""
            INSERT INTO prod_configurations (species, technology, wood_class)
            SELECT DISTINCT
              COALESCE(parsed_wood_species, 'unknown'),
              COALESCE(parsed_technology, 'unknown'),
              COALESCE(parsed_wood_class, 'unknown')
            FROM prod_items
        """))
        new_configs = conn.execute(text("SELECT COUNT(*) FROM prod_configurations")).scalar()
        print(f"  → {new_configs} konfiguracji")

        # KROK 3: migracja orderów (z agregacją per BL order)
        print(f"\n[STEP 2/4] Migracja prod_orders")
        conn.execute(text("""
            INSERT INTO prod_orders (
              baselinker_order_id, internal_order_number, baselinker_status_id, payment_date,
              client_order_number, order_notes, client_name, client_email, client_phone,
              delivery_address, delivery_method, delivery_fullname, delivery_company,
              delivery_city, delivery_postcode, delivery_country_code,
              override_delivery_method, logistics_completed_at,
              shipping_package_id, shipping_tracking_number, shipping_courier_name,
              shipping_price, shipping_label_base64, shipping_created_at,
              attachment_file_name, attachment_file_url, sync_source,
              created_at, updated_at
            )
            SELECT
              baselinker_order_id,
              MAX(internal_order_number), MAX(baselinker_status_id), MAX(payment_date),
              MAX(client_order_number), MAX(order_notes), MAX(client_name), MAX(client_email),
              MAX(client_phone), MAX(delivery_address), MAX(delivery_method), MAX(delivery_fullname),
              MAX(delivery_company), MAX(delivery_city), MAX(delivery_postcode), MAX(delivery_country_code),
              MAX(override_delivery_method), MIN(logistics_completed_at),
              MAX(shipping_package_id), MAX(shipping_tracking_number), MAX(shipping_courier_name),
              MAX(shipping_price), MAX(shipping_label_base64), MAX(shipping_created_at),
              MAX(attachment_file_name), MAX(attachment_file_url), MAX(sync_source),
              MIN(created_at), MAX(updated_at)
            FROM prod_items
            GROUP BY baselinker_order_id
        """))
        new_orders = conn.execute(text("SELECT COUNT(*) FROM prod_orders")).scalar()
        print(f"  → {new_orders} zamówień")

        # KROK 4: migracja produktów (zachowane id)
        print(f"\n[STEP 3/4] Migracja prod_products (zachowane id)")
        conn.execute(text("""
            INSERT INTO prod_products (
              id, order_id, configuration_id,
              short_product_id, product_sequence_in_order, baselinker_product_id, original_product_name,
              parsed_length_cm, parsed_width_cm, parsed_thickness_cm,
              parsed_finish_state, parsed_finish_type, parsed_finish_color_type,
              parsed_finish_gloss, parsed_finish_color,
              parsed_edge_processing, cut_to_size,
              parsed_edge_type, parsed_edge_radius, parsed_edge_angle, parsed_edge_letters,
              edge_svg, shape_svg, lamella_direction, quote_item_detail_id, thickness_group,
              volume_m3, unit_price_net, total_value_net, quantity,
              current_status, deadline_date, days_until_deadline,
              priority_rank, priority_manual_override, is_priority,
              quantity_done_cutting, quantity_done_assembly, quantity_done_completion,
              quantity_done_gluing, quantity_done_formatting, quantity_done_finishing,
              quantity_done_painting, quantity_done_packaging,
              cutting_completed_at, assembly_completed_at, completion_completed_at,
              gluing_completed_at, formatting_completed_at, finishing_completed_at,
              painting_completed_at, packaging_completed_at,
              label_printed_at, label_print_count,
              production_notes, quality_issues, created_at, updated_at
            )
            SELECT
              i.id, o.id, c.id,
              i.short_product_id, i.product_sequence_in_order, i.baselinker_product_id, i.original_product_name,
              i.parsed_length_cm, i.parsed_width_cm, i.parsed_thickness_cm,
              i.parsed_finish_state, i.parsed_finish_type, i.parsed_finish_color_type,
              i.parsed_finish_gloss, i.parsed_finish_color,
              i.parsed_edge_processing, i.cut_to_size,
              i.parsed_edge_type, i.parsed_edge_radius, i.parsed_edge_angle, i.parsed_edge_letters,
              i.edge_svg, i.shape_svg, i.lamella_direction, i.quote_item_detail_id, i.thickness_group,
              i.volume_m3, i.unit_price_net, i.total_value_net, i.quantity,
              i.current_status, i.deadline_date, i.days_until_deadline,
              i.priority_rank, i.priority_manual_override, i.is_priority,
              i.quantity_done_cutting, i.quantity_done_assembly, i.quantity_done_completion,
              i.quantity_done_gluing, i.quantity_done_formatting, i.quantity_done_finishing,
              i.quantity_done_painting, i.quantity_done_packaging,
              i.cutting_completed_at, i.assembly_completed_at, i.completion_completed_at,
              i.gluing_completed_at, i.formatting_completed_at, i.finishing_completed_at,
              i.painting_completed_at, i.packaging_completed_at,
              i.label_printed_at, i.label_print_count,
              i.production_notes, i.quality_issues, i.created_at, i.updated_at
            FROM prod_items i
            JOIN prod_orders o ON o.baselinker_order_id = i.baselinker_order_id
            JOIN prod_configurations c
              ON c.species    = COALESCE(i.parsed_wood_species, 'unknown')
             AND c.technology = COALESCE(i.parsed_technology, 'unknown')
             AND c.wood_class = COALESCE(i.parsed_wood_class, 'unknown')
        """))
        new_products = conn.execute(text("SELECT COUNT(*) FROM prod_products")).scalar()
        print(f"  → {new_products} produktów")

        # KROK 5: weryfikacja
        print(f"\n[STEP 4/4] Weryfikacja")
        assert new_products == items_count, f"MISMATCH: products {new_products} vs items {items_count}"

        max_id = conn.execute(text("SELECT MAX(id) FROM prod_products")).scalar()
        # AUTO_INCREMENT jest DDL — ustawiamy tylko przy --confirm (DDL powoduje implicit COMMIT w MySQL)
        print(f"  AUTO_INCREMENT prod_products → {max_id + 1}")

        # FK sanity
        orphan_orders = conn.execute(text("""
            SELECT COUNT(*) FROM prod_products p
            LEFT JOIN prod_orders o ON o.id = p.order_id
            WHERE o.id IS NULL
        """)).scalar()
        orphan_configs = conn.execute(text("""
            SELECT COUNT(*) FROM prod_products p
            WHERE p.configuration_id IS NOT NULL AND p.configuration_id NOT IN (SELECT id FROM prod_configurations)
        """)).scalar()
        assert orphan_orders == 0, f"Orphan products bez order: {orphan_orders}"
        assert orphan_configs == 0, f"Orphan products bez config: {orphan_configs}"
        print(f"  FK sanity: OK (0 orphans)")

        if dry_run:
            # Uwaga: ALTER TABLE (DDL) w MySQL powoduje implicit COMMIT — pomijamy w dry-run
            print(f"\n[DRY RUN] Rollback transakcji — nic nie zapisane.")
            db.session.rollback()
            # Wyczyść tabele ręcznie po dry-run (MySQL DDL nie pozwala na rollback)
            conn2 = db.session.connection()
            conn2.execute(text("SET FOREIGN_KEY_CHECKS=0"))
            conn2.execute(text("DELETE FROM prod_products"))
            conn2.execute(text("DELETE FROM prod_orders"))
            conn2.execute(text("DELETE FROM prod_configurations"))
            conn2.execute(text("SET FOREIGN_KEY_CHECKS=1"))
            db.session.commit()
            print(f"  (tabele wyczyszczone po dry-run)")
            return 0

        # KROK 6: ustaw AUTO_INCREMENT + rename prod_items → prod_items_legacy_YYYYMMDD
        conn.execute(text(f"ALTER TABLE prod_products AUTO_INCREMENT = {max_id + 1}"))
        suffix = datetime.now().strftime("%Y%m%d")
        legacy_name = f"prod_items_legacy_{suffix}"

        # Drop dangling FK first (z prod_errors, prod_station_events do prod_items)
        # bo po renamie one wskazywałyby na legacy
        conn.execute(text("SET FOREIGN_KEY_CHECKS=0"))
        try:
            conn.execute(text("ALTER TABLE prod_errors DROP FOREIGN KEY prod_errors_ibfk_1"))
        except Exception:
            pass  # może nie istnieć
        try:
            conn.execute(text("ALTER TABLE prod_station_events DROP FOREIGN KEY prod_station_events_ibfk_1"))
        except Exception:
            pass

        conn.execute(text(f"RENAME TABLE prod_items TO {legacy_name}"))

        # przepiąć FK na prod_products
        conn.execute(text("""
            ALTER TABLE prod_errors
            ADD CONSTRAINT prod_errors_ibfk_1
            FOREIGN KEY (related_product_id) REFERENCES prod_products(id)
        """))
        conn.execute(text("""
            ALTER TABLE prod_station_events
            ADD CONSTRAINT prod_station_events_ibfk_1
            FOREIGN KEY (production_item_id) REFERENCES prod_products(id) ON DELETE CASCADE
        """))
        conn.execute(text("SET FOREIGN_KEY_CHECKS=1"))

        db.session.commit()
        print(f"\n[DONE] prod_items → {legacy_name}")
        print(f"  Konfiguracje: {new_configs}")
        print(f"  Zamówienia:   {new_orders}")
        print(f"  Produkty:     {new_products}")
        return 0


def main():
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true", help="Tylko raport, ROLLBACK")
    group.add_argument("--confirm", action="store_true", help="Właściwa migracja z COMMIT")
    args = parser.parse_args()

    sys.exit(run_migration(dry_run=args.dry_run))


if __name__ == "__main__":
    main()
