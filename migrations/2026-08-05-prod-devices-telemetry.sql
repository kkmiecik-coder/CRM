/* Migracja: Telemetria tabletów stanowiskowych (heartbeat, bateria, temperatura).
   Data: 2026-08-05 — uzupełnienie wstecz.

   Cel: Kolumny istnieją na produkcji od dawna (model ProductionDevice ich używa),
        ale nigdy nie trafiły do repozytorium — dodano je ręcznie. Skutek: świeżo
        postawiona baza wywalała dashboard produkcji błędem
        1054 "Unknown column 'prod_devices.last_heartbeat_at' in 'field list'".

   UWAGA: na produkcji ten plik jest już faktycznie wykonany. Uruchamiać wyłącznie
   na nowych środowiskach (lokalny Docker, staging) — ponowne wykonanie na bazie,
   która te kolumny ma, zakończy się błędem 1060 "Duplicate column name". */

ALTER TABLE prod_devices ADD COLUMN last_heartbeat_at DATETIME DEFAULT NULL COMMENT 'Ostatni sygnał życia z tabletu (osobny od last_seen_at — heartbeat leci w tle)';
ALTER TABLE prod_devices ADD COLUMN last_battery_pct SMALLINT DEFAULT NULL COMMENT 'Poziom baterii w procentach (0-100)';
ALTER TABLE prod_devices ADD COLUMN last_battery_charging BOOLEAN DEFAULT NULL COMMENT 'Czy tablet był podłączony do ładowarki';
ALTER TABLE prod_devices ADD COLUMN last_temperature_c FLOAT DEFAULT NULL COMMENT 'Temperatura baterii w stopniach Celsjusza';
ALTER TABLE prod_devices ADD COLUMN last_app_version_code INT DEFAULT NULL COMMENT 'versionCode zainstalowanej aplikacji Android';

/* Indeks pod listę urządzeń sortowaną po ostatnim sygnale życia */
ALTER TABLE prod_devices ADD INDEX idx_prod_devices_last_heartbeat (last_heartbeat_at);
