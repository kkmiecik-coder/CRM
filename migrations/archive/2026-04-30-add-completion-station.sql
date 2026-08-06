-- Migracja: dodaj stanowisko kompletacji do pipeline'u produkcji
-- Data: 2026-04-30
-- Spec: docs/superpowers/specs/2026-04-30-completion-station-design.md
-- Tabela: prod_items (model ProductionItem.__tablename__)

-- 1. Nowe kolumny per-produkt
ALTER TABLE prod_items
  ADD COLUMN quantity_done_completion INT NOT NULL DEFAULT 0
    COMMENT 'Ile sztuk wykonano na stanowisku kompletacji',
  ADD COLUMN completion_completed_at DATETIME NULL,
  ADD INDEX idx_completion_completed_at (completion_completed_at);

-- 2. Rozszerzenie ENUM o nową wartość czeka_na_kompletacje
-- WAŻNE: zachowujemy WSZYSTKIE istniejące wartości łącznie z 'wstrzymane' i
-- 'w_realizacji' (poza pipeline'em ale używane do oznaczania ręcznych pauz).
ALTER TABLE prod_items
  MODIFY COLUMN current_status ENUM(
    'czeka_na_wyciecie',
    'czeka_na_skladanie',
    'czeka_na_kompletacje',
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
