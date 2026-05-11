-- ROLLBACK: usuwa nowe tabele i przywraca prod_items z legacy.
-- UŻYWAĆ TYLKO gdy migracja się zepsuła i nowy kod nie działa.
-- Wymaga że prod_items_legacy_YYYYMMDD istnieje (przekaż przez --batch i zmienną).
-- Wywołanie:
--   /Applications/XAMPP/xamppfiles/bin/mysql -u root woodpower_crm_local \
--     -e "SET @legacy='prod_items_legacy_20260511'; SOURCE scripts/rollback_split_tables.sql;"

SET FOREIGN_KEY_CHECKS=0;

-- usuń FK z prod_errors/prod_station_events do prod_products (powstałe po migracji)
ALTER TABLE prod_errors DROP FOREIGN KEY prod_errors_ibfk_1;
ALTER TABLE prod_station_events DROP FOREIGN KEY prod_station_events_ibfk_1;

-- przywróć prod_items z legacy (UWAGA: @legacy musi być ustawione)
SET @sql = CONCAT('RENAME TABLE ', @legacy, ' TO prod_items');
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- przywróć FK do prod_items
ALTER TABLE prod_errors
  ADD CONSTRAINT prod_errors_ibfk_1 FOREIGN KEY (related_product_id) REFERENCES prod_items(id);
ALTER TABLE prod_station_events
  ADD CONSTRAINT prod_station_events_ibfk_1 FOREIGN KEY (production_item_id) REFERENCES prod_items(id) ON DELETE CASCADE;

-- drop nowych tabel
DROP TABLE prod_products;
DROP TABLE prod_orders;
DROP TABLE prod_configurations;

SET FOREIGN_KEY_CHECKS=1;

SELECT 'Rollback wykonany' AS status;
