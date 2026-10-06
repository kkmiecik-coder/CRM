# Runbook K7 — wdrożenie czwartek 8.10.2026, przerwa 10:30 (wersja v2)

Logistyka etapy 1–4 + 4.6, priorytety produkcji, appka 1.8.0 / vc 44 — jedno okno. Prowadzi centrala z Konradem;
**zapisy na serwerze i push wykonuje Konrad**, centrala czyta, sprawdza i podaje następny krok. Źródło: raport próby
wdrożenia (`d4078bb1`, runbook A–F), raport poprawki zaznaczeń (hashe v2), przekazanie logistyki (poza repo, na komputerze z Windows: `woodpower-podglady/priorytety/przekazanie-logistyki-2026-10-05.md`).
Oznaczenia: **[S]** serwer (ssh na serwer produkcyjny jako root (dostęp jak zwykle — nie w repo), katalog `/home/woodpower-crm/htdocs/crm.woodpower.pl`, MySQL `mysql -uroot crm`),
**[P]** panel CRM, **[T]** tablety, **[L]** lokalnie (repo, ten komputer).

## Hashe (v2 — obowiązują)
| | Gałąź | Commit |
|---|---|---|
| produkcja dziś | `main` | `31a0b0145b222799234674bdf1e995dab6791a0c` |
| **wdrożenie** | `claude/wdrozenie-2026-10-08-v2` | `9bd6fc510fb9a7efb617bafeba4e492f49668784` |
| **wycofanie** | `claude/wycofanie-2026-10-08-v2` | `e295421a123d4c86df89e0a0d2ec086f93b9ced4` |
Stare `5e944a55` / `8e14937e` — NIE używać (bez poprawki zaznaczeń).

## 0. Zrobione wcześniej
- [x] Klucz ORS w `core.json` produkcji (6.10, zapis + restart). Kopia `/root/core.json.przed-ors` — usunąć po czwartku.
- [x] APK 1.8.0 (release, vc 44) wgrany w CRM jako **nieaktywny**.
- [x] Próba wdrożenia na kopii produkcji (2 przebiegi), pełny przebieg E2E z tabletem — bez blokad.

## A. Przed oknem (środa / czwartek rano, przed zmianą)
1. **[Konrad] Zadania logistyki** (przekazanie logistyki): klucz CARTO ograniczony do crm.woodpower.pl; status Base. 524520 istnieje;
   drukarka paczek XP-410B na hali (adres w sieci hali, AP/PIN, uchwyt rolki; kalibracja z E2E: X=0/Y=0, marginesy
   L 3,5 / P 1,5 / G 5 / D 3,5 mm) + sekcja `[printer:wysylka]` w `config.ini` agenta + konfiguracja agenta druku na hali (szczegóły w przekazaniu logistyki, poza repo);
   weryfikator w pracownikach, kierowcy (`is_driver`) i pojazdy we Flocie.
2. **[T] Tablet Wycinania włączony** (6.10 żaden tablet Wycinania nie łączył się przez 24 h).
3. **[P] Aktywacja APK 1.8.0** w CRM (czwartek rano, przed zmianą) → tablety aktualizują się same i pracują na starym
   backendzie jak dziś (lista). Release ma `https` w `sse_url` — na produkcji jest `https://crm.woodpower.pl/realtime/connection/uni_sse`.
4. **[L] Stan:** `git fetch origin && git rev-parse origin/main` → `31a0b014…`; **[S]** `git rev-parse HEAD` → to samo.
   Inaczej **STOP** (centrala robi nowy squash).
5. **[S] Nie wołać żadnego `flask …`** na serwerze przed pushem (migruje przy `create_app()`).
6. **[S] Broker:** `supervisorctl status centrifugo` → RUNNING; namespace `station` w `/etc/centrifugo/config.json`; `REALTIME.enabled = true`.
7. **[S] Crontab:** wpis crona logistyki już jest (co godzinę o :00) — nic nie zmieniać; pierwszy automat o 11:00.
   Nie włączać `sync-cron`.
8. **[S] Heartbeat tabletów** (tylko widziane w 24 h) — po aktywacji APK:
   ```sql
   SELECT station_code, COUNT(*) tablety, SUM(last_app_version_code >= 44) vc44,
          GROUP_CONCAT(CONCAT(device_name, ':', last_app_version_code)) szczegoly
   FROM prod_devices WHERE is_active = 1 AND last_seen_at >= NOW() - INTERVAL 1 DAY GROUP BY station_code;
   ```
   Oczekiwane przed „Włącz stoły”: `tablety = vc44` na każdym stanowisku.
9. **[Hala] przed przerwą:** „wbijcie licznik na tym, co macie w rękach” (kafel startowy = licznik > 0).
   **[Logistyk/weryfikator] ustnie:** pilne przepakowanie po „Cofnij do pakowania” → „Wyślij na stanowisko”.
   **[Biuro] ustnie:** dopóki leżą kafle startowe, doróbki posyłać „Wyślij na stanowisko”; hurtowa zmiana statusu
   nie wysyła statusu do Base. (ustawić ręcznie).

## Harmonogram przerwy (10:30–11:00, 30 min — Konrad 6.10)
| Godz. | Krok |
|---|---|
| 10:20–10:25 | hala: „wbijcie licznik na tym, co macie w rękach”; [S] heartbeat (A8), stan `main` (A4) |
| 10:30 | B1 kopia priorytetów → B2 push `9bd6fc51` |
| ~10:31 | B3 `Deploy complete!` (restart ~6 s) |
| 10:32–10:40 | B4 ręczny cron, B5 kontrole SQL, B6 panel, B7 tablety na liście |
| 10:40–10:48 | C: podgląd startu → „Przygotuj stoły” → poprawki → „Włącz stoły” (44) → „Rozpoczęte” na szczyt |
| 10:48–10:55 | C6: tablety na stole, przegląd stanowisk |
| do 11:00 | bufor; przy problemie w B → wycofanie (F) zanim hala wróci; problem tylko w C → stoły na „zgodność”, hala pracuje na liście |
| 11:00 | pierwszy automatyczny cron logistyki |

## B. Wdrożenie (10:30)
1. **[S] Kopia ręcznych priorytetów** (0,4 s):
   ```sql
   CREATE TABLE IF NOT EXISTS zz_przed_wdrozeniem_2026_10_08_priorytety AS
   SELECT id, priority_rank, priority_manual_override, is_priority FROM prod_products
   WHERE current_status NOT IN ('spakowane', 'anulowane');
   SELECT COUNT(*) FROM zz_przed_wdrozeniem_2026_10_08_priorytety;
   ```
2. **[L] Push:** `git fetch origin && git rev-parse origin/main` (= `31a0b014…`), potem
   **`git push origin 9bd6fc510fb9a7efb617bafeba4e492f49668784:main`**.
3. **[S]** `tail -f logs/deploy.log` do `Deploy complete!` (~30 s; migracje pod „Syncing changelog…”: 17 × „✓ Sukces”,
   ~2,5 s; restart ~6 s niedostępności — tablety kolejkują). `[MIGRATION FAILED]` → deploy sam cofa kod; nie restartować.
4. **[S] Ręczny cron:** `scripts/cron_endpoint.sh POST /production/api/logistics/cron` → 200 < 1 s,
   `priorytety_utrwalone.success: true`, `zamowien` ≈ aktywne zamówienia, `szczeble_uzupelnione: 0`; drugi raz → 0 zmian.
   Znacznik `logistyka_wydane_dostarczone` ma czas PO restarcie (inaczej usunąć wiersz i powtórzyć cron).
5. **[S] Kontrole SQL priorytetów** (wszystkie zgodne w próbie):
   ```sql
   SELECT config_key, config_value FROM prod_config WHERE config_key LIKE 'DEADLINE%';      -- robocze / 10 / 14
   SELECT kind, stars, tag, position FROM prod_priority_rungs ORDER BY position;            -- 9 szczebli
   SELECT SUM(config_key LIKE 'priorytety\_%'), SUM(config_key = 'DEADLINE_DAY_TYPE') FROM prod_config;  -- 37, 1
   SELECT COUNT(*), COUNT(DISTINCT priority_rank), SUM(priority_rank IS NULL) FROM prod_orders o
    WHERE EXISTS (SELECT 1 FROM prod_products p WHERE p.order_id = o.id AND p.current_status NOT IN ('spakowane','anulowane'));  -- N, N, 0
   SELECT config_key, config_value FROM prod_config WHERE config_key LIKE 'priorytety\_tryb\_%' OR config_key = 'priorytety_min_app_version_code';  -- 7 × stary, 0
   SELECT COUNT(*) FROM prod_station_desk;                                                   -- 0
   SELECT COUNT(*) FROM schema_migrations WHERE success = 1 AND version >= '2026-09-25';    -- 17
   ```
   **Kontrole logistyki** (plan logistyki C4): wiersze `prod_config` `logistyka_trasy_blokada`, `logistyka_paczki_blokada`,
   `logistyka_weryfikacja_od`; `SHOW COLUMNS FROM prod_route_stops LIKE 'not_delivered%'` → 4; indeks
   `ix_prod_logistics_log_route_id`; `SELECT COUNT(*) FROM sales_orders WHERE current_status='Status 417343'` = 0 i to samo
   w `baselinker_reports_orders` (> 0 → powtórzyć idempotentny UPDATE z migracji).
6. **[P] Panel:** Lista produkcyjna (#1…), Drabina, Konfiguracja → Terminy (10 / 14 / robocze), Stół stanowisk
   (6 × „zgodność”, Lakiernia „lista”, próg 0), zakładka Stanowiska, monitor hali, Logistyka (zamówienia „Nie ustawiono”).
7. **[T]** tablety dalej na liście (`tryb: "stary"`), zaległe akcje dochodzą w ~40 s.

## C. Start stołów (w tej samej przerwie, ok. 10:40)
1. **[S]** heartbeat (A8) — każdy używany tablet vc ≥ 44.
2. **[P] Konfiguracja → Start stołów → podgląd** (liczby per stanowisko; 6.10 rano: Sklejanie 11, Formatowanie 8, Pakowanie 1).
3. **[P] „Przygotuj stoły”** → poprawki „Wyślij” / „Zdejmij”.
4. **[P] „Włącz stoły”** z minimalną wersją **44** (przy 0 serwer odmawia).
5. **[P] Drabina:** „Rozpoczęte” na szczyt.
6. **[T]** tablety na stole same w ≤ 30 s (próba 4–19 s), kafle startowe z plakietką.
7. **[P]** po zejściu kafli startowych „Rozpoczęte” z powrotem pod ★★★★.

## D. Po wdrożeniu (logistyk, biuro)
- Logistyk **przed pierwszym planowaniem tras:** M2 wariant (a) — z „także zamknięte” zamówienia własnym transportem →
  „Transport WoodPower”; sposoby dla czekających (~75). Rejestracja telefonów Weryfikacji (Biuro) i Dostawy.
- Drukarka paczek: Konfiguracja → Drukarka → „Wydruk próbny”, przesunięcie.
- Testy dymne logistyki (plan logistyki C8): Trasy, mapa z przebiegiem (ORS), Archiwum, Pakowanie z etykietą 100×150,
  Weryfikacja, Dostawa „Moje trasy”, `logs/` bez `Traceback`.
- Obserwacja: cron co godzinę (`priorytety_utrwalone`), wpisy 1205/1213 w logu, czasy `desk`/ZAKOŃCZ, statusy Base.
  („Wyczerpano retry”).

## E. Objawy i reakcje
- ZAKOŃCZ ~1,5 s → broker zawieszony: `supervisorctl restart centrifugo` albo `REALTIME.enabled=false` + **natychmiastowy restart aplikacji**.
- 409 „Pozycja … nie czeka na …” → kafel zamknięty gdzie indziej; appka odświeża sama.
- Widma w zakładce Stanowiska → „Zdejmij”.
- Wycofanie jednego stanowiska: Stół stanowisk → „zgodność”; tablet wraca na listę ≤ 30 s (pełny stół do 5 min — wyjść i wejść na ekran).

## F. Wycofanie całości
**Przed:** logistyk zdejmuje „Niedostarczone” (`prod_route_stops.not_delivered_at` → 0); ręczny cron + `bl_*_pending` → 0;
spisać `repack_required`/`problem_at`; **sposób dostawy dla zamówień w pakowaniu bez sposobu** (→ 0).
**Wykonanie:** `git rev-parse origin/main` = `9bd6fc51…` (inaczej STOP), **`git push origin e295421a123d4c86df89e0a0d2ec086f93b9ced4:main`**;
po `Deploy complete!` **[S]** `mysql -uroot crm < migrations/2026-10-08-wycofanie-logistyki.sql`; kontrole C7 z raportu
próby (wszystkie 0); `UPDATE prod_config SET config_value='stary' WHERE config_key LIKE 'priorytety\_tryb\_%';`
**Nie wołać** `recalculate-all-priorities`. Telefony Weryfikacji/Dostawy — nie używać.
**Ponowne wdrożenie później:** przed pushem `DELETE FROM prod_station_desk;` (widma), tryby `stary`; nowa gałąź od bieżącego `main`.

## G. Sprzątanie po wdrożeniu
`/root/core.json.przed-ors`; tabela `zz_przed_wdrozeniem_2026_10_08_priorytety` (po kilku dniach); podglądy i bazy
(5003–5007, `priorytety-k5`, stack `priorytety-proba`, bazy `logistyka*`, `priorytety_*`, `logistyka46_wyscigi`);
gałęzie `claude/logistyka-etap-*` (decyzja o usunięciu z origin — historia z danymi zamówienia); `woodpower-podglady/priorytety/{proba,e2e,k5}`.
Pierwszy commit po wdrożeniu na `main`: CLAUDE.md (Python 3.12.3) + karty po wdrożeniu (lista w dzienniku centrali).
