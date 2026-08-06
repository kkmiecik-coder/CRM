# Migracje archiwalne — NIE uruchamiane przez runner

Runner (`migration_service.py`) pomija podkatalogi, więc te pliki są tylko
zapisem historii. Trafiają tu migracje, których **nie da się już wykonać
na żadnym środowisku**, bo operują na strukturach, które od tamtej pory
zniknęły.

Nie usuwamy ich, bo tłumaczą, skąd wzięły się dzisiejsze kolumny i statusy.

| Plik | Dlaczego nie da się wykonać |
|---|---|
| `2026-04-30-add-completion-station.sql` | Operuje na `prod_items`, tabeli rozbitej 11.05.2026 na `prod_orders` / `prod_products` / `prod_configurations`. |
| `2026-05-15-remove-completion-station.sql` | Zdejmuje kolumny stanowiska kompletacji, których świeża baza nigdy nie dostanie (dodawał je plik wyżej). |
