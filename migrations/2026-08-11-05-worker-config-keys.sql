/* Migracja: Klucze konfiguracyjne profili pracowników.
   Data: 2026-08-11
   Projekt: docs/worker-profiles-backend.md, §4.5

   Wszystkie zmienialne z /production/?tab=config, bez deployu.

   WORKER_SELECTION_REQUIRED to KILL-SWITCH i wchodzi jako 'false' celowo:
   bramka blokuje całe stanowisko, więc awaria katalogu pracowników przy
   włączonej bramce zatrzymuje halę. Włączamy dopiero po roll-oucie apki,
   która potrafi wysyłać X-Worker-Ids (etap 5 w §9).

   INSERT IGNORE — powtórka migracji nie nadpisze wartości ustawionych
   później w panelu. */

INSERT IGNORE INTO prod_config (config_key, config_value, config_description, config_type)
VALUES
    ('WORKER_SELECTION_REQUIRED', 'false',
     'Czy akcje produkcyjne z tabletu wymagają nagłówka X-Worker-Ids. KILL-SWITCH: false = hala pracuje bez wyboru profilu.',
     'boolean'),

    ('WORKER_SESSION_IDLE_TIMEOUT_MINUTES', '120',
     'Po ilu minutach BEZ AKCJI PRODUKCYJNEJ (nie: bez dotknięcia ekranu) sesja pracownika jest domykana jako idle_timeout.',
     'integer'),

    ('WORKER_SESSION_NIGHT_CUTOFF', '23:00',
     'Godzina twardego domknięcia zapomnianych sesji (HH:MM, czas lokalny).',
     'string'),

    ('WORKER_QUICK_PICK_COUNT', '8',
     'Ile kafelków pracowników pokazać w sekcji szybkiego wyboru na tablecie.',
     'integer');
