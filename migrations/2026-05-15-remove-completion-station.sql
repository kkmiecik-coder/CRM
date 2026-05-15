-- Migracja: usunięcie stanowiska kompletacji z pipeline'u produkcji
-- Data: 2026-05-15
-- Spec: docs/superpowers/specs/2026-05-15-remove-completion-station-design.md
-- Cofa: migrations/2026-04-30-add-completion-station.sql
-- Tabela: prod_items
--
-- UWAGA: Plik referencyjny — uruchamiany RĘCZNIE przez phpMyAdmin
-- w dwóch fazach (PRE-DEPLOY i POST-DEPLOY).

-- ============================================================
-- FAZA A — PRE-DEPLOY (uruchom PRZED git push)
-- Przesunięcie wszystkich in-flight produktów z kompletacji do sklejania.
-- Świadomie NIE przepisujemy quantity_done_completion do quantity_done_gluing —
-- to inne fizyczne czynności. Operator zaczyna sklejanie od 0/N.
-- ============================================================

UPDATE prod_items
   SET current_status = 'czeka_na_sklejanie'
 WHERE current_status = 'czeka_na_kompletacje';

-- Weryfikacja (powinno zwrócić 0):
-- SELECT COUNT(*) FROM prod_items WHERE current_status = 'czeka_na_kompletacje';


-- ============================================================
-- FAZA C — POST-DEPLOY (uruchom PO pomyślnym deployu kodu)
-- DROP kolumn, ALTER ENUM, DELETE eventów. Operacja nieodwracalna —
-- przed uruchomieniem upewnij się że deploy poszedł czysto i nic nie
-- crashuje w panelu admina.
-- ============================================================

ALTER TABLE prod_items DROP COLUMN quantity_done_completion;
ALTER TABLE prod_items DROP COLUMN completion_completed_at;
-- Indeks idx_completion_completed_at zostanie automatycznie usunięty z kolumną.

ALTER TABLE prod_items MODIFY COLUMN current_status ENUM(
  'czeka_na_wyciecie',
  'czeka_na_skladanie',
  'czeka_na_sklejanie',
  'czeka_na_formatowanie',
  'czeka_na_wykanczanie',
  'czeka_na_lakiernie',
  'czeka_na_logistyke',
  'czeka_na_pakowanie',
  'spakowane',
  'anulowane',
  'wstrzymane',
  'w_realizacji'
) NOT NULL DEFAULT 'czeka_na_wyciecie';

DELETE FROM prod_station_events WHERE station_code = 'completion';

-- Weryfikacja po fazie C:
-- SHOW COLUMNS FROM prod_items LIKE '%completion%';        -- powinno być puste
-- SELECT COUNT(*) FROM prod_station_events WHERE station_code='completion';  -- 0
