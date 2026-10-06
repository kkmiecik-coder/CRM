-- Logistyka etap 4, krok 4.1 (spec 2026-09-30-logistyka-etap-4-weryfikacja-dostawa-design.md, sekcja 6.1):
-- przesunięcie etykiety paczki 100x150 w punktach drukarki (8 punktów = 1 mm), ustawiane w panelu
-- Konfiguracja → Drukarka etykiet. Zakres −120…120 pilnuje config_service, generator etykiety
-- (package_label.wczytaj_przesuniecie) przycina do tego samego zakresu.
--
-- Klucze zakładamy TUTAJ, a nie z panelu: batch update w config_service dodaje nowy wiersz bez
-- zwiększenia licznika zmian, a commit stoi pod warunkiem na tym liczniku — panel zwraca sukces,
-- po czym zapis znika. Istniejący klucz panel aktualizuje normalnie. Bez wiersza typ byłby też
-- zgadywany z wartości (tekst "500" wychodzi jako json), więc config_type podajemy JAWNIE.
--
-- INSERT IGNORE — powtórka migracji nie nadpisze przesunięcia ustawionego w panelu.

INSERT IGNORE INTO prod_config (config_key, config_value, config_description, config_type, created_at, updated_at)
VALUES
    ('PACKAGE_LABEL_OFFSET_X_DOTS', '0',
     'Przesunięcie poziome etykiety paczki 100x150 w punktach drukarki (8 punktów = 1 mm), zakres od -120 do 120', 'integer', NOW(), NOW()),
    ('PACKAGE_LABEL_OFFSET_Y_DOTS', '0',
     'Przesunięcie pionowe etykiety paczki 100x150 w punktach drukarki (8 punktów = 1 mm), zakres od -120 do 120', 'integer', NOW(), NOW());
