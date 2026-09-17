-- Migracja: konfigurowalne wyliczanie kosztów wysyłki
-- Data: 2026-09-15
-- Opis: Narzut na pakowanie przestaje być zaszytym w kodzie +30%. Cztery klucze
--       w calculator_settings opisują pełną regułę:
--           cena_koncowa = cena_kuriera * (1 + procent/100) + doplata_progowa
--       Dopłata należy się, gdy cena PO procencie leży po wybranej stronie progu.
--
--       Wartości zasiewane tutaj (30 / 0 / 0 / below) odtwarzają dotychczasowe
--       zachowanie co do grosza: przy progu 0 i stronie 'below' warunek
--       „cena < 0" nigdy nie zachodzi, więc dopłata wynosi 0, a cena końcowa
--       to dokładnie cena kuriera x 1,3. Deploy tej migracji NIE zmienia
--       żadnej wyceny — zmieni ją dopiero edycja w panelu Ustawień.
--
-- Idempotentność: INSERT IGNORE na unikalnym setting_key. Powtórny przebieg
--       nie nadpisze wartości ustawionych przez administratora w panelu.

INSERT IGNORE INTO `calculator_settings` (`setting_key`, `setting_value`, `description`)
VALUES ('shipping_markup_percent', '30', 'Narzut na pakowanie wysylki w procentach');

INSERT IGNORE INTO `calculator_settings` (`setting_key`, `setting_value`, `description`)
VALUES ('shipping_threshold_brutto', '0', 'Prog ceny wysylki brutto, od ktorego zalezy doplata');

INSERT IGNORE INTO `calculator_settings` (`setting_key`, `setting_value`, `description`)
VALUES ('shipping_surcharge_brutto', '0', 'Kwota doplaty brutto doliczana po wybranej stronie progu');

INSERT IGNORE INTO `calculator_settings` (`setting_key`, `setting_value`, `description`)
VALUES ('shipping_surcharge_side', 'below', 'Strona progu: below = ponizej, above = od progu w gore');
