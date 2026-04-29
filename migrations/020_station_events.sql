/* Migracja: Log zdarzeń stanowiskowych.
   Data: 2026-04-29.
   Cel: Tabela prod_station_events — każda zmiana quantity_done_<station>
        (zarówno + jak i -) tworzy rekord. Pozwala odpowiedzieć
        "co stanowisko X zrobiło dnia Y" niezależnie od bieżącego stanu pozycji.
        Historia zaczyna się od wdrożenia tabeli (bez backfillu). */

CREATE TABLE IF NOT EXISTS prod_station_events (
    id INT AUTO_INCREMENT PRIMARY KEY,
    production_item_id INT NOT NULL,
    station_code VARCHAR(32) NOT NULL COMMENT 'cutting, assembly, gluing, formatting, finishing, painting, packaging',
    delta INT NOT NULL COMMENT 'Zmiana wartości quantity_done (+/-)',
    quantity_done_after INT NOT NULL COMMENT 'Stan quantity_done_<station> po operacji',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    user_id INT DEFAULT NULL,
    device_id VARCHAR(64) DEFAULT NULL COMMENT 'prod_devices.device_id (gdy mobile)',
    source ENUM('web', 'mobile', 'admin', 'system') NOT NULL DEFAULT 'web',
    INDEX idx_item_id (production_item_id),
    INDEX idx_station_code (station_code),
    INDEX idx_created_at (created_at),
    INDEX idx_user_id (user_id),
    INDEX idx_device_id (device_id),
    INDEX idx_source (source),
    INDEX idx_station_date (station_code, created_at),
    CONSTRAINT fk_station_events_item
        FOREIGN KEY (production_item_id) REFERENCES prod_items(id) ON DELETE CASCADE,
    CONSTRAINT fk_station_events_user
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
