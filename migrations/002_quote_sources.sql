-- Migracja: Dodanie źródeł wycen
-- Data: 2026-01-16
-- Opis: Dodaje kolumnę source do tabeli quotes

ALTER TABLE quotes ADD COLUMN source VARCHAR(50) DEFAULT 'calculator' COMMENT 'Źródło wyceny (calculator/public/baselinker)';
