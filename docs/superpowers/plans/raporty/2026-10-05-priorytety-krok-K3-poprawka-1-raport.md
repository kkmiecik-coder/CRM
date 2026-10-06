# Raport karty naprawczej K3-poprawka-1 — program „Priorytety produkcji”

- **Karta:** K3-poprawka-1 (decyzje Konrada / centrali 5.10 po bramce K3; dziennik centrali, rozstrzygnięcie 14).
- **Plan:** `docs/superpowers/plans/2026-10-05-priorytety-krok-K3-stol-odloz-sygnaly.md`, sekcja „K3-poprawka-1” (Taski
  P1–P7 dopisane PRZED kodem, commit `51c1262f`; wszystkie kroki `- [x]`).
- **Spec:** `docs/superpowers/specs/2026-10-04-priorytety-produkcji-design.md` w wersji po bramce K3 (5.1, 5.2, 5.4, 5.6,
  5.8, 6.1) — bez zmian w tej karcie.
- **Gałąź:** `claude/priorytety-produkcji`, start `2634c5b8` (zgodny z kartą). Worktree
  `.claude/worktrees/priorytety-produkcji`; `main` i główny checkout nietknięte.
- **Data:** 2026-10-05. **Sesja:** lokalna, effort high, bez trybu szybkiego. **Model:** środowisko na starcie
  przedstawiło sesję jako Opus 5.5 i po pierwszym poleceniu poprawiło na **Fable 5.1 (`claude-fable-5-1`)** — model z
  karty; cała praca nad kodem poszła na Fable 5.1.

## Zrobione (po punktach karty)

| Punkt | Commit | Co weszło |
|---|---|---|
| plan | `51c1262f` | Taski P1–P7 w planie K3 (sekcja „K3-poprawka-1”), przed pierwszą linią kodu. |
| 1 | `db15090b` | **Start stołów tylko z licznika.** `stol._rozpoczete`: kaflem startowym jest wyłącznie pozycja w statusie stanowiska z licznikiem `quantity_done_<S>` > 0 (jednostka `zamowienie` — zamówienie z taką pozycją). Reguła „inna pozycja zamówienia już zrobiona na S” usunięta razem z `_zrobione_recznie` i `ZRODLA_RECZNE` (jedno zapytanie do `prod_station_events` mniej). Pole `powod` w `GET /start` zostaje, zawsze `licznik`. |
| 2 | `99486d9f` | **Doróbki w ramach K.** `stol.dopelnij`: jedna lista „doróbki, potem kolejka” obcięta do `miejsca − na_stole`; doróbka nie wchodzi już ponad K, wchodzi pierwsza przy najbliższym dopełnieniu, źródło wiersza dalej `dorobka`, kolejność na stole bez zmian (`uporzadkuj`). `kolejka_dalej` liczy też doróbki, które nie weszły. |
| 3 | `33b93187` | **Kompletność bez pozycji omijających stanowisko.** Nowa czysta `kolejka.liczone_na_stanowisku(pary, S, omijajace)`; `kolejka.kompletne_na_stanowisku(statusy, S, omija=None)` i `kolejka.kandydaci_stanowiska(..., omijajace=None)`; reguła ścieżki `widok.sciezka_omija(pozycja, S)` / `widok.omijajace_stanowisko(S, pozycje)`; wpięte w stół (`stol.kompletne_na`, `_aktualny`, `_kandydaci` → dopełnienie, `stan`, „Niekompletne”, bramka ZAKOŃCZ, `zdejmij_nieaktualne`) i w panel (`widok._dane_stanowiska`, `pozycji` kafla zamówienia, modal priorytetu). Szczegóły niżej. |
| 4 | `990e6481` | **`pracownik` „Adam K.” na tablecie.** `stol.imie_z_inicjalem(imie, nazwisko)`, użyte w `_odpowiedz_stolu` (`GET desk` i odpowiedź `postpone`). Panel (`/stoly`, `/odlozenia`, modal) bez zmian — pełne imię i nazwisko. |
| 5 + 6 | `82dfce11` | **Brakujące sygnały:** `station:packaging` po „Cofnij do pakowania” (handler planuje w `g`, `with_idempotency` wysyła po commicie) i po zmianie sposobu dostawy cofającej do pakowania (router panelu Logistyki, po commicie, jeden sygnał na żądanie); `station:cutting` + `station:assembly` po imporcie nowych zamówień z Base. (`process_orders_with_priority_logic`, po commitach pozycji). **D3:** w `with_idempotency` sygnały stanowisk idą jako pierwsze po commicie, PRZED hakiem statusu Base. (zmiana kolejności dwóch bloków — bez przebudowy). |
| 7 | (ten commit) | Pełny pakiet, składnia 3.9, pomiary na `priorytety_podglad`, raport. |

**Zmienione pliki kodu (10):** `priorytety/services/stol.py`, `kolejka.py`, `widok.py`, `priorytety/stale.py` (komentarz),
`routers/mobile_api.py`, `services/mobile_api_service.py`, `services/sync_service.py`, `services/rework_service.py`
(komentarz), `logistics/routers/weryfikacja_api.py`, `logistics/routers/panel_api.py`. Bez migracji, bez nowych końcówek,
bez zmian kształtu JSON poza wartością pola `pracownik` (tablet) i tym, że `powod` w `GET /start` ma jedną wartość.
`KSZTALT_ODPOWIEDZI_KOLEJKI` i `KSZTALT_ODPOWIEDZI_STOLU` bez zmian (patrz Rozstrzygnięcia p. 9).

### Punkt 3 — reguła ścieżki i gdzie działa

- **Reguła z kodu routingu, nie z nazwy stanowiska:** `widok.sciezka_omija(pozycja, S)` =
  `not order_timeline_service.product_in_route(pozycja, S)` — istniejące odbicie `ProductionProduct.complete_task`
  (parytetu reguły Krawędzi pilnuje `tests/test_krawedzie_parytet_reguly.py`): bez docięcia (`cut_to_size is False`,
  `should_skip_formatting`) pozycja omija Formatowanie i Krawędzie; bez obróbki krawędzi omija Krawędzie; Lakiernia
  tylko dla olejowanych / lakierowanych; Sklejania i Pakowania nie omija nic. Wycinanie i Składanie to jedno wejście
  (`entry`). Dziś regułę zużywają tylko stanowiska z jednostką `zamowienie` (Formatowanie, Pakowanie); gdyby admin
  przestawił na `zamowienie` np. Krawędzie, zadziała bez zmian w kodzie.
- **Co znaczy „nie liczy się”:** pozycja omijająca S znika z listy pozycji liczonych do kompletności S — nie trzyma
  zamówienia w „Niekompletnych”, nie ma jej w `brakuje` i nie wchodzi do mianownika `pozycji` („1/2 na stanowisku”).
  Wyjątek: pozycja omijająca, która mimo to STOI w statusie S (ręczna zmiana statusu w panelu), jest na stanowisku
  i liczy się normalnie. Tag „Rozpoczęte” bez zmian (patrzy na statusy — spec 5.6 p. 1).
- **Przykład z pytania 8 raportu K3** (A z docięciem czeka na Formatowaniu, B bez docięcia stoi na Sklejaniu): zamówienie
  jest teraz na Formatowaniu KOMPLETNE — wchodzi na stół (kafel niesie obie pozycje), sekcja „Niekompletne” go nie ma,
  `zdejmij_nieaktualne` zostawia jego kafel, a bramka ZAKOŃCZ wymaga wiersza stołu (zamówienie nie korzysta już z
  furtki „Niekompletne”). Na Pakowaniu ta sama pozycja B nadal trzyma zamówienie w „Niekompletnych”.
- **Kolumny w odczycie kandydatów:** `cut_to_size`, `parsed_edge_processing`, `parsed_finish_type` dopisane do
  `widok._KOLUMNY_POZYCJI` (z nich korzysta też odczyt bieżący stołu) — bez tego każda pozycja doczytywałaby je osobnym
  zapytaniem, i to w zasięgu limitu czekania `desk` (test `test_dopelnij_nie_doczytuje_kolumn_sciezki`).

## Testy (polecenia i wyniki)

Polecenie (karta), z worktree: `docker compose -p priorytety run --rm --no-deps app pytest <ścieżki> -q -p no:cacheprovider`.
Przed pełnym pakietem `docker ps` — biegł przebieg innej sesji (`priorytety-app-run-*`), poczekałem do jego końca.

| Co | Wynik |
|---|---|
| Punkt wyjścia (bramka K3, `2634c5b8`) | 6592 passed, 3 skipped (pomiar centrali w bramce K3; nie powtarzany) |
| Zestawy po punktach | P1: 269 passed (`test_priorytety_stol`, `_panel_api`) · P2: 363 · P3: 996 (`-k "priorytety or stol or mobile or krawedzie or timeline or dorobka"`) · P4: 335 · P5+P6: 1209 (`-k "priorytety or weryfikacja or mobile or logistyka_panel or sales_ingest or sync or idempot"`) |
| **Pełny pakiet końcowy** | **6661 passed, 3 skipped, 0 failed (7 min 02 s) na `1fdabfe0` (po rebase: zawiera commity K4a / K4b do `8aabdc85`)** |

**Bilans testów tej karty: +25 funkcji testowych** (`test_priorytety_stol` 93 → 101, `_kolejka` 37 → 41, `_mobile` 48 → 51,
`_panel_api` 95 → 96, `_sygnaly` 28 → 30, `_wyzwalacze` 17 → 21, nowy `test_priorytety_sygnaly_import.py` 3). Reszta
przyrostu pełnego pakietu względem 6592 to testy K4a / K4b, które w tym czasie weszły na gałąź. Żaden test nie został
wyłączony.

**TDD:** każdy punkt test → RED → kod → GREEN. RED obejrzany: P1 — 4 failed; P2 — 3 failed (sprawdzone na kodzie sprzed
zmiany, po napisaniu obu naraz); P3 — 11 failed; P4 — 3 failed; P5+P6 — 4 failed.

**Testy K3 poprawione, bo pilnowały reguł zmienionych decyzjami 5.10** (wymóg karty — wpis):

| Test K3 | Co się stało | Dlaczego |
|---|---|---|
| `test_rozpoczete_pozycja_gdy_inna_zrobiona_recznie` | zastąpiony `test_rozpoczete_tylko_z_licznika_pozycja` (odwrócona asercja) | pilnował reguły „inna pozycja zamówienia zrobiona na S” (p. 1) |
| `test_rozpoczete_pomija_auto_skip_i_system` | zastąpiony `test_rozpoczete_tylko_z_licznika_zamowienie` | reguła zdarzeń ręcznych odpadła razem z regułą zamówienia; nowy test pilnuje, że ani zdarzenie automatu, ani ręczne na INNEJ pozycji nie robi kafla |
| `test_rozpoczete_zamowienie_na_formatowaniu` | oczekiwanie zawężone do zamówienia z licznikiem | p. 1 |
| `test_dopelnij_dorobka_ponad_k` | zastąpiony `test_dopelnij_dorobka_w_ramach_k` i `test_dopelnij_dorobka_nie_wchodzi_na_pelny_stol` | pilnował „ponad K” (p. 2) |
| `test_dopelnij_formatowanie_dorobka_kompletna_ponad_k` | → `…_w_ramach_k` | p. 2 |
| `test_desk_stol_ma_zrodlo` (`_mobile`) | przy K = 2 zajętym przez `biuro` + `start` doróbka czeka; kolejność źródeł sprawdzana po podniesieniu K do 3 | p. 2 |
| `test_postpone_200_zwraca_stol_z_odlozonym` (`_mobile`) | `pracownik` „Adam K.” | p. 4 |
| `test_dopelnij_przekazuje_szczebel_rozpoczete_i_jednostke`, `test_kolejka_stanowiska_z_kandydatow_k1` | szpiedzy `kandydaci_stanowiska` znają nowy argument `omijajace` | p. 3 |

**Testy mutacyjne** (mutacja reguły w kodzie → wskazane testy muszą poczerwienieć → przywrócenie pliku): P3 **6/6**
(brak kolumn ścieżki w odczycie; stół bez `omijajace`; panel bez `omijajace`; brak wyjątku „stoi na stanowisku”;
`_aktualny` na starej regule; reguła ścieżki uznająca Pakowanie za omijane), P5 **4/4** po wzmocnieniu testu (pierwszy
przebieg: mutant „sygnał w transakcji zamiast planu” PRZEŻYŁ — asercja „jakiś COMMIT przed sygnałem” była za słaba;
fikstura `sygnaly_stanowisk` notuje teraz także zapisy sesji i niezapisane zmiany w chwili sygnału, a asercja
`_tuz_po_commicie` wymaga commitu bezpośrednio przed sygnałem). P1, P2, P4 — bez mutacji (zmiana pokryta odwróconymi
testami K3).

**Składnia 3.9:** `python:3.9-slim` (3.9.25), `ast.parse(feature_version=(3, 9))` + `compile` dla 17 plików `.py`
zmienionych przez tę kartę — 0 błędów.

**MySQL:** karta nie zmienia kolejności ani kształtu żadnego zapytania blokującego (dopełnienie bierze te same blokady;
doszły trzy kolumny w `SELECT` pozycji, ubyło jedno zwykłe zapytanie do zdarzeń w starcie stołów). Na `priorytety_podglad`
wykonane wyłącznie odczyty (pomiary niżej); `priorytety_wyscigi` nietknięta. Wyścigów i Centrifugo nie sprawdzałem (K5).

## Kafle startowe per stanowisko (nowe liczby; `priorytety_podglad`, tylko odczyt)

`stol.rozpoczete_na_stanowisku(S)` po punkcie 1 — same liczby, bez danych klientów.

| Stanowisko | Jednostka | Pozycji w statusie | Zamówień | Pozycji z licznikiem > 0 | **Kafle startowe** (było w K3) |
|---|---|---|---|---|---|
| Wycinanie | pozycja | 22 | 18 | 1 | **1** (7) |
| Składanie | pozycja | 34 | 13 | 0 | **0** (27) |
| Sklejanie | pozycja | 78 | 21 | 15 (z 6 zamówień) | **15** (30) |
| Formatowanie | zamówienie | 51 | 23 | 13 (z 5 zamówień) | **5** (6) |
| Krawędzie | pozycja | 5 | 5 | 0 | **0** (0) |
| Pakowanie | zamówienie | 95 | 66 | 1 (1 zamówienie) | **0** (4) |
| **Razem** | | | | | **21** (74) |

Zgodne z oczekiwaniem karty (~21). Czas policzenia 3–13 ms na stanowisko. Pakowanie: jedyne zamówienie z licznikiem
nie ma sposobu dostawy, więc nie wchodzi (reguła 409 `delivery_method_not_set` — poza zakresem karty). Warunek „licznik
ma zdarzenie ręczne (`mobile` / `web` / `admin`)” policzony obok dla kontroli: te same liczby na każdym stanowisku.

Przy okazji tego samego odczytu (stan kopii, do porównania w K5): doróbek czekających na Wycinaniu 11, na Składaniu 9,
na Formatowaniu 2, na Pakowaniu 1 — po punkcie 2 pierwszy `desk` kładzie najwyżej K z nich, reszta stoi na początku
kolejki. „Niekompletne”: Formatowanie 4, Pakowanie 7 — bez zmian względem raportu K2, bo na tej kopii żadna pozycja
omijająca Formatowanie nie stoi dziś przed nim w zamówieniu czekającym na Formatowaniu (punkt 3 nie zmienia tu liczb).
W `priorytety_podglad` leżą 4 wiersze stołu Sklejania — nie z tej karty (baza wspólna z podglądami K4a / K4b).

## Odstępstwa

1. **Punkt 2, RED po fakcie:** testy i kod `dopelnij` powstały jednym ruchem; RED obejrzałem na kodzie sprzed zmiany
   (3 failed), przywracając plik z `HEAD` na czas przebiegu.
2. **Punkt wyjścia pełnego pakietu nie był mierzony osobno** — przyjąłem 6592 passed / 3 skipped z bramki K3 (centrala,
   ten sam hash `2634c5b8`); na gałąź wchodziły w tym czasie commity K4a / K4b, więc wynik końcowy jest „po rebase”.
3. **Testy importu w nowym pliku** `tests/test_priorytety_sygnaly_import.py`, na fiksturach z
   `tests/test_sales_ingest_wyzwalacze.py` (ten plik bez zmian — konwencja z K1).
4. **Usunięty kod K3:** `stol._zrobione_recznie`, `stol.ZRODLA_RECZNE` (martwe po punkcie 1), `widok._liczone`
   (zastąpione `kolejka.liczone_na_stanowisku`).

## Rozstrzygnięcia podjęte w trakcie (numerowane; koszt, jeśli błędne)

1. **Start stołów: licznik bez sprawdzania źródła zdarzenia.** Spec 5.8 mówi „licznik > 0 (z tabletu)”. Stanowisko
   pominięte automatem (`auto_skip` / `system`) dostaje licznik w chwili, w której pozycja z niego SCHODZI, więc pozycja
   czekająca na S z licznikiem S to praca ręczna; na kopii danych dodatkowy warunek „ma zdarzenie ręczne” nie zmienia
   ani jednego kafla. — Koszt: przywrócenie warunku to jedno zapytanie do `prod_station_events` i kilka linii (kod jest
   w historii: `64358f02`).
2. **Doróbki, które nie weszły, liczą się do `kolejka_dalej`** (w `dopelnij` i `stan` ta sama liczba). — Koszt: żaden.
3. **Pozycja omijająca znika także z mianownika `pozycji` i z `brakuje`,** nie tylko z decyzji o kompletności — żeby
   „1/2 na stanowisku” zgadzało się z tym, co na stanowisko rzeczywiście dojdzie. — Koszt: jedna funkcja
   (`kolejka.liczone_na_stanowisku`).
4. **Pozycja omijająca, która STOI w statusie stanowiska, liczy się normalnie** (ręczna zmiana statusu w panelu). —
   Koszt: bez tego wyjątku licznik pokazałby np. „2/1”.
5. **Reguła ścieżki = `order_timeline_service.product_in_route`,** nie własna kopia w pakiecie priorytetów (trzecia
   kopia reguły Krawędzi rozjechałaby się z `complete_task`). — Koszt: zmiana routingu wymaga zmiany w dwóch istniejących
   miejscach, jak dotąd; priorytety idą za osią czasu zamówienia.
6. **Sygnatury:** `kompletne_na_stanowisku(statusy, S, omija=None)` — flagi równoległe do `statusy` (funkcja z K1
   przyjmuje same statusy; wołania K1 / K2 działają bez zmian); `kandydaci_stanowiska(..., omijajace=None)` — zbiór id
   pozycji. Zbiór liczy wołający (`widok.omijajace_stanowisko`), bo czysta kolejka nie zna modelu pozycji. — Koszt:
   wołający, który nie poda `omijajace`, dostaje starą regułę (dziś dwa miejsca: stół i panel, oba pod testami).
7. **`imie_z_inicjalem`:** samo imię → imię; samo nazwisko → inicjał („K.”); nic → `null`; inicjał wielką literą,
   nazwisko dwuczłonowe → pierwsza litera. — Koszt: format pola.
8. **Sygnał po przepakowaniu: jeden na żądanie i tylko, gdy coś wróciło do pakowania** (`przepakowanie` niepuste);
   zwykła zmiana sposobu dostawy bez cofnięcia sygnału NIE wysyła (karta: „zmiana sposobu dostawy cofająca do
   pakowania”) — patrz Pytania p. 1. Sygnał idzie przed `bl_sync.po_zmianie` i przeliczeniem rang. — Koszt: jedna linia.
9. **Sygnał po imporcie: zawsze oba stanowiska startowe** (`cutting`, `assembly`), gdy import utworzył choć jedną
   pozycję — bez ustalania, na które stanowisko trafiły (mikrowczep / lity). Nadmiarowy sygnał to jedno `GET desk`
   z odpowiedzią 304. Idzie po przeliczeniu rang (`utrwal`), żeby tablet pobrał stół już z nowymi rangami. — Koszt:
   dokładne stanowiska wymagałyby zbierania statusów w pętli importu (kilkanaście linii w najdłuższej metodzie serwisu).
10. **D3 zrobione przestawieniem bloków w `with_idempotency`:** sygnały stanowisk → hak Base. → sygnał agenta druku →
    dopychacz logistyki → `utrwal`. Sygnał idzie więc PRZED przeliczeniem rang zaplanowanym przez handler („Cofnij do
    pakowania”, Dostawa) — tablet może pobrać stół z rangą sprzed przeliczenia; kafle na stole i tak się nie przestawiają
    (spec 5.1), a następne dopełnienie widzi nowe rangi. — Koszt: przeniesienie `sygnaly.wyslij()` za `utrwal` to
    przestawienie jednego bloku (wraca wtedy czekanie na HTTP do Base.).
11. **`KSZTALT_ODPOWIEDZI_*` bez podbicia.** Zmieniła się wartość pola `pracownik` w `desk` (nie zestaw pól) i reguły
    doboru kafli; ETag `desk` zmienia się sam, gdy zmieni się zawartość stołu. Tablet z zapamiętanym ETagiem i
    odłożonym kaflem mógłby raz dostać 304 ze starym „Adam Kowalski” — ale nowej appki jeszcze nie ma, a stara `desk`
    nie woła. — Koszt: podbicie `KSZTALT_ODPOWIEDZI_STOLU` to jedna linia i jeden test.
12. **Komentarze w sąsiednich plikach poprawione** („ponad K” przy doróbce: `stale.py`, `rework_service.py`, docstring
    testu sygnału doróbki) — sam tekst, bez zmiany zachowania.

## Pytania do Konrada

1. **Sygnał po zwykłej zmianie sposobu dostawy.** Zamówienie czekające na Pakowaniu bez sposobu dostawy nie wchodzi na
   stół; gdy logistyka ustawi sposób, staje się kandydatem, ale tablet dowie się o tym dopiero z siatki odpytywania
   (30 s przy pustym stole, 5 min przy niepustym). Karta kazała dać sygnał tylko przy cofnięciu do pakowania — dopisać
   go też tutaj (jedna linia), czy zostawić, skoro reguła „bez sposobu dostawy” i tak ma zniknąć (rozstrzygnięcie 15
   centrali)?
2. **„Niekompletne” przy pozycji bez docięcia — czy pracownik Formatowania ma widzieć, że zamówienie ma jeszcze pozycję
   „w drodze do pakowania”?** Dziś kafel zamówienia na Formatowaniu niesie wszystkie pozycje (także tę bez docięcia, ze
   statusem Sklejania), ale nic jej nie wyróżnia. To pytanie do kontraktu appki (K6), nie blokuje.

## Stan gałęzi

- `claude/priorytety-produkcji`, ostatni commit kodu tej karty `82dfce11` (+ `1fdabfe0`, poprawka jednej asercji testu); commit raportu — hash w odpowiedzi sesji.
  Wypchnięte po każdym commicie (`git pull --rebase` przed pushem — bez konfliktów; w międzyczasie weszły commity K4a
  i K4b, pliki rozłączne).
- `main` nietknięty; główny checkout nie zmieniał gałęzi; drzewo robocze worktree czyste (pusty `config/core.json` po
  `docker run` kasowany).

## Co następny krok musi wiedzieć

### K4a / K4b (w toku, ta sama gałąź)

- `GET /start`: `powod` ma już tylko wartość `licznik` (pole zostaje). Jeśli UI rysuje osobną plakietkę dla `zamowienie`
  — nie pojawi się.
- `GET /stoly`: doróbka nie jest już „ponad K” — stół bywa dłuższy niż K tylko przez kafle `biuro` i `start`.
- `widok._liczone` usunięte → `kolejka.liczone_na_stanowisku(pary, stanowisko, omijajace)`; `widok._dane_stanowiska`
  oddaje dodatkowo `stanowisko` i `omijajace`.
- Monitory hali (K4b, decyzja Konrada „Adam K. na tablecie i monitorze”): format daje `stol.imie_z_inicjalem(imie,
  nazwisko)`; panel zostaje przy pełnym nazwisku.

### K5 (przegląd P1, wyścigi)

- Tryb `desk-dorobka`: doróbka wchodzi w ramach K — przy pełnym stole `desk` jej NIE kładzie (oczekiwania scenariusza
  do poprawienia razem z błędnym stanowiskiem powrotu, już zapisanym w raporcie K3).
- Nowy pisarz-sygnalista bez zmian blokad: „Cofnij do pakowania” planuje `station:packaging`; tryb
  `weryfikacja-cofnij-desk` z raportu K3 może teraz sprawdzić także sygnał na podglądzie z brokerem.
- D3 z listy drobnych K3 jest zrobione (kolejność w `with_idempotency`); zostają D2, D5, D6, D8–D11. D5 (sygnał
  doróbki planowany po jej własnym commicie przepada przy wyjątku dalszej części handlera) — bez zmian.
- Do CLAUDE.md (sekcja priorytetów): „zamówienie kompletne na stanowisku” = bez pozycji, których ścieżka omija
  stanowisko (`widok.sciezka_omija`); nowy czytelnik kompletności MUSI podać `omijajace` / `omija`, inaczej wróci
  stara reguła.
- Rozjazd tekstu specu z kodem do domknięcia: 5.8 „(z tabletu)” — kod nie sprawdza źródła licznika (Rozstrzygnięcia
  p. 1); 5.4 nie wymienia w tabeli trzech nowych sygnałów (cofnięcie, przepakowanie, import).
- Liczba kafli startowych do powtórzenia na świeżej kopii produkcji: dziś 21 (tabela wyżej).

### K6 (kontrakt appki)

- `desk` / `postpone`: `pracownik` = „Adam K.” (imię + inicjał nazwiska) albo `null`.
- **Stół jest dłuższy niż `miejsca` tylko przez kafle `biuro` i `start`;** doróbka (`zrodlo: "dorobka"`) wchodzi w ramach
  `miejsca`, zawsze jako pierwsza z kolejki, i na stole stoi na początku.
- **Kafel zamówienia na Formatowaniu może nieść pozycję, która na Formatowanie nie przyjdzie** (bez docięcia, status
  wcześniejszego stanowiska, `cut_to_size: false`) — zamówienie jest mimo to kompletne i da się je zakończyć; sekcja
  „Niekompletne” i `brakuje` takich pozycji nie pokazują, `pozycji` ich nie liczy.
- **Sygnał `station:<kod>` przychodzi dodatkowo:** `station:packaging` po „Cofnij do pakowania” (Weryfikacja) i po
  zmianie sposobu dostawy cofającej do pakowania; `station:cutting` i `station:assembly` po imporcie nowych zamówień.
  Zalecenie z raportu K3 (odpytywać co 30 s także przy stole krótszym niż `miejsca` i `kolejka_dalej > 0`) zostaje —
  zgubiony sygnał i zwykła zmiana sposobu dostawy (Pytania p. 1) dalej nadrabia siatka.
- Sygnał po ZAKOŃCZ przychodzi teraz przed wysyłką statusu do Base. (szybciej o czas HTTP do Base. przy ZAKOŃCZ
  kończącym zamówienie).

### K7 (wdrożenie)

- Start stołów: na kopii danych 21 kafli (Sklejanie 15, Formatowanie 5, Wycinanie 1); resztę „w rękach” biuro dokłada
  „Wyślij” na podstawie podglądu `GET /start`.
- Zaległe doróbki pierwszego dnia (dziś 11 na Wycinaniu, 9 na Składaniu) wchodzą po K naraz i stoją przed całą
  kolejką — stanowiska startowe zaczną dzień od doróbek.
