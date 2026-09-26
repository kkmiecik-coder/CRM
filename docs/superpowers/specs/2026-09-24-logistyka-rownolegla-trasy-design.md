# Logistyka równoległa: sposób dostawy, mapa, trasy i flota — projekt

- **Data:** 2026-09-24
- **Status:** zatwierdzony w rozmowie sekcja po sekcji, czeka na przegląd spisanej wersji
- **Zastępuje:** ustalenia z sesji CRM z 2026-09-23 („Logistyka równoległa w produkcji”,
  plik `2026-09-23-logistyka-rownolegla-kursy-design.md` nie istnieje na tej maszynie).
  Z tamtego projektu przejmujemy wyłącznie **kształt obiektu `transport` w API mobilnym**,
  który zna już sesja appki (plan wersji vc38), rozszerzony o `mode = null`.
- **Plik nie idzie do gita** — repo jest publiczne, `docs/superpowers/` jest w `.gitignore`.

## 1. Cel i kontekst

Logistyka jest dziś **etapem w pipeline'ie**: po Krawędziach/Lakierni produkt dostaje status
`czeka_na_logistyke`, logistyk na stronie `/production/logistics` wybiera kuriera albo
transport WoodPower, a produkt przechodzi do `czeka_na_pakowanie`. Odbiór osobisty
(heurystyka `ProductionOrder.is_personal_pickup`) omija logistykę automatycznie.

W praktyce ten etap jest omijany: w kopii bazy z 21.09 ok. 1040 przejść z
`czeka_na_logistyke` w sierpniu–wrześniu to hurtowa zmiana statusu z listy produktów
(`products_api.bulk_action`), prawie zawsze tego samego dnia. `override_delivery_method`
od lipca nie został ustawiony ani razu. Logistyk rozdzielał towar ręcznie na hali, więc
dane z BaseLinkera zaniżają realną liczbę dostaw transportem własnym.

**Cel:** logistyka działa **równolegle** do produkcji. Sposób dostawy jest atrybutem
zamówienia, który logistyk ustawia i zmienia przez cały czas życia zamówienia. Każde
zamówienie musi go mieć, zanim zostanie spakowane. Zamówienia z transportem własnym
logistyk układa w trasy z pojazdem i kierowcą, widzi je na mapie i eksportuje do Routimo.

**Sukces:**
- żadne zamówienie nie zostaje spakowane bez decyzji logistyka,
- logistyk planuje trasy transportu własnego w CRM (mapa, przystanki, pojazd, kierowca,
  km i czas, eksport do Routimo) zamiast ręcznie na hali,
- pakowacz na tablecie widzi, jak zamówienie jedzie: kurier, odbiór osobisty albo nazwa trasy,
- BaseLinker ma zawsze aktualną metodę dostawy i właściwy status po spakowaniu.

## 2. Ustalenia z rozmowy

1. Sposób dostawy: `override_delivery_method`, domyślnie **„Nie ustawiono”** (NULL). Wartość z
   BaseLinkera (`delivery_method`) to tylko podpowiedź dla logistyka.
2. **Każde zamówienie przechodzi przez logistykę**, także odbiór osobisty. Znika
   automatyczne omijanie logistyki.
3. Status `czeka_na_logistyke` znika z pipeline'u. Pakowacz widzi zamówienie bez sposobu
   dostawy, ale nie może go spakować — pomija je i bierze kolejne.
4. Zmiana sposobu dostawy aktualizuje zamówienie w BaseLinkerze.
5. Bez widoków kierowcy — przyjdą później razem ze stanowiskiem kierowcy, który będzie
   skanował zamówienia i wtedy CRM będzie zmieniał statusy „Wysłane / Dostarczona –
   transport WoodPower”. Teraz zostawiamy na to furtkę.
6. Tablet pakowania: kurier → „KURIER”, odbiór → „ODBIÓR OSOBISTY”, transport własny →
   **nazwa trasy**, a bez trasy „TRANSPORT WOODPOWER”, brak ustawienia → „NIE USTAWIONO”.
7. Zamówienie znika z widoku logistyki (wariant B):
   - kurier — po spakowaniu,
   - odbiór osobisty — po kliknięciu **„Wydane klientowi”** (status BL 149779 „Odebrane”),
   - transport własny — po odhaczeniu trasy jako wykonanej (przystanek dostarczony).
8. BaseLinker:
   - zmiana sposobu dostawy zawsze nadpisuje pole „Metoda dostawy” tekstem „Kurier”,
     „Odbiór osobisty” albo „Transport WoodPower” (także gdy było tam np. „DPD”),
   - po spakowaniu status według sposobu dostawy (jak dziś), a zmiana po spakowaniu
     przestawia status,
   - „Wydane klientowi” → 149779,
   - odhaczenie trasy **nie** zmienia statusu w BL (furtka pod stanowisko kierowcy),
   - nazwa trasy **nie** trafia do BL.
9. Trasa: nazwa, **zakres dat** (od–do), pojazd, kierowca z **pracowników produkcji**, notatka,
   uporządkowane przystanki, podsumowanie m³ / waga (m³ × 800 kg) / km / czas.
10. **Flota**: panel pojazdów. Pojazd i kierowca zajęty w nakładających się datach na innej
    trasie jest w wyborze wyszarzony z dopiskiem „(zajęty)”.
11. Statusy trasy: **Robocza → Zatwierdzona → Wykonana**. Zatwierdzona daje **eksport do
    Routimo** (mechanizm istnieje w module raportów). Wykonaną odhacza ręcznie logistyk.
12. Dzień wdrożenia: **nic nie wypełniamy automatycznie**. Logistyk przeklikuje sposoby dostawy
    (lista ma hurtowe ustawianie).
13. Przepakowanie: zamówienie spakowane pod transport własny albo odbiór, zmienione na kuriera,
    **wraca do kolejki pakowania z banerem „PRZEPAKUJ NA KURIERA”**.
14. Geokodowanie: **cron co godzinę** albo ręcznie przyciskiem w panelu.
15. Geokodowanie i przebieg tras: GUGiK UUG → Nominatim, przebieg OpenRouteService
    (podejście 1 z rozmowy).
16. **Cały interfejs** (zakładka Logistyka, mapa, trasy, flota) powstaje ze skillem
    `frontend-design:frontend-design` — wymóg dla każdego zadania UI w planie.
17. **Nazewnictwo:** w interfejsie i komunikatach dla użytkownika piszemy **„Base.”**, nie
    „BaseLinker” ani „BL” (np. „Base.: czeka na wysłanie”, „Metoda dostawy z Base.”).
    Identyfikatory w kodzie (`bl_*`, `baselinker_*`) i ten dokument zostają bez zmian.

## 3. Zakres i etapy

Jedna specyfikacja, trzy etapy wdrażane osobno, każdy z własnym planem implementacji:

| Etap | Zawartość | Warunek wdrożenia |
|---|---|---|
| **1. Sposób dostawy** | wyjęcie logistyki z pipeline'u, blokada pakowania, zapis do BL, przepakowanie, cykl życia, zakładka Logistyka z listą, kontrakt `transport`, cron logistyki (dopychanie BL) | nowa appka wydana wcześniej (patrz 11.2), wpis crontaba |
| **2. Mapa** | geokodowanie, dashboard z mapą zamówień, ręczna korekta pinezek | — (cron z etapu 1 dostaje geokodowanie) |
| **3. Trasy i flota** | pojazdy, trasy ze statusami, przystanki, przebieg ORS, widok tras na mapie, eksport Routimo, nazwa trasy na tablecie | klucz ORS w `core.json` na serwerze |

**Poza zakresem:** widoki i stanowisko kierowcy, śledzenie GPS, statusy BL 149763/149778,
automatyczna optymalizacja kolejności przystanków, pojazd na tablecie poza polem
`vehicle_name`, usunięcie wartości `czeka_na_logistyke` z typu kolumny (osobne sprzątanie,
patrz 13), ceny dostawy w BL.

## 4. Umiejscowienie kodu

Nowy podpakiet na wzór Trakowni (`modules/production/sawmill/`):

```
modules/production/logistics/
├── __init__.py            # blueprint logistics_panel_bp
├── models.py              # LogisticsLog (1), OrderGeo (2), Vehicle, Route, RouteStop (3)
├── sposoby.py             # czyste mapowania + obiekt `transport` dla panelu i API mobilnego
├── services/
│   ├── delivery.py        # zmiana sposobu dostawy, cykl życia, przepakowanie, wydanie
│   ├── dzierzawa.py       # „jeden wykonawca na serwer” w prod_config (Base., geokoder)
│   ├── bl_sync.py         # zapisy do BL + trwałe „do wysłania” + dopychacz w tle + furtka kierowcy
│   ├── lista.py           # lista zamówień zakładki
│   ├── geocoding.py       # GUGiK → Nominatim → przybliżenie (etap 2)
│   ├── routing.py         # ORS + fallback linii prostych (etap 3)
│   ├── routes.py          # trasy, przystanki, zajętość, odhaczanie (etap 3)
│   ├── fleet.py           # pojazdy (etap 3)
│   └── routimo.py         # wspólny generator Excela Routimo (etap 3)
├── routers/panel_api.py   # /production/api/logistics/*
├── routers/cron_api.py    # /production/api/logistics/cron
├── templates/logistics/tab_content.html
└── static/{css,js}/logistics*.{css,js}
```

Blueprint rejestrowany w `app.py` obok `sawmill_panel_bp`, prefiks `/production/api/logistics`.
Kolumny na `prod_orders` zostają w `modules/production/models.py`.

Leaflet 1.9.4 i Leaflet.markercluster **vendorujemy** do `modules/production/static/vendor/`
(Safari ITP, patrz `feedback_vendor_cdn`). Kafelki: CARTO `light_all`, jak dziś.

## 5. Model danych

### 5.1 `prod_orders` — nowe i zmienione kolumny (etap 1)

| Kolumna | Typ | Znaczenie |
|---|---|---|
| `override_delivery_method` | istniejąca, VARCHAR(255) | NULL = nie ustawiono; `kurier_baselinker`, `transport_woodpower`, **nowa** `odbior_osobisty`. Stare nazwy zostają (historia, synchronizacja statusów BL). |
| `delivery_method_set_at` | DATETIME NULL | kiedy logistyk ostatnio ustawił sposób |
| `delivery_method_set_by` | INT NULL → users.id | kto |
| `handed_over_at` / `handed_over_by` | DATETIME / INT NULL | „Wydane klientowi” |
| `repack_required` | BOOL NOT NULL DEFAULT 0 | czeka na przepakowanie na kuriera |
| `logistics_closed_at` | DATETIME NULL, indeks | koniec cyklu logistycznego; NULL = zamówienie widoczne w Logistyce |
| `bl_delivery_method_pending` | BOOL NOT NULL DEFAULT 0 | metoda dostawy czeka na wysłanie do BL |
| `bl_status_pending_id` | INT NULL | status BL czekający na wysłanie (z decyzji logistyki) |
| `logistics_completed_at` | istniejąca | **nowe znaczenie:** chwila, w której ostatni niezanulowany produkt zamówienia wszedł do `czeka_na_pakowanie` („Zeszło z produkcji” w Arkuszu) |

Mapowanie wartości:

| `override_delivery_method` | `transport.mode` | `delivery_type` (legacy) | Tekst do BL |
|---|---|---|---|
| NULL | `null` | `courier` | — |
| `kurier_baselinker` | `kurier` | `courier` | Kurier |
| `transport_woodpower` | `wlasny` | `transport_woodpower` | Transport WoodPower |
| `odbior_osobisty` | `odbior` | `personal_pickup` | Odbiór osobisty |

`is_personal_pickup` zostaje wyłącznie jako **podpowiedź** z BL w liście logistyki. Nie steruje
już żadną logiką (BL status, etykieta, pipeline).

### 5.2 `prod_logistics_log` (etap 1)

`id, order_id → prod_orders, action ENUM('sposob_dostawy','wydane','przepakowanie',
'trasa_dodane','trasa_usuniete','trasa_status'), old_value VARCHAR(64), new_value VARCHAR(64),
route_id NULL, user_id NULL, note VARCHAR(255) NULL, created_at`. Wszystko, co zmienia logistykę
zamówienia, zostawia tu wiersz.

### 5.3 `prod_order_geo` (etap 2)

`order_id PK → prod_orders, lat DECIMAL(9,6) NULL, lng DECIMAL(9,6) NULL,
source ENUM('gugik','nominatim','reczna') NULL, quality ENUM('dokladna','przyblizona',
'nie_znaleziono'), address_hash CHAR(40), address_changed_after_manual BOOL DEFAULT 0,
attempts INT DEFAULT 0, updated_at`.

### 5.4 Trasy i flota (etap 3)

- `prod_vehicles`: `id, name, registration, capacity_kg INT NULL, is_active, created_at,
  updated_at, deactivated_at`. Nigdy nie kasujemy.
- `prod_routes`: `id, name, date_from DATE, date_to DATE, status ENUM('robocza','zatwierdzona',
  'wykonana'), vehicle_id NULL → prod_vehicles, driver_worker_id NULL → prod_workers, notes,
  approved_at/by, completed_at/by, created_at/by, updated_at` oraz cache przebiegu:
  `geometry_json LONGTEXT NULL, distance_km DECIMAL(8,1) NULL, duration_min INT NULL,
  geometry_hash CHAR(40) NULL, geometry_approx BOOL DEFAULT 0`.
  Ograniczenie: `date_to >= date_from`.
- `prod_route_stops`: `id, route_id → prod_routes ON DELETE CASCADE, order_id → prod_orders
  UNIQUE, position INT`. Zamówienie jest na co najwyżej jednej trasie. Przystanek na trasie
  wykonanej = dostarczony.

Wszystkie migracje idempotentne, w formacie `2026-MM-DD-nazwa.sql`, bez `DELIMITER`.

## 6. Etap 1 — sposób dostawy

### 6.1 Pipeline

- `ProductionProduct.complete_task`: każde dzisiejsze wyjście do `czeka_na_logistyke`
  (`edges`, `painting`, `formatting` bez krawędzi, `gluing` przy `cut_to_size=False`) prowadzi
  do `czeka_na_pakowanie`. Blok odbioru osobistego (`models.py:637-640`) znika.
- Gdy ostatni niezanulowany produkt zamówienia wchodzi do `czeka_na_pakowanie`, ustawiamy
  `logistics_completed_at` (jeśli puste).
- `baselinker_status_sync.POSTPROD_STATUSES` = `{'czeka_na_pakowanie','spakowane'}`.
- Migracja: produkty w `czeka_na_logistyke` → `czeka_na_pakowanie`. Wartość zostaje w ENUM do
  osobnego sprzątania (okno kilku sekund między migracją a restartem nie może wywalić tabletu
  starym kodem).
- Status znika z UI: lista hurtowej zmiany statusu (`products-tab-content.html:305`), filtry i
  mapy statusów w `products-module.js`/`archive-module.js`, bramka „Logistyka” na dashboardzie
  produkcji (`dashboard-tab-content.html:273-282`), węzeł diagramu (`dashboard-module.js`),
  alert rangi 7 w `dashboard_alerts.py`, krok „Logistyka” na linii czasu produktu. Etykiety
  statusu zostają tam, gdzie wyświetlamy **historię** (zdarzenia, raporty poza pipeline'em).
- Bramkę na dashboardzie produkcji zastępuje licznik **„Bez sposobu dostawy: N”** z linkiem do
  zakładki Logistyka.
- `bulk_action` przestaje przyjmować `czeka_na_logistyke` jako cel.

### 6.2 Cykl życia zamówienia w logistyce

`logistics_closed_at` jest **wyliczany** przez jedną funkcję
`delivery.przelicz_zamkniecie(order)`, wołaną po każdej zmianie, która może go dotyczyć
(zmiana sposobu, spakowanie, wydanie, odhaczenie trasy, przepakowanie, anulowanie):

| Sytuacja | Zamknięte? |
|---|---|
| wszystkie produkty anulowane | tak |
| `mode = null` | nie (nawet po spakowaniu — to anomalia do wyjaśnienia) |
| `repack_required` | nie |
| kurier, wszystkie niezanulowane spakowane | tak |
| odbiór, `handed_over_at` ustawione | tak |
| transport własny, przystanek na trasie `wykonana` | tak |
| pozostałe | nie |

Migracja etapu 1 ustawia `logistics_closed_at = NOW()` dla zamówień, których wszystkie
produkty są `spakowane`/`anulowane` — inaczej historia (w tym ~100 zamówień z
`transport_woodpower` z kwietnia–czerwca) zalałaby widok.

Reguły edycji:
- „Wydane klientowi” — tylko przy `mode = odbior` i wszystkich produktach spakowanych.
- Zmiana sposobu dostawy zablokowana (409 z komunikatem), gdy zamówienie zostało wydane albo
  dostarczone, oraz gdy leży na trasie **zatwierdzonej** („cofnij zatwierdzenie trasy X”).
- Zmiana z transportu własnego na inny zdejmuje zamówienie z trasy roboczej (log + komunikat
  „usunięto z trasy X”).

### 6.3 BaseLinker

Wszystko w `logistics/services/bl_sync.py`:

- **Zmiana sposobu dostawy** → `setOrderFields {order_id, delivery_method: <tekst>}`
  (przez `sync_service._make_api_request`).
- **Zmiana po spakowaniu** (wszystkie niezanulowane spakowane, bez przepakowania) →
  `setOrderStatus` według nowego sposobu: kurier 138623, transport 417343, odbiór 149777.
- **Wydane klientowi** → 149779.
- **Przepakowanie** (6.4) → 138620, a po ponownym spakowaniu 138623 (istniejąca ścieżka
  `schedule_after_station_complete`).
- `_determine_packaging_target_status` czyta **tylko** `override_delivery_method`
  (bez heurystyki `is_personal_pickup`). `mode = null` → 138623 z ostrzeżeniem (możliwe tylko
  przez ręczną zmianę statusu przez admina).
- **Trwałość:** zapis w CRM ustawia `bl_delivery_method_pending` / `bl_status_pending_id` w tej
  samej transakcji. Sukces wysyłki czyści znacznik. Cron logistyki (8.3) dopycha wszystko, co
  zostało — wątki i timery giną przy restarcie gunicorna, znacznik nie.
- **Tempo i bezpiecznik (limit API Base. = 100 zapytań/min na CAŁE konto, wspólny z
  synchronizacją CRM; 24.09 przekroczenie zablokowało token konta — `feedback_baselinker_limit_api`):**
  - **Żadnych wywołań Base. w żądaniu HTTP** — sync worker gunicorna ma 30 s na żądanie
    (`-w 4`, memory `project_apk_timeouty_nginx`), a `_make_api_request` ponawia z przerwami.
  - Każda zmiana (pojedyncza i hurtowa) → tylko znaczniki w transakcji; po commicie startuje
    **jeden** wątek „dopychacz” w tle (jeśli jeszcze nie działa), który bierze zamówienia ze
    znacznikami po kolei z odstępem **1,5 s (≤ 40/min)**. W dniu wdrożenia 300 zamówień to
    ok. 8 minut; pojedyncza zmiana dociera do Base. w ciągu sekund.
  - **Jeden dopychacz na cały serwer**, nie na proces: gunicorn ma kilka workerów i każdy
    uruchomiłby własny wątek, a razem przekroczyłyby limit. Wątek najpierw przejmuje
    dzierżawę (wiersz `logistyka_bl_dzierzawa` w `prod_config`, warunkowy `UPDATE` na
    znaczniku ważności, odnawiany co zamówienie). Kto dzierżawy nie dostał, kończy od razu.
  - Cron logistyki tylko **uruchamia** dopychacz w tle i od razu odpowiada. Dzierżawa jest
    w osobnym module (`services/dzierzawa.py`), bo etap 2 używa jej dla geokodowania
    (klucz `logistyka_geo_dzierzawa`).
  - **Bezpiecznik:** odpowiedź „Query limit exceeded” / „token blocked until <data>” zatrzymuje
    wszystkie wysyłki logistyki do podanej chwili (zapamiętanej w bazie, żeby cron i wątek jej
    przestrzegały), log ERROR. Znaczniki zostają, nic nie ginie.
  - **Oszczędność:** `setOrderFields` pomijamy, gdy `prod_orders.delivery_method` (ostatnia
    wartość z synchronizacji) już równa się tekstowi docelowemu.
  - Istniejące ponawianie timerem (`RETRY_DELAYS_S`) dla statusu po spakowaniu zostaje bez zmian.
- Awaria BL **nie cofa** decyzji w CRM. UI pokazuje ostrzeżenie, a lista ikonę „Base.: czeka na
  wysłanie” (znika sama, gdy timer albo cron dopchnie zmianę).
- **Furtka kierowcy:** `bl_sync.oznacz_wyslane(order)` (149763) i
  `bl_sync.oznacz_dostarczone(order)` (149778) — zaimplementowane i przetestowane, **niewołane**.

### 6.4 Przepakowanie na kuriera

Warunek: zmiana na `kurier_baselinker` z `transport_woodpower` albo `odbior_osobisty`, gdy
choć jeden niezanulowany produkt jest `spakowane`.

1. `repack_required = 1`, wpis `przepakowanie` w logu.
2. Produkty `spakowane` → `czeka_na_pakowanie`; `set_quantity_done('packaging', 0,
   source='system')` (bez atrybucji pracownika); `packaging_completed_at = NULL`.
3. BL: metoda „Kurier” + status 138620.
4. Tablet pokazuje baner „PRZEPAKUJ NA KURIERA” (`transport.repack_required`).
5. Ponowne `complete_task('packaging')` czyści `repack_required`, BL dostaje 138623.

W drugą stronę (kurier → transport/odbiór) przepakowania nie ma — zmienia się tylko status BL.

### 6.5 API mobilne — kontrakt `transport`

Każda pozycja w odpowiedziach kolejek i wyszukiwarki (`serialize_order`,
`mobile_api_service.py:1051`) dostaje identyczny dla całego zamówienia obiekt:

```json
"delivery_type": "transport_woodpower | personal_pickup | courier",
"transport": {
  "mode": null,
  "trip_name": null,
  "trip_date": null,
  "vehicle_name": null,
  "repack_required": false
}
```

- `mode`: `null` | `"kurier"` | `"wlasny"` | `"odbior"`.
- `trip_name` / `trip_date` (RRRR-MM-DD, = `date_from`) / `vehicle_name` — z trasy
  niewykonanej, na której leży zamówienie; w etapach 1–2 zawsze `null`.
- **Nowy backend ZAWSZE wysyła obiekt `transport`** (nigdy `null`, nigdy pominięty). Brak
  obiektu oznacza stary backend — to rozróżnienie jest podstawą kompatybilności appki (11.2).
- `delivery_type` zachowuje stare wartości (mapowanie w 5.1). Dla `mode = null` = `courier`:
  stare APK pokażą „KURIER” — świadomie akceptowane na okres przejściowy.
- Serializer `transport` jest jeden (`logistics/services/serializers.py`) i używają go panel
  oraz API mobilne.
- **Blokada:** `POST /api/mobile/orders/<id>/complete` na stanowisku `packaging` przy
  `mode = null` → **409** `{"error": "delivery_method_not_set", "message": "Logistyka nie
  ustawiła jeszcze sposobu dostawy dla zamówienia <nr>. Pomiń je i weź kolejne."}`.
- **Świeżość:** każda zmiana wpływająca na obiekt `transport` (sposób dostawy, przepakowanie,
  przypisanie do trasy i zdjęcie z niej, zmiana nazwy/dat/pojazdu/statusu trasy) podbija
  `updated_at` **wszystkich pozycji** zamówień, których dotyczy. ETag kolejek liczy się z
  `MAX(updated_at)` pozycji, więc to wystarcza. Dodatkowo `KSZTALT_ODPOWIEDZI_KOLEJKI` 2 → 3.

### 6.6 Etykieta produktu

`label_print_service._format_delivery_label` korzysta z tej samej funkcji tekstu co tablet:
„Kurier”, „Odbiór osobisty”, nazwa trasy albo „Transport WoodPower”, „Nie ustawiono”. Zmiana
sposobu dostawy po wydruku nie przedrukowuje etykiet automatycznie — lista logistyki pokazuje
ikonę „etykiety wydrukowane przed zmianą” (gdy `label_printed_at` < `delivery_method_set_at`).

### 6.7 Zakładka Logistyka — lista (etap 1)

- Zakładka **„Logistyka”** w `panel/dashboard.html` **przed Trakownią**, ładowana jak Trakownia
  (gotowy HTML z `GET /production/api/logistics/tab-content`, wpis w `validTabs` i
  `loadTabContent` w `production-app-loader.js`).
- Podzakładki: **Dashboard** | **Trasy** | **Flota**. W etapie 1 działa Dashboard (sama lista),
  Trasy i Flota pojawiają się w etapie 3.
- Lista zamówień z `logistics_closed_at IS NULL`:
  numer, klient, miasto, **podpowiedź „Metoda dostawy z Base.”** (`delivery_method`),
  **wybór sposobu dostawy**, etap produkcji (najwcześniejszy status spośród niezanulowanych
  produktów), termin, m³, ikony: „Base.: czeka na wysłanie” / etykiety sprzed zmiany /
  przepakowanie.
- Sortowanie: „Nie ustawiono” na górze, dalej termin rosnąco.
- Filtry: sposób dostawy, etap produkcji; wyszukiwarka po numerze, kliencie i mieście.
- Zaznaczanie wielu zamówień + **hurtowe ustawienie sposobu dostawy**.
- Wyszukiwarka z przełącznikiem „także zamknięte” — znajduje zamówienia spoza widoku (np.
  kurierskie po spakowaniu) i pozwala zmienić sposób dostawy (z blokadami z 6.2).
- Przycisk **„Wydane klientowi”** przy spakowanych odbiorach osobistych.
- Stara strona `/production/logistics`, `templates/logistics/logistics.html` i
  `routers/api/logistics_api.py` są usuwane.

## 7. Etap 2 — geokodowanie i mapa

### 7.1 Geokodowanie

Kolejność prób w `geocoding.py`:

1. **GUGiK UUG** — `https://services.gugik.gov.pl/uug/?request=GetAddress&address=<...>&srid=4326`.
   Zapytanie **bez kodu pocztowego**: „<miejscowość>, <ulica> <numer>” albo „<miejscowość>
   <numer>”. Kod pocztowy służy wyłącznie do wyboru spośród kilku trafień. Pułapka sprawdzona
   24.09: „36-068 Bachórz 14N” → 0 wyników (rejestr ma dla 14N kod 36-065), „Bachórz 14N” →
   dokładny punkt. Tylko dla `delivery_country_code = PL` (albo pustego).
2. **Nominatim** — z serwera, najwyżej 1 zapytanie na sekundę, User-Agent identyfikujący CRM
   (`WoodPowerCRM/1.0 (crm.woodpower.pl)`), zgodnie z zasadami usługi. Dla zagranicy i gdy
   GUGiK nic nie znajdzie.
3. **Przybliżenie** — miejscowość + kod (GUGiK/Nominatim), `quality = przyblizona`.
4. **Nie znaleziono** — `quality = nie_znaleziono`, zamówienie na liście do ręcznego ustawienia.

- Do usług zewnętrznych wysyłamy **wyłącznie adres** (bez nazwiska, firmy, telefonu, e-maila).
- `address_hash` = SHA-1 znormalizowanego adresu. Zmiana adresu w BL (hash inny niż zapisany)
  → ponowne geokodowanie, **chyba że** punkt jest ręczny — wtedy tylko
  `address_changed_after_manual = 1` i ikona „adres zmieniony” na liście.
- Ręczna korekta: przeciągnięcie pinezki albo „ustaw tutaj” → `source = reczna`,
  `quality = dokladna`. Automat nigdy jej nie nadpisuje.
- Wyzwalanie: cron logistyki co godzinę (8.3) i przycisk **„Zlokalizuj teraz”** w panelu
  (`POST /production/api/logistics/geocode`). Oba tylko **uruchamiają wątek w tle** (limit
  30 s na żądanie) z dzierżawą `logistyka_geo_dzierzawa` — jeden geokoder na serwer, Nominatim
  najwyżej 1 zapytanie/s. Wątek bierze wszystkie otwarte zamówienia do zlokalizowania; panel
  pokazuje postęp licznikiem „Bez lokalizacji: N” (odświeżanie listy).
- Zamówienia z `attempts >= 3` i `nie_znaleziono` nie wracają do automatu, dopóki nie zmieni
  się adres.
- **Magazyn** (Bachórz 14N, 49.840438, 22.254053) — stała w `geocoding.py`: znacznik na mapie i
  start/koniec tras.

### 7.2 Dashboard z mapą

- Układ: mapa + lista z 6.7 obok siebie, powiązane: kliknięcie pinezki podświetla wiersz i
  odwrotnie. Filtry listy działają na mapie.
- Przełącznik widoków:
  - **Zamówienia** — pinezki w kolorze sposobu dostawy (szary: nie ustawiono, niebieski: kurier,
    zielony: transport własny, fioletowy: odbiór osobisty), klastry z liczbą przy wielu
    zamówieniach blisko siebie, pinezki przybliżone rysowane inaczej (np. obwódką).
  - **Trasy** — aktywne trasy (robocze i zatwierdzone), etap 3.
- Licznik **„Bez lokalizacji: N”** nad mapą, z przejściem do ręcznego ustawiania.

## 8. Etap 3 — trasy, flota, Routimo

### 8.1 Flota

Podzakładka **Flota**: tabela pojazdów (nazwa, rejestracja, ładowność, aktywny), dodawanie,
edycja, wyłączanie. Pojazd wyłączony nie pojawia się w wyborze nowych tras, ale zostaje
widoczny w starych.

### 8.2 Trasy

- Podzakładka **Trasy**: po lewej lista tras pogrupowana po dacie (sekcje: robocze,
  zatwierdzone, wykonane z filtrem dat); po prawej edytor:
  formularz (nazwa, data od, data do, pojazd, kierowca, notatka) → przystanki z przeciąganiem →
  „Do dodania” (zamówienia `wlasny` bez trasy, niezamknięte) → mapka z przebiegiem →
  podsumowanie.
- **Zajętość:** pojazd/kierowca na innej trasie `robocza` albo `zatwierdzona` z nakładającym
  się zakresem dat (`a.from <= b.to AND b.from <= a.to`) jest w wyborze wyszarzony, z
  dopiskiem „(zajęty)” i nazwą trasy w podpowiedzi. Serwer sprawdza to samo przy zapisie
  (409 z komunikatem) — dwie osoby edytujące naraz nie obejdą reguły.
- Kierowcy: aktywni `prod_workers`.
- Na trasę trafiają wyłącznie zamówienia z `mode = wlasny`. Z listy w Dashboardzie jest też
  hurtowa akcja **„Dodaj do trasy”** (wybór trasy roboczej).
- **Podsumowanie:** liczba przystanków, m³ (suma `volume_m3 × quantity` niezanulowanych
  produktów), szacowana waga (m³ × 800 kg), km i czas jazdy. Gdy pojazd ma ładowność i waga ją
  przekracza — ostrzeżenie (nie blokada).
- **Przebieg:** `routing.py` woła ORS `directions/driving-car` z punktami magazyn → przystanki
  w kolejności → magazyn. Liczony przy zapisie trasy, gdy zmienił się `geometry_hash` (skrót
  kolejności i współrzędnych), z limitem 10 s. Brak klucza, błąd, limit albo przystanek bez
  współrzędnych → linie proste, `geometry_approx = 1`, odległość w linii prostej, dopisek
  „przebieg przybliżony”. Powyżej 48 przystanków — od razu linie proste (limit ORS).
- **Statusy:**
  - `robocza` — pełna edycja.
  - **Zatwierdź** → `zatwierdzona`: edycja zablokowana (formularz, przystanki, kolejność), przycisk
    **„Eksport do Routimo”**, przycisk „Cofnij do roboczej”.
  - **Odhacz jako wykonaną** (z roboczej albo zatwierdzonej) → okno z listą przystanków,
    domyślnie wszystkie „dostarczone”. Odznaczone są zdejmowane z trasy (log `trasa_usuniete`,
    notatka „niedostarczone”) i wracają do puli. Trasa → `wykonana`, zamówienia dostarczone →
    `przelicz_zamkniecie`. BL bez zmian.
  - `wykonana` — tylko do odczytu, przycisk **„Przywróć trasę”** (do `zatwierdzona`, log
    `trasa_status`, ponowne przeliczenie zamknięcia).
- Każda zmiana trasy widoczna na tablecie podbija `updated_at` pozycji jej zamówień (6.5).

### 8.3 Cron logistyki

`POST /production/api/logistics/cron`, dekorator `cron_secret_required`, wołany co godzinę
przez `scripts/cron_endpoint.sh POST /production/api/logistics/cron`:
- etap 1: uruchomienie dopychacza Base. w tle (patrz 6.3) oraz siatka bezpieczeństwa cyklu
  życia (w żądaniu, szybkie zapytania w bazie): ponowne
  `przelicz_zamkniecie` dla zamówień otwartych i dla zamkniętych, które mają znów aktywne
  produkty (np. Base. dołożył pozycję, doróbka),
- etap 2: uruchomienie geokodera w tle (patrz 7.1).

Endpoint odpowiada natychmiast — praca idzie w wątkach tła z dzierżawą.

Wpis w crontabie serwera dodajemy ręcznie przy wdrożeniu etapu 1 (zakres zadania).

### 8.4 Eksport do Routimo

- Generator Excela z `modules/reports/routers.py` (`generate_routimo_excel`, :3057) wydzielamy do
  wspólnej funkcji przyjmującej listę neutralnych słowników „przystanek” (37 kolumn Routimo,
  formatowanie i szerokości bez zmian). Stary eksport z raportów i nowy z tras korzystają z niej.
- Eksport trasy (`GET /production/api/logistics/routes/<id>/routimo`, tylko `zatwierdzona`):
  wiersze w kolejności przystanków; „Pojazd” = nazwa pojazdu, „Oczekiwana data realizacji” =
  `date_from`, „Szerokość/Długość geograficzna” z `prod_order_geo`, „Region” z
  `PostcodeToStateMapper`, „Waga przesyłki” = m³ × 800, pola, których `prod_orders` nie ma,
  puste. Nazwa pliku: `routimo_<nazwa-trasy>_<data>.xlsx`.
- Test zgodności: nagłówki i formatowanie wspólnego generatora identyczne ze starym wynikiem.

## 9. Uprawnienia i konfiguracja

- Wszystkie endpointy panelu Logistyki: `require_module_access('production', as_json=True)` na
  zewnątrz, `login_required` wewnątrz (wzór `guard` z `sawmill/routers/panel_api.py:53`).
- Cron: `cron_secret_required` (`cron_auth.py`).
- `config/core.json`: nowe pole **`OPENROUTESERVICE_API_KEY`**, bez wartości domyślnej w kodzie.
  Brak → przebiegi przybliżone + log WARNING (nie CRITICAL — mapa działa dalej).
- Aktualizacja `CLAUDE.md`: cron logistyki, klucz ORS, zasada „każde zamówienie przez
  logistykę”.

## 10. Obsługa błędów

| Sytuacja | Zachowanie |
|---|---|
| BL niedostępny / błąd | decyzja w CRM zostaje, znacznik „do wysłania”, dopychacz + cron, ostrzeżenie w UI |
| BL: przekroczony limit / token zablokowany | bezpiecznik wstrzymuje wysyłki logistyki do podanej chwili, znaczniki zostają |
| Pakowanie przy `mode = null` | 409 `delivery_method_not_set` z komunikatem po polsku |
| Zmiana sposobu wydanego/dostarczonego zamówienia | 409 z komunikatem |
| Zmiana zamówienia na trasie zatwierdzonej | 409 „cofnij zatwierdzenie trasy X” |
| Pojazd/kierowca zajęty | 409 z nazwą kolidującej trasy |
| Edycja trasy zatwierdzonej/wykonanej | 409 |
| Geokodowanie bez wyniku | `nie_znaleziono`, lista do ręcznego ustawienia |
| ORS niedostępny / brak klucza | linie proste, `geometry_approx = 1` |
| Równoległa edycja tej samej trasy | ostatni zapis wygrywa, ale reguły zajętości i blokady statusów sprawdza serwer w transakcji |

## 11. Wdrożenie

### 11.1 Kolejność etapów

1. **Etap 1:** najpierw nowa appka na tabletach (11.2), potem backend. Migracja przenosi produkty
   z `czeka_na_logistyke` do pakowania i zamyka historyczne zamówienia. Zaraz po wdrożeniu
   logistyk przeklikuje sposoby dostawy. Dopisanie crontaba logistyki.
2. **Etap 2:** backend; cron z etapu 1 zaczyna geokodować. Pierwsze uruchomienie „Zlokalizuj
   teraz” kilka razy albo odczekanie kilku godzin crona.
3. **Etap 3:** klucz ORS w `core.json` na serwerze **i restart** (zapis `core.json` i restart
   zawsze razem — incydent z 24.09), potem backend. Tablety bez zmian (pola `trip_*` już obsługują).

Praca na nowej gałęzi od `main` w osobnym worktree (w głównym katalogu pracują równolegle inne
sesje). Push do `main` = deploy.

### 11.2 Kompatybilność appki

| Appka | Backend | Efekt |
|---|---|---|
| nowa | obecny | brak obiektu `transport` → zachowanie jak dziś (plakietka z `delivery_type`, bez blokady, bez banera) |
| nowa | nowy | pełna funkcja |
| stara | nowy | działa, ale nieustawione pokazuje jako „KURIER”, 409 kończy się mylącym „sukcesem” i powrotem po ≤30 s, brak nazwy trasy i banera — dlatego tablety aktualizujemy **przed** backendem |

Warunki: nowy backend zawsze wysyła obiekt `transport`; appka przechowuje w Room rozróżnienie
„obiekt obecny / nieobecny” (patrz 12).

## 12. Aplikacja tabletowa — zakres zmian (repo `woodpower_prod_app`)

Na podstawie rozpoznania sesji appki z 24.09:

1. `OrderDto`: `transport: TransportDto? = null` (`mode: String?`, `trip_name`, `trip_date`,
   `vehicle_name`, `repack_required: Boolean = false`).
2. Room: migracja **20 → 21** — kolumny `transport_present` (BOOL), `transport_mode`,
   `trip_name`, `trip_date`, `vehicle_name`, `repack_required` w `orders`; schemat 21.json; test w
   `MigrationTest`. `fallbackToDestructiveMigration` nie może się uruchomić (kasuje kolejkę offline).
3. Domena: `DeliveryType` + `NotSet`; wyliczanie: `transport_present = false` → stare
   `fromBackend(delivery_type)`; `true` → z `mode` (`null` → `NotSet`).
4. `DeliveryBadge`: „NIE USTAWIONO”, a dla `wlasny` nazwa trasy (fallback „TRANSPORT WOODPOWER”).
5. Pakowanie (`OrderGroupCard`/`OrderGroup`): „ZAKOŃCZ” zablokowane przy `NotSet` z widocznym
   powodem („Czeka na decyzję logistyki — weź kolejne zamówienie”); zamówienia `NotSet` na końcu
   kolejki pakowania.
6. Baner „PRZEPAKUJ NA KURIERA” przy `repack_required`.
7. 409 `delivery_method_not_set`: nie pokazywać sukcesu, przywrócić pozycję, pokazać `message`
   z serwera; wpis kolejki offline z tym kodem nie może udawać sukcesu (dziś optymistyczne
   usunięcie + `BLOCKED` z ogólnym tekstem).
8. Usunięcie gałęzi `czeka_na_logistyke` w `Station.kt:97` (+ testy `SearchHitLocationLabelTest`).
9. Wydanie APK **przed** wdrożeniem backendu etapu 1.

Szczegółowy plan dla appki wysyłamy sesji appki po zatwierdzeniu tej specyfikacji.

## 13. Testy

pytest (SQLite), usługi zewnętrzne (BL, GUGiK, Nominatim, ORS) zamockowane:

- przejścia `complete_task` bez `czeka_na_logistyke` (wszystkie wyjścia, także odbiór osobisty);
  aktualizacja `tests/test_routing_krawedzie.py` i pozostałych testów z listy w 14,
- `logistics_completed_at` przy ostatnim produkcie,
- blokada pakowania (409) i kontrakt obiektu `transport` (zawsze obecny, mapowanie wartości,
  legacy `delivery_type`),
- podbijanie `updated_at` przy każdej zmianie z 6.5,
- `przelicz_zamkniecie` — wszystkie wiersze tabeli z 6.2,
- wybór wywołań BL (metoda, status po spakowaniu, zmiana po spakowaniu, wydanie, przepakowanie),
  znaczniki „do wysłania” i cron, odstęp dopychacza, bezpiecznik „Query limit exceeded”,
  pomijanie zbędnego `setOrderFields`,
- przepakowanie: reset pakowania, baner, ponowne spakowanie,
- migracja: przeniesienie statusów i zamknięcie historii,
- parser GUGiK (fixture'y JSON, w tym pułapka kodu dla „14N”), wybór trafienia po kodzie,
  fallback Nominatim, przybliżenie, ochrona ręcznego punktu,
- zajętość pojazdów i kierowców (granice zakresów dat), blokady statusów trasy, odhaczenie z
  niedostarczonymi przystankami, przywrócenie trasy,
- ORS: fallback linii prostych, `geometry_hash`,
- eksport Routimo: zgodność nagłówków i formatowania ze starym generatorem,
- uprawnienia (401/403 JSON) i cron (403/500 bez sekretu).

Migracje dodatkowo uruchamiane na MySQL w kontenerze `db` (testy na SQLite nie sprawdzają
ENUM ani `ALTER`). Po każdym etapie: przegląd kodu całej gałęzi i oględziny panelu z danymi.

## 14. Mapa dotkniętych miejsc (etap 1)

- Pipeline: `modules/production/models.py:590-645` (`should_skip_to_logistics`, `complete_task`),
  `:210-227` (`is_personal_pickup` → tylko podpowiedź, `delivery_type` nieużywane).
- BL: `services/baselinker_status_sync.py:50-54, :235-262, :284-291`.
- Mobile: `services/mobile_api_service.py:1051-1190` (`serialize_order`), `:1208`
  (`mark_order_complete`), `routers/mobile_api.py:131-133` (`KSZTALT_ODPOWIEDZI_KOLEJKI`).
- Etykieta: `services/label_print_service.py:346-369`.
- Dashboard: `routers/api/dashboard_api.py:261-265, :1004-1011`,
  `templates/components/dashboard-tab-content.html:273-282`, `services/dashboard_alerts.py:55-65`,
  `static/js/modules/dashboard-module.js:497-511`, `static/css/production-panel.css:2679-2758`.
- Lista produktów/archiwum: `routers/api/products_api.py:227-230, :1240, :2361-2363`,
  `static/js/modules/products-module.js` (mapy statusów, linia czasu :3929-4160, :4486),
  `archive-module.js:27, :944, :959`, `templates/components/products-tab-content.html:305`.
- Raporty produkcji: `services/reports_service.py:118-124`, `routers/api/reports_api.py:1060,
  :1098-1106` — etykiety historyczne zostają.
- Arkusz: `modules/reports/arkusz_service.py:104-115, :556-587, :643` — bez zmian w kodzie, zmienia
  się tylko źródło znacznika (6.1).
- Stara logistyka do usunięcia: `routers/api/logistics_api.py`, `templates/logistics/logistics.html`,
  `routers/main_routers.py:200-204`.
- Panel: `templates/panel/dashboard.html:35-99`, `static/js/production-app-loader.js:46, :90-91,
  :275-283`, `app.py:877-879`.
- Testy odwołujące się do `czeka_na_logistyke`: `test_routing_krawedzie.py`,
  `test_krawedzie_parytet_reguly.py`, `test_mobile_api_alias_krawedzi.py`,
  `test_mobile_complete_bl_sync_queue.py`, `test_reports_service.py`, `test_reports_przeglad.py`,
  `test_dashboard_statusy_produkcji.py`, `test_dashboard_krawedzie.py`,
  `test_order_timeline_service.py`, `test_stanowiska_tab_krawedzie.py`,
  `test_produkty_formularz_statusu.py`, `test_produkty_etykiety_statusow_eksport.py`,
  `test_produkty_js_mapy_pol_stanowisk.py`, `test_katalog_stanowisk_krawedzie.py`,
  `test_baselinker_krawedzie.py`.

## 15. Na później

- Stanowisko kierowcy (skanowanie, statusy 149763/149778 przez furtkę z 6.3, pojazd na tablecie).
- Automatyczna optymalizacja kolejności przystanków (ORS optimization).
- Migracja sprzątająca: usunięcie `czeka_na_logistyke` z ENUM `production_status`, gdy żadna
  wersja kodu go nie zapisuje.
- Status 417343 „Planowana trasa” w mapie statusów Analizy sprzedażowej
  (`modules/reports/service.py:30-49`) — dziś wyświetla się jako „Status 417343”.
