/* Migracja: Kolejka zadań drukowania etykiet (do print-agenta).
   Data: 2026-04-29.
   Cel: Tabela prod_print_queue — bufor zadań ZPL wstawianych przez CRM
        gdy LABEL_PRINTER_USE_AGENT=True. Print agent na hubie biura
        odpytuje endpoint /api/print-agent/jobs co 5s, pobiera pending
        i drukuje przez TCP do drukarki w LAN. Po sukcesie / błędzie
        wysyła ACK.

        TTL: pending starsze niż 1h są oznaczane jako 'expired' przy
        kolejnym GET /jobs i nigdy nie drukowane. */

CREATE TABLE IF NOT EXISTS prod_print_queue (
    id INT AUTO_INCREMENT PRIMARY KEY,
    short_product_id VARCHAR(20) NOT NULL COMMENT 'ID produktu (informacyjne)',
    baselinker_order_id INT DEFAULT NULL COMMENT 'ID zamówienia BL (informacyjne)',
    zpl_payload MEDIUMTEXT NOT NULL COMMENT 'Pełny ZPL gotowy do wysłania na drukarkę',
    station_code VARCHAR(50) NOT NULL COMMENT 'Stanowisko, z którego zlecono druk',
    requested_by_type VARCHAR(20) NOT NULL COMMENT 'user|device',
    requested_by_id VARCHAR(100) NOT NULL COMMENT 'user_id albo device_id',
    requested_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    status ENUM('pending','printed','failed','expired') NOT NULL DEFAULT 'pending',
    printed_at DATETIME DEFAULT NULL,
    error_message TEXT DEFAULT NULL,
    INDEX idx_status_requested_at (status, requested_at),
    INDEX idx_short_product_id (short_product_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

INSERT INTO prod_config (config_key, config_value, config_type, config_description)
VALUES
    ('LABEL_PRINTER_USE_AGENT', 'false', 'boolean', 'Tryb drukowania: false=bezpośrednio TCP do drukarki (dev), true=przez kolejkę i print-agenta (prod)'),
    ('LABEL_PRINTER_AGENT_TOKEN', 'change-me-in-prod', 'string', 'Token bearer dla print-agenta (Authorization: Bearer ...)')
ON DUPLICATE KEY UPDATE config_key = config_key;
