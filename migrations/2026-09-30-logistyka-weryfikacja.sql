-- Logistyka etap 4, krok 4.3 (spec 2026-09-30-logistyka-etap-4-weryfikacja-dostawa-design.md, sekcje 4, 5.3,
-- 5.5 i 8): statusy pozycji po spakowaniu, kolumny weryfikacji, problemu i banera przepakowania na
-- zamówieniu, akcje logu Weryfikacji, indeks paczek po (zamówienie, unieważnienie) i chwila startu listy
-- „Do weryfikacji”. Idempotentna: MODIFY enumów jest idempotentny sam z siebie, ALTER dodające kolumny i
-- zmieniające indeksy osłonięte warunkiem z information_schema przez PREPARE/EXECUTE (bez zmiany
-- separatora poleceń), wiersz konfiguracji przez INSERT IGNORE, przepisanie wydanych - warunkiem na status.

-- Nowe wartości NA KOŃCU listy: MySQL 8 zmienia wtedy same metadane (bez przebudowy tabeli). Zestaw
-- znaków i porównywanie jak w bazie produkcyjnej (kolumna ma je jawnie w SHOW CREATE TABLE).
ALTER TABLE prod_products MODIFY COLUMN current_status ENUM(
    'czeka_na_wyciecie','czeka_na_skladanie','czeka_na_sklejanie',
    'czeka_na_formatowanie','czeka_na_krawedzie','czeka_na_lakiernie',
    'czeka_na_logistyke','czeka_na_pakowanie',
    'spakowane','anulowane','wstrzymane','w_realizacji',
    'zweryfikowane','zaladowane','dostarczone'
) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'czeka_na_wyciecie';

-- Zamówienie zweryfikowane (kto i kiedy), zgłoszony problem (NULL = brak) i tekst banera przepakowania
-- na tablecie pakowania (uzupełnia repack_required).
SET @brak = (SELECT COUNT(*) = 0 FROM information_schema.COLUMNS
             WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'prod_orders' AND COLUMN_NAME = 'verified_at');
SET @sql = IF(@brak, 'ALTER TABLE prod_orders ADD COLUMN verified_at DATETIME NULL',
              'SELECT "verified_at juz jest" AS info');
PREPARE krok FROM @sql; EXECUTE krok; DEALLOCATE PREPARE krok;

SET @brak = (SELECT COUNT(*) = 0 FROM information_schema.COLUMNS
             WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'prod_orders' AND COLUMN_NAME = 'verified_by_worker_id');
SET @sql = IF(@brak, 'ALTER TABLE prod_orders ADD COLUMN verified_by_worker_id INT NULL',
              'SELECT "verified_by_worker_id juz jest" AS info');
PREPARE krok FROM @sql; EXECUTE krok; DEALLOCATE PREPARE krok;

SET @brak = (SELECT COUNT(*) = 0 FROM information_schema.COLUMNS
             WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'prod_orders' AND COLUMN_NAME = 'problem_reason');
SET @sql = IF(@brak, 'ALTER TABLE prod_orders ADD COLUMN problem_reason VARCHAR(32) NULL',
              'SELECT "problem_reason juz jest" AS info');
PREPARE krok FROM @sql; EXECUTE krok; DEALLOCATE PREPARE krok;

SET @brak = (SELECT COUNT(*) = 0 FROM information_schema.COLUMNS
             WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'prod_orders' AND COLUMN_NAME = 'problem_note');
SET @sql = IF(@brak, 'ALTER TABLE prod_orders ADD COLUMN problem_note VARCHAR(255) NULL',
              'SELECT "problem_note juz jest" AS info');
PREPARE krok FROM @sql; EXECUTE krok; DEALLOCATE PREPARE krok;

SET @brak = (SELECT COUNT(*) = 0 FROM information_schema.COLUMNS
             WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'prod_orders' AND COLUMN_NAME = 'problem_at');
SET @sql = IF(@brak, 'ALTER TABLE prod_orders ADD COLUMN problem_at DATETIME NULL',
              'SELECT "problem_at juz jest" AS info');
PREPARE krok FROM @sql; EXECUTE krok; DEALLOCATE PREPARE krok;

SET @brak = (SELECT COUNT(*) = 0 FROM information_schema.COLUMNS
             WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'prod_orders' AND COLUMN_NAME = 'problem_by_worker_id');
SET @sql = IF(@brak, 'ALTER TABLE prod_orders ADD COLUMN problem_by_worker_id INT NULL',
              'SELECT "problem_by_worker_id juz jest" AS info');
PREPARE krok FROM @sql; EXECUTE krok; DEALLOCATE PREPARE krok;

SET @brak = (SELECT COUNT(*) = 0 FROM information_schema.COLUMNS
             WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'prod_orders' AND COLUMN_NAME = 'repack_reason');
SET @sql = IF(@brak, 'ALTER TABLE prod_orders ADD COLUMN repack_reason VARCHAR(255) NULL',
              'SELECT "repack_reason juz jest" AS info');
PREPARE krok FROM @sql; EXECUTE krok; DEALLOCATE PREPARE krok;

-- Log logistyki: akcje Weryfikacji. Lista MUSI zawierać wszystkie dotychczasowe wartości (także 'paczki'
-- z kroku 4.2) - MODIFY podaje pełną listę, a brakująca wartość skasowałaby akcję wpisom w logu.
ALTER TABLE prod_logistics_log MODIFY action
    ENUM('sposob_dostawy','wydane','przepakowanie',
         'trasa_dodane','trasa_usuniete','trasa_status','adres','paczki',
         'weryfikacja','weryfikacja_cofnieta','problem','problem_rozwiazany','cofniete_do_pakowania')
    COLLATE utf8mb4_unicode_ci NOT NULL;

-- Paczki czytamy zawsze po zamówieniu i unieważnieniu (aktualna deklaracja = voided_at IS NULL).
-- Nowy indeks zastępuje osobny indeks po voided_at, który nie ma żadnych zapytań.
SET @brak = (SELECT COUNT(*) = 0 FROM information_schema.STATISTICS
             WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'prod_packages'
               AND INDEX_NAME = 'ix_prod_packages_order_voided');
SET @sql = IF(@brak, 'ALTER TABLE prod_packages ADD INDEX ix_prod_packages_order_voided (order_id, voided_at)',
              'SELECT "ix_prod_packages_order_voided juz jest" AS info');
PREPARE krok FROM @sql; EXECUTE krok; DEALLOCATE PREPARE krok;

SET @jest = (SELECT COUNT(*) > 0 FROM information_schema.STATISTICS
             WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'prod_packages'
               AND INDEX_NAME = 'ix_prod_packages_voided_at');
SET @sql = IF(@jest, 'ALTER TABLE prod_packages DROP INDEX ix_prod_packages_voided_at',
              'SELECT "ix_prod_packages_voided_at juz usuniety" AS info');
PREPARE krok FROM @sql; EXECUTE krok; DEALLOCATE PREPARE krok;

-- Lista „Do weryfikacji” (decyzja Konrada 30.09): zamówienia zamknięte w Logistyce (kurier) trafiają na nią
-- tylko, gdy spakowano je w ostatnich 7 dniach i nie wcześniej niż wdrożenie tego kroku. INSERT IGNORE:
-- pierwsze wykonanie zapisuje chwilę wdrożenia, kolejne jej nie ruszają.
INSERT IGNORE INTO prod_config (config_key, config_value, config_description, config_type, created_at, updated_at)
VALUES ('logistyka_weryfikacja_od', CAST(NOW() AS CHAR),
        'Logistyka: lista Do weryfikacji obejmuje zamówienia spakowane od tej chwili (wdrożenie kroku 4.3)',
        'string', NOW(), NOW());

-- „Wydane klientowi” od kroku 4.3 ustawia pozycje na 'dostarczone' - zamówienia wydane wcześniej dostają
-- ten sam stan. Zwykły UPDATE omija audyt prod_product_events (listener działa tylko w ORM) - świadomie:
-- to przepisanie historii, nie czyjaś praca.
UPDATE prod_products p
  JOIN prod_orders o ON o.id = p.order_id
   SET p.current_status = 'dostarczone'
 WHERE o.handed_over_at IS NOT NULL AND p.current_status = 'spakowane';
