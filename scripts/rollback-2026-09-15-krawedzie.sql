-- Rollback migracji 2026-09-15-krawedzie-podzial-wykanczania.sql
--
-- TEN PLIK NIE MOZE LEZEC W migrations/. Nazwa RRRR-MM-DD-*.sql zostalaby
-- rozpoznana przez runner i wykonana przy najblizszym deployu.
-- Precedens: scripts/rollback_rework_columns.sql.
--
-- URUCHOMIENIE:
--   mysql -u <user> -p <baza> --force < scripts/rollback-2026-09-15-krawedzie.sql
--
-- FLAGA --force JEST OBOWIAZKOWA, nie zalecana. Po pierwsze skrypt bywa
-- uruchamiany na schemacie w stanie NIEZNANYM (migracja przerwana w polowie).
-- Po drugie krok 8 pada bledem 1146 na kazdej bazie bez tabeli schema_migrations.
-- Bez --force mysql przerywa na pierwszym bledzie i zostawia baze w stanie
-- gorszym niz zastal. Renamey sa dodatkowo osloniete information_schema.
--
-- KOLEJNOSC MA ZNACZENIE. Kod aplikacji trzeba cofnac ODDZIELNIE (git revert
-- + deploy). Dopoki chodzi nowy kod, natychmiast odtwarza wiersze
-- 'czeka_na_krawedzie' i krok 7 (zdjecie wartosci z enuma) padnie bledem 1265.
--
-- CZEGO TEN SKRYPT NIE COFNIE:
--   * podzialu sesji pracownikow — migracja przepisala je hurtem, wiec
--     odtworzenie oddaje dokladnie stan sprzed, ale informacja, ile czasu
--     nalezalo do Lakierni, nigdy nie istniala;
--   * wierszy zlapanych dopiero przez sweep wyscigu w sekcji 5 migracji —
--     nie ma ich w tabeli kopii; te na 'czeka_na_krawedzie' zlapie catch-all
--     w kroku 3, te na 'czeka_na_lakiernie' zostana tam, gdzie sa;
--   * wpisow w prod_product_events — migracja ich nie tworzyla i rollback
--     tez nie tworzy, wiec dziura w audycie zostaje po obu stronach;
--   * niczego w kodzie aplikacji. To robi git revert + deploy.
--
-- TABELI prod_migracja_krawedzie_kopia NIE USUWAMY — przyda sie przy kolejnym
-- podejsciu, a bez niej przepisania historii nie da sie juz odroznic od danych
-- wlasnych Lakierni.

-- -- 1. Enum statusu: obie wartosci naraz ------------------------------------
ALTER TABLE prod_products MODIFY COLUMN current_status ENUM(
    'czeka_na_wyciecie','czeka_na_skladanie','czeka_na_sklejanie',
    'czeka_na_formatowanie','czeka_na_krawedzie','czeka_na_wykanczanie',
    'czeka_na_lakiernie','czeka_na_logistyke','czeka_na_pakowanie',
    'spakowane','anulowane','wstrzymane','w_realizacji'
) NOT NULL DEFAULT 'czeka_na_wyciecie';

-- -- 2. Nazwy kolumn wstecz, jednym atomicznym ALTER-em -----------------------
-- Ten sam wzorzec co migracja (sekcja 6, recenzja 2026-09-15): jeden ALTER na
-- oba renamey zamiast dwoch osobnych blokow SET/PREPARE/EXECUTE/DEALLOCATE.
-- Dwa osobne ALTER-y dawaly okno miedzy nimi: zerwane polaczenie, restart
-- mysqld albo cokolwiek innego przerywajace rollback w tym miejscu zostawialoby
-- jedna kolumne juz cofnieta do starej nazwy, druga jeszcze pod nowa — kazde
-- zapytanie o prod_products lecialoby wtedy 1054 i modul produkcji byl martwy.
--
-- W ROLLBACKU TA SAMA WADA JEST GROZNIEJSZA NIZ W MIGRACJI, NIE LAGODNIEJSZA:
-- rollback odpala sie wtedy, gdy produkcja jest JUZ zepsuta (stad w ogole
-- decyzja o rollbacku), a operator naprawia ja pod presja czasu. To, ze patrzy
-- na wynik kazdego polecenia, nie powstrzymuje zerwanego polaczenia ani
-- restartu mysqld w polowie skryptu. Skrypt, ktory w polowie zostawia balagan,
-- jest w tym momencie najgorszym mozliwym narzedziem.
SET @kolumna_ilosci := (
    SELECT COUNT(*) FROM information_schema.COLUMNS
     WHERE TABLE_SCHEMA = DATABASE()
       AND TABLE_NAME = 'prod_products'
       AND COLUMN_NAME = 'quantity_done_edges');

SET @kolumna_daty := (
    SELECT COUNT(*) FROM information_schema.COLUMNS
     WHERE TABLE_SCHEMA = DATABASE()
       AND TABLE_NAME = 'prod_products'
       AND COLUMN_NAME = 'edges_completed_at');

-- OBA liczniki stoja PRZED zbudowaniem klauzul, tak samo jak w migracji:
-- policzony PO wykonaniu renamu patrzylby na schemat, ktory to polecenie
-- wlasnie zmienilo — po scaleniu obu renameow w jeden ALTER bylby to cichy blad.
SET @klauzule_renamu := CONCAT_WS(', ',
    IF(@kolumna_ilosci > 0, 'RENAME COLUMN quantity_done_edges TO quantity_done_finishing', NULL),
    IF(@kolumna_daty   > 0, 'RENAME COLUMN edges_completed_at TO finishing_completed_at',   NULL));

-- Puste klauzule = obie kolumny juz pod starymi nazwami (drugi przebieg
-- rollbacku): 'SELECT 1', dokladnie jak w dawnej oslonie. COALESCE to obrona
-- TEORETYCZNA, nie obserwowane zachowanie: CONCAT_WS(', ', NULL, NULL)
-- w MySQL 8.4 zwraca pusty string, nie NULL (zweryfikowane), wiec oba warunki
-- falszywe i tak dają '' = ''. Oslona zostaje mimo to — jest tania, a gdyby to
-- zachowanie kiedys przestalo byc prawdziwe, PREPARE z NULL-em konczy sie
-- bledem 1064.
SET @sql_renamu := IF(COALESCE(@klauzule_renamu, '') = '',
    'SELECT 1',
    CONCAT('ALTER TABLE prod_products ', @klauzule_renamu));

PREPARE polecenie_renamu FROM @sql_renamu;

EXECUTE polecenie_renamu;

DEALLOCATE PREPARE polecenie_renamu;

-- -- 3. Kolejka produktow -----------------------------------------------------
-- Najpierw dokladnie, z kopii (odroznia 'czeka_na_lakiernie' przeniesione
-- od tych, ktore tam staly wczesniej), potem catch-all.
--
-- ODSTEPSTWO OD SZKICU, SWIADOME: warunek na biezacy status. Bez niego pozycja,
-- ktora po migracji przeszla pod nowym kodem dalej (np. jest juz 'spakowane'),
-- zostalaby cofnieta do kolejki wykanczania — a tego rollback nie umie juz
-- odkrecic. Wiersze kopii maja stara_wartosc zawsze rowna 'czeka_na_wykanczanie',
-- wiec ograniczenie nie gubi nic, co migracja faktycznie ruszyla.
--
-- KTOREGO PRZYPADKU BRONI WASKA REGULA NIZEJ: produkt, ktorego migracja
-- postawila na 'czeka_na_krawedzie', po REALNIE WYKONANYM stanowisku Krawedzie
-- trafia pod nowym kodem na 'czeka_na_lakiernie' (models.py:566-568) — czyli
-- prosto w druga galaz warunku ponizej. Sama tabela kopii tych dwoch
-- przypadkow nie odroznia: kazdy wiersz ma stara_wartosc rowna
-- 'czeka_na_wykanczanie', niezaleznie od tego, na ktora galaz migracja go
-- wyslala. Odroznia je dopiero TA SAMA regula, ktorej migracja uzyla przy
-- rozdzielaniu kolejki (sekcja 1 pliku migracji): 'czeka_na_lakiernie'
-- osiagniete WPROST przez migracje ma parsed_edge_processing = 0 i olej/lakier
-- — taki wiersz bezpiecznie cofamy razem z 'czeka_na_krawedzie'.
-- 'czeka_na_lakiernie' osiagniete przez realne odbicie Krawedzi tej reguly nie
-- spelnia (parsed_edge_processing = 1) — takiego NIE cofamy: stanowisko zostalo
-- faktycznie wykonane, quantity_done_edges jest rowne quantity i data
-- zakonczenia ustawiona, a cofniecie wrocilo by z licznikiem mowiacym
-- "zrobione" do kolejki, w ktorej stanowisko dopiero czeka.
UPDATE prod_products p
  JOIN prod_migracja_krawedzie_kopia k
    ON k.tabela = 'prod_products' AND k.rekord_id = p.id
   SET p.current_status = k.stara_wartosc
 WHERE p.current_status = 'czeka_na_krawedzie'
    OR (p.current_status = 'czeka_na_lakiernie'
        AND p.parsed_edge_processing = 0
        AND p.parsed_finish_type IN ('olejowane','lakierowane'));

UPDATE prod_products SET current_status = 'czeka_na_wykanczanie'
 WHERE current_status = 'czeka_na_krawedzie';

-- -- 4. Historia stanowiskowa -------------------------------------------------
-- Wiersze historii sa niezmienne, wiec odtworzenie z kopii nie moze nadpisac
-- niczego nowszego — inaczej niz kolejka w kroku 3.
UPDATE prod_station_events e
  JOIN prod_migracja_krawedzie_kopia k
    ON k.tabela = 'prod_station_events' AND k.rekord_id = e.id
   SET e.station_code = k.stara_wartosc;

UPDATE prod_station_events SET station_code = 'finishing'
 WHERE station_code = 'edges';

-- -- 5. Urzadzenia, sesje, wydruki, uprawnienia, konfiguracja -----------------
UPDATE prod_devices SET station_code = 'finishing' WHERE station_code = 'edges';

UPDATE prod_worker_sessions SET station_code = 'finishing' WHERE station_code = 'edges';

UPDATE prod_print_queue SET station_code = 'finishing' WHERE station_code = 'edges';

UPDATE prod_workers
   SET allowed_stations = TRIM(BOTH ',' FROM
         REPLACE(CONCAT(',', allowed_stations, ','), ',edges,', ',finishing,'))
 WHERE allowed_stations LIKE '%edges%';

UPDATE prod_config
   SET config_value = TRIM(BOTH ',' FROM
         REPLACE(CONCAT(',', config_value, ','), ',edges,', ',finishing,'))
 WHERE config_key = 'LABEL_PRINTER_ALLOWED_STATIONS'
   AND CONCAT(',', config_value, ',') LIKE '%,edges,%';

-- Konwencja z sufiksem. '_EDGES' ma 6 znakow, '_FINISHING' ma 10.
UPDATE prod_config
   SET config_key = CONCAT(SUBSTRING(config_key, 1, CHAR_LENGTH(config_key) - 6), '_FINISHING')
 WHERE RIGHT(config_key, 6) = '_EDGES';

-- Konwencja z nazwa stanowiska w srodku. 'STATION_EDGES_' ma 14 znakow.
UPDATE prod_config
   SET config_key = CONCAT('STATION_FINISHING_', SUBSTRING(config_key, 15))
 WHERE LEFT(config_key, 14) = 'STATION_EDGES_';

-- -- 6. Enum stanowiska dorobki -----------------------------------------------
ALTER TABLE prod_rework_log MODIFY COLUMN rejected_at_station
    ENUM('formatting','edges','finishing','painting') NOT NULL;

UPDATE prod_rework_log SET rejected_at_station = 'finishing'
 WHERE rejected_at_station = 'edges';

ALTER TABLE prod_rework_log MODIFY COLUMN rejected_at_station
    ENUM('formatting','finishing','painting') NOT NULL;

-- -- 7. DOPIERO TERAZ zdjac 'czeka_na_krawedzie' z enuma statusu --------------
-- Blad 1265 tutaj znaczy, ze nowy kod wciaz chodzi i odtwarza wiersze.
-- Najpierw cofnij kod (git revert + deploy), potem powtorz to polecenie.
ALTER TABLE prod_products MODIFY COLUMN current_status ENUM(
    'czeka_na_wyciecie','czeka_na_skladanie','czeka_na_sklejanie',
    'czeka_na_formatowanie','czeka_na_wykanczanie',
    'czeka_na_lakiernie','czeka_na_logistyke','czeka_na_pakowanie',
    'spakowane','anulowane','wstrzymane','w_realizacji'
) NOT NULL DEFAULT 'czeka_na_wyciecie';

-- -- 8. Zwolnienie wersji w rejestrze migracji --------------------------------
-- Bez tego poprawiona migracja JUZ NIGDY sie nie wykona: get_executed_migrations
-- filtruje po success=TRUE, wiec wpis z success=FALSE jest bezpieczny — problem
-- dotyczy wylacznie migracji UDANEJ, cofanej recznie.
-- Na bazie bez tej tabeli poleci 1146 i --force pojdzie dalej. Tak ma byc.
DELETE FROM schema_migrations WHERE version = '2026-09-15-krawedzie-podzial-wykanczania';
