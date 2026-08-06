# Kontrakt API trakowni (`/api/mobile/sawmill/*`) — integracja z aplikacją Android

Dokument dla zespołu piszącego natywną aplikację Android na tablet stanowiska traka.
**Nie zakłada dostępu do kodu Pythona ani do reszty dokumentacji CRM** — wszystko, co
potrzebne do zbudowania klienta, jest tutaj. Układ wzorowany na `docs/bot-api-contract.md`.

> **Źródło prawdy:** `modules/production/sawmill/routers/mobile_api.py` (7 endpointów
> trakowni), `modules/production/routers/mobile_api.py` (rejestracja, heartbeat — wspólne
> dla całej floty tabletów produkcji), `modules/production/sawmill/services/serializers.py`,
> `modules/production/sawmill/services/validation.py`,
> `modules/production/sawmill/services/settings.py`. Przykłady JSON poniżej to realne
> kształty odpowiedzi (nazwy pól 1:1 z kodem), nie parafrazy.

---

## 1. Kontekst — po co jest trakownia i dlaczego appka nie widzi deklaracji

Trakownia to rejestr kłód drewna wchodzących do zakładu, **zanim** cokolwiek stanie się
produktem. Biuro wprowadza dostawę z objętością zadeklarowaną przez dostawcę (na fakturze
albo bez niej). Pracownik na tablecie mierzy każdą kłodę **niezależnie** — system potem
porównuje sumę realnie zmierzoną z deklaracją.

**Sedno biznesowe: wykryć rozbieżność między deklaracją a rzeczywistością.** Dlatego
API mobilne **celowo nigdy nie zwraca** deklarowanej objętości, ceny ani żadnej wartości
finansowej — gdyby pracownik ją widział, pomiary zaczęłyby się do niej „magicznie"
zbiegać, i cała kontrolna wartość modułu by przepadła. Pełna lista pól, które appka
nigdy nie dostanie, jest w sekcji 9 — **to jest zamierzone, nie przeoczenie**.

Trakownia to osobny rejestr, niepowiązany z zamówieniami/produktami reszty CRM. Dzieli
z resztą floty tabletów produkcji wyłącznie infrastrukturę: rejestrację urządzenia, JWT,
heartbeat i mechanizm kolejki offline (`X-Operation-Id`).

### 1.1 Zakres po stronie aplikacji — czego oczekujemy

Trakownia **nie jest wariantem istniejącego ekranu stanowiska.** Nie da się jej dołożyć
przez podmianę etykiet czy dodanie gałęzi `if (station == "sawmill")` w obecnym widoku
kolejki — model danych jest inny (zlecenia dostaw i kłody zamiast produktów zamówienia),
inny jest przepływ pracy i inne endpointy.

Do zbudowania:

1. **Nowa pozycja „Trakownia" na ekranie rejestracji urządzenia.** Wybór stanowiska musi
   dawać `station_code: "sawmill"` w `POST /api/mobile/register` (sekcja 3.1). Uwaga:
   trakownia **nie ma aliasów** — token zarejestrowany dla dowolnego innego stanowiska
   dostaje `403 station_mismatch` na każdym endpoincie `/api/mobile/sawmill/*`, i
   odwrotnie. To celowe, w odróżnieniu od pozostałych stacji produkcji, gdzie tokeny
   bywają współdzielone.
2. **Nowy ekran listy zleceń** — otwarte zlecenia z `GET /orders`, odświeżane z
   `If-None-Match` (sekcja 4.1). Na kafelku zlecenia: numer TRK, gatunek, dostawca,
   numer faktury, liczba zmierzonych kłód i suma m³. **Nigdy deklaracja** — patrz
   sekcja 9, to sedno modułu.
3. **Nowy ekran pomiaru** — formularz o **dwóch polach liczbowych**: obwód w połowie
   długości kłody i długość, oba w cm z jednym miejscem po przecinku (sekcja 4.3).
   Do tego lista dotychczasowych kłód zlecenia z możliwością korekty (4.4) i usunięcia
   (4.5) oraz przycisk zakończenia zlecenia (4.6).
4. **Kolejka offline** z `X-Operation-Id` — sekcja 6. To nie jest komponent UI, ale
   jest to najbardziej ryzykowna część integracji i musi powstać razem z ekranem
   pomiaru, nie po nim.

Komponenty do ponownego użycia z istniejącej appki: warstwa sieciowa (JWT, nagłówki,
`X-App-Version`), ekran rejestracji jako *szkielet* (dochodzi pozycja na liście
stanowisk), heartbeat i mechanizm aktualizacji APK. Cała reszta — modele, ekrany,
walidacja, kolejka — jest nowa.

---

## 2. Zasady wspólne

- **Bazowy URL (produkcja):** `https://crm.woodpower.pl`
- **Prefiks endpointów trakowni:** `/api/mobile/sawmill` (7 endpointów, sekcja 4).
- **Prefiks rejestracji/heartbeatu (wspólny dla całej floty):** `/api/mobile` (sekcja 3).
- **Autoryzacja:** nagłówek `Authorization: Bearer <JWT>` w **każdym** żądaniu do
  `/api/mobile/sawmill/*` (JWT otrzymany z `POST /api/mobile/register`, sekcja 3.1).
  Bez tego nagłówka albo ze złym tokenem: `401`.
- **`X-App-Version`:** opcjonalny nagłówek z wersją appki (np. `1.2.0`, semver). Gdy
  serwer ma skonfigurowaną minimalną wspieraną wersję i appka jest poniżej niej → `426`
  (sekcja 8). Gdy nagłówek nie jest wysłany, sprawdzenie wersji jest **pomijane** —
  ale wysyłaj go zawsze, to jedyny sposób serwera, żeby wymusić aktualizację floty.
- **`X-Operation-Id`:** wymagany na **wszystkich czterech endpointach mutujących**
  (`POST /orders/<id>/logs`, `PATCH /logs/<id>`, `DELETE /logs/<id>`,
  `POST /orders/<id>/complete`). Mechanizm idempotencji opisany w sekcji 6 —
  **to jest najważniejsza część tego kontraktu**, przeczytaj ją w całości przed
  implementacją kolejki offline.
- **Format odpowiedzi:** zawsze JSON. Sukces → kształt opisany przy każdym endpoincie.
  Błąd → `{"error": "<kod>", ...dodatkowe pola}` z odpowiednim kodem HTTP (sekcja 7).
  Kontrakt trakowni, w odróżnieniu od bota kalkulatora, **używa kodów HTTP**, nie pola
  `ok`.
- **Jednostki:** średnice i długość w **centymetrach**, objętość w **m³**. Liczby jako
  JSON number (nie string) — zarówno w request, jak i response.
- **Separator dziesiętny w body:** kropka (`42.5`, nie `42,5`) — to standardowy JSON
  number, walidacja po stronie serwera akceptuje też przecinek jako wygodę (patrz
  sekcja 5), ale appka powinna zawsze wysyłać kropkę.

---

## 3. Rejestracja urządzenia i utrzymanie sesji

### 3.1 `POST /api/mobile/register`

Rejestruje tablet i zwraca JWT. **Idempotentne** — ponowna rejestracja tego samego
`device_id` aktualizuje wpis (nowy `station_code`/`device_name`, reaktywacja gdy
urządzenie było zablokowane) i zawsze zwraca **nowy** token. Uwaga: sama re-rejestracja
**nie unieważnia** poprzedniego tokenu — oba (stary i nowy) pozostają ważne równolegle,
bo o tym decyduje `token_version` na urządzeniu, a zwykła re-rejestracja go nie zmienia.
`token_version` jest bumpowany wyłącznie osobną akcją administracyjną w panelu (np. po
zgubieniu/kradzieży tabletu) i dopiero to unieważnia **wszystkie** dotąd wydane JWT
naraz. Appka i tak powinna zawsze używać najświeższego tokenu, jaki dostała.

**Request:**
```json
{"device_id": "TRAK-TABLET-01", "device_name": "Tablet trak hala A", "station_code": "sawmill"}
```
- `device_id` (string, **wymagane**) — unikalny identyfikator fizycznego urządzenia,
  appka generuje go raz i trwale przechowuje (np. Android ID / UUID zapisany lokalnie).
- `device_name` (string, opcjonalne) — czytelna nazwa do panelu admina.
- `station_code` (string, **wymagane**) — dla trakowni zawsze dosłownie `"sawmill"`.

**Response 200:**
```json
{"token": "eyJhbGciOiJIUzI1NiIs...", "device_id": "TRAK-TABLET-01", "station_code": "sawmill"}
```
Token JWT jest **opakiem** dla appki — nie trzeba go dekodować, tylko przechowywać
i wysyłać w `Authorization: Bearer <token>`. Ważność: zwykle 365 dni (konfigurowalne
po stronie serwera). Appka wykrywa wygaśnięcie/unieważnienie po `401 invalid_token`
z dowolnego endpointu i wtedy rejestruje się ponownie.

**Błędy:**
- `400 missing_fields` — brak `device_id` lub `station_code`; pole `required` w
  odpowiedzi wskazuje, czego brakuje.
- `400 invalid_station_code` — `station_code` spoza dozwolonej listy; pole `allowed`
  w odpowiedzi wypisuje wszystkie dozwolone kody (dla trakowni zawsze używaj `"sawmill"`).
- `500 registration_failed` — błąd serwera, ponów żądanie.

**curl:**
```bash
curl -X POST https://crm.woodpower.pl/api/mobile/register \
  -H "Content-Type: application/json" \
  -d '{"device_id": "TRAK-TABLET-01", "device_name": "Tablet trak hala A", "station_code": "sawmill"}'
```

### 3.2 `POST /api/mobile/devices/heartbeat`

Telemetria urządzenia (bateria, temperatura, wersja appki) — zasila badge tabletu
w panelu admina. **Zalecane co ~15 minut**, ale nie jest to twardy wymóg protokołu:
każde uwierzytelnione żądanie do dowolnego endpointu (nie tylko heartbeat) odświeża
też `last_seen_at` po stronie serwera, więc tablet aktywnie pracujący na tablecie liczy
się jako „Aktywny", zanim jeszcze wyśle pierwszy heartbeat.

Wymaga `Authorization: Bearer <JWT>`. **Bez `X-Operation-Id`** — heartbeat nie jest
idempotentny, każde wywołanie po prostu nadpisuje pola telemetrii na urządzeniu.

**Request:**
```json
{"battery_pct": 78, "battery_charging": false, "temperature_c": 31.2,
 "app_version_code": 14, "app_version_name": "1.2.0", "ip_address": "192.168.1.42"}
```
- `app_version_code` (int, **wymagane**) i `app_version_name` (string, **wymagane**).
- `battery_pct` (int 0–100, opcjonalne), `battery_charging` (bool, opcjonalne),
  `temperature_c` (float, zakres -20.0–100.0, opcjonalne), `ip_address` (string, opcjonalne).

**Response:** `204 No Content` (brak body) przy sukcesie.

**Błędy:** `422 validation` (`detail` z opisem, np. `"battery_pct out of range"` albo
`"app_version_code required"`) · `500 internal`.

### 3.3 `GET /api/mobile/app/version` — sanity-check przed rejestracją (opcjonalny)

Publiczny (bez JWT). Zwraca metadane najnowszego aktywnego release'u APK — appka może
go odpytać przed rejestracją, żeby sprawdzić czy jest aktualna.

```json
{"version_code": 14, "version_name": "1.2.0", "sha256": "…", "release_notes": "…",
 "file_size_bytes": 11534336, "apk_url": "/api/mobile/app/apk?version=14",
 "min_supported_version": "1.0.0"}
```
Gdy w bazie nie ma żadnego release'u: `{"version_code": 0, ...}` — appka interpretuje
to jako „brak aktualizacji do pobrania".

---

## 4. Endpointy trakowni (`/api/mobile/sawmill/*`)

Wszystkie poniższe wymagają `Authorization: Bearer <JWT>` z urządzenia zarejestrowanego
jako `station_code = "sawmill"`. Token zarejestrowany dla innego stanowiska dostaje
`403 station_mismatch` na każdym z nich (sekcja 7) — trakownia **nie** dzieli kolejki
z żadnym innym stanowiskiem (bez aliasów, w odróżnieniu od pozostałych stacji produkcji).

### 4.1 `GET /orders` — lista otwartych zleceń

Zwraca zlecenia w statusie `new` lub `in_progress` — **zakończone i rozliczone znikają
z tej listy**. Appka nie musi (i nie powinna) się martwić o filtrowanie po statusie.
Kolejność: rosnąco po `order_number` (czyli w praktyce chronologicznie w ramach roku,
`TRK/2026/001` przed `TRK/2026/002`) — brak paginacji, lista wraca w całości za jednym
razem.

Wspiera cache HTTP: odpowiedź niesie nagłówek `ETag` (format `W/"..."`, weak). Wyślij
go z powrotem jako `If-None-Match` przy kolejnym odpytaniu — gdy nic się nie zmieniło,
dostaniesz `304 Not Modified` bez body (oszczędność transferu przy częstym pollingu).
Odpowiedź niesie też `Cache-Control: private, max-age=15`.

**Response 200:**
```json
{"orders": [{
  "id": 12,
  "order_number": "TRK/2026/007",
  "species": "Dąb",
  "supplier_name": "Tartak Nowak sp. z o.o.",
  "invoice_number": "FV/2026/0451",
  "delivery_date": "2026-08-03",
  "status": "in_progress",
  "logs_count": 46,
  "measured_volume_m3": 23.847,
  "started_at": "2026-08-05T07:12:00"
}]}
```
- `status` — tu zawsze `"new"` albo `"in_progress"` (nic innego nie trafia do tej listy).
- `logs_count` / `measured_volume_m3` — **zawsze liczby, nigdy `null`**, nawet dla
  zlecenia bez ani jednego pomiaru (wtedy `0` / `0.0`).
- `started_at` — `null` dopóki nie padł pierwszy pomiar (status wciąż `"new"`).
- `supplier_name` / `invoice_number` / `delivery_date` mogą być `null`, gdy dostawa nie
  ma faktury (`invoice_number`/`invoice_date` są opcjonalne przy zakładaniu dostawy) —
  `delivery_date` samo w sobie jest zawsze ustawione po stronie serwera, ale jeśli
  kiedykolwiek zobaczysz tu `null`, traktuj to jak brak danych, nie błąd.

**curl:**
```bash
curl https://crm.woodpower.pl/api/mobile/sawmill/orders \
  -H "Authorization: Bearer $TOKEN" -H "X-App-Version: 1.2.0"
```

### 4.2 `GET /orders/<id>` — szczegóły zlecenia

**Bez ETagu/cache** (w odróżnieniu od `GET /orders`) — zawsze pełna odpowiedź 200.
Zwraca zlecenie w tym samym kształcie co wyżej, plus listę pomiarów (bez soft-skasowanych).

**Response 200:**
```json
{"order": { "...jak w GET /orders..." }, "logs": [{
  "id": 501, "sequence_no": 46,
  "mid_circumference_cm": 125.6,
  "length_cm": 410.0, "volume_m3": 0.514699,
  "measured_at": "2026-08-05T09:31:12"
}]}
```
- `logs` posortowane po `sequence_no` rosnąco (kolejność dodawania kłód, nadana przez
  serwer — patrz sekcja 5, appka nie generuje własnych numerów).
- `volume_m3` ma 6 miejsc po przecinku — to wartość **zapisana** przy tworzeniu pomiaru
  (nie liczona na bieżąco), pokazuj ją bez przeliczania.

**Błędy:** `404 order_not_found`.

### 4.3 `POST /orders/<id>/logs` — dodanie pomiaru kłody

Wymaga `X-Operation-Id` (**kolejka offline — przeczytaj sekcję 6 przed wdrożeniem**).

**Request:**
```json
{"mid_circumference_cm": 125.6,
 "length_cm": 410.0, "measured_at": "2026-08-05T09:31:12"}
```
Wszystkie trzy pola **wymagane**. Pracownik wprowadza **tylko dwie liczby**: obwód
zmierzony taśmą w połowie długości kłody oraz długość — obie w centymetrach, z jednym
miejscem po przecinku. Nie ma i nie będzie pól średnicy: metodyka pomiaru (Huber) jest
decyzją zarządu, a nie szczegółem implementacyjnym, który appka mogłaby rozszerzyć.
Format `measured_at` i tolerancja zegara — sekcja 5.

**Response 201:**
```json
{"log": { "...jak w logs[] wyżej..." }, "order": { "...jak w GET /orders..." }}
```
`order` w odpowiedzi ma już zaktualizowane `logs_count` i `measured_volume_m3` —
nie trzeba dociągać `GET /orders/<id>` po zapisie, żeby odświeżyć sumę na ekranie.
Pierwszy pomiar zlecenia przełącza `status` `"new" → "in_progress"` i ustawia
`started_at` — również widoczne w tym samym response, bez dodatkowego żądania.

**Błędy:** `404 order_not_found` · `422 validation_error` · `409 order_not_open`
(**patrz sekcja 6** — to jest ścieżka kolejki offline, obsłuż ją dokładnie tak, jak tam
opisano, nie jak zwykły błąd czterysta-coś).

**curl:**
```bash
curl -X POST https://crm.woodpower.pl/api/mobile/sawmill/orders/12/logs \
  -H "Authorization: Bearer $TOKEN" -H "X-App-Version: 1.2.0" \
  -H "X-Operation-Id: 8f14e45f-ceea-467e-bd3f-0e4a8a4b6b1a" \
  -H "Content-Type: application/json" \
  -d '{"mid_circumference_cm": 125.6, "length_cm": 410.0, "measured_at": "2026-08-05T09:31:12"}'
```

### 4.4 `PATCH /logs/<id>` — korekta pomiaru

Wymaga `X-Operation-Id`. Dozwolone tylko gdy zlecenie jest wciąż `new`/`in_progress`
(inaczej `409 order_not_open` — z panelu admin może edytować dłużej, ale appka już nie).

**Request — TYLKO dwa pola wymiarów, dokładnie jak przy tworzeniu:**
```json
{"mid_circumference_cm": 126.1, "length_cm": 410.0}
```

> **Ważne, łatwe do przeoczenia:** `measured_at` **NIE JEST** akceptowane przez ten
> endpoint. Serwer nie parsuje i nie zmienia `measured_at` przy korekcie — czas
> pierwotnego pomiaru zostaje bez zmian, niezależnie od tego, kiedy wykonano korektę.
> Jeśli appka wyśle pole `measured_at` w tym body, zostanie po prostu zignorowane
> (endpoint go w ogóle nie czyta). Nie buduj UI korekty w oparciu o założenie, że da się
> tu poprawić też czas pomiaru — nie da się, przez ten endpoint nigdy.

**Response 200:**
```json
{"log": { "...zaktualizowany pomiar, measured_at bez zmian..." },
 "order": { "...jak w GET /orders..." }}
```
Tak jak przy `POST .../logs`, `order` w odpowiedzi ma już przeliczone
`measured_volume_m3` (korekta wymiaru zmienia sumę zlecenia) — nie trzeba dociągać
`GET /orders/<id>` po edycji tylko po to, żeby odświeżyć sumę na ekranie.

**Błędy:** `404 log_not_found` · `422 validation_error` · `409 order_not_open`.

### 4.5 `DELETE /logs/<id>` — usunięcie pomiaru

Wymaga `X-Operation-Id`. Soft delete — kłoda znika z list i z sumy, ale jej
`sequence_no` **nie jest nigdy ponownie użyty** przez kolejny pomiar.

**Request:** brak body.

**Response 200:**
```json
{"order": { "...jak w GET /orders..., logs_count i measured_volume_m3 już bez tej kłody..." }}
```

**Błędy:** `404 log_not_found` · `409 order_not_open`.

### 4.6 `POST /orders/<id>/complete` — zakończenie zlecenia przez pracownika

Wymaga `X-Operation-Id`. To jedyna zmiana statusu, jaką appka może wykonać — od tej
chwili `status` = `"completed"` i **żaden** z endpointów 4.3–4.5 dla tego zlecenia nie
zadziała już z tabletu (`409 order_not_open`), dopóki biuro nie użyje „Cofnij
zakończenie" w panelu.

**Request:** brak body.

**Response 200:**
```json
{"order": { "...status: \"completed\"..." }}
```

**Błędy:**
- `404 order_not_found`.
- `409 order_not_open` — **dwa różne powody kryją się pod tym samym kodem błędu:**
  1. zlecenie już nie jest w `new`/`in_progress` (np. drugi tablet/panel już je zamknął),
  2. zlecenie **nie ma ani jednego pomiaru** — nie da się zakończyć pustego zlecenia.

  Kod błędu jest identyczny w obu przypadkach; jeśli appka chce rozróżnić komunikat dla
  pracownika, musi spojrzeć na `detail` w odpowiedzi (tekst po polsku, nieprzeznaczony
  do parsowania — traktuj go jako informację dla człowieka, nie jako maszynowy kod).

### 4.7 `GET /config` — limity walidacji do pracy offline

Appka MUSI pobrać ten endpoint po rejestracji i **co jakiś czas odświeżać** (limity mogą
się zmienić w panelu), żeby lokalna walidacja formularza pomiaru używała aktualnych
progów, zanim cokolwiek wyśle do serwera.

**Response 200:**
```json
{"min_circumference_cm": 30.0, "max_circumference_cm": null,
 "min_length_cm": 30.0, "max_length_cm": 20000.0,
 "decimal_places": 1}
```
Zwróć uwagę: `max_circumference_cm` jest domyślnie `null` — obwód **nie ma górnego
limitu** (decyzja biznesowa: nietypowo gruba kłoda ma przejść bez interwencji biura).
To nie jest błąd konfiguracji ani wartość do zastąpienia własną stałą.
Znaczenie i semantyka `null` — **sekcja 8**. `decimal_places` (dziś zawsze `1`) to
maksymalna liczba miejsc po przecinku akceptowana przez serwer dla obu
wymiarów — pilnuj tego już w klawiaturze/formularzu na tablecie, żeby pracownik nie
musiał się dowiadywać o odrzuceniu dopiero po wysyłce.

Ten endpoint **nie zwraca** `deviation_threshold_pct` (próg flagowania odchylenia) —
to ustawienie panelu, patrz sekcja 9.

---

## 5. Format `measured_at` i tolerancja zegara

Format: **naiwny ISO-8601 czasu lokalnego, BEZ offsetu strefy** —
`"2026-08-05T09:31:12"`. **Nie** wysyłaj `Z` ani `+02:00` — serwer to jawnie odrzuca:

- Wartość z offsetem/strefą (`.../...+02:00`, `...Z`) → `422 validation_error`,
  `field: "measured_at"`, `detail: "oczekiwano czasu lokalnego bez offsetu strefy"`.
- Wartość nie do sparsowania jako ISO-8601 → `422 validation_error`,
  `detail: "oczekiwano formatu RRRR-MM-DDTGG:MM:SS"`.

**Tolerancja zegara tabletu:**
- Do **5 minut** w przyszłość względem czasu serwera — akceptowane bez zmian.
- **Powyżej** 5 minut w przyszłość — serwer **po cichu przycina wartość do własnego
  czasu** (nie odrzuca!) i zapisuje pomiar z tym przyciętym czasem. Odpowiedź `201`
  wygląda normalnie; appka nie dostaje żadnej informacji zwrotnej o tym, że czas został
  skorygowany — jeśli chcesz to wykryć, porównaj `measured_at` w zwróconym `log` z tym,
  co appka wysłała.
- **Starsze niż 30 dni** → **odrzucone**, `422 validation_error`,
  `detail: "pomiar starszy niż 30 dni"`. To realny scenariusz przy bardzo długiej
  kolejce offline — appka powinna to pokazać pracownikowi jako trwały błąd (nie
  ponawiać), analogicznie do innych `422`.

Konsekwencja dla appki: **zegar systemowy tabletu spieszący się o kilka minut nigdy nie
kosztuje pomiaru** — to świadome zabezpieczenie, nie luka. Dopiero drastyczny rozjazd
(>30 dni w przeszłość) albo bardzo stary zegar odrzuca dane.

Walidacja wymiarów (te same zasady co limity z `GET /config`, sekcja 4.7 i 8): każda
wartość musi być dodatnia, mieścić się w `[min, max]` swojej kategorii (obwód vs.
długość) i mieć maksymalnie `decimal_places` miejsc po przecinku. Serwer sprawdza **oba
pola wymiarów w kolejności** `mid_circumference_cm, length_cm`
i zwraca błąd dla **pierwszego** napotkanego — jeśli oba pola są błędne naraz,
`field` w odpowiedzi wskaże tylko jedno z nich; napraw je i wyślij ponownie (walidacja
lokalna z `GET /config`, sekcja 8, powinna i tak wyłapać wszystkie błędy naraz, zanim
appka w ogóle wyśle żądanie).

---

## 6. Kolejka offline i kod `409` — najważniejsza część tego kontraktu

**Scenariusz:** tablet traci sieć. Pracownik dalej mierzy — pomiary lądują w lokalnej
kolejce offline appki. W tym czasie biuro (albo panel, albo drugi tablet) kończy albo
rozlicza to samo zlecenie. Sieć wraca, appka zaczyna wysyłać zaległą kolejkę i dostaje
`409 order_not_open` na zaległych pomiarach.

**To NIE jest błąd trwały jak `422`.** Sam kod błędu jest identyczny niezależnie od tego,
czy zlecenie zostało zamknięte przez kogoś innego, czy appka próbuje dodać pomiar do
zlecenia, które od razu było zamknięte (np. źle zsynchronizowana lista) — w obu
przypadkach zachowanie appki ma być **to samo**, opisane w czterech punktach niżej.

Dotyczy **wszystkich czterech** endpointów mutujących trakowni: `POST .../logs`,
`PATCH /logs/<id>`, `DELETE /logs/<id>`, `POST .../complete` — każdy z nich może dostać
`409 order_not_open`, gdy zlecenie w międzyczasie przestało być `new`/`in_progress`.

### Postępowanie appki przy `409` (dokładnie te cztery kroki):

1. **Zostaw wpis w kolejce offline — nie kasuj go.** Pomiar wciąż istnieje tylko lokalnie
   na tablecie; skasowanie wpisu po `409` **trwale go gubi** — serwer nigdy go nie
   otrzyma, a nie ma nigdzie kopii poza kolejką appki.
2. **Pokaż wpis w widocznej liście „błędy synchronizacji"**, żeby pracownik/kierownik
   zmiany wiedział, że coś czeka na ręczną interwencję biura.
3. **Nie ponawiaj automatycznie w pętli.** Dopóki zlecenie pozostaje zamknięte po
   drugiej stronie, każda kolejna próba da dokładnie to samo `409` — pusty retry-loop
   tylko zasypuje serwer bezsensownymi żądaniami i wyczerpuje baterię/transfer tabletu.
4. **Ponów WYŁĄCZNIE przy następnej ręcznej synchronizacji** (przycisk „Synchronizuj"
   w appce) albo gdy zlecenie ponownie pojawi się na liście `GET /orders` (bo biuro
   użyło „Cofnij zakończenie" w panelu) — **i zawsze z tym samym `X-Operation-Id`**,
   który appka wygenerowała przy pierwszej próbie dla tego konkretnego pomiaru/edycji/
   usunięcia. **Nigdy nie generuj nowego `X-Operation-Id` dla ponowienia tej samej
   operacji z kolejki.**

### Dlaczego to działa — i dlaczego odstępstwo od punktów 1 i 4 psuje dane

Mechanizm idempotencji serwera (`X-Operation-Id`) normalnie zapamiętuje **każdą**
odpowiedź (2xx i 4xx) i przy powtórnym żądaniu z tym samym `X-Operation-Id` **nie
wykonuje handlera ponownie** — po prostu odsyła zapamiętaną odpowiedź z pierwszej próby.
Gdyby to dotyczyło też `409`, ponowienie po tym, jak biuro otworzy zlecenie z powrotem,
i tak dostałoby odtworzone `409` z pamięci — **bez żadnej szansy na zapis pomiaru**,
bo handler w ogóle by się nie uruchomił.

Serwer **celowo robi wyjątek dla `409` na endpointach trakowni**: ta konkretna
odpowiedź **nie jest zapisywana** w tabeli idempotencji. Dzięki temu ponowienie z tym
samym `X-Operation-Id`, wysłane PO tym, jak biuro cofnie zamknięcie zlecenia, faktycznie
**wykonuje handler od nowa** i tym razem kończy się `201`/`200` z prawdziwym zapisem.

Stąd dwie twarde zasady, obie z konkretną, złą konsekwencją przy złamaniu:

- **Skasowanie wpisu z kolejki po `409` → pomiar ginie bezpowrotnie.** Serwer nie ma
  żadnej kopii tego pomiaru — istniał tylko na tablecie, w tym jednym wpisie kolejki.
  Nie da się go „odzyskać" inaczej niż wpisując ponownie ręcznie w panelu (co jest
  dopuszczalną, ale awaryjną ścieżką biura, nie czymś, na czym appka ma polegać).
- **Wygenerowanie NOWEGO `X-Operation-Id` przy ponowieniu → ryzyko duplikatu.** Nowy
  operation-id to dla serwera zupełnie inna, nigdy niewidziana operacja — jeśli
  poprzednia próba z jakiegoś powodu jednak coś zapisała (np. appka dostała `409`
  z opóźnieniem sieciowym, ale serwer commitował coś przed tym, jak zlecenie zostało
  zamknięte — wyścig), ponowienie z nowym ID nie ma jak tego wykryć i stworzy drugą
  kłodę dla tego samego pomiaru fizycznego.

**Krótko: jeden pomiar w kolejce = jeden `X-Operation-Id`, na zawsze, dopóki appka nie
dostanie za niego odpowiedzi innej niż `409` albo `5xx`.**

---

## 7. Tabela kodów błędów

| Kod HTTP | `error` | Kiedy | Co ma zrobić appka |
|---|---|---|---|
| 401 | `missing_token` | brak nagłówka `Authorization: Bearer ...` | Ponowna rejestracja urządzenia (sekcja 3.1) |
| 401 | `invalid_token` | token wygasł / podpis zły / urządzenie zablokowane (`detail` z powodem) | Ponowna rejestracja urządzenia |
| 403 | `ip_not_allowed` | IP tabletu poza whitelistą (jeśli włączona po stronie serwera) | Pokaż komunikat, brak retry — problem sieci/konfiguracji, nie appki |
| 403 | `station_mismatch` (+ `device_station`, `required_station`) | token zarejestrowany dla innego `station_code` niż `sawmill` | Pokaż komunikat „to urządzenie nie jest trakiem", nie ponawiaj |
| 404 | `order_not_found` | zlecenie o podanym `id` nie istnieje | Usuń z lokalnej listy, odśwież `GET /orders` |
| 404 | `log_not_found` | pomiar o podanym `id` nie istnieje (albo już soft-skasowany) | Usuń z lokalnego stanu, odśwież szczegóły zlecenia |
| 409 | `order_not_open` | zlecenie nie jest już `new`/`in_progress` (zamknięte gdzie indziej, albo próba `complete` pustego zlecenia) | **Sekcja 6 — cztery kroki, nie zwykły błąd** |
| 422 | `validation_error` (+ `field`, `detail`) | wymiar/`measured_at` poza dozwolonym zakresem albo złego formatu | Pokaż błąd przy konkretnym polu (`field`), **nie ponawiaj** tym samym payloadem bez poprawki |
| 426 | `app_version_too_old` (+ `min_supported`, `your_version`) | appka poniżej minimalnej wspieranej wersji | Zablokuj pracę, wymuś aktualizację z `GET /app/version` |
| 5xx | — (body może nie być JSON-em) | błąd serwera / bazy / sieci po stronie backendu | **Ponawiaj z tym samym `X-Operation-Id`** — serwer świadomie NIE zapisuje odpowiedzi 5xx w tabeli idempotencji (dokładnie ta sama zasada co dla `409` z sekcji 6), więc bezpiecznie odtworzy operację od zera przy ponowieniu |

Wiersz `5xx` jest łatwy do przeoczenia, a krytyczny: potraktowanie każdego `5xx` jako
błędu trwałego (jak `422`) i porzucenie wpisu z kolejki gubi pomiar dokładnie tak samo,
jak skasowanie wpisu po `409` (sekcja 6) — mechanizm ochronny jest identyczny dla obu
kodów, tylko przyczyna inna (tam: zlecenie zamknięte; tu: awaria serwera).

`400` (np. `missing_fields` przy rejestracji) różni się od powyższych — to błąd samego
kształtu żądania (appka wysłała niekompletne dane), nie coś do retry z tym samym
payloadem bez poprawki.

---

## 8. Walidacja lokalna i semantyka `null` w `GET /config`

Appka **musi** walidować pomiar lokalnie, offline, PRZED wstawieniem go do kolejki —
przy złej sieci pracownik i tak zobaczy błąd dopiero przy synchronizacji, a to zbyt
późno, żeby poprawić coś, co mógł zauważyć od razu.

Cztery limity z `GET /config` (`min_circumference_cm`, `max_circumference_cm`,
`min_length_cm`, `max_length_cm`) mogą każdy niezależnie przyjść jako **`null`** — to się dzieje, gdy
administrator wyczyścił dane pole w panelu konfiguracji.

> **`null` znaczy „nie sprawdzaj tego limitu w ogóle", NIE „limit wynosi zero".**
> Kod, który potraktuje `null` jak `0` (np. `wartość < (min ?? 0)` w Kotlinie/Javie),
> odrzuci **każdy** dodatni pomiar, bo żaden sensowny obwód ani długość nie jest
> ujemna — cała walidacja przestanie przepuszczać cokolwiek, po cichu, bez żadnego
> wyjątku czy crasha. Zaimplementuj to jako jawne rozgałęzienie: `if (min != null && value
> < min) { ...błąd... }`, analogicznie dla `max`. Dokładnie to samo zabezpieczenie
> (`null` = pomiń sprawdzenie) obowiązuje po stronie serwera — więc appka, która
> zignoruje lokalnie zbyt szeroki/wąski pomiar przy `null`, i tak dostanie `201` przy
> wysyłce, nie `422`.

`decimal_places` (dziś zawsze `1`, ale appka nie powinna go zaszywać na sztywno) nigdy
nie jest `null` — to stała serwera, nie ustawienie, które administrator mógłby wyczyścić.

Odśwież `GET /config` przy starcie appki i okresowo (np. przy każdej ręcznej
synchronizacji) — limity mogą się zmienić w panelu w dowolnym momencie, a appka
z przeterminowanym configiem albo odrzuci poprawne pomiary, albo przepuści lokalnie to,
co serwer i tak odrzuci.

---

## 9. Czego to API nigdy nie zwróci — i dlaczego to zamierzone

Serializer mobilny (`serialize_order_for_device` w `services/serializers.py`) jest
zbudowany na **białej liście pól**, nie na wykluczeniach — dodanie nowej kolumny do
zlecenia w przyszłości **nie** poszerzy automatycznie tego, co appka dostaje. Poniższa
lista pól jest w kodzie zaszyta jako stała (`DEVICE_FORBIDDEN_FIELDS`) właśnie po to,
żeby dało się ją zaasertować testem — **żaden z poniższych kluczy nigdy nie pojawi się
w żadnej odpowiedzi `/api/mobile/sawmill/*`**. Jeśli podczas integracji zobaczysz jeden
z nich w JSON-ie, to błąd po stronie serwera do zgłoszenia, nie coś, na czym można polegać.

| Pole | Dlaczego appka go nie dostaje |
|---|---|
| `declared_volume_m3` | Deklaracja dostawcy — sedno kontroli modułu. Gdyby pracownik ją widział, pomiary zaczęłyby się do niej „magicznie" zbiegać. |
| `declared_logs_count` | Deklarowana liczba kłód — ten sam mechanizm zbiegania co wyżej. |
| `price_per_m3` | Dane finansowe zakupu surowca — poza zakresem stanowiska pomiarowego. |
| `declared_value` | Wyliczona wartość finansowa deklaracji (`declared_volume_m3 × price_per_m3`) — jw. |
| `agreed_volume_m3` | Objętość uzgodniona z dostawcą przy rozliczeniu — decyzja biura, podejmowana już PO zakończeniu pomiarów przez tablet. |
| `notes` | Notatka na zleceniu — najbardziej prawdopodobne miejsce, gdzie ktoś ręcznie wpisze coś w rodzaju „80 m³ wg WZ"; ujawniłoby to deklarację pośrednio. |
| `settlement_notes` | Notatka rozliczeniowa biura — wynik weryfikacji różnicy, nieistotny i nieznany na etapie mierzenia. |
| `deviation_threshold_pct` | Próg flagowania odchylenia (ustawienie panelu) — tablet nie liczy różnic (nie zna deklaracji), więc próg nic by mu nie powiedział. |

Dodatkowo, dla porządku (to nie są pola „zakazane", po prostu nie ma ich w żadnym
odpowiadanym kształcie): `GET /orders` i `GET /orders/<id>.order` nie zawierają
`invoice_date` (tylko `invoice_number`), danych adresowych ani kontaktowych dostawcy —
appka dostaje tylko to, co potrzebne do zidentyfikowania zlecenia i wykonania pomiaru.

---

## 10. Skrócona checklista integracji

1. `POST /api/mobile/register` ze `station_code: "sawmill"` → zapisz `token` trwale.
2. Każde żądanie do `/api/mobile/sawmill/*`: nagłówek `Authorization: Bearer <token>`
   (+ `X-App-Version` zalecane, `X-Operation-Id` wymagane na czterech endpointach
   mutujących, wygenerowane RAZ na operację i trzymane razem z wpisem kolejki).
3. Pobierz `GET /config` przy starcie i waliduj lokalnie z semantyką `null` = „pomiń"
   (sekcja 8), zanim cokolwiek wyślesz.
4. `GET /orders` z `If-None-Match` do odświeżania listy (obsłuż `304`).
5. Kolejka offline: przy `409` (i przy `5xx`) **nie kasuj wpisu, nie generuj nowego
   `X-Operation-Id`, nie ponawiaj automatycznie w pętli** — sekcja 6 to najważniejsza
   część tego dokumentu, wróć do niej przy każdej wątpliwości.
6. Nigdy nie zakładaj obecności pól z sekcji 9 w odpowiedzi — jeśli UI potrzebuje np.
   deklaracji, to znak, że dany ekran nie powinien istnieć na tablecie tego stanowiska.
