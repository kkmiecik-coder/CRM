# Obsługa biura i pełny przebieg zamówienia — CRM WoodPower po wdrożeniu 8.10.2026 (logistyka etapy 1–4 + 4.6, priorytety produkcji, appka 1.8.0)

- **Stan kodu:** gałąź wdrożeniowa `claude/wdrozenie-2026-10-08` = `5e944a55` (jeden squash logistyki 1–4 + 4.6 i priorytetów P1 na `main` @ `31a0b014`). Dokument czytał kod z worktree `priorytety-centrala` (zawiera tę samą treść kodu co squash plus późniejsze dokumenty).
- **Appka tabletów i telefonów:** 1.8.0, `versionCode` 44 (repo appki, gałąź `dev/priorytety-stol`). Kodu appki w repo CRM nie ma — nazwy przycisków appki pochodzą z kontraktu i specyfikacji; tam, gdzie to ma znaczenie, są oznaczone „(do sprawdzenia w przebiegu)”.
- **Dla kogo:** (1) Konrad — jak pracuje biuro, logistyk, hala, weryfikator i kierowca po 8.10; (2) agent Claude — scenariusz pełnego przebiegu na kopii produkcji (sekcja 10).
- **Zasada dokumentu:** opisane zachowanie jest zgodne z kodem i dokumentami źródłowymi (lista na końcu). Czego nie dało się potwierdzić w kodzie, ma dopisek **„(do sprawdzenia w przebiegu)”**.
- W tekstach UI piszemy „Base.”. Kilka starszych przycisków w panelu nadal ma na sobie pełną nazwę systemu (np. „Synchronizuj z Base.” na Dashboardzie, „Odśwież z Base.” w szczegółach zamówienia) — tu podane w wersji „Base.”.
- Dokument nie zawiera danych klientów, adresów IP, kluczy ani tokenów. Numery zamówień w przykładach są fikcyjne.

---

## 1. Mapa systemu w jednym rzucie

### 1.1 Kto, gdzie, czym

| Kto | Urządzenie | Gdzie pracuje | Co robi |
|---|---|---|---|
| **Biuro / admin** | komputer, przeglądarka | Panel produkcji: zakładki **Dashboard**, **Lista produkcyjna**, **Stanowiska**, **Archiwum**, **Logistyka**, **Trakownia**, **Raporty**, **Pracownicy**, **Konfiguracja** | import z Base., priorytety (gwiazdki, drabina), „Wyślij na stanowisko” / „Zdejmij ze stołu”, hurtowa zmiana statusu, wstrzymanie, poprawki z Base.; admin — Konfiguracja (terminy, stoły, start stołów) |
| **Logistyk** | komputer | Zakładka **Logistyka** → podzakładki **Dashboard** (lista + mapa), **Trasy**, **Flota** | sposób dostawy, adres i pinezka, trasy, „Wydane klientowi”, rozliczenia tras, flota i kierowcy |
| **Pracownicy stanowisk** | tablety Android (appka 1.8.0), na stanowisko 1–2 tablety | Wycinanie - mikro, Składanie - lite, Sklejanie, Formatowanie, Krawędzie (tablet Krawędzi obsługuje też Lakiernię), Lakiernia, Pakowanie | stół / lista, ZAKOŃCZ, licznik sztuk, Odłóż, odrzut sztuk (doróbka), druk etykiet produktów, okno paczek i etykiety paczek (Pakowanie) |
| **Weryfikator** | telefon (appka, stanowisko **Weryfikacja**, sekcja Biuro) | lista „Do weryfikacji” | skan paczek `P-…`, „Zweryfikuj wszystkie”, „Zgłoś problem”, cofnięcia, deklaracja paczek dla „BEZ PACZEK”, ponowny druk etykiet paczek |
| **Kierowca** | telefon/tablet (appka, stanowisko **Dostawa**, sekcja Dostawa) | „Moje trasy” | załadunek skanem, „Zostaje”, „Zakończ załadunek”, „Ruszam w trasę”, „Dostarczone” / „Niedostarczone”, cofnięcie ostatniego dostarczenia |
| **Monitory hali (TV)** | przeglądarka na telewizorze | `/production/stations/monitors/<kod stanowiska>` i zbiorczy `/production/stations/monitor` | tylko odczyt: „TERAZ n/K”, „Odłożone”, „Dalej w kolejce”, gwiazdki, plakietki |
| **Agent druku** | komputer na hali (hub), program `tools/print_agent/print_agent.py` | pobiera zadania z kolejki `prod_print_queue` | drukuje na dwóch drukarkach: `etykiety` (produkty 60×40) i `wysylka` (paczki 100×150) |
| **Cron serwera** | serwer | `POST /production/api/logistics/cron` co godzinę | zamknięcia cyklu logistyki, dopychanie Base., geokoder, uzupełnienie drabiny, przeliczenie rang |

### 1.2 Kody stanowisk (używane w API i w Konfiguracji)

| Kod | Nazwa w UI | Status pozycji, która tu czeka |
|---|---|---|
| `cutting` | Wycinanie - mikro | `czeka_na_wyciecie` |
| `assembly` | Składanie - lite | `czeka_na_skladanie` |
| `gluing` | Sklejanie | `czeka_na_sklejanie` |
| `formatting` | Formatowanie | `czeka_na_formatowanie` |
| `edges` | Krawędzie | `czeka_na_krawedzie` |
| `painting` | Lakiernia | `czeka_na_lakiernie` |
| `packaging` | Pakowanie | `czeka_na_pakowanie` |
| `verification` | Weryfikacja | (telefon; brak kolejki statusów) |
| `delivery` | Dostawa | (telefon kierowcy) |

### 1.3 Jednostka pracy na stanowisku

| Stanowisko | Kafel = | Stół | Uwagi |
|---|---|---|---|
| Wycinanie, Składanie, Sklejanie, Krawędzie | **pozycja** | tak (po „Włącz stoły”) | grupowanie po materiale w szczeblu |
| Formatowanie, Pakowanie | **zamówienie** | tak | na stół wchodzą tylko zamówienia **kompletne**; niekompletne w sekcji „Niekompletne” |
| Lakiernia | pozycja (lista) | **nigdy** — zawsze lista | lista ułożona po grupach wykończenia; ZAKOŃCZ bez bramki |

### 1.4 Dwa tryby stanowiska

| Tryb (`priorytety_tryb_<S>`) | W Konfiguracji | Tablet z nową appką | ZAKOŃCZ |
|---|---|---|---|
| `stary` | „zgodność (stara appka)” | dzisiejsza lista całej kolejki | bez bramki (jak przed wdrożeniem) |
| `stol` | „stół” | ekran stołu: Teraz / Odłożone / Niekompletne | bramka statusu i stołu (tylko dla nowej appki) |

Po wdrożeniu **wszystkie stanowiska są w `stary`**, próg wersji appki = 0. Stoły włącza admin („Start stołów”, sekcja 3.8).

---

## 2. Cykl życia zamówienia i pozycji

### 2.1 Statusy pozycji (`prod_products.current_status`)

| Status | Nazwa w UI | Kto ustawia / skąd |
|---|---|---|
| `czeka_na_wyciecie` | Czeka na wycięcie | import z Base. (technologia **mikrowczep**); doróbka, gdy oryginał był cięty; hurt statusu |
| `czeka_na_skladanie` | Czeka na składanie | import (technologia **lity**); doróbka, gdy oryginał był składany; hurt |
| `czeka_na_sklejanie` | Czeka na sklejanie | ZAKOŃCZ na Wycinaniu albo Składaniu; hurt |
| `czeka_na_formatowanie` | Czeka na formatowanie | ZAKOŃCZ na Sklejaniu (pozycja z docięciem); hurt |
| `czeka_na_krawedzie` | Czeka na krawędzie | ZAKOŃCZ na Formatowaniu (pozycja z obróbką krawędzi); hurt |
| `czeka_na_lakiernie` | Czeka na lakiernię | ZAKOŃCZ na Formatowaniu (bez obróbki krawędzi, olejowane/lakierowane) albo na Krawędziach (olejowane/lakierowane); hurt |
| `czeka_na_pakowanie` | Czeka na pakowanie | ZAKOŃCZ na Sklejaniu (bez docięcia), Formatowaniu (bez krawędzi, surowe), Krawędziach (surowe), Lakierni; „Cofnij do pakowania” (Weryfikacja, Logistyka); hurt |
| `spakowane` | Spakowane (etap zamówienia: „Spakowane — czeka na weryfikację”) | ZAKOŃCZ na Pakowaniu; hurt; cofnięcie weryfikacji |
| `zweryfikowane` | Zweryfikowane | **tylko logistyka**: ostatnia paczka zweryfikowana na telefonie; zejście z trasy zamówienia zweryfikowanego |
| `zaladowane` | Załadowane | **tylko logistyka**: „Zakończ załadunek” (telefon kierowcy) |
| `dostarczone` | Dostarczone | **tylko logistyka**: „Dostarczone” (telefon), „Odhacz jako dostarczoną” (panel), „Wydane klientowi” (odbiór) |
| `wstrzymane` | Wstrzymane | hurtowa zmiana statusu w Liście produkcyjnej |
| `anulowane` | Anulowane | hurt; zmiana z Base.; doróbka całej ilości (oryginał z ilością 0) |

Statusów `zweryfikowane`, `zaladowane`, `dostarczone` **nie ma** na liście hurtowej zmiany statusu (serwer ich nie przyjmuje). Status `czeka_na_logistyke` nie jest już etapem (logistyka jest równoległa).

### 2.2 Droga pozycji przez stanowiska (z kodu `complete_task`)

```
Import z Base. ─┬─ mikrowczep → Wycinanie ─┐
                └─ lity       → Składanie ─┴→ Sklejanie ─┬─ bez docięcia (cut_to_size = false) ───────────────→ Pakowanie
                                                         └─ z docięciem → Formatowanie ─┬─ z obróbką krawędzi → Krawędzie ─┬─ olej/lakier → Lakiernia → Pakowanie
                                                                                         │                                  └─ surowe ──────────────────→ Pakowanie
                                                                                         └─ bez obróbki krawędzi ─┬─ olej/lakier → Lakiernia → Pakowanie
                                                                                                                  └─ surowe ──────────────────→ Pakowanie
Pakowanie → spakowane → (Weryfikacja) zweryfikowane → (Dostawa) zaladowane → dostarczone
```

- **Bez docięcia** pozycja z Sklejania idzie prosto do Pakowania i **omija Formatowanie, Krawędzie i Lakiernię** — także gdy jest olejowana albo lakierowana (liczniki Formatowania i Krawędzi wpisuje automat `auto_skip`). **Potwierdzone przez Konrada 6.10: to poprawne — zamówienia bez docięcia nie są wykańczane.**
- Do Lakierni trafiają tylko wykończenia `olejowane` i `lakierowane`. Inne (np. bejcowane) idą z Formatowania/Krawędzi prosto do Pakowania (do sprawdzenia w przebiegu, czy takie pozycje w ogóle występują).
- ZAKOŃCZ ustawia licznik sztuk stanowiska na pełną ilość — nie wymaga wcześniejszego wbicia licznika.

### 2.3 Zamówienie po spakowaniu — według sposobu dostawy

| Sposób dostawy | Pozycje po kolei | Zamyka się w Logistyce (i trafia do Archiwum) |
|---|---|---|
| **Kurier** | spakowane → (opcjonalnie) zweryfikowane | **przy spakowaniu** (dalej kurierzy w Base.) |
| **Transport własny** („Transport WoodPower” w Base.) | spakowane → zweryfikowane (**obowiązkowo przed załadunkiem**) → zaladowane → dostarczone | gdy wszystkie pozycje `dostarczone` |
| **Odbiór osobisty** | spakowane → (opcjonalnie) zweryfikowane → dostarczone („Wydane klientowi”) | po „Wydane klientowi” |
| **Nie ustawiono** | spakowane (pakowanie przechodzi od kroku 4.6) | **nie zamyka się** — czeka na decyzję logistyka |
| Anulowane w całości | — | zawsze |

Zamówienie spakowane, ale otwarte w Logistyce (transport bez trasy lub na trasie, odbiór niewydany, brak sposobu, przepakowanie) zostaje w aktywnych w Liście produkcyjnej, nie w Archiwum.

### 2.4 Statusy wysyłane do Base. i kiedy

| Moment | Status w Base. (numer) | Mechanizm |
|---|---|---|
| Import zamówienia oknem synchronizacji | „W produkcji – surowe / olejowanie / lakierowanie / bejcowanie” (mieszanka → surowe) | jednorazowe wywołanie przy imporcie (do sprawdzenia w przebiegu, czy ścieżka okna synchronizacji ma włączoną zmianę statusu) |
| Ostatnia aktywna pozycja wchodzi do pakowania (wszystkie w `czeka_na_pakowanie` lub dalej) | „Produkcja zakończona” (138620) | po commicie ZAKOŃCZ, ponowienia co 5 s … 10 min (ok. 18 min łącznie), bez trwałego znacznika |
| Wszystkie aktywne pozycje spakowane | kurier: „Zamówienie spakowane” (138623); transport: „Planowana trasa” (417343); odbiór: „Czeka na odbiór osobisty” (149777); **bez sposobu: nic** | jak wyżej |
| Zmiana sposobu dostawy | pole „Metoda dostawy”: „Kurier” / „Transport WoodPower” / „Odbiór osobisty” | trwały znacznik `bl_delivery_method_pending` + dopychacz w tle |
| Zmiana sposobu na zamówieniu w całości spakowanym („Zmień bez przepakowania”, także pierwsze ustawienie po pakowaniu bez sposobu) | status po spakowaniu dla nowego sposobu | `bl_status_pending_id` + dopychacz |
| „Cofnij do pakowania” (Logistyka albo Weryfikacja) | „Produkcja zakończona” (138620) | `bl_status_pending_id` + dopychacz |
| Poprawiony adres w Logistyce | adres dostawy | `bl_address_pending` + dopychacz |
| „Wydane klientowi” | „Odebrane” (149779) | `bl_status_pending_id` |
| Zatwierdzenie trasy | **bez zmiany** | — |
| „Zakończ załadunek” | „Załadowane - trans. WoodPower” (524520) | `bl_status_pending_id` |
| „Ruszam w trasę”; „Cofnij dostarczenie” | „Wysłane - trans. WoodPower” (149763) | `bl_status_pending_id` |
| „Dostarczone” (telefon) albo zaznaczone w „Odhacz” | „Dostarczona - trans. WoodPower” (149778) | `bl_status_pending_id` |
| „Niedostarczone” | **bez zmiany** (zostaje „Wysłane”) | — |
| Zejście z trasy do puli (zamknięcie trasy z niedostarczonymi, „Zdejmij z trasy”, odznaczenie w „Odhacz” zamówienia załadowanego, „Cofnij załadunek”, doróbka/zmiana z Base. na trasie w drodze) | „Planowana trasa” (417343) | `bl_status_pending_id` |
| Hurtowa zmiana statusu w Liście produkcyjnej, „Cofnij weryfikację”, „Zgłoś problem”, Odłóż, gwiazdki | **nic** | — |

Dopychacz wysyła z odstępem 1,5 s (limit API Base. 100/min na konto). Dopóki zmiana nie dotrze, lista Logistyki pokazuje ikonę chmurki „Base.: czeka na wysłanie”. Gdy Base. odmówi limitem, pojawia się pasek „Wysyłka do Base. wstrzymana do …”.

---

## 3. Biuro — codzienna obsługa

### 3.1 Import zamówień z Base. (okno synchronizacji)

Dashboard produkcji → przycisk **„Synchronizuj z Base.”** (nad kartą „Stanowiska produkcyjne”). Okno ma cztery kroki:

1. **„Synchronizacja z Base.”** — „Zakres pobierania (dni wstecz)” i „Statusy do pobrania” (statusy Base. z listy, kilka domyślnie zaznaczonych) → **„Pobierz zamówienia”**.
2. **„Pobieranie zamówień”** — postęp i log → **„Przejdź do listy zamówień”**.
3. **„Wybierz zamówienia”** — **„Zaznacz wszystkie”** / **„Odznacz wszystkie”**, potem **„Zapisz zamówienia (N)”** (najwyżej 100 naraz). Zamówienia już będące w bazie są oznaczone.
4. **„Zapisywanie zamówień”** → „Synchronizacja zakończona!” → **„Zakończ”**.

Skutki zapisu: nowe pozycje dostają status startowy (mikrowczep → Wycinanie, lity → Składanie), **termin** = data wejścia w status w Base. + **10 dni roboczych** (surowe) albo **14** (gdy choć jedna pozycja wykończona), rangę w kolejce (przeliczenie od razu), a tablety Wycinania i Składania dostają sygnał.

Uwagi:
- Ponowny zapis zamówienia, które już jest w produkcji, **dopisuje jego pozycje drugi raz** (tryb `force_update`) — nie zapisywać ponownie oznaczonych zamówień.
- Cron importu (`sync-cron`) jest wyłączony i ma zastaną usterkę — import zostaje ręczny.

### 3.2 Lista produkcyjna

Zakładka **„Lista produkcyjna”** (dawniej „Lista produktów”). Nagłówek: tytuł i przycisk **„Drabina priorytetów”**. Kafelki: Zamówienia, Produkty, Objętość, Wartość netto, Pilne. Filtry: wyszukiwarka („Szukaj: nr zamówienia, klient, produkt...”), skaner kodu (ikona), Gatunek, Technologia, Klasa, Grubość, Status, Źródło → **„Filtruj”**.

Karta zamówienia (kolumny): **#** (miejsce w kolejce produkcji; „—” dla zamówień spoza kolejki), pole wyboru, **★** (przycisk priorytetu z gwiazdkami — otwiera modal), ▶ (rozwija pozycje), Klient / Zamówienie, Pozycje, Objętość, Wartość netto, Status, Termin, Akcje (Załączniki, Notatki, Szczegóły, link do Base.).

- **Kolejność kart = ranga liczona na żywo** (`GET /production/api/priorytety/kolejka`). Zamówienia spoza kolejki (spakowane, wstrzymane, anulowane) na końcu, po terminie. Gdy kolejka nie odpowie — sortowanie po terminie i ostrzeżenie „Kolejność wg terminu: nie udało się wczytać priorytetów”.
- **Plakietki na karcie:** gwiazdki, trasa, tag („Po terminie”, „Blisko terminu”, „Rozpoczęte”), „Odłożone na <stanowisku>: powód, godzina, pracownik” (przy kilku odłożeniach — liczba).
- **Pasek hurtu** (po zaznaczeniu): **„Zmień status”**, **„Ustaw gwiazdki”**, **„Eksport”**, **„Usuń”** (usuwanie tylko admin).

### 3.3 Okno priorytetu zamówienia (modal)

Otwiera je przycisk ★ na karcie. Tytuł „Priorytet zamówienia <nr>”. Sekcje:

| Sekcja | Zawartość |
|---|---|
| **Gwiazdki** | 5 gwiazdek (klik = ustaw 1–5) i „Bez gwiazdek”; pod spodem „Ustawił: kto, kiedy” albo „Nikt jeszcze nie ustawiał” |
| **Szczebel** | nazwa szczebla i „szczebel n z z”; „Miejsce w kolejce: N”. Zamówienie poza kolejką: „Zamówienie jest poza kolejką produkcji (spakowane, wstrzymane albo anulowane).” |
| **Termin** | data (albo „brak terminu”), tagi; „Trasa: nazwa, od …” albo „bez trasy” |
| **Gdzie leży** | tabela per stanowisko z pozycjami zamówienia: Pozycji, Na stole (kafle z przyciskiem **„Zdejmij ze stołu”**), Odłożone, W kolejce („miejsce z z”), Stół — przycisk **„Wyślij na stanowisko”** (Lakiernia: „bez stołu (pracuje z listy)”); plakietka „niekompletne” |
| **Odłożenia** | stanowisko, pozycja, powód, notatka, godzina, pracownik (pełne imię i nazwisko) + „Zdejmij ze stołu” |
| **Historia** | ostatnie wpisy: Gwiazdki (stare → nowe), Wysłanie na stół, Zdjęcie ze stołu, Odłożenie, Zamknięcie odłożonego (· kto · kiedy) |

- Zmiana gwiazdek zapisuje i od razu przelicza rangi (każdy z dostępem do modułu produkcji, nie tylko admin).
- **„Wyślij na stanowisko”** kładzie na stół tego stanowiska kafle zamówienia, które **w tej chwili** czekają na tym stanowisku — **ponad K**, na początek stołu, z plakietką „wysłane przez biuro”. Kafel odłożony wraca na stół (to jedyne „przywróć” odłożenia). Brak pozycji na stanowisku → „Zamówienie … nie ma teraz żadnej pozycji na …” (409 `brak_na_stanowisku`). Działa w trybie `stary` i `stol`.
- **„Zdejmij ze stołu”** usuwa kafel (leżący albo odłożony) — wraca do kolejki. Doróbka i kafel, który stanąłby pierwszy w kolejce, dostają podpis „Kafel wróci przy następnym dopełnieniu stołu.” (zdjęcie nie blokuje kafla).
- Komunikaty po akcji: „Na stół stanowiska … wysłano kafli: N.” / „Zamówienie już leży na stole stanowiska ….” / „Zdjęto ze stołu stanowiska …. Kafel wrócił do kolejki stanowiska.”

### 3.4 Drabina priorytetów

Przycisk **„Drabina priorytetów”** → okno z drabiną. Na górze: „Zamówienie z trasy bierze szczebel trasy. Zamówienie bez trasy bierze najwyższy ze swoich szczebli (gwiazdki, tagi).”

**Domyślna drabina po migracji:** ★★★★★, Po terminie, ★★★★, Blisko terminu, Rozpoczęte, ★★★, ★★, ★, bez gwiazdek.

| Rodzaj szczebla | Przesuwanie | Skąd się bierze |
|---|---|---|
| Gwiazdki (★5 … bez) | **stałe** (kłódka „stały”) | gwiazdki zamówienia |
| Tag „Po terminie” | strzałki ↑↓ | termin zamówienia < dziś |
| Tag „Blisko terminu” | ↑↓ | termin ≤ dziś + próg (domyślnie 3 dni robocze, Konfiguracja) |
| Tag „Rozpoczęte” | ↑↓ | zamówienie ma pozycję na Formatowaniu/Pakowaniu lub dalej i inną pozycję wcześniej; liczony na żywo przy pobieraniu na stół |
| Trasa (robocza / zatwierdzona) | ↑↓ | powstaje z trasą **bezpośrednio pod najniższym szczeblem trasy**, a bez tras — pod ★★★★★; znika po załadunku; „Cofnij załadunek” przywraca w tym samym miejscu |

- Przy każdym szczeblu licznik „N w produkcji”; szczebel pusty jest wyszarzony.
- **Ostrzeżenie o datach:** gdy wyższa trasa ma późniejszą datę „od” niż niższa — nic nie przesuwa się samo.
- Zmiana z innej sesji w międzyczasie → „Drabina zmieniła się w międzyczasie. Sprawdź i spróbuj jeszcze raz.” (okno czyta drabinę od nowa).

**Kolejność w szczeblu (zamówienia):** gwiazdki malejąco → termin rosnąco → numer zamówienia. **Kafle pozycji** (Wycinanie, Składanie, Sklejanie, Krawędzie): doróbki pierwsze → szczebel → gwiazdki → najpierw pozycje zamówień „Rozpoczętych” → grupa materiału (gatunek, klasa, grubość) w kolejności najbliższego terminu w grupie → termin → długość i szerokość malejąco → numer → kolejność pozycji.

### 3.5 Hurt: gwiazdki, zmiana statusu, wstrzymanie, usunięcie

| Akcja (pasek hurtu) | Co robi | Wpływ na kolejkę / stół |
|---|---|---|
| **„Ustaw gwiazdki”** | gwiazdki 0–5 na unikalnych zamówieniach zaznaczonych pozycji; potwierdzenie przy zdejmowaniu gwiazdek albo > 10 zamówieniach (fokus na „Anuluj”); > 500 zamówień — odmowa bez wysyłki | przeliczenie rang od razu; kafli na stołach nie rusza |
| **„Zmień status”** | lista: Wycinanie - mikro, Składanie - lite, Sklejanie, Formatowanie, Krawędzie, Lakiernia, Pakowanie, Spakowane, Wstrzymane, Anulowane | kafle pozycji, które zeszły ze stanowiska, schodzą ze stołu; sygnał do stanowisk; przeliczenie rang; **Base. nie dostaje statusu** |
| „Zmień status” → **Wstrzymane** | narzędzie „zabierz z kolejki” | zamówienie wypada z kolejki (bez rangi), kafle schodzą ze stołów |
| „Zmień status” → **Anulowane** | — | jak wyżej; przechodzi także dla zamówień na trasie w drodze |
| „Zmień status” → **Spakowane** na zamówieniu zweryfikowanym | działa jak „Cofnij weryfikację” | — |
| „Zmień status” na status produkcyjny/„Spakowane” zamówienia z trasy **załadowanej / w drodze** | **odmowa** dla tego zamówienia („…najpierw Cofnij załadunek” / „…najpierw Niedostarczone, potem Zdejmij z trasy” / „…najpierw Cofnij dostarczenie”); reszta zaznaczonych przechodzi | — |
| **„Usuń”** (tylko admin) | trwałe usunięcie pozycji | kafel `o:` zamówienia może zostać jako **widmo** na stole (zakładka Stanowiska → „Do zdjęcia ze stołu”) |

Pozycja cofnięta hurtem do produkcji unieważnia paczki, weryfikację i załadunek zamówienia (reguła „unieważnij etapy”).

### 3.6 Poprawki zamówienia i pozycji — co biuro może zmienić

| Co | Gdzie | Skutek dla kolejki / stołu |
|---|---|---|
| Gwiazdki | modal priorytetu, hurt, kolumna ★ w Logistyce | przeliczenie rang; kafle na stołach zostają |
| Szczebel (miejsce tagu/trasy) | Drabina priorytetów | przeliczenie rang |
| Kafel na stole | „Wyślij na stanowisko” / „Zdejmij ze stołu” (modal, zakładka Stanowiska) | sygnał do tabletów stanowiska |
| Status pozycji, wstrzymanie, anulowanie | hurt „Zmień status” | 3.5 |
| Pozycje zamówienia zgodnie z Base. (dodane / usunięte / zmienione) | Szczegóły zamówienia → **„Odśwież z Base.”** → okno porównania → **„Zastosuj wszystkie zmiany”** | nowa pozycja wchodzi na Wycinanie/Składanie (sygnał); zamówienie z trasy załadowanej / w drodze, które wraca do produkcji, schodzi z trasy jak „Niedostarczone” (Base. 417343); przeliczenie rang |
| Notatki | akcja „Notatki” na karcie | bez wpływu |
| Sposób dostawy, adres, pinezka, trasa | zakładka Logistyka (sekcja 6) | trasa robocza/zatwierdzona = szczebel trasy |
| Termin istniejącego zamówienia | **brak edycji w UI** — terminy w bazie nie są przeliczane; liczba dni dotyczy tylko nowych importów | — |
| Licznik sztuk stanowiska | końcówka `POST /production/api/admin/update-quantity-done` istnieje, ale przycisku w panelu nie znalazłem (do sprawdzenia w przebiegu) | licznik > 0 = kandydat na kafel startowy |

### 3.7 Zakładka Stanowiska

Siedem kart stanowisk. Na karcie: „Tryb: stół / zgodność (stara appka) • Na stole n/K • Odłożone n/limit • W kolejce N”. Sekcje: **„Na stole (n/K …)”** z plakietką źródła kafla (wysłane przez biuro, rozpoczęte przed startem, doróbka) i **„Zdejmij ze stołu”**; **„Odłożone (n/limit)”**; **„Do zdjęcia ze stołu (kafle bez pozycji na stanowisku)”** — widma; **„Niekompletne”** (Formatowanie, Pakowanie) z brakującymi pozycjami; **„Dalej w kolejce (pierwsze 15)”** (w trybie `stary`: „Dalej na liście”). Lakiernia: pierwsze 15 pozycji listy z nazwą grupy wykończenia. Zakładka odświeża się co 120 s, gdy jest widoczna. To ten sam stół, który widzi tablet.

### 3.8 Konfiguracja (admin)

**Karta „Terminy”** (zapis przyciskiem „Zapisz terminy”, poza ogólnym paskiem zmian):
- „Termin zamówień surowych” — domyślnie 10 dni (1–90),
- „Termin zamówień z wykończeniem” — domyślnie 14 dni (1–90),
- „Dni terminu” — robocze / kalendarzowe.
Zmiana dotyczy tylko zamówień importowanych po zmianie (inne workery serwera widzą nowe liczby dni z opóźnieniem do 60 minut).

**Karta „Stół stanowisk”** (zapis „Zapisz stół stanowisk”): tabela Stanowisko / **Tryb** („zgodność (stara appka)” | „stół”) / **Miejsca na stole (K)** (1–5, domyślnie 2) / **Kafel** (pozycja | zamówienie) / **Limit odłożeń** (1–50, domyślnie 10). Wiersz Lakierni: „Lista (bez stołu) — Lakiernia pracuje z listy ułożonej po wykończeniu”. Pod tabelą: **Próg „Blisko terminu”** (0–15 dni roboczych, domyślnie 3; zmiana przelicza kolejkę) i **Minimalna wersja appki** (kod wersji; 0 = bez bramki). Serwer **odmawia** włączenia trybu „stół” przy progu wersji 0 (400 „prog_wersji_wymagany”).

**Sekcja „Start stołów”** (w karcie „Stół stanowisk”):
1. **Podgląd** (przycisk „Odśwież podgląd”) — kafle rozpoczęte na każdym stanowisku (pozycja czekająca na stanowisku z licznikiem sztuk tego stanowiska > 0; na Formatowaniu i Pakowaniu — jej zamówienie).
2. **„Przygotuj stoły”** (po zakończeniu zmiany) — kafle rozpoczęte stają się kaflami stołu ze źródłem „start”; tablety w trybie zgodności ich jeszcze nie pokazują; można powtarzać (dokłada tylko nowe). Pyta natywnym oknem przeglądarki. Komunikat wymienia kody stanowisk po angielsku („gluing: +4…”).
3. **Poprawki biura** — „Wyślij na stanowisko” / „Zdejmij ze stołu”.
4. **„Włącz stoły”** (przed zmianą) — jeden zapis: minimalna wersja appki z pola wyżej (dla appki 1.8.0: **44**) i tryb „stół” dla sześciu stanowisk (Lakiernia zostaje na liście).
5. „Rozpoczęte” na szczyt drabiny; po zejściu kafli startowych — z powrotem na domyślne miejsce.

**Wycofanie stołów** = tryb „zgodność (stara appka)” w tabeli (jeden zapis, bez wdrożenia). Kafle zostają w tabeli (tylko do odczytu) i wrócą po ponownym włączeniu.

Instrukcja dla hali przed „Przygotuj stoły”: **„wbijcie licznik na tym, co macie w rękach”** — kafel startowy powstaje wyłącznie z licznika > 0.

**Drukarka etykiet** (karta „Drukarka etykiet”): wybór „Etykiety produktów (60×40)” / „Paczki (100×150)”, przesunięcia drukarki paczek (−120…120 punktów, 8 punktów = 1 mm), **„Wydruk próbny”**, tryb druku etykiet produktów „TCP direct” / „przez agent”.

### 3.9 Monitory hali i dashboard

- **Monitor stanowiska** (`/production/stations/monitors/<kod>`): sekcje „TERAZ n/K” i „Odłożone” (powód, notatka, „Imię I.”) — tylko gdy niepuste; „Dalej w kolejce” — tylko w trybie `stol`; doróbka pierwsza. Monitor nie dopełnia stołu (przy pustym stole pokazuje kolejkę po randze). Zmiana z tabletu widoczna po ≤ 30 s. Trybu stanowiska monitor nie pokazuje.
- **Monitor Lakierni:** lista (bez „TERAZ”/„Odłożone”), karty w kolejności listy tabletu, z nazwą grupy wykończenia.
- **Monitor zbiorczy** (`/production/stations/monitor`): po randze.
- Monitory i tablety czytają rangę z bazy — tagi terminowe i „Rozpoczęte” mogą być spóźnione do najbliższego przeliczenia (cron co godzinę albo dowolne zdarzenie przeliczające).
- **Dashboard produkcji:** „Stanowiska produkcyjne”; **pasek logistyki** („Logistyka: N bez sposobu dostawy”, „Do weryfikacji: N”, „Problemy: N” — czerwone przy N > 0, „—” = nie policzono; „Otwórz Logistykę”); `high_priority_count` = zamówienia aktywne na szczeblach ★★★★★, ★★★★, „Po terminie” i trasach; alert „Dużo pilnych zamówień” powyżej 10.

---

## 4. Stanowiska (tablet)

### 4.1 Wspólne zasady

| Element | Tryb `stary` (po wdrożeniu) | Tryb `stol` (po „Włącz stoły”) |
|---|---|---|
| Ekran | lista całej kolejki stanowiska (`/stations/<S>/orders`), pracownik wybiera | **„Teraz”** (nazwa robocza sekcji stołu, do sprawdzenia w przebiegu), **„Odłożone”**, (Formatowanie, Pakowanie) **„Niekompletne”**; nagłówek „w kolejce: N” |
| Kto wybiera | pracownik | serwer (stół dopełnia się przy `GET desk`) |
| ZAKOŃCZ | dowolnej pozycji | tylko pozycji czekającej na stanowisku (inaczej 409 „Pozycja … nie czeka na …”) i z kafla na stole, odłożonego albo zamówienia niekompletnego (inaczej 409 „Zamówienie … nie leży na stole …”) |
| Odświeżanie | jak dotąd (30 s, ETag) + `desk` co ≤ 30 s, żeby wykryć przełączenie | sygnał `station:<S>` + siatka: co 30 s przy stole niepełnym, co 5 min przy pełnym; `desk` zawsze po własnym ZAKOŃCZ/Odłóż |

**ZAKOŃCZ** — zamyka pozycję na stanowisku (licznik = pełna ilość), przestawia status według 2.2, zdejmuje kafel ze stołu (także w `stary` i ze starej appki), wysyła sygnał na to i następne stanowisko. Na kaflu-zamówieniu ZAKOŃCZ to osobne ZAKOŃCZ każdej pozycji w statusie stanowiska (pozostałe pozycje kafla — bez przycisków).

**Licznik sztuk** (`PATCH …/quantity`) — „2/15”; sygnał do drugiego tabletu; w `stol` ta sama bramka co ZAKOŃCZ; kafla nie zdejmuje.

**Odłóż** (tylko w `stol` widoczne w appce; serwer przyjmuje też w `stary`, tylko online) — modal z powodem: **Brak materiału**, **Awaria maszyny**, **Brak miejsca**, **Czeka na biuro**, **Inne** (notatka wymagana, do 255 znaków). Kafel przechodzi do „Odłożone” (powód, godzina, „Imię I.”), zostaje na tablecie i **da się go zakończyć** w każdej chwili. Na stół wchodzi następny kafel (przy następnym `GET desk`). Limit otwartych odłożeń na stanowisko (domyślnie 10) — przy limicie: „Na Sklejaniu leży 10 odłożonych pozycji. Zamknij którąś, zanim odłożysz kolejną.” Limit jest **miękki** (dwa Odłóż naraz mogą go przekroczyć o 1). Nie ma „Przywróć” na tablecie — przywraca tylko biuro („Wyślij na stanowisko”). Lakiernia nie ma Odłóż.

**Odrzut sztuk = doróbka („cofnięcie”)** — z Sklejania, Formatowania, Krawędzi, Lakierni i Pakowania (nie z Wycinania i Składania). Powody: wymiary, jakość sklejenia, jakość produktu, jakość krawędzi, jakość lakierowania, inne. Ilość ≤ ilość − sztuki już zrobione na tym stanowisku. Skutek w sekcji 9.1.

**Druk etykiet produktów** (60×40, QR = identyfikator pozycji `N_S`, np. `1203_4`) — z tabletów stanowisk dozwolonych w konfiguracji (`LABEL_PRINTER_ALLOWED_STATIONS`, domyślnie Formatowanie i Pakowanie; wartość na produkcji do sprawdzenia w przebiegu): jedna pozycja, wybrane sztuki (panel kafelków) albo całe zamówienie. Bez bramki stołu.

**Przyciski stołu na kaflu:** Odłóż (lewy), ZAKOŃCZ (prawy); gwiazdki, plakietka szczebla („Trasa: nazwa, data”, „Po terminie”, „Blisko terminu”, „Rozpoczęte”, „Doróbka”), plakietka źródła („wysłane przez biuro”, „rozpoczęte przed startem”). Appka 1.8.0 **nie pokazuje „poz. i/n”** (odstępstwo przyjęte przy odbiorze).

### 4.2 Stanowisko po stanowisku

| Stanowisko | Kafel | Co widzi / robi | Dokąd idzie pozycja | Sygnał po ZAKOŃCZ |
|---|---|---|---|---|
| **Wycinanie - mikro** | pozycja | stół (doróbki pierwsze, w ramach K) | Sklejanie | `cutting` + `gluing` |
| **Składanie - lite** | pozycja | jw. | Sklejanie | `assembly` + `gluing` |
| **Sklejanie** | pozycja | stół; odrzut sztuk | z docięciem → Formatowanie; bez docięcia → Pakowanie | `gluing` + następne |
| **Formatowanie** | zamówienie | stół z zamówieniami kompletnymi; „Niekompletne” (do K) z postępem „n/m na stanowisku, k na <stanowisku>” i listą brakujących; ZAKOŃCZ pozycji niekompletnego działa; pozycja bez docięcia na kaflu — plakietka „idzie prosto do pakowania”, bez przycisków; druk etykiet; odrzut | Krawędzie / Lakiernia / Pakowanie (2.2) | `formatting` + następne |
| **Krawędzie** | pozycja | stół; tablet Krawędzi ma też ekran Lakierni (lista); odrzut | Lakiernia (olej/lakier) albo Pakowanie | `edges` + następne |
| **Lakiernia** | lista pozycji | **zawsze lista** po grupach wykończenia (rodzaj · typ koloru · kolor · połysk — połysk tylko dla lakierowanych), grupa z doróbką na początku, separator przy zmianie grupy; pracownik wybiera sam; ZAKOŃCZ bez bramki; bez Odłóż | Pakowanie | `painting` + `packaging` |
| **Pakowanie** | zamówienie | stół z zamówieniami kompletnymi (**także bez sposobu dostawy** — plakietka „Sposób dostawy do ustalenia – pakuj normalnie”); „Niekompletne”; baner przepakowania (`repack_reason`: „Przepakuj na kuriera”, „Logistyka: zmiana sposobu dostawy na …”, „Logistyka: sposób dostawy do ustalenia”, „Weryfikacja: <powód>: <notatka>”); druk etykiet produktów; odrzut | `spakowane` | `packaging` |

### 4.3 Pakowanie — okno paczek i etykiety paczek

1. Pakowacz kończy pozycje ZAKOŃCZ. ZAKOŃCZ, który domyka **całe** zamówienie, otwiera **okno paczek**: po lewej **Paczka / Paleta**, po prawej liczba **1–10**; przy palecie **Europaleta (120×80)** albo **niestandardowa** (wymiar 20–400 cm). Podpowiedź z wagi (m³ × 800 kg; do 40 kg paczka, powyżej paleta EUR ×1). Okno kończy „Zatwierdź” albo „Wróć” (Wróć anuluje ZAKOŃCZ) — nazwy przycisków do sprawdzenia w przebiegu.
2. Deklaracja (`PUT /api/mobile/orders/<numer>/packages`) tworzy paczki `P-<id>`, unieważnia poprzednie i kolejkuje **etykietę 100×150 na każdą paczkę** na drukarkę `wysylka` — zawsze przez agenta druku.
3. Etykieta paczki: numer zamówienia, „PACZKA n / N” albo „PALETA”, **pas sposobu dostawy** (KURIER, ODBIOR OSOBISTY, „TRASA: nazwa data”, TRANSPORT WOODPOWER, **NIE USTAWIONO**), odbiorca zanonimizowany (bez adresu), **QR `P-<id>`**, rodzaj, waga szacunkowa, zawartość zamówienia, numer Base. i numer zamówienia klienta.
4. Ponowny druk: jedna paczka albo wszystkie — z tabletu Pakowania i telefonu Weryfikacji; drukuje z **bieżącymi** danymi i gasi ikonę „etykiety sprzed zmiany”.
5. **Pakowanie bez sposobu dostawy przechodzi** (krok 4.6): etykieta z pasem „NIE USTAWIONO”, Base. nie dostaje statusu, zamówienie zostaje otwarte w Logistyce i liczy się do „N bez sposobu dostawy”.

---

## 5. Druk i kody QR

| Etykieta | Rozmiar / drukarka | Kto zleca | Droga | Kod QR |
|---|---|---|---|---|
| **Produkt** (sztuka pozycji) | 60×40, drukarka `etykiety` | tablet stanowiska dozwolonego w konfiguracji (domyślnie Formatowanie, Pakowanie) | `LABEL_PRINTER_USE_AGENT` = false → TCP prosto do drukarki; true → kolejka `prod_print_queue` → agent druku | identyfikator pozycji **`N_S`** (np. `1203_4`; doróbka ma ten sam identyfikator co oryginał); na etykiecie też „n/N” sztuki w zamówieniu, numer Base., klient, linia „Dostawa: …” |
| **Paczka** | 100×150, drukarka `wysylka` | deklaracja paczek (Pakowanie, Weryfikacja), ponowny druk | **zawsze** kolejka `prod_print_queue` → agent druku | **`P-<id>`** paczki (np. `P-1234`) |
| **Wydruk próbny** | obie | Konfiguracja → „Drukarka etykiet” (admin) | kolejka | kod testowy |

- **Agent druku** (`tools/print_agent/print_agent.py`, sekcje `[printer:etykiety]` i `[printer:wysylka]` w `config.ini`) pobiera zadania z serwera osobno dla każdej drukarki (najpierw etykiety produktów). Drukarkę paczek kalibruje technik: `--kalibruj wysylka`.
- **Bez działającego agenta** zadania paczek wygasają po godzinie; nieudany albo wygasły druk cofa znacznik wydruku paczki (licznik −1, ikona „etykiety sprzed zmiany” każe przedrukować).
- **Kto skanuje:** `P-<id>` — telefon Weryfikacji (rozpoznaje lokalnie z listy, działa bez zasięgu) i telefon kierowcy (załadunek). `N_S` — telefon Weryfikacji otwiera zamówienie; skaner w Liście produkcyjnej (wyszukiwanie). Inne kody na telefonie Weryfikacji: „Nieznany kod” (do sprawdzenia w przebiegu).
- **Skan unieważnionej etykiety** (po nowej deklaracji, cofnięciu do pakowania albo doróbce): „Etykieta nieaktualna — paczki zadeklarowano ponownie” (409 `package_void`).
- Panel nie ma podglądu etykiety na ekranie. Treść ZPL leży w `prod_print_queue.zpl_payload`.

---

## 6. Logistyka — logistyk

### 6.1 Sposoby dostawy

| W UI (lista i liczniki) | Wartość w bazie | Tekst do Base. | Kolor pinezki |
|---|---|---|---|
| Nie ustawiono | NULL | — | szara |
| Kurier | `kurier_baselinker` | Kurier | niebieska |
| Transport własny | `transport_woodpower` | Transport WoodPower | zielona |
| Odbiór osobisty | `odbior_osobisty` | Odbiór osobisty | fioletowa |

Wartość z Base. („Metoda z Base.”) to tylko podpowiedź (logo Base. przy metodzie); przyjęcie hurtem: **„Przyjmij podpowiedzi z Base.”**.

### 6.2 Lista (Logistyka → Dashboard)

- Kolumny: pole wyboru, ▶, **Zamówienie** (pinezka / „Ustaw na mapie”), **Klient**, **Adres**, **Metoda z Base.**, **Sposób dostawy** (lista + plakietka trasy albo „bez trasy”), **★** (gwiazdki 0–5; chowa się, gdy tabela ma ≤ 1035 px; tylko do odczytu na zamkniętych, anulowanych i wydanych), **Etap produkcji** (etap najbardziej zaległej pozycji: nazwa stanowiska, „Spakowane — czeka na weryfikację”, „Zweryfikowane”, „Załadowane”, „W trasie”, „W trasie — niedostarczone”, „Dostarczone”; pod spodem paczki „2 × paczka”, „sprawdzono 1/2”, „BEZ PACZEK”, ikona problemu z powodem), **Termin**, **m³**, **Stan** (ikony + „Wydane klientowi” / „Wydane” / „Zamknięte”).
- Liczniki (filtr i legenda): Nie ustawiono, Kurier, Transport własny, Odbiór osobisty, Wszystkie otwarte. Filtry: Szukaj, „także zamknięte” (wymaga frazy), Etap, Lokalizacja, Transport bez trasy, **Do weryfikacji / Problem / Bez paczek**, Województwa.
- Ikony „Stan”: pudełko otwarte (wróciło do pakowania), metki (etykiety produktów sprzed zmiany), pudełko (etykiety paczek sprzed zmiany sposobu lub trasy — przedrukować na pakowaniu), chmurka („Base.: czeka na wysłanie”), mapa z pinezką (adres zmieniony po ręcznym punkcie).
- Lista odświeża się co minutę (nie w trakcie pracy); przycisk „Odśwież”, „Stan na GG:MM”.

### 6.3 Ustawianie i zmiana sposobu dostawy

- Pojedynczo: lista w wierszu (albo w dymku pinezki). Hurtem: pasek „Zaznaczono: N” → „Ustaw sposób dostawy:” Kurier / Transport własny / Odbiór osobisty, „Dodaj do trasy…”, „Przyjmij podpowiedzi z Base.”, „Odznacz”.
- Zmiana z transportu na inny sposób zdejmuje z **trasy roboczej** („Zamówienie … usunięto z trasy …”). Trasa zatwierdzona → najpierw „Cofnij do roboczej”; załadowana → „Cofnij załadunek”; w drodze / dostarczona → zmiana niemożliwa.
- **Okno przepakowania (8.7)** — zamówienie w całości spakowane, niezaładowane, otwiera okno przy każdej zmianie sposobu („Zamówienie … jest spakowane”):

| Zmiana | Przyciski |
|---|---|
| na „Nie ustawiono” | **Cofnij do pakowania**, Anuluj |
| na Kuriera z Transportu własnego albo Odbioru (przepakowanie obowiązkowe) | **Cofnij do pakowania**, Anuluj |
| pozostałe (kurier → transport/odbiór, transport ↔ odbiór, **„Nie ustawiono” → dowolny**, także kurier) | **Zmień bez przepakowania**, **Cofnij do pakowania**, Anuluj |

  - „Cofnij do pakowania” — pozycje → `czeka_na_pakowanie`, paczki unieważnione, weryfikacja skasowana, Base. 138620, baner na tablecie, nowy sposób zapisany; sygnał do Pakowania.
  - „Zmień bez przepakowania” — nowy sposób, status Base. po spakowaniu dla nowego sposobu; paczki i weryfikacja zostają; ikona „etykiety paczek sprzed zmiany”.
  - Hurt: jedno okno; gdy część wymaga przepakowania — drugi krok „Cofnij je do pakowania” / „Pomiń je”.
  - **„Nie ustawiono → Kurier” bez przepakowania** zamyka zamówienie od razu (kurier spakowany) — etykiety „NIE USTAWIONO” trzeba przedrukować natychmiast (zamówienie znika z otwartych, widać je tylko z wyszukiwaniem).
- Zmiana sposobu **nie wysyła sygnału** do tabletów, chyba że cofnęła coś do pakowania.

### 6.4 Adres, pinezka, mapa

- Adres: dwuklik → okno **„Adres dostawy”** (Ulica i numer, Kod pocztowy, Miejscowość) → **„Zapisz”**. Zapis w CRM od razu, do Base. w tle, geokoder od nowa. Zablokowane dla wydanych, anulowanych, zamkniętych, z przesyłką, na trasie zatwierdzonej / załadowanej / w drodze.
- Mapa (obok listy): przełącznik **Zamówienia | Trasy**, „Grupuj pinezki”, podkłady Voyager / Positron / OpenStreetMap, **„Zlokalizuj teraz”**, licznik „Bez lokalizacji: N”, w dymku: sposób dostawy, Etap, Termin, **„Popraw lokalizację”**, **„Potwierdź punkt”**, **„Przywróć automat”**; przy wierszu **„Ustaw na mapie”**. Punkt ręczny nigdy nie jest nadpisywany automatem.
- Geokoder wysyła **wyłącznie adres** do GUGiK i Nominatim (z serwera, w tle).

### 6.5 Trasy (Logistyka → Trasy)

| Status trasy (UI) | Wartość | Co można | Kto u steru |
|---|---|---|---|
| **Robocza** (ołówek) | `robocza` | edycja pól, przystanki, kolejność, „Optymalizuj trasę”, „Zatwierdź”, „Usuń trasę”, „Odhacz jako dostarczoną” | logistyk |
| **Zatwierdzona** (kłódka) | `zatwierdzona` | „Eksport do Routimo”, „Cofnij do roboczej”, „Odhacz jako dostarczoną”; kierowca ładuje | kierowca ładuje |
| **Załadowana** | `zaladowana` | „Cofnij załadunek”, Routimo, „Odhacz” | kierowca |
| **W trasie** | `w_trasie` | „Cofnij dostarczenie”, „Cofnij niedostarczenie”, „Zdejmij z trasy” (niedostarczony), „Odhacz” | kierowca |
| **Dostarczona** | `wykonana` | „Cofnij dostarczenie”, Routimo | — |

- **Nowa trasa:** „+ Nowa trasa” → Nazwa trasy, Od, Do (≤ 31 dni), Pojazd, Kierowca (zajęci w tych dniach — wyszarzeni „(zajęty — nazwa trasy)”), Notatka → „Utwórz trasę”. **Kierowca widzi w telefonie tylko trasy przypisane do niego.**
- **Przystanki:** tylko **otwarte** zamówienia z **Transportem własnym**, nie na innej trasie — także zamówienia **jeszcze w produkcji**. Drogi: lista „Do dodania” („Dodaj”, „Dodaj zaznaczone (n)”), „Dodaj do trasy…” z Dashboardu, plakietka „bez trasy” w wierszu. Usunięcie: „Usuń z trasy” (tylko trasa robocza).
- **Kolejność:** przeciąganie za uchwyt albo „Wyżej / Niżej”; oś „Wyjazd z magazynu” → przystanki → „Powrót do magazynu”; kafelki Przystanki, Objętość, Waga, Dystans, Czas jazdy; ostrzeżenie o przekroczonej ładowności.
- **„Optymalizuj trasę”** (tylko robocza i tylko z kluczem OpenRouteService; bez klucza przycisku nie ma): podgląd Obecnie / Po optymalizacji / Zysk → „Zastosuj” albo „Anuluj”.
- **„Zatwierdź”** — blokuje edycję; Base. bez zmian; komunikat „…zatwierdzona. Możesz ją wyeksportować do Routimo.”
- **„Eksport do Routimo”** — plik `routimo_<nazwa>_<data>.xlsx`; po każdej zmianie trasy eksportować od nowa.
- **„Cofnij do roboczej”** — przy rozpoczętym załadunku czyści znaczniki załadunku i decyzje „Zostaje” (kierowca skanuje od nowa).
- **Szczebel trasy na drabinie priorytetów:** trasa robocza i zatwierdzona ma własny szczebel (nowy — bezpośrednio pod najniższym szczeblem trasy, bez tras — pod ★★★★★). Dodanie przystanku zamówienia w produkcji **od razu przestawia jego rangę** (przeliczenie po każdej akcji trasy). Po załadunku szczebel znika z widocznej drabiny; „Cofnij załadunek” przywraca go w tym samym miejscu.

### 6.6 „Wydane klientowi”, archiwum, flota

- **„Wydane klientowi”** (kolumna „Stan”; tylko odbiór osobisty, zamówienie w całości spakowane, weryfikacja niewymagana) → pytanie „Zamówienie … zostało odebrane przez klienta?” → pozycje `dostarczone`, znacznik „Wydane”, Base. „Odebrane” (149779), zamknięcie w Logistyce. Przy otwartym problemie z Weryfikacji dodatkowe pytanie „…ma zgłoszony problem z Weryfikacji: …. Wydać klientowi mimo to?”.
- **Archiwum** (zakładka produkcji): zamówienia zamknięte w Logistyce albo w całości anulowane; data „Zakończono” = zamknięcie (kurier: spakowanie, odbiór: wydanie, transport: dostarczenie); plakietka etapu najbardziej zaległej pozycji. Doróbka zamówienia z archiwum przywraca je do aktywnych.
- **Flota:** **Pojazdy** („Dodaj pojazd”: Nazwa, Numer rejestracyjny, Ładowność (kg); „Edytuj”, „Wyłącz” / „Włącz” — pojazdów się nie kasuje) i **Kierowcy** („Dodaj kierowcę” z aktywnych pracowników, kosz „Usuń z kierowców”). Liczba tras kierowcy przy nazwisku.

---

## 7. Weryfikacja (telefon weryfikatora)

- **Rejestracja:** appka na telefonie → stanowisko **Weryfikacja** (sekcja Biuro). Pracownik biura musi być w katalogu pracowników (zakładka Pracownicy, puste pole „Stanowiska” = może wszędzie); bramka **„Kto pracuje?”** — bez wybranej osoby zapisy nie przechodzą (400 `worker_required`).
- **Lista „Do weryfikacji”:** zamówienia, których wszystkie aktywne pozycje są spakowane (także już zweryfikowane — do skanu ponownego i cofnięć), otwarte w Logistyce albo spakowane w ostatnich 7 dniach (nie wcześniej niż od wdrożenia), plus zawsze zamówienia z problemem. Kolejność: z tras o najbliższej dacie, potem wg daty spakowania. Filtry w appce: Wszystkie / Trasy / Kurier / Odbiór (do sprawdzenia w przebiegu). Plakietka „BEZ PACZEK” — weryfikator deklaruje paczki tym samym oknem co tablet.
- **Akcje:**

| Akcja (appka) | Skutek | Odmowy |
|---|---|---|
| skan `P-<id>` (albo zaznaczenie ręczne) | paczka sprawdzona; **ostatnia** → zamówienie `zweryfikowane`; ponowny skan = OK bez zmian | unieważniona 409 `package_void`; problem otwarty 409 `problem_open`; spoza zakresu 409 `order_status` |
| „Zweryfikuj wszystkie” | wszystkie ważne paczki ręcznie | jw.; brak paczek 409 `no_packages` |
| cofnięcie sprawdzenia paczki | tylko ta paczka niesprawdzona; zamówienie zweryfikowane wraca do `spakowane` | po załadunku 409 `order_status` |
| „Cofnij weryfikację” | pozycje → `spakowane`, paczki zostają ważne | tylko zweryfikowane i niezaładowane |
| „Zgłoś problem” (Brak elementu, Uszkodzenie, Etykieta, Opakowanie, Inne + notatka) | flaga problemu; zweryfikowane wraca do `spakowane`; blokuje weryfikację i załadunek; panel: ikona i „Problemy: N” | tylko przed załadunkiem |
| zdjęcie problemu (rozwiązanie) | flaga znika | — |
| „Cofnij do pakowania” (z powodem) | pozycje → `czeka_na_pakowanie`, paczki unieważnione, baner „Weryfikacja: <powód>: <notatka>”, Base. 138620, sygnał do Pakowania; przy kurierze appka pyta najpierw „Paczka jeszcze na hali?” („Nie” niczego nie wysyła) | — |
| ponowny druk etykiet paczek | jak na Pakowaniu | — |

Weryfikacja jest **obowiązkowa tylko dla transportu własnego** (bramka załadunku). Kurier i odbiór mogą być zweryfikowane, ale nie muszą.

---

## 8. Dostawa (telefon kierowcy)

- **Rejestracja:** stanowisko **Dostawa** (sekcja Dostawa); w „Kto pracuje?” tylko kierowcy (Flota → Kierowcy), bez PIN-u; każdy endpoint wymaga kierowcy na pierwszym miejscu `X-Worker-Ids` (400 `worker_required`, 403 `not_a_driver`).
- **„Moje trasy”:** trasy zalogowanego kierowcy — zatwierdzone z datą „do” ≥ dziś, załadowane i w trasie (bez względu na datę), zatwierdzone z rozpoczętym załadunkiem także po dacie. Trasa robocza dla telefonu nie istnieje (404).

| Faza | Akcja (appka) | Skutek | Odmowy |
|---|---|---|---|
| Załadunek (trasa zatwierdzona) | skan `P-<id>` (lista domyślnie w odwrotnej kolejności przystanków) | znacznik załadunku paczki; postęp „załadowano x/y” | paczka innej trasy 409 `package_not_on_route` (z nazwą trasy albo „bez trasy”); niezweryfikowane 409 `order_not_verified`; unieważniona 409 `package_void`; przystanek „Zostaje” 409 `stop_stays` |
| | rozładunek paczki (pomyłka) | znacznik znika | — |
| | **„Zostaje”** na całym przystanku (Niespakowane, Niezweryfikowane, Brak miejsca, Uszkodzone, Inne + notatka); można zdjąć | czyści znaczniki załadunku zamówienia; przy „Zakończ załadunek” przystanek schodzi z trasy do puli „Transport bez trasy” | — |
| | **„Zakończ załadunek”** | pozycje załadowanych → `zaladowane`, trasa `zaladowana`, Base. 524520; „Zostaje” → zdjęte; zamówienie anulowane w całości → zdjęte | brak zweryfikowania / załadunku / paczek → 409 `loading_incomplete` z listą braków; nic nie załadowane → 409 `nothing_loaded` |
| Wyjazd | **„Ruszam w trasę”** | trasa `w_trasie`, Base. 149763 | pusta trasa → 409 „Trasa nie ma przystanków — logistyk cofnie załadunek albo odhaczy ją w panelu tras.” |
| Dostarczenia | „Nawiguj”, „Zadzwoń”; **„Dostarczone”** | pozycje `dostarczone`, Base. 149778; zamknięcie w Logistyce | — |
| | **„Niedostarczone”** (Brak klienta, Odmowa przyjęcia, Brak dojazdu, Uszkodzenie, Inne + notatka) | przystanek **zostaje na trasie do jej końca** (szary, pozycje `zaladowane`, Base. bez zmian); można go jeszcze dostarczyć albo cofnąć niedostarczenie | — |
| | „Cofnij niedostarczenie” | przystanek znów do dostarczenia | — |
| | „Cofnij dostarczenie” | **tylko własne ostatnie** dostarczenie (także po automatycznym zamknięciu trasy); pozycje → `zaladowane`, Base. 149763, trasa wraca do „W trasie” | dostarczenie zaznaczone w panelu → 409 „To dostarczenie zaznaczył logistyk w panelu — cofnąć może tylko panel.” |
| Zamknięcie | ostatni przystanek rozliczony (dostarczony, niedostarczony albo anulowany) | trasa **„Dostarczona”** (`wykonana`); niedostarczone schodzą do puli (pozycje → `zweryfikowane`, znaczniki załadunku czyszczone, Base. 417343); historia „Niedostarczone — wróciły do puli (n)” | zamknięcie jest dla niedostarczonych nieodwracalne (appka ostrzega) |

Bez zasięgu akcje czekają w kolejce offline; powtórki dają 200 „bez zmian” z pełną trasą.

---

## 9. Cofnięcia i poprawki — katalog przypadków

### 9.1 Odrzut sztuk (doróbka)

| | |
|---|---|
| Skąd | tablet: Sklejanie, Formatowanie, Krawędzie, Lakiernia, Pakowanie (`POST /api/mobile/orders/<id pozycji>/reject`) |
| Dokąd wraca | **Wycinanie** (gdy oryginał był cięty) albo **Składanie** (gdy składany; awaryjnie wg technologii) — nowy wiersz pozycji (doróbka) z tym samym identyfikatorem `N_S`, ilością odrzuconą, terminem oryginału |
| Oryginał | ilość zmniejszona; przy 0 → `anulowane` |
| Ranga | doróbka ma **rangę 0** i ramkę — pierwsza na **każdym** stanowisku; wchodzi na stół **w ramach K** jako pierwsza przy najbliższym dopełnieniu (źródło „doróbka”, plakietka „Doróbka”); na stanowisku zamówieniowym — gdy zamówienie jest kompletne |
| Logistyka | paczki unieważnione, weryfikacja i załadunek skasowane, pozycje po spakowaniu wracają do `spakowane`; zamówienie z trasy **załadowanej / w drodze** schodzi z trasy jak „Niedostarczone” (Base. 417343, wpis „Zdjęto … · Doróbka — wraca do produkcji”); z trasy roboczej/zatwierdzonej nie schodzi (kierowca zobaczy „NIESPAKOWANE”) |
| Stół | kafle, które przestały być aktualne, schodzą; sygnały: stanowisko odrzutu, stanowisko powrotu, stanowiska ze zdjętym kaflem |
| Gdzie widać | Lista produkcyjna (nowy wiersz pozycji), modal priorytetu, zakładka Stanowiska (doróbka pierwsza), monitor, tablet Wycinania/Składania |
| Ograniczenie | doróbka w zamówieniu z pozycjami **dostarczonymi** — obsługa ręczna poza systemem (nie da się zadeklarować paczek, brak na liście „Do weryfikacji”, drugie „Wydane klientowi” zablokowane) |

### 9.2 Pozostałe cofnięcia i poprawki

| Sytuacja | Kto / gdzie | Skutek | Base. |
|---|---|---|---|
| „Cofnij do pakowania” | Weryfikacja (telefon) albo okno przepakowania w Logistyce | pozycje → `czeka_na_pakowanie`, paczki unieważnione, weryfikacja skasowana, baner, sygnał `packaging`; zamówienie na trasie zostaje (kierowca: „NIESPAKOWANE”) | 138620 |
| Zmiana sposobu po spakowaniu | Logistyka, okno 8.7 | 6.3 | status po spakowaniu dla nowego sposobu albo 138620 |
| „Cofnij weryfikację” / cofnięcie sprawdzenia paczki | telefon Weryfikacji | pozycje → `spakowane` | — |
| „Cofnij do roboczej” | panel tras | trasa robocza; czyści załadunek i „Zostaje”; nowy eksport Routimo | — |
| „Cofnij załadunek” | panel tras (trasa załadowana) | trasa → Zatwierdzona, pozycje → `zweryfikowane`, paczki do ponownego skanu, szczebel trasy wraca | 417343 |
| „Niedostarczone” | telefon albo odznaczenie w „Odhacz” (powód „odhaczone w panelu”) | 8; do puli przy zamknięciu trasy albo „Zdejmij z trasy” | bez zmian; przy zejściu do puli 417343 |
| „Cofnij niedostarczenie” | telefon albo panel (trasa w drodze) | przystanek do dostarczenia | — |
| „Zdejmij z trasy” | panel tras, przy przystanku niedostarczonym trasy w drodze | zamówienie od razu w puli „bez trasy”; gdy reszta rozliczona — trasa się zamyka | 417343 |
| „Cofnij dostarczenie” | panel (dowolny dostarczony przystanek) albo telefon (tylko własne ostatnie) | zamówienie znów otwarte; trasa dostarczona wraca do „W trasie”; niedostarczone, które zeszły do puli, **nie wracają** | 149763 |
| „Odhacz jako dostarczoną” | panel tras (robocza … w trasie) | zaznaczone → dostarczone; odznaczone → do puli; niespakowanych nie da się zaznaczyć; trasa zamknięta w panelu — cofa tylko panel | 149778 / 417343 (gdy było załadowane) |
| Wstrzymanie | hurt „Zmień status” → Wstrzymane | poza kolejką, kafle schodzą ze stołów; powrót — hurt na status stanowiska | — |
| Anulowanie | hurt → Anulowane albo zmiana z Base. | poza kolejką; na trasie: przystanek anulowanego w całości jest „rozliczony”; **hurt nie zamyka trasy**, którą to rozliczyło | — |
| Zmiany z Base. | Szczegóły → „Odśwież z Base.” → „Zastosuj wszystkie zmiany” | nowa pozycja do produkcji (unieważnia paczki/weryfikację); z trasy załadowanej/w drodze — zdjęcie jak doróbka; zmiana ilości/nazwy przystanku nie zdejmuje | 417343 przy zdjęciu |
| Hurtowa zmiana statusu | Lista produkcyjna | 3.5 | — |
| „Zdejmij ze stołu” | modal priorytetu, zakładka Stanowiska | kafel wraca do kolejki | — |
| Wycofanie stanowiska na tryb `stary` | Konfiguracja → „Stół stanowisk” → „zgodność (stara appka)” | ZAKOŃCZ bez bramki, `desk` przestaje dopełniać; nowa appka wraca na listę przy najbliższym `desk` (≤ 30 s przy niepełnym stole, ≤ 5 min przy pełnym); kafle zostają w tabeli | — |

---

## 10. Scenariusz pełnego przebiegu (dla agenta E2E)

### 10.0 Zasady przebiegu

- **Środowisko:** podgląd na kopii produkcji wskazany przez Konrada (np. stack próby wdrożenia), z kodem `5e944a55` (albo czubkiem gałęzi priorytetów z tym samym kodem). **Nigdy produkcja.**
- **Ruch zewnętrzny zablokowany od pierwszego uruchomienia** (Base., ORS, GUGiK, Nominatim, GlobKurier, Sentry, poczta) — incydent 6.10: geokoder z kopii wysłał adresy na zewnątrz. Bez klucza Base. statusów Base. nie da się wysłać: sprawdzamy je w bazie (`prod_orders.bl_status_pending_id`, `bl_delivery_method_pending`, `bl_address_pending`) i w logu (`production.baselinker_status_sync`, `logistyka`) — (do sprawdzenia w przebiegu, jak wygląda nieudane wywołanie przy braku klucza: błąd, ponowienia timerem, wstrzymanie dopychacza).
- **Przeglądarka:** wyłącznie wbudowana; sesja panelu przez `login_user` w skrypcie (bez haseł); natywne okna `confirm()` — podmiana `window.confirm` albo akcja przez API.
- **Urządzenia:** wirtualne tablety i telefony przez `POST /api/mobile/register` (`device_id`, `station_code`), potem `POST /api/mobile/devices/heartbeat` z `app_version_code: 44`, `app_version_name: "1.8.0"` — **bez heartbeatu tablet jest „starą appką” i omija bramkę stołu**. Nagłówki: `Authorization: Bearer <JWT>`, `X-Operation-Id` (nowy UUID na akcję, ten sam przy ponowieniu), `X-Worker-Ids` (pracownik z `GET /api/mobile/workers`; dla Dostawy — kierowca). Ewentualne 403 `ip_not_allowed` / 426 `app_version_too_old` (nagłówek `X-App-Version`) — do sprawdzenia w przebiegu na konfiguracji podglądu.
- **Identyfikatory w API:** ZAKOŃCZ / licznik / odrzut / Odłóż — **id pozycji** (`prod_products.id`); paczki i Weryfikacja — **numer zamówienia** (`internal_order_number`); druk całego zamówienia — **id zamówienia w Base.**; przystanki Dostawy i tras — **id zamówienia** (`prod_orders.id`).
- **Druk:** agent druku hali jest podłączony do produkcji, nie do podglądu — zadania na podglądzie zostają `pending` i wygasają po godzinie (do sprawdzenia w przebiegu, czy da się podłączyć lokalnego agenta do podglądu). **Kody do skanu dla Konrada:** agent generuje **lokalnie** (bez usług zewnętrznych) stronę z kodami QR `P-<id>` (kody nie zawierają danych osobowych) i pokazuje ją na ekranie; alternatywnie fizyczny wydruk, jeśli agent druku działa na podgląd.
- **Telefony Konrada** (Weryfikacja, Dostawa) i ewentualny tablet muszą wskazywać na serwer podglądu (build debug appki, Wi-Fi albo kabel z przekierowaniem portów) — do sprawdzenia w przebiegu; build release wymaga `https` dla `sse_url`.
- **Jak appka:** przed każdym ZAKOŃCZ / Odłóż na stanowisku w trybie `stol` wirtualny tablet woła `GET desk` (i po każdej akcji też). Pozycja testowa, która nie leży na stole, nie da się zakończyć (409) — wtedy „Wyślij na stanowisko” z modalu priorytetu albo czekanie na dopełnienie (stół dobiera z kolejki tylko do K, licząc także kafle startowe i biura).
- **Raport:** numery zamówień i id — tak; nazwiska klientów, adresy, telefony — nie.
- **Oznaczenia:** **[A]** agent sam (panel w przeglądarce, API urządzenia, SQL na bazie podglądu), **[K]** wymaga Konrada (skan aparatem telefonu/tabletu, decyzja), **[A+K]** agent przygotowuje, Konrad wykonuje.

### 10.1 Dobór zamówień testowych (z danych kopii, już w CRM)

| Ozn. | Kryterium (SQL na `prod_products` / `prod_orders`) | Sposób dostawy w teście | Co sprawdza |
|---|---|---|---|
| **T1** | 1 pozycja, **bez docięcia** (`cut_to_size = 0`), surowa, czeka na Wycinaniu/Składaniu albo Sklejaniu | Kurier | droga z pominięciem Formatowania/Krawędzi/Lakierni; zamknięcie przy spakowaniu; Archiwum |
| **T2** | pozycja z docięciem, **olejowana lub lakierowana**, bez obróbki krawędzi, przed Formatowaniem | Odbiór osobisty | Formatowanie → Lakiernia (lista po wykończeniu) → Pakowanie; „Wydane klientowi” |
| **T3** | **≥ 3 pozycje** z docięciem (choć jedna z obróbką krawędzi), pozycje na różnych etapach przed Formatowaniem, bez trasy | Transport własny (na trasę dopiero po spakowaniu) | tag „Rozpoczęte”, „Niekompletne” na Formatowaniu, Krawędzie, paczki ×2, „Zostaje” |
| **T4** | pozycja czekająca na Formatowaniu (ilość ≥ 2) | Transport własny | doróbka (odrzut 1 szt.), ranga 0, powrót na Wycinanie/Składanie |
| **T5** | dowolne, blisko Pakowania (np. czeka na pakowanie), **sposób NULL** | Nie ustawiono → potem Transport własny | pakowanie bez sposobu, „NIE USTAWIONO”, okno 8.7 „Zmień bez przepakowania”, problem i „Cofnij do pakowania” z Weryfikacji |
| **T6** | czeka na pakowanie | Transport własny → po spakowaniu zmiana na Kurier | przepakowanie obowiązkowe, baner „Przepakuj na kuriera”, status kuriera |
| **T7** | czeka na Sklejaniu (do Odłóż) | Kurier | Odłóż, limit, ZAKOŃCZ odłożonego, „Wyślij” przywraca |
| **T8, T9** | 2 zamówienia w produkcji (np. Sklejanie / Formatowanie) | Transport własny, **trasa R1 od początku** | szczebel trasy (skok rangi), załadunek, Dostarczone / Niedostarczone, Cofnij załadunek, Cofnij dostarczenie |
| **T10** | małe zamówienie w produkcji | — | Wstrzymane / powrót, Anulowane (opcjonalnie) |

Zapisz w raporcie: `prod_orders.id`, `internal_order_number`, id pozycji, statusy startowe, `priority_rank` przed testem. Dla T3/T5 przy braku pasujących danych — opisać i pominąć krok (nie tworzyć sztucznych danych bez zgody Konrada).

### 10.2 Faza 0 — przygotowanie

| # | Kto | Gdzie / końcówka | Akcja | Sprawdź / oczekiwane |
|---|---|---|---|---|
| 0.1 | [A] | podgląd | potwierdź wersję kodu i blokadę ruchu zewnętrznego | hash kodu; zaślepki hostów aktywne |
| 0.2 | [A] | `POST /production/api/logistics/cron` (nagłówek `X-Cron-Secret` z konfiguracji podglądu) | ręczny cron | 200 < 1 s; `priorytety_utrwalone.success: true`; `szczeble_uzupelnione: 0`; drugi przebieg — 0 zmian |
| 0.3 | [A] | SQL | kontrole po wdrożeniu | 9 szczebli (★5, po_terminie, ★4, blisko_terminu, rozpoczete, ★3…★0); 37 kluczy `priorytety_*` + `DEADLINE_DAY_TYPE`; `DEADLINE_DEFAULT_DAYS` 10, `DEADLINE_FINISHED_DAYS` 14; rangi aktywnych zamówień unikatowe; wszystkie `priorytety_tryb_*` = `stary`; próg wersji 0; `prod_station_desk` pusty |
| 0.4 | [A] | panel | logowanie (skrypt `login_user`), zakładki Dashboard, Lista produkcyjna, Stanowiska, Logistyka, Konfiguracja | bez błędów JS w konsoli |
| 0.5 | [A] | `/api/mobile/register` + `/devices/heartbeat` | tablety: `cutting`, `assembly`, `gluing` ×2 (dwa tablety Sklejania), `formatting`, `edges`, `packaging`; telefony: `verification`, `delivery`; jeden dodatkowy tablet `gluing` **bez** heartbeatu („stara appka”) | 200 z tokenem; heartbeat 204 |
| 0.6 | [A] | `GET /api/mobile/workers`; Logistyka → Flota | wybór 2 pracowników; „Dodaj pojazd”; „Dodaj kierowcę” | pracownik-kierowca widoczny jako kierowca |
| 0.7 | [A] | `GET /api/mobile/realtime-token` | sprawdzenie realtime | 200 z kanałem `station:<kod>` (tablet Krawędzi: `edges` i `painting`) albo 503 — wtedy sygnały sprawdzamy tylko pośrednio (siatka odpytywania) |
| 0.8 | [A] | SQL + Lista produkcyjna | dobór T1–T10 (10.1) | lista w raporcie |
| 0.9 | [K] | telefony | rejestracja Weryfikacja i Dostawa na podgląd; „Kto pracuje?” — pracownik / kierowca | telefony widzą listę „Do weryfikacji” i „Moje trasy” (pustą) |

### 10.3 Faza 1 — biuro: priorytety i logistyka w trybie `stary`

| # | Kto | Gdzie / końcówka | Akcja | Sprawdź / oczekiwane |
|---|---|---|---|---|
| 1.1 | [A] | Lista produkcyjna; `GET /production/api/priorytety/kolejka` | odczyt | kolejność kart = `kolejka`; kolumna `#`; plakietki tagów zgodne z API |
| 1.2 | [A] | modal ★ na T10 | gwiazdki 0 → 5 | „Ustawił: …”; ranga T10 rośnie (Lista, `GET /zamowienia/<id>/priorytet`); wpis „Gwiazdki 0 → 5” w Historii; po przeliczeniu `priority_rank` pozycji T10 zmieniony (`/stations/<S>/orders` tabletu — `priorytet.gwiazdki: 5`) |
| 1.3 | [A] | pasek hurtu | „Ustaw gwiazdki” ★★ dla T7 i T10, potem zdjęcie gwiazdek T10 | potwierdzenie przy zdejmowaniu (fokus na „Anuluj”); log `gwiazdki` |
| 1.4 | [A] | Drabina priorytetów | strzałka ↑ przy „Blisko terminu”, potem z powrotem | renumeracja; liczniki „N w produkcji” sumują się do liczby zamówień aktywnych; (opcjonalnie) zmiana z drugiej sesji → „Drabina zmieniła się w międzyczasie…” |
| 1.5 | [A] | Logistyka → Dashboard | sposób dostawy: T1 Kurier, T2 Odbiór osobisty, T3/T4/T6/T8/T9 Transport własny, T7 Kurier; T5 zostaje „Nie ustawiono” | `bl_delivery_method_pending = 1` u zmienionych; ikona chmurki; licznik „Nie ustawiono” obejmuje T5; pasek dashboardu „Logistyka: N bez sposobu dostawy” |
| 1.6 | [A] | Logistyka → Trasy | „+ Nowa trasa” **R1** (daty od jutra, pojazd, kierowca z 0.6) i przystanki T8, T9 (w produkcji) | szczebel R1 na drabinie pod ★★★★★; ranga T8/T9 skacze na górę (Lista: plakietka trasy); tablet: `priorytet.szczebel = "trasa"`, `trasa: {nazwa, data}` |
| 1.7 | [A] | Trasy | **R2** z wcześniejszą datą „od” niż R1, pusta, „Bez pojazdu” / „Bez kierowcy” (inaczej zajętość z R1); w Drabinie R2 pod R1 | ostrzeżenie o datach tras; potem przesunąć R2 nad R1 → ostrzeżenie znika |
| 1.8 | [A] | Logistyka | adres T9: dwuklik → „Adres dostawy” → zapis tej samej wartości | „Adres zamówienia … bez zmian.” (bez wysyłki) |
| 1.9 | [A] | `GET /api/mobile/stations/<S>/desk` (dowolny tablet, tryb `stary`) | odczyt | `tryb: "stary"`, stół pusty, **zero nowych wierszy** w `prod_station_desk` |

### 10.4 Faza 2 — start stołów

| # | Kto | Gdzie / końcówka | Akcja | Sprawdź / oczekiwane |
|---|---|---|---|---|
| 2.1 | [A] | `PATCH /api/mobile/orders/<id pozycji>/quantity` | licznik 1 na pozycji T7 (Sklejanie) i na jednej pozycji Formatowania (np. T4) | 200; zakładka Stanowiska bez zmian stołu |
| 2.2 | [A] | Konfiguracja → „Start stołów” → „Odśwież podgląd” | podgląd | T7 i T4 wśród kafli rozpoczętych |
| 2.3 | [A] | „Przygotuj stoły” | potwierdź | kafle `zrodlo = start` w `prod_station_desk`; ponowne „Przygotuj” → +0; log `start_stolow` |
| 2.4 | [A] | `GET desk` w trybie `stary` | odczyt | kafle startowe widoczne tylko do odczytu, `tryb: "stary"`, brak dopełnienia |
| 2.5 | [A] | modal ★ T2 → „Wyślij na stanowisko” przy stanowisku, na którym T2 ma pozycję | wyślij | kafel `zrodlo = biuro`; Historia „Wysłanie na stół”; sygnał na to stanowisko (gdy realtime) |
| 2.6 | [A] | zakładka Stanowiska | „Zdejmij ze stołu” na jednym kaflu startowym, potem „Przygotuj stoły” jeszcze raz | kafel wraca (bo nadal rozpoczęty) — zgodnie z opisem „poprawki po ostatnim przebiegu” |
| 2.7 | [A] | Konfiguracja → „Stół stanowisk” | „Włącz stoły” z minimalną wersją **0** | odmowa 400 `prog_wersji_wymagany`, nic się nie zmienia |
| 2.8 | [A] | jw. | „Włącz stoły” z minimalną wersją **44** | sześć stanowisk „stół”, Lakiernia lista; `priorytety_min_app_version_code = 44` |
| 2.9 | [A] | Drabina | „Rozpoczęte” na szczyt | renumeracja; przeliczenie rang |
| 2.10 | [A] | `GET desk` każdego tabletu | pierwsze dopełnienie | `tryb: "stol"`; z kolejki dochodzi tylko tyle kafli, żeby leżało razem K (domyślnie 2) — kafle startowe i „biuro” liczą się do K (gdy jest ich ≥ K, nic nie dochodzi); doróbki pierwsze; Formatowanie/Pakowanie: tylko kompletne + „Niekompletne”; `kolejka_dalej`; zakładka Stanowiska i monitor pokazują to samo |
| 2.11 | [A] | dwa tablety Sklejania | `GET desk` z obu | identyczny stół w tej samej kolejności, bez duplikatów |
| 2.12 | [K] | tablet z appką 1.8.0 (jeśli jest) | obserwacja | przejście z listy na stół w ≤ 30 s, bez restartu |
| 2.13 | [A] | `/production/stations/monitors/gluing`, `/formatting`, `/painting`, `/production/stations/monitor` | odczyt | „TERAZ n/K”, „Odłożone”, „Dalej w kolejce”; Lakiernia — lista z grupą wykończenia |

### 10.5 Faza 3 — przebieg produkcji

| # | Kto | Gdzie / końcówka | Akcja | Sprawdź / oczekiwane |
|---|---|---|---|---|
| 3.1 | [A] | T1 na Wycinaniu/Składaniu: `GET desk` → ZAKOŃCZ (`POST /orders/<id>/complete`, `station_code`) | — | jeśli T1 nie leży na stole: najpierw ZAKOŃCZ → **409 `nie_na_stole`** („Zamówienie … nie leży na stole …”), bez wpisu idempotencji; potem „Wyślij na stanowisko” z panelu i ZAKOŃCZ → 200, status `czeka_na_sklejanie`, kafel zszedł |
| 3.2 | [A] | T1 na Sklejaniu | ZAKOŃCZ | `czeka_na_pakowanie` (pominięte Formatowanie i Krawędzie — liczniki `auto_skip`); Base.: zaplanowane 138620 (log); `logistics_completed_at` ustawione |
| 3.3 | [A] | bramki | (a) ZAKOŃCZ pozycji T1 drugi raz z nowym `X-Operation-Id` (tablet Sklejania) → **409 `pozycja_poza_stanowiskiem`**; (b) ZAKOŃCZ pozycji z innego stanowiska → 409 `pozycja_poza_stanowiskiem`; (c) ZAKOŃCZ z tabletu **bez heartbeatu** pozycji nieleżącej na stole → 200 (stara appka bez bramki) i kafel znika ze stołu, jeśli tam leżał | wszystkie trzy jak opisano; (c) zmienia status — wybrać pozycję, którą i tak trzeba przesunąć |
| 3.4 | [A] | T7 na Sklejaniu: Odłóż (`POST /orders/<id>/postpone`, `zakres: "pozycja"`, `powod: "brak_materialu"`) | — | 200 ze stołem **bez dopełnienia** (kafel w `odlozone`, „Imię I.”); następny `GET desk` dokłada kafel; Lista: plakietka „Odłożone na Sklejaniu: brak materiału, GG:MM, <pracownik>”; modal: sekcja „Odłożenia”; log `odlozenie` |
| 3.5 | [A] | Odłóż — błędy | `powod: "inne"` bez notatki → 400 `powod_niepoprawny`; `zakres: "zamowienie"` na Sklejaniu → 400 `dane_niepoprawne` | komunikaty jak w kontrakcie; brak zapisów |
| 3.6 | [A] | Konfiguracja: limit odłożeń Sklejania = 1; Odłóż drugiego kafla | — | 409 `limit_odlozen` („Na Sklejaniu leży 1 odłożona pozycja. Zamknij którąś…”); przywróć limit 10 |
| 3.7 | [A] | modal ★ T7 → „Wyślij na stanowisko” (Sklejanie) | — | odłożony kafel wraca na stół (`przywrocone`, źródło „biuro”); potem Odłóż jeszcze raz i **ZAKOŃCZ odłożonego** → 200, log `odlozenie_zamkniete`, plakietka znika |
| 3.8 | [A] | T3: pierwsza pozycja do Formatowania (ZAKOŃCZ na Sklejaniu; w razie potrzeby „Wyślij”) | — | T3 dostaje tag **„Rozpoczęte”** (modal, po przeliczeniu także tablet); pozostałe pozycje T3 na Sklejaniu idą na początek swojego szczebla (`GET /kolejka?stanowisko=gluing`); Formatowanie: T3 w **„Niekompletne”** z `na_stanowisku`, `pozycji`, `brakuje` |
| 3.9 | [A] | Formatowanie: ZAKOŃCZ pozycji T3 z „Niekompletnych” | — | 200 (furtka niekompletnego); ZAKOŃCZ brakującej pozycji (jeszcze na Sklejaniu) z tabletu Formatowania → 409 `pozycja_poza_stanowiskiem` |
| 3.10 | [A] | dokończenie Sklejania dla T3 | ZAKOŃCZ ostatniej brakującej | sygnał `formatting`; przy następnym `GET desk` Formatowania T3 jest kompletne i wchodzi na stół, gdy jest miejsce (inaczej czeka w `kolejka_dalej`) |
| 3.11 | [A] | T3 Formatowanie → Krawędzie → Pakowanie | ZAKOŃCZ kolejno | pozycja z krawędziami → `czeka_na_krawedzie`, bez → `czeka_na_pakowanie` (surowa) |
| 3.12 | [A] | T2: Formatowanie → **Lakiernia** | ZAKOŃCZ na Formatowaniu; `GET /stations/painting/orders` tabletem Krawędzi | T2 w `czeka_na_lakiernie`; lista po grupach wykończenia, pole `grupa_wykonczenia`; `GET .../painting/desk` → 409 `stanowisko_bez_stolu`; ZAKOŃCZ na Lakierni (`station_code: "painting"` z tabletu Krawędzi) → 200 bez bramki → `czeka_na_pakowanie` |
| 3.13 | [A] | T4: doróbka — `POST /orders/<id pozycji>/reject` na Formatowaniu (`quantity: 1`, `reason_category: "wymiary"`) | — | oryginał: ilość −1 (przy 0 → anulowane); nowa pozycja-doróbka z tym samym `N_S`, `priority_rank = 0`, status `czeka_na_wyciecie` albo `czeka_na_skladanie`; kafel oryginału uzgodniony na stole; `GET desk` Wycinania/Składania → doróbka **pierwsza, w ramach K** (`zrodlo: "dorobka"`, `priorytet.szczebel: "dorobka"`); zakładka Stanowiska i monitor — doróbka pierwsza |
| 3.14 | [A] | doróbka T4 przez Sklejanie (i dalej) aż do Pakowania; oryginał T4 dalej | ZAKOŃCZ | Pakowanie dostaje T4 dopiero, gdy kompletne (oryginał + doróbka); doróbka zachowuje rangę 0 do końca |
| 3.15 | [A] | druk etykiet produktów: `POST /api/mobile/products/<N_S>/print-label` (tablet Formatowania) i `/orders/<id Base.>/print-labels` (tablet Pakowania) | — | tryb agenta: wiersze `prod_print_queue` (`printer = etykiety`, QR = `N_S`); tryb TCP: odpowiedź z błędem połączenia (502) — (do sprawdzenia w przebiegu, który tryb ma podgląd); tablet stanowiska spoza dozwolonych → 403 |
| 3.16 | [A] | T10: hurt „Zmień status” → Wstrzymane | — | T10 poza kolejką (modal: „poza kolejką produkcji”), kafle zeszły ze stołów, sygnał; hurt → status stanowiska — wraca do kolejki z nową rangą |
| 3.17 | [A] | (opcjonalnie) hurt „Usuń” jednej pozycji zamówienia leżącego na stole Formatowania/Pakowania (admin, **tylko za zgodą Konrada** — trwałe usunięcie na kopii) | — | kafel `o:` jako widmo w „Do zdjęcia ze stołu”; „Zdejmij ze stołu” go usuwa |

### 10.6 Faza 4 — Pakowanie, paczki, etykiety

| # | Kto | Gdzie / końcówka | Akcja | Sprawdź / oczekiwane |
|---|---|---|---|---|
| 4.1 | [A] | T1 (kurier) na Pakowaniu: ZAKOŃCZ → `PUT /api/mobile/orders/<nr>/packages` `{"kind": "paczka", "count": 1}` | — | pozycje `spakowane`; paczka `P-<id>`; 1 zadanie `printer = wysylka`; Base.: 138623 zaplanowane; T1 **zamknięte w Logistyce** (`logistics_closed_at`), w Archiwum; na liście „Do weryfikacji” (7 dni) |
| 4.2 | [A] | T2 (odbiór): ZAKOŃCZ + 1 paczka | — | Base. 149777; „Wydane klientowi” widoczne w Logistyce |
| 4.3 | [A] | T3 (transport): ZAKOŃCZ + `{"kind": "paczka", "count": 2}` | — | 2 paczki, etykiety „PACZKA 1 / 2”, „2 / 2”, pas „TRANSPORT WOODPOWER”; Base. 417343; Logistyka: „Spakowane — czeka na weryfikację”, „2 × paczka” |
| 4.4 | [A] | T5 (**bez sposobu**): ZAKOŃCZ | — | **200** (brak 409 `delivery_method_not_set`); okno paczek: `{"kind": "paleta", "count": 1, "pallet_type": "eur"}`; etykieta z pasem **„NIE USTAWIONO”**; **Base. nic** (`bl_status_pending_id` NULL); T5 otwarte w Logistyce, w liczniku „Nie ustawiono” |
| 4.5 | [A] | T6, T8, T9, T4: ZAKOŃCZ + paczki | — | jak 4.3 (T8/T9 pas „TRASA: R1 <data>”) |
| 4.6 | [A] | `GET /api/mobile/orders/<nr>/packages`; `POST /packages/<id>/print`; `POST /orders/<nr>/packages/print` | ponowny druk | nowe zadania `wysylka`; licznik wydruku paczki rośnie |
| 4.7 | [A] | deklaracja przed spakowaniem (zamówienie w trakcie) | `PUT …/packages` | 409 `order_not_packed` |
| 4.8 | [A+K] | lokalna strona z kodami QR `P-<id>` (T1, T2, T3 ×2, T4, T5, T6, T8, T9) | agent przygotowuje stronę bez usług zewnętrznych | Konrad ma kody na ekranie do skanowania telefonem (sekcje 10.7–10.9) |

### 10.7 Faza 5 — Logistyka po spakowaniu

| # | Kto | Gdzie / końcówka | Akcja | Sprawdź / oczekiwane |
|---|---|---|---|---|
| 5.1 | [A] | Logistyka, T5: sposób „Transport własny” | okno „Zamówienie … jest spakowane” | przyciski: Zmień bez przepakowania / Cofnij do pakowania / Anuluj; wybierz **„Zmień bez przepakowania”** → `bl_status_pending_id = 417343`; ikona „etykiety paczek sprzed zmiany” (napis z druku „NIE USTAWIONO” ≠ obecny) |
| 5.2 | [A] | T5 → ponowny druk wszystkich paczek (`POST /orders/<nr>/packages/print`) | — | nowe zadanie; ikona gaśnie dopiero po udanym druku (na podglądzie bez agenta zostaje — do sprawdzenia w przebiegu) |
| 5.3 | [A] | T6: zmiana Transport własny → Kurier | okno | tylko **„Cofnij do pakowania”** i „Anuluj” + zdanie o obowiązku; „Cofnij do pakowania” → pozycje `czeka_na_pakowanie`, paczki unieważnione, Base. 138620 (`bl_status_pending_id`), sygnał `packaging`; tablet Pakowania: T6 z banerem `repack_reason: "Przepakuj na kuriera"` |
| 5.4 | [A] | T6: ponowne ZAKOŃCZ + paczki | — | baner znika; Base. 138623; T6 zamknięte (kurier) |
| 5.5 | [A+K] | skan starej etykiety T6 telefonem Weryfikacji | Konrad skanuje kod sprzed przepakowania | „Etykieta nieaktualna — paczki zadeklarowano ponownie” |
| 5.6 | [A] | T3, T5 → „Dodaj do trasy…” → R1 | — | przystanki dodane (zamówienia spakowane — szczebel trasy nie zmienia już niczego na stołach); pas etykiet paczek „TRANSPORT WOODPOWER” ≠ „TRASA: R1 …” → ikona „etykiety paczek sprzed zmiany” (do sprawdzenia w przebiegu) |

### 10.8 Faza 6 — Weryfikacja (telefon Konrada)

| # | Kto | Gdzie / końcówka | Akcja | Sprawdź / oczekiwane |
|---|---|---|---|---|
| 6.1 | [K] | telefon Weryfikacji, lista „Do weryfikacji” | odczyt | T1, T2, T3, T4, T5, T6, T8, T9 widoczne; panel: filtr „Do weryfikacji”, pasek „Do weryfikacji: N” |
| 6.2 | [K] | skan T3 `P-…1` | — | „sprawdzono 1/2” w Logistyce; zamówienie jeszcze `spakowane` |
| 6.3 | [K] | skan T3 `P-…2` | — | T3 `zweryfikowane`; Logistyka „Zweryfikowane”; ponowny skan = OK bez zmian |
| 6.4 | [K] | T8, T9, T4: skan wszystkich paczek albo „Zweryfikuj wszystkie” | — | `zweryfikowane` |
| 6.5 | [K] | T5: „Zgłoś problem” (Uszkodzenie + notatka) | — | panel: ikona problemu, filtr „Problem”, „Problemy: N” (czerwone); skan paczki T5 → 409 `problem_open` |
| 6.6 | [K] | T5: „Cofnij do pakowania” z powodem | — | T5 `czeka_na_pakowanie`, paczki unieważnione, baner „Weryfikacja: Uszkodzenie: …”, Base. 138620; sygnał `packaging`; problem przeniesiony do banera |
| 6.7 | [A] | T5: ZAKOŃCZ + nowe paczki | — | baner znika; status po spakowaniu wg sposobu (transport 417343); T5 znów na liście |
| 6.8 | [K] | T5: skan nowych paczek | — | `zweryfikowane` |
| 6.9 | [K] | T9: cofnięcie sprawdzenia jednej paczki, potem ponowny skan | — | T9 → `spakowane` → `zweryfikowane` |
| 6.10 | [K] | T2 (odbiór): skan (opcjonalnie) | — | możliwe, ale nie wymagane |

### 10.9 Faza 7 — Dostawa (telefon Konrada jako kierowcy)

| # | Kto | Gdzie / końcówka | Akcja | Sprawdź / oczekiwane |
|---|---|---|---|---|
| 7.1 | [A] | Trasy → R1 (T8, T9, T3, T5) | „Zatwierdź” | „…zatwierdzona. Możesz ją wyeksportować do Routimo.”; Base. bez zmian; „Eksport do Routimo” — pobranie pliku tylko za zgodą Konrada |
| 7.2 | [K] | telefon Dostawy → „Moje trasy” | R1 widoczna (data „do” ≥ dziś) | — |
| 7.3 | [K] | skan paczki T6 (kurier) na R1 | — | odmowa „Paczka … nie jedzie trasą …” (`package_not_on_route`, „bez trasy”) |
| 7.4 | [K] | skan paczek T8, T9, T5 | — | „załadowano x/y” w panelu i telefonie |
| 7.5 | [K] | T3: **„Zostaje”** (Brak miejsca + notatka) | — | panel: „Zostaje: Brak miejsca — notatka” |
| 7.6 | [K] | „Zakończ załadunek” przed skanem wszystkich (wariant) | — | 409 z listą braków (`loading_incomplete`) |
| 7.7 | [K] | „Zakończ załadunek” po komplecie | — | R1 „Załadowana”; T8/T9/T5 `zaladowane`, Base. 524520; **T3 zszedł do puli** „Transport bez trasy” (pozycje zostają `zweryfikowane`); szczebel R1 znika z drabiny |
| 7.8 | [A] | panel tras: **„Cofnij załadunek”** | — | R1 „Zatwierdzona”, pozycje `zweryfikowane`, Base. 417343, szczebel R1 wraca na drabinę w tym samym miejscu |
| 7.9 | [K] | ponowny skan T8, T9, T5 → „Zakończ załadunek” → **„Ruszam w trasę”** | — | R1 „W trasie”, Base. 149763; Logistyka etap „W trasie” |
| 7.10 | [K] | T8: **„Dostarczone”** | — | T8 `dostarczone`, Base. 149778, zielony przystanek „Dostarczono GG:MM”, T8 zamknięte → Archiwum |
| 7.11 | [K] | T9: **„Niedostarczone”** (Brak klienta) → „Cofnij niedostarczenie” → „Niedostarczone” ponownie | — | przystanek szary, zostaje na trasie; pozycje `zaladowane`; Base. bez zmian; Logistyka „W trasie — niedostarczone” |
| 7.12 | [K] | T5: „Dostarczone” → „Cofnij dostarczenie” (telefon) → „Dostarczone” | — | cofnięcie tylko ostatniego własnego; Base. 149763 → 149778 |
| 7.13 | [A] | panel tras: „Cofnij dostarczenie” T8 (dostarczenie z telefonu) | — | T8 znów otwarte, Base. 149763; potem kierowca [K] „Dostarczone” T8 ponownie |
| 7.14 | [K] | ostatnie rozliczenie R1 (T9 niedostarczone, reszta dostarczona) | — | R1 **„Dostarczona”** sama; T9 zszedł do puli (pozycje `zweryfikowane`, Base. 417343); historia „Niedostarczone — wróciły do puli (1)”; postęp „dostarczono 2/3 · niedostarczono 1” (T3 zdjęty przez „Zostaje” przed załadunkiem nie liczy się do mianownika — do sprawdzenia w przebiegu) |
| 7.15 | [A] | R2 (z 1.7): przystanki T9 i T3 → Zatwierdź → **„Odhacz jako dostarczoną”** (zaznacz T3, odznacz T9) | — | T3 `dostarczone` (149778); T9 do puli (Base. bez zmiany, bo niezaładowane — status 417343 już jest); R2 „Dostarczona”, zamknięta w panelu; telefon nie cofnie jej dostarczenia (409 „To dostarczenie zaznaczył logistyk w panelu…”) |
| 7.16 | [A] | (opcjonalnie) R3 z T9: Zatwierdź → [K] załadunek → Ruszam → Niedostarczone → [A] **„Zdejmij z trasy”** | — | T9 od razu w puli, Base. 417343; trasa zamyka się (jedyny przystanek) |
| 7.17 | [A] | T2: „Wydane klientowi” | potwierdź | pozycje `dostarczone`, Base. 149779, „Wydane”, zamknięte → Archiwum |
| 7.18 | [A] | (opcjonalnie) powrót do produkcji zamówienia z trasy **załadowanej** | — | odrzut sztuk działa tylko na pozycji czekającej na stanowisku (po spakowaniu już nie), a druga droga — „Odśwież z Base.” → nowa pozycja — wymaga Base.; **(do sprawdzenia w przebiegu — prawdopodobnie nie do wykonania na podglądzie)**; oczekiwane wg specu: zdjęcie z trasy jak „Niedostarczone”, Base. 417343 |

### 10.10 Faza 8 — kontrole końcowe i wycofanie stanowiska

| # | Kto | Gdzie / końcówka | Akcja | Sprawdź / oczekiwane |
|---|---|---|---|---|
| 8.1 | [A] | SQL | stan T1–T10 | statusy pozycji zgodne z tabelami; `logistics_closed_at` zgodnie z 2.3; `bl_status_pending_id` / `bl_delivery_method_pending` zgodne z ostatnim przejściem (na podglądzie bez klucza Base. zostają — do sprawdzenia w przebiegu) |
| 8.2 | [A] | Archiwum | odczyt | T1, T2, T6, T8, T3 w Archiwum; T9 i T4 (jeśli nieukończone) w aktywnych |
| 8.3 | [A] | Konfiguracja → tryb Sklejania „zgodność (stara appka)” | zapis | `GET desk` Sklejania → `tryb: "stary"`, bez dopełniania; ZAKOŃCZ bez bramki; [K] tablet wraca na listę ≤ 30 s (niepełny stół) / ≤ 5 min (pełny) |
| 8.4 | [A] | ponownie „stół” dla Sklejania | zapis | kafle wracają; `desk` dopełnia |
| 8.5 | [A] | drugi ręczny cron | — | `success: true`, 0 albo kilka zmian (tagi terminowe) |
| 8.6 | [A] | log aplikacji | przegląd | brak 500; wpisy „limit czekania” i 1213 — pojedyncze albo żadne |
| 8.7 | [A] | raport | — | tabela kroków z wynikiem OK / odstępstwo, bez danych klientów |

---

## 11. Znane ograniczenia i pułapki

| # | Pułapka | Skutek / co robić | Źródło |
|---|---|---|---|
| 1 | **Zmiana trybu stanowiska nie wysyła sygnału** | po „Włącz stoły” tablet przechodzi na stół ≤ 30 s; po wycofaniu na `stary` — ≤ 30 s przy niepełnym stole, **≤ 5 min przy pełnym** (szybciej: wejść na ekran stanowiska od nowa). Sygnał przy zmianie trybu — karta po wdrożeniu | K5, kontrakt §12, uwaga appki 1 |
| 2 | **Widma po wycofaniu i ponownym wdrożeniu backendu** | ZAKOŃCZ starego kodu nie zdejmuje wierszy stołu → po ponownym wdrożeniu `DELETE FROM prod_station_desk` **przed** „Przygotuj stoły” | uwaga appki 2 (dziennik centrali 6.10) |
| 3 | Widma po hurtowym usunięciu pozycji i po ręcznej synchronizacji z `force_update` | kafel `o:` zostaje; zakładka Stanowiska → „Do zdjęcia ze stołu” → „Zdejmij” | CLAUDE.md, K5.13 |
| 4 | **Zawieszony broker realtime** (przyjmuje połączenie, nie odpowiada) | każde ZAKOŃCZ dłuższe o ok. 1,4 s (ok. 1,5 s zamiast 0,05 s); reakcja: restart brokera albo `REALTIME.enabled=false` w `core.json` z natychmiastowym restartem aplikacji; tablety przechodzą na odpytywanie 30 s / 5 min | K5.7, runbook K5 B6 |
| 5 | **Odpowiedź `desk` do ok. 0,65 MB** (appka), 343 kB zmierzone w K5 (Formatowanie z 9 kaflami startowymi) | obserwacja po wdrożeniu | uwaga appki 4, K5 |
| 6 | **Limit odłożeń jest miękki** | dwa Odłóż naraz mogą przekroczyć limit o 1 | CLAUDE.md, K3.13 |
| 7 | `desk` przy cudzej blokadzie zamówienia wraca po 5–9 s **bez dopełnienia** (200); ZAKOŃCZ zamówienia o niższym id może czekać z nim do ok. 5 s | to nie błąd; seria wpisów „limit czekania” w logu = coś długo trzyma blokadę | K5.12 |
| 8 | Tagi terminowe i „Rozpoczęte” na tabletach, monitorach i liście Lakierni są **z ostatniego przeliczenia** (cron co godzinę); panel liczy na żywo; ETag `desk` nie obejmuje szczebla i trasy | plakietka może być chwilę nieświeża | CLAUDE.md, K5 |
| 9 | **Próg wersji 0 + tryb „stół”** | serwer odmawia (400 `prog_wersji_wymagany`); przy włączonym stole tablet **bez heartbeatu** liczy się jako stara appka i omija bramkę | K4b.21, kontrakt §11 |
| 10 | Dwa równoczesne pierwsze zapisy tego samego klucza ustawień | jedno 500 `blad_serwera`, powtórka przechodzi | K5.14 |
| 11 | Dwa „Wyślij” naraz na puste stoły różnych stanowisk | 1213 z udanym ponowieniem (200/200) | K5.11 |
| 12 | Cron importu `sync-cron` | kończy się 500 po zapisie zamówień i blokuje `manual-sync` wpisem „w toku” — **nie włączać** | K5, uwagi 2 |
| 13 | Ponowny zapis z okna synchronizacji zamówienia już w produkcji | dubluje pozycje | K5, uwagi poza zakresem |
| 14 | Hurtowe „Anulowane” nie zamyka trasy, którą rozliczyło | niedostarczone wiszą z „Wysłane” do „Zdejmij z trasy” / „Odhacz” / „Niedostarczone” | spec etapu 4, R32.2 |
| 15 | Doróbka w zamówieniu z pozycjami dostarczonymi | obsługa ręczna poza systemem | spec etapu 4, 4.5 |
| 16 | **Stara appka 1.7.3 sama blokuje ZAKOŃCZ Pakowania bez sposobu dostawy** i spycha takie zamówienia na koniec | dopiero appka 1.8.0 pakuje bez sposobu | spec etapu 4, 10a |
| 17 | **Przewodnik logistyka (części A i E) mówi „tablet nie zacznie pakowania bez sposobu dostawy”** | nieaktualne od kroku 4.6 — pakowanie przechodzi, etykieta „NIE USTAWIONO” | przewodnik A, E vs spec 10a |
| 18 | „Nie ustawiono → Kurier” bez przepakowania zamyka zamówienie od razu | etykiety „NIE USTAWIONO” u kuriera przedrukować natychmiast | spec 10a pkt 3 |
| 19 | Druk paczek wyłącznie przez agenta druku | bez agenta zadania wygasają po godzinie i cofają znacznik wydruku | CLAUDE.md |
| 20 | Hurtowa zmiana statusu **nie wysyła statusu do Base.** (wg kodu) | **Konrad 6.10: powinna** — poprawka osobną kartą po wdrożeniu 8.10; do tego czasu biuro ustawia status w Base. ręcznie | kod `products_api._zapisz_zmiane_statusu` |
| 21 | Zamknięcie trasy jest dla niedostarczonych nieodwracalne; „Cofnij dostarczenie” ich nie przywraca | ponownie zaplanować z puli | spec etapu 4, R32.4 |
| 22 | Kierowca widzi tylko trasy przypisane do siebie | trasa bez kierowcy nie pojawi się w żadnym telefonie; zastępstwo = zmiana kierowcy w panelu (przy załadunku zeruje postęp) | spec etapu 4, 9.8 |
| 23 | Appka 1.8.0 — odstępstwa przyjęte przy odbiorze | brak „poz. i/n” na kaflu; sygnał na tablecie Krawędzi odświeża tylko bieżący widok; ponowienie po `nie_na_stole` po czasie; Odłóż na Krawędziach 32 dp; **pkt 12 (Odłóż bez sieci) niesprawdzony**; doróbka na kaflu-zamówieniu z `szczebel = gwiazdki` — po wdrożeniu | dziennik centrali 6.10 |
| 24 | Build release appki blokuje ruch nieszyfrowany | produkcyjny `sse_url` musi być `https` | dziennik centrali (K5) |
| 25 | 409 `delivery_method_not_set` (tylko stary backend) | appka 1.8.0 zostawia wpis w kolejce offline | kontrakt §10 |
| 26 | Stara appka sortuje listę Lakierni sama | porządek po wykończeniu widać od 1.8.0 | spec 16.7 LAK.10 |
| 27 | Drobne UI | komunikat „Przygotuj stoły” z kodami po angielsku; walidacja pokazuje ścieżkę pola („stanowiska.gluing.miejsca”); nagłówek „Na stole … ponad K: doróbki…” nieaktualny (doróbki w ramach K); „Przygotuj”/„Włącz” pytają natywnym oknem; po 409 drabiny Lista zostaje przy starej kolejności do odświeżenia; monitor nie pokazuje trybu | K5 uwagi 6–13 |
| 28 | Na serwerze przed pushem **nie wołać `flask …`** z nowym kodem na dysku (każde polecenie migruje) | — | pakiet wdrożenia, odstępstwo 4 |
| 29 | Po wycofaniu **nie wołać** `POST /production/api/recalculate-all-priorities` (zdejmuje blokady doróbek); telefony Weryfikacji i Dostawy po wycofaniu nie działają (ich niewysłane akcje przepadają) | — | pakiet wdrożenia C |
| 30 | Kopia produkcji: geokoder i inne usługi wysyłają dane na zewnątrz, jeśli ruch nie jest zablokowany | blokada od pierwszego uruchomienia | dziennik centrali 6.10 |
| 31 | Zmiana `core.json` (np. `REALTIME`) bez restartu | część workerów na starej konfiguracji — zapis i restart zawsze razem | CLAUDE.md |
| 32 | Terminy: zmiana liczby dni w Konfiguracji widoczna dla importu na innych workerach z opóźnieniem do 60 min; terminów istniejących zamówień nikt nie przelicza | — | CLAUDE.md, spec K2.21 |

---

## Źródła

Repozytorium (worktree `C:/Users/Grafik/Documents/woodpower-crm/.claude/worktrees/priorytety-centrala`, tylko odczyt):
- `CLAUDE.md` (sekcje „Zadania cykliczne”, „Ważne”, „Priorytety produkcji”)
- `docs/superpowers/specs/2026-09-24-logistyka-rownolegla-trasy-design.md`
- `docs/superpowers/specs/2026-09-28-logistyka-runda-2-uwagi-design.md` (spis treści)
- `docs/superpowers/specs/2026-09-30-logistyka-etap-4-weryfikacja-dostawa-design.md`
- `docs/superpowers/specs/2026-10-04-priorytety-produkcji-design.md` (całość, w tym 16.1–16.9)
- `docs/api-mobile-priorytety.md`
- `docs/superpowers/plans/raporty/2026-10-05-priorytety-krok-K5-raport.md`
- `docs/superpowers/plans/raporty/2026-10-06-priorytety-pakiet-wdrozenia-raport.md`
- `docs/superpowers/plans/raporty/2026-10-05-priorytety-krok-K3-raport.md` (sekcja „Co następny krok musi wiedzieć”)
- `docs/superpowers/plans/raporty/2026-10-05-priorytety-dziennik-centrali.md`
- Kod: `modules/production/models.py` (`complete_task`, statusy, `LabelPrintJob`), `services/station_catalog.py`, `services/rework_service.py`, `services/label_print_service.py`, `services/print_queue_service.py`, `services/baselinker_status_sync.py`, `services/sync_service.py` (import, terminy), `services/mobile_api_service.py` (`mark_order_complete`, `STATION_GROUPS`), `services/id_generator.py`, `routers/mobile_api.py`, `routers/api/products_api.py` (hurt, zmiany z Base.), `routers/api/sync_api.py`, `routers/stations/monitors.py`, `routers/__init__.py`, `logistics/sposoby.py`, `logistics/routers/{panel_api,trasy_api,cron_api,weryfikacja_api,dostawa_api}.py`, `logistics/services/delivery.py`, `logistics/templates/logistics/tab_content.html`, `logistics/static/js/logistics.js`, `priorytety/static/js/priorytety.js`, `templates/panel/dashboard.html`, `templates/components/{products-tab-content,stations-tab-content,config-tab-content,dashboard-tab-content,dashboard_bl_sync_modal}.html`, `static/js/modules/{products-module,dashboard_bl_sync_modal}.js`, `app.py` (prefiksy blueprintów)

Poza repo:
- `C:/Users/Grafik/Documents/woodpower-podglady/logistyka4/przewodnik/A-lista.md`, `B-mapa.md`, `C-trasy.md`, `D-flota-dashboard.md`, `E-cykl-zamowienia.md`
- `C:/Users/Grafik/Documents/woodpower-podglady/logistyka4/instrukcja-pracownikow-material.md`

---

## Punkty „(do sprawdzenia w przebiegu)”

1. Nazwy przycisków i sekcji w appce 1.8.0 (tablet, telefon Weryfikacji, telefon Dostawy) — kod appki poza repo CRM; w szczególności ostateczna nazwa sekcji „Teraz”, przyciski okna paczek („Zatwierdź” / „Wróć”), filtry listy Weryfikacji (Wszystkie / Trasy / Kurier / Odbiór), komunikat „Nieznany kod”, możliwość ręcznego załadunku paczki bez skanu.
2. Czy ścieżka okna synchronizacji (`save_selected_orders`) wysyła do Base. status „W produkcji – …” (zmiana statusu przy imporcie).
3. Wykończenia inne niż olejowane/lakierowane (np. bejcowane) — czy występują; wg kodu omijają Lakiernię.
4. Wartość `LABEL_PRINTER_ALLOWED_STATIONS` i `LABEL_PRINTER_USE_AGENT` na produkcji i na podglądzie (które tablety drukują etykiety produktów i którą drogą; odpowiedź druku TCP na podglądzie).
5. Edycja liczników sztuk z panelu — końcówka `admin/update-quantity-done` istnieje, przycisku w Liście produkcyjnej nie znaleziono.
6. Jak na podglądzie bez klucza Base. zachowują się wysyłki statusów (błąd, ponowienia timerem, wstrzymanie dopychacza) i czy znaczniki `bl_*_pending` zostają — źródło kontroli „kolejki Base.” w przebiegu.
7. Czy lokalnego agenta druku da się podłączyć do podglądu (inaczej zadania druku tylko w `prod_print_queue`, kody QR z lokalnie wygenerowanej strony); czy ikona „etykiety sprzed zmiany” gaśnie bez udanego druku.
8. Podłączenie telefonów Konrada (Weryfikacja, Dostawa) i tabletu do serwera podglądu (build debug, przekierowanie portów) oraz konfiguracja podglądu wobec `ip_not_allowed` i `X-App-Version` (426).
9. Czy do akcji mobilnych potrzebny jest wcześniejszy `POST /api/mobile/sessions/start` (kod odświeża sesje pracownika przy akcji; wymaganie startu sesji niepotwierdzone).
10. Krok 10.9 / 7.18 — doróbka na zamówieniu z trasy załadowanej po spakowaniu: odrzut sztuk z Pakowania jest możliwy tylko dla pozycji czekającej na Pakowaniu, a „Odśwież z Base.” wymaga Base. — prawdopodobnie niewykonalne na podglądzie.
11. Zachowanie zmian z Base. („Odśwież z Base.” → „Zastosuj wszystkie zmiany”) — na podglądzie bez Base. nie do sprawdzenia.
12. Pkt 12 odbioru appki (Odłóż bez sieci — przycisk nieaktywny) — niesprawdzony przy odbiorze.
13. Czy panel tras ma przycisk „Usuń trasę” dla trasy zatwierdzonej (przewodnik: pustą roboczą lub zatwierdzoną usuń) i czy „Optymalizuj trasę” pojawia się na podglądzie (zależy od klucza ORS).
14. Ikona „etykiety paczek sprzed zmiany” po dodaniu spakowanego zamówienia do trasy (pas „TRANSPORT WOODPOWER” → „TRASA: …”) — krok 5.6.
15. Licznik postępu trasy po zamknięciu z przystankiem zdjętym wcześniej przez „Zostaje” (krok 7.14: oczekiwane „dostarczono 2/3 · niedostarczono 1”).
