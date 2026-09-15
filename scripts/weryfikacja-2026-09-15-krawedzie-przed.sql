-- Zestaw kontrolny PRZED migracja 2026-09-15-krawedzie-podzial-wykanczania.sql
-- WYLACZNIE ODCZYT, STARY schemat. Bezpieczny do wklejenia na produkcji.
-- Punkt 2 kolejnosci wdrozenia.
--
-- Uruchomienie lokalnie:
--   docker compose exec -T db mysql -uroot woodpower_crm_local < scripts/weryfikacja-2026-09-15-krawedzie-przed.sql

-- A1. Rozklad kolejki wykanczania wg reguly trojdzielnej.
-- Wiersze z parsed_edge_processing=0 i olejem/lakierem pojda na Lakiernie,
-- cala reszta na Krawedzie.
SELECT parsed_edge_processing, parsed_finish_type, COUNT(*) AS ile
  FROM prod_products
 WHERE current_status = 'czeka_na_wykanczanie'
 GROUP BY parsed_edge_processing, parsed_finish_type;

-- A2. Produkty CZESCIOWO odbite w kolejce — najbardziej ryzykowny przypadek
-- migracji (ryzyko R8b: sztuki, ktorych fizycznie nie wykonczono, przeskocza
-- stanowisko). Wynik niepusty = przelozyc wdrozenie albo dokonczyc te sztuki.
SELECT id, short_product_id, quantity, quantity_done_finishing, parsed_finish_type
  FROM prod_products
 WHERE current_status = 'czeka_na_wykanczanie'
   AND quantity_done_finishing > 0;

-- A3. Wszystkie rodzaje wykonczenia w bazie. Wartosc spoza
-- ('surowe','olejowane','lakierowane') znaczy, ze regula trojdzielna ma luke.
SELECT parsed_finish_type, COUNT(*) AS ile FROM prod_products GROUP BY parsed_finish_type;

-- A4. Kody stanowisk w historii. 'edges' MUSI byc nieobecne przed migracja;
-- liczba wierszy 'finishing' to podstawa bilansu z sekcji "po" (B5).
SELECT station_code, COUNT(*) AS ile FROM prod_station_events GROUP BY station_code;

-- A5. Tablety. Po migracji kazdy wiersz 'finishing' ma byc 'edges'.
SELECT station_code, COUNT(*) AS ile FROM prod_devices GROUP BY station_code;

-- A6. Sesje pracownikow — przepisywane hurtem, swiadoma strata (ryzyko R20).
SELECT station_code, COUNT(*) AS ile FROM prod_worker_sessions GROUP BY station_code;

-- A7. Uprawnienia pracownikow (CSV). Wartosc runtime — grep po repo jej nie znajdzie.
SELECT id, first_name, last_name, allowed_stations
  FROM prod_workers
 WHERE allowed_stations IS NOT NULL;

-- A8. Enum dorobki. Wartosc inna niz 'formatting' znaczy, ze zwezenie enuma
-- w sekcji 4 migracji poleci bledem 1265 i PRZERWIE deploy (ryzyko R22).
SELECT rejected_at_station, COUNT(*) AS ile FROM prod_rework_log GROUP BY rejected_at_station;

-- A9. Wartosci runtime w prod_config — OBIE konwencje kluczy naraz.
SELECT config_key, config_value
  FROM prod_config
 WHERE config_key = 'LABEL_PRINTER_ALLOWED_STATIONS'
    OR RIGHT(config_key, 10) = '_FINISHING'
    OR LEFT(config_key, 18) = 'STATION_FINISHING_';

-- A10. Kolizja kluczy: gdyby klucz w NOWEJ konwencji juz istnial, UPDATE
-- przemianowujacy poleci bledem 1062 (config_key ma UNIQUE). Ma byc pusto.
SELECT config_key FROM prod_config
 WHERE RIGHT(config_key, 6) = '_EDGES'
    OR LEFT(config_key, 14) = 'STATION_EDGES_';

-- A11. Kolejka wydruku etykiet — defensywnie, 'finishing' nigdy tam nie bylo.
SELECT station_code, COUNT(*) AS ile FROM prod_print_queue GROUP BY station_code;

-- A12. Produkty wstrzymane i anulowane. Enum nie pamieta, gdzie staly przed
-- wstrzymaniem — po odwieszeniu panel moze probowac ustawic stary status
-- i wywalic caly batch (ryzyko R10).
SELECT current_status, COUNT(*) AS ile FROM prod_products
 WHERE current_status IN ('wstrzymane','anulowane')
 GROUP BY current_status;
