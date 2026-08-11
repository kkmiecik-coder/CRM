/* Migracja: Katalog pracowników produkcji (profile na tabletach).
   Data: 2026-08-11
   Projekt: docs/worker-profiles-backend.md, §4.1

   UWAGA na numer "-01-" w nazwie: runner wykonuje migracje posortowane
   ALFABETYCZNIE po nazwie pliku, a ta piątka ma zależności przez klucze obce
   (workers → sessions → event_workers → ALTER-y). Bez numerów kolejność
   wychodziła "station-event-workers" jako pierwsza i MySQL odbijał ją błędem
   1824 "Failed to open the referenced table", co przerywa deploy.

   Cel: Tablet stanowiskowy pyta "kto teraz pracuje" i wysyła wybrane profile
        w nagłówku X-Worker-Ids. Ta tabela to katalog do wyboru.

   Bez seeda — pracowników dodaje się przez /production/?tab=workers.

   ZASADA TWARDA: pracowników NIGDY nie kasujemy. Odejście z firmy to
   is_active = 0 + deactivated_at. Statystyki historyczne muszą przetrwać,
   a FK z tabeli atrybucji i tak by kasowania nie pozwolił. */

CREATE TABLE IF NOT EXISTS prod_workers (
    id               INT AUTO_INCREMENT PRIMARY KEY,
    first_name       VARCHAR(64)  NOT NULL,
    last_name        VARCHAR(64)  NOT NULL,
    worker_code      VARCHAR(16)  DEFAULT NULL COMMENT 'Rezerwa pod QR/badge, dziś nieużywane',
    pin_hash         VARCHAR(255) DEFAULT NULL COMMENT 'Rezerwa pod przyszłe PIN-y, dziś zawsze NULL',
    avatar_path      VARCHAR(255) DEFAULT NULL COMMENT 'Rezerwa — dziś kafelki pokazują inicjały na color_hex',
    color_hex        CHAR(7)      DEFAULT NULL COMMENT 'Tło kafelka z inicjałami, np. #3E7C59',
    allowed_stations VARCHAR(255) DEFAULT NULL COMMENT 'CSV kodów stanowisk; NULL/pusty = wszystkie',
    is_active        TINYINT(1)   NOT NULL DEFAULT 1,
    user_id          INT          DEFAULT NULL COMMENT 'Opcjonalne powiązanie z kontem CRM',
    sort_order       SMALLINT     NOT NULL DEFAULT 0,
    created_at       DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at       DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    deactivated_at   DATETIME     DEFAULT NULL,
    UNIQUE KEY uq_worker_code (worker_code),
    INDEX idx_is_active (is_active),
    INDEX idx_user_id (user_id),
    CONSTRAINT fk_workers_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
