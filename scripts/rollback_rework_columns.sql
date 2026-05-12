-- =========================================================
-- Rollback dla add_rework_columns.sql
-- Uwaga: jeśli w prod_products istnieją rekordy z original_product_id NOT NULL,
-- najpierw usuń je ręcznie (DELETE FROM prod_products WHERE original_product_id IS NOT NULL).
-- =========================================================

START TRANSACTION;

DROP TABLE IF EXISTS prod_rework_log;

ALTER TABLE prod_products
  DROP FOREIGN KEY fk_prod_products_original,
  DROP INDEX ix_prod_products_original_product_id,
  DROP COLUMN original_product_id;

ALTER TABLE prod_products
  DROP INDEX ix_prod_products_short_product_id;

ALTER TABLE prod_products
  ADD UNIQUE INDEX short_product_id (short_product_id);

COMMIT;
