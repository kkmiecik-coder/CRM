# Logistyka etap 4, krok 4.3 — nowe statusy pozycji i stanowisko Weryfikacja — plan implementacji

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** pozycje zamówienia dostają statusy po spakowaniu (`zweryfikowane`, `zaladowane`, `dostarczone`), cały CRM traktuje je jak „spakowane lub dalej”, a pracownik biura na telefonie (stanowisko `verification`) sprawdza paczki zamówienia, zgłasza problem, cofa weryfikację albo cofa zamówienie do pakowania — z widokiem w panelu Logistyki i licznikami na dashboardzie produkcji.

**Architecture:** Jedna stała `sposoby.STATUSY_PO_SPAKOWANIU` zastępuje pytania `== 'spakowane'` w znaczeniu „produkcja zakończona” (mapa z przeglądu całego repo w Task 3–4). Nowy serwis `logistics/services/weryfikacja.py` trzyma regułę unieważniania etapów (paczki, weryfikacja, załadunek) po powrocie pozycji do produkcji, definicję listy „Do weryfikacji” (SQL wspólny dla telefonu, panelu i dashboardu) oraz akcje Weryfikacji. API telefonu to osobny blueprint `/api/mobile/verification` (`logistics/routers/weryfikacja_api.py`) na dekoratorach API mobilnego (`require_device_token`, `with_idempotency`). Kolejność blokad każdego zapisu Weryfikacji: pracownicy → `paczki.zablokuj_deklaracje()` → wiersz zamówienia po PK → paczki → pozycje.

**Tech Stack:** Flask 2 + SQLAlchemy < 2.0, MySQL 8.4 (produkcja) / SQLite (testy), pytest, vanilla JS, Jinja.

**Spec:** `docs/superpowers/specs/2026-09-30-logistyka-etap-4-weryfikacja-dostawa-design.md` — sekcje 2, 3, 4 (4.1, 4.2, 4.4–4.6), 5.3, 5.5, 7.2 (blokada po weryfikacji), 8 (cała), 11, 12 pkt 1, 3–5, 7–8, 13, 14 pkt 3, 15. Wzór formatu i dorobek kroków 4.1–4.2: `docs/superpowers/plans/2026-09-30-logistyka-etap-4-krok-4-1-druk.md`, `docs/superpowers/plans/2026-09-30-logistyka-etap-4-krok-4-2-paczki.md`.

## Global Constraints

- Kod zgodny z **Pythonem 3.9** (produkcja): bez `X | Y` w adnotacjach, bez `match`; `typing.Optional/List`.
- Komentarze i docstringi **po polsku**; teksty w UI i komunikaty API po polsku; w UI „Base.” zamiast BaseLinker.
- Błędy API: `{"error": <kod>, "message": <tekst dla człowieka>}` (spec 13). Błędy pracownika z `worker_service.WorkerError` zostają w dotychczasowym kształcie `{"error", "detail"}` (kontrakt z appką).
- Funkcje serwisów **nie commitują**; w API mobilnym commit robi `@with_idempotency(retryable_statuses=BLEDY_DO_PONOWIENIA)`. Sygnały po commicie (agent druku, dopychacz Base.) **wyłącznie po commicie**.
- `STATUSY_PO_SPAKOWANIU = ('spakowane', 'zweryfikowane', 'zaladowane', 'dostarczone')` i `STATUSY_LOGISTYCZNE = ('zweryfikowane', 'zaladowane', 'dostarczone')` żyją **tylko** w `modules/production/logistics/sposoby.py` (moduł bez importów aplikacji). W JS i szablonach — lista literałów z komentarzem „jak sposoby.STATUSY_PO_SPAKOWANIU”.
- Nowe statusy nadaje wyłącznie logistyka (Weryfikacja, „Wydane klientowi”, w 4.4 Dostawa) — **hurtowa zmiana statusu ich nie oferuje** (serwer i listy wyboru).
- Nowe statusy zmieniają się **dla wszystkich niezanulowanych pozycji zamówienia naraz**.
- Kolejność blokad zapisów Weryfikacji (każdy endpoint zapisu `/api/mobile/verification/*`): `_resolve_workers`/`touch_sessions` → `paczki.zablokuj_deklaracje()` → zamówienie `FOR UPDATE` po PK (`_zamowienie_po_numerze(numer, do_zapisu=True)` albo po `order_id` paczki) → paczki `FOR UPDATE` → zapisy pozycji. Stan, na którym zapis decyduje, czytany **po** blokadzie odczytem bieżącym (`with_for_update().populate_existing()`), bo MySQL pracuje na REPEATABLE READ.
- Reguła unieważniania (`weryfikacja.uniewaznij_etapy`) nie bierze żadnej blokady globalnej; zapisuje najpierw wiersz zamówienia (`flush`), potem paczki.
- `serialize_order` (kolejki tabletów) nadal **nie czyta `prod_packages`**.
- `KSZTALT_ODPOWIEDZI_KOLEJKI = 5` (nowe pole `transport.repack_reason`).
- Migracja: `migrations/2026-09-30-logistyka-weryfikacja.sql`, idempotentna, dopisuje wartości **na końcu** ENUM-ów, `ALTER` dodające osłonięte `information_schema` + `PREPARE/EXECUTE`, bez zmiany separatora poleceń (słowo nie może paść nawet w komentarzu — test szuka go w całym pliku). ENUM akcji logu MUSI zawierać wszystkie dotychczasowe wartości, także `'paczki'`.
- `tools/print_agent` — **bez zmian** (każda zmiana = nowa paczka dla hali).
- Testy WYŁĄCZNIE z katalogu worktree zadania: `docker compose -p <projekt> run --rm --no-deps app pytest <ścieżki> -q -p no:cacheprovider`; **nigdy** `docker compose exec`; nie twórz `config/core.json` w worktree.
- Podgląd 5004 (kontener `logistyka4-podglad`, baza `logistyka4_podglad`, agent testowy) — **nie ruszać**, dopóki centrala nie potwierdzi końca testu wydruku 4.2 (1.10 rano). Odczyt (zrzut) bazy jest dozwolony.
- Commity: Conventional Commits po polsku **bez polskich znaków w temacie**, stopka `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Bez pushu (push robi Konrad), nigdy do `main`. Spec i plan commitujemy `git add -f`.
- Repo publiczne: żadnych sekretów, adresów IP drukarek ani uwag bezpieczeństwa w commitowanych plikach.

## Review Focus

1. **Stara akcja z kolejki offline po weryfikacji** (ponowione „ZAKOŃCZ” pakowania, powtórzony skan z tym samym `X-Operation-Id`) nie może cofnąć zamówienia zweryfikowanego ani zweryfikować drugi raz — `test_ponowione_zakoncz_pakowania_nie_cofa_statusu_logistyki` (Task 1), `test_powtorka_operacji_nie_weryfikuje_drugi_raz`, `test_ponowny_skan_bez_zmian` (Task 6).
2. **Problem zgłoszony na zweryfikowanym zamówieniu** musi cofnąć weryfikację (inaczej obszedłby bramkę załadunku z kroku 4.4), a weryfikacja przy otwartym problemie — odmówić — `test_problem_na_zweryfikowanym_cofa_weryfikacje` (Task 7), `test_odmowy_409[problem_open]` (Task 6).
3. **Zamówienie wraca do produkcji po weryfikacji** (doróbka, nowa pozycja z Base., hurtowa zmiana statusu, przepakowanie, cofnięcie do pakowania, ścieżka bez wołania reguły) — paczki i weryfikacja się kasują, dostarczone zostaje dostarczone, cron łata resztę — `test_nowa_pozycja_uniewaznia_paczki_weryfikacje_i_wydruki`, `test_dostarczone_zostaja_zaladowane_wracaja` (Task 1), `test_dorobka_uniewaznia_etapy`, `test_nowa_pozycja_z_base_uniewaznia_etapy`, `test_przepakowanie_zweryfikowanego_uniewaznia_paczki_i_weryfikacje`, `test_cron_nie_otwiera_zweryfikowanego_i_czysci_etapy_po_nowej_pozycji` (Task 2), `test_reczna_zmiana_statusu_wola_regule_uniewaznienia` (Task 3), `test_cofniecie_do_pakowania` (Task 7).
4. **Historia i zamówienia kurierskie na liście** — 1512 historycznych spakowanych zamówień nie może zalać telefonu, kurierskie (zamknięte przy spakowaniu) muszą na nim być przez 7 dni od wdrożenia, a zweryfikowane zostać w telefonie (lokalny skaner) — `test_zakres_listy`, `test_bez_daty_wdrozenia_samo_okno_dni` (Task 5), `test_filtry_weryfikacji` (Task 8), `test_liczniki_weryfikacji` (Task 9).
5. **Nowe statusy nie mogą wyglądać jak „niespakowane” ani otwierać zamkniętych** (archiwum, wyszukiwarka tabletu, zamknięcie kuriera, „Odhacz” trasy, deklaracja po weryfikacji z mylącym `order_not_packed`) — `test_zamkniecie_po_nowych_statusach`, `test_deklaracja_po_weryfikacji_409` (Task 2), `test_brak_porownan_z_dokladnym_spakowane`, `test_zamowienia_po_weryfikacji_i_wydaniu_zostaja_w_archiwum`, `test_zamowienie_zweryfikowane_i_dostarczone_idzie_do_archiwum` (Task 3), `test_etap_po_spakowaniu`, `test_front_zna_nowe_etapy_i_filtry` (Task 8).

Poza testami SQLite (Task 10, MySQL): kolejność blokad Weryfikacja ↔ deklaracja ↔ „ZAKOŃCZ” ↔ ACK agenta druku ↔ hurtowa zmiana statusu na dwóch sesjach.

## Decyzje Konrada z 30.09 (przed planem)

1. **Jeden plan 4.3** (bez podziału na 4.3a i 4.3b), mimo rozmiaru.
2. **Zamknięcie transportu własnego po „dostarczone” (spec 4.6) — w kroku 4.4**, razem z Dostawą. W 4.3 zmienia się tylko reguła kuriera (zamknięte, gdy wszystkie niezanulowane pozycje są w `STATUSY_PO_SPAKOWANIU` — inaczej zweryfikowane zamówienia kurierskie by się otwierały). Transport w 4.3 dalej zamyka „przystanek na trasie wykonanej”, odhaczenie trasy nie zmienia statusów pozycji.
3. **Zakres listy „Do weryfikacji”** (telefon, filtr panelu, licznik dashboardu): zamówienia, których wszystkie niezanulowane pozycje są `spakowane`, i które są **otwarte w Logistyce** albo **spakowane w ostatnich 7 dniach, nie wcześniej niż od wdrożenia kroku 4.3** (data w `prod_config`, wiersz `logistyka_weryfikacja_od` zakładany migracją), plus **zawsze** zamówienia z otwartym problemem. Powód: na kopii produkcji z 28.09 jest 1512 zamówień w całości spakowanych (112 z ostatnich 7 dni) — bez zawężenia wszystkie trafiłyby na listę.
4. **Doróbka albo nowa pozycja w zamówieniu dostarczonym**: pozycje `dostarczone` zostają dostarczone (towar u klienta jest u klienta). Paczki i weryfikacja kasują się, pozycje `zweryfikowane` i `zaladowane` wracają do `spakowane`.
5. (Z centrali, zrobione przed planem osobnym commitem `f5e13293`) ikona „etykiety paczek sprzed zmiany” pokazuje się także na zamówieniach zamkniętych w Logistyce, z porównaniem do trasy zamówienia także wykonanej.

## Odstępstwa i doprecyzowania względem specu (do dopisania w specu w Task 10)

- 4.6 / 8.5: transport własny zamyka się jak dotąd (decyzja 2); reguła „wszystkie dostarczone” przechodzi do 4.4.
- 8.2: lista telefonu zawiera zamówienia `spakowane` **i `zweryfikowane`** (w tym samym zakresie) oraz zamówienia z problemem. Powód: skaner rozpoznaje `P-<id>` lokalnie z listy, a „ponowny skan = OK bez zmian” i „Cofnij weryfikację” wymagają, żeby zamówienie zweryfikowane nadal było w telefonie. Licznik „Do weryfikacji: N” i filtr panelu liczą tylko `spakowane`.
- 8.2: zakres listy wg decyzji 3; kolejność: zamówienia z problemem nie mają osobnego miejsca — kolejność jak w specu (trasa aktywna z najbliższą datą początku, potem `packed_at` rosnąco, potem numer).
- 8.1: nagłówek `X-Worker-Ids` wymagany na **endpointach zapisu** Weryfikacji; odczyty (lista, szczegóły) go nie wymagają (nie ma czego przypisać).
- 8.3: kody błędów doprecyzowane (kontrakt niżej): `order_not_packed` 409 (pozycja przed spakowaniem), `order_status` 409 (zamówienie już załadowane albo dostarczone), `no_packages` 409 (weryfikacja bez deklaracji — spec 4.4 „Weryfikacja wymaga zadeklarowanych paczek”), `order_not_verified` 409 (cofnięcie weryfikacji zamówienia niezweryfikowanego), `invalid_method` 422, `invalid_problem` 422, `station_not_allowed` 403, `worker_required` 400.
- 8.3: `problem` na zamówieniu, które ma już problem, nadpisuje powód i notatkę (200); `problem/resolve` bez problemu = 200 bez zmian (kolejka offline nie może utknąć na 409).
- 8.4: `repack_reason` ustawia też przepakowanie na kuriera (`"Przepakuj na kuriera"`); `transport.repack_reason` = `order.repack_reason` przy `repack_required`, a przy starym `repack_required` bez tekstu — `"Przepakuj na kuriera"`. Ponowne spakowanie czyści oba.
- 4.1 / 11: „Spakowane — czeka na weryfikację” to napis etapu w panelu Logistyki i na telefonie; `status_display_name` pozycji zostaje „Spakowane” (raporty, historia produktu).
- 5.3 / 5.2: indeks `ix_prod_packages_order_voided (order_id, voided_at)` zastępuje `ix_prod_packages_voided_at` (zapytania o paczki zawsze filtrują po zamówieniu; osobny indeks po `voided_at` nie ma zapytań).
- „Wydane klientowi” (spec 4.2): migracja przestawia na `dostarczone` pozycje `spakowane` zamówień już wydanych (spójność z nową regułą; SQL omija audyt `prod_product_events` — zapisane w komentarzu migracji).
- 11: „W trasie” (etap zamówienia na trasie `w_trasie`) — w kroku 4.4, razem ze statusami tras.

## Poza zakresem kroku 4.3 (celowo)

- Zamknięcie transportu po `dostarczone`, odhaczenie trasy → `dostarczone`, statusy Base. Załadowane/Wysłane/Dostarczone, migracja historycznych tras wykonanych — krok 4.4.
- Archiwum (`_archived_order_condition` → `logistics_closed_at`) — krok 4.5. Tu archiwum tylko **zachowuje** dzisiejszy sens („spakowane lub dalej albo anulowane”).
- Rozwiązywanie problemu i cofanie weryfikacji z panelu webowego — spec daje w panelu tylko ikonę i filtry.
- Drobiazgi agenta druku z 4.2 — czekają na najbliższe wydanie agenta.

## Kontrakt API Weryfikacji (dla appki i przeglądu)

Prefiks `/api/mobile/verification`. Wszystkie: `Authorization: Bearer <JWT urządzenia>`; urządzenie zarejestrowane na stanowisku `verification` (inne → 403 `station_not_allowed`). Zapisy: `X-Operation-Id` (400/403/404/409 **niezapamiętane** — `BLEDY_DO_PONOWIENIA`; 422 zapamiętane), `X-Worker-Ids` wymagany (brak → 400 `worker_required`; nieznany/nieaktywny pracownik → kody `WorkerError` jak w `complete`).

| Endpoint | Body | 200 | Błędy |
|---|---|---|---|
| `GET /orders` | — | `{"orders": [Zamówienie…], "count": N}`; nagłówek `ETag`, `If-None-Match` → 304 | 403 |
| `GET /orders/<nr>` | — | `{"order": Zamówienie + "items": [Pozycja…]}` (`no-store`) | 404 `order_not_found`, 403 |
| `POST /packages/<id>/verify` | `{"method": "skan"\|"reczne"}` (brak = `skan`) | `{"package": Paczka, "order": Zamówienie, "order_verified": bool, "changed": bool, "message"}` | 404 `package_not_found`; 409 `package_void`, `problem_open`, `order_not_packed`, `order_status`; 422 `invalid_method` |
| `POST /orders/<nr>/verify-all` | — | `{"order", "order_verified": true, "changed", "message"}` | 404 `order_not_found`; 409 `no_packages`, `problem_open`, `order_not_packed`, `order_status` |
| `POST /orders/<nr>/unverify` | — | `{"order", "changed": true, "message"}` | 404; 409 `order_not_verified`, `order_status` |
| `POST /orders/<nr>/problem` | `{"reason", "note"}` | `{"order", "changed": true, "message"}` | 404; 409 `order_not_packed`, `order_status`; 422 `invalid_problem` |
| `POST /orders/<nr>/problem/resolve` | — | `{"order", "changed": bool, "message"}` | 404 |
| `POST /orders/<nr>/revert-to-packing` | `{"reason"?, "note"?}` | `{"order", "changed": true, "message"}` | 404; 409 `order_not_packed`, `order_status`; 422 `invalid_problem` (brak powodu i brak otwartego problemu) |

- Powody problemu: `brak_elementu` („Brak elementu”), `uszkodzenie` („Uszkodzenie”), `etykieta` („Etykieta”), `opakowanie` („Opakowanie”), `inne` („Inne”). Notatka opcjonalna; dłuższa niż 255 znaków jest **ucinana** (422 z kolejki offline to utracona akcja).
- **Zamówienie:** `{"order_id", "internal_order_number", "baselinker_order_id", "client_name", "delivery_city", "stage", "stage_label", "packed_at", "verified_at", "transport": {"mode", "trip_name", "trip_date", "vehicle_name", "repack_required", "repack_reason"}, "packages": [Paczka…], "packages_total", "packages_verified", "no_packages", "problem": null | {"reason", "reason_label", "note", "at", "by_worker_id"}}`. `stage` = status najbardziej zaległej niezanulowanej pozycji (`spakowane`, `zweryfikowane`, …); `stage_label` = „Spakowane — czeka na weryfikację”, „Zweryfikowane”, „Załadowane”, „Dostarczone” albo nazwa stanowiska. `packed_at` = najpóźniejsze `packaging_completed_at` niezanulowanych pozycji. `no_packages` = zamówienie spakowane bez aktualnej deklaracji (plakietka „BEZ PACZEK”).
- **Paczka** (ten sam serializer co w 4.2, rozszerzony): `{"id", "code": "P-<id>", "seq", "kind", "pallet_type", "length_cm", "width_cm", "label_print_count", "label_printed_at", "verified", "verified_at", "verified_method"}` — nowe pola dochodzą też w odpowiedziach `PUT/GET /orders/<nr>/packages` i ponownego druku (zmiana addytywna).
- **Pozycja** (tylko szczegóły): `{"id", "short_id", "product_name", "quantity", "status", "status_label", "volume_m3"}`.
- `N_S` z etykiety produktu: `N` = numer wewnętrzny zamówienia — appka szuka zamówienia na liście lokalnie.
- Deklaracja i ponowny druk z telefonu: istniejące `PUT/GET /api/mobile/orders/<nr>/packages`, `POST /api/mobile/packages/<id>/print`, `POST /api/mobile/orders/<nr>/packages/print` (stanowisko `verification` już uprawnione). **Nowe w 4.3:** `PUT` na zamówieniu z pozycją w `STATUSY_LOGISTYCZNE` → 409 `order_verified` („najpierw Cofnij weryfikację”).
- Kolejka tabletów: `transport.repack_reason` (tekst banera albo `null`), ETag kształt 5.

## Środowisko i tory równoległe

- Główny worktree (Git Bash): `cd /c/Users/Grafik/Documents/woodpower-crm/.claude/worktrees/logistyka-etap-4`, gałąź `claude/logistyka-etap-4`, projekt dockera `logistyka4`.
- `PYTEST <ścieżki>` w krokach = `docker compose -p <projekt> run --rm --no-deps app pytest <ścieżki> -q -p no:cacheprovider` uruchomione z katalogu worktree zadania.
- Punkt wyjścia: `5148 passed, 3 skipped` (koniec kroku 4.2 `00c09009` + poprawka ikony paczek na zamkniętych `f5e13293`). Po każdym zadaniu pełny pakiet: 0 failed, passed = poprzednio + nowe (± testy świadomie zmienione, wymienione w raporcie). **Najwyżej 2 pełne pakiety naraz** (Docker VM 15,5 GB — wcześniej OOM, exit 137).
- Tor równoległy: `git worktree add .claude/worktrees/logistyka-etap-4-t<N> -b claude/logistyka-etap-4-t<N> <BASE>` z katalogu głównego repo, własny `-p logistyka4-t<N>`; scalanie cherry-pickiem do `claude/logistyka-etap-4`, gdy w głównym worktree nikt nie pracuje; po scaleniu pełny pakiet w głównym worktree, potem usunięcie gałęzi i worktree toru. Pliki torów są rozłączne (kolumna „Task” w mapie plików).

| Etap | Główny worktree | Tor równoległy |
|---|---|---|
| 1 | Task 1 (schemat, stałe, reguła) | — |
| 2 | Task 2 (cykl zamówienia w logistyce) | Task 3 (przegląd backendu produkcji) — `…-t3`, `-p logistyka4-t3`, baza = commit Task 1 |
| 3 | Task 5 (stanowisko i lista) | Task 4 (front produkcji) — `…-t4`, `-p logistyka4-t4`, baza = główna gałąź po scaleniu Task 3 |
| 4 | Task 6 (akcje weryfikacji) | Task 8 (panel Logistyki, skill `frontend-design:frontend-design`) — `…-t8`, `-p logistyka4-t8`, baza = główna gałąź po Task 5 i scaleniu Task 4 |
| 5 | Task 7 (problem, cofnięcie do pakowania, `repack_reason`) | (Task 8 trwa) |
| 6 | Task 9 (pasek dashboardu) — po scaleniu Task 8 | — |
| 7 | Task 10 (MySQL, podgląd, spec) | — |

## Mapa plików

| Plik | Task | Rola |
|---|---|---|
| `migrations/2026-09-30-logistyka-weryfikacja.sql` (nowy) | 1 | ENUM statusu (+3 na końcu), 7 kolumn `prod_orders`, ENUM akcji logu (+5), indeks paczek, wiersz `logistyka_weryfikacja_od`, wydane → `dostarczone` |
| `modules/production/models.py` | 1, 5 | ENUM + nazwy statusów, kolumny zamówienia, indeks paczek, strażnik `complete_task('packaging')` (1); `VALID_STATION_CODES` + `verification` (5) |
| `modules/production/logistics/models.py` | 1 | `AKCJE_LOGU` + 5 akcji |
| `modules/production/logistics/sposoby.py` | 1, 7 | `STATUSY_PO_SPAKOWANIU`, `STATUSY_LOGISTYCZNE`, `PRZEPAKUJ_NA_KURIERA` (1); `transport_payload` + `repack_reason` (7) |
| `modules/production/logistics/services/weryfikacja.py` (nowy) | 1, 5, 6, 7 | reguła `uniewaznij_etapy` (1); stałe, warunki SQL listy, serializacja (5); weryfikacja paczki i wszystkich, cofnięcie (6); problem, cofnięcie do pakowania (7) |
| `modules/production/logistics/services/paczki.py` | 1, 2, 5 | `uniewaznij(…, powod)` (1); blokada `order_verified` w `zadeklaruj` (2); stan weryfikacji w `serializuj_paczke` (5) |
| `scripts/create_split_tables.sql` | 1 | ENUM statusu w DDL bootstrapu |
| `modules/production/logistics/services/delivery.py` | 2 | „spakowane lub dalej”, zamknięcie kuriera, wydane → `dostarczone`, przepakowanie → reguła, `repack_reason`, siatka crona |
| `modules/production/services/rework_service.py`, `modules/production/services/sync_service.py` | 2 | wywołania reguły (doróbka, nowa pozycja z Base.) |
| `modules/production/routers/api/products_api.py` | 3 | archiwum, statystyki, hurt (wykluczenie + reguła), kolory eksportu, opcje filtra |
| `modules/production/routers/api/{dashboard_api,common_api,reports_api,sync_api}.py`, `routers/{main_routers,admin_routers,mobile_api}.py`, `routers/stations/monitors.py` | 3 | przegląd z mapy (Task 3) |
| `modules/production/services/{baselinker_status_sync,mobile_api_service,daily_report_service,dashboard_alerts,display_monitor_service,reports_service,order_timeline_service}.py`, `templates/components/reports/mix.html` | 3 | przegląd z mapy (Task 3) |
| `modules/dashboard/services/chart_service.py` | 1 | kolory nowych statusów (test kolorów iteruje po całym ENUM) |
| `modules/production/static/js/modules/{products-module,archive-module}.js` | 4 | etykiety, klasy, „spakowane lub dalej” |
| `modules/production/services/station_catalog.py`, `modules/production/services/mobile_api_service.py` (telemetria) | 5 | nazwa i telemetria stanowiska |
| `modules/production/logistics/routers/weryfikacja_api.py` (nowy), `app.py`, `tests/logistyka_fixtures.py` | 5, 6, 7 | blueprint `/api/mobile/verification` |
| `modules/production/logistics/services/bl_sync.py`, `modules/production/services/mobile_api_service.py` (`with_idempotency`), `modules/production/routers/mobile_api.py` (kształt 5) | 7 | dopychacz po commicie, `KSZTALT_ODPOWIEDZI_KOLEJKI = 5` |
| `modules/production/logistics/services/lista.py`, `logistics/routers/panel_api.py`, `logistics/static/js/{logistics,logistics-map,logistics-routes}.js`, `logistics/static/css/logistics.css`, `logistics/templates/logistics/tab_content.html` | 8 | kolumna Etap, paczki, problem, filtry |
| `modules/production/routers/api/dashboard_api.py` (liczniki), `templates/components/dashboard-tab-content.html`, `static/js/modules/dashboard-module.js`, `static/css/production-panel.css` | 9 | pasek „Do weryfikacji / Problemy” |
| `CLAUDE.md`, spec | 10 | kolejność blokad Weryfikacji, odstępstwa |

---

### Task 1: Schemat, stałe statusów i reguła unieważniania etapów

**Files:**
- Create: `migrations/2026-09-30-logistyka-weryfikacja.sql`
- Create: `modules/production/logistics/services/weryfikacja.py`
- Modify: `modules/production/models.py` (`ProductionOrder` ok. :186–210, `ProductionProduct.current_status` :359–365, `status_display_name` :448–467, `complete_task` :617–673, `ProductionPackage` :991–1008)
- Modify: `modules/production/logistics/models.py` (`AKCJE_LOGU`)
- Modify: `modules/production/logistics/sposoby.py`
- Modify: `modules/production/logistics/services/paczki.py` (`uniewaznij`)
- Modify: `scripts/create_split_tables.sql:89`
- Modify: `modules/dashboard/services/chart_service.py:247` (kolory nowych statusów — `tests/test_dashboard_statusy_produkcji.py` iteruje po całym ENUM, więc bez nich pełny pakiet padnie już w tym zadaniu)
- Modify: `tests/test_krawedzie_model.py:115-126`, `tests/test_migracja_krawedzie.py:156-171` i `:493-506`
- Test: `tests/test_weryfikacja_schemat.py`, `tests/test_weryfikacja_regula.py`

**Interfaces:**
- Produces: `sposoby.STATUSY_PO_SPAKOWANIU = ('spakowane', 'zweryfikowane', 'zaladowane', 'dostarczone')`, `sposoby.STATUSY_LOGISTYCZNE = ('zweryfikowane', 'zaladowane', 'dostarczone')`, `sposoby.PRZEPAKUJ_NA_KURIERA = u'Przepakuj na kuriera'`; `ProductionOrder.verified_at`, `.verified_by_worker_id`, `.problem_reason`, `.problem_note`, `.problem_at`, `.problem_by_worker_id`, `.repack_reason`; akcje logu `weryfikacja`, `weryfikacja_cofnieta`, `problem`, `problem_rozwiazany`, `cofniete_do_pakowania`; `paczki.uniewaznij(lista, teraz, powod=u'nowa deklaracja paczek') -> int`; `weryfikacja.uniewaznij_etapy(order, teraz, powod, user_id=None, worker_id=None, device_id=None) -> bool`; wiersz `prod_config.logistyka_weryfikacja_od` (z migracji; tekst `RRRR-MM-DD GG:MM:SS`).

- [ ] **Step 0: Punkt wyjścia**

Run: `PYTEST tests/` (projekt `logistyka4`)
Expected: `5148 passed, 3 skipped` (po poprawce ikony `f5e13293`).

- [ ] **Step 1: Testy schematu, które padną**

Create `tests/test_weryfikacja_schemat.py`:

```python
# -*- coding: utf-8 -*-
"""Schemat kroku 4.3 (logistyka etap 4, spec 4.1, 5.3 i 5.5): statusy po spakowaniu, kolumny
weryfikacji, problemu i banera przepakowania, akcje logu Weryfikacji, indeks paczek."""
import os
import re
from datetime import datetime

from migrations.migration_service import MigrationService
from modules.production.logistics import sposoby
from modules.production.logistics.models import AKCJE_LOGU
from modules.production.models import ProductionOrder, ProductionPackage, ProductionProduct
from tests.logistyka_fixtures import app, zamowienie  # noqa: F401

MIGRACJA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        'migrations', '2026-09-30-logistyka-weryfikacja.sql')
STARE_STATUSY = ['czeka_na_wyciecie', 'czeka_na_skladanie', 'czeka_na_sklejanie',
                 'czeka_na_formatowanie', 'czeka_na_krawedzie', 'czeka_na_lakiernie',
                 'czeka_na_logistyke', 'czeka_na_pakowanie', 'spakowane', 'anulowane',
                 'wstrzymane', 'w_realizacji']
STARE_AKCJE = ['sposob_dostawy', 'wydane', 'przepakowanie', 'trasa_dodane', 'trasa_usuniete',
               'trasa_status', 'adres', 'paczki']


def _polecenia():
    with open(MIGRACJA, encoding='utf-8') as f:
        sql = f.read()
    return sql, [' '.join(p.split()) for p in MigrationService.split_statements(sql)]


def _wartosci(polecenie):
    return re.findall(r"'([a-z_]+)'", polecenie.split('ENUM(', 1)[1].split(')', 1)[0])


def test_stale_statusow():
    assert sposoby.STATUSY_PO_SPAKOWANIU == ('spakowane', 'zweryfikowane', 'zaladowane', 'dostarczone')
    assert sposoby.STATUSY_LOGISTYCZNE == ('zweryfikowane', 'zaladowane', 'dostarczone')
    assert sposoby.PRZEPAKUJ_NA_KURIERA == u'Przepakuj na kuriera'


def test_nowe_statusy_na_koncu_enuma():
    """Dopisanie NA KOŃCU: MySQL 8 zmienia same metadane, a stare wartości zachowują porządek."""
    wartosci = list(ProductionProduct.current_status.type.enums)
    assert wartosci == STARE_STATUSY + ['zweryfikowane', 'zaladowane', 'dostarczone']


def test_nazwy_nowych_statusow(app):
    order = zamowienie(statusy=('zweryfikowane', 'zaladowane', 'dostarczone'))
    assert [p.status_display_name for p in order.products] == ['Zweryfikowane', u'Załadowane', 'Dostarczone']


def test_kolumny_weryfikacji_i_problemu_na_zamowieniu(app):
    chwila = datetime(2026, 10, 1, 9, 30)
    order = zamowienie(statusy=('spakowane',), verified_at=chwila, verified_by_worker_id=3,
                       problem_reason='etykieta', problem_note=u'nieczytelna', problem_at=chwila,
                       problem_by_worker_id=4, repack_reason=u'Weryfikacja: Etykieta')
    o = ProductionOrder.query.get(order.id)
    assert (o.verified_at, o.verified_by_worker_id, o.problem_reason, o.problem_note, o.problem_at,
            o.problem_by_worker_id, o.repack_reason) == \
        (chwila, 3, 'etykieta', u'nieczytelna', chwila, 4, u'Weryfikacja: Etykieta')
    pusty = zamowienie()
    assert (pusty.verified_at, pusty.problem_at, pusty.repack_reason) == (None, None, None)


def test_akcje_logu_weryfikacji():
    assert list(AKCJE_LOGU) == STARE_AKCJE + ['weryfikacja', 'weryfikacja_cofnieta', 'problem',
                                              'problem_rozwiazany', 'cofniete_do_pakowania']


def test_indeks_paczek_po_zamowieniu_i_uniewaznieniu():
    indeksy = {i.name: [c.name for c in i.columns] for i in ProductionPackage.__table__.indexes}
    assert indeksy['ix_prod_packages_order_voided'] == ['order_id', 'voided_at']
    assert 'ix_prod_packages_voided_at' not in indeksy
    assert indeksy['ix_prod_packages_order_id'] == ['order_id']


def test_migracja():
    sql, polecenia = _polecenia()
    status = next(p for p in polecenia
                  if p.startswith('ALTER TABLE prod_products MODIFY COLUMN current_status'))
    assert _wartosci(status) == list(ProductionProduct.current_status.type.enums)
    assert 'COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT' in status
    log = next(p for p in polecenia if p.startswith('ALTER TABLE prod_logistics_log MODIFY action'))
    assert _wartosci(log) == list(AKCJE_LOGU)
    for kolumna in ('verified_at DATETIME NULL', 'verified_by_worker_id INT NULL',
                    'problem_reason VARCHAR(32) NULL', 'problem_note VARCHAR(255) NULL',
                    'problem_at DATETIME NULL', 'problem_by_worker_id INT NULL',
                    'repack_reason VARCHAR(255) NULL'):
        assert 'ALTER TABLE prod_orders ADD COLUMN %s' % kolumna in sql, kolumna
    # 7 kolumn + nowy indeks + zdjęcie starego — każdy osłonięty warunkiem.
    assert sql.count('FROM information_schema.COLUMNS') == 7
    assert sql.count('FROM information_schema.STATISTICS') == 2
    assert sql.count('PREPARE krok FROM @sql') == 9
    assert 'ALTER TABLE prod_packages ADD INDEX ix_prod_packages_order_voided (order_id, voided_at)' in sql
    assert 'ALTER TABLE prod_packages DROP INDEX ix_prod_packages_voided_at' in sql
    od = next(p for p in polecenia if p.startswith('INSERT IGNORE INTO prod_config'))
    assert "'logistyka_weryfikacja_od'" in od and 'CAST(NOW() AS CHAR)' in od
    wydane = next(p for p in polecenia if p.startswith('UPDATE prod_products'))
    assert "SET p.current_status = 'dostarczone'" in wydane
    assert 'o.handed_over_at IS NOT NULL' in wydane and "p.current_status = 'spakowane'" in wydane
    assert polecenia.index(status) < polecenia.index(wydane)
    assert 'DELIMITER' not in sql.upper()


def test_runner_rozpoznaje_migracje():
    nazwa = os.path.basename(MIGRACJA)
    assert MigrationService(db=None)._match(nazwa) is not None
    assert nazwa > '2026-09-30-logistyka-paczki.sql'
```

- [ ] **Step 2: Testy reguły, które padną**

Create `tests/test_weryfikacja_regula.py`:

```python
# -*- coding: utf-8 -*-
"""Jedna reguła unieważniania etapów (logistyka etap 4, krok 4.3, spec 4.5 ostatni wiersz i 8.5)."""
from datetime import datetime

from sqlalchemy import event

from extensions import db
from modules.production.logistics.models import LogisticsLog
from modules.production.logistics.services import weryfikacja
from modules.production.models import LabelPrintJob, ProductionPackage
from tests.logistyka_fixtures import app, produkt, zamowienie  # noqa: F401

TERAZ = datetime(2026, 10, 1, 9, 0)
DEKLARACJA = datetime(2026, 9, 30, 15, 0)


def _z_paczkami(statusy=('spakowane', 'spakowane'), n=2, zweryfikowane=False, **kolumny):
    order = zamowienie(sposob='kurier_baselinker', statusy=statusy,
                       packages_declared_at=DEKLARACJA, **kolumny)
    lista = [ProductionPackage(order_id=order.id, seq=i, kind='paczka', declared_at=DEKLARACJA,
                               verified_at=DEKLARACJA if zweryfikowane else None)
             for i in range(1, n + 1)]
    db.session.add_all(lista)
    db.session.commit()
    return order, lista


def test_zamowienie_w_calosci_spakowane_bez_zmian(app):
    order, lista = _z_paczkami()
    assert weryfikacja.uniewaznij_etapy(order, TERAZ, u'kontrola') is False
    assert all(p.voided_at is None for p in lista)
    assert order.packages_declared_at == DEKLARACJA and LogisticsLog.query.count() == 0


def test_nowa_pozycja_uniewaznia_paczki_weryfikacje_i_wydruki(app):
    order, lista = _z_paczkami(statusy=('zweryfikowane', 'zweryfikowane'), zweryfikowane=True,
                               verified_at=DEKLARACJA, verified_by_worker_id=7)
    zadanie = LabelPrintJob(printer='wysylka', package_id=lista[0].id, short_product_id=lista[0].kod,
                            zpl_payload='^XA^XZ', station_code='packaging',
                            requested_by_type='device', requested_by_id='TAB-1')
    db.session.add(zadanie)
    produkt(order, status='czeka_na_wyciecie')
    db.session.commit()

    assert weryfikacja.uniewaznij_etapy(order, TERAZ, u'nowa pozycja z Base.', user_id=5) is True
    db.session.commit()

    assert [p.current_status for p in order.products] == ['spakowane', 'spakowane', 'czeka_na_wyciecie']
    assert (order.packages_declared_at, order.verified_at, order.verified_by_worker_id) == (None, None, None)
    assert [p.voided_at for p in ProductionPackage.query.filter_by(order_id=order.id)] == [TERAZ, TERAZ]
    wygaszone = LabelPrintJob.query.get(zadanie.id)
    assert wygaszone.status == LabelPrintJob.STATUS_EXPIRED
    assert wygaszone.error_message == u'Paczka unieważniona — nowa pozycja z Base.'
    wpisy = {w.action: w for w in LogisticsLog.query.filter_by(order_id=order.id)}
    assert set(wpisy) == {'paczki', 'weryfikacja_cofnieta'}
    assert (wpisy['paczki'].old_value, wpisy['paczki'].new_value, wpisy['paczki'].note,
            wpisy['paczki'].user_id) == (u'2 × paczka', None, u'nowa pozycja z Base.', 5)
    assert wpisy['weryfikacja_cofnieta'].note == u'nowa pozycja z Base.'
    assert all(p.updated_at == TERAZ for p in order.products)   # ETag kolejek tabletów


def test_dostarczone_zostaja_zaladowane_wracaja(app):
    """Decyzja Konrada 30.09: towar u klienta jest u klienta."""
    order, _ = _z_paczkami(statusy=('dostarczone', 'zaladowane'))
    produkt(order, status='czeka_na_formatowanie')
    db.session.commit()
    assert weryfikacja.uniewaznij_etapy(order, TERAZ, u'doróbka') is True
    assert [p.current_status for p in order.products] == ['dostarczone', 'spakowane', 'czeka_na_formatowanie']


def test_zamowienie_w_produkcji_bez_paczek_bez_zmian(app):
    order = zamowienie(statusy=('czeka_na_pakowanie', 'spakowane'))
    assert weryfikacja.uniewaznij_etapy(order, TERAZ, u'kontrola') is False
    assert LogisticsLog.query.count() == 0


def test_anulowana_pozycja_nie_wraca_zamowienia(app):
    order, lista = _z_paczkami(statusy=('spakowane', 'anulowane'))
    assert weryfikacja.uniewaznij_etapy(order, TERAZ, u'kontrola') is False
    assert all(p.voided_at is None for p in lista)


def test_pozycje_zweryfikowane_bez_deklaracji_tez_wracaja(app):
    """Stan „zweryfikowane bez paczek” (np. po ręcznej zmianie admina) — reguła i tak go czyści."""
    order = zamowienie(statusy=('zweryfikowane', 'czeka_na_pakowanie'))
    assert weryfikacja.uniewaznij_etapy(order, TERAZ, u'zmiana statusu w panelu') is True
    assert order.products[0].current_status == 'spakowane'


def test_bez_zapytan_gdy_nie_ma_czego_kasowac(app):
    """Cron woła regułę dla każdego otwartego zamówienia — bez pracy ma nie pytać bazy."""
    zamowienia = [zamowienie(statusy=('czeka_na_wyciecie', 'spakowane')) for _ in range(3)]
    for o in zamowienia:
        assert len(o.products) == 2
    zapytania = []

    def licz(*_a, **_k):
        zapytania.append(1)

    event.listen(db.engine, 'before_cursor_execute', licz)
    try:
        for o in zamowienia:
            assert weryfikacja.uniewaznij_etapy(o, TERAZ, u'kontrola') is False
    finally:
        event.remove(db.engine, 'before_cursor_execute', licz)
    assert zapytania == []


def test_ponowione_zakoncz_pakowania_nie_cofa_statusu_logistyki(app, monkeypatch):
    """Kolejka offline tabletu może dosłać „ZAKOŃCZ” po weryfikacji — pozycja zostaje zweryfikowana,
    a po_spakowaniu się nie odpala (dziś spakowane → spakowane też niczego nie zmienia)."""
    from modules.production.logistics.services import delivery
    wolania = []
    monkeypatch.setattr(delivery, 'po_spakowaniu', lambda *a, **k: wolania.append(a))
    for status in ('zweryfikowane', 'zaladowane', 'dostarczone'):
        order = zamowienie(sposob='kurier_baselinker', statusy=(status,))
        order.products[0].complete_task('packaging')
        assert order.products[0].current_status == status
    assert wolania == []
```

- [ ] **Step 3: Uruchom — mają paść**

Run: `PYTEST tests/test_weryfikacja_schemat.py tests/test_weryfikacja_regula.py`
Expected: FAIL przy imporcie (`ImportError: cannot import name 'weryfikacja'`) albo `AttributeError: … STATUSY_PO_SPAKOWANIU`.

- [ ] **Step 4: Migracja**

Create `migrations/2026-09-30-logistyka-weryfikacja.sql`:

```sql
-- Logistyka etap 4, krok 4.3 (spec 2026-09-30-logistyka-etap-4-weryfikacja-dostawa-design.md, sekcje 4, 5.3,
-- 5.5 i 8): statusy pozycji po spakowaniu, kolumny weryfikacji, problemu i banera przepakowania na
-- zamówieniu, akcje logu Weryfikacji, indeks paczek po (zamówienie, unieważnienie) i chwila startu listy
-- „Do weryfikacji”. Idempotentna: MODIFY enumów jest idempotentny sam z siebie, ALTER dodające kolumny i
-- zmieniające indeksy osłonięte warunkiem z information_schema przez PREPARE/EXECUTE (bez zmiany
-- separatora poleceń), wiersz konfiguracji przez INSERT IGNORE, przepisanie wydanych - warunkiem na status.

-- Nowe wartości NA KOŃCU listy: MySQL 8 zmienia wtedy same metadane (bez przebudowy tabeli). Zestaw
-- znaków i porównywanie jak w bazie produkcyjnej (kolumna ma je jawnie w SHOW CREATE TABLE).
ALTER TABLE prod_products MODIFY COLUMN current_status ENUM(
    'czeka_na_wyciecie','czeka_na_skladanie','czeka_na_sklejanie',
    'czeka_na_formatowanie','czeka_na_krawedzie','czeka_na_lakiernie',
    'czeka_na_logistyke','czeka_na_pakowanie',
    'spakowane','anulowane','wstrzymane','w_realizacji',
    'zweryfikowane','zaladowane','dostarczone'
) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'czeka_na_wyciecie';

-- Zamówienie zweryfikowane (kto i kiedy), zgłoszony problem (NULL = brak) i tekst banera przepakowania
-- na tablecie pakowania (uzupełnia repack_required).
SET @brak = (SELECT COUNT(*) = 0 FROM information_schema.COLUMNS
             WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'prod_orders' AND COLUMN_NAME = 'verified_at');
SET @sql = IF(@brak, 'ALTER TABLE prod_orders ADD COLUMN verified_at DATETIME NULL',
              'SELECT "verified_at juz jest" AS info');
PREPARE krok FROM @sql; EXECUTE krok; DEALLOCATE PREPARE krok;

SET @brak = (SELECT COUNT(*) = 0 FROM information_schema.COLUMNS
             WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'prod_orders' AND COLUMN_NAME = 'verified_by_worker_id');
SET @sql = IF(@brak, 'ALTER TABLE prod_orders ADD COLUMN verified_by_worker_id INT NULL',
              'SELECT "verified_by_worker_id juz jest" AS info');
PREPARE krok FROM @sql; EXECUTE krok; DEALLOCATE PREPARE krok;

SET @brak = (SELECT COUNT(*) = 0 FROM information_schema.COLUMNS
             WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'prod_orders' AND COLUMN_NAME = 'problem_reason');
SET @sql = IF(@brak, 'ALTER TABLE prod_orders ADD COLUMN problem_reason VARCHAR(32) NULL',
              'SELECT "problem_reason juz jest" AS info');
PREPARE krok FROM @sql; EXECUTE krok; DEALLOCATE PREPARE krok;

SET @brak = (SELECT COUNT(*) = 0 FROM information_schema.COLUMNS
             WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'prod_orders' AND COLUMN_NAME = 'problem_note');
SET @sql = IF(@brak, 'ALTER TABLE prod_orders ADD COLUMN problem_note VARCHAR(255) NULL',
              'SELECT "problem_note juz jest" AS info');
PREPARE krok FROM @sql; EXECUTE krok; DEALLOCATE PREPARE krok;

SET @brak = (SELECT COUNT(*) = 0 FROM information_schema.COLUMNS
             WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'prod_orders' AND COLUMN_NAME = 'problem_at');
SET @sql = IF(@brak, 'ALTER TABLE prod_orders ADD COLUMN problem_at DATETIME NULL',
              'SELECT "problem_at juz jest" AS info');
PREPARE krok FROM @sql; EXECUTE krok; DEALLOCATE PREPARE krok;

SET @brak = (SELECT COUNT(*) = 0 FROM information_schema.COLUMNS
             WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'prod_orders' AND COLUMN_NAME = 'problem_by_worker_id');
SET @sql = IF(@brak, 'ALTER TABLE prod_orders ADD COLUMN problem_by_worker_id INT NULL',
              'SELECT "problem_by_worker_id juz jest" AS info');
PREPARE krok FROM @sql; EXECUTE krok; DEALLOCATE PREPARE krok;

SET @brak = (SELECT COUNT(*) = 0 FROM information_schema.COLUMNS
             WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'prod_orders' AND COLUMN_NAME = 'repack_reason');
SET @sql = IF(@brak, 'ALTER TABLE prod_orders ADD COLUMN repack_reason VARCHAR(255) NULL',
              'SELECT "repack_reason juz jest" AS info');
PREPARE krok FROM @sql; EXECUTE krok; DEALLOCATE PREPARE krok;

-- Log logistyki: akcje Weryfikacji. Lista MUSI zawierać wszystkie dotychczasowe wartości (także 'paczki'
-- z kroku 4.2) - MODIFY podaje pełną listę, a brakująca wartość skasowałaby akcję wpisom w logu.
ALTER TABLE prod_logistics_log MODIFY action
    ENUM('sposob_dostawy','wydane','przepakowanie',
         'trasa_dodane','trasa_usuniete','trasa_status','adres','paczki',
         'weryfikacja','weryfikacja_cofnieta','problem','problem_rozwiazany','cofniete_do_pakowania')
    COLLATE utf8mb4_unicode_ci NOT NULL;

-- Paczki czytamy zawsze po zamówieniu i unieważnieniu (aktualna deklaracja = voided_at IS NULL).
-- Nowy indeks zastępuje osobny indeks po voided_at, który nie ma żadnych zapytań.
SET @brak = (SELECT COUNT(*) = 0 FROM information_schema.STATISTICS
             WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'prod_packages'
               AND INDEX_NAME = 'ix_prod_packages_order_voided');
SET @sql = IF(@brak, 'ALTER TABLE prod_packages ADD INDEX ix_prod_packages_order_voided (order_id, voided_at)',
              'SELECT "ix_prod_packages_order_voided juz jest" AS info');
PREPARE krok FROM @sql; EXECUTE krok; DEALLOCATE PREPARE krok;

SET @jest = (SELECT COUNT(*) > 0 FROM information_schema.STATISTICS
             WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'prod_packages'
               AND INDEX_NAME = 'ix_prod_packages_voided_at');
SET @sql = IF(@jest, 'ALTER TABLE prod_packages DROP INDEX ix_prod_packages_voided_at',
              'SELECT "ix_prod_packages_voided_at juz usuniety" AS info');
PREPARE krok FROM @sql; EXECUTE krok; DEALLOCATE PREPARE krok;

-- Lista „Do weryfikacji” (decyzja Konrada 30.09): zamówienia zamknięte w Logistyce (kurier) trafiają na nią
-- tylko, gdy spakowano je w ostatnich 7 dniach i nie wcześniej niż wdrożenie tego kroku. INSERT IGNORE:
-- pierwsze wykonanie zapisuje chwilę wdrożenia, kolejne jej nie ruszają.
INSERT IGNORE INTO prod_config (config_key, config_value, config_description, config_type, created_at, updated_at)
VALUES ('logistyka_weryfikacja_od', CAST(NOW() AS CHAR),
        'Logistyka: lista Do weryfikacji obejmuje zamówienia spakowane od tej chwili (wdrożenie kroku 4.3)',
        'string', NOW(), NOW());

-- „Wydane klientowi” od kroku 4.3 ustawia pozycje na 'dostarczone' - zamówienia wydane wcześniej dostają
-- ten sam stan. Zwykły UPDATE omija audyt prod_product_events (listener działa tylko w ORM) - świadomie:
-- to przepisanie historii, nie czyjaś praca.
UPDATE prod_products p
  JOIN prod_orders o ON o.id = p.order_id
   SET p.current_status = 'dostarczone'
 WHERE o.handed_over_at IS NOT NULL AND p.current_status = 'spakowane';
```

- [ ] **Step 5: Stałe w `sposoby.py`**

W `modules/production/logistics/sposoby.py` po `STATUS_PO_SPAKOWANIU = {…}` dopisz:

```python
# Statusy pozycji „spakowane lub dalej” (logistyka etap 4, spec 4.1): produkcja zakończona, towar
# spakowany. Jedna stała na cały CRM — tam, gdzie kod pyta, czy pozycja wyszła z produkcji, a nie
# czy czeka dokładnie na weryfikację. W JS i szablonach — kopia listy z odsyłaczem tutaj.
STATUSY_PO_SPAKOWANIU = ('spakowane', 'zweryfikowane', 'zaladowane', 'dostarczone')
# Statusy nadawane wyłącznie przez logistykę (Weryfikacja, „Wydane klientowi”, Dostawa w kroku 4.4) —
# hurtowa zmiana statusu ich nie oferuje, a deklaracja paczek po nich odmawia (409 order_verified).
STATUSY_LOGISTYCZNE = ('zweryfikowane', 'zaladowane', 'dostarczone')
# Tekst banera na tablecie pakowania przy przepakowaniu na kuriera (transport.repack_reason).
PRZEPAKUJ_NA_KURIERA = u'Przepakuj na kuriera'
```

- [ ] **Step 6: Modele**

W `modules/production/models.py`:

1. `ProductionOrder` — po `packages_declared_at = Column(DateTime)` dopisz:

```python
    # Weryfikacja (logistyka etap 4, krok 4.3): kto i kiedy zweryfikował wszystkie paczki.
    verified_at = Column(DateTime)
    verified_by_worker_id = Column(Integer)
    # Problem zgłoszony przy weryfikacji; NULL = brak. Powody: weryfikacja.POWODY_PROBLEMU.
    problem_reason = Column(String(32))
    problem_note = Column(String(255))
    problem_at = Column(DateTime)
    problem_by_worker_id = Column(Integer)
    # Tekst banera na tablecie pakowania, gdy repack_required (np. „Weryfikacja: Uszkodzenie: …”).
    repack_reason = Column(String(255))
```

2. `ProductionProduct.current_status`:

```python
    current_status = Column(Enum(
        'czeka_na_wyciecie', 'czeka_na_skladanie',
        'czeka_na_sklejanie', 'czeka_na_formatowanie', 'czeka_na_krawedzie',
        'czeka_na_lakiernie', 'czeka_na_logistyke', 'czeka_na_pakowanie',
        'spakowane', 'anulowane', 'wstrzymane', 'w_realizacji',
        # Logistyka etap 4 (krok 4.3) — po spakowaniu, dopisane NA KOŃCU (migracja
        # 2026-09-30-logistyka-weryfikacja.sql); nadaje je tylko logistyka (sposoby.STATUSY_LOGISTYCZNE).
        'zweryfikowane', 'zaladowane', 'dostarczone',
        name='production_status'
    ), default='czeka_na_wyciecie', nullable=False, index=True)
```

3. `status_display_name` — po `'spakowane': 'Spakowane',` dopisz:

```python
            'zweryfikowane': 'Zweryfikowane',
            'zaladowane': 'Załadowane',
            'dostarczone': 'Dostarczone',
```

4. `complete_task` — zaraz po `station_code = resolve_station_code(station_code)` (przed `now = get_local_now()`) dopisz:

```python
        # Logistyka etap 4: pozycja zweryfikowana, załadowana albo dostarczona jest już „dalej niż
        # spakowana”. Ponowione z kolejki offline „ZAKOŃCZ” pakowania nie może jej cofnąć do
        # 'spakowane' (zamówienie straciłoby spójny stan weryfikacji). Dziś spakowane → spakowane
        # też niczego nie zmienia, więc strażnik tylko utrzymuje to zachowanie dla nowych statusów.
        if station_code == 'packaging':
            from modules.production.logistics import sposoby as _sposoby
            if self.current_status in _sposoby.STATUSY_LOGISTYCZNE:
                self.updated_at = get_local_now()
                return
```

5. `ProductionPackage` — `voided_at = Column(DateTime, index=True)` → `voided_at = Column(DateTime)`, a po `__tablename__ = 'prod_packages'` dopisz (i dodaj `Index` do importu z `sqlalchemy` na górze pliku, jeśli go nie ma):

```python
    # Aktualna deklaracja = paczki zamówienia z voided_at IS NULL — tak pytają wszystkie odczyty
    # (migracja 2026-09-30-logistyka-weryfikacja.sql zastąpiła tym osobny indeks po voided_at).
    __table_args__ = (Index('ix_prod_packages_order_voided', 'order_id', 'voided_at'),)
```

W `modules/production/logistics/models.py`:

```python
AKCJE_LOGU = ('sposob_dostawy', 'wydane', 'przepakowanie',
              'trasa_dodane', 'trasa_usuniete', 'trasa_status', 'adres',
              'paczki',
              # Weryfikacja (logistyka etap 4, krok 4.3).
              'weryfikacja', 'weryfikacja_cofnieta', 'problem', 'problem_rozwiazany',
              'cofniete_do_pakowania')
```

- [ ] **Step 7: `paczki.uniewaznij` z powodem**

W `modules/production/logistics/services/paczki.py` (domyślna wartość zachowuje tekst z kroku 4.2 — sprawdza go `tests/test_paczki_deklaracja.py:193`):

```python
def uniewaznij(lista, teraz, powod=u'nowa deklaracja paczek'):
    """
    Unieważnia paczki (wiersze zostają — skan starej etykiety ma dostać „nieaktualna”) i
    w tej samej transakcji wygasza ich oczekujące zadania druku (`pending` → `expired`).
    Agent druku pobiera właśnie `pending`, więc bez tego etykiety starych paczek wyszłyby
    na drukarkę obok nowych (np. po przerwie w pracy agenta). Zadań `printed` i `failed`
    nie ruszamy; zadanie już przekazane do spoolera Windows jest poza zasięgiem CRM.
    `powod` trafia do komunikatu wygaszonego zadania. Zwraca liczbę unieważnionych paczek.
    """
    for p in lista:
        p.voided_at = teraz
    if lista:
        (LabelPrintJob.query
         .filter(LabelPrintJob.status == LabelPrintJob.STATUS_PENDING,
                 LabelPrintJob.package_id.in_([p.id for p in lista]))
         .update({'status': LabelPrintJob.STATUS_EXPIRED,
                  'error_message': u'Paczka unieważniona — {}'.format(powod)},
                 synchronize_session=False))
    return len(lista)
```

- [ ] **Step 8: Reguła w nowym serwisie**

Create `modules/production/logistics/services/weryfikacja.py`:

```python
# -*- coding: utf-8 -*-
"""
Weryfikacja paczek (logistyka etap 4, krok 4.3, spec 4.4–4.5 i 8).

Tu żyje jedna reguła unieważniania etapów (paczki, weryfikacja, załadunek) po powrocie pozycji do
produkcji, definicja listy „Do weryfikacji” i akcje stanowiska Weryfikacja. Funkcje NIE commitują —
robi to wołający (API mobilne przez @with_idempotency, panel, cron, synchronizacja).
"""
from extensions import db
from modules.production.logistics import sposoby
from modules.production.logistics.services import delivery, paczki

# Pozycje, które wracają do 'spakowane', gdy zamówienie wróci do produkcji. 'dostarczone' zostaje
# (decyzja Konrada 30.09): towar u klienta jest u klienta.
_COFANE_DO_SPAKOWANYCH = ('zweryfikowane', 'zaladowane')


def uniewaznij_etapy(order, teraz, powod, user_id=None, worker_id=None, device_id=None):
    """
    Jedna reguła (spec 4.5, ostatni wiersz, i 8.5): zamówienie, którego któraś niezanulowana pozycja
    nie jest „spakowane lub dalej” (doróbka, nowa pozycja z Base., przepakowanie, cofnięcie do
    pakowania, ręczna zmiana statusu), traci paczki (unieważnione razem z oczekującymi zadaniami
    druku), weryfikację i załadunek, a jego pozycje zweryfikowane i załadowane wracają do
    'spakowane'. Po ponownym spakowaniu zamówienie przechodzi kroki od nowa.

    `powod` — tekst do logu i komunikatu wygaszonego zadania druku (np. u'nowa pozycja z Base.').
    Zwraca True, gdy coś zmieniła. Gdy nie ma czego kasować, nie pyta bazy (czyta kolumny zamówienia
    i statusy już wczytanych pozycji) — woła ją cron dla każdego otwartego zamówienia. NIE commituje.

    Kolejność blokad: najpierw zapis wiersza zamówienia (flush), potem paczki (odczyt blokujący) —
    ta sama kolejność co w deklaracji i akcjach Weryfikacji (zamówienie → paczki), więc nie tworzy
    z nimi cyklu. Globalnej blokady deklaracji NIE bierze: wołający (panel, synchronizacja, tablet)
    trzymają już inne blokady, a wiersz blokady musiałby być pierwszy.
    """
    aktywne = delivery.aktywne_produkty(order)
    if not aktywne or all(p.current_status in sposoby.STATUSY_PO_SPAKOWANIU for p in aktywne):
        return False
    cofane = [p for p in aktywne if p.current_status in _COFANE_DO_SPAKOWANYCH]
    if order.packages_declared_at is None and order.verified_at is None and not cofane:
        return False
    notatka = (powod or u'')[:255] or None
    for p in cofane:
        p.current_status = 'spakowane'
    if order.verified_at is not None:
        order.verified_at = None
        order.verified_by_worker_id = None
        delivery.zapisz_log(order, 'weryfikacja_cofnieta', note=notatka, user_id=user_id,
                            worker_id=worker_id, device_id=device_id, teraz=teraz)
    if order.packages_declared_at is not None:
        order.packages_declared_at = None
        db.session.flush()   # wiersz zamówienia przed paczkami (kolejność blokad — docstring)
        stare = paczki.aktualne_paczki(order.id, do_zapisu=True)
        paczki.uniewaznij(stare, teraz, powod=powod)
        delivery.zapisz_log(order, 'paczki', paczki.opis_paczek(stare), None, note=notatka,
                            user_id=user_id, worker_id=worker_id, device_id=device_id, teraz=teraz)
    delivery.podbij_pozycje(order, teraz)
    return True
```

- [ ] **Step 9: DDL bootstrapu i testy starej migracji**

1. `scripts/create_split_tables.sql:89` — w liście ENUM `current_status` dopisz na końcu `,'zweryfikowane','zaladowane','dostarczone'` (przed `) NOT NULL DEFAULT`).
2. `tests/test_krawedzie_model.py` — test `test_enum_statusu_ma_dokladnie_dwanascie_wartosci_bez_duplikatow` przemianuj na `test_enum_statusu_ma_pietnascie_wartosci_bez_duplikatow`, `assert len(wartosci) == 12` → `assert len(wartosci) == 15`, a w docstringu dopisz zdanie: „Od kroku 4.3 logistyki na końcu listy stoją 'zweryfikowane', 'zaladowane', 'dostarczone' (migracja 2026-09-30-logistyka-weryfikacja.sql).”
3. `tests/test_migracja_krawedzie.py` — migracja 2026-09-15 nie mogła znać wartości z 4.3, więc oba porównania z modelem odejmują `sposoby.STATUSY_LOGISTYCZNE`:
   - `test_enum_migracji_zgadza_sie_z_enumem_modelu`: `wartosci_modelu = set(ProductionProduct.current_status.type.enums)` → `wartosci_modelu = set(ProductionProduct.current_status.type.enums) - set(sposoby.STATUSY_LOGISTYCZNE)`;
   - `test_zwezajacy_alter_zgadza_sie_z_enumem_modelu`: `assert wartosci_migracji == set(ProductionProduct.current_status.type.enums)` → `assert wartosci_migracji == set(ProductionProduct.current_status.type.enums) - set(sposoby.STATUSY_LOGISTYCZNE)`;
   - w obu dopisz `from modules.production.logistics import sposoby` (obok importu modelu) i komentarz: „Wartości z kroku 4.3 logistyki dopisuje migracja 2026-09-30-logistyka-weryfikacja.sql (pilnuje jej tests/test_weryfikacja_schemat.py).”
4. `modules/dashboard/services/chart_service.py` — w `STATUS_CONFIG` po wpisie `'spakowane'` dopisz (kolory policzone w przeglądzie: odległość CIE76 ≥ 31 od wszystkich pozostałych, próg testu 25):

```python
        # Logistyka etap 4 (krok 4.3): statusy po spakowaniu — ciemne odcienie, żeby nie zlać się
        # z zielenią 'spakowane' i kolorami stanowisk.
        'zweryfikowane': {'name': 'Zweryfikowane', 'color': '#14532d'},
        'zaladowane': {'name': 'Załadowane', 'color': '#1e3a8a'},
        'dostarczone': {'name': 'Dostarczone', 'color': '#713f12'},
```

- [ ] **Step 10: Uruchom testy zadania**

Run: `PYTEST tests/test_weryfikacja_schemat.py tests/test_weryfikacja_regula.py tests/test_krawedzie_model.py tests/test_migracja_krawedzie.py tests/test_bootstrap_ddl_krawedzie.py tests/test_paczki_deklaracja.py tests/test_paczki_schemat.py tests/test_dashboard_statusy_produkcji.py`
Expected: PASS (`test_paczki_schemat.py` sprawdza plik migracji 4.2 — `'KEY ix_prod_packages_voided_at (voided_at)'` w nim zostaje).

- [ ] **Step 11: MySQL — migracja dwa razy na świeżej kopii**

Zrzut bazy podglądu **tylko do odczytu** (nie zmieniaj `logistyka4_podglad`), odtworzenie do nowej bazy i dwukrotne wykonanie pliku klientem `mysql` z pomiarem czasu (Git Bash, z katalogu worktree):

```bash
docker exec woodpower-crm-db-1 sh -c "mysqldump -uroot --single-transaction logistyka4_podglad > /tmp/l43.sql && mysql -uroot -e 'DROP DATABASE IF EXISTS logistyka43_migracja; CREATE DATABASE logistyka43_migracja CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci' && mysql -uroot logistyka43_migracja < /tmp/l43.sql"
docker cp migrations/2026-09-30-logistyka-weryfikacja.sql woodpower-crm-db-1:/tmp/l43-migracja.sql
docker exec woodpower-crm-db-1 sh -c "time mysql -uroot logistyka43_migracja < /tmp/l43-migracja.sql && time mysql -uroot logistyka43_migracja < /tmp/l43-migracja.sql"
docker exec woodpower-crm-db-1 sh -c "mysql -uroot logistyka43_migracja -e 'SHOW CREATE TABLE prod_products\G' | grep current_status"
docker exec woodpower-crm-db-1 mysql -uroot logistyka43_migracja -e "SHOW INDEX FROM prod_packages; SELECT config_value FROM prod_config WHERE config_key='logistyka_weryfikacja_od'; SELECT COUNT(*) FROM prod_products WHERE current_status='dostarczone'"
```

Expected: oba przebiegi bez błędu, każdy poniżej 5 s; ENUM z 15 wartościami; indeksy `ix_prod_packages_order_id` i `ix_prod_packages_order_voided`, bez `ix_prod_packages_voided_at`; jedna data w `logistyka_weryfikacja_od` (drugi przebieg jej nie zmienia). Czasy wpisz do raportu. Bazę `logistyka43_migracja` zostaw — użyje jej Task 10.

- [ ] **Step 12: Pełny pakiet i commit**

Run: `PYTEST tests/`
Expected: 0 failed; passed = punkt wyjścia + nowe testy zadania (w raporcie wymień testy świadomie zmienione).

```bash
git add migrations/2026-09-30-logistyka-weryfikacja.sql modules/production/logistics/services/weryfikacja.py \
  modules/production/models.py modules/production/logistics/models.py modules/production/logistics/sposoby.py \
  modules/production/logistics/services/paczki.py scripts/create_split_tables.sql \
  modules/dashboard/services/chart_service.py \
  tests/test_weryfikacja_schemat.py tests/test_weryfikacja_regula.py tests/test_krawedzie_model.py \
  tests/test_migracja_krawedzie.py
git commit -m "feat(production): statusy pozycji po spakowaniu i regula uniewazniania etapow logistyki" \
  -m "Nowe statusy zweryfikowane, zaladowane i dostarczone na koncu ENUM, kolumny weryfikacji, problemu i banera przepakowania, akcje logu Weryfikacji oraz jedna regula, ktora po powrocie pozycji do produkcji uniewaznia paczki i weryfikacje." \
  -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 2: Cykl zamówienia w logistyce — „spakowane lub dalej”, wydanie, przepakowanie, reguła w wołających

**Files:**
- Modify: `modules/production/logistics/services/delivery.py` (:18, :35–41, :58–89, :114–126, :194–295, :298–322, :395–409, :438–462)
- Modify: `modules/production/logistics/services/paczki.py` (`zadeklaruj` :278–319)
- Modify: `modules/production/services/rework_service.py` (przed commitem w `reject_product_quantity`, ok. :296)
- Modify: `modules/production/services/sync_service.py` (`apply_baselinker_changes`, koniec bloku „# 3. Dodaj nowe produkty”, ok. :2769)
- Test: `tests/test_weryfikacja_cykl.py`

**Interfaces:**
- Consumes (Task 1): `sposoby.STATUSY_PO_SPAKOWANIU`, `sposoby.STATUSY_LOGISTYCZNE`, `sposoby.PRZEPAKUJ_NA_KURIERA`, `ProductionOrder.repack_reason/.verified_at`, `weryfikacja.uniewaznij_etapy(order, teraz, powod, user_id=None, worker_id=None, device_id=None)`.
- Produces: `delivery.wszystkie_w(order, statusy) -> bool` (aktywna pozycja jest i każda niezanulowana w `statusy`); `delivery.wszystkie_spakowane(order)` = „spakowane lub dalej” (zmiana znaczenia — wołający: `lista`, `routes.wykonaj`, `paczki_druk`, `po_spakowaniu`, `ustaw_sposob_dostawy`); `delivery.STATUSY_PO_PRODUKCJI = ('czeka_na_pakowanie',) + STATUSY_PO_SPAKOWANIU`; `wydaj_klientowi` ustawia pozycje na `dostarczone`; `paczki.zadeklaruj` → `PaczkiBlad('order_verified', …, 409)` dla zamówienia z pozycją w `STATUSY_LOGISTYCZNE`.

- [ ] **Step 1: Testy, które padną**

Create `tests/test_weryfikacja_cykl.py`:

```python
# -*- coding: utf-8 -*-
"""Cykl zamówienia w logistyce po nowych statusach (logistyka etap 4, krok 4.3, spec 4.1, 4.2, 4.5, 4.6, 8.5)."""
from datetime import datetime

import pytest

from extensions import db
from modules.production.logistics import sposoby as s
from modules.production.logistics.models import LogisticsLog
from modules.production.logistics.services import delivery as d, paczki
from modules.production.models import ProductionPackage, ProductionProduct
from tests.logistyka_fixtures import app, produkt, zamowienie  # noqa: F401

T0 = datetime(2026, 10, 1, 8, 0)
T1 = datetime(2026, 10, 1, 9, 0)


def _paczki(order, n=2, zweryfikowane=False):
    lista = [ProductionPackage(order_id=order.id, seq=i, kind='paczka', declared_at=T0,
                               verified_at=T0 if zweryfikowane else None) for i in range(1, n + 1)]
    db.session.add_all(lista)
    order.packages_declared_at = T0
    db.session.commit()
    return lista


def test_spakowane_lub_dalej_i_dokladnie_spakowane(app):
    order = zamowienie(sposob=s.KURIER, statusy=('zweryfikowane', 'dostarczone', 'anulowane'))
    assert d.wszystkie_spakowane(order) is True
    assert d.wszystkie_w(order, ('spakowane',)) is False
    assert d.wszystkie_w(zamowienie(statusy=('anulowane',)), s.STATUSY_PO_SPAKOWANIU) is False
    assert d.STATUSY_PO_PRODUKCJI == ('czeka_na_pakowanie',) + s.STATUSY_PO_SPAKOWANIU


@pytest.mark.parametrize('sposob, statusy, kolumny, zamkniete', [
    (s.KURIER, ('zweryfikowane',), {}, True),
    (s.KURIER, ('spakowane', 'zweryfikowane'), {}, True),
    (s.KURIER, ('zweryfikowane', 'czeka_na_pakowanie'), {}, False),
    (s.TRANSPORT, ('zweryfikowane',), {}, False),          # transport zamyka trasa wykonana (decyzja 2)
    (s.ODBIOR, ('dostarczone',), {'handed_over_at': T0}, True),
])
def test_zamkniecie_po_nowych_statusach(app, sposob, statusy, kolumny, zamkniete):
    assert d.zamkniecie_wyliczone(zamowienie(sposob=sposob, statusy=statusy, **kolumny)) is zamkniete


@pytest.mark.parametrize('statusy', [('spakowane',), ('zweryfikowane',), ('spakowane', 'anulowane')])
def test_wydanie_klientowi_ustawia_dostarczone(app, statusy):
    order = zamowienie(sposob=s.ODBIOR, statusy=statusy)
    d.wydaj_klientowi(order, user_id=5, teraz=T0)
    assert [p.current_status for p in order.products] == \
        ['anulowane' if st == 'anulowane' else 'dostarczone' for st in statusy]
    assert (order.handed_over_at, order.bl_status_pending_id, order.logistics_closed_at) == \
        (T0, s.STATUS_ODEBRANE, T0)
    assert all(p.updated_at == T0 for p in order.products)


@pytest.mark.parametrize('statusy', [('czeka_na_pakowanie', 'spakowane'), ('zaladowane',)])
def test_wydanie_tylko_ze_spakowanego_albo_zweryfikowanego(app, statusy):
    with pytest.raises(d.LogistykaBlad):
        d.wydaj_klientowi(zamowienie(sposob=s.ODBIOR, statusy=statusy), teraz=T0)


def test_cofniecie_do_nie_ustawiono_odmawia_przy_zweryfikowanym(app):
    order = zamowienie(sposob=s.KURIER, statusy=('zweryfikowane',))
    with pytest.raises(d.LogistykaBlad):
        d.ustaw_sposob_dostawy(order, s.BRAK, teraz=T0)


def test_przepakowanie_zweryfikowanego_uniewaznia_paczki_i_weryfikacje(app):
    order = zamowienie(sposob=s.TRANSPORT, statusy=('zweryfikowane', 'zweryfikowane'),
                       verified_at=T0, verified_by_worker_id=3)
    stare = _paczki(order, zweryfikowane=True)
    wynik = d.ustaw_sposob_dostawy(order, s.KURIER, user_id=7, teraz=T1)
    db.session.commit()
    assert wynik['przepakowanie'] is True
    assert [p.current_status for p in order.products] == ['czeka_na_pakowanie', 'czeka_na_pakowanie']
    assert (order.repack_required, order.repack_reason) == (True, s.PRZEPAKUJ_NA_KURIERA)
    assert (order.verified_at, order.packages_declared_at) == (None, None)
    assert all(p.voided_at == T1 for p in ProductionPackage.query.filter_by(order_id=order.id))
    akcje = [w.action for w in LogisticsLog.query.filter_by(order_id=order.id).order_by(LogisticsLog.id)]
    assert akcje[:2] == ['sposob_dostawy', 'przepakowanie']
    assert set(akcje[2:]) == {'weryfikacja_cofnieta', 'paczki'}
    assert order.bl_status_pending_id == s.STATUS_PRODUKCJA_ZAKONCZONA


def test_zmiana_na_inny_niz_kurier_i_spakowanie_czyszcza_baner(app):
    order = zamowienie(sposob=s.KURIER, statusy=('czeka_na_pakowanie',), repack_required=True,
                       repack_reason=s.PRZEPAKUJ_NA_KURIERA)
    d.ustaw_sposob_dostawy(order, s.TRANSPORT, teraz=T0)
    assert (order.repack_required, order.repack_reason) == (False, None)
    drugie = zamowienie(sposob=s.KURIER, statusy=('spakowane',), repack_required=True,
                        repack_reason=u'Weryfikacja: Uszkodzenie')
    d.po_spakowaniu(drugie, T0)
    assert (drugie.repack_required, drugie.repack_reason) == (False, None)


def test_zaladowane_nie_zmienia_sposobu(app):
    order = zamowienie(sposob=s.TRANSPORT, statusy=('zaladowane',))
    assert d.ustaw_sposob_dostawy(order, s.TRANSPORT, teraz=T0)['zmieniono'] is False  # bez zmiany = no-op
    with pytest.raises(d.LogistykaBlad) as e:
        d.ustaw_sposob_dostawy(order, s.KURIER, teraz=T0)
    assert e.value.status == 409


def test_cron_nie_otwiera_zweryfikowanego_i_czysci_etapy_po_nowej_pozycji(app):
    zweryfikowane = zamowienie(sposob=s.KURIER, statusy=('zweryfikowane',), logistics_closed_at=T0,
                               verified_at=T0)
    z_nowa = zamowienie(sposob=s.KURIER, statusy=('spakowane',), logistics_closed_at=T0)
    _paczki(z_nowa)
    produkt(z_nowa, status='czeka_na_wyciecie')
    db.session.commit()

    d.przelicz_otwarte(teraz=T1)
    db.session.commit()

    assert zweryfikowane.logistics_closed_at == T0 and zweryfikowane.verified_at == T0
    assert z_nowa.logistics_closed_at is None and z_nowa.packages_declared_at is None
    assert all(p.voided_at == T1 for p in ProductionPackage.query.filter_by(order_id=z_nowa.id))
    assert LogisticsLog.query.filter_by(order_id=z_nowa.id, action='paczki').one().note == u'kontrola cykliczna'


@pytest.mark.parametrize('status, fragment', [
    ('zweryfikowane', u'Cofnij weryfikację'), ('zaladowane', u'załadowane'), ('dostarczone', u'dostarczone')])
def test_deklaracja_po_weryfikacji_409(app, status, fragment):
    order = zamowienie(sposob=s.KURIER, statusy=(status, status))
    with pytest.raises(paczki.PaczkiBlad) as e:
        paczki.zadeklaruj(order, paczki.Deklaracja('paczka', 1), 'verification',
                          {'type': 'device', 'id': 'TEL-1'}, teraz=T0)
    assert (e.value.kod, e.value.status) == ('order_verified', 409) and fragment in e.value.komunikat


def test_deklaracja_dalej_wymaga_dokladnie_spakowanego(app):
    order = zamowienie(sposob=s.KURIER, statusy=('spakowane', 'czeka_na_pakowanie'))
    with pytest.raises(paczki.PaczkiBlad) as e:
        paczki.zadeklaruj(order, paczki.Deklaracja('paczka', 1), 'packaging',
                          {'type': 'device', 'id': 'TAB-1'}, teraz=T0)
    assert e.value.kod == 'order_not_packed'


def test_dorobka_uniewaznia_etapy(app):
    from modules.production.services import rework_service
    order = zamowienie(sposob=s.KURIER, statusy=('spakowane', 'czeka_na_pakowanie'))
    stare = _paczki(order, n=1)
    rework_service.reject_product_quantity(product_id=order.products[1].id, quantity=1,
                                           reason_category=sorted(rework_service.VALID_REASONS)[0],
                                           rejected_at_station='packaging')
    assert ProductionPackage.query.get(stare[0].id).voided_at is not None
    assert order.packages_declared_at is None


def test_nowa_pozycja_z_base_uniewaznia_etapy(app, monkeypatch):
    from modules.production.services.sync_service import BaselinkerSyncService
    order = zamowienie(sposob=s.KURIER, statusy=('zweryfikowane',), numer_wewnetrzny='1450',
                       verified_at=T0)
    stare = _paczki(order, n=1, zweryfikowane=True)
    serwis = BaselinkerSyncService()
    monkeypatch.setattr(serwis, 'get_order_from_baselinker', lambda _id: {
        'products': [{'order_product_id': '77', 'name': 'Blat', 'quantity': 1}]})
    monkeypatch.setattr('modules.production.services.parser_service.ProductNameParser.parse_product_name',
                        lambda self, nazwa: None)

    def nowa_pozycja(dane):
        return ProductionProduct(order_id=order.id, short_product_id=dane['short_product_id'],
                                 product_sequence_in_order=dane['product_sequence_in_order'],
                                 original_product_name=dane['original_product_name'], quantity=1,
                                 current_status='czeka_na_wyciecie')

    monkeypatch.setattr(serwis, '_create_production_product_from_data', nowa_pozycja)
    wynik = serwis.apply_baselinker_changes(order.baselinker_order_id,
                                            {'products_to_add': [{'order_product_id': '77'}]})
    assert wynik['success'] is True and wynik['added'] == 1
    db.session.expire_all()
    assert ProductionPackage.query.get(stare[0].id).voided_at is not None
    statusy = sorted(p.current_status for p in ProductionProduct.query.filter_by(order_id=order.id))
    assert statusy == ['czeka_na_wyciecie', 'spakowane']
```

- [ ] **Step 2: Uruchom — mają paść**

Run: `PYTEST tests/test_weryfikacja_cykl.py`
Expected: FAIL (`AttributeError: module … has no attribute 'wszystkie_w'` i kolejne).

- [ ] **Step 3: `delivery.py`**

1. Stała i funkcje pomocnicze (zamiast :18 i :39–41):

```python
# Pozycja „zeszła z produkcji”: czeka na pakowanie albo jest spakowana lub dalej (logistyka etap 4).
STATUSY_PO_PRODUKCJI = ('czeka_na_pakowanie',) + sposoby.STATUSY_PO_SPAKOWANIU
```

```python
def wszystkie_w(order, statusy):
    """Czy zamówienie ma aktywną (niezanulowaną) pozycję i każda aktywna jest w `statusy`."""
    aktywne = aktywne_produkty(order)
    return bool(aktywne) and all(p.current_status in statusy for p in aktywne)


def wszystkie_spakowane(order):
    """
    „Spakowane lub dalej” (logistyka etap 4, spec 4.1): towar całego zamówienia jest spakowany —
    także zweryfikowany, załadowany albo dostarczony. Tak pytają lista i trasy (przycisk „Wydane”,
    „Odhacz”), etykieta paczki i zmiana sposobu dostawy. Kto potrzebuje DOKŁADNIE 'spakowane'
    (deklaracja paczek), woła wszystkie_w(order, ('spakowane',)).
    """
    return wszystkie_w(order, sposoby.STATUSY_PO_SPAKOWANIU)
```

2. `zamkniecie_wyliczone` — gałąź kuriera (:78–79):

```python
    if sposob == sposoby.KURIER:
        # Kurier kończy cykl po spakowaniu; weryfikacja nie może go z powrotem otworzyć.
        return all(p.current_status in sposoby.STATUSY_PO_SPAKOWANIU for p in aktywne)
```

3. `po_spakowaniu` — blok flagi przepakowania:

```python
        if order.repack_required or order.repack_reason:
            order.repack_required = False
            order.repack_reason = None
            podbij_pozycje(order, teraz)
```

4. `ustaw_sposob_dostawy`:
   - zaraz po `if stary == nowy: return {…}` dopisz:

```python
    # (etap 4) Towar na aucie albo u klienta — nowy sposób dostawy wysłałby do Base. status po
    # spakowaniu i cofnął „Załadowane”/„Wysłane”/„Dostarczona”. Po porównaniu bez zmian, jak przesyłka.
    if any(p.current_status in ('zaladowane', 'dostarczone') for p in aktywne_produkty(order)):
        raise LogistykaBlad(u'Zamówienie {} jest już załadowane albo dostarczone — sposobu dostawy '
                            u'nie zmieniamy.'.format(order.internal_order_number))
```

   - w gałęzi `if cofniecie:` warunek `any(p.current_status == 'spakowane' …)` → `any(p.current_status in sposoby.STATUSY_PO_SPAKOWANIU for p in aktywne_produkty(order))`;
   - lista do przepakowania: `spakowane = [p for p in aktywne_produkty(order) if p.current_status in sposoby.STATUSY_PO_SPAKOWANIU]`;
   - w gałęzi `if przepakowanie:` po `zapisz_log(order, 'przepakowanie', …)` dopisz:

```python
        order.repack_reason = sposoby.PRZEPAKUJ_NA_KURIERA
        # Jedna reguła (spec 4.5): zamówienie wróciło do pakowania — paczki i weryfikacja kasują się.
        from modules.production.logistics.services import weryfikacja
        weryfikacja.uniewaznij_etapy(order, teraz, u'przepakowanie na kuriera', user_id=user_id)
```

   - blok `if nowy != sposoby.KURIER:` → ustawia też `order.repack_reason = None`.

5. `_cofnij_sposob` — po `order.repack_required = False` dopisz `order.repack_reason = None`.

6. `wydaj_klientowi` (cały warunek i zapis):

```python
def wydaj_klientowi(order, user_id=None, teraz=None):
    if sposoby.normalizuj(order.override_delivery_method) != sposoby.ODBIOR:
        raise LogistykaBlad(u'„Wydane klientowi” dotyczy tylko odbioru osobistego.')
    if order.handed_over_at is not None:
        raise LogistykaBlad(u'Zamówienie {} jest już wydane.'.format(order.internal_order_number))
    # Spec 4.2 i 4.4: wydanie nie czeka na weryfikację — działa ze 'spakowane' i 'zweryfikowane'.
    if not wszystkie_w(order, ('spakowane', 'zweryfikowane')):
        raise LogistykaBlad(u'Zamówienie {} nie jest jeszcze w całości spakowane.'.format(
            order.internal_order_number))
    teraz = teraz or get_local_now()
    order.handed_over_at = teraz
    order.handed_over_by = user_id
    order.bl_status_pending_id = sposoby.STATUS_ODEBRANE
    for p in aktywne_produkty(order):
        p.current_status = 'dostarczone'
    zapisz_log(order, 'wydane', user_id=user_id, teraz=teraz)
    podbij_pozycje(order, teraz)
    przelicz_zamkniecie(order, teraz)
```

7. `przelicz_otwarte` — filtr `do_otwarcia` i siatka reguły:

```python
    do_otwarcia = (ProductionOrder.query.options(selectinload(ProductionOrder.products))
                   .filter(ProductionOrder.logistics_closed_at.isnot(None))
                   .filter(or_(
                       ProductionOrder.products.any(ProductionProduct.current_status.notin_(
                           sposoby.STATUSY_PO_SPAKOWANIU + ('anulowane',))),
                       and_(ProductionOrder.override_delivery_method == sposoby.TRANSPORT,
                            ProductionOrder.id.in_(na_aktywnych_trasach))))
                   .all())
    # Siatka bezpieczeństwa jednej reguły (spec 8.5): ścieżki, które nie wołają jej same (np. przyszłe
    # zmiany statusu), dostają ją najpóźniej przy godzinnym przebiegu. Bez pracy nie pyta bazy.
    from modules.production.logistics.services import weryfikacja
    zmienione = 0
    for order in otwarte + do_otwarcia:
        weryfikacja.uniewaznij_etapy(order, teraz, u'kontrola cykliczna')
        if przelicz_zamkniecie(order, teraz):
            zmienione += 1
    return zmienione
```

Popraw docstring `przelicz_otwarte` („spakowane lub dalej” zamiast „spakowane w całości”).

- [ ] **Step 4: Blokada deklaracji po weryfikacji (`paczki.zadeklaruj`)**

Zamień początek `zadeklaruj` (warunek `if not delivery.wszystkie_spakowane(order): …`) na:

```python
    etap = next((p.current_status for p in delivery.aktywne_produkty(order)
                 if p.current_status in sposoby.STATUSY_LOGISTYCZNE), None)
    if etap is not None:
        raise PaczkiBlad('order_verified', _ODMOWA_PO_WERYFIKACJI[etap].format(
            order.internal_order_number), 409)
    if not delivery.wszystkie_w(order, ('spakowane',)):
        raise PaczkiBlad('order_not_packed', u'Zamówienie {} nie jest jeszcze w całości spakowane — '
                         u'paczki deklaruje się po spakowaniu ostatniej pozycji.'.format(
                             order.internal_order_number), 409)
```

i nad `def zadeklaruj` dopisz:

```python
# Spec 7.2 i 13: deklaracja po weryfikacji → 409 order_verified (najpierw „Cofnij weryfikację”).
_ODMOWA_PO_WERYFIKACJI = {
    'zweryfikowane': u'Zamówienie {} jest już zweryfikowane — najpierw „Cofnij weryfikację”, potem '
                     u'zadeklaruj paczki od nowa.',
    'zaladowane': u'Zamówienie {} jest już załadowane — paczek nie można zmienić.',
    'dostarczone': u'Zamówienie {} jest już dostarczone — paczek nie można zmienić.',
}
```

W docstringu `zadeklaruj` zdanie „a od kroku 4.3 zamówienie, które przestało być w całości spakowane, ma paczki unieważniane” zamień na „zamówienie, które przestało być w całości spakowane, traci paczki przez weryfikacja.uniewaznij_etapy”.

- [ ] **Step 5: Reguła w doróbce i w nowej pozycji z Base.**

`modules/production/services/rework_service.py` — w `reject_product_quantity` tuż przed `try: db.session.commit()`:

```python
    # Logistyka etap 4 (spec 8.5): doróbka w zamówieniu z paczkami albo weryfikacją — jedna reguła
    # unieważnia etapy. Doróbka ma tylko order_id, więc kolekcję pozycji zamówienia czytamy od nowa.
    if original.order is not None:
        from modules.production.logistics.services import weryfikacja
        db.session.expire(original.order, ['products'])
        weryfikacja.uniewaznij_etapy(original.order, now, u'doróbka',
                                     worker_id=(worker_ids[0] if worker_ids else None))
```

`modules/production/services/sync_service.py` — w `apply_baselinker_changes` na końcu bloku `# 3. Dodaj nowe produkty` (po pętli `for idx, product_to_add in …`, przed `# 4. Aktualizuj dane na poziomie zamówienia`), na poziomie wcięcia `if changes.get('products_to_add'):`:

```python
                if result['added']:
                    # Logistyka etap 4 (spec 8.5): nowa pozycja z Base. w zamówieniu z paczkami albo
                    # weryfikacją — jedna reguła unieważnia etapy. Nowe pozycje mają tylko order_id,
                    # więc kolekcję pozycji zamówienia czytamy od nowa.
                    from modules.production.logistics.services import weryfikacja
                    zamowienie = ProductionOrder.query.filter_by(
                        baselinker_order_id=baselinker_order_id).first()
                    if zamowienie is not None:
                        db.session.flush()
                        db.session.expire(zamowienie, ['products'])
                        weryfikacja.uniewaznij_etapy(zamowienie, get_local_now(), u'nowa pozycja z Base.')
```

- [ ] **Step 6: Uruchom testy zadania i sąsiednie**

Run: `PYTEST tests/test_weryfikacja_cykl.py tests/test_weryfikacja_regula.py tests/test_logistyka_delivery.py tests/test_logistyka_pipeline.py tests/test_logistyka_cron.py tests/test_paczki_deklaracja.py tests/test_logistyka_trasy_serwis.py tests/test_logistyka_poprawki_panelu.py tests/test_logistyka_przeglad_koncowy.py`
Expected: PASS. Jeśli padnie istniejący test pilnujący dawnego „dokładnie spakowane” w tych miejscach, zmień go świadomie i opisz w raporcie (spec 15: „testy odwołujące się do 'spakowane' przejrzane pod kątem 8.6”).

- [ ] **Step 7: Pełny pakiet i commit**

Run: `PYTEST tests/`
Expected: 0 failed.

```bash
git add modules/production/logistics/services/delivery.py modules/production/logistics/services/paczki.py \
  modules/production/services/rework_service.py modules/production/services/sync_service.py \
  tests/test_weryfikacja_cykl.py
git commit -m "feat(production): cykl logistyki traktuje zweryfikowane i dalsze statusy jak spakowane" \
  -m "Kurier zostaje zamkniety po weryfikacji, Wydane klientowi ustawia dostarczone, przepakowanie, doroka i nowa pozycja z Base. uniewazniaja paczki jedna regula, a deklaracja po weryfikacji dostaje 409 order_verified." \
  -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 3: Przegląd backendu produkcji — mapa miejsc z `'spakowane'` (spec 8.6)

Tor równoległy z Task 2 (worktree `…-t3`, `-p logistyka4-t3`, baza = commit Task 1). Pliki rozłączne z Task 2.

**Files:**
- Modify: `modules/production/routers/api/products_api.py` (:284–297, :760, :1291–1293, :1346–1352, :1562–1573, :2142–2148)
- Modify: `modules/production/routers/api/dashboard_api.py` (:292, :316, :382, :1073, :1220, :1248)
- Modify: `modules/production/routers/main_routers.py:150`, `modules/production/routers/admin_routers.py:99`
- Modify: `modules/production/routers/api/common_api.py:103`, `modules/production/routers/api/reports_api.py` (:948, :1102), `modules/production/routers/api/sync_api.py:606`
- Modify: `modules/production/routers/mobile_api.py` (:334 docstring, :374)
- Modify: `modules/production/routers/stations/monitors.py` (:172, :183, :194, :233, :255, :326, :337, :347, :383, :403)
- Modify: `modules/production/services/mobile_api_service.py:854` (+ docstring :870)
- Modify: `modules/production/services/baselinker_status_sync.py` (:61, :280–298, :436)
- Modify: `modules/production/services/{daily_report_service.py:50, dashboard_alerts.py:103, display_monitor_service.py:88/101/105/114, reports_service.py:116, order_timeline_service.py:41/53/75/190}`
- Modify: `modules/production/templates/components/reports/mix.html:198`
- Modify: `tests/test_logistyka_pipeline.py:46-47`, `tests/test_produkty_masowa_zmiana_statusu.py`, `tests/test_archive_tab.py`, `tests/test_mobile_search_archiwum.py`
- Test: `tests/test_weryfikacja_przeglad_backendu.py`

**Interfaces:**
- Consumes (Task 1): `sposoby.STATUSY_PO_SPAKOWANIU`, `sposoby.STATUSY_LOGISTYCZNE`, `weryfikacja.uniewaznij_etapy`.
- Produces: `mobile_api_service.ARCHIVE_STATUSES = frozenset(STATUSY_PO_SPAKOWANIU) | {'anulowane'}`; `baselinker_status_sync.POSTPROD_STATUSES = frozenset(('czeka_na_pakowanie',) + STATUSY_PO_SPAKOWANIU)`; bulk `update_status` odrzuca `STATUSY_LOGISTYCZNE` (400) i woła regułę.

Reguła przeglądu (z mapy w dzienniku SDD, klasy A–F): pytania „produkcja zakończona / pozycja nieaktywna / poza backlogiem / archiwum / ukończone dziś” → `sposoby.STATUSY_PO_SPAKOWANIU` (w SQL `in_(…)` / `notin_(… + ('anulowane',))`); mapy etykiet, klas i kolorów → trzy nowe wpisy; hurtowa zmiana → wykluczenie. Teksty, komentarze i statusy Base. (138623) — bez zmian. W każdym zmienianym pliku Pythona dodaj `from modules.production.logistics import sposoby` (moduł bez importów aplikacji — bez ryzyka cyklu), jeśli go nie ma.

- [ ] **Step 1: Testy, które padną**

Create `tests/test_weryfikacja_przeglad_backendu.py`:

```python
# -*- coding: utf-8 -*-
"""Przegląd miejsc z 'spakowane' (logistyka etap 4, krok 4.3, spec 8.6): nowe statusy po spakowaniu
liczą się jak „spakowane lub dalej” w backendzie produkcji."""
import os
import re
from types import SimpleNamespace as NS

import pytest

from modules.production.logistics import sposoby as s
from modules.production.services import baselinker_status_sync as bl
from modules.production.services import mobile_api_service, order_timeline_service, reports_service
from tests.logistyka_fixtures import app, zamowienie  # noqa: F401

KORZEN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Pliki przeglądu tego zadania i dopuszczalna liczba porównań z dokładnym 'spakowane' po zmianie.
# dashboard_api: jedno zostaje — log diagnostyczny liczący wiersze o statusie 'spakowane' (klasa E).
PRZEGLADANE = {
    'modules/production/routers/api/dashboard_api.py': 1,
    'modules/production/routers/api/products_api.py': 0,
    'modules/production/routers/api/reports_api.py': 0,
    'modules/production/routers/api/sync_api.py': 0,
    'modules/production/routers/main_routers.py': 0,
    'modules/production/routers/admin_routers.py': 0,
    'modules/production/routers/stations/monitors.py': 0,
    'modules/production/routers/mobile_api.py': 0,
    'modules/production/services/daily_report_service.py': 0,
    'modules/production/services/dashboard_alerts.py': 0,
    'modules/production/services/display_monitor_service.py': 0,
    'modules/production/services/reports_service.py': 0,
    'modules/production/services/order_timeline_service.py': 0,
    'modules/production/services/baselinker_status_sync.py': 0,
}
# Każdy wzorzec łapie inny zapis tego samego pytania (bez nakładania się — jedno miejsce = jedno trafienie).
_WZORCE = (r"current_status\s*[!=]=\s*'spakowane'",            # p.current_status == 'spakowane'
           r"\(\s*'spakowane'\s*,\s*'anulowane'",             # ('spakowane', 'anulowane'…), także w SQL
           r"dominant_status'?\]?\s*==\s*'spakowane'",         # monitory hali
           r"\{\s*'czeka_na_pakowanie'\s*,\s*'spakowane'\s*\}")  # dawne POSTPROD_STATUSES


@pytest.mark.parametrize('sciezka, dozwolone', sorted(PRZEGLADANE.items()))
def test_brak_porownan_z_dokladnym_spakowane(sciezka, dozwolone):
    with open(os.path.join(KORZEN, sciezka), encoding='utf-8') as f:
        tresc = f.read()
    trafienia = [m.group(0) for w in _WZORCE for m in re.finditer(w, tresc)]
    assert len(trafienia) == dozwolone, trafienia


def test_archiwum_wyszukiwarki_i_statusy_zamkniete():
    assert mobile_api_service.ARCHIVE_STATUSES == frozenset(s.STATUSY_PO_SPAKOWANIU) | {'anulowane'}
    assert set(reports_service.STATUSY_ZAMKNIETE) == set(s.STATUSY_PO_SPAKOWANIU) | {'anulowane'}


def test_linia_czasu_zna_nowe_statusy():
    porzadek = order_timeline_service.STATUS_ORDINAL
    assert porzadek['spakowane'] < porzadek['zweryfikowane'] < porzadek['zaladowane'] < porzadek['dostarczone']
    for status, nazwa in (('zweryfikowane', 'Zweryfikowane'), ('zaladowane', u'Załadowane'),
                          ('dostarczone', 'Dostarczone')):
        assert order_timeline_service._STATUS_DISPLAY[status] == nazwa
        assert order_timeline_service._STATUS_BADGE[status] == 'badge-completed'


def test_postprod_obejmuje_statusy_po_spakowaniu():
    assert bl.POSTPROD_STATUSES == frozenset(('czeka_na_pakowanie',) + s.STATUSY_PO_SPAKOWANIU)


def _pozycje(*statusy, order=None):
    return [NS(current_status=st, order=order) for st in statusy]


def test_status_po_spakowaniu_dla_zamowienia_czesciowo_zweryfikowanego(app, monkeypatch):
    """Retry statusu po spakowaniu nie może przepaść, bo zamówienie w międzyczasie zweryfikowano."""
    monkeypatch.setattr(bl, '_determine_packaging_target_status', lambda order: 138623)
    assert bl._cel_po_stanowisku(_pozycje('spakowane', 'zweryfikowane'), 'packaging') == 138623
    assert bl._cel_po_stanowisku(_pozycje('zweryfikowane', 'anulowane'), 'packaging') == 138623


@pytest.mark.parametrize('statusy', [('spakowane', 'dostarczone'), ('zaladowane',)])
def test_status_po_spakowaniu_nie_cofa_zaladowanego_ani_dostarczonego(app, monkeypatch, statusy):
    monkeypatch.setattr(bl, '_determine_packaging_target_status', lambda order: 138623)
    assert bl._cel_po_stanowisku(_pozycje(*statusy), 'packaging') is None


def test_retry_produkcji_zakonczonej_pomijany_po_weryfikacji(app, monkeypatch):
    order = zamowienie(sposob=s.KURIER, statusy=('zweryfikowane',))
    monkeypatch.setattr(bl, '_produkty_zamowienia', lambda numer: list(order.products))
    powod = bl._powod_pominiecia_ponowienia(order.internal_order_number, 'edges',
                                            bl.PRODUCTION_COMPLETED_STATUS_ID)
    assert powod == u'zamówienie już spakowane'
```

(`_powod_pominiecia_ponowienia(internal_order_number, station_code, zaplanowany_cel)` — sygnatura sprawdzona w `baselinker_status_sync.py:412`.)

Dopisz do istniejących plików:

`tests/test_produkty_masowa_zmiana_statusu.py`:

```python
@pytest.mark.parametrize('status', ['zweryfikowane', 'zaladowane', 'dostarczone'])
def test_statusow_logistyki_nie_ustawia_sie_recznie(client, app, status):
    """Spec 8.6: nowe statusy nadaje tylko logistyka — hurtowa zmiana ich nie oferuje."""
    pid, _ = produkt(app, status='czeka_na_pakowanie')
    r = _masowo(client, [pid], status)
    assert r.status_code == 400
    with app.app_context():
        assert db.session.get(ProductionProduct, pid).current_status == 'czeka_na_pakowanie'


def test_reczna_zmiana_statusu_wola_regule_uniewaznienia(client, app, monkeypatch):
    from modules.production.logistics.services import weryfikacja
    wolania = []
    monkeypatch.setattr(weryfikacja, 'uniewaznij_etapy',
                        lambda order, teraz, powod, **k: wolania.append((order.id, powod)) or False)
    pid, _ = produkt(app, status='spakowane')
    assert _masowo(client, [pid], 'czeka_na_pakowanie').status_code == 200
    with app.app_context():
        order_id = db.session.get(ProductionProduct, pid).order_id
    assert wolania == [(order_id, u'zmiana statusu w panelu')]
```

(dodaj `import pytest` na górze pliku, jeśli go nie ma).

`tests/test_archive_tab.py`:

```python
def test_zamowienia_po_weryfikacji_i_wydaniu_zostaja_w_archiwum(app, client):
    """Krok 4.3: statusy po spakowaniu to dalej „zakończone produkcyjnie” (regułę zmieni krok 4.5)."""
    baza = datetime(2026, 10, 1, 12, 0, 0)
    _zamowienie(app, '26/00011', [{'status': 'zweryfikowane', 'packaging_completed_at': baza}],
                bl_id=555011)
    _zamowienie(app, '26/00012', [{'status': 'dostarczone', 'packaging_completed_at': baza},
                                  {'status': 'spakowane', 'packaging_completed_at': baza}], bl_id=555012)
    _zamowienie(app, '26/00013', [{'status': 'zweryfikowane', 'packaging_completed_at': baza},
                                  {'status': 'czeka_na_wyciecie'}], bl_id=555013)
    numery = set(_numery(_archiwum(client)))
    assert {'26/00011', '26/00012'} <= numery and '26/00013' not in numery
```

`tests/test_mobile_search_archiwum.py`:

```python
def test_zamowienie_zweryfikowane_i_dostarczone_idzie_do_archiwum(app):
    _zamowienie(app, '700', [dict(current_status='zweryfikowane', priority_rank=1,
                                  packaging_completed_at=datetime(2026, 10, 1, 8))])
    _zamowienie(app, '710', [dict(current_status='dostarczone',
                                  packaging_completed_at=datetime(2026, 9, 30, 8))])
    _zamowienie(app, '720', [dict(current_status='czeka_na_krawedzie', priority_rank=9)])
    with app.app_context():
        items, _more, _total = search_orders_global('Kowalski', limit=50)
    assert _numery(items) == ['720', '700', '710']
```

oraz test endpointu obok `test_endpoint_oznacza_spakowane_data_i_bez_stanowiska`:

```python
def test_endpoint_oznacza_date_spakowania_po_weryfikacji(app):
    _zamowienie(app, '730', [dict(current_status='zweryfikowane',
                                  packaging_completed_at=datetime(2026, 10, 1, 9, 15))])
    with app.app_context():
        device = ProductionDevice(device_id='TAB-S2', device_name='Tablet', station_code='formatting')
        db.session.add(device)
        db.session.commit()
        token = generate_token(device)
    odp = app.test_client().get('/api/mobile/orders/search?q=Kowalski',
                                headers={'Authorization': 'Bearer ' + token, 'X-App-Version': '1.0.0'})
    assert odp.status_code == 200, odp.get_json()
    wiersze = [(o['status'], o['packed_at'], o['current_station']) for o in odp.get_json()['orders']]
    assert wiersze == [('zweryfikowane', '2026-10-01T09:15:00', None)]
```

`tests/test_logistyka_pipeline.py:46-47`:

```python
def test_postprod_bez_logistyki():
    assert bl.POSTPROD_STATUSES == frozenset(('czeka_na_pakowanie',) + s.STATUSY_PO_SPAKOWANIU)
```

- [ ] **Step 2: Uruchom — mają paść**

Run: `PYTEST tests/test_weryfikacja_przeglad_backendu.py tests/test_produkty_masowa_zmiana_statusu.py tests/test_archive_tab.py tests/test_mobile_search_archiwum.py tests/test_logistyka_pipeline.py`
Expected: FAIL w nowych testach (porównania z dokładnym 'spakowane', `ARCHIVE_STATUSES`, bulk przepuszcza nowe statusy itd.).

- [ ] **Step 3: Zmiany według mapy**

| Plik:linia | Zmiana |
|---|---|
| `products_api.py:284–297` `_archived_order_condition` | `case((ProductionItem.current_status != 'spakowane', 1), else_=0)` → `case((ProductionItem.current_status.notin_(sposoby.STATUSY_PO_SPAKOWANIU), 1), else_=0)`; docstring: „WSZYSTKIE pozycje są spakowane lub dalej (zakończone produkcyjnie; regułę archiwum zmienia krok 4.5 logistyki)” |
| `products_api.py:760` | `if p.get('current_status') in sposoby.STATUSY_PO_SPAKOWANIU + ('anulowane',): continue` |
| `products_api.py:1291–1293` | `dozwolone_statusy = (set(ProductionItem.current_status.type.enums) - {'czeka_na_logistyke'} - set(sposoby.STATUSY_LOGISTYCZNE))` z komentarzem „statusy po spakowaniu nadaje tylko logistyka (spec 8.6)”. **Literał `- {'czeka_na_logistyke'}` zostaje** (pilnuje go `tests/test_logistyka_sprzatanie.py:37`) |
| `products_api.py:1346–1352` (blok `if action == 'update_status':`) | przed `przelicz_zamkniecie(zamowienie)` dopisz `weryfikacja.uniewaznij_etapy(zamowienie, teraz, u'zmiana statusu w panelu', user_id=current_user.id)` (import `from modules.production.logistics.services import weryfikacja` obok importu `przelicz_zamkniecie`; `teraz = get_local_now()` raz przed pętlą) |
| `products_api.py:1562–1573` kolory XLSX | `'zweryfikowane': 'A5D6A7', 'zaladowane': 'B3E5FC', 'dostarczone': 'D7CCC8'` |
| `products_api.py:2142–2148` opcje filtra | po `spakowane` trzy opcje: `{'value': 'zweryfikowane', 'label': 'Zweryfikowane'}`, `{'value': 'zaladowane', 'label': 'Załadowane'}`, `{'value': 'dostarczone', 'label': 'Dostarczone'}` |
| `dashboard_api.py:292, :316, :382, :1220` | `ProductionItem.current_status != 'spakowane'` → `ProductionItem.current_status.notin_(sposoby.STATUSY_PO_SPAKOWANIU)` |
| `dashboard_api.py:1073, :1248`, `main_routers.py:150`, `dashboard_alerts.py:103` | `notin_(('spakowane', 'anulowane'))` → `notin_(sposoby.STATUSY_PO_SPAKOWANIU + ('anulowane',))` |
| `dashboard_api.py:1432–1437` | bez zmian (log diagnostyczny; dozwolone 1 trafienie w teście) |
| `admin_routers.py:99`, `reports_api.py:948`, `sync_api.py:606` | `ProductionItem.current_status == 'spakowane'` → `ProductionItem.current_status.in_(sposoby.STATUSY_PO_SPAKOWANIU)` (pozycja spakowana dziś i zweryfikowana dziś dalej jest „spakowana dziś”) |
| `common_api.py:103` `_format_status` | `'zweryfikowane': 'Zweryfikowane', 'zaladowane': 'Załadowane', 'dostarczone': 'Dostarczone'` |
| `reports_api.py:1102` `_ETYKIETY_STATUSOW_POZA_PIPELINE` | te same trzy etykiety |
| `mobile_api.py:374` | `if it.current_status in sposoby.STATUSY_PO_SPAKOWANIU and it.packaging_completed_at`; docstring :334 „archiwum (spakowane lub dalej i anulowane)” |
| `monitors.py:172, :326` `status_labels` | `'zweryfikowane': 'Zweryfikowane', 'zaladowane': 'Załadowane', 'dostarczone': 'Dostarczone'` |
| `monitors.py:183, :337` `status_class_map` | trzy nowe → `'status-completed'` |
| `monitors.py:194, :347` | `ProductionProduct.current_status != 'spakowane'` → `ProductionProduct.current_status.notin_(sposoby.STATUSY_PO_SPAKOWANIU)` |
| `monitors.py:233, :383` | `elif dominant_status == 'spakowane':` → `elif dominant_status in sposoby.STATUSY_PO_SPAKOWANIU:` |
| `monitors.py:255, :403` | `o['dominant_status'] == 'spakowane'` → `o['dominant_status'] in sposoby.STATUSY_PO_SPAKOWANIU` |
| `mobile_api_service.py:854` | `ARCHIVE_STATUSES = frozenset(sposoby.STATUSY_PO_SPAKOWANIU) \| {'anulowane'}` (import `sposoby` na górze modułu, jeśli go nie ma); docstring :870 „spakowane lub dalej/anulowane” |
| `baselinker_status_sync.py:27` (docstring modułu) | „Warunek: wszystkie aktywne pozycje mają current_status == 'spakowane'” → „Warunek: wszystkie aktywne pozycje są spakowane lub dalej (sposoby.STATUSY_PO_SPAKOWANIU), żadna nie jest załadowana ani dostarczona” (strażnik tekstowy liczy też docstringi) |
| `baselinker_status_sync.py:61` | `POSTPROD_STATUSES = frozenset(('czeka_na_pakowanie',) + sposoby.STATUSY_PO_SPAKOWANIU)` |
| `baselinker_status_sync.py:293–296` (gałąź `packaging` w `_cel_po_stanowisku`) | zob. kod niżej |
| `baselinker_status_sync.py:436` | `all(p.current_status == 'spakowane' for p in aktywne)` → `all(p.current_status in sposoby.STATUSY_PO_SPAKOWANIU for p in aktywne)` |
| `daily_report_service.py:50` | `_STATUSY_POZA_BACKLOGIEM = sposoby.STATUSY_PO_SPAKOWANIU + ('anulowane',)` |
| `reports_service.py:116` | `STATUSY_ZAMKNIETE = sposoby.STATUSY_PO_SPAKOWANIU + ('anulowane',)` |
| `display_monitor_service.py:88, :101, :105, :114` | zob. kod niżej |
| `order_timeline_service.py:41` `STATUS_ORDINAL` | `'zweryfikowane': 7, 'zaladowane': 8, 'dostarczone': 9` (bez wpisu kropka „Pakowanie” szarzeje) |
| `order_timeline_service.py:53` `_STATUS_DISPLAY` | trzy etykiety jak wyżej |
| `order_timeline_service.py:75` `_STATUS_BADGE` | trzy nowe → `'badge-completed'` |
| `order_timeline_service.py:190` | `completed = sum(1 for p in products if p.current_status in sposoby.STATUSY_PO_SPAKOWANIU)` |
| `templates/components/reports/mix.html:198` `colorMap` | `'zweryfikowane': '#14532d', 'zaladowane': '#1e3a8a', 'dostarczone': '#713f12'` (policzone w przeglądzie: CIE76 ≥ 29 do wszystkich wpisów mapy) |

`baselinker_status_sync.py` — gałąź pakowania w `_cel_po_stanowisku`:

```python
    if station_code == 'packaging':
        if not all(p.current_status in sposoby.STATUSY_PO_SPAKOWANIU for p in aktywne):
            return None
        # (logistyka etap 4) Towar na aucie albo u klienta: status po spakowaniu cofnąłby Base.
        # z „Załadowane”/„Wysłane”/„Dostarczona”/„Odebrane” (jak strażnik handed_over_at niżej).
        # 'zweryfikowane' przechodzi — ponowienie nie może przepaść przez szybką weryfikację.
        if any(p.current_status in ('zaladowane', 'dostarczone') for p in aktywne):
            return None
        return _determine_packaging_target_status(aktywne[0].order)
```

`display_monitor_service.py` — nad `_build_aggregation_sql` dopisz stałe i użyj ich w czterech miejscach:

```python
from modules.production.logistics import sposoby

# Statusy „poza produkcją” w surowym SQL — literały składane ze stałych kodu, nie z danych.
_SQL_ZAKONCZONE = ','.join("'%s'" % st for st in sposoby.STATUSY_PO_SPAKOWANIU + ('anulowane',))
_SQL_NIEAKTYWNE = _SQL_ZAKONCZONE + ",'wstrzymane'"
```

np. `f"AND pp.current_status NOT IN ({_SQL_NIEAKTYWNE}) "` (trzy miejsca z `'wstrzymane'`) i `"AND pp.current_status NOT IN (" + _SQL_ZAKONCZONE + ") "` (overdue).

- [ ] **Step 4: Uruchom testy zadania i sąsiednie**

Run: `PYTEST tests/test_weryfikacja_przeglad_backendu.py tests/test_produkty_masowa_zmiana_statusu.py tests/test_archive_tab.py tests/test_mobile_search_archiwum.py tests/test_logistyka_pipeline.py tests/test_logistyka_sprzatanie.py tests/test_baselinker_krawedzie.py tests/test_order_timeline_service.py tests/test_reports_service.py tests/test_produkty_etykiety_statusow_eksport.py tests/test_display_monitor_service.py tests/test_dashboard_statusy_produkcji.py`
Expected: PASS.

- [ ] **Step 5: Pełny pakiet i commit**

Run: `PYTEST tests/` (w worktree toru, `-p logistyka4-t3`)
Expected: 0 failed.

```bash
git add modules/production/routers modules/production/services/baselinker_status_sync.py \
  modules/production/services/mobile_api_service.py modules/production/services/daily_report_service.py \
  modules/production/services/dashboard_alerts.py modules/production/services/display_monitor_service.py \
  modules/production/services/reports_service.py modules/production/services/order_timeline_service.py \
  modules/production/templates/components/reports/mix.html tests/test_weryfikacja_przeglad_backendu.py \
  tests/test_produkty_masowa_zmiana_statusu.py tests/test_archive_tab.py tests/test_mobile_search_archiwum.py \
  tests/test_logistyka_pipeline.py
git commit -m "feat(production): statusy po spakowaniu w raportach, dashboardzie, monitorach i archiwum" \
  -m "Przeglad miejsc z 'spakowane' (spec 8.6): pytania o produkcje zakonczona licza zweryfikowane, zaladowane i dostarczone, mapy etykiet i kolorow znaja nowe statusy, hurtowa zmiana statusu ich nie oferuje i uniewaznia etapy logistyki." \
  -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

Przed `git add modules/production/routers` sprawdź `git status` — w torze nie może być zmian spoza tego zadania.

---

### Task 4: Front produkcji — etykiety i klasy nowych statusów

Tor równoległy z Task 5 (worktree `…-t4`, `-p logistyka4-t4`, baza = główna gałąź po scaleniu Task 3).

**Files:**
- Modify: `modules/production/static/js/modules/products-module.js` (:43, :69, :1415, :1778, :1798, :2138, :3409, :3540, :4119, :4179, :4680)
- Modify: `modules/production/static/js/modules/archive-module.js` (:29, :946, :961)
- Test: `tests/test_weryfikacja_front_produkcji.py`; rozszerz `tests/test_produkty_formularz_statusu.py`, `tests/test_produkty_js_klasy_statusow.py`

**Interfaces:**
- Consumes: nazwy statusów `zweryfikowane`, `zaladowane`, `dostarczone` (Task 1).
- Produces: w `products-module.js` stała `STATUSY_PO_SPAKOWANIU = ['spakowane', 'zweryfikowane', 'zaladowane', 'dostarczone']` (kopia `sposoby.STATUSY_PO_SPAKOWANIU`).

- [ ] **Step 1: Testy, które padną**

Create `tests/test_weryfikacja_front_produkcji.py`:

```python
# -*- coding: utf-8 -*-
"""Front listy produktów i archiwum zna statusy po spakowaniu (logistyka etap 4, krok 4.3, spec 8.6).
Testy tekstowe jak tests/test_produkty_js_klasy_statusow.py."""
import os
import re

from modules.production.logistics import sposoby

KORZEN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JS = os.path.join(KORZEN, 'modules', 'production', 'static', 'js', 'modules')
NOWE = {'zweryfikowane': 'Zweryfikowane', 'zaladowane': u'Załadowane', 'dostarczone': 'Dostarczone'}


def _plik(nazwa):
    with open(os.path.join(JS, nazwa), encoding='utf-8') as f:
        return f.read()


def test_stala_spakowane_lub_dalej_w_liscie_produktow():
    js = _plik('products-module.js')
    stala = re.search(r"const STATUSY_PO_SPAKOWANIU = \[([^\]]*)\]", js)
    assert stala, 'brak stałej STATUSY_PO_SPAKOWANIU'
    assert re.findall(r"'(\w+)'", stala.group(1)) == list(sposoby.STATUSY_PO_SPAKOWANIU)
    # Pytania „czy skończone” idą przez stałą, nie przez porównanie z 'spakowane'.
    assert not re.search(r"(===|!==)\s*'spakowane'", js)


def test_etykiety_nowych_statusow():
    for nazwa in ('products-module.js', 'archive-module.js'):
        js = _plik(nazwa)
        for status, etykieta in NOWE.items():
            assert "'%s': '%s'" % (status, etykieta) in js, (nazwa, status)


def test_klasy_css_nowych_statusow_jak_zakonczone():
    js = _plik('products-module.js')
    for status in NOWE:
        # getStatusCSSClass domyślnie daje 'paused' — nowe statusy muszą mieć wpis jawnie.
        assert re.search(r"'%s':\s*'completed'" % status, js), status
        assert re.search(r"'%s':\s*'status-completed'" % status, js), status
        assert re.search(r"'%s':\s*'badge-completed'" % status, js), status
    arch = _plik('archive-module.js')
    for status in NOWE:
        assert re.search(r"'%s':\s*'status-completed'" % status, arch), status
        assert re.search(r"'%s':\s*'badge-completed'" % status, arch), status
```

Dopisz do `tests/test_produkty_formularz_statusu.py`:

```python
def test_formularz_nie_oferuje_statusow_logistyki():
    """Spec 8.6 (krok 4.3 logistyki): zweryfikowane/zaladowane/dostarczone nadaje tylko logistyka."""
    from modules.production.logistics import sposoby
    assert not set(_wartosci_selecta()) & set(sposoby.STATUSY_LOGISTYCZNE)
```

i do `tests/test_produkty_js_klasy_statusow.py`:

```python
def test_dropdown_masowej_zmiany_bez_statusow_logistyki():
    from modules.production.logistics import sposoby
    wartosci = set(re.findall(r"value: '(\w+)'", _lista_dropdownu()))
    assert not wartosci & set(sposoby.STATUSY_LOGISTYCZNE)
```

- [ ] **Step 2: Uruchom — mają paść**

Run: `PYTEST tests/test_weryfikacja_front_produkcji.py`
Expected: FAIL (brak stałej i etykiet).

- [ ] **Step 3: `products-module.js`**

Na górze modułu (obok `STATUS_TRANSLATIONS`) dopisz:

```javascript
// Statusy „spakowane lub dalej” (logistyka etap 4) — kopia sposoby.STATUSY_PO_SPAKOWANIU w Pythonie.
const STATUSY_PO_SPAKOWANIU = ['spakowane', 'zweryfikowane', 'zaladowane', 'dostarczone'];
```

| Linia | Zmiana |
|---|---|
| :43 `STATUS_TRANSLATIONS` | `'zweryfikowane': 'Zweryfikowane', 'zaladowane': 'Załadowane', 'dostarczone': 'Dostarczone'` |
| :69 `STATUS_CONFIG` | `'zweryfikowane': {icon: 'fa-clipboard-check', color: 'text-success', badgeClass: 'badge-success'}`, `'zaladowane': {icon: 'fa-truck-loading', …}`, `'dostarczone': {icon: 'fa-flag-checkered', …}` (pozostałe pola jak we wpisie `spakowane`) |
| :1415 | `completedCount … === 'spakowane'` → `STATUSY_PO_SPAKOWANIU.includes(p.current_status)` |
| :1778 `getStationClassFromStatus`, :3540 `getStatusClass` | trzy nowe → `'status-completed'` |
| :1798 `getStatusBadgeClass` | trzy nowe → `'badge-completed'` |
| :2138 `getStatusCSSClass` | trzy nowe → `'completed'` (domyślne `'paused'` pokazałoby je jak wstrzymane) |
| :2780 dropdown masowej zmiany | **bez zmian** (nowych statusów nie dopisujemy) |
| :3409 | `status === 'spakowane' \|\| status === 'anulowane'` → `STATUSY_PO_SPAKOWANIU.includes(status) \|\| status === 'anulowane'` |
| :4119 | `if (currentStatus === 'spakowane')` → `if (STATUSY_PO_SPAKOWANIU.includes(currentStatus))` |
| :4179 | `currentStatus === 'spakowane'` → `STATUSY_PO_SPAKOWANIU.includes(currentStatus)` |
| :4680 `getStatusConfig` | trzy wpisy z ikonami jak w :69 i `cssClass: 'completed'` |

- [ ] **Step 4: `archive-module.js`**

| Linia | Zmiana |
|---|---|
| :29 `STATUS_DISPLAY_NAMES` | trzy etykiety |
| :946 `getStationClassFromStatus` | trzy nowe → `'status-completed'` |
| :961 `getStatusBadgeClass` | trzy nowe → `'badge-completed'` |
| :242 stała etykieta „Spakowane” wiersza archiwum | bez zmian (pozostaje prawdą) |

Podbij wersję skryptów w szablonie, który je ładuje (parametr `?v=` przy `products-module.js` i `archive-module.js` — znajdź `grep -rn "products-module.js" modules/production/templates`), żeby przeglądarki nie trzymały starej wersji.

- [ ] **Step 5: Uruchom testy i pełny pakiet**

Run: `PYTEST tests/test_weryfikacja_front_produkcji.py tests/test_produkty_formularz_statusu.py tests/test_produkty_js_klasy_statusow.py tests/test_archiwum_js_statusy_krawedzi.py`, potem `PYTEST tests/`
Expected: PASS, 0 failed.

- [ ] **Step 6: Commit**

```bash
git add modules/production/static/js/modules/products-module.js modules/production/static/js/modules/archive-module.js \
  modules/production/templates tests/test_weryfikacja_front_produkcji.py tests/test_produkty_formularz_statusu.py \
  tests/test_produkty_js_klasy_statusow.py
git commit -m "feat(production): lista produktow i archiwum pokazuja statusy po spakowaniu" \
  -m "Etykiety, ikony i klasy dla zweryfikowane, zaladowane i dostarczone; pytania o zakonczenie ida przez liste statusow spakowane lub dalej; hurtowa zmiana statusu ich nie oferuje." \
  -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Stanowisko Weryfikacja, lista „Do weryfikacji” i szczegóły zamówienia

**Files:**
- Modify: `modules/production/models.py` (`ProductionDevice.VALID_STATION_CODES` :1128–1138)
- Modify: `modules/production/services/station_catalog.py` (`STATION_LABELS`)
- Modify: `modules/production/services/mobile_api_service.py` (`_STATION_CODES_WITH_TABLETS` :262–265)
- Modify: `modules/production/logistics/services/weryfikacja.py` (stałe, zakres listy, serializacja)
- Modify: `modules/production/logistics/services/paczki.py` (`serializuj_paczke`)
- Create: `modules/production/logistics/routers/weryfikacja_api.py`
- Modify: `app.py` (`register_blueprints_lazy`, obok trakowni :877–878)
- Modify: `tests/logistyka_fixtures.py` (blueprint + tabela `ProductionWorkerSession`)
- Modify: `tests/test_katalog_stanowisk_krawedzie.py:93`, `tests/test_device_telemetry.py` (zbiór kluczy telemetrii), `tests/test_paczki_podpowiedz.py:142-149`
- Test: `tests/test_weryfikacja_lista.py`

**Interfaces:**
- Consumes: Task 1 (kolumny, reguła), Task 2 (`delivery.wszystkie_w`).
- Produces (w `weryfikacja.py`): `STANOWISKO = 'verification'`, `DNI_LISTY = 7`, `KLUCZ_OD = 'logistyka_weryfikacja_od'`, `POWODY_PROBLEMU` (dict kod → etykieta: `brak_elementu`, `uszkodzenie`, `etykieta`, `opakowanie`, `inne`), `NAZWY_ETAPOW` (dict status → napis dla `spakowane/zweryfikowane/zaladowane/dostarczone`), `data_wdrozenia() -> Optional[datetime]`, `poczatek_okna(teraz) -> datetime`, `warunek_zakresu(teraz)`, `warunek_do_weryfikacji(teraz)`, `warunek_problemu()`, `warunek_bez_paczek(teraz)`, `warunek_listy(teraz)` (wyrażenia SQL na `ProductionOrder`), `liczba_do_weryfikacji(teraz) -> int`, `liczba_problemow() -> int`, `etap(aktywne) -> (status, napis)`, `nazwa_etapu(produkt) -> str`, `serializuj_problem(order) -> Optional[dict]`, `serializuj_zamowienie(order, paczki_zamowienia, trasa=None, z_pozycjami=False) -> dict`, `lista(teraz) -> (zamowienia, {order_id: [paczki]}, {order_id: Route})`, `podpis_listy(zamowienia, pakunki, teraz) -> tuple` (części ETagu). W `weryfikacja_api.py`: `weryfikacja_mobile_bp`, dekorator `wymaga_weryfikacji`, `_pracownik() -> (worker_id, None) | (None, odpowiedź)`, `_blad(e)`, `_brak_zamowienia(numer)`, `KSZTALT_LISTY = 1`. `paczki.serializuj_paczke` dostaje `verified`, `verified_at`, `verified_method`.

- [ ] **Step 1: Testy, które padną**

Create `tests/test_weryfikacja_lista.py`:

```python
# -*- coding: utf-8 -*-
"""Stanowisko Weryfikacja: rejestracja, lista „Do weryfikacji” z ETag i szczegóły zamówienia
(logistyka etap 4, krok 4.3, spec 8.1–8.2, decyzja Konrada 30.09 o zakresie listy)."""
import itertools
from datetime import date, timedelta

import pytest

from extensions import db
from modules.production.logistics import sposoby as s
from modules.production.logistics.models import Route, RouteStop
from modules.production.logistics.services import weryfikacja
from modules.production.models import ProductionConfig, ProductionDevice, ProductionPackage, get_local_now
from modules.production.services.mobile_api_service import generate_token
from tests.logistyka_fixtures import app, client, zamowienie  # noqa: F401

URL = '/api/mobile/verification/orders'
_licznik = itertools.count(1)
_numery = itertools.count(2100)


def _urzadzenie(stanowisko='verification'):
    device = ProductionDevice(device_id='TEL-%s-%d' % (stanowisko, next(_licznik)),
                              device_name='Telefon', station_code=stanowisko)
    db.session.add(device)
    db.session.commit()
    return device


def _naglowki(device, **inne):
    naglowki = {'Authorization': 'Bearer ' + generate_token(device)}
    naglowki.update(inne)
    return naglowki


def _zam(sposob=s.KURIER, statusy=('spakowane',), spakowano=None, zamkniete=True, **kolumny):
    teraz = get_local_now()
    order = zamowienie(sposob=sposob, statusy=statusy, numer_wewnetrzny=str(next(_numery)),
                       logistics_closed_at=teraz if zamkniete else None, **kolumny)
    for p in order.products:
        if p.current_status != 'anulowane':
            p.packaging_completed_at = spakowano or teraz
    db.session.commit()
    return order


def _trasa(order, dzien, nazwa=u'Rzeszów', status='zatwierdzona'):
    """Trasa z jednym przystankiem = `order` (wzór: tests/test_paczki_panel.py)."""
    trasa = Route(name=nazwa, date_from=dzien, date_to=dzien, status=status)
    db.session.add(trasa)
    db.session.flush()
    db.session.add(RouteStop(route_id=trasa.id, order_id=order.id, position=1))
    db.session.commit()
    return trasa


def _wdrozenie(chwila):
    db.session.add(ProductionConfig(config_key=weryfikacja.KLUCZ_OD, config_type='string',
                                    config_value=chwila.strftime('%Y-%m-%d %H:%M:%S')))
    db.session.commit()


def _numery_listy(client, device):
    r = client.get(URL, headers=_naglowki(device))
    assert r.status_code == 200, r.get_json()
    return [o['internal_order_number'] for o in r.get_json()['orders']]


def test_rejestracja_telefonu_na_weryfikacji(app, client):
    r = client.post('/api/mobile/register', json={'device_id': 'TEL-W-1', 'station_code': 'verification'})
    assert r.status_code == 200 and r.get_json()['station_code'] == 'verification'


def test_inne_stanowisko_nie_widzi_listy(app, client):
    r = client.get(URL, headers=_naglowki(_urzadzenie('packaging')))
    assert r.status_code == 403 and r.get_json()['error'] == 'station_not_allowed'


def test_zakres_listy(app, client):
    teraz = get_local_now()
    _wdrozenie(teraz - timedelta(days=1))
    swieze = _zam()                                                     # kurier, zamknięty, dziś
    stare = _zam(spakowano=teraz - timedelta(days=10))                  # poza oknem 7 dni
    przed_wdrozeniem = _zam(spakowano=teraz - timedelta(days=2))        # w oknie, ale przed wdrożeniem
    otwarte = _zam(sposob=s.TRANSPORT, spakowano=teraz - timedelta(days=20), zamkniete=False)
    problem = _zam(statusy=('dostarczone',), spakowano=teraz - timedelta(days=30),
                   problem_reason='uszkodzenie', problem_at=teraz)
    zweryfikowane = _zam(statusy=('zweryfikowane',), verified_at=teraz)
    w_pakowaniu = _zam(statusy=('spakowane', 'czeka_na_pakowanie'))
    anulowane = _zam(statusy=('anulowane',))

    numery = set(_numery_listy(client, _urzadzenie()))

    assert {swieze.internal_order_number, otwarte.internal_order_number, problem.internal_order_number,
            zweryfikowane.internal_order_number} == numery
    for poza in (stare, przed_wdrozeniem, w_pakowaniu, anulowane):
        assert poza.internal_order_number not in numery
    assert weryfikacja.liczba_do_weryfikacji(teraz) == 2                 # świeże + otwarte (tylko 'spakowane')
    assert weryfikacja.liczba_problemow() == 1


def test_bez_daty_wdrozenia_samo_okno_dni(app, client):
    teraz = get_local_now()
    trzy_dni = _zam(spakowano=teraz - timedelta(days=3))
    assert _numery_listy(client, _urzadzenie()) == [trzy_dni.internal_order_number]
    assert weryfikacja.poczatek_okna(teraz) == teraz - timedelta(days=weryfikacja.DNI_LISTY)


def test_kolejnosc_trasy_wg_daty_potem_spakowanie(app, client):
    teraz = get_local_now()
    pozniej_spakowane = _zam(spakowano=teraz - timedelta(hours=1))
    wczesniej_spakowane = _zam(spakowano=teraz - timedelta(hours=5))
    na_trasie_pozniej = _zam(sposob=s.TRANSPORT, zamkniete=False)
    na_trasie_wczesniej = _zam(sposob=s.TRANSPORT, zamkniete=False)
    _trasa(na_trasie_pozniej, date(2026, 10, 9))
    _trasa(na_trasie_wczesniej, date(2026, 10, 2))
    assert _numery_listy(client, _urzadzenie()) == [
        na_trasie_wczesniej.internal_order_number, na_trasie_pozniej.internal_order_number,
        wczesniej_spakowane.internal_order_number, pozniej_spakowane.internal_order_number]


def test_zamowienie_na_liscie(app, client):
    teraz = get_local_now()
    order = _zam(sposob=s.TRANSPORT, zamkniete=False, spakowano=teraz, packages_declared_at=teraz,
                 problem_reason='etykieta', problem_note=u'nieczytelna', problem_at=teraz,
                 problem_by_worker_id=4)
    _trasa(order, date(2026, 10, 2), nazwa=u'Kraków + Tarnów')
    p1 = ProductionPackage(order_id=order.id, seq=1, kind='paczka', declared_at=teraz,
                           verified_at=teraz, verified_method='skan', verified_by_worker_id=4)
    p2 = ProductionPackage(order_id=order.id, seq=2, kind='paczka', declared_at=teraz)
    db.session.add_all([p1, p2])
    db.session.commit()

    wiersz = client.get(URL, headers=_naglowki(_urzadzenie())).get_json()['orders'][0]

    assert (wiersz['internal_order_number'], wiersz['stage'], wiersz['stage_label']) == \
        (order.internal_order_number, 'spakowane', u'Spakowane — czeka na weryfikację')
    assert (wiersz['packages_total'], wiersz['packages_verified'], wiersz['no_packages']) == (2, 1, False)
    assert [(p['code'], p['verified'], p['verified_method']) for p in wiersz['packages']] == \
        [(p1.kod, True, 'skan'), (p2.kod, False, None)]
    assert wiersz['transport']['mode'] == 'wlasny' and wiersz['transport']['trip_name'] == u'Kraków + Tarnów'
    assert wiersz['problem'] == {'reason': 'etykieta', 'reason_label': 'Etykieta', 'note': u'nieczytelna',
                                 'at': teraz.isoformat(), 'by_worker_id': 4}
    assert wiersz['packed_at'] == teraz.isoformat() and wiersz['verified_at'] is None


def test_bez_paczek_to_plakietka(app, client):
    order = _zam()
    wiersz = client.get(URL, headers=_naglowki(_urzadzenie())).get_json()['orders'][0]
    assert wiersz['internal_order_number'] == order.internal_order_number
    assert (wiersz['no_packages'], wiersz['packages']) == (True, [])


def test_etag_i_304(app, client):
    order = _zam()
    device = _urzadzenie()
    pierwsza = client.get(URL, headers=_naglowki(device))
    etag = pierwsza.headers['ETag']
    assert client.get(URL, headers=_naglowki(device, **{'If-None-Match': etag})).status_code == 304
    order.products[0].updated_at = get_local_now() + timedelta(seconds=5)
    db.session.commit()
    druga = client.get(URL, headers=_naglowki(device, **{'If-None-Match': etag}))
    assert druga.status_code == 200 and druga.headers['ETag'] != etag


def test_szczegoly_z_pozycjami(app, client):
    order = _zam(statusy=('spakowane', 'anulowane'))
    r = client.get(URL + '/' + order.internal_order_number, headers=_naglowki(_urzadzenie()))
    assert r.status_code == 200 and 'no-store' in r.headers['Cache-Control']
    pozycje = r.get_json()['order']['items']
    assert [(p['status'], p['status_label']) for p in pozycje] == \
        [('spakowane', u'Spakowane — czeka na weryfikację'), ('anulowane', 'Anulowane')]
    brak = client.get(URL + '/999999', headers=_naglowki(_urzadzenie()))
    assert brak.status_code == 404 and brak.get_json()['error'] == 'order_not_found'
```

Dopasuj istniejące testy:
- `tests/test_katalog_stanowisk_krawedzie.py:93`: `assert set(STATION_LABELS) == set(STATION_ORDER) | {'sawmill', 'verification'}` + komentarz „Weryfikacja (logistyka etap 4) — telefon biura, poza pipeline'em produktów”.
- `tests/test_device_telemetry.py` (asercja `set(result.keys()) == set(STATION_ORDER) | {'sawmill'}`): `| {'sawmill', 'verification'}`.
- `tests/test_paczki_podpowiedz.py:146-149` — oczekiwany słownik dostaje `'verified': False, 'verified_at': None, 'verified_method': None`.

- [ ] **Step 2: Uruchom — mają paść**

Run: `PYTEST tests/test_weryfikacja_lista.py`
Expected: FAIL (`ValueError: Nieprawidłowy station_code: verification` przy tworzeniu urządzenia, 404 na `/api/mobile/verification/orders`).

- [ ] **Step 3: Stanowisko w katalogu, rejestracji i telemetrii**

- `models.py`, `VALID_STATION_CODES` — po `'sawmill',` dopisz: `'verification',  # Weryfikacja paczek (logistyka etap 4) — telefon biura, poza pipeline'em produktów`.
- `station_catalog.py`, `STATION_LABELS` — po `'sawmill': 'Trakownia',` dopisz:

```python
    # Logistyka etap 4 — telefon biura sprawdzający paczki. Jak trakownia: poza STATION_ORDER
    # (nie ma kolejki statusów), ale z nazwą, bo pracownik ma tu sesję.
    'verification': 'Weryfikacja',
```

- `mobile_api_service.py`, `_STATION_CODES_WITH_TABLETS` — dopisz `'verification'` (telefon Weryfikacji ma telemetrię jak tablety).

- [ ] **Step 4: Stan weryfikacji w paczce**

`paczki.serializuj_paczke` — po `'label_printed_at': …` dopisz:

```python
        # Krok 4.3: stan weryfikacji (telefon Weryfikacji, spec 8.2).
        'verified': p.verified_at is not None,
        'verified_at': p.verified_at.isoformat() if p.verified_at else None,
        'verified_method': p.verified_method,
```

i popraw docstring („kontrakt kroków 4.2–4.3”).

- [ ] **Step 5: Zakres listy i serializacja w `weryfikacja.py`**

Uzupełnij importy na górze modułu:

```python
from datetime import date, datetime, timedelta

from sqlalchemy import and_, func, or_
from sqlalchemy.orm import selectinload

from extensions import db
from modules.logging import get_structured_logger
from modules.production.logistics import sposoby
from modules.production.logistics.models import STATUSY_TRASY_AKTYWNE
from modules.production.logistics.services import delivery, paczki, routes
from modules.production.models import ProductionConfig, ProductionOrder, ProductionProduct
from modules.production.services.station_catalog import STATION_LABELS, STATION_PENDING_STATUS

logger = get_structured_logger('production.logistics.weryfikacja')
```

i dopisz pod `_COFANE_DO_SPAKOWANYCH`:

```python
STANOWISKO = 'verification'
# Zamówienia zamknięte w Logistyce (kurier) są na liście przez tyle dni od spakowania (decyzja 30.09).
DNI_LISTY = 7
# Chwila wdrożenia kroku 4.3 — wiersz prod_config z migracji 2026-09-30-logistyka-weryfikacja.sql.
KLUCZ_OD = 'logistyka_weryfikacja_od'
POWODY_PROBLEMU = {
    'brak_elementu': u'Brak elementu',
    'uszkodzenie': u'Uszkodzenie',
    'etykieta': u'Etykieta',
    'opakowanie': u'Opakowanie',
    'inne': u'Inne',
}
# Napis etapu zamówienia po spakowaniu (telefon i panel Logistyki, spec 4.1 i 11).
NAZWY_ETAPOW = {
    'spakowane': u'Spakowane — czeka na weryfikację',
    'zweryfikowane': u'Zweryfikowane',
    'zaladowane': u'Załadowane',
    'dostarczone': u'Dostarczone',
}
# Etap przed spakowaniem = stanowisko, na którym pozycja czeka (jak kolumna listy Logistyki).
_NAZWA_STANOWISKA = {status: STATION_LABELS[kod] for kod, status in STATION_PENDING_STATUS.items()}


def data_wdrozenia():
    """Chwila wdrożenia kroku 4.3 (prod_config) albo None — wtedy zakres listy to samo okno dni."""
    wiersz = ProductionConfig.query.filter_by(config_key=KLUCZ_OD).first()
    tekst = (wiersz.config_value or '').strip() if wiersz is not None else ''
    if not tekst:
        return None
    try:
        return datetime.strptime(tekst[:19], '%Y-%m-%d %H:%M:%S')
    except ValueError:
        logger.warning(u"Nieczytelna data w prod_config '{}': {!r} - lista Do weryfikacji liczy "
                       u"samo okno {} dni".format(KLUCZ_OD, tekst, DNI_LISTY))
        return None


def poczatek_okna(teraz):
    """Od kiedy zamówienia zamknięte w Logistyce trafiają na listę: ostatnie DNI_LISTY dni, ale nie
    wcześniej niż wdrożenie kroku 4.3 (inaczej w dniu wdrożenia lista miałaby ~110 starych zamówień)."""
    okno = teraz - timedelta(days=DNI_LISTY)
    wdrozenie = data_wdrozenia()
    return max(okno, wdrozenie) if wdrozenie is not None else okno


def _wszystkie_sql(statusy):
    """SQL: zamówienie ma pozycję w `statusy`, a żadna niezanulowana nie jest spoza `statusy`."""
    statusy = tuple(statusy)
    return and_(
        ProductionOrder.products.any(ProductionProduct.current_status.in_(statusy)),
        ~ProductionOrder.products.any(ProductionProduct.current_status.notin_(statusy + ('anulowane',))))


def warunek_zakresu(teraz):
    """Zamówienie otwarte w Logistyce albo z pozycją spakowaną od poczatek_okna(teraz)."""
    return or_(ProductionOrder.logistics_closed_at.is_(None),
               ProductionOrder.products.any(and_(
                   ProductionProduct.current_status != 'anulowane',
                   ProductionProduct.packaging_completed_at >= poczatek_okna(teraz))))


def warunek_do_weryfikacji(teraz):
    """„Do weryfikacji” (spec 8.2): wszystkie niezanulowane pozycje 'spakowane', w zakresie listy.
    Licznik dashboardu i filtr panelu Logistyki."""
    return and_(_wszystkie_sql(('spakowane',)), warunek_zakresu(teraz))


def warunek_problemu():
    return ProductionOrder.problem_at.isnot(None)


def warunek_bez_paczek(teraz):
    """Do weryfikacji, ale bez aktualnej deklaracji paczek (stara appka, zmiana admina)."""
    return and_(warunek_do_weryfikacji(teraz), ProductionOrder.packages_declared_at.is_(None))


def warunek_listy(teraz):
    """Lista telefonu: do weryfikacji i zweryfikowane (w tym samym zakresie — skaner rozpoznaje paczki
    lokalnie, więc zweryfikowane muszą zostać w telefonie) plus zawsze zamówienia z problemem."""
    return or_(warunek_problemu(),
               and_(_wszystkie_sql(('spakowane', 'zweryfikowane')), warunek_zakresu(teraz)))


def liczba_do_weryfikacji(teraz):
    return db.session.query(func.count(ProductionOrder.id)).filter(
        warunek_do_weryfikacji(teraz)).scalar() or 0


def liczba_problemow():
    return db.session.query(func.count(ProductionOrder.id)).filter(warunek_problemu()).scalar() or 0


def nazwa_etapu(produkt):
    return (NAZWY_ETAPOW.get(produkt.current_status) or _NAZWA_STANOWISKA.get(produkt.current_status)
            or produkt.status_display_name)


def etap(aktywne):
    """(status, napis) najbardziej zaległej aktywnej pozycji; bez aktywnych — anulowane."""
    if not aktywne:
        return 'anulowane', u'Anulowane'
    kolejnosc = sposoby.STATUSY_PO_SPAKOWANIU
    najwczesniejsza = min(aktywne, key=lambda p: kolejnosc.index(p.current_status)
                          if p.current_status in kolejnosc else -1)
    return najwczesniejsza.current_status, nazwa_etapu(najwczesniejsza)


def _iso(chwila):
    return chwila.isoformat() if chwila else None


def _spakowano(order):
    daty = [p.packaging_completed_at for p in delivery.aktywne_produkty(order) if p.packaging_completed_at]
    return max(daty) if daty else None


def _trasa_aktywna(order, trasa):
    if trasa is None or trasa.status not in STATUSY_TRASY_AKTYWNE:
        return None
    return trasa if sposoby.normalizuj(order.override_delivery_method) == sposoby.TRANSPORT else None


def serializuj_problem(order):
    if order.problem_at is None:
        return None
    return {'reason': order.problem_reason,
            'reason_label': POWODY_PROBLEMU.get(order.problem_reason, order.problem_reason),
            'note': order.problem_note, 'at': _iso(order.problem_at),
            'by_worker_id': order.problem_by_worker_id}


def serializuj_zamowienie(order, paczki_zamowienia, trasa=None, z_pozycjami=False):
    """Zamówienie w API telefonu (kontrakt w planie kroku 4.3). `trasa` — dowolnego statusu (z
    routes.trasy_zamowien); na telefon trafia tylko aktywna trasa transportu własnego."""
    aktywne = delivery.aktywne_produkty(order)
    status, napis = etap(aktywne)
    dane = {
        'order_id': order.id,
        'internal_order_number': order.internal_order_number,
        'baselinker_order_id': order.baselinker_order_id,
        'client_name': order.client_name,
        'delivery_city': order.delivery_city,
        'stage': status,
        'stage_label': napis,
        'packed_at': _iso(_spakowano(order)),
        'verified_at': _iso(order.verified_at),
        'transport': sposoby.transport_payload(order, _trasa_aktywna(order, trasa)),
        'packages': [paczki.serializuj_paczke(p) for p in paczki_zamowienia],
        'packages_total': len(paczki_zamowienia),
        'packages_verified': sum(1 for p in paczki_zamowienia if p.verified_at is not None),
        'no_packages': not paczki_zamowienia and delivery.wszystkie_w(order, ('spakowane', 'zweryfikowane')),
        'problem': serializuj_problem(order),
    }
    if z_pozycjami:
        dane['items'] = [{
            'id': p.id, 'short_id': p.short_product_id, 'product_name': p.original_product_name,
            'quantity': p.quantity, 'status': p.current_status, 'status_label': nazwa_etapu(p),
            'volume_m3': float(p.volume_m3) if p.volume_m3 is not None else None,
        } for p in sorted(order.products, key=lambda x: (x.product_sequence_in_order or 0, x.id or 0))]
    return dane


def lista(teraz):
    """
    Zamówienia listy telefonu w kolejności specu 8.2 (aktywna trasa transportu z najbliższą datą
    początku, potem spakowanie rosnąco, potem numer) + mapy paczek i tras — po jednym zapytaniu na
    mapę, bez zapytań na wiersz.
    """
    zamowienia = (ProductionOrder.query.options(selectinload(ProductionOrder.products))
                  .filter(warunek_listy(teraz)).all())
    ids = [o.id for o in zamowienia]
    pakunki = paczki.aktualne_paczki_zamowien(ids)
    trasy = routes.trasy_zamowien(ids)

    def klucz(order):
        aktywna = _trasa_aktywna(order, trasy.get(order.id))
        spakowano = _spakowano(order)
        return (aktywna is None, aktywna.date_from if aktywna is not None else date.max,
                spakowano or datetime.max, order.internal_order_number or '')

    zamowienia.sort(key=klucz)
    return zamowienia, pakunki, trasy


def podpis_listy(zamowienia, pakunki, teraz):
    """Części ETagu listy: dzień (okno dni przesuwa się bez zmian danych), liczba zamówień, najnowszy
    updated_at i liczba pozycji (akcje Weryfikacji, deklaracje i zmiany tras podbijają pozycje), stan
    paczek (weryfikacja, wydruki)."""
    pozycje = [p for o in zamowienia for p in o.products]
    znaczniki = [p.updated_at for p in pozycje if p.updated_at]
    wszystkie_paczki = [p for lista_paczek in pakunki.values() for p in lista_paczek]
    return (teraz.date().isoformat(), len(zamowienia),
            int(max(znaczniki).timestamp()) if znaczniki else 0, len(pozycje), len(wszystkie_paczki),
            sum(1 for p in wszystkie_paczki if p.verified_at is not None),
            sum(p.label_print_count or 0 for p in wszystkie_paczki))
```

- [ ] **Step 6: Blueprint telefonu**

Create `modules/production/logistics/routers/weryfikacja_api.py`:

```python
# -*- coding: utf-8 -*-
"""
API telefonu Weryfikacji — /api/mobile/verification/* (logistyka etap 4, krok 4.3, spec 8).

Reużywa autoryzację i idempotencję API mobilnego produkcji (require_device_token, with_idempotency).
Handlery zapisu NIE commitują — robi to dekorator idempotencji. Kolejność blokad każdego zapisu:
pracownicy (touch_sessions w _pracownik) → paczki.zablokuj_deklaracje() → zamówienie po PK →
paczki → pozycje. Deklaracja paczek i ponowny druk z telefonu idą istniejącymi endpointami
/api/mobile/orders/<nr>/packages (stanowisko 'verification' jest w paczki.STANOWISKA_PACZEK).
"""
from functools import wraps

from flask import Blueprint, g, jsonify, request

from modules.logging import get_structured_logger
from modules.production.logistics.services import paczki, routes, weryfikacja
from modules.production.models import get_local_now
from modules.production.routers.mobile_api import BLEDY_DO_PONOWIENIA, _zamowienie_po_numerze  # noqa: F401
from modules.production.services import worker_service
from modules.production.services.mobile_api_service import require_device_token, with_idempotency  # noqa: F401
from modules.production.services.station_catalog import resolve_station_code
from modules.production.services.worker_service import WorkerError
from modules.production.utils.cache import cached_json, if_none_match, make_weak_etag, no_store_json, not_modified

logger = get_structured_logger('production.logistics.weryfikacja_api')

weryfikacja_mobile_bp = Blueprint('weryfikacja_mobile', __name__)

# Wersja KSZTAŁTU odpowiedzi listy — część ETagu (jak KSZTALT_ODPOWIEDZI_KOLEJKI w mobile_api).
# PODBIJ przy każdej zmianie zestawu pól w weryfikacja.serializuj_zamowienie().
#   1 — 2026-09-30: pierwsza wersja (krok 4.3)
KSZTALT_LISTY = 1


def wymaga_weryfikacji(f):
    """Urządzenie zarejestrowane na stanowisku Weryfikacja (kod z JWT, jak druk etykiet paczek)."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        if resolve_station_code((g.device.station_code or '').strip()) != weryfikacja.STANOWISKO:
            return jsonify({'error': 'station_not_allowed',
                            'message': u'To urządzenie nie jest zarejestrowane na stanowisku Weryfikacja.'}), 403
        return f(*args, **kwargs)
    return wrapper


def _pracownik():
    """
    (worker_id, None) albo (None, odpowiedź). Zapis Weryfikacji zawsze ma pracownika (spec 8.1) —
    niezależnie od WORKER_SELECTION_REQUIRED: brak nagłówka X-Worker-Ids → 400 worker_required
    (w BLEDY_DO_PONOWIENIA — akcja zostaje w kolejce offline, appka wraca na „Kto pracuje?”).
    """
    try:
        ids = worker_service.resolve_worker_ids(request.headers.get('X-Worker-Ids'), required=False)
    except WorkerError as e:
        payload, status = e.as_response()
        return None, (jsonify(payload), status)
    if not ids:
        return None, (jsonify({'error': 'worker_required',
                               'message': u'Wybierz pracownika („Kto pracuje?”) — weryfikacja zapisuje, '
                                          u'kto sprawdził paczki.'}), 400)
    g.worker_ids = ids   # audyt zmian statusu pozycji (product_events.current_actor)
    worker_service.touch_sessions(ids, device_id=g.device.device_id)
    return ids[0], None


def _brak_zamowienia(numer):
    return jsonify({'error': 'order_not_found', 'message': u'Nie ma zamówienia {}.'.format(numer)}), 404


def _blad(e):
    return jsonify({'error': e.kod, 'message': e.komunikat}), e.status


@weryfikacja_mobile_bp.route('/orders', methods=['GET'])
@require_device_token
@wymaga_weryfikacji
def verification_orders():
    """GET /api/mobile/verification/orders — lista „Do weryfikacji” (spec 8.2) z ETagiem."""
    teraz = get_local_now()
    zamowienia, pakunki, trasy = weryfikacja.lista(teraz)
    etag = make_weak_etag('weryfikacja', KSZTALT_LISTY, *weryfikacja.podpis_listy(zamowienia, pakunki, teraz))
    if if_none_match(etag):
        return not_modified(etag)
    return cached_json({
        'orders': [weryfikacja.serializuj_zamowienie(o, pakunki.get(o.id, []), trasy.get(o.id))
                   for o in zamowienia],
        'count': len(zamowienia),
    }, etag)


@weryfikacja_mobile_bp.route('/orders/<numer>', methods=['GET'])
@require_device_token
@wymaga_weryfikacji
def verification_order_details(numer):
    """GET /api/mobile/verification/orders/<nr> — zamówienie z pozycjami, bez cache."""
    order = _zamowienie_po_numerze(numer)
    if order is None:
        return _brak_zamowienia(numer)
    return no_store_json({'order': weryfikacja.serializuj_zamowienie(
        order, paczki.aktualne_paczki(order.id), routes.trasy_zamowien([order.id]).get(order.id),
        z_pozycjami=True)})
```

(`BLEDY_DO_PONOWIENIA` i `with_idempotency` użyją endpointy zapisu w Task 6–7 — importy od razu, z `noqa`.)

`app.py` — w `register_blueprints_lazy` zaraz po rejestracji trakowni (`sawmill_mobile_bp`):

```python
        # Logistyka etap 4, krok 4.3: telefon Weryfikacji.
        from modules.production.logistics.routers.weryfikacja_api import weryfikacja_mobile_bp
        app.register_blueprint(weryfikacja_mobile_bp, url_prefix='/api/mobile/verification')
```

`tests/logistyka_fixtures.py`:
- do importu modeli dopisz `ProductionWorkerSession`, a do `TABLES` — `ProductionWorkerSession` (touch_sessions czyta sesje pracowników);
- w fiksturze `app` po `app.register_blueprint(mobile_api_bp, url_prefix='/api/mobile')`:

```python
    from modules.production.logistics.routers.weryfikacja_api import weryfikacja_mobile_bp
    app.register_blueprint(weryfikacja_mobile_bp, url_prefix='/api/mobile/verification')
```

- [ ] **Step 7: Uruchom testy zadania i sąsiednie**

Run: `PYTEST tests/test_weryfikacja_lista.py tests/test_katalog_stanowisk_krawedzie.py tests/test_device_telemetry.py tests/test_paczki_podpowiedz.py tests/test_paczki_deklaracja.py tests/test_paczki_ponowny_druk.py tests/test_logistyka_mobile.py`
Expected: PASS.

- [ ] **Step 8: Pełny pakiet i commit**

Run: `PYTEST tests/`
Expected: 0 failed.

```bash
git add modules/production/models.py modules/production/services/station_catalog.py \
  modules/production/services/mobile_api_service.py modules/production/logistics/services/weryfikacja.py \
  modules/production/logistics/services/paczki.py modules/production/logistics/routers/weryfikacja_api.py \
  app.py tests/logistyka_fixtures.py tests/test_weryfikacja_lista.py tests/test_katalog_stanowisk_krawedzie.py \
  tests/test_device_telemetry.py tests/test_paczki_podpowiedz.py
git commit -m "feat(production): stanowisko Weryfikacja i lista zamowien do weryfikacji dla telefonu" \
  -m "Rejestracja telefonu na stanowisku verification, GET /api/mobile/verification/orders z ETagiem (zakres: otwarte w Logistyce albo spakowane w ostatnich 7 dniach od wdrozenia, plus problemy) i szczegoly zamowienia z pozycjami." \
  -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Akcje weryfikacji — paczka, „Zweryfikuj wszystkie”, „Cofnij weryfikację”

**Files:**
- Modify: `modules/production/logistics/services/weryfikacja.py`
- Modify: `modules/production/logistics/routers/weryfikacja_api.py`
- Test: `tests/test_weryfikacja_akcje.py`

**Interfaces:**
- Consumes: Task 5 (`weryfikacja_mobile_bp`, `wymaga_weryfikacji`, `_pracownik`, `_blad`, `_brak_zamowienia`, `serializuj_zamowienie`, `POWODY_PROBLEMU`), `paczki.zablokuj_deklaracje()`, `paczki.aktualne_paczki(order_id, do_zapisu)`, `mobile_api._zamowienie_po_numerze(numer, do_zapisu)`.
- Produces (w `weryfikacja.py`): `class WeryfikacjaBlad(Exception)` (`kod`, `komunikat`, `status` domyślnie 409), `METODY = ('skan', 'reczne')`, `sprawdz_stan(order) -> aktywne pozycje` (odmowy `order_status`/`order_not_packed`), `problem_otwarty(order) -> WeryfikacjaBlad`, `zweryfikuj_paczke(paczka, order, metoda, worker_id=None, device_id=None, teraz=None) -> (zmieniono, zamowienie_zweryfikowane)`, `zweryfikuj_wszystkie(order, worker_id=None, device_id=None, teraz=None) -> bool`, `cofnij_weryfikacje(order, worker_id=None, device_id=None, teraz=None, powod=u'Cofnij weryfikację') -> bool`, `cofnij_weryfikacje_zamowienia(order, aktywne, powod, worker_id, device_id, teraz)` (wspólne dla cofnięcia i problemu w Task 7). W routerze: `_zamowienie_do_zapisu(numer)`, `_odpowiedz(order, message, **dodatkowe)`.

- [ ] **Step 1: Testy, które padną**

Create `tests/test_weryfikacja_akcje.py`:

```python
# -*- coding: utf-8 -*-
"""Akcje telefonu Weryfikacji: weryfikacja paczki, „Zweryfikuj wszystkie”, „Cofnij weryfikację”
(logistyka etap 4, krok 4.3, spec 4.4, 4.5 i 8.3)."""
import itertools
from datetime import datetime

import pytest

from extensions import db
from modules.production.logistics import sposoby as s
from modules.production.logistics.models import LogisticsLog
from modules.production.models import ProcessedMobileOperation, ProductionDevice, ProductionOrder, ProductionPackage
from modules.production.services.mobile_api_service import generate_token
from tests.logistyka_fixtures import app, client, pracownik, zamowienie  # noqa: F401

BASE = '/api/mobile/verification'
T0 = datetime(2026, 10, 1, 8, 0)
_licznik = itertools.count(1)
_numery = itertools.count(2600)


@pytest.fixture(autouse=True)
def bez_statusow_base(monkeypatch):
    monkeypatch.setattr(
        'modules.production.services.baselinker_status_sync.schedule_after_station_complete',
        lambda *a, **k: None)


def _urzadzenie(stanowisko='verification'):
    device = ProductionDevice(device_id='TEL-%s-%d' % (stanowisko, next(_licznik)),
                              device_name='Telefon', station_code=stanowisko)
    db.session.add(device)
    db.session.commit()
    return device


def _naglowki(device, kto=None, op_id=None, **inne):
    naglowki = {'Authorization': 'Bearer ' + generate_token(device),
                'X-Operation-Id': op_id or 'op-wer-%d' % next(_licznik)}
    if kto is not None:
        naglowki['X-Worker-Ids'] = str(kto.id)
    naglowki.update(inne)
    return naglowki


def _z_paczkami(statusy=('spakowane', 'spakowane'), n=2, sposob=s.KURIER, **kolumny):
    order = zamowienie(sposob=sposob, statusy=statusy, numer_wewnetrzny=str(next(_numery)),
                       packages_declared_at=T0, **kolumny)
    lista = [ProductionPackage(order_id=order.id, seq=i, kind='paczka', declared_at=T0)
             for i in range(1, n + 1)]
    db.session.add_all(lista)
    db.session.commit()
    return order, lista


def _verify(client, paczka, device, kto, **body):
    return client.post('%s/packages/%d/verify' % (BASE, paczka.id), json=body or {'method': 'skan'},
                       headers=_naglowki(device, kto))


def test_ostatnia_paczka_weryfikuje_zamowienie(app, client):
    kto, device = pracownik(), _urzadzenie()
    order, (p1, p2) = _z_paczkami(logistics_closed_at=T0)

    pierwsza = _verify(client, p1, device, kto)
    assert pierwsza.status_code == 200, pierwsza.get_json()
    assert (pierwsza.get_json()['changed'], pierwsza.get_json()['order_verified']) == (True, False)
    assert pierwsza.get_json()['order']['packages_verified'] == 1
    assert [p.current_status for p in ProductionOrder.query.get(order.id).products] == ['spakowane', 'spakowane']

    druga = _verify(client, p2, device, kto).get_json()
    assert (druga['changed'], druga['order_verified']) == (True, True)
    o = ProductionOrder.query.get(order.id)
    assert [p.current_status for p in o.products] == ['zweryfikowane', 'zweryfikowane']
    assert o.verified_by_worker_id == kto.id and o.verified_at is not None
    assert o.logistics_closed_at == T0                        # kurier zostaje zamknięty
    assert [(p.verified_method, p.verified_by_worker_id) for p in ProductionPackage.query.order_by(ProductionPackage.seq)] \
        == [('skan', kto.id), ('skan', kto.id)]
    wpis = LogisticsLog.query.filter_by(order_id=order.id, action='weryfikacja').one()
    assert (wpis.new_value, wpis.note, wpis.worker_id, wpis.device_id) == (u'2 × paczka', 'skan', kto.id, device.id)
    assert druga['order']['stage'] == 'zweryfikowane'


def test_ponowny_skan_bez_zmian(app, client):
    kto, device = pracownik(), _urzadzenie()
    order, (p1,) = _z_paczkami(n=1)
    assert _verify(client, p1, device, kto).get_json()['order_verified'] is True
    ponowny = _verify(client, p1, device, kto)
    assert ponowny.status_code == 200
    assert (ponowny.get_json()['changed'], ponowny.get_json()['order_verified']) == (False, True)
    assert LogisticsLog.query.filter_by(order_id=order.id, action='weryfikacja').count() == 1


@pytest.mark.parametrize('ustaw, kod', [
    (lambda o, p: setattr(p, 'voided_at', T0), 'package_void'),
    (lambda o, p: (setattr(o, 'problem_reason', 'uszkodzenie'), setattr(o, 'problem_at', T0)), 'problem_open'),
    (lambda o, p: setattr(o.products[1], 'current_status', 'czeka_na_pakowanie'), 'order_not_packed'),
    (lambda o, p: [setattr(x, 'current_status', 'dostarczone') for x in o.products], 'order_status'),
])
def test_odmowy_409(app, client, ustaw, kod):
    kto, device = pracownik(), _urzadzenie()
    order, (p1, _p2) = _z_paczkami()
    ustaw(order, p1)
    db.session.commit()
    r = _verify(client, p1, device, kto)
    assert (r.status_code, r.get_json()['error']) == (409, kod)
    assert r.get_json()['message']
    assert ProductionPackage.query.get(p1.id).verified_at is None
    assert ProcessedMobileOperation.query.count() == 0           # 409 niezapamiętane (BLEDY_DO_PONOWIENIA)


def test_bez_pracownika_400_i_bez_zmian(app, client):
    order, (p1, _p2) = _z_paczkami()
    r = client.post('%s/packages/%d/verify' % (BASE, p1.id), json={'method': 'skan'},
                    headers=_naglowki(_urzadzenie()))
    assert (r.status_code, r.get_json()['error']) == (400, 'worker_required')
    assert ProductionPackage.query.get(p1.id).verified_at is None


def test_inne_stanowisko_403_zla_metoda_422_brak_paczki_404(app, client):
    kto = pracownik()
    order, (p1, _p2) = _z_paczkami()
    assert _verify(client, p1, _urzadzenie('packaging'), kto).status_code == 403
    zla = _verify(client, p1, _urzadzenie(), kto, method='laser')
    assert (zla.status_code, zla.get_json()['error']) == (422, 'invalid_method')
    brak = client.post(BASE + '/packages/999999/verify', json={}, headers=_naglowki(_urzadzenie(), kto))
    assert (brak.status_code, brak.get_json()['error']) == (404, 'package_not_found')


def test_powtorka_operacji_nie_weryfikuje_drugi_raz(app, client):
    kto, device = pracownik(), _urzadzenie()
    order, (p1,) = _z_paczkami(n=1)
    naglowki = _naglowki(device, kto, op_id='op-wer-powtorka')
    url = '%s/packages/%d/verify' % (BASE, p1.id)
    pierwsza = client.post(url, json={'method': 'skan'}, headers=naglowki)
    druga = client.post(url, json={'method': 'skan'}, headers=naglowki)
    assert druga.get_json() == pierwsza.get_json()
    assert LogisticsLog.query.filter_by(order_id=order.id, action='weryfikacja').count() == 1


def test_zweryfikuj_wszystkie(app, client):
    kto, device = pracownik(), _urzadzenie()
    order, (p1, p2) = _z_paczkami()
    _verify(client, p1, device, kto)
    url = '%s/orders/%s/verify-all' % (BASE, order.internal_order_number)
    r = client.post(url, headers=_naglowki(device, kto))
    assert r.status_code == 200 and r.get_json()['order_verified'] is True and r.get_json()['changed'] is True
    assert [p.verified_method for p in ProductionPackage.query.order_by(ProductionPackage.seq)] == ['skan', 'reczne']
    assert LogisticsLog.query.filter_by(order_id=order.id, action='weryfikacja').one().note == u'ręcznie'
    ponownie = client.post(url, headers=_naglowki(device, kto))
    assert ponownie.status_code == 200 and ponownie.get_json()['changed'] is False


def test_zweryfikuj_wszystkie_bez_paczek_409(app, client):
    order = zamowienie(sposob=s.KURIER, statusy=('spakowane',), numer_wewnetrzny=str(next(_numery)))
    r = client.post('%s/orders/%s/verify-all' % (BASE, order.internal_order_number),
                    headers=_naglowki(_urzadzenie(), pracownik()))
    assert (r.status_code, r.get_json()['error']) == (409, 'no_packages')


def test_cofnij_weryfikacje(app, client):
    kto, device = pracownik(), _urzadzenie()
    order, (p1, p2) = _z_paczkami()
    client.post('%s/orders/%s/verify-all' % (BASE, order.internal_order_number), headers=_naglowki(device, kto))
    r = client.post('%s/orders/%s/unverify' % (BASE, order.internal_order_number), headers=_naglowki(device, kto))
    assert r.status_code == 200 and r.get_json()['changed'] is True
    o = ProductionOrder.query.get(order.id)
    assert [p.current_status for p in o.products] == ['spakowane', 'spakowane'] and o.verified_at is None
    assert all(p.verified_at is None and p.verified_method is None
               for p in ProductionPackage.query.filter_by(order_id=order.id))
    assert LogisticsLog.query.filter_by(order_id=order.id, action='weryfikacja_cofnieta').one().worker_id == kto.id
    drugi_raz = client.post('%s/orders/%s/unverify' % (BASE, order.internal_order_number),
                            headers=_naglowki(device, kto))
    assert (drugi_raz.status_code, drugi_raz.get_json()['error']) == (409, 'order_not_verified')


def test_telefon_deklaruje_paczki_zamowieniu_bez_paczek(app, client, monkeypatch):
    """Spec 7.2: „BEZ PACZEK” (stara appka, admin) — weryfikator deklaruje paczki tym samym PUT."""
    from modules.production.services import print_queue_service as pqs
    monkeypatch.setattr(pqs.realtime_service, 'publish_print_signal', lambda n: True)
    order = zamowienie(sposob=s.KURIER, statusy=('spakowane',), numer_wewnetrzny=str(next(_numery)))
    r = client.put('/api/mobile/orders/%s/packages' % order.internal_order_number,
                   json={'kind': 'paczka', 'count': 1}, headers=_naglowki(_urzadzenie(), pracownik()))
    assert r.status_code == 200, r.get_json()
    assert ProductionPackage.query.filter_by(order_id=order.id).one().declared_device_id is not None


def test_deklaracja_po_weryfikacji_z_telefonu_409(app, client):
    kto, device = pracownik(), _urzadzenie()
    order, (p1,) = _z_paczkami(n=1)
    _verify(client, p1, device, kto)
    r = client.put('/api/mobile/orders/%s/packages' % order.internal_order_number,
                   json={'kind': 'paczka', 'count': 2}, headers=_naglowki(device, kto))
    assert (r.status_code, r.get_json()['error']) == (409, 'order_verified')
```

- [ ] **Step 2: Uruchom — mają paść**

Run: `PYTEST tests/test_weryfikacja_akcje.py`
Expected: FAIL (404 — brak endpointów zapisu).

- [ ] **Step 3: Serwis**

Dopisz do `modules/production/logistics/services/weryfikacja.py` (import `get_local_now` z `modules.production.models`):

```python
METODY = ('skan', 'reczne')   # = ProductionPackage.SPOSOBY_POTWIERDZENIA
_OPIS_METODY = {'skan': u'skan', 'reczne': u'ręcznie'}


class WeryfikacjaBlad(Exception):
    """Odmowa z kodem dla appki (`error`) i komunikatem dla człowieka (`message`)."""

    def __init__(self, kod, komunikat, status=409):
        super().__init__(komunikat)
        self.kod = kod
        self.komunikat = komunikat
        self.status = status


def sprawdz_stan(order):
    """
    Zamówienie, na którym Weryfikacja może działać: każda niezanulowana pozycja 'spakowane' albo
    'zweryfikowane' (spec 8.3). Załadowane i dostarczone → 409 order_status (spec 4.5: cofnięcia
    Weryfikacji działają do załadunku). Zwraca aktywne pozycje.
    """
    numer = order.internal_order_number
    aktywne = delivery.aktywne_produkty(order)
    if not aktywne:
        raise WeryfikacjaBlad('order_status', u'Zamówienie {} jest anulowane.'.format(numer))
    if any(p.current_status not in sposoby.STATUSY_PO_SPAKOWANIU for p in aktywne):
        raise WeryfikacjaBlad('order_not_packed', u'Zamówienie {} nie jest jeszcze w całości spakowane — '
                              u'weryfikacja po spakowaniu wszystkich pozycji.'.format(numer))
    if any(p.current_status == 'dostarczone' for p in aktywne):
        raise WeryfikacjaBlad('order_status', u'Zamówienie {} jest już dostarczone.'.format(numer))
    if any(p.current_status == 'zaladowane' for p in aktywne):
        raise WeryfikacjaBlad('order_status', u'Zamówienie {} jest już załadowane.'.format(numer))
    return aktywne


def problem_otwarty(order):
    return WeryfikacjaBlad('problem_open', u'Zamówienie {} ma zgłoszony problem ({}) — najpierw go '
                           u'rozwiąż.'.format(order.internal_order_number,
                                              POWODY_PROBLEMU.get(order.problem_reason, order.problem_reason)))


def _oznacz(paczka, metoda, worker_id, teraz):
    paczka.verified_at = teraz
    paczka.verified_by_worker_id = worker_id
    paczka.verified_method = metoda


def _zweryfikuj_zamowienie(order, aktywne, aktualne, metoda, worker_id, device_id, teraz):
    """Wszystkie ważne paczki sprawdzone → pozycje 'zweryfikowane', kto i kiedy, log (spec 8.3)."""
    for p in aktywne:
        p.current_status = 'zweryfikowane'
    order.verified_at = teraz
    order.verified_by_worker_id = worker_id
    delivery.zapisz_log(order, 'weryfikacja', None, paczki.opis_paczek(aktualne), worker_id=worker_id,
                        device_id=device_id, note=_OPIS_METODY[metoda], teraz=teraz)
    delivery.przelicz_zamkniecie(order, teraz)


def zweryfikuj_paczke(paczka, order, metoda, worker_id=None, device_id=None, teraz=None):
    """
    Skan albo ręczne odhaczenie jednej paczki (spec 8.3). Zwraca (zmieniono, zamówienie_zweryfikowane).
    Ostatnia ważna paczka → zamówienie 'zweryfikowane'. Ponowny skan sprawdzonej paczki = OK bez zmian.
    Router bierze paczki.zablokuj_deklaracje(), potem zamówienie i paczkę FOR UPDATE (w tej kolejności —
    jak deklaracja, zamówienie → paczki). NIE commituje.
    """
    teraz = teraz or get_local_now()
    if paczka.voided_at is not None:
        raise WeryfikacjaBlad('package_void', u'Etykieta nieaktualna — paczki zadeklarowano ponownie.')
    aktywne = sprawdz_stan(order)
    if order.problem_at is not None:
        raise problem_otwarty(order)
    if paczka.verified_at is not None:
        return False, all(p.current_status == 'zweryfikowane' for p in aktywne)
    _oznacz(paczka, metoda, worker_id, teraz)
    aktualne = paczki.aktualne_paczki(order.id, do_zapisu=True)
    zweryfikowane = all(p.verified_at is not None for p in aktualne)
    if zweryfikowane:
        _zweryfikuj_zamowienie(order, aktywne, aktualne, metoda, worker_id, device_id, teraz)
    delivery.podbij_pozycje(order, teraz)
    return True, zweryfikowane


def zweryfikuj_wszystkie(order, worker_id=None, device_id=None, teraz=None):
    """„Zweryfikuj wszystkie” (spec 8.3): niesprawdzone ważne paczki ręcznie. Zwraca True, gdy coś
    zmieniła. Weryfikacja wymaga zadeklarowanych paczek (spec 4.4) → bez nich 409 no_packages."""
    teraz = teraz or get_local_now()
    aktywne = sprawdz_stan(order)
    if order.problem_at is not None:
        raise problem_otwarty(order)
    aktualne = paczki.aktualne_paczki(order.id, do_zapisu=True)
    if not aktualne:
        raise WeryfikacjaBlad('no_packages', u'Zamówienie {} nie ma zadeklarowanych paczek — najpierw '
                              u'zadeklaruj paczki.'.format(order.internal_order_number))
    niesprawdzone = [p for p in aktualne if p.verified_at is None]
    if not niesprawdzone and all(p.current_status == 'zweryfikowane' for p in aktywne):
        return False
    for p in niesprawdzone:
        _oznacz(p, 'reczne', worker_id, teraz)
    _zweryfikuj_zamowienie(order, aktywne, aktualne, 'reczne', worker_id, device_id, teraz)
    delivery.podbij_pozycje(order, teraz)
    return True


def cofnij_weryfikacje_zamowienia(order, aktywne, powod, worker_id, device_id, teraz):
    """Pozycje zweryfikowane → 'spakowane', znaczniki weryfikacji zamówienia i aktualnych paczek
    czyszczone (spec 4.5), log 'weryfikacja_cofnieta' z powodem. Wspólne dla „Cofnij weryfikację”
    i zgłoszenia problemu (Task 7)."""
    for p in aktywne:
        if p.current_status == 'zweryfikowane':
            p.current_status = 'spakowane'
    order.verified_at = None
    order.verified_by_worker_id = None
    for p in paczki.aktualne_paczki(order.id, do_zapisu=True):
        p.verified_at = None
        p.verified_by_worker_id = None
        p.verified_method = None
    delivery.zapisz_log(order, 'weryfikacja_cofnieta', note=(powod or u'')[:255] or None,
                        worker_id=worker_id, device_id=device_id, teraz=teraz)
    delivery.przelicz_zamkniecie(order, teraz)
    delivery.podbij_pozycje(order, teraz)


def cofnij_weryfikacje(order, worker_id=None, device_id=None, teraz=None, powod=u'Cofnij weryfikację'):
    """„Cofnij weryfikację” (spec 4.5): tylko zamówienie zweryfikowane i niezaładowane."""
    teraz = teraz or get_local_now()
    aktywne = sprawdz_stan(order)
    if not all(p.current_status == 'zweryfikowane' for p in aktywne):
        raise WeryfikacjaBlad('order_not_verified', u'Zamówienie {} nie jest zweryfikowane.'.format(
            order.internal_order_number))
    cofnij_weryfikacje_zamowienia(order, aktywne, powod, worker_id, device_id, teraz)
    return True
```

- [ ] **Step 4: Endpointy**

Dopisz do `weryfikacja_api.py` (importy: `from extensions import db`, `from modules.production.models import ProductionOrder, ProductionPackage, get_local_now`; usuń `noqa` przy `BLEDY_DO_PONOWIENIA`/`with_idempotency`):

```python
def _zamowienie_do_zapisu(numer):
    """Kolejność blokad zapisu Weryfikacji: blokada deklaracji paczek → wiersz zamówienia po PK."""
    paczki.zablokuj_deklaracje()
    return _zamowienie_po_numerze(numer, do_zapisu=True)


def _odpowiedz(order, message, **dodatkowe):
    dane = {'order': weryfikacja.serializuj_zamowienie(
                order, paczki.aktualne_paczki(order.id), routes.trasy_zamowien([order.id]).get(order.id)),
            'message': message}
    dane.update(dodatkowe)
    return jsonify(dane), 200


@weryfikacja_mobile_bp.route('/packages/<int:package_id>/verify', methods=['POST'])
@require_device_token
@wymaga_weryfikacji
@with_idempotency(retryable_statuses=BLEDY_DO_PONOWIENIA)
def verification_package_verify(package_id):
    """POST /api/mobile/verification/packages/<id>/verify {"method": "skan"|"reczne"} (spec 8.3)."""
    metoda = (request.get_json(silent=True) or {}).get('method') or 'skan'
    if metoda not in weryfikacja.METODY:
        return jsonify({'error': 'invalid_method', 'message': u'Sposób weryfikacji: „skan” albo „reczne”.'}), 422
    worker_id, err = _pracownik()
    if err:
        return err
    paczki.zablokuj_deklaracje()
    # Zamówienie paczki ustalamy zwykłym odczytem, a blokujemy najpierw zamówienie, potem paczkę —
    # ta sama kolejność co deklaracja (zamówienie → paczki), więc bez cyklu blokad.
    order_id = db.session.query(ProductionPackage.order_id).filter_by(id=package_id).scalar()
    if order_id is None:
        return jsonify({'error': 'package_not_found', 'message': u'Nie ma paczki P-{}.'.format(package_id)}), 404
    order = ProductionOrder.query.filter_by(id=order_id).with_for_update().populate_existing().one()
    paczka = ProductionPackage.query.filter_by(id=package_id).with_for_update().populate_existing().one()
    try:
        zmieniono, zweryfikowane = weryfikacja.zweryfikuj_paczke(paczka, order, metoda, worker_id=worker_id,
                                                                device_id=g.device.id)
    except weryfikacja.WeryfikacjaBlad as e:
        return _blad(e)
    aktualne = paczki.aktualne_paczki(order.id)
    licznik = u'{} / {}'.format(sum(1 for p in aktualne if p.verified_at is not None), len(aktualne))
    if zmieniono and zweryfikowane:
        komunikat = u'Zamówienie {} zweryfikowane ({}).'.format(order.internal_order_number, licznik)
    elif zmieniono:
        komunikat = u'Paczka {} sprawdzona ({}).'.format(paczka.kod, licznik)
    else:
        komunikat = u'Paczka {} była już sprawdzona ({}).'.format(paczka.kod, licznik)
    logger.info("Weryfikacja: paczka", extra={'package': paczka.kod, 'changed': zmieniono,
                                              'order_verified': zweryfikowane, 'device_id': g.device.device_id})
    return _odpowiedz(order, komunikat, package=paczki.serializuj_paczke(paczka),
                      order_verified=zweryfikowane, changed=zmieniono)


@weryfikacja_mobile_bp.route('/orders/<numer>/verify-all', methods=['POST'])
@require_device_token
@wymaga_weryfikacji
@with_idempotency(retryable_statuses=BLEDY_DO_PONOWIENIA)
def verification_verify_all(numer):
    """POST /api/mobile/verification/orders/<nr>/verify-all — wszystkie ważne paczki ręcznie."""
    worker_id, err = _pracownik()
    if err:
        return err
    order = _zamowienie_do_zapisu(numer)
    if order is None:
        return _brak_zamowienia(numer)
    try:
        zmieniono = weryfikacja.zweryfikuj_wszystkie(order, worker_id=worker_id, device_id=g.device.id)
    except weryfikacja.WeryfikacjaBlad as e:
        return _blad(e)
    komunikat = (u'Zamówienie {} zweryfikowane ręcznie.' if zmieniono
                 else u'Zamówienie {} było już zweryfikowane.').format(order.internal_order_number)
    return _odpowiedz(order, komunikat, order_verified=True, changed=zmieniono)


@weryfikacja_mobile_bp.route('/orders/<numer>/unverify', methods=['POST'])
@require_device_token
@wymaga_weryfikacji
@with_idempotency(retryable_statuses=BLEDY_DO_PONOWIENIA)
def verification_unverify(numer):
    """POST /api/mobile/verification/orders/<nr>/unverify — „Cofnij weryfikację” (spec 4.5)."""
    worker_id, err = _pracownik()
    if err:
        return err
    order = _zamowienie_do_zapisu(numer)
    if order is None:
        return _brak_zamowienia(numer)
    try:
        weryfikacja.cofnij_weryfikacje(order, worker_id=worker_id, device_id=g.device.id)
    except weryfikacja.WeryfikacjaBlad as e:
        return _blad(e)
    return _odpowiedz(order, u'Cofnięto weryfikację zamówienia {} — paczki trzeba sprawdzić od nowa.'.format(
        order.internal_order_number), changed=True)
```

- [ ] **Step 5: Uruchom testy zadania**

Run: `PYTEST tests/test_weryfikacja_akcje.py tests/test_weryfikacja_lista.py tests/test_paczki_deklaracja.py`
Expected: PASS.

- [ ] **Step 6: Pełny pakiet i commit**

Run: `PYTEST tests/`
Expected: 0 failed.

```bash
git add modules/production/logistics/services/weryfikacja.py modules/production/logistics/routers/weryfikacja_api.py \
  tests/test_weryfikacja_akcje.py
git commit -m "feat(production): weryfikacja paczek z telefonu i cofniecie weryfikacji" \
  -m "Skan albo reczne odhaczenie paczki, ostatnia wazna paczka weryfikuje zamowienie; Zweryfikuj wszystkie, Cofnij weryfikacje; odmowy package_void, problem_open, order_not_packed, order_status, no_packages; pracownik wymagany." \
  -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Problem, „Cofnij do pakowania” i baner `repack_reason`

**Files:**
- Modify: `modules/production/logistics/services/weryfikacja.py`
- Modify: `modules/production/logistics/routers/weryfikacja_api.py`
- Modify: `modules/production/logistics/sposoby.py` (`transport_payload`)
- Modify: `modules/production/routers/mobile_api.py` (`KSZTALT_ODPOWIEDZI_KOLEJKI` :123–135)
- Modify: `modules/production/logistics/services/bl_sync.py` (po `po_zmianie`)
- Modify: `modules/production/services/mobile_api_service.py` (`with_idempotency`, po sygnale dla agenta druku)
- Modify: `tests/test_logistyka_sposoby.py:36-49`, `tests/test_logistyka_mobile.py:36-48`
- Test: `tests/test_weryfikacja_problem.py`

**Interfaces:**
- Consumes: Task 6 (`WeryfikacjaBlad`, `sprawdz_stan`, `cofnij_weryfikacje_zamowienia`, `_zamowienie_do_zapisu`, `_odpowiedz`), Task 1 (`uniewaznij_etapy`, `PRZEPAKUJ_NA_KURIERA`), Task 5 (`POWODY_PROBLEMU`, `etap`).
- Produces: `weryfikacja.waliduj_powod(powod) -> str` (422 `invalid_problem`), `weryfikacja.zglos_problem(order, powod, notatka, worker_id=None, device_id=None, teraz=None) -> bool`, `weryfikacja.rozwiaz_problem(order, worker_id=None, device_id=None, teraz=None, notatka=None) -> bool`, `weryfikacja.cofnij_do_pakowania(order, powod=None, notatka=None, worker_id=None, device_id=None, teraz=None) -> str` (tekst banera); `sposoby.transport_payload(...)['repack_reason']`; `bl_sync.zaplanuj_po_commicie(order_id)`, `bl_sync.wyslij_zaplanowane()`; `mobile_api.KSZTALT_ODPOWIEDZI_KOLEJKI = 5`.

- [ ] **Step 1: Testy, które padną**

Create `tests/test_weryfikacja_problem.py`:

```python
# -*- coding: utf-8 -*-
"""Problem przy weryfikacji, „Cofnij do pakowania” i baner repack_reason na tablecie pakowania
(logistyka etap 4, krok 4.3, spec 4.5, 8.3 i 8.4)."""
import itertools
from datetime import date, datetime

import pytest

from extensions import db
from modules.production.logistics import sposoby as s
from modules.production.logistics.models import LogisticsLog, Route, RouteStop
from modules.production.logistics.services import bl_sync
from modules.production.models import (ProcessedMobileOperation, ProductionDevice, ProductionOrder,
                                       ProductionPackage)
from modules.production.routers import mobile_api
from modules.production.services.mobile_api_service import generate_token
from tests.logistyka_fixtures import app, client, pracownik, zamowienie  # noqa: F401

BASE = '/api/mobile/verification'
T0 = datetime(2026, 10, 1, 8, 0)
_licznik = itertools.count(1)
_numery = itertools.count(3100)


@pytest.fixture(autouse=True)
def bez_statusow_base(monkeypatch):
    monkeypatch.setattr(
        'modules.production.services.baselinker_status_sync.schedule_after_station_complete',
        lambda *a, **k: None)


@pytest.fixture()
def dopychacz(monkeypatch):
    wolania = []
    monkeypatch.setattr(bl_sync, 'uruchom_w_tle', lambda app: wolania.append('start') or True)
    return wolania


def _urzadzenie(stanowisko='verification'):
    device = ProductionDevice(device_id='TEL-%s-%d' % (stanowisko, next(_licznik)),
                              device_name='Telefon', station_code=stanowisko)
    db.session.add(device)
    db.session.commit()
    return device


def _naglowki(device, kto=None, op_id=None):
    naglowki = {'Authorization': 'Bearer ' + generate_token(device),
                'X-Operation-Id': op_id or 'op-prob-%d' % next(_licznik)}
    if kto is not None:
        naglowki['X-Worker-Ids'] = str(kto.id)
    return naglowki


def _z_paczkami(statusy=('spakowane', 'spakowane'), n=2, sposob=s.KURIER, zweryfikowane=False, **kolumny):
    order = zamowienie(sposob=sposob, statusy=statusy, numer_wewnetrzny=str(next(_numery)),
                       packages_declared_at=T0, **kolumny)
    for p in order.products:
        p.packaging_completed_at = T0
    db.session.add_all([ProductionPackage(order_id=order.id, seq=i, kind='paczka', declared_at=T0,
                                          verified_at=T0 if zweryfikowane else None,
                                          verified_method='skan' if zweryfikowane else None)
                        for i in range(1, n + 1)])
    db.session.commit()
    return order


def _post(client, order, akcja, device, kto, **body):
    return client.post('%s/orders/%s/%s' % (BASE, order.internal_order_number, akcja), json=body,
                       headers=_naglowki(device, kto))


def _akcje(order):
    return [w.action for w in LogisticsLog.query.filter_by(order_id=order.id).order_by(LogisticsLog.id)]


def test_problem_na_spakowanym(app, client):
    kto, device = pracownik(), _urzadzenie()
    order = _z_paczkami()
    r = _post(client, order, 'problem', device, kto, reason='brak_elementu', note=u'  brak   nóżki ')
    assert r.status_code == 200, r.get_json()
    o = ProductionOrder.query.get(order.id)
    assert (o.problem_reason, o.problem_note, o.problem_by_worker_id) == ('brak_elementu', u'brak nóżki', kto.id)
    assert r.get_json()['order']['problem']['reason_label'] == u'Brak elementu'
    assert _akcje(order) == ['problem']


def test_problem_na_zweryfikowanym_cofa_weryfikacje(app, client):
    kto, device = pracownik(), _urzadzenie()
    order = _z_paczkami(statusy=('zweryfikowane', 'zweryfikowane'), zweryfikowane=True, verified_at=T0)
    assert _post(client, order, 'problem', device, kto, reason='uszkodzenie').status_code == 200
    o = ProductionOrder.query.get(order.id)
    assert [p.current_status for p in o.products] == ['spakowane', 'spakowane'] and o.verified_at is None
    assert all(p.verified_at is None for p in ProductionPackage.query.filter_by(order_id=order.id))
    assert _akcje(order) == ['weryfikacja_cofnieta', 'problem']
    assert LogisticsLog.query.filter_by(order_id=order.id, action='weryfikacja_cofnieta').one().note == \
        u'problem: Uszkodzenie'


def test_ponowny_problem_nadpisuje(app, client):
    kto, device = pracownik(), _urzadzenie()
    order = _z_paczkami()
    _post(client, order, 'problem', device, kto, reason='etykieta')
    _post(client, order, 'problem', device, kto, reason='opakowanie', note='x' * 300)
    o = ProductionOrder.query.get(order.id)
    assert o.problem_reason == 'opakowanie' and len(o.problem_note) == 255
    wpis = LogisticsLog.query.filter_by(order_id=order.id, action='problem').order_by(LogisticsLog.id.desc()).first()
    assert (wpis.old_value, wpis.new_value) == ('etykieta', 'opakowanie')


def test_zly_powod_422_zapamietany(app, client):
    r = _post(client, _z_paczkami(), 'problem', _urzadzenie(), pracownik(), reason='pogoda')
    assert (r.status_code, r.get_json()['error']) == (422, 'invalid_problem')
    assert ProcessedMobileOperation.query.count() == 1


@pytest.mark.parametrize('statusy, kod', [(('dostarczone',), 'order_status'),
                                          (('spakowane', 'czeka_na_pakowanie'), 'order_not_packed')])
def test_problem_odmowy(app, client, statusy, kod):
    r = _post(client, _z_paczkami(statusy=statusy), 'problem', _urzadzenie(), pracownik(), reason='inne')
    assert (r.status_code, r.get_json()['error']) == (409, kod)


def test_rozwiazanie_problemu(app, client):
    kto, device = pracownik(), _urzadzenie()
    order = _z_paczkami(problem_reason='etykieta', problem_at=T0)
    r = _post(client, order, 'problem/resolve', device, kto)
    assert r.status_code == 200 and r.get_json()['changed'] is True
    o = ProductionOrder.query.get(order.id)
    assert (o.problem_reason, o.problem_note, o.problem_at, o.problem_by_worker_id) == (None, None, None, None)
    wpis = LogisticsLog.query.filter_by(order_id=order.id, action='problem_rozwiazany').one()
    assert (wpis.old_value, wpis.worker_id) == ('etykieta', kto.id)
    bez = _post(client, order, 'problem/resolve', device, kto)
    assert bez.status_code == 200 and bez.get_json()['changed'] is False


def test_cofniecie_do_pakowania(app, client, dopychacz):
    kto, device = pracownik(), _urzadzenie()
    order = _z_paczkami(statusy=('zweryfikowane', 'zweryfikowane'), zweryfikowane=True, verified_at=T0,
                        logistics_closed_at=T0)
    r = _post(client, order, 'revert-to-packing', device, kto, reason='brak_elementu', note=u'brak nóżki')
    assert r.status_code == 200, r.get_json()
    o = ProductionOrder.query.get(order.id)
    assert [(p.current_status, p.quantity_done_packaging, p.packaging_completed_at) for p in o.products] == \
        [('czeka_na_pakowanie', 0, None), ('czeka_na_pakowanie', 0, None)]
    assert (o.repack_required, o.repack_reason) == (True, u'Weryfikacja: Brak elementu: brak nóżki')
    assert (o.verified_at, o.packages_declared_at, o.logistics_closed_at) == (None, None, None)
    assert o.bl_status_pending_id == s.STATUS_PRODUKCJA_ZAKONCZONA
    assert all(p.voided_at is not None for p in ProductionPackage.query.filter_by(order_id=order.id))
    assert 'cofniete_do_pakowania' in _akcje(order)
    assert dopychacz == ['start']                         # dopychacz Base. dopiero po commicie


def test_cofniecie_przenosi_problem_do_banera(app, client, dopychacz):
    kto, device = pracownik(), _urzadzenie()
    order = _z_paczkami(problem_reason='uszkodzenie', problem_note=u'pęknięty blat', problem_at=T0)
    assert _post(client, order, 'revert-to-packing', device, kto).status_code == 200
    o = ProductionOrder.query.get(order.id)
    assert o.repack_reason == u'Weryfikacja: Uszkodzenie: pęknięty blat' and o.problem_at is None
    assert LogisticsLog.query.filter_by(order_id=order.id, action='problem_rozwiazany').one().note == \
        u'przeniesiony do banera pakowania'


def test_cofniecie_bez_powodu_i_bez_problemu_422(app, client, dopychacz):
    r = _post(client, _z_paczkami(), 'revert-to-packing', _urzadzenie(), pracownik())
    assert (r.status_code, r.get_json()['error']) == (422, 'invalid_problem')
    assert dopychacz == []


def test_zamowienie_na_trasie_zostaje_na_niej(app, client, dopychacz):
    order = _z_paczkami(sposob=s.TRANSPORT)
    trasa = Route(name=u'Rzeszów', date_from=date(2026, 10, 7), date_to=date(2026, 10, 7), status='zatwierdzona')
    db.session.add(trasa)
    db.session.flush()
    db.session.add(RouteStop(route_id=trasa.id, order_id=order.id, position=1))
    db.session.commit()
    assert _post(client, order, 'revert-to-packing', _urzadzenie(), pracownik(), reason='inne').status_code == 200
    assert RouteStop.query.filter_by(order_id=order.id).one().route_id == trasa.id


def test_baner_na_tablecie_i_ponowne_spakowanie(app, client, dopychacz):
    order = _z_paczkami()
    _post(client, order, 'revert-to-packing', _urzadzenie(), pracownik(), reason='opakowanie')
    tablet = _urzadzenie('packaging')
    r = client.get('/api/mobile/stations/packaging/orders', headers={'Authorization': 'Bearer ' + generate_token(tablet)})
    transport = r.get_json()['orders'][0]['transport']
    assert (transport['repack_required'], transport['repack_reason']) == (True, u'Weryfikacja: Opakowanie')
    assert mobile_api.KSZTALT_ODPOWIEDZI_KOLEJKI == 5
    o = ProductionOrder.query.get(order.id)
    for p in o.products:
        p.complete_task('packaging')
    db.session.commit()
    o = ProductionOrder.query.get(order.id)
    assert (o.repack_required, o.repack_reason) == (False, None)
    assert [p.current_status for p in o.products] == ['spakowane', 'spakowane']
```

Dopasuj istniejące testy:

`tests/test_logistyka_sposoby.py`:

```python
def test_transport_bez_sposobu_i_bez_trasy():
    order = NS(override_delivery_method=None, repack_required=False)
    assert s.transport_payload(order) == {
        'mode': None, 'trip_name': None, 'trip_date': None,
        'vehicle_name': None, 'repack_required': False, 'repack_reason': None}


def test_transport_z_trasa_i_przepakowaniem():
    order = NS(override_delivery_method=s.TRANSPORT, repack_required=True)
    trasa = NS(name='Kraków + Tarnów', date_from=date(2026, 9, 30),
               vehicle=NS(name='Iveco KR 12345'))
    assert s.transport_payload(order, trasa) == {
        'mode': 'wlasny', 'trip_name': 'Kraków + Tarnów', 'trip_date': '2026-09-30',
        'vehicle_name': 'Iveco KR 12345', 'repack_required': True,
        'repack_reason': s.PRZEPAKUJ_NA_KURIERA}   # stary repack_required bez tekstu → tekst domyślny


def test_transport_z_powodem_z_weryfikacji():
    order = NS(override_delivery_method=s.KURIER, repack_required=True,
               repack_reason=u'Weryfikacja: Uszkodzenie: pęknięty blat')
    assert s.transport_payload(order)['repack_reason'] == u'Weryfikacja: Uszkodzenie: pęknięty blat'
    order.repack_required = False
    assert s.transport_payload(order)['repack_reason'] is None
```

`tests/test_logistyka_mobile.py`: w `test_serializer_zawsze_ma_obiekt_transport_i_stare_delivery_type` oczekiwany słownik dostaje `'repack_reason': None`; `test_ksztalt_odpowiedzi_podbity` → `== 5   # 5 — transport.repack_reason (etap 4, krok 4.3)`.

- [ ] **Step 2: Uruchom — mają paść**

Run: `PYTEST tests/test_weryfikacja_problem.py tests/test_logistyka_sposoby.py tests/test_logistyka_mobile.py`
Expected: FAIL (404 na endpointach, brak `repack_reason`, kształt 4).

- [ ] **Step 3: `transport_payload` i kształt kolejki**

`sposoby.py` — w słowniku zwracanym przez `transport_payload` po `'repack_required': …` dopisz `'repack_reason': _tekst_przepakowania(order),`, a pod funkcją:

```python
def _tekst_przepakowania(order):
    """
    Tekst banera na tablecie pakowania (logistyka etap 4, spec 8.4): powód z Weryfikacji albo
    przepakowania na kuriera. Stare repack_required bez tekstu (sprzed kroku 4.3) → tekst domyślny.
    Bez przepakowania — None (appka pokazuje baner tylko przy repack_required).
    """
    if order is None or not getattr(order, 'repack_required', False):
        return None
    return getattr(order, 'repack_reason', None) or PRZEPAKUJ_NA_KURIERA
```

`mobile_api.py` — komentarz historii kształtu i wartość:

```python
#   4 — 2026-09-30: `packing_hint` (logistyka etap 4, krok 4.2 — okno paczek na pakowaniu)
#   5 — 2026-09-30: `transport.repack_reason` (logistyka etap 4, krok 4.3 — baner przepakowania)
KSZTALT_ODPOWIEDZI_KOLEJKI = 5
```

- [ ] **Step 4: Dopychacz Base. po commicie żądania API mobilnego**

`bl_sync.py` — pod `po_zmianie`:

```python
def zaplanuj_po_commicie(order_id):
    """
    Zamówienie, którego zmiana czeka na wysłanie do Base., zapamiętane w `g` żądania API mobilnego.
    Dopychacz startuje dopiero po udanym commicie (with_idempotency → wyslij_zaplanowane); przy
    rollbacku i powtórce idempotentnej lista ginie razem z `g` (jak sygnał dla agenta druku).
    """
    from flask import g, has_request_context
    if not has_request_context():
        return
    lista = getattr(g, '_logistyka_bl_po_commicie', None)
    if lista is None:
        lista = g._logistyka_bl_po_commicie = []
    lista.append(order_id)


def wyslij_zaplanowane():
    """Po commicie: uruchamia dopychacz dla zamówień z zaplanuj_po_commicie (najwyżej raz na żądanie)."""
    from flask import g, has_request_context
    if not has_request_context():
        return
    lista = getattr(g, '_logistyka_bl_po_commicie', None) or []
    g._logistyka_bl_po_commicie = []
    if lista:
        po_zmianie(lista)
```

`mobile_api_service.py`, `with_idempotency` — po bloku „Etykiety paczek … wyslij_zaplanowany_sygnal()” dopisz:

```python
            # Logistyka etap 4: zmiany dla Base. z telefonu (np. 138620 po „Cofnij do pakowania”) —
            # dopychacz w tle dopiero po commicie (bl_sync.zaplanuj_po_commicie).
            try:
                from modules.production.logistics.services.bl_sync import wyslij_zaplanowane
                wyslij_zaplanowane()
            except Exception as bl_logistyka_error:
                logger.error("Mobile API: błąd uruchomienia dopychacza logistyki", extra={
                    'error': str(bl_logistyka_error),
                })
```

i dopisz w docstringu dekoratora zdanie o dopychaczu obok akapitu o sygnale dla agenta druku.

- [ ] **Step 5: Serwis — problem i cofnięcie do pakowania**

Dopisz do `weryfikacja.py`:

```python
def _notatka(wartosc):
    """Notatka z JSON-a: tekst z pojedynczymi spacjami, najwyżej 255 znaków (dłuższa jest ucinana —
    422 z kolejki offline to utracona akcja); inny typ albo pusty tekst → None."""
    if not isinstance(wartosc, str):
        return None
    return ' '.join(wartosc.split())[:255] or None


def waliduj_powod(powod):
    if powod not in POWODY_PROBLEMU:
        raise WeryfikacjaBlad('invalid_problem', u'Powód problemu: {}.'.format(
            u', '.join(sorted(POWODY_PROBLEMU))), 422)
    return powod


def zglos_problem(order, powod, notatka, worker_id=None, device_id=None, teraz=None):
    """
    Zgłoszenie problemu (spec 8.3): tylko przed załadunkiem. Zamówienie zweryfikowane (albo z częścią
    sprawdzonych paczek) traci weryfikację — inaczej problem obszedłby bramkę załadunku. Ponowne
    zgłoszenie nadpisuje powód i notatkę. NIE commituje.
    """
    teraz = teraz or get_local_now()
    waliduj_powod(powod)
    notatka = _notatka(notatka)
    aktywne = sprawdz_stan(order)
    aktualne = paczki.aktualne_paczki(order.id, do_zapisu=True)
    if (order.verified_at is not None or any(p.current_status == 'zweryfikowane' for p in aktywne)
            or any(p.verified_at is not None for p in aktualne)):
        cofnij_weryfikacje_zamowienia(order, aktywne, u'problem: {}'.format(POWODY_PROBLEMU[powod]),
                                      worker_id, device_id, teraz)
    stary = order.problem_reason
    order.problem_reason = powod
    order.problem_note = notatka
    order.problem_at = teraz
    order.problem_by_worker_id = worker_id
    delivery.zapisz_log(order, 'problem', stary, powod, note=notatka, worker_id=worker_id,
                        device_id=device_id, teraz=teraz)
    delivery.podbij_pozycje(order, teraz)
    return True


def rozwiaz_problem(order, worker_id=None, device_id=None, teraz=None, notatka=None):
    """Zdjęcie flagi problemu (spec 8.3). Bez problemu — False bez zmian (kolejka offline nie utyka)."""
    if order.problem_at is None:
        return False
    teraz = teraz or get_local_now()
    stary = order.problem_reason
    order.problem_reason = None
    order.problem_note = None
    order.problem_at = None
    order.problem_by_worker_id = None
    delivery.zapisz_log(order, 'problem_rozwiazany', stary, None, note=notatka, worker_id=worker_id,
                        device_id=device_id, teraz=teraz)
    delivery.podbij_pozycje(order, teraz)
    return True


def cofnij_do_pakowania(order, powod=None, notatka=None, worker_id=None, device_id=None, teraz=None):
    """
    „Cofnij do pakowania” (spec 4.5 i 8.4) — jak przepakowanie z etapu 1: pozycje → czeka_na_pakowanie,
    licznik pakowania wyzerowany zdarzeniem systemowym, repack_required + repack_reason
    („Weryfikacja: <powód>: <notatka>”), Base. 138620 (dopychacz po commicie), paczki i weryfikacja
    unieważnione jedną regułą, otwarty problem przeniesiony do banera. Brak powodu w żądaniu → powód
    i notatka z otwartego problemu. Zamówienie na trasie zostaje na niej. Zwraca tekst banera.
    """
    teraz = teraz or get_local_now()
    notatka = _notatka(notatka)
    if not powod and order.problem_at is not None:
        powod = order.problem_reason
        notatka = notatka or order.problem_note
    if not powod:
        raise WeryfikacjaBlad('invalid_problem', u'Podaj powód cofnięcia do pakowania.', 422)
    waliduj_powod(powod)
    aktywne = sprawdz_stan(order)
    przed, _napis = etap(aktywne)
    tekst = (u'Weryfikacja: {}'.format(POWODY_PROBLEMU[powod])
             + (u': {}'.format(notatka) if notatka else u''))[:255]
    for p in aktywne:
        # Zdarzenie systemowe bez atrybucji — jak przepakowanie w delivery.ustaw_sposob_dostawy.
        p.set_quantity_done('packaging', 0, source='system')
        p.packaging_completed_at = None
        p.current_status = 'czeka_na_pakowanie'
    order.repack_required = True
    order.repack_reason = tekst
    order.bl_status_pending_id = sposoby.STATUS_PRODUKCJA_ZAKONCZONA
    if order.problem_at is not None:
        rozwiaz_problem(order, worker_id, device_id, teraz, notatka=u'przeniesiony do banera pakowania')
    delivery.zapisz_log(order, 'cofniete_do_pakowania', przed, 'czeka_na_pakowanie', note=tekst,
                        worker_id=worker_id, device_id=device_id, teraz=teraz)
    uniewaznij_etapy(order, teraz, u'cofnięte do pakowania', worker_id=worker_id, device_id=device_id)
    delivery.przelicz_zamkniecie(order, teraz)
    delivery.podbij_pozycje(order, teraz)
    from modules.production.logistics.services import bl_sync
    bl_sync.zaplanuj_po_commicie(order.id)
    return tekst
```

- [ ] **Step 6: Endpointy**

Dopisz do `weryfikacja_api.py`:

```python
@weryfikacja_mobile_bp.route('/orders/<numer>/problem', methods=['POST'])
@require_device_token
@wymaga_weryfikacji
@with_idempotency(retryable_statuses=BLEDY_DO_PONOWIENIA)
def verification_problem(numer):
    """POST /api/mobile/verification/orders/<nr>/problem {"reason", "note"} (spec 8.3)."""
    dane = request.get_json(silent=True) or {}
    try:
        weryfikacja.waliduj_powod(dane.get('reason'))
    except weryfikacja.WeryfikacjaBlad as e:
        return _blad(e)
    worker_id, err = _pracownik()
    if err:
        return err
    order = _zamowienie_do_zapisu(numer)
    if order is None:
        return _brak_zamowienia(numer)
    try:
        weryfikacja.zglos_problem(order, dane.get('reason'), dane.get('note'), worker_id=worker_id,
                                  device_id=g.device.id)
    except weryfikacja.WeryfikacjaBlad as e:
        return _blad(e)
    return _odpowiedz(order, u'Zgłoszono problem w zamówieniu {}: {}.'.format(
        order.internal_order_number, weryfikacja.POWODY_PROBLEMU[dane.get('reason')]), changed=True)


@weryfikacja_mobile_bp.route('/orders/<numer>/problem/resolve', methods=['POST'])
@require_device_token
@wymaga_weryfikacji
@with_idempotency(retryable_statuses=BLEDY_DO_PONOWIENIA)
def verification_problem_resolve(numer):
    """POST /api/mobile/verification/orders/<nr>/problem/resolve — zdjęcie flagi problemu."""
    worker_id, err = _pracownik()
    if err:
        return err
    order = _zamowienie_do_zapisu(numer)
    if order is None:
        return _brak_zamowienia(numer)
    zmieniono = weryfikacja.rozwiaz_problem(order, worker_id=worker_id, device_id=g.device.id)
    komunikat = (u'Problem w zamówieniu {} rozwiązany.' if zmieniono
                 else u'Zamówienie {} nie ma otwartego problemu.').format(order.internal_order_number)
    return _odpowiedz(order, komunikat, changed=zmieniono)


@weryfikacja_mobile_bp.route('/orders/<numer>/revert-to-packing', methods=['POST'])
@require_device_token
@wymaga_weryfikacji
@with_idempotency(retryable_statuses=BLEDY_DO_PONOWIENIA)
def verification_revert_to_packing(numer):
    """POST /api/mobile/verification/orders/<nr>/revert-to-packing {"reason"?, "note"?} (spec 8.4)."""
    dane = request.get_json(silent=True) or {}
    worker_id, err = _pracownik()
    if err:
        return err
    order = _zamowienie_do_zapisu(numer)
    if order is None:
        return _brak_zamowienia(numer)
    try:
        weryfikacja.cofnij_do_pakowania(order, dane.get('reason'), dane.get('note'), worker_id=worker_id,
                                        device_id=g.device.id)
    except weryfikacja.WeryfikacjaBlad as e:
        return _blad(e)
    return _odpowiedz(order, u'Zamówienie {} wraca do pakowania. Paczki są nieaktualne — pakowacz '
                             u'zadeklaruje je od nowa.'.format(order.internal_order_number), changed=True)
```

- [ ] **Step 7: Uruchom testy zadania i sąsiednie**

Run: `PYTEST tests/test_weryfikacja_problem.py tests/test_weryfikacja_akcje.py tests/test_logistyka_sposoby.py tests/test_logistyka_mobile.py tests/test_mobile_complete_bl_sync_queue.py tests/test_paczki_deklaracja.py tests/test_paczki_ponowny_druk.py`
Expected: PASS.

- [ ] **Step 8: Pełny pakiet i commit**

Run: `PYTEST tests/`
Expected: 0 failed.

```bash
git add modules/production/logistics/services/weryfikacja.py modules/production/logistics/routers/weryfikacja_api.py \
  modules/production/logistics/sposoby.py modules/production/routers/mobile_api.py \
  modules/production/logistics/services/bl_sync.py modules/production/services/mobile_api_service.py \
  tests/test_weryfikacja_problem.py tests/test_logistyka_sposoby.py tests/test_logistyka_mobile.py
git commit -m "feat(production): problem przy weryfikacji i cofniecie zamowienia do pakowania" \
  -m "Zgloszenie i rozwiazanie problemu z telefonu, Cofnij do pakowania z banerem repack_reason na tablecie (ksztalt kolejki 5), Base. 138620 wysylany po commicie, paczki i weryfikacja uniewaznione jedna regula." \
  -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: Panel Logistyki — etap po spakowaniu, paczki, problem i filtry (spec 11)

Tor równoległy z Task 6–7 (worktree `…-t8`, `-p logistyka4-t8`, baza = główna gałąź po Task 5 i scaleniu Task 4). UI robi implementer ze skillem **`frontend-design:frontend-design`**, w istniejącym stylu zakładki (te same kafle, plakietki, kolory i odstępy co ikony „etykiety sprzed zmiany” i filtr „Transport bez trasy”); w tekstach UI „Base.”.

**Files:**
- Modify: `modules/production/logistics/services/lista.py` (`KOLEJNOSC_ETAPOW`, `_etap`, `_pozycja`, `serializuj`, `pobierz`, nowa `liczniki_weryfikacji`)
- Modify: `modules/production/logistics/routers/panel_api.py` (`orders()` :100–125)
- Modify: `modules/production/logistics/static/js/logistics.js` (:102–106, :828–831, :840–931, filtr i parametry zapytania :286–302, :475)
- Modify: `modules/production/logistics/static/js/logistics-map.js:466`, `modules/production/logistics/static/js/logistics-routes.js:463`
- Modify: `modules/production/logistics/static/css/logistics.css` (:769, :779 i nowe klasy)
- Modify: `modules/production/logistics/templates/logistics/tab_content.html` (pasek filtrów przy :127, legenda :278, wersje skryptów i stylów)
- Modify: `tests/test_logistyka_poprawki_panelu.py:114-124`
- Test: `tests/test_weryfikacja_panel.py`

**Interfaces:**
- Consumes: Task 5 (`weryfikacja.NAZWY_ETAPOW`, `POWODY_PROBLEMU`, `warunek_do_weryfikacji(teraz)`, `warunek_problemu()`, `warunek_bez_paczek(teraz)`, `liczba_do_weryfikacji(teraz)`, `liczba_problemow()`), `paczki.opis_paczek(lista)`, `delivery.wszystkie_w`.
- Produces: wiersz listy (`lista.serializuj`) dostaje `paczki` (`null` albo `{"opis": "2 × paczka", "liczba": 2, "zweryfikowane": 1}`), `bez_paczek` (bool), `problem` (`null` albo `{"powod", "etykieta", "notatka", "kiedy"}`), `zweryfikowano` (ISO albo `null`); `etap.nazwa` dla `spakowane` = „Spakowane — czeka na weryfikację”; `lista.pobierz(…, stan=None)` z `stan` ∈ `do_weryfikacji`, `problem`, `bez_paczek`; `GET …/orders?stan=…`; odpowiedź listy ma `weryfikacja: {"do_weryfikacji": N, "problem": N, "bez_paczek": N}`.

- [ ] **Step 1: Testy, które padną**

Create `tests/test_weryfikacja_panel.py`:

```python
# -*- coding: utf-8 -*-
"""Panel Logistyki po kroku 4.3 (spec 11): etap po spakowaniu, paczki, problem, filtry
„Do weryfikacji”, „Problem”, „Bez paczek”."""
import os
import re
from datetime import timedelta

import pytest

from extensions import db
from modules.production.logistics import sposoby as s
from modules.production.logistics.services import lista
from modules.production.models import ProductionPackage, get_local_now
from tests.logistyka_fixtures import BASE, app, client, zamowienie  # noqa: F401

KORZEN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG = os.path.join(KORZEN, 'modules', 'production', 'logistics')


def _plik(*czesci):
    with open(os.path.join(LOG, *czesci), encoding='utf-8') as f:
        return f.read()


def _spakowane(sposob=s.KURIER, statusy=('spakowane',), dni_temu=0, zamkniete=False, paczek=0, **kolumny):
    teraz = get_local_now()
    order = zamowienie(sposob=sposob, statusy=statusy,
                       logistics_closed_at=teraz if zamkniete else None, **kolumny)
    for p in order.products:
        p.packaging_completed_at = teraz - timedelta(days=dni_temu)
    if paczek:
        order.packages_declared_at = teraz
        db.session.add_all([ProductionPackage(order_id=order.id, seq=i, kind='paczka', declared_at=teraz,
                                              verified_at=teraz if i == 1 else None)
                            for i in range(1, paczek + 1)])
    db.session.commit()
    return order


@pytest.mark.parametrize('status, nazwa', [
    ('spakowane', u'Spakowane — czeka na weryfikację'), ('zweryfikowane', 'Zweryfikowane'),
    ('zaladowane', u'Załadowane'), ('dostarczone', 'Dostarczone')])
def test_etap_po_spakowaniu(app, status, nazwa):
    wiersz = lista.serializuj(zamowienie(statusy=(status,)))
    assert wiersz['etap'] == {'status': status, 'nazwa': nazwa}


def test_etap_zamowienia_to_najbardziej_zalegla_pozycja(app):
    wiersz = lista.serializuj(zamowienie(statusy=('zweryfikowane', 'spakowane', 'dostarczone')))
    assert wiersz['etap']['status'] == 'spakowane'


def test_paczki_problem_i_bez_paczek_w_wierszu(app):
    teraz = get_local_now()
    z_paczkami = _spakowane(paczek=2, problem_reason='uszkodzenie', problem_note=u'róg', problem_at=teraz)
    wiersz = lista.serializuj(z_paczkami)
    assert wiersz['paczki'] == {'opis': u'2 × paczka', 'liczba': 2, 'zweryfikowane': 1}
    assert wiersz['problem'] == {'powod': 'uszkodzenie', 'etykieta': 'Uszkodzenie', 'notatka': u'róg',
                                 'kiedy': teraz.isoformat()}
    assert wiersz['bez_paczek'] is False
    bez = lista.serializuj(_spakowane())
    assert (bez['paczki'], bez['bez_paczek'], bez['problem']) == (None, True, None)
    w_produkcji = lista.serializuj(zamowienie(statusy=('czeka_na_pakowanie',)))
    assert w_produkcji['bez_paczek'] is False


def test_filtry_weryfikacji(app, client):
    teraz = get_local_now()
    do_weryfikacji = _spakowane(zamkniete=True, paczek=1)           # kurier zamknięty, świeży
    bez_paczek = _spakowane(sposob=s.TRANSPORT)                      # otwarty, bez deklaracji
    stare = _spakowane(zamkniete=True, dni_temu=12)                  # poza oknem
    problem = _spakowane(statusy=('zweryfikowane',), paczek=1, problem_reason='etykieta', problem_at=teraz)
    numery = lambda stan: {w['numer'] for w in client.get(BASE + '/orders?stan=' + stan).get_json()['orders']}
    assert numery('do_weryfikacji') == {do_weryfikacji.internal_order_number, bez_paczek.internal_order_number}
    assert numery('bez_paczek') == {bez_paczek.internal_order_number}
    assert numery('problem') == {problem.internal_order_number}
    assert stare.internal_order_number not in numery('do_weryfikacji')
    dane = client.get(BASE + '/orders').get_json()
    assert dane['weryfikacja'] == {'do_weryfikacji': 2, 'problem': 1, 'bez_paczek': 1}


def test_nieznany_stan_422(app, client):
    assert client.get(BASE + '/orders?stan=pogoda').status_code == 422


def test_front_zna_nowe_etapy_i_filtry():
    js = _plik('static', 'js', 'logistics.js')
    kolejnosc = re.search(r"KOLEJNOSC_ETAPOW = \[([^\]]*)\]", js).group(1)
    wartosci = re.findall(r"'(\w+)'", kolejnosc)
    i = wartosci.index('spakowane')
    assert wartosci[i:i + 4] == list(s.STATUSY_PO_SPAKOWANIU)
    assert re.search(r"const STATUSY_PO_SPAKOWANIU = \['spakowane', 'zweryfikowane', 'zaladowane', 'dostarczone'\]", js)
    for plik in ('logistics.js', 'logistics-map.js', 'logistics-routes.js'):
        tresc = _plik('static', 'js', plik)
        assert not re.search(r"(etap\.status|status)\s*===\s*'spakowane'", tresc), plik
    assert "params.set('stan'" in js
    szablon = _plik('templates', 'logistics', 'tab_content.html')
    for stan in ('do_weryfikacji', 'problem', 'bez_paczek'):
        assert 'data-lg-stan="%s"' % stan in szablon, stan
    css = _plik('static', 'css', 'logistics.css')
    for status in s.STATUSY_LOGISTYCZNE:
        assert '[data-etap="%s"]' % status in css, status
```

W `tests/test_logistyka_poprawki_panelu.py` (parametryzacja `test_etap_to_nazwa_stanowiska`) zmień `('spakowane', 'Spakowane')` na `('spakowane', u'Spakowane — czeka na weryfikację')` z komentarzem „spec 4.1 i 11 (krok 4.3)”.

- [ ] **Step 2: Uruchom — mają paść**

Run: `PYTEST tests/test_weryfikacja_panel.py tests/test_logistyka_poprawki_panelu.py`
Expected: FAIL.

- [ ] **Step 3: Backend listy**

`lista.py`:
- import: `from modules.production.logistics.services import geocoding, paczki, paczki_druk, routes, weryfikacja` i `from modules.production.logistics.services.delivery import aktywne_produkty, wszystkie_spakowane, wszystkie_w`, `from modules.production.models import get_local_now` (obok istniejących importów modeli);
- `KOLEJNOSC_ETAPOW` — po `'spakowane'` dopisz `'zweryfikowane', 'zaladowane', 'dostarczone'`;
- nazwa etapu w `_etap` i `_pozycja`: `weryfikacja.NAZWY_ETAPOW.get(status) or NAZWA_STANOWISKA.get(status) or <produkt>.status_display_name`;
- w `serializuj` po `'etykiety_paczek_sprzed_zmiany': …` dopisz:

```python
        # Krok 4.3 (spec 11): paczki pod kolumną Etap, plakietka „BEZ PACZEK”, ikona problemu.
        'paczki': ({'opis': paczki.opis_paczek(paczki_zamowienia), 'liczba': len(paczki_zamowienia),
                    'zweryfikowane': sum(1 for p in paczki_zamowienia if p.verified_at is not None)}
                   if paczki_zamowienia else None),
        'bez_paczek': not paczki_zamowienia and wszystkie_w(order, ('spakowane', 'zweryfikowane')),
        'problem': _problem(order),
        'zweryfikowano': order.verified_at.isoformat() if order.verified_at else None,
```

oraz funkcję:

```python
def _problem(order):
    if order.problem_at is None:
        return None
    return {'powod': order.problem_reason,
            'etykieta': weryfikacja.POWODY_PROBLEMU.get(order.problem_reason, order.problem_reason),
            'notatka': order.problem_note, 'kiedy': order.problem_at.isoformat()}
```

- `pobierz(sposob=None, etap=None, q=None, zamkniete=False, woj=None, stan=None)` — zamiast `if not zamkniete: …filter(logistics_closed_at IS NULL)`:

```python
    # Krok 4.3 (spec 11): filtry Weryfikacji mają własny zakres (zamówienia kurierskie zamykają się
    # przy spakowaniu, a nadal czekają na weryfikację) — zastępują podział otwarte/zamknięte.
    teraz = get_local_now()
    if stan == 'do_weryfikacji':
        zapytanie = zapytanie.filter(weryfikacja.warunek_do_weryfikacji(teraz))
    elif stan == 'problem':
        zapytanie = zapytanie.filter(weryfikacja.warunek_problemu())
    elif stan == 'bez_paczek':
        zapytanie = zapytanie.filter(weryfikacja.warunek_bez_paczek(teraz))
    elif not zamkniete:
        zapytanie = zapytanie.filter(ProductionOrder.logistics_closed_at.is_(None))
```

  i `if zamkniete:` przy `order_by(...).limit(LIMIT_ZAMKNIETYCH)` → `if zamkniete and not stan:` (uwaga R3 z docstringu: wszystkie filtry PRZED `order_by/limit`).
- nowa funkcja:

```python
STANY_WERYFIKACJI = ('do_weryfikacji', 'problem', 'bez_paczek')


def liczniki_weryfikacji():
    """Liczby przy filtrach Weryfikacji (spec 11) — trzy zapytania COUNT, niezależne od listy."""
    teraz = get_local_now()
    return {'do_weryfikacji': weryfikacja.liczba_do_weryfikacji(teraz),
            'problem': weryfikacja.liczba_problemow(),
            'bez_paczek': db.session.query(func.count(ProductionOrder.id)).filter(
                weryfikacja.warunek_bez_paczek(teraz)).scalar() or 0}
```

`panel_api.py`, `orders()`:

```python
    stan = request.args.get('stan') or None
    if stan is not None and stan not in lista.STANY_WERYFIKACJI:
        return _blad(u'Nieznany filtr weryfikacji.', 422)
```

(przed `wstrzymane = …`), `stan=stan` w wywołaniu `lista.pobierz(...)`, a w odpowiedzi `'weryfikacja': lista.liczniki_weryfikacji(),`. Wyszukiwanie zamkniętych bez frazy (`zamkniete and not q` → 422) zostaje bez zmian.

Jeśli `tests/test_logistyka_poprawki_panelu.py::test_pozycje_bez_zapytania_na_kazda_pozycje` mierzy cały endpoint `/orders`, jego budżet rośnie dokładnie o 3 stałe zapytania liczników — podnieś go i opisz w raporcie (jak Ruling 5 kroku 4.2); liczba zapytań nie może rosnąć z liczbą wierszy.

- [ ] **Step 4: Front (skill `frontend-design:frontend-design`)**

Wywołaj skill `frontend-design:frontend-design` i zaprojektuj zmiany w istniejącym stylu zakładki. Wymagania funkcjonalne (testy z Step 1 pilnują nazw i atrybutów):

1. `logistics.js`: stała `const STATUSY_PO_SPAKOWANIU = ['spakowane', 'zweryfikowane', 'zaladowane', 'dostarczone'];` (kopia `sposoby.STATUSY_PO_SPAKOWANIU`); `KOLEJNOSC_ETAPOW` z trzema nowymi statusami po `'spakowane'`; ptaszek etapu (:828, :928) dla `STATUSY_PO_SPAKOWANIU.includes(etap.status)`; to samo w `logistics-map.js:466` i `logistics-routes.js:463`.
2. Kolumna Etap w wierszu: pod nazwą etapu linia paczek z `w.paczki.opis` (np. „2 × paczka”, „1 × EUR”), a gdy `w.paczki.zweryfikowane` > 0 i < `liczba` — postęp „sprawdzono 1/2”; plakietka „BEZ PACZEK” dla `w.bez_paczek`; ikona problemu dla `w.problem` z dymkiem „Problem: <etykieta> — <notatka> (<data>)” (ten sam komponent dymka co pozostałe ikony wiersza, dostępny z klawiatury i czytnika — `aria-label`). Zamówienia wydane/zamknięte bez weryfikacji (etap `dostarczone` bez `zweryfikowano`) — spec 4.4: panel je pokazuje; wystarczy etap „Dostarczone” bez ptaszka weryfikacji w dymku, nie osobna ikona.
3. Filtry: trzy przyciski w pasku filtrów obok „Transport bez trasy”, atrybuty `data-lg-stan="do_weryfikacji"`, `data-lg-stan="problem"`, `data-lg-stan="bez_paczek"`, `aria-pressed`, liczby z `weryfikacja` w odpowiedzi listy; wzajemnie wykluczające się; stan w `stan.filtr.stan`, wysyłany jako `params.set('stan', …)` (filtr serwera — jak `sposob`); „Zdejmij filtry” i pusty stan listy obsługują nowy filtr („Brak zamówień do weryfikacji.” itp.); `zawezonyWidok()` uwzględnia `stan`.
4. `logistics.css`: selektory `[data-etap="zweryfikowane"]`, `[data-etap="zaladowane"]`, `[data-etap="dostarczone"]` (ptaszek i kolor jak `spakowane` albo odróżnione odcieniem — decyzja projektowa), style linii paczek, plakietki „BEZ PACZEK” i ikony problemu.
5. `tab_content.html`: przyciski filtrów, pozycje legendy (ikona problemu, „BEZ PACZEK”), podbite `?v=` przy `logistics.js`, `logistics-map.js`, `logistics-routes.js` i `logistics.css`.

- [ ] **Step 5: Uruchom testy zadania i sąsiednie**

Run: `PYTEST tests/test_weryfikacja_panel.py tests/test_logistyka_poprawki_panelu.py tests/test_paczki_panel.py tests/test_logistyka_panel_api.py tests/test_logistyka_zakladka.py tests/test_logistyka_trasy_ui.py tests/test_logistyka_mapa_ui.py tests/test_logistyka_przeglad_koncowy_ui.py`
Expected: PASS.

- [ ] **Step 6: Oględziny w przeglądarce (wbudowana przeglądarka, bez Chrome Konrada)**

Render zakładki przez test client z `session_transaction()` (wzór: pamięć „Podgląd strony bez logowania”) albo na podglądzie z Task 10; zrzut ekranu wiersza z paczkami, problemem i „BEZ PACZEK” oraz pasek filtrów — do raportu.

- [ ] **Step 7: Pełny pakiet i commit**

Run: `PYTEST tests/` (w worktree toru)
Expected: 0 failed.

```bash
git add modules/production/logistics/services/lista.py modules/production/logistics/routers/panel_api.py \
  modules/production/logistics/static modules/production/logistics/templates/logistics/tab_content.html \
  tests/test_weryfikacja_panel.py tests/test_logistyka_poprawki_panelu.py
git commit -m "feat(production): panel Logistyki pokazuje weryfikacje, paczki i problemy" \
  -m "Kolumna Etap z etapami po spakowaniu, paczki pod etapem, plakietka BEZ PACZEK i ikona problemu z powodem; filtry Do weryfikacji, Problem i Bez paczek z liczbami (spec 11)." \
  -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: Pasek dashboardu produkcji — „Do weryfikacji: N” i „Problemy: N”

**Files:**
- Modify: `modules/production/routers/api/dashboard_api.py` (render statystyk ok. :1016–1023, `dashboard-data` ok. :1275–1283, nowa `_safe_weryfikacja` obok `_safe_logistyka_bez_sposobu` :201)
- Modify: `modules/production/templates/components/dashboard-tab-content.html` (blok `LOGISTYKA: pasek pod pipeline'em`)
- Modify: `modules/production/static/js/modules/dashboard-module.js` (handler odświeżania :200, `updateLogisticsPending` :2321)
- Modify: `modules/production/static/css/production-panel.css` (klasy paska `il-logistyka`)
- Test: rozszerz `tests/test_dashboard_logistyka_pasek.py`, nowy `tests/test_weryfikacja_dashboard.py`

**Interfaces:**
- Consumes: `weryfikacja.liczba_do_weryfikacji(teraz)`, `weryfikacja.liczba_problemow()` (Task 5).
- Produces: `dashboard_stats['logistics']['verification_pending']`, `['verification_problems']`; w `dashboard-data`: `data.verification = {"pending": N, "problems": N}` albo `null` (błąd licznika); w JS `updateVerification(dane)`; elementy `id="verification-pending"`, `id="verification-problems"`.

- [ ] **Step 1: Testy, które padną**

Create `tests/test_weryfikacja_dashboard.py`:

```python
# -*- coding: utf-8 -*-
"""Liczniki Weryfikacji na dashboardzie produkcji (logistyka etap 4, krok 4.3, spec 11)."""
from modules.production.logistics import sposoby as s
from modules.production.models import get_local_now
from modules.production.routers.api import dashboard_api
from tests.logistyka_fixtures import app, zamowienie  # noqa: F401


def test_liczniki_weryfikacji(app):
    teraz = get_local_now()
    zamowienie(sposob=s.TRANSPORT, statusy=('spakowane',))
    zamowienie(sposob=s.KURIER, statusy=('spakowane',), problem_reason='inne', problem_at=teraz)
    zamowienie(statusy=('czeka_na_pakowanie',))
    assert dashboard_api._safe_weryfikacja() == {'pending': 2, 'problems': 1}


def test_blad_licznika_nie_psuje_odswiezenia(app, monkeypatch):
    from modules.production.logistics.services import weryfikacja
    monkeypatch.setattr(weryfikacja, 'liczba_problemow', lambda: 1 / 0)
    assert dashboard_api._safe_weryfikacja() is None
```

Rozszerz `tests/test_dashboard_logistyka_pasek.py` (fragment szablonu renderowany Jinją jak w `test_pasek_pokazuje_liczbe_albo_spokoj`):

```python
@pytest.mark.parametrize('do_weryfikacji, problemy', [(0, 0), (5, 2)])
def test_pasek_pokazuje_weryfikacje(do_weryfikacji, problemy):
    html = Environment(autoescape=True).from_string(_pasek()).render(
        dashboard_stats={'logistics': {'pending_count': 0, 'verification_pending': do_weryfikacji,
                                       'verification_problems': problemy}},
        url_for=lambda endpoint, **k: '/production/')
    assert 'id="verification-pending">%d<' % do_weryfikacji in html
    assert 'id="verification-problems">%d<' % problemy in html
    assert 'Do weryfikacji' in html and 'Problemy' in html


def test_odswiezanie_paska_weryfikacji():
    js = _plik(DASHBOARD_JS)
    assert 'updateVerification(' in js and 'data.data.verification' in js
    assert "getElementById('verification-pending')" in js
    assert "getElementById('verification-problems')" in js
```

- [ ] **Step 2: Uruchom — mają paść**

Run: `PYTEST tests/test_weryfikacja_dashboard.py tests/test_dashboard_logistyka_pasek.py`
Expected: FAIL.

- [ ] **Step 3: Backend**

`dashboard_api.py` — obok `_safe_logistyka_bez_sposobu`:

```python
def _safe_weryfikacja():
    """
    Liczniki Weryfikacji na pasku logistyki (logistyka etap 4, spec 11): {'pending', 'problems'} —
    ta sama definicja co lista telefonu i filtr panelu (weryfikacja.warunek_do_weryfikacji). Wzorzec
    osłony jak _safe_logistyka_bez_sposobu: błąd licznika → None (front zostawia ostatnie liczby).
    """
    from modules.production.logistics.services import weryfikacja
    try:
        return {'pending': weryfikacja.liczba_do_weryfikacji(get_local_now()),
                'problems': weryfikacja.liczba_problemow()}
    except Exception as e:
        logger.warning("Nie udało się policzyć zamówień do weryfikacji", extra={'error': str(e)})
        return None
```

W renderze zakładki (`dashboard_stats['logistics'] = {...}`):

```python
        weryfikacja_liczniki = _safe_weryfikacja() or {}
        dashboard_stats['logistics'] = {
            'pending_count': logistics_pending,
            'verification_pending': weryfikacja_liczniki.get('pending', 0),
            'verification_problems': weryfikacja_liczniki.get('problems', 0),
        }
```

W `response_data` endpointu `dashboard-data` po `'logistics_pending': …`: `'verification': _safe_weryfikacja(),`.

- [ ] **Step 4: Szablon, JS, CSS (skill `frontend-design:frontend-design`)**

W bloku paska logistyki (między znacznikami `LOGISTYKA: pasek pod pipeline'em` i `/LOGISTYKA`) dopisz, w stylu istniejącego licznika, dwa liczniki: „Do weryfikacji: N” (`<strong id="verification-pending">`) i „Problemy: N” (`<strong id="verification-problems">`, wyróżnione, gdy N > 0), wartości z `dashboard_stats.logistics.verification_pending|default(0)` i `verification_problems|default(0)`; link „Otwórz Logistykę” bez zmian. W `dashboard-module.js` w handlerze, który woła `updateLogisticsPending(data.data.logistics_pending)`, dopisz `this.updateVerification(data.data.verification);` i metodę:

```javascript
    /**
     * Liczniki Weryfikacji na pasku logistyki (krok 4.3). null = błąd licznika po stronie serwera —
     * zostają ostatnie liczby (jak updateLogisticsPending).
     */
    updateVerification(dane) {
        if (!dane || typeof dane !== 'object') return;
        const ustaw = (id, liczba) => {
            if (typeof liczba !== 'number' || !Number.isFinite(liczba)) return;
            const el = document.getElementById(id);
            if (el) el.textContent = String(liczba);
        };
        ustaw('verification-pending', dane.pending);
        ustaw('verification-problems', dane.problems);
        const problemy = document.getElementById('verification-problems');
        const blok = problemy ? problemy.closest('.il-logistyka-weryfikacja-problemy') : null;
        if (blok) blok.classList.toggle('is-alarm', (dane.problems || 0) > 0);
    }
```

(nazwy klas dopasuj do zaprojektowanego znacznika; zachowaj `id`). Style w `production-panel.css`. Podbij `?v=` przy `dashboard-module.js` i `production-panel.css` w szablonie, który je ładuje.

- [ ] **Step 5: Testy, pełny pakiet, commit**

Run: `PYTEST tests/test_weryfikacja_dashboard.py tests/test_dashboard_logistyka_pasek.py`, potem `PYTEST tests/`
Expected: PASS, 0 failed.

```bash
git add modules/production/routers/api/dashboard_api.py modules/production/templates \
  modules/production/static/js/modules/dashboard-module.js modules/production/static/css/production-panel.css \
  tests/test_weryfikacja_dashboard.py tests/test_dashboard_logistyka_pasek.py
git commit -m "feat(production): liczniki Do weryfikacji i Problemy na pasku logistyki dashboardu" \
  -m "Pasek pod pipeline'em pokazuje zamowienia do weryfikacji i otwarte problemy, odswiezane razem z dashboard-data (spec 11)." \
  -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 10: MySQL (wyścigi na dwóch sesjach), podgląd, spec i CLAUDE.md

Zadanie dzielone jak Task 7 kroków 4.1–4.2: subagent robi kroki 1–4 i 7–8, kontroler kroki 5–6 z Konradem.

**Files:**
- Create (poza repo): skrypty wyścigów w katalogu podglądu (`C:\Users\Grafik\Documents\woodpower-podglady\logistyka43\` albo `…\logistyka4\kod`, gdy centrala zwolni 5004)
- Modify: `docs/superpowers/specs/2026-09-30-logistyka-etap-4-weryfikacja-dostawa-design.md` (odstępstwa z sekcji „Odstępstwa i doprecyzowania” tego planu)
- Modify: `CLAUDE.md` (punkt „Deklaracje paczek — jedna naraz” w sekcji „Ważne”)

- [ ] **Step 1: Wybór podglądu**

Jeśli centrala potwierdziła koniec testu wydruku 4.2 — podgląd 5004 (`logistyka4-podglad`, baza `logistyka4_podglad`): odświeżenie `git archive HEAD | tar -x -C …/logistyka4/kod` (zachowaj `config/core.json` podglądu i skrypty `_paczki_tablet.py`), `docker restart logistyka4-podglad` — runner wykona migrację 4.3. Jeśli nie — osobny podgląd **5005**: katalog `C:\Users\Grafik\Documents\woodpower-podglady\logistyka43\` (kopia `przygotuj_config.py` i `env.list` z `…\logistyka4`, baza `logistyka43_podglad` = zrzut `logistyka4_podglad` odtworzony jak w Task 1 Step 11), kontener `logistyka43-podglad` z obrazu `logistyka3-app`, `-p 127.0.0.1:5005:5000`, sieć `woodpower-crm_default`, wolumen `…\logistyka43\kod:/app`, polecenie `flask run --host=0.0.0.0 --port=5000`. Zgłoś centrali, który podgląd działa (SendMessage). Nie uruchamiaj agenta druku testowego — etykiety `wysylka` z wyścigów wygaś w bazie podglądu (`UPDATE prod_print_queue SET status='expired' WHERE status='pending' AND printer='wysylka'`).

- [ ] **Step 2: Migracja przez runner**

Log kontenera po restarcie: migracja `2026-09-30-logistyka-weryfikacja.sql` wykonana, bez błędów; `SHOW CREATE TABLE prod_products` z 15 wartościami; `SELECT config_value FROM prod_config WHERE config_key='logistyka_weryfikacja_od'`; drugi ręczny przebieg pliku (`mysql < plik`) bez błędów.

- [ ] **Step 3: Wyścigi na dwóch sesjach MySQL**

Skrypt w katalogu podglądu (`docker exec -w /app <kontener> python _weryfikacja_wyscigi.py <tryb>`), dwa wątki z osobnymi klientami testowymi Flaska (`app.test_client()`), start na wspólnej barierze (`threading.Barrier(2)`), każde z żądań z własnym `X-Operation-Id`, po wyścigu odczyt stanu z bazy. Urządzenia testowe: `PODGLAD-PAKOWANIE` (4.2) i nowe `PODGLAD-WERYFIKACJA` (station `verification`), pracownik z `prod_workers` (nagłówek `X-Worker-Ids`). Tryby, każdy 5 razy, na świeżo spakowanych zamówieniach kopii (zapisz numery w raporcie):

| Tryb | Strona A | Strona B | Oczekiwane |
|---|---|---|---|
| `complete-deklaracja` | `POST /orders/<id>/complete` ostatniej pozycji (pakowanie) | `PUT /orders/<nr>/packages` tego zamówienia | brak 1213 albo 1213 → 500 i ponowienie tym samym op-id = 200; spójny stan |
| `weryfikacja-deklaracja` | `POST /verification/packages/<id>/verify` | `PUT /orders/<nr>/packages` (ponowna deklaracja) | jedna strona 200, druga 200 albo 409; nigdy paczka zweryfikowana w unieważnionej deklaracji przy zamówieniu `zweryfikowane` |
| `dwie-paczki` | verify P-1 | verify P-2 (ostatnie dwie) | zamówienie `zweryfikowane`, dokładnie jeden wpis logu `weryfikacja` |
| `cofniecie-weryfikacja` | `revert-to-packing` | verify ostatniej paczki | końcowo `czeka_na_pakowanie`, paczki unieważnione, `verified_at` NULL |
| `ack-uniewaznienie` | `POST /api/print-agent/jobs/ack` zadań `wysylka` zamówienia | ponowna deklaracja (wygasza `pending`) | brak 1213 albo samonaprawa 500 → ponowienie |
| `hurt-weryfikacja` | hurtowa zmiana statusu pozycji na `czeka_na_pakowanie` (panel, sesja admina w skrypcie przez `login_user`) | verify ostatniej paczki | spójny stan (reguła albo weryfikacja wygrywa, nie oba) |

Po każdym trybie: `grep -c "1213\|Deadlock" <log aplikacji>`, liczba 500, stan zamówień. Wynik do raportu jako tabela. Zakleszczenie powtarzalne (≥ 2/5) → STOP i meldunek do kontrolera (decyzja o poprawce należy do Konrada, jak w 4.2).

- [ ] **Step 4: Skrypt „telefon” do oględzin**

`_weryfikacja_telefon.py` w katalogu podglądu: tryby `lista`, `szczegoly <nr>`, `skan <P-id>`, `wszystkie <nr>`, `cofnij <nr>`, `problem <nr> <powod> [notatka]`, `rozwiaz <nr>`, `do-pakowania <nr> [powod]` — wywołania API telefonu z urządzeniem `PODGLAD-WERYFIKACJA` i pracownikiem z kopii; drukuje odpowiedź w czytelnej postaci. Appka z ekranami Weryfikacji jeszcze nie istnieje.

- [ ] **Step 5: Oględziny z Konradem (kontroler)**

Na podglądzie z Konradem: panel Logistyki (kolumna Etap, paczki, problem, „BEZ PACZEK”, trzy filtry z liczbami), pasek dashboardu, przebieg skryptem: lista → skan paczek → zamówienie zweryfikowane → problem → cofnięcie do pakowania → baner na tablecie pakowania (kolejka `GET /stations/packaging/orders` w skrypcie `_paczki_tablet.py` albo na tablecie testowym, jeśli appka 4.3 będzie gotowa). Uwagi Konrada → dziennik SDD.

- [ ] **Step 6: Decyzje z oględzin (kontroler)** — poprawki tylko na polecenie Konrada (fala poprawek po przeglądzie końcowym).

- [ ] **Step 7: Spec i CLAUDE.md**

- Spec: dopisz odstępstwa z sekcji „Odstępstwa i doprecyzowania” tego planu w sekcjach 4.1, 4.6, 5.2–5.3, 8.1–8.4, 11 (jak w 4.2 — zdanie w tekście z dopiskiem „(krok 4.3)”), decyzje Konrada 2–4 z tego planu i wynik wyścigów MySQL (jedno zdanie w 8).
- `CLAUDE.md`, sekcja „Ważne”, punkt „Deklaracje paczek — jedna naraz”: dopisz „Zapisy telefonu Weryfikacji (`/api/mobile/verification/*`) biorą tę samą blokadę: pracownicy → `paczki.zablokuj_deklaracje()` → zamówienie po PK → paczki → pozycje. Reguła `weryfikacja.uniewaznij_etapy` (powrót pozycji do produkcji) blokady globalnej nie bierze — zapisuje najpierw zamówienie, potem paczki.”

- [ ] **Step 8: Pełny pakiet, kompilacja pod 3.9 i commit dokumentów**

Run: `PYTEST tests/`, potem `docker compose -p logistyka4 run --rm --no-deps app python -m py_compile $(git diff --name-only <BASE_4_3>..HEAD -- '*.py')` (składnia; kod produkcyjny ma działać na Pythonie 3.9 — sprawdź brak `X | Y` w adnotacjach i `match`: `git diff <BASE_4_3>..HEAD -- '*.py' | grep -nE "^\+.*(: [A-Za-z_\[\]]+ \| |-> [A-Za-z_\[\]]+ \| |^\+\s*match )"` → pusto).

```bash
git add -f docs/superpowers/specs/2026-09-30-logistyka-etap-4-weryfikacja-dostawa-design.md
git add CLAUDE.md
git commit -m "docs: krok 4.3 logistyki - odstepstwa od projektu i kolejnosc blokad Weryfikacji" \
  -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```


---

## Wdrożenie kroku 4.3 (poza zadaniami — na polecenie Konrada, po etapach 1–3 i krokach 4.1–4.2)

1. Backend (migracja `2026-09-30-logistyka-weryfikacja.sql` wykona się przed restartem; zapisze chwilę wdrożenia w `logistyka_weryfikacja_od`).
2. Appka z ekranem Weryfikacji i banerem `repack_reason` (plan dla sesji appki: `C:\Users\Grafik\Documents\woodpower-podglady\logistyka4\plan-appki-krok-4-3-weryfikacja.md`). Stara appka działa z nowym backendem: kształt kolejki 5 wymusza jednorazowe pełne pobranie, nowe statusy trafiają do archiwum wyszukiwarki.
3. Telefon biura zarejestrowany na stanowisku `verification`; pracownik biura w `prod_workers` (z dozwolonym stanowiskiem Weryfikacja, jeśli profil ma listę stanowisk).
4. Po wdrożeniu: liczba „Do weryfikacji” na dashboardzie zgodna z listą w telefonie; przepakowanie i doróbka w zamówieniu zweryfikowanym kasują paczki (log `paczki` z powodem).
