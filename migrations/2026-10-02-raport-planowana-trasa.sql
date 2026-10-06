-- Logistyka etap 4, krok 4.4b (spec 2026-09-30-logistyka-etap-4-weryfikacja-dostawa-design.md, sekcja 14):
-- jednorazowa poprawka nazwy statusu 417343 w historycznych wierszach STAREGO raportu sprzedażowego
-- (tabela `baselinker_reports_orders`, model BaselinkerReportOrder). Towarzyszka migracji
-- 2026-10-01-analiza-planowana-trasa.sql, która robi to samo w `sales_orders` (nowa Analiza sprzedażowa).
--
-- Zanim mapa STATUSY_BASELINKER (modules/reports/service.py) poznała status 417343, ingest zapisywał go jako
-- „Status 417343” (nazwa dla identyfikatora spoza mapy). Od commita 73232c57 mapa daje „Planowana trasa”, ale
-- stare wiersze zostają ze starą nazwą aż do ponownego wczytania zamówienia, więc jeden status Base. widać w
-- starym raporcie w dwóch kubełkach. Decyzja właściciela z 2.10.2026: poprawiamy historię raz, tą migracją.
--
-- Poprawiamy wyłącznie nazwę, po obu kolumnach (identyfikator i stara nazwa), więc wiersz o tym identyfikatorze
-- z inną nazwą oraz wiersz, który ingest już poprawił, zostają nietknięte. Stary raport trzyma 1 wiersz = 1
-- pozycja, więc zmieniają się wszystkie pozycje takiego zamówienia. Idempotentna: po wykonaniu żaden wiersz nie
-- spełnia warunku, drugi przebieg zmienia 0 wierszy.
--
-- `updated_at` zostaje bez zmian: stary raport go czyta, a kolumna (zwykłe DATETIME NOT NULL, bez
-- ON UPDATE CURRENT_TIMESTAMP) nie przesuwa się przy surowym UPDATE-cie, który nie uruchamia też `onupdate`
-- modelu. Brak indeksu na `baselinker_status_id` nie przeszkadza: to jednorazowy przebieg całej tabeli.
--
-- OSŁONA TABELI. W odróżnieniu od `sales_orders` tabelę `baselinker_reports_orders` zakłada wyłącznie
-- create_all() z modelu: żadna migracja jej nie tworzy, a plik 2026-09-22-sales-tabele.sql zapowiada jej
-- kasowanie po weryfikacji sum. Goły UPDATE na bazie bez tej tabeli (albo bez kolumn statusu) kończy się
-- błędem 1146 (1054), nieudana migracja jest ponawiana przy każdym deployu i przerywa go przed restartem.
-- Dlatego warunek składamy z information_schema i UPDATE wykonujemy przez PREPARE/EXECUTE: treść polecenia
-- siedzi w literale tekstowym, więc na bazie bez tabeli nikt się do niej nie odwołuje i wychodzi sam
-- komunikat „pomijam”. Odczyt z information_schema może zostać zwykłym `SET`, bo pyta katalog systemowy,
-- nie samą tabelę. Napisy w literałach mają PODWOJONE apostrofy, nie cudzysłów (sql_mode z ANSI_QUOTES).

SET @kolumny_raportu = (
    SELECT COUNT(*) FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'baselinker_reports_orders'
      AND COLUMN_NAME IN ('current_status', 'baselinker_status_id')
);

SET @sql = IF(@kolumny_raportu = 2,
    'UPDATE baselinker_reports_orders SET current_status = ''Planowana trasa'' WHERE baselinker_status_id = 417343 AND current_status = ''Status 417343''',
    'SELECT ''tabela baselinker_reports_orders (z kolumnami statusu) nie istnieje - pomijam'' AS info');

PREPARE popraw_status_raportu FROM @sql;
EXECUTE popraw_status_raportu;
DEALLOCATE PREPARE popraw_status_raportu;
