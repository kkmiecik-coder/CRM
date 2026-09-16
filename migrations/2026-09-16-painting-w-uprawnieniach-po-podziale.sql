-- Migracja: przywrocenie dostepu do Lakierni po podziale Wykanczania
-- Data: 2026-09-16
--
-- Tabela: prod_workers (kolumna allowed_stations).
--
-- MUSI ISC PO 2026-09-15-krawedzie-podzial-wykanczania.sql — dopiero tamta
-- przepisuje 'finishing' na 'edges', a ta naprawia skutek tego przepisania.
-- Kolejnosc zapewnia data w nazwie pliku.
--
-- DLACZEGO. Tamta migracja przepisuje allowed_stations jeden do jednego:
-- 'finishing' -> 'edges'. Ale 'finishing' bylo JEDNYM stanowiskiem obslugujacym
-- OBIE czynnosci (tablet ogarnial je przez STATION_GROUPS), a po podziale sa
-- dwa kody. Pracownik z jawnym 'finishing' dostaje wiec wylacznie 'edges'
-- i po cichu traci Lakiernie — jedno uprawnienie na dwa stanowiska.
-- Tamta migracja NAZYWA to ryzyko w naglowku (sekcja o swiadomej stracie)
-- i uznaje za bezskutkowe, bo w zrzucie z 2026-09-14 wszystkie wiersze
-- mialy allowed_stations = NULL, a NULL/pusty CSV znaczy "wszystkie".
--
-- ZALOZENIE JUZ NIEAKTUALNE. 2026-09-16 na produkcji sa TRZY wiersze z jawna
-- lista, zalozone tego samego dnia, kazdy z 'finishing':
--   id 21 Mateusz Litwin  cutting,assembly,finishing,packaging
--   id 22 Marek Ochman    formatting,finishing,packaging
--   id 23 Janusz Kruk     finishing,packaging
-- Bez tej migracji cala trojka po wdrozeniu traci Lakiernie.
-- To PRZYWROCENIE dostepu, ktory maja dzis, a nie nowe uprawnienie.
--
-- DLACZEGO WARUNEK, A NIE LISTA ID. Dopoki podzial nie jest wdrozony, kodu
-- 'painting' nie da sie nikomu nadac recznie — nie istnieje jeszcze jako
-- wybieralne stanowisko. Kazde 'edges' w jawnej liscie w momencie wdrozenia
-- pochodzi wiec z przepisania 'finishing' i ma prawo do obu polowek.
-- Warunek naprawia klase problemu; lista ID naprawilaby trzy jego wystapienia.
--
-- IDEMPOTENTNOSC. Warunek wymaga BRAKU 'painting', wiec drugi przebieg trafia
-- w zero wierszy. Porownania na CSV owinietym przecinkami (wzorzec z migracji
-- podzialu), zeby nie zlapac kodu bedacego fragmentem innego.

UPDATE prod_workers
   SET allowed_stations = CONCAT(allowed_stations, ',painting')
 WHERE allowed_stations IS NOT NULL
   AND allowed_stations <> ''
   AND CONCAT(',', allowed_stations, ',') LIKE '%,edges,%'
   AND CONCAT(',', allowed_stations, ',') NOT LIKE '%,painting,%';
