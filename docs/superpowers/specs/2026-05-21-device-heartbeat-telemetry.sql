-- 2026-05-21 Device Heartbeat & Telemetry
-- Dodaje kolumny telemetrii do prod_devices.
-- Reusujemy istniejące last_ip (VARCHAR(45)) i app_version (VARCHAR(32))
-- dla IP i app_version_name — nie dodajemy duplikatów.
-- User puszcza ręcznie przez phpMyAdmin PRZED deployem kodu
-- (lokalnie: woodpower_crm_local, prod: produkcyjna baza).

ALTER TABLE prod_devices
  ADD COLUMN last_heartbeat_at DATETIME NULL,
  ADD COLUMN last_battery_pct SMALLINT NULL,
  ADD COLUMN last_battery_charging BOOLEAN NULL,
  ADD COLUMN last_temperature_c FLOAT NULL,
  ADD COLUMN last_app_version_code INT NULL,
  ADD INDEX idx_prod_devices_last_heartbeat (last_heartbeat_at);
