-- Stanowisko tabletu „Kierownik hali” (spec 2026-10-19-stanowisko-kierownika-hali-design.md, pkt 2.2 i 2.3):
--  1) prod_workers.is_manager — kierownik hali to wyróżniony pracownik produkcji (jak is_driver kierowcy);
--     ustawia go admin w zakładce Pracownicy. Na start nikt nim nie jest.
--  2) prod_station_desk.sent_by_worker_id — pracownik (kierownik), który wysłał kafel na stół z tabletu;
--     obok sent_by_user_id, którym oznacza się wysyłkę z panelu biura.
-- Kod stanowiska `manager` nie wymaga migracji: prod_devices.station_code to zwykły VARCHAR.
-- Idempotentna (runner wykonuje katalog przy każdym deployu i przy starcie aplikacji).
-- ALTER ADD COLUMN nie ma IF NOT EXISTS, więc warunek z information_schema przez
-- PREPARE/EXECUTE (bez zmiany separatora poleceń), jak w 2026-09-28-logistyka-kierowcy.sql.

SET @brak = (SELECT COUNT(*) = 0 FROM information_schema.COLUMNS
             WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'prod_workers'
               AND COLUMN_NAME = 'is_manager');
SET @sql = IF(@brak, 'ALTER TABLE prod_workers ADD COLUMN is_manager TINYINT(1) NOT NULL DEFAULT 0',
              'SELECT ''is_manager juz jest'' AS info');
PREPARE krok FROM @sql; EXECUTE krok; DEALLOCATE PREPARE krok;

SET @brak = (SELECT COUNT(*) = 0 FROM information_schema.COLUMNS
             WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'prod_station_desk'
               AND COLUMN_NAME = 'sent_by_worker_id');
SET @sql = IF(@brak, 'ALTER TABLE prod_station_desk ADD COLUMN sent_by_worker_id INT NULL',
              'SELECT ''sent_by_worker_id juz jest'' AS info');
PREPARE krok FROM @sql; EXECUTE krok; DEALLOCATE PREPARE krok;
