-- Migracja: Wykanczanie -> Krawedzie + Lakiernia (podzial stanowiska)
-- Data: 2026-09-15
--
-- Tabele: prod_products, prod_station_events, prod_devices, prod_worker_sessions,
--         prod_workers, prod_print_queue, prod_rework_log, prod_config.
--
-- CALOSC W JEDNYM PLIKU CELOWO. run_pending_migrations po bledzie loguje,
-- zapisuje success=FALSE i PRZECHODZI DO NASTEPNEJ migracji
-- (migrations/migration_service.py:326-332). Przy podziale na 01..04 padniecie
-- pliku 01 nie powstrzymaloby pliku 03, ktory przemianowalby kolumny na
-- nieprzepisanej kolejce.
--
-- IDEMPOTENTNOSC — KAZDE POLECENIE OSOBNO. execute_sql_migration polyka
-- wylacznie bledy 'duplicate column' / 'duplicate key name' / 'already exists'
-- (:247-251); kazdy inny blad przerywa plik. Dlatego: CREATE TABLE ma
-- IF NOT EXISTS, wstawki sa INSERT IGNORE, kazdy UPDATE ma warunek na STARA
-- wartosc (drugi przebieg trafia w zero wierszy), a RENAME COLUMN jest
-- osloniety warunkiem na information_schema (wzorzec:
-- migrations/2026-08-21-prod-products-shape-rotation.sql).
--
-- KOLEJNOSC JEST OBOWIAZKOWA:
--   sekcja 0 robi kopie ZANIM cokolwiek sie zmieni,
--   sekcja 1 dodaje wartosc enuma ZANIM ktokolwiek ja zapisze,
--   sekcja 6 zdejmuje stara DOPIERO gdy nikt jej nie trzyma,
--   sekcje 1-4 operuja jeszcze STARA nazwa kolumny (rename jest w sekcji 5).
--
-- Zmiany separatora polecen ten plik celowo nie uzywa — runner rozpoznaje
-- wylacznie srednik, a test ksztaltu migracji szuka tamtego slowa w calej
-- tresci pliku, razem z komentarzami.
--
-- SWIADOMA STRATA: sesje pracownika (prod_worker_sessions) przepisujemy hurtem
-- na 'edges'. Tablet 'finishing' obslugiwal przez STATION_GROUPS oba stanowiska,
-- a sesja to przedzial CZASU, nie produkt — rozdzielic sie tego nie da.
-- Statystyki czasu pracy sprzed rozdzialu zawyza Krawedzie kosztem Lakierni
-- (ryzyko R20).
--
-- SWIADOMIE POZA ZAKRESEM: prod_security_events.station_type. To dziennik audytu
-- dostepu po IP, w zrzucie z 2026-09-14 zero wierszy 'finishing', a zaden
-- konsument nie czyta stamtad kodu stanowiska jako biezacego. Historyczny wpis
-- ma prawo pamietac kod z dnia zdarzenia.
--
-- DZIURA W AUDYCIE, SWIADOMA (ryzyko R21): product_events.py:22-25 sledzi
-- current_status przez before_flush SQLAlchemy. Ponizsze UPDATE-y sa surowym
-- SQL-em, wiec listener sie NIE odpali — w historii produktu ostatni wpis powie
-- "-> Czeka na wykanczanie", a nastepny zacznie sie od "Czeka na krawedzie ->".

-- == 0. Kopia na potrzeby rollbacku i audytu =================================
-- Przepisanie na 'painting' jest STRATNE: po fakcie nie odroznimy wierszy
-- ruszonych przez migracje od tych, ktore byly tam wczesniej. Tabela jest
-- jednoczesnie znacznikiem pozwalajacym pozniej rozdzielic metryki Lakierni
-- (ryzyko R16) i jedyna podstawa bilansu "zaden wiersz nie zginal".
-- Usuwa ja osobna, datowana migracja, nie wczesniej niz 2 tygodnie po wdrozeniu.
CREATE TABLE IF NOT EXISTS prod_migracja_krawedzie_kopia (
    tabela        VARCHAR(32) NOT NULL,
    rekord_id     INT         NOT NULL,
    stara_wartosc VARCHAR(40) NOT NULL,
    PRIMARY KEY (tabela, rekord_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

INSERT IGNORE INTO prod_migracja_krawedzie_kopia (tabela, rekord_id, stara_wartosc)
SELECT 'prod_products', id, current_status FROM prod_products
 WHERE current_status = 'czeka_na_wykanczanie';

INSERT IGNORE INTO prod_migracja_krawedzie_kopia (tabela, rekord_id, stara_wartosc)
SELECT 'prod_station_events', id, station_code FROM prod_station_events
 WHERE station_code = 'finishing';

INSERT IGNORE INTO prod_migracja_krawedzie_kopia (tabela, rekord_id, stara_wartosc)
SELECT 'prod_devices', id, station_code FROM prod_devices
 WHERE station_code = 'finishing';

INSERT IGNORE INTO prod_migracja_krawedzie_kopia (tabela, rekord_id, stara_wartosc)
SELECT 'prod_worker_sessions', id, station_code FROM prod_worker_sessions
 WHERE station_code = 'finishing';

-- == 1. Enum statusu + kolejka ===============================================
-- Nowa wartosc WCHODZI, stara ZOSTAJE do sekcji 6. Wstawienie w srodek listy
-- wymusza ALGORITHM=COPY (przenumerowanie porzadkowych enuma) — przy tej
-- wielkosci tabeli to milisekundy, a czytelnosc listy jest warta wiecej.
ALTER TABLE prod_products MODIFY COLUMN current_status ENUM(
    'czeka_na_wyciecie','czeka_na_skladanie','czeka_na_sklejanie',
    'czeka_na_formatowanie','czeka_na_krawedzie','czeka_na_wykanczanie',
    'czeka_na_lakiernie','czeka_na_logistyke','czeka_na_pakowanie',
    'spakowane','anulowane','wstrzymane','w_realizacji'
) NOT NULL DEFAULT 'czeka_na_wyciecie';

-- Najpierw przypadek waski: bez obrobki krawedzi, ale olejowane/lakierowane —
-- w nowym routingu takie produkty ida z formatowania prosto na lakiernie
-- (models.complete_task, blok `formatting` + should_skip_edges).
-- Licznika NIE zerujemy: rozjechalby sie z historia w prod_station_events
-- (raport "stan na koniec dnia" i modal produktu licza z eventow).
UPDATE prod_products
   SET current_status = 'czeka_na_lakiernie'
 WHERE current_status = 'czeka_na_wykanczanie'
   AND parsed_edge_processing = 0
   AND parsed_finish_type IN ('olejowane','lakierowane');

-- Reszta kolejki (z krawedziami; oraz teoretyczne "bez krawedzi + surowe",
-- ktorych stary routing nie mogl wytworzyc) staje na Krawedziach.
UPDATE prod_products
   SET current_status = 'czeka_na_krawedzie'
 WHERE current_status = 'czeka_na_wykanczanie';

-- == 2. Historia stanowiskowa ================================================
-- Ta sama regula co dla kolejki, liczona z BIEZACYCH pol produktu.
-- Kolejnosc ma znaczenie: drugie polecenie to catch-all.
--
-- SKUTEK DO WIEDZY (ryzyko R16): produkt bez krawedzi z olejem/lakierem
-- przechodzil DZIS realnie przez dwa stanowiska i na obu ma prawdziwe eventy
-- source='mobile'. Oba komplety skleja sie tu pod 'painting', wiec podzialy
-- raportow per stanowisko przesuna sie wstecz. Sumy globalne bez zmian.
-- Tabela kopii z sekcji 0 pozwala to pozniej rozdzielic — NIE USUWAC jej
-- pochopnie.
UPDATE prod_station_events e
  JOIN prod_products p ON p.id = e.production_item_id
   SET e.station_code = 'painting'
 WHERE e.station_code = 'finishing'
   AND p.parsed_edge_processing = 0
   AND p.parsed_finish_type IN ('olejowane','lakierowane');

-- Reszta, w tym sztuczne znaczniki auto-pomijania zapisywane przez stary kod
-- dla produktow surowych bez krawedzi (source='auto_skip'/'system').
UPDATE prod_station_events
   SET station_code = 'edges'
 WHERE station_code = 'finishing';

-- == 3. Urzadzenia, sesje, uprawnienia, wydruki, konfiguracja ================
UPDATE prod_devices SET station_code = 'edges' WHERE station_code = 'finishing';

-- Sesja to przedzial CZASU, nie produkt — reguly trojdzielnej nie da sie tu
-- zastosowac. Hurtem na Krawedzie, swiadoma strata opisana w naglowku (R20).
UPDATE prod_worker_sessions SET station_code = 'edges' WHERE station_code = 'finishing';

-- CSV bez spacji (worker_service._normalize_stations robi ','.join).
-- Przecinki-wartownicy lapia wartosc na poczatku i na koncu listy i chronia
-- przed trafieniem w podciag innego kodu.
UPDATE prod_workers
   SET allowed_stations = TRIM(BOTH ',' FROM
         REPLACE(CONCAT(',', allowed_stations, ','), ',finishing,', ',edges,'))
 WHERE allowed_stations LIKE '%finishing%';

-- Defensywnie: w zrzucie z 2026-09-14 kolejka wydruku nie ma ani jednego
-- wiersza 'finishing'. Zostaje, bo kosztuje zero, a brak kosztowalby 403.
UPDATE prod_print_queue SET station_code = 'edges' WHERE station_code = 'finishing';

-- Wartosc runtime edytowalna z panelu (config-tab-content.html) — grep po repo
-- jej nie znajdzie. Po rename wydruk z tego stanowiska leci 403 po cichu.
UPDATE prod_config
   SET config_value = TRIM(BOTH ',' FROM
         REPLACE(CONCAT(',', config_value, ','), ',finishing,', ',edges,'))
 WHERE config_key = 'LABEL_PRINTER_ALLOWED_STATIONS'
   AND CONCAT(',', config_value, ',') LIKE '%,finishing,%';

-- KONWENCJA PIERWSZA: klucz hierarchiczny {KEY}_{STATION_TYPE.upper()}, skladany
-- w config_service.get_config(..., station_type=...) — np.
-- STATION_ALLOWED_IPS_FINISHING. Bez tego stanowisko po cichu spada na wartosc
-- globalna, bez bledu i bez logu. RIGHT() zamiast LIKE, zeby nie walczyc
-- z podkresleniem jako wildcardem. '_FINISHING' ma 10 znakow.
UPDATE prod_config
   SET config_key = CONCAT(SUBSTRING(config_key, 1, CHAR_LENGTH(config_key) - 10), '_EDGES')
 WHERE RIGHT(config_key, 10) = '_FINISHING';

-- KONWENCJA DRUGA: nazwa stanowiska w SRODKU klucza — STATION_CUTTING_PRIORITY_SORT,
-- STATION_ASSEMBLY_PRIORITY_SORT, STATION_PACKAGING_PRIORITY_SORT
-- (config_api.py:514-515). Wariantu dla wykanczania dzis nie ma, ale kazdy zapis
-- z panelu moze go wytworzyc, wiec migracja obejmuje oba wzory.
-- 'STATION_FINISHING_' ma 18 znakow, 'STATION_EDGES_' ma 14.
UPDATE prod_config
   SET config_key = CONCAT('STATION_EDGES_', SUBSTRING(config_key, 19))
 WHERE LEFT(config_key, 18) = 'STATION_FINISHING_';

-- == 4. Enum stanowiska dorobki ==============================================
-- Ten sam schemat co dla statusu: rozszerz, przepisz, zwez.
-- W danych z 2026-09-14 rejected_at_station ma WYLACZNIE 'formatting'
-- (8 wierszy) — wartosc 'finishing' w enumie jest martwa. UPDATE jest wiec
-- defensywny, ale ALTER nie: po aliasie do routera moze trafic 'edges'
-- (mobile_api.py:450 to jedyny writer tego enuma).
ALTER TABLE prod_rework_log MODIFY COLUMN rejected_at_station
    ENUM('formatting','edges','finishing','painting') NOT NULL;

UPDATE prod_rework_log SET rejected_at_station = 'edges'
 WHERE rejected_at_station = 'finishing';

ALTER TABLE prod_rework_log MODIFY COLUMN rejected_at_station
    ENUM('formatting','edges','painting') NOT NULL;

-- == 5. Nazwy kolumn =========================================================
-- RENAME COLUMN (nie CHANGE) zachowuje typ, NOT NULL, DEFAULT i komentarz.
-- Warunek na information_schema jak w 2026-08-21-prod-products-shape-rotation.
--
-- OD TEGO MIEJSCA schemat jest juz NOWY, a gunicorn chodzi jeszcze na STARYM
-- kodzie (deploy.sh: `flask migrate` w linii 50, restart w linii 69). Przerwanie
-- migracji ponizej tej linii zostawia produkcje uszkodzona — patrz ryzyko R7
-- i scripts/rollback-2026-09-15-krawedzie.sql.
--
-- UWAGA NAZEWNICZA: obok siebie staja teraz parsed_edges_groups (dane produktu,
-- ksztalt krawedzi z wyceny) i quantity_done_edges (licznik STANOWISKA).
-- To dwa rozne znaczenia tego samego slowa — zaden sed po 'edges' na slepo.
-- Praktyczny skutek: `SHOW COLUMNS FROM prod_products LIKE '%edges%'` zwraca
-- parsed_edges_groups JUZ PRZED ta migracja, a po niej trzy wiersze, nie dwa.
SET @kolumna_ilosci := (
    SELECT COUNT(*) FROM information_schema.COLUMNS
     WHERE TABLE_SCHEMA = DATABASE()
       AND TABLE_NAME = 'prod_products'
       AND COLUMN_NAME = 'quantity_done_finishing');

SET @sql_ilosc := IF(@kolumna_ilosci > 0,
    'ALTER TABLE prod_products RENAME COLUMN quantity_done_finishing TO quantity_done_edges',
    'SELECT 1');

PREPARE polecenie_ilosc FROM @sql_ilosc;

EXECUTE polecenie_ilosc;

DEALLOCATE PREPARE polecenie_ilosc;

SET @kolumna_daty := (
    SELECT COUNT(*) FROM information_schema.COLUMNS
     WHERE TABLE_SCHEMA = DATABASE()
       AND TABLE_NAME = 'prod_products'
       AND COLUMN_NAME = 'finishing_completed_at');

SET @sql_data := IF(@kolumna_daty > 0,
    'ALTER TABLE prod_products RENAME COLUMN finishing_completed_at TO edges_completed_at',
    'SELECT 1');

PREPARE polecenie_data FROM @sql_data;

EXECUTE polecenie_data;

DEALLOCATE PREPARE polecenie_data;

-- == 6. Sweep wyscigu + zdjecie starej wartosci enuma ========================
-- Stary kod chodzi jeszcze w pamieci gunicorna w chwili migracji (deploy.sh:50
-- migruje PRZED restartem w linii 69) i mogl dopisac status miedzy sekcja 1
-- a tym miejscem. Bez sweepu ALTER polecialby bledem 1265 pod
-- STRICT_TRANS_TABLES i przerwal deploy tuz przed restartem (ryzyko R8c).
--
-- Wiersze zlapane DOPIERO tutaj nie maja swojego sladu w tabeli kopii — kopia
-- powstala w sekcji 0. Rollback cofnie je swoim catch-allem ('czeka_na_krawedzie'
-- -> 'czeka_na_wykanczanie'); te, ktore trafily na 'czeka_na_lakiernie',
-- zostana tam. Okno wyscigu to ulamek sekundy miedzy sekcja 0 a ta linia,
-- wiec cena jest znana i przyjeta.
UPDATE prod_products SET current_status = 'czeka_na_lakiernie'
 WHERE current_status = 'czeka_na_wykanczanie'
   AND parsed_edge_processing = 0
   AND parsed_finish_type IN ('olejowane','lakierowane');

UPDATE prod_products SET current_status = 'czeka_na_krawedzie'
 WHERE current_status = 'czeka_na_wykanczanie';

ALTER TABLE prod_products MODIFY COLUMN current_status ENUM(
    'czeka_na_wyciecie','czeka_na_skladanie','czeka_na_sklejanie',
    'czeka_na_formatowanie','czeka_na_krawedzie','czeka_na_lakiernie',
    'czeka_na_logistyke','czeka_na_pakowanie',
    'spakowane','anulowane','wstrzymane','w_realizacji'
) NOT NULL DEFAULT 'czeka_na_wyciecie';
