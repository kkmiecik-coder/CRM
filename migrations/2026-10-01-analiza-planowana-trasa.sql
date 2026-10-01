-- Logistyka etap 4, krok 4.4b (spec 2026-09-30-logistyka-etap-4-weryfikacja-dostawa-design.md, sekcja 14):
-- jednorazowa poprawka nazwy statusu 417343 w historycznych wierszach Analizy sprzedażowej.
--
-- Zanim mapa STATUSY_BASELINKER (modules/reports/service.py) poznała status 417343, ingest zapisywał go jako
-- „Status 417343” (nazwa dla identyfikatora spoza mapy). Od commita 73232c57 mapa daje „Planowana trasa”, ale
-- stare wiersze zostają ze starą nazwą aż do ponownego wczytania zamówienia, więc jeden status Base. widać w
-- Analizie w dwóch kubełkach. Decyzja właściciela z 1.10.2026: poprawiamy historię raz, tą migracją.
--
-- Poprawiamy wyłącznie nazwę, po obu kolumnach (identyfikator i stara nazwa), więc wiersz o tym identyfikatorze
-- z inną nazwą oraz wiersz, który ingest już poprawił, zostają nietknięte. Idempotentna: po wykonaniu żaden
-- wiersz nie spełnia warunku, drugi przebieg zmienia 0 wierszy. Status 524520 („Załadowane”) nie wchodzi w
-- zakres: w kopii produkcji z ok. 25.09 nie było wierszy z nazwą „Status 524520”.
--
-- `updated_at` zostaje bez zmian: kolumna w MySQL nie ma ON UPDATE CURRENT_TIMESTAMP (zakłada ją migracja
-- 2026-09-22-sales-tabele.sql jako zwykłe DATETIME NOT NULL), a surowy UPDATE nie uruchamia `onupdate` modelu.
-- Przeliczenie denormalizacji klientów (deploy.sh, krok 6) liczy po identyfikatorze statusu, nie po nazwie,
-- więc po tej zmianie nie wymaga osobnego przebiegu.
UPDATE sales_orders SET current_status = 'Planowana trasa'
WHERE baselinker_status_id = 417343 AND current_status = 'Status 417343';
