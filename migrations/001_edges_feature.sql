-- Migracja: Dodanie obsługi obróbki krawędzi
-- Data: 2026-01-15
-- Opis: Dodaje kolumny do quote_items_details dla konfiguracji krawędzi

-- Dodaj kolumny do quote_items_details
ALTER TABLE quote_items_details ADD COLUMN edges_type VARCHAR(50) DEFAULT NULL COMMENT 'Typ obróbki krawędzi (round/chamfer)';
ALTER TABLE quote_items_details ADD COLUMN edges_r_value INT DEFAULT NULL COMMENT 'Wartość promienia R w mm';
ALTER TABLE quote_items_details ADD COLUMN edges_config JSON DEFAULT NULL COMMENT 'Konfiguracja krawędzi [{letter, length_cm, price}]';
ALTER TABLE quote_items_details ADD COLUMN edges_svg TEXT DEFAULT NULL COMMENT 'SVG wizualizacja krawędzi';
ALTER TABLE quote_items_details ADD COLUMN edges_total_price DECIMAL(10,2) DEFAULT NULL COMMENT 'Łączna cena obróbki krawędzi';
