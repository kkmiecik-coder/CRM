-- Terminy zamówień w bazie (decyzja Konrada 5.10, spec priorytetów 2026-10-04, 4.3): surowe 10, z wykończeniem
-- 14 dni (roboczych albo kalendarzowych — DEADLINE_DAY_TYPE). Zmienia się je w Konfiguracji → „Terminy”, bez wdrożenia.
-- INSERT IGNORE: wiersz, który już jest (na produkcji DEADLINE_DEFAULT_DAYS = 10), zostaje bez zmian; zakładany jest
-- tylko brakujący (na produkcji DEADLINE_FINISHED_DAYS — do dziś działało 21 z kodu). Wartości awaryjne w kodzie
-- (gdy wiersza brak) też 10 / 14. Stary kod (`main` sprzed priorytetów) czyta te same wiersze — po wycofaniu
-- wdrożenia terminy zostają 10 / 14.
INSERT IGNORE INTO prod_config (config_key, config_value, config_description, config_type, created_at, updated_at)
VALUES ('DEADLINE_DEFAULT_DAYS', '10', 'Terminy: dni do terminu zamówienia surowego (bez wykończenia)', 'integer', NOW(), NOW()),
       ('DEADLINE_FINISHED_DAYS', '14', 'Terminy: dni do terminu zamówienia z choć jedną pozycją wykończoną', 'integer', NOW(), NOW());
