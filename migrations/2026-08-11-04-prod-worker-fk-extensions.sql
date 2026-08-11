/* Migracja: Dopięcie worker_id do istniejących tabel audytowych.
   Data: 2026-08-11
   Projekt: docs/worker-profiles-backend.md, §4.4

   prod_product_events i prod_rework_log to AUDYT, nie statystyka — mają
   pojedynczą kolumnę worker_id. Przy pracy zespołowej zapisujemy pierwszego
   pracownika z nagłówka X-Worker-Ids. Pełna, dzielona atrybucja żyje wyłącznie
   w prod_station_event_workers.

   Idempotentność: ADD COLUMN i ADD INDEX są bezpieczne przy powtórce, bo
   runner migracji świadomie połyka błędy 1060/1061 (migration_service.py,
   execute_sql_migration). Klucze obce już NIE — błąd 1826 "Duplicate foreign
   key constraint name" nie pasuje do żadnego z połykanych wzorców i wywaliłby
   deploy. Dlatego każdy FK jest osłonięty warunkiem na information_schema.
   MODIFY COLUMN jest idempotentny z natury. */

-- ---------------------------------------------------------------------------
-- Naprawa zastanego rozjazdu: model używa source='auto_skip' (models.py, przy
-- pomijaniu stanowisk w complete_task), a ENUM w bazie tej wartości nie zna
-- (020_station_events.sql). W trybie strict MySQL to błąd 1265 przy każdym
-- produkcie nieprzycinanym na wymiar.
-- ---------------------------------------------------------------------------
ALTER TABLE prod_station_events
    MODIFY COLUMN source ENUM('web','mobile','admin','system','auto_skip') NOT NULL DEFAULT 'web';

-- ---------------------------------------------------------------------------
-- prod_product_events: kto wykonał akcję zmieniającą status/priorytet
-- ---------------------------------------------------------------------------
ALTER TABLE prod_product_events
    ADD COLUMN worker_id INT DEFAULT NULL COMMENT 'prod_workers.id — kto wykonał akcję' AFTER user_id;

ALTER TABLE prod_product_events
    ADD INDEX idx_worker_id (worker_id);

ALTER TABLE prod_product_events
    MODIFY COLUMN actor_type ENUM('user','device','system','worker') NOT NULL;

SET @fk_istnieje := (
    SELECT COUNT(*) FROM information_schema.TABLE_CONSTRAINTS
    WHERE CONSTRAINT_SCHEMA = DATABASE()
      AND TABLE_NAME = 'prod_product_events'
      AND CONSTRAINT_NAME = 'fk_product_events_worker'
);
SET @sql := IF(@fk_istnieje = 0,
    'ALTER TABLE prod_product_events ADD CONSTRAINT fk_product_events_worker FOREIGN KEY (worker_id) REFERENCES prod_workers(id) ON DELETE SET NULL',
    'DO 0');
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- ---------------------------------------------------------------------------
-- prod_rework_log: kto zgłosił doróbkę
-- ---------------------------------------------------------------------------
ALTER TABLE prod_rework_log
    ADD COLUMN worker_id INT DEFAULT NULL COMMENT 'prod_workers.id — kto zgłosił doróbkę' AFTER user_id;

ALTER TABLE prod_rework_log
    ADD INDEX idx_worker_id (worker_id);

SET @fk_istnieje := (
    SELECT COUNT(*) FROM information_schema.TABLE_CONSTRAINTS
    WHERE CONSTRAINT_SCHEMA = DATABASE()
      AND TABLE_NAME = 'prod_rework_log'
      AND CONSTRAINT_NAME = 'fk_rework_worker'
);
SET @sql := IF(@fk_istnieje = 0,
    'ALTER TABLE prod_rework_log ADD CONSTRAINT fk_rework_worker FOREIGN KEY (worker_id) REFERENCES prod_workers(id) ON DELETE SET NULL',
    'DO 0');
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- ---------------------------------------------------------------------------
-- prod_devices: kiedy ostatnio ktoś zaczął na tym tablecie sesję
-- (przydatne w monitoringu floty)
-- ---------------------------------------------------------------------------
ALTER TABLE prod_devices
    ADD COLUMN last_worker_session_at DATETIME DEFAULT NULL COMMENT 'Kiedy ostatnio ktoś zaczął tu sesję';
