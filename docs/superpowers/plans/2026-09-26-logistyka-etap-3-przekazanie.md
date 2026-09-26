# Logistyka równoległa — etap 3 (trasy i flota): stan gałęzi i przekazanie na Maca

Data: 2026-09-26. Źródło: sesja na Windows (tryb subagent-driven, plan
`docs/superpowers/plans/2026-09-24-logistyka-etap-3-trasy-flota.md`, spec
`docs/superpowers/specs/2026-09-24-logistyka-rownolegla-trasy-design.md`). Plany etapów 1–3 i spec są od tego
commita w repo na gałęzi (mimo `.gitignore`, na prośbę Konrada — repo jest publiczne, więc nie dopisuj tu sekretów).

## 1. Gałęzie i stan

- Piętrowe: `claude/logistyka-etap-1-dostawy-22cf12` → `claude/logistyka-etap-2-mapa` → **`claude/logistyka-etap-3-trasy`**
  (zawiera etapy 1 i 2; 65+ commitów ponad `main`). **Nic nie jest w `main` ani wdrożone.** Merge do `main` = deploy
  (webhook) — wyłącznie na polecenie Konrada.
- Etap 3: 9 zadań planu + 3 rundy poprawek interfejsu + fala poprawek po dwóch przeglądach końcowych (backend, UI).
- Testy: `4695 passed, 3 skipped` (pełny pakiet w Dockerze, SQLite, Python 3.12; kod zgodny z Pythonem 3.9 produkcji —
  sprawdzone kompilacją na python:3.9-slim).
- Weryfikacja poza testami (na Windows):
  - migracje etapów 1–3 na MySQL 8.4: na kopii lokalnej bazy i na **świeżej kopii produkcji z 25.09 21:07** (4/4, idempotentne, 2× ręcznie);
  - blokada zapisów tras na dwóch prawdziwych sesjach MySQL (wyścigi S1–S5b: podwójne zajęcie pojazdu, zakleszczenia, stary status, odhaczenie vs dodanie, adres vs zapis trasy) — PASS po poprawkach;
  - 315 „złych” żądań do całego API logistyki na MySQL — 0 × 5xx, integralność danych OK;
  - 4 tury oględzin interfejsu we wbudowanej przeglądarce na kopii danych (1440/1280/1024/768) — ostatnia: PASS poza punktem 4.1 niżej.

## 2. Zmiany w bazie przy aktualizacji repo na Macu (przeczytaj, zanim uruchomisz kod gałęzi)

Migracje wykonują się **same przy starcie aplikacji** (`RUN_MIGRATIONS`, domyślnie włączone) i przy `flask migrate`.
Uruchomienie kodu tej gałęzi na bazie Maca wykona **nieodwracalnie** cztery migracje (runner zapisuje je w `schema_migrations`):

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
- `.env`: `FLASK_SECRET_KEY` (już jest), porty Maca `CRM_APP_PORT=5002`, `CRM_DB_PORT=3308`.
- Stan „jak po wdrożeniu dziś” (kopia produkcji z 25.09): 209 zamówień w Logistyce, 208 z nich „Nie ustawiono”,
  **75 ma pozycje czekające na pakowanie** (tablet zablokuje ich pakowanie do ustawienia sposobu dostawy), flota pusta,
  współrzędnych brak (trzeba „Zlokalizuj teraz” albo cron).

## 3. Testy i podgląd na Macu

- Z katalogu worktree: `docker compose -p logistyka3 run --rm --no-deps app pytest tests/ -q -p no:cacheprovider`
  (oczekiwane 4695 passed, 3 skipped); `integrations/blog_seo` osobno. `docker compose exec` z worktree testuje
  GŁÓWNY checkout, nie gałąź. Nie twórz `config/core.json` w worktree (zmienia wyniki testów).
- Podgląd gałęzi: osobny kontener z kodem z `git archive` + kopia bazy + kopia `core.json` bez integracji, na innym porcie;
  gdy chodzi obok innego podglądu na tym samym hoście, ustaw w jego `core.json` własne `SESSION_COOKIE_NAME` i
  `REMEMBER_COOKIE_NAME` (ciasteczka nie rozróżniają portów). Loguj się przez `127.0.0.1:<port>`, nie `localhost`.
- Subagenci z przeglądarką: tylko wbudowana, odizolowana przeglądarka; **nigdy Chrome Konrada** (jego sesje, produkcja).

## 4. Co zostało otwarte

### 4.1. Do poprawy na starcie (znalezione w ostatnich oględzinach, odłożone zgodnie z procesem)
- **W pełni anulowane zamówienie zdjęte przy odhaczeniu trasy jako „niedostarczone” wraca do puli „Transport bez trasy”**
  zamiast się zamknąć: `usun_przystanek` w ścieżce niedostarczonych z `routes.wykonaj()` nie woła
  `delivery.przelicz_zamkniecie`. Osiągalne, gdy anulowanie ominęło przeliczenie (SQL, wyścig); cron `przelicz_otwarte`
  zamyka je w ≤ 1 h. Poprawka: `przelicz_zamkniecie` dla zdjętych zamówień (w `wykonaj`/`usun_przystanek`) + test.
- Hurtowe „Dodaj do trasy…”, które kończy się po zamknięciu okna (dwa Esc w trakcie zapisu), czyści bieżące zaznaczenie i
  przenosi fokus (`logistics-routes.js` ok. `:2919` + `logistics.js` ok. `:1390–1394`) — Minor.

### 4.2. Decyzje dla Konrada
1. **Doróbka / nowa pozycja w zamówieniu dostarczonym trasą**: zamówienie zostaje zamknięte (tak samo jak odbiór osobisty
   od etapu 1); spec jest wewnętrznie sprzeczny (6.2 vs 8.3), a obsługa wymaga zmiany modelu (historia przystanków,
   UNIQUE `order_id`). Dziś taką doróbkę trzeba obsłużyć poza CRM.
2. **Odhaczenie trasy tylko ze spakowanymi**: przyjąłem, że niespakowane zamówienie nie może być „dostarczone” (409,
   w oknie pole nieaktywne z wyjaśnieniem) — potwierdź.
3. Uwagi bezpieczeństwa znalezione przy przeglądach (poza zakresem etapu) Konrad dostał w czacie — celowo nie ma ich
   w publicznym repo.

### 4.3. Świadomie odłożone drobiazgi (mogą czekać)
- Backend: ikona „etykiety sprzed zmiany” nie widzi zmian trasy po wydruku (brak znacznika czasu przypisania);
  `String(40)` vs `CHAR(40)` w modelu; brak CHECK `date_to >= date_from` w bazie (pilnuje serwis); N+1 w przelicz_otwarte;
  punkt automatyczny po zmianie adresu w Base. eksportowany do czasu przeliczenia przez geokoder; `przywroc` trasy wykonanej
  prosto z roboczej zostawia `approved_at = NULL`; stopka jednego commita (`4b4c6e79`) z inną nazwą modelu.
- UI: `logistics-routes.js` ma ok. 3800 linii i zduplikowane pomocniki (`esc`, `odmiana`, `zapytanie`) — refaktor po
  testach Konrada; komunikat „na pozycji N z M” liczy anulowane; potwierdzenie usunięcia trasy liczy anulowane jako
  „wróci do puli”; log odhaczenia zapisuje anulowane jako „niedostarczone”; testy UI to testy tekstu źródła (brak runnera JS).

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
39. Odłożone: hurtowe dodanie po zamknięciu okna (4.1) — koszt: rzadka irytacja.
40. Odłożone: anulowane zdjęte przy odhaczeniu wraca do puli do czasu crona (4.1) — koszt: do godziny zbędny wiersz.

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

## 7. Sprzątanie na Windows (gdy już niepotrzebne)
- Podglądy: `docker rm -f logistyka3-podglad logistyka3-prod`; bazy w kontenerze `woodpower-crm-db-1`:
  `DROP DATABASE logistyka3_podglad; DROP DATABASE logistyka3_prod;`.
- Zrzut produkcji (dane klientów) w scratchpadzie sesji: `…\scratchpad\prod\crm_dump_2026-09-25.sql.gz` — usuń ręcznie.
- `C:\Users\Grafik\Downloads\routimo_krakow_2026-09-29.xlsx` (2 B, plik testowy) — usuń ręcznie.
- Kopia konfiguracji na serwerze przed wpisaniem klucza CARTO: `config/core.json.bak-20260925-carto` (600).

## 8. Prompt startowy dla sesji na Macu

> Kontynuujemy „logistykę równoległą” w WoodPower CRM — etap 3 (trasy i flota). Repo: `~/Documents/woodpower-crm`.
> Gałąź robocza: `claude/logistyka-etap-3-trasy` (zawiera etapy 1 i 2; nic nie jest w `main` ani wdrożone; **nie merguj
> i nie pushuj na `main` bez mojego polecenia**). Pracuj w osobnym worktree:
> `git fetch origin && git worktree add ../woodpower-crm-logistyka-3 claude/logistyka-etap-3-trasy` i nie przełączaj gałęzi
> w głównym checkoucie.
>
> Najpierw przeczytaj w worktree `docs/superpowers/plans/2026-09-26-logistyka-etap-3-przekazanie.md` (stan, rozstrzygnięcia,
> decyzje, **sekcja 2 — zmiany w bazie**, lista wdrożenia), potem plan `docs/superpowers/plans/2026-09-24-logistyka-etap-3-trasy-flota.md`
> i spec `docs/superpowers/specs/2026-09-24-logistyka-rownolegla-trasy-design.md`.
>
> Przygotuj środowisko: kopia bazy do testów (migracje etapów 1–3 wykonają się same przy starcie i są nieodwracalne —
> nie na mojej roboczej bazie, jeśli używam jej dla `main`), w konfiguracji testowej wyczyść klucz Base., pocztę i
> integracje; sprawdź testy `docker compose -p logistyka3 run --rm --no-deps app pytest tests/ -q -p no:cacheprovider`
> (oczekiwane 4695 passed, 3 skipped) i uruchom podgląd gałęzi na kopii danych. Na Macu `python3`, porty 5002/3308.
>
> Zadania na start: (1) popraw punkt 4.1 dokumentu przekazania (anulowane zamówienie wracające do puli po odhaczeniu +
> hurtowe dodanie po zamknięciu okna), (2) potem przejdziemy do moich uwag z testów i **nowych rzeczy spoza planu** —
> wypiszę je w następnej wiadomości. Pracuj w trybie subagent-driven (superpowers): przegląd po każdej zmianie, na koniec
> adwersaryjny przegląd całej gałęzi i oględziny UI na kopii danych we wbudowanej przeglądarce (nigdy mój Chrome).
> Commity Conventional Commits po polsku (scope `production`), na koniec push gałęzi na origin. Zacznij od potwierdzenia,
> że środowisko działa, i czekaj na moją listę.
