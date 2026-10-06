-- Priorytety produkcji P1 (spec 2026-10-04-priorytety-produkcji-design.md, sekcja 8): gwiazdki i pamięć podręczna
-- rangi na zamówieniu, drabina szczebli, log priorytetów, stół stanowiska, ustawienia w prod_config.
-- Idempotentna: kolumny i indeks prod_orders osłonięte warunkiem z information_schema przez PREPARE/EXECUTE (bez
-- zmiany separatora poleceń), tabele przez CREATE TABLE IF NOT EXISTS, wiersze przez INSERT IGNORE. Żadnej zmiany
-- typu ani listy wartości na istniejących tabelach — stary kod w oknie wdrożenia niczego nowego nie zobaczy (8.7).

-- 8.1 prod_orders: gwiazdki 0–5 (ustawia biuro) oraz ranga i szczebel zamówienia (pamięć podręczna, liczy ją
-- wyłącznie priorytety.services.kolejka.utrwal). Kolumny na końcu tabeli — w MySQL 8 bez przebudowy tabeli.
SET @brak = (SELECT COUNT(*) = 0 FROM information_schema.COLUMNS
             WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'prod_orders' AND COLUMN_NAME = 'priority_stars');
SET @sql = IF(@brak, 'ALTER TABLE prod_orders ADD COLUMN priority_stars TINYINT NOT NULL DEFAULT 0',
              'SELECT ''priority_stars juz jest'' AS info');
PREPARE krok FROM @sql; EXECUTE krok; DEALLOCATE PREPARE krok;

SET @brak = (SELECT COUNT(*) = 0 FROM information_schema.COLUMNS
             WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'prod_orders' AND COLUMN_NAME = 'priority_stars_set_at');
SET @sql = IF(@brak, 'ALTER TABLE prod_orders ADD COLUMN priority_stars_set_at DATETIME NULL',
              'SELECT ''priority_stars_set_at juz jest'' AS info');
PREPARE krok FROM @sql; EXECUTE krok; DEALLOCATE PREPARE krok;

SET @brak = (SELECT COUNT(*) = 0 FROM information_schema.COLUMNS
             WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'prod_orders' AND COLUMN_NAME = 'priority_stars_set_by');
SET @sql = IF(@brak, 'ALTER TABLE prod_orders ADD COLUMN priority_stars_set_by INT NULL',
              'SELECT ''priority_stars_set_by juz jest'' AS info');
PREPARE krok FROM @sql; EXECUTE krok; DEALLOCATE PREPARE krok;

SET @brak = (SELECT COUNT(*) = 0 FROM information_schema.COLUMNS
             WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'prod_orders' AND COLUMN_NAME = 'priority_rank');
SET @sql = IF(@brak, 'ALTER TABLE prod_orders ADD COLUMN priority_rank INT NULL',
              'SELECT ''priority_rank juz jest'' AS info');
PREPARE krok FROM @sql; EXECUTE krok; DEALLOCATE PREPARE krok;

SET @brak = (SELECT COUNT(*) = 0 FROM information_schema.COLUMNS
             WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'prod_orders' AND COLUMN_NAME = 'priority_rung');
SET @sql = IF(@brak, 'ALTER TABLE prod_orders ADD COLUMN priority_rung INT NULL',
              'SELECT ''priority_rung juz jest'' AS info');
PREPARE krok FROM @sql; EXECUTE krok; DEALLOCATE PREPARE krok;

-- Indeks rangi zamówienia (Lista produkcyjna sortuje po niej w SQL). Dodanie indeksu InnoDB idzie online.
SET @brak = (SELECT COUNT(*) = 0 FROM information_schema.STATISTICS
             WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'prod_orders'
               AND INDEX_NAME = 'ix_prod_orders_priority_rank');
SET @sql = IF(@brak, 'ALTER TABLE prod_orders ADD INDEX ix_prod_orders_priority_rank (priority_rank)',
              'SELECT ''ix_prod_orders_priority_rank juz jest'' AS info');
PREPARE krok FROM @sql; EXECUTE krok; DEALLOCATE PREPARE krok;

-- 8.2 Drabina: szczeble gwiazdek (stałe), tagów i tras (ruchome). position renumerowane 1..n przy każdym zapisie.
-- Każdy rodzaj ma własny klucz unikalny (gwiazdki: kind+stars, tagi: kind+tag, trasy: route_id) — NULL w cudzym
-- kluczu nie przeszkadza.
CREATE TABLE IF NOT EXISTS prod_priority_rungs (
    id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    kind ENUM('stars','tag','route') NOT NULL,
    stars TINYINT NULL,
    tag VARCHAR(32) NULL,
    route_id INT NULL,
    position INT NOT NULL,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NULL,
    updated_by INT NULL,
    UNIQUE KEY uq_prod_priority_rungs_stars (kind, stars),
    UNIQUE KEY uq_prod_priority_rungs_tag (kind, tag),
    UNIQUE KEY uq_prod_priority_rungs_route (route_id),
    CONSTRAINT fk_prod_priority_rungs_route FOREIGN KEY (route_id)
        REFERENCES prod_routes (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 8.3 Log priorytetów: gwiazdki, przesunięcia szczebli, odłożenia, ustawienia, ręczne przeliczenia.
CREATE TABLE IF NOT EXISTS prod_priority_log (
    id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    action ENUM('gwiazdki','szczebel','odlozenie','odlozenie_zamkniete','ustawienia','przeliczenie') NOT NULL,
    order_id INT NULL,
    product_id INT NULL,
    route_id INT NULL,
    station_code VARCHAR(32) NULL,
    old_value VARCHAR(64) NULL,
    new_value VARCHAR(64) NULL,
    reason VARCHAR(32) NULL,
    note VARCHAR(255) NULL,
    user_id INT NULL,
    worker_id INT NULL,
    device_id INT NULL,
    created_at DATETIME NOT NULL,
    KEY ix_prod_priority_log_order_id (order_id),
    KEY ix_prod_priority_log_route_id (route_id),
    KEY ix_prod_priority_log_station_code (station_code),
    KEY ix_prod_priority_log_created_at (created_at),
    CONSTRAINT fk_prod_priority_log_order FOREIGN KEY (order_id)
        REFERENCES prod_orders (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 8.4 Stół stanowiska: kafle leżące na stanowisku (postponed_at NULL) i odłożone (postponed_at NOT NULL).
-- unit_key: p:<product_id> dla kafla-pozycji, o:<order_id> dla kafla-zamówienia.
CREATE TABLE IF NOT EXISTS prod_station_desk (
    id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    station_code VARCHAR(32) NOT NULL,
    order_id INT NOT NULL,
    product_id INT NULL,
    unit_key VARCHAR(24) NOT NULL,
    pulled_at DATETIME NOT NULL,
    postponed_at DATETIME NULL,
    postpone_reason VARCHAR(32) NULL,
    postpone_note VARCHAR(255) NULL,
    postponed_by_worker_id INT NULL,
    postponed_device_id INT NULL,
    UNIQUE KEY uq_prod_station_desk_unit (station_code, unit_key),
    KEY ix_prod_station_desk_station_code (station_code),
    KEY ix_prod_station_desk_order_id (order_id),
    KEY ix_prod_station_desk_product_id (product_id),
    CONSTRAINT fk_prod_station_desk_order FOREIGN KEY (order_id)
        REFERENCES prod_orders (id) ON DELETE CASCADE,
    CONSTRAINT fk_prod_station_desk_product FOREIGN KEY (product_id)
        REFERENCES prod_products (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Domyślna drabina (spec 3.1, decyzja Konrada 5.10): pięć gwiazdek, Po terminie, cztery gwiazdki, Blisko terminu,
-- Rozpoczęte, trzy, dwie, jedna, bez gwiazdek. Drugi przebieg niczego nie zmienia: biuro mogło już przesunąć tagi,
-- a klucze unikalne (kind+stars, kind+tag) zatrzymują powtórkę niezależnie od position.
INSERT IGNORE INTO prod_priority_rungs (kind, stars, tag, position, created_at, updated_at)
VALUES ('stars', 5, NULL, 1, NOW(), NOW()),
       ('tag', NULL, 'po_terminie', 2, NOW(), NOW()),
       ('stars', 4, NULL, 3, NOW(), NOW()),
       ('tag', NULL, 'blisko_terminu', 4, NOW(), NOW()),
       ('tag', NULL, 'rozpoczete', 5, NOW(), NOW()),
       ('stars', 3, NULL, 6, NOW(), NOW()),
       ('stars', 2, NULL, 7, NOW(), NOW()),
       ('stars', 1, NULL, 8, NOW(), NOW()),
       ('stars', 0, NULL, 9, NOW(), NOW());

-- 8.6 Ustawienia per stanowisko: tryb (stary albo stol), miejsca na stole, jednostka kafla, limit odłożeń i wiersz
-- blokady pobierania na stół (jeden pobierający na stanowisko — jak blokada tras). INSERT IGNORE: wartości
-- zmienione już w Konfiguracji zostają.
INSERT IGNORE INTO prod_config (config_key, config_value, config_description, config_type, created_at, updated_at)
VALUES ('priorytety_tryb_cutting', 'stary', 'Priorytety: tryb stanowiska Wycinanie (stary albo stol)', 'string', NOW(), NOW()),
       ('priorytety_stol_cutting', '2', 'Priorytety: miejsca na stole stanowiska Wycinanie', 'integer', NOW(), NOW()),
       ('priorytety_jednostka_cutting', 'pozycja', 'Priorytety: jednostka kafla stanowiska Wycinanie (pozycja albo zamowienie)', 'string', NOW(), NOW()),
       ('priorytety_limit_odlozen_cutting', '10', 'Priorytety: limit otwartych odłożeń stanowiska Wycinanie', 'integer', NOW(), NOW()),
       ('priorytety_blokada_cutting', '', 'Priorytety: blokada pobierania na stół stanowiska Wycinanie (jeden naraz)', 'string', NOW(), NOW()),
       ('priorytety_tryb_assembly', 'stary', 'Priorytety: tryb stanowiska Składanie (stary albo stol)', 'string', NOW(), NOW()),
       ('priorytety_stol_assembly', '2', 'Priorytety: miejsca na stole stanowiska Składanie', 'integer', NOW(), NOW()),
       ('priorytety_jednostka_assembly', 'pozycja', 'Priorytety: jednostka kafla stanowiska Składanie (pozycja albo zamowienie)', 'string', NOW(), NOW()),
       ('priorytety_limit_odlozen_assembly', '10', 'Priorytety: limit otwartych odłożeń stanowiska Składanie', 'integer', NOW(), NOW()),
       ('priorytety_blokada_assembly', '', 'Priorytety: blokada pobierania na stół stanowiska Składanie (jeden naraz)', 'string', NOW(), NOW()),
       ('priorytety_tryb_gluing', 'stary', 'Priorytety: tryb stanowiska Sklejanie (stary albo stol)', 'string', NOW(), NOW()),
       ('priorytety_stol_gluing', '2', 'Priorytety: miejsca na stole stanowiska Sklejanie', 'integer', NOW(), NOW()),
       ('priorytety_jednostka_gluing', 'pozycja', 'Priorytety: jednostka kafla stanowiska Sklejanie (pozycja albo zamowienie)', 'string', NOW(), NOW()),
       ('priorytety_limit_odlozen_gluing', '10', 'Priorytety: limit otwartych odłożeń stanowiska Sklejanie', 'integer', NOW(), NOW()),
       ('priorytety_blokada_gluing', '', 'Priorytety: blokada pobierania na stół stanowiska Sklejanie (jeden naraz)', 'string', NOW(), NOW()),
       ('priorytety_tryb_formatting', 'stary', 'Priorytety: tryb stanowiska Formatowanie (stary albo stol)', 'string', NOW(), NOW()),
       ('priorytety_stol_formatting', '2', 'Priorytety: miejsca na stole stanowiska Formatowanie', 'integer', NOW(), NOW()),
       ('priorytety_jednostka_formatting', 'zamowienie', 'Priorytety: jednostka kafla stanowiska Formatowanie (pozycja albo zamowienie)', 'string', NOW(), NOW()),
       ('priorytety_limit_odlozen_formatting', '10', 'Priorytety: limit otwartych odłożeń stanowiska Formatowanie', 'integer', NOW(), NOW()),
       ('priorytety_blokada_formatting', '', 'Priorytety: blokada pobierania na stół stanowiska Formatowanie (jeden naraz)', 'string', NOW(), NOW()),
       ('priorytety_tryb_edges', 'stary', 'Priorytety: tryb stanowiska Krawędzie (stary albo stol)', 'string', NOW(), NOW()),
       ('priorytety_stol_edges', '2', 'Priorytety: miejsca na stole stanowiska Krawędzie', 'integer', NOW(), NOW()),
       ('priorytety_jednostka_edges', 'pozycja', 'Priorytety: jednostka kafla stanowiska Krawędzie (pozycja albo zamowienie)', 'string', NOW(), NOW()),
       ('priorytety_limit_odlozen_edges', '10', 'Priorytety: limit otwartych odłożeń stanowiska Krawędzie', 'integer', NOW(), NOW()),
       ('priorytety_blokada_edges', '', 'Priorytety: blokada pobierania na stół stanowiska Krawędzie (jeden naraz)', 'string', NOW(), NOW()),
       ('priorytety_tryb_painting', 'stary', 'Priorytety: tryb stanowiska Lakiernia (stary albo stol)', 'string', NOW(), NOW()),
       ('priorytety_stol_painting', '2', 'Priorytety: miejsca na stole stanowiska Lakiernia', 'integer', NOW(), NOW()),
       ('priorytety_jednostka_painting', 'pozycja', 'Priorytety: jednostka kafla stanowiska Lakiernia (pozycja albo zamowienie)', 'string', NOW(), NOW()),
       ('priorytety_limit_odlozen_painting', '10', 'Priorytety: limit otwartych odłożeń stanowiska Lakiernia', 'integer', NOW(), NOW()),
       ('priorytety_blokada_painting', '', 'Priorytety: blokada pobierania na stół stanowiska Lakiernia (jeden naraz)', 'string', NOW(), NOW()),
       ('priorytety_tryb_packaging', 'stary', 'Priorytety: tryb stanowiska Pakowanie (stary albo stol)', 'string', NOW(), NOW()),
       ('priorytety_stol_packaging', '2', 'Priorytety: miejsca na stole stanowiska Pakowanie', 'integer', NOW(), NOW()),
       ('priorytety_jednostka_packaging', 'zamowienie', 'Priorytety: jednostka kafla stanowiska Pakowanie (pozycja albo zamowienie)', 'string', NOW(), NOW()),
       ('priorytety_limit_odlozen_packaging', '10', 'Priorytety: limit otwartych odłożeń stanowiska Pakowanie', 'integer', NOW(), NOW()),
       ('priorytety_blokada_packaging', '', 'Priorytety: blokada pobierania na stół stanowiska Pakowanie (jeden naraz)', 'string', NOW(), NOW());

-- Ustawienia wspólne: próg tagu „Blisko terminu” w dniach roboczych (decyzja Konrada 5.10), bramka wersji starej
-- appki (0 = brak bramki) i sposób liczenia terminu nowych zamówień (robocze albo kalendarzowe, spec 4.3).
INSERT IGNORE INTO prod_config (config_key, config_value, config_description, config_type, created_at, updated_at)
VALUES ('priorytety_blisko_terminu_dni', '3', 'Priorytety: próg tagu Blisko terminu (dni robocze)', 'integer', NOW(), NOW()),
       ('priorytety_min_app_version_code', '0', 'Priorytety: minimalny kod wersji appki dla trybu stol (0 = brak bramki)', 'integer', NOW(), NOW()),
       ('DEADLINE_DAY_TYPE', 'robocze', 'Terminy: dni robocze albo kalendarzowe przy nadawaniu terminu zamówienia', 'string', NOW(), NOW());
