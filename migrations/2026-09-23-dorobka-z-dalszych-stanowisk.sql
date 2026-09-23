-- Migracja: cofanie do doróbki z dalszych stanowisk
-- Data: 2026-09-23
--
-- Tabela: prod_rework_log (enumy rejected_at_station i reason_category).
--
-- DLACZEGO. Do dziś sztukę do doróbki cofało wyłącznie formatowanie. Od tej
-- zmiany cofają też sklejanie, krawędzie, lakiernia i pakowanie
-- (rework_service.VALID_REJECT_STATIONS), więc enum stanowiska dostaje
-- 'gluing' i 'packaging' ('edges' i 'painting' były w nim od 2026-09-15).
-- Dochodzą też dwie przyczyny dla dalszych stanowisk: jakość krawędzi
-- i jakość lakierowania.
--
-- NOWE WARTOŚCI NA KOŃCU. Dopisanie na końcu listy ENUM nie zmienia numerów
-- istniejących wartości, więc MySQL nie przepisuje tabeli, a stare wiersze
-- czytają się bez zmian. Kolejność pilnowana testem modelu.
--
-- IDEMPOTENTNOŚĆ. MODIFY do tej samej definicji przy drugim przebiegu nic nie
-- zmienia — lista jest nadzbiorem poprzedniej, więc żaden wiersz nie wypada.
--
-- KOLEJNOŚĆ Z DEPLOYEM. Migracja idzie PRZED restartem (deploy.sh), a stary
-- kod nie zapisuje nowych wartości, więc okna wyścigu nie ma.

ALTER TABLE prod_rework_log MODIFY COLUMN rejected_at_station
    ENUM('formatting','edges','painting','gluing','packaging') NOT NULL;

ALTER TABLE prod_rework_log MODIFY COLUMN reason_category
    ENUM('wymiary','jakosc_sklejenia','jakosc_produktu','inne',
         'jakosc_krawedzi','jakosc_lakierowania') NOT NULL;
