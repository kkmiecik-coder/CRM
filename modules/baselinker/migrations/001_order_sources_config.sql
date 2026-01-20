-- ============================================
-- Migracja: Rozszerzenie konfiguracji źródeł zamówień Baselinker
-- Data: 2026-01-20
-- Opis: Dodaje pola do zarządzania widocznością i przypisaniem źródeł zamówień
-- ============================================

-- 1. Dodaj nowe kolumny do baselinker_config
ALTER TABLE baselinker_config
ADD COLUMN IF NOT EXISTS visible_for_roles JSON DEFAULT NULL COMMENT 'Role dla których źródło jest widoczne (null = wszystkie)',
ADD COLUMN IF NOT EXISTS assigned_user_ids JSON DEFAULT NULL COMMENT 'ID użytkowników dla których to źródło jest domyślne',
ADD COLUMN IF NOT EXISTS sort_order INT DEFAULT 0 COMMENT 'Kolejność wyświetlania';

-- 2. Dodaj pole order_source_id do tabeli clients
ALTER TABLE clients
ADD COLUMN IF NOT EXISTS order_source_id INT DEFAULT NULL COMMENT 'Domyślne źródło zamówień dla klienta';

-- 3. Ustaw domyślną kolejność dla istniejących źródeł zamówień
UPDATE baselinker_config
SET sort_order = id
WHERE config_type = 'order_source' AND sort_order = 0;

-- ============================================
-- Weryfikacja
-- ============================================
SELECT 'Migracja order_sources_config zakończona' AS status;
SELECT id, name, baselinker_id, visible_for_roles, assigned_user_ids, sort_order
FROM baselinker_config
WHERE config_type = 'order_source'
ORDER BY sort_order;
