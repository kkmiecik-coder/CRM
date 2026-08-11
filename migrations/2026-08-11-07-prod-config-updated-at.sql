/* Migracja: prod_config.updated_at aktualizuje się samo.
   Data: 2026-08-11

   Kolumna była DATETIME NULL bez ON UPDATE, a wypełniał ją wyłącznie
   config_service.set_config(). Skutek: zmiana wartości wykonana INACZEJ niż
   z panelu — czyli zapytaniem w phpMyAdmin — nie ruszała znacznika czasu.

   Dlaczego to ma znaczenie akurat teraz: tablety pobierają konfigurację razem
   z katalogiem pracowników (GET /api/mobile/workers) i cache'ują ją po ETagu.
   Segment konfiguracyjny ETagu opiera się na wykryciu zmiany; gdy znacznik
   stoi w miejscu, tablet dostaje 304 i pracuje na starej wartości.

   Najgorszy przypadek to WORKER_SELECTION_REQUIRED — kill-switch, po który
   sięga się wtedy, gdy hala stoi. Wtedy właśnie ktoś może pójść na skróty
   do bazy zamiast do panelu, a to jedyna droga, na której przełącznik
   nie dojeżdżał.

   ON UPDATE CURRENT_TIMESTAMP dotyczy wszystkich kluczy w tabeli — i dobrze:
   znacznik "kiedy ostatnio zmieniono" ma być prawdziwy niezależnie od tego,
   kto i czym pisał. Istniejące wiersze mają dziś NULL i tak zostaje, dopóki
   ktoś ich nie ruszy; nie backfillujemy, bo zmyślona data byłaby gorsza
   od jej braku. */

ALTER TABLE prod_config
    MODIFY COLUMN updated_at DATETIME NULL DEFAULT NULL ON UPDATE CURRENT_TIMESTAMP;
