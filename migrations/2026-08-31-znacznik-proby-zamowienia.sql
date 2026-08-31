-- Znacznik próby złożenia zamówienia na wycenie (quotes.order_attempt_started_at).
--
-- Po co: jedyny trwały ślad próby zamówienia powstawał dotąd PO awarii —
-- w obsłudze wyjątku, w zapisie awaryjnym numeru, we wpisie `uncertain`
-- w baselinker_order_logs. Czyli dokładnie wtedy, gdy niesprawna bywała
-- właśnie baza. Gdy padł też ten zapis, do bazy nie trafiało NIC, a klient
-- po odświeżeniu strony dostawał z powrotem przycisk „Zamów" i składał
-- DRUGIE realne zamówienie w BaseLinkerze.
--
-- Ta kolumna trzyma chwilę (UTC) rozpoczęcia próby, zapisaną i zacommitowaną
-- ZANIM poleci addOrder. Nie ma NULL-owego znaczenia „w toku vs nierozstrzygnięta"
-- — o wyborze komunikatu decyduje wiek znacznika (checkout_service.stan_proby),
-- a blokują oba stany tak samo. Znacznik zdejmuje sukces albo pewność, że
-- zamówienia nie ma.
--
-- Idempotentność: ALTER osłonięty warunkiem na istnienie kolumny
-- (information_schema), wykonywany przez PREPARE/EXECUTE — dokładnie ten sam
-- wzorzec co migrations/2026-08-21-prod-products-shape-rotation.sql. Powtórne
-- uruchomienie pliku nie rusza wartości zapisanych już przez aplikację.
-- Zmiana separatora poleceń (DELIMITER) jest tu celowo pominięta — runner
-- jej nie obsługuje.

SET @kolumna_istnieje := (
    SELECT COUNT(*) FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'quotes'
      AND COLUMN_NAME = 'order_attempt_started_at'
);

SET @sql_dodaj := IF(@kolumna_istnieje = 0,
    'ALTER TABLE quotes ADD COLUMN order_attempt_started_at DATETIME NULL DEFAULT NULL',
    'SELECT 1');

PREPARE polecenie_dodaj FROM @sql_dodaj;

EXECUTE polecenie_dodaj;

DEALLOCATE PREPARE polecenie_dodaj;
