-- Trzy tabele Analizy sprzedażowej: klient -> zamówienie -> pozycja.
--
-- Zastępują płaską `baselinker_reports_orders`, w której pola poziomu
-- zamówienia są powielone na każdej pozycji. Zmierzone na produkcji
-- 21.09.2026: SUM(balance_due) po wierszach = 5 618 320 zł, to samo saldo
-- liczone raz na zamówienie = 741 279 zł.
--
-- Stara tabela ZOSTAJE nietknięta — kasujemy ją dopiero po weryfikacji sum
-- po backfillu (scripts/backfill_sales_tables.py).
--
-- CREATE TABLE IF NOT EXISTS, bo runner przechodzi katalog przy każdym deployu.

CREATE TABLE IF NOT EXISTS sales_clients (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    lead_id         INT NULL,
    email_norm      VARCHAR(150) NULL,
    nip_norm        VARCHAR(20)  NULL,
    phone_norm      VARCHAR(20)  NULL,
    display_name    VARCHAR(200) NULL,
    client_kind     ENUM('detal','b2b') NULL,
    needs_merge     TINYINT(1) NOT NULL DEFAULT 0
                    COMMENT 'Brak wszystkich trzech kluczy - do recznego scalenia',
    first_order_at  DATE NULL,
    last_order_at   DATE NULL,
    orders_count    INT NOT NULL DEFAULT 0,
    lifetime_net    DECIMAL(12,2) NOT NULL DEFAULT 0,
    created_at      DATETIME NOT NULL,
    updated_at      DATETIME NOT NULL,
    KEY idx_sc_lead  (lead_id),
    KEY idx_sc_email (email_norm),
    KEY idx_sc_nip   (nip_norm),
    KEY idx_sc_phone (phone_norm)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS sales_orders (
    id                    INT AUTO_INCREMENT PRIMARY KEY,
    baselinker_order_id   INT NULL,
    client_id             INT NULL,
    date_created          DATE NOT NULL,
    internal_order_number VARCHAR(50) NULL,
    customer_name         VARCHAR(200) NULL,
    email                 VARCHAR(150) NULL,
    phone                 VARCHAR(100) NULL,
    delivery_address      VARCHAR(250) NULL,
    delivery_postcode     VARCHAR(20)  NULL,
    delivery_city         VARCHAR(100) NULL,
    delivery_state        VARCHAR(50)  NULL,
    caretaker             VARCHAR(100) NULL,
    order_source          VARCHAR(50)  NULL,
    order_source_id       INT NULL,
    client_origin         VARCHAR(50)  NULL,
    delivery_method       VARCHAR(255) NULL,
    own_transport         TINYINT(1) NOT NULL DEFAULT 0,
    delivery_cost         DECIMAL(10,2) NULL,
    price_type            ENUM('netto','brutto','') NULL DEFAULT '',
    payment_method        VARCHAR(255) NULL,
    paid_amount           DECIMAL(10,2) NOT NULL DEFAULT 0,
    payment_date          DATE NULL,
    balance_due           DECIMAL(10,2) NOT NULL DEFAULT 0,
    advance_cash          DECIMAL(10,2) NOT NULL DEFAULT 0,
    advance_wp            DECIMAL(10,2) NOT NULL DEFAULT 0,
    advance_loza          DECIMAL(10,2) NOT NULL DEFAULT 0,
    paid_cash             DECIMAL(10,2) NOT NULL DEFAULT 0,
    paid_wp               DECIMAL(10,2) NOT NULL DEFAULT 0,
    paid_loza             DECIMAL(10,2) NOT NULL DEFAULT 0,
    current_status        VARCHAR(100) NULL,
    baselinker_status_id  INT NULL,
    picked_up             TINYINT(1) NOT NULL DEFAULT 0,
    notes                 VARCHAR(200) NULL,
    created_at            DATETIME NOT NULL,
    updated_at            DATETIME NOT NULL,
    UNIQUE KEY uq_so_bl_order (baselinker_order_id),
    KEY idx_so_date    (date_created),
    KEY idx_so_client  (client_id),
    KEY idx_so_state   (delivery_state),
    KEY idx_so_care    (caretaker),
    KEY idx_so_source  (order_source),
    KEY idx_so_origin  (client_origin),
    KEY idx_so_status  (current_status),
    CONSTRAINT fk_so_client FOREIGN KEY (client_id)
        REFERENCES sales_clients (id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS sales_order_items (
    id                  INT AUTO_INCREMENT PRIMARY KEY,
    order_id            INT NOT NULL,
    bl_order_product_id BIGINT NULL,
    wood_species        VARCHAR(50) NULL,
    technology          VARCHAR(50) NULL,
    wood_class          VARCHAR(10) NULL,
    finish_state        VARCHAR(50) NULL,
    group_type          VARCHAR(30) NULL,
    product_type        VARCHAR(30) NULL,
    length_cm           DECIMAL(10,2) NULL,
    width_cm            DECIMAL(10,2) NULL,
    thickness_cm        DECIMAL(10,2) NULL,
    quantity            INT NULL,
    price_gross         DECIMAL(10,2) NULL,
    price_net           DECIMAL(10,2) NULL,
    value_gross         DECIMAL(10,2) NULL,
    value_net            DECIMAL(10,2) NULL,
    volume_per_piece    DECIMAL(10,6) NULL,
    total_volume        DECIMAL(10,6) NULL,
    total_surface_m2    DECIMAL(10,4) NULL,
    price_per_m3        DECIMAL(10,2) NULL,
    raw_product_name    TEXT NULL,
    KEY idx_soi_order   (order_id),
    KEY idx_soi_species (wood_species),
    KEY idx_soi_group   (group_type),
    KEY idx_soi_ptype   (product_type),
    CONSTRAINT fk_soi_order FOREIGN KEY (order_id)
        REFERENCES sales_orders (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
