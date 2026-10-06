# Raport — pakiet wdrożenia i wycofania (8.10.2026), program „Priorytety produkcji”

- **Data:** 2026-10-05 wieczór → 2026-10-06 noc
- **Sesja:** lokalna (Windows). **Model: Opus 5.5, nie Fable 5.1 z karty** (zgłoszone na starcie sesji). Effort
  extra, bez trybu szybkiego.
- **Karta:** „pakiet wdrożenia i wycofania (8.10.2026)”, rozstrzygnięcia 20, 23, 24 dziennika centrali
- **Stan wejściowy (sprawdzony):** `origin/main` = `31a0b014`; serwer produkcyjny `git rev-parse HEAD` =
  `31a0b0145b222799234674bdf1e995dab6791a0c` (ssh, tylko odczyt) = `origin/main`; `origin/claude/priorytety-produkcji`
  = `581c3651`

## Zrobione

| Krok | Co | Wynik |
|---|---|---|
| 0 | terminy 10 / 14 w bazie i jako wartości awaryjne (TDD) | `05b7f767` na `claude/priorytety-produkcji`; 6831 passed |
| 1 | gałąź wdrożeniowa = `git merge --squash` na `main` | `5e944a55` na `claude/wdrozenie-2026-10-08`; 6855 passed, blog_seo 89 |
| 2 | gałąź wycofania = revert squasha + migracja cofająca (TDD) | `8e14937e` na `claude/wycofanie-2026-10-08` |
| 3 | próba a–e na świeżej kopii produkcji (`priorytety_wdrozenie`) | wycofanie: 0 × 500 i 0 × `LookupError` ponad punkt odniesienia; ponowne wdrożenie czyste |
| 4 | wejście do runbooka K7 | sekcja na końcu |

`main` nietknięty, bez `--force`. Pushe: `claude/priorytety-produkcji` (krok 0 i ten raport, przez rebase),
`claude/wdrozenie-2026-10-08`, `claude/wycofanie-2026-10-08`.

## Hashe

| Co | Hash |
|---|---|
| `main` / produkcja (stan wejściowy) | `31a0b0145b222799234674bdf1e995dab6791a0c` |
| krok 0 (terminy) na `claude/priorytety-produkcji` — podstawa squasha | `05b7f7672a2e91aad8df5a72e7579cdfb977fd24` |
| **squash — `claude/wdrozenie-2026-10-08`** (rodzic: `31a0b014`) | **`5e944a55978f659ca38a69d09d74b50a5a4d841e`** (drzewo `47680110`) |
| revert squasha | `ca5ac6b1` |
| **wycofanie — `claude/wycofanie-2026-10-08`** (revert + migracja; rodzic: squash) | **`8e14937e8497fdf9a27c5ba0db97e739b9057ccc`** |

Drzewo `ca5ac6b1` = drzewo `main` @ `31a0b014` (`git diff origin/main ca5ac6b1` puste). `8e14937e` dokłada wyłącznie
`migrations/2026-10-08-wycofanie-logistyki.sql` i `tests/test_migracja_wycofanie_logistyki.py`.

## Terminy (krok 0)

- `migrations/2026-10-07-terminy-w-bazie.sql`: jedno `INSERT IGNORE` dwóch wierszy `prod_config` —
  `DEADLINE_DEFAULT_DAYS` = `10`, `DEADLINE_FINISHED_DAYS` = `14`, typ `integer` (kształt jak istniejący wiersz
  `DEADLINE_DEFAULT_DAYS` na kopii produkcji: `config_value` tekst, `config_type` `integer`). Istniejących wierszy nie
  nadpisuje. Nazwa po wszystkich migracjach gałęzi (runner `sorted()` po nazwie).
- Wartości awaryjne 10 / 14: `config_service._default_values`, `sync_service._calculate_deadline_date` (oba odczyty
  i gałąź wyjątku), `priorytety/stale.py` (`TERMIN_SUROWE_DNI`, `TERMIN_WYKONCZONE_DNI` — z nich czyta
  `ustawienia.termin_*`); opis „domyślnie: 10 / 14 dni” w karcie „Terminy” Konfiguracji.
- TDD: najpierw czerwone (27.10 zamiast 19.10), potem zielone. Nowe testy: `tests/test_migracja_terminy_w_bazie.py`
  (nazwa i kolejność, bez `DELIMITER`, jedno `INSERT IGNORE` 10/14 bez `UPDATE`/`DELETE`/`REPLACE`, wykonanie na
  SQLite: brakujący wiersz zakłada, istniejący zostaje, drugi przebieg bez zmian) i 3 testy w
  `tests/test_priorytety_terminy.py` (wartości awaryjne w trzech miejscach; awaria konfiguracji przy imporcie → 10 / 14;
  wartości z bazy wygrywają); zaktualizowane oczekiwania 16/21 → 10/14 w dwóch plikach.
- **MySQL ×2** (tymczasowa baza z kopią `prod_config` produkcji): 1. przebieg — 1 wiersz wstawiony
  (`DEADLINE_FINISHED_DAYS` = 14), 1 duplikat (istniejące 10 nietknięte); 2. przebieg — 0 wierszy. Na kopii po
  wdrożeniu: `DEADLINE_DEFAULT_DAYS` 10, `DEADLINE_FINISHED_DAYS` 14, `DEADLINE_DAY_TYPE` robocze.
- Pełny pakiet po kroku 0: **6831 passed, 3 skipped, 0 failed** (7 min 10 s; 6824 + 7 nowych).
- Skutek dla starego kodu: `main` czyta te same wiersze — po ewentualnym wycofaniu terminy zostają 10 / 14
  (pożądane, karta). Od wdrożenia zamówienia z wykończeniem dostają 14 dni zamiast dzisiejszych 21 (decyzja 5.10).

## Kontrole squasha

| Kontrola | Wynik |
|---|---|
| sposób | `git merge --squash origin/claude/priorytety-produkcji` na worktree od `origin/main`, jeden commit, rodzic `31a0b014` |
| konflikty | brak (auto-merge `modules/production/templates/components/reports/mix.html`) |
| `git diff --stat` squash ↔ `origin/claude/priorytety-produkcji` | **24 pliki**, lista identyczna z `git diff --name-only <merge-base> origin/main` (5 commitów: `c2b312f0`, `b910b07b`, `a71af794`, `0310b6a7`, `31a0b014`) |
| `docs/superpowers` | zostają w drzewie (decyzja 4.10) |
| zamówienie 1450 | identyfikator Base. z kopii produkcji i pola danych osobowych tego zamówienia (każde pole i każde słowo ≥ 5 znaków): **0 trafień w drzewie squasha**; historia gałęzi wdrożeniowej to jeden commit na `main` — historia logistyki do `main` nie wchodzi. Uwaga w „Odstępstwach” p. 3 |
| pełny pakiet na drzewie squasha | **6855 passed, 3 skipped, 0 failed** (7 min 21 s) |
| `integrations/blog_seo` | **89 passed** |
| składnia Python 3.9 | `ast.parse(..., feature_version=(3, 9))` dla 232 plików `.py` zmienionych względem `main`: 0 błędów |

## Migracja cofająca (`migrations/2026-10-08-wycofanie-logistyki.sql`)

Wykonuje ją **stary kod** (runner z `main` — identyczny jak na gałęzi) przy deployu gałęzi wycofania, przed
restartem. Same dane; ENUM-y, kolumny i tabele zostają. Każdy zapis przez `PREPARE` po sprawdzeniu
`information_schema` (baza bez tabel/kolumn logistyki → komunikat „pomijam”, nie błąd 1146/1054 blokujący deploy).
Bez `DELIMITER`, bez parametrów `:nazwa` (runner woła `db.text`). 44 polecenia.

| # | Przepis | Źródło |
|---|---|---|
| 1 | `prod_products.current_status` `zweryfikowane`/`zaladowane`/`dostarczone` → `spakowane` | spec etapu 4 (`2026-09-30-…`), sekcja 14 pkt 3 |
| 1b | `DELETE` wiersza `prod_config` `logistyka_wydane_dostarczone` | sekcja 14 pkt 3 |
| 2 | U10: `prod_route_stops.not_delivered_*` → NULL | sekcja 14 pkt 6.2 |
| 2b | log `niedostarczenie_cofniete` → `trasa_status` z notatką `cofniete niedostarczenie: …` | sekcja 14 pkt 6.2 |
| 3 | `prod_routes.status` `zaladowana`/`w_trasie` → `zatwierdzona` | sekcja 14 pkt 4 |
| 3b | log Dostawy (`zaladunek`, `zostaje`, `wyjazd`, `dostarczone`, `niedostarczone`, `dostarczenie_cofniete`) → `trasa_status` | sekcja 14 pkt 4 |
| 4 | oczekujące zadania drukarki paczek (`printer <> 'etykiety'` albo `package_id`) → `expired` | **znalezisko** (audyt próby): stary `GET /api/print-agent/jobs` nie filtruje drukarki — etykiety 100×150 poszłyby na drukarkę 60×40 |
| 5a | opcjonalnie: przywrócenie `priority_rank`, `priority_manual_override`, `is_priority` z kopii `zz_przed_wdrozeniem_2026_10_08_priorytety` (jeśli istnieje) dla pozycji jeszcze w produkcji | **znalezisko**: nowy kod nadpisuje ręczne flagi i blokady (spec priorytetów 8.5); kopia — krok runbooka K7, patrz „Pytania” 1 |
| 5b | doróbki przed Formatowaniem → ranga 1, blokada, `is_priority` (jak `lock_priority(1)` starego `rework_service`) | **znalezisko**: nowy kod daje doróbce rangę 0 bez blokady, a stare przeliczenie pomija tylko zablokowane — doróbki straciłyby szczyt kolejki |

**Etapy 1–3 logistyki — przepisów nie ma i nie trzeba:** spec etapów 1–3 nie ma sekcji wycofania. Migracja etapu 1
przenosi `czeka_na_logistyke` → `czeka_na_pakowanie` (stary kod zna oba), zamyka historię kolumną, której stary kod
nie czyta; `override_delivery_method = 'odbior_osobisty'` stary kod obsługuje bez wyjątku (`is_personal_pickup`
z tekstu `delivery_method`, fallback statusu — audyt); trasy, flota, geolokalizacja to nowe tabele.

**Priorytety (spec 11) — tabele i kolumny zostają; stary kod nie zależy od niczego, co rzuca wyjątkiem:** nowe
wiersze `prod_config` mają typy `string`/`integer` z poprawnymi wartościami (stary `config_service` je parsuje);
żadnych zmian ENUM na tabelach starego kodu poza `current_status`; nowe kolumny NOT NULL mają DEFAULT (INSERT-y starego
ORM przechodzą — sprawdzone ZAKOŃCZ i hurtem statusów); wiersze terminów 10/14 stary kod czyta (pożądane). Rangi
pozycji (×100, doróbki 0) — stare przeliczenie przy imporcie numeruje je od nowa 1…N z zachowaniem blokad
(zmierzone: 594 pozycje, 594 unikatowe rangi, blokada doróbki zachowana).

**Testy:** `tests/test_migracja_wycofanie_logistyki.py` (10 testów: nazwa ostatnia w katalogu i po
`2026-10-07-terminy-w-bazie.sql`, bez zmian schematu, bez parametrów wiązanych, każdy zapis przez `PREPARE`, każdy
przepis obecny dosłownie) — czerwone przed plikiem, zielone po; z `tests/test_migration_service.py` 25 passed.
Pełny pakiet drzewa wycofania (= `main` + test): **4110 passed, 3 skipped, 0 failed** (3 min 15 s).

**Co migracja świadomie zostawia** (audyt, bez 500): `override_delivery_method` (potrzebne przy ponownym wdrożeniu),
urządzenia `verification`/`delivery` (stary kod ich nie obsłuży — rejestracja 400, reszta pomija), otwarte sesje
pracowników na tych stanowiskach, nazwy „Planowana trasa” w `sales_orders`/`baselinker_reports_orders` (stary kod
czyta przez `.get`), wiersze stołu, gwiazdki, szczeble, log priorytetów.

## Próba na kopii produkcji (a–e)

Środowisko (poza repo, `C:/Users/Grafik/Documents/woodpower-podglady/priorytety/wdrozenie/`): zrzut produkcji
`mysqldump --single-transaction --routines --no-tablespaces` (bez danych `user_sessions`, `public_sessions`;
schemat tak) z 5.10 23:49, 63 MB; baza `priorytety_wdrozenie` w `woodpower-crm-db-1` (kolacja `utf8mb4_general_ci`
jak na produkcji; 85 tabel, 1912 zamówień, 4396 pozycji, 57 wpisów `schema_migrations`); kontener `wdrozenie-proba`
(obraz `logistyka3-app`, 127.0.0.1:5007, Flask) z kodem z `git archive` każdej wersji; konfiguracja
`przygotuj_config_wdrozenie.py` (bez klucza Base., poczty, Sentry, ORS, GlobKurier, AI; losowe klucze; REALTIME
wyłączony; własne nazwy ciasteczek); zaślepione hosty Base., ORS, GUGiK, Nominatim, GlobKurier, Sentry.
Narzędzia: `narzedzia/wdr_smoke.py` — **każda trasa GET z `url_map`** danej wersji kodu (685–798 adresów) jako
zalogowany admin (sesja bez hasła, `login_user` w kontekście żądania) albo z tokenem urządzenia stanowiska, parametry
z `wdr_parametry.py` (pozycje z każdego statusu + wszystkie z kroku c); zapis 500 i `LookupError` z wyjątków
i logu. `wdr_migracja.py` — `create_app()` z opakowanym `execute_sql_migration` (pomiar per plik).

### a) `main` @ `31a0b014` na kopii — punkt odniesienia

Start bez migracji („Brak nowych migracji”). Przegląd: 685 adresów — 450 × 200, 33 × 500, 0 × `LookupError`.
**Wszystkie 33 × 500 są zastane i wspólne dla wszystkich wersji kodu:** 30 × `/baselinker/api/order/<id>/packages`
i `/baselinker/api/courier/list` (brak klucza Base. w kopii), `/settings/logs` i `/settings/prices`
(`TemplateNotFound` — szablonów nie ma w `git archive`).

### b) gałąź wdrożeniowa — migracje, cron, kontrole

Migracje jak `deploy.sh` (nowy kod migruje, stary serwer jeszcze działa), dwa niezależne przebiegi na świeżej kopii:

| Migracja | Poleceń | Przebieg 1 | Przebieg 2 |
|---|---|---|---|
| `2026-09-25-logistyka-sposob-dostawy.sql` | 49 | 0,549 s | 0,520 s |
| `2026-09-26-logistyka-geolokalizacja.sql` | 3 | 0,063 s | 0,141 s |
| `2026-09-26-logistyka-zmiana-adresu.sql` | 6 | 0,051 s | 0,043 s |
| `2026-09-27-logistyka-trasy-flota.sql` | 4 | 0,206 s | 0,195 s |
| `2026-09-28-logistyka-kierowcy.sql` | 5 | 0,038 s | 0,039 s |
| `2026-09-30-druk-dwie-drukarki.sql` | 15 | 0,118 s | 0,121 s |
| `2026-09-30-druk-klucze-przesuniecia.sql` | 1 | 0,014 s | 0,014 s |
| `2026-09-30-logistyka-paczki-blokada.sql` | 1 | 0,008 s | 0,005 s |
| `2026-09-30-logistyka-paczki.sql` | 23 | 0,914 s | 0,836 s |
| `2026-09-30-logistyka-weryfikacja.sql` | 48 | 1,999 s | 1,802 s |
| `2026-10-01-analiza-planowana-trasa.sql` | 1 | 0,008 s | 0,028 s |
| `2026-10-01-logistyka-dostawa.sql` | 42 | 1,581 s | 1,019 s |
| `2026-10-02-logistyka-niedostarczone-na-trasie.sql` | 26 | 0,582 s | 0,418 s |
| `2026-10-02-raport-planowana-trasa.sql` | 5 | 0,056 s | 0,168 s |
| `2026-10-05-priorytety-produkcji.sql` | 36 | 0,791 s | 0,459 s |
| `2026-10-06-priorytety-stol-zrodlo.sql` | 11 | 0,483 s | 0,220 s |
| `2026-10-07-terminy-w-bazie.sql` | 1 | 0,007 s | 0,006 s |
| **razem** | **277, 0 porażek** | **7,47 s** | **6,03 s** |

Czasy ok. 3× dłuższe niż w K5 (2,2 s) — w obu przebiegach równolegle szedł pełny pakiet testów na tym samym
Dockerze; na produkcji spodziewać się wartości bliższych K5. Cały `create_app()` z migracjami: 11,7–13,2 s.
Kolejne `flask migrate` ×2: „Wykonano 0 migracji”.

Restart na nowym kodzie: „Brak nowych migracji”. **Terminy:** `DEADLINE_DEFAULT_DAYS` 10, `DEADLINE_FINISHED_DAYS`
14, `DEADLINE_DAY_TYPE` robocze. **Ręczny cron** (`POST /production/api/logistics/cron`, nagłówek sekretu): 200
w 0,77–0,83 s, `priorytety_utrwalone.success: true`, 253 zamówienia / 606 pozycji, wszystkie zmienione,
`duration_seconds` 0,51; `szczeble_uzupelnione: 0`, `wydane_dostarczone: 0`; drugi przebieg 0,09 s, 0 zmian.
**Kontrole SQL z K5 B3:** 9 szczebli w kolejności ★5, po terminie, ★4, blisko terminu, rozpoczęte, ★3…★0; 37 kluczy
`priorytety_*` + `DEADLINE_DAY_TYPE`; zamówienia aktywne 253, rangi unikatowe 253, bez rangi 0; wszystkie
`priorytety_tryb_*` = `stary`, `priorytety_min_app_version_code` = 0; `prod_station_desk` pusty. Przegląd nowego
kodu: 729 adresów, 478 × 200, te same 33 zastane × 500, 0 × `LookupError`.

### c) dane w każdym nowym stanie (prawdziwe API nowego kodu)

`narzedzia/wdr_stany.py` (+ `wdr_stany_dod.py`), 59 żądań, wszystkie 200/201. Na 7 prawdziwych zamówieniach
z kopii, których pozycje czekały na pakowanie: sposób dostawy z panelu (kurier ×1, transport ×5, odbiór ×1) → ZAKOŃCZ
pakowania z tabletu → deklaracja paczek → Weryfikacja (`verify-all`, telefon `verification`) → „Wydane klientowi”
(odbiór) → 2 pojazdy, 2 kierowców, trasy R1 i R2 (zatwierdzone) → załadunek z telefonu `delivery` → „Zakończ
załadunek” R1 → „Zostaje” jednego przystanku R2 → „Zakończ załadunek” i „Ruszam” R2 → „Dostarczone”,
„Niedostarczone” + „Cofnij niedostarczenie” (U10), drugie „Niedostarczone” (wisi), „Cofnij dostarczenie” z panelu
i ponowne „Dostarczone”; gwiazdki (★5 ×1, ★3 ×2), „Przygotuj stoły”, „Włącz stoły” dla Sklejania (próg 44), `desk`
tabletu Sklejania, „Odłóż”, „Wyślij na stanowisko”. Stan bazy przed wycofaniem:

| Stan | Liczba |
|---|---|
| pozycje `zweryfikowane` / `zaladowane` / `dostarczone` | 2 / 5 / 4 |
| trasy `zaladowana` / `w_trasie` | 1 / 1 |
| log logistyki: `zaladunek` 4, `zostaje` 1, `wyjazd` 3, `dostarczone` 2, `niedostarczone` 2, `dostarczenie_cofniete` 1, `niedostarczenie_cofniete` 1 (+ `paczki` 7, `weryfikacja` 6, `wydane`, `sposob_dostawy`, `trasa_*`) | 14 akcji Dostawy/U10 |
| przystanek z `not_delivered_at` (U10, wisi) | 1 |
| `logistyka_wydane_dostarczone` w `prod_config` | 1 |
| zadania drukarki paczek `pending` (`printer` = `wysylka`) | 7 |
| stół: Sklejanie `start` 3 + odłożony 1, `biuro` 1; Formatowanie `start` 9 | 14 wierszy |
| log priorytetów: `gwiazdki` 3, `szczebel` 2, `start_stolow` 6, `ustawienia` 2, `odlozenie` 1, `wyslanie` 1 | |
| szczeble tras | 2 |
| `override_delivery_method` = `odbior_osobisty` | 1 |
| urządzenia `verification` / `delivery` | 1 / 1 |
| doróbka bez blokady (nowy kod) | 1 |

Przegląd nowego kodu na tych danych: 798 adresów, 546 × 200, 33 zastane × 500, 0 × `LookupError`. Migawka bazy
„stan c” do powtórek d.

### d) gałąź wycofania na stanie c — migracja cofająca i stary kod

**d1 (bez kopii priorytetów — wariant domyślny):** migracja cofająca jak w `deploy.sh` (kod wycofania migruje,
serwer jeszcze na nowym kodzie): **1 plik, 44 polecenia, 0,026 s, 0 porażek**; `flask migrate` ×2 → 0. Liczniki po:
pozycje w nowych statusach 0, trasy w nowych statusach 0, akcje Dostawy/U10 w logu 0, U10 wiszące 0, znacznik
wydanych 0, zadania drukarki paczek `pending` 0, doróbki bez blokady 0 (stół 14 wierszy i `is_priority` 19 zostają —
stary kod ich nie czyta / czyta bez błędu). Restart na starym kodzie („Brak nowych migracji”). **Drugi, ręczny
przebieg pliku** (`mysql … source`, jak w runbooku po restarcie): 81 × „0 rows affected”, 0 błędów.

**Stary kod po wycofaniu — przegląd:** 748 adresów (wszystkie trasy GET starego kodu + pozycje i zamówienia z kroku
c), **514 × 200, 33 × 500 — dokładnie te same zastane co w a), 0 × `LookupError`** (także 0 w logu serwera). Wybrane
grupy (a / bez migracji / d1):

| Adres | a) `main` | stary kod na stanie c **bez** migracji | d1) po migracji |
|---|---|---|---|
| `/production/` (lista produkcji) | 200 | 200 | 200 |
| `/production/api/products-tab-content` (lista, zakładka) | 200 | **500** | 200 |
| `/production/api/products-tab-content?view=archive&page=1…5` (archiwum) | — | — | 200 ×5 |
| `/production/api/products-filtered?status=spakowane|czeka_na_pakowanie|all`, `?search=<nr Base.>` ×5 | — | — | 200 ×8 |
| `/production/api/products/<id>/order-products` (szczegóły zamówienia) | 200 | **500** (pozycje z kroku c) | 200 ×58 |
| `/production/api/dashboard*` | 200/302 | **500** | 200/302 |
| `/production/api/reports/deadline-progress` (raport terminów) | 200 | **500** | 200 |
| `/production/stations/<kod>` (panele stanowisk) | 200/308 | **500** | 200/308 |
| `/production/stations/monitor`, `/ajax/monitor` (monitory hali) | 200 | **500** | 200 |
| `/api/mobile/stations/<kod>/orders` ×7 (lista tabletu) | 200 | 200 | 200 |
| `/api/mobile/stations/<kod>/summary` ×7, `/orders/since` ×7 | 200 | 200 | 200 |
| `/api/mobile/orders/search?q=<nr Base.>` ×15 (wyszukiwarka tabletu) | 200/400 | **500** | 200/400 |
| `/api/mobile/orders/<id>` ×30 (szczegóły pozycji) | 200 | **500** | 200 |
| `/reports/`, `/reports/api/*` (stary raport) | 200/400 | 200/400 | 200/400 |
| `/reports/analiza` (Analiza sprzedażowa) | 200 | 200 | 200 |
| `/dashboard/` | 200 | 200 | 200 |

**Kontrola negatywna** (stary kod na stanie c bez migracji cofającej): 141 × 500, z czego **108 z `LookupError`** na
15 końcówkach — przegląd łapie dokładnie skutek opisany w sekcji 14 specu etapu 4, a migracja go usuwa.

**Zapisy starego kodu po wycofaniu** (`wdr_zapisy_stary.py`): `GET /api/print-agent/jobs` — 200, 0 zadań (żadnej
etykiety paczki); przeliczenie priorytetów tak, jak robi je stary import z Base. (`recalculate_all_priorities`) —
rangi 1…594 unikatowe, blokada doróbki zachowana; ZAKOŃCZ ze starego API na Sklejaniu (200, → `czeka_na_formatowanie`)
i Pakowaniu (200, → `spakowane`); hurtowa zmiana statusu pozycji z trasy `spakowane` → `czeka_na_pakowanie` →
`spakowane` (200, 200). **Uwaga do runbooka:** stary `POST /production/api/recalculate-all-priorities` (z
`confirm_reset`) **zdejmuje wszystkie blokady**, także przywróconych doróbek — w UI nie jest podpięty, ale nie
wolno go wołać po wycofaniu.

**Nowa appka 1.8.0 na starym backendzie (kontrakt §12) — sprawdzone na starym kodzie:** `GET
/api/mobile/stations/gluing/desk` → 404 `text/html`, `GET /api/mobile/realtime-token` → 404 `text/html`, `PUT
/api/mobile/orders/<n>/packages` → 404 `text/html`, lista `/stations/gluing/orders` → 200 JSON, rejestracja telefonu
`delivery` → 400 `invalid_station_code` — dokładnie przypadki tabeli §12 („appka działa jak 1.7.3”).

**d2 (z kopią priorytetów sprzed wdrożenia):** stan c + tabela `zz_przed_wdrozeniem_2026_10_08_priorytety` zrobiona
z nietkniętej kopii produkcji (606 pozycji, `is_priority` 69, blokady 2). Przed wycofaniem z kopią zgadzało się 0
pozycji (nowy kod nadpisał wszystkie), po: **595 z 595** pozycji jeszcze w produkcji (pozostałe 11 to pozycje
spakowane w kroku c); doróbka z blokadą; migracja 0,039 s.

### e) ponowne wdrożenie po wycofaniu (ta sama baza)

Gałąź wdrożeniowa jeszcze raz: migracje **0 plików** (wszystkie w `schema_migrations`), `flask migrate` ×2 → 0;
restart; cron 200 w 0,57 s, `wydane_dostarczone: 3` (znacznik usunięty przez wycofanie → cron znów przestawia
wydane odbiory, jak przewiduje spec), `priorytety_utrwalone.success: true` (246 zamówień / 595 pozycji); drugi cron
0 zmian. Trasy po wycofaniu zostają `zatwierdzona`. Przegląd: 798 adresów, 546 × 200, 33 zastane × 500,
0 × `LookupError`; w logu serwera tylko oczekiwane błędy braku klucza Base. i zaślepionego geokodera.

**Drugie wycofanie po ponownym wdrożeniu** (sprawdzone): runner nie wykona migracji cofającej drugi raz (jest
w `schema_migrations`) — stary kod dał 38 adresów z `LookupError`. Ręczne `source` pliku → 0 `LookupError`, 33 zastane
× 500. Do runbooka (niżej).

## Odstępstwa

1. **Model:** Opus 5.5 zamiast Fable 5.1 (karta przewidywała zgłoszenie).
2. **Geokoder z kopii wysłał adresy na zewnątrz.** Pierwszy cron w kroku b (zanim dołożyłem zaślepki hostów, które
   miał K5) uruchomił geokoder w tle: przetworzył **46 z 253 zamówień z kopii — adresy dostawy poszły do GUGiK
   i Nominatim** (16 znalezionych). To te same publiczne usługi i te same adresy, które produkcja wyśle po wdrożeniu,
   ale K5 celowo to odcinał. Wątek zginął z kontenerem po ok. 5 minutach; od tej chwili wszystkie uruchomienia mają
   zaślepki (Base., ORS, GUGiK, Nominatim, GlobKurier, Sentry) — kolejne crony: „GUGiK nie odpowiedział”, 0 nowych
   wyników. Klucza Base. w kopii nie było, więc do Base. nic nie wyszło.
3. **Zamówienie 1450:** sprawdziłem drzewo squasha po identyfikatorze Base. zamówienia `prod_orders.id = 1450`
   z kopii oraz po jego danych osobowych — 0 trafień. Ale **ten sam identyfikator i te dane mają też 0 trafień
   w historii `origin/claude/logistyka-etap-4`** (`git log -S`), a plan logistyki mówi o 5 commitach. Albo centrala
   logistyki sprawdzała inny identyfikator, albo „1450” to numer z innej bazy. Nie wpływa to na wdrożenie (do `main`
   idzie jeden commit bez historii logistyki), ale nie potwierdziłem, czego dokładnie dotyczyło ostrzeżenie —
   pytanie 4.
4. `flask migrate-status` w pierwszym podejściu do b) sam wykonał migracje (każde polecenie `flask` woła
   `create_app()`, które przy `RUN_MIGRATIONS` migruje) — pomiar przepadł, kopię odtworzyłem ze zrzutu i powtórzyłem.
   Wniosek do runbooka: na serwerze PRZED wdrożeniem nie wołać `flask` z nowym kodem na dysku.
5. Pierwszy przebieg c) przerwał się na moich błędach skryptu (paczki deklaruje się po spakowaniu; jeden kierowca na
   dwóch trasach tego dnia → 409). Kopię odtworzyłem i scenariusz przeszedł od zera (stąd drugi pomiar migracji).
6. Czasy migracji zawyżone równoległym pełnym pakietem testów (patrz b).
7. Obraz `logistyka3-app` ma Pythona 3.12 (produkcja 3.9) — zgodność składni sprawdzona `ast` z `feature_version`
   (3, 9); próba na Macu (rozstrz. 20) ma środowisko 3.9.
8. Push gałęzi wdrożeniowej zrobiłem dopiero po audycie wycofania (karta: po kroku 1) — gdyby audyt wymagał zmiany
   w pakiecie wdrożenia, gałąź trzeba by przepisać (`--force`). Nie wymagał.
9. Krok d sprawdzałem klientem testowym Flaska w kontenerze z serwerem (te same trasy, ta sama baza), a nie
   `curl` po HTTP; serwer HTTP odpowiadał 200 na `/login` po każdym restarcie. Lista adresów to wszystkie trasy GET
   (nie ręczny wybór), w tym API mobilne z tokenami urządzeń.

## Rozstrzygnięcia podjęte w trakcie

1. **Przepisy 4 i 5b (druk paczek, blokada doróbek) weszły do migracji cofającej** bez pytania: oba odtwarzają stan,
   który stary kod sam tworzy albo którego nie umie obsłużyć, nie zmieniają decyzji projektowych. Koszt, jeśli błędne:
   7 zadań druku nie wydrukuje się po wycofaniu (paczek stary kod i tak nie zna); doróbki na szczycie kolejki.
2. **Przepis 5a (kopia ręcznych flag) jest warunkowy** — działa tylko, gdy przed wdrożeniem zrobiono kopię (pytanie 1).
   Bez kopii flagi `is_priority` zostają w znaczeniu nowego kodu (gwiazdki albo po terminie), co przy wycofaniu daje
   pomarańczowe ramki na tych zamówieniach — bez błędów.
3. **Nie dołożyłem** przepisów z audytu, które zmieniają przepływ albo wymagają decyzji: cofnięcie pozycji
   `czeka_na_pakowanie` bez sposobu dostawy do `czeka_na_logistyke`; tekst `delivery_method` dla wysyłek do Base.,
   które utknęły; wyłączenie telefonów Weryfikacji/Dostawy; nazwy statusów w raportach. Wszystkie są w runbooku albo
   w pytaniach.
4. **Przepisy etapu 4 pkt 4 (trasy, log Dostawy) są w migracji, choć `main` tych tabel nie czyta** — karta i spec
   ich wymagają, a ponowne wdrożenie po nich działa (krok e).
5. Bazę `priorytety_wdrozenie` zostawiam w stanie **„po drugim wycofaniu”** (kod wycofania, migracja cofająca
   wykonana ręcznie); w bazie jest też tabela `zz_przed_wdrozeniem_2026_10_08_priorytety` z próby d2.

## Pytania do Konrada

1. **Kopia ręcznych priorytetów przed wdrożeniem.** Na produkcji jest dziś 67 aktywnych pozycji z ręczną flagą
   priorytetu (ramka), 1 ręczna blokada rangi i 1 doróbka z blokadą. Pierwsze przeliczenie nowego kodu nadpisze je
   bezpowrotnie — przy wycofaniu nie da się ich odtworzyć bez kopii. Rekomendacja: w runbooku K7, przed pushem do
   `main`, jedno polecenie SQL na produkcji (niżej, A3). Migracja cofająca sama ją wykorzysta, jeśli tabela istnieje.
   Tak?
2. **Zamówienia w pakowaniu bez sposobu dostawy przy wycofaniu.** Po wycofaniu stary kod po spakowaniu wyśle im
   status Base. „Zamówienie spakowane” (138623) — także tym, które miały jechać transportem (stary przepływ
   wymagał decyzji logistyki przed pakowaniem). Wariant A (rekomendacja): przed wycofaniem logistyk ustawia sposób
   wszystkim takim zamówieniom (lista z zapytania w runbooku). Wariant B: migracja cofa je do „Czeka na logistykę”
   (zmiana przepływu — do decyzji).
3. **Telefony Weryfikacji i Dostawy po wycofaniu** — stary backend ich nie obsłuży (rejestracja 400, kolejka offline
   ich akcji przepada). Wystarczy instrukcja „po wycofaniu nie używać”?
4. **Zamówienie 1450** — czy ktoś (centrala logistyki) poda identyfikator, który był w historii? Moja kontrola po
   numerze Base. i danych z kopii nie znalazła go nawet w historii logistyki.

## Stan środowiska

- Baza `priorytety_wdrozenie` — **zostaje do czwartku** (stan „po drugim wycofaniu”, opis wyżej). Bazy pomocnicze
  `wdrozenie_wzor` (nietknięta kopia do d2) i `wdrozenie_k0_terminy` — usunięte. Kontener `wdrozenie-proba` —
  zatrzymany i usunięty (127.0.0.1:5007 wolny).
- **Zrzut produkcji i migawka „stan c” — usunięte** po raporcie (plik w `woodpower-podglady/priorytety/wdrozenie/`
  i kopia w kontenerze `db`).
- Poza repo zostają narzędzia i wyniki: `woodpower-podglady/priorytety/wdrozenie/narzedzia/` (skrypty
  `kontener.sh`, `odtworz_kopie.sh`, `migruj.sh`, `cron.sh`, `wdr_*.py`, `zaslepki.txt`), `wyniki/` (JSON przeglądów,
  migracji, cronów — bez danych klientów poza id), `config/` (oczyszczony `core.json` — klucze losowe),
  `kod-main/`, `kod-wdrozenie/`, `kod-wycofanie/` (`git archive`).
- W `/tmp` kontenera `woodpower-crm-db-1` leżą pliki innych sesji (m.in. `l43.sql`, 230 MB z 30.09 — zrzut z podglądu
  logistyki); moich nie ma. Do sprzątnięcia przy porządkach po wdrożeniu.
- Kontenerów i baz K5 (`priorytety-k5`, `k5-centrifugo`, `priorytety_prod_kopia`, `priorytety_wyscigi`) ani
  logistyki (5003–5005) nie dotykałem. Worktree: `.claude/worktrees/pakiet-wdrozenia`, `wdrozenie-2026-10-08`,
  `wycofanie-2026-10-08` (do sprzątnięcia po czwartku).

## Wejście do runbooka K7

### A. Przed oknem (środa / czwartek rano)

1. **Stan:** `git fetch origin && git rev-parse origin/main` = `31a0b0145b222799234674bdf1e995dab6791a0c` i na serwerze
   `git -C /home/woodpower-crm/htdocs/crm.woodpower.pl rev-parse HEAD` = to samo. Inaczej **STOP** — squash trzeba
   zrobić od nowa (próbne scalenie, pakiet, kontrola 24 plików), a gałąź wycofania odbić od nowego squasha.
2. **Na serwerze przed pushem nie wołać żadnego `flask …`** z nowym kodem na dysku (każde polecenie migruje przy
   `create_app()`).
3. **(Pytanie 1) Kopia ręcznych priorytetów** — na produkcji, tuż przed pushem (jedno polecenie, nic nie zmienia
   w danych aplikacji):
   ```sql
   CREATE TABLE IF NOT EXISTS zz_przed_wdrozeniem_2026_10_08_priorytety AS
   SELECT id, priority_rank, priority_manual_override, is_priority FROM prod_products
   WHERE current_status NOT IN ('spakowane', 'anulowane');
   ```
   Kontrola: liczba wierszy ≈ liczba aktywnych pozycji (5.10 wieczorem: 606).

### B. Wdrożenie

1. `git fetch origin` → sprawdzenie A1 → **`git push origin 5e944a55978f659ca38a69d09d74b50a5a4d841e:main`**
   (szybkie przewinięcie z `31a0b014`). Webhook → `deploy.sh`; śledzić `logs/deploy.log` do `Deploy complete!`.
2. **Migracje:** 17 plików, 277 poleceń, 0 porażek; na kopii 6,0–7,5 s pod obciążeniem (K5 bez obciążenia: 2,2 s);
   najdłuższe: weryfikacja 1,8–2,0 s, dostawa 1,0–1,6 s, paczki 0,8–0,9 s. Błąd migracji → `deploy.sh` sam cofa kod
   przed restartem.
3. **Po restarcie raz ręcznie:** `scripts/cron_endpoint.sh POST /production/api/logistics/cron`. Oczekiwane: 200
   w < 1 s; `priorytety_utrwalone.success: true`, `zamowien` ≈ liczba aktywnych (kopia z 5.10: 253; K5: 255),
   `pozycji` ≈ 606, wszystkie zmienione; `szczeble_uzupelnione: 0`; drugi przebieg 0 zmian.
4. **Kontrole SQL po wdrożeniu:**
   - `SELECT config_key, config_value FROM prod_config WHERE config_key LIKE 'DEADLINE%'` → `DEADLINE_DAY_TYPE`
     robocze, `DEADLINE_DEFAULT_DAYS` 10, `DEADLINE_FINISHED_DAYS` 14;
   - `SELECT kind, stars, tag, position FROM prod_priority_rungs ORDER BY position` → 9 wierszy: ★5, `po_terminie`,
     ★4, `blisko_terminu`, `rozpoczete`, ★3, ★2, ★1, ★0;
   - `SELECT SUM(config_key LIKE 'priorytety\_%'), SUM(config_key = 'DEADLINE_DAY_TYPE') FROM prod_config` → 37, 1;
   - rangi aktywnych zamówień: `COUNT(*) = COUNT(DISTINCT priority_rank)`, `SUM(priority_rank IS NULL) = 0`;
   - `priorytety_tryb_*` = `stary` ×7, `priorytety_min_app_version_code` = 0, `SELECT COUNT(*) FROM prod_station_desk`
     = 0;
   - `SELECT COUNT(*) FROM schema_migrations WHERE success = 1 AND version >= '2026-09-25'` = 17.
5. Dalej jak w raporcie K5 („Wejście do runbooka K7”, B4–B6) i planie logistyki.

### C. Wycofanie (cała paczka: logistyka 1–4 + priorytety)

**Przed** (jeszcze na nowym kodzie, jeśli się da):
1. Logistyk zdejmuje wiszące „Niedostarczone” do puli („Zdejmij z trasy” / „Odhacz”) — kontrola
   `SELECT COUNT(*) FROM prod_route_stops WHERE not_delivered_at IS NOT NULL` = 0 (spec etapu 4, 14 pkt 6.1;
   niezdjęte migracja i tak wyzeruje, ale bez skutków w Base.).
2. Ręczny cron logistyki (dopycha zaległe wysyłki do Base.), potem
   `SELECT COUNT(*) FROM prod_orders WHERE bl_status_pending_id IS NOT NULL OR bl_delivery_method_pending = 1 OR
   bl_address_pending = 1` = 0 (po wycofaniu nikt tego nie dośle). Spisać zamówienia z `repack_required = 1` albo
   `problem_at IS NOT NULL` (banery i problemy Weryfikacji znikną).
3. (Pytanie 2) Zamówienia w pakowaniu bez sposobu dostawy:
   `SELECT COUNT(DISTINCT o.id) FROM prod_orders o JOIN prod_products p ON p.order_id = o.id WHERE p.current_status
   = 'czeka_na_pakowanie' AND o.override_delivery_method IS NULL` — logistyk ustawia sposób.
4. Usunąć z crontaba wpis `POST /production/api/logistics/cron` (po wycofaniu 404 co godzinę).

**Wykonanie:**
5. `git fetch origin && git rev-parse origin/main` = `5e944a55978f659ca38a69d09d74b50a5a4d841e` (inaczej **STOP** —
   gałąź wycofania trzeba odbić od bieżącego `main`), potem
   **`git push origin 8e14937e8497fdf9a27c5ba0db97e739b9057ccc:main`** (szybkie przewinięcie). `deploy.sh` wykona
   migrację cofającą przed restartem (na kopii: 44 polecenia, 0,03 s).
6. **Po `Deploy complete!` jeszcze raz ręcznie** (okno między migracją a restartem — do ok. 5 min z przeliczeniem
   klientów — nowy kod mógł dopisać nowe stany; plik jest idempotentny):
   `cd /home/woodpower-crm/htdocs/crm.woodpower.pl && mysql -uroot crm < migrations/2026-10-08-wycofanie-logistyki.sql`
7. **Kontrole SQL po wycofaniu** (wszystkie = 0):
   ```sql
   SELECT COUNT(*) FROM prod_products WHERE current_status IN ('zweryfikowane','zaladowane','dostarczone');
   SELECT COUNT(*) FROM prod_routes WHERE status IN ('zaladowana','w_trasie');
   SELECT COUNT(*) FROM prod_logistics_log WHERE action IN ('zaladunek','zostaje','wyjazd','dostarczone',
     'niedostarczone','dostarczenie_cofniete','niedostarczenie_cofniete');
   SELECT COUNT(*) FROM prod_route_stops WHERE not_delivered_at IS NOT NULL;
   SELECT COUNT(*) FROM prod_config WHERE config_key = 'logistyka_wydane_dostarczone';
   SELECT COUNT(*) FROM prod_print_queue WHERE status = 'pending' AND (printer <> 'etykiety' OR package_id IS NOT NULL);
   SELECT COUNT(*) FROM prod_products WHERE original_product_id IS NOT NULL
     AND current_status IN ('czeka_na_wyciecie','czeka_na_skladanie','czeka_na_sklejanie')
     AND NOT (priority_rank = 1 AND priority_manual_override = 1 AND is_priority = 1);
   ```
   oraz w panelu: Lista produkcyjna, archiwum, monitor hali, tablet (lista stanowiska, wyszukiwarka) bez błędów.
8. **Nie wołać** `POST /production/api/recalculate-all-priorities` — zdejmuje wszystkie blokady (także doróbek).
   Rangi pozycji (po wdrożeniu ×100) stary kod numeruje od nowa przy najbliższym imporcie nowych zamówień z Base.
9. **Tablety:** nowa appka 1.8.0 na starym backendzie działa jak 1.7.3 (sprawdzone: `desk`, `realtime-token`,
   `packages` → 404 HTML, lista 200) — stół znika przy najbliższym `desk`, bez restartu; kolejka offline zostaje
   (ZAKOŃCZ i licznik mają ten sam kształt). Odłożenia (tylko online) przestają istnieć dla hali. Stara appka 1.7.3 —
   bez zmian. **Telefony Weryfikacji i Dostawy** przestają działać (404 / rejestracja 400); ich niewysłane akcje
   z kolejki offline przepadają.
10. **Drugie wycofanie po ponownym wdrożeniu:** runner nie wykona migracji cofającej drugi raz (wpis w
    `schema_migrations`) — po deployu gałęzi wycofania koniecznie ręcznie krok 6 (sprawdzone: bez niego 38 adresów
    z `LookupError`, z nim 0).
11. **Ponowne wdrożenie po wycofaniu** (sprawdzone): push squasha jeszcze raz (gałąź wdrożeniowa musi wtedy wyjść od
    bieżącego `main` — revert revertu albo nowy squash), migracje 0 plików, ręczny cron — przestawi wydane odbiory
    na `dostarczone`; trasy wracają jako `zatwierdzona`.

**Czego wycofanie NIE cofa:**
- statusów i pól wysłanych już do Base. (Planowana trasa 417343, Załadowane 524520, Wysłane 149763, Dostarczone
  149778, Odebrane 149779, Spakowane 138623, metoda dostawy jako „Kurier” / „Transport WoodPower” / „Odbiór osobisty”,
  adresy poprawione w Logistyce) — zostają w Base., stary kod ich nie poprawi;
- ręcznych flag i blokad priorytetów bez kopii z A3; nazw kurierów w `delivery_method` nadpisanych tekstem metody;
- ręcznych kroków z planu logistyki: klucz ORS i CARTO w `core.json`, status 524520 w Base., wpisy crontaba (krok 4),
  agent druku z dwiema drukarkami na hubie (na starym backendzie drukuje tylko etykiety — zadania bez pola `printer`),
  APK 1.8.0 na tabletach, telefony i kierowcy we Flocie;
- danych logistyki i priorytetów w nowych tabelach i kolumnach (trasy, paczki, geolokalizacja, gwiazdki, stół, log) —
  zostają na ponowne wdrożenie;
- terminów 10 / 14 w `prod_config` (stary kod je czyta — zamierzone).
