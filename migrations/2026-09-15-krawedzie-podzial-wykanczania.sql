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
--   sekcja 5 zdejmuje stara DOPIERO gdy nikt jej nie trzyma — i robi to PRZED
--   renameem kolumn w sekcji 6.
--
--   UZASADNIENIE, BEZ SLOWA "JEDYNY". Polecen dlugo trwajacych albo bioracych
--   ciezki lock jest w tym pliku kilka: UPDATE przepisujacy historie
--   stanowiskowa (prod_station_events JOIN prod_products, 2687 wierszy
--   w zrzucie z 2026-09-14), oba ALTER-y enuma prod_rework_log (MODIFY
--   wymusza ALGORITHM=COPY), zwezajacy ALTER enuma current_status (to samo)
--   oraz sam RENAME COLUMN — ten tabeli nie przepisuje, ale bierze wylaczny
--   metadata lock i czeka na dlugie transakcje tak samo jak reszta. Kazde
--   z nich moze pasc z przyczyn NIEZWIAZANYCH z trescia (1205/1206 —
--   metadata lock na zywej tabeli); zwezajacy ALTER dodatkowo na 1265
--   (resztkowe okno wyscigu, opisane przy sekcji 5).
--
--   Dlatego regula nie brzmi "po sekcji 1 jest jedno ryzykowne polecenie",
--   tylko: WSZYSTKIE polecenia zdolne pasc z przyczyn niezwiazanych z trescia
--   stoja PRZED renameem, a sam rename jest od recenzji 2026-09-15 atomiczny
--   (jeden ALTER na obie kolumny). Padniecie gdziekolwiek przed renameem
--   kosztuje kilka pozycji na nieznanym statusie przy dzialajacej aplikacji
--   i schemacie, ktory stary kod dalej czyta; padniecie PO renameie (dawna
--   kolejnosc sekcji 5 i 6, przed recenzja 2026-09-15) zostawialoby
--   przemianowany schemat pod starym kodem gunicorna —
--   quantity_done_finishing juz by nie istnialo, wiec kazde zapytanie
--   o prod_products lecialoby 1054, a caly modul produkcji byl martwy
--   do recznego rollbacku,
--   sekcje 1-4 nie dotykaja ani quantity_done_finishing, ani
--   finishing_completed_at — zadne z ich polecen nie odwoluje sie do tych
--   kolumn, wiec to NIE jest zaleznosc od tego, gdzie stoi rename (sekcja 6).
--   Od STAREJ nazwy kolumny zalezy wylacznie zapytanie A2 w
--   scripts/weryfikacja-2026-09-15-krawedzie-przed.sql:19 i :22 — i to jest
--   jedyny powod, dla ktorego skrypty kontrolne sa dwa, a nie jeden.
--
-- Zmiany separatora polecen ten plik celowo nie uzywa — runner rozpoznaje
-- wylacznie srednik, a test ksztaltu migracji szuka tamtego slowa w calej
-- tresci pliku, razem z komentarzami.
--
-- SWIADOMA STRATA: sesje pracownika (prod_worker_sessions) przepisujemy hurtem
-- na 'edges'. Tablet 'finishing' obslugiwal przez STATION_GROUPS oba stanowiska,
-- a sesja to przedzial CZASU, nie produkt — rozdzielic sie tego nie da.
-- Statystyki czasu pracy sprzed rozdzialu zawyza Krawedzie kosztem Lakierni
-- (ryzyko R20). Ten sam rodzaj przepisania (sekcja 3) dotyka tez
-- prod_workers.allowed_stations: pracownik z jawnym 'finishing' na liscie
-- dostaje po migracji wylacznie 'edges', po cichu tracac Lakiernie — to
-- podzial jednego stanowiska na dwa przy jednym uprawnieniu. Dzis bez skutku
-- (w zrzucie z 2026-09-14 wszystkie wiersze maja allowed_stations = NULL,
-- a NULL/pusty CSV znaczy "wszystkie stanowiska", models.py:1332) i zgodne
-- z jednokierunkowym kontraktem aliasu, ale ma zostac nazwane.
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

-- WERYFIKACJA LOKALNA — SCHEMAT I DANE (MySQL 8.4, kontener db, kopia produkcji
-- z 2026-09-14): SIEDEM przebiegow migracji, kazdy zakonczony '✓ Sukces', ani
-- razu '✗ Blad'. Poza dwoma przebiegami wymaganymi przez plan sprawdzone tez:
--   * PELNA PETLA migracja -> scripts/rollback-2026-09-15-krawedzie.sql ->
--     migracja. Skrypt kontrolny "przed" po rollbacku daje wyjscie identyczne
--     CO DO BAJTU ze stanem wyjsciowym (to samo md5), a skrypt "po" ponownej
--     migracji — identyczne z pierwszym przebiegiem. Jedyna roznica miedzy
--     wyjsciami "po" to executed_at w schema_migrations, ktore z definicji
--     jest nowe. Rollback przeszedl TRZY razy, za kazdym razem bez ani jednego
--     komunikatu bledu mimo obowiazkowej flagi --force;
--   * OSLONA TROJSTANOWA SEKCJI 6 w OBU galeziach stanu polowicznego, recznie
--     wytworzonego (zaden normalny przebieg tam nie wchodzi): raz cofnieta sama
--     kolumna ilosci (quantity_done_edges -> quantity_done_finishing, data
--     zostaje nowa), raz sama data (edges_completed_at -> finishing_completed_at,
--     licznik zostaje nowy). Migracja w obu wypadkach dokonczyla rename i obie
--     kolumny wyladowaly pod NOWYMI nazwami;
--   * ta sama para stanow polowicznych dla ROLLBACKU — konczy sie sukcesem
--     i obiema kolumnami pod STARYMI nazwami.
-- Po migracji: 0 wierszy 'czeka_na_wykanczanie', 0 eventow 'finishing',
-- bilans 2687 = 2553 na Krawedziach + 134 na Lakierni (zaden wiersz nie zginal),
-- kolumny quantity_done_edges i edges_completed_at obecne, enum dorobki zwezony,
-- tabela kopii 2 / 5 / 2687 / 133 — bez przyrostu przy powtorkach (INSERT IGNORE).

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
-- Nowa wartosc WCHODZI, stara ZOSTAJE do sekcji 5. Wstawienie w srodek listy
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
-- (config_api.py:514-515). Klucza dla wykanczania panel dzis NIE wytworzy —
-- biala lista allowed_config_keys zaczyna sie w
-- modules/production/routers/api/config_api.py:503, a te trzy
-- klucze stoja w niej w liniach 514-515; wariantu FINISHING w niej nie ma. Obslugujemy mimo to obie konwencje, bo druga
-- konwencja kluczy ISTNIEJE w kodzie (ten sam wzorzec dla innych stanowisk),
-- a nie dlatego, ze panel mogl ten konkretny klucz kiedykolwiek zapisac.
-- Polecenie zostaje defensywnie — nic nie kosztuje, a zabezpiecza przed
-- przyszlym dopisaniem wariantu FINISHING do bialej listy.
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

-- == 5. Sweep wyscigu + zdjecie starej wartosci enuma ========================
-- Stary kod chodzi jeszcze w pamieci gunicorna w chwili migracji (deploy.sh:50
-- migruje PRZED restartem w linii 69) i mogl dopisac status miedzy sekcja 1
-- a tym miejscem. Sweep zamyka wiekszosc tego okna, ale go NIE domyka: miedzy
-- wykonaniem tego UPDATE-u a wykonaniem ponizszego ALTER-u zostaje resztkowe
-- okno (dwa osobne polecenia w tym samym polaczeniu), w ktorym stary kod wciaz
-- moze dopisac 'czeka_na_wykanczanie'. Trafienie w nie konczy sie bledem 1265
-- pod STRICT_TRANS_TABLES na TYM ALTERZE, nie gdzies indziej.
--
-- DLACZEGO TO JUZ NIE BOLI: ta sekcja stoi teraz PRZED renameem kolumn
-- (sekcja 6). Trafienie w resztkowe okno przerywa PLIK migracji tutaj — kolumny
-- sa jeszcze nieprzemianowane, aplikacja dalej dziala na starym kodzie
-- i starym schemacie. Cena to kilka pozycji do zlapania przy nastepnym
-- przebiegu migracji, dokladnie jak przy oknie sekcja 0 -> tu, nizej. Przed
-- przestawieniem tej sekcji przed rename (recenzja 2026-09-15, patrz naglowek
-- pliku) to samo trafienie padalo PO renameie: kolumny juz przemianowane,
-- stary kod gunicorna leci 1054 na kazdym zapytaniu o prod_products, caly
-- modul produkcji martwy do recznego rollbacku.
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

-- == 6. Nazwy kolumn =========================================================
-- RENAME COLUMN (nie CHANGE) zachowuje typ, NOT NULL, DEFAULT i komentarz.
-- Warunek na information_schema jak w 2026-08-21-prod-products-shape-rotation.
--
-- OD TEGO MIEJSCA schemat przestaje byc czytelny dla STAREGO kodu, a gunicorn
-- chodzi jeszcze wlasnie na nim (deploy.sh: `flask migrate` w linii 50, restart
-- w linii 69). Do tego miejsca zadnej kolumny nie ubylo — ale to dowodzi
-- WYLACZNIE zgodnosci SCHEMATU, nie zgodnosci z danymi, ktore ten schemat juz
-- przyjal. Sekcje 1-5 juz zapisaly 'czeka_na_krawedzie' do current_status
-- (sekcja 1, linie 135-137), a Enum(...) w wdrozonym models.py tej wartosci
-- nie zna. SQLAlchemy 1.4.54 rzuca LookupError w Enum._object_value_for_elem
-- (sqltypes.py, result_processor) przy KAZDEJ probie ODCZYTU takiego wiersza —
-- nie tylko przy zapisie na nim. To rozstrzyga swiat (A) nizej.
-- To OSTATNIA sekcja pliku.
--
-- OPERATORZE O 2 W NOCY — SA DWA SWIATY. DWA ZAPYTANIA ROZSTRZYGAJA KTORY,
-- BEZ ZGADYWANIA:
--   SHOW COLUMNS FROM prod_products LIKE 'quantity_done_%';
--   SELECT COUNT(*) FROM prod_products WHERE current_status = 'czeka_na_krawedzie';
--
--   Pierwsze zapytanie mowi, w ktorym SWIECIE jestes — czy rename z sekcji 6
--   sie wykonal. Drugie mierzy w swiecie (A) ROZMIAR SZKODY: ile wierszy ma
--   status, ktorego stary kod nie zna, czyli ile wierszy wywroci na ODCZYCIE
--   kazde zapytanie ORM, w ktorego wyniku sie znajda (0 = migracja padla,
--   zanim ktorykolwiek wiersz dostal nowa wartosc — modul dziala normalnie,
--   mimo failed migracji, dopoki taki wiersz nie powstanie).
--
--   (A) Widac quantity_done_finishing — migracja padla PRZED renameem.
--       Schemat jest juz zwezony (current_status i prod_rework_log), ale
--       MODUL PRODUKCJI NIE DZIALA NORMALNIE. Przyczyna to DANE, nie schemat:
--       kazde zapytanie ORM, ktorego WYNIK zawiera choc jeden wiersz ze
--       statusem 'czeka_na_krawedzie', wywraca sie na ODCZYCIE (LookupError,
--       patrz wyzej) — listy produktow, kolejki, panel admina, kazdy widok
--       czytajacy prod_products. To NIE jest blad 1265 na jednej akcji
--       tabletu: 1265 jest bledem ZAPISU nieznanej wartosci enuma, a tu zapis
--       juz sie udal (sekcje 1-5 dzialaly PRZED renameem) — pada dopiero
--       kolejny ODCZYT tego wiersza, i to na kazdym miejscu, ktore go czyta.
--       'czeka_na_lakiernie' tego problemu nie ma i nigdy nie mial: ta
--       wartosc jest w enumie origin/main od czasow, gdy Lakiernia byla
--       zakladka wykanczania — stary kod ja zna i czyta bez bledu.
--       Rozmiar, wedlug drugiego zapytania powyzej: garstka wierszy (w
--       zrzucie z 2026-09-14 to 3 z 5 pozycji kolejki wykanczania — te z
--       parsed_edge_processing=1; pozostale 2, bez krawedzi i z olejem albo
--       lakierem, ida na 'czeka_na_lakiernie' i nie sa problemem). Mala skala,
--       ale WYSTARCZY JEDEN taki wiersz w wyniku, zeby polozyc caly widok
--       listy — to nie jest awaria punktowa.
--       Rollback NIE jest potrzebny: usun przyczyne padniecia i pusc migracje
--       jeszcze raz. Jest idempotentna, a nieudany przebieg zostal zapisany
--       jako success=FALSE (migrations/migration_service.py:326-332);
--       get_executed_migrations filtruje po success = TRUE (:129), wiec ten
--       wpis nie blokuje kolejnego `flask migrate`.
--
--   (B) Widac quantity_done_edges — rename sie WYKONAL. Schemat jest nowy,
--       a gunicorn dalej chodzi na starym kodzie, bo deploy.sh restartuje
--       dopiero w linii 69 i przerwany deploy do tej linii nie dojdzie.
--       Stary kod pyta o quantity_done_finishing, ktorego juz nie ma — 1054
--       na kazdym zapytaniu o prod_products, caly modul produkcji martwy.
--       POTRZEBNY ROLLBACK (ryzyko R7): scripts/rollback-2026-09-15-krawedzie.sql
--       — albo dokonczenie deployu i restart, jesli reszta kodu jest juz
--       pobrana.
--
-- Trzeciego swiata — jedna kolumna przemianowana, druga nie — juz nie ma:
-- od recenzji 2026-09-15 oba renamey ida jednym, atomicznym ALTER-em.
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

-- OBA liczniki stoja PRZED zbudowaniem klauzul. W dawnej wersji (dwa osobne
-- bloki SET/PREPARE/EXECUTE/DEALLOCATE) ten liczyl kolumne juz PO wykonaniu
-- pierwszego renamu; po scaleniu obu renameow w jedno polecenie taka kolejnosc
-- bylaby cichym bledem — licznik patrzylby na schemat zmieniony przez ALTER,
-- ktory jeszcze sie nie wykonal.
SET @kolumna_daty := (
    SELECT COUNT(*) FROM information_schema.COLUMNS
     WHERE TABLE_SCHEMA = DATABASE()
       AND TABLE_NAME = 'prod_products'
       AND COLUMN_NAME = 'finishing_completed_at');

-- JEDEN ALTER NA OBA RENAMEY, CELOWO. DDL w MySQL 8 jest atomiczne, wiec ta
-- para kolumn zmienia nazwe w calosci albo wcale. Dwa osobne ALTER-y (wersja
-- przed recenzja 2026-09-15) dawaly okno miedzy nimi: zerwane polaczenie,
-- restart mysqld albo ubity deploy.sh zostawialy quantity_done_finishing juz
-- przemianowane, a finishing_completed_at jeszcze nie — stary kod gunicorna
-- lecial wtedy 1054 na KAZDYM zapytaniu o prod_products.
--
-- OSLONA TROJSTANOWA: CONCAT_WS pomija NULL-e, wiec jedno polecenie obsluguje
-- wszystkie cztery stany schematu — obie kolumny stare (pelny rename), tylko
-- jedna przemianowana (dokonczenie po przerwanym przebiegu, w obie strony),
-- obie nowe (drugi przebieg runnera, klauzule puste).
SET @klauzule_renamu := CONCAT_WS(', ',
    IF(@kolumna_ilosci > 0, 'RENAME COLUMN quantity_done_finishing TO quantity_done_edges', NULL),
    IF(@kolumna_daty   > 0, 'RENAME COLUMN finishing_completed_at TO edges_completed_at',   NULL));

-- Puste klauzule = nie ma czego przemianowac: 'SELECT 1', dokladnie jak
-- w dotychczasowej oslonie. COALESCE zostaje jako obrona TEORETYCZNA, nie
-- obserwowane zachowanie: CONCAT_WS(', ', NULL, NULL) w MySQL 8.4 zwraca
-- pusty string, nie NULL (zweryfikowane), wiec ponizszy warunek i tak trafia
-- w galaz '' = ''. Oslona zostaje mimo to — jest tania, a gdyby to
-- zachowanie kiedys przestalo byc prawdziwe, PREPARE z NULL-em konczy sie
-- bledem 1064 i przerwalby plik w polowie sekcji.
SET @sql_renamu := IF(COALESCE(@klauzule_renamu, '') = '',
    'SELECT 1',
    CONCAT('ALTER TABLE prod_products ', @klauzule_renamu));

PREPARE polecenie_renamu FROM @sql_renamu;

EXECUTE polecenie_renamu;

DEALLOCATE PREPARE polecenie_renamu;
