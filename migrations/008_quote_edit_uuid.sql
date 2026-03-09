-- Migracja: Dodanie kolumny edit_uuid do tabeli quotes
-- Bezpieczny identyfikator UUID do edycji wycen przez kalkulator

-- 1. Dodaj kolumne edit_uuid
ALTER TABLE quotes ADD COLUMN edit_uuid VARCHAR(36) DEFAULT NULL;

-- 2. Wygeneruj UUID dla istniejacych wycen
UPDATE quotes SET edit_uuid = UUID() WHERE edit_uuid IS NULL;

-- 3. Dodaj unique index
ALTER TABLE quotes ADD UNIQUE INDEX idx_quotes_edit_uuid (edit_uuid);
