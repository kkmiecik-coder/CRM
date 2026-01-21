-- Migracja: Dodanie obsługi kątów fazowania
-- Data: 2026-01-21
-- Opis: Dodaje kolumny dla predefiniowanych kątów fazowania

-- 1. Dodaj kolumny do edge_options dla kątów fazowania
ALTER TABLE edge_options ADD COLUMN chamfer_angles JSON DEFAULT NULL COMMENT 'Predefiniowane kąty dla fazowania np. [30, 45, 60]';
ALTER TABLE edge_options ADD COLUMN angle_default INT DEFAULT NULL COMMENT 'Domyślny kąt dla fazowania';

-- 2. Dodaj kolumnę do quote_items_details dla zapisanego kąta
ALTER TABLE quote_items_details ADD COLUMN edges_angle_value INT DEFAULT NULL COMMENT 'Wybrany kąt fazowania w stopniach';

-- 3. Ustaw domyślne kąty dla fazowania
UPDATE edge_options SET chamfer_angles = '[30, 45, 60]', angle_default = 45 WHERE type = 'chamfer';
