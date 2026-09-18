-- Migracja: stan druku etykiet PER SZTUKA
-- Data: 2026-09-18
--
-- Tabele: prod_products (label_printed_units), prod_print_queue (label_index).
--
-- DLACZEGO. Dotad wiedzielismy TYLKO ILE etykiet pozycji wyszlo
-- (label_print_count), co wystarczalo, dopoki druk szedl zawsze od pierwszej
-- sztuki. Panel kafelkow aplikacji stanowiskowej pozwala operatorowi dotknac
-- dowolnej sztuki, wiec liczba przestaje wystarczac — trzeba wiedziec, KTORE.
--
-- STAN IDZIE NA POZYCJE, NIE DO KOLEJKI. prod_print_queue jest dziennikiem
-- zadan, a nie stanem: 3810 wpisow historycznych nie ma label_index, tryb
-- bezpośredni po TCP w ogole nie tworzy w nim wierszy, a log kiedys ktos
-- przytnie. Wyprowadzanie z niego biezacego stanu bylo by tym samym, co
-- liczenie salda z listy przelewow.
--
-- label_index w kolejce sluzy WYLACZNIE cofaniu: gdy zadanie sie nie powiedzie
-- albo wygasnie, trzeba odznaczyc konkretna sztuke, a nie ogon prefiksu.
--
-- NUMERY SA LOKALNE (1..quantity), nie globalne. Numer globalny — ten na
-- papierze — zalezy od offsetu pozycji w zamowieniu, a offset rosnie, gdy
-- BaseLinker dolozy do zamowienia nowa pozycje. Zapisany numer globalny
-- przestalby wtedy wskazywac te sama sztuke i nikt by tego nie powiazal
-- z dolozeniem pozycji. Przeliczenie robimy na wejsciu i wyjsciu z API.
--
-- BACKFILL Z PREFIKSU. Istniejacym pozycjom wpisujemy pierwsze
-- min(label_print_count, quantity) sztuk — czyli dokladnie to, co dzis
-- oznacza licznik. Nie udajemy, ze wiemy wiecej, niz wiedzielismy: 212 pozycji
-- ma licznik WIEKSZY od liczby sztuk (przedruki), wiec clamp jest konieczny,
-- inaczej zbior zawieralby sztuki, ktorych pozycja nie ma.
--
-- label_print_count ZOSTAJE. Jest wyprowadzalny z dlugosci zbioru, ale czytaja
-- go tez panel webowy i wyniki serwisu druku. Backfill go NIE przelicza —
-- zostaje jako wartosc historyczna i zbiega sie z nowa przy pierwszej zmianie.
--
-- IDEMPOTENTNOSC. Dodanie kolumn oslonione warunkiem na information_schema;
-- backfill ma warunek na NULL, wiec drugi przebieg obejmuje zero wierszy
-- i nie nadpisze zbioru zmienionego juz przez operatorow.

SET @ma_units = (
    SELECT COUNT(*) FROM information_schema.COLUMNS
     WHERE TABLE_SCHEMA = DATABASE()
       AND TABLE_NAME = 'prod_products'
       AND COLUMN_NAME = 'label_printed_units'
);

SET @sql = IF(@ma_units = 0,
    'ALTER TABLE prod_products ADD COLUMN label_printed_units JSON NULL COMMENT ''Wydrukowane sztuki, numery LOKALNE 1..quantity''',
    'SELECT ''label_printed_units juz istnieje — pomijam''');
PREPARE s1 FROM @sql; EXECUTE s1; DEALLOCATE PREPARE s1;

SET @ma_index = (
    SELECT COUNT(*) FROM information_schema.COLUMNS
     WHERE TABLE_SCHEMA = DATABASE()
       AND TABLE_NAME = 'prod_print_queue'
       AND COLUMN_NAME = 'label_index'
);

SET @sql2 = IF(@ma_index = 0,
    'ALTER TABLE prod_print_queue ADD COLUMN label_index INT NULL COMMENT ''Numer LOKALNY sztuki, ktorej dotyczy zadanie — do cofania''',
    'SELECT ''label_index juz istnieje — pomijam''');
PREPARE s2 FROM @sql2; EXECUTE s2; DEALLOCATE PREPARE s2;

-- Backfill: pierwsze min(licznik, quantity) sztuk jako JSON-owa tablica.
-- JSON_ARRAYAGG po wygenerowanym szeregu 1..16 — 16 z zapasem, bo najwieksza
-- pozycja w historii ma 50 sztuk, ale licznik ponad 16 przy jednej pozycji
-- nie wystepuje, a tabela liczb wiekszego zakresu nie jest tu warta zachodu.
UPDATE prod_products p
   SET p.label_printed_units = (
       SELECT JSON_ARRAYAGG(n.i)
         FROM (SELECT 1 AS i UNION ALL SELECT 2 UNION ALL SELECT 3 UNION ALL
               SELECT 4 UNION ALL SELECT 5 UNION ALL SELECT 6 UNION ALL
               SELECT 7 UNION ALL SELECT 8 UNION ALL SELECT 9 UNION ALL
               SELECT 10 UNION ALL SELECT 11 UNION ALL SELECT 12 UNION ALL
               SELECT 13 UNION ALL SELECT 14 UNION ALL SELECT 15 UNION ALL
               SELECT 16) AS n
        WHERE n.i <= LEAST(p.label_print_count, COALESCE(p.quantity, 1))
   )
 WHERE p.label_printed_units IS NULL
   AND p.label_print_count > 0;

-- Pozycje nigdy nie drukowane dostaja pusty zbior zamiast NULL-a, zeby kod
-- nie musial rozrozniac "nie drukowano" od "nie wiadomo".
UPDATE prod_products
   SET label_printed_units = JSON_ARRAY()
 WHERE label_printed_units IS NULL;
