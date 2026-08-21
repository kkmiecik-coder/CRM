-- Migracja: lamella_direction -> shape_rotation
-- Data: 2026-08-21
-- Opis: Pole "kierunek lameli" (0/45/90/135) znika z aplikacji. Lamele są
--       od teraz zawsze poziome, a ukośny układ słojów uzyskuje się obrotem
--       kształtu w canvasie kalkulatora. Ta sama kolumna trzyma teraz kąt
--       obrotu kształtu w stopniach (0-359).
--
--       Zastane wartości zerujemy: kształty archiwalnych wycen NIE są
--       obrócone, więc 45 w starym znaczeniu to 0 w nowym. Informacja
--       o ukośnych lamelach przepada — decyzja świadoma, patrz spec
--       docs/superpowers/specs/2026-08-21-obrot-ksztaltu-canvas-design.md
--
-- Idempotentność: oba polecenia są osłonięte warunkiem na istnienie starej
-- kolumny. Po pierwszym przebiegu warunek jest fałszywy, więc powtórka nie
-- wyzeruje kątów zapisanych już przez użytkowników.
-- Zmiana separatora poleceń jest tu celowo pominięta — runner jej nie obsługuje.

SET @stara_kolumna := (
    SELECT COUNT(*) FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'quote_items_details'
      AND COLUMN_NAME = 'lamella_direction'
);

SET @sql_rename := IF(@stara_kolumna > 0,
    'ALTER TABLE quote_items_details RENAME COLUMN lamella_direction TO shape_rotation',
    'SELECT 1');

PREPARE polecenie_rename FROM @sql_rename;

EXECUTE polecenie_rename;

DEALLOCATE PREPARE polecenie_rename;

SET @sql_zerowanie := IF(@stara_kolumna > 0,
    'UPDATE quote_items_details SET shape_rotation = 0 WHERE shape_rotation IS NOT NULL',
    'SELECT 1');

PREPARE polecenie_zerowanie FROM @sql_zerowanie;

EXECUTE polecenie_zerowanie;

DEALLOCATE PREPARE polecenie_zerowanie;
