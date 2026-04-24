/* Migracja: Idempotency dla Mobile API (offline queue retry).
   Data: 2026-04-24.
   Cel: Tabela processed_mobile_operations przechowująca response (2xx/4xx) dla
   każdego operation_id — retry z tym samym X-Operation-Id zwraca zapisany
   response zamiast wykonywać akcję drugi raz. 5xx NIE zapisywane (klient retry). */

CREATE TABLE IF NOT EXISTS processed_mobile_operations (
    operation_id VARCHAR(64) NOT NULL PRIMARY KEY COMMENT 'UUID wygenerowany na urządzeniu (X-Operation-Id header)',
    endpoint VARCHAR(64) NOT NULL COMMENT 'Flask endpoint name, np. mobile_api.order_complete',
    order_id INT DEFAULT NULL COMMENT 'ID zlecenia którego dotyczy akcja (FK luźne — bez constraint)',
    device_id VARCHAR(64) DEFAULT NULL COMMENT 'device_id urządzenia wywołującego (z JWT claims)',
    response_status INT NOT NULL COMMENT 'HTTP status zwrócony klientowi (2xx lub 4xx)',
    response_body LONGTEXT NOT NULL COMMENT 'Zapisany JSON response body — retry zwraca to samo',
    processed_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT 'Timestamp pierwszego przetworzenia',
    INDEX idx_processed_at (processed_at),
    INDEX idx_device_id (device_id),
    INDEX idx_endpoint (endpoint)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
