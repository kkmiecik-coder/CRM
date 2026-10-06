# Raport — próba wdrożenia i wycofania na Windowsie (6.10.2026), program „Priorytety produkcji”

- **Data:** 2026-10-06, 09:30–11:05
- **Sesja:** lokalna (Windows, repo CRM). **Model: Opus 5.5, effort high** (zgodnie z kartą).
- **Karta:** „próba wdrożenia na Windowsie (wtorek 6.10)”, rozstrzygnięcia 20, 25 dziennika centrali
- **Udział Konrada:** tablet z appką **1.8.0-debug / vc 44** podłączony kablem do tego komputera (`adb reverse tcp:5020`).
  Konrad zarejestrował tablet, a resztę obsługi tabletu prowadziła sesja przez `adb` (stuknięcia, przewijanie,
  zrzuty ekranu).
- **Wdrożenie produkcyjne:** czwartek 8.10, przerwa 10:30

## Werdykt

**Czwartek jest bezpieczny.** Przeszedłem cały dzień dwa razy na świeżej kopii produkcji, dokładnie na commitach,
które pójdą na produkcję: przebieg 1 (serwer i curl) i przebieg 2 (z tabletem). Kolejność była taka: stan sprzed
wdrożenia → wdrożenie → start stołów → scenariusze → wycofanie stanowiska → wycofanie całości przy włączonych stołach
→ ponowne wdrożenie. W żadnym kroku nie pojawił się nowy błąd 500 ani `LookupError`. Kolejka offline tabletu przetrwała
oba restarty, a appka sama przechodziła między listą a stołem w obie strony, bez restartu.

Nic nie blokuje czwartku. Wyszły **dwie rzeczy do runbooka** dotyczące tylko scenariusza wycofania:
- tryby stanowisk i próg wersji zostają po wycofaniu, więc trzeba je zresetować;
- przed ponownym wdrożeniem trzeba posprzątać widma ze stołów.

Szczegóły w „Znaleziskach” 1–2, gotowe polecenia w runbooku E8 i F1.

## Stan wejściowy (sprawdzony)

| Co | Wynik |
|---|---|
| `origin/main` | `31a0b0145b222799234674bdf1e995dab6791a0c` |
| serwer: `git rev-parse HEAD` w katalogu aplikacji (ssh, odczyt) | `31a0b0145b222799234674bdf1e995dab6791a0c` = `origin/main` |
| `claude/wdrozenie-2026-10-08` | `5e944a55978f659ca38a69d09d74b50a5a4d841e` |
| `claude/wycofanie-2026-10-08` | `8e14937e8497fdf9a27c5ba0db97e739b9057ccc` |
| `requirements.txt` `31a0b014` → `5e944a55` | bez zmian (`pip install` nic nie instaluje) |
| migracje `31a0b014` → `5e944a55` | 17 plików |

**Odczyt produkcji (ssh, tylko odczyt, sekrety odfiltrowane):**
- supervisor `crm_woodpower`: `venv/bin/gunicorn -w 4 -b 127.0.0.1:8090 app:app` (worker sync, domyślny timeout 30 s);
- **Python w venv: 3.12.3**, nie 3.9 (CLAUDE.md jest tu nieaktualny); gunicorn 21.2.0;
- MySQL: Percona 8.4.11, `utf8mb4_general_ci`, REPEATABLE-READ;
- Centrifugo v6.9.1: namespace `print` i `station`, `uni_sse` włączony; nginx: `/realtime/api` → 403, `/realtime/` → broker bez buforowania;
- `REALTIME`: `enabled: true`, **`sse_url` = `https://crm.woodpower.pl/realtime/connection/uni_sse`** (https — warunek
  release appki spełniony), `token_ttl_seconds` 3600, `connect_timeout` 0,3 s, `read_timeout` 0,7 s;
- `/etc/cron.d/woodpower-crm`: **wpis crona logistyki już jest** (`0 * * * *`, `POST /production/api/logistics/cron`).
  Dziś co godzinę dostaje 404, bo `main` nie ma tej trasy (log `cron-endpointy.log`, ostatni wpis 10:00);
- dane 6.10 rano: 592 aktywne pozycje, `is_priority` 69, ręczne blokady 6, 57 wpisów `schema_migrations`,
  tabeli `zz_przed_wdrozeniem…` brak.

## Środowisko próby

Stack `docker compose -p priorytety-proba` (plik `compose.yml` poza repo, `woodpower-podglady/priorytety/proba/`),
worktree `.claude/worktrees/priorytety-proba` z odłączonym HEAD (zmiana kodu = `git checkout --detach <hash>`).

| Kontener | Rola | Sieć |
|---|---|---|
| `db` | MySQL 8.4 (`utf8mb4_general_ci`), baza `crm`, wolumen `priorytety-proba_db_data` | `wewn` |
| `centrifugo` | Centrifugo **v6.9.1** (jak produkcja), losowe klucze, namespace `print` + `station` | `wewn` |
| `app` | obraz z repo (Python 3.12, jak produkcja), **gunicorn `-w 4` sync**, `FLASK_ENV=production`, `core.json` próby (montowany) | `wewn` |
| `edge` | nginx jak na produkcji: `/realtime/api` 403, `/realtime/` → broker (SSE bez buforowania), reszta → gunicorn; publikuje 127.0.0.1:**5020** (app), **8021** (broker), **3320** (MySQL) | `wewn` + `publ` |

**Ruch zewnętrzny zablokowany od pierwszego uruchomienia aplikacji:**
- sieć `wewn` ma `internal: true` (Docker nie publikuje z niej portów, stąd bramka `edge`);
- zaślepki `extra_hosts` → 127.0.0.1: Base., ORS, GUGiK, Nominatim, GlobKurier, Sentry, GitHub, Google AI, OpenAI, MF, GUS, CEIDG, CARTO, poczta;
- `core.json` próby: puste klucze Base., poczty, GlobKurier, AI, CEIDG, Sentry, ORS, CARTO, Chatwoot; reszta kluczy losowa.

**Kontrola przed uruchomieniem aplikacji z danymi** (z kontenera `app`, `docker compose run`):
- `example.com` i `google.com` → brak DNS;
- `1.1.1.1` i `8.8.8.8` → sieć nieosiągalna;
- GUGiK, Nominatim, Base. → odmowa połączenia;
- `db` i `centrifugo` → osiągalne.

W logu aplikacji geokoder dostał „GUGiK/Nominatim nie odpowiedział”. Żaden adres z kopii nie wyszedł na zewnątrz.

**Zrzut produkcji:**
- 6.10 09:42, `mysqldump --single-transaction --quick --routines --no-tablespaces --set-gtid-purged=OFF`, strumieniem przez ssh;
- dane `user_sessions` i `public_sessions` pominięte (schemat jest);
- 63 MB gz, 18 s; import 66 s;
- wynik: 85 tabel, 1912 zamówień, 4400 pozycji, 592 aktywne, 57 migracji.

## Tabela kroków

Czasy z przebiegu 1 (serwer), w nawiasie przebieg 2 (z tabletem). „Niedostępność” = od restartu do pierwszej odpowiedzi 200.

| Krok | Co | Czas | Wynik | Dowód |
|---|---|---|---|---|
| 1 | stan przed: kopia + stary kod `31a0b014` na gunicornie | start gunicorna 8,3 s | panel 200, lista tabletu 200 | `wyniki/przebieg1/dziennik.txt` |
| 1b | **tablet:** appka 1.8.0 na starym backendzie | — | zwykła lista Sklejania, bez komunikatu błędu; `desk` 404 HTML, `realtime-token` 404 HTML, lista 200, `summary` 200 (§12) | zrzut `tablet-1b.png`, log bramki |
| 2 | A3 — kopia ręcznych priorytetów | 0,41 s | 592 wiersze (`is_priority` 69, blokady 6) | — |
| 3 | wdrożenie `5e944a55` odwzorowujące `deploy.sh` | cały deploy 35,4 s | 17/17 migracji, 0 porażek | `deploy-wdrozenie.log` |
| 3a | ├ `git checkout --detach` | 0,9 s | | |
| 3b | ├ `pip install -r requirements.txt` | 8,3 s* | wymagania bez zmian | *artefakt odcięcia sieci, patrz Odstępstwa 3 |
| 3c | ├ `flask sync-changelog` — **tu `create_app()` wykonuje migracje** | 9,4 s, w tym **migracje 2,43 s** (2,32 s) | 17 plików | znaczniki czasu per plik w logu |
| 3d | ├ `flask migrate` (bramka) | 4,8 s | „Wykonano 0 migracji”, RC 0 | |
| 3e | ├ `przelicz_klientow_sprzedazy.py --apply` | 6,1 s | 0 klientów do poprawy | |
| 3f | └ restart gunicorna (`docker restart` ≈ `supervisorctl restart`) | **niedostępność 5,6 s**: 502 przez ~1,3 s, potem żądania czekają na workery | `/login`, lista tabletu, lista produkcyjna: 3 × 502 każde | `sonda-wdrozenie.tsv` |
| 3g | stary kod na zmigrowanej bazie (okno między migracją a restartem, 12 s) | — | 25/25 × 200 na każdym z trzech adresów | sonda |
| 3h | **tablet:** ZAKOŃCZ w trakcie restartu (kolejka offline) | kolejka wysłana 37 s po starcie serwera | baner „HTTP 502”, licznik kolejki 2 (licznik + ZAKOŃCZ) → po starcie oba 200, pozycja przeszła dalej; curl: 502 → ponowienie z tym samym `X-Operation-Id` → 200 | `tablet-3a.png`, `kolejka-wdrozenie.log` |
| 3i | **tablet:** lista na nowym backendzie | — | `desk` → `tryb: "stary"`, appka zostaje na liście | log bramki |
| 4 | ręczny cron logistyki | 0,45 s (0,35 s) | 200, `priorytety_utrwalone.success: true`, 249 zamówień / 592 pozycje, wszystkie zmienione; drugi przebieg 0,03 s, 0 zmian | `cron-wdrozenie-1.json` |
| 4 | kontrole SQL B4 | — | terminy 10 / 14 / robocze; 9 szczebli w kolejności; 37 + 1 kluczy; 249 zamówień, 249 rang unikatowych, 0 bez rangi; 7 × `stary`; próg 0; stół pusty; 17 migracji | `b4-wdrozenie.txt` |
| 4 | panel (wbudowana przeglądarka) | — | Lista produkcyjna (#1…, 249 zamówień); Drabina: 9 szczebli, liczniki 16+46+3+184 = 249; Konfiguracja: Terminy 10/14, Stół stanowisk (6 × zgodność, Lakiernia lista, próg 0), Start stołów; zakładka Stanowiska; Logistyka bez 500 (bez kluczy mapy); monitor hali (po dopisaniu IP bramki, patrz Odstępstwa 4); 0 błędów JS | — |
| 4 | przegląd tras GET (`wdr_smoke.py`) | 21 s | 729 adresów: 478 × 200, **33 × 500 — dokładnie te zastane co w pakiecie** (30 × pakiety Base. bez klucza, lista kurierów, 2 × `TemplateNotFound`), **0 × `LookupError`** | `smoke-wdrozenie-stoly.json` |
| 5 | kontrola heartbeatu | — | tablety próby vc 44, stara appka vc 38; **produkcja: patrz Znalezisko 4** | — |
| 5 | podgląd „Start stołów” | 0,07 s | **20 kafli: Sklejanie 11, Formatowanie 8, Pakowanie 1** (w przebiegu 2 to samo) | `GET /start` |
| 5 | „Przygotuj stoły” | **0,13 s** (0,11 s) | +11 / +8 / +1; powtórka idempotentna | — |
| 5 | „Wyślij na stanowisko” / „Zdejmij ze stołu” | 0,03 s / 0,03 s | 2 kafle „biuro”; zdjęcie jednego; ponowne „Wyślij” dokłada tylko brakujący | — |
| 5 | „Włącz stoły” przy progu 0 | 0,02 s | **400 `prog_wersji_wymagany`** (także bez pola progu) | — |
| 5 | „Włącz stoły” z progiem **44** | **0,04 s** | 6 × `stol`, Lakiernia `stary`, `przeliczenie: niepotrzebne` | — |
| 5 | „Rozpoczęte” na szczyt drabiny | 0,16 s | przeliczenie ok; 9+16+40+184 = 249 | — |
| 5b | **tablet:** przejście na stół | **4 s** od „Włącz” (maks. 30 s — takt `desk` na liście) | „TERAZ · 11”, kafle z plakietką „rozpoczęte przed startem”, bez restartu appki | `tablet-5b.png` |
| 5b | rozmiar `desk` | — | **Formatowanie 343 kB / 0,19 s** (8 kafli-zamówień + 2 niekompletne; tablet pobrał tyle samo); Sklejanie 44 kB, Pakowanie 40 kB, Krawędzie 12 kB, Wycinanie i Składanie 4 kB | `desk-*-po-wlacz.json` |
| 6 | scenariusze curl (`s6.py`) | — | **34 / 34 zgodne z kontraktem** (lista niżej) | `wyniki/przebieg1/s6.txt` |
| 6 | **tablet:** scenariusze | — | wszystkie zgodne (lista niżej) | zrzuty `tablet-6*.png`, `tablet-pak*.png`, `tablet-fmt*.png`, `tablet-lak1.png` |
| 6 | sygnał przez broker | — | „Zdejmij” w panelu → ramka po **0,15 s**; ZAKOŃCZ starej appki → **0,19 s**; „Wyślij” → tablet pobrał `desk` w tej samej sekundzie; ping co **25,0 s** | `sse-gluing.log` |
| 6 | broker zawieszony / wyłączony | — | ZAKOŃCZ **1,445 s** (×4, zawieszony) / 0,04 s (wyłączony, odmowa połączenia); `desk` i `realtime-token` bez zmian | `broker.txt` |
| 7 | Sklejanie → `stary` (bez wdrożenia) | zapis 0,03 s | `desk` od razu `tryb: "stary"`, bez dopełniania; ZAKOŃCZ spoza stołu bez bramki (200); wiersze stołu zostają | — |
| 7 | **tablet:** powrót na listę przy **pełnym** stole | **288 s** (takt 5 min) | zgodnie z K5 (zmiana trybu nie wysyła sygnału) | log bramki |
| 7 | **tablet:** Sklejanie → `stol` ponownie | **19 s** | stół wraca z tymi samymi kaflami | `tablet-7b.png` |
| 8 | kroki C przed wycofaniem | — | C1 0; C2 0 (w przebiegu 1: 1 — moje „kurier” bez klucza Base.); **C3: 44 (40) zamówień w pakowaniu bez sposobu dostawy** | `c_przed.sql` |
| 8 | wycofanie `8e14937e` (jak `deploy.sh`), stoły włączone | cały deploy 32,8 s; **migracja cofająca 0,055 s** (44 polecenia) | 1/1, 0 porażek; `flask migrate` 0 | `deploy-wycofanie.log` |
| 8 | ├ nowy kod na cofniętych danych (okno przed restartem, 12 s) | — | 24/24 × 200 na każdym adresie | `sonda-wycofanie.tsv` |
| 8 | └ restart | niedostępność **6,2–6,7 s** | 3 × 502 | |
| 8 | C6: ręczny drugi przebieg `mysql crm < migrations/2026-10-08-wycofanie-logistyki.sql` | **0,42 s** (0,48 s) | RC 0, 0 błędów | `c6.txt` |
| 8 | C7 | — | **wszystkie 0** (7 kontroli); kopia A3 przywrócona **588/588** (590/590) pozycji w produkcji; stół (22–26 wierszy) zostaje | `c7.txt` |
| 8 | przegląd tras starego kodu | — | 679 adresów: 448 × 200, te same 33 zastane × 500, **0 × `LookupError`** | `smoke-wycofanie.json` |
| 8b | **tablet:** appka na starym backendzie | — | `desk` 404 HTML → **sama wraca na listę bez restartu**; ZAKOŃCZ z kolejki (wysłany w trakcie restartu, 502) doszedł 200 na starym kodzie 17 s po starcie serwera; plakietki dostawy wracają do tekstu Base. („KURIER”, „ODBIÓR OSOBISTY”) | `tablet-8a.png`, `tablet-8b.png` |
| 8b | ZAKOŃCZ starym kodem pozycji leżących na stołach | — | tablet + curl: Sklejanie, Formatowanie (zamówienie), Pakowanie (zamówienie), Wycinanie | `widma_zakoncz.txt` |
| 9 | ponowne wdrożenie `5e944a55` | cały deploy 40,7 s (34,9 s) | **0 migracji**; cron 200, 246 zamówień, 2. przebieg 0 zmian; B4 jak w kroku 4, ale `schema_migrations` od 25.09 = **18** (17 + cofająca) | `deploy-ponowne*.log` |
| 9 | widma (przebieg 1, bez sprzątania) | — | **6 wierszy stołu** (Wycinanie 1, Sklejanie 3, Formatowanie 1, Pakowanie 1); tablety w `stol` od razu (tryby zostały) — widma na stole, ZAKOŃCZ → 409 | `widma.sql` |
| 9 | sprzątanie widm (przebieg 1: „Zdejmij” na jednym + tryby `stary` → `DELETE` → „Przygotuj” → „Włącz”) | `DELETE` 25 wierszy | **0 widm**, wszystkie `desk` w `stol` | panel: `widma` 0 na wszystkich stanowiskach |
| 9 | sprzątanie w kolejności runbooka (przebieg 2: SQL **przed** ponownym wdrożeniem, na starym kodzie) | 0,39 s | 6 trybów → `stary`, 22 wiersze usunięte (4 widma) | `przed_ponownym.sql` |
| 9b | **tablet:** po ponownym wdrożeniu | — | zostaje na liście (`stary`); „Przygotuj” (Sklejanie 7, Formatowanie 7) → „Włącz” (44) → stół w ≤ 31 s, „TERAZ · 7”, **bez widm** | `tablet-9b.png` |
| 9 | przegląd tras końcowy | — | 729 adresów: 478 × 200, te same 33 zastane × 500, 0 × `LookupError` | `smoke-ponowne2.json` |

Wyniki (bez danych klientów: id, kody, czasy) leżą w `woodpower-podglady/priorytety/proba/wyniki/`:
`przebieg1/` (serwer) i katalog główny (przebieg 2 z tabletem, zrzuty ekranu tabletu).

### Scenariusze kroku 6 (curl jako tablety vc 44, druga pozycja `GLUING-3`, stara appka vc 38)

Sklejanie:
- ZAKOŃCZ kafla ze stołu → 200 (0,06 s), drugi tablet na tym samym kaflu → **409 `pozycja_poza_stanowiskiem`**;
- licznik → 200;
- Odłóż `brak_materialu` → 200, `odlozone` 1;
- Odłóż „inne” bez notatki → 400 `powod_niepoprawny`, zły zakres → 400 `dane_niepoprawne`;
- ZAKOŃCZ spoza stołu: nowa appka → **409 `nie_na_stole`**, stara appka → 200 (bez bramki);
- 10 odłożeń → jedenaste **409 `limit_odlozen`**;
- „Wyślij” odłożonego → wraca (`przywrocone`).

Formatowanie:
- ZAKOŃCZ obu pozycji kafla-zamówienia → kafel schodzi;
- ZAKOŃCZ pozycji z „Niekompletnych” → 200;
- **pozycja bez docięcia:** na produkcji nie ma dziś aktywnej, więc ustawiłem w kopii `cut_to_size=0` na jedynej
  brakującej pozycji zamówienia z „Niekompletnych”. Zamówienie przeszło do kolejki Formatowania (miejsce 2 z 39).

Pakowanie:
- zamówienie bez sposobu dostawy jest na stole, ZAKOŃCZ × 3 → 200, paczki → 200;
- sposób „kurier” z Logistyki → ZAKOŃCZ → 200, paczki → 200.

Krawędzie i Lakiernia:
- `desk` Krawędzi → 200;
- lista Lakierni z tabletu Krawędzi: 35 pozycji, 6 grup wykończenia, każda grupa w ciągu;
- Odłóż na Lakierni → **409 `stanowisko_bez_stolu`**;
- ZAKOŃCZ Lakierni z tabletu Krawędzi → 200;
- ZAKOŃCZ Krawędzi ze stołu → 200.

### Scenariusze kroku 6 na tablecie

- **Sygnał:** „Wyślij na stanowisko” w panelu → tablet pobrał stół w tej samej sekundzie; kafle „wysłane przez biuro”
  na początku stołu.
- **ZAKOŃCZ:** „+” → licznik 1/1 (PATCH 200) → ZAKOŃCZ → okno „Zapisuję… / ANULUJ” (ok. 8 s) → 200 → kafel schodzi,
  „Wykonano dziś” +1.
- **Odłóż:** okno z pięcioma powodami i notatką (ODŁÓŻ nieaktywne bez powodu) → 200 → kafel znika ze stołu.
- **Punkt 12 odbioru — Odłóż bez sieci, wariant „serwer nieosiągalny”:** zdjęty `adb reverse` i zerwane połączenia
  bramki. Appka pokazała komunikat „Nie udało się odłożyć — brak odpowiedzi serwera. Sprawdź stół i spróbuj ponownie.”
  i baner „Błąd synchronizacji — pokazuję ostatni znany stół”. **Kafel zostaje, do kolejki nic nie trafia** — zgodnie
  z kontraktem (Odłóż tylko online). Pierwsza próba się nie liczy: `adb reverse --remove` nie zrywa otwartego
  połączenia, więc Odłóż poszło. Wariant „Wi-Fi wyłączone” (tryb samolotowy) nie był sprawdzany, patrz Odstępstwa 7.
- **Drugi tablet na tym samym kaflu:** broker wstrzymany (bez sygnału), curl zamknął kafel, tablet nacisnął ZAKOŃCZ.
  Wynik: 409, komunikat „Pozycja 1519_1 nie czeka na Sklejaniu.”, wpis porzucony, stół pobrany od nowa (kafla już
  nie ma).
- **Pakowanie:** okno paczek po ZAKOŃCZ działa dla zamówienia **ze sposobem** (transport własny: szacunek ok. 635 kg,
  podpowiedź 1 × paleta EURO) i **bez sposobu** (plakietka „Sposób dostawy do ustalenia – pakuj normalnie”,
  podpowiedź 1 × paczka). Oba `PUT packages` → 200, komunikat „Zadeklarowano … Etykiety poszły do drukarki paczek.”,
  stół dopełnił się następnym zamówieniem.
- **Formatowanie:** stół 343 kB wyświetla się płynnie. Sekcja „NIEKOMPLETNE · 2” pokazuje „3/11 na stanowisku,
  8 na Sklejaniu — Brakuje: …” i „2/3 na stanowisku, 1 na Składaniu — Brakuje: …”.
- **Krawędzie:** stół 2 kafli z panelem roboczym. **Lakiernia:** lista pogrupowana po wykończeniu
  („LAKIEROWANE · BEZBARWNIE · PÓŁMATOWY · 24 poz.”), bez stołu.
- **Zmiana stanowiska na tablecie:** potwierdzenie „Zmienić stanowisko tabletu?”, ponowna rejestracja (200),
  heartbeat, nowy token SSE.

## Znaleziska

| # | Objaw | Kroki | Blokuje czwartek? | Reakcja |
|---|---|---|---|---|
| 1 | **Po wycofaniu tryby stanowisk zostają `stol`, a próg wersji 44.** Migracja cofająca nie rusza `prod_config`. Przy ponownym wdrożeniu tablety wchodzą od razu na stół, z widmami i starymi kaflami startowymi, zanim ktokolwiek zrobi „Przygotuj stoły”. | krok 8 → 9 (przebieg 1): po ponownym wdrożeniu B4 pokazało 6 × `stol`, próg 44 | **nie** — dotyczy tylko scenariusza wycofania i ponownego wdrożenia | runbook E8: po wycofaniu `UPDATE` trybów na `stary` (SQL, stary kod nie ma tej karty). Ponowne wdrożenie startuje wtedy jak pierwsze |
| 2 | **Widma po wycofaniu.** ZAKOŃCZ starego kodu (także z kolejki offline w trakcie restartu) nie zdejmuje wierszy stołu. Po ponownym wdrożeniu `desk` je **pokazuje** (`zdejmij_nieaktualne` działa tylko przy zapisie danego zamówienia). ZAKOŃCZ widma → 409 `pozycja_poza_stanowiskiem`, appka porzuca wpis, kafel **zostaje**. Widmo zajmuje też miejsce K. | krok 8b → 9: 6 widm (przebieg 1), 4 (przebieg 2); panel (zakładka Stanowiska) liczy je w polu `widma` | **nie** | rekomendacja centrali **potwierdzona:** `DELETE FROM prod_station_desk` przed „Przygotuj stoły” wystarcza i niczego nie psuje (stary kod tej tabeli nie czyta; nowy po „Przygotuj” odbudowuje kafle startowe). Kasuje też odłożenia i kafle „biuro” sprzed wycofania — biuro wyśle je ponownie. Najlepiej na starym kodzie, **przed** pushem ponownego wdrożenia (runbook F1). Pojedyncze widmo usuwa „Zdejmij ze stołu” (200) |
| 3 | **Przed wycofaniem logistyk musi ustawić sposób dostawy dla ok. 40–44 zamówień w pakowaniu** (C3; decyzja Konrada 6.10, pytanie 2 pakietu). Na kopii z 6.10 rano sposób miało 1 z 249 zamówień, a po wdrożeniu wszystkie kafle pokazują „NIE USTAWIONO”. | krok 8, `c_przed.sql` | **nie** | runbook E3: hurt w Logistyce. Liczba rośnie z każdym dniem po wdrożeniu, jeśli logistyk nie ustawia sposobów na bieżąco |
| 4 | **Kontrola heartbeatu musi liczyć tylko używane tablety.** W `prod_devices` produkcji wiszą stare, nieużywane tablety (`is_active=1`, np. 8 na Składaniu), a zapytanie po wszystkich zawsze pokaże „starsze”. W ostatnich 24 h widziane: Składanie 5 (w tym jeden vc 29 / 1.1.0-debug), Sklejanie 2, Pakowanie 2, Formatowanie 1, Krawędzie 1, **Wycinanie 0**. Dziś wszystkie na 1.6.3 / vc 38, a 1.7.3 nie było aktywne. | odczyt kopii z 6.10 | **nie** | runbook A6: zapytanie z `last_seen_at >= NOW() - INTERVAL 1 DAY`; tablet bez heartbeatu ≥ 44 → aktualizacja APK przed „Włącz stoły”, inaczej ten tablet zostaje „starą appką” (bez bramki stołu, jego ZAKOŃCZ i tak zdejmuje kafel) |
| 5 | **Appka po wysłaniu kolejki offline pokazuje zakończony kafel jeszcze do 60 s** (tryb listy). Pobrała listę o :52, a kolejkę wysłała o :53; kafel zniknął przy następnym odświeżeniu listy. | krok 3h, przebieg 2 | **nie** (kosmetyka; dotyczy minuty po restarcie) | karta appki po wdrożeniu: po wysłaniu kolejki odświeżyć listę (albo wysyłać kolejkę przed pobraniem listy) |
| 6 | **Wskaźnik „ONLINE” w appce zależy od Wi-Fi, nie od serwera.** Przy nieosiągalnym serwerze świeci „ONLINE” obok czerwonego banera „Błąd synchronizacji”. | krok 6, punkt 12 | **nie** | informacyjnie dla hali: liczy się baner |
| 7 | **CLAUDE.md:** „venv w katalogu aplikacji (Python 3.9)” — na serwerze jest 3.12.3. Pakiet (odstępstwo 7) opierał się na tym zdaniu. | odczyt produkcji | **nie** | poprawka CLAUDE.md po wdrożeniu (karta dokumentacyjna) |
| 8 | **Cron logistyki już jest w `/etc/cron.d/woodpower-crm`** i dziś co godzinę dostaje 404. Po wdrożeniu o 10:30 pierwszy automatyczny przebieg będzie o 11:00. Po wycofaniu znów 404 co godzinę (szum w `cron-endpointy.log`, bez skutków). | odczyt produkcji | **nie** | runbook A5 i E4: crontaba nie trzeba zmieniać przy wdrożeniu; usunięcie wpisu po wycofaniu — opcjonalne |
| 9 | **W `deploy.sh` migracje wykonuje `create_app()` kroku `flask sync-changelog`**, nie `flask migrate` (który potem znajduje 0). Bramka mimo to działa: nieudana migracja zapisuje się z `success = 0`, zostaje oczekująca, `flask migrate` ją ponawia i kończy się kodem 1. | krok 3c | **nie** | runbook: w `logs/deploy.log` czas i ewentualne błędy migracji są pod „Syncing changelog…” |
| 10 | Kafle startowe 6.10 rano: **Sklejanie 11** przy K = 2 (K5 z 5.10 wieczorem: 4). Spec 5.8 każe zgłosić Konradowi, jeśli to wyraźnie więcej, niż hala skończy na jednej zmianie. | krok 5 | **nie** | w czwartek podgląd tuż przed „Przygotuj”; biuro może zdjąć nadmiar „Zdejmij” albo zostawić (start i tak schodzi przez ZAKOŃCZ) |

## Odstępstwa od karty i raportów pakietu / K5

1. **Python 3.12 zamiast 3.9.** Karta zakładała 3.9 za CLAUDE.md, a produkcja ma 3.12.3 (Znalezisko 7). Obraz z repo
   (`python:3.12-slim`) odpowiada więc serwerowi.
2. **Restart w przebiegu 2** rozbity na `docker stop` + `docker start` z przerwą, żeby zdążyć wysłać ZAKOŃCZ z tabletu
   w oknie 502. Przebieg 1 robił `docker restart` jak `supervisorctl restart`.
3. **`pip install`** w kontenerze bez sieci ponawiał pobieranie `packaging==21.3` i kończył się błędem (8,3 s,
   best-effort jak w `deploy.sh`). To artefakt obrazu: `pytest` z Dockerfile podnosi `packaging`, a sieci nie ma.
   Na serwerze wymagania są te same co dziś, więc krok potrwa sekundy.
4. **Monitor hali** wymaga adresu z `STATION_ALLOWED_IPS` (także na `main`). W kopii dopisałem IP bramki próby
   (`192.168.80.1`), tylko na potrzeby oględzin. W kopii dla przebiegu 1 dodatkowo `cut_to_size=0` na jednej pozycji
   (scenariusz „bez docięcia”).
5. **Wbudowana przeglądarka** wczytała widżet czatu z `chat.woodpower.pl` (JS strony; odmowa CSP `frame-ancestors`).
   To ruch przeglądarki do własnej usługi, bez danych z kopii; kontener aplikacji nie ma wyjścia. Logowanie do panelu
   ciasteczkiem z `login_user` (bez hasła).
6. **Moje stuknięcie przez `adb`** w powiadomienie, które już zniknęło, trafiło w ZAKOŃCZ kafla 1790_4 (licznik 2/2)
   na stole Sklejania kopii. Zwykłe ZAKOŃCZ z tabletu (200), bez znaczenia dla wyników.
7. **Punkt 12 odbioru** sprawdzony w wariancie „serwer nieosiągalny”. Wariant „Wi-Fi wyłączone” wymaga trybu
   samolotowego na tablecie, a ustawień tabletu nie zmieniałem. `adb reverse` działa też w trybie samolotowym, więc
   ten wariant to osobny test z Konradem: tryb samolotowy + zdjęty `reverse`.
8. **Przegląd tras** robiłem klientem testowym Flaska w kontenerze z serwerem (`wdr_smoke.py` z pakietu,
   ścieżki `/wdr` → `/proba`), jak pakiet.
9. Krok 5 „Rozpoczęte na szczyt” zrobiony tylko w przebiegu 1. Sekwencję D w przebiegu 2 zrobiłem bez niego —
   drabina nie wpływa na widma.
10. W przebiegu 2 tablet zarejestrował Konrad, ale stanowisko wybrał serwer (`packaging` przy rejestracji). Przy
    każdej zmianie stanowiska appka rejestruje się od nowa — w `prod_devices` przybywa wierszy tylko przy nowym
    `device_id`.

## Czasy niedostępności i migracji (do zapowiedzi dla hali)

| Zdarzenie | Migracje | Niedostępność (502 + start workerów) | Cały `deploy.sh` (bez webhooka) |
|---|---|---|---|
| wdrożenie `5e944a55` | 17 plików / **2,3–2,4 s** (K5: 2,2 s; pakiet pod obciążeniem 6–7,5 s) | **~5,6 s** | ~35 s (na serwerze bez artefaktu `pip`: ~25–30 s) |
| wycofanie `8e14937e` | 1 plik / 0,055 s; ręczny C6 0,4–0,5 s | ~6,5 s | ~33 s |
| ponowne wdrożenie | 0 | ~5 s | ~35–41 s |

Tablety w trakcie restartu: baner „Błąd synchronizacji — HTTP 502”, akcje w kolejce (licznik przy profilu),
po restarcie dochodzą same — 17–37 s po starcie serwera (najbliższy takt appki).

## Liczby kafli startowych (kopia 6.10, 09:42 — w trakcie zmiany)

| Stanowisko | Rozpoczęte → stół | K |
|---|---|---|
| Wycinanie | 0 | 2 |
| Składanie | 0 | 2 |
| Sklejanie | **11** | 2 |
| Formatowanie | **8** (zamówienia) | 2 |
| Krawędzie | 0 | 2 |
| Pakowanie | 1 (zamówienie) | 2 |
| **razem** | **20** | |

Po pierwszym `desk` stanowiska z 0 startowych dopełniają się z kolejki do K. Lakiernia nie ma stołu.

## Runbook K7 — dzień wdrożenia (czwartek 8.10, przerwa 10:30)

Oznaczenia: **[S]** serwer (ssh jako root, katalog `/home/woodpower-crm/htdocs/crm.woodpower.pl`), **[P]** panel CRM,
**[T]** tablet, **[L]** lokalnie (repo). Czasy z próby.

### A. Przed oknem (środa / czwartek rano)

1. **[T] APK 1.8.0 (release, vc 44) na wszystkich tabletach** (wcześniej, na starym backendzie działa jak dziś —
   sprawdzone 1b: lista, bez błędów). Release wymaga `https` w `sse_url` — na produkcji jest
   `https://crm.woodpower.pl/realtime/connection/uni_sse` (sprawdzone 6.10).
2. **[L] Stan:** `git fetch origin && git rev-parse origin/main` → `31a0b0145b222799234674bdf1e995dab6791a0c`.
   **[S]** `git -C /home/woodpower-crm/htdocs/crm.woodpower.pl rev-parse HEAD` → to samo. Inaczej **STOP** (nowy squash).
3. **[S] Nie wołać żadnego `flask …`** na serwerze przed pushem (każde migruje przy `create_app()`).
4. **[S] Broker:** `supervisorctl status centrifugo` → RUNNING; w `/etc/centrifugo/config.json` namespace `station`
   (sprawdzone 6.10: jest); `REALTIME.enabled = true` (jest).
5. **[S] Crontab:** wpis crona logistyki **już jest** (`/etc/cron.d/woodpower-crm`, co godzinę o :00) — nic nie
   zmieniać; pierwszy automatyczny przebieg po wdrożeniu o 11:00. **Nie włączać** crona `sync-cron`.
6. **[S] Heartbeat — kontrola tabletów** (tylko tablety widziane w ostatnich 24 h):
   ```sql
   SELECT station_code, COUNT(*) tablety, SUM(last_app_version_code >= 44) vc44,
          GROUP_CONCAT(CONCAT(device_name, ':', last_app_version_code)) szczegoly
   FROM prod_devices WHERE is_active = 1 AND last_seen_at >= NOW() - INTERVAL 1 DAY
   GROUP BY station_code;
   ```
   Oczekiwane przed „Włącz stoły”: `tablety = vc44` na każdym stanowisku. Tablet bez vc 44 → zaktualizować APK
   (heartbeat idzie zaraz po starcie i po aktualizacji — w próbie vc 44 w bazie w 1 s po rejestracji).
   6.10: Wycinanie 0 tabletów widzianych w 24 h — sprawdzić, czy jest tablet Wycinania.
7. **[P/S] Instrukcja dla hali przed przerwą:** „wbijcie licznik na tym, co macie w rękach” (kafel startowy powstaje
   tylko z licznika > 0).

### B. Wdrożenie (10:30)

1. **[S] Kopia ręcznych priorytetów (A3)** — tuż przed pushem (0,4 s):
   ```sql
   CREATE TABLE IF NOT EXISTS zz_przed_wdrozeniem_2026_10_08_priorytety AS
   SELECT id, priority_rank, priority_manual_override, is_priority FROM prod_products
   WHERE current_status NOT IN ('spakowane', 'anulowane');
   SELECT COUNT(*) FROM zz_przed_wdrozeniem_2026_10_08_priorytety;   -- ≈ liczba aktywnych pozycji (6.10: 592)
   ```
2. **[L] Push:** `git push origin 5e944a55978f659ca38a69d09d74b50a5a4d841e:main` (szybkie przewinięcie).
3. **[S] Śledzić** `tail -f logs/deploy.log` do `Deploy complete!`. Oczekiwane (próba): całość ~30 s;
   **migracje widać pod „Syncing changelog…”** — 17 × „✓ Sukces”, ok. 2,5 s; `flask migrate` → „Wykonano 0 migracji.”;
   restart → ~6 s niedostępności (502, tablety kolejkują). `[MIGRATION FAILED]` → deploy sam cofa kod, aplikacja
   zostaje na starym; nie restartować ręcznie.
4. **[S] Ręczny cron** (raz): `scripts/cron_endpoint.sh POST /production/api/logistics/cron` → 200 w < 1 s,
   `priorytety_utrwalone.success: true`, `zamowien` ≈ liczba aktywnych zamówień (6.10: 249), wszystkie zmienione,
   `szczeble_uzupelnione: 0`. Drugi raz → 0 zmian. `success: false` → przeczytać `error`, powtórzyć (nie przerywa).
5. **[S] Kontrole SQL (B4)** — wszystkie zgodne w próbie:
   ```sql
   SELECT config_key, config_value FROM prod_config WHERE config_key LIKE 'DEADLINE%';      -- robocze / 10 / 14
   SELECT kind, stars, tag, position FROM prod_priority_rungs ORDER BY position;            -- 9: ★5, po_terminie, ★4, blisko_terminu, rozpoczete, ★3, ★2, ★1, ★0
   SELECT SUM(config_key LIKE 'priorytety\_%'), SUM(config_key = 'DEADLINE_DAY_TYPE') FROM prod_config;  -- 37, 1
   SELECT COUNT(*), COUNT(DISTINCT priority_rank), SUM(priority_rank IS NULL) FROM prod_orders o
    WHERE EXISTS (SELECT 1 FROM prod_products p WHERE p.order_id = o.id AND p.current_status NOT IN ('spakowane','anulowane'));  -- N, N, 0
   SELECT config_key, config_value FROM prod_config WHERE config_key LIKE 'priorytety\_tryb\_%' OR config_key = 'priorytety_min_app_version_code';  -- 7 × stary, 0
   SELECT COUNT(*) FROM prod_station_desk;                                                   -- 0
   SELECT COUNT(*) FROM schema_migrations WHERE success = 1 AND version >= '2026-09-25';    -- 17
   ```
6. **[P] Panel:** Lista produkcyjna (#1…, liczba zamówień = cron), Drabina (suma liczników = liczba zamówień),
   Konfiguracja → Terminy (10 / 14 / robocze) i Stół stanowisk (6 × „zgodność”, Lakiernia „lista”, próg 0), zakładka
   Stanowiska, monitor hali, Logistyka (wszystkie zamówienia „Nie ustawiono” — oczekiwane).
7. **[T] Tablety:** po restarcie dalej lista (`desk` → `tryb: "stary"`), zaległe akcje z kolejki dochodzą same w ciągu
   ok. 40 s; plakietki dostawy zmieniają się na „NIE USTAWIONO” (dopóki logistyk nie ustawi sposobu). Zakończony
   w trakcie restartu kafel może pokazać się jeszcze do 60 s (Znalezisko 5).

### C. Start stołów (po zakończeniu zmiany / przed następną)

1. **[S] Heartbeat** — zapytanie z A6: każdy używany tablet vc ≥ 44.
2. **[P] Konfiguracja → Start stołów → podgląd** (0,1 s): liczby per stanowisko (6.10 rano: Sklejanie 11,
   Formatowanie 8, Pakowanie 1). Dużo więcej niż hala zrobi na zmianie → decyzja Konrada (zostawić / „Zdejmij”).
3. **[P] „Przygotuj stoły”** (0,1 s; można powtarzać — dokłada tylko nowe).
4. **[P] Poprawki:** „Wyślij na stanowisko” (modal priorytetu na Liście / zakładka Stanowiska) i „Zdejmij ze stołu”
   (0,03 s każde).
5. **[P] „Włącz stoły”** z minimalną wersją **44** (jedno pole + przycisk; przy 0 serwer odmawia — 400
   `prog_wersji_wymagany`, sprawdzone). Zapis 0,04 s.
6. **[P] Drabina:** „Rozpoczęte” na szczyt (0,2 s z przeliczeniem).
7. **[T] Kontrola:** tablety przechodzą na stół same w ≤ 30 s (próba: 4 s i 19 s), kafle startowe z plakietką
   „rozpoczęte przed startem”, pozostałe stanowiska dopełniają się do K. Formatowanie: `desk` ok. 350 kB — ładuje się
   płynnie.
8. **[P] Po zejściu kafli startowych:** „Rozpoczęte” z powrotem pod ★★★★ (decyzja biura).

### D. Objawy i reakcje po starcie

- ZAKOŃCZ trwa ok. 1,5 s zamiast 0,05 s → broker przyjmuje połączenia i nie odpowiada (próba: 1,445 s):
  `supervisorctl restart centrifugo` albo `REALTIME.enabled=false` w `core.json` **z natychmiastowym restartem
  aplikacji**. Broker wyłączony (odmowa połączenia) nie spowalnia (0,04 s); tablety przechodzą na odpytywanie.
- Tablet: 409 „Pozycja … nie czeka na …” → ktoś zamknął kafel gdzie indziej; appka sama odświeża stół (sprawdzone).
- Tablet: „Nie udało się odłożyć — brak odpowiedzi serwera” → Odłóż działa tylko online; ponowić po powrocie sieci.
- Zakładka Stanowiska: kafle w polu „do zdjęcia” / widma → „Zdejmij”.
- Wycofanie jednego stanowiska: Konfiguracja → Stół stanowisk → tryb „zgodność” (0,03 s). Tablet wraca na listę
  w ≤ 30 s przy niepełnym stole, **do 5 min przy pełnym** (próba: 288 s) — szybciej: wyjść i wejść na ekran
  stanowiska. Ponowne „stół” → tablet na stole w ≤ 30 s (próba: 19 s), kafle zostają.

### E. Wycofanie całości (logistyka 1–4 + priorytety)

**Przed** (na nowym kodzie):
1. Logistyk zdejmuje wiszące „Niedostarczone”: `SELECT COUNT(*) FROM prod_route_stops WHERE not_delivered_at IS NOT NULL` → 0.
2. Ręczny cron, potem `SELECT COUNT(*) FROM prod_orders WHERE bl_status_pending_id IS NOT NULL OR bl_delivery_method_pending = 1 OR bl_address_pending = 1` → 0;
   spisać `repack_required = 1` / `problem_at IS NOT NULL`.
3. **Pakowanie bez sposobu** — logistyk ustawia sposób wszystkim (próba: **40–44 zamówienia**, hurt w Logistyce):
   `SELECT COUNT(DISTINCT o.id) FROM prod_orders o JOIN prod_products p ON p.order_id = o.id WHERE p.current_status = 'czeka_na_pakowanie' AND o.override_delivery_method IS NULL` → 0.
4. (Opcjonalnie) wpis crona logistyki w `/etc/cron.d/woodpower-crm` — po wycofaniu 404 co godzinę, bez skutków.

**Wykonanie:**
5. **[L]** `git rev-parse origin/main` = `5e944a55…` (inaczej STOP), **`git push origin 8e14937e8497fdf9a27c5ba0db97e739b9057ccc:main`**.
   `deploy.log`: pod „Syncing changelog…” 1 × „✓ Sukces: 2026-10-08-wycofanie-logistyki” (0,05 s); restart ~6,5 s.
6. **[S] Po `Deploy complete!`:** `mysql -uroot crm < migrations/2026-10-08-wycofanie-logistyki.sql` (0,4 s, bez wyjścia).
7. **[S] Kontrole C7** (wszystkie 0 w próbie):
   ```sql
   SELECT COUNT(*) FROM prod_products WHERE current_status IN ('zweryfikowane','zaladowane','dostarczone');
   SELECT COUNT(*) FROM prod_routes WHERE status IN ('zaladowana','w_trasie');
   SELECT COUNT(*) FROM prod_logistics_log WHERE action IN ('zaladunek','zostaje','wyjazd','dostarczone','niedostarczone','dostarczenie_cofniete','niedostarczenie_cofniete');
   SELECT COUNT(*) FROM prod_route_stops WHERE not_delivered_at IS NOT NULL;
   SELECT COUNT(*) FROM prod_config WHERE config_key = 'logistyka_wydane_dostarczone';
   SELECT COUNT(*) FROM prod_print_queue WHERE status = 'pending' AND (printer <> 'etykiety' OR package_id IS NOT NULL);
   SELECT COUNT(*) FROM prod_products WHERE original_product_id IS NOT NULL AND current_status IN ('czeka_na_wyciecie','czeka_na_skladanie','czeka_na_sklejanie')
     AND NOT (priority_rank = 1 AND priority_manual_override = 1 AND is_priority = 1);
   ```
8. **[S] NOWE (Znalezisko 1) — tryby stanowisk na `stary`**, żeby ewentualne ponowne wdrożenie startowało jak pierwsze:
   ```sql
   UPDATE prod_config SET config_value = 'stary' WHERE config_key LIKE 'priorytety\_tryb\_%';
   ```
   (stary kod tych kluczy nie czyta; próg wersji może zostać 44).
9. **[P/T]** Panel: Lista produkcyjna, archiwum, monitor hali bez błędów. Tablety: wracają na listę **same, bez
   restartu** (`desk` → 404 HTML; sprawdzone), kolejka offline dochodzi (sprawdzone: ZAKOŃCZ z okna restartu → 200 na
   starym kodzie). Telefony Weryfikacji/Dostawy — nie używać.
10. **Nie wołać** `POST /production/api/recalculate-all-priorities` (zdejmuje blokady).

### F. Ponowne wdrożenie po wycofaniu

1. **[S] NOWE (Znalezisko 2) — przed pushem, na starym kodzie** (0,4 s):
   ```sql
   UPDATE prod_config SET config_value = 'stary' WHERE config_key LIKE 'priorytety\_tryb\_%' AND config_value <> 'stary';  -- jeśli E8 pominięto
   SELECT COUNT(*) FROM prod_station_desk;   -- do protokołu (widma + stare kafle)
   DELETE FROM prod_station_desk;
   ```
   Kasuje też odłożenia i kafle „biuro” sprzed wycofania — biuro wyśle je ponownie po starcie stołów.
2. **[L]** Gałąź ponownego wdrożenia od bieżącego `main` (revert revertu albo nowy squash) → push → `deploy.log`:
   „Brak nowych migracji” (0 plików).
3. **[S]** Ręczny cron (200), kontrole B5 — z tą różnicą, że `schema_migrations` od 25.09 = **18** (17 + cofająca),
   tryby `stary`, stół 0.
4. **[S] Druga migracja cofająca w przyszłości:** runner jej nie powtórzy — przy kolejnym wycofaniu ręczne E6 obowiązkowe.
5. Start stołów jak C1–C8 (próba: „Przygotuj” Sklejanie 7, Formatowanie 7 → „Włącz” → tablet na stole w ≤ 31 s,
   **0 widm**).

## Stan środowiska po próbie

- Stack `priorytety-proba` **zatrzymany** (`docker compose -p priorytety-proba stop`); **wolumen bazy
  `priorytety-proba_db_data` zostaje do czwartku** (stan końcowy: kod `5e944a55`, stoły włączone, 0 widm). Może
  posłużyć przebiegowi E2E (rozstrz. 26): `docker compose -f woodpower-podglady/priorytety/proba/compose.yml start`
  (porty 5020 / 8021 / 3320, sieć bez wyjścia), stan od nowa ze zrzutu — skrypt `narzedzia/reset_stan_przed.sh`
  wymaga zrzutu, który usunąłem (nowy zrzut tym samym poleceniem).
- **Zrzut produkcji usunięty** (`proba/dump/`); w kontenerze `db` nie ma kopii pliku.
- Worktree `.claude/worktrees/priorytety-proba` (odłączony HEAD `5e944a55`) zostaje do czwartku razem ze stackiem.
- Tablet: appka debug zarejestrowana na kopii (urządzenie „Proba-Tablet-Konrad”); `adb reverse tcp:5020` zdjęty.
  Przed produkcją — appka release z adresem produkcyjnym (debug ma `127.0.0.1:5020` na stałe).
- Poza repo: `woodpower-podglady/priorytety/proba/` — `compose.yml`, `edge/nginx.conf`, `config/core.json` (klucze
  losowe), `centrifugo/config.json`, `narzedzia/` (`deploy_proba.sh`, `sonda.py`, `kolejka.py`, `ph.py`, `s6.py`,
  `sse.py`, `broker.py`, `wdr_smoke.py`, `wdr_parametry.py`, SQL kontroli), `wyniki/` (logi, JSON, zrzuty tabletu).
  Zrzuty ekranu tabletu i odpowiedzi API zawierają dane klientów z kopii — do usunięcia razem z katalogiem po czwartku.
- Kontenerów, baz i worktree innych sesji (5002–5007, `priorytety-k5`, `k5-centrifugo`, bazy logistyki i priorytetów
  w `woodpower-crm-db-1`) nie dotykałem. Gałąź głównego checkoutu bez zmian (`main`).
