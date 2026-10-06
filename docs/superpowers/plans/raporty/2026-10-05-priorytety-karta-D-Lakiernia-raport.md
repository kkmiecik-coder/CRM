# Raport — karta dokumentacyjna D-Lakiernia (program „Priorytety produkcji”)

- **Sesja:** lokalna, Opus 5.5, medium. Tylko dokumenty, bez kodu i bez testów.
- **Worktree:** `.claude/worktrees/priorytety-docs-lakiernia`, gałąź lokalna `claude/priorytety-docs-lakiernia`
  odbita od `origin/claude/priorytety-produkcji` @ `0f23bb35`.
- **Decyzja do naniesienia:** S-6 wariant C (Konrad 5.10) — Lakiernia na stałe w `stary`, lista po wykończeniu;
  dziennik centrali, „Decyzje startowe” S-6 i rozstrzygnięcie 4.

## Zrobione

| Plik | Miejsce | Zmiana |
|---|---|---|
| spec `2026-10-04-priorytety-produkcji-design.md` | 2, nowy p. 15 | decyzja: Lakiernia `stary` na stałe, lista po wykończeniu (3 pola), reguła kolejności „do potwierdzenia przy bramce K3”, kolejność P3 bez Lakierni |
| spec | 3.2 | Lakiernia wyjęta z „kafli na stanowisku pozycyjnym”; nowy akapit **„Lista Lakierni”** (grupy, klucz pozycji, kolejność grup, cała grupa w ciągu, pozycje w innych statusach na końcu, opóźnienie tagów do `utrwal()`) |
| spec | 5.5 | „Lakiernia zawsze `stary`”: stała `STANOWISKA_BEZ_STOLU`, bramka przepuszcza mimo `stol` w ustawieniach, `desk`/`postpone` → 409 `stanowisko_bez_stolu` |
| spec | 6.3 | wyjątek Lakierni w punkcie o trybie; nowy punkt „Lista Lakierni”: kolejność listy i delty, pole `grupa_wykonczenia`, jedno podbicie `KSZTALT` → 6 razem z `priorytet`, ETag bez zmian w budowie |
| spec | 6.4, nowy p. 7 | ekran Lakierni = lista bez stołu i Odłóż (wybór ekranu po kodzie stanowiska); tablet Krawędzi na stałe w trybie mieszanym (przed i po przełączeniu Krawędzi, stara appka); uwaga, że appka 1.7.3 sortuje listę sama |
| spec | 7.2 | zakładka Stanowiska (Lakiernia: 15 pozycji listy, bez stołu), monitor Lakierni (lista zamiast stołu, kolejność jak tablet), Konfiguracja (wiersz Lakierni bez wyboru trybu) |
| spec | 8.6 | `priorytety_tryb_painting` = `stary` na stałe; akapit „Porządek listy Lakierni bez nowego klucza” (kolejność zależna od kodu stanowiska) |
| spec | 11 | P3: kolejność 6 stanowisk, Lakiernia nie przechodzi |
| spec | 13 | testy Lakierni w liście pytest; P-1 i P-2 „Lakiernia: nie dotyczy”; nowy P-10 (reguła listy) |
| plan K3 | Review Focus 9, Decyzje p. 9, Mapa plików, Task 1 (bramka — odesłanie do 5a), Task 2 (test `test_desk_tablet_krawedzi_widzi_lakiernie` → `test_desk_urzadzenie_lakierni_widzi_krawedzie`), **nowy Task 5a**, Task 6 (grep, „Co następny krok”: K4b, K2/centrala, K6, K7), DoD 9–10, Pytania p. 6 | Task 5a: `lista.py` (`porzadek_listy`, `klucz_grupy_wykonczenia`, `grupa_wykonczenia_json`), `STANOWISKA_BEZ_STOLU`, przepięcia `station_orders`/delta/serializer/bramka/`desk`/`postpone`/`stoly_panelu`, 14 testów, miejsca sortowania z numerami linii na `0f23bb35` |
| plan K4b | Decyzje p. 9, Doprecyzowania p. 15 (nowy), Review Focus 6, Interfaces (Consumes, `stoly_panelu` 6 stanowisk), Task 2 (test zakładki Lakierni), Task 5 (wiersz Lakierni w „Stół stanowisk”), Task 6 (testy i Step 4 monitora Lakierni), Task 8 (K5 Doprecyzowania 1–15, K7) | monitor Lakierni po liście tabletu, bez TERAZ; zakładka i Konfiguracja Lakierni |
| plan K7 | Goal, Decyzje p. 4, Doprecyzowania 5, 6, 9, Task 3 Step 4, Task 4 Step 1, Task 5 (×6, lista stanowisk, kontrola `priorytety_tryb_painting`, Krawędzie), Task 5 Step 6, Task 6 Step 1 i tabela pomiaru, DoD 8, Pytania C5 | P3 bez Lakierni; okno pomiaru od przełączenia Pakowania; tryb mieszany tabletu Krawędzi na stałe |
| plan K6 | Decyzje p. 4 i nowy p. 10, Doprecyzowania p. 6, Review Focus 2, Task 2 Step 3 (409 `stanowisko_bez_stolu`), Task 4 Step 1–2 (ekran Lakierni, kryterium 13, nowe 19), Task 5 (lista kontrolna, zmiana 9 i nowa 10 w karcie appki), DoD 2 | kontrakt: Lakiernia bez stołu, lista w kolejności serwera, `grupa_wykonczenia` |
| podręcznik centrali | sekcja 7, wiersz S-6 | rekomendacja zastąpiona decyzją z odnośnikiem do dziennika |

Dziennik centrali — bez zmian (zgodnie z kartą).

## Odstępstwa

1. Karta kazała dopisać Task „albo krok w istniejącym Tasku listy”. Dopisany **osobny Task 5a** (po Task 5), bo
   korzysta z `serialize_order(..., priorytety=)` i `KSZTALT = 6` z Task 5, a dotyka też bramki (Task 1) i `desk`/`postpone`
   (Task 2–3). Skutek: DoD K3 p. 9 — 7 commitów zamiast 6.
2. Poza wymienionymi sekcjami specu nie ruszałem 5.1 (lista jednostek wymienia jeszcze Lakiernię z `pozycja`) ani 9.1
   (pakiet bez `lista.py`) — opisy w 3.2, 5.5, 8.6 je nadpisują. Do przeniesienia przez K5/D1 razem z Doprecyzowaniami K3.

## Rozstrzygnięcia (koszt, jeśli błędne)

1. **Doróbka w liście Lakierni** — „doróbki jak wszędzie pierwsze” czytam w obrębie reguły grup: doróbka ma rangę 0,
   więc jej grupa idzie pierwsza, a doróbka na początku grupy (kilka doróbek w różnych grupach — po najstarszej). Nie
   wyciągam doróbek ponad wszystkie grupy, bo to rozbiłoby „całą grupę w jednym ciągu”. Koszt: przy dwóch doróbkach
   w różnych grupach druga czeka na całą grupę pierwszej — zmiana jednego klucza w `porzadek_listy`.
2. **Stół Lakierni zablokowany w kodzie**, nie tylko w ustawieniach: `STANOWISKA_BEZ_STOLU` — bramka zawsze przepuszcza,
   `desk`/`postpone` → 409 `stanowisko_bez_stolu`. Powód: pomyłkowe `stol` w Konfiguracji zatrzymałoby ZAKOŃCZ z listy
   na hali. Koszt: gdyby Konrad kiedyś chciał stół na Lakierni — zmiana stałej i testów.
3. **Bez nowego klucza `prod_config`** na porządek listy — kolejność zależy od kodu stanowiska (ta sama stała). Klucze
   `priorytety_*_painting` z migracji K1 zostają (37 bez zmian), nieużywane. Koszt: żaden.
4. **Pole `grupa_wykonczenia` w serializerze** (tylko dla `painting`, inaczej `null`), w tym samym `KSZTALT = 6` co
   `priorytet`. Powód: separatory grup w appce mają wynikać z klucza serwera, nie z własnego klucza appki (dziś
   `batchKeyOf` w appce ma inny klucz — z typem koloru, bez połysku dla olejowanych). Koszt: jedno pole więcej w
   kontrakcie K6.
5. **Pozycje w innych statusach na końcu listy Lakierni** (lista oddaje całe zamówienia; appka i tak pokazuje tylko
   aktywne). Koszt: żaden dla ekranu.
6. **Monitor Lakierni po kolejności pierwszego wystąpienia na liście tabletu**, a nie po randze zamówienia jak pozostałe
   monitory — telewizor pokazuje to samo co tablet. Koszt: inny klucz sortu dla jednego monitora (K4b Doprecyzowania 15).
7. **Okno pomiaru K7 od przełączenia Pakowania** (ostatniego stanowiska ze stołem); w tabeli pomiaru Lakiernia bez
   kryterium „spadek omijania” — lista po wykończeniu omija rangę z założenia.
8. **Sygnał `station:painting` zostaje** w tokenie tabletu Krawędzi i w ZAKOŃCZ Krawędzi — nowa appka może nim odświeżyć
   listę Lakierni zamiast czekać 30 s; nie woła `desk`.

## Pytania do Konrada

1. **Dzisiejsza appka sortuje listę Lakierni sama** (repo `woodpower_prod_app` @ `265e563`, 1.7.3: `StationSorting.kt`
   `buildOrderComparator` — najpierw `isPriority`, potem „po terminie”, potem wybrane sortowanie: domyślnie
   `priority_rank`, albo „Partia (kolor i połysk)” z separatorami; Room czyta `ORDER BY priority_rank`). Porządek po
   wykończeniu z serwera **nie pojawi się na tablecie** do czasu nowej appki (P2). Do tego czasu pracownik ma w appce
   sortowanie „Partia”, które grupuje podobnie (inny klucz, grupy alfabetycznie, pilne wyniesione nad wszystko).
   Rekomendacja: przyjąć, że lista po wykończeniu działa od nowej appki; w nowej appce na Lakierni domyślnie kolejność
   serwera (bez wynoszenia pilnych nad grupy), separatory z `grupa_wykonczenia`, ręczne sortowanie zostaje jako opcja.
   Alternatywa: osobne wydanie appki tylko z tą zmianą przed P2.
2. **Klucz grupy:** potwierdzone trzy pola (rodzaj, kolor, połysk). Appka grupuje dziś także po typie koloru
   (`parsed_finish_color_type`: barwne/bezbarwne) i ignoruje połysk przy olejowanych. Czy klucz serwera ma tak zostać
   (trzy pola), czy dołożyć typ koloru? Rekomendacja: trzy pola (decyzja), K3 przy bramce sprawdzi na kopii produkcji,
   czy gdzieś ten sam kolor różni się typem.
3. **Reguła doróbek** (Rozstrzygnięcie 1) i cała reguła listy — do potwierdzenia przy bramce K3 (spec P-10).

Do centrali (nie do Konrada): `PUT /production/api/priorytety/ustawienia` (K2) przyjmie `stanowiska.painting.tryb = stol`
bez skutku — czy walidacja K2 ma to odrzucać (400). Planu K2 nie zmieniałem (poza zakresem karty, K2 w toku).

## Stan gałęzi

Commit `docs(priorytety): Lakiernia w trybie stary z lista po wykonczeniu` wypchnięty na
`origin/claude/priorytety-produkcji` — hash w odpowiedzi do Konrada (commit zawiera ten raport, więc nie może podać
własnego hasha).
