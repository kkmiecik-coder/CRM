# Raport — Priorytety produkcji, krok K5: przegląd przed wdrożeniem

- **Data:** 2026-10-05 (sesja wieczorna; termin werdyktu: wtorek 6.10, ok. 13:00)
- **Sesja:** lokalna, model Fable 5.1, effort extra. Dwa pierwsze polecenia sesji (pobranie gałęzi, założenie
  worktree) wykonał Opus 5.5 — Konrad przełączył model na Fable 5.1 przed pierwszym krokiem planu; cała praca
  merytoryczna jest z Fable 5.1.
- **Plan:** `docs/superpowers/plans/2026-10-05-priorytety-krok-K5-przeglad-p1.md` + dodatki z karty K5
- **Stan wyjściowy:** `claude/priorytety-produkcji` @ `f7c47c9a` (108 commitów ponad `claude/logistyka-etap-4`
  @ `f07b21ec`; logistyka bez ruchu, `main` @ `31a0b014` bez ruchu od bramki K3)
- **Stan końcowy:** commit dokumentacji `be539b9f` i commit tego raportu (czubek `claude/priorytety-produkcji` po
  jego wypchnięciu); kod aplikacji bez zmian wobec stanu wyjściowego

## Werdykt w skrócie

**P1 GOTOWE DO WDROŻENIA.** Blokad wdrożenia nie znalazłem; kodu aplikacji K5 nie zmieniał (poza dwoma
docstringami w `blokady_zamowien.py`).

- Pełny pakiet: 6818 passed przed, 6824 po (doszło 6 testów dokumentacji); `blog_seo` 89 passed; składnia
  Pythona 3.9 dla 86 zmienionych plików.
- Migracje na świeżej kopii produkcji (bez tabel logistyki): 16 plików w 2,16 s, bez błędu; kolejne przebiegi
  „Wykonano 0 migracji”.
- Nowy algorytm na danych produkcji zgadza się z symulacją w 100 % (255 zamówień, sześć stanowisk).
- Wyścigi na MySQL: 34 tryby, 1222 przebiegi + 96 potwierdzających + trzy próby obciążeniowe (3879 żądań) —
  **zero zakleszczeń bez ponowienia, zero zdublowanych, nieaktualnych i niekompletnych kafli, zero 500 poza jednym
  znanym przypadkiem** (dwa równoczesne pierwsze zapisy tego samego klucza ustawień). Regresja wyścigów logistyki
  4.4a/4.4b: 12 trybów × 10, czysto.
- Próbne scalenie z `main` (5 commitów spoza gałęzi): bez konfliktów, pełny pakiet 6842 passed.
- Sygnały przez prawdziwy broker, start stołów na kopii produkcji i oględziny panelu: bez usterek blokujących.

Uwagi nieblokujące (lista niżej) mają trzy pozycje warte uwagi przed czwartkiem: objaw zawieszonego brokera
(ZAKOŃCZ dłuższy o ok. 1,4 s), nieużywana ścieżka crona importu, która kończy się 500 (zastane; import, którego
biuro używa, działa), i sposób squasha do `main` (musi być scaleniem, nie kopią drzewa).

## Zrobione

| Task | Co | Wynik |
|---|---|---|
| 1 | punkt wyjścia, interfejsy, pełny pakiet, regresje | bez zmian w kodzie; 0 usterek w zakresie |
| 2 | migracja ×2 (baza z logistyką i kopia produkcji), cron, symulacja | bez błędu, zgodność 100 % |
| 3 | broker w dockerze, podgląd na kopii, skrypt wyścigów, kolejność zapytań z `general_log` | zgodna z K3 DoD 3 |
| 4 | wyścigi MySQL (plan + lista K3 + karta + własne), regresja logistyki | kryterium spełnione |
| 5 | oględziny w przeglądarce, API mobilne po HTTP, sygnały, awarie brokera, czasy, start stołów | bez blokad |
| 6 | CLAUDE.md, docstring `blokady_zamowien`, spec (sekcja 16 i zaszłości), kontrakt §6/§8, test dokumentacji | commit `be539b9f` |
| 7 | pełny pakiet po zmianach, raport, werdykt | ten dokument |

Narzędzia i wyniki surowe leżą poza repo: `woodpower-podglady/priorytety/k5/` (skrypty `k5_*.py`, logi serii,
`_wyscigi_k5*.jsonl`, `innodb-status-wyslij-wyslij-*.txt`, `explain-*.log`, `general-log-desk-zakoncz.txt`,
`k5-notatki.md`).

## Testy

| Co | Polecenie (z worktree) | Wynik |
|---|---|---|
| pełny pakiet, punkt wyjścia (`f7c47c9a`) | `docker compose -p priorytety run --rm --no-deps app pytest tests/ -q -p no:cacheprovider` | **6818 passed, 3 skipped, 0 failed** (7 min 18 s) |
| pełny pakiet po Task 6 (`be539b9f`) | to samo | **6824 passed, 3 skipped, 0 failed** (6 min 28 s) |
| `integrations/blog_seo` | `… app bash -c "cd integrations/blog_seo && python -m pytest -q -p no:cacheprovider"` | 89 passed (przed i po) |
| składnia 3.9 | `ast.parse(…, feature_version=(3, 9))` dla plików z `git diff --name-only --diff-filter=d b4b4a54d..HEAD -- '*.py'` | OK, 86 plików (+ pliki K5) |
| test dokumentacji (nowy) | `pytest tests/test_priorytety_dokumentacja.py` | czerwony przed zmianami (6 failed), zielony po (6 passed) |
| próbne scalenie z `origin/main` (ponad plan) | osobny tymczasowy worktree, `git merge --no-commit --no-ff origin/main`, pełny pakiet | 0 konfliktów; **6842 passed, 3 skipped, 0 failed** (7 min 04 s) |

Grepy interfejsów (Task 1 Step 2): 14 końcówek panelu priorytetów; `KSZTALT_ODPOWIEDZI_KOLEJKI = 6`,
`KSZTALT_ODPOWIEDZI_STOLU = 2`; handlery stołu nazywają się `station_desk`, `order_postpone`, `realtime_token`;
w serwisach pakietu `priorytety` nie ma `db.session.commit()`; w `mobile_api.py` commituje tylko `desk` (dwa razy)
oraz dwa miejsca sprzed P1 (druk etykiety, heartbeat); `stol.zdejmij_nieaktualne` wołają: ZAKOŃCZ, doróbka, zmiany
z Base., hurt i cron osieroconych; martwych nazw (`update-priority`, `set-priority`, `products-dragdrop`,
`PRIORITY_RECALC_INTERVAL_HOURS`, `PRIORITY_ALGORITHM_VERSION`, `_PRIORITY_SORT`) nie ma — zostały tylko znane progi
`priority_rank <= 10` w `routers/admin_routers.py` i `modules/production/__init__.py` (K8).

## Migracje

**Kopia produkcji** (zrzut z 5.10 wieczorem; serwer produkcyjny i kopia w dockerze: MySQL 8.4, REPEATABLE READ,
kolacja bazy jak na produkcji; 85 tabel, 1912 zamówień, 4397 pozycji; **bez tabel logistyki** — ostatnia
wykonana migracja `2026-09-23-unikalnosc-klucza-pozycji`). Pierwszy przebieg = pełna sekwencja, którą wykona
`deploy.sh` w czwartek:

| Migracja | Poleceń | Czas |
|---|---|---|
| `2026-09-25-logistyka-sposob-dostawy.sql` | 49 | 0,302 s |
| `2026-09-26-logistyka-geolokalizacja.sql` | 3 | 0,023 s |
| `2026-09-26-logistyka-zmiana-adresu.sql` | 6 | 0,032 s |
| `2026-09-27-logistyka-trasy-flota.sql` | 4 | 0,081 s |
| `2026-09-28-logistyka-kierowcy.sql` | 5 | 0,025 s |
| `2026-09-30-druk-dwie-drukarki.sql` | 15 | 0,061 s |
| `2026-09-30-druk-klucze-przesuniecia.sql` | 1 | 0,006 s |
| `2026-09-30-logistyka-paczki-blokada.sql` | 1 | 0,006 s |
| `2026-09-30-logistyka-paczki.sql` | 23 | 0,297 s |
| `2026-09-30-logistyka-weryfikacja.sql` | 48 | 0,439 s |
| `2026-10-01-analiza-planowana-trasa.sql` | 1 | 0,007 s |
| `2026-10-01-logistyka-dostawa.sql` | 42 | 0,327 s |
| `2026-10-02-logistyka-niedostarczone-na-trasie.sql` | 26 | 0,164 s |
| `2026-10-02-raport-planowana-trasa.sql` | 5 | 0,035 s |
| `2026-10-05-priorytety-produkcji.sql` | 36 | 0,256 s |
| `2026-10-06-priorytety-stol-zrodlo.sql` | 11 | 0,099 s |
| **razem** | 276, 0 błędów | **2,159 s** |

Najdłuższe pojedyncze polecenie: `MODIFY` kolumny ENUM w `prod_products` — 0,214 s; na `prod_orders` 25 poleceń
(razem ok. 0,60 s, żadne ponad 0,05 s). Drugi i trzeci przebieg: „Wykonano 0 migracji”. Po migracji: 9 szczebli
w kolejności ze specu 3.1, 38 wierszy `prod_config` (37 kluczy `priorytety_*` i `DEADLINE_DAY_TYPE`), 5 kolumn
`prod_orders.priority*`, klucz obcy `fk_prod_priority_rungs_route` → `prod_routes` z `ON DELETE CASCADE`, nowe tabele
w kolacji `utf8mb4_unicode_ci`, rangi zamówień NULL (liczy je cron). Jedna pozycja w statusie `czeka_na_logistyke`
przeszła migracją do pakowania (254 → 255 zamówień aktywnych).

**Baza z wykonaną logistyką** (`priorytety_wyscigi`, kopia podglądu programu; 73 wpisy `schema_migrations`):
`flask migrate` dwa razy → „Wykonano 0 migracji.”; `migrate-status` pokazuje obie migracje priorytetów `[success]`;
te same kontrole schematu (szczeble tras stoją między ★★★★★ a „Po terminie”).

**Pierwszy cron na kopii** (`POST /production/api/logistics/cron`): 200 w 0,585 s (90 zapytań),
`szczeble_uzupelnione: 0`, `priorytety_utrwalone.success: true`, 255 zamówień i 609 pozycji z rangą, `utrwal` 0,34 s.
Drugi przebieg: 0,150 s, 0 zmian, `utrwal` 0,021 s. Rangi 1..255 unikatowe; aktywnych pozycji
z `priority_manual_override` — 0. Rozkład: „Po terminie” 14, „Blisko terminu” 29, „Rozpoczęte” 6 (tag ma 10
zamówień), bez gwiazdek 206.

**Algorytm kontra symulacja** (`scripts/symulacja_priorytetow.py`, ten sam dzień, próg 3 dni): ranga zamówień
255/255 zgodnych miejsc; kolejki stanowisk: Wycinanie 26/26, Składanie 200/200, Sklejanie 110/110, Krawędzie 29/29,
Formatowanie 33 kompletne + 6 niekompletnych, Pakowanie 39 + 3 — identycznie; tagi identyczne.

## Kolejność zapytań (`general_log`, Sklejanie w trybie `stol`)

- `GET desk` z dopełnieniem: `COMMIT` → `SET SESSION innodb_lock_wait_timeout = 5` → `prod_config`
  `priorytety_blokada_gluing` `FOR UPDATE` → zwykłe odczyty ustawień i id zamówień z pozycją w statusie → `prod_orders
  … ORDER BY id LOCK IN SHARE MODE` → `prod_products … ORDER BY order_id, id LOCK IN SHARE MODE` → zwykłe odczyty
  (przystanki, stół, konfiguracje, szczeble) → przywrócenie limitu → `INSERT prod_station_desk` ×2 → `COMMIT`.
- ZAKOŃCZ kafla: `prod_orders … FOR UPDATE` → `prod_products … FOR UPDATE` → własny wiersz stołu po kluczu unikalnym
  `FOR UPDATE` → `UPDATE prod_products` → zdarzenia → `prod_station_desk WHERE order_id … FOR UPDATE` → `DELETE` →
  wpis idempotencji → `COMMIT`.
- Odłóż: zamówienie `FOR UPDATE` → pozycje `FOR UPDATE` → własny kafel `FOR UPDATE` → zwykły `COUNT` odłożonych →
  log → `UPDATE` stołu → `COMMIT`.

Zgodne z kontraktem z raportu K3 (DoD 3). W trybie `stary` `GET desk`: zero blokad, jedyny zapis to znacznik
ostatniego kontaktu urządzenia.

## Wyścigi

Skrypt poza repo (`k5_wyscigi.py`): jeden proces, N wątków na `threading.Barrier`, każdy wątek z własnym klientem
testowym Flaska i własnym połączeniem (pula powiększona, żeby wątki nie czekały na siebie), osobne `X-Operation-Id`.
Miary po każdym przebiegu: licznik InnoDB `lock_deadlocks`, log aplikacji (1213, 1205, ponowienia), odpowiedzi 500,
niezmienniki stołu (bez duplikatów, bez nieaktualnych, bez niekompletnych kafli-zamówień) i rang (punkt stały po
dodatkowym `utrwal`). Serie: `b` = start z bariery, `rNN` = losowy rozjazd startu 0–NN ms. Baza
`priorytety_wyscigi`, chyba że napisano inaczej. Licznik `lock_deadlocks` przez całą serię: 19 → 27.

| Tryb | Przebiegi | 1213 (z ponowieniem) | 500 | Odpowiedzi / obserwacje |
|---|---|---|---|---|
| **`desk-desk`** — dwa tablety, pusty stół | 62 | 0 | 0 | 200/200; stół zawsze 2 kafle |
| **`desk-zakoncz-inne`** — ZAKOŃCZ A1 ↔ `desk` | 62 | 0 | 0 | 200/200; po wyścigu stół bywa o 1 krótszy (57×) do następnego `desk` |
| **`gwiazdki-zakoncz`** | 62 | 0 | 0 | 200/200 |
| **`szczebel-przystanek`** — drabina ↔ przystanek trasy | 62 | 0 | 0 | 200/200; bez 409 `drabina_zmieniona` |
| **`utrwal-dostawa`** — gwiazdki ↔ „Zakończ załadunek” | 62 | 0 | 0 | 200/200; szczebel trasy znika z drabiny |
| `utrwal-dostawa-b` — załadunek niekompletny | 10 | 0 | 0 | 200 / 409 `loading_incomplete` |
| **`odloz-zakoncz-ten-sam-kafel`** | 62 | 0 | 0 | 409 `nie_na_stole` / 200 — 41×; 200 / 200 — 21× (ZAKOŃCZ odłożonego) |
| `desk-zakoncz-to-samo-zamowienie` | 30 | 0 | 0 | 200/200 |
| `desk-dorobka` — doróbka z Formatowania ↔ `desk` | 30 + 30 | 0 | 0 | powtórzone: 30/30 200/200, doróbka wraca na Składanie (pierwsza seria: 9× 400 `invalid_quantity` — dane testu) |
| `desk-panel-sposob` — sposób dostawy ↔ `desk` Pakowania | 30 | 0 | 0 | 200/200 |
| `odloz-odloz` — limit 2, jeden już odłożony | 30 | 0 | 0 | 200/200 — 29× (3 odłożone: limit miękki); 409 `limit_odlozen` — 1× |
| `odloz-zakoncz` | 30 | 0 | 0 | 200/200 |
| `odloz-hurt` | 30 | 0 | 0 | 200/200 |
| `zakoncz-zakoncz-ten-sam-kafel` (Sklejanie, `stol`) | 30 | 0 | 0 | zawsze 200 + 409 `pozycja_poza_stanowiskiem`; status przesunięty raz |
| `zakoncz-zakoncz-formatowanie` (kafel-zamówienie) | 30 | 0 | 0 | jak wyżej |
| `zakoncz-zakoncz-pakowanie` (kafel-zamówienie) | 30 | 0 | 0 | jak wyżej |
| `zakoncz-zakoncz-stary` (tryb `stary`) | 20 | 0 | 0 | 200 + 200, status przesunięty raz (zachowanie zastane) |
| `hurt-desk` — hurt 20 pozycji ↔ `desk` | 30 | 0 | 0 | 200/200 |
| `wyslij-desk` | 30 | 0 | 0 | 200/200 |
| `wyslij-zakoncz` | 30 | 0 | 0 | 200/200 |
| `wyslij-zakoncz-stary` | 30 | 0 | 0 | 200/200 — 26×; 409 `brak_na_stanowisku` / 200 — 4× |
| `wyslij-przywroc-zakoncz` — „Wyślij” odłożonego ↔ ZAKOŃCZ | 30 | 0 | 0 | 200/200 — 24×; 409 `brak_na_stanowisku` / 200 — 6× |
| `zdejmij-zakoncz` | 30 | 0 | 0 | 200 / 409 `nie_na_stole` — 16×; 404 `brak_kafla` / 200 — 14× |
| `zdejmij-odloz` | 30 | 0 | 0 | 200 / 409 `nie_na_stole` — 23×; 200/200 — 7× |
| `przygotuj-zakoncz` | 30 | 0 | 0 | 200/200 |
| `przygotuj-desk` | 30 | 0 | 0 | 200/200 |
| `utrwal-utrwal` — dwa przeliczenia naraz | 30 | 0 | 0 | oba `success`, rangi w punkcie stałym |
| `weryfikacja-cofnij-desk` | 30 | 0 | 0 | 200/200 |
| `wyslij-wyslij` — dwa „Wyślij” na puste stoły różnych stanowisk | 30 | **8 (8 udanych ponowień)** | 0 | zawsze 200/200 |
| `wyslij-zakoncz-inne` — regresja W1 z K3 | 50 | 0 | 0 | 200/200 |
| `desk-stary-zakoncz` | 30 | 0 | 0 | 200/200 |
| `wlacz-stoly-desk` — „Włącz stoły” ↔ dwa `desk` | 30 | 0 | 0 | 200/200/200 |
| `ustawienia-ustawienia` — dwa `PUT /ustawienia` | 20 | 0 | **9** | brakujący wiersz klucza: 200 + 500 `blad_serwera` 9 z 10; istniejące klucze: 200 + 200 |
| `desk-utrwal` — **kopia produkcji**, hurt gwiazdek ↔ 6 × `desk` | 30 | 0 | 0 | 7 × 200 |
| **razem** | **1222** | **8, wszystkie z ponowieniem** | **9, jeden znany przypadek** | 0 złamanych niezmienników |

Tryby wytłuszczone to sześć obowiązkowych z planu (po 62 przebiegi). Nazwy trybów są kanoniczne — spec 16.8.

**Próby specjalne:**

- `utrwal-niezatwierdzony-zapis` ×3 — `utrwal()` wołane przez wątek, który sam trzyma niezatwierdzoną blokadę
  zamówienia: 5,15 / 5,01 / 5,02 s i `success: False` (1205), bez wyjątku; po zwolnieniu blokady 0,03–0,04 s
  i `success: True`; limit czekania wszystkich połączeń puli wrócił do wartości serwera.
- `desk-dluga-blokada` ×2 — obca sesja trzyma `FOR UPDATE` na zamówieniu-kandydacie przez 20 s: każdy `desk` wraca
  z 200 i bieżącym stołem, bez dopełnienia — po 5,0–5,1 s, a gdy czekania się sumują (najpierw blokada stanowiska
  za innym tabletem, potem zamówienie) po 6–9 s (maks. 9,1 s; limit 5 s dotyczy każdego czekania z osobna).
  **Obserwacja:** w tym czasie ZAKOŃCZ kafla INNEGO zamówienia czekał do 5,1 s (4,1 s w pierwszym powtórzeniu,
  5,1 s w drugim) — czekający `desk` trzyma już blokady S zamówień o niższych id. Raport K3 pisał „bez opóźnień
  dla pisarzy”; opóźnienie jest ograniczone limitem 5 s i wymaga cudzej blokady trzymanej sekundami.
- `widmo` — po hurtowym usunięciu pozycji (`bulk-action` z `delete`) kafel `p:` znika kaskadą klucza obcego, kafel
  `o:` zostaje: `desk` oddaje 200, kafel zajmuje miejsce na stole, `GET /stoly` pokazuje go w `widma`, „Zdejmij”
  działa.
- `burza` (ponad plan) — 16 wątków mieszanego ruchu (12 tabletów na sześciu stanowiskach, Lakiernia, dwa panele
  biura, cron) bez przerw: 60 s na bazie wyścigów (1080 żądań) i 2 × 90 s na kopii produkcji (1353 i 1446 żądań):
  0 × 1213, 0 × 1205, 0 × 500, 0 złamanych niezmienników.
- Seria potwierdzająca (po poprawce skryptu, patrz „Odstępstwa” p. 14): 8 trybów × 12 = 96 przebiegów, czysto.

**Regresja wyścigów logistyki** (skrypty 4.4a/4.4b z katalogu podglądów, bez zmian; każdy tryb 5 z bariery + 5
z rozjazdem 15 ms): 4.4a `panel-zakoncz-ostatnie`, `dorobka-zakoncz`, `sync-zakoncz`, `hurt-zakoncz`,
`zakoncz-zakoncz`; 4.4b `zakonczenie-zakoncz`, `dostarczenie-odhaczenie`, `zakonczenie-dwa`, `zakonczenie-cron`,
`hurt-zakonczenie`, `skan-przeliczenie`, `odhacz-przeliczenie` — 120 przebiegów, 0 zakleszczeń, 0 × 500, 0
niespójności; rozkłady odpowiedzi jak w raportach logistyki.

**Dwa zakleszczenia do opisania, żadne nie jest blokadą:**

1. `wyslij-wyslij` (8 z 30): dwa „Wyślij” naraz na RÓŻNE stanowiska przy pustych stołach. Każda transakcja czyta
   własny kafel odczytem bieżącym po kluczu unikalnym (wiersza nie ma → blokada luki na końcu indeksu, wspólnej dla
   obu), po czym wstawia wiersz i czeka na lukę drugiej. InnoDB wycofuje jedną, router ponawia — obie kończą się
   200. Znane z K3 (rozstrz. 37). Zjawisko wymaga pustej tabeli stołów; po starcie stołów luki są wąskie.
   Wyciąg z `LATEST DETECTED DEADLOCK` (osiem zapisów, wszystkie tej postaci): obie transakcje „inserting”
   (`INSERT INTO prod_station_desk`), każda **trzyma** `RECORD LOCKS … index uq_prod_station_desk_unit … lock_mode X`
   i **czeka** na `… index uq_prod_station_desk_unit … lock_mode X insert intention`. Żadna inna tabela ani indeks
   w cyklu nie występuje — to nie jest złamanie kolejności zamówienie → pozycje → stół.
2. `ustawienia-ustawienia` (9 × 500): dwóch adminów zapisuje w tej samej chwili klucz, którego wiersza nie ma
   jeszcze w `prod_config` — drugi `INSERT` łamie unikalność i kończy się 500 `blad_serwera` (bez zapisu),
   powtórka przechodzi. Na produkcji brakuje dziś jednego takiego wiersza (`DEADLINE_FINISHED_DAYS`). „Włącz stoły”
   tego nie dotyczy (wszystkie klucze trybów zakłada migracja).

**Czasy z wyścigów** (para żądań naraz, jeden proces): ZAKOŃCZ mediana 40 ms, p95 80 ms; `desk` 88 / 184 ms (maks.
224); Odłóż 53 / 85; „Wyślij” 19 / 65; „Zdejmij” 18 / 39; „Przygotuj stoły” 120 / 166; „Włącz stoły” 101 / 126;
hurt statusu 195 / 273; gwiazdki z przeliczeniem 105–278 / 362; `utrwal` 161 / 230 ms.

## EXPLAIN (kopia produkcji, trzy stany stołu: 0 / 14 / 21 wierszy)

Żadne zapytanie blokujące nie robi pełnego skanu (`ALL` ani `index`):

| Zapytanie | Plan | Co blokuje |
|---|---|---|
| `utrwal`: zamówienia (pełna lista 255) | `range` po PRIMARY | 255 wierszy + 6 blokad następnego klucza |
| `utrwal`: pozycje `order_id IN (…) ORDER BY id` (uwaga K1 M4) | `range` po `idx_order` + sortowanie | 627 rekordów PRIMARY — dokładnie pozycje tych zamówień; do tego 254 luki `idx_order` |
| `dopelnij`: wiersz blokady stanowiska | `const` | 1 wiersz `prod_config` |
| `dopelnij`: zamówienia / pozycje `LOCK IN SHARE MODE` | `range` po PRIMARY / `range` po `idx_order` | S tylko na własnych (na czterech stanowiskach +1 sąsiedni rekord zamówienia) |
| ZAKOŃCZ: zamówienie / pozycje | `const` / `ref` po `idx_order` | własne zamówienie i jego pozycje |
| ZAKOŃCZ: własny kafel | `const` po `uq_prod_station_desk_unit` | 1 wiersz (przy pustej tabeli: luka) |
| ZAKOŃCZ: wiersze stołu zamówienia | `ref` po `ix_prod_station_desk_order_id` | wiersze jednego zamówienia |

**Indeks `ix_prod_station_desk_station_code`:** jest nadmiarowy wobec lewego prefiksu klucza unikalnego
`(station_code, unit_key)`. Żaden odczyt blokujący go nie używa, więc nie dokłada blokad; kosztuje jeden wpis
indeksu przy wstawieniu i usunięciu kafla (kilkaset operacji dziennie). Rekomendacja: zostawić na wdrożenie, usunąć
w K8 po sprawdzeniu planów zwykłych odczytów stołu.

## Sygnały (prawdziwy broker Centrifugo w dockerze, podgląd na kopii produkcji)

- `GET /api/mobile/realtime-token`: Sklejanie → `["station:gluing"]`; Krawędzie → `["station:edges",
  "station:painting"]`; Lakiernia → `["station:painting", "station:edges"]`; trakownia i weryfikacja → 404
  `unknown_station`; panel bez sesji → 401.
- Pełne przejście API mobilnego po HTTP (jak tablet): `desk` dopełniający → jeden sygnał; 304 i `desk` bez zmian →
  brak; Odłóż → sygnał; 400 `powod_niepoprawny` i `dane_niepoprawne`; 409 `limit_odlozen` i 409 `nie_na_stole` bez
  sygnału i bez wpisu idempotencji; stara appka (bez heartbeatu) → 200 mimo trybu `stol`; licznik → sygnał; ZAKOŃCZ
  odłożonego → 200, log `odlozenie_zamkniete`, sygnały na to i następne stanowisko; powtórka tym samym
  `X-Operation-Id` → zapisana odpowiedź; drugi tablet z nowym identyfikatorem → 409 `pozycja_poza_stanowiskiem`;
  „Wyślij” i „Zdejmij” → sygnał; gwiazdki → brak; `desk` w `stary` tylko czyta. Ładunek zawsze
  `{"kind": "station", "station": …}`.
- Pozostałe zdarzenia: „Cofnij do pakowania” i przepakowanie → `packaging`; zwykła zmiana sposobu dostawy → brak;
  import → `assembly` i `cutting`; doróbka → stanowisko odrzutu i powrotu; hurt → stanowisko, z którego zdjęto
  kafel, i stanowisko nowego statusu; cron osieroconych → `packaging`.
- **Awarie brokera:** zdrowy — ZAKOŃCZ mediana 53 ms. Zawieszony (przyjmuje połączenie, nie odpowiada) — ZAKOŃCZ
  mediana **1460 ms** (dwa sygnały po 0,7 s), `desk` z dopełnieniem ok. 800 ms, wszystko 200. Zatrzymany (odmowa
  połączenia) — bez narzutu, 200. `REALTIME.enabled=false` → `realtime-token` 503 `{"enabled": false, "reason":
  "realtime disabled"}`, akcje 200.

## Start stołów (kopia produkcji z 5.10 wieczorem)

- Podgląd (`GET /start`, 67 ms): **14 kafli rozpoczętych** — Sklejanie 4, Formatowanie 9, Pakowanie 1; Wycinanie,
  Składanie i Krawędzie 0. Tło: pozycji / zamówień na stanowiskach — Wycinanie 26 / 17, Składanie 200 / 79,
  Sklejanie 110 / 57, Formatowanie 143 / 39, Krawędzie 29 / 17, Lakiernia 37 / 22, Pakowanie 64 / 42. Liczba kafli
  zależy od liczników w chwili kliknięcia (w czwartek o 10:30 — z połowy zmiany).
- „Przygotuj stoły” z działającym brokerem: **126 ms** (63 zapytania, 20 zapisów); drugi raz 87 ms i +0 wszędzie.
- „Włącz stoły”: przy progu wersji 0 → 400 `prog_wersji_wymagany` (nic się nie zmienia); z progiem → jeden zapis,
  37–198 ms, sześć stanowisk `stol`, Lakiernia zostaje `stary`.
- Pierwsze `desk` po włączeniu (HTTP): Wycinanie 2 kafle z kolejki, Składanie 2 (doróbka + kolejka), Sklejanie 4
  startowe, Formatowanie 9 startowych, Krawędzie 2, Pakowanie 2 (start + kolejka); 51–148 ms.
- Wycofanie sześciu stanowisk na `stary` jednym zapisem: 72 ms; `desk` oddaje wtedy `tryb: "stary"`.

## Oględziny (wbudowana przeglądarka, podgląd na kopii produkcji)

Logowanie bez haseł (ciasteczko testowej sesji z losowym kluczem podglądu). Zrzuty zostały w katalogu sesji
narzędzia, poza repo. Sprawdzone bez usterek:

- **Lista produkcyjna** — 255 kart w kolejności `GET /kolejka` (255/255), plakietki tagów zgodne z API (14 / 29 /
  10), miejsce `#n`; modal priorytetu (szczebel „n z 9”, „Gdzie leży”, historia; 0 → 3 → 0 gwiazdek zapisuje
  i dopisuje historię; Esc zamyka i oddaje fokus; Tab + Enter otwiera); modal drabiny (9 szczebli, kłódka przy
  gwiazdkach, strzałki, liczniki sumują się do 255; zmiana z innej sesji → 409 `drabina_zmieniona` z komunikatem
  i ponownym odczytem; ostrzeżenie o datach dwóch tras); hurt gwiazdek (dymek, potwierdzenie przy zdejmowaniu
  z fokusem na „Anuluj”).
- **Logistyka** — kolumna ★ widoczna przy szerokim kontenerze i schowana przy mapie obok listy; zmiana gwiazdek
  z komórki; sortowanie w obie strony; trasa robocza dostaje szczebel pod ★★★★★; dodanie dwóch przystanków (234 ms
  z przeliczeniem) przenosi zamówienia z miejsc 150 i 151 na 2 i 3 i daje plakietkę trasy na Liście; gwiazdki przy
  przystanku w edytorze trasy.
- **Konfiguracja** — karty „Terminy” (wartości z produkcji: 10 / 21 / robocze) i „Stół stanowisk” (sześć wierszy,
  Lakiernia „Lista (bez stołu)”, próg 3, wersja 0); zapis K; K = 9 → pole podświetlone i komunikat; druga droga
  zapisu zamknięta (`update-config` i `update-configs` → 400); „Start stołów”: podgląd, „Przygotuj”, „Włącz”.
- **Stanowiska** — siedem kart: tryb, „Na stole n/K”, odłożone, kolejka; źródło kafla, „Zdejmij ze stołu”, podpis
  o powrocie przy dopełnieniu; „Niekompletne” z brakującymi pozycjami; Lakiernia jako lista z grupą wykończenia.
- **Modal — akcje stołu** — „Zdejmij ze stołu” i „Wyślij na stanowisko” działają, wpisy w historii.
- **Monitory hali** — Sklejanie i Formatowanie w `stol`: „TERAZ n/K”, „Odłożone” z powodem i „Imię I.”, „Dalej
  w kolejce”, doróbka pierwsza; zmiana z tabletu widoczna po ≤ 30 s bez przeładowania; Lakiernia bez sekcji stołu;
  monitor zbiorczy po randze; w `stary` bez „Dalej w kolejce”.
- **Dashboard** — `high_priority_count` = suma liczników szczebli ★★★★★, ★★★★, „Po terminie” i tras (14).
- **390 px** — Lista bez przewijania poziomego, modal na pełną szerokość.
- **Konsola** — zero błędów JS aplikacji (tylko oczekiwane 4xx z prób odmów).

## Czasy na kopii produkcji (255 zamówień aktywnych)

| Odczyt | Próg | Klient testowy (mediana z 5) | Po HTTP z przeglądarki (stoły zapełnione) |
|---|---|---|---|
| `GET /kolejka` | 1 s | 26 ms (12 zapytań) | 41 ms |
| `GET /kolejka?stanowisko=…` | 1 s | 16–20 ms | 24–25 ms |
| modal priorytetu | 1 s | 66 ms | 47 ms |
| `GET /drabina` | — | 24 ms | 33 ms |
| `GET /stoly` | — | 85 ms | 111 ms |
| zakładka Stanowiska | 1 s | 184 ms (126 zapytań) | 224 ms |
| `dashboard-stats` | — | 33 ms | 45 ms |
| monitor stanowiska / zbiorczy (AJAX) | — | — | 42 / 54 ms |
| `GET desk`, tryb `stary` | 300 ms | 18–65 ms; 304 w 8 ms | — |
| `GET desk`, tryb `stol` | 300 ms | 32–137 ms; 304 w 18–93 ms | 51–148 ms |
| ZAKOŃCZ / Odłóż | — | — | 34–53 ms / 52–165 ms |
| dodanie przystanku z przeliczeniem rang | — | — | 234 ms (samo `utrwal`: 0,02 s bez zmian, 0,34 s pełne) |

Żaden próg nie jest przekroczony. Odpowiedź `desk` Formatowania z dziewięcioma kaflami startowymi ma 343 kB — mniej
niż dzisiejsza pełna lista tego stanowiska (493 kB); zwykły stół to 4–40 kB.

## Ocena uwag z raportów K1–K4b

| Uwaga | Ocena | Dlaczego |
|---|---|---|
| K1 M2 — wyjątek w `uzupelnij()` pomija `utrwal()` w cronie; nieudane przeliczenie nie tworzy zdarzenia Sentry | nie blokuje (D1/K8) | stoły nie zależą od przeliczenia w danej godzinie, wyzwalaczy jest kilkanaście; K7 sprawdza `priorytety_utrwalone.success` w odpowiedzi ręcznego crona |
| K1 M4 — plan blokady pozycji przy pełnej liście | zamknięta | `range` po `idx_order`, blokady tylko na własnych pozycjach (EXPLAIN wyżej) |
| K1 M5 — CLAUDE.md i docstring `blokady_zamowien` | zamknięta | Task 6 |
| K1 M6 — szczebel wirtualny kontra `pozycja_tagu` | nie blokuje (D1/K8) | po wdrożeniu trasy powstają od razu ze szczeblem; na kopii `szczeble_uzupelnione: 0` |
| K2 (a) — odczyt istnienia zamówień przed `try` w gwiazdkach | nie blokuje (K8) | przy błędzie bazy ogólne 500, nic nie zapisane |
| K2 (b) — dwa `PUT /ustawienia` naraz | nie blokuje (K8) | zmierzone: jedno 500 tylko przy brakującym wierszu klucza, powtórka przechodzi |
| K3 D2 — kafel-widmo po hurtowym usunięciu pozycji | nie blokuje (D1) | zmierzone w trybie `widmo`; biuro widzi i zdejmuje |
| K3 D2 — stół o jeden krótszy po `desk` czekającym na ZAKOŃCZ | nie blokuje | zmierzone (57 z 62); dopełnia następny `desk`, który wywoła sygnał z ZAKOŃCZ |
| K3 D5 — sygnał doróbki przepada przy wyjątku po commicie serwisu | nie blokuje (K8) | nadrabia siatka odpytywania |
| K3 D6 — ETag `desk` nie obejmuje szczebla i trasy | nie blokuje (D1/K8) | skutek: plakietka szczebla nieświeża do zmiany rangi |
| K3 D8 — limit odłożeń liczy też wiersze innej jednostki | nie blokuje (K8) | wdrożenie nie zmienia jednostek |
| K3 D9 — `zdejmij_kafel`, `kafel_pozycji` bez wołających | nie blokuje (K8) | opisane w specu 16 |
| K3 D10 — liczba zapytań `desk` | nie blokuje (K8) | zmierzone: ≤ 148 ms po HTTP |
| K3 D11 — rozjazdy specu z kodem | zamknięta | spec 16 i 16.9 |
| K3 „Poza zakresem” 8 — `complete_task` nie sprawdza statusu | nie blokuje (D1/K8) | jest na `main`; w trybie `stol` nowa appka dostaje 409 `pozycja_poza_stanowiskiem` (zmierzone); w `stary` drugie ZAKOŃCZ daje 200 bez zmiany statusu |
| K3 „Poza zakresem” 9 — tekst alertu `realtime_service` | nie blokuje (K8) | K7: sprawdzić przestrzeń `station` w brokerze produkcyjnym |
| K4b — `config_service.update_multiple_configs` nie commituje nowego klucza | nie blokuje (K8) | **warunek z karty nie zachodzi:** ustawienia priorytetów, terminy i „Włącz stoły” idą wyłącznie przez `ustawienia.zapisz` z commitem routera; tej funkcji nie używają |

## Uwagi nieblokujące

**Do runbooka K7 (szczegóły w sekcji „Wejście do runbooka K7”):**

1. Zawieszony broker wydłuża każde ZAKOŃCZ o ok. 1,4 s (publikacja jest synchroniczna; ten sam mechanizm ma dziś
   sygnał agenta druku).
2. Ścieżka crona importu `POST /production/api/sync-cron` kończy się 500 **po** zapisaniu zamówień (tekst `00:00:00`
   trafia do kolumny liczbowej logu synchronizacji) i zostawia wpis „w toku”, który blokuje `manual-sync` kodem 409.
   Zastane, identyczne na `main`; na produkcji nieużywane (w logu synchronizacji są wyłącznie przebiegi ręczne).
   **Import, którego biuro używa naprawdę** — okno synchronizacji na Dashboardzie, `POST
   /production/api/save_selected_orders` — sprawdziłem na kopii produkcji z podmienionym pobraniem z Base.: 200
   w 0,13–0,52 s, nowe zamówienie od razu z rangą (miejsce 195 z 256, szczebel „bez gwiazdek”) i terminem (+10 dni
   roboczych), rangi unikatowe, przeliczenie nie czeka na żadną blokadę. Pozostałe dwie końcówki ręcznej
   synchronizacji: 200 w 136–203 ms, sygnały `cutting` i `assembly`.
3. Squash do `main` musi być scaleniem — `main` ma 5 commitów, których gałąź nie zawiera.
4. Brakujący wiersz `DEADLINE_FINISHED_DAYS` w `prod_config` na produkcji (kod używa 21).
5. Przy cudzej blokadzie zamówienia trzymanej sekundami `desk` wraca po 5–9 s bez dopełnienia, a ZAKOŃCZ kafla
   zamówienia o niższym id może czekać z nim (zmierzone do 5,1 s). W takiej chwili czekające `desk` zajmują też
   workery serwera aplikacji — do obserwacji po wdrożeniu (wpisy o limicie czekania w logu).

**Drobne w UI (do karty po wdrożeniu albo K8), żadna nie psuje pracy:**

6. Po odmowie 409 `drabina_zmieniona` modal czyta drabinę od nowa, ale Lista produkcyjna zostaje przy starej
   kolejności do następnej zmiany albo odświeżenia.
7. Komunikat po „Przygotuj stoły” wymienia kody stanowisk po angielsku („cutting: +0, assembly: +0, gluing: +4…”).
8. Komunikat walidacji ustawień pokazuje ścieżkę pola („stanowiska.gluing.miejsca”) zamiast nazwy z formularza.
9. Nagłówek „Na stole (n/K — ponad K: doróbki, wysłane przez biuro, startowe)” w zakładce Stanowiska wymienia
   doróbki, które od K3-poprawki-1 wchodzą w ramach K.
10. Etykieta „Start stołów” w historii modalu nigdy się nie pokaże (wpis logu nie ma zamówienia).
11. „Przygotuj stoły” i „Włącz stoły” pytają natywnym oknem przeglądarki (działa; inne okna panelu są własne).
12. Zmiana trybu stanowiska nie wysyła sygnału do tabletów: po „Włącz stoły” przechodzą na stół w ciągu 30 s,
    ale po wycofaniu na `stary` tablet z pełnym stołem zauważy zmianę dopiero po 5 min (albo po dowolnej akcji
    na stanowisku). Kontrakt appki §12 obiecywał „najwyżej 30 s” w obie strony — poprawiłem zdanie. Jeden sygnał
    po zapisie trybu skróciłby to do sekund (zmiana kodu — do decyzji, nie w K5).
13. Monitor hali nie pokazuje trybu stanowiska (plan K4b to zapowiadał; jest tylko licznik „Dalej w kolejce”
    w trybie `stol`).
14. Pole `priorytet` w API mobilnym dla pozycji zamówienia nieaktywnego (wyszukiwarka, szczegóły) pokazuje
    szczebel z ostatniego przeliczenia — kosmetyka, opisana w specu 16 (K1.19, K1.26).

**Poza zakresem priorytetów (zastane, do K8 albo osobnych kart):** progi `priority_rank <= 10` w dwóch miejscach
panelu; `rework_service.reject_product_quantity` commituje w serwisie; `processed_mobile_operations` ma na produkcji
ok. 34 tys. wierszy (128 MB) — sprawdzić wpis crontaba sprzątania; martwe klucze starego algorytmu w `prod_config`;
ponowny zapis z okna synchronizacji zamówienia, które już jest w produkcji, dopisuje jego pozycje drugi raz (tryb
`force_update`, kod identyczny na `main`; okno oznacza pozycje będące już w bazie);
plik `MIGRATION_PLAN.md`, do którego odsyła CLAUDE.md, nie jest w repo (celowo); trzy opisy w kodzie logistyki
(docstring modułu `logistics/services/dostawa.py`, `dostawa_api._zapis`, `trasy_api._akcja`) dalej wymieniają
priorytety wśród pisarzy pozycji bez blokady zamówień — komentarze do poprawienia w K8. Trzy uwagi innego rodzaju
przekazałem Konradowi poza repo (plik w katalogu roboczym K5).

## Odstępstwa od planu

1. Skrypt wyścigów własny (`k5_wyscigi.py`), wariant „jeden proces, klienty testowe Flaska, N wątków”; pula
   połączeń procesu powiększona (produkcyjna 2 + 2 na proces udawałaby kolejkę do puli, nie wyścig).
2. 34 tryby zamiast 15: tryby planu, brakujące z raportu K3, trzy z karty i sześć własnych
   (`zakoncz-zakoncz-formatowanie`, `-pakowanie`, `-stary`, `wyslij-zakoncz-stary`, `ustawienia-ustawienia`,
   `utrwal-dostawa-b`) oraz próby `widmo` i `burza`.
3. `desk-dorobka`: plan zakładał powrót doróbki na Sklejanie i wejście ponad K. W kodzie doróbka z Formatowania
   wraca na Wycinanie albo Składanie i wchodzi w ramach K — tryb napisany wg kodu. Pierwsza seria miała 9 odmów
   400 `invalid_quantity` (pozycja testowa z pełnym licznikiem); powtórzona 30/30.
4. Regresja logistyki: trybu `dostarcz-dostarcz` z planu nie ma w skrypcie 4.4b — wykonałem wszystkie 12
   istniejących trybów obu skryptów.
5. Kopia produkcji: baza `priorytety_prod_kopia` (nazwa z karty), zrzut bez DANYCH tabel sesji użytkowników
   (schemat jest), z danymi sesji pracowników hali; kolacja bazy jak na produkcji.
6. Podgląd odcięty od świata także dla geokodera (plan dopuszczał geokoder „jak produkcja”): adresy z kopii nie
   wyszły do żadnej usługi; Base., poczta, Sentry, ORS i mapy wyłączone.
7. „Migracja ×2 na kontenerze `db`” wykonana na bazie `priorytety_wyscigi` (kopia podglądu programu z wykonaną
   logistyką), nie na `woodpower_crm_local` — to baza głównego checkoutu (`main`), której karta każe nie dotykać.
8. API mobilne sprawdzane skryptem HTTP zamiast `curl` (te same żądania, pełny log poza repo).
9. Oględziny: zrzuty tylko w katalogu sesji narzędzia przeglądarki; natywne okna `confirm()` potwierdzane podmianą
   `window.confirm` (wbudowana przeglądarka ich nie pokazuje); płynność przewijania monitora przy odświeżaniu nie
   była sprawdzana (panel bez klatek animacji).
10. Spec 11 nie dostał listy wdrożenia P1 — zgodnie z kartą lista wejściowa do runbooka jest w tym raporcie.
11. Sekcję 16 specu i listę zaszłości przygotowali pomocnicy (repo tylko do odczytu); każdy punkt sprawdzili potem
    z kodem trzej niezależni weryfikatorzy, a punkty o współbieżności — moje pomiary. Wynik weryfikacji: 228
    punktów (159 w sekcji 16 i 69 zaszłości), 44 rozbieżności — 4 błędy rzeczowe i 40 nieścisłości; wszystkie
    poprawione przed zapisem do specu. Nową sekcję CLAUDE.md, docstring, test i sekcję 16.8 przejrzał na końcu
    osobny recenzent (ok. 210 twierdzeń: 0 znalezisk krytycznych, 3 ważne, 16 drobnych — naniesione; jedno
    z ważnych dotyczyło tego raportu: czasy próby `desk-dluga-blokada` opisywały tylko pierwsze powtórzenie).
12. Ponad plan: próbne scalenie z `main` z pełnym pakietem, próby `burza`, seria potwierdzająca, pomiar awarii
    brokera w trzech wariantach.
13. Jedno polecenie odczytu na produkcji wyszło poza sam zrzut (lista procesów serwera aplikacji — liczba workerów).
    Więcej odczytów produkcji nie robiłem; konfigurację brokera i crontab sprawdza K7.
14. **Usterka mojego skryptu, znaleziona przy przywracaniu podglądu:** pierwszy `reset()` w procesie odtwarzał tylko
    część stanu (pomocnik czytający listę kolumn kończył sesję wątku i wycofywał wcześniejsze polecenia resetu).
    Każdy proces serii kończył się jednak pełnym resetem, więc następny startował ze stanu wzorcowego — wyniki
    są ważne. Po poprawce powtórzyłem 8 trybów × 12 przebiegów: bez różnic.

## Rozstrzygnięcia podjęte w trakcie

1. **Wariant skryptu wyścigów: jeden proces z klientami testowymi.** Daje dostęp do bazy dla niezmienników i start
   z bariery co do milisekundy. Koszt, jeśli błędne: przeplecenia przez gunicorna i sieć mogą być inne — łagodzą to
   serie z rozjazdem 15 i 40 ms, przejście API po HTTP i próby `burza`.
2. **Drugi ZAKOŃCZ tego samego kafla = 409 `pozycja_poza_stanowiskiem`** (tryb `stol`, nowa appka; bez wpisu
   idempotencji) — wpisane do specu 16 i kontraktu §6 jako wynik potwierdzony. Koszt: żaden (opis stanu).
3. **1213 w `wyslij-wyslij` i 500 w `ustawienia-ustawienia` to uwagi, nie blokady.** Pierwsze kończy się udanym
   ponowieniem (kryterium karty: „zero 1213 bez ponowienia”), drugie wymaga dwóch adminów zapisujących w tej samej
   chwili nowy klucz. Koszt, jeśli błędne: jeden komunikat „Błąd serwera” przy pierwszym zapisie terminów.
4. **Czekanie ZAKOŃCZ do 5 s przy `desk` zablokowanym cudzą blokadą — uwaga, nie blokada.** Wymaga blokady
   zamówienia trzymanej sekundami (dziś: duży hurt statusu); jest ograniczone limitem. Koszt, jeśli błędne: rzadkie
   kilkusekundowe ZAKOŃCZ — do obserwacji po wdrożeniu (wpisy „limit czekania” w logu).
5. **Test specu pomija się, gdy pliku nie ma.** `docs/superpowers/` jest śledzone tylko na gałęziach programu
   (dziennik centrali, rozstrz. 9) — test czerwony na `main` z powodu braku dokumentu byłby fałszywym alarmem.
   Koszt: na `main` bez dokumentów test nie pilnuje specu.
6. **Zaszłości specu: tabela 16.9 i odsyłacze w treści** zamiast przepisywania 69 miejsc. Spec zostaje czytelny,
   a każda nieaktualna fraza ma znacznik z numerem wiersza tabeli. Koszt: czytelnik musi zajrzeć do 16.9.
7. **Kontrakt appki: dwie poprawki tekstu** (§6 — wynik wyścigu potwierdzony; §8 — nazwa wiersza „cron logistyki”
   zamiast „Dostawa i cron logistyki”). Zachowanie bez zmian; sesja appki pracuje na kopii kontraktu z `34773e9f`.
   Koszt: żaden; centrala może przekazać potwierdzenie sesji appki.
8. **Uwagi spoza zakresu, których nie wolno opisywać w publicznym repo, zostały poza repo.**
9. **Środowisko K5 zostawiam do decyzji Konrada** (patrz „Stan gałęzi i środowiska”); zrzut produkcji usunięty.

## Pytania do Konrada

1. **Squash do `main`:** potwierdzasz, że gałąź wdrożeniowa powstaje przez `git merge --squash` na `main` (z pięcioma
   commitami `main` w środku), a nie przez podstawienie drzewa gałęzi priorytetów? Przy podstawieniu drzewa cofnęłyby
   się: mnożnik w wycenach sklepu, „APK domyślnie nieaktywny” i m² lakierni w raportach.
2. **Dokumenty programu w `main`** (`docs/superpowers/…`, rozstrz. 9 centrali) — wchodzą czy nie? K5 jest
   przygotowany na oba warianty.
3. **Terminy na produkcji:** `DEADLINE_DEFAULT_DAYS` = 10 dni roboczych (opis pola mówi „domyślnie 16”), a wiersza
   `DEADLINE_FINISHED_DAYS` nie ma (działa 21 z kodu). Czy 10 / 21 to wartości zamierzone? Karta „Terminy” pokaże je
   po wdrożeniu.
4. **Notatka odłożenia na telewizorze hali** — monitor pokazuje powód i treść notatki („inne”: tekst wpisany na
   tablecie) oraz „Imię I.”. Zostaje?
5. **Drobne w UI (p. 6–11 wyżej)** — osobna mała karta po wdrożeniu czy K8?
6. **Środowisko K5** — sprzątnąć od razu (kontenery `priorytety-k5`, `k5-centrifugo`, bazy `priorytety_prod_kopia`,
   `priorytety_wyscigi`) czy zostawić do czwartku jako podgląd na danych produkcji z brokerem (127.0.0.1:5006)?
7. Otwarte z wcześniejszych kroków, potwierdzone w działaniu, bez decyzji w dzienniku: próg „Blisko terminu”
   w zakresie 0–15 dni, `GET /ustawienia` tylko dla admina (gwiazdki i drabinę zmienia całe biuro), alert „Dużo
   pilnych zamówień” powyżej 10.

## Stan gałęzi i środowiska

- Commity K5 na `claude/priorytety-produkcji`: `be539b9f` (Task 6 — dokumentacja i test, wypchnięty) oraz commit tego
  raportu z odhaczonym planem (Task 7). `main` nietknięty; bez `--force`.
- Kod aplikacji: zmienione wyłącznie dwa docstringi w `modules/production/services/blokady_zamowien.py`. Nowy plik testów
  `tests/test_priorytety_dokumentacja.py`. Migracji brak.
- Poza repo (`woodpower-podglady/priorytety/k5/`): skrypty, logi, wyniki, notatki. **Zrzut produkcji usunięty**
  przed zapisaniem tego raportu (plik zrzutu i kopia robocza bazy wyjściowej wyścigów w kontenerze bazy).
- Podgląd na kopii produkcji przywrócony do stanu „po wdrożeniu”: wszystkie stanowiska `stary`, próg wersji 0,
  stoły puste, bez tras i gwiazdek, rangi po cronie. Działa pod 127.0.0.1:5006 (kontener `priorytety-k5`), broker
  testowy `k5-centrifugo`; bazy `priorytety_prod_kopia` i `priorytety_wyscigi` w kontenerze `db`. Podglądów i baz
  logistyki nie dotykałem. Zmienne serwera MySQL (`general_log`, `innodb_print_all_deadlocks`) przywrócone.
- Tymczasowy worktree próbnego scalenia z `main` usunięty; nic z niego nie wyszło poza komputer.

## Wejście do runbooka K7

Runbook pisze K7 (jedno okno: logistyka 1–4, priorytety, nowa appka). Poniżej to, co K5 zmierzył albo znalazł —
do wklejenia obok planu wdrożenia logistyki.

**A. Przed oknem**

1. **Hash i squash.** Wdrażany stan = czubek `claude/priorytety-produkcji` po commicie tego raportu (dokumentacja `be539b9f` + raport)
   scalony z `main` @ `31a0b014`.
   Kontrola po squashu: różnica między drzewem squasha a gałęzią priorytetów to dokładnie 24 pliki z pięciu
   commitów `main` (`c2b312f0`, `b910b07b`, `a71af794`, `0310b6a7`, `31a0b014`). Próbne scalenie w K5: 0 konfliktów,
   6842 passed. Jeśli `main` dostanie kolejne commity — powtórzyć próbne scalenie i pełny pakiet.
2. **Broker na produkcji** (odczyt przed „Włącz stoły”): przestrzeń nazw `station` w konfiguracji Centrifugo,
   `REALTIME.enabled`, `sse_url` i lokalizacja `/realtime/` w nginx. Test: `GET /api/mobile/realtime-token`
   z tabletu → 200 z kanałem stanowiska. K5 produkcyjnego brokera nie czytał.
3. **Crontab:** nowy wpis crona logistyki co godzinę (plan logistyki) — od P1 ten sam przebieg utrwala rangi;
   sprawdzić wpis sprzątania `processed_mobile_operations`.
4. **Nie włączać crona importu** (`sync-cron`) — ścieżka kończy się 500 po zapisie zamówień. Import nowych
   zamówień zostaje przy ręcznej synchronizacji, jak dziś.
5. **Instrukcja dla hali przed przerwą** (z dziennika centrali): „wbijcie licznik na tym, co macie w rękach” —
   kafel startowy powstaje wyłącznie z licznika > 0 pozycji czekającej na stanowisku.

**B. W oknie**

1. **Migracje:** 16 plików, na kopii produkcji 2,2 s łącznie (najdłuższe polecenie 0,21 s). Przebieg robi
   `deploy.sh` przed restartem; błąd migracji sam cofa kod.
2. **Po `Deploy complete!` — raz ręcznie** `scripts/cron_endpoint.sh POST /production/api/logistics/cron`.
   Oczekiwane: HTTP 200 w poniżej sekundy; `szczeble_uzupelnione: 0` (na produkcji nie ma jeszcze tras);
   `priorytety_utrwalone.success: true`, `zamowien` ≈ liczba zamówień aktywnych (5.10: 255), wszystkie zmienione;
   drugi przebieg: 0 zmian. `success: false` → nie przerywać wdrożenia, przeczytać `error` w odpowiedzi i powtórzyć
   cron (1205 = ktoś trzymał blokadę zamówienia ponad 5 s).
3. **Kontrole SQL (bez danych klientów):** 9 szczebli (`SELECT kind, stars, tag, position FROM prod_priority_rungs
   ORDER BY position` — kolejność ze specu 3.1); 38 wierszy `prod_config` (`config_key LIKE 'priorytety\_%'`
   — 37 — i `DEADLINE_DAY_TYPE`); rangi unikatowe wśród zamówień aktywnych (`COUNT(*) = COUNT(DISTINCT
   priority_rank)`); wszystkie `priorytety_tryb_*` = `stary`, `priorytety_min_app_version_code` = 0;
   `prod_station_desk` pusty.
4. **Kontrole w panelu:** Lista produkcyjna po randze (`#1…`), „Drabina priorytetów” — liczniki szczebli sumują
   się do liczby zamówień na liście; Konfiguracja → karty „Terminy” (10 / 21 / robocze) i „Stół stanowisk”;
   zakładka Stanowiska; monitor hali; tablet ze starą appką — lista działa jak dotąd.
5. **Start stołów:** Konfiguracja → „Start stołów” → podgląd (5.10 wieczorem: 14 kafli — Sklejanie 4, Formatowanie
   9, Pakowanie 1) → „Przygotuj stoły” (ok. 0,1 s; można powtarzać) → poprawki przez „Wyślij na stanowisko”
   i „Zdejmij ze stołu” → „Włącz stoły” z minimalną wersją appki = `versionCode` nowej appki (przy 0 serwer odmówi)
   → „Rozpoczęte” na szczyt drabiny. Pierwsze `desk` tabletów dopełnia stoły do K.
6. **Objawy i reakcje:**
   - ZAKOŃCZ trwa ok. 1,5 s zamiast 0,05 s → broker przyjmuje połączenia i nie odpowiada: restart brokera albo
     `REALTIME.enabled=false` w `core.json` **z natychmiastowym restartem aplikacji**; tablety przechodzą na samo
     odpytywanie (30 s / 5 min).
   - Kafel w „Do zdjęcia ze stołu” (zakładka Stanowiska) → „Zdejmij”; powstaje po hurtowym usunięciu pozycji.
   - Tablet dostaje 409 `pozycja_poza_stanowiskiem` → pozycję zamknął inny tablet albo zmieniło ją biuro; appka
     odświeża stół.
   - Stoły do wycofania → tryb „zgodność” w karcie „Stół stanowisk” (jeden zapis, ok. 0,1 s). Zmiana trybu nie
     wysyła sygnału: nowa appka wraca na listę przy najbliższym `desk` — do 30 s przy niepełnym stole, do 5 min
     przy pełnym (szybciej: wejście na ekran stanowiska od nowa). Kafle zostają w tabeli i wrócą po ponownym
     włączeniu. Po „Włącz stoły” tablety przechodzą na stół w ciągu 30 s.
7. **Wycofanie całego wdrożenia:** według planu logistyki (migracja cofająca statusy logistyki); tabele i kolumny
   priorytetów zostają, stary kod ich nie czyta. Próbę wycofania przewiduje próba wdrożenia (rozstrz. 20) — K5 jej
   nie wykonywał.

**C. Po wdrożeniu**

1. Cron co godzinę: `priorytety_utrwalone.success` i `duration_seconds` (odniesienie: 0,02 s bez zmian, 0,34 s
   pełne przeliczenie 255 zamówień).
2. Log aplikacji: wpisy o limicie czekania 5 s (1205) i ponowieniach po 1213 — oczekiwane rzadko; częste =
   meldunek z porą i końcówką.
3. Czasy odniesienia: `desk` 50–150 ms, ZAKOŃCZ 35–55 ms, `/kolejka` 40 ms, zakładka Stanowiska 220 ms.
4. Regresja wyścigów po zmianach w blokadach: nazwy trybów ze specu 16.8; sześć obowiązkowych po 62 przebiegi.
5. Pomiar skutku (po przejściu hali na stoły): `scripts/symulacja_priorytetow.py` na danych produkcji — udział
   zakończeń z pominięciem pilniejszego (przed zmianą 84–96 %).

## Co następny krok musi wiedzieć

- **Sesja appki / odbiór:** drugi ZAKOŃCZ tej samej pozycji z innego tabletu → 409 `pozycja_poza_stanowiskiem`
  (potwierdzone 90 + 12 przebiegami na trzech stanowiskach); `desk` może w rzadkim przypadku wracać po 5–9 s
  (limit czekania, zmierzone maks. 9,1 s) — limit czasu żądania 15 s z kontraktu wystarcza; przy zawieszonym brokerze akcje są dłuższe o 0,7–1,4
  s; największa odpowiedź `desk` po starcie stołów: 343 kB (Formatowanie, 9 kafli-zamówień).
- **K7:** sekcja „Wejście do runbooka K7”.
- **D1 / K8:** tabela „Ocena uwag” i lista „Uwagi nieblokujące”; indeks `ix_prod_station_desk_station_code` do
  usunięcia po sprawdzeniu planów; wiersz blokady na „Wyślij” na puste stoły (1213 z ponowieniem) nie wymaga zmian.

## Werdykt

**P1 GOTOWE DO WDROŻENIA.** Wszystkie kryteria zakończenia planu K5 (1–9) są spełnione: pełny pakiet i `blog_seo`
zielone, migracje przechodzą na kopii produkcji i powtarzają się bez zmian, algorytm zgadza się z symulacją, wyścigi
na MySQL nie dały ani jednego zakleszczenia bez ponowienia ani złamanego niezmiennika stołu, kolejność blokad
odpowiada kontraktowi, sygnały idą po commicie na właściwe kanały, czasy mieszczą się w progach, a CLAUDE.md i spec
opisują stan kodu. Uwagi z sekcji „Uwagi nieblokujące” i „Pytania do Konrada” nie wstrzymują czwartkowego okna.
