# Priorytety produkcji, krok K4b — czytelnicy rangi: Stanowiska, dashboard, Konfiguracja, monitory hali — plan implementacji

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ekrany, które dziś czytają rangę progami (`priority_rank <= 10/50/100`, „priorytet ≥150”), pokazują nowy model:
zakładka Stanowiska i monitory hali widzą **stół, odłożone, niekompletne i kolejkę** stanowiska (to samo, co tablet),
z gwiazdkami i plakietkami szczebla; dashboard liczy **zamówienia** na szczeblach pilnych; Konfiguracja ma grupy
„Terminy” i „Stół stanowisk” zapisywane **jedną drogą** (`PUT /production/api/priorytety/ustawienia`), a martwe klucze
starego algorytmu znikają z kodu.

> **Karta K4b (centrala, 5.10) — decyzje i zakres dodatkowy (dopisane przez sesję K4b przed kodem).**
> Pytanie 1: **wariant A** (zakładka „Stanowiska” podpięta, Task 2 Step 6 wykonywany). Pytania 2–4: wartości domyślne
> planu (terminy 1–90, alert > 10 zamówień). Pytanie 3: na monitorze pracownik **„Adam K.”** (imię + inicjał nazwiska),
> notatka widoczna; w zakładce Stanowiska pełne imię i nazwisko. Zakres dodatkowy wg specu 5.1, 5.7, 5.8, 7.2 —
> **Task 2a** (zakładka: źródło kafla, „Zdejmij ze stołu”, stół dłuższy niż K, widma z D2 raportu K3), **Task 5a**
> (Konfiguracja: sekcja „Start stołów”, „Przygotuj stoły”, „Włącz stoły”), **Task 7a** (monitory: źródło kafla,
> „Adam K.”). Każdy osobnym commitem. Gdy plan i spec się różnią — wygrywa spec (wersja po bramce K3).

**Architecture:** Krok wyłącznie **czytający** (poza zapisem ustawień, który jest już w K2). Czytelnicy nie liczą kolejki
sami: zakładka Stanowiska renderuje się po stronie serwera z funkcji `priorytety/services/widok.py`, które stoją za
`GET /stoly` (K3) i `GET /kolejka?stanowisko=` (K2); dashboard sumuje liczniki `w_produkcji` z `widok.drabina_panelu()`
(K2), więc liczba zgadza się z modalem drabiny; monitory hali czytają kolumny pamięci podręcznej (`prod_orders.priority_rank`,
`priority_rung`, `priority_stars`) i wiersze `prod_station_desk`, bez `policz()` na każdym odświeżeniu telewizora.
Konfiguracja dostaje dwie karty ładowane i zapisywane przez `GET`/`PUT /ustawienia` (wzór: karta Trakownia,
`config-module.js:137-213`), poza paskiem „Zapisz zmiany” i allowlistą `update-configs`. K4b dokłada do `widok.py` trzy
małe odczyty i do `ustawienia.py` dwa pola terminów.

**Tech Stack:** Flask 2 + SQLAlchemy < 2.0, Jinja2, czysty JS (bez bundlera), MySQL 8.4 (produkcja) / SQLite in-memory
(testy), pytest. Frontu nie da się uruchomić w obrazie testowym — JS i szablony sprawdzamy strukturalnie na źródle
(konwencja `tests/test_druk_panel_ui.py`, `tests/krawedzie_fixtures.py:9-11`) i w przeglądarce na podglądzie.

**Spec:** `docs/superpowers/specs/2026-10-04-priorytety-produkcji-design.md`: 3.1 (drabina, szczeble), 4.1 (pojęcia:
zamówienie aktywne, ranga zamówienia i pozycji), 4.3 (Terminy), 5.1/5.3/5.6 (stół, odłożone, niekompletne), 7.2
(Stanowiska, monitory, dashboard, Konfiguracja), 7.3 (uprawnienia), 8.1–8.6 (kolumny, `prod_station_desk`, klucze
`prod_config`), 8.8 (martwe klucze), 9.1/9.2 (pakiet, kontrakty), 9.4 (współbieżność), 9.5 (wiersze `config_api.py`,
`stations_api.py`, `dashboard_api.py`, `monitors.py`, `routers/stations/__init__.py`), 10 (błędy ustawień), 13 (P-2, P-3,
P-4, P-9). Symulacja: `docs/superpowers/specs/2026-10-04-priorytety-produkcji-symulacja.md`, „Analiza wyniku” B, D p. 5
i „E. Decyzje”. Plany: K2 (`…-krok-K2-panel-api.md`: Task 2, 4, 5, Doprecyzowania 4, 7, 8), K3
(`…-krok-K3-stol-odloz-sygnaly.md`: Task 5, Doprecyzowania 4, 9, 10). Podręcznik centrali: sekcje 2, 3, 4a, 8.0, 8.5.

**Sesja:** lokalna (Docker: `docker compose exec app pytest`; podgląd w przeglądarce dla zakładek i monitorów hali).
Opus 5.5, effort high (podręcznik 4a: UI i czytelnicy pod testami strukturalnymi; jedyny zapis to gotowa końcówka K2).
Tryb szybki dozwolony. Wyścigów MySQL krok nie robi — nie ma nowych zapisów.

**Zależności:** K3 zakończony i zaliczony na bramce (daje `prod_station_desk` w użyciu, `widok.stoly_panelu()`,
`widok.odlozenia_panelu()`, `stol.kontekst_priorytetu(items)`, `GET /stoly`). Przez K3 także K1 i K2 (`widok.drabina_panelu()`,
`widok.kolejka_stanowiska()`, `widok.szczebel_json()`, `ustawienia.waliduj/zapisz/odczyt_panelu`, `GET`/`PUT /ustawienia`).
K4a niezależne, może iść równolegle (wspólny plik tylko `templates/panel/dashboard.html`).

**Gałąź:** `claude/priorytety-produkcji`. Start: `git fetch origin && git checkout claude/priorytety-produkcji && git pull
--ff-only origin claude/priorytety-produkcji`. Nigdy `main`. Numery linii w planie dotyczą `claude/logistyka-etap-4` @
`b4b4a54d` (sprzed K1–K3); pliki K4b K1–K3 ruszają tylko w `products_api.py`, `mobile_api*`, fixturach — mimo to szukaj
po nazwie funkcji (`grep -n`), gdy linia się nie zgadza.

## Global Constraints

- **Python 3.9:** `X | Y` w adnotacjach tylko w plikach z `from __future__ import annotations`; bez `match`.
- Komentarze i docstringi **po polsku**; w tekstach UI „Base.”. Teksty dla hali po polsku z polskimi znakami (szablony
  monitorów dziś mieszają ASCII i polskie znaki — nowe teksty z polskimi znakami, istniejących nie poprawiamy).
- **Czytelnicy nie piszą i nie blokują.** `stations-tab-content`, `dashboard-stats`, monitory (`/monitors/<kod>`,
  `/ajax/monitors/<kod>`, `/monitor`, `/ajax/monitor`) i `config-tab-content`: żadnego `FOR UPDATE`/`LOCK IN SHARE MODE`,
  żadnego `INSERT`/`UPDATE`/`DELETE`, żadnego `db.session.commit()`. W szczególności **nigdy** `stol.dopelnij(S)` (bierze
  `priorytety_blokada_<S>` i wstawia kafle — wolno tylko tabletowi, spec 5.2) ani ścieżka samonaprawy z routera
  `GET /drabina` (bierze blokadę tras, K2 Task 2) — czytelnik woła `widok.drabina_panelu()`, które jest czystym odczytem.
- **Jedyny zapis kroku** to istniejąca końcówka K2 `PUT /production/api/priorytety/ustawienia` (rozszerzona o dwa pola
  terminów). Jej kolejność bez zmian (K2 Task 5): walidacja całości → `user_id` → `ustawienia.zapisz` (UPDATE/INSERT
  `prod_config` + INSERT `prod_priority_log` **bez** `order_id`) → `db.session.commit()` → `invalidate_config_cache()` →
  `kolejka.utrwal()` tylko przy zmianie progu „Blisko terminu”. Bez blokad tras, deklaracji, zamówień i stołu: zapis nie
  dotyka `prod_orders`, `prod_products`, `prod_routes` ani `prod_station_desk` (CLAUDE.md „Trasy logistyki — jeden piszący
  naraz”, „Deklaracje paczek — jedna naraz”, „zamówienie najpierw” nie mają tu zastosowania; spec 9.4: `utrwal()` po
  commicie, na własnej sesji).
- **Serwisy nie commitują**; nowe funkcje w `widok.py` też nie (DoD 6 K2).
- **Odporność czytelników:** wyjątek w warstwie priorytetów (np. brak tabeli w oknie wdrożenia, błąd `policz`) nie kładzie
  ekranu: `logger.error`, sekcje priorytetów puste albo `None`, odpowiedź 200 z resztą danych (wzór `_safe_*`,
  `dashboard_api.py:80-252`). Monitor hali to telewizor bez człowieka przy klawiaturze.
- **Escape w JS:** każdy tekst z bazy wstawiany przez `innerHTML`/szablon literałowy (nazwa trasy, powód, notatka,
  pracownik, numer) idzie przez funkcję ucieczki (`escapeHtml` w `station-monitor.js`, nowa, 5 znaków `& < > " '`).
- Zakres: pliki z „Mapy plików”. **Nie** ruszaj: Listy produkcyjnej, modali, Logistyki, `products_api.py`,
  `products-module.js`, `products-dragdrop.js` (K4a); algorytmu `kolejka.*`, `stol.*`, API mobilnego (K1/K3);
  `priority_service.py`, `ProductionPriorityConfig` jako modelu (K8); `tools/print_agent`. Usterki spoza zakresu → raport.
- Testy: `docker compose exec app pytest <ścieżki> -q -p no:cacheprovider`. TDD: najpierw test, który pada. SQLite
  in-memory wg konwencji repo (`tests/krawedzie_fixtures.py`, `tests/blokady_pomocnicze.py` — `Zapytania`,
  `tests/logistyka_fixtures.py`, `tests/priorytety_fixtures.py` z K1).
- Commity: Conventional Commits po polsku, **temat bez polskich znaków**, jeden na Task, stopka atrybucji własnej sesji.
  `docs/superpowers/` przez `git add -f`. Push wg karty (S-2). Gdy K4a pracuje równolegle na tej gałęzi: `git pull --rebase`
  przed każdym commitem; konflikt tylko w `templates/panel/dashboard.html` — scal obie zmiany, nie nadpisuj.
- Repo publiczne: bez sekretów, adresów IP i danych klientów (zrzuty ekranu z bazy podglądu z danymi testowymi).

## Review Focus

1. **Czytelnicy niczego nie piszą, nie blokują i nie dopełniają stołu** (spec 5.2, 9.4). Testy:
   `test_zakladka_stanowisk_bez_blokad_i_zapisow`, `test_dashboard_stats_bez_blokad_i_zapisow`,
   `test_monitory_bez_blokad_i_zapisow` (parametryzowany po 4 końcówkach), `test_monitor_i_zakladka_nie_wolaja_dopelnij`
   (Task 2, 3, 6).
2. **Zakładka Stanowiska pokazuje to, co tablet, a nie progi rangi** (spec 7.2). Testy:
   `test_zakladka_stanowisk_stol_i_odlozone_z_widoku`, `test_zakladka_stanowisk_kolejka_15_z_kandydatow`,
   `test_zakladka_formatowania_niekompletne_z_brakujacymi`, `test_zakladka_bez_progow_rangi_i_sekcji_priority`,
   `test_zakladka_przezywa_blad_priorytetow` (Task 2).
3. **Dashboard liczy zamówienia na szczeblach ★★★★★/★★★★/Po terminie/trasy** — tą samą liczbą co modal drabiny. Testy:
   `test_high_priority_count_to_zamowienia_na_szczeblach_pilnych`, `test_high_priority_count_rowny_sumie_licznikow_drabiny`,
   `test_alert_pilnych_bez_progu_150`, `test_dashboard_stats_przezywa_blad_priorytetow` (Task 3).
4. **Jedna droga zapisu ustawień priorytetów i terminów** (K2 Doprecyzowania 8). Testy:
   `test_update_configs_odrzuca_klucze_priorytetow_i_terminow`, `test_ustawienia_terminow_przez_put`,
   `test_karty_terminow_i_stolu_poza_pending_changes`, `test_skrypt_zapisuje_przez_put_ustawienia`,
   `test_update_config_pojedynczy_odrzuca_priorytety_i_terminy` (Task 4, 5).
5. **Martwe klucze i martwy odczyt `prod_priority_config` znikają z kodu**, inaczej DROP w K8 położy zakładkę
   Konfiguracja. Testy: `test_martwe_klucze_priorytetow_usuniete_z_kodu`, `test_update_configs_odrzuca_martwe_klucze`,
   `test_zakladka_konfiguracji_bez_prod_priority_config` (Task 4, 5).
6. **Monitory po randze, z doróbkami na początku; widok HTML i AJAX mają tę samą kolejność** (pułapka 2 z
   `tests/test_monitory_krawedzie.py:9-11`). Testy: `test_monitor_stanowiska_po_randze_dorobki_pierwsze`,
   `test_monitor_html_i_ajax_ta_sama_kolejnosc`, `test_monitor_ogolny_po_randze`, `test_monitor_stol_teraz_i_odlozone`,
   `test_monitor_przezywa_blad_priorytetow`, `test_monitor_grupuje_po_id_zamowienia` (Task 6);
   `test_priorytet_zamowien_indeks_widoczny_nie_position`, `test_priorytet_zamowien_nieaktywne_bez_rangi` (Task 1).
   **Lakiernia (Doprecyzowania 15):** `test_monitor_lakierni_kolejnosc_jak_lista_tabletu`,
   `test_monitor_lakierni_bez_stolu_mimo_trybu_stol`, `test_zakladka_lakierni_lista_bez_stolu`,
   `test_konfiguracja_lakierni_bez_wyboru_trybu` (Task 2, 5, 6).
7. **Auto-odświeżenie monitora przestawia karty wg serwera i ucieka teksty z bazy.** Testy (na źródle JS):
   `test_js_monitora_przestawia_karty_wg_kolejnosci_serwera`, `test_js_monitora_escapuje_teksty_z_bazy`,
   `test_js_monitora_renderuje_stol_i_odlozone`, `test_js_monitora_klucz_karty_to_order_id` (Task 7).

## Decyzje przyjęte (ze specu i symulacji)

1. Priorytetami zarządza biuro; gwiazdki 0–5 na **zamówieniu**, trasy i tagi na drabinie (Konrad 4.10, spec 2 p. 1–3).
   Czytelnicy pokazują gwiazdki zamówienia, a gwiazdka pozycji (`is_priority`) zostaje tylko pochodną (spec 4.2, 8.5).
2. Stół 1–2 kafle, odłożony kafel zostaje widoczny, limit odłożeń (Konrad 4.10, spec 2 p. 5–6). Zakładka i monitor
   pokazują stół i odłożone z powodem, godziną i pracownikiem (spec 5.3, 7.2).
3. K=2 i sekcja „Niekompletne” do K wystarczają (symulacja D p. 5, Konrad 5.10, P-2/P-9) — czytelnicy nie mają własnych
   limitów, pokazują to, co liczy K2/K3.
4. Próg „Blisko terminu” **3 dni robocze**, konfigurowalny bez wdrożenia (Konrad 5.10; symulacja E). Pole w karcie
   „Stół stanowisk” (spec 7.2), zakres 0–15 (K2 Doprecyzowania 8).
5. `DEADLINE_DAY_TYPE` ∈ {`robocze`, `kalendarzowe`}, domyślnie `robocze`; terminy już zaimportowanych zamówień się nie
   zmieniają (Konrad 4.10, spec 4.3) — karta „Terminy” mówi to w opisie pola.
6. Jedyna droga zapisu kluczy `priorytety_*` i `DEADLINE_DAY_TYPE` to `PUT /ustawienia`; K4b nie dopisuje ich do allowlisty
   `update-configs` (K2 Doprecyzowania 8). K4b przenosi tam także `DEADLINE_DEFAULT_DAYS` i `DEADLINE_FINISHED_DAYS`
   (Doprecyzowania p. 5) — jedna karta, jedna droga.
7. Ustawienia tylko dla admina (spec 7.3); podgląd stołów — `guard` (spec 7.3). Zakładki panelu zostają przy
   `login_required` jak pozostałe `*-tab-content` (Doprecyzowania p. 11).
8. Tryb stanowiska `stary` do P3 (spec 11): w tym trybie stół jest pusty (stara appka nie woła `desk`), więc monitor
   i zakładka pokazują kolejkę po randze, a sekcje stołu pojawiają się dopiero po przełączeniu stanowiska na `stol` (K7).
9. **Lakiernia na stałe bez stołu, lista po wykończeniu** (Konrad 5.10, S-6 wariant C; spec ustalenie 15, 3.2 „Lista
   Lakierni”, 7.2): monitor i zakładka Lakierni nigdy nie pokazują stołu ani odłożeń; kolejność = lista Lakierni
   z K3 (`lista.porzadek_listy('painting', …)`, grupy wykończenia), nie ranga zamówienia; w Konfiguracji wiersz Lakierni
   bez wyboru trybu, K, jednostki i limitu (Doprecyzowania 15).

## Doprecyzowania (do specu — K5 przeniesie)

1. **Zakładka Stanowiska nie woła HTTP.** `stations_api.stations_tab_content` renderuje po stronie serwera z
   `widok.stoly_panelu()` (K3) i `widok.kolejka_stanowiska(S, limit=15)` (K2) — tych samych funkcji, które stoją za
   `GET /stoly` i `GET /kolejka?stanowisko=`. Tablet, panel i zakładka widzą to samo.
2. **„Pierwsze 15 kafli kolejki”** = `kolejka_stanowiska(S, limit=15)['kafle']`: bez kafli leżących na stole i odłożonych;
   na Formatowaniu i Pakowaniu tylko zamówienia **kompletne**. Niekompletne (`['niekompletne']`) w osobnej sekcji
   z `na_stanowisku/pozycji` i listą brakujących (`short_id` + nazwa stanowiska), najwyżej 15.
3. **Statystyki zakładki:** `stats.high_priority` znika; dochodzą `na_stole`, `miejsca`, `odlozone`, `limit_odlozen`,
   `tryb`, `kolejka_dalej` (z K3). Kropka przy liczniku w „Przepływie produkcji” oznacza **odłożone** (`title="N
   odłożonych"`), nie rangę. `total_pending`, `today_completed`, `today_volume`, `name`, `icon` bez zmian (testy
   `tests/test_stanowiska_tab_krawedzie.py`).
4. **`high_priority_count`** w `GET /production/api/dashboard-stats` = suma `w_produkcji` szczebli widocznych
   w `widok.drabina_panelu()` o rodzaju: `gwiazdki` 5 i 4, `tag` `po_terminie`, `trasa` (każda). Liczy **zamówienia**
   (dotąd pozycje z `priority_rank <= 10`). Nazwa pola zostaje (zgodność kontraktu). Próg alertu `> 10` bez zmian; tytuł
   „Dużo pilnych zamówień”, treść „N zamówień w produkcji na szczeblach ★★★★★, ★★★★, „Po terminie” i trasach”. Błąd
   warstwy priorytetów → `high_priority_count: null`, brak alertu, log ERROR.
5. **Terminy przez `PUT /ustawienia`:** dwa nowe pola ciała i odpowiedzi `GET`: `deadline_default_days` →
   `DEADLINE_DEFAULT_DAYS`, `deadline_finished_days` → `DEADLINE_FINISHED_DAYS` (int 1–90, `bool` nie przechodzi,
   `config_type='integer'`), log `ustawienia` jak inne pola, **bez** `utrwal()` (zmiana dotyczy tylko nowych importów).
   Oba klucze znikają z allowlisty `update-configs` (dziś jest tam tylko `DEADLINE_DEFAULT_DAYS`, `config_api.py:510`;
   `DEADLINE_FINISHED_DAYS` nie było nigdzie w UI ani w allowliście).
6. **Karty „Terminy” i „Stół stanowisk”** ładują stan z `GET /ustawienia` po wczytaniu zakładki
   (`loadOriginalValuesFromDOM`) i zapisują go własnym przyciskiem „Zapisz” na karcie — tylko zmienione pola, odpowiedź
   `PUT` odświeża pola. Nie trafiają do `pendingChanges`/`saveAllChanges` (wzór Trakownia). 400 `ustawienie_niepoprawne`
   podświetla pole z `pole` (np. `stanowiska.gluing.miejsca`), 403 → komunikat „Tylko administrator”.
7. **Martwe klucze w K4b znikają z kodu** (UI, `EXPECTED`, allowlista, JS, `config_service._default_values`), **wiersze**
   w `prod_config` usuwa migracja K8 (spec 8.8). Odczyt `ProductionPriorityConfig` w `config_tab_content`
   (`config_api.py:328-352`, pole `priority_configs` odpowiedzi; szablon go nie używa) znika w K4b, żeby DROP
   `prod_priority_config` w K8 nie położył zakładki. Import modelu w `routers/api/__init__.py:13-15` zostaje dla K8.
8. **Monitory czytają kolumny, nie `policz()`.** Kolejność monitora stanowiska: (zamówienie ma doróbkę na tym
   stanowisku ? 0 : 1, `prod_orders.priority_rank` NULLS LAST, numer). Monitor zbiorczy: (`priority_rank` NULLS LAST,
   numer). Szczebel i plakietka z `priority_rung` przetłumaczonego mapą **indeks widoczny → szczebel**
   (`enumerate(drabina.szczeble(), 1)`; ta sama mapa co K3 Doprecyzowania 4 i `stol.kontekst_priorytetu`). `priority_rung`
   to indeks wśród szczebli **widocznych** (K1: `pozycja_szczebla`), **nie** kolumna `PriorityRung.position` — ta numeruje
   też ukryte szczeble tras załadowanych/w trasie, więc po pierwszym załadunku mapa po `position` przypisałaby
   zamówieniom cudze szczeble. Tag „Rozpoczęte” i „Po terminie” mogą być spóźnione do najbliższego `utrwal()`
   (cron co godzinę) — świadomie: telewizor odświeża co 30 s i nie może liczyć całej kolejki.
   **Zamówienie nieaktywne** (żadna pozycja w `stale.STATUSY_PRODUKCJI`, np. same `wstrzymane`/`anulowane` — monitor
   zbiorczy je pokazuje, bo filtruje tylko „nie po spakowaniu”) ma w kolumnach rangę z ostatniego przeliczenia
   (K1 ich nie zeruje) — czytelnik traktuje je jak `ranga: None`, `szczebel: None`, `plakietka: None`.
9. **Monitory grupują po `ProductionOrder.id`**, nie po `internal_order_number` (numer powtarza się co rok — zgłoszone
   w 4.4a, „Poza zakresem”). **Kluczem karty w JS i w szablonach jest `order_id`** (`data-order-id`, mapa
   `currentOrders` po `order_id`): przy kluczu `order_number` dwie karty z tym samym numerem zlewałyby się po pierwszym
   auto-odświeżeniu (jedna aktualizowana dwa razy, druga gubiona). `data-order` i pole `order_number` zostają do
   wyświetlania; dochodzi `order_id`.
10. **Sekcje „TERAZ” i „Odłożone” na monitorze** rysują się tylko, gdy niepuste; nagłówek pokazuje `kolejka_dalej`
    i tryb stanowiska tylko w trybie `stol`. Monitor nigdy nie dopełnia stołu — w trybie `stol` przy pustym stole widać
    kolejkę po randze, a stół zapełni pierwszy `GET desk` tabletu.
11. **Uprawnienia zakładki Stanowiska** bez zmian (`login_required`, jak inne `*-tab-content`); `GET /stoly` ma `guard`
    (K3). Monitory bez zmian (filtr IP `apply_station_security`, `routers/stations/__init__.py:28-32`).
12. **Nowe odczyty w `widok.py`** (K4b): `stoly_panelu(stanowiska=None)` — opcjonalny filtr listy kodów (bez filtra
    zachowanie K3); `liczba_pilnych_zamowien() -> int`; `priorytet_zamowien(order_ids) -> Dict[int, dict]`
    (`{"gwiazdki", "ranga", "szczebel": szczebel_json|None, "plakietka": str|None}` z kolumn i `drabina.szczeble()`,
    mapa po indeksie widocznym — p. 8; zamówienie nieaktywne → `ranga`/`szczebel`/`plakietka` `None`).
13. **Etykiety powodów odłożenia.** `stale.POWODY_ODLOZENIA` to krotka **kodów** (K1/K3), nie tekstów. K4b dokłada
    `stale.ETYKIETY_POWODOW_ODLOZENIA = {'brak_materialu': 'brak materiału', 'awaria_maszyny': 'awaria maszyny',
    'brak_miejsca': 'brak miejsca', 'czeka_na_biuro': 'czeka na biuro', 'inne': 'inne'}` (chyba że K1/K3 już mają
    odpowiednik — Step 0, wtedy jego nazwa) i pole `powod_etykieta` w odłożonych z `stoly_panelu` (zakładka, monitor,
    JS monitora czyta gotowy tekst — bez trzeciej kopii mapy w JS). Test: klucze mapy == `POWODY_ODLOZENIA`.
14. **Druga droga zapisu zamknięta także w `POST /update-config`** (pojedynczy klucz, `config_api.py:18`, `admin_required`,
    **bez allowlisty** — zapisuje dowolny klucz przez `set_config`). Klucze z prefiksem `priorytety_` albo `DEADLINE_`
    → 400 „Ten klucz zapisuje się w Konfiguracji → Terminy / Stół stanowisk (PUT /production/api/priorytety/ustawienia)”.
    Sprawdzenie po prefiksie, bez wypisywania martwych kluczy z nazwy (grep z Task 8 ma zostać pusty; martwe klucze
    nic nie czytają, więc ich zapis tą drogą jest nieszkodliwy).
15. **Lakiernia u czytelników** (Decyzje 9; K3 Task 5a): `widok.stoly_panelu()` zwraca 6 stanowisk (bez `painting`).
    **Monitor Lakierni** (`/monitors/painting`, AJAX): kolejność kart zamówień = kolejność **pierwszego wystąpienia**
    pozycji zamówienia na liście `lista.porzadek_listy('painting', items)` (te same pozycje w statusie Lakierni, które
    monitor już czyta; doróbki i tak są na początku listy) — telewizor pokazuje to samo co tablet; nigdy sekcji
    „TERAZ”/„Odłożone” ani „Dalej w kolejce”, `stol` w AJAX = `null` (bez wołania `stoly_panelu`); na karcie plakietka
    grupy wykończenia pierwszej pozycji (`lista.grupa_wykonczenia_json`, tekst „lakierowane · <kolor> · <połysk>”, brak
    wartości pomijany). Monitor zbiorczy bez zmian (ranga). **Zakładka Stanowiska, karta Lakierni:** bez paska trybu
    i sekcji stołu/odłożeń/niekompletnych; „Dalej na liście (pierwsze 15)” = pierwsze 15 pozycji z `porzadek_listy` (pozycje
    w statusie Lakierni) z nazwą grupy, zamiast `kolejka_stanowiska`. **Konfiguracja „Stół stanowisk”:** wiersz Lakierni
    z napisem „Lista (bez stołu)”, bez `select.prio-tryb`, `input.prio-miejsca`, `select.prio-jednostka`,
    `input.prio-limit` — JS nie wysyła pól `stanowiska.painting.*`. Funkcja porządku tylko z K3 — bez kopii w K4b.

## Mapa plików

| Plik | Task | Rola |
|---|---|---|
| `modules/production/priorytety/services/widok.py` (K2/K3) | 1 | `stoly_panelu(stanowiska=None)`, `liczba_pilnych_zamowien()`, `priorytet_zamowien(order_ids)` |
| `modules/production/priorytety/stale.py` (K1) | 1 | `ETYKIETY_POWODOW_ODLOZENIA` (Doprecyzowania 13; tylko gdy K1/K3 nie dali odpowiednika) |
| `modules/production/templates/components/_priorytet_plakietki.html` (nowy) | 1 | makra Jinja `gwiazdki(n)`, `plakietka(szczebel)` |
| `modules/production/routers/api/stations_api.py:16-155` | 2 | stół, odłożone, niekompletne, 15 kafli; bez progów rangi |
| `modules/production/templates/components/stations-tab-content.html` | 2 | nowe sekcje; usunięte `priority-section` (`:120-209`), progi (`:21-23`, `:44-46`, `:74-78`), `startProcessing` (`:262-266`) |
| `modules/production/static/css/stations-tab.css` | 2 | style stołu, odłożonych, plakietek; martwe `.priority-section/-badge/-table` (`:396-516`) usunięte |
| `templates/panel/dashboard.html`, `static/js/production-app-loader.js` | 2 | **tylko przy decyzji A** (Pytania do Konrada): przycisk i panel „Stanowiska”, `loadStationsTab()`, link CSS |
| `modules/production/routers/api/dashboard_api.py:314-374`, `:395` | 3 | `high_priority_count`, alert |
| `modules/production/priorytety/services/ustawienia.py` (K1/K2) | 4 | pola `deadline_default_days`, `deadline_finished_days` w `waliduj`/`zapisz`/`odczyt_panelu` |
| `modules/production/routers/api/config_api.py:18-128`, `:226-230`, `:328-352`, `:362`, `:506-529` | 4, 5 | odmowa prefiksów w `update-config` (4), odczyt `ProductionPriorityConfig` (4), allowlista (4); `EXPECTED` i `stanowiska_stolu` (5, razem z kartą) |
| `modules/production/services/config_service.py:75` | 4 | usunięcie `PRIORITY_RECALC_INTERVAL_HOURS` z `_default_values` |
| `modules/production/templates/components/config-tab-content.html:1283-1417` | 5 | karta „Priorytety i Deadlines” → karty „Terminy” i „Stół stanowisk” |
| `modules/production/static/js/modules/config-module.js` | 5 | `loadPriorytetyUstawienia()`, `savePriorytetyUstawienia(karta)`; martwe klucze (`:54-56`, `:65-67`, `:238-240`, `:675-677`, `:805-807`) |
| `modules/production/static/css/config-tab.css` | 5 | tabela stanowisk w karcie |
| `templates/panel/dashboard.html:14`, `:365` | 5 | wersje `config-tab.css`, `config-module.js` |
| `modules/production/routers/stations/__init__.py:271-364` | 6 | `_get_monitor_station_data` (sort, `priorytet`, `order_id`), nowe `_stol_monitora(kod)` |
| `modules/production/routers/stations/monitors.py:52-127`, `:134-437` | 6 | stół w widoku i AJAX; monitor zbiorczy po randze — jedna funkcja `_zamowienia_monitora_ogolnego()` zamiast dwóch kopii map |
| `modules/production/templates/stations/monitor_station.html`, `monitor.html` | 7 | sekcje TERAZ/Odłożone, gwiazdki, plakietki |
| `modules/production/static/js/stations/station-monitor.js` | 7 | przestawianie kart, sekcje stołu, `escapeHtml` |
| `modules/production/static/css/stations/station-monitor-v2.css`, `station-monitor.css` | 7 | style |
| `tests/test_priorytety_czytelnicy.py` (nowy) | 1–5 | zakładka, dashboard, Konfiguracja |
| `tests/test_priorytety_monitory.py` (nowy) | 6, 7 | monitory, JS monitora |
| `tests/test_priorytety_panel_api.py` (K2) | 4 | testy pól terminów `PUT /ustawienia` |
| `tests/test_monitory_krawedzie.py:58-60` | 6 | nowe tabele w `TABELE` |
| `tests/test_druk_panel_ui.py:30-33`, `:198-203` | 5 | znacznik końca karty drukarki, wersja skryptu |
| `tests/test_reports_service.py` | 3 | `is_priority` w raporcie terminów = kolumna pochodna |
| `docs/superpowers/plans/raporty/2026-10-05-priorytety-krok-K4b-raport.md` (nowy) | 8 | raport kroku |

Usunięte w całości: brak plików. Raporty (`reports_service.py:492`, `:514`, `components/reports/deadlines.html:500`) —
**bez zmian kodu** (`is_priority` jest pochodną od K1); K4b dokłada tylko test regresji.

---

### Task 1: Punkt wyjścia, wspólne odczyty i makra plakietek

**Files:**
- Modify: `modules/production/priorytety/services/widok.py` (K2/K3), `modules/production/priorytety/stale.py` (K1)
- Create: `modules/production/templates/components/_priorytet_plakietki.html`, `tests/test_priorytety_czytelnicy.py`

**Stan obecny (ugruntowanie):**
- Na `b4b4a54d` pakietu `priorytety` **nie ma**; `widok.py` zakłada K2 (Task 2/4), K3 dokłada `stoly_panelu()`,
  `odlozenia_panelu()` (K3 Task 5). `drabina.szczeble()` — K1. Kolumny `prod_orders.priority_*` — K1 (spec 8.1).
- Katalog stanowisk: `services/station_catalog.py:24` (`STATION_ORDER`), `:37` (`STATION_LABELS`), `:68`
  (`STATION_PENDING_STATUS`), `:79` (`station_label`).
- Dziś nie ma w kodzie żadnego wspólnego renderu gwiazdek ani plakietek szczebla (gwiazdka = pomarańczowa ramka
  i `is_priority`). K4a robi komponent JS dla Listy produkcyjnej; K4b potrzebuje wersji Jinja (zakładka, monitory)
  i JS monitora (Task 7) — nie dzielimy plików z K4a.

**Interfaces:**
- Consumes (sprawdź w Step 0, spec 9.1/9.2/8.x, K2/K3):

  | Nazwa | Czego K4b oczekuje |
  |---|---|
  | `lista.porzadek_listy(kod, items)`, `lista.grupa_wykonczenia_json(item)`, `stale.STANOWISKA_BEZ_STOLU` (K3 Task 5a) | porządek listy Lakierni i grupa wykończenia (Doprecyzowania 15) |
  | `widok.stoly_panelu() -> List[dict]` (K3) | 6 słowników (bez Lakierni, K3 Task 5a): `stanowisko`, `nazwa`, `tryb`, `jednostka`, `miejsca`, `limit_odlozen`, `stol`, `odlozone`, `kolejka_dalej` |
  | `widok.kolejka_stanowiska(kod, limit=50) -> dict` (K2) | `stanowisko`, `nazwa`, `jednostka`, `lacznie`, `kafle`, `niekompletne`; kafel z `szczebel` |
  | `widok.drabina_panelu() -> dict` (K2) | `szczeble[*]` z `rodzaj`, `gwiazdki`, `tag`, `trasa`, `w_produkcji`; bez blokad i bez samonaprawy |
  | `widok.szczebel_json(rung) -> dict` (K2) | `id`, `rodzaj`, `etykieta`, `pozycja`, `trasa` |
  | `drabina.szczeble()` (K1) | wiersze z `kind`, `stars`, `tag`, `route_id`, `position`, bez tras nieaktywnych; `priority_rung` = indeks 1-based na tej liście (nie `position`) |
  | `stol.kontekst_priorytetu(items)` (K3) | mapa indeks widoczny → rodzaj (cache w `g`) — jeśli K3 wystawił samą mapę jako funkcję, użyj jej |
  | `stale.STATUSY_PRODUKCJI`, `stale.POWODY_ODLOZENIA` (K1) | 7 statusów aktywnych; krotka kodów powodów |
  | `ustawienia.waliduj(dane)`, `zapisz(zmiany, user_id)`, `odczyt_panelu()` (K2) | jak K2 Task 5 |
  | `ProductionOrder.priority_stars`, `.priority_rank`, `.priority_rung`; `StationDesk` (K1) | spec 8.1, 8.4 |

- Produces (`widok.py`, bez commitów, bez blokad):
  ```python
  def stoly_panelu(stanowiska=None):        # Optional[Iterable[str]]; None = 6 stanowisk jak w K3 (bez Lakierni)
      ...
  def liczba_pilnych_zamowien():            # -> int; suma w_produkcji szczebli pilnych (Doprecyzowania 4)
      ...
  def priorytet_zamowien(order_ids):        # -> Dict[int, dict]; kolumny + mapa position→szczebel (Doprecyzowania 8, 12)
      ...
  SZCZEBLE_PILNE = (('gwiazdki', 5), ('gwiazdki', 4), ('tag', 'po_terminie'), ('trasa', None))
  ```
  `priorytet_zamowien` czyta jednym zapytaniem `id, priority_stars, priority_rank, priority_rung` zamówień, jednym
  zapytaniem zbiór `order_id` z pozycją w `STATUSY_PRODUKCJI` (aktywne) i raz `drabina.szczeble()`; szczebel =
  `widoczne[priority_rung - 1]` z `widoczne = list(drabina.szczeble())`, serializowany `szczebel_json(rung,
  pozycja=priority_rung)` (bez zapytania na szczebel). `plakietka` = etykieta szczebla dla rodzaju innego niż `gwiazdki`
  („Trasa Śląsk · od 08.10”, „Po terminie”, „Blisko terminu”, „Rozpoczęte”), dla `gwiazdki` — `None`. `rung` poza
  zakresem listy (np. trasa właśnie załadowana, wirtualny szczebel K1) → `szczebel: None`, `plakietka: None`. Zamówienie
  nieaktywne → `ranga`, `szczebel`, `plakietka` `None` (Doprecyzowania 8). Jeśli K3 wystawił mapę indeks widoczny →
  szczebel jako funkcję (Step 0), użyj jej zamiast drugiej kopii.
- Produces (`stale.py`, Doprecyzowania 13): `ETYKIETY_POWODOW_ODLOZENIA`; `stoly_panelu` dokłada `powod_etykieta`
  do każdego odłożonego.
- Produces (Jinja, `components/_priorytet_plakietki.html`): `{% macro gwiazdki(n) %}` → `<span class="prio-gwiazdki"
  title="N gwiazdek">★★★</span>` albo nic przy 0; `{% macro plakietka(szczebel, dorobka=False) %}` → `<span class="prio-plakietka
  prio-<rodzaj|tag>">…</span>`, doróbka → „Doróbka”. Klasy CSS: `prio-gwiazdki`, `prio-plakietka`, `prio-trasa`,
  `prio-po_terminie`, `prio-blisko_terminu`, `prio-rozpoczete`, `prio-dorobka`.

- [x] **Step 0: Punkt wyjścia i weryfikacja K1–K3**
  1. `git log -1 --oneline` → hash z karty centrali; inny → STOP, pytanie do centrali.
  2. Przeczytaj raporty K1, K2, K3 (`docs/superpowers/plans/raporty/2026-10-05-priorytety-krok-K{1,2,3}-raport.md`), sekcje
     „Co następny krok musi wiedzieć” i „Odstępstwa”. Zanotuj decyzję K2 o pamięci podręcznej `ustawienia.*`
     (`test_ustawienia_czytane_bez_pamieci_podrecznej_procesu`: zielony czy `xfail`).
  3. Dla każdego wiersza „Consumes”: `grep -n "def stoly_panelu\|def kolejka_stanowiska\|def drabina_panelu\|def szczebel_json\|def odczyt_panelu\|def waliduj\|def zapisz\|def kontekst_priorytetu\|def szczeble" -r modules/production/priorytety`
     — zapisz do raportu ścieżka:linia i faktyczny kształt (szczególnie `kafel["szczebel"]`: obiekt czy napis).
     Inna nazwa przy tej samej semantyce → nazwa z kodu + „Odstępstwa”. **Brak** `stoly_panelu`, `kolejka_stanowiska`
     albo `drabina_panelu` → **STOP** przed Taskiem, który ich potrzebuje (2, 3, 6), meldunek do centrali (karta
     naprawcza K2/K3). Bez własnej kopii algorytmu.
  4. `grep -n "PriorityRung\|StationDesk" tests/krawedzie_fixtures.py tests/test_monitory_krawedzie.py` — zanotuj, które
     fixtury mają już nowe tabele (K1 dopisał część; `test_monitory_krawedzie.py` dopisuje Task 6). Gdy
     `krawedzie_fixtures.TABLES` nie ma `PriorityRung`, `PriorityLog`, `StationDesk`, nowy plik testów zakłada je we
     własnej fiksturze (`db.metadata.create_all(bind=db.engine, tables=[...])` po fiksturze `app`), bez zmiany
     `krawedzie_fixtures.py`.
  5. Pełny pakiet: `docker compose exec app pytest tests/ -q -p no:cacheprovider` → liczby `passed/skipped/failed` do
     raportu. Zero `failed` to warunek startu; inaczej STOP.
- [x] **Step 1: Testy, które padną** (`tests/test_priorytety_czytelnicy.py`; fixture `app` z `krawedzie_fixtures` +
  `drabina_domyslna()` z `tests/priorytety_fixtures.py`; pomocniki `zamowienie(...)`, `pozycja(...)`, `trasa(...)`,
  `kafel_stolu(...)` lokalnie albo z fixtur K2/K3):
  `test_stoly_panelu_filtr_stanowisk` (`['gluing']` → jeden słownik; `None` → 7, kolejność `STATION_ORDER`),
  `test_liczba_pilnych_zamowien_szczeble` (★5, ★4, po terminie, na trasie zatwierdzonej, ★3, blisko terminu,
  bez gwiazdek, spakowane ★5 → 4), `test_priorytet_zamowien_z_kolumn` (★2 bez trasy → `szczebel.rodzaj == 'gwiazdki'`,
  `plakietka is None`; `priority_rung` trasy → plakietka z nazwą i datą; `priority_rung None` → `szczebel None`),
  `test_priorytet_zamowien_indeks_widoczny_nie_position` (trasa `zaladowana` ze szczeblem nad ★★★★★ — ukryta, ale
  z `position` 1; zamówienie z `priority_rung` = indeksem „Po terminie” na liście widocznych → plakietka „Po terminie”,
  nie sąsiedni szczebel), `test_priorytet_zamowien_nieaktywne_bez_rangi` (zamówienie z samymi pozycjami `wstrzymane`
  i starą `priority_rank` 3 → `ranga is None`, `szczebel is None`), `test_etykiety_powodow_pokrywaja_kody`
  (`set(ETYKIETY_POWODOW_ODLOZENIA) == set(POWODY_ODLOZENIA)`),
  `test_makra_plakietek` (render makr przez `app.jinja_env.from_string`: 0 gwiazdek → pusto, 3 → trzy „★”, tag
  `po_terminie` → klasa `prio-po_terminie` i tekst „Po terminie”, doróbka → „Doróbka”, nazwa trasy z `<b>` ucieczona).
- [x] **Step 2: Testy padają.** **Step 3: Implementacja** wg „Produces”. **Step 4: Testy przechodzą** + testy K2/K3
  (`tests/test_priorytety_panel_api.py`, `tests/test_priorytety_mobile.py`) zielone. **Step 5: Commit**
  `feat(priorytety): odczyty widoku dla czytelnikow rangi i makra plakietek`

---

### Task 2: Zakładka Stanowiska — stół, odłożone, niekompletne, 15 kafli kolejki

**Files:**
- Modify: `modules/production/routers/api/stations_api.py`, `modules/production/templates/components/stations-tab-content.html`,
  `modules/production/static/css/stations-tab.css`, `tests/test_priorytety_czytelnicy.py`
- Modify (tylko decyzja A): `modules/production/templates/panel/dashboard.html`, `modules/production/static/js/production-app-loader.js`

**Stan obecny (ugruntowanie):**
- `stations_api.py:16-155` (`stations_tab_content`, `@login_required`): pięć lokalnych map stanowisk (`:32`, `:35-43`,
  `:68-76`, `:96-114`), `pending_products` = 20 pozycji po `priority_rank` (`:48-52`), `high_priority` =
  `priority_rank <= 100` (`:56-59`). Odpowiedź `{success, html, data, last_updated}` (`:139-144`).
- Szablon `stations-tab-content.html`: kropka i „pilne” z `high_priority` (`:21-23`, `:44-46`), klasy rangi
  `<= 10/50/100` (`:74-78`), sekcja „Produkty wymagające uwagi” = `priority_rank <= 10` (`:120-209`), martwy
  `startProcessing` z `alert('Funkcja będzie wkrótce dostępna')` (`:262-266`). `navigateToStation` i
  `viewFullStationList` (`:224-260`) pilnuje `tests/test_stanowiska_tab_adresy_monitorow.py` — zostają bez zmian.
- **Zakładka nie jest podpięta w panelu:** `templates/panel/dashboard.html:36-107` ma przyciski dashboard, products,
  archive, logistics, sawmill, reports, workers, config; `production-app-loader.js:90-91` i `:274-283` nie znają
  `stations-tab`; `stations-tab.css` nie jest nigdzie dołączany (grep). Jedyny klient JS: nieużywane
  `shared-services.js:249` (`getStationsTabContent`). Endpoint i szablon testują `tests/test_stanowiska_tab_krawedzie.py`
  i `tests/test_stanowiska_tab_adresy_monitorow.py`. Decyzja o podpięciu — Pytania do Konrada, p. 1.

**Interfaces:**
- Consumes: `widok.stoly_panelu()`, `widok.kolejka_stanowiska(S, limit=15)`, makra z Task 1.
- Produces (`data[<kod>]` w JSON i kontekst szablonu): dotychczasowe `name`, `icon`, `stats.total_pending`,
  `stats.today_completed`, `stats.today_volume` plus `stats.na_stole`, `stats.miejsca`, `stats.odlozone`,
  `stats.limit_odlozen`, `stats.kolejka_dalej`, `tryb`, `jednostka`, `stol: [kafel]`, `odlozone: [kafel + powod, notatka,
  odlozono, pracownik]`, `niekompletne: [...]`, `kolejka: [kafel]` (≤ 15), `blad_priorytetow: bool`. Usunięte:
  `stats.high_priority`, `pending_products`.
- Szkic:
  ```python
  try:
      stoly = {s['stanowisko']: s for s in widok.stoly_panelu()}
      kolejki = {kod: widok.kolejka_stanowiska(kod, limit=15) for kod in STATION_ORDER}
      blad = False
  except Exception:
      logger.error(...); stoly, kolejki, blad = {}, {}, True      # zakładka dalej działa (Global Constraints)
  ```

- [x] **Step 1: Testy, które padną** (`tests/test_priorytety_czytelnicy.py`, fixture `krawedzie_fixtures.app`):
  `test_zakladka_stanowisk_stol_i_odlozone_z_widoku` (Sklejanie: kafel na stole i odłożony z powodem `brak_materialu`
  i pracownikiem; oba w `data.gluing` i w HTML, odłożony z tekstem „brak materiału”), `test_zakladka_stanowisk_kolejka_15_z_kandydatow`
  (20 pozycji na Sklejaniu → `kolejka` ma 15 i tę samą kolejność co `widok.kolejka_stanowiska('gluing', 15)['kafle']`;
  pozycja ze stołu nie występuje), `test_zakladka_formatowania_niekompletne_z_brakujacymi` (zamówienie 1/2 na
  Formatowaniu, druga pozycja na Sklejaniu → sekcja „Niekompletne”, „1/2”, „Sklejanie”),
  `test_zakladka_lakierni_lista_bez_stolu` (Doprecyzowania 15: `data.painting` bez `stol`/`odlozone`/`tryb`, `kolejka`
  = pierwsze 15 pozycji w kolejności `lista.porzadek_listy('painting', …)` z nazwą grupy wykończenia; w HTML karty Lakierni
  brak „Na stole” i paska trybu),
  `test_zakladka_bez_progow_rangi_i_sekcji_priority` (na źródle szablonu: brak `priority-section`, `priority_rank <=`,
  `high_priority`, `startProcessing`; na źródle `stations_api.py`: brak `priority_rank <=`),
  `test_zakladka_kropka_to_odlozone` (`title="1 odłożonych"`, brak kropki przy 0), `test_zakladka_gwiazdki_i_plakietka_trasy`,
  `test_zakladka_przezywa_blad_priorytetow` (monkeypatch `widok.stoly_panelu` rzuca → 200, `total_pending` poprawne,
  w HTML komunikat „Stół i kolejka chwilowo niedostępne”),
  `test_zakladka_stanowisk_bez_blokad_i_zapisow` (`Zapytania`: brak `FOR UPDATE`, `LOCK IN SHARE MODE`, `INSERT`,
  `UPDATE`, `DELETE`; szpieg na `db.session.commit` pusty), `test_monitor_i_zakladka_nie_wolaja_dopelnij` (szpieg
  `stol.dopelnij` — tu część zakładki; monitory w Task 6). Istniejące `tests/test_stanowiska_tab_krawedzie.py`
  i `tests/test_stanowiska_tab_adresy_monitorow.py` muszą zostać zielone bez zmian.
  Decyzja A dodatkowo: `test_panel_ma_zakladke_stanowisk` (na źródle `dashboard.html`: `id="stations-tab"`,
  `id="stations-tab-content"`, link `css/stations-tab.css?v=`; `production-app-loader.js`: `'stations-tab'` w `validTabs`
  i `case 'stations-tab': await this.loadStationsTab()`, a **nie** w liście skrótów Ctrl; reszta asercji w Step 6).
- [x] **Step 2: Testy padają.**
- [x] **Step 3: `stations_api.py`** wg szkicu. Lokalne mapy nazw i ikon zostają (bez refaktoru), mapa statusów →
  `STATION_PENDING_STATUS` (już jest w `station_catalog`, tego samego używa K2). `today_*` bez zmian.
- [x] **Step 4: Szablon** — na karcie stanowiska: pasek „Tryb: stół / zgodność (stara appka)”, „Na stole n/K”,
  „Odłożone n/limit”; sekcja „Na stole” (kafel: `short_id` albo numer zamówienia, materiał i wymiary dla pozycji,
  gwiazdki, plakietka, „od 9:12”); „Odłożone” (+ powód po polsku z `powod_etykieta` — Doprecyzowania 13, notatka,
  godzina, pracownik); „Niekompletne” (tylko jednostka `zamowienie`); „Dalej w kolejce (pierwsze 15)” — tabela: lp., id,
  gwiazdki, plakietka, materiał/grubość (jednostka `pozycja`), termin (kolory z dzisiejszego `deadline-text`).
  Pusty stół w trybie `stary` — bez sekcji (Decyzje 8). „Pokaż wszystkie” → monitor (bez zmian). Usuń `priority-section`
  i `startProcessing`. Makra przez `{% import 'components/_priorytet_plakietki.html' as prio %}`. **Nie dodawaj**
  nowych wywołań `navigateToStation('…')` w sekcjach stołu/kolejki: `test_lakiernia_stoi_zaraz_za_krawedziami_w_przeplywie`
  porównuje listę wszystkich takich wywołań w HTML z 7 kodami (kliknięcie kafla → `viewProductDetails`, jak dziś).
  Pętla po `stations_data.items()` zostaje w kolejności `STATION_ORDER` (jsonify sortuje klucze `data`, kolejność niesie
  tylko HTML).
- [x] **Step 5: CSS** `stations-tab.css`: style sekcji i klas `prio-*`; usuń `.priority-section`, `.priority-badge`,
  `.priority-table` (`:396-450`, `:511-516`) i klasy progów `.priority-value.*` (`:313-335`), jeśli po zmianie szablonu
  nic ich nie używa (grep).
- [x] **Step 6 (tylko decyzja A): podpięcie zakładki** — przycisk „Stanowiska” w `dashboard.html` (po „Lista produkcyjna”
  wg K4a albo po `products-tab`, jeśli K4a jeszcze nie scalone), pusty `tab-pane` `stations-tab-content` z wrapperem jak
  `workers-tab-content` (`:282`), `<link … css/stations-tab.css?v=20261005>`; w `production-app-loader.js`
  `loadStationsTab()`, `'stations-tab'` w `validTabs` (`:90`) i `case` w `:274-283`. Ugruntowanie (sprawdzone na kodzie):
  - **Nie** dopisuj `stations-tab` do listy z `:770` — to skróty Ctrl+1…7 (warunek `event.key <= '7'`, komentarz
    `:763-765`: „bez Pracowników”, inaczej Konfiguracja wypada poza skróty). Stanowiska, jak Pracownicy, bez skrótu.
  - `/stations-tab-content` oddaje JSON `{success, html}`, nie HTML jak `workers/tab-content` — wzór to
    `loadReportsTab()` (`:479-515`: `wrapper.innerHTML = response.html` + `executeInlineScripts`), ale przez zwykły
    `fetch` (nagłówek `X-Requested-With`), **nie** `apiClient.getStationsTabContent()`: `ApiClient.request`
    (`shared-services.js:116-131`) cache'uje udane GET-y, więc odświeżenie oddawałoby stary stół.
  - `refreshWorkflowData()` (szablon `:240-244`) woła `window.loadTabContent`, które **nie istnieje** (por. komentarz
    `reports/system.html:60-63`) — przycisk „Odśwież” i timer 120 s są dziś martwe. Zamień na wzór
    `workers-tab-content.html:390-397`: `window.ProductionApp.state.tabCache.delete('stations-tab');
    window.ProductionApp.loadTabContent('stations-tab')`.
  - `initStationsTab()` wykonuje się przy każdym wstawieniu HTML (`executeInlineScripts`), więc bez osłony każde
    odświeżenie dokłada kolejny `setInterval`. Osłona: `if (window.__stanowiskaTimer) clearInterval(window.__stanowiskaTimer);
    window.__stanowiskaTimer = setInterval(...)`.
  Test `test_panel_ma_zakladke_stanowisk` dodatkowo: brak `window.loadTabContent` w szablonie, `clearInterval(` w
  `initStationRefreshTimers`, lista skrótów z `:770` bez `stations-tab`.
- [x] **Step 7: Testy przechodzą** (plik + oba istniejące testy zakładki). **Podgląd:** otwórz zakładkę (decyzja A) albo
  `GET /production/api/stations-tab-content` i wstaw `html` do pustej strony podglądu (decyzja B); zrzut do raportu.
  Zmierz czas odpowiedzi na podglądzie z realistyczną liczbą pozycji; > 1 s → meldunek, bez optymalizacji na własną rękę.
- [x] **Step 8: Commit** `feat(priorytety): zakladka Stanowiska pokazuje stol, odlozone i kolejke stanowiska`

---

### Task 2a (karta): Zakładka Stanowiska — źródło kafla, „Zdejmij ze stołu”, stół dłuższy niż K, widma

**Files:**
- Modify: `modules/production/priorytety/services/widok.py` (`_stol_stanowiska`), `stations-tab-content.html`,
  `stations-tab.css`, `tests/test_priorytety_czytelnicy.py`, `tests/test_priorytety_panel_api.py` (zbiór kluczy
  `test_stoly_panelu_ksztalt` + `widma`)

**Ugruntowanie:** spec 5.1 (źródła `kolejka|dorobka|biuro|start`, stół może mieć więcej kafli niż K), 5.7 („Zdejmij”:
`POST /production/api/priorytety/stoly/<S>/zdejmij {unit_key}`, `guard`, 404 `brak_kafla`), 7.2 (zakładka „ze źródłem
kafla” i „Zdejmij ze stołu”), raport K3 D2 (wiersz-widmo: kafel `o:` zamówienia bez pozycji na stanowisku zostaje,
liczy się do K, a `GET /stoly` go ukrywa — biuro nie ma jak kliknąć „Zdejmij”), D7 / pytanie 9 („Zdejmij” na doróbce
albo pierwszym kaflu kolejki jest pozorne — opis w panelu, decyzja centrali).

**Interfaces (Produces):**
- `widok.stoly_panelu()` — każdy słownik stanowiska dostaje `widma: [{"unit_key", "order_id", "numer", "product_id",
  "short_id", "zrodlo", "pobrano", "odlozony": bool, "opis"}]` = wiersze stołu stanowiska, których dziś nie pokazuje
  ani `stol`, ani `odlozone`: kafel pozycji, która już nie czeka na stanowisku („pozycja już nie czeka na
  stanowisku”), kafel zamówienia bez pozycji na stanowisku („zamówienie bez pozycji na stanowisku”), wiersz innej
  jednostki niż bieżąca („kafel innej jednostki (po zmianie ustawień)”). Zwykłe odczyty; dodatkowe zapytania tylko,
  gdy widma są. Kształt `GET /stoly` rośnie o klucz `widma` (zawsze obecny, lista).
- Kafle `stol` i `odlozone` dostają `wroci_przy_dopelnieniu: bool` — kafel zdjęty wróci przy najbliższym dopełnieniu:
  doróbka albo kafel, który po zdjęciu stanąłby **pierwszy** w kolejce stanowiska (kolejność z
  `kolejka.kandydaci_stanowiska` na wejściu bez ukrywania stołu — jedno dodatkowe wywołanie czystej funkcji na
  stanowisko, bez zapytań; Pakowanie bez sposobu dostawy nie wraca).
- Szablon: plakietka źródła na kaflu stołu (`zrodlo-biuro` „wysłane przez biuro”, `zrodlo-start` „rozpoczęte przed
  startem”, `zrodlo-dorobka` „doróbka”; `kolejka` bez plakietki), przycisk „Zdejmij ze stołu”
  (`zdejmijZeStolu('<kod>', '<unit_key>', wroci)`) przy każdym kaflu stołu, odłożonym i widmie; przy
  `wroci_przy_dopelnieniu` podpis „kafel wróci przy następnym dopełnieniu”. Sekcja „Do zdjęcia” z widmami i opisem.
  Nagłówek „Na stole n/K” — przy n > K dopisek „ponad K”. Lista stołu bez stałej liczby miejsc (przewijana).
- JS w szablonie: `async function zdejmijZeStolu(stanowisko, unitKey, wroci)` — `confirm` (z ostrzeżeniem
  „Kafel wróci przy następnym dopełnieniu…” gdy `wroci`), `fetch(... '/production/api/priorytety/stoly/' +
  stanowisko + '/zdejmij', {method: 'POST', JSON {unit_key}})`, 200 → odświeżenie zakładki (`refreshWorkflowData`),
  404 `brak_kafla` → komunikat „Tego kafla nie ma już na stole” i odświeżenie, inny błąd → `message` z odpowiedzi.
  Nie dodaje wywołań `navigateToStation('…')`.

- [x] **Step 1: Testy, które padną:** `test_stoly_panelu_widma_widoczne_do_zdjecia` (kafel `o:` zamówienia, którego
  pozycja zeszła ze stanowiska, i kafel `p:` pozycji w innym statusie → `widma` z opisem, ani w `stol`, ani w
  `odlozone`), `test_stoly_panelu_widmo_innej_jednostki`, `test_stoly_panelu_wroci_przy_dopelnieniu` (doróbka → True;
  kafel, który byłby pierwszy w kolejce → True; kafel daleko w kolejce → False), `test_zakladka_zrodlo_kafla_plakietki`
  („wysłane przez biuro”, „rozpoczęte przed startem”, „doróbka” w HTML karty Sklejania), `test_zakladka_zdejmij_ze_stolu`
  (HTML: `zdejmijZeStolu('gluing', 'p:<id>'` przy kaflu stołu, odłożonym i widmie; podpis „kafel wróci przy
  następnym dopełnieniu” tylko przy kaflu z flagą), `test_zakladka_stol_dluzszy_niz_k` (5 kafli przy K=2 → wszystkie
  w HTML, „5/2”, „ponad K”), `test_zakladka_js_zdejmij_przez_post` (na źródle szablonu: funkcja woła
  `/production/api/priorytety/stoly/`, `'/zdejmij'`, `method: 'POST'`, `confirm(`, obsługa `brak_kafla`),
  `test_stoly_i_odlozenia_bez_blokad_i_zapisow` (K3) zielony z widmami.
- [x] **Step 2: Testy padają.** **Step 3: Implementacja** wg Interfaces. **Step 4: Testy przechodzą** (plik czytelników,
  `tests/test_priorytety_panel_api.py`, testy zakładki). **Step 5: Commit**
  `feat(priorytety): zakladka Stanowiska - zrodlo kafla, Zdejmij ze stolu i widma`

---

### Task 3: Dashboard — pilne zamówienia; raporty — regresja `is_priority`

**Files:**
- Modify: `modules/production/routers/api/dashboard_api.py`, `tests/test_priorytety_czytelnicy.py`, `tests/test_reports_service.py`

**Stan obecny (ugruntowanie):**
- `dashboard_api.py:254-461` (`dashboard_stats`, `GET /production/api/dashboard-stats`): `high_priority_count` =
  pozycje z `priority_rank <= 10` (`:314-317`, komentarz „(>=150)”), alert „N produktów z priorytetem ≥150” przy `> 10`
  (`:366-374`), pole w `stats` (`:395`). `avg_priority` per status (`:282-308`) i lista `include_products` po
  `priority_rank` (`:410-438`) — po K1 ranga = ranga zamówienia × 100 + sekwencja, więc sort zostaje poprawny,
  a średnia zmienia skalę (brak konsumenta, Poza zakresem).
- Konsumenci: **żaden JS nie woła `/dashboard-stats`** (`shared-services.js:213` definiuje `getDashboardStats`, nikt go nie
  używa); `dashboard-module.js:208` czyta `/dashboard-stats-data` (`pending_priority`, `:1496-1504` — termin ≤ 3 dni, nie
  ranga; poza zakresem). Testów `/dashboard-stats` w repo nie ma.
- Ten sam próg rangi czytają jeszcze: `modules/production/__init__.py:132-163` (`get_high_priority_items_count`, eksport
  `:192`, nikt nie woła) i `routers/admin_routers.py:138-144` (`high_priority_products` w panelu admina) — **spoza listy
  spec 9.5**; do raportu (Poza zakresem), bez zmian.
- Raporty: `services/reports_service.py:413` (`termin_vs_postep`), `:514` (`'is_priority': bool(produkt.is_priority)`),
  render `components/reports/deadlines.html:500` (ikona błyskawicy). Od K1 `is_priority` = doróbka ∨ ★≥1 ∨ po terminie.

**Interfaces:**
- Consumes: `widok.liczba_pilnych_zamowien()` (Task 1).
- Produces: `_safe_pilne_zamowienia() -> Optional[int]` w `dashboard_api.py` (wzór `_safe_tempo`, `:150-163`); pole
  `stats.high_priority_count` (int albo `null`); alert wg Doprecyzowań 4.

- [x] **Step 1: Testy, które padną:** `test_high_priority_count_to_zamowienia_na_szczeblach_pilnych` (zamówienie ★5 z trzema
  pozycjami liczy się raz; ★3 i „Blisko terminu” nie), `test_high_priority_count_rowny_sumie_licznikow_drabiny`
  (ten sam zestaw: wynik == suma `w_produkcji` z `widok.drabina_panelu()` dla `SZCZEBLE_PILNE`),
  `test_alert_pilnych_bez_progu_150` (11 pilnych → alert z „zamówień” i „★★★★★”; brak „≥150” w odpowiedzi i w źródle
  `dashboard_api.py`), `test_dashboard_stats_przezywa_blad_priorytetow` (monkeypatch rzuca → 200, `high_priority_count is None`,
  brak alertu pilnych), `test_dashboard_stats_bez_blokad_i_zapisow` (`Zapytania`, jak Task 2). W
  `tests/test_reports_service.py` (fixture tego pliku): `test_termin_vs_postep_is_priority_z_kolumny_pochodnej`
  (pozycja z `is_priority=True` ustawionym jak po `utrwal()` dla ★1 → `True` w `wynik['items']` — klucz odpowiedzi
  `termin_vs_postep` to `items`, `reports_service.py:528`; bez gwiazdek → `False`).
- [x] **Step 2: Testy padają** (raport może przejść od razu — wtedy zapisz w raporcie, że to test regresji).
- [x] **Step 3: Implementacja** — zamień `:314-317` na `_safe_pilne_zamowienia()`, alert `:366-374` na `if (n or 0) > 10`
  z nowym tytułem i treścią, komentarz nad polem bez „≥150”. Nic więcej w `dashboard_api.py`.
- [x] **Step 4: Testy przechodzą** + `tests/test_dashboard_*.py`. **Step 5: Commit**
  `feat(priorytety): dashboard liczy pilne zamowienia z drabiny`

---

### Task 4: Konfiguracja — backend: terminy w `PUT /ustawienia`, allowlista, martwe klucze

**Files:**
- Modify: `modules/production/priorytety/services/ustawienia.py`, `modules/production/routers/api/config_api.py`,
  `modules/production/services/config_service.py`, `tests/test_priorytety_panel_api.py`, `tests/test_priorytety_czytelnicy.py`

**Stan obecny (ugruntowanie):**
- `config_api.py:137-379` (`config_tab_content`, `@login_required`): `EXPECTED` z grupą `priorities` (`:226-230`:
  `DEADLINE_DEFAULT_DAYS`, `DEADLINE_FINISHED_DAYS`, `PRIORITY_RECALC_INTERVAL_HOURS`, `PRIORITY_ALGORITHM_VERSION`),
  heurystyka grup (`:288-305`; klucze `priorytety_*` trafiają do `other` — szablon nie iteruje grup, więc ich nie
  pokaże), odczyt `ProductionPriorityConfig` (`:328-333`) i pole `priority_configs` (`:344-352`, `:362`) — szablon
  go **nie** używa (grep `priority_configs` w szablonie i JS → pusto).
- `config_api.py:456-605` (`update_configs`, `@admin_required`): allowlista `:506-529` z `DEADLINE_DEFAULT_DAYS` (`:510`),
  `PRIORITY_RECALC_INTERVAL_HOURS`, `PRIORITY_ALGORITHM_VERSION` (`:511`), `STATION_{CUTTING,ASSEMBLY,PACKAGING}_PRIORITY_SORT`
  (`:517-518`); `DEADLINE_FINISHED_DAYS` w niej nie ma. Pusty nagłówek sekcji „PRIORITY STAR ENDPOINTS” `:800-803`.
- `config_service.py:60-76` (`_default_values`): `DEADLINE_DEFAULT_DAYS: 16`, `DEADLINE_FINISHED_DAYS: 21`,
  `PRIORITY_RECALC_INTERVAL_HOURS: 24` (`:75`); po K1 także `DEADLINE_DAY_TYPE`. Walidacja `DEADLINE_DEFAULT_DAYS` 1–365
  (`:400-403`) zostaje (używa jej tylko `update-configs`/`validate-config`).
- **Szablon czyta te klucze kropkowo** (`config-tab-content.html:1314-1406`:
  `config_groups.priorities.DEADLINE_DEFAULT_DAYS.updated_by|default(...)`). Brak klucza w `EXPECTED` i w bazie daje
  `Undefined` → `.updated_by` rzuca `UndefinedError` (filtr `default` stoi za atrybutem, za późno) → 500 całej zakładki.
  Dlatego wpisy grupy `priorities` znikają z `EXPECTED` **razem z kartą, w Task 5**, nie tutaj.
- `POST /update-config` (`config_api.py:18-128`, `admin_required`) zapisuje **dowolny** klucz przez `set_config` — bez
  allowlisty; nikt go nie woła z UI (grep), ale to druga droga zapisu kluczy priorytetów i terminów (Doprecyzowania 14).
- Drugi czytelnik `ProductionPriorityConfig`: `routers/main_routers.py:228-254` (stary panel `panel/config.html`) —
  poza zakresem K4b, **do raportu dla K8** (DROP położy ten widok).
- Czytelnicy martwych kluczy w Pythonie: brak (grep `PRIORITY_RECALC_INTERVAL_HOURS|PRIORITY_ALGORITHM_VERSION|PRIORITY_SORT`
  poza `config_api.py`, `config_service.py:75`, JS i szablonem → tylko migracja `2026-09-15-krawedzie-podzial-wykanczania.sql:238-251`
  i jej test, których **nie** ruszamy — historyczna migracja).
- K2: `ustawienia.waliduj/zapisz/odczyt_panelu` i `GET`/`PUT /ustawienia` (K2 Task 5, mapa pól i zakresy).

**Interfaces:**
- Produces (`ustawienia.py`, rozszerzenie K2): mapa pól + `deadline_default_days` → (`DEADLINE_DEFAULT_DAYS`, int 1–90,
  `integer`), `deadline_finished_days` → (`DEADLINE_FINISHED_DAYS`, int 1–90, `integer`); `odczyt_panelu()` zwraca oba
  (wartość z `prod_config`, brak wiersza → `config_service` domyślne 16/21). Zmiana tych pól **nie** ustawia
  `przeliczenie: ok` (wynik `niepotrzebne`).
- Produces (HTTP, bez nowych końcówek): `GET`/`PUT /production/api/priorytety/ustawienia` z dwoma nowymi polami;
  `POST /production/api/update-configs` odrzuca 400 „Niepozwolone klucze konfiguracji” dla: `DEADLINE_DEFAULT_DAYS`,
  `DEADLINE_FINISHED_DAYS`, `DEADLINE_DAY_TYPE`, `priorytety_*`, `PRIORITY_RECALC_INTERVAL_HOURS`,
  `PRIORITY_ALGORITHM_VERSION`, `STATION_*_PRIORITY_SORT`; `POST /production/api/update-config` odrzuca 400 klucze
  z prefiksem `priorytety_` i `DEADLINE_` (Doprecyzowania 14), przed walidacją typu i przed `set_config`.

- [x] **Step 1: Testy, które padną:**
  `tests/test_priorytety_panel_api.py` (fixture K2): `test_ustawienia_terminow_przez_put` (`deadline_finished_days: 10`
  → wiersz `prod_config` `'10'`/`integer`, wpis logu `ustawienia` z `note='DEADLINE_FINISHED_DAYS'`, `przeliczenie ==
  'niepotrzebne'`, `GET` oddaje 10), `test_ustawienia_terminow_walidacja_400` (parametryzowany: 0, 91, `True`, `"10"` →
  `ustawienie_niepoprawne` z `pole`), `test_ustawienia_odczyt_domyslny` — **zaktualizuj** test K2 o dwa pola (16, 21),
  jeśli porównuje cały słownik (odnotuj w raporcie).
  `tests/test_priorytety_czytelnicy.py` (fixture `krawedzie_fixtures.app`, nagłówek `X-Requested-With: XMLHttpRequest`):
  `test_update_configs_odrzuca_klucze_priorytetow_i_terminow` (parametryzowany po 5 kluczach → 400, wiersz w bazie bez
  zmian), `test_update_configs_odrzuca_martwe_klucze` (5 kluczy → 400), `test_update_configs_przyjmuje_pozostale`
  (`REFRESH_INTERVAL_SECONDS: 45` → 200, regresja), `test_update_config_pojedynczy_odrzuca_priorytety_i_terminy`
  (parametryzowany: `priorytety_tryb_gluing`, `DEADLINE_DAY_TYPE`, `DEADLINE_DEFAULT_DAYS` → 400, wiersz bez zmian;
  `REFRESH_INTERVAL_SECONDS` → 200), `test_zakladka_konfiguracji_bez_prod_priority_config`
  (`GET /production/api/config-tab-content` → 200 na fixturze **bez** tabeli `prod_priority_config`; brak klucza
  `priority_configs` w `data`), `test_martwe_klucze_priorytetow_usuniete_z_kodu` (na źródle `config_api.py`,
  `config_service.py`, `config-module.js`, `config-tab-content.html`: zero trafień `PRIORITY_RECALC_INTERVAL_HOURS`,
  `PRIORITY_ALGORITHM_VERSION`, `_PRIORITY_SORT` — część JS/szablonu zazieleni Task 5; do tego czasu test oznacz
  `xfail(strict=True)` z powodem „Task 5”).
- [x] **Step 2: Testy padają.**
- [x] **Step 3: Implementacja** — `ustawienia.py` wg „Produces”; `config_api.py`: wpisów grupy `priorities`
  w `EXPECTED` **jeszcze nie ruszaj** (Task 5, razem z kartą — „Stan obecny”), usuń odczyt i pole `priority_configs` oraz
  argument `priority_configs=` w `render_template`, usuń z allowlisty `DEADLINE_DEFAULT_DAYS`, oba `PRIORITY_*`, trzy
  `STATION_*_PRIORITY_SORT` (komentarz nad allowlistą: „klucze priorytetów i terminów zapisuje wyłącznie
  `PUT /production/api/priorytety/ustawienia` — jedna droga zapisu, plan K4b”), w `update_config` odmowa prefiksów
  (Doprecyzowania 14), usuń pusty nagłówek `:797-800`; `config_service.py:75` — usuń `PRIORITY_RECALC_INTERVAL_HOURS`.
  Import `ProductionPriorityConfig` usuń w **obu** miejscach `config_api.py` (`:14` na poziomie modułu i `:158`
  w `config_tab_content`), jeśli po zmianie nieużywany (`grep -n ProductionPriorityConfig config_api.py` → pusto).
- [x] **Step 4: Testy przechodzą** (oba pliki, `tests/test_config_service_set.py`, `tests/test_druk_wydruk_probny.py`).
  **Step 5: Commit** `refactor(priorytety): terminy w ustawieniach priorytetow, allowlista bez martwych kluczy`

---

### Task 5: Konfiguracja — karty „Terminy” i „Stół stanowisk” w UI

**Files:**
- Modify: `modules/production/templates/components/config-tab-content.html`, `modules/production/static/js/modules/config-module.js`,
  `modules/production/static/css/config-tab.css`, `modules/production/templates/panel/dashboard.html:14`, `:365`,
  `modules/production/routers/api/config_api.py` (`EXPECTED` grupy `priorities`, kontekst wierszy stołu),
  `tests/test_druk_panel_ui.py`, `tests/test_priorytety_czytelnicy.py`

**Stan obecny (ugruntowanie):**
- Szablon: karta „Priorytety i Deadlines” `config-tab-content.html:1283-1417` (komentarz-znacznik `:1283`, pole
  `deadline_days` z `configChanged('DEADLINE_DEFAULT_DAYS', …)` `:1298-1336`, opis „domyślnie: 14 dni” niezgodny z serwerem
  (16), `PRIORITY_RECALC_INTERVAL_HOURS` `:1338-1376`, `PRIORITY_ALGORITHM_VERSION` `:1378-1416`); następna karta
  `<!-- System i Debug -->` `:1419`. Karta Trakownia `:1789-1945` — wzór pól zapisywanych osobno.
- JS `config-module.js`: `defaultValues` z martwymi kluczami (`:54-56`, `:65-67`; `DEADLINE_DEFAULT_DAYS: 14` `:54`),
  mapy pól w `loadOriginalValues` (`:238-240`), `updateFormField` (`:675-677`), `getFieldIdFromConfigKey` (`:805-807`);
  `loadOriginalValuesFromDOM` (`:117-129`) woła `loadSawmillSettings()` (`:137-176`) — wzór dla nowych kart;
  `showToast` `:1196`.
- `tests/test_druk_panel_ui.py`: `_karta_drukarki` kończy kartę drukarki na `'<!-- Priorytety i Deadlines -->'`
  (`:30-33`); `test_nowa_wersja_skryptu_i_stylu_konfiguracji` przypina `config-module.js?v=20260930b` i
  `config-tab.css?v=20260930` (`:198-203`; `dashboard.html:14`, `:365`).

**Interfaces:**
- Produces (szablon): `<!-- Terminy -->` karta z polami `#prio_deadline_default_days`, `#prio_deadline_finished_days`
  (number 1–90), `#prio_deadline_day_type` (select `robocze`/`kalendarzowe`, opis: „Dotyczy tylko zamówień importowanych
  po zmianie — terminy w bazie się nie zmieniają”), przycisk `#prio_terminy_zapisz`; `<!-- Stół stanowisk -->` karta
  z tabelą 7 wierszy (`data-stanowisko="<kod>"`: `select.prio-tryb`, `input.prio-miejsca` 1–5, `select.prio-jednostka`,
  `input.prio-limit` 1–50; wiersz `painting` tylko z napisem „Lista (bez stołu)”, bez tych pól — Doprecyzowania 15,
  test `test_konfiguracja_lakierni_bez_wyboru_trybu` na źródle szablonu i JS: brak `stanowiska.painting` w ciele `PUT`), `#prio_blisko_terminu_dni` (0–15, „dni robocze”), `#prio_min_app_version_code` (≥ 0,
  opis: „0 = bez bramki wersji; ustawia K7 przed przełączeniem pierwszego stanowiska na stół”), przycisk
  `#prio_stol_zapisz`. Żadne z tych pól nie ma `configChanged(...)`. Wiersze tabeli renderuje pętla Jinja po
  `stanowiska_stolu` — nowy argument `render_template` w `config_tab_content`: `[(kod, station_label(kod)) for kod in
  STATION_ORDER]` (bez odczytu `prod_config`; wartości wpisuje JS z `GET /ustawienia`).
- Produces (JS, metody `ConfigModule`): `async loadPriorytetyUstawienia()` (GET, wypełnia pola, brak kart w DOM → cicho;
  403 — zakładkę Konfiguracja widzi każdy z dostępem do modułu, `production-app-loader.js:525`, a `GET /ustawienia` jest
  tylko dla admina — pola obu kart `disabled`, przyciski ukryte, napis „Tylko administrator”, bez toastu błędu),
  `async savePriorytetyUstawienia(karta)` (`'terminy'|'stol'`; ciało = tylko pola różne od ostatnio wczytanych, kształt
  K2: `{"stanowiska": {"gluing": {"miejsca": 1}}, "blisko_terminu_dni": 3, …}`; 200 → toast z `przeliczenie`, odświeżenie
  pól z odpowiedzi; 400 → `is-invalid` na polu z `pole` i toast `message`; 403 → „Tylko administrator może zmieniać
  ustawienia priorytetów”), globalny `window.savePriorytetyUstawienia`. `loadOriginalValuesFromDOM` woła
  `loadPriorytetyUstawienia()` obok `loadSawmillSettings()`.

- [x] **Step 1: Testy, które padną** (na źródle, konwencja `tests/test_druk_panel_ui.py`):
  `test_karty_terminow_i_stolu_w_szablonie` (na źródle: znaczniki `<!-- Terminy -->`, `<!-- Stół stanowisk -->`, id pól
  z „Produces”; na **wyrenderowanym** `GET /production/api/config-tab-content` (fixture `krawedzie_fixtures.app`, bez
  wierszy `prod_config`): 200 i 7 wierszy `data-stanowisko` w kolejności `STATION_ORDER` z nazwami z `station_label`),
  `test_skrypt_obsluguje_403_przy_wczytaniu` (`_metoda(js, 'async loadPriorytetyUstawienia(')` zawiera `403`
  i `disabled`), `test_karty_terminow_i_stolu_poza_pending_changes`
  (w obu kartach brak `configChanged(`; w JS żadna z map pól nie zna `prio_*`),
  `test_skrypt_zapisuje_przez_put_ustawienia` (`_metoda(js, 'async savePriorytetyUstawienia(')` zawiera
  `'/production/api/priorytety/ustawienia'` i `method: 'PUT'`; `loadOriginalValuesFromDOM` woła
  `this.loadPriorytetyUstawienia()`), `test_skrypt_obsluguje_403_i_pole_bledu` (`403`, `result.pole`, `is-invalid`),
  `test_brak_karty_priorytety_i_deadlines` (brak `Priorytety i Deadlines`, `id="deadline_days"`, `priority_recalc`,
  `priority_version`). Zdejmij `xfail` z `test_martwe_klucze_priorytetow_usuniete_z_kodu` (Task 4).
  `tests/test_druk_panel_ui.py`: `_karta_drukarki` kończy na `'<!-- Terminy -->'`; wersje → nowe (Step 4).
- [x] **Step 2: Testy padają.**
- [x] **Step 3: Implementacja** — w miejscu `:1283-1417` dwie karty (struktura `config-card`/`config-item` jak sąsiednie);
  w **tym samym** commicie `config_api.py`: usuń 4 wpisy grupy `priorities` z `EXPECTED` (`:226-230`; po usunięciu karty
  szablon już ich nie czyta — Task 4 „Stan obecny”) i dodaj `stanowiska_stolu` do `render_template`. W JS usuń martwe
  klucze i `DEADLINE_DEFAULT_DAYS` ze wszystkich czterech map oraz `defaultValues`, dodaj metody i globalną funkcję;
  CSS tabeli stanowisk w `config-tab.css`. Sprawdź `grep -n "config_groups.priorities" config-tab-content.html` → pusto.
- [x] **Step 4: Wersje** w `dashboard.html`: `config-tab.css?v=20261005`, `config-module.js?v=20261005` (K4a może
  równolegle podbić inne pliki — scal, nie nadpisuj); te same wartości w `test_druk_panel_ui.py:198-203`.
- [x] **Step 5: Testy przechodzą:** `tests/test_priorytety_czytelnicy.py tests/test_druk_panel_ui.py tests/test_druk_wydruk_probny.py`.
  **Podgląd** (admin): zmień K Sklejania na 1 i próg na 4 → toast „Zapisano”, ponowne wczytanie zakładki pokazuje
  wartości; `DEADLINE_DAY_TYPE` → `kalendarzowe` i z powrotem; błędna wartość (K=9) → podświetlone pole. Zrzuty kart do
  raportu (przed i po). Przywróć wartości domyślne na podglądzie.
- [x] **Step 6: Commit** `feat(priorytety): karty Terminy i Stol stanowisk w Konfiguracji`

---

### Task 5a (karta): Konfiguracja — sekcja „Start stołów” (spec 5.8)

**Files:**
- Modify: `config-tab-content.html` (karta „Stół stanowisk”), `config-module.js`, `config-tab.css`,
  `tests/test_priorytety_czytelnicy.py`

**Ugruntowanie:** spec 5.8 (podgląd `GET /production/api/priorytety/start` — guard; „Przygotuj stoły”
`POST /start/przygotuj` — admin; „Włącz stoły” = jeden zapis ustawień: `priorytety_min_app_version_code` i
`priorytety_tryb_<S>` = `stol` dla sześciu stanowisk, bez Lakierni), 7.2, 7.3; raport K3 (kształty `GET /start`,
`POST /start/przygotuj`, rozstrz. 39: próg wersji 0 przy trybie `stol` = bramka także dla starej appki; „Poza zakresem”
p. 12 — brak walidacji w `PUT /ustawienia`, więc ostrzeżenie w UI). Jedna droga zapisu ustawień — „Włącz stoły” to
`PUT /ustawienia` (bez nowej końcówki).

**Interfaces (Produces):**
- Szablon w karcie „Stół stanowisk”: sekcja `<!-- Start stołów -->` z `#prio_start_podglad` (lista stanowisk:
  nazwa, liczba kafli rozpoczętych, ile już na stole, rozwijana lista kafli: numer / `short_id`), przyciskami
  `#prio_start_odswiez`, `#prio_start_przygotuj` („Przygotuj stoły”) i `#prio_start_wlacz` („Włącz stoły”) oraz
  opisem kolejności (podgląd → Przygotuj po zakończeniu zmiany → poprawki „Wyślij”/„Zdejmij” → Włącz przed zmianą →
  „Rozpoczęte” na szczyt drabiny).
- JS (`ConfigModule`): `async loadStartStolow()` (GET `/start`, render; błąd → komunikat w sekcji, bez toastu;
  wołana z `loadOriginalValuesFromDOM` obok `loadPriorytetyUstawienia`), `async przygotujStoly()` (`confirm`, POST
  `/start/przygotuj`, toast z liczbą dodanych per stanowisko, 403 → „Tylko administrator”, 500 → komunikat z
  `nieudane`; potem `loadStartStolow()`), `async wlaczStoly()` (wersja z pola `#prio_min_app_version_code`;
  `confirm` z listą sześciu stanowisk; przy wersji 0 dodatkowe ostrzeżenie „próg wersji 0 — stara appka dostanie
  odmowę ZAKOŃCZ na wszystkim spoza stołu”; jedno `PUT /ustawienia` z `{"min_app_version_code": N, "stanowiska":
  {kod: {"tryb": "stol"} × 6}}` — bez `painting`; 200 → odświeżenie pól z odpowiedzi; 400 → `is-invalid` na polu z
  `pole`; 403 → „Tylko administrator”). Globalne `window.przygotujStoly`, `window.wlaczStoly`, `window.odswiezStartStolow`.
- [x] **Step 1: Testy, które padną** (na źródle): `test_sekcja_start_stolow_w_szablonie` (znacznik, id, opis
  kolejności), `test_skrypt_start_stolow_podglad` (`loadStartStolow` woła `/production/api/priorytety/start`,
  `loadOriginalValuesFromDOM` ją woła), `test_skrypt_przygotuj_stoly_post_z_potwierdzeniem` (`confirm(`,
  `/start/przygotuj`, `method: 'POST'`, `403`), `test_skrypt_wlacz_stoly_jednym_put` (`wlaczStoly` ma dokładnie jedno
  `fetch(`, `'/production/api/priorytety/ustawienia'`, `method: 'PUT'`, `min_app_version_code`, `tryb: 'stol'`, sześć
  kodów bez `painting`, ostrzeżenie przy `=== 0`), `test_start_stolow_poza_pending_changes` (brak `configChanged(` w
  sekcji).
- [x] **Step 2: Testy padają.** **Step 3: Implementacja.** **Step 4: Testy przechodzą** (+ `test_druk_panel_ui.py`).
  **Podgląd** (admin, baza `priorytety_podglad` wspólna z K4a): podgląd startu, „Przygotuj stoły”, potem przywrócenie
  stanu (wiersze `start` usunięte przez „Zdejmij” albo SQL tylko na tej bazie); „Włącz stoły” z progiem 0 →
  ostrzeżenie, potwierdzenie, potem tryby z powrotem na `stary`. Zrzuty. **Step 5: Commit**
  `feat(priorytety): Konfiguracja - start stolow (podglad, Przygotuj, Wlacz)`

---

### Task 6: Monitory hali — backend: ranga, stół „TERAZ”, odłożone, plakietki

**Files:**
- Modify: `modules/production/routers/stations/__init__.py`, `modules/production/routers/stations/monitors.py`,
  `tests/test_monitory_krawedzie.py:58-60`
- Create: `tests/test_priorytety_monitory.py`

**Stan obecny (ugruntowanie):**
- `routers/stations/__init__.py:271-364` (`_get_monitor_station_data(station_code) -> (orders, monitor_stats,
  species_stats)`): pozycje w statusie stanowiska z `joinedload(order, configuration)` (`:284-296`), grupowanie po
  `internal_order_number` (`:299-309`), sort „najwyższy postęp” (`:338-342`). `MONITOR_STATION_MAP` `:220-268`.
- `monitors.py`: `monitor_station` (`:52-97`) i `ajax_monitor_station_data` (`:100-127`) wołają
  `_get_monitor_station_data`; monitor zbiorczy `production_monitor` (`:134-291`) i `ajax_production_monitor`
  (`:294-437`) — **dwie niezależne kopie** map i zapytań (pułapka opisana w `tests/test_monitory_krawedzie.py:9-11`),
  grupowanie po `internal_order_number` (`:194-215`, `:354-373`), sort po postępie (`:257`, `:411`).
- Zabezpieczenie: `apply_station_security` (`__init__.py:28-32`), testy montują `station_bp` pod `/production`
  (`tests/test_monitory_krawedzie.py:24-28`, fixture `:73-97`, `TABELE` `:58-60` bez tabel tras i priorytetów).
- K3: `widok.stoly_panelu()` (kafle z `pobrano`, odłożone z `powod`, `notatka`, `odlozono`, `pracownik`), `kolejka_dalej`.

**Interfaces:**
- Produces (`routers/stations/__init__.py`):
  ```python
  def _get_monitor_station_data(station_code):   # -> (orders, monitor_stats, species_stats) — kształt bez zmian
      # orders[*] += order_id, gwiazdki, szczebel, plakietka, dorobka (bool), na_stole (bool)
      # sort: (0 if dorobka else 1, ranga NULLS LAST, order_number)   — Doprecyzowania 8
  def _stol_monitora(station_code):              # -> {"tryb", "jednostka", "miejsca", "stol": [...], "odlozone": [...],
      ...                                        #     "kolejka_dalej": int|None, "blad": bool}; wyjątek → puste + blad
  ```
- Produces (`monitors.py`): `_zamowienia_monitora_ogolnego() -> (orders, stats)` — jedna funkcja dla `production_monitor`
  i `ajax_production_monitor` (te same mapy statusów co dziś, grupowanie po `ProductionOrder.id`, `priorytet_zamowien`,
  sort `(ranga NULLS LAST, order_number)`); obie końcówki tylko ją wołają. AJAX stanowiska: odpowiedź `+ "stol": {...}`
  (wynik `_stol_monitora`); AJAX zbiorczy: każde zamówienie `+ order_id, gwiazdki, szczebel, plakietka`. Szablony dostają
  `stol=` (stanowisko) i nowe pola zamówień.

- [x] **Step 1: Testy, które padną** (`tests/test_priorytety_monitory.py`, fixture jak `test_monitory_krawedzie.py:73-97`
  z `TABELE` + `PriorityRung, PriorityLog, StationDesk, Vehicle, Route, RouteStop` i `drabina_domyslna()`):
  `test_monitor_stanowiska_po_randze_dorobki_pierwsze` (trzy zamówienia na Sklejaniu z rangami 3, 1, `NULL` i czwarte
  z doróbką i rangą 9 → kolejność: doróbka, 1, 3, `NULL`), `test_monitor_html_i_ajax_ta_sama_kolejnosc` (kolejność
  `data-order-id` w HTML == kolejność `order_id` w `orders` AJAX-a, stanowisko i zbiorczy), `test_monitor_ogolny_po_randze`
  (w tym zamówienie z samymi pozycjami `wstrzymane` i starą rangą 1 → na końcu, bez plakietki — Doprecyzowania 8),
  `test_monitor_grupuje_po_id_zamowienia` (dwa zamówienia z tym samym `internal_order_number` → dwie karty z różnym
  `data-order-id`, AJAX: dwa różne `order_id`),
  `test_monitor_stol_teraz_i_odlozone` (tryb `stol`, kafel na stole i odłożony → AJAX `stol.stol` i `stol.odlozone`,
  HTML z „TERAZ” i „Odłożone”, karta zamówienia z kafla ma `na_stole: true`),
  `test_monitor_lakierni_kolejnosc_jak_lista_tabletu` (Doprecyzowania 15: trzy zamówienia na Lakierni, rangi
  zamówień 1, 2, 3, grupy wykończenia ułożone tak, że lista tabletu ma kolejność 2, 1, 3 → karty HTML i AJAX 2, 1, 3;
  plakietka grupy na karcie), `test_monitor_lakierni_bez_stolu_mimo_trybu_stol` (`priorytety_tryb_painting = stol`
  → brak „TERAZ”, AJAX `stol is None`, szpieg `widok.stoly_panelu` niewołany), `test_monitor_bez_stolu_bez_sekcji`
  (tryb `stary`, pusty stół → brak „TERAZ” w HTML), `test_monitor_gwiazdki_i_plakietka_trasy`,
  `test_monitor_przezywa_blad_priorytetow` (monkeypatch `widok.stoly_panelu` i `widok.priorytet_zamowien` rzucają → 200,
  karty są, `stol.blad is True`), `test_monitory_bez_blokad_i_zapisow` (parametryzowany: `/monitors/gluing`,
  `/ajax/monitors/gluing`, `/monitor`, `/ajax/monitor`; `Zapytania` bez blokad i zapisów),
  `test_monitor_i_zakladka_nie_wolaja_dopelnij` (część monitorów: szpieg `stol.dopelnij` pusty).
  `tests/test_monitory_krawedzie.py`: dopisz nowe tabele do `TABELE`; jego testy muszą zostać zielone bez zmian asercji.
- [x] **Step 2: Testy padają.**
- [x] **Step 3: `_get_monitor_station_data`** — klucz grupowania `item.order_id`; `order_number` dalej z
  `internal_order_number`; `dorobka` = któraś pozycja ma `original_product_id`; `priorytet_zamowien(ids)` jednym
  wywołaniem w `try/except` (wyjątek → `logger.error`, pola priorytetu `None`, sort po numerze); `na_stole` z
  `_stol_monitora` (zbiór `order_id` kafli stołu); sort wg Interfaces. `species_stats` i `monitor_stats` bez zmian.
  Import modułowy (`from ...priorytety.services import widok` i wywołania `widok.priorytet_zamowien(...)`,
  `widok.stoly_panelu(...)`), nie `from … import priorytet_zamowien` — inaczej monkeypatch w
  `test_monitor_przezywa_blad_priorytetow` nie podmieni funkcji i test przejdzie bez sprawdzenia osłony.
- [x] **Step 4: `_stol_monitora`** = `widok.stoly_panelu(stanowiska=[kod])[0]` w `try/except` (Global Constraints);
  dla `kod in STANOWISKA_BEZ_STOLU` → `None` bez wołania `stoly_panelu`. W `_get_monitor_station_data` dla `painting`
  sort kart po pierwszym wystąpieniu na `lista.porzadek_listy('painting', items)` zamiast klucza rangi (Doprecyzowania 15).
- [x] **Step 5: `monitors.py`** — przekazanie `stol` do szablonu i AJAX-a stanowiska; `_zamowienia_monitora_ogolnego()`
  zamiast dwóch kopii (komentarze `:151-154`, `:311-314` usunięte razem z kopiami); grupowanie po id: najpierw
  `SELECT DISTINCT prod_orders.id …` dla pozycji poza `STATUSY_PO_SPAKOWANIU`, potem pozycje tych zamówień jednym
  zapytaniem `WHERE order_id IN (…)` (dziś N+1 po numerze, `:213-215`, `:371-373`).
- [x] **Step 6: Testy przechodzą:** `tests/test_priorytety_monitory.py tests/test_monitory_krawedzie.py tests/test_display_monitor_service.py`.
  **Step 7: Commit** `feat(priorytety): monitory hali po randze ze stolem i odlozonymi`

---

### Task 7: Monitory hali — szablony, JS auto-odświeżania, style; sprawdzenie w przeglądarce

**Files:**
- Modify: `modules/production/templates/stations/monitor_station.html`, `monitor.html`,
  `modules/production/static/js/stations/station-monitor.js`, `modules/production/static/css/stations/station-monitor-v2.css`,
  `station-monitor.css`, `tests/test_priorytety_monitory.py`

**Stan obecny (ugruntowanie):**
- `monitor_station.html:71-107` (siatka kart, `data-order`), `:121-128` (`MONITOR_CONFIG.ajaxUrl`), meta refresh 300 s
  (`:8`). `monitor.html:103-151` (inny układ karty), `:166-172` (bez `ajaxUrl` → domyślny `/production/stations/ajax/monitor`,
  `station-monitor.js:57`).
- `station-monitor.js` (891 linii): `generateOrderCardHTML` `:211-239` (szablon literałowy **bez** ucieczki),
  `updateOrderCard` `:244-283`, `refreshMonitorData` `:289-344`, `incrementalUpdateOrders` `:362-447` — nowe karty
  dokleja na koniec (`:428`), **nie przestawia** istniejących, więc zmiana rangi nie zmienia kolejności na ekranie aż do
  przeładowania strony (meta refresh 300 s). Auto-przewijanie `:468-750` liczy siatkę `.orders-grid`.
- Monitor zbiorczy używa tego samego `generateOrderCardHTML` (karta w stylu stanowiska, inna niż w `monitor.html`) —
  istniejąca niespójność, poza zakresem.

**Interfaces:**
- Produces (JS): `escapeHtml(tekst)`, `gwiazdkiHTML(n)`, `plakietkaHTML(order)` (te same teksty i klasy co makra Jinja
  z Task 1), `renderStolSekcje(stol)` (sekcje `#monitor-stol` i `#monitor-odlozone` na początku `.monitor-content` —
  `.orders-grid` nie istnieje przy pustej liście, `monitor_station.html:72-78`; ukryte, gdy puste; `stol` `undefined`
  (monitor zbiorczy, AJAX bez pola) → nic nie robi), w `incrementalUpdateOrders` krok „3a: ułóż karty w kolejności
  z serwera” (`grid.appendChild(element)` dla każdej karty w kolejności `orders` — przenosi istniejące węzły bez
  przebudowy, przewijanie zostaje), w `updateOrderCard` aktualizacja gwiazdek, plakietki i klasy `na-stole`.
  **Klucz karty = `order_id`** (Doprecyzowania 9): `initializeOrdersCache` czyta `card.dataset.orderId`, `newOrdersMap`
  i `currentOrders` po `String(order.order_id)`, `generateOrderCardHTML` ustawia `data-order-id` (i dalej `data-order`).
- Produces (szablony): sekcje `TERAZ` / `Odłożone` (monitor stanowiska, Jinja = to samo co JS), gwiazdki i plakietka na
  kartach obu monitorów, w nagłówku stanowiska „Dalej w kolejce: N” (tryb `stol`).

- [x] **Step 1: Testy, które padną** (na źródle): `test_js_monitora_przestawia_karty_wg_kolejnosci_serwera`
  (w `incrementalUpdateOrders` po pętli aktualizacji jest pętla `orders.forEach` z `grid.appendChild(` na elementach
  z cache), `test_js_monitora_escapuje_teksty_z_bazy` (`function escapeHtml(`; w `generateOrderCardHTML`
  i `renderStolSekcje` każde `${order.` / `${kafel.` dla pól tekstowych idzie przez `escapeHtml(`; lista pól:
  `order_number`, `client_order_number`, `plakietka`, `powod_etykieta`, `notatka`, `pracownik`, `short_id`),
  `test_js_monitora_renderuje_stol_i_odlozone` (`renderStolSekcje(data.stol)` w `refreshMonitorData`),
  `test_js_monitora_klucz_karty_to_order_id` (`initializeOrdersCache` czyta `dataset.orderId`; w
  `incrementalUpdateOrders` brak `newOrdersMap.set(order.order_number`; `generateOrderCardHTML` ma `data-order-id=`;
  oba szablony mają `data-order-id="{{ order.order_id }}"`),
  `test_szablony_monitorow_maja_gwiazdki_i_sekcje` (`monitor_station.html`: `prio.gwiazdki`, `monitor-stol`,
  `monitor-odlozone`; `monitor.html`: `prio.gwiazdki`), `test_style_monitora_maja_klasy_prio` (oba CSS: `.prio-gwiazdki`,
  `.prio-plakietka`, `.na-stole`).
- [x] **Step 2: Testy padają.** **Step 3: Szablony i CSS.** **Step 4: JS** wg „Produces” (bez frameworków, `var`/`const`
  jak w pliku; żadnych zmian w auto-przewijaniu poza wywołaniem `calculateGridDimensions()` po przestawieniu).
- [x] **Step 5: Testy przechodzą** (pliki monitorów). **Podgląd w przeglądarce** (karta 8.5): `/production/stations/monitors/gluing`
  i `/production/stations/monitor` na podglądzie wskazanym przez centralę (IP podglądu na liście dozwolonych lokalnie;
  karta 8.5 podaje `/production/monitors/<kod>` — błędnie, blueprint stanowisk ma prefiks `/stations`).
  Scenariusz: (a) tryb `stary` — karty po randze, gwiazdki, plakietka trasy; (b) przez `PUT /ustawienia` tryb Sklejania
  `stol`, jedno `GET /api/mobile/stations/gluing/desk` z tokenem urządzenia podglądu (to tablet dopełnia stół, nie
  monitor), jedno `postpone` → po ≤ 30 s monitor pokazuje „TERAZ” i „Odłożone” bez przeładowania; (c) zmiana gwiazdek
  zamówienia w panelu (K2 `PUT /zamowienia/gwiazdki`) → po odświeżeniu karta przesuwa się na nowe miejsce, przewijanie
  nie skacze na górę. Zrzuty (a), (b), (c) do raportu; przywróć tryb `stary`.
- [x] **Step 6: Commit** `feat(priorytety): monitory hali - stol TERAZ, odlozone i plakietki na ekranie`

---

### Task 7a (karta): Monitory hali — źródło kafla i pracownik „Adam K.”

**Files:**
- Modify: `modules/production/priorytety/services/widok.py` (`_stol_stanowiska`: `pracownik_krotko`),
  `routers/stations/__init__.py` (`_stol_monitora`), `monitor_station.html`, `station-monitor.js`, CSS monitorów,
  `tests/test_priorytety_monitory.py`

**Ugruntowanie:** spec 7.2 (monitory: „pracownik odłożenia jako „Adam K.” (jak tablet)”, stół ze źródłem kafla jak
zakładka), 6.1 (`pracownik`: imię + inicjał nazwiska, pełne tylko w panelu), decyzja Konrada 5.10 (karta: notatka
widoczna na monitorze).

**Interfaces (Produces):**
- `widok.stoly_panelu()` — odłożony kafel dostaje `pracownik_krotko` („Adam K.”; samo imię, gdy brak nazwiska; None,
  gdy brak pracownika). `pracownik` (pełne) bez zmian — zakładka panelu.
- `_stol_monitora(kod)` oddaje odłożonym `pracownik` = `pracownik_krotko` (telewizor nie dostaje pełnego nazwiska),
  kafle stołu z `zrodlo`; szablon i JS rysują plakietkę źródła (te same teksty i klasy co zakładka: `zrodlo-biuro`
  „wysłane przez biuro”, `zrodlo-start` „rozpoczęte przed startem”, `zrodlo-dorobka` „doróbka”).
- [x] **Step 1: Testy, które padną:** `test_stoly_panelu_pracownik_krotko`, `test_monitor_odlozone_pracownik_adam_k`
  (HTML i AJAX: „Adam K.”, brak „Kowalski”; notatka widoczna), `test_monitor_zrodlo_kafla_plakietki` (HTML i AJAX
  `zrodlo`), `test_js_monitora_plakietka_zrodla` (na źródle JS: `zrodlo-biuro`, `zrodlo-start`, `zrodlo-dorobka`,
  teksty jak w zakładce).
- [x] **Step 2: Testy padają.** **Step 3: Implementacja.** **Step 4: Testy przechodzą** (pliki monitorów i czytelników).
  **Step 5: Commit** `feat(priorytety): monitory - zrodlo kafla i pracownik jako imie z inicjalem`

---

### Task 8: Pełny pakiet, Python 3.9, raport kroku

**Files:**
- Create: `docs/superpowers/plans/raporty/2026-10-05-priorytety-krok-K4b-raport.md`

- [x] **Step 1: Pełny pakiet:** `docker compose exec app pytest tests/ -q -p no:cacheprovider` → 0 failed; `passed` =
  punkt wyjścia + nowe (liczby do raportu). `blog_seo` nie dotyczy.
- [x] **Step 2: Składnia 3.9** dla zmienionych `.py` (`git diff --name-only <hash startu>..HEAD -- '*.py'`):
  `docker compose exec app python -c "import ast,sys; [ast.parse(open(p,encoding='utf-8').read(), p, feature_version=(3,9)) for p in sys.argv[1:]]; print('OK')" <pliki>`
  oraz grep `' | None'` / `\w+ \| \w+` w adnotacjach plików bez `from __future__ import annotations` → pusto.
- [x] **Step 3: Grep kontrolny** (wyniki do raportu):
  `grep -rn "priority_rank <=\|priority_rank<=\|≥150\|>=150" modules/production/routers/api/stations_api.py modules/production/routers/api/dashboard_api.py modules/production/templates/components/stations-tab-content.html modules/production/routers/stations`
  → pusto; `grep -rn "PRIORITY_RECALC_INTERVAL_HOURS\|PRIORITY_ALGORITHM_VERSION\|_PRIORITY_SORT" modules app.py`
  → pusto; `grep -rn "DEADLINE_DEFAULT_DAYS\|DEADLINE_FINISHED_DAYS" modules/production/routers/api/config_api.py`
  → pusto; `grep -rn "db.session.commit\|dopelnij\|with_for_update" modules/production/routers/api/stations_api.py modules/production/routers/stations modules/production/priorytety/services/widok.py`
  → pusto (poza istniejącymi przed K4b — wypisz je).
- [x] **Step 4: Raport** z sekcjami karty: **Zrobione** (po Taskach, z hashami), **Testy** (polecenia i wyniki; czasy
  odpowiedzi zakładki i monitora z podglądu), **Odstępstwa od planu** (nazwy K2/K3 inne niż w planie, decyzja A/B
  zakładki), **Rozstrzygnięcia podjęte w trakcie** (numerowane; koszt, jeśli błędne — co najmniej: grupowanie monitorów
  po id, kolumny zamiast `policz()` na monitorach, przeniesienie terminów do `PUT /ustawienia`), **Pytania do Konrada**,
  **Stan gałęzi** (hash, czy wypchnięte), **Co następny krok musi wiedzieć**, co najmniej:
  - **K5:** Doprecyzowania 1–15 do specu (7.2, 4.3, 8.6, 8.8); CLAUDE.md — zakładka i monitory to czytelnicy bez blokad,
    jedyna droga zapisu ustawień priorytetów i terminów; `reset-configs` (`config_api.py:608`, `@login_required`,
    bez UI) nadal może zresetować `DEADLINE_*` i `DEADLINE_DAY_TYPE` do domyślnych mimo „jednej drogi” — do decyzji;
    pozostałe progi rangi poza zakresem: `admin_routers.py:138-144`, `modules/production/__init__.py:132-163`;
  - **K6:** monitory nie są częścią kontraktu appki; tablet dalej jedynym, kto dopełnia stół;
  - **K7:** zakładka Stanowiska i monitory pokazują stół dopiero po przełączeniu stanowiska na `stol` (Lakiernia
    nigdy — lista po wykończeniu, Doprecyzowania 15);
    `min_app_version_code` ustawia się w karcie „Stół stanowisk”; w oknie wdrożenia (przed migracją) monitory przeżyją
    brak tabel (`blad: true`), ale sprawdzić je zaraz po restarcie;
  - **K8:** wiersze martwych kluczy w `prod_config` do usunięcia migracją; `ProductionPriorityConfig` nie ma już
    czytelnika w `config_api.py` (import w `routers/api/__init__.py:13-15` do usunięcia razem z modelem), ale **ma**
    w `routers/main_routers.py:228-254` (stary panel `panel/config.html`) — DROP bez usunięcia tego odczytu położy ten
    widok; `avg_priority` w `/dashboard-stats` w nowej skali bez konsumenta — usunąć albo opisać.
- [x] **Step 5: Commit raportu i push** wg karty: `git add -f docs/superpowers/plans/raporty/2026-10-05-priorytety-krok-K4b-raport.md`,
  `docs(priorytety): raport kroku K4b czytelnicy rangi`.

---

## Kryteria zakończenia (DoD)

1. Wszystkie testy z Review Focus istnieją pod podanymi nazwami i przechodzą; `tests/test_priorytety_czytelnicy.py`,
   `tests/test_priorytety_monitory.py` zielone. Pełny pakiet: 0 failed, liczby w raporcie, różnica wobec Step 0 wyjaśniona.
2. Istniejące testy zakładki i monitorów (`test_stanowiska_tab_krawedzie.py`, `test_stanowiska_tab_adresy_monitorow.py`,
   `test_monitory_krawedzie.py`) zielone bez zmiany asercji (dozwolone: nowe tabele w `TABELE`); `test_druk_panel_ui.py`
   zielony z nowym znacznikiem i wersjami.
3. Grep z Task 8, Step 3 bez trafień: brak progów rangi w czytelnikach, brak martwych kluczy w `modules/`, brak kluczy
   `DEADLINE_*` w `config_api.py`, brak commitów, blokad i `dopelnij` w czytelnikach.
4. `POST /update-configs` odrzuca każdy klucz priorytetów, terminów i martwy, a `POST /update-config` klucze
   `priorytety_*` i `DEADLINE_*` (testy); `PUT /ustawienia` przyjmuje `deadline_default_days` i `deadline_finished_days`
   z walidacją 1–90.
5. `GET /config-tab-content` działa bez tabeli `prod_priority_config`.
6. Zrzuty do raportu: zakładka Stanowiska (albo jej HTML przy decyzji B), karty „Terminy” i „Stół stanowisk”, monitor
   stanowiska w trybach `stary` i `stol`, monitor zbiorczy. Czasy odpowiedzi zakładki i `/ajax/monitors/gluing` z podglądu.
7. Składnia 3.9 OK dla zmienionych `.py`. Brak migracji w kroku.
8. Raport zacommitowany z sekcją „Co następny krok musi wiedzieć” (K5, K6, K7, K8). `main` nietknięty; commity tylko na
   `claude/priorytety-produkcji`: 8, po jednym na Task.

## Poza zakresem

- Lista produkcyjna, modal priorytetu, modal drabiny, gwiazdki w Logistyce, `set-priority`, `products-dragdrop.js` (K4a).
- Algorytm kolejki, stół, Odłóż, API mobilne, sygnały (K1/K3); końcówki panelu priorytetów poza rozszerzeniem
  `ustawienia` o dwa pola terminów (K2).
- `pending_priority` w `/dashboard-stats-data` (`dashboard_api.py:1496-1504`: termin ≤ 3 dni na trzech statusach — nie
  ranga), `avg_priority` w `/dashboard-stats`, `admin_routers.py:138-144`, `modules/production/__init__.py:132-163`,
  `reset-configs` bez admina, odczyt `ProductionPriorityConfig` w `routers/main_routers.py:228-254` (dla K8) — do
  raportu, bez zmian.
- Niespójny wygląd nowych kart na monitorze zbiorczym (`generateOrderCardHTML` w stylu monitora stanowiska) — istniejące,
  bez zmian poza nowymi polami.
- Wiersze martwych kluczy w `prod_config`, `ProductionPriorityConfig`, `priority_service.py` (K8). Wyścigi MySQL (K5;
  krok nie ma nowych zapisów).

## Ryzyka i co robić przy blokadzie

| Ryzyko | Skutek | Co robić |
|---|---|---|
| `widok.stoly_panelu`/`kolejka_stanowiska`/`drabina_panelu` z K2/K3 mają inne nazwy albo kształt (np. `kafel["szczebel"]` jako napis) | szablony i testy wg planu nie pasują | Task 1 Step 0: dopasuj się do kodu, „Odstępstwa”. Brak funkcji → **STOP** przed Taskiem, meldunek do centrali (karta naprawcza K2/K3). Bez własnej kopii algorytmu |
| Zakładka liczy `kolejka_stanowiska` 7× i `stoly_panelu` (który sam liczy `kolejka_dalej`) — `policz`/kandydaci kilkanaście razy na żądanie | odpowiedź > 1 s przy ~250 zamówieniach | zmierz na podglądzie (Task 2 Step 7); > 1 s → meldunek z pomiarem, opcja do decyzji: jedno wspólne wyliczenie kandydatów w `widok` (zmiana K2/K3, poza krokiem) |
| `ustawienia.*` czytane przez pamięć podręczną procesu (60 min) — wynik K2 Task 5 | nowe K/tryb/terminy widoczne w innych workerach gunicorna z opóźnieniem; monitor pokazuje stary tryb | nie naprawiaj w K4b; stan z raportu K2 przepisz do raportu K4b; jeśli K2 zostawił `xfail` — meldunek do centrali przed Task 4 |
| Monitor zbiorczy po zmianie grupowania z numeru na id pokazuje więcej kart (zamówienia z powtórzonym numerem z różnych lat) | „nowe” karty na ekranie hali | zamierzone (Doprecyzowania 9); w raporcie liczba takich par na podglądzie z kopią produkcji, jeśli jest |
| Konflikt w `dashboard.html` z K4a (wersje skryptów, zmiana nazwy zakładki, usunięcie `products-dragdrop.js`) | utrata zmian drugiej sesji | `git pull --rebase` przed każdym commitem, ręczne scalenie; `test_druk_panel_ui.py` i testy K4a zielone po scaleniu |
| JS monitora bez runnera — błąd składni wychodzi dopiero na telewizorze | czarny ekran hali | testy strukturalne + obowiązkowe sprawdzenie w przeglądarce z konsolą (Task 7 Step 5); `node --check` niedostępny w obrazie — jeśli jest lokalnie poza Dockerem, uruchom i wpisz wynik |
| Telewizor w oknie wdrożenia (kod nowy, migracja jeszcze nie wykonana) | 500 na monitorze | `_stol_monitora` i `priorytet_zamowien` w `try/except` (test `test_monitor_przezywa_blad_priorytetow`); sort po kolumnie `priority_rank` zamówienia wymaga migracji K1 — deploy i tak migruje przed restartem (CLAUDE.md, `deploy.sh` krok 5) |
| Padający test spoza zakresu, spór spec ↔ kod | — | **STOP**: opis w raporcie, meldunek do centrali, bez obejść i bez wyłączania testów (podręcznik, sekcja 6) |

## Pytania do Konrada

**Przed kartą (zbiera centrala):**
1. **Zakładka „Stanowiska” nie jest dziś podpięta w panelu** (`dashboard.html:36-107` nie ma przycisku, loader jej nie
   zna, CSS nie jest dołączany; endpoint i szablon żyją tylko w testach). Spec 7.2 zakłada, że biuro ją widzi.
   (A) K4b przerabia ją i **podpina** w panelu jako zakładkę „Stanowiska” — **rekomendacja**: inaczej podgląd stołów
   i odłożeń wszystkich stanowisk jest tylko na monitorach hali; (B) K4b przerabia endpoint i szablon, bez podpinania
   (Task 2 Step 6 pominięty, decyzja do K7); (C) zakładka do usunięcia w K8, K4b jej nie rusza (Task 2 odpada, testy
   Review Focus 2 skreślone). Bez odpowiedzi sesja robi wariant B.

**Do potwierdzenia przy bramce (plan przyjmuje wartości domyślne):**
2. Zakres dni terminów 1–90 w `PUT /ustawienia` (dziś pole UI ma `max="90"`, serwis waliduje 1–365).
3. Na monitorze hali odłożenie pokazuje pracownika („Adam K.”) i notatkę, jak tablet — czy na telewizorze notatka ma być
   widoczna dla całej hali.
4. Próg alertu „Dużo pilnych zamówień” zostaje `> 10` (zamówień, dotąd pozycji).
