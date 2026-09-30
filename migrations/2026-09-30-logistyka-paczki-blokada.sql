-- Logistyka etap 4, krok 4.2: blokada „jedna deklaracja paczek naraz” — patrz paczki.zablokuj_deklaracje().
-- Dwie pierwsze deklaracje różnych zamówień blokowały tę samą lukę indeksu prod_packages i zakleszczały się (MySQL 1213).
INSERT IGNORE INTO prod_config (config_key, config_value, config_description, config_type, created_at, updated_at)
VALUES ('logistyka_paczki_blokada', '',
        'Logistyka: blokada deklaracji paczek (jedna naraz)', 'string', NOW(), NOW());
