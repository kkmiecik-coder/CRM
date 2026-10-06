# Raport kroku K3 „Stół, Odłóż, bramka ZAKOŃCZ, sygnały (+ „Wyślij”, start stołów, poprawka K1)” — program „Priorytety produkcji”

- **Plan:** `docs/superpowers/plans/2026-10-05-priorytety-krok-K3-stol-odloz-sygnaly.md` — rozszerzony o Task 0 i Taski
  dopisane z karty (sekcja „Zakres dopisany z karty K3”: Task 0, 0a, dopisek w Tasku 2, 5b, 5c); wszystkie kroki `- [x]`.
- **Spec:** `docs/superpowers/specs/2026-10-04-priorytety-produkcji-design.md` (wiążący; tam, gdzie plan i spec się różnią,
  wygrał spec — patrz Odstępstwa).
- **Gałąź:** `claude/priorytety-produkcji`, start `dcd28e0a` (zgodny z kartą). `main` i główny checkout nietknięte.
- **Data:** 2026-10-05. **Sesja:** lokalna, effort extra, bez trybu szybkiego. **Model:** środowisko na starcie przedstawiło
  sesję jako Opus 5.5, po pierwszym poleceniu poprawiło na **Fable 5.1 (`claude-fable-5-1`)** — czyli model z karty; cała
  praca poszła na Fable 5.1. Przegląd końcowy gałęzi: osobny agent Fable 5.1 w świeżym kontekście.

## Zrobione (po Taskach)

| Task | Commit | Co weszło |
|---|---|---|
| plan | `badc7326` | Plan K3 uzupełniony o Taski z karty (0, 0a, 5b, 5c, dopisek „źródło kafla” w Tasku 2) — przed pierwszą linią kodu. |
| 0 | `6fb9f094` | **K1-poprawka-1** — `kolejka.utrwal` na własnym, przypiętym połączeniu z limitem czekania na blokadę 5 s; 1205 → `success: False` bez ponowienia. Osobna sekcja niżej. |
| 0a | `abf3cfd4` | Migracja `migrations/2026-10-06-priorytety-stol-zrodlo.sql`: `prod_station_desk.zrodlo VARCHAR(16) NOT NULL DEFAULT 'kolejka'`, `sent_by_user_id INT NULL` (osłonięte `information_schema` + `PREPARE`), `prod_priority_log.action` + `wyslanie`, `zdjecie`, `start_stolow`. Model `StationDesk`, stałe `ZRODLO_*`, `KOLEJNOSC_ZRODEL_NA_STOLE`, `AKCJE_LOGU` (9 wartości). |
| 1 | `98911631` | `priorytety/services/stol.py`: klucze kafli (`p:<id>` / `o:<id>`), `kompletne_na`, `stara_appka`, `zdejmij_kafel`, **`zdejmij_nieaktualne(order)`** (uzgodnienie wierszy stołu zamówienia pod jego blokadą X) wpięte u pięciu pisarzy: ZAKOŃCZ, doróbka, zmiany z Base., hurt, cron osieroconych; **`bramka_zakoncz`** (409 `nie_na_stole` w trybie `stol`) w `order_complete` i `order_quantity`; log `odlozenie_zamkniete`. |
| 2 | `4b9c0632` | `stol.dopelnij(S)` pod blokadą stanowiska (`priorytety_blokada_<S>` w `prod_config`), odczyt bieżący zamówień → pozycji `FOR SHARE`, `stol.stan`, **`GET /api/mobile/stations/<kod>/desk`** (commit → blokada → commit, jedno ponowienie po 1213, ETag, `max-age=0`). W tym samym commicie zakres (b) karty: źródło kafla (`kolejka` / `dorobka`), liczenie do K wszystkich kafli na stole, kolejność stołu wg spec 5.1, `zrodlo` w JSON. |
| 3 | `b7cf0904` | `stol.odloz` + **`POST /api/mobile/orders/<id>/postpone`** (powód z listy, notatka, miękki limit na stanowisko, blokada tylko wiersza własnego kafla, log `odlozenie`). |
| 4 | `76e8ee81` | `priorytety/services/sygnaly.py` (`zaplanuj` / `porzuc` / `wyslij`), `realtime_service.publish_station_signal` (kanał `station:<kod>`, bez ładunku), `with_idempotency` wysyła plan po commicie i porzuca go przy rollbacku, **`GET /api/mobile/realtime-token`**; sygnały z ZAKOŃCZ, licznika, Odłóż, `desk` (tylko gdy coś pobrał), doróbki, hurtu, Base., crona. |
| 5 | `e2e40fe3` | `stol.kontekst_priorytetu` + pole **`priorytet`** w `serialize_order` (`gwiazdki`, `szczebel`, `trasa`, `pozycja_w_zamowieniu`), `KSZTALT_ODPOWIEDZI_KOLEJKI = 6`; panel: **`GET /stoly`**, **`GET /odlozenia`** (`widok.stoly_panelu`, `odlozenia_panelu`). |
| 5a | `1bb0c733` | Lakiernia bez stołu: `priorytety/services/lista.py` (`klucz_grupy_wykonczenia`, `porzadek_listy`), lista i delta `painting` w kolejności grup wykończenia, pole `grupa_wykonczenia`, 409 `stanowisko_bez_stolu` z `desk` / `postpone`, bramka przepuszcza Lakiernię. Używa `ustawienia.STANOWISKA_BEZ_STOLU` z K2 (bez drugiej stałej). |
| 5b | `cff4f51d` | Spec 5.7: `stol.wyslij`, `stol.zdejmij_przez_biuro` + **`POST /stoly/<kod>/wyslij`**, **`POST /stoly/<kod>/zdejmij`** (`guard`), logi `wyslanie` / `zdjecie`, sygnał po commicie. |
| 5c | `64358f02` | Spec 5.8: `stol.rozpoczete_na_stanowisku`, `stol.przygotuj_start` + **`GET /start`** (`guard`), **`POST /start/przygotuj`** (`admin_required`, stanowisko po stanowisku w osobnych transakcjach, log `start_stolow`). `test_zestaw_koncowek` → 14 końcówek panelu. |
| przegląd | `d7850918` | Poprawki po przeglądzie końcowym gałęzi — sekcja „Przegląd końcowy”. |
| 6 | (ten commit) | Pełny pakiet, składnia 3.9, grepy kontrolne, próby na MySQL, lista wyścigów dla K5, raport. |

Zakres (e) karty: `test_zestaw_koncowek` ma 14 końcówek panelu (8 z K2 + `stoly`, `odlozenia`, `wyslij`, `zdejmij`, `start`,
`start/przygotuj`), testy 401/403 są parametryzowane tą samą listą, więc nowe końcówki dostały je automatycznie.

**Nowe pliki kodu:** `priorytety/services/stol.py`, `sygnaly.py`, `lista.py`, migracja K3. **Zmienione:** `kolejka.py`,
`widok.py`, `stale.py`, `models.py`, `routers/panel_api.py` (pakiet `priorytety`); `routers/mobile_api.py`,
`services/mobile_api_service.py`, `realtime_service.py`, `rework_service.py`, `sync_service.py`,
`routers/api/products_api.py`, `logistics/services/delivery.py`, `logistics/routers/cron_api.py`. Razem z testami 32 pliki,
+6375 / −61 linii (przed poprawkami przeglądu; poprawki: 4 pliki, +336 / −31).

## K1-poprawka-1

**Usterka (raport K1 / dziennik centrali):** `kolejka.utrwal()` pracuje na WŁASNEJ sesji. Gdy wołający ma niezatwierdzony
zapis zamówienia (albo cudza transakcja długo trzyma blokadę), `utrwal` czekał na blokadę pełne
`innodb_lock_wait_timeout` serwera (50 s) — przy własnym zapisie wołającego do końca, bo wołający czeka na `utrwal`.

**Zrobione (`modules/production/priorytety/services/kolejka.py`):**

- `nowa_sesja()` przypina sesję do JEDNEGO połączenia z puli (`db.engine.connect()` + `create_session({'bind': polaczenie,
  'binds': {}})` — puste `binds` jest konieczne, inaczej mapa tabel Flask-SQLAlchemy wygrywa z `bind` i sesja bierze inne
  połączenie). Na MySQL pierwszym poleceniem jest `SET SESSION innodb_lock_wait_timeout = 5`
  (`LIMIT_CZEKANIA_NA_BLOKADE_S`); poza MySQL (SQLite testów) nic nie jest wysyłane.
- Błąd **1205** (limit czekania) → ostrzeżenie w logu + `success: False` **bez ponowienia** (ponowienie znów czekałoby
  5 s na tę samą blokadę). 1213 nadal ponawiane raz, jak w K1 — druga sesja też dostaje limit.
- **Przywrócić czy odłączyć — decyzja: przywracam.** `_zamknij(sesja)` zamyka sesję, wysyła
  `SET SESSION innodb_lock_wait_timeout = DEFAULT` (wartość sesji wraca do globalnej) i oddaje połączenie do puli.
  Dopiero gdy przywrócenie się nie uda, połączenie jest unieważniane (`invalidate()`), żeby do puli nie wróciło z limitem
  5 s. Uzasadnienie: `utrwal` idzie po większości akcji panelu i po cronie; odłączanie połączenia za każdym razem to nowe
  połączenie TCP + uwierzytelnienie na każde przeliczenie i szybsze zużycie limitu połączeń na użytkownika bazy (40 na
  produkcji). Koszt błędnej decyzji: zamiana na `invalidate()` zawsze — 2 linie.

**Testy SQLite** (`tests/test_priorytety_kolejnosc_zapisow.py`, 6 nowych):
`test_utrwal_ustawia_limit_czekania_na_wlasnym_polaczeniu`, `test_utrwal_trzyma_jedno_polaczenie_przez_wszystkie_przebiegi`,
`test_utrwal_1205_bez_ponowienia_i_z_przywroceniem_limitu`, `test_utrwal_po_1213_druga_sesja_tez_ma_limit`,
`test_utrwal_nieudane_przywrocenie_uniewaznia_polaczenie`, `test_utrwal_bez_limitu_poza_mysql`.

**MySQL, dwie sesje** (baza `priorytety_podglad`, skrypt poza repo, bez trwałych zmian danych):

| Próba | Wynik |
|---|---|
| (0) czyste `utrwal()` | `success: True`, 0,17 s |
| (1) cudza sesja trzyma `FOR UPDATE` na zamówieniu | `success: False` po **5,02 s**, błąd 1205, bez ponowienia |
| (2) ten sam wątek ma niezatwierdzony zapis zamówienia i woła `utrwal()` | `success: False` po **5,02 s** (zamiast 50 s) |
| (3) po zwolnieniu blokady | `success: True`, ranga wróciła |
| (4) limity połączeń w puli po próbach | `[50, 50, 50, 50]` = wartość globalna 50 — limit 5 s nie wyciekł do puli |

## Testy (polecenia i wyniki)

Polecenie (karta), z worktree: `docker compose -p priorytety run --rm --no-deps app pytest <ścieżki> -q -p no:cacheprovider`
(nigdy `docker compose exec app`). Pełny pakiet zawsze pojedynczo.

| Co | Wynik |
|---|---|
| Punkt wyjścia, pełny pakiet na `dcd28e0a` | **6341 passed, 3 skipped**, 0 failed (7 min 01 s) |
| Pełny pakiet po Tasku 1 (`98911631`) | 6387 passed, 3 skipped |
| Pełny pakiet po Tasku 2 (`4b9c0632`) | 6428 passed, 3 skipped (6 min 12 s) |
| Pełny pakiet po Tasku 4 (`76e8ee81`) | 6489 passed, 3 skipped (7 min 15 s) |
| Pełny pakiet po Tasku 5c (`64358f02`) | **6584 passed, 3 skipped**, 0 failed (6 min 14 s) |
| Pełny pakiet końcowy (`d7850918`, po poprawkach przeglądu) | **6592 passed, 3 skipped**, 0 failed (6 min 54 s) |
| Zestawy po Taskach (`-k 'priorytety or blokady or mobile …'`) | T0: 522 · T2: 533 · T3: 558 · T4: 905 · T5: 1880 · T5a: 1903 · T5b: 669 · T5c: 689 passed |

**Bilans:** 6341 (punkt wyjścia) + 243 (Taski 0–5c) + 8 (poprawki przeglądu końcowego) = **6592**; żaden test nie został
wyłączony ani usunięty (3 `skipped` to te same co w punkcie wyjścia).

**Nowe / zmienione pliki testów:** `tests/test_priorytety_stol.py` (93 testy), `test_priorytety_mobile.py` (40, po
poprawkach przeglądu 48),
`test_priorytety_sygnaly.py` (28), `test_priorytety_lista_lakierni.py` (18), `test_migracja_priorytety_stol.py` (7),
`test_priorytety_panel_api.py` (80 → 95 funkcji, lista końcówek 8 → 14), `test_priorytety_kolejnosc_zapisow.py` (+6),
`test_priorytety_wyzwalacze_produkty.py` (+2); pomocniki `tests/blokady_pomocnicze.py`. Zaktualizowane testy starszych
kroków: `KSZTALT == 5` → 6 (`test_logistyka_mobile`, `test_paczki_podpowiedz`; `test_weryfikacja_problem` na `>= 5`),
lista `AKCJE_LOGU` w `test_priorytety_ustawienia`, zestaw tabel fikstury w `test_mobile_complete_bl_sync_queue`
(ZAKOŃCZ czyta stół). `blog_seo` nie dotyczy.

**TDD:** każdy Task: test → obejrzany RED → kod → GREEN. Wyjątek zapisany w dzienniku: testy Taska 2 powstały przed
kodem, ale bez osobnego przebiegu RED (pierwsze uruchomienie już z kodem) — zastąpione testami mutacyjnymi.

**Testy mutacyjne** (tekstowa mutacja reguły w kodzie → wskazany test musi poczerwienieć → przywrócenie pliku):
T1+T2 **22/22**, T3 **10/10**, T4 **17/17**, T5 **13/13**, T5a **15/15**, T5b **13/14** (ocalały mutant = zdublowana
kontrola stanowiska w routerze panelu; duplikat usunięty, zostaje `stol.wymagaj_stolu` w serwisie), T5c **15/15**,
poprawki przeglądu końcowego **14/14** (jedna mutacja przeżyła pierwszy przebieg — trzecia próba po dwóch 1213 — i
została złapana po dopisaniu licznika prób do `test_desk_dwa_1213_to_500_bez_zapisow`).
Mutacje obejmowały m.in.: brak commitu przed blokadą stanowiska, `FOR UPDATE` zamiast `FOR SHARE`, kolejność zamówienia /
pozycje, liczenie do K z odłożonymi, doróbka wliczana do limitu pobrania, bramka bez progu wersji, sygnał przed
commitem, sygnał przy rollbacku, połysk w kluczu grupy dla olejowanych, zdarzenia innego stanowiska w starcie stołów.

**Składnia 3.9:** `python:3.9-slim` (3.9.25), `ast.parse(feature_version=(3, 9))` + `compile` dla 30 plików `.py`
zmienionych od `dcd28e0a` — 0 błędów; brak `X | Y` w adnotacjach, brak `match`.

**Grepy kontrolne (plan, Task 6 Step 3):**

- `db.session.commit` w `stol.py`, `sygnaly.py`, `lista.py`, `widok.py` — **brak**. W `mobile_api.py` nowe commity tylko
  w `station_desk` (dwa: koniec migawki i commit dopełnienia); pozostałe dwa miejsca są sprzed K3.
- `zdejmij_nieaktualne` wołane przez dokładnie **pięciu pisarzy**: `mobile_api.order_complete` (ZAKOŃCZ),
  `rework_service` (doróbka), `sync_service.apply_baselinker_changes` (Base.), `products_api._zapisz_zmiane_statusu`
  (hurt), `delivery.przenies_osierocone_z_logistyki` (cron). Licznik sztuk ma tylko bramkę.
- Blokujące odczyty `prod_station_desk` wyłącznie po (`station_code`, `unit_key`) własnego kafla albo po `order_id`
  zablokowanego zamówienia. Nikt nie blokuje wierszy stołu całego stanowiska.
- `sygnaly.*` wołane tylko z miejsc tabeli w sekcji „Sygnały” niżej.

### Realtime bez Centrifugo

Brokera w środowisku nie ma; konfiguracja podglądu ma `REALTIME.enabled: false`. Sprawdzone testami
(`tests/test_priorytety_sygnaly.py`): `publish_station_signal` przy wyłączonym realtime zwraca `False` bez wyjątku, przy
padniętym brokerze (wyjątek połączenia) też `False` — ZAKOŃCZ, Odłóż i `desk` kończą się 200; `GET /realtime-token` →
503 `{"enabled": false, "reason": "realtime disabled"}`. Na próbie MySQL (niżej) wszystkie żądania szły przy wyłączonym
realtime. **Niesprawdzone:** prawdziwa publikacja do Centrifugo i odbiór po SSE — zostaje dla K5 (podgląd z brokerem).

### Próba na MySQL — zapisy stołu (bez wyścigów)

Osobna baza **`priorytety_wyscigi`** (kopia `priorytety_podglad`, MySQL 8.4.10) — `priorytety_podglad` nie dostała
żadnego zapisu stołu. Klient testowy Flaska, prawdziwe commity, realtime wyłączony. Kolejność zapytań zebrana **po stronie
klienta** (tekst SQL wysłany przez dialekt MySQL + commity), bez `SET GLOBAL general_log` — serwer jest wspólny
z podglądami 5002–5005 (rozstrzygnięcie 34). Parametry zapytań i dane klientów nie były wypisywane.

Czasy `GET desk` (K = 2 na każdym stanowisku):

| Stanowisko | 1. `desk` (dopełnia) | 2. `desk` (200) | 3. `desk` (304) | Stół po 1. | Niekompletne | `kolejka_dalej` |
|---|---|---|---|---|---|---|
| cutting | 103 ms | 43 ms | 21 ms | 11 | 0 | 11 |
| assembly | 56 ms | 43 ms | 21 ms | 9 | 0 | 25 |
| gluing | 82 ms | 51 ms | 26 ms | 2 | 0 | 76 |
| formatting | 81 ms | 75 ms | 23 ms | 2 | 2 | 17 |
| edges | 37 ms | 33 ms | 15 ms | 2 | 0 | 3 |
| packaging | 62 ms | 54 ms | 27 ms | 2 | 2 | 4 |

10 kolejnych `desk` bez ETagu: gluing mediana 51 ms (max 53), packaging 56 (60), formatting 72 (75) — daleko pod progiem
300 ms z tabeli ryzyk planu. Dopełnienie to 19 zapytań. Stół Wycinania (11) i Składania (9) po pierwszym `desk` to doróbki
ponad K (spec 5.1) — patrz Pytania p. 2. `stoly_panelu()`: 93 ms / 66 zapytań (6 stanowisk); `odlozenia_panelu()`: 4 ms.
ZAKOŃCZ pozycji spoza stołu w trybie `stol` → 409 `nie_na_stole`; ZAKOŃCZ kafla ze stołu → 200 w 41 ms. Zero
zdublowanych kluczy (`station_code`, `unit_key`) po całej próbie.

Kolejność zapytań (skrócona do tabel i klauzul blokad):

```
GET desk (gluing, dopełnia):
  COMMIT                                                        -- koniec migawki żądania
  SET SESSION innodb_lock_wait_timeout = 5                      -- po poprawce W2 (nie jest odczytem)
  SELECT prod_config WHERE config_key = ? FOR UPDATE            -- blokada stanowiska
  SELECT prod_config … ×2                                       -- K, jednostka (zwykły odczyt: tu powstaje migawka)
  SELECT prod_products WHERE current_status = ?                 -- id kandydatów
  SELECT prod_orders WHERE id IN (…) ORDER BY id LOCK IN SHARE MODE
  SELECT prod_products WHERE order_id IN (…) ORDER BY order_id, id LOCK IN SHARE MODE
  SELECT prod_route_stops JOIN prod_routes …                    -- trasy zamówień
  SELECT prod_station_desk WHERE station_code = ?               -- zwykły odczyt stołu, bez blokady
  SELECT prod_configurations … ; SELECT prod_priority_rungs …
  SET SESSION innodb_lock_wait_timeout = DEFAULT                -- po poprawce W2: przed commitem
  INSERT prod_station_desk ×2
  COMMIT
  … zwykłe odczyty odpowiedzi (stol.stan + serializacja)

POST complete (gluing, kafel ze stołu, tryb stol):
  SELECT prod_orders … ORDER BY id FOR UPDATE                   -- zamówienie najpierw
  SELECT prod_products WHERE order_id = ? ORDER BY id FOR UPDATE
  SELECT prod_config … ×3                                       -- tryb, próg wersji, jednostka
  SELECT prod_station_desk WHERE station_code = ? AND unit_key = ? FOR UPDATE   -- bramka: własny kafel
  UPDATE prod_products … ; INSERT prod_product_events
  SELECT prod_station_desk WHERE order_id = ? ORDER BY id FOR UPDATE            -- zdejmij_nieaktualne
  DELETE prod_station_desk WHERE id = ?
  … odczyty odpowiedzi ; INSERT processed_mobile_operations ; COMMIT

POST postpone (gluing):
  SELECT prod_orders … FOR UPDATE ; SELECT prod_products … FOR UPDATE
  SELECT prod_station_desk WHERE station_code = ? AND unit_key = ? FOR UPDATE   -- tylko własny kafel
  SELECT prod_station_desk WHERE station_code = ? AND postponed_at IS NOT NULL  -- limit: zwykły odczyt
  INSERT prod_priority_log ; UPDATE prod_station_desk ; … odczyty odpowiedzi ; COMMIT

stol.wyslij / zdejmij_przez_biuro / przygotuj_start:
  SELECT prod_config … FOR UPDATE                               -- blokada stanowiska
  [zdejmij: SELECT prod_station_desk WHERE station_code = ? AND unit_key = ?   -- zwykły: które zamówienie]
  [przygotuj: SELECT prod_products WHERE current_status = ?]
  SELECT prod_orders … LOCK IN SHARE MODE ; SELECT prod_products … LOCK IN SHARE MODE
  [przygotuj: SELECT prod_station_events … ; SELECT prod_station_desk WHERE station_code = ?  -- zwykłe]
  [wyslij/zdejmij: SELECT prod_station_desk WHERE station_code = ? AND unit_key = ? LIMIT 1 FOR UPDATE
                   -- po poprawce W1: jedno zapytanie NA KLUCZ (przed poprawką: unit_key IN (…) ORDER BY id)]
  INSERT prod_priority_log ; INSERT / UPDATE / DELETE prod_station_desk ; COMMIT
```

Ślady `desk` i „Wyślij” powtórzone po poprawkach przeglądu (sekcja „Przegląd końcowy”); czasy w tabeli wyżej są sprzed
poprawek — po nich `desk` bez cudzej blokady: 0,11–0,18 s.

Potwierdzone na MySQL: `dopelnij` nie bierze żadnej blokady X na zamówieniach ani na wierszach stołu; ZAKOŃCZ nie dotyka
`priorytety_blokada_%`; DELETE stołu zawsze po blokadzie zamówienia i pozycji.

**Stan baz po kroku:** `priorytety_podglad` — migracja K3 wykonana, 0 wierszy stołu, dane bez zmian.
`priorytety_wyscigi` — ISTNIEJE i jest w stanie po próbach (stoły wypełnione, Sklejanie 49 wierszy po próbie „Wyślij”,
`priorytety_tryb_gluing = stol`, urządzenia `K3-PROBA-*`, kilka wpisów logu; tabela pomocnicza EXPLAIN usunięta) —
**K5 musi ją odtworzyć z `priorytety_podglad` przed wyścigami**. Pusty
`config/core.json` w worktree kasowany po każdym `docker run`. Kontenery i bazy podglądów 5002–5005 nietknięte, port
5006 nieużyty, `general_log` nie był włączany.

### Migracja K3 na MySQL

Na `priorytety_podglad`: pierwsze wykonanie przy `create_app()`; dwa kolejne `flask migrate` — „Brak nowych migracji”;
ponowne wykonanie pliku po ręcznym usunięciu wpisu z `schema_migrations` — bez błędu i bez zmian. Kolumny po migracji:
`zrodlo varchar(16) NOT NULL DEFAULT 'kolejka'`, `sent_by_user_id int NULL`, `action` enum o 9 wartościach.
`MODIFY` enuma nie ma osłony `information_schema` (jest idempotentny sam z siebie — wzór migracji logistyki).

## Kafle startowe per stanowisko (kopia danych, `priorytety_podglad`, tylko odczyt)

`stol.rozpoczete_na_stanowisku(S)` — same liczby, bez danych klientów. K = 2 na każdym stanowisku.

| Stanowisko | Jednostka | Pozycji w statusie | Zamówień | **Kafle startowe** | z licznika (> 0 szt. na S) | z „zamówienie rozpoczęte na S” |
|---|---|---|---|---|---|---|
| Wycinanie | pozycja | 22 | 18 | **7** | 1 | 6 |
| Składanie | pozycja | 34 | 13 | **27** | 0 | 27 |
| Sklejanie | pozycja | 78 | 21 | **30** | 15 | 15 |
| Formatowanie | zamówienie | 51 | 23 | **6** | 5 | 1 |
| Krawędzie | pozycja | 5 | 5 | **0** | 0 | 0 |
| Pakowanie | zamówienie | 95 | 66 | **4** | 0 | 4 |
| **Razem** | | | | **74** | 21 | 53 |

Czas policzenia 4–30 ms na stanowisko. Lakiernia nie ma stołu (brak wiersza). Wariant „tylko licznik” dałby 21 kafli.
**Do decyzji Konrada** (spec 5.8, ostatni akapit): Składanie 27 z 34 pozycji i Sklejanie 30 z 78 — stół startowy
wielokrotnie dłuższy niż K. Definicja „rozpoczęte” użyta w liczeniu: rozstrzygnięcie 31; pytanie 1.

## Odstępstwa od planu

1. **Zakres rozszerzony kartą:** Task 0 (poprawka K1), 0a (migracja — plan zakładał „brak migracji w kroku”), 5b
   („Wyślij” / „Zdejmij”), 5c (start stołów), dopisek „źródło kafla” w Tasku 2. Dopisane do planu przed kodem (`badc7326`).
2. **Liczenie do K — spec 5.1 zamiast planu.** Plan: doróbki nie liczą się do K. Spec i karta: do K liczą się WSZYSTKIE
   kafle leżące na stole (także `dorobka`, `biuro`, `start`); doróbka wchodzi zawsze, ponad K, ale zajmuje miejsce.
   Skutek: po doróbce stół dobiera z kolejki dopiero, gdy zejdzie poniżej K.
3. **Kolejność na stole — spec 5.1** (`dorobka`, `biuro`, `start`, `kolejka`; w grupie `pulled_at`, `id`) zamiast planu
   (Doprecyzowanie 17: `created_at` doróbki).
4. **Zakres (b) karty w commicie Taska 2**, nie osobnym — osobny commit wymagałby najpierw wersji `dopelnij` sprzecznej
   ze specem. Karta dopuszcza („osobne Taski”) — Task jest (dopisek w planie), commit wspólny.
5. **`STANOWISKA_BEZ_STOLU`:** używam `ustawienia.STANOWISKA_BEZ_STOLU` z K2; plan chciał nowej krotki w `stale.py`.
6. **Polecenia testów i MySQL z karty**, nie z planu (`docker compose exec app` → `docker compose -p priorytety run …`).
7. **Step 4 Taska 6:** kolejność zapytań z klienta zamiast `general_log` (serwer wspólny z innymi podglądami); treść ta sama.
8. **Liczba commitów:** plan przewidywał 7; jest 11 + poprawki przeglądu + raport (Taski z karty).
9. **`test_zestaw_koncowek`:** 14, nie 10 (karta, zakres e).
10. **Sygnał po pobraniu na stół** wszedł w Tasku 4 (plan: wstawić w Tasku 2 i przenieść w 4).
11. **Wejście kandydatów jak K2**, nie jak w tekście planu: `widok.wejscie_kandydatow(...)`, statusy jako pary
    `(product_id, status)`, `jednostka=ustawienia.jednostka(S)` — plan miał starszy kształt; kontrakt z raportów K1/K2.
12. **Kontrola stanowiska w serwisie** (`stol.wymagaj_stolu`), router panelu jej nie dubluje (mutant T5b).
13. **Nazwy dwóch testów z Review Focus 2:** plan podaje je raz jako `test_dopelnij_ponawia_raz_po_1213` /
    `test_dopelnij_dwa_1213_to_500_bez_zapisow` (Review Focus), raz jako `test_desk_…` (treść Taska 2). Istnieją pod
    nazwami `test_desk_ponawia_raz_po_1213` i `test_desk_dwa_1213_to_500_bez_zapisow` (`tests/test_priorytety_mobile.py`) —
    ponowienie siedzi w routerze `desk`, nie w `dopelnij`. Pozostałe 44 testy z Review Focus istnieją pod nazwami z planu.

## Rozstrzygnięcia podjęte w trakcie (numerowane; koszt, jeśli błędne)

Blokady i transakcje:

1. **Kolejność blokad „pisarzy stołu”** (`dopelnij`, `wyslij`, `zdejmij_przez_biuro`, `przygotuj_start`): commit →
   `priorytety_blokada_<S>` `FOR UPDATE` → zamówienia rosnąco `FOR SHARE` → pozycje `ORDER BY order_id, id` `FOR SHARE` →
   zwykły odczyt stołu → zapis → commit. Nigdy X na zamówieniach. — Koszt: `FOR SHARE` na kilkudziesięciu zamówieniach co
   `desk`; zmierzone 37–103 ms. Gdyby na produkcji było wolno: opcja z planu (zwykły odczyt zamówień, S tylko na pozycjach).
2. **„Pisarze zamówienia”** (ZAKOŃCZ, Odłóż, hurt, doróbka, Base., cron) dotykają wierszy stołu WYŁĄCZNIE własnego
   zamówienia, pod jego blokadą X: po (`station_code`, `unit_key`) albo po `order_id`. Nikt nie blokuje wierszy stołu
   całego stanowiska. — Koszt: żaden; inaczej wracał cykl indeks wtórny ↔ klucz główny.
3. **`zdejmij_nieaktualne(order)`** — jedna funkcja uzgadniająca stół zamówienia u każdego pisarza (po `flush`, odczyt
   bieżący wierszy stołu po `order_id`): kafel `p:` zostaje tylko, gdy pozycja czeka na swoim stanowisku w jednostce
   `pozycja`; kafel `o:` — gdy zamówienie ma pozycję na stanowisku i jest kompletne **albo** kafel ma źródło `biuro` /
   `start` (biuro świadomie wysłało niekompletne — spec 5.7); wiersze innej jednostki i Lakierni znikają. — Koszt: jedna funkcja.
4. **„Wyślij” / „Zdejmij”: wiersze stołu własnego zamówienia czytane odczytem bieżącym** (`FOR UPDATE` po kluczu
   unikalnym) pod blokadą stanowiska i S zamówienia. „Zdejmij” zna tylko klucz kafla, więc zamówienie ustala zwykłym
   odczytem przed blokadą zamówienia; ZAKOŃCZ mógł w tym oknie zdjąć kafel — odczyt bieżący to wykrywa (404), zwykły
   dawał `StaleDataError`. — Koszt: blokada rekordu / luki na (`station_code`, `unit_key`). **Poprawione po
   przeglądzie (W1):** odczyt idzie każdym kluczem osobno; pierwotna wersja (`unit_key IN (…)`) blokowała cudze kafle,
   a zdanie „bez cyklu” z dziennika było za mocne — patrz „Przegląd końcowy” i rozstrzygnięcie 37.
5. **Task 0: przywracam limit i oddaję połączenie**, unieważnienie tylko po nieudanym przywróceniu (sekcja K1-poprawka-1). — Koszt: 2 linie.
6. **Odpowiedź `desk` / `postpone` zawsze ze zwykłych odczytów po commicie** (`stol.stan`), nie z wyniku `dopelnij`. —
   Koszt: drugie policzenie kandydatów przy 200 (przy 304 nie).
7. **`POST /start/przygotuj` przerywa na pierwszym nieudanym stanowisku** (500 z listą wykonanych i polem `nieudane`),
   bez cofania poprzednich; wywołanie jest idempotentne. — Koszt: żaden.
8. **Doróbka planuje sygnał PO własnym commicie** (`reject_product_quantity` commituje sam). — Koszt: żaden.

Reguły stołu:

9. **Bramka ZAKOŃCZ przepuszcza:** Lakiernię, tryb `stary`, starą appkę, kafel leżący albo odłożony, oraz pozycję
   NIEKOMPLETNEGO zamówienia na stanowisku zamówieniowym (plan, Doprecyzowanie 12 — takie zamówienie nie może mieć kafla,
   a pracownik musi móc robić dostępne pozycje). — Koszt: na Formatowaniu / Pakowaniu niekompletne zamówienia są poza
   kontrolą stołu (sekcja „Niekompletne” jest klikalna).
10. **Próg wersji appki:** stara = próg > 0 i (wersja nieznana albo < progu); próg 0 = bramka wersji wyłączona (wszyscy
    „nowi”). Tablet bez heartbeatu przy progu > 0 liczy się jako stary. Stara appka omija bramkę, ale jej ZAKOŃCZ zdejmuje kafel. — Koszt: jedna funkcja (`stol.stara_appka`).
11. **Limit odłożeń miękki** (plan, Doprecyzowanie 13): liczony zwykłym odczytem, dwa jednoczesne Odłóż mogą przekroczyć
    limit o 1. — Koszt: twardy limit wymagałby blokady stanowiska w Odłóż (odwrócona kolejność → cykl).
12. **Pakowanie: zamówienie bez sposobu dostawy** nie wchodzi na stół (spec), a dodatkowo: nie trafia do „Niekompletnych”,
    nie staje się kaflem startowym, „Wyślij” odpowiada 409 `delivery_method_not_set`. — Koszt: jedna linia filtra na przypadek.
13. **„Wyślij” na kaflu już leżącym niczego nie zmienia** (ani źródła, ani czasu); odłożony wraca na stół ze źródłem
    `biuro`. Odpowiedź: `wynik` + listy kluczy `wyslane` / `przywrocone` / `juz_na_stole`. — Koszt: kształt do K4a.
14. **Definicja „rozpoczęte” (start stołów):** patrz 31.
15. **Log `odlozenie_zamkniete`:** `reason` = powód, `note` = notatka odłożenia, `old_value` = czas odłożenia (plan:
    `note` = powód). — Koszt: żaden; modal K2 czyta `reason` / `note`.

API i kontrakt:

16. **ETag `desk` szerszy niż plan:** poza `max(updated_at)` wchodzą liczba pozycji w statusie S, suma liczników sztuk
    stanowiska, gwiazdki zamówień, liczba odłożonych, K / limit / jednostka i oba KSZTAŁTY. `updated_at` ma w MySQL
    dokładność sekundy — dwie zmiany w tej samej sekundzie dawałyby 304. — Koszt: 3 agregaty na `desk`.
17. **`pracownik` w odłożonych = imię i nazwisko** (plan), nie „Adam K.” z przykładu specu. — Koszt: format pola.
18. **Komunikat limitu z polską odmianą i nazwą jednostki** („Na Sklejaniu leży 1 odłożona pozycja. Zamknij którąś,
    zanim odłożysz kolejną.”) zamiast dosłownego przykładu specu. — Koszt: tekst.
19. **Walidacja `postpone`:** notatka > 255 znaków i złe typy → 400 `dane_niepoprawne` (router); powód spoza listy albo
    „inne” bez notatki → 400 `powod_niepoprawny` (serwis); `zakres` niezgodny z jednostką stanowiska → 400 `dane_niepoprawne`. — Koszt: żaden.
20. **`sygnaly.wyslij(*kody)`** przyjmuje też kody wprost (routery panelu, `desk`, hurt, Base. wysyłają po własnym
    commicie), a dekorator woła `sygnaly.porzuc()` w gałęziach rollbacku (plan: plan sygnałów „ginie z `g`”). — Koszt: 3 wywołania.
21. **Bez sygnału:** „Cofnij do pakowania” (weryfikacja), przepakowanie i import nowych zamówień nie wysyłają
    `station:packaging` / `station:cutting` (plan: poza zakresem; spec 5.4 ich nie wymienia). — Koszt: do 30 s opóźnienia
    na pustym stole, a przy stole niepustym i niepełnym (1 z 2) — do 5 min, jeśli appka odpytuje co 30 s tylko pusty
    stół (uwaga recenzenta, D4; zalecenie dla K6 niżej).
22. **`kontekst_priorytetu` bez pamięci w `g`** (plan: cache w `g`); tryb `komplet=True` dla list i stołu (bez
    dodatkowego zapytania o pozycje) i pominięcie odczytu drabiny, gdy żadne zamówienie nie ma `priority_rung`. — Koszt:
    pojedyncza pozycja (ZAKOŃCZ, wyszukiwarka) płaci 1–2 małe zapytania.
23. **`pozycja_w_zamowieniu` liczona po „miejscach”:** doróbka stoi w miejscu oryginału (także anulowanego w całości),
    pozycja anulowana bez żywej doróbki → `null`. — Koszt: jedna funkcja.
24. **`trasa` w `priorytet`** brana z wiersza szczebla (`rung.route`), nie z osobnego odczytu tras. — Koszt: gdy
    `priority_rung` nieświeży, trasa też — do najbliższego `utrwal`.
25. **`GET /stoly`: 6 stanowisk od razu** (bez Lakierni); kafel panelu ma dodatkowo `unit_key`, `zrodlo`, `wyslal`;
    odłożenia mają `unit_key`. — Koszt: żaden.
26. **`grupa_wykonczenia` ma CZTERY pola** `{rodzaj, typ_koloru, kolor, polysk}` — spec 6.3 wymienia trzy, ale klucz
    grupy w 3.2 (po poprawce Konrada) zawiera typ koloru; bez niego appka nie narysuje separatora tam, gdzie serwer
    zmienia grupę. — Koszt: jedno pole więcej w kontrakcie K6; spec 6.3 do poprawienia (pytanie 3).
27. **Lista Lakierni porównuje numer zamówienia tekstowo** (jak dzisiejszy `ORDER BY` listy), nie liczbowo jak kolejka K1. —
    Koszt: przy równej randze „9999” po „10000”.
28. **Nieznane stanowisko w ścieżce panelu → 400 `stanowisko_nieznane`** (jak `GET /kolejka?stanowisko=` z K2). — Koszt: żaden.
29. **Testy starszych kroków pilnujące `KSZTALT == 5`** podbite do 6. — Koszt: żaden (spec 6.3).
30. **`MODIFY` enuma w migracji bez osłony**; test K1 listy akcji zaktualizowany o 3 akcje. — Koszt: żaden.
31. **Start stołów — „ręcznie zrobione”:** zdarzenie `prod_station_events` na stanowisku S ze źródłem `mobile` / `web` /
    `admin` i `delta > 0`. Kaflem startowym jest: (a) pozycja w statusie S z licznikiem S > 0 (bez sprawdzania źródła —
    spec: „ma licznik > 0”), albo (b) pozycja w statusie S z zamówienia, którego INNA pozycja była ręcznie zrobiona na S
    (takie zdarzenie + licznik > 0 + status już inny niż S + nie anulowana / wstrzymana) — „zamówienie rozpoczęte na
    stanowisku”. Na stanowisku zamówieniowym kaflem jest całe zamówienie. Pozycje przepchnięte automatem (`auto_skip`,
    `system`) nie liczą się. — Koszt: zawężenie / poszerzenie to jedna funkcja (`_rozpoczete` / `_zrobione_recznie`);
    liczby w tabeli wyżej zmienią się razem z definicją.
32. **`stol.wymagaj_stolu` w serwisie** (`dopelnij`, `odloz`, `wyslij`, `przygotuj_start`) obok odmowy w routerze
    mobilnym — stół Lakierni nie powstanie także przy wywołaniu serwisu wprost. — Koszt: żaden.
33. **Zakres (b) w commicie Taska 2** — Odstępstwa p. 4. — Koszt: brak osobnego commita w historii.
34. **Kolejność zapytań na MySQL z klienta**, bez `general_log`. — Koszt: brak zapisu w dzienniku serwera; treść ta sama.

Po przeglądzie końcowym:

35. **`GET desk` po przekroczeniu limitu czekania (MySQL 1205) oddaje 200 z bieżącym stołem bez dopełnienia**, nie 500
    `desk_failed`, i nie ponawia. Tablet po własnym ZAKOŃCZ dostaje prawdziwy stan stołu; wolne miejsce zajmie następny
    `desk` (sygnał albo siatka). — Koszt: zamiana na 500 to jedna linia i test.
36. **Limit czekania tylko w `GET desk`.** „Wyślij”, „Zdejmij” i „Przygotuj stoły” (ręczne akcje panelu) czekają jak
    dotąd — przy cudzej długiej blokadzie akcja panelu wisi do limitu serwera. — Koszt: dopisanie zasięgu limitu w
    `_zapis_z_ponowieniem` (kilka linii).
37. **Luka indeksu unikalnego zostaje:** dwa „Wyślij” naraz na RÓŻNYCH stanowiskach, których nowe klucze wpadają w tę
    samą lukę indeksu (`station_code`, `unit_key`), dają 1213 z jednym ponowieniem w routerze panelu. — Koszt: rzadkie
    ponowienie; tryb `wyslij-wyslij` dopisany do listy K5.
38. **Bez podpowiedzi indeksu (`FORCE INDEX`)** w `zdejmij_nieaktualne` (`order_id = ?`) i w odczycie pozycji `FOR SHARE`:
    EXPLAIN na MySQL 8.4 daje dostęp po właściwym indeksie we wszystkich sprawdzonych rozmiarach (tabela niżej), a
    podpowiedź wiązałaby kod z nazwą indeksu, która na `prod_products` różni się między środowiskami (`idx_order` w
    bazie z produkcji). — Koszt, jeśli błędne: 1213 w ZAKOŃCZ przy złym planie; K5 powtarza EXPLAIN na świeżej kopii.
39. **Próg wersji 0 przy trybie `stol` = bramka dla wszystkich, także starej appki** (plan,
    `test_bramka_prog_zero_to_brak_bramki_wersji`). — Koszt: stara appka dostaje 409 na wszystkim spoza stołu, jeśli
    K7 przełączy tryb przed ustawieniem progu (kolejność w sekcji K7).
40. **Kafel Pakowania, któremu logistyka zdjęła sposób dostawy po wejściu na stół, zostaje na stole;** ZAKOŃCZ → 409
    `delivery_method_not_set`, pracownik może go odłożyć. Spec milczy. — Koszt: kafel zajmuje miejsce (pytanie 7).
41. **Pozycja omijająca Formatowanie trzyma zamówienie w „Niekompletnych”** do czasu zejścia z wcześniejszego stanowiska —
    reguła K1 (`kompletne_na_stanowisku`), K3 jej nie zmienia. — Koszt: zamówienie w „Niekompletnych” zamiast na stole
    (pytanie 8).
42. **Wpis idempotencji `postpone` niesie cały stół** (odpowiedź 200). Kilka odłożeń dziennie na stanowisko. — Koszt:
    wzrost tabeli `processed_mobile_operations`; sprzątanie tabeli poza K3.

## Przegląd końcowy gałęzi

Osobny agent (Fable 5.1, świeży kontekst, tylko odczyt) przejrzał zakres `dcd28e0a..64358f02` względem specu, planu,
dziewięciu punktów Review Focus i rozstrzygnięć z dziennika. **Wynik: 0 krytycznych, 2 ważne, 11 drobnych; werdykt „po
poprawkach”.** Review Focus 1–9 spełnione (z uwagami niżej); ze wszystkimi rozstrzygnięciami zgoda, poza dwoma uwagami
(zdanie „bez cyklu” — W1; koszt braku sygnału — D4). Oba ważne znaleziska poprawione w jednej turze, test najpierw
(commit `d7850918`); drobne odłożone.

**W1 — „Wyślij” blokowało wiersze stołu całego stanowiska.** `_wiersze_do_zapisu` czytało własne kafle jednym
zapytaniem `WHERE station_code = ? AND unit_key IN (…) ORDER BY id FOR UPDATE`. EXPLAIN na MySQL 8.4.10
(`priorytety_wyscigi`) potwierdził zarzut recenzenta:

| Zapytanie | Tabela 87 wierszy | Tabela 10 wierszy | Tabela 2–4 wiersze |
|---|---|---|---|
| `unit_key IN (2 klucze) ORDER BY id` | `range` po `uq_prod_station_desk_unit` | `range` po uq / `index` po `ix_…_station_code` | `ref` po `ix_…_station_code` (wszystkie wiersze stanowiska) |
| `unit_key IN (3 klucze)` | `range` po `ix_…_station_code` (15 wierszy stanowiska) | `ref` po `ix_…_station_code` | `ref` po `ix_…_station_code` |
| `unit_key IN (8 / 25 kluczy)` | `ref` po `ix_…_station_code` | **`index` po `PRIMARY` — cała tabela** | `ref` po `ix_…_station_code` |
| `station_code = ? AND unit_key = ? LIMIT 1` (po poprawce) | `const` | `const` | `const` |
| `order_id = ? ORDER BY id` (`zdejmij_nieaktualne`) | `ref` po `ix_…_order_id` | `ref` | `ref` (także 0, 1 i 6 wierszy jednego zamówienia) |
| pozycje `order_id IN (…) … LOCK IN SHARE MODE` | `range` po `idx_order` dla każdego stanowiska (5–66 zamówień) i dla 156 aktywnych naraz (371 z 4017 wierszy) | | |

Skan indeksu stanowiska albo klucza głównego z `FOR UPDATE` blokuje cudze kafle — z ZAKOŃCZ innego zamówienia (trzyma
rekord swojego kafla, przy DELETE musi oznaczyć rekord indeksu wtórnego) wychodził cykl: 1213, „Wyślij” ponawia, a
**ZAKOŃCZ dostaje 500**. Poprawka: każdy klucz osobnym zapytaniem, równością po obu kolumnach klucza unikalnego (dostęp
`const` — rekord albo sama luka), w ustalonej kolejności kluczy. Testy: `test_wyslij_kolejnosc_blokad_jak_dopelnij`,
`test_zdejmij_przez_biuro_kolejnosc_blokad` (RED → GREEN). MySQL po poprawce: „Wyślij” zamówienia z 28 pozycjami na
Sklejaniu = 28 odczytów `const`, żadnego `IN` ani `ORDER BY`, 203 ms.

**W2 — `GET desk` czekał na cudzą blokadę bez limitu.** Dopełnienie czyta odczytem bieżącym zamówienia wszystkich
kandydatów; jedna długo trzymana blokada zamówienia zatrzymywała każde `desk` stanowiska na limicie serwera (50 s;
gunicorn ubija po 30 s), a `desk` wołają wszystkie tablety co 30 s — kilka wiszących żądań zajmuje workery całego CRM
(klasa incydentu z APK). Poprawka (wzór Taska 0): `stol.krotkie_czekanie_na_blokady()` — sesyjny
`innodb_lock_wait_timeout = 5` jako pierwsze polecenie transakcji dopełnienia, przywracany na tym samym połączeniu
PRZED commitem i rollbackiem; w zasięgu limitu nie ma autoflusha (nieudany flush oddałby połączenie do puli przed
przywróceniem); nieudane przywrócenie unieważnia połączenie, a gdyby połączenie było już w puli — wymienia pulę. Po
1205 `desk` nie ponawia i oddaje 200 z bieżącym stołem bez dopełnienia (rozstrzygnięcie 35). Testy (8 nowych,
`tests/test_priorytety_mobile.py`): `test_desk_ogranicza_czekanie_na_blokady_i_przywraca_limit`,
`test_desk_1205_oddaje_stol_bez_dopelnienia_i_bez_ponowienia`, `test_desk_po_1213_ponowienie_tez_ma_limit`,
`test_desk_1213_potem_1205_stol_bez_dopelnienia`, `test_desk_nieudane_przywrocenie_limitu_uniewaznia_polaczenie`,
`test_uniewaznij_polaczenie_zamkniete_wymienia_pule`, `test_desk_bez_limitu_poza_mysql`,
`test_dopelnienie_pod_limitem_nie_flushuje_przed_przywroceniem` (RED → GREEN); `test_desk_inny_blad_bazy_500_bez_ponowienia`
używa teraz innego kodu błędu (1040), a `test_desk_dwa_1213_to_500_bez_zapisow` liczy próby. Mutacje poprawek: **14/14**.

MySQL, dwie sesje (`priorytety_wyscigi`):

| Próba | Wynik |
|---|---|
| (0) `desk` bez cudzej blokady | 200, 0,18 s; ślad: `COMMIT` → `SET SESSION innodb_lock_wait_timeout = 5` → blokada stanowiska → … → `SET … = DEFAULT` → `COMMIT` |
| (1) cudza sesja trzyma `FOR UPDATE` na zamówieniu-kandydacie | **200 po 5,10 s**, stół bez zmian, `ROLLBACK`, limit przywrócony |
| (2) po zwolnieniu blokady | 200, 0,11 s |
| limity połączeń puli przed / po (0) / po (1) / po (2) | `[50, 50, 50, 50]` za każdym razem = wartość globalna |

**Drobne (odłożone, bez poprawek w K3):**

| # | Znalezisko | Dla kogo |
|---|---|---|
| D1 | Dwa testy Review Focus 2 pod nazwami `test_desk_…` | Odstępstwa p. 13 |
| D2 | Wiersz-widmo: po hurtowym usunięciu pozycji (admin) kafel `o:` zamówienia bez pozycji na stanowisku zostaje, liczy się do K, tablet go pokazuje, a `GET /stoly` go ukrywa (biuro nie ma jak kliknąć „Zdejmij”). Przejściowo to samo: zwykły odczyt stołu w `dopelnij` pochodzi sprzed blokad S, więc kafel zdjęty przez ZAKOŃCZ, na który dopełnienie czekało, zajmuje miejsce do następnego `desk` | K4b (pokazać widma), K5 |
| D3 | Sygnał stanowiska idzie po haku statusu Base. (pierwsza próba `setOrderStatus` jest synchroniczna) — przy ZAKOŃCZ kończącym zamówienie drugi tablet czeka na HTTP do Base. | K5 (przenieść `sygnaly.wyslij()` tuż za commit) |
| D4 | Koszt braku sygnału po „Cofnij do pakowania” / przepakowaniu / imporcie to do 5 min przy stole niepustym i niepełnym | K6 (zalecenie niżej), pytanie 5 |
| D5 | Sygnał doróbki planowany po jej własnym commicie przepada, gdy dalsza część handlera rzuci wyjątek | K5 |
| D6 | Luki ETagu stołu: zmiana samego szczebla (`priority_rung`) bez zmiany rangi, nazwa / data trasy; podmiana wiersza w tej samej sekundzie przy równej liczbie wierszy | K5 (dodać `max(id)` wierszy i znacznik drabiny) |
| D7 | „Zdejmij ze stołu” bywa pozorne: doróbka albo pierwszy kafel kolejki wraca przy najbliższym `desk` | K4a, K6 (opis), pytanie 9 |
| D8 | Limit odłożeń liczy wszystkie wiersze odłożone stanowiska, także innej jednostki i widma | K5 |
| D9 | `stol.zdejmij_kafel` i `stol.kafel_pozycji` nie są wołane z kodu produkcyjnego (tylko testy); spec 9.2 wymienia `zdejmij_kafel` jako kontrakt | K5 (usunąć albo poprawić spec: kontraktem jest `zdejmij_nieaktualne`) |
| D10 | Wydajność: leniwe `rung.route` w `kontekst_priorytetu` (zapytanie na szczebel trasy), pełne wiersze pozycji w delcie Lakierni tylko dla `all_ids`, podwójne liczenie kandydatów w `desk` 200 | K5 |
| D11 | Rozjazdy tekstu specu z kodem: `dane_niepoprawne` w Odłóż (spec 6.2 zna `powod_niepoprawny`), 4 pola `grupa_wykonczenia`, `STANOWISKA_BEZ_STOLU` w `ustawienia.py`, imię i nazwisko w `pracownik`, nazwa wiersza blokady w spec 5.2 (`priorytety_stol_<kod>` — w kodzie i reszcie specu `priorytety_blokada_<S>`) | K5 / K6 |

Rzeczy, które recenzent odłożył bez oceny, mają swoje rozstrzygnięcia (39–42) albo są w „Poza zakresem” (8–11).

## Pytania do Konrada

1. **Start stołów (spec 5.8).** Na kopii danych wychodzi 74 kafle, w tym Składanie 27 i Sklejanie 30 (tabela wyżej). 53
   z 74 pochodzą z reguły „zamówienie rozpoczęte na stanowisku” (inna pozycja zamówienia już tu zrobiona). Zostawić obie
   reguły (stół startowy bardzo długi), czy zawęzić do samego licznika (21 kafli), czy ograniczyć liczbą na stanowisko?
2. **Doróbki ponad K w dniu startu.** Na kopii danych pierwszy `desk` Wycinania kładzie 11 kafli, Składania 9 — to
   wszystkie doróbki czekające na tych stanowiskach (spec 5.1: doróbka zawsze na stół). Czy tak ma być pierwszego dnia,
   czy doróbki sprzed startu mają wejść inaczej (np. tylko nowe od startu)?
3. **`grupa_wykonczenia` z czterema polami** (`typ_koloru` dodatkowo) — potwierdzić i poprawić spec 6.3, zanim K6 spisze
   kontrakt appki.
4. **Pakowanie bez sposobu dostawy** nie pokazuje się ani na stole, ani w „Niekompletnych” — na tablecie go po prostu nie
   ma (jest na dzisiejszej liście dla starej appki). Czy nowa appka ma je gdzieś pokazywać („czeka na sposób dostawy”)?
5. **Bez sygnału realtime** po „Cofnij do pakowania”, przepakowaniu i imporcie nowych zamówień (do 30 s opóźnienia przy
   pustym stole). Dopisać te trzy miejsca w osobnym kroku, czy zostaje siatka odpytywania?
6. **Imię i nazwisko pracownika** w sekcji „Odłożone” na tablecie i w panelu (spec w przykładzie: „Adam K.”) — zostawić
   pełne, czy skracać nazwisko?
7. **Kafel Pakowania, któremu logistyka zdjęła sposób dostawy po wejściu na stół** — dziś zostaje na stole, ZAKOŃCZ
   odpowiada 409 „Logistyka nie ustawiła jeszcze sposobu dostawy…”, pracownik może go odłożyć. Czy ma sam schodzić ze
   stołu (wracać do kolejki bez sposobu dostawy)?
8. **Pozycja, która omija Formatowanie** (bez docięcia), a stoi jeszcze na wcześniejszym stanowisku, trzyma całe
   zamówienie w „Niekompletnych” Formatowania, choć na Formatowanie nigdy nie trafi (reguła kompletności z K1). Czy
   takie pozycje mają nie liczyć się do kompletności?
9. **„Zdejmij ze stołu” na doróbce albo pierwszym kaflu kolejki** jest pozorne: kafel wraca przy najbliższym `desk`
   (pozycja dalej czeka na stanowisku). Wystarczy opis w panelu („wróci do kolejki”), czy „Zdejmij” ma dla takich
   kafli odmawiać / wstrzymywać pozycję?
10. **Limit czekania `desk` (5 s) i odpowiedź 200 bez dopełnienia** po jego przekroczeniu — nowe zachowanie dodane po
    przeglądzie (rozstrzygnięcia 35–36); spec 5.2 o tym nie mówi. Do potwierdzenia i wpisania do specu.

## Stan gałęzi

- Gałąź `claude/priorytety-produkcji`, ostatni commit kodu `d7850918`, commit raportu — hash w odpowiedzi
  sesji (raport nie może zawierać własnego hasha). **Wypchnięte** na `origin/claude/priorytety-produkcji` po każdym Tasku
  (`git pull --rebase` przed pushem — bez konfliktów; wyjątek: przy commicie poprawek przeglądu `pull --rebase` odmówił
  z powodu niezacommitowanego jeszcze planu, a push przeszedł jako zwykłe przewinięcie `64358f02..d7850918` — zdalna
  gałąź nie miała nowych commitów).
- `main` nietknięty; główny checkout nie zmieniał gałęzi. Drzewo robocze czyste.
- Migracja K3 jest częścią gałęzi — wejdzie razem z migracją K1 przy wdrożeniu (kolejność plików po dacie:
  `2026-10-05-…` przed `2026-10-06-…`).

## Co następny krok musi wiedzieć

### Kontrakt blokad (K5 → CLAUDE.md, K4a/K4b przy każdym nowym zapisie)

- **Pisarz stołu** (`dopelnij`, `wyslij`, `zdejmij_przez_biuro`, `przygotuj_start`): router commituje → PIERWSZE
  polecenie to `stol.zablokuj_stanowisko(S)` → odczyt bieżący zamówień, potem pozycji (`FOR SHARE`) → zapis wierszy stołu →
  commit → sygnał. Żadnego zwykłego odczytu między commitem a blokadą stanowiska. Nigdy `FOR UPDATE` na zamówieniach.
- **Pisarz zamówienia** (każdy, kto zmienia status pozycji albo skład zamówienia): pod blokadą X zamówienia, po `flush`,
  woła `stol.zdejmij_nieaktualne(order)` i planuje sygnał dla zwróconych stanowisk. Nowy pisarz statusu bez tego wywołania
  zostawi martwy kafel na stole. Odłóż blokuje tylko wiersz własnego kafla.
- **Odczyt bieżący wierszy stołu tylko dwóch kształtów:** równość po całym kluczu unikalnym (`station_code = ? AND
  unit_key = ?`, jeden klucz na zapytanie) albo `order_id = ?` własnego zamówienia. Nigdy `unit_key IN (…)` ani sam
  `station_code` z klauzulą blokady — MySQL wykonuje je skanem indeksu stanowiska albo całej tabeli i blokuje cudze
  kafle (W1, EXPLAIN w „Przegląd końcowy”).
- **`GET desk` czeka na cudzą blokadę najwyżej 5 s** (`stol.krotkie_czekanie_na_blokady`, W2): limit sesji MySQL wraca
  do wartości serwera przed commitem i rollbackiem; w zasięgu limitu nie wolno commitować, cofać ani flushować
  (połączenie wróciłoby do puli z krótkim limitem — ostatnią zaporą jest wymiana puli).
- `order_quantity` (licznik) nie bierze blokady zamówienia (jak dziś) i czyta stół zwykłym odczytem — tylko bramka.
- `utrwal()` wolno wołać wyłącznie po commicie wołającego; z niezatwierdzonym zapisem zamówienia kończy się po ~5 s
  `success: False` (Task 0), bez wyjątku.

### K4a (Lista produkcyjna)

- Plakietka „Odłożone na …” i sekcja odłożeń: `GET /production/api/priorytety/odlozenia` →
  `{"success": true, "odlozenia": [{"stanowisko", "nazwa", "unit_key", "order_id", "numer", "product_id", "short_id",
  "powod", "notatka", "odlozono", "pracownik"}]}` (najdłużej leżące pierwsze; kafel zamówienia ma `product_id` i
  `short_id` = `null`). Modal priorytetu z K2 (`GET …/zamowienia/<id>/priorytet`) pokazuje w historii także `wyslanie`,
  `zdjecie`, `odlozenie`, `odlozenie_zamkniete`, `start_stolow`.
- **„Wyślij na stanowisko”:** `POST …/stoly/<kod>/wyslij` z `{"order_id": int}` → 200
  `{"success": true, "stanowisko", "wynik": "wyslano" | "juz_na_stole", "wyslane": [klucze], "przywrocone": [klucze],
  "juz_na_stole": [klucze]}`. Błędy: 400 `dane_niepoprawne`, 400 `stanowisko_nieznane`, 404 `zamowienie_nieznane`, 409
  `brak_na_stanowisku` („Zamówienie 5001 nie ma teraz żadnej pozycji na Krawędziach.”), 409 `stanowisko_bez_stolu`
  (Lakiernia), 409 `delivery_method_not_set` (Pakowanie bez sposobu dostawy). Na stanowisku pozycyjnym kładzie kafle
  WSZYSTKICH pozycji zamówienia w statusie stanowiska; na zamówieniowym — jeden kafel `o:<id>`, także dla zamówienia
  niekompletnego (zostaje na stole mimo niekompletności, bo źródło `biuro`).
- **„Zdejmij ze stołu”:** `POST …/stoly/<kod>/zdejmij` z `{"unit_key": "p:123" | "o:45"}` → 200
  `{"success": true, "stanowisko", "unit_key", "order_id", "product_id", "odlozony": bool}`; 404 `brak_kafla` („Tego kafla
  nie ma już na stole.”), 400 `dane_niepoprawne`. Kafel zdjęty wraca do kolejki — następny `desk` może go pobrać znowu,
  jeśli jest pierwszy w kolejce (to nie jest „blokada” kafla).
- Obie akcje działają w trybie `stary` i `stol`; wymagają `guard` (dostęp do produkcji), nie admina.

### K4b (zakładka Stanowiska, Konfiguracja, monitory)

- `GET …/stoly` → `{"success": true, "stanowiska": [{"stanowisko", "nazwa", "tryb", "jednostka", "miejsca",
  "limit_odlozen", "stol": [kafel], "odlozone": [kafel], "kolejka_dalej"}]}` — **6 stanowisk** w kolejności procesu, bez
  Lakierni. Kafel = kształt kafla z `GET /kolejka?stanowisko=` (K2) + `unit_key`, `pobrano`, `zrodlo`
  (`kolejka` | `dorobka` | `biuro` | `start`), `wyslal` (nazwa użytkownika albo `null`); odłożony dodatkowo `powod`,
  `notatka`, `odlozono`, `pracownik`. Kolejność kafli = kolejność tabletu. Same zwykłe odczyty, bez dopełniania —
  `kolejka_dalej` to ta sama liczba co na tablecie. 66 zapytań / 93 ms na kopii danych (do ewentualnej optymalizacji,
  gdyby zakładka odświeżała się często).
- **Start stołów:** `GET …/start` → `{"success": true, "stanowiska": [{"stanowisko", "nazwa", "tryb", "jednostka",
  "miejsca", "liczba", "na_stole", "kafle": [{"unit_key", "order_id", "numer", "product_id", "short_id",
  "powod": "licznik" | "zamowienie", "na_stole": bool}]}]}`; `POST …/start/przygotuj` (admin) → `{"success": true,
  "stanowiska": [{"stanowisko", "dodane", "juz_byly"}]}`, przy błędzie 500 `blad_serwera` z `stanowiska` (zrobione) i
  `nieudane` (kod). Idempotentne. „Przygotuj” nie przełącza trybu — to osobna czynność (`PUT /ustawienia`).
- **Lakiernia:** w „Stół stanowisk” wiersz bez wyboru trybu; zakładka i monitor Lakierni układają się przez
  `lista.porzadek_listy('painting', items)` i pokazują `lista.grupa_wykonczenia_json(item)`.
- Stół bywa dłuższy niż K (doróbki, `biuro`, `start`) — UI musi to pomieścić.

### K5 (przegląd P1, wyścigi MySQL)

- **Baza `priorytety_wyscigi` istnieje w stanie po próbie K3 — odtworzyć z `priorytety_podglad` przed wyścigami.**
- Plan K5 ma wszystkie tryby z listy planu K3 (`desk-desk`, `desk-zakoncz-inne`, `desk-zakoncz-to-samo-zamowienie`,
  `desk-dorobka`, `desk-panel-sposob`, `desk-utrwal`, `odloz-odloz`, `odloz-zakoncz`, `odloz-zakoncz-ten-sam-kafel`,
  `odloz-hurt`, `zakoncz-zakoncz-ten-sam-kafel`, `hurt-desk`, `gwiazdki-zakoncz`, `szczebel-przystanek`,
  `utrwal-dostawa`), z Odłóż opisanym już jako blokada własnego wiersza. **W planie K5 BRAKUJE** (do dopisania):

  | Tryb | Strona A | Strona B | Oczekiwane |
  |---|---|---|---|
  | `wyslij-desk` | panel „Wyślij” zamówienia Z na S | `GET desk` S (to samo stanowisko) | serializacja na blokadzie stanowiska; kafle Z raz (bez duplikatu `unit_key`), źródło `biuro` albo `kolejka` zależnie od kolejności; zero 1213 |
  | `wyslij-zakoncz` | „Wyślij” Z na S | ZAKOŃCZ pozycji Z na S | „Wyślij” czeka na S zamówienia albo ZAKOŃCZ czeka na „Wyślij”; nigdy kafel pozycji, która już zeszła ze stanowiska; zero 1213 bez ponowienia |
  | `wyslij-przywroc-zakoncz` | „Wyślij” przywraca odłożony kafel | ZAKOŃCZ tego samego (odłożonego) kafla | jedno z dwóch: kafel zamknięty (log `odlozenie_zamkniete`) albo przywrócony i potem zamknięty; bez `StaleDataError` / 500 |
  | `zdejmij-zakoncz`, `zdejmij-odloz` | „Zdejmij” kafla | ZAKOŃCZ / Odłóż tego samego kafla | „Zdejmij” 200 albo 404 `brak_kafla`; druga strona 200 albo 409 `nie_na_stole`; bez 500 (rozstrzygnięcie 4) |
  | `przygotuj-zakoncz` | „Przygotuj stoły” | ZAKOŃCZ kafla rozpoczętego na S | brak kafla `start` dla pozycji, która zeszła ze stanowiska; zero 1213 bez ponowienia |
  | `przygotuj-desk` | „Przygotuj stoły” | `GET desk` S | bez duplikatów; kafel ma źródło tego, kto był pierwszy |
  | `utrwal-niezatwierdzony-zapis` | wątek z niezatwierdzonym zapisem zamówienia woła `utrwal()` | — | ~5 s i `success: False`, bez wyjątku i bez 50 s (Task 0; zmierzone 5,02 s) |
  | `utrwal-utrwal` | `utrwal()` | `utrwal()` (dwa naraz) | oba kończą się, rangi spójne; 1213 najwyżej z udanym ponowieniem; żadne nie czeka dłużej niż 5 s (dziennik centrali, rozstrz. 6) |
  | `weryfikacja-cofnij-desk` | „Cofnij do pakowania” | `GET desk` Pakowania | z raportu K1 — tryb regresji; kafel wraca do kolejki, bez 1213 |
  | `wyslij-wyslij` | „Wyślij” na stanowisku A (nowy klucz na końcu zakresu A w indeksie unikalnym) | „Wyślij” na sąsiednim w indeksie stanowisku B (nowy klucz przed pierwszym wierszem B) | dopuszczalne 1213 z jednym udanym ponowieniem po jednej stronie (luka indeksu, rozstrzygnięcie 37); oba kończą 200, bez duplikatów |
  | `desk-dluga-blokada` | obca sesja trzyma `FOR UPDATE` na zamówieniu-kandydacie przez 20 s | `GET desk` z dwóch tabletów stanowiska, co 2 s | każde `desk` kończy się 200 w ≤ ~10 s (5 s na blokadzie stanowiska + 5 s na zamówieniu), stół bez dopełnienia; ZAKOŃCZ innych zamówień bez opóźnień; po próbie limit czekania każdego połączenia puli = globalny (zmierzone w K3: 5,10 s, pula `[50, 50, 50, 50]`) |
  | `wyslij-zakoncz-inne` (regresja W1) | „Wyślij” zamówienia z ≥ 3 pozycjami na S (50 serii) | ZAKOŃCZ kafla INNEGO zamówienia na S | zero 1213 i zero 500 po stronie ZAKOŃCZ — przed poprawką W1 tu wychodził cykl |

- **EXPLAIN na świeżej kopii produkcji** (zalecenie recenzenta) trzech odczytów blokujących — plan zależy od statystyk,
  więc trzeba go powtórzyć na danych o realnej wielkości: (1) `prod_station_desk WHERE station_code = ? AND unit_key = ?
  LIMIT 1 FOR UPDATE` → `const`; (2) `prod_station_desk WHERE order_id = ? ORDER BY id FOR UPDATE` → `ref` po
  `ix_prod_station_desk_order_id` (nigdy `ALL` / `index`); (3) `prod_products WHERE order_id IN (…) ORDER BY order_id, id
  LOCK IN SHARE MODE` dla każdego stanowiska i dla wszystkich aktywnych → `range` po indeksie `order_id` (w bazie z
  produkcji nazywa się `idx_order`). Wyniki z K3 w sekcji „Przegląd końcowy”. Do rozważenia: usunięcie zbędnego
  `ix_prod_station_desk_station_code` (prefiks indeksu unikalnego pokrywa odczyty po stanowisku) — bez niego
  optymalizator nie ma „taniego” planu, który blokuje wiersze całego stanowiska.
- Drobne z przeglądu końcowego przypisane K5: D2, D3, D5, D6, D8, D9, D10, D11 (tabela w „Przegląd końcowy”).

- **Błąd w planie K5, tryb `desk-dorobka`:** zakłada doróbkę wracającą na Sklejanie (`returned_to_station=gluing`).
  Doróbka wraca na Wycinanie albo Składanie (`rework_service._determine_return_station`) — scenariusz trzeba ustawić na
  `desk` Wycinania / Składania.
- Do CLAUDE.md (sekcja „Priorytety produkcji”): kontrakt blokad z początku tej sekcji; do specu: Odstępstwa 2–3
  (już zgodne ze specem), rozstrzygnięcia 9–13, 26, 31 i kształty JSON niżej.
- Sygnały na podglądzie z brokerem — niesprawdzone w K3 (brak Centrifugo).
- Znane wyjątki bez `zdejmij_nieaktualne` — sekcja „Poza zakresem”.

### K6 (kontrakt appki)

Końcówki mobilne (wszystkie pod `require_device_token`):

- **`GET /api/mobile/stations/<kod>/desk`** — dopełnia stół i zwraca go. Nagłówki: `ETag` (słaby),
  `Cache-Control: private, max-age=0` (OkHttp zawsze pyta serwer, z `If-None-Match` → 304). Błędy: 404
  `unknown_station`, 403 `station_mismatch`, 409 `stanowisko_bez_stolu` (Lakiernia), 500 `desk_failed` (ponowić z siatki).
  Działa w trybie `stary` i `stol`. **Odpowiedź może przyjść po ~5–10 s i bez dopełnienia** (200, stół z wolnym
  miejscem mimo `kolejka_dalej > 0`), gdy serwer nie doczekał się cudzej blokady — appka nie traktuje tego jak błędu;
  **zalecenie:** przy stole krótszym niż `miejsca` i `kolejka_dalej > 0` odpytywać co 30 s (jak przy pustym), nie co
  5 min — to samo domyka brak sygnału po „Cofnij do pakowania”, przepakowaniu i imporcie (D4). Limit czasu żądania w
  appce dla `desk` ≥ 15 s. Ciało:

  ```json
  {"station_code": "gluing", "jednostka": "pozycja", "miejsca": 2, "limit_odlozen": 10, "kolejka_dalej": 4,
   "stol": [{"kafel": {…pozycja jak w /orders…, "priorytet": {"gwiazdki": 2, "szczebel": "gwiazdki", "trasa": null,
                       "pozycja_w_zamowieniu": "1/4"}, "grupa_wykonczenia": null},
             "pobrano": "2026-10-05T15:09:10.189635", "zrodlo": "kolejka"}],
   "odlozone": [{"kafel": {…}, "odlozono": "2026-10-05T15:09:10.260570", "powod": "brak_materialu",
                 "notatka": "czekamy na dąb", "pracownik": "Adam Kowalski"}],
   "niekompletne": []}
  ```

  Jednostka `zamowienie` (Formatowanie, Pakowanie) — `kafel` to obiekt zamówienia z WSZYSTKIMI pozycjami (także w innych
  statusach), a `niekompletne` niesie postęp i brakujące pozycje:

  ```json
  {"jednostka": "zamowienie", …,
   "stol": [{"kafel": {"zamowienie": {"order_id": 3, "internal_order_number": "1503", "deadline": null,
                                      "priorytet": {"gwiazdki": 0, "szczebel": "gwiazdki", "trasa": null},
                                      "delivery_type": "courier", "transport": {…}, "packing_hint": {…},
                                      "client_name": …, "client_order_number": …, "baselinker_order_id": …,
                                      "delivery_city": …, "delivery_postcode": …, "order_notes": …,
                                      "order_source": …, "order_source_id": …, "order_source_name": …,
                                      "order_source_display": …},
                       "pozycje": [{…pozycja…}, {…pozycja…}]},
             "pobrano": "…", "zrodlo": "kolejka"}],
   "niekompletne": [{"kafel": {"zamowienie": {…}, "pozycje": […]}, "na_stanowisku": 1, "pozycji": 2,
                     "brakuje": [{"short_id": "4_2", "stanowisko": "gluing"}]}]}
  ```

  `priorytet` zamówienia nie ma `pozycja_w_zamowieniu`. Kolejność `stol` i `odlozone` jest kolejnością serwera — appka
  nie sortuje. **Stół bywa dłuższy niż `miejsca`** (doróbki, `biuro`, `start`) — lista przewijana; `zrodlo` ∈
  `kolejka` | `dorobka` | `biuro` | `start` (plakietki „wysłane przez biuro”, „rozpoczęte przed startem”).
- **`priorytet.szczebel`**: `"gwiazdki"` (także szczebel „bez gwiazdek”), `"trasa"`, nazwa tagu (`"po_terminie"`,
  `"blisko_terminu"`, `"rozpoczete"`), `"dorobka"` albo `null` (zamówienie jeszcze bez rangi). `trasa`:
  `{"id", "nazwa", "data"}` albo `null`.
- **`POST /api/mobile/orders/<id>/postpone`** — body `{"station_code", "zakres": "pozycja" | "zamowienie", "powod",
  "notatka"?}`, nagłówki `X-Operation-Id` i `X-Worker-Ids` jak ZAKOŃCZ; `<id>` to zawsze id POZYCJI (dla zakresu
  `zamowienie` — dowolnej pozycji zamówienia). Powody: `brak_materialu`, `awaria_maszyny`, `brak_miejsca`,
  `czeka_na_biuro`, `inne` (wymaga notatki). 200 → ciało jak `desk`, ale BEZ dopełnienia (wolne miejsce zajmie następny
  `GET desk` — appka woła go po własnym Odłóż). Błędy (żaden nie zapisuje wpisu idempotencji — można ponowić z tym samym
  `X-Operation-Id`): 409 `limit_odlozen` („Na Sklejaniu leży 1 odłożona pozycja. Zamknij którąś, zanim odłożysz
  kolejną.”), 409 `nie_na_stole`, 409 `stanowisko_bez_stolu`, 400 `powod_niepoprawny` („Przy powodzie „inne” wpisz,
  dlaczego odkładasz.”), 400 `dane_niepoprawne`, 404 `order_not_found`. Limit jest miękki (dwa jednoczesne Odłóż mogą go
  przekroczyć o 1). Odłożony kafel zostaje w `odlozone` i **można na nim zrobić ZAKOŃCZ i licznik** (bramka przepuszcza).
- **ZAKOŃCZ / licznik w trybie `stol`:** 409 `{"error": "nie_na_stole", "message": "Zamówienie 1501 nie leży na stole
  Sklejania."}` → komunikat i odświeżenie stołu. Nie zapisuje wpisu idempotencji. Przechodzą: kafel na stole, kafel
  odłożony, pozycja niekompletnego zamówienia na stanowisku zamówieniowym (sekcja „Niekompletne”), Lakiernia, stara
  appka. Odpowiedź 200 bez zmian w kształcie (dochodzi `priorytet`).
- **`GET /api/mobile/realtime-token`** → 200 `{"enabled": true, "token", "ttl_seconds", "sse_url", "channels":
  ["station:gluing"]}` (tablet Krawędzi: `["station:edges", "station:painting"]`); 503 `{"enabled": false, "reason":
  "realtime disabled" | "misconfigured"}` → appka zostaje przy odpytywaniu (30 s pusty stół, 5 min pełny), bez
  ponawiania w kółko; 404 `unknown_station` dla urządzeń spoza stanowisk produktu. Sygnał nie ma ładunku do
  interpretacji (`{"kind": "station", "station": "<kod>"}`) — po sygnale `GET desk` (Lakiernia: odświeżenie listy).
- **Kiedy przychodzi sygnał `station:<kod>`:** ZAKOŃCZ (to stanowisko + następne stanowisko pozycji + stanowiska, z
  których zszedł kafel), licznik sztuk, Odłóż, `desk`, który coś pobrał, doróbka (stanowisko odrzutu + powrotu), hurt i
  zmiany z Base. w panelu, cron osieroconych, „Wyślij”, „Zdejmij”, „Przygotuj stoły”. Zawsze po commicie; zgubiony
  sygnał nadrabia siatka odpytywania.
- **Listy dla starej appki:** `GET /stations/<kod>/orders` i `/orders/since` mają nowe pola `priorytet` i
  `grupa_wykonczenia` (dla stanowisk innych niż Lakiernia `null`); ETag list zmienił się raz
  (`KSZTALT_ODPOWIEDZI_KOLEJKI = 6`); `priority_rank` i `is_priority` bez zmian. `KSZTALT_ODPOWIEDZI_STOLU = 1` wchodzi
  do ETagu `desk`.
- **Lakiernia:** `desk` / `postpone` → 409 `stanowisko_bez_stolu` („Lakiernia pracuje z listy, bez stołu.”); lista
  `/stations/painting/orders` i delta (`all_ids`, `changed`) w kolejności serwera (grupy wykończenia), pole
  `grupa_wykonczenia: {"rodzaj", "typ_koloru", "kolor", "polysk"}` — **cztery pola** (pytanie 3); separator grupy = zmiana
  dowolnego z czterech. ZAKOŃCZ Lakierni bez bramki, niezależnie od ustawień.
- Pakowanie: zamówienie bez sposobu dostawy nie pojawia się w `desk` w ogóle (pytanie 4).

### K7 (wdrożenie i przełączenie)

- Migracja K3 (`2026-10-06-priorytety-stol-zrodlo.sql`) idzie po migracji K1; wiersze `priorytety_blokada_<S>` zakłada
  migracja K1 (bez nich `desk` loguje ostrzeżenie i samonaprawia wiersz na MySQL).
- `priorytety_min_app_version_code` = kod wersji nowej appki PRZED przełączeniem pierwszego stanowiska na `stol`; przy
  progu > 0 tablet bez heartbeatu liczy się jako stary (omija bramkę). Próg 0 = bramka dla wszystkich.
- Start: „Przygotuj stoły” po zakończeniu zmiany (admin), potem przełączenie trybu; liczby i decyzja — pytania 1–2.
  Lakiernia nie jest przełączana (6 stanowisk).
- `utrwal` ma teraz limit czekania 5 s — przy długich transakcjach na produkcji raport `success: False` w logu
  (`ostrzeżenie` z kodem 1205) zamiast wiszącego żądania; cron nadrabia. Ten sam limit ma `GET desk`: w logu
  ostrzeżenie „Mobile API desk: limit czekania na blokadę, stół bez dopełnienia” — pojedyncze wpisy są nieszkodliwe,
  seria oznacza, że coś długo trzyma blokadę zamówienia (np. otwarta ręczna transakcja w kliencie bazy).
- Realtime na produkcji: `REALTIME.enabled` i klucze jak dla agenta druku; bez nich wszystko działa na odpytywaniu.

## Poza zakresem (zauważone, nie ruszane)

1. **Hurtowe usunięcie pozycji** (`bulk-action` `delete`, tylko admin) nie woła `zdejmij_nieaktualne`: na MySQL kaskada FK
   zdejmuje kafel `p:`, ale kafel `o:` zamówienia, które straciło ostatnią pozycję na stanowisku, zostaje do następnego
   pisarza tego zamówienia albo „Zdejmij ze stołu”.
2. **Ręczna synchronizacja z `force_update`** dopisuje pozycje bez blokady zamówienia (opisane w CLAUDE.md) — kafel `o:`
   może zostać na stole zamówienia, które stało się niekompletne; uzgodni go następny pisarz zamówienia.
3. **Brak sygnału** po „Cofnij do pakowania”, przepakowaniu i imporcie nowych zamówień (rozstrzygnięcie 21, pytanie 5).
4. **`order_quantity` (licznik) nie bierze blokady zamówienia** — jak przed K3; bramka czyta stół zwykłym odczytem, więc
   licznik może przejść tuż po zdjęciu kafla przez inny tablet (skutek: sztuka doliczona do pozycji, która właśnie
   schodzi — jak dziś).
5. **Fikstury SQLite nie włączają `PRAGMA foreign_keys`** — kaskady FK (`ON DELETE CASCADE` wierszy stołu) nie są
   sprawdzane testami; pilnuje ich tylko MySQL.
6. **Plan K5, tryb `desk-dorobka`** — błędne założenie o stanowisku powrotu doróbki (sekcja K5 wyżej).
7. **`GET /stoly` — 66 zapytań** na 6 stanowisk (liczy kandydatów każdego stanowiska osobno). Wystarcza dziś; do
   optymalizacji, jeśli K4b będzie odświeżać zakładkę często.

Z listy „odłożone bez oceny” recenzenta (kod i decyzje sprzed K3 albo poza nim):

8. **`complete_task` nie sprawdza, czy pozycja jest w statusie stanowiska** — według recenzenta powtórzone ZAKOŃCZ
   w trybie `stary` cofa status pozycji (kod sprzed K3; w K3 niezweryfikowane — do sprawdzenia w K5). W trybie `stol`
   na stanowisku pozycyjnym drugie ZAKOŃCZ zatrzymuje bramka (kafla już nie ma → 409 `nie_na_stole`).
9. **Tekst alertu `realtime_service` („Centrifugo nie przyjmuje publikacji — wydruki spadły na polling”)** pojawi się
   teraz także przy nieudanej publikacji sygnału stanowiska — treść alertu myli, gdy broker padnie.
10. **Hurtowe usunięcie pozycji poza zasadą „zamówienie najpierw”** — znany wyjątek z CLAUDE.md; skutek dla stołu w p. 1
    i D2.
11. **`docs/superpowers` śledzone na gałęzi w publicznym repo** (`git add -f` wg kart kroków) — decyzja centrali przed
    scaleniem do `main` (squash bez tych plików albo z nimi).
12. **Panel: „Wyślij” / „Zdejmij” / „Przygotuj stoły” bez limitu czekania na blokady** (rozstrzygnięcie 36) i bez
    walidacji „próg wersji 0 + tryb `stol`” w `PUT /ustawienia` (rozstrzygnięcie 39) — K4b / K7.
