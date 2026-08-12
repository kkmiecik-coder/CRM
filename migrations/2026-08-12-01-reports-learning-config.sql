/* Migracja: próg badge'a „Trwa nauka" w zakładce Raporty.
   Data: 2026-08-12

   Badge liczy się Z DANYCH, nie z kalendarza — ten klucz mówi tylko, ILE dni
   PRODUKCYJNYCH z sesjami pracowników musi się uzbierać, zanim badge zgaśnie.
   Dni produkcyjnych, nie kalendarzowych: hala pracuje pn-pt, więc „14 z 14 dni
   kalendarza" byłoby matematycznie nieosiągalne i badge zostałby na ekranie
   na zawsze.

   Domyślka MUSI być identyczna z worker_service.DOMYSLNA_KONFIGURACJA —
   powielenie jest celowe, żeby brak wiersza w bazie nie wywalał raportu.

   INSERT IGNORE — powtórka migracji nie nadpisze wartości ustawionej
   później w panelu konfiguracji. */

INSERT IGNORE INTO prod_config (config_key, config_value, config_description, config_type)
VALUES
    ('WORKER_LEARNING_DAYS', '14',
     'Ile dni produkcyjnych z sesjami pracowników musi się uzbierać, zanim badge „Trwa nauka" zniknie z raportów.',
     'integer');
