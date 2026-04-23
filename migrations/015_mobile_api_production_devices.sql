/* Migracja: Rejestracja urządzeń mobilnych (tablety stanowiskowe).
   Data: 2026-04-23.
   Cel: Tabela ProductionDevice dla API mobile (JWT per-device, rotacja tokenów). */

CREATE TABLE IF NOT EXISTS prod_devices (
    id INT AUTO_INCREMENT PRIMARY KEY,
    device_id VARCHAR(64) NOT NULL UNIQUE COMMENT 'UUID wygenerowany na urządzeniu przy pierwszym starcie',
    device_name VARCHAR(128) DEFAULT NULL COMMENT 'Nazwa nadana przez admina (np. "Tablet Stanowisko 1")',
    station_code VARCHAR(32) NOT NULL COMMENT 'Kod stanowiska: packaging, cutting, assembly, gluing, formatting, finishing',
    token_version INT NOT NULL DEFAULT 1 COMMENT 'Bump = unieważnienie wszystkich istniejących JWT tego urządzenia',
    last_ip VARCHAR(45) DEFAULT NULL COMMENT 'Ostatnie IP z którego urządzenie się łączyło (IPv4 lub IPv6)',
    last_seen_at DATETIME DEFAULT NULL COMMENT 'Ostatnia aktywność urządzenia',
    registered_at DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT 'Data rejestracji',
    app_version VARCHAR(32) DEFAULT NULL COMMENT 'Ostatnia widziana wersja appki (X-App-Version header)',
    is_active BOOLEAN NOT NULL DEFAULT TRUE COMMENT 'FALSE = urządzenie zablokowane (np. zgubione)',
    INDEX idx_device_id (device_id),
    INDEX idx_station_code (station_code),
    INDEX idx_is_active (is_active)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
