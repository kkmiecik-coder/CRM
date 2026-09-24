-- Prywatny układ pulpitu Analizy sprzedażowej: jeden wiersz na użytkownika.
--
-- KONTEKST. W tym CRM-ie nie ma dziś ŻADNEGO mechanizmu ustawień per
-- użytkownik: `app_settings` i `calculator_settings` są globalne, a tabela
-- `users` nie ma kolumny na preferencje. Ta tabela jest pierwsza tego rodzaju.
--
-- DLACZEGO JEDEN WIERSZ Z DOKUMENTEM JSON, A NIE WIERSZ NA KAFELEK. Układ jest
-- zawsze czytany i zapisywany W CAŁOŚCI; żadne zapytanie nigdy nie pyta „kto
-- ma kafelek X". Wiersz na kafelek oznaczałby przy każdym przestawieniu
-- DELETE + N × INSERT, żeby utrzymać kolejność, i indeks porządkowy jako drugie
-- źródło prawdy obok kolejności wierszy. Kolejność listy JSON jest kolejnością
-- w siatce i nie ma z czym się rozjechać.
--
-- TYP JSON, NIE TEXT. MySQL sprawdza poprawność dokumentu przy zapisie, więc
-- uszkodzony zapis pada od razu, zamiast ulec zapisaniu i wybuchnąć przy
-- następnym odczycie. W repo jest precedens (db.JSON w pięciu modelach).
-- UWAGA: testy jadą na SQLite, która trzyma to jako TEXT i NICZEGO nie
-- sprawdza — dlatego zadanie ma osobny krok wykonania na prawdziwym MySQL-u.
--
-- UNIKALNOŚĆ user_id. Jeden układ na użytkownika. Bez tego dwa równoległe
-- zapisy z dwóch kart przeglądarki zostawiłyby dwa wiersze, a odczyt
-- (`.first()` bez ORDER BY) wybierałby niedeterministycznie.
--
-- KASKADA NA users. Skasowanie użytkownika zabiera jego układ. Nazwy
-- ograniczeń są JAWNE (uq_rdl_user, fk_rdl_user), bo `db.create_all()`
-- nadałby własne (reports_dashboard_layouts_ibfk_1) i schemat z migracji
-- różniłby się od schematu z metadanych — dokładnie ten rozjazd wyszedł
-- 21.09.2026 przy sales_orders.
--
-- IDEMPOTENCJA. Runner wykonuje cały katalog przy KAŻDYM deployu. Nie używamy
-- wariantu CREATE TABLE „jeśli jeszcze nie istnieje": przy RUN_DB_SETUP=true
-- `db.create_all()` (app.py) odpala się PRZED migracjami przy każdej komendzie
-- `flask`, więc taki warunek bywa no-opem, a plik z błędem składni przechodzi
-- lokalnie niezauważony. (Samej frazy nie cytujemy — test pilnuje, żeby nie
-- było jej nigdzie w pliku, tak jak słowa zmieniającego separator poleceń.)
-- Warunek budujemy z information_schema i wykonujemy przez
-- PREPARE/EXECUTE/DEALLOCATE (zmiany separatora poleceń runner nie obsługuje)
-- — ten sam wzorzec co `migrations/2026-09-22-clients-na-leads.sql`.
--
-- Odczyt z information_schema może zostać ZWYKŁYM `SET`: pyta katalog
-- systemowy, nie tworzoną tabelę, więc błąd 1146 mu nie grozi.
--
-- Napis w gałęzi „tabela już istnieje" stoi w PODWOJONYCH APOSTROFACH, nie
-- w cudzysłowie: przy sql_mode z ANSI_QUOTES cudzysłów oznacza identyfikator
-- i ta gałąź padłaby błędem nieznanej kolumny. Ten sam zapis, co we wdrożonych
-- migracjach (np. 2026-09-18-print-queue-product-id.sql). Runner nie liczy
-- sum kontrolnych plików (schema_migrations trzyma samą nazwę), więc zmiana
-- treści już wykonanej lokalnie migracji niczego nie psuje.

SET @tabela_istnieje = (
    SELECT COUNT(*) FROM information_schema.TABLES
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'reports_dashboard_layouts'
);

SET @sql = IF(@tabela_istnieje = 0,
    'CREATE TABLE reports_dashboard_layouts (
        id INT NOT NULL AUTO_INCREMENT,
        user_id INT NOT NULL,
        uklad JSON NOT NULL,
        updated_at DATETIME NOT NULL,
        PRIMARY KEY (id),
        UNIQUE KEY uq_rdl_user (user_id),
        CONSTRAINT fk_rdl_user FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci',
    'SELECT ''tabela reports_dashboard_layouts juz istnieje - pomijam'' AS info');

PREPARE zaloz_uklady FROM @sql;
EXECUTE zaloz_uklady;
DEALLOCATE PREPARE zaloz_uklady;
