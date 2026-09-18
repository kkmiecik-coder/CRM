-- Migracja: product_id w kolejce druku etykiet
-- Data: 2026-09-18
--
-- Tabela: prod_print_queue (nowa kolumna product_id).
--
-- DLACZEGO. Zadanie druku identyfikuje pozycje przez short_product_id, a ten
-- klucz NIE jest unikalny: rework_service tworzy dorobke z tym samym
-- short_product_id co oryginal (13 takich par na produkcji we wrzesniu 2026).
-- Dopoki kolejka tylko wiozla ZPL do drukarki, bylo to nieszkodliwe. Przestaje
-- byc, gdy licznik wydrukowanych etykiet ma byc PROSTOWANY po nieudanym
-- wydruku: cofniecie po short_product_id trafiloby w losowy z dwoch wierszy.
--
-- Kolumna jest nullable CELOWO. Wiersze sprzed tej migracji zostaja z NULL
-- i po prostu nie podlegaja cofaniu — nie ma czego prostowac wstecz, bo dla
-- nich nie wiadomo, ktorej pozycji dotyczyly. Nowe zadania dostaja product_id
-- przy wkladaniu do kolejki.
--
-- BEZ FK. prod_print_queue jest dziennikiem zadan, nie czescia modelu
-- produktu: zadania przezywaja usuniecie pozycji i maja prawo pamietac, co
-- drukowano. FK z ON DELETE CASCADE kasowalby historie, a z RESTRICT
-- blokowalby porzadki. Ten sam wzorzec co short_product_id w tej tabeli.
--
-- IDEMPOTENTNOSC. Dodanie kolumny oslonione warunkiem na information_schema
-- (wzorzec: migrations/2026-08-21-prod-products-shape-rotation.sql). Runner
-- polyka blad 'duplicate column', ale poleganie na tym zostawia w logu
-- deployu falszywy alarm przy kazdym kolejnym przebiegu.

SET @kolumna_istnieje = (
    SELECT COUNT(*) FROM information_schema.COLUMNS
     WHERE TABLE_SCHEMA = DATABASE()
       AND TABLE_NAME = 'prod_print_queue'
       AND COLUMN_NAME = 'product_id'
);

SET @sql = IF(@kolumna_istnieje = 0,
    'ALTER TABLE prod_print_queue ADD COLUMN product_id INT NULL COMMENT ''prod_products.id — klucz jednoznaczny, w odroznieniu od short_product_id''',
    'SELECT ''product_id juz istnieje — pomijam''');

PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- Indeks pod cofanie licznika: szukamy zadan po pozycji i statusie.
SET @indeks_istnieje = (
    SELECT COUNT(*) FROM information_schema.STATISTICS
     WHERE TABLE_SCHEMA = DATABASE()
       AND TABLE_NAME = 'prod_print_queue'
       AND INDEX_NAME = 'ix_prod_print_queue_product_id'
);

SET @sql_idx = IF(@indeks_istnieje = 0,
    'CREATE INDEX ix_prod_print_queue_product_id ON prod_print_queue (product_id)',
    'SELECT ''indeks juz istnieje — pomijam''');

PREPARE stmt_idx FROM @sql_idx;
EXECUTE stmt_idx;
DEALLOCATE PREPARE stmt_idx;
