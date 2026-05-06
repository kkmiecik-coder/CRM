-- Migracja: dodanie pola cut_to_size do quote_items_details
-- Data: 2026-05-06
-- Wykonać RĘCZNIE na produkcji po wdrożeniu kodu (auto-migracje są zawodne).

ALTER TABLE quote_items_details
  ADD COLUMN cut_to_size BOOLEAN NOT NULL DEFAULT TRUE;

-- Weryfikacja:
-- DESCRIBE quote_items_details;
-- SELECT COUNT(*) FROM quote_items_details WHERE cut_to_size = TRUE;
