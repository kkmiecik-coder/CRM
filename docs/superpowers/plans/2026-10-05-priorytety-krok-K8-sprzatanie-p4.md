# Priorytety produkcji, krok K8 — „sprzątanie P4” — plan implementacji

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Po 2–3 tygodniach stabilnej pracy P3 z kodu i bazy znika wszystko, co zostało po starym systemie priorytetów: `priority_service.py` z warstwą zgodności, kolumna `prod_products.priority_manual_override` z metodami `lock_priority`/`unlock_priority`/`is_priority_locked`, tabela `prod_priority_config` z modelem `ProductionPriorityConfig` i `PriorityConfigCache`, martwe klucze `prod_config`, a — tylko po potwierdzonym wycofaniu starej appki — lista `/stations/<kod>/orders`, delta `/orders/since` i pole `refresh_interval_seconds` tabletów. Produkcja przechodzi przez to bez ani jednej odpowiedzi 500: najpierw wchodzi kod bez odwołań (etap A), potem migracja DROP (etap B), a na wypadek wycofania jest przećwiczona migracja cofająca.

**Architecture:** Krok wyłącznie usuwa. Commity Tasków 1–4 to **etap A** (kod i testy, żadnego pliku w `migrations/`), commit Taska 5 to **etap B** (jedyny plik migracji: `DROP COLUMN` osłonięty `information_schema`, `DROP TABLE IF EXISTS`, `DELETE` jawnej listy kluczy) razem ze skryptem cofającym poza runnerem (`scripts/priorytety_p4_cofniecie.sql`). Synchronizacja z Base. woła `kolejka.utrwal()` wprost (K1 zostawił to na K8). Dowód: pełny pakiet pytest, migracja ×2 na kontenerze `db` i na świeżej kopii produkcji, kod etapu A na kopii **z** kolumną, kod etapu B po DROP, próba cofnięcia (skrypt + kod P1 z produkcji), skrypt symulacji na kopii po DROP.

**Tech Stack:** Flask 2 + SQLAlchemy < 2.0, MySQL 8.4 (produkcja) / SQLite in-memory (testy), pytest, Python 3.9 na produkcji.

**Spec:** `docs/superpowers/specs/2026-10-04-priorytety-produkcji-design.md` — sekcje 8.5 (kolumna martwa od P1, usuwana w P4), 8.8 (lista usunięć P4), 9.5 (`priority_service.py`, `test_priority_statusy_krawedzi.py`, `lock_priority`), 11 (krok P4, warunek „2–3 tygodnie P3 bez wycofania”, „P4: migracja przywracająca przed restartem”), 14 (zdjęcie `REFRESH_INTERVAL_SECONDS` i listy `/orders` po wycofaniu starej appki), 15 („Usunięte (P4)”), 16 (doprecyzowania z realizacji, dopisane przez K5 w grupach K1–K5; **K8 dopisuje grupy K6, K7, K8** — Task 6 Step 2b). Raporty K6 i K7 (`docs/superpowers/plans/raporty/2026-10-05-priorytety-krok-K6-raport.md`, `…-krok-K7-raport.md`) i plany K6, K7 (sekcje „Doprecyzowania”) są wejściem Taska 6. Symulacja: `docs/superpowers/specs/2026-10-04-priorytety-produkcji-symulacja.md`, „Analiza wyniku” D p. 7 (pomiar po wdrożeniu tym samym skryptem — skrypt musi działać po DROP) i „E. Decyzje”. Podręcznik centrali: `docs/superpowers/plans/2026-10-05-priorytety-produkcji-centrala.md`, sekcje 2, 3, 4a, 6, 8.0, 8.9.

**Sesja:** lokalna — pełny pakiet pytest w kontenerze `app`, migracja na kontenerze `db` i na kopii produkcji (SQLite nie zna `information_schema`, `PREPARE` ani `DROP COLUMN` na MySQL-u), podgląd z kodem trzech wersji (A, B, P1 z produkcji). **Model:** Opus 5.5, effort high (podręcznik 4a; tryb szybki dozwolony). Zastępczo Sonnet 5.5 high, gdy budżet ciśnie.

**Zależności:** K7 zakończony w obu częściach (P1 na produkcji, P3: wszystkie stanowiska w trybie `stol`), 2–3 tygodnie P3 bez wycofania, raporty K1–K7 z sekcją „Co następny krok musi wiedzieć” (punkty K8). Task 4 dodatkowo: stara appka zdjęta ze wszystkich tabletów (warunek W-3). Plan K7 (`…-krok-K7-wdrozenie-i-przelaczenie.md`) powstawał równolegle z tym planem; numery i hashe z wdrożenia bierzesz z dziennika centrali.

**Gałąź:** `claude/priorytety-produkcji`. Start: `git fetch origin && git checkout claude/priorytety-produkcji && git pull --ff-only origin claude/priorytety-produkcji`, potem **`git merge origin/main`** — po K7 `main` ma merge commit P1 (K7 Doprecyzowanie 3), którego gałąź nie zawiera, więc bez tego scalenia `git merge-base --is-ancestor origin/main HEAD` jest zawsze fałszem (raport K7, punkt K8: „K8 zaczyna od `git merge origin/main`”). Oczekiwane czyste scalenie; `git diff --stat HEAD^1 HEAD` (zmiany wniesione z `main`, np. poprawki logistyki po K7) do raportu. Konflikt → `git merge --abort`, **STOP**, karta „scalenie” (podręcznik 2 p. 2). Po scaleniu `git merge-base --is-ancestor origin/main HEAD` → prawda; commit scalenia to punkt startu (hash do raportu), nie należy do etapu A ani B. Nigdy `main`. Numery linii w planie dotyczą `claude/logistyka-etap-4` @ `b4b4a54d` (sprzed K1); kroki K1–K7 je przesunęły — szukaj po nazwie funkcji (`grep -n`), nazwy są podane wszędzie.

## Global Constraints

- **Python 3.9**: bez `X | Y` w adnotacjach poza plikami z `from __future__ import annotations`, bez `match`.
- Komentarze i docstringi **po polsku**; w tekstach dla ludzi „Base.”.
- **Krok usuwa, nie dodaje.** Żadnej nowej funkcji, końcówki, klucza `prod_config` ani zmiany zachowania poza tym, co wynika z usunięcia. Nazwy, na których stoją inne kroki (`kolejka.utrwal`, `stol.dopelnij`, `GET /api/mobile/stations/<kod>/desk`, `priorytety_tryb_<S>`, `priorytety_min_app_version_code`), zostają nietknięte.
- **Dwa etapy w historii gałęzi:** commity Tasków 1–4 nie zawierają żadnego pliku w `migrations/`; plik migracji P4 pojawia się wyłącznie w commicie Taska 5. Od tego zależy bezpieczne wdrożenie (sekcja „Okno wdrożenia”).
- **Kolejność blokad** (CLAUDE.md „Trasy logistyki — jeden piszący naraz”, „Deklaracje paczek — jedna naraz”, akapit pisarzy pozycji bez blokady zamówienia; spec 9.4) bez zmian: K8 nie dodaje pisarza ani blokady. Sekcja „Współbieżność” mówi, czego krok dotyka.
- Migracja **idempotentna**, bez `DELIMITER`, nazwa `RRRR-MM-DD-priorytety-p4-sprzatanie.sql` (data sesji K8, sortuje się po `2026-10-05-priorytety-produkcji.sql`). Wzór osłony: `migrations/2026-10-02-logistyka-niedostarczone-na-trasie.sql` (`information_schema` + `PREPARE/EXECUTE`).
- Serwisy nie commitują; żadnego `db.session.commit()` w handlerach API mobilnego; żadnych blokad w czasie HTTP do Base.
- Testy: `docker compose exec app pytest <ścieżki> -q -p no:cacheprovider`; TDD (test, który pada → zmiana → test zielony). SQLite in-memory wg konwencji repo (`tests/krawedzie_fixtures.py`, `tests/logistyka_fixtures.py`, `tests/blokady_pomocnicze.py`). Testy usuwamy wyłącznie z mapą „usunięty → równoważny” (Task 1) — pokrycie nie może zmaleć po cichu.
- **Nigdy** kodu gałęzi na bazie produkcyjnej (import `create_app()` odpala migracje). Kopia produkcji tylko w kontenerze `db` dewelopera.
- Repo publiczne: bez sekretów, IP, danych klientów (także w raporcie: liczby tak, numery zamówień i nazwy nie). `tools/print_agent` bez zmian.
- Commity Conventional Commits po polsku, temat bez polskich znaków, jeden na Task, stopka atrybucji własnej sesji; `docs/superpowers/` przez `git add -f`.
- Poza zakresem nie naprawiać — do raportu. Blokada → **STOP** i meldunek do centrali (sekcja „Ryzyka”).

## Warunki wejścia (potwierdza centrala w karcie)

| # | Warunek | Dowód w karcie | Bez niego |
|---|---|---|---|
| W-1 | K7 część 2 zakończona: wszystkie 7 stanowisk w `stol`, `priorytety_min_app_version_code` > 0 | wpis dziennika centrali z datą przełączenia ostatniego stanowiska | STOP całego kroku |
| W-2 | ≥ 14 dni od przełączenia ostatniego stanowiska bez wycofania (`stary`) i bez karty naprawczej P1/P3 w toku | dziennik centrali | STOP całego kroku |
| W-3 | Stara appka zdjęta: każde aktywne urządzenie (`prod_devices.is_active = 1`, heartbeat z ostatnich 7 dni) ma `last_app_version_code` ≥ progu **i** log nginx z ostatnich 7 dni ma 0 żądań `GET /api/mobile/stations/*/orders` (także `/orders/since`) | wynik zapytania i licznik z logu (bez IP i nazw urządzeń) — robi Konrad/centrala na serwerze | Task 4 **pomijasz** (adnotacja w raporcie); reszta kroku idzie |
| W-4 | Świeży zrzut produkcji (po P3, `mysqldump --single-transaction`, bez tabel sesji) dostarczony poza repo | ścieżka w karcie | Taski 1–5 idą; Task 6 (kopia) STOP, krok niezakończony |
| W-5 | Hash kodu P1/P3 działającego na produkcji (`git rev-parse HEAD` na serwerze) | dziennik centrali | próba cofnięcia w Task 6 niewykonalna → STOP Task 6 |

## Review Focus

1. **Okno wdrożenia bez 500:** kod etapu A nie mapuje ani nie czyta usuwanej kolumny i tabeli, więc działa i przed DROP, i po nim; ORM nie wymienia kolumny w INSERT ani SELECT: `test_model_pozycji_nie_mapuje_priority_manual_override`, `test_insert_i_select_pozycji_bez_priority_manual_override`, `test_model_konfiguracji_priorytetow_usuniety` (Task 2, 3) + kopia z kolumną (Task 6 Step 3a).
2. **Migracja P4 idempotentna, w osobnym commicie, nie rusza kluczy żywych ani wierszy blokad:** `test_drop_kolumny_osloniety_information_schema`, `test_delete_martwych_kluczy_jawna_lista`, `test_delete_nie_dotyka_wierszy_blokad_ani_kluczy_zywych`, `test_lock_wait_timeout_przed_alter` (Task 5), `test_kod_bez_martwych_kluczy` (Task 3 — kod nie założy usuniętych wierszy od nowa) + `flask migrate` ×2 na `db` i kopii, `git show --stat` commitów A/B (DoD 7).
3. **Cofnięcie działa naprawdę:** skrypt odtwarza kolumnę i tabelę w kształcie, który mapuje kod P1, i kod P1 z produkcji wstaje na kopii po cofnięciu: `test_cofniecie_odtwarza_kolumne_i_tabele_idempotentnie` (Task 5) + próba w Task 6 Step 3c.
4. **Synchronizacja z Base. przelicza rangi przez `kolejka.utrwal()` wprost i dalej nie rusza sesji wołającego:** `test_synchronizacja_wola_utrwal_wprost`, `test_aktualizacja_po_synchronizacji_wola_utrwal_wprost`, przepisany `test_brudna_sesja_po_priorytetach_nie_blokuje_zasilania_analityki` (Task 1).
5. **Usunięte testy mają równoważniki:** mapa w Task 1; nowe `test_utrwal_kazde_wywolanie_na_nowej_sesji`, `test_utrwal_pusta_kolejka_to_sukces` (jeśli K1 ich nie ma), przeniesiony `test_stale_statusy_produkcji_znaja_obie_kolejki` (Task 1).
6. **Ciche `try/except ImportError` w `__init__` nie gubi serwisów ani modeli po usunięciu:** `test_import_katalogu_w_modelu_nie_rozwala_serwisow` (uaktualniony), `test_pakiet_produkcji_ma_modele_i_serwisy` (Task 1, 3).
7. **`utrwal()` bez kolumny pisze tylko pozycje ze zmienioną rangą lub `is_priority`, w tej samej kolejności blokad, i nie pada po cichu na brakującym atrybucie:** `test_utrwal_podbija_updated_at_tylko_zmienionym`, `test_pozycja_migawki_bez_manual_override`, `success is True` w `test_insert_i_select_pozycji_bez_priority_manual_override` + niezmienione `test_utrwal_blokuje_zamowienia_przed_pozycjami_przed_zapisem`, `test_utrwal_zapisuje_tylko_zmienione_rosnaco_po_id` (Task 2).
8. **(Task 4, warunkowo) `desk` przenosi wszystko, co tablet brał z listy:** `test_desk_pakowania_niesie_podpowiedz_calego_zamowienia`, `test_desk_baner_weryfikacji_i_repack_reason`, `test_desk_etag_zmienia_sie_po_zmianie_sposobu`, `test_lista_i_delta_tabletu_usuniete`, `test_summary_bez_refresh_interval_seconds` (Task 4).
9. **Doprecyzowania K6–K8 nie giną po drodze:** plany K6 i K7 odsyłają swoje Doprecyzowania „do specu kartą dokumentacyjną”, ale żadna karta mapy kroków (podręcznik, sekcja 3) tego nie robi — K8 jest ostatnim krokiem programu i domyka spec 16 oraz CLAUDE.md: `test_spec_ma_grupy_k6_k7_k8`, rozszerzony `test_claude_md_po_p4` (próg `999999`, restart przy zmianie ustawień wg stanu pamięci podręcznej, dwa etapy P4) (Task 6).

## Decyzje przyjęte (ze specu i symulacji)

1. Spec v2 (4.10, zatwierdzony przez Konrada 4–5.10), sekcja 11: P4 = DROP `prod_priority_config`, `priority_manual_override`; `priority_service.py`, puste metody, martwy JS (usunięty już w K4a), `REFRESH_INTERVAL_SECONDS` — warunek „2–3 tygodnie P3 bez wycofania”.
2. Spec 8.5: `priority_manual_override` martwa od P1 (nic nie ustawia True, `utrwal()` zeruje napotkane); kolumna i `lock_priority`/`unlock_priority`/`is_priority_locked` usuwane w P4.
3. Spec 8.8: `prod_priority_config` (`ProductionPriorityConfig`, `PriorityConfigCache`), `priority_manual_override`, martwe klucze (`PRIORITY_RECALC_INTERVAL_HOURS`, `PRIORITY_ALGORITHM_VERSION`, `STATION_*_PRIORITY_SORT`), martwe końcówki (zrobione w K2/K4a), `REFRESH_INTERVAL_SECONDS` po wycofaniu starej appki.
4. Spec 9.5: `services/priority_service.py` — P1 warstwa zgodności, P4 usunięcie; `test_priority_statusy_krawedzi.py` traci przedmiot (jedna lista statusów w `priorytety/stale.py`).
5. Spec 11 „Wycofanie”: P4 cofa migracja przywracająca, wykonana **przed** restartem.
6. Spec 14: zdjęcie `REFRESH_INTERVAL_SECONDS` i listy `/orders` dla tabletów dopiero po wycofaniu starej appki.
7. Podręcznik centrali 8.9 (5.10): warunek wejścia potwierdza centrala w karcie (data P3, brak wycofań, stara appka zdjęta — inaczej `REFRESH_INTERVAL_SECONDS` i lista `/stations/<kod>/orders` zostają); migracja DROP i migracja cofająca w raporcie.
8. Plan K1 (5.10), Doprecyzowania: wywołania przeliczenia w `sync_service` zostały na warstwie zgodności; **K8 przepina je wprost na `kolejka.utrwal()`** przy usuwaniu `priority_service.py`.
9. Plany K4a i K4b (5.10): do K8 trafiają `priority_range` w `GET /products/filters-data` (nikt nie czyta), wiersze martwych kluczy w `prod_config`, import `ProductionPriorityConfig` w `routers/api/__init__.py`.
10. Plan K6 (5.10): `refresh_interval_seconds`, `/stations/<kod>/orders` i `/orders/since` zostają, dopóki jakikolwiek tablet ma starą appkę (kontrakt `docs/api-mobile-priorytety.md`, sekcja o starej appce).
11. Symulacja, „Analiza wyniku” D p. 7 (5.10): po wdrożeniu mierzymy tym samym skryptem `scripts/symulacja_priorytetow.py` — po DROP skrypt ma dalej działać (wykrywa kolumny przez inspector, `:26`).
12. Decyzje Konrada 5.10 (spec 13 P-4, P-5, P-8; spec 14 — bloki odrzucone): próg „Blisko terminu” 3 dni robocze, grupa (gatunek, klasa, grubość) po najbliższym terminie, w grupie termin przed długością, „Blisko terminu” nad „Rozpoczęte” — K8 ich nie dotyka (`policz`, `kandydaci_stanowiska`, seed drabiny i `priorytety_blisko_terminu_dni` bez zmian); symulacja w Task 6 z `--blisko 3`.

## Doprecyzowania (do specu — K5 jest za nami; K8 przenosi je sam w Task 6 Step 2b, sekcja 16, razem z Doprecyzowaniami K6 i K7)

1. **Wdrożenie P4 dwuetapowe** (spec 11 mówi tylko o migracji przywracającej): etap A = kod bez odwołań, etap B = migracja DROP po `Deploy complete!` etapu A; każdy etap osobnym merge commitem na `main` (jak P1, K7 Doprecyzowanie 3), wycofanie przez `git revert -m 1`. Powód w sekcji „Okno wdrożenia”.
2. **`REFRESH_INTERVAL_SECONDS` zostaje jako klucz** — czytają go monitory hali (`routers/stations/__init__.py:179`, `get_station_config`) i Konfiguracja („Interwał odświeżania — interfejsy stanowisk”, `config-tab-content.html:415-450`). Z tabletów znika tylko pole `refresh_interval_seconds` w `GET /summary` (Task 4). Spec 8.8 i 14 mówią o zdjęciu klucza — to doprecyzowanie je zawęża.
3. **Migracja cofająca jest skryptem poza runnerem** (`scripts/priorytety_p4_cofniecie.sql`). Przy wycofaniu commit wycofujący kopiuje ją do `migrations/` pod nową datowaną nazwą, żeby `deploy.sh` wykonał ją przed restartem. Odtwarza strukturę (kolumna `TINYINT(1) NULL DEFAULT 0` z indeksem, pusta `prod_priority_config`), nie dane: kod P1 po K4b nie czyta wierszy `prod_priority_config` ani martwych kluczy.
4. **Martwe klucze to jawna lista** ustalona na kopii produkcji (Task 1 Step 0), bez `LIKE` — `STATION_*_PRIORITY_SORT` ze specu 8.8 rozwinięte do kluczy, które istnieją.
5. **Bootstrap DDL bez kolumny:** `scripts/create_split_tables.sql` i `scripts/migrate_prod_items_to_split_tables.py` tracą `priority_manual_override` (parytet z modelem pilnuje `tests/test_bootstrap_ddl_krawedzie.py`).
6. **Wynik synchronizacji zachowuje kształt:** klucze `priority_recalc_triggered`, `priority_recalc_duration`, `manual_overrides_preserved` (kolumny `prod_sync_logs`) zostają; linie `:999-1001` bez zmian (`manual_overrides_preserved` → 0, bo raport `utrwal()` nie ma tego klucza; `priority_recalc_duration` dalej `'00:00:00'` z braku `calculation_duration` — istniejąca usterka typu kolumny INT, „Poza zakresem”, krok jej nie naprawia). Usuwanie kolumn historii synchronizacji to nie P4.
7. **`ProductionPriorityConfig` czyta jeszcze `main_routers.config_panel`** (`:228`, `:247-255`; K4b go nie wymienił) — K8 usuwa ten odczyt. Sama trasa renderuje nieistniejący `panel/config.html` (martwa od dawna) i zostaje — do raportu.
8. **`lock_wait_timeout = 30` w migracji:** `ALTER TABLE … DROP COLUMN` czeka na blokadę metadanych za każdą otwartą transakcją na `prod_products`, a domyślny `lock_wait_timeout` to rok — w tym czasie wszystkie kolejne zapytania do tabeli stoją za nim. Z limitem migracja po 30 s pada, `deploy.sh` przerywa deploy przed restartem i cofa kod (stan spójny), a etap B ponawia się poza godzinami pracy hali.

## Ugruntowanie w kodzie

Stan na `b4b4a54d` (sprzed K1). Kolumna „Po K1–K7” mówi, co według planów zmieniły poprzednie kroki — **sprawdź grepem w Step 0 Taska 1**, nie zakładaj.

| Miejsce | Stan na `b4b4a54d` | Po K1–K7 (wg planów) | K8 |
|---|---|---|---|
| `modules/production/services/priority_service.py` (988 linii) | `nowa_sesja_priorytetow` `:83`, `NewPriorityCalculator` `:96`, `recalculate_all_priorities` `:167`, `get_priority_calculator` `:886`, `recalculate_priorities` `:907`, `recalculate_all_priorities` `:923`, `get_priority_statistics` `:932` | K1: warstwa zgodności `WarstwaZgodnosciPriorytetow` → `kolejka.utrwal()`; klasa i statystyki nietknięte | **usunięty** |
| `services/sync_service.py` | `process_orders_with_priority_logic`: przeliczenie `:929-943` (`get_priority_calculator().recalculate_all_priorities()`), wynik `:999-1001`; `_update_product_priorities` `:3031-3045` (woła `:2195`) | K1: log `:938-939` z kluczy nowych, wywołania bez zmian | `kolejka.utrwal()` wprost w obu miejscach |
| `services/__init__.py` | docstring `:11`; import `:52-58`; `_priority_calculator_instance` `:70`; `get_priority_calculator` `:102-115`; `invalidate_caches` `:122`; `reload_services` `:142-158` (`:147`, `:152`, `:157`); `recalculate_priorities` `:236-251`; `health_check` `:292`, `:296`; `__all__` `:319`, `:325`, `:335` | bez zmian | wszystkie odwołania do kalkulatora usunięte |
| `modules/production/__init__.py` | import serwisów w jednym `try` `:37-48` (`NewPriorityCalculator` `:42`); import modeli `:53-62` (`ProductionPriorityConfig` `:56`) | K1 dopisał import `priorytety.models` | `:42` i `:56` usunięte |
| `services/blokady_zamowien.py` docstring `kod_mysql` | `:127-130` (przeciąganie, `priority_service`) | K2: „przeliczenie priorytetów (`priority_service…`, od K1 `kolejka.utrwal`) i zapis gwiazdek oraz drabiny” | tylko `kolejka.utrwal` |
| `models.py` `ProductionProduct` | `priority_manual_override` `:384`; `is_priority_locked` `:491-493`; `lock_priority` `:513-518`; `unlock_priority` `:520-521`; `complete_task` reset `:714-719` | K1: metody puste z docstringiem „usuwane w P4”, blok `:714-719` usunięty | kolumna, właściwość i obie metody usunięte |
| `models.py` `ProductionPriorityConfig` | docstring modułu `:9`; klasa `:732-757` (`prod_priority_config`) | bez zmian | usunięte |
| `priorytety/services/kolejka.py` (K1) | — (nie istnieje) | K1: `utrwal()` dokłada do zapisu pozycję z `priority_manual_override = True` i zeruje ją; `Pozycja(…, manual_override)` w migawce | warunek, przypisanie, pole `Pozycja.manual_override` i jego odczyt w `_migawka` usunięte |
| `routers/api/products_api.py` | `_serialize_product` `:178` (`priority_manual_override`); `get_filters_data` `:2430`, `priority_range` `:2478-2490`, `:2506`; martwe końcówki `:2534-2597`, `:2880-2996`, `:3253-3676` | K2: martwe końcówki usunięte; K4a: `:178` i `priority_range` zostawione dla K8 | `:178` i `priority_range` usunięte |
| `routers/api/__init__.py` | `:13`, `:15` import `ProductionPriorityConfig` | K4b: zostawiony dla K8 | usunięty z obu linii |
| `routers/api/config_api.py` | import `:14`; lokalny import `:158`; odczyt `:328-352`, `:362` | K4b: odczyt i `:14` usunięte; `:158` niewymieniony | resztki usunięte (grep) |
| `routers/main_routers.py` `config_panel` | lokalny import `:228`; odczyt i `priority_configs=` `:247-255` | bez zmian | odczyt usunięty |
| `services/config_service.py` | `PriorityConfigCache` `:1022-1056` (czyta `*_WEIGHT`, nikt nie woła); `REFRESH_INTERVAL_SECONDS` `:15`, `:62`, `:390` | K4b: `PRIORITY_RECALC_INTERVAL_HOURS` `:75` usunięty | `PriorityConfigCache` usunięty; `REFRESH_INTERVAL_SECONDS` zostaje |
| `routers/mobile_api.py` | importy `:36-45` (`get_station_queue_delta` `:38`, `parse_since_ts` `:41`); `KSZTALT_ODPOWIEDZI_KOLEJKI` `:137`; `station_orders` `:242-326`; `station_summary` `:634-697` (segment konfiguracji ETagu `:672-678`); `station_orders_since` `:699-747` | K3: `KSZTALT` 6, `priorytet` w liście i delcie, `desk`, `postpone`, `realtime-token`, `KSZTALT_ODPOWIEDZI_STOLU` | Task 4 (warunkowo): lista, delta, `KSZTALT_ODPOWIEDZI_KOLEJKI` i segment ETagu usunięte |
| `services/mobile_api_service.py` | `compute_station_summary` `:1604-1668` (`REFRESH_INTERVAL_SECONDS` `:1643-1653`, pole `:1666`); `parse_since_ts` `:1675-1700` (jedyny wołający `mobile_api.py:731`); `get_station_queue_delta` `:1752-1799` | K3: `priorytety=` w delcie | Task 4: pole, `parse_since_ts`, `get_station_queue_delta` usunięte |
| `logistics/routers/weryfikacja_api.py:33`, `routers/mobile_api.py:139` | komentarze „jak `KSZTALT_ODPOWIEDZI_KOLEJKI`” | bez zmian | Task 4: komentarze odsyłają do `KSZTALT_ODPOWIEDZI_STOLU` |
| `scripts/create_split_tables.sql:93`, `scripts/migrate_prod_items_to_split_tables.py:122`, `:143` | kolumna w bootstrapowym DDL i w obu listach INSERT/SELECT | bez zmian | usunięte (parytet) |
| `scripts/smoke_test_rework.py:203-207` | asercje `priority_manual_override`, `is_priority is False`, `priority_rank is None` | K1 nie ruszał (skrypt ręczny) | asercje na stan P1: `priority_rank == 0`, `is_priority is True`, bez kolumny |
| testy | `tests/test_priority_statusy_krawedzi.py` (`:86`, `:94`, `:109`, `:160`); `tests/test_sales_ingest_wyzwalacze.py` (atrapa `:519-535`, `_PriorytetyKtorePadajaBrudzac` `:840-857`, `_scena_priorytetow` `:905-925`, 11 testów klasy `:954`, `:1015`, `:1070`, `:1102`, `:1141`, `:1315`, `:1331`, `:1345`, `:1360`, `:1388`, `:1441`, test analityki `:1163-1185`); `tests/test_krawedzie_model.py:192-207`; `tests/test_routing_krawedzie.py:256-278`; `tests/test_mobile_api_alias_krawedzi.py:577-630`, `:720`; `tests/test_paczki_podpowiedz.py:62-110`; `tests/test_weryfikacja_problem.py:205-215`; `tests/test_logistyka_mobile.py:123-141` | K1: `test_priority_statusy_krawedzi.py` uaktualniony (test stałych, statystyki, czysta sesja), `test_priorytety_kolejnosc_zapisow.py` przepisany (m.in. `test_warstwa_zgodnosci_wola_utrwal`, `test_utrwal_zeruje_manual_override_i_podbija_updated_at`), `test_priorytety_dorobka.py` (`…_bez_manual_override`, `test_lock_i_unlock_priority_nic_nie_robia`), `test_routing_krawedzie.py:256-278` uaktualniony; K3: testy `KSZTALT` 6; K5: `tests/test_priorytety_dokumentacja.py` | wg Tasków 1–4 |
| `CLAUDE.md` | akapit pisarzy pozycji `:367-369`, `:384` (`priority_service`) | K5: sekcja `### Priorytety produkcji` („`priority_service.py` to warstwa zgodności do P4”), akapit pisarzy poprawiony | Task 6 |

**Czego w kodzie nie ma (żeby nikt nie szukał):** migracji, która zakłada `prod_priority_config` albo `priority_manual_override` — obie powstały z `create_all()` albo z `scripts/create_split_tables.sql`, więc kształt kolumny na produkcji jest nieznany (Task 1 Step 0 sprawdza go na kopii); czytelnika kluczy `*_WEIGHT` poza `PriorityConfigCache` (`config_service.py:1044-1047`); wołającego `PriorityConfigCache`, `health_check()` i `reload_services()` z pakietu `services` (grep `modules app.py tests` → tylko definicje); konsumenta `priority_range` w JS (`products-module.js:982` to TODO); migracji `DROP COLUMN` w formacie `.sql` (jedyne `DROP COLUMN` to `migrations/022_partner_academy_drop_pesel.py` — Python przez `SHOW COLUMNS`; K8 trzyma się wzoru `.sql` z `information_schema`, jak K1).

## Okno wdrożenia (dlaczego dwa etapy)

`deploy.sh` wykonuje `flask migrate` **przed** restartem (krok 5), a potem przeliczenie klientów do 300 s (krok 6). Przez cały ten czas działają workery z kodem sprzed deployu, a gunicorn dokłada nowe workery z kodem z dysku (CLAUDE.md, Deployment, krok 5). Kod P1/P3 mapuje `priority_manual_override` w `ProductionProduct`, więc **każde** zapytanie ORM o pozycje (tablety, panel, cron) po DROP kończy się MySQL 1054 „Unknown column”. Jeden push z kodem i migracją = kilka minut 500 na całej produkcji.

| Etap | Commity | Na dysku po `git reset` | Schemat | Bezpieczne, bo |
|---|---|---|---|---|
| **A** | Taski 1–4 | kod bez odwołań | kolumna i tabela są | kod A ich nie mapuje; INSERT pozycji bez kolumny bierze `DEFAULT`/NULL (W: Task 1 Step 0 sprawdza `NULL`/`DEFAULT` na kopii) |
| **B** | Taski 5–7 | kod A + plik migracji | DROP przed restartem | działające workery mają kod A — kolumny nie znają |

Etap B dopiero po `Deploy complete!` etapu A w `logs/deploy.log` (drugi push wcześniej trafi w lock i sam się nie wdroży — CLAUDE.md, Deployment) i po dniu pracy hali na etapie A bez błędów. Etap B najlepiej poza zmianą (blokada metadanych przy `ALTER`, Doprecyzowania 8).

Oba etapy wchodzą na `main` **merge commitem** (K7 Doprecyzowanie 3 — wycofanie = jeden `git revert -m 1`): etap A to PR z gałęzi pomocniczej `claude/priorytety-p4-etap-a` wskazującej `<hash A>` (`git push origin <hash A>:refs/heads/claude/priorytety-p4-etap-a`), etap B to PR `claude/priorytety-produkcji` → `main`. Nie `git push origin <hash>:main` — to fast-forward bez merge commita, wycofanie wymagałoby wtedy revertu każdego commitu z osobna.

**Wycofanie:**
- etap A (przed B): `git revert -m 1 <merge A>` → PR do `main` (kod P1) — schemat nietknięty, nic więcej;
- po etapie B: commit wycofujący = `git revert -m 1 <merge B>` i `git revert -m 1 <merge A>` (kod P1) **plus** `scripts/priorytety_p4_cofniecie.sql` skopiowany do `migrations/<data>-priorytety-p4-cofniecie.sql`, jednym PR-em; `deploy.sh` wykona migrację przed restartem. Krótkie okno: workery dołożone przez gunicorna między `git reset` a końcem migracji (ułamek sekundy dla `ADD COLUMN`) dostaną kod P1 bez kolumny — wycofywać poza godzinami pracy hali. Ponowne wdrożenie K8 po takim wycofaniu wymaga migracji DROP **pod nową nazwą** (runner pamięta wykonane pliki po nazwie).

## Współbieżność (CLAUDE.md „Trasy logistyki — jeden piszący naraz”, spec 9.4)

K8 nie dodaje pisarza, blokady ani wywołania HTTP. Dotyka trzech miejsc związanych z blokadami:

1. **`kolejka.utrwal()` (Task 2).** Kolejność bez zmian: zwykłe odczyty migawki na własnej sesji → `prod_orders` `FOR UPDATE` rosnąco po id (tylko zamówienia ze zmianą) → `prod_products WHERE order_id IN (…) ORDER BY id FOR UPDATE` → jeden flush przy commicie (UPDATE-y jednego mappera po PK, zamówienia przed pozycjami); jedno ponowienie po 1213 na nowej sesji. Usunięcie zerowania `priority_manual_override` tylko zmniejsza zbiór zapisywanych pozycji. Testy pilnujące: `test_utrwal_blokuje_zamowienia_przed_pozycjami_przed_zapisem`, `test_utrwal_zapisuje_tylko_zmienione_rosnaco_po_id`, `test_utrwal_bez_zmian_nie_bierze_blokad`, `test_utrwal_ponawia_raz_po_1213_na_nowej_sesji` (K1, bez zmian asercji kolejności).
2. **Synchronizacja z Base. (Task 1).** `kolejka.utrwal()` w tym samym miejscu, co dziś warstwa zgodności: po pętli z commitem per zamówienie (`sync_service.py:866`) i po zmianach statusów w Base. (HTTP `set_status_for_imported_order`, `:915-926`) — przeliczenie nie trzyma blokad w czasie HTTP i nie widzi niezatwierdzonej pracy wołającego. K8 nie przesuwa wywołania. Test: `test_synchronizacja_wola_utrwal_wprost` + testy analityki z `tests/test_sales_ingest_wyzwalacze.py`.
3. **Migracja (Task 5).** `ALTER TABLE prod_products DROP COLUMN` bierze wyłączną blokadę metadanych (online DDL InnoDB, krótkie okna na początku i końcu); `lock_wait_timeout = 30` ogranicza czekanie (Doprecyzowania 8). `DELETE FROM prod_config` blokuje tylko wiersze z jawnej listy — **nigdy** wierszy blokad `logistyka_trasy_blokada`, `logistyka_paczki_blokada`, `priorytety_blokada_<S>` ani kluczy `priorytety_*`/`DEADLINE_*` (`test_delete_nie_dotyka_wierszy_blokad_ani_kluczy_zywych`). Na kopii mierzysz czas migracji (Task 6).

Task 4 usuwa wyłącznie końcówki odczytu bez blokad (lista, delta); jedyną drogą pobrania na stół zostaje `stol.dopelnij(S)` w `GET desk` (blokada `priorytety_blokada_<S>`, spec 5.2) — bez zmian. Trybów wyścigów z K5 krok nie powtarza (żaden pisarz się nie zmienia); jeśli centrala zażąda regresji, nazwy trybów są w raporcie K5.

## Środowisko

- `PYTEST <ścieżki>` = `docker compose exec app pytest <ścieżki> -q -p no:cacheprovider`. Pełny pakiet zajmuje dużo pamięci — nigdy dwa naraz.
- Migracja na kontenerze `db`: `docker compose exec app flask migrate` (×2), `docker compose exec app flask migrate-status`; zapytania przez `docker compose exec db mysql -u<user> -p <baza> -e "…"` (dane z lokalnego `config/core.json`, nie do raportu).
- **Kopia produkcji** jak w K5: osobna baza `prod_kopia_p4` w kontenerze `db` z zrzutu z W-4; podgląd = osobny kontener `app` z własnym `config/core.json` (URI na tę bazę), port i katalog wg karty centrali. Kod podglądu przełączasz `git checkout <hash>` w katalogu podglądu (A, B, P1 z W-5). `REALTIME` na podglądzie wyłączony (`enabled=false`) — sygnały nie są przedmiotem kroku.

## Mapa plików

| Plik | Task | Rola |
|---|---|---|
| `modules/production/services/priority_service.py` | 1 | **usunięty** |
| `modules/production/services/sync_service.py`, `services/__init__.py`, `modules/production/__init__.py:42`, `services/blokady_zamowien.py` (docstring) | 1 | przepięcie na `kolejka.utrwal`, reeksporty |
| `tests/test_priority_statusy_krawedzi.py` | 1 | **usunięty** (test stałych przeniesiony) |
| `tests/test_sales_ingest_wyzwalacze.py`, `tests/test_priorytety_kolejnosc_zapisow.py`, `tests/test_krawedzie_model.py`, `tests/test_priorytety_kolejka.py` | 1 | atrapy na `kolejka.utrwal`, usunięte testy klasy, równoważniki |
| `tests/test_priorytety_p4_sprzatanie.py` (nowy) | 1–4 | testy nieobecności i modelu po usunięciach |
| `modules/production/models.py` (`ProductionProduct`), `priorytety/services/kolejka.py`, `routers/api/products_api.py` (`_serialize_product`) | 2 | kolumna i metody |
| `scripts/create_split_tables.sql`, `scripts/migrate_prod_items_to_split_tables.py`, `scripts/smoke_test_rework.py` | 2 | bootstrap DDL i skrypt dymny |
| `tests/test_routing_krawedzie.py`, `tests/test_priorytety_dorobka.py`, `tests/test_priorytety_kolejnosc_zapisow.py`, `tests/test_priorytety_kolejka.py` (konstruktory `Pozycja`), `tests/test_bootstrap_ddl_krawedzie.py` | 2 | |
| `modules/production/models.py` (`ProductionPriorityConfig`, docstring), `services/config_service.py` (`PriorityConfigCache`), `modules/production/__init__.py:56`, `routers/api/__init__.py:13,15`, `routers/api/config_api.py`, `routers/main_routers.py` (`config_panel`), `routers/api/products_api.py` (`get_filters_data`) | 3 | model, pamięć podręczna, martwe odczyty, `priority_range` |
| `routers/mobile_api.py`, `services/mobile_api_service.py`, `logistics/routers/weryfikacja_api.py:33`, `docs/api-mobile-priorytety.md` | 4 (warunkowo) | lista, delta, `refresh_interval_seconds` |
| `tests/test_paczki_podpowiedz.py`, `tests/test_weryfikacja_problem.py`, `tests/test_logistyka_mobile.py`, `tests/test_mobile_api_alias_krawedzi.py`, testy listy z K3 | 4 (warunkowo) | przepięcie na `desk` albo usunięcie |
| `migrations/RRRR-MM-DD-priorytety-p4-sprzatanie.sql` (nowy), `scripts/priorytety_p4_cofniecie.sql` (nowy), `tests/test_migracja_priorytety_p4.py` (nowy) | 5 | etap B i cofnięcie |
| `CLAUDE.md`, `tests/test_priorytety_dokumentacja.py`, `docs/superpowers/specs/2026-10-04-priorytety-produkcji-design.md` (sekcja 16 + odesłania) | 6 | dokumentacja po P4; Doprecyzowania K6, K7, K8 w specu i CLAUDE.md |
| `docs/superpowers/plans/raporty/2026-10-05-priorytety-krok-K8-raport.md` (nowy) | 7 | raport kroku |

---

### Task 1: `priority_service.py` out — synchronizacja woła `kolejka.utrwal()` wprost

**Files:**
- Delete: `modules/production/services/priority_service.py`, `tests/test_priority_statusy_krawedzi.py`
- Modify: `modules/production/services/sync_service.py` (`process_orders_with_priority_logic` `:929-943`, `_update_product_priorities` `:3031-3045`), `modules/production/services/__init__.py` (miejsca z tabeli ugruntowania), `modules/production/__init__.py:42`, `modules/production/services/blokady_zamowien.py` (docstring `kod_mysql`)
- Modify: `tests/test_sales_ingest_wyzwalacze.py`, `tests/test_priorytety_kolejnosc_zapisow.py`, `tests/test_krawedzie_model.py:192-207`, `tests/test_priorytety_kolejka.py`
- Create: `tests/test_priorytety_p4_sprzatanie.py`

**Interfaces:**
- Consumes (K1, bez zmian): `kolejka.utrwal(zrodlo=None, user_id=None) -> dict` z kluczami `success`, `zamowien`, `pozycji`, `zmienione_zamowienia`, `zmienione_pozycje`, `ostrzezenia`, `duration_seconds`, `error`; nigdy nie rzuca, nigdy nie dotyka `db.session`. `kolejka.nowa_sesja()`. `priorytety.stale.STATUSY_PRODUKCJI`.
- `sync_service` (pseudokod):
  ```
  # process_orders_with_priority_logic, w miejscu :931-935
  from modules.production.priorytety.services import kolejka
  priority_recalc_result = kolejka.utrwal()      # wynik :999-1001 bez zmiany kształtu (Doprecyzowania 6)
  # _update_product_priorities
  wynik = kolejka.utrwal(); log 'products_updated' = wynik.get('pozycji'), błąd = wynik.get('error')
  ```
  Import modułu (`kolejka.utrwal()` przez atrybut), nie funkcji — testy podmieniają `kolejka.utrwal` przez `monkeypatch.setattr`.
- `modules.production.services` traci: `NewPriorityCalculator`, `get_priority_calculator`, `recalculate_priorities`, `_priority_calculator_instance`, klucze `NewPriorityCalculator` i `priority_calculator_instance` w `health_check()`.

**Mapa usuwanych testów (równoważniki — Review Focus 5):**

| Usunięty | Właściwość | Równoważnik |
|---|---|---|
| `test_udane_priorytety_nie_zatwierdzaja_pracy_wolajacego` (`test_sales_ingest…:954`) | przeliczenie nie commituje cudzej pracy | `test_utrwal_nie_commituje_ani_nie_cofa_sesji_wolajacego` (K1) |
| `test_awaria_w_oknie_nie_zostawia_pracy_priorytetow_w_cudzej_sesji` (`:1015`), `test_nieudane_priorytety_sprzataja_po_sobie_a_nie_po_wolajacym` (`:1102`) | błąd nie brudzi `db.session` | `test_nieudane_utrwal_zostawia_db_session_czysta` (K1) |
| `test_awaria_commitu_w_sterowniku_nie_zabiera_wolajacemu_transakcji` (`:1070`) | błąd commitu własnej sesji | `test_utrwal_nie_commituje_ani_nie_cofa_sesji_wolajacego` + `test_utrwal_inny_kod_bez_ponowienia` (K1) |
| `test_udane_priorytety_nadal_zapisuja_swoja_prace` (`:1141`) | zapis dochodzi do bazy | `test_utrwal_zapisuje_tylko_zmienione_rosnaco_po_id` (K1) |
| `test_awaria_pobierania_produktow_nie_udaje_pustej_kolejki` (`:1315`), `test_awaria_bazy_nie_konczy_przeliczania_sukcesem` (`:1331`) | błąd odczytu ≠ sukces | `test_utrwal_nie_rzuca_przy_bledzie_odczytu` (K1, `success False`) |
| `test_pusta_kolejka_nadal_jest_sukcesem` (`:1345`) | brak aktywnych = sukces | **nowy** `test_utrwal_pusta_kolejka_to_sukces`, jeśli K1 nie ma odpowiednika |
| `test_awaria_zarezerwowanych_rang_nie_udaje_ich_braku` (`:1360`) | rezerwacje rang | bez przedmiotu (rezerwacji nie ma od P1) |
| `test_sesja_przeliczania_nie_wycieka_do_innego_watku` (`:1388`), `test_zagniezdzone_przeliczanie_nie_podmienia_sesji_zewnetrznemu` (`:1441`) | sesja nie jest współdzielona | **nowy** `test_utrwal_kazde_wywolanie_na_nowej_sesji` (dwa wywołania → dwie różne sesje z `nowa_sesja`, obie zamknięte; moduł `kolejka` nie trzyma sesji w atrybucie) |
| `test_priority_statusy_krawedzi.py`: test stałych (K1: `test_stale_statusy_produkcji_znaja_obie_kolejki`) | jedna lista statusów | **przeniesiony** do `tests/test_priorytety_kolejka.py` bez zmian treści |
| `test_priority_statusy_krawedzi.py`: dwa testy statystyk (`:94`, `:109`) | `get_priority_statistics` | bez przedmiotu (funkcja usunięta; liczniki panelu liczą K2/K4b) |
| `test_priority_statusy_krawedzi.py`: test czystej sesji (`:160`, po K1 na `utrwal`) | błąd nie brudzi sesji | `test_nieudane_utrwal_zostawia_db_session_czysta` (K1) |
| `test_priorytety_kolejnosc_zapisow.py`: `test_warstwa_zgodnosci_wola_utrwal` (K1) | warstwa zgodności | bez przedmiotu; zastępuje `test_synchronizacja_wola_utrwal_wprost` |

- [ ] **Step 0: Punkt wyjścia, inwentarz, kopia**
  1. Warunki W-1…W-5 z karty przepisane do notatek raportu; brak W-1/W-2 → STOP.
  2. `PYTEST tests/` → liczby (passed/skipped) do raportu jako punkt wyjścia; `blog_seo` (`docker compose exec app bash -c "cd integrations/blog_seo && python -m pytest -q"`).
  3. Inwentarz (wynik do raportu):
     `grep -rn --include=*.py --include=*.js --include=*.html --include=*.sql -E "priority_service|NewPriorityCalculator|get_priority_calculator|recalculate_priorities\b|get_priority_statistics|nowa_sesja_priorytetow|PriorityError|priority_manual_override|is_priority_locked|lock_priority|unlock_priority|ProductionPriorityConfig|PriorityConfigCache|prod_priority_config|priority_range|PRIORITY_RECALC_INTERVAL_HOURS|PRIORITY_ALGORITHM_VERSION|_PRIORITY_SORT|_WEIGHT'" modules app.py scripts tests CLAUDE.md`
     Porównaj z tabelą ugruntowania; każde trafienie spoza niej → do Tasku, który obejmuje ten obiekt, albo do raportu („Poza zakresem”), nigdy pominięte bez słowa. Sprawdź nazwy testów K1 z mapy (`grep -n "def test_utrwal_" tests/`); brak równoważnika → dopisz go w tym Tasku.
  4. Raporty K1–K7, sekcje „Co następny krok musi wiedzieć” → punkty K8: każdy przypisz do Tasku albo „Poza zakresem”.
  5. Kopia (W-4): `CREATE DATABASE prod_kopia_p4`, import zrzutu, podgląd wg karty z kodem W-5. Zapytania (wynik do raportu, bez danych klientów):
     `SHOW COLUMNS FROM prod_products LIKE 'priority_manual_override'` — **`Null = NO` i `Default = NULL` → STOP** (etap A dawałby błąd 1364 przy każdym INSERT pozycji; centrala decyduje o migracji `MODIFY … NULL DEFAULT 0` w etapie A);
     `SELECT priority_manual_override, COUNT(*) FROM prod_products GROUP BY 1`;
     `SHOW CREATE TABLE prod_priority_config` (zapisz w notatkach — wzór dla skryptu cofającego) i `SELECT COUNT(*) FROM prod_priority_config`;
     `SELECT config_key FROM prod_config WHERE config_key LIKE '%PRIORITY%' OR config_key LIKE '%\_WEIGHT'` → lista martwych kluczy dla Taska 5 (bez `priorytety_*`);
     zależności DDL: `SELECT TABLE_NAME FROM information_schema.KEY_COLUMN_USAGE WHERE TABLE_SCHEMA = DATABASE() AND REFERENCED_TABLE_NAME = 'prod_priority_config'` oraz widoki i wyzwalacze z `priority_manual_override`/`prod_priority_config` w `VIEW_DEFINITION`/`ACTION_STATEMENT` (`information_schema.VIEWS`, `TRIGGERS`) — oczekiwane pusto; trafienie → STOP (DROP padłby albo unieważnił widok).
- [ ] **Step 1: Testy, które padną**
  `tests/test_priorytety_p4_sprzatanie.py` (fixture `krawedzie_fixtures.app`; testy na źródle jak `tests/krawedzie_fixtures.zrodlo`): `test_priority_service_nie_istnieje` (`importlib.util.find_spec('modules.production.services.priority_service') is None`), `test_nikt_nie_odwoluje_sie_do_priority_service` (grep po `modules/`, `app.py`, `scripts/` bez trafień `priority_service|NewPriorityCalculator|get_priority_calculator|nowa_sesja_priorytetow|PriorityError|def recalculate_priorities|\brecalculate_priorities\(` — **nie** gołego `recalculate_priorities`: to także nazwa parametru synchronizacji, który zostaje, `sync_service.py:1770`, `:1844`, `:2047`, `:2094`, `:2104`, `sync_api.py:62`, `:212`, `:221`, `:261`, `:317`, `:1078` — „Poza zakresem”), `test_services_bez_kalkulatora` (`NewPriorityCalculator`, `get_priority_calculator`, `recalculate_priorities` ani w `services.__all__`, ani jako atrybuty — nazwa w `__all__` bez atrybutu rozwala `from … import *`; `health_check()['services']` bez obu kluczy).
  `tests/test_sales_ingest_wyzwalacze.py` (tam są fixture `app`, `serwis_synchronizacji` i pomocnik `zamowienie()` — `krawedzie_fixtures.app` ich nie ma): `test_synchronizacja_wola_utrwal_wprost` (`monkeypatch.setattr(kolejka, 'utrwal', licznik)`; `serwis_synchronizacji.process_orders_with_priority_logic([zamowienie()], sync_type='manual', auto_status_change=False)` → licznik 1, `priority_recalc_triggered is True`), `test_aktualizacja_po_synchronizacji_wola_utrwal_wprost` (`serwis_synchronizacji._update_product_priorities()` → licznik 1, wyjątek atrapy nie wychodzi na zewnątrz). Dalej w tym pliku: atrapa `:525-535` → `monkeypatch.setattr(kolejka, 'utrwal', lambda **kw: {'success': True, 'zmienione_pozycje': 0})`; `_PriorytetyKtorePadajaBrudzac` → funkcja `_utrwal_ktore_brudzi(**kw)` (ta sama treść: brudzi `db.session`, zwraca `success False`), test `:1163-1185` podmienia `kolejka.utrwal`; usuń 11 testów z mapy, `_scena_priorytetow` i pomocniki używane tylko przez nie (`grep -n` przed usunięciem). Docstringi sekcji: odsyłacz do testów `kolejka.utrwal`.
  `tests/test_priorytety_kolejnosc_zapisow.py`: usuń `test_warstwa_zgodnosci_wola_utrwal`; dopisz `test_utrwal_kazde_wywolanie_na_nowej_sesji` i (jeśli brak) `test_utrwal_pusta_kolejka_to_sukces`.
  `tests/test_priorytety_kolejka.py`: przenieś `test_stale_statusy_produkcji_znaja_obie_kolejki`. `tests/test_krawedzie_model.py:199-207`: bez `NewPriorityCalculator` (reszta asercji bez zmian).
- [ ] **Step 2:** `PYTEST tests/test_priorytety_p4_sprzatanie.py tests/test_sales_ingest_wyzwalacze.py tests/test_priorytety_kolejnosc_zapisow.py` → FAIL (nowe testy).
- [ ] **Step 3: Implementacja** wg Interfaces; usuń `priority_service.py` (`git rm`) i `tests/test_priority_statusy_krawedzi.py` (po przeniesieniu testu stałych). W `services/__init__.py` usuń też zdanie docstringu `:11`. Docstring `kod_mysql`: „przeliczenie priorytetów (`priorytety.services.kolejka.utrwal`) i zapis gwiazdek oraz drabiny w panelu priorytetów”.
- [ ] **Step 4:** `PYTEST tests/test_priorytety_p4_sprzatanie.py tests/test_sales_ingest_wyzwalacze.py tests/test_priorytety_kolejnosc_zapisow.py tests/test_priorytety_kolejka.py tests/test_krawedzie_model.py tests/test_priorytety_wyzwalacze.py` → PASS.
- [ ] **Step 5: Commit** `refactor(priorytety): synchronizacja wola kolejka.utrwal wprost, usuniecie priority_service`

---

### Task 2: `priority_manual_override` i martwe metody

**Files:**
- Modify: `modules/production/models.py` (`ProductionProduct`: kolumna `:384`, `is_priority_locked` `:491-493`, `lock_priority` `:513-518`, `unlock_priority` `:520-521` — po K1 puste), `modules/production/priorytety/services/kolejka.py` (`utrwal`: warunek i przypisanie `priority_manual_override`; `_migawka`: odczyt kolumny; namedtuple `Pozycja` — pole `manual_override`, K1 Interfaces Task 2), `modules/production/routers/api/products_api.py` (`_serialize_product` `:178`)
- Modify: każde miejsce budujące `kolejka.Pozycja` (`grep -rn "Pozycja(\|manual_override" modules/production/priorytety tests` — co najmniej `tests/test_priorytety_kolejka.py`, pomocniki testów K3/K4a, jeśli budują `Pozycja` pozycyjnie)
- Modify: `scripts/create_split_tables.sql:93`, `scripts/migrate_prod_items_to_split_tables.py:122`, `:143`, `scripts/smoke_test_rework.py:203-207`
- Modify: `tests/test_priorytety_kolejnosc_zapisow.py`, `tests/test_priorytety_dorobka.py`, `tests/test_routing_krawedzie.py:256-278`, `tests/test_bootstrap_ddl_krawedzie.py`, `tests/test_priorytety_p4_sprzatanie.py`

**Interfaces:**
- `ProductionProduct` bez `priority_manual_override`, `is_priority_locked`, `lock_priority`, `unlock_priority`. `priority_rank` i `is_priority` bez zmian (pamięć podręczna, spec 4.1).
- `kolejka.utrwal()` — raport bez zmian kluczy; pozycja trafia do zapisu wyłącznie, gdy różni się `priority_rank` albo `is_priority`; `updated_at` podbijany tylko takim pozycjom (ETag czytelników, spec 4.2).
- `kolejka.Pozycja` bez pola `manual_override` (pozostałe pola i ich kolejność bez zmian); `_migawka` nie czyta kolumny — inaczej po usunięciu atrybutu z modelu `utrwal()` łapie `AttributeError` i po cichu zwraca `success False` przy każdym wywołaniu (nigdy nie rzuca). `policz()`, `kandydaci_stanowiska()` i `PozycjaStanowiska` bez zmian.
- `_serialize_product` bez klucza `priority_manual_override` (JS go nie czyta — K4a; grep w Step 0).

- [ ] **Step 1: Testy, które padną**
  `tests/test_priorytety_p4_sprzatanie.py`: `test_model_pozycji_nie_mapuje_priority_manual_override` (`'priority_manual_override' not in ProductionProduct.__table__.c`; brak atrybutów `is_priority_locked`, `lock_priority`, `unlock_priority`), `test_insert_i_select_pozycji_bez_priority_manual_override` (`blokady_pomocnicze.Zapytania`: utworzenie pozycji przez fixture, `commit`, `ProductionProduct.query.all()`, `kolejka.utrwal()` po commicie → `success is True` i żadne zapytanie nie zawiera `priority_manual_override`), `test_pozycja_migawki_bez_manual_override` (`'manual_override' not in kolejka.Pozycja._fields`), `test_kod_bez_priority_manual_override` (grep `modules/`, `app.py`, `scripts/`: zero trafień `priority_manual_override|is_priority_locked|lock_priority|unlock_priority`; `scripts/priorytety_p4_cofniecie.sql` wyłączony z grepu — powstaje w Tasku 5).
  `tests/test_priorytety_kolejnosc_zapisow.py`: `test_utrwal_zeruje_manual_override_i_podbija_updated_at` → `test_utrwal_podbija_updated_at_tylko_zmienionym` (pozycja z poprawną rangą zachowuje `updated_at`, pozycja ze zmienioną rangą dostaje nowy).
  `tests/test_priorytety_dorobka.py`: `…_bez_manual_override` → `test_dorobka_dostaje_range_0_i_is_priority` (bez asercji kolumny); usuń `test_lock_i_unlock_priority_nic_nie_robia`.
  `tests/test_routing_krawedzie.py:256-278`: bez przypisania i asercji `priority_manual_override` (reszta wg K1).
  `tests/test_bootstrap_ddl_krawedzie.py`: `test_bootstrap_bez_priority_manual_override` (brak w `create_split_tables.sql` i w obu listach skryptu); istniejący `test_liczba_kolumn_insertu_zgadza_sie_z_liczba_kolumn_selecta` pilnuje równoliczności.
- [ ] **Step 2:** testy z Step 1 → FAIL.
- [ ] **Step 3: Implementacja.** Usuń kolumnę i metody z modelu; z `utrwal` usuń warunek „albo override True” i przypisanie `priority_manual_override=False` (kolejność blokad bez zmian — sekcja „Współbieżność” p. 1), z `Pozycja` pole `manual_override`, z `_migawka` jego odczyt; konstruktory `Pozycja` w testach bez tego argumentu; `_serialize_product` bez klucza; bootstrap: usuń linię `:93` i parę `priority_manual_override`/`i.priority_manual_override` w `:122`/`:143`; `smoke_test_rework.py`: asercje stanu P1 (`priority_rank == 0`, `is_priority is True`, komentarz „doróbka ma rangę 0 od P1 priorytetów, spec 4.2”).
- [ ] **Step 4:** `PYTEST tests/test_priorytety_p4_sprzatanie.py tests/test_priorytety_kolejnosc_zapisow.py tests/test_priorytety_kolejka.py tests/test_priorytety_dorobka.py tests/test_routing_krawedzie.py tests/test_bootstrap_ddl_krawedzie.py tests/test_priorytety_lista_produkcyjna_ui.py` + pliki z grepu `Pozycja(` → PASS. Składnia `scripts/smoke_test_rework.py` pod 3.9 (skrypt ręczny — nie uruchamiaj na żadnej bazie poza kontenerem `db`).
- [ ] **Step 5: Commit** `refactor(priorytety): usuniecie priority_manual_override i martwych metod rangi z kodu`

---

### Task 3: `ProductionPriorityConfig`, `PriorityConfigCache`, martwe odczyty i `priority_range`

**Files:**
- Modify: `modules/production/models.py` (docstring `:9`, klasa `:732-757`), `modules/production/services/config_service.py` (`PriorityConfigCache` `:1022-1056`), `modules/production/__init__.py:56`, `modules/production/routers/api/__init__.py:13`, `:15`, `modules/production/routers/api/config_api.py` (`:14`, `:158` i resztki po K4b), `modules/production/routers/main_routers.py` (`config_panel` `:228`, `:247-255`), `modules/production/routers/api/products_api.py` (`get_filters_data` `:2478-2490`, `:2506`)
- Modify: `tests/test_priorytety_p4_sprzatanie.py`

**Interfaces:**
- `modules.production.models` bez `ProductionPriorityConfig`; `db.metadata.tables` bez `prod_priority_config` (`flask setup-db` jej nie założy).
- `config_service` bez `PriorityConfigCache`. `REFRESH_INTERVAL_SECONDS` zostaje (Doprecyzowania 2).
- `GET /production/api/products/filters-data` bez klucza `priority_range`; pozostałe klucze bez zmian.
- `config_panel` renderuje bez `priority_configs` (stan trasy poza tym bez zmian — Doprecyzowania 7).

- [ ] **Step 1: Testy, które padną** (`tests/test_priorytety_p4_sprzatanie.py`): `test_model_konfiguracji_priorytetow_usuniety` (brak atrybutu w `models`, `'prod_priority_config' not in db.metadata.tables`), `test_kod_bez_prod_priority_config` (grep `modules/`, `app.py`, `scripts/` — zero `ProductionPriorityConfig|PriorityConfigCache|prod_priority_config|priority_configs`; skrypt cofający wyłączony), `test_pakiet_produkcji_ma_modele_i_serwisy` (`import modules.production as p`: `p.ProductionItem`, `p.ProductionSyncLog`, `p.ProductionConfig`, `p.ProductionDevice`, `p.ProcessedMobileOperation`, `p.BaselinkerSyncService` istnieją — `try/except ImportError` w `__init__` nie może ich po cichu zgubić), `test_filters_data_bez_priority_range` (klient zalogowanego admina — wzór logowania z testów K2/K4a dla `/production/api/*` albo `_zaloguj` z `tests/test_druk_wydruk_probny.py:50`; 200, brak klucza, `statuses` jest), `test_config_panel_nie_czyta_konfiguracji_priorytetow` (na źródle funkcji `config_panel`), `test_kod_bez_martwych_kluczy` (grep `modules/`, `app.py` w `.py`/`.js`/`.html` — zero kluczy z listy Taska 1 Step 0, w tym `PRIORITY_RECALC_INTERVAL_HOURS`, `PRIORITY_ALGORITHM_VERSION`, `_PRIORITY_SORT`, `*_WEIGHT`; K4b miał je zdjąć z UI, allowlisty, JS i `config_service._default_values` — jeśli którykolwiek zostaje, `reset-configs` albo „Zapisz zmiany” w Konfiguracji założy wiersz od nowa po `DELETE` z Taska 5; trafienie = brak po K4b, usuń w tym Tasku i odnotuj w „Odstępstwach”).
- [ ] **Step 2:** → FAIL.
- [ ] **Step 3: Implementacja.** Kolejność: najpierw usuń importy (`modules/production/__init__.py:56`, `routers/api/__init__.py:13,15`, `config_api.py:14/:158`, `main_routers.py:228`), potem klasę — inaczej `ImportError` w `try` zgubi resztę modeli (Review Focus 6). `PriorityConfigCache` i jego docstring. `priority_range` z zapytaniem `:2478-2490`.
- [ ] **Step 4:** `PYTEST tests/test_priorytety_p4_sprzatanie.py tests/test_priorytety_czytelnicy.py tests/test_krawedzie_model.py tests/test_config_service_set.py` → PASS; `grep -rn "priority_range" modules` → pusto.
- [ ] **Step 5: Commit** `refactor(priorytety): usuniecie modelu konfiguracji priorytetow i martwych odczytow`

---

### Task 4 (warunkowy, W-3): lista i delta tabletu, `refresh_interval_seconds`

**Bez W-3 w karcie:** nie wykonuj; w raporcie „Task 4 pominięty — brak potwierdzenia wycofania starej appki”, centrala wyda go później jako kartę K8-b na tym samym planie.

**Files:**
- Modify: `modules/production/routers/mobile_api.py` (importy `:38`, `:41`; `KSZTALT_ODPOWIEDZI_KOLEJKI` `:137` z historią podbić; komentarz nad `KSZTALT_KATALOGU_PRACOWNIKOW` `:139` („jak `KSZTALT_ODPOWIEDZI_KOLEJKI`” → „jak `KSZTALT_ODPOWIEDZI_STOLU`”); wzmianka o `parse_since_ts` w docstringu `:1468`; `station_orders` `:242-326`; segment konfiguracji ETagu `station_summary` `:672-678`; `station_orders_since` `:699-747`), `modules/production/services/mobile_api_service.py` (`compute_station_summary` `:1643-1653`, `:1666`; `parse_since_ts` `:1675-1700`; `get_station_queue_delta` `:1752-1799`; docstring `parse_client_local_ts` `:1708-1710` porównuje się z `parse_since_ts` — przeredagować bez odwołania do usuniętej funkcji), `modules/production/logistics/routers/weryfikacja_api.py:33` (komentarz), `docs/api-mobile-priorytety.md` (nowa sekcja na górze „Zmiany po K8”)
- Modify: `tests/test_paczki_podpowiedz.py:62-110`, `tests/test_weryfikacja_problem.py:205-215`, `tests/test_logistyka_mobile.py:49` (asercja `KSZTALT_ODPOWIEDZI_KOLEJKI == 5`) i `:123-141`, `tests/test_mobile_api_alias_krawedzi.py:577-630`, `:715-725`, testy listy i delty z K3 (grep `stations/.*/orders|orders/since|KSZTALT_ODPOWIEDZI_KOLEJKI|get_station_queue_delta` w `tests/`), `tests/test_priorytety_p4_sprzatanie.py`

**Interfaces:**
- Znikają: `GET /api/mobile/stations/<kod>/orders`, `GET /api/mobile/stations/<kod>/orders/since`, `get_station_queue_delta`, `parse_since_ts` (jeśli Step 0 potwierdzi jedynego wołającego), `KSZTALT_ODPOWIEDZI_KOLEJKI`, pole `refresh_interval_seconds` w `GET /summary`.
- Zostają bez zmian (spec 6.1–6.3): `GET …/desk` (K3, `KSZTALT_ODPOWIEDZI_STOLU`), `POST …/postpone`, `GET /api/mobile/realtime-token`, `GET /orders/search`, `GET /orders/<id>`, `complete`, `quantity`, `reject`, `summary` (pozostałe pola), tryby `stary`/`stol` i próg wersji (dźwignia wycofania P3), `serialize_order` z `priority_rank`/`is_priority`/`priorytet`.

- [ ] **Step 0: Kontrakt appki.** W `docs/api-mobile-priorytety.md` (K6) sprawdź, czy nowa appka czyta `refresh_interval_seconds` albo woła `/orders`, `/orders/since` poza awaryjnym powrotem na backend bez `/desk` (Doprecyzowania K6 p. 3). Kontrakt mówi, że czyta, albo milczy → **STOP Taska 4**, meldunek (pytanie do sesji appki przez centralę).
- [ ] **Step 1: Testy, które padną.** Przepnij na `GET /api/mobile/stations/packaging/desk` (jednostka `zamowienie`: kafle-pozycje w `pozycje[]`): `test_desk_pakowania_niesie_podpowiedz_calego_zamowienia`, `test_desk_pakowania_nie_laduje_pozycji_zamowien_osobnymi_zapytaniami` (limit zapytań wg pomiaru na `desk` — w raporcie liczba przed/po), `test_desk_baner_weryfikacji_i_repack_reason` (z `test_weryfikacja_problem.py`), `test_desk_etag_zmienia_sie_po_zmianie_sposobu` (z `test_logistyka_mobile.py`); usuń testy aliasu `finishing` dla `/orders` i `/orders/since` (alias `/summary` zostaje) i testy `KSZTALT_ODPOWIEDZI_KOLEJKI`. Nowe w `test_priorytety_p4_sprzatanie.py`: `test_lista_i_delta_tabletu_usuniete` (`app.url_map` bez obu reguł; `desk`, `summary`, `search` są), `test_summary_bez_refresh_interval_seconds`.
- [ ] **Step 2:** → FAIL. **Jeśli któryś przepięty test pada, bo `desk` nie ma właściwości listy** (np. ETag `desk` nie zmienia się po zmianie sposobu dostawy kafla leżącego na stole) → **STOP Taska 4**: nie usuwaj listy, cofnij zmiany Taska 4 (`git checkout -- .`), meldunek do centrali z nazwą testu (karta K3-poprawka).
- [ ] **Step 3: Implementacja** wg Interfaces. Grep `parse_since_ts` przed usunięciem (jedyny wołający `mobile_api.py:731`). W kontrakcie appki sekcja „Zmiany po K8 (data, hash)”: lista usuniętych końcówek i pola, zdanie „nowa appka na backendzie bez `/desk` nie ma już do czego wracać — backend bez `/desk` nie istnieje od P1”.
- [ ] **Step 4:** `PYTEST tests/test_paczki_podpowiedz.py tests/test_weryfikacja_problem.py tests/test_logistyka_mobile.py tests/test_mobile_api_alias_krawedzi.py tests/test_priorytety_stol.py tests/test_priorytety_p4_sprzatanie.py` → PASS.
- [ ] **Step 5: Commit** `refactor(priorytety): usuniecie listy i delty kolejki tabletu po wycofaniu starej appki`

---

### Task 5: Migracja P4 (etap B) i skrypt cofający

**Files:**
- Create: `migrations/RRRR-MM-DD-priorytety-p4-sprzatanie.sql`, `scripts/priorytety_p4_cofniecie.sql`, `tests/test_migracja_priorytety_p4.py`

**Interfaces:**
- Migracja (szkic; lista kluczy z Task 1 Step 0):
  ```sql
  -- Priorytety produkcji, krok K8 (P4): sprzątanie po starym systemie. Wdrażana jako ETAP B, po kodzie
  -- bez odwołań (etap A). Idempotentna. Cofnięcie: scripts/priorytety_p4_cofniecie.sql (przed restartem).
  SET SESSION lock_wait_timeout = 30;
  SET @jest = (SELECT COUNT(*) > 0 FROM information_schema.COLUMNS
               WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'prod_products'
                 AND COLUMN_NAME = 'priority_manual_override');
  SET @sql = IF(@jest, 'ALTER TABLE prod_products DROP COLUMN priority_manual_override',
                'SELECT ''priority_manual_override juz usunieta'' AS info');
  PREPARE krok FROM @sql; EXECUTE krok; DEALLOCATE PREPARE krok;
  DROP TABLE IF EXISTS prod_priority_config;
  DELETE FROM prod_config WHERE config_key IN ('PRIORITY_RECALC_INTERVAL_HOURS', 'PRIORITY_ALGORITHM_VERSION',
      'STATION_CUTTING_PRIORITY_SORT', 'STATION_ASSEMBLY_PRIORITY_SORT', 'STATION_PACKAGING_PRIORITY_SORT' /*, …z kopii */);
  SET SESSION lock_wait_timeout = DEFAULT;
  ```
  Indeks na kolumnie (`ix_prod_products_priority_manual_override`, jeśli istnieje) MySQL usuwa razem z kolumną.
- Skrypt cofający (poza runnerem; kształt z `SHOW CREATE TABLE` z Task 1 Step 0, kolumny zgodne z dawnym modelem: `id`, `config_name VARCHAR(100) NOT NULL`, `criteria_json JSON NOT NULL`, `weight_percentage INT NOT NULL`, `is_active`, `display_order` z indeksami, `created_at`, `updated_at`): `ADD COLUMN priority_manual_override TINYINT(1) NULL DEFAULT 0` osłonięty `information_schema`, indeks osłonięty `information_schema.STATISTICS`, `CREATE TABLE IF NOT EXISTS prod_priority_config (…) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci`. Nagłówek: kiedy i jak użyć (Doprecyzowania 3, sekcja „Okno wdrożenia”).

- [ ] **Step 1: Testy, które padną** (`tests/test_migracja_priorytety_p4.py`, wzór `tests/test_migracja_krawedzie.py`, tylko treść plików): `test_plik_istnieje_i_runner_go_widzi` (`MigrationService(db=None)._match`), `test_sortuje_sie_po_migracji_p1` (`> '2026-10-05-priorytety-produkcji.sql'`), `test_nie_uzywa_zmiany_separatora_polecen`, `test_drop_kolumny_osloniety_information_schema` (każde `DROP COLUMN` wyłącznie w literale `IF(…)` po `information_schema.COLUMNS`), `test_drop_tabeli_if_exists`, `test_delete_martwych_kluczy_jawna_lista` (zbiór kluczy == lista z raportu Step 0; brak `LIKE`), `test_delete_nie_dotyka_wierszy_blokad_ani_kluczy_zywych` (brak `REFRESH_INTERVAL_SECONDS`, `priorytety_`, `DEADLINE_`, `logistyka_`), `test_lock_wait_timeout_przed_alter` (pierwsze polecenie z `split_statements`), `test_liczba_polecen` (stała z implementacji), `test_cofniecie_poza_runnerem_i_idempotentne` (plik w `scripts/`, brak takiej treści w `migrations/`; `ADD COLUMN` osłonięty; `CREATE TABLE IF NOT EXISTS prod_priority_config`), `test_cofniecie_odtwarza_kolumne_i_tabele_idempotentnie` (kolumny tabeli i definicja kolumny zgodne z listą wyżej; `NULL DEFAULT 0`).
- [ ] **Step 2:** → FAIL. **Step 3:** pliki wg Interfaces. **Step 4:** `PYTEST tests/test_migracja_priorytety_p4.py tests/test_migration_service.py` → PASS.
- [ ] **Step 5: MySQL na kontenerze `db`.** `flask migrate` → wykonana; drugi raz → nic do zrobienia; `flask migrate-status`. Po: `SHOW COLUMNS FROM prod_products LIKE 'priority_manual_override'` → pusto, `SHOW TABLES LIKE 'prod_priority_config'` → pusto, martwe klucze → 0, wiersze `priorytety_*` i `logistyka_*_blokada` bez zmian (liczby przed/po). Cofnięcie: `docker compose exec -T db mysql … < scripts/priorytety_p4_cofniecie.sql` ×2 → kolumna i tabela są; potem migracja ręcznie `mysql … < migrations/…-priorytety-p4-sprzatanie.sql` ×2 (runner pamięta plik) → stan K8. Wyniki i czasy do raportu.
- [ ] **Step 6: Commit** `feat(priorytety): migracja P4 usuwa martwa kolumne, tabele i klucze priorytetow` — **jedyny commit kroku z plikiem w `migrations/`** (`git show --stat HEAD` do raportu).

---

### Task 6: Kopia produkcji (A, B, cofnięcie), CLAUDE.md, spec 16, pełny pakiet

**Files:**
- Modify: `CLAUDE.md` (sekcja `### Priorytety produkcji` z K5 i wszystkie trafienia z grepu Step 0 Taska 1), `tests/test_priorytety_dokumentacja.py` (K5), `docs/superpowers/specs/2026-10-04-priorytety-produkcji-design.md` (sekcja 16 z K5 + odesłania w 6, 8.1, 8.6, 8.8, 9.3, 10, 11, 12, 13, 14, 15)
- Read: plany K6, K7 (sekcje „Doprecyzowania”), raporty K6, K7 („Odstępstwa”, „Rozstrzygnięcia”, „Co następny krok musi wiedzieć”), raport K2/K5 (stan `test_ustawienia_czytane_bez_pamieci_podrecznej_procesu`: zielony albo `xfail`), dziennik centrali (czy karta dokumentacyjna nie naniosła już części — wtedy uzupełniasz tylko brakujące)

Steps 1–2b nie zależą od W-4/W-5 — wykonaj je także, gdy Step 3 stoi.

- [ ] **Step 1: Testy, które padną** (`tests/test_priorytety_dokumentacja.py`): `test_claude_md_po_p4` (w CLAUDE.md brak `priority_service`, `warstwa zgodności`, `priority_manual_override`, `prod_priority_config`; jest zdanie o dwuetapowym wdrożeniu P4 — etap A kod, etap B DROP po `Deploy complete!` — i `scripts/priorytety_p4_cofniecie.sql`; jest `999999` przy `priorytety_min_app_version_code`; gdy raport K2/K5 mówi `xfail` pamięci podręcznej — jest zdanie „zmiana trybu, progu wersji, K i limitu = zapis i restart razem”, a gdy zielony — tego zdania nie ma); `test_spec_ma_grupy_k6_k7_k8` (sekcja 16 specu zawiera grupy „K6”, „K7”, „K8” po grupach K1–K5; w 8.6 przy „0” stoi odesłanie do 16, a w 8.8/14 przy `REFRESH_INTERVAL_SECONDS` — „(K8) zostaje dla monitorów”; w 9.3 nie ma „warstwę zgodności `priority_service`”). Testy K5 w tym pliku (m.in. `test_spec_ma_sekcje_16_i_prog_3`) zostają zielone — nagłówek `## 16. Doprecyzowania z realizacji` zachowuje prefiks.
- [ ] **Step 2: CLAUDE.md.** W `### Priorytety produkcji`: „`priority_service.py` to warstwa zgodności do P4” → „starego systemu (`priority_service.py`, ręczne nadpisania rangi, `prod_priority_config`) nie ma od P4”; jedno zdanie w „Ważne”: wycofanie P4 = kod P1 + skrypt cofający skopiowany do `migrations/` pod nową nazwą, wykonany przed restartem; ponowny DROP pod nową nazwą; wdrożenie P4 dwuetapowe (etap A kod bez odwołań, etap B migracja DROP po `Deploy complete!` etapu A, każdy etap osobnym merge commitem). Do zdania K5 o `priorytety_min_app_version_code` („0 = brak bramki wersji”) dopisz: 0 to bramka stołu dla **każdego** tabletu, a wyłączenie bramki dla wszystkich naraz = próg `999999` (większy niż każdy `version_code`), nie 0 (K7 Doprecyzowanie 1). Zdanie o restarcie wg raportu K2/K5: przy `xfail` pamięci podręcznej (`config_service`, 60 min na proces) każda zmiana trybu, progu wersji, K i limitu w Konfiguracji idzie razem z `crm-fix-logs-perms.sh` i `supervisorctl restart crm_woodpower`, także wycofanie P3 (K7 Doprecyzowanie 2); przy zielonym — nic nie dopisuj. Bez numerów linii.
- [ ] **Step 2b: Spec, sekcja 16.** Nagłówek K5 `## 16. Doprecyzowania z realizacji (K1–K5)` → `(K1–K8)`. Po grupie K5 dopisz grupy „K6” (Doprecyzowania K6 p. 1–11, adresat: sekcje 6, 10, 12), „K7” (K7 p. 1–11: 8.1, 8.6, 11, 13) i „K8” (Doprecyzowania tego planu p. 1–8: 8.8, 11, 14) — przepisane z planów i skorygowane o „Odstępstwa”/„Rozstrzygnięcia” raportów K6, K7 i Tasków 1–5 tego kroku (to, co faktycznie w kodzie i na produkcji, nie to, co planowano). Odesłania „(K6)/(K7)/(K8) patrz 16” w miejscach, którym doprecyzowanie przeczy: 8.6 „0 = brak bramki” → brak bramki **wersji**, wyłączenie dla wszystkich = `999999`; 8.1 „pamięć podręczna” → unikatowość rang tylko wśród aktywnych (K7 p. 11); 11 „bez zmiany kodu” przy wycofaniu P3 → restart wg pamięci podręcznej (K7 p. 2), P4 dwuetapowe i skrypt cofający (K8 p. 1, 3); 8.8 i 14 `REFRESH_INTERVAL_SECONDS` → zostaje dla monitorów, z tabletów znika tylko pole (K8 p. 2); 9.3 „(K1) przez warstwę zgodności `priority_service` do P4” → „(K8) `kolejka.utrwal()` wprost”; 15 „Usunięte (P4)” → stan faktyczny (Task 4 wykonany albo pominięty). Jeśli dziennik centrali mówi, że karta dokumentacyjna już część naniosła — sprawdź zgodność i dopisz tylko brakujące (do raportu: co było, co dopisane).
- [ ] **Step 3: Kopia produkcji** (podgląd wg karty; w raporcie czasy i kody odpowiedzi, bez danych klientów). Smoke = `GET` zakładki Lista produkcyjna (dane), `GET /production/api/priorytety/kolejka`, `GET /production/api/config-tab-content`, `GET /production/api/products/filters-data`, `GET /api/mobile/stations/gluing/desk` z tokenem urządzenia podglądu, `POST /production/api/logistics/cron` (`priorytety_utrwalone.success: true`), INSERT pozycji przez ORM (krótki skrypt w kontenerze podglądu: zamówienie testowe z jedną pozycją → commit → usunięcie).
  a) **Etap A z kolumną:** `git checkout <hash ostatniego commitu Tasków 1–4>` w katalogu podglądu → start → `flask migrate` (nic nowego) → smoke → wszystko 200, INSERT bez błędu 1364.
  b) **Etap B:** `git checkout <hash Taska 5>` → `flask migrate` ×2 (czas pierwszego) → zapytania jak w Task 5 Step 5 → smoke → 200. `docker exec <podgląd> python scripts/symulacja_priorytetow.py --db-url "<URI kopii>" --blisko 3 --k 2 --top 50 --out /tmp/k8-sym.md` → kończy się bez błędu.
  c) **Cofnięcie:** `mysql … < scripts/priorytety_p4_cofniecie.sql` → `git checkout <hash W-5>` → start → smoke → 200 (kod P1 na odtworzonym schemacie). Potem `git checkout` HEAD gałęzi i ręczny DROP jak w Task 5 Step 5.
  Którykolwiek punkt z 500 → STOP, meldunek z logiem (bez danych klientów).
- [ ] **Step 4: Pełny pakiet** `PYTEST tests/` → 0 failed; passed = punkt wyjścia − usunięte + nowe (lista nazw w raporcie). `blog_seo` zielony. Składnia 3.9 dla zmienionych `.py` (`git diff --name-only <hash startu>..HEAD -- '*.py'`, `ast.parse(..., feature_version=(3,9))` jak w K2 Task 7 Step 2). Grep z DoD 1 → pusto.
- [ ] **Step 5: Commit** `docs(priorytety): CLAUDE.md i spec po sprzataniu P4` (`git add CLAUDE.md tests/test_priorytety_dokumentacja.py && git add -f docs/superpowers/specs/2026-10-04-priorytety-produkcji-design.md`)

---

### Task 7: Raport kroku

**Files:**
- Create: `docs/superpowers/plans/raporty/2026-10-05-priorytety-krok-K8-raport.md`
- Modify: ten plan (odhaczone checkboxy)

- [ ] **Step 1: Raport** z sekcjami: **Zrobione** (po Taskach, hashe; Task 4 wykonany albo pominięty z powodem), **Testy** (polecenia i wyniki: punkt wyjścia i pełny pakiet po, `blog_seo`, składnia 3.9, migracja ×2 na `db` i kopii z czasami, zapytania przed/po, smoke A/B/cofnięcie, symulacja), **Odstępstwa od planu**, **Rozstrzygnięcia podjęte w trakcie** (numerowane; koszt, jeśli błędne — co najmniej: lista martwych kluczy z kopii, kształt kolumny na produkcji, równoważniki usuniętych testów), **Pytania do Konrada**, **Stan gałęzi** (hash, czy wypchnięte), **Wdrożenie** (hash końca etapu A, hash etapu B, pełna treść migracji DROP i skryptu cofającego — wymóg karty 8.9), **Co następny krok musi wiedzieć**: centrala/Konrad — kolejność wdrożenia A → `Deploy complete!` → dzień pracy → B poza zmianą, procedura wycofania A i B; centrala — Doprecyzowania K6, K7, K8 są w spec 16 i CLAUDE.md (Task 6 Step 2b; lista dopisanych grup i punktów), kartą dokumentacyjną idą tylko rozstrzygnięcia K8 powstałe po Task 6; Task 4, jeśli pominięty — karta K8-b; „Poza zakresem” z listą znalezisk.
- [ ] **Step 2: Commit i push** wg karty: `git add -f docs/superpowers/plans/raporty/2026-10-05-priorytety-krok-K8-raport.md docs/superpowers/plans/2026-10-05-priorytety-krok-K8-sprzatanie-p4.md`, `docs(priorytety): raport kroku K8 sprzatanie P4`.

---

## Kryteria zakończenia (DoD)

1. `grep -rn --include=*.py --include=*.js --include=*.html -E "priority_service|NewPriorityCalculator|get_priority_calculator|priority_manual_override|is_priority_locked|lock_priority|unlock_priority|ProductionPriorityConfig|PriorityConfigCache|prod_priority_config|priority_range|PRIORITY_RECALC_INTERVAL_HOURS|PRIORITY_ALGORITHM_VERSION|_PRIORITY_SORT" modules app.py scripts` → pusto (klucze `*_WEIGHT` z listy Taska 1 Step 0 tak samo — `test_kod_bez_martwych_kluczy`); trafienia `.sql` wyłącznie w migracji P4 i w `scripts/priorytety_p4_cofniecie.sql`.
2. Nie istnieją: `modules/production/services/priority_service.py`, `tests/test_priority_statusy_krawedzi.py`. Każdy usunięty test ma wiersz w mapie Taska 1 (albo w Tasku 4) z równoważnikiem albo „bez przedmiotu” z powodem.
3. Migracja: runner ją widzi; `flask migrate` ×2 na `db` i na kopii — drugi przebieg bez zmian; po migracji brak kolumny, tabeli i martwych kluczy; `REFRESH_INTERVAL_SECONDS`, `priorytety_*`, wiersze blokad bez zmian (liczby przed/po w raporcie).
4. Kopia: smoke etapu A z kolumną, etapu B po DROP i kodu P1 po cofnięciu — same 200; INSERT pozycji bez 1364; symulacja kończy się bez błędu.
5. `tests/test_priorytety_p4_sprzatanie.py`, `tests/test_migracja_priorytety_p4.py` i wszystkie testy z Review Focus istnieją pod podanymi nazwami i przechodzą (Task 4 — gdy wykonany).
6. Pełny pakiet: 0 failed; passed = punkt wyjścia − usunięte + nowe (nazwy w raporcie); `blog_seo` zielony; składnia 3.9 OK.
7. `git log --oneline` gałęzi: commit scalenia `origin/main` na starcie (wnosi tylko to, co już jest na `main`), commity Tasków 1–4 bez plików w `migrations/` (`git show --stat` każdego), commit Taska 5 jedyny z plikiem migracji, dalej tylko dokumentacja. Hashe końca A i B w raporcie. `main` nietknięty.
8. Task 4 wykonany z dowodem W-3 albo pominięty z adnotacją; gdy wykonany: `app.url_map` bez listy i delty, `/summary` bez `refresh_interval_seconds`, kontrakt appki ma sekcję „Zmiany po K8”.
9. Raport kroku zacommitowany z wszystkimi sekcjami, w tym „Wdrożenie” z treścią obu skryptów SQL.
10. Spec 16 ma grupy K6, K7, K8 i odesłania z Taska 6 Step 2b; CLAUDE.md ma próg `999999`, zdanie o restarcie zgodne ze stanem pamięci podręcznej z raportu K2/K5 i dwuetapowe P4; `test_spec_ma_grupy_k6_k7_k8` i `test_claude_md_po_p4` zielone.

## Poza zakresem

- Nowe funkcje; zmiany algorytmu, stołu, sygnałów, panelu, trybów `stary`/`stol` i progu wersji (dźwignia wycofania P3 zostaje).
- `prod_products.priority_rank`/`is_priority` — pamięć podręczna czytelników SQL (spec 4.1), zostaje.
- Kolumny historii synchronizacji `prod_sync_logs.manual_overrides_preserved`, `priority_recalc_triggered`, `priority_recalc_duration_seconds`, parametr `respect_manual_overrides` w `sync_api.py:212-263`/`sync_service.py:1772-2096` (martwy, nieszkodliwy) — do raportu; wartość `'00:00:00'` w `priority_recalc_duration` (`sync_service.py:1000`) dla kolumny INT — istniejąca, do raportu.
- `priority_change` w ENUM `prod_product_events.event_type` (historia audytu).
- Zgłoszone przez K4b/K5 do K8, ale nie należące do listy P4: `avg_priority` w `/dashboard-stats`, progi rangi w `admin_routers.py:138-144` (`priority_rank <= 10`), `reset-configs` bez `admin_required`, `MIGRATION_PLAN.md` nieobecny w repo, `order_quantity` jako pisarz bez blokady, `reject_product_quantity` commitujący w handlerze, trasa `config_panel` renderująca nieistniejący szablon — do raportu, centrala decyduje o kartach.
- Klucz `REFRESH_INTERVAL_SECONDS` i jego karta w Konfiguracji (monitory hali — Doprecyzowania 2). `scripts/symulacja_priorytetow.py` bez zmian. `tools/print_agent` bez zmian.
- Wdrożenie A i B na produkcję (centrala z Konradem wg sekcji „Wdrożenie” raportu).

## Pytania do Konrada

**Blokujące start (centrala zbiera przed kartą):**
1. **Czy stara appka jest zdjęta ze wszystkich tabletów** — z dowodem W-3 (wersje aktywnych urządzeń ≥ próg i 0 żądań list `/orders` w logu nginx z 7 dni)? Rekomendacja: Task 4 tylko z tym dowodem; bez niego K8 idzie bez Taska 4, a lista i `refresh_interval_seconds` zostają do karty K8-b.
2. **Świeży zrzut produkcji po P3 (W-4) i hash kodu z serwera (W-5)** — bez nich nie ma dowodu, że etap A działa na prawdziwym kształcie kolumny ani że cofnięcie stawia kod P1. Rekomendacja: zrzut z dnia wydania karty, `mysqldump --single-transaction` bez tabel sesji, poza repo.

**Do potwierdzenia przy bramce (plan przyjmuje rekomendację):** `REFRESH_INTERVAL_SECONDS` zostaje dla monitorów (Doprecyzowania 2); etap B wdrażany poza zmianą, dzień po etapie A.

## Ryzyka i co robić przy blokadzie

| Ryzyko | Objaw | Co robić |
|---|---|---|
| Etap A i B wdrożone jednym pushem | 1054 „Unknown column” / 500 na tabletach i w panelu od migracji do restartu (do ~5 min) | w raporcie i CLAUDE.md wymóg dwóch pushów z hashami; gdyby się stało — nie cofać w panice: deploy skończy się restartem i kod B pasuje do schematu; tablety mają kolejkę offline |
| Kolumna na produkcji `NOT NULL` bez `DEFAULT` | INSERT pozycji po etapie A: MySQL 1364 (import z Base., doróbka) | wykrywa Task 1 Step 0 na kopii → **STOP**, meldunek; centrala decyduje o migracji `MODIFY … NULL DEFAULT 0` w etapie A (karta K8-poprawka) |
| `DROP COLUMN` czeka na blokadę metadanych za długą transakcją | zapytania do `prod_products` stoją w kolejce za `ALTER` | `lock_wait_timeout = 30` w migracji → po 30 s migracja pada, `deploy.sh` przerywa przed restartem i cofa kod; ponowić B poza zmianą |
| `try/except ImportError` w `modules/production/__init__.py` i `services/__init__.py` po cichu gubi modele/serwisy | `None` zamiast `BaselinkerSyncService`, brak modeli w pakiecie, błędy dopiero na produkcji | `test_pakiet_produkcji_ma_modele_i_serwisy`, `test_import_katalogu_w_modelu_nie_rozwala_serwisow`; importy usuwać przed klasami (Task 3 Step 3) |
| Nazwy testów lub funkcji K1–K7 inne niż w planach | mapa równoważników nie pasuje | szukaj po treści (`grep -n`); brak równoważnika → dopisz w Tasku 1, odnotuj w „Odstępstwach”; brak funkcji, na którą plan liczy (np. `kolejka.utrwal`) → **STOP** |
| `desk` nie przenosi właściwości listy (ETag po zmianie sposobu dostawy, podpowiedź paczek, baner Weryfikacji) | przepięty test pada | **STOP Taska 4** (Step 2), lista zostaje, karta K3-poprawka; reszta kroku idzie |
| Nowa appka czyta `refresh_interval_seconds` albo woła `/orders` | kontrakt K6 tak mówi albo milczy | **STOP Taska 4**, pytanie do sesji appki przez centralę |
| Scalenie `origin/main` na starcie nie jest czyste (poprawki na `main` po K7 w tych samych plikach) | konflikt przy `git merge origin/main` | `git merge --abort`, **STOP**, karta „scalenie” (podręcznik 2 p. 2) |
| Brak kopii (W-4) lub hasha (W-5) | Task 6 Step 3 niewykonalny | Taski 1–5 wykonaj; Task 6 Step 3 **STOP**, krok niezakończony (DoD 4) |
| Wycofanie po etapie B, potem ponowne wdrożenie K8 | runner nie wykona drugi raz pliku o tej samej nazwie | w raporcie: ponowny DROP = nowa migracja pod nową nazwą |
| Test spoza zakresu pada po usunięciach | np. test innego modułu używa `lock_priority` albo `priority_manual_override` w fixturze | konsekwencja decyzji specu (test czyta martwy obiekt) → uaktualnij i wymień w raporcie; regresja zachowania → **STOP** |

**STOP** = zatrzymanie pracy (albo danego Taska, gdy tak napisano), opis w raporcie („Odstępstwa”/„Pytania”), bez wyłączania testów i bez obejść, meldunek do centrali.

## Wdrożenie (informacyjnie — prowadzi centrala z Konradem)

1. Etap A: PR gałęzi pomocniczej `claude/priorytety-p4-etap-a` (= `<hash A>`, koniec Tasków 1–4) → `main` z merge commitem (sekcja „Okno wdrożenia”; hash merge A do dziennika). Czekać na `Deploy complete!` w `logs/deploy.log`. Dzień pracy hali bez 500 (Sentry, log gunicorna).
2. Etap B: PR `claude/priorytety-produkcji` → `main` z merge commitem (hash merge B do dziennika), najlepiej po zmianie. Po deployu: `flask migrate-status` (plik P4 wykonany), `SHOW COLUMNS FROM prod_products LIKE 'priority_manual_override'` → pusto, tablety i panel działają.
3. Wycofanie — sekcja „Okno wdrożenia”. Po etapie B tylko z `scripts/priorytety_p4_cofniecie.sql` skopiowanym do `migrations/` w commicie wycofującym.
