-- Dodanie kolumny kierunku lameli do QuoteItemDetails
-- Wartości: 0, 45, 90, 135 (stopnie obrotu) lub NULL (prostokąt/koło)
ALTER TABLE quote_items_details ADD COLUMN lamella_direction INT NULL DEFAULT NULL;
