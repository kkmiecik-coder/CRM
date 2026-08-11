# Profile pracowników — backend (CRM)

**Status:** projekt zatwierdzony w burzy mózgów, gotowy do implementacji
**Data:** 2026-08-11
**Dokument siostrzany:** `crm_prod_app/docs/worker-profiles-mobile.md`
**Dotyczy:** `modules/production/`

---

## 1. Po co to robimy

Dziś system wie **z którego tabletu** wykonano operację, ale nie wie **kto** ją wykonał.
`prod_station_events` ma kolumny `user_id` i `device_id`, ale z apki mobilnej zawsze leci
`user_id = NULL` (`mobile_api.py:375` — komentarz wprost: *„mobile API używa device, nie user"*,
w handlerze reject; complete i quantity też nie przekazują użytkownika),
a panele webowe stanowisk chodzą bez logowania, więc też zapisują `NULL`.

Bezpośrednim wyzwalaczem jest **sklejanie**: to jedno stanowisko, ale obsługiwane przez kilka
tabletów, więc metryka „per urządzenie" nie odpowiada na żadne sensowne pytanie. Zamiast łatać
sklejanie, wprowadzamy wymiar **pracownika** dla całej produkcji.

### Czego ta funkcja NIE jest

Wybór profilu to **jeden tap w kafelek, bez PIN-u i bez żadnego dowodu tożsamości**.
Świadoma decyzja — priorytetem jest zero tarcia na hali. Konsekwencja, którą przyjmujemy
z otwartymi oczami:

> Statystyki są narzędziem **operacyjnym**, nie rozliczeniowym. Nie nadają się jako
> jedyna podstawa premii ani jako dowód w sporze pracowniczym, bo każdy może kliknąć
> cudzy kafelek.

Model danych przewiduje miejsce na PIN (`prod_workers.pin_hash`), ale **nie implementujemy
go teraz**. Gdyby statystyki miały kiedyś służyć rozliczeniom, dokładamy warstwę
uwierzytelnienia bez zmiany schematu.

---

## 2. Decyzje projektowe (zamknięte)

| # | Decyzja | Wybór | Uzasadnienie |
|---|---|---|---|
| 1 | Gdzie mieszkają profile | Nowa tabela `prod_workers` | Pracownicy hali to nie użytkownicy CRM — nie mają maili, haseł, ról ani dostępu do panelu. Wpychanie ich do `users` wymagałoby `email` nullable i filtrowania ich ze wszystkich list użytkowników. Opcjonalny FK `user_id` łączy tych, którzy są jednym i drugim (brygadzista). |
| 2 | Uwierzytelnienie | Kafelek z avatarem, jeden tap, **bez PIN** | Zero tarcia. Rękawice, pośpiech, hala. |
| 3 | Model sesji | Sesja zmianowa z auto-wylogowaniem | Loguje się raz, pracuje do końca dnia. |
| 4 | Timeout | 120 min bezczynności + twardy cutoff 23:00 | Wartości w `prod_config`, zmienialne z `/production/?tab=config` bez deployu. |
| 5 | Wielu naraz | **Tak, wszędzie**, praca dzielona po równo | Dwóch ludzi robi jeden blat na sklejaniu. Wybór zawsze wymaga potwierdzenia „Start" — jednolicie, bez trybów. |
| 6 | Bramka | Pełnoekranowy wybór blokuje wszystko | Zero eventów bez przypisanego pracownika. |
| 7 | Lista profili | Pełna lista + „szybki wybór" (ostatnio aktywni na tym stanowisku) | Plus kolumna `allowed_stations` do sortowania i domyślnego zawężenia. |
| 8 | CRUD pracowników | Nowa zakładka `/production/?tab=workers` | Obok istniejących zakładek modułu produkcji. |
| 9 | Statystyki | Wydajność dzienna (sztuki + m³) + czas pracy (sesje, przerwy) | Bez metryk jakościowych na tym etapie. |
| 10 | Zmiany | Jedna zmiana, doba = jednostka raportowa | Brak wymiaru `shift` w modelu. |
| 11 | Kolumny „kto zrobił" na produkcie | **Nie ma ich** — jedno zapytanie zbiorcze | Jedno źródło prawdy (eventy), zero ryzyka rozjazdu. |
| 12 | Zakres | **Tylko mobile** | Panele webowe stanowisk znikają — patrz rozdział 3. |
| 13 | Stanowisko w JWT | Bez zmian | Rozważaliśmy wybór stanowiska przy sesji; **porzucone**. Tablet nadal ma stanowisko zaszyte w tokenie. |

### Decyzja odrzucona i dlaczego

**Kolumny `*_worker_id` na `prod_products`** (np. `cutting_worker_id`, `gluing_worker_id`).
Kusząca, ale nie działa:

- przy dwóch osobach na jednej sztuce jeden FK nie zmieści obu,
- ten sam produkt bywa robiony przez różnych ludzi w różnych momentach (5 sztuk Adam rano,
  5 Bartek po południu) — jeden FK zgubi jednego z nich,
- `prod_station_events.delta` to `INT` (sztuki); dzielenie pracy wymagałoby ułamków,
  a `delta` napędza `quantity_done`, więc zmiana typu rozwaliłaby wszystkie istniejące agregaty.

Zamiast tego: **eventy zostają nietknięte, atrybucja idzie osobną tabelą**
`prod_station_event_workers`.

---

## 3. ETAP 0 (poprzedza wszystko): usunięcie webowych paneli wykonawczych

**To musi wejść pierwsze.** Bez tego budujemy profile w dwóch miejscach naraz i podwajamy
zakres. Po tej zmianie praca produkcyjna odbywa się **wyłącznie przez apkę Android**.

### 3.1 Co znika

Skala: **~26 800 linii** (JS 11 554, CSS 8 596, HTML 2 505, Python ~3 175 w pełnych plikach
plus fragmenty). Zero testów do przepisania.

**Pliki w całości:**

```
modules/production/routers/stations/interfaces.py                    (1348)
modules/production/routers/stations/ajax.py                          (1089)
modules/production/routers/stations/shipping.py                      ( 679)  ← patrz 3.4
modules/production/templates/stations/cutting.html
modules/production/templates/stations/assembly.html
modules/production/templates/stations/gluing.html
modules/production/templates/stations/formatting.html
modules/production/templates/stations/finishing.html
modules/production/templates/stations/packaging.html
modules/production/templates/stations/select.html
modules/production/templates/stations/_print_label_button.html
modules/production/static/js/stations/station-cutting.js
modules/production/static/js/stations/station-assembly.js
modules/production/static/js/stations/station-gluing.js
modules/production/static/js/stations/station-formatting.js
modules/production/static/js/stations/station-finishing.js
modules/production/static/js/stations/station-packaging.js           (2236)
modules/production/static/js/stations/station-common.js              (1999)
modules/production/static/js/stations/station-attachments.js
modules/production/static/js/stations/station-edge-modal.js
modules/production/static/js/stations/station-print-label.js
modules/production/static/js/stations/station-assembly-backup.js     ← martwy już dziś
modules/production/static/css/stations/station-cutting.css
modules/production/static/css/stations/station-assembly.css
modules/production/static/css/stations/station-gluing.css
modules/production/static/css/stations/station-formatting.css
modules/production/static/css/stations/station-finishing.css
modules/production/static/css/stations/station-packaging.css
modules/production/static/css/stations/station-shared.css
modules/production/static/css/stations/station-root.css              ← martwy już dziś
scripts/smoke_test_web_reject.py
```

**Fragmenty w `modules/production/routers/stations/__init__.py`:**

| Element | Linie | Uwaga |
|---|---|---|
| `complete_order_bulk()` | 1075–1289 | **Weryfikacja przed usunięciem — patrz 3.3** |
| `get_station_frontend_config()` | 1036–1072 | `GET /production/stations/config` |
| `get_products_for_station()` | 319–509 | |
| `_ajax_get_orders_simple()` | 809–1029 | |
| `_format_product_display_name()`, `_format_deadline_display()` | | |
| 5 filtrów Jinja (`format_priority`, `format_deadline`, `format_volume`, `format_currency`, `truncate_smart`) | 192–281 | Zero użyć w templatkach |
| `station_urls` / `ajax_urls` / `api_urls` w `inject_station_context()` | 102–120 | Inaczej `BuildError` przy każdym renderze monitora |

**Endpointy w `modules/production/routers/api/products_api.py`:**

| Endpoint | Linia | Powód |
|---|---|---|
| `POST /production/api/complete-task` | 20 | Woła tylko `station-common.js`. **Metoda modelu `ProductionItem.complete_task()` ZOSTAJE** — używa jej mobile. |
| `POST /production/api/update-quantity-done` | 255 | |
| `POST /production/api/products/<id>/reject` | 390 | Mobile ma `mobile_api.py:340` |
| `POST /production/api/toggle-product-done` | 143 | martwy |
| `POST /production/api/get-cutting-progress` | 448 | martwy |
| `POST /production/api/get-assembly-progress` | 519 | martwy |

Plus `GET /production/api/station-health` (`sync_api.py:496`) — heartbeat `station-common.js`.

Po usunięciu tych sześciu: dekorator `ip_validation_required` (`routers/api/common_api.py:67`)
nie ma już żadnego użytkownika. Mobile API go **nie używa** — ma własną autoryzację JWT.

### 3.2 Naprawy obowiązkowe (inaczej 500 w panelu CRM)

Te dwa pliki robią `url_for('production.production_stations.<x>_station')`. Po usunięciu
widoków → `BuildError` → **500 na dashboardzie i na zakładce Stanowiska**:

- `modules/production/templates/components/dashboard-tab-content.html` — linie 121, 159, 197, 235, 273, 330
- `modules/production/templates/components/stations-tab-content.html` — linie 50, 226–231, 247–252

Dodatkowo:

- `stations/__init__.py:184` (handler 500) i `templates/stations/error.html:211` — odwołują się
  do `station_select`; przekierować na `monitors_select`
- `templates/stations/monitors_select.html:105–107` — kafelek „Kompletacja" prowadzi do
  `/monitors/completion`, którego nie ma w `MONITOR_STATION_MAP` → **404 już dziś**, usunąć
- `services/security_service.py:56–62` — `IPSecurityService.PROTECTED_ROUTERS` zawiera
  nieaktualne ścieżki bez prefiksu `/stations`; przegląd przy okazji

### 3.3 Synchronizacja statusów Baselinkera — sprawdzone, jest OK

`complete_order_bulk()` odpala hook synchronizacji statusów BL (linie 1240–1253).
Sprawdzono w kodzie: **mobilne `POST /api/mobile/orders/{id}/complete` robi to samo** —
`mobile_api_service.py:1107-1109` woła `schedule_after_station_complete(...)`,
a `:581` `flush_pending_syncs()`. Usunięcie paneli nie zepsuje statusów
„Produkcja zakończona" / „Spakowane".

**Test regresyjny do dopisania mimo to:** zamknięcie stanowiska przez mobile API skutkuje
wpisem w kolejce synchronizacji statusów BL. To jedyna rzecz, która po Etapie 0 pilnuje
integracji z Baselinkerem.

### 3.4 Wysyłka kurierska — usuwamy całość

`stations/shipping.py` + `ShippingModule` w `station-packaging.js` to jedyne UI do nadawania
przesyłek w CRM. **Nie jest używane** — biuro nadaje wszystko bezpośrednio w Baselinkerze.
Usuwamy frontend i backend.

Opis na wypadek, gdyby kiedyś wracało (kod jest w historii gita):

**Architektura:** dwustopniowa. GlobKurier (bezpośrednie API,
`modules/production/services/shipping_service.py`, token przez `_get_globkurier_token()`,
endpoint w `config/core.json`) do **wyceny**, następnie Baselinker
(`modules/baselinker/service.py` → `createPackage` / `getLabel` / `getOrderPackages`,
`account_id=11364`, `courier_code='globkurier'`) do **nadania i etykiety**.

**Flow `create_shipment`, 7 kroków:** produkty → warianty pakowania → ceny GlobKurier →
wybór najtańszej (`min` po `price`) → mapowanie nazwy kuriera na kod Baselinkera
(słownik `COURIER_NAME_TO_CODE`, `shipping.py:141–164`, 22 pozycje) → `create_package()` →
`get_label()` → zapis.

**Nadawca hardcoded:** `36-068` (Bachorz).

**Endpointy (wszystkie znikają):**

```
GET  /production/stations/api/packaging/check-shipping/<order_id>
POST /production/stations/api/packaging/quote/<order_id>
POST /production/stations/api/packaging/ship/<order_id>
GET  /production/stations/api/packaging/refresh-tracking/<order_id>
GET  /production/stations/api/packaging/refresh-label/<order_id>
```

**Co ZOSTAJE mimo usunięcia:**

- kolumny `ProductionOrder.shipping_package_id`, `shipping_tracking_number`,
  `shipping_courier_name`, `shipping_price`, `shipping_label_base64`, `shipping_created_at`
  — **nie kasujemy**, zawierają dane historyczne
- `modules/baselinker/service.py` — `get_order_packages` używa też diagnostyka w
  `modules/baselinker/routers.py`
- `modules/calculator/routers/shipping_routers.py` — **to inny moduł**, wycena dostawy
  w ofercie, bez związku

`modules/production/services/shipping_service.py` (silnik GlobKurier) traci jedynego
użytkownika → usuwamy razem z resztą.

> **Sprostowanie do wcześniejszego audytu:** `sync_service.py:1319–1320` bywało opisywane
> jako „ochrona pól `shipping_*` przed nadpisaniem przez sync Baselinkera". To nieprawda —
> te linie to zbiór `ORDER_LEVEL_KEYS` w `_create_production_product_from_data()`, czyli
> routing pól z płaskiego dicta do `ProductionOrder`. **Żadnej ochrony tam nie ma.**
> Jeśli sync Baselinkera ma nie zerować historycznych danych wysyłkowych, trzeba to
> dopisać jako osobne zadanie — nie zakładać, że już działa.

### 3.5 Co zostaje nietknięte

- **Monitory hali** — `monitors.py` (8 dekoratorów `@route` na 6 funkcjach, wyłącznie `GET`,
  zero przycisków akcji), `monitor.html`, `monitor_station.html`, `monitors_select.html`,
  `station-monitor.js`, `station-monitor.css`, `station-monitor-v2.css`. Nie zależą od
  `interfaces.py` ani `ajax.py`.

  **Jeden wyjątek:** `monitors.py` hostuje też `station_select()` (route'y `/`
  i `/station-select`, linie 18–20), który renderuje `stations/select.html` — plik z listy
  do skasowania. Rozstrzygnięcie: `station_select()` zamieniamy w **redirect na
  `monitors_select`**, a `select.html` kasujemy. `monitors.py` nie jest więc całkiem
  nietknięty — to jedyna zmiana w tym pliku.
- **`station_bp`** — blueprint zostaje (hostuje monitory) razem z `apply_station_security()`,
  `log_station_access()`, `add_station_headers()`, handlerami 403/500, `get_station_config()`,
  `MONITOR_STATION_MAP`, `_get_monitor_station_data()`, `_format_dimension()`

  > **Korekta po wdrożeniu:** `get_station_summary()` zasilała wyłącznie `select.html`,
  > więc po Etapie 0 została bez użytkownika i poszła razem z nim (commit sprzątający).
- **`IPSecurityService`** — używany globalnie (`routers/__init__.py:254, 296`), nie ruszać.
  `ip_security_middleware()` **jest aktywny** — wisi na `station_bp.before_request`
  (`apply_station_security()` → `apply_security()`), więc `PROTECTED_ROUTERS` realnie
  chroni monitory hali. Z listy usunięto tylko cztery martwe prefiksy bez `/stations`;
  wpis `/production/` — który jako jedyny cokolwiek łapał — został.
- **`ProductionProduct.complete_task()`** (`models.py:474`) — używa go mobile.
  Uwaga: `ProductionItem` to tylko alias zgodności (`models.py:533`, z komentarzem
  „zostanie usunięty osobnym commitem"); właściwa klasa nazywa się `ProductionProduct`.
- **`label_print_service`** — współdzielony z mobile API
- **`display_api.py`** + `display_monitor_service` — wyświetlacze ESP8266, niezależny system
- Reszta `products_api.py` — panel CRM, raporty, priorytety, eksporty, admin

### 3.6 Konsekwencja dla profili pracowników

Po Etapie 0 `prod_station_events.source = 'web'` staje się wartością **wyłącznie historyczną**.
Nowe eventy produkcyjne mają `source = 'mobile'`, `'admin'` (panel CRM), `'system'` lub
`'auto_skip'`. Raporty per pracownik pokrywają więc **całą** produkcję — nie ma dziury
„robota zrobiona z przeglądarki".

> **Bug do naprawienia przy okazji:** kolumna `prod_station_events.source` jest w bazie
> zadeklarowana jako `ENUM('web','mobile','admin','system')` (migracja
> `020_station_events.sql:18`), a model używa też `'auto_skip'` (`models.py:1030`).
> **Żadna migracja tej wartości nie dodała.** W trybie strict MySQL zwraca błąd 1265.
> Migracja `MODIFY COLUMN source ENUM(...,'auto_skip')` wchodzi w zakres — patrz §4.6.

---

## 4. Model danych

### 4.1 `prod_workers` — katalog pracowników

```sql
CREATE TABLE IF NOT EXISTS prod_workers (
    id               INT AUTO_INCREMENT PRIMARY KEY,
    first_name       VARCHAR(64)  NOT NULL,
    last_name        VARCHAR(64)  NOT NULL,
    worker_code      VARCHAR(16)  DEFAULT NULL COMMENT 'Rezerwa pod QR/badge, dziś nieużywane',
    pin_hash         VARCHAR(255) DEFAULT NULL COMMENT 'Rezerwa pod przyszłe PIN-y, dziś zawsze NULL',
    avatar_path      VARCHAR(255) DEFAULT NULL,
    color_hex        CHAR(7)      DEFAULT NULL COMMENT 'Tło kafelka gdy brak zdjęcia, np. #3E7C59',
    allowed_stations VARCHAR(255) DEFAULT NULL COMMENT 'CSV kodów stanowisk; NULL/pusty = wszystkie',
    is_active        TINYINT(1)   NOT NULL DEFAULT 1,
    user_id          INT          DEFAULT NULL COMMENT 'Opcjonalne powiązanie z kontem CRM',
    sort_order       SMALLINT     NOT NULL DEFAULT 0,
    created_at       DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at       DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    deactivated_at   DATETIME     DEFAULT NULL,
    UNIQUE KEY uq_worker_code (worker_code),
    INDEX idx_is_active (is_active),
    INDEX idx_user_id (user_id),
    CONSTRAINT fk_workers_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
```

**Zasada twarda: pracowników nigdy nie kasujemy.** Odejście z firmy = `is_active = 0` +
`deactivated_at`. Statystyki historyczne muszą przetrwać, a FK z tabeli atrybucji i tak
by na to nie pozwolił.

`allowed_stations` jako CSV (nie tabela łącząca ani JSON): zbiór pracowników jest rzędu
dziesiątek, filtrowanie robimy w Pythonie po pobraniu całej listy. Osobna tabela to
niepotrzebny JOIN, JSON w MySQL to brzydkie zapytania.

### 4.2 `prod_worker_sessions` — sesje pracy

```sql
CREATE TABLE IF NOT EXISTS prod_worker_sessions (
    id               INT AUTO_INCREMENT PRIMARY KEY,
    worker_id        INT          NOT NULL,
    station_code     VARCHAR(32)  NOT NULL,
    device_id        VARCHAR(64)  DEFAULT NULL COMMENT 'prod_devices.device_id',
    session_group    CHAR(36)     NOT NULL COMMENT 'UUID; łączy sesje wystartowane razem (praca zespołowa)',
    started_at       DATETIME     NOT NULL,
    last_activity_at DATETIME     NOT NULL,
    ended_at         DATETIME     DEFAULT NULL,
    end_reason       ENUM('manual','idle_timeout','night_cutoff','replaced','admin') DEFAULT NULL,
    work_date        DATE         NOT NULL COMMENT 'DATE(started_at) — doba raportowa',
    source           ENUM('mobile','web','admin') NOT NULL DEFAULT 'mobile',
    created_at       DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_worker_date (worker_id, work_date),
    INDEX idx_station_date (station_code, work_date),
    INDEX idx_device_open (device_id, ended_at),
    INDEX idx_open (ended_at),
    INDEX idx_session_group (session_group),
    CONSTRAINT fk_sessions_worker FOREIGN KEY (worker_id) REFERENCES prod_workers(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
```

**`session_group`** jest kluczowy dla pracy zespołowej: gdy Adam i Bartek startują razem,
powstają **dwie sesje** z tym samym `session_group`. Pozwala to:

- zamknąć obie jednym requestem,
- odtworzyć „kto z kim pracował",
- policzyć `share` bez zgadywania (liczba otwartych sesji w grupie).

**Praca zespołowa na jednym urządzeniu = N otwartych sesji z tym samym `device_id`.**
Model to obsługuje naturalnie, bez dodatkowych kolumn.

### 4.3 `prod_station_event_workers` — atrybucja

```sql
CREATE TABLE IF NOT EXISTS prod_station_event_workers (
    event_id   INT           NOT NULL,
    worker_id  INT           NOT NULL,
    session_id INT           DEFAULT NULL,
    share      DECIMAL(9,6)  NOT NULL COMMENT '1/N gdzie N = liczba pracowników przy evencie',
    PRIMARY KEY (event_id, worker_id),
    INDEX idx_worker (worker_id),
    INDEX idx_session (session_id),
    CONSTRAINT fk_sew_event   FOREIGN KEY (event_id)   REFERENCES prod_station_events(id) ON DELETE CASCADE,
    CONSTRAINT fk_sew_worker  FOREIGN KEY (worker_id)  REFERENCES prod_workers(id),
    CONSTRAINT fk_sew_session FOREIGN KEY (session_id) REFERENCES prod_worker_sessions(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
```

**Dlaczego osobna tabela, a nie kolumny w `prod_station_events`:** event pozostaje
niemutowalny i całkowicie niezmieniony. Wszyscy istniejący konsumenci eventów
(`station_events_service.py`, `dashboard_api.py`, `main_routers.py`, `stations/ajax.py`,
`mobile_api_service.py`) działają dalej bez jednej linijki zmiany. Atrybucja to warstwa
**dokładana**, nie przebudowa.

**Dlaczego `share` jest denormalizowany, skoro odradzamy denormalizację:** bo jest
**niemutowalny**. Zapisywany raz przy tworzeniu eventu, nigdy nie aktualizowany — nie ma
więc czego rozjeżdżać. Alternatywa (`1.0 / COUNT(*) OVER (PARTITION BY event_id)`) wymaga
funkcji okienkowych, czyli MySQL 8+; nie chcemy tego zakładać.

**Ograniczenie precyzji, świadome:** przy trzech osobach `share = 0.333333`,
czyli 3 × 0.333333 = 0.999999. Błąd 1e-6 na event; przy 10 000 eventów to 0,01 sztuki.
**Raporty zaokrąglają do 1 miejsca po przecinku i tyle.** Nie warto tego rozwiązywać
przez ułamki licznik/mianownik.

### 4.4 Rozszerzenia istniejących tabel

```sql
-- Naprawa zastanego rozjazdu: model używa 'auto_skip', baza go nie zna
ALTER TABLE prod_station_events
    MODIFY COLUMN source ENUM('web','mobile','admin','system','auto_skip') NOT NULL DEFAULT 'web';

-- Audyt zmian statusu/priorytetu (prod_product_events)
ALTER TABLE prod_product_events
    ADD COLUMN worker_id INT DEFAULT NULL COMMENT 'prod_workers.id — kto wykonał akcję' AFTER user_id,
    ADD INDEX idx_worker_id (worker_id),
    ADD CONSTRAINT fk_product_events_worker FOREIGN KEY (worker_id) REFERENCES prod_workers(id) ON DELETE SET NULL;

ALTER TABLE prod_product_events
    MODIFY COLUMN actor_type ENUM('user','device','system','worker') NOT NULL;

-- Doróbki (prod_rework_log)
ALTER TABLE prod_rework_log
    ADD COLUMN worker_id INT DEFAULT NULL COMMENT 'prod_workers.id — kto zgłosił doróbkę' AFTER user_id,
    ADD INDEX idx_worker_id (worker_id),
    ADD CONSTRAINT fk_rework_worker FOREIGN KEY (worker_id) REFERENCES prod_workers(id) ON DELETE SET NULL;

-- Ostatnie stanowisko urządzenia (przydatne w monitoringu floty; opcjonalne)
ALTER TABLE prod_devices
    ADD COLUMN last_worker_session_at DATETIME DEFAULT NULL COMMENT 'Kiedy ostatnio ktoś zaczął tu sesję';
```

**Uwaga do `prod_product_events` i `prod_rework_log`:** obie tabele to **audyt, nie
statystyka**, i obie mają pojedynczą kolumnę `worker_id`. Przy pracy zespołowej zapisujemy
**pierwszego** pracownika z aktywnej grupy (kolejność z nagłówka `X-Worker-Ids`)
i `actor_type = 'worker'`. Pełna, dzielona atrybucja żyje wyłącznie
w `prod_station_event_workers`.

**Doróbki nie generują eventów stanowiskowych.** `rework_service.reject_product_quantity()`
nie woła `set_quantity_done()`, więc nie powstaje `prod_station_event`, a więc nie ma do
czego dopiąć atrybucji dzielonej. Dla rejectu `X-Worker-Ids` służy wyłącznie do:
(a) zapisania `prod_rework_log.worker_id`, (b) odświeżenia `last_activity_at` sesji.
W raporcie wydajności doróbki nie występują — to zgodne z decyzją nr 9 (bez metryk
jakościowych na tym etapie).

### 4.5 Klucze `prod_config`

Zarządzane z `/production/?tab=config`, zmienialne bez deployu:

| Klucz | Domyślnie | Opis |
|---|---|---|
| `WORKER_SELECTION_REQUIRED` | `true` | **Kill-switch.** `false` = akcje bez `X-Worker-Ids` przechodzą. Jeśli coś się zepsuje, hala nie stoi. |
| `WORKER_SESSION_IDLE_TIMEOUT_MINUTES` | `120` | Liczone od ostatniej **akcji produkcyjnej**, nie od dotknięcia ekranu |
| `WORKER_SESSION_NIGHT_CUTOFF` | `23:00` | Twarde domknięcie zapomnianych sesji |
| `WORKER_QUICK_PICK_COUNT` | `8` | Ile kafelków w „szybkim wyborze" |

Kill-switch jest **wymagany**, nie opcjonalny. Bramka blokuje całe stanowisko — awaria
katalogu pracowników bez kill-switcha oznacza zatrzymanie produkcji.

### 4.6 Migracje

Format datowany, zgodnie z konwencją (`CLAUDE.md` → *Migracje bazy*). Idempotentne,
bez `DELIMITER`:

```
migrations/2026-08-11-01-prod-workers.sql              — prod_workers (bez seeda, katalog uzupełnia panel)
migrations/2026-08-11-02-prod-worker-sessions.sql      — prod_worker_sessions
migrations/2026-08-11-03-prod-station-event-workers.sql— tabela atrybucji
migrations/2026-08-11-04-prod-worker-fk-extensions.sql — ALTER: worker_id w prod_product_events
                                                         i prod_rework_log, last_worker_session_at
                                                         w prod_devices, MODIFY actor_type
                                                         (+'worker'), MODIFY prod_station_events.source
                                                         (+'auto_skip' — naprawa zastanego rozjazdu)
migrations/2026-08-11-05-worker-config-keys.sql        — INSERT IGNORE do prod_config
```

> **Numer po dacie jest obowiązkowy, nie kosmetyczny.** Runner wykonuje migracje
> posortowane **alfabetycznie po nazwie pliku**, a ta piątka ma zależności przez
> klucze obce. Bez numerów kolejność wychodziła
> `prod-station-event-workers` → `prod-worker-fk-extensions` → `prod-worker-sessions`
> → `prod-workers`, czyli tabela atrybucji powstawała **przed** tabelami, do których
> ma FK. MySQL odbijał to błędem 1824 „Failed to open the referenced table",
> co przerywa deploy przed restartem aplikacji. Wykryte dopiero przy uruchomieniu
> migracji na MySQL — testy chodzą na SQLite i takiej kolejności nie sprawdzają.

`ALTER TABLE ... ADD COLUMN` **nie jest** idempotentne w MySQL (błąd 1060 przy powtórce —
dokładnie ten problem opisuje `migrations/2026-08-05-prod-devices-telemetry.sql`).
Osłonić warunkiem na `information_schema.COLUMNS` albo przyjąć jednorazowość i odnotować
to w nagłówku pliku.

### 4.7 Dane historyczne

Eventy sprzed wdrożenia nie mają wierszy w `prod_station_event_workers`. Raporty
prezentują je jako **„Nieprzypisane"** — osobny wiersz, nie ukrywany. To uczciwsze niż
zerowanie i pozwala zobaczyć, kiedy pokrycie atrybucją doszło do 100%.

---

## 5. Logika sesji

### 5.1 Start

```
POST /api/mobile/sessions/start
```

1. Walidacja: wszystkie `worker_ids` istnieją i mają `is_active = 1`
2. **Domknięcie poprzednich sesji tego urządzenia** — `end_reason = 'replaced'`
   (zmiana obsady = koniec poprzedniej sesji, nie jej modyfikacja)
3. `session_group` bierzemy **z requestu** — apka zawsze generuje UUID lokalnie, bo sesja
   startuje offline i `sessionGroup` jest kluczem głównym encji w Room. Serwer generuje
   własny UUID **wyłącznie** dla sesji zakładanych z panelu CRM.
4. Insert N wierszy: `started_at`, `last_activity_at = started_at`, `work_date = DATE(started_at)`
5. Aktualizacja `prod_devices.last_worker_session_at`

`started_at` przyjmujemy **z klienta** (sesja mogła się zacząć offline), ale przycinamy
do `min(client_ts, now)` — nie akceptujemy przyszłości.

### 5.2 Przedłużanie

`last_activity_at` aktualizuje się przy **każdej akcji produkcyjnej** (`complete`,
`quantity`, `reject`) — nie ma osobnego heartbeatu sesji.

Skutek uboczny, który jest tu zaletą: pracownik, który stoi i nic nie robi przez
2 godziny, faktycznie zostaje wylogowany. Metryka „czas pracy" mierzy pracę, nie obecność.

### 5.3 Zamykanie

| Powód | Kto zamyka | Kiedy |
|---|---|---|
| `manual` | apka / panel | Pracownik klika „Zmień pracownika" lub „Zakończ" |
| `replaced` | backend | Nowa sesja na tym samym `device_id` |
| `idle_timeout` | **cron** | `last_activity_at < now - WORKER_SESSION_IDLE_TIMEOUT_MINUTES` |
| `night_cutoff` | **cron** | Po `WORKER_SESSION_NIGHT_CUTOFF` |
| `admin` | panel CRM | Ręczne domknięcie przez brygadzistę |

**Timeout musi być egzekwowany po stronie serwera**, nie tylko w apce — tablet może być
offline, rozładowany albo zrestartowany.

> **Uwaga: `scheduler_daemon.py` NIE ISTNIEJE.** Został usunięty commitem `0684949`
> („usuń martwy scheduler_daemon i nieużywane zależności APScheduler", 2026-05-18)
> razem z APScheduler/tzlocal/tzdata z `requirements.txt`. W repo nie ma żadnego
> schedulera ani `modules/scheduler/`. **Nie planować zadań pod nieistniejący daemon.**

Idziemy ścieżką, która na produkcji faktycznie działa — **endpoint wołany zewnętrznym
cronem hostingu**, dokładnie jak istniejący `/production/api/sync-cron`:

```python
@api_bp.route('/workers/close-stale-sessions', methods=['POST'])
def close_stale_worker_sessions():
    """Domyka sesje po bezczynności i po nocnym cutoffie.
    Wołane cronem hostingu co 5 min (wzorzec: /production/api/sync-cron).
    Idempotentne — działa wyłącznie na wierszach z ended_at IS NULL."""
```

Autoryzacja jak w `sync-cron` (token w query/nagłówku), nie `@login_required` — cron
nie ma sesji. Wpis w crontabie hostingu trzeba dodać ręcznie przy wdrożeniu; to element
zakresu etapu 1, a nie „samo się uruchomi".

Apka egzekwuje ten sam timeout lokalnie, żeby UX był natychmiastowy (nie czeka
na potwierdzenie z serwera). Przy rozjeździe **serwer ma rację**.

### 5.4 Wyliczanie `share`

Przy zapisie eventu:

```python
share = Decimal(1) / Decimal(len(worker_ids))   # kwantyzacja do 6 miejsc
```

`worker_ids` bierzemy **z requestu** (nagłówek `X-Worker-Ids`), nie z listy aktualnie
otwartych sesji. Powód: akcja mogła powstać offline, a sesja mogła się w międzyczasie
zamknąć nocnym cutoffem. Atrybucja musi odzwierciedlać stan **w momencie akcji**,
nie w momencie synchronizacji.

Backend **nie wymaga otwartej sesji** do przyjęcia akcji — wymaga tylko, żeby pracownicy
istnieli i byli aktywni.

---

## 6. API mobilne

Prefiks bez zmian: `/api/mobile` (rejestracja w `app.py:572`). Autoryzacja przez
istniejący `@require_device_token`.

### 6.1 Katalog pracowników

```http
GET /api/mobile/workers
Authorization: Bearer <JWT>
```

```json
{
  "catalog_version": "2026-08-11T09:14:22",
  "quick_pick_count": 8,
  "selection_required": true,
  "idle_timeout_minutes": 120,
  "night_cutoff": "23:00",
  "workers": [
    {
      "id": 3,
      "first_name": "Adam",
      "last_name": "Kowalski",
      "initials": "AK",
      "avatar_url": "https://crm.woodpower.pl/production/uploads/workers/3.jpg",
      "color_hex": "#3E7C59",
      "allowed_stations": ["gluing", "assembly"],
      "recent_on_station": true,
      "sort_order": 10
    }
  ]
}
```

- `recent_on_station` — czy pracował na stanowisku z JWT w ciągu ostatnich 7 dni;
  apka używa tego do sekcji „szybki wybór"
- `catalog_version` — `MAX(updated_at)` z `prod_workers`; obsługa `ETag` / `If-None-Match`,
  żeby apka nie ciągnęła listy przy każdym starcie
- Zwracamy **tylko** `is_active = 1`
- `avatar_url` musi być **pełnym URL-em**, nie ścieżką root-relative. `BASE_URL` w apce
  kończy się na `/api/mobile/` (`NetworkModule.kt:135`), więc `/static/...` by się nie
  skleiło. Wzorzec jest w `mobile_api_service._build_attachments()`, które już zwraca
  pełne URL-e.
- `allowed_stations` to **tablica**; `NULL`/pusta w bazie → zwracamy `[]`, co apka czyta
  jako „wszystkie stanowiska"
- Odpowiedź niesie też pełną konfigurację (`selection_required`, `idle_timeout_minutes`,
  `night_cutoff`, `quick_pick_count`) — apka nie hardkoduje żadnej z tych wartości
  i nie pobiera ich osobnym requestem

### 6.2 Start sesji

```http
POST /api/mobile/sessions/start
X-Operation-Id: <UUID>
```

```json
{
  "worker_ids": [3, 7],
  "station_code": "gluing",
  "session_group": "6f1c...",
  "started_at": "2026-08-11T06:12:00"
}
```

Odpowiedź `201`:

```json
{
  "session_group": "6f1c...",
  "sessions": [
    {"id": 4412, "worker_id": 3, "started_at": "2026-08-11T06:12:00"},
    {"id": 4413, "worker_id": 7, "started_at": "2026-08-11T06:12:00"}
  ],
  "expires_at": "2026-08-11T08:12:00"
}
```

Objęte `@with_idempotency` — offline retry nie tworzy duplikatów.

### 6.3 Koniec sesji

```http
POST /api/mobile/sessions/end
X-Operation-Id: <UUID>
```

```json
{ "session_group": "6f1c...", "ended_at": "2026-08-11T14:03:00", "reason": "manual" }
```

Odpowiedź `204`. Objęte `@with_idempotency` — ten request też idzie przez kolejkę offline,
więc obowiązuje go ta sama zasada „jeden wpis w kolejce = jeden `X-Operation-Id`".

**Dozwolone wartości `reason` od klienta:** `manual`, `idle_timeout`, `night_cutoff`.
Apka egzekwuje timeouty lokalnie (żeby UX był natychmiastowy) i raportuje powód —
serwer go przyjmuje zamiast nadpisywać własnym. Wartości `replaced` i `admin` ustawia
**wyłącznie backend**; przysłane przez klienta → `422`.

### 6.4 Odtworzenie stanu

```http
GET /api/mobile/sessions/active
```

Zwraca otwarte sesje dla `device_id` z JWT. Apka woła to po restarcie/crashu, żeby
nie zmuszać do ponownego wyboru profilu.

### 6.5 Zmiana w istniejących akcjach

`POST /orders/{id}/complete`, `PATCH /orders/{id}/quantity`, `POST /orders/{id}/reject`
dostają **obowiązkowy nagłówek**:

```
X-Worker-Ids: 3,7
```

- Body DTO **bez zmian** — nagłówek nie łamie kompatybilności z niczym
- Gdy `WORKER_SELECTION_REQUIRED = true` i nagłówka brak → `400 worker_ids_required`
- Gdy `false` → apka **pomija nagłówek całkowicie** (nie wysyła pustego stringa),
  akcja przechodzi bez atrybucji. Pusty nagłówek to `422`, nie kill-switch.

**Zakres działania nagłówka per endpoint:**

| Endpoint | Co robi z `X-Worker-Ids` |
|---|---|
| `POST /orders/{id}/complete` | Pełna atrybucja dzielona w `prod_station_event_workers` — **po warunku z §8** |
| `PATCH /orders/{id}/quantity` | Pełna atrybucja dzielona |
| `POST /orders/{id}/reject` | Tylko `prod_rework_log.worker_id` (pierwszy z listy) + `last_activity_at`; brak eventu stanowiskowego, więc brak atrybucji dzielonej |

### 6.6 Kody błędów

| HTTP | `error` | Znaczenie | Reakcja apki |
|---|---|---|---|
| 400 | `worker_ids_required` | Brak nagłówka przy włączonej bramce | Wyrzuć na ekran wyboru, akcja zostaje w kolejce |
| 404 | `worker_not_found` | Nieistniejące `id` | Odśwież katalog, wyrzuć na ekran wyboru |
| 409 | `worker_inactive` | Pracownik dezaktywowany po starcie sesji | Odśwież katalog, wyrzuć na ekran wyboru |
| 422 | `invalid_worker_ids` | Pusta lista / śmieci | Usuń z kolejki, zaloguj |

**Uwaga dla apki:** `SyncWorker` klasyfikuje dziś **każde** 4xx jako `Rejected` i kasuje
wpis z kolejki (`SyncWorker.kt:170`). Dla `400 worker_ids_required` i `409 worker_inactive`
to zgubiłoby wykonaną pracę. Szczegóły w dokumencie mobilnym, rozdział o kolejce.

---

## 7. Panel CRM

### 7.1 Nowa zakładka `/production/?tab=workers`

**Lista pracowników** — imię, nazwisko, avatar, przypisane stanowiska, status, ostatnia
aktywność, robota z ostatnich 7 dni (sztuki + m³). Filtr aktywni/nieaktywni.

**Formularz** — imię, nazwisko, zdjęcie (opcjonalne), kolor kafelka, przypisane stanowiska
(checkboxy), kolejność, powiązanie z kontem CRM (opcjonalne, autocomplete po `users`).

**Dezaktywacja zamiast usuwania.** Przycisk „Usuń" ustawia `is_active = 0` i `deactivated_at`.
Jeśli ktoś naprawdę chce skasować wiersz — FK z `prod_station_event_workers` nie pozwoli,
i bardzo dobrze.

**Panel „Kto teraz na hali"** — otwarte sesje: pracownik, stanowisko, tablet, od kiedy,
ostatnia aktywność, robota w tej sesji. Przycisk domknięcia sesji (`end_reason = 'admin'`).
To najbardziej użyteczna operacyjnie część całej funkcji.

**Zdjęcia:** upload do `modules/production/uploads/workers/` serwowany dedykowanym routem —
konwencja repo dla załączników (wzorzec: `modules/quotes/services/attachment_service.py:12`).
Katalog `static/uploads/` **nie istnieje** i nie tworzymy go. Przeskalowanie do max
256×256 px przy zapisie (kafelki na tablecie nie potrzebują więcej, a 6 tabletów ciągnących
pełne zdjęcia przy każdym starcie to niepotrzebny transfer). Brak zdjęcia = inicjały
na `color_hex`.

### 7.2 Raport wydajności

```http
GET /production/api/reports/worker-output
    ?start_date=2026-08-01&end_date=2026-08-11
    &station=all|<station_code>
    &worker_id=<opcjonalnie>
```

Nowy plik `modules/production/services/worker_stats_service.py`, wzorowany na istniejącym
`station_events_service.py`.

**Wydajność — rdzeń zapytania:**

```sql
SELECT
    w.id, w.first_name, w.last_name,
    DATE(e.created_at)              AS work_date,
    e.station_code,
    SUM(e.delta * ew.share)         AS pieces,
    SUM(p.volume_m3 * e.delta * ew.share) AS m3
FROM prod_station_event_workers ew
JOIN prod_station_events e ON e.id = ew.event_id
JOIN prod_workers w        ON w.id = ew.worker_id
JOIN prod_products p       ON p.id = e.production_item_id
WHERE e.created_at >= :start AND e.created_at < :end
  AND e.source NOT IN ('auto_skip', 'system')   -- eventy, których nikt fizycznie nie wykonał
GROUP BY w.id, DATE(e.created_at), e.station_code
```

Filtr `source` jest **obowiązkowy**, nie kosmetyczny — patrz §8, „Pułapka nr 2".

**Czas pracy — z sesji:**

```sql
SELECT worker_id, work_date,
       SUM(TIMESTAMPDIFF(MINUTE, started_at, COALESCE(ended_at, NOW()))) AS minutes
FROM prod_worker_sessions
WHERE work_date BETWEEN :start AND :end
GROUP BY worker_id, work_date
```

**Tempo** = `m3 / (minutes / 60)`.

**Prezentacja:** tabela dzień × pracownik × stanowisko, sumy dzienne i okresowe,
wiersz „Nieprzypisane" dla eventów bez atrybucji, eksport do XLSX (istnieje już wzorzec
w `products_api.py` → `products/export`).

Uczciwe ostrzeżenie w UI raportu — jedno zdanie pod nagłówkiem, że wybór profilu nie jest
chroniony hasłem, więc dane są poglądowe. Lepiej powiedzieć to raz w interfejsie niż
tłumaczyć przy każdej rozmowie o premiach.

### 7.3 „Kto zrobił" na liście produktów — bez nowych kolumn

Zamiast N+1 zapytań: **jedno** zapytanie zbiorcze dla wszystkich produktów na stronie,
sklejane w Pythonie.

```python
def get_workers_for_products(product_ids: list[int]) -> dict[int, dict[str, list[str]]]:
    """{product_id: {station_code: ['Adam K.', 'Bartek N.']}}
    Jedno zapytanie na całą stronę listy, nie jedno na produkt."""
```

Ta sama funkcja zasila modal historii produktu (`products_api.py:2262`
`GET /production/api/products/<id>/history`) — dokładając do
`product_history_service.merge_history()` nazwiska obok istniejących `last_device_id`
i `last_source`.

---

## 8. Zmiany w istniejącym kodzie

| Plik | Zmiana |
|---|---|
| `modules/production/models.py` | Nowe modele `ProductionWorker`, `ProductionWorkerSession`, `ProductionStationEventWorker`. `set_quantity_done()` przyjmuje `actor_worker_ids: list[int] \| None` i tworzy wiersze atrybucji. |
| `modules/production/services/mobile_api_service.py` | Parser `X-Worker-Ids`, walidacja, przekazanie do `set_quantity_done()`. Nowe handlery sesji. Rozszerzenie `require_device_token` o wstrzyknięcie `g.worker_ids`. |
| `modules/production/routers/mobile_api.py` | 4 nowe route'y (`/workers`, `/sessions/start`, `/sessions/end`, `/sessions/active`) |
| `modules/production/services/product_events.py` | `build_actor()` / `current_actor()` rozpoznają `actor_type = 'worker'`; kolejność pierwszeństwa: **worker → device → user → system** |
| `modules/production/services/rework_service.py` | `reject_product_quantity()` przyjmuje `worker_ids` |
| `modules/production/services/worker_stats_service.py` | **Nowy** — agregaty wydajności i czasu pracy |
| `modules/production/routers/api/workers_api.py` | **Nowy** — CRUD + raport + „kto na hali" + endpoint cron |
| `modules/production/templates/components/workers-tab-content.html` | **Nowy** (zakładki modułu leżą w `templates/components/`, nie `templates/production/`) |
| crontab hostingu | Wpis wołający `/production/api/workers/close-stale-sessions` co 5 min |

### Pułapka nr 1: `/orders/{id}/complete` nie generuje ŻADNEGO eventu

**To nie jest pytanie otwarte — to potwierdzony brak i obowiązkowy punkt zakresu.**

Sprawdzone w kodzie: `mobile_api.py:254 order_complete` → `mobile_api_service.mark_order_complete()`
(ok. linia 1087) woła `item.complete_task(station_code)` **bezpośrednio, z pominięciem
`set_quantity_done()`**. A `complete_task()` (`models.py:474`) tworzy `ProductionStationEvent`
**wyłącznie dla stanowisk pominiętych** (`auto_skip` w `models.py:491`, `system`
w `models.py:499`) — dla stanowiska faktycznie zamykanego nie tworzy nic.

Konsekwencja: **dziś zamknięcie stanowiska nie zostawia śladu w `prod_station_events`.**
Nie da się do tego dopiąć `prod_station_event_workers`, więc bez naprawy cała atrybucja
pokryłaby wyłącznie `PATCH /orders/{id}/quantity`.

Po Etapie 0 `/orders/{id}/complete` zostaje **jedyną** ścieżką zamykania stanowiska
(webowy `complete_order_bulk()` znika), więc dziura obejmuje 100% tej operacji.

**Naprawa (wchodzi w etap 3, nie „do rozważenia"):**

```python
# mobile_api_service.mark_order_complete()
item.set_quantity_done(
    station_code, item.quantity,
    source='mobile', actor_device_id=device_id, actor_worker_ids=worker_ids,
)
# dopiero potem complete_task() dla tranzycji statusu
```

Bez tego scenariusz ręczny z dokumentu mobilnego (§11, kroki 1–5) nie może przejść —
i to jest właśnie test, który tę naprawę weryfikuje.

### Pułapka nr 2: eventy, których nikt nie wykonał

`complete_task()` generuje sztuczne eventy dla stanowisk pominiętych:

- `source = 'auto_skip'` (`models.py:491`) — produkt nieprzycinany na wymiar
  (`should_skip_to_logistics()`) po sklejeniu przeskakuje formatowanie i wykańczanie
- `source = 'system'` (`models.py:499`) — przeskok `formatting → finishing`

**Te eventy nie dostają atrybucji** — nikt ich fizycznie nie wykonał. Raport musi je
filtrować (`AND e.source NOT IN ('auto_skip','system')`, §7.2), inaczej sklejacz dostanie
kredyt za formatowanie, którego nie było.

Filtrowanie po `source` jest odporniejsze niż poleganie na „braku wiersza atrybucji" —
działa nawet gdy ktoś kiedyś nieopatrznie dopisze atrybucję do tych ścieżek.

---

## 9. Kolejność wdrożenia

> **Stan na 2026-08-11:** etapy **1-3 zaimplementowane** (gałąź `worktree-worker-profiles`).
> Migracje przetestowane na MySQL 8.4 — wykonują się na czystym schemacie i są
> idempotentne przy powtórce. `WORKER_SELECTION_REQUIRED = false`, więc hala
> pracuje dokładnie jak dotąd. Do zrobienia poza kodem CRM:
> **wpis w crontabie** wołający `/production/api/workers/close-stale-sessions`
> (bez niego sesje wiszą do ręcznego domknięcia) oraz etapy 4-5, czyli roll-out
> apki i dopiero potem włączenie bramki. Etap 6 (raporty) nietknięty.

| Etap | Zakres | Ryzyko |
|---|---|---|
| **0** | Usunięcie webowych paneli wykonawczych (rozdz. 3) + naprawa dashboardu + test regresyjny hooka BL | Średnie — dotyka działającego systemu, ale hala już pracuje na apce |
| **1** | Migracje + modele + CRUD w panelu CRM + wpis w crontabie. Pracownicy wpisani, nic ich jeszcze nie używa. | Zerowe |
| **2** | `GET /api/mobile/workers` + endpointy sesji. Apka może już pobierać katalog. | Zerowe — nowe endpointy |
| **3** | **Naprawa `mark_order_complete()`** (§8, pułapka nr 1) + atrybucja `X-Worker-Ids` w akcjach, `WORKER_SELECTION_REQUIRED = false`. Kto przysyła — zapisujemy; kto nie — przechodzi. | Niskie |
| **4** | Roll-out apki po jednym tablecie — do wersji **M5 włącznie** (apka wysyła już `X-Worker-Ids`). Weryfikacja, że atrybucja faktycznie wchodzi do bazy. | Niskie |
| **5** | `WORKER_SELECTION_REQUIRED = true`. Bramka aktywna (apka M4). | **Wysokie** — od tej chwili awaria katalogu zatrzymuje halę. Kill-switch musi być przetestowany **przed** tym krokiem. |
| **6** | Raport wydajności + „kto na hali" + kolumna na liście produktów | Zerowe |

Uwaga do etapu 4: weryfikacja atrybucji wymaga apki, która **wysyła** nagłówek, czyli
mobilnego M5. Kolejność w apce to `M5 → M4` (najpierw wysyłanie, potem bramka) —
patrz dokument mobilny §10. Włączenie bramki bez działającej atrybucji dałoby ludziom
tarcie bez żadnego zysku.

Etapy 1–3 wchodzą na produkcję **bez żadnej zmiany w zachowaniu systemu**. Dopiero etap 5
jest przełącznikiem. Ta kolejność pozwala wycofać się na każdym kroku.

---

## 10. Ryzyka

| Ryzyko | Skala | Mitygacja |
|---|---|---|
| Awaria katalogu zatrzymuje całą halę | **Wysoka** | `WORKER_SELECTION_REQUIRED` w `prod_config`, zmienialny bez deployu. Przetestować przed etapem 5. |
| Ludzie klikają byle kogo / pierwszy kafelek z brzegu | Wysoka | Nie do rozwiązania technicznie bez PIN-u. Zaadresować organizacyjnie; monitorować rozkład (jeden profil z 80% robocizny = sygnał). |
| Jeden zalogowany na całą brygadę | Średnia | Panel „kto na hali" pokazuje to natychmiast. Timeout 120 min ogranicza szkody. |
| Sesje wiszące przez noc | Średnia | Nocny cutoff 23:00 + idle timeout. Egzekwowane serwerowo. |
| Praca offline z nieaktualnym katalogiem | Niska | Katalog w Room, `catalog_version` przy każdym starcie. Dezaktywowany pracownik daje 409, akcja wraca do kolejki. |
| Utrata pracy przy 4xx w kolejce sync | **Wysoka** | `SyncWorker` kasuje wpis przy każdym 4xx. `400` i `409` z tej funkcji **muszą** być wyjątkiem — szczegóły w dokumencie mobilnym. |
| `auto_skip` zawyża statystyki | Średnia | Raport pomija eventy bez atrybucji zamiast przypisywać je do aktywnej sesji. |
| Rozjazd zegara tabletu | Niska | `started_at` przycinane do `min(client, now)`; `work_date` liczone serwerowo. |

---

## 11. Pytania otwarte

1. **Ilu jest pracowników?** Decyduje o układzie ekranu wyboru (jedna siatka vs. przewijanie).
   Przy >20 kafelkach trzeba przemyśleć wyszukiwanie.
2. **Czy „szybki wybór" ma być per stanowisko czy per urządzenie?**
   Zaproponowano per stanowisko (z JWT). Do weryfikacji po pierwszym tygodniu użycia.
3. **Czy panel „kto na hali" ma trafić na monitory TV?**
   `monitors.py` zostaje — technicznie łatwe, pytanie czy potrzebne.
4. **Czy sync Baselinkera ma chronić historyczne pola `shipping_*`?**
   Wbrew wcześniejszym założeniom takiej ochrony w kodzie nie ma (§3.4). Do decyzji:
   dopisać ją czy przyjąć, że dane wysyłkowe mogą zostać nadpisane.

Rozstrzygnięte w trakcie weryfikacji, zostawione dla historii:

- ~~Czy mobilne `/orders/{id}/complete` odpala `baselinker_status_sync`?~~ **Tak** —
  `mobile_api_service.py:1107-1109` + `:581`. Nie blokuje etapu 0.
- ~~Czy mobilna ścieżka `complete` przechodzi przez `set_quantity_done()`?~~ **Nie** —
  i to jest bug do naprawienia w etapie 3, nie pytanie otwarte. Patrz §8, pułapka nr 1.
