-- Dodaje ograniczenie UNIQUE na sales_order_items(order_id, bl_order_product_id).
--
-- KONTEKST. `_upsert_pozycje` (modules/reports/ingest.py) dopasowuje pozycje
-- WYŁĄCZNIE po `bl_order_product_id`, ale nic w schemacie nie broni dwóm
-- wierszom tego samego zamówienia noszenia tego samego klucza — gdyby taki
-- dublet kiedykolwiek powstał (błąd w kodzie, równoległy zapis), nikt by go
-- nie zauważył od razu. To ograniczenie zamienia „nie powinno się zdarzyć"
-- w „nie MOŻE się zdarzyć" — cała gimnastyka z dopasowywaniem pozycji po
-- nazwie/kolejności, którą PRZESTAJEMY ROBIĆ (patrz historia w ingest.py),
-- istniała właśnie dlatego, że baza nie pilnowała tożsamości pozycji.
--
-- NULL-E W INDEKSIE UNIKALNYM. MySQL/InnoDB nie traktuje NULL jako równy
-- NULL-owi — wiersz, w którym KTÓRAKOLWIEK kolumna złożonego indeksu
-- unikalnego jest NULL, nigdy nie koliduje z żadnym innym wierszem tego
-- indeksu, nawet jeśli pozostałe kolumny są identyczne. Zmierzone na
-- woodpower_crm_local (21.09.2026, przed wdrożeniem tej migracji):
-- wszystkie 7938 istniejących wierszy `sales_order_items` mają
-- `bl_order_product_id IS NULL`, więc ten ALTER przechodzi na nich bez
-- konfliktu — ograniczenie zaczyna realnie działać dopiero dla wierszy,
-- które klucz DOSTANĄ (nowa synchronizacja przyrostowa,
-- `scripts/uzupelnij_klucze_pozycji.py` po ręcznym przeglądzie raportu).
--
-- IDEMPOTENCJA. Runner (migrations/migration_service.py) wykonuje cały
-- katalog przy KAŻDYM deployu. `ALTER TABLE ... ADD UNIQUE` nie ma wariantu
-- IF NOT EXISTS, więc warunek wykonania budujemy z information_schema
-- i wykonujemy przez PREPARE/EXECUTE/DEALLOCATE (zmiana separatora poleceń
-- nie jest tu obsługiwana — patrz CLAUDE.md) — ten sam wzorzec co
-- `migrations/2026-09-22-clients-na-leads.sql`.
--
-- Sprawdzamy też istnienie SAMEJ TABELI: na czystej instalacji katalog
-- migracji wykonuje się w kolejności nazw plików, a
-- `2026-09-22-sales-tabele.sql` sortuje się PRZED tym plikiem, więc tabela
-- normalnie już istnieje — ale goły ALTER TABLE na nieistniejącej tabeli
-- kończy się błędem 1146 i przerywa CAŁY plik migracji. Ten sam odruch
-- ostrożności co krok 7 migracji clients-na-leads (kolumna created_at).
--
-- Oba odczyty niżej (tabela, indeks) mogą zostać ZWYKŁYMI `SET`, bez
-- PREPARE: to zapytania DO information_schema, nie DO `sales_order_items`
-- samej — a information_schema istnieje zawsze i po prostu zwraca zero
-- wierszy, gdy opisywana tabela jeszcze nie istnieje. Błąd 1146 grozi
-- wyłącznie bezpośredniemu odwołaniu do `sales_order_items` w treści
-- polecenia, czyli tylko samemu ALTER-owi niżej.

SET @tabela_istnieje = (
    SELECT COUNT(*) FROM information_schema.TABLES
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'sales_order_items'
);

SET @indeks_istnieje = (
    SELECT COUNT(*) FROM information_schema.STATISTICS
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'sales_order_items'
      AND INDEX_NAME = 'uq_soi_order_bl_product'
);

SET @sql = CASE
    WHEN @tabela_istnieje = 0
        THEN 'SELECT "tabela sales_order_items nie istnieje - pomijam dodanie ograniczenia" AS info'
    WHEN @indeks_istnieje > 0
        THEN 'SELECT "ograniczenie uq_soi_order_bl_product juz istnieje - pomijam" AS info'
    ELSE
        'ALTER TABLE sales_order_items ADD UNIQUE KEY uq_soi_order_bl_product (order_id, bl_order_product_id)'
END;

PREPARE dodaj_unique FROM @sql;
EXECUTE dodaj_unique;
DEALLOCATE PREPARE dodaj_unique;
