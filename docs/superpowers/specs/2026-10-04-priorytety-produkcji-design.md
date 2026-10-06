# Priorytety produkcji — przebudowa: drabina biura, gwiazdki 0–5, trasy, stół stanowiska — projekt

- **Data:** 2026-10-04 (wersja 2, po rozmowie z Konradem; wersja 1 z tego samego dnia zakładała „okno z blokadą” —
  zastąpione „stołem stanowiska” i „Odłóż”, sekcja 2)
- **Status:** zatwierdzony w rozmowie co do mechanizmu i parametrów (Konrad 4–5.10); zweryfikowany symulacją na danych
  produkcyjnych (`2026-10-04-priorytety-produkcji-symulacja.md`, sekcja „Analiza wyniku”). Gotowy do planu kroku P1.
  Wdrożenie w osobnych planach kroków (P1–P4), na Opusie/Sonnecie. Kontrakt dla appki (P2) powstaje po P1.
- **Gałąź:** `claude/logistyka-etap-4` (stan `3c50cc8d`) (K5 → 16.9 Z01). Projekt opiera się na trasach z etapu 3 logistyki i statusach
  z etapu 4, więc wdraża się **po logistyce**, nigdy przed.
- **Podstawa:** `docs/superpowers/specs/2026-09-24-logistyka-rownolegla-trasy-design.md` (sposób dostawy, trasy),
  `docs/superpowers/specs/2026-09-30-logistyka-etap-4-weryfikacja-dostawa-design.md` (statusy po spakowaniu, Dostawa),
  `docs/superpowers/specs/2026-04-08-parallel-stations-design.md` (Wycinanie/Składanie równolegle), CLAUDE.md sekcja
  „Trasy logistyki — jeden piszący naraz”. Pojęcia stamtąd (sposób dostawy, `transport`, blokada tras, „zamówienie
  najpierw”, sygnał realtime dla agenta druku) używamy bez ponownego opisu.
- **Zastępuje:** `modules/production/services/priority_service.py` („Enhanced Priority System 2.0”) wraz z martwymi
  końcówkami priorytetów w `routers/api/products_api.py` (sekcja 9.5).
- Repo jest publiczne — w tym pliku nie ma sekretów ani uwag bezpieczeństwa.

> **(K5) Stan po realizacji K1–K5.** Sekcje 1–15 opisują projekt sprzed kodu. Tam, gdzie różnią się od tego, co
> powstało, obowiązuje **sekcja 16**; miejsca nieaktualne mają w treści znacznik „(K5 → 16.9 Znn)”, a tabela
> 16.9 mówi, co obowiązuje.

## 1. Cel i kontekst

### 1.1 Jak jest (stan na gałęzi)

- **Ranga pozycji.** `prod_products.priority_rank` to jeden globalny numer 1..N nadawany pozycjom (nie zamówieniom)
  przez `priority_service.recalculate_all_priorities()`: grupowanie po tygodniu `payment_date`, w tygodniu
  częstość gatunku/technologii/grubości/klasy („więcej = wyżej”), dalej `deadline_date`, `payment_date`, `id`.
  Przelicza się po każdej synchronizacji z Base., która utworzyła pozycje (`sync_service.py:933`, `:3033`); nie ma
  przeliczenia cyklicznego ani przycisku w UI.
- **Gwiazdka.** `prod_products.is_priority` (bool) ustawia tylko admin (`POST /production/api/set-priority`,
  `@admin_required`) z karty zamówienia albo wiersza pozycji w zakładce Produkty. **Algorytm rangi gwiazdki nie czyta** —
  gwiazdka to wyłącznie pomarańczowa ramka na tablecie i licznik `priority_count` w podsumowaniu stanowiska.
- **Ręczne nadpisania.** `priority_manual_override` + `lock_priority()` rezerwują numer rangi przy przeliczaniu.
  Jedyny żywy użytkownik: doróbka (`rework_service.py:302`, `lock_priority(rank=1)` — żółta ramka, szczyt kolejki,
  zdejmowana na Formatowaniu). Przeciąganie wierszy (`products-dragdrop.js`) i końcówki `update-priority`,
  `products/<id>/priority`, `set-manual-priority`, `recalculate-all-priorities`, `priority-statistics` są martwe
  w obecnym układzie zakładki Produkty.
- **Tablet.** `GET /api/mobile/stations/<kod>/orders` oddaje **całą kolejkę** stanowiska, posortowaną
  `COALESCE(priority_rank, 999999), internal_order_number, id`, odpytywaną co 30 s (`REFRESH_INTERVAL_SECONDS`) z ETagiem.
  Nie ma kroku „rozpocznij”. **Serwer nie sprawdza kolejności**: ZAKOŃCZ przyjmuje dowolną pozycję kolejki
  (`complete_task` nie sprawdza nawet `current_status`). Jedyna bramka zależna od zamówienia: pakowanie bez sposobu
  dostawy → 409 `delivery_method_not_set`. Appka pokazuje na większości stanowisk pojedyncze pozycje, na Formatowaniu
  i Pakowaniu całe zamówienia.
- **Termin.** `prod_products.deadline_date` liczy import: data wejścia w „Nowe – opłacone” + `DEADLINE_DEFAULT_DAYS` (16)
  albo `DEADLINE_FINISHED_DAYS` (21, gdy choć jedna pozycja wykończona) **dni roboczych** (`_add_business_days`,
  zaszyte w kodzie). Ustawienia liczby dni już są w zakładce Konfiguracja; przełącznika dni roboczych/kalendarzowych nie ma.
- **Trasy.** Trasa robocza albo zatwierdzona może mieć zamówienia jeszcze w produkcji. Trasa ma `date_from`/`date_to`.
  Zamówienie jest na co najwyżej jednej trasie (`prod_route_stops.order_id` UNIQUE). **Trasy nie mają związku z rangą.**
- **Realtime.** Centrifugo jest wdrożone dla agenta druku: CRM zapisuje do bazy, po commicie wysyła krótki sygnał
  (`realtime_service.publish`, w API mobilnym planowany przez `g` i wysyłany przez `with_idempotency` po commicie),
  odbiorca po sygnale woła REST. Namespace `station:<kod>` jest przygotowany w konfiguracji brokera, token wystawia
  `issue_connection_token` (precedens: `GET /api/print-agent/realtime-token`). Tablety z tego jeszcze nie korzystają.

### 1.2 Problem

Na hali ludzie wybierają zamówienia, które są łatwiejsze — ranga jest widoczna, ale nic jej nie pilnuje. Biuro nie ma
narzędzia, żeby powiedzieć produkcji „to ma być pierwsze”: gwiazdka nie wpływa na kolejkę. Algorytm „więcej = wyżej”
optymalizuje jednorodność tygodnia, nie pilność, i nie wie nic o trasach — a to trasy decydują, co musi zjechać
z produkcji do konkretnego dnia, także gdy logistyk dociąga na trasę zamówienie, które dopiero wpadło.

### 1.3 Cel

**Cel:** jedno źródło kolejności produkcji, ustawiane przez biuro na poziomie **zamówienia** (gwiazdki 0–5, trasy
i tagi terminowe ułożone na **drabinie**), z którego system wylicza kolejkę każdego stanowiska. Tablet pokazuje tylko to,
co **leży na stole** stanowiska (1–2 kafle), pracownik kończy albo **odkłada** z powodem, a następny kafel przychodzi
z kolejki w chwili zwolnienia miejsca. Dwa tablety na stanowisku widzą to samo i dowiadują się o zmianach sygnałem,
nie odpytywaniem.

**Sukces:**
- biuro w Liście produkcyjnej ustawia gwiazdki na zamówieniu i układa drabinę; dodanie do trasy przestawia kolejkę od razu,
- pracownik nie wybiera — dostaje kafel, kończy go albo odkłada z powodem; odłożenie nie zdejmuje kafla z tabletu,
- biuro widzi odłożenia z powodami i reaguje gwiazdkami albo wstrzymaniem,
- dwa tablety na stanowisku są spójne w ciągu sekund po ZAKOŃCZ, Odłóż albo zmianie licznika,
- stare APK działają do czasu aktualizacji (pełna lista, bez bramki).

## 2. Ustalenia z rozmowy (Konrad, 4.10)

1. System priorytetów **od zera**, w osobnym pakiecie. Priorytetami zarządza **biuro** z backoffice produkcji.
2. **Gwiazdki 0–5** na zamówieniu i **trasy** na jednej **drabinie**. Trasa stojąca wyżej niż ★★★★★ idzie w całości
   pierwsza; w obrębie trasy porządkują gwiazdki, potem **termin** (nie data złożenia — poprawka wobec wersji 1).
3. Na drabinie są też **tagi**: „Po terminie” i „Blisko terminu” (K5 → 16.9 Z02) (próg w dniach w ustawieniach). Zamówienie bez trasy
   bierze **najwyższy** ze swoich szczebli (gwiazdki, tag); zamówienie z trasy bierze szczebel trasy.
4. **Termin:** w ustawieniach całej produkcji liczba dni dla zamówień surowych i z wykończeniem oraz przełącznik
   **dni robocze / kalendarzowe**. Zamówienia już w bazie zostają ze swoim terminem — bez przeliczania.
5. **Tablet pokazuje 1–2 kafle** („stół”), nie całą kolejkę i nic wyszarzonego. Nie ma kroku „rozpocznij”: pozycja raz
   pokazana **zostaje**, aż pracownik ją zakończy albo odłoży, niezależnie od zmian priorytetów w biurze (pracownik odchodzi
   od tabletu przygotować pozycję i wraca ją zamknąć).
6. **Odłóż** obok ZAKOŃCZ: modal z powodem. Odłożony kafel **zostaje widoczny** na tablecie (sekcja „Odłożone”), żeby dało
   się go zamknąć później; na stół wchodzi następny z kolejki. **Limit** otwartych odłożeń na stanowisko (np. 10) blokuje
   dalsze odkładanie — koniec z „nie chce mi się”.
7. **Dwa tablety na stanowisku działają synergicznie** — pokazują to samo. Zamiast odświeżania co 30 s: **sygnał** jak dla
   agenta druku (zapis do bazy + push), do tabletów tego samego stanowiska i do stanowiska następnego przy ZAKOŃCZ.
   Tablet z pustym stołem odpytuje bazę co 30 s jako zabezpieczenie.
8. **Kafel:** na stanowiskach, które dziś pokazują pojedyncze pozycje, zostają pozycje (grupowane po materiale);
   Formatowanie i Pakowanie pokazują całe zamówienia, jak dziś. Odłóż dotyczy kafla.
9. **Grupowanie po materiale w obrębie szczebla** (pozycje dostępne na danym stanowisku): gatunek i klasa, potem grubość (K5 → 16.9 Z03)
   malejąco, długość malejąco, szerokość malejąco (wymiary to [długość]×[szerokość]×[grubość]).
10. Miejsce ustawiania: **modal priorytetu** na karcie zamówienia w zakładce **„Lista produkcyjna”** (dotychczas „Lista
    produktów” — zmiana nazwy) i **przycisk „Drabina priorytetów”** w tej zakładce otwierający modal z drabiną.
11. Po pracy nad CRM powstaje **kontrakt dla sesji appki** (repo `woodpower_prod_app`), w stylu
    `docs/api-mobile-krawedzie-lakiernia.md`.
12. Spec z wersji 1 zostaje w historii gałęzi; ta wersja go zastępuje w miejscu.
14. **Decyzje po symulacji na produkcji (Konrad 5.10):** (K5 → 16.9 Z04) próg „Blisko terminu” **3 dni robocze** (konfigurowalny;
    5 dawało lepsze wyniki w symulacji, ale termin zamówienia to dziś 10 dni roboczych i 3 dni to świadomy start);
    grupa materiału = (gatunek, klasa, grubość) ułożona po najbliższym terminie w grupie, **w grupie termin przed
    długością**; w domyślnej drabinie **„Blisko terminu” nad „Rozpoczęte”**; grupowanie w blokach po N zamówień
    odrzucone (w symulacji wracało do dzisiejszej liczby przezbrojeń).
13. **Formatowanie i Pakowanie są zamówieniowe:** zbierają pojedyncze pozycje w zamówienie i puszczają dalej tylko całe.
    Nie mogą czekać, aż kolejka priorytetów „zwolni” ostatnią pozycję z Sklejania. Potrzebne zabezpieczenie (5.6).
15. **Lakiernia bez stołu, lista po wykończeniu (Konrad 5.10, decyzja S-6 wariant C; dziennik centrali).** Lakiernia
    (`painting`) zostaje **na stałe w trybie `stary`** i nie przechodzi na stół w P3: tablet pokazuje pełną listę
    (`GET /api/mobile/stations/painting/orders`), pracownik wybiera sam, ZAKOŃCZ bez bramki stołu, Odłóż i limit odłożeń
    jej nie dotyczą. Lista jest ułożona **po wykończeniu**: grupa = (rodzaj `parsed_finish_type` olejowane/lakierowane,
    kolor `parsed_finish_color`, połysk `parsed_finish_gloss` — te trzy pola potwierdził Konrad), cała grupa w jednym
    ciągu, bez górnego limitu liczby pozycji; grupy w kolejności najpilniejszej pozycji (najmniejsza ranga pozycji, czyli
    najwyższy priorytet zamówienia), w grupie po randze, doróbki pierwsze — 3.2 „Lista Lakierni”. **Klucz grupy
    poprawiony przez Konrada 5.10 („jak w appce”)**: rodzaj, typ koloru `parsed_finish_color_type`, kolor, a połysk
    tylko przy lakierowanych — ten sam podział na partie, który lakiernik zna z sortowania „Partia” w appce 1.7.3.
    **Doróbka ciągnie swoją grupę na początek listy** (potwierdzone przez Konrada 5.10). Pozostałe stanowiska przechodzą
    na `stol` **wszystkie naraz** w dniu wdrożenia (ustalenie 16, sekcja 11).
16. **Jedno wdrożenie (Konrad 5.10):** logistyka etapy 1–4, priorytety P1 i nowa appka (logistyka + stół) wychodzą na
    produkcję **razem** — jedno scalenie do `main`, jedno wydanie appki. Wszystkie stanowiska poza Lakiernią przechodzą
    na stół **od razu**, bez przełączania stanowisko po stanowisku. Kontrakt appki (12) powstaje przed wdrożeniem.
17. **Start stołów bez gubienia rozpoczętych (Konrad 5.10, 5.8):** w chwili przejścia system spisuje kafle **rozpoczęte
    na każdym stanowisku** (licznik sztuk z tabletu > 0 — zawężone przez Konrada po bramce K3) (K5 → 16.9 Z05) i kładzie je na stół
    (ponad K). Nowe kafle z kolejki wchodzą dopiero, gdy rozpoczęte zejdą
    poniżej K — przejście na nowe priorytety rozkłada się w czasie, ale żadne zamówienie zaczęte na stanowisku nie
    wypada z rąk. Pilne w tym czasie biuro dokłada ręcznie (ustalenie 18). Dzień wcześniej biuro widzi podgląd „to wejdzie
    na stół” i może go poprawić. Na start szczebel **„Rozpoczęte” idzie na szczyt drabiny** (krok wdrożenia, nie zmiana
    domyślnej drabiny), żeby zamówienia zaczęte na Formatowaniu/Pakowaniu dociągnęły brakujące pozycje przed nowymi.
18. **„Wyślij na stanowisko” (Konrad 5.10, 5.7):** biuro może położyć zamówienie na stół wybranego stanowiska ponad K,
    na początek stołu, z plakietką „wysłane przez biuro” — tylko te pozycje, które są w tej chwili w statusie tego
    stanowiska (bez przeskakiwania procesu). Może też zdjąć kafel ze stołu (wraca do kolejki). Każdy z dostępem do
    modułu produkcji, z wpisem w historii priorytetu zamówienia.

## 3. Zasady modelu

### 3.1 Drabina

- **Szczeble stałe gwiazdek:** ★★★★★, ★★★★, ★★★, ★★, ★, „bez gwiazdek” — zawsze w tej kolejności względem siebie.
- **Szczeble tagów:** „Po terminie”, „Blisko terminu”, **„Rozpoczęte”** — trzy stałe wiersze, które biuro **przesuwa**
  jak trasy. „Rozpoczęte” = zamówienie ma już pozycję na stanowisku zamówieniowym (Formatowanie, Pakowanie) albo dalej,
  a inną pozycję jeszcze wcześniej — czyli stanowisko zamówieniowe na nie czeka (5.6). Domyślne miejsce po migracji
  (decyzja Konrada 5.10, po symulacji: domykanie dużego zamówienia na 12.10 nie może wygrywać z małym na 5.10):
  ★★★★★, Po terminie, ★★★★, **Blisko terminu, Rozpoczęte**, ★★★, ★★, ★, bez gwiazdek.
- **Szczeble tras:** każda trasa **robocza albo zatwierdzona** ma własny szczebel. Powstaje z trasą i wchodzi
  **bezpośrednio pod najniższym szczeblem trasy**, a gdy tras nie ma — bezpośrednio pod ★★★★★. Biuro przesuwa go
  w dowolne miejsce, także pod „bez gwiazdek”. Szczebel znika z drabiny, gdy trasa przestaje być robocza/zatwierdzona
  (załadowana, w trasie, dostarczona) albo zostaje usunięta; „Cofnij załadunek” przywraca go w tym samym miejscu.
- **Szczebel zamówienia:**
  - zamówienie z przystankiem na trasie roboczej/zatwierdzonej → szczebel **trasy** (gwiazdki i tagi nie wyciągają go
    ponad trasę — trasa jest terminem wysyłki; jeśli biuro chce całą trasę wyżej, przesuwa szczebel, jeśli jedno
    zamówienie poza trasą, zdejmuje je z trasy);
  - zamówienie bez trasy → **najwyższy** ze szczebli: gwiazdek (wg `priority_stars`), „Po terminie” (termin < dziś),
    „Blisko terminu” (termin ≤ dziś + próg dni roboczych, domyślnie **3**, konfigurowalny), „Rozpoczęte” (5.6). Zamówienie z trasy
    bierze szczebel trasy także wtedy, gdy jest rozpoczęte — w obrębie trasy porządkuje je dodatkowo p. 2 w 3.2.
- **Ostrzeżenie o datach:** panel pokazuje przy drabinie uwagę, gdy kolejność szczebli tras nie zgadza się z `date_from`.
  Nic nie przesuwa samo.

### 3.2 Kolejność w obrębie szczebla

**Zamówienia** (ranga zamówienia, materializowana — 4.2):
1. pozycja szczebla na drabinie,
2. gwiazdki malejąco (ma znaczenie w szczeblu trasy; w szczeblu gwiazdek są równe; w szczeblu tagu porządkują zamówienia
   o różnych gwiazdkach),
3. **termin zamówienia** rosnąco (= najmniejszy `deadline_date` niezanulowanych pozycji, jak w panelu Logistyki (K5 → 16.9 Z06)),
4. numer zamówienia.

**Kafle na stanowisku pozycyjnym** (Wycinanie, Składanie, Sklejanie, Krawędzie; Lakiernia nie ma stołu — „Lista
Lakierni” niżej) — liczone **przy pobieraniu
na stół** (5.2), tylko wśród pozycji w statusie tego stanowiska, nieodłożonych i nieleżących na stole:
1. szczebel zamówienia (tag „Rozpoczęte” liczony **na żywo** ze statusów pozycji, 5.6), gwiazdki (jak wyżej, p. 1–2),
2. w obrębie szczebla **najpierw pozycje zamówień rozpoczętych** (domknięcie tego, na co czeka Formatowanie albo
   Pakowanie), potem pozostałe,
3. **grupa materiału** = (gatunek, klasa, **grubość**) — grupy w kolejności **najbliższego terminu w grupie** (grupa,
   w której leży najpilniejsze zamówienie, idzie pierwsza); przy równym terminie gatunek, klasa, grubość malejąco,
4. w grupie: **termin zamówienia**, potem długość malejąco, szerokość malejąco (decyzja Konrada 5.10, wariant A2
   z symulacji: te same przezbrojenia co grupowanie po samym materiale z długością przed terminem, a rozrzut pozycji
   jednego zamówienia p90 28→15 miejsc na Składaniu i 23→13 na Sklejaniu),
5. numer zamówienia, kolejność pozycji w zamówieniu.

**Kafle na stanowisku zamówieniowym** (Formatowanie, Pakowanie): zamówienia w kolejności rangi zamówienia; pozycje (K5 → 16.9 Z07)
w zamówieniu po `product_sequence_in_order`. Bez grupowania po materiale — jednostką jest zamówienie.

**Lista Lakierni** (ustalenie 15; Lakiernia nie ma stołu i zawsze pracuje w trybie `stary`). Kolejność pozycji w odpowiedzi
`GET /stations/painting/orders` i w `all_ids`/`changed` delty `/stations/painting/orders/since`, liczona **przy odczycie**
z kolumn (bez `policz()`, bez stołu, bez blokad):
1. pozycje w statusie Lakierni (`czeka_na_lakiernie`) dzielą się na **grupy wykończenia** = (`parsed_finish_type`,
   `parsed_finish_color_type`, `parsed_finish_color`, `parsed_finish_gloss` — **połysk tylko dla lakierowanych**,
   dla pozostałych pusty; klucz jak sortowanie „Partia” w appce 1.7.3, `StationSorting.kt` `batchKeyOf` — decyzja Konrada
   5.10), wartości znormalizowane (bez spacji na brzegach, małe litery, pusty napis = brak); brak wartości to osobna
   wartość klucza, nie „pasuje do wszystkiego”;
2. klucz pozycji = (doróbka ? 0 : 1, `created_at` doróbki, `priority_rank` rosnąco NULLS LAST, numer zamówienia, `id`) — (K5 → 16.9 Z08)
   doróbka ma rangę 0, więc jest najpilniejsza (3.2 „Doróbki”);
3. grupy w kolejności **najmniejszego klucza pozycji w grupie** (grupa z najpilniejszą pozycją pierwsza; grupa z doróbką
   przed każdą bez doróbki, kilka takich — po najstarszej doróbce); przy remisie rodzaj, kolor, połysk alfabetycznie (K5 → 16.9 Z09);
4. w grupie pozycje po kluczu pozycji (doróbki pierwsze, dalej ranga); cała grupa w jednym ciągu, bez limitu liczby
   pozycji — także gdy w środku stoją pozycje mniej pilne niż pierwsza pozycja następnej grupy (świadomie: jedno
   rozrobione wiadro);
5. pozostałe pozycje zamówień z listy (w innych statusach — lista oddaje całe zamówienia, appka pokazuje je jako kontekst)
   na końcu, po dzisiejszym kluczu (`priority_rank` NULLS LAST, numer, `id`).

Ranga pozycji to pamięć podręczna z ostatniego `utrwal()` (4.2), więc tag „Rozpoczęte” i tagi terminowe działają na
Lakierni z opóźnieniem do najbliższego przeliczenia (cron co godzinę) — jak na monitorach (7.2). Pozostałe stanowiska:
lista `/orders` bez zmian (sort po randze), a w trybie `stol` kolejność kafli wg reguł wyżej. Reguła listy Lakierni
(klucz grupy i doróbka ciągnąca grupę) **potwierdzona przez Konrada 5.10** (ustalenie 15).

**Doróbki** (`original_product_id IS NOT NULL`) zawsze pierwsze na każdym stanowisku, po `created_at` — reszta zamówienia
czeka na nie w pakowaniu. **Cena grupowania:** w dużym szczeblu pozycje jednego zamówienia rozjeżdżają się po kolejce.
Granicę stawia tag „Rozpoczęte” (5.6): gdy pierwsza pozycja zamówienia dotrze na Formatowanie, pozostałe wskakują na
szczebel tagu i w jego obrębie na początek, więc rozrzut pozycji jednego zamówienia nie przekracza mniej więcej jednego
stołu Sklejania. W szczeblach stojących nad tagiem (np. trasa na szczycie) grupowanie działa w pełni — tam wszystkie
pozycje i tak idą zaraz po sobie.

### 3.3 Przykład

Drabina biura: `1 [trasa Śląsk]`, `2 [★★★★★]`, `3 [Po terminie]`, `4 [★★★★]`, `5 [trasa Mazowsze]`, `6 [Blisko terminu]`,
`7 [★★★]`, `8 [trasa Pomorze]`, `9 [★★]`, `10 [★]`, `11 [bez gwiazdek]`.

| Zamówienie | Trasa | Gwiazdki | Termin | Szczebel | Wynik |
|---|---|---|---|---|---|
| A | Śląsk | ★★ | 17.10 | 1 | 1. (trasa; w trasie ★★ przed ★0) |
| B | Śląsk | — | 21.10 | 1 | 2. |
| C | — | ★★★★★ | 20.10 | 2 | 3. |
| H | — | ★ | 2.10 (po terminie) | 3 | 4. — tag wyciąga je ponad ★★★★ |
| D | Mazowsze | ★★★★ | 24.10 | 5 | 5. |
| E | — | ★★★ | 6.10 (blisko) | 6 | 6. — tag „Blisko terminu” stoi nad ★★★ |
| F | Pomorze | ★★★★★ | 27.10 | 8 | 7. — **mimo pięciu gwiazdek**, bo trasa decyduje |
| G | — | — | 27.10 | 11 | 8. |

Na Sklejaniu pozycje A i B (szczebel 1): **najpierw wszystkie pozycje A (★★), potem B (bez gwiazdek)** — gwiazdki
porządkują w obrębie trasy przed grupowaniem po materiale (3.2 p. 1–2; decyzja z rozmowy 4.10: „wyższe w tej samej trasie
mają wyższy priorytet”). W obrębie A: grupa dąb A/B 4 cm przed 3 cm, w grupie po długości malejąco (ten sam termin);
tak samo w obrębie B. Grupowanie po materiale łączy zamówienia tylko o **równych** gwiazdkach w szczeblu — przykład
Konrada z rozmowy (cztery zamówienia bez gwiazdek, 4 cm przed 3 cm) dotyczy właśnie takiego przypadku. Rozstrzygnięte
5.10 przy planie K1 (recenzja wykryła sprzeczność narracji z regułą; obowiązuje reguła 3.2).

## 4. Serwis priorytetów — ranga

### 4.1 Pojęcia

| Pojęcie | Definicja |
|---|---|
| **Gwiazdki** | `prod_orders.priority_stars` 0–5. Ustawia biuro. |
| **Szczebel** | Wiersz drabiny: `stars` (5..0), `tag` (`po_terminie`, `blisko_terminu`) albo `route` (K5 → 16.9 Z10) (`route_id`). Ma `position`. |
| **Termin zamówienia** | min `deadline_date` niezanulowanych pozycji (liczony, nie przechowywany) (K5 → 16.9 Z11). |
| **Zamówienie aktywne** | ma ≥1 pozycję w `STATUSY_PRODUKCJI` (7 statusów `czeka_na_*`). `anulowane`, `wstrzymane`, statusy po spakowaniu — poza kolejką. `w_realizacji` nikt nie nadaje — poza listą. |
| **Ranga zamówienia** | `prod_orders.priority_rank` 1..M wg 3.2 (zamówienia); `prod_orders.priority_rung` = pozycja szczebla. |
| **Ranga pozycji** | `prod_products.priority_rank` = ranga zamówienia × 100 + `product_sequence_in_order` (K5 → 16.9 Z12) (pamięć podręczna dla czytelników SQL i starej appki; doróbki 0). |
| **Stół stanowiska** | kafle leżące na stanowisku (5.1). |

### 4.2 Algorytm (`priorytety/services/kolejka.py`)

```
policz(migawka) -> rangi zamówień i pozycji
  drabina = szczeble po position (gwiazdki, tagi zawsze; trasy tylko robocza/zatwierdzona)
  dla zamówienia aktywnego Z:
      termin(Z)   = min deadline_date aktywnych pozycji
      tagi(Z)     = {po_terminie jeśli termin < dziś; blisko_terminu jeśli termin <= dziś + próg dni roboczych;
                     rozpoczete jeśli Z ma pozycję w statusie stanowiska zamówieniowego lub dalej
                     i pozycję w statusie wcześniejszym (5.6)}
      szczebel(Z) = drabina[trasa Z] jeśli przystanek na trasie roboczej/zatwierdzonej
                    inaczej min position z {drabina[gwiazdki Z]} ∪ {drabina[t] for t in tagi(Z)}
      klucz(Z)    = (szczebel.position, -gwiazdki, termin, numer)
  rangi zamówień 1..M po klucz; priority_rung = position    ← (K5 → 16.9 Z13)
  pozycje aktywne: doróbki → 0; inne → ranga zamówienia*100 + sequence
  is_priority(pozycja) = doróbka or gwiazdki >= 1 or po_terminie   # ramka starej appki, licznik /summary

utrwal() -> raport
  WŁASNA sesja (jak dziś priority_service: nigdy db.session), jedna transakcja: czyta zamówienia aktywne, pozycje,
  przystanki, trasy, szczeble; policz(); zapisuje TYLKO zmienione: zamówienia (priority_rank, priority_rung)
  i pozycje (priority_rank, is_priority), każdą tabelę jednym flushem rosnąco po id; commit; po MySQL 1213 jedno    ← (K5 → 16.9 Z14)
  ponowienie na nowej sesji (blokady_zamowien.kod_mysql).
```

**Dlaczego pamięć podręczna.** Czytelników rangi jest kilkunastu (stara lista tabletu, delta `since`, wyszukiwarka,
Lista produkcyjna z sortowaniem w SQL, eksporty, zakładka Stanowiska, raporty). Zmiana rangi podbija `updated_at`
pozycji, co napędza ETag starej appki. Liczymy raz po każdym zdarzeniu (9.3). **Stół** (5.2) czyta `priority_rung`
i `priority_rank` zamówienia z kolumn, ale tag „Rozpoczęte” liczy **na żywo** ze statusów pozycji (ZAKOŃCZ zmienia
statusy bez `utrwal()`, a na ten tag nie wolno czekać do crona) i dokłada grupowanie po materiale wśród kandydatów.
Kolumny nadrabia cron (9.3).

**Zapis zamówień przez `utrwal()`** (nowość wobec dziś: `priority_service` pisał tylko pozycje). Reguła z CLAUDE.md
dla pisarzy pozycji bez blokady zamówienia zakłada, że nie dotykają `prod_orders`. `utrwal()` pisze obie tabele,
więc **bierze blokady jak hurt**: zamówienia `FOR UPDATE` rosnąco po id, potem pozycje tych zamówień rosnąco po id,
dopiero zapisy — ale tylko dla wierszy, które zmienia (przeliczenie rzadko zmienia wszystko). Nie bierze blokady tras
(czyta trasy tylko do odczytu). Jedno ponowienie po 1213 jak dotąd.

**Doróbka bez przeliczenia.** `reject_product_quantity` nadaje nowej doróbce `priority_rank = 0`; najbliższe
`utrwal()` niczego tu nie zmienia (doróbki mają 0 z definicji). Zastępuje `lock_priority(rank=1)`; kasowanie rangi
na Formatowaniu (`complete_task`, `models.py:714-719`) znika.

### 4.3 Termin — ustawienia

Zakładka Konfiguracja, grupa „Terminy” (dziś „priorities”) (K5 → 16.9 Z15): `DEADLINE_DEFAULT_DAYS` (surowe, 16), `DEADLINE_FINISHED_DAYS`
(z wykończeniem, 21; na produkcji ustawione dziś na 10 dni roboczych) — bez zmian — oraz nowy `DEADLINE_DAY_TYPE` ∈ {`robocze`, `kalendarzowe`} (domyślnie `robocze`,
czyli dzisiejsze zachowanie). **Decyzja Konrada 5.10 (po K5):** wartości trzymane **w bazie**, zmieniane w Konfiguracji
bez wdrożenia — surowe **10**, z wykończeniem **14** dni roboczych; migracja zakłada brakujące wiersze (`INSERT IGNORE`,
na produkcji brakowało `DEADLINE_FINISHED_DAYS`), a wartości awaryjne w kodzie (gdy wiersza brak) też 10 / 14.
`sync_service._calculate_deadline_date` czyta przełącznik i wybiera `_add_business_days`
albo zwykłe `timedelta`. „Surowe” = żadna pozycja zamówienia nie jest wykończona (`_order_has_finished_product`), jak dziś.
**Zamówienia już zaimportowane zachowują swój termin** — żadnego przeliczania wstecz (decyzja Konrada 4.10). Próg
„Blisko terminu” (`priorytety_blisko_terminu_dni`, domyślnie **3**, dni robocze; decyzja 5.10) stoi obok.

### 4.4 Cykl życia szczebla trasy

| Zdarzenie | Skutek |
|---|---|
| `routes.utworz` | `drabina.zapewnij_szczebel_trasy(route)` **pod blokadą tras**, którą `utworz` trzyma: nowy wiersz w miejscu domyślnym (3.1); renumeracja `position` 1..n. |
| `routes.usun` | FK `ON DELETE CASCADE`. (K5 → 16.9 Z16) |
| zatwierdzenie / cofnięcie do roboczej | bez zmian. |
| załadowana / w trasie / dostarczona | szczebel ukryty (filtr po statusie trasy), wiersz zostaje. |
| przesunięcie w panelu | `drabina.przesun(rung_id, pozycja)` pod blokadą tras; szczeble gwiazdek nieruchome (400 `szczebel_staly`), tagi i trasy ruchome; log. |
| trasa bez zamówień w produkcji | szczebel zostaje, wyszarzony, z licznikiem „0 w produkcji”. |
| trasa bez szczebla (okno wdrożenia) | `policz()` liczy ją w miejscu domyślnym i loguje WARNING; `GET /drabina` dopisuje brakujące pod blokadą tras. |

### 4.5 Zasady brzegowe

- Zamówienie z pozycjami na Wycinaniu i Składaniu jest w obu kolejkach z tym samym kluczem.
- Zamówienie częściowo spakowane jest aktywne, dopóki ma pozycję w produkcji.
- Przystanek na trasie załadowanej/w trasie/dostarczonej nie liczy się jako trasa.
- Zmiana sposobu dostawy z transportu zdejmuje z trasy roboczej → szczebel gwiazdek/tagów przy najbliższym `utrwal()`.
- `wstrzymane` nie są aktywne — hurtowa zmiana statusu to narzędzie biura „zabierz z kolejki”.
- Zamówienia bez `deadline_date` (ręczne, stare): termin = brak → sortują się na końcu swojego szczebla; tagi nie działają (K5 → 16.9 Z17).

## 5. Stół stanowiska, Odłóż, sygnały

### 5.1 Stół

**Stół** stanowiska to zbiór kafli, które tablet(y) tego stanowiska pokazują jako „do zrobienia”. Jest stanem
**serwera** (tabela `prod_station_desk`, 8.4), wspólnym dla wszystkich tabletów stanowiska. Ma **K miejsc** (ustawienie
`priorytety_stol_<S>`, domyślnie 2). **Jednostka kafla** zależy od stanowiska (`priorytety_jednostka_<S>`): `pozycja`
dla Wycinania, Składania, Sklejania, Krawędzi, Lakierni; `zamowienie` dla Formatowania i Pakowania (K5 → 16.9 Z18) (jak dziś w appce).

Kafel **leży** na stole od pobrania do zakończenia albo odłożenia. **Zmiany priorytetów w biurze nie ruszają kafli na
stole** (ustalenie 5): dotyczą tego, co wejdzie następne. Kafel schodzi ze stołu, gdy:
- ZAKOŃCZ przestawi status pozycji (kafel-pozycja) albo wszystkich niezanulowanych pozycji zamówienia na tym stanowisku
  (kafel-zamówienie) — zwykłe `complete_task`;
- pracownik go **odłoży** (5.3) — kafel przechodzi do „Odłożonych”, nie na stół;
- pozycja/zamówienie zniknie ze stanowiska inaczej: wstrzymanie, anulowanie, usunięcie z Base., doróbka, hurtowa zmiana
  statusu → serwer usuwa wiersz stołu w tej samej transakcji (reguła w `priorytety/services/stol.py`, wołana z tych
  samych miejsc, które dziś podbijają `updated_at`).

**Doróbka** stoi **na początku kolejki** stanowiska (3.2) i wchodzi na stół **w ramach K**, jako pierwsza przy
najbliższym dopełnieniu (decyzja Konrada 5.10 po bramce K3 — wersja „ponad K” kładła pierwszego dnia 11 zaległych doróbek
na stół Wycinania i 9 na Składanie). Reszta zamówienia czeka na nią w pakowaniu, więc w kolejce jest przed wszystkim.
Ponad K wchodzą kafle **wysłane przez biuro** (5.7) i kafle **startowe** (5.8). Każdy wiersz
stołu ma **źródło** (`zrodlo`, 8.4): `kolejka` (pobrany przez dopełnienie), `dorobka`, `biuro`, `start`. Dopełnienie (5.2)
liczy wszystkie kafle leżące na stole (bez odłożonych), niezależnie od źródła, i dobiera z kolejki dopiero, gdy jest ich
mniej niż K. Kolejność na stole: doróbki, wysłane przez biuro, startowe, pobrane — w każdej grupie po czasie wejścia. Pakowanie: **zamówienie bez sposobu dostawy wchodzi na stół jak każde inne** (decyzja Konrada 5.10, „najwyżej
logistyka wróci na przepakowanie”; logistyka krok 4.6, `claude/logistyka-etap-4` @ `f07b21ec`: serwer nie zwraca już 409
`delivery_method_not_set`, bez statusu Base. przy spakowaniu bez sposobu, etykieta „NIE USTAWIONO”, pierwsze ustawienie
sposobu przez okno 8.7 logistyki). Stół, „Wyślij” (5.7) i bramka Pakowania nie odrzucają takich zamówień — po scaleniu
logistyki 4.6 do gałęzi priorytetów (karta scalenia). Nowa appka zdejmuje własną blokadę ZAKOŃCZ bez sposobu dostawy
(`DeliveryGate` w appce 1.7.3); stara appka blokuje dalej po swojej stronie.

### 5.2 Pobieranie na stół

Pobieranie jest **leniwe, przy odczycie** (K5 → 16.9 Z19): `GET /api/mobile/stations/<kod>/desk` (6.1) dopełnia stół do K kafli
z kolejki stanowiska (3.2) i oddaje wynik. Tablet woła tę końcówkę po własnym ZAKOŃCZ/Odłóż, po sygnale (5.4) i co 30 s,
gdy stół jest pusty. Pobieranie **nie jest** częścią transakcji ZAKOŃCZ, bo ZAKOŃCZ trzyma blokadę X na zamówieniu
i jego pozycjach, a pobranie czyta pozycje **innych** zamówień: drugi tablet w ZAKOŃCZ innego zamówienia dałby cykl
blokad (MySQL 1213). Osobne żądanie nie trzyma żadnej blokady zamówienia.

Kolejność blokad pobrania: `FOR UPDATE` na wierszu `prod_config` `priorytety_stol_<kod>` (jeden pobierający na
stanowisko; wiersz zakłada migracja, kod dopisze `INSERT IGNORE` gdy brak — jak blokada tras) → kandydaci odczytem
bieżącym (`with_for_update(read=True).populate_existing()`, pozycje w statusie stanowiska poza stołem i odłożeniami, (K5 → 16.9 Z20)
posortowane wg 3.2) → `INSERT` wierszy stołu → commit → sygnał (5.4). Dwa tablety wołające `desk` naraz: drugi czeka
na blokadzie i widzi już pełny stół. Rzadkie 1213 z ZAKOŃCZ innego zamówienia (gap na indeksie stołu) — jedno
ponowienie całego pobrania (`blokady_zamowien.kod_mysql`), jak w hurcie. Wiersz blokady nazywa się
`priorytety_blokada_<kod>` (8.6; wyżej dawna nazwa robocza).

**Limit czekania (K3, potwierdzony 5.10):** transakcja dopełnienia czeka na cudzą blokadę najwyżej **5 s** (sesyjny
`innodb_lock_wait_timeout`, przywracany przed commitem/rollbackiem na tym samym połączeniu). Po przekroczeniu (1205)
`desk` nie ponawia i oddaje **200 z bieżącym stołem bez dopełnienia** — tablet dopełni przy następnym wywołaniu. Ten sam
limit ma własna sesja `kolejka.utrwal` (1205 → `success: False`, cron nadrabia). Powód: jedna długo trzymana blokada
zamówienia nie może zawiesić tabletów całego stanowiska ani workerów gunicorna.

### 5.3 Odłóż

- Przycisk **„Odłóż”** na kaflu obok ZAKOŃCZ otwiera modal z powodem: `brak_materialu`, `awaria_maszyny`,
  `brak_miejsca`, `czeka_na_biuro`, `inne` (wymaga notatki). Odłożenie dotyczy **kafla** (pozycja na stanowisku
  pozycyjnym, zamówienie na zamówieniowym).
- Odłożony kafel **zostaje na tablecie** w sekcji „Odłożone” (z powodem, godziną, pracownikiem) i da się go **zakończyć**
  w każdej chwili (ZAKOŃCZ działa na kaflu odłożonym tak samo jak na kaflu na stole). Nie wraca do kolejki i nie jest
  pobierany ponownie — nie staje się „mniej ważny”, tylko czeka na pracownika (ustalenie 6).
- **Limit** otwartych odłożeń na stanowisko (`priorytety_limit_odlozen_<S>`, domyślnie 10): przy limicie Odłóż odpowiada
  409 `limit_odlozen` z komunikatem „Na Sklejaniu leży 10 odłożonych zamówień. Zamknij któreś, zanim odłożysz kolejne.” (K5 → 16.9 Z21)
- Odłożenie zapisuje wiersz `prod_priority_log` (`action='odlozenie'`: stanowisko, zamówienie, pozycja, powód, notatka,
  pracownik, urządzenie). ZAKOŃCZ odłożonego kafla zapisuje `odlozenie_zamkniete` (czas leżenia liczy raport).
- **Biuro** widzi odłożenia w Liście produkcyjnej: plakietka „Odłożone na Sklejaniu: brak materiału, 9:40, Adam” na karcie
  zamówienia i lista w modalu priorytetu. Nie ma „Przywróć” — odłożony kafel i tak jest na tablecie (K5 → 16.9 Z22); biuro reaguje
  gwiazdkami, wstrzymaniem albo dowiezieniem materiału. Odłożenie znika razem z kaflem (ZAKOŃCZ, wstrzymanie, anulowanie).

### 5.4 Sygnały zamiast odpytywania

Wzór z agenta druku: **najpierw baza, potem sygnał, sygnał bez ładunku**. Kanał `station:<kod>` (namespace już w
konfiguracji brokera). Serwer publikuje po commicie:

| Zdarzenie | Kanał | Co robi tablet po sygnale |
|---|---|---|
| ZAKOŃCZ (kafel schodzi, pozycja idzie dalej) | `station:<to stanowisko>` i `station:<następne stanowisko pozycji>` | `GET desk`: pierwszy tablet widzi nowy kafel, drugi — zniknięcie zamkniętego; następne stanowisko dopełnia pusty stół |
| zmiana licznika sztuk (`PATCH quantity`) | `station:<to stanowisko>` | `GET desk`: drugi tablet widzi „2/15” |
| Odłóż | `station:<to stanowisko>` | `GET desk`: kafel w „Odłożonych”, nowy na stole |
| pobranie na stół przez jeden tablet | `station:<to stanowisko>` | drugi tablet dociąga ten sam stół |
| zdjęcie kafla przez biuro/Base./doróbkę (K5 → 16.9 Z23) | `station:<to stanowisko>` | `GET desk` |

W API mobilnym publikację planuje handler (`g`, jak `print_queue_service.zaplanuj_sygnal_po_commicie`), a wysyła
`with_idempotency` po udanym commicie — rozszerzenie dekoratora o drugi rodzaj sygnału. Z panelu i crona: po commicie
routera. **Zabezpieczenie:** tablet z pustym stołem odpytuje `desk` co 30 s; tablet ze stołem — co 5 min (K5 → 16.9 Z24) (siatka na
zgubiony sygnał i na wyłączony realtime: `REALTIME.enabled=false` oznacza dziś dla agenta druku zwykły polling i tak samo
ma być dla tabletów). Token: `GET /api/mobile/realtime-token` (jak `/api/print-agent/realtime-token`), kanał
w tokenie = stanowisko urządzenia (tablet Krawędzi: `station:edges` i `station:painting`).

### 5.5 Bramki ZAKOŃCZ

W trybie `stol` (6.3) serwer przyjmuje ZAKOŃCZ i `PATCH quantity` tylko dla kafla **na stole albo odłożonego** tego (K5 → 16.9 Z25)
stanowiska; inaczej 409 `nie_na_stole` („Zamówienie 1234 nie leży na stole Sklejania.”). Nowa appka tego błędu nie zobaczy (K5 → 16.9 Z26)
(pokazuje tylko stół i odłożone); to bramka na błędy i na starą appkę. `reject` (doróbka) i druk etykiet — bez bramki.
`delivery_method_not_set` znika po logistyce 4.6 (5.1). Stara appka (`last_app_version_code` < próg) dostaje zachowanie
`stary`: pełna lista, ZAKOŃCZ bez bramki, a jej ZAKOŃCZ zdejmuje kafel ze stołu, jeśli tam leżał.

**Lakiernia zawsze `stary`** (ustalenie 15): bramka stołu nie obowiązuje jej nigdy, niezależnie od wartości
`priorytety_tryb_painting` i wersji appki — stanowisko jest w stałej `STANOWISKA_BEZ_STOLU = ('painting',)` (K5 → 16.9 Z27)
(`priorytety/stale.py`), a `stol.bramka_zakoncz` przepuszcza je jak tryb `stary`. Pomyłkowe `stol` w Konfiguracji nie
zablokuje więc ZAKOŃCZ z listy. `desk` i `postpone` dla `painting` odpowiadają 409 `stanowisko_bez_stolu` („Lakiernia
pracuje z listy, bez stołu.”) i niczego nie zapisują — stół Lakierni nigdy nie powstaje.

### 5.6 Stanowiska zamówieniowe: kompletność i zabezpieczenia

Formatowanie i Pakowanie **zbierają** pozycje w zamówienie i puszczają dalej tylko całe. Grupowanie po materiale na
Sklejaniu (i wcześniej) rozrzuca pozycje jednego zamówienia w czasie, więc bez zabezpieczeń Formatowanie dostawałoby
zamówienia po kawałku i stałoby z zajętym stołem. Trzy reguły, wszystkie w ramach modelu:

1. **Tag „Rozpoczęte” na drabinie** (3.1). Zamówienie, którego pierwsza pozycja dotarła na stanowisko zamówieniowe
   (status `czeka_na_formatowanie`, `czeka_na_pakowanie` albo dalszy w produkcji), a inna pozycja jest jeszcze wcześniej,
   dostaje tag — automatycznie, bez udziału biura, liczony na żywo przy każdym pobraniu na stół. Pozostałe pozycje tego
   zamówienia na Sklejaniu (Wycinaniu, Składaniu, Krawędziach, Lakierni) wskakują na szczebel tagu i w jego obrębie na
   początek (3.2 p. 2). Biuro decyduje, gdzie tag stoi: domyślnie pod ★★★★ — czyli „domknij rozpoczęte, zanim weźmiesz
   nowe bez gwiazdek”, ale pięć i cztery gwiazdki oraz trasy nad tagiem idą pierwsze. Zamówienie z trasy nie zmienia
   szczebla (trasa decyduje), ale w obrębie trasy jego pozostałe pozycje też idą na początek.
   Pozycje, które omijają Formatowanie (`cut_to_size = False` → prosto do pakowania) albo Krawędzie, liczą się według
   własnej ścieżki: tag patrzy na statusy, nie na nazwę stanowiska.
2. **Stół stanowiska zamówieniowego nie czeka na niekompletne zamówienia.** Kafel-zamówienie jest **kompletny**, gdy
   żadna niezanulowana pozycja zamówienia nie jest w statusie **wcześniejszym** niż status tego stanowiska (pozycje już
   dalej liczą się jako zrobione). **Pozycja, której ścieżka omija to stanowisko** (np. bez docięcia — `cut_to_size =
   False` — nie idzie na Formatowanie), **nie liczy się** do kompletności tego stanowiska, nawet gdy stoi jeszcze
   wcześniej (decyzja centrali 5.10 po bramce K3 — inaczej trzymałaby zamówienie w „Niekompletnych” Formatowania, choć
   tam nigdy nie trafi; liczy się do kompletności Pakowania). Pobieranie na stół (5.2) bierze **kompletne** zamówienia w kolejności rangi; zajmują
   K miejsc. Zamówienia **niekompletne**, których część pozycji już czeka na tym stanowisku, tablet pokazuje w osobnej
   sekcji **„Niekompletne”** (do K sztuk, w kolejności rangi) z postępem „3/5 na stanowisku, 2 na Sklejaniu” — pracownik
   może formatować to, co przyszło (ZAKOŃCZ pozycji działa), ale zamówienie nie blokuje miejsca na stole i nie da się go
   „puścić dalej”, dopóki nie dojdą pozostałe (to robi już dzisiejsze `complete_task` per pozycja: ostatnia pozycja
   kończy zamówienie na tym stanowisku). Gdy wejdzie ostatnia pozycja, zamówienie staje się kompletne i przy następnym
   pobraniu wchodzi na stół na swoje miejsce — z zachowaniem postępu.
3. **Sygnał na następne stanowisko** (5.4) idzie przy każdym ZAKOŃCZ, więc Formatowanie dowiaduje się o dojściu ostatniej
   pozycji od razu, nie po 30 s.

Co to daje: Sklejanie batchuje po materiale, ale raz rozpoczęte zamówienie domyka w ciągu mniej więcej jednego stołu;
Formatowanie zawsze ma na stole coś, co da się skończyć, i widzi, na co czeka. Pakowanie działa tak samo (dochodzą
pozycje z Krawędzi, Lakierni i prosto z Formatowania/Sklejania).

**Przykład.** Zamówienie X (bez gwiazdek, 4 pozycje: 190×50×4, 180×70×4, 180×60×3, 170×78×3) i Y (bez gwiazdek, 3 pozycje
po 4 cm). Sklejanie grupuje: 4 cm z X i Y razem, potem 3 cm. Po zakończeniu 190×50×4 z X pozycja idzie na Formatowanie,
X staje się „Rozpoczęte” (szczebel 4 zamiast 9): 180×70×4, 180×60×3 i 170×78×3 z X wchodzą na stół Sklejania przed
pozostałymi 4 cm z Y. Formatowanie w sekcji „Niekompletne” widzi X „1/4 na stanowisku, 3 na Sklejaniu” i może zacząć.

**Czego nie robimy:** nie wstrzymujemy grupowania ani nie zmuszamy Sklejania do pracy zamówienie po zamówieniu —
to byłoby wyrzucenie korzyści z batchowania. Bloki po N zamówień sprawdzone w symulacji i odrzucone (sekcja 14);
rozrzut ogranicza rozjemca terminu w grupie (3.2 p. 4) i tag „Rozpoczęte”.

### 5.7 „Wyślij na stanowisko” i „Zdejmij ze stołu” (biuro, ustalenie 18)

- **Wyślij:** `POST /production/api/priorytety/stoly/<S>/wyslij` `{order_id}` — `guard` biura (7.3). Kładzie na stół `S`
  kafle zamówienia, które są **w tej chwili** w statusie stanowiska `S`: na stanowisku pozycyjnym każdą taką pozycję jako
  osobny kafel, na zamówieniowym kafel-zamówienie (także niekompletne — biuro świadomie je wypycha; ZAKOŃCZ pozycji działa
  jak w 5.6). Ponad K, `zrodlo='biuro'`, na początek stołu (5.1), plakietka „wysłane przez biuro”.
  - kafel już na stole → bez zmian (200, `juz_na_stole`); kafel **odłożony** → wraca na stół (zdjęte `postponed_*`,
    `zrodlo='biuro'`) — to jest jedyne „przywróć” odłożenia i robi je biuro, nie tablet (5.3);
  - żadna pozycja zamówienia nie jest w statusie `S` → 409 `brak_na_stanowisku` (nie przeskakujemy procesu);
  - Lakiernia → 409 `stanowisko_bez_stolu` (ustalenie 15);
  - działa w trybie `stary` i `stol` (w `stary` służy przygotowaniu startu, 5.8).
- **Zdejmij:** `POST /production/api/priorytety/stoly/<S>/zdejmij` `{unit_key}` — usuwa wiersz stołu (na stole albo
  odłożony); kafel wraca do kolejki stanowiska. Służy poprawkom podglądu startu (5.8) i pomyłkom biura.
- Blokady: jak dopełnienie (5.2, 9.4) — blokada stołu `priorytety_blokada_<S>` → odczyt bieżący zamówienia i jego pozycji
  (`FOR SHARE`) → INSERT/UPDATE/DELETE wiersza stołu → commit → sygnał `station:<S>`. Bez blokad X zamówień.
- Log `prod_priority_log`: `wyslanie` / `zdjecie` (stanowisko, zamówienie, pozycja, użytkownik). Modal priorytetu (7.1)
  pokazuje to w historii.

### 5.8 Start stołów — przejście bez gubienia rozpoczętych (ustalenie 17)

**Kafel rozpoczęty na stanowisku `S`** (stanowiska ze stołem, bez Lakierni) — na stanowisku coś już przy nim zrobiono
**ręcznie** (z tabletu, nie automatycznym przeskokiem stanowiska `auto_skip`/`system`):
- jednostka `pozycja`: pozycja w statusie `S`, która ma licznik `quantity_done_<S>` > 0 (z tabletu); (K5 → 16.9 Z28)
- jednostka `zamowienie`: zamówienie z pozycją w statusie `S`, która ma licznik `S` > 0 (z tabletu).
**Zawężone przez Konrada 5.10 po bramce K3:** reguła „inna pozycja zamówienia już zrobiona na `S`” odpada — na kopii
danych dawała 53 z 74 kafli (Składanie 27 z 34 pozycji, czyli praktycznie starą listę); sam licznik daje 21 kafli, czyli
to, co ludzie mają w rękach. Resztę biuro dokłada „Wyślij” na podstawie podglądu.
Źródło „ręcznie”: `prod_station_events` (`ProductionStationEvent`, pole źródła zdarzenia) — plan (K5 → 16.9 Z29)
K3 ustala dokładny warunek na kodzie; pozycje pominięte automatycznie (np. `cut_to_size = False`) się nie liczą.

**Przebieg** (runbook K7):
1. **Podgląd** (dzień wcześniej i w dniu startu): `GET /production/api/priorytety/start` — dla każdego stanowiska lista
   kafli rozpoczętych („to wejdzie na stół”) z liczbą; bez zapisu. Panel (Konfiguracja, grupa „Stół stanowisk”).
2. **Przygotuj** (admin, po zakończeniu zmiany): `POST /production/api/priorytety/start/przygotuj` — wpisuje kafle
   rozpoczęte jako wiersze stołu `zrodlo='start'` (stanowiska jeszcze w `stary`, tablety tego nie widzą; ZAKOŃCZ
   w `stary` i tak zdejmuje kafel ze stołu, 5.5). Idempotentne (UNIQUE); ponowne wywołanie dokłada tylko nowe
   rozpoczęte — kafle zdjęte ręcznie wrócą, jeśli nadal są rozpoczęte, więc poprawki robi się po ostatnim przebiegu.
   Blokady jak dopełnienie, stanowisko po stanowisku, każde w osobnej transakcji. Log `start_stolow` (liczby).
3. **Poprawki biura:** „Wyślij” (5.7) dokłada to, co ludzie mają w rękach, a dane tego nie widzą; „Zdejmij” usuwa to,
   czego na stole być nie powinno.
4. **Włącz** (admin, przed rozpoczęciem zmiany): `priorytety_min_app_version_code` = kod nowej appki i (K5 → 16.9 Z30)
   `priorytety_tryb_<S>` = `stol` dla sześciu stanowisk — jeden zapis ustawień (Konfiguracja albo
   `PUT /production/api/priorytety/ustawienia`). Biuro przesuwa „Rozpoczęte” na szczyt drabiny (ustalenie 17).
5. Stoły dopełniają się z kolejki, gdy kafle startowe zejdą poniżej K; pilne — „Wyślij”. Po zejściu startowych biuro
   przestawia „Rozpoczęte” na domyślne miejsce (pod ★★★★) — decyzja biura, bez wdrożenia.

**Wycofanie:** `priorytety_tryb_<S>` → `stary` (jak dotąd, 11); wiersze startowe mogą zostać (w `stary` nie blokują).
**Liczba kafli startowych** na każdym stanowisku mierzona na kopii produkcji w K5 (i podglądem w dniu startu); jeśli na
którymś stanowisku wyjdzie wyraźnie więcej, niż hala skończy w jedną zmianę — decyzja Konrada (zawężenie definicji albo
poprawki biura).

## 6. API mobilne — kontrakt (zakres; pełny kontrakt dla sesji appki powstaje po P1 — sekcja 12)

### 6.1 `GET /api/mobile/stations/<kod>/desk` (nowa)

Dopełnia stół (5.2) i oddaje:
```json
{
  "station_code": "gluing",
  "tryb": "stol",                             // "stary" | "stol" — appka pokazuje stół tylko przy "stol" (K3-poprawka-2)
  "jednostka": "pozycja",                     // "pozycja" | "zamowienie"
  "miejsca": 2,
  "stol": [ { "kafel": {...}, "pobrano": "2026-10-05T09:12:40", "zrodlo": "kolejka" } ],  // kolejka|dorobka|biuro|start
  "odlozone": [ { "kafel": {...}, "odlozono": "2026-10-05T08:50:01", "powod": "brak_materialu",
                  "notatka": "czekamy na dąb 4 cm", "pracownik": "Adam K." } ],   // imię + inicjał nazwiska (Konrad 5.10); pełne tylko w panelu
  "niekompletne": [ { "kafel": {...}, "na_stanowisku": 3, "pozycji": 5,
                      "brakuje": [ {"short_id": "1203_4", "stanowisko": "gluing"} ] } ],   // tylko jednostka "zamowienie"
  "limit_odlozen": 10,
  "kolejka_dalej": 37                          // ile kafli czeka w kolejce stanowiska (informacyjnie)
}
```
`kafel` dla jednostki `pozycja` = dzisiejszy obiekt pozycji z `serialize_order` (wszystkie pola jak dotąd) plus
`priorytet: {gwiazdki, szczebel: "trasa"|"gwiazdki"|"po_terminie"|"blisko_terminu"|"dorobka", trasa: {id,nazwa,data}|null,
pozycja_w_zamowieniu: "2/5"}` (K5 → 16.9 Z31). Dla jednostki `zamowienie` = `{zamowienie: {...}, pozycje: [kafel-pozycja, ...]}`
z tymi samymi polami. Stół może mieć **więcej niż `miejsca`** kafli (doróbki, wysłane przez biuro, startowe (K5 → 16.9 Z32) — 5.1, 5.7, 5.8).
ETag jak w liście (max `updated_at` + liczba + `KSZTALT`) (K5 → 16.9 Z33), żeby odpytywanie co 30 s przy pustym
stole było tanie.

### 6.2 Odłóż: `POST /api/mobile/orders/<id>/postpone`

Body: `{station_code, zakres: "pozycja"|"zamowienie", powod, notatka?}`; `X-Worker-Ids` jak w ZAKOŃCZ; `with_idempotency`.
Odpowiedzi: 200 ze stołem jak w 6.1; 409 `limit_odlozen`; 409 `nie_na_stole` (K5 → 16.9 Z34) (kafel nie leży na stole — np. drugi tablet
już go zakończył); 400 `powod_niepoprawny`.

### 6.3 ZAKOŃCZ, licznik, lista

- `POST /orders/<id>/complete`, `PATCH /orders/<id>/quantity` — bez zmian w ciele; w trybie `stol` bramka 5.5;
  po commicie sygnały 5.4; odpowiedź jak dotąd.
- `GET /stations/<kod>/orders` i `/orders/since` zostają dla starej appki i wyszukiwarki; dochodzi `priorytet` na pozycji
  i `KSZTALT_ODPOWIEDZI_KOLEJKI` → 6. `priority_rank` i `is_priority` jak dotąd (4.1).
- `GET /stations/<kod>/summary` → `refresh_interval_seconds` zostaje (stara appka); nowa appka czyta `desk`.
- `GET /api/mobile/realtime-token` (nowa) — `{enabled, token, ttl_seconds, sse_url, channels}`; 503 gdy realtime wyłączony (K5 → 16.9 Z35)
  (appka zostaje przy odpytywaniu co 30 s).
- Tryb stanowiska `priorytety_tryb_<S>` ∈ {`stary`, `stol`}. **`GET desk` oddaje `tryb`** i **w `stary` nie dopełnia
  stołu** (bez zapisów i bez blokady stanowiska; zwraca bieżące wiersze stołu, np. kafle startowe po „Przygotuj stoły”) —
  dopełnianie wyłącznie w `stol` (decyzja centrali 5.10 po znalezisku K6: przy deployu o 10:30 w trakcie zmiany appka nie
  może przejść na stół przed „Włącz stoły”, a `desk` w `stary` nie może kłaść kafli `kolejka` przed startem). Appka pokazuje
  ekran stołu tylko przy `tryb == "stol"`, przy `stary` dzisiejszą listę, i wykrywa przełączenie (w obie strony) przez
  `desk` w rytmie siatki. `postpone` w `stary` działa (do testów); ZAKOŃCZ w `stary` nie ma bramki. **Wyjątek: Lakiernia** (5.5) — zawsze `stary`, `desk`/`postpone` → 409
  `stanowisko_bez_stolu`.
- **Lista Lakierni** (ustalenie 15, 3.2): `GET /stations/painting/orders` i `/orders/since` (`all_ids`, `changed`) w
  kolejności grup wykończenia; pozostałe stanowiska bez zmian. Każda pozycja serializowana dla `painting` dostaje pole
  `grupa_wykonczenia: {rodzaj, typ_koloru, kolor, polysk}` (klucz z 3.2 p. 1, decyzja Konrada „jak w appce”; wartości
  znormalizowane, `polysk` tylko dla lakierowanych, `null` = brak; dla innych stanowisk
  pole `null`) — appka rysuje separator grupy z tego pola, nie z własnego klucza. Zestaw pól zmienia się w tym samym
  kroku co `priorytet` (K3), więc jedno podbicie `KSZTALT_ODPOWIEDZI_KOLEJKI` → 6 obejmuje oba. ETag listy bez zmian
  w budowie: kolejność zależy od rangi i pól wykończenia pozycji, a ich zmiana podbija `updated_at` (4.2).

### 6.4 Zakres dla sesji appki (`woodpower_prod_app`) — do kontraktu po P1

1. Ekran stanowiska = stół (1–2 kafle) + sekcja „Odłożone” + (Formatowanie, Pakowanie) sekcja „Niekompletne” z postępem
   i listą brakujących pozycji; bez listy kolejki. Licznik „w kolejce: 37” w nagłówku.
2. Kafel: jak dotychczasowa karta pozycji/zamówienia, plus gwiazdki, plakietka trasy/tagu, „poz. 2/5”. Przyciski:
   **Odłóż** (lewa) i **ZAKOŃCZ** (prawa); licznik sztuk jak dotąd.
3. Modal Odłóż: lista powodów, notatka przy „inne”; 409 `limit_odlozen` jako komunikat.
4. Połączenie SSE (`uni_sse`, token z `/realtime-token`), po sygnale `GET desk`; brak realtime → odpytywanie: 30 s przy
   pustym stole, 5 min przy pełnym; zawsze `GET desk` po własnym ZAKOŃCZ/Odłóż.
5. Kolejka offline jak dotąd; 409 `nie_na_stole` → komunikat i odświeżenie stołu (kafel zamknął inny tablet). (K5 → 16.9 Z36)
6. Stara appka bez tych zmian działa jak dziś do czasu przełączenia stanowiska na `stol` (bramka wersji). Przy jednym
   wdrożeniu (ustalenie 16) nowa appka trafia na tablety razem z CRM — stara appka to tylko zabezpieczenie dla tabletu,
   którego nie zaktualizowano.
6a. Stół bywa dłuższy niż K (5.1): lista kafli stołu przewijana, plakietki źródła „wysłane przez biuro” i „rozpoczęte
   przed startem” (`zrodlo` = `biuro` / `start`).
7. **Lakiernia bez stołu** (ustalenie 15): ekran Lakierni = dzisiejsza pełna lista `/stations/painting/orders`
   (pracownik wybiera sam), bez stołu, bez Odłóż, bez „w kolejce”; appka **nie woła** `desk`/`postpone` dla `painting`
   (wybór ekranu po kodzie stanowiska, nie po trybie). Kolejność pozycji = kolejność z odpowiedzi serwera (grupy
   wykończenia, 3.2) — appka jej nie przesortowuje domyślnie; separatory grup z pola `grupa_wykonczenia`. Odświeżanie
   listy jak dziś (ETag, 30 s); sygnał na `station:painting` może dodatkowo wywołać odświeżenie listy.
   **Tablet Krawędzi** (grupa `edges`+`painting`, `STATION_GROUPS`) pracuje na stałe w trybie mieszanym: dopóki Krawędzie
   są `stary` — dwie listy jak dziś; po przełączeniu Krawędzi na `stol` — ekran Krawędzi to stół (Teraz, Odłożone, Odłóż,
   bramka ZAKOŃCZ), a ekran Lakierni dalej lista po wykończeniu, ZAKOŃCZ bez bramki. Token realtime tabletu Krawędzi
   dalej obejmuje oba kanały (`station:edges`, `station:painting`). Stara appka na tablecie Krawędzi (wersja poniżej
   progu) — obie listy bez bramki (5.5).
   **Uwaga — stara appka sortuje sama.** Appka 1.7.3 układa listę Lakierni własnym komparatorem (`isPriority`, po
   terminie, potem `priority_rank` albo sortowanie „Partia (kolor i połysk)” z separatorami), a nie w kolejności
   odpowiedzi; porządek po wykończeniu z serwera widać od nowej appki — **przyjęte przez Konrada 5.10** (appka wychodzi
   razem z CRM, ustalenie 16; bez osobnego wydania). Ręczne sortowanie w nowej appce zostaje jako opcja.

## 7. Panel biura

### 7.1 Zakładka „Lista produkcyjna” (dotychczas „Lista produktów”)

- **Zmiana nazwy** zakładki (szablon `templates/panel/dashboard.html`, teksty w `products-tab-content.html`, testy UI).
- **Modal priorytetu** na karcie zamówienia (przycisk z gwiazdkami w nagłówku karty, zastępuje dzisiejszą gwiazdkę
  true/false): gwiazdki 0–5 (klik), szczebel i jego pozycja („trasa Śląsk, szczebel 1 z 11”), termin i tagi, ranga
  zamówienia, **gdzie leży**: stół/odłożone/kolejka na każdym stanowisku, które ma pozycję tego zamówienia, odłożenia
  z powodami, historia gwiazdek z `prod_priority_log` (K5 → 16.9 Z37). Gwiazdka pozycji znika. Przy każdym stanowisku, na którym
  zamówienie ma pozycje: **„Wyślij na stanowisko”** (5.7), a przy kaflu na stole — **„Zdejmij ze stołu”**.
- **Przycisk „Drabina priorytetów”** w nagłówku zakładki → modal z drabiną: szczeble gwiazdek stałe, tagi i trasy
  przeciągalne (strzałki ↑↓ jako zapas) (K5 → 16.9 Z38), licznik zamówień w produkcji na szczeblu, ostrzeżenie o datach (3.1), zapis
  `PUT /production/api/priorytety/drabina/kolejnosc`.
- **Kolejność kart** = ranga zamówienia (dziś termin) (K5 → 16.9 Z39). Termin zostaje jako kolumna i kolor. Plakietki na karcie: gwiazdki,
  trasa, tag, „Odłożone na …”. Hurtowy pasek: „Ustaw gwiazdki”.
- Martwe: `products-dragdrop.js`, `showEditPriorityModal`, `handleStarClick`, progi `getPriorityClass` — usunięte.

### 7.2 Inne miejsca

- **Logistyka:** kolumna „★” z wyborem 0–5 (ten sam komponent) (K5 → 16.9 Z40); przystanki w edytorze trasy pokazują gwiazdki.
- **Zakładka Stanowiska** (dziś niepodpięta w panelu — **podpinamy ją** jako widoczną zakładkę, decyzja Konrada 5.10,
  wariant A planu K4b): zamiast progów rangi — stół i odłożone każdego stanowiska (to samo, co widzi tablet, ze
  źródłem kafla) oraz pierwsze 15 kafli kolejki; „Zdejmij ze stołu” przy kaflu (5.7) (K5 → 16.9 Z41). **Lakiernia:** bez sekcji stołu i odłożeń; pierwsze 15 pozycji w kolejności listy Lakierni
  (3.2, ta sama funkcja co tablet) z nazwą grupy wykończenia.
- **Monitory hali:** stół + odłożone + „dalej w kolejce”, gwiazdki i plakietki (krok P3) (K5 → 16.9 Z42); pracownik odłożenia jako
  „Adam K.” (jak tablet). **Monitor Lakierni: lista
  zamiast stołu** — nigdy sekcji „TERAZ”/„Odłożone”; karty zamówień w kolejności pierwszego wystąpienia pozycji
  zamówienia na liście Lakierni (3.2), więc telewizor pokazuje tę samą kolejność co tablet.
- **Dashboard:** `high_priority_count` → zamówienia aktywne na szczeblach ★★★★, ★★★★★, „Po terminie” albo trasy.
- **Konfiguracja:** grupa „Terminy” (4.3) i grupa „Stół stanowisk”: K, jednostka, limit odłożeń, tryb per stanowisko,
  minimalna wersja appki, próg „Blisko terminu”; sekcja **„Start stołów”** (5.8): podgląd kafli rozpoczętych per
  stanowisko, „Przygotuj stoły”, „Włącz stoły” (admin). Wiersz Lakierni: tryb na stałe „lista (bez stołu)”, bez wyboru
  i bez K/jednostki/limitu (ustalenie 15; kod i tak traktuje ją jako `stary`, 5.5).

### 7.3 Uprawnienia

Gwiazdki, drabina, podgląd stołów i odłożeń, „Wyślij na stanowisko”, „Zdejmij ze stołu”, podgląd startu: `guard` jak
w Logistyce (login + moduł `production`) — biuro. Ustawienia (Konfiguracja), „Przygotuj stoły”, „Włącz stoły”:
`admin_required`. Tablet: token urządzenia + `X-Worker-Ids`.

## 8. Model danych i migracja

### 8.1 `prod_orders`

| Kolumna | Typ | Znaczenie |
|---|---|---|
| `priority_stars` | TINYINT NOT NULL DEFAULT 0 | gwiazdki 0–5 |
| `priority_stars_set_at`, `priority_stars_set_by` | DATETIME NULL, INT NULL | ostatnia zmiana |
| `priority_rank` | INT NULL, INDEX | ranga zamówienia (pamięć podręczna, 4.2) |
| `priority_rung` | INT NULL | pozycja szczebla (pamięć podręczna) |

### 8.2 `prod_priority_rungs` (szczeble), model `PriorityRung`

| Kolumna | Typ | Uwagi |
|---|---|---|
| `id` | INT PK | |
| `kind` | ENUM('stars','tag','route') NOT NULL | |
| `stars` | TINYINT NULL | 0–5 dla `stars` |
| `tag` | VARCHAR(32) NULL | `po_terminie`, `blisko_terminu`, `rozpoczete` |
| `route_id` | INT NULL UNIQUE, FK `prod_routes.id` ON DELETE CASCADE | |
| `position` | INT NOT NULL | renumeracja 1..n przy każdym zapisie |
| `created_at`, `updated_at`, `updated_by` | | |
| UNIQUE | (`kind`,`stars`), (`kind`,`tag`) | |

Seed migracją (`INSERT IGNORE`): 9 wierszy w kolejności z 3.1 (6 gwiazdek, 3 tagi).

### 8.3 `prod_priority_log`, model `PriorityLog`

| Kolumna | Typ | Uwagi |
|---|---|---|
| `id` | INT PK | |
| `action` | ENUM('gwiazdki','szczebel','odlozenie','odlozenie_zamkniete','ustawienia','przeliczenie','wyslanie','zdjecie','start_stolow') | trzy ostatnie: 5.7, 5.8 (migracja K3; tabela nowa w tym samym wdrożeniu, więc zmiana ENUM nie dotyka starego kodu) |
| `order_id` | INT NULL, FK `prod_orders.id` ON DELETE CASCADE, INDEX | |
| `product_id` | INT NULL | kafel-pozycja |
| `route_id` | INT NULL, INDEX | szczebel |
| `station_code` | VARCHAR(32) NULL, INDEX | |
| `old_value`, `new_value` | VARCHAR(64) | |
| `reason`, `note` | VARCHAR(32), VARCHAR(255) | powód odłożenia |
| `user_id`, `worker_id`, `device_id` | INT NULL | |
| `created_at` | DATETIME NOT NULL, INDEX | |

### 8.4 `prod_station_desk` (stół), model `StationDesk`

| Kolumna | Typ | Uwagi |
|---|---|---|
| `id` | INT PK | |
| `station_code` | VARCHAR(32) NOT NULL, INDEX | |
| `order_id` | INT NOT NULL, FK `prod_orders.id` ON DELETE CASCADE | |
| `product_id` | INT NULL, FK `prod_products.id` ON DELETE CASCADE | NULL dla kafla-zamówienia |
| `unit_key` | VARCHAR(24) NOT NULL | `p:<product_id>` albo `o:<order_id>`; UNIQUE (`station_code`,`unit_key`) |
| `pulled_at` | DATETIME NOT NULL | |
| `postponed_at` | DATETIME NULL | NULL = na stole; NOT NULL = odłożony |
| `postpone_reason`, `postpone_note` | VARCHAR(32), VARCHAR(255) | |
| `postponed_by_worker_id`, `postponed_device_id` | INT NULL | |
| `zrodlo` | VARCHAR(16) NOT NULL DEFAULT 'kolejka' | `kolejka`, `dorobka`, `biuro`, `start` (5.1); migracja K3 |
| `sent_by_user_id` | INT NULL | kto wysłał/przygotował (`biuro`, `start`); migracja K3 |

Wiersz znika razem z kaflem (ZAKOŃCZ, zdjęcie — 5.1). FK CASCADE sprząta po usunięciu pozycji/zamówienia.

### 8.5 `prod_products`

`priority_rank` — pamięć podręczna (4.1), doróbki 0. `is_priority` — pochodna. `priority_manual_override` — martwa od P1
(nic nie ustawia True; `utrwal()` zeruje napotkane), kolumna i metody `lock_priority`/`unlock_priority`/`is_priority_locked`
usuwane w P4.

### 8.6 `prod_config`

| Klucz | Typ | Domyślnie | Znaczenie |
|---|---|---|---|
| `priorytety_tryb_<S>` | string | `stary` | `stary` / `stol` (bramka 5.5, 7 kodów stanowisk); `priorytety_tryb_painting` = `stary` **na stałe** (ustalenie 15) — wiersz zostaje z migracji K1, bramka i `desk` go dla Lakierni ignorują (`STANOWISKA_BEZ_STOLU`, 5.5) |
| `priorytety_stol_<S>` | integer | 2 | miejsca na stole K |
| `priorytety_jednostka_<S>` | string | `pozycja`; `formatting`, `packaging`: `zamowienie` | jednostka kafla |
| `priorytety_limit_odlozen_<S>` | integer | 10 | |
| `priorytety_stol_<S>` (wiersz blokady) | — | — | blokada pobierania (5.2); osobny klucz `priorytety_blokada_<S>` |
| `priorytety_blisko_terminu_dni` | integer | 3 | dni robocze (decyzja 5.10; w symulacji 5 dawało mniej „tonięcia” pilnych — do zmiany w Konfiguracji bez wdrożenia) |
| `priorytety_min_app_version_code` | integer | 0 | bramka starej appki (0 = brak bramki) (K5 → 16.9 Z43) |
| `DEADLINE_DAY_TYPE` | string | `robocze` | 4.3 |

**Porządek listy Lakierni bez nowego klucza.** Kolejność listy zależy od **kodu stanowiska**: stała
`STANOWISKA_BEZ_STOLU = ('painting',)` w `priorytety/stale.py` (K5 → 16.9 Z44) wyznacza i porządek po grupach wykończenia (3.2 „Lista
Lakierni”), i brak stołu (5.5). Żadnego klucza `prod_config` w rodzaju „porządek listy”: decyzja jest stała (ustalenie
15), a przełącznik w Konfiguracji byłby drugą drogą do tego samego. Zmiana decyzji = zmiana kodu. Klucze
`priorytety_stol_painting`, `priorytety_jednostka_painting`, `priorytety_limit_odlozen_painting` zostają z migracji K1
(37 kluczy `priorytety_*` bez zmian), ale poza wyświetleniem w ustawieniach nic ich nie używa.

### 8.7 Migracja `2026-10-XX-priorytety-produkcji.sql`

*(K5 → 16.9 Z45)*

Idempotentna, wzór `2026-10-02-logistyka-niedostarczone-na-trasie.sql`: `ADD COLUMN` przez `information_schema` +
`PREPARE/EXECUTE`, `CREATE TABLE IF NOT EXISTS`, `INSERT IGNORE` (szczeble, wiersze `prod_config`). Żadnych zmian ENUM
na istniejących tabelach → stary kod w oknie wdrożenia niczego nie zobaczy. Sprawdzić na kontenerze `db` i na kopii
produkcji.

### 8.8 Usunięcia (P4)

`prod_priority_config` (`ProductionPriorityConfig`, `PriorityConfigCache`), `prod_products.priority_manual_override`,
martwe klucze (`PRIORITY_RECALC_INTERVAL_HOURS`, `PRIORITY_ALGORITHM_VERSION`, `STATION_*_PRIORITY_SORT`), martwe końcówki
(9.5), `REFRESH_INTERVAL_SECONDS` po wycofaniu starej appki.

## 9. Umiejscowienie kodu

### 9.1 Pakiet `modules/production/priorytety/` (wzór: `modules/production/logistics/`)

```
priorytety/
├── __init__.py            # blueprint priorytety_panel → /production/api/priorytety
├── models.py              # PriorityRung, PriorityLog, StationDesk
├── stale.py               # STATUSY_PRODUKCJI, TAGI, POWODY_ODLOZENIA, JEDNOSTKI, TRYBY, domyślne K/limit
├── services/
│   ├── kolejka.py         # policz(), utrwal(), kandydaci_stanowiska(S) (3.2 dla kafli)
│   ├── drabina.py         # szczeble(), zapewnij_szczebel_trasy(), przesun(), uzupelnij(), miejsce_domyslne()
│   ├── gwiazdki.py        # ustaw(order_ids, gwiazdki, user_id)
│   ├── stol.py            # dopelnij(S) (5.2), odloz(...), zdejmij_kafel(...) (5.1), bramka_zakoncz(...) (5.5),
│   │                      # wyslij(S, order_id, user), zdejmij_przez_biuro(S, unit_key, user) (5.7),
│   │                      # rozpoczete_na_stanowisku(S), przygotuj_start(S, user) (5.8)
│   ├── sygnaly.py         # zaplanuj(S...) / wyslij() — kanały station:<kod>, wzór print_queue_service
│   └── ustawienia.py      # tryb(S), miejsca(S), jednostka(S), limit(S), prog_blisko(), min_app_version()
├── routers/panel_api.py   # drabina, gwiazdki, stoły, odłożenia, ustawienia, przelicz
├── templates/priorytety/  # modal priorytetu, modal drabiny (wstrzykiwane do Listy produkcyjnej)    ← (K5 → 16.9 Z46)
└── static/{js,css}/priorytety.*
```
Końcówki mobilne (`desk`, `postpone`, `realtime-token`) w `routers/mobile_api.py` obok dzisiejszych, logika w `stol.py`.
`priority_service.py` zostaje do P4 jako cienka warstwa zgodności (`recalculate_all_priorities()` → `kolejka.utrwal()`).

### 9.2 Kontrakty funkcji

- `kolejka.policz(...)` — czysta funkcja na strukturach; testowana tabelami przypadków (3.3).
- `kolejka.utrwal()` — własna sesja; blokady zamówień rosnąco po id, potem pozycje (4.2); jedno ponowienie po 1213.
- `kolejka.kandydaci_stanowiska(S, pozycje, statusy_zamowien)` — czysta (K5 → 16.9 Z47): pozycje w statusie S poza stołem i odłożeniami →
  kolejność kafli (3.2, z tagiem „Rozpoczęte” liczonym ze statusów i grupowaniem po materiale dla jednostki `pozycja`;
  dla jednostki `zamowienie` dzieli na kompletne i niekompletne, 5.6).
- `stol.dopelnij(S)` — blokada `priorytety_blokada_<S>` → kandydaci odczytem bieżącym → INSERT → commit przez wołającego
  (router) → `sygnaly.zaplanuj(S)`; ponowienie po 1213 w routerze. (K5 → 16.9 Z48)
- `stol.odloz(order_id, product_id|None, S, powod, notatka, worker, device)` — pod blokadą zamówienia (handler ZAKOŃCZ
  już ją ma; `postpone` bierze `zablokuj_zamowienie_pozycji` tak samo), sprawdza limit odczytem bieżącym stołu stanowiska, (K5 → 16.9 Z49)
  ustawia `postponed_*`, log.
- `stol.zdejmij_kafel(pozycja|zamowienie, S)` — DELETE wiersza stołu; woła ją `complete_task`-owy pisarz (K5 → 16.9 Z50) (handler ZAKOŃCZ
  po `mark_order_complete`), hurt, wstrzymanie, Base., doróbka — w tej samej transakcji, pod już trzymaną blokadą zamówienia.
- `stol.bramka_zakoncz(item, S, device)` — tryb `stary`/wersja appki → przepuść (K5 → 16.9 Z51); inaczej kafel na stole albo odłożony →
  przepuść; inaczej 409 `nie_na_stole`.
- `stol.wyslij(S, order_id, user_id)`, `stol.zdejmij_przez_biuro(S, unit_key, user_id)` — 5.7; kolejność blokad jak
  `dopelnij`; commit i sygnał w routerze panelu.
- `stol.rozpoczete_na_stanowisku(S)` (odczyt, podgląd startu) i `stol.przygotuj_start(S, user_id)` (zapis wierszy
  `zrodlo='start'` pod blokadą stołu `S`) — 5.8.
- `drabina.przesun`, `gwiazdki.ustaw` — jak w wersji 1: drabina pod blokadą tras; gwiazdki `commit` → `FOR UPDATE`
  zamówień rosnąco → zapis → `commit` → `utrwal()`.

### 9.3 Wyzwalacze `utrwal()`

| Zdarzenie | Gdzie |
|---|---|
| zmiana gwiazdek, przesunięcie szczebla | `panel_api` po commicie |
| trasa: utworzenie, usunięcie, przystanek +/−, zatwierdzenie, cofnięcie, odhaczenie, załadunek, „Zostaje” | `trasy_api`/`dostawa_api` po commicie (`utrwal_po_commicie()`) |
| zmiana sposobu dostawy | `panel_api.delivery_method` po commicie |
| import z Base. | `sync_service` (`:933`, `:3033`) (K5 → 16.9 Z52) |
| zmiany z Base., hurtowa zmiana statusu | `products_api` po commicie |
| **codziennie o północy i co godzinę w cronie** (K5 → 16.9 Z53) | faza `priorytety_utrwalone` w `cron_api.cron` — tagi „Po terminie”/„Blisko terminu” zmieniają się z datą, bez zdarzenia |
| „Przelicz teraz” | `panel_api.przelicz` (admin) |

Doróbka: ranga 0 przy utworzeniu, bez `utrwal()` (API mobilne nie commituje w handlerze).

### 9.4 Współbieżność (zgodnie z CLAUDE.md „Trasy logistyki — jeden piszący naraz”)

- Szczeble: zapis pod blokadą tras, potem `FOR UPDATE` szczebli.
- Gwiazdki: `commit` → `FOR UPDATE` zamówień rosnąco → zapis → `commit`. Bez blokady tras.
- `utrwal()`: zamówienia `FOR UPDATE` rosnąco → pozycje rosnąco → zapisy zmienionych (K5 → 16.9 Z54); nie bierze blokady tras ani
  blokady stołu. Jedno ponowienie po 1213.
- Stół: `dopelnij` w osobnym żądaniu, blokada `priorytety_blokada_<S>` → odczyt bieżący kandydatów (`FOR SHARE`) → INSERT.
  Nie bierze blokad zamówień (czyta `FOR SHARE` pozycje wielu zamówień (K5 → 16.9 Z55) — ZAKOŃCZ innego zamówienia trzymający X na
  swoich pozycjach nie czeka na blokadę stołu, bo jej nie bierze, więc cyklu nie ma). Rzadkie 1213 na gapach indeksu
  stołu — ponowienie raz.
- „Wyślij”, „Zdejmij”, „Przygotuj stoły” (5.7, 5.8): jak `dopelnij` — blokada `priorytety_blokada_<S>` → odczyt
  bieżący (`FOR SHARE`) → zapis wierszy stołu; bez blokad X zamówień; „Przygotuj” stanowisko po stanowisku, osobne
  transakcje.
- ZAKOŃCZ/Odłóż: kolejność dzisiejsza (zamówienie → pozycje), DELETE/UPDATE wiersza stołu własnego kafla w tej samej
  transakcji (FK do zamówienia już zablokowanego X przez ten wątek — bez nowej kolejności). Nie dotykają blokady stołu.
- Sygnały: zawsze **po** commicie (dekorator / router), nigdy w transakcji; `publish` nie rzuca (jak dla druku).

### 9.5 Co znika albo zmienia znaczenie

| Miejsce | Zmiana |
|---|---|
| `services/priority_service.py` | P1: warstwa zgodności → `kolejka.utrwal`; P4: usunięcie. `test_priority_statusy_krawedzi.py` traci przedmiot — jedna lista statusów w `priorytety/stale.py`. |
| `products_api.py` końcówki `update-priority`, `products/<id>/priority`, `set-manual-priority`, `recalculate-all-priorities`, `priority-statistics`, `set-priority`, `bulk-action update_priority` | P1: usunięte. |
| `products_api.py` listy/eksporty | sort po `priority_rank` bez zmian (ranga zamówienia×100+sekwencja daje tę samą kolejność); filtr `priority_range` → gwiazdki (K5 → 16.9 Z56). |
| `models.py` `lock_priority`/`unlock_priority`/`is_priority_locked`, blok `:714-719` w `complete_task` | P1: blok znika, metody puste; P4: usunięcie. |
| `rework_service.py:302` | `rework.priority_rank = 0`. |
| `sync_service.py` | `_calculate_deadline_date` czyta `DEADLINE_DAY_TYPE`; wywołania przeliczenia → `kolejka.utrwal()` (K5 → 16.9 Z57). |
| `mobile_api.py` | nowe `desk`, `postpone`, `realtime-token`; w `complete`/`quantity`: `stol.bramka_zakoncz`, `stol.zdejmij_kafel`, `sygnaly.zaplanuj` (K5 → 16.9 Z58). |
| `mobile_api_service.with_idempotency` | po commicie wysyła także sygnały stanowisk (obok sygnału druku i dopychacza Base.) (K5 → 16.9 Z59). |
| `mobile_api_service.serialize_order` | `priorytet`; `KSZTALT` → 6. |
| `config_api.py`, `config-tab-content.html` | `DEADLINE_DAY_TYPE`, grupa „Stół stanowisk”; martwe klucze znikają. |
| `stations_api.py`, `dashboard_api.py`, `monitors.py`, `routers/stations/__init__.py` | czytelnicy (7.2). |
| `products-module.js`, `products-dragdrop.js`, `products-tab-content.html`, `products-tab.css`, `dashboard.html` | Lista produkcyjna, modale (7.1). |
| `logistics.js`, `logistics-routes.js` | gwiazdki (7.2). |
| `routes.utworz`, `trasy_api.py`, `panel_api.py` (logistyka), `cron_api.cron` | szczebel trasy, `utrwal_po_commicie()`, faza crona. |
| `realtime_service.py` | `publish_station_signal(kod)`; token dla tabletów. |
| `tests/test_priorytety_kolejnosc_zapisow.py` | na `kolejka.utrwal` (nowa kolejność blokad); przeciąganie znika. |

## 10. Obsługa błędów

| Sytuacja | Zachowanie |
|---|---|
| ZAKOŃCZ/licznik kafla poza stołem w trybie `stol` (nowa appka) (K5 → 16.9 Z60) | 409 `nie_na_stole`; w `BLEDY_DO_PONOWIENIA` (akcja z kolejki offline przejdzie, gdy kafel wejdzie na stół — albo appka ją porzuci po odświeżeniu stołu) |
| Odłóż przy limicie | 409 `limit_odlozen` z komunikatem po polsku |
| Odłóż kafla, który nie leży na stole (zamknął go inny tablet) | 409 `nie_na_stole` |
| zły powód, `inne` bez notatki | 400 `powod_niepoprawny` |
| gwiazdki poza 0–5, > `LIMIT_HURTU` | 400 |
| przesunięcie szczebla gwiazdek / nieznany / trasa nieaktywna | 400 `szczebel_staly` / 404 / 409 `trasa_nieaktywna` |
| ustawienia: K poza 1–5, limit poza 1–50, jednostka spoza listy, nieznane stanowisko (K5 → 16.9 Z61) | 400 |
| `utrwal()` padło dwa razy | log ERROR; zapis gwiazdek/szczebla zostaje; panel `{"przeliczenie":"nieudane"}`; cron nadrobi |
| `dopelnij` 1213 dwa razy | 500 z rollbackiem; tablet ponowi po 30 s (K5 → 16.9 Z62) |
| realtime wyłączony / broker milczy | `publish` zwraca False bez wyjątku; tablety wracają do odpytywania (30 s / 5 min) |
| stara appka w trybie `stol` | zachowanie `stary` (5.5) |
| „Wyślij”: brak pozycji w statusie stanowiska / Lakiernia | 409 `brak_na_stanowisku` / `stanowisko_bez_stolu` |
| „Zdejmij”: kafla nie ma na stole | 404 `brak_kafla` |
| `PUT /ustawienia`: `stanowiska.painting.tryb = stol` | 400 `stanowisko_bez_stolu` |

## 11. Kroki wdrożenia i kompatybilność

| Krok | Zawartość | Warunek |
|---|---|---|
| **P1 Serwis, drabina, gwiazdki, stół, panel** | migracja (8), pakiet `priorytety`, `utrwal()` w miejsce starego algorytmu, terminy (4.3), Lista produkcyjna z modalami (7.1), gwiazdki w Logistyce, czytelnicy rangi, końcówki `desk`/`postpone`/`realtime-token`, sygnały, wszystkie stanowiska w trybie `stary` | logistyka etapy 1–4 wdrożone; Centrifugo z namespace `station` (jest w konfiguracji) |
| **P2 Kontrakt i appka** | dokument kontraktu (12), sesja appki: stół, Odłóż, SSE, odpytywanie awaryjne | P1 na produkcji |
| **P3 Przełączenie stanowisk** | `priorytety_min_app_version_code` = kod nowej appki; `priorytety_tryb_<S>` → `stol` stanowisko po stanowisku: Sklejanie → Formatowanie → Składanie → Wycinanie → Krawędzie → Pakowanie, po 2 dniach obserwacji każde; **Lakiernia nie przechodzi** (zostaje `stary` z listą po wykończeniu, ustalenie 15); monitory hali | P2 na tabletach |
| **P4 Sprzątanie** | DROP `prod_priority_config`, `priority_manual_override`; `priority_service.py`, puste metody, martwy JS, `REFRESH_INTERVAL_SECONDS` | 2–3 tygodnie P3 bez wycofania |

**Jedno wdrożenie (ustalenie 16, Konrad 5.10) — zastępuje kolejność P1 → P2 → P3 z tabeli wyżej.** P1, P2 i P3
wchodzą jednym oknem razem z logistyką etapów 1–4: kontrakt appki i appka (P2) powstają **przed** wdrożeniem (po K3,
równolegle z panelem i przeglądem); w oknie wdrożenia: scalenie logistyki i priorytetów do `main`, deploy, ręczny cron
(niżej), nowa appka na tabletach, „Przygotuj stoły” po zakończeniu zmiany, „Włącz stoły” dla sześciu stanowisk przed
następną zmianą i „Rozpoczęte” na szczyt drabiny (5.8). Lakiernia zostaje `stary`. P4 bez zmian (2–3 tygodnie po starcie).
Wycofanie stołów — `priorytety_tryb_<S>` → `stary` w Konfiguracji, bez wdrożenia; wycofanie kodu — razem z logistyką.

**Przed P1 — symulacja na danych produkcyjnych** (decyzja Konrada 4.10): `scripts/symulacja_priorytetow.py` liczy nową
kolejkę każdego stanowiska na prawdziwej bazie bez Flaska i bez zapisu (tylko SELECT, kolumny i tabele wykrywa, działa
na produkcji sprzed logistyki). Raport Markdown + JSON: dzisiejsza kolejka kontra nowa, tagi, stół K, niekompletne na
Formatowaniu/Pakowaniu, historia omijania pilniejszych pozycji i rozrzut pozycji zamówienia przed stanowiskami
zamówieniowymi (obawa z sekcji 5.6), liczba zdarzeń dziennie do zwymiarowania sygnałów. Uruchomienie i opcje w docstringu
skryptu; test `tests/test_symulacja_priorytetow.py`. Wynik czytamy przed planem P1 i na jego podstawie ustawiamy parametry
z sekcji 13 (K, limit odłożeń, próg „Blisko terminu”, miejsce tagu „Rozpoczęte”).

**Po wdrożeniu P1 uruchom raz ręcznie** `scripts/cron_endpoint.sh POST /production/api/logistics/cron` (K5 → 16.9 Z63) (po restarcie):
faza `priorytety_utrwalone` nada rangi nowym algorytmem i dopisze szczeble istniejących tras. Wpis do CLAUDE.md razem z P1.

**Okno wdrożenia P1:** nowe kolumny i tabele bez zmian ENUM → stary worker niczego nie rzuci; może raz przeliczyć rangi
starym algorytmem po synchronizacji — cron nadpisze. Stara appka ignoruje dodatkowe pola.

**Wycofanie.** P1: cofnięcie kodu; kolumny i tabele zostają; stary algorytm przelicza rangi przy następnej synchronizacji;
gwiazdki zostają na przyszłość. P2: appkę można cofnąć niezależnie. P3: `priorytety_tryb_<S>` → `stary` w Konfiguracji,
bez zmiany kodu; stół i odłożenia przestają być egzekwowane, appka nowa dalej pokazuje stół (działa) (K5 → 16.9 Z64). P4: migracja
przywracająca przed restartem.

## 12. Kontrakt dla sesji appki (powstaje po P1)

*(K5 → 16.9 Z65)*

Osobny plik `docs/api-mobile-priorytety.md` w stylu `docs/api-mobile-krawedzie-lakiernia.md`: każde twierdzenie
z odnośnikiem do pliku i linii na gałęzi, „stan przed” i „stan po”, tabela końcówek (bez zmian / nowe / zmienione),
pełne przykłady JSON `desk`, `postpone`, `realtime-token`, kody 409, zachowanie przy wyłączonym realtime, zachowanie
starej appki, kolejka offline, lista ekranów do zmiany (6.4). Sesja appki pracuje wyłącznie z tego dokumentu.

## 13. Testy i parametry do potwierdzenia

**pytest na SQLite:** `policz()` tabelami (3.3; trasa decyduje mimo ★★★★★; tagi; termin jako rozjemca; doróbki 0);
`kandydaci_stanowiska` (grupowanie po materiale z przykładu Konrada; grupy po najbliższym terminie; „Rozpoczęte” na żywo
i przed grupowaniem — przykład X/Y z 5.6; pozycje omijające Formatowanie; jednostka `zamowienie`: kompletne na stół,
niekompletne osobno z listą brakujących, ostatnia pozycja czyni zamówienie kompletnym); drabina (seed 9 szczebli, miejsce domyślne, przesunięcie, tagi ruchome, gwiazdki stałe,
kaskada, ukrycie, samonaprawa); stół (dopełnienie do K, doróbka ponad K, pakowanie bez sposobu (K5 → 16.9 Z66), ZAKOŃCZ zdejmuje kafel,
odłożony nie jest pobierany ponownie, limit 409, `nie_na_stole`, bramka wersji appki, tryb `stary` bez bramki, zdjęcie
kafla przez wstrzymanie/Base./doróbkę; Lakiernia: bramka zawsze otwarta mimo `stol` w ustawieniach, `desk`/`postpone`
409 `stanowisko_bez_stolu`); lista Lakierni (grupy wykończenia, kolejność grup po najpilniejszej pozycji, doróbki
pierwsze, cała grupa w ciągu, inne stanowiska bez zmian, `grupa_wykonczenia`, ETag/`KSZTALT`); sygnały (planowanie w `g`, wysyłka po commicie, brak przy rollbacku, kanał
następnego stanowiska, `publish` nie rzuca); terminy (`DEADLINE_DAY_TYPE`, brak przeliczania wstecz); `utrwal()`
(kolejność blokad zamówienia→pozycje, zapis tylko zmienionych, 1213 raz); gwiazdki (hurt, `LIMIT_HURTU`, `guard`, log);
UI (Lista produkcyjna, modale, brak `products-dragdrop.js`). **MySQL:** migracja ×2; wyścigi: dwa `desk` naraz, (K5 → 16.9 Z67)
`desk` ↔ ZAKOŃCZ innego zamówienia, gwiazdki ↔ ZAKOŃCZ, przesunięcie szczebla ↔ przystanek, `utrwal()` ↔ Dostawa.
Kryterium: zero 1213 bez ponowienia, zero kafli zdublowanych na stole.

**Parametry do potwierdzenia przez Konrada:**

| # | Parametr | Propozycja |
|---|---|---|
| P-1 | Jednostka kafla per stanowisko | pozycja: Wycinanie, Składanie, Sklejanie, Krawędzie; zamówienie: Formatowanie, Pakowanie (jak dziś w appce). **Lakiernia: nie dotyczy** — bez stołu, lista pozycji (ustalenie 15, Konrad 5.10) |
| P-2 | Miejsca na stole K | 2 wszędzie; Pakowanie 2. **Lakiernia: nie dotyczy** (bez stołu, ustalenie 15) |
| P-3 | Limit odłożeń na stanowisko | 10 |
| P-4 | Próg „Blisko terminu” | **3 dni robocze** (Konrad 5.10), konfigurowalny |
| P-5 | Kolejność grup materiału w szczeblu | grupa = (gatunek, klasa, grubość) po najbliższym terminie w grupie; w grupie termin przed długością (Konrad 5.10) |
| P-6 | Zakres Odłóż | kafel (pozycja na pozycyjnych, zamówienie na zamówieniowych) |
| P-7 | Odpytywanie awaryjne nowej appki | 30 s przy pustym stole, 5 min przy pełnym |
| P-8 | Domyślne miejsce tagów na drabinie po migracji | ★★★★★, Po terminie, ★★★★, **Blisko terminu, Rozpoczęte**, ★★★, ★★, ★, bez (Konrad 5.10) |
| P-11 | Przejście na stoły | wszystkie stanowiska poza Lakiernią naraz, ze startem z kafli rozpoczętych (5.8), „Rozpoczęte” na szczycie drabiny na start (Konrad 5.10) |
| P-13 | Kafle startowe, doróbki | start tylko z licznika > 0 (21 kafli na kopii danych); doróbki na początku kolejki w ramach K (Konrad 5.10, po bramce K3) |
| P-14 | Pakowanie bez sposobu dostawy | dozwolone (Konrad 5.10) — logistyka 4.6 (`f07b21ec`) + scalenie do priorytetów (5.1) |
| P-12 | „Wyślij na stanowisko” | biuro (`guard`), ponad K, na początek stołu, tylko pozycje w statusie stanowiska; odłożony wraca na stół (Konrad 5.10, 5.7) |
| P-9 | Sekcja „Niekompletne” na Formatowaniu i Pakowaniu | do K zamówień, z postępem i listą brakujących pozycji; ZAKOŃCZ pozycji dozwolony |
| P-10 | Lista Lakierni | grupa = (rodzaj, kolor, połysk) — pola potwierdzone (Konrad 5.10) (K5 → 16.9 Z68); grupy po najpilniejszej pozycji, w grupie ranga, doróbki pierwsze, bez limitu w grupie (3.2) — **do potwierdzenia przy bramce K3** |

## 14. Poza zakresem / na później

- Harmonogramowanie według czasów operacji (APS); obiecywanie terminów klientom.
- Przydział kafli do konkretnych pracowników (stół jest wspólny dla stanowiska — decyzja Konrada 4.10).
- Raport odłożeń: udział odłożeń w ZAKOŃCZ per stanowisko i powód, czas leżenia — po zebraniu logu z P3.
- Szczeble innych kategorii na drabinie (np. kanał sprzedaży) — `kind` jest na to gotowy.
- Grupowanie po materiale w blokach po N zamówień szczebla — **odrzucone po symulacji 5.10** (przezbrojenia wracały
  do dzisiejszych 45; cały zysk grupowania przepadał). Nie wracać bez nowych danych.
- Sprzątanie duplikatów map stanowisko→status poza `station_catalog` — przy okazji P3, jeśli nie rozdmucha kroku.
- Zdjęcie `REFRESH_INTERVAL_SECONDS` i listy `/orders` dla tabletów po wycofaniu starej appki.

## 15. Mapa dotkniętych miejsc

- **Nowe:** `modules/production/priorytety/**`, `migrations/2026-10-XX-priorytety-produkcji.sql`, szablony modali (K5 → 16.9 Z69)
  i `priorytety.js/.css`, `docs/api-mobile-priorytety.md` (P2), testy `tests/test_priorytety_*.py`.
- **Zmienione:** `models.py` (`ProductionOrder` kolumny, `complete_task`, puste `lock_priority`), `rework_service.py`,
  `sync_service.py` (terminy, przeliczenie), `mobile_api_service.py` (`with_idempotency`, `serialize_order`),
  `routers/mobile_api.py`, `routers/api/products_api.py`, `stations_api.py`, `dashboard_api.py`, `config_api.py`,
  `routers/stations/monitors.py`, `routers/stations/__init__.py`, `services/realtime_service.py`,
  `logistics/services/routes.py`, `logistics/routers/trasy_api.py`, `dostawa_api.py`, `panel_api.py`, `cron_api.py`,
  `logistics/static/js/logistics.js`, `logistics-routes.js`, `templates/panel/dashboard.html`,
  `templates/components/products-tab-content.html`, `stations-tab-content.html`, `config-tab-content.html`,
  `static/js/modules/products-module.js`, `static/css/products-tab.css`, `app.py`, `CLAUDE.md`,
  `tests/test_priorytety_kolejnosc_zapisow.py`, `tests/test_priority_statusy_krawedzi.py`.
- **Usunięte (P1):** `static/js/modules/products-dragdrop.js`, martwe końcówki priorytetów w `products_api.py`.
- **Usunięte (P4):** `services/priority_service.py`, `ProductionPriorityConfig`, `PriorityConfigCache`,
  `priority_manual_override`.

## 16. Doprecyzowania z realizacji (K1–K5)

Sekcja zbiera doprecyzowania z planów i raportów kroków K1–K4b, kart naprawczych (K3-poprawka-1, K3-poprawka-2,
K4-poprawka-1), karty Lakierni i scalenia logistyki 4.6 — w wersji, która jest w kodzie. Tam, gdzie sekcja 16 i
wcześniejsza treść specu (1–15) się różnią, obowiązuje sekcja 16. W nawiasach stoi źródło punktu i ewentualna zmiana
wobec planu; reguły po stronie appki opisuje kontrakt `docs/api-mobile-priorytety.md`.

### 16.1 K1 — fundament rangi

Punkty K1.1–K1.21 odpowiadają kolejno 21 doprecyzowaniom planu K1; K1.22–K1.36 pochodzą z raportu K1 i z K1-poprawki-1
(Task 0 kroku K3).

- **K1.1** Termin zamówienia to najmniejszy `deadline_date` pozycji AKTYWNYCH (w `stale.STATUSY_PRODUKCJI`); pozycja
  spakowana, wstrzymana ani anulowana terminu nie wyznacza (`kolejka.termin_zamowienia`). Obowiązuje 4.2, nie
  „niezanulowanych” z 4.1 i 3.2 p. 3.
- **K1.2** Tag „Rozpoczęte” i kompletność zamówienia liczą się na pozycjach w statusach produkcji i po spakowaniu
  (`stale.ETAP_STATUSU`); `anulowane` i `wstrzymane` są pomijane (`stale.STATUSY_POZA_KOLEJKA`), więc wstrzymana
  pozycja nie blokuje kompletności.
- **K1.3** `kolejka.kandydaci_stanowiska` ma sześć parametrów: `stanowisko`, `pozycje`, `statusy_zamowien`,
  `szczebel_rozpoczete=None`, `jednostka=None`, `omijajace=None`. `statusy_zamowien` to
  `{order_id: ((product_id, status), …)}` dla WSZYSTKICH pozycji zamówienia; `szczebel_rozpoczete` to pozycja szczebla
  tagu „Rozpoczęte” wśród szczebli widocznych (`drabina.pozycja_tagu('rozpoczete')`, `None` = tag nie podnosi);
  `jednostka` to ustawienie stanowiska (`None` = `zamowienie` na Formatowaniu i Pakowaniu); `omijajace` — K3.36. (9.2
  podaje trzy parametry; rozszerzone w K1 i K3-poprawce-1)
- **K1.4** Jednostka `zamowienie`: zamówienia porządkuje klucz rangi (szczebel, gwiazdki malejąco, termin, numer), w
  którym szczebel pochodzi z kolumny `priority_rung`, a zamówieniu rozpoczętemu spoza trasy roboczej albo
  zatwierdzonej podnosi go na żywo szczebel tagu „Rozpoczęte”, jeśli stoi wyżej (`kolejka._szczebel_na_zywo`) — nie
  goła kolumna `priority_rank`. Zamówienie z doróbką czekającą na tym stanowisku idzie pierwsze, po `created_at`
  doróbki. (raport K1, rozstrz. 7)
- **K1.5** Trasa robocza albo zatwierdzona z zamówieniami w produkcji, ale bez wiersza szczebla: `policz()` liczy ją
  jako szczebel wirtualny w miejscu domyślnym (3.1), rosnąco po id trasy, z ostrzeżeniem w logu; brakujący szczebel
  stały liczy na końcu drabiny w kolejności `stale.DRABINA_DOMYSLNA`. Wiersze dopisuje `drabina.uzupelnij()` (cron,
  samonaprawa `GET /drabina`); do tego czasu `priority_rung` (liczy szczeble wirtualne) i `drabina.pozycja_tagu`
  (tylko wiersze) mogą się różnić o liczbę szczebli wirtualnych stojących nad tagiem — po jednym na każdą trasę bez
  wiersza; przy braku wiersza tagu `pozycja_tagu` zwraca `None` (tag nie podnosi).
- **K1.6** `utrwal()` zapisuje rangi tylko zamówieniom aktywnym i ich pozycjom w statusach produkcji; pozycje
  spakowane, anulowane i wstrzymane zachowują dawną rangę. Zamówienie aktywne bez `deadline_date` ma termin „brak” i w
  swoim szczeblu stoi za zamówieniami o tej samej liczbie gwiazdek, ale przed tymi o mniejszej (gwiazdki są w kluczu
  przed terminem — doprecyzowanie skrótu z 4.5); nie dostaje tagów terminowych (tag „Rozpoczęte” działa także bez
  terminu).
- **K1.7** `utrwal()` zeruje `priority_manual_override` napotkane na pozycjach aktywnych i podbija `updated_at`
  pozycji przy każdej zmianie (ranga, `is_priority`, wyzerowanie nadpisania) — to napędza ETag list starej appki.
- **K1.8** Wpis `przeliczenie` w `prod_priority_log` powstaje tylko, gdy `utrwal(zrodlo=…, user_id=…)` dostanie źródło
  („Przelicz teraz”) — także wtedy, gdy nic się nie zmieniło (`note` = źródło, `new_value` = liczba zamówień
  zmienionych w pierwszym przebiegu; raport sumuje wszystkie przebiegi). Cron i wyzwalacze wołają bez źródła i nie
  logują. (raport K1, rozstrz. 17; plan K2 p. 10 mówił „tylko gdy coś zmieniło”)
- **K1.9** `gwiazdki.ustaw(order_ids, gwiazdki, user_id)` nie commituje i nie przelicza rang: pierwsze zapytanie to
  blokada zamówień rosnąco po id (`blokady_zamowien.zablokuj_zamowienia`), potem zapis zmienionych zamówień i wpisów
  logu `gwiazdki`; zwraca `zmienione`, `bez_zmian`, `brak`. Bez blokady tras. Sekwencję commit → `ustaw` → commit →
  `utrwal_po_commicie()` wykonuje router (K2.17).
- **K1.10** Doróbka dostaje w konstruktorze `priority_rank = 0` i `is_priority = True` (bez przeliczania rang po
  odrzuceniu sztuki); `complete_task` nie kasuje rangi doróbki na Formatowaniu, ale dalej zamyka wpis
  `prod_rework_log`.
- **K1.11** `ProductionProduct.lock_priority()` i `unlock_priority()` są puste do P4; `unlock_priority()` nie zeruje
  `priority_manual_override` — robi to wyłącznie `utrwal()`. Końcówki, które z nich korzystały, usunął K2 (K2.23).
- **K1.12** Wywołania przeliczenia w `sync_service` (po imporcie zamówień i w `_update_product_priorities`) idą do P4
  przez warstwę zgodności `priority_service` (`get_priority_calculator().recalculate_all_priorities()` →
  `kolejka.utrwal()`; raport niesie też stare klucze `products_updated`, `products_prioritized`, `products_processed`
  i `manual_overrides_preserved` — zawsze 0); wprost przepina je K8. Singleton w `services/__init__.py` deleguje do
  tej samej warstwy. (odstępstwo od 9.5)
- **K1.13** Wyzwalacze `utrwal()` poza tabelą 9.3: „Wydane klientowi” (`handed_over` w panelu Logistyki), Weryfikacja
  „Cofnij do pakowania” oraz akcje tras, których tabela nie wymienia (edycja trasy, zmiana kolejności przystanków,
  cofnięcie dostarczenia i niedostarczenia, zdjęcie niedostarczonego) — przelicza każda akcja idąca przez
  `trasy_api._akcja`. `routes.usun` woła `drabina.usun_szczebel_trasy` (renumeracja od razu; na MySQL wiersz usunąłby
  też FK CASCADE).
- **K1.14** Handlery API mobilnego pod `with_idempotency` nie commitują, więc Dostawa (`dostawa_api._zapis`) i „Cofnij
  do pakowania” tylko PLANUJĄ przeliczenie (`kolejka.zaplanuj_po_commicie()`), a dekorator wykonuje je po udanym
  commicie (`kolejka.wykonaj_zaplanowane()`); ponowienie po 1213 w `_zapis` porzuca plan (`porzuc_zaplanowane()`).
- **K1.15** `is_priority` pozycji jest pochodną (doróbka albo gwiazdki ≥ 1 albo „Po terminie”) nadpisywaną przy każdym
  `utrwal()`; ręcznej gwiazdki pozycji nie ma od K4a (K4a.17).
- **K1.16** `ustawienia.*` czytają wiersz `prod_config` wprost — bez pamięci podręcznej procesu `config_service` —
  przez `db.session` w `no_autoflush`; `ustawienia.prog_blisko(sesja)` czyta sesją `utrwal`. Zmiana trybu, K, limitu i
  progów działa od razu na wszystkich workerach. (plan K1 zakładał pamięć podręczną 60 min; zmienione w K2 decyzją
  karty)
- **K1.17** Klucz kafla-pozycji (`kolejka._kafle_pozycji`): doróbki (po `created_at`), szczebel, gwiazdki malejąco,
  pozycje zamówień rozpoczętych, grupa materiału po najbliższym terminie w grupie (potem gatunek, klasa, grubość
  malejąco), termin zamówienia, długość i szerokość malejąco, numer zamówienia, kolejność pozycji, id. Gwiazdki stoją
  PRZED grupą materiału — reguła 3.2 (rozstrzygnięcie przy planie K1; 3.3 już poprawione).
- **K1.18** Najbliższy termin grupy materiału liczy się po kluczu (szczebel, gatunek, klasa, grubość) przez wszystkie
  pozycje szczebla — także o różnych gwiazdkach i z zamówień rozpoczętych.
- **K1.19** `priority_rank` i `priority_rung` zamówień nieaktywnych zostają z ostatniego przeliczenia (nie są
  zerowane). Monitory (`widok.priorytet_zamowien`) oddają dla nieaktywnych rangę, szczebel i plakietkę `None`; pole
  `priorytet` API mobilnego (`stol.kontekst_priorytetu`) aktywności nie sprawdza — dla pozycji zamówienia nieaktywnego
  (wyszukiwarka, szczegóły pozycji) `szczebel` i `trasa` pochodzą z ostatniego przeliczenia.
- **K1.20** `kolejka.utrwal_po_commicie()` przelicza przy każdym wywołaniu, bez znacznika „raz na żądanie”;
  przeliczenie bez zmian to jeden przebieg samych odczytów, bez blokad.
- **K1.21** Importy pakietu `priorytety` w routerach i serwisach logistyki oraz w `rework_service`, `sync_service` i
  `mobile_api_service` są lokalne (wewnątrz funkcji), a `priorytety/models.py` odwołuje się do trasy napisem: pakiet
  priorytetów importuje logistykę, więc import na górze modułu dałby cykl. Router panelu priorytetów woła
  `common_api.admin_required` leniwie z powodu drugiego cyklu: `modules.production` ładuje pakiet priorytetów (z
  routerem panelu), a `modules.production.routers` importuje `apply_security` z niedokończonego jeszcze
  `modules.production`.
- **K1.22** `utrwal()` pracuje na WŁASNEJ sesji i nigdy nie dotyka `db.session`: migawka zwykłym odczytem → zamówienia
  `FOR UPDATE` rosnąco po id (tylko te, którym zmienia się wiersz albo pozycje) → pozycje tych zamówień `FOR UPDATE` →
  zapis wyłącznie zmienionych wierszy → commit. Nie bierze blokady tras ani stołu. Nigdy nie rzuca; zwraca raport:
  `success`, `zamowien`, `pozycji`, `zmienione_zamowienia`, `zmienione_pozycje`, `ostrzezenia`, `duration_seconds`,
  `error`.
- **K1.23** Przebieg kontrolny: po każdym zapisie `utrwal()` czyta migawkę od nowa i poprawia różnice, aż przebieg nie
  znajdzie żadnej — najwyżej 3 przebiegi, potem ostrzeżenie w logu. Dwa przeliczenia naraz nie zostawiają mieszanki
  rang; dodatkowego wiersza blokady nie ma. (raport K1, I1; dziennik centrali, rozstrz. 6)
- **K1.24** Limit czekania: sesja `utrwal` jest przypięta do jednego połączenia z sesyjnym `innodb_lock_wait_timeout`
  = 5 s (`kolejka.LIMIT_CZEKANIA_NA_BLOKADE_S`), przywracanym przed oddaniem połączenia do puli (nieudane przywrócenie
  = unieważnienie połączenia). Przekroczenie (MySQL 1205) → `success: False` bez ponowienia; 1213 → jedno ponowienie
  na nowej sesji. (K1-poprawka-1; dziennik centrali, rozstrz. 7 i 12)
- **K1.25** Warunek wstępny `utrwal()`: wołający nie ma niezatwierdzonych zapisów zamówień ani pozycji — wołać
  wyłącznie po commicie. Gdy przeliczenie musi zablokować wiersz z takim zapisem, na MySQL kończy się po około 5 s
  raportem `success: False`, a nie czekaniem do limitu serwera.
- **K1.26** Przypisania idą tylko na obiektach z odczytu blokującego: zamówienie albo pozycja skasowane między migawką
  a blokadą nie dostają rangi, a pozycja, która w tym czasie wyszła z produkcji, zostaje nietknięta (jej status jest
  sprawdzany ponownie). Statusu zamówienia kod nie sprawdza ponownie — zamówienie, które w tym oknie przestało być
  aktywne, dostaje rangę i szczebel z migawki i zachowuje je jako ostatnie (K1.19).
- **K1.27** Numer zamówienia w kluczu rangi i kolejki porządkowany jest liczbowo, gdy składa się z samych cyfr (9999
  przed 10000), inaczej tekstowo (`kolejka._klucz_numeru`).
- **K1.28** Ranga pozycji = ranga zamówienia × 100 + kolejność pozycji przycięta do 0–99 (`stale.MNOZNIK_RANGI`);
  pozycje powyżej 99. w jednym zamówieniu mają tę samą rangę.
- **K1.29** Pozycje szczebli pokazywane ludziom, zapisywane w `prod_orders.priority_rung` i w logu `szczebel` to
  indeksy od 1 wśród szczebli WIDOCZNYCH. Kolumna `prod_priority_rungs.position` numeruje wszystkie wiersze, także
  ukryte szczeble tras załadowanych, w trasie i wykonanych; `drabina.pozycja_szczebla()` zwraca dla ukrytego `None`.
- **K1.30** `drabina.przesun()` i `drabina.uzupelnij()` same biorą blokadę tras; `zapewnij_szczebel_trasy` i
  `usun_szczebel_trasy` wymagają jej od wołającego (`routes.utworz`, `routes.usun`). Przesunięcie na tę samą pozycję
  niczego nie zapisuje; `pozycja` musi być liczbą całkowitą (nie `bool`, nie tekst). Statusy tras przy zapisie drabiny
  czytane są odczytem bieżącym.
- **K1.31** Trasa ma szczebel na drabinie tylko w statusach `robocza` i `zatwierdzona`
  (`stale.STATUSY_TRASY_NA_DRABINIE`) — zbiór węższy niż aktywne trasy logistyki. Miejsce domyślne nowego szczebla
  liczy się względem najniższego szczebla trasy roboczej albo zatwierdzonej; ukryte szczeble tras się nie liczą.
- **K1.32** „Dziś” przeliczenia to `kolejka.dzis()` (czas lokalny). „Po terminie” = termin < dziś; „Blisko terminu” =
  dziś ≤ termin ≤ dziś + próg dni roboczych (poniedziałek–piątek, bez kalendarza świąt).
- **K1.33** `DEADLINE_DAY_TYPE` działa wyłącznie przy nadawaniu terminu nowym pozycjom
  (`sync_service._calculate_deadline_date`): `kalendarzowe` = data + max(dni, 0), `robocze` = dotychczasowe
  `_add_business_days`; błąd odczytu ustawienia oznacza dni robocze.
- **K1.34** Odczyt ustawień ma dolne granice (miejsca ≥ 1, limit odłożeń ≥ 1, próg ≥ 0, wersja appki ≥ 0, dni terminu
  ≥ 1); wartość spoza nich albo spoza listy daje wartość domyślną ze `stale` i ostrzeżenie w logu.
- **K1.35** Cron logistyki: faza priorytetów idzie po fazach logistyki i po uruchomieniu wątków w tle, we własnym
  `try/except` — `drabina.uzupelnij()` z commitem, potem `kolejka.utrwal()`. Odpowiedź ma `szczeble_uzupelnione` i
  `priorytety_utrwalone` (raport `utrwal`); po błędzie fazy oba są `null`, a cron kończy się normalnie. Wyjątek w
  `uzupelnij()` pomija `utrwal()` w tym przebiegu.
- **K1.36** Migracja `2026-10-05-priorytety-produkcji.sql` zakłada schemat kroku K1: 5 kolumn `prod_orders` z indeksem
  rangi, trzy tabele (stół z kluczem unikalnym `(station_code, unit_key)` i indeksami `station_code`, `order_id`,
  `product_id`), 9 szczebli i 38 wierszy `prod_config` (5 kluczy × 7 stanowisk, w tym wiersz blokady, oraz 3 wspólne).
  Resztę schematu P1 — `zrodlo` i `sent_by_user_id` stołu oraz trzy akcje logu — dokłada
  `2026-10-06-priorytety-stol-zrodlo.sql` (K3.32).

### 16.2 K2 — API panelu

Punkty K2.1–K2.15 odpowiadają doprecyzowaniom planu K2 (p. 1–15); K2.16–K2.23 pochodzą z raportu K2 i późniejszych
kart.

- **K2.1** Odmowa panelu ma format `{"success": false, "error": "<kod>", "message": "<po polsku>"}` z ewentualnymi
  polami (`pole`, `nieznane`, `limit`, `stanowiska`, `nieudane`). Kody 400: `dane_niepoprawne`,
  `gwiazdki_niepoprawne`, `za_duzo_zamowien`, `szczebel_staly`, `pozycja_niepoprawna`, `stanowisko_nieznane`,
  `ustawienie_niepoprawne`, `prog_wersji_wymagany`; 404: `zamowienie_nieznane`, `szczebel_nieznany`, `brak_kafla`;
  409: `trasa_nieaktywna`, `drabina_zmieniona`, `brak_na_stanowisku`; 500: `przeliczenie_nieudane`, `blad_serwera` (z
  ogólnym komunikatem). `stanowisko_bez_stolu` to 400 w `GET /kolejka` i `PUT /ustawienia`, a 409 w akcjach stołu.
  Formaty odmów `guard` (401, 403) i `admin_required` (403) zostają własne.
- **K2.2** `pozycja` w `PUT /drabina/kolejnosc` to indeks 1..n w WIDOCZNEJ drabinie, w kolejności z `GET /drabina`
  (tak samo liczy `drabina.przesun`). `pozycja` < 1 albo nie-liczba → 400 `dane_niepoprawne`; ponad liczbę widocznych
  szczebli → 400 `pozycja_niepoprawna`. (raport K2, rozstrz. 6)
- **K2.3** Opcjonalne `oczekiwane` w `PUT /drabina/kolejnosc` to id widocznych szczebli w kolejności, którą widział
  klient; inna drabina pod blokadą tras → 409 `drabina_zmieniona` bez zapisu.
- **K2.4** Drabina (z licznikami `w_produkcji`), cała kolejka i modal priorytetu liczą szczebel, tagi i rangę na żywo
  (`kolejka.policz` na migawce bez blokad). Kolumny `priority_rank` i `priority_rung` to pamięć podręczna czytelników
  SQL i mogą różnić się od panelu do najbliższego `utrwal()`.
- **K2.5** Samonaprawa w `GET /drabina` — jedyny odczyt panelu, który zapisuje — rusza tylko, gdy brakuje szczebla
  stałego albo szczebla trasy roboczej lub zatwierdzonej: commit, blokada tras, `drabina.uzupelnij`, commit; bez
  przeliczenia rang. Porażka nie psuje odczytu (`uzupelniono: 0` i ostrzeżenie `samonaprawa_nieudana`).
- **K2.6** Ostrzeżenie o datach (`kod: daty_tras`, `route_ids`, `message`) porównuje kolejne szczeble TRAS w widocznej
  drabinie (szczeble gwiazdek i tagów między nimi się nie liczą): wyższa trasa z późniejszym `date_from` niż niższa.
  Jedno ostrzeżenie na parę; nic nie przesuwa się samo. (raport K2, rozstrz. 4)
- **K2.7** `GET /kolejka?stanowisko=S&limit=L` (limit 1–500, domyślnie 50) to podgląd tego, co stół wziąłby jako
  następne: ten sam `kandydaci_stanowiska`, bez kafli leżących na stole i odłożonych. Wejście do algorytmu buduje
  jedna funkcja `widok.wejscie_kandydatow`, wołana także przez stół. Nieznane stanowisko → 400 `stanowisko_nieznane`.
- **K2.8** Ustawienia: K 1–5, limit odłożeń 1–50, próg „Blisko terminu” 0–15, minimalna wersja appki ≥ 0 (dni terminu
  — K4b.5). Zapis idzie jedną transakcją dla wszystkich kluczy, bez blokad; każda zmieniona wartość zostawia wiersz
  logu `ustawienia` (`old_value`, `new_value`, `note` = klucz; brak wiersza `prod_config` = zmiana). Przeliczenie rang
  po commicie tylko przy zmianie progu „Blisko terminu”. `PUT /ustawienia` jest jedyną drogą zmiany tych kluczy z
  panelu; wyjątek: `POST /production/api/reset-configs` (bez przycisku w UI) przywraca `DEADLINE_DEFAULT_DAYS`,
  `DEADLINE_FINISHED_DAYS` i `DEADLINE_DAY_TYPE` do wartości domyślnych, bez wpisu `ustawienia` w logu (kluczy
  `priorytety_*` nie rusza).
- **K2.9** Próg „Blisko terminu” to domyślnie 3 dni robocze (`stale.BLISKO_TERMINU_DNI`, seed migracji) — 4.3 jest już
  zgodne.
- **K2.10** `POST /przelicz` woła `kolejka.utrwal(zrodlo='panel', user_id=…)`; wpis logu robi sam `utrwal` (K1.8),
  router niczego nie zapisuje. Odpowiedź niesie raport bez pola `error`; porażka → 500 `przeliczenie_nieudane`.
- **K2.11** `PUT /zamowienia/gwiazdki` `{order_ids, gwiazdki}`: `gwiazdki` typu `int` 0–5 (nie `bool`, nie tekst),
  `order_ids` to niepusta lista liczb całkowitych; duplikaty są usuwane, a po ich usunięciu wolno najwyżej
  `stale.LIMIT_HURTU` = 500 (400 `za_duzo_zamowien`). Odpowiedź: `zmienione`, `bez_zmian`, `nieznane`, `przeliczenie`;
  404 `zamowienie_nieznane` tylko wtedy, gdy nie istnieje żadne z zamówień.
- **K2.12** Kody `drabina.BladDrabiny` tłumaczy router: `brak_szczebla` → `szczebel_nieznany` (404),
  `pozycja_poza_zakresem` → `pozycja_niepoprawna` (400); `szczebel_staly` (400) i `trasa_nieaktywna` (409) bez zmian.
  `gwiazdki.BladGwiazdek` → 400 `gwiazdki_niepoprawne`.
- **K2.13** Podgląd kolejki stanowiska bierze szczebel zamówienia z kolumny `priority_rung` (jak stół, 4.2), tag
  „Rozpoczęte” liczy na żywo, a gwiazdki, termin i numer z bieżących danych; kolumna `priority_rank` nie wpływa na
  kolejność kafli. Pokazuje dokładnie to, co weźmie dopełnienie. Cała kolejka i modal liczą na żywo (K2.4); różnica
  trwa najwyżej do najbliższego `utrwal()`.
- **K2.14** Pakowanie w podglądzie kolejki: kafel-zamówienie ma informacyjne pole `sposob_dostawy_ustawiony`, które od
  logistyki 4.6 niczego nie blokuje — zamówienie bez sposobu dostawy jest zwykłym kandydatem i ma miejsce w kolejce
  jak każde inne (16.6). (plan K2 p. 14 zakładał, że stół je pomija; zmienione scaleniem logistyki 4.6)
- **K2.15** Reguła jednostki: wiersz stołu z kluczem innej jednostki niż bieżąca (`p:<id>` po przejściu na
  `zamowienie` i odwrotnie) jest nieaktualny — nie ukrywa kandydata, nie liczy się do K i nie jest pokazywany jako
  kafel; zdejmuje go pierwszy pisarz zamówienia (K3.2) albo biuro (widma, K4b.17). `PUT /ustawienia` przy zmianie
  jednostki niczego na stole nie zmienia.
- **K2.16** Blueprint `priorytety_panel` pod `/production/api/priorytety` ma 14 końcówek API: `GET /drabina`, `PUT
  /drabina/kolejnosc`, `PUT /zamowienia/gwiazdki`, `POST /przelicz`, `GET /kolejka`, `GET /zamowienia/<id>/priorytet`,
  `GET /stoly`, `GET /odlozenia`, `POST /stoly/<S>/wyslij`, `POST /stoly/<S>/zdejmij`, `GET /start`, `POST
  /start/przygotuj`, `GET /ustawienia`, `PUT /ustawienia`. Wszystkie pod `guard` (login i moduł `production`); `POST
  /przelicz`, `POST /start/przygotuj` oraz `GET` i `PUT /ustawienia` dodatkowo `admin_required`. Poza nimi blueprint
  serwuje statykę (`priorytety_panel.static`: `priorytety.js` i `priorytety.css`) bez `guard`.
- **K2.17** Zapisy drabiny, gwiazdek i stołu („Wyślij”, „Zdejmij”, „Przygotuj stoły”) idą przez `_zapis_z_ponowieniem`
  wzorem commit → blokada → zapis → commit: między commitem a pierwszą blokadą nie ma żadnego odczytu (id użytkownika
  czytane przed commitem); jedno ponowienie całego zapisu po MySQL 1213, drugie 1213 i każdy inny błąd → rollback i
  500 `blad_serwera`. Po commicie drabina i gwiazdki przeliczają rangi (gdy coś zmieniły), a akcje stołu wysyłają
  sygnał. Zapis drabiny blokuje trasy; gwiazdki blokują zamówienia rosnąco po id, bez blokady tras. `PUT /ustawienia`
  zapisuje bez blokad i bez ponowienia (K2.8).
- **K2.18** Pole `przeliczenie` w odpowiedziach zapisów ∈ `ok`, `nieudane`, `niepotrzebne`. `nieudane` nie cofa zapisu
  (gwiazdki, szczebel i ustawienia zostają) — rangi nadrobi cron.
- **K2.19** `GET /kolejka` bez parametrów: `{wyliczono, lacznie, zamowienia}` po randze liczonej na żywo; wiersz ma
  `order_id`, `numer`, `klient`, `ranga`, `gwiazdki`, `szczebel`, `tagi`, `termin`, `trasa`, `pozycji` (pozycje w
  produkcji) i `etapy`. Szczebel wirtualny (K1.5) ma `id: null`. W kaflu-zamówieniu podglądu stanowiska `pozycji` to
  pozycje liczone do kompletności (K3.36).
- **K2.20** `GET /zamowienia/<id>/priorytet` (modal): gwiazdki z autorem i czasem zmiany, szczebel z `pozycja` i `z`
  („szczebel n z z”), ranga, tagi i termin liczone na żywo, trasa (tylko robocza albo zatwierdzona), `stanowiska[]`
  (`pozycji`, `na_stole`, `odlozone`, `w_kolejce {miejsce, z}`, `niekompletne`) i `historia[]` (ostatnie wpisy logu
  zamówienia). `w_kolejce` to miejsce PIERWSZEGO kafla zamówienia. Zamówienie nieaktywne ma `aktywne: false`, bez
  rangi i bez listy stanowisk.
- **K2.21** `PUT /ustawienia` przyjmuje dowolny podzbiór kształtu `GET /ustawienia` (bez `nazwa` i bez klucza
  blokady), waliduje całość przed zapisem (jedno złe pole = nic się nie zmienia; 400 `ustawienie_niepoprawne` z
  `pole`, np. `stanowiska.gluing.miejsca`) i odpowiada stanem z `zmienione` i `przeliczenie`. Po zapisie router
  unieważnia pamięć podręczną `config_service` swojego procesu — import z Base. czyta liczby dni terminu przez
  `config_service`, więc pozostałe workery widzą je z opóźnieniem do 60 minut, jak przed P1.
- **K2.22** Lakiernia w API panelu: `PUT /ustawienia` z `stanowiska.painting.tryb = "stol"` → 400
  `stanowisko_bez_stolu`; `GET /kolejka?stanowisko=painting` → 400 `stanowisko_bez_stolu`; w modalu `w_kolejce: null`
  (16.7).
- **K2.23** Usunięte w K2: `PUT /products/<id>/priority`, `POST /update-priority`, `POST /recalculate-all-priorities`,
  `POST /products/<id>/set-manual-priority`, `GET /priority-statistics` oraz akcja `update_priority` w `bulk-action`
  (teraz 400). `POST /set-priority` usunął K4a.

### 16.3 K3 — stół, Odłóż, bramka, sygnały, „Wyślij”, start stołów

Punkty K3.1–K3.17 odpowiadają doprecyzowaniom planu K3 (p. 1–17) w wersji obowiązującej po kartach naprawczych;
K3.18–K3.33 pochodzą z karty i raportu K3, K3.34–K3.39 z K3-poprawki-1, K3.40–K3.42 z K3-poprawki-2, K3.43 z kontraktu
appki (K6).

- **K3.1** Blokady pisarzy stołu (`stol.dopelnij`, `stol.wyslij`, `stol.zdejmij_przez_biuro`, `stol.przygotuj_start`):
  router commituje, a pierwszym odczytem nowej transakcji jest blokada stanowiska (`stol.zablokuj_stanowisko` — wiersz
  `prod_config` `priorytety_blokada_<S>` `FOR UPDATE`; brakujący wiersz kod dopisuje na MySQL przez `INSERT IGNORE`).
  Potem zamówienia `FOR SHARE` rosnąco po id i WSZYSTKIE ich pozycje `FOR SHARE` (`ORDER BY order_id, id`) — w
  dopełnianiu i starcie stołów wszystkie zamówienia z pozycją w statusie stanowiska, w „Wyślij” tylko zamówienie z
  żądania, w „Zdejmij” tylko zamówienie kafla (jego `order_id` daje zwykły odczyt wiersza stołu już pod blokadą
  stanowiska); „Wyślij” i „Zdejmij” biorą potem `FOR UPDATE` własnych wierszy stołu (K3.19). To kolejność kanoniczna
  wszystkich pisarzy. Nigdy blokad X zamówień ani pozycji, nigdy blokady tras. W zapytaniach MySQL blokada S ma postać
  `LOCK IN SHARE MODE`. (plan K3 p. 1 — zmiana wobec 9.4 „FOR SHARE pozycje, bez blokad zamówień”; ślad zapytań w
  raporcie K3)
- **K3.2** `stol.zdejmij_nieaktualne(order)` to jedna reguła uzgadniania stołu, wołana pod blokadą X zamówienia i jego
  pozycji przez pięciu pisarzy: ZAKOŃCZ (`mobile_api.order_complete`), doróbkę (`rework_service`), zmiany z Base.
  (`sync_service.apply_baselinker_changes`), hurtową zmianę statusu (`products_api._zapisz_zmiane_statusu`) i cron
  osieroconych (`delivery.przenies_osierocone_z_logistyki`). Sama zaczyna od `flush` (zmiany statusów wołającego
  trafiają do bazy przed odczytem bieżącym wierszy stołu po `order_id`). Kafel `p:` zostaje tylko, gdy pozycja czeka
  na swoim stanowisku w jednostce `pozycja`; kafel `o:` — gdy zamówienie ma tam pozycję i jest kompletne albo kafel ma
  źródło `biuro` lub `start`; wiersze innej jednostki i Lakierni znikają. Funkcja zwraca kody stanowisk, z których coś
  zdjęła. `stol.zdejmij_kafel` z 9.2 istnieje w module, ale kod produkcyjny go nie woła. (plan K3 p. 2; raport K3,
  rozstrz. 3 i D9)
- **K3.3** Próg wersji: tablet jest „stary”, gdy `priorytety_min_app_version_code` > 0 i `last_app_version_code` (z
  heartbeatu) jest nieznany albo mniejszy od progu (`stol.stara_appka`). Próg 0 = bramka wersji wyłączona — w trybie
  `stol` bramka stołu obowiązuje wtedy każdy tablet; panel nie pozwala takiej kombinacji wprowadzić (K4b.21). (plan K3
  p. 3; raport K3, rozstrz. 39)
- **K3.4** `priorytet.szczebel` ∈ `"trasa"`, `"gwiazdki"` (także szczebel „bez gwiazdek”), `"po_terminie"`,
  `"blisko_terminu"`, `"rozpoczete"`, `"dorobka"` albo `null` (zamówienie bez rangi albo `priority_rung` spoza
  widocznej drabiny). Rodzaj wynika z `prod_orders.priority_rung` tłumaczonego po indeksie wśród szczebli widocznych,
  nie po kolumnie `position`; `trasa` = `{id, nazwa, data}` tylko dla szczebla trasy. Kontekst liczy się raz na listę
  (`stol.kontekst_priorytetu`), bez pamięci w `g`; plakietka tagu może być nieaktualna do najbliższego `utrwal()`.
  (plan K3 p. 4 — 6.1 nie wymienia `rozpoczete` ani `null`; raport K3, rozstrz. 22 i 24)
- **K3.5** `pozycja_w_zamowieniu` = `"i/n"`: `n` to liczba niezanulowanych „miejsc” zamówienia, `i` — miejsce po
  (`product_sequence_in_order`, `id`). Doróbka stoi w miejscu oryginału (także anulowanego w całości); pozycja
  anulowana bez żywej doróbki ma `null`. (plan K3 p. 5; raport K3, rozstrz. 23)
- **K3.6** ETag `desk` (słaby) obejmuje: najpóźniejszy `updated_at` i liczbę pozycji zamówień stanowiska, liczbę
  pozycji w statusie stanowiska, sumę liczników sztuk stanowiska, czas i sumę gwiazdek zamówień, czasy i liczby
  wierszy stołu (w tym odłożonych), K, limit, jednostkę, tryb oraz `KSZTALT_ODPOWIEDZI_KOLEJKI` (6) i
  `KSZTALT_ODPOWIEDZI_STOLU` (2). W trybie `stol` liczy się po dopełnieniu i commicie. (plan K3 p. 6 — szerszy niż
  planowano; raport K3, rozstrz. 16)
- **K3.7** `POST /api/mobile/orders/<id>/postpone` `{station_code?, zakres, powod, notatka?}`: `<id>` to zawsze id
  POZYCJI (dla `zakres: "zamowienie"` — dowolnej pozycji zamówienia, kafel `o:<order_id>`), a `zakres` musi zgadzać
  się z jednostką stanowiska. Błędy: 400 `missing_station_code`, 404 `unknown_station`, 403 `station_mismatch`
  (rozpoznanie stanowiska jak w ZAKOŃCZ), błędy nagłówka `X-Worker-Ids` jak w ZAKOŃCZ, 409 `stanowisko_bez_stolu`
  (Lakiernia, przed walidacją ciała), 400 `dane_niepoprawne` (zły albo niezgodny z jednostką `zakres`, złe typy,
  notatka ponad 255 znaków), 400 `powod_niepoprawny` (powód spoza listy, `inne` bez niepustej notatki), 404
  `order_not_found`, 409 `nie_na_stole` (kafla nie ma na stole albo jest już odłożony), 409 `limit_odlozen`. (plan K3
  p. 7 — 6.2 zna tylko trzy kody)
- **K3.8** Kiedy idzie sygnał `station:<kod>`: ZAKOŃCZ (to stanowisko, następne stanowisko pozycji, stanowiska ze
  zdjętym kaflem), licznik sztuk i Odłóż (to stanowisko), `desk`, który coś pobrał (bez pobrania — nic), doróbka
  (stanowisko odrzutu, stanowisko powrotu, stanowiska ze zdjętym kaflem), hurtowa zmiana statusu (stanowiska ze
  zdjętym kaflem i stanowisko nowego statusu), zmiany z Base. w panelu (stanowiska ze zdjętym kaflem; Wycinanie, gdy
  doszła pozycja), cron osieroconych (Pakowanie i stanowiska ze zdjętym kaflem), „Wyślij” (to stanowisko, tylko gdy
  coś wysłało albo przywróciło), „Zdejmij” (to stanowisko, po każdym udanym zdjęciu) i „Przygotuj stoły” (każde
  stanowisko, na którym dodało kafle). Pozostałe — K3.38. (plan K3 p. 8)
- **K3.9** `kolejka_dalej` to liczba kandydatów poza stołem i odłożonymi, razem z doróbkami, które jeszcze nie weszły;
  dla jednostki `zamowienie` liczy tylko zamówienia kompletne. Ta sama liczba jest w `desk`, `postpone` i
  `GET /stoly`.
- **K3.10** Odczyty panelu: `GET /stoly` → stół i odłożone sześciu stanowisk ze stołem, w kolejności tabletu (kształt
  kafla — K4b.17, K4b.18, K4b.20); `GET /odlozenia` → otwarte odłożenia w bieżącej jednostce stanowiska, najdłużej
  leżące pierwsze (`stanowisko`, `nazwa`, `unit_key`, `order_id`, `numer`, `product_id`, `short_id`, `powod`,
  `notatka`, `odlozono`, `pracownik`). Bez blokad i bez dopełniania.
- **K3.11** Log: `odlozenie` przy Odłóż (`reason` = powód, `note` = notatka, `worker_id`, `device_id`);
  `odlozenie_zamkniete` przy ZAKOŃCZ kafla odłożonego (`reason` = powód, `note` = notatka, `old_value` = chwila
  odłożenia w ISO — czas leżenia liczy raport). Zdjęcie odłożonego kafla przez hurt, Base., doróbkę i cron nie loguje.
  (plan K3 p. 11 miał `note` = powód; raport K3, rozstrz. 15)
- **K3.12** Bramka a „Niekompletne”: na stanowisku zamówieniowym bramka stołu przepuszcza ZAKOŃCZ i licznik pozycji
  zamówienia NIEKOMPLETNEGO — każdego, nie tylko K pokazanych (sekcja nie ma wiersza stołu, a policzenie jej
  kolejności wymagałoby czytania innych zamówień pod blokadą X). Kompletne zamówienie bez wiersza stołu dostaje 409
  `nie_na_stole`; na stół wejdzie przy dopełnieniu (`GET desk`), gdy przyjdzie jego kolej w kolejce i na stole będzie
  wolne miejsce. Od K3-poprawki-2 pozycja musi przy tym czekać na stanowisku (K3.41). (plan K3 p. 12)
- **K3.13** Limit odłożeń jest miękki: Odłóż blokuje tylko wiersz własnego kafla, a liczbę otwartych odłożeń
  stanowiska czyta zwykłym `COUNT` z migawki żądania — dwa jednoczesne Odłóż mogą przekroczyć limit o 1. Licznik
  obejmuje wszystkie odłożone wiersze stanowiska, także nieaktualne (K2.15). (plan K3 p. 13 — zmiana wobec 9.2
  „odczytem bieżącym stołu stanowiska”)
- **K3.14** `desk` odpowiada z `Cache-Control: private, max-age=0` (także 304): tablet pyta serwer za każdym razem, z
  `If-None-Match`. (plan K3 p. 14)
- **K3.15** Doróbka na stanowisku zamówieniowym to KOMPLETNE zamówienie z pozycją-doróbką czekającą na tym stanowisku
  — wchodzi na stół pierwsze, w ramach K; niekompletne zostaje w „Niekompletnych” (kompletność ma pierwszeństwo).
  (plan K3 p. 15 mówił „ponad K”; zmienione K3-poprawką-1, K3.35)
- **K3.16** Kafel jednostki `zamowienie` = `{zamowienie: {…}, pozycje: […]}`: `zamowienie` ma 14 pól z serializacji
  pierwszej pozycji oraz `order_id`, `deadline` (termin z pozycji aktywnych) i `priorytet` bez `pozycja_w_zamowieniu`;
  `pozycje` to WSZYSTKIE pozycje zamówienia (także w innych statusach i anulowane) po (`product_sequence_in_order`,
  `id`). (plan K3 p. 16)
- **K3.17** Kolejność jest jedna dla `desk`, `postpone` i panelu (`stol.uporzadkuj`), a appka nie sortuje: `stol` —
  doróbki, wysłane przez biuro, startowe, pobrane z kolejki, w każdej grupie po `pulled_at`, potem `id`; `odlozone` —
  najdłużej leżące pierwsze; `niekompletne` — w kolejności rangi, najwyżej K. (plan K3 p. 17 mówił o `created_at`
  doróbki; obowiązuje 5.1)
- **K3.18** Do K liczą się WSZYSTKIE kafle leżące na stole w bieżącej jednostce (bez odłożonych), niezależnie od
  źródła (`zrodlo`: `kolejka`, `dorobka`, `biuro`, `start`); dopełnienie dobiera dopiero, gdy jest ich mniej niż K.
  Kafle `biuro` i `start` leżą ponad K i trzymają miejsca, dopóki nie zejdą. (karta K3; plan K3 liczył bez doróbek)
- **K3.19** Odczyt bieżący (`FOR UPDATE`) wierszy stołu ma tylko dwa kształty: równość po całym kluczu unikalnym
  (`station_code = ? AND unit_key = ?`, jeden klucz na zapytanie — bramka, Odłóż, „Wyślij”, „Zdejmij”) albo
  `order_id = ?` zablokowanego zamówienia (`zdejmij_nieaktualne`). Nikt nie blokuje wierszy stołu całego stanowiska
  ani nie czyta ich przez `unit_key IN (…)`; dopełnianie i start stołów czytają stół zwykłym odczytem. (raport K3, W1)
- **K3.20** Pisarze zamówienia (ZAKOŃCZ, Odłóż, hurt, doróbka, zmiany z Base., cron) dotykają wierszy stołu wyłącznie
  własnego zamówienia, pod jego blokadą X i po pozycjach; nie biorą blokady stanowiska, więc nie stoją w kolejce do
  niej za dopełnianiem — mogą najwyżej poczekać, aż dopełnianie, które już trzyma blokady S na ich zamówieniu i
  pozycjach, zrobi commit (bez cyklu blokad; zwykle milisekundy, do 5 s, gdy samo dopełnianie czeka na cudzą blokadę —
  16.8, K5.12). Licznik sztuk (`PATCH quantity`) zostaje pisarzem pozycji bez blokady zamówienia: bramka czyta status
  i stół zwykłym odczytem, a kafla nie zdejmuje.
- **K3.21** Limit czekania: w transakcji dopełnienia każde czekanie na cudzą blokadę trwa najwyżej 5 s (sesyjny
  `innodb_lock_wait_timeout`, `stol.krotkie_czekanie_na_blokady`; limit sesji wraca na tym samym połączeniu przed
  commitem i rollbackiem, w jego zasięgu nie ma autoflusha). Czekania na kolejne blokady mogą się sumować (blokada
  stanowiska, potem zamówienia) — stąd limit żądania `desk` w appce co najmniej 15 s (K3.43). Po 1205 `desk` nie
  ponawia i oddaje 200 z bieżącym stołem bez dopełnienia; 1213 → jedno ponowienie, drugie → 500 `desk_failed`. Limit
  ma tylko `GET desk` — „Wyślij”, „Zdejmij” i „Przygotuj stoły” czekają jak zwykłe zapisy panelu. (raport K3, W2 i
  rozstrz. 35–36; potwierdzone przez centralę)
- **K3.22** Odpowiedź `desk` i `postpone` liczy się zwykłymi odczytami (`stol.stan`), nie z wyniku dopełnienia: `desk`
  w trybie `stol` po commicie dopełnienia, w trybie `stary` w transakcji żądania; `postpone` w transakcji handlera,
  przed commitem dekoratora `with_idempotency` (widzi własne, jeszcze niezatwierdzone odłożenie). `postpone` oddaje
  stół BEZ dopełnienia (handler trzyma blokadę zamówienia) — wolne miejsce zajmie następny `GET desk`. Odłóż działa
  także w trybie `stary`.
- **K3.23** Błędy `desk`: 404 `unknown_station`, 403 `station_mismatch`, 409 `stanowisko_bez_stolu` (Lakiernia), 500
  `desk_failed`.
- **K3.24** Komunikat `limit_odlozen` odmienia liczbę i nazwę jednostki („Na Sklejaniu leży 10 odłożonych pozycji.
  Zamknij którąś, zanim odłożysz kolejną.”; „…leżą 3 odłożone zamówienia. Zamknij któreś…”). (raport K3, rozstrz. 18 —
  5.3 ma przykład bez odmiany)
- **K3.25** `priorytet` i `grupa_wykonczenia` są w każdej serializacji pozycji API mobilnego (listy, delta,
  wyszukiwarka, szczegóły, odpowiedzi ZAKOŃCZ, licznika i `reject`, stół); `KSZTALT_ODPOWIEDZI_KOLEJKI` = 6 obejmuje
  oba pola. `priority_rank` i `is_priority` zostają dla starej appki.
- **K3.26** Sygnał nie niesie danych do interpretacji (`{"kind": "station", "station": "<kod>"}`), idzie zawsze po
  commicie, a publikacja nie rzuca. Pod `with_idempotency` handler tylko planuje (`sygnaly.zaplanuj`), a dekorator
  wysyła po commicie (`sygnaly.wyslij()`) i porzuca plan przy rollbacku (5xx, statusy do ponowienia, wyjątek); przy
  powtórce idempotentnej handler się nie wykonuje. Routery panelu, `desk`, import i cron wysyłają po własnym commicie.
- **K3.27** `GET /api/mobile/realtime-token` → 200 `{enabled, token, ttl_seconds, sse_url, channels}`; kanały są w
  tokenie: stanowisko urządzenia, potem reszta jego grupy w kolejności procesu (tablet Krawędzi: `station:edges`,
  `station:painting`). 503 `{enabled: false, reason}` przy wyłączonym albo źle skonfigurowanym realtime; 404
  `unknown_station` dla urządzeń spoza stanowisk z kolejką produktów.
- **K3.28** „Wyślij”: `POST /stoly/<S>/wyslij` `{order_id}` → 200
  `{stanowisko, wynik, wyslane, przywrocone, juz_na_stole}` (`wynik`: `wyslano` albo `juz_na_stole`; listy kluczy
  kafli). Jednostka `pozycja`: kafel każdej pozycji zamówienia w statusie stanowiska; `zamowienie`: jeden kafel `o:`,
  także dla zamówienia niekompletnego (zostaje mimo niekompletności, bo ma źródło `biuro`). Kafel leżący — bez zmian;
  odłożony — wraca na stół (`zrodlo='biuro'`, nowy `pulled_at`). Błędy: 400 `dane_niepoprawne`, 400
  `stanowisko_nieznane`, 404 `zamowienie_nieznane`, 409 `brak_na_stanowisku`, 409 `stanowisko_bez_stolu`. Działa w
  `stary` i `stol`; sygnał idzie tylko, gdy coś się zmieniło.
- **K3.29** „Zdejmij”: `POST /stoly/<S>/zdejmij` `{unit_key}` (`p:<id>` albo `o:<id>`) → 200
  `{stanowisko, unit_key, order_id, product_id, odlozony}`; 404 `brak_kafla`, 400 `dane_niepoprawne`. Kafel wraca do
  kolejki — doróbka albo pierwszy kafel kolejki wejdzie znowu przy najbliższym dopełnieniu; panel to opisuje (K4b.18).
  (raport K3, D7; decyzja centrali: bez zmiany zachowania)
- **K3.30** Log: `wyslanie` (`new_value` = klucz kafla; przy przywróceniu odłożonego `old_value='odlozone'` z powodem
  i notatką) i `zdjecie` (`old_value` = źródło kafla albo `odlozone`) — oba z `order_id`, więc widać je w historii
  modalu. Dwa „Wyślij” naraz na różnych stanowiskach mogą dać 1213 na luce indeksu unikalnego stołu — jedno ponowienie
  w routerze panelu. (raport K3, rozstrz. 37)
- **K3.31** Start stołów: `GET /start` (`guard`, bez zapisu) oddaje dla sześciu stanowisk
  `{stanowisko, nazwa, tryb, jednostka, miejsca, liczba, na_stole, kafle}`, a kafel to
  `{unit_key, order_id, numer, product_id, short_id, powod, na_stole}`. `POST /start/przygotuj` (admin) idzie
  stanowisko po stanowisku, każde w osobnej transakcji; dodaje brakujące wiersze `zrodlo='start'`, istniejących
  (leżących i odłożonych) nie rusza; log `start_stolow` na stanowisko (`new_value` = dodane, `old_value` = już leżały,
  bez `order_id`). Przerywa na pierwszym nieudanym stanowisku (500 `blad_serwera` z `stanowiska` i `nieudane`), bez
  cofania poprzednich; jest idempotentne i nie przełącza trybu. (raport K3, rozstrz. 7)
- **K3.32** Migracja `2026-10-06-priorytety-stol-zrodlo.sql` (K3): `prod_station_desk.zrodlo` (domyślnie `kolejka`),
  `sent_by_user_id` i trzy akcje logu (`wyslanie`, `zdjecie`, `start_stolow`); zmiana ENUM dotyczy tabeli zakładanej w
  tym samym wdrożeniu.
- **K3.33** Znane wyjątki bez `zdejmij_nieaktualne`: hurtowe usunięcie pozycji (`bulk-action delete`; na MySQL kafel
  `p:` usuwa FK CASCADE, kafel `o:` zamówienia bez pozycji na stanowisku zostaje) i ręczna synchronizacja z
  `force_update`. Taki kafel biuro widzi jako widmo (K4b.17) i może go zdjąć; uzgodni go też następny pisarz
  zamówienia.
- **K3.34** Kafel rozpoczęty (start stołów) = pozycja w statusie stanowiska z licznikiem `quantity_done_<S>` > 0; dla
  jednostki `zamowienie` — zamówienie z taką pozycją, także niekompletne. To jedyna reguła: kod nie sprawdza źródła
  licznika i nie czyta `prod_station_events`, a `powod` w `GET /start` ma zawsze wartość `licznik`. (plan K3 miał też
  regułę „inna pozycja zamówienia zrobiona ręcznie na stanowisku”; usunięta K3-poprawką-1 — 21 zamiast 74 kafli na
  kopii danych)
- **K3.35** Doróbki wchodzą W RAMACH K: stoją na początku kolejki i wchodzą pierwsze przy najbliższym dopełnieniu, ze
  źródłem `dorobka`; przy pełnym stole czekają i liczą się do `kolejka_dalej`. Ponad K stół wychodzi wyłącznie przez
  kafle `biuro` i `start`. (plan K3 i raport K3: „ponad K”; zmienione K3-poprawką-1, decyzja Konrada 5.10)
- **K3.36** Kompletność bez pozycji omijających stanowisko: pozycja, której ścieżka omija stanowisko
  (`widok.sciezka_omija`, czyli `order_timeline_service.product_in_route` — bez docięcia omija Formatowanie, Krawędzie
  i Lakiernię; z docięciem omija Krawędzie, gdy nie ma obróbki krawędzi, i Lakiernię, gdy nie jest olejowana ani
  lakierowana; wejścia — Wycinania albo Składania — oraz Sklejania i Pakowania nie omija nic), nie liczy się do
  kompletności tego stanowiska, nie ma jej w `brakuje` ani w mianowniku `pozycji`. Wyjątek: pozycja omijająca, która
  mimo to STOI w statusie stanowiska, liczy się normalnie. Tag „Rozpoczęte” dalej patrzy na statusy. Nowy czytelnik
  kompletności musi podać `omijajace` (albo `omija`), inaczej wraca dawna reguła. (pytanie 8 raportu K3;
  K3-poprawka-1, decyzja centrali)
- **K3.37** `pracownik` w „Odłożonych” na tablecie (`desk`, `postpone`) to imię z inicjałem nazwiska — „Adam K.”
  (`stol.imie_z_inicjalem`; samo imię → imię, samo nazwisko → inicjał, brak → `null`). Panel biura pokazuje pełne imię
  i nazwisko. (raport K3: pełne nazwisko; zmienione K3-poprawką-1, decyzja Konrada 5.10)
- **K3.38** Sygnały dodane K3-poprawką-1: `station:packaging` po „Cofnij do pakowania” (Weryfikacja; plan w `g`) i po
  zmianie sposobu dostawy, która cofnęła coś do pakowania (router panelu Logistyki, jeden na żądanie);
  `station:cutting` i `station:assembly` po imporcie z Base., który utworzył pozycje (po przeliczeniu rang). Zwykła
  zmiana sposobu dostawy sygnału nie wysyła. (raport K3, rozstrz. 21: „bez sygnału”; zmienione K3-poprawką-1)
- **K3.39** W `with_idempotency` sygnały stanowisk idą jako PIERWSZY hak po commicie — przed synchronicznym statusem
  Base. Kolejność haków: sygnały stanowisk, status Base., sygnał agenta druku, dopychacz logistyki, `utrwal`. Tablet
  może więc pobrać stół z rangą sprzed zaplanowanego przeliczenia; kafle na stole i tak się nie przestawiają. (raport
  K3, D3; K3-poprawka-1)
- **K3.40** `GET desk` oddaje pole `tryb` (`stary` albo `stol`; także w odpowiedzi `postpone`). W trybie `stary` jest
  zwykłym odczytem — bez commita, blokady stanowiska, limitu czekania, dopełniania i sygnału — i oddaje bieżące
  wiersze stołu (np. kafle startowe) w tym samym kształcie; dopełnia wyłącznie w `stol`. Tryb wchodzi do ETagu, a
  `KSZTALT_ODPOWIEDZI_STOLU` = 2. (plan K3 i plan K2 p. 15 zakładały dopełnianie także w `stary`; zmienione
  K3-poprawką-2 — dziennik centrali, rozstrz. 19)
- **K3.41** Bramka statusu: w trybie `stol`, dla nowej appki i poza Lakiernią, ZAKOŃCZ i licznik pozycji, która nie
  czeka na tym stanowisku, dostają 409 `pozycja_poza_stanowiskiem` („Pozycja 1203_4 nie czeka na Pakowaniu.”) — PRZED
  odczytem wiersza stołu; w ZAKOŃCZ status czytany jest z pozycji spod blokady zamówienia. Dotyczy też pozycji
  kafla-zamówienia w innym statusie, pozycji omijającej stanowisko i brakujących pozycji zamówienia z
  „Niekompletnych”. (K3-poprawka-2 — dziennik centrali, rozstrz. 22)
- **K3.42** Oba 409 bramki (`pozycja_poza_stanowiskiem`, `nie_na_stole`) nie zapisują wpisu idempotencji:
  `BLEDY_DO_PONOWIENIA` to zbiór statusów HTTP `{400, 403, 404, 409}`, a o porzuceniu wpisu kolejki offline decyduje
  appka po polu `error`. ZAKOŃCZ zdejmuje kafel w tej samej transakcji także w trybie `stary` i dla starej appki;
  drugie ZAKOŃCZ tej samej pozycji z nowym `X-Operation-Id` dostaje w trybie `stol` (nowa appka, poza Lakiernią) 409
  `pozycja_poza_stanowiskiem`; stara appka i tryb `stary` bramki nie mają, więc tam to 409 nie pada — drugie ZAKOŃCZ
  kończy się 200 bez ponownej zmiany statusu. (raport K3-poprawka-2, odstępstwo 1 i rozstrz. 7–8; wynik wyścigu —
  16.8)
- **K3.43** Reguły po stronie appki ustala kontrakt `docs/api-mobile-priorytety.md` (K6), między innymi: ekran stołu
  tylko przy `tryb == "stol"` (Lakiernia zawsze lista, po kodzie stanowiska); siatka `desk` co 30 s, gdy na stole leży
  mniej kafli niż `miejsca`, i co 5 min w pozostałych przypadkach, a w trybie `stary` najwyżej co 30 s; `GET desk` po
  własnym ZAKOŃCZ i Odłóż oraz po sygnale; Odłóż tylko online; limit czasu żądania `desk` co najmniej 15 s; heartbeat
  zaraz po starcie appki.

### 16.4 K4a — Lista produkcyjna

Punkty K4a.1–K4a.14 odpowiadają doprecyzowaniom planu K4a (p. 1–14); K4a.15–K4a.18 pochodzą z karty i raportu K4a oraz
z K4-poprawki-1.

- **K4a.1** Modale priorytetu i drabiny to natywne `<dialog>` budowane w `priorytety/static/js/priorytety.js`
  (`window.Priorytety`; statyka blueprintu `priorytety_panel` ładowana w `dashboard.html`). Katalog
  `templates/priorytety/` z 9.1 nie powstał — render zakładki nie zależy od blueprintu priorytetów.
- **K4a.2** Zakładka nazywa się „Lista produkcyjna”. Kolejność kart = ranga z `GET /kolejka` (liczona na żywo);
  zamówienia spoza kolejki idą na koniec, po terminie i numerze. Gdy `/kolejka` nie odpowie, lista sortuje po terminie
  i pokazuje ostrzeżenie; spóźniony odczyt kolejki nie nadpisuje nowszego. (plan K4a p. 2; raport K4a, przegląd
  końcowy)
- **K4a.3** Serializery listy produktów (`_serialize_product`, `_serialize_production_item`) mają `order_id` i
  `order_priority_stars`. `_serialize_product` zachowuje do P4 `is_priority`, `priority_rank` i
  `priority_manual_override`; `_serialize_production_item` niesie z nich tylko `priority_rank`.
- **K4a.4** `lista.serializuj` logistyki ma `gwiazdki` (0–5) — z tego pola korzystają kolumna „★” i gwiazdki
  przystanków w edytorze trasy; serializer telefonu kierowcy jest bez zmian.
- **K4a.5** Modal priorytetu czyta `GET /zamowienia/<id>/priorytet`; klucze kafli do „Zdejmij” i podpis „wróci” przy
  kaflu bierze z `GET /stoly` (pole `wroci_przy_dopelnieniu`; tylko gdy zamówienie ma coś na stole albo odłożone), a
  po udanym „Zdejmij” czyta `GET /kolejka?stanowisko=S&limit=1` — komunikat „Kafel wróci przy następnym dopełnieniu
  stołu.” pada, gdy zdjęty kafel jest teraz pierwszy w kolejce. Sekcja „Historia” pokazuje wpisy logu zamówienia:
  `gwiazdki`, `wyslanie`, `zdjecie`, `odlozenie`, `odlozenie_zamkniete` (wpis `start_stolow` nie ma zamówienia, więc w
  historii się nie pojawia). (plan K4a p. 5 zakładał samą historię gwiazdek i jeden odczyt; rozszerzone kartą K4a)
- **K4a.6** Plakietka „Odłożone na …” pochodzi z `GET /odlozenia`: jedna na stanowisko — przy jednym odłożeniu z
  powodem, godziną i pracownikiem, przy kilku z liczbą (szczegóły w podpowiedzi i w modalu). Pracownik jest w panelu
  pełnym imieniem i nazwiskiem.
- **K4a.7** Hurt „Ustaw gwiazdki” działa na unikalnych zamówieniach zaznaczonych pozycji; powyżej 500 zamówień UI
  odmawia bez wysyłki (bez dzielenia na partie). Zdjęcie gwiazdek pyta o potwierdzenie zawsze, ustawienie — przy
  więcej niż 10 zamówieniach; okno potwierdzenia (`Priorytety.potwierdz`) startuje z fokusem na „Anuluj”. (plan K4a p.
  7; potwierdzenie dodane K4-poprawką-1, decyzja Konrada 5.10)
- **K4a.8** Modal drabiny: szczeble gwiazdek stałe, tagi i trasy ze strzałkami ↑↓ — `pozycja` to indeks sąsiada w
  widocznej drabinie, zawsze z `oczekiwane`; po 409 `drabina_zmieniona` modal czyta drabinę od nowa; jeden zapis
  naraz. Przeciągania nie ma (7.1 mówiło „przeciągalne”). Szczebel bez zamówień jest wyszarzony, z licznikiem „0 w
  produkcji”.
- **K4a.9** Pierwsza kolumna karty to miejsce w kolejce (`#n`; „—” dla zamówień spoza kolejki) zamiast uchwytu
  przeciągania.
- **K4a.10** Wskaźnik rangi w modalu szczegółów pozycji zniknął bez następcy.
- **K4a.11** Logistyka: kolumna „★” (wybór 0–5 tym samym komponentem, sortowalna) jest tylko do odczytu na
  zamówieniach zamkniętych, anulowanych i wydanych oraz chowa się, gdy kontener tabeli ma najwyżej 1035 px (lista obok
  mapy). (plan K4a p. 11; chowanie kolumny dodane K4-poprawką-1, decyzja Konrada 5.10)
- **K4a.12** Po każdym zapisie z komponentu idzie zdarzenie `priorytety:zmiana` z `rodzaj` (`gwiazdki`, `drabina` albo
  `stol`), `order_ids` i — przy gwiazdkach — `gwiazdki`, na `ProductionShared.eventBus`: Lista produkcyjna czyta wtedy
  `/kolejka` i `/odlozenia` od nowa, a Logistyka poprawia wiersz lokalnie. (plan K4a p. 12; `stol` i `gwiazdki` dodane
  w raporcie K4a)
- **K4a.13** Filtr `priority_range` w `GET /products/filters-data` został bez zmian (nikt go nie czyta); usuwa go K8.
  (odstępstwo od 9.5)
- **K4a.14** Klawiatura listy (Esc, Ctrl+A) nie działa pod otwartym oknem `dialog` ani dymkiem wyboru gwiazdek —
  zaznaczenie zostaje.
- **K4a.15** „Wyślij na stanowisko” jest w modalu przy każdym stanowisku zamówienia poza Lakiernią, a „Zdejmij ze
  stołu” przy kaflu leżącym i odłożonym — z opisem „Kafel wróci przy następnym dopełnieniu stołu” dla doróbki i kafla,
  który stanąłby pierwszy (K4b.18). Komunikaty błędów stołu pochodzą ze słownika UI; nieznany kod pokazuje `message`
  serwera. (karta K4a; spec 5.7, 7.1)
- **K4a.16** We froncie jest jedna droga zapisu gwiazdek (`Priorytety.ustawGwiazdki`: modal, hurt, Logistyka) i jedna
  drabiny; modal priorytetu i drabina wysyłają najwyżej jeden zapis naraz (`zapisTrwa`), kolumna „★” Logistyki — jeden
  na wiersz (`stan.wysylane`), a hurt Listy produkcyjnej nie ma własnej blokady. UI nie ponawia 500, a `przeliczenie:
  "nieudane"` pokazuje jako ostrzeżenie. Gwiazdki i drabinę zmienia każdy użytkownik z dostępem do modułu produkcji
  (7.3), nie tylko admin.
- **K4a.17** Usunięte: `products-dragdrop.js`, gwiazdka pozycji i progi rangi w JS oraz końcówka
  `POST /production/api/set-priority` — ostatni pisarz priorytetu pozycji bez blokady zamówienia.
- **K4a.18** Esc zamyka okna przez zdarzenie `cancel` i od razu oddaje fokus przyciskowi, który je otworzył (albo
  przyciskowi tej samej karty po przerysowaniu listy). (raport K4a, rozstrz. 13–14)

### 16.5 K4b — czytelnicy rangi, Konfiguracja, monitory

Punkty K4b.1–K4b.15 odpowiadają doprecyzowaniom planu K4b (p. 1–15); K4b.16–K4b.22 pochodzą z karty i raportu K4b oraz
z K4-poprawki-1.

- **K4b.1** Zakładka „Stanowiska” renderuje się po stronie serwera z tych samych funkcji, które stoją za `GET /stoly`
  i `GET /kolejka?stanowisko=` (`widok.stoly_panelu`, `widok.kolejka_stanowiska`) — tablet, panel i zakładka widzą to
  samo.
- **K4b.2** „Pierwsze 15 kafli kolejki” = `kolejka_stanowiska(S, limit=15)`: bez kafli leżących na stole i odłożonych,
  na Formatowaniu i Pakowaniu tylko zamówienia kompletne; niekompletne w osobnej sekcji z `na_stanowisku`, `pozycji` i
  listą brakujących (najwyżej 15).
- **K4b.3** Statystyki karty stanowiska: `na_stole`, `miejsca`, `odlozone`, `limit_odlozen`, `kolejka_dalej` i `tryb`
  zamiast progów rangi; kropka przy liczniku oznacza odłożone.
- **K4b.4** `high_priority_count` w `/dashboard-stats` to liczba ZAMÓWIEŃ aktywnych na szczeblach ★★★★★, ★★★★, „Po
  terminie” i trasach — suma liczników `w_produkcji` drabiny (`widok.liczba_pilnych_zamowien`), ta sama liczba co w
  modalu drabiny. Alert „Dużo pilnych zamówień” powyżej 10; przy błędzie warstwy priorytetów `null` i brak alertu.
- **K4b.5** Terminy przez `PUT /ustawienia`: `deadline_default_days` → `DEADLINE_DEFAULT_DAYS`,
  `deadline_finished_days` → `DEADLINE_FINISHED_DAYS` (liczba całkowita 1–90, log `ustawienia`, bez przeliczenia rang
  — zmiana dotyczy tylko nowych importów) i `deadline_day_type`. `POST /update-configs` nie ma tych kluczy na liście
  dozwolonych. (zakres 1–90 potwierdzony przez centralę)
- **K4b.6** Karty Konfiguracji „Terminy” i „Stół stanowisk” ładują stan z `GET /ustawienia` i zapisują własnym
  przyciskiem tylko zmienione pola, poza ogólnym paskiem zmian; 400 podświetla pole wskazane w `pole`, 403 blokuje
  karty.
- **K4b.7** Martwe klucze starego algorytmu (`PRIORITY_RECALC_INTERVAL_HOURS`, `PRIORITY_ALGORITHM_VERSION`,
  `STATION_*_PRIORITY_SORT`) i odczyt `prod_priority_config` w zakładce Konfiguracja zniknęły z kodu; wiersze
  `prod_config`, model i tabelę usuwa K8 (model czyta jeszcze stary panel w `routers/main_routers.py`).
- **K4b.8** Monitory czytają kolumny, nie `policz()` (`widok.priorytet_zamowien`): monitor stanowiska poza Lakiernią
  sortuje (zamówienie z doróbką na tym stanowisku pierwsze, `priority_rank` NULLS LAST, numer tekstowo), monitor
  Lakierni — jak lista tabletu (LAK.8), monitor zbiorczy — (`priority_rank` NULLS LAST, numer tekstowo). Szczebel i
  plakietka pochodzą z `priority_rung` tłumaczonego po indeksie widocznym (K1.29). Tagi mogą być spóźnione do
  najbliższego `utrwal()`; zamówienie nieaktywne nie ma rangi ani plakietki.
- **K4b.9** Monitory grupują karty po `ProductionOrder.id` (numer zamówienia powtarza się co rok), a kluczem karty w
  JS jest `order_id`. Widok HTML i AJAX monitora zbiorczego liczy jedna funkcja, więc mają tę samą kolejność.
- **K4b.10** Sekcje „TERAZ” i „Odłożone” na monitorze rysują się tylko, gdy są niepuste; licznik „Dalej w kolejce” w
  nagłówku — tylko w trybie `stol` (trybu stanowiska monitor nie pokazuje). Monitor nie dopełnia stołu: przy pustym
  stole widać kolejkę po randze, a stół zapełni pierwszy `GET desk` tabletu.
- **K4b.11** Uprawnienia: zakładka Stanowiska ma `login_required` jak pozostałe zakładki, `GET /stoly` jest pod
  `guard`, `GET /ustawienia` tylko dla admina; dostęp do monitorów bez zmian.
- **K4b.12** Odczyty dodane w `widok.py`: `stoly_panelu(stanowiska=None)` (opcjonalny filtr kodów),
  `liczba_pilnych_zamowien()` i `priorytet_zamowien(order_ids)` → `{gwiazdki, ranga, szczebel, plakietka}` z kolumn.
- **K4b.13** Etykiety powodów odłożenia po polsku są w `stale.ETYKIETY_POWODOW_ODLOZENIA`; odłożone w `GET /stoly`
  niosą gotowe `powod_etykieta` (zakładka i monitor nie mają własnej mapy).
- **K4b.14** `POST /update-config` (pojedynczy klucz) odrzuca klucze z prefiksem `priorytety_` albo `DEADLINE_` (400)
  — druga droga zapisu jest zamknięta.
- **K4b.15** Lakiernia u czytelników: `stoly_panelu()` zwraca sześć stanowisk, a zakładka, monitor i Konfiguracja
  pokazują Lakiernię jako listę bez stołu (LAK.8).
- **K4b.16** Zakładka „Stanowiska” jest podpięta w panelu (decyzja Konrada 5.10, wariant A) i odświeża się co 120 s
  tylko wtedy, gdy jest widoczna.
- **K4b.17** Zakładka pokazuje źródło kafla (wysłane przez biuro, rozpoczęte przed startem, doróbka), „Zdejmij ze
  stołu” przy kaflu i stół dłuższy niż K. `GET /stoly` ma klucz `widma`: wiersze stołu, których nie da się pokazać
  jako kafla (pozycja już nie czeka na stanowisku, zamówienie bez pozycji na stanowisku, kafel innej jednostki) — z
  opisem i możliwością zdjęcia. Widma bieżącej jednostki liczą się do K (leżące) albo do limitu odłożeń (odłożone), a
  tablet pokazuje je jako zwykłe kafle; wiersz innej jednostki nie liczy się do K i tablet go nie pokazuje — do limitu
  odłożeń liczy się tylko wtedy, gdy jest odłożony. (raport K3, D2; raport K4b, rozstrz. 5)
- **K4b.18** `wroci_przy_dopelnieniu` kafla w `GET /stoly` = doróbka albo kafel, który stanąłby w kolejce przed
  dzisiejszym pierwszym kandydatem (liczone z tymi samymi pozycjami omijającymi stanowisko, co dopełnienie). Panel
  pokazuje wtedy podpis „kafel wróci przy następnym dopełnieniu” — „Zdejmij” nie blokuje kafla. (raport K4b, rozstrz.
  6 i W1; decyzja centrali)
- **K4b.19** Sekcja „Start stołów” w karcie „Stół stanowisk”: podgląd (`GET /start`), „Przygotuj stoły”
  (`POST /start/przygotuj`) i „Włącz stoły” — jeden `PUT /ustawienia` z progiem wersji z pola i `tryb = stol` dla
  sześciu stanowisk (bez Lakierni).
- **K4b.20** Monitor pokazuje plakietki źródła kafla jak zakładka, a pracownika odłożenia w formacie „Adam K.” (pole
  `pracownik_krotko` z `GET /stoly`, format `stol.imie_z_inicjalem`); panel zostaje przy pełnym imieniu i nazwisku.
- **K4b.21** `PUT /ustawienia` odmawia kodem 400 `prog_wersji_wymagany` (`pole` = `min_app_version_code`), gdy żądanie
  WPROWADZA stan „stanowisko w `stol` przy progu wersji 0”: ustawia `stol` stanowisku, które w bazie nie jest w
  `stol`, przy progu wynikowym 0, albo obniża próg z wartości > 0 do 0, gdy jakieś stanowisko jest wynikowo w `stol`.
  Zastany stan `stol` + 0 nie blokuje wycofania na `stary` ani innych zmian; Lakiernia jest pomijana; reguła nie
  bierze blokady. (raport K3, rozstrz. 39; K4-poprawka-1 — uzupełnia 8.6 „0 = brak bramki”)
- **K4b.22** Czytelnicy (zakładka Stanowiska, `/dashboard-stats`, monitory hali) niczego nie zapisują, nie blokują i
  nie dopełniają stołu. Błąd warstwy priorytetów nie kładzie widoku: zakładka zostaje bez sekcji stołu, dashboard
  dostaje `high_priority_count: null`, monitor — `stol.blad: true`.

### 16.6 Logistyka 4.6 — Pakowanie bez sposobu dostawy

- **L46.1** ZAKOŃCZ na Pakowaniu nie zwraca już 409 `delivery_method_not_set`: zamówienie bez sposobu dostawy pakuje
  się normalnie, a etykieta paczki ma pas „NIE USTAWIONO”. (logistyka, krok 4.6 — decyzja Konrada 5.10; spec logistyki
  etapu 4, sekcja 10a)
- **L46.2** Po spakowaniu bez sposobu dostawy Base. nie dostaje statusu po spakowaniu
  (`baselinker_status_sync._determine_packaging_target_status` nie wyznacza wtedy statusu); wysyła go pierwsze
  ustawienie sposobu w panelu (`delivery.ustaw_sposob_dostawy`, okno 8.7 logistyki).
- **L46.3** Priorytety nie filtrują Pakowania po sposobie dostawy: zamówienie bez sposobu jest zwykłym kandydatem
  stołu, sekcji „Niekompletne”, `kolejka_dalej`, „Wyślij”, startu stołów, miejsca w kolejce w modalu i podpisu
  „wróci”. (raport K3, rozstrz. 12 i plan K2 p. 14 mówiły odwrotnie; zmienione scaleniem logistyki 4.6)
- **L46.4** Bramka ZAKOŃCZ stołu nie zna sposobu dostawy: pozycja Pakowania bez sposobu przechodzi ją jak każda inna —
  w trybie `stol` dla nowej appki poza stołem dostaje 409 `nie_na_stole` (gdy zamówienie jest kompletne; pozycję
  zamówienia niekompletnego bramka przepuszcza, K3.12), a z kafla na stole — 200.
- **L46.5** Pole `sposob_dostawy_ustawiony` w podglądzie kolejki panelu zostaje jako informacja dla biura;
  `transport.mode` w API mobilnym dalej bywa `null`.
- **L46.6** Zwykła zmiana sposobu dostawy nie zmienia zbioru kandydatów Pakowania, więc nie wysyła sygnału; sygnał
  idzie tylko przy cofnięciu do pakowania (K3.38).
- **L46.7** Krok 4.6 nie ma migracji. Nowa appka zdejmuje własną blokadę ZAKOŃCZ przy pustym sposobie dostawy i
  pokazuje plakietkę „Sposób dostawy do ustalenia – pakuj normalnie” (kontrakt §6, §13); stara appka blokuje dalej po
  swojej stronie.

### 16.7 Lakiernia (wariant C)

- **LAK.1** Lakiernia (`painting`) nie ma stołu nigdy. Na serwerze decyduje o tym słownik
  `ustawienia.STANOWISKA_BEZ_STOLU` (kod → nazwa do komunikatu) w `priorytety/services/ustawienia.py` — jedno miejsce
  dla braku stołu, porządku listy i pola `grupa_wykonczenia`. Front ma kopie tej decyzji: stałą `STANOWISKA_BEZ_STOLU`
  w `priorytety.js` i warunek `kod == 'painting'` w karcie „Stół stanowisk” Konfiguracji; lista Lakierni w zakładce
  Stanowiska (`stations_api._lista_lakierni`) czyta kod `painting` wprost. (5.5 i 8.6 mówią o krotce w `stale.py`; w
  `stale.py` tej stałej nie ma)
- **LAK.2** `desk` i `postpone` dla Lakierni → 409 `stanowisko_bez_stolu` bez zapisu; `stol.wymagaj_stolu` odmawia też
  w serwisie („Wyślij”, „Zdejmij” — 409); `GET /kolejka?stanowisko=painting` i `PUT /ustawienia` z trybem `stol` →
  400; `GET /stoly` i `GET /start` jej nie zwracają; modal ma dla niej `w_kolejce: null` i nie ma „Wyślij”.
- **LAK.3** Bramka ZAKOŃCZ przepuszcza Lakiernię zawsze, niezależnie od `priorytety_tryb_painting` i wersji appki.
- **LAK.4** Klucz grupy wykończenia (`lista.klucz_grupy_wykonczenia`): `parsed_finish_type`,
  `parsed_finish_color_type`, `parsed_finish_color` i `parsed_finish_gloss` — połysk tylko dla lakierowanych — po
  normalizacji (bez spacji na brzegach, małe litery, pusty napis = brak); brak wartości jest osobną wartością klucza.
  (decyzja Konrada 5.10 „jak w appce”; plan K3 zakładał trzy pola)
- **LAK.5** `grupa_wykonczenia` w serializacji ma cztery pola `{rodzaj, typ_koloru, kolor, polysk}` i jest obiektem
  tylko wtedy, gdy pozycja jest serializowana dla stanowiska `painting`; inaczej `null`. (raport K3, rozstrz. 26)
- **LAK.6** Porządek listy (`lista.porzadek_listy`): pozycje w statusie Lakierni w grupach; grupy w kolejności
  najpilniejszej pozycji (doróbka — po `created_at` — przed wszystkim, potem `priority_rank` NULLS LAST, numer
  zamówienia, id); klucz kończy się id pozycji, więc remisu nie ma (rozjemca po nazwie grupy — rodzaj, typ koloru,
  kolor, połysk, brak wartości na końcu — jest w kodzie tylko zabezpieczeniem); cała grupa w jednym ciągu; pozycje w
  innych statusach na końcu, po (ranga, numer, id). Numer zamówienia porównywany jest tu tekstowo. (raport K3,
  rozstrz. 27)
- **LAK.7** Delta `/stations/painting/orders/since` oddaje `all_ids` i `changed` w tej samej kolejności; ETag listy
  bez zmian w budowie.
- **LAK.8** Monitor Lakierni: karty zamówień w kolejności pierwszego wystąpienia pozycji zamówienia na liście tabletu,
  z nazwą grupy wykończenia pierwszej pozycji; bez „TERAZ”, „Odłożone” i „Dalej w kolejce”. Zakładka Stanowiska:
  pierwsze 15 pozycji listy z nazwą grupy. Konfiguracja: wiersz „Lista (bez stołu)” bez pól.
- **LAK.9** Nazwa grupy dla ludzi (`lista.nazwa_grupy_wykonczenia`): rodzaj · typ koloru · kolor · połysk z klucza
  grupy (małe litery, połysk tylko dla lakierowanych), puste pomijane; gdy wszystkie puste — „bez wykończenia”.
  (raport K4b, rozstrz. 7)
- **LAK.10** Ranga pozycji jest pamięcią podręczną, więc tagi terminowe i „Rozpoczęte” działają na liście Lakierni z
  opóźnieniem do najbliższego `utrwal()`. Stara appka (1.7.3) sortuje listę sama — porządek serwera widać od nowej
  appki.

### 16.8 Wyniki K5 (przegląd przed wdrożeniem, 5.10.2026)

Pełny opis, polecenia i liczby: `docs/superpowers/plans/raporty/2026-10-05-priorytety-krok-K5-raport.md`. Stan kodu:
`claude/priorytety-produkcji` @ `f7c47c9a`. Bazy: MySQL 8.4 w dockerze (jak produkcja: MySQL 8.4, REPEATABLE
READ), świeża kopia produkcji (1912 zamówień, 4397 pozycji, 255 zamówień aktywnych) i baza wyścigów z podglądu
programu.

- **K5.1 Testy.** Pełny pakiet 6818 passed / 3 skipped przed krokiem; `blog_seo` 89 passed; składnia Pythona 3.9
  dla 86 plików zmienionych w P1. Próbne scalenie z `main` (5 commitów spoza gałęzi): bez konfliktów, 6842 passed.
- **K5.2 Migracje.** Na kopii produkcji bez tabel logistyki runner wykonał 16 migracji (14 logistyki, druku
  i analiz, potem obie priorytetów) w 2,16 s, bez błędu; najdłuższe polecenie 0,21 s. Kolejne przebiegi: „Wykonano
  0 migracji”. Po migracji: 9 szczebli w kolejności 3.1, 38 wierszy `prod_config`, klucz obcy szczebla do
  `prod_routes`, rangi puste do pierwszego crona. Na bazie z wykonaną logistyką — to samo, dwa przebiegi bez zmian.
- **K5.3 Pierwszy cron.** 200 w 0,6 s; `szczeble_uzupelnione: 0`, `priorytety_utrwalone.success: true`, 255
  zamówień i 609 pozycji z rangą w 0,34 s; drugi przebieg bez zmian (0,02 s). Rangi unikatowe.
- **K5.4 Algorytm kontra symulacja** (`scripts/symulacja_priorytetow.py`, ten sam dzień, próg 3): ranga zamówień
  255/255; kolejki Wycinania, Składania, Sklejania i Krawędzi oraz kompletne i niekompletne Formatowania
  i Pakowania — identyczne; tagi identyczne.
- **K5.5 Kolejność zapytań** (`general_log`): `desk` z dopełnieniem i ZAKOŃCZ idą dokładnie tak, jak opisują K3.1,
  K3.19 i K3.20; blokada S ma w SQL postać `LOCK IN SHARE MODE`. W trybie `stary` `desk` nie zakłada żadnej
  blokady.
- **K5.6 Plany zapytań** (EXPLAIN na kopii produkcji, stół pusty, po starcie i pełny): żadne zapytanie blokujące
  nie skanuje tabeli. `utrwal` blokuje pozycje zakresem po `idx_order` — dokładnie pozycje zamówień z listy;
  `dopelnij` blokuje S własne zamówienia i ich pozycje (na czterech z sześciu stanowisk także jeden sąsiedni rekord
  zamówienia — blokada następnego klucza na końcu zakresu); ZAKOŃCZ czyta własny kafel po kluczu unikalnym,
  a wiersze stołu zamówienia po indeksie `order_id`. Indeks `ix_prod_station_desk_station_code` jest nadmiarowy wobec klucza
  unikalnego `(station_code, unit_key)` — do usunięcia w K8.
- **K5.7 Sygnały** przez prawdziwy broker: kanały z tokenu i zdarzenia jak w K3.8, K3.26, K3.27 i K3.38; po 409
  i po `desk` bez zmian sygnału nie ma. Broker zawieszony (przyjmuje połączenie, nie odpowiada) wydłuża ZAKOŃCZ
  z ok. 50 ms do ok. 1,5 s (dwa sygnały po 0,7 s); zatrzymany albo wyłączony w konfiguracji — bez narzutu.
- **K5.8 Start stołów** na kopii produkcji: 14 kafli rozpoczętych (Sklejanie 4, Formatowanie 9, Pakowanie 1);
  „Przygotuj stoły” 0,13 s, powtórka niczego nie dokłada; „Włącz stoły” jednym zapisem (przy progu wersji 0 —
  odmowa, K4b.21); wycofanie na `stary` jednym zapisem.
- **K5.9 Czasy** na kopii produkcji (255 zamówień aktywnych): `GET /kolejka` 26–41 ms, modal priorytetu 47–66 ms,
  zakładka Stanowiska 184–224 ms, `GET desk` 32–148 ms (304: 8–93 ms), ZAKOŃCZ 34–53 ms, dodanie przystanku trasy
  z przeliczeniem rang 234 ms. Progi z planów (1 s, 300 ms) nieprzekroczone.

**Wyścigi na MySQL** — nazwy trybów są kanoniczne (regresja po zmianach w blokadach odwołuje się do nich). Każdy
przebieg: N żądań startujących z bariery albo z losowym rozjazdem 0–15 / 0–40 ms; po przebiegu licznik zakleszczeń
InnoDB, log aplikacji, odpowiedzi 500 oraz niezmienniki: stół bez duplikatów, bez kafli nieaktualnych, bez
niekompletnych kafli-zamówień; rangi w punkcie stałym (drugie dodatkowe `utrwal` niczego nie zmienia).

| Tryb | Strony wyścigu | Przebiegi | Wynik |
|---|---|---|---|
| `desk-desk` | dwa tablety, pusty stół | 62 | 200/200, stół 2 kafle |
| `desk-zakoncz-inne` | ZAKOŃCZ kafla A ↔ `desk` | 62 | 200/200; stół bywa o 1 krótszy do następnego `desk` |
| `gwiazdki-zakoncz` | gwiazdki zamówienia ↔ ZAKOŃCZ jego kafla | 62 | 200/200 |
| `szczebel-przystanek` | przesunięcie szczebla ↔ dodanie przystanku | 62 | 200/200 |
| `utrwal-dostawa` (+ wariant `-b`) | gwiazdki ↔ „Zakończ załadunek” | 62 + 10 | 200/200; wariant b: 200 / 409 `loading_incomplete` |
| `odloz-zakoncz-ten-sam-kafel` | Odłóż ↔ ZAKOŃCZ tego samego kafla | 62 | 409 `nie_na_stole` / 200 albo 200 / 200 |
| `desk-zakoncz-to-samo-zamowienie` | ZAKOŃCZ P1 ↔ `desk` (P2 kandydat) | 30 | 200/200 |
| `desk-dorobka` | doróbka z Formatowania ↔ `desk` | 30 + 30 | 200/200; doróbka wraca na Wycinanie albo Składanie (pierwsza seria: 9 × 400 `invalid_quantity` z danych testu, powtórzona — 30 × 200/200) |
| `desk-panel-sposob` | zmiana sposobu dostawy ↔ `desk` Pakowania | 30 | 200/200 |
| `odloz-odloz` | dwa Odłóż przy limicie | 30 | oba 200 (limit miękki) albo jedno 409 `limit_odlozen` |
| `odloz-zakoncz`, `odloz-hurt` | Odłóż ↔ ZAKOŃCZ innego kafla / hurt statusu | 30 + 30 | 200/200 |
| `zakoncz-zakoncz-ten-sam-kafel`, `zakoncz-zakoncz-formatowanie`, `zakoncz-zakoncz-pakowanie` | dwa ZAKOŃCZ tej samej pozycji, tryb `stol` | 3 × 30 | zawsze 200 + 409 `pozycja_poza_stanowiskiem` |
| `zakoncz-zakoncz-stary` | to samo w trybie `stary` | 20 | 200 + 200, status przesunięty raz |
| `hurt-desk` | hurt statusu 20 pozycji ↔ `desk` | 30 | 200/200 |
| `wyslij-desk`, `wyslij-zakoncz`, `wyslij-zakoncz-stary`, `wyslij-przywroc-zakoncz`, `wyslij-zakoncz-inne` | „Wyślij” ↔ `desk` / ZAKOŃCZ | 4 × 30 + 50 | 200/200 albo 409 `brak_na_stanowisku` / 200 |
| `zdejmij-zakoncz`, `zdejmij-odloz` | „Zdejmij” ↔ ZAKOŃCZ / Odłóż | 30 + 30 | 200 / 409 `nie_na_stole`, 404 `brak_kafla` / 200 albo 200 / 200 |
| `przygotuj-zakoncz`, `przygotuj-desk` | „Przygotuj stoły” ↔ ZAKOŃCZ / `desk` | 30 + 30 | 200/200 |
| `utrwal-utrwal` | dwa przeliczenia naraz | 30 | oba `success` |
| `weryfikacja-cofnij-desk` | „Cofnij do pakowania” ↔ `desk` Pakowania | 30 | 200/200 |
| `wyslij-wyslij` | dwa „Wyślij” na puste stoły różnych stanowisk | 30 | 200/200; **8 × 1213 z udanym ponowieniem** |
| `desk-stary-zakoncz`, `wlacz-stoly-desk` | `desk` w `stary` ↔ ZAKOŃCZ; „Włącz stoły” ↔ dwa `desk` | 30 + 30 | 200 |
| `ustawienia-ustawienia` | dwa `PUT /ustawienia` | 20 | brakujący wiersz klucza: 200 + 500 `blad_serwera` (9 z 10); istniejące: 200 + 200 |
| `desk-utrwal` (kopia produkcji) | hurt gwiazdek 20 zamówień ↔ sześć `desk` | 30 | 7 × 200 |

Razem 34 tryby i 1222 przebiegi: **zero zakleszczeń bez ponowienia i zero złamanych niezmienników**. Do tego: trzy
próby obciążeniowe (16 wątków mieszanego ruchu, 3879 żądań) bez 1213, 1205 i 500; regresja wyścigów logistyki
4.4a/4.4b (12 trybów × 10) bez zmian wyniku; seria potwierdzająca po poprawce skryptu wyścigów (8 trybów × 12 =
96 przebiegów, poza sumą 1222) — wyniki bez zmian.

- **K5.10 Drugi ZAKOŃCZ tej samej pozycji** (pytanie z planów K3 i K5): w trybie `stol` i dla nowej appki zawsze 409
  `pozycja_poza_stanowiskiem`, bez wpisu idempotencji; w trybie `stary` 200 bez ponownej zmiany statusu (K3.42).
- **K5.11 „Wyślij” na puste stoły.** Dwa „Wyślij” naraz na różne stanowiska przy pustej tabeli stołów zakleszczają
  się na luce indeksu unikalnego (oba odczyty bieżące własnego kafla trafiają w tę samą lukę); router ponawia raz
  i oba kończą się 200 (K3.30).
- **K5.12 Limit czekania.** `utrwal()` wołane z niezatwierdzonym zapisem zamówienia wraca po 5,0–5,2 s
  z `success: False`; `desk` czekający na cudzą blokadę wraca z 200 bez dopełnienia po ok. 5,1 s, a gdy czekania
  się sumują (blokada stanowiska, potem zamówienie — K3.21) — później: zmierzone do 9,1 s (K1.24). Czekający
  `desk` trzyma już blokady S zamówień o niższych id, więc ZAKOŃCZ kafla takiego zamówienia może czekać razem
  z nim (zmierzone do 5,1 s).
- **K5.13 Kafel-widmo.** Po hurtowym usunięciu pozycji kafel `p:` znika kaskadą klucza obcego, kafel `o:` zostaje,
  zajmuje miejsce na stole i jest widoczny dla biura w `widma` (K3.33, K4b.17).
- **K5.14 Dwa zapisy ustawień naraz.** Kończą się jednym 500 tylko wtedy, gdy oba zakładają ten sam brakujący
  wiersz `prod_config` (K2.8); powtórka przechodzi.
- **K5.15 Import.** Ręczna synchronizacja z Base. na kopii produkcji: 200 w 0,14–0,20 s, nowe zamówienie od razu
  z rangą i terminem, sygnały `cutting` i `assembly`. Ścieżka crona importu (`sync-cron`) kończy się 500 po zapisie
  zamówień — usterka zastana, niezwiązana z priorytetami; cron importu nie jest uruchamiany.

### 16.9 Miejsca w sekcjach 1–15 zmienione przez realizację

Każdy wiersz odpowiada znacznikowi „(K5 → 16.9 Znn)” w treści sekcji 1–15. Kolumna „Fragment” to dosłowny
początek nieaktualnego zdania; „Obowiązuje” — stan kodu z odesłaniem do punktów 16.1–16.8. Sekcja 1.1 („Jak jest”)
i numery linii w 4.2 i 9.5 opisują punkt wyjścia sprzed realizacji i nie mają znaczników.

| Nr | Sekcja | Fragment | Obowiązuje |
|---|---|---|---|
| Z01 | nagłówek | `` **Gałąź:** `claude/logistyka-etap-4` (stan `3c50cc8d`) `` | (K5) Realizacja K1–K6 na gałęzi `claude/priorytety-produkcji` (odbitej od `claude/logistyka-etap-4`, z logistyką 4.6); na produkcję jednym wdrożeniem z logistyką (ustalenie 16). |
| Z02 | 2, ustalenie 3 | `Na drabinie są też **tagi**: „Po terminie” i „Blisko terminu”` | (K5) Doszedł trzeci tag „Rozpoczęte” (ustalenie 13; 3.1, 5.6). |
| Z03 | 2, ustalenie 9 | `(pozycje dostępne na danym stanowisku): gatunek i klasa, potem grubość` | (K5) Zastąpione ustaleniem 14 i regułą 3.2: grupy materiału idą w kolejności najbliższego terminu w grupie, a w grupie termin stoi przed długością — K1.17, K1.18. |
| Z04 | 2, numeracja ustaleń | `14. **Decyzje po symulacji na produkcji (Konrad 5.10):**` | (K5) Punkt 14 dopisano później niż 13, ale wstawiono go nad nim; numerów nie zmieniamy, bo odwołują się do nich plany i raporty kroków. |
| Z05 | 2, ustalenie 17 | `(licznik sztuk z tabletu > 0 — zawężone przez Konrada po bramce K3)` | (K5) Kod patrzy na sam licznik pozycji czekającej na stanowisku i nie sprawdza jego źródła (uzasadnienie przy 5.8, Z28) — K3.34. |
| Z06 | 3.2, zamówienia p. 3 | `` najmniejszy `deadline_date` niezanulowanych pozycji, jak w panelu Logistyki `` | (K5) W kodzie: najmniejszy `deadline_date` pozycji AKTYWNYCH (w statusach produkcji), jak w 4.2 — 16.1 K1.1. |
| Z07 | 3.2 „Kafle na stanowisku zamówieniowym” | `zamówienia w kolejności rangi zamówienia; pozycje` | (K1) Kolejność liczy klucz rangi (szczebel z kolumny `priority_rung` z tagiem „Rozpoczęte” doliczonym na żywo, gwiazdki, termin, numer), nie goła kolumna `priority_rank`; zamówienie z doróbką czekającą na tym stanowisku idzie pierwsze — K1.4. |
| Z08 | 3.2 „Lista Lakierni” p. 2 | `` `priority_rank` rosnąco NULLS LAST, numer zamówienia, `id`) — `` | (K5) Na liście Lakierni numer zamówienia porównywany jest tekstowo (jak w dotychczasowym porządku listy z SQL); w kolejce stołu — liczbowo (K1.27, LAK.6). |
| Z09 | 3.2 „Lista Lakierni” p. 3 | `przy remisie rodzaj, kolor, połysk alfabetycznie` | (K5) Przy remisie po czterech polach klucza: rodzaj, typ koloru, kolor, połysk; brak wartości na końcu (LAK.6). |
| Z10 | 4.1 „Szczebel” | `` `tag` (`po_terminie`, `blisko_terminu`) albo `route` `` | (K5) Tagi są trzy: `po_terminie`, `blisko_terminu`, `rozpoczete` (jak 3.1 i 8.2). |
| Z11 | 4.1 „Termin zamówienia” (kontra 4.2) | `` min `deadline_date` niezanulowanych pozycji (liczony, nie przechowywany) `` | (K5) Jak w 4.2: pozycji AKTYWNYCH (w `STATUSY_PRODUKCJI`), nie wszystkich niezanulowanych — K1.1. |
| Z12 | 4.1 „Ranga pozycji” | `` ranga zamówienia × 100 + `product_sequence_in_order` `` | (K5) Kolejność pozycji przycięta do 0–99 — K1.28. |
| Z13 | 4.2, `policz` | `rangi zamówień 1..M po klucz; priority_rung = position` | (K1) `priority_rung` to indeks od 1 wśród szczebli WIDOCZNYCH (po ukryciu tras załadowanych, w trasie i wykonanych; ze szczeblami wirtualnymi), nie wartość kolumny `position` — dotyczy też 4.1 i 8.1; K1.5, K1.29. |
| Z14 | 4.2, `utrwal()` | `każdą tabelę jednym flushem rosnąco po id; commit; po MySQL 1213 jedno` | (K5) Dodatkowo: przebieg kontrolny po każdym zapisie (najwyżej 3 przebiegi) i limit czekania na blokadę 5 s na przypiętym połączeniu (1205 → `success: False` bez ponowienia) — K1.23, K1.24. |
| Z15 | 4.3 | `Zakładka Konfiguracja, grupa „Terminy” (dziś „priorities”)` | (K5) Od K4b wszystkie klucze terminów (`DEADLINE_DEFAULT_DAYS` i `DEADLINE_FINISHED_DAYS` — zakres 1–90 — oraz `DEADLINE_DAY_TYPE`) zapisuje z panelu wyłącznie `PUT /production/api/priorytety/ustawienia`; `update-config` i `update-configs` ich nie przyjmują. Wyjątkiem jest `POST /production/api/reset-configs` (bez przycisku w UI), który przywraca je do wartości domyślnych `config_service` (16, 21, `robocze`) bez wpisu w logu priorytetów — K4b.5, K4b.14. |
| Z16 | 4.4, wiersz `routes.usun` | `` FK `ON DELETE CASCADE`. `` | (K5) `routes.usun` woła też `drabina.usun_szczebel_trasy` pod trzymaną blokadą tras (renumeracja od razu) — K1.13. |
| Z17 | 4.5 | `termin = brak → sortują się na końcu swojego szczebla; tagi nie działają` | (K5) Nie działają tagi terminowe; tag „Rozpoczęte” liczy się ze statusów także bez terminu — K1.6. |
| Z18 | 5.1 | `` dla Wycinania, Składania, Sklejania, Krawędzi, Lakierni; `zamowienie` dla Formatowania i Pakowania `` | (K5) Lakiernia nie ma stołu (ustalenie 15): klucz `priorytety_jednostka_painting` zostaje w `prod_config` (8.6), ale poza odczytem i zapisem ustawień nic go nie używa. |
| Z19 | 5.2 | `Pobieranie jest **leniwe, przy odczycie**` | (K5) Dopełnianie działa wyłącznie w trybie `stol`; w `stary` `desk` tylko czyta (6.3, K3.40) — dotyczy też pierwszego zdania 6.1. |
| Z20 | 5.2, odczyt kandydatów | `` bieżącym (`with_for_update(read=True).populate_existing()`, pozycje w statusie stanowiska poza stołem i odłożeniami, `` | (K3/K5) Odczyt bieżący idzie w kolejności kanonicznej: zamówienia z pozycją w statusie stanowiska — blokada S (`with_for_update(read=True)`, na MySQL `LOCK IN SHARE MODE`) rosnąco po id — potem tak samo WSZYSTKIE pozycje tych zamówień (`ORDER BY order_id, id`); wiersze stołu zwykłym odczytem — K3.1, K3.19. |
| Z21 | 5.3 | `„Na Sklejaniu leży 10 odłożonych zamówień. Zamknij któreś, zanim odłożysz kolejne.”` | (K5) Komunikat odmienia liczbę i nazwę jednostki (na Sklejaniu: „…10 odłożonych pozycji. Zamknij którąś, zanim odłożysz kolejną.”); limit jest miękki — K3.13, K3.24. |
| Z22 | 5.3 | `Nie ma „Przywróć” — odłożony kafel i tak jest na tablecie` | (K3) Wyjątek opisany w 5.7: „Wyślij na stanowisko” przywraca odłożony kafel na stół — to jedyne „przywróć” i robi je biuro, nie tablet — K3.28. |
| Z23 | 5.4, tabela sygnałów | `zdjęcie kafla przez biuro/Base./doróbkę` | (K5) Poza tabelą sygnał idzie też: `station:packaging` po „Cofnij do pakowania” (Weryfikacja), po zmianie sposobu dostawy cofającej do pakowania i gdy cron przeniesie osierocone pozycje do pakowania; `station:cutting` i `station:assembly` po imporcie nowych zamówień; po doróbce także na stanowisko powrotu; po hurtowej zmianie statusu na stanowisko nowego statusu; po zmianach z Base. na Wycinanie, gdy doszła pozycja. W `with_idempotency` sygnały stanowisk idą pierwsze po commicie, przed statusem Base. — K3.8, K3.38, K3.39. |
| Z24 | 5.4, siatka odpytywania | `` tablet z pustym stołem odpytuje `desk` co 30 s; tablet ze stołem — co 5 min `` | (K6/K5) Kontrakt appki: co 30 s, gdy na stole leży mniej kafli niż `miejsca`, co 5 min w pozostałych przypadkach; w trybie `stary` `desk` najwyżej co 30 s, tylko żeby wykryć przełączenie (dotyczy też 5.2, 6.4 p. 4 i P-7) — K3.43. |
| Z25 | 5.5 | `` serwer przyjmuje ZAKOŃCZ i `PATCH quantity` tylko dla kafla **na stole albo odłożonego** tego `` | (K3/K5) Najpierw bramka statusu: pozycja, która nie czeka na tym stanowisku → 409 `pozycja_poza_stanowiskiem` (K3-poprawka-2). Bramka stołu przepuszcza też pozycję zamówienia NIEKOMPLETNEGO na stanowisku zamówieniowym (sekcja „Niekompletne” nie ma wiersza stołu) — K3.12, K3.41. |
| Z26 | 5.5 | `Nowa appka tego błędu nie zobaczy` | (K6/K5) Nowa appka może dostać oba 409 z kolejki offline (akcja dosłana po zdjęciu kafla albo po zmianie statusu pozycji); reguły porzucania i ponawiania — kontrakt §10, K3.42. |
| Z27 | 5.5 | `` stanowisko jest w stałej `STANOWISKA_BEZ_STOLU = ('painting',)` `` | (K5) W kodzie to słownik `ustawienia.STANOWISKA_BEZ_STOLU` (kod → nazwa do komunikatu) w `priorytety/services/ustawienia.py`, nie krotka w `stale.py` — LAK.1. |
| Z28 | 5.8 | `` która ma licznik `quantity_done_<S>` > 0 (z tabletu); `` | (K5) Kod nie sprawdza źródła licznika. Pominięcie automatyczne (`auto_skip`, `system` w `complete_task`) wpisuje licznik stanowiska omijanego w chwili, gdy pozycja je mija, więc samo nie tworzy kafla startowego; licznik S pozycji czekającej na S pochodzi zwykle z tabletu, ale bywa też ręczną korektą z panelu albo zostaje po cofnięciu statusu hurtem (to samo w punkcie o jednostce `zamowienie`) — K3.34. |
| Z29 | 5.8 | `` Źródło „ręcznie”: `prod_station_events` (`ProductionStationEvent`, pole źródła zdarzenia) — plan `` | (K5) Nieaktualne: po K3-poprawce-1 start stołów nie czyta `prod_station_events` (K3.34). |
| Z30 | 5.8, krok 4 | `` 4. **Włącz** (admin, przed rozpoczęciem zmiany): `priorytety_min_app_version_code` = kod nowej appki i `` | (K5) `PUT /ustawienia` odmawia włączenia `stol` przy progu wynikowym 0 (400 `prog_wersji_wymagany`), więc próg trzeba podać w tym samym zapisie albo wcześniej — K4b.21. |
| Z31 | 6.1, pole `priorytet` | `priorytet: {gwiazdki, szczebel: "trasa"` | (K5) `szczebel` przyjmuje też `"rozpoczete"` i `null`; `pozycja_w_zamowieniu` bywa `null`; kafel-zamówienie ma `priorytet` bez `pozycja_w_zamowieniu` — K3.4, K3.5, K3.16. |
| Z32 | 6.1 | `` Stół może mieć **więcej niż `miejsca`** kafli (doróbki, wysłane przez biuro, startowe `` | (K5) Od K3-poprawki-1 doróbki wchodzą w ramach K — ponad `miejsca` stół wychodzi przez kafle `biuro` i `start`, a poza tym tylko chwilowo po obniżeniu K w Konfiguracji (nadmiaru nikt nie zdejmuje, dopełnianie po prostu nie dobiera) — K3.35. |
| Z33 | 6.1, ETag | `` ETag jak w liście (max `updated_at` + liczba + `KSZTALT`) `` | (K5) ETag stołu jest szerszy (liczniki sztuk, gwiazdki, wiersze stołu, ustawienia, tryb, `KSZTALT_ODPOWIEDZI_STOLU` = 2), a odpowiedź ma `Cache-Control: private, max-age=0` — K3.6, K3.14. |
| Z34 | 6.2 | `` Odpowiedzi: 200 ze stołem jak w 6.1; 409 `limit_odlozen`; 409 `nie_na_stole` `` | (K5) 200 oddaje stół BEZ dopełnienia (dopełnia następny `GET desk`); dochodzą 400 `dane_niepoprawne` (zły `zakres` albo typy, notatka ponad 255 znaków, `zakres` niezgodny z jednostką stanowiska), 409 `stanowisko_bez_stolu` i 404 `order_not_found`; `<id>` w ścieżce to zawsze id pozycji — K3.7, K3.22. |
| Z35 | 6.3 | `` `{enabled, token, ttl_seconds, sse_url, channels}`; 503 gdy realtime wyłączony `` | (K3) 503 ma ciało `{enabled: false, reason}` (także przy błędnej konfiguracji brokera); urządzenie spoza stanowisk z kolejką produktów dostaje 404 `unknown_station` — K3.27. |
| Z36 | 6.4 p. 5 | `` 5. Kolejka offline jak dotąd; 409 `nie_na_stole` → komunikat i odświeżenie stołu (kafel zamknął inny tablet). `` | (K5) Dochodzi 409 `pozycja_poza_stanowiskiem` (appka porzuca wpis po polu `error`); pełne reguły kolejki offline — kontrakt §10. |
| Z37 | 7.1 | `` historia gwiazdek z `prod_priority_log` `` | (K4a) Sekcja „Historia” pokazuje też akcje stołu zamówienia: `wyslanie`, `zdjecie`, `odlozenie`, `odlozenie_zamkniete`; „Wyślij” jest przy każdym stanowisku zamówienia poza Lakiernią, a „Zdejmij” także przy kaflu odłożonym — K4a.5, K4a.15. |
| Z38 | 7.1 | `przeciągalne (strzałki ↑↓ jako zapas)` | (K4a) Zrobione same strzałki ↑↓ (zapis z `oczekiwane`, 409 `drabina_zmieniona` → odczyt od nowa); przeciągania nie ma — K4a.8. |
| Z39 | 7.1 | `**Kolejność kart** = ranga zamówienia (dziś termin)` | (K4a/K4-poprawka-1) Ranga z `GET /kolejka` (liczona na żywo); gdy nie odpowie — sort po terminie z ostrzeżeniem. Hurt „Ustaw gwiazdki” pyta o potwierdzenie przy zdjęciu gwiazdek albo ponad 10 zamówieniach — K4a.2, K4a.7. |
| Z40 | 7.2 | `**Logistyka:** kolumna „★” z wyborem 0–5 (ten sam komponent)` | (K4a/K4-poprawka-1) Kolumna chowa się, gdy kontener tabeli ma najwyżej 1035 px; na zamówieniach zamkniętych, anulowanych i wydanych gwiazdki są tylko do odczytu — K4a.11. |
| Z41 | 7.2 | `pierwsze 15 kafli kolejki; „Zdejmij ze stołu” przy kaflu (5.7)` | (K4b) Zakładka pokazuje też sekcję „Do zdjęcia ze stołu” (widma — wiersze stołu bez kafla do pokazania) i podpis o powrocie kafla przy dopełnieniu — K4b.17, K4b.18. |
| Z42 | 7.2 | `gwiazdki i plakietki (krok P3)` | (K4b) Monitory zrobione w K4b (jedno wdrożenie, ustalenie 16): czytają kolumny rangi i nie dopełniają stołu; „TERAZ” i „Odłożone” rysują się tylko niepuste, „Dalej w kolejce” tylko w trybie `stol` — K4b.8–K4b.10, K4b.20. |
| Z43 | 8.6 | `bramka starej appki (0 = brak bramki)` | (K5) Próg 0 = bramka wersji wyłączona: w trybie `stol` bramka stołu obowiązuje wtedy każdy tablet. Z panelu nie da się włączyć `stol` przy progu 0 (400 `prog_wersji_wymagany`) — K3.3, K4b.21. |
| Z44 | 8.6 | `` `STANOWISKA_BEZ_STOLU = ('painting',)` w `priorytety/stale.py` `` | (K5) W kodzie: słownik `ustawienia.STANOWISKA_BEZ_STOLU` w `priorytety/services/ustawienia.py` — LAK.1. |
| Z45 | 8.7 | `` ### 8.7 Migracja `2026-10-XX-priorytety-produkcji.sql` `` | (K5) Dwie migracje: `2026-10-05-priorytety-produkcji.sql` (K1 — kolumny `prod_orders`, tabele drabiny, logu i stołu, seed drabiny, 38 wierszy `prod_config`) i `2026-10-06-priorytety-stol-zrodlo.sql` (K3 — `zrodlo`, `sent_by_user_id`, trzy akcje logu) — K1.36, K3.32. |
| Z46 | 9.1 | `├── templates/priorytety/` | (K4a/K5) Katalog nie powstał — modale buduje `static/js/priorytety.js` jako `<dialog>`. Pakiet ma dodatkowo `services/widok.py` (odczyty panelu, `wejscie_kandydatow`) i `services/lista.py` (porządek listy Lakierni) — K4a.1. |
| Z47 | 9.2 | `` `kolejka.kandydaci_stanowiska(S, pozycje, statusy_zamowien)` — czysta `` | (K5) W kodzie sześć parametrów: `stanowisko`, `pozycje`, `statusy_zamowien`, `szczebel_rozpoczete=None`, `jednostka=None`, `omijajace=None`; `statusy_zamowien` to słownik id zamówienia → pary `(product_id, status)` WSZYSTKICH jego pozycji, a wejście buduje `widok.wejscie_kandydatow` — K1.3, K2.7. |
| Z48 | 9.2 | `` (router) → `sygnaly.zaplanuj(S)`; ponowienie po 1213 w routerze. `` | (K5) Router `desk` woła `sygnaly.wyslij(S)` po własnym commicie i tylko wtedy, gdy dopełnienie coś pobrało; czeka na blokadę najwyżej 5 s (1205 → 200 bez dopełnienia) — K3.21, K3.26. |
| Z49 | 9.2, `stol.odloz` | `sprawdza limit odczytem bieżącym stołu stanowiska,` | (K3/K5) Limit liczony zwykłym `COUNT` (migawka żądania); blokowany jest tylko wiersz własnego kafla — limit miękki, dwa jednoczesne Odłóż mogą go przekroczyć o 1 — K3.13. |
| Z50 | 9.2, `stol.zdejmij_kafel` | `` DELETE wiersza stołu; woła ją `complete_task`-owy pisarz `` | (K3/K5) Kontraktem pisarzy jest `stol.zdejmij_nieaktualne(order)` — uzgadnia wszystkie wiersze stołu zamówienia pod jego blokadą X; `zdejmij_kafel` istnieje w `stol.py`, ale kod produkcyjny go nie woła — K3.2. |
| Z51 | 9.2 | `` `stol.bramka_zakoncz(item, S, device)` — tryb `stary`/wersja appki → przepuść `` | (K3/K5) Kolejność w kodzie: Lakiernia, tryb `stary` i stara appka → przepuść; pozycja nie czeka na stanowisku → 409 `pozycja_poza_stanowiskiem`; kafel na stole albo odłożony → przepuść; pozycja niekompletnego zamówienia na stanowisku zamówieniowym → przepuść; inaczej 409 `nie_na_stole` — K3.12, K3.41. |
| Z52 | 9.3, wiersz „import z Base.” | `` `sync_service` (`:933`, `:3033`) `` | (K1) Oba wywołania idą do P4 przez warstwę zgodności `priority_service`; wprost przepina je K8 — K1.12. |
| Z53 | 9.3 | `**codziennie o północy i co godzinę w cronie**` | (K5) Jest jeden wyzwalacz czasowy: cron logistyki co godzinę (`szczeble_uzupelnione`, `priorytety_utrwalone`); osobnego przebiegu o północy kod nie ma — kolumny rang (stół, tablety, monitory, lista Lakierni) dostają nowe tagi terminowe przy pierwszym przeliczeniu po północy, najpóźniej w pierwszym przebiegu crona, a panel biura liczy tagi na żywo. Poza tabelą przeliczają też: „Wydane klientowi” (panel Logistyki), każda akcja trasy idąca przez `trasy_api._akcja` (także edycja trasy i zmiana kolejności przystanków), „Cofnij do pakowania” (Weryfikacja) i `PUT /ustawienia` przy zmianie progu „Blisko terminu”. W API mobilnym (Dostawa, Weryfikacja) handler tylko planuje przeliczenie, a wykonuje je dekorator po commicie — K1.13, K1.14, K1.35, K2.8. |
| Z54 | 9.4 | `` `utrwal()`: zamówienia `FOR UPDATE` rosnąco → pozycje rosnąco → zapisy zmienionych `` | (K1/K3) Plus przebieg kontrolny po zapisie i limit czekania 5 s (1205 bez ponowienia) — K1.23, K1.24. |
| Z55 | 9.4 | `` Nie bierze blokad zamówień (czyta `FOR SHARE` pozycje wielu zamówień `` | (K3/K5) `dopelnij` bierze blokady S (`with_for_update(read=True)`, na MySQL `LOCK IN SHARE MODE`): najpierw zamówienia rosnąco po id, potem ich pozycje (`ORDER BY order_id, id`) — kolejność kanoniczna wszystkich pisarzy; blokadę X bierze tylko na wierszu `priorytety_blokada_<S>` (i na wstawianych wierszach stołu), nie na zamówieniach ani pozycjach. „Wyślij” i „Zdejmij” czytają do tego własne kafle odczytem bieżącym po kluczu unikalnym. Dopełnienie czeka na cudzą blokadę najwyżej 5 s — K3.1, K3.19, K3.21. |
| Z56 | 9.5 | `` filtr `priority_range` → gwiazdki `` | (K4a) Filtr `priority_range` został bez zmian (nikt go nie czyta); usuwa go K8 — K4a.13. |
| Z57 | 9.5 | `` wywołania przeliczenia → `kolejka.utrwal()` `` | (K1) Przez warstwę zgodności `priority_service` do P4 — K1.12. |
| Z58 | 9.5 | `` w `complete`/`quantity`: `stol.bramka_zakoncz`, `stol.zdejmij_kafel`, `sygnaly.zaplanuj` `` | (K5) `complete` woła `stol.zdejmij_nieaktualne`; `quantity` ma tylko bramkę i sygnał (kafla nie zdejmuje) — K3.2, K3.20. |
| Z59 | 9.5 | `po commicie wysyła także sygnały stanowisk (obok sygnału druku i dopychacza Base.)` | (K3/K5) Kolejność haków po commicie: sygnały stanowisk (pierwsze), status Base., sygnał agenta druku, dopychacz logistyki, zaplanowane przeliczenie rang (`kolejka.wykonaj_zaplanowane`) — K3.39, K1.14. |
| Z60 | 10 | `` ZAKOŃCZ/licznik kafla poza stołem w trybie `stol` (nowa appka) `` | (K5) Nowy wiersz tabeli: ZAKOŃCZ albo licznik pozycji, która nie czeka na tym stanowisku, w trybie `stol` (nowa appka) → 409 `pozycja_poza_stanowiskiem` przed bramką stołu; niezapamiętywane, appka porzuca wpis po polu `error` — K3.41, K3.42. |
| Z61 | 10 | `ustawienia: K poza 1–5, limit poza 1–50, jednostka spoza listy, nieznane stanowisko` | (K5) Odmowy 400 mają kod i — poza ciałem, które nie jest obiektem JSON — pole `pole` ze ścieżką w ciele: `ustawienie_niepoprawne` (wartość poza zakresem albo spoza listy: K 1–5, limit 1–50, próg „Blisko terminu” 0–15, dni terminu 1–90, próg wersji od 0, jednostka, tryb, typ dni), `stanowisko_nieznane`, `dane_niepoprawne` (nieznane pole, zły kształt), `stanowisko_bez_stolu` (tryb `stol` dla Lakierni) i `prog_wersji_wymagany` (włączenie `stol` przy progu wersji 0 albo obniżenie progu do 0 przy włączonym stole) — K2.8, K2.21, K4b.5, K4b.21. |
| Z62 | 10 | `500 z rollbackiem; tablet ponowi po 30 s` | (K5) Kod błędu `desk_failed`; przekroczony limit czekania 5 s (1205) nie jest błędem — 200 z bieżącym stołem bez dopełnienia (5.2) — K3.21, K3.23. |
| Z63 | 11, lista wdrożenia | `` **Po wdrożeniu P1 uruchom raz ręcznie** `scripts/cron_endpoint.sh POST /production/api/logistics/cron` `` | (K5) Listy wdrożenia spec nie powtarza: lista wejściowa do runbooka (czasy migracji, oczekiwana odpowiedź ręcznego crona, kontrole, start stołów, objawy i reakcje) jest w raporcie K5, sekcja „Wejście do runbooka K7”, a runbook jednego okna pisze K7. W skrócie: obie migracje priorytetów idą przed restartem razem z migracjami logistyki; po restarcie raz ręcznie cron logistyki (w odpowiedzi `szczeble_uzupelnione` i `priorytety_utrwalone` z `success: true`); po wdrożeniu wszystkie stanowiska są w `stary`, a próg wersji to 0 — nowa appka zostaje na liście; stoły włącza biuro („Przygotuj stoły”, potem „Włącz stoły”), a wycofuje tryb `stary` w Konfiguracji — 16.8. |
| Z64 | 11, „Wycofanie” | `appka nowa dalej pokazuje stół (działa)` | (K3-poprawka-2) Po przełączeniu na `stary` `desk` oddaje `tryb: "stary"` i przestaje dopełniać, a nowa appka wraca na listę przy najbliższym `desk` — po sygnale z innej akcji na stanowisku albo z siatki odpytywania: do 30 s przy niepełnym stole, do 5 min przy pełnym (sama zmiana trybu sygnału nie wysyła; kontrakt §9 i §12) — K3.40. |
| Z65 | 12 | `## 12. Kontrakt dla sesji appki (powstaje po P1)` | (K6/K5) Kontrakt powstał przed wdrożeniem (ustalenie 16): `docs/api-mobile-priorytety.md`; reguły po stronie appki — 16.3 K3.43. |
| Z66 | 13, lista testów | `stół (dopełnienie do K, doróbka ponad K, pakowanie bez sposobu` | (K5) Doróbka w ramach K (5.1, K3.35); pakowanie bez sposobu dostawy wchodzi na stół jak każde inne (16.6). |
| Z67 | 13, lista wyścigów | `` **MySQL:** migracja ×2; wyścigi: dwa `desk` naraz, `` | (K5) Pełna lista trybów wyścigów (nazwy kanoniczne) i wyniki — 16.8. |
| Z68 | 13, P-10 | `grupa = (rodzaj, kolor, połysk) — pola potwierdzone (Konrad 5.10)` | (K5) Obowiązuje klucz czteropolowy (rodzaj, typ koloru, kolor, połysk tylko dla lakierowanych) i reguła z 3.2 — potwierdzone przez Konrada 5.10 (ustalenie 15); LAK.4. |
| Z69 | 15 | `` `migrations/2026-10-XX-priorytety-produkcji.sql`, szablony modali `` | (K5) Migracje `2026-10-05-…` i `2026-10-06-…`; szablonów modali nie ma (modale buduje `priorytety.js`). |
