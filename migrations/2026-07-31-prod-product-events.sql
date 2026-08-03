-- Audyt zdarzeń produktu (zmiany statusu, priorytetu, doróbki, transport).
-- Wykonać w phpMyAdmin PRZED deployem kodu.

CREATE TABLE IF NOT EXISTS `prod_product_events` (
  `id` INT NOT NULL AUTO_INCREMENT,
  `production_item_id` INT NOT NULL,
  `event_type` ENUM('status_change','priority_change','rework','logistics') NOT NULL,
  `old_value` VARCHAR(64) NULL,
  `new_value` VARCHAR(64) NULL,
  `actor_type` ENUM('user','device','system') NOT NULL,
  `user_id` INT NULL,
  `device_id` VARCHAR(64) NULL COMMENT 'prod_devices.device_id (gdy tablet)',
  `source` ENUM('web','mobile','admin','system','auto_skip','sync') NOT NULL DEFAULT 'web',
  `endpoint` VARCHAR(128) NULL,
  `ip_address` VARCHAR(45) NULL,
  `note` VARCHAR(255) NULL COMMENT 'Powód doróbki, kategoria wady',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `ix_prod_product_events_production_item_id` (`production_item_id`),
  KEY `ix_prod_product_events_event_type` (`event_type`),
  KEY `ix_prod_product_events_user_id` (`user_id`),
  KEY `ix_prod_product_events_created_at` (`created_at`),
  KEY `ix_prod_product_events_item_created` (`production_item_id`,`created_at`),
  CONSTRAINT `fk_prod_product_events_item`
    FOREIGN KEY (`production_item_id`) REFERENCES `prod_products` (`id`) ON DELETE CASCADE,
  CONSTRAINT `fk_prod_product_events_user`
    FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
