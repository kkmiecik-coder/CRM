# Priorytety produkcji, krok K7 — „wdrożenie i przełączenie” — runbook

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** P1 (kod K1–K4b, zaliczony przez K5) działa na produkcji: rangi liczone nowym algorytmem, drabina z 9 szczeblami
stałymi i szczeblem każdej trasy roboczej/zatwierdzonej, Lista produkcyjna po randze, stara appka pracuje bez zmian,
sygnały `station:<kod>` przechodzą przez Centrifugo. Potem P3: po wydaniu appki z K6 próg wersji i przełączanie stanowisk
na `stol` jedno po drugim z obserwacją, pomiar skryptem symulacji po 2 tygodniach i gotowe procedury wycofania.
**To runbook, nie plan kodowania** — żadnej zmiany w kodzie, testach, migracjach ani konfiguracji repo.

**Architecture:** Dwie części rozłożone w czasie. **Część 1 (P1):** warunki wejścia → scalenie `main` → gałąź robocza
i testy → próba generalna na świeżej kopii produkcji (migracja ×2, cron, czas `utrwal()`) → przegląd serwera (Centrifugo
namespace `station`, `REALTIME`, crontab logistyki, kopia bazy) → scalenie do `main` na polecenie Konrada → obserwacja
`deploy.sh` (`logs/deploy.log`, `flask migrate` PRZED restartem) → ręczny cron logistyki (faza `priorytety_utrwalone`,
szczeble tras) → weryfikacja i 1–2 dni obserwacji. **Część 2 (P3):** wydanie APK → heartbeat nowej wersji na wszystkich
tabletach → `priorytety_min_app_version_code` → `priorytety_tryb_<S>=stol` kolejno: Sklejanie, Formatowanie, Składanie,
Wycinanie, Krawędzie, Pakowanie (po 2 dni; Lakiernia zostaje na stałe w `stary` z listą po wykończeniu — spec ustalenie
15) → pomiar po 2 tygodniach. Wycofania (tryb, próg wersji, revert P1)
opisane jako procedury z warunkami uruchomienia. Każdy punkt odhacza centrala w dzienniku z datą.

**Tech Stack:** webhook GitHub → `deploy.sh` (lock, `git reset --hard origin/main`, `flask migrate` przed restartem,
`supervisorctl restart crm_woodpower`), gunicorn pod supervisorem, MySQL 8.4 (produkcja, REPEATABLE READ), Centrifugo
v6.9.1 (`uni_sse`, namespace `station`), `scripts/cron_endpoint.sh`, `scripts/symulacja_priorytetow.py`, Docker lokalnie
(pytest, kopia produkcji), ssh na serwer.

**Spec:** `docs/superpowers/specs/2026-10-04-priorytety-produkcji-design.md` — sekcje 5.4 (sygnały, odpytywanie
awaryjne), 5.5 (bramka ZAKOŃCZ, stara appka), 6.3 (tryb `stary`/`stol`, `realtime-token`), 8.6 (klucze `prod_config`),
8.7 (migracja, okno wdrożenia), 9.3 (wyzwalacze `utrwal()`, faza crona), 9.4 (współbieżność), 10 (błędy), **11** (P1–P4,
okno wdrożenia, ręczny cron, wycofanie), 13 (P-2, P-3, P-7), 14. Symulacja: `docs/superpowers/specs/2026-10-04-priorytety-produkcji-symulacja.md`
— „Analiza wyniku” A (poziom odniesienia), D p. 7 (co mierzyć po wdrożeniu), E (decyzje 5.10). Podręcznik centrali:
`docs/superpowers/plans/2026-10-05-priorytety-produkcji-centrala.md` — sekcje 2, 3, 4a (eskalacja), 5, 7 (S-4, S-6), 8.8.
CLAUDE.md: „Deployment” (deploy.sh, ręczny deploy, „Ważne”), „Zadania cykliczne (cron)”, „Trasy logistyki — jeden
piszący naraz”.

**Sesja:** lokalna z ssh, prowadzona przez **centralę** (Opus 5.5, high) razem z Konradem, bez trybu szybkiego. Lokalna,
bo potrzebne są: Docker (pełny pakiet pytest po scaleniu `main`, migracja i cron na kopii produkcji), ssh (odczyty logów
i bazy na serwerze), przeglądarka (panel, Konfiguracja). Rozłożone w czasie: część 1 — dzień wdrożenia + 1–2 dni
obserwacji; część 2 — ok. 14 dni przełączeń + 14 dni do pomiaru. Między częściami: K6 i sesja appki.

**Zależności:** K5 z werdyktem **„P1 GOTOWE DO WDROŻENIA”** (bramka centrali zaliczona); logistyka etapy 1–4 na `main`
i wdrożona, z jej ręcznymi krokami po wdrożeniu (CLAUDE.md „Ważne”, „Logistyka równoległa”); dla części 2 — raport
sesji appki z `version_code` APK i odbiorem z tabletem (K6 Task 5, Interfaces) oraz APK wgrany w Ustawieniach.

**Gałąź:** `claude/priorytety-produkcji` (zakłada K1 z `origin/claude/logistyka-etap-4`). Scalenie do `main` wyłącznie na
polecenie Konrada, w Task 2. Dokumenty kroku (raport, dziennik) commitowane na gałąź roboczą, **nigdy na `main`**.

## Global Constraints

- **Zero zmian w kodzie.** Każda potrzeba zmiany kodu, testu, migracji, `deploy.sh` → STOP i karta naprawcza centrali
  (podręcznik 6). Konflikt przy scaleniu `main` → gałąź to też zmiana kodu (karta naprawcza „scalenie”).
- **Push do `main` = deploy na produkcję.** Wykonuje go Konrad (albo sesja na jego wyraźne „scal teraz” dla tego punktu).
  Sesja nie pushuje `main` z własnej inicjatywy i nie woła ręcznego `./deploy.sh` ani `workflow_dispatch`.
- **Zapisy na produkcji** (ręczny cron, zmiana ustawień w Konfiguracji, restart, SQL wycofania) tylko na „wykonaj” Konrada
  dla konkretnego punktu. Odczyty (logi, `SELECT` w trybie tylko do odczytu, `supervisorctl status`) — wg decyzji Konrada
  z pytań startowych (rekomendacja: sesja sama).
- **Nigdy `create_app()` na bazie produkcyjnej poza deployem** (import odpala migracje, podręcznik 2 p. 9). Zapytania
  kontrolne idą gołym SQLAlchemy z `core.json` (wzorzec „SQL-RO” w sekcji „Środowisko”), z `SET SESSION TRANSACTION READ
  ONLY`, bez `FOR UPDATE`. Wyniki z danymi klientów (nazwy, adresy, telefony) nigdy do raportu ani do repo — zapytania
  zwracają tylko id, numery, statusy, liczby.
- **Repo publiczne:** w raporcie i dzienniku żadnych sekretów, kluczy API, adresów IP, danych klientów, treści `core.json`.
  Klucz Centrifugo czytamy do zmiennej powłoki, nie wypisujemy (wzorzec `ops/centrifugo/README.md:70-72`).
- **Ustawienia priorytetów zmieniamy jedną drogą:** Konfiguracja → karta „Stół stanowisk” (K4b) albo
  `PUT /production/api/priorytety/ustawienia` (K2). Nigdy surowym `UPDATE prod_config` (omija log `ustawienia`
  i walidację). Po zapisie — restart albo odczekanie, wg Doprecyzowania 2.
- **Kolejność blokad** z CLAUDE.md i spec 9.4 obowiązuje także czynności runbooka (sekcja „Współbieżność”).
- **Eskalacja** (podręcznik 4a): pierwsze MySQL 1213 na produkcji → `SHOW ENGINE INNODB STATUS` (sekcja `LATEST DETECTED
  DEADLOCK`, bez rekordów z danymi klientów) i analiza na **Fable 5.1, max**, zanim ktokolwiek zmieni kod.
- Commity (tylko dokumenty na gałęzi roboczej): Conventional Commits po polsku, temat bez polskich znaków, stopka
  atrybucji sesji, `git add -f docs/superpowers/...`. Python 3.9 nie dotyczy (bez kodu).

## Review Focus

Runbook nie dodaje testów; pilnuje, żeby na produkcję weszło to, co testy K1–K5 zabezpieczają, i żeby zachowanie na żywo
zgadzało się z ich asercjami. Przed scaleniem (Task 1) te testy muszą być zielone na gałęzi po scaleniu `main`:

1. **Okno wdrożenia nie wywraca starego workera** — migracja bez zmian ENUM, idempotentna, sortuje się po migracjach
   logistyki: `test_brak_zmian_enum_istniejacych_tabel`, `test_seed_dziewieciu_szczebli_w_kolejnosci_3_1`,
   `test_38_wierszy_prod_config`, `test_sortuje_sie_po_ostatniej_migracji_logistyki` (K1 Task 1). Na żywo: Task 1
   Step 5 (kopia produkcji, ×2) i Task 2 (log deployu).
2. **Ręczny cron po restarcie robi to, co obiecuje spec 11** — `test_cron_ma_faze_priorytety_utrwalone`,
   `test_cron_uzupelnia_pod_blokada_tras_przed_utrwal` (K1 Task 6). Na żywo: Task 3 Step 1 (klucze `szczeble_uzupelnione`,
   `priorytety_utrwalone.success`).
3. **`utrwal()` blokuje zamówienia przed pozycjami i nie dotyka sesji wołającego** — `test_utrwal_blokuje_zamowienia_przed_pozycjami_przed_zapisem`,
   `test_utrwal_nie_commituje_ani_nie_cofa_sesji_wolajacego`, `test_utrwal_ponawia_raz_po_1213_na_nowej_sesji` (K1 Task 4)
   oraz wyścig `utrwal-dostawa` z K5. Na żywo: zero 1213 w logach po cronie i w dniach obserwacji (Task 3 Step 6).
4. **P1 nie zmienia pracy hali** (wszystkie stanowiska `stary`): `test_tryb_stary_bez_bramki`, `test_desk_w_trybie_stary_dziala`,
   `test_postpone_w_trybie_stary_dziala` (K3). Na żywo: stara appka kończy pozycje na każdym stanowisku (Task 3 Step 4).
5. **Próg wersji: 0 to NIE „wyłączone”** — `test_bramka_prog_zero_to_brak_bramki_wersji`,
   `test_bramka_stara_appka_bez_bramki_ale_zdejmuje_kafel` (K3). Na żywo: próg ustawiony PRZED pierwszym `stol` (Task 4),
   wycofanie progiem = duża liczba (Task 7).
6. **Zmiana ustawień dociera do wszystkich workerów** — `test_ustawienia_czytane_bez_pamieci_podrecznej_procesu` (K2 Task 5;
   zielony albo `xfail(strict=True)` z meldunkiem). Wynik z raportu K2/K5 decyduje, czy przełączenie wymaga restartu
   (Doprecyzowanie 2).
7. **Sygnały po commicie, nigdy w transakcji; brak brokera nie psuje akcji** — `test_zakoncz_sygnal_na_to_i_nastepne_stanowisko`,
   `test_sygnal_nie_idzie_przy_rollbacku_409`, `test_realtime_token_kanaly_stanowiska`, `test_publish_station_signal_kanal_i_ladunek`
   (K3 Task 4). Na żywo: publish testowy na `station:*` przed scaleniem (Task 1 Step 7) i po wdrożeniu (Task 3 Step 5).
8. **Stół bez duplikatów i bez 1213 bez ponowienia** — `test_desk_dwa_1213_to_500_bez_zapisow`,
   `test_odloz_limit_409`, `test_postpone_limit_409_bez_wpisu_idempotencji` (K3) i kryterium wyścigów K5 (zero 1213 bez ponowienia, zero zdublowanych
   i niekompletnych kafli). Na żywo: zapytania kontrolne stołu w obserwacji każdego stanowiska (Task 5 Step 4).

## Decyzje przyjęte (spec, symulacja, podręcznik)

1. Wdrożenie **po logistyce etapy 1–4, nigdy przed** (spec nagłówek, 11; podręcznik 2 p. 2) — 4.10.
2. P1 wchodzi z **wszystkimi stanowiskami w trybie `stary`** i `priorytety_min_app_version_code = 0` (spec 8.6, 11) —
   hala nie widzi stołu, widzi tylko nową kolejność listy.
3. **Po restarcie raz ręcznie** `scripts/cron_endpoint.sh POST /production/api/logistics/cron` (spec 11, K1 „Wdrożenie”).
4. Kolejność przełączania (S-6 — decyzja Konrada 5.10 w dzienniku centrali; spec 11, ustalenie 15): **Sklejanie →
   Formatowanie → Składanie → Wycinanie → Krawędzie → Pakowanie**, po 2 dni obserwacji każde. **Lakiernia nie
   przechodzi na `stol`** (wariant C): zostaje na stałe w `stary`, tablet pokazuje pełną listę ułożoną po wykończeniu
   (spec 3.2 „Lista Lakierni”), ZAKOŃCZ bez bramki, bez Odłóż; kod i tak ją przepuszcza (`STANOWISKA_BEZ_STOLU`, K3 Task 5a).
5. Parametry startowe (Konrad 5.10, spec 13): K = 2 wszędzie, limit odłożeń 10, „Blisko terminu” 3 dni robocze, drabina
   domyślna ★★★★★, Po terminie, ★★★★, Blisko terminu, Rozpoczęte, ★★★, ★★, ★, bez gwiazdek; odpytywanie awaryjne
   30 s / 5 min (P-7). K7 ich nie zmienia; korekty tylko na decyzję Konrada przez Konfigurację.
6. **Pomiar** tym samym skryptem (symulacja D p. 7): omijanie pilniejszych ma spaść, rozrzut przed Formatowaniem
   (dziś p90 70,8 h) **nie może wzrosnąć** — 5.10.
7. Wycofanie (spec 11): P3 — `priorytety_tryb_<S>` → `stary` bez zmiany kodu; P1 — cofnięcie kodu, kolumny i tabele
   zostają, gwiazdki zostają na przyszłość, stary algorytm przelicza rangi przy następnej synchronizacji.
8. K8 dopiero po 2–3 tygodniach P3 bez wycofania i po zdjęciu starej appki z tabletów (podręcznik 3, 8.9).

## Doprecyzowania (do specu — przeniesie centrala kartą dokumentacyjną albo K8)

1. **`priorytety_min_app_version_code = 0` znaczy „bramka stołu dla każdego tabletu”, nie „wyłączone”** (K3 Doprecyzowania
   p. 3: `stary = prog > 0 and (kod is None or kod < prog)`). Spec 8.6 opisuje 0 jako „brak bramki” — chodzi o brak
   bramki **wersji**. Wycofanie bramki dla wszystkich tabletów naraz = próg **większy niż każdy `version_code`**
   (runbook: `999999`), nie 0.
2. **Zmiana trybu/progu a pamięć podręczna procesu.** `config_service` trzyma wartości 60 min na proces
   (`config_service.py:47-56`); K2 unieważnia tylko w workerze, który obsłużył `PUT`. Jeśli raport K2/K5 mówi, że
   `test_ustawienia_czytane_bez_pamieci_podrecznej_procesu` jest zielony — zmiana działa od razu. Jeśli `xfail` — każda
   zmiana trybu, progu wersji, K i limitu idzie razem z `sudo /usr/local/sbin/crm-fix-logs-perms.sh && sudo
   /usr/bin/supervisorctl restart crm_woodpower` (CLAUDE.md „Ważne”, incydent 24.09: zapis i restart razem). Dotyczy też
   wycofania P3 — „bez zmiany kodu” w spec 11 nie znaczy „natychmiast” bez restartu.
3. **Scalenie do `main` przez merge commit** (PR „Create a merge commit” albo `git merge --no-ff`), nie squash ani rebase:
   wycofanie P1 = jeden `git revert -m 1 <merge>`; ponowne wdrożenie po revercie wymaga „revertu revertu”.
4. **Wycofanie kodu P1 — skutki dla danych, których spec 11 nie wymienia** (z kodu, sekcja „Ugruntowanie”):
   - doróbki utworzone w P1 mają `priority_rank = 0`, `priority_manual_override = False`; stary algorytm nada im zwykłą
     rangę przy pierwszej synchronizacji, więc stracą szczyt kolejki, który dawał `lock_priority(rank=1)`
     (`rework_service.py:302`, `models.py:513-518`). Naprawa danych jednym `UPDATE` (Task 7, Step 4) — na decyzję Konrada;
   - `prod_products.is_priority` jako pochodna (`gwiazdki ≥ 1`, „Po terminie”, doróbka) zostaje; stary kod jej nie
     przelicza (`priority_service.py` nie zapisuje `is_priority`), więc pomarańczowe ramki starej appki zostaną na tych
     pozycjach do ręcznej zmiany — decyzja Konrada: zostawić albo wyzerować (Task 7, Step 4);
   - trasy utworzone po revercie nie dostaną szczebli; przy ponownym wdrożeniu P1 naprawi to `drabina.uzupelnij()` w cronie;
   - wiersze `prod_station_desk` zostają (FK CASCADE sprząta usunięte pozycje); przed ponownym przełączeniem na `stol`
     po ponownym wdrożeniu — decyzja, czy wyczyścić stół (odłożenia stracą widoczność).
5. **Pomiar (spec 11, symulacja D p. 7):** skrypt **nie czyta** gwiazdek ani drabiny z bazy (`wczytaj`
   `scripts/symulacja_priorytetow.py:177-231`, gwiazdki tylko z `--gwiazdki` CSV `:743-755`, drabina z `--drabina`
   `:275-285`). Żeby sekcje 1–2 raportu opisywały rzeczywistą kolejkę, runbook buduje CSV gwiazdek i listę `--drabina`
   z bazy (Task 6). Sekcja 3 (historia) od tego nie zależy. Okno `--dni 14` liczone od dnia przełączenia Pakowania
   (ostatniego stanowiska), żeby całe okno było w trybie `stol` na wszystkich stanowiskach ze stołem.
6. **Lakiernia i Krawędzie dzielą tablet** (`STATION_GROUPS`, `mobile_api_service.py:118-120`): po przełączeniu Krawędzi
   tablet Krawędzi pracuje **na stałe** w trybie mieszanym (spec 6.4 p. 7): ekran Krawędzi = stół (Teraz, Odłożone,
   Odłóż, bramka ZAKOŃCZ), ekran Lakierni = lista po wykończeniu, ZAKOŃCZ bez bramki. Hala musi to wiedzieć (Task 5,
   karta Krawędzi).
7. **Cron „o północy i co godzinę” (spec 9.3)** = istniejący godzinny wpis crona logistyki; nowego wpisu crontaba P1
   nie wymaga.
8. **Liczba wierszy `prod_config` po migracji:** 37 kluczy `priorytety_*` (7 stanowisk × 5 + próg + wersja) i
   `DEADLINE_DAY_TYPE` — razem 38 (K1 `test_38_wierszy_prod_config`). Lista wdrożenia K5 (plan K5 Task 6 Step 5 p. 4)
   pisze „38 wierszy `priorytety_*`” — obowiązuje rachunek K1.
9. **Okno pomiaru:** lista wdrożenia K5 (p. 9) podaje `--dni 30`; runbook mierzy `--dni 14` od przełączenia Pakowania
   (całe okno w `stol` na wszystkich stanowiskach ze stołem), a `--dni 30`/`60` tylko do trendu.
10. **Lista wdrożenia P1 z raportu K5** (plan K5 Task 6 Step 5, p. 1–9) jest wejściem tego runbooka: Task 1 Step 1
    porównuje ją punkt po punkcie z Taskami 1–3; punkt z listy K5, którego runbook nie ma, dopisuje się do dziennika
    jako dodatkowy punkt kontrolny (nie zmienia planu bez centrali).
11. **Ranga zamówienia nieaktywnego (spec 8.1 „pamięć podręczna”):** `utrwal()` nie dotyka zamówień bez pozycji
    w `STATUSY_PRODUKCJI`, więc ich `priority_rank`/`priority_rung` zostają z ostatniego przeliczenia (plan K1, „Doprecyzowania”)
    i powtarzają rangi aktywnych. Unikatowość rang i zgodność z Listą produkcyjną sprawdzamy wyłącznie wśród zamówień
    aktywnych (Task 3 Step 3); spec 8.1 tego nie mówi — do dopisania kartą dokumentacyjną.

## Ugruntowanie w kodzie (stan przed K7)

Stan w chwili pisania planu: gałąź `claude/logistyka-etap-4` @ `b4b4a54d`; `origin/main` @ `a71af794` (2.10). K7 nie
zmienia żadnego pliku kodu — tabela wskazuje, na czym runbook polega.

| Miejsce | Stan obecny | Rola w runbooku |
|---|---|---|
| `deploy.sh` | lock `:8-18`; `FLASK_SKIP_DOTENV=1` `:29`; `OLD_HEAD` `:31`; `git fetch origin main` + `reset --hard` `:34-35`; log `Deploy: OLD -> NEW` `:38`; `pip` best-effort `:41`; `sync-changelog` `:44-47`; **`flask migrate` `:60-70`** (błąd → `[MIGRATION FAILED]` `:62`, cofnięcie kodu do `OLD_HEAD` `:63-64`, `[ROLLBACK FAILED]` `:66`, `exit 1` `:69`); przeliczenie klientów `timeout -k 10 300` `:91-92`; chown logów `:105`; restart `:107`; `Deploy complete!` `:109` | Task 2: co czytać w logu i co znaczy każda linia |
| `modules/deploy/routes.py` | `github_webhook` `:16`; tylko `refs/heads/main` `:46-48`; log `logs/deploy.log` `:57-59`; `Popen(..., start_new_session=True)` `:64-70` | Task 2: gdzie jest log; webhook uruchamia `deploy.sh` z dysku sprzed pobrania (CLAUDE.md) |
| `app.py` | `RUN_MIGRATIONS` w `create_app()` `:178-191` (domyślnie włączone — każde `flask …` i każdy nowy worker gunicorna wykonuje oczekujące migracje przy starcie); `register_cli_commands`: `flask migrate` `:309-323` (`Wykonano N migracji.`, `BŁĄD migracji …` i `SystemExit(1)`); `flask migrate-status` `:325-355` | Task 2 Step 4–5 |
| `migrations/migration_service.py` | wzorce nazw `:32-35`; `run_pending_migrations` `:296-334` (nieudana migracja zapisana z `success=False`, rollback, dalsze migracje idą `:322-331`); wykonane = `success = TRUE` `:125-134` | nieudana migracja wykona się ponownie przy następnym deployu; DDL MySQL commituje się sam, więc częściowy stan dokańcza idempotentny plik |
| `scripts/cron_endpoint.sh` | sekret z `core.json` `:36-44`, nagłówek przez stdin `:51-52`, kod 0 tylko przy HTTP 200 `:60-65`, wypisuje treść odpowiedzi `:65` | Task 3 Step 1 |
| `modules/production/logistics/routers/cron_api.py` | `cron` `:24-80`: faza 1 `przenies_osierocone` + commit `:37-47`, faza 2 `dostarcz_wydane` + commit `:57-58`, faza 3 `przelicz_otwarte` + commit `:62-63`, wątki w tle `:64-65`, odpowiedź `:67-75`, błąd → 500 `:76-80` | po K1: po `:63` `drabina.uzupelnij()` + commit i `kolejka.utrwal()`, klucze `szczeble_uzupelnione`, `priorytety_utrwalone` (plan K1 Task 6) — **na tej gałęzi jeszcze ich nie ma** |
| `modules/production/services/realtime_service.py` | kanały w docstringu `:10-12` (`station:<code>` zapowiedziany); `is_enabled` `:53-56` (`REALTIME.enabled`); `publish` `:110` (nigdy nie rzuca, alert Sentry co 50 porażek `:42`); `issue_connection_token` `:192` | Task 1 Step 7, Task 3 Step 5; po K3: `CHANNEL_STATION`, `publish_station_signal(kod)` (plan K3 Task 4) |
| `ops/centrifugo/config.example.json` | `uni_sse.enabled` `:14-16`; namespaces `print`, `station` `:17-26` | wzorzec; na serwerze `/etc/centrifugo/config.json` (README `:18`) — sprawdzamy, nie zmieniamy repo |
| `ops/centrifugo/README.md` | test publikacji z serwera `:68-77` (`{"result":{}}` = przyjęte; publiczne `/realtime/api/publish` → 403); włączanie/wyłączanie `REALTIME.enabled` + restart `:79-90`; dodanie namespace `:92-98` | Task 1 Step 7, Task 7 Step 5 |
| `modules/production/services/config_service.py` | `ProductionConfigService.__init__(cache_duration_minutes=60)` `:47-57`; `get_config` `:83`; `set_config` `:265`; `invalidate_cache` `:452` | Doprecyzowanie 2 |
| `modules/production/models.py` | `ProductionDevice` `:1139-1161` (`prod_devices`: `station_code`, `is_active`, `last_heartbeat_at`, `last_app_version_code` `:1161`); `lock_priority` `:513-518` (ranga, `priority_manual_override = True`, `is_priority = True`); blok doróbki w `complete_task` `:712-725`; `ProductionConfig` `prod_config` `:915-927` (`config_key`, `config_value`, `config_type`) | Task 4 (wersje tabletów), Task 7 (dane po revercie) |
| `modules/production/routers/mobile_api.py` | `KSZTALT_ODPOWIEDZI_KOLEJKI = 5` `:137` (K3 → 6: jednorazowa zmiana ETagu listy starej appki); `device_heartbeat` `:1256-1300` (co 15 min; `last_app_version_code` `:1278`) | Task 3 Step 4, Task 4 Step 3 |
| `modules/production/services/mobile_api_service.py` | `STATION_GROUPS = [{'edges', 'painting'}]` `:118-120`; `REFRESH_INTERVAL_SECONDS` dla starej appki `:1647` | Doprecyzowanie 6; K8 |
| `modules/production/services/rework_service.py:302` | `rework.lock_priority(rank=1)` (K1 zamienia na rangę 0) | Doprecyzowanie 4 |
| `modules/production/services/priority_service.py` | stary algorytm; nie zapisuje `is_priority` (grep: brak przypisania) | Doprecyzowanie 4 |
| `scripts/symulacja_priorytetow.py` | docstring uruchomienia `:31-50`; `DRABINA_DOMYSLNA` `:83`; `wczytaj` `:177-231` (`SET SESSION TRANSACTION READ ONLY` `:182-186`, trasy `:217-221`); `_drabina` `:275-285` (`trasy` albo `trasa:<id>`); `_wczytaj_gwiazdki` `:743-755` (klucz = `internal_order_number`); parser `:758-771`; `_db_url` `:724-729` | Task 6 |
| `.github/workflows/deploy.yml` | `on: workflow_dispatch` — tylko ręczny fallback | nie używamy (Global Constraints) |
| `main`: `mobile_api_service.register_release(..., activate)` (`origin/main:…/mobile_api_service.py:1413`, commit `b910b07b`) | wgrany APK domyślnie **nieaktywny**; tablety instalują najnowszy aktywny; włącza przełącznik „Aktywny” w historii wydań | Task 4 Step 1 (wydanie appki) |

**Czego w kodzie nie ma (żeby nikt nie szukał):** gałęzi `claude/priorytety-produkcji`, pakietu `modules/production/priorytety/`,
migracji `2026-10-05-priorytety-produkcji.sql`, kluczy `priorytety_*`, końcówek `/production/api/priorytety/*`,
`/api/mobile/stations/<kod>/desk`, `/postpone`, `/realtime-token`, `publish_station_signal` — wszystko to powstaje w K1–K3
(nazwy wg planów K1–K3 i specu 8.6, 9.1). Plan K5 istnieje (`docs/superpowers/plans/2026-10-05-priorytety-krok-K5-przeglad-p1.md`),
jego raportu z werdyktem i „Listą wdrożenia P1” jeszcze nie. Na `origin/main` nie ma logistyki etapów 1–4 (brak
migracji `2026-09-24…` i dalszych, brak `cron_api.py` logistyki) ani skryptu `scripts/symulacja_priorytetow.py` — trafią tam
z wdrożeniem logistyki i P1. W repo nie ma skryptu kopii bazy ani konfiguracji gunicorna/supervisora CRM (żyją na
serwerze) — runbook ich nie zgaduje, każe sprawdzić. **Task 1 Step 1 aktualizuje tę tabelę numerami linii z HEAD gałęzi
roboczej po K5** (grep z Task 1).

## Współbieżność — czynności runbooka a kolejność blokad (CLAUDE.md, spec 9.4)

Runbook nie dodaje pisarzy. Te czynności biorą blokady na produkcji w trakcie pracy hali — kolejność jest kodem K1–K3,
runbook tylko pilnuje warunków:

| Czynność | Kolejność blokad (z kodu K1–K3) | Warunek runbooka | Test / dowód |
|---|---|---|---|
| ręczny cron (Task 3 Step 1) | faza 1–3 logistyki, każda w osobnej transakcji (zamówienia rosnąco) → `drabina.uzupelnij()`: `routes.zablokuj_trasy()` → `prod_priority_rungs` `FOR UPDATE` → commit → `kolejka.utrwal()` na własnej sesji: zamówienia `FOR UPDATE` rosnąco → pozycje tych zamówień rosnąco → jeden flush → commit; 1213 → jedno ponowienie | jedno wywołanie naraz (nie w minucie godzinnego crona — sprawdzić minutę wpisu crontaba); czas odpowiedzi < 30 s (timeout workera) — zmierzony na kopii w Task 1 Step 6 | `test_cron_uzupelnia_pod_blokada_tras_przed_utrwal`, `test_utrwal_blokuje_zamowienia_przed_pozycjami_przed_zapisem`, wyścig `utrwal-dostawa` (K5) |
| zmiana ustawień (Task 4, 5, 7) | `PUT /ustawienia`: tylko `prod_config` + `prod_priority_log` (bez `order_id`) → commit → `utrwal()` po commicie tylko przy zmianie progu „Blisko terminu” | bez SQL na `prod_config`; restart wg Doprecyzowania 2 | K2 Task 5 (kolejność: walidacja → zapis → commit → invalidate → przeliczenie) |
| przełączenie na `stol` (Task 5) | od tej chwili ZAKOŃCZ/licznik na tym stanowisku przechodzą przez `stol.bramka_zakoncz` pod blokadą zamówienia, którą handler już trzyma; `desk`: blokada `priorytety_blokada_<S>` → odczyt bieżący kandydatów → INSERT → commit → sygnał | przełączać przed rozpoczęciem zmiany albo w przerwie, nie w szczycie ZAKOŃCZ | `test_desk_dwa_1213_to_500_bez_zapisow`, wyścigi K5 `desk-desk`, `desk-zakoncz` |
| SQL wycofania doróbek (Task 7 Step 4) | `SELECT id` (SQL-RO), potem jedno `UPDATE prod_products … WHERE id IN (<lista>) ORDER BY id` — pisarz pozycji bez blokady zamówienia: blokady tylko wskazanych wierszy, po PK rosnąco, bez skanu po indeksie statusu (RR blokowałby każdy przejrzany wiersz w kolejności indeksu), nie zmienia kolumn FK, więc nie sięga po `prod_orders` (CLAUDE.md „pisarz pozycji bez blokady zamówienia”) | tylko po decyzji Konrada, poza godzinami pracy hali, po `SELECT` z liczbą wierszy | — (dowód: liczba wierszy przed/po w raporcie) |
| zapytania kontrolne (wszędzie) | `SET SESSION TRANSACTION READ ONLY`, zwykły `SELECT`, bez `FOR UPDATE`/`FOR SHARE` | nigdy w jednej sesji z zapisem | — |

Po wdrożeniu P1 i po każdym przełączeniu: `grep -cE "zakleszczenie 1213|\(1213, |Deadlock found"` w dziennym logu
aplikacji (`modules/logging/logs/app_<data>.log`, katalog z `ops/crm-fix-logs-perms.sh:22`) — **wzorzec „1213”** dalej
w runbooku. Gołe `1213` łapałoby numery zamówień i id; ten wzorzec łapie ponowienia (`zakleszczenie 1213` w WARNING-ach
kodu, np. `products_api.py:1605`) i błąd MySQL. Wynik > 0 → eskalacja (Global Constraints).

## Środowisko i role

- **Konrad:** decyzje, push do `main`, „wykonaj” dla zapisów na produkcji, wydanie APK, komunikat do biura i hali.
- **Centrala (sesja K7):** przygotowuje polecenia, czyta wyniki, odhacza punkty w dzienniku centrali
  (`docs/superpowers/plans/raporty/2026-10-05-priorytety-dziennik-centrali.md`) z datą i godziną, zbiera zgłoszenia hali.
- **Lokalnie:** `docker compose exec app pytest tests/ -q -p no:cacheprovider` (pełny pakiet; nie dwa naraz — pamięć) i
  `docker compose exec app bash -c "cd integrations/blog_seo && python -m pytest"`.
- **Serwer:** katalog `/home/woodpower-crm/htdocs/crm.woodpower.pl`, użytkownik `woodpower-crm`, log deployu
  `logs/deploy.log`, logi aplikacji `modules/logging/logs/`, program supervisora `crm_woodpower`, broker `centrifugo`.
- **Wzorzec „SQL-RO”** (na serwerze, w katalogu aplikacji; bez `create_app()`, bez wypisywania `DATABASE_URI`):

```bash
sudo -u woodpower-crm venv/bin/python - <<'EOF'
import json
from sqlalchemy import create_engine, text
url = json.load(open('config/core.json', encoding='utf-8'))['DATABASE_URI']
with create_engine(url).connect() as c:
    c.execute(text('SET SESSION TRANSACTION READ ONLY'))
    for w in c.execute(text("""ZAPYTANIE""")):
        print(tuple(w))
EOF
```

## Mapa plików

| Plik | Task | Rola |
|---|---|---|
| `docs/superpowers/plans/raporty/2026-10-05-priorytety-dziennik-centrali.md` (zmieniany) | 1–7 | odhaczenia punktów runbooka z datą, decyzje Konrada, zgłoszenia hali |
| `docs/superpowers/plans/raporty/<data>-priorytety-pomiar-po-p3.md` (nowy) | 6 | raport skryptu symulacji po P3 + tabela porównania (bez danych klientów) |
| `docs/superpowers/plans/raporty/2026-10-05-priorytety-krok-K7-raport.md` (nowy) | 8 | raport kroku |
| kod, testy, migracje, `deploy.sh`, `CLAUDE.md`, spec | — | **bez zmian** (zmiana = karta naprawcza) |

---

### Task 1: Warunki wejścia, scalenie `main` → gałąź, próba generalna na kopii produkcji, przegląd serwera

**Files:** dziennik centrali (wpisy). Bez zmian w kodzie; commit scalenia `main` → gałąź tylko, gdy scalenie jest czyste.

**Interfaces (Consumes):** werdykt K5; raporty K1–K5 („Co następny krok musi wiedzieć”); migracja
`migrations/2026-10-05-priorytety-produkcji.sql`; odpowiedź crona z kluczami `szczeble_uzupelnione` (int) i
`priorytety_utrwalone` (`{'success', 'zamowien', 'pozycji', 'zmienione_zamowienia', 'zmienione_pozycje', 'ostrzezenia',
'duration_seconds', 'error'}` — plan K1 Task 4); kanał `station:<kod>` (spec 5.4).

- [ ] **Step 1: Warunki wejścia i ugruntowanie na HEAD**
  1. Dziennik: K1–K5 „zaliczony”, werdykt K5 „P1 GOTOWE DO WDROŻENIA”; odpowiedzi na pytania startowe K7 (sekcja
     „Pytania do Konrada”, A1–A4) wpisane.
  2. Logistyka na `main`: `git fetch origin && git merge-base --is-ancestor <hash wdrożonej logistyki> origin/main`;
     na serwerze `flask migrate-status` nie jest potrzebne — SQL-RO:
     `SELECT version, success FROM schema_migrations WHERE version >= '2026-09-25' ORDER BY version` → każdy plik
     `migrations/` z `origin/main` od `2026-09-25-logistyka-sposob-dostawy.sql` (lista: `git ls-tree --name-only origin/main
     migrations/`) ma wiersz z `success = 1` — także `2026-09-30-*` (paczki, weryfikacja, blokada paczek) i `2026-10-0*`.
     (Wzorzec `LIKE '2026-09-2%'` pomijałby migracje etapu 4 z 30.09.) Ręczne kroki logistyki po wdrożeniu (CLAUDE.md „Ważne”) odhaczone
     w dzienniku logistyki. Brak → STOP (P1 nie wchodzi przed logistyką).
  3. Grep nazw, na których runbook polega (wynik do raportu, brak którejkolwiek → STOP):
     `git grep -n "szczeble_uzupelnione\|priorytety_utrwalone\|def publish_station_signal\|CHANNEL_STATION\|def bramka_zakoncz\|def min_app_version\|def tryb\|priorytety_min_app_version_code\|priorytety_tryb_" -- modules migrations`.
  4. Zaktualizuj w raporcie K7 tabelę „Ugruntowanie” numerami linii z HEAD (cron, migracja, `realtime_service`).
  5. „Lista wdrożenia P1” z raportu K5 obok Tasków 1–3 (Doprecyzowanie 10); hash gałęzi roboczej = hash z werdyktu K5
     (inny → co doszło po werdykcie; kod → STOP, bramka centrali od nowa). Status Base. 524520 istnieje (warunek
     logistyki etapu 4, CLAUDE.md) — potwierdza Konrad.
- [ ] **Step 2: Scalenie `main` → gałąź robocza** (podręcznik 2 p. 2): `git checkout claude/priorytety-produkcji &&
  git pull --ff-only && git merge origin/main`. Konflikty → `git merge --abort`, STOP, karta naprawcza „scalenie + testy”
  (pliki z blokadami: Fable 5.1, extra). Czyste scalenie → commit scalenia (domyślny komunikat + stopka), push gałęzi.
- [ ] **Step 3: Co wnosi scalenie do `main`:** `git diff --stat origin/main...claude/priorytety-produkcji -- deploy.sh
  requirements.txt .github/ scripts/cron_endpoint.sh` → oczekiwane puste. Zmiana `deploy.sh` → wdrożenie dwuetapowe
  (CLAUDE.md „Deployment”) — STOP i decyzja Konrada. `git diff --name-only origin/main...claude/priorytety-produkcji --
  migrations/` → oczekiwana jedna nowa migracja priorytetów (inne → wypisać i wyjaśnić przed scaleniem).
- [ ] **Step 4: Pełny pakiet po scaleniu** (Review Focus 1–8 w środku): `docker compose exec app pytest tests/ -q -p
  no:cacheprovider` → `0 failed`, liczby do raportu; blog_seo → zielone. Jakikolwiek `failed` → STOP, karta naprawcza.
  Kontener ma Pythona 3.12, produkcja 3.9: składnia 3.9 poleceniem z planu K5 (Task 1 Step 3, `ast.parse(...,
  feature_version=(3,9))` + grep adnotacji `X | Y`) dla `git diff --name-only --diff-filter=d origin/main...HEAD -- '*.py'`
  (lista z `git` na hoście) → `OK`. Błąd → STOP (na produkcji `flask migrate` padłby na imporcie, deploy by się cofnął).
- [ ] **Step 5: Migracja na świeżej kopii produkcji** (po wdrożeniu logistyki, więc kopia z K5 jest nieaktualna):
  zrzut strumieniem przez ssh (`mysqldump --single-transaction --quick --no-tablespaces --default-character-set=utf8mb4`,
  jak w `docs/superpowers/plans/2026-09-26-logistyka-etap-3-przekazanie.md:131-134`) do osobnej bazy w kontenerze `db`;
  w lokalnej konfiguracji testowej **puste** `API_BASELINKER.api_key`, poczta, GlobKurier, AI, Sentry (inaczej dopychacz
  wyśle zmiany do prawdziwego Base.). `DATABASE_URI` przestawiony na kopię przy działającym kontenerze (zmiana `core.json`
  nie przeładowuje dev servera — byle w tym czasie nie zmieniać plików `.py`, bo reloader zbudowałby aplikację i wykonał
  migrację przed pomiarem; K5: „start podglądu na kopii jest pierwszym przebiegiem migracji”), potem
  `time docker compose exec app flask migrate` ×2 (podgląd dla Step 6 dopiero po nich: `docker compose restart app`) →
  pierwszy: `[Migrations]   ✓ Sukces: 2026-10-05-priorytety-produkcji_…` (wykonuje go już `create_app()` komendy, więc
  może ona wypisać `Wykonano 0 migracji.`), drugi: `Brak nowych migracji do wykonania`; czas
  pierwszego przebiegu do raportu (okno blokady metadanych `prod_orders`). Po migracji SQL: 9 wierszy stałych
  w `prod_priority_rungs`, `SELECT COUNT(*) FROM prod_config WHERE config_key LIKE 'priorytety\_%'` = 37 i
  `DEADLINE_DAY_TYPE` = 1 — razem 38, jak w K1 `test_38_wierszy_prod_config` (lista K5 mówi „38 wierszy `priorytety_*`”
  — Doprecyzowanie 8).
- [ ] **Step 6: Cron na kopii:** wywołanie `POST /production/api/logistics/cron` na lokalnym podglądzie z tą bazą (nagłówek
  `X-Cron-Secret` z lokalnej konfiguracji). **`scripts/cron_endpoint.sh` ma domyślnie `ADRES=https://crm.woodpower.pl`
  i `KATALOG_APLIKACJI` serwera (`:20-21`)** — lokalnie wyłącznie z obiema zmiennymi, na hoście (obraz kontenera nie ma
  `curl`): `time ADRES=http://localhost:<CRM_APP_PORT> KATALOG_APLIKACJI="$PWD" sh scripts/cron_endpoint.sh POST
  /production/api/logistics/cron` (wymaga `python3` i `curl` na hoście; bez nich — ten sam nagłówek przez `curl -H @-`
  na `localhost`). Wywołanie bez `ADRES` uderzyłoby w produkcję. Oczekiwane: 200, `szczeble_uzupelnione` = liczba tras roboczych+zatwierdzonych na kopii,
  `priorytety_utrwalone.success = true`, `duration_seconds` do raportu. Drugie wywołanie: `szczeble_uzupelnione = 0`,
  `zmienione_zamowienia` ≈ 0. Czas całej odpowiedzi > 20 s → STOP (na produkcji worker ma 30 s; decyzja centrali/Konrada).
- [ ] **Step 7: Przegląd serwera (odczyty):**
  1. Centrifugo: `supervisorctl status centrifugo` → RUNNING; namespace `station` w `/etc/centrifugo/config.json`
     (plik `chmod 600`, właściciel `woodpower-crm` — `sudo -u woodpower-crm python3 -c` wypisujący tylko listę
     `channel.namespaces[*].name`; tak samo odczyt klucza do publish testowego); publish testowy jak `ops/centrifugo/README.md:70-72`,
     kanał `station:test`, dane `{"kind":"station","station":"test"}` → `{"result":{}}`. Błąd przestrzeni nazw → Konrad
     dopisuje namespace na serwerze + `supervisorctl restart centrifugo` (README `:92-98`; zmiana konfiguracji serwera,
     nie repo). Publiczne `https://crm.woodpower.pl/realtime/api/publish` → 403.
  2. `REALTIME.enabled` w `core.json` (wypisać tylko tę wartość). `false` → P1 działa, tablety w P3 zostaną przy
     odpytywaniu; decyzja Konrada, czy włączyć przed P3.
  3. Crontab: wpis `scripts/cron_endpoint.sh POST /production/api/logistics/cron` co godzinę istnieje (minuta wpisu do
     raportu — ręczny cron w Task 3 nie w tej minucie); log crona bez błędów z ostatniej doby.
  4. Kopia bazy przed wdrożeniem: zrzut ze Step 5 zachowany lokalnie (poza repo) jako punkt odtworzenia; ścieżka do raportu.
- [ ] **Step 8: Wpis do dziennika** (Steps 1–7 z wynikami) i commit dziennika na gałąź roboczą:
  `docs(priorytety): K7 warunki wejscia i proba generalna wdrozenia P1`.

### Task 2: Scalenie do `main` i obserwacja `deploy.sh` (część 1)

**Files:** dziennik. **Interfaces:** `logs/deploy.log` (linie z `deploy.sh:20-109`), `flask migrate` (`app.py:309-323`).

- [ ] **Step 1: Pytania przed scaleniem** (B1–B4 z sekcji „Pytania do Konrada”) — odpowiedzi w dzienniku. Komunikat do
  biura i hali gotowy (Task 3 Step 7) i wysłany przed scaleniem.
- [ ] **Step 2: Stan przed:** SQL-RO `SELECT COUNT(*) FROM prod_products WHERE current_status IN (<7 statusów produkcji>)`,
  liczba tras roboczych/zatwierdzonych, `COUNT(DISTINCT order_id)` tych pozycji (zamówienia aktywne — porównanie
  z `priorytety_utrwalone.zamowien` w Task 3 Step 1), `sudo -u woodpower-crm git -C <katalog aplikacji> rev-parse HEAD`
  na serwerze (= `OLD_HEAD`; jako właściciel repo, bez ostrzeżenia `safe.directory`) — do dziennika.
- [ ] **Step 3: Scalenie (Konrad):** PR `claude/priorytety-produkcji` → `main` z **merge commitem** (Doprecyzowanie 3),
  hash merge commita do dziennika. Sesja w tym czasie: `tail -f logs/deploy.log` na serwerze.
- [ ] **Step 4: Obserwacja logu — kolejno oczekiwane:** `Starting deploy...` → `Deploy: <OLD_HEAD> -> <merge>` →
  (pip) → `Running database migrations...` → linie runnera na stderr (`MigrationService.log` `:50-58`):
  `[Migrations] Wykonuję: 2026-10-05-priorytety-produkcji_2026-10-05-priorytety-produkcji.sql` (opis
  `{version}_{name}.{ext}`, dla pliku datowanego wersja = nazwa = cała nazwa bez rozszerzenia, `_match` `:60-75`,
  `:314`) i `[Migrations]   ✓ Sukces: …` (`:323`) → `Wykonano N migracji.` — **N = 0 albo 1 i oba są poprawne**: samo
  `flask migrate` buduje aplikację, a `create_app()` przy `RUN_MIGRATIONS` (domyślnie włączone, `app.py:178-191`)
  wykonuje oczekujące migracje jeszcze przed komendą; liczy się linia `✓ Sukces` i brak `[MIGRATION FAILED]` → `Recounting sales
  clients...` (do 300 s; `[recount-warn]` nie przerywa) → `Restarting application...` → `Deploy complete!`.
  `Already deploying, skipping.` → poprzedni deploy jeszcze trwa: po jego `Deploy complete!` Konrad wypycha ponownie
  (pusty commit na gałęzi roboczej i ponowne scalenie albo „Redeliver” webhooka). Gdy żaden deploy nie trwa
  (`pgrep -af deploy.sh` pusto), a lock `/tmp/crm-deploy.lock` leży (proces zabity bez `trap`) — Konrad usuwa lock
  i robi „Redeliver”; bez tego każdy kolejny push też się pominie.
- [ ] **Step 5: Gdy migracja padnie** (`[MIGRATION FAILED]` w logu): aplikacja zostaje na starym kodzie, kod na dysku
  cofnięty do `OLD_HEAD` (`deploy.sh:62-69`). **Nie restartować ręcznie**. Kolejno:
  1. `[ROLLBACK FAILED]` w logu → natychmiast Konrad: na serwerze `git reset --hard <OLD_HEAD>` i sprawdzenie
     `git rev-parse HEAD`, dopiero potem cokolwiek innego (gunicorn importuje `app.py` przy każdym nowym workerze);
  2. SQL-RO `SELECT version, success, error_message FROM schema_migrations WHERE version LIKE '2026-10-05%'` — treść
     błędu do raportu (bez danych);
  3. `main` ma teraz kod, którego serwer nie uruchomił: każdy następny push do `main` ponowi deploy. Decyzja Konrada:
     (a) karta naprawcza migracji na gałęzi roboczej → ponowne scalenie (runner wykona plik ponownie, bo zapisany
     z `success = 0`; plik idempotentny dokończy częściowy DDL), albo (b) `git revert -m 1 <merge>` na `main`
     (Task 7 Step 3) do czasu naprawy;
  4. STOP części 1 do decyzji.
- [ ] **Step 6: Po `Deploy complete!`:** `supervisorctl status crm_woodpower` → RUNNING; strona logowania 200; `flask
  migrate-status` niepotrzebne — SQL-RO `SELECT success FROM schema_migrations WHERE version LIKE '2026-10-05%'` → 1;
  `SHOW COLUMNS FROM prod_orders LIKE 'priority%'` → 5 kolumn (spec 8.1); `SELECT COUNT(*) FROM prod_priority_rungs WHERE
  kind <> 'route'` → 9.
- [ ] **Step 7: Wpis do dziennika** z godzinami (push, migracja, restart). Commit dziennika na gałąź roboczą.

### Task 3: Ręczny cron, weryfikacja P1 na produkcji, obserwacja

**Files:** dziennik. **Interfaces (Consumes):** `POST /production/api/logistics/cron` (klucze jak w Task 1);
`GET /production/api/priorytety/drabina` (`{"szczeble": [...], "ostrzezenia": [...]}`), `GET /production/api/priorytety/kolejka[?stanowisko=S]`
(K2); `GET /api/mobile/stations/<kod>/orders` (stara appka, `KSZTALT_ODPOWIEDZI_KOLEJKI` → 6); kanał `station:<kod>`,
ładunek `{"kind": "station", "station": "<kod>"}` (K3).

- [ ] **Step 1: Ręczny cron (Konrad „wykonaj”), zaraz po restarcie, nie w minucie godzinnego wpisu:**
  `sudo -u woodpower-crm scripts/cron_endpoint.sh POST /production/api/logistics/cron` → `OK: {…}`; w treści:
  `success: true`, `szczeble_uzupelnione` = liczba tras roboczych/zatwierdzonych bez szczebla (na świeżym wdrożeniu =
  wszystkie takie trasy), `priorytety_utrwalone.success: true`, `zamowien` = liczba zamówień aktywnych z Task 2 Step 2 (± zmiany od tamtej
  chwili), `zmienione_zamowienia` > 0 (pierwsze nadanie rang; 0 jest poprawne tylko wtedy, gdy między restartem a cronem
  `utrwal()` uruchomił już inny wyzwalacz — trasa, sposób dostawy, synchronizacja; wtedy rangi zamówień aktywnych są
  w bazie, Step 3), `ostrzezenia` przepisane do raportu, `duration_seconds`. HTTP ≠ 200 → treść błędu z stderr, log aplikacji, STOP;
  `priorytety_utrwalone.success: false` → `error` do raportu, drugie wywołanie po minucie; drugi raz `false` → STOP,
  eskalacja (jeśli 1213 — Fable max).
- [ ] **Step 2: Drabina 9 + trasy:** SQL-RO `SELECT r.position, r.kind, r.stars, r.tag, r.route_id, t.status FROM
  prod_priority_rungs r LEFT JOIN prod_routes t ON t.id = r.route_id ORDER BY r.position` → 9 szczebli stałych w kolejności
  z Decyzji 5 (z trasami wstawionymi pod najniższym szczeblem trasy albo pod ★★★★★, spec 3.1) + po jednym wierszu na trasę.
  Wiersz szczebla trasy **zostaje** w tabeli, gdy trasa przestaje być robocza/zatwierdzona (ukryty; „Cofnij załadunek”
  przywraca go na tym samym miejscu, spec 3.1, K1 `test_szczebel_trasy_zaladowanej_ukryty_po_cofnieciu_wraca`), więc
  liczymy z filtrem statusu: `SELECT t.id FROM prod_routes t LEFT JOIN prod_priority_rungs r ON r.route_id = t.id WHERE
  t.status IN ('robocza','zatwierdzona') AND r.id IS NULL` → pusto (każda aktywna trasa ma szczebel). W panelu: Lista produkcyjna → „Drabina priorytetów” pokazuje to samo, liczniki
  „w produkcji”, ewentualne ostrzeżenie o datach (do dziennika, bez przesuwania).
- [ ] **Step 3: Lista produkcyjna po randze:** zakładka nazywa się „Lista produkcyjna”; pierwsze 15 kart = pierwsze 15
  zamówień z SQL-RO `SELECT o.internal_order_number, o.priority_rung, o.priority_rank, o.priority_stars FROM prod_orders o
  WHERE <aktywne> ORDER BY o.priority_rank LIMIT 15` i z `GET /kolejka`, gdzie `<aktywne>` = `EXISTS (SELECT 1 FROM
  prod_products p WHERE p.order_id = o.id AND p.current_status IN (<7 statusów produkcji, stale.STATUSY_PRODUKCJI>))`.
  Rangi unikatowe **wśród aktywnych**: `SELECT o.priority_rank, COUNT(*) FROM prod_orders o WHERE <aktywne> GROUP BY
  o.priority_rank HAVING COUNT(*) > 1` → pusto, oraz `SELECT COUNT(*) FROM prod_orders o WHERE <aktywne> AND
  o.priority_rank IS NULL` → 0. Bez filtra wynik jest fałszywy: zamówienia nieaktywne zachowują rangę z ostatniego
  przeliczenia (plan K1, Doprecyzowanie 11), więc od pierwszego spakowania po cronie powtarzają rangi aktywnych.
  Konfiguracja: karty „Terminy” i „Stół stanowisk” wczytują się, wszystkie tryby `stary`, próg wersji 0. Kontrola krzyżowa algorytmu (nie
  blokuje): skrypt symulacji jak w Task 6 Step 2 (`--gwiazdki` i `--drabina` z bazy, `--dni 1`) — kolejka Sklejania
  w raporcie skryptu vs `GET /kolejka?stanowisko=gluing`, pierwsze 10 kafli; różnice opisać (spodziewane: stół, doróbki).
- [ ] **Step 4: Stara appka:** zaraz po restarcie — jedno ZAKOŃCZ testowe, jeśli ktoś z hali jest na zmianie (B3);
  w pierwszym dniu pracy po wdrożeniu — na każdym z 7 stanowisk co najmniej jedno ZAKOŃCZ ze starej appki (DoD 6; scalenie
  idzie po pracy hali, A1, więc „godzina od restartu” nie jest miarą; Lakiernia kończy ~3 pozycje dziennie — dzień bez jej
  pozycji odnotować, nie traktować jak błędu) (SQL-RO: `SELECT station_code, COUNT(*), MAX(created_at) FROM
  prod_station_events WHERE created_at >= '<restart>' AND source = 'mobile' GROUP BY station_code`); w godzinach pracy
  `SELECT station_code, device_id, last_app_version_code, last_heartbeat_at FROM prod_devices WHERE is_active = 1 ORDER BY
  station_code` — heartbeat świeższy niż 20 min (co 15 min, `mobile_api.py:1258`); hala potwierdza: lista się wczytała (jednorazowo
  pełne przeładowanie — zmiana ETagu), kolejność inna niż wczoraj (spodziewane), ZAKOŃCZ działa, brak 409 `nie_na_stole`.
  Lakiernia: serwer oddaje listę po grupach wykończenia, ale stara appka sortuje ją sama (spec 6.4 p. 7) — porządek po
  wykończeniu na ekranie dopiero z nową appką; to nie jest błąd wdrożenia.
- [ ] **Step 5: Centrifugo `station` po wdrożeniu:** publish testowy na `station:gluing` (README `:70-72`) → `{"result":{}}`;
  w logu aplikacji brak ostrzeżeń nieudanej publikacji realtime od restartu; Sentry: brak zdarzeń `subsystem: realtime`.
  Tablety starej appki nie łączą się z kanałem — to oczekiwane. `GET /api/mobile/realtime-token` z produkcyjnym brokerem
  (lista K5 p. 4) wymaga tokena urządzenia: jeśli Konrad ma zarejestrowane urządzenie testowe — jedno wywołanie, 200
  i `channels` = `station:<kod>` (sam token nie do raportu); jeśli nie — sprawdza to Task 4 Step 5 na nowej appce.
- [ ] **Step 6: Obserwacja 1–2 dni robocze:** dziennie: log aplikacji, wzorzec „1213” (sekcja „Współbieżność”) → 0; odpowiedzi
  godzinnego crona (`priorytety_utrwalone.success` i `duration_seconds` w logu crona); Sentry bez nowych błędów
  z `priorytety` (WARNING „trasa bez szczebla” = samonaprawa, odnotować; ERROR `utrwal` → karta naprawcza); czasy
  `GET /kolejka` i modalu priorytetu na produkcji kontra K5 (≤ 1 s); monitory hali
  i zakładka Stanowiska działają (stół pusty — wszystko `stary`, K4b; zakładka tylko przy decyzji A z planu K4b); gwiazdki ustawione przez biuro widać na tablecie
  w kolejności (po `utrwal()`); 404 starej gwiazdki w otwartych kartach przeglądarki → odświeżenie (K4a).
- [ ] **Step 7: Komunikat do biura i hali** (przygotowany w Task 2 Step 1, treść w raporcie): biuro — zakładka „Lista
  produkcyjna”, gwiazdki 0–5 na zamówieniu (także kolumna ★ w Logistyce) dostępne dla wszystkich z modułem produkcji (nie tylko admina, spec 7.3),
  „Drabina priorytetów”, trasa decyduje mimo ★★★★★, odświeżyć otwarte karty; hala — lista na tablecie w nowej kolejności,
  nic więcej się nie zmienia; co zgłaszać (sekcja „Co zgłasza hala”).
- [ ] **Step 8: Bramka części 1** w dzienniku: „P1 na produkcji stabilne” albo lista problemów. Commit dziennika.
  Centrala wydaje kartę K6 (podręcznik 3).

### Task 4: P3 — wydanie appki, wersje tabletów, próg wersji

**Files:** dziennik. **Interfaces (Consumes):** raport sesji appki: `version_code`, `version_name`, odbiór §14 kontraktu
(K6 Task 5); `prod_devices.last_app_version_code` (heartbeat co 15 min, `mobile_api.py:1278`); klucz
`priorytety_min_app_version_code` (int ≥ 0, `PUT /ustawienia` pole `min_app_version_code`, K2).

- [ ] **Step 1: Warunki:** raport sesji appki z odbiorem z tabletem (checklista §14 w całości, w tym fallback „nowa appka
  bez `/desk`” i tablet Krawędzi: stół Krawędzi i lista Lakierni po wykończeniu); kontrakt K6 zaliczony; K6 R1 rozstrzygnięty (pozycja z
  „Niekompletne” przechodzi bramkę — K3 `test_bramka_przepuszcza_pozycje_niekompletnego_zamowienia` zielony w pakiecie
  z Task 1 Step 4, a K6 nie zgłosił R1; zgłosił → karta naprawcza K3 i jej test), inaczej Formatowanie nie przejdzie w Task 5;
  `REALTIME.enabled` ustalone (Task 1 Step 7.2).
- [ ] **Step 2: Wydanie APK (Konrad):** Ustawienia → „Wgraj APK” bez „Aktywuj od razu” → kontrola wersji na liście →
  przełącznik „Aktywny” poza godzinami pracy hali (tablety instalują najnowszy aktywny — wydanie jest dla całej hali naraz).
- [ ] **Step 3: Wersje na tabletach:** SQL-RO z Task 3 Step 4 co 15 min aż każde aktywne urządzenie stanowisk
  produkcyjnych ma `last_app_version_code ≥ <version_code>`. Tablet, który nie przyszedł w 2 h → do Konrada (ręczna
  instalacja); bez niego stanowisko tego tabletu nie przechodzi na `stol`.
- [ ] **Step 4: Próg wersji (Konrad „wykonaj”):** Konfiguracja → „Stół stanowisk” → minimalna wersja appki = `<version_code>`
  → zapis; restart wg Doprecyzowania 2. Kontrola: SQL-RO `SELECT config_value FROM prod_config WHERE config_key =
  'priorytety_min_app_version_code'` i wpis `prod_priority_log` (`action = 'ustawienia'`, `note` = klucz). Wszystkie
  stanowiska dalej `stary`, więc próg niczego jeszcze nie egzekwuje.
- [ ] **Step 5: Nowa appka w trybie `stary`** (1 dzień): hala pracuje na stole bez bramki; `GET /api/mobile/realtime-token`
  z tabletów → 200 (log aplikacji; 503 = `REALTIME.enabled=false`, tablety na odpytywaniu); dwa tablety jednego
  stanowiska pokazują to samo po ZAKOŃCZ w ciągu sekund; odłożenia z powodami trafiają do Listy produkcyjnej. Wpis do dziennika.

### Task 5: P3 — przełączanie stanowisk na `stol` (×6, po 2 dni; Lakiernia bez przełączenia)

**Files:** dziennik. **Interfaces (Consumes):** `priorytety_tryb_<S>` ∈ {`stary`, `stol`} (spec 8.6; pole
`stanowiska.<S>.tryb` w `PUT /ustawienia`); 409 `nie_na_stole`, 409 `limit_odlozen` (spec 6.2, 10); tabele
`prod_station_desk`, `prod_priority_log` (spec 8.3, 8.4).

Ta sama karta dla każdego stanowiska, kolejno: `gluing`, `formatting`, `assembly`, `cutting`, `edges`, `packaging`.
Następne stanowisko dopiero po bramce poprzedniego. **`painting` nie ma karty** — zostaje `stary` na stałe (Decyzje 4);
przy każdej bramce SQL-RO `SELECT config_value FROM prod_config WHERE config_key = 'priorytety_tryb_painting'` = `stary`
(gdyby ktoś przełączył — bez skutku dla hali, kod ignoruje, ale przywrócić i odnotować).

- [ ] **Step 1: Pytania przed przełączeniem** (C1–C6, sekcja „Pytania do Konrada”) — odpowiedzi w dzienniku.
- [ ] **Step 2: Stan przed:** wersje tabletów stanowiska (Task 4 Step 3) ≥ progu; `SELECT COUNT(*) FROM prod_station_desk
  WHERE station_code = '<S>' AND postponed_at IS NULL` (stół) i `… IS NOT NULL` (odłożone) — liczby do dziennika.
- [ ] **Step 3: Przełączenie (Konrad „wykonaj”, przed zmianą albo w przerwie):** Konfiguracja → „Stół stanowisk” →
  tryb `<S>` = `stol` → zapis; restart wg Doprecyzowania 2. Kontrola: SQL-RO `config_value` klucza `priorytety_tryb_<S>`
  = `stol` i wpis logu `ustawienia`. Hala: tablety odświeżają stół (sygnał albo do 5 min).
- [ ] **Step 4: Obserwacja 2 dni robocze — dziennie, zapytania SQL-RO:**
  - stół: `SELECT COUNT(*) FROM prod_station_desk WHERE station_code='<S>' AND postponed_at IS NULL` ≤ K + doróbki
    na stole;
  - kafle nieaktualne (powinno być 0): dla jednostki `pozycja` — `SELECT d.id FROM prod_station_desk d JOIN prod_products p
    ON p.id = d.product_id WHERE d.station_code='<S>' AND p.current_status <> '<status oczekiwania S>'`; dla jednostki
    `zamowienie` (Formatowanie, Pakowanie — `product_id IS NULL`, więc JOIN po pozycji nic nie znajdzie) — `SELECT d.id
    FROM prod_station_desk d WHERE d.station_code='<S>' AND d.product_id IS NULL AND NOT EXISTS (SELECT 1 FROM
    prod_products p WHERE p.order_id = d.order_id AND p.current_status = '<status oczekiwania S>')`; dodatkowo zdublowane
    kafle: `SELECT unit_key, COUNT(*) FROM prod_station_desk WHERE station_code='<S>' GROUP BY unit_key HAVING COUNT(*) > 1`
    → pusto (UNIQUE i tak to wymusza — wynik niepusty = migracja nie założyła indeksu);
  - odłożenia: `SELECT reason, COUNT(*) FROM prod_priority_log WHERE action='odlozenie' AND station_code='<S>' AND
    created_at >= '<przełączenie>' GROUP BY reason`; otwarte odłożenia vs limit (10);
  - pusty stół przy niepustej kolejce: `GET /kolejka?stanowisko=<S>` `lacznie` > 0 a stół pusty dłużej niż 5 min → zgłoszenie;
  - log aplikacji: wzorzec „1213” (sekcja „Współbieżność”) → 0; liczba odpowiedzi 409 `nie_na_stole` z tabletów tego stanowiska
    (nowa appka ich nie powinna wywoływać; pojedyncze z kolejki offline po zamknięciu kafla na drugim tablecie są
    dopuszczalne); 500 z `/desk` → 0;
  - zgłoszenia hali (sekcja „Co zgłasza hala”).
  - **Formatowanie i Pakowanie dodatkowo:** sekcja „Niekompletne” na tablecie; zamówienie w „Niekompletne” dłużej niż
    1 dzień roboczy → zgłoszenie (rozrzut na Sklejaniu); Pakowanie: zamówienia bez sposobu dostawy nie wchodzą na stół —
    logistyk musi je ustawiać na bieżąco (spec 5.1).
  - **Krawędzie:** tablet w trybie mieszanym z Lakiernią na stałe (Doprecyzowanie 6) — Lakiernia lista bez bramki;
    sprawdzić, że ZAKOŃCZ z listy Lakierni na tym tablecie przechodzi (0 × 409) i że `GET /stations/painting/desk`
    nie jest wołane (w logu 0 × 409 `stanowisko_bez_stolu`).
- [ ] **Step 5: Bramka stanowiska** (dziennik): „zostaje `stol`” albo wycofanie (Task 7 Step 1). Kryterium zostania:
  0 × 1213, 0 kafli nieaktualnych, 0 × 500 z `/desk`, brak blokujących zgłoszeń hali, odłożenia z powodami (bez serii
  „inne” bez sensu — do oceny Konrada). Następne stanowisko — dopiero po wpisie.
- [ ] **Step 6: Po Pakowaniu:** data przełączenia ostatniego stanowiska = **start okna pomiaru** (Task 6). Commit dziennika:
  `docs(priorytety): K7 wszystkie stanowiska w trybie stol`.

### Task 6: Pomiar po 2 tygodniach i porównanie z symulacją

**Files:** Create `docs/superpowers/plans/raporty/<data>-priorytety-pomiar-po-p3.md` (`git add -f`).
**Interfaces (Consumes):** `scripts/symulacja_priorytetow.py` (opcje `:758-771`; `--drabina` przyjmuje `g<n>`,
`po_terminie`, `blisko_terminu`, `rozpoczete`, `trasy` albo `trasa:<id>` — `_drabina` `:275-285`).

- [ ] **Step 1: Warunek:** minęło ≥ 14 dni od przełączenia Pakowania bez wycofania żadnego stanowiska. Wycofanie w oknie
  → okno liczy się od ponownego przełączenia.
- [ ] **Step 2: Wejście z bazy (SQL-RO, wyniki do `/tmp` na serwerze, nie do repo):** CSV gwiazdek
  `SELECT internal_order_number, priority_stars FROM prod_orders WHERE priority_stars > 0 AND priority_rank IS NOT NULL`
  → `/tmp/gwiazdki-p3.csv` (`numer,gwiazdki`); lista `--drabina` z `SELECT kind, stars, tag, route_id FROM
  prod_priority_rungs ORDER BY position` (tylko trasy robocze/zatwierdzone; `stars` → `g<n>`, `tag` → nazwa, `route` →
  `trasa:<route_id>`).
- [ ] **Step 3: Uruchomienie** (jak symulacja 4.10, nagłówek symulacji: `sudo -u woodpower-crm`, bez `flask`):
  `venv/bin/python scripts/symulacja_priorytetow.py --core config/core.json --dni 14 --k 2 --blisko 3 --top 30
  --gwiazdki /tmp/gwiazdki-p3.csv --drabina "<lista>" --out /tmp/pomiar-p3.md --json /tmp/pomiar-p3.json`. `--k`
  i `--blisko` = aktualne ustawienia (jeśli Konrad je zmienił — wartości z Konfiguracji). Drugi przebieg `--dni 60`
  tylko do trendu (okno miesza okres przed i po).
- [ ] **Step 4: Odłożenia (skrypt ich nie liczy):** SQL-RO per stanowisko i powód z `prod_priority_log` (`odlozenie`,
  `odlozenie_zamkniete`) w oknie; udział odłożeń w zakończeniach = odłożenia / zdarzenia ZAKOŃCZ ze skryptu (sekcja 3.3);
  mediana czasu leżenia (para `odlozenie` → `odlozenie_zamkniete` po `order_id`, `product_id`, `station_code`).
- [ ] **Step 5: Porównanie** (tabela w pliku pomiaru), poziom odniesienia z symulacji A:

  | Miara | Dziś (symulacja 4.10, 60 dni) | Po P3 (14 dni) | Kryterium |
  |---|---|---|---|
  | Omijanie pilniejszych — % zakończeń, per stanowisko | Wycinanie 84, Składanie 88, Sklejanie 96, Formatowanie 96, Krawędzie 78, Lakiernia 71, Pakowanie 94 | | spadek na każdym stanowisku ze stołem (symulacja D7); resztę tłumaczą gwiazdki, trasy i grupy materiału — opisać. **Lakiernia:** bez kryterium — lista po wykończeniu omija rangę z założenia (grupy), pracownik wybiera sam; podać wartość informacyjnie |
  | …o ≥ 3 dni | 68 / 77 / 88 / 89 / 69 / 56 / 86 | | spadek |
  | Rozrzut przed Formatowaniem: mediana / p90 / >24 h / >72 h | 0,4 h / 70,8 h / 20 % / 10 % | | **p90 ≤ 70,8 h** i >24 h ≤ 20 % (symulacja D7: „nie może wzrosnąć”) |
  | Rozrzut przed Pakowaniem: mediana / p90 / >24 h / >72 h | 0,0 h / 28,8 h / 12 % / 7 % | | nie rośnie |
  | Zdarzenia liczników / dzień (wszystkie) | ok. 380 | | informacyjnie (sygnały) |
  | Odłożenia: udział w zakończeniach, powody, mediana leżenia | — (nie było) | | do oceny Konrada (spec 14 „raport odłożeń”) |
  | Formatowanie: niekompletne / czekające (sekcja 2 skryptu) | 6 / 29 | | informacyjnie |

- [ ] **Step 6: Wnioski** (w pliku pomiaru, po polsku, bez danych klientów — skrypt podaje tylko numery): czy kryteria
  spełnione; propozycje parametrów (próg „Blisko terminu”, K, limit) jako **pytania do Konrada**, nie zmiany.
  Przekroczone kryterium rozrzutu → meldunek do centrali (decyzja Konrada: miejsce tagu „Rozpoczęte”, K Sklejania).
  Commit: `docs(priorytety): pomiar po P3 skryptem symulacji`.

### Task 7: Wycofania — procedury (wykonywane tylko na decyzję Konrada)

**Files:** dziennik (wpis przy każdym użyciu). **Interfaces:** jak Task 4–5; `git revert -m 1`; `REALTIME.enabled`.

Wyzwalacze (każdy → meldunek do Konrada z rekomendacją, decyzja w dzienniku): hala nie może pracować na stanowisku
(pusty stół przy kolejce, ZAKOŃCZ odrzucane) → Step 1; problem na wielu stanowiskach albo z wersją appki → Step 2;
1213 bez ponowienia, `priorytety_utrwalone.success = false` w kolejnych cronach, masowe 500 w panelu/tabletach po P1 →
Step 3 (po analizie, Global Constraints „Eskalacja”); awaria brokera → Step 5.

- [ ] **Step 1: Wycofanie stanowiska (P3):** Konfiguracja → tryb `<S>` = `stary` → zapis + restart wg Doprecyzowania 2.
  Skutek: bramka ZAKOŃCZ znika, nowa appka dalej pokazuje stół i Odłóż (działają w `stary`, `test_desk_w_trybie_stary_dziala`),
  odłożenia zostają widoczne. Kontrola jak Task 5 Step 3. Ponowne przełączenie — od nowa Task 5 dla tego stanowiska.
- [ ] **Step 2: Wyłączenie bramki dla wszystkich tabletów naraz:** `priorytety_min_app_version_code` = `999999`
  (Doprecyzowanie 1; **nie 0**) + restart. Każdy tablet liczy się jako „stary”: pełna lista, ZAKOŃCZ bez bramki, ZAKOŃCZ
  zdejmuje kafel ze stołu, jeśli tam leżał (spec 5.5). Tryby stanowisk zostają `stol` — powrót = przywrócenie
  `<version_code>`. Też jako ratunek, gdy stara appka wróci na tablet (np. ręczna reinstalacja).
- [ ] **Step 3: Revert kodu P1** (spec 11): najpierw Step 1 dla wszystkich stanowisk w `stol` (albo Step 2), potem
  na gałęzi lokalnej z `main`: `git revert -m 1 <merge commit P1>` → PR do `main` (Konrad) → deploy: `flask migrate` bez
  pracy (migracja już wykonana), restart. Dane zostają (spec 11): kolumny i tabele, gwiazdki, szczeble, stół, log.
  Nowa appka bez `/desk` (404) przechodzi na listę (kontrakt K6 §12 — sprawdzone w odbiorze appki). Stary algorytm
  przelicza rangi przy następnej synchronizacji z Base., która utworzy pozycje (`sync_service.py:933`, `:3033`).
  Ponowne wdrożenie później = revert revertu + Task 1–3 od nowa (cron dopisze szczeble tras utworzonych w międzyczasie).
- [ ] **Step 4: Dane po revercie** (Doprecyzowanie 4; każde osobno na decyzję Konrada, poza godzinami pracy hali; najpierw
  SQL-RO `SELECT id` z tym samym `WHERE` (liczba do dziennika, lista id do zapisu), potem zapis po samych id:
  `UPDATE … WHERE id IN (<lista>) ORDER BY id` (sekcja „Współbieżność”). Wzorzec zapisu jak SQL-RO, ale **`with
  create_engine(url).begin() as c:`** zamiast `.connect()` i bez `READ ONLY` — na serwerze jest SQLAlchemy 1.4
  (`requirements.txt`: `<2.0`), gdzie zwykłe `Connection` nie ma `commit()` (AttributeError już po autocommicie UPDATE-u);
  `begin()` zatwierdza przy wyjściu z bloku albo cofa przy wyjątku. Kontrola: `result.rowcount` = liczba z `SELECT`):
  - doróbki w produkcji przed Formatowaniem odzyskują szczyt starej kolejki (odpowiednik `lock_priority(rank=1)`):
    `WHERE original_product_id IS NOT NULL AND current_status IN ('czeka_na_wyciecie','czeka_na_skladanie',
    'czeka_na_sklejanie')` → `UPDATE prod_products SET priority_rank = 1, priority_manual_override = 1, is_priority = 1
    WHERE id IN (<lista>) ORDER BY id` — listę statusów
    potwierdza centrala z kodem po revercie (`complete_task` zeruje doróbkę na Formatowaniu, `models.py:712-725`);
  - pomarańczowe ramki: zostawić (rekomendacja — biuro widzi zamówienia, które miały gwiazdki) albo
    `WHERE original_product_id IS NULL AND is_priority = 1 AND current_status IN (<7 statusów>)` → `UPDATE prod_products
    SET is_priority = 0 WHERE id IN (<lista>) ORDER BY id`.
- [ ] **Step 5: Realtime:** `REALTIME.enabled = false` w `core.json` + restart (README `:79-90`) — tablety zostają przy
  odpytywaniu (30 s pusty stół / 5 min pełny), agent druku wraca do odpytywania co 10 s (dotyczy też druku!). Broker bez
  zmian. Powrót: `true` + restart, publish testowy jak Task 3 Step 5.
- [ ] **Step 6:** każdy użyty krok → wpis w dzienniku (kto, kiedy, dlaczego, wynik kontroli) i w raporcie K7
  („Rozstrzygnięcia”). Revert P1 → centrala zatrzymuje K8.

### Task 8: Raport kroku

**Files:** Create `docs/superpowers/plans/raporty/2026-10-05-priorytety-krok-K7-raport.md` (`git add -f`). Raport może
powstawać etapami: wersja po części 1 (commit), uzupełniona po P3 i pomiarze (commit).

- [ ] **Step 1: Kontrola:** `git log origin/main --oneline -3` — ostatni commit `main` to merge P1 (albo późniejsze
  zmiany spoza programu — wypisać); żadnego commita K7 na `main`; `git diff <hash startu K7>..HEAD --name-only` na
  gałęzi roboczej → tylko dziennik, pomiar, raport (+ commit scalenia `main` z Task 1 Step 2).
- [ ] **Step 2: Raport** z sekcjami: **Zrobione** (po Taskach, z datami i godzinami), **Testy** (pełny pakiet po scaleniu
  `main`, blog_seo, migracja ×2 na kopii z czasami, cron na kopii, wyniki SQL kontrolnych bez danych klientów, odpowiedzi
  crona z produkcji bez danych klientów), **Odstępstwa od planu**, **Rozstrzygnięcia podjęte w trakcie** (numerowane;
  koszt, jeśli błędne; w tym każde użycie Task 7), **Pytania do Konrada**, **Stan gałęzi** (hash merge commita na `main`,
  hash gałęzi roboczej, czy wypchnięte), **Co następny krok musi wiedzieć**:
  - **K8:** data wdrożenia P1 i przełączenia każdego stanowiska; czy było jakiekolwiek wycofanie; czy na którymkolwiek
    tablecie zostało `last_app_version_code` < progu (stara appka) — jeśli tak, `REFRESH_INTERVAL_SECONDS` i lista
    `/stations/<kod>/orders` zostają; gałąź robocza po scaleniu ma commity dokumentów nieobecne na `main` (K8 zaczyna
    od `git merge origin/main`); stan pamięci podręcznej ustawień (Doprecyzowanie 2);
  - **centrala:** Doprecyzowania 1–11 do specu (8.6, 11, 13) kartą dokumentacyjną; wyniki pomiaru i pytania o parametry.
- [ ] **Step 3: Commit:** `docs(priorytety): raport kroku K7 wdrozenie i przelaczenie`; push gałęzi roboczej.

---

## Kryteria zakończenia (DoD)

**Część 1 (P1):**
1. Pełny pakiet po scaleniu `main` → gałąź: `0 failed`; blog_seo zielone; migracja ×2 na świeżej kopii produkcji
   (drugi przebieg: 0 migracji); cron na kopii 200 z `priorytety_utrwalone.success = true` i czasem < 20 s.
2. Centrifugo: namespace `station` na serwerze, publish testowy `{"result":{}}` przed scaleniem i po wdrożeniu.
3. `logs/deploy.log`: `[Migrations]   ✓ Sukces: 2026-10-05-priorytety-produkcji_…` przed `Restarting application...`,
   brak `[MIGRATION FAILED]`, `Deploy complete!`; `schema_migrations` ma migrację priorytetów z `success = 1`.
4. Ręczny cron po restarcie: HTTP 200, `szczeble_uzupelnione` = liczba tras roboczych/zatwierdzonych bez szczebla,
   `priorytety_utrwalone.success = true`; 9 szczebli stałych + 1 na każdą trasę roboczą/zatwierdzoną (żadna aktywna trasa
   bez szczebla — zapytanie z Task 3 Step 2).
5. Lista produkcyjna = kolejność `priority_rank` zamówień aktywnych (pierwsze 15 zgodne z SQL i `GET /kolejka`; rangi
   unikatowe wśród aktywnych, żadne aktywne bez rangi).
6. Stara appka: ZAKOŃCZ na każdym z 7 stanowisk w ciągu doby, 0 × 409 `nie_na_stole`; 1–2 dni: 0 × 1213 w logach,
   godzinny cron `success = true` (wzorzec „1213” z sekcji „Współbieżność”).

**Część 2 (P3):**
7. Każde aktywne urządzenie stanowisk produkcyjnych z `last_app_version_code ≥` progu; próg ustawiony przed pierwszym `stol`.
8. 6 stanowisk w `stol` (bez Lakierni, która zostaje `stary` — Decyzje 4), każde po bramce z 2 dni obserwacji wpisanej w dzienniku (0 × 1213, 0 kafli nieaktualnych,
   0 × 500 z `/desk`), albo udokumentowane wycofanie z decyzją Konrada.
9. Plik pomiaru z tabelą porównania; kryterium rozrzutu przed Formatowaniem oceniony (spełniony albo meldunek).
10. Raport K7 zacommitowany na gałęzi roboczej; `main` zawiera tylko merge P1 (i ewentualny revert); żadnych danych
    klientów, sekretów ani adresów IP w commitach (grep raportu, dziennika i pomiaru po `api_key`, `@`, `token`).

## Poza zakresem

- Jakiekolwiek zmiany w kodzie, testach, migracjach, `deploy.sh`, `CLAUDE.md`, specu (→ karty naprawcze i dokumentacyjne
  centrali). Także drobne poprawki zauważone na produkcji — do raportu.
- Wdrożenie logistyki i jej ręczne kroki (osobny runbook logistyki; tu tylko warunek wejścia).
- Kod appki, jej testy i budowa APK (sesja appki z karty K6). Instalacja ręczna na tablecie, który się nie zaktualizował.
- Zmiana parametrów (K, limit, próg, drabina) inaczej niż na decyzję Konrada; raport odłożeń jako funkcja panelu (spec 14).
- K8: DROP kolumn i tabel, usunięcie `priority_service.py`, `REFRESH_INTERVAL_SECONDS`, listy `/orders`.
- Konfiguracja serwera poza sprawdzeniem (nginx, supervisor, Centrifugo) — gdyby trzeba było ją zmienić (np. namespace
  `station`), robi to Konrad wg `ops/centrifugo/README.md`, wpis do dziennika.

## Ryzyka i co robić przy blokadzie

| # | Ryzyko | Objaw | Co robić |
|---|---|---|---|
| R1 | Konflikty przy scaleniu `main` → gałąź (logistyka poprawiana po etapie 4 w tych samych plikach: `routes.py`, `cron_api.py`, `mobile_api.py`, `with_idempotency`) | `git merge` z konfliktami | `git merge --abort`, STOP, karta naprawcza „scalenie + testy” (Fable 5.1, extra — pliki z blokadami); K7 wraca do Task 1 Step 2 |
| R2 | Migracja pada na produkcji mimo próby na kopii (dane inne niż kopia, uprawnienia `ALTER`) | `[MIGRATION FAILED]` | Task 2 Step 5; nie restartować; decyzja Konrada (karta naprawcza albo revert na `main`) |
| R3 | Pierwszy cron po wdrożeniu przekracza 30 s (pierwsze nadanie rang wszystkim zamówieniom) | 502/timeout w `cron_endpoint.sh`, w logu przerwany worker | `utrwal()` commituje raz — przerwanie = rollback; zmierzone w Task 1 Step 6, więc zaskoczenie = STOP i meldunek; godzinny cron powtórzy |
| R4 | Brak namespace `station` albo `REALTIME` wyłączone | publish → błąd; po P1 seria alertów Sentry `subsystem: realtime` przy każdym ZAKOŃCZ | sprawdzone przed scaleniem (Task 1 Step 7); po fakcie: dopisanie namespace przez Konrada albo `REALTIME.enabled=false` (Task 7 Step 5 — uwaga: dotyczy też agenta druku) |
| R5 | Pamięć podręczna ustawień 60 min na proces | po przełączeniu część żądań w starym trybie (bramka raz jest, raz nie) | Doprecyzowanie 2: restart razem z zapisem; jeśli K2/K5 to naprawiły — bez restartu |
| R6 | Tablet bez heartbeatu nowej wersji przy progu > 0 | tablet traktowany jako stary: pełna lista, ZAKOŃCZ bez bramki — niespójność z drugim tabletem | stanowisko nie przechodzi na `stol`, dopóki wszystkie jego tablety nie mają nowej wersji (Task 4 Step 3, Task 5 Step 2) |
| R7 | Formatowanie stoi na niekompletnych zamówieniach (bramka nie przepuszcza pozycji z „Niekompletne”, K6 R1) | 409 `nie_na_stole` przy ZAKOŃCZ pozycji z sekcji „Niekompletne” | warunek Task 4 Step 1; jeśli mimo to — Task 7 Step 1 dla Formatowania, karta naprawcza K3 |
| R8 | Pakowanie bez sposobu dostawy | stół Pakowania pusty, kolejka pełna | spec 5.1 (świadomie); przed przełączeniem pytanie C5; logistyk ustawia sposoby; to nie jest powód wycofania |
| R9 | Rozrzut przed Formatowaniem rośnie (grupowanie po materiale) | p90 > 70,8 h w pomiarze, zgłoszenia „Niekompletne” | meldunek; decyzja Konrada: tag „Rozpoczęte” wyżej na drabinie (panel, bez kodu) albo K Sklejania; bloki po N odrzucone (spec 14) — nie wracać bez nowych danych |
| R10 | MySQL 1213 na produkcji | wpis w logu, 500 na tablecie/panelu | `SHOW ENGINE INNODB STATUS` (bez danych klientów) → analiza na Fable 5.1, max (podręcznik 4a p. 3); do czasu analizy — wycofanie stanowiska, którego dotyczy (Task 7 Step 1), bez zmian kodu |
| R11 | Dane klientów w raporcie/pomiarze | nazwy, adresy w zapytaniach albo zrzutach | zapytania wyłącznie id/numery/liczby; grep przed commitem (DoD 10); przy wątpliwości — STOP przed commitem |
| R12 | Drugi push do `main` w trakcie deployu | `Already deploying, skipping.` | odczekać `Deploy complete!`, ponowić (Task 2 Step 4) |

**STOP** = zatrzymanie runbooka w bieżącym punkcie, stan produkcji opisany w dzienniku (co już wykonane, co nie), meldunek
do Konrada z rekomendacją, bez obejść i bez zmian kodu. Produkcja ma zostać w stanie spójnym: albo stary kod na starym
schemacie, albo nowy kod po migracji, nigdy pośrodku.

## Pytania do Konrada

**A. Blokujące start K7 (przed Task 1):**
1. **Termin części 1:** ile dni stabilnej pracy logistyki etapów 1–4 na produkcji przed P1 i o której scalamy —
   rekomendacja: ≥ 3 dni robocze logistyki bez 1213 i bez otwartych zgłoszeń; scalenie po zakończeniu pracy hali.
2. **Kto wykonuje polecenia na serwerze** — rekomendacja: odczyty (logi, SQL-RO, `supervisorctl status`) sesja sama
   przez ssh; zapisy (push `main`, ręczny cron, Konfiguracja, restart, SQL wycofania) Konrad albo sesja na „wykonaj”
   dla konkretnego punktu.
3. **Sposób scalenia:** PR z merge commitem (Doprecyzowanie 3) — rekomendacja: tak, nie squash.
4. **Kopia produkcji lokalnie** (Task 1 Step 5): zgoda na zrzut przez ssh do kontenera `db` z wyczyszczonymi kluczami
   zewnętrznymi w konfiguracji testowej — rekomendacja: tak, jak przy etapie 3 logistyki.

**B. Przed scaleniem (Task 2 Step 1):** (1) potwierdzenie „scal teraz”; (2) treść komunikatu do biura (gwiazdki dla
wszystkich z modułem produkcji, nie tylko admina — spec 7.3) i do hali; (3) czy ktoś z hali będzie na zmianie po
restarcie do testu ZAKOŃCZ starą appką (Task 3 Step 4); (4) zgoda na restart wg Doprecyzowania 2 przy każdej zmianie
ustawień w P3, jeśli pamięć podręczna nie jest naprawiona.

**C. Przed każdym przełączeniem stanowiska (Task 5 Step 1):**
1. Wszystkie tablety stanowiska mają nową wersję (lista z SQL) — potwierdzasz?
2. Hala tego stanowiska przeszkolona: stół, Odłóż z powodem, limit 10, „inne” wymaga notatki?
3. Godzina przełączenia — rekomendacja: przed rozpoczęciem zmiany.
4. K i limit odłożeń dla tego stanowiska zostają domyślne (2 / 10)?
5. Pakowanie: czy logistyk ustawia sposoby dostawy na bieżąco (bez nich zamówienie nie wejdzie na stół)?
   Formatowanie: czy sekcja „Niekompletne” do K zamówień jest akceptowana (P-9)? Krawędzie/Lakiernia: czy Lakiernia ma
   własny tablet, czy tylko tablet Krawędzi (tryb mieszany na stałe, Doprecyzowanie 6)? Czy hala Krawędzi wie, że po
   przełączeniu ekran Krawędzi to stół, a ekran Lakierni dalej lista (bez Odłóż)?
6. Po 2 dniach: zostaje `stol` i idziemy dalej, przedłużamy obserwację, czy wycofujemy?

**D. Po pomiarze (Task 6, nieblokujące):** progi oceny omijania (symulacja D7 mówi „spadek do poziomu odłożeń z powodem”
— czy wystarczy spadek, czy konkretny próg); korekty parametrów; zgoda na K8 po 2–3 tygodniach P3.

### Co zgłasza hala (przekazuje kierownik hali Konradowi, Konrad centrali — z godziną i stanowiskiem)

- P1 (stara appka): lista się nie wczytuje albo jest pusta; ZAKOŃCZ nie przechodzi; komunikat „nie leży na stole”.
- P3: dwa tablety jednego stanowiska pokazują różny stół dłużej niż minutę; pusty stół, a „w kolejce” > 0; ZAKOŃCZ albo
  licznik odrzucany na kaflu ze stołu; Odłóż zablokowane limitem (ile razy dziennie); na Formatowaniu/Pakowaniu
  zamówienie dłużej niż dzień w „Niekompletne”; kafel, którego nie da się zrobić (materiał, maszyna) — przez Odłóż
  z powodem, nie ustnie; brak sygnału (stół odświeża się dopiero po kilku minutach).
- Zawsze: każde „nie da się pracować” → natychmiast telefonicznie do Konrada (wycofanie stanowiska, Task 7 Step 1).
