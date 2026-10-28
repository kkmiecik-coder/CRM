-- Koniec okresu przejściowego agenta druku (wdrożenie 28.10.2026): etykiety drukuje wyłącznie agent druku v2.
-- Usuwa klucze starego agenta: jego token, chwile przełączenia drukarek i ostatni kontakt.
-- DRUKARKA_OBSLUGA_etykiety / _wysylka (= 'nowy') CELOWO zostają: między migracją a restartem (deploy.sh, do ~5 min
-- przez przeliczenie klientów) działa jeszcze stary kod, którego obsluga() przy braku wiersza zwraca 'stary' — agent v2
-- dostałby wtedy pusto i druk stanąłby na cały ten czas. Nowy kod ich nie czyta; usunie je późniejsza migracja.
-- Idempotentna: drugi przebieg nie ma czego usunąć.
DELETE FROM prod_config WHERE config_key IN ('LABEL_PRINTER_AGENT_TOKEN', 'DRUKARKA_OBSLUGA_etykiety_OD',
    'DRUKARKA_OBSLUGA_wysylka_OD', 'STARY_AGENT_OSTATNI_KONTAKT');
