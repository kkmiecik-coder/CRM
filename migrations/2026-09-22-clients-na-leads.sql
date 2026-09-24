-- `clients` -> `leads`.
--
-- Tabela trzyma rejestr WYCENIANYCH, nie kupujących: jest zasilana wyłącznie
-- z procesu wyceny, więc kupujący ze sklepu i Allegro nigdy do niej nie
-- trafiali. Zmierzone 21.09.2026: tylko 593 z 2557 e-maili z raportu
-- sprzedażowego (23,2%) ma tu odpowiednik. Klienci sprzedażowi dostają własną
-- tabelę `sales_clients`, a te dwie łączy opcjonalne `sales_clients.lead_id`.
--
-- Zasięg zmiany: JEDEN klucz obcy (quotes.client_id, ograniczenie
-- quotes_ibfk_1), który MySQL przepina sam przy RENAME TABLE. Klasa modelu
-- (Client), katalog modułu i URL /clients zostają — ich przemianowanie to
-- osobne zadanie, niezwiązane z tą przebudową.
--
-- IDEMPOTENCJA: RENAME TABLE nie ma wariantu IF EXISTS, więc budujemy
-- instrukcję warunkowo z information_schema i wykonujemy przez PREPARE.
-- Ta droga nie wymaga zmiany separatora poleceń, której runner nie obsługuje.
-- (information_schema jest dostępne na VPS-ie — sprawdzone 21.09.2026,
-- stara blokada zniknęła razem z hostingiem współdzielonym.)
--
-- SAMOLECZENIE (dopisane 22.09.2026, po zablokowanym deployu): `db.create_all()`
-- w app.py (uruchamiane, gdy RUN_DB_SETUP=true) odpala się przy KAŻDEJ
-- komendzie `flask` — w tym przy samym `flask migrate` — PRZED tym, jak ta
-- migracja w ogóle dostanie szansę się wykonać. Metadane SQLAlchemy znają już
-- `leads` (zmieniony __tablename__ modelu), więc create_all() na bazie
-- sprzed migracji tworzy PUSTĄ tabelę `leads`, zanim RENAME zdąży cokolwiek
-- zrobić. Pierwsza wersja tej migracji na taki stan reagowała twardym
-- błędem — bezpiecznym, ale ślepym zaułkiem: `get_executed_migrations()`
-- filtruje `WHERE success = TRUE`, więc nieudana migracja wraca do kolejki
-- przy KAŻDYM kolejnym deployu i pada identycznie, blokując też zmiany
-- zupełnie niezwiązane z tą gałęzią. Jedyne odblokowanie było ręczne: DROP
-- TABLE leads na serwerze.
--
-- Pusta `leads` OBOK `clients` z danymi to jednoznaczna sygnatura tego
-- zatrucia — nie ma innego mechanizmu w tej aplikacji, który wytworzyłby
-- dokładnie taki układ. Migracja rozpoznaje go i naprawia się sama (krok 3
-- niżej). Gdy `leads` ma jakiekolwiek wiersze, układ przestaje być
-- jednoznaczny (mógł powstać z zupełnie innego powodu) i migracja nadal ma
-- PRZERYWAĆ się błędem — zgadywanie w takiej sytuacji groziłoby cichą
-- utratą danych.

-- KROK 1: odczytujemy, czy istnieje `clients` i czy istnieje `leads`.
SET @clients_istnieje = (
    SELECT COUNT(*) FROM information_schema.TABLES
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'clients'
);
SET @leads_istnieje = (
    SELECT COUNT(*) FROM information_schema.TABLES
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'leads'
);

-- KROK 2: liczymy wiersze w `leads`, ale TYLKO gdy tabela istnieje — gołe
-- `SELECT COUNT(*) FROM leads` na bazie, gdzie jej nie ma, kończy się błędem
-- 1146 (Table doesn't exist) i przerywa cały plik. Zapytanie budujemy więc
-- warunkowo i puszczamy tą samą drogą PREPARE/EXECUTE co resztę migracji.
SET @leads_wierszy = 0;
SET @sql_licz = IF(@leads_istnieje = 1,
    'SELECT COUNT(*) INTO @leads_wierszy FROM leads',
    'SELECT 0 INTO @leads_wierszy');
PREPARE licz FROM @sql_licz;
EXECUTE licz;
DEALLOCATE PREPARE licz;

-- KROK 3: SAMOLECZENIE. `clients` istnieje, `leads` istnieje i jest PUSTA —
-- to dokładnie ślad create_all() opisany wyżej: nic innego w tej aplikacji
-- nie zakłada tabeli `leads` bez ani jednego wiersza, podczas gdy `clients`
-- wciąż stoi obok z danymi. Skoro `leads` jest pusta, nie ma w niej niczego
-- do stracenia — usunięcie jej i przejście do zwykłego RENAME w kroku 5/6
-- jest bezpieczne: oddaje bazę do stanu, w jakim byłaby, gdyby create_all()
-- nigdy nie zdążył jej dotknąć.
SET @sql_uzdrow = IF(@clients_istnieje = 1 AND @leads_istnieje = 1 AND @leads_wierszy = 0,
    'DROP TABLE leads',
    'SELECT "brak sygnatury zatrucia create_all - pomijam samoleczenie" AS info');
PREPARE uzdrow FROM @sql_uzdrow;
EXECUTE uzdrow;
DEALLOCATE PREPARE uzdrow;

-- KROK 4: odczytujemy istnienie `leads` PONOWNIE — po ewentualnym DROP-ie
-- z kroku 3 flaga ustawiona w kroku 1 jest już nieaktualna.
SET @leads_istnieje = (
    SELECT COUNT(*) FROM information_schema.TABLES
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'leads'
);

-- KROK 5 i 6: właściwy rename oraz twarde zatrzymanie na przypadku, który
-- samoleczenie z kroku 3 świadomie zostawiło nietknięty.
--   * `clients` istnieje, `leads` (po kroku 4) już NIE istnieje -> zwykły
--     RENAME. Obejmuje zarówno czysty pierwszy przebieg (leads nigdy nie
--     istniało), jak i przebieg po samoleczeniu (leads istniało, było puste
--     i właśnie zniknęło w kroku 3).
--   * `leads` istnieje, `clients` NIE istnieje -> migracja już przeszła
--     wcześniej, legalny stan końcowy, cicho pomijamy.
--   * `clients` NADAL istnieje, a `leads` PO KROKU 4 też NADAL istnieje ->
--     skoro krok 3 nie usunął tej `leads`, to znaczy, że nie była pusta,
--     czyli @leads_wierszy > 0. To już nie jest zatrucie przez create_all()
--     (ono zawsze zostawia tabelę pustą) — sytuacja jest naprawdę
--     niejednoznaczna i nie wolno w niej zgadywać. Przerywamy błędem na
--     tabeli-sygnale, której nazwa mówi wprost, co się stało: `leads` ma
--     dane, więc automatyczny rename byłby nadpisaniem czyjejś zawartości.
--   * żadna z tabel nie istnieje -> czysta instalacja albo katalog migracji
--     puszczony na pustej bazie, nic do zrobienia.
SET @sql = CASE
    WHEN @clients_istnieje = 1 AND @leads_istnieje = 0
        THEN 'RENAME TABLE clients TO leads'
    WHEN @leads_istnieje = 1 AND @clients_istnieje = 0
        THEN 'SELECT "leads juz istnieje - pomijam rename" AS info'
    WHEN @clients_istnieje = 1 AND @leads_istnieje = 1
        THEN 'SELECT * FROM BLAD_MIGRACJI_leads_ma_dane_a_clients_wciaz_istnieje'
    ELSE
        'SELECT "brak clients i leads - pomijam rename (czysta instalacja albo juz po migracji)" AS info'
END;
PREPARE zmien FROM @sql;
EXECUTE zmien;
DEALLOCATE PREPARE zmien;

-- Po ewentualnym RENAME odświeżamy flagę istnienia `leads` — wartość
-- z kroku 4 pochodzi sprzed EXECUTE i w gałęzi RENAME jest już nieaktualna
-- (tabela dopiero co powstała pod tą nazwą).
SET @leads_istnieje = (
    SELECT COUNT(*) FROM information_schema.TABLES
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'leads'
);

-- KROK 7: created_at — bez zmian względem poprzedniej wersji migracji.
-- Tabela nie miała daty założenia wcale, więc nie dało się policzyć
-- konwersji lead -> klient w czasie. NULL dla istniejących wierszy jest
-- uczciwszy niż zmyślona data.
--
-- Sprawdzamy ISTNIENIE TABELI `leads` (@leads_istnieje powyżej), nie tylko
-- brak kolumny: gdy `leads` w ogóle nie istnieje (baza bez clients i bez
-- leads — świeża instalacja albo katalog migracji puszczony na pustej
-- bazie), information_schema.COLUMNS też nie zwróci ani jednego wiersza dla
-- created_at, więc sam brak kolumny fałszywie wygląda jak "trzeba dodać".
-- ALTER TABLE na nieistniejącej tabeli kończy się błędem MySQL 1146
-- (Table doesn't exist) i przerywa deploy — stąd dodatkowy warunek.
SET @brak_kolumny = (
    SELECT COUNT(*) = 0 FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'leads'
      AND COLUMN_NAME = 'created_at'
);

SET @sql2 = CASE
    WHEN @leads_istnieje = 0
        THEN 'SELECT "tabela leads nie istnieje - pomijam dodanie created_at" AS info'
    WHEN @brak_kolumny
        THEN 'ALTER TABLE leads ADD COLUMN created_at DATETIME NULL'
    ELSE
        'SELECT "created_at juz istnieje - pomijam" AS info'
END;
PREPARE dodaj FROM @sql2;
EXECUTE dodaj;
DEALLOCATE PREPARE dodaj;
