-- ============================================
-- Migracja: Funkcjonalność obróbki krawędzi
-- Data: 2026-01-19
-- Wersja: PROSTA (bez sprawdzania czy kolumny istnieją)
-- ============================================

-- 1. Tabela słownikowa typów obróbki
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
-- UWAGA: Uruchom każde polecenie osobno jeśli któreś zawiedzie (kolumna już istnieje)

ALTER TABLE quote_items_details ADD COLUMN edges_config JSON DEFAULT NULL;
ALTER TABLE quote_items_details ADD COLUMN edges_type VARCHAR(32) DEFAULT NULL;
ALTER TABLE quote_items_details ADD COLUMN edges_r_value INT DEFAULT NULL;
ALTER TABLE quote_items_details ADD COLUMN edges_price_netto DECIMAL(10, 2) DEFAULT 0;
ALTER TABLE quote_items_details ADD COLUMN edges_price_brutto DECIMAL(10, 2) DEFAULT 0;
ALTER TABLE quote_items_details ADD COLUMN edges_svg TEXT DEFAULT NULL;

-- ============================================
-- Weryfikacja
-- ============================================
SELECT 'Migracja zakończona' AS status;
SELECT * FROM edge_options;
