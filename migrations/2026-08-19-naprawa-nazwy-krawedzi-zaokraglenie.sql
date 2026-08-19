-- Migracja: Naprawa uszkodzonej nazwy krawędzi "Zaokrąglenie"
-- Data: 2026-08-19
-- Opis: W edge_options.name (type='round') zamiast "Zaokrąglenie" siedziało
--       "Zaokrą…glenie" — w środku wyrazu znak U+2026 (…) zamiast "g".
--       Nazwa jest widoczna w panelu ustawień i w GET /edges/options.
--       Skan całej bazy produkcyjnej (409 kolumn tekstowych) dał jedno
--       trafienie na U+2026, więc to jednorazowe uszkodzenie, nie problem
--       z kodowaniem połączenia.
--
-- Warunek na dokładną, uszkodzoną wartość zamiast na samym type='round':
-- migracja ma być idempotentna i nie może nadpisać nazwy, którą ktoś
-- świadomie zmieni w panelu po tym wdrożeniu.

UPDATE edge_options
SET name = 'Zaokrąglenie'
WHERE type = 'round' AND name = 'Zaokrą…glenie';
