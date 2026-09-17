-- Źródło zamówienia (kanał sprzedaży) na zamówieniu produkcyjnym.
--
-- Po co: stanowisko pakowania musi wiedzieć, skąd przyszło zamówienie, bo kody
-- rabatowe dokładane do paczki będą inne dla Allegro, inne dla sklepu, a dla
-- klientów B2B nie będzie ich wcale. Do tej pory synchronizacja z BaseLinkera
-- w ogóle nie czytała pól `order_source*` z getOrders — informacja istniała
-- po stronie BL, ale do CRM-u nie trafiała.
--
-- Trzy kolumny, nie jedna etykieta: `order_source` + `order_source_id` to
-- surowa para z BaseLinkera i JEDYNY pewny klucz źródła (`order_source_id`
-- bywa niejednoznaczne — 0 to zarówno „Detal" w kanale `personal`, jak
-- i „Zwrot do zamówienia" w kanale `order_return`). `order_source_name` jest
-- migawką nazwy ze słownika getOrderSources zrobioną w chwili synchronizacji:
-- BaseLinker zwraca w samym zamówieniu `order_source_info` = "-", więc nazwy
-- nie da się odczytać z zamówienia, a trzymanie jej przy wierszu oszczędza
-- każdemu konsumentowi (tablet, panel, eksport) własnego mapowania.
--
-- Wartości spotykane w praktyce (stan na 09.2026):
--   personal / 0 Detal, 63189 Czernecki, 68970 Nowy B2B, 68971 Stały B2B,
--              68973 PH Nowy B2B, 68974 PH Stały B2B, 85727 Dębuś VPS
--   shop     / 5029946 Presta VPS
--   allegro  / 8881 woodpower
--   olx      / 12428, inpsa / 43452, order_return / 0
--
-- Kolumny zostają NULL-owalne: zamówienia wprowadzone ręcznie
-- (sync_source = 'manual_entry') nie mają źródła w BaseLinkerze, a stare
-- zamówienia uzupełnia osobno `flask backfill-order-sources`.
--
-- Indeks na (order_source, order_source_id) obsługuje filtr po kanale na
-- liście produktów. Idempotentność: ALTER-y i indeks osłonięte warunkiem na
-- information_schema, wykonywane przez PREPARE/EXECUTE — wzorzec taki sam
-- jak w migrations/2026-08-31-znacznik-proby-zamowienia.sql.

-- 1. order_source — kanał sprzedaży (klucz słownika getOrderSources)
SET @kolumna_source := (
    SELECT COUNT(*) FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'prod_orders'
      AND COLUMN_NAME = 'order_source'
);

SET @sql_source := IF(@kolumna_source = 0,
    'ALTER TABLE prod_orders ADD COLUMN order_source VARCHAR(50) NULL DEFAULT NULL',
    'SELECT 1');

PREPARE polecenie_source FROM @sql_source;
EXECUTE polecenie_source;
DEALLOCATE PREPARE polecenie_source;

-- 2. order_source_id — identyfikator konkretnego źródła w obrębie kanału
SET @kolumna_source_id := (
    SELECT COUNT(*) FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'prod_orders'
      AND COLUMN_NAME = 'order_source_id'
);

SET @sql_source_id := IF(@kolumna_source_id = 0,
    'ALTER TABLE prod_orders ADD COLUMN order_source_id INT NULL DEFAULT NULL',
    'SELECT 1');

PREPARE polecenie_source_id FROM @sql_source_id;
EXECUTE polecenie_source_id;
DEALLOCATE PREPARE polecenie_source_id;

-- 3. order_source_name — nazwa źródła ze słownika, migawka z chwili synchronizacji
SET @kolumna_source_name := (
    SELECT COUNT(*) FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'prod_orders'
      AND COLUMN_NAME = 'order_source_name'
);

SET @sql_source_name := IF(@kolumna_source_name = 0,
    'ALTER TABLE prod_orders ADD COLUMN order_source_name VARCHAR(100) NULL DEFAULT NULL',
    'SELECT 1');

PREPARE polecenie_source_name FROM @sql_source_name;
EXECUTE polecenie_source_name;
DEALLOCATE PREPARE polecenie_source_name;

-- 4. Indeks pod filtr po kanale sprzedaży
SET @indeks_istnieje := (
    SELECT COUNT(*) FROM information_schema.STATISTICS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'prod_orders'
      AND INDEX_NAME = 'idx_prod_orders_order_source'
);

SET @sql_indeks := IF(@indeks_istnieje = 0,
    'CREATE INDEX idx_prod_orders_order_source ON prod_orders (order_source, order_source_id)',
    'SELECT 1');

PREPARE polecenie_indeks FROM @sql_indeks;
EXECUTE polecenie_indeks;
DEALLOCATE PREPARE polecenie_indeks;
