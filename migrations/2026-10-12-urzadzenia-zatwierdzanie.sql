-- Urządzenia mobilne — dostęp po zatwierdzeniu (spec 2026-10-12-urzadzenia-mobilne-zatwierdzanie-design.md, 3.2).
-- Idempotentna: kolumny i indeks osłonięte warunkiem z information_schema przez PREPARE/EXECUTE (wzór:
-- 2026-10-05-priorytety-produkcji.sql), UPDATE-y z warunkami, które po pierwszym wykonaniu nie trafiają w nic.
-- Migracja nie wydaje tokenów i nie zmienia wersji tokenów — działające urządzenia nie zauważają wdrożenia.

-- 3.1 status: dodanie z domyślnym 'zatwierdzone' nadaje ten status wszystkim istniejącym wierszom.
SET @brak = (SELECT COUNT(*) = 0 FROM information_schema.COLUMNS
             WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'prod_devices' AND COLUMN_NAME = 'status');
SET @sql = IF(@brak, 'ALTER TABLE prod_devices ADD COLUMN status VARCHAR(16) NOT NULL DEFAULT ''zatwierdzone''',
              'SELECT ''status juz jest'' AS info');
PREPARE krok FROM @sql; EXECUTE krok; DEALLOCATE PREPARE krok;

SET @brak = (SELECT COUNT(*) = 0 FROM information_schema.COLUMNS
             WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'prod_devices' AND COLUMN_NAME = 'mac_address');
SET @sql = IF(@brak, 'ALTER TABLE prod_devices ADD COLUMN mac_address CHAR(17) NULL',
              'SELECT ''mac_address juz jest'' AS info');
PREPARE krok FROM @sql; EXECUTE krok; DEALLOCATE PREPARE krok;

SET @brak = (SELECT COUNT(*) = 0 FROM information_schema.COLUMNS
             WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'prod_devices' AND COLUMN_NAME = 'mac_conflict');
SET @sql = IF(@brak, 'ALTER TABLE prod_devices ADD COLUMN mac_conflict CHAR(17) NULL',
              'SELECT ''mac_conflict juz jest'' AS info');
PREPARE krok FROM @sql; EXECUTE krok; DEALLOCATE PREPARE krok;

SET @brak = (SELECT COUNT(*) = 0 FROM information_schema.COLUMNS
             WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'prod_devices' AND COLUMN_NAME = 'device_model');
SET @sql = IF(@brak, 'ALTER TABLE prod_devices ADD COLUMN device_model VARCHAR(64) NULL',
              'SELECT ''device_model juz jest'' AS info');
PREPARE krok FROM @sql; EXECUTE krok; DEALLOCATE PREPARE krok;

SET @brak = (SELECT COUNT(*) = 0 FROM information_schema.COLUMNS
             WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'prod_devices' AND COLUMN_NAME = 'requested_at');
SET @sql = IF(@brak, 'ALTER TABLE prod_devices ADD COLUMN requested_at DATETIME NULL',
              'SELECT ''requested_at juz jest'' AS info');
PREPARE krok FROM @sql; EXECUTE krok; DEALLOCATE PREPARE krok;

SET @brak = (SELECT COUNT(*) = 0 FROM information_schema.COLUMNS
             WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'prod_devices' AND COLUMN_NAME = 'approved_at');
SET @sql = IF(@brak, 'ALTER TABLE prod_devices ADD COLUMN approved_at DATETIME NULL',
              'SELECT ''approved_at juz jest'' AS info');
PREPARE krok FROM @sql; EXECUTE krok; DEALLOCATE PREPARE krok;

SET @brak = (SELECT COUNT(*) = 0 FROM information_schema.COLUMNS
             WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'prod_devices' AND COLUMN_NAME = 'approved_by');
SET @sql = IF(@brak, 'ALTER TABLE prod_devices ADD COLUMN approved_by INT NULL',
              'SELECT ''approved_by juz jest'' AS info');
PREPARE krok FROM @sql; EXECUTE krok; DEALLOCATE PREPARE krok;

SET @brak = (SELECT COUNT(*) = 0 FROM information_schema.COLUMNS
             WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'prod_devices' AND COLUMN_NAME = 'blocked_at');
SET @sql = IF(@brak, 'ALTER TABLE prod_devices ADD COLUMN blocked_at DATETIME NULL',
              'SELECT ''blocked_at juz jest'' AS info');
PREPARE krok FROM @sql; EXECUTE krok; DEALLOCATE PREPARE krok;

SET @brak = (SELECT COUNT(*) = 0 FROM information_schema.COLUMNS
             WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'prod_devices' AND COLUMN_NAME = 'blocked_by');
SET @sql = IF(@brak, 'ALTER TABLE prod_devices ADD COLUMN blocked_by INT NULL',
              'SELECT ''blocked_by juz jest'' AS info');
PREPARE krok FROM @sql; EXECUTE krok; DEALLOCATE PREPARE krok;

SET @brak = (SELECT COUNT(*) = 0 FROM information_schema.STATISTICS
             WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'prod_devices'
               AND INDEX_NAME = 'ix_prod_devices_mac_address');
SET @sql = IF(@brak, 'ALTER TABLE prod_devices ADD INDEX ix_prod_devices_mac_address (mac_address)',
              'SELECT ''ix_prod_devices_mac_address juz jest'' AS info');
PREPARE krok FROM @sql; EXECUTE krok; DEALLOCATE PREPARE krok;

-- 3.2 p.3: wpisy sprzed zmiany są zatwierdzone od chwili rejestracji (panel odróżnia dzięki temu odrzuconą prośbę
-- od zablokowanego urządzenia). Nowe wiersze mają requested_at, więc ponowne wykonanie ich nie dotyka.
UPDATE prod_devices SET approved_at = registered_at WHERE approved_at IS NULL AND requested_at IS NULL;

-- 3.2 p.4: nieaktywne urządzenia stają się zablokowanymi. Nowy kod nigdy nie zostawia 'zatwierdzone' z is_active = 0.
UPDATE prod_devices SET status = 'zablokowane', blocked_at = COALESCE(blocked_at, NOW())
WHERE is_active = 0 AND status = 'zatwierdzone';
