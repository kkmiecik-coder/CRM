-- Logistyka równoległa, etap 3: flota, trasy, przystanki. Idempotentna.

CREATE TABLE IF NOT EXISTS prod_vehicles (
    id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    registration VARCHAR(20) NULL,
    capacity_kg INT NULL,
    is_active TINYINT(1) NOT NULL DEFAULT 1,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NULL,
    deactivated_at DATETIME NULL,
    KEY ix_prod_vehicles_is_active (is_active)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS prod_routes (
    id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(120) NOT NULL,
    date_from DATE NOT NULL,
    date_to DATE NOT NULL,
    status ENUM('robocza','zatwierdzona','wykonana') NOT NULL DEFAULT 'robocza',
    vehicle_id INT NULL,
    driver_worker_id INT NULL,
    notes TEXT NULL,
    approved_at DATETIME NULL,
    approved_by INT NULL,
    completed_at DATETIME NULL,
    completed_by INT NULL,
    created_at DATETIME NOT NULL,
    created_by INT NULL,
    updated_at DATETIME NULL,
    geometry_json LONGTEXT NULL,
    distance_km DECIMAL(8,1) NULL,
    duration_min INT NULL,
    geometry_hash CHAR(40) NULL,
    geometry_approx TINYINT(1) NOT NULL DEFAULT 0,
    KEY ix_prod_routes_date_from (date_from),
    KEY ix_prod_routes_date_to (date_to),
    KEY ix_prod_routes_status (status),
    KEY ix_prod_routes_vehicle_id (vehicle_id),
    KEY ix_prod_routes_driver_worker_id (driver_worker_id),
    CONSTRAINT fk_prod_routes_vehicle FOREIGN KEY (vehicle_id)
        REFERENCES prod_vehicles (id) ON DELETE SET NULL,
    CONSTRAINT fk_prod_routes_driver FOREIGN KEY (driver_worker_id)
        REFERENCES prod_workers (id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS prod_route_stops (
    id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    route_id INT NOT NULL,
    order_id INT NOT NULL,
    position INT NOT NULL,
    UNIQUE KEY uq_prod_route_stops_order (order_id),
    KEY ix_prod_route_stops_route_id (route_id),
    CONSTRAINT fk_prod_route_stops_route FOREIGN KEY (route_id)
        REFERENCES prod_routes (id) ON DELETE CASCADE,
    CONSTRAINT fk_prod_route_stops_order FOREIGN KEY (order_id)
        REFERENCES prod_orders (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Blokada „jeden piszący trasy naraz" (fix-1, Ruling A) — patrz routes.zablokuj_trasy().
INSERT IGNORE INTO prod_config (config_key, config_value, config_description, config_type, created_at, updated_at)
VALUES ('logistyka_trasy_blokada', '',
        'Logistyka: blokada zapisow tras (jeden piszacy naraz)', 'string', NOW(), NOW());
