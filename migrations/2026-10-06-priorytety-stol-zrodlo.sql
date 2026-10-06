-- Priorytety produkcji, krok K3 (spec 2026-10-04-priorytety-produkcji-design.md, sekcje 5.1, 5.7, 5.8, 8.3, 8.4):
-- źródło kafla na stole stanowiska i akcje logu „Wyślij na stanowisko”, „Zdejmij ze stołu”, start stołów.
-- Idempotentna: ADD COLUMN osłonięte warunkiem z information_schema przez PREPARE/EXECUTE (bez zmiany separatora
-- poleceń), MODIFY enuma jest idempotentny sam z siebie. Obie tabele zakłada migracja 2026-10-05-priorytety-produkcji
-- w TYM SAMYM wdrożeniu, więc stary kod ich nie zna i zmiana listy wartości niczego mu nie psuje.

-- 8.4 Stół: skąd kafel się wziął — 'kolejka' (dopełnienie), 'dorobka', 'biuro' („Wyślij na stanowisko”), 'start'
-- (kafle rozpoczęte przy przejściu na stoły). Wiersze sprzed tej migracji są z dopełnienia, stąd DEFAULT.
SET @brak = (SELECT COUNT(*) = 0 FROM information_schema.COLUMNS
             WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'prod_station_desk' AND COLUMN_NAME = 'zrodlo');
SET @sql = IF(@brak, 'ALTER TABLE prod_station_desk ADD COLUMN zrodlo VARCHAR(16) NOT NULL DEFAULT ''kolejka''',
              'SELECT ''zrodlo juz jest'' AS info');
PREPARE krok FROM @sql; EXECUTE krok; DEALLOCATE PREPARE krok;

-- Kto wysłał kafel na stół albo przygotował stoły (users.id); NULL dla kafli z kolejki i doróbek.
SET @brak = (SELECT COUNT(*) = 0 FROM information_schema.COLUMNS
             WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'prod_station_desk'
               AND COLUMN_NAME = 'sent_by_user_id');
SET @sql = IF(@brak, 'ALTER TABLE prod_station_desk ADD COLUMN sent_by_user_id INT NULL',
              'SELECT ''sent_by_user_id juz jest'' AS info');
PREPARE krok FROM @sql; EXECUTE krok; DEALLOCATE PREPARE krok;

-- 8.3 Log: trzy akcje NA KOŃCU listy (same metadane). Lista MUSI zawierać wszystkie dotychczasowe wartości —
-- MODIFY podaje pełną listę, a brakująca wartość skasowałaby akcję wpisom w logu.
ALTER TABLE prod_priority_log MODIFY action
    ENUM('gwiazdki','szczebel','odlozenie','odlozenie_zamkniete','ustawienia','przeliczenie',
         'wyslanie','zdjecie','start_stolow') NOT NULL;
