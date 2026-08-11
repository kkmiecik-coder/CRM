/* Migracja: Atrybucja eventów stanowiskowych do pracowników.
   Data: 2026-08-11
   Projekt: docs/worker-profiles-backend.md, §4.3

   Warstwa DOKŁADANA do prod_station_events, nie przebudowa: event zostaje
   niemutowalny i niezmieniony, więc wszyscy jego dotychczasowi konsumenci
   (station_events_service, dashboard_api, main_routers, mobile_api_service)
   działają dalej bez jednej linijki zmiany.

   share = 1/N gdzie N to liczba pracowników przy evencie. Denormalizacja jest
   tu bezpieczna, bo wartość jest NIEMUTOWALNA — zapisywana raz przy tworzeniu
   eventu i nigdy nie aktualizowana, więc nie ma czego rozjeżdżać. Alternatywa
   (funkcja okienkowa COUNT(*) OVER) wymagałaby MySQL 8+.

   Świadome ograniczenie precyzji: przy trzech osobach 3 × 0.333333 = 0.999999.
   Błąd 1e-6 na event, przy 10 000 eventów to 0,01 sztuki. Raporty zaokrąglają
   do jednego miejsca po przecinku i tyle.

   Eventy sprzed wdrożenia nie mają tu wierszy — raporty pokazują je jako
   osobny wiersz "Nieprzypisane", nie ukrywają. */

CREATE TABLE IF NOT EXISTS prod_station_event_workers (
    event_id   INT           NOT NULL,
    worker_id  INT           NOT NULL,
    session_id INT           DEFAULT NULL,
    share      DECIMAL(9,6)  NOT NULL COMMENT '1/N gdzie N = liczba pracowników przy evencie',
    PRIMARY KEY (event_id, worker_id),
    INDEX idx_worker (worker_id),
    INDEX idx_session (session_id),
    CONSTRAINT fk_sew_event   FOREIGN KEY (event_id)   REFERENCES prod_station_events(id) ON DELETE CASCADE,
    CONSTRAINT fk_sew_worker  FOREIGN KEY (worker_id)  REFERENCES prod_workers(id),
    CONSTRAINT fk_sew_session FOREIGN KEY (session_id) REFERENCES prod_worker_sessions(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
