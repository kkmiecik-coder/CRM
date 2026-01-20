-- ============================================
-- Migracja: Funkcjonalność obróbki krawędzi
-- Data: 2026-01-19
-- ============================================

-- 1. Tabela słownikowa typów obróbki (jeśli nie istnieje)
CREATE TABLE IF NOT EXISTS edge_options (
    id INT AUTO_INCREMENT PRIMARY KEY,
    type VARCHAR(32) NOT NULL UNIQUE,
    name VARCHAR(100) NOT NULL,
    price_per_mb DECIMAL(10, 2) NOT NULL DEFAULT 0,
    corner_price DECIMAL(10, 2) NOT NULL DEFAULT 0,
    r_min INT DEFAULT NULL,
    r_max INT DEFAULT NULL,
    r_default INT DEFAULT NULL,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 2. Dane początkowe dla edge_options
INSERT IGNORE INTO edge_options (type, name, price_per_mb, corner_price, r_min, r_max, r_default) VALUES
('sharp', 'Ostre', 0.00, 0.00, NULL, NULL, NULL),
('chamfer', 'Fazowanie', 15.00, 5.00, 3, 10, 3),
('round', 'Zaokrąglenie', 15.00, 5.00, 3, 20, 5);

-- 3. Rozszerzenie tabeli quote_items_details o kolumny krawędzi
-- Sprawdź czy kolumny nie istnieją przed dodaniem

-- edges_config (JSON)
SET @dbname = DATABASE();
SET @tablename = 'quote_items_details';
SET @columnname = 'edges_config';
SET @preparedStatement = (SELECT IF(
  (SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA = @dbname AND TABLE_NAME = @tablename AND COLUMN_NAME = @columnname) = 0,
  CONCAT('ALTER TABLE ', @tablename, ' ADD COLUMN ', @columnname, ' JSON DEFAULT NULL'),
  'SELECT 1'
));
PREPARE alterIfNotExists FROM @preparedStatement;
EXECUTE alterIfNotExists;
DEALLOCATE PREPARE alterIfNotExists;

-- edges_type
SET @columnname = 'edges_type';
SET @preparedStatement = (SELECT IF(
  (SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA = @dbname AND TABLE_NAME = @tablename AND COLUMN_NAME = @columnname) = 0,
  CONCAT('ALTER TABLE ', @tablename, ' ADD COLUMN ', @columnname, ' VARCHAR(32) DEFAULT NULL'),
  'SELECT 1'
));
PREPARE alterIfNotExists FROM @preparedStatement;
EXECUTE alterIfNotExists;
DEALLOCATE PREPARE alterIfNotExists;

-- edges_r_value
SET @columnname = 'edges_r_value';
SET @preparedStatement = (SELECT IF(
  (SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA = @dbname AND TABLE_NAME = @tablename AND COLUMN_NAME = @columnname) = 0,
  CONCAT('ALTER TABLE ', @tablename, ' ADD COLUMN ', @columnname, ' INT DEFAULT NULL'),
  'SELECT 1'
));
PREPARE alterIfNotExists FROM @preparedStatement;
EXECUTE alterIfNotExists;
DEALLOCATE PREPARE alterIfNotExists;

-- edges_price_netto
SET @columnname = 'edges_price_netto';
SET @preparedStatement = (SELECT IF(
  (SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA = @dbname AND TABLE_NAME = @tablename AND COLUMN_NAME = @columnname) = 0,
  CONCAT('ALTER TABLE ', @tablename, ' ADD COLUMN ', @columnname, ' DECIMAL(10, 2) DEFAULT 0'),
  'SELECT 1'
));
PREPARE alterIfNotExists FROM @preparedStatement;
EXECUTE alterIfNotExists;
DEALLOCATE PREPARE alterIfNotExists;

-- edges_price_brutto
SET @columnname = 'edges_price_brutto';
SET @preparedStatement = (SELECT IF(
  (SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA = @dbname AND TABLE_NAME = @tablename AND COLUMN_NAME = @columnname) = 0,
  CONCAT('ALTER TABLE ', @tablename, ' ADD COLUMN ', @columnname, ' DECIMAL(10, 2) DEFAULT 0'),
  'SELECT 1'
));
PREPARE alterIfNotExists FROM @preparedStatement;
EXECUTE alterIfNotExists;
DEALLOCATE PREPARE alterIfNotExists;

-- ============================================
-- Weryfikacja
-- ============================================
SELECT 'Migracja zakończona pomyślnie' AS status;
SELECT COUNT(*) AS edge_options_count FROM edge_options;
SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS
WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'quote_items_details' AND COLUMN_NAME LIKE 'edges%';
