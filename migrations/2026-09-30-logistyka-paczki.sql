-- Logistyka etap 4, krok 4.2 (spec 2026-09-30-logistyka-etap-4-weryfikacja-dostawa-design.md, sekcje 5.1-5.3
-- i 5.5): paczki zamówienia (paczka albo paleta) z etykietą 100x150 na drukarce 'wysylka'.
-- prod_packages powstaje od razu z kolumnami weryfikacji i załadunku (kroki 4.3-4.4) - dopisywanie ich
-- później wymagałoby osłoniętych ALTER-ów na tabeli, która będzie już pełna. label_delivery_text:
-- napis z pasa sposobu dostawy w chwili druku (ikona „etykiety paczek sprzed zmiany”, decyzja 30.09).
-- Idempotentna: CREATE TABLE IF NOT EXISTS, a ALTER dodające kolumny i klucz obcy osłonięte warunkiem
-- z information_schema przez PREPARE/EXECUTE (bez zmiany separatora poleceń), jak w
-- 2026-09-30-druk-dwie-drukarki.sql.

CREATE TABLE IF NOT EXISTS prod_packages (
    id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    order_id INT NOT NULL,
    seq SMALLINT NOT NULL,
    kind ENUM('paczka','paleta') NOT NULL,
    pallet_type ENUM('eur','niestandardowa') NULL,
    length_cm SMALLINT NULL,
    width_cm SMALLINT NULL,
    declared_at DATETIME NOT NULL,
    declared_by_worker_id INT NULL,
    declared_device_id INT NULL,
    voided_at DATETIME NULL,
    label_printed_at DATETIME NULL,
    label_print_count INT NOT NULL DEFAULT 0,
    label_delivery_text VARCHAR(40) NULL,
    verified_at DATETIME NULL,
    verified_by_worker_id INT NULL,
    verified_method ENUM('skan','reczne') NULL,
    loaded_at DATETIME NULL,
    loaded_by_worker_id INT NULL,
    loaded_method ENUM('skan','reczne') NULL,
    loaded_route_id INT NULL,
    KEY ix_prod_packages_order_id (order_id),
    KEY ix_prod_packages_voided_at (voided_at),
    CONSTRAINT fk_prod_packages_order FOREIGN KEY (order_id)
        REFERENCES prod_orders (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Ostatnia ważna deklaracja paczek zamówienia.
SET @brak = (SELECT COUNT(*) = 0 FROM information_schema.COLUMNS
             WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'prod_orders'
               AND COLUMN_NAME = 'packages_declared_at');
SET @sql = IF(@brak, 'ALTER TABLE prod_orders ADD COLUMN packages_declared_at DATETIME NULL',
              'SELECT ''packages_declared_at juz jest'' AS info');
PREPARE krok FROM @sql; EXECUTE krok; DEALLOCATE PREPARE krok;

-- Log logistyki: akcja 'paczki' oraz pracownik i urządzenie (akcje z tabletów i telefonów
-- nie mają użytkownika panelu). Runner wykonuje plik raz (schema_migrations). Przy ręcznym
-- ponownym uruchomieniu po kroku 4.3 ten MODIFY skurczyłby listę wartości, więc kolejne
-- migracje rozszerzające ENUM muszą zawierać wszystkie wartości (także 'paczki').
ALTER TABLE prod_logistics_log MODIFY action
    ENUM('sposob_dostawy','wydane','przepakowanie',
         'trasa_dodane','trasa_usuniete','trasa_status','adres','paczki') NOT NULL;

SET @brak = (SELECT COUNT(*) = 0 FROM information_schema.COLUMNS
             WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'prod_logistics_log'
               AND COLUMN_NAME = 'worker_id');
SET @sql = IF(@brak, 'ALTER TABLE prod_logistics_log ADD COLUMN worker_id INT NULL',
              'SELECT ''worker_id juz jest'' AS info');
PREPARE krok FROM @sql; EXECUTE krok; DEALLOCATE PREPARE krok;

SET @brak = (SELECT COUNT(*) = 0 FROM information_schema.COLUMNS
             WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'prod_logistics_log'
               AND COLUMN_NAME = 'device_id');
SET @sql = IF(@brak, 'ALTER TABLE prod_logistics_log ADD COLUMN device_id INT NULL',
              'SELECT ''device_id juz jest'' AS info');
PREPARE krok FROM @sql; EXECUTE krok; DEALLOCATE PREPARE krok;

-- Klucz obcy kolejki wydruku do paczki (krok 4.1 dodał samą kolumnę). Osierocone wartości
-- zerujemy najpierw - bez tego ADD CONSTRAINT kończy się błędem 1452.
UPDATE prod_print_queue SET package_id = NULL
WHERE package_id IS NOT NULL AND package_id NOT IN (SELECT id FROM prod_packages);

SET @brak = (SELECT COUNT(*) = 0 FROM information_schema.TABLE_CONSTRAINTS
             WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'prod_print_queue'
               AND CONSTRAINT_NAME = 'fk_prod_print_queue_package');
SET @sql = IF(@brak, 'ALTER TABLE prod_print_queue ADD CONSTRAINT fk_prod_print_queue_package FOREIGN KEY (package_id) REFERENCES prod_packages (id) ON DELETE SET NULL',
              'SELECT ''klucz paczki juz jest'' AS info');
PREPARE krok FROM @sql; EXECUTE krok; DEALLOCATE PREPARE krok;
