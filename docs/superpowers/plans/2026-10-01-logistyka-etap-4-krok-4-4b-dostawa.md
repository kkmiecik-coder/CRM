# Logistyka etap 4, krok 4.4b — stanowisko Dostawa (kierowca) i statusy tras — plan implementacji

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** kierowca na telefonie (stanowisko `delivery`) ładuje paczki swojej trasy, oznacza „Zostaje”, kończy załadunek, rusza w trasę i potwierdza dostarczenia; trasy dostają statusy `zaladowana` i `w_trasie`, transport własny zamyka się po `dostarczone`, a panel tras pokazuje postęp, „Cofnij załadunek”, „Odhacz” ze statusami Base. i „Cofnij dostarczenie” zamiast „Przywróć trasę”.

**Architecture:** Nowy serwis `logistics/services/dostawa.py` trzyma wszystkie przejścia Dostawy (załadunek, „Zostaje”, zakończenie załadunku, wyjazd, dostarczenie, niedostarczenie, cofnięcia) — wspólne dla telefonu i panelu tras, z jedną kolejnością blokad: blokada tras → blokada deklaracji paczek → zamówienia `FOR UPDATE` rosnąco → paczki → pozycje (odczyt bieżący). Telefon dostaje osobny blueprint `/api/mobile/delivery` (`logistics/routers/dostawa_api.py`) z odczytem w `logistics/services/dostawa_widok.py`; panel tras korzysta z tych samych funkcji przez `trasy_api.py`. Reguła zamknięcia transportu (`delivery.zamkniecie_wyliczone`) przestaje czytać trasy — liczy się `dostarczone` na pozycjach.

**Tech Stack:** Flask 2 + SQLAlchemy < 2.0, MySQL 8.4 (produkcja) / SQLite (testy), pytest, vanilla JS, Jinja.

**Spec:** `docs/superpowers/specs/2026-09-30-logistyka-etap-4-weryfikacja-dostawa-design.md` — sekcje 2, 4 (4.2–4.6), 5.4, 5.5, 9 (cała), 11, 12 pkt 1, 4, 6–7, 13, 14 pkt 4, 15, 16. Poprzedni krok: `docs/superpowers/plans/2026-10-01-logistyka-etap-4-krok-4-4a-zamowienie-najpierw.md` (moduł `services/blokady_zamowien.py`, pisarze stanowisk biorą zamówienie przed pozycją). Wzór formatu: plany kroków 4.1–4.3.

## Global Constraints

- Kod zgodny z **Pythonem 3.9** (produkcja): bez `X | Y` w adnotacjach, bez `match`; `typing.Optional/List`.
- Komentarze i docstringi **po polsku**; teksty w UI i komunikaty API po polsku; w UI „Base.” zamiast BaseLinker.
- Błędy API telefonu: `{"error": <kod>, "message": <tekst>}` (+ pola dodatkowe, np. `braki`). Błędy pracownika z `worker_service.WorkerError` w dotychczasowym kształcie `{"error", "detail"}`. Błędy panelu: `{"success": false, "error": <tekst>}` (+ pola dodatkowe), jak w `trasy_api._odmowa`.
- Funkcje serwisów **nie commitują**. API mobilne: commit robi `@with_idempotency(retryable_statuses=BLEDY_DO_PONOWIENIA)`, bez `db.session.commit()` w handlerze. Dopychacz Base. po commicie: telefon przez `bl_sync.zaplanuj_po_commicie(order_id)`, panel przez `bl_sync.po_zmianie(ids)` po commicie w routerze.
- **Kolejność blokad każdego zapisu Dostawy** (telefon i panel tras): pracownicy (`touch_sessions`, tylko telefon) → `routes.zablokuj_trasy(route)` (blokada tras + świeża trasa z przystankami) → `paczki.zablokuj_deklaracje()` → zamówienia CAŁEJ trasy `FOR UPDATE` rosnąco po id (`blokady_zamowien.zablokuj_zamowienia`) → paczki i pozycje każdego zamówienia (`paczki.zablokuj_stan`) → dopiero zapisy; odpowiedź telefonu (pełna trasa) z tych samych blokad (`dostawa_widok.trasa_po_zapisie`). Decyzje na odczycie bieżącym. Nikt nie bierze blokady deklaracji przed blokadą tras.
- Statusy pozycji `zaladowane` i `dostarczone` nadaje wyłącznie Dostawa (i „Wydane klientowi” — `dostarczone` odbioru). Hurtowa zmiana statusu ich nie oferuje (bez zmian od 4.3).
- Statusy Base.: **524520** = `sposoby.STATUS_ZALADOWANE` (po zakończeniu załadunku), **149763** = `STATUS_WYSLANE_TRANSPORT` (po „Ruszam” i po cofnięciu dostarczenia), **149778** = `STATUS_DOSTARCZONE_TRANSPORT` (po dostarczeniu i odhaczeniu), **417343** = `STATUS_PLANOWANA_TRASA` (po cofnięciu załadunku i niedostarczeniu zamówienia, które było załadowane). Wysyłka tylko znacznikiem `bl_status_pending_id` + dopychacz.
- Trasy aktywne (zajętość pojazdu/kierowcy, `trasa_dla_tabletu`, mapa tras): `robocza`, `zatwierdzona`, `zaladowana`, `w_trasie` — jedna stała `STATUSY_TRASY_AKTYWNE`.
- `KSZTALT_ODPOWIEDZI_KOLEJKI` (tablety) **bez zmian** (5) — kolejki tabletów nie dostają nowych pól. Katalog pracowników dostaje `is_driver` i własny segment kształtu ETagu (`KSZTALT_KATALOGU_PRACOWNIKOW = 2`).
- Migracja: `migrations/2026-10-01-logistyka-dostawa.sql`, idempotentna, nowe wartości **na końcu** ENUM-ów, `ALTER` dodające kolumny osłonięte `information_schema` + `PREPARE/EXECUTE`, słowo separatora poleceń nie pada nigdzie w pliku (test). ENUM akcji logu z **pełną** listą (także `paczki` z 4.2 i akcje Weryfikacji z 4.3).
- `tools/print_agent` — bez zmian.
- Testy WYŁĄCZNIE z katalogu worktree zadania: `docker compose -p <projekt> run --rm --no-deps app pytest <ścieżki> -q -p no:cacheprovider`; **nigdy** `docker compose exec`; nie twórz `config/core.json` w worktree. **Najwyżej JEDEN pełny pakiet naraz** (zajmuje ok. 13 GiB z 15,5 GiB pamięci Dockera; dwa naraz = OOM, exit 137) — także między torami równoległymi.
- Podgląd **5004** (`logistyka4-podglad`, baza `logistyka4_podglad`) jest do wyścigów i oględzin tego kroku. **5005 i 5003 — nie ruszać.**
- Front: skill `frontend-design:frontend-design`, istniejący styl zakładek (tokeny `--lg-*`, klasy `lg-*`), dostęp z klawiatury, bez animacji przy `prefers-reduced-motion`. Wersje `?v=` podbite przy każdej zmianie pliku statycznego.
- Commity: Conventional Commits po polsku **bez polskich znaków w temacie**, stopka `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Bez pushu, nigdy do `main`. Spec i plan: `git add -f`.
- Repo publiczne: żadnych sekretów, adresów IP ani uwag bezpieczeństwa w commitowanych plikach.

## Review Focus

1. **Kierowca omyłkowo potwierdza ostatni przystanek** — ostatnie „Dostarczone” zamyka trasę, a telefon musi móc to cofnąć (decyzja Konrada): `test_telefon_cofa_ostatnie_dostarczenie_takze_po_zamknieciu_trasy` (Task 4), `test_api_cofniecie_po_automatycznym_zamknieciu` (Task 6). Odhaczenie z panelu tego nie odblokowuje (`completed_by` ustawione): `test_telefon_nie_cofa_po_odhaczeniu_w_panelu` (Task 4).
2. **Weryfikacja albo doróbka w trakcie załadunku** (paczki już na aucie, trasa jeszcze zatwierdzona) — znaczniki załadunku znikają, a zakończenie załadunku nie przepuści zamówienia, które przestało być zweryfikowane: `test_cofniecie_weryfikacji_czysci_zaladunek`, `test_regula_uniewaznienia_czysci_zaladunek` (Task 2), `test_zakonczenie_odmawia_gdy_zamowienie_przestalo_byc_zweryfikowane` (Task 3).
3. **Trasa z dnia, który minął, nie znika z telefonu w trakcie pracy** — `zaladowana` i `w_trasie` są w „Moich trasach” bez względu na datę: `test_moje_trasy_zakres` (Task 6).
4. **Powtórka z kolejki offline** (ten sam skan, „Ruszam”, „Dostarczone” po raz drugi z nowym `X-Operation-Id`) to 200 bez zmian, nie drugi status Base. ani drugi wpis w logu: `test_ponowny_skan_bez_zmian`, `test_ponowne_ruszam_bez_zmian` (Task 3), `test_ponowne_dostarczenie_bez_zmian` (Task 4).
5. **Zamówienie z przystanku zmienia stan poza Dostawą** (anulowane w całości, cofnięte do pakowania, doróbka po załadunku) — zakończenie załadunku zdejmuje anulowane, przystanek niespakowany i niezweryfikowany blokuje z listą braków, dostarczenie zamówienia, które wróciło do produkcji, dostaje 409: `test_zakonczenie_zdejmuje_anulowane`, `test_zakonczenie_lista_brakow` (Task 3), `test_dostarczenie_zamowienia_spoza_zaladunku_409` (Task 4).

Poza testami SQLite (Task 8, MySQL): kolejność blokad Dostawa ↔ panel tras ↔ Weryfikacja ↔ deklaracja paczek ↔ ZAKOŃCZ ↔ cron na dwóch sesjach.

## Decyzje Konrada (1.10)

1. Krok 4.4 w dwóch planach: 4.4a (zamówienie najpierw — osobny plan, realizowany pierwszy) i 4.4b (ten).
2. **Etapy 3 i 4 wdrażamy jednym wdrożeniem** — w chwili wdrożenia nie ma tras wykonanych, więc jednorazowego przestawienia pozycji z tras wykonanych na `dostarczone` nie robimy (zapis w specu 14, Task 3 kroku 4.4a).
3. **Telefon cofa ostatnie dostarczenie także zaraz po automatycznym zamknięciu trasy** (trasa wraca z `wykonana` do `w_trasie`); odstępstwo od specu 9.5.
4. Akcje automatyczne Base.: jedyna to „Odebrane” → druk KP (ID 292653); statusy Dostawy jej nie wyzwalają.
5. **Zastępstwo kierowcy — tylko zmianą kierowcy w panelu** (przed załadunkiem: cofnij zatwierdzenie → zmień kierowcę → zatwierdź). „Moje trasy” pokazują wyłącznie trasy przypisanego kierowcy, bez parametru „wszystkie trasy” w API. Serwer nadal przyjmuje zapisy na trasie od każdego aktywnego kierowcy (nie szkodzi, appka tego nie wykorzystuje).
6. **Eksport Routimo ze starej zakładki Raporty** (`modules/reports/routers.py`, `excluded_status_ids` bez 417343 i 524520) — zakładka do wyrzucenia, ignorujemy; bez zmian w kodzie (uwaga centrali o podwójnej dostawie przedstawiona Konradowi 1.10).

## Doprecyzowania i odstępstwa (do specu w Task 8)

- **Ścieżki z trasą.** Załadunek i jego cofnięcie: `POST /delivery/routes/<route_id>/packages/<package_id>/load|unload` (spec: `/delivery/packages/<id>/load`) — odmowa `package_not_on_route` potrzebuje trasy, w kontekście której kierowca skanuje. Przystanki po `order_id` (nie po numerze wewnętrznym, który powtarza się co rok).
- **Wszystkie endpointy telefonu wymagają kierowcy** (`X-Worker-Ids`, pierwszy = kierowca), także odczyty — „Moje trasy” to trasy tego kierowcy. Akcje na trasie przyjmujemy od **każdego** aktywnego kierowcy (nie szkodzi); appka pokazuje tylko trasy zalogowanego kierowcy, a zastępstwo załatwia zmiana kierowcy w panelu (decyzja 5).
- **„Moje trasy”**: trasy kierowcy `zatwierdzona` z `date_to >= dziś` oraz **`zaladowana` i `w_trasie` bez względu na datę** (spec: wszystkie z `date_to >= dziś`) — rozpoczęta trasa nie może zniknąć z telefonu o północy. Szczegóły trasy (`GET /delivery/routes/<id>`) także dla `wykonana` (ekran po zamknięciu, cofnięcie ostatniego dostarczenia); trasa robocza → 404.
- **Cofnięcie ostatniego dostarczenia z telefonu** (decyzja 3): trasa `w_trasie`, albo `wykonana` zamknięta automatycznie ostatnim dostarczeniem z telefonu (`completed_by IS NULL`). Trasa odhaczona w panelu (`completed_by` = użytkownik) — tylko panel. „Ostatnie” = przystanek z najpóźniejszym `delivered_at` (remis: wyższa pozycja).
- **„Cofnij dostarczenie” w panelu** (zastępuje „Przywróć trasę”): dowolny dostarczony przystanek trasy `w_trasie` albo `wykonana`; trasa wykonana wraca do `w_trasie`. **Bez sprawdzania zajętości pojazdu i kierowcy** (to korekta, nie planowanie — dawne „Przywróć” sprawdzało).
- **„Odhacz jako wykonaną”** zostaje dostępne także z roboczej (ruling R12 etapu 3; spec 9.7 wymienia zatwierdzona/załadowana/w trasie). Przystanki już dostarczone są zawsze dostarczone (okno pokazuje je zaznaczone i zablokowane). Odznaczony przystanek: zdjęty z trasy, pozycje `zaladowane` → `zweryfikowane`, znaczniki załadunku czyszczone, Base. 417343 **tylko gdy zamówienie było załadowane** (zamówienie z trasy zatwierdzonej ma już 417343 po spakowaniu).
- **Zakończenie załadunku**: przystanek „załadowany” = co najmniej jedna aktualna paczka i wszystkie aktualne paczki załadowane na tę trasę, a pozycje nadal `zweryfikowane` (odczyt bieżący). Przystanek zamówienia anulowanego w całości zdejmujemy z trasy (notatka „anulowane”) zamiast blokować. Braki → 409 `loading_incomplete` z listą `braki` (`niezaladowane`, `niezweryfikowane`, `bez_paczek`); nic załadowanego → 409 `nothing_loaded`.
- **Skan paczki z przystanku „Zostaje”** → 409 `stop_stays` („najpierw zdejmij »Zostaje«”), bez cichego zdejmowania oznaczenia.
- **Log**: `zaladunek` przy zakończeniu załadunku (stara wartość brak → `zaladowane`, notatka: opis paczek) i przy „Cofnij załadunek” (`zaladowane` → brak, notatka „cofnięty w panelu”); `zostaje` przy zdjęciu przystanku z powodem; `wyjazd`; `dostarczone`; `niedostarczone` (notatka: powód i opis); `dostarczenie_cofniete`; zmiany statusu trasy jak dotąd `trasa_status`. Wpis `trasa_usuniete` przy niedostarczeniu ma notatkę `niedostarczone` jak w etapie 3 (powód w osobnym wpisie `niedostarczone`).
- **Eksport Routimo**: `zatwierdzona`, `zaladowana`, `w_trasie` **i `wykonana`** (spec: „bez wykonana — jak dziś”; dziś wykonana jest dozwolona — ruling R11 etapu 3, zostaje).
- **Regula transportu (4.6)**: `zamkniecie_wyliczone` przestaje czytać trasy; parametr `trasa` znika z `zamkniecie_wyliczone`/`przelicz_zamkniecie`. Siatka crona: warunek „transport bez trasy wykonanej” → „transport z aktywną pozycją inną niż `dostarczone`”.
- **Etap „W trasie”** w panelu Logistyki: pozycje `zaladowane`, a trasa zamówienia `w_trasie`. To etap zamówienia na liście (`lista._etap`), nie status pozycji.

## Poza zakresem (celowo)

- Archiwum (`dostarczone` w archiwum pokazuje „Spakowane”) — krok 4.5.
- Doróbka albo nowa pozycja w zamówieniu z pozycjami `dostarczone` — obsługa ręczna (decyzja Konrada 1.10, spec 4.5).
- Cofnięcie „Ruszam” — nie ma (spec go nie przewiduje); pomyłkę logistyk rozlicza „Odhacz”.
- Eksport Routimo ze starej zakładki Raporty — decyzja 6 (zakładka do wyrzucenia, ignorujemy).

## Kontrakt API Dostawy (dla appki i przeglądu)

Prefiks `/api/mobile/delivery`. Wszystkie: `Authorization: Bearer <JWT urządzenia>` (stanowisko `delivery`, inne → 403 `station_not_allowed`) i **`X-Worker-Ids`** (pierwszy = kierowca; brak → 400 `worker_required`; nie kierowca albo nieaktywny → 403 `not_a_driver`; nieznany identyfikator → kody `WorkerError` jak w `complete`). Zapisy: `X-Operation-Id`; 400/403/404/409 **niezapamiętane** (`BLEDY_DO_PONOWIENIA`), 422 zapamiętane. Każdy zapis zwraca pełną trasę (`route`).

| Endpoint | Body | 200 | Błędy |
|---|---|---|---|
| `GET /routes` | — | `{"routes": [TrasaKrotko…], "count": N}` (`no-store`) | 400, 403 |
| `GET /routes/<rid>` | — | `{"route": Trasa}`, `ETag`, `If-None-Match` → 304 | 404 `route_not_found` |
| `POST /routes/<rid>/packages/<pid>/load` | `{"method": "skan"\|"reczne"}` (brak = `skan`) | `{"route", "package": PaczkaDostawy, "changed", "message"}` | 404 `route_not_found`, `package_not_found`; 409 `route_status`, `package_void`, `package_not_on_route`, `order_not_verified`, `stop_stays`; 422 `invalid_method` |
| `POST /routes/<rid>/packages/<pid>/unload` | — | `{"route", "package", "changed", "message"}` | 404; 409 `route_status`, `package_not_on_route` |
| `POST /routes/<rid>/stops/<oid>/stays` | `{"reason", "note"?}` | `{"route", "changed", "message"}` | 404 `route_not_found`, `stop_not_found`; 409 `route_status`; 422 `invalid_reason` |
| `DELETE /routes/<rid>/stops/<oid>/stays` | — | `{"route", "changed", "message"}` | 404; 409 `route_status` |
| `POST /routes/<rid>/finish-loading` | — | `{"route", "removed": [{"order_id", "internal_order_number", "reason"}], "message"}` | 404; 409 `route_status`, `loading_incomplete` (+ `braki`), `nothing_loaded` |
| `POST /routes/<rid>/depart` | — | `{"route", "changed", "message"}` | 404; 409 `route_status` |
| `POST /routes/<rid>/stops/<oid>/delivered` | — | `{"route", "changed", "route_completed", "message"}` | 404; 409 `route_status`, `order_status` |
| `POST /routes/<rid>/stops/<oid>/not-delivered` | `{"reason", "note"?}` | `{"route", "route_completed", "message"}` | 404; 409 `route_status`, `stop_delivered`; 422 `invalid_reason` |
| `POST /routes/<rid>/stops/<oid>/undo-delivered` | — | `{"route", "changed", "message"}` | 404; 409 `route_status`, `not_last_delivery` |

- **TrasaKrotko:** `{"id", "name", "date_from", "date_to", "status", "status_label", "vehicle_name", "stops_total", "stops_delivered", "packages_total", "packages_loaded"}`. `status_label`: „Zatwierdzona”, „Załadowana”, „W trasie”, „Wykonana”.
- **Trasa:** TrasaKrotko + `{"vehicle_registration", "notes", "loaded_at", "departed_at", "completed_at", "completed_by_panel", "stops": [Przystanek…]}` (`completed_by_panel` = trasa odhaczona w panelu — telefon nie cofa wtedy ostatniego dostarczenia).
- **Przystanek:** `{"position", "order_id", "internal_order_number", "client_name", "recipient", "phone", "address": {"street", "postcode", "city", "country_code"}, "geo": null | {"lat", "lng"}, "order_notes", "m3", "weight_kg", "packages": [PaczkaDostawy…], "packages_total", "packages_loaded", "state", "state_label", "problem": null | {"reason", "reason_label", "note"}, "stays": null | {"reason", "reason_label", "note"}, "delivered_at"}`. `position` = numer wśród aktywnych przystanków (anulowany: `null`). `geo` tylko przy punkcie dokładnym (`prod_order_geo.quality = 'dokladna'`). `recipient` = osoba dostawy → firma → klient.
- **state / state_label:** `zweryfikowane` „Zweryfikowane”, `niezweryfikowane` „NIEZWERYFIKOWANE”, `niespakowane` „NIESPAKOWANE”, `problem` „PROBLEM: <powód>”, `zaladowane` „Załadowane”, `dostarczone` „Dostarczone”, `anulowane` „Anulowane”.
- **PaczkaDostawy:** `{"id", "code": "P-<id>", "seq", "kind", "pallet_type", "length_cm", "width_cm", "verified", "loaded", "loaded_at", "loaded_method"}` (`loaded` = załadowana na TĘ trasę).
- Powody „Zostaje”: `niespakowane` „Niespakowane”, `niezweryfikowane` „Niezweryfikowane”, `brak_miejsca` „Brak miejsca”, `uszkodzone` „Uszkodzone”, `inne` „Inne”. Powody „Niedostarczone”: `brak_klienta` „Brak klienta”, `odmowa` „Odmowa przyjęcia”, `brak_dojazdu` „Brak dojazdu”, `uszkodzenie` „Uszkodzenie”, `inne` „Inne”. Notatka opcjonalna, ucinana do 255 znaków.
- `braki` (409 `loading_incomplete`): `[{"order_id", "internal_order_number", "reason": "niezaladowane"|"niezweryfikowane"|"bez_paczek", "loaded", "total"}]`.
- **Katalog pracowników** (`GET /api/mobile/workers`): nowe pole `is_driver`; ETag z segmentem kształtu 2 (jednorazowe pełne pobranie).
- **Nowa appka na starym backendzie:** rejestracja na `delivery` → 400 `invalid_station_code`, a `/api/mobile/delivery/*` → 404 — appka ukrywa Dostawę (jak Weryfikację przed 4.3).

## Środowisko i tory równoległe

- Główny worktree (Git Bash): `cd /c/Users/Grafik/Documents/woodpower-crm/.claude/worktrees/logistyka-etap-4`, gałąź `claude/logistyka-etap-4`, projekt dockera `logistyka4`.
- `PYTEST <ścieżki>` w krokach = `docker compose -p <projekt> run --rm --no-deps app pytest <ścieżki> -q -p no:cacheprovider` z katalogu worktree zadania.
- Punkt wyjścia: koniec kroku 4.4a (`P` passed, 3 skipped — liczba z dziennika 4.4a; plan 4.4a przewiduje 5496). Po każdym zadaniu pełny pakiet: 0 failed, passed = poprzednio + nowe ± testy świadomie zmienione (wymienione w raporcie).
- Tor równoległy: `git worktree add .claude/worktrees/logistyka-etap-4-b<N> -b claude/logistyka-etap-4-b<N> <BASE>` z katalogu głównego repo, własny `-p logistyka4-b<N>`; scalanie cherry-pickiem; po scaleniu pełny pakiet w głównym worktree, usunięcie gałęzi i worktree toru.

| Etap | Główny worktree | Tor równoległy |
|---|---|---|
| 1 | Task 1 (schemat, stanowisko, katalog) | — |
| 2 | Task 2 (statusy tras w istniejącym backendzie) | — |
| 3 | Task 3 (załadunek w serwisie) | — |
| 4 | Task 4 (dostarczenia, reguła transportu, odhaczenie) | — |
| 5 | Task 5 (API panelu tras) | Task 6 (API telefonu) — `…-b6`, `-p logistyka4-b6`, baza = commit Task 4; Task 7 (front) — `…-b7`, `-p logistyka4-b7`, baza = commit Task 4, pisany według kontraktu z Task 5 (pola `postep`, `zaladowana`, `wyjazd`, `odhaczona_w_panelu`, `zamowienie.dostawa`, endpointy `/unload` i `/stops/<oid>/undo-delivered`); skrypt wyścigów Task 8 (`_dostawa_wyscigi.py` poza repo) — przygotowany z wyprzedzeniem według kontraktu, uruchamiany dopiero w Task 8 |
| 6 | scalenie Task 6 i Task 7 cherry-pickiem po Task 5 (Task 7: oględziny na żywym API dopiero po scaleniu) | — |
| 7 | Task 8 (MySQL — tylko odpalenie przygotowanych serii, oględziny, spec) | — |

Przegląd zadania N idzie równolegle z implementerem N+1 (pliki rozłączne). Testy celowane mogą iść w kilku torach naraz; pełne pakiety — najwyżej dwa naraz w całym systemie (po poprawce pamięci pakietu, f8658ffa); wyścigi MySQL tylko na 5004, seria po serii.

## Mapa plików

| Plik | Task | Rola |
|---|---|---|
| `migrations/2026-10-01-logistyka-dostawa.sql` (nowy) | 1 | ENUM statusu trasy (+2), 4 kolumny `prod_routes`, 4 kolumny `prod_route_stops`, ENUM akcji logu (+6) |
| `modules/production/logistics/models.py` | 1 | `STATUSY_TRASY`, `STATUSY_TRASY_AKTYWNE`, kolumny tras i przystanków, `AKCJE_LOGU` |
| `modules/production/logistics/sposoby.py` | 1 | `STATUS_ZALADOWANE` |
| `modules/production/models.py`, `services/station_catalog.py`, `services/mobile_api_service.py` (telemetria) | 1 | stanowisko `delivery` |
| `modules/production/services/worker_service.py`, `routers/mobile_api.py` (katalog) | 1 | `is_driver`, `KSZTALT_KATALOGU_PRACOWNIKOW` |
| `modules/production/logistics/services/delivery.py` | 2, 4 | blokady zmian na trasach załadowanych i w trasie (2); reguła transportu i siatka (4) |
| `modules/production/logistics/services/routes.py` | 2, 3, 4, 5 | etykiety statusów (2); `usun_przystanek` z pracownikiem (3); `wykonaj` → `dostawa.odhacz`, bez `przywroc` (4); postęp w serializacji (5) |
| `modules/production/logistics/services/weryfikacja.py` | 2 | znaczniki załadunku w regule i w cofnięciu weryfikacji |
| `modules/production/logistics/services/lista.py` | 2 | etap „W trasie”, liczba załadowanych paczek |
| `modules/production/logistics/services/bl_sync.py` | 2 | `oznacz_zaladowane`, `oznacz_planowana_trasa` |
| `modules/production/logistics/routers/trasy_api.py` | 2, 4, 5 | kolejność sekcji, Routimo (2); `/complete` przez `dostawa.odhacz`, `/stops/<oid>/undo-delivered` zamiast `/restore`, dopychacz Base. po commicie w `_akcja` (4); `/unload`, postęp i Dostawa przy przystankach (5) |
| `modules/reports/models.py`, `modules/reports/service.py`, `modules/baselinker/routers.py` | 2 | 524520 i 417343 w „Wyprodukowane” i słownikach nazw |
| `modules/production/logistics/services/dostawa.py` (nowy) | 3, 4 | przejścia Dostawy (telefon i panel) |
| `modules/production/logistics/services/dostawa_widok.py` (nowy), `logistics/routers/dostawa_api.py` (nowy), `app.py`, `tests/logistyka_fixtures.py` | 6 | API telefonu |
| `modules/production/logistics/static/js/{logistics-routes,logistics,logistics-map}.js`, `static/css/{logistics-trasy,logistics}.css`, `templates/logistics/tab_content.html` | 7 | front |
| `CLAUDE.md`, spec | 8 | kolejność blokad Dostawy, odstępstwa, wyniki |

---

### Task 1: Schemat, stanowisko Dostawa i znacznik kierowcy w katalogu

**Files:**
- Create: `migrations/2026-10-01-logistyka-dostawa.sql`
- Modify: `modules/production/logistics/models.py` (`AKCJE_LOGU` :10-15, `STATUSY_TRASY` :57-59, `Route` :76-106, `RouteStop` :109-120)
- Modify: `modules/production/logistics/sposoby.py:30-37`
- Modify: `modules/production/models.py:1158-1169` (`VALID_STATION_CODES`)
- Modify: `modules/production/services/station_catalog.py:37-52` (`STATION_LABELS`)
- Modify: `modules/production/services/mobile_api_service.py:263-266` (`_STATION_CODES_WITH_TABLETS`)
- Modify: `modules/production/services/worker_service.py:255-278` (`serialize_worker_for_mobile`)
- Modify: `modules/production/routers/mobile_api.py:124-137` (stała), `:1337-1339` (ETag katalogu)
- Modify: `modules/production/logistics/services/fleet.py` (docstringi o trasach aktywnych: :90-95, :148-152, :165-166)
- Modify (testy pinujące zbiory): `tests/test_device_telemetry.py:120`, `tests/test_katalog_stanowisk_krawedzie.py:92-94`, `tests/test_krawedzie_model.py:306-318`, `tests/test_weryfikacja_schemat.py:64-66` i `:83`, `tests/test_paczki_schemat.py:90-96`
- Test: `tests/test_dostawa_schemat.py`

**Interfaces:**
- Produces: `STATUSY_TRASY = ('robocza', 'zatwierdzona', 'wykonana', 'zaladowana', 'w_trasie')`, `STATUSY_TRASY_AKTYWNE = ('robocza', 'zatwierdzona', 'zaladowana', 'w_trasie')`; `Route.loaded_at`, `.loaded_by_worker_id`, `.departed_at`, `.departed_by_worker_id`; `RouteStop.delivered_at`, `.delivered_by_worker_id`, `.stays_reason`, `.stays_note`; akcje logu `zaladunek`, `zostaje`, `wyjazd`, `dostarczone`, `niedostarczone`, `dostarczenie_cofniete`; `sposoby.STATUS_ZALADOWANE = 524520`; stanowisko `'delivery'` („Dostawa”); `serialize_worker_for_mobile(...)['is_driver']`; `mobile_api.KSZTALT_KATALOGU_PRACOWNIKOW = 2`.

- [ ] **Step 0: Punkt wyjścia**

Run: `PYTEST tests/`
Expected: `P passed, 3 skipped` (P = wynik końca kroku 4.4a).

- [ ] **Step 1: Testy, które padną**

Create `tests/test_dostawa_schemat.py`:

```python
# -*- coding: utf-8 -*-
"""Schemat kroku 4.4 (logistyka etap 4, spec 5.4, 5.5 i 9.1): statusy tras załadowana i w trasie, kolumny
załadunku, wyjazdu, dostarczenia i „Zostaje”, akcje logu Dostawy, status Base. „Załadowane”, stanowisko Dostawa
i znacznik kierowcy w katalogu pracowników."""
import os
import re
from datetime import date, datetime

from extensions import db
from migrations.migration_service import MigrationService
from modules.production.logistics import sposoby
from modules.production.logistics.models import (
    AKCJE_LOGU, STATUSY_TRASY, STATUSY_TRASY_AKTYWNE, Route, RouteStop,
)
from modules.production.models import ProductionDevice
from modules.production.routers import mobile_api
from modules.production.services.mobile_api_service import _STATION_CODES_WITH_TABLETS, generate_token
from modules.production.services.station_catalog import STATION_LABELS, STATION_ORDER
from tests.logistyka_fixtures import app, client, kierowca, pracownik, zamowienie  # noqa: F401

MIGRACJA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        'migrations', '2026-10-01-logistyka-dostawa.sql')
AKCJE_DO_4_3 = ['sposob_dostawy', 'wydane', 'przepakowanie', 'trasa_dodane', 'trasa_usuniete', 'trasa_status',
                'adres', 'paczki', 'weryfikacja', 'weryfikacja_cofnieta', 'problem', 'problem_rozwiazany',
                'cofniete_do_pakowania']
AKCJE_DOSTAWY = ['zaladunek', 'zostaje', 'wyjazd', 'dostarczone', 'niedostarczone', 'dostarczenie_cofniete']


def _polecenia():
    with open(MIGRACJA, encoding='utf-8') as f:
        sql = f.read()
    return sql, [' '.join(p.split()) for p in MigrationService.split_statements(sql)]


def _wartosci(polecenie):
    return re.findall(r"'([a-z_]+)'", polecenie.split('ENUM(', 1)[1].split(')', 1)[0])


def test_statusy_tras_nowe_na_koncu_i_aktywne():
    assert STATUSY_TRASY == ('robocza', 'zatwierdzona', 'wykonana', 'zaladowana', 'w_trasie')
    assert STATUSY_TRASY_AKTYWNE == ('robocza', 'zatwierdzona', 'zaladowana', 'w_trasie')
    assert list(Route.status.type.enums) == list(STATUSY_TRASY)


def test_akcje_logu_dostawy_na_koncu():
    assert list(AKCJE_LOGU) == AKCJE_DO_4_3 + AKCJE_DOSTAWY


def test_statusy_base_dostawy():
    assert sposoby.STATUS_ZALADOWANE == 524520
    assert (sposoby.STATUS_PLANOWANA_TRASA, sposoby.STATUS_WYSLANE_TRANSPORT,
            sposoby.STATUS_DOSTARCZONE_TRANSPORT) == (417343, 149763, 149778)


def test_kolumny_trasy_i_przystanku(app):
    chwila = datetime(2026, 10, 2, 7, 30)
    trasa = Route(name=u'Rzeszów', date_from=date(2026, 10, 2), date_to=date(2026, 10, 2), status='w_trasie',
                  loaded_at=chwila, loaded_by_worker_id=3, departed_at=chwila, departed_by_worker_id=4)
    db.session.add(trasa)
    db.session.flush()
    order = zamowienie()
    db.session.add(RouteStop(route_id=trasa.id, order_id=order.id, position=1, delivered_at=chwila,
                             delivered_by_worker_id=5, stays_reason='brak_miejsca', stays_note=u'za długie'))
    db.session.commit()
    db.session.expire_all()
    t = Route.query.get(trasa.id)
    s = t.stops[0]
    assert (t.status, t.loaded_at, t.loaded_by_worker_id, t.departed_at, t.departed_by_worker_id) == \
        ('w_trasie', chwila, 3, chwila, 4)
    assert (s.delivered_at, s.delivered_by_worker_id, s.stays_reason, s.stays_note) == \
        (chwila, 5, 'brak_miejsca', u'za długie')


def test_migracja():
    sql, polecenia = _polecenia()
    trasy = next(p for p in polecenia if p.startswith('ALTER TABLE prod_routes MODIFY COLUMN status'))
    assert _wartosci(trasy) == list(STATUSY_TRASY)
    assert 'COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT' in trasy
    log = next(p for p in polecenia if p.startswith('ALTER TABLE prod_logistics_log MODIFY action'))
    assert _wartosci(log) == list(AKCJE_LOGU)   # pełna lista: brakująca wartość skasowałaby akcję wpisom w logu
    for tabela, kolumna in (('prod_routes', 'loaded_at DATETIME NULL'),
                            ('prod_routes', 'loaded_by_worker_id INT NULL'),
                            ('prod_routes', 'departed_at DATETIME NULL'),
                            ('prod_routes', 'departed_by_worker_id INT NULL'),
                            ('prod_route_stops', 'delivered_at DATETIME NULL'),
                            ('prod_route_stops', 'delivered_by_worker_id INT NULL'),
                            ('prod_route_stops', 'stays_reason VARCHAR(32) NULL'),
                            ('prod_route_stops', 'stays_note VARCHAR(255) NULL')):
        assert 'ALTER TABLE %s ADD COLUMN %s' % (tabela, kolumna) in sql, kolumna
    assert sql.count('FROM information_schema.COLUMNS') == 8
    assert sql.count('PREPARE krok FROM @sql') == 8
    assert 'DELIMITER' not in sql.upper()


def test_stanowisko_dostawy_w_katalogu():
    assert 'delivery' in ProductionDevice.VALID_STATION_CODES
    assert STATION_LABELS['delivery'] == 'Dostawa'
    assert 'delivery' not in STATION_ORDER
    assert 'delivery' in _STATION_CODES_WITH_TABLETS


def test_rejestracja_telefonu_dostawy(app, client):
    r = client.post('/api/mobile/register', json={'device_id': 'TEL-KIEROWCA-1', 'device_name': 'Telefon kierowcy',
                                                  'station_code': 'delivery'})
    assert r.status_code == 200, r.get_data()[:300]
    assert r.get_json()['station_code'] == 'delivery'


def test_katalog_pracownikow_ma_znacznik_kierowcy_i_nowy_ksztalt(app, client):
    k, p = kierowca(), pracownik()
    device = ProductionDevice(device_id='TEL-DOSTAWA-KAT', device_name='Telefon', station_code='delivery')
    db.session.add(device)
    db.session.commit()
    r = client.get('/api/mobile/workers', headers={'Authorization': 'Bearer ' + generate_token(device)})
    assert r.status_code == 200, r.get_data()[:300]
    profile = {w['id']: w for w in r.get_json()['workers']}
    assert profile[k.id]['is_driver'] is True and profile[p.id]['is_driver'] is False
    assert mobile_api.KSZTALT_KATALOGU_PRACOWNIKOW == 2
    # Nowe pole nie zmienia danych, z których liczy się ETag. Bez segmentu kształtu telefon z zapamiętanym
    # katalogiem dostawałby 304 i nie zobaczyłby is_driver (bramka Dostawy pokazuje tylko kierowców).
    assert r.headers['ETag'].startswith('W/"workers:2:')
```

- [ ] **Step 2: Testy padają**

Run: `PYTEST tests/test_dostawa_schemat.py`
Expected: FAIL (import przechodzi — wszystkie importowane nazwy już istnieją): `test_statusy_tras_nowe_na_koncu_i_aktywne` i `test_akcje_logu_dostawy_na_koncu` na asercjach; `test_statusy_base_dostawy` — `AttributeError: STATUS_ZALADOWANE`; `test_migracja` — `FileNotFoundError`; `test_kolumny_trasy_i_przystanku` — `TypeError` (nieznane kolumny); `test_stanowisko_dostawy_w_katalogu`; `test_rejestracja_telefonu_dostawy` (400 `invalid_station_code`); `test_katalog_pracownikow_ma_znacznik_kierowcy_i_nowy_ksztalt` (`KeyError: 'is_driver'`).

- [ ] **Step 3: Migracja**

Create `migrations/2026-10-01-logistyka-dostawa.sql`:

```sql
-- Logistyka etap 4, krok 4.4 (spec 2026-09-30-logistyka-etap-4-weryfikacja-dostawa-design.md, sekcje 5.4, 5.5 i 9):
-- statusy tras załadowana i w trasie, kto i kiedy załadował trasę i ruszył, dostarczenie i „Zostaje” na
-- przystanku, akcje logu Dostawy. Idempotentna: MODIFY enumów jest idempotentny sam z siebie, ALTER dodające
-- kolumny osłonięte warunkiem z information_schema przez PREPARE/EXECUTE (bez zmiany separatora poleceń).

-- Nowe wartości NA KOŃCU listy: MySQL 8 zmienia wtedy same metadane (bez przebudowy tabeli). Stary kod w oknie
-- wdrożenia (migracja idzie przed restartem) tych wartości nie zapisuje, a tras z nimi jeszcze nie ma.
ALTER TABLE prod_routes MODIFY COLUMN status
    ENUM('robocza','zatwierdzona','wykonana','zaladowana','w_trasie')
    CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'robocza';

-- Trasa: kto i kiedy zakończył załadunek i ruszył (telefon kierowcy — pracownik, nie użytkownik panelu).
SET @brak = (SELECT COUNT(*) = 0 FROM information_schema.COLUMNS
             WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'prod_routes' AND COLUMN_NAME = 'loaded_at');
SET @sql = IF(@brak, 'ALTER TABLE prod_routes ADD COLUMN loaded_at DATETIME NULL',
              'SELECT "loaded_at juz jest" AS info');
PREPARE krok FROM @sql; EXECUTE krok; DEALLOCATE PREPARE krok;

SET @brak = (SELECT COUNT(*) = 0 FROM information_schema.COLUMNS
             WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'prod_routes' AND COLUMN_NAME = 'loaded_by_worker_id');
SET @sql = IF(@brak, 'ALTER TABLE prod_routes ADD COLUMN loaded_by_worker_id INT NULL',
              'SELECT "loaded_by_worker_id juz jest" AS info');
PREPARE krok FROM @sql; EXECUTE krok; DEALLOCATE PREPARE krok;

SET @brak = (SELECT COUNT(*) = 0 FROM information_schema.COLUMNS
             WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'prod_routes' AND COLUMN_NAME = 'departed_at');
SET @sql = IF(@brak, 'ALTER TABLE prod_routes ADD COLUMN departed_at DATETIME NULL',
              'SELECT "departed_at juz jest" AS info');
PREPARE krok FROM @sql; EXECUTE krok; DEALLOCATE PREPARE krok;

SET @brak = (SELECT COUNT(*) = 0 FROM information_schema.COLUMNS
             WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'prod_routes' AND COLUMN_NAME = 'departed_by_worker_id');
SET @sql = IF(@brak, 'ALTER TABLE prod_routes ADD COLUMN departed_by_worker_id INT NULL',
              'SELECT "departed_by_worker_id juz jest" AS info');
PREPARE krok FROM @sql; EXECUTE krok; DEALLOCATE PREPARE krok;

-- Przystanek: dostarczenie (kto i kiedy) i czasowe „Zostaje” z powodem do zakończenia załadunku.
SET @brak = (SELECT COUNT(*) = 0 FROM information_schema.COLUMNS
             WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'prod_route_stops' AND COLUMN_NAME = 'delivered_at');
SET @sql = IF(@brak, 'ALTER TABLE prod_route_stops ADD COLUMN delivered_at DATETIME NULL',
              'SELECT "delivered_at juz jest" AS info');
PREPARE krok FROM @sql; EXECUTE krok; DEALLOCATE PREPARE krok;

SET @brak = (SELECT COUNT(*) = 0 FROM information_schema.COLUMNS
             WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'prod_route_stops' AND COLUMN_NAME = 'delivered_by_worker_id');
SET @sql = IF(@brak, 'ALTER TABLE prod_route_stops ADD COLUMN delivered_by_worker_id INT NULL',
              'SELECT "delivered_by_worker_id juz jest" AS info');
PREPARE krok FROM @sql; EXECUTE krok; DEALLOCATE PREPARE krok;

SET @brak = (SELECT COUNT(*) = 0 FROM information_schema.COLUMNS
             WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'prod_route_stops' AND COLUMN_NAME = 'stays_reason');
SET @sql = IF(@brak, 'ALTER TABLE prod_route_stops ADD COLUMN stays_reason VARCHAR(32) NULL',
              'SELECT "stays_reason juz jest" AS info');
PREPARE krok FROM @sql; EXECUTE krok; DEALLOCATE PREPARE krok;

SET @brak = (SELECT COUNT(*) = 0 FROM information_schema.COLUMNS
             WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'prod_route_stops' AND COLUMN_NAME = 'stays_note');
SET @sql = IF(@brak, 'ALTER TABLE prod_route_stops ADD COLUMN stays_note VARCHAR(255) NULL',
              'SELECT "stays_note juz jest" AS info');
PREPARE krok FROM @sql; EXECUTE krok; DEALLOCATE PREPARE krok;

-- Log logistyki: akcje Dostawy. Lista MUSI zawierać wszystkie dotychczasowe wartości (kroki 4.2 i 4.3) — MODIFY
-- podaje pełną listę, a brakująca wartość skasowałaby akcję wpisom w logu.
ALTER TABLE prod_logistics_log MODIFY action
    ENUM('sposob_dostawy','wydane','przepakowanie',
         'trasa_dodane','trasa_usuniete','trasa_status','adres','paczki',
         'weryfikacja','weryfikacja_cofnieta','problem','problem_rozwiazany','cofniete_do_pakowania',
         'zaladunek','zostaje','wyjazd','dostarczone','niedostarczone','dostarczenie_cofniete')
    COLLATE utf8mb4_unicode_ci NOT NULL;
```

- [ ] **Step 4: Modele i stałe**

Modify `modules/production/logistics/models.py`:

`AKCJE_LOGU` (linie 10-15):
```python
AKCJE_LOGU = ('sposob_dostawy', 'wydane', 'przepakowanie',
              'trasa_dodane', 'trasa_usuniete', 'trasa_status', 'adres',
              'paczki',
              # Weryfikacja (logistyka etap 4, krok 4.3).
              'weryfikacja', 'weryfikacja_cofnieta', 'problem', 'problem_rozwiazany',
              'cofniete_do_pakowania',
              # Dostawa (logistyka etap 4, krok 4.4).
              'zaladunek', 'zostaje', 'wyjazd', 'dostarczone', 'niedostarczone', 'dostarczenie_cofniete')
```

`STATUSY_TRASY` (linie 57-59):
```python
# Kolejność jak w ENUM bazy (nowe wartości dopisane na końcu migracją kroku 4.4); cykl trasy:
# robocza → zatwierdzona → zaladowana → w_trasie → wykonana.
STATUSY_TRASY = ('robocza', 'zatwierdzona', 'wykonana', 'zaladowana', 'w_trasie')
# Trasy, które widzi tablet i które blokują pojazd/kierowcę (jeszcze nie wykonane). Krok 4.4: także
# załadowana (kierowca zakończył załadunek) i w trasie (kierowca ruszył).
STATUSY_TRASY_AKTYWNE = ('robocza', 'zatwierdzona', 'zaladowana', 'w_trasie')
```

`Route` — docstring i kolumny (po `completed_by = Column(Integer)`):
```python
class Route(db.Model):
    """Trasa transportu własnego: Robocza → Zatwierdzona → Załadowana → W trasie → Wykonana."""
```
```python
    completed_by = Column(Integer)
    # Dostawa (krok 4.4): zakończenie załadunku i wyjazd — pracownik z telefonu kierowcy.
    loaded_at = Column(DateTime)
    loaded_by_worker_id = Column(Integer)
    departed_at = Column(DateTime)
    departed_by_worker_id = Column(Integer)
```

`RouteStop` (po `position = Column(Integer, nullable=False)`):
```python
    position = Column(Integer, nullable=False)
    # Dostawa (krok 4.4): dostarczenie (kto i kiedy) oraz czasowe „Zostaje” z powodem — do zakończenia
    # załadunku, które zdejmuje taki przystanek z trasy (dostawa.POWODY_ZOSTAJE).
    delivered_at = Column(DateTime)
    delivered_by_worker_id = Column(Integer)
    stays_reason = Column(String(32))
    stays_note = Column(String(255))
```

Modify `modules/production/logistics/sposoby.py` (linie 30-37):
```python
STATUS_PRODUKCJA_ZAKONCZONA = 138620
STATUS_SPAKOWANE = 138623
STATUS_PLANOWANA_TRASA = 417343
STATUS_CZEKA_NA_ODBIOR = 149777
STATUS_ODEBRANE = 149779
# Transport własny — stanowisko Dostawa (krok 4.4): „Załadowane - trans. WoodPower” po zakończeniu załadunku
# (status założony w Base. 30.09.2026), „Wysłane - trans. WoodPower” po „Ruszam”, „Dostarczona” po dostarczeniu.
STATUS_ZALADOWANE = 524520
STATUS_WYSLANE_TRANSPORT = 149763
STATUS_DOSTARCZONE_TRANSPORT = 149778
```

- [ ] **Step 5: Stanowisko Dostawa**

`modules/production/models.py`, `VALID_STATION_CODES` — po linii z `'verification'`:
```python
        'verification',  # Weryfikacja paczek (logistyka etap 4) — telefon biura, poza pipeline'em produktów
        'delivery',      # Dostawa (logistyka etap 4, krok 4.4) — telefon kierowcy, poza pipeline'em produktów
```

`modules/production/services/station_catalog.py`, `STATION_LABELS` — po `'verification': 'Weryfikacja',`:
```python
    # Logistyka etap 4, krok 4.4 — telefon kierowcy (załadunek, wyjazd, dostarczenia). Jak Weryfikacja:
    # poza STATION_ORDER, ale z nazwą, bo kierowca ma tu sesję.
    'delivery': 'Dostawa',
```

`modules/production/services/mobile_api_service.py`, `_STATION_CODES_WITH_TABLETS`:
```python
_STATION_CODES_WITH_TABLETS = (
    'cutting', 'assembly', 'gluing', 'formatting', 'edges', 'painting',
    'packaging', 'sawmill', 'verification', 'delivery',
)
```

- [ ] **Step 6: Znacznik kierowcy w katalogu**

`modules/production/services/worker_service.py`, `serialize_worker_for_mobile` — w słowniku po `'sort_order'`:
```python
        'sort_order': worker.sort_order or 0,
        # Logistyka etap 4, krok 4.4: bramka stanowiska Dostawa pokazuje tylko kierowców (Flota → Kierowcy).
        'is_driver': bool(worker.is_driver),
```

`modules/production/routers/mobile_api.py` — pod `KSZTALT_ODPOWIEDZI_KOLEJKI = 5`:
```python

# Wersja KSZTAŁTU katalogu pracowników (GET /workers) — część ETagu, jak KSZTALT_ODPOWIEDZI_KOLEJKI.
# ETag katalogu liczy się z MAX(prod_workers.updated_at) i odcisku konfiguracji, więc nowe pole bez tego
# segmentu nie dotarłoby do urządzeń z zapamiętanym katalogiem (304). PODBIJ przy każdej zmianie zestawu pól
# w worker_service.serialize_worker_for_mobile().
#   2 — 2026-10-01: `is_driver` (logistyka etap 4, krok 4.4 — bramka stanowiska Dostawa)
KSZTALT_KATALOGU_PRACOWNIKOW = 2
```
i w `workers_catalog`:
```python
    etag = make_weak_etag('workers', KSZTALT_KATALOGU_PRACOWNIKOW, station_code,
                          worker_service.get_catalog_version(),
                          worker_service.get_config_fingerprint())
```

- [ ] **Step 7: Docstringi floty i testy pinujące zbiory**

`modules/production/logistics/services/fleet.py`: w docstringach `_podbij_trasy_pojazdu` (ok. :90-95), `trasy_kierowcow` (:148-152) i `kierowcy_z_trasami` (:165-166) zamień „ROBOCZYCH/ZATWIERDZONYCH” / „robocze i zatwierdzone” na „aktywnych (robocza, zatwierdzona, załadowana, w trasie — STATUSY_TRASY_AKTYWNE)”. Kod bez zmian.

`tests/test_device_telemetry.py:120`:
```python
    assert set(result.keys()) == set(STATION_ORDER) | {'sawmill', 'verification', 'delivery'}
```
`tests/test_katalog_stanowisk_krawedzie.py:92-94`:
```python
    # Weryfikacja i Dostawa (logistyka etap 4) — telefony, poza pipeline'em produktów.
    assert set(STATION_LABELS) == set(STATION_ORDER) | {'sawmill', 'verification', 'delivery'}
```
`tests/test_krawedzie_model.py:306-318` — nazwa i zbiór:
```python
def test_zbior_kodow_urzadzen_ma_dokladnie_jedenascie_wpisow():
    ...  # docstring bez zmian
    assert ProductionDevice.VALID_STATION_CODES == {
        'packaging', 'cutting', 'assembly', 'gluing', 'formatting',
        'edges', 'painting', 'finishing', 'sawmill',
        'verification',   # Weryfikacja paczek (logistyka etap 4, krok 4.3)
        'delivery',       # Dostawa (logistyka etap 4, krok 4.4)
    }
```
`tests/test_weryfikacja_schemat.py` — `test_akcje_logu_weryfikacji` i linia 83 w `test_migracja`:
```python
def test_akcje_logu_weryfikacji():
    # Akcje Dostawy (krok 4.4) dochodzą na końcu — pilnuje ich tests/test_dostawa_schemat.py.
    assert list(AKCJE_LOGU)[:13] == STARE_AKCJE + ['weryfikacja', 'weryfikacja_cofnieta', 'problem',
                                                   'problem_rozwiazany', 'cofniete_do_pakowania']
```
```python
    # Migracja kroku 4.3 zna akcje do 4.3; akcje Dostawy dopisuje 2026-10-01-logistyka-dostawa.sql.
    assert _wartosci(log) == list(AKCJE_LOGU)[:13]
```
`tests/test_paczki_schemat.py:90-96`:
```python
    # Akcje z kroków 4.3 i 4.4 dopisują migracje 2026-09-30-logistyka-weryfikacja.sql
    # i 2026-10-01-logistyka-dostawa.sql — ta migracja zna tylko akcje do kroku 4.2.
    akcje_po_4_2 = ('weryfikacja', 'weryfikacja_cofnieta', 'problem', 'problem_rozwiazany',
                    'cofniete_do_pakowania', 'zaladunek', 'zostaje', 'wyjazd', 'dostarczone',
                    'niedostarczone', 'dostarczenie_cofniete')
    for akcja in AKCJE_LOGU:
        if akcja not in akcje_po_4_2:
            assert "'%s'" % akcja in enum, akcja
```

- [ ] **Step 8: Testy przechodzą, MySQL**

Run: `PYTEST tests/test_dostawa_schemat.py tests/test_weryfikacja_schemat.py tests/test_paczki_schemat.py tests/test_device_telemetry.py tests/test_katalog_stanowisk_krawedzie.py tests/test_krawedzie_model.py tests/test_worker_profiles.py tests/test_mobile_api_alias_krawedzi.py`
Expected: PASS.

Migracja na MySQL (kontener `db` lokalnego dockera, osobna baza testowa — NIE `logistyka4_podglad` i NIE `logistyka43_podglad`): utwórz bazę `logistyka44_migracja` ze zrzutu struktury `logistyka4_podglad` (`mysqldump --no-data`), wykonaj plik dwa razy (`mysql logistyka44_migracja < migrations/2026-10-01-logistyka-dostawa.sql`), zapisz czasy i `SHOW CREATE TABLE prod_routes` / `prod_route_stops` / `prod_logistics_log` w raporcie (pierwszy przebieg: dodane kolumny; drugi: komunikaty „juz jest”), potem `DROP DATABASE logistyka44_migracja`. Jeśli baza `logistyka4_podglad` nie ma jeszcze tabel etapu 3 albo 4.3 (podgląd na starszym kodzie), wykonaj wcześniej w kolejności nazw pliki migracji `2026-09-2*` i `2026-09-30-*` z repo na tej samej bazie testowej.

- [ ] **Step 9: Pełny pakiet**

Run: `PYTEST tests/`
Expected: `P + 8 passed, 3 skipped`. Testy zmienione świadomie (wymień w raporcie): 5 plików ze Step 7.

- [ ] **Step 10: Commit**

```bash
git add migrations/2026-10-01-logistyka-dostawa.sql modules/production/logistics/models.py \
  modules/production/logistics/sposoby.py modules/production/models.py \
  modules/production/services/station_catalog.py modules/production/services/mobile_api_service.py \
  modules/production/services/worker_service.py modules/production/routers/mobile_api.py \
  modules/production/logistics/services/fleet.py tests/test_dostawa_schemat.py tests/test_device_telemetry.py \
  tests/test_katalog_stanowisk_krawedzie.py tests/test_krawedzie_model.py tests/test_weryfikacja_schemat.py \
  tests/test_paczki_schemat.py
git commit -m "feat(production): schemat Dostawy - statusy tras, przystanki, stanowisko kierowcy" \
  -m "Krok 4.4 logistyki: trasy zaladowana i w_trasie, kolumny zaladunku, wyjazdu, dostarczenia i Zostaje, akcje logu Dostawy, status Base. Zaladowane (524520), stanowisko delivery i is_driver w katalogu pracownikow (ksztalt ETagu 2)." \
  -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---
### Task 2: Statusy tras załadowana i w trasie w istniejącym backendzie

**Files:**
- Create: `tests/dostawa_pomocnicze.py`, `tests/test_dostawa_statusy_tras.py`
- Modify: `modules/production/logistics/services/delivery.py:145-184` (`_przystanek_do_zmiany`)
- Modify: `modules/production/logistics/services/routes.py:1-9` (docstring modułu), `:243-247` (`_wymagaj_statusu`)
- Modify: `modules/production/logistics/routers/trasy_api.py:26` (`KOLEJNOSC_STATUSOW`), `:474-496` (`route_routimo`)
- Modify: `modules/production/logistics/services/paczki.py` (nowa `wyczysc_zaladunek`)
- Modify: `modules/production/logistics/services/weryfikacja.py:245-305` (`uniewaznij_etapy`), `:479-497` (`cofnij_weryfikacje_zamowienia`) i funkcja cofnięcia weryfikacji jednej paczki (z sesji kroku 4.3, nazwa w briefie)
- Modify: `modules/production/logistics/services/lista.py:95-100` (`_etap`), `:224-272` (`serializuj`)
- Modify: `modules/production/logistics/services/bl_sync.py:478-485`
- Modify: `modules/reports/models.py:685-703`, `modules/reports/service.py:30-49`, `modules/baselinker/routers.py:544-562`

**Interfaces:**
- Consumes (Task 1): nowe statusy tras, kolumny załadunku paczek (`loaded_*`, z kroku 4.2), `sposoby.STATUS_ZALADOWANE`.
- Produces: `paczki.wyczysc_zaladunek(lista) -> int` (liczba paczek, które były załadowane); `bl_sync.oznacz_zaladowane(order)`, `oznacz_wyslane(order)`, `oznacz_dostarczone(order)`, `oznacz_planowana_trasa(order)`; `lista.serializuj(...)['etap']` może mieć `{'status': 'w_trasie', 'nazwa': 'W trasie'}`; `lista.serializuj(...)['paczki']` z polem `zaladowane`; `tests/dostawa_pomocnicze.py`: `T0`, `DZIEN`, `zamowienie_z_paczkami(statusy=('zweryfikowane', 'zweryfikowane'), paczek=2, zweryfikowane=True, sposob=TRANSPORT, **kolumny) -> (order, [paczki])`, `trasa(zamowienia, status='zatwierdzona', kierowca_id=None, nazwa=None, od=DZIEN, do=None, **kolumny) -> Route`, `zaladuj_wprost(paczki, trasa_, kto_id=None, chwila=T0)`, `telefon_kierowcy() -> (device, kierowca)`, `naglowki(device, kto=None, op_id=None) -> dict`.

- [ ] **Step 1: Pomocnik testów Dostawy**

Create `tests/dostawa_pomocnicze.py`:

```python
# -*- coding: utf-8 -*-
"""Wspólne dane testów Dostawy (logistyka etap 4, krok 4.4): zamówienie z paczkami, trasa z przystankami,
paczki załadowane wprost, telefon kierowcy i jego nagłówki. Importuj razem z fiksturami:

    from tests.dostawa_pomocnicze import T0, DZIEN, trasa, zamowienie_z_paczkami
    from tests.logistyka_fixtures import app, client  # noqa: F401
"""
import itertools
from datetime import date, datetime

from extensions import db
from modules.production.logistics import sposoby as s
from modules.production.logistics.models import Route, RouteStop
from modules.production.models import ProductionDevice, ProductionPackage
from modules.production.services.mobile_api_service import generate_token
from tests.logistyka_fixtures import kierowca, zamowienie

T0 = datetime(2026, 10, 1, 8, 0)
# W granicach dat tras: „dziś” tras w testach to 26.09.2026 (tests/logistyka_fixtures.DZIS_TESTOW).
DZIEN = date(2026, 10, 1)
_licznik = itertools.count(1)


def zamowienie_z_paczkami(statusy=('zweryfikowane', 'zweryfikowane'), paczek=2, zweryfikowane=True,
                          sposob=s.TRANSPORT, **kolumny):
    """Zamówienie (domyślnie transport własny) z `paczek` aktualnymi paczkami, domyślnie sprawdzonymi."""
    order = zamowienie(sposob=sposob, statusy=statusy, packages_declared_at=T0,
                       verified_at=T0 if zweryfikowane else None, **kolumny)
    lista = [ProductionPackage(order_id=order.id, seq=i, kind='paczka', declared_at=T0,
                               verified_at=T0 if zweryfikowane else None,
                               verified_method='skan' if zweryfikowane else None)
             for i in range(1, paczek + 1)]
    db.session.add_all(lista)
    db.session.commit()
    return order, lista


def trasa(zamowienia, status='zatwierdzona', kierowca_id=None, nazwa=None, od=DZIEN, do=None, **kolumny):
    """Trasa z przystankami w kolejności `zamowienia` — wprost w bazie, bez blokad i walidacji serwisu tras."""
    t = Route(name=nazwa or u'Trasa %d' % next(_licznik), date_from=od, date_to=do or od, status=status,
              driver_worker_id=kierowca_id, **kolumny)
    db.session.add(t)
    db.session.flush()
    for pozycja, order in enumerate(zamowienia, start=1):
        db.session.add(RouteStop(route_id=t.id, order_id=order.id, position=pozycja))
    db.session.commit()
    return t


def zaladuj_wprost(paczki, trasa_, kto_id=None, chwila=T0):
    """Paczki załadowane na trasę (stan wyjściowy testu, bez API)."""
    for p in paczki:
        p.loaded_at, p.loaded_by_worker_id, p.loaded_method, p.loaded_route_id = chwila, kto_id, 'skan', trasa_.id
    db.session.commit()


def telefon_kierowcy():
    """(urządzenie stanowiska Dostawa, kierowca ze znacznikiem is_driver)."""
    device = ProductionDevice(device_id='TEL-DOSTAWA-%d' % next(_licznik), device_name='Telefon kierowcy',
                              station_code='delivery')
    db.session.add(device)
    db.session.commit()
    return device, kierowca()


def naglowki(device, kto=None, op_id=None):
    wynik = {'Authorization': 'Bearer ' + generate_token(device),
             'X-Operation-Id': op_id or 'op-dost-%d' % next(_licznik)}
    if kto is not None:
        wynik['X-Worker-Ids'] = str(kto.id)
    return wynik
```

- [ ] **Step 2: Testy, które padną**

Create `tests/test_dostawa_statusy_tras.py`:

```python
# -*- coding: utf-8 -*-
"""Statusy tras załadowana i w trasie w istniejącym backendzie (logistyka etap 4, krok 4.4, spec 4.3, 4.5, 9.3,
9.7 i 11): blokady zmian zamówień z takich tras, zajętość, tablet, Routimo, kolejność listy tras, etap „W trasie”,
znaczniki załadunku w regule unieważniania i w cofnięciu weryfikacji, statusy Base. Dostawy w raportach."""
import os

import pytest

from extensions import db
from modules.production.logistics.services import bl_sync, delivery, lista, paczki, routes, weryfikacja
from modules.production.logistics.services.delivery import LogistykaBlad
from tests.dostawa_pomocnicze import DZIEN, T0, trasa, zaladuj_wprost, zamowienie_z_paczkami
from tests.logistyka_fixtures import BASE, app, client, kierowca, pojazd  # noqa: F401

KORZEN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.mark.parametrize('status, fragment', [
    ('zaladowana', u'najpierw cofnij załadunek'),
    ('w_trasie', u'gdy kierowca rozliczy przystanek'),
])
def test_zmiana_adresu_zamowienia_z_trasy_zaladowanej_i_w_trasie_409(app, status, fragment):
    order, _ = zamowienie_z_paczkami(statusy=('zaladowane',))
    t = trasa([order], status=status)
    with pytest.raises(LogistykaBlad) as e:
        delivery.zmien_adres(order, u'ul. Nowa 1', '35-001', u'Rzeszów')
    assert e.value.status == 409
    assert t.name in e.value.komunikat and fragment in e.value.komunikat


def test_zmiana_adresu_zamowienia_dostarczonego_na_trasie_w_drodze_409(app):
    """Przystanek już dostarczony, a trasa jeszcze w drodze — zamówienie jest u klienta, jak na trasie wykonanej."""
    order, _ = zamowienie_z_paczkami(statusy=('dostarczone',))
    t = trasa([order], status='w_trasie')
    t.stops[0].delivered_at = T0
    db.session.commit()
    with pytest.raises(LogistykaBlad) as e:
        delivery.zmien_adres(order, u'ul. Nowa 1', '35-001', u'Rzeszów')
    assert e.value.status == 409 and u'zostało dostarczone' in e.value.komunikat


@pytest.mark.parametrize('status, napis', [('zaladowana', u'załadowana'), ('w_trasie', u'w trasie')])
def test_edycja_trasy_zaladowanej_i_w_trasie_zablokowana(app, status, napis):
    t = trasa([], status=status)
    with pytest.raises(LogistykaBlad) as e:
        routes.edytuj(t, {'name': 'Inna', 'date_from': '2026-10-01'})
    assert e.value.status == 409 and napis in e.value.komunikat


@pytest.mark.parametrize('status', ['zaladowana', 'w_trasie'])
def test_zaladowana_i_w_trasie_zajmuja_pojazd_i_kierowce(app, status):
    v, k = pojazd(), kierowca()
    trasa([], status=status, vehicle_id=v.id, kierowca_id=k.id)
    z = routes.zajetosc(DZIEN, DZIEN)
    assert v.id in z['pojazdy'] and k.id in z['kierowcy']


def test_tablet_widzi_trase_zaladowana_i_w_trasie(app):
    a, _ = zamowienie_z_paczkami(statusy=('zaladowane',))
    b, _ = zamowienie_z_paczkami(statusy=('zaladowane',))
    ta, tb = trasa([a], status='zaladowana'), trasa([b], status='w_trasie')
    assert routes.trasa_dla_tabletu(a.id).id == ta.id
    assert routes.trasa_dla_tabletu(b.id).id == tb.id


@pytest.mark.parametrize('status, kod', [('robocza', 409), ('zatwierdzona', 200), ('zaladowana', 200),
                                         ('w_trasie', 200), ('wykonana', 200)])
def test_routimo_od_zatwierdzonej_wzwyz(app, client, status, kod):
    order, _ = zamowienie_z_paczkami()
    t = trasa([order], status=status)
    assert client.get(BASE + '/routes/%d/routimo' % t.id).status_code == kod


def test_lista_tras_sortuje_sekcje_po_cyklu(app, client):
    ids = {status: trasa([], status=status).id
           for status in ('wykonana', 'w_trasie', 'zaladowana', 'zatwierdzona', 'robocza')}
    r = client.get(BASE + '/routes')
    assert r.status_code == 200, r.get_data()[:300]
    assert [t['id'] for t in r.get_json()['routes']] == [ids['robocza'], ids['zatwierdzona'], ids['zaladowana'],
                                                         ids['w_trasie'], ids['wykonana']]


def test_cofniecie_weryfikacji_czysci_zaladunek(app):
    """Review Focus 2: weryfikator cofa weryfikację w trakcie załadunku (paczki już na aucie, trasa jeszcze
    zatwierdzona) — znaczniki załadunku znikają razem ze znacznikami weryfikacji."""
    order, lista_paczek = zamowienie_z_paczkami()
    t = trasa([order])
    zaladuj_wprost(lista_paczek, t, kto_id=7)
    weryfikacja.cofnij_weryfikacje(order, worker_id=3, teraz=T0)
    db.session.commit()
    for p in lista_paczek:
        assert (p.loaded_at, p.loaded_by_worker_id, p.loaded_method, p.loaded_route_id) == (None, None, None, None)
        assert p.verified_at is None
    assert [p.current_status for p in order.products] == ['spakowane', 'spakowane']


def test_regula_uniewaznienia_czysci_zaladunek(app):
    """Doróbka po załadunku (spec 4.5): pozycje załadowane wracają do „spakowane”, paczki unieważnione razem ze
    znacznikami załadunku, zamówienie zostaje na trasie (kierowca zobaczy NIESPAKOWANE)."""
    order, lista_paczek = zamowienie_z_paczkami(statusy=('zaladowane', 'zaladowane'))
    t = trasa([order], status='zaladowana')
    zaladuj_wprost(lista_paczek, t, kto_id=7)
    order.products[0].current_status = 'czeka_na_wyciecie'       # doróbka
    db.session.commit()
    assert weryfikacja.uniewaznij_etapy(order, T0, u'doróbka') is True
    db.session.commit()
    assert [p.current_status for p in order.products] == ['czeka_na_wyciecie', 'spakowane']
    for p in lista_paczek:
        assert p.voided_at is not None and p.loaded_at is None and p.loaded_route_id is None
    assert routes.przystanek_zamowienia(order.id).route_id == t.id


def test_deklaracja_odmawia_zamowieniu_zaladowanemu(app):
    """Uwaga z Ruling 27 kroku 4.3: deklaracja paczek odmawia także zamówieniu załadowanemu (409 order_verified)."""
    order, _ = zamowienie_z_paczkami(statusy=('zaladowane',), numer_wewnetrzny='4401')
    with pytest.raises(paczki.PaczkiBlad) as e:
        paczki.zadeklaruj(order, paczki.Deklaracja('paczka', 1), 'packaging', {'type': 'device', 'id': 'TAB-1'},
                          teraz=T0)
    assert e.value.kod == 'order_verified' and u'załadowane' in e.value.komunikat


def test_etap_w_trasie_na_liscie_logistyki(app):
    jedzie, _ = zamowienie_z_paczkami(statusy=('zaladowane',))
    stoi, _ = zamowienie_z_paczkami(statusy=('zaladowane',))
    tj, ts = trasa([jedzie], status='w_trasie'), trasa([stoi], status='zaladowana')
    assert lista.serializuj(jedzie, None, tj)['etap'] == {'status': 'w_trasie', 'nazwa': 'W trasie'}
    assert lista.serializuj(stoi, None, ts)['etap'] == {'status': 'zaladowane', 'nazwa': u'Załadowane'}


def test_paczki_na_liscie_licza_zaladowane(app):
    order, lista_paczek = zamowienie_z_paczkami(paczek=3)
    t = trasa([order])
    zaladuj_wprost(lista_paczek[:2], t)
    assert lista.serializuj(order, None, t)['paczki'] == {'opis': u'3 × paczka', 'liczba': 3,
                                                          'zweryfikowane': 3, 'zaladowane': 2}


def test_znaczniki_base_dostawy(app):
    order, _ = zamowienie_z_paczkami()
    for funkcja, status in ((bl_sync.oznacz_zaladowane, 524520), (bl_sync.oznacz_wyslane, 149763),
                            (bl_sync.oznacz_dostarczone, 149778), (bl_sync.oznacz_planowana_trasa, 417343)):
        funkcja(order)
        assert order.bl_status_pending_id == status


def test_raporty_znaja_statusy_dostawy(app):
    """Spec 9.3: zamówienia na trasie i załadowane zostają w „Wyprodukowane”, a nazwy nie są „Status N”."""
    from modules.reports.models import BaselinkerReportOrder
    from modules.reports.service import STATUSY_BASELINKER
    assert STATUSY_BASELINKER[417343] == 'Planowana trasa'
    assert STATUSY_BASELINKER[524520] == u'Załadowane - trans. WoodPower'
    for status_id, nazwa in ((417343, 'Planowana trasa'), (524520, u'Załadowane - trans. WoodPower')):
        wiersz = BaselinkerReportOrder(current_status=nazwa, baselinker_status_id=status_id,
                                       total_volume=1.5, value_net=100)
        wiersz.update_production_fields()
        assert (wiersz.ready_pickup_volume, wiersz.ready_pickup_value_net) == (1.5, 100.0), status_id
        bez_id = BaselinkerReportOrder(current_status=nazwa, total_volume=2.0, value_net=50)
        bez_id.update_production_fields()
        assert bez_id.ready_pickup_volume == 2.0, nazwa
    with open(os.path.join(KORZEN, 'modules', 'baselinker', 'routers.py'), encoding='utf-8') as f:
        zrodlo = f.read()
    assert "417343: 'Planowana trasa'" in zrodlo and u"524520: 'Załadowane - trans. WoodPower'" in zrodlo
```

- [ ] **Step 3: Testy padają**

Run: `PYTEST tests/test_dostawa_statusy_tras.py`
Expected: FAIL — m.in. oba `test_zmiana_adresu…` (zmiana przechodzi bez 409 — trasy załadowanej i w drodze `_przystanek_do_zmiany` jeszcze nie zna), `test_edycja…` (komunikat bez nazwy statusu), `test_routimo…[zaladowana|w_trasie]` (409), `test_lista_tras_sortuje…` (`KeyError` w `KOLEJNOSC_STATUSOW` → 500), `test_cofniecie_weryfikacji…`, `test_regula…` (znaczniki zostają), `test_etap_w_trasie…`, `test_paczki_na_liscie…`, `test_znaczniki_base…` (`AttributeError`), `test_raporty…`. Przechodzą już: `test_zaladowana_i_w_trasie_zajmuja…`, `test_tablet_widzi…` (Task 1 dopisał statusy do `STATUSY_TRASY_AKTYWNE`), `test_deklaracja_odmawia…` (krok 4.3).

- [ ] **Step 4: Blokady zmian i etykiety statusów**

`modules/production/logistics/services/delivery.py`, `_przystanek_do_zmiany` — w docstringu dopisz akapit:
```python
    (krok 4.4, spec 4.3) Trasa załadowana i w trasie jest zablokowana jak zatwierdzona: zmiana zdejmująca zamówienie
    z trasy albo zmieniająca adres → 409. Załadowaną odblokowuje „Cofnij załadunek” w panelu tras, a z trasy w
    drodze zamówienie schodzi dopiero, gdy kierowca rozliczy przystanek („Niedostarczone” wraca je do puli).
```
i w kodzie, przed sprawdzeniem `zatwierdzona`:
```python
    trasa = routes.zablokuj_trasy(przystanek.route)
    # Krok 4.4: przystanek już dostarczony na trasie jeszcze w drodze traktujemy jak trasę wykonaną.
    if trasa.status == 'wykonana' or przystanek.delivered_at is not None:
        raise LogistykaBlad(u'Zamówienie {} zostało dostarczone trasą „{}”.'.format(
            order.internal_order_number, trasa.name))
    if trasa.status == 'zaladowana' and zdejmuje:
        raise LogistykaBlad(u'Zamówienie {} jest załadowane na trasę „{}” — najpierw cofnij załadunek w panelu '
                            u'tras, potem {}.'.format(order.internal_order_number, trasa.name, opis))
    if trasa.status == 'w_trasie' and zdejmuje:
        raise LogistykaBlad(u'Zamówienie {} jedzie trasą „{}” — {} dopiero, gdy kierowca rozliczy '
                            u'przystanek.'.format(order.internal_order_number, trasa.name, opis))
    if trasa.status == 'zatwierdzona' and zdejmuje:
```

`modules/production/logistics/services/routes.py` — docstring modułu (linie 5-6):
```python
Statusy: robocza (pełna edycja) → zatwierdzona (zablokowana, eksport Routimo) → zaladowana
(kierowca zakończył załadunek) → w_trasie (kierowca ruszył) → wykonana (tylko odczyt; dostarczenie cofa
„Cofnij dostarczenie”). Przejścia Dostawy: services/dostawa.py. Funkcje NIE commitują.
```
`_wymagaj_statusu`:
```python
def _wymagaj_statusu(route, *statusy):
    if route.status not in statusy:
        opis = {'robocza': u'robocza', 'zatwierdzona': u'zatwierdzona', 'wykonana': u'wykonana',
                'zaladowana': u'załadowana', 'w_trasie': u'w trasie'}
        raise LogistykaBlad(u'Trasa „{}” jest {} — ta operacja nie jest dostępna.'.format(
            route.name, opis.get(route.status, route.status)))
```

`modules/production/logistics/routers/trasy_api.py`:
```python
# Sekcje listy tras w kolejności cyklu trasy (krok 4.4: załadowane i w trasie między zatwierdzonymi a wykonanymi).
KOLEJNOSC_STATUSOW = {'robocza': 0, 'zatwierdzona': 1, 'zaladowana': 2, 'w_trasie': 3, 'wykonana': 4}
```
`route_routimo` — zdanie docstringu i warunek:
```python
    Dostępny od zatwierdzonej wzwyż: zatwierdzona, załadowana, w trasie i wykonana (R11 — przewoźnik może pobrać
    plik ponownie po zamknięciu trasy); robocza (jeszcze się zmienia) zwraca 409.
```
```python
    if trasa.status not in ('zatwierdzona', 'zaladowana', 'w_trasie', 'wykonana'):
        return _blad(u'Eksport do Routimo jest dostępny po zatwierdzeniu trasy.', 409)
```

- [ ] **Step 5: Znaczniki załadunku**

`modules/production/logistics/services/paczki.py` — po `uniewaznij`:
```python
def wyczysc_zaladunek(lista):
    """
    Czyści znaczniki załadunku paczek (krok 4.4): towar wraca z auta albo przestał się nadawać do załadunku —
    cofnięcie weryfikacji, reguła unieważniania etapów, „Zostaje”, niedostarczenie, „Cofnij załadunek”.
    Zwraca liczbę paczek, które były załadowane. NIE commituje.
    """
    ile = 0
    for p in lista:
        if p.loaded_at is not None or p.loaded_route_id is not None:
            ile += 1
        p.loaded_at = None
        p.loaded_by_worker_id = None
        p.loaded_method = None
        p.loaded_route_id = None
    return ile
```

`modules/production/logistics/services/weryfikacja.py`, `uniewaznij_etapy` — po `for p in cofane: p.current_status = 'spakowane'`:
```python
    # (krok 4.4) Zamówienie wróciło do produkcji, więc nic z niego nie jest już na aucie. Paczki unieważniane niżej
    # nie mogą liczyć się trasie jako załadowane.
    paczki.wyczysc_zaladunek(stare)
```
`cofnij_weryfikacje_zamowienia` — w docstringu dopisz „(krok 4.4) Czyści też znaczniki załadunku: weryfikację cofnięto
w trakcie załadunku, a paczka bez weryfikacji nie może liczyć się jako załadowana.” i po pętli czyszczącej `verified_*`:
```python
    paczki.wyczysc_zaladunek(aktualne)
```

**Cofnięcie sprawdzenia jednej paczki** — `weryfikacja.cofnij_sprawdzenie_paczki(paczka, order, worker_id=None, device_id=None, teraz=None) -> (zmieniono, bylo_zweryfikowane)` (endpoint `POST /api/mobile/verification/packages/<id>/unverify`, zatwierdzony przez Konrada 1.10; robi go sesja kroku 4.3 na gałęzi `claude/logistyka-etap-4-unverify`, kontroler scala jej commit przed dyspozycją tego zadania). Odmowę dla zamówienia z pozycjami `zaladowane`/`dostarczone` funkcja już ma (409 `order_status` z `sprawdz_stan` przez `stan_do_zapisu`, jak cofnięcie weryfikacji zamówienia — spec 4.5 „do załadunku”). Dopisz tylko czyszczenie znaczników załadunku: gdy cofnięcie przywraca zamówieniu `spakowane` (gałąź `bylo_zweryfikowane`; w trakcie załadunku trasa jest jeszcze zatwierdzona) — `paczki.wyczysc_zaladunek(<aktualne paczki zamówienia ze stan_do_zapisu>)` na WSZYSTKICH aktualnych paczkach, przed logiem: zamówienie niezweryfikowane nie może być na aucie, a kierowca zobaczy NIEZWERYFIKOWANE. W docstringu funkcji dopisz „(krok 4.4) Czyści też znaczniki załadunku wszystkich paczek zamówienia, które przestało być zweryfikowane.”

Testy (w `tests/test_dostawa_statusy_tras.py`):
```python
def test_cofniecie_sprawdzenia_paczki_czysci_zaladunek_zamowienia(app):
    """Weryfikator cofa sprawdzenie jednej paczki w trakcie załadunku — zamówienie wraca do „spakowane”, a znaczniki
    załadunku znikają ze wszystkich jego paczek (pozostałe paczki zostają sprawdzone)."""
    order, lista_paczek = zamowienie_z_paczkami()
    t = trasa([order])
    zaladuj_wprost(lista_paczek, t, kto_id=7)
    wynik = weryfikacja.cofnij_sprawdzenie_paczki(lista_paczek[0], order, worker_id=3, teraz=T0)
    db.session.commit()
    assert wynik == (True, True)
    assert [p.current_status for p in order.products] == ['spakowane', 'spakowane']
    assert all(p.loaded_at is None and p.loaded_route_id is None for p in lista_paczek)
    assert lista_paczek[1].verified_at is not None


def test_cofniecie_sprawdzenia_paczki_zamowienia_zaladowanego_409(app):
    order, lista_paczek = zamowienie_z_paczkami(statusy=('zaladowane', 'zaladowane'))
    t = trasa([order], status='zaladowana')
    zaladuj_wprost(lista_paczek, t, kto_id=7)
    with pytest.raises(weryfikacja.WeryfikacjaBlad) as e:
        weryfikacja.cofnij_sprawdzenie_paczki(lista_paczek[0], order, worker_id=3, teraz=T0)
    assert e.value.kod == 'order_status'
    db.session.rollback()
    assert all(p.loaded_route_id == t.id and p.verified_at is not None for p in lista_paczek)
```
(Jeśli scalona wersja funkcji ma inną sygnaturę albo kod odmowy, kontroler poprawia oba testy w briefie.)

- [ ] **Step 6: Etap „W trasie” i liczba załadowanych paczek**

`modules/production/logistics/services/lista.py` (pod `NAZWA_STANOWISKA`):
```python
# Etap zamówienia załadowanego na trasę, która już ruszyła (krok 4.4, spec 11) — wynika z pozycji I trasy.
NAZWA_W_TRASIE = u'W trasie'
```
```python
def _etap(aktywne, trasa=None):
    if not aktywne:
        return {'status': 'anulowane', 'nazwa': 'Anulowane'}
    najwczesniejszy = min(aktywne, key=lambda p: _ranga(p.current_status))
    status = najwczesniejszy.current_status
    if status == 'zaladowane' and trasa is not None and trasa.status == 'w_trasie':
        return {'status': 'w_trasie', 'nazwa': NAZWA_W_TRASIE}
    return {'status': status, 'nazwa': _nazwa_etapu(najwczesniejszy)}
```
W `serializuj`: `'etap': _etap(aktywne, trasa),` oraz słownik paczek:
```python
        'paczki': ({'opis': paczki.opis_paczek(paczki_zamowienia), 'liczba': len(paczki_zamowienia),
                    'zweryfikowane': sum(1 for p in paczki_zamowienia if p.verified_at is not None),
                    # Krok 4.4: panel tras pokazuje „załadowano 1/2” przy przystanku.
                    'zaladowane': sum(1 for p in paczki_zamowienia if p.loaded_at is not None)}
                   if paczki_zamowienia else None),
```

- [ ] **Step 7: Znaczniki Base. Dostawy**

`modules/production/logistics/services/bl_sync.py` — zamień sekcję „Furtka pod stanowisko kierowcy” (linie 478-485) na:
```python
# ── Statusy Dostawy (logistyka etap 4, krok 4.4) — sam znacznik, wysyła dopychacz po commicie ──────

def oznacz_zaladowane(order):
    """Zakończony załadunek trasy: „Załadowane - trans. WoodPower”."""
    order.bl_status_pending_id = sposoby.STATUS_ZALADOWANE


def oznacz_wyslane(order):
    """„Ruszam w trasę” i cofnięcie dostarczenia: „Wysłane - trans. WoodPower”."""
    order.bl_status_pending_id = sposoby.STATUS_WYSLANE_TRANSPORT


def oznacz_dostarczone(order):
    """Dostarczone (telefon) albo odhaczone w panelu: „Dostarczona - trans. WoodPower”."""
    order.bl_status_pending_id = sposoby.STATUS_DOSTARCZONE_TRANSPORT


def oznacz_planowana_trasa(order):
    """Cofnięty załadunek albo niedostarczone zamówienie, które było załadowane: „Planowana trasa”."""
    order.bl_status_pending_id = sposoby.STATUS_PLANOWANA_TRASA
```

- [ ] **Step 8: Raporty**

`modules/reports/models.py`, `update_production_fields`:
```python
        # NOWA LOGIKA: Statusy dla "Wyprodukowane" (zamiast tylko "Czeka na odbiór osobisty")
        # ID statusów: 138620, 138623, 105113, 105114, 149763, 149777, 138624, 149778, 149779,
        # 417343 (Planowana trasa) i 524520 (Załadowane) — logistyka etap 4, krok 4.4 (spec 9.3)
        elif (self.baselinker_status_id and
              self.baselinker_status_id in [138620, 138623, 105113, 105114, 149763, 149777, 138624, 149778, 149779,
                                            417343, 524520]):
```
i w liście nazw (fallback), przed `'odebrane'`:
```python
            'planowana trasa',                # 417343
            'załadowane - trans. woodpower',  # 524520
            'odebrane'                        # 149779
```
`modules/reports/service.py`, `STATUSY_BASELINKER` — po `149779: "Odebrane",`:
```python
    417343: "Planowana trasa",
    524520: "Załadowane - trans. WoodPower",
```
`modules/baselinker/routers.py`, `status_map` — po `149779: 'Odebrane',`:
```python
                417343: 'Planowana trasa',
                524520: 'Załadowane - trans. WoodPower',
```
(Nazwy jak w Base. — sprawdzone `getOrderStatusList` 1.10.2026.)

- [ ] **Step 9: Testy przechodzą**

Run: `PYTEST tests/test_dostawa_statusy_tras.py tests/test_logistyka_trasy_serwis.py tests/test_logistyka_trasy_api.py tests/test_logistyka_delivery.py tests/test_weryfikacja_akcje.py tests/test_weryfikacja_regula.py tests/test_weryfikacja_problem.py tests/test_logistyka_panel_api.py`
Expected: PASS.

- [ ] **Step 10: Pełny pakiet**

Run: `PYTEST tests/`
Expected: `wynik Task 1 + 23 passed, 3 skipped` (21 w pliku z kroku 2 + 2 testy cofnięcia weryfikacji jednej paczki).

- [ ] **Step 11: Commit**

```bash
git add tests/dostawa_pomocnicze.py tests/test_dostawa_statusy_tras.py \
  modules/production/logistics/services/delivery.py modules/production/logistics/services/routes.py \
  modules/production/logistics/routers/trasy_api.py modules/production/logistics/services/paczki.py \
  modules/production/logistics/services/weryfikacja.py modules/production/logistics/services/lista.py \
  modules/production/logistics/services/bl_sync.py modules/reports/models.py modules/reports/service.py \
  modules/baselinker/routers.py
git commit -m "feat(production): trasy zaladowane i w trasie w panelu, znaczniki zaladunku i statusy Base. Dostawy" \
  -m "Krok 4.4 logistyki: blokady zmian zamowien z tras zaladowanych i w trasie, Routimo od zatwierdzonej wzwyz, kolejnosc sekcji listy tras, etap W trasie, czyszczenie znacznikow zaladunku w regule uniewazniania i w cofnieciu weryfikacji, znaczniki Base. 524520/149763/149778/417343, nowe statusy w raportach." \
  -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---
### Task 3: Serwis Dostawy — załadunek, „Zostaje”, zakończenie załadunku, wyjazd, „Cofnij załadunek”

**Files:**
- Create: `modules/production/logistics/services/dostawa.py`
- Modify: `modules/production/logistics/services/routes.py:560-595` (`usun_przystanek`: pracownik i urządzenie w logu)
- Test: `tests/test_dostawa_zaladunek.py`

**Interfaces:**
- Consumes: `blokady_zamowien.zablokuj_zamowienia(order_ids)` (krok 4.4a, `modules/production/services/blokady_zamowien.py`); `paczki.zablokuj_deklaracje()`, `paczki.zablokuj_stan(order) -> [aktualne paczki]`, `paczki.wyczysc_zaladunek(lista)` (Task 2), `paczki.opis_paczek(lista)`; `routes.zablokuj_trasy(route) -> świeża trasa z przystankami`, `routes.przystanek_zamowienia(order_id)`; `bl_sync.oznacz_zaladowane/oznacz_wyslane/oznacz_planowana_trasa(order)` (Task 2), `bl_sync.zaplanuj_po_commicie(order_id)`; `weryfikacja._notatka(wartosc)`; `delivery.aktywne_produkty`, `delivery.podbij_pozycje(order, teraz)`, `delivery.zapisz_log(order, akcja, stara, nowa, user_id=, note=, route_id=, teraz=, worker_id=, device_id=)`; `tests/dostawa_pomocnicze.py` (Task 2); `tests/blokady_pomocnicze.py` (krok 4.4a: `Zapytania` z `.lista` i `.pierwsze(warunek)`, predykaty `blokada_zamowien`, `blokada_pozycji`, `zapis`).
- Produces (`dostawa.py`): `STANOWISKO = 'delivery'`, `METODY`, `POWODY_ZOSTAJE`, `POWODY_NIEDOSTARCZENIA`, `POWOD_ODHACZENIA = 'odhaczone_w_panelu'`, `ETYKIETA_ODHACZENIA`, `NAZWY_STATUSOW_TRASY`; `class DostawaBlad(LogistykaBlad)` z polem `kod`; `waliduj_powod(powod, slownik)`, `waliduj_metode(metoda)`; `zablokuj(route) -> (trasa, {order_id: order}, {order_id: [paczki]})` (zamówienia CAŁEJ trasy); `_wymagaj_statusu(trasa, *statusy)`, `_przystanek(trasa, order_id)`, `_numer(order)`, `_zaladowane_na_trase(aktualne, trasa)`, `_log_trasy(trasa, stary, nowy, teraz, user_id=None, worker_id=None, device_id=None)`; `zaladuj_paczke(route, package_id, metoda='skan', worker_id=None, device_id=None, teraz=None) -> (paczka, zmieniono)`; `rozladuj_paczke(route, package_id, worker_id=None, device_id=None, teraz=None) -> (paczka, zmieniono)`; `ustaw_zostaje(route, order_id, powod, notatka=None, worker_id=None, device_id=None, teraz=None) -> bool`; `zdejmij_zostaje(route, order_id, worker_id=None, device_id=None, teraz=None) -> bool`; `zakoncz_zaladunek(route, worker_id=None, device_id=None, teraz=None) -> (trasa, usuniete)`; `ruszaj(route, worker_id=None, device_id=None, teraz=None) -> (trasa, zmieniono)`; `cofnij_zaladunek(route, user_id=None, teraz=None) -> trasa`. `routes.usun_przystanek(route, order_id, user_id=None, note=None, wymagaj_roboczej=True, worker_id=None, device_id=None)`.

- [ ] **Step 1: Testy, które padną**

Create `tests/test_dostawa_zaladunek.py`:

```python
# -*- coding: utf-8 -*-
"""Załadunek trasy (logistyka etap 4, krok 4.4, spec 9.3–9.4 i 4.5): skan paczek z bramką weryfikacji, „Zostaje”,
zakończenie załadunku, wyjazd i „Cofnij załadunek” z panelu — serwis services/dostawa.py."""
import pytest

from extensions import db
from modules.production.logistics.models import LogisticsLog, RouteStop
from modules.production.logistics.services import dostawa, routes
from tests.blokady_pomocnicze import Zapytania, blokada_pozycji, blokada_zamowien, zapis
from tests.dostawa_pomocnicze import T0, trasa, zaladuj_wprost, zamowienie_z_paczkami
from tests.logistyka_fixtures import app  # noqa: F401


def _blad(funkcja, *args, **kwargs):
    with pytest.raises(dostawa.DostawaBlad) as e:
        funkcja(*args, **kwargs)
    db.session.rollback()
    return e.value


def _akcje(order):
    return [w.action for w in LogisticsLog.query.filter_by(order_id=order.id).order_by(LogisticsLog.id)]


# --- Skan paczki --------------------------------------------------------------------------------------

def test_zaladunek_paczki_skanem(app):
    order, (p1, p2) = zamowienie_z_paczkami()
    t = trasa([order])
    paczka, zmieniono = dostawa.zaladuj_paczke(t, p1.id, 'skan', worker_id=7, device_id=3, teraz=T0)
    db.session.commit()
    assert zmieniono is True and paczka is p1
    assert (p1.loaded_at, p1.loaded_by_worker_id, p1.loaded_method, p1.loaded_route_id) == (T0, 7, 'skan', t.id)
    assert p2.loaded_at is None
    # Pozycje zostają zweryfikowane — „zaladowane” dostają dopiero przy zakończeniu załadunku.
    assert [p.current_status for p in order.products] == ['zweryfikowane', 'zweryfikowane']


def test_ponowny_skan_bez_zmian(app):
    """Review Focus 4: powtórka z kolejki offline z nowym X-Operation-Id — bez zmian, pierwszy zapis zostaje."""
    order, (p1, _p2) = zamowienie_z_paczkami()
    t = trasa([order])
    dostawa.zaladuj_paczke(t, p1.id, 'skan', worker_id=7, teraz=T0)
    db.session.commit()
    _paczka, zmieniono = dostawa.zaladuj_paczke(t, p1.id, 'reczne', worker_id=8)
    assert zmieniono is False
    assert (p1.loaded_method, p1.loaded_by_worker_id, p1.loaded_at) == ('skan', 7, T0)


def test_zaladunek_odmowy(app):
    order, (p1, _p2) = zamowienie_z_paczkami()
    t = trasa([order])
    e = _blad(dostawa.zaladuj_paczke, t, 987654)
    assert (e.kod, e.status) == ('package_not_found', 404)
    e = _blad(dostawa.zaladuj_paczke, t, p1.id, 'palcem')
    assert (e.kod, e.status) == ('invalid_method', 422)
    inne, (q1, _q2) = zamowienie_z_paczkami()
    trasa([inne], nazwa=u'Lublin 03.10')
    e = _blad(dostawa.zaladuj_paczke, t, q1.id)
    assert e.kod == 'package_not_on_route' and u'Lublin 03.10' in e.komunikat
    assert e.dane == {'route_name': u'Lublin 03.10'}
    bez_trasy, (b1, _b2) = zamowienie_z_paczkami()
    e = _blad(dostawa.zaladuj_paczke, t, b1.id)
    assert e.kod == 'package_not_on_route' and u'bez trasy' in e.komunikat and e.dane == {'route_name': None}


def test_zaladunek_tylko_na_trasie_zatwierdzonej(app):
    order, (p1, _p2) = zamowienie_z_paczkami()
    for status in ('robocza', 'zaladowana', 'w_trasie', 'wykonana'):
        t = trasa([order], status=status)
        e = _blad(dostawa.zaladuj_paczke, t, p1.id)
        assert (e.kod, e.status) == ('route_status', 409), status
        RouteStop.query.filter_by(order_id=order.id).delete()
        db.session.commit()


def test_zaladunek_niewaznej_paczki_i_niezweryfikowanego_zamowienia(app):
    order, (p1, p2) = zamowienie_z_paczkami()
    t = trasa([order])
    p1.voided_at = T0
    db.session.commit()
    assert _blad(dostawa.zaladuj_paczke, t, p1.id).kod == 'package_void'
    niezweryfikowane, (n1, _n2) = zamowienie_z_paczkami(statusy=('spakowane', 'spakowane'), zweryfikowane=False)
    t2 = trasa([niezweryfikowane])
    e = _blad(dostawa.zaladuj_paczke, t2, n1.id)
    assert e.kod == 'order_not_verified' and niezweryfikowane.internal_order_number in e.komunikat
    assert p2.loaded_at is None and n1.loaded_at is None


def test_wstepna_odmowa_niezweryfikowanego_bez_blokad(app, monkeypatch):
    """Odmowę widoczną już w migawce dajemy przed blokadami (lekcja 1213 z kroku 4.3: nie czekamy na blokady,
    skoro i tak odmówimy)."""
    order, (p1,) = zamowienie_z_paczkami(statusy=('spakowane',), paczek=1, zweryfikowane=False)
    t = trasa([order])

    def _nie_wolno(*a, **k):
        raise AssertionError('blokady przed wstępną odmową')

    monkeypatch.setattr(routes, 'zablokuj_trasy', _nie_wolno)
    assert _blad(dostawa.zaladuj_paczke, t, p1.id).kod == 'order_not_verified'


def test_skan_paczki_z_innej_trasy_mowi_o_trasie(app):
    """Wstępna odmowa „niezweryfikowane” tylko dla zamówienia z TEJ trasy: paczka z innej trasy dostaje odmowę
    z nazwą tamtej trasy (spec 9.3), także gdy tamto zamówienie nie jest jeszcze zweryfikowane."""
    order, _ = zamowienie_z_paczkami()
    t = trasa([order])
    obce, (o1,) = zamowienie_z_paczkami(statusy=('spakowane',), paczek=1, zweryfikowane=False)
    trasa([obce], nazwa=u'Krosno 05.10')
    e = _blad(dostawa.zaladuj_paczke, t, o1.id)
    assert e.kod == 'package_not_on_route' and u'Krosno 05.10' in e.komunikat


def test_skan_przystanku_zostaje_409(app):
    order, (p1, _p2) = zamowienie_z_paczkami()
    t = trasa([order])
    dostawa.ustaw_zostaje(t, order.id, 'brak_miejsca', worker_id=7)
    db.session.commit()
    e = _blad(dostawa.zaladuj_paczke, t, p1.id)
    assert e.kod == 'stop_stays' and u'Brak miejsca' in e.komunikat
    assert p1.loaded_at is None


def test_rozladunek_cofa_pomylke(app):
    order, (p1, _p2) = zamowienie_z_paczkami()
    t = trasa([order])
    zaladuj_wprost([p1], t, kto_id=7)
    _paczka, zmieniono = dostawa.rozladuj_paczke(t, p1.id, worker_id=7)
    db.session.commit()
    assert zmieniono is True and (p1.loaded_at, p1.loaded_route_id, p1.loaded_method) == (None, None, None)
    assert dostawa.rozladuj_paczke(t, p1.id)[1] is False


# --- „Zostaje” ---------------------------------------------------------------------------------------

def test_zostaje_czysci_zaladunek_przystanku_i_daje_sie_zdjac(app):
    order, lista_paczek = zamowienie_z_paczkami()
    t = trasa([order])
    zaladuj_wprost(lista_paczek, t, kto_id=7)
    assert dostawa.ustaw_zostaje(t, order.id, 'uszkodzone', u'  pęknięta  deska ', worker_id=7) is True
    db.session.commit()
    stop = RouteStop.query.filter_by(order_id=order.id).one()
    assert (stop.stays_reason, stop.stays_note) == ('uszkodzone', u'pęknięta deska')
    assert all(p.loaded_at is None for p in lista_paczek)
    assert dostawa.ustaw_zostaje(t, order.id, 'uszkodzone', u'pęknięta deska') is False
    assert dostawa.zdejmij_zostaje(t, order.id, worker_id=7) is True
    db.session.commit()
    assert (stop.stays_reason, stop.stays_note) == (None, None)
    assert dostawa.zdejmij_zostaje(t, order.id) is False


def test_zostaje_odmowy(app):
    order, _ = zamowienie_z_paczkami()
    t = trasa([order])
    e = _blad(dostawa.ustaw_zostaje, t, order.id, 'nie_chce')
    assert (e.kod, e.status) == ('invalid_reason', 422)
    e = _blad(dostawa.ustaw_zostaje, t, order.id, ['inne'])          # lista z JSON-a — 422, nie 500
    assert e.kod == 'invalid_reason'
    e = _blad(dostawa.ustaw_zostaje, t, 987654, 'inne')
    assert (e.kod, e.status) == ('stop_not_found', 404)
    jedzie, _ = zamowienie_z_paczkami(statusy=('zaladowane',))
    w_trasie = trasa([jedzie], status='w_trasie')
    assert _blad(dostawa.ustaw_zostaje, w_trasie, jedzie.id, 'inne').kod == 'route_status'


# --- Zakończenie załadunku ---------------------------------------------------------------------------

def test_zakonczenie_zaladunku(app):
    jedzie, paczki_jedzie = zamowienie_z_paczkami()
    zostaje, _ = zamowienie_z_paczkami()
    t = trasa([jedzie, zostaje])
    zaladuj_wprost(paczki_jedzie, t, kto_id=7)
    dostawa.ustaw_zostaje(t, zostaje.id, 'brak_miejsca', u'za długie')
    db.session.commit()
    trasa_po, usuniete = dostawa.zakoncz_zaladunek(t, worker_id=7, device_id=3, teraz=T0)
    db.session.commit()
    assert trasa_po.status == 'zaladowana' and (trasa_po.loaded_at, trasa_po.loaded_by_worker_id) == (T0, 7)
    assert [s.order_id for s in trasa_po.stops] == [jedzie.id]
    assert usuniete == [{'order_id': zostaje.id, 'internal_order_number': zostaje.internal_order_number,
                         'reason': 'brak_miejsca'}]
    assert [p.current_status for p in jedzie.products] == ['zaladowane', 'zaladowane']
    assert jedzie.bl_status_pending_id == 524520
    assert [p.current_status for p in zostaje.products] == ['zweryfikowane', 'zweryfikowane']   # bez zmian
    assert zostaje.bl_status_pending_id is None
    assert RouteStop.query.filter_by(order_id=zostaje.id).first() is None
    wpis = LogisticsLog.query.filter_by(order_id=zostaje.id, action='zostaje').one()
    assert (wpis.new_value, wpis.note, wpis.worker_id, wpis.device_id) == \
        ('brak_miejsca', u'Brak miejsca: za długie', 7, 3)
    assert LogisticsLog.query.filter_by(order_id=zostaje.id, action='trasa_usuniete').one().worker_id == 7
    zaladunek = LogisticsLog.query.filter_by(order_id=jedzie.id, action='zaladunek').one()
    assert (zaladunek.old_value, zaladunek.new_value, zaladunek.note) == (None, 'zaladowane', u'2 × paczka')
    status = LogisticsLog.query.filter_by(order_id=jedzie.id, action='trasa_status').one()
    assert (status.old_value, status.new_value, status.worker_id) == ('zatwierdzona', 'zaladowana', 7)


def test_zakonczenie_zdejmuje_anulowane(app):
    jedzie, paczki_jedzie = zamowienie_z_paczkami()
    anulowane, _ = zamowienie_z_paczkami(statusy=('anulowane',))
    t = trasa([jedzie, anulowane])
    zaladuj_wprost(paczki_jedzie, t)
    _trasa, usuniete = dostawa.zakoncz_zaladunek(t, worker_id=7)
    db.session.commit()
    assert usuniete == [{'order_id': anulowane.id, 'internal_order_number': anulowane.internal_order_number,
                         'reason': 'anulowane'}]
    assert RouteStop.query.filter_by(order_id=anulowane.id).first() is None


def test_zakonczenie_lista_brakow(app):
    czesc, (c1, _c2) = zamowienie_z_paczkami()
    bez_paczek, _ = zamowienie_z_paczkami(paczek=0)
    t = trasa([czesc, bez_paczek])
    zaladuj_wprost([c1], t)
    e = _blad(dostawa.zakoncz_zaladunek, t, worker_id=7)
    assert (e.kod, e.status) == ('loading_incomplete', 409)
    assert e.dane == {'braki': [
        {'order_id': czesc.id, 'internal_order_number': czesc.internal_order_number, 'reason': 'niezaladowane',
         'loaded': 1, 'total': 2},
        {'order_id': bez_paczek.id, 'internal_order_number': bez_paczek.internal_order_number,
         'reason': 'bez_paczek', 'loaded': 0, 'total': 0}]}
    assert czesc.internal_order_number in e.komunikat
    assert routes.przystanek_zamowienia(czesc.id).route.status == 'zatwierdzona'


def test_zakonczenie_odmawia_gdy_zamowienie_przestalo_byc_zweryfikowane(app):
    """Review Focus 2: paczki zostały na aucie, ale pozycje nie są już zweryfikowane — zakończenie nie przepuszcza
    takiego zamówienia jako załadowanego."""
    order, lista_paczek = zamowienie_z_paczkami()
    t = trasa([order])
    zaladuj_wprost(lista_paczek, t)
    for p in order.products:
        p.current_status = 'spakowane'
    db.session.commit()
    e = _blad(dostawa.zakoncz_zaladunek, t)
    assert e.dane['braki'][0]['reason'] == 'niezweryfikowane'


def test_zakonczenie_bez_zaladowanych_409(app):
    order, _ = zamowienie_z_paczkami()
    t = trasa([order], nazwa=u'Jasło 06.10')
    dostawa.ustaw_zostaje(t, order.id, 'inne')
    db.session.commit()
    e = _blad(dostawa.zakoncz_zaladunek, t)
    assert e.kod == 'nothing_loaded' and u'Jasło 06.10' in e.komunikat
    assert RouteStop.query.filter_by(order_id=order.id).one().stays_reason == 'inne'   # nic nie zdjęte


# --- Wyjazd i cofnięcie załadunku ------------------------------------------------------------------------

def test_ruszam(app):
    order, _ = zamowienie_z_paczkami(statusy=('zaladowane', 'zaladowane'))
    t = trasa([order], status='zaladowana')
    trasa_po, zmieniono = dostawa.ruszaj(t, worker_id=7, device_id=3, teraz=T0)
    db.session.commit()
    assert zmieniono is True and trasa_po.status == 'w_trasie'
    assert (trasa_po.departed_at, trasa_po.departed_by_worker_id) == (T0, 7)
    assert order.bl_status_pending_id == 149763
    wpis = LogisticsLog.query.filter_by(order_id=order.id, action='wyjazd').one()
    assert (wpis.old_value, wpis.new_value, wpis.worker_id) == ('zaladowana', 'w_trasie', 7)


def test_ponowne_ruszam_bez_zmian(app):
    """Review Focus 4: drugie „Ruszam” nie wysyła drugi raz 149763 ani nie dopisuje logu."""
    order, _ = zamowienie_z_paczkami(statusy=('zaladowane',))
    t = trasa([order], status='zaladowana')
    dostawa.ruszaj(t, worker_id=7, teraz=T0)
    db.session.commit()
    order.bl_status_pending_id = None   # dopychacz wysłał
    db.session.commit()
    _trasa, zmieniono = dostawa.ruszaj(t, worker_id=7)
    assert zmieniono is False and order.bl_status_pending_id is None
    assert _akcje(order).count('wyjazd') == 1


def test_ruszam_wymaga_zakonczonego_zaladunku(app):
    order, _ = zamowienie_z_paczkami()
    t = trasa([order])
    assert _blad(dostawa.ruszaj, t).kod == 'route_status'


def test_cofnij_zaladunek_z_panelu(app):
    order, lista_paczek = zamowienie_z_paczkami(statusy=('zaladowane', 'zaladowane'))
    t = trasa([order], status='zaladowana', loaded_at=T0, loaded_by_worker_id=7)
    zaladuj_wprost(lista_paczek, t, kto_id=7)
    trasa_po = dostawa.cofnij_zaladunek(t, user_id=1, teraz=T0)
    db.session.commit()
    assert trasa_po.status == 'zatwierdzona' and (trasa_po.loaded_at, trasa_po.loaded_by_worker_id) == (None, None)
    assert [p.current_status for p in order.products] == ['zweryfikowane', 'zweryfikowane']
    assert all(p.loaded_at is None for p in lista_paczek)
    assert order.bl_status_pending_id == 417343
    wpis = LogisticsLog.query.filter_by(order_id=order.id, action='zaladunek').one()
    assert (wpis.old_value, wpis.new_value, wpis.user_id) == ('zaladowane', None, 1)
    assert _blad(dostawa.cofnij_zaladunek, trasa_po).kod == 'route_status'


# --- Kolejność blokad --------------------------------------------------------------------------------

def test_kolejnosc_blokad_zapisu_dostawy(app):
    """Blokada tras → blokada deklaracji → zamówienia (rosnąco) → paczki → pozycje → zapis. SQLite pomija FOR UPDATE,
    więc pilnujemy kolejności zapytań (wiersze blokad rozpoznajemy po kluczu w parametrach)."""
    a, paczki_a = zamowienie_z_paczkami()
    b, paczki_b = zamowienie_z_paczkami()
    t = trasa([b, a])
    zaladuj_wprost(paczki_a + paczki_b, t)
    with Zapytania() as z:
        dostawa.zakoncz_zaladunek(t, worker_id=7)
        db.session.flush()

    def blokada(klucz):
        return next(i for i, (sql, par) in enumerate(z.lista)
                    if 'FROM prod_config' in sql and klucz in tuple(par or ()))

    zamowienia_i = z.pierwsze(blokada_zamowien)
    paczki_i = z.pierwsze(lambda sql: sql.startswith('SELECT') and 'FROM prod_packages' in sql)
    assert (blokada('logistyka_trasy_blokada') < blokada('logistyka_paczki_blokada') < zamowienia_i < paczki_i
            < z.pierwsze(blokada_pozycji) < z.pierwsze(zapis))
    assert list(z.lista[zamowienia_i][1]) == sorted([a.id, b.id])
```

- [ ] **Step 2: Testy padają**

Run: `PYTEST tests/test_dostawa_zaladunek.py`
Expected: FAIL — `ImportError: cannot import name 'dostawa'` (cały plik).

- [ ] **Step 3: `usun_przystanek` z pracownikiem**

`modules/production/logistics/services/routes.py`, `usun_przystanek` — sygnatura i wpis logu (reszta bez zmian):
```python
def usun_przystanek(route, order_id, user_id=None, note=None, wymagaj_roboczej=True, worker_id=None,
                    device_id=None):
    # (fix-1, Ruling A3) Wołania zagnieżdżone (wykonaj/usun w pętli) są bezpieczne —
    # patrz docstring zablokuj_trasy(). `worker_id`/`device_id` (krok 4.4): zdjęcie z telefonu kierowcy
    # („Zostaje” przy zakończeniu załadunku, „Niedostarczone”).
```
```python
    delivery.zapisz_log(order, 'trasa_usuniete', route.name[:64], None, user_id=user_id,
                        worker_id=worker_id, device_id=device_id,
                        note=note, route_id=route.id, teraz=teraz)
```

- [ ] **Step 4: Serwis Dostawy — część załadunkowa**

Create `modules/production/logistics/services/dostawa.py`:

```python
# -*- coding: utf-8 -*-
"""
Stanowisko Dostawa (logistyka etap 4, krok 4.4, spec 9 i 4.5): przejścia trasy i jej przystanków — załadunek paczek,
„Zostaje”, zakończenie załadunku, wyjazd, dostarczenia, niedostarczenia, odhaczenie i cofnięcia. Wspólne dla telefonu
kierowcy (routers/dostawa_api.py) i panelu tras (routers/trasy_api.py). Funkcje NIE commitują.

KOLEJNOŚĆ BLOKAD każdego zapisu (zablokuj): blokada tras (routes.zablokuj_trasy — razem ze świeżą trasą i jej
przystankami) → blokada deklaracji paczek (paczki.zablokuj_deklaracje) → zamówienia FOR UPDATE rosnąco po id
(blokady_zamowien.zablokuj_zamowienia) → paczki i pozycje każdego zamówienia (paczki.zablokuj_stan) → dopiero
zapisy. Decyzje zapadają na odczycie bieżącym (REPEATABLE READ: migawka sprzed czekania na blokady jest nieświeża).
Blokada deklaracji jest potrzebna, bo zapis Dostawy czyta paczki odczytem blokującym (blokady luk indeksu
prod_packages), a deklaracja paczek wstawia nowe paczki w te luki: bez wspólnej blokady zakończenie załadunku
(wiele zamówień) i deklaracja na zamówieniu z tej samej trasy mogłyby się zakleszczyć. Nikt nie bierze blokady
deklaracji przed blokadą tras, więc ta para nie tworzy cyklu.

Każdy zapis blokuje zamówienia CAŁEJ trasy, nie tylko przystanku, którego dotyczy: telefon dostaje w odpowiedzi
pełną trasę (dostawa_widok.trasa_po_zapisie) i ma ona być bieżąca także dla pozostałych przystanków (dwa telefony
na jednej trasie). Zwykły odczyt po blokadach widziałby migawkę sprzed czekania na nie, a blokujący odczyt cudzych
paczek bez blokady ich zamówienia odwróciłby kolejność blokad (reguła unieważniania: zamówienie → paczki →
pozycje). Zamówienia z trasy zatwierdzonej i dalej nie mają już pracy stanowisk, więc szersza blokada nikogo
realnie nie wstrzymuje (Base. i doróbka czekają kilka milisekund).
"""
from extensions import db
from modules.production.logistics.models import LogisticsLog, RouteStop
from modules.production.logistics.services import bl_sync, delivery, paczki, routes
from modules.production.logistics.services.delivery import LogistykaBlad
from modules.production.logistics.services.weryfikacja import _notatka
from modules.production.models import ProductionOrder, ProductionPackage, ProductionProduct, get_local_now
from modules.production.services import blokady_zamowien

STANOWISKO = 'delivery'
METODY = ProductionPackage.SPOSOBY_POTWIERDZENIA   # ('skan', 'reczne')
POWODY_ZOSTAJE = {
    'niespakowane': u'Niespakowane',
    'niezweryfikowane': u'Niezweryfikowane',
    'brak_miejsca': u'Brak miejsca',
    'uszkodzone': u'Uszkodzone',
    'inne': u'Inne',
}
POWODY_NIEDOSTARCZENIA = {
    'brak_klienta': u'Brak klienta',
    'odmowa': u'Odmowa przyjęcia',
    'brak_dojazdu': u'Brak dojazdu',
    'uszkodzenie': u'Uszkodzenie',
    'inne': u'Inne',
}
# Przystanek odznaczony w oknie „Odhacz jako wykonaną” panelu tras (spec 9.7) — tylko panel, nie telefon.
POWOD_ODHACZENIA = 'odhaczone_w_panelu'
ETYKIETA_ODHACZENIA = u'Odhaczone w panelu'
NAZWY_STATUSOW_TRASY = {'robocza': u'Robocza', 'zatwierdzona': u'Zatwierdzona', 'zaladowana': u'Załadowana',
                        'w_trasie': u'W trasie', 'wykonana': u'Wykonana'}


class DostawaBlad(LogistykaBlad):
    """
    Odmowa Dostawy: `kod` dla appki (`error`), komunikat dla człowieka (`message`), `dane` — pola dodatkowe
    odpowiedzi (np. `braki`). Dziedziczy po LogistykaBlad, więc panel tras (trasy_api._odmowa) obsługuje ją bez zmian.
    """

    def __init__(self, kod, komunikat, status=409, dane=None):
        super().__init__(komunikat, status=status, dane=dane)
        self.kod = kod


def waliduj_powod(powod, slownik):
    """Powód z JSON-a. Typ sprawdzamy przed słownikiem (lista nie jest hashowalna), 422 jest zapamiętywane."""
    if not isinstance(powod, str) or powod not in slownik:
        raise DostawaBlad('invalid_reason', u'Powód: {}.'.format(u', '.join(sorted(slownik))), status=422)
    return powod


def waliduj_metode(metoda):
    """`skan` (domyślnie) albo `reczne`; inaczej 422 invalid_method."""
    wynik = metoda or 'skan'
    if not isinstance(wynik, str) or wynik not in METODY:
        raise DostawaBlad('invalid_method', u'Sposób załadunku: „skan” albo „reczne”.', status=422)
    return wynik


def _numer(order):
    return order.internal_order_number or u'#{}'.format(order.id)


def _wymagaj_statusu(trasa, *statusy):
    if trasa.status not in statusy:
        raise DostawaBlad('route_status', u'Trasa „{}” jest {} — ta operacja nie jest dostępna.'.format(
            trasa.name, NAZWY_STATUSOW_TRASY.get(trasa.status, trasa.status).lower()))


def _przystanek(trasa, order_id):
    """Przystanek zamówienia na świeżej trasie (spod blokady) albo 404 stop_not_found."""
    stop = next((s for s in trasa.stops if s.order_id == order_id), None)
    if stop is None:
        raise DostawaBlad('stop_not_found', u'Tego zamówienia nie ma na trasie „{}”.'.format(trasa.name), status=404)
    return stop


def _zaladowane_na_trase(aktualne, trasa):
    """Aktualne paczki zamówienia załadowane na TĘ trasę."""
    return [p for p in aktualne if p.loaded_at is not None and p.loaded_route_id == trasa.id]


def _log_trasy(trasa, stary, nowy, teraz, user_id=None, worker_id=None, device_id=None):
    """Wpis `trasa_status` przy każdym przystanku świeżej trasy (wystarczy order_id — bez czytania zamówień)."""
    for s in trasa.stops:
        db.session.add(LogisticsLog(order_id=s.order_id, action='trasa_status', old_value=stary, new_value=nowy,
                                    route_id=trasa.id, user_id=user_id, worker_id=worker_id, device_id=device_id,
                                    created_at=teraz))


def zablokuj(route):
    """
    Blokady zapisu Dostawy w jednej kolejności (docstring modułu) dla wszystkich przystanków trasy. Zwraca (świeża
    trasa, {order_id: zamówienie}, {order_id: [aktualne paczki]}) — wszystko z odczytu bieżącego. Wołana drugi raz
    w tej samej transakcji (odpowiedź po zapisie) niczego nie czeka: blokady są już trzymane.
    """
    trasa = routes.zablokuj_trasy(route)
    paczki.zablokuj_deklaracje()
    zamowienia = {o.id: o for o in blokady_zamowien.zablokuj_zamowienia([s.order_id for s in trasa.stops])}
    pakunki = {order_id: paczki.zablokuj_stan(zamowienia[order_id]) for order_id in sorted(zamowienia)}
    return trasa, zamowienia, pakunki


def _paczka_niewazna():
    return DostawaBlad('package_void', u'Etykieta nieaktualna — paczki zadeklarowano ponownie.')


def _paczka_spoza_trasy(order_id, trasa):
    """409 package_not_on_route z nazwą trasy, na której jest zamówienie paczki, albo „bez trasy” (spec 9.3)."""
    order = ProductionOrder.query.get(order_id)     # tylko do komunikatu — zwykłe odczyty wystarczą
    inna = routes.przystanek_zamowienia(order_id)
    nazwa = inna.route.name if inna is not None else None
    gdzie = u'na trasie „{}”'.format(nazwa) if nazwa else u'bez trasy'
    return DostawaBlad('package_not_on_route', u'Paczka zamówienia {} nie jedzie trasą „{}” — zamówienie jest {}.'
                       .format(_numer(order), trasa.name, gdzie), dane={'route_name': nazwa})


def _niezweryfikowane(order):
    return DostawaBlad('order_not_verified', u'Zamówienie {} nie jest zweryfikowane — na auto ładujemy tylko '
                       u'zweryfikowane paczki.'.format(_numer(order)))


def _wiersz_paczki(package_id):
    """(order_id, voided_at) paczki zwykłym odczytem; brak paczki → 404 package_not_found."""
    wiersz = (db.session.query(ProductionPackage.order_id, ProductionPackage.voided_at)
              .filter(ProductionPackage.id == package_id).first())
    if wiersz is None:
        raise DostawaBlad('package_not_found', u'Nie ma paczki P-{}.'.format(package_id), status=404)
    return wiersz


def _wstepna_odmowa(route, wiersz):
    """
    Odmowa z migawki, PRZED blokadami (lekcja 1213 z kroku 4.3: nie czekamy na blokady, skoro i tak odmówimy):
    paczka unieważniona (to się nie cofa) albo zamówienie z TEJ trasy, które w migawce nie jest zweryfikowane.
    Paczkę zamówienia spoza tej trasy przepuszczamy — odmowa z nazwą jego trasy zapada pod blokadami. Migawka może
    się spóźniać o chwilę (weryfikacja zapisana tuż przed skanem): wtedy appka pokazuje odmowę, a ponowny skan
    przechodzi — 409 nie jest zapamiętywane.
    """
    if wiersz.voided_at is not None:
        raise _paczka_niewazna()
    trasa_zamowienia = (db.session.query(RouteStop.route_id)
                        .filter(RouteStop.order_id == wiersz.order_id).scalar())
    if trasa_zamowienia != route.id:
        return
    statusy = [s for (s,) in db.session.query(ProductionProduct.current_status)
               .filter(ProductionProduct.order_id == wiersz.order_id,
                       ProductionProduct.current_status != 'anulowane')]
    if not statusy or any(s != 'zweryfikowane' for s in statusy):
        raise _niezweryfikowane(ProductionOrder.query.get(wiersz.order_id))


def zaladuj_paczke(route, package_id, metoda='skan', worker_id=None, device_id=None, teraz=None):
    """
    Skan albo ręczne odhaczenie paczki przy załadunku (spec 9.3). Zwraca (paczka, zmieniono). Trasa zatwierdzona,
    paczka ważna, jej zamówienie na TEJ trasie i zweryfikowane, przystanek bez „Zostaje” (inaczej 409 stop_stays —
    bez cichego zdejmowania oznaczenia). Ponowny skan = bez zmian. Pozycje zostają 'zweryfikowane' — 'zaladowane'
    dostają dopiero przy zakończeniu załadunku.
    """
    metoda = waliduj_metode(metoda)
    wiersz = _wiersz_paczki(package_id)
    _wstepna_odmowa(route, wiersz)
    trasa, zamowienia, _pakunki = zablokuj(route)
    _wymagaj_statusu(trasa, 'zatwierdzona')
    order = zamowienia.get(wiersz.order_id)
    if order is None:
        raise _paczka_spoza_trasy(wiersz.order_id, trasa)
    stop = _przystanek(trasa, order.id)
    paczka = (ProductionPackage.query.filter(ProductionPackage.id == package_id)
              .with_for_update().populate_existing().one())
    if paczka.voided_at is not None:
        raise _paczka_niewazna()
    if stop.stays_reason:
        raise DostawaBlad('stop_stays', u'Zamówienie {} ma oznaczenie „Zostaje” ({}) — najpierw je zdejmij.'.format(
            _numer(order), POWODY_ZOSTAJE.get(stop.stays_reason, stop.stays_reason)))
    aktywne = delivery.aktywne_produkty(order)
    if not aktywne or any(p.current_status != 'zweryfikowane' for p in aktywne):
        raise _niezweryfikowane(order)
    if paczka.loaded_at is not None and paczka.loaded_route_id == trasa.id:
        return paczka, False
    teraz = teraz or get_local_now()
    paczka.loaded_at = teraz
    paczka.loaded_by_worker_id = worker_id
    paczka.loaded_method = metoda
    paczka.loaded_route_id = trasa.id
    delivery.podbij_pozycje(order, teraz)   # ETag szczegółów trasy w telefonie i kolejek tabletów
    return paczka, True


def rozladuj_paczke(route, package_id, worker_id=None, device_id=None, teraz=None):
    """Cofnięcie pomyłki przed zakończeniem załadunku (spec 9.3). Zwraca (paczka, zmieniono); niezaładowana → bez zmian."""
    wiersz = _wiersz_paczki(package_id)
    trasa, zamowienia, _pakunki = zablokuj(route)
    _wymagaj_statusu(trasa, 'zatwierdzona')
    order = zamowienia.get(wiersz.order_id)
    if order is None:
        raise _paczka_spoza_trasy(wiersz.order_id, trasa)
    paczka = (ProductionPackage.query.filter(ProductionPackage.id == package_id)
              .with_for_update().populate_existing().one())
    if paczka.loaded_at is None or paczka.loaded_route_id != trasa.id:
        return paczka, False
    paczki.wyczysc_zaladunek([paczka])
    delivery.podbij_pozycje(order, teraz or get_local_now())
    return paczka, True


def ustaw_zostaje(route, order_id, powod, notatka=None, worker_id=None, device_id=None, teraz=None):
    """
    „Zostaje” z powodem (spec 9.3) — przystanek zejdzie z trasy przy zakończeniu załadunku. Czyści znaczniki
    załadunku paczek zamówienia na tej trasie. Zwraca True, gdy coś zmieniła (ten sam powód i notatka — bez zmian).
    """
    waliduj_powod(powod, POWODY_ZOSTAJE)
    notatka = _notatka(notatka)
    trasa, zamowienia, pakunki = zablokuj(route)
    _wymagaj_statusu(trasa, 'zatwierdzona')
    stop = _przystanek(trasa, order_id)
    zmieniono = (stop.stays_reason, stop.stays_note) != (powod, notatka)
    stop.stays_reason, stop.stays_note = powod, notatka
    if paczki.wyczysc_zaladunek(_zaladowane_na_trase(pakunki.get(order_id, []), trasa)):
        zmieniono = True
    if zmieniono and order_id in zamowienia:
        delivery.podbij_pozycje(zamowienia[order_id], teraz or get_local_now())
    return zmieniono


def zdejmij_zostaje(route, order_id, worker_id=None, device_id=None, teraz=None):
    """Zdjęcie „Zostaje” przed zakończeniem załadunku. Zwraca True, gdy przystanek je miał."""
    trasa, zamowienia, _pakunki = zablokuj(route)
    _wymagaj_statusu(trasa, 'zatwierdzona')
    stop = _przystanek(trasa, order_id)
    if stop.stays_reason is None and stop.stays_note is None:
        return False
    stop.stays_reason, stop.stays_note = None, None
    if order_id in zamowienia:
        delivery.podbij_pozycje(zamowienia[order_id], teraz or get_local_now())
    return True


def _opis_brakow(braki):
    numery = u', '.join(b['internal_order_number'] or u'#{}'.format(b['order_id']) for b in braki)
    return u'Nie wszystko jest załadowane: {} — załaduj paczki albo oznacz przystanek „Zostaje”.'.format(numery)


def zakoncz_zaladunek(route, worker_id=None, device_id=None, teraz=None):
    """
    „Zakończ załadunek” (spec 9.3). Każdy przystanek musi być załadowany (co najmniej jedna aktualna paczka, wszystkie
    załadowane na tę trasę, pozycje nadal 'zweryfikowane') albo mieć „Zostaje”; przystanek zamówienia anulowanego
    w całości schodzi z trasy sam. Braki → 409 loading_incomplete z listą `braki`; nic załadowanego → 409
    nothing_loaded (trasę, z której nic nie jedzie, logistyk cofa albo usuwa w panelu).

    Pod blokadami: „Zostaje” → zdjęcie z trasy (routes.usun_przystanek, log `zostaje` z powodem); załadowane →
    pozycje 'zaladowane', Base. 524520 (dopychacz po commicie), log `zaladunek`; trasa → 'zaladowana', kto i kiedy.
    Zwraca (świeża trasa, usuniete: [{order_id, internal_order_number, reason}]).
    """
    trasa, zamowienia, pakunki = zablokuj(route)
    _wymagaj_statusu(trasa, 'zatwierdzona')
    braki, zostaja, anulowane, zaladowane = [], [], [], []
    for stop in list(trasa.stops):
        order = zamowienia.get(stop.order_id)
        if order is None:
            continue
        aktywne = delivery.aktywne_produkty(order)
        if not aktywne:
            anulowane.append(order)
            continue
        if stop.stays_reason:
            zostaja.append((stop.stays_reason, stop.stays_note, order))
            continue
        aktualne = pakunki.get(order.id, [])
        na_aucie = _zaladowane_na_trase(aktualne, trasa)
        wpis = {'order_id': order.id, 'internal_order_number': order.internal_order_number,
                'loaded': len(na_aucie), 'total': len(aktualne)}
        if not aktualne:
            braki.append(dict(wpis, reason='bez_paczek'))
        elif any(p.current_status != 'zweryfikowane' for p in aktywne):
            # Przed brakami załadunku: cofnięta weryfikacja czyści znaczniki załadunku, a kierowcy ważniejsze jest,
            # że tego zamówienia w ogóle nie załaduje (skan dostanie order_not_verified).
            braki.append(dict(wpis, reason='niezweryfikowane'))
        elif len(na_aucie) < len(aktualne):
            braki.append(dict(wpis, reason='niezaladowane'))
        else:
            zaladowane.append(order)
    if braki:
        raise DostawaBlad('loading_incomplete', _opis_brakow(braki), dane={'braki': braki})
    if not zaladowane:
        raise DostawaBlad('nothing_loaded', u'Na trasie „{}” nic nie jest załadowane — trasę, z której nic nie jedzie, '
                          u'cofnij albo usuń w panelu tras.'.format(trasa.name))
    teraz = teraz or get_local_now()
    usuniete = []
    for powod, notatka, order in zostaja:
        etykieta = POWODY_ZOSTAJE.get(powod, powod)
        delivery.zapisz_log(order, 'zostaje', None, powod,
                            note=(etykieta + (u': ' + notatka if notatka else u''))[:255],
                            route_id=trasa.id, worker_id=worker_id, device_id=device_id, teraz=teraz)
        usuniete.append({'order_id': order.id, 'internal_order_number': order.internal_order_number,
                         'reason': powod})
        routes.usun_przystanek(trasa, order.id, note=u'zostaje: ' + etykieta, wymagaj_roboczej=False,
                               worker_id=worker_id, device_id=device_id)
    for order in anulowane:
        usuniete.append({'order_id': order.id, 'internal_order_number': order.internal_order_number,
                         'reason': 'anulowane'})
        routes.usun_przystanek(trasa, order.id, note=u'anulowane', wymagaj_roboczej=False,
                               worker_id=worker_id, device_id=device_id)
    trasa = routes.zablokuj_trasy(trasa)   # świeże przystanki po zdjęciach (ta sama transakcja, bez czekania)
    for order in zaladowane:
        for p in delivery.aktywne_produkty(order):
            p.current_status = 'zaladowane'
        bl_sync.oznacz_zaladowane(order)
        bl_sync.zaplanuj_po_commicie(order.id)
        delivery.zapisz_log(order, 'zaladunek', None, 'zaladowane', note=paczki.opis_paczek(pakunki[order.id]),
                            route_id=trasa.id, worker_id=worker_id, device_id=device_id, teraz=teraz)
        delivery.podbij_pozycje(order, teraz)
    trasa.status = 'zaladowana'
    trasa.loaded_at = teraz
    trasa.loaded_by_worker_id = worker_id
    _log_trasy(trasa, 'zatwierdzona', 'zaladowana', teraz, worker_id=worker_id, device_id=device_id)
    return trasa, usuniete


def ruszaj(route, worker_id=None, device_id=None, teraz=None):
    """
    „Ruszam w trasę” (spec 9.4): trasa załadowana → w_trasie, kto i kiedy, Base. 149763 dla zamówień z pozycjami
    załadowanymi, log `wyjazd` (to on zapisuje tę zmianę statusu trasy — bez osobnego `trasa_status`). Trasa już
    w trasie → bez zmian (powtórka z kolejki offline). Zwraca (trasa, zmieniono).
    """
    trasa, zamowienia, _pakunki = zablokuj(route)
    if trasa.status == 'w_trasie':
        return trasa, False
    _wymagaj_statusu(trasa, 'zaladowana')
    teraz = teraz or get_local_now()
    trasa.status = 'w_trasie'
    trasa.departed_at = teraz
    trasa.departed_by_worker_id = worker_id
    for stop in trasa.stops:
        order = zamowienia.get(stop.order_id)
        if order is None:
            continue
        if any(p.current_status == 'zaladowane' for p in delivery.aktywne_produkty(order)):
            bl_sync.oznacz_wyslane(order)
            bl_sync.zaplanuj_po_commicie(order.id)
        delivery.zapisz_log(order, 'wyjazd', 'zaladowana', 'w_trasie', route_id=trasa.id, worker_id=worker_id,
                            device_id=device_id, teraz=teraz)
        delivery.podbij_pozycje(order, teraz)
    return trasa, True


def cofnij_zaladunek(route, user_id=None, teraz=None):
    """
    „Cofnij załadunek” z panelu tras (spec 4.5, 9.7): trasa załadowana → zatwierdzona, pozycje 'zaladowane' →
    'zweryfikowane', znaczniki załadunku czyszczone, Base. 417343 dla zamówień, które były załadowane, log
    `zaladunek` (zaladowane → brak) i `trasa_status`. Zwraca świeżą trasę.
    """
    trasa, zamowienia, pakunki = zablokuj(route)
    _wymagaj_statusu(trasa, 'zaladowana')
    teraz = teraz or get_local_now()
    for stop in trasa.stops:
        order = zamowienia.get(stop.order_id)
        if order is None:
            continue
        cofniete = [p for p in delivery.aktywne_produkty(order) if p.current_status == 'zaladowane']
        for p in cofniete:
            p.current_status = 'zweryfikowane'
        paczki.wyczysc_zaladunek(pakunki.get(order.id, []))
        if cofniete:
            bl_sync.oznacz_planowana_trasa(order)
            bl_sync.zaplanuj_po_commicie(order.id)
            delivery.zapisz_log(order, 'zaladunek', 'zaladowane', None, note=u'cofnięty w panelu', route_id=trasa.id,
                                user_id=user_id, teraz=teraz)
        delivery.podbij_pozycje(order, teraz)
    trasa.status = 'zatwierdzona'
    trasa.loaded_at = None
    trasa.loaded_by_worker_id = None
    _log_trasy(trasa, 'zaladowana', 'zatwierdzona', teraz, user_id=user_id)
    return trasa
```

- [ ] **Step 5: Testy przechodzą**

Run: `PYTEST tests/test_dostawa_zaladunek.py tests/test_logistyka_trasy_serwis.py tests/test_logistyka_trasy_api.py`
Expected: PASS (`usun_przystanek` z nowymi parametrami nie zmienia zachowania dotychczasowych wołających).

- [ ] **Step 6: Pełny pakiet**

Run: `PYTEST tests/`
Expected: `wynik Task 2 + 21 passed, 3 skipped`.

- [ ] **Step 7: Commit**

```bash
git add modules/production/logistics/services/dostawa.py modules/production/logistics/services/routes.py \
  tests/test_dostawa_zaladunek.py
git commit -m "feat(production): serwis Dostawy - zaladunek, Zostaje, zakonczenie zaladunku, wyjazd" \
  -m "Krok 4.4 logistyki: services/dostawa.py z jedna kolejnoscia blokad (trasy, deklaracje, zamowienia rosnaco, paczki, pozycje), bramka weryfikacji przy skanie z wstepna odmowa z migawki, Zostaje, zakonczenie zaladunku z lista brakow, Ruszam i Cofnij zaladunek z panelu." \
  -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Dostarczenia, odhaczenie z Base., „Cofnij dostarczenie” i reguła transportu po „dostarczone”

**Files:**
- Modify: `modules/production/logistics/services/dostawa.py` (dostarczenie, niedostarczenie, cofnięcie, odhaczenie)
- Modify: `modules/production/logistics/services/delivery.py:23-31` (docstring `LogistykaBlad`), `:47-55` (docstring `wszystkie_spakowane`), `:72-117` (`zamkniecie_wyliczone`, `przelicz_zamkniecie`), `:633-700` (`przelicz_otwarte`)
- Modify: `modules/production/logistics/services/routes.py` (docstring `zablokuj_trasy` :152-156; `usun_przystanek` :580-594; usuń `_odmowa_niespakowanych` :635-643, `wykonaj` :646-696, `przywroc` :699-713)
- Modify: `modules/production/logistics/routers/trasy_api.py:22` (import), `:229-256` (`_akcja`), `:550-563` (`/complete`, `/restore` → `/stops/<oid>/undo-delivered`)
- Create: `tests/test_dostawa_dostarczenia.py`
- Modify (testy etapu 3 na nowe wejścia): `tests/test_logistyka_trasy_serwis.py`, `tests/test_logistyka_trasy_api.py`, `tests/test_logistyka_kierowcy.py`, `tests/test_logistyka_routimo.py`, `tests/test_logistyka_trasy_integracja.py`, `tests/test_logistyka_cron.py`, `tests/test_weryfikacja_cykl.py`

**Interfaces:**
- Consumes: Task 3 (`zablokuj`, `_przystanek`, `_wymagaj_statusu`, `_numer`, `_log_trasy`, `DostawaBlad`, `waliduj_powod`, `POWODY_NIEDOSTARCZENIA`, `POWOD_ODHACZENIA`, `ETYKIETA_ODHACZENIA`, `_notatka`); `routes._lista_id`, `routes.AKTYWNE`, `routes.usun_przystanek(..., worker_id=, device_id=)`; `bl_sync.oznacz_dostarczone/oznacz_wyslane/oznacz_planowana_trasa`, `bl_sync.zaplanuj_po_commicie`, `bl_sync.wyslij_zaplanowane`.
- Produces: `dostawa.dostarcz(route, order_id, worker_id=None, device_id=None, teraz=None) -> (trasa, zmieniono, zamknieta)`; `dostawa.nie_dostarcz(route, order_id, powod, notatka=None, worker_id=None, device_id=None, teraz=None) -> (trasa, zamknieta)`; `dostawa.cofnij_dostarczenie(route, order_id, z_telefonu=False, user_id=None, worker_id=None, device_id=None, teraz=None) -> (trasa, zmieniono)`; `dostawa.odhacz(route, dostarczone_ids, user_id=None, teraz=None) -> {'dostarczone': [...], 'niedostarczone': [...]}`; `delivery.zamkniecie_wyliczone(order)` i `delivery.przelicz_zamkniecie(order, teraz=None)` BEZ parametru `trasa`; endpoint panelu `POST /production/api/logistics/routes/<rid>/stops/<oid>/undo-delivered`; `routes.wykonaj` i `routes.przywroc` oraz `POST …/routes/<rid>/restore` przestają istnieć.

- [ ] **Step 1: Testy, które padną**

Create `tests/test_dostawa_dostarczenia.py`:

```python
# -*- coding: utf-8 -*-
"""Dostarczenia (logistyka etap 4, krok 4.4, spec 9.5, 9.7, 4.5 i 4.6): „Dostarczone”, „Niedostarczone”, cofnięcie
dostarczenia z telefonu i z panelu, automatyczne zamknięcie trasy, odhaczenie z panelu ze statusami Base. i reguła
zamknięcia transportu po „dostarczone”."""
import pytest

from extensions import db
from modules.production.logistics import sposoby as s
from modules.production.logistics.models import LogisticsLog, RouteStop
from modules.production.logistics.services import bl_sync, delivery, dostawa, routes
from tests.dostawa_pomocnicze import T0, trasa, zaladuj_wprost, zamowienie_z_paczkami
from tests.logistyka_fixtures import BASE, app, client, pojazd, zamowienie  # noqa: F401

T1 = T0.replace(hour=9)
T2 = T0.replace(hour=10)


def _blad(funkcja, *args, **kwargs):
    with pytest.raises(dostawa.DostawaBlad) as e:
        funkcja(*args, **kwargs)
    db.session.rollback()
    return e.value


def _zaladowane():
    """(zamówienie z pozycjami załadowanymi, [paczki])."""
    return zamowienie_z_paczkami(statusy=('zaladowane', 'zaladowane'))


def _w_trasie(*zamowienia):
    """Trasa w drodze z zamówieniami (order, paczki) — paczki na aucie."""
    t = trasa([o for o, _ in zamowienia], status='w_trasie', loaded_at=T0, departed_at=T0)
    for _o, lista_paczek in zamowienia:
        zaladuj_wprost(lista_paczek, t, kto_id=7)
    return t


# --- „Dostarczone” --------------------------------------------------------------------------------------

def test_dostarczenie(app):
    a, b = _zaladowane(), _zaladowane()
    t = _w_trasie(a, b)
    order = a[0]
    trasa_po, zmieniono, zamknieta = dostawa.dostarcz(t, order.id, worker_id=7, device_id=3, teraz=T1)
    db.session.commit()
    assert (zmieniono, zamknieta, trasa_po.status) == (True, False, 'w_trasie')
    assert [p.current_status for p in order.products] == ['dostarczone', 'dostarczone']
    stop = RouteStop.query.filter_by(order_id=order.id).one()
    assert (stop.delivered_at, stop.delivered_by_worker_id) == (T1, 7)
    assert order.bl_status_pending_id == 149778 and order.logistics_closed_at == T1
    wpis = LogisticsLog.query.filter_by(order_id=order.id, action='dostarczone').one()
    assert (wpis.old_value, wpis.new_value, wpis.worker_id, wpis.device_id) == ('zaladowane', 'dostarczone', 7, 3)


def test_ostatnie_dostarczenie_zamyka_trase(app):
    a, b = _zaladowane(), _zaladowane()
    t = _w_trasie(a, b)
    dostawa.dostarcz(t, a[0].id, worker_id=7, teraz=T1)
    trasa_po, _zmieniono, zamknieta = dostawa.dostarcz(t, b[0].id, worker_id=7, teraz=T2)
    db.session.commit()
    assert zamknieta is True and trasa_po.status == 'wykonana'
    assert (trasa_po.completed_at, trasa_po.completed_by) == (T2, None)   # zamknął telefon
    for order, _ in (a, b):
        wpis = LogisticsLog.query.filter_by(order_id=order.id, action='trasa_status').one()
        assert (wpis.old_value, wpis.new_value, wpis.worker_id) == ('w_trasie', 'wykonana', 7)


def test_ponowne_dostarczenie_bez_zmian(app):
    """Review Focus 4: powtórka „Dostarczone” — także po zamknięciu trasy tym dostarczeniem — bez zmian, bez drugiego
    statusu Base. i drugiego wpisu w logu."""
    a = _zaladowane()
    t = _w_trasie(a)
    dostawa.dostarcz(t, a[0].id, worker_id=7, teraz=T1)
    db.session.commit()
    a[0].bl_status_pending_id = None   # dopychacz wysłał
    db.session.commit()
    trasa_po, zmieniono, zamknieta = dostawa.dostarcz(t, a[0].id, worker_id=8, teraz=T2)
    assert (zmieniono, zamknieta, trasa_po.status) == (False, False, 'wykonana')
    assert a[0].bl_status_pending_id is None
    assert LogisticsLog.query.filter_by(order_id=a[0].id, action='dostarczone').count() == 1


@pytest.mark.parametrize('statusy', [('zaladowane', 'czeka_na_wyciecie'), ('anulowane', 'anulowane')])
def test_dostarczenie_zamowienia_spoza_zaladunku_409(app, statusy):
    """Review Focus 5: zamówienie wróciło do produkcji (doróbka) albo zostało anulowane w trakcie jazdy —
    „Dostarczone” 409 order_status; przystanek rozlicza się „Niedostarczone”."""
    order, lista_paczek = zamowienie_z_paczkami(statusy=statusy)
    t = _w_trasie((order, lista_paczek))
    e = _blad(dostawa.dostarcz, t, order.id, worker_id=7)
    assert e.kod == 'order_status' and order.internal_order_number in e.komunikat
    assert RouteStop.query.filter_by(order_id=order.id).one().delivered_at is None


def test_dostarczenie_wymaga_trasy_w_drodze(app):
    order, _ = _zaladowane()
    t = trasa([order], status='zaladowana')
    assert _blad(dostawa.dostarcz, t, order.id).kod == 'route_status'
    e = _blad(dostawa.dostarcz, t, 987654)
    assert (e.kod, e.status) == ('stop_not_found', 404)


# --- „Niedostarczone” ------------------------------------------------------------------------------------

def test_niedostarczenie_wraca_zamowienie_do_puli(app):
    a, b = _zaladowane(), _zaladowane()
    t = _w_trasie(a, b)
    order, lista_paczek = a
    trasa_po, zamknieta = dostawa.nie_dostarcz(t, order.id, 'brak_klienta', u' nikt  nie otworzył ', worker_id=7,
                                               device_id=3, teraz=T1)
    db.session.commit()
    assert zamknieta is False and [st.order_id for st in trasa_po.stops] == [b[0].id]
    assert [p.current_status for p in order.products] == ['zweryfikowane', 'zweryfikowane']
    assert all(p.loaded_at is None and p.loaded_route_id is None for p in lista_paczek)
    assert order.bl_status_pending_id == 417343 and order.logistics_closed_at is None
    wpis = LogisticsLog.query.filter_by(order_id=order.id, action='niedostarczone').one()
    assert (wpis.new_value, wpis.note, wpis.worker_id) == ('brak_klienta', u'Brak klienta: nikt nie otworzył', 7)
    usuniete = LogisticsLog.query.filter_by(order_id=order.id, action='trasa_usuniete').one()
    assert (usuniete.note, usuniete.worker_id, usuniete.device_id) == ('niedostarczone', 7, 3)
    assert routes.przystanek_zamowienia(order.id) is None


def test_rozliczenie_ostatniego_przystanku_niedostarczeniem_zamyka_trase(app):
    a, b = _zaladowane(), _zaladowane()
    t = _w_trasie(a, b)
    dostawa.dostarcz(t, a[0].id, worker_id=7, teraz=T1)
    trasa_po, zamknieta = dostawa.nie_dostarcz(t, b[0].id, 'odmowa', worker_id=7, teraz=T2)
    db.session.commit()
    assert zamknieta is True and trasa_po.status == 'wykonana'
    assert [st.order_id for st in trasa_po.stops] == [a[0].id]


def test_niedostarczenie_odmowy(app):
    a, b = _zaladowane(), _zaladowane()
    t = _w_trasie(a, b)
    e = _blad(dostawa.nie_dostarcz, t, a[0].id, 'zgubione')
    assert (e.kod, e.status) == ('invalid_reason', 422)
    dostawa.dostarcz(t, a[0].id, worker_id=7)
    db.session.commit()
    assert _blad(dostawa.nie_dostarcz, t, a[0].id, 'inne').kod == 'stop_delivered'
    stoi, _ = _zaladowane()
    zaladowana = trasa([stoi], status='zaladowana')
    assert _blad(dostawa.nie_dostarcz, zaladowana, stoi.id, 'inne').kod == 'route_status'


# --- „Cofnij dostarczenie” ---------------------------------------------------------------------------------

def test_telefon_cofa_tylko_ostatnie_dostarczenie(app):
    a, b, c = _zaladowane(), _zaladowane(), _zaladowane()
    t = _w_trasie(a, b, c)
    dostawa.dostarcz(t, a[0].id, worker_id=7, teraz=T1)
    dostawa.dostarcz(t, b[0].id, worker_id=7, teraz=T2)
    db.session.commit()
    assert _blad(dostawa.cofnij_dostarczenie, t, a[0].id, z_telefonu=True, worker_id=7).kod == 'not_last_delivery'
    order = b[0]
    trasa_po, zmieniono = dostawa.cofnij_dostarczenie(t, order.id, z_telefonu=True, worker_id=7, device_id=3,
                                                      teraz=T2)
    db.session.commit()
    assert zmieniono is True and trasa_po.status == 'w_trasie'
    assert [p.current_status for p in order.products] == ['zaladowane', 'zaladowane']
    stop = RouteStop.query.filter_by(order_id=order.id).one()
    assert (stop.delivered_at, stop.delivered_by_worker_id) == (None, None)
    assert order.bl_status_pending_id == 149763 and order.logistics_closed_at is None
    wpis = LogisticsLog.query.filter_by(order_id=order.id, action='dostarczenie_cofniete').one()
    assert (wpis.old_value, wpis.new_value, wpis.worker_id) == ('dostarczone', 'zaladowane', 7)
    assert dostawa.cofnij_dostarczenie(t, order.id, z_telefonu=True)[1] is False   # powtórka bez zmian


def test_remis_chwili_dostarczenia_rozstrzyga_kolejnosc_przystankow(app):
    """DATETIME bez ułamków sekundy: dwa dostarczenia w tej samej sekundzie — ostatni jest dalszy przystanek."""
    a, b, c = _zaladowane(), _zaladowane(), _zaladowane()
    t = _w_trasie(a, b, c)
    dostawa.dostarcz(t, b[0].id, worker_id=7, teraz=T1)
    dostawa.dostarcz(t, a[0].id, worker_id=7, teraz=T1)
    db.session.commit()
    assert _blad(dostawa.cofnij_dostarczenie, t, a[0].id, z_telefonu=True).kod == 'not_last_delivery'
    assert dostawa.cofnij_dostarczenie(t, b[0].id, z_telefonu=True)[1] is True


def test_telefon_cofa_ostatnie_dostarczenie_takze_po_zamknieciu_trasy(app):
    """Review Focus 1, decyzja Konrada 3: ostatnie „Dostarczone” zamknęło trasę, a kierowca pomylił przystanek —
    telefon cofa je, trasa wraca do „w trasie”."""
    a = _zaladowane()
    t = _w_trasie(a)
    dostawa.dostarcz(t, a[0].id, worker_id=7, teraz=T1)
    db.session.commit()
    assert t.status == 'wykonana'
    trasa_po, zmieniono = dostawa.cofnij_dostarczenie(t, a[0].id, z_telefonu=True, worker_id=7, teraz=T2)
    db.session.commit()
    assert zmieniono is True
    assert (trasa_po.status, trasa_po.completed_at, trasa_po.completed_by) == ('w_trasie', None, None)
    assert a[0].logistics_closed_at is None
    assert [w.new_value for w in LogisticsLog.query.filter_by(order_id=a[0].id, action='trasa_status')
            .order_by(LogisticsLog.id)] == ['wykonana', 'w_trasie']


def test_telefon_nie_cofa_po_odhaczeniu_w_panelu(app):
    """Review Focus 1: trasę odhaczoną w panelu (completed_by = użytkownik) cofa tylko panel."""
    a = _zaladowane()
    t = _w_trasie(a)
    dostawa.odhacz(t, [a[0].id], user_id=1, teraz=T1)
    db.session.commit()
    e = _blad(dostawa.cofnij_dostarczenie, t, a[0].id, z_telefonu=True, worker_id=7)
    assert e.kod == 'route_status' and u'panelu' in e.komunikat
    assert dostawa.cofnij_dostarczenie(t, a[0].id, user_id=1)[1] is True


def test_panel_cofa_dowolne_dostarczenie_bez_sprawdzania_zajetosci(app):
    """Cofnięcie dostarczenia to korekta, nie planowanie — zajęty w tych dniach pojazd go nie blokuje
    (dawne „Przywróć trasę” sprawdzało zajętość)."""
    v = pojazd()
    a, b = _zaladowane(), _zaladowane()
    t = _w_trasie(a, b)
    t.vehicle_id = v.id
    db.session.commit()
    dostawa.dostarcz(t, a[0].id, worker_id=7, teraz=T1)
    dostawa.dostarcz(t, b[0].id, worker_id=7, teraz=T2)
    db.session.commit()
    trasa([], status='zatwierdzona', vehicle_id=v.id)   # ten sam pojazd, ten sam dzień
    trasa_po, zmieniono = dostawa.cofnij_dostarczenie(t, a[0].id, user_id=1, teraz=T2)   # nie ostatnie
    db.session.commit()
    assert zmieniono is True and trasa_po.status == 'w_trasie'
    wpis = LogisticsLog.query.filter_by(order_id=a[0].id, action='dostarczenie_cofniete').one()
    assert (wpis.user_id, wpis.worker_id) == (1, None)


# --- „Odhacz jako wykonaną” ------------------------------------------------------------------------------

def test_odhaczenie_trasy_w_drodze_ze_statusami_base(app):
    """Spec 9.7: zaznaczone → jak „Dostarczone” (149778), odznaczone → jak „Niedostarczone” z powodem
    odhaczone_w_panelu (417343, bo było załadowane); przystanek dostarczony z telefonu zostaje dostarczony."""
    a, b, c = _zaladowane(), _zaladowane(), _zaladowane()
    t = _w_trasie(a, b, c)
    dostawa.dostarcz(t, a[0].id, worker_id=7, teraz=T0)
    db.session.commit()
    wynik = dostawa.odhacz(t, [b[0].id], user_id=1, teraz=T1)
    db.session.commit()
    assert wynik == {'dostarczone': [a[0].id, b[0].id], 'niedostarczone': [c[0].id]}
    assert (t.status, t.completed_at, t.completed_by) == ('wykonana', T1, 1)
    assert [p.current_status for p in b[0].products] == ['dostarczone', 'dostarczone']
    assert b[0].bl_status_pending_id == 149778 and b[0].logistics_closed_at == T1
    assert RouteStop.query.filter_by(order_id=b[0].id).one().delivered_at == T1
    assert RouteStop.query.filter_by(order_id=a[0].id).one().delivered_at == T0          # bez zmian
    assert [p.current_status for p in c[0].products] == ['zweryfikowane', 'zweryfikowane']
    assert c[0].bl_status_pending_id == 417343 and all(p.loaded_at is None for p in c[1])
    wpis = LogisticsLog.query.filter_by(order_id=c[0].id, action='niedostarczone').one()
    assert (wpis.new_value, wpis.note, wpis.user_id) == ('odhaczone_w_panelu', u'Odhaczone w panelu', 1)


def test_odhaczenie_trasy_zatwierdzonej_bez_zaladunku(app):
    """Praca bez telefonu (jak w etapie 3): spakowane prosto na „dostarczone”; odznaczone wraca do puli bez 417343
    (nie było załadowane, a 417343 ma od spakowania)."""
    a = zamowienie_z_paczkami(statusy=('spakowane',), zweryfikowane=False)
    b = zamowienie_z_paczkami(statusy=('spakowane',), zweryfikowane=False)
    t = trasa([a[0], b[0]])
    dostawa.odhacz(t, [a[0].id], user_id=1, teraz=T1)
    db.session.commit()
    assert [p.current_status for p in a[0].products] == ['dostarczone']
    assert a[0].bl_status_pending_id == 149778 and a[0].logistics_closed_at == T1
    wpis = LogisticsLog.query.filter_by(order_id=a[0].id, action='dostarczone').one()
    assert (wpis.old_value, wpis.user_id) == ('spakowane', 1)
    assert [p.current_status for p in b[0].products] == ['spakowane'] and b[0].bl_status_pending_id is None


# --- Reguła transportu ------------------------------------------------------------------------------------

@pytest.mark.parametrize('statusy, zamkniete', [
    (('dostarczone', 'dostarczone'), True),
    (('dostarczone', 'anulowane'), True),
    (('dostarczone', 'zaladowane'), False),
    (('zaladowane',), False),
])
def test_regula_transportu_po_dostarczonych(app, statusy, zamkniete):
    """Spec 4.6 (krok 4.4): transport własny zamyka się po „dostarczone” — reguła nie czyta tras."""
    order = zamowienie(sposob=s.TRANSPORT, statusy=statusy)
    trasa([order], status='wykonana')
    assert delivery.zamkniecie_wyliczone(order) is zamkniete


# --- Panel tras (API) ---------------------------------------------------------------------------------------

def test_panel_cofniecie_dostarczenia_przez_api(app, client):
    a, b = _zaladowane(), _zaladowane()
    t = _w_trasie(a, b)
    dostawa.dostarcz(t, a[0].id, worker_id=7, teraz=T1)
    dostawa.dostarcz(t, b[0].id, worker_id=7, teraz=T2)
    db.session.commit()
    rid, oid = t.id, a[0].id
    r = client.post(BASE + '/routes/%d/stops/%d/undo-delivered' % (rid, oid))
    assert r.status_code == 200, r.get_data()[:300]
    assert r.get_json()['route']['status'] == 'w_trasie'
    r = client.post(BASE + '/routes/%d/stops/%d/undo-delivered' % (rid, 987654))
    assert r.status_code == 404 and r.get_json()['success'] is False
    assert client.post(BASE + '/routes/%d/restore' % rid).status_code == 404   # „Przywróć trasę” zniknęło


def test_panel_uruchamia_dopychacz_base_po_odhaczeniu(app, client, monkeypatch):
    """Odhaczenie z panelu wysyła statusy Base. (zmiana względem etapu 3) — dopychacz rusza po commicie."""
    wywolania = []
    monkeypatch.setattr(bl_sync, 'po_zmianie', lambda ids: wywolania.append(sorted(ids)))
    a = _zaladowane()
    t = _w_trasie(a)
    rid, oid = t.id, a[0].id
    r = client.post(BASE + '/routes/%d/complete' % rid, json={'delivered_order_ids': [oid]})
    assert r.status_code == 200, r.get_data()[:300]
    assert wywolania == [[oid]]
```

Dopisz w `tests/test_logistyka_cron.py` (pod `test_siatka_otwiera_zamkniecia_wbrew_regule`):

```python
def test_siatka_otwiera_transport_z_pozycja_niedostarczona_na_trasie_wykonanej(app):
    """Krok 4.4 (spec 4.6): transport zamyka „dostarczone”, nie trasa wykonana — zamknięty po znaczniku z pozycją
    niedostarczoną wraca na listę otwartych, także na trasie wykonanej."""
    with app.app_context():
        _ustaw_znacznik()
        order = zamowienie(sposob=s.TRANSPORT, statusy=('dostarczone', 'zaladowane'),
                           logistics_closed_at=PO_ZNACZNIKU)
        _na_trasie(order, 'wykonana')
        zmienione, zamkniete = _po_przebiegu([order])
        assert zamkniete == [False] and zmienione == 1
```

- [ ] **Step 2: Testy padają**

Run: `PYTEST tests/test_dostawa_dostarczenia.py tests/test_logistyka_cron.py`
Expected: FAIL — `AttributeError: module … dostawa has no attribute 'dostarcz'` (i `odhacz`, `nie_dostarcz`, `cofnij_dostarczenie`); `test_regula_transportu_po_dostarczonych` — pierwsze dwa warianty (reguła czyta trasę: wykonana zamyka, ale wariant `zaladowane` daje True zamiast False); API — 404 na `/undo-delivered`; nowy test crona — zamówienie zostaje zamknięte.

- [ ] **Step 3: Reguła transportu i siatka crona**

`modules/production/logistics/services/delivery.py`:

```python
def zamkniecie_wyliczone(order):
    """
    Tabela z sekcji 6.2 specu. Transport własny zamyka się po dostarczeniu (krok 4.4, spec 4.6): wszystkie aktywne
    pozycje 'dostarczone' — nadaje je Dostawa (telefon kierowcy albo odhaczenie trasy w panelu). Reguła nie czyta
    tras, więc wołający spod blokady tras nie musi jej już podawać świeżej trasy (dawny parametr `trasa`, resztka O1).
    """
    aktywne = aktywne_produkty(order)
    if not aktywne:
        return True
    sposob = sposoby.normalizuj(order.override_delivery_method)
    if sposob is None or order.repack_required:
        return False
    if sposob == sposoby.KURIER:
        # Kurier kończy cykl po spakowaniu; weryfikacja nie może go z powrotem otworzyć.
        return all(p.current_status in sposoby.STATUSY_PO_SPAKOWANIU for p in aktywne)
    if sposob == sposoby.ODBIOR:
        return order.handed_over_at is not None
    return all(p.current_status == 'dostarczone' for p in aktywne)


def przelicz_zamkniecie(order, teraz=None):
    """Ustawia albo czyści logistics_closed_at. Zwraca True, gdy stan się zmienił."""
    zamkniete = zamkniecie_wyliczone(order)
```
(reszta `przelicz_zamkniecie` bez zmian).

Docstring `LogistykaBlad` — „z odhaczenia trasy, routes.wykonaj” → „z odhaczenia trasy, dostawa.odhacz”; docstring `wszystkie_spakowane` — „routes.wykonaj (odhaczenie trasy)” → „dostawa.odhacz (odhaczenie trasy)”.

`przelicz_otwarte` — docstring, zdanie o M10:
```python
    Siatka bezpieczeństwa dla crona: przelicza zamówienia otwarte oraz zamknięte,
    które znów mają aktywne produkty (Base. dołożył pozycję, doróbka) albo (M10) mają
    transport własny i przystanek na trasie aktywnej (krok 4.4: także załadowanej i w drodze) —
    zamknięte może być tylko zamówienie dostarczone, a samo nie wróci: spakowane lub dalej
    (w całości) nie łapie się na warunek „znów aktywne pozycje”.
```
oraz „(odbiór niewydany, transport bez trasy wykonanej, brak sposobu, przepakowanie)” → „(odbiór niewydany, transport z pozycją niedostarczoną, brak sposobu, przepakowanie)”. W kodzie usuń zapytanie `na_trasach_wykonanych` i zmień warunek transportu:
```python
        sposob = ProductionOrder.override_delivery_method
        warunki_otwarcia.append(and_(
            ProductionOrder.logistics_closed_at > wdrozenie,
            ProductionOrder.products.any(ProductionProduct.current_status != 'anulowane'),
            or_(and_(sposob == sposoby.ODBIOR, ProductionOrder.handed_over_at.is_(None)),
                # Krok 4.4 (spec 4.6): transport zamyka „dostarczone”, nie trasa wykonana.
                and_(sposob == sposoby.TRANSPORT, ProductionOrder.products.any(
                    ProductionProduct.current_status.notin_(('dostarczone', 'anulowane')))),
                sposob.is_(None),
                ProductionOrder.repack_required.is_(True))))
```

- [ ] **Step 4: Dostarczenia, odhaczenie i cofnięcie w `dostawa.py`**

Dopisz na końcu `modules/production/logistics/services/dostawa.py`:

```python
# ── Dostarczenia (trasa w drodze) i odhaczenie z panelu ─────────────────────────────────────────────

def _rozliczona(trasa):
    """Każdy przystanek dostarczony (trasa bez przystanków też — kierowca wrócił ze wszystkim)."""
    return all(s.delivered_at is not None for s in trasa.stops)


def _zamknij_jesli_rozliczona(trasa, teraz, worker_id=None, device_id=None):
    """
    Spec 9.5: brak nierozliczonych przystanków → trasa 'wykonana'. `completed_by` zostaje NULL — zamknął telefon,
    więc kierowca może jeszcze cofnąć ostatnie dostarczenie (decyzja Konrada 3). Zwraca True, gdy zamknęła.
    """
    if trasa.status != 'w_trasie' or not _rozliczona(trasa):
        return False
    trasa.status, trasa.completed_at, trasa.completed_by = 'wykonana', teraz, None
    _log_trasy(trasa, 'w_trasie', 'wykonana', teraz, worker_id=worker_id, device_id=device_id)
    return True


def _oznacz_dostarczone(order, stop, teraz, user_id=None, worker_id=None, device_id=None):
    """Pozycje aktywne → 'dostarczone', przystanek z kto i kiedy, Base. 149778, log `dostarczone`, zamknięcie."""
    aktywne = delivery.aktywne_produkty(order)
    stare = u','.join(sorted({p.current_status for p in aktywne}))[:64]
    for p in aktywne:
        p.current_status = 'dostarczone'
    stop.delivered_at = teraz
    stop.delivered_by_worker_id = worker_id
    bl_sync.oznacz_dostarczone(order)
    bl_sync.zaplanuj_po_commicie(order.id)
    delivery.zapisz_log(order, 'dostarczone', stare, 'dostarczone', route_id=stop.route_id, user_id=user_id,
                        worker_id=worker_id, device_id=device_id, teraz=teraz)
    delivery.podbij_pozycje(order, teraz)
    delivery.przelicz_zamkniecie(order, teraz)


def _wycofaj_z_trasy(trasa, order, aktualne, powod, notatka, teraz, user_id=None, worker_id=None, device_id=None):
    """
    „Niedostarczone” (telefon) i przystanek odznaczony przy odhaczeniu (panel), spec 4.5: zamówienie wraca do puli
    „Transport bez trasy” jako zweryfikowane — pozycje 'zaladowane' → 'zweryfikowane', znaczniki załadunku
    czyszczone, Base. 417343 tylko, gdy było załadowane (zamówienie z trasy zatwierdzonej ma 417343 od spakowania),
    log `niedostarczone` z powodem, zdjęcie z trasy (routes.usun_przystanek: log `trasa_usuniete` z notatką
    „niedostarczone” jak w etapie 3 i przeliczenie zamknięcia).
    """
    cofniete = [p for p in delivery.aktywne_produkty(order) if p.current_status == 'zaladowane']
    for p in cofniete:
        p.current_status = 'zweryfikowane'
    paczki.wyczysc_zaladunek(aktualne)
    if cofniete:
        bl_sync.oznacz_planowana_trasa(order)
        bl_sync.zaplanuj_po_commicie(order.id)
    etykieta = ETYKIETA_ODHACZENIA if powod == POWOD_ODHACZENIA else POWODY_NIEDOSTARCZENIA.get(powod, powod)
    delivery.zapisz_log(order, 'niedostarczone', None, powod,
                        note=(etykieta + (u': ' + notatka if notatka else u''))[:255], route_id=trasa.id,
                        user_id=user_id, worker_id=worker_id, device_id=device_id, teraz=teraz)
    routes.usun_przystanek(trasa, order.id, user_id=user_id, note=u'niedostarczone', wymagaj_roboczej=False,
                           worker_id=worker_id, device_id=device_id)


def dostarcz(route, order_id, worker_id=None, device_id=None, teraz=None):
    """
    „Dostarczone” na przystanku (spec 9.5). Zwraca (trasa, zmieniono, zamknieta). Wszystkie aktywne pozycje muszą być
    'zaladowane' — zamówienie, które wróciło do produkcji albo zostało anulowane w trakcie jazdy, dostaje 409
    order_status (kierowca rozlicza je „Niedostarczone”). Ostatni rozliczony przystanek zamyka trasę. Przystanek już
    dostarczony = bez zmian (powtórka z kolejki offline), także na trasie, którą to dostarczenie zamknęło.
    """
    trasa, zamowienia, _pakunki = zablokuj(route)
    stop = _przystanek(trasa, order_id)
    if stop.delivered_at is not None:
        return trasa, False, False
    _wymagaj_statusu(trasa, 'w_trasie')
    order = zamowienia.get(order_id)
    aktywne = delivery.aktywne_produkty(order) if order is not None else []
    if not aktywne or any(p.current_status != 'zaladowane' for p in aktywne):
        numer = _numer(order) if order is not None else u'#{}'.format(order_id)
        raise DostawaBlad('order_status', u'Zamówienie {} nie jest załadowane — wróciło do produkcji albo zostało '
                          u'anulowane. Rozlicz przystanek jako „Niedostarczone”.'.format(numer))
    teraz = teraz or get_local_now()
    _oznacz_dostarczone(order, stop, teraz, worker_id=worker_id, device_id=device_id)
    return trasa, True, _zamknij_jesli_rozliczona(trasa, teraz, worker_id=worker_id, device_id=device_id)


def nie_dostarcz(route, order_id, powod, notatka=None, worker_id=None, device_id=None, teraz=None):
    """
    „Niedostarczone” z powodem (spec 9.5 i 4.5) — patrz _wycofaj_z_trasy. Przystanek dostarczony → 409
    stop_delivered (najpierw cofnij dostarczenie). Ostatni rozliczony przystanek zamyka trasę. Zwraca
    (trasa, zamknieta). Powtórka po zdjęciu przystanku dostaje 404 stop_not_found (niezapamiętane — appka odświeża
    trasę).
    """
    waliduj_powod(powod, POWODY_NIEDOSTARCZENIA)
    notatka = _notatka(notatka)
    trasa, zamowienia, pakunki = zablokuj(route)
    stop = _przystanek(trasa, order_id)
    _wymagaj_statusu(trasa, 'w_trasie')
    if stop.delivered_at is not None:
        raise DostawaBlad('stop_delivered', u'Przystanek jest już dostarczony — najpierw cofnij dostarczenie.')
    teraz = teraz or get_local_now()
    _wycofaj_z_trasy(trasa, zamowienia[order_id], pakunki.get(order_id, []), powod, notatka, teraz,
                     worker_id=worker_id, device_id=device_id)
    trasa = routes.zablokuj_trasy(trasa)   # świeże przystanki po zdjęciu (ta sama transakcja, bez czekania)
    return trasa, _zamknij_jesli_rozliczona(trasa, teraz, worker_id=worker_id, device_id=device_id)


def cofnij_dostarczenie(route, order_id, z_telefonu=False, user_id=None, worker_id=None, device_id=None,
                        teraz=None):
    """
    „Cofnij dostarczenie” (spec 4.5): pozycje 'dostarczone' → 'zaladowane', przystanek bez kto i kiedy, Base. 149763,
    log `dostarczenie_cofniete`, zamówienie znów otwarte; trasa wykonana wraca do 'w_trasie'. Przystanek
    niedostarczony = bez zmian (powtórka). Zwraca (trasa, zmieniono).

    Panel: dowolny dostarczony przystanek trasy w drodze albo wykonanej, bez sprawdzania zajętości pojazdu
    i kierowcy (korekta, nie planowanie). Telefon (`z_telefonu`): tylko ostatnie dostarczenie (najpóźniejsze
    `delivered_at`, przy remisie dalszy przystanek), także zaraz po automatycznym zamknięciu trasy (decyzja Konrada 3
    — trasa zamknięta telefonem ma `completed_by` NULL); trasę odhaczoną w panelu cofa tylko panel.
    Na trasie odhaczonej bez załadunku (z roboczej albo zatwierdzonej) cofnięcie też daje 'zaladowane' i 'w_trasie'
    (spec 4.5) — logistyk rozlicza potem przystanek ponownym „Odhacz”.
    """
    trasa, zamowienia, _pakunki = zablokuj(route)
    stop = _przystanek(trasa, order_id)
    if stop.delivered_at is None:
        return trasa, False
    _wymagaj_statusu(trasa, 'w_trasie', 'wykonana')
    if z_telefonu:
        if trasa.status == 'wykonana' and trasa.completed_by is not None:
            raise DostawaBlad('route_status', u'Trasę „{}” odhaczono w panelu tras — dostarczenie cofnie tam '
                              u'logistyk.'.format(trasa.name))
        ostatni = max((s for s in trasa.stops if s.delivered_at is not None),
                      key=lambda s: (s.delivered_at, s.position))
        if ostatni.order_id != order_id:
            raise DostawaBlad('not_last_delivery', u'Telefon cofa tylko ostatnie dostarczenie na trasie — starsze '
                              u'cofnie logistyk w panelu tras.')
    teraz = teraz or get_local_now()
    order = zamowienia.get(order_id)
    if order is not None:
        cofniete = [p for p in delivery.aktywne_produkty(order) if p.current_status == 'dostarczone']
        for p in cofniete:
            p.current_status = 'zaladowane'
        if cofniete:
            bl_sync.oznacz_wyslane(order)
            bl_sync.zaplanuj_po_commicie(order.id)
        delivery.zapisz_log(order, 'dostarczenie_cofniete', 'dostarczone', 'zaladowane', route_id=trasa.id,
                            user_id=user_id, worker_id=worker_id, device_id=device_id, teraz=teraz)
        delivery.podbij_pozycje(order, teraz)
        delivery.przelicz_zamkniecie(order, teraz)
    stop.delivered_at = None
    stop.delivered_by_worker_id = None
    if trasa.status == 'wykonana':
        trasa.status, trasa.completed_at, trasa.completed_by = 'w_trasie', None, None
        _log_trasy(trasa, 'wykonana', 'w_trasie', teraz, user_id=user_id, worker_id=worker_id, device_id=device_id)
    return trasa, True


def _odmowa_niespakowanych(zamowienia, niespakowane):
    numery = u', '.join(zamowienia[i].internal_order_number or u'#{}'.format(i) for i in niespakowane)
    if len(niespakowane) == 1:
        tekst = (u'Zamówienie {} nie jest jeszcze w całości spakowane — spakuj je na tablecie '
                 u'albo odznacz, a wróci do puli bez trasy.')
    else:
        tekst = (u'Zamówienia {} nie są jeszcze w całości spakowane — spakuj je na tablecie '
                 u'albo odznacz, a wrócą do puli bez trasy.')
    return LogistykaBlad(tekst.format(numery), status=409, dane={'niespakowane': niespakowane})


def odhacz(route, dostarczone_ids, user_id=None, teraz=None):
    """
    „Odhacz jako wykonaną” z panelu tras (spec 9.7; dostępne też z roboczej — ruling R12 etapu 3). Zastępuje
    routes.wykonaj z etapu 3. `dostarczone_ids` (WYMAGANE, także pusta lista — M6) to zamówienia dostarczone;
    przystanki dostarczone już z telefonu zostają dostarczone. Zaznaczone → jak „Dostarczone” (pozycje
    'dostarczone', Base. 149778); odznaczone → jak „Niedostarczone” z powodem `odhaczone_w_panelu`. (I1) 409 z
    `niespakowane`, gdy jako dostarczone zaznaczono zamówienie, którego aktywne pozycje nie są wszystkie spakowane
    (lub dalej); zamówienia bez aktywnych pozycji ta reguła pomija. Trasa → 'wykonana', completed_by = użytkownik
    (telefon nie cofa wtedy ostatniego dostarczenia). Zwraca {'dostarczone', 'niedostarczone'} w kolejności
    przystanków.
    """
    trasa, zamowienia, pakunki = zablokuj(route)
    _wymagaj_statusu(trasa, *routes.AKTYWNE)
    na_trasie = [s.order_id for s in trasa.stops]
    if not na_trasie:
        raise LogistykaBlad(u'Trasa nie ma przystanków.', status=422)
    if dostarczone_ids is None:
        raise LogistykaBlad(u'Podaj listę dostarczonych zamówień (delivered_order_ids), '
                            u'także pustą.', status=422)
    zaznaczone = set(routes._lista_id(dostarczone_ids))
    if not zaznaczone <= set(na_trasie):
        raise LogistykaBlad(u'Część zamówień nie należy do tej trasy.', status=422)
    juz = {s.order_id for s in trasa.stops if s.delivered_at is not None}
    dostarczone = zaznaczone | juz
    nowe = [i for i in na_trasie if i in dostarczone and i not in juz]
    niespakowane = [i for i in nowe if i in zamowienia and delivery.aktywne_produkty(zamowienia[i])
                    and not delivery.wszystkie_spakowane(zamowienia[i])]
    if niespakowane:
        raise _odmowa_niespakowanych(zamowienia, niespakowane)
    teraz = teraz or get_local_now()
    niedostarczone = [i for i in na_trasie if i not in dostarczone]
    for order_id in niedostarczone:
        _wycofaj_z_trasy(trasa, zamowienia[order_id], pakunki.get(order_id, []), POWOD_ODHACZENIA, None, teraz,
                         user_id=user_id)
    trasa = routes.zablokuj_trasy(trasa)   # świeże przystanki po zdjęciach
    stary = trasa.status
    for stop in trasa.stops:
        if stop.order_id not in nowe:
            continue
        order = zamowienia.get(stop.order_id)
        if order is not None and delivery.aktywne_produkty(order):
            _oznacz_dostarczone(order, stop, teraz, user_id=user_id)
        else:
            stop.delivered_at = teraz   # anulowane w całości — bez statusu Base.
    trasa.status, trasa.completed_at, trasa.completed_by = 'wykonana', teraz, user_id
    _log_trasy(trasa, stary, 'wykonana', teraz, user_id=user_id)
    return {'dostarczone': [i for i in na_trasie if i in dostarczone], 'niedostarczone': niedostarczone}
```

- [ ] **Step 5: `routes.py` bez odhaczenia i przywracania**

W `modules/production/logistics/services/routes.py`:
- usuń funkcje `_odmowa_niespakowanych`, `wykonaj` i `przywroc` (przeniesione do `dostawa.py` jako `_odmowa_niespakowanych` i `odhacz`; „Przywróć trasę” zastępuje `dostawa.cofnij_dostarczenie`);
- w docstringu `zablokuj_trasy` zdanie „(Flask-Login ładuje usera; `edytuj`/`przywroc` dostają już wczytaną trasę)” → „(Flask-Login ładuje usera; `edytuj` i przejścia Dostawy dostają już wczytaną trasę)”, a przykład „(np. `wykonaj` → `usun_przystanek`)” → „(np. `dostawa.odhacz` → `usun_przystanek`)”;
- w `usun_przystanek` zastąp blok komentarza nad przeliczeniem i samo przeliczenie:
```python
    # (Task 1, runda 4.1, rozstrzygnięcie 40) Jedyne miejsce, w którym przystanek schodzi z trasy (odhaczenie,
    # niedostarczenie, „Zostaje”, ręczne DELETE, usun trasy, delivery._zdejmij_z_trasy) — spec 6.2 wymaga
    # przeliczenia zamknięcia po każdej zmianie, która może go dotyczyć (np. zamówienie anulowane w całości, którego
    # anulowanie ominęło przeliczenie, zamyka się od razu zamiast czekać na cron). Od kroku 4.4 reguła nie czyta tras.
    delivery.przelicz_zamkniecie(order, teraz)
```

- [ ] **Step 6: API panelu tras**

`modules/production/logistics/routers/trasy_api.py` — import:
```python
from modules.production.logistics.services import (bl_sync, dostawa, fleet, geocoding, lista, paczki, routes,
                                                   routimo, routing)
```
`_akcja` — po udanym commicie (przed budową odpowiedzi):
```python
    try:
        wynik = funkcja(trasa)
        db.session.commit()
    except LogistykaBlad as e:
        return _odmowa(e)
    except IntegrityError:
        return _konflikt(KOMUNIKAT_KONFLIKT_PRZYSTANKU)
    # Krok 4.4: przejścia Dostawy z panelu (odhaczenie, cofnięcia) zostawiają znaczniki statusów Base. —
    # dopychacz rusza dopiero po udanym commicie (bl_sync.zaplanuj_po_commicie w serwisie).
    bl_sync.wyslij_zaplanowane()
```
`/complete` i zamiast `/restore`:
```python
@logistics_panel_bp.route('/routes/<int:route_id>/complete', methods=['POST'])
@guard
def route_complete(route_id):
    # (M6) `delivered_order_ids` wymagane (lista, także pusta) — brak albo null to 422
    # z dostawa.odhacz, nie „wszystko dostarczone”. (I1) 409 z `niespakowane` przechodzi
    # przez _akcja → _odmowa razem z pozostałymi polami odmowy. Krok 4.4: odhaczenie wysyła statusy Base.
    return _akcja(route_id, lambda t: dostawa.odhacz(
        t, _cialo().get('delivered_order_ids'), user_id=_user_id()), przelicz_wykonana=True)


@logistics_panel_bp.route('/routes/<int:route_id>/stops/<int:order_id>/undo-delivered', methods=['POST'])
@guard
def route_stop_undo_delivered(route_id, order_id):
    """„Cofnij dostarczenie” przy przystanku (krok 4.4, spec 4.5 i 9.7) — zastępuje „Przywróć trasę”."""
    return _akcja(route_id, lambda t: dostawa.cofnij_dostarczenie(t, order_id, user_id=_user_id()) and None)
```

- [ ] **Step 7: Testy etapu 3 na nowe wejścia**

Mechanicznie (Git Bash, katalog worktree):
```bash
sed -i 's/routes\.wykonaj(/dostawa.odhacz(/g' tests/test_logistyka_trasy_serwis.py tests/test_logistyka_trasy_api.py \
  tests/test_logistyka_kierowcy.py tests/test_logistyka_routimo.py tests/test_logistyka_trasy_integracja.py
```
i import `dostawa` w tych plikach:
- `tests/test_logistyka_trasy_serwis.py:11` → `from modules.production.logistics.services import dostawa, routes`
- `tests/test_logistyka_trasy_api.py:10` → `from modules.production.logistics.services import dostawa, routes`
- `tests/test_logistyka_kierowcy.py:9` → `from modules.production.logistics.services import dostawa, fleet, routes`
- `tests/test_logistyka_routimo.py:47` → `from modules.production.logistics.services import dostawa, geocoding, routes, routimo`
- `tests/test_logistyka_trasy_integracja.py:9` → `from modules.production.logistics.services import delivery, dostawa, routes`

Ręcznie — `tests/test_logistyka_trasy_serwis.py`:
- `test_przywrocenie_otwiera_zamowienia` → zastąp całym:
```python
def test_cofniecie_dostarczenia_otwiera_zamowienie(app):
    with app.app_context():
        t = _trasa()
        a = _transport(statusy=('spakowane',))
        routes.dodaj_przystanki(t, [a.id])
        dostawa.odhacz(t, [a.id])
        db.session.commit()
        assert a.logistics_closed_at is not None
        dostawa.cofnij_dostarczenie(t, a.id)
        db.session.commit()
        assert t.status == 'w_trasie' and a.logistics_closed_at is None
```
- `test_kazda_zmiana_trasy_podbija_pozycje` — dwa wpisy listy i identyfikatory:
```python
    ('zatwierdzona', lambda t: dostawa.odhacz(t, [s.order_id for s in t.stops])),
    ('wykonana', lambda t: dostawa.cofnij_dostarczenie(t, t.stops[0].order_id)),
    ('robocza', lambda t: routes.usun(t)),
], ids=['edytuj', 'zatwierdz', 'cofnij_do_roboczej', 'odhacz', 'cofnij_dostarczenie', 'usun'])
```
- `test_zablokuj_trasy_na_starcie_kazdej_funkcji_zmieniajacej` — koniec testu od `routes.zatwierdz(t)` / `przed = len(wywolania)`:
```python
        routes.zatwierdz(t)
        przed = len(wywolania)
        dostawa.odhacz(t, [o1.id])
        assert t.id in wywolania[przed:]

        dostawa.cofnij_dostarczenie(t, o1.id)
        assert wywolania[-1] == t.id

        # (krok 4.4) Z trasy w drodze nie ma powrotu do roboczej — usunięcie sprawdzamy na drugiej trasie.
        druga = routes.utworz({'name': 'C', 'date_from': '2026-10-02'})
        routes.dodaj_przystanki(druga, [o2.id])
        routes.usun(druga)
        assert druga.id in wywolania[-2:]   # własne wywołanie + re-entrantne z usun_przystanek
```
- `test_odhaczenie_zamyka_wedlug_swiezej_trasy` — docstring: „(krok 4.4) Reguła transportu nie czyta tras: odhaczenie i cofnięcie dostarczenia decydują o zamknięciu bez routes.przystanek_zamowienia (zwykłego odczytu z migawki transakcji).”; `routes.przywroc(t)` → `dostawa.cofnij_dostarczenie(t, a.id)`.
- usuń `_wykonana_z`, `test_przywrocenie_z_wylaczonym_pojazdem_i_kierowca` i `test_przywrocenie_nadal_sprawdza_zajetosc` (cofnięcie dostarczenia celowo nie sprawdza zasobów — `test_panel_cofa_dowolne_dostarczenie_bez_sprawdzania_zajetosci`).

`tests/test_logistyka_trasy_api.py`:
- `test_pelny_cykl_trasy`, ostatnia linia:
```python
    r = client.post(BASE + '/routes/%d/stops/%d/undo-delivered' % (rid, b))
    assert r.status_code == 200 and r.get_json()['route']['status'] == 'w_trasie'
```
- `test_404_akcje_na_nieznanej_trasie`, ostatnia linia:
```python
    assert client.post(BASE + '/routes/%d/stops/1/undo-delivered' % nid).status_code == 404
```

`tests/test_logistyka_kierowcy.py`, `test_kierowca_bez_znacznika_zostaje_na_swojej_trasie`: w docstringu „edycja i przywrócenie przechodzą” → „edycja i cofnięcie dostarczenia przechodzą”; `routes.przywroc(w)` → `dostawa.cofnij_dostarczenie(w, a.id)`; `assert w.status == 'zatwierdzona'` → `assert w.status == 'w_trasie'`.

`tests/test_logistyka_cron.py`:
- `test_cron_otwiera_zamkniete_na_aktywnej_trasie`: `dostarczone = zamowienie(sposob=s.TRANSPORT, statusy=('dostarczone',), …)`; w docstringu „To samo zamówienie na trasie WYKONANEJ zostaje zamknięte.” → „Zamówienie dostarczone (pozycje „dostarczone”, krok 4.4) na trasie WYKONANEJ zostaje zamknięte.”
- `test_siatka_zostawia_zamkniecia_zgodne_z_regula`: `dowieziony = zamowienie(sposob=s.TRANSPORT, statusy=('dostarczone',), logistics_closed_at=PO_ZNACZNIKU)`; w docstringu „transport na trasie wykonanej” → „transport dostarczony (pozycje „dostarczone”, krok 4.4)”.

`tests/test_weryfikacja_cykl.py`, `test_zamkniecie_po_nowych_statusach` — komentarz przy wariancie transportu:
```python
    (s.TRANSPORT, ('zweryfikowane',), {}, False),          # transport zamyka „dostarczone” (krok 4.4, spec 4.6)
```

Jeśli pełny pakiet (Step 9) pokaże inne testy oparte na „trasa wykonana zamyka transport” albo na `routes.wykonaj`/`przywroc`/`/restore`, popraw je tak samo (pozycje `dostarczone`, `dostawa.odhacz`, `dostawa.cofnij_dostarczenie`) i wymień w raporcie.

- [ ] **Step 8: Testy przechodzą**

Run: `PYTEST tests/test_dostawa_dostarczenia.py tests/test_dostawa_zaladunek.py tests/test_logistyka_trasy_serwis.py tests/test_logistyka_trasy_api.py tests/test_logistyka_kierowcy.py tests/test_logistyka_routimo.py tests/test_logistyka_trasy_integracja.py tests/test_logistyka_cron.py tests/test_weryfikacja_cykl.py tests/test_logistyka_delivery.py`
Expected: PASS.

- [ ] **Step 9: Pełny pakiet**

Run: `PYTEST tests/`
Expected: `wynik Task 3 + 21 passed, 3 skipped` (+23 nowych: 22 w `test_dostawa_dostarczenia.py`, 1 w `test_logistyka_cron.py`; −2 usunięte testy przywracania).

- [ ] **Step 10: Commit**

```bash
git add modules/production/logistics/services/dostawa.py modules/production/logistics/services/delivery.py \
  modules/production/logistics/services/routes.py modules/production/logistics/routers/trasy_api.py \
  tests/test_dostawa_dostarczenia.py tests/test_logistyka_trasy_serwis.py tests/test_logistyka_trasy_api.py \
  tests/test_logistyka_kierowcy.py tests/test_logistyka_routimo.py tests/test_logistyka_trasy_integracja.py \
  tests/test_logistyka_cron.py tests/test_weryfikacja_cykl.py
git commit -m "feat(production): dostarczenia, odhaczenie ze statusami Base. i cofniecie dostarczenia" \
  -m "Krok 4.4 logistyki: Dostarczone i Niedostarczone z automatycznym zamknieciem trasy, Cofnij dostarczenie (telefon: ostatnie, takze po zamknieciu trasy; panel: dowolne) zamiast Przywroc trase, odhaczenie z panelu jak Dostarczone/Niedostarczone ze statusami Base., transport zamyka sie po dostarczone (regula nie czyta tras)." \
  -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: API panelu tras — „Cofnij załadunek”, postęp i Dostawa przy przystankach

**Files:**
- Modify: `modules/production/logistics/services/routes.py` (`serializuj_trase` :768-785; nowa `postep`)
- Modify: `modules/production/logistics/routers/trasy_api.py` (`_szczegoly` :192-218, `routes_list` :376-404, nowy endpoint `/routes/<rid>/unload`)
- Test: `tests/test_dostawa_panel_tras.py`

**Interfaces:**
- Consumes: Task 3 (`dostawa.cofnij_zaladunek`, `dostawa.POWODY_ZOSTAJE`), Task 4 (`_akcja` z `bl_sync.wyslij_zaplanowane()`), Task 2 (`lista.serializuj(...)['paczki']['zaladowane']`).
- Produces: `routes.postep(route, zamowienia, pakunki) -> {'przystanki', 'zaladowane', 'dostarczone'}`; `routes.serializuj_trase(route, zamowienia=None, punkty=None, pakunki=None)` z polami `zaladowana`, `wyjazd`, `odhaczona_w_panelu` i (z `pakunki`) `postep`; w `GET /routes/<rid>` i odpowiedziach akcji każdy przystanek ma `zamowienie.dostawa = {'dostarczono': iso|None, 'zostaje': None|{'powod', 'etykieta', 'notatka'}}`; `GET /routes` — `postep` przy każdej trasie; `POST /routes/<rid>/unload` (panel, „Cofnij załadunek”). Front (Task 7) czyta dokładnie te nazwy.

- [ ] **Step 1: Testy, które padną**

Create `tests/test_dostawa_panel_tras.py`:

```python
# -*- coding: utf-8 -*-
"""Panel tras po kroku 4.4 (spec 9.7): „Cofnij załadunek”, postęp „załadowano x/y · dostarczono a/b”, kiedy
załadowano i ruszono, trasa odhaczona w panelu, dostarczenie i „Zostaje” przy przystanku."""
from extensions import db
from modules.production.logistics.services import bl_sync, dostawa, routes
from tests.dostawa_pomocnicze import T0, trasa, zaladuj_wprost, zamowienie_z_paczkami
from tests.logistyka_fixtures import BASE, app, client  # noqa: F401


def _przystanki(dane):
    return {p['zamowienie']['id']: p['zamowienie'] for p in dane['przystanki']}


def test_cofnij_zaladunek_przez_api(app, client, monkeypatch):
    wywolania = []
    monkeypatch.setattr(bl_sync, 'po_zmianie', lambda ids: wywolania.append(sorted(ids)))
    order, lista_paczek = zamowienie_z_paczkami(statusy=('zaladowane', 'zaladowane'))
    t = trasa([order], status='zaladowana', loaded_at=T0)
    zaladuj_wprost(lista_paczek, t)
    rid, oid = t.id, order.id
    r = client.post(BASE + '/routes/%d/unload' % rid)
    assert r.status_code == 200, r.get_data()[:300]
    assert r.get_json()['route']['status'] == 'zatwierdzona'
    assert wywolania == [[oid]]
    r = client.post(BASE + '/routes/%d/unload' % rid)
    assert r.status_code == 409 and u'zatwierdzona' in r.get_json()['error']
    assert client.post(BASE + '/routes/999999/unload').status_code == 404


def test_szczegoly_trasy_w_zaladunku(app, client):
    pelne, paczki_pelne = zamowienie_z_paczkami()
    czesc, (c1, _c2) = zamowienie_z_paczkami()
    zostaje, _ = zamowienie_z_paczkami()
    anulowane, _ = zamowienie_z_paczkami(statusy=('anulowane',))
    t = trasa([pelne, czesc, zostaje, anulowane])
    zaladuj_wprost(paczki_pelne + [c1], t)
    dostawa.ustaw_zostaje(t, zostaje.id, 'brak_miejsca', u'za długie')
    db.session.commit()
    r = client.get(BASE + '/routes/%d' % t.id)
    assert r.status_code == 200, r.get_data()[:300]
    dane = r.get_json()['route']
    assert dane['postep'] == {'przystanki': 3, 'zaladowane': 1, 'dostarczone': 0}   # anulowane się nie liczy
    assert (dane['zaladowana'], dane['wyjazd'], dane['odhaczona_w_panelu']) == (None, None, False)
    przystanki = _przystanki(dane)
    assert przystanki[zostaje.id]['dostawa'] == {
        'dostarczono': None,
        'zostaje': {'powod': 'brak_miejsca', 'etykieta': u'Brak miejsca', 'notatka': u'za długie'}}
    assert przystanki[pelne.id]['dostawa'] == {'dostarczono': None, 'zostaje': None}
    assert przystanki[czesc.id]['paczki']['zaladowane'] == 1


def test_szczegoly_trasy_w_drodze(app, client):
    a, paczki_a = zamowienie_z_paczkami(statusy=('zaladowane', 'zaladowane'))
    b, paczki_b = zamowienie_z_paczkami(statusy=('zaladowane', 'zaladowane'))
    t = trasa([a, b], status='w_trasie', loaded_at=T0, departed_at=T0)
    zaladuj_wprost(paczki_a + paczki_b, t)
    dostawa.dostarcz(t, a.id, worker_id=7, teraz=T0)
    db.session.commit()
    dane = client.get(BASE + '/routes/%d' % t.id).get_json()['route']
    assert dane['postep'] == {'przystanki': 2, 'zaladowane': 2, 'dostarczone': 1}
    assert (dane['zaladowana'], dane['wyjazd']) == (T0.isoformat(), T0.isoformat())
    przystanki = _przystanki(dane)
    assert przystanki[a.id]['dostawa']['dostarczono'] == T0.isoformat()
    assert przystanki[b.id]['dostawa']['dostarczono'] is None


def test_lista_tras_ma_postep(app, client):
    order, lista_paczek = zamowienie_z_paczkami()
    t = trasa([order])
    zaladuj_wprost(lista_paczek, t)
    trasy = client.get(BASE + '/routes').get_json()['routes']
    wpis = next(x for x in trasy if x['id'] == t.id)
    assert wpis['postep'] == {'przystanki': 1, 'zaladowane': 1, 'dostarczone': 0}


def test_trasa_odhaczona_w_panelu(app):
    order, _ = zamowienie_z_paczkami(statusy=('zaladowane',))
    t = trasa([order], status='w_trasie')
    dostawa.odhacz(t, [order.id], user_id=1, teraz=T0)
    db.session.commit()
    assert routes.serializuj_trase(t)['odhaczona_w_panelu'] is True
    t.completed_by = None                      # zamknął telefon (ostatnie „Dostarczone”)
    assert routes.serializuj_trase(t)['odhaczona_w_panelu'] is False
```

- [ ] **Step 2: Testy padają**

Run: `PYTEST tests/test_dostawa_panel_tras.py`
Expected: FAIL — 404 na `/unload`, `KeyError: 'postep'` / `'dostawa'` / `'zaladowana'`, `KeyError: 'odhaczona_w_panelu'`.

- [ ] **Step 3: Postęp i nowe pola trasy**

`modules/production/logistics/services/routes.py` — nad `serializuj_trase`:
```python
def postep(route, zamowienia, pakunki):
    """
    Postęp Dostawy w nagłówku edytora i na liście tras (krok 4.4, spec 9.7: „załadowano 7/8 · dostarczono 3/7”),
    liczony na przystankach aktywnych (zamówienia z choć jedną nieanulowaną pozycją). `zaladowane` — przystanek
    z co najmniej jedną aktualną paczką i wszystkimi załadowanymi na tę trasę (po dostarczeniu znaczniki zostają);
    `dostarczone` — przystanek z `delivered_at`. `pakunki` — {order_id: [aktualne paczki]}.
    """
    aktywne = {o.id for o in zamowienia if delivery.aktywne_produkty(o)}
    stopy = [s for s in route.stops if s.order_id in aktywne]

    def zaladowany(order_id):
        lista_paczek = pakunki.get(order_id, [])
        return bool(lista_paczek) and all(p.loaded_at is not None and p.loaded_route_id == route.id
                                          for p in lista_paczek)

    return {'przystanki': len(stopy),
            'zaladowane': sum(1 for s in stopy if zaladowany(s.order_id)),
            'dostarczone': sum(1 for s in stopy if s.delivered_at is not None)}
```
`serializuj_trase`:
```python
def serializuj_trase(route, zamowienia=None, punkty=None, pakunki=None):
    kierowca = route.driver
    dane = {
        ...  # dotychczasowe pola bez zmian, do 'wykonana' włącznie
        'wykonana': route.completed_at.isoformat() if route.completed_at else None,
        # Krok 4.4: Dostawa — koniec załadunku, wyjazd i czy trasę zamknął logistyk (telefon nie cofa wtedy
        # ostatniego dostarczenia; trasa zamknięta telefonem ma completed_by NULL).
        'zaladowana': route.loaded_at.isoformat() if route.loaded_at else None,
        'wyjazd': route.departed_at.isoformat() if route.departed_at else None,
        'odhaczona_w_panelu': route.status == 'wykonana' and route.completed_by is not None,
    }
    if zamowienia is not None:
        dane['podsumowanie'] = podsumowanie(route, zamowienia, punkty or {})
        if pakunki is not None:
            dane['postep'] = postep(route, zamowienia, pakunki)
    return dane
```

- [ ] **Step 4: Szczegóły, lista i „Cofnij załadunek” w API**

`modules/production/logistics/routers/trasy_api.py`, `_szczegoly` — końcówka (od `dane = routes.serializuj_trase(...)`):
```python
    pakunki = paczki.aktualne_paczki_zamowien([o.id for o in zamowienia])
    dane = routes.serializuj_trase(route, zamowienia, punkty, pakunki)
    przystanki = {s.order_id: s for s in route.stops}
    dane['przystanki'] = []
    for o, numer, anulowane in routes.numeracja_przystankow(zamowienia):
        zamowienie = lista.serializuj(o, punkty.get(o.id), route, pakunki.get(o.id, []))
        zamowienie['dostawa'] = _dostawa_przystanku(przystanki.get(o.id))
        dane['przystanki'].append({'pozycja': numer, 'anulowane': anulowane, 'zamowienie': zamowienie})
    dane['przebieg'] = routing.przebieg(route)
    return dane
```
i nad `_szczegoly`:
```python
def _dostawa_przystanku(stop):
    """
    Krok 4.4: dostarczenie i „Zostaje” przystanku dla edytora trasy i okna „Odhacz”. W słowniku zamówienia
    (`zamowienie.dostawa`), bo front buduje listę przystanków z samych zamówień (przystankiWidoczne).
    """
    if stop is None:
        return {'dostarczono': None, 'zostaje': None}
    zostaje = None
    if stop.stays_reason:
        zostaje = {'powod': stop.stays_reason,
                   'etykieta': dostawa.POWODY_ZOSTAJE.get(stop.stays_reason, stop.stays_reason),
                   'notatka': stop.stays_note}
    return {'dostarczono': stop.delivered_at.isoformat() if stop.delivered_at else None, 'zostaje': zostaje}
```
`routes_list` — przed budową wyniku:
```python
    trasy, zamowienia_wg_trasy, punkty = _wczytaj_trasy(zapytanie)
    trasy = sorted(trasy, key=lambda r: (KOLEJNOSC_STATUSOW[r.status], r.date_from, r.id))
    # Krok 4.4: postęp Dostawy przy każdej trasie — paczki wszystkich tras jednym zapytaniem.
    pakunki = paczki.aktualne_paczki_zamowien(
        [o.id for zamowienia in zamowienia_wg_trasy.values() for o in zamowienia])
    wynik = [routes.serializuj_trase(trasa, zamowienia_wg_trasy[trasa.id], punkty, pakunki) for trasa in trasy]
```
Endpoint (pod `route_revert`):
```python
@logistics_panel_bp.route('/routes/<int:route_id>/unload', methods=['POST'])
@guard
def route_unload(route_id):
    """„Cofnij załadunek” (krok 4.4, spec 4.5 i 9.7): trasa załadowana wraca do zatwierdzonej."""
    return _akcja(route_id, lambda t: dostawa.cofnij_zaladunek(t, user_id=_user_id()) and None)
```
W docstringu modułu dopisz zdanie: „Dostawa (krok 4.4): `POST /routes/<id>/unload` („Cofnij załadunek”), `POST /routes/<id>/stops/<oid>/undo-delivered` („Cofnij dostarczenie”), odhaczenie `/complete` przez services/dostawa.py.”

- [ ] **Step 5: Testy przechodzą**

Run: `PYTEST tests/test_dostawa_panel_tras.py tests/test_logistyka_trasy_api.py tests/test_logistyka_trasy_serwis.py tests/test_dostawa_dostarczenia.py tests/test_paczki_panel.py`
Expected: PASS.

- [ ] **Step 6: Pełny pakiet**

Run: `PYTEST tests/`
Expected: `wynik Task 4 + 5 passed, 3 skipped`.

- [ ] **Step 7: Commit**

```bash
git add modules/production/logistics/services/routes.py modules/production/logistics/routers/trasy_api.py \
  tests/test_dostawa_panel_tras.py
git commit -m "feat(production): panel tras - Cofnij zaladunek, postep Dostawy i stan przystankow" \
  -m "Krok 4.4 logistyki: POST /routes/<id>/unload, postep (zaladowane i dostarczone przystanki) na liscie i w szczegolach trasy, kiedy zaladowano i ruszono, trasa odhaczona w panelu, dostarczenie i Zostaje przy przystanku." \
  -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: API telefonu kierowcy — `/api/mobile/delivery`

**Tor równoległy** do Task 5 (pliki rozłączne): worktree `.claude/worktrees/logistyka-etap-4-b6`, gałąź `claude/logistyka-etap-4-b6` z commita Task 4, projekt dockera `logistyka4-b6`. Po scaleniu (cherry-pick do głównego worktree po Task 5) — pełny pakiet w głównym worktree.

**Files:**
- Create: `modules/production/logistics/services/dostawa_widok.py`
- Create: `modules/production/logistics/routers/dostawa_api.py`
- Modify: `app.py:881-882` (rejestracja blueprintu obok Weryfikacji)
- Modify: `tests/logistyka_fixtures.py:84-85` (rejestracja w apce testowej)
- Test: `tests/test_dostawa_api.py`

**Interfaces:**
- Consumes: Task 3–4 (`dostawa.zablokuj`, `zaladuj_paczke`, `rozladuj_paczke`, `ustaw_zostaje`, `zdejmij_zostaje`, `zakoncz_zaladunek`, `ruszaj`, `dostarcz`, `nie_dostarcz`, `cofnij_dostarczenie(..., z_telefonu=True)`, `waliduj_metode`, `waliduj_powod`, `POWODY_ZOSTAJE`, `POWODY_NIEDOSTARCZENIA`, `NAZWY_STATUSOW_TRASY`, `STANOWISKO`, `DostawaBlad`); `routes.dzis()`, `routes.numeracja_przystankow(zamowienia)`, `routes.WAGA_KG_NA_M3`; `paczki.aktualne_paczki_zamowien(ids)`; `geocoding.geo_zamowien(ids)`; `weryfikacja.POWODY_PROBLEMU`; z API mobilnego: `require_device_token`, `with_idempotency`, `BLEDY_DO_PONOWIENIA`, `worker_service.resolve_worker_ids/touch_sessions`, `WorkerError`, `resolve_station_code`, cache (`make_weak_etag`, `if_none_match`, `not_modified`, `cached_json`, `no_store_json`).
- Produces: blueprint `dostawa_mobile_bp` pod `/api/mobile/delivery` — kontrakt z sekcji „Kontrakt API Dostawy” tego planu; `dostawa_widok.lista_moich_tras(kierowca_id, dzis)`, `wczytaj(route_id)`, `serializuj(trasa, zamowienia, pakunki, punkty)`, `trasa_po_zapisie(trasa)`, `serializuj_paczke(p, trasa)`, `podpis(dane)`; `dostawa_api.KSZTALT_TRASY = 1`.

- [ ] **Step 1: Testy, które padną**

Create `tests/test_dostawa_api.py`:

```python
# -*- coding: utf-8 -*-
"""API telefonu kierowcy (logistyka etap 4, krok 4.4, spec 9): bramka stanowiska i kierowcy, „Moje trasy”, trasa
z ETagiem, załadunek, „Zostaje”, zakończenie załadunku, wyjazd, dostarczenia i cofnięcie — kontrakt z planu 4.4b."""
from datetime import timedelta

from extensions import db
from modules.production.logistics.models import OrderGeo, RouteStop
from modules.production.logistics.services import bl_sync, dostawa
from modules.production.models import ProductionDevice
from tests.dostawa_pomocnicze import (T0, naglowki, telefon_kierowcy, trasa, zaladuj_wprost,
                                      zamowienie_z_paczkami)
from tests.logistyka_fixtures import DZIS_TESTOW, app, client, kierowca, pracownik  # noqa: F401

API = '/api/mobile/delivery'


def _trasa_kierowcy(k, zamowienia, **kolumny):
    kolumny.setdefault('od', DZIS_TESTOW)
    return trasa(zamowienia, kierowca_id=k.id, **kolumny)


# --- Bramka -------------------------------------------------------------------------------------------

def test_api_wymaga_stanowiska_dostawy(app, client):
    _device, k = telefon_kierowcy()
    obcy = ProductionDevice(device_id='TEL-WERYF', device_name='Telefon biura', station_code='verification')
    db.session.add(obcy)
    db.session.commit()
    r = client.get(API + '/routes', headers=naglowki(obcy, k))
    assert r.status_code == 403 and r.get_json()['error'] == 'station_not_allowed'


def test_api_wymaga_kierowcy(app, client):
    device, _k = telefon_kierowcy()
    r = client.get(API + '/routes', headers=naglowki(device))
    assert r.status_code == 400 and r.get_json()['error'] == 'worker_required'
    r = client.get(API + '/routes', headers=naglowki(device, pracownik()))
    assert r.status_code == 403 and r.get_json()['error'] == 'not_a_driver'
    obcy = dict(naglowki(device), **{'X-Worker-Ids': '987654'})
    r = client.get(API + '/routes', headers=obcy)
    assert r.status_code == 404 and r.get_json()['error'] == 'worker_not_found'


# --- Odczyty -------------------------------------------------------------------------------------------

def test_moje_trasy_zakres(app, client):
    """Review Focus 3: zatwierdzone od dziś, a załadowane i w drodze bez względu na datę — rozpoczęta trasa nie
    znika z telefonu o północy. Robocze, wykonane i cudze — nie."""
    device, k = telefon_kierowcy()
    wczoraj = DZIS_TESTOW - timedelta(days=1)
    dzisiejsza = _trasa_kierowcy(k, [zamowienie_z_paczkami()[0]], nazwa=u'Dziś')
    jutrzejsza = _trasa_kierowcy(k, [zamowienie_z_paczkami()[0]], nazwa=u'Jutro', od=DZIS_TESTOW + timedelta(days=1))
    _trasa_kierowcy(k, [zamowienie_z_paczkami()[0]], nazwa=u'Wczorajsza', od=wczoraj)
    zaladowana = _trasa_kierowcy(k, [zamowienie_z_paczkami(statusy=('zaladowane',))[0]], nazwa=u'Stoi',
                                 status='zaladowana', od=wczoraj)
    w_trasie = _trasa_kierowcy(k, [zamowienie_z_paczkami(statusy=('zaladowane',))[0]], nazwa=u'Jedzie',
                               status='w_trasie', od=wczoraj - timedelta(days=1))
    _trasa_kierowcy(k, [zamowienie_z_paczkami()[0]], nazwa=u'Robocza', status='robocza')
    _trasa_kierowcy(k, [zamowienie_z_paczkami(statusy=('dostarczone',))[0]], nazwa=u'Wykonana', status='wykonana')
    trasa([zamowienie_z_paczkami()[0]], kierowca_id=kierowca().id, nazwa=u'Cudza', od=DZIS_TESTOW)
    r = client.get(API + '/routes', headers=naglowki(device, k))
    assert r.status_code == 200, r.get_data()[:300]
    assert r.headers['Cache-Control'] == 'no-store'
    dane = r.get_json()
    assert [t['id'] for t in dane['routes']] == [w_trasie.id, zaladowana.id, dzisiejsza.id, jutrzejsza.id]
    assert dane['count'] == 4
    pierwsza = dane['routes'][0]
    assert (pierwsza['status'], pierwsza['status_label']) == ('w_trasie', u'W trasie')
    assert set(pierwsza) == {'id', 'name', 'date_from', 'date_to', 'status', 'status_label', 'vehicle_name',
                             'stops_total', 'stops_delivered', 'packages_total', 'packages_loaded'}


def test_trasa_ksztalt_i_stany(app, client):
    device, k = telefon_kierowcy()
    gotowe, (g1, g2) = zamowienie_z_paczkami(delivery_fullname=u'Anna Nowak', client_phone='600100200',
                                             order_notes=u'Brama od podwórza')
    niezweryfikowane, _ = zamowienie_z_paczkami(statusy=('spakowane',), zweryfikowane=False,
                                                delivery_company=u'Stolarnia Sp. z o.o.')
    problem, _ = zamowienie_z_paczkami(problem_at=T0, problem_reason='uszkodzenie', problem_note=u'pęknięta')
    niespakowane, _ = zamowienie_z_paczkami(statusy=('zweryfikowane', 'czeka_na_lakiernie'))
    anulowane, _ = zamowienie_z_paczkami(statusy=('anulowane',))
    t = _trasa_kierowcy(k, [gotowe, niezweryfikowane, problem, niespakowane, anulowane], nazwa=u'Rzeszów 02.10')
    zaladuj_wprost([g1], t, kto_id=k.id)
    db.session.add(OrderGeo(order_id=gotowe.id, lat=50.04, lng=22.0, source='gugik', quality='dokladna',
                            address_hash='x' * 40))
    db.session.add(OrderGeo(order_id=niezweryfikowane.id, lat=50.0, lng=21.9, source='nominatim',
                            quality='przyblizona', address_hash='y' * 40))
    dostawa.ustaw_zostaje(t, niespakowane.id, 'niespakowane')
    db.session.commit()
    r = client.get(API + '/routes/%d' % t.id, headers=naglowki(device, k))
    assert r.status_code == 200, r.get_data()[:300]
    trasa_ = r.get_json()['route']
    assert (trasa_['name'], trasa_['status_label'], trasa_['stops_total'], trasa_['packages_loaded']) == \
        (u'Rzeszów 02.10', u'Zatwierdzona', 4, 1)
    assert trasa_['completed_by_panel'] is False
    stopy = {s['order_id']: s for s in trasa_['stops']}
    s = stopy[gotowe.id]
    assert (s['position'], s['recipient'], s['phone'], s['order_notes']) == \
        (1, u'Anna Nowak', '600100200', u'Brama od podwórza')
    assert s['geo'] == {'lat': 50.04, 'lng': 22.0}
    assert (s['state'], s['state_label'], s['packages_total'], s['packages_loaded']) == \
        ('zweryfikowane', u'Zweryfikowane', 2, 1)
    assert [p['code'] for p in s['packages']] == ['P-%d' % g1.id, 'P-%d' % g2.id]
    assert [p['loaded'] for p in s['packages']] == [True, False]
    assert set(s['address']) == {'street', 'postcode', 'city', 'country_code'}
    assert stopy[niezweryfikowane.id]['geo'] is None                      # tylko punkt dokładny
    assert stopy[niezweryfikowane.id]['recipient'] == u'Stolarnia Sp. z o.o.'
    assert (stopy[niezweryfikowane.id]['state'], stopy[niezweryfikowane.id]['state_label']) == \
        ('niezweryfikowane', u'NIEZWERYFIKOWANE')
    assert stopy[problem.id]['state'] == 'problem' and stopy[problem.id]['state_label'].startswith(u'PROBLEM: ')
    assert stopy[problem.id]['problem']['reason'] == 'uszkodzenie'
    assert (stopy[niespakowane.id]['state'], stopy[niespakowane.id]['state_label']) == \
        ('niespakowane', u'NIESPAKOWANE')
    assert stopy[niespakowane.id]['stays'] == {'reason': 'niespakowane', 'reason_label': u'Niespakowane',
                                               'note': None}
    assert (stopy[anulowane.id]['position'], stopy[anulowane.id]['state']) == (None, 'anulowane')


def test_trasa_etag_i_304(app, client):
    device, k = telefon_kierowcy()
    order, (p1, _p2) = zamowienie_z_paczkami()
    t = _trasa_kierowcy(k, [order])
    r = client.get(API + '/routes/%d' % t.id, headers=naglowki(device, k))
    etag = r.headers['ETag']
    assert etag.startswith('W/"dostawa:1:%d:' % t.id)
    assert r.headers['Cache-Control'] == 'private, max-age=0'
    r = client.get(API + '/routes/%d' % t.id, headers=dict(naglowki(device, k), **{'If-None-Match': etag}))
    assert r.status_code == 304
    assert client.post(API + '/routes/%d/packages/%d/load' % (t.id, p1.id), headers=naglowki(device, k),
                       json={'method': 'skan'}).status_code == 200
    r = client.get(API + '/routes/%d' % t.id, headers=dict(naglowki(device, k), **{'If-None-Match': etag}))
    assert r.status_code == 200 and r.headers['ETag'] != etag


def test_trasa_robocza_i_nieznana_404(app, client):
    device, k = telefon_kierowcy()
    robocza = _trasa_kierowcy(k, [zamowienie_z_paczkami()[0]], status='robocza')
    for rid in (robocza.id, 987654):
        r = client.get(API + '/routes/%d' % rid, headers=naglowki(device, k))
        assert r.status_code == 404 and r.get_json()['error'] == 'route_not_found'


# --- Zapisy ------------------------------------------------------------------------------------------------

def test_zaladunek_przez_api_i_idempotencja(app, client):
    device, k = telefon_kierowcy()
    order, (p1, _p2) = zamowienie_z_paczkami()
    t = _trasa_kierowcy(k, [order])
    adres = API + '/routes/%d/packages/%d/load' % (t.id, p1.id)
    h = naglowki(device, k, op_id='op-load-1')
    r = client.post(adres, headers=h, json={'method': 'skan'})
    assert r.status_code == 200, r.get_data()[:300]
    dane = r.get_json()
    assert (dane['changed'], dane['package']['code'], dane['package']['loaded']) == (True, 'P-%d' % p1.id, True)
    assert dane['route']['stops'][0]['packages_loaded'] == 1 and dane['message']
    assert client.post(adres, headers=h, json={'method': 'skan'}).get_json() == dane      # powtórka op_id
    r = client.post(adres, headers=naglowki(device, k), json={})                         # nowy op_id
    assert r.status_code == 200 and r.get_json()['changed'] is False


def test_odmowy_409_nie_sa_zapamietywane_a_422_tak(app, client):
    device, k = telefon_kierowcy()
    order, (p1,) = zamowienie_z_paczkami(statusy=('spakowane',), paczek=1, zweryfikowane=False)
    t = _trasa_kierowcy(k, [order])
    adres = API + '/routes/%d/packages/%d/load' % (t.id, p1.id)
    h = naglowki(device, k, op_id='op-load-409')
    r = client.post(adres, headers=h, json={})
    assert r.status_code == 409 and r.get_json()['error'] == 'order_not_verified'
    for p in order.products:
        p.current_status = 'zweryfikowane'
    db.session.commit()
    assert client.post(adres, headers=h, json={}).status_code == 200      # to samo X-Operation-Id przechodzi
    h422 = naglowki(device, k, op_id='op-load-422')
    assert client.post(adres, headers=h422, json={'method': 'palcem'}).status_code == 422
    r = client.post(adres, headers=h422, json={'method': 'skan'})
    assert r.status_code == 422 and r.get_json()['error'] == 'invalid_method'   # odtworzone z idempotencji


def test_paczka_z_innej_trasy_ma_nazwe_trasy(app, client):
    device, k = telefon_kierowcy()
    t = _trasa_kierowcy(k, [zamowienie_z_paczkami()[0]])
    inne, (q1, _q2) = zamowienie_z_paczkami()
    trasa([inne], nazwa=u'Lublin 03.10')
    r = client.post(API + '/routes/%d/packages/%d/load' % (t.id, q1.id), headers=naglowki(device, k), json={})
    dane = r.get_json()
    assert r.status_code == 409 and (dane['error'], dane['route_name']) == ('package_not_on_route', u'Lublin 03.10')


def test_zostaje_zakonczenie_i_wyjazd_przez_api(app, client, monkeypatch):
    wywolania = []
    monkeypatch.setattr(bl_sync, 'po_zmianie', lambda ids: wywolania.append(sorted(ids)))
    device, k = telefon_kierowcy()
    jedzie, (j1, j2) = zamowienie_z_paczkami()
    zostaje, _ = zamowienie_z_paczkami()
    t = _trasa_kierowcy(k, [jedzie, zostaje])
    rid = t.id
    r = client.post(API + '/routes/%d/packages/%d/load' % (rid, j1.id), headers=naglowki(device, k), json={})
    assert r.status_code == 200
    r = client.post(API + '/routes/%d/finish-loading' % rid, headers=naglowki(device, k))
    dane = r.get_json()
    assert r.status_code == 409 and dane['error'] == 'loading_incomplete'
    assert [b['reason'] for b in dane['braki']] == ['niezaladowane', 'niezaladowane']
    r = client.post(API + '/routes/%d/stops/%d/stays' % (rid, zostaje.id), headers=naglowki(device, k),
                    json={'reason': 'brak_miejsca', 'note': u'za długie'})
    assert r.status_code == 200 and r.get_json()['changed'] is True
    assert client.post(API + '/routes/%d/stops/%d/stays' % (rid, zostaje.id), headers=naglowki(device, k),
                       json={'reason': 'zle'}).status_code == 422
    client.post(API + '/routes/%d/packages/%d/load' % (rid, j2.id), headers=naglowki(device, k), json={})
    r = client.post(API + '/routes/%d/finish-loading' % rid, headers=naglowki(device, k))
    assert r.status_code == 200, r.get_data()[:300]
    dane = r.get_json()
    assert dane['route']['status'] == 'zaladowana' and [s['order_id'] for s in dane['route']['stops']] == [jedzie.id]
    assert dane['removed'] == [{'order_id': zostaje.id, 'internal_order_number': zostaje.internal_order_number,
                                'reason': 'brak_miejsca'}]
    r = client.post(API + '/routes/%d/depart' % rid, headers=naglowki(device, k))
    assert r.status_code == 200 and r.get_json()['route']['status'] == 'w_trasie'
    assert [jedzie.id] in wywolania                                   # dopychacz Base. po commicie


def test_api_cofniecie_po_automatycznym_zamknieciu(app, client):
    """Review Focus 1: ostatnie „Dostarczone” zamyka trasę, telefon od razu cofa pomyłkę."""
    device, k = telefon_kierowcy()
    order, lista_paczek = zamowienie_z_paczkami(statusy=('zaladowane', 'zaladowane'))
    t = _trasa_kierowcy(k, [order], status='w_trasie', loaded_at=T0, departed_at=T0)
    zaladuj_wprost(lista_paczek, t, kto_id=k.id)
    rid = t.id
    r = client.post(API + '/routes/%d/stops/%d/delivered' % (rid, order.id), headers=naglowki(device, k))
    assert r.status_code == 200, r.get_data()[:300]
    dane = r.get_json()
    assert (dane['changed'], dane['route_completed'], dane['route']['status']) == (True, True, 'wykonana')
    r = client.post(API + '/routes/%d/stops/%d/undo-delivered' % (rid, order.id), headers=naglowki(device, k))
    assert r.status_code == 200 and r.get_json()['route']['status'] == 'w_trasie'
    assert RouteStop.query.filter_by(order_id=order.id).one().delivered_at is None


def test_niedostarczenie_przez_api(app, client):
    device, k = telefon_kierowcy()
    a, paczki_a = zamowienie_z_paczkami(statusy=('zaladowane', 'zaladowane'))
    b, paczki_b = zamowienie_z_paczkami(statusy=('zaladowane', 'zaladowane'))
    t = _trasa_kierowcy(k, [a, b], status='w_trasie')
    zaladuj_wprost(paczki_a + paczki_b, t)
    rid = t.id
    adres = API + '/routes/%d/stops/%d/not-delivered' % (rid, a.id)
    assert client.post(adres, headers=naglowki(device, k), json={'reason': 'nie_wiem'}).status_code == 422
    r = client.post(adres, headers=naglowki(device, k), json={'reason': 'brak_klienta', 'note': u'nie odbiera'})
    assert r.status_code == 200, r.get_data()[:300]
    dane = r.get_json()
    assert dane['route_completed'] is False and [s['order_id'] for s in dane['route']['stops']] == [b.id]
    r = client.post(adres, headers=naglowki(device, k), json={'reason': 'brak_klienta'})
    assert r.status_code == 404 and r.get_json()['error'] == 'stop_not_found'      # przystanku już nie ma


def test_zastepca_zapisuje_na_cudzej_trasie(app, client):
    """Akcje na trasie przyjmujemy od każdego aktywnego kierowcy (zastępstwo); „Moje trasy” są tylko jego."""
    device, wlasciciel = telefon_kierowcy()
    zastepca = kierowca()
    order, (p1, _p2) = zamowienie_z_paczkami()
    t = _trasa_kierowcy(wlasciciel, [order])
    r = client.post(API + '/routes/%d/packages/%d/load' % (t.id, p1.id), headers=naglowki(device, zastepca),
                    json={})
    assert r.status_code == 200
    assert p1.loaded_by_worker_id == zastepca.id
    assert client.get(API + '/routes', headers=naglowki(device, zastepca)).get_json()['count'] == 0
```

- [ ] **Step 2: Testy padają**

Run: `PYTEST tests/test_dostawa_api.py`
Expected: FAIL — 404 na każdym `/api/mobile/delivery/*` (blueprintu nie ma).

- [ ] **Step 3: Odczyty telefonu**

Create `modules/production/logistics/services/dostawa_widok.py`:

```python
# -*- coding: utf-8 -*-
"""
Odczyty telefonu kierowcy (logistyka etap 4, krok 4.4, spec 9.2): „Moje trasy” i trasa z przystankami, paczkami
i stanami zamówień — kształt z kontraktu API Dostawy (plan kroku 4.4b, sekcja „Kontrakt API Dostawy”). Bez zapisów.
"""
import hashlib
import json

from sqlalchemy import and_, or_
from sqlalchemy.orm import selectinload

from modules.production.logistics.models import Route
from modules.production.logistics.services import delivery, dostawa, geocoding, paczki, routes, weryfikacja
from modules.production.models import ProductionOrder

ETYKIETY_STANU = {
    'zweryfikowane': u'Zweryfikowane',
    'niezweryfikowane': u'NIEZWERYFIKOWANE',
    'niespakowane': u'NIESPAKOWANE',
    'zaladowane': u'Załadowane',
    'dostarczone': u'Dostarczone',
    'anulowane': u'Anulowane',
}


def moje_trasy(kierowca_id, dzis):
    """
    „Moje trasy” (spec 9.2 z odstępstwem z planu 4.4b): trasy kierowcy zatwierdzone z `date_to >= dziś` oraz
    załadowane i w drodze bez względu na datę — rozpoczęta trasa nie może zniknąć z telefonu o północy.
    Najbliższa `date_from` pierwsza.
    """
    return (Route.query.options(selectinload(Route.stops), selectinload(Route.vehicle))
            .filter(Route.driver_worker_id == kierowca_id,
                    or_(and_(Route.status == 'zatwierdzona', Route.date_to >= dzis),
                        Route.status.in_(('zaladowana', 'w_trasie'))))
            .order_by(Route.date_from, Route.id).all())


def _zamowienia(ids):
    if not ids:
        return {}
    return {o.id: o for o in ProductionOrder.query.options(selectinload(ProductionOrder.products))
            .filter(ProductionOrder.id.in_(ids))}


def _zaladowana(p, trasa):
    return p.loaded_at is not None and p.loaded_route_id == trasa.id


def serializuj_paczke(p, trasa):
    """PaczkaDostawy z kontraktu; `loaded` — załadowana na TĘ trasę."""
    return {'id': p.id, 'code': p.kod, 'seq': p.seq, 'kind': p.kind, 'pallet_type': p.pallet_type,
            'length_cm': p.length_cm, 'width_cm': p.width_cm, 'verified': p.verified_at is not None,
            'loaded': _zaladowana(p, trasa), 'loaded_at': p.loaded_at.isoformat() if p.loaded_at else None,
            'loaded_method': p.loaded_method}


def _stan(order, aktywne):
    """Stan zamówienia dla kierowcy (spec 9.2)."""
    if not aktywne:
        return 'anulowane'
    statusy = {p.current_status for p in aktywne}
    if statusy == {'dostarczone'}:
        return 'dostarczone'
    if statusy == {'zaladowane'}:
        return 'zaladowane'
    if order.problem_at is not None:
        return 'problem'
    if not delivery.wszystkie_spakowane(order):
        return 'niespakowane'
    if statusy == {'zweryfikowane'}:
        return 'zweryfikowane'
    return 'niezweryfikowane'


def _aktywne_przystanki(trasa, zamowienia):
    return [s for s in trasa.stops if s.order_id in zamowienia and delivery.aktywne_produkty(zamowienia[s.order_id])]


def _krotko(trasa, zamowienia, pakunki):
    """TrasaKrotko z kontraktu: liczniki na przystankach aktywnych i ich aktualnych paczkach."""
    stopy = _aktywne_przystanki(trasa, zamowienia)
    paczki_trasy = [p for s in stopy for p in pakunki.get(s.order_id, [])]
    return {
        'id': trasa.id, 'name': trasa.name,
        'date_from': trasa.date_from.isoformat(), 'date_to': trasa.date_to.isoformat(),
        'status': trasa.status, 'status_label': dostawa.NAZWY_STATUSOW_TRASY.get(trasa.status, trasa.status),
        'vehicle_name': trasa.vehicle.name if trasa.vehicle is not None else None,
        'stops_total': len(stopy),
        'stops_delivered': sum(1 for s in stopy if s.delivered_at is not None),
        'packages_total': len(paczki_trasy),
        'packages_loaded': sum(1 for p in paczki_trasy if _zaladowana(p, trasa)),
    }


def lista_moich_tras(kierowca_id, dzis):
    trasy = moje_trasy(kierowca_id, dzis)
    ids = list({s.order_id for t in trasy for s in t.stops})
    zamowienia = _zamowienia(ids)
    pakunki = paczki.aktualne_paczki_zamowien(ids)
    return [_krotko(t, zamowienia, pakunki) for t in trasy]


def _przystanek(stop, order, numer, pakunki_zamowienia, punkt, trasa):
    aktywne = delivery.aktywne_produkty(order)
    stan = _stan(order, aktywne)
    etykieta = ETYKIETY_STANU.get(stan)
    if stan == 'problem':
        etykieta = u'PROBLEM: ' + weryfikacja.POWODY_PROBLEMU.get(order.problem_reason, order.problem_reason or u'')
    m3 = round(sum(float(p.volume_m3 or 0) * (p.quantity or 1) for p in aktywne), 4)
    return {
        'position': numer,
        'order_id': order.id,
        'internal_order_number': order.internal_order_number,
        'client_name': order.client_name,
        # Osoba do odbioru: osoba z adresu dostawy, potem firma, na końcu klient.
        'recipient': order.delivery_fullname or order.delivery_company or order.client_name,
        'phone': order.client_phone,
        'address': {'street': order.delivery_address, 'postcode': order.delivery_postcode,
                    'city': order.delivery_city, 'country_code': order.delivery_country_code},
        # Tylko punkt dokładny — przybliżony (miejscowość) prowadziłby nawigację w złe miejsce.
        'geo': ({'lat': float(punkt.lat), 'lng': float(punkt.lng)}
                if punkt is not None and punkt.quality == 'dokladna' and punkt.lat is not None else None),
        'order_notes': order.order_notes,
        'm3': m3,
        'weight_kg': int(round(m3 * routes.WAGA_KG_NA_M3)),
        'packages': [serializuj_paczke(p, trasa) for p in pakunki_zamowienia],
        'packages_total': len(pakunki_zamowienia),
        'packages_loaded': sum(1 for p in pakunki_zamowienia if _zaladowana(p, trasa)),
        'state': stan,
        'state_label': etykieta,
        'problem': ({'reason': order.problem_reason,
                     'reason_label': weryfikacja.POWODY_PROBLEMU.get(order.problem_reason, order.problem_reason),
                     'note': order.problem_note} if order.problem_at is not None else None),
        'stays': ({'reason': stop.stays_reason,
                   'reason_label': dostawa.POWODY_ZOSTAJE.get(stop.stays_reason, stop.stays_reason),
                   'note': stop.stays_note} if stop.stays_reason else None),
        'delivered_at': stop.delivered_at.isoformat() if stop.delivered_at else None,
    }


def serializuj(trasa, zamowienia, pakunki, punkty):
    """Trasa z kontraktu. `zamowienia` — {order_id: zamówienie}, `pakunki` — {order_id: [aktualne paczki]}."""
    dane = _krotko(trasa, zamowienia, pakunki)
    kolejne = [zamowienia[s.order_id] for s in trasa.stops if s.order_id in zamowienia]
    przystanki = {s.order_id: s for s in trasa.stops}
    dane.update({
        'vehicle_registration': trasa.vehicle.registration if trasa.vehicle is not None else None,
        'notes': trasa.notes,
        'loaded_at': trasa.loaded_at.isoformat() if trasa.loaded_at else None,
        'departed_at': trasa.departed_at.isoformat() if trasa.departed_at else None,
        'completed_at': trasa.completed_at.isoformat() if trasa.completed_at else None,
        # Trasa odhaczona w panelu — telefon nie cofa wtedy ostatniego dostarczenia (decyzja Konrada 3).
        'completed_by_panel': trasa.status == 'wykonana' and trasa.completed_by is not None,
        'stops': [_przystanek(przystanki[o.id], o, numer, pakunki.get(o.id, []), punkty.get(o.id), trasa)
                  for o, numer, _anulowane in routes.numeracja_przystankow(kolejne)],
    })
    return dane


def wczytaj(route_id):
    """(trasa, zamówienia, paczki, punkty) do GET — kilka zapytań zbiorczych; brak trasy → None."""
    trasa = Route.query.options(selectinload(Route.stops), selectinload(Route.vehicle)).get(route_id)
    if trasa is None:
        return None
    ids = [s.order_id for s in trasa.stops]
    return trasa, _zamowienia(ids), paczki.aktualne_paczki_zamowien(ids), geocoding.geo_zamowien(ids)


def trasa_po_zapisie(trasa):
    """
    Pełna trasa w odpowiedzi zapisu z telefonu — z odczytu bieżącego: dostawa.zablokuj drugi raz w tej samej
    transakcji (blokady już trzymane, nic nie czeka). Zwykły odczyt pokazałby migawkę sprzed czekania na blokady,
    np. paczki załadowane w tym czasie drugim telefonem.
    """
    trasa, zamowienia, pakunki = dostawa.zablokuj(trasa)
    return serializuj(trasa, zamowienia, pakunki, geocoding.geo_zamowien(list(zamowienia)))


def podpis(dane):
    """Skrót treści trasy do ETagu: zmiana czegokolwiek, co widzi kierowca, zmienia ETag."""
    tekst = json.dumps(dane, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha1(tekst.encode('utf-8')).hexdigest()[:20]
```

- [ ] **Step 4: Blueprint telefonu**

Create `modules/production/logistics/routers/dostawa_api.py`:

```python
# -*- coding: utf-8 -*-
"""
API telefonu kierowcy — /api/mobile/delivery/* (logistyka etap 4, krok 4.4, spec 9; kontrakt w planie 4.4b).

Reużywa autoryzację i idempotencję API mobilnego produkcji (require_device_token, with_idempotency). Każde żądanie
ma kierowcę: pierwszy identyfikator z X-Worker-Ids, aktywny pracownik ze znacznikiem is_driver. Odczyty pokazują
trasy tego kierowcy; zapisy przyjmujemy od każdego aktywnego kierowcy (zastępstwo bez przepisywania trasy).
Handlery zapisu NIE commitują — robi to dekorator idempotencji; 400/403/404/409 nie są zapamiętywane
(BLEDY_DO_PONOWIENIA), 422 jest. Kolejność blokad zapisu: pracownicy (touch_sessions w _kierowca) →
dostawa.zablokuj (trasy → deklaracje paczek → zamówienia trasy rosnąco → paczki → pozycje).
"""
from functools import wraps

from flask import Blueprint, g, jsonify, request

from modules.logging import get_structured_logger
from modules.production.logistics.models import Route
from modules.production.logistics.services import dostawa, dostawa_widok, routes
from modules.production.logistics.services.delivery import LogistykaBlad
from modules.production.models import ProductionOrder, ProductionWorker
from modules.production.routers.mobile_api import BLEDY_DO_PONOWIENIA
from modules.production.services import worker_service
from modules.production.services.mobile_api_service import require_device_token, with_idempotency
from modules.production.services.station_catalog import resolve_station_code
from modules.production.services.worker_service import WorkerError
from modules.production.utils.cache import cached_json, if_none_match, make_weak_etag, no_store_json, not_modified

logger = get_structured_logger('production.logistics.dostawa_api')

dostawa_mobile_bp = Blueprint('dostawa_mobile', __name__)

# Wersja KSZTAŁTU odpowiedzi trasy — część ETagu (jak KSZTALT_LISTY Weryfikacji).
# PODBIJ przy każdej zmianie zestawu pól w dostawa_widok.serializuj().
#   1 — 2026-10-01: pierwsza wersja (krok 4.4)
KSZTALT_TRASY = 1


def wymaga_dostawy(f):
    """Urządzenie zarejestrowane na stanowisku Dostawa (kod z JWT, jak Weryfikacja)."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        if resolve_station_code((g.device.station_code or '').strip()) != dostawa.STANOWISKO:
            return jsonify({'error': 'station_not_allowed',
                            'message': u'To urządzenie nie jest zarejestrowane na stanowisku Dostawa.'}), 403
        return f(*args, **kwargs)
    return wrapper


def _kierowca(dotknij=True):
    """
    (kierowca, None) albo (None, odpowiedź). Pierwszy identyfikator z X-Worker-Ids = kierowca (spec 9.1). Brak
    nagłówka → 400 worker_required; nieznany albo nieaktywny → kody WorkerError jak w `complete`; bez znacznika
    kierowcy → 403 not_a_driver. Wszystkie w BLEDY_DO_PONOWIENIA (akcja zostaje w kolejce offline, appka wraca na
    wybór kierowcy). `dotknij` — zapis odświeża sesje pracowników (pierwsze blokady transakcji); odczyt nie.
    """
    try:
        ids = worker_service.resolve_worker_ids(request.headers.get('X-Worker-Ids'), required=False)
    except WorkerError as e:
        payload, status = e.as_response()
        return None, (jsonify(payload), status)
    if not ids:
        return None, (jsonify({'error': 'worker_required',
                               'message': u'Wybierz kierowcę — Dostawa zapisuje, kto ładował i dostarczył.'}), 400)
    kierowca = ProductionWorker.query.get(ids[0])
    if kierowca is None or not kierowca.is_driver or not kierowca.is_active:
        return None, (jsonify({'error': 'not_a_driver',
                               'message': u'Ten pracownik nie jest kierowcą (Flota → Kierowcy).'}), 403)
    g.worker_ids = ids   # audyt zmian statusu pozycji (product_events.current_actor)
    if dotknij:
        worker_service.touch_sessions(ids, device_id=g.device.device_id)
    return kierowca, None


def _brak_trasy():
    return jsonify({'error': 'route_not_found', 'message': u'Nie ma takiej trasy.'}), 404


def _blad(e):
    """Odmowa serwisu → {error, message, …dane}. LogistykaBlad spoza Dostawy (np. trasa usunięta w międzyczasie —
    routes.zablokuj_trasy) dostaje kod według statusu HTTP."""
    kod = getattr(e, 'kod', None) or {404: 'route_not_found', 422: 'invalid_request'}.get(e.status, 'route_status')
    odpowiedz = dict(e.dane or {})
    odpowiedz.update(error=kod, message=e.komunikat)
    return jsonify(odpowiedz), e.status


def _dane_json():
    """Ciało JSON jako słownik; brak, zły JSON albo inny typ niż obiekt → pusty słownik (pola są opcjonalne)."""
    dane = request.get_json(silent=True)
    return dane if isinstance(dane, dict) else {}


def _numer(order_id):
    order = ProductionOrder.query.get(order_id)   # z mapy tożsamości — zamówienie trasy jest już zablokowane
    return order.internal_order_number if order is not None else u'#{}'.format(order_id)


def _zapis(route_id, akcja):
    """
    Szkielet zapisu: kierowca (pracownicy pierwsi w kolejności blokad), trasa (404 — także robocza, której telefon
    nie widzi), akcja serwisu Dostawy, odpowiedź z pełną trasą z odczytu bieżącego.
    `akcja(trasa, kierowca) -> (komunikat, {pola dodatkowe})`.
    """
    kierowca, err = _kierowca()
    if err:
        return err
    trasa = Route.query.get(route_id)
    if trasa is None or trasa.status == 'robocza':
        return _brak_trasy()
    try:
        komunikat, dodatkowe = akcja(trasa, kierowca)
        dane = {'route': dostawa_widok.trasa_po_zapisie(trasa), 'message': komunikat}
    except LogistykaBlad as e:
        return _blad(e)
    dane.update(dodatkowe)
    logger.info('Dostawa: zapis', extra={'route_id': route_id, 'endpoint': request.endpoint,
                                         'worker_id': kierowca.id, 'device_id': g.device.device_id})
    return jsonify(dane), 200


# ── Odczyty ─────────────────────────────────────────────────────────────────────────────

@dostawa_mobile_bp.route('/routes', methods=['GET'])
@require_device_token
@wymaga_dostawy
def delivery_routes():
    """GET /api/mobile/delivery/routes — „Moje trasy” kierowcy (spec 9.2), bez cache."""
    kierowca, err = _kierowca(dotknij=False)
    if err:
        return err
    trasy = dostawa_widok.lista_moich_tras(kierowca.id, routes.dzis())
    return no_store_json({'routes': trasy, 'count': len(trasy)})


@dostawa_mobile_bp.route('/routes/<int:route_id>', methods=['GET'])
@require_device_token
@wymaga_dostawy
def delivery_route(route_id):
    """GET /api/mobile/delivery/routes/<id> — trasa z przystankami i paczkami, ETag z treści (max-age=0)."""
    _kierowca_, err = _kierowca(dotknij=False)
    if err:
        return err
    wczytane = dostawa_widok.wczytaj(route_id)
    if wczytane is None or wczytane[0].status == 'robocza':
        return _brak_trasy()
    dane = dostawa_widok.serializuj(*wczytane)
    etag = make_weak_etag('dostawa', KSZTALT_TRASY, route_id, dostawa_widok.podpis(dane))
    if if_none_match(etag):
        return not_modified(etag, max_age=0)
    return cached_json({'route': dane}, etag, max_age=0)


# ── Załadunek ───────────────────────────────────────────────────────────────────────────

@dostawa_mobile_bp.route('/routes/<int:route_id>/packages/<int:package_id>/load', methods=['POST'])
@require_device_token
@wymaga_dostawy
@with_idempotency(retryable_statuses=BLEDY_DO_PONOWIENIA)
def delivery_package_load(route_id, package_id):
    """POST …/packages/<id>/load {"method": "skan"|"reczne"} (spec 9.3)."""
    metoda = _dane_json().get('method')
    try:
        dostawa.waliduj_metode(metoda)
    except dostawa.DostawaBlad as e:
        return _blad(e)

    def akcja(trasa, kierowca):
        paczka, zmieniono = dostawa.zaladuj_paczke(trasa, package_id, metoda, worker_id=kierowca.id,
                                                   device_id=g.device.id)
        komunikat = (u'Paczka {} załadowana.' if zmieniono else u'Paczka {} była już załadowana.').format(paczka.kod)
        return komunikat, {'package': dostawa_widok.serializuj_paczke(paczka, trasa), 'changed': zmieniono}
    return _zapis(route_id, akcja)


@dostawa_mobile_bp.route('/routes/<int:route_id>/packages/<int:package_id>/unload', methods=['POST'])
@require_device_token
@wymaga_dostawy
@with_idempotency(retryable_statuses=BLEDY_DO_PONOWIENIA)
def delivery_package_unload(route_id, package_id):
    """POST …/packages/<id>/unload — cofnięcie pomyłki przed zakończeniem załadunku (spec 9.3)."""
    def akcja(trasa, kierowca):
        paczka, zmieniono = dostawa.rozladuj_paczke(trasa, package_id, worker_id=kierowca.id, device_id=g.device.id)
        komunikat = (u'Paczka {} zdjęta z auta.' if zmieniono else u'Paczka {} nie była załadowana.').format(paczka.kod)
        return komunikat, {'package': dostawa_widok.serializuj_paczke(paczka, trasa), 'changed': zmieniono}
    return _zapis(route_id, akcja)


@dostawa_mobile_bp.route('/routes/<int:route_id>/stops/<int:order_id>/stays', methods=['POST'])
@require_device_token
@wymaga_dostawy
@with_idempotency(retryable_statuses=BLEDY_DO_PONOWIENIA)
def delivery_stop_stays(route_id, order_id):
    """POST …/stops/<order_id>/stays {"reason", "note"?} — „Zostaje” (spec 9.3)."""
    dane = _dane_json()
    try:
        dostawa.waliduj_powod(dane.get('reason'), dostawa.POWODY_ZOSTAJE)
    except dostawa.DostawaBlad as e:
        return _blad(e)

    def akcja(trasa, kierowca):
        zmieniono = dostawa.ustaw_zostaje(trasa, order_id, dane.get('reason'), dane.get('note'),
                                          worker_id=kierowca.id, device_id=g.device.id)
        return (u'Zamówienie {} zostaje: {}.'.format(_numer(order_id), dostawa.POWODY_ZOSTAJE[dane.get('reason')]),
                {'changed': zmieniono})
    return _zapis(route_id, akcja)


@dostawa_mobile_bp.route('/routes/<int:route_id>/stops/<int:order_id>/stays', methods=['DELETE'])
@require_device_token
@wymaga_dostawy
@with_idempotency(retryable_statuses=BLEDY_DO_PONOWIENIA)
def delivery_stop_stays_remove(route_id, order_id):
    """DELETE …/stops/<order_id>/stays — zdjęcie „Zostaje” przed zakończeniem załadunku."""
    def akcja(trasa, kierowca):
        zmieniono = dostawa.zdejmij_zostaje(trasa, order_id, worker_id=kierowca.id, device_id=g.device.id)
        return (u'Zamówienie {} jedzie.'.format(_numer(order_id)) if zmieniono
                else u'Zamówienie {} nie miało „Zostaje”.'.format(_numer(order_id))), {'changed': zmieniono}
    return _zapis(route_id, akcja)


@dostawa_mobile_bp.route('/routes/<int:route_id>/finish-loading', methods=['POST'])
@require_device_token
@wymaga_dostawy
@with_idempotency(retryable_statuses=BLEDY_DO_PONOWIENIA)
def delivery_finish_loading(route_id):
    """POST …/finish-loading — „Zakończ załadunek” (spec 9.3); braki → 409 loading_incomplete z `braki`."""
    def akcja(trasa, kierowca):
        trasa_po, usuniete = dostawa.zakoncz_zaladunek(trasa, worker_id=kierowca.id, device_id=g.device.id)
        komunikat = u'Załadunek zakończony: {} przystanków.'.format(len(trasa_po.stops))
        if usuniete:
            komunikat += u' Zdjęte z trasy: {}.'.format(u', '.join(
                u['internal_order_number'] or u'#{}'.format(u['order_id']) for u in usuniete))
        return komunikat, {'removed': usuniete}
    return _zapis(route_id, akcja)


@dostawa_mobile_bp.route('/routes/<int:route_id>/depart', methods=['POST'])
@require_device_token
@wymaga_dostawy
@with_idempotency(retryable_statuses=BLEDY_DO_PONOWIENIA)
def delivery_depart(route_id):
    """POST …/depart — „Ruszam w trasę” (spec 9.4)."""
    def akcja(trasa, kierowca):
        trasa_po, zmieniono = dostawa.ruszaj(trasa, worker_id=kierowca.id, device_id=g.device.id)
        return (u'Trasa „{}” w drodze.' if zmieniono else u'Trasa „{}” była już w drodze.').format(trasa_po.name), \
            {'changed': zmieniono}
    return _zapis(route_id, akcja)


# ── Dostarczenia ────────────────────────────────────────────────────────────────────────

@dostawa_mobile_bp.route('/routes/<int:route_id>/stops/<int:order_id>/delivered', methods=['POST'])
@require_device_token
@wymaga_dostawy
@with_idempotency(retryable_statuses=BLEDY_DO_PONOWIENIA)
def delivery_stop_delivered(route_id, order_id):
    """POST …/stops/<order_id>/delivered — „Dostarczone” (spec 9.5)."""
    def akcja(trasa, kierowca):
        _t, zmieniono, zamknieta = dostawa.dostarcz(trasa, order_id, worker_id=kierowca.id, device_id=g.device.id)
        komunikat = (u'Dostarczono zamówienie {}.' if zmieniono
                     else u'Zamówienie {} było już dostarczone.').format(_numer(order_id))
        if zamknieta:
            komunikat += u' Trasa zakończona.'
        return komunikat, {'changed': zmieniono, 'route_completed': zamknieta}
    return _zapis(route_id, akcja)


@dostawa_mobile_bp.route('/routes/<int:route_id>/stops/<int:order_id>/not-delivered', methods=['POST'])
@require_device_token
@wymaga_dostawy
@with_idempotency(retryable_statuses=BLEDY_DO_PONOWIENIA)
def delivery_stop_not_delivered(route_id, order_id):
    """POST …/stops/<order_id>/not-delivered {"reason", "note"?} — „Niedostarczone” (spec 9.5, 4.5)."""
    dane = _dane_json()
    try:
        dostawa.waliduj_powod(dane.get('reason'), dostawa.POWODY_NIEDOSTARCZENIA)
    except dostawa.DostawaBlad as e:
        return _blad(e)

    def akcja(trasa, kierowca):
        numer = _numer(order_id)
        _t, zamknieta = dostawa.nie_dostarcz(trasa, order_id, dane.get('reason'), dane.get('note'),
                                             worker_id=kierowca.id, device_id=g.device.id)
        komunikat = u'Zamówienie {} niedostarczone — wraca do puli bez trasy.'.format(numer)
        if zamknieta:
            komunikat += u' Trasa zakończona.'
        return komunikat, {'route_completed': zamknieta}
    return _zapis(route_id, akcja)


@dostawa_mobile_bp.route('/routes/<int:route_id>/stops/<int:order_id>/undo-delivered', methods=['POST'])
@require_device_token
@wymaga_dostawy
@with_idempotency(retryable_statuses=BLEDY_DO_PONOWIENIA)
def delivery_stop_undo_delivered(route_id, order_id):
    """POST …/stops/<order_id>/undo-delivered — cofnięcie ostatniego dostarczenia (spec 9.5; także zaraz po
    automatycznym zamknięciu trasy — decyzja Konrada 3)."""
    def akcja(trasa, kierowca):
        _t, zmieniono = dostawa.cofnij_dostarczenie(trasa, order_id, z_telefonu=True, worker_id=kierowca.id,
                                                    device_id=g.device.id)
        return (u'Cofnięto dostarczenie zamówienia {}.' if zmieniono
                else u'Zamówienie {} nie było dostarczone.').format(_numer(order_id)), {'changed': zmieniono}
    return _zapis(route_id, akcja)
```

Uwaga do `_zapis`: `trasa_po_zapisie` stoi w tym samym `try` co akcja — gdyby trasa zniknęła w międzyczasie (LogistykaBlad 404 z `routes.zablokuj_trasy`), odpowiedzią jest 404, a nie 500.

- [ ] **Step 5: Rejestracja blueprintu**

`app.py` — pod rejestracją `weryfikacja_mobile_bp` (:881-882):
```python
        from modules.production.logistics.routers.dostawa_api import dostawa_mobile_bp
        app.register_blueprint(dostawa_mobile_bp, url_prefix='/api/mobile/delivery')
```
`tests/logistyka_fixtures.py` — pod rejestracją `weryfikacja_mobile_bp` (:84-85):
```python
    from modules.production.logistics.routers.dostawa_api import dostawa_mobile_bp
    app.register_blueprint(dostawa_mobile_bp, url_prefix='/api/mobile/delivery')
```

- [ ] **Step 6: Testy przechodzą**

Run: `PYTEST tests/test_dostawa_api.py tests/test_dostawa_schemat.py tests/test_weryfikacja_api.py`
Expected: PASS.

- [ ] **Step 7: Pełny pakiet (w worktree toru)**

Run: `docker compose -p logistyka4-b6 run --rm --no-deps app pytest tests/ -q -p no:cacheprovider`
Expected: `wynik Task 4 + 13 passed, 3 skipped`. **Nie równolegle z pełnym pakietem Task 5** — pakiet zajmuje ok. 13 GiB z 15,5 GiB pamięci Dockera.

- [ ] **Step 8: Commit**

```bash
git add modules/production/logistics/services/dostawa_widok.py modules/production/logistics/routers/dostawa_api.py \
  app.py tests/logistyka_fixtures.py tests/test_dostawa_api.py
git commit -m "feat(production): API telefonu kierowcy - moje trasy, zaladunek, wyjazd, dostarczenia" \
  -m "Krok 4.4 logistyki: blueprint /api/mobile/delivery (stanowisko delivery, kierowca z X-Worker-Ids), Moje trasy (zaladowane i w drodze bez wzgledu na date), trasa z ETagiem z tresci, zapisy z pelna trasa z odczytu biezacego, idempotencja z BLEDY_DO_PONOWIENIA." \
  -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Front panelu tras i listy Logistyki (frontend-design)

**Tor równoległy** z Task 5 (i Task 6): worktree `.claude/worktrees/logistyka-etap-4-b7`, gałąź `claude/logistyka-etap-4-b7` z commita Task 4, projekt dockera `logistyka4-b7`; kod według kontraktu z Task 5 (Interfaces niżej). W torze tylko testy celowane (Step 9 bez oględzin); oględziny i pełny pakiet (Step 10) po scaleniu cherry-pickiem do głównego worktree, gdy Task 5 jest już scalony.

**REQUIRED SUB-SKILL:** `frontend-design:frontend-design` — w istniejącym stylu zakładek (tokeny `--lg-*`, klasy `lg-*`, ikony Font Awesome z `static/vendor`), dostęp z klawiatury, bez animacji przy `prefers-reduced-motion`. Sprawdź, że użyte ikony są w wersji Font Awesome dołączonej do repo (grep w `static/vendor`); brakującą zastąp istniejącą.

**Files:**
- Modify: `modules/production/logistics/static/js/logistics-routes.js` (:104-131 stałe i `AKCJE`, :143-147 `listy`, :626-651 `pozycjaListyHtml`, :679-690 `rysujListe`, :822-828 `skrotTrasy`, :1175-1201 `renderujEdytor`, :1635-1655 `cofnij`/`przywroc`, :1832-1880 `przystanekHtml`, :1935-1960 `renderujPrzystanki`, :3034-3070 okno „Odhacz”, :3127-3140, :3290-3335, :3440-3460 obsługa akcji)
- Modify: `modules/production/logistics/static/js/logistics.js` (:110-115 `KOLEJNOSC_ETAPOW`, :149-152 `STATUSY_TRAS`/`IKONY_TRAS`, :966-970 blokada selecta, :1780, :1861, :1889)
- Modify: `modules/production/logistics/static/js/logistics-map.js` (:392-399 `powodBlokadySposobu`, :1693 `NAZWY_STATUSOW_TRAS`, :1850 tekst legendy)
- Modify: `modules/production/logistics/static/css/logistics-trasy.css`, `modules/production/logistics/static/css/logistics.css`
- Modify: `modules/production/logistics/templates/logistics/tab_content.html` (sekcje listy tras :363-382, nagłówek edytora :395-400, okno „Odhacz” :619-635, wersje `?v=`)
- Create: `tests/test_dostawa_panel_ui.py`
- Modify: `tests/test_logistyka_trasy_ui.py:41`, `tests/test_weryfikacja_panel.py:88-91`

**Interfaces:**
- Consumes (Task 5): w trasie `postep {przystanki, zaladowane, dostarczone}`, `zaladowana`, `wyjazd`, `odhaczona_w_panelu`; przy przystanku `zamowienie.dostawa {dostarczono, zostaje}`, `zamowienie.paczki.zaladowane`; endpointy `POST /routes/<id>/unload`, `POST /routes/<id>/stops/<oid>/undo-delivered` (Task 4); `lista.serializuj(...)['etap']` może mieć `{status: 'w_trasie', nazwa: 'W trasie'}` (Task 2).
- Produces: UI z sekcji 9.7 i 11 specu; brak „Przywróć trasę”.

- [ ] **Step 1: Testy, które padną**

Create `tests/test_dostawa_panel_ui.py`:

```python
# -*- coding: utf-8 -*-
"""Front panelu po kroku 4.4 (spec 9.7 i 11): sekcje Załadowane i W trasie, akcje według statusu, „Cofnij załadunek”
i „Cofnij dostarczenie” zamiast „Przywróć trasę”, postęp Dostawy, etap „W trasie” na liście i blokada sposobu
dostawy po załadunku. Pilnujemy treści plików (jak tests/test_logistyka_trasy_ui.py) i renderu szablonu."""
import os
import re

from tests.logistyka_fixtures import BASE, app, client  # noqa: F401

KATALOG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       'modules', 'production', 'logistics')


def _plik(*czesci):
    with open(os.path.join(KATALOG, *czesci), encoding='utf-8') as f:
        return f.read()


def test_trasy_js_zna_statusy_dostawy_i_nowe_akcje():
    js = _plik('static', 'js', 'logistics-routes.js')
    for fraza in ("zaladowana: 'Załadowana'", "w_trasie: 'W trasie'", "'/unload'", "'/undo-delivered'",
                  "'cofnij-zaladunek'", "'cofnij-dostarczenie'", 'postep', 'dostarczono', 'zostaje',
                  "const ODHACZALNE = ['robocza', 'zatwierdzona', 'zaladowana', 'w_trasie']"):
        assert fraza in js, fraza
    assert '/restore' not in js and "'przywroc'" not in js
    akcje = js[js.index('const AKCJE = {'):]
    akcje = akcje[:akcje.index('\n    };')]
    assert re.search(r"zaladowana: \[\s*\['routimo'[^\]]*\],\s*\['cofnij-zaladunek'[^\]]*\],\s*\['wykonaj'", akcje)
    assert re.search(r"w_trasie: \[\s*\['routimo'[^\]]*\],\s*\['wykonaj'", akcje)
    assert re.search(r"wykonana: \[\s*\['routimo'[^\]]*\],\s*\]", akcje)   # bez odhaczania i przywracania


def test_szablon_ma_sekcje_postep_i_opis_odhaczenia(client):
    r = client.get(BASE + '/tab-content')
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    for nazwa in ('zaladowane', 'zaladowane-ile', 'w-trasie', 'w-trasie-ile', 'postep'):
        assert 'data-lg-trasy="%s"' % nazwa in html, nazwa
    assert html.index('data-lg-trasy="zatwierdzone"') < html.index('data-lg-trasy="zaladowane"') \
        < html.index('data-lg-trasy="w-trasie"') < html.index('data-lg-trasy="wykonane"')
    okno = html[html.index('data-lg="trasa-wykonaj-dialog"'):]
    okno = okno[:okno.index('</dialog>')]
    assert u'Base.' in okno and u'kierowc' in okno     # odhaczenie wysyła statusy; dostarczone z telefonu zostają


def test_lista_logistyki_zna_etap_w_trasie_i_blokuje_sposob_po_zaladunku():
    js = _plik('static', 'js', 'logistics.js')
    kolejnosc = re.findall(r"'(\w+)'", re.search(r"KOLEJNOSC_ETAPOW = \[([^\]]*)\]", js).group(1))
    i = kolejnosc.index('zaladowane')
    assert kolejnosc[i:i + 3] == ['zaladowane', 'w_trasie', 'dostarczone']
    for fraza in ("zaladowana: 'załadowana'", "w_trasie: 'w trasie'", 'const poZaladunku'):
        assert fraza in js, fraza
    assert 'w.spakowane && !poZaladunku(w)' in js
    assert js.count('!poZaladunku(w)') >= 3          # wiersz, hurt sposobu, hurt podpowiedzi — bez okna 8.7
    mapa = _plik('static', 'js', 'logistics-map.js')
    assert "w_trasie: 'W trasie'" in mapa and "zaladowana: 'Załadowana'" in mapa
    assert u'załadowany' in mapa[mapa.index('function powodBlokadySposobu'):][:1500]


def test_style_statusow_dostawy():
    css = _plik('static', 'css', 'logistics-trasy.css')
    for klasa in ('.lg-status--zaladowana', '.lg-status--w_trasie', '.lg-plakietka-trasy--zaladowana',
                  '.lg-plakietka-trasy--w_trasie', '.lg-edytor-postep', '.lg-trasa-pozycja-postep',
                  '.lg-przystanek-dostarczono', '.lg-przystanek-zostaje', '.lg-wykonaj-pozycja--dostarczone'):
        assert klasa in css, klasa
    assert '[data-etap="w_trasie"]' in _plik('static', 'css', 'logistics.css')
```

Zmień istniejące testy:
- `tests/test_logistyka_trasy_ui.py:41` — w krotce fraz `'/restore'` → `'/undo-delivered', '/unload'`.
- `tests/test_weryfikacja_panel.py:90-91`:
```python
    i = wartosci.index('spakowane')
    # Krok 4.4: „W trasie” to etap zamówienia (pozycje załadowane, trasa w drodze), nie status pozycji — stoi
    # między załadowanymi a dostarczonymi.
    assert wartosci[i:i + 5] == ['spakowane', 'zweryfikowane', 'zaladowane', 'w_trasie', 'dostarczone']
```

- [ ] **Step 2: Testy padają**

Run: `PYTEST tests/test_dostawa_panel_ui.py tests/test_logistyka_trasy_ui.py tests/test_weryfikacja_panel.py`
Expected: FAIL — brak fraz w JS, brak sekcji w szablonie, brak klas w CSS; `test_js_uzywa_api_tras_i_floty` (`/undo-delivered`), `test_front_zna_nowe_etapy_i_filtry` (kolejność bez `w_trasie`).

- [ ] **Step 3: Lista tras i nagłówek edytora**

`logistics-routes.js` — stałe (zamiast :104-131):
```js
    const NAZWY_STATUSOW = { robocza: 'Robocza', zatwierdzona: 'Zatwierdzona', zaladowana: 'Załadowana',
        w_trasie: 'W trasie', wykonana: 'Wykonana' };
    const IKONY_STATUSOW = { robocza: 'fa-pen', zatwierdzona: 'fa-lock', zaladowana: 'fa-truck-ramp-box',
        w_trasie: 'fa-truck-fast', wykonana: 'fa-check' };
    // Trasy, które da się odhaczyć w panelu (R12 etapu 3: także robocza; krok 4.4: załadowana i w drodze).
    const ODHACZALNE = ['robocza', 'zatwierdzona', 'zaladowana', 'w_trasie'];
    // [akcja, etykieta, ikona, odmiana przycisku] — przyciski edytora wg statusu. Krok 4.4: „Przywróć trasę”
    // zastępuje „Cofnij dostarczenie” przy przystanku (spec 9.7), trasa załadowana ma „Cofnij załadunek”.
    const AKCJE = {
        nowa: [
            ['utworz', 'Utwórz trasę', 'fa-plus', 'glowny'],
            ['anuluj-nowa', 'Anuluj', '', ''],
        ],
        robocza: [
            ['zapisz', 'Zapisz', 'fa-floppy-disk', ''],
            ['zatwierdz', 'Zatwierdź', 'fa-lock', 'glowny'],
            ['wykonaj', 'Odhacz jako wykonaną', 'fa-check-double', ''],
            ['usun', 'Usuń trasę', 'fa-trash-can', 'niebezpieczny'],
        ],
        zatwierdzona: [
            ['routimo', 'Eksport do Routimo', 'fa-file-excel', 'glowny'],
            ['wykonaj', 'Odhacz jako wykonaną', 'fa-check-double', ''],
            ['cofnij', 'Cofnij do roboczej', 'fa-lock-open', ''],
        ],
        zaladowana: [
            ['routimo', 'Eksport do Routimo', 'fa-file-excel', ''],
            ['cofnij-zaladunek', 'Cofnij załadunek', 'fa-dolly', ''],
            ['wykonaj', 'Odhacz jako wykonaną', 'fa-check-double', ''],
        ],
        w_trasie: [
            ['routimo', 'Eksport do Routimo', 'fa-file-excel', ''],
            ['wykonaj', 'Odhacz jako wykonaną', 'fa-check-double', ''],
        ],
        wykonana: [
            ['routimo', 'Eksport do Routimo', 'fa-file-excel', ''],
        ],
    };
```
`listy` (:143-147):
```js
    const listy = {
        robocza: { lista: el('robocze'), ile: el('robocze-ile') },
        zatwierdzona: { lista: el('zatwierdzone'), ile: el('zatwierdzone-ile') },
        zaladowana: { lista: el('zaladowane'), ile: el('zaladowane-ile') },
        w_trasie: { lista: el('w-trasie'), ile: el('w-trasie-ile') },
        wykonana: { lista: el('wykonane-lista'), ile: el('wykonane-ile') },
    };
```
`rysujListe` — `sekcje` (komentarz „robocze i zatwierdzone — najbliższe na górze” → „aktywne — najbliższe na górze”):
```js
        const sekcje = {
            robocza: [wgStatusu('robocza'), 'Brak tras roboczych.'],
            zatwierdzona: [wgStatusu('zatwierdzona'), 'Brak zatwierdzonych tras.'],
            zaladowana: [wgStatusu('zaladowana'), 'Brak załadowanych tras.'],
            w_trasie: [wgStatusu('w_trasie'), 'Brak tras w drodze.'],
            wykonana: [wykonane, stan.filtrWykonanych ? 'Brak wykonanych tras w tych dniach.'
                : 'Brak wykonanych tras w ostatnich 30 dniach.'],
        };
```
Postęp (nad `pozycjaListyHtml`):
```js
    // Krok 4.4 (spec 9.7): „załadowano 7/8 · dostarczono 3/7” — liczy serwer (routes.postep) na przystankach
    // aktywnych. Zatwierdzona pokazuje załadunek dopiero, gdy kierowca zaczął ładować; wykonana — same dostarczenia.
    function postepTekst(t) {
        const p = t && t.postep;
        if (!p || !p.przystanki) return '';
        const zaladowano = 'załadowano ' + p.zaladowane + '/' + p.przystanki;
        const dostarczono = 'dostarczono ' + p.dostarczone + '/' + p.przystanki;
        if (t.status === 'zatwierdzona') return p.zaladowane ? zaladowano : '';
        if (t.status === 'zaladowana') return zaladowano;
        if (t.status === 'w_trasie') return zaladowano + ' · ' + dostarczono;
        if (t.status === 'wykonana') return dostarczono;
        return '';
    }
```
W `pozycjaListyHtml` — po `lg-trasa-pozycja-liczby` dopisz (i dołóż tekst do `opis` w aria-label):
```js
            (postepTekst(t) ? '<span class="lg-trasa-pozycja-postep">' + esc(postepTekst(t)) + '</span>' : '') +
```
`skrotTrasy` — dopisz pola: `postep: r.postep, zaladowana: r.zaladowana, wyjazd: r.wyjazd, odhaczona_w_panelu: r.odhaczona_w_panelu`.

Szablon `tab_content.html` — między sekcją Zatwierdzone a `<details … wykonane>`:
```html
        <section class="lg-trasy-sekcja" aria-labelledby="lg-trasy-zaladowane">
          <h3 class="lg-trasy-sekcja-tytul" id="lg-trasy-zaladowane">Załadowane <span class="lg-trasy-sekcja-ile" data-lg-trasy="zaladowane-ile"></span></h3>
          <ul class="lg-trasy-pozycje" data-lg-trasy="zaladowane"></ul>
        </section>
        <section class="lg-trasy-sekcja" aria-labelledby="lg-trasy-w-trasie">
          <h3 class="lg-trasy-sekcja-tytul" id="lg-trasy-w-trasie">W trasie <span class="lg-trasy-sekcja-ile" data-lg-trasy="w-trasie-ile"></span></h3>
          <ul class="lg-trasy-pozycje" data-lg-trasy="w-trasie"></ul>
        </section>
```
nagłówek edytora — w `.lg-edytor-tytul-rzad` za `<h2 … data-lg-trasy="tytul">`:
```html
              <span class="lg-edytor-postep" data-lg-trasy="postep" aria-live="polite"></span>
```
`renderujEdytor` — po `tytulEl.textContent = …`:
```js
        if (postepEl) postepEl.textContent = t ? postepTekst(t) : '';
```
(`const postepEl = el('postep');` w sekcji „Elementy”).

- [ ] **Step 4: Przystanki — Dostawa i „Cofnij dostarczenie”**

`przystanekHtml(z, indeks, ile, numer, edyt, status)` (dodatkowy parametr — status trasy; `renderujPrzystanki` podaje `t.status`). Poniżej adresu (`lg-przystanek-adres`) dopisz pasek Dostawy dla tras od zatwierdzonej wzwyż (robocza go nie ma):
```js
    // Krok 4.4 (spec 9.7): przy przystanku paczki i stan Dostawy — „załadowano 1/2”, „Zostaje: <powód>”,
    // „Dostarczono 14:05” z „Cofnij dostarczenie” (trasa w drodze albo wykonana; zastępuje „Przywróć trasę”).
    function dostawaPrzystankuHtml(z, status) {
        if (status === 'robocza') return '';
        const d = z.dostawa || {};
        const czesci = [];
        if (d.dostarczono) {
            czesci.push('<span class="lg-przystanek-dostarczono"><i class="fas fa-check" aria-hidden="true"></i>' +
                'Dostarczono ' + esc(godzinaZIso(d.dostarczono)) + '</span>');
            if (status === 'w_trasie' || status === 'wykonana') {
                czesci.push('<button type="button" class="lg-przycisk lg-przycisk--cichy lg-przystanek-cofnij"' +
                    ' data-lg-przystanek="cofnij-dostarczenie"' +
                    ' aria-label="' + esc('Cofnij dostarczenie zamówienia ' + z.numer) + '">' +
                    '<i class="fas fa-rotate-left" aria-hidden="true"></i><span>Cofnij dostarczenie</span></button>');
            }
        } else if (d.zostaje) {
            czesci.push('<span class="lg-przystanek-zostaje">Zostaje: ' + esc(d.zostaje.etykieta) +
                (d.zostaje.notatka ? ' — ' + esc(d.zostaje.notatka) : '') + '</span>');
        }
        if (z.paczki && status !== 'wykonana') {
            czesci.push('<span class="lg-przystanek-paczki">załadowano ' + esc(z.paczki.zaladowane) + '/' +
                esc(z.paczki.liczba) + '</span>');
        }
        return czesci.length ? '<div class="lg-przystanek-dostawa">' + czesci.join('') + '</div>' : '';
    }
```
Pomocnik (w sekcji funkcji pomocniczych pliku — `logistics.js` ma własny `godzina`, ale pliki są osobnymi modułami):
```js
    // „14:05” z ISO serwera (czas lokalny bez strefy, jak w całym API logistyki) — bez przeliczania stref.
    const godzinaZIso = (iso) => (iso && iso.length >= 16 ? iso.slice(11, 16) : '');
```

Obsługa kliknięcia w liście przystanków (tam, gdzie dziś `data-lg-przystanek="usun"`): `cofnij-dostarczenie` →
```js
                if (window.confirm('Cofnąć dostarczenie zamówienia ' + numerZamowienia + '?\n' +
                    'Zamówienie znów będzie otwarte, a Base. dostanie status „Wysłane - trans. WoodPower”.')) {
                    mutacja((ctx) => cofnijDostarczenie(ctx, orderId));
                }
```
i nowe funkcje (zamiast `przywroc`):
```js
    async function cofnijDostarczenie(ctx, orderId) {
        const t = ctx.trasa;
        if (!t) return;
        const odp = await zapytanie('/routes/' + t.id + '/stops/' + orderId + '/undo-delivered', { metoda: 'POST', dane: {} });
        if (zniszczona) return;
        przyjmijOdpowiedz(ctx, odp.route, { formularz: true, zmiana: true });
        komunikat('info', 'Cofnięto dostarczenie. Trasa „' + odp.route.nazwa + '” jest znów w drodze.', { klucz: 'trasa' });
        fokusNaTytul(ctx);
    }

    async function cofnijZaladunek(ctx) {
        const t = ctx.trasa;
        if (!t) return;
        const odp = await zapytanie('/routes/' + t.id + '/unload', { metoda: 'POST', dane: {} });
        if (zniszczona) return;
        przyjmijOdpowiedz(ctx, odp.route, { formularz: true, zmiana: true });
        komunikat('info', 'Trasa „' + odp.route.nazwa + '” znów jest zatwierdzona — kierowca załaduje ją od nowa.',
            { klucz: 'trasa' });
        fokusNaTytul(ctx);
    }
```
obsługa akcji (zamiast `case 'przywroc'`):
```js
            case 'cofnij-zaladunek':
                if (t && window.confirm('Cofnąć załadunek trasy „' + t.nazwa + '”?\n' +
                    'Paczki trzeba będzie załadować od nowa, a Base. dostanie z powrotem status „Planowana trasa”.')) {
                    mutacja(cofnijZaladunek);
                }
                break;
```
Usuń `przywroc` i komentarz nagłówka pliku z listą endpointów (:29) popraw: `/approve | /revert | /unload | /complete | /stops/<oid>/undo-delivered`; w linii :32 eksport Routimo: „(od zatwierdzonej wzwyż)”.

- [ ] **Step 5: Okno „Odhacz jako wykonaną”**

- Wszystkie warunki „robocza albo zatwierdzona” w oknie (`odswiezPrzyciskiWykonania` :3135, komunikat po odczycie :3292, `otworzWykonanie` :3306, `przygotujWykonanie` :3330) → `ODHACZALNE.includes(t.status)`; komentarz :3127 „nie jest już robocza ani zatwierdzona” → „nie jest już do odhaczenia (wykonana)”.
- Stan przystanku dostarczonego przez kierowcę — zawsze dostarczony, pole zaznaczone i nieaktywne:
```js
    const UWAGA_WYKONANIA = {
        niespakowane: 'wróci do puli bez trasy; spakuj na tablecie, żeby oznaczyć jako dostarczone',
        anulowane: 'zdejmiemy z trasy',
        dostarczone: 'dostarczone przez kierowcę — zostaje dostarczone',
    };

    function stanPrzystankuWykonania(p) {
        const z = p.zamowienie || {};
        if (z.dostawa && z.dostawa.dostarczono) return 'dostarczone';
        if (p.anulowane || anulowane(z)) return 'anulowane';
        return z.spakowane ? 'spakowane' : 'niespakowane';
    }
```
w `pozycjaWykonaniaHtml`: `const zaznaczone = stanP === 'dostarczone' || (mozna && (w.wybory.has(z.id) ? w.wybory.get(z.id) : true));`; w `stanWykonaniaHtml`: `if (stanP === 'dostarczone') return znacznikEtapuHtml('dostarczone', 'dostarczone');`; w `odswiezLicznikWykonania` klasa `lg-wykonaj-pozycja--dostarczone` liczy się jako dostarczone (pole i tak jest zaznaczone). Wysyłka listy: przystanki dostarczone mogą, ale nie muszą być w `delivered_order_ids` — serwer i tak trzyma je jako dostarczone.
- Opis w szablonie (`<p class="lg-dialog-opis">` okna): „Zaznaczone zamówienia oznaczymy jako dostarczone (Base. dostanie status „Dostarczona - trans. WoodPower”), odznaczone zdejmiemy z trasy i wrócą do puli bez trasy. Dostarczone mogą być tylko zamówienia spakowane w całości, a przystanki dostarczone już przez kierowcę zostają dostarczone.” Komentarz Jinja nad oknem — dopisz zdanie o przystankach dostarczonych przez kierowcę.

- [ ] **Step 6: Lista Logistyki i mapa**

`logistics.js`:
```js
    const KOLEJNOSC_ETAPOW = [
        'czeka_na_wyciecie', 'czeka_na_skladanie', 'czeka_na_sklejanie',
        'czeka_na_formatowanie', 'czeka_na_krawedzie', 'czeka_na_lakiernie',
        // Krok 4.4: „W trasie” to etap zamówienia (pozycje załadowane, trasa w drodze), nie status pozycji.
        'czeka_na_pakowanie', 'spakowane', 'zweryfikowane', 'zaladowane', 'w_trasie', 'dostarczone',
        'wstrzymane', 'anulowane',
    ];
```
```js
    const STATUSY_TRAS = { robocza: 'robocza', zatwierdzona: 'zatwierdzona', zaladowana: 'załadowana',
        w_trasie: 'w trasie', wykonana: 'wykonana' };
    // Status trasy na plakietce jako znak — te same ikony co w edytorze trasy (ołówek = szkic, kłódka = zatwierdzona,
    // auto z rampą = załadowana, auto w ruchu = w trasie, ptaszek = wykonana); całą szerokość plakietki dostaje nazwa.
    const IKONY_TRAS = { robocza: 'fa-pen', zatwierdzona: 'fa-lock', zaladowana: 'fa-truck-ramp-box',
        w_trasie: 'fa-truck-fast', wykonana: 'fa-check' };
    // Krok 4.4: towar załadowany na trasę, w drodze albo dostarczony — sposobu dostawy nie zmienia się (serwer odmawia
    // 409), więc select jest zablokowany, a okno przepakowania (spec 8.7) takich zamówień nie dotyczy.
    const ETAPY_PO_ZALADUNKU = ['zaladowane', 'w_trasie', 'dostarczone'];
    const poZaladunku = (w) => !!(w && w.etap && ETAPY_PO_ZALADUNKU.includes(w.etap.status));
```
blokada selecta w `wierszHtml` (po `else if (anulowane) …`):
```js
        else if (poZaladunku(w)) powod = 'Towar jest już załadowany na trasę albo dostarczony. Sposobu dostawy nie można zmienić.';
```
okno 8.7: zmiana z wiersza (:1780) `if (w.spakowane && !poZaladunku(w)) {`; `hurtSposob` (:1861) `const doDecyzji = zmieniane.filter((w) => w.spakowane && !poZaladunku(w));`; `hurtPodpowiedzi` (:1889) `const spakowane = doZmiany.filter((w) => w.spakowane && !poZaladunku(w));`. Liczba „inne” w opisie okna liczy się dalej z różnicy — zamówienia po załadunku serwer odrzuci z komunikatem, jak dziś trasę zatwierdzoną.

`logistics-map.js`:
```js
    const NAZWY_STATUSOW_TRAS = { robocza: 'Robocza', zatwierdzona: 'Zatwierdzona', zaladowana: 'Załadowana',
        w_trasie: 'W trasie', wykonana: 'Wykonana' };
```
`powodBlokadySposobu(z)` — po warunku anulowanego:
```js
        if (z.etap && ['zaladowane', 'w_trasie', 'dostarczone'].includes(z.etap.status)) {
            return 'Towar jest już załadowany na trasę albo dostarczony. Sposobu dostawy nie można zmienić.';
        }
```
legenda tras (:1850): „Brak aktywnych tras (roboczych ani zatwierdzonych).” → „Brak aktywnych tras.”

- [ ] **Step 7: Style**

`logistics-trasy.css` — w istniejącym stylu (tokeny `--lg-*`, te same promienie, odstępy i wielkości co `.lg-status--zatwierdzona`, `.lg-plakietka-trasy--zatwierdzona`, `.lg-trasa-pozycja-liczby`): `.lg-status--zaladowana`, `.lg-status--w_trasie`, `.lg-plakietka-trasy--zaladowana > .lg-plakietka-trasy-status`, `.lg-plakietka-trasy--w_trasie > .lg-plakietka-trasy-status`, `.lg-trasa-pozycja-postep`, `.lg-edytor-postep`, `.lg-przystanek-dostawa` (wiersz pod adresem, zawijanie), `.lg-przystanek-dostarczono`, `.lg-przystanek-zostaje` (ostrzegawczy, jak plakietki problemu), `.lg-przystanek-paczki`, `.lg-przystanek-cofnij`, `.lg-wykonaj-pozycja--dostarczone`. Kolory statusów rozróżnialne od zatwierdzonej i wykonanej także w trybie wysokiego kontrastu; status nie tylko kolorem (ikona + nazwa). `logistics.css`: `[data-etap="w_trasie"] .lg-etap-znak` i `[data-etap="w_trasie"] .lg-etap-nazwa` obok reguł `zaladowane`/`dostarczone`.

- [ ] **Step 8: Wersje plików statycznych**

W `tab_content.html` podbij `?v=` każdego zmienionego pliku (`logistics-routes.js`, `logistics.js`, `logistics-map.js`, `logistics-trasy.css`, `logistics.css`) na nową wartość (np. `20261001-44b`).

- [ ] **Step 9: Testy przechodzą, oględziny**

Run: `PYTEST tests/test_dostawa_panel_ui.py tests/test_logistyka_trasy_ui.py tests/test_weryfikacja_panel.py tests/test_logistyka_mapa_ui.py`
Expected: PASS.

Oględziny (jak Task 8 kroku 4.3): tymczasowy serwer z kodu tego worktree na wolnym porcie (np. 5099; zatrzymaj po oględzinach), przeglądarka WYŁĄCZNIE wbudowana (`mcp__Claude_Browser__*`), nigdy Chrome Konrada, bez haseł w poleceniach. Dane: trasy w każdym statusie (robocza, zatwierdzona w trakcie załadunku z „Zostaje”, załadowana, w drodze z jednym dostarczeniem, wykonana zamknięta telefonem). Sprawdź: sekcje listy i liczniki, plakietki i ikony statusów, postęp na liście i w nagłówku, przyciski według statusu, „Cofnij załadunek” i „Cofnij dostarczenie” (potwierdzenie, komunikat, fokus), okno „Odhacz” z przystankiem dostarczonym (zaznaczony, nieaktywny, opis), etap „W trasie” na liście Logistyki i w filtrze etapów, zablokowany select sposobu dla zamówienia załadowanego (dymek z powodem), szerokość 1280 i 1920 px, klawiatura (Tab przez nowe przyciski), tryb ciemny zakładki, jeśli zakładka go ma. Zrzuty do `C:\Users\Grafik\Documents\woodpower-podglady\logistyka4\sdd-44b\ogledziny-task7\`. W raporcie: co sprawdzone, co poprawione po oględzinach.

- [ ] **Step 10: Pełny pakiet**

Run: `PYTEST tests/`
Expected: `wynik ostatniego pełnego pakietu w głównym worktree + 4 passed, 3 skipped` (Task 6 scala się cherry-pickiem, kiedy jest gotowy — przed albo po Task 7; testy zmienione świadomie: `test_logistyka_trasy_ui.py`, `test_weryfikacja_panel.py`).

- [ ] **Step 11: Commit**

```bash
git add modules/production/logistics/static/js/logistics-routes.js modules/production/logistics/static/js/logistics.js \
  modules/production/logistics/static/js/logistics-map.js modules/production/logistics/static/css/logistics-trasy.css \
  modules/production/logistics/static/css/logistics.css modules/production/logistics/templates/logistics/tab_content.html \
  tests/test_dostawa_panel_ui.py tests/test_logistyka_trasy_ui.py tests/test_weryfikacja_panel.py
git commit -m "feat(production): panel tras - zaladowane i w trasie, postep Dostawy, cofniecia zamiast Przywroc trase" \
  -m "Krok 4.4 logistyki: sekcje Zaladowane i W trasie, akcje wedlug statusu (Cofnij zaladunek), Cofnij dostarczenie przy przystanku, postep zaladunku i dostarczen, okno Odhacz z przystankami dostarczonymi przez kierowce, etap W trasie na liscie Logistyki, blokada sposobu dostawy po zaladunku bez okna przepakowania." \
  -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: MySQL na podglądzie 5004 — wyścigi Dostawy, siatka crona na kopii produkcji, oględziny, dokumentacja

**Podział (jak Task 10 kroku 4.3 i Task 3 kroku 4.4a):** subagent robi kroki 1–7 i 9, kontroler krok 8 (oględziny z Konradem) i 10 (meldunek do centrali). Podgląd **5004** (`logistyka4-podglad`, baza `logistyka4_podglad`, katalog `C:\Users\Grafik\Documents\woodpower-podglady\logistyka4`). **5005 i 5003 — nie ruszać.** Wyniki i skrypty pomocnicze: `C:\Users\Grafik\Documents\woodpower-podglady\logistyka4\sdd-44b\` (poza repo).

**Files:**
- Create (poza repo, w `…\logistyka4\kod\`): `_dostawa_wyscigi.py` (tryby niżej; wspólne pomocniki z `_podglad_wspolne.py`, skopiowanego w kroku 4.4a)
- Create (poza repo): `…\logistyka4\sdd-44b\task-8-report.md`
- Modify: `CLAUDE.md` (sekcja „Ważne”, akapit „Trasy logistyki — jeden piszący naraz”)
- Modify: `docs/superpowers/specs/2026-09-30-logistyka-etap-4-weryfikacja-dostawa-design.md` (4.6, 9 — nowa podsekcja 9.8, 14 pkt 4, 15)

**Interfaces:**
- Consumes: cała gałąź po Task 7 (HEAD); kontrakt API Dostawy (ten plan); `_podglad_wspolne.py` (bariera dwóch wątków `wyscig`, `klient_admina`, `token`, liczniki zakleszczeń `zakleszczenia_serwera`, `log_od`, `stan`).
- Produces: raport z liczbami przebiegów, zakleszczeń, odpowiedzi 500 i niespójnych stanów; liczby SELECT-ów siatki crona przed i po; poprawione CLAUDE.md i spec.

- [ ] **Step 1: Kopia bazy i kod na podglądzie**

Kopia bazy przed zmianami: `mysqldump --single-transaction logistyka4_podglad` w kontenerze `db` (`docker ps` — kontener bazy projektu `woodpower-crm`, tak samo jak w kroku 4.4a, Task 3), plik skompresowany do `C:\Users\Grafik\Documents\woodpower-podglady\logistyka4\sdd-44b\baza-przed-44b.sql.gz`. Dane osobowe kopii i hasła nie trafiają do raportu ani do repo. Kod:
```bash
cd /c/Users/Grafik/Documents/woodpower-crm/.claude/worktrees/logistyka-etap-4
git archive HEAD | tar -xf - -C /c/Users/Grafik/Documents/woodpower-podglady/logistyka4/kod
docker restart logistyka4-podglad
```
Po starcie: `docker logs --since 2m logistyka4-podglad` — migracja `2026-10-01-logistyka-dostawa.sql` wykonana (runner przy starcie), bez błędów. `SHOW CREATE TABLE prod_routes`, `prod_route_stops`, `prod_logistics_log` do raportu.

- [ ] **Step 2: Siatka crona i reguła transportu na kopii produkcji (SELECT przed i po)**

Reguła z Task 4 zamyka transport po `dostarczone`, a siatka crona otwiera transport zamknięty po znaczniku `logistyka_weryfikacja_od` z pozycją niedostarczoną. PRZED pierwszym cronem na nowym kodzie policz (i wypisz numery zamówień):
```sql
SELECT o.id, o.internal_order_number, o.logistics_closed_at
FROM prod_orders o
WHERE o.logistics_closed_at IS NOT NULL
  AND o.override_delivery_method = '<sposoby.TRANSPORT>'
  AND o.logistics_closed_at > (SELECT STR_TO_DATE(config_value, '%Y-%m-%d %H:%i:%s') FROM prod_config
                               WHERE config_key = 'logistyka_weryfikacja_od')
  AND EXISTS (SELECT 1 FROM prod_products p WHERE p.order_id = o.id
              AND p.current_status NOT IN ('dostarczone', 'anulowane'));
```
(`<sposoby.TRANSPORT>` — wartość stałej z `modules/production/logistics/sposoby.py`; format znacznika jak w `weryfikacja.data_wdrozenia()`). Drugi SELECT: transport zamknięty z przystankiem na trasie aktywnej (`robocza`, `zatwierdzona`, `zaladowana`, `w_trasie`). Potem `docker exec -w /app logistyka4-podglad python -c "…delivery.przelicz_otwarte()…"` (albo cron przez `scripts/cron_endpoint.sh` podglądu, jeśli skonfigurowany) i te same SELECT-y po. W raporcie: liczby przed i po, lista otwartych zamówień, ocena (na produkcji przy wdrożeniu etapów 3 i 4 razem nie ma tras ani zamknięć po znaczniku, więc oczekiwane 0 — kopia może mieć dane testowe z etapu 3).

- [ ] **Step 3: Skrypt wyścigów Dostawy**

`…\logistyka4\kod\_dostawa_wyscigi.py` — tryby (każdy: przygotowanie danych, dwa wątki przez `wyscig(zad_a, zad_b)` z barierą, sprawdzenie niezmienników po przebiegu, sprzątanie). Zapytania jak w produkcji: telefon przez `/api/mobile/delivery/*` z tokenem urządzenia `delivery` i nagłówkiem `X-Worker-Ids` kierowcy (urządzenie `PODGLAD-DOSTAWA`, kierowca oznaczony `is_driver` — załóż w przygotowaniu), panel przez `klient_admina()`, stanowiska przez `/api/mobile/...` jak w `_zamowienie_najpierw_wyscigi.py`.

| Tryb | Strona A | Strona B | Oczekiwane wyniki |
|---|---|---|---|
| `dwa-telefony-skan` | skan paczki 1 (trasa zatwierdzona) | skan paczki 2 tej trasy | 200 / 200, obie załadowane |
| `skan-zakonczenie` | skan ostatniej paczki | „Zakończ załadunek” | 200 / 200 (trasa załadowana) albo 200 / 409 `loading_incomplete` |
| `zakonczenie-cofnij-weryfikacje` | „Zakończ załadunek” | Weryfikacja: `unverify` zamówienia z trasy | 200 / 409 albo 409 `loading_incomplete` (`niezweryfikowane`) / 200 |
| `zakonczenie-deklaracja` | „Zakończ załadunek” | deklaracja paczek zamówienia z trasy | 200 / 409 `order_verified` |
| `zaladunek-dorobka` | skan paczki | doróbka (`reject`) pozycji tego zamówienia | 200 / 200 (reguła czyści załadunek) albo 409 `order_not_verified` / 200 |
| `zakonczenie-zakoncz` | „Zakończ załadunek” | ZAKOŃCZ pakowania pozycji zamówienia z trasy (stan sztuczny: jedna pozycja w pakowaniu) | bez 1213; 409 `loading_incomplete` albo 200 / 200 |
| `zakonczenie-cron` | „Zakończ załadunek” | cron logistyki (`przelicz_otwarte`) | 200 / 200 |
| `dostarczenie-odhaczenie` | „Dostarczone” (trasa w drodze) | panel „Odhacz” | 200 / 200 albo 200 / 409; trasa wykonana, stany spójne |
| `dostarczenie-sync` | „Dostarczone” | zmiana z Base. (ilość, `apply_baselinker_changes`) na tym zamówieniu | 200 / sukces |
| `cofniecie-dwa` | telefon `undo-delivered` | panel `undo-delivered` tego przystanku | jedno `changed: true`, drugie bez zmian |
| `niedostarczenie-odhaczenie` | „Niedostarczone” | panel „Odhacz” | 200 / 200 albo 404 / 200; zamówienie w puli albo dostarczone, nigdy oba |
| `cofniecie-paczki-zaladunek` | Weryfikacja: `POST /verification/packages/<id>/unverify` (paczka z trasy zatwierdzonej) | skan innej paczki tego zamówienia | 200 / 409 `order_not_verified` albo 200 / 200 (skan pierwszy — potem cofnięcie czyści znaczniki); nigdy paczka załadowana przy zamówieniu niezweryfikowanym |
| `cofniecie-paczki-zakonczenie` | ten sam `unverify` | „Zakończ załadunek” | 200 / 409 `loading_incomplete` (`niezweryfikowane`) albo 409 / 200 (załadunek pierwszy — zamówienie załadowane, cofnięcie odmówione) |

Niezmienniki po każdym przebiegu: trasa `zaladowana`/`w_trasie` ⇒ wszystkie aktywne pozycje jej przystanków (niedostarczonych) `zaladowane`, aktualne paczki załadowane na tę trasę; przystanek z `delivered_at` ⇔ pozycje `dostarczone` ⇔ `logistics_closed_at` ustawione; zamówienie zdjęte z trasy (Zostaje, Niedostarczone, odznaczone) ⇒ brak znaczników załadunku i pozycje nie `zaladowane`; `bl_status_pending_id` zgodny z ostatnim przejściem (524520 / 149763 / 149778 / 417343); dokładnie jeden wpis logu na przejście.

- [ ] **Step 4: Serie**

Każdy tryb: 10 przebiegów na czystej barierze + 10 z rozjazdem 0–40 ms + 10 z rozjazdem 0–15 ms. Liczniki jak w kroku 4.3: `lock_deadlocks` InnoDB (różnica przed i po serii), wpisy logu z `1213|deadlock|1205|lock wait`, odpowiedzi 500. **STOP przy pierwszym 1213 albo niespójnym stanie**: `SHOW ENGINE INNODB STATUS`, opis cyklu w raporcie, meldunek do kontrolera — bez poprawiania kodu w tym zadaniu. Regresja kroku 4.4a: tryby `panel-zakoncz`, `dorobka-zakoncz`, `sync-zakoncz` z `_zamowienie_najpierw_wyscigi.py` po 10 przebiegów.

- [ ] **Step 5: Odtworzenie bazy i dane pod oględziny**

Odtwórz bazę z `sdd-44b\baza-przed-44b.sql.gz` do `logistyka4_podglad` w tym samym kontenerze `db` (wzór: `…\logistyka43\sdd\task-10-rerun-report.md`, pkt 5), potem skrypt `_ogledziny_44b.py`: trasy na kopii z prawdziwymi zamówieniami w każdym statusie — zatwierdzona w trakcie załadunku (część paczek, jeden przystanek „Zostaje”), załadowana, w drodze z jednym dostarczeniem i jednym „Niedostarczone”, wykonana zamknięta telefonem; kierowca `is_driver` z urządzeniem `PODGLAD-DOSTAWA`. Stan końcowy bazy do raportu (id tras, numery zamówień).

- [ ] **Step 6: Python 3.9**

```bash
cd /c/Users/Grafik/Documents/woodpower-crm/.claude/worktrees/logistyka-etap-4
docker run --rm -v "$(pwd -W)":/src -w /src python:3.9-slim python -m py_compile \
  modules/production/logistics/services/dostawa.py modules/production/logistics/services/dostawa_widok.py \
  modules/production/logistics/routers/dostawa_api.py modules/production/logistics/services/delivery.py \
  modules/production/logistics/services/routes.py modules/production/logistics/routers/trasy_api.py
```
Expected: brak błędów.

- [ ] **Step 7: CLAUDE.md i spec**

`CLAUDE.md`, akapit „Trasy logistyki — jeden piszący naraz” — dopisz na końcu:
```markdown
  **Dostawa (krok 4.4, `logistics/services/dostawa.py`)** — telefon kierowcy (`/api/mobile/delivery/*`) i przejścia
  z panelu tras (odhaczenie, „Cofnij załadunek”, „Cofnij dostarczenie”): [pracownicy, tylko telefon] → blokada tras
  → blokada deklaracji paczek → zamówienia CAŁEJ trasy rosnąco po id → paczki → pozycje; decyzje na odczycie
  bieżącym, a odpowiedź telefonu (pełna trasa) z tych samych blokad. Transport własny zamyka się po `dostarczone`
  na pozycjach (reguła nie czyta tras); siatka crona otwiera transport zamknięty po znaczniku
  `logistyka_weryfikacja_od` z pozycją niedostarczoną.
```
Spec:
- 4.6 — siatka: „transport bez trasy `wykonana`” → „transport z aktywną pozycją inną niż `dostarczone` (krok 4.4)”; po akapicie o regule transportu: „(krok 4.4) Wdrożone: reguła nie czyta tras, parametr `trasa` zniknął z `zamkniecie_wyliczone`/`przelicz_zamkniecie`.”
- nowa **9.8 „Doprecyzowania kroku 4.4 (plan 4.4b)”** — przenieś listę „Doprecyzowania i odstępstwa” z nagłówka tego planu (ścieżki z trasą, wszystkie endpointy z kierowcą, zakres „Moich tras”, cofnięcie ostatniego dostarczenia także po automatycznym zamknięciu, „Cofnij dostarczenie” w panelu bez sprawdzania zajętości, „Odhacz” z roboczej, zakończenie załadunku i jego braki, skan przy „Zostaje”, log, Routimo z wykonaną, etap „W trasie”) i dopisz: każdy zapis Dostawy blokuje zamówienia całej trasy (odpowiedź telefonu z odczytu bieżącego); trasa bez przystanków po ostatnim „Niedostarczone” zamyka się jako wykonana.
- 14 pkt 4 — dopisz: „Kolejność APK ↔ backend: nowa appka na starym backendzie ukrywa Dostawę (rejestracja `delivery` → 400 `invalid_station_code`, `/api/mobile/delivery/*` → 404), więc appka może wejść przed backendem. **Wycofanie** po zapisaniu nowych stanów: stary kod nie zna statusów tras `zaladowana`/`w_trasie` ani akcji logu Dostawy w Enum (`LookupError`), więc revert musi nieść migrację przed restartem: `UPDATE prod_routes SET status='zatwierdzona' WHERE status IN ('zaladowana','w_trasie');` i `UPDATE prod_logistics_log SET action='trasa_status' WHERE action IN ('zaladunek','zostaje','wyjazd','dostarczone','niedostarczone','dostarczenie_cofniete');` (pozycje `zaladowane`/`dostarczone` zna już kod 4.3).”
- 15 — dopisz wynik wyścigów MySQL kroku 4.4 (liczby z raportu) jednym akapitem.

- [ ] **Step 8 (kontroler): Oględziny z Konradem**

Konrad otwiera `http://127.0.0.1:5004` (nie `localhost`) i loguje się sam. Lista do przejścia: sekcje tras i liczniki, postęp, akcje według statusu, „Cofnij załadunek”, „Cofnij dostarczenie”, okno „Odhacz” z przystankiem dostarczonym przez kierowcę, etap „W trasie” i blokada sposobu na liście Logistyki, statusy Base. w kolumnie „Base. czeka”. Uwagi Konrada → poprawki (nowy brief) albo wpis do „Poza zakresem” z jego decyzją. Po oględzinach baza zostaje w stanie z kroku 5 (podgląd dla appki Dostawy).

- [ ] **Step 9: Pełny pakiet i commit**

Run: `PYTEST tests/`
Expected: bez zmian względem Task 7 (zmiany tylko w dokumentacji).

```bash
git add CLAUDE.md
git add -f docs/superpowers/specs/2026-09-30-logistyka-etap-4-weryfikacja-dostawa-design.md
git commit -m "docs: krok 4.4 logistyki - kolejnosc blokad Dostawy, odstepstwa w specu, wyniki wyscigow MySQL" \
  -m "CLAUDE.md: zapisy Dostawy (telefon i panel tras) i regula transportu po dostarczone. Spec: 4.6 siatka crona, 9.8 doprecyzowania kroku 4.4, 14 kolejnosc APK i wycofanie, 15 wyniki wyscigow." \
  -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

- [ ] **Step 10 (kontroler): Meldunek do centrali**

SendMessage do „Sesja centralna rozwoju logistyki”: commity kroku 4.4b, wynik pakietu, wyścigi (tryby, przebiegi, 0 × 1213 albo opis), liczby siatki crona z kopii, decyzje Konrada z oględzin, rzeczy odłożone, działania po stronie hali/Base./appki (telefon kierowcy zarejestrowany na `delivery`, kierowcy oznaczeni we Flocie, status 524520 w Base. jest), co wpisać do promptu 4.5 (archiwum: `dostarczone` pokazuje „Spakowane”).
