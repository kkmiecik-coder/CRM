-- Logistyka etap 4, krok 4.1 (spec 2026-09-30-logistyka-etap-4-weryfikacja-dostawa-design.md, sekcja 5.1):
-- kolejka wydruku zna drukarkę. 'etykiety' = dotychczasowa drukarka 60x40 (domyślna, więc stare
-- wiersze i stary kod działają bez zmian), 'wysylka' = drukarka etykiet paczek 100x150 przy pakowaniu.
-- package_id: paczka, której dotyczy etykieta (tabela prod_packages powstaje w kroku 4.2 — klucz obcy
-- dojdzie wtedy). Indeks (printer, status): agent pyta o zadania 'pending' jednej drukarki.
-- Idempotentna: ALTER nie ma IF NOT EXISTS, więc warunek z information_schema przez
-- PREPARE/EXECUTE (bez zmiany separatora poleceń), jak w 2026-09-28-logistyka-kierowcy.sql.

SET @brak = (SELECT COUNT(*) = 0 FROM information_schema.COLUMNS
             WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'prod_print_queue'
               AND COLUMN_NAME = 'printer');
SET @sql = IF(@brak, 'ALTER TABLE prod_print_queue ADD COLUMN printer VARCHAR(20) NOT NULL DEFAULT ''etykiety''',
              'SELECT "printer juz jest" AS info');
PREPARE krok FROM @sql; EXECUTE krok; DEALLOCATE PREPARE krok;

SET @brak = (SELECT COUNT(*) = 0 FROM information_schema.COLUMNS
             WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'prod_print_queue'
               AND COLUMN_NAME = 'package_id');
SET @sql = IF(@brak, 'ALTER TABLE prod_print_queue ADD COLUMN package_id INT NULL',
              'SELECT "package_id juz jest" AS info');
PREPARE krok FROM @sql; EXECUTE krok; DEALLOCATE PREPARE krok;

SET @brak = (SELECT COUNT(*) = 0 FROM information_schema.STATISTICS
             WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'prod_print_queue'
               AND INDEX_NAME = 'ix_prod_print_queue_printer_status');
SET @sql = IF(@brak, 'ALTER TABLE prod_print_queue ADD INDEX ix_prod_print_queue_printer_status (printer, status)',
              'SELECT "indeks drukarki juz jest" AS info');
PREPARE krok FROM @sql; EXECUTE krok; DEALLOCATE PREPARE krok;
