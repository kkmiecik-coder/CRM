# Logistyka — etap 3, runda poprawek 4.1 (28.09.2026) — plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Zadania wykonuj po kolei,
> przegląd po każdym.

**Cel:** zamknąć dwa punkty z sekcji 4.1 dokumentu przekazania
(`docs/superpowers/plans/2026-09-26-logistyka-etap-3-przekazanie.md`): (1) zamówienie anulowane w całości, zdjęte
z trasy, wraca do puli „Transport bez trasy” zamiast się zamknąć; (2) hurtowe „Dodaj do trasy…”, dokończone w tle po
zamknięciu okna, czyści BIEŻĄCE zaznaczenie listy i przenosi fokus.

**Spec:** `docs/superpowers/specs/2026-09-24-logistyka-rownolegla-trasy-design.md` — sekcja 6.2 (cykl życia) i 8.2
(trasy). Gałąź `claude/logistyka-etap-3-trasy` (zawiera etapy 1–3), worktree
`C:\Users\Grafik\Documents\woodpower-crm\.claude\worktrees\logistyka-etap-3-trasy`.

## Global Constraints

- Komentarze w kodzie **po polsku**; w UI „Base.” zamiast „BaseLinker”.
- Commity: Conventional Commits po polsku, scope `production`, stopka
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`; commit z jawną listą ścieżek (`git commit -- <pliki>`).
- Nie commitujemy `docs/superpowers/**`, `config/core.json`, `CLAUDE.local.md`, `MIGRATION_PLAN.md`.
- Spec 6.2: `logistics_closed_at` jest **wyliczany** przez jedną funkcję `delivery.przelicz_zamkniecie(order)`,
  wołaną po każdej zmianie, która może go dotyczyć. Tabela: „wszystkie produkty anulowane → zamknięte”;
  „transport własny, przystanek na trasie `wykonana` → zamknięte”; pozostałe → otwarte.
- Blokady tras (rozstrzygnięcia 16 i 22 przekazania): każdy piszący trasę bierze najpierw `routes.zablokuj_trasy()`,
  a stan trasy czyta ze świeżej `route.stops` spod blokady — nie dokładamy zwykłych odczytów trasy/przystanków,
  które mogłyby czytać migawkę sprzed blokady.
- Każda zmiana widoczna na tablecie podbija `updated_at` pozycji zamówienia (`delivery.podbij_pozycje`).
- Pliki statyczne: przy każdej zmianie pliku JS podbij jego parametr `?v=` w
  `modules/production/logistics/templates/logistics/tab_content.html`.
- Testy UI to testy tekstu źródła (brak runnera JS) — `tests/test_logistyka_trasy_ui.py` (pomocnik `_funkcja`).
  Testy UI etapów 2–3 muszą zostać zielone.
- Testy z katalogu worktree: `docker compose -p logistyka3 run --rm --no-deps app pytest <ścieżki> -q -p no:cacheprovider`;
  pełny pakiet raz przed commitem (punkt wyjścia: `4695 passed, 3 skipped`). NIE `docker compose exec` (testuje główny
  checkout), NIE twórz `config/core.json` w worktree.

### Task 1: Zdjęcie przystanku przelicza zamknięcie zamówienia

**Problem (sekcja 4.1 przekazania, rozstrzygnięcie 40):** `routes.usun_przystanek`
(`modules/production/logistics/services/routes.py`) zdejmuje przystanek, renumeruje, loguje `trasa_usuniete` i podbija
pozycje, ale **nie woła** `delivery.przelicz_zamkniecie`. Zamówienie anulowane w całości (wszystkie produkty
`anulowane`), którego `logistics_closed_at` zostało puste, bo anulowanie ominęło przeliczenie (SQL, wyścig, ścieżka bez
przeliczenia), po zdjęciu z trasy wraca do puli „Transport bez trasy” / „Do dodania” i wisi tam do crona
`przelicz_otwarte` (≤ 1 h). Najczęstsza droga: okno „Odhacz jako wykonaną” wysyła anulowane jako niedostarczone
(pole anulowanego jest nieaktywne, opis „zdejmiemy z trasy”), więc `routes.wykonaj` zdejmuje je przez
`usun_przystanek(..., note='niedostarczone', wymagaj_roboczej=False)`. Ten sam brak dotyczy pozostałych wołających
`usun_przystanek`: ręcznego zdjęcia (`DELETE /production/api/logistics/routes/<id>/stops/<order_id>`), usunięcia trasy
(`routes.usun`) i zmiany sposobu dostawy (`delivery._zdejmij_z_trasy`).

**Zmiana:** przyczynę naprawiamy w `usun_przystanek` (jedno miejsce dla wszystkich wołających, zgodnie ze spec 6.2), nie
tylko w pętli `wykonaj`:
- po zdjęciu przystanku (po logu i podbiciu pozycji) `delivery.przelicz_zamkniecie(order, teraz, trasa=route)`.
  `trasa=route` — świeża trasa spod blokady, z której zamówienie właśnie zeszło (UNIQUE `order_id`: nie ma go na tej, to
  nie ma go na żadnej); dzięki temu przeliczenie nie robi zwykłego odczytu przystanku z migawki
  (`routes.przystanek_zamowienia`). Dla transportu własnego z aktywnymi pozycjami wynik = otwarte (jak dotąd), dla
  anulowanego w całości = zamknięte.
- zaktualizuj docstringi `delivery.zamkniecie_wyliczone` i `delivery.przelicz_zamkniecie`, które mówią, że `trasa`
  podają tylko `routes.wykonaj/przywroc` — teraz także `routes.usun_przystanek`.
- `wykonaj` bez zmian w kształcie odpowiedzi (`{'dostarczone', 'niedostarczone'}`), log i notatka „niedostarczone”
  bez zmian (osobny, odłożony drobiazg 4.3 — nie ruszamy).
- sprawdź, że `delivery.ustaw_sposob_dostawy` (dwie ścieżki: główna i cofnięcie do „Nie ustawiono”) daje ten sam
  końcowy wynik zamknięcia co dotąd — tam `przelicz_zamkniecie` i tak jest wołane na końcu.

**Testy (TDD — najpierw czerwone), w `tests/test_logistyka_trasy_serwis.py` i/lub `tests/test_logistyka_trasy_api.py`:**
1. Odhaczenie: trasa z zamówieniem A (transport, spakowane) i C (transport), C anulowane w całości PO dodaniu do trasy
   bez przeliczenia (`p.current_status = 'anulowane'` wprost + commit, `logistics_closed_at` zostaje puste — wzór:
   `test_odhaczenie_pomija_anulowane_w_regule_spakowania`); `routes.wykonaj(t, [A])` → odpowiedź
   `{'dostarczone': [A], 'niedostarczone': [C]}`, C nie ma przystanku, **`C.logistics_closed_at` ustawione**, A zamknięte.
2. Ręczne zdjęcie przez API (`DELETE .../routes/<id>/stops/<C>`) takiego anulowanego zamówienia → zamknięte; oraz
   zamówienie nie trafia do puli kandydatów trasy (ten sam endpoint, którego używa lista „Do dodania” w edytorze).
3. Usunięcie trasy roboczej (`routes.usun`) z przystankiem anulowanym i aktywnym → anulowane zamknięte, aktywne otwarte.
4. Regresja: `test_niedostarczony_wraca_do_puli` i `test_usuniecie_roboczej` bez zmian i zielone (aktywne
   niedostarczone zostaje otwarte, podbite `updated_at`).

### Task 2: Hurtowe „Dodaj do trasy…” dokończone w tle nie rusza bieżącego zaznaczenia ani fokusu

**Problem (sekcja 4.1 przekazania, rozstrzygnięcie 39):** okno „Dodaj do trasy…” (`logistics-routes.js`,
`dodajDoTrasy` → `zapiszDodawanie`) zamknięte w trakcie zapisu (drugi Esc przeglądarki) nie gubi wyniku: zapis kończy
się w tle (`poZamknieciuOknaDodawania` → `dodawaniaWTle`, potem `zakonczDodawanieWTle(d)` rozstrzyga obietnicę tym
samym wynikiem co przy otwartym oknie). W `logistics.js` `hurtTrasa` (ok. `:1387–1395`) na każdy wynik z dodanymi
zamówieniami woła **`odznaczWszystko()`** i **`fokusPoDodaniuDoTrasy()`**. Przy zapisie dokończonym w tle logistyk mógł
już zaznaczyć inne zamówienia albo pracować w innym polu — tracił nowe zaznaczenie, a fokus (i przewinięcie listy)
skakał na plakietkę trasy.

**Zmiana:**
- `logistics-routes.js`: `zakonczDodawanieWTle(d)` oddaje wynik oznaczony jako dokończony w tle (np. pole `wTle: true`
  w kopii `d.wynik`; `null` zostaje `null`). Zaktualizuj opis publicznego `dodajDoTrasy` (co daje obietnica).
  Ścieżka z otwartym oknem (`zamknijOknoDodawania`) bez zmian.
- `logistics.js`, wywołanie zwrotne w `hurtTrasa`:
  - wynik z otwartego okna (bez znacznika) — **bez zmian** (`odznaczWszystko()` + `fokusPoDodaniuDoTrasy`, oględziny
    Task 8 I3);
  - wynik dokończony w tle — z zaznaczenia schodzą **tylko** dodane zamówienia (te z `wynik.dodane`, które wciąż są
    zaznaczone; `stan.ostatniKlik` zerowany tylko, gdy wskazywał jedno z nich), reszta zaznaczenia zostaje;
    `renderujZaznaczenie()`. Fokus przenosimy (`fokusPoDodaniuDoTrasy`) **tylko wtedy**, gdy przed odznaczeniem był
    w pasku hurtu (`el('hurt')`), a pasek po odznaczeniu zniknął (fokus zginąłby razem z nim); w każdym innym
    przypadku fokusu nie ruszamy.
- Podbij `?v=` obu plików w `tab_content.html` (`logistics.js`, `logistics-routes.js`) na `20260928a`.
- Wiersze listy nadal podmieniane odpowiedzią (`podmienWiersze`) w obu ścieżkach; komunikaty bez zmian.

**Testy (tekst źródła, `tests/test_logistyka_trasy_ui.py`, wzór: test z `dodawaniaWTle` ok. `:339`):** znacznik
w `zakonczDodawanieWTle`, rozgałęzienie w `hurtTrasa` (ścieżka w tle nie woła `odznaczWszystko`, odznacza tylko
`wynik.dodane`, fokus warunkowo po sprawdzeniu paska hurtu), podbite `?v=`. Zachowanie w przeglądarce sprawdza
kontroler oględzinami na podglądzie (implementer NIE uruchamia przeglądarki).
