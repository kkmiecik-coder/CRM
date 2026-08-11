/* Migracja: Sesje pracy pracowników na stanowiskach.
   Data: 2026-08-11
   Projekt: docs/worker-profiles-backend.md, §4.2

   Jedna sesja = jeden pracownik przy jednym stanowisku. Praca zespołowa na
   jednym tablecie to N sesji z tym samym session_group i device_id — model
   obsługuje to bez dodatkowych kolumn.

   session_group przychodzi Z APKI (UUID generowany lokalnie, bo sesja startuje
   offline i jest kluczem głównym encji w Room). Serwer generuje własny UUID
   wyłącznie dla sesji zakładanych z panelu CRM.

   work_date liczone serwerowo z started_at — doba raportowa nie może zależeć
   od zegara tabletu. */

CREATE TABLE IF NOT EXISTS prod_worker_sessions (
    id               INT AUTO_INCREMENT PRIMARY KEY,
    worker_id        INT          NOT NULL,
    station_code     VARCHAR(32)  NOT NULL,
    device_id        VARCHAR(64)  DEFAULT NULL COMMENT 'prod_devices.device_id',
    session_group    CHAR(36)     NOT NULL COMMENT 'UUID; łączy sesje wystartowane razem (praca zespołowa)',
    started_at       DATETIME     NOT NULL,
    last_activity_at DATETIME     NOT NULL COMMENT 'Odświeżane przy każdej akcji produkcyjnej, nie przy dotknięciu ekranu',
    ended_at         DATETIME     DEFAULT NULL,
    end_reason       ENUM('manual','idle_timeout','night_cutoff','replaced','admin') DEFAULT NULL,
    work_date        DATE         NOT NULL COMMENT 'DATE(started_at) — doba raportowa',
    source           ENUM('mobile','web','admin') NOT NULL DEFAULT 'mobile',
    created_at       DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_worker_date (worker_id, work_date),
    INDEX idx_station_date (station_code, work_date),
    INDEX idx_device_open (device_id, ended_at),
    INDEX idx_open (ended_at),
    INDEX idx_session_group (session_group),
    CONSTRAINT fk_sessions_worker FOREIGN KEY (worker_id) REFERENCES prod_workers(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
