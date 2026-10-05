-- Wycofanie wdrożenia z 8.10.2026 (logistyka etapy 1–4 i priorytety produkcji): dane, których stary kod (`main`
-- sprzed wdrożenia) nie zna albo które czyta inaczej. Wykonuje ją STARY kod przy deployu gałęzi wycofania, PRZED
-- restartem (deploy.sh, krok `flask migrate`). Same dane: ENUM-y, kolumny i tabele logistyki i priorytetów zostają —
-- stary kod ich nie czyta, a ponowne wdrożenie z nich korzysta (spec logistyki etapu 4, sekcja 14; spec priorytetów,
-- sekcja 11 „Wycofanie”).
--
-- Idempotentna: każdy przepis zmienia tylko wiersze w nowym stanie, drugi przebieg zmienia 0 wierszy. Każdy zapis
-- idzie przez PREPARE po sprawdzeniu information_schema — na bazie bez tabel albo kolumn logistyki (np. po nieudanym
-- wdrożeniu) przepis się pomija zamiast blokować deploy błędem 1146/1054. Bez zmiany separatora poleceń. Napisy w literałach mają
-- PODWOJONE apostrofy. Po wykonaniu wpis w schema_migrations zostaje: drugie wycofanie (po ponownym wdrożeniu)
-- wymaga ręcznego uruchomienia tego pliku (`mysql <baza> < migrations/2026-10-08-wycofanie-logistyki.sql`) albo
-- kopii pod nową nazwą — runner drugi raz go nie weźmie.
--
-- Okno wdrożenia: między tą migracją a restartem działa jeszcze nowy kod (deploy.sh liczy też klientów sprzedaży,
-- do 300 s) i może zapisać nowe stany. Po restarcie uruchom ten plik ręcznie jeszcze raz (runbook wycofania).

-- 1. Statusy pozycji (spec etapu 4, sekcja 14 pkt 3). Stary Enum `production_status` nie zna `zweryfikowane`,
--    `zaladowane`, `dostarczone` → LookupError, czyli 500 na listach, w archiwum, wyszukiwarce tabletów i monitorach.
SET @nowe_statusy = (
    SELECT COUNT(*) FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'prod_products' AND COLUMN_NAME = 'current_status'
      AND COLUMN_TYPE LIKE '%zweryfikowane%'
);
SET @sql = IF(@nowe_statusy = 1,
    'UPDATE prod_products SET current_status = ''spakowane'' WHERE current_status IN (''zweryfikowane'', ''zaladowane'', ''dostarczone'')',
    'SELECT ''prod_products.current_status bez statusow logistyki - pomijam'' AS info');
PREPARE krok FROM @sql;
EXECUTE krok;
DEALLOCATE PREPARE krok;

-- Znacznik jednorazowego przestawienia wydanych odbiorów (sekcja 14 pkt 3): bez niego ponowne wdrożenie znów
-- przestawi wydane na `dostarczone`.
SET @konfiguracja = (
    SELECT COUNT(*) FROM information_schema.TABLES
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'prod_config'
);
SET @sql = IF(@konfiguracja = 1,
    'DELETE FROM prod_config WHERE config_key = ''logistyka_wydane_dostarczone''',
    'SELECT ''brak prod_config - pomijam'' AS info');
PREPARE krok FROM @sql;
EXECUTE krok;
DEALLOCATE PREPARE krok;

-- 2. U10 — niedostarczony przystanek na trasie w drodze (sekcja 14 pkt 6). Najpierw (jeszcze na nowym kodzie)
--    logistyk zdejmuje wiszące niedostarczone do puli; co zostało, wraca tu do „do dostarczenia”.
SET @u10 = (
    SELECT COUNT(*) FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'prod_route_stops'
      AND COLUMN_NAME IN ('not_delivered_at', 'not_delivered_reason', 'not_delivered_note', 'not_delivered_by_worker_id')
);
SET @sql = IF(@u10 = 4,
    'UPDATE prod_route_stops SET not_delivered_at = NULL, not_delivered_reason = NULL, not_delivered_note = NULL, not_delivered_by_worker_id = NULL WHERE not_delivered_at IS NOT NULL',
    'SELECT ''prod_route_stops bez kolumn U10 - pomijam'' AS info');
PREPARE krok FROM @sql;
EXECUTE krok;
DEALLOCATE PREPARE krok;

SET @log_logistyki = (
    SELECT COUNT(*) FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'prod_logistics_log'
      AND COLUMN_NAME IN ('action', 'note', 'old_value')
);
SET @sql = IF(@log_logistyki = 3,
    'UPDATE prod_logistics_log SET action = ''trasa_status'', note = LEFT(CONCAT(''cofniete niedostarczenie: '', COALESCE(old_value, '''')), 255) WHERE action = ''niedostarczenie_cofniete''',
    'SELECT ''brak prod_logistics_log - pomijam'' AS info');
PREPARE krok FROM @sql;
EXECUTE krok;
DEALLOCATE PREPARE krok;

-- 3. Trasy i log Dostawy (sekcja 14 pkt 4): statusy tras `zaladowana`/`w_trasie` i akcje Dostawy → wartości kodu
--    sprzed kroku 4.4. Stary `main` tych tabel nie czyta wcale; przepis trzyma bazę w stanie, który zna każdy
--    wcześniejszy kod logistyki, i nie szkodzi ponownemu wdrożeniu.
SET @trasy = (
    SELECT COUNT(*) FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'prod_routes' AND COLUMN_NAME = 'status'
);
SET @sql = IF(@trasy = 1,
    'UPDATE prod_routes SET status = ''zatwierdzona'' WHERE status IN (''zaladowana'', ''w_trasie'')',
    'SELECT ''brak prod_routes - pomijam'' AS info');
PREPARE krok FROM @sql;
EXECUTE krok;
DEALLOCATE PREPARE krok;

SET @sql = IF(@log_logistyki = 3,
    'UPDATE prod_logistics_log SET action = ''trasa_status'' WHERE action IN (''zaladunek'', ''zostaje'', ''wyjazd'', ''dostarczone'', ''niedostarczone'', ''dostarczenie_cofniete'')',
    'SELECT ''brak prod_logistics_log - pomijam'' AS info');
PREPARE krok FROM @sql;
EXECUTE krok;
DEALLOCATE PREPARE krok;

-- 4. Kolejka druku (znalezisko próby wycofania, krok 4.1/4.2 logistyki): stary `GET /print-agent/jobs` nie filtruje
--    drukarki, więc oczekujące etykiety paczek (100×150, `printer` = `wysylka`) poszłyby na drukarkę etykiet
--    produktów 60×40. Wygaszamy je statusem, który zna stary Enum; paczki zostają w bazie.
SET @druk = (
    SELECT COUNT(*) FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'prod_print_queue'
      AND COLUMN_NAME IN ('printer', 'package_id', 'status', 'error_message')
);
SET @sql = IF(@druk = 4,
    'UPDATE prod_print_queue SET status = ''expired'', error_message = ''Wycofanie wdrozenia 8.10: zadanie drukarki paczek'' WHERE status = ''pending'' AND (printer <> ''etykiety'' OR package_id IS NOT NULL)',
    'SELECT ''prod_print_queue bez drukarki paczek - pomijam'' AS info');
PREPARE krok FROM @sql;
EXECUTE krok;
DEALLOCATE PREPARE krok;

-- 5. Priorytety pozycji (znalezisko próby wycofania; spec priorytetów 8.5 i 11). Nowy kod przy każdym przeliczeniu
--    nadaje rangi z drabiny, zdejmuje ręczne blokady (`priority_manual_override`) i liczy `is_priority` od nowa
--    (gwiazdki albo „po terminie”). Stary kod: `is_priority` to ręczna flaga biura, a stare przeliczenie pomija
--    tylko pozycje zablokowane.
-- 5a. Kopia sprzed wdrożenia (opcjonalna, runbook K7: tabela zz_przed_wdrozeniem_2026_10_08_priorytety z kolumnami
--     id, priority_rank, priority_manual_override, is_priority) — przywraca ręczne flagi i blokady pozycjom, które
--     są jeszcze w produkcji. Bez kopii przepis się pomija (flagi z wdrożenia zostają; stare przeliczenie
--     ponumeruje rangi od nowa).
SET @kopia = (
    SELECT COUNT(*) FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'zz_przed_wdrozeniem_2026_10_08_priorytety'
      AND COLUMN_NAME IN ('id', 'priority_rank', 'priority_manual_override', 'is_priority')
);
SET @sql = IF(@kopia = 4,
    'UPDATE prod_products p JOIN zz_przed_wdrozeniem_2026_10_08_priorytety k ON k.id = p.id SET p.priority_rank = k.priority_rank, p.priority_manual_override = k.priority_manual_override, p.is_priority = k.is_priority WHERE p.current_status NOT IN (''spakowane'', ''anulowane'')',
    'SELECT ''brak kopii priorytetow sprzed wdrozenia - pomijam'' AS info');
PREPARE krok FROM @sql;
EXECUTE krok;
DEALLOCATE PREPARE krok;

-- 5b. Doróbki przed Formatowaniem — stan, który stary kod nadaje doróbce przy tworzeniu (rework_service:
--     lock_priority(rank=1): ranga 1, blokada, ramka) i zdejmuje dopiero na Formatowaniu. Obejmuje też doróbki
--     utworzone po wdrożeniu (nowy kod daje im rangę 0 bez blokady).
SET @dorobki = (
    SELECT COUNT(*) FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'prod_products'
      AND COLUMN_NAME IN ('original_product_id', 'priority_rank', 'priority_manual_override', 'is_priority')
);
SET @sql = IF(@dorobki = 4,
    'UPDATE prod_products SET priority_rank = 1, priority_manual_override = 1, is_priority = 1 WHERE original_product_id IS NOT NULL AND current_status IN (''czeka_na_wyciecie'', ''czeka_na_skladanie'', ''czeka_na_sklejanie'')',
    'SELECT ''prod_products bez kolumn priorytetu - pomijam'' AS info');
PREPARE krok FROM @sql;
EXECUTE krok;
DEALLOCATE PREPARE krok;
