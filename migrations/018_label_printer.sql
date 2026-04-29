/* Migracja: Drukowanie etykiet produkcyjnych (Xprinter XP-423B, ZPL).
   Data: 2026-04-29.
   Cel: Dodaje kolumny śledzące wydruk etykiet na ProductionItem oraz
        seeduje 7 kluczy konfiguracji drukarki w prod_config (edytowalne
        w ?tab=config). */

ALTER TABLE prod_items
    ADD COLUMN label_printed_at DATETIME NULL
        COMMENT 'Czas ostatniego udanego wydruku etykiety produktu',
    ADD COLUMN label_print_count INT NOT NULL DEFAULT 0
        COMMENT 'Licznik wydruków etykiety dla tego produktu';

INSERT INTO prod_config (config_key, config_value, config_type, config_description)
VALUES
    ('LABEL_PRINTER_IP', '192.168.100.199', 'string', 'Adres IP drukarki etykiet (LAN)'),
    ('LABEL_PRINTER_PORT', '9100', 'integer', 'Port TCP drukarki (raw)'),
    ('LABEL_PRINTER_TIMEOUT_SECONDS', '3', 'integer', 'Timeout pojedynczej próby socketu'),
    ('LABEL_PRINTER_RETRY_COUNT', '1', 'integer', 'Liczba ponowień przy błędzie połączenia'),
    ('LABEL_PRINTER_OFFSET_LT', '-16', 'integer', 'ZPL ^LT — offset pionowy etykiety'),
    ('LABEL_PRINTER_OFFSET_LS', '112', 'integer', 'ZPL ^LS — offset poziomy etykiety (uwaga: dodatnia wartość = w lewo)'),
    ('LABEL_PRINTER_ALLOWED_STATIONS', 'formatowanie,pakowanie', 'string', 'Stanowiska uprawnione do drukowania (CSV)')
ON DUPLICATE KEY UPDATE config_key = config_key;
