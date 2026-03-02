-- Migracja: Dodanie obsługi kształtu produktu (prostokątny/okrągły)
-- Data: 2026-03-02
-- Opis: Dodaje kolumny kształtu do quote_items_details oraz tabelę ustawień kalkulatora

-- 1. Dodaj kolumny kształtu do quote_items_details
ALTER TABLE quote_items_details ADD COLUMN shape VARCHAR(20) DEFAULT 'rectangular' COMMENT 'Kształt produktu: rectangular lub round';
ALTER TABLE quote_items_details ADD COLUMN round_surcharge_netto DECIMAL(10,2) DEFAULT 0 COMMENT 'Dopłata netto za kształt okrągły (łącznie za ilość)';
ALTER TABLE quote_items_details ADD COLUMN round_surcharge_brutto DECIMAL(10,2) DEFAULT 0 COMMENT 'Dopłata brutto za kształt okrągły (łącznie za ilość)';

-- 2. Dodaj pole rzeczywistej objętości produktu (dla kształtu okrągłego inna niż objętość bloku)
ALTER TABLE quote_items ADD COLUMN real_volume_m3 DECIMAL(10,6) DEFAULT NULL COMMENT 'Rzeczywista objętość produktu w m³ (dla okrągłych: π×a×b×T)';

-- 3. Utwórz tabelę ustawień kalkulatora (klucz-wartość)
CREATE TABLE IF NOT EXISTS calculator_settings (
    id INT AUTO_INCREMENT PRIMARY KEY,
    setting_key VARCHAR(100) NOT NULL UNIQUE,
    setting_value VARCHAR(255) NOT NULL,
    description VARCHAR(500) DEFAULT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 4. Wstaw domyślną dopłatę za kształt okrągły
INSERT INTO calculator_settings (setting_key, setting_value, description)
VALUES ('round_shape_surcharge_netto', '50.00', 'Dopłata netto za sztukę za kształt okrągły/owalny')
ON DUPLICATE KEY UPDATE setting_key = setting_key;
