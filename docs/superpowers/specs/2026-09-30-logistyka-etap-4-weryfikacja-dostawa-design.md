# Logistyka — etap 4: paczki, Weryfikacja i Dostawa — projekt

- **Data:** 2026-09-30
- **Status:** zatwierdzony w rozmowie sekcja po sekcji (7/7), czeka na przegląd spisanej wersji
- **Gałąź:** `claude/logistyka-etap-4`, odbita od `claude/logistyka-etap-3-trasy` (`112aa34b`). Etapy 1–3 nie są
  wdrożone; etap 4 wdrażamy dopiero po nich.
- **Podstawa:** `docs/superpowers/specs/2026-09-24-logistyka-rownolegla-trasy-design.md` (etapy 1–3) i przekazanie
  `docs/superpowers/plans/2026-09-26-logistyka-etap-3-przekazanie.md`. Pojęcia stamtąd (sposób dostawy, `transport`,
  `przelicz_zamkniecie`, dopychacz Base., blokada tras) używamy bez ponownego opisu.
- Repo jest publiczne — w tym pliku nie ma sekretów ani uwag bezpieczeństwa.

## 1. Cel i kontekst

Dziś cykl zamówienia w CRM kończy się na `spakowane`. To, czy paczka jest kompletna, czy trafiła na auto i czy
dojechała do klienta, dzieje się poza systemem. Logistyk planuje trasy (etap 3), ale nikt nie potwierdza w CRM
załadunku ani dostarczenia, a archiwum zabiera zamówienia już po spakowaniu.

**Cel:** zamknąć cykl od pakowania do klienta:
- pakowacz deklaruje, **ile i jakich sztuk wysyłki** (paczek/palet) ma zamówienie, a drukarka przy pakowaniu wydaje
  etykietę na każdą z nich,
- pracownik biura na stanowisku **Weryfikacja** (telefon) sprawdza każdą paczkę po zmianie produkcji,
- kierowca na stanowisku **Dostawa** (telefon) ładuje paczki swojej trasy, rusza w trasę i potwierdza dostarczenia,
- statusy pozycji i Base. odzwierciedlają te kroki, a archiwum przyjmuje zamówienie dopiero w stanie końcowym.

**Sukces:**
- żadna paczka nie trafia na auto bez weryfikacji,
- logistyk widzi w panelu, co jest zweryfikowane, załadowane, w trasie i dostarczone,
- klient widzi w Base. „Załadowane” → „Wysłane” → „Dostarczona” w chwilach, w których to faktycznie zachodzi,
- archiwum zawiera tylko zamówienia zakończone dla swojego sposobu dostawy.

## 2. Ustalenia z rozmowy

1. Dwa nowe stanowiska w tej samej appce, na telefonach: **Weryfikacja** (`verification`) i **Dostawa** (`delivery`).
   W etapie 4 Dostawa obejmuje załadunek, wyjazd i proste potwierdzanie dostarczeń („pół Routimo”).
2. Jednostką skanowania jest **paczka** (paczka albo paleta). CRM dziś nie zna paczek — pakowacz deklaruje je przy
   zamykaniu zamówienia.
3. Okno paczek na tablecie pakowania: po lewej **Paczka / Paleta**, po prawej liczba jako kafelki **1–10**; przy palecie
   **Europaleta** (120×80) albo **niestandardowa** z wymiarem wpisanym ręcznie. Półautomat: wybór zaznaczony z
   podpowiedzi (do 40 kg paczka, powyżej paleta), z możliwością zmiany.
4. Każda paczka dostaje **etykietę 100×150** z własnym QR na **drugiej drukarce** (przy pakowaniu). Druga drukarka
   wymaga zmian w agencie druku i kolumny drukarki w kolejce wydruku. Później ta sama drukarka będzie drukować listy
   przewozowe kurierów (poza zakresem).
5. Na etykiecie jest **cała zawartość zamówienia** (bez przypisywania pozycji do paczek).
6. Problem przy weryfikacji: **zgłoszenie z powodem** i opcjonalne **cofnięcie do pakowania**.
7. Załadunek niezweryfikowanego zamówienia: **twarda blokada**.
8. Brak możliwości załadowania: kierowca oznacza zamówienie **„Zostaje”** z powodem; zakończenie załadunku zdejmuje je z
   trasy.
9. Po załadunku **nowy status w Base.** „Załadowane – trans. WoodPower” (zakłada go Konrad). 149763 „Wysłane – transport
   WoodPower” ustawia przycisk **„Ruszam w trasę”**.
10. **Nowe statusy pozycji** (nie osobny rejestr): `zweryfikowane`, `zaladowane`, `dostarczone`.
11. Archiwum: kurier po spakowaniu, transport własny po dostarczeniu, odbiór osobisty po wydaniu. Zmiana archiwum w
    etapie 4, jako ostatni krok.
12. Po załadunku kierowca dostaje ekran dostarczeń (przystanki w kolejności, „Dostarczone” / „Niedostarczone”).
13. Etap dzielony na kroki z osobnymi planami, **zaczynając od agenta druku** (drukarka podłączona do komputera
    deweloperskiego — test na miejscu).
14. Nazwy: stanowiska „Weryfikacja” i „Dostawa” (ekran kierowcy w trybach „Załadunek” i „Dostarczenia”).

## 3. Kroki i zakres

| Krok | Zawartość | Warunek wdrożenia |
|---|---|---|
| **4.1 Druk** | kolumna drukarki w kolejce, agent na 2 drukarki (TCP i kolejka Windows), etykieta paczki ZPL, wydruk próbny, ustawienia drukarki paczek | drukarka w sieci hali, nowy agent na komputerze hali |
| **4.2 Paczki** | `prod_packages`, podpowiedź, deklaracja z tabletu, druk etykiet, ponowny druk, okno w appce | 4.1; backend przed appką |
| **4.3 Statusy i Weryfikacja** | nowe wartości `current_status`, przegląd miejsc z `spakowane`, stanowisko Weryfikacja, problem, cofnięcie do pakowania, `repack_reason` | 4.2; appka z ekranem Weryfikacji |
| **4.4 Dostawa** | statusy tras, Moje trasy, załadunek, „Zostaje”, „Ruszam”, dostarczenia, zmiany w panelu tras, statusy Base. | 4.3; status „Załadowane” założony w Base. |
| **4.5 Archiwum** | reguła archiwum = zamknięte w Logistyce albo anulowane | 4.4 |

**Poza zakresem (etap 5 i dalej):** pełne Routimo (zdjęcia, podpis, kolejność na żywo, powiadomienia klienta), listy
przewozowe kurierów na drukarce paczek, liczba paczek/waga wysyłane do Base. lub kuriera, mieszane typy paczek w jednym
zamówieniu, przypisanie pozycji do paczek, paleta z kilku zamówień, wyświetlanie tras na mapie w telefonie.

## 4. Statusy i cykl życia

### 4.1 Nowe statusy pozycji

`current_status` (ENUM `production_status`) dostaje na końcu: `zweryfikowane`, `zaladowane`, `dostarczone`.
- Zmieniają się **dla wszystkich niezanulowanych pozycji zamówienia naraz**, gdy zamówienie przejdzie krok.
- `spakowane` zostaje nazwą; w UI po etapie 4 opisujemy je jako „Spakowane — czeka na weryfikację”. (krok 4.3) To napis
  **etapu zamówienia** w panelu Logistyki i na telefonie Weryfikacji (`stage_label`); `status_display_name` pozycji
  zostaje „Spakowane” (raporty, historia produktu).
- (krok 4.3) Nowe statusy nadaje wyłącznie logistyka (Weryfikacja, „Wydane klientowi”, w kroku 4.4 Dostawa) —
  hurtowa zmiana statusu ich nie oferuje (serwer i listy wyboru).
- „Spakowane lub dalej” (`STATUSY_PO_SPAKOWANIU = {'spakowane','zweryfikowane','zaladowane','dostarczone'}`) — jedna
  stała w `logistics/sposoby.py`, używana wszędzie tam, gdzie dziś kod pyta o `== 'spakowane'` w znaczeniu „produkcja
  zakończona” (mapa miejsc w 8.6).

### 4.2 Przebieg według sposobu dostawy

| Sposób | Pozycje | Base. | Zamknięcie w Logistyce / archiwum |
|---|---|---|---|
| Transport własny | spakowane → zweryfikowane → zaladowane → dostarczone | Planowana trasa (417343) → **Załadowane** (nowy) → 149763 po „Ruszam” → 149778 | po `dostarczone` |
| Odbiór osobisty | spakowane → zweryfikowane → dostarczone („Wydane klientowi”) | Czeka na odbiór (149777) → Odebrane (149779) | po wydaniu |
| Kurier | spakowane → zweryfikowane | Spakowane (138623), dalej kurierzy w Base. | po spakowaniu |

„Wydane klientowi” (etap 1) od kroku 4.3 ustawia też pozycje na `dostarczone`. Działa ze `spakowane` i `zweryfikowane`
(bez wymogu weryfikacji). (krok 4.3) Pozycje `spakowane` zamówień **już wydanych** przed wdrożeniem przestawia na
`dostarczone` cron logistyki (`delivery.dostarcz_wydane`, klucz `wydane_dostarczone` w odpowiedzi, wołany obok
`przenies_osierocone_z_logistyki`), a nie migracja: migracja wykonuje się przed restartem, a stary kod w oknie wdrożenia
nie zna tej wartości ENUM (odczyt takiego wiersza rzuciłby `LookupError`, czyli 500 na listach). Po wdrożeniu kroku
4.3 cron trzeba więc uruchomić raz ręcznie (CLAUDE.md, „Logistyka równoległa”).

### 4.3 Statusy trasy

`prod_routes.status`: `robocza → zatwierdzona → zaladowana → w_trasie → wykonana`.
- `zaladowana` — kierowca zakończył załadunek. `w_trasie` — kierowca nacisnął „Ruszam”.
- Obie są **aktywne** (zajętość pojazdu/kierowcy, `trasa_dla_tabletu`, lista tras) i **zablokowane do edycji** jak
  `zatwierdzona` (formularz, przystanki, kolejność; zmiana sposobu dostawy i adresu zamówienia z takiej trasy → 409).
- Eksport Routimo dostępny od `zatwierdzona` wzwyż, także z `wykonana` (ruling R11 etapu 3 — przewoźnik może pobrać
  plik ponownie po zamknięciu trasy; tak działa kod, patrz 9.8).
- `wykonana` ustawia się sama po rozliczeniu ostatniego przystanku albo ręcznie z panelu (9.7).
- **Nazwy dla ludzi (decyzja Konrada 2.10, oględziny U7):** Robocza, Zatwierdzona, Załadowana, W trasie,
  **Dostarczona** (wartość `wykonana` w bazie i API bez zmian; sekcja listy tras „Dostarczone”). Szczegóły w 9.8.

### 4.4 Bramki

- Załadunek przyjmuje paczkę tylko, gdy zamówienie jest `zweryfikowane` (serwer: 409 `order_not_verified`).
- „Wydane klientowi” i kurier nie czekają na weryfikację. Panel pokazuje zamówienia wydane/zamknięte bez weryfikacji.
- Weryfikacja wymaga zadeklarowanych paczek.

### 4.5 Cofnięcia

| Akcja | Kto | Skutek |
|---|---|---|
| Cofnij weryfikację | weryfikator (do załadunku) | pozycje → `spakowane`, znaczniki weryfikacji paczek czyszczone |
| Cofnij sprawdzenie paczki | weryfikator (do załadunku) | znaczniki weryfikacji tej jednej paczki czyszczone; pozostałe paczki zostają sprawdzone; zamówienie było zweryfikowane → jego pozycje → `spakowane` i `verified_at` zamówienia czyszczone |
| Cofnij do pakowania | weryfikator (`spakowane`/`zweryfikowane`) | pozycje → `czeka_na_pakowanie`, paczki unieważnione, `repack_required` + `repack_reason`, Base. 138620 |
| Zostaje | kierowca (przed „Zakończ załadunek”) | przy zakończeniu: zamówienie zdjęte z trasy (pula), statusy bez zmian |
| Cofnij załadunek | logistyk w panelu (trasa `zaladowana`) | pozycje → `zweryfikowane`, znaczniki załadunku czyszczone, Base. 417343, trasa → `zatwierdzona` |
| Niedostarczone | kierowca (trasa `w_trasie`) albo panel | zdjęte z trasy (pula), pozycje → `zweryfikowane`, znaczniki załadunku czyszczone, Base. 417343 |
| Cofnij dostarczenie | kierowca (ostatnie, trasa `w_trasie`) albo panel (dowolny przystanek) | pozycje → `zaladowane`, Base. 149763, trasa `wykonana` → `w_trasie` |
| Doróbka / nowa pozycja / przepakowanie | system | paczki unieważnione, weryfikacja i załadunek zamówienia kasują się; zamówienie przejdzie kroki od nowa po spakowaniu (poza zamówieniem z pozycjami `dostarczone` — niżej) |
| Doróbka na zamówieniu z trasy `zaladowana`/`w_trasie` (decyzja Konrada 2.10) | system | jak „Niedostarczone”: pozycje do produkcji (reguła wyżej), przystanek zdjęty z trasy (log `trasa_usuniete`, notatka „doróbka”), znaczniki załadunku czyszczone, Base. 417343, log `niedostarczone` z powodem `dorobka`; zdjęcie ostatniego nierozliczonego przystanku trasy w drodze zamyka trasę (przystanek anulowanego w całości jest rozliczony). Przystanek już dostarczony zostaje (niżej). Trasa robocza i zatwierdzona — bez zmian (sama reguła wyżej) |
| Zmiana z Base. cofająca do produkcji zamówienie z trasy `zaladowana`/`w_trasie` (Ruling 30) | system | jak doróbka wyżej, z powodem `zmiana_base` i notatką „zmiana z Base.”; zmiana, która nie cofa do produkcji (ilość, nazwa), zostawia przystanek |
| Hurtowa zmiana statusu na status produkcyjny albo `spakowane` zamówienia z trasy `zaladowana`/`w_trasie` (decyzja Konrada 2.10) | panel produkcji | odmowa dla tego zamówienia: „Zamówienie X jest na trasie „T” (załadowana / w drodze) — najpierw Cofnij załadunek albo Niedostarczone.”; reszta zaznaczonych przechodzi, a gdy odmowa obejmuje wszystkie — 409 bez zapisów. Anulowanie przechodzi (Dostawa obsługuje zamówienie anulowane) |
| Hurtowa zmiana statusu na `spakowane` zamówienia zweryfikowanego (decyzja Konrada 2.10) | panel produkcji | jak „Cofnij weryfikację”: pozycje `zweryfikowane` → `spakowane`, `verified_at` zamówienia i znaczniki weryfikacji paczek czyszczone, znaczniki załadunku czyszczone, log `weryfikacja_cofnieta` (z użytkownikiem); paczki zostają ważne. Zamyka lukę z audytu wyścigów (15, „LEGACY”) |

**Znane ograniczenie — doróbka albo nowa pozycja w zamówieniu z pozycjami `dostarczone`** (decyzja Konrada
1.10.2026: obsługa ręczna, poza systemem; nowego cyklu nie robimy ani w 4.3, ani w 4.4). Pozycje `dostarczone`
zostają, a przerobiona albo dodana pozycja po spakowaniu zostaje `spakowane`: deklaracja paczek dostaje 409
`order_verified` („…jest już dostarczone — paczek nie można zmienić”), zapisy Weryfikacji 409 `order_status`,
zamówienia nie ma na liście „Do weryfikacji”, w filtrach ani w licznikach, a przy odbiorze osobistym `handed_over_at`
blokuje drugie „Wydane klientowi”. Cron nie przestawi takiej pozycji na `dostarczone` (przestawienie wydanych jest
jednorazowe, sekcja 14). Biuro obsługuje taki przypadek poza systemem.

### 4.6 Cykl logistyki (`delivery.zamkniecie_wyliczone`)

Zmienione reguły (reszta tabeli z etapu 1 bez zmian):
- kurier: zamknięte, gdy wszystkie niezanulowane pozycje są w `STATUSY_PO_SPAKOWANIU`,
- odbiór osobisty: `handed_over_at` (bez zmian),
- transport własny: wszystkie niezanulowane pozycje `dostarczone` (zamiast „przystanek na trasie wykonanej”).
  **(krok 4.3) Ta reguła przechodzi do kroku 4.4, razem z Dostawą** (decyzja Konrada 30.09): w 4.3 transport własny
  zamyka się jak dotąd, „przystanek na trasie wykonanej”, a odhaczenie trasy nie zmienia statusów pozycji. W 4.3
  zmienia się tylko reguła kuriera (inaczej zweryfikowane zamówienia kurierskie by się otwierały).
  (krok 4.4) Wdrożone: reguła nie czyta tras, parametr `trasa` zniknął z `zamkniecie_wyliczone`/`przelicz_zamkniecie`.

Historia jest bezpieczna: migracja etapu 1 zamyka stare spakowane zamówienia, a cron `przelicz_otwarte` otwiera
zamknięte, gdy wróci aktywna pozycja (doróbka).

**Siatka w cronie (decyzja Konrada 1.10).** Stanowisko (ostatnie „ZAKOŃCZ” pakowania) decyduje o zamknięciu cyklu na
migawce sposobu dostawy, więc zmiana sposobu z panelu w tej samej chwili może zostawić zamówienie zamknięte wbrew
regule (przyczyna: kolejność blokad stanowisk, poprawka w zadaniu wstępnym kroku 4.4). Dlatego `przelicz_otwarte`
otwiera też zamknięte zamówienia z aktywną pozycją, dla których `zamkniecie_wyliczone` daje False: odbiór bez
`handed_over_at`, transport z aktywną pozycją inną niż `dostarczone` (krok 4.4), sposób NULL i `repack_required`;
bez aktywnych pozycji zamówienie zostaje zamknięte, jak mówi reguła. Siatka obejmuje wyłącznie zamknięcia ściśle późniejsze niż
`logistyka_weryfikacja_od` (`weryfikacja.data_wdrozenia()`), a brak znacznika albo nieczytelna data ją wyłącza. Bez
tego zawężenia pierwszy przebieg otworzyłby masowo zamknięcia historyczne: migracja etapu 1 zamknęła przy wdrożeniu
(`NOW()`) każde zamówienie spakowane poza odbiorem osobistym, bez względu na sposób (na kopii z 28.09 ok. 1500, głównie
sposób NULL i transport bez trasy; odbiorów migracja nie zamykała). Zawężenie jest bezpieczne, bo runner migracji wykonuje pliki w kolejności nazw:
`2026-09-25-…` (zamknięcie historyczne) idzie PRZED `2026-09-30-logistyka-weryfikacja.sql` (znacznik,
`CAST(NOW() AS CHAR)`), więc zamknięcie historyczne ma `logistics_closed_at <= znacznik`, także przy jednym deployu
etapów 1–4, gdy obie wartości wypadają w tej samej sekundzie (DATETIME bez ułamków); warunek „ściśle większe” je
wyklucza. Znacznik i zamknięcia z migracji mają czas MySQL (`NOW()`), a zamknięcia z kodu `get_local_now()` (czas
polski). Czas polski nigdy nie jest wcześniejszy niż UTC ani niż czas serwera w tej samej strefie, więc mieszanie
stref przesuwa zamknięcia z kodu tylko w bezpieczną stronę, na później od znacznika (por. Ruling 6 kroku 4.3).
(krok 4.4a) Przyczynę usuwa zadanie wstępne kroku 4.4: ZAKOŃCZ blokuje zamówienie przed pozycjami i decyduje na
odczycie bieżącym; siatka zostaje jako zabezpieczenie.

## 5. Model danych

Migracje w formacie `2026-MM-DD-nazwa.sql`, idempotentne, bez `DELIMITER`, sprawdzone na MySQL w kontenerze `db` i na
kopii produkcji. Dopisanie wartości **na końcu** ENUM na MySQL 8 zmienia same metadane (bez przebudowy tabeli) —
sprawdzić na kopii produkcji czasem wykonania.

### 5.1 `prod_print_queue` (krok 4.1)

- `printer VARCHAR(20) NOT NULL DEFAULT 'etykiety'` + indeks `(printer, status)`. Wartości: `etykiety` (dzisiejsza
  drukarka 60×40), `wysylka` (drukarka paczek 100×150).
- `package_id INT NULL` → `prod_packages.id` (od kroku 4.2; kolumna może powstać w 4.1 bez FK, FK w 4.2).
- `short_product_id` jest dziś `NOT NULL`: etykieta paczki zapisuje tam `P-<id>` (mieści się w VARCHAR(20)).

### 5.2 `prod_packages` (krok 4.2)

| Kolumna | Typ | Znaczenie |
|---|---|---|
| `id` | INT PK | kod paczki = `P-<id>` |
| `order_id` | INT NOT NULL → prod_orders, indeks | |
| `seq` | SMALLINT NOT NULL | numer 1..N w deklaracji |
| `kind` | ENUM('paczka','paleta') | |
| `pallet_type` | ENUM('eur','niestandardowa') NULL | tylko paleta |
| `length_cm`, `width_cm` | SMALLINT NULL | EUR = 120×80; niestandardowa 20–400 cm |
| `declared_at`, `declared_by_worker_id`, `declared_device_id` | | kto zadeklarował |
| `voided_at` | DATETIME NULL | unieważniona (nowa deklaracja / cofnięcie / doróbka); (krok 4.3) indeks złożony `ix_prod_packages_order_voided (order_id, voided_at)` zastępuje indeks samego `voided_at` — zapytania o paczki zawsze filtrują po zamówieniu, osobny indeks po `voided_at` nie miał zapytań (`ix_prod_packages_order_id` zostaje) |
| `label_printed_at`, `label_print_count` | | druk etykiety |
| `label_delivery_text` | VARCHAR(40) NULL | napis z pasa sposobu dostawy w chwili druku (ikona „sprzed zmiany”) |
| `verified_at`, `verified_by_worker_id`, `verified_method` ENUM('skan','reczne') | | weryfikacja |
| `loaded_at`, `loaded_by_worker_id`, `loaded_method` ENUM('skan','reczne'), `loaded_route_id` | | załadunek |

Aktualna deklaracja = paczki zamówienia z `voided_at IS NULL`. N (mianownik „2 / 3”) = ich liczba.

### 5.3 `prod_orders` (kroki 4.2–4.3)

`packages_declared_at` — krok 4.2; pozostałe kolumny — migracja kroku 4.3.

- `packages_declared_at DATETIME NULL` — ostatnia ważna deklaracja.
- `verified_at DATETIME NULL`, `verified_by_worker_id INT NULL` — zamówienie zweryfikowane.
- `problem_reason VARCHAR(32) NULL`, `problem_note VARCHAR(255) NULL`, `problem_at DATETIME NULL`,
  `problem_by_worker_id INT NULL` — zgłoszony problem (NULL = brak).
- `repack_reason VARCHAR(255) NULL` — tekst banera na tablecie pakowania (uzupełnia istniejące `repack_required`).
- (krok 4.3) Wiersz `prod_config` `logistyka_weryfikacja_od` (zakłada migracja, `INSERT IGNORE`: pierwsze wykonanie
  zapisuje chwilę wdrożenia, kolejne jej nie ruszają) — początek zakresu listy „Do weryfikacji” (8.2). Migracja zapisuje
  ją w strefie serwera MySQL, a aplikacja liczy czasem lokalnym (Warszawa), więc w dniu wdrożenia próg wypada najwyżej
  2 h wcześniej — na liście może pojawić się kilka zamówień spakowanych tuż przed wdrożeniem; wartość można poprawić
  w `prod_config`.

### 5.4 `prod_routes` i `prod_route_stops` (krok 4.4)

- `prod_routes.status` ENUM + `zaladowana`, `w_trasie`.
- `prod_routes`: `loaded_at`, `loaded_by_worker_id`, `departed_at`, `departed_by_worker_id` (NULL).
- `prod_route_stops`: `delivered_at DATETIME NULL`, `delivered_by_worker_id INT NULL`,
  `stays_reason VARCHAR(32) NULL`, `stays_note VARCHAR(255) NULL` (czasowe „Zostaje” do zakończenia załadunku).

### 5.5 `prod_logistics_log`

ENUM akcji + `paczki`, `weryfikacja`, `weryfikacja_cofnieta`, `problem`, `problem_rozwiazany`, `cofniete_do_pakowania`,
`zaladunek`, `zostaje`, `wyjazd`, `dostarczone`, `niedostarczone`, `dostarczenie_cofniete`. Nowa kolumna
`worker_id INT NULL` (akcje z telefonów mają pracownika, nie użytkownika) i `device_id INT NULL`. Sposób (skan/ręcznie)
i powód idą w `note`.

## 6. Krok 4.1 — druk na dwóch drukarkach

### 6.1 CRM

- `LabelPrintJob` (`models.py:917`) dostaje `printer` (i `package_id`).
- `GET /api/print-agent/jobs` (`routers/api/print_agent_api.py:129`) przyjmuje `?printers=etykiety,wysylka`. **Bez
  parametru zwraca wyłącznie `etykiety`** — stary agent nigdy nie wyśle etykiety 100×150 na drukarkę 60×40. `ack`
  bez zmian (po id zadania). Wygaszanie przeterminowanych zadań (`_expire_stale_pending`) działa per zadanie jak dziś.
- Sygnał push (Centrifugo `print:agent`) bez zmian — agent i tak pobiera zadania zapytaniem.
- Ustawienia drukarki paczek w panelu konfiguracji produkcji (`prod_config`, jak `LABEL_PRINTER_*`):
  `PACKAGE_LABEL_OFFSET_X_DOTS`, `PACKAGE_LABEL_OFFSET_Y_DOTS` (przesunięcie w punktach dodawane do współrzędnych
  każdego pola — `^LH` nie przyjmuje wartości ujemnych; domyślnie 0, zakres ±120) i przycisk
  **„Wydruk próbny”** dla każdej drukarki (zadanie z etykietą testową: ramka 3 mm od krawędzi, bieżące przesunięcie, QR).
  Oba klucze zakłada migracja `2026-09-30-druk-klucze-przesuniecia.sql` (typ `integer`, wartość 0), a
  `config_service` waliduje je po nazwie klucza (liczba całkowita −120…120). Powód: zapis klucza bez wiersza w
  `prod_config` dostawał typ zgadywany z wartości (`json`/`string`) i omijał walidację.
- Stanowiska uprawnione do etykiet paczek: `packaging` i `verification` (stała, niezależna od
  `LABEL_PRINTER_ALLOWED_STATIONS` dla etykiet produktów) (przeniesione do kroku 4.2).

### 6.2 Agent (`tools/print_agent/`)

- `config.ini`: sekcje `[printer:etykiety]` i `[printer:wysylka]`, każda z `type = tcp` (`ip`, `port`, domyślnie
  9100) albo `type = windows` (`name` = nazwa kolejki wydruku Windows; surowe bajty przez `winspool.drv`
  `OpenPrinter/StartDocPrinter(RAW)/WritePrinter` na `ctypes`, bez zewnętrznych pakietów). Stara sekcja `[printer]`
  czytana jako `etykiety`. Nazwy drukarek nie rozróżniają wielkości liter.
- Agent pyta o zadania osobno dla każdej skonfigurowanej drukarki (jedno `GET` z `?printers=<nazwa>` na drukarkę),
  a kolejkę `etykiety` obsługuje zawsze **pierwszą** — martwa drukarka paczek nie opóźnia etykiet produktów.
- Nieudany wydruk przerywa partię tej drukarki: jedno zadanie dostaje `failed`, reszta partii zostaje `pending`.
  Osobnych liczników błędów ani ponowień per drukarka nie ma. Zadania innej drukarki (np. od starego serwera, który
  ignoruje `?printers=`) agent po cichu zostawia jako `pending`; ostrzeżenie o nieznanej nazwie drukarki pojawia się
  tylko przy wczytaniu konfiguracji.
- Nieudany zapis w trybie `windows` kończy się `AbortPrinter` (dokument jest anulowany, nie wysyłany do drukarki
  jako urwany). W tym trybie „sukces” oznacza „przyjęte przez spooler Windows”, a nie „wydrukowane” — agent nie
  widzi błędów samej drukarki (brak papieru, otwarta pokrywa).
- `python print_agent.py --kalibruj [nazwa]` wysyła TSPL `GAPDETECT` (kalibracja z 6.4 bez dodatkowych narzędzi na
  hubie); bez nazwy kalibruje drukarkę paczek.
- README: dwie drukarki, tryb `windows`, aktualizacja na komputerze hali (kopiowanie folderu, `config.ini`, restart).

### 6.3 Etykieta paczki (ZPL, 100×150 mm, 203 dpi = 800×1200 punktów)

Funkcja `package_label.generate_package_label_zpl(dane: DaneEtykietyPaczki, przesuniecie)` w
`modules/production/services/package_label.py`; kolejkowanie przez `print_queue_service.zakolejkuj_zpl(...)` (flush,
bez commita — commit i sygnał dla agenta robi wywołujący). Krok 4.2 buduje `DaneEtykietyPaczki` z `prod_packages`.
Tekst transliterowany do ASCII (polskie litery jak na etykietach produktów, reszta spoza ASCII usuwana),
`^ i ~` usuwane z danych. Treść w marginesie ≥ 3 mm,
dół treści ≤ 1130 punktów (zapas na przesunięcie). Układ (wzór wydrukowany 30.09 na zamówieniu 1450):

1. **Nagłówek:** „ZAMOWIENIE” i duży numer wewnętrzny; po prawej czarny kafel „PACZKA” / „PALETA” i „2 / 3”.
2. **Pas sposobu dostawy** (biały na czarnym): `KURIER`, `ODBIOR OSOBISTY`, `TRASA: <nazwa> <data>` albo
   `TRANSPORT WOODPOWER` (bez trasy), `NIE USTAWIONO`.
3. **Odbiorca — zanonimizowany** (uwaga Konrada po wzorze): z nazwy (osoba, a gdy jej brak — firma) dwa pierwsze
   słowa, z każdego 3 pierwsze znaki i `***`, gdy słowo jest dłuższe (np. „Dar*** Kow***”). **Żadnych danych
   adresowych** — bez ulicy, kodu pocztowego i miejscowości. Pełne dane są w CRM pod kodem paczki.
4. **QR** (`^BQN,2,11`, treść `P-<id>`) i obok: kod `P-<id>`, rodzaj i typ (`PALETA EUR 120x80`,
   `PALETA 150x100`, `PACZKA`), waga szacunkowa (m³ × `WAGA_KG_NA_M3`) jako wiersz `Waga szac.: ok. N kg` — bez `~`
   (w ZPL `~` zaczyna komendy sterujące, więc w etykiecie nie występuje nigdzie), „N poz. / N szt. / m³”, data spakowania.
5. **Zawartość zamówienia:** wiersze „n. Gatunek technologia klasa DxSxG cm … N szt.” (wykończenie, gdy nie surowe);
   do 14 wierszy, przy większej liczbie 13 wierszy i „+ N pozycji (N szt.) – pełna lista w CRM”.
6. **Stopka:** numer Base., numer zamówienia klienta (ucięty do 15 znaków, by całość mieściła się w jednej linii),
   „WoodPower, Bachorz 14N”.

Etykieta nie jest przedrukowywana automatycznie po zmianie sposobu dostawy albo trasy; panel pokazuje ikonę „etykiety
paczek sprzed zmiany” (jak dla etykiet produktów w etapie 1) (przeniesione do kroku 4.2). Ikona to porównanie napisu
zapamiętanego na paczce (`label_delivery_text`) z dzisiejszym; ponowny druk gasi ikonę. Ikona pokazuje się także na zamówieniach zamkniętych w Logistyce; dla nich napis porównujemy z trasą zamówienia także wtedy, gdy jest wykonana (decyzja Konrada 30.09).

### 6.4 Drukarka — ustalenia z testu 30.09

Xprinter XP-410B (firmware 1.038), etykiety 100×150 z przerwą 3 mm. **Emulacja ZPL działa**; polskie znaki poza Ó/ó
nie drukują się (strona kodowa 850) → ASCII. Przed kalibracją wydruk był przesunięty w dół i ucięty z boku; po
poprawieniu prowadnic boki są dobre, a po kalibracji czujnika przerwy (TSPL `GAPDETECT`) cała ramka 100×150 mieści się
na etykiecie z wolnym miejscem ok. 4 mm u góry i 2 mm na dole. Wniosek: **kalibracja `GAPDETECT` jest obowiązkowym
krokiem instalacji** (i po każdej zmianie rolki na inną), treść etykiety trzyma margines ≥ 3 mm, a resztę wyrównuje
przesunięcie w ustawieniach (6.1; na drukarce testowej ok. −8 punktów w pionie). Drukarka ma adres fabryczny spoza
sieci hali — konfiguracja sieci drukarki to krok wdrożenia 4.1, na hali.

Dalsze ustalenia z testu 30.09 (z Konradem, XP-410B):

- **Prędkość druku:** 3 cale/s (`^PR3`) daje wyraźnie lepszą czerń niż domyślne 6; komenda jest w etykiecie paczki i
  w wydruku próbnym (stała `PREDKOSC_DRUKU_CALE_S`). Ok. 2 s na etykietę nie ma znaczenia przy pakowaniu.
- **Ściskanie wydruku w pionie** brało się z tarcia dużej rolki opartej o spód drukarki (mechanika, nie ZPL). Przy
  instalacji na hali: uchwyt rolki zewnętrzny albo mniejsza rolka, potem `--kalibruj wysylka`, wydruk próbny i dopiero
  ustawienie przesunięcia.
- **Stan wdrożenia:** nowy agent działa na hali od 30.09 (etykiety produktów); drukarka paczek nie jest tam jeszcze
  podłączona.
- **Test kroku 4.2 (1.10, z Konradem, XP-410B, podgląd na kopii produkcji, kod 00c09009) — zaliczony w całości:**
  deklaracja 2 paczek („PACZKA 1 / 2”, „2 / 2”, pas „TRANSPORT WOODPOWER”, QR skanowany telefonem, odbiorca
  zanonimizowany, bez adresu); palety niestandardowej 150×100 (14 pozycji, pas „NIE USTAWIONO”); po zmianie sposobu
  dostawy w panelu zapala się ikona „etykiety paczek sprzed zmiany”, a ponowny druk (pas „ODBIOR OSOBISTY”) ją gasi.
  Ścieżka: deklaracja → kolejka CRM → agent (kolejka Windows) → drukarka → ACK.

## 7. Krok 4.2 — paczki na pakowaniu

### 7.1 Podpowiedź

W kolejce pakowania każda pozycja niesie (identyczny dla zamówienia) obiekt:
```json
"packing_hint": {"kind": "paleta", "count": 1, "pallet_type": "eur", "weight_kg": 298}
```
Waga = Σ(`volume_m3 × quantity`) niezanulowanych pozycji × `WAGA_KG_NA_M3` (800, `logistics/services/routes.py:32`);
`> PROG_PALETY_KG` (40) → paleta EUR ×1, w przeciwnym razie paczka ×1. Stałe w `logistics/sposoby.py`.

### 7.2 Deklaracja

- `PUT /api/mobile/orders/<internal_order_number>/packages` z
  `{"kind": "paczka|paleta", "count": 1..10, "pallet_type": "eur|niestandardowa|null", "length_cm": .., "width_cm": ..}`.
- Przyjmowana, gdy **wszystkie niezanulowane pozycje są `spakowane`** (inaczej 409 `order_not_packed`). Blokada po
  weryfikacji (409 `order_verified` — najpierw „Cofnij weryfikację”) **przeniesiona do kroku 4.3**: w 4.2 weryfikacji
  jeszcze nie ma.
- Unieważnia poprzednie paczki, tworzy N nowych, `packages_declared_at`, wpis `paczki` w logu, podbija `updated_at`
  pozycji (ETag), kolejkuje N etykiet na drukarkę `wysylka`. Idempotentna przez `X-Operation-Id`.
- Błędy (`error` + `message`): `invalid_packages` 422 — zły rodzaj, liczba poza 1..10, brak albo wymiar palety
  niestandardowej poza 20–400 cm, zły typ palety; pola bez znaczenia dla rodzaju (wymiar przy EUR i przy paczce, typ
  palety przy paczce) są **pomijane, nie odrzucane** (422 z kolejki offline to deklaracja utracona bez śladu; EUR ma
  zawsze 120×80). Liczby (`count`, wymiary) przyjmują też całkowity float (`2.0`); `1.5`, tekst i wartości logiczne to
  422. `order_not_found` 404, `station_not_allowed` 403 (paczki deklaruje i drukuje tylko `packaging` albo
  `verification`), `order_not_packed` 409.
- Numer wewnętrzny powtarza się co roku (licznik startuje od nowa), więc zamówienie to **najnowsze** o tym numerze
  (najwyższe `id`). Id ustalane zwykłym odczytem, a wiersz blokowany dopiero po kluczu głównym: kolumna
  `internal_order_number` nie ma indeksu i blokujący odczyt po niej założyłby blokady next-key na całej tabeli.
- Odpowiedź 200: `{"internal_order_number", "packages_declared_at", "packages": [{"id", "code" ("P-<id>"), "seq",
  "kind", "pallet_type", "length_cm", "width_cm", "label_print_count", "label_printed_at"}], "labels_queued", "message"}`.
- `GET /api/mobile/orders/<nr>/packages` (decyzja 30.09): aktualne paczki w tym samym kształcie (bez `labels_queued` i
  `message`), bez cache, dla każdego stanowiska — tablet pokazuje je i drukuje ponownie jedną albo wszystkie.
- Appka wysyła ją po „ZAKOŃCZ”, który domyka całe zamówienie: najpierw jak dziś zakończenia pozycji, potem deklaracja
  (kolejka offline zachowuje kolejność). Wcześniejsze raty pakowania (rzadkie: 10/742 zamówień od sierpnia pakowane w
  różne dni) nie pokazują okna.
- Kompatybilność: backend przyjmuje pakowanie bez deklaracji (stara appka, admin, hurtowa zmiana). Takie zamówienie
  ma na liście Weryfikacji plakietkę „BEZ PACZEK” i weryfikator deklaruje paczki na telefonie tym samym oknem. Nowa
  appka na starym backendzie dostaje 404 i pomija deklarację bez blokowania pakowania.

### 7.3 Ponowny druk

`POST /api/mobile/packages/<id>/print` (jedna) i `POST /api/mobile/orders/<nr>/packages/print` (wszystkie ważne) —
z tabletu pakowania i telefonu Weryfikacji. Błędy: `package_not_found` 404 (brak paczki o tym id), `package_void` 409
(unieważniona paczka), `no_packages` 409 (druk wszystkich dla zamówienia bez deklaracji), `station_not_allowed` 403.
Etykieta drukuje się **z bieżącymi danymi** zamówienia (pas sposobu dostawy, odbiorca, zawartość), a nie z chwili
deklaracji; zapisuje nowy `label_delivery_text`, więc gasi ikonę „sprzed zmiany”.

## 8. Krok 4.3 — statusy i Weryfikacja

### 8.1 Stanowisko

`verification` („Weryfikacja”) w `ProductionDevice.VALID_STATION_CODES`, `STATION_LABELS` (poza `STATION_ORDER`, jak
`sawmill`), `_STATION_CODES_WITH_TABLETS` (telemetria). Pracownik biura loguje się przez „Kto pracuje?” — musi mieć
wpis w `prod_workers`; stanowisko wymaga nagłówka `X-Worker-Ids` niezależnie od `WORKER_SELECTION_REQUIRED`
(400 `worker_required`). (krok 4.3) Nagłówek jest wymagany na **endpointach zapisu** Weryfikacji; odczyty (lista,
szczegóły zamówienia) go nie wymagają — nie ma czego przypisać. Zapisy mają `X-Operation-Id`; 400, 403, 404 i 409 są
„do ponowienia” (niezapamiętane, akcja zostaje w kolejce offline), 422 jest zapamiętane.

### 8.2 Lista „Do weryfikacji”

`GET /api/mobile/verification/orders` (ETag): zamówienia, których wszystkie niezanulowane pozycje są `spakowane`, plus
zamówienia z problemem. Każde z paczkami (`id`, kod, `seq`, rodzaj, stan weryfikacji), sposobem dostawy/trasą
(`transport`), klientem, miejscowością, flagą problemu i „BEZ PACZEK”. Kolejność: zamówienia z tras o najbliższej dacie
początku, potem według `packaging_completed_at` rosnąco. Filtry w appce: Wszystkie / Trasy / Kurier / Odbiór.

(krok 4.3) Doprecyzowania:
- **Zakres** (decyzja Konrada 30.09; dotyczy telefonu, filtra „Do weryfikacji” w panelu i licznika dashboardu):
  zamówienia, których wszystkie niezanulowane pozycje są `spakowane`, i które są **otwarte w Logistyce** albo
  **spakowane w ostatnich 7 dniach, nie wcześniej niż od wdrożenia kroku 4.3** (`logistyka_weryfikacja_od`, 5.3), plus
  **zawsze** zamówienia z otwartym problemem. Powód: na kopii produkcji z 28.09 jest 1512 zamówień w całości
  spakowanych (112 z ostatnich 7 dni) — bez zawężenia wszystkie trafiłyby na listę, a zamówienia kurierskie (zamykane
  przy spakowaniu) muszą na niej być przez 7 dni.
- **Lista telefonu zawiera też zamówienia `zweryfikowane`** (w tym samym zakresie): skaner rozpoznaje `P-<id>` lokalnie
  z listy, a „ponowny skan = OK bez zmian” i „Cofnij weryfikację” wymagają, żeby zamówienie zweryfikowane nadal było
  w telefonie. Licznik „Do weryfikacji: N” i filtr panelu liczą tylko `spakowane`.
- **Kolejność**: zamówienia z problemem nie mają osobnego miejsca — kolejność jak wyżej (trasa aktywna z najbliższą
  datą początku, potem `packed_at` rosnąco, potem numer).
- **ETag listy** zależy od dnia (okno dni przesuwa się bez zmian danych), liczby zamówień, najnowszego `updated_at`
  **zamówień** (problem, weryfikacja i dane klienta zmieniają same kolumny zamówienia, a nie pozycje), najnowszego
  `updated_at` i liczby pozycji (akcje Weryfikacji, deklaracje i zmiany tras podbijają pozycje) oraz stanu paczek
  (weryfikacja, wydruki); `KSZTALT_LISTY = 1`.
- **Plakietka „BEZ PACZEK”** (zamówienie do weryfikacji bez aktualnej deklaracji, np. po starej appce pakowania albo
  zmianie admina) ma **zakres filtra „Do weryfikacji”**: zamknięte w Logistyce zamówienia spoza okna dni, których nie
  pokazuje ani telefon, ani filtr, plakietki nie dostają (inaczej wyszukiwanie w panelu oznaczałoby historyczne
  zamówienia jako „BEZ PACZEK”). Okno liczy się raz na listę.

### 8.3 Akcje

| Endpoint | Działanie |
|---|---|
| `POST /verification/packages/<id>/verify` `{method}` | paczka zweryfikowana; ostatnia ważna → zamówienie `zweryfikowane` (pozycje, `verified_at`, log). Ponowny skan = OK bez zmian. Unieważniona → 409 `package_void`. Zamówienie z problemem → 409 `problem_open` |
| `POST /verification/packages/<id>/unverify` | cofnięcie sprawdzenia jednej paczki (4.5). Unieważniona → 409 `package_void`; pozycja przed spakowaniem → 409 `order_not_packed`; zamówienie załadowane albo dostarczone → 409 `order_status` (cofnięcia działają do załadunku). Paczka niesprawdzona → 200 `changed: false` bez zapisu i bez logu, bez sprawdzania zakresu listy (jak ponowny skan). Przed zapisem zakres listy (poza nim 409 `order_status`). Otwarty problem NIE blokuje. Zapis: znaczniki paczki czyszczone; jeśli wszystkie niezanulowane pozycje były `zweryfikowane`, wracają do `spakowane`, a `verified_at` i `verified_by_worker_id` zamówienia są czyszczone — pozostałe paczki zostają sprawdzone (stąd nie „Cofnij weryfikację”, które czyści wszystkie). Potem przeliczenie zamknięcia i podbicie pozycji. Log `weryfikacja_cofnieta` (`P-<id> sprawdzona` → `P-<id> niesprawdzona`) przy każdej zmianie. Odpowiedź jak `verify`; `order_verified` = stan po akcji (po cofnięciu zawsze `false`) |
| `POST /verification/orders/<nr>/verify-all` | wszystkie ważne paczki ręcznie (`reczne`) |
| `POST /verification/orders/<nr>/unverify` | tylko `zweryfikowane` i niezaładowane → pozycje `spakowane` |
| `POST /verification/orders/<nr>/problem` `{reason, note}` | flaga problemu; powody: `brak_elementu`, `uszkodzenie`, `etykieta`, `opakowanie`, `inne`. Tylko przed załadunkiem; zamówienie `zweryfikowane` wraca do `spakowane` (cofnięcie weryfikacji), więc bramka załadunku obejmuje też problemy |
| `POST /verification/orders/<nr>/problem/resolve` | zdejmuje flagę (log `problem_rozwiazany`) |
| `POST /verification/orders/<nr>/revert-to-packing` `{reason, note}` | 4.5; `repack_reason = "Weryfikacja: <powód>: <notatka>"`, flaga problemu przenoszona do banera |

Skaner w appce rozpoznaje `^P-\d+$` lokalnie z listy (działa bez zasięgu, akcja idzie kolejką offline); `N_S` (etykieta
produktu) otwiera zamówienie; inne kody → komunikat „Nieznany kod”.

(krok 4.3) Doprecyzowania kontraktu (pełny kształt: plan kroku 4.3, „Kontrakt API Weryfikacji”):
- **Kody błędów** (`{"error", "message"}`): `order_not_packed` 409 (pozycja przed spakowaniem), `order_status` 409
  (zamówienie już załadowane, dostarczone albo anulowane), `no_packages` 409 (weryfikacja bez deklaracji — 4.4),
  `order_not_verified` 409 (cofnięcie weryfikacji zamówienia niezweryfikowanego), `package_void` 409, `problem_open`
  409, `order_not_found` i `package_not_found` 404, `invalid_method` 422 (`method` to `skan` albo `reczne`, brak = `skan`),
  `invalid_problem` 422 (zły powód albo brak powodu cofnięcia do pakowania bez otwartego problemu),
  `station_not_allowed` 403, `worker_required` 400. Nowe w deklaracji paczek: `PUT /api/mobile/orders/<nr>/packages`
  na zamówieniu z pozycją `zweryfikowane`, `zaladowane` albo `dostarczone` → 409 `order_verified` („najpierw Cofnij
  weryfikację”).
- `problem` na zamówieniu, które ma już problem, **nadpisuje** powód i notatkę (200); `problem/resolve` bez problemu =
  200 bez zmian (kolejka offline nie może utknąć na 409). Notatka dłuższa niż 255 znaków jest **ucinana** (422 z kolejki
  offline to utracona akcja).
- **Współbieżność**: każdy zapis `/api/mobile/verification/*` bierze blokady w jednej kolejności: pracownicy
  (`touch_sessions`) → `paczki.zablokuj_deklaracje()` → zamówienie `FOR UPDATE` po kluczu głównym → paczki `FOR UPDATE`
  → pozycje `FOR UPDATE` po kluczu głównym (od kroku 4.4a: wszystkie pozycje zamówienia jednym odczytem po
  `order_id`). Stan, na którym zapis decyduje (paczki, potem pozycje), jest czytany
  **po** blokadzie odczytem bieżącym (`with_for_update().populate_existing()`): MySQL pracuje na REPEATABLE READ,
  a migawka powstaje przy pierwszym zwykłym odczycie transakcji (już w `before_request`), więc zwykły odczyt po
  blokadzie pokazałby stan sprzed czekania i po cichu nadpisał cudze przepakowanie, „Wydane klientowi” albo pierwszy
  z dwóch skanów. Reguła unieważniania (8.5) blokady globalnej nie bierze; gdy ma pracę, potwierdza ją odczytem
  bieżącym w tej samej kolejności (zamówienie → paczki → pozycje). Deklaracja paczek bierze ten sam odczyt bieżący,
  ale najpierw odmawia „nie w całości spakowane” na migawce, zanim sięgnie po pozycje: ostatnie „ZAKOŃCZ” trzyma
  pozycję i sięga po zamówienie, więc czekanie na pozycje pod blokadą zamówienia dawało 1213. Hurtowa zmiana statusu
  i cron logistyki blokują zamówienia rosnąco po id przed pozycjami.
  Wyścigi na dwóch sesjach MySQL (Task 10, kopia produkcji: 13 par operacji × 5 przebiegów i serie z opóźnieniem
  jednej strony, po fali poprawek powtórka w ponad 300 przebiegach) nie pokazują niespójności ani zakleszczeń w
  zapisach Weryfikacji, deklaracji paczek względem weryfikacji, „ZAKOŃCZ” i reguły, hurtowej zmianie statusu, ACK
  agenta druku ani w podwójnym skanie. Znany wyjątek: doróbka (`reject`) blokuje pozycję przed zamówieniem — w stanie
  sztucznym (paczki jeszcze ważne, pozycja już w pakowaniu) zakleszcza się z zapisem Weryfikacji, w stanie realnym
  0 z 11; ofiara dostaje 500, a ponowienie tym samym `X-Operation-Id` przechodzi (decyzja Konrada 1.10.2026: zostaje).
  Kolejność „zamówienie najpierw” dla wszystkich pisarzy stanowisk to osobne zadanie wstępne kroku 4.4, przed nowymi
  zapisami Dostawy.
  (krok 4.4a) Usunięte: ZAKOŃCZ, wejście do pakowania, doróbka i zmiany z Base. biorą zamówienie przed pozycją
  (`services/blokady_zamowien.py`); pozycje zamówienia czytane są jednym odczytem bieżącym po `order_id` (tak samo
  zapisy Weryfikacji i deklaracja paczek, `paczki.zablokuj_stan`), a zablokowane obiekty sesja trzyma silnymi
  referencjami. Pierwsza seria na kodzie sprzed tej poprawki dała 0 × 1213, ale niezgodne zamknięcia (odczyt
  bieżący nie wystarczał: odrzucone zablokowane obiekty były czytane od nowa z migawki, a pozycja dodana po migawce
  była niewidoczna). Wyścigi MySQL po poprawce (kopia produkcji, 1.10.2026, 873 przebiegi w 26 trybach; czysta
  bariera oraz rozjazd startu 0–40 i 0–15 ms): 0 × 1213, 0 odpowiedzi 500, 0 niezgodnych zamknięć. W tym
  `dorobka-weryfikacja` (w kroku 4.3 13 z 16 × 1213) 0 z 10, doróbka kontra ZAKOŃCZ w zamówieniu sąsiednim w indeksie
  pozycji (62), cron logistyki z pracą dla reguły kontra doróbka (62) i hurtowa zmiana statusu kontra ZAKOŃCZ (30).
  Import nowego zamówienia kontra ostatnie ZAKOŃCZ najnowszego zamówienia (62): import czeka na COMMIT ZAKOŃCZ
  (odczyt po `order_id` trzyma lukę indeksu za pozycjami najnowszego zamówienia); w przebiegach mediana żądania
  importu 171–207 ms wobec 141 ms samodzielnie, a oczekiwanie na blokady najwyżej 16 ms. Znane wyjątki bez
  naprawy: ręczna synchronizacja z `force_update` oraz `sync-cron` (`sync_paid_orders_only`) przy ponownym imporcie
  istniejącego zamówienia dopisują pozycje bez blokady zamówienia (cron importu dziś nie jest uruchamiany).

### 8.4 Cofnięcie do pakowania

Jak przepakowanie z etapu 1 (`delivery.py`): pozycje → `czeka_na_pakowanie`, `set_quantity_done('packaging', 0,
source='system')`, `packaging_completed_at = NULL`, `repack_required = 1`, paczki unieważnione, Base. 138620, po
ponownym spakowaniu status po spakowaniu według sposobu. `transport` dostaje `repack_reason` (dla przepakowania na
kuriera: „Przepakuj na kuriera”); `KSZTALT_ODPOWIEDZI_KOLEJKI` 4 → 5 (w kroku 4.3; 4 = `packing_hint` z kroku 4.2). Zamówienie na trasie zostaje na niej (kierowca
zobaczy „NIESPAKOWANE”).

(krok 4.3) `repack_reason` ustawia też przepakowanie na kuriera (`"Przepakuj na kuriera"`).
`transport.repack_reason` = `order.repack_reason` przy `repack_required`, a przy starym `repack_required` bez tekstu
(sprzed kroku 4.3) — `"Przepakuj na kuriera"`; bez przepakowania `null`. Ponowne spakowanie czyści oba pola. Zmiana
sposobu dostawy na inny niż kurier zdejmuje **tylko** baner „Przepakuj na kuriera”: baner z Weryfikacji („Weryfikacja:
Uszkodzenie: …”) to informacja o towarze, nie o kurierze, i zostaje do ponownego spakowania. Po „Cofnij do pakowania”
otwarty problem zamówienia przenosi się do banera w całości (flaga problemu znika).

Zamówienie kurierskie mogło już odjechać z kurierem, a CRM tego nie wie. Dlatego appka przed „Cofnij do pakowania”
zamówienia kurierskiego pyta „Paczka jeszcze na hali?”, a odpowiedź „Nie” nie wysyła cofnięcia (decyzja Konrada
1.10.2026). Backend nie ma parametru potwierdzenia: pytanie chroni przed pomyłką osoby z telefonem, a parametr
wysyłany zawsze przez tę samą appkę niczego by nie dodał.

### 8.5 Przejścia systemowe

- Wejście pozycji do produkcji w zamówieniu z paczkami (doróbka, nowa pozycja z Base.) → paczki unieważnione,
  `verified_at = NULL`, pozostałe pozycje wracają do `spakowane` (albo zostają niżej, jeśli nie były spakowane).
- `delivery.po_spakowaniu` bez zmian dla Base.; `przelicz_zamkniecie` według 4.6.
- (krok 4.3) **Doróbka albo nowa pozycja w zamówieniu dostarczonym** (decyzja Konrada 30.09): pozycje `dostarczone`
  zostają dostarczone (towar u klienta jest u klienta); paczki i weryfikacja kasują się, a pozycje `zweryfikowane`
  i `zaladowane` wracają do `spakowane`. Tę jedną regułę (`weryfikacja.uniewaznij_etapy`) woła każda ścieżka powrotu
  pozycji do produkcji: doróbka, synchronizacja z Base., przepakowanie na kuriera, „Cofnij do pakowania”, hurtowa zmiana
  statusu i cron `przelicz_otwarte` (łata resztę).
- (krok 4.3) Stara akcja z kolejki offline po weryfikacji (ponowione „ZAKOŃCZ” pakowania, powtórzony skan z tym samym
  `X-Operation-Id`) nie cofa zamówienia zweryfikowanego ani nie weryfikuje go drugi raz.

### 8.6 Przegląd miejsc z `'spakowane'` (każde: „dokładnie spakowane” czy „spakowane lub dalej”)

`logistics/services/{delivery.py, lista.py}`, `logistics/static/js/{logistics.js, logistics-map.js, logistics-routes.js}`,
`models.py`, `routers/{admin_routers.py, main_routers.py, mobile_api.py}`, `routers/api/{common_api.py, dashboard_api.py,
products_api.py, reports_api.py, sync_api.py}`, `routers/stations/monitors.py`,
`services/{baselinker_status_service.py, baselinker_status_sync.py (POSTPROD_STATUSES), daily_report_service.py,
dashboard_alerts.py, display_monitor_service.py, mobile_api_service.py (ARCHIVE_STATUSES :838), order_timeline_service.py,
reports_service.py}`, `static/js/modules/{archive-module.js, products-module.js}`,
`templates/components/{products-tab-content.html, reports/mix.html}`, `modules/dashboard/services/chart_service.py`.
Nowe statusy dostają etykiety i kolory w listach, filtrach i linii czasu (kroki Weryfikacja, Załadunek, Dostarczenie);
hurtowa zmiana statusu (`bulk_action`) **nie** oferuje nowych statusów.

### 8.7 Zmiana sposobu dostawy na spakowanym zamówieniu (decyzja Konrada 1.10.2026, z testu 4.2)

Dotyczy zamówienia **w całości spakowanego** (każda niezanulowana pozycja `spakowane` albo `zweryfikowane`). Zamówienia
częściowo spakowane działają jak dotąd: zmiana na kuriera z transportu albo odbioru sama przepakowuje spakowane pozycje,
a „Nie ustawiono” daje błąd. Blokady sprzed decyzji zostają i wygrywają z oknem: wydane klientowi, załadowane albo
dostarczone, utworzona przesyłka, trasa wykonana, trasa zatwierdzona przy zmianie zdejmującej z trasy.

Zamiast błędu (dawniej: „jest już spakowane — nie da się cofnąć do »Nie ustawiono«”) panel pokazuje okno przy **każdej**
zmianie sposobu na takim zamówieniu (select w wierszu, dymek mapy, hurt):

| Zmiana | Opcje w oknie |
|---|---|
| na „Nie ustawiono” | „Cofnij do pakowania”, „Anuluj” (bez przepakowania nie wolno — kolejny wybór nie wiedziałby, pod jaki sposób pakowano) |
| na kuriera z transportu własnego albo odbioru | „Cofnij do pakowania”, „Anuluj” (przepakowanie na kuriera jest obowiązkowe) |
| pozostałe (kurier → transport/odbiór, transport ↔ odbiór, „Nie ustawiono” → dowolny) | „Zmień bez przepakowania”, „Cofnij do pakowania”, „Anuluj” |

- **Zmień bez przepakowania** — jak dotąd: nowy sposób, status Base. po spakowaniu dla nowego sposobu, paczki i weryfikacja
  zostają, ikona „etykiety paczek sprzed zmiany” każe przedrukować etykiety.
- **Cofnij do pakowania** — mechanizm przepakowania: pozycje → `czeka_na_pakowanie`, paczki unieważnione, weryfikacja
  skasowana (reguła 8.5), `repack_required`, Base. 138620, nowy sposób zapisany (przy „Nie ustawiono” NULL — pakowanie
  czeka na decyzję logistyka, 409 `delivery_method_not_set`). Baner `repack_reason`: „Przepakuj na kuriera” (zmiana na
  kuriera z transportu albo odbioru), w pozostałych „Logistyka: zmiana sposobu dostawy na <sposób>” albo „Logistyka:
  sposób dostawy do ustalenia”. Kolejna zmiana sposobu przed ponownym spakowaniem przepisuje baner „Logistyka: …” na nowy
  sposób. Powód z Weryfikacji („Weryfikacja: …”) ma pierwszeństwo i nie jest nadpisywany. Ponowne spakowanie czyści baner.
- **Hurt** (zaznaczone zamówienia): jedno okno dla partii („N z zaznaczonych jest w całości spakowanych”). Gdy logistyk
  wybierze „Zmień bez przepakowania”, a część zamówień wymaga przepakowania, drugie okno pyta o nie osobno: „Cofnij je do
  pakowania” albo „Pomiń je”. „Anuluj” w dowolnym oknie nie wysyła niczego, także dla zamówień niespakowanych.
- **Backend** (`POST /production/api/logistics/orders/delivery-method`, pole `przepakowanie`: `true` | `false` | brak):
  w całości spakowane zamówienie bez decyzji nie zmienia się i trafia do `bledy` z `kod: "wymaga_decyzji_przepakowania"`
  i `opcje` (`["przepakuj"]` albo `["przepakuj", "bez_przepakowania"]`); `false` przy przepakowaniu obowiązkowym → `bledy`
  z `kod: "wymaga_przepakowania"`. Stary front (karta otwarta w czasie wdrożenia) pokazuje to jako zwykłą odmowę z
  komunikatem. Decyzja zapada pod blokadą tras i blokadami wierszy zamówień (rosnąco po id), na migawce utworzonej po
  tych blokadach; pozycji panel nie blokuje przed zamówieniem (do kroku 4.4a stanowiska brały pozycję przed zamówieniem;
  od 4.4a biorą zamówienie najpierw).
- **Odstępstwa z realizacji** (1.10.2026):
  - Panel nie bierze blokady deklaracji paczek (`paczki.zablokuj_deklaracje`): wiersz zamówienia `FOR UPDATE`
    serializuje go z Weryfikacją i deklaracją, bo obie biorą zamówienie przed paczkami.
  - Pole `przepakowanie` poza `true`, `false`, `null` i brakiem pola daje 422 „Pole przepakowanie musi mieć wartość
    true albo false.” (`1`, `"tak"`, `[]` nie przechodzą za decyzję).
  - API tabletów (zmiana względem 8.4): `transport.repack_required` jest prawdziwe tylko przy przepakowaniu na
    kuriera. Baner „Logistyka: …” i „Weryfikacja: …” idzie wyłącznie jako `transport.repack_reason`, bo stara appka
    (1.6.4) pokazuje baner przy samym `repack_required` i wyświetlałaby błędne „PRZEPAKUJ NA KURIERA”. Skutek:
    stara appka nie pokaże banera z innego powodu niż kurier, nowa pokazuje go z `repack_reason`.
  - Powód reguły unieważniania etapów to „cofnięcie do pakowania z panelu” także dla dawnego automatycznego
    przepakowania na kuriera (wcześniej „przepakowanie na kuriera”); zmienia się tylko notatka w logach `paczki` i
    `weryfikacja_cofnieta` oraz komunikat wygaszonego zadania druku.
  - „Nie ustawiono” z cofnięciem do pakowania zostawia `repack_required = 1`, baner „Logistyka: sposób dostawy do
    ustalenia” i sposób NULL; tablet odmawia pakowania (409 `delivery_method_not_set`) do ustawienia sposobu.
  - Front: ikona wiersza i legenda mówią „wróciło do pakowania, czeka na ponowne spakowanie” (`repack_required`
    ustawia teraz każda zmiana z cofnięciem, nie tylko przepakowanie na kuriera); fokus startowy okna jest na „Anuluj”,
    żeby Enter nie cofnął zamówienia przypadkiem; zamówienie z hurtu, które już ma docelowy sposób, nie dostaje okna
    (serwer odpowie „bez zmian”); gdy dane w przeglądarce są starsze niż serwer (zamówienie spakowano po odświeżeniu
    listy), odmowa `wymaga_decyzji_przepakowania` otwiera okno, a wysyłka idzie jeszcze raz (tylko raz). Komunikaty
    wyniku: „Zamówienie {nr} wraca do pakowania.”, „Wracają do pakowania: {numery}.”, „Pominięto (wymagają cofnięcia
    do pakowania): {numery}.”, „Anulowano zmianę sposobu dostawy: {numery}.”.
- **Współbieżność** (wyścigi na dwóch sesjach MySQL, kopia produkcji, 1.10.2026): zmiana sposobu z
  `przepakowanie=true` kontra ponowne „ZAKOŃCZ” zamówienia w całości spakowanego, deklaracja paczek, weryfikacja
  ostatniej paczki z telefonu i hurt dwóch zamówień kontra cron logistyki, po 62 przebiegi każdy (czysta bariera i
  rozjazd startu 0–40 ms oraz 0–15 ms), nie dały ani jednego 1213, odpowiedzi 500 ani ważnej paczki na cofniętym
  zamówieniu. Jedyne zakleszczenie pomiaru to dosłowne ostatnie „ZAKOŃCZ” na zamówieniu spakowanym w połowie przy
  zmianie z kuriera na odbiór (11 z 62 przebiegów), ale to nie jest granica problemu. Blokada zamówień panelu
  (`panel_api.py`, `FOR UPDATE` rosnąco po id) trzyma zamówienia przez całą pętlę zmiany, a stanowisko (ZAKOŃCZ,
  wejście do pakowania) najpierw zapisuje pozycję, potem zamówienie (`odnotuj_wejscie_do_pakowania`,
  `po_spakowaniu`). Okno 1213 dotyczy więc KAŻDEJ zmiany sposobu na zamówieniu, które ma pozycję w ruchu na
  stanowisku, a nie tylko „ostatniego ZAKOŃCZ przy kurier → odbiór”. Ściśle: zakleszczenie wymaga, żeby transakcja
  stanowiska zapisała wiersz zamówienia — przy wejściu ostatniej pozycji do pakowania (puste
  `logistics_completed_at`) albo przy „ZAKOŃCZ” pakowania, które zmienia zamknięcie, flagi przepakowania lub zaległy
  138620; w pozostałych przypadkach stanowisko tylko czeka na blokadę. Ofiarą może być też stanowisko, np. przy dużym
  hurcie. Obie strony ponawiają: panel jedną automatyczną próbą po 1213 (`delivery_method` w `panel_api.py`), a
  tablet kolejką offline. Poprawność się nie pogorszyła, bo dodatek usunął przeplot z decyzją panelu na starej
  migawce; pogorszyła się dostępność. Właściwa poprawka to zadanie wstępne kroku 4.4 („zamówienie najpierw” dla
  stanowisk, decyzja Konrada 3).
  (krok 4.4a) Po zmianie kolejności blokad stanowisk tryb ostatniego ZAKOŃCZ na zamówieniu spakowanym w połowie:
  0 × 1213 i 0 błędnych zamknięć w 82 przebiegach (62 na kodzie `20fee377` i 20 na końcowym `5f7d5620`). Na kodzie sprzed
  poprawki odczytu pozycji (`32469b9c`) ten sam tryb dawał 0 × 1213, ale 27 z 62 błędnych zamknięć (w kroku 4.3: 11 z
  62 × 1213 i 11 z 62 zamkniętych odbiorów).

## 9. Krok 4.4 — Dostawa

### 9.1 Stanowisko i kierowca

`delivery` („Dostawa”) jak w 8.1. Serwer bierze kierowcę z pierwszego `X-Worker-Ids`; bez `is_driver` → 403
`not_a_driver`. Katalog pracowników dla appki (`serialize_worker_for_mobile`) dostaje `is_driver`; bramka stanowiska
Dostawa pokazuje tylko kierowców.

### 9.2 Moje trasy

`GET /api/mobile/delivery/routes`: trasy z `driver_worker_id` = kierowca, status `zatwierdzona`/`zaladowana`/`w_trasie`,
`date_to >= dziś` (Europe/Warsaw), najbliższa `date_from` pierwsza. `GET /delivery/routes/<id>` (ETag): przystanki w
kolejności z zamówieniem, adresem, telefonem (`client_phone`), współrzędnymi (`prod_order_geo`, gdy dokładne), paczkami
(kody, stany) i stanem zamówienia (`zweryfikowane` / „NIEZWERYFIKOWANE” / „NIESPAKOWANE” / problem).

### 9.3 Załadunek (trasa `zatwierdzona`)

- Lista domyślnie w odwrotnej kolejności przystanków (przełącznik w appce).
- `POST /delivery/packages/<id>/load` `{method}`: paczka musi być ważna, na tej trasie i z zamówienia `zweryfikowane`
  (409 `package_void` / `package_not_on_route` z nazwą trasy albo „bez trasy” / `order_not_verified`). Ponowny skan = OK.
- `POST /delivery/packages/<id>/unload` — cofnięcie pomyłki przed zakończeniem.
- `POST /delivery/routes/<id>/stops/<order>/stays` `{reason, note}` i `DELETE …/stays`; powody: `niespakowane`,
  `niezweryfikowane`, `brak_miejsca`, `uszkodzone`, `inne`. Ustawienie czyści znaczniki załadunku paczek zamówienia.
- `POST /delivery/routes/<id>/finish-loading`: każdy przystanek ma wszystkie ważne paczki załadowane albo „Zostaje”, i
  co najmniej jeden jest załadowany (inaczej 409 z listą braków; trasę, z której nic nie jedzie, logistyk cofa albo
  usuwa w panelu). Pod blokadą tras: „Zostaje” → zdjęcie z trasy
  (`routes.usun_przystanek`, log `zostaje` + `trasa_usuniete` z powodem); załadowane → pozycje `zaladowane`, Base.
  `STATUS_ZALADOWANE = 524520` (nowa stała w `sposoby.py`; status założony przez Konrada 30.09, sprawdzony w Base.);
  trasa → `zaladowana`, `loaded_at/by`.
- Raporty: 524520 i 417343 dopisane do listy statusów „Wyprodukowane” (`modules/reports/models.py:688`, obok 149763)
  i do słownika nazw statusów (`STATUSY_BASELINKER` w `modules/reports/service.py`, `modules/baselinker/routers.py`) — inaczej
  zamówienia załadowane i zaplanowane na trasę wypadają z „Wyprodukowane”, a Analiza sprzedażowa pokazuje „Status N”.

### 9.4 Wyjazd

`POST /delivery/routes/<id>/depart` (trasa `zaladowana`) → `w_trasie`, `departed_at/by`, Base. 149763 dla
załadowanych zamówień (`bl_sync.oznacz_wyslane` + `po_zmianie`).

### 9.5 Dostarczenia (trasa `w_trasie`)

- Przystanki w kolejności trasy; appka: „Nawiguj” (Google Maps ze współrzędnymi albo adresem), „Zadzwoń”.
- `POST /delivery/routes/<id>/stops/<order>/delivered` → pozycje `dostarczone`, `delivered_at/by`, Base. 149778
  (`bl_sync.oznacz_dostarczone`), `przelicz_zamkniecie`.
- `POST …/not-delivered` `{reason, note}`; powody: `brak_klienta`, `odmowa`, `brak_dojazdu`, `uszkodzenie`, `inne`
  → 4.5.
- `POST …/undo-delivered` — tylko ostatnie dostarczenie, trasa `w_trasie`.
- Brak nierozliczonych przystanków → trasa `wykonana` (`completed_at`, log z pracownikiem).

### 9.6 Offline i współbieżność

Trasa z kodami paczek leży w telefonie; skany rozpoznawane lokalnie, akcje w kolejce offline (idempotentne,
`X-Operation-Id`, błędy 4xx nie zapamiętywane — jak `BLEDY_DO_PONOWIENIA`). Każdy zapis Dostawy zaczyna od
`routes.zablokuj_trasy()` i czyta stan odczytem bieżącym (reguła z CLAUDE.md gałęzi).

### 9.7 Zmiany w panelu tras (etap 3)

- Sekcje listy tras: Robocze, Zatwierdzone, **Załadowane**, **W trasie**, Wykonane (od 2.10 „Dostarczone”, 9.8);
  kłódka i postęp
  „załadowano 7/8 · dostarczono 3/7” w nagłówku edytora; przy przystanku paczki i stany.
- **„Cofnij załadunek”** (trasa `zaladowana`) — 4.5.
- **„Odhacz jako dostarczoną”** (do 2.10 „Odhacz jako wykonaną”; z `zatwierdzona`/`zaladowana`/`w_trasie`):
  zaznaczone → jak „Dostarczone” (pozycje
  `dostarczone`, 149778); odznaczone → jak „Niedostarczone” z powodem `odhaczone_w_panelu`. Wymóg „spakowane lub
  dalej” zostaje. **Zmiana względem etapu 3:** odhaczenie wysyła statusy do Base.
- **„Przywróć trasę” znika**; zastępuje ją **„Cofnij dostarczenie”** przy przystanku (4.5).
- Zajętość pojazdów i kierowców liczy `zaladowana` i `w_trasie` jako aktywne.

### 9.8 Doprecyzowania kroku 4.4 (plan 4.4b)

Odstępstwa od 9.1–9.7 i rozstrzygnięcia z realizacji (plan 4.4b, decyzje Konrada z 1.10). Gdzie tekst różni się od
9.1–9.7, wygrywa ta sekcja.

Dostawa częściowa („Zostaje” na pojedynczej paczce) odrzucona przez Konrada 2.10 — zamówienie jedzie zawsze w całości.

**Ścieżki i bramki**
- **Ścieżki z trasą.** Załadunek i jego cofnięcie to `POST /api/mobile/delivery/routes/<route_id>/packages/<package_id>/load|unload`
  (nie `/delivery/packages/<id>/load`): odmowa `package_not_on_route` potrzebuje trasy, w kontekście której kierowca
  skanuje. Przystanki adresowane po `order_id`, nie po numerze wewnętrznym (powtarza się co rok).
- **Wszystkie endpointy z kierowcą.** Każdy endpoint telefonu, także odczyty (to „Moje trasy” tego kierowcy), wymaga
  `X-Worker-Ids` z kierowcą na pierwszym miejscu: brak → 400 `worker_required`, pracownik bez `is_driver` albo
  nieaktywny → 403 `not_a_driver`. Zapisy na trasie przyjmujemy od każdego aktywnego kierowcy (nie szkodzi), a appka
  pokazuje tylko trasy zalogowanego. Zastępstwo załatwia wyłącznie zmiana kierowcy w panelu: przed załadunkiem „Cofnij
  zatwierdzenie”, zmiana kierowcy, zatwierdzenie (decyzja 5). Nie ma parametru „wszystkie trasy”.
- **Kody odmów.** Każda odmowa serwisu ma kod (`error`), komunikat po polsku (`message`) i pola dodatkowe (np. `braki`);
  400/403/404/409 nie są zapamiętywane przez idempotencję (`BLEDY_DO_PONOWIENIA`), 422 tak. Trasa skasowana w trakcie
  żądania → 404 `route_not_found`; trasa robocza dla telefonu to także 404 (nie jest dla kierowcy). Zapis telefonu robi
  rollback przy każdej odmowie, więc odmowa niczego nie zostawia w sesji.
- **Zakres „Moich tras”.** Trasy kierowcy `zatwierdzona` z `date_to >= dziś` oraz `zaladowana` i `w_trasie` bez względu
  na datę (rozpoczęta trasa nie znika z telefonu o północy). Trasa zatwierdzona z rozpoczętym załadunkiem (paczka ze
  znacznikiem tej trasy) zostaje także po dacie końca. Szczegóły trasy (`GET /delivery/routes/<id>`) także dla
  `wykonana` (ekran po zamknięciu i cofnięcie ostatniego dostarczenia); trasa robocza → 404.
- **Punkt nawigacji.** Telefon podaje współrzędne tą samą regułą co eksport Routimo (`geocoding.punkt_do_nawigacji`):
  tylko punkt dokładny, aktualny dla adresu zamówienia; ręczny punkt po zmianie adresu (inny `address_hash`) nie jest podawany.
- **Postęp.** Liczniki `paczki.zaladowane` i `postep` liczą tylko znaczniki załadunku tej trasy (paczka załadowana na inną
  trasę się nie liczy).

**Załadunek**
- **Zakończenie załadunku i jego braki.** Przystanek „załadowany” = co najmniej jedna aktualna paczka, wszystkie aktualne
  paczki załadowane na tę trasę i pozycje nadal `zweryfikowane` (odczyt bieżący). Przystanek zamówienia anulowanego w całości
  jest zdejmowany z trasy (notatka „anulowane”) zamiast blokować. Braki → 409 `loading_incomplete` z listą `braki`
  (`niezaladowane`, `niezweryfikowane`, `bez_paczek`; powód `niezweryfikowane` sprawdzany przed `niezaladowane`); nic
  załadowanego → 409 `nothing_loaded`.
- **Skan paczki z przystanku „Zostaje”** → 409 `stop_stays` („najpierw zdejmij »Zostaje«”), bez cichego zdejmowania oznaczenia.
- **Ruling 21b: „Cofnij zatwierdzenie” trasy z rozpoczętym załadunkiem** czyści znaczniki załadunku paczek tej trasy pod
  blokadami Dostawy (trasy, deklaracje, zamówienia rosnąco, paczki i pozycje), z wpisem `zaladunek` (notatka „cofnięte
  zatwierdzenie trasy”). Odmowa 409 odpadła: panel nie ma rozładunku częściowo załadowanej trasy zatwierdzonej, więc logistyk
  zostałby w pułapce. Zastępstwo kierowcy w trakcie załadunku zeruje więc postęp (paczki trzeba zeskanować ponownie).
- **Ruling 25: zamówienie zdjęte z trasy.** Zamówienie zdjęte z trasy („Niedostarczone”, odznaczenie w „Odhacz”) wraca do puli
  „Transport bez trasy”: pozycje `zaladowane` → `zweryfikowane`, a gdy zamówienie nie jest zweryfikowane (`verified_at` NULL;
  trasa odhaczona bez załadunku, potem cofnięte dostarczenie) → `spakowane`, bo „zweryfikowane” bez weryfikacji ominęłoby
  bramkę załadunku. „Cofnij zatwierdzenie” zdejmuje też flagi „Zostaje” przystanków trasy (powrót do roboczej to nowy
  załadunek od zera; wpis `zostaje` z tą samą notatką).
- **Log.** `zaladunek` przy zakończeniu załadunku (brak → `zaladowane`, notatka: opis paczek) i przy „Cofnij załadunek”
  (`zaladowane` → brak, notatka „cofnięty w panelu”); `zostaje` przy zdjęciu przystanku z powodem; `wyjazd`; `dostarczone`;
  `niedostarczone` (notatka: powód i opis; wpis idzie po zdjęciu przystanku, więc jest ostatnim wpisem zamówienia);
  `dostarczenie_cofniete` tylko wtedy, gdy któraś pozycja się zmieniła; zmiany statusu trasy jak dotąd `trasa_status`,
  z jednym wyjątkiem: „Ruszam” (`zaladowana` → `w_trasie`) zapisuje wyłącznie wpis `wyjazd`, bez `trasa_status`.
  Wpis `trasa_usuniete` przy niedostarczeniu ma notatkę `niedostarczone` jak w etapie 3.

**Wyjazd i dostarczenia**
- **Powtórki z kolejki offline bez zmian (Ruling 23 i 26).** `finish-loading` na trasie `zaladowana`/`w_trasie` → 200
  `{changed: false, removed: []}` (pierwsze zakończenie ma `changed: true`); `depart` na trasie `w_trasie`/`wykonana` → 200
  `{changed: false}`; `not-delivered` po udanym zdjęciu przystanku → 200 `{changed: false, route_completed: false}`, gdy
  OSTATNI wpis logu zamówienia to niedostarczenie z tej trasy, także na trasie, którą to niedostarczenie zamknęło (każdy inny
  brak przystanku → 404 `stop_not_found`). Spóźnione „Niedostarczone” po odznaczeniu zamówienia w panelu też dostaje 200,
  a powód kierowcy nie jest zapisywany (zostaje wpis panelu `odhaczone_w_panelu`). Każde 200 zapisu zawiera pełną trasę
  (`route`) i `message`, także przy `changed: false`: appka podmienia trasę z odpowiedzi i zdejmuje wpis z kolejki.
- **Cofnięcie ostatniego dostarczenia z telefonu także po automatycznym zamknięciu trasy** (decyzja 3; odstępstwo od 9.5):
  trasa `w_trasie` albo `wykonana` zamknięta ostatnim dostarczeniem z telefonu (`completed_by` NULL) wraca do `w_trasie`.
  Trasa odhaczona w panelu (`completed_by` ustawione, pole `completed_by_panel` w odpowiedzi) — tylko panel. „Ostatnie” =
  przystanek z najpóźniejszym `delivered_at` (remis: wyższa pozycja).
- **Trasa bez przystanków po ostatnim „Niedostarczone”** zamyka się jako `wykonana` (kierowca wrócił ze wszystkim).
- **Każdy zapis Dostawy blokuje zamówienia całej trasy**, nie tylko przystanku, którego dotyczy: odpowiedź telefonu (pełna
  trasa) jest liczona z tych samych blokad, na odczycie bieżącym, więc dwa telefony na jednej trasie widzą swoje zapisy
  nawzajem. Kolejność blokad: pracownicy (tylko telefon), blokada tras, blokada deklaracji paczek, zamówienia rosnąco po id,
  paczki, pozycje (CLAUDE.md, „Dostawa”).

**Panel tras**
- **„Cofnij dostarczenie”** (zamiast „Przywróć trasę”): dowolny dostarczony przystanek trasy `w_trasie` albo `wykonana`;
  trasa wykonana wraca do `w_trasie`. Bez sprawdzania zajętości pojazdu i kierowcy (korekta, nie planowanie).
- **„Odhacz jako dostarczoną”** zostaje dostępne także z roboczej (ruling R12 etapu 3; 9.7 wymienia zatwierdzoną, załadowaną
  i w trasie). Przystanki już dostarczone są zawsze dostarczone (okno pokazuje je zaznaczone i zablokowane). Odznaczony
  przystanek: Ruling 25, Base. 417343 tylko gdy zamówienie było załadowane (zamówienie z trasy zatwierdzonej ma 417343
  od spakowania).
- **Routimo.** Eksport z `zatwierdzona`, `zaladowana`, `w_trasie` i `wykonana` (4.3 i plan mówiły „bez wykonanej”;
  dziś wykonana jest dozwolona, ruling R11 etapu 3, i zostaje — 4.3 poprawione).
- **Etap „W trasie”** na liście Logistyki: pozycje `zaladowane`, a trasa zamówienia `w_trasie`. To etap zamówienia na liście
  (`lista._etap`), nie status pozycji, więc filtr `etap=zaladowane` nie zwraca zamówień z trasy w drodze.

**Fala końcowa (2.10, po przeglądzie całej gałęzi)**
- **Decyzja Konrada A1 — hurt na „spakowane” cofa weryfikację.** Hurtowa zmiana statusu na `spakowane` na zamówieniu
  zweryfikowanym (`verified_at` albo pozycja `zweryfikowane` przed zmianą) działa jak „Cofnij weryfikację”
  (`weryfikacja.cofnij_weryfikacje_zamowienia`, tabela w 4.5), pod blokadami hurtu i z jego ponowieniem po 1213; gdy
  reguła unieważniania etapów zrobiła to już sama, drugi raz nie cofa. Base. bez zmian, jak przy „Cofnij weryfikację”.
- **Decyzja Konrada A2 — powrót do produkcji z trasy załadowanej albo w drodze.** Hurt (status produkcyjny albo
  `spakowane`) odmawia zamówieniu, którego przystanek jest na trasie `zaladowana`/`w_trasie`: błąd per zamówienie
  w `errors` (jego zaznaczone pozycje w `failed_count`), reszta zaznaczonych przechodzi; gdy odmowa obejmuje wszystkie
  zaznaczone pozycje — 409 z `error`, bez zapisów. Anulowanie przechodzi (Dostawa obsługuje anulowane). Zamówienie
  z przystankiem już dostarczonym na trasie w drodze dostaje komunikat „…najpierw Cofnij dostarczenie” (Ruling 30).
  Doróbki nie da się odmówić, więc zdejmuje zamówienie z takiej trasy jak „Niedostarczone”
  (`dostawa.zdejmij_z_trasy_w_drodze`; skutki w 4.5). Kolejność blokad obu: **globalna blokada tras najpierw** (hurt:
  blokada tras → odczyt bieżący przystanków i tras zaznaczonych zamówień → zamówienia rosnąco → pozycje; doróbka:
  blokada tras → odczyt blokujący przystanku → na trasie załadowanej albo w drodze blokady Dostawy CAŁEJ trasy
  (`dostawa.blokady_trasy_w_drodze`: deklaracje paczek → zamówienia rosnąco → paczki → pozycje), inaczej samo
  zamówienie → pozycje → reguła unieważniania → zdjęcie), czyli kolejność Dostawy. Zamówienia wszystkich przystanków
  blokujemy przed zapisami (Ruling 30), bo zdjęcie może zamknąć trasę, a zamknięcie decyduje na nich (C2 — przystanek
  anulowanego w całości jest rozliczony) i zapisuje przy nich `trasa_status`; blokowanie ich dopiero po własnym
  zamówieniu odwróciłoby rosnącą kolejność crona logistyki.
- **Zmiana z Base. jak doróbka (Ruling 30).** Zmiana z Base., która cofa do produkcji zamówienie z trasy załadowanej
  albo w drodze (nowa pozycja z Base.), zdejmuje je z trasy tak samo (powód `zmiana_base`, notatka „zmiana z Base.”).
  Kolejność: wywołanie Base. (HTTP) przed blokadami → id zamówienia zwykłym odczytem jeszcze w starej transakcji
  (powiązanie z `baselinker_order_id` się nie zmienia) → COMMIT → blokada tras → odczyt blokujący przystanku → blokady
  Dostawy całej trasy w drodze albo samo zamówienie → pozycje; między COMMIT-em a blokadą zamówień same odczyty
  blokujące, więc zwykłe odczyty pod blokadą widzą stan bieżący. Zmiana, która nie cofa do produkcji (ilość, nazwa),
  zostawia przystanek. Status Base. wysyła dopychacz po wyniku (router zmian z Base.).
- **Pusta trasa (Ruling 30).** Doróbka albo zmiana z Base. na jedynym przystanku trasy załadowanej zostawia trasę bez
  przystanków. „Ruszam” takiej trasy → 409 `route_status` „Trasa nie ma przystanków — logistyk cofnie załadunek albo
  odhaczy ją w panelu tras.” (trasa w drodze bez przystanków nie zamknęłaby się sama). W panelu: „Cofnij załadunek”
  albo „Odhacz” — pustą trasę załadowaną albo w drodze odhaczenie zamyka jako dostarczoną (`wykonana`; pusta lista dostarczonych,
  zapis tylko na trasie: bez wpisów logu i bez Base.). Pusta robocza i zatwierdzona — jak dotąd 422.
- **417343 przy zdjęciu z trasy w drodze (Ruling 30).** „Niedostarczone” i odznaczenie w „Odhacz” z trasy załadowanej
  albo w drodze zawsze wysyłają „Planowana trasa” (Base. ma wtedy „Załadowane” albo „Wysłane”, także gdy pozycje
  cofnięto wcześniej), poza zamówieniem anulowanym w całości (Base. ma status anulowania); z trasy roboczej
  i zatwierdzonej — jak dotąd tylko po załadunku. Spójnie z doróbką i zmianą z Base.
- **Spóźnione „Dostarczone” po powrocie do produkcji (Ruling 30).** Przystanek zdjęty przez doróbkę albo zmianę
  z Base. (ostatni wpis logu: niedostarczenie z tej trasy z powodem `dorobka`/`zmiana_base`): 404 `stop_not_found`
  z komunikatem „Zamówienie wróciło do produkcji i zostało zdjęte z trasy.” Spóźnione „Niedostarczone” — powtórka
  (Ruling 26).
- **Front hurtu (Ruling 30).** Panel produktów pokazuje pominięte zamówienia z komunikatami serwera (osobne
  ostrzeżenie), gdy hurt zmienił tylko część zaznaczonych.
- **Ponowienie po 1213 (B1).** Dostawa blokuje pozycje wszystkich zamówień trasy w kolejności (zamówienie, id), a trasa
  robocza i zatwierdzona może mieć zamówienia w produkcji (doróbka dokłada starszemu zamówieniu pozycję o wyższym id).
  Z pisarzami wielu pozycji bez blokady zamówień (przeliczenie i przeciąganie priorytetów, druk TCP) rzadkie 1213 jest
  więc możliwe, jak w hurcie. Zapis telefonu (`dostawa_api._zapis`) i akcje Dostawy w panelu tras (odhaczenie, „Cofnij
  załadunek”, „Cofnij dostarczenie”, „Cofnij zatwierdzenie”) ponawiają się raz: rollback, porzucenie planu dopychacza
  Base. z tej próby i cały zapis od nowa, z decyzją na nowym stanie. Telefon ponawia wewnątrz handlera, więc wpis
  idempotencji powstaje raz; „Cofnij zatwierdzenie” zaczyna każdą próbę od nowej transakcji pod blokadą tras. Drugie
  1213 i inny kod — 500 bez zapisów (telefon: wpis niezapamiętany).
- **Powtórka „Niedostarczone” na odczycie bieżącym (C1, Ruling 26).** Ostatni wpis logu zamówienia czytamy odczytem
  blokującym (współdzielonym) pod blokadami Dostawy, a nie z migawki: w wyścigu z „Odhacz”, drugim telefonem albo przy
  zdublowanym `X-Operation-Id` kierowca dostawał 404 zamiast 200 bez zmian. Wpisy logu zamówienia piszą tylko
  posiadacze blokady tras albo blokady tego zamówienia, a po tym odczycie zapis Dostawy na nic już nie czeka.
- **Przystanek zamówienia anulowanego w całości jest rozliczony (C2).** Klient anulował zamówienie po zakończeniu
  załadunku: liczniki liczą tylko przystanki aktywne, więc trasa zamyka się po ostatnim realnym dostarczeniu
  („Dostarczone” albo „Niedostarczone”), a przystanek anulowany nie musi mieć `delivered_at`.
- **„Zostaje” znika przy dostarczeniu (C3).** Przystanek z flagą „Zostaje” zaznaczony jako dostarczony w „Odhacz”
  traci flagę (wpis `zostaje`: powód → brak, notatka „oznaczone jako dostarczone”).
- **Dostarczenie z panelu cofa tylko panel (C4).** Telefon cofa wyłącznie dostarczenie kierowcy
  (`delivered_by_worker_id` ustawione); dostarczenie zaznaczone w panelu (także przystanek anulowanego) ma je puste —
  telefon dostaje 409 `route_status` „To dostarczenie zaznaczył logistyk w panelu — cofnąć może tylko panel.”, także
  gdy po „Cofnij dostarczenie” w panelu trasa wróciła do `w_trasie` z `completed_by` NULL.
- **Spóźnione „Dostarczone” po odznaczeniu w panelu (C5).** Przystanku już nie ma, a ostatni wpis logu zamówienia to
  niedostarczenie z tej trasy z powodem `odhaczone_w_panelu` (odczyt bieżący jak w C1): kod bez zmian, 404
  `stop_not_found`, komunikat „Logistyk zdjął to zamówienie z trasy w panelu.”

**Oględziny 2.10 (Konrad) — nazwy i kontrakt**
- **Status `wykonana` dla ludzi to „Dostarczona” (U7).** Wartość w bazie i API zostaje `wykonana`. Plakietki i etykiety
  statusu w panelu, sekcja listy tras „Dostarczone”, komunikaty panelu i odmowy serwera mówią „dostarczona”; przycisk
  i okno odhaczenia to „Odhacz jako dostarczoną”.
- **Kontrakt API Dostawy:** `status_label` trasy (`TrasaKrotko`, `Trasa`) przyjmuje „Zatwierdzona”, „Załadowana”,
  „W trasie”, „Dostarczona” (dawniej „Wykonana”). Appka rozpoznaje stan trasy wyłącznie po polu `status`; etykieta służy
  tylko do wyświetlania i może się zmieniać.
- **Szczegóły trasy w panelu (addytywnie):** `zamowienie.dostawa.cofnieto` (czas ostatniego „Cofnij dostarczenie”
  zamówienia na tej trasie, null po ponownym dostarczeniu) i `dostarczone` przy przystanku w `GET /routes/map`.

**Rozstrzygnięcia realizacji** — etykiety używane w komentarzach kodu i w testach (dziennik realizacji nie jest w repo):

| Etykieta | Sedno |
|---|---|
| Ruling 20 | Pisarz statusów pozycji pod blokadą tras bierze blokady zamówień (`blokady_zamowien.zablokuj_zamowienia`) zaraz po blokadzie tras i deklaracji — nie polega na blokadach S z kluczy obcych ani na kolejności flushu. |
| Ruling 21 | Postęp „załadowano” liczy tylko paczki ze znacznikiem załadunku tej trasy. |
| Ruling 21b | „Cofnij zatwierdzenie” trasy z rozpoczętym załadunkiem czyści znaczniki załadunku pod blokadami Dostawy (z logiem `zaladunek`) zamiast odmowy 409. |
| Ruling 22 | Odmowy skanu zapadają pod blokadami (wstępna odmowa z migawki to skrót), trasa skasowana w trakcie → 404 `route_not_found`, anulowane przy zakończeniu załadunku traci znaczniki, przystanek „Zostaje” bez wstępnej odmowy. |
| Ruling 23 | Powtórka „Zakończ załadunek” i „Ruszam” z kolejki offline (nowy `X-Operation-Id`) → 200 `changed: false` z pełną trasą zamiast 409. |
| Ruling 24 | Testy z apką logistyki podmieniają start wątku dopychacza Base., żeby wątek nie psuł transakcji testu. |
| Ruling 25 | Zamówienie zdjęte z trasy wraca do `zweryfikowane` tylko z weryfikacją (inaczej `spakowane`); „Cofnij zatwierdzenie” zdejmuje flagi „Zostaje”; log `dostarczenie_cofniete` tylko przy zmianie pozycji. |
| Ruling 26 | Powtórka „Niedostarczone” po udanym zdjęciu przystanku (ostatni wpis logu = niedostarczenie z tej trasy) → 200 `changed: false` zamiast 404. |
| Ruling 27 | Poprawki frontu panelu tras: okno „Odhacz” (Zostaje, domyślne zaznaczenia), ostrzeżenie „Cofnij zatwierdzenie” ze świeżego odczytu trasy, neutralne „już dostarczone”, dostępność. |
| Ruling 28 | Punkt nawigacji telefonu tą samą regułą co Routimo, „Moje trasy” z trasą zatwierdzoną w trakcie załadunku po dacie końca, bramki stanowiska (403 `station_not_allowed`) i kierowcy sprawdzane na każdym endpoincie telefonu, `completed_by_panel`, rollback przy każdej odmowie zapisu telefonu. |
| Ruling 30 | Runda 2 fali końcowej: pusta trasa po doróbce (odmowa „Ruszam”, „Odhacz” zamyka), zmiana z Base. zdejmuje z trasy w drodze jak doróbka (blokada tras przed zamówieniem, cała trasa w kolejności Dostawy), 417343 zawsze przy zdjęciu z trasy w drodze, C2 w zamknięciu po doróbce, komunikaty spóźnionego „Dostarczone” i hurtu na przystanku dostarczonym, pominięte zamówienia w panelu produktów. |
| Ruling 31 | Runda 3 fali końcowej: panel tras odhacza pustą trasę załadowaną albo w drodze, zdjęcie z trasy po zmianie z Base. z użytkownikiem panelu w logach, przeciąganie i przeliczenie priorytetów ponawiają raz po MySQL 1213 (wyścig z Dostawą). |
| P1 | Numery wierszy w planie 4.4b są orientacyjne (sprzed 4.4a) — kod szuka się po nazwie funkcji. |
| P2 | Wynik `dostawa.zablokuj` (trasa, zamówienia, paczki) zapis trzyma w zmiennych do końca decyzji i odpowiedzi i decyduje tylko na tych obiektach (mapa tożsamości trzyma czyste obiekty słabo). |

## 10. Krok 4.5 — archiwum

- `_archived_order_condition` (`routers/api/products_api.py:284`): zamówienie archiwalne, gdy
  `prod_orders.logistics_closed_at IS NOT NULL` **albo** wszystkie pozycje `anulowane`. Ten sam warunek w widoku
  aktywnych (`products_api.py:643`).
- Kolumna „zakończono” w archiwum: `logistics_closed_at` zamiast `MAX(packaging_completed_at)`.
- Wyszukiwarka tabletu: `ARCHIVE_STATUSES` (`mobile_api_service.py:838`) + nowe statusy.
- Test na kopii produkcji: liczba zamówień w archiwum przed i po zmianie (różnica = otwarte w Logistyce).

## 11. Panel Logistyki i dashboard

- Lista (Dashboard Logistyki): kolumna „Etap” z nowymi stanami (Spakowane — czeka na weryfikację, Zweryfikowane,
  Załadowane, W trasie, Dostarczone), pod nią paczki („2 × paczka”, „1 × EUR”) i ikona problemu z powodem w dymku;
  filtry „Do weryfikacji”, „Problem”, „Bez paczek”. (krok 4.3) Filtry mają własny zakres (8.2), niezależny od podziału
  na otwarte i zamknięte zamówienia, a liczby przy filtrach liczy serwer. Powód problemu jest widoczny jako napis przy
  ikonie (nie tylko w dymku), dostępny z klawiatury. „Do weryfikacji” obejmuje tylko `spakowane`; zamówienia
  `zweryfikowane` nie są w tym filtrze. Etap „W trasie” (zamówienie na trasie `w_trasie`) pojawia się w kroku 4.4,
  razem ze statusami tras. Panel daje tylko ikonę i filtry: rozwiązywanie problemu i cofanie weryfikacji z panelu
  webowego są poza zakresem kroku 4.3 (robi je telefon Weryfikacji).
- Pasek logistyki pod szyną dashboardu produkcji: „Do weryfikacji: N” i „Problemy: N” (w odświeżaniu
  `dashboard-data`, obok `logistics_pending`).
- UI tworzone ze skillem `frontend-design:frontend-design`; w tekstach UI „Base.”.

## 12. Aplikacja (repo `woodpower_prod_app`) — zakres dla sesji appki

Plan każdego kroku dostaje sesja appki. Zakres:
1. `StationCode`: `VERIFICATION`, `DELIVERY` (telefon; poza kolejkami `activeStatuses`).
2. Okno paczek na pakowaniu (tablet): Paczka/Paleta, kafelki 1–10, EUR/niestandardowa z wymiarem, zaznaczenie z
   `packing_hint`; po „ZAKOŃCZ” domykającym zamówienie → `PUT …/packages` w kolejce offline; 404 = pomiń. Okno
   pojawia się tylko przy obecnym `packing_hint` (stary backend go nie wysyła); kończy się „Zatwierdź” albo „Wróć”
   (Wróć anuluje ZAKOŃCZ). Ponowny druk online przez `GET …/packages` (lista aktualnych paczek, druk jednej albo
   wszystkich).
3. Baner `repack_reason` (fallback: dzisiejszy tekst przy `repack_required`).
4. Ekrany telefonowe: pion, jedna kolumna, ciemne, dotyk ≥ 48 dp, bez animacji; skaner w trybie ciągłym z haptyką;
   lokalne rozpoznawanie `P-<id>` i `N_S`; kolejka offline dla nowych akcji.
5. Weryfikacja: lista, filtry, szczegóły, problem, cofnięcia, deklaracja paczek, ponowny druk. Przed „Cofnij do
   pakowania” zamówienia kurierskiego pytanie „Paczka jeszcze na hali?” (8.4).
6. Dostawa: Moje trasy, Załadunek (odwrotna kolejność), Zostaje, Zakończ, Ruszam, Dostarczenia (Nawiguj, Zadzwoń),
   cofnięcie ostatniego dostarczenia; bramka tylko z kierowcami (`is_driver`).
7. Room: nowe tabele/kolumny z migracją (bez `fallbackToDestructiveMigration`).
8. Wyszukiwarka: etykiety nowych statusów.

## 13. Obsługa błędów

| Sytuacja | Zachowanie |
|---|---|
| Deklaracja paczek przed końcem pakowania | 409 `order_not_packed` |
| Deklaracja po weryfikacji | 409 `order_verified` |
| Zapis Weryfikacji na zamówieniu spoza listy (zamknięte w Logistyce, spakowane ponad 7 dni temu albo przed wdrożeniem 4.3, bez otwartego problemu) | 409 `order_status`; `problem/resolve` i szczegóły zamówienia działają zawsze |
| Akcja Weryfikacji, gdy pozycja w międzyczasie wróciła do produkcji | 409 `order_not_packed` |
| Cofnięcie do pakowania bez powodu | 422 `invalid_problem` (zapamiętane w idempotencji) |
| Skan unieważnionej etykiety | 409 `package_void` „Etykieta nieaktualna — paczki zadeklarowano ponownie” |
| Weryfikacja przy otwartym problemie | 409 `problem_open` |
| Załadunek niezweryfikowanego | 409 `order_not_verified` |
| Paczka spoza trasy | 409 `package_not_on_route` z nazwą trasy albo „bez trasy” |
| Akcja w złej fazie trasy | 409 `route_status` |
| Brak kierowcy / nie kierowca | 400 `worker_required` / 403 `not_a_driver` |
| Base. niedostępny / limit | decyzja w CRM zostaje, `bl_status_pending_id` + dopychacz + cron (etap 1) |
| Drukarka niedostępna | zadanie `failed` widoczne w panelu, ponowny druk z tabletu/telefonu |
| Stary agent druku | nie dostaje zadań `wysylka` (zostają `pending` do wygaszenia) |
| Wyścig tablet ↔ panel tras | blokada tras, odczyt bieżący; jedna strona dostaje 409/ponowienie |

Komunikaty po polsku, w API z `error` (kod) i `message` (tekst dla człowieka).

## 14. Wdrożenie i kompatybilność

1. **4.1:** migracja kolejki wydruku (wsteczna: domyślnie `etykiety`), backend, potem nowy agent na komputerze hali z
   dwiema drukarkami; drukarka paczek w sieci hali, kalibracja, „Wydruk próbny”, ustawienie przesunięcia.
2. **4.2:** backend (przyjmuje pakowanie z deklaracją i bez), potem appka z oknem paczek.
3. **4.3:** backend + appka z Weryfikacją; rejestracja telefonu weryfikatora, pracownik biura w `prod_workers`.
   Stara appka tabletów (v1.6.4) znosi nowe statusy (status to napis, nieznany daje tylko usterki wyglądu do nowego
   APK), więc backend może wejść przed appką. Po restarcie raz ręcznie cron logistyki: jednorazowo przestawia
   wydane odbiory osobiste na `dostarczone` i zapisuje znacznik `logistyka_wydane_dostarczone` w `prod_config`;
   kolejne przebiegi niczego nie przestawiają (doróbka po wydaniu nie staje się sama „dostarczona”).
   Siatka w cronie (4.6) zakłada, że migracja etapu 1 `2026-09-25-logistyka-sposob-dostawy.sql` wykonała się PRZED
   `2026-09-30-logistyka-weryfikacja.sql`. Gdyby przy wdrożeniu padła tylko ta pierwsza i wykonała się dopiero przy
   kolejnym deployu, jej zamknięcia historyczne dostaną czas późniejszy niż znacznik — wtedy PRZED pierwszym cronem
   ustaw `logistyka_weryfikacja_od` na chwilę po jej wykonaniu (`flask migrate-status`); usunięcie wiersza nie pomoże,
   bo migracja 4.3 się nie powtórzy.
   Gdy znacznik ma chwilę sprzed restartu (godzinny cron trafił w oknie wdrożenia na nowy worker gunicorna),
   usuń wiersz i uruchom cron ponownie — inaczej wydania starym kodem do restartu zostaną `spakowane`.
   **Wycofanie** po zapisaniu nowych statusów: stary kod nie zna ich w Enum (`LookupError`, czyli 500 na listach,
   w archiwum, wyszukiwarce tabletów i monitorach), więc revert na `main` musi nieść migrację, która wykona się
   przed restartem: `UPDATE prod_products SET current_status='spakowane' WHERE current_status IN
   ('zweryfikowane','zaladowane','dostarczone');` oraz `DELETE FROM prod_config WHERE
   config_key='logistyka_wydane_dostarczone';` (ponowne wdrożenie znów przestawi wydane). ENUM-y, kolumny
   i log mogą zostać — stary kod ich nie czyta.
   Dodatek 8.7 (semantyka `transport.repack_required`, Ruling 3) wchodzi RAZEM z 4.3: kształt odpowiedzi kolejki 5
   (`KSZTALT_ODPOWIEDZI_KOLEJKI`) obejmuje oba. Gdyby dodatek szedł osobno po 4.3, musiałby podbić go do 6.
4. **4.4:** status „Załadowane – trans. WoodPower” założony w Base. (numer do `sposoby.STATUS_ZALADOWANE`), backend +
   appka z Dostawą; telefon kierowcy, kierowca oznaczony we Flocie.
   Etapy 3 i 4 wdrażamy jednym wdrożeniem (decyzja Konrada 1.10), więc w chwili wdrożenia nie ma tras wykonanych.
   Gdyby etap 3 poszedł wcześniej, przed 4.4 trzeba dopisać jednorazowe przestawienie pozycji zamówień z tras
   wykonanych na `dostarczone` (wzór `delivery.dostarcz_wydane`). Kolejność APK ↔ backend: etap 1 wymagał appki
   przed backendem, kroki 4.2–4.3 backendu przed appką (pkt 2–3), a dla 4.4 oba porządki są bezpieczne — nowa appka
   na starym backendzie ukrywa Dostawę (rejestracja `delivery` → 400 `invalid_station_code`,
   `/api/mobile/delivery/*` → 404). Ustalona kolejność wdrożenia (centrala, 2.10): APK 1.7.0 idzie PRZED backendem
   (jest zgodna ze starym backendem).
   **Wycofanie** po zapisaniu nowych stanów: stary kod nie zna statusów tras `zaladowana`/`w_trasie` ani akcji logu
   Dostawy w Enum (`LookupError`), więc revert musi nieść migrację przed restartem:
   `UPDATE prod_routes SET status='zatwierdzona' WHERE status IN ('zaladowana','w_trasie');` oraz
   `UPDATE prod_logistics_log SET action='trasa_status' WHERE action IN
   ('zaladunek','zostaje','wyjazd','dostarczone','niedostarczone','dostarczenie_cofniete');` (pozycje
   `zaladowane`/`dostarczone` zna już kod 4.3).
5. **4.4b — nazwa statusu 417343 w Analizie sprzedażowej i w starym Raporcie sprzedażowym:** dwie jednorazowe migracje
   zmieniają w historycznych wierszach nazwę „Status 417343” na „Planowana trasa” (od commita 73232c57 mapa nazw zna ten
   status, ale stare wiersze zostawały ze starą nazwą i ten sam status siedział w dwóch kubełkach; decyzje Konrada: Analiza
   1.10, stary raport 2.10):
   - `2026-10-01-analiza-planowana-trasa.sql` — `sales_orders`; na kopii produkcji (dane z ok. 25.09) zmienia 66 wierszy;
   - `2026-10-02-raport-planowana-trasa.sql` — `baselinker_reports_orders`; na kopii zmienia 131 wierszy. Kolumna
     `updated_at` tej tabeli nie ma `ON UPDATE`, więc surowy `UPDATE` jej nie zmienia. Tabelę zakłada wyłącznie
     `create_all`, żadna migracja jej nie tworzy, więc migracja jest osłonięta: sprawdza `information_schema` i dopiero
     wtedy robi `PREPARE`/`EXECUTE`. Goły `UPDATE` na bazie bez tej tabeli zablokowałby wszystkie kolejne deploye błędem
     1146. Próba na zastępczej bazie MySQL: 131 wierszy, drugi przebieg 0, `updated_at` bez zmian.
   Obie mają warunek po obu kolumnach (`baselinker_status_id = 417343` i stara nazwa), więc są idempotentne: drugi przebieg
   zmienia 0 wierszy. Na produkcji liczby mogą być inne. Skrypt przeliczenia klientów (`deploy.sh`, krok 6) liczy po
   identyfikatorze statusu, nie po nazwie, więc zmiana nazwy nie wymaga osobnego przeliczenia.
   Notatka wdrożeniowa: po wdrożeniu sprawdź oba zapytania: `SELECT COUNT(*) FROM sales_orders WHERE
   current_status='Status 417343'` oraz `SELECT COUNT(*) FROM baselinker_reports_orders WHERE
   current_status='Status 417343'`. Wynik > 0 oznacza zapis starego kodu w oknie między migracją a restartem — wtedy ręcznie
   ten sam idempotentny `UPDATE` z odpowiedniej migracji.
6. **4.5:** backend.

Każdy krok: push gałęzi, przegląd całej zmiany, oględziny na kopii produkcji (podgląd), wdrożenie tylko na polecenie
Konrada. Merge do `main` = deploy.

## 15. Testy

pytest (SQLite), usługi zewnętrzne zamockowane:
- kolejka wydruku: filtr `printers`, zgodność wsteczna agenta bez parametru; ZPL etykiety paczki (ASCII, pola, ucinanie
  listy, marginesy, anonimizacja odbiorcy — brak pełnej nazwy i jakichkolwiek danych adresowych w ZPL); agent: kierowanie po `printer`, tryb `windows` (zamockowany `ctypes`), stara sekcja `[printer]`;
- podpowiedź paczek (próg 40 kg, anulowane pozycje), deklaracja (warunki, unieważnianie, druk N etykiet, idempotencja);
- przejścia statusów dla każdego sposobu dostawy, wszystkie cofnięcia z 4.5, bramki z 4.4;
- `zamkniecie_wyliczone` (nowe reguły), archiwum (4.5), `ARCHIVE_STATUSES`;
- wywołania Base. (Załadowane, 149763, 149778, 417343 przy cofnięciach, 138620 przy cofnięciu do pakowania);
- trasy: nowe statusy, zajętość, blokady edycji, „Odhacz” z Base., „Cofnij dostarczenie”, zakończenie załadunku ze
  „Zostaje”;
- kontrakt API (kształty, ETag, `KSZTALT_ODPOWIEDZI_KOLEJKI = 5` po kroku 4.3 — 4 po kroku 4.2 z `packing_hint`, `is_driver` w katalogu), uprawnienia (401/403/400);
- testy odwołujące się do `'spakowane'` przejrzane pod kątem 8.6.

Migracje dodatkowo na MySQL (`db` i kopia produkcji). Po każdym kroku przegląd kodu całej zmiany i oględziny z danymi.

**Wyniki MySQL kroku 4.4 (podgląd na kopii produkcji, 2.10).** Wyścigi dwóch sesji (osobne `test_client()`, bariera dwóch
wątków, rozjazd startu 0–40 ms i 0–15 ms): 18 trybów Dostawy (łańcuch skan, zakończenie załadunku, Weryfikacja,
deklaracja paczek, doróbka, ZAKOŃCZ pakowania, cron logistyki, hurtowa zmiana statusu, „Dostarczone”, „Niedostarczone”,
„Odhacz”, „Cofnij dostarczenie”, „Cofnij zatwierdzenie”, zmiana z Base., skan paczki z cudzej trasy i powtórki z kolejki
offline) po 30 przebiegów (10 na czystej barierze, po 10 z rozjazdem), czyli 540 przebiegów, oraz regresja kroku 4.4a
(`panel-zakoncz`, `dorobka-zakoncz`, `sync-zakoncz`, po 10): razem 570 przebiegów. Wynik: **0 × 1213** (licznik InnoDB
`lock_deadlocks` 0 przed i po, 0 wpisów `1213`/`deadlock`/`lock wait` w logu aplikacji), **0 × 500**, **0 niespójnych
stanów** i 0 niezgodnych zamknięć cyklu. Po każdym przebiegu sprawdzane są niezmienniki: trasa załadowana albo w drodze ma
wszystkie aktywne pozycje nierozliczonych przystanków `zaladowane` i paczki załadowane na tę trasę; przystanek z
`delivered_at` ⇔ pozycje `dostarczone` ⇔ `logistics_closed_at`; zamówienie zdjęte z trasy nie ma znaczników załadunku;
żadna ważna paczka nie wskazuje trasy roboczej; `bl_status_pending_id` zgodny z ostatnim przejściem; dokładnie jeden wpis
logu na przejście; kształt odpowiedzi telefonu (Ruling 23 i 26). Siatka crona na kopii (reguła transportu po
`dostarczone`): przed i po `przelicz_otwarte` zero zamknięć transportu po znaczniku z pozycją niedostarczoną i zero z
przystankiem na trasie aktywnej, `przeliczone: 0` (na produkcji przy wdrożeniu etapów 3 i 4 razem też nie ma tras ani
zamknięć po znaczniku). Przy starcie podglądu wykonały się `2026-10-01-logistyka-dostawa` i
`2026-10-01-analiza-planowana-trasa` (2/2) bez błędów; Analiza zmieniła 66 wierszy. Migracja starego raportu
`2026-10-02-raport-planowana-trasa` doszła później i przez runner podglądu nie szła — sprawdzona osobno na zastępczej
bazie MySQL (131 wierszy, drugi przebieg 0; 14 pkt 5).

Audyt wyścigów (nie błędy kroku 4.4, znane luki spoza zakresu): (a) hurtowa zmiana jednej pozycji zamówienia zweryfikowanego
na `spakowane` zostawia `verified_at`, znaczniki załadunku i paczki załadowane (reguła unieważniania nie ma wtedy pracy, bo
wszystkie pozycje są „spakowane lub dalej”, `weryfikacja._jest_praca_dla_reguly`; luka sprzed 4.4) — 15 przebiegów oznaczonych
`LEGACY`; gdy hurt jest pierwszy, bramka zakończenia załadunku (statusy pozycji) odmawia z powodem `niezweryfikowane`
(13 z 15), a gdy zakończenie jest pierwsze, trasa jedzie z pozycjami `spakowane` i `zaladowane` (2 z 15);
(b) hurtowa zmiana pozycji do produkcji po zakończeniu załadunku cofa zamówienie do pakowania (znaczniki i paczki znikają),
ale znacznik Base. 524520 („Załadowane”) zostaje na zamówieniu, a trasa zostaje `zaladowana` z tym przystankiem (według
kodu kierowca zobaczy `niespakowane`, a „Dostarczone” da 409 `order_status`) — 3 przebiegi. Zgodne z Review Focus 5 planu 4.4b.
Po fali końcowej (decyzje Konrada z 2.10 i Ruling 30, tabela w 4.5 i „Fala końcowa” w 9.8): lukę (a) zamyka A1 — hurt na
„spakowane” cofa weryfikację, znaczniki weryfikacji i załadunku. Lukę (b) zamykają dla znanych ścieżek: hurt (odmowa dla
zamówień z trasy załadowanej albo w drodze), doróbka i zmiana z Base. (zdjęcie z trasy, 417343). Nie jest to dowód, że
innej drogi nie ma: ręczna synchronizacja z `force_update`, która dopisuje pozycje istniejącym zamówieniom (dziś
nieaktywna, CLAUDE.md), nie bierze blokady tras i zostawiłaby przystanek. Powtórzone serie MySQL po rundzie 2 — wyniki
w raporcie kontrolera.

## 16. Do zebrania przed realizacją

- Adres drukarki paczek w sieci hali (krok 4.1) i wynik kalibracji/przesunięcia.
- ~~Numer statusu Base. „Załadowane”~~ — **zrobione 30.09: 524520** „Załadowane - trans. WoodPower”, w grupie statusów
  transportu własnego między „Planowana trasa” (417343) a „Wysłane - trans. WoodPower” (149763, Konrad skrócił nazwę;
  kod porównuje statusy po numerach, więc zmiana nazwy nic nie psuje).
- Telefony: rejestracja jako urządzenia stanowisk, pracownik biura w `prod_workers`, kierowcy oznaczeni.
- Akcja automatyczna w Base. „drukuj KP przy Odebrane” (etap 2) — sprawdzić, że nie koliduje z nowymi statusami.
