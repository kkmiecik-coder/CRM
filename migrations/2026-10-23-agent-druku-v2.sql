-- Agent druku v2 (schemat): rejestr agentów, konfiguracja z historią zmian, polecenia (kalibracja),
-- wydania agenta oraz rozszerzenie kolejki druku o dzierżawę zadań i nowe statusy.
-- Idempotentna: CREATE TABLE IF NOT EXISTS, a ALTER przez information_schema + PREPARE/EXECUTE
-- (bez DELIMITER), jak w 2026-10-19-kierownik-hali.sql.
-- Uwaga wdrożeniowa: nowe wartości ENUM (claimed, sending, unknown, cancelled) zapisuje tylko nowy kod.
-- Wycofanie po ich zapisaniu wymaga migracji cofającej je na pending/failed — stary kod rzuciłby
-- LookupError na listach.

CREATE TABLE IF NOT EXISTS prod_print_agents (
    id INT NOT NULL AUTO_INCREMENT,
    name VARCHAR(100) NOT NULL,
    token_sha256 CHAR(64) NOT NULL,
    created_at DATETIME NOT NULL,
    created_by_user_id INT NULL,
    revoked_at DATETIME NULL,
    last_seen_at DATETIME NULL,
    version VARCHAR(40) NULL,
    printers_state TEXT NULL,
    push_connected TINYINT(1) NOT NULL DEFAULT 0,
    PRIMARY KEY (id),
    UNIQUE KEY uq_prod_print_agents_token (token_sha256)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS prod_print_agent_config (
    agent_id INT NOT NULL,
    version INT NOT NULL DEFAULT 1,
    data TEXT NOT NULL,
    updated_at DATETIME NOT NULL,
    updated_source ENUM('crm','agent') NOT NULL DEFAULT 'crm',
    updated_by VARCHAR(100) NULL,
    PRIMARY KEY (agent_id),
    CONSTRAINT fk_prod_print_agent_config_agent FOREIGN KEY (agent_id)
        REFERENCES prod_print_agents (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS prod_print_agent_config_changes (
    id INT NOT NULL AUTO_INCREMENT,
    agent_id INT NOT NULL,
    version INT NOT NULL,
    base_version INT NULL,
    source ENUM('crm','agent') NOT NULL,
    actor VARCHAR(100) NULL,
    data_before TEXT NULL,
    data_after TEXT NULL,
    overwrote_version INT NULL,
    created_at DATETIME NOT NULL,
    PRIMARY KEY (id),
    KEY ix_prod_print_agent_config_changes_agent (agent_id, id),
    CONSTRAINT fk_prod_print_agent_config_changes_agent FOREIGN KEY (agent_id)
        REFERENCES prod_print_agents (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS prod_print_agent_commands (
    id INT NOT NULL AUTO_INCREMENT,
    agent_id INT NOT NULL,
    kind ENUM('kalibracja') NOT NULL,
    printer VARCHAR(20) NOT NULL,
    status ENUM('pending','done','failed') NOT NULL DEFAULT 'pending',
    result TEXT NULL,
    created_by_user_id INT NULL,
    created_at DATETIME NOT NULL,
    done_at DATETIME NULL,
    PRIMARY KEY (id),
    KEY ix_prod_print_agent_commands_agent_status (agent_id, status),
    CONSTRAINT fk_prod_print_agent_commands_agent FOREIGN KEY (agent_id)
        REFERENCES prod_print_agents (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS prod_print_agent_releases (
    id INT NOT NULL AUTO_INCREMENT,
    version_name VARCHAR(20) NOT NULL,
    file_path VARCHAR(500) NOT NULL,
    file_size_bytes BIGINT NOT NULL,
    sha256 VARCHAR(64) NOT NULL,
    release_notes TEXT NULL,
    uploaded_at DATETIME NOT NULL,
    uploaded_by_user_id INT NULL,
    is_active TINYINT(1) NOT NULL DEFAULT 1,
    PRIMARY KEY (id),
    UNIQUE KEY uq_prod_print_agent_releases_version (version_name),
    KEY ix_prod_print_agent_releases_active (is_active)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Kolejka druku: dzierżawa zadania przez agenta i powiązanie ponowienia z oryginałem.
SET @brak = (SELECT COUNT(*) = 0 FROM information_schema.COLUMNS
             WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'prod_print_queue'
               AND COLUMN_NAME = 'claimed_by_agent_id');
SET @sql = IF(@brak, 'ALTER TABLE prod_print_queue ADD COLUMN claimed_by_agent_id INT NULL',
              'SELECT ''claimed_by_agent_id juz jest'' AS info');
PREPARE krok FROM @sql; EXECUTE krok; DEALLOCATE PREPARE krok;

SET @brak = (SELECT COUNT(*) = 0 FROM information_schema.COLUMNS
             WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'prod_print_queue'
               AND COLUMN_NAME = 'lease_until');
SET @sql = IF(@brak, 'ALTER TABLE prod_print_queue ADD COLUMN lease_until DATETIME(3) NULL',
              'SELECT ''lease_until juz jest'' AS info');
PREPARE krok FROM @sql; EXECUTE krok; DEALLOCATE PREPARE krok;

SET @brak = (SELECT COUNT(*) = 0 FROM information_schema.COLUMNS
             WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'prod_print_queue'
               AND COLUMN_NAME = 'sending_at');
SET @sql = IF(@brak, 'ALTER TABLE prod_print_queue ADD COLUMN sending_at DATETIME(3) NULL',
              'SELECT ''sending_at juz jest'' AS info');
PREPARE krok FROM @sql; EXECUTE krok; DEALLOCATE PREPARE krok;

SET @brak = (SELECT COUNT(*) = 0 FROM information_schema.COLUMNS
             WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'prod_print_queue'
               AND COLUMN_NAME = 'reprint_of_job_id');
SET @sql = IF(@brak, 'ALTER TABLE prod_print_queue ADD COLUMN reprint_of_job_id INT NULL',
              'SELECT ''reprint_of_job_id juz jest'' AS info');
PREPARE krok FROM @sql; EXECUTE krok; DEALLOCATE PREPARE krok;

-- ENUM statusu: rozszerzamy tylko gdy brakuje nowych wartości (MODIFY przepisuje tabelę).
SET @brak = (SELECT COUNT(*) > 0 FROM information_schema.COLUMNS
             WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'prod_print_queue'
               AND COLUMN_NAME = 'status' AND COLUMN_TYPE NOT LIKE '%''cancelled''%');
SET @sql = IF(@brak,
              'ALTER TABLE prod_print_queue MODIFY status ENUM(''pending'',''claimed'',''sending'',''printed'',''failed'',''expired'',''unknown'',''cancelled'') NOT NULL DEFAULT ''pending''',
              'SELECT ''status ENUM juz rozszerzony'' AS info');
PREPARE krok FROM @sql; EXECUTE krok; DEALLOCATE PREPARE krok;
