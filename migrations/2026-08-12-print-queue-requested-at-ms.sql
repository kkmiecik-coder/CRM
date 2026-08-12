-- Precyzja milisekundowa znacznika zlecenia wydruku etykiety.
--
-- DATETIME bez ułamków sekundy gubił część sekundy już przy zapisie, więc czas
-- życia zadania w kolejce był nie do zmierzenia poniżej sekundy: etykieta
-- wydrukowana w 90 ms raportowała się jako „0,9 s”. Po wdrożeniu sygnału push
-- cała interesująca skala zjawiska mieści się właśnie poniżej sekundy.
--
-- Idempotencja: to MODIFY istniejącej kolumny, nie dodanie nowej — powtórne
-- wykonanie ustawia tę samą definicję i nie rzuca błędem. Tabela trzyma rzędu
-- setek wierszy (ok. 600 na 30 dni), więc przebudowa jest natychmiastowa.
--
-- Uwaga przy czytaniu danych: `requested_at` stawia serwer CRM, a wiek zadania
-- w logu agenta liczy hub w Bachórzu ze swojego zegara. Różnica zegarów obu
-- maszyn wchodzi w ten pomiar — do oceny szybkości reakcji samego agenta służy
-- pole „reakcja”, mierzone jednym zegarem monotonicznym.
ALTER TABLE prod_print_queue
    MODIFY COLUMN requested_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3);
