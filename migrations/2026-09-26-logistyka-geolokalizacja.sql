-- Logistyka równoległa, etap 2: współrzędne adresów dostawy.
-- Idempotentna (runner wykonuje katalog przy każdym deployu).

CREATE TABLE IF NOT EXISTS prod_order_geo (
    order_id INT NOT NULL PRIMARY KEY,
    lat DECIMAL(9,6) NULL,
    lng DECIMAL(9,6) NULL,
    source ENUM('gugik','nominatim','reczna') NULL,
    quality ENUM('dokladna','przyblizona','nie_znaleziono') NOT NULL,
    address_hash CHAR(40) NOT NULL,
    address_changed_after_manual TINYINT(1) NOT NULL DEFAULT 0,
    attempts INT NOT NULL DEFAULT 0,
    updated_at DATETIME NULL,
    CONSTRAINT fk_prod_order_geo_order FOREIGN KEY (order_id)
        REFERENCES prod_orders (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Dzierżawa „jeden geokoder na serwer" (Nominatim: 1 zapytanie/s).
INSERT IGNORE INTO prod_config (config_key, config_value, config_description, config_type, created_at, updated_at)
VALUES ('logistyka_geo_dzierzawa', '1970-01-01T00:00:00',
        'Logistyka: dzierzawa geokodera (waznosc ISO)', 'string', NOW(), NOW());

-- Postęp trwającego przebiegu geokodera dla przycisku „Zlokalizuj teraz” ('' = nic nie biegnie).
INSERT IGNORE INTO prod_config (config_key, config_value, config_description, config_type, created_at, updated_at)
VALUES ('logistyka_geo_postep', '',
        'Logistyka: postęp geokodera (JSON)', 'string', NOW(), NOW());
