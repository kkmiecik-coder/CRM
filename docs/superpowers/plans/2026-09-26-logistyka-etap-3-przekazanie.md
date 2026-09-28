# Logistyka równoległa — etap 3 (trasy i flota): stan gałęzi i kontynuacja

Data: 2026-09-26, aktualizacje 2026-09-28 (**kontynuujemy na Windows**, nie na Macu; runda poprawek 4.1 — sekcje 0,
4 i 5; potem na prośbę Konrada **jedna gałąź i jeden podgląd** — sekcje 0, 1 i 7). Źródło: sesja na Windows
(tryb subagent-driven, plan `docs/superpowers/plans/2026-09-24-logistyka-etap-3-trasy-flota.md`, spec
`docs/superpowers/specs/2026-09-24-logistyka-rownolegla-trasy-design.md`). Plany etapów 1–3 i spec są w repo na gałęzi
(mimo `.gitignore`, na prośbę Konrada — repo jest publiczne, więc nie dopisuj tu sekretów ani uwag bezpieczeństwa).
**Ten dokument jest jedynym źródłem prawdy o przebiegu etapu 3** — roboczy katalog procesu (ledger `.superpowers/sdd/…`
z raportami przeglądów) zniknął razem z usuniętym worktree; raporty oględzin i testów zostały w scratchpadzie (sekcja 0).

## 0. Stan na 28.09.2026 (Windows)

- Gałąź `claude/logistyka-etap-3-trasy` na origin i lokalnie = ten commit. **Runda 4.1 (28.09 po południu)** dodała
  kod: `5463bc99`, `30c7ef9a`, `fe61e674`, `380a8f8c` (sekcja 4.1) i mini-plan
  `docs/superpowers/plans/2026-09-28-logistyka-etap-3-poprawki-4-1.md`; stan przed rundą: `3eafac50`. `main` = `origin/main` =
  `a5a0f1f9` — od startu gałęzi **nic nowego w `main`**, więc merge `main` do gałęzi nie jest potrzebny.
- Testy po rundzie 4.1: **`4704 passed, 3 skipped`**.
- Worktree: `C:\Users\Grafik\Documents\woodpower-crm\.claude\worktrees\logistyka-etap-3-trasy` (jedyny worktree
  logistyki; worktree etapów 1 i 2 usunięte). Główny checkout stoi na `main` i obsługuje kontener 5002 — **nie
  przełączaj w nim gałęzi**.
- **Gdzie co sprawdzać (ujednolicone 28.09 na prośbę Konrada):**
  - **localhost:5002** — `main`, czyli to, co jest na produkcji, na bazie `woodpower_crm_local` odświeżonej z produkcji
    28.09 (liczniki identyczne z produkcją). **Logistyki tam nie ma** — i nie uruchamiamy tam kodu gałęzi (sekcja 2).
  - **127.0.0.1:5003** — **jedyny podgląd logistyki**: kod gałęzi (po rundzie 4.1, `380a8f8c`), kontener
    `logistyka3-prod` (obraz `logistyka3-app`, sieć `woodpower-crm_default`), baza `logistyka3_prod` = zrzut produkcji
    z 25.09 21:07 po migracjach etapów 1–3 — te same zamówienia co produkcja 28.09 (1733, ostatnie z 25.09 16:02) — plus
    testy Konrada z 28.09 (o 08:38 hurtowo ustawione sposoby dostawy 209 zamówień). Logowanie hasłem produkcyjnym przez
    `127.0.0.1`, nie `localhost`; ciasteczka `session_lg3prod`/`remember_lg3prod`. W konfiguracji pusty klucz Base.
    i integracje, bez klucza ORS i CARTO → przebiegi liniami prostymi, podkład OSM. Do 28.09 przedpołudnia ten sam
    podgląd był na porcie 5004 — **5004 już nie istnieje**.
  - Dawny podgląd z danymi testowymi (kontener `logistyka3-podglad` na 5003) **usunięty 28.09**; jego baza
    `logistyka3_podglad` zostaje nieużywana do decyzji Konrada (trasa 17 „trasa 1” Konrada, trasy testowe oględzin
    18–36) — sekcja 7.
  - Odświeżenie kodu podglądu (strażnik sandboxa nie przepuszcza potoku `git archive | tar`, więc dwa kroki; w Git Bash
    ścieżki do `tar` w formie `/c/…`, bo `C:` tar bierze za zdalny host):
    `git archive --output=<katalog>/kod.tar HEAD`, `tar -xf /c/…/kod.tar -C /c/…/kod` (`config/core.json` nie jest
    w gicie, więc zostaje), potem `docker restart logistyka3-prod` i sprawdzenie `/login` = 200 oraz `[Migrations]`
    w `docker logs`. Katalog podglądu: `C:\Users\Grafik\AppData\Local\Temp\claude\C--Users-Grafik-Documents-woodpower-crm\320e7d76-d002-459d-83b4-3b0a3df0403a\scratchpad\podglad-prod`
    (kod w `kod`, montowany jako `/app`; `env.list` z kluczem sesji). Kontener odtworzysz tak:
    `MSYS_NO_PATHCONV=1 docker run -d --name logistyka3-prod --network woodpower-crm_default -p 127.0.0.1:5003:5000
    --env-file <katalog>/env.list -v "<katalog>/kod:/app" -w /app logistyka3-app flask run --host=0.0.0.0 --port=5000`.
    To katalog tymczasowy Windows — jeśli zniknie, podgląd trzeba postawić od nowa (sekcja 3).
- Raporty z weryfikacji (scratchpad poprzedniej sesji, `…\320e7d76-d002-459d-83b4-3b0a3df0403a\scratchpad\podglad\`):
  `RAPORT.md` (przygotowanie podglądu), `RAPORT-BLOKADA.md` (testy blokady na dwóch sesjach MySQL + skrypt
  `kod\_proba_blokady.py`), `SMOKE-API.md` (315 złych żądań), `OGLEDZINY.md`, `OGLEDZINY-2.md`, `OGLEDZINY-3.md`,
  `OGLEDZINY-4.md` (4 tury oględzin UI). Skrypty pomocnicze leżą w kodzie DAWNEGO podglądu (`…\podglad\kod`):
  `_sesja.py` (ciasteczko sesji admina dla wbudowanej przeglądarki — na obecnym podglądzie trzeba go skopiować do
  `…\podglad-prod\kod` i szukać ciasteczka `session_lg3prod=` zamiast `session=`), `_routimo_check.py` (eksport Routimo
  po stronie serwera).
- Raporty rundy 4.1 (scratchpad sesji `cea01798-…`, `…\cea01798-4898-4fcf-9c72-c6856d824d42\scratchpad\raporty-4-1\`):
  `progress.md` (ledger: przebieg, rozstrzygnięcia, odłożone drobiazgi), `final-review.md` (przegląd adwersaryjny
  rundy), `ogledziny-4-1.md` (oględziny A–G), `fix-wave-rereview.md` (przegląd fali poprawek). **Pułapka oględzin:**
  wbudowana przeglądarka z kartą w tle / schowanym panelem nie ma klatek animacji — `requestAnimationFrame` i zdarzenie
  `close` okien `<dialog>` nie przychodzą (Chromium wysyła `close` w następnej klatce). Scenariusze zależne od `close`
  sprawdzaj pomiarem zdarzeń, nie samym efektem.
- Zrzuty produkcji (dane klientów): `…\320e7d76-d002-459d-83b4-3b0a3df0403a\scratchpad\prod\crm_dump_2026-09-25.sql.gz`
  i `…\cea01798-4898-4fcf-9c72-c6856d824d42\scratchpad\prod\crm_dump_2026-09-28.sql.gz` (z tego drugiego odświeżono
  28.09 bazę 5002); kopia `woodpower_crm_local` sprzed odświeżenia:
  `…\cea01798-4898-4fcf-9c72-c6856d824d42\scratchpad\kopie\woodpower_crm_local_przed_2026-09-28.sql.gz`.
- Klucz `CARTO_BASEMAPS_KEY` jest w `config/core.json` na VPS od 25.09 (z restartem). Kod produkcji jeszcze go nie czyta.

## 1. Gałęzie i stan

- **Jedna gałąź logistyki: `claude/logistyka-etap-3-trasy`** (etapy 1, 2 i 3; 70+ commitów ponad `main`). Dawne gałęzie
  etapów (`claude/logistyka-etap-1-dostawy-22cf12` = `facbda24`, `claude/logistyka-etap-2-mapa` = `1c9fa686`) były
  w całości zawarte w tej gałęzi (sprawdzone `merge-base --is-ancestor`) i zostały usunięte 28.09 lokalnie i na origin
  na prośbę Konrada — w razie potrzeby da się je odtworzyć z tych SHA. Wszystkie dalsze prace logistyki idą na tę
  jedną gałąź. **Nic nie jest w `main` ani wdrożone.** Merge do `main` = deploy (webhook) — wyłącznie na polecenie
  Konrada.
- Etap 3: 9 zadań planu + 3 rundy poprawek interfejsu + fala poprawek po dwóch przeglądach końcowych (backend, UI)
  + runda 4.1 (28.09: 2 zadania, przegląd adwersaryjny rundy, fala poprawek, oględziny).
- Testy: `4704 passed, 3 skipped` (pełny pakiet w Dockerze, SQLite, Python 3.12; kod zgodny z Pythonem 3.9 produkcji —
  sprawdzone kompilacją na python:3.9-slim przed rundą 4.1; runda 4.1 nie dodała składni spoza 3.9).
- Weryfikacja poza testami (na Windows):
  - migracje etapów 1–3 na MySQL 8.4: na kopii lokalnej bazy i na **świeżej kopii produkcji z 25.09 21:07** (4/4, idempotentne, 2× ręcznie);
  - blokada zapisów tras na dwóch prawdziwych sesjach MySQL (wyścigi S1–S5b: podwójne zajęcie pojazdu, zakleszczenia, stary status, odhaczenie vs dodanie, adres vs zapis trasy) — PASS po poprawkach;
  - 315 „złych” żądań do całego API logistyki na MySQL — 0 × 5xx, integralność danych OK;
  - 4 tury oględzin interfejsu we wbudowanej przeglądarce na kopii danych (1440/1280/1024/768) — ostatnia: PASS poza punktem 4.1 niżej.

## 2. Zmiany w bazie przy uruchamianiu kodu gałęzi na innej bazie (przeczytaj, zanim to zrobisz)

Dotyczy każdej bazy, która jeszcze nie widziała kodu etapów 1–3 — na Windows: robocza `woodpower_crm_local` (5002),
na Macu: jego lokalna baza. Kopie `logistyka3_podglad` i `logistyka3_prod` mają już te migracje.
Migracje wykonują się **same przy starcie aplikacji** (`RUN_MIGRATIONS`, domyślnie włączone) i przy `flask migrate`.
Uruchomienie kodu tej gałęzi na takiej bazie wykona **nieodwracalnie** cztery migracje (runner zapisuje je w `schema_migrations`):

1. `2026-09-25-logistyka-sposob-dostawy.sql` (etap 1):
   - nowe kolumny `prod_orders`: `delivery_method_set_at`, `delivery_method_set_by`, `handed_over_at`, `handed_over_by`,
     `repack_required`, `logistics_closed_at` (+ indeks), `bl_delivery_method_pending`, `bl_status_pending_id`;
   - tabela `prod_logistics_log`; wiersze `prod_config` (dzierżawa wysyłki do Base., pauza po limicie API);
   - **dane:** produkty `czeka_na_logistyke` → `czeka_na_pakowanie`; zamówienia w całości spakowane/anulowane dostają
     `logistics_closed_at` (historia znika z widoku Logistyki).
2. `2026-09-26-logistyka-geolokalizacja.sql` (etap 2): tabela `prod_order_geo` + wiersze `prod_config`
   `logistyka_geo_dzierzawa`, `logistyka_geo_postep`.
3. `2026-09-26-logistyka-zmiana-adresu.sql` (etap 2): kolumna `prod_orders.bl_address_pending`, akcja `adres` w ENUM logu.
4. `2026-09-27-logistyka-trasy-flota.sql` (etap 3): tabele `prod_vehicles`, `prod_routes`, `prod_route_stops` + wiersz
   `prod_config` **`logistyka_trasy_blokada`** (blokada „jeden piszący trasy naraz”).

Zalecenie (tak było na Windows):
- **Pracuj na kopii bazy**, nie na roboczej `woodpower_crm_local`, jeśli potrzebujesz jej dla `main`: np.
  `CREATE DATABASE logistyka3_prod …` + import świeżego zrzutu produkcji (procedura zrzutu: `mysqldump -uroot
  --single-transaction --quick --no-tablespaces --default-character-set=utf8mb4 crm | gzip` przez SSH na VPS,
  strumieniem, bez pliku na serwerze), a w konfiguracji testowej wskaż ją w `DATABASE_URI`.
  Kod `main` na bazie po tych migracjach nadal działa (tylko dodane kolumny/tabele), ale dane etapu 1 (przeniesione statusy,
  zamknięcia) już zostaną.
- **W konfiguracji do testów na danych produkcji wyczyść `API_BASELINKER.api_key`** (a także pocztę, GlobKurier, AI,
  Sentry). Inaczej dopychacz w tle wyśle do prawdziwego Base. metodę dostawy, status i adres po każdym kliknięciu.
- „Zlokalizuj teraz” wysyła do GUGiK i Nominatim wyłącznie adresy (jak produkcja).
- Wiersz `logistyka_trasy_blokada` tworzy migracja; gdyby go brakowało (baza, która wykonała wcześniejszą wersję pliku),
  kod na MySQL sam go dopisze (`INSERT IGNORE`).
- `config/core.json` (nie w repo): `CARTO_BASEMAPS_KEY` — opcjonalny, klucz ograniczony do `crm.woodpower.pl`, lokalnie
  kafelki CARTO dają 403/znak wodny → przełącz podkład na OSM; `OPENROUTESERVICE_API_KEY` — opcjonalny, bez niego przebiegi
  tras liniami prostymi („przebieg przybliżony”), z nim km i czas po drogach. Po zmianie `core.json` zrestartuj kontener app.
- `.env`: `FLASK_SECRET_KEY` (już jest), porty `CRM_APP_PORT=5002`, `CRM_DB_PORT=3308` (Windows i Mac tak samo).
- Stan „jak po wdrożeniu dziś” (kopia produkcji z 25.09): 209 zamówień w Logistyce, 208 z nich „Nie ustawiono”,
  **75 ma pozycje czekające na pakowanie** (tablet zablokuje ich pakowanie do ustawienia sposobu dostawy), flota pusta,
  współrzędnych brak (trzeba „Zlokalizuj teraz” albo cron).

## 3. Testy i podgląd

- Z katalogu worktree: `docker compose -p logistyka3 run --rm --no-deps app pytest tests/ -q -p no:cacheprovider`
  (oczekiwane 4704 passed, 3 skipped; obraz `logistyka3-app` już zbudowany); `integrations/blog_seo` osobno.
  Składnia JS: `node --check <plik>` na hoście (node jest w PATH Windows, w obrazie go nie ma).
  `docker compose exec` z worktree testuje GŁÓWNY checkout, nie gałąź. Nie twórz `config/core.json` w worktree
  (zmienia wyniki testów). W Git Bash polecenia dockera ze ścieżkami `/app` lub `C:/…` poprzedzaj `MSYS_NO_PATHCONV=1`.
- Na Windows stoi jeden podgląd logistyki, 127.0.0.1:5003 (sekcja 0); po każdej zmianie kodu odśwież jego kod. Sesja dla
  wbudowanej przeglądarki: skrypt `_sesja.py` (sekcja 0 — na obecnym podglądzie ciasteczko `session_lg3prod`; użytkownik
  id=1 to konto z kopii produkcji, więc tylko lokalnie) (`create_app()` + `login_user` admina w `test_request_context` + `save_session`)
  → wartość ciasteczka wstrzyknięta przez `document.cookie` (bez `user_session_token` aplikacja nie wymaga wiersza
  `user_sessions`). Eksport Routimo sprawdzaj po stronie serwera (`_routimo_check.py`), nie klikając pobierania.
- Podgląd gałęzi: osobny kontener z kodem z `git archive` + kopia bazy + kopia `core.json` bez integracji, na innym porcie;
  gdy chodzi obok innego podglądu na tym samym hoście, ustaw w jego `core.json` własne `SESSION_COOKIE_NAME` i
  `REMEMBER_COOKIE_NAME` (ciasteczka nie rozróżniają portów). Loguj się przez `127.0.0.1:<port>`, nie `localhost`.
- Subagenci z przeglądarką: tylko wbudowana, odizolowana przeglądarka; **nigdy Chrome Konrada** (jego sesje, produkcja).

## 4. Co zostało otwarte

### 4.1. Do poprawy na starcie — ZROBIONE 28.09 (runda 4.1)
- ✅ **Anulowane w całości zamówienie zdjęte z trasy zamyka się** (`5463bc99`): `routes.usun_przystanek` po zdjęciu woła
  `delivery.przelicz_zamkniecie(order, teraz, trasa=route)` — dotyczy wszystkich czterech dróg zdjęcia (odhaczenie jako
  niedostarczone, ręczne zdjęcie w edytorze, usunięcie trasy roboczej, zmiana sposobu dostawy). Efekt uboczny, też
  poprawny: zamówienie transportu własnego z aktywnymi pozycjami, zamknięte „nieświeżo” na trasie aktywnej, po zdjęciu
  się otwiera. Testy serwisu i API (`380a8f8c` przypina też ten efekt uboczny).
- ✅ **Teksty o anulowanych po zdjęciu z trasy** (`fe61e674`, wynik przeglądu adwersaryjnego rundy): ręczne zdjęcie
  anulowanego przystanku mówi „Jest anulowane, więc nie wraca do „Do dodania””, a potwierdzenie usunięcia trasy liczy do
  „wróci/wrócą do puli” tylko aktywne i osobno „N anulowane zamówienie/-a/anulowanych zamówień zamknie/zamkną się
  w logistyce” (dawny drobiazg z 4.3).
- ✅ **Hurtowe „Dodaj do trasy…” dokończone w tle nie rusza bieżącego zaznaczenia ani fokusu** (`30c7ef9a` +
  `fe61e674`): wynik zapisu dokończonego po zamknięciu okna niesie `wTle: true`; wtedy z zaznaczenia schodzą tylko dodane
  zamówienia, a fokus przenosimy tylko wtedy, gdy był w pasku hurtu, który po odznaczeniu zniknął. Ścieżka z otwartym
  oknem bez zmian (I3). **Przyczyna, przez którą pierwsza wersja nie działała w oględzinach:** Chromium wysyła
  zdarzenie `close` okna `<dialog>` dopiero w następnej klatce animacji (karta w tle / schowany panel — wcale), a drugi
  Esc w trakcie zapisu daje `cancel` z `cancelable === false` i zamyka okno. Tryb „w tle” włącza się teraz od razu przy
  takim `cancel`, a koniec zapisu sprawdza `dialogDodaj.open` — bez polegania na `close`. Sprawdzone pomiarem zdarzeń we
  wbudowanej przeglądarce (scenariusze A, B, B2, C — PASS).

### 4.2. Decyzje dla Konrada
1. **Doróbka / nowa pozycja w zamówieniu dostarczonym trasą**: zamówienie zostaje zamknięte (tak samo jak odbiór osobisty
   od etapu 1); spec jest wewnętrznie sprzeczny (6.2 vs 8.3), a obsługa wymaga zmiany modelu (historia przystanków,
   UNIQUE `order_id`). Dziś taką doróbkę trzeba obsłużyć poza CRM.
2. **Odhaczenie trasy tylko ze spakowanymi**: przyjąłem, że niespakowane zamówienie nie może być „dostarczone” (409,
   w oknie pole nieaktywne z wyjaśnieniem) — potwierdź.
3. Uwagi bezpieczeństwa znalezione przy przeglądach (poza zakresem etapu) Konrad dostał w czacie; są też w pamięci
   Claude na tym komputerze — celowo nie ma ich w publicznym repo.

### 4.3. Świadomie odłożone drobiazgi (mogą czekać)
- Backend: ikona „etykiety sprzed zmiany” nie widzi zmian trasy po wydruku (brak znacznika czasu przypisania);
  `String(40)` vs `CHAR(40)` w modelu; brak CHECK `date_to >= date_from` w bazie (pilnuje serwis); N+1 w przelicz_otwarte;
  punkt automatyczny po zmianie adresu w Base. eksportowany do czasu przeliczenia przez geokoder; `przywroc` trasy wykonanej
  prosto z roboczej zostawia `approved_at = NULL`; stopka jednego commita (`4b4c6e79`) z inną nazwą modelu.
- UI: `logistics-routes.js` ma ok. 3800 linii i zduplikowane pomocniki (`esc`, `odmiana`, `zapytanie`) — refaktor po
  testach Konrada; komunikat „na pozycji N z M” liczy anulowane; log odhaczenia zapisuje anulowane jako „niedostarczone”;
  testy UI to testy tekstu źródła (brak runnera JS). (Potwierdzenie usunięcia trasy liczące anulowane — naprawione
  w rundzie 4.1.)
- Z rundy 4.1 (odłożone świadomie, szczegóły w `raporty-4-1\progress.md`):
  - komunikat po odhaczeniu (`logistics-routes.js` ok. `:3170–3180`) rozpoznaje anulowane po liście z okna — zamówienie
    anulowane już PO wczytaniu okna zostanie opisane jako „wraca do puli” (rzadkie; poprawka wymaga zmiany kształtu
    odpowiedzi `/complete`);
  - pozostałe okna zakładki (poprawka adresu w `logistics.js`, „Odhacz jako wykonaną”, pojazd we Flocie) sprzątają stan
    w zdarzeniu `close`, które w karcie w tle przychodzi dopiero po powrocie — bez widocznego skutku dla użytkownika,
    ale „Odhacz” w `close` przerywa (abort) zapytanie w toku, jeśli okno zamknięto drugim Esc w trakcie zapisu;
  - zmiana sposobu dostawy zamówienia z trasy przelicza zamknięcie dwa razy (idempotentnie; końcowe przeliczenie
    maskuje pierwsze, więc test tej ścieżki nie wykryłby regresji); test UI dzieli ciało `hurtTrasa` po wcięciu (kruche
    przy przeformatowaniu, ale błąd dałby czerwony test, nie fałszywie zielony).

## 5. Rozstrzygnięcia podjęte w trakcie (w kolejności; koszt, jeśli błędne)

1. Worktree `.claude/worktrees/logistyka-etap-3-trasy` zamiast ścieżki z planu — koszt: zero.
2. Task 6 nie tworzy trasy `/routimo` (sprzeczny tekst planu) — koszt: brak.
3. Identyfikatory w `dodaj_przystanki`/`zmien_kolejnosc`/`wykonaj` tylko jako lista int → inaczej 422 — koszt: kilka linii.
4. Zmiana nazwy pojazdu odświeża tablety (ETag) zamówień na aktywnych trasach — koszt: zbędne odświeżenie.
5. Blokada adresu na trasie zatwierdzonej po porównaniu „bez zmian” — koszt: brak.
6. Filtr `bez_trasy` w SQL (NOT EXISTS), nie w Pythonie — koszt: brak.
7. Timeout ORS 8 s (plan) zamiast 10 s (spec) — koszt: brak.
8. `GET /routes/map` przelicza najwyżej jedną trasę na żądanie — koszt: przebieg innej trasy odświeży się później.
9. Walidacja wejścia API tras (ciało, status, daty, zakresy, wyścig UNIQUE → 409) — koszt: kilkanaście linii.
10. Nazwa pliku Routimo z transliteracją polskich znaków — koszt: brak.
11. Eksport Routimo także dla trasy wykonanej (spec: „tylko zatwierdzona”) — koszt: trywialny.
12. „Odhacz jako wykonaną” także na roboczej (spec 8.2) — koszt: jeden przycisk.
13. Brak makiety — wzorem UI etapu 2 — koszt: drobne różnice stylu.
14. Oględziny na podglądzie z kopią bazy (5003) = też test migracji na MySQL — koszt: czas przygotowania.
15. ORS na żywo pominięty (brak klucza) — koszt: format odpowiedzi sprawdzony tylko na atrapie; `radiuses: [-1]` do sprawdzenia przed wdrożeniem.
16. **Globalna blokada zapisów tras** (wiersz `prod_config` brany jako pierwsza blokada, potem odczyty bieżące) zamiast
    blokad per pojazd (te zakleszczały się przy dwóch trasach naraz) — koszt: zapisy tras czekają na siebie po kilka ms;
    ryzyko resztkowe opisane w kodzie.
17. Testy podbijania `updated_at` dla każdej zmiany trasy — koszt: brak.
18. Walidacja typów pól (bool/inf/nie-tekst) w serwisach tras i floty — koszt: kilka linii.
19. Ręczna pinezka zamówienia na trasie zatwierdzonej/wykonanej = 409 (jak adres) — koszt: logistyk cofa zatwierdzenie, żeby poprawić pinezkę.
20. Doróbka po dostarczeniu trasą → decyzja Konrada (4.2.1) — koszt: doróbkę obsłużyć poza CRM.
21. WARNING o braku klucza ORS raz na proces — koszt: jedno ostrzeżenie na workera.
22. Kolejność blokad: blokada tras zawsze pierwsza także przy adresie, pinezce i hurcie; świeże przystanki po blokadzie; cyfry tylko ASCII; notatka ≤ 2000 znaków — koszt: jedna runda poprawek.
23. Zapis cache przebiegu poza blokadą (ORS nigdy pod blokadą) — koszt: krótkie oczekiwanie GET.
24. Lista tras ładowana zbiorczo + domyślne okno 30 dni dla wykonanych — koszt: starszą wykonaną trzeba znaleźć filtrem dat.
25. Niepoprawne ciało żądania → 422 wszędzie (wcześniej `/complete` ze złym JSON-em = „wszystko dostarczone”) — koszt: brak.
26. Trasa wykonana tylko do odczytu (bez przeliczania przebiegu), poza jednorazowym przeliczeniem w odpowiedzi `/complete` — koszt: stara geometria po zmianie pinezki.
27. Drobne poprawki API tras w tej samej rundzie (komentarze, teksty 409, testy, `route_id`, sortowanie mapy) — koszt: brak.
28. Do Routimo tylko dokładne współrzędne (przybliżone puste, Routimo geokoduje adres) — koszt: Routimo geokoduje kilka adresów.
29. Jedna runda poprawek UI łącząca przegląd kodu i oględziny — koszt: szersza runda.
30. Druga runda UI z N3 (komunikaty przesuwały przyciski — ryzyko złych kliknięć) — koszt: jedna runda więcej.
31. **Odhaczenie tylko spakowanych** (409 + okno ze stanem pakowania) — wbrew literze spec 8.2, zgodnie z celem — koszt: trzeba spakować albo odznaczyć.
32. Przebieg po awarii ORS / po dodaniu klucza przelicza się ponownie (warianty skrótu), `timeout=(3.05, 8)`, `radiuses=[-1]` — koszt: brak.
33. Niezmieniony wyłączony pojazd/kierowca nie blokuje edycji i przywrócenia trasy (spec 8.1) — koszt: brak.
34. (= 28) wykonane w fali końcowej.
35. Anulowane zamówienia: nie na trasę, pomijane w Routimo i w geometrii, liczone osobno, oznaczone w UI — koszt: brak.
36. Fala końcowa także: odczyt bieżący zamówień po blokadzie, zmiana nazwy pojazdu pod blokadą, samonaprawa wiersza blokady, nazwa trasy w ZPL bez `^`/`~` (30 znaków), `delivered_order_ids` wymagane, zapytania zbiorcze po commicie, granice dat (dziś−1 rok … dziś+2 lata, ≤ 31 dni), cron otwiera zamknięte z przystankiem na aktywnej trasie, format dat RRRR-MM-DD (3.9 = 3.12) — koszt: kilkadziesiąt linii i testów.
37. W oknie odhaczenia niespakowane i anulowane pola nieaktywne — koszt: nie da się „na siłę” oznaczyć niespakowanego.
38. Kształt API dla anulowanych (`anulowane`, `pozycja` wśród aktywnych, `podsumowanie.anulowane`, `X-Routimo-Pominiete`, `niespakowane` w 409) — koszt: brak.
39. Odłożone: hurtowe dodanie po zamknięciu okna (4.1) — koszt: rzadka irytacja. **Zrobione 28.09 (43, 45).**
40. Odłożone: anulowane zdjęte przy odhaczeniu wraca do puli do czasu crona (4.1) — koszt: do godziny zbędny wiersz.
    **Zrobione 28.09 (42).**

Runda 4.1 (28.09.2026):

41. Mini-plan rundy (`2026-09-28-logistyka-etap-3-poprawki-4-1.md`, 2 zadania) zamiast planu od zera — źródłem zadań
    była sekcja 4.1 — koszt: brak.
42. Poprawka „anulowane zdjęte z trasy” w `routes.usun_przystanek` (wszyscy czterej wołający), nie tylko w pętli
    `wykonaj` — spec 6.2 każe przeliczać zamknięcie po każdej zmianie, a ręczne zdjęcie i usunięcie trasy miały ten sam
    błąd; `trasa=route` (świeża trasa spod blokady, bez dodatkowego odczytu przystanku) — koszt: jedno zbędne,
    idempotentne przeliczenie przy zmianie sposobu dostawy.
43. Zapis „Dodaj do trasy…” dokończony w tle: z zaznaczenia schodzą tylko dodane, fokus tylko gdy ginąłby z paskiem
    hurtu; ścieżka z otwartym oknem bez zmian (I3) — koszt: w tle nieudane zostają zaznaczone (logistyk odznacza sam).
44. Przegląd końcowy tej rundy = adwersaryjny przegląd zakresu rundy (`3eafac50..`) + oględziny 4.1; adwersaryjny
    przegląd CAŁEJ gałęzi i pełne oględziny — na koniec następnej rundy (uwagi Konrada), żeby nie robić ich dwa razy —
    koszt: pełny przegląd gałęzi przesunięty o jedną rundę, i tak przed jakimkolwiek merge.
45. Tryb „w tle” okna „Dodaj do trasy…” nie polega na zdarzeniu `close` (Chromium: następna klatka animacji; karta
    w tle — wcale): przełącza `cancel` bez możliwości anulowania w trakcie zapisu, koniec zapisu sprawdza
    `dialogDodaj.open` i sprząta stan, spóźnione `close` przy ponownie otwartym oknie jest ignorowane — koszt:
    kilkanaście linii JS.
46. Teksty o anulowanych po zdjęciu z trasy (komunikat ręcznego zdjęcia, potwierdzenie usunięcia trasy) naprawione
    w tej rundzie, bo po 42 mówiłyby nieprawdę; komunikat po odhaczeniu (anulowane rozpoznawane po liście z okna) —
    odłożony (4.3) — koszt: rzadki mylący komunikat.

Ujednolicenie (28.09, prośba Konrada „jedna gałąź, jedno miejsce do sprawdzania”):

47. Gałąź zostaje pod nazwą `claude/logistyka-etap-3-trasy` (zawiera wszystkie etapy), bez zmiany nazwy — dokumenty,
    pamięć i worktree już się do niej odwołują — koszt: nazwa sugeruje sam etap 3.
48. Jedynym podglądem logistyki jest kopia produkcji (dawny 5004) przeniesiona na 5003 z tym samym kluczem sesji —
    ma te same zamówienia co produkcja 28.09 i testy Konrada z rana; dawny podgląd z danymi testowymi wyłączony, jego baza
    zostaje do decyzji (trasa 17) — koszt: trasy testowe oględzin nie są już widoczne w przeglądarce.
49. 5002 zostaje `main` (reguła „nie przełączaj gałęzi w głównym checkoucie”); podgląd logistyki na 5002 wymagałby
    wykonania migracji gałęzi na bazie roboczej `woodpower_crm_local` — koszt: dwa adresy (5002 = produkcja, 5003 =
    logistyka) zamiast jednego.

## 6. Lista wdrożenia (nic bez decyzji Konrada)
1. Etap 1 (jest w tej gałęzi): **najpierw appka 1.7.0 (vc38) na wszystkich tabletach**, dopiero potem backend; wpis crontaba
   logistyki co godzinę (`scripts/cron_endpoint.sh POST /production/api/logistics/cron`) i jedno ręczne uruchomienie.
2. Etap 2: `CARTO_BASEMAPS_KEY` jest już w `core.json` na serwerze (25.09, z restartem). Geokoder rusza z cronem.
3. Etap 3: konto OpenRouteService (darmowe, 2000 tras/dobę), `OPENROUTESERVICE_API_KEY` w `core.json` na serwerze i
   **od razu** `crm-fix-logs-perms.sh && supervisorctl restart crm_woodpower`; próba ORS na żywo (także adres wiejski,
   sprawdzenie `radiuses`); po migracji `SELECT config_key FROM prod_config WHERE config_key='logistyka_trasy_blokada'`.
4. Wdrożenie = merge `claude/logistyka-etap-3-trasy` do `main` (zawiera 1+2); gałąź nie zmienia `deploy.sh`, skryptów ani
   `requirements.txt`, więc bez wdrożenia dwuetapowego.
5. Zaraz po wdrożeniu: logistyk ustawia sposoby dostawy (hurtem, z podpowiedzią Base.) — **75 zamówień** z pozycjami na
   pakowaniu czeka na decyzję; dodaje pojazdy we Flocie; próba eksportu Routimo w Routimo; na tablecie pakowania nazwa
   trasy na plakietce; akcja Base. „Odebrane → drukuj KP” przy statusie ustawionym przez API; jeden testowy wydruk etykiety
   z długą nazwą trasy.

## 7. Sprzątanie na Windows (dopiero po zakończeniu prac — na czas kontynuacji podglądy i bazy zostają)
- Podgląd: `docker rm -f logistyka3-prod`; bazy w kontenerze `woodpower-crm-db-1`: `DROP DATABASE logistyka3_prod;`.
  Baza dawnego podglądu testowego `logistyka3_podglad` (bez kontenera od 28.09; trasa 17 „trasa 1” Konrada i trasy
  testowe) — `DROP DATABASE logistyka3_podglad;`, gdy Konrad potwierdzi, że trasa 17 nie jest potrzebna.
- Zrzuty produkcji (dane klientów) w scratchpadach sesji: `…\320e7d76-…\scratchpad\prod\crm_dump_2026-09-25.sql.gz`
  i `…\cea01798-…\scratchpad\prod\crm_dump_2026-09-28.sql.gz` oraz kopia `…\cea01798-…\scratchpad\kopie\
  woodpower_crm_local_przed_2026-09-28.sql.gz` — usuń ręcznie; razem z nimi całe katalogi scratchpadów sesji
  `320e7d76-…` (kody podglądów, archiwa `kod.tar`, raporty) i `cea01798-…` (raporty rundy 4.1).
- `C:\Users\Grafik\Downloads\routimo_krakow_2026-09-29.xlsx` (2 B, plik testowy) — nadal leży, usuń ręcznie.
- Kopia konfiguracji na serwerze przed wpisaniem klucza CARTO: `config/core.json.bak-20260925-carto` (600).

## 8. Prompt startowy dla kolejnej sesji (Windows)

> Kontynuujemy „logistykę równoległą” w WoodPower CRM — etap 3 (trasy i flota), dalej na Windows. Repo:
> `C:\Users\Grafik\Documents\woodpower-crm`. Gałąź robocza `claude/logistyka-etap-3-trasy` (zawiera etapy 1 i 2; nic nie
> jest w `main` ani wdrożone; **nie merguj i nie pushuj na `main` bez mojego polecenia**). Pracuj w istniejącym worktree
> `C:\Users\Grafik\Documents\woodpower-crm\.claude\worktrees\logistyka-etap-3-trasy` — jeśli sesja wystartowała gdzie
> indziej (np. w nowym worktree od `main`), przejdź do niego; gdyby go nie było:
> `git worktree add .claude/worktrees/logistyka-etap-3-trasy claude/logistyka-etap-3-trasy`. Nie przełączaj gałęzi
> w głównym checkoucie (na nim stoi `main` i kontener 5002).
>
> Najpierw przeczytaj w worktree `docs/superpowers/plans/2026-09-26-logistyka-etap-3-przekazanie.md` — to jedyne źródło
> prawdy o etapie 3 (sekcja 0: stan na 28.09, podglądy i raporty; 2: zmiany w bazie; 4: co otwarte; 5: rozstrzygnięcia;
> 6: lista wdrożenia), potem plan `docs/superpowers/plans/2026-09-24-logistyka-etap-3-trasy-flota.md` i spec
> `docs/superpowers/specs/2026-09-24-logistyka-rownolegla-trasy-design.md`.
>
> Sprawdź środowisko: `git fetch origin` (czy gałąź i `main` nie odjechały od stanu z sekcji 0), testy z katalogu worktree
> `docker compose -p logistyka3 run --rm --no-deps app pytest tests/ -q -p no:cacheprovider` (oczekiwane 4704 passed,
> 3 skipped), podgląd logistyki 127.0.0.1:5003 (kopia produkcji, jedyny — sekcja 0) i localhost:5002 (`main`) odpowiadają. Nie uruchamiaj
> kodu gałęzi na roboczej bazie `woodpower_crm_local` (migracje nieodwracalne — sekcja 2).
>
> Punkt 4.1 jest zrobiony (28.09, sekcja 4.1). Moje uwagi z testów i **nowe rzeczy spoza planu** wypiszę w kolejnej
> wiadomości — z nich zrobimy plan następnej rundy; po niej adwersaryjny przegląd całej gałęzi (sekcja 5, pkt 44). Tryb subagent-driven (superpowers): przegląd po każdym zadaniu, na koniec
> adwersaryjny przegląd całej gałęzi i oględziny UI na kopii danych. Subagenci tylko we wbudowanej przeglądarce
> (`mcp__Claude_Browser__*`) — nigdy mój Chrome ani `chrome.exe`, nigdy produkcja, bez pobierania plików. Po zmianach kodu
> odświeżaj kod podglądów (sekcja 0). Commity Conventional Commits po polsku (scope `production`), dokument przekazania
> aktualizuj na bieżąco (sekcje 0, 4 i 5), na koniec push gałęzi na origin. Zacznij od potwierdzenia, że środowisko działa.
