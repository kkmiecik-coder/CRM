-- Migracja: trakownia — obwód w środku kłody -> średnica w środku kłody
-- Data: 2026-09-12
-- Opis: Zarząd zmienił metodykę pomiaru surowca. Pracownik przestaje mierzyć
--       obwód taśmą, a zaczyna mierzyć średnicę na środku kłody (jeden odczyt,
--       bez korekty owalności). Metoda objętości pozostaje Hubera, zmienia się
--       tylko wielkość wejściowa:
--           bylo:  V = (C/100)^2 / (4*pi) * (L/100)
--           jest:  V = pi/4 * (d/100)^2 * (L/100)
--
--       Razem z kolumną zmieniają się limity walidacji: zamiast
--       min/max_circumference_cm (30 / brak) wchodzą min/max_diameter_cm
--       (15 / 250). Górny limit przestaje być nullem — średnica powyżej 250 cm
--       to prawie na pewno wpisany obwód zamiast średnicy, czyli najczęstszy
--       błąd po tej zmianie.
--
-- UWAGA — MIGRACJA KASUJE DANE TRAKOWNI.
--       Trakownia nie weszła jeszcze na halę, więc nie ma historii wartej
--       przenoszenia, a decyzją właściciela zaczynamy od zera. Kasowanie jest
--       konieczne, nie kosmetyczne: zastane wartości to OBWODY, a po zmianie
--       kolumny byłyby czytane jako ŚREDNICE — objętość każdej takiej kłody
--       urosłaby o czynnik pi^2/4 (~2,47x) i poszła w rozliczenie z dostawcą.
--       Czyszczone są pomiary, audyt, zlecenia, dostawy i licznik numeracji
--       (nowe zlecenia startują od numeru 1). Słowniki — dostawcy i gatunki —
--       ZOSTAJĄ, to dane referencyjne, nie transakcyjne.
--
-- Idempotentność: DELETE-y są bezwarunkowe, ale po pierwszym przebiegu nie mają
--       już czego kasować (nowe zlecenia powstaną dopiero po wdrożeniu, a
--       migracja nie wykona się drugi raz — schema_migrations). Zmiana kolumny
--       jest osłoniona warunkiem na jej istnienie, podmiana ustawień działa na
--       kluczu prod_config i jest powtarzalna.
-- Zmiana separatora poleceń jest tu celowo pominięta — runner jej nie obsługuje.

-- ── Czyszczenie danych ──────────────────────────────────────────────────────
-- Kolejność zgodna z kluczami obcymi: pomiary -> zlecenia -> dostawy.
-- Audyt nie ma FK na zlecenie (ma przeżyć jego usunięcie), więc idzie osobno.
DELETE FROM `prod_sawmill_logs`;

DELETE FROM `prod_sawmill_audit`;

DELETE FROM `prod_sawmill_orders`;

DELETE FROM `prod_sawmill_deliveries`;

DELETE FROM `prod_sawmill_counters`;

-- ── Zmiana kolumny pomiaru ──────────────────────────────────────────────────
SET @stara_kolumna := (
    SELECT COUNT(*) FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'prod_sawmill_logs'
      AND COLUMN_NAME = 'mid_circumference_cm'
);

SET @sql_rename := IF(@stara_kolumna > 0,
    'ALTER TABLE prod_sawmill_logs CHANGE COLUMN mid_circumference_cm mid_diameter_cm DECIMAL(6,1) NOT NULL COMMENT ''Srednica w polowie dlugosci klody (metoda Hubera)''',
    'SELECT 1');

PREPARE polecenie_rename FROM @sql_rename;

EXECUTE polecenie_rename;

DEALLOCATE PREPARE polecenie_rename;

-- ── Limity walidacji ────────────────────────────────────────────────────────
-- Pełna podmiana wartości, nie JSON_SET na pojedynczych kluczach: stare klucze
-- min/max_circumference_cm muszą ZNIKNĄĆ, bo get_sawmill_settings() nakłada
-- zawartość bazy na wartości domyślne i zostawione śmieci wracałyby w payloadzie
-- wysyłanym na tablet.
UPDATE `prod_config`
SET `config_value` = '{"min_diameter_cm": 15.0, "max_diameter_cm": 250.0, "min_length_cm": 30.0, "max_length_cm": 20000.0, "decimal_places": 1, "deviation_threshold_pct": 5.0}'
WHERE `config_key` = 'sawmill_settings';
