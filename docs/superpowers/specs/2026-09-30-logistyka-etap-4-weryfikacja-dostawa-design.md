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
- `spakowane` zostaje nazwą; w UI po etapie 4 opisujemy je jako „Spakowane — czeka na weryfikację”.
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
(bez wymogu weryfikacji).

### 4.3 Statusy trasy

`prod_routes.status`: `robocza → zatwierdzona → zaladowana → w_trasie → wykonana`.
- `zaladowana` — kierowca zakończył załadunek. `w_trasie` — kierowca nacisnął „Ruszam”.
- Obie są **aktywne** (zajętość pojazdu/kierowcy, `trasa_dla_tabletu`, lista tras) i **zablokowane do edycji** jak
  `zatwierdzona` (formularz, przystanki, kolejność; zmiana sposobu dostawy i adresu zamówienia z takiej trasy → 409).
- Eksport Routimo dostępny od `zatwierdzona` wzwyż (bez `wykonana` — jak dziś).
- `wykonana` ustawia się sama po rozliczeniu ostatniego przystanku albo ręcznie z panelu (9.7).

### 4.4 Bramki

- Załadunek przyjmuje paczkę tylko, gdy zamówienie jest `zweryfikowane` (serwer: 409 `order_not_verified`).
- „Wydane klientowi” i kurier nie czekają na weryfikację. Panel pokazuje zamówienia wydane/zamknięte bez weryfikacji.
- Weryfikacja wymaga zadeklarowanych paczek.

### 4.5 Cofnięcia

| Akcja | Kto | Skutek |
|---|---|---|
| Cofnij weryfikację | weryfikator (do załadunku) | pozycje → `spakowane`, znaczniki weryfikacji paczek czyszczone |
| Cofnij do pakowania | weryfikator (`spakowane`/`zweryfikowane`) | pozycje → `czeka_na_pakowanie`, paczki unieważnione, `repack_required` + `repack_reason`, Base. 138620 |
| Zostaje | kierowca (przed „Zakończ załadunek”) | przy zakończeniu: zamówienie zdjęte z trasy (pula), statusy bez zmian |
| Cofnij załadunek | logistyk w panelu (trasa `zaladowana`) | pozycje → `zweryfikowane`, znaczniki załadunku czyszczone, Base. 417343, trasa → `zatwierdzona` |
| Niedostarczone | kierowca (trasa `w_trasie`) albo panel | zdjęte z trasy (pula), pozycje → `zweryfikowane`, znaczniki załadunku czyszczone, Base. 417343 |
| Cofnij dostarczenie | kierowca (ostatnie, trasa `w_trasie`) albo panel (dowolny przystanek) | pozycje → `zaladowane`, Base. 149763, trasa `wykonana` → `w_trasie` |
| Doróbka / nowa pozycja / przepakowanie | system | paczki unieważnione, weryfikacja i załadunek zamówienia kasują się; zamówienie przejdzie kroki od nowa po spakowaniu |

### 4.6 Cykl logistyki (`delivery.zamkniecie_wyliczone`)

Zmienione reguły (reszta tabeli z etapu 1 bez zmian):
- kurier: zamknięte, gdy wszystkie niezanulowane pozycje są w `STATUSY_PO_SPAKOWANIU`,
- odbiór osobisty: `handed_over_at` (bez zmian),
- transport własny: wszystkie niezanulowane pozycje `dostarczone` (zamiast „przystanek na trasie wykonanej”).

Historia jest bezpieczna: migracja etapu 1 zamyka stare spakowane zamówienia, a cron `przelicz_otwarte` otwiera
zamknięte, gdy wróci aktywna pozycja (doróbka).

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
| `voided_at` | DATETIME NULL, indeks | unieważniona (nowa deklaracja / cofnięcie / doróbka) |
| `label_printed_at`, `label_print_count` | | druk etykiety |
| `verified_at`, `verified_by_worker_id`, `verified_method` ENUM('skan','reczne') | | weryfikacja |
| `loaded_at`, `loaded_by_worker_id`, `loaded_method` ENUM('skan','reczne'), `loaded_route_id` | | załadunek |

Aktualna deklaracja = paczki zamówienia z `voided_at IS NULL`. N (mianownik „2 / 3”) = ich liczba.

### 5.3 `prod_orders` (kroki 4.2–4.3)

- `packages_declared_at DATETIME NULL` — ostatnia ważna deklaracja.
- `verified_at DATETIME NULL`, `verified_by_worker_id INT NULL` — zamówienie zweryfikowane.
- `problem_reason VARCHAR(32) NULL`, `problem_note VARCHAR(255) NULL`, `problem_at DATETIME NULL`,
  `problem_by_worker_id INT NULL` — zgłoszony problem (NULL = brak).
- `repack_reason VARCHAR(255) NULL` — tekst banera na tablecie pakowania (uzupełnia istniejące `repack_required`).

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
  `PACKAGE_LABEL_OFFSET_X_DOTS`, `PACKAGE_LABEL_OFFSET_Y_DOTS` (przesunięcie `^LH`, domyślnie 0) i przycisk
  **„Wydruk próbny”** dla każdej drukarki (zadanie z etykietą testową: ramka z marginesem 3 mm, miarka w rogach, QR).
- Stanowiska uprawnione do etykiet paczek: `packaging` i `verification` (stała, niezależna od
  `LABEL_PRINTER_ALLOWED_STATIONS` dla etykiet produktów).

### 6.2 Agent (`tools/print_agent/`)

- `config.ini`: sekcje `[printer:etykiety]` i `[printer:wysylka]`, każda z `type = tcp` (`host`, `port`, domyślnie
  9100) albo `type = windows` (`name` = nazwa kolejki wydruku Windows; surowe bajty przez `winspool.drv`
  `OpenPrinter/StartDocPrinter(RAW)/WritePrinter` na `ctypes`, bez zewnętrznych pakietów). Stara sekcja `[printer]`
  czytana jako `etykiety`.
- Agent pyta o zadania wszystkich skonfigurowanych drukarek jednym zapytaniem i kieruje każde według `printer`.
  Nieznana drukarka → zadanie zostaje `pending` (log ostrzeżenia), nie `failed`.
- Awaria jednej drukarki nie wstrzymuje drugiej (osobne liczniki błędów i ponowień).
- README: dwie drukarki, tryb `windows`, aktualizacja na komputerze hali (kopiowanie folderu, `config.ini`, restart).

### 6.3 Etykieta paczki (ZPL, 100×150 mm, 203 dpi = 800×1200 punktów)

Nowa funkcja `generate_package_label_zpl(package, order, cfg)` w `label_print_service.py`. Tekst transliterowany do ASCII
tą samą mapą co etykiety produktów (`label_print_service.py:38`), `^ i ~` usuwane z danych. Treść w marginesie ≥ 3 mm,
dół treści ≤ 1130 punktów (zapas na przesunięcie). Układ (wzór wydrukowany 30.09 na zamówieniu 1450):

1. **Nagłówek:** „ZAMOWIENIE” i duży numer wewnętrzny; po prawej czarny kafel „PACZKA” / „PALETA” i „2 / 3”.
2. **Pas sposobu dostawy** (biały na czarnym): `KURIER`, `ODBIOR OSOBISTY`, `TRASA: <nazwa> <data>` albo
   `TRANSPORT WOODPOWER` (bez trasy), `NIE USTAWIONO`.
3. **Odbiorca — zanonimizowany** (uwaga Konrada po wzorze): z nazwy (osoba, a gdy jej brak — firma) dwa pierwsze
   słowa, z każdego 3 pierwsze znaki i `***`, gdy słowo jest dłuższe (np. „Dar*** Kow***”). **Żadnych danych
   adresowych** — bez ulicy, kodu pocztowego i miejscowości. Pełne dane są w CRM pod kodem paczki.
4. **QR** (`^BQN,2,11`, treść `P-<id>`) i obok: kod `P-<id>`, rodzaj i typ (`PALETA EUR 120x80`,
   `PALETA 150x100`, `PACZKA`), waga szacunkowa (m³ × `WAGA_KG_NA_M3`), „N poz. / N szt. / m³”, data spakowania.
5. **Zawartość zamówienia:** wiersze „n. Gatunek technologia klasa DxSxG cm … N szt.” (wykończenie, gdy nie surowe);
   do 14 wierszy, przy większej liczbie 13 wierszy i „+ N pozycji (N szt.) – pełna lista w CRM”.
6. **Stopka:** numer Base., numer zamówienia klienta, „WoodPower, Bachorz 14N”.

Etykieta nie jest przedrukowywana automatycznie po zmianie sposobu dostawy albo trasy; panel pokazuje ikonę „etykiety
paczek sprzed zmiany” (jak dla etykiet produktów w etapie 1).

### 6.4 Drukarka — ustalenia z testu 30.09

Xprinter XP-410B (firmware 1.038), etykiety 100×150 z przerwą 3 mm. **Emulacja ZPL działa**; polskie znaki poza Ó/ó
nie drukują się (strona kodowa 850) → ASCII. Wydruk przesunięty ok. 4 mm w dół, lewa krawędź ramki ucięta → kalibracja
czujnika przerwy przy instalacji i przesunięcie w ustawieniach (6.1). Drukarka ma adres fabryczny spoza sieci hali —
konfiguracja sieci drukarki to krok wdrożenia 4.1.

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
- Przyjmowana, gdy **wszystkie niezanulowane pozycje są `spakowane`** (inaczej 409 `order_not_packed`). Po weryfikacji
  zablokowana (409 `order_verified` — najpierw „Cofnij weryfikację”).
- Unieważnia poprzednie paczki, tworzy N nowych, `packages_declared_at`, wpis `paczki` w logu, podbija `updated_at`
  pozycji (ETag), kolejkuje N etykiet na drukarkę `wysylka`. Idempotentna przez `X-Operation-Id`.
- Appka wysyła ją po „ZAKOŃCZ”, który domyka całe zamówienie: najpierw jak dziś zakończenia pozycji, potem deklaracja
  (kolejka offline zachowuje kolejność). Wcześniejsze raty pakowania (rzadkie: 10/742 zamówień od sierpnia pakowane w
  różne dni) nie pokazują okna.
- Kompatybilność: backend przyjmuje pakowanie bez deklaracji (stara appka, admin, hurtowa zmiana). Takie zamówienie
  ma na liście Weryfikacji plakietkę „BEZ PACZEK” i weryfikator deklaruje paczki na telefonie tym samym oknem. Nowa
  appka na starym backendzie dostaje 404 i pomija deklarację bez blokowania pakowania.

### 7.3 Ponowny druk

`POST /api/mobile/packages/<id>/print` (jedna) i `POST /api/mobile/orders/<nr>/packages/print` (wszystkie ważne) —
z tabletu pakowania i telefonu Weryfikacji. Unieważniona paczka → 409 `package_void`.

## 8. Krok 4.3 — statusy i Weryfikacja

### 8.1 Stanowisko

`verification` („Weryfikacja”) w `ProductionDevice.VALID_STATION_CODES`, `STATION_LABELS` (poza `STATION_ORDER`, jak
`sawmill`), `_STATION_CODES_WITH_TABLETS` (telemetria). Pracownik biura loguje się przez „Kto pracuje?” — musi mieć
wpis w `prod_workers`; stanowisko wymaga nagłówka `X-Worker-Ids` niezależnie od `WORKER_SELECTION_REQUIRED`
(400 `worker_required`).

### 8.2 Lista „Do weryfikacji”

`GET /api/mobile/verification/orders` (ETag): zamówienia, których wszystkie niezanulowane pozycje są `spakowane`, plus
zamówienia z problemem. Każde z paczkami (`id`, kod, `seq`, rodzaj, stan weryfikacji), sposobem dostawy/trasą
(`transport`), klientem, miejscowością, flagą problemu i „BEZ PACZEK”. Kolejność: zamówienia z tras o najbliższej dacie
początku, potem według `packaging_completed_at` rosnąco. Filtry w appce: Wszystkie / Trasy / Kurier / Odbiór.

### 8.3 Akcje

| Endpoint | Działanie |
|---|---|
| `POST /verification/packages/<id>/verify` `{method}` | paczka zweryfikowana; ostatnia ważna → zamówienie `zweryfikowane` (pozycje, `verified_at`, log). Ponowny skan = OK bez zmian. Unieważniona → 409 `package_void`. Zamówienie z problemem → 409 `problem_open` |
| `POST /verification/orders/<nr>/verify-all` | wszystkie ważne paczki ręcznie (`reczne`) |
| `POST /verification/orders/<nr>/unverify` | tylko `zweryfikowane` i niezaładowane → pozycje `spakowane` |
| `POST /verification/orders/<nr>/problem` `{reason, note}` | flaga problemu; powody: `brak_elementu`, `uszkodzenie`, `etykieta`, `opakowanie`, `inne`. Tylko przed załadunkiem; zamówienie `zweryfikowane` wraca do `spakowane` (cofnięcie weryfikacji), więc bramka załadunku obejmuje też problemy |
| `POST /verification/orders/<nr>/problem/resolve` | zdejmuje flagę (log `problem_rozwiazany`) |
| `POST /verification/orders/<nr>/revert-to-packing` `{reason, note}` | 4.5; `repack_reason = "Weryfikacja: <powód>: <notatka>"`, flaga problemu przenoszona do banera |

Skaner w appce rozpoznaje `^P-\d+$` lokalnie z listy (działa bez zasięgu, akcja idzie kolejką offline); `N_S` (etykieta
produktu) otwiera zamówienie; inne kody → komunikat „Nieznany kod”.

### 8.4 Cofnięcie do pakowania

Jak przepakowanie z etapu 1 (`delivery.py`): pozycje → `czeka_na_pakowanie`, `set_quantity_done('packaging', 0,
source='system')`, `packaging_completed_at = NULL`, `repack_required = 1`, paczki unieważnione, Base. 138620, po
ponownym spakowaniu status po spakowaniu według sposobu. `transport` dostaje `repack_reason` (dla przepakowania na
kuriera: „Przepakuj na kuriera”); `KSZTALT_ODPOWIEDZI_KOLEJKI` 3 → 4. Zamówienie na trasie zostaje na niej (kierowca
zobaczy „NIESPAKOWANE”).

### 8.5 Przejścia systemowe

- Wejście pozycji do produkcji w zamówieniu z paczkami (doróbka, nowa pozycja z Base.) → paczki unieważnione,
  `verified_at = NULL`, pozostałe pozycje wracają do `spakowane` (albo zostają niżej, jeśli nie były spakowane).
- `delivery.po_spakowaniu` bez zmian dla Base.; `przelicz_zamkniecie` według 4.6.

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
  `STATUS_ZALADOWANE` (nowa stała w `sposoby.py`); trasa → `zaladowana`, `loaded_at/by`.

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

- Sekcje listy tras: Robocze, Zatwierdzone, **Załadowane**, **W trasie**, Wykonane; kłódka i postęp
  „załadowano 7/8 · dostarczono 3/7” w nagłówku edytora; przy przystanku paczki i stany.
- **„Cofnij załadunek”** (trasa `zaladowana`) — 4.5.
- **„Odhacz jako wykonaną”** (z `zatwierdzona`/`zaladowana`/`w_trasie`): zaznaczone → jak „Dostarczone” (pozycje
  `dostarczone`, 149778); odznaczone → jak „Niedostarczone” z powodem `odhaczone_w_panelu`. Wymóg „spakowane lub
  dalej” zostaje. **Zmiana względem etapu 3:** odhaczenie wysyła statusy do Base.
- **„Przywróć trasę” znika**; zastępuje ją **„Cofnij dostarczenie”** przy przystanku (4.5).
- Zajętość pojazdów i kierowców liczy `zaladowana` i `w_trasie` jako aktywne.

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
  filtry „Do weryfikacji”, „Problem”, „Bez paczek”.
- Pasek logistyki pod szyną dashboardu produkcji: „Do weryfikacji: N” i „Problemy: N” (w odświeżaniu
  `dashboard-data`, obok `logistics_pending`).
- UI tworzone ze skillem `frontend-design:frontend-design`; w tekstach UI „Base.”.

## 12. Aplikacja (repo `woodpower_prod_app`) — zakres dla sesji appki

Plan każdego kroku dostaje sesja appki. Zakres:
1. `StationCode`: `VERIFICATION`, `DELIVERY` (telefon; poza kolejkami `activeStatuses`).
2. Okno paczek na pakowaniu (tablet): Paczka/Paleta, kafelki 1–10, EUR/niestandardowa z wymiarem, zaznaczenie z
   `packing_hint`; po „ZAKOŃCZ” domykającym zamówienie → `PUT …/packages` w kolejce offline; 404 = pomiń.
3. Baner `repack_reason` (fallback: dzisiejszy tekst przy `repack_required`).
4. Ekrany telefonowe: pion, jedna kolumna, ciemne, dotyk ≥ 48 dp, bez animacji; skaner w trybie ciągłym z haptyką;
   lokalne rozpoznawanie `P-<id>` i `N_S`; kolejka offline dla nowych akcji.
5. Weryfikacja: lista, filtry, szczegóły, problem, cofnięcia, deklaracja paczek, ponowny druk.
6. Dostawa: Moje trasy, Załadunek (odwrotna kolejność), Zostaje, Zakończ, Ruszam, Dostarczenia (Nawiguj, Zadzwoń),
   cofnięcie ostatniego dostarczenia; bramka tylko z kierowcami (`is_driver`).
7. Room: nowe tabele/kolumny z migracją (bez `fallbackToDestructiveMigration`).
8. Wyszukiwarka: etykiety nowych statusów.

## 13. Obsługa błędów

| Sytuacja | Zachowanie |
|---|---|
| Deklaracja paczek przed końcem pakowania | 409 `order_not_packed` |
| Deklaracja po weryfikacji | 409 `order_verified` |
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
4. **4.4:** status „Załadowane – trans. WoodPower” założony w Base. (numer do `sposoby.STATUS_ZALADOWANE`), backend +
   appka z Dostawą; telefon kierowcy, kierowca oznaczony we Flocie.
5. **4.5:** backend.

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
- kontrakt API (kształty, ETag, `KSZTALT_ODPOWIEDZI_KOLEJKI = 4`, `is_driver` w katalogu), uprawnienia (401/403/400);
- testy odwołujące się do `'spakowane'` przejrzane pod kątem 8.6.

Migracje dodatkowo na MySQL (`db` i kopia produkcji). Po każdym kroku przegląd kodu całej zmiany i oględziny z danymi.

## 16. Do zebrania przed realizacją

- Adres drukarki paczek w sieci hali (krok 4.1) i wynik kalibracji/przesunięcia.
- Numer statusu Base. „Załadowane – trans. WoodPower” (krok 4.4). Propozycja nazw: podstawowa „Załadowane - trans.
  WoodPower” (29 zn.), skrócona „Załadowane” (10), pełna dla klienta „Zamówienie jest załadowane na nasz samochód i
  wkrótce wyruszy w trasę. Nasz kierowca skontaktuje się z Tobą przed dostawą.”, komentarz „Ustawia CRM automatycznie,
  gdy kierowca zakończy załadunek trasy w appce (stanowisko Dostawa). Nie ustawiać ręcznie.”
- Telefony: rejestracja jako urządzenia stanowisk, pracownik biura w `prod_workers`, kierowcy oznaczeni.
- Akcja automatyczna w Base. „drukuj KP przy Odebrane” (etap 2) — sprawdzić, że nie koliduje z nowymi statusami.
