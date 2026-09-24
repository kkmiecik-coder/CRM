-- Logistyka równoległa, etap 1 (spec 2026-09-24-logistyka-rownolegla-trasy-design.md).
-- Idempotentna: runner (migrations/migration_service.py) uruchamia katalog przy
-- każdym deployu. ALTER nie ma IF NOT EXISTS, więc warunek składamy
-- z information_schema i wykonujemy przez PREPARE/EXECUTE (składnia delimitera nie działa).

SET @brak = (SELECT COUNT(*) = 0 FROM information_schema.COLUMNS
             WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'prod_orders'
               AND COLUMN_NAME = 'delivery_method_set_at');
SET @sql = IF(@brak, 'ALTER TABLE prod_orders ADD COLUMN delivery_method_set_at DATETIME NULL',
              'SELECT "delivery_method_set_at juz jest" AS info');
PREPARE krok FROM @sql; EXECUTE krok; DEALLOCATE PREPARE krok;

SET @brak = (SELECT COUNT(*) = 0 FROM information_schema.COLUMNS
             WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'prod_orders'
               AND COLUMN_NAME = 'delivery_method_set_by');
SET @sql = IF(@brak, 'ALTER TABLE prod_orders ADD COLUMN delivery_method_set_by INT NULL',
              'SELECT "delivery_method_set_by juz jest" AS info');
PREPARE krok FROM @sql; EXECUTE krok; DEALLOCATE PREPARE krok;

SET @brak = (SELECT COUNT(*) = 0 FROM information_schema.COLUMNS
             WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'prod_orders'
               AND COLUMN_NAME = 'handed_over_at');
SET @sql = IF(@brak, 'ALTER TABLE prod_orders ADD COLUMN handed_over_at DATETIME NULL',
              'SELECT "handed_over_at juz jest" AS info');
PREPARE krok FROM @sql; EXECUTE krok; DEALLOCATE PREPARE krok;

SET @brak = (SELECT COUNT(*) = 0 FROM information_schema.COLUMNS
             WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'prod_orders'
               AND COLUMN_NAME = 'handed_over_by');
SET @sql = IF(@brak, 'ALTER TABLE prod_orders ADD COLUMN handed_over_by INT NULL',
              'SELECT "handed_over_by juz jest" AS info');
PREPARE krok FROM @sql; EXECUTE krok; DEALLOCATE PREPARE krok;

SET @brak = (SELECT COUNT(*) = 0 FROM information_schema.COLUMNS
             WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'prod_orders'
               AND COLUMN_NAME = 'repack_required');
SET @sql = IF(@brak, 'ALTER TABLE prod_orders ADD COLUMN repack_required TINYINT(1) NOT NULL DEFAULT 0',
              'SELECT "repack_required juz jest" AS info');
PREPARE krok FROM @sql; EXECUTE krok; DEALLOCATE PREPARE krok;

SET @brak = (SELECT COUNT(*) = 0 FROM information_schema.COLUMNS
             WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'prod_orders'
               AND COLUMN_NAME = 'logistics_closed_at');
SET @sql = IF(@brak, 'ALTER TABLE prod_orders ADD COLUMN logistics_closed_at DATETIME NULL',
              'SELECT "logistics_closed_at juz jest" AS info');
PREPARE krok FROM @sql; EXECUTE krok; DEALLOCATE PREPARE krok;

SET @brak = (SELECT COUNT(*) = 0 FROM information_schema.COLUMNS
             WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'prod_orders'
               AND COLUMN_NAME = 'bl_delivery_method_pending');
SET @sql = IF(@brak, 'ALTER TABLE prod_orders ADD COLUMN bl_delivery_method_pending TINYINT(1) NOT NULL DEFAULT 0',
              'SELECT "bl_delivery_method_pending juz jest" AS info');
PREPARE krok FROM @sql; EXECUTE krok; DEALLOCATE PREPARE krok;

SET @brak = (SELECT COUNT(*) = 0 FROM information_schema.COLUMNS
             WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'prod_orders'
               AND COLUMN_NAME = 'bl_status_pending_id');
SET @sql = IF(@brak, 'ALTER TABLE prod_orders ADD COLUMN bl_status_pending_id INT NULL',
              'SELECT "bl_status_pending_id juz jest" AS info');
PREPARE krok FROM @sql; EXECUTE krok; DEALLOCATE PREPARE krok;

SET @brak = (SELECT COUNT(*) = 0 FROM information_schema.STATISTICS
             WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'prod_orders'
               AND INDEX_NAME = 'ix_prod_orders_logistics_closed_at');
SET @sql = IF(@brak, 'CREATE INDEX ix_prod_orders_logistics_closed_at ON prod_orders (logistics_closed_at)',
              'SELECT "indeks juz jest" AS info');
PREPARE krok FROM @sql; EXECUTE krok; DEALLOCATE PREPARE krok;

CREATE TABLE IF NOT EXISTS prod_logistics_log (
    id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    order_id INT NOT NULL,
    action ENUM('sposob_dostawy','wydane','przepakowanie',
                'trasa_dodane','trasa_usuniete','trasa_status') NOT NULL,
    old_value VARCHAR(64) NULL,
    new_value VARCHAR(64) NULL,
    route_id INT NULL,
    user_id INT NULL,
    note VARCHAR(255) NULL,
    created_at DATETIME NOT NULL,
    KEY ix_prod_logistics_log_order_id (order_id),
    KEY ix_prod_logistics_log_user_id (user_id),
    KEY ix_prod_logistics_log_created_at (created_at),
    CONSTRAINT fk_prod_logistics_log_order FOREIGN KEY (order_id)
        REFERENCES prod_orders (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Stan wysyłki do Base.: dzierżawa jednego nadawcy i pauza po limicie API.
INSERT IGNORE INTO prod_config (config_key, config_value, config_description, config_type, created_at, updated_at)
VALUES ('logistyka_bl_dzierzawa', '1970-01-01T00:00:00',
        'Logistyka: dzierzawa nadawcy do Base. (waznosc ISO)', 'string', NOW(), NOW()),
       ('logistyka_bl_wstrzymane_do', '1970-01-01T00:00:00',
        'Logistyka: wysylki do Base. wstrzymane do (ISO) po limicie API', 'string', NOW(), NOW());

-- Logistyka przestaje być etapem pipeline'u. Wartość zostaje w ENUM do osobnego
-- sprzątania — między tą migracją a restartem stary kod może ją jeszcze zapisać.
UPDATE prod_products SET current_status = 'czeka_na_pakowanie'
WHERE current_status = 'czeka_na_logistyke';

-- Historia: zamówienia w całości spakowane/anulowane przed wdrożeniem kończą cykl
-- logistyczny, inaczej zalałyby widok (np. ~100 zamówień transport_woodpower
-- z kwietnia–czerwca). Odbiór osobisty nie istnieje jeszcze jako wartość, więc
-- warunek na odbior_osobisty chroni jedynie przed ponownym przebiegiem po wdrożeniu.
UPDATE prod_orders o SET o.logistics_closed_at = NOW()
WHERE o.logistics_closed_at IS NULL
  AND (o.override_delivery_method IS NULL OR o.override_delivery_method <> 'odbior_osobisty')
  AND NOT EXISTS (SELECT 1 FROM prod_products p
                  WHERE p.order_id = o.id
                    AND p.current_status NOT IN ('spakowane', 'anulowane'));
