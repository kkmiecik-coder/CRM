-- =========================================================
-- Reject z formatowania: nowa kolumna prod_products.original_product_id
-- + nowa tabela prod_rework_log + reindex short_product_id
-- Uruchomienie: mysql -u <user> -p woodpower_crm_local < scripts/add_rework_columns.sql
-- =========================================================

START TRANSACTION;

-- 1. Dodanie kolumny original_product_id
ALTER TABLE prod_products
  ADD COLUMN original_product_id INT NULL
    COMMENT 'FK do oryginalnego prod_products gdy ten rekord jest doróbką; NULL dla oryginałów'
    AFTER id,
  ADD INDEX ix_prod_products_original_product_id (original_product_id),
  ADD CONSTRAINT fk_prod_products_original
    FOREIGN KEY (original_product_id) REFERENCES prod_products(id)
    ON DELETE SET NULL ON UPDATE CASCADE;

-- 2. Drop unique constraint na short_product_id (zostawiamy zwykły index)
--    UWAGA: nazwa indeksu może być różna; sprawdź SHOW INDEX FROM prod_products
ALTER TABLE prod_products
  DROP INDEX short_product_id;

ALTER TABLE prod_products
  ADD INDEX ix_prod_products_short_product_id (short_product_id);

-- 3. Nowa tabela prod_rework_log
CREATE TABLE prod_rework_log (
  id INT AUTO_INCREMENT PRIMARY KEY,
  original_product_id INT NOT NULL,
  rework_product_id INT NOT NULL,
  quantity INT NOT NULL,
  rejected_at_station ENUM('formatting','finishing','painting') NOT NULL,
  returned_to_station ENUM('cutting','assembly') NOT NULL,
  reason_category ENUM('wymiary','jakosc_sklejenia','jakosc_produktu','inne') NOT NULL,
  reason_note TEXT NULL,
  created_at DATETIME NOT NULL,
  closed_at DATETIME NULL COMMENT 'Kiedy doróbka wróciła do statusu czeka_na_formatowanie',
  user_id INT NULL,
  device_id VARCHAR(64) NULL,
  INDEX ix_rework_log_original (original_product_id, closed_at),
  INDEX ix_rework_log_rework (rework_product_id),
  INDEX ix_rework_log_station_created (rejected_at_station, created_at),
  INDEX ix_rework_log_reason (reason_category),
  CONSTRAINT fk_rework_log_original FOREIGN KEY (original_product_id)
    REFERENCES prod_products(id) ON DELETE CASCADE,
  CONSTRAINT fk_rework_log_rework FOREIGN KEY (rework_product_id)
    REFERENCES prod_products(id) ON DELETE CASCADE,
  CONSTRAINT fk_rework_log_user FOREIGN KEY (user_id)
    REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

COMMIT;
