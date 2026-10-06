-- Logistyka równoległa, runda 2 (spec 2026-09-28-logistyka-runda-2-uwagi-design.md, pkt 2.6):
-- kierowca trasy = wyróżniony pracownik produkcji (prod_workers.is_driver). Na start nikt
-- nie jest kierowcą — logistyk dodaje kierowców w zakładce Logistyka, podzakładka Flota.
-- Idempotentna (runner wykonuje katalog przy każdym deployu i przy starcie aplikacji).
-- ALTER ADD COLUMN nie ma IF NOT EXISTS, więc warunek z information_schema przez
-- PREPARE/EXECUTE (bez zmiany separatora poleceń), jak w 2026-09-26-logistyka-zmiana-adresu.sql.

SET @brak = (SELECT COUNT(*) = 0 FROM information_schema.COLUMNS
             WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'prod_workers'
               AND COLUMN_NAME = 'is_driver');
SET @sql = IF(@brak, 'ALTER TABLE prod_workers ADD COLUMN is_driver TINYINT(1) NOT NULL DEFAULT 0',
              'SELECT ''is_driver juz jest'' AS info');
PREPARE krok FROM @sql; EXECUTE krok; DEALLOCATE PREPARE krok;
