-- Migracja: Dane dla tabeli finishing_options
-- Data: 2026-01-21
-- Opis: Wstawia dane wykończeń do hierarchicznej tabeli finishing_options
--       (tylko jeśli tabela jest pusta)

-- Sprawdź czy tabela jest pusta i wstaw dane
-- MySQL nie obsługuje IF w czystym SQL, więc używamy INSERT IGNORE + unikalność

-- Najpierw upewnij się że tabela istnieje (na wypadek gdyby 003 się nie wykonała)
CREATE TABLE IF NOT EXISTS finishing_options (
    id INT AUTO_INCREMENT PRIMARY KEY,
    parent_id INT DEFAULT NULL,
    name VARCHAR(100) NOT NULL,
    code VARCHAR(20) DEFAULT NULL,
    price_netto DECIMAL(10,2) DEFAULT NULL,
    image_path VARCHAR(255) DEFAULT NULL,
    level INT DEFAULT 0,
    sort_order INT DEFAULT 0,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (parent_id) REFERENCES finishing_options(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Wstaw dane tylko jeśli tabela jest pusta (używamy procedury)
-- Jeśli tabela ma już dane, INSERT IGNORE pominie duplikaty

-- Level 0: Główne kategorie
INSERT INTO finishing_options (id, parent_id, name, code, price_netto, level, sort_order)
VALUES (1, NULL, 'Surowe', 'SUR', 0.00, 0, 0)
ON DUPLICATE KEY UPDATE name=name;

INSERT INTO finishing_options (id, parent_id, name, code, price_netto, level, sort_order)
VALUES (2, NULL, 'Lakierowane', 'LAK', NULL, 0, 1)
ON DUPLICATE KEY UPDATE name=name;

INSERT INTO finishing_options (id, parent_id, name, code, price_netto, level, sort_order)
VALUES (20, NULL, 'Olejowanie', 'OLE', 250.00, 0, 2)
ON DUPLICATE KEY UPDATE name=name;

-- Level 1: Podkategorie Lakierowane
INSERT INTO finishing_options (id, parent_id, name, code, price_netto, level, sort_order)
VALUES (3, 2, 'Bezbarwne', NULL, 200.00, 1, 0)
ON DUPLICATE KEY UPDATE name=name;

INSERT INTO finishing_options (id, parent_id, name, code, price_netto, level, sort_order)
VALUES (4, 2, 'Barwne', NULL, NULL, 1, 1)
ON DUPLICATE KEY UPDATE name=name;

-- Level 2: Kolory pod Barwne
INSERT INTO finishing_options (id, parent_id, name, code, price_netto, image_path, level, sort_order)
VALUES (5, 4, 'POPIEL 20-07', NULL, 250.00, 'images/finishing_colors/popiel-20-07.jpg', 2, 1)
ON DUPLICATE KEY UPDATE name=name;

INSERT INTO finishing_options (id, parent_id, name, code, price_netto, image_path, level, sort_order)
VALUES (6, 4, 'BEŻ BN-125/09', NULL, 250.00, 'images/finishing_colors/bez-bn-125-09.jpg', 2, 2)
ON DUPLICATE KEY UPDATE name=name;

INSERT INTO finishing_options (id, parent_id, name, code, price_netto, image_path, level, sort_order)
VALUES (7, 4, 'BRUNAT 22-10', NULL, 250.00, 'images/finishing_colors/brunat-22-10.jpg', 2, 3)
ON DUPLICATE KEY UPDATE name=name;

INSERT INTO finishing_options (id, parent_id, name, code, price_netto, image_path, level, sort_order)
VALUES (8, 4, 'BRUNAT 22-05', NULL, 250.00, 'images/finishing_colors/brunat-22-05.jpg', 2, 4)
ON DUPLICATE KEY UPDATE name=name;

INSERT INTO finishing_options (id, parent_id, name, code, price_netto, image_path, level, sort_order)
VALUES (9, 4, 'BRUNAT 22-15', NULL, 250.00, 'images/finishing_colors/brunat-22-15.jpg', 2, 5)
ON DUPLICATE KEY UPDATE name=name;

INSERT INTO finishing_options (id, parent_id, name, code, price_netto, image_path, level, sort_order)
VALUES (10, 4, 'BRUNAT 22-23', NULL, 250.00, 'images/finishing_colors/brunat-22-23.jpg', 2, 6)
ON DUPLICATE KEY UPDATE name=name;

INSERT INTO finishing_options (id, parent_id, name, code, price_netto, image_path, level, sort_order)
VALUES (11, 4, 'ORZECH 22-74', NULL, 250.00, 'images/finishing_colors/orzech-22-74.jpg', 2, 7)
ON DUPLICATE KEY UPDATE name=name;

INSERT INTO finishing_options (id, parent_id, name, code, price_netto, image_path, level, sort_order)
VALUES (12, 4, 'BRĄZ 22-50', NULL, 250.00, 'images/finishing_colors/braz-22-50.jpg', 2, 8)
ON DUPLICATE KEY UPDATE name=name;

INSERT INTO finishing_options (id, parent_id, name, code, price_netto, image_path, level, sort_order)
VALUES (13, 4, 'ORZECH 22-66', NULL, 250.00, 'images/finishing_colors/orzech-22-66.jpg', 2, 9)
ON DUPLICATE KEY UPDATE name=name;
