-- Logistyka etap 4, krok 4.4b, U10 (decyzja Konrada 2.10, Ruling 32 w specu 2026-09-30-logistyka-etap-4-weryfikacja-
-- dostawa-design.md, sekcja 9.8): „Niedostarczone” zostaje na przystanku do końca trasy — kto, kiedy, powód i notatka
-- na przystanku; akcja logu „Cofnij niedostarczenie”; indeks route_id w logu (historia niedostarczonych zdjętych
-- z trasy). Idempotentna: ALTER dodające kolumny i indeks osłonięte warunkiem z information_schema przez
-- PREPARE/EXECUTE (bez zmiany separatora poleceń), MODIFY enuma jest idempotentny sam z siebie.

-- Przystanek: niedostarczenie (ADD COLUMN na końcu tabeli — w MySQL 8 bez przebudowy tabeli).
SET @brak = (SELECT COUNT(*) = 0 FROM information_schema.COLUMNS
             WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'prod_route_stops' AND COLUMN_NAME = 'not_delivered_at');
SET @sql = IF(@brak, 'ALTER TABLE prod_route_stops ADD COLUMN not_delivered_at DATETIME NULL',
              'SELECT "not_delivered_at juz jest" AS info');
PREPARE krok FROM @sql; EXECUTE krok; DEALLOCATE PREPARE krok;

SET @brak = (SELECT COUNT(*) = 0 FROM information_schema.COLUMNS
             WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'prod_route_stops' AND COLUMN_NAME = 'not_delivered_reason');
SET @sql = IF(@brak, 'ALTER TABLE prod_route_stops ADD COLUMN not_delivered_reason VARCHAR(32) NULL',
              'SELECT "not_delivered_reason juz jest" AS info');
PREPARE krok FROM @sql; EXECUTE krok; DEALLOCATE PREPARE krok;

SET @brak = (SELECT COUNT(*) = 0 FROM information_schema.COLUMNS
             WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'prod_route_stops' AND COLUMN_NAME = 'not_delivered_note');
SET @sql = IF(@brak, 'ALTER TABLE prod_route_stops ADD COLUMN not_delivered_note VARCHAR(255) NULL',
              'SELECT "not_delivered_note juz jest" AS info');
PREPARE krok FROM @sql; EXECUTE krok; DEALLOCATE PREPARE krok;

SET @brak = (SELECT COUNT(*) = 0 FROM information_schema.COLUMNS
             WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'prod_route_stops'
               AND COLUMN_NAME = 'not_delivered_by_worker_id');
SET @sql = IF(@brak, 'ALTER TABLE prod_route_stops ADD COLUMN not_delivered_by_worker_id INT NULL',
              'SELECT "not_delivered_by_worker_id juz jest" AS info');
PREPARE krok FROM @sql; EXECUTE krok; DEALLOCATE PREPARE krok;

-- Log: indeks trasy (dodanie indeksu InnoDB idzie online, bez blokady zapisów).
SET @brak = (SELECT COUNT(*) = 0 FROM information_schema.STATISTICS
             WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'prod_logistics_log'
               AND INDEX_NAME = 'ix_prod_logistics_log_route_id');
SET @sql = IF(@brak, 'ALTER TABLE prod_logistics_log ADD INDEX ix_prod_logistics_log_route_id (route_id)',
              'SELECT "ix_prod_logistics_log_route_id juz jest" AS info');
PREPARE krok FROM @sql; EXECUTE krok; DEALLOCATE PREPARE krok;

-- Log: akcja „Cofnij niedostarczenie” NA KOŃCU listy (same metadane). Lista MUSI zawierać wszystkie dotychczasowe
-- wartości — MODIFY podaje pełną listę, a brakująca wartość skasowałaby akcję wpisom w logu.
ALTER TABLE prod_logistics_log MODIFY action
    ENUM('sposob_dostawy','wydane','przepakowanie',
         'trasa_dodane','trasa_usuniete','trasa_status','adres','paczki',
         'weryfikacja','weryfikacja_cofnieta','problem','problem_rozwiazany','cofniete_do_pakowania',
         'zaladunek','zostaje','wyjazd','dostarczone','niedostarczone','dostarczenie_cofniete',
         'niedostarczenie_cofniete')
    COLLATE utf8mb4_unicode_ci NOT NULL;
