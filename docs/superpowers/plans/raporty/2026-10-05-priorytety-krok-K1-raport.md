# Raport kroku K1 „fundament rangi” — program „Priorytety produkcji”

- **Plan:** `docs/superpowers/plans/2026-10-05-priorytety-krok-K1-fundament-rangi.md` (wszystkie kroki odhaczone `- [x]`)
- **Spec:** `docs/superpowers/specs/2026-10-04-priorytety-produkcji-design.md`
- **Gałąź:** `claude/priorytety-produkcji`, baza `f731b77c` (jak w karcie; DoD p. 1 czytane względem tej bazy)
- **Data:** 2026-10-05. **Sesja:** lokalna, model Fable 5.1 (`claude-fable-5-1`), bez trybu szybkiego. Na samym starcie
  środowisko przedstawiło sesję jako Opus 5.5 i po pierwszym poleceniu poprawiło na Fable 5.1 — cała praca nad kodem
  szła na Fable 5.1. Przegląd końcowy gałęzi: osobny agent, też Fable 5.1.

## Zrobione (po Taskach)

| Task | Commit | Co weszło |
|---|---|---|
| 1 | `611f1fd5` | Migracja `migrations/2026-10-05-priorytety-produkcji.sql` dla CAŁEGO P1 (5 kolumn `prod_orders` + indeks rangi, `prod_priority_rungs`, `prod_priority_log`, `prod_station_desk`, 9 szczebli, 38 wierszy `prod_config`). Pakiet `modules/production/priorytety/` bez blueprintu: `stale.py`, `models.py` (`PriorityRung`, `PriorityLog`, `StationDesk`), `services/ustawienia.py`. Kolumny na `ProductionOrder`, import modeli w `modules/production/__init__.py`. Fixtury testów z nowymi tabelami, `tests/priorytety_fixtures.py`. |
| 2 | `045cb5cd` | `services/kolejka.py`, część czysta: `policz(migawka)` i `kandydaci_stanowiska(...)` z pomocniczymi (`termin_zamowienia`, `tagi_zamowienia`, `rozpoczete`, `dodaj_dni_robocze`, `kompletne_na_stanowisku`, `klucz_zamowienia`). Tabela 3.3 specu, przykład Konrada (dąb 4 cm przed 3 cm) i X/Y jako testy. |
| 3 | `28296ff0` | `services/drabina.py` (`szczeble`, `wszystkie_do_zapisu`, `miejsce_domyslne`, `zapewnij_szczebel_trasy`, `usun_szczebel_trasy`, `przesun`, `uzupelnij`, `pozycja_tagu`, `pozycja_szczebla`, `BladDrabiny`). `routes.utworz` zakłada szczebel pod trzymaną blokadą tras, `routes.usun` go usuwa i renumeruje. |
| 4 | `b3e6e11f` | `kolejka.utrwal()` na własnej sesji (migawka → zamówienia `FOR UPDATE` rosnąco → pozycje tych zamówień rosnąco → zapis tylko zmienionych → commit; jedno ponowienie po 1213; nigdy nie rzuca, nie dotyka `db.session`), `utrwal_po_commicie`, `zaplanuj_po_commicie` / `porzuc_zaplanowane` / `wykonaj_zaplanowane`. `services/gwiazdki.py` (`ustaw`, `BladGwiazdek`). `priority_service` jako warstwa zgodności (`WarstwaZgodnosciPriorytetow`), delegacja singletonu w `services/__init__.py`, log w `sync_service`. |
| 5 | `15193a6c` | `DEADLINE_DAY_TYPE` w `_calculate_deadline_date` (tylko przy nadawaniu terminu), wartość domyślna w `config_service`. Doróbka: `priority_rank=0`, `is_priority=True` w konstruktorze, bez `lock_priority`. `lock_priority`/`unlock_priority` puste, `complete_task` nie kasuje rangi doróbki (wpis `prod_rework_log` zamyka jak dotąd). |
| 6 | `2514594e` | Wyzwalacze po commicie: `trasy_api` (`_akcja`, utworzenie i usunięcie trasy), `panel_api` logistyki (sposób dostawy, „Wydane klientowi”), `products_api` (zmiany z Base., hurtowa zmiana statusu). Telefon kierowcy (`dostawa_api._zapis`) i „Cofnij do pakowania” (`weryfikacja_api`) planują, `with_idempotency` wykonuje po commicie. Cron logistyki: faza priorytetów (`szczeble_uzupelnione`, `priorytety_utrwalone`) po uruchomieniu wątków w tle. |
| poprawki po przeglądzie | `f2a7a6cc` | Przebieg kontrolny `utrwal` po zapisie (dwa przeliczenia naraz nie zostawiają mieszanki rang), licznik zapisów sprzed commitu w fiksturze `szpieg_utrwal` — sekcja „Przegląd końcowy gałęzi i runda poprawek”. |
| 7 | (ten commit) | Raport kroku. |

Nazwy z sekcji „Interfaces” planu (DoD p. 3) — `grep -n "^def \|^class "` bez funkcji prywatnych:

- `stale.py`: `klucz_tryb`, `klucz_stol`, `klucz_jednostka`, `klucz_limit`, `klucz_blokady` + stałe (`STATUSY_PRODUKCJI`,
  `STATUSY_ZROBIONE`, `ETAP_STATUSU`, `ETAP_STANOWISKA`, `STANOWISKA`, `STANOWISKA_ZAMOWIENIOWE`, `TAG_*`, `TAGI`,
  `RODZAJE_SZCZEBLA`, `GWIAZDKI_MAX`, `DRABINA_DOMYSLNA`, `POWODY_ODLOZENIA`, `JEDNOSTKI`, `TRYBY`, `AKCJE_LOGU`, `TYPY_DNI`,
  `STOL_K`, `LIMIT_ODLOZEN`, `BLISKO_TERMINU_DNI`, `MIN_APP_VERSION_CODE`, `DEADLINE_DAY_TYPE_DOMYSLNY`, `LIMIT_HURTU`,
  `KLUCZ_BLISKO`, `KLUCZ_MIN_APP`, `KLUCZ_TYP_DNI`; ponad plan: `STATUSY_TRASY_NA_DRABINIE`, `STATUSY_POZA_KOLEJKA`,
  `MNOZNIK_RANGI`).
- `models.py`: `PriorityRung`, `PriorityLog`, `StationDesk`.
- `services/ustawienia.py`: `tryb`, `miejsca`, `jednostka`, `limit`, `prog_blisko`, `min_app_version`, `typ_dni_terminu`,
  `klucz_blokady`.
- `services/kolejka.py`: `dodaj_dni_robocze`, `termin_zamowienia`, `rozpoczete`, `tagi_zamowienia`, `kompletne_na_stanowisku`,
  `klucz_zamowienia`, `policz`, `kandydaci_stanowiska`, `dzis`, `nowa_sesja`, `utrwal`, `utrwal_po_commicie`,
  `zaplanuj_po_commicie`, `porzuc_zaplanowane`, `wykonaj_zaplanowane`; struktury `Migawka`, `Zamowienie`, `Pozycja`, `Trasa`,
  `Szczebel`, `Wynik`, `RangaZamowienia`, `PozycjaStanowiska`, `Kandydaci`; prywatny loader `_migawka(sesja)` (woła go K2).
- `services/drabina.py`: `BladDrabiny`, `szczeble`, `wszystkie_do_zapisu`, `miejsce_domyslne`, `zapewnij_szczebel_trasy`,
  `usun_szczebel_trasy`, `przesun`, `uzupelnij`, `pozycja_szczebla`, `pozycja_tagu`.
- `services/gwiazdki.py`: `BladGwiazdek`, `ustaw`.

Pakiet nie ma `routers/`, `templates/`, `static/`, `stol.py`, `sygnaly.py`; `__init__.py` bez blueprintu.

## Testy (polecenia i wyniki)

Polecenie testów (karta, Start 4), z katalogu worktree:
`docker compose -p priorytety run --rm --no-deps app pytest <ścieżki> -q -p no:cacheprovider`.

| Co | Wynik |
|---|---|
| Punkt wyjścia, pełny pakiet na `f731b77c` | **6061 passed, 3 skipped**, 0 failed (7 min 39 s) |
| Pełny pakiet po Tasku 6 (`2514594e`) | **6202 passed, 3 skipped**, 0 failed (6 min 50 s) |
| Pełny pakiet po rundzie poprawek (`f2a7a6cc`) | **6205 passed, 3 skipped**, 0 failed |
| `integrations/blog_seo` (`cd integrations/blog_seo && python -m pytest`) | 89 passed |
| Task 1: `test_priorytety_ustawienia`, `test_migracja_priorytety`, `test_migration_service`, `test_logistyka_trasy_serwis`, `test_blokady_zamowien`, `test_produkty_masowa_zmiana_statusu` | 171 passed |
| Task 2: `test_priorytety_kolejka`, `test_priorytety_ustawienia` | 50 passed |
| Task 3: `test_priorytety_drabina` + 10 plików z planu wołających `routes.utworz` + cztery pliki z własnymi tabelami | 489 passed |
| Task 4: `test_priorytety_kolejnosc_zapisow`, `test_priority_statusy_krawedzi`, `test_priorytety_gwiazdki`, `test_sales_ingest_wyzwalacze` | 93 passed; `tests/test_sales_ingest_wyzwalacze.py` **bez zmian w pliku** |
| Task 5: `test_priorytety_terminy`, `test_priorytety_dorobka`, `test_routing_krawedzie`, `test_blokady_dorobka_base`, `test_dorobka_dalsze_stanowiska`, `test_dorobka_trasa_krawedzi`, `test_dostawa_dorobka_na_trasie`, `test_sync_flaga_krawedzi` | 95 passed |
| Task 6: `test_priorytety_wyzwalacze`, `test_priorytety_wyzwalacze_produkty`, `test_logistyka_cron`, `test_logistyka_trasy_api`, `test_dostawa_api`, `test_dostawa_ponowienie_1213`, `test_blokady_zamowien`, `test_produkty_masowa_zmiana_statusu`, `test_blokady_dorobka_base`, `test_weryfikacja_problem`, `test_weryfikacja_akcje`, `test_weryfikacja_przeglad_backendu`, `test_logistyka_panel_api` | 371 passed |

**Bilans testów:** 6061 + 129 (nowe pliki) + 19 nowych − 4 usunięte (w `tests/test_priorytety_kolejnosc_zapisow.py`) = 6205
(po Tasku 6 było 6202; runda poprawek po przeglądzie dodała 3 testy).

- Nowe pliki (129): `test_migracja_priorytety` 9, `test_priorytety_ustawienia` 13, `test_priorytety_kolejka` 37,
  `test_priorytety_drabina` 27, `test_priorytety_gwiazdki` 13, `test_priorytety_terminy` 7, `test_priorytety_dorobka` 4,
  `test_priorytety_wyzwalacze` 17, `test_priorytety_wyzwalacze_produkty` 2.
- `tests/test_priorytety_kolejnosc_zapisow.py`: było 14, jest 29. **Usunięte** (testy dawnego kalkulatora):
  `test_przeliczenie_priorytetow_zapisuje_pozycje_jednym_flushem_rosnaco`,
  `test_przeliczenie_ponawia_raz_po_1213_na_nowej_sesji`, `test_przeliczenie_dwa_1213_z_rzedu_bez_zapisow`,
  `test_przeliczenie_inny_kod_bez_ponowienia`. **Zostawione dla K2**: 10 testów przeciągania (`update-priority`).
- Przemianowany: `test_kalkulator_zna_obie_kolejki_po_rozdziale` → `test_stale_statusy_produkcji_znaja_obie_kolejki`
  (`tests/test_priority_statusy_krawedzi.py`); `test_nieudane_przeliczanie_priorytetow_czysci_sesje` w tym pliku został
  bez zmian na `NewPriorityCalculator`.
- Zmieniony: `tests/test_routing_krawedzie.py::test_domkniecie_dorobki_na_formatowaniu_dziala_dalej` (ranga 0 i ramka
  doróbki zostają po Formatowaniu — decyzja specu 9.5).

**Testy mutacyjne** (dowód, że testy z Review Focus łapią odwrócenie reguły; skrypty poza repo):
część czysta 6/6 (trasa nie decyduje, gwiazdki za grupą, długość przed terminem, grupy bez najbliższego terminu,
„Rozpoczęte” bez podnoszenia, brak tagu „Po terminie”), część z bazą 12/12 (pozycje blokowane przed zamówieniami,
zamówienia bez `FOR UPDATE`, blokada wszystkich aktywnych, blokady przy braku zmian, próg przez `db.session`,
`manual_override` zostaje, ranga dla pozycji poza produkcją, brak ponowienia po 1213, ponowienie po każdym błędzie, trzy
próby, pozycje nieaktywne liczone, log przeliczenia zawsze). Pierwszy przebieg wykazał, że test przykładu X/Y nie
odróżniał „wskakuje na szczebel tagu” od „pierwsze w swoim szczeblu” — test wzmocniony o zamówienie ★★★.

**Migracja ×2 na MySQL** (baza `priorytety_podglad` w kontenerze `db`, kopia `logistyka4_podglad`; polecenie z karty):

- `flask migrate-status` sam wykonuje migracje przy starcie aplikacji (`create_app` → `RUN_MIGRATIONS`), więc pierwsze
  wykonanie poszło już przy nim: `✓ 2026-10-05-priorytety-produkcji_2026-10-05-priorytety-produkcji.sql [success]`.
- `flask migrate` #1: `Brak nowych migracji do wykonania`, `Wykonano 0 migracji.` `flask migrate` #2: to samo.
- Ponieważ runner nie wykonuje pliku drugi raz, idempotencję samego SQL sprawdziłem dodatkowo: na własnej bazie usunąłem
  wpis `schema_migrations`, zmieniłem próg „Blisko terminu” na 4 i przestawiłem dwa szczeble (jak biuro), po czym plik
  wykonał się ponownie: `✓ Sukces`, liczby bez zmian, próg został 4, szczeble zostały na nowych pozycjach. Wartości
  przywrócone.

Zapytania kontrolne po migracji (DoD p. 2):

| Kontrola | Wynik |
|---|---|
| kolumny `priority%` na `prod_orders` | 5 (`priority_stars tinyint NOT NULL DEFAULT 0`, `priority_stars_set_at datetime NULL`, `priority_stars_set_by int NULL`, `priority_rank int NULL` z indeksem, `priority_rung int NULL`) |
| indeks `ix_prod_orders_priority_rank` | 1 |
| nowe tabele | 3 (`prod_priority_rungs`, `prod_priority_log`, `prod_station_desk`); tabel w bazie 91 → 94 |
| szczeble | 9, w kolejności 3.1: ★5, po_terminie, ★4, blisko_terminu, rozpoczete, ★3, ★2, ★1, ★0 (`position` 1..9) |
| wiersze `prod_config` (`priorytety_%` + `DEADLINE_DAY_TYPE`) | 38 |
| `SHOW CREATE TABLE prod_priority_rungs` | `UNIQUE KEY uq_…_stars (kind, stars)`, `uq_…_tag (kind, tag)`, `uq_…_route (route_id)`, `CONSTRAINT fk_…_route FOREIGN KEY (route_id) REFERENCES prod_routes (id) ON DELETE CASCADE`, `ENGINE=InnoDB … utf8mb4_unicode_ci` |

**`utrwal()` na MySQL** (ponad plan — SQLite nie sprawdza MySQL-a; ta sama baza, same liczby zbiorcze):
`drabina.uzupelnij()` dopisał 5 szczebli tras roboczych/zatwierdzonych (drugi raz 0). `utrwal()` #1: 156 zamówień
aktywnych, 318 pozycji, wszystko zmienione, **0,218 s**; kolejność zapytań blokujących i zapisów: `prod_orders … FOR UPDATE`
→ `prod_products … FOR UPDATE` → `UPDATE prod_orders` → `UPDATE prod_products`. `utrwal()` #2: bez zmian, **0,02 s**, zero
blokad i zapisów. Po przebiegu: rangi zamówień 1..156 bez duplikatów i bez braków, pozycje zgodne z „ranga × 100 +
kolejność”, doróbki z rangą 0, `priority_manual_override` wyzerowane na pozycjach aktywnych.

**Cykl importów** (Review Focus 9), świeże procesy: `import modules.production.priorytety.models`;
`…services.drabina, …services.kolejka`; `modules.production.logistics.routers.trasy_api`; dodatkowo `gwiazdki`,
`ustawienia`, cztery pozostałe routery logistyki, `mobile_api_service`, `products_api` — wszystkie bez błędu.
`from app import create_app; create_app()` na `priorytety_podglad` — bez błędu.

**`utrwal()` na MySQL po rundzie poprawek** (rangi dziesięciu zamówień zepsute jak cudzym zapisem): kolejność zapytań
6 odczytów → blokada `prod_orders` → blokada `prod_products` → `UPDATE prod_orders` → `COMMIT` → 6 odczytów
(przebieg kontrolny) → `ROLLBACK`; 0,204 s. Przeliczenie bez zmian: 6 odczytów → `ROLLBACK`, 0,015 s, zero blokad.
Rangi aktywnych po przebiegu: 1..156, 156 różnych.

**Składnia Python 3.9:** `python:3.9-slim` (3.9.25), `ast.parse(..., feature_version=(3, 9))` + `compile` dla 46 plików
`.py` zmienionych i nowych od `f731b77c` — 0 błędów; brak `X | Y` w adnotacjach dodanych linii poza plikami
z `from __future__ import annotations`, brak `match`.

## Odstępstwa od planu

1. **Polecenia środowiska** wg karty (Start 4), nie wg planu (`docker compose exec app …`): testy przez
   `docker compose -p priorytety run`, migracja i przebiegi na MySQL przez `docker run … logistyka3-app` z `core.json`
   montowanym plikowo, baza `priorytety_podglad`.
2. **Testy wyzwalaczy w dwóch plikach**: `tests/test_priorytety_wyzwalacze.py` (aplikacja logistyki) i
   `tests/test_priorytety_wyzwalacze_produkty.py` (aplikacja API produkcji — hurt statusu i zmiany z Base.). Obie
   fikstury nazywają się `app`.
3. **Izolacja od `utrwal` po commicie w trzech istniejących testach** (plan przewidział dwa), asercje bez zmian:
   - `tests/test_logistyka_cron.py::test_cron_przenosi_osierocone_z_logistyki_do_pakowania` (`kolejka.utrwal`),
   - `tests/test_produkty_masowa_zmiana_statusu.py::test_hurt_ponowienie_blokuje_zamowienia_i_pozycje_od_nowa`
     (`kolejka.utrwal_po_commicie`),
   - `tests/test_logistyka_panel_api.py::test_hurt_laduje_pozycje_jednym_zapytaniem` (`kolejka.utrwal_po_commicie`;
     liczy `SELECT`-y pozycji w całym żądaniu).
4. **Plan odsyłał do fixtury `bez_statusow_base` w `tests/test_blokady_dorobka_base.py`** — takiej tam nie ma i nie jest
   potrzebna (doróbka nie woła Base.).
5. **Fixtury z nowymi tabelami** (`PriorityRung`, `PriorityLog`, `StationDesk`): `tests/logistyka_fixtures.py`,
   `tests/krawedzie_fixtures.py`, `tests/test_dorobka_dalsze_stanowiska.py`, `tests/test_dorobka_trasa_krawedzi.py`,
   `tests/test_mobile_api_alias_krawedzi.py`, `tests/test_worker_profiles.py` — zgodnie z planem, bez dodatkowych.

Pozostałe różnice wobec litery planu to rozstrzygnięcia niżej.

## Rozstrzygnięcia podjęte w trakcie (koszt, jeśli błędne)

1. **Ustawienia liczbowe mają dolne granice** (miejsca ≥ 1, limit ≥ 1, próg ≥ 0, wersja appki ≥ 0); poza nimi wartość
   domyślna i ostrzeżenie w logu. Stół z zerem miejsc zamroziłby stanowisko. Koszt: żaden — K2 waliduje to samo przy zapisie.
2. **Migracja ma jawne indeksy** `prod_station_desk` na `station_code`, `order_id`, `product_id` (jak `index=True` modeli).
   Koszt: żaden.
3. **`stale` dostały trzy stałe ponad plan**: `STATUSY_TRASY_NA_DRABINIE = ('robocza', 'zatwierdzona')`,
   `STATUSY_POZA_KOLEJKA = ('anulowane', 'wstrzymane')`, `MNOZNIK_RANGI = 100`; `PriorityRung.klucz` (property). Koszt: żaden.
4. **Numer zamówienia porządkowany liczbowo**, gdy to same cyfry (9999 przed 10000), inaczej tekstowo. Koszt: jedna funkcja.
5. **Kolejność pozycji w randze przycięta do 0..99** — „ranga × 100 + kolejność” nie może wejść w numerację następnego
   zamówienia (limit konfiguracji to 999 pozycji). Koszt: pozycje powyżej 99. jednego zamówienia mają tę samą rangę.
6. **`kandydaci_stanowiska` ma opcjonalny piąty parametr `jednostka=None`** (None = jak w planie: Formatowanie
   i Pakowanie zamówieniowe). Jednostka jest ustawieniem stanowiska, więc K3 może przekazać `ustawienia.jednostka(S)` bez
   zmiany K1. Koszt: żaden (zgodne wstecz).
7. **Kafle-zamówienia: zamówienie z doróbką na tym stanowisku idzie pierwsze** (po `created_at` doróbki) — spec 3.2
   „doróbki zawsze pierwsze na każdym stanowisku”; plan rozpisał to tylko dla kafli-pozycji. Koszt: dwa wiersze klucza.
8. **`RangaZamowienia.tagi` to krotka w kolejności `stale.TAGI`** (`tagi_zamowienia` zwraca zbiór, jak w planie);
   gwiazdki puste albo spoza 0..5 są przycinane; jedno ostrzeżenie na każdy brakujący szczebel stały; szczeble wirtualne
   tylko dla tras z zamówieniami w produkcji, rosnąco po id trasy (tak samo dopisuje je `drabina.uzupelnij`). Koszt: żaden.
9. **`termin_zamowienia` przyjmuje obiekty ze statusem w `status` (migawka) albo `current_status` (model)** — K3 może
   podać pozycje ORM. Koszt: żaden.
10. **Test tabeli 3.3 ma tag „Rozpoczęte” jako dwunasty szczebel** (przykład specu powstał przed tym tagiem; numeracja
    1–11 bez zmian). Koszt: żaden.
11. **Pozycje w logu `szczebel` i w komunikacie zakresu to indeksy wśród szczebli widocznych** (to widzi biuro), nie
    kolumna `position`; dla szczebla tagu `note` = kod tagu. Koszt: dwa wyrażenia.
12. **`drabina.przesun`**: przesunięcie na tę samą pozycję niczego nie zapisuje (bez wpisu logu); `pozycja` musi być
    liczbą całkowitą (`True`, `'2'`, `2.0` → `pozycja_poza_zakresem`). Koszt: K2 musi podać liczbę z JSON.
13. **`drabina.pozycja_szczebla` zwraca `None` dla szczebla ukrytego**; `pozycja_szczebla` i `pozycja_tagu` mają opcjonalne
    `widoczne=` (bez ponownego odczytu w pętli). Koszt: żaden.
14. **Statusy tras przy zapisie drabiny czytane odczytem bieżącym (`FOR SHARE`)**: `route_create` woła `routes.utworz` bez
    commita przed blokadą tras, więc zwykły `SELECT` widziałby migawkę sprzed blokady. `szczeble(aktualny=True)` blokuje
    też wiersze tras ze złączenia — pod blokadą tras bez ryzyka. Koszt: żaden.
15. **`drabina.uzupelnij`**: brak szczebla stałego → ostrzeżenie w logu aplikacji, dopisany szczebel trasy → wpis
    informacyjny; `miejsce_domyslne` na drabinie bez ★★★★★ → góra. Koszt: żaden.
16. **„Dziś” przeliczenia to funkcja `kolejka.dzis()`**; testy ją zamrażają (`zamrozony_dzien`, 5.10.2026), inaczej
    terminy wpisane w testach zaczęłyby z czasem łapać tagi. Koszt: żaden.
17. **`utrwal(zrodlo=…)` zapisuje wpis `przeliczenie` także wtedy, gdy nic się nie zmieniło** (`new_value='0'`).
    Pseudokod planu wracał przed logiem, tekst planu mówi „gdy dostanie źródło”; ręczne kliknięcie ma zostawić ślad. Wpis
    nie ma `order_id`, więc nie bierze blokad. Koszt: jeden warunek.
18. **Pozycja, która między migawką a blokadą wyszła z produkcji, nie dostaje rangi** (sprawdzenie statusu na obiekcie
    z odczytu blokującego). Koszt: żaden.
19. **Odczyty blokujące `utrwal` czytają tylko potrzebne kolumny** (`load_only`): zamówienie niesie etykietę kuriera,
    pozycja rysunki SVG. Kształt zapytań blokujących bez zmian. Koszt: żaden.
20. **`updated_at` pozycji podbijany przy każdej zmianie** (ranga, `is_priority` albo wyzerowanie `manual_override`).
    Koszt: żaden.
21. **Warstwa zgodności dokłada też stary klucz `products_processed`.** Koszt: żaden.
22. **Tryb kalendarzowy liczy `data + max(dni, 0)`.** Koszt: żaden.
23. **`unlock_priority()` puste zostawia `priority_manual_override=True`** (plan: „ciała puste”); zaszłości zeruje
    wyłącznie `kolejka.utrwal()`. Koszt: żaden.
24. **Wyzwalacze w routerach przez małe funkcje z importem lokalnym** (`_utrwal_priorytety` w `trasy_api` i `panel_api`,
    `_kolejka_priorytetow` w `dostawa_api`, `_priorytety` w `cron_api`). Koszt: żaden.
25. **Powtórka zapisu Dostawy bez zmian (`changed: false`) też planuje przeliczenie** — bez zmian to same odczyty. Koszt: żaden.
26. **Test „zmiany z Base. utrwalają” podmienia `BaselinkerSyncService.apply_baselinker_changes`** (zapis i commit
    w atrapie) i mierzy okablowanie końcówki. Koszt: żaden.

## Przegląd końcowy gałęzi i runda poprawek

Po Tasku 6 całą gałąź (`f731b77c..2514594e`) przejrzał niezależny agent ze świeżym kontekstem (plan, spec, reguły
blokad z CLAUDE.md, każde miejsce wywołania `utrwal`, migracja, testy). Wynik: **0 krytycznych, 3 ważne, 8 drobnych**;
werdykt „gotowe jako baza K2 po poprawkach”. Potwierdził m.in. brak cyklu blokad `utrwal` z ZAKOŃCZ, hurtem, Dostawą,
Weryfikacją, doróbką i gwiazdkami, poprawność wszystkich wyzwalaczy (po commicie) i kompletność nazw z „Interfaces”.

**Ważne — naprawione w commicie `f2a7a6cc`** (każde: test najpierw czerwony, potem zielony, mutacje, pełny pakiet):

- **I3. Licznik „po commicie” w testach nie widział zflushowanej, niezatwierdzonej transakcji** (sprawdzał tylko
  `db.session.new/dirty/deleted`, puste także po `flush()`). Fikstura `szpieg_utrwal` liczy teraz zapisy na silniku od
  ostatniego commitu albo rollbacku. Test: `test_szpieg_utrwal_wykrywa_zflushowany_niezatwierdzony_zapis`. Mutacje
  (przeliczenie przesunięte przed commit w `trasy_api` ×2, `panel_api`, `weryfikacja_api`): 4/4 złapane — wcześniej
  przeszłyby niezauważone.
- **I1. Dwa przeliczenia naraz mogły zostawić mieszankę dwóch rankingów** (migawka poprzedza blokady, a zapis obejmuje
  tylko wiersze różne na tej migawce). `utrwal` po każdym zapisie czyta teraz migawkę od nowa i poprawia różnice, aż
  przebieg kontrolny nie znajdzie żadnej (najwyżej 3 przebiegi, potem ostrzeżenie w logu). Testy:
  `test_utrwal_po_zapisie_sprawdza_rangi_na_swiezej_migawce`,
  `test_utrwal_konczy_po_trzech_przebiegach_gdy_stan_ciagle_sie_zmienia`; asercja „od pierwszego zapisu do commitu
  same zapisy, po commicie same zwykłe odczyty” w `test_utrwal_zapisuje_tylko_zmienione_rosnaco_po_id`. Mutacje 2/2.
  **Inaczej niż proponował przegląd** (wiersz blokady w `prod_config` brany przed migawką): tamto zmieniałoby spec 9.4
  („`utrwal` nie bierze innych blokad”), test planu „przeliczenie bez zmian nie bierze blokad” i liczbę 38 wierszy
  migracji. Przebieg kontrolny niczego z tego nie rusza: przeliczenie bez zmian to dalej jeden przebieg samych odczytów.
  Koszt: jeden dodatkowy odczyt (ok. 0,02 s) po każdym przeliczeniu, które coś zapisało; `zmienione_*` w raporcie to
  suma zapisanych wierszy ze wszystkich przebiegów. Koszt, jeśli to za mało: gdy dane zmieniają się szybciej niż trzy
  przebiegi, rangi czekają na następne przeliczenie — wtedy zostaje wiersz blokady (decyzja centrali, wyścigi w K5).

**Ważne — NIE naprawione, do decyzji centrali:**

- **I2. Warunek wstępny `utrwal` jest tylko opisany, a `sync_service` może go złamać.** Pętla importu ma gałęzie, które
  zostawiają w `db.session` zflushowany, niezatwierdzony zapis zamówienia (opisuje to komentarz w samym `sync_service`).
  Dla NOWEGO zamówienia kolizji nie ma. Gdy jednak ręczna synchronizacja z `force_update` przerabia istniejące aktywne
  zamówienie, wszystkie jego pozycje padają i jest ono ostatnie w partii, `utrwal` (drugie połączenie tego samego
  wątku) czeka na blokadę tego zamówienia do limitu serwera (50 s), a gunicorn ubija żądanie po 30 s. Stary kalkulator
  nie blokował zamówień, więc to nowe ryzyko — wąskie: CLAUDE.md opisuje tę ścieżkę jako dziś nieaktywną.
  Nie naprawiałem, bo każda naprawa to mechanizm sesji MySQL, którego pakiet na SQLite nie sprawdzi, z decyzjami do
  podjęcia: (a) krótki limit czekania na blokadę we własnej sesji `utrwal` (np. 5 s; połączenie trzeba potem odłączyć od
  puli albo przywrócić mu ustawienie) — przeliczenie pada szybko, cron nadrabia; (b) znacznik „`db.session` ma
  niezatwierdzony zapis” i natychmiastowa odmowa — ale wtedy po imporcie z błędną ostatnią pozycją rangi nowych zamówień
  czekają do crona. Rekomendacja: (a), razem z wyścigiem „`utrwal` przy niezatwierdzonym zapisie zamówienia” w K5 albo
  jako pierwszy krok K2. Do tego czasu chroni test: każdy nowy wyzwalacz sprawdzany licznikiem `szpieg_utrwal` (I3)
  wykryje wywołanie przed commitem. Koszt, jeśli zostanie: zawieszone żądanie ręcznej synchronizacji w opisanym
  przypadku.

**Drobne — odnotowane, bez zmian w kodzie:**

- M1. `ProductionOrder.priority_stars` ma `default=0` bez `server_default` — bazy zakładane przez `create_all` (testy,
  lokalne `setup-db`) nie mają wartości domyślnej w kolumnie, inaczej niż po migracji.
- M2. Cron: wyjątek w `drabina.uzupelnij()` pomija `utrwal()` w tej godzinie (tak chciał plan); nieudane przeliczenie
  loguje ERROR, a Sentry robi zdarzenia z CRITICAL — trwała awaria byłaby niewidoczna.
- M3. Telefon kierowcy planuje przeliczenie po każdym skanie paczki, także bez zmian (dziś tanie).
- M4. Blokada pozycji idzie w kolejności skanu indeksu `order_id`, czyli (zamówienie, id) — jak hurt i Dostawa;
  komentarz „rosnąco po id” jest nieścisły. W K5 sprawdzić `EXPLAIN` przy pełnej liście zamówień (pierwszy przebieg po
  wdrożeniu), czy optymalizator nie wybiera pełnego skanu tabeli.
- M5. `CLAUDE.md` i docstring `blokady_zamowien.py` nadal opisują przeliczenie priorytetów jako pisarza pozycji bez
  blokady zamówienia — patrz „Co następny krok musi wiedzieć”.
- M6. `priority_rung` z `policz` liczy szczeble wirtualne (trasa bez szczebla), a `drabina.pozycja_tagu` tylko wiersze —
  do pierwszego crona po wdrożeniu indeksy mogą różnić się o jeden.
- M7. Szczeble tras wykonanych zostają w tabeli na zawsze (zgodnie ze specem 4.4), więc renumeracja rośnie z liczbą
  tras — sprzątanie do rozważenia w K5/K8.
- M8. `test_zmiany_z_base_utrwalaja` podmienia cały serwis zmian z Base. — mierzy okablowanie końcówki, nie serwis.

**Odłożone przez recenzenta jako spoza K1 — moje rozstrzygnięcia (wszystkie: kod zostaje):**

1. Pozycja omijająca Formatowanie (`cut_to_size=False`) trzyma zamówienie w „Niekompletnych” na Formatowaniu, dopóki
   jest przed nim — dosłowna reguła specu 5.6; rozstrzyga K3. Koszt: zamówienie dłużej w sekcji „Niekompletne”.
2. Termin zamówienia z pozycji aktywnych (4.2), nie niezanulowanych (4.1) — doprecyzowanie planu; spec poprawia K5.
3. Rangi w skali „× 100” i pochodne `is_priority` u dotychczasowych czytelników (stara appka, progi dashboardu,
   Stanowiska, eksporty) — czytelników przepinają K3, K4b, K6; nic z K1 nie idzie na produkcję przed K5.
4. `set-priority`, przeciąganie i hurtowa zmiana priorytetu nadpisywane przez najbliższe przeliczenie — Pytanie 1
   planu, przyjęte w karcie.
5. Doróbka i hurtowe usunięcie pozycji zmieniają aktywność zamówienia bez wyzwalacza (ranga zamówienia nieświeża do
   crona) — tak stanowi spec 9.3; ranga 0 doróbki działa od razu.
6. Przeliczenie synchronicznie w żądaniu — Pytanie 2 planu, pomiar w K5.
7. Sześć osobnych `ALTER TABLE prod_orders` (blokady metadanych przy wdrożeniu w godzinach pracy) — ta sama praktyka
   co w migracjach logistyki; pora wdrożenia to K7.
8. Wycofanie po wdrożeniu (doróbki z rangą 0 pod starym algorytmem) — instrukcja K7.
9. Pamięć podręczna `config_service` (60 min na proces) dla progów i `DEADLINE_DAY_TYPE` — K2, jak w karcie.
10. Dokumenty programu i `symulacja.json` śledzone na gałęzi w publicznym repo — nie z commitów K1 (K1 dodał tylko
    odhaczenia w planie i ten raport); decyzja centrali przed scaleniem do `main`.

## Pytania do Konrada

Blokujących — brak. Dwie sprawy do decyzji centrali (1–2) i jedna do wiadomości (3):

1. **Limit czekania `utrwal` na blokadę (znalezisko I2 przeglądu)** — opis i dwa warianty w sekcji „Przegląd końcowy”.
   Do decyzji centrali: naprawa jako pierwszy krok K2, karta naprawcza albo K5 razem z wyścigami.
2. **Dwa przeliczenia naraz** — naprawione przebiegiem kontrolnym zamiast wiersza blokady, który proponował
   przegląd (uzasadnienie tamże). Jeśli centrala woli wiersz blokady, to zmiana specu 9.4 i migracji — łatwa,
   dopóki P1 nie jest wdrożone.
3. Pytania 1 i 2 z planu K1 (gwiazdka z `set-priority` żyje do najbliższego przeliczenia; przeliczenie po każdej akcji
   trasy wydłuża odpowiedź) przyjęte wg rekomendacji, jak w karcie. Pomiar na kopii danych: 0,22 s przy zmianie
   wszystkich 156 zamówień, 0,02 s bez zmian.

## Stan gałęzi

- `claude/priorytety-produkcji`: kod kończy się na `f2a7a6cc`; commit z tym raportem jest następny i jest HEAD-em gałęzi
  (hash w odpowiedzi końcowej sesji). Wszystko **wypchnięte** na `origin` — po każdym Tasku.
- 8 commitów nad `f731b77c`: po jednym na Task (7) i jeden z poprawkami po przeglądzie końcowym
  (`f2a7a6cc`, między Taskiem 6 a 7). `main` i `claude/logistyka-etap-4` nietknięte.
- Worktree: `.claude/worktrees/priorytety-produkcji` w katalogu głównego checkoutu (ten został na `main`).

## Co następny krok musi wiedzieć

**Środowisko (K2 i dalej):**

- Praca w worktree `.claude/worktrees/priorytety-produkcji` głównego checkoutu; start: `git fetch origin &&
  git pull --ff-only origin claude/priorytety-produkcji` w tym katalogu.
- Testy: `docker compose -p priorytety run --rm --no-deps app pytest <ścieżki> -q -p no:cacheprovider` (obraz
  `priorytety-app` jest zbudowany; kod montowany z worktree). Nigdy `docker compose exec app` (inny checkout). Pełny
  pakiet ~7 min, jeden naraz na maszynie.
- MySQL: baza `priorytety_podglad` w kontenerze `woodpower-crm-db-1` (kopia `logistyka4_podglad` + migracja K1 + rangi
  z przebiegu kontrolnego). Konfiguracja poza repo: `woodpower-podglady/priorytety/core.json` (+ `przygotuj_config.py`,
  `env.list`). Uruchomienie kodu gałęzi na tej bazie:
  `docker run --rm --network woodpower-crm_default -v "<worktree>:/app" -v "<…>/woodpower-podglady/priorytety/core.json:/app/config/core.json:ro" -w /app -e FLASK_SECRET_KEY=<losowy> logistyka3-app <polecenie>`.
- **Pułapka montowania:** takie uruchomienie zostawia w worktree PUSTY plik `config/core.json` (zaślepka Dockera,
  ignorowana przez git). Trzeba go skasować po każdym uruchomieniu — inaczej zmienia wynik
  `tests/test_daily_report_cli.py`. Nie uruchamiać tego równolegle z pełnym pakietem testów.
- `flask migrate-status` (i każde `create_app()`) samo wykonuje oczekujące migracje.
- `db.session` po odczycie trzyma migawkę REPEATABLE READ: sprawdzając w skrypcie skutek `utrwal()` (własna sesja),
  trzeba najpierw zrobić `db.session.rollback()`.

**Kontrakty K1:**

- `kolejka.policz(migawka) -> Wynik(zamowienia, pozycje, ostrzezenia, drabina)`; `Wynik.zamowienia[order_id] =
  RangaZamowienia(rank, rung, szczebel, tagi, termin)`: `rung` = indeks 1-based w `Wynik.drabina` (po ukryciu tras
  nieaktywnych i wstawieniu szczebli wirtualnych), `szczebel` ∈ `'trasa' | 'gwiazdki' | 'po_terminie' | 'blisko_terminu' |
  'rozpoczete'`, `tagi` = krotka. `kolejka._migawka(sesja)` — loader (sam odczyt, kolumny bez obiektów ORM).
- `kolejka.kandydaci_stanowiska(S, pozycje, statusy_zamowien, szczebel_rozpoczete=None, jednostka=None) ->
  Kandydaci(kafle, niekompletne)`. `pozycje` = lista `PozycjaStanowiska` w statusie stanowiska, już bez stołu i odłożeń.
  **`statusy_zamowien = {order_id: ((product_id, status), …)}` — pary, dla WSZYSTKICH pozycji zamówienia** (plan K3
  w jednym miejscu pisze „tuple(statusy)” — to pomyłka, obowiązują pary). `niekompletne = [(order_id, na_stanowisku,
  pozycji, brakuje)]`, `brakuje = [(product_id, status), …]` rosnąco po id. `szczebel_rozpoczete =
  drabina.pozycja_tagu('rozpoczete')`. `rung` puste (zamówienie jeszcze nieutrwalone) = koniec drabiny.
  `kolejka.kompletne_na_stanowisku(statusy, S)` przyjmuje same statusy.
- `kolejka.utrwal(zrodlo=None, user_id=None) -> dict` (`success`, `zamowien`, `pozycji`, `zmienione_zamowienia`,
  `zmienione_pozycje`, `ostrzezenia`, `duration_seconds`, `error`) — nigdy nie rzuca, nigdy nie dotyka `db.session`.
  **Warunek wstępny:** `db.session` wołającego nie ma niezatwierdzonych zapisów do zamówień ani pozycji (inaczej
  czekanie na własne blokady do limitu 50 s) — wołać wyłącznie po commicie.
- **`utrwal` po zapisie robi przebieg kontrolny** (świeża migawka, same odczyty, gdy rangi się zgadzają; najwyżej
  3 przebiegi). Raport: `zmienione_*` to suma zapisanych wierszy ze wszystkich przebiegów. Przeliczenie bez zmian to
  dalej jeden przebieg bez blokad.
- **K2: nie oddawać do przeglądarki `raport['error']`** — tekst błędu bazy niesie SQL z parametrami; spec 10
  przewiduje `{"przeliczenie": "nieudane"}`.
- **`CLAUDE.md` („Zamówienie najpierw”) i docstring `services/blokady_zamowien.py` są nieaktualne w jednym punkcie:**
  wymieniają przeliczenie priorytetów (`priority_service`) wśród pisarzy pozycji BEZ blokady zamówienia. Od K1
  przeliczenie (`kolejka.utrwal`) blokuje zamówienia, potem pozycje — jak hurt. Przeciąganie (`update-priority`)
  zostaje pisarzem bez blokady do K2. Poprawka tekstów: K5.
- **Trasa bez szczebla (okno wdrożenia, do pierwszego crona):** `priority_rung` z `policz` liczy szczebel wirtualny,
  a `drabina.pozycja_tagu` tylko wiersze tabeli — indeksy mogą różnić się o jeden, dopóki `drabina.uzupelnij()` nie
  dopisze szczebla (K3: porównanie ze `szczebel_rozpoczete`; K7: ręczny cron zaraz po restarcie).
- `drabina.pozycja_szczebla()` zwraca `None` dla szczebla ukrytego — K2 musi to obsłużyć.
- **Router commituje, serwis nie.** Panel: `db.session.commit()` → `kolejka.utrwal_po_commicie()` (każde wywołanie
  przelicza, wyjątek tylko do logu). API mobilne pod `with_idempotency`: handler woła `kolejka.zaplanuj_po_commicie()`,
  dekorator po commicie `wykonaj_zaplanowane()`; przy ponowieniu po 1213 `porzuc_zaplanowane()`. K3 dokłada do
  dekoratora piąty hook (sygnały stanowisk).
- `drabina.przesun` i `uzupelnij` same biorą blokadę tras; `zapewnij_szczebel_trasy` i `usun_szczebel_trasy` wymagają
  jej od wołającego. Pozycje szczebli (`pozycja_tagu`, `pozycja_szczebla`, `priority_rung`, log) to indeksy wśród
  szczebli WIDOCZNYCH, 1-based; kolumna `position` numeruje wszystkie wiersze, także ukryte szczeble tras.
- `gwiazdki.ustaw(order_ids, gwiazdki, user_id=None, teraz=None)` — pierwsze zapytanie to blokada zamówień; bez commita,
  bez blokady tras, bez przeliczenia. Sekwencja routera K2: `commit` → `ustaw` → `commit` → `utrwal_po_commicie()`.
- Klucze `prod_config` wyłącznie przez `stale.klucz_*(S)` i `stale.KLUCZ_*` (dosłownie jak w migracji — pilnuje tego
  test); `stale.LIMIT_HURTU = 500`.
- **`ustawienia.*` czytają przez `config_service.get_config` z pamięcią podręczną 60 minut na proces** — zgodnie z kartą
  naprawia to K2 (odczyt bez pamięci podręcznej). `ustawienia.prog_blisko(sesja)` już dziś czyta wiersz wprost.
- **Rangi zamówień nieaktywnych zostają z ostatniego przeliczenia** — czytelnicy `prod_orders.priority_rank/rung`
  (K2, K4a, K4b) muszą filtrować zamówienia aktywne, inaczej trafią na stare, zdublowane rangi.
- `POST /production/api/set-priority` (gwiazdka pozycji) działa jak dotąd, ale najbliższe `utrwal()` nadpisuje
  `is_priority`. `update-priority` i `bulk-action update_priority` piszą rangę wprost do następnego `utrwal()`;
  `lock_priority`/`unlock_priority` są puste, więc `products/<id>/priority` i `set-manual-priority` przyjmują żądanie
  i nie zapisują rangi. Wszystkie te końcówki usuwa K2 razem z 10 testami przeciągania w
  `tests/test_priorytety_kolejnosc_zapisow.py`.
- Importy pakietu `priorytety` w routerach logistyki **tylko wewnątrz funkcji** (pakiet logistyki importuje routery,
  a `priorytety.stale` importuje `logistics.sposoby`); `priorytety/models.py` odwołuje się do trasy napisem.
- Wywołania przeliczenia w `sync_service` idą dalej przez warstwę zgodności `priority_service` (stuby w
  `tests/test_sales_ingest_wyzwalacze.py`); wprost przepina je K8.
- Kanoniczny test „błąd `utrwal` nie brudzi `db.session`”: `test_nieudane_utrwal_zostawia_db_session_czysta`
  w `tests/test_priorytety_kolejnosc_zapisow.py` (warunek K8 dla usunięcia `tests/test_priority_statusy_krawedzi.py`).
- Fixtury testów z tabelami priorytetów: sześć plików z punktu 5 „Odstępstw”. Pomocniki: `tests/priorytety_fixtures.py`
  (`drabina_domyslna()`, `ustaw(klucz, wartosc, typ)`, fikstury `czyste_ustawienia`, `zamrozony_dzien`, `szpieg_utrwal`).
  Testy, które wołają `utrwal`, potrzebują `zamrozony_dzien`. `szpieg_utrwal[i]['czysta']` jest prawdą tylko wtedy,
  gdy od ostatniego commitu albo rollbacku nie poszedł do bazy żaden zapis — każdy nowy wyzwalacz w K2–K4b sprawdzać
  tą asercją. W `tests/blokady_pomocnicze.py` doszedł predykat
  `blokada_pozycji_zamowien`, a `zapis` łapie też `INSERT INTO prod_priority_log` i `prod_station_desk`.
- Testy liczące zapytania albo blokady w całym żądaniu trzeba izolować od `utrwal` po commicie (trzy przykłady
  w „Odstępstwach”, p. 3).
- Weryfikacja „Cofnij do pakowania” planuje przeliczenie po commicie — K3: sygnał `station:packaging` po tym zapisie
  (albo jawnie poza zakresem), K5: tryb regresji `weryfikacja-cofnij-desk`.
- Wdrożenie (K7): po restarcie raz ręcznie cron logistyki — faza `szczeble_uzupelnione` dopisze szczeble istniejących
  tras, `priorytety_utrwalone` nada rangi.

**Czego K1 celowo nie zrobił:** blueprint i końcówki HTTP, stół i sygnały, UI, `CLAUDE.md`, poprawki specu (zaszłości
„domyślnie 2” w 4.3 i „seed 8 szczebli” w 13 — do K5).

## Poza zakresem (zauważone, nie ruszane)

- Docstring `blokady_zamowien.kod_mysql` i sekcja „Zamówienie najpierw” w `CLAUDE.md` wymieniają jeszcze
  `priority_service.recalculate_all_priorities` jako pisarza — opis do aktualizacji w K5.
- `services/__init__.py`: zmienna `_priority_calculator_instance` została martwa (używa jej tylko `reload_services`).
- Zakładka Konfiguracja może pokazać 38 nowych wierszy `prod_config` w dotychczasowym układzie — porządkuje to K4b.
