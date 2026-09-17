-- Migracja: dopłata za kształt nietypowy
-- Data: 2026-09-15
-- Opis: Kształty inne niż prostokąt i koło/owal (trójkąty, trapezy, równoległobok,
--       wielokąt) wymagają docinania po szablonie. Doliczamy za nie stałą kwotę
--       netto za sztukę, konfigurowaną w ustawieniach kalkulatora pod kluczem
--       `custom_shape_surcharge_netto`.
--
--       Kwota jest już wliczona w cenę wariantu materiału (pricing_service), a te
--       dwie kolumny trzymają ją osobno — tak jak round_surcharge_* dla koła —
--       żeby breakdown wyceny mówił, za co doliczono. Obie dopłaty wykluczają się
--       wzajemnie: produkt ma dokładnie jeden kształt.
--
-- Idempotentność: każde ALTER osłonięte warunkiem na brak kolumny, INSERT IGNORE
-- dla ustawienia. Powtórny przebieg nie nadpisze kwoty ustawionej przez admina.
-- Zmiana separatora poleceń celowo pominięta — runner jej nie obsługuje.

SET @brak_kolumny_netto := (
    SELECT COUNT(*) = 0 FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'quote_items_details'
      AND COLUMN_NAME = 'custom_shape_surcharge_netto'
);

SET @sql_netto := IF(@brak_kolumny_netto,
    'ALTER TABLE quote_items_details ADD COLUMN custom_shape_surcharge_netto DECIMAL(10,2) DEFAULT 0 COMMENT ''Dopłata netto za kształt nietypowy (łącznie za ilość)'' AFTER round_surcharge_brutto',
    'SELECT 1');

PREPARE polecenie_netto FROM @sql_netto;

EXECUTE polecenie_netto;

DEALLOCATE PREPARE polecenie_netto;

SET @brak_kolumny_brutto := (
    SELECT COUNT(*) = 0 FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'quote_items_details'
      AND COLUMN_NAME = 'custom_shape_surcharge_brutto'
);

SET @sql_brutto := IF(@brak_kolumny_brutto,
    'ALTER TABLE quote_items_details ADD COLUMN custom_shape_surcharge_brutto DECIMAL(10,2) DEFAULT 0 COMMENT ''Dopłata brutto za kształt nietypowy (łącznie za ilość)'' AFTER custom_shape_surcharge_netto',
    'SELECT 1');

PREPARE polecenie_brutto FROM @sql_brutto;

EXECUTE polecenie_brutto;

DEALLOCATE PREPARE polecenie_brutto;

-- Wartość startowa 0 — dopłata jest wyłączona, dopóki admin nie wpisze kwoty
-- w Ustawieniach → Kalkulator → Cennik. Dzięki temu migracja niczego nie podraża.
INSERT IGNORE INTO calculator_settings (setting_key, setting_value, description)
VALUES ('custom_shape_surcharge_netto', '0.00',
        'Dopłata netto za sztukę dla kształtów innych niż prostokąt i koło/owal');
