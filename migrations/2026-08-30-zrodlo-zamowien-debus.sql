-- Źródło zamówień „Dębuś" — zamówienia złożone samodzielnie przez klienta
-- ze strony wyceny (checkout), bez udziału handlowca.
-- baselinker_id trzeba wcześniej założyć ręcznie w panelu BaseLinkera
-- (Ustawienia -> Źródła zamówień -> własne) i wpisać tutaj.
--
-- UWAGA WDROŻENIOWA: 99001 to wartość ZASTĘPCZA. Przed uruchomieniem tej
-- migracji na produkcji załóż źródło w panelu BaseLinkera i podmień liczbę
-- na realne id. Istniejące źródła „personal": 0 Detal, 63189 Czernecki,
-- 68970 Nowy B2B, 68971 Stały B2B, 68973 PH Nowy B2B, 68974 PH Stały B2B.
--
-- Wstawiamy przez WHERE NOT EXISTS, a NIE przez INSERT IGNORE: tabela
-- baselinker_config ma jedyny klucz na kolumnie `id` (AUTO_INCREMENT) —
-- nie ma UNIQUE na (config_type, baselinker_id), więc INSERT IGNORE nie
-- miałby czego zignorować i przy powtórnym wykonaniu pliku dołożyłby drugi
-- wiersz „Dębuś". Podzapytanie idzie przez pochodną tabelę (AS istniejace),
-- bo MySQL nie pozwala czytać tabeli docelowej wprost w podzapytaniu INSERT-a.
--
-- created_at/updated_at ustawiamy jawnie: kolumny nie mają DEFAULT w bazie
-- (wartość domyślna jest tylko po stronie modelu SQLAlchemy), a wszystkie
-- pozostałe źródła mają te pola wypełnione.
INSERT INTO baselinker_config
    (config_type, baselinker_id, name, is_default, is_active, sort_order,
     created_at, updated_at)
SELECT 'order_source', 99001, 'Dębuś', 0, 1, 100, NOW(), NOW()
FROM DUAL
WHERE NOT EXISTS (
    SELECT 1 FROM (SELECT config_type, baselinker_id FROM baselinker_config) AS istniejace
    WHERE istniejace.config_type = 'order_source'
      AND istniejace.baselinker_id = 99001
);
