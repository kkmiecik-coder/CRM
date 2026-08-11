/* Migracja: Atrybucja pracy w trakowni.
   Data: 2026-08-11
   Projekt: docs/worker-profiles-backend.md (rozszerzenie na moduł trakowni)

   Trakownia dotąd wiedziała, Z KTÓREGO TABLETU wykonano pomiar, ale nie kto go
   zrobił — a na trakowni stoją dwa tablety i dwie osoby potrafią mierzyć to samo
   zlecenie równocześnie.

   DLACZEGO NA KŁODZIE, a nie na zleceniu: objętość w m³ powstaje przy pomiarze
   POJEDYNCZEJ kłody (metodyka Hubera, services/volume.py), więc dopiero na tym
   poziomie da się powiedzieć "ten człowiek zmierzył tyle metrów". Zlecenie jest
   tylko pojemnikiem na kłody — atrybucja na nim przy dwóch mierzących byłaby
   zgadywaniem.

   DLACZEGO TAKŻE W AUDYCIE: prod_sawmill_audit rejestruje już każdą akcję
   (dodanie, korektę, usunięcie pomiaru, zamknięcie zlecenia) razem z device_id
   i user_id. Dopisanie worker_id załatwia tam "kto zamknął zlecenie" — czyli
   decyzję o tym, że zmierzona objętość idzie do rozliczenia z dostawcą — bez
   dokładania osobnej tabeli ani kolumny na samym zleceniu.

   Numeracja "-06-" utrzymuje kolejność wykonania: runner sortuje migracje
   alfabetycznie, a ta zależy od prod_workers z migracji "-01-". */

ALTER TABLE prod_sawmill_logs
    ADD COLUMN worker_id INT DEFAULT NULL COMMENT 'prod_workers.id — kto zmierzył tę kłodę';

ALTER TABLE prod_sawmill_logs
    ADD INDEX idx_sawmill_logs_worker (worker_id);

SET @fk_istnieje := (
    SELECT COUNT(*) FROM information_schema.TABLE_CONSTRAINTS
    WHERE CONSTRAINT_SCHEMA = DATABASE()
      AND TABLE_NAME = 'prod_sawmill_logs'
      AND CONSTRAINT_NAME = 'fk_sawmill_logs_worker'
);
SET @sql := IF(@fk_istnieje = 0,
    'ALTER TABLE prod_sawmill_logs ADD CONSTRAINT fk_sawmill_logs_worker FOREIGN KEY (worker_id) REFERENCES prod_workers(id) ON DELETE SET NULL',
    'DO 0');
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

/* Audyt: kto wykonał akcję. Bez klucza obcego — tak samo jak order_id w tej
   tabeli, która celowo nie ma FK, żeby wpisy przeżyły usunięcie tego, czego
   dotyczą. Ślad audytowy ma być trwalszy niż jego przedmiot. */
ALTER TABLE prod_sawmill_audit
    ADD COLUMN worker_id INT DEFAULT NULL COMMENT 'prod_workers.id — kto wykonał akcję';

ALTER TABLE prod_sawmill_audit
    ADD INDEX idx_sawmill_audit_worker (worker_id);
