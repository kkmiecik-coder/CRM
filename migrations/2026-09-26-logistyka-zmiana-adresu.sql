-- Logistyka równoległa, etap 2: poprawianie adresu dostawy w zakładce Logistyka.
-- Idempotentna (runner wykonuje katalog przy każdym deployu). ALTER ADD COLUMN nie ma
-- IF NOT EXISTS, więc warunek z information_schema przez PREPARE/EXECUTE (bez DELIMITER),
-- jak w 2026-09-25-logistyka-sposob-dostawy.sql.

-- Znacznik „adres do wysłania do Base.” (dopycha go bl_sync, jak metodę i status).
SET @brak = (SELECT COUNT(*) = 0 FROM information_schema.COLUMNS
             WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'prod_orders'
               AND COLUMN_NAME = 'bl_address_pending');
SET @sql = IF(@brak, 'ALTER TABLE prod_orders ADD COLUMN bl_address_pending TINYINT(1) NOT NULL DEFAULT 0',
              'SELECT "bl_address_pending juz jest" AS info');
PREPARE krok FROM @sql; EXECUTE krok; DEALLOCATE PREPARE krok;

-- Nowa akcja w logu logistyki: 'adres'. MODIFY do tej samej definicji jest bezpieczny
-- przy każdym przebiegu (lista wartości tylko rośnie — stare wiersze zostają ważne).
ALTER TABLE prod_logistics_log MODIFY action
    ENUM('sposob_dostawy','wydane','przepakowanie',
         'trasa_dodane','trasa_usuniete','trasa_status','adres') NOT NULL;
