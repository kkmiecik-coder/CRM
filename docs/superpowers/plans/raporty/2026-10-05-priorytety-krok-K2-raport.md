# Raport kroku K2 „API panelu biura” — program „Priorytety produkcji”

- **Plan:** `docs/superpowers/plans/2026-10-05-priorytety-krok-K2-panel-api.md` (wszystkie kroki odhaczone `- [x]`)
- **Spec:** `docs/superpowers/specs/2026-10-04-priorytety-produkcji-design.md` (w trakcie kroku centrala wypchnęła wersję
  `d7452c47`; K2 dostosował się do niej w jednym punkcie, patrz Odstępstwa p. 1)
- **Gałąź:** `claude/priorytety-produkcji`, start `0f23bb35` (zgodny z kartą)
- **Data:** 2026-10-05. **Sesja:** lokalna, Opus 5.5 (`claude-opus-5-5`), effort high. Przegląd końcowy gałęzi: osobny
  agent Opus (świeży kontekst).

## Zrobione (po Taskach)

| Task | Commit | Co weszło |
|---|---|---|
| 1 | `9cee3951` | Blueprint `priorytety_panel` w `priorytety/__init__.py` (router importowany na końcu), rejestracja w `app.py` pod `/production/api/priorytety`, `routers/panel_api.py`: `guard` (wzór Logistyki), `_blad(kod, komunikat, status, **pola)`, `_user_id()`. Testy zestawu końcówek i 401/403 JSON. |
| 2 | `81bc6ddc` | `services/widok.py`: `szczebel_json`, `ostrzezenia_dat`, `brakujace_szczeble_tras`, `brak_szczebli`, `drabina_panelu` (liczniki z `policz` na żywo). `GET /drabina` z samonaprawą pod blokadą tras, `PUT /drabina/kolejnosc` (commit → blokada tras → odczyt bieżący → `drabina.przesun` → commit → przeliczenie; `oczekiwane`; jedno ponowienie po 1213). Wspólne `_zapis_z_ponowieniem`, `_przelicz_po_zapisie`. |
| 3 | `d294d023` | `PUT /zamowienia/gwiazdki` (commit → `gwiazdki.ustaw` = blokada zamówień rosnąco → commit → przeliczenie; bez blokady tras; 1213 raz), `POST /przelicz` (admin, `utrwal(zrodlo='panel', user_id)`, raport bez `error`). |
| 4 | `696ec313` | `widok.kolejka_zamowien`, `wejscie_kandydatow` (czysta, zero zapytań — wspólna z K3), `kolejka_stanowiska`, `priorytet_zamowienia`. `GET /kolejka` (cała kolejka na żywo albo `?stanowisko=&limit=` z kolumn, jak stół), `GET /zamowienia/<id>/priorytet`. |
| 5 | `6f784d38` | `ustawienia.py`: odczyt wiersza `prod_config` wprost (bez pamięci podręcznej procesu, `no_autoflush`), `odczyt_panelu`, `waliduj`, `zapisz`. `GET`/`PUT /ustawienia` (admin), przeliczenie tylko po zmianie progu „Blisko terminu”. |
| 6 | `8d466836` | Usunięte: `PUT /products/<id>/priority`, `POST /update-priority` (+ `_id_pozycji`, `_zapisz_priorytety`), `POST /recalculate-all-priorities`, `POST /products/<id>/set-manual-priority`, `GET /priority-statistics`, akcja `update_priority` w `bulk-action` (teraz 400), wpis w `URL_PATTERNS`, docstring `kod_mysql`. `POST /set-priority` zostaje (K4a). 10 testów przeciągania i ich pomocniki usunięte. |
| wiadomość centrali | `3763bfd7` | `PUT /ustawienia`: `stanowiska.painting.tryb = "stol"` → 400 `stanowisko_bez_stolu` (spec 10, ustalenie 15). |
| poprawki | `0dd939ca`, `6c62636e` | Cykl importów przy starcie aplikacji (znalezione w trakcie pokazu końcówek); Lakiernia bez podglądu stołu w kolejce i modalu (przegląd końcowy, Ważne 1). Szczegóły niżej. |
| 7 | (ten commit) | Raport. |

**Weryfikacja Step 0 (interfejsy K1):** wszystkie nazwy z tabeli „Consumes” są w kodzie z tą samą semantyką —
`drabina.przesun(rung_id, pozycja, user_id=None)` i `uzupelnij(user_id=None)` biorą blokadę tras same;
`gwiazdki.ustaw(...) -> {'zmienione','bez_zmian','brak'}`; `kolejka._migawka(sesja)` (dzień z `kolejka.dzis()`, próg
przez `ustawienia.prog_blisko(sesja)`); `kolejka.kandydaci_stanowiska(S, pozycje, statusy_zamowien,
szczebel_rozpoczete=None, jednostka=None)` z parami `(product_id, status)` i `brakuje` z `product_id`;
`kolejka.utrwal(zrodlo=None, user_id=None)` nigdy nie rzuca. Żadnych dopasowań plików K1 poza decyzją z karty
(`ustawienia.*` bez pamięci podręcznej).

## Testy (polecenia i wyniki)

Polecenie (karta, Start 4), z worktree: `docker compose -p priorytety run --rm --no-deps app pytest <ścieżki> -q -p no:cacheprovider`.

| Co | Wynik |
|---|---|
| Punkt wyjścia, pełny pakiet na `0f23bb35` | **6205 passed, 3 skipped**, 0 failed (6 min 42 s) |
| Pełny pakiet po Tasku 6 (`8d466836`) | **6337 passed, 3 skipped**, 0 failed (6 min 22 s) |
| Pełny pakiet końcowy (`6c62636e`) | **6341 passed, 3 skipped**, 0 failed (6 min 36 s) |
| `tests/test_priorytety_panel_api.py` (końcowo) | 144 passed |
| Task 2–6 (`task-done`) | 43 / 88 (z `test_priorytety_gwiazdki`) / 142 (z `test_priorytety_kolejka`) / 160 (z `test_priorytety_ustawienia`, `test_priorytety_terminy`) / 207 (trzy zmienione pliki, `test_priority_statusy_krawedzi`, plik panelu) passed |
| Wszystkie `tests/test_priorytety*.py` po Tasku 2 | 192 passed |

**Bilans:** 6205 + 144 (nowy plik panelu) + 2 (`test_martwe_koncowki_priorytetow_usuniete`,
`test_bulk_action_update_priority_400`) − 10 (testy przeciągania) = **6341**. `blog_seo` nie dotyczy (K2 go nie dotyka).

**Testy mutacyjne** (odwrócenie reguły → czerwony test, potem przywrócenie pliku, `cmp`): brak commitu przed blokadą tras
w `PUT /drabina/kolejnosc` → 3 czerwone; w samonaprawie → 1; brak commitu przed blokadą zamówień w gwiazdkach → 5;
klucze stołu wszystkich jednostek → 1; `rung` nie z kolumny → 1; `ustawienia.tryb` przez `config_service` → test pamięci
podręcznej czerwony; odczyt ustawień z autoflushem → 1.

**Składnia 3.9:** `python:3.9-slim` (3.9.25), `ast.parse(feature_version=(3, 9))` + `compile` dla 13 plików `.py`
zmienionych od `0f23bb35` — OK; brak `X | Y` w adnotacjach.

**Pomiar na MySQL** (baza `priorytety_podglad`, 156 zamówień aktywnych, klient testowy Flaska z sesją admina, 5 przebiegów,
mediana / max; liczba zapytań z `before_request`). Dane klientów nie były wypisywane.

| Końcówka | Mediana | Max | Zapytań | Liczności |
|---|---|---|---|---|
| `GET /drabina` | 0,029 s | 0,154 s | 20 | 14 szczebli, 1 ostrzeżenie o datach |
| `GET /kolejka` | 0,027 s | 0,031 s | 15 | 156 zamówień |
| `GET /kolejka?stanowisko=gluing` | 0,020 s | 0,035 s | 14 | 50 kafli (limit) |
| `GET /kolejka?stanowisko=formatting` | 0,017 s | 0,017 s | 13 | 19 kafli, 4 niekompletne |
| `GET /kolejka?stanowisko=packaging` | 0,021 s | 0,021 s | 14 | 50 kafli, 7 niekompletnych |
| `GET /zamowienia/<id>/priorytet` | 0,057 s | 0,061 s | 41 | zamówienie z 3 stanowiskami |
| `GET /ustawienia` | 0,019 s | 0,020 s | 36 | 7 stanowisk |

Wszystko daleko pod progiem 1 s z planu. Pomiar na `6f784d38`+ (przed poprawką Lakierni). Pusty `config/core.json`
po `docker run` skasowany.

**Pokaz końcówek** (karta 8.2) — klient testowy Flaska na danych testowych (plik tymczasowy, niezacommitowany), listy
skrócone do 2 elementów, adres jak na porcie programu 5006:

```
$ curl -X GET http://127.0.0.1:5006/production/api/priorytety/drabina
HTTP 200
{"ostrzezenia": [], "success": true, "uzupelniono": 0, "szczeble": [
 {"etykieta": "★★★★★", "gwiazdki": 5, "id": 1, "pozycja": 1, "rodzaj": "gwiazdki", "ruchomy": false, "tag": null, "trasa": null, "w_produkcji": 1},
 {"etykieta": "Trasa testowa", "gwiazdki": null, "id": 10, "pozycja": 2, "rodzaj": "trasa", "ruchomy": true, "tag": null,
  "trasa": {"date_from": "2026-10-08", "date_to": "2026-10-09", "id": 1, "nazwa": "Trasa testowa", "status": "robocza"}, "w_produkcji": 1},
 "… (10)"]}

$ curl -X PUT http://127.0.0.1:5006/production/api/priorytety/drabina/kolejnosc -H 'Content-Type: application/json' -d '{"szczebel_id": 5, "pozycja": 2}'
HTTP 200
{"ostrzezenia": [], "przeliczenie": "ok", "success": true, "uzupelniono": 0, "szczeble": [
 {"etykieta": "★★★★★", "id": 1, "pozycja": 1, …},
 {"etykieta": "Rozpoczęte", "id": 5, "pozycja": 2, "rodzaj": "tag", "ruchomy": true, "tag": "rozpoczete", "w_produkcji": 0, …}, "… (10)"]}

$ curl -X PUT http://127.0.0.1:5006/production/api/priorytety/zamowienia/gwiazdki -H 'Content-Type: application/json' -d '{"order_ids": [2, 987654], "gwiazdki": 3}'
HTTP 200
{"bez_zmian": [], "nieznane": [987654], "przeliczenie": "ok", "success": true, "zmienione": [2]}

$ curl -X POST http://127.0.0.1:5006/production/api/priorytety/przelicz
HTTP 200
{"raport": {"duration_seconds": 0.003, "ostrzezenia": [], "pozycji": 4, "success": true, "zamowien": 3,
 "zmienione_pozycje": 0, "zmienione_zamowienia": 0}, "success": true}

$ curl -X GET http://127.0.0.1:5006/production/api/priorytety/kolejka
HTTP 200
{"lacznie": 3, "success": true, "wyliczono": "2026-10-05T12:46:23", "zamowienia": [
 {"etapy": {"formatting": 1}, "gwiazdki": 5, "klient": "Klient testowy 3", "numer": "1003", "order_id": 3, "pozycji": 1, "ranga": 1,
  "szczebel": {"etykieta": "★★★★★", "id": 1, "pozycja": 1, "rodzaj": "gwiazdki"}, "tagi": [], "termin": "2026-10-25", "trasa": null},
 {"etapy": {"cutting": 1, "gluing": 1}, "gwiazdki": 2, "numer": "1001", "order_id": 1, "pozycji": 2, "ranga": 2,
  "szczebel": {"etykieta": "Trasa testowa", "id": 10, "pozycja": 3, "rodzaj": "trasa"}, "tagi": [], "termin": "2026-10-17",
  "trasa": {"date_from": "2026-10-08", "id": 1, "nazwa": "Trasa testowa"}, …}, "… (3)"]}

$ curl -X GET 'http://127.0.0.1:5006/production/api/priorytety/kolejka?stanowisko=gluing&limit=2'
HTTP 200
{"jednostka": "pozycja", "lacznie": 1, "nazwa": "Sklejanie", "niekompletne": [], "stanowisko": "gluing", "success": true, "kafle": [
 {"dorobka": false, "gwiazdki": 2, "material": {"gatunek": null, "grubosc_cm": null, "klasa": null}, "numer": "1001", "order_id": 1,
  "product_id": 2, "rozpoczete": false, "short_id": "1_2", "szczebel": {"etykieta": "Trasa testowa", "id": 10, "pozycja": 3, "rodzaj": "trasa"},
  "termin": "2026-10-17", "wymiary": {"dlugosc_cm": null, "grubosc_cm": null, "szerokosc_cm": null}}]}

$ curl -X GET http://127.0.0.1:5006/production/api/priorytety/zamowienia/1/priorytet
HTTP 200
{"aktywne": true, "gwiazdki": 2, "gwiazdki_ustawione": null, "historia": [], "ranga": 2, "success": true, "tagi": [], "termin": "2026-10-17",
 "stanowiska": [{"na_stole": [], "nazwa": "Wycinanie - mikro", "niekompletne": false, "odlozone": [], "pozycji": 1, "stanowisko": "cutting", "w_kolejce": {"miejsce": 1, "z": 1}},
                {"na_stole": [], "nazwa": "Sklejanie", "niekompletne": false, "odlozone": [], "pozycji": 1, "stanowisko": "gluing", "w_kolejce": {"miejsce": 1, "z": 1}}],
 "szczebel": {"etykieta": "Trasa testowa", "id": 10, "pozycja": 3, "rodzaj": "trasa", "ruchomy": true, "z": 10, …},
 "trasa": {"date_from": "2026-10-08", "id": 1, "nazwa": "Trasa testowa"}, "zamowienie": {"klient": "Klient testowy 1", "numer": "1001", "order_id": 1}}

$ curl -X GET http://127.0.0.1:5006/production/api/priorytety/ustawienia
HTTP 200
{"blisko_terminu_dni": 3, "deadline_day_type": "robocze", "min_app_version_code": 0, "success": true, "stanowiska": {
 "assembly": {"jednostka": "pozycja", "limit_odlozen": 10, "miejsca": 2, "nazwa": "Składanie - lite", "tryb": "stary"}, …
 "formatting": {"jednostka": "zamowienie", "limit_odlozen": 10, "miejsca": 2, "nazwa": "Formatowanie", "tryb": "stary"}, … (7 stanowisk)}}

$ curl -X PUT http://127.0.0.1:5006/production/api/priorytety/ustawienia -H 'Content-Type: application/json' -d '{"stanowiska": {"gluing": {"miejsca": 3}}, "blisko_terminu_dni": 4}'
HTTP 200
{"blisko_terminu_dni": 4, "przeliczenie": "ok", "success": true, "zmienione": ["priorytety_blisko_terminu_dni", "priorytety_stol_gluing"],
 "stanowiska": {… "gluing": {"miejsca": 3, …} …}, …}

$ curl -X PUT http://127.0.0.1:5006/production/api/priorytety/drabina/kolejnosc -H 'Content-Type: application/json' -d '{"szczebel_id": 1, "pozycja": 3}'
HTTP 400
{"error": "szczebel_staly", "message": "Szczebli gwiazdek nie można przesuwać.", "success": false}

$ curl -X PUT http://127.0.0.1:5006/production/api/priorytety/ustawienia -H 'Content-Type: application/json' -d '{"stanowiska": {"gluing": {"miejsca": 9}}}'
HTTP 400
{"error": "ustawienie_niepoprawne", "message": "Pole „stanowiska.gluing.miejsca”: podaj liczbę całkowitą od 1 do 5.", "pole": "stanowiska.gluing.miejsca", "success": false}
```

## Odstępstwa od planu

1. **Lakiernia bez stołu** (spec `d7452c47`, ustalenie 15; wiadomość centrali do K2 z 5.10): `PUT /ustawienia` odrzuca
   `stanowiska.painting.tryb = "stol"` kodem 400 `stanowisko_bez_stolu` (test
   `test_ustawienia_lakiernia_nie_przyjmuje_trybu_stol`, commit `3763bfd7`). Po przeglądzie końcowym dodatkowo
   `GET /kolejka?stanowisko=painting` → 400 `stanowisko_bez_stolu`, a modal ma dla Lakierni `w_kolejce: null`
   (`6c62636e`). Kod `stanowisko_bez_stolu` dochodzi do listy z Doprecyzowań p. 1.
2. **Liczba commitów:** 10 zamiast 7 (DoD p. 9): Taski 1–7 + Lakiernia w ustawieniach (zgoda centrali) + dwie poprawki
   (`0dd939ca`, `6c62636e`).
3. **Test K1 do przepięcia leży w `tests/test_priorytety_wyzwalacze_produkty.py`** (plan pisał
   `test_priorytety_wyzwalacze.py`; K1, Odstępstwa p. 2). Przemianowany na
   `test_hurt_statusu_utrwala_a_update_priority_odrzucone` (400, ranga bez zmian, bez przeliczenia) — dotknięcie testu K1
   wymuszone usunięciem akcji (spec 9.5).
4. **Testy przeciągania usunął K2, nie K1** (K1 zostawił je celowo, raport K1). Grep Step 4 przed usunięciem: 10 testów
   `update-priority` + pomocniki `_zamowienie_z_pozycjami`, `_przeciagnij`, `_commit_z_bledami`, `_rangi`; `_blad_mysql`
   zostaje (używają go testy `utrwal`). Docstring modułu mówi, że przeciąganie usunięto w K2.
5. **Grep kontrolny Task 6, Step 5:** jedno trafienie w `modules/` — komentarz w `priority_service.py:911` („końcówka
   `recalculate-all-priorities`”). Plan zabrania ruszać `priority_service.py` (K8), więc komentarz zostaje do K8.
   W `tests/` tylko testy nieobecności i 400. JS (`products-dragdrop.js:535`, `dashboard.html:361`,
   `products-tab-content.html:317`) zostaje dla K4a.
6. **Test LIMIT_HURTU** (Task 3) — równość `stale.LIMIT_HURTU == logistics.panel_api.LIMIT_HURTU` sprawdza już K1
   (`tests/test_priorytety_ustawienia.py:90`), nie dublowałem.
7. **Polecenia środowiska** wg karty (Start 4), nie wg planu (`docker compose exec`).
8. **Pokaz końcówek** z klienta testowego Flaska (plik tymczasowy, niezacommitowany), a pomiar czasu osobno na MySQL
   (bez wypisywania danych, bo to kopia produkcji).

## Rozstrzygnięcia podjęte w trakcie (koszt, jeśli błędne)

1. `_przelicz_po_zapisie` woła `kolejka.utrwal_po_commicie()` (karta), nie `kolejka.utrwal()` z pseudokodu; podmiany
   `kolejka.utrwal` w testach działają, bo `utrwal_po_commicie` woła globalne `utrwal`. Koszt: żaden.
2. `kolejka_stanowiska` podaje `jednostka=ustawienia.jednostka(S)` do `kandydaci_stanowiska` (K1 rozstrz. 6) — spójne
   z Doprecyzowaniem 15. Koszt: jeden argument (twardy wymóg dla K3, niżej).
3. `ustawienia.*` czyta wiersz `prod_config` wprost (decyzja karty) przez `db.session` w `no_autoflush` — inaczej każdy
   odczyt wypychałby niezapisaną pracę wołającego (np. `sync_service._calculate_deadline_date`). Testy K1 zielone, bez
   `xfail`. Koszt: ok. 31 małych zapytań na `GET /ustawienia` (0,02 s).
4. Ostrzeżenie o datach porównuje kolejne szczeble TRAS w widocznej drabinie (gwiazdki i tagi między nimi pomijane).
   Koszt: jedna linia filtra.
5. `PUT /drabina/kolejnosc` oddaje też `"uzupelniono": 0` (ten sam kształt co `GET`). Koszt: żaden.
6. `pozycja < 1` (i nie-liczba) → 400 `dane_niepoprawne`; `pozycja` > liczby widocznych → 400 `pozycja_niepoprawna`
   (wymusza to test `zle_cialo` planu; przegląd: dla klienta niespójne, opisane w kontrakcie K4a). Koszt: żaden.
7. Test nieudanego przeliczenia szuka w odpowiedzi tekstu `SEKRETNY_BLAD_SQL` zamiast litery `x`. Koszt: żaden.
8. Limit hurtu gwiazdek liczony po usunięciu duplikatów; 404 `zamowienie_nieznane` niesie pole `nieznane`. Koszt: żaden.
9. `pozycji` w wierszu `GET /kolejka` = pozycje w produkcji (suma `etapy`); w kaflu-zamówieniu = pozycje liczone do
   kompletności (bez anulowanych i wstrzymanych, jak `niekompletne` z K1). Koszt: definicja do zmiany w K4a.
10. `szczebel` kafla stanowiska = szczebel efektywny (kolumna `priority_rung`, a zamówienie rozpoczęte spoza trasy —
    „Rozpoczęte”, jeśli wyżej), krótki kształt `{id, rodzaj, etykieta, pozycja}`. Przy szczeblu wirtualnym (trasa bez
    wiersza, okno wdrożenia) etykieta kafla może być przesunięta o jeden do samonaprawy/crona (uwaga przeglądu). Koszt:
    chwilowo zła etykieta w oknie wdrożenia.
11. Szczebel wirtualny `policz` w kolejce i modalu ma `id: null` i `pozycja` z `Wynik.rung`. Koszt: żaden.
12. Modal pokazuje `na_stole`/`odlozone` tylko z wierszy stołu bieżącej jednostki (Doprecyzowanie 15) i trasę tylko
    roboczą/zatwierdzoną; odłożenie kafla-zamówienia ma `short_id: null`; `w_kolejce` na stanowisku pozycyjnym = miejsce
    PIERWSZEGO kafla zamówienia, na Pakowaniu liczone tylko wśród kafli z ustawionym sposobem dostawy (Doprecyzowanie 14).
    Koszt: odłożenie starej jednostki niewidoczne w modalu, dopóki K3 go nie zdejmie.
13. Słownik `stanowiska` w JSON ustawień ma klucze posortowane przez `jsonify` — kolejność procesu ustala UI
    (`STATION_ORDER`). Koszt: sortowanie w K4b.
14. `ustawienia.zapisz` porównuje z tekstem wiersza; brak wiersza = zmiana (INSERT, `old_value: null`), nawet przy wartości
    równej domyślnej. Pole `nazwa` i klucz blokady w `PUT` → 400 `dane_niepoprawne` z `pole`. Koszt: zbędny wpis logu na
    bazie bez seedu.
15. **Cykl importów (poprawka `0dd939ca`):** od Taska 1 `priorytety/__init__.py` importuje router, a router importował
    `common_api.admin_required` na górze. Start aplikacji (`modules.production` → modele priorytetów → pakiet → router →
    `modules.production.routers` → `apply_security` z niedokończonego `modules.production`) kończył się wpisem ERROR
    „Nie można zaimportować modeli priorytetów” przy KAŻDYM starcie, a pakiet ładował się dopiero drugim importem
    z `app.py` (tabele i trasy działały, więc testy końcówek tego nie widziały). Router woła teraz
    `common_api.admin_required` leniwie, w chwili żądania (bez kopii, format 403 bez zmian). Test
    `test_import_pakietu_produkcji_laduje_router_priorytetow_bez_cyklu` (świeży interpreter) — czerwony przed poprawką.
    Koszt: żaden.
16. **Przegląd końcowy** (agent Opus, `0f23bb35..8d466836`): 0 krytycznych, 1 ważne (Lakiernia — naprawione, Odstępstwa
    p. 1), 6 drobnych — odłożone (lista „Poza zakresem”). Z rozstrzygnięciami wykonawcy recenzent się zgodził.

## Pytania do Konrada

Blokujących — brak. Do potwierdzenia przy bramce (wartości z planu, wdrożone):
1. Zakres progu „Blisko terminu” 0–15 dni (Doprecyzowania p. 8).
2. `GET /ustawienia` tylko dla admina (spec 7.3) — biuro bez roli admin nie zobaczy ustawień stołów w panelu.

## Stan gałęzi

- `claude/priorytety-produkcji`: kod kończy się na `6c62636e`; commit z tym raportem jest HEAD-em (hash w odpowiedzi
  końcowej). Wszystko **wypchnięte** po każdym Tasku (`git pull --rebase` przed każdym pushem — po drodze weszły commity
  centrali `d752a727`, `60252789`, `d7452c47`, `4f657fc8`, same dokumenty, bez konfliktów).
- `main` nietknięty. Worktree `.claude/worktrees/priorytety-produkcji`.

## Co następny krok musi wiedzieć

**K3 (stół, sygnały, API mobilne):**
- Kafel panelu z `GET /kolejka?stanowisko=` (`widok._kafel_pozycji`/`_kafel_zamowienia`) K3 używa tylko w panelowym
  `GET /stoly`; kafel w `GET desk` to `serialize_order` + `priorytet` (spec 6.1), nie pola panelu. Wspólne jest wyłącznie
  wejście do `kolejka.kandydaci_stanowiska`: `stol.dopelnij` woła `widok.wejscie_kandydatow(S, zamowienia, pozycje,
  trasa_zamowienia, desk_unit_keys)` na listach z odczytu bieżącego (bez kopii tej funkcji), z `szczebel_rozpoczete =
  drabina.pozycja_tagu('rozpoczete')` i — **twardy wymóg** — `jednostka=ustawienia.jednostka(S)` (podgląd podaje ją tak
  samo, `widok._dane_stanowiska`; bez niej po zmianie jednostki przez admina podgląd i stół się rozjadą).
- `wejscie_kandydatow` jest czysta: wołający wczytuje `configuration` pozycji z wyprzedzeniem i nie oddaje obiektów
  wygaszonych commitem (wzór `_dane_stanowiska`: `selectinload(products).load_only(...)` +
  `selectinload(products).selectinload(configuration)`). `desk_unit_keys` = klucze BIEŻĄCEJ jednostki.
- `statusy_zamowien` to pary `(product_id, current_status)`; `kompletne_na_stanowisku(statusy, S)` przyjmuje same statusy
  — plan K3 (Interfaces Task 2, Step 0 p. 3) poprawić na pary. Wiersz stołu z kluczem innej jednostki jest nieaktualny
  (Doprecyzowanie 15): `dopelnij` nie liczy go do K, `zdejmij_nieaktualne` go zdejmuje — z testami. K2 `StationDesk`
  tylko czyta, a `PUT /ustawienia` przy zmianie jednostki niczego na stole nie zmienia.
- Lakiernia: `ustawienia.STANOWISKA_BEZ_STOLU = {'painting': 'Lakiernia'}` (jedno miejsce); `PUT /ustawienia` i
  `GET /kolejka?stanowisko=painting` już odpowiadają `stanowisko_bez_stolu`. `GET /ustawienia` dalej pokazuje dla
  Lakierni tryb/K/jednostkę/limit — ukrycie w UI (spec 7.2) i ewentualne zawężenie odpowiedzi to K3 Task 5a/K4b.
- Nowe końcówki panelu ze specu 5.7–5.8 (`POST /stoly/<S>/wyslij`, `POST /stoly/<S>/zdejmij`, `GET /start`,
  `POST /start/przygotuj`): najłatwiej dopiąć w `priorytety/routers/panel_api.py` jako nową sekcję po „kolejka i modal”
  (przed „ustawienia”), z `@guard` (+ `@admin_required` tam, gdzie spec każe) i istniejącymi pomocnikami:
  `_blad`, `_Odmowa` (odmowa pod blokadą → rollback i kod), `_zapis_z_ponowieniem` (commit → blokady → zapis → commit,
  jedno ponowienie po 1213, 500 bez treści), `_przelicz_po_zapisie`. Każdą nową końcówkę dopisać do `KONCOWKI`
  w `tests/test_priorytety_panel_api.py` i podbić `len(KONCOWKI) == 8` w `test_zestaw_koncowek` (testy 401/403 obejmą
  ją same).
- **Importy w routerze panelu:** nic z `modules.production.routers.*` na górze modułu (cykl, rozstrz. 15) — tylko
  leniwie, wzorem `admin_required` w `panel_api.py`.

**K4a (Lista produkcyjna, modale):**
- Kontrakty: `GET /drabina` (`szczeble[]`: `id, rodzaj (gwiazdki|tag|trasa), gwiazdki, tag, trasa{id,nazwa,status,
  date_from,date_to}|null, pozycja, etykieta, ruchomy, w_produkcji`; `ostrzezenia[]` z `kod` ∈ `daty_tras`
  (`route_ids`, `message`), `samonaprawa_nieudana`; `uzupelniono`). `PUT /drabina/kolejnosc` `{szczebel_id, pozycja,
  oczekiwane?}` — `pozycja` = indeks w WIDOCZNEJ drabinie z `GET /drabina`, `oczekiwane` = id widocznych szczebli
  w kolejności, którą widział użytkownik (409 `drabina_zmieniona` → odśwież). `PUT /zamowienia/gwiazdki`
  `{order_ids, gwiazdki}` → `{zmienione, bez_zmian, nieznane, przeliczenie}`. `GET /kolejka`, `GET /kolejka?stanowisko=`,
  `GET /zamowienia/<id>/priorytet` — kształty w pokazie wyżej i w docstringach `widok.py`.
- `przeliczenie` ∈ `ok | nieudane | niepotrzebne` — `nieudane` to nie błąd zapisu (zapis jest), tylko informacja, że
  rangi nadrobi cron.
- Kody błędów: `dane_niepoprawne`, `gwiazdki_niepoprawne`, `za_duzo_zamowien` (+`limit`), `zamowienie_nieznane`
  (+`nieznane`), `szczebel_nieznany` 404, `szczebel_staly`, `trasa_nieaktywna` 409, `pozycja_niepoprawna`,
  `drabina_zmieniona` 409, `stanowisko_nieznane`, `stanowisko_bez_stolu`, `ustawienie_niepoprawne` (+`pole`),
  `przeliczenie_nieudane` 500, `blad_serwera` 500. Wyjątki formatu: `guard` → `{"error": "unauthorized"}` 401 /
  `{"error": "module_access_denied"}` 403; `admin_required` → `{"success": false, "error": "Brak uprawnień
  administratora"}` 403.
- Do usunięcia w JS: `products-dragdrop.js` (+ `<script>` w `dashboard.html:361`), formularz `bulk-priority-form`
  (`products-tab-content.html:316-330`), wywołanie `set-priority` (`products-module.js:2383`) razem z końcówką
  `POST /production/api/set-priority` (`products_api.py`).

**K4b (Konfiguracja, Stanowiska, dashboard):**
- `GET`/`PUT /ustawienia` to jedyna droga zapisu kluczy priorytetów i `DEADLINE_DAY_TYPE` (allowlista `update-configs`
  w `config_api.py` ich nie dostaje). Format 403 z `admin_required` jak wyżej. `PUT` przyjmuje dowolny podzbiór
  kształtu `GET` (bez `nazwa`), waliduje całość, odpowiada stanem + `zmienione` + `przeliczenie`.
- „Pierwsze 15 kafli kolejki” w zakładce Stanowiska: `GET /kolejka?stanowisko=S&limit=15` — dla Lakierni 400
  `stanowisko_bez_stolu`; jej lista wg spec 3.2 (porządek po wykończeniu) to osobna funkcja, gdy powstanie (K3 Task 5a).
- `widok.drabina_panelu()` (liczniki bez samonaprawy i bez blokad) nadaje się na dashboard.

**K5 (wyścigi, CLAUDE.md, spec):**
- `CLAUDE.md` („Zamówienie najpierw”, akapit pisarzy pozycji) opisuje jeszcze „przeciąganie `update-priority`”
  i „hurtową i ręczną zmianę priorytetu” — po K2 tych pisarzy nie ma; poprawić razem z sekcją „Priorytety produkcji”.
- Doprecyzowania 1–15 planu K2 do specu (plus kod `stanowisko_bez_stolu` w liście kodów panelu) i decyzja: `ustawienia.*`
  bez pamięci podręcznej procesu (K2, rozstrz. 3).
- Wyścigi MySQL: gwiazdki ↔ ZAKOŃCZ, przesunięcie szczebla ↔ przystanek (spec 13); dwa równoległe `PUT /ustawienia`
  z brakującym kluczem (UNIQUE → 500, drobne 5 przeglądu).

## Poza zakresem (zauważone, nie ruszane)

- Drobne z przeglądu końcowego (odłożone, bez zmian w kodzie):
  - `widok._widoczne_z_trasami`: wczytanie tras z wyprzedzeniem nie trzyma obiektów (słaba mapa tożsamości), więc
    `rung.route` robi SELECT na każdy szczebel trasy; komentarz „bez SELECT-a” jest nieprawdziwy (kilka zapytań).
  - Modal woła `_dane_stanowiska` na każde stanowisko zamówienia i dociąga konfiguracje własnego zamówienia leniwie —
    zmierzone 0,057 s / 41 zapytań.
  - `PUT /zamowienia/gwiazdki`: odczyt istnienia zamówień stoi przed `try` — błąd bazy trafi do globalnego
    `errorhandler` (bez treści wyjątku, ale w innym formacie niż `{success, error, message}`).
  - `ustawienia.zapisz` bez blokady (wyścig dwóch adminów, K5).
  - `products_api.py` (`bulk_action`, komentarz przy logu): „Hurtowa zmiana priorytetu i usuwanie nie przeliczają” —
    nieaktualny.
- `priority_service.py:911` — komentarz o końcówce `recalculate-all-priorities` (K8).
- `tests/test_priorytety_ustawienia.py:173` i `tests/priorytety_fixtures.py` (`czyste_ustawienia`) — komentarze
  o pamięci podręcznej `config_service` przy ustawieniach priorytetów są już nieaktualne (testy K1, nieruszane).
- Rejestracja blueprintów produkcji w `create_app` daje ostrzeżenia Flaska „name … is already registered”
  (`production_stations`, `production_api`, `production_admin`) — sprzed K2.
