# Raport — karta naprawcza K3-poprawka-2 (program „Priorytety produkcji”)

Sesja lokalna, worktree `.claude/worktrees/priorytety-k3p2`, gałąź robocza `claude/priorytety-k3p2` → push na
`claude/priorytety-produkcji`. Model: **Opus 5.5** (karta zakładała Fable 5.1), effort high, bez trybu szybkiego.
Punkt wyjścia `b991db9d` (po rebase: `22f9fd78`, wpis dziennika centrali). Taski Q1–Q4 w planie
`2026-10-05-priorytety-krok-K3-stol-odloz-sygnaly.md`, sekcja „K3-poprawka-2” — wszystkie odhaczone.

## Zrobione

| Task | Commit | Co |
|---|---|---|
| Q1 | `9a72d056` | `GET desk` oddaje `tryb` (`"stary"` \| `"stol"`, z `ustawienia.tryb`). W `stary` handler jest zwykłym odczytem: bez commita, blokady stanowiska, limitu czekania, ponowienia 1213 i zapisów — oddaje bieżące wiersze stołu (np. startowe) w tym samym kształcie. Dopełnianie wydzielone do `_dopelnij_stol` i wołane tylko w `stol`. Tryb wchodzi do ETagu stołu, `KSZTALT_ODPOWIEDZI_STOLU` 1 → 2. `tryb` jest też w odpowiedzi `postpone` (wspólne ciało). Lakiernia bez zmian. |
| Q2 | `07710d4c` | `stol.bramka_zakoncz`: w trybie `stol`, dla nowej appki, poza Lakiernią — pozycja, która nie czeka na stanowisku, dostaje **409 `pozycja_poza_stanowiskiem`** („Pozycja 1203_4 nie czeka na Pakowaniu.”), PRZED odczytem wiersza stołu. ZAKOŃCZ sprawdza pozycję z blokady zamówienia (odczyt bieżący), licznik — zwykłym odczytem jak dotąd; oba przed zapisem. Komentarze przy bramkach w routerze. |
| Q3 | `34773e9f`, `f27ffca7` | Kontrakt `docs/api-mobile-priorytety.md`: akapity [K3-poprawka-2] opisują kod z odnośnikami; 409 `pozycja_poza_stanowiskiem` w §1, §3, §6, §10, §11, §13, §14 (punkt 23b); Pakowanie bez sposobu dostawy po `2f3e6ce7` (zwykły kandydat); §15 bez dwóch otwartych pozycji; nagłówek na `07710d4c`. Karta appki: hashe, akapit [K3-poprawka-2], punkt 13 f), punkt odbioru 23b. |
| Q4 | (ten commit) | Pełny pakiet, składnia 3.9, raport. |

## Testy

- **Pełny pakiet** (`docker compose -p priorytety run --rm --no-deps app pytest tests/ -q -p no:cacheprovider`, kod
  `07710d4c`, przed startem `docker ps` — innych `priorytety-app-run-*` nie było): **6818 passed, 3 skipped, 0 failed**
  (punkt wyjścia 6805 + 13 nowych testów).
- **Nowe testy (13):**
  - `tests/test_priorytety_mobile.py`: `test_desk_oddaje_tryb` (także w `postpone`), `test_desk_stary_nie_dopelnia_i_nie_blokuje`
    (asercje na zapytaniach: zero odczytów blokujących, zero ustawień limitu, jedyny zapis i jedyny commit = touch
    urządzenia przed handlerem, `stol.dopelnij` i `zablokuj_stanowisko` nie wołane), `test_desk_stary_bez_sygnalu`,
    `test_desk_stol_dopelnia`, `test_desk_przelaczenie_trybu_miedzy_wywolaniami` (`stary` → `stol` → `stary`, ETag za
    każdym razem inny, 304 tylko bez przełączenia), `test_desk_etag_zalezy_od_trybu_i_ksztaltu_stolu`,
    `test_desk_lakiernia_409_w_obu_trybach`;
  - `tests/test_priorytety_stol.py`: `test_poza_stanowiskiem_pakowanie_kafel_zamowienia_z_pozycjami_w_roznych_statusach`
    (kafel `biuro`, pozycje `czeka_na_pakowanie`/`spakowane`/`czeka_na_krawedzie`; ZAKOŃCZ i licznik; brak wpisu
    idempotencji, statusy i licznik nietknięte), `test_poza_stanowiskiem_formatowanie_niekompletne_zamowienie` (furtka
    „Niekompletne” nie przepuszcza już pozycji ze Sklejania), `test_poza_stanowiskiem_pozycja_omijajaca_stanowisko`,
    `test_poza_stanowiskiem_stanowisko_pozycyjne_przed_nie_na_stole`,
    `test_poza_stanowiskiem_bez_bramki_w_stary_dla_starej_appki_i_lakierni`,
    `test_poza_stanowiskiem_zakoncz_czyta_status_pod_blokada_zamowienia`.
- **Zmienione testy:** 22 istniejące testy `desk` w `test_priorytety_mobile.py` i po jednym w `test_priorytety_stol.py`
  (`test_dopelnij_commit_blokada_stanowiska_zamowienia_pozycje_potem_insert`) i `test_priorytety_sygnaly.py`
  (`test_desk_sygnal_tylko_gdy_dopelnil`) zakładały dopełnianie w domyślnym `stary` — dostały jawne `tryb = stol`.
  `test_desk_w_trybie_stary_dziala` → `test_desk_w_trybie_stary_nie_dopelnia` (nowa semantyka). `POLA_STOLU` + `tryb`.
- **Grep (karta, punkt 3):** żaden test K3 ani logistyki nie zakładał ZAKOŃCZ/licznika pozycji spoza statusu w trybie
  `stol` — testy bramki (`test_bramka_*`, `test_licznik_*`, `test_logistyka_pakowanie_bez_sposobu.py`) przechodzą bez
  zmian; jedyne zmiany w istniejących testach to tryb `stol` dla `desk` (wyżej).
- **MySQL (`priorytety_podglad`, obraz `logistyka3-app`, sieć `woodpower-crm_default`, `core.json` z podglądów):**
  skrypt w scratchpadzie woła `station_desk` bez dekoratora tokena (bez touchu urządzenia), liczy zapytania i blokady
  InnoDB tego połączenia (`performance_schema.data_locks`), na końcu rollback. Wszystkie stanowiska podglądu są w
  `stary`. Wynik:

  | stanowisko | status | `tryb` | zapytań | zapisów | odczytów blokujących | commitów | blokad InnoDB |
  |---|---|---|---|---|---|---|---|
  | gluing | 200 | stary | 18 | 0 | 0 | 0 | 0 |
  | formatting | 200 | stary | 55 | 0 | 0 | 0 | 0 |
  | packaging | 200 | stary | 40 | 0 | 0 | 0 | 0 |
  | cutting | 200 | stary | 18 | 0 | 0 | 0 | 0 |

  Bez trwałych zmian; pusty `config/core.json` z worktree skasowany po uruchomieniu.
- **Składnia 3.9:** `python:3.9-slim` (3.9.25), `ast.parse(feature_version=(3, 9))` + `compile` dla 5 zmienionych
  plików `.py` — ok.

## Kontrakt

- `docs/api-mobile-priorytety.md` @ **`34773e9f`** (karta appki wskazuje ten commit), odnośniki na kod **`07710d4c`**
  (nagłówek §0). Po nim zmieniła się tylko karta appki i ten raport — kod i kontrakt bez zmian.
- Sprawdzacz (`<scratchpad>/sprawdz_odnosniki.py`, wzór z planu K6 + ścieżki `docs/`, bez pomijania [K3-poprawka-2]):
  **358 odnośników, `bledow 0`**.
- Odnośniki przeliczone ze starego hasha `4299267d` skryptem `przelicz_odnosniki.py` (mapa linii z `git diff -U0`);
  31 zakresów w zmienionych miejscach poprawione ręcznie, a wszystkie odnośniki do `mobile_api.py`, `stol.py`
  i `widok.py` przejrzane zrzutem „odnośnik → linia kodu” (sprawdzacz pilnuje tylko kotwic i zakresów).
- Treść: §4 nowa lista „Co robi serwer” (krok 4 = tryb, kroki 5–6 tylko w `stol`), akapit „Pole `tryb`” zamiast „Stan
  docelowy”, pole w tabeli i przykładach JSON (z adnotacją, że doszło po żywym sprawdzeniu); §6 bramka statusu,
  nowy przykład 409 i szablon komunikatu, „dwa tablety, ten sam kafel” → teraz `pozycja_poza_stanowiskiem`, Pakowanie
  bez sposobu — zwykły kandydat z odnośnikami i testami; §10 wiersz tabeli (porzucić, `message`, `GET desk`); §14
  punkt 23b; §15 bez otwartego pytania o Pakowanie i bez zapowiedzi odnośników.

## Odstępstwa

1. **„Kod nie w `BLEDY_DO_PONOWIENIA`”** — niewykonalne dosłownie bez zmiany wspólnego dekoratora: `BLEDY_DO_PONOWIENIA`
   to zbiór **statusów HTTP** (`{400, 403, 404, 409}`), a karta wymaga statusu 409. `pozycja_poza_stanowiskiem` jest
   więc, jak każde 409, niezapamiętywane pod `X-Operation-Id` (rollback). Sens decyzji („appka porzuca wpis”) jest
   zachowany po stronie kontraktu: appka decyduje po polu `error` i porzuca wpis (§10). Zmiany dekoratora na kody
   błędów nie robiłem (poza zakresem, dotyka wszystkich końcówek mobilnych). Koszt: ponowienie z tym samym
   `X-Operation-Id` wykona handler jeszcze raz — dostanie to samo 409 albo (gdyby pozycja wróciła na stanowisko)
   przejdzie; appka zgodna z kontraktem i tak go nie ponawia.
2. Punkt 4 zakresu w **dwóch commitach** (kontrakt, potem karta appki) — karta musi wskazać hash commita kontraktu.
3. Testy Q2 tylko w `tests/test_priorytety_stol.py` (plan wymieniał też `test_priorytety_mobile.py`) — bramka i jej
   pomocniki mieszkają tam; plan poprawiony.
4. Model Opus 5.5 zamiast Fable 5.1 (ustawienie sesji).

## Rozstrzygnięcia

1. **Tryb w ETagu, nie tylko podbity kształt.** Samo `KSZTALT_ODPOWIEDZI_STOLU = 2` unieważnia stare ETagi raz, ale
   przełączenie trybu w Konfiguracji nie zmienia żadnego wiersza pozycji ani stołu — bez trybu w ETagu tablet w
   `stary` dostawałby 304 i nie wykryłby „Włącz stoły”. Koszt: żaden (jedno 200 więcej po przełączeniu).
2. **Tryb czytany zwykłym odczytem przed dopełnieniem** (w transakcji żądania, ustawienia bez pamięci podręcznej). Koszt
   wyścigu z przełączeniem w panelu: najwyżej jedno dopełnienie „w starym trybie” albo jedno pominięte.
3. **`tryb` także w odpowiedzi `postpone`** (wspólne `_odpowiedz_stolu`, kontrakt: „ciało jak w `GET desk`”). Koszt: żaden.
4. **Bramka statusu przed wierszem stołu** — także na stanowisku pozycyjnym pozycja, która poszła dalej, dostaje kod
   konkretny zamiast `nie_na_stole`. Pierwsza gałąź reguły `nie_na_stole` z §10 staje się rzadka (zostaje w kontrakcie
   na zmianę statusu między odpowiedziami). Koszt, jeśli błędne: appka dostaje inny kod niż dotąd w tym przypadku —
   obie ścieżki kończą się porzuceniem wpisu.
5. **Bramka statusu w `bramka_zakoncz`** — dziedziczy warunki bramki stołu (tylko `stol`, tylko nowa appka wg progu,
   nigdy Lakiernia), zgodnie z kartą. Koszt: żaden.
6. Komunikat z `short_product_id`, zapasowo `#<id>`; nazwa stanowiska w miejscowniku (`_NAZWA_MIEJSCOWNIK`).
7. **Ponowne ZAKOŃCZ Pakowania pozycji już `spakowane` z NOWYM `X-Operation-Id` w trybie `stol`** dostaje 409 (dawniej
   handler przechodził i wołał `po_spakowaniu`, które może zdjąć `repack_required`). Z tym samym `X-Operation-Id`
   działa powtórka zapamiętanej odpowiedzi 200 jak dotąd. Koszt: tylko wpis starszy niż retencja idempotencji (7 dni)
   albo appka łamiąca kontrakt — przepakowanie i tak cofa pozycję do `czeka_na_pakowanie`.
8. **Dwa ZAKOŃCZ tej samej pozycji z dwóch tabletów** — drugie widzi pod blokadą pozycję w statusie następnego
   stanowiska i dostaje `pozycja_poza_stanowiskiem` także na stanowisku zamówieniowym (dawniej tam przechodziło).
   W kontrakcie opisane jako oczekiwane, „do potwierdzenia przez K5”. Koszt, jeśli wyścig na MySQL wygląda inaczej:
   poprawka akapitu §6.
9. **Sprawdzenie na MySQL wołaniem handlera bez dekoratora tokena** — żeby nie dotknąć `last_seen_at` istniejącego
   urządzenia (bez trwałych zmian w bazie podglądu). Touch urządzenia (jedyny zapis żądania `desk` w `stary`) pokrywa
   test na SQLite. Koszt: żaden.
10. **Hash w nagłówku kontraktu = hash kodu** (`07710d4c`), jak w K6 (`4299267d`), nie commita kontraktu. Koszt: żaden.

## Pytania do Konrada

Brak blokujących.

## Stan gałęzi

- `claude/priorytety-produkcji` @ commit tego raportu (hash w odpowiedzi sesji), wypchnięte po każdym commicie
  (rebase bez konfliktów). Commity karty: `9a72d056`, `07710d4c`, `34773e9f`, `f27ffca7`, raport.
- `main` nietknięty. Główny checkout nietknięty. Kontenery i bazy 5002–5008 oraz `priorytety_wyscigi` nieruszane.
- Worktree `.claude/worktrees/priorytety-k3p2` (gałąź `claude/priorytety-k3p2`) do usunięcia po bramce centrali.

## Co następny krok musi wiedzieć

- **K5 (przegląd przed wdrożeniem):**
  - `GET desk` w `stary` nie bierze żadnych blokad ani nie zapisuje (MySQL wyżej) — w przebiegach wyścigów `desk`
    na stanowisku w `stary` nie jest już pisarzem; pisarzem jest tylko w `stol`.
  - Nowy odczyt w transakcji ZAKOŃCZ: status pozycji z `zablokuj_zamowienie_pozycji` (już trzymanej) — kolejność blokad
    bez zmian; licznik: zwykły odczyt jak dotąd (bez blokady zamówienia).
  - Tryb `zakoncz-zakoncz-ten-sam-kafel`: oczekiwany wynik drugiego ZAKOŃCZ to 409 `pozycja_poza_stanowiskiem`
    (stanowisko pozycyjne i zamówieniowe) — wpisać wynik do §6 kontraktu (akapit „do potwierdzenia przez K5”).
  - Na kopii produkcji po wdrożeniu (wszystko `stary`) tablety z nową appką wołają `desk` co ≤ 30 s — sam odczyt
    (18–55 zapytań na kopii, tabela wyżej).
- **Sesja appki:** kontrakt do skopiowania = `docs/api-mobile-priorytety.md` @ `34773e9f` (dotąd `42275bcf`). Zmiany
  względem `42275bcf`: pole `tryb` jest w kodzie (także w `postpone`), `desk` w `stary` niczego nie zapisuje; 409
  `pozycja_poza_stanowiskiem` przy ZAKOŃCZ i liczniku w `stol` → porzucić wpis, `message`, `GET desk` (§6, §10); stół
  Pakowania przyjmuje zamówienia bez sposobu dostawy; nowy punkt odbioru 23b; karta appki zaktualizowana
  (`f27ffca7`). Serwer do odbioru musi mieć kod ≥ `07710d4c` (pole `tryb` w `desk`).
- **K7 (runbook):** po deployu wszystkie stanowiska w `stary` → nowa appka zostaje na liście, `desk` tylko czyta;
  „Przygotuj stoły” kładzie kafle startowe, które w `stary` widać w `desk` tylko do odczytu; „Włącz stoły” (tryb +
  próg wersji jednym zapisem) przełącza tablety na stół w ≤ 30 s (ETag z trybem), wycofanie stanowiska na `stary` —
  z powrotem na listę.
