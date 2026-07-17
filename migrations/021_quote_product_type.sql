ALTER TABLE quote_items_details ADD COLUMN product_type VARCHAR(20) NULL DEFAULT NULL;
-- product_type: typ produktu wg sklepu PrestaShop (blat|schody|parapet). Koncept sklepu,
-- CRM go NIE interpretuje. Utrwalany przy POST/PUT /api/bot/quotes, zwracany verbatim w
-- GET /api/bot/quotes/by-token/<token>. NULL dla wycen spoza sklepu (kalkulator CRM, inne boty).
--
-- UWAGA: ALTER MUSI byc PIERWSZY (przed komentarzem). MigrationService dzieli plik po sredniku
-- i pomija fragmenty zaczynajace sie od dwoch myslnikow, wiec komentarz PRZED ALTER-em skleilby
-- sie z nim w jeden pomijany blok (patrz 012_lamella_direction.sql, ktory jest de facto no-opem).
-- MigrationService pomija tez blad duplicate column, wiec ALTER jest idempotentny i bezpieczny
-- takze gdy kolumne dodano wczesniej recznie w phpMyAdmin.
