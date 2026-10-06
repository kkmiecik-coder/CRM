-- Logistyka etap 4, krok 4.4 (spec 2026-09-30-logistyka-etap-4-weryfikacja-dostawa-design.md, sekcje 5.4, 5.5 i 9):
-- statusy tras załadowana i w trasie, kto i kiedy załadował trasę i ruszył, dostarczenie i „Zostaje” na
-- przystanku, akcje logu Dostawy. Idempotentna: MODIFY enumów jest idempotentny sam z siebie, ALTER dodające
-- kolumny osłonięte warunkiem z information_schema przez PREPARE/EXECUTE (bez zmiany separatora poleceń).

-- Nowe wartości NA KOŃCU listy: MySQL 8 zmienia wtedy same metadane (bez przebudowy tabeli). Stary kod w oknie
-- wdrożenia (migracja idzie przed restartem) tych wartości nie zapisuje, a tras z nimi jeszcze nie ma.
ALTER TABLE prod_routes MODIFY COLUMN status
    ENUM('robocza','zatwierdzona','wykonana','zaladowana','w_trasie')
    CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'robocza';

-- Trasa: kto i kiedy zakończył załadunek i ruszył (telefon kierowcy — pracownik, nie użytkownik panelu).
SET @brak = (SELECT COUNT(*) = 0 FROM information_schema.COLUMNS
             WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'prod_routes' AND COLUMN_NAME = 'loaded_at');
SET @sql = IF(@brak, 'ALTER TABLE prod_routes ADD COLUMN loaded_at DATETIME NULL',
              'SELECT ''loaded_at juz jest'' AS info');
PREPARE krok FROM @sql; EXECUTE krok; DEALLOCATE PREPARE krok;

SET @brak = (SELECT COUNT(*) = 0 FROM information_schema.COLUMNS
             WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'prod_routes' AND COLUMN_NAME = 'loaded_by_worker_id');
SET @sql = IF(@brak, 'ALTER TABLE prod_routes ADD COLUMN loaded_by_worker_id INT NULL',
              'SELECT ''loaded_by_worker_id juz jest'' AS info');
PREPARE krok FROM @sql; EXECUTE krok; DEALLOCATE PREPARE krok;

SET @brak = (SELECT COUNT(*) = 0 FROM information_schema.COLUMNS
             WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'prod_routes' AND COLUMN_NAME = 'departed_at');
SET @sql = IF(@brak, 'ALTER TABLE prod_routes ADD COLUMN departed_at DATETIME NULL',
              'SELECT ''departed_at juz jest'' AS info');
PREPARE krok FROM @sql; EXECUTE krok; DEALLOCATE PREPARE krok;

SET @brak = (SELECT COUNT(*) = 0 FROM information_schema.COLUMNS
             WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'prod_routes' AND COLUMN_NAME = 'departed_by_worker_id');
SET @sql = IF(@brak, 'ALTER TABLE prod_routes ADD COLUMN departed_by_worker_id INT NULL',
              'SELECT ''departed_by_worker_id juz jest'' AS info');
PREPARE krok FROM @sql; EXECUTE krok; DEALLOCATE PREPARE krok;

-- Przystanek: dostarczenie (kto i kiedy) i czasowe „Zostaje” z powodem do zakończenia załadunku.
SET @brak = (SELECT COUNT(*) = 0 FROM information_schema.COLUMNS
             WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'prod_route_stops' AND COLUMN_NAME = 'delivered_at');
SET @sql = IF(@brak, 'ALTER TABLE prod_route_stops ADD COLUMN delivered_at DATETIME NULL',
              'SELECT ''delivered_at juz jest'' AS info');
PREPARE krok FROM @sql; EXECUTE krok; DEALLOCATE PREPARE krok;

SET @brak = (SELECT COUNT(*) = 0 FROM information_schema.COLUMNS
             WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'prod_route_stops' AND COLUMN_NAME = 'delivered_by_worker_id');
SET @sql = IF(@brak, 'ALTER TABLE prod_route_stops ADD COLUMN delivered_by_worker_id INT NULL',
              'SELECT ''delivered_by_worker_id juz jest'' AS info');
PREPARE krok FROM @sql; EXECUTE krok; DEALLOCATE PREPARE krok;

SET @brak = (SELECT COUNT(*) = 0 FROM information_schema.COLUMNS
             WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'prod_route_stops' AND COLUMN_NAME = 'stays_reason');
SET @sql = IF(@brak, 'ALTER TABLE prod_route_stops ADD COLUMN stays_reason VARCHAR(32) NULL',
              'SELECT ''stays_reason juz jest'' AS info');
PREPARE krok FROM @sql; EXECUTE krok; DEALLOCATE PREPARE krok;

SET @brak = (SELECT COUNT(*) = 0 FROM information_schema.COLUMNS
             WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'prod_route_stops' AND COLUMN_NAME = 'stays_note');
SET @sql = IF(@brak, 'ALTER TABLE prod_route_stops ADD COLUMN stays_note VARCHAR(255) NULL',
              'SELECT ''stays_note juz jest'' AS info');
PREPARE krok FROM @sql; EXECUTE krok; DEALLOCATE PREPARE krok;

-- Log logistyki: akcje Dostawy. Lista MUSI zawierać wszystkie dotychczasowe wartości (kroki 4.2 i 4.3) — MODIFY
-- podaje pełną listę, a brakująca wartość skasowałaby akcję wpisom w logu.
ALTER TABLE prod_logistics_log MODIFY action
    ENUM('sposob_dostawy','wydane','przepakowanie',
         'trasa_dodane','trasa_usuniete','trasa_status','adres','paczki',
         'weryfikacja','weryfikacja_cofnieta','problem','problem_rozwiazany','cofniete_do_pakowania',
         'zaladunek','zostaje','wyjazd','dostarczone','niedostarczone','dostarczenie_cofniete')
    COLLATE utf8mb4_unicode_ci NOT NULL;
