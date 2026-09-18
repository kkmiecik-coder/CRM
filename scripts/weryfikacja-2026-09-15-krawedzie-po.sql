-- Zestaw kontrolny PO migracji 2026-09-15-krawedzie-podzial-wykanczania.sql
-- WYLACZNIE ODCZYT, NOWY schemat. Zero odwolan do starych nazw kolumn,
-- wiec dziala bez flagi --force. Punkt 14a kolejnosci wdrozenia.
--
-- Uruchomienie lokalnie:
--   docker compose exec -T db mysql -uroot woodpower_crm_local < scripts/weryfikacja-2026-09-15-krawedzie-po.sql

-- B1. Kolejka: zero wierszy na starym statusie.
-- Porownanie do literalu spoza enuma jest legalne i zwraca 0 bez ostrzezenia.
SELECT COUNT(*) AS powinno_byc_zero FROM prod_products
 WHERE current_status = 'czeka_na_wykanczanie';

-- B2. Gdzie stanela kolejka po rozdzieleniu.
SELECT current_status, COUNT(*) AS ile FROM prod_products
 WHERE current_status IN ('czeka_na_krawedzie','czeka_na_lakiernie')
 GROUP BY current_status;

-- B3. Historia: zero wierszy ze starym kodem.
SELECT COUNT(*) AS powinno_byc_zero FROM prod_station_events
 WHERE station_code = 'finishing';

-- B4. Urzadzenia, sesje, wydruki: zero wierszy ze starym kodem.
SELECT
  (SELECT COUNT(*) FROM prod_devices         WHERE station_code = 'finishing') AS urzadzenia,
  (SELECT COUNT(*) FROM prod_worker_sessions WHERE station_code = 'finishing') AS sesje,
  (SELECT COUNT(*) FROM prod_print_queue     WHERE station_code = 'finishing') AS wydruki;

-- B5. BILANS — jedyne zapytanie lapiace ZGUBIENIE wiersza.
-- Musi zachodzic: w_kopii = trafilo_na_krawedzie + trafilo_na_lakiernie.
-- Wszystkie trzy liczby licza sie w JEDNYM poleceniu, z tej samej tabeli kopii
-- i z tego samego momentu — trzy osobne SELECT-y dowodzilyby mniej.
SELECT
  (SELECT COUNT(*) FROM prod_migracja_krawedzie_kopia
    WHERE tabela = 'prod_station_events')                          AS w_kopii,
  (SELECT COUNT(*) FROM prod_station_events e
     JOIN prod_migracja_krawedzie_kopia k
       ON k.tabela = 'prod_station_events' AND k.rekord_id = e.id
    WHERE e.station_code = 'edges')                                AS trafilo_na_krawedzie,
  (SELECT COUNT(*) FROM prod_station_events e
     JOIN prod_migracja_krawedzie_kopia k
       ON k.tabela = 'prod_station_events' AND k.rekord_id = e.id
    WHERE e.station_code = 'painting')                             AS trafilo_na_lakiernie;

-- B6. Rozklad kodow po migracji. Suma edges + przyrost painting ma sie zgadzac
-- z liczba wierszy 'finishing' z zapytania A4.
SELECT station_code, COUNT(*) AS ile FROM prod_station_events GROUP BY station_code;

-- B7. Stare kolumny znikaja. Ma byc PUSTO.
SHOW COLUMNS FROM prod_products LIKE '%finishing%';

-- B8. Nowe kolumny sa. UWAGA: to zapytanie zwraca TRZY wiersze, nie dwa —
-- quantity_done_edges, edges_completed_at ORAZ parsed_edges_groups.
-- Ten ostatni to dane produktu (ksztalt krawedzi z wyceny), byl tam zawsze
-- i migracji nie dotyczy. Przed migracja to zapytanie zwraca wlasnie jego.
SHOW COLUMNS FROM prod_products LIKE '%edges%';

-- B9. Enum statusu bez starej wartosci.
SELECT COLUMN_TYPE FROM information_schema.COLUMNS
 WHERE TABLE_SCHEMA = DATABASE()
   AND TABLE_NAME = 'prod_products'
   AND COLUMN_NAME = 'current_status';

-- B10. Enum dorobki: ma byc enum('formatting','edges','painting').
SELECT COLUMN_TYPE FROM information_schema.COLUMNS
 WHERE TABLE_SCHEMA = DATABASE()
   AND TABLE_NAME = 'prod_rework_log'
   AND COLUMN_NAME = 'rejected_at_station';

-- B11. Konfiguracja po obu konwencjach — nowe klucze i CSV drukarki.
SELECT config_key, config_value FROM prod_config
 WHERE config_key = 'LABEL_PRINTER_ALLOWED_STATIONS'
    OR RIGHT(config_key, 6) = '_EDGES'
    OR LEFT(config_key, 14) = 'STATION_EDGES_';

-- B12. Uprawnienia pracownikow: zero CSV ze starym kodem.
SELECT id, allowed_stations FROM prod_workers
 WHERE allowed_stations LIKE '%finishing%';

-- B13. Rejestr migracji: wpis udany, bez komunikatu bledu.
SELECT version, success, error_message, executed_at
  FROM schema_migrations
 WHERE version = '2026-09-15-krawedzie-podzial-wykanczania';

-- B14. Tabela kopii — ile wierszy da sie jeszcze cofnac i rozdzielic w metrykach.
-- NIE USUWAC wczesniej niz 2 tygodnie po wdrozeniu (ryzyko R16).
SELECT tabela, COUNT(*) AS ile FROM prod_migracja_krawedzie_kopia GROUP BY tabela;

-- B15. BILANS prod_products — symetria do B5. B5 dowodzi, ze zaden EVENT nie
-- zginal; ponizej to samo dla pozycji KOLEJKI. Pokazuje, gdzie wyladowal kazdy
-- produkt z tabeli kopii (current_status po migracji) i wylapuje zgubiona
-- pozycje: wiersz z wyladowal_na = NULL to produkt z kopii bez odpowiednika
-- w prod_products. Takiego wiersza NIE MA PRAWA byc w wyniku.
SELECT p.current_status AS wyladowal_na, COUNT(*) AS ile
  FROM prod_migracja_krawedzie_kopia k
  LEFT JOIN prod_products p ON p.id = k.rekord_id
 WHERE k.tabela = 'prod_products'
 GROUP BY p.current_status;
