# Priorytety produkcji, krok K5 — „przegląd P1”: pełne testy, migracja na kopii produkcji, wyścigi MySQL, oględziny, dokumentacja, werdykt — plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Jedna sesja odpowiada na pytanie „czy P1 (K1–K4b) jest gotowe do wdrożenia na produkcję”: pełny pakiet testów
(`tests/` i `integrations/blog_seo`) zielony, migracja `2026-10-05-priorytety-produkcji.sql` przechodzi dwa razy na
kontenerze `db` **i** na kopii produkcji bez tabel logistyki (runner wykonuje najpierw migracje logistyki, potem FK
szczebli do `prod_routes`), piętnaście wyścigów na dwóch sesjach MySQL kończy się bez zakleszczenia bez ponowienia,
bez zdublowanego kafla i bez niekompletnego kafla-zamówienia na stole, UI i API mobilne obejrzane na podglądzie z brokerem
Centrifugo, a CLAUDE.md i spec opisują to, co faktycznie powstało. Na końcu raport z werdyktem „P1 GOTOWE DO WDROŻENIA”
albo listą blokad, oraz lista wdrożenia P1 dla K7.

**Architecture:** K5 **nie dodaje funkcji**. Dotyka kodu tylko przy naprawie regresji w zakresie pakietu
`modules/production/priorytety/` i jego testów (każda naprawa = osobny commit `fix(priorytety): …` i numerowane
rozstrzygnięcie w raporcie). Narzędzia kroku żyją poza repo: skrypt wyścigów `_priorytety_wyscigi.py` (dwa wątki z
`threading.Barrier(2)`, osobne `app.test_client()` albo HTTP na podgląd, osobne `X-Operation-Id`, trzy miary 1213:
licznik InnoDB `lock_deadlocks`, log aplikacji, odpowiedzi 500 — jak `_zamowienie_najpierw_wyscigi.py` z kroku 4.4a
i `_dostawa_wyscigi.py` z 4.4b), kopia produkcji jako osobna baza w kontenerze `db`, broker Centrifugo w kontenerze
dockera na podglądzie. Dokumentacja wchodzi do repo: CLAUDE.md (nowa sekcja „Priorytety produkcji”, uzupełnienie
„Logistyka równoległa”, poprawka akapitu pisarzy pozycji), spec (sekcja „16. Doprecyzowania z realizacji” i dopisek
w 11 „Lista wdrożenia P1”), raport kroku.

**Tech Stack:** Flask 2 + SQLAlchemy < 2.0, MySQL 8.4 (produkcja i kontener `db`, REPEATABLE READ) / SQLite in-memory
(testy), pytest, Centrifugo v6 (sygnał bez ładunku), curl, `general_log` MySQL, `SHOW ENGINE INNODB STATUS`.

**Spec:** `docs/superpowers/specs/2026-10-04-priorytety-produkcji-design.md` — 4.2 (`utrwal`, blokady), 4.3 (terminy),
4.4 (cykl szczebla trasy), 5.2 (pobieranie na stół, blokada stanowiska, 1213), 5.3 (Odłóż), 5.4 (sygnały), 5.5 (bramki),
5.6 (kompletność), 6.1–6.3 (kontrakt mobilny), 8.7 (migracja: „sprawdzić na kontenerze `db` i na kopii produkcji”),
9.3 (wyzwalacze), **9.4** (współbieżność), 10 (błędy), **11** (kroki wdrożenia, „Po wdrożeniu P1 uruchom raz ręcznie…
Wpis do CLAUDE.md razem z P1”), **13** (testy MySQL: migracja ×2, wyścigi, kryterium), 15 (mapa). Symulacja:
`docs/superpowers/specs/2026-10-04-priorytety-produkcji-symulacja.md`, „Analiza wyniku” (A: dziś 84–96 % zakończeń
z pominięciem pilniejszego — poziom odniesienia dla pomiaru po P3; D p. 7: „po wdrożeniu mierzyć tym samym skryptem”)
i „E. Decyzje Konrada”. Podręcznik centrali: `docs/superpowers/plans/2026-10-05-priorytety-produkcji-centrala.md`
(sekcje 2, 4a, 5 p. 4 bramka, 6, 8.0, **8.6**). Plany K1–K4b: sekcje „Doprecyzowania (do specu — K5 przeniesie)”,
„Pytania do Konrada”, „Co następny krok musi wiedzieć” (K5) i lista wyścigów K3 (Task 6, Step 5).

**Sesja:** lokalna — Docker (`docker compose exec app pytest`), kontener `db` (migracja ×2, druga baza na kopię
produkcji), **podgląd MySQL z dwiema sesjami** (wyścigi: dwa wątki klienta + `mysql` CLI na `SHOW ENGINE INNODB STATUS`),
przeglądarka (oględziny), curl (API mobilne), kontener Centrifugo (sygnały). **Model:** Fable 5.1, effort **extra**
(podręcznik 4a: werdykt „gotowe” i analiza 1213 to błędy, których testy SQLite nie łapią; przy pierwszym 1213 —
analiza `INNODB STATUS` na Fable 5.1 **max**, zanim ktokolwiek zmieni kod). Bez trybu szybkiego.

**Zależności:** K1, K2, K3, K4a, K4b zakończone i zaliczone na bramce (raporty w `docs/superpowers/plans/raporty/`).
Jeśli K4a albo K4b nie są scalone na gałęzi roboczej — STOP przed Task 1 (centrala najpierw zleca scalenie).

**Gałąź:** `claude/priorytety-produkcji`. Start: `git fetch origin && git checkout claude/priorytety-produkcji &&
git pull --ff-only origin claude/priorytety-produkcji`. Nigdy `main` (push do `main` = deploy). **Numery linii w tym
planie dotyczą `claude/logistyka-etap-4` @ `b4b4a54d`, czyli sprzed K1** — po K1–K4b linie się przesunęły; szukaj po
nazwie (`grep -n`), nazwy są podane w każdym miejscu. Nazwy funkcji pakietu `priorytety` pochodzą ze specu 9.1/9.2
i planów K1–K4b; faktyczne nazwy potwierdza Task 1, Step 2 (raporty K1–K4b, „Odstępstwa”).

## Global Constraints

- **Python 3.9** w każdej poprawce: bez `X | Y` w adnotacjach poza plikami z `from __future__ import annotations`,
  bez `match`. Komentarze po polsku; w UI „Base.”.
- **Zakres zmian w kodzie:** wyłącznie naprawa regresji, której przyczyna leży w pakiecie `modules/production/priorytety/`,
  jego przepięciach z K1–K4b albo w testach `tests/test_priorytety_*.py`. Każda naprawa = test, który pada → poprawka →
  test zielony → osobny commit. Regresja wymagająca zmiany projektu, padający test spoza zakresu z przyczyną spoza
  priorytetów, spór spec ↔ kod — **STOP**, meldunek do centrali (podręcznik, sekcja 6). Nic „przy okazji”.
- **Kolejność blokad (CLAUDE.md „Trasy logistyki — jeden piszący naraz”, „Deklaracje paczek”, „zamówienie najpierw”;
  spec 9.4):** [pracownicy `touch_sessions`] → [`routes.zablokuj_trasy()`] → [`paczki.zablokuj_deklaracje()`] → zamówienia
  `FOR UPDATE` rosnąco po id → paczki → pozycje rosnąco po id → zapisy. Nowe zamki P1: `priorytety_blokada_<S>` (tylko
  `stol.dopelnij`, jako pierwsze polecenie nowej transakcji, potem S na zamówieniach i pozycjach), `prod_priority_rungs`
  `FOR UPDATE` (tylko pod blokadą tras), wiersze `prod_station_desk` (tylko pod X zamówienia albo pod blokadą stanowiska).
  K5 **sprawdza** tę kolejność na MySQL — nie zmienia jej. Każdy wyścig w Task 4 ma w tabeli zapisaną oczekiwaną
  kolejność blokad obu stron i odwołanie do ramki w planie K1/K2/K3.
- **Bazy:** nigdy baza produkcyjna (import `create_app()` uruchamia migracje gałęzi — `app.py` `RUN_MIGRATIONS`, `:179`).
  Kopia produkcji = zrzut wczytany do **osobnej bazy w kontenerze `db`** (`prod_kopia_priorytety`), dane klientów nie
  trafiają do raportu, repo ani zrzutów ekranu. Podgląd, porty i katalog poza repo — wg wskazań centrali (S-3).
- **`core.json` podglądu na kopii produkcji odcięty od świata (przed pierwszym startem podglądu):** `API_BASELINKER.api_key`
  pusty albo fałszywy — inaczej dopychacz Base. z crona (Task 2 Step 4) i zapisy z wyścigów (`desk-panel-sposob` →
  `bl_sync.po_zmianie`, `utrwal-dostawa` → status 524520, hurt, doróbka) wyślą zmiany do **prawdziwego** konta Base.
  na zamówieniach z kopii; `SENTRY.enabled=false` i `SENTRY_FRONTEND.enabled=false` (błędy podglądu nie trafiają do
  produkcyjnego Sentry), `MAIL_*` fałszywe, `GLOB_KURIER`/`OPENROUTESERVICE_API_KEY`/`CARTO_BASEMAPS_KEY` puste;
  `SECRET_KEY` losowy ≥ 32 znaki (bez niego `create_app()` rzuca `BrakKluczaSesjiError`); `RUN_DB_SETUP: false` (jak
  `deploy.sh` — sama migracja, bez `create_all()` po niej, które dorobiłoby tabele brakujące w migracji i zafałszowało
  Task 2); `PRODUCTION_CRON_SECRET` losowy. Geokoder z crona odpyta GUGiK/Nominatim adresami z kopii — jak produkcja,
  dopuszczalne. Sprawdzenie przed startem: `python3 -c` czytający `core.json` podglądu wypisuje tylko **nazwy** pól
  niepustych (bez wartości).
- **Serwisy nie commitują; w handlerach API mobilnego żadnego `db.session.commit()`** poza `GET desk` (K3) i dwoma
  miejscami sprzed P1 (`mobile_print_label_by_id` — druk wybranych sztuk, `device_heartbeat`; poza handlerem: serwis
  `rework_service.reject_product_quantity` commituje sam — znane, do K8) — K5 potwierdza grepem, nie zmienia. **Żadnych blokad przy HTTP do Base.** — `apply_baselinker_changes` ma Base. przed
  blokadami (4.4a); K5 to tylko potwierdza w wyścigu `hurt-desk`/`desk-dorobka` nie dotykając Base. (podmiana
  `get_order_from_baselinker` w procesie skryptu jak w 4.4a).
- **Migracje:** K5 nie dodaje migracji. Jeśli migracja K1 pada na kopii produkcji — STOP (błąd modelu danych albo
  założenia o schemacie produkcji), bez poprawiania „na szybko”.
- **Wyścigi:** kryterium (karta 8.6): zero 1213 bez ponowienia, zero zdublowanych kafli na stole, zero niekompletnych
  kafli-zamówień na stole. Pierwsze 1213 albo złamany niezmiennik → `SHOW ENGINE INNODB STATUS` (sekcja `LATEST DETECTED
  DEADLOCK`, bez zrzutów rekordów z danymi klientów), dokończ serię dla częstości, **STOP** i meldunek. Bez zmian w kodzie
  w tym kroku (decyzja należy do Konrada i centrali).
- Testy: `docker compose exec app pytest <ścieżki> -q -p no:cacheprovider`; pełny pakiet `tests/` i osobno
  `docker compose exec app bash -c "cd integrations/blog_seo && python -m pytest"` (CLAUDE.md: gołe `pytest` z korzenia
  dla `blog_seo` nie działa). Najwyżej jeden pełny pakiet naraz (pamięć ~13 GiB, plany 4.4a/4.4b).
- Commity: Conventional Commits po polsku, temat bez polskich znaków, jeden na Task (Task 1 może mieć 0–n commitów
  `fix(priorytety)`), stopka atrybucji własnej sesji. `docs/superpowers/` przez `git add -f`. Push wg karty (S-2).
- Repo publiczne: bez sekretów (klucze Centrifugo podglądu, hasła baz, cookie), adresów IP i danych klientów w commitach,
  raporcie i skryptach poza repo, które mogłyby trafić do repo.
- `tools/print_agent` — bez zmian. Agent druku na podglądzie **nie działa** w czasie wyścigów (po seriach z Pakowaniem
  wygaś etykiety jak w 4.4a: `UPDATE prod_print_queue SET status='expired' WHERE status='pending'`).

## Review Focus

1. **Piętnaście wyścigów na MySQL bez zakleszczenia bez ponowienia** (spec 13, karta 8.6): tryby `desk-desk`,
   `desk-zakoncz-inne`, `gwiazdki-zakoncz`, `szczebel-przystanek`, `utrwal-dostawa`, `odloz-zakoncz-ten-sam-kafel`
   (obowiązkowe, 62 przebiegi każdy) + 9 trybów z listy K3, w tym `odloz-hurt` (30 przebiegów każdy). Niezmienniki po
   KAŻDYM przebiegu: `stol_bez_duplikatow`, `stol_bez_nieaktualnych`, `stol_bez_niekompletnych`, `rangi_zbiezne`
   (definicja w Task 3 — punkt stały po dodatkowym `utrwal()`, nie „zero zmian od razu”; Doprecyzowania p. 9) (Task 4).
2. **Migracja na kopii produkcji bez `prod_routes`**: runner wykonuje `2026-09-27-logistyka-trasy-flota.sql` przed
   `2026-10-05-priorytety-produkcji.sql` (kolejność nazw, `migrations/migration_service.py:32-34`), FK
   `fk_prod_priority_rungs_route` powstaje, drugi przebieg „Wykonano 0 migracji”; `tests/test_migracja_priorytety.py`
   (K1) i `tests/test_migration_service.py::test_wszystkie_pliki_w_katalogu_migracji_sa_rozpoznawane` zielone (Task 2).
3. **Nowy algorytm na prawdziwych danych zgadza się z symulacją**: `GET /production/api/priorytety/kolejka` na kopii
   produkcji kontra `scripts/symulacja_priorytetow.py --db-url … --blisko 3 --dzis <ta sama data>` — ta sama kolejność
   zamówień aktywnych (różnice tylko tam, gdzie kopia ma trasy/gwiazdki, których symulacja nie zna) (Task 2).
4. **Sygnały idą po commicie na właściwe kanały przez prawdziwy broker**: subskrypcja SSE `station:gluing` i
   `station:formatting` widzi publikację po ZAKOŃCZ na Sklejaniu; po 409 `nie_na_stole` nic nie przychodzi; przy
   wyłączonym brokerze `GET /api/mobile/realtime-token` → 503, a `desk`/`complete` dalej 200 (Task 5; testy SQLite:
   `test_zakoncz_sygnal_na_to_i_nastepne_stanowisko`, `test_sygnal_nie_idzie_przy_rollbacku_409` z K3).
5. **Bramka stołu w trybie `stol` na podglądzie**: `POST complete` kafla poza stołem → 409 `nie_na_stole` bez wpisu
   idempotencji; `postpone` ponad limit → 409 `limit_odlozen`; ZAKOŃCZ odłożonego → 200 i `odlozenie_zamkniete`
   (Task 5; testy K3: `test_bramka_409_nie_na_stole_w_trybie_stol`, `test_nie_na_stole_nie_zapisuje_wpisu_idempotencji`,
   `test_zakoncz_odlozonego_200`).
6. **Czasy na kopii produkcji (~250 zamówień aktywnych)**: `GET desk` ≤ 300 ms (K3), `GET /kolejka` i modal ≤ 1 s (K2),
   zakładka Stanowiska ≤ 1 s (K4b), akcja trasy z `utrwal()` po commicie — zmierzony przyrost (K1, pytanie 2).
   Przekroczenie = uwaga w werdykcie z liczbami, nie samowolna optymalizacja (Task 5).
7. **Dokumentacja zgodna z kodem**: każde zdanie nowej sekcji CLAUDE.md i sekcji 16 specu ma pokrycie w kodzie
   (ścieżka:linia w notatce roboczej); akapit pisarzy pozycji nie wymienia już przeciągania ani `set-priority`
   (`test_martwe_koncowki_priorytetow_usuniete` K2/K4a, `test_set_priority_usuniete` K4a) (Task 6).
8. **Werdykt z liczbami**: raport zawiera tabelę wyścigów, wyniki migracji z obu baz, czasy, listę blokad albo
   „P1 GOTOWE DO WDROŻENIA” i listę wdrożenia dla K7 (Task 7).

## Decyzje przyjęte (ze specu i symulacji)

1. Spec v2 z 4.10 zatwierdzony (Konrad 4–5.10); P1 wdraża się **po** logistyce etapy 1–4, nigdy przed (spec nagłówek, 11).
2. Próg „Blisko terminu” **3 dni robocze** (Konrad 5.10; symulacja E) — spec 4.3 „domyślnie 2” to zaszłość; K5 poprawia
   spec (Task 6). Domyślna drabina ★★★★★, Po terminie, ★★★★, **Blisko terminu, Rozpoczęte**, ★★★, ★★, ★, bez gwiazdek —
   9 szczebli; spec 13 „seed 8 szczebli” to zaszłość (Task 6).
3. Grupa materiału = (gatunek, klasa, grubość) po najbliższym terminie w grupie, w grupie termin przed długością
   (wariant A2, Konrad 5.10). K5 sprawdza to na kopii produkcji porównaniem z symulacją (Review Focus 3), nie liczy sam.
4. Bloki po N zamówień — odrzucone (symulacja C/D). W kodzie nie ma ich i K5 nie szuka.
5. Stół K=2, limit odłożeń 10, „Niekompletne” do K (P-2, P-3, P-9; symulacja D p. 5) — wartości seedu migracji K1;
   wyścigi idą na nich (K=2) i na K=1 tam, gdzie trzeba pełnego stołu.
6. Wszystkie stanowiska startują w trybie `stary` (spec 11, P1); przełącza K7. Na podglądzie K5 przełącza **jedno**
   stanowisko (Sklejanie) na `stol` do wyścigów i curl-a i przywraca `stary` na końcu.
7. Sygnał bez ładunku, po commicie, `publish` nie rzuca; siatka 30 s / 5 min (spec 5.4, P-7; ~380 zdarzeń/dzień).
8. Kryterium wyścigów (karta 8.6 i spec 13): zero 1213 bez ponowienia, zero zdublowanych kafli, zero niekompletnych
   kafli-zamówień na stole. Pierwsze 1213 → analiza na Fable 5.1 max (podręcznik 4a, eskalacja p. 3).
9. Pomiar po wdrożeniu (symulacja D p. 7) należy do K7 (P3); K5 tylko sprawdza, że skrypt symulacji działa na kopii
   z gałęzi (wykrywa nowe kolumny) i zostawia K7 polecenie.

## Doprecyzowania (do specu — K5 przenosi sam w Task 6, sekcja 16)

1. **„Migracja ×2” ze spec 13** = dwa przebiegi na **każdej** z dwóch baz: kontener `db` (`woodpower_crm_local`, logistyka
   już wykonana przez K1) i kopia produkcji (`prod_kopia_priorytety`, bez tabel logistyki — runner wykonuje najpierw
   migracje logistyki `2026-09-2x…2026-10-02`, potem `2026-10-05-priorytety-produkcji.sql`; to dokładnie kolejność, w jakiej
   `deploy.sh` wykona je na produkcji, gdy logistyka i P1 wejdą osobnymi wdrożeniami albo jednym).
2. **Kopia produkcji** to osobna baza w kontenerze `db` projektu dewelopera (`CREATE DATABASE prod_kopia_priorytety`), a
   podgląd to osobny kontener `app` z własnym `config/core.json` (`DATABASE_URI` na tę bazę) — jak podglądy
   `logistyka4-podglad` z kroków 4.3–4.4b. Zrzut dostarcza Konrad (`mysqldump --single-transaction`, bez tabel sesji);
   nie leży w repo.
3. **Broker na podglądzie**: kontener `centrifugo/centrifugo:v6` z konfiguracją wzorowaną na `ops/centrifugo/`
   (`http_api.key` = `REALTIME.api_key` podglądu, `client.token.hmac_secret_key` = `REALTIME.token_hmac_secret`, namespace
   `station`), `REALTIME.enabled=true`, `api_url` na kontener, `sse_url` na port podglądu. Klucze losowe, tylko w
   `core.json` podglądu. Produkcyjny broker **nigdy**.
4. **Nazwy trybów wyścigów** (Task 4) są nazwami kanonicznymi do raportu K5, specu 16 i CLAUDE.md; K7 i K8 odwołują się
   do nich przy regresji.
5. **Progi czasów** (Review Focus 6) pochodzą z planów K1 (pytanie 2), K2 (Ryzyka: `GET /kolejka` > 1 s → meldunek),
   K3 (Ryzyka: `desk` > 300 ms → meldunek), K4b (Ryzyka: zakładka > 1 s → meldunek). Przekroczenie nie jest blokadą P1 —
   jest „zaliczone z uwagami” z liczbami i rekomendacją (np. `utrwal()` w wątku w tle jak dopychacz Base.).
6. **`zakoncz-zakoncz-ten-sam-kafel`**: K3 zostawił dwie dopuszczalne odpowiedzi drugiego tabletu (200 idempotentnie po
   statusie albo 409 `nie_na_stole`). K5 zapisuje w raporcie i specu 16, którą daje kod, i sprawdza, że nie ma 500 ani
   wpisu idempotencji przy 409.
7. **Sekcja CLAUDE.md** „Priorytety produkcji” to nowa podsekcja `###` po `### Ważne` (dziś `CLAUDE.md:248-386`), przed
   `## Architecture` (`:387`), w stylu istniejących (prosa z nazwami funkcji i plików), a nie kolejny punkt listy „Ważne”;
   punkt „Logistyka równoległa” (`:276-298`) dostaje jedno zdanie-odesłanie i dopisek o nowych fazach crona.
8. **Lista wdrożenia P1 dla K7** żyje w dwóch miejscach: pełna w raporcie K5 (sekcja „Lista wdrożenia P1”) i skrócona
   w specu 11 (dopisek „(K5) Lista wdrożenia P1”). K7 nie ma jeszcze planu — K5 nie go pisze, tylko daje mu wejście.
9. **`rangi_zbiezne` = punkt stały, nie „utrwal bez zmian od razu” (recenzja planu).** `utrwal()` czyta migawkę zwykłym
   odczytem **przed** blokadami (plan K1, „Współbieżność”), a ZAKOŃCZ, doróbka i hurt zmieniają statusy bez `utrwal()`
   (spec 4.2, 9.3) — więc po przebiegu z ZAKOŃCZ (zbiór aktywnych, tag „Rozpoczęte”) albo z dwoma `utrwal()` na
   przeplecionych migawkach (`szczebel-przystanek`, `utrwal-dostawa`, `gwiazdki-zakoncz`) pierwsze dodatkowe `utrwal()`
   może legalnie coś zmienić (K1: „rangi mogą być o chwilę nieaktualne… cron nadrabia”). Niezmiennik: dodatkowe `utrwal()`
   kończy się `success: true`, **drugie** dodatkowe → `zmienione_zamowienia == 0` i `zmienione_pozycje == 0`, rangi
   aktywnych unikatowe. Liczba przebiegów, w których pierwsze dodatkowe `utrwal()` coś zmieniło, idzie do raportu jako
   miara „nieaktualności do następnego zdarzenia/crona” — informacyjnie, nie jako złamany niezmiennik.
10. **Odłóż blokuje tylko wiersz własnego kafla, limit jest miękki (K3 Doprecyzowania p. 13, zmiana wobec spec 9.2).**
    Odłóż: [pracownicy] → X zamówienia → X pozycje → wiersz stołu **własnego** kafla `FOR UPDATE` (po `unit_key`) → liczba
    odłożonych stanowiska **zwykłym** `SELECT COUNT(*)` (migawka) → UPDATE → INSERT logu. Żadnego `FOR UPDATE` wierszy
    całego stanowiska (wcześniejsza wersja planu K3 tak miała i dawała cykl indeks wtórny ↔ klucz główny z ZAKOŃCZ).
    Dwa jednoczesne Odłóż mogą przekroczyć limit o 1 — tryb `odloz-odloz` to dopuszcza i liczy rozkład.
11. **`FOR SHARE` w zapisie = `LOCK IN SHARE MODE` w `general_log`.** SQLAlchemy 1.4 (`requirements.txt`:
    `SQLAlchemy>=1.4.54,<2.0`) na dialekcie MySQL zamienia `with_for_update(read=True)` na `LOCK IN SHARE MODE`
    (`sqlalchemy/dialects/mysql/base.py`, `for_update_clause`); dla InnoDB 8.x to ta sama blokada S co `FOR SHARE`.
    Oczekiwania z `general_log` (Task 3 Step 3, DoD 5) podają tę postać — inna składnia **nie** jest „inną kolejnością”.
12. **1213 z udanym ponowieniem** jest zgodne z kryterium karty 8.6 („zero 1213 **bez** ponowienia”) w każdym trybie, w którym
    serwer ponawia (`desk`, hurt, `trasy_api._akcja`, `dostawa_api._zapis`, `kolejka.utrwal`, gwiazdki/drabina K2).
    Spodziewane jest tylko w `desk-zakoncz-inne`, `hurt-desk`, `odloz-hurt` i `desk-utrwal`; w innym trybie to nie STOP,
    ale uwaga do werdyktu z wyciągiem `LATEST DETECTED DEADLOCK` i hipotezą (K5 nie zmienia kodu).

## Ugruntowanie w kodzie (stan `claude/logistyka-etap-4` @ `b4b4a54d`, sprzed K1; po K1–K4b szukaj po nazwie)

| Miejsce | Stan obecny (ścieżka:linia) | Co K5 z tym robi |
|---|---|---|
| `CLAUDE.md` | `### Zadania cykliczne (cron)` `:125-168` (cron logistyki `:149`); `### Ważne` `:248-386`; punkt „Logistyka równoległa” `:276-298`; „Trasy logistyki — jeden piszący naraz” `:299-335`; „Deklaracje paczek — jedna naraz” `:336-386`, w nim akapit pisarzy pozycji bez blokady zamówienia `:355-386` z „przeciąganie `update-priority` jednym odczytem, hurtowa i ręczna zmiana priorytetu, przeliczenie `priority_service` na własnej sesji bez autoflushu” (`:368-369`) i „oraz przeciąganie i przeliczenie priorytetów odpowiadają jednym automatycznym ponowieniem” (`:384`); `## Architecture` `:387` | Task 6: nowa `### Priorytety produkcji` między `:386` i `:387`; dopisek w `:276-298`; przepisanie `:368-369` i `:384` (po K2 nie ma przeciągania ani `bulk-action update_priority`, po K4a nie ma `set-priority`; `utrwal()` blokuje zamówienia → pozycje, więc wypada z listy pisarzy bez blokady; dochodzi `order_quantity` czytający stół bez blokady zamówienia — K3 Doprecyzowania); `:149` cron: dwie nowe fazy odpowiedzi |
| spec `2026-10-04-priorytety-produkcji-design.md` (762 linie) | 4.3 `:239-246` („domyślnie 2”); 5.5 `:342-348`; 6.1 `:392-413` (`szczebel` bez `rozpoczete`); 9.1 `:567-586` (`templates/priorytety/`); 9.2 `:588-605`; 9.4 `:621-633` („FOR SHARE pozycje, bez blokad zamówień”); 11 `:672-698`; 13 `:707-734` („seed 8 szczebli”, lista wyścigów `:718-720`); 14 `:736-745`; 15 `:747-762` | Task 6: dopiski „(K5)” w 4.3, 13, 11; nowa `## 16. Doprecyzowania z realizacji` po `:762` z numerowanymi punktami z K1–K4b i wynikami wyścigów |
| `modules/production/routers/mobile_api.py` | `BLEDY_DO_PONOWIENIA` `:122`; `KSZTALT_ODPOWIEDZI_KOLEJKI = 5` `:137` (K3 → 6); `station_orders` `:243-326`; `order_complete` `:426-497` (`zablokuj_zamowienie_pozycji` `:460`, `delivery_method_not_set` `:471`, `mark_order_complete` `:477`); `order_quantity` `:499-543`; `order_reject` `:545-633`; heartbeat/`last_app_version_code` `:1257+` | strony wyścigów ZAKOŃCZ/licznik/doróbka; po K3 szukaj `def desk`, `def postpone`, `def realtime_token`, `KSZTALT_ODPOWIEDZI_STOLU` |
| `modules/production/services/blokady_zamowien.py` | `zablokuj_zamowienia` `:58`, `zablokuj_pozycje` `:71`, `zablokuj_zamowienie` `:92`, `zablokuj_zamowienie_pozycji` `:104`, `kod_mysql` `:123` | odwołania w tabeli wyścigów; `kod_mysql` → warunek ponowienia |
| `modules/production/logistics/services/routes.py` | `KLUCZ_BLOKADY` `:42`, `zablokuj_trasy` `:146-204`, `_zaloz_wiersz_blokady` `:212-229`, `utworz` `:406` (K1: szczebel trasy), `dodaj_przystanki` `:491`, `zmien_kolejnosc` `:601`, `zatwierdz` `:628`, `usun` `:658` | strona B wyścigu `szczebel-przystanek` |
| `modules/production/logistics/routers/trasy_api.py` | `_akcja` `:333-385` (ponowienie 1213 `ponow_po_1213`), `route_create` `:543`, `route_stops_add` `:653`, `route_approve` `:697` | HTTP strony B `szczebel-przystanek`; po K1 `utrwal_po_commicie()` w `_akcja` |
| `modules/production/logistics/routers/dostawa_api.py` | `_zapis` `:125-178` (pętla 1213, `flush` `:160`, `porzuc_zaplanowane` `:169`), `delivery_finish_loading` `:281-302` | strona B wyścigu `utrwal-dostawa` (telefon kierowcy, `tests/dostawa_pomocnicze.py:62-83` wzór nagłówków) |
| `modules/production/logistics/routers/panel_api.py` | `LIMIT_HURTU` `:24`, `_zapis_pod_blokada` `:72-89`, `delivery_method` `:181-246`, `handed_over` `:247-283` | strona A `desk-panel-sposob`; wzór „commit → blokada” do opisu w CLAUDE.md |
| `modules/production/logistics/routers/cron_api.py` | `cron` `:24-80` (fazy: `przenies_osierocone` → commit `:47`, `dostarcz_wydane` → commit `:58`, `przelicz_otwarte` → commit `:63`; K1 dokłada `drabina.uzupelnij()` + `kolejka.utrwal()`) | Task 2 (cron na kopii po migracji), Task 5 (odpowiedź z `szczeble_uzupelnione`, `priorytety_utrwalone`) |
| `cron_auth.py` | `CRON_SECRET_HEADER = 'X-Cron-Secret'` `:37`, `cron_secret_required` `:83` | cron podglądu woła curl z nagłówkiem (sekret podglądu z jego `core.json`) albo `scripts/cron_endpoint.sh` z `KATALOG_APLIKACJI`/`ADRES` ustawionymi na podgląd (`scripts/cron_endpoint.sh:19-20`) |
| `modules/production/routers/api/products_api.py` | `admin_apply_baselinker_changes` `:1247`, `_zablokuj_zamowienia_i_pozycje` `:1325`, `_zapisz_zmiane_statusu` `:1420`, `bulk_action` `:1525` (ponowienie 1213 `:1602`); martwe końcówki `:2538`, `:2895`, `:3260`, `:3380`, `:3499` (usuwa K2), `set_product_priority` `:3681` (usuwa K4a) | strona A `hurt-desk`; grep kontrolny nieobecności w Task 1 |
| `migrations/migration_service.py` | `MIGRATION_PATTERNS` `:32-34` (format `YYYY-MM-DD-nazwa.sql`), `_match` `:60`, `split_statements` `:163`, `run_pending_migrations` `:296`, zapis do `schema_migrations` `:277` | Task 2: kolejność wykonania = kolejność nazw; `flask migrate-status` (`app.py:325`) |
| `app.py` | `RUN_MIGRATIONS` przy starcie `:179-191` (migruje przy każdym `create_app()`!), `migrate` `:309-323` (exit 1 gdy `service.failed`), `migrate-status` `:325`, `DATABASE_URI` → `SQLALCHEMY_DATABASE_URI` `:829`, rejestracja blueprintów `:863-903` (`logistics_panel_bp` `:886-887`; K2 dokłada `priorytety_panel_bp`) | Task 2: start podglądu na kopii **jest** pierwszym przebiegiem migracji; Task 1: grep blueprintu |
| `modules/production/services/realtime_service.py` | `CHANNEL_PRINT_AGENT` `:30`, `is_enabled` `:53`, `sse_url` `:79`, `publish` `:110-180` (nie rzuca), `publish_print_signal` `:183`, `issue_connection_token` `:192-216`; K3 dokłada `channel_station`, `publish_station_signal` | Task 5: sygnały z brokerem |
| `config/core.json.example` | `DATABASE_URI` `:4`, `PRODUCTION_CRON_SECRET` `:29`, `REALTIME` `:90-100` (`enabled`, `api_url` `http://127.0.0.1:8091/api/publish`, `api_key`, `token_hmac_secret`, `token_ttl_seconds`, `sse_url`) | wzór `core.json` podglądu |
| `docker-compose.yml` | `app` (port `${CRM_APP_PORT:-5000}`, wolumen `./:/app`), `db` `mysql:8.4` (`MYSQL_ALLOW_EMPTY_PASSWORD`, `MYSQL_DATABASE: woodpower_crm_local`, port `${CRM_DB_PORT:-3306}`, wolumen `db_data`, healthcheck) | Task 2: druga baza w tym samym kontenerze `db`; podgląd jako osobny kontener `app` |
| `ops/centrifugo/README.md`, `supervisor-centrifugo.conf` | opis produkcyjnego brokera (`127.0.0.1:8091`, klucze `http_api.key` ↔ `REALTIME.api_key`, `client.token.hmac_secret_key` ↔ `token_hmac_secret`, test publikacji curlem); `ops/centrifugo/` ma `README.md`, `config.example.json` (`http_server` `127.0.0.1:8091`, `uni_sse.enabled`, namespace'y `print` i `station`), `nginx-realtime.conf`, `supervisor-centrifugo.conf` — `config.example.json` to wzór brokera podglądu (z adresem `0.0.0.0`, Task 3 Step 1) | Task 3: broker lokalny na podglądzie |
| `scripts/symulacja_priorytetow.py` | docstring `:1-60` (tylko SELECT, nie importuje aplikacji, `--db-url`, `--blisko`, `--dzis`, `--drabina`, `--gwiazdki`), opcje `:760-770` | Task 2: porównanie z `GET /kolejka` na kopii; Task 7: polecenie pomiaru dla K7 |
| `tests/blokady_pomocnicze.py` | `Zapytania` `:25`, `klauzula_blokady` `:51`, `indeks_blokady_tras` `:63`, `blokada_zamowien` `:81`, `blokada_pozycji` `:86`, `zapis` `:91`, `id_zapisow_pozycji` `:103`, `dodaj_pozycje_za_plecami` `:119`; K1/K3 dokładają predykaty | Task 1: regresja testów kolejności (lista w Step 4) |
| `tests/dostawa_pomocnicze.py` | `zamowienie_z_paczkami` `:29`, `trasa` `:43`, `zaladuj_wprost` `:55`, `telefon_kierowcy` `:62`, `naglowki` `:71` | wzór stanu wyjściowego `utrwal-dostawa` (skrypt poza repo robi to samo SQL-em/HTTP na podglądzie) |
| `tests/test_dostawa_ponowienie_1213.py` | `_blad_mysql` `:28`, `_scenariusz` `:32` | wzór liczenia prób; K5 **nie** wstrzykuje 1213 — mierzy prawdziwe |
| `tests/test_priorytety_kolejnosc_zapisow.py` | docstring `:1-13` (pisarze bez blokady, kolejność UPDATE-ów); K1 przepisuje na `kolejka.utrwal`, K2 usuwa przeciąganie | Task 1: regresja |
| `tests/test_migration_service.py` | `test_wszystkie_pliki_w_katalogu_migracji_sa_rozpoznawane` `:130`, `test_migracja_trakowni_jest_idempotentna` `:148` | Task 2 |

**Czego w kodzie nie ma (żeby nikt nie szukał):** na `b4b4a54d` nie ma pakietu `priorytety`, testów `tests/test_priorytety_*`
poza `kolejnosc_zapisow`, raportów K1–K4b (powstają w krokach), skryptów wyścigów w repo (`_podglad_wspolne.py`,
`_zamowienie_najpierw_wyscigi.py`, `_dostawa_wyscigi.py` leżą w katalogu podglądów Konrada poza repo — K5 kopiuje je stamtąd
wg wskazań centrali albo pisze własny od zera wg opisu w Task 3), kontenera Centrifugo w `docker-compose.yml` (broker tylko na
produkcji przez supervisora), pliku `MIGRATION_PLAN.md` (CLAUDE.md odsyła do niego w sekcji „Serwer produkcyjny”, pliku na
gałęzi nie ma — do „Poza zakresem” raportu), planu K7 (K5 daje mu wejście). `threading.Barrier` nie występuje w `tests/`
ani `scripts/`.

## Środowisko

- Repo: `cd <repo> && docker compose up -d`; `PYTEST <ścieżki>` = `docker compose exec app pytest <ścieżki> -q -p no:cacheprovider`.
- Kontener `db`: `docker compose exec db mysql -uroot <baza>` (puste hasło roota w compose; dane podglądu z jego `core.json`,
  nie do raportu). Druga baza: `prod_kopia_priorytety`.
- Podgląd (wg centrali, S-3): osobny kontener `app` z katalogiem kodu poza repo (`git archive HEAD | tar -x -C <katalog>`),
  własny `config/core.json` (`DATABASE_URI` → `prod_kopia_priorytety`, `REALTIME` → broker lokalny, `PRODUCTION_CRON_SECRET`
  losowy), port z karty. **5003 i 5005 — nie ruszać** (poprzednie programy). Dwie sesje MySQL do wyścigów: skrypt (dwa
  wątki) + `mysql` CLI na `SHOW ENGINE INNODB STATUS` i licznik `information_schema.INNODB_METRICS` `lock_deadlocks`
  (sprawdź `STATUS='enabled'`; zmiennej `Innodb_deadlocks` MySQL — w odróżnieniu od MariaDB/Percona — nie ma, więc
  `SHOW GLOBAL STATUS` może zwrócić pusto). Na czas serii `SET GLOBAL innodb_print_all_deadlocks=ON` (każde zakleszczenie
  w logu błędów kontenera `db`, nie tylko ostatnie z `INNODB STATUS`; po seriach `OFF`, log bez danych klientów do raportu).
- Broker: `docker run -d --name centrifugo-podglad -p <port>:8000 -v <config.json>:/centrifugo/config.json centrifugo/centrifugo:v6 centrifugo -c config.json`
  w sieci compose podglądu (albo `host.docker.internal`). Konfiguracja wg `ops/centrifugo/README.md`: `http_api.key`,
  `client.token.hmac_secret_key`, namespace `station` (jak produkcja: „kanały `station:*` są przygotowane pod etap 2”).
- Katalog wyników poza repo (wskazany przez centralę): skrypty `_podglad_wspolne.py`, `_priorytety_wyscigi.py`, wyniki
  `_wyscigi_k5.jsonl`, zrzuty ekranu, `innodb-status-*.txt` (bez danych klientów), notatka robocza `k5-notatki.md`.

## Mapa plików

| Plik | Task | Rola |
|---|---|---|
| `modules/production/priorytety/**`, `tests/test_priorytety_*.py` (K1–K4b) | 1 | tylko naprawa regresji w zakresie (0–n commitów `fix(priorytety)`) |
| (poza repo) `<katalog>/kod/_podglad_wspolne.py`, `_priorytety_wyscigi.py`, `_wyscigi_k5.jsonl`, `innodb-status-*.txt` | 3, 4 | skrypt wyścigów, wyniki |
| (poza repo) `<katalog>/centrifugo/config.json`, `core.json` podglądu | 3 | broker i konfiguracja podglądu |
| `CLAUDE.md` (`:149`, `:276-298`, `:368-369`, `:384`, nowa sekcja po `:386`) | 6 | „Priorytety produkcji”, „Logistyka równoległa”, akapit pisarzy |
| `docs/superpowers/specs/2026-10-04-priorytety-produkcji-design.md` (4.3, 11, 13, nowa 16) | 6 | doprecyzowania z realizacji, lista wdrożenia P1 (skrót), wyniki wyścigów |
| `docs/superpowers/plans/raporty/2026-10-05-priorytety-krok-K5-raport.md` (nowy) | 7 | raport, werdykt, lista wdrożenia P1 dla K7 |
| `docs/superpowers/plans/2026-10-05-priorytety-krok-K5-przeglad-p1.md` | 7 | odhaczone checkboxy (commit z raportem) |

Usunięte: nic. Migracje: żadnych nowych.

---

### Task 1: Punkt wyjścia, weryfikacja interfejsów P1, pełny pakiet, naprawa regresji w zakresie

**Files:**
- Read: raporty `docs/superpowers/plans/raporty/2026-10-05-priorytety-krok-K{1,2,3,4a,4b}-raport.md`
- Modify (tylko przy regresji): `modules/production/priorytety/**`, `tests/test_priorytety_*.py`

**Interfaces (weryfikowane, nie produkowane — nazwy ze specu 9.1/9.2/6/8 i planów K1–K4b):**

| Nazwa (spec) | Gdzie | Czego K5 oczekuje |
|---|---|---|
| `kolejka.policz(migawka)`, `kolejka.kandydaci_stanowiska(S, pozycje, statusy_zamowien, szczebel_rozpoczete=None)`, `kolejka.utrwal(zrodlo=None, user_id=None) -> dict`, `kolejka.utrwal_po_commicie`, `zaplanuj_po_commicie`/`porzuc_zaplanowane`/`wykonaj_zaplanowane`, `kolejka.nowa_sesja` | `priorytety/services/kolejka.py` (K1) | `utrwal` nigdy nie rzuca, nie dotyka `db.session`, raport z `success`, `zmienione_zamowienia`, `zmienione_pozycje` |
| `drabina.szczeble(aktualny=False)`, `wszystkie_do_zapisu`, `zapewnij_szczebel_trasy(route, user_id=None)`, `usun_szczebel_trasy`, `przesun(rung_id, pozycja, user_id=None)`, `uzupelnij(user_id=None)`, `pozycja_tagu`, `BladDrabiny` | `drabina.py` (K1) | zapisy pod `routes.zablokuj_trasy()` |
| `gwiazdki.ustaw(order_ids, gwiazdki, user_id=None, teraz=None) -> dict`, `BladGwiazdek` | `gwiazdki.py` (K1) | `zablokuj_zamowienia` rosnąco, bez commita, bez blokady tras |
| `ustawienia.tryb(S)`, `miejsca(S)`, `jednostka(S)`, `limit(S)`, `prog_blisko()`, `min_app_version()`, `typ_dni_terminu()`, `waliduj`, `zapisz`, `odczyt_panelu` | `ustawienia.py` (K1/K2/K4b) | wynik K2 Task 5 o pamięci podręcznej 60 min — zanotować (zielony czy `xfail`) |
| `stol.zablokuj_stanowisko(S)`, `dopelnij(S) -> Dopelnienie`, `odloz(...)`, `zdejmij_kafel`, `zdejmij_nieaktualne(order)`, `bramka_zakoncz(item, S, device)`, `kafle(S, do_zapisu=False)`, `kontekst_priorytetu(items)`, `BladStolu` | `stol.py` (K3) | `grep "db.session.commit"` w `stol.py`, `sygnaly.py` → pusto |
| `sygnaly.zaplanuj(*kody)`, `wyslij()`, `nastepne_stanowisko(item)`, `zaplanuj_po_zakonczeniu(item, S)`; `realtime_service.channel_station`, `publish_station_signal(kod)` | `sygnaly.py`, `realtime_service.py` (K3) | wysyłka po commicie w `with_idempotency` |
| `widok.drabina_panelu`, `kolejka_zamowien`, `kolejka_stanowiska(kod, limit)`, `priorytet_zamowienia`, `stoly_panelu(stanowiska=None)`, `odlozenia_panelu`, `liczba_pilnych_zamowien`, `priorytet_zamowien`, `szczebel_json` | `widok.py` (K2/K3/K4b) | bez commitów i blokad |
| HTTP panel: `GET /drabina`, `PUT /drabina/kolejnosc`, `PUT /zamowienia/gwiazdki`, `POST /przelicz`, `GET /kolejka`, `GET /zamowienia/<id>/priorytet`, `GET/PUT /ustawienia`, `GET /stoly`, `GET /odlozenia` (10) | `priorytety/routers/panel_api.py`, `app.py` | `test_zestaw_koncowek` → 10 |
| HTTP mobilne: `GET /api/mobile/stations/<kod>/desk`, `POST /api/mobile/orders/<id>/postpone`, `GET /api/mobile/realtime-token`; `KSZTALT_ODPOWIEDZI_KOLEJKI == 6`, `KSZTALT_ODPOWIEDZI_STOLU` | `routers/mobile_api.py` (K3) | `serialize_order` ma `priorytet` |
| Modele `PriorityRung`, `PriorityLog`, `StationDesk`; kolumny `ProductionOrder.priority_stars/_set_at/_set_by/priority_rank/priority_rung` | `priorytety/models.py`, `models.py` (K1) | spec 8.1–8.4 |
| Klucze `prod_config`: `priorytety_tryb_<S>`, `priorytety_stol_<S>`, `priorytety_jednostka_<S>`, `priorytety_limit_odlozen_<S>`, `priorytety_blokada_<S>`, `priorytety_blisko_terminu_dni`, `priorytety_min_app_version_code`, `DEADLINE_DAY_TYPE` | `stale.py`, migracja (K1) | 38 wierszy seedu |
| UI: `priorytety.js/.css`, `window.Priorytety`, brak `products-dragdrop.js`, brak `set-priority` (K4a); karty „Terminy”/„Stół stanowisk”, `_priorytet_plakietki.html`, monitory ze stołem (K4b) | szablony, statyka | testy strukturalne K4a/K4b zielone |

- [x] **Step 0: Gałąź i warunek startu**
  1. `git log -1 --oneline` → hash z karty centrali; inny → STOP, pytanie do centrali. `git log --oneline origin/claude/logistyka-etap-4..HEAD | wc -l`
     ≈ 7 (K1) + 7 (K2) + 6 (K3) + 7 (K4a) + 8 (K4b) = 35 (± poprawki) — liczba do raportu. `git status` czysty.
  2. Potwierdź, że K4a **i** K4b są scalone (oba raporty istnieją; `ls modules/production/priorytety/static/js/priorytety.js
     modules/production/templates/components/_priorytet_plakietki.html`). Brak któregoś → STOP.
  3. `git fetch origin && git log --oneline HEAD..origin/claude/logistyka-etap-4 HEAD..origin/main | head` — jeśli
     logistyka albo `main` poszły do przodu od ostatniego scalenia, STOP: centrala zleca scalenie przed K5 (podręcznik 2 p. 2).
- [x] **Step 1: Raporty K1–K4b** — przeczytaj w całości; z każdego wypisz do `k5-notatki.md`: „Odstępstwa”, „Rozstrzygnięcia”,
  „Pytania do Konrada” (otwarte), „Co następny krok musi wiedzieć → K5”, oraz liczby `passed/skipped` z ostatniego pełnego
  pakietu (punkt odniesienia). Z raportu K3 weź listę wyścigów i porównaj z Task 4 tego planu — czego brakuje, dopisz do
  Task 4 jako tryb dodatkowy (zapisz w „Odstępstwach”). Z raportu K2 i K4b: stan `test_ustawienia_czytane_bez_pamieci_podrecznej_procesu`
  (zielony czy `xfail`) — jeśli `xfail`, to **uwaga do werdyktu** (tryb `stol` i limit docierają do innych workerów gunicorna
  po godzinie; wycofanie P3 „bez zmiany kodu” opóźnione), z rekomendacją karty naprawczej przed K7 część 2.
- [x] **Step 2: Grep interfejsów** (wynik do notatki, ścieżka:linia dla każdej nazwy z tabeli „Interfaces”):
  ```bash
  grep -n "^def \|^class " modules/production/priorytety/services/*.py modules/production/priorytety/models.py modules/production/priorytety/stale.py
  grep -n "route(" modules/production/priorytety/routers/panel_api.py
  grep -n "def desk\|def postpone\|def realtime_token\|KSZTALT_ODPOWIEDZI_KOLEJKI =\|KSZTALT_ODPOWIEDZI_STOLU =" modules/production/routers/mobile_api.py
  grep -rn "db.session.commit" modules/production/priorytety/services/ ; grep -n "db.session.commit" modules/production/routers/mobile_api.py
  grep -rn "zdejmij_nieaktualne\|utrwal_po_commicie\|wykonaj_zaplanowane\|publish_station_signal\|sygnaly\." modules --include=*.py | grep -v "priorytety/services" 
  grep -rn --include=*.py --include=*.js --include=*.html -E "update-priority|set-priority|set_product_priority|products-dragdrop|ProductsDragDrop|PRIORITY_RECALC_INTERVAL_HOURS|PRIORITY_ALGORITHM_VERSION|_PRIORITY_SORT|priority_rank <=" modules app.py
  ```
  Oczekiwane: commity serwisów → pusto; w `mobile_api.py` commit tylko w `desk` (+ dwa sprzed P1:
  `mobile_print_label_by_id` i `device_heartbeat` — na `b4b4a54d` `:952` i `:1285`; `register`/`apk` commitów nie mają);
  `zdejmij_nieaktualne` u pięciu pisarzy (ZAKOŃCZ, doróbka, Base., hurt, cron — K3 DoD 4; licznik sztuk ma tylko bramkę,
  a ZAKOŃCZ odłożonego idzie przez `zdejmij_kafel` z logiem `odlozenie_zamkniete`); ostatni grep (zakres `modules app.py`)
  → wyłącznie `priority_rank <=` w `modules/production/__init__.py` (`get_high_priority_items_count`) i
  `routers/admin_routers.py` (`high_priority_products`) — znane, poza zakresem K4b, do K8; żadnych `update-priority`,
  `set-priority`, `products-dragdrop`, `PRIORITY_RECALC_INTERVAL_HOURS`, `PRIORITY_ALGORITHM_VERSION`, `_PRIORITY_SORT`
  (K2/K4a/K4b DoD). Inaczej → regresja do Step 4 albo „Odstępstwa”.
- [x] **Step 3: Pełny pakiet (punkt wyjścia K5)**
  ```bash
  docker compose exec app pytest tests/ -q -p no:cacheprovider          # 0 failed; passed/skipped do raportu
  docker compose exec app bash -c "cd integrations/blog_seo && python -m pytest -q -p no:cacheprovider"
  ```
  Składnia 3.9 dla wszystkich `.py` zmienionych od `b4b4a54d` (cały P1, nie tylko ostatni krok):
  `docker compose exec app python -c "import ast,sys; [ast.parse(open(p,encoding='utf-8').read(), p, feature_version=(3,9)) for p in sys.argv[1:]]; print('OK')" $(git diff --name-only --diff-filter=d b4b4a54d..HEAD -- '*.py')`
  (lista plików z `git` na **hoście** — obraz `docker/python/Dockerfile` nie ma `git`; `--diff-filter=d` pomija pliki usunięte)
  oraz grep `' | None'`/`\w+ \| \w+` w adnotacjach plików bez `from __future__ import annotations` → pusto.
- [x] **Step 4: Regresja w zakresie priorytetów (tylko gdy Step 2/3 coś znalazły)** — dla każdej usterki: test, który pada
  (istniejący albo nowy w `tests/test_priorytety_*.py`) → poprawka w pakiecie `priorytety` albo przepięciu z K1–K4b → test
  zielony → regresja celowana (pliki `tests/test_priorytety_*.py`, `tests/test_blokady_*.py`, `tests/test_produkty_masowa_zmiana_statusu.py`,
  `tests/test_dostawa_api.py`, `tests/test_logistyka_cron.py`, `tests/test_mobile_*.py`) → commit
  `fix(priorytety): <co>` z opisem przyczyny. Przyczyna poza pakietem (np. test logistyki pada na zmianie `with_idempotency`,
  której nie da się naprawić bez zmiany kontraktu) → **STOP**, meldunek (karta naprawcza do kroku źródłowego). Po poprawkach
  pełny pakiet raz jeszcze (Step 3). Bez usterek — Task 1 bez commita; zapisz „Task 1: bez zmian w kodzie”.

---

### Task 2: Migracja ×2 na kontenerze `db` i na kopii produkcji; algorytm kontra symulacja

**Files:**
- Read: `migrations/2026-10-05-priorytety-produkcji.sql` (K1), `migrations/migration_service.py:32-34, 296`, `app.py:179-191, 309-323`
- Create (poza repo): `<katalog>/kopia/dump-produkcji.sql.gz` (od Konrada), `<katalog>/kopia/core.json` podglądu, `k5-notatki.md`

**Interfaces:** Consumes: `flask migrate`, `flask migrate-status` (`app.py:309-335`), `scripts/symulacja_priorytetow.py --db-url … --blisko 3 --dzis … --json …`
(`:760-770`), `GET /production/api/priorytety/kolejka` (K2), `POST /production/api/logistics/cron` z `X-Cron-Secret` (K1 fazy
`szczeble_uzupelnione`, `priorytety_utrwalone`). Produces: dwa protokoły migracji (po jednym na bazę) i porównanie kolejek
w raporcie.

- [x] **Step 1: Kontener `db` (baza z logistyką już wykonaną przez K1)**
  ```bash
  docker compose exec app flask migrate-status           # 2026-10-05-priorytety-produkcji.sql: wykonana (K1)
  docker compose exec app flask migrate && docker compose exec app flask migrate    # 2× „Wykonano 0 migracji.”
  docker compose exec db mysql -uroot woodpower_crm_local -e "
    SELECT kind, stars, tag, position FROM prod_priority_rungs WHERE kind<>'route' ORDER BY position;
    SELECT COUNT(*) FROM prod_config WHERE config_key LIKE 'priorytety_%' OR config_key='DEADLINE_DAY_TYPE';
    SHOW COLUMNS FROM prod_orders LIKE 'priority%';
    SHOW CREATE TABLE prod_priority_rungs\G"
  ```
  Oczekiwane: 9 szczebli w kolejności 3.1 (`blisko_terminu` 4, `rozpoczete` 5), 38 wierszy, 5 kolumn, FK
  `fk_prod_priority_rungs_route … ON DELETE CASCADE`. K2–K4b nie dodały migracji — `ls migrations/ | tail -3` to potwierdza
  (inaczej: odstępstwo, protokół także dla nich).
- [x] **Step 2: Kopia produkcji — wczytanie (bez kodu gałęzi)**
  Zrzut od Konrada (`mysqldump --single-transaction --routines=0 --triggers=0`, bez tabel sesji; **bez danych w repo**):
  ```bash
  docker compose exec db mysql -uroot -e "DROP DATABASE IF EXISTS prod_kopia_priorytety; CREATE DATABASE prod_kopia_priorytety CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
  gunzip -c <katalog>/kopia/dump-produkcji.sql.gz | docker compose exec -T db mysql -uroot prod_kopia_priorytety
  docker compose exec db mysql -uroot prod_kopia_priorytety -e "
    SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME IN ('prod_routes','prod_route_stops','prod_priority_rungs','prod_station_desk');
    SELECT version FROM schema_migrations ORDER BY version DESC LIMIT 5;"
  ```
  Oczekiwane: **0** z czterech tabel (kopia sprzed logistyki etapu 3 — jak w symulacji 4.10: „baza produkcyjna nie ma jeszcze
  tabel logistyki”), ostatnia migracja sprzed `2026-09-2x-logistyka-*`. Jeśli kopia ma już logistykę (Konrad wdrożył etapy
  1–4 przed K5) — zapisz to i traktuj jak Step 1 (wariant „po logistyce”); wariant „bez prod_routes” wtedy odpada i jest
  wymieniony w „Odstępstwach” jako niesprawdzony na danych (pokryty tylko kolejnością nazw w runnerze).
- [x] **Step 3: Kopia produkcji — przebieg 1 i 2**
  Podgląd (kontener `app` poza repo) z `core.json` → `DATABASE_URI=mysql+pymysql://root@db/prod_kopia_priorytety`
  (albo przez port hosta), reszta `core.json` wg Global Constraints („odcięty od świata”, `RUN_DB_SETUP: false`). Kontener
  podglądu z obrazu aplikacji compose, w sieci compose (żeby `db` się rozwiązywało), z `FLASK_APP=app.py` w środowisku
  (inaczej `docker exec <podglad> flask migrate` nie znajdzie aplikacji). **Pierwszy przebieg to start podglądu**
  (`app.py:179` `RUN_MIGRATIONS`) — równoważny `flask migrate` z `deploy.sh` (ten sam `MigrationService.run_pending_migrations`).
  Zapisz `docker logs --since 5m <podglad>`: kolejność wykonania — wszystkie migracje gałęzi nieobecne w kopii, po nazwach:
  logistyka `2026-09-25-logistyka-sposob-dostawy.sql` … `2026-10-02-logistyka-niedostarczone-na-trasie.sql` przemieszana
  z `2026-09-30-druk-*`, `2026-10-01-analiza-planowana-trasa.sql`, `2026-10-02-raport-planowana-trasa.sql`, na końcu
  `2026-10-05-priorytety-produkcji.sql` — **bez błędów**. Potem:
  ```bash
  docker exec <podglad> flask migrate && docker exec <podglad> flask migrate-status      # „Wykonano 0 migracji.”
  docker compose exec db mysql -uroot prod_kopia_priorytety -e "<te same SELECT-y co w Step 1> ;
    SELECT COUNT(*) AS aktywne FROM prod_orders o WHERE EXISTS (SELECT 1 FROM prod_products p WHERE p.order_id=o.id AND p.current_status IN ('czeka_na_wyciecie','czeka_na_skladanie','czeka_na_sklejanie','czeka_na_formatowanie','czeka_na_krawedzie','czeka_na_lakiernie','czeka_na_pakowanie'));
    SELECT COUNT(*) FROM prod_orders WHERE priority_rank IS NOT NULL;"
  ```
  Oczekiwane: 9 szczebli, 38 wierszy, 5 kolumn, FK do istniejącej teraz `prod_routes`; `priority_rank` zamówień **NULL**
  (migracja nie liczy rang — robi to cron, spec 11). Czas obu przebiegów do raportu. Błąd migracji → STOP (Global Constraints).
- [x] **Step 4: Pierwszy cron na kopii (jak „po wdrożeniu P1 uruchom raz ręcznie”)**
  `curl -s -X POST -H "X-Cron-Secret: <sekret podglądu>" http://127.0.0.1:<port>/production/api/logistics/cron` (albo
  `KATALOG_APLIKACJI=<katalog kodu podglądu> ADRES=http://127.0.0.1:<port> scripts/cron_endpoint.sh POST /production/api/logistics/cron`
  — **zawsze z `ADRES`**: domyślny adres skryptu to produkcja).
  Oczekiwane: 200, `szczeble_uzupelnione: 0` (kopia bez tras), `priorytety_utrwalone.success: true`, `zamowien` ≈ `aktywne`
  z Step 3, `zmienione_zamowienia` = `aktywne`, czas `duration_seconds` do raportu (próg K1 pytanie 2: „setki ms”). Drugi cron
  → `zmienione_zamowienia: 0`, `zmienione_pozycje: 0` (idempotencja). SQL: `SELECT COUNT(*), COUNT(DISTINCT priority_rank)
  FROM prod_orders WHERE priority_rank IS NOT NULL` → równe (rangi unikatowe); `SELECT COUNT(*) FROM prod_products WHERE
  priority_manual_override=1 AND current_status IN (…STATUSY_PRODUKCJI…)` → 0 (spec 8.5 `utrwal` zeruje).
- [x] **Step 5: Algorytm kontra symulacja (Review Focus 3)**
  ```bash
  docker exec <podglad> python scripts/symulacja_priorytetow.py --db-url "<URI kopii>" --blisko 3 --k 2 --dzis <dzisiejsza data> --top 300 --out /tmp/k5-sym.md --json /tmp/k5-sym.json
  curl -s -b <cookie zalogowanej sesji podglądu> http://127.0.0.1:<port>/production/api/priorytety/kolejka > /tmp/k5-kolejka.json
  ```
  JSON symulacji ma kształt `{"symulacja": {"stanowiska": {"<kod>": {"kolejka": [...], "kolejka_pelna": [... ≤ 200]}}, ...},
  "historia": ...}` (`uruchom`/`symuluj`, `:398-441`, `:774-787`) — **nie ma** w nim globalnej kolejki zamówień, a wiersze
  identyfikują numer zamówienia (`zamowienie`) i `short_product_id` (`pozycja`), nie `order_id`. Porównania:
  (a) **Sklejanie:** `GET /kolejka?stanowisko=gluing&limit=300` → `kafle[].short_id` kontra
  `symulacja.stanowiska.gluing.kolejka[].pozycja` (z `--top 300`; `kolejka_pelna` jest ucięta do 200);
  (b) **Formatowanie/Pakowanie:** `GET /kolejka?stanowisko=formatting` → `kafle[].numer` + `niekompletne[].numer` kontra
  `symulacja.stanowiska.formatting.kolejka[].zamowienie` (kompletne i niekompletne w jednej kolejności `nowa`);
  (c) **ranga zamówień:** `GET /kolejka` → `zamowienia[].numer` kontra lista policzona małym skryptem poza repo, który
  importuje `scripts/symulacja_priorytetow.py` jako moduł (nie importuje aplikacji) i sortuje `dane['aktywne']` po
  `_klucz_zamowienia` (`wczytaj` → `_przygotuj(dane, {}, 3)` → `_drabina(dane, DRABINA_DOMYSLNA)`). `?stanowisko=` czyta
  szczebel z kolumn `priority_rung` (K2 Doprecyzowania p. 13), więc porównanie dopiero **po** cronie ze Step 4, przy
  pustych stołach (przed Task 3). Oczekiwane: identyczna kolejność
  (kopia bez tras i gwiazdek — obie strony liczą ten sam klucz). Różnice → sprawdź `--dzis` (migawka vs „dziś” serwera) i
  próg; prawdziwa rozbieżność algorytmu = **regresja K1** (test tabelą w `tests/test_priorytety_kolejka.py` → STOP, karta
  naprawcza K1; K5 nie poprawia algorytmu). Liczby (zamówień, pozycji, zgodnych miejsc, pierwsze 10 kolejki Sklejania bez
  danych klientów) do raportu.
- [x] **Step 6: Notatka** `k5-notatki.md`: oba protokoły, czasy, wynik porównania. Bez commita (Task 2 nie zmienia repo).

---

### Task 3: Podgląd do wyścigów — broker, tryb `stol` na Sklejaniu, skrypt wyścigów, kolejność zapytań (`general_log`)

**Files:**
- Create (poza repo): `<katalog>/centrifugo/config.json`, `<katalog>/kod/_podglad_wspolne.py`, `<katalog>/kod/_priorytety_wyscigi.py`
- Read: `ops/centrifugo/README.md`, `config/core.json.example:90-100`, `modules/production/services/realtime_service.py` (K3: `publish_station_signal`), `modules/production/priorytety/services/stol.py` (K3), `modules/production/routers/mobile_api.py` (K3: `desk`, `postpone`)

**Interfaces:**
- Produces (skrypt, poza repo): `wyscig(zad_a, zad_b, rozjazd_ms=0) -> (odp_a, odp_b)` (dwa wątki, `threading.Barrier(2)`,
  każdy z własnym `requests.Session` na podgląd **albo** własnym `app.test_client()` w jednym procesie z `create_app()` na
  `core.json` podglądu — jak 4.4a; drugi wariant daje dostęp do `db.session` do niezmienników, pierwszy jest bliższy
  produkcji; wybierz jeden i zapisz); `token(urzadzenie)`, `klient_admina()` (sesja panelu), `zakleszczenia_serwera()`
  (`SELECT COUNT FROM information_schema.INNODB_METRICS WHERE NAME='lock_deadlocks'`), `log_od(znacznik)` (wpisy
  `1213|Deadlock|1205|Lock wait` z logu podglądu), `stan(order_id)`; **niezmienniki** liczone świeżym odczytem po każdym
  przebiegu:
  ```python
  def stol_bez_duplikatow(S):     # SELECT station_code, unit_key, COUNT(*) FROM prod_station_desk GROUP BY 1,2 HAVING COUNT(*)>1 → 0 wierszy
  def stol_bez_nieaktualnych(S):  # każdy wiersz p:<id> → pozycja w STATION_PENDING_STATUS[S]; każdy o:<id> → zamówienie ma pozycję w statusie S
  def stol_bez_niekompletnych(S): # dla o:<id> z postponed_at IS NULL: żadna niezanulowana/niewstrzymana pozycja zamówienia w statusie o etapie < etap S
  def rangi_zbiezne():            # dodatkowe kolejka.utrwal() → success; DRUGIE dodatkowe → zmienione_zamowienia == 0 i zmienione_pozycje == 0 (punkt stały);
                                  # rangi aktywnych unikatowe; zmiany z PIERWSZEGO dodatkowego tylko do statystyki (Doprecyzowania p. 9)
  def kafel_zamkniety_zniknal(item_id, S):  # po ZAKOŃCZ brak wiersza p:<item_id> (i o:<order_id>, gdy to była ostatnia pozycja)
  ```
  Każdy tryb: `przygotuj() -> kontekst` (surowy SQL na zamówieniach z puli podglądu + `desk`, jak `w.reset` w 4.4a),
  `strona_a(k)`, `strona_b(k)`, `sprawdz(k) -> (ok, opis)`, `posprzataj(k)`.
- Consumes: urządzenia podglądu (`PODGLAD-SKLEJANIE-1`, `PODGLAD-SKLEJANIE-2` ze stanowiskiem `gluing`,
  `PODGLAD-FORMATOWANIE`, `PODGLAD-PAKOWANIE`, `PODGLAD-DOSTAWA`), kierowca `is_driver`, sesja admina panelu,
  `PRODUCTION_CRON_SECRET` podglądu.

- [x] **Step 1: Broker** — `config.json` z `ops/centrifugo/config.example.json` (klucze `openssl rand -hex 32`, tylko w plikach
  podglądu) z **jedną zmianą**: `http_server.address` `127.0.0.1` → `0.0.0.0` (w kontenerze `127.0.0.1` to sam kontener —
  port wystawiony przez `-p` byłby głuchy); port w `-p <port hosta>:8091` zgodny z `http_server.port`. `api_url` w `core.json`
  podglądu wskazuje broker **z sieci kontenerów** (`http://centrifugo-podglad:8091/api/publish` w tej samej sieci albo
  `http://host.docker.internal:<port hosta>/api/publish`), a `sse_url` — z perspektywy klienta na hoście
  (`http://127.0.0.1:<port hosta>/connection/uni_sse`). Uruchomienie kontenera, test publikacji curlem z nagłówkiem
  `X-API-Key` jak w README (`{"result":{}}`; bez klucza 401). W `core.json` podglądu
  `REALTIME.enabled=true`, `api_url`, `api_key`, `token_hmac_secret`, `sse_url` → `http://127.0.0.1:<port brokera>/connection/uni_sse`.
  Restart podglądu. `curl -s -H "Authorization: Bearer <token urządzenia>" http://127.0.0.1:<port>/api/mobile/realtime-token`
  → 200 `{enabled: true, channels: ["station:gluing"], …}`; token dekoduje się z sekretem podglądu.
- [x] **Step 2: Tryb `stol` na Sklejaniu** przez `PUT /production/api/priorytety/ustawienia` (admin podglądu):
  `{"stanowiska": {"gluing": {"tryb": "stol", "miejsca": 2, "limit_odlozen": 2}}}` (limit 2 do trybów Odłóż). Odpowiedź 200,
  `zmienione` 2 klucze. `GET /ustawienia` oddaje nowe wartości. Jeśli raport K2 zgłosił pamięć podręczną 60 min
  (`xfail`): zrestartuj podgląd po zapisie i zanotuj (uwaga do werdyktu, Task 1 Step 1).
- [x] **Step 3: Kolejność zapytań z `general_log` (K3 Task 6 Step 4 — zawsze: tani, a DoD 5 wymaga wyciągu z tego kroku;
  wynik K3, jeśli był, to punkt odniesienia)**: `SET GLOBAL general_log=1, log_output='TABLE'`; jedno `GET desk` Sklejania (pusty stół, ≥ 2 kandydaci) i jedno
  ZAKOŃCZ kafla; `SELECT argument FROM mysql.general_log WHERE thread_id=<id> ORDER BY event_time`; `SET GLOBAL general_log=0;
  TRUNCATE mysql.general_log`. Oczekiwane (K3 Review Focus 1, DoD 3; `LOCK IN SHARE MODE` = postać `FOR SHARE` z SQLAlchemy
  1.4, Doprecyzowania p. 11): `desk`: `COMMIT` → `SELECT … prod_config … 'priorytety_blokada_gluing' … FOR UPDATE` → zwykły
  `SELECT` id zamówień z pozycją w statusie stanowiska (bez klauzuli; K3 Doprecyzowania p. 1) → `SELECT … prod_orders WHERE id
  IN (…) ORDER BY id … LOCK IN SHARE MODE` → `SELECT … prod_products WHERE order_id IN (…) ORDER BY order_id, id … LOCK IN
  SHARE MODE` → `SELECT … prod_station_desk …` (bez klauzuli) →
  `INSERT INTO prod_station_desk` → `COMMIT`; ZAKOŃCZ: `prod_orders … FOR UPDATE` → `prod_products … FOR UPDATE` → `UPDATE
  prod_products` → `SELECT … prod_station_desk … FOR UPDATE` → `DELETE FROM prod_station_desk` → `COMMIT`. **Inna kolejność →
  STOP** (K3 Ryzyka), meldunek z wyciągiem logu (bez danych klientów).
- [x] **Step 4: Skrypt** `_priorytety_wyscigi.py` z trybami z Task 4 (docstring trybu = wiersz tabeli), `--tryb`, `--serie`
  `20b,12r40,30r15` (b = czysta bariera, rNN = rozjazd startu 0–NN ms), `--jsonl`. Próba na sucho każdego trybu ×1 (bez
  statystyk) — wszystkie `sprawdz()` zielone, pula zamówień wraca do stanu wyjściowego (`posprzataj`). Agent druku wyłączony;
  po trybach z Pakowaniem `UPDATE prod_print_queue SET status='expired' WHERE status='pending'`.

---

### Task 4: Wyścigi MySQL na dwóch sesjach

**Files:**
- Modify (poza repo): `_priorytety_wyscigi.py`; Create (poza repo): `_wyscigi_k5.jsonl`, `innodb-status-<tryb>-<n>.txt` (tylko przy 1213)

**Interfaces:** Consumes: strony A/B z tabeli; `blokady_zamowien.kod_mysql` (ponowienia po stronie serwera: `desk` K3,
`bulk_action` `products_api.py:1602`, `trasy_api._akcja`, `dostawa_api._zapis`, `panel_api` K2 gwiazdki/drabina,
`kolejka.utrwal` K1). Produces: tabela wyników (tryb, przebiegi, 1213 serwer/log, 500, ponowienia z sukcesem, złamane
niezmienniki, rozkład odpowiedzi A/B).

**Kolejność blokad obu stron każdego trybu (CLAUDE.md „Trasy logistyki”, „Deklaracje paczek”, „zamówienie najpierw”;
spec 9.4; ramki K1 „Współbieżność”, K2 Task 2/3, K3 Task 1–3):**

| Tryb | Stan wyjściowy (Sklejanie `stol`, K=2, chyba że inaczej) | Strona A | Strona B | Dlaczego bez cyklu (kolejność) | Oczekiwane |
|---|---|---|---|---|---|
| **`desk-desk`** | pusty stół, 6 kandydatów, dwa urządzenia | `GET desk` tablet 1 | `GET desk` tablet 2 | obie: `COMMIT` → X `priorytety_blokada_gluing` → S zamówienia ↑ → S pozycje (order_id, id) → SELECT stołu → INSERT; B czeka na pierwszym zamku | 200/200, stół = 2 kafle, `stol_bez_duplikatow`, 0 × 1213, sygnał `station:gluing` raz (tylko od tego, który dopełnił) |
| **`desk-zakoncz-inne`** | stół pełny (A1 z zam. A, B1 z zam. B), kandydat C1 z zam. C | ZAKOŃCZ A1 (tablet 1) | `GET desk` (tablet 2) | ZAKOŃCZ: X A → X pozycje A → UPDATE → X stół A → DELETE; `desk`: blokada stanowiska → S na A,B,C… — jeśli S na A czeka na X ZAKOŃCZ-a, ZAKOŃCZ niczego od `desk` nie chce (nie bierze blokady stanowiska, stół czyta po kluczu) → `desk` czeka, nie zakleszcza; luka indeksu stołu przy INSERT ↔ DELETE — rzadkie 1213 **po stronie `desk`**, ponowienie w routerze (K3 Task 2) | 200/200; po obu: stół = B1 + C1 (albo B1 + następny), `kafel_zamkniety_zniknal(A1)`, 1213 najwyżej po stronie `desk` **z udanym ponowieniem** (liczba do raportu), zero 500 |
| `desk-zakoncz-to-samo-zamowienie` | zam. Z: P1 na stole, P2 kandydat | ZAKOŃCZ P1 | `GET desk` | `desk` chce S na Z (X trzyma ZAKOŃCZ) → czeka do commita, potem widzi P1 już poza statusem i bierze P2 | 200/200, stół: P2 (+ inny), 0 × 1213 |
| `desk-dorobka` | kandydat w zam. Z na Sklejaniu; pozycja Z na Formatowaniu | `POST reject` (doróbka z Formatowania do Sklejania, `returned_to_station=gluing`) | `GET desk` Sklejania | doróbka: blokada tras → X Z → X pozycje Z → INSERT pozycji (luka `order_id` za ostatnią pozycją Z) → `zdejmij_nieaktualne` → commit; `desk`: S zamówienia ↑ → S pozycje — na Z czeka **zanim** sięgnie po jego pozycje (K3 Task 2, analiza) | 200/200; następny `desk` ma doróbkę ponad K (3 kafle), 0 × 1213 |
| `desk-panel-sposob` | Pakowanie `stol`, kandydat bez sposobu dostawy | panel `POST /orders/delivery-method` (kurier) | `GET desk` Pakowania | panel: `_zapis_pod_blokada` (commit → blokada tras → X zamówienia ↑ → …); `desk`: blokada stanowiska → S zamówienia; nikt nie trzyma stanowiska czekając na trasy ani odwrotnie | 200/200; kafel wchodzi teraz albo przy następnym `desk`; **nigdy** kafel bez sposobu na stole (`sposoby.normalizuj(...) is None` → brak wiersza), 0 × 1213 |
| `desk-utrwal` | kopia produkcji, ~250 zamówień aktywnych; stoły 7 stanowisk puste, wszystkie w `stol` na czas trybu | `PUT /zamowienia/gwiazdki` (hurt 20 zamówień → `utrwal()` po commicie) | `GET desk` ×7 (po jednym na stanowisko, równolegle) | `utrwal`: X zamówienia ↑ → X pozycje `WHERE order_id IN (…) ORDER BY id`; `desk`: S zamówienia ↑ → S pozycje (order_id, id); obie rosnąco po zamówieniach, `utrwal` nie zapisuje pozycji zamówienia, którego nie zablokował (sprawdzenie z K3 Task 2) | wszystkie 200, `przeliczenie: "ok"`, 0 × 1213; `rangi_zbiezne` po przebiegu; jeśli 1213 → `INNODB STATUS` i sprawdź, czy `utrwal` dotknął pozycji zamówienia spoza swojej listy X |
| **`gwiazdki-zakoncz`** | zam. A z kaflem A1 na stole, bez gwiazdek | `PUT /zamowienia/gwiazdki` `{order_ids:[A], gwiazdki: 4}` | ZAKOŃCZ A1 | gwiazdki: commit → X A (rosnąco) → UPDATE A → INSERT log (FK A) → commit → `utrwal` (X A → X pozycje A); ZAKOŃCZ: X A → X pozycje A → … — ten sam prefiks, serializacja na A | 200/200; `priority_stars=4`, A1 poza Sklejaniem, wiersz stołu zniknął, `rangi_zbiezne` (gdy ZAKOŃCZ zatwierdzi się po migawce `utrwal` gwiazdek, pierwsze dodatkowe `utrwal` coś zmieni — statystyka, p. 9), 0 × 1213 |
| **`szczebel-przystanek`** | trasa robocza T (szczebel na drabinie), zam. B bez trasy | panel `PUT /drabina/kolejnosc` (tag „Rozpoczęte” o 1 w górę, z `oczekiwane`) | panel `POST /routes/<T>/stops` `{order_ids:[B]}` | obie zaczynają od `routes.zablokuj_trasy()` (drabina: commit → blokada tras → `prod_priority_rungs FOR UPDATE`; przystanek: `_akcja` → blokada tras → …) → pełna serializacja; każda woła `utrwal_po_commicie()` po swoim commicie | 200/200 (dodanie przystanku nie zmienia listy szczebli, więc 409 `drabina_zmieniona` nie powinno wystąpić — jeśli wystąpi, zapisz); drabina spójna (`position` 1..n bez luk), B ma `priority_rung` = pozycja szczebla T, `rangi_zbiezne`, 0 × 1213 |
| **`utrwal-dostawa`** | trasa zatwierdzona T z 2 zamówieniami Z1, Z2, wszystkie pozycje `zweryfikowane` i wszystkie paczki załadowane (stan jak `tests/dostawa_pomocnicze.zaladuj_wprost`), żeby `finish-loading` przeszło; obok ≥ 20 innych zamówień aktywnych (praca dla `utrwal`). Wariant b (×10, dodatkowo): Z2 ma pozycję w produkcji → B odmawia 409 `loading_incomplete` **pod blokadami** (`dostawa.zakoncz_zaladunek`: najpierw `zablokuj(route)`, potem decyzja i rollback w `_zapis`), A 200 | `PUT /zamowienia/gwiazdki` `{order_ids:[Z1], gwiazdki: 2}` → X na wierszu Z1 (gwiazdki blokują zamówienie niezależnie od aktywności) → commit → `utrwal()` | telefon kierowcy `POST /api/mobile/delivery/routes/<T>/finish-loading` | Dostawa: pracownicy → blokada tras → deklaracje → X zamówienia **całej trasy** ↑ (Z1, Z2) → paczki → pozycje; gwiazdki: X Z1; `utrwal`: X zamówienia aktywne ↑ → X ich pozycje — wszystko sufiksem tego samego łańcucha, sporny jest wiersz Z1; Dostawa planuje `utrwal` w `g`, dekorator wykonuje po commicie (K1) | 200/200; trasa `zaladowana`, pozycje `zaladowane`, szczebel T **ukryty** w `GET /drabina`, `priority_stars` Z1 = 2, `rangi_zbiezne` (dwa `utrwal` — jeden z panelu, jeden po commicie Dostawy — na przeplecionych migawkach mogą zostawić stan o krok nieaktualny; punkt stały osiąga dodatkowe `utrwal`, p. 9), 0 × 1213 |
| **`odloz-zakoncz-ten-sam-kafel`** | kafel A1 na stole, dwa tablety | `POST postpone` A1 (`brak_materialu`) | ZAKOŃCZ A1 (inny `X-Operation-Id`) | obie: pracownicy → X A → X pozycje A → (Odłóż: wiersz stołu **własnego kafla** `FOR UPDATE` po `unit_key` → zwykły `COUNT` odłożonych → UPDATE → INSERT log; K3 Doprecyzowania p. 13) / (ZAKOŃCZ: UPDATE pozycji → wiersze stołu zamówienia `FOR UPDATE` po `order_id` (`zdejmij_nieaktualne`/`zdejmij_kafel`) → DELETE) — serializacja na A | **dwa dopuszczalne przeplecenia**: Odłóż pierwszy → 200, potem ZAKOŃCZ odłożonego → 200 z logiem `odlozenie_zamkniete`; ZAKOŃCZ pierwszy → 200, Odłóż → 409 `nie_na_stole` **bez wpisu idempotencji**. Zero 500, 0 × 1213, po obu brak wiersza stołu A1; rozkład przeplatań do raportu |
| `odloz-odloz` | limit 2, jeden odłożony, kafle A1, B1 na stole | `postpone` A1 | `postpone` B1 | X zamówień różnych → każda blokuje tylko wiersz **własnego** kafla; limit ze zwykłego `COUNT` (migawka żądania) — strony nie czekają na siebie (limit miękki, K3 Doprecyzowania p. 13; Doprecyzowania p. 10 tutaj) | jedno 200 i jedno 409 `limit_odlozen` (bez wpisu idempotencji) **albo** oba 200; odłożonych ≤ limit + 1; rozkład do raportu; 0 × 1213 |
| `odloz-zakoncz` | kafle A1, B1 na stole (dwa tablety jednego stanowiska) | `postpone` A1 | ZAKOŃCZ B1 | każda strona blokuje tylko wiersz swojego zamówienia i jego wiersze stołu (`unit_key`/`order_id`) — rozłączne zbiory, bez czekania (przy blokadzie wierszy całego stanowiska wychodził tu cykl indeks wtórny ↔ klucz główny, K3) | 200/200 bez czekania na siebie (czasy A/B do raportu), 0 × 1213 |
| `odloz-hurt` | kafle A1, B1, C1 na stole (trzy zamówienia; wiersz C1 wstawiony przed A1, czyli niższe `id` w `prod_station_desk`) | `postpone` B1 | panel `POST /products/bulk-action` `update_status: wstrzymane` na A i C | hurt: blokada tras → X A, C rosnąco → X ich pozycje → UPDATE → `zdejmij_nieaktualne` (wiersze stołu A, potem C) → commit; Odłóż: X B → pozycje B → wiersz stołu B1 — zbiory wierszy rozłączne (K3 Task 6 Step 5) | 200/200; kafle A1 i C1 zniknęły, B1 odłożony, `stol_bez_nieaktualnych`, 0 × 1213 bez ponowienia (hurt ponawia raz — liczba do raportu) |
| `zakoncz-zakoncz-ten-sam-kafel` | kafel A1 na stole, dwa tablety | ZAKOŃCZ A1 | ZAKOŃCZ A1 (inny op-id) | X A serializuje; drugi widzi pozycję poza statusem S | pierwszy 200; drugi: 200 idempotentnie po statusie **albo** 409 `nie_na_stole` — zapisz które (Doprecyzowania p. 6); zero 500; wiersz stołu zniknął raz, jeden wpis `odlozenie_zamkniete` najwyżej |
| `hurt-desk` | 20 pozycji Sklejania zaznaczonych w panelu, 2 z nich na stole | panel `POST /products/bulk-action` `update_status: wstrzymane` | `GET desk` | hurt: blokada tras → X zamówienia ↑ → X pozycje per zamówienie → UPDATE → `zdejmij_nieaktualne` → commit → sygnały; `desk`: blokada stanowiska → S zamówienia — czeka na X hurtu, nie odwrotnie | 200/200; kafle wstrzymanych zniknęły, `desk` dopełnił innymi, `stol_bez_nieaktualnych`, 0 × 1213 bez ponowienia (hurt ponawia raz — liczba do raportu) |

Tryby **wytłuszczone** = sześć obowiązkowych z zakresu kroku; reszta (9) z listy K3 (Task 6 Step 5, z `odloz-hurt`).
Opisy Odłóż w tej tabeli są już po recenzji K3 (blokada tylko własnego kafla, limit miękki). Jeśli raport K3 dodał tryby
spoza tej tabeli albo zmienił kolejność blokad — dołóż/popraw je (Odstępstwa).

- [x] **Step 1: Serie obowiązkowe** — każdy z 6 trybów wytłuszczonych: **×20 czysta bariera, ×12 rozjazd 0–40 ms, ×30 rozjazd
  0–15 ms = 62 przebiegi** (jak 4.4a Task 3). Przed każdą serią `zakleszczenia_serwera()` i znacznik logu; po każdym przebiegu
  wszystkie niezmienniki. Wyniki do `_wyscigi_k5.jsonl` (tryb, n, rozjazd, status A, status B, kody błędów, czas A/B, 1213
  serwer, 1213 log, 500, niezmienniki).
- [x] **Step 2: Serie z listy K3** — 9 trybów po **×10 bariera + ×10 rozjazd 0–40 + ×10 rozjazd 0–15 = 30**. `desk-utrwal`
  tylko na kopii produkcji (Task 2) — na niej wszystkie 7 stanowisk na czas trybu w `stol` (zapisz i przywróć `stary`).
- [x] **Step 3: Regresja wyścigów logistyki (jeśli skrypty 4.4a/4.4b są dostępne z katalogu podglądów Konrada)** —
  `panel-zakoncz-ostatnie`, `dorobka-zakoncz`, `sync-zakoncz` (4.4a) i `zakonczenie-zakoncz`, `dostarcz-dostarcz` (4.4b) po
  ×10: nowy pisarz `utrwal()` po commicie każdej z tych akcji nie może wprowadzić 1213 ani zmienić wyniku. Brak skryptów →
  pomiń i zapisz w „Odstępstwach” (centrala decyduje, czy K7 to nadrobi).
- [x] **Step 4: Przy pierwszym 1213 bez ponowienia, 500 albo złamanym niezmienniku** — natychmiast
  `docker compose exec db mysql -uroot -e "SHOW ENGINE INNODB STATUS\G" > innodb-status-<tryb>-<n>.txt` (zostaw sekcję
  `LATEST DETECTED DEADLOCK`, usuń zrzuty rekordów z danymi klientów), dokończ serię dla częstości, **STOP**: tryb, częstość,
  dwie transakcje cyklu (tabela, indeks, typ blokady, zapytanie), hipoteza (który pisarz złamał kolejność z tabeli wyżej),
  meldunek do centrali. Bez zmian w kodzie (podręcznik 4a p. 3: analiza na Fable 5.1 max, decyzja Konrada).
- [x] **Step 5: Czasy z wyścigów** — mediany i p95 czasu odpowiedzi `desk`, ZAKOŃCZ, `postpone`, gwiazdek (z `_wyscigi_k5.jsonl`)
  do tabeli czasów (Task 5 Step 4). Przywróć `priorytety_tryb_gluing=stary`, `limit_odlozen=10` na podglądzie po zakończeniu
  Task 5 (nie teraz — Task 5 używa trybu `stol`).

---

### Task 5: Oględziny w przeglądarce, curl API mobilnego, sygnały z brokerem, czasy

**Files:**
- Create (poza repo): zrzuty ekranu w `<katalog>/zrzuty-k5/` (baza kopii zawiera dane klientów → zrzuty **nie trafiają do repo**;
  w raporcie ścieżki i opis), `k5-czasy.md`

**Interfaces:** Consumes: UI K4a/K4b, końcówki K2/K3, `GET /api/mobile/realtime-token`, SSE `uni_sse` brokera.
Produces: lista „sprawdzone / usterki” i tabela czasów.

- [x] **Step 1: Panel biura (podgląd, kopia produkcji, przeglądarka)**
  1. **Lista produkcyjna**: zakładka nazywa się „Lista produkcyjna”; karty po randze `#1, #2…` zgodnie z `GET /kolejka`;
     plakietki tagów („Po terminie”, „Blisko terminu”, „Rozpoczęte”); przycisk gwiazdek otwiera **modal priorytetu**: zmiana
     0→3→0 zapisuje (`PUT /zamowienia/gwiazdki`), historia rośnie, „Gdzie leży” zgadza się z `GET /kolejka?stanowisko=`;
     **modal drabiny**: strzałki przy tagach i trasach, kłódka przy gwiazdkach, przesunięcie „Rozpoczęte” ↑ zmienia kolejność
     kart po zamknięciu; druga karta przeglądarki przesuwa szczebel → pierwsza dostaje `drabina_zmieniona`; ostrzeżenie o datach
     przy dwóch trasach w odwrotnej kolejności (załóż dwie trasy robocze w Logistyce); hurt „Ustaw gwiazdki” na 2 zamówieniach.
  2. **Logistyka**: kolumna ★ (zmiana, sortowanie), gwiazdki przy przystankach w edytorze trasy; dodanie przystanku →
     karta zamówienia w Liście produkcyjnej dostaje plakietkę trasy i nowe miejsce (po `utrwal`).
  3. **Konfiguracja**: karty „Terminy” (16/21, `robocze`/`kalendarzowe`, opis „dotyczy tylko nowych importów”) i „Stół
     stanowisk” (7 wierszy, próg 3, `min_app_version_code` 0); zapis K Sklejania → toast; K=9 → podświetlone pole;
     `POST /production/api/update-configs` z `DEADLINE_DEFAULT_DAYS` → 400 i pojedyncze `POST /production/api/update-config`
     z `priorytety_tryb_gluing` → 400 (jedna droga zapisu, K4b Doprecyzowania 14).
  4. **Stanowiska**: wg decyzji K4b (A: zakładka w panelu; B: `GET /production/api/stations-tab-content` wstawiony do pustej
     strony): stół, odłożone, niekompletne na Formatowaniu, pierwsze 15 kafli; brak progów rangi.
  5. **Monitory hali**: `/production/stations/monitors/gluing` i `/production/stations/monitor` (IP podglądu dozwolone):
     tryb `stol` → sekcje „TERAZ” i „Odłożone” po ≤ 30 s bez przeładowania; zmiana gwiazdek w panelu → karta przesuwa się po
     odświeżeniu, przewijanie nie skacze; doróbka pierwsza.
  6. **Dashboard**: `GET /production/api/dashboard-stats` → `high_priority_count` = suma `w_produkcji` szczebli ★★★★★, ★★★★,
     „Po terminie”, tras z `GET /drabina`.
  7. **Konsola DevTools**: zero błędów JS na każdej z powyższych stron. Klawiatura: Tab → przycisk gwiazdek → Enter → modal → Esc.
  Zrzuty (1440 i 390 px): Lista produkcyjna, modal priorytetu, modal drabiny, Logistyka ★, Konfiguracja (2 karty), Stanowiska,
  monitor w `stary` i `stol`. Każda usterka UI → „Odstępstwa”/blokada w werdykcie (naprawa UI należy do karty naprawczej K4a/K4b,
  **nie** do K5).
- [x] **Step 2: API mobilne curl-em (Sklejanie w trybie `stol`, K=2, limit 2; tokeny urządzeń podglądu; każdy `curl` i skrócona
  odpowiedź do raportu, bez danych klientów)**
  ```
  GET  /api/mobile/stations/gluing/desk                      → 200: jednostka "pozycja", miejsca 2, stol[2], odlozone[], kolejka_dalej, kafel.priorytet{gwiazdki,szczebel,trasa,pozycja_w_zamowieniu}; ETag; drugi GET z If-None-Match → 304
  GET  /api/mobile/stations/formatting/desk                  → 200: jednostka "zamowienie", kafel.zamowienie + kafel.pozycje, niekompletne[] z brakuje[].short_id/stanowisko
  POST /api/mobile/orders/<kafel>/postpone {station_code:"gluing", zakres:"pozycja", powod:"brak_materialu"}   → 200, odlozone[1] z pracownik/powod; sygnał station:gluing
  POST …/postpone (drugi kafel)                              → 200; trzeci kafel → 409 limit_odlozen (ProcessedMobileOperation bez wpisu dla tego op-id)
  POST …/postpone {powod:"inne"} bez notatki                 → 400 powod_niepoprawny; {zakres:"zamowienie"} na Sklejaniu → 400 dane_niepoprawne
  POST /api/mobile/orders/<pozycja POZA stołem>/complete     → 409 nie_na_stole, message z numerem zamówienia i „Sklejania”; status pozycji bez zmian; bez wpisu idempotencji
  PATCH /api/mobile/orders/<pozycja POZA stołem>/quantity    → 409 nie_na_stole
  POST /api/mobile/orders/<kafel odłożony>/complete          → 200; wiersz stołu znika; prod_priority_log ma odlozenie_zamkniete
  POST /api/mobile/orders/<kafel na stole>/complete          → 200; GET desk → nowy kafel dopełniony; sygnały station:gluing + station:formatting
  GET  /api/mobile/stations/gluing/orders                    → 200 (stara appka): pełna lista, pozycja ma priorytet, ETag inny niż z KSZTALT 5
  GET  /api/mobile/realtime-token                            → 200 {enabled, token, ttl_seconds, sse_url, channels:["station:gluing"]}; urządzenie edges → 2 kanały; trakownia → 404 unknown_station
  tryb stary (PUT /ustawienia gluing tryb=stary): POST complete pozycji poza stołem → 200 (bez bramki), a jeśli miała wiersz stołu → wiersz znika
  ```
- [x] **Step 3: Sygnały przez broker (Review Focus 4)** — w drugim terminalu `curl -N "<sse_url>?cf_connect=<json z tokenem>"`
  (format `uni_sse` Centrifugo; token z `/realtime-token` tabletu Sklejania; drugi strumień dla tabletu Formatowania). Po
  ZAKOŃCZ kafla Sklejania (pozycja z `cut_to_size` = 1 — inaczej następnym stanowiskiem jest inne, wg `sygnaly.nastepne_stanowisko`): publikacja na `station:gluing` **i** `station:formatting` (ładunek `{"kind":"station","station":…}`,
  bez danych); po `postpone` — tylko `station:gluing`; po 409 `nie_na_stole` — nic; po `GET desk`, który dopełnił — jeden
  sygnał, po `GET desk` bez zmian — nic. `docker stop centrifugo-podglad` → ZAKOŃCZ dalej 200 (publish zwraca False, log
  WARNING/Sentry-alert jak dla druku), `/realtime-token` → 200 z tokenem (broker nieosiągalny nie zmienia `enabled`) —
  zapisz zachowanie; `REALTIME.enabled=false` + restart → `/realtime-token` → 503 `{enabled:false, reason:"realtime disabled"}`.
  Przywróć broker i `enabled=true`.
- [x] **Step 4: Czasy (kopia produkcji, ~250 zamówień aktywnych, DevTools Network albo `curl -w '%{time_total}'`, mediana z 5):**
  `GET /production/api/priorytety/kolejka` (próg 1 s), `GET …/zamowienia/<id>/priorytet` (1 s), `GET /drabina`,
  `GET /api/mobile/stations/gluing/desk` z pustym stołem i z pełnym (300 ms), `GET /production/api/stations-tab-content` (1 s),
  `GET /production/stations/ajax/monitors/gluing`, `POST /routes/<id>/stops` **z** `utrwal_po_commicie` kontra czas samego
  `utrwal()` z odpowiedzi crona (`duration_seconds`) — przyrost dla K1 pytanie 2; `PUT /zamowienia/gwiazdki` hurt 20 zamówień
  (z `utrwal`). Tabela do `k5-czasy.md` i raportu; przekroczenia = uwagi w werdykcie z rekomendacją (Doprecyzowania p. 5).
- [x] **Step 5: Przywróć podgląd**: `priorytety_tryb_gluing=stary`, `limit_odlozen=10`, stoły opróżnione
  (`DELETE FROM prod_station_desk` tylko na podglądzie), etykiety wygaszone. Bez commita (Task 5 nie zmienia repo).

---

### Task 6: Dokumentacja — CLAUDE.md, spec (sekcja 16, poprawki zaszłości), lista wdrożenia P1

**Files:**
- Modify: `CLAUDE.md` (`:149`, `:276-298`, `:368-369`, `:384`, nowa sekcja między `:386` i `:387` — po K1–K4b szukaj po
  tekście „Deklaracje paczek — jedna naraz” i „## Architecture”)
- Modify: `docs/superpowers/specs/2026-10-04-priorytety-produkcji-design.md` (4.3 `:246`, 11 `:689-690`, 13 `:712`, `:718-720`, nowa `## 16` po `:762`)

**Interfaces:** Produces: tekst dokumentacji. Consumes: notatka robocza z Task 1–5 (ścieżka:linia dla każdego zdania),
sekcje „Doprecyzowania (do specu — K5 przeniesie)” z planów — **w całości**: K1 (21 punktów wypunktowanych, bez numerów —
w specu 16 ponumeruj je K1.1–K1.21), K2 (p. 1–14), K3 (p. 1–16), K4a (p. 1–14), K4b (p. 1–14) — oraz Doprecyzowania p. 9–12
tego planu, odpowiedzi Konrada z dziennika centrali i raporty K1–K4b („Odstępstwa”, „Rozstrzygnięcia”).

- [x] **Step 1: Test strukturalny, który pada** — `tests/test_priorytety_dokumentacja.py` (nowy, mały; konwencja testów na źródle
  jak `tests/krawedzie_fixtures.zrodlo`): `test_claude_md_ma_sekcje_priorytety_produkcji` (`### Priorytety produkcji` przed
  `## Architecture`; w sekcji występują: `kolejka.utrwal`, `priorytety_blokada_`, `stol.dopelnij`, `zdejmij_nieaktualne`,
  `station:<kod>`, `priorytety_tryb_`, `priorytety_min_app_version_code`, `szczeble_uzupelnione`, `priorytety_utrwalone`,
  `/production/api/priorytety/ustawienia`), `test_claude_md_bez_martwych_pisarzy_priorytetow` (w CLAUDE.md nie ma
  „przeciąganie `update-priority`”, „hurtowa i ręczna zmiana priorytetu”, „przeciąganie i przeliczenie priorytetów” —
  porównanie **bez rozróżniania wielkości liter i po sklejeniu białych znaków** (`' '.join(tekst.split()).lower()`):
  CLAUDE.md łamie wiersze w środku zdań, a `:369` ma „Przeciąganie i przeliczenie…” wielką literą),
  `test_spec_ma_sekcje_16_i_prog_3` (spec zawiera `## 16. Doprecyzowania z realizacji`; w 4.3 nie ma „domyślnie 2”; w 13 nie ma
  „seed 8 szczebli”). Run → FAIL.
- [x] **Step 2: CLAUDE.md — nowa `### Priorytety produkcji`** (po punkcie „Deklaracje paczek”, przed `## Architecture`; prosa w stylu
  sekcji „Zadania cykliczne”; każde zdanie z pokryciem w kodzie; **bez** numerów linii, z nazwami funkcji i plików). Zawartość:
  - **Model:** drabina szczebli (`prod_priority_rungs`: gwiazdki stałe, tagi `po_terminie`/`blisko_terminu`/`rozpoczete` i trasy
    ruchome; domyślna kolejność 3.1 z decyzji 5.10), gwiazdki 0–5 na **zamówieniu** (`prod_orders.priority_stars`), zamówienie z trasy
    roboczej/zatwierdzonej bierze szczebel trasy; ranga zamówienia `prod_orders.priority_rank/priority_rung` i pozycji
    (`ranga×100+sekwencja`, doróbki 0, `is_priority` pochodna) to **pamięć podręczna** licząca się przez `kolejka.utrwal()` na
    własnej sesji (nigdy `db.session`); panel liczy na żywo (`kolejka.policz`); `priority_service.py` to warstwa zgodności do P4.
  - **Blokady** (dopisanie do łańcucha „Trasy logistyki → Deklaracje → zamówienia → paczki → pozycje”): `utrwal()` — zamówienia
    `FOR UPDATE` rosnąco → pozycje tych zamówień rosnąco, bez blokady tras i stołu, jedno ponowienie po 1213; gwiazdki —
    `commit` → `blokady_zamowien.zablokuj_zamowienia` → zapis → `commit` → `utrwal`, bez blokady tras; drabina — `commit` →
    `routes.zablokuj_trasy()` → `prod_priority_rungs FOR UPDATE`; `stol.dopelnij(S)` — **tylko w `GET desk`**, nigdy w ZAKOŃCZ:
    `commit` → `prod_config` `priorytety_blokada_<S>` `FOR UPDATE` (samonaprawa `INSERT IGNORE` jak blokada tras) → zwykły odczyt
    id zamówień z pozycją w statusie S → zamówienia `FOR SHARE` rosnąco (w SQL z SQLAlchemy 1.4: `LOCK IN SHARE MODE`) → pozycje
    tych zamówień `FOR SHARE` `(order_id, id)` → zwykły SELECT stołu → INSERT; wiersze `prod_station_desk` zmienia się
    tylko pod X zamówienia (ZAKOŃCZ, Odłóż, hurt, Base., doróbka, cron przez `stol.zdejmij_nieaktualne`) albo pod blokadą stanowiska,
    a blokujący odczyt stołu obejmuje wyłącznie wiersze własnego kafla (`unit_key`) albo zablokowanego zamówienia (`order_id`) —
    nigdy całe stanowisko; Odłóż liczy limit zwykłym `COUNT` (limit miękki, dwa tablety naraz mogą go przekroczyć o 1);
    `order_quantity` czyta stół bez blokady zamówienia (bramka, nie zapis). Znane wyjątki bez `zdejmij_nieaktualne`, bez naprawy
    (jak w akapicie pisarzy pozycji): hurtowe usunięcie pozycji (`bulk-action` `delete`) i ręczna synchronizacja z `force_update`
    — kafel `o:` może zostać na stole do ręcznego sprzątnięcia (plan K3, „Poza zakresem”). Nowy zapis stołu albo rang zaczyna od
    tych samych zamków w tej kolejności. Wyniki wyścigów K5 jednym zdaniem (liczby).
  - **Stół, Odłóż, bramka:** K miejsc (`priorytety_stol_<S>`), jednostka (`priorytety_jednostka_<S>`), tryb (`priorytety_tryb_<S>`:
    `stary` = bez bramki, `stol` = 409 `nie_na_stole` poza stołem/odłożonymi; stara appka wg `priorytety_min_app_version_code`,
    0 = brak bramki wersji, tablet bez heartbeatu = stara), limit odłożeń, `delivery_method_not_set` przed bramką, Formatowanie
    i Pakowanie zamówieniowe (kompletne na stół, niekompletne osobno), doróbka ponad K.
  - **Sygnały:** najpierw baza, potem `station:<kod>` bez ładunku, w `with_idempotency` po commicie (czwarty hook obok druku,
    Base., `utrwal`), kanał następnego stanowiska przy ZAKOŃCZ, `publish` nie rzuca, siatka appki 30 s / 5 min, `GET
    /api/mobile/realtime-token`, `REALTIME.enabled=false` → 503 i polling.
  - **Cron:** `/production/api/logistics/cron` ma fazy `szczeble_uzupelnione` (pod blokadą tras) i `priorytety_utrwalone`
    (tagi zmieniają się z datą); ustawienia przez `config_service` (pamięć podręczna 60 min na proces — stan wg raportu K2:
    naprawione albo „do czasu restartu/godziny”).
  - **Co uruchomić po wdrożeniu P1:** raz ręcznie `scripts/cron_endpoint.sh POST /production/api/logistics/cron` po restarcie
    (szczeble istniejących tras, rangi nowym algorytmem); wszystkie stanowiska zostają w `stary`; przed P3 ustawić
    `priorytety_min_app_version_code` = kod nowej appki, potem `priorytety_tryb_<S>` → `stol` stanowisko po stanowisku
    (Konfiguracja → karta „Stół stanowisk”, jedyna droga zapisu — `update-configs` odrzuca te klucze); wycofanie P3 = tryb `stary`
    bez zmiany kodu; wycofanie P1 = cofnięcie kodu, kolumny zostają.
- [x] **Step 3: CLAUDE.md — uzupełnienia istniejących miejsc**
  - „Logistyka równoległa” (`:276-298`): dopisek „**Od P1 priorytetów** trasa robocza/zatwierdzona ma szczebel na drabinie
    (`drabina.zapewnij_szczebel_trasy` pod blokadą tras w `routes.utworz`), a akcje tras, zmiana sposobu dostawy, „Wydane klientowi”
    i Dostawa przeliczają rangi po commicie (`kolejka.utrwal_po_commicie`, w telefonie kierowcy przez plan w `g`) — patrz
    „Priorytety produkcji”.”
  - „Zadania cykliczne” (`:149`, akapit crona logistyki): „Od P1 ten sam cron uzupełnia szczeble tras i utrwala rangi
    (`szczeble_uzupelnione`, `priorytety_utrwalone` w odpowiedzi).”
  - Akapit pisarzy pozycji (`:368-369`): „oraz priorytety (przeciąganie `update-priority` jednym odczytem, hurtowa i ręczna zmiana
    priorytetu, przeliczenie `priority_service` na własnej sesji bez autoflushu). Przeciąganie i przeliczenie priorytetów ponawiają
    raz po 1213 (…)” → „Przeliczenie priorytetów (`kolejka.utrwal()`, własna sesja) **nie jest już** pisarzem bez blokady
    zamówienia — blokuje zamówienia przed pozycjami (sekcja „Priorytety produkcji”); przeciąganie, `bulk-action update_priority`
    i `set-priority` usunięto w P1.” `:384`: „oraz przeciąganie i przeliczenie priorytetów” → „oraz przeliczenie priorytetów
    (`kolejka.utrwal`), gwiazdki i drabina w panelu priorytetów (`priorytety/routers/panel_api.py`) i dopełnianie stołu
    (`GET desk`)”.
- [x] **Step 4: Spec** — `## 16. Doprecyzowania z realizacji (K1–K5)` po sekcji 15: numerowane punkty w grupach „K1”, „K2”, „K3”,
  „K4a”, „K4b”, „K5” przepisane z sekcji „Doprecyzowania (do specu)” planów i skorygowane o „Odstępstwa”/„Rozstrzygnięcia”
  z raportów (to, co faktycznie w kodzie, nie to, co planowano); na końcu „Wyniki K5”: tabela wyścigów (tryb, przebiegi, 1213,
  ponowienia, niezmienniki), migracja (obie bazy), czasy, zgodność z symulacją. Dopiski „(K5)” w treści: 4.3 „domyślnie 2” →
  „domyślnie **3** (decyzja 5.10)”; 13 „seed 8 szczebli” → „seed 9 szczebli (z tagiem „Rozpoczęte”)”, lista wyścigów `:718-720`
  → odesłanie do 16; 9.4 „FOR SHARE pozycje, bez blokad zamówień” → „(K3/K5) `dopelnij` czyta zamówienia `FOR SHARE` rosnąco,
  potem pozycje — kolejność kanoniczna, patrz 16”; 6.1 `szczebel` → dopisz `"rozpoczete"`; 9.1 `templates/priorytety/` → „(K4a)
  modale budowane w JS, katalog nie powstał”; 5.2 „`FOR UPDATE` na wierszu `prod_config` `priorytety_stol_<kod>`” → „(K5)
  `priorytety_blokada_<kod>` (8.6; `priorytety_stol_<S>` to K)”; 9.2 `stol.odloz` „sprawdza limit odczytem bieżącym stołu
  stanowiska” → „(K3/K5) zwykłym `COUNT`, blokada tylko własnego kafla, limit miękki — patrz 16”; 9.3 wiersz „import z Base.”
  → „(K1) przez warstwę zgodności `priority_service` do P4”; **3.3** (narracja przykładu Konrada kontra 3.2 p. 1 „gwiazdki przed
  grupą materiału”) — wg odpowiedzi Konrada na pytanie 3 planu K1 (dziennik centrali / raport K1): jeśli zostaje 3.2 —
  popraw narrację 3.3 („w szczeblu trasy pozycje A ★★ idą przed B, potem grupy”); jeśli wybrał 3.3 — sprawdź, że K1 zmienił
  klucz kafla, inaczej to blokada K1; brak odpowiedzi → pytanie w raporcie, 3.3 z dopiskiem „(K5) do decyzji”; numeracja
  sekcji 2 (punkt 14 stoi przed 13) — bez przenumerowania, tylko dopisek; 11 — po akapicie „Po wdrożeniu P1 uruchom raz ręcznie…” dopisz „(K5) Lista
  wdrożenia P1 — pełna w raporcie K5; skrót:” z 6–8 punktami (Step 5). Spec zostaje spójny: nic nie usuwamy, dopiski oznaczone.
- [x] **Step 5: Lista wdrożenia P1 dla K7** (do raportu w całości, do specu 11 w skrócie), punkty:
  1. Warunki wejścia: logistyka etapy 1–4 na `main` i na produkcji (`flask migrate-status` pokazuje `2026-10-02-*`), Centrifugo
     działa (`supervisorctl status centrifugo`; `/etc/centrifugo/config.json` ma namespace `station` — ops README mówi „przygotowane”,
     K7 sprawdza), Base. status 524520 istnieje (logistyka), hash gałęzi roboczej = hash z werdyktu K5.
  2. Scalenie `claude/priorytety-produkcji` → `main` (= deploy; `deploy.sh`: `flask migrate` przed restartem — migracja
     `2026-10-05-priorytety-produkcji.sql`; przy błędzie deploy cofa kod sam). W oknie wdrożenia stary worker nic nie rzuci (bez ENUM).
  3. Po `Deploy complete!`: **raz ręcznie** `scripts/cron_endpoint.sh POST /production/api/logistics/cron` → oczekiwane
     `szczeble_uzupelnione` = liczba tras roboczych/zatwierdzonych, `priorytety_utrwalone.success: true`, `zamowien` ≈ aktywne.
  4. Weryfikacja (SQL i HTTP, bez danych klientów): 9 + N szczebli, 38 wierszy `prod_config` `priorytety_*`, rangi unikatowe,
     `GET /production/api/priorytety/drabina` 200, Lista produkcyjna po randze, Konfiguracja (karty), monitory hali bez błędu,
     tablet: lista `/stations/<kod>/orders` działa (ETag zmieniony raz, pole `priorytet` ignorowane), `GET /api/mobile/realtime-token`
     200 z produkcyjnego brokera.
  5. Stan po P1: wszystkie `priorytety_tryb_<S>=stary`, `priorytety_min_app_version_code=0`, nic nie przełączać do K6/appki.
  6. Komunikat do biura: „Lista produktów” → „Lista produkcyjna”, modal priorytetu i „Drabina priorytetów”, gwiazdki dla całego biura
     (nie tylko admin), stara karta przeglądarki → 404 na starej gwiazdce do odświeżenia; Logistyka ma kolumnę ★.
  7. Obserwacja 24 h: log crona co godzinę (`priorytety_utrwalone.success`, `duration_seconds`), Sentry: WARNING „trasa bez
     szczebla” (samonaprawa), ERROR `utrwal` → karta naprawcza; czasy `GET /kolejka` i `desk` z produkcji kontra K5.
  8. Wycofanie P1: cofnięcie kodu, kolumny i tabele zostają, stary algorytm przelicza rangi przy następnej synchronizacji.
  9. P3 (po K6 i appce, prowadzi K7 część 2): `priorytety_min_app_version_code` = kod nowej appki **przed** pierwszym `stol`;
     kolejność stanowisk S-6 (Sklejanie → Formatowanie → Składanie → Wycinanie → Krawędzie → Pakowanie → Lakiernia, po 2 dniach
     obserwacji); pomiar `FLASK_SKIP_DOTENV=1 venv/bin/python scripts/symulacja_priorytetow.py --dni 30 --blisko 3 --out /tmp/po-p3.md`
     (udział zakończeń z pominięciem pilniejszego: dziś 84–96 %; rozrzut przed Formatowaniem p90 70,8 h — nie może wzrosnąć).
- [x] **Step 6: Test przechodzi** (`PYTEST tests/test_priorytety_dokumentacja.py`), całość `tests/test_priorytety_*.py` zielona. Przeczytaj
  CLAUDE.md od `### Ważne` do `## Architecture` raz w całości — spójność z resztą (nazwy, brak powtórzeń z „Logistyka równoległa”).
- [x] **Step 7: Commit**
  ```bash
  git add CLAUDE.md tests/test_priorytety_dokumentacja.py
  git add -f docs/superpowers/specs/2026-10-04-priorytety-produkcji-design.md
  git commit -m "docs(priorytety): sekcja Priorytety produkcji w CLAUDE.md, doprecyzowania z realizacji i lista wdrozenia P1 w specu" -m "<stopka atrybucji sesji>"
  ```

---

### Task 7: Werdykt i raport kroku K5

**Files:**
- Create: `docs/superpowers/plans/raporty/2026-10-05-priorytety-krok-K5-raport.md`
- Modify: `docs/superpowers/plans/2026-10-05-priorytety-krok-K5-przeglad-p1.md` (odhaczone checkboxy)

- [x] **Step 1: Pełny pakiet po Task 6** — `PYTEST tests/` (0 failed; passed = Task 1 Step 3 + testy dokumentacji + poprawki)
  i `blog_seo`; składnia 3.9 dla plików `.py` zmienionych w K5 (`git diff --name-only <hash startu K5>..HEAD -- '*.py'`).
- [x] **Step 2: Raport** z sekcjami karty (podręcznik 2 p. 7): **Zrobione** (po Taskach 1–6, hashe commitów; Task 2–5 bez commitów —
  wyniki), **Testy** (polecenia i wyniki: pełny pakiet przed/po, blog_seo, składnia 3.9; migracja — oba protokoły z liczbami i
  kolejnością wykonania z logu; cron na kopii; porównanie z symulacją; `general_log` obu żądań; **tabela wyścigów** 15 (+ regresja)
  trybów: przebiegi, 1213 serwer/log, 500, ponowienia z sukcesem, złamane niezmienniki, rozkład odpowiedzi A/B, czasy; **curl** API
  mobilnego z odpowiedziami; sygnały z brokerem; **tabela czasów** z progami), **Odstępstwa od planu**, **Rozstrzygnięcia podjęte
  w trakcie** (numerowane; koszt, jeśli błędne — co najmniej: wariant skryptu wyścigów (HTTP vs test_client), semantyka drugiego
  ZAKOŃCZ tego samego kafla, obsługa pamięci podręcznej ustawień na podglądzie, pominięte regresje 4.4a/4.4b), **Pytania do
  Konrada** (otwarte z K1–K4b, które K5 potwierdził albo nie: K2 zakres progu 0–15 i `GET /ustawienia` tylko admin; K3 kolejność
  `dopelnij`, `postpone` bez dopełnienia, próg wersji; K4a gwiazdki dla biura, brak drag&drop, plakietka zbiorcza; K4b zakres dni
  1–90, notatka odłożenia na telewizorze, próg alertu > 10; K1 koszt `utrwal` po akcjach tras — z liczbą z Task 5 — i pytanie 3
  „gwiazdki przed grupą materiału” (3.2 kontra 3.3), jeśli bez odpowiedzi), **Stan
  gałęzi** (hash, czy wypchnięte), **Lista wdrożenia P1** (Task 6 Step 5 w całości), **Co następny krok musi wiedzieć**: K6 —
  pełne przykłady JSON `desk` (obie jednostki), `postpone`, `realtime-token`, kody 409/400, `KSZTALT_ODPOWIEDZI_STOLU`, zachowanie
  bez brokera i stara appka (z curl-i Task 5, hash gałęzi do nagłówka kontraktu); K7 — lista wdrożenia, czasy odniesienia, nazwy
  trybów wyścigów do regresji po wdrożeniu, uwaga o pamięci podręcznej ustawień (jeśli nienaprawiona); K8 — znaleziska „Poza
  zakresem” z K1–K5 (`MIGRATION_PLAN.md` nieobecny w repo, `reset-configs` bez admina, `admin_routers.py` progi rangi,
  `priority_range`, `avg_priority`, `order_quantity` jako pisarz bez blokady, `reject_product_quantity` commituje w handlerze).
- [x] **Step 3: Werdykt** (ostatni akapit raportu, wytłuszczony): **„P1 GOTOWE DO WDROŻENIA”** wyłącznie gdy wszystkie DoD 1–9
  spełnione; inaczej **„P1 NIEGOTOWE — blokady:”** z numerowaną listą (każda: objaw, dowód — tryb/test/log, krok źródłowy K1–K4b,
  rekomendacja karty naprawczej). Uwagi nieblokujące (przekroczone progi czasów, pamięć podręczna ustawień, odstępstwa) w osobnej
  liście „Uwagi do decyzji Konrada przed K7”.
- [x] **Step 4: Commit i odpowiedź**
  ```bash
  git add -f docs/superpowers/plans/raporty/2026-10-05-priorytety-krok-K5-raport.md docs/superpowers/plans/2026-10-05-priorytety-krok-K5-przeglad-p1.md
  git commit -m "docs(priorytety): raport kroku K5 przeglad P1 z werdyktem" -m "<stopka atrybucji sesji>"
  ```
  Push wg karty (S-2). Jedna wiadomość do Konrada: werdykt, liczby wyścigów (przebiegi, 1213), hash.

---

## Kryteria zakończenia (DoD)

1. Pełny pakiet `tests/`: 0 failed (liczby przed i po w raporcie, różnica wyjaśniona); `integrations/blog_seo` zielony; składnia 3.9
   OK dla wszystkich `.py` zmienionych od `b4b4a54d` (lista z `git` na hoście, Task 1 Step 3).
2. Migracja `2026-10-05-priorytety-produkcji.sql`: na kontenerze `db` drugi i trzeci przebieg „Wykonano 0 migracji”; na kopii
   produkcji **bez `prod_routes`** pierwszy przebieg wykonał migracje logistyki przed priorytetami bez błędu, drugi „0 migracji”;
   na obu bazach 9 szczebli w kolejności 3.1, 38 wierszy `prod_config`, 5 kolumn `prod_orders`, FK szczebla do `prod_routes`.
   Pierwszy cron na kopii: `priorytety_utrwalone.success: true`, drugi: 0 zmian; rangi unikatowe.
3. Kolejka `GET /kolejka` i `GET /kolejka?stanowisko=gluing` na kopii zgodne z `scripts/symulacja_priorytetow.py` (ta sama
   kolejność; liczby w raporcie) albo rozbieżność zgłoszona jako blokada K1.
4. Wyścigi: 6 trybów obowiązkowych × 62 i 9 trybów K3 × 30 przebiegów wykonane; **0 × 1213 bez ponowienia, 0 × 500, 0 złamanych
   niezmienników** (`stol_bez_duplikatow`, `stol_bez_nieaktualnych`, `stol_bez_niekompletnych`, `rangi_zbiezne` wg definicji
   punktu stałego, Doprecyzowania p. 9); liczba 1213 z udanym ponowieniem w raporcie per tryb (spodziewana w `desk-zakoncz-inne`,
   `hurt-desk`, `odloz-hurt`, `desk-utrwal`; w innym trybie — uwaga z analizą, nie blokada, Doprecyzowania p. 12); przeplecenia
   `odloz-zakoncz-ten-sam-kafel`, rozkład `odloz-odloz` (limit miękki) i odpowiedź drugiego ZAKOŃCZ opisane. Albo: pierwsze 1213 → `INNODB STATUS` w katalogu poza repo
   i STOP z meldunkiem (wtedy DoD niespełnione, werdykt „niegotowe”).
5. `general_log`: kolejność zapytań `desk` i ZAKOŃCZ zgodna z K3 DoD 3 (`LOCK IN SHARE MODE` jako postać `FOR SHARE`;
   wyciąg w raporcie, bez danych klientów).
6. Oględziny Task 5 Step 1 p. 1–7 wykonane, konsola bez błędów JS, zrzuty poza repo wymienione; wszystkie wywołania curl z Step 2
   z oczekiwanymi kodami; sygnały z brokerem na właściwych kanałach, bez brokera 200 na akcjach i 503 na `/realtime-token`
   przy `enabled=false`.
7. Tabela czasów z progami (1 s / 300 ms / przyrost `utrwal`) w raporcie; przekroczenia jako uwagi z rekomendacją.
8. CLAUDE.md ma `### Priorytety produkcji`, dopiski w „Logistyka równoległa” i „Zadania cykliczne”, akapit pisarzy bez
   przeciągania/`set-priority`; spec ma sekcję 16, poprawione 4.3/13/9.4/6.1/9.1/5.2/9.2/9.3, 3.3 wg odpowiedzi na pytanie 3 K1
   (albo dopisek „do decyzji”) i skrót listy wdrożenia w 11;
   `tests/test_priorytety_dokumentacja.py` zielony.
9. Raport kroku zacommitowany z werdyktem, listą wdrożenia P1, sekcją „Co następny krok musi wiedzieć” (K6, K7, K8). `main`
   nietknięty; commity tylko na `claude/priorytety-produkcji`: 2 (Task 6, Task 7) + 0–n `fix(priorytety)` z Task 1. Podgląd
   przywrócony do trybu `stary`.

## Poza zakresem

- Wdrożenie, scalenie do `main`, cron na produkcji, przełączanie stanowisk, pomiar po P3 (K7). Kontrakt appki
  `docs/api-mobile-priorytety.md` i karta sesji appki (K6) — K5 daje im dane (curl-e, hash). Sprzątanie P4 (K8).
- Zmiany algorytmu, blokad, końcówek, UI (K1–K4b) — każda usterka tam = karta naprawcza, nie poprawka w K5 (poza regresją
  w zakresie z Task 1).
- Optymalizacja czasów (`utrwal` w tle, wspólne wyliczenie kandydatów w `widok`) — tylko rekomendacja w werdykcie.
- Naprawa pamięci podręcznej `ustawienia.*` (60 min) — jeśli K2 zostawił `xfail`, K5 zgłasza do decyzji, nie naprawia.
- Znaleziska spoza priorytetów (`MIGRATION_PLAN.md` nieobecny, `reset-configs` bez admina, `reject_product_quantity` commituje
  w handlerze, progi rangi w `admin_routers.py`/`modules/production/__init__.py`, `priority_range`, `avg_priority`) — raport, bez zmian.
- Regresja skryptów wyścigów 4.4a/4.4b, gdy ich nie ma pod ręką — pomijana z wpisem (centrala decyduje o K7).

## Ryzyka i co robić przy blokadzie

| Ryzyko | Objaw | Co robić |
|---|---|---|
| K4a/K4b niescalone albo `origin/claude/logistyka-etap-4`/`origin/main` poszły do przodu | Task 1 Step 0 | **STOP**, centrala zleca scalenie; K5 rusza od nowa po nim |
| Brak zrzutu produkcji albo zrzut z już wykonaną logistyką | wariant „bez `prod_routes`” niesprawdzalny | wykonaj wariant dostępny, wpisz w „Odstępstwa” i uwagach werdyktu; kolejność nazw w runnerze pokryta `tests/test_migration_service.py` |
| Migracja pada na kopii (składnia MySQL 8.4 produkcji, kolacja, FK) | log startu podglądu / `flask migrate` exit 1 | **STOP** — błąd K1, meldunek z pełnym komunikatem (bez danych), bez poprawki na własną rękę |
| Start podglądu na kopii migruje „za plecami” (`RUN_MIGRATIONS`) | brak protokołu pierwszego przebiegu | to jest pierwszy przebieg — zapisz `docker logs`; nigdy nie podłączaj podglądu do bazy produkcyjnej |
| 1213 w wyścigu bez ponowienia, 500, zdublowany/niekompletny kafel | `_wyscigi_k5.jsonl`, licznik InnoDB, log | Task 4 Step 4: `INNODB STATUS`, dokończ serię, **STOP**, meldunek (podręcznik 4a p. 3: analiza na Fable 5.1 max). Werdykt „niegotowe” |
| 1213 z udanym ponowieniem częściej niż „rzadko” (np. > 10 % serii `desk-zakoncz-inne`) | tablety czekają na ponowienie, log WARNING często | nie blokada, ale uwaga w werdykcie z częstością i hipotezą (luka indeksu stołu); rekomendacja analizy w karcie naprawczej K3 |
| Kolejność z `general_log` inna niż w planie K3 | np. pozycje przed zamówieniami w `dopelnij` | **STOP** (K3 Ryzyka), wyciąg logu w meldunku |
| Rozbieżność kolejki panelu z symulacją | inne miejsca tych samych zamówień | sprawdź `--dzis`, próg, trasy/gwiazdki na kopii; prawdziwa różnica → test tabelą w `tests/test_priorytety_kolejka.py`, STOP, karta K1 |
| Brak brokera w dockerze (obraz niedostępny, port zajęty) | `realtime-token` 503, sygnały niesprawdzalne | spróbuj innego portu; jeśli nie — Review Focus 4 pozostaje na testach SQLite K3 + `REALTIME.enabled=false`; odstępstwo i uwaga dla K7 („sprawdzić sygnał na produkcji po wdrożeniu”) |
| Pamięć podręczna `ustawienia.*` (60 min) na podglądzie | zmiana trybu nie działa od razu | restart podglądu po `PUT /ustawienia`; uwaga do werdyktu i rekomendacja karty naprawczej przed K7 część 2 |
| Czasy ponad progami na kopii (~250 zamówień) | `GET /kolejka` > 1 s, `desk` > 300 ms, akcja trasy + `utrwal` wyraźnie dłuższa | liczby do raportu, rekomendacja (cache kandydatów, `utrwal` w tle); nie optymalizować w K5 |
| Pełny pakiet pada na teście spoza priorytetów | np. logistyka po zmianie `with_idempotency` | przyczyna w przepięciu K1/K3 → naprawa w Task 1 tylko gdy nie zmienia kontraktu; inaczej STOP, karta naprawcza do kroku źródłowego |
| Dane klientów w zrzutach ekranu/raporcie/skryptach | — | zrzuty poza repo; raport z numerami zamówień i wymiarami tylko; `grep -i` nazwisk/miast przed commitem raportu |
| Dwa pełne pakiety naraz (K5 + inna sesja) | OOM, exit 137 | jeden pakiet naraz; uzgodnić z centralą, czy inna sesja pracuje |
| `core.json` podglądu z prawdziwym kluczem Base./Sentry | zmiany statusów i sposobu dostawy w prawdziwym koncie Base. z danych kopii; zdarzenia podglądu w Sentry produkcji | sprawdzenie nazw pól przed pierwszym startem (Global Constraints); gdy klucz był ustawiony choć przez chwilę — STOP, meldunek do centrali i Konrada (sprawdzić w Base. zamówienia z kopii) |
| Budżet jednej sesji (≈ 640 przebiegów wyścigów, 2 pełne pakiety, oględziny, dokumentacja) | sesja kończy się przed Task 7 | kolejność ważności: Task 1 → 2 → 4 Step 1 (obowiązkowe) → 6 → 7 z werdyktem „niegotowe — niedokończone: …”; serie K3, regresja 4.4a/4.4b i oględziny do karty kontynuacji K5 (centrala), nigdy pominięte bez wpisu |

**STOP** = zatrzymanie pracy w danym Tasku, opis w raporcie („Odstępstwa”/„Pytania”), bez wyłączania testów i bez zmian poza
planem, meldunek do centrali z rekomendacją; pozostałe Taski niezależne (np. dokumentacja) można dokończyć, a werdykt brzmi
„niegotowe — blokady”.

## Pytania do Konrada

**Blokujące start (zbiera centrala przed kartą):**
1. **Zrzut bazy produkcyjnej** (`mysqldump --single-transaction`, bez tabel sesji, bez danych w repo) — skąd i kiedy; bez niego
   odpada połowa Task 2 (migracja na kopii, porównanie z symulacją, czasy na realnych danych, `desk-utrwal`). Jeśli produkcja ma
   już wdrożoną logistykę, wariant „bez `prod_routes`” sprawdza się tylko kolejnością nazw w runnerze. Rekomendacja: zrzut z dnia
   startu K5 na katalog podglądów (S-3), skasowany po raporcie.

**Do potwierdzenia przy bramce (plan przyjmuje wartości domyślne):**
2. Broker Centrifugo jako kontener dockera na podglądzie z losowymi kluczami (nigdy produkcyjny) — tak.
3. Przekroczenie progów czasów (1 s / 300 ms) to uwaga do decyzji, nie blokada P1 — tak (Doprecyzowania p. 5).
4. Regresja skryptów wyścigów 4.4a/4.4b wymaga dostępu do katalogu podglądów logistyki — jeśli go nie ma, pomijamy i K7 nie
   nadrabia (nowy pisarz `utrwal` idzie zamówienia → pozycje, zgodnie z łańcuchem).
