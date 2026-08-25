/* Migracja: Odbiorcy dziennego raportu produkcji.
   Data: 2026-08-25
   Projekt: docs/superpowers/specs/2026-08-25-raport-dzienny-produkcji-design.md

   Klucz zakładamy TUTAJ, a nie z panelu, bo batch update w config_service
   (:660-668) dodaje nowy wiersz bez inkrementacji licznika zmian, a commit
   stoi pod warunkiem na tym liczniku — panel zwraca sukces, po czym
   teardown_appcontext robi rollback i zapis znika. Istniejący klucz panel
   aktualizuje normalnie.

   config_type podany JAWNIE: _guess_config_type jest w tym module
   zdefiniowane dwukrotnie i wygrywa druga definicja, o innym zachowaniu.

   Pusta wartość jest celowa — dopóki nikt nie wpisze adresów, raport się nie
   wysyła. To jest wyłącznik funkcji, dlatego nie ma osobnego klucza ENABLED.

   INSERT IGNORE — powtórka migracji nie nadpisze adresów wpisanych w panelu. */

INSERT IGNORE INTO prod_config (config_key, config_value, config_description, config_type)
VALUES
    ('DAILY_REPORT_RECIPIENTS', '',
     'Adresy e-mail odbiorców dziennego raportu produkcji, rozdzielone przecinkami. Puste = raport nie jest wysyłany.',
     'string');
