# Karta sesji appki — stół stanowiska, Odłóż, sygnały (+ zmiany logistyki 4.6)

Przygotowana w kroku K6 programu „Priorytety produkcji” (2026-10-05). Wspólna karta nowej appki dla logistyki
(etapy 1–4 i krok 4.6) i priorytetów — jedno wydanie APK (decyzja Konrada).

**Dla Konrada:** sesja **lokalna w repo `woodpower_prod_app`** (`C:\Users\Grafik\Documents\woodpower_prod_app`),
uruchamiana w CLI Android Studio, **tablet po USB, Fable 5.1, effort extra**, bez trybu szybkiego — kolejka offline,
idempotencja i SSE to logika, której testy appki nie złapią. Przed startem skopiuj kontrakt do repo appki:
`docs/api-mobile-priorytety.md` z repo CRM (gałąź `claude/priorytety-produkcji`, commit
`34773e9f956a1467e1e6ec6eb3e65d5700a15d36`) → `docs/kontrakt-api-priorytety.md` w repo appki (albo podaj sesji
ścieżkę do pliku). Wskaż sesji serwer CRM do odbioru — lokalny CRM na Twoim komputerze (kopia produkcji, port
podaje centrala), osiągalny z tabletu przez Wi-Fi albo `adb reverse` — nigdy produkcję.
**Termin:** appka gotowa i odebrana na tablecie przeciw lokalnemu serwerowi CRM Konrada **najpóźniej we wtorek 6.10** (build debug we wtorek, po południu próba wdrożenia z odbiorem appki
na tablecie — harmonogram centrali); wdrożenie CRM + APK w czwartek 8.10 w przerwie o 10:30, APK na tabletach wcześniej.

Prompt do wklejenia:

````markdown
# Karta: appka tabletów — stół stanowiska, Odłóż, sygnały, Pakowanie bez sposobu dostawy

Sesja: lokalna, repo woodpower_prod_app, tablet po USB. Model: Fable 5.1. Effort: extra. Bez trybu szybkiego.
Jeśli działasz na innym modelu albo effortcie — napisz to na początku i w raporcie.

## Źródło — JEDYNE

Kontrakt: `docs/kontrakt-api-priorytety.md` w tym repo = kopia `docs/api-mobile-priorytety.md` z repo CRM
(kkmiecik-coder/CRM, gałąź `claude/priorytety-produkcji`, commit `34773e9f956a1467e1e6ec6eb3e65d5700a15d36`;
odnośniki w nim wskazują kod CRM @ `07710d4c3b6c4ba313fbf234c003d8878d8db86d`). Numery „§N” niżej to sekcje kontraktu.

Pracujesz WYŁĄCZNIE z kontraktu. Nie czytasz kodu CRM i nie zgadujesz zachowania serwera. Niejasność albo
serwer CRM do odbioru robi co innego niż kontrakt → STOP, pytanie do Konrada (centrala odpowie albo zleci poprawkę
kontraktu). Nie „naprawiasz” serwera po stronie appki.

Akapity kontraktu oznaczone **[K3-poprawka-2]** (pole `tryb` w `GET desk`, `desk` w trybie `stary` bez dopełniania,
409 `pozycja_poza_stanowiskiem`) są już w kodzie CRM (od `9a72d056` i `07710d4c`, odnośniki w kontrakcie). Na
serwerze z kodem sprzed tej karty `desk` nie ma pola `tryb` — wtedy **build debug** traktuje 200 jak `tryb: "stol"`,
a **build release** jak `"stary"` (lista) (§4). Jeśli serwer do odbioru nie oddaje pola `tryb`, ma stary kod —
zgłoś to Konradowi przed punktami odbioru 18, 18a, 18b.

## Start

1. `git status` czysty; gałąź robocza appki (np. `claude/priorytety-stol`) od aktualnej gałęzi głównej appki (wersja
   z logistyką etapu 4 — 1.7.3 albo nowsza; stan repo ustalasz sam), nigdy gałąź wydań.
2. Przeczytaj kontrakt w całości.
3. Spisz, jak appka robi to dziś („stan przed” do raportu): ekran stanowiska i jego odświeżanie (ETag, interwał),
   kolejka offline (Room, `X-Operation-Id`, reakcja na każdy kod 4xx/5xx), heartbeat (kiedy pierwszy), sortowanie
   listy Lakierni, blokada Pakowania przy pustym sposobie dostawy (`DeliveryGate`), okno paczek.
4. Napisz krótki plan w repo appki (Task po Tasku, testy najpierw) i pokaż go Konradowi przed kodowaniem.

## Zmiany (każda z sekcją kontraktu)

1. **Wybór ekranu stanowiska** przy każdej odpowiedzi `GET desk`: Lakiernia zawsze lista (po kodzie stanowiska);
   pozostałe — stół tylko przy `tryb == "stol"`, lista przy `"stary"` i przy 404 bez JSON (stary backend).
   Przełączanie w obie strony bez restartu, bez ponownego logowania, bez utraty kolejki offline. Ekranu NIE
   przełączają 304, 5xx, przekroczony czas, brak sieci, 401, 426 (§4, §12, §13).
2. **Ekran stołu:** „Teraz” (nazwa robocza — tekst akceptuje Konrad przy odbiorze), „Odłożone”, „Niekompletne”
   (Formatowanie, Pakowanie), nagłówek „w kolejce: N”; bez listy kolejki; kafle w kolejności odpowiedzi — appka nie
   sortuje ani nie grupuje; „Teraz” przewijane (stół bywa dłuższy niż `miejsca`), plakietki „wysłane przez biuro”
   i „rozpoczęte przed startem” z `zrodlo` (§4, §13).
3. **Kafel:** gwiazdki, plakietka szczebla, „poz. i/n” z `priorytet`; **Odłóż** (lewy), **ZAKOŃCZ** (prawy), licznik
   sztuk jak dotąd; na Formatowaniu pozycja z `cut_to_size == false` w innym statusie niż `czeka_na_formatowanie` →
   plakietka „idzie prosto do pakowania”, bez przycisków. **ZAKOŃCZ i licznik wyłącznie przy pozycjach w statusie
   tego stanowiska** — w trybie `stary` serwer tego nie pilnuje (ZAKOŃCZ pozycji z innego statusu przeskoczy albo
   cofnie stanowisko); **[K3-poprawka-2]** w trybie `stol` serwer odpowiada wtedy 409 `pozycja_poza_stanowiskiem`
   (§6);
   pozostałe pozycje kafla-zamówienia (także anulowane) bez przycisków; ZAKOŃCZ kafla-zamówienia = osobne ZAKOŃCZ
   każdej pozycji w statusie stanowiska, każde z własnym `X-Operation-Id`; przycisk nieaktywny do odpowiedzi serwera
   (§4, §6, §7, §13).
4. **Modal Odłóż:** pięć powodów z etykietami z §5, notatka wymagana i niepusta przy „Inne” (≤ 255 znaków),
   `zakres` = `jednostka` z `desk`, tylko online; 409 → `message` jako komunikat; po 200 zawsze `GET desk` (§5, §10).
5. **SSE:** token z `/realtime-token` przy każdym połączeniu, `POST` na `sse_url` (pusty → złożony z adresu CRM),
   ramki wg §8, 40 s ciszy = zerwanie, drabinka ponowień z rozrzutem ±10 %, zerwanie raz na TTL to rutyna; po każdym
   udanym połączeniu (ramka `connect`) jedno `GET desk`; sygnał = `GET desk` (tablet z dwoma kanałami: desk Krawędzi
   + lista Lakierni, listę po sygnale z `Cache-Control: no-cache`); 503/404 → samo odpytywanie, nowa próba tokena co
   5 min (§8, §9).
6. **Odpytywanie zawsze, także przy SSE:** co 30 s, gdy na stole mniej kafli niż `miejsca`, co 5 min, gdy co najmniej
   `miejsca`; `GET desk` po każdym własnym ZAKOŃCZ/Odłóż i po synchronizacji kolejki; najwyżej jedno `desk` w locie
   i jedno oczekujące na stanowisko; `If-None-Match` i **żadnego serwowania `desk` z pamięci OkHttp**
   (`Cache-Control: max-age=0`); limit czasu żądania `desk` ≥ 15 s; na liście w trybie `stary` — `desk` najwyżej
   co 30 s do wykrycia przełączenia (§4, §9).
7. **Kolejka offline:** `X-Operation-Id` nowy na akcję, ten sam przy każdym ponowieniu; tabela kodów z §10 (porzucić /
   zostawić / pokazać) — **decyzja po polu `error`, nie po statusie HTTP**, nieznany `error` przy 4xx → zostawić
   i pokazać; reguła dla 409 `nie_na_stole` (ponowienie najwyżej raz na takt siatki, nigdy po `desk` wywołanym przez
   samą regułę); wpisy starsze niż 7 dni tylko po potwierdzeniu człowieka.
   Testy jednostkowe porzucania i ponawiania dla KAŻDEGO kodu z tabeli §10 (§10).
8. **409:** `nie_na_stole` (komunikat + `GET desk`), `limit_odlozen` (komunikat, kafel zostaje),
   `delivery_method_not_set` (komunikat, wpis zostaje w kolejce — tylko backend sprzed 4.6, czyli produkcja przed
   deployem 8.10; obsługa zostaje),
   `stanowisko_bez_stolu` (błąd appki), **[K3-poprawka-2]** `pozycja_poza_stanowiskiem` (komunikat `message`, wpis
   z kolejki offline **porzucić** — ponowienie nic nie zmieni — i `GET desk`) (§5, §6, §10).
9. **Heartbeat zaraz po starcie appki i po każdej aktualizacji APK** (nie dopiero po 15 min) (§11).
10. **Nowa appka na starym backendzie** (APK trafia na tablety przed deployem 8.10): wszystkie zachowania zastępcze
    z tabeli §12 — lista zamiast stołu, samo odpytywanie, brak plakietek przy braku pól, pominięcie deklaracji paczek
    przy 404, oczekiwane 400 `invalid_station_code` dla telefonów Weryfikacji/Dostawy (§12).
11. **Tablet Krawędzi:** ekran Krawędzi = stół, ekran Lakierni = lista; jeden token z dwoma kanałami; każdy sygnał
    odświeża oba (§8, §13).
12. **Lakiernia bez stołu:** lista w kolejności serwera (domyślnie, bez wynoszenia pilnych nad grupy), separatory
    z `grupa_wykonczenia` (zmiana dowolnego z czterech pól), bez Odłóż, bez „w kolejce”, **nigdy** `desk`/`postpone`
    dla `painting`; ręczne sortowanie może zostać jako opcja (§13; 409 `stanowisko_bez_stolu` w §10).
13. **Pakowanie bez sposobu dostawy (logistyka 4.6, §6, §13)** — wskazówki centrali logistyki z przeglądu appki
    1.7.3 (`main` `265e563`; sprawdź w repo, numery linii mogły się przesunąć):
    a) `DeliveryGate.kt:14-15` `finalizeBlockReason` z `DELIVERY_METHOD_REQUIRED_STATIONS = {"packaging"}`
       (`StationViewModel.kt:1437`) przestaje blokować ZAKOŃCZ przy `transport.mode == null` (przerwanie
       `StationViewModel.kt:724`, przycisk wyłączony `StationScreen.kt:343` i `:519`);
    b) `DeliveryGate.kt:22` `orderGroupsForStation` — nie spychać zamówień bez sposobu na koniec (kolejność daje
       serwer);
    c) **PUŁAPKA:** okno paczek jest warunkowane tą samą flagą (`StationViewModel.kt:741`
       `blocksUnsetDelivery && group.packingHint != null` i `:762`) — rozdzielić „stanowisko z oknem paczek”
       (packaging) od „blokuje brak sposobu” (puste), inaczej okno paczek zniknie;
    d) plakietka informacyjna **„Sposób dostawy do ustalenia – pakuj normalnie”** (tekst zatwierdzony przez Konrada),
       bez blokady; pas „NIE USTAWIONO” na etykiecie paczki robi serwer — appka nic nie rysuje;
    e) obsługa 409 `delivery_method_not_set` zostaje (backend sprzed 4.6);
    f) stół Pakowania na serwerze przyjmuje zamówienia bez sposobu dostawy od `2f3e6ce7` (stół, „Niekompletne”,
       `kolejka_dalej`, „Wyślij”, start stołów — §6) — appka niczego tu nie obchodzi, pokazuje je jak każde inne.
14. **Room:** nowe tabele/kolumny tylko z migracją, bez `fallbackToDestructiveMigration` (kolejka offline nie może
    przepaść przy aktualizacji).

## Zasady

- Tylko serwer CRM wskazany przez Konrada (niżej). **Nigdy produkcja**, nigdy rejestracja urządzenia na
  produkcji.
- **Środowisko odbioru:** odbiór appki i wtorkowa próba wdrożenia idą przeciw **lokalnemu serwerowi CRM na komputerze
  Konrada** (kopia produkcji; port podaje centrala w dniu próby). Build **debug** ma ustawiany adres serwera —
  łączysz się przez Wi-Fi albo kabel USB z tunelowaniem (np. `adb reverse`). Wszystkie scenariusze z §14 najpierw
  na buildzie debug przeciw temu serwerowi; build **release** (z `version_code` dla `priorytety_min_app_version_code`)
  dopiero po odbiorze i **z adresem produkcyjnym** — sprawdź to przed oddaniem APK.
- Kolejka offline: zero utraty akcji. Każda zmiana reakcji na kod błędu — test jednostkowy przed kodem.
- Ekrany hali: tylko ciemny motyw, zero animacji, cele dotykowe ≥ 48 px (jak dotychczasowe ekrany stanowisk).
- Testy appki przed implementacją; commity małe, Conventional Commits po polsku; push wg Konrada.
- `version_code` nowej appki **większy** niż wszystkie dotychczasowe (APK 1.7.3 w CRM jest nieaktywne i takie
  zostaje — na tablety idzie to nowe APK).
- STOP i pytanie do Konrada: niejasność kontraktu, serwer CRM niezgodny z kontraktem, potrzeba zmiany po stronie CRM,
  ryzyko utraty danych kolejki offline.

## Koniec

Odbiór z tabletem: checklista z §14 kontraktu punkt po punkcie (wynik i dowód: zrzut ekranu albo log serwera/appki),
z punktami 18, 18a, 18b (przełączanie bez restartu w obie strony), 23 (Pakowanie bez sposobu + okno paczek z i bez
sposobu dostawy), 23a (ZAKOŃCZ tylko pozycji w statusie stanowiska) i 23b (409 `pozycja_poza_stanowiskiem`
z kolejki porzucony) obowiązkowo. Raport w repo appki (`docs/raporty/<RRRR-MM-DD>-priorytety-appka-raport.md` albo
katalog raportów appki) i pełna treść w odpowiedzi do Konrada, sekcje:
Zrobione (z hashami), Testy (polecenia i wyniki), Checklista §14 (punkt po punkcie), Odstępstwa od kontraktu,
Rozstrzygnięcia (numerowane, koszt jeśli błędne), Pytania do Konrada, **`version_code` i `version_name` APK**, hash
commita appki, Co K7 musi wiedzieć (`priorytety_min_app_version_code` = ten `version_code`, ustawiany przy „Włącz
stoły”; tablety muszą wysłać heartbeat z nową wersją; czego appka wymaga od konfiguracji realtime).
````
