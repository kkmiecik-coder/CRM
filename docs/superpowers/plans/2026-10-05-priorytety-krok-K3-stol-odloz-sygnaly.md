# Priorytety produkcji, krok K3 — stół stanowiska, Odłóż, bramka ZAKOŃCZ, sygnały — plan implementacji

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Tablet dostaje ze serwera **stół** stanowiska (K kafli dopełnianych leniwie z kolejki K1), może kafel **odłożyć**
z powodem (limit na stanowisko) albo zakończyć; w trybie `stol` ZAKOŃCZ i licznik sztuk przyjmują tylko kafel ze stołu lub
odłożony (409 `nie_na_stole`), a każdy pisarz, który zabiera pozycję ze stanowiska (ZAKOŃCZ, hurt, Base., doróbka, cron),
zdejmuje jej kafel w tej samej transakcji. Po commicie idzie **sygnał** Centrifugo na kanał `station:<kod>` (także na
następne stanowisko pozycji), żeby dwa tablety stanowiska widziały to samo w sekundy, nie po 30 s.

**Architecture:** Dwa nowe serwisy w pakiecie K1 `modules/production/priorytety/services/`: `stol.py` (stan tabeli
`prod_station_desk`: `dopelnij`, `odloz`, `zdejmij_kafel`, `zdejmij_nieaktualne`, `bramka_zakoncz`) i `sygnaly.py`
(planowanie w `g` i wysyłka po commicie, wzór `print_queue_service`). `dopelnij(S)` biegnie we **własnym żądaniu**
(`GET desk`), nigdy w transakcji ZAKOŃCZ, pod blokadą wiersza `prod_config` `priorytety_blokada_<S>`, a kandydatów czyta
odczytem bieżącym w kolejności kanonicznej całej gałęzi (zamówienia rosnąco → pozycje). Zdjęcie kafla to DELETE wiersza
stołu pod blokadą zamówienia, którą pisarz już trzyma (spec 9.4). Końcówki mobilne (`desk`, `postpone`, `realtime-token`)
leżą w `routers/mobile_api.py` obok dzisiejszych; `with_idempotency` wysyła sygnały stanowisk po commicie obok sygnału
druku i dopychacza Base. Dla K4b dochodzą dwa odczyty panelu: `GET /production/api/priorytety/stoly` i `/odlozenia`.

**Tech Stack:** Flask 2 + SQLAlchemy < 2.0, MySQL 8.4 (produkcja, REPEATABLE READ) / SQLite in-memory (testy), pytest,
Centrifugo (sygnał bez ładunku, `realtime_service.publish`).

**Spec:** `docs/superpowers/specs/2026-10-04-priorytety-produkcji-design.md`: 2 (ustalenia 5–8, 13), 3.2 (kafle na
stanowisku), 5.1–5.6 (stół, pobieranie, Odłóż, sygnały, bramki, kompletność), 6.1–6.3 (kontrakt API mobilnego), 8.3–8.4,
8.6 (dane, klucze `prod_config`), 9.1–9.2 (pakiet, kontrakty funkcji `stol.*`, `sygnaly.*`), 9.4 (współbieżność), 9.5
(co zmienia znaczenie), 10 (błędy), 13 (testy, wyścigi MySQL). Symulacja:
`docs/superpowers/specs/2026-10-04-priorytety-produkcji-symulacja.md`, „Analiza wyniku” B, D p. 5–6 i „E. Decyzje”
(K=2 i „Niekompletne” do K wystarczają; ~380 zdarzeń liczników dziennie). Podręcznik centrali:
`docs/superpowers/plans/2026-10-05-priorytety-produkcji-centrala.md` (sekcje 2, 4a, 8.0, 8.3). Plan K2:
`docs/superpowers/plans/2026-10-05-priorytety-krok-K2-panel-api.md` (Doprecyzowania p. 7: `GET /kolejka?stanowisko=` to
podgląd tego, co `dopelnij` weźmie następne).

**Sesja:** lokalna (Docker: `docker compose exec app pytest`), **Fable 5.1, effort extra** (podręcznik 4a: kolejność blokad
i odczyt bieżący to błędy, których testy SQLite nie łapią). Podgląd MySQL tylko do ręcznego obejrzenia kolejności
zapytań (`general_log`) — wyścigi na dwóch sesjach wykonuje K5, ten krok je tylko **spisuje** (Task 6). Centrifugo na
podglądzie nieobowiązkowe (karta 8.3): bez brokera testujemy z `REALTIME.enabled=false`, `publish` zwraca `False`.

**Zależności:** K1 zakończony i zaliczony (migracja P1 z `prod_station_desk`, `prod_priority_log`, wiersze `prod_config`
`priorytety_*`; modele `StationDesk`, `PriorityLog`; `stale.py`; `kolejka.kandydaci_stanowiska`, `ustawienia.*`,
`drabina.szczeble`). K2 **zalecany przed** (nie wymagany): daje `widok.py` i blueprint `priorytety_panel_bp`; bez K2
Task 5 zakłada blueprint sam, wg wzoru K2 Task 1 (patrz Ryzyka).

**Gałąź:** `claude/priorytety-produkcji`. Start: `git fetch origin && git checkout claude/priorytety-produkcji && git pull
--ff-only origin claude/priorytety-produkcji`. Nigdy `main`. Numery linii w planie dotyczą `claude/logistyka-etap-4` @
`b4b4a54d` (sprzed K1/K2); jeśli linie się przesunęły, szukaj po nazwie (`grep -n`). Nazwy podane są w każdym miejscu.

## Global Constraints

- **Python 3.9:** `X | Y` tylko w plikach z `from __future__ import annotations` (jest w `rework_service.py` i
  `realtime_service.py`), bez `match`. Komentarze i docstringi po polsku; w `message` dla ludzi „Base.”.
- **Kolejność blokad całej gałęzi** (CLAUDE.md „Trasy logistyki — jeden piszący naraz”, „Deklaracje paczek”, „zamówienie
  najpierw”; spec 9.4): [pracownicy `touch_sessions`] → [blokada tras] → [blokada deklaracji paczek] → zamówienia `FOR
  UPDATE` rosnąco po id → paczki → pozycje rosnąco → zapisy. Ten krok dokłada **dwa nowe zamki** i wpisuje je w tę
  kolejność bez cyklu:
  - `priorytety_blokada_<S>` (wiersz `prod_config`, `FOR UPDATE`) bierze **wyłącznie** `stol.dopelnij(S)` we własnym
    żądaniu, jako **pierwsze polecenie nowej transakcji** (commit tuż przed, zero odczytów pomiędzy — wzór
    `_zapis_pod_blokada`, `logistics/routers/panel_api.py:72-89`). Po nim `dopelnij` czyta zamówienia `FOR SHARE` rosnąco,
    potem pozycje tych zamówień `FOR SHARE` w kolejności `(order_id, id)` — czyli tą samą drogą co hurt, Dostawa i
    `blokady_zamowien`. **Nie bierze** blokady tras, deklaracji paczek ani X na zamówieniach. Nikt, kto trzyma blokadę
    zamówienia, nie czeka na `priorytety_blokada_<S>` (ZAKOŃCZ, Odłóż, hurt, doróbka, Base., cron nie biorą jej) — dlatego
    cyklu z ZAKOŃCZ nie ma, a `dopelnij` czeka najwyżej do końca cudzego ZAKOŃCZ.
  - wiersze `prod_station_desk` (FK do `prod_orders` i `prod_products`) zapisuje się tylko **pod blokadą X zamówienia**,
    po pozycjach (DELETE/UPDATE własnego kafla w ZAKOŃCZ, Odłóż, hurt, doróbka, Base., cron) albo pod
    `priorytety_blokada_<S>` po odczytach `FOR SHARE` (INSERT w `dopelnij`). Odczyt stołu w `dopelnij` jest **zwykły**
    (migawka założona już pod blokadą), więc `dopelnij` nie trzyma blokad S na wierszach stołu i DELETE z ZAKOŃCZ na nie
    nie czeka.
  - **Blokujący odczyt wierszy stołu (`FOR UPDATE`) wyłącznie wierszy WŁASNEGO zamówienia**, pod trzymaną blokadą X tego
    zamówienia: po (`station_code`, `unit_key`) własnego kafla (bramka ZAKOŃCZ, Odłóż) albo po `order_id`
    (`zdejmij_nieaktualne`). Nikt nie blokuje wierszy stołu całego stanowiska (`WHERE station_code = S FOR UPDATE`):
    taki skan bierze rekord indeksu wtórnego przed rekordem klucza głównego, a ZAKOŃCZ/hurt innego zamówienia, który
    trzyma już rekord klucza głównego swojego wiersza (wzięty po `unit_key` albo `order_id`), przy DELETE musi oznaczyć
    do usunięcia ten sam rekord indeksu wtórnego — klasyczny cykl indeks wtórny ↔ klucz główny (MySQL 1213, także między
    dwoma tabletami jednego stanowiska). Liczniki stanowiska (limit odłożeń) czyta się zwykłym odczytem
    (Doprecyzowania p. 13).
- **Odczyt bieżący:** MySQL pracuje na REPEATABLE READ; migawka powstaje przy pierwszym zwykłym odczycie transakcji
  (w API mobilnym: `require_device_token` commituje `touch`, a potem każdy dostęp do atrybutu `g.device` to zwykły
  SELECT). Stan, na którym zapis decyduje, czyta się `with_for_update().populate_existing()` (X) albo
  `with_for_update(read=True).populate_existing()` (S), PRZED pierwszą zmianą obiektów w sesji.
- **Bez `db.session.commit()` w handlerach `with_idempotency`** (`complete`, `quantity`, `postpone`, `reject`). Wyjątek
  istniejący: `reject_product_quantity` commituje sam (`rework_service.py:337`) — nie zmieniamy. `GET desk` i
  `GET realtime-token` nie są pod `with_idempotency`; `desk` commituje sam (commit → blokada → commit), bo dopełnienie jest
  zapisem w żądaniu GET (spec 5.2).
- **Sygnały zawsze po commicie, nigdy w transakcji; `publish` nie rzuca** (spec 9.4). W handlerach `with_idempotency`
  handler tylko planuje (`sygnaly.zaplanuj`), dekorator wysyła po commicie. Z routerów panelu, `desk` i crona: po własnym
  commicie. Przy rollbacku, powtórce idempotentnej i statusie z `BLEDY_DO_PONOWIENIA` sygnał nie idzie.
- **Żadnych blokad przy HTTP do Base.** (ten krok nie dotyka wywołań Base.; `apply_baselinker_changes` zachowuje
  „Base. przed blokadami”, `sync_service.py:2651-2676`).
- Serwisy nie commitują (`stol.py`, `sygnaly.py`). Commituje router (`desk`) albo dekorator.
- Jedno ponowienie po MySQL 1213 (`blokady_zamowien.kod_mysql(e) == 1213`: rollback i cały zapis od nowa) **tylko** dla
  `dopelnij` w `GET desk` (spec 5.2, 10). ZAKOŃCZ, Odłóż, licznik — bez ponowienia (jak dotąd: tablet ponawia z kolejki).
- Migracje: K3 **nie dodaje** migracji — tabela `prod_station_desk`, `prod_priority_log` i klucze `priorytety_*` są z K1.
  Jeśli K1 nie założył wierszy `priorytety_blokada_<S>`, `stol.zablokuj_stanowisko` zakłada je `INSERT IGNORE` jak
  `routes.zablokuj_trasy` (`routes.py:175-193`, `_zaloz_wiersz_blokady` `:214-229`) — na MySQL; SQLite fail-open z WARNING.
- Testy: `docker compose exec app pytest <ścieżki> -q -p no:cacheprovider`. TDD: najpierw test, który pada. Fikstury wg
  konwencji repo: `tests/logistyka_fixtures.py` (apka z API mobilnym, `zamowienie`, `produkt`), `tests/blokady_pomocnicze.py`
  (`Zapytania`, `blokada_zamowien`, `blokada_pozycji`, `zapis`, `klauzula_blokady`), `tests/krawedzie_fixtures.py` (panel).
  SQLite pomija `FOR UPDATE`, więc kolejności pilnujemy kolejnością zapytań z klauzulą blokady dopisaną przez `Zapytania`
  (`LOCK IN SHARE MODE` dla `read=True`) i commitów (`after_commit` → znacznik `('COMMIT', None)`, wzór K2 Task 2).
- Commity: Conventional Commits po polsku, temat bez polskich znaków, jeden na Task, stopka atrybucji własnej sesji.
  `docs/superpowers/` przez `git add -f`. Push wg karty centrali (S-2). Nigdy `main`.
- `tools/print_agent` — bez zmian. UI, monitory, kontrakt appki (K6) — poza zakresem. Repo publiczne: bez sekretów.

## Review Focus

1. **`dopelnij` nie bierze blokady zamówień X i nie trzyma blokad S na stole, a ZAKOŃCZ nie czeka na blokadę stołu.**
   Kolejność: `COMMIT` → `SELECT … prod_config … FOR UPDATE` (`priorytety_blokada_<S>`) → zamówienia `LOCK IN SHARE MODE`
   rosnąco → pozycje `LOCK IN SHARE MODE` `ORDER BY order_id, id` → zwykły SELECT stołu → INSERT → `COMMIT`. Testy:
   `test_dopelnij_commit_blokada_stanowiska_zamowienia_pozycje_potem_insert`, `test_dopelnij_nie_blokuje_wierszy_stolu`,
   `test_zakoncz_nie_dotyka_blokady_stanowiska` (Task 2).
2. **Dwa `desk` naraz nie dublują kafli, a drugi widzi pełny stół** — po blokadzie stół i kandydaci są czytane od nowa:
   `test_dopelnij_po_blokadzie_widzi_cudzy_kafel` (surowy INSERT „za plecami” po migawce; Task 2),
   `test_dopelnij_ponawia_raz_po_1213`, `test_dopelnij_dwa_1213_to_500_bez_zapisow` (Task 2). UNIQUE
   (`station_code`, `unit_key`) to ostatnia zapora, nie mechanizm.
3. **Kafel schodzi ze stołu w tej samej transakcji co pozycja ze stanowiska, u każdego pisarza:** ZAKOŃCZ (także ostatnia
   pozycja kafla-zamówienia), hurt (`wstrzymane`, `anulowane`, inny status), Base. (usunięcie, nowa pozycja czyni kafel
   Formatowania niekompletnym), doróbka (oryginał `anulowane`, zamówienie niekompletne), cron osieroconych. Testy:
   `test_zakoncz_zdejmuje_kafel_pozycji`, `test_zakoncz_ostatniej_pozycji_zdejmuje_kafel_zamowienia`,
   `test_hurt_wstrzymanie_zdejmuje_kafel`, `test_base_usuniecie_pozycji_zdejmuje_kafel`,
   `test_dorobka_zdejmuje_kafel_zamowienia_na_formatowaniu`, `test_cron_osierocone_zdejmuje_kafel` (Task 1), oraz
   kolejność „zamówienie → pozycje → DELETE stołu”: `test_zdjecie_kafla_po_blokadzie_zamowienia_i_pozycji` (Task 1).
4. **Bramka ZAKOŃCZ decyduje na bieżącym stole i po `delivery_method_not_set`:** `test_bramka_409_nie_na_stole_w_trybie_stol`,
   `test_bramka_przepuszcza_odlozony`, `test_bramka_przepuszcza_pozycje_niekompletnego_zamowienia` (Doprecyzowania p. 12),
   `test_bramka_widzi_kafel_wstawiony_po_migawce`, `test_bramka_delivery_method_not_set_przed_nie_na_stole`,
   `test_bramka_stara_appka_bez_bramki_ale_zdejmuje_kafel`, `test_tryb_stary_bez_bramki`,
   `test_nie_na_stole_nie_zapisuje_wpisu_idempotencji` (Task 1).
5. **Odłóż pod blokadą zamówienia, blokuje tylko wiersz własnego kafla, limit ze zwykłego odczytu (Doprecyzowania
   p. 13), kafel zostaje na tablecie:** `test_odloz_limit_409`, `test_odloz_nie_blokuje_cudzych_wierszy_stolu`,
   `test_odloz_zablokuj_zamowienie_potem_stol`, `test_odlozony_nie_jest_pobierany_ponownie`,
   `test_odloz_nie_na_stole_409`, `test_odloz_powod_inne_bez_notatki_400` (Task 3).
6. **Sygnały po commicie, bez ładunku, na właściwe kanały, `publish` nie rzuca:** `test_zakoncz_sygnal_na_to_i_nastepne_stanowisko`,
   `test_sygnal_nie_idzie_przy_rollbacku_409`, `test_sygnal_nie_idzie_przy_powtorce_idempotentnej`,
   `test_desk_sygnal_tylko_gdy_dopelnil`, `test_publish_station_signal_nie_rzuca_gdy_broker_padl` (Task 4).
7. **Stanowisko zamówieniowe: tylko kompletne na stół, niekompletne osobno z listą brakujących, pakowanie bez sposobu
   dostawy nie wchodzi, doróbka ponad K:** `test_dopelnij_formatowanie_kompletne_na_stol_niekompletne_osobno`,
   `test_dopelnij_pakowanie_bez_sposobu_dostawy_nie_wchodzi`, `test_dopelnij_dorobka_ponad_k`,
   `test_dopelnij_kolejnosc_jak_podglad_kolejki_k2` (wejście `kandydaci_stanowiska` takie samo jak w K2) (Task 2).
8. **Stara appka nie traci nic:** `GET /stations/<kod>/orders` i `/orders/since` dostają pole `priorytet`, ETag zmienia
   się przez `KSZTALT_ODPOWIEDZI_KOLEJKI = 6`, pozostałe pola bez zmian: `test_serialize_order_ma_priorytet_i_ksztalt_6`,
   `test_lista_stanowiska_etag_zmienia_sie_po_ksztalcie` (Task 5).
9. **Lakiernia bez stołu, lista po wykończeniu (spec ustalenie 15, 3.2 „Lista Lakierni”, 5.5):** grupy (rodzaj, kolor,
   połysk) w jednym ciągu, grupy po najpilniejszej pozycji, w grupie ranga, doróbki pierwsze; pozostałe stanowiska bez
   zmian kolejności; bramka przepuszcza Lakiernię mimo `stol` w ustawieniach; `desk`/`postpone` dla `painting` → 409
   `stanowisko_bez_stolu` bez zapisu; `grupa_wykonczenia` w tym samym `KSZTALT = 6`. Testy:
   `test_lista_lakierni_grupy_wykonczenia_w_jednym_ciagu`, `test_lista_lakierni_grupy_po_najpilniejszej_pozycji`,
   `test_lista_lakierni_dorobka_pierwsza_i_jej_grupa_pierwsza`, `test_lista_innych_stanowisk_bez_zmian`,
   `test_delta_lakierni_all_ids_w_kolejnosci_listy`, `test_lista_lakierni_etag_bez_zmian_budowy_ksztalt_6`,
   `test_bramka_lakierni_otwarta_mimo_trybu_stol`, `test_desk_i_postpone_lakierni_409_bez_zapisu` (Task 5a).

## Decyzje przyjęte (ze specu i symulacji)

1. Tablet pokazuje **stół** (K kafli, domyślnie 2) i „Odłożone”, nie całą kolejkę; nie ma kroku „rozpocznij”; kafel raz
   pokazany zostaje do ZAKOŃCZ albo Odłóż niezależnie od zmian w biurze (Konrad 4.10, spec 2 p. 5, 5.1).
2. Pobieranie na stół jest **leniwe przy odczycie** (`GET desk`), poza transakcją ZAKOŃCZ (spec 5.2; uzasadnienie 9.4).
3. Odłóż dotyczy **kafla** (pozycja na pozycyjnych, zamówienie na Formatowaniu i Pakowaniu), zostaje widoczny, nie wraca do
   kolejki, limit otwartych odłożeń na stanowisko 10 (Konrad 4.10, spec 2 p. 6, 5.3, P-3, P-6).
4. Sygnał jak dla agenta druku: najpierw baza, potem sygnał bez ładunku, kanał `station:<kod>`, przy ZAKOŃCZ także na
   następne stanowisko pozycji; siatka: 30 s przy pustym stole, 5 min przy pełnym (spec 5.4, P-7; symulacja D p. 6:
   ~380 zdarzeń dziennie — brak ryzyka po stronie brokera).
5. Stanowiska zamówieniowe: kompletne na stół, niekompletne do K w osobnej sekcji z postępem i listą brakujących; ZAKOŃCZ
   pozycji niekompletnego dozwolony (spec 5.6, P-9; symulacja B: na Formatowaniu 6 z 29 niekompletnych, K=2 wystarcza).
6. Bramka ZAKOŃCZ tylko w trybie `stol`; stara appka (`last_app_version_code` < próg) dostaje zachowanie `stary`, a jej
   ZAKOŃCZ zdejmuje kafel, jeśli leżał (spec 5.5). Wszystkie stanowiska startują w `stary` (P1); przełącza K7.
7. Doróbka wchodzi na stół swojego stanowiska ponad K (spec 5.1); kafel pakowania bez sposobu dostawy nie wchodzi (5.1).
8. Decyzje 5.10 (próg 3 dni, termin przed długością, „Blisko terminu” nad „Rozpoczęte”) siedzą w `kolejka.kandydaci_stanowiska`
   z K1 — K3 ich nie liczy, tylko konsumuje.
9. **Lakiernia na stałe w `stary`, lista po wykończeniu** (Konrad 5.10, S-6 wariant C; spec ustalenie 15, 3.2 „Lista
   Lakierni”, 5.5, 6.3, 8.6): bez stołu, bez Odłóż, ZAKOŃCZ bez bramki; grupa = (`parsed_finish_type`,
   `parsed_finish_color`, `parsed_finish_gloss`), bez limitu w grupie; grupy po najpilniejszej pozycji, w grupie
   `priority_rank`, doróbki pierwsze. Kolejność zależy od kodu stanowiska (stała `STANOWISKA_BEZ_STOLU`), bez nowego
   klucza `prod_config`. Reguła kolejności **do potwierdzenia przy bramce K3** (Pytania p. 6).

## Doprecyzowania (do specu — K5 przeniesie)

1. **Blokady `dopelnij` (spec 9.4 mówi „FOR SHARE pozycje, bez blokad zamówień”).** Odczyt bieżący kandydatów idzie
   w kolejności kanonicznej: zamówienia z pozycją w statusie S (lista id ze zwykłego odczytu pod blokadą stanowiska)
   `FOR SHARE` rosnąco po id → wszystkie pozycje tych zamówień `FOR SHARE` `WHERE order_id IN (…) ORDER BY order_id, id`.
   Powód: skan pozycji po indeksie `current_status` z `FOR SHARE` zakłada blokady luk na tym indeksie, a UPDATE statusu
   z ZAKOŃCZ innego zamówienia wstawia nowy wpis indeksu w tę lukę, gdy my czekamy na jego pozycję (cykl → 1213, który
   spec przewiduje jako „rzadki”); do tego panel Logistyki pisze „zamówienie X → pozycje”, a odczyt „pozycje → zamówienie”
   byłby odwrotny. Odczyt po `order_id` nie dotyka indeksu statusu, a kolejność zamówienie → pozycje jest ta sama, co
   u wszystkich pisarzy, więc `dopelnij` tylko czeka, nigdy nie zakleszcza się z nimi (analiza w Task 2). Ponowienie po
   1213 zostaje jako zabezpieczenie. Pozycja, która weszła w status S między migawką a blokadą, czeka do następnego
   `desk` (sygnał z ZAKOŃCZ i tak go wywoła).
2. **`stol.zdejmij_nieaktualne(order)`** — jedna reguła uzgadniająca wiersze stołu zamówienia z bieżącymi statusami pozycji
   (pod blokadą X zamówienia i pozycji, którą pisarz już trzyma; wiersze stołu zamówienia czyta **odczytem bieżącym**
   `FOR UPDATE` po `order_id` — zwykły odczyt nie widziałby kafla, który `dopelnij` wstawił i zatwierdził po migawce
   żądania, a przed blokadą zamówienia, i zostawiłby na stole kafel pozycji, która już poszła dalej): kafel `p:<id>` zostaje tylko, gdy pozycja jest
   w statusie oczekiwania swojego stanowiska; kafel `o:<order_id>` zostaje tylko, gdy zamówienie jest na tym stanowisku
   **kompletne** (5.6 p. 2; jedna reguła z K1: `kolejka.kompletne_na_stanowisku`) i ma tam choć jedną pozycję. Zwraca kody stanowisk, z których coś zdjęła (do sygnałów).
   Wołają ją wszyscy pisarze z 5.1 zamiast ręcznego wybierania, co zdjąć; `zdejmij_kafel(kafel, S)` ze specu zostaje jako
   prymityw użyty przez tę regułę i przez ZAKOŃCZ odłożonego kafla (log `odlozenie_zamkniete`).
3. **Próg wersji appki:** `stary = prog > 0 and (kod is None or kod < prog)`, gdzie `prog = ustawienia.min_app_version()`,
   a `kod = g.device.last_app_version_code` (heartbeat, `mobile_api.py:1278`; tablet bez heartbeatu = stary). `prog == 0`
   (domyślnie) = brak bramki wersji, czyli w trybie `stol` bramka stołu obowiązuje każdego.
4. **`priorytet.szczebel`** przyjmuje też `"rozpoczete"` (spec 6.1 wymienia `trasa|gwiazdki|po_terminie|blisko_terminu|
   dorobka`, a 3.1 ma trzeci tag). Rodzaj szczebla pochodzi z `prod_orders.priority_rung` (pozycja) tłumaczonej mapą
   **indeks widoczny → rodzaj** (`enumerate(drabina.szczeble(), 1)`, ta sama numeracja co `drabina.pozycja_szczebla`
   i `pozycja_szczebla` w `policz`), liczoną raz na żądanie (cache w `g`, jak `routes.trasa_dla_tabletu`). **Nie**
   kolumna `PriorityRung.position` — ta numeruje też ukryte szczeble tras załadowanych (K1: renumeracja wszystkich
   wierszy), więc po pierwszym załadunku rozjechałaby się z `priority_rung`. `priority_rung` poza listą (wirtualny
   szczebel z ostrzeżeniem K1) → `szczebel: null`.
   Doróbka → `"dorobka"`. Brak rangi (zamówienie nieprzeliczone) → `szczebel: null`.
5. **`pozycja_w_zamowieniu`** = `"<i>/<n>"`, gdzie `n` to liczba niezanulowanych pozycji zamówienia, a `i` to miejsce tej
   pozycji po (`product_sequence_in_order`, `id`). Doróbka ma `i` oryginału. Listy podają `serialize_order` gotową mapę
   (`priorytety=` jak `label_numbering`); pojedyncza pozycja liczy sama.
6. **ETag `desk`:** `make_weak_etag('desk', S, max(updated_at), liczba pozycji — po wszystkich pozycjach zamówień, które
   mają pozycję w statusie S (ten sam podzbiór co `station_orders`, bo kafel-zamówienie i `niekompletne.brakuje` pokazują
   pozycje w innych statusach), max(pulled_at, postponed_at) wierszy stołu S, liczba wierszy stołu S,
   KSZTALT_ODPOWIEDZI_STOLU)`, liczony **po** dopełnieniu i commicie. Nagłówki: `cached_json(..., max_age=0)` /
   `not_modified(etag, max_age=0)` (p. 14). `KSZTALT_ODPOWIEDZI_STOLU = 1` (osobna stała w `mobile_api.py`, komentarz jak przy
   `KSZTALT_ODPOWIEDZI_KOLEJKI`).
7. **`postpone`:** `zakres` musi zgadzać się z `ustawienia.jednostka(S)` (400 `dane_niepoprawne` z `message`); dla
   `zakres: "zamowienie"` `<id>` w ścieżce to **id pozycji** zamówienia (jak w `complete`, bo appka zna id pozycji),
   a kafel to `o:<order_id>`. 400 `powod_niepoprawny` także dla `inne` bez niepustej notatki (≤ 255 znaków).
8. **Sygnały dodatkowe:** doróbka publikuje też na stanowisko powrotu (`returned_to_station`), bo nowa doróbka wchodzi
   tam ponad K; `GET desk` publikuje tylko, gdy coś dopełnił (drugi tablet dociąga ten sam stół); zdjęcie kafli przez
   hurt, Base. i cron publikuje na każde stanowisko, z którego zdjęto (po commicie routera/crona).
9. **`kolejka_dalej`** = liczba kafli kandydatów poza stołem i odłożonymi (dla jednostki `zamowienie`: kompletnych).
10. **Odczyty panelu dla K4b:** `GET /production/api/priorytety/stoly` → stół i odłożone każdego z 7 stanowisk;
    `GET /production/api/priorytety/odlozenia` → otwarte odłożenia (kształty w Task 5). Bez blokad, bez dopełniania.
11. **Log:** `odlozenie` przy Odłóż; `odlozenie_zamkniete` przy ZAKOŃCZ kafla odłożonego (`note` = powód odłożenia,
    `old_value` = ISO `postponed_at`, czas leżenia liczy raport). Zdjęcie odłożonego kafla przez hurt/Base./doróbkę/cron
    nie loguje — odłożenie znika razem z kaflem (spec 5.3).
12. **Bramka a „Niekompletne” (spec 5.6 p. 2, decyzja p. 5 wyżej):** na stanowisku z jednostką `zamowienie` bramka
    przepuszcza ZAKOŃCZ i licznik pozycji zamówienia, które na S **nie jest kompletne** (`not kompletne_na(order, S)`,
    decyzja na pozycjach z blokady zamówienia) — takie zamówienie nie ma wiersza stołu (sekcja „Niekompletne” liczy się
    przy `desk`, nie jest zapisana), a spec każe pozwolić formatować to, co przyszło. Przepuszcza każde niekompletne
    zamówienie, nie tylko K pokazanych: policzenie kolejności „Niekompletnych” w ZAKOŃCZ wymagałoby odczytu innych
    zamówień w transakcji trzymającej X (cykl, 5.2). Kompletne zamówienie bez wiersza stołu → 409 `nie_na_stole`.
13. **Limit odłożeń ze zwykłego odczytu (zmiana wobec spec 9.2 „limit odczytem bieżącym stołu stanowiska”):** Odłóż
    blokuje tylko wiersz własnego kafla (`kafel_pozycji(..., do_zapisu=True)`), a liczbę otwartych odłożeń stanowiska
    czyta zwykłym `SELECT COUNT(*) … WHERE station_code = S AND postponed_at IS NOT NULL` (migawka żądania). Odczyt
    bieżący wierszy całego stanowiska to cykl blokad z ZAKOŃCZ/hurtem innych zamówień (Global Constraints, indeks wtórny
    ↔ klucz główny), a handler `with_idempotency` nie może zacząć nowej transakcji (commit), żeby migawka powstała pod
    blokadą. Koszt: dwa Odłóż na jednym stanowisku w tej samej chwili mogą przekroczyć limit o 1 (limit to bariera
    dyscypliny, nie niezmiennik danych). Do potwierdzenia przez Konrada (Pytania p. 4).
14. **`desk` bez buforowania po stronie tabletu:** `Cache-Control: private, max-age=0` + ETag (OkHttp Cache pyta wtedy
    serwer za każdym razem, z `If-None-Match`). Domyślne `max_age=15` z `cached_json` oznaczałoby, że `GET desk` po
    sygnale przez 15 s wraca z pamięci tabletu — bez dopełnienia i bez zmian z drugiego tabletu (spec 5.2, 5.4).
15. **Doróbka na stanowisku zamówieniowym:** „doróbka ponad K” (spec 5.1) dla jednostki `zamowienie` = **kompletne**
    zamówienie, którego pozycja-doróbka czeka w statusie S, wchodzi na stół ponad K; niekompletne zostaje w
    „Niekompletnych” (kompletność ma pierwszeństwo — kafla-zamówienia nie da się puścić dalej po kawałku).
16. **Kafel-zamówienie:** `pozycje` = wszystkie pozycje zamówienia (jak `station_orders`: także w innych statusach, appka
    pokazuje postęp i plakietki sąsiednich stanowisk), w kolejności (`product_sequence_in_order`, `id`).
17. **Kolejność `stol` i `odlozone` (spec 3.2 „doróbki zawsze pierwsze, po `created_at`”):** jedna kolejność z
    `stol.kafle(S)` dla odpowiedzi `desk`, odpowiedzi `postpone` i panelowego `GET /stoly`; appka nie sortuje (dwa tablety
    stanowiska pokazują to samo, K6 przepisuje ten klucz do kontraktu jako „ORDER BY z kodu”). Stół: (doróbka ? 0 : 1,
    `created_at` doróbki, `pulled_at`, `id`) — doróbka wchodzi ponad K później niż reszta, więc po samym `pulled_at`/`id`
    byłaby ostatnia. Odłożone: (`postponed_at`, `id`) — najdłużej leżące pierwsze, tak samo jak `GET /odlozenia`.

## Mapa plików

| Plik | Task | Rola |
|---|---|---|
| `modules/production/priorytety/services/stol.py` (nowy) | 1, 2, 3 | `zablokuj_stanowisko`, `kafle`, `zdejmij_kafel`, `zdejmij_nieaktualne`, `bramka_zakoncz`, `dopelnij`, `odloz`, `BladStolu` |
| `modules/production/priorytety/services/sygnaly.py` (nowy) | 4 | `zaplanuj(*kody)`, `wyslij()`, `nastepne_stanowisko(item)` |
| `modules/production/priorytety/stale.py` (K1; dopisać, jeśli brak) | 1, 3 | `POWODY_ODLOZENIA` (K1 ma), `klucz_blokady(S)` (K1 ma), `KAFEL_POZYCJA/KAFEL_ZAMOWIENIE` |
| `modules/production/services/realtime_service.py` | 4 | `CHANNEL_STATION = 'station:{}'`, `publish_station_signal(kod)` |
| `modules/production/services/mobile_api_service.py` | 1, 4, 5 | `with_idempotency` (sygnały stanowisk po commicie), `serialize_order` (`priorytet`), `get_station_queue_delta` |
| `modules/production/routers/mobile_api.py` | 1–5, 5a | `complete`/`quantity`/`reject` (bramka, zdjęcie, sygnały), nowe `desk`, `postpone`, `realtime-token`, `KSZTALT_ODPOWIEDZI_KOLEJKI = 6`, `KSZTALT_ODPOWIEDZI_STOLU` |
| `modules/production/services/rework_service.py` | 1, 4 | `zdejmij_nieaktualne` po zapisach doróbki; wynik stanowisk do sygnału |
| `modules/production/services/sync_service.py` (`apply_baselinker_changes`) | 1 | `zdejmij_nieaktualne` przed commitem |
| `modules/production/routers/api/products_api.py` (`_zapisz_zmiane_statusu`, `bulk_action`, `admin_apply_baselinker_changes`) | 1, 4 | `zdejmij_nieaktualne` w pętli hurtu; sygnały po commicie |
| `modules/production/logistics/services/delivery.py` (`przenies_osierocone_z_logistyki`) | 1 | `zdejmij_nieaktualne`; zwrot stanowisk |
| `modules/production/logistics/routers/cron_api.py` | 4 | sygnał po commicie fazy 1 |
| `modules/production/priorytety/routers/panel_api.py` (K2) | 5 | `GET /stoly`, `GET /odlozenia` |
| `modules/production/priorytety/services/widok.py` (K2) | 5 | `stoly_panelu()`, `odlozenia_panelu()` |
| `tests/test_priorytety_stol.py` (nowy) | 1–3 | stół, zdjęcia, bramka, Odłóż |
| `tests/test_priorytety_mobile.py` (nowy) | 2, 3, 5 | końcówki `desk`, `postpone`, `realtime-token`, listy, panel `stoly`/`odlozenia` |
| `tests/test_priorytety_sygnaly.py` (nowy) | 4 | planowanie, wysyłka, kanały, `publish` |
| `modules/production/priorytety/services/lista.py` (nowy) | 5a | `porzadek_listy`, `klucz_grupy_wykonczenia`, `grupa_wykonczenia_json` — porządek listy Lakierni (czyste funkcje) |
| `modules/production/priorytety/stale.py` (K1) | 5a | `STANOWISKA_BEZ_STOLU = ('painting',)` |
| `tests/test_priorytety_lista_lakierni.py` (nowy) | 5a | porządek listy, delta, bramka i `desk`/`postpone` Lakierni |
| `docs/superpowers/plans/raporty/2026-10-05-priorytety-krok-K3-raport.md` (nowy) | 6 | raport kroku z listą wyścigów dla K5 |

Usunięte: nic. Zmienione fragmenty istniejących funkcji wymienia każdy Task w „Stan obecny”.

---

## Zakres dopisany z karty K3 (centrala, 5.10) — Taski sesji kroku

Karta kroku rozszerza plan (dziennik centrali, rozstrzygnięcia 7, 11, 12; spec w wersji z 5.10 wieczór: ustalenia
15–18, sekcje 5.1, 5.7, 5.8, 6.1, 8.3, 8.4, 9.2, 9.4, 10). **Gdy plan i spec się różnią, wygrywa spec.** Dopisane Taski:
0 (K1-poprawka-1), 0a (migracja K3), 5b („Wyślij”/„Zdejmij”), 5c (start stołów) oraz dopisek w Tasku 2 (źródło kafla).
Kolejność wykonania: 0 → 0a → 1 → 2 → 3 → 4 → 5 → 5a → 5b → 5c → 6. Środowisko wg karty (`docker compose -p
priorytety run --rm --no-deps app pytest …`; MySQL: baza `priorytety_podglad`).

Zmiany w Taskach planu wynikające ze specu (obowiązują zamiast litery planu):
- **Lakiernia (Task 5a):** klucz grupy wykończenia = (`parsed_finish_type`, `parsed_finish_color_type`,
  `parsed_finish_color`, `parsed_finish_gloss` tylko dla lakierowanych) — spec 3.2 p. 1, decyzja Konrada „jak w appce”.
  Stała stanowisk bez stołu jest już w K2: `ustawienia.STANOWISKA_BEZ_STOLU` (słownik kod → nazwa) — bez drugiej
  stałej w `stale.py`. `PUT /ustawienia` dla `painting.tryb = stol` zrobione w K2.
- **Stół (Task 2):** dopełnianie liczy WSZYSTKIE kafle leżące na stole (bez odłożonych), także doróbki, wysłane
  przez biuro i startowe (spec 5.1) — plan liczył bez doróbek. Kolejność na stole: doróbki, wysłane przez biuro,
  startowe, pobrane, w każdej grupie po czasie wejścia (`pulled_at`, `id`) — zastępuje Doprecyzowania p. 17 w części
  o stole. `zrodlo` w JSON `desk` (spec 6.1).
- **Wejście `kandydaci_stanowiska`:** `statusy_zamowien` to pary `(product_id, status)`, `jednostka =
  ustawienia.jednostka(S)`, wejście buduje `widok.wejscie_kandydatow` (raport K2, „Co następny krok musi wiedzieć”).
- **Końcówki panelu:** `test_zestaw_koncowek` → 14 (8 z K2 + `stoly`, `odlozenia`, `stoly/<S>/wyslij`,
  `stoly/<S>/zdejmij`, `start`, `start/przygotuj`).

---

### Task 0: K1-poprawka-1 — limit czekania `kolejka.utrwal` na blokadę (I2 z raportu K1)

**Files:** `modules/production/priorytety/services/kolejka.py`, `tests/test_priorytety_kolejnosc_zapisow.py`.

**Problem (raport K1, I2; dziennik, rozstrzygnięcia 7 i 12):** własna sesja `utrwal` to drugie połączenie tego
samego wątku. Gdy `db.session` wołającego trzyma niezatwierdzony zapis zamówienia (ręczna synchronizacja z
`force_update`), `utrwal` czeka na tę blokadę do limitu serwera (50 s), a gunicorn ubija żądanie po 30 s.

**Rozwiązanie (wariant (a)):** własna sesja `utrwal` pracuje na JEDNYM, przypiętym połączeniu (`db.engine.connect()`
+ sesja z `bind=połączenie`, `binds={}`), na którym przed pierwszym zapytaniem idzie
`SET SESSION innodb_lock_wait_timeout = 5` (tylko MySQL). Po pracy — także po błędzie — ustawienie wraca
(`SET SESSION innodb_lock_wait_timeout = DEFAULT`, czyli wartość globalna serwera) i połączenie wraca do puli; gdy
przywrócenie się nie uda, połączenie jest unieważniane (`invalidate`) i nie wraca do puli z krótkim limitem.
Przekroczony limit to MySQL 1205: rollback własnej sesji, `success: False`, **bez ponowienia** (ponawiamy tylko 1213),
bez wyjątku na zewnątrz; rangi nadrabia cron.

- [x] **Step 1: Testy, które padną** (`tests/test_priorytety_kolejnosc_zapisow.py`, SQLite — szpieg na funkcji
  wysyłającej ustawienie, bo SQLite go nie zna): `test_utrwal_ustawia_limit_czekania_na_wlasnym_polaczeniu`
  (ustawienie idzie na połączeniu własnej sesji PRZED pierwszym zapytaniem, przywrócenie PO ostatnim, połączenie
  zamknięte), `test_utrwal_trzyma_jedno_polaczenie_przez_wszystkie_przebiegi` (zapis + przebieg kontrolny na tym
  samym połączeniu), `test_utrwal_1205_bez_ponowienia_i_z_przywroceniem_limitu`,
  `test_utrwal_po_1213_druga_sesja_tez_ma_limit`, `test_utrwal_nieudane_przywrocenie_uniewaznia_polaczenie`,
  `test_utrwal_bez_limitu_poza_mysql` (SQLite: żadnego `SET SESSION`).
- [x] **Step 2: Testy padają.** **Step 3: Implementacja** w `kolejka.py` (`nowa_sesja`, `_ogranicz_czekanie`,
  `_zamknij`; komentarz nad częścią z bazą). **Step 4: Testy przechodzą** — cały plik + `tests/test_priorytety_*.py`.
- [x] **Step 5: MySQL (`priorytety_podglad`), dwie sesje:** (1) druga sesja trzyma `FOR UPDATE` na zamówieniu,
  którego rangę `utrwal` musi zmienić → `utrwal()` kończy `success: False` po ok. 5 s; (2) ten sam wątek:
  `db.session` z niezatwierdzonym zapisem zamówienia → `utrwal()` jak wyżej (dotąd 50 s); (3) po zwolnieniu blokady
  `utrwal()` przechodzi; (4) połączenia puli mają `@@innodb_lock_wait_timeout` = wartość globalna. Wynik i czasy do
  raportu („K1-poprawka-1”).
- [x] **Step 6: Commit** `fix(priorytety): limit czekania utrwal na blokade zamowienia`

---

### Task 0a: Migracja K3 — źródło kafla i akcje logu (spec 8.3, 8.4)

**Files:** `migrations/2026-10-06-priorytety-stol-zrodlo.sql` (nowy), `modules/production/priorytety/models.py`,
`modules/production/priorytety/stale.py`, `tests/test_migracja_priorytety_stol.py` (nowy).

- [x] **Step 1: Testy, które padną:** kształt nowej migracji (runner rozpoznaje nazwę, sortuje się po migracji K1,
  oba `ADD COLUMN` osłonięte `information_schema` + `PREPARE/EXECUTE`, `MODIFY` enuma idempotentny sam z siebie (wzór migracji logistyki 2026-10-02), lista akcji w SQL
  == `stale.AKCJE_LOGU`); model `StationDesk` ma `zrodlo` (NOT NULL, domyślnie `kolejka`) i `sent_by_user_id`;
  `stale.ZRODLA_KAFLA == ('kolejka', 'dorobka', 'biuro', 'start')`; `stale.AKCJE_LOGU` ma `wyslanie`, `zdjecie`,
  `start_stolow`.
- [x] **Step 2: Testy padają.** **Step 3: Migracja, model, stałe.** **Step 4: Testy przechodzą.**
- [x] **Step 5: MySQL:** migracja ×2 na `priorytety_podglad` (`flask migrate`; drugi raz ręcznie po usunięciu wpisu
  `schema_migrations` — plik wykonuje się ponownie bez błędu i bez zmian), `SHOW COLUMNS` do raportu.
- [x] **Step 6: Commit** `feat(priorytety): migracja K3 - zrodlo kafla i akcje logu stolu`

---

### Task 1: `stol.py` — zdjęcie kafla u pisarzy i bramka ZAKOŃCZ

**Files:**
- Create: `modules/production/priorytety/services/stol.py`, `tests/test_priorytety_stol.py`
- Modify: `modules/production/priorytety/stale.py` (K1), `modules/production/routers/mobile_api.py:425-541`
  (`order_complete`, `order_quantity`), `modules/production/services/rework_service.py:188-330`,
  `modules/production/services/sync_service.py:2677-2862`, `modules/production/routers/api/products_api.py:1420-1503`,
  `modules/production/logistics/services/delivery.py:559-589`

**Stan obecny (ugruntowanie, `b4b4a54d`):**
- ZAKOŃCZ: `mobile_api.order_complete` `:425-495`. Kolejność: `_resolve_station_code` → `_resolve_workers` (:147-180,
  `touch_sessions`) → `blokady_zamowien.zablokuj_zamowienie_pozycji(order_id)` (:462; X zamówienie → X pozycje po
  `order_id`, `blokady_zamowien.py:58-118`) → bramka `delivery_method_not_set` dla pakowania (:467-476) →
  `mark_order_complete` (:479; `mobile_api_service.py:1260-1316`: `set_quantity_done`, `complete_task`,
  `schedule_after_station_complete`) → `serialize_order` (:495). `complete_task` (`models.py:633-725`) przestawia
  `current_status` i woła `odnotuj_wejscie_do_pakowania`/`po_spakowaniu`; blok `:714-719` (ranga doróbki) **usuwa K1**.
- Licznik: `order_quantity` `:498-541` — `ProductionItem.query.get(order_id)` (:519, **zwykły odczyt, bez blokady**;
  CLAUDE.md: pisarz pozycji bez blokady zamówienia, jeden flush) → `update_order_quantity` (`mobile_api_service.py:1319-1340`).
  Bramka stołu ma tu czytać stół **bez** blokady zamówienia (zwykły odczyt wiersza `p:<id>` wystarcza do odmowy; licznik
  nie zmienia stołu), żeby nie zmieniać klasy tego pisarza.
- Doróbka: `rework_service.reject_product_quantity` `:96-364`: blokada tras (:147) → `zablokuj_zamowienie_pozycji`
  (:162) → oryginał `quantity -= n`, `'anulowane'` przy 0 (:191-193) → nowa `ProductionProduct` (:211-287), `flush`
  (:299), `lock_priority(rank=1)` (:302, **K1 zamienia na `priority_rank = 0`**) → `zablokuj_pozycje(original.order)`
  + `uniewaznij_etapy` (:326-328) → `commit` (:337). Zwraca `(original, rework, log_entry)`; `returned_to_station` w
  `log_entry.returned_to_station`.
- Zmiany z Base.: `sync_service.apply_baselinker_changes` `:2602-2880`: Base. przed blokadami (:2651), `commit` →
  `zablokuj_trasy` → `zablokuj_zamowienie` (:2669-2676) → usunięcia `db.session.delete(product)` (:2679-2690) →
  aktualizacje → nowe pozycje `czeka_na_wyciecie` (:2739-2821) → `zablokuj_pozycje` + `przelicz_zamkniecie` (:2859-2861)
  → `commit` (:2868). Router: `products_api.admin_apply_baselinker_changes` `:1245-1320` (`bl_sync.wyslij_zaplanowane()`
  po wyniku, `:1308`).
- Hurt: `products_api._zapisz_zmiane_statusu` `:1420-1502`: `_zablokuj_zamowienia_i_pozycje` (:1444; blokada tras →
  zamówienia rosnąco → pozycje per zamówienie, `:1325-1367`) → pętla `product.current_status = nowy_status` (:1471) →
  per zamówienie `uniewaznij_etapy`, `przelicz_zamkniecie` (:1491-1500) → `commit` (:1502). Ponowienie 1213 w `bulk_action`
  (:1599-1607). **Jedyni pisarze `anulowane`/`wstrzymane` w kodzie:** ten hurt i doróbka (`rework_service.py:193`,
  oryginał przy ilości 0) — grep `current_status = 'anulowane'|'wstrzymane'` po `modules/production` nie znajduje innych;
  „anulowanie” ze spec 5.1 to te dwie ścieżki.
- Cron: `delivery.przenies_osierocone_z_logistyki` `:559-589`: `zablokuj_zamowienia` → `zablokuj_pozycje` → status
  `czeka_na_pakowanie` (:581-585) → `odnotuj_wejscie_do_pakowania`, `przelicz_zamkniecie` (:586-588); zwraca liczbę.
  Router `cron_api.cron` (`cron_api.py:25-80`), commit po fazie 1 (:48).
- Model stołu `StationDesk` (K1, spec 8.4): `station_code`, `order_id` FK, `product_id` FK NULL, `unit_key` UNIQUE
  z `station_code`, `pulled_at`, `postponed_*`. Model logu `PriorityLog` (K1, spec 8.3).
- Urządzenie: `ProductionDevice.last_app_version_code` (`models.py:1161`), ustawiane w heartbeacie (`mobile_api.py:1278`).
  Tryb stanowiska i próg: `ustawienia.tryb(S)`, `ustawienia.min_app_version()` (K1, spec 9.1).
- `blokady_pomocnicze.zapis` (`tests/blokady_pomocnicze.py:93-102`) nie zna `prod_station_desk` — dopisujemy
  `'DELETE FROM prod_station_desk'`, `'INSERT INTO prod_station_desk'`, `'UPDATE prod_station_desk'` (INSERT ma FK do
  `prod_orders`, czyli blokadę S na zamówieniu, jak `prod_logistics_log`).

**Interfaces:**
- Produces (`stol.py`, bez commitów):
  - `class BladStolu(Exception)`: `kod` (`nie_na_stole`, `limit_odlozen`, `powod_niepoprawny`, `dane_niepoprawne`),
    `komunikat` (po polsku), `status` (409/400).
  - `KAFEL_POZYCJA = 'p'`, `KAFEL_ZAMOWIENIE = 'o'`; `unit_key(kafel) -> str` (`p:<product_id>` / `o:<order_id>`).
  - `kafle(station_code) -> List[StationDesk]`: wiersze stołu stanowiska (na stole i odłożone), **zawsze zwykły odczyt**
    (`dopelnij`, odpowiedzi `desk`/`postpone`, panel). Wariantu blokującego nie ma (Global Constraints: nikt nie blokuje
    wierszy stołu całego stanowiska). **Kolejność ustalona (Doprecyzowania p. 17):** wiersze na stole (`postponed_at IS
    NULL`) po kluczu (doróbka ? 0 : 1, `created_at` doróbki, `pulled_at`, `id`), odłożone po (`postponed_at`, `id`);
    zwraca na stole, potem odłożone. Doróbka: kafel `p:` — pozycja z `original_product_id IS NOT NULL`, `created_at`
    tej pozycji; kafel `o:` — zamówienie z pozycją-doróbką w statusie S, `created_at` najstarszej z nich (Doprecyzowania
    p. 15). Dla nie-doróbki składnik `created_at` pusty (stały). Sortowanie w Pythonie po zwykłym odczycie (pozycje
    i zamówienia kafli zwykłym SELECT bez klauzuli blokady); `dopelnij` korzysta z `kafle` tylko jako zbioru `unit_key`,
    więc kolejność go nie dotyczy.
  - `kafel_pozycji(item, station_code, *, do_zapisu=False) -> Optional[StationDesk]`: wiersz `p:<id>` albo, gdy jednostka
    stanowiska to `zamowienie`, `o:<order_id>`, po (`station_code`, `unit_key`). `do_zapisu=True` →
    `with_for_update().populate_existing()` (odczyt bieżący; wołać tylko pod blokadą X zamówienia tej pozycji).
  - `zdejmij_kafel(kafel, station_code, *, teraz=None, worker_id=None, device_id=None, zamkniecie_odlozenia=False) -> bool`
    (spec 9.2): `kafel` to `ProductionProduct` albo `ProductionOrder`; DELETE wiersza stołu (`db.session.delete` wiersza
    wczytanego `with_for_update()`, żeby test kolejności widział DELETE po blokadach); gdy wiersz był odłożony i
    `zamkniecie_odlozenia`, dopisuje `PriorityLog(action='odlozenie_zamkniete', …)` (Doprecyzowania p. 11). Zwraca, czy
    coś usunęła. **Warunek wstępny:** wołający trzyma X na zamówieniu i jego pozycjach.
  - `zdejmij_nieaktualne(order, *, teraz=None, zamkniecie_odlozen=False, worker_id=None, device_id=None) -> Set[str]`
    (Doprecyzowania p. 2): najpierw `db.session.flush()` (UPDATE pozycji wołającego idzie przed blokadą wierszy stołu
    w kolejności zapytań), potem wiersze stołu zamówienia **odczytem bieżącym** `with_for_update().populate_existing()`
    po `order_id` (zwykły odczyt nie widziałby kafla wstawionego przez `dopelnij` po migawce żądania — `dopelnij` pisze
    pod blokadą S zamówienia, nie X wołającego), kontra `order.products` (kolekcja z `zablokuj_pozycje`, odczyt
    bieżący); każdy nieaktualny wiersz → `zdejmij_kafel(...)`. `zamkniecie_odlozen=True` (tylko ZAKOŃCZ) loguje
    `odlozenie_zamkniete` dla każdego zdejmowanego wiersza z `postponed_at` (Doprecyzowania p. 11). Zwraca kody stanowisk,
    z których coś zdjęła.
  - `bramka_zakoncz(item, station_code, device, *, do_zapisu=False) -> None` (spec 9.2, 5.5): (Task 5a dokłada na
    początku: `S in STANOWISKA_BEZ_STOLU` → przepuść); `ustawienia.tryb(S) !=
    'stol'` → przepuść; `stara_appka(device)` (Doprecyzowania p. 3) → przepuść; `kafel_pozycji(item, S,
    do_zapisu=do_zapisu)` istnieje (na stole albo odłożony) → przepuść; jednostka `zamowienie` i `not kompletne_na(
    item.order, S)` → przepuść (Doprecyzowania p. 12); inaczej `raise BladStolu('nie_na_stole', 'Zamówienie {numer} nie
    leży na stole {nazwa stanowiska}.', 409)`. Nazwa z `station_catalog.station_label`. ZAKOŃCZ woła z `do_zapisu=True`
    (pod blokadą X zamówienia — odczyt bieżący własnego wiersza), licznik z `do_zapisu=False` (bez blokady zamówienia;
    zwykły odczyt wystarcza do odmowy, a blokada wiersza stołu przed UPDATE pozycji odwróciłaby kolejność wobec
    ZAKOŃCZ: stół → pozycja kontra pozycja → stół).
  - `stara_appka(device) -> bool`.
- Consumes (K1): `StationDesk`, `PriorityLog`, `ustawienia.tryb`, `ustawienia.jednostka`, `ustawienia.min_app_version`,
  `stale.STATUSY_PRODUKCJI`, **`kolejka.kompletne_na_stanowisku(statusy, stanowisko)`** (jedna reguła kompletności dla
  `kandydaci_stanowiska`, podglądu K2 i stołu — K1: `ETAP_STATUSU`, pomija `anulowane`/`wstrzymane`, pozycje dalej
  liczą się jako zrobione); `station_catalog.STATION_PENDING_STATUS`, `STATION_ORDER`. Bez własnej mapy etapów
  w `stol.py` (rozjechałaby się z K1: K1 liczy `czeka_na_logistyke` jak pakowanie).
- Produces (przepięcia):
  - `mobile_api.order_complete`: po `zablokuj_zamowienie_pozycji` i po bramce `delivery_method_not_set`:
    `stol.bramka_zakoncz(item, station_code, g.device, do_zapisu=True)` (`except BladStolu as e: return jsonify({'error':
    e.kod, 'message': e.komunikat}), e.status`); po `mark_order_complete`: `zdjete = stol.zdejmij_nieaktualne(item.order,
    zamkniecie_odlozen=True, worker_id=worker_ids[0] if worker_ids else None, device_id=g.device.id)` — jedna droga,
    bez osobnego odczytu „czy odłożony” przed `mark_order_complete` (log `odlozenie_zamkniete` tylko dla wiersza, który
    naprawdę znika: kafel-zamówienie z drugą pozycją na S zostaje). Sygnały — Task 4.
  - `mobile_api.order_quantity`: `stol.bramka_zakoncz(item, station_code, g.device)` po `ProductionItem.query.get`
    (zwykły odczyt stołu; bez blokady zamówienia — klasa pisarza bez zmian; „niekompletne” z `item.order.products`
    zwykłym odczytem, odmowa/przepuszczenie na migawce — licznik nie zmienia stołu).
  - `rework_service.reject_product_quantity`: po `zablokuj_pozycje(original.order)` i `uniewaznij_etapy` (:326-328),
    przed `zdejmij_z_trasy_w_drodze`: `stanowiska = stol.zdejmij_nieaktualne(original.order)`; wynik do sygnału trzeba
    wynieść z funkcji — dopisz atrybut `log_entry.zdjete_stanowiska` **nie** (model); zamiast tego funkcja planuje sygnał
    sama przez `sygnaly.zaplanuj(*stanowiska)` (Task 4; `g` może nie istnieć w testach jednostkowych → `has_request_context`).
  - `sync_service.apply_baselinker_changes`: po `zablokuj_pozycje(zamowienie)` + `przelicz_zamkniecie` (:2859-2861), przed
    `commit`: `g_stanowiska = stol.zdejmij_nieaktualne(zamowienie)`; do `result['zdjete_stanowiska'] = sorted(...)`
    (router publikuje po wyniku, Task 4). Usunięta pozycja (`db.session.delete(product)`) — jej wiersz stołu na SQLite
    nie zniknie kaskadą (brak `PRAGMA foreign_keys`), więc `zdejmij_nieaktualne` usuwa wiersze stołu, których
    `product_id` nie ma już w `order.products` (odczyt bieżący po `order_id` po autoflushu nie zawiera usuniętej).
  - `products_api._zapisz_zmiane_statusu`: w pętli per zamówienie (:1491-1500) po `przelicz_zamkniecie`:
    `zdjete |= stol.zdejmij_nieaktualne(zamowienie)`; `results['zdjete_stanowiska'] = sorted(zdjete)`.
  - `delivery.przenies_osierocone_z_logistyki`: po `przelicz_zamkniecie(order, teraz)` (:588) `stol.zdejmij_nieaktualne(order)`;
    import lokalny w funkcji (pakiet `priorytety` importuje logistykę — unikamy cyklu). Zwrot bez zmian (liczba);
    stanowiska do sygnału zbiera `cron_api` z `g` (`sygnaly.zaplanuj` wewnątrz, `has_request_context` jest w cronie).

**Kolejność blokad (CLAUDE.md „zamówienie najpierw”; spec 9.4 „ZAKOŃCZ/Odłóż: kolejność dzisiejsza, DELETE wiersza stołu
własnego kafla w tej samej transakcji”):**
```
ZAKOŃCZ (order_complete):
  touch_sessions (pracownicy)                       # _resolve_workers, jak dziś
  X zamówienie → X pozycje (zablokuj_zamowienie_pozycji)
  bramka delivery_method_not_set                    # na bieżącym override_delivery_method
  bramka_zakoncz: tryb, wersja, SELECT prod_station_desk WHERE station_code=? AND unit_key=? FOR UPDATE
                                                    # odczyt bieżący własnego kafla (tylko w trybie stol); zwykły
                                                    # odczyt widziałby migawkę sprzed blokady zamówienia
  mark_order_complete → UPDATE pozycji (+ zamówienie w po_spakowaniu)
  zdejmij_nieaktualne → flush → SELECT prod_station_desk WHERE order_id=? FOR UPDATE → DELETE
  (commit w with_idempotency) → sygnały
Hurt / Base. / doróbka / cron: [blokada tras] → X zamówienia rosnąco → X pozycje → zapisy → zdejmij_nieaktualne → commit
```
Wiersz stołu to dziecko FK zamówienia już trzymanego X, więc DELETE nie wprowadza nowej kolejności. Z `dopelnij` (Task 2)
nie ma cyklu: `dopelnij` czyta stół zwykłym odczytem (bez S na wierszach), a jego INSERT w lukę indeksu `order_id`
stołu (blokada następnego klucza z `SELECT … WHERE order_id=? FOR UPDATE`) najwyżej czeka na commit pisarza — pisarz
nie czeka na nic, co trzyma `dopelnij` (S tylko na zamówieniach i pozycjach kandydatów; zamówienie pisarza, jeśli jest
wśród kandydatów, `dopelnij` blokuje S dopiero po commicie pisarza albo pisarz czeka na nie, zanim weźmie cokolwiek).

- [x] **Step 0: Punkt wyjścia i weryfikacja K1/K2**
1. `git log -1 --oneline` zgodny z kartą centrali; inaczej STOP.
2. Przeczytaj raporty K1 (i K2, jeśli jest): „Co następny krok musi wiedzieć”, „Odstępstwa”.
3. `grep -n "def kandydaci_stanowiska\|def tryb\|def miejsca\|def jednostka\|def limit\|def min_app_version\|def szczeble\|class StationDesk\|class PriorityLog\|POWODY_ODLOZENIA\|STATUSY_PRODUKCJI" -r modules/production/priorytety`
   — zapisz do raportu ścieżka:linia, sygnatury, typy zwracane. Kluczowe: **kształt wyniku `kandydaci_stanowiska(S,
   pozycje, statusy_zamowien)`** (lista kafli w kolejności; dla jednostki `zamowienie` podział na kompletne i niekompletne
   z listą brakujących) i to, czego oczekuje na wejściu (`pozycje` jako obiekty ORM czy słowniki; `statusy_zamowien`
   jako `{order_id: [statusy]}`). Jeśli funkcja oczekuje słowników, `stol.py` buduje je z obiektów z odczytu bieżącego —
   nie kopiuj algorytmu.
4. Decyzje: inna nazwa przy tej samej semantyce → nazwa z kodu, wpis w „Odstępstwa”; **brak `kandydaci_stanowiska`
   albo brak podziału kompletne/niekompletne** → STOP przed Task 2 (Task 1 i 3–4 bez niego się da), meldunek do centrali.
   `ustawienia.*` przez pamięć podręczną procesu (K2 Task 5 miało to sprawdzić) → tryb stanowiska przełączony
   w Konfiguracji dotarłby do bramki po godzinie; odnotuj, nie naprawiaj bez zgody.
5. Pełny pakiet: `docker compose exec app pytest tests/ -q -p no:cacheprovider` → liczby `passed/skipped/failed` jako
   punkt wyjścia; zero `failed` to warunek startu.

- [x] **Step 1: Testy, które padną** — `tests/test_priorytety_stol.py`, fikstury z `tests/logistyka_fixtures.py`
  (`app`, `client`, `zamowienie`, `produkt`; `StationDesk`, `PriorityLog`, `PriorityRung` dopisał do `TABLES` już K1 —
  sprawdź; pomocniki z `tests/priorytety_fixtures.py` K1: `ustaw(klucz, wartosc, typ)`, `czyste_ustawienia` — pamięć
  podręczna `config_service` żyje 60 min między testami, więc każdy plik piszący `prod_config` używa `czyste_ustawienia`).
  Pomocniki w pliku: `_naglowki(stanowisko)` jak `tests/test_blokady_zamowien.py` (urządzenie + token +
  `X-Operation-Id`), `_tryb(S, 'stol')` i `_prog_wersji(n)` przez `priorytety_fixtures.ustaw`, `_kafel(S, item|order, odlozony=False)` wstawiający wiersz stołu, `_zakoncz`, `_licznik`.
  Testy:
  - `test_zdejmij_nieaktualne_widzi_kafel_wstawiony_po_migawce` (zwykły odczyt stołu w teście zakłada migawkę, surowy
    INSERT wiersza `p:` „za plecami”, pozycja przestawiona dalej → `zdejmij_nieaktualne` usuwa wiersz; zapytanie stołu
    ma klauzulę `FOR UPDATE` w `Zapytania`), `test_bramka_widzi_kafel_wstawiony_po_migawce` (ZAKOŃCZ w trybie `stol`,
    wiersz wstawiony surowo po migawce → 200, nie 409).
  - `test_zdejmij_kafel_usuwa_wiersz_i_loguje_zamkniecie_odlozenia`, `test_zdejmij_nieaktualne_zostawia_kafel_na_stanowisku`
    (pozycja dalej w statusie S → wiersz zostaje), `test_zdejmij_nieaktualne_usuwa_kafel_zamowienia_gdy_niekompletne`
    (doróbka cofnęła pozycję przed Formatowanie → `o:` z Formatowania znika; `p:` na Sklejaniu dla doróbki nie istnieje).
  - Review Focus 3: `test_zakoncz_zdejmuje_kafel_pozycji`, `test_zakoncz_ostatniej_pozycji_zdejmuje_kafel_zamowienia`
    (dwie pozycje na Formatowaniu, kafel `o:`; po pierwszym ZAKOŃCZ wiersz zostaje, po drugim znika),
    `test_zakoncz_odlozonego_loguje_odlozenie_zamkniete`, `test_hurt_wstrzymanie_zdejmuje_kafel` (`POST
    /production/api/products/bulk-action` na fiksturze `krawedzie_fixtures.app` **albo** bezpośrednio
    `_zapisz_zmiane_statusu(ids, 'wstrzymane', user_id)` na `logistyka_fixtures.app` — wybierz drugą drogę, jeśli
    rejestracja `api_bp` w fiksturze logistyki jest kłopotliwa; zapisz wybór w raporcie), `test_base_usuniecie_pozycji_zdejmuje_kafel`
    (`apply_baselinker_changes` z `products_to_remove`, `get_order_from_baselinker` niepotrzebny — brak `products_to_add`),
    `test_base_nowa_pozycja_zdejmuje_kafel_zamowienia_na_pakowaniu` (monkeypatch `get_order_from_baselinker` jak
    `tests/test_blokady_dorobka_base.py`), `test_dorobka_zdejmuje_kafel_zamowienia_na_formatowaniu`,
    `test_dorobka_oryginal_anulowany_zdejmuje_kafel_pozycji`, `test_cron_osierocone_zdejmuje_kafel`
    (pozycja `czeka_na_logistyke` z kaflem `p:` na… — uwaga: taki kafel nie powinien istnieć; test: zamówienie z kaflem
    `o:` na Pakowaniu, które po przeniesieniu staje się kompletne → wiersz zostaje; i odwrotnie kafel `p:` na Krawędziach
    pozycji przeniesionej → znika).
  - `test_zdjecie_kafla_po_blokadzie_zamowienia_i_pozycji`: `Zapytania`; indeksy `blokada_zamowien` < `blokada_pozycji` <
    (tryb `stol`: `SELECT … prod_station_desk … unit_key … FOR UPDATE` bramki) < pierwszy `UPDATE prod_products` <
    `SELECT … prod_station_desk … order_id … FOR UPDATE` < `DELETE FROM prod_station_desk`; żaden SELECT stołu nie ma
    `station_code` bez `unit_key` z klauzulą blokady.
  - Review Focus 4: `test_bramka_409_nie_na_stole_w_trybie_stol` (`message` zawiera numer zamówienia i nazwę stanowiska,
    status pozycji bez zmian), `test_bramka_przepuszcza_kafel_na_stole`, `test_bramka_przepuszcza_odlozony`,
    `test_bramka_przepuszcza_pozycje_niekompletnego_zamowienia` (Formatowanie, tryb `stol`, zamówienie X 1/4 bez
    wiersza stołu → ZAKOŃCZ 200 i licznik 200; kompletne Y bez wiersza → 409),
    `test_bramka_delivery_method_not_set_przed_nie_na_stole` (pakowanie, bez sposobu, bez kafla → 409
    `delivery_method_not_set`), `test_bramka_stara_appka_bez_bramki_ale_zdejmuje_kafel` (próg 100, urządzenie z
    `last_app_version_code=50` i kaflem na stole → 200, wiersz znika; bez kafla → 200), `test_bramka_prog_zero_to_brak_bramki_wersji`
    (próg 0, urządzenie bez heartbeatu, tryb `stol`, bez kafla → 409), `test_tryb_stary_bez_bramki`,
    `test_licznik_409_nie_na_stole_w_trybie_stol`, `test_licznik_nie_bierze_blokady_zamowienia` (`Zapytania`: brak
    `blokada_zamowien`, jak dziś), `test_nie_na_stole_nie_zapisuje_wpisu_idempotencji` (`ProcessedMobileOperation.query.count()
    == 0`, wzór `tests/test_mobile_api_ponowienie_403.py:85-103`).
- [x] **Step 2: Testy padają** (import `stol` → `ImportError`).
- [x] **Step 3: `stol.py`** wg „Interfaces”. Docstring modułu: kolejność blokad z ramki wyżej i odesłanie do spec 5.1,
  5.5, 9.4. `zdejmij_nieaktualne` i bramka liczą kompletność jedną funkcją `kompletne_na(order, station_code) -> bool`
  (eksport) = cienka nakładka `kolejka.kompletne_na_stanowisku(tuple(p.current_status for p in order.products), S)` z K1
  — bez własnej mapy etapów. Importy w `stol.py`: `station_catalog`, nie `mobile_api_service` (ten importuje `stol`
  w Task 5 — cykl); odwrotna mapa status → stanowisko z `STATION_PENDING_STATUS`.
- [x] **Step 4: Przepięcia** w sześciu miejscach z „Produces (przepięcia)”. W `order_complete` bramka z
  `do_zapisu=True` przed `mark_order_complete` i `zdejmij_nieaktualne(..., zamkniecie_odlozen=True)` po nim; komentarz
  przy bramce: dlaczego po `delivery_method_not_set` (spec 5.5) i dlaczego odczyt bieżący własnego wiersza (migawka). W `rework_service` i `sync_service` import `stol` lokalnie w funkcji
  (pakiet `priorytety` może importować `rework_service`? — nie powinien; sprawdź `grep -rn "import" modules/production/priorytety/services/*.py`,
  żeby nie zrobić cyklu).
- [x] **Step 5: `tests/blokady_pomocnicze.py`** — rozszerz `zapis` o `prod_station_desk` (docstring: FK do `prod_orders`).
  Uruchom `tests/test_blokady_zamowien.py tests/test_blokady_dorobka_base.py tests/test_produkty_masowa_zmiana_statusu.py`
  — mają zostać zielone (DELETE stołu idzie po dotychczasowym pierwszym zapisie, więc indeksy się nie zmieniają).
- [x] **Step 6: Testy przechodzą** (cały `tests/test_priorytety_stol.py` + pliki ze Step 5). **Step 7: Commit**
`feat(priorytety): stol stanowiska - zdjecie kafla u pisarzy i bramka ZAKONCZ`

---

### Task 2: `stol.dopelnij(S)` i `GET /api/mobile/stations/<kod>/desk`

**Files:**
- Modify: `modules/production/priorytety/services/stol.py`, `modules/production/routers/mobile_api.py` (nowa końcówka
  obok `station_orders` `:242`), `tests/test_priorytety_stol.py`
- Create: `tests/test_priorytety_mobile.py`

**Stan obecny (ugruntowanie):**
- Wzór blokady wiersza `prod_config` z samonaprawą: `routes.zablokuj_trasy` `routes.py:146-204`, `_zaloz_wiersz_blokady`
  `:214-229`, `paczki.zablokuj_deklaracje` `paczki.py:266-306`. Migracja wiersza: `2026-09-30-logistyka-paczki-blokada.sql`.
- Wzór „commit, potem blokada”: `panel_api._zapis_pod_blokada` (`logistics/routers/panel_api.py:72-89`).
- Wzór ponowienia po 1213 w routerze: `products_api.bulk_action` `:1599-1607`; `kod_mysql` `blokady_zamowien.py:121-133`.
- Lista stanowiska dla tabletu (ETag, serializer, numeracja etykiet, podpowiedzi paczek): `station_orders` `:242-326`
  (`make_weak_etag('orders', …, KSZTALT_ODPOWIEDZI_KOLEJKI)`, `compute_label_offsets`, `podpowiedzi_zamowien`,
  `cached_json`). Pomocniki cache: `modules/production/utils/cache.py:17-66`.
- Kolejność kafli: `kolejka.kandydaci_stanowiska(S, pozycje, statusy_zamowien)` (K1, spec 9.2; wzorzec w
  `scripts/symulacja_priorytetow.py:304-378` — `kolejka_pozycji`, `kolejka_zamowien` z `kompletne`/`brakuje`).
  Kafle poza stołem i odłożeniami filtruje wołający (K2 Doprecyzowania p. 7 robi to samo w `widok.py`).
- Sposób dostawy: `sposoby.normalizuj(order.override_delivery_method) is None` = nie ustawiono (`mobile_api.py:471`).
- Ustawienia: `ustawienia.miejsca(S)` (K, 1–5), `ustawienia.jednostka(S)` (`pozycja`/`zamowienie`),
  `ustawienia.limit(S)`.

**Interfaces:**
- Produces (`stol.py`):
  - Klucz wiersza blokady: `stale.klucz_blokady(S)` / `ustawienia.klucz_blokady(S)` z K1 (`'priorytety_blokada_<S>'`;
    wiersze zakłada migracja K1). Własna stała tylko, gdy K1 jej nie dał (Odstępstwa).
  - `zablokuj_stanowisko(station_code) -> Optional[ProductionConfig]`: `FOR UPDATE` wiersza `priorytety_blokada_<S>`;
    brak wiersza na MySQL → `INSERT IGNORE` + ponowny odczyt + WARNING; na innych bazach WARNING raz na proces (fail-open).
    **Pierwsze polecenie transakcji** — wołający commituje tuż przed.
  - `dopelnij(station_code, *, teraz=None) -> Dopelnienie` (spec 9.2), gdzie `Dopelnienie` to `namedtuple('Dopelnienie',
    'pobrane kolejka_dalej niekompletne')`: `pobrane` — lista nowych `StationDesk` (dodane do sesji, **bez commita**),
    `kolejka_dalej` — int, `niekompletne` — lista `(order, na_stanowisku, pozycji, brakuje)` do K sztuk (tylko jednostka
    `zamowienie`; liczona z tego samego odczytu bieżącego, żeby router nie czytał drugi raz).
  - `odczyt_biezacy_kandydatow(station_code) -> Tuple[List[ProductionOrder], List[ProductionProduct]]`: lista id zamówień
    z pozycją w statusie S (zwykły odczyt — **pierwszy zwykły odczyt transakcji, już pod blokadą**) → zamówienia
    `with_for_update(read=True).populate_existing()` rosnąco (`WHERE prod_orders.id IN (…) ORDER BY prod_orders.id`) →
    pozycje `WHERE prod_products.order_id IN (…) ORDER BY prod_products.order_id, prod_products.id`
    `with_for_update(read=True).populate_existing()`; `set_committed_value` kolekcji jak `blokady_zamowien.zablokuj_pozycje`
    (silne referencje: `order.products`, `p.order`).
  - `Dopelnienie` wylicza: doróbki w statusie S poza stołem → **wszystkie** na stół (ponad K, spec 5.1; dla jednostki
    `zamowienie` — Doprecyzowania p. 15); potem kandydaci z `kolejka.kandydaci_stanowiska` bez kafli ze stołu
    i odłożonych (`unit_key`), dla pakowania bez zamówień bez sposobu dostawy, dla jednostki `zamowienie` tylko kompletne
    (`kompletne_na`), aż stół (wiersze z `postponed_at IS NULL`, doróbki nie liczą się do K) ma K kafli.
  - **Wejście `kandydaci_stanowiska` — to samo co w podglądzie K2** (`widok.kolejka_stanowiska`, plan K2 Task 4
    i Doprecyzowania p. 13 K2; inaczej `GET /kolejka?stanowisko=` rozjedzie się ze stołem): `PozycjaStanowiska` (K1)
    z pozycji w statusie S odczytu bieżącego, bez kafli ze stołu i odłożonych; `rung`/`rank`/`gwiazdki` z kolumn
    zamówienia (odczyt S), `termin` = `kolejka.termin_zamowienia(...)`, `na_trasie` z przystanku na trasie
    `robocza`/`zatwierdzona` (zwykły odczyt `RouteStop`+`Route` dla zamówień kandydatów — tylko do kolejności),
    gatunek/klasa z `ProductionConfiguration` (`species`, `wood_class`), wymiary z `parsed_*_cm`;
    `statusy_zamowien = {order_id: tuple(statusy wszystkich pozycji)}`; **`szczebel_rozpoczete =
    drabina.pozycja_tagu('rozpoczete')`** (K1 Doprecyzowania: bez tego tag „Rozpoczęte” nie podnosi pozycji na stole).
    Jeśli K2 wystawił budowanie wejścia jako funkcję — wołaj ją (z listami z odczytu bieżącego), jeśli jest wewnątrz
    `kolejka_stanowiska` — wydziel ją do funkcji w `widok.py` bez zmiany zachowania (Odstępstwa) i użyj w obu miejscach.
    Bez kopii.
  - `ustawienia.miejsca/jednostka/limit(S)` czyta `dopelnij` **po** `zablokuj_stanowisko` (`config_service` przy
    chybionej pamięci podręcznej robi zwykły SELECT — między commitem a blokadą nie wolno nic czytać).
- Produces (HTTP) `GET /api/mobile/stations/<kod>/desk` (`require_device_token`, bez `with_idempotency`), odpowiedź jak
  spec 6.1 (`station_code`, `jednostka`, `miejsca`, `stol`, `odlozone`, `niekompletne`, `limit_odlozen`, `kolejka_dalej`;
  `kafel` = `serialize_order(..., station_code=S, label_numbering=…, packing_hints=…, priorytety=…)` dla jednostki
  `pozycja`, a `{zamowienie: {...}, pozycje: [...]}` dla `zamowienie`, gdzie `zamowienie` to pola zamówienia z
  `serialize_order` pierwszej pozycji: `internal_order_number`, `baselinker_order_id`, `client_name`, `client_order_number`,
  `delivery_type`, `transport`, `packing_hint`, `delivery_city`, `delivery_postcode`, `order_notes`, `order_source*`,
  `priorytet`, plus `order_id`, `deadline` (termin zamówienia)), a `pozycje` wg Doprecyzowań p. 16. `stol` i `odlozone`
  w kolejności z `stol.kafle(S)` (Doprecyzowania p. 17; ta sama w odpowiedzi `postpone` i panelowym `GET /stoly`). ETag wg Doprecyzowań
  p. 6 (304 przez `not_modified(etag, max_age=0)`, 200 przez `cached_json(payload, etag, max_age=0)` — p. 14).
  Błędy: 404 `unknown_station`, 403 `station_mismatch` (jak w `station_orders`), 500 `desk_failed` po drugim 1213.
  Kolejność w handlerze:
  ```
  resolve_station_code → znane_kody / device_can_access_station      # zwykłe odczyty g.device (migawka, zaraz ją kończymy)
  def _dopelnij():
      db.session.commit()                 # koniec migawki; następne polecenie to blokada
      wynik = stol.dopelnij(S)            # FOR UPDATE prod_config → S zamówienia → S pozycje → zwykły SELECT stołu → INSERT
      db.session.commit()
      return wynik
  try: wynik = _dopelnij()
  except OperationalError as e: if kod_mysql(e) != 1213: raise; rollback; log WARNING; wynik = _dopelnij()
  if wynik.pobrane: realtime_service.publish_station_signal(S)        # po commicie; Task 4 przenosi do sygnaly.wyslij
  stol = stol.kafle(S)  # zwykły odczyt po commicie = świeża migawka; serializacja; ETag; cached_json / not_modified
  ```
  Drugie 1213 i każdy inny wyjątek → rollback, `logger.error`, 500 `desk_failed` bez treści wyjątku.

**Kolejność blokad `dopelnij` i dlaczego poza ZAKOŃCZ (spec 5.2, 9.4; Doprecyzowania p. 1):**
```
COMMIT                                   # migawka żądania (touch urządzenia, g.device) zakończona
SELECT prod_config WHERE config_key='priorytety_blokada_<S>' FOR UPDATE      # jeden pobierający na stanowisko
SELECT DISTINCT order_id FROM prod_products WHERE current_status = <S>       # zwykły odczyt → migawka POD blokadą
SELECT prod_orders WHERE id IN (…) ORDER BY id LOCK IN SHARE MODE            # bieżące gwiazdki, ranga, sposób dostawy
SELECT prod_products WHERE order_id IN (…) ORDER BY order_id, id LOCK IN SHARE MODE   # bieżące statusy, skład zamówień
SELECT prod_station_desk WHERE station_code = <S>                           # zwykły odczyt (migawka spod blokady) — bez S
INSERT prod_station_desk …                                                   # FK → S na zamówieniu i pozycji (już trzymane)
COMMIT → sygnał
```
Dlaczego nie w transakcji ZAKOŃCZ: ZAKOŃCZ trzyma X na zamówieniu A i jego pozycjach; dopełnienie czyta pozycje innych
zamówień (B, C); drugi tablet w ZAKOŃCZ zamówienia B trzymałby X na B i chciał czytać A → cykl (1213). Osobne żądanie
nie trzyma żadnej blokady zamówienia, gdy czeka na blokadę stanowiska.
Dlaczego zamówienia → pozycje, a nie pozycje po statusie: ZAKOŃCZ, hurt, Dostawa, panel i doróbka biorą zamówienie przed
pozycjami. `dopelnij` czekający na S zamówienia A (X trzyma ZAKOŃCZ) nie ma jeszcze żadnej pozycji, a ZAKOŃCZ nie czeka
na nic, co `dopelnij` trzyma (stół czytany bez blokad). ZAKOŃCZ blokuje wiersze stołu własnego zamówienia po `unit_key`
(rekord) i po `order_id` (indeks niejednoznaczny → blokady następnego klucza z luką); INSERT `dopelnij` trafiający
w tę lukę czeka na commit ZAKOŃCZ — czekanie, nie cykl, bo ZAKOŃCZ niczego od `dopelnij` nie chce. Doróbka: X zamówienie → X pozycje → INSERT pozycji w lukę `order_id`
— `dopelnij` blokuje luki `order_id` tylko po zamówieniach, które zdążył przeczytać, a na zamówienie doróbki czeka
**zanim** sięgnie po jego pozycje; INSERT doróbki trafia w lukę za ostatnią pozycją jej zamówienia, której `dopelnij`
jeszcze nie zablokował. `utrwal()` z K1 (X zamówienia rosnąco → X pozycje **tych** zamówień) idzie tą samą drogą;
warunek: `utrwal` nie zapisuje pozycji zamówienia, którego nie zablokował — Task 6 dopisuje to do listy sprawdzeń K5.
Pozostałe rzadkie 1213 (np. ręczna synchronizacja z `force_update` bez blokady zamówienia, CLAUDE.md) łapie jedno
ponowienie w routerze.

**Dopisane z karty K3 — źródło kafla (spec 5.1, 6.1, 8.4; w tym samym commicie co Task 2):**
- `dopelnij` zapisuje `zrodlo='kolejka'`, a doróbkom `zrodlo='dorobka'`; liczy do K wszystkie kafle leżące na stole
  w bieżącej jednostce (bez odłożonych), niezależnie od źródła — z kolejki dobiera dopiero, gdy jest ich mniej niż K.
- `stol.kafle(S)`: na stole w kolejności źródeł `dorobka`, `biuro`, `start`, `kolejka`, w grupie po (`pulled_at`,
  `id`); odłożone po (`postponed_at`, `id`). Wiersze z kluczem innej jednostki niż bieżąca pomija.
- JSON `desk`: `stol[].zrodlo`.
- Testy: `test_dopelnij_zapisuje_zrodlo_kolejka_i_dorobka`, `test_dopelnij_liczy_do_k_kafle_kazdego_zrodla`
  (K=2, na stole doróbka i kafel `biuro` → nic z kolejki), `test_kafle_kolejnosc_zrodel_na_stole`,
  `test_desk_stol_ma_zrodlo`, `test_dopelnij_nie_liczy_wiersza_innej_jednostki`.

- [x] **Step 1: Testy, które padną**
  `tests/test_priorytety_stol.py` (serwis, bezpośrednio na sesji):
  - `test_dopelnij_do_k_w_kolejnosci_kandydatow` (szpieg `kolejka.kandydaci_stanowiska` zwraca ustaloną kolejność;
    K=2 → dwa pierwsze kafle, `kolejka_dalej` = reszta, `pobrane` mają `pulled_at`, `postponed_at is None`).
  - `test_dopelnij_pomija_kafle_na_stole_i_odlozone` (odłożony nie wraca na stół: Review Focus 5, część serwisowa).
  - `test_dopelnij_dorobka_ponad_k` (K=1, stół pełny, doróbka w statusie S → trzeci wiersz; dwie doróbki → obie).
  - `test_dopelnij_pakowanie_bez_sposobu_dostawy_nie_wchodzi` (zamówienie bez `override_delivery_method` pomijane,
    następne wchodzi; `kolejka_dalej` liczy je? — **nie**, liczy tylko kandydatów zdolnych wejść; zapisz w docstringu).
  - `test_dopelnij_formatowanie_kompletne_na_stol_niekompletne_osobno` (przykład X/Y ze spec 5.6: X 1/4 na Formatowaniu →
    `niekompletne` z `na_stanowisku=1`, `pozycji=4`, `brakuje` = 3 pozycje ze `stanowisko='gluing'`; kompletne Y na stole),
    `test_dopelnij_ostatnia_pozycja_czyni_zamowienie_kompletnym` (po ZAKOŃCZ ostatniej na Sklejaniu kolejne `dopelnij`
    wstawia `o:`), `test_dopelnij_pozycja_omijajaca_formatowanie_nie_jest_brakujaca` (`cut_to_size=False`, pozycja już
    `czeka_na_pakowanie` — dla Formatowania liczy się jako „dalej”).
  - Review Focus 1: `test_dopelnij_commit_blokada_stanowiska_zamowienia_pozycje_potem_insert` (`Zapytania` + znacznik
    `COMMIT`; po `COMMIT` pierwsze zapytanie to `SELECT … FROM prod_config … FOR UPDATE` z parametrem
    `priorytety_blokada_gluing`; potem `blokada_zamowien`-podobny predykat z końcówką `LOCK IN SHARE MODE` (dopisz do
    `blokady_pomocnicze`: `odczyt_biezacy_zamowien(sql)`, `odczyt_biezacy_pozycji_wielu_zamowien(sql)` —
    `WHERE prod_products.order_id IN` + `ORDER BY prod_products.order_id, prod_products.id` + `LOCK IN SHARE MODE`);
    potem `SELECT … prod_station_desk` **bez** klauzuli blokady; potem `INSERT INTO prod_station_desk`),
    `test_dopelnij_nie_blokuje_wierszy_stolu` (żaden SELECT `prod_station_desk` nie kończy się klauzulą blokady),
    `test_dopelnij_bez_blokady_tras_i_paczek` (brak parametrów `logistyka_trasy_blokada`, `logistyka_paczki_blokada`),
    `test_zakoncz_nie_dotyka_blokady_stanowiska` (ZAKOŃCZ: brak parametru `priorytety_blokada_%`),
    `test_dopelnij_ustawienia_po_blokadzie` (cache `config_service` wyczyszczony: pierwszy SELECT `prod_config` z kluczem
    `priorytety_stol_%`/`priorytety_jednostka_%` po blokadzie stanowiska).
  - Zgodność z K2 i K1: `test_dopelnij_kolejnosc_jak_podglad_kolejki_k2` (te same dane: kolejność `pobrane` +
    `kolejka_dalej` = kolejność `kafle` z `widok.kolejka_stanowiska(S)` wywołanego przed dopełnieniem),
    `test_dopelnij_przekazuje_szczebel_rozpoczete` (szpieg na `kandydaci_stanowiska`: `szczebel_rozpoczete ==
    drabina.pozycja_tagu('rozpoczete')`), `test_dopelnij_formatowanie_dorobka_kompletna_ponad_k` (Doprecyzowania p. 15).
  - Review Focus 2: `test_dopelnij_po_blokadzie_widzi_cudzy_kafel` — przelotka na `stol.zablokuj_stanowisko`: po
    prawdziwym wywołaniu surowy INSERT wiersza stołu „drugiego tabletu” dla kandydata nr 1; `dopelnij` wstawia kandydata
    nr 2 (nie dubluje nr 1; stół = 2 kafle). `test_dopelnij_widzi_biezacy_status_pozycji` (surowy UPDATE statusu
    kandydata nr 1 w tej samej przelotce → kandydat nie wchodzi).
  `tests/test_priorytety_mobile.py` (klient HTTP, `logistyka_fixtures.app`):
  - `test_desk_ksztalt_odpowiedzi_pozycja` (pola ze spec 6.1; `kafel` ma wszystkie pola `serialize_order` + `priorytet`),
    `test_desk_ksztalt_odpowiedzi_zamowienie` (Formatowanie: `kafel.zamowienie`, `kafel.pozycje`, `niekompletne` z
    `brakuje[].short_id/stanowisko`), `test_desk_dopelnia_i_commituje` (po żądaniu wiersze w bazie),
    `test_desk_etag_304_i_zmiana_po_odlozeniu`, `test_desk_cache_control_max_age_0` (200 i 304: `Cache-Control:
    private, max-age=0`), `test_desk_kafel_zamowienia_ma_wszystkie_pozycje`,
    `test_desk_stol_doroba_pierwsza_potem_kolejnosc_pobrania` (dwa kafle pobrane, potem doróbka ponad K → w `stol`
    doróbka pierwsza, dalej po `pulled_at`; dwie doróbki po `created_at`; Doprecyzowania p. 17),
    `test_desk_odlozone_po_czasie_odlozenia` (dwa odłożenia w odwrotnej kolejności id → `odlozone` po `postponed_at`), `test_desk_urzadzenie_lakierni_widzi_krawedzie` (`/stations/edges/desk`
    z urządzenia `painting` → 200; grupa `STATION_GROUPS` symetryczna — Lakiernia sama stołu nie ma, Task 5a),
    `test_desk_station_mismatch_403`, `test_desk_unknown_station_404`,
    `test_desk_w_trybie_stary_dziala` (spec 6.3), `test_desk_ponawia_raz_po_1213`, `test_desk_dwa_1213_to_500_bez_zapisow`
    (wzór `_blad_mysql`/`_commit_z_bledami` z `tests/test_priorytety_kolejnosc_zapisow.py:163-183` — po K2 skopiowany
    już do `test_priorytety_panel_api.py`; skopiuj lokalnie), `test_desk_commit_przed_blokada_bez_odczytu_pomiedzy`
    (między pierwszym `COMMIT` handlera a `SELECT prod_config … FOR UPDATE` nie ma żadnego `SELECT`).
- [x] **Step 2: Testy padają.**
- [x] **Step 3: `dopelnij` i odczyt bieżący** w `stol.py` wg „Interfaces”; `kompletne_na` z Task 1 dla jednostki
  `zamowienie`; `brakuje` = `Kandydaci.niekompletne[*].brakuje` z K1 (pozycje, przez które zamówienie nie jest kompletne)
  uzupełnione o `short_id` z odczytu bieżącego i kod stanowiska z odwrotnej mapy `station_catalog.STATION_PENDING_STATUS`
  (nie z `mobile_api_service.STATUS_TO_STATION` — cykl importów, Task 1 Step 3).
- [x] **Step 4: Końcówka `desk`** w `mobile_api.py` wg pseudokodu; stała `KSZTALT_ODPOWIEDZI_STOLU = 1` obok
  `KSZTALT_ODPOWIEDZI_KOLEJKI` (`:137`) z komentarzem „PODBIJ przy zmianie zestawu pól”. Serializacja kafli po commicie,
  `compute_label_offsets` i `podpowiedzi_zamowien` raz dla wszystkich pozycji odpowiedzi (jak `station_orders` `:306-310`).
  Pole `priorytet` dochodzi w Task 5 — do tego czasu `serialize_order` bez niego, test kształtu z `xfail(strict=True)`
  na samym polu `priorytet` (zdejmuje Task 5).
- [x] **Step 5: Testy przechodzą** (oba pliki). **Step 6: Commit**
`feat(priorytety): dopelnianie stolu stanowiska i koncowka desk`

---

### Task 3: Odłóż — `stol.odloz` i `POST /api/mobile/orders/<id>/postpone`

**Files:**
- Modify: `modules/production/priorytety/services/stol.py`, `modules/production/priorytety/stale.py`
  (`POWODY_ODLOZENIA`, jeśli K1 nie dał), `modules/production/routers/mobile_api.py` (nowa końcówka obok `order_complete`),
  `tests/test_priorytety_stol.py`, `tests/test_priorytety_mobile.py`

**Stan obecny (ugruntowanie):** wzór handlera mutującego z `X-Worker-Ids` i `with_idempotency(retryable_statuses=
BLEDY_DO_PONOWIENIA)`: `order_complete` `:425-495` (`_resolve_station_code` → `_resolve_workers` → blokada → zapis →
`serialize_order`). `BLEDY_DO_PONOWIENIA = {400, 403, 404, 409}` (`:122`) — 409 `limit_odlozen` i `nie_na_stole` są w nim
już przez kod statusu; test potwierdza brak wpisu idempotencji. Pracownik do logu: `worker_ids[0]` jak w doróbce
(`rework_service.py:313`). Urządzenie: `g.device.id` (`prod_devices.id`, INT — `PriorityLog.device_id INT`).

**Interfaces:**
- Produces (`stale.py`): `POWODY_ODLOZENIA = ('brak_materialu', 'awaria_maszyny', 'brak_miejsca', 'czeka_na_biuro', 'inne')`.
- Produces (`stol.py`): `odloz(order_id, product_id, station_code, powod, notatka, worker_id, device_id, *, teraz=None)
  -> StationDesk` (spec 9.2; `product_id=None` dla kafla-zamówienia). **Warunek wstępny:** wołający trzyma X na zamówieniu
  i pozycjach (`zablokuj_zamowienie_pozycji`). Kolejno: walidacja powodu (`BladStolu('powod_niepoprawny', …, 400)`;
  `inne` wymaga notatki) → `kafel_pozycji(..., do_zapisu=True)` (FOR UPDATE **tylko wiersza własnego kafla** po
  (`station_code`, `unit_key`) — odczyt bieżący pod trzymaną X zamówienia; wierszy innych zamówień NIE blokuje, Global
  Constraints) → wiersz z `postponed_at IS NULL`, inaczej `BladStolu('nie_na_stole', …, 409)` (odłożony drugi raz też →
  `nie_na_stole`) → liczba odłożonych stanowiska **zwykłym** `SELECT COUNT(*)` (Doprecyzowania p. 13) ≥
  `ustawienia.limit(S)` → `BladStolu('limit_odlozen', 'Na {nazwa} leży {n} odłożonych {zamówień|pozycji}. Zamknij któreś, zanim odłożysz
  kolejne.', 409)` → `postponed_at/reason/note/by_worker_id/device_id` → `PriorityLog(action='odlozenie', order_id,
  product_id, station_code, reason, note, worker_id, device_id)`.
- Produces (HTTP) `POST /api/mobile/orders/<int:order_id>/postpone` (`require_device_token`,
  `with_idempotency(retryable_statuses=BLEDY_DO_PONOWIENIA)`): ciało `{station_code, zakres, powod, notatka?}`,
  `X-Worker-Ids` jak ZAKOŃCZ. 200 → ciało jak `GET desk` **bez dopełniania** (spec 6.2 mówi „ze stołem jak w 6.1”;
  dopełnienie zrobi `GET desk`, który appka woła po własnym Odłóż — Doprecyzowanie: `postpone` nie bierze blokady
  stanowiska, bo trzyma X zamówienia, a to byłaby odwrotna kolejność wobec `dopelnij`; w odpowiedzi `stol` może więc mieć
  < K kafli, a `kolejka_dalej` liczony zwykłym odczytem). 409 `limit_odlozen`, 409 `nie_na_stole`, 400 `powod_niepoprawny`,
  400 `dane_niepoprawne` (`zakres` ≠ jednostka stanowiska, złe typy), 404 `order_not_found`.

**Kolejność blokad (spec 9.4 „ZAKOŃCZ/Odłóż: kolejność dzisiejsza”):** `touch_sessions` → X zamówienie → X pozycje →
`SELECT prod_station_desk WHERE station_code=? AND unit_key=? FOR UPDATE` (własny wiersz) → zwykły `SELECT COUNT(*)`
odłożonych stanowiska → UPDATE wiersza → INSERT `prod_priority_log` (FK zamówienia już X) → commit (dekorator) →
sygnał. Odłóż i ZAKOŃCZ/hurt/Base./cron innego zamówienia nie dzielą żadnego zamka (każdy blokuje tylko wiersze stołu
swojego zamówienia, pod swoją X), więc nie czekają na siebie. **Dlaczego nie `WHERE station_code=? FOR UPDATE` (wersja
planu sprzed recenzji):** skan stanowiska bierze rekord indeksu wtórnego, potem czeka na rekord klucza głównego wiersza
zamówienia B trzymany przez ZAKOŃCZ B (bramka po `unit_key`); ZAKOŃCZ B przy DELETE musi oznaczyć ten rekord indeksu
wtórnego, który trzyma już Odłóż → 1213 między dwoma tabletami jednego stanowiska; z hurtem (wiersze kilku zamówień
po kolei) cykl wychodzi tak samo. Dwa Odłóż na jednym stanowisku w tej samej chwili: oba mogą przejść limit o 1
(Doprecyzowania p. 13). `dopelnij` (bez S na stole) z INSERT-em w lukę indeksu najwyżej czeka na Odłóż do commita;
Odłóż nie czeka na `dopelnij` (nie bierze blokady stanowiska, a `dopelnij` trzyma tylko S na zamówieniach — jeśli S
obejmuje zamówienie Odłóż, Odłóż czeka na X zamówienia, czyli na commit `dopelnij`, który na nikogo nie czeka).
Bez cyklu.

- [x] **Step 1: Testy, które padną**
  `tests/test_priorytety_stol.py`: `test_odloz_ustawia_postponed_i_loguje`, `test_odloz_limit_409` (limit 2; dwa
  odłożone w bazie → 409 z komunikatem; jeden → 200 — Review Focus 5), `test_odloz_nie_blokuje_cudzych_wierszy_stolu`
  (`Zapytania`: jedyny SELECT `prod_station_desk` z klauzulą blokady ma `unit_key` w WHERE; licznik odłożonych bez
  klauzuli blokady), `test_odloz_nie_na_stole_409` (brak wiersza; wiersz już odłożony),
  `test_odloz_powod_inne_bez_notatki_400`, `test_odloz_powod_nieznany_400`, `test_odloz_kafel_zamowienia_na_formatowaniu`
  (`product_id=None`, `unit_key` `o:`), `test_odlozony_nie_jest_pobierany_ponownie` (po `odloz` `dopelnij` wstawia inny
  kafel, odłożony zostaje w `kafle(S)` z `postponed_at`), `test_odloz_zablokuj_zamowienie_potem_stol` (`Zapytania`:
  `blokada_zamowien` < `blokada_pozycji` < `SELECT … prod_station_desk … unit_key … FOR UPDATE` < `UPDATE
  prod_station_desk` < `INSERT INTO prod_priority_log`; brak `priorytety_blokada_%`).
  `tests/test_priorytety_mobile.py`: `test_postpone_200_zwraca_stol_z_odlozonym` (sekcja `odlozone` ma `powod`, `notatka`,
  `pracownik` = imię i nazwisko z `X-Worker-Ids`, `odlozono`), `test_postpone_limit_409_bez_wpisu_idempotencji`,
  `test_postpone_nie_na_stole_409_bez_wpisu_idempotencji`, `test_postpone_zakres_niezgodny_z_jednostka_400`,
  `test_postpone_powtorka_idempotentna_zwraca_zapisana_odpowiedz` (drugie wywołanie z tym samym `X-Operation-Id` → ta
  sama odpowiedź, jeden wiersz logu), `test_postpone_w_trybie_stary_dziala` (spec 6.3), `test_zakoncz_odlozonego_200`
  (bramka przepuszcza, wiersz znika, log `odlozenie_zamkniete`).
- [x] **Step 2: Testy padają.** **Step 3: `odloz` w `stol.py`** i stałe. **Step 4: Końcówka `postpone`** wg wzoru
  `order_complete`: `_resolve_station_code` → walidacja ciała (`zakres` ∈ `JEDNOSTKI`, zgodny z `ustawienia.jednostka(S)`;
  `powod` str; `notatka` None/str ≤ 255) → `_resolve_workers` → `zablokuj_zamowienie_pozycji(order_id)` (404) →
  `stol.odloz(item.order_id, item.id if zakres == 'pozycja' else None, S, …)` → odpowiedź budowana funkcją wspólną z `desk`
  (`_odpowiedz_stolu(S, dopelnienie=None)`), bez commita. `except BladStolu` → `{'error': e.kod, 'message': e.komunikat}`,
  `e.status`.
- [x] **Step 5: Testy przechodzą.** **Step 6: Commit** `feat(priorytety): Odloz kafla z powodem i limitem na stanowisko`

---

### Task 4: Sygnały Centrifugo — `sygnaly.py`, `publish_station_signal`, `with_idempotency`, `realtime-token`

**Files:**
- Create: `modules/production/priorytety/services/sygnaly.py`, `tests/test_priorytety_sygnaly.py`
- Modify: `modules/production/services/realtime_service.py:30-31, 183-190`, `modules/production/services/mobile_api_service.py:470-672`
  (`with_idempotency`, blok `:637-645`), `modules/production/routers/mobile_api.py` (`order_complete`, `order_quantity`,
  `order_reject` `:544-631`, `desk`, `postpone`, nowy `realtime-token`), `modules/production/services/rework_service.py`,
  `modules/production/routers/api/products_api.py` (`bulk_action` `:1609-1615`, `admin_apply_baselinker_changes` `:1303-1310`),
  `modules/production/logistics/routers/cron_api.py:36-51`

**Stan obecny (ugruntowanie):**
- `realtime_service.publish(channel, data)` `:110-180` — nigdy nie rzuca, `False` gdy `REALTIME.enabled` false albo brak
  `api_key`; `publish_print_signal` `:183-190`; `issue_connection_token(subject, channels, ttl)` `:192-216`;
  `sse_url()` `:79-82`; `is_enabled()` `:53-56`. Namespace `station:<code>` zapowiedziany w docstringu `:12`.
- Wzór planowania w `g` i wysyłki po commicie: `print_queue_service.zaplanuj_sygnal_po_commicie` `:93-101`,
  `wyslij_zaplanowany_sygnal` `:104-110`; dekorator woła go `mobile_api_service.py:637-645` po `flush_pending_syncs`,
  a dopychacz Base. `:647-654` (`bl_sync.wyslij_zaplanowane`, `bl_sync.py:452-488` z `has_request_context`).
- Token agenta: `modules/production/routers/api/print_agent_api.py` `realtime_token` `:265-301` (503 `realtime disabled` / `misconfigured`, odpowiedź
  `{enabled, token, channel, sse_url, expires_in}`). Spec 6.3 dla tabletu: `{enabled, token, ttl_seconds, sse_url, channels}`.
- Grupy stanowisk: `STATION_GROUPS = [{'edges', 'painting'}]` (`mobile_api_service.py:118-120`) — kanały tabletu Krawędzi.
- Następne stanowisko pozycji po ZAKOŃCZ: `STATUS_TO_STATION.get(item.current_status)` (`mobile_api_service.py:106`) po
  `complete_task`; `spakowane`/statusy logistyczne → brak następnego.
- Testy wzorcowe: `tests/test_realtime_publish.py` (monkeypatch `realtime_service.requests.post`, `app.config['REALTIME']`),
  `tests/test_print_agent_api_realtime.py` (token, 503).

**Interfaces:**
- Produces (`realtime_service.py`): `CHANNEL_STATION = 'station:{}'`; `channel_station(kod) -> str`;
  `publish_station_signal(kod) -> bool` = `publish(channel_station(kod), {'kind': 'station', 'station': kod})`.
  Bez ładunku użytkowego (spec 5.4).
- Produces (`sygnaly.py`): `zaplanuj(*kody) -> None` (do `g._priorytety_sygnaly: set`; bez kontekstu żądania — nic),
  `wyslij() -> List[str]` (wysyła raz na kod, czyści `g`, zwraca kody; każdy `publish_station_signal` w `try` — i tak nie
  rzuca), `nastepne_stanowisko(item) -> Optional[str]`, `zaplanuj_po_zakonczeniu(item, station_code)` (to stanowisko +
  następne pozycji). Kody filtrowane przez `STATION_PENDING_STATUS` (nieznany kod ignorowany z WARNING).
- Produces (`with_idempotency`): po `wyslij_zaplanowany_sygnal()` i przed `wyslij_zaplanowane()` dopisany blok
  `from modules.production.priorytety.services.sygnaly import wyslij; wyslij()` w `try/except` z `logger.error`
  (docstring dekoratora: trzeci rodzaj sygnału). Rollback/powtórka/`retryable` → `g` ginie, nic nie idzie (jak dotąd).
- Produces (HTTP) `GET /api/mobile/realtime-token` (`require_device_token`): 200 `{enabled: true, token, ttl_seconds,
  sse_url, channels: ['station:<kod>', …]}` — kanały = stanowisko urządzenia plus grupa (`edges` → `station:edges`,
  `station:painting`); `subject = 'device:' + g.device.device_id`; 503 `{enabled: false, reason: 'realtime disabled' |
  'misconfigured'}` jak agent. Kod urządzenia przez `station_catalog.resolve_station_code(g.device.station_code)` (wiersz
  `prod_devices` z dawnym `finishing` → `edges`). Urządzenie spoza `STATION_PENDING_STATUS` (`sawmill`, `verification`,
  `delivery`) → 200 z `channels: []`? — **nie**: 404 `unknown_station` (tablet trakowni nie ma stołu).
- Produces (miejsca publikacji, spec 5.4 i Doprecyzowania p. 8):
  | Zdarzenie | Gdzie planuje | Kanały |
  |---|---|---|
  | ZAKOŃCZ | `order_complete` po `zdejmij_nieaktualne`: `sygnaly.zaplanuj_po_zakonczeniu(item, S)` + kody z `zdejmij_nieaktualne` | to stanowisko, następne pozycji |
  | licznik | `order_quantity` | to stanowisko |
  | Odłóż | `postpone` | to stanowisko |
  | pobranie na stół | `desk` po commicie, tylko gdy `pobrane` | to stanowisko |
  | doróbka | `rework_service.reject_product_quantity` (`sygnaly.zaplanuj(rejected_at_station, return_station, *zdjete)`), wysyła dekorator | to, powrotu, zdjęte |
  | hurt | `bulk_action` po `_zapisz_zmiane_statusu` (commit w środku): `realtime_service.publish_station_signal` per kod z `results['zdjete_stanowiska']` **i** stanowiska docelowe nowego statusu (`STATUS_TO_STATION.get(nowy_status)`) | zdjęte + docelowe |
  | Base. | `admin_apply_baselinker_changes` po wyniku: kody z `result['zdjete_stanowiska']` + `cutting` gdy `added` | zdjęte, Wycinanie |
  | cron | `cron_api.cron` po commicie fazy 1: `sygnaly.wyslij()` (zaplanowane w `przenies_osierocone_z_logistyki` + `packaging`, gdy przeniesione) | zdjęte, Pakowanie |

- [x] **Step 1: Testy, które padną** — `tests/test_priorytety_sygnaly.py` (szpieg: `monkeypatch.setattr(realtime_service,
  'publish', lambda ch, data: wysłane.append((ch, data)) or True)`, `app.config['REALTIME'] = {'enabled': True, …}`
  na fiksturze `logistyka_fixtures.app`):
  - `test_publish_station_signal_kanal_i_ladunek` (`('station:gluing', {'kind': 'station', 'station': 'gluing'})`),
    `test_publish_station_signal_nie_rzuca_gdy_broker_padl` (prawdziwy `publish` z `requests.post` rzucającym; wynik
    `False`), `test_publish_station_signal_wylaczony_false`.
  - `test_zaplanuj_bez_kontekstu_zadania_nic_nie_robi`, `test_wyslij_raz_na_kod_i_czysci_g`, `test_nastepne_stanowisko_po_zakonczeniu`
    (parametryzowany: `gluing`→`formatting`; `gluing` z `cut_to_size=False`→`packaging`; `edges` olejowane→`painting`;
    `packaging`→None).
  - Review Focus 6: `test_zakoncz_sygnal_na_to_i_nastepne_stanowisko` (po 200 dokładnie `station:gluing` i
    `station:formatting`, w tej kolejności wywołań po commicie — znacznik `COMMIT` przed pierwszym `publish`),
    `test_sygnal_nie_idzie_przy_rollbacku_409` (`nie_na_stole` → brak publish), `test_sygnal_nie_idzie_przy_powtorce_idempotentnej`,
    `test_sygnal_nie_idzie_przy_wyjatku_handlera` (monkeypatch `mark_order_complete` rzuca → 500, brak publish),
    `test_licznik_sygnal_na_to_stanowisko`, `test_postpone_sygnal`, `test_desk_sygnal_tylko_gdy_dopelnil` (drugi `desk`
    bez zmian → brak publish), `test_dorobka_sygnal_na_stanowisko_powrotu`, `test_hurt_sygnal_na_zdjete_i_docelowe`,
    `test_base_sygnal_po_wyniku`, `test_cron_sygnal_po_commicie_fazy_1`.
  - `test_realtime_token_kanaly_stanowiska` (urządzenie `edges` → `channels == ['station:edges', 'station:painting']`,
    `jwt.decode(..., 'test-secret')['channels']` to samo, `sub == 'device:<device_id>'`, `ttl_seconds == 3600`),
    `test_realtime_token_503_gdy_wylaczony`, `test_realtime_token_503_bez_sekretu`, `test_realtime_token_404_trakownia`,
    `test_realtime_token_wymaga_tokena_urzadzenia` (401).
- [x] **Step 2: Testy padają.** **Step 3: `realtime_service` + `sygnaly.py`.** **Step 4: `with_idempotency`** (blok +
  docstring). **Step 5: planowanie w handlerach i routerach** wg tabeli; w `desk` zamień bezpośredni `publish_station_signal`
  z Task 2 na `sygnaly.zaplanuj(S); sygnaly.wyslij()` po commicie (jedna droga). **Step 6: `realtime-token`.**
- [x] **Step 7: Testy przechodzą:** nowy plik + `tests/test_realtime_publish.py tests/test_print_agent_api_realtime.py
  tests/test_mobile_complete_bl_sync_queue.py tests/test_logistyka_cron.py`. **Step 8: Commit**
`feat(priorytety): sygnaly station:<kod> po commicie i token realtime dla tabletow`

---

### Task 5: `priorytet` w serializerze, `KSZTALT` 6, końcówki panelu `stoly` i `odlozenia`

**Files:**
- Modify: `modules/production/services/mobile_api_service.py:1088-1253` (`serialize_order`), `:1752-1799`
  (`get_station_queue_delta`), `modules/production/routers/mobile_api.py:137` (`KSZTALT_ODPOWIEDZI_KOLEJKI`), `:242-326`
  (`station_orders`), `modules/production/priorytety/services/widok.py` (K2), `modules/production/priorytety/routers/panel_api.py`
  (K2), `tests/test_priorytety_mobile.py`, `tests/test_priorytety_panel_api.py` (K2; test zestawu końcówek)

**Stan obecny (ugruntowanie):**
- `serialize_order(item, station_code=None, label_numbering=None, packing_hints=None)` `:1088-1253`: słownik z
  `priority_rank`, `is_priority` (`:1222-1223`), `transport` przez `trasa_dla_tabletu` (`:1168-1174`, cache w `g`:
  `routes.py:460-469`, mapa tras aktywnych `:453-457` — statusy `robocza…w_trasie`). Listy podają mapy, pojedyncza
  pozycja liczy sama (docstring `:1092-1101`).
- `KSZTALT_ODPOWIEDZI_KOLEJKI = 5` `:137` z historią podbić; ETag listy `:293-296`, delty — `get_station_queue_delta`
  nie ma ETagu (`:1752-1799`), `changed` serializowane z `numeracja`.
- Pola zamówienia z K1: `priority_stars`, `priority_rank`, `priority_rung` (spec 8.1); drabina: `drabina.szczeble()`
  (K1; wiersze z `kind`, `stars`, `tag`, `route_id`, `position`). Po K2: `widok.szczebel_json`, `test_zestaw_koncowek`
  (dokładnie 8 końcówek — K3 podnosi do 10).
- Uprawnienia panelu: `guard` w `priorytety/routers/panel_api.py` (K2) — biuro (spec 7.3).

**Interfaces:**
- Produces (`mobile_api_service.py`): `serialize_order(..., priorytety=None)` — nowy argument: mapa
  `{item_id: priorytet_dict}` z `stol.kontekst_priorytetu(items)`; brak mapy → liczy dla jednej pozycji. Pole
  `'priorytet': {'gwiazdki': int, 'szczebel': 'trasa'|'gwiazdki'|'po_terminie'|'blisko_terminu'|'rozpoczete'|'dorobka'|None,
  'trasa': {'id', 'nazwa', 'data'}|None, 'pozycja_w_zamowieniu': 'i/n'}` (spec 6.1, Doprecyzowania p. 4–5). `trasa` tylko
  gdy szczebel to trasa (robocza/zatwierdzona) — z `trasa_dla_tabletu` + filtr statusu; `data` = `date_from` ISO.
  `priority_rank`/`is_priority` bez zmian (spec 6.3).
- Produces (`stol.py`): `kontekst_priorytetu(items) -> Dict[int, dict]` — jedna mapa indeks widoczny → rodzaj z
  `drabina.szczeble()` (Doprecyzowania p. 4; test `test_priorytet_szczebel_po_indeksie_widocznym` — trasa załadowana
  nad zamówieniem nie przesuwa rodzaju) (cache w `g` przez `has_request_context`), liczniki pozycji per zamówienie z `item.order.products`
  (w listach zamówienia są już `joinedload`; kolekcja `products` ładowana leniwie raz na zamówienie — akceptowalne;
  w `desk` zamówień jest ≤ K + odłożone).
- Produces (`mobile_api.py`): `KSZTALT_ODPOWIEDZI_KOLEJKI = 6` z linią historii `#   6 — 2026-10-0X: 'priorytet'
  (priorytety produkcji, krok K3)`; `station_orders` i `get_station_queue_delta` podają `priorytety=stol.kontekst_priorytetu(items)`.
- Produces (HTTP, panel, `guard`):
  - `GET /production/api/priorytety/stoly` → 200 `{"success": true, "stanowiska": [{"stanowisko": "gluing", "nazwa":
    "Sklejanie", "tryb": "stary"|"stol", "jednostka", "miejsca", "limit_odlozen", "stol": [kafel_panelu…], "odlozone":
    [kafel_panelu + {"powod", "notatka", "odlozono", "pracownik"}], "kolejka_dalej": int}, …×7]}`; `stol`/`odlozone`
    w kolejności `stol.kafle(S)` (Doprecyzowania p. 17); `kafel_panelu` =
    kształt kafla z K2 `GET /kolejka?stanowisko=` (`widok.py`) + `pobrano`. Bez dopełniania, bez blokad.
  - `GET /production/api/priorytety/odlozenia` → 200 `{"success": true, "odlozenia": [{"stanowisko", "nazwa", "order_id",
    "numer", "product_id"|null, "short_id"|null, "powod", "notatka", "odlozono", "pracownik"}]}` po `postponed_at` rosnąco
    (najdłużej leżące pierwsze). Dane do plakietki „Odłożone na Sklejaniu: brak materiału, 9:40, Adam” (spec 5.3).
- Produces (`widok.py`): `stoly_panelu() -> List[dict]`, `odlozenia_panelu() -> List[dict]`.

- [x] **Step 1: Testy, które padną** — `tests/test_priorytety_mobile.py`: Review Focus 8:
  `test_serialize_order_ma_priorytet_i_ksztalt_6` (stała == 6; pole `priorytet` z czterema kluczami; `priority_rank`
  i `is_priority` dalej są), `test_priorytet_szczebel_z_rangi_i_drabiny` (parametryzowany: ★3 bez trasy →
  `gwiazdki`; przystanek na trasie zatwierdzonej → `trasa` z `id/nazwa/data`; `priority_rung` wskazujący tag → `po_terminie`;
  doróbka → `dorobka`; brak `priority_rung` → `None`), `test_priorytet_pozycja_w_zamowieniu_pomija_anulowane` (3 pozycje,
  jedna anulowana → `2/2` dla ostatniej), `test_lista_stanowiska_etag_zmienia_sie_po_ksztalcie` (ETag z `KSZTALT=5`
  w `If-None-Match` → 200), `test_lista_i_delta_licza_kontekst_raz` (szpieg `kontekst_priorytetu` wołany raz na żądanie),
  `test_desk_kafel_ma_priorytet` (zdejmij `xfail` z Task 2).
  `tests/test_priorytety_panel_api.py`: `test_stoly_panelu_ksztalt` (7 stanowisk, kafel ze stołu i odłożony z powodem),
  `test_odlozenia_panelu_najdluzej_lezace_pierwsze`, `test_stoly_i_odlozenia_bez_blokad_i_zapisow` (`Zapytania`: brak
  `FOR UPDATE`/`LOCK IN SHARE MODE`, brak `INSERT`/`UPDATE`/`DELETE`, brak `COMMIT`), `test_zestaw_koncowek` → 10 par.
  Bez K2: zarejestruj `priorytety_panel_bp` wg K2 Task 1 Step 3 i zapisz to w „Odstępstwach” (K2 potem scala).
- [x] **Step 2: Testy padają.** **Step 3: `kontekst_priorytetu` + `serialize_order`** (kolejność kluczy: `priorytet` za
  `is_priority`). **Step 4: `KSZTALT = 6`, listy i delta.** **Step 5: `widok.py` i dwie końcówki panelu.**
- [x] **Step 6: Testy przechodzą:** oba pliki + `tests/test_logistyka_mobile.py tests/test_mobile_api_alias_krawedzi.py
  tests/test_mobile_search_archiwum.py tests/test_sawmill_mobile_api.py` (konsumenci `serialize_order`). **Step 7: Commit**
`feat(priorytety): pole priorytet w serializerze tabletu, KSZTALT 6, stoly i odlozenia w panelu`

---

### Task 5a: Lakiernia bez stołu — lista po wykończeniu, bramka i `desk`/`postpone`

Decyzja Konrada 5.10 (S-6 wariant C; spec ustalenie 15, 3.2 „Lista Lakierni”, 5.5, 6.3, 6.4 p. 7, 8.6). Task po Task 5,
bo korzysta z `serialize_order(..., priorytety=)` i `KSZTALT = 6` (jedno podbicie dla `priorytet` i `grupa_wykonczenia`).

**Files:**
- Create: `modules/production/priorytety/services/lista.py`, `tests/test_priorytety_lista_lakierni.py`
- Modify: `modules/production/priorytety/stale.py` (K1), `modules/production/priorytety/services/stol.py`
  (`bramka_zakoncz`), `modules/production/routers/mobile_api.py` (`station_orders`, `desk`, `postpone`),
  `modules/production/services/mobile_api_service.py` (`get_station_queue_delta`, `serialize_order`)

**Stan obecny (ugruntowanie, `0f23bb35`; po Taskach 1–5 linie się przesuną — szukaj po nazwie):**
- Lista tabletu: `mobile_api.station_orders` `:244`; zbiór pozycji = **wszystkie** pozycje zamówień, które mają pozycję
  w statusie stanowiska (`items_filter` po numerze zamówienia, `:272-285`); sortowanie wyłącznie w SQL `:303-307`:
  `func.coalesce(ProductionItem.priority_rank, 999999).asc()`, `internal_order_number`, `id`. ETag `:288-296`
  (`max(updated_at)`, liczba, `KSZTALT_ODPOWIEDZI_KOLEJKI`).
- Delta: `mobile_api.station_orders_since` `:701` → `mobile_api_service.get_station_queue_delta` `:1763`; zbiór =
  pozycje **w statusie** stanowiska; `all_ids` `:1779-1785` i `changed` `:1787-1795` posortowane
  `coalesce(priority_rank, 999999)`, `created_at`.
- Pozostałe użycia rangi w tych plikach: wyszukiwarka `mobile_api_service.py:901`, `:989-1048` (nie zmieniamy).
- Pola wykończenia: `ProductionItem.parsed_finish_type` (`models.py:352`, domyślnie `surowe`), `parsed_finish_color`
  (`:355`), `parsed_finish_gloss` (`:354`); serializer wystawia je już w `finish` (`mobile_api_service.py:1129-1136`,
  klucz `'finish'` `:1246`). Status Lakierni: `station_catalog.STATION_PENDING_STATUS['painting'] = 'czeka_na_lakiernie'`.
- Tablet Krawędzi: `STATION_GROUPS = [{'edges', 'painting'}]` (`mobile_api_service.py:118-120`).
- Appka 1.7.3 (repo `woodpower_prod_app`, tylko do wiadomości — K3 jej nie zmienia): lista Lakierni sortowana po stronie
  appki (`buildOrderComparator`: `isPriority`, po terminie, potem `priority_rank` albo „Partia (kolor i połysk)”) —
  porządek serwera dotrze na ekran dopiero z nową appką (spec 6.4 p. 7; pytanie do Konrada w raporcie D-Lakiernia).

**Interfaces:**
- Produces (`stale.py`): `STANOWISKA_BEZ_STOLU = ('painting',)` — jedna stała: porządek listy po wykończeniu i brak
  stołu (spec 8.6). Bez klucza `prod_config`.
- Produces (`lista.py`, czyste funkcje, bez zapytań i bez `db.session`):
  - `klucz_grupy_wykonczenia(item) -> Tuple[Optional[str], Optional[str], Optional[str]]` — (`parsed_finish_type`,
    `parsed_finish_color`, `parsed_finish_gloss`) znormalizowane: `strip()`, `lower()`, pusty → `None`.
  - `grupa_wykonczenia_json(item) -> dict` — `{"rodzaj", "kolor", "polysk"}` z klucza (wartości `None` → `null`).
  - `porzadek_listy(station_code, items) -> List[item]` — `station_code not in STANOWISKA_BEZ_STOLU` → `items` bez zmian
    (lista w kolejności SQL, ta sama tożsamość). Dla `painting` wg spec 3.2 „Lista Lakierni”: pozycje w statusie
    `czeka_na_lakiernie` → klucz pozycji `(0 if original_product_id else 1, created_at if doróbka else <stały>,
    priority_rank if not None else 999999, internal_order_number, id)`; grupy po `klucz_grupy_wykonczenia`, kolejność
    grup po **najmniejszym** kluczu pozycji w grupie, remis → klucz grupy (z `None` na końcu); w grupie po kluczu
    pozycji; cała grupa w jednym ciągu; potem pozostałe pozycje (inne statusy) po dzisiejszym kluczu
    (`priority_rank` NULLS LAST, `internal_order_number`, `id`). `internal_order_number` z `item.order` (listy mają
    `joinedload`). Sortowanie stabilne, wynik deterministyczny dla tych samych danych (dwa tablety, odświeżanie co 30 s).
- Produces (przepięcia):
  - `station_orders`: po `.all()` → `items = porzadek_listy(station_code, items)` (SQL `ORDER BY` zostaje — dla innych
    stanowisk jedyne źródło kolejności); numeracja etykiet i podpowiedzi paczek liczone jak dotąd. ETag bez zmian
    w budowie (kolejność zależy od rangi i pól wykończenia pozycji tego samego zbioru — ich zmiana podbija `updated_at`;
    nowa doróbka zmienia liczbę).
  - `get_station_queue_delta`: dla `painting` `all_ids` z pełnych obiektów (`base.options(joinedload(order)).all()`,
    potem `porzadek_listy` i `[it.id …]`), `changed` też przez `porzadek_listy`; dla innych stanowisk zapytania bez zmian
    (`with_entities(id)` — bez dodatkowego kosztu).
  - `serialize_order`: pole `grupa_wykonczenia` = `grupa_wykonczenia_json(item)` gdy `station_code == 'painting'`,
    inaczej `None`; klucz za `priorytet`. Ten sam `KSZTALT_ODPOWIEDZI_KOLEJKI = 6` co `priorytet` (Task 5) — **bez**
    drugiego podbicia; linia historii przy stałej dopisuje oba pola.
  - `stol.bramka_zakoncz`: pierwszy warunek `station_code in STANOWISKA_BEZ_STOLU` → przepuść (przed odczytem trybu
    i wiersza stołu — zero zapytań stołu dla Lakierni). Pomyłkowe `priorytety_tryb_painting = stol` nie blokuje hali.
  - `desk` i `postpone`: po `resolve_station_code` i kontroli dostępu, **przed** commitem i blokadą stanowiska:
    `S in STANOWISKA_BEZ_STOLU` → 409 `{"error": "stanowisko_bez_stolu", "message": "Lakiernia pracuje z listy, bez
    stołu."}`, bez zapisu (dla `postpone` 409 z `BLEDY_DO_PONOWIENIA` → bez wpisu idempotencji). `realtime-token`
    bez zmian (tablet Krawędzi dalej dostaje `station:painting` — sygnał może odświeżyć listę Lakierni).
  - Panel `GET /stoly` (Task 5) i `widok.stoly_panelu()` pomijają stanowiska z `STANOWISKA_BEZ_STOLU` (6 stanowisk);
    `test_stoly_panelu_ksztalt` z Task 5 → 6 stanowisk.

- [x] **Step 1: Testy, które padną** — `tests/test_priorytety_lista_lakierni.py` (fikstury `logistyka_fixtures`,
  pozycje z ustawionymi `parsed_finish_*`, rangami i statusem `czeka_na_lakiernie`):
  - `test_klucz_grupy_normalizuje` (spacje, wielkie litery, pusty napis → `None`; olejowane bez połysku to osobna
    wartość od lakierowanego z połyskiem).
  - `test_lista_lakierni_grupy_wykonczenia_w_jednym_ciagu` (grupy A i B przeplecione rangami: A 1, B 2, A 3, B 4 →
    A1, A3, B2, B4; brak limitu: grupa A z 12 pozycji w jednym ciągu).
  - `test_lista_lakierni_grupy_po_najpilniejszej_pozycji` (grupa B ma pozycję z rangą 101, A najwyżej 205 → B pierwsza;
    remis rang niemożliwy w danych — remis kluczy grup przez `None` rangi: kolejność po kluczu grupy).
  - `test_lista_lakierni_dorobka_pierwsza_i_jej_grupa_pierwsza` (doróbka z rangą 0 w grupie C → C pierwsza, doróbka na
    jej początku; dwie doróbki w różnych grupach → grupa starszej doróbki pierwsza, druga zaraz po niej).
  - `test_lista_lakierni_pozycje_w_innych_statusach_na_koncu` (zamówienie z pozycją na Lakierni i pozycją
    `czeka_na_pakowanie` → ta druga na końcu listy).
  - `test_lista_lakierni_bez_rangi_na_koncu_grupy` (`priority_rank = None`).
  - `test_lista_innych_stanowisk_bez_zmian` (parametryzowany: `cutting`, `assembly`, `gluing`, `formatting`, `edges`,
    `packaging` — kolejność odpowiedzi `GET /stations/<kod>/orders` == dzisiejszy klucz SQL; pole `grupa_wykonczenia`
    jest `None`).
  - `test_delta_lakierni_all_ids_w_kolejnosci_listy` (`/stations/painting/orders/since`: `all_ids` == id pozycji
    w statusie Lakierni w kolejności `porzadek_listy`; `changed` w tej samej względnej kolejności).
  - `test_lista_lakierni_etag_bez_zmian_budowy_ksztalt_6` (`KSZTALT_ODPOWIEDZI_KOLEJKI == 6`; zmiana
    `parsed_finish_color` pozycji z podbiciem `updated_at` → nowy ETag i nowa kolejność; bez zmian danych → 304).
  - `test_serialize_order_grupa_wykonczenia` (`painting` → `{"rodzaj", "kolor", "polysk"}`; inne stanowisko → `None`).
  - `test_bramka_lakierni_otwarta_mimo_trybu_stol` (`priorytety_tryb_painting = stol`, próg wersji 0, brak wiersza
    stołu → ZAKOŃCZ 200 i licznik 200; `Zapytania`: brak SELECT `prod_station_desk` z klauzulą blokady).
  - `test_desk_i_postpone_lakierni_409_bez_zapisu` (urządzenie `edges` i `painting`: `GET /stations/painting/desk` → 409
    `stanowisko_bez_stolu`, zero wierszy `prod_station_desk`, brak `priorytety_blokada_painting` w zapytaniach;
    `POST postpone` ze `station_code=painting` → 409, `ProcessedMobileOperation.query.count() == 0`).
  - `test_stoly_panelu_bez_lakierni` (`GET /production/api/priorytety/stoly` → 6 stanowisk, bez `painting`).
- [x] **Step 2: Testy padają.** **Step 3: `stale.STANOWISKA_BEZ_STOLU` i `lista.py`.** **Step 4: przepięcia**
  (`station_orders`, delta, serializer, bramka, `desk`, `postpone`, `widok.stoly_panelu`); komentarz przy
  `porzadek_listy` z odesłaniem do spec 3.2 „Lista Lakierni” i decyzji „do potwierdzenia przy bramce K3”.
- [x] **Step 5: Testy przechodzą:** nowy plik + `tests/test_priorytety_stol.py tests/test_priorytety_mobile.py
  tests/test_priorytety_panel_api.py tests/test_mobile_api_alias_krawedzi.py tests/test_logistyka_mobile.py`.
  **Step 6: Commit** `feat(priorytety): Lakiernia bez stolu - lista po grupach wykonczenia`

---

### Task 5b: „Wyślij na stanowisko” i „Zdejmij ze stołu” (spec 5.7, 9.2, 9.4, 10)

**Files:** `modules/production/priorytety/services/stol.py`, `modules/production/priorytety/routers/panel_api.py`,
`tests/test_priorytety_stol.py`, `tests/test_priorytety_panel_api.py`.

**Interfaces:**
- `stol.wyslij(station_code, order_id, user_id, *, teraz=None) -> dict` — `{'wyslane': [unit_key], 'przywrocone':
  [unit_key], 'juz_na_stole': [unit_key]}`; bez commita. Kładzie na stół kafle zamówienia, które są TERAZ w statusie
  stanowiska: jednostka `pozycja` — każda taka pozycja osobno, `zamowienie` — kafel `o:` (także niekompletne).
  `zrodlo='biuro'`, `sent_by_user_id`, ponad K. Kafel na stole → bez zmian; odłożony → wraca na stół (`postponed_*`
  wyczyszczone, `zrodlo='biuro'`, `pulled_at=teraz`). Odmowy `BladStolu`: 409 `stanowisko_bez_stolu`, 404
  `zamowienie_nieznane`, 409 `brak_na_stanowisku`, 409 `delivery_method_not_set` (Pakowanie bez sposobu dostawy).
  Log `wyslanie` na każdy kafel wysłany albo przywrócony.
- `stol.zdejmij_przez_biuro(station_code, unit_key, user_id, *, teraz=None) -> StationDesk` — DELETE wiersza (na
  stole albo odłożonego), log `zdjecie`; 404 `brak_kafla`, 400 `dane_niepoprawne` (zły klucz).
- Kolejność blokad obu (spec 9.4, jak `dopelnij`): [commit routera] → `priorytety_blokada_<S>` FOR UPDATE →
  zamówienie FOR SHARE → jego pozycje FOR SHARE (`ORDER BY id`) → wiersze stołu WŁASNEGO zamówienia odczytem
  bieżącym po (`station_code`, `unit_key`) → INSERT/UPDATE/DELETE → [commit routera] → sygnał `station:<S>`.
  Bez blokad X zamówień, bez blokady tras.
- HTTP (`guard`): `POST /production/api/priorytety/stoly/<S>/wyslij` `{order_id}` → 200 `{success, stanowisko,
  wynik: 'wyslano'|'juz_na_stole', wyslane, przywrocone, juz_na_stole}`; `POST …/stoly/<S>/zdejmij` `{unit_key}` →
  200 `{success, stanowisko, unit_key}`. Nieznane stanowisko → 400 `stanowisko_nieznane`. Przez
  `_zapis_z_ponowieniem` (jedno ponowienie po 1213). Działa w trybie `stary` i `stol`.

- [x] **Step 1: Testy, które padną** — serwis: `test_wyslij_pozycje_w_statusie_stanowiska_ponad_k`,
  `test_wyslij_kafel_zamowienia_takze_niekompletny`, `test_wyslij_juz_na_stole_bez_zmian`,
  `test_wyslij_odlozony_wraca_na_stol`, `test_wyslij_brak_na_stanowisku_409`,
  `test_wyslij_pakowanie_bez_sposobu_dostawy_409`, `test_wyslij_lakiernia_409`,
  `test_wyslij_kolejnosc_blokad_jak_dopelnij`, `test_wyslany_niekompletny_kafel_przezywa_zakoncz_pozycji`,
  `test_zdejmij_przez_biuro_usuwa_i_loguje`, `test_zdejmij_przez_biuro_brak_kafla_404`,
  `test_zdjety_kafel_wraca_do_kolejki`; panel: `test_wyslij_200_log_i_sygnal`, `test_wyslij_kody_bledow`,
  `test_zdejmij_200_i_404`, `test_wyslij_commit_przed_blokada_stanowiska`, `test_zestaw_koncowek` (+2).
- [x] **Step 2: Testy padają.** **Step 3: `stol.wyslij`, `stol.zdejmij_przez_biuro`.** **Step 4: Końcówki.**
- [x] **Step 5: Testy przechodzą.** **Step 6: Commit** `feat(priorytety): Wyslij na stanowisko i Zdejmij ze stolu`

---

### Task 5c: Start stołów — kafle rozpoczęte (spec 5.8, ustalenie 17)

**Files:** `modules/production/priorytety/services/stol.py`, `modules/production/priorytety/routers/panel_api.py`,
`tests/test_priorytety_stol.py`, `tests/test_priorytety_panel_api.py`.

**Definicja „rozpoczęte na stanowisku S” (ustalona na kodzie):** praca RĘCZNA = zdarzenie `prod_station_events`
pozycji na stanowisku `S` ze źródłem `mobile`, `web` albo `admin` i `delta > 0` (źródła `auto_skip` i `system`
tworzy wyłącznie `complete_task` przy automatycznym pominięciu stanowiska). Pozycja „zrobiona ręcznie na S” = ma
takie zdarzenie, licznik `quantity_done_<S>` > 0 i NIE czeka już na S (status inny niż status stanowiska), nie jest
anulowana ani wstrzymana.
- jednostka `pozycja`: pozycja w statusie `S` z `quantity_done_<S>` > 0 ALBO pozycja w statusie `S`, której
  zamówienie ma inną pozycję zrobioną ręcznie na `S`;
- jednostka `zamowienie`: zamówienie z pozycją w statusie `S`, które ma pozycję z `quantity_done_<S>` > 0 w statusie
  `S` albo pozycję zrobioną ręcznie na `S` (także niekompletne — jak „Wyślij”);
- Pakowanie: zamówienie bez sposobu dostawy nie wchodzi (spec 5.1); Lakiernia nie ma stołu.

**Interfaces:**
- `stol.rozpoczete_na_stanowisku(station_code) -> List[dict]` — zwykłe odczyty, bez zapisu: `{'unit_key',
  'order_id', 'numer', 'product_id', 'short_id', 'powod': 'licznik'|'zamowienie', 'na_stole': bool}` w kolejności
  (numer zamówienia, id pozycji).
- `stol.przygotuj_start(station_code, user_id, *, teraz=None) -> dict` — `{'dodane': n, 'juz_byly': m}`; pod
  blokadą stołu, odczytem bieżącym jak `dopelnij`; INSERT brakujących wierszy `zrodlo='start'`, `sent_by_user_id`;
  istniejących (na stole i odłożonych) nie rusza; log `start_stolow` (`station_code`, `new_value` = dodane,
  `old_value` = już były). Bez commita.
- HTTP: `GET /production/api/priorytety/start` (`guard`) → `{success, stanowiska: [{stanowisko, nazwa, tryb,
  jednostka, miejsca, liczba, na_stole, kafle}]}` dla 6 stanowisk; `POST /production/api/priorytety/start/przygotuj`
  (`guard` + `admin_required`) → stanowisko po stanowisku, każde w osobnej transakcji (commit → blokada → zapis →
  commit → sygnał), `{success, stanowiska: [{stanowisko, dodane, juz_byly}]}`; błąd jednego stanowiska nie cofa
  poprzednich (500 `blad_serwera` z listą wykonanych — wywołanie jest idempotentne).

- [x] **Step 1: Testy, które padną** — serwis: `test_rozpoczete_pozycja_z_licznikiem`,
  `test_rozpoczete_pozycja_gdy_inna_zrobiona_recznie`, `test_rozpoczete_pomija_auto_skip_i_system`,
  `test_rozpoczete_zamowienie_na_formatowaniu`, `test_rozpoczete_pakowanie_bez_sposobu_dostawy_nie_wchodzi`,
  `test_przygotuj_start_wstawia_zrodlo_start_ponad_k`, `test_przygotuj_start_idempotentne`,
  `test_przygotuj_start_kolejnosc_blokad`, `test_dopelnij_startowe_trzymaja_miejsca_az_zejda_ponizej_k` (napisany w Tasku 2),
  `test_zakoncz_w_trybie_stary_zdejmuje_kafel_startowy`; panel: `test_start_podglad_ksztalt_bez_zapisow`,
  `test_start_przygotuj_admin_i_osobne_transakcje`, `test_start_przygotuj_403_bez_admina`, `test_zestaw_koncowek` (+2).
- [x] **Step 2: Testy padają.** **Step 3: serwis.** **Step 4: końcówki.** **Step 5: Testy przechodzą.**
- [x] **Step 6: MySQL — liczba kafli startowych per stanowisko** na `priorytety_podglad` (kopia danych produkcji):
  `rozpoczete_na_stanowisku(S)` dla 6 stanowisk, same liczby (bez danych klientów) do raportu — wejście do decyzji
  Konrada (spec 5.8, ostatni akapit).
- [x] **Step 7: Commit** `feat(priorytety): start stolow z kafli rozpoczetych`

---

### Task 6: Pełny pakiet, Python 3.9, lista wyścigów dla K5, raport kroku

**Files:**
- Create: `docs/superpowers/plans/raporty/2026-10-05-priorytety-krok-K3-raport.md`

- [x] **Step 1: Pełny pakiet:** `docker compose exec app pytest tests/ -q -p no:cacheprovider` → 0 failed; `passed` =
  punkt wyjścia + nowe (liczby do raportu). `blog_seo` nie dotyczy.
- [x] **Step 2: Składnia 3.9** dla plików `.py` z `git diff --name-only <hash startu>..HEAD -- '*.py'`:
  `docker compose exec app python -c "import ast,sys; [ast.parse(open(p,encoding='utf-8').read(), p, feature_version=(3,9)) for p in sys.argv[1:]]; print('OK')" <pliki>`
  i grep `' | None'` / `\w+ \| \w+` w adnotacjach plików bez `from __future__ import annotations` → pusto.
- [x] **Step 3: Grep kontrolny** (wyniki do raportu): `grep -rn "db.session.commit" modules/production/priorytety/services/stol.py
  modules/production/priorytety/services/sygnaly.py` → pusto; `grep -n "db.session.commit" modules/production/routers/mobile_api.py`
  → tylko w `desk` (i istniejące miejsca sprzed K3: `register`, `heartbeat`, `apk`); `grep -rn "publish_station_signal\|sygnaly\." modules`
  → wyłącznie miejsca z tabeli Task 4; `grep -rn "zdejmij_nieaktualne" modules` → pięciu pisarzy z Task 1 (ZAKOŃCZ,
  doróbka, Base., hurt, cron; licznik ma tylko bramkę); `grep -n "station_code.*with_for_update\|do_zapisu=True"
  modules/production/priorytety/services/stol.py` → blokujące odczyty stołu tylko po `unit_key`/`order_id`;
  `grep -rn "STANOWISKA_BEZ_STOLU\|porzadek_listy" modules` → `stale.py`, `lista.py`, `stol.bramka_zakoncz`, `desk`,
  `postpone`, `station_orders`, `get_station_queue_delta`, `widok.stoly_panelu` (Task 5a) i nic więcej.
- [x] **Step 4: Podgląd MySQL (bez wyścigów):** na podglądzie wskazanym przez centralę włącz `SET GLOBAL general_log=1`,
  wykonaj jedno `GET desk` (tryb `stol`, dwa kandydaci) i jedno ZAKOŃCZ kafla; wklej do raportu kolejność zapytań obu
  żądań (bez danych klientów) i potwierdź: `COMMIT` → `SELECT … prod_config … FOR UPDATE` → `… LOCK IN SHARE MODE`
  zamówień → pozycji → zwykły SELECT stołu → `INSERT`; ZAKOŃCZ: zamówienie → pozycje → UPDATE → `SELECT … prod_station_desk
  … FOR UPDATE` → DELETE. Wyłącz `general_log`. Jeśli podglądu MySQL nie ma — napisz to w raporcie (K5 to zrobi).
- [x] **Step 5: Lista wyścigów MySQL dla K5** (sekcja raportu „Co następny krok musi wiedzieć”, a karta 8.3 każe
  sprawdzić, czy plan K5 ma je wszystkie — czego brakuje, wypisz):

  | Tryb | Stan wyjściowy | Strona A | Strona B | Oczekiwane |
  |---|---|---|---|---|
  | `desk-desk` | Sklejanie, tryb `stol`, K=2, 6 kandydatów, pusty stół, dwa urządzenia | `GET desk` tablet 1 | `GET desk` tablet 2 (równolegle, 50 serii) | oba 200, stół = 2 kafle, zero duplikatów `unit_key`, zero 1213 (B czeka na blokadzie) |
  | `desk-zakoncz-inne` | stół pełny (A, B), kandydat C w innym zamówieniu niż A | ZAKOŃCZ kafla A (zamówienie A) | `GET desk` | 200/200, stół po obu: B + następny; 1213 najwyżej raz na serię i tylko po stronie `desk` z udanym ponowieniem |
  | `desk-zakoncz-to-samo-zamowienie` | zamówienie Z z pozycjami P1 (na stole) i P2 (kandydat) | ZAKOŃCZ P1 | `GET desk` (chce S na Z) | `desk` czeka, potem bierze P2 albo widzi już nowy stan; zero 1213 |
  | `desk-dorobka` | kandydat w zamówieniu Z; doróbka z Formatowania do Sklejania | `POST reject` | `GET desk` Sklejania | doróbka na stole ponad K przy następnym `desk`; zero 1213 (Doprecyzowania p. 1, analiza Task 2) |
  | `desk-panel-sposob` | Pakowanie, tryb `stol`, kandydat bez sposobu dostawy | panel: `delivery_method` ustawia kuriera | `GET desk` Pakowania | kafel wchodzi albo czeka do następnego `desk`; nigdy kafel bez sposobu; zero 1213 |
  | `desk-utrwal` | 250 zamówień aktywnych (kopia produkcji) | `kolejka.utrwal()` (zmiana gwiazdek w panelu) | `GET desk` ×7 stanowisk | zero 1213; jeśli 1213 → `SHOW ENGINE INNODB STATUS`, sprawdź, czy `utrwal` zapisuje pozycje zamówienia, którego nie zablokował |
  | `odloz-odloz` | limit 2, jeden odłożony, dwa kafle na stole | `postpone` kafla 1 | `postpone` kafla 2 | jedno 200 i jedno 409 `limit_odlozen` **albo** oba 200 (limit miękki, Doprecyzowania p. 13 — zapisać rozkład); odłożonych ≤ limit + 1; zero 1213 |
  | `odloz-zakoncz` | kafel A na stole, kafel B na stole (dwa tablety jednego stanowiska) | `postpone` A | ZAKOŃCZ B | oba 200 bez czekania na siebie (każdy blokuje tylko wiersz swojego zamówienia); zero 1213 — przy blokadzie wierszy całego stanowiska tu wychodził cykl indeks wtórny ↔ klucz główny |
  | `odloz-hurt` | kafle A, B, C na stole (trzy zamówienia, wiersz C wstawiony przed A) | `postpone` B | hurt → `wstrzymane` na A i C | oba 200; kafle A i C zniknęły, B odłożony; zero 1213 (hurt blokuje wiersze stołu A, potem C; Odłóż tylko B) |
  | `zakoncz-zakoncz-ten-sam-kafel` | kafel A na stole, dwa tablety | ZAKOŃCZ A | ZAKOŃCZ A (inny `X-Operation-Id`) | pierwszy 200, drugi 200 idempotentnie po statusie (jak dziś) albo 409 `nie_na_stole` — zapisać, które; bez 500 |
  | `hurt-desk` | 20 zaznaczonych pozycji na Sklejaniu, część na stole | hurt → `wstrzymane` | `GET desk` | kafle wstrzymanych znikają, `desk` dopełnia innymi; zero 1213 bez ponowienia |
  | `gwiazdki-zakoncz`, `szczebel-przystanek`, `utrwal-dostawa` | z K1/K2 (spec 13) | — | — | już w planach K1/K2; sprawdź, że K5 je ma |

  Kryterium (karta 8.6): zero 1213 bez ponowienia, zero zdublowanych kafli, zero niekompletnych kafli-zamówień na stole.
- [x] **Step 6: Raport** z sekcjami karty: Zrobione (po Taskach), Testy (polecenia i wyniki; liczby Step 0 Task 1 i Step 1
  tutaj), Odstępstwa od planu (nazwy K1 inne niż spec; brak K2), Rozstrzygnięcia podjęte w trakcie (numerowane; koszt,
  jeśli błędne — co najmniej: kolejność blokad `dopelnij` z Doprecyzowań p. 1, `zdejmij_nieaktualne`, semantyka progu
  wersji, bramka niekompletnych p. 12, miękki limit p. 13), Pytania do Konrada, Stan gałęzi (hash, czy wypchnięte), Co następny krok musi wiedzieć:
  - **K4a:** plakietka „Odłożone na …” i sekcja odłożeń w modalu czytają `GET /production/api/priorytety/odlozenia`
    i `GET …/zamowienia/<id>/priorytet` (K2); kształty JSON z Task 5;
  - **K4b:** zakładka Stanowiska czyta `GET /production/api/priorytety/stoly` (stół + odłożone + `kolejka_dalej`; pierwsze
    15 kafli kolejki z K2 `GET /kolejka?stanowisko=`); Konfiguracja: `tryb`, `miejsca`, `jednostka`, `limit_odlozen`,
    `min_app_version_code` przez `PUT /ustawienia` (K2); **Lakiernia:** `stoly_panelu()` jej nie zwraca (6 stanowisk),
    zakładka i monitor Lakierni układają się przez `lista.porzadek_listy('painting', items)` i pokazują
    `grupa_wykonczenia_json` (Task 5a), wiersz Lakierni w „Stół stanowisk” bez wyboru trybu;
  - **K2 / centrala:** `PUT /ustawienia` nadal przyjmuje `stanowiska.painting.tryb = stol` — bez skutku (bramka i `desk`
    ignorują Lakiernię), ale do decyzji, czy walidacja ma to odrzucać (400);
  - **K5:** lista wyścigów wyżej — plan K5 ma jeszcze `odloz-odloz`/`odloz-zakoncz`/`odloz-zakoncz-ten-sam-kafel`
    z opisem „Odłóż: `prod_station_desk` stanowiska `FOR UPDATE`” sprzed recenzji K3: poprawić opisy i oczekiwania wg
    tabeli wyżej i dopisać `odloz-hurt`; CLAUDE.md — sekcja „Priorytety produkcji” z kolejnością blokad `dopelnij`, Odłóż
    i zdjęcia kafla (ramki z Task 1–3), dopisek do akapitu pisarzy pozycji (`order_quantity` czyta stół bez blokady
    zamówienia); Doprecyzowania 1–17 do specu (zwłaszcza 9.4 → kolejność zamówienia → pozycje w `dopelnij`); sprawdzenie
    `utrwal` z Task 2;
  - **K6 (kontrakt appki):** pełne przykłady JSON `desk` (obie jednostki), `postpone`, `realtime-token` z testów;
    kody 409 `nie_na_stole`, `limit_odlozen`, 400 `powod_niepoprawny`, `dane_niepoprawne`; `KSZTALT_ODPOWIEDZI_STOLU`;
    zachowanie przy `REALTIME.enabled=false` (503 z `/realtime-token` → odpytywanie 30 s / 5 min); stara appka: `priorytet`
    ignorowane, ETag listy zmieniony raz; `desk` z `Cache-Control: private, max-age=0` (OkHttp zawsze pyta serwer);
    ZAKOŃCZ/licznik pozycji niekompletnego zamówienia przechodzą bramkę (Doprecyzowania p. 12); limit odłożeń miękki
    (p. 13); **Lakiernia bez stołu** (Task 5a): 409 `stanowisko_bez_stolu` z `desk`/`postpone`, lista
    `/stations/painting/orders` w kolejności serwera z polem `grupa_wykonczenia`, delta `all_ids` w tej samej kolejności;
  - **K7:** `priorytety_min_app_version_code` = kod wersji nowej appki PRZED przełączeniem pierwszego stanowiska na `stol`;
    tablety bez heartbeatu liczą się jako stare; Lakiernia nie jest przełączana (6 stanowisk w P3).
- [x] **Step 7: Commit raportu i push** wg karty: `git add -f docs/superpowers/plans/raporty/2026-10-05-priorytety-krok-K3-raport.md`,
  `docs(priorytety): raport kroku K3 stol Odloz sygnaly`.

---

## Kryteria zakończenia (DoD)

1. `tests/test_priorytety_stol.py`, `tests/test_priorytety_mobile.py`, `tests/test_priorytety_sygnaly.py` zielone; każdy test
   z Review Focus istnieje pod podaną nazwą. Pełny pakiet: 0 failed, liczby w raporcie.
2. `app.url_map` ma `GET /api/mobile/stations/<station_code>/desk`, `POST /api/mobile/orders/<int:order_id>/postpone`,
   `GET /api/mobile/realtime-token`, `GET /production/api/priorytety/stoly`, `GET /production/api/priorytety/odlozenia`
   (`test_zestaw_koncowek` K2 → 10; w `test_priorytety_mobile.py` analogiczny test dla trzech końcówek mobilnych).
3. Test kolejności `dopelnij` (Review Focus 1) potwierdza: `COMMIT` → `prod_config FOR UPDATE` → zamówienia
   `LOCK IN SHARE MODE` rosnąco → pozycje `… ORDER BY order_id, id LOCK IN SHARE MODE` → zwykły SELECT stołu → `INSERT`;
   żaden SELECT `prod_station_desk` w `dopelnij` nie ma klauzuli blokady; ZAKOŃCZ nie dotyka `priorytety_blokada_%`.
4. Pięciu pisarzy z Task 1 (ZAKOŃCZ, doróbka, Base., hurt, cron) woła `stol.zdejmij_nieaktualne` pod trzymaną blokadą
   zamówienia (grep + testy Review Focus 3); DELETE stołu zawsze po `blokada_zamowien` i `blokada_pozycji` w kolejności
   zapytań. Żaden blokujący odczyt `prod_station_desk` nie obejmuje wierszy innych zamówień (blokada tylko po
   `unit_key` własnego kafla albo `order_id` zablokowanego zamówienia).
5. 409 `nie_na_stole` i `limit_odlozen` nie zapisują wpisu idempotencji (testy); sygnał nie idzie przy rollbacku,
   powtórce idempotentnej ani wyjątku handlera (testy Review Focus 6).
6. `grep "db.session.commit" stol.py sygnaly.py` → pusto; w `mobile_api.py` nowy commit tylko w `desk`.
   `realtime_service.publish_station_signal` zwraca `False` bez wyjątku przy wyłączonym realtime i przy padniętym brokerze.
7. `KSZTALT_ODPOWIEDZI_KOLEJKI == 6`, `serialize_order` ma `priorytet` o czterech kluczach; konsumenci serializera zielone.
8. Składnia 3.9 OK dla zmienionych `.py`. Brak migracji w kroku (albo odstępstwo wyjaśnione).
9. Raport kroku zacommitowany z listą wyścigów (≥ 10 trybów) i sekcją „Co następny krok musi wiedzieć” z punktami K4a,
   K4b, K5, K6, K7. `main` nietknięty; commity tylko na `claude/priorytety-produkcji`: 7, po jednym na Task (1–5, 5a, 6).
10. Lakiernia (Task 5a, Review Focus 9): `tests/test_priorytety_lista_lakierni.py` zielony; lista i delta `painting`
    w kolejności grup wykończenia, pozostałe stanowiska bez zmian kolejności; `KSZTALT_ODPOWIEDZI_KOLEJKI == 6` (jedno
    podbicie dla `priorytet` i `grupa_wykonczenia`); bramka przepuszcza Lakiernię przy `priorytety_tryb_painting = stol`;
    `desk`/`postpone` Lakierni → 409 `stanowisko_bez_stolu` bez zapisów; brak klucza `prod_config` dla porządku listy.

## Poza zakresem

- UI (Lista produkcyjna, zakładka Stanowiska, Konfiguracja, monitory hali) — K4a, K4b. Kontrakt appki i karta sesji appki —
  K6. Przełączanie trybów i progu wersji na produkcji — K7.
- Algorytm kolejki (`kolejka.kandydaci_stanowiska`, `policz`, `utrwal`), drabina, gwiazdki, migracja — K1; końcówki panelu
  poza `stoly`/`odlozenia` — K2. Zmiana `ustawienia.*` (pamięć podręczna) — tylko za zgodą centrali.
- Wyścigi na dwóch sesjach MySQL — K5 (ten krok je spisuje). Sprawdzenie sygnałów na podglądzie z brokerem — K5.
- Raport odłożeń (udział, czas leżenia) — po P3 (spec 14). `REFRESH_INTERVAL_SECONDS`, lista `/orders` dla tabletów — P4.
- Zaobserwowane usterki spoza zakresu (np. `order_quantity` bez blokady zamówienia jako klasa pisarza; brak `PRAGMA
  foreign_keys` w fiksturach SQLite) — do raportu, bez naprawy.
- Znane wyjątki bez `zdejmij_nieaktualne` (do raportu, bez naprawy): hurtowe usunięcie pozycji (`bulk-action` `delete`,
  tylko admin — na MySQL kaskada FK zdejmuje kafel `p:`, ale kafel `o:` zamówienia bez pozycji na S zostaje do ręcznego
  sprzątnięcia) i ręczna synchronizacja z `force_update` dopisująca pozycje bez blokady zamówienia (CLAUDE.md — kafel `o:`
  może zostać na stole niekompletnego zamówienia). Pisarze, którzy DOKŁADAJĄ pracę stanowisku bez zdejmowania kafla
  (przepakowanie `delivery.py:389`, „Cofnij do pakowania” `weryfikacja.py:677`, import nowych zamówień), sygnału
  `station:packaging`/`station:cutting` nie wysyłają — siatka 30 s/5 min (spec 5.4 ich nie wymienia).

## Ryzyka i co robić przy blokadzie

| Ryzyko | Skutek | Co robić |
|---|---|---|
| `kolejka.kandydaci_stanowiska` z K1 ma inny kształt wejścia/wyjścia niż spec 9.2 (brak podziału kompletne/niekompletne, brak `brakuje`, słowniki zamiast ORM) | Task 2 nie da się zrobić wg planu | Step 0: drobne dopasowanie (adapter w `stol.py` budujący wejście) dopuszczalne; brak podziału kompletne/niekompletne → **STOP** przed Task 2, meldunek do centrali (karta K1-poprawka). Bez własnej kopii algorytmu |
| K2 nie zakończony (brak `priorytety_panel_bp`, `widok.py`) | Task 5 część panelowa | Zarejestruj blueprint wg K2 Task 1 Step 3, `widok.py` z dwiema funkcjami; „Odstępstwa”; K2 scala przy `git pull` |
| `ustawienia.tryb(S)` przez pamięć podręczną procesu (60 min) | bramka na innym workerze gunicorna widzi stary tryb; wycofanie P3 „bez zmiany kodu” opóźnione | nie naprawiaj sam; meldunek, test z K2 Task 5 to pokrywa |
| Odwrotna kolejność blokad między `dopelnij` a innym pisarzem, niewidoczna w SQLite | 1213 na produkcji | Testy kolejności zapytań (Review Focus 1–2), analiza w Task 2, lista wyścigów dla K5. Jeśli w Step 4 Task 6 `general_log` pokaże inną kolejność niż w planie → STOP i meldunek |
| `dopelnij` bierze S na kilkudziesięciu zamówieniach co 30 s na stanowisko (7 stanowisk, 2 tablety) | panel i ZAKOŃCZ czekają po kilkadziesiąt ms; przy wolnym MySQL odczuwalne | zmierz czas `GET desk` na podglądzie z kopią produkcji i wpisz do raportu; > 300 ms → meldunek, bez optymalizacji na własną rękę (opcja do decyzji: zwykły odczyt zamówień i S tylko na pozycjach) |
| Cykl importów: `priorytety.services.stol` importuje `logistics.services.delivery`/`sposoby`, a `delivery` ma importować `stol`; `mobile_api_service` (Task 5) importuje `stol` | `ImportError` przy starcie | importy `stol` w `delivery`, `rework_service`, `sync_service`, `mobile_api_service` lokalne w funkcji (jak dziś `blokady_zamowien` w `delivery`); `stol.py` nie importuje `mobile_api_service` (mapy stanowisk z `station_catalog`) |
| Doróbka commituje sama (`rework_service.py:337`) i planuje sygnał w `g` — dekorator wysyła po własnym (pustym) commicie | sygnał idzie, ale ewentualny błąd między commitem doróbki a dekoratorem nie cofa doróbki (stan sprzed K3) | zachowanie bez zmian; zapisz w raporcie jako znaną usterkę spoza zakresu (4.4a też ją zgłosił) |
| SQLite nie egzekwuje FK CASCADE (`db.session.delete(product)` zostawia wiersz stołu) | test Base. padnie, jeśli liczyć na kaskadę | `zdejmij_nieaktualne` usuwa wiersze stołu pozycji nieobecnych w `order.products` (Task 1); na MySQL kaskada robi to samo wcześniej |
| Stara appka dostaje 409 `nie_na_stole` zamiast zachowania `stary`, bo tablet nie wysłał heartbeatu, a próg > 0 | praca z kolejki offline czeka | próg 0 do czasu wydania appki (K7); 409 jest w `BLEDY_DO_PONOWIENIA`, więc akcja nie przepada |
| Padający test spoza zakresu, spór spec ↔ kod, MySQL 1213 przy oględzinach | — | **STOP**: opis w raporcie, meldunek do centrali, bez obejść i bez wyłączania testów (podręcznik, sekcja 6) |

## Pytania do Konrada

Brak pytań blokujących start. Do potwierdzenia przy bramce K3/K5 (plan przyjmuje wartości domyślne):
1. Kolejność blokad `dopelnij` (zamówienia `FOR SHARE` rosnąco → pozycje) zamiast „FOR SHARE pozycje bez blokad zamówień”
   ze spec 9.4 — Doprecyzowania p. 1 (rekomendacja: tak, kolejność kanoniczna; K5 mierzy czas `desk`).
2. `postpone` zwraca stół **bez** dopełnienia (dopełnia `GET desk`, który appka i tak woła po Odłóż) — Task 3.
3. Semantyka progu wersji: `0` = brak bramki wersji, tablet bez heartbeatu = stara appka — Doprecyzowania p. 3.
4. Limit odłożeń „miękki” przy jednoczesnym Odłóż dwóch tabletów jednego stanowiska (może wyjść limit + 1) zamiast odczytu
   bieżącego ze spec 9.2, który dawał zakleszczenia Odłóż ↔ ZAKOŃCZ na tym samym stanowisku — Doprecyzowania p. 13
   (rekomendacja: tak; alternatywa to jedno ponowienie po 1213 w `postpone`, jak w `dostawa_api._zapis`, ale 1213
   zostałby częsty, a K5 wymaga zera).
5. Bramka przepuszcza ZAKOŃCZ/licznik pozycji **każdego** niekompletnego zamówienia na Formatowaniu/Pakowaniu, nie tylko
   K pokazanych w „Niekompletnych” — Doprecyzowania p. 12 (rekomendacja: tak).
6. **Reguła listy Lakierni** (Decyzje p. 9, Task 5a; propozycja centrali przyjęta jako obowiązująca): grupa = (rodzaj,
   kolor, połysk), grupy po najpilniejszej pozycji, w grupie ranga, doróbki pierwsze (doróbka ciągnie swoją grupę na
   początek), bez limitu w grupie, pozycje w innych statusach na końcu — potwierdzenie przy bramce K3.

## K3-poprawka-1 (karta naprawcza po bramce K3, 5.10) — Taski sesji naprawczej

Zakres z karty (decyzje Konrada / centrali po bramce K3; spec już je zawiera: 5.1, 5.2, 5.4, 5.6, 5.8, 6.1, 13 P-13).
Baza `2634c5b8`. Każdy Task: test → RED → kod → GREEN → commit → `git pull --rebase` → push. Jeden commit na punkt
(P6 dołącza do P5). Reguły pakowania bez sposobu dostawy (409 `delivery_method_not_set`) NIE ruszamy.

### Task P1: Start stołów tylko z licznika (spec 5.8)

**Pliki:** `priorytety/services/stol.py` (`_rozpoczete`, `rozpoczete_na_stanowisku`, komentarz sekcji; `_zrobione_recznie`
znika albo zmienia rolę), `tests/test_priorytety_stol.py`, `tests/test_priorytety_panel_api.py` (`GET /start`).

- [x] Testy (RED): `test_rozpoczete_tylko_z_licznika_pozycja` (pozycja w statusie S z licznikiem S > 0 → kafel, powód
      `licznik`; inna pozycja tego zamówienia w statusie S bez licznika → brak kafla, choć trzecia pozycja zamówienia
      była już ręcznie zrobiona na S), `test_rozpoczete_tylko_z_licznika_zamowienie` (Formatowanie: zamówienie z pozycją
      w statusie S z licznikiem > 0 → kafel `o:`; zamówienie, którego inna pozycja przeszła już S, a te czekające mają
      licznik 0 → brak), `test_przygotuj_start_bez_reguly_zamowienia`. Poprawić testy K3 pilnujące powodu `zamowienie`
      (wpis w raporcie).
- [x] Kod: `_rozpoczete` — kafel wyłącznie z licznika; `powod` zawsze `licznik` (pole zostaje w `GET /start`).
- [x] Pomiar na `priorytety_podglad` (tylko odczyt): kafle startowe per stanowisko (oczekiwane ~21) → raport.

### Task P2: Doróbki w ramach K (spec 5.1)

**Pliki:** `stol.py` (`dopelnij`, docstringi `_kandydaci`/`dopelnij`), `stale.py` (komentarz źródeł),
`tests/test_priorytety_stol.py`, ew. `tests/test_priorytety_sygnaly.py` (opis).

- [x] Testy (RED): `test_dopelnij_dorobka_w_ramach_k` (K = 2, dwie doróbki i zwykła pozycja → na stole 2 doróbki ze
      źródłem `dorobka`, starsza pierwsza; trzy doróbki przy K = 2 → wchodzą dwie, trzecia czeka w kolejce i liczy się
      do `kolejka_dalej`), `test_dopelnij_dorobka_nie_wchodzi_na_pelny_stol` (stół pełny kaflami `kolejka` → doróbka
      czeka; po zejściu kafla wchodzi jako pierwsza, przed zwykłą pozycją), `test_dopelnij_formatowanie_dorobka_
      kompletna_w_ramach_k`. Poprawić `test_dopelnij_dorobka_ponad_k`, `test_dopelnij_formatowanie_dorobka_kompletna_
      ponad_k` (wpis w raporcie).
- [x] Kod: jedna lista kandydatów „doróbki, potem kolejka”, obcięta do `miejsca − na_stole`; źródło wiersza `dorobka`
      dla doróbek, kolejność na stole bez zmian (`uporzadkuj`).

### Task P3: Kompletność bez pozycji omijających stanowisko (spec 5.6 p. 2)

**Reguła ścieżki — z kodu routingu, nie z nazwy:** `order_timeline_service.product_in_route(pozycja, stanowisko)`
(ta sama reguła co `ProductionProduct.complete_task`: `should_skip_formatting` = `cut_to_size is False` omija
Formatowanie i Krawędzie, `should_skip_edges` omija Krawędzie; Pakowania nie omija nic). Pozycja omijająca S, która
mimo to STOI w statusie S (ręczna zmiana statusu), liczy się normalnie.

**Pliki:** `kolejka.py` (`kompletne_na_stanowisku`, `kandydaci_stanowiska`, `_kafle_zamowien`, nowa czysta
`liczone_na_stanowisku`), `widok.py` (`omijajace_stanowisko`, `_dane_stanowiska`, `_kafel_zamowienia`, `_stanowisko_
zamowienia`, kolumny pozycji), `stol.py` (`kompletne_na`, `_aktualny`, `_kandydaci`), testy: `test_priorytety_kolejka.py`,
`test_priorytety_stol.py`, `test_priorytety_panel_api.py`, `test_priorytety_mobile.py`.

- [x] Testy (RED), przykład z pytania 8 raportu K3 (zamówienie: A z docięciem czeka na Formatowaniu, B bez docięcia
      stoi na Sklejaniu): `test_kompletne_na_stanowisku_pomija_omijajace`, `test_kandydaci_pozycja_omijajaca_nie_
      blokuje_kompletnosci` (kafel w `kafle`, nie w `niekompletne`; na Pakowaniu ta sama pozycja nadal blokuje),
      `test_kandydaci_niekompletne_bez_omijajacych_w_liczniku_i_brakuje`, `test_dopelnij_formatowanie_pozycja_
      omijajaca_nie_trzyma_w_niekompletnych`, `test_zdejmij_nieaktualne_zostawia_kafel_gdy_wczesniej_tylko_omijajaca`,
      `test_bramka_zakoncz_zamowienie_kompletne_mimo_omijajacej` (409 `nie_na_stole` — zamówienie jest kompletne, więc
      musi leżeć na stole), panel: `test_kolejka_formatowania_pomija_pozycje_omijajaca`, `desk`: sekcja
      „Niekompletne” pusta dla przykładu.
- [x] Kod wg listy plików; `rozpoczete` (tag) bez zmian — patrzy na statusy.

### Task P4: `pracownik` „Adam K.” na tablecie (spec 6.1)

**Pliki:** `stol.py` (`imie_z_inicjalem`), `routers/mobile_api.py` (`_odpowiedz_stolu`), `tests/test_priorytety_mobile.py`.

- [x] Testy (RED): `test_imie_z_inicjalem` (pełne, samo imię, samo nazwisko, puste, nazwisko dwuczłonowe, białe znaki),
      `desk` i `postpone` oddają „Adam K.”; panel (`/stoly`, `/odlozenia`) dalej „Adam Kowalski” (testy K3 bez zmian).
- [x] Kod: format w jednym miejscu, użyty w odpowiedzi stołu.

### Task P5 (+ P6): Brakujące sygnały i sygnał przed HTTP do Base.

**Pliki:** `logistics/routers/weryfikacja_api.py` („Cofnij do pakowania” — plan w `g`, wysyła `with_idempotency`),
`logistics/routers/panel_api.py` (zmiana sposobu dostawy cofająca do pakowania — po commicie routera),
`services/sync_service.py` (import nowych zamówień — po commitach importu), `services/mobile_api_service.py`
(P6: `sygnaly.wyslij()` tuż po commicie, przed hakiem statusu Base.), `tests/test_priorytety_sygnaly.py`.

- [x] Testy (RED): `test_cofnij_do_pakowania_sygnal_packaging_po_commicie`, `test_cofnij_do_pakowania_odmowa_bez_
      sygnalu`, `test_przepakowanie_z_panelu_sygnal_packaging`, `test_zmiana_sposobu_bez_przepakowania_bez_sygnalu`,
      `test_import_nowych_zamowien_sygnal_na_stanowiska_startowe`, `test_import_bez_nowych_pozycji_bez_sygnalu`,
      P6: `test_sygnal_stanowiska_przed_hakiem_base` (kolejność: commit → sygnał → `flush_pending_syncs`).
- [x] Kod wg wzoru K3: nigdy w transakcji; panel i import — `sygnaly.wyslij(kody)` po commicie.

### Task P7: Pełny pakiet, składnia 3.9, raport

- [x] `docker ps` (inny `priorytety-app-run-*` → czekać) → pełny pakiet 0 failed; składnia 3.9 zmienionych plików.
- [x] Raport `raporty/2026-10-05-priorytety-krok-K3-poprawka-1-raport.md`, commit, push.

## K3-poprawka-2 (karta naprawcza przed K5, 5.10) — Taski sesji naprawczej

Rozstrzygnięcia 19 i 22 dziennika centrali. Punkt wyjścia `b991db9d` (po scaleniu logistyki 4.6).

### Task Q1: `desk` oddaje `tryb`; w `stary` bez dopełniania (rozstrz. 19, spec 6.1, 6.3)

**Pliki:** `modules/production/routers/mobile_api.py` (`station_desk`, `_odpowiedz_stolu`, `_etag_stolu`,
`KSZTALT_ODPOWIEDZI_STOLU` → 2), `tests/test_priorytety_mobile.py`, testy `desk` zakładające dopełnianie w domyślnym
trybie (`test_priorytety_stol.py`, `test_priorytety_sygnaly.py`, `test_priorytety_lista_lakierni.py`).

- [x] Testy (RED): `test_desk_oddaje_tryb` (`stary` domyślnie, `stol` po ustawieniu; pole też w `postpone`),
      `test_desk_stary_nie_dopelnia_i_nie_blokuje` (zero INSERT, zero `FOR UPDATE`, zero commitu z zapisem —
      asercja na zapytaniach; kafle startowe widoczne tylko do odczytu), `test_desk_stol_dopelnia` (jak dotąd),
      `test_desk_przelaczenie_trybu_miedzy_wywolaniami` (`stary` → `stol` → `stary`: ETag różny, stół dopełniony dopiero
      w `stol`, po powrocie bez nowych wierszy), `test_desk_stary_bez_sygnalu`, ETag zależny od trybu i od
      `KSZTALT_ODPOWIEDZI_STOLU`; Lakiernia 409 `stanowisko_bez_stolu` bez zmian.
- [x] Kod: tryb czytany przed dopełnieniem (zwykły odczyt w transakcji żądania); `stary` → bez commita, blokady,
      limitu czekania i ponowienia 1213 — tylko odczyt; `tryb` w ciele i w ETagu; kształt → 2.
- [x] Istniejące testy `desk` z dopełnianiem dostają jawne `tryb = stol`.

### Task Q2: 409 `pozycja_poza_stanowiskiem` przy ZAKOŃCZ i liczniku (rozstrz. 22, spec 5.5)

**Pliki:** `modules/production/priorytety/services/stol.py` (`bramka_zakoncz`), `routers/mobile_api.py`
(komentarze przy bramkach), `tests/test_priorytety_stol.py`.

- [x] Testy (RED): Formatowanie i Pakowanie — kafel-zamówienie na stole z pozycjami w różnych statusach: ZAKOŃCZ
      i licznik pozycji spoza statusu → 409 `pozycja_poza_stanowiskiem` z `message` („Pozycja 1203_4 nie czeka na
      Pakowaniu.”), pozycji w statusie → 200; pozycja omijająca stanowisko → 409; stanowisko pozycyjne (Sklejanie)
      — pozycja dalej niż stanowisko → 409 `pozycja_poza_stanowiskiem` (nie `nie_na_stole`); tryb `stary`, stara appka,
      Lakiernia → bez zmian (200 jak dotąd); 409 bez wpisu idempotencji i bez zapisu (status pozycji nietknięty).
- [x] Kod: kontrola statusu w `bramka_zakoncz` po trybie i wersji appki, przed odczytem wiersza stołu; ZAKOŃCZ — na
      pozycji z blokady zamówienia (odczyt bieżący), licznik — zwykły odczyt jak dotąd.
- [x] Grep testów K3/logistyki: ZAKOŃCZ/licznik pozycji spoza statusu w trybie `stol` — wynik w raporcie.

### Task Q3: Kontrakt appki i karta appki

**Pliki:** `docs/api-mobile-priorytety.md`, `docs/superpowers/plans/2026-10-05-priorytety-karta-appki.md`.

- [x] Akapity [K3-poprawka-2] → opis kodu z odnośnikami na końcowym hashu kodu; nagłówek → nowy hash.
- [x] 409 `pozycja_poza_stanowiskiem` w §6, §10 (porzucić, komunikat, `GET desk`), §14 (punkt checklisty).
- [x] Po 4.6: Pakowanie bez sposobu dostawy — zwykły kandydat (stół, „Niekompletne”, `kolejka_dalej`, „Wyślij”,
      start); otwarte pytanie zamknięte; przesunięte odnośniki `mobile_api.py`.
- [x] Sprawdzacz odnośników (scratchpad) — `bledow 0`.
- [x] Karta appki: hashe, punkt 13 f), akapit [K3-poprawka-2], spójność 409.

### Task Q4: Pełny pakiet, składnia 3.9, raport

- [x] `docker ps` (inny `priorytety-app-run-*` → czekać) → pełny pakiet 0 failed; składnia 3.9 zmienionych plików.
- [x] Raport `raporty/2026-10-05-priorytety-krok-K3-poprawka-2-raport.md`, commit, push.
