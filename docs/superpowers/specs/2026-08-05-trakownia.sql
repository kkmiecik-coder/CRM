-- Trakownia — schemat rejestru cięcia kłód.
-- Wykonać RĘCZNIE w phpMyAdmin PRZED deployem kodu.
-- Wszystkie tabele: InnoDB, utf8mb4_unicode_ci.

CREATE TABLE `prod_sawmill_suppliers` (
  `id` INT NOT NULL AUTO_INCREMENT,
  `name` VARCHAR(200) NOT NULL,
  `nip` VARCHAR(20) DEFAULT NULL,
  `address_street` VARCHAR(200) DEFAULT NULL,
  `address_zip` VARCHAR(12) DEFAULT NULL,
  `address_city` VARCHAR(120) DEFAULT NULL,
  `contact_person` VARCHAR(120) DEFAULT NULL,
  `phone` VARCHAR(40) DEFAULT NULL,
  `email` VARCHAR(160) DEFAULT NULL,
  `notes` TEXT,
  `is_active` TINYINT(1) NOT NULL DEFAULT 1,
  `created_by_user_id` INT DEFAULT NULL,
  `created_at` DATETIME NOT NULL,
  `updated_at` DATETIME DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_sawmill_supplier_name` (`name`),
  KEY `ix_sawmill_supplier_active` (`is_active`),
  CONSTRAINT `fk_sawmill_supplier_created_by_user`
    FOREIGN KEY (`created_by_user_id`) REFERENCES `users` (`id`) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE `prod_sawmill_species` (
  `id` INT NOT NULL AUTO_INCREMENT,
  `name` VARCHAR(80) NOT NULL,
  `short_code` VARCHAR(8) DEFAULT NULL,
  `sort_order` INT NOT NULL DEFAULT 0,
  `is_active` TINYINT(1) NOT NULL DEFAULT 1,
  `created_at` DATETIME NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_sawmill_species_name` (`name`),
  KEY `ix_sawmill_species_active` (`is_active`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE `prod_sawmill_counters` (
  `year` SMALLINT NOT NULL,
  `last_number` INT NOT NULL DEFAULT 0,
  PRIMARY KEY (`year`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE `prod_sawmill_deliveries` (
  `id` INT NOT NULL AUTO_INCREMENT,
  `supplier_id` INT NOT NULL,
  `invoice_number` VARCHAR(64) DEFAULT NULL,
  `invoice_date` DATE DEFAULT NULL,
  `delivery_date` DATE NOT NULL,
  `notes` TEXT,
  `created_by_user_id` INT DEFAULT NULL,
  `created_at` DATETIME NOT NULL,
  `updated_at` DATETIME DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `ix_sawmill_delivery_supplier` (`supplier_id`),
  KEY `ix_sawmill_delivery_invoice` (`invoice_number`),
  KEY `ix_sawmill_delivery_date` (`delivery_date`),
  CONSTRAINT `fk_sawmill_delivery_supplier`
    FOREIGN KEY (`supplier_id`) REFERENCES `prod_sawmill_suppliers` (`id`),
  CONSTRAINT `fk_sawmill_delivery_created_by_user`
    FOREIGN KEY (`created_by_user_id`) REFERENCES `users` (`id`) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE `prod_sawmill_orders` (
  `id` INT NOT NULL AUTO_INCREMENT,
  `order_number` VARCHAR(24) NOT NULL,
  `delivery_id` INT NOT NULL,
  `species_id` INT NOT NULL,
  `declared_volume_m3` DECIMAL(10,3) NOT NULL,
  `declared_logs_count` INT DEFAULT NULL,
  `price_per_m3` DECIMAL(10,2) DEFAULT NULL,
  `declared_value` DECIMAL(12,2) DEFAULT NULL,
  `agreed_volume_m3` DECIMAL(10,3) DEFAULT NULL,
  `status` VARCHAR(16) NOT NULL DEFAULT 'new',
  `notes` TEXT,
  `settlement_notes` TEXT,
  `started_at` DATETIME DEFAULT NULL,
  `completed_at` DATETIME DEFAULT NULL,
  `completed_by_device` VARCHAR(64) DEFAULT NULL,
  `settled_at` DATETIME DEFAULT NULL,
  `settled_by_user_id` INT DEFAULT NULL,
  `created_by_user_id` INT DEFAULT NULL,
  `created_at` DATETIME NOT NULL,
  `updated_at` DATETIME DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_sawmill_order_number` (`order_number`),
  KEY `ix_sawmill_order_delivery` (`delivery_id`),
  KEY `ix_sawmill_order_species` (`species_id`),
  KEY `ix_sawmill_order_status` (`status`),
  CONSTRAINT `fk_sawmill_order_delivery`
    FOREIGN KEY (`delivery_id`) REFERENCES `prod_sawmill_deliveries` (`id`),
  CONSTRAINT `fk_sawmill_order_species`
    FOREIGN KEY (`species_id`) REFERENCES `prod_sawmill_species` (`id`),
  CONSTRAINT `fk_sawmill_order_settled_by_user`
    FOREIGN KEY (`settled_by_user_id`) REFERENCES `users` (`id`) ON DELETE SET NULL,
  CONSTRAINT `fk_sawmill_order_created_by_user`
    FOREIGN KEY (`created_by_user_id`) REFERENCES `users` (`id`) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE `prod_sawmill_logs` (
  `id` INT NOT NULL AUTO_INCREMENT,
  `order_id` INT NOT NULL,
  `sequence_no` INT NOT NULL,
  -- Obwód w połowie długości kłody — jedyny pomiar przekroju (metoda Hubera).
  `mid_circumference_cm` DECIMAL(6,1) NOT NULL,
  `length_cm` DECIMAL(6,1) NOT NULL,
  `volume_m3` DECIMAL(12,6) NOT NULL,
  `device_id` VARCHAR(64) DEFAULT NULL,
  `measured_at` DATETIME NOT NULL,
  `created_at` DATETIME NOT NULL,
  `updated_at` DATETIME DEFAULT NULL,
  `is_deleted` TINYINT(1) NOT NULL DEFAULT 0,
  `deleted_at` DATETIME DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_sawmill_log_seq` (`order_id`, `sequence_no`),
  KEY `ix_sawmill_log_order_active` (`order_id`, `is_deleted`),
  KEY `ix_sawmill_log_device` (`device_id`),
  CONSTRAINT `fk_sawmill_log_order`
    FOREIGN KEY (`order_id`) REFERENCES `prod_sawmill_orders` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- order_id BEZ klucza obcego: wpisy muszą przeżyć usunięcie zlecenia,
-- inaczej akcja order_delete nie miałaby gdzie się zapisać.
CREATE TABLE `prod_sawmill_audit` (
  `id` BIGINT NOT NULL AUTO_INCREMENT,
  `order_id` INT NOT NULL,
  `log_id` INT DEFAULT NULL,
  `action` VARCHAR(24) NOT NULL,
  `before_json` TEXT,
  `after_json` TEXT,
  `device_id` VARCHAR(64) DEFAULT NULL,
  `user_id` INT DEFAULT NULL,
  `created_at` DATETIME NOT NULL,
  PRIMARY KEY (`id`),
  KEY `ix_sawmill_audit_order` (`order_id`),
  KEY `ix_sawmill_audit_created` (`created_at`),
  CONSTRAINT `fk_sawmill_audit_user`
    FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ── Seed ────────────────────────────────────────────────────────────────────
INSERT INTO `prod_sawmill_species` (`name`, `short_code`, `sort_order`, `is_active`, `created_at`)
VALUES
  ('Dąb',    'DB', 10, 1, NOW()),
  ('Jesion', 'JS', 20, 1, NOW()),
  ('Buk',    'BK', 30, 1, NOW());

-- decimal_places jest STAŁĄ zgodną ze schematem DECIMAL(x,1), nie ustawieniem.
-- Zmiana precyzji wymaga ALTER TABLE, nie edycji tej wartości.
INSERT INTO `prod_config` (`config_key`, `config_value`, `config_description`, `config_type`, `created_at`)
VALUES (
  'sawmill_settings',
  '{"min_circumference_cm": 30.0, "max_circumference_cm": null, "min_length_cm": 30.0, "max_length_cm": 20000.0, "decimal_places": 1, "deviation_threshold_pct": 5.0}',
  'Trakownia: limity walidacji pomiarów i próg flagowania odchylenia',
  'json',
  NOW()
);
