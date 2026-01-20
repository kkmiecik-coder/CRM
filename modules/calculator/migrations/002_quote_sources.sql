-- ============================================
-- Migracja: Tabela źródeł wycen (Quote Sources)
-- Data: 2026-01-20
-- Opis: Prosta tabela źródeł wycen
-- ============================================

-- 1. Usuń starą tabelę jeśli istnieje
DROP TABLE IF EXISTS quote_sources;

-- 2. Utwórz nową uproszczoną tabelę
CREATE TABLE quote_sources (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    sort_order INT DEFAULT 0,
    skip_contact_validation BOOLEAN DEFAULT FALSE,
    is_active BOOLEAN DEFAULT TRUE,
    allowed_roles JSON DEFAULT NULL COMMENT 'Role które mogą używać tego źródła (NULL = wszystkie)',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);

-- 3. Dane początkowe
INSERT INTO quote_sources (name, sort_order) VALUES
('E-mail', 1),
('Telefon', 2),
('Osobiście', 3);

-- ============================================
-- Weryfikacja
-- ============================================
SELECT 'Migracja quote_sources zakończona' AS status;
SELECT * FROM quote_sources ORDER BY sort_order;
