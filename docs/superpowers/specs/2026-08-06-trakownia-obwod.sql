-- ===========================================================================
-- Trakownia — zmiana metodyki pomiaru na obwód w połowie długości (Huber).
--
-- Pracownik podaje odtąd WYŁĄCZNIE dwie liczby: długość i obwód w środku
-- kłody. Cztery kolumny średnic znikają, wchodzi jedna `mid_circumference_cm`.
--
-- UWAGA: skrypt KASUJE wszystkie dane trakowni. Starych pomiarów nie da się
-- przeliczyć na obwód bez zgadywania (z czterech średnic obwód wychodzi tylko
-- dla idealnie okrągłej kłody), a moduł nie był jeszcze wdrożony na
-- produkcji — kasujemy świadomie, decyzja właściciela projektu.
--
-- Uruchamiać na bazie, na której wykonano już `2026-08-05-trakownia.sql`.
-- Na czystej bazie NIE uruchamiaj tego pliku — tam wystarczy sam
-- `2026-08-05-trakownia.sql`, który jest już zaktualizowany do nowej metodyki.
-- ===========================================================================

-- 1. Czyszczenie danych. Kolejność od dzieci do rodziców — bez wyłączania
--    sprawdzania kluczy obcych, żeby błąd w kolejności ujawnił się głośno,
--    zamiast zostawić osierocone wiersze.
DELETE FROM `prod_sawmill_audit`;
DELETE FROM `prod_sawmill_logs`;
DELETE FROM `prod_sawmill_orders`;
DELETE FROM `prod_sawmill_deliveries`;

-- Numeracja TRK/RRRR/NNN rusza od 001 — inaczej pierwsze zlecenie po
-- czyszczeniu dostałoby numer sprzed kasowania i wyglądało na zgubione.
DELETE FROM `prod_sawmill_counters`;

ALTER TABLE `prod_sawmill_audit` AUTO_INCREMENT = 1;
ALTER TABLE `prod_sawmill_logs` AUTO_INCREMENT = 1;
ALTER TABLE `prod_sawmill_orders` AUTO_INCREMENT = 1;
ALTER TABLE `prod_sawmill_deliveries` AUTO_INCREMENT = 1;

-- 2. Schemat pomiaru: cztery średnice → jeden obwód.
ALTER TABLE `prod_sawmill_logs`
  DROP COLUMN `butt_d1_cm`,
  DROP COLUMN `butt_d2_cm`,
  DROP COLUMN `top_d1_cm`,
  DROP COLUMN `top_d2_cm`,
  ADD COLUMN `mid_circumference_cm` DECIMAL(6,1) NOT NULL AFTER `sequence_no`;

-- 3. Limity walidacji. Obwód bez górnego limitu (null = „nie sprawdzaj") —
--    nietypowo gruba kłoda ma przejść bez interwencji biura.
UPDATE `prod_config`
SET `config_value` = '{"min_circumference_cm": 30.0, "max_circumference_cm": null, "min_length_cm": 30.0, "max_length_cm": 20000.0, "decimal_places": 1, "deviation_threshold_pct": 5.0}'
WHERE `config_key` = 'sawmill_settings';
