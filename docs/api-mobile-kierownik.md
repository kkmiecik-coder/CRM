# API mobilne — stanowisko „Kierownik hali”

## 0. Do kogo i na czym stoi ten dokument

- **Dla kogo:** sesja appki produkcyjnej Android (`crm_prod_app`). Dokument opisuje wyłącznie końcówki backendu i ich
  zachowanie. Wygląd ekranów ustala sesja appki.
- **Status:** **wdrożone na gałęzi `worktree-kierownik-hali`** (19.10.2026), jeszcze nie na `main`: kod wchodzi na
  produkcję po przeglądzie końcowym. Nazwy tras, pól i kodów błędów zostały takie, jak w projekcie kontraktu.
  Odnośniki `plik:linia` poniżej wskazują stan gałęzi na commicie, który dodał ten dokument do repo (najnowszy
  commit zmieniający ten plik); kształty odpowiedzi sprawdzono z kodem i testami (`tests/test_kierownik_*.py`).
  Zmiany po wdrożeniu na `main` dopiszemy tu z oznaczeniem **[zmiana]**. Do tego czasu sprawdzaj na podglądzie
  wskazanym przez Konrada, nigdy na produkcji.
- **Wspólne zasady API mobilnego** (rejestracja, JWT, `X-App-Version`, `X-Worker-Ids`, sesje, heartbeat,
  `X-Operation-Id`) są takie same jak na pozostałych tabletach. Ten dokument powtarza tylko to, co dla kierownika
  działa inaczej.

### Gdzie to stoi w kodzie CRM

Blueprint rejestruje `app.py:886-888` pod `/api/mobile/manager`. Trasy: `modules/production/kierownik/routers/mobile_api.py`
(w tabeli niżej sam numer linii w tym pliku), logika w `modules/production/kierownik/services/`. Każda trasa idzie
przez `require_device_token` (`modules/production/services/mobile_api_service.py:407`) i bramkę kierownika; zapisy
dodatkowo przez `with_idempotency` (`mobile_api_service.py:458`, lista ponawialnych kodów `BLEDY_DO_PONOWIENIA` w
`modules/production/routers/mobile_api.py:130`).

| Co | Trasa (`mobile_api.py`) | Logika |
|---|---|---|
| Bramka (§2.1) | — | `services/bramka.py:49` (`wymaga_kierownika`), `:28` (`kierownik`: kolejność odmów 400/422/404/403) |
| Biała lista pól (§11) | — | `services/biala_lista.py` (`ZAKAZANE_KLUCZE`, `zakazane_w`; pilnują jej testy każdej trasy i `tests/test_kierownik_przekroj.py`) |
| `GET /manager/orders` (§5.1) | `:37` | `services/zamowienia.py:72` (parametry), `:333` (`lista`), `:632` (ETag) |
| `GET /manager/orders/<id>` (§5.2) | `:52` | `services/zamowienia.py:515` (`karta`) |
| `GET /manager/products/<id>/history` (§5.3) | `:63` | `services/zamowienia.py:606` (`historia`) |
| `POST /manager/products/status` (§6) | `:357` | `:284` (walidacja ciała), `:313` (akcja), `:240` (szkielet zapisu z ponowieniem po 1213), `:237` (dozwolone statusy); wspólny serwis z hurtem w panelu: `modules/production/services/zmiana_statusu.py:126` (`zmien_status`), `:31` (blokady); bliźniak w webie: `modules/production/routers/api/products_api.py:1159` (`bulk_action`) |
| `GET /manager/stations` (§7.1) | `:81` | `services/stanowiska.py:140` (`przeglad`) |
| `GET /manager/stations/<kod>` (§7.2) | `:96` | `services/stanowiska.py:162` (`pelne`), `:38` (`wczytaj_limit`) |
| `POST /manager/stations/<kod>/desk` (§7.3) | `:435` | `:372` (akcja), `modules/production/priorytety/services/stol.py:911` (`wyslij`) |
| `POST /manager/stations/<kod>/desk/remove` (§7.4) | `:451` | `:399` (akcja), `stol.py:980` (`zdejmij_przez_biuro`) |
| `GET /manager/workers/now` (§7.5) | `:111` | `services/stanowiska.py:203` (`obsada`) |
| `GET /manager/routes` (§8.1) | `:122` | `services/trasy.py:53` (parametry), `:174` (`lista`), `:228` (ETag) |
| `GET /manager/routes/<id>` (§8.2) | `:138` | `services/trasy.py:189` (`szczegoly`), `:232` (ETag) |
| `GET /manager/sawmill/orders` (§8.3) | `:155` | `services/trakownia.py:66` (parametry), `:181` (`lista`), `:272` (ETag) |
| `GET /manager/sawmill/orders/<id>` (§8.4) | `:171` | `services/trakownia.py:233` (`zlecenie`) |
| `GET /manager/reports/stations` (§8.5) | `:196` | `services/raporty.py:52` (`zakres`), `:92` (`stanowiska`) |
| `GET /manager/reports/workers` (§8.6) | `:207` | `services/raporty.py:153` (`pracownicy`), nad wspólnym raportem `modules/production/services/worker_stats_service.py:563` (`raport_wydajnosci`; tempo: `:336` `minuty_sesji_zakresu`) |
| `GET /manager/reports/daily` (§8.7) | `:222` | `services/raporty.py:227` (`dzien_po_dniu`) |

Poza blueprintem kierownika: stanowisko `manager` w katalogu stanowisk — `modules/production/services/station_catalog.py:57`
i lista dozwolonych kodów rejestracji `modules/production/models.py:1204`; `is_manager` pracownika — kolumna
`modules/production/models.py:1542`, katalog `GET /api/mobile/workers` `modules/production/services/worker_service.py:281`,
zakładka Pracownicy `modules/production/routers/api/workers_api.py:47`; kanały realtime kierownika —
`modules/production/routers/mobile_api.py:664` (`realtime_token`, gałąź `manager`); migracja
`migrations/2026-10-19-kierownik-hali.sql`.

---

## 1. Najważniejsze w pięciu zdaniach

1. **Tablet kierownika to urządzenie ze stanowiskiem `manager`.** Rejestruje się i czeka na zatwierdzenie jak każdy
   tablet. Nie ma kolejki pracy, stołu, ZAKOŃCZ ani licznika sztuk.
2. **Każde żądanie `/api/mobile/manager/*` wymaga profilu kierownika.** Pierwszy identyfikator w `X-Worker-Ids` musi
   należeć do aktywnego pracownika z `is_manager: true` (katalog `GET /api/mobile/workers`), inaczej 403
   `not_a_manager`. Dotyczy to także odczytów.
3. **Kierownik ma cztery zapisy:** zmianę statusu pozycji (jednej albo wielu), „Na stół”, „Zdejmij ze stołu”, oraz
   start i koniec sesji pracownika jak na innych tabletach. Każdy zapis wymaga `X-Operation-Id`. Reszta to podgląd.
4. **Kwot, e-maili i telefonów API nie zwraca nigdzie.** Dotyczy to zamówień, tras i trakowni.
5. **Odświeżanie:** po sygnale realtime `station:<kod>` (tablet kierownika słucha wszystkich 7 stanowisk), a bez
   sygnałów odpytywanie w rytmie z §9.

---

## 2. Zasady wspólne

| Element | Wartość |
|---|---|
| Adres | `https://crm.woodpower.pl` |
| Prefiks kierownika | `/api/mobile/manager` |
| Uwierzytelnienie | `Authorization: Bearer <JWT z /api/mobile/register>` |
| Wersja appki | `X-App-Version: <wersja>`; poniżej minimum serwer odpowiada 426 `app_version_too_old` (jak wszędzie) |
| Kierownik | `X-Worker-Ids: <id kierownika>[,<inni>]`. Liczy się **pierwszy** identyfikator |
| Zapisy | `X-Operation-Id: <UUID>` **obowiązkowe**, bez niego 400 `missing_operation_id` |
| Format | JSON UTF-8. Daty `RRRR-MM-DD`, czas lokalny ISO 8601 **bez strefy** (`2026-10-19T09:41:07`) |
| Błędy | `{"error": "<kod>", "message": "<zdanie po polsku do pokazania>"}`, czasem z polami dodatkowymi |
| m³ | zawsze objętość sztuki × liczba sztuk, zaokrąglone do 4 miejsc |
| Pamięć podręczna | listy mają słaby `ETag` i `Cache-Control: private, max-age=15`, appka wysyła `If-None-Match` i dostaje 304; karty i odczyty „na żywo” mają `no-store` |

### 2.1 Bramka kierownika (każda trasa `/manager/*`)

Serwer sprawdza w tej kolejności:

| Kolejność | Status | Ciało | Kiedy | Co robi appka |
|---|---|---|---|---|
| 1 | 401 | `missing_token` / `invalid_token` + `reason` | jak na innych tabletach | jak na innych tabletach (rejestracja od nowa / ekran blokady) |
| 2 | 426 | `app_version_too_old` | stara appka | ekran aktualizacji |
| 3 | 403 | `station_not_allowed` | urządzenie nie jest zarejestrowane jako `manager` | ekran „Ten tablet nie jest tabletem kierownika” |
| 4 | 400 | `worker_required` | brak `X-Worker-Ids` | wróć do wyboru profilu |
| 5 | 422 | `invalid_worker_ids` | nagłówek pusty albo niepoprawny | wróć do wyboru profilu |
| 6 | 404 | `worker_not_found` | nieznany pracownik | odśwież katalog, wróć do wyboru profilu |
| 7 | 403 | `not_a_manager` | pracownik nieaktywny albo bez `is_manager` | komunikat z `message`, wróć do wyboru profilu |

---

## 3. Rejestracja, profil, sesja (istniejące końcówki, różnice dla kierownika)

| Końcówka | Różnica dla kierownika |
|---|---|
| `POST /api/mobile/register` | `station_code: "manager"`. Reszta bez zmian (prośba → 202 `pending` → zatwierdzenie w panelu „Urządzenia mobilne” → 200 z tokenem). Przed wdrożeniem backendu serwer odrzuci kod `manager` błędem walidacji, a appka ma to pokazać czytelnie |
| `GET /api/mobile/workers` | **[nowe pole]** `is_manager: bool` w każdym pracowniku. Profile bez `is_manager` appka kierownika wyszarza albo ukrywa. ETag katalogu zmieni się raz po wdrożeniu (nowy kształt) |
| `POST /api/mobile/sessions/start`, `/sessions/end`, `GET /sessions/active` | bez zmian, `station_code: "manager"`. Kierownik z otwartą sesją jest widoczny w „Kto teraz pracuje” jako „Kierownik hali” |
| `POST /api/mobile/devices/heartbeat` | bez zmian |
| `GET /api/mobile/realtime-token` | **[zmiana]** dla `manager` zwraca kanały wszystkich 7 stanowisk (§9) |
| `GET /api/mobile/app/version`, `/app/apk` | bez zmian |

Końcówki stanowisk (`/stations/<kod>/orders`, `/desk`, `/orders/search`, `/orders/<id>/complete` itd.) **nie są
dla kierownika** i appka kierownika ich nie woła. Większość odpowie 403 `station_mismatch`, a wszystko, czego
kierownik potrzebuje, jest pod `/manager/*`.

---

## 4. Tabela końcówek kierownika

| # | Metoda i trasa | Co robi | Sekcja |
|---|---|---|---|
| 1 | `GET /manager/orders` | Lista zamówień (bieżące, archiwum, wszystkie) ze statystykami | §5.1 |
| 2 | `GET /manager/orders/<order_id>` | Karta zamówienia z pełnymi pozycjami | §5.2 |
| 3 | `GET /manager/products/<product_id>/history` | Historia pozycji | §5.3 |
| 4 | `POST /manager/products/status` | Zmiana statusu pozycji | §6 |
| 5 | `GET /manager/stations` | Przegląd 7 stanowisk + obsada | §7.1 |
| 6 | `GET /manager/stations/<kod>` | Pełne stanowisko: stół, odłożone, do zdjęcia, niekompletne, kolejka | §7.2 |
| 7 | `POST /manager/stations/<kod>/desk` | „Na stół” — zamówienie na stół stanowiska | §7.3 |
| 8 | `POST /manager/stations/<kod>/desk/remove` | „Zdejmij ze stołu” | §7.4 |
| 9 | `GET /manager/workers/now` | Kto teraz pracuje (wszystkie stanowiska) | §7.5 |
| 10 | `GET /manager/routes` | Lista tras transportu własnego | §8.1 |
| 11 | `GET /manager/routes/<route_id>` | Trasa z przystankami i przebiegiem | §8.2 |
| 12 | `GET /manager/sawmill/orders` | Zlecenia trakowni | §8.3 |
| 13 | `GET /manager/sawmill/orders/<id>` | Zlecenie trakowni z kłodami | §8.4 |
| 14 | `GET /manager/reports/stations` | Raport: przerób stanowisk | §8.5 |
| 15 | `GET /manager/reports/workers` | Raport: wydajność pracowników | §8.6 |
| 16 | `GET /manager/reports/daily` | Raport: przerób dzień po dniu | §8.7 |

Wszystkie trasy w tabeli mają prefiks `/api/mobile`.

### 4.1 Słowniki

**Statusy pozycji** (`status`) z etykietą (`status_etykieta`), w kolejności procesu:

| Kod | Etykieta | Kierownik może ustawić? |
|---|---|---|
| `czeka_na_wyciecie` | Czeka na wycięcie | tak |
| `czeka_na_skladanie` | Czeka na składanie | tak |
| `czeka_na_sklejanie` | Czeka na sklejanie | tak |
| `czeka_na_formatowanie` | Czeka na formatowanie | tak |
| `czeka_na_krawedzie` | Czeka na krawędzie | tak |
| `czeka_na_lakiernie` | Czeka na lakiernię | tak |
| `czeka_na_pakowanie` | Czeka na pakowanie | tak |
| `spakowane` | Spakowane | tak |
| `zweryfikowane` | Zweryfikowane | nie (nadaje Weryfikacja) |
| `zaladowane` | Załadowane | nie (nadaje Dostawa) |
| `dostarczone` | Dostarczone | nie (nadaje Dostawa / „Wydane klientowi”) |
| `wstrzymane` | Wstrzymane | tak |
| `anulowane` | Anulowane | tak |
| `w_realizacji`, `czeka_na_logistyke` | stare wartości, mogą się trafić w historii | nie |

Appka bierze etykiety z odpowiedzi (`status_etykieta`) i nie trzyma własnej kopii. Lista „można ustawić” wraca w
błędzie 400 `status_niedozwolony` (pole `dozwolone`).

**Stanowiska** (`kod`, w kolejności procesu): `cutting` Wycinanie, `assembly` Składanie, `gluing` Sklejanie,
`formatting` Formatowanie, `edges` Krawędzie, `painting` Lakiernia (bez stołu), `packaging` Pakowanie. Poza
procesem (pojawiają się tylko w „Kto teraz pracuje”): `sawmill` Trakownia, `verification` Weryfikacja, `delivery`
Dostawa, `manager` Kierownik hali. Nazwy wracają w polach `nazwa`.

**Sposób dostawy** (`sposob`): `kurier_baselinker`, `transport_woodpower`, `odbior_osobisty` albo `null` („Nie
ustawiono”). Etykieta w `sposob_etykieta`.

---

## 5. Zamówienia

### 5.1 `GET /api/mobile/manager/orders`

**Parametry (query):**

| Parametr | Domyślnie | Uwagi |
|---|---|---|
| `view` | `active` | `active` = bieżące (wszystko poza archiwum, także spakowane, ale jeszcze otwarte w logistyce). `archive` = zamknięte w logistyce albo w całości anulowane. `all` = oba (do szukania po numerze) |
| `search` | — | numer wewnętrzny, numer Base., numer wyceny, numer zamówienia klienta, klient (imię i nazwisko, firma), nazwa pozycji, `short_product_id`. Bez rozróżniania wielkości liter, fragment wystarczy. Znaki `%` i `_` są zwykłymi znakami, nie wieloznacznymi |
| `status` | — | tylko zamówienia z co najmniej jedną pozycją w tym statusie (§4.1) |
| `completed_from`, `completed_to` | — | tylko `archive`: data zakończenia `RRRR-MM-DD`, obie granice włącznie |
| `page` | 1 | od 1 |
| `per_page` | 50 | 1–100 |

**Kolejność:** `active` według kolejki priorytetów (ranga rosnąco, bez rangi na końcu), `archive` od najświeżej
zakończonych, `all` od najnowszych.

**Ciało 200:**

```json
{
  "view": "active",
  "zamowienia": [
    {
      "order_id": 812,
      "numer": "25_01234",
      "baselinker_order_id": 41188237,
      "quote_number": "W/2026/0912",
      "zrodlo": "Sklep",
      "klient": {"nazwa": "Jan Kowalski", "firma": "Kowalski Meble Sp. z o.o.", "miasto": "Rzeszów"},
      "sposob": "transport_woodpower",
      "sposob_etykieta": "Transport WoodPower",
      "termin": "2026-10-24",
      "dni_do_terminu": 5,
      "gwiazdki": 2,
      "ranga": 14,
      "status_zbiorczy": {"status": null, "etykieta": "Różne (2/4)"},
      "etap_logistyki": {"kod": "w_produkcji", "etykieta": "W produkcji"},
      "trasa": {"id": 33, "nazwa": "Rzeszów czw.", "status": "zatwierdzona"},
      "zakonczono": null,
      "pozycji": 4,
      "sztuk": 6,
      "m3": 0.4122,
      "pozycje": [
        {
          "product_id": 5521,
          "short_product_id": "25_01234_1",
          "nazwa": "Blat dąb lity 4 cm",
          "wymiary": {"dlugosc_cm": 240.0, "szerokosc_cm": 65.0, "grubosc_cm": 4.0},
          "sztuk": 1,
          "status": "czeka_na_formatowanie",
          "status_etykieta": "Czeka na formatowanie",
          "m3": 0.0624,
          "dorobka": false
        }
      ]
    }
  ],
  "statystyki": {
    "zamowien": 143,
    "pozycji": 521,
    "sztuk": 790,
    "m3": 61.2034,
    "wg_statusu": {
      "czeka_na_formatowanie": {"pozycji": 48, "sztuk": 70, "m3": 6.1022}
    },
    "sztuk_do_spakowania": 612,
    "m3_do_spakowania": 47.9311
  },
  "strona": {"page": 1, "per_page": 50, "lacznie": 143, "stron": 3}
}
```

| Pole | Typ | Znaczenie |
|---|---|---|
| `klient.nazwa` | string/null | imię i nazwisko odbiorcy (z dostawy), a gdy go brak, nazwa klienta |
| `klient.firma` | string/null | firma z adresu dostawy |
| `termin` / `dni_do_terminu` | data/int, null | najbliższy termin aktywnej pozycji; ujemne = po terminie |
| `gwiazdki` | int 0–5 | priorytet zamówienia (tylko odczyt) |
| `ranga` | int/null | miejsce w kolejce produkcji (mniej = wcześniej); null dla zamówienia archiwalnego (ma wtedy `zakonczono`) |
| `status_zbiorczy` | obiekt | jeden status, gdy wszystkie pozycje zamówienia mają ten sam (`status` = kod), inaczej `status: null` i etykieta „Różne (x/n)”. Liczy też pozycje anulowane — ta sama funkcja, która rysuje plakietkę statusu w webie |
| `etap_logistyki` | obiekt | `{kod, etykieta}`. Przed spakowaniem zawsze `w_produkcji` / „W produkcji” (na którym stanowisku stoi zamówienie, mówią `status_zbiorczy` i pozycje). Po spakowaniu `kod` to status najbardziej zaległej pozycji (`spakowane`, `zweryfikowane`, `zaladowane`, `dostarczone`), a etykieta jest ta sama co w panelu Logistyki. Zamówienie bez aktywnych pozycji: `anulowane` |
| `trasa` | obiekt/null | trasa transportu, na której jest zamówienie |
| `zakonczono` | czas/null | tylko archiwum: data zakończenia |
| `pozycji`, `sztuk`, `m3` | liczby | zamówienia; anulowane pozycje liczą się w `pozycji`, ale nie w `sztuk` i `m3`. Reguła jest ta sama we wszystkich widokach, także w archiwum (w webie archiwum wlicza anulowane do m³, więc dla archiwum nasze m³ bywa mniejsze — świadomie) |
| `pozycje[]` | lista | wszystkie pozycje zamówienia w skrócie, w kolejności z zamówienia |
| `statystyki` | obiekt | na **całym** przefiltrowanym zbiorze zamówień, nie na stronie. Liczą wszystkie pozycje tych zamówień, także te, które same nie pasują do `status` ani `search` (widok jest zamówieniowy); bez filtrów wynik jest identyczny jak w webie |
| `statystyki.wg_statusu` | mapa | rozkład pozycji według statusu; brak klucza = 0. Wiersz `anulowane` ma `pozycji` > 0, ale `sztuk: 0` i `m3: 0.0`, żeby suma wierszy zgadzała się z liczbami ogólnymi |
| `statystyki.*_do_spakowania` | liczby | tylko `active`: sztuki jeszcze niespakowane (tak samo jak licznik w webie) |
| `statystyki.sredni_czas_realizacji_dni` | liczba | tylko `archive` |

**Błędy:** 400 `dane_niepoprawne` (zły `view`, `status`, data, `page`, `per_page`).

**Pamięć podręczna:** ETag, `max-age=15`.

### 5.2 `GET /api/mobile/manager/orders/<order_id>`

Karta zamówienia. `no-store`. Zawiera wszystkie pola zamówienia z §5.1 (bez skróconych `pozycje`) oraz:

```json
{
  "zamowienie": {
    "order_id": 812,
    "numer": "25_01234",
    "notatki": "Klient prosi o telefon przed dostawą.",
    "zalaczniki": [
      {"nazwa": "projekt_blatu.pdf", "url": "https://..."}
    ],
    "na_stanowiskach": [
      {"stanowisko": "formatting", "nazwa": "Formatowanie", "gdzie": "stol", "unit_key": "o:812"},
      {"stanowisko": "edges", "nazwa": "Krawędzie", "gdzie": "odlozone", "unit_key": "p:5523",
       "powod_etykieta": "Brak materiału"}
    ],
    "pozycje": [
      {
        "product_id": 5521,
        "short_product_id": "25_01234_1",
        "nazwa": "Blat dąb lity 4 cm",
        "kolejnosc": "1/4",
        "specyfikacja": {
          "gatunek": "Dąb", "technologia": "Lity", "klasa": "A/B", "grubosc_cm": 4.0,
          "wykonczenie": "Olej naturalny", "krawedzie": "Zaokrąglenie R3 (Krawędź 1, Krawędź 3)",
          "ksztalt": "Prostokąt z wycięciem pod zlew"
        },
        "shape_svg": "<svg ...>",
        "edge_svg": "<svg ...>",
        "wymiary": {"dlugosc_cm": 240.0, "szerokosc_cm": 65.0, "grubosc_cm": 4.0},
        "sztuk": 1,
        "m3": 0.0624,
        "zrobione": {"cutting": 1, "gluing": 1, "formatting": 0, "edges": 0, "painting": 0, "packaging": 0},
        "trasa_stanowisk": ["assembly", "gluing", "formatting", "painting", "packaging"],
        "status": "czeka_na_formatowanie",
        "status_etykieta": "Czeka na formatowanie",
        "termin": "2026-10-24",
        "ranga": 1401,
        "dorobka": false,
        "oryginal_id": null,
        "notatki_produkcji": null
      }
    ]
  }
}
```

| Pole | Znaczenie |
|---|---|
| `zalaczniki` | lista (dziś najwyżej jeden plik). **Uwaga:** część linków z Base. (pole „Załącznik z wyceny CRM”) zwraca 403 z serwera plików Base. Appka ma wtedy pokazać „Plik niedostępny”, a nie pusty ekran |
| `na_stanowiskach` | gdzie zamówienie leży na stołach: `gdzie` = `stol` albo `odlozone`; `unit_key` służy do „Zdejmij ze stołu” (§7.4) |
| `shape_svg`, `edge_svg` | ten sam rysunek kształtu i krawędzi co na tabletach stanowisk; null, gdy brak |
| `zrobione` | sztuki zrobione na każdym stanowisku; klucze tylko dla stanowisk z `trasa_stanowisk` |
| `trasa_stanowisk` | przez które stanowiska pozycja idzie (ta sama reguła co oś czasu w webie). Technologia decyduje o pierwszym stanowisku: lity → `assembly`, mikrowczep → `cutting` |
| `dorobka`, `oryginal_id` | pozycja-doróbka i id pozycji, z której powstała |

**Błędy:** 404 `zamowienie_nieznane`.

### 5.3 `GET /api/mobile/manager/products/<product_id>/history`

`no-store`.

```json
{
  "product_id": 5521,
  "przeplyw": {
    "cutting":  {"zakonczono": "2026-10-16T10:12:44", "kto": "Tablet Wycinanie", "pracownicy": ["Adam K."]},
    "gluing":   {"zakonczono": "2026-10-17T13:02:10", "kto": "Tablet Sklejanie", "pracownicy": ["Bartek N."]}
  },
  "historia": [
    {"kiedy": "2026-10-17T13:02:10", "rodzaj": "status", "z": "czeka_na_sklejanie",
     "z_etykieta": "Czeka na sklejanie", "na": "czeka_na_formatowanie",
     "na_etykieta": "Czeka na formatowanie", "kto": "Bartek N.", "zrodlo": "mobile"},
    {"kiedy": "2026-10-17T12:40:01", "rodzaj": "praca", "stanowisko": "gluing", "zmiana": 1,
     "kto": "Bartek N.", "zrodlo": "mobile"}
  ]
}
```

`historia` jest posortowana od najnowszych. `rodzaj`: `status` (zmiana statusu), `praca` (sztuki na stanowisku,
`zmiana` może być ujemna przy cofnięciu), `priorytet`, `dorobka`, `logistyka`. Nieznane rodzaje appka pokazuje
ogólnie (`kiedy`, `kto` i `opis`, jeśli jest).

**Błędy:** 404 `pozycja_nieznana`.

---

## 6. `POST /api/mobile/manager/products/status`, czyli zmiana statusu

Ta sama operacja co „Zmień status” (hurt) w panelu webowym, z tymi samymi skutkami:

- pozycja przestawiona na inny status schodzi ze stołu stanowiska;
- pozycja cofnięta do produkcji unieważnia paczki, weryfikację i załadunek zamówienia;
- „Spakowane” na zamówieniu zweryfikowanym cofa weryfikację;
- kolejka priorytetów przelicza się po zapisie;
- tablety stanowisk dostają sygnał.

**Statusu do Base. ta zmiana nie wysyła** (tak samo jak web).

### Żądanie

```http
POST /api/mobile/manager/products/status
Authorization: Bearer <JWT>
X-App-Version: 1.10.0
X-Worker-Ids: 17
X-Operation-Id: 6f1c2b7e-0c1e-4b8e-9b55-2a3a3b7b9d10
Content-Type: application/json

{"product_ids": [5521, 5522], "status": "wstrzymane"}
```

| Pole | Wymagane | Uwagi |
|---|---|---|
| `product_ids` | tak | 1–500 identyfikatorów pozycji (`product_id`); powtórzenia serwer usuwa. Mogą być z różnych zamówień |
| `status` | tak | kod z §4.1 z kolumną „Kierownik może ustawić” = tak |

### Ciało 200 (także gdy część pozycji odmówiono)

```json
{
  "message": "Zmieniono status 2 pozycji.",
  "zmienione": 2,
  "odmowione": 0,
  "odmowy": [],
  "pozycje": [
    {"product_id": 5521, "order_id": 812, "status": "wstrzymane", "status_etykieta": "Wstrzymane"},
    {"product_id": 5522, "order_id": 812, "status": "wstrzymane", "status_etykieta": "Wstrzymane"}
  ],
  "zdjete_ze_stolow": ["formatting"],
  "nieznane": []
}
```

| Pole | Znaczenie |
|---|---|
| `zmienione` / `odmowione` | liczby pozycji |
| `odmowy[]` | zdania po polsku, po jednym na zamówienie, któremu serwer odmówił (np. zamówienie na trasie załadowanej albo w drodze — „najpierw Cofnij załadunek”) |
| `pozycje[]` | bieżący stan **wszystkich** przesłanych pozycji po zapisie, także odmówionych (z niezmienionym statusem). Appka podmienia wiersze bez ponownego GET |
| `zdjete_ze_stolow` | kody stanowisk, z których zeszły kafle |
| `nieznane` | przesłane identyfikatory, których nie ma w bazie (pozycja usunięta w międzyczasie); appka usuwa je z widoku. Gdy nieznane są **wszystkie**, odpowiedź to 404 `pozycje_nieznane` |

### Błędy

| Status | Ciało `error` | Kiedy | Zapamiętane pod `X-Operation-Id`? | Co robi appka |
|---|---|---|---|---|
| 400 | `missing_operation_id` | brak nagłówka | nie | błąd programisty |
| 400 | `dane_niepoprawne` | brak/zły `product_ids` (pusty, > 500, nie liczby) | nie | komunikat |
| 400 | `status_niedozwolony` + `dozwolone: [...]` | status spoza dozwolonych | nie | komunikat |
| 404 | `pozycje_nieznane` | żadnej z pozycji nie ma | nie | odśwież listę |
| 409 | `trasa_w_drodze` | **wszystkie** pozycje są w zamówieniach na trasie załadowanej albo w drodze; nic nie zapisano | nie | pokaż `message` |
| 500 | — | błąd serwera | nie | ponów z **tym samym** `X-Operation-Id` (§10) |

Pozycje anulowane można anulować także na trasie w drodze, bo Dostawa obsługuje zamówienie anulowane.

---

## 7. Stanowiska

### 7.1 `GET /api/mobile/manager/stations`

Przegląd wszystkich 7 stanowisk: nagłówki i liczniki, bez list kafli. ETag, `max-age=15`.

```json
{
  "stanowiska": [
    {
      "kod": "formatting",
      "nazwa": "Formatowanie",
      "tryb": "stol",
      "jednostka": "zamowienie",
      "ma_stol": true,
      "blad_priorytetow": false,
      "statystyki": {
        "oczekuje": 37, "ukonczono_dzis": 12, "m3_dzis": 1.8422,
        "na_stole": 3, "miejsca": 3, "odlozone": 1, "limit_odlozen": 3,
        "kolejka_dalej": 21, "widm": 0, "niekompletnych": 4
      },
      "obsada": [
        {"id": 3, "imie": "Adam", "nazwisko": "Kowalczyk", "inicjaly": "AK", "kolor": "#2E7D32",
         "od": "2026-10-19T06:02:11", "ostatnia_aktywnosc": "2026-10-19T09:38:40", "bezczynnosc_min": 3}
      ]
    }
  ],
  "suma": {"oczekuje": 210, "ukonczono_dzis": 64, "m3_dzis": 9.1201, "odlozone": 2},
  "wyliczono": "2026-10-19T09:41:07"
}
```

| Pole | Znaczenie |
|---|---|
| `tryb` | `stary` (stanowisko pracuje listą) albo `stol` (stół K miejsc). Stoły włącza admin w Konfiguracji |
| `jednostka` | `pozycja` (kafel = pozycja) albo `zamowienie` (kafel = zamówienie: Formatowanie, Pakowanie) |
| `ma_stol` | false tylko dla Lakierni (lista w grupach wykończenia, bez „Na stół”) |
| `blad_priorytetow` | `true`, gdy serwer nie zdołał policzyć stołu i kolejki tego stanowiska (awaria warstwy priorytetów; tak samo jak w zakładce Stanowiska w panelu). Wtedy odpowiedź jest zwykłym 200: są `oczekuje`, `ukonczono_dzis`, `m3_dzis` i `obsada`, a `tryb`, `jednostka` i pozostałe liczniki stołu (`na_stole`, `miejsca`, `odlozone`, `limit_odlozen`, `kolejka_dalej`, `widm`, `niekompletnych`) mają wartość `null`. Appka pokazuje liczniki dnia i krótką informację „stół i kolejka chwilowo niedostępne”, bez ekranu błędu, i odświeża przy następnym odpytaniu. Poza awarią zawsze `false` |
| `oczekuje` | pozycje w statusie stanowiska |
| `ukonczono_dzis`, `m3_dzis` | pozycje zakończone dziś na stanowisku i ich m³ |
| `na_stole` / `miejsca` | zajęte i wszystkie miejsca stołu |
| `kolejka_dalej` | ile kafli czeka w kolejce poza stołem |
| `widm` | wiersze stołu do zdjęcia (§7.2) |
| `niekompletnych` | tylko stanowiska zamówieniowe: zamówienia, których nie wszystkie pozycje doszły |
| `obsada` | kto ma teraz otwartą sesję na tym stanowisku (jak §7.5) |

### 7.2 `GET /api/mobile/manager/stations/<kod>`

Pełne stanowisko. Parametr `limit` (długość kolejki): domyślnie 50, najwyżej 500. `no-store`.

```json
{
  "kod": "formatting",
  "nazwa": "Formatowanie",
  "tryb": "stol",
  "jednostka": "zamowienie",
  "ma_stol": true,
  "blad_priorytetow": false,
  "statystyki": { "...": "jak w §7.1" },
  "obsada": [ "...jak w §7.1" ],
  "stol": [
    {
      "unit_key": "o:812",
      "order_id": 812,
      "numer": "25_01234",
      "gwiazdki": 2,
      "szczebel": {"id": 4, "rodzaj": "gwiazdki", "etykieta": "★★", "pozycja": 3},
      "termin": "2026-10-24",
      "pozycji": 4,
      "sposob_dostawy_ustawiony": true,
      "pobrano": "2026-10-19T07:15:02",
      "zrodlo": "kolejka",
      "wyslal": null,
      "wroci_przy_dopelnieniu": false
    }
  ],
  "odlozone": [
    {
      "unit_key": "o:799",
      "order_id": 799,
      "numer": "25_01198",
      "...": "pola kafla jak w stol",
      "powod": "brak_materialu",
      "powod_etykieta": "Brak materiału",
      "notatka": "czekamy na lamele",
      "odlozono": "2026-10-19T08:01:44",
      "pracownik": "Adam Kowalczyk",
      "pracownik_krotko": "Adam K."
    }
  ],
  "widma": [
    {"unit_key": "p:5401", "order_id": 790, "numer": "25_01170", "product_id": 5401, "short_id": "25_01170_2",
     "zrodlo": "kolejka", "pobrano": "2026-10-18T14:00:00", "odlozony": false,
     "opis": "pozycja już nie czeka na stanowisku"}
  ],
  "niekompletne": [
    {"order_id": 830, "numer": "25_01260", "na_stanowisku": 2, "pozycji": 3,
     "brakuje": [{"short_id": "25_01260_3", "stanowisko": "gluing"}]}
  ],
  "kolejka": {
    "lacznie": 21,
    "kafle": [
      {"order_id": 841, "numer": "25_01277", "gwiazdki": 0,
       "szczebel": {"id": 9, "rodzaj": "tag", "etykieta": "Po terminie", "pozycja": 1},
       "termin": "2026-10-17", "pozycji": 2, "sposob_dostawy_ustawiony": false}
    ]
  }
}
```

**Kafel pozycji** (stanowiska z `jednostka: "pozycja"`) ma zamiast `pozycji` i `sposob_dostawy_ustawiony` pola
`product_id`, `short_id`, `rozpoczete`, `dorobka`, `material` {gatunek, klasa, grubosc_cm}, `wymiary`
{dlugosc_cm, szerokosc_cm, grubosc_cm}. `unit_key` ma wtedy postać `p:<product_id>`.

| Pole | Znaczenie |
|---|---|
| `unit_key` | klucz kafla: `p:<id pozycji>` albo `o:<id zamówienia>`. Służy do „Zdejmij ze stołu” |
| `szczebel` | szczebel drabiny priorytetów, z którego kafel jest w kolejce: `{id, rodzaj, etykieta, pozycja}`. `rodzaj` to `gwiazdki`, `tag` (szczebel terminowy albo „Rozpoczęte” — który dokładnie, mówi `etykieta`) albo `trasa`. `pozycja` to miejsce szczebla na widocznej drabinie |
| `zrodlo` | skąd kafel na stole: `kolejka` (wziął system), `dorobka`, `biuro` (położył ktoś z biura albo kierownik), `start` (start stołów) |
| `wyslal` | kto położył kafel `biuro`: imię i nazwisko użytkownika CRM albo kierownika |
| `wroci_przy_dopelnieniu` | po zdjęciu kafel wróci na stół przy najbliższym dopełnieniu (zdjęcie byłoby pozorne). Appka może ostrzec przed „Zdejmij” |
| `widma` | wiersze stołu, którym nie odpowiada już kafel (pozycja poszła dalej, zmiana ustawień). Zajmują miejsce na stole, więc kierownik może je zdjąć |
| `niekompletne` | zamówienia, których część pozycji jest jeszcze na wcześniejszych stanowiskach. Pełna lista, bez przycinania do `limit` — licznik `niekompletnych` w statystykach zgadza się z jej długością |
| `kolejka.kafle` | kolejka poza stołem w kolejności pobierania (pierwszy = następny), najwyżej `limit` |

**Lakiernia** (`painting`) w przeglądzie §7.1: liczniki stołu (`na_stole`, `miejsca`, `odlozone`, `limit_odlozen`, `widm`, `niekompletnych`) są zerami, a `kolejka_dalej` równa się `oczekuje` — cała praca stoi na liście.

**Lakiernia** (`painting`) w §7.2: `ma_stol: false`, puste `stol`, `odlozone`, `widma`, `niekompletne`, a `kolejka.kafle`
to lista w kolejności tabletu Lakierni (grupy wykończenia). Każda pozycja: `product_id`, `short_id`, `order_id`,
`numer`, `gwiazdki`, `dorobka`, `termin`, `dni_do_terminu`, `grupa` (nazwa grupy wykończenia), `material`.

Odczyt **niczego nie zmienia**: nie dopełnia stołu (to robią tablety stanowisk).

**`blad_priorytetow`** (jak w §7.1): `true`, gdy serwer nie zdołał policzyć stołu i kolejki (awaria warstwy
priorytetów). Odpowiedź to nadal 200: `statystyki` mają liczniki dnia (`oczekuje`, `ukonczono_dzis`, `m3_dzis`),
a `stol`, `odlozone`, `widma`, `niekompletne` i `kolejka.kafle` są pustymi listami, `kolejka.lacznie` jest `null`
(`tryb`, `jednostka` i liczniki stołu w `statystyki` także `null`; Lakiernia traci tylko listę). Appka pokazuje liczniki i
informację zamiast ekranu błędu. Odpowiedzi zapisów §7.3 i §7.4 niosą `stanowisko` zawsze z `blad_priorytetow: false`:
awaria priorytetów w trakcie zapisu cofa cały zapis i kończy się błędem 500, nie połową odpowiedzi.

**Błędy:** 404 `stanowisko_nieznane`, 400 `dane_niepoprawne` (zły `limit`).

### 7.3 `POST /api/mobile/manager/stations/<kod>/desk`, czyli „Na stół”

Kładzie na stół kafle zamówienia, które jest **teraz** na tym stanowisku. Na stanowisku pozycyjnym idzie każda
pozycja zamówienia w statusie stanowiska, na zamówieniowym kafel zamówienia (także niekompletnego). Kafel
odłożony wraca na stół. Kafel już leżący zostaje bez zmian. Działa w trybie `stary` i `stol`. Kafel staje ponad
liczbą miejsc, ze źródłem `biuro`.

```http
POST /api/mobile/manager/stations/formatting/desk
X-Operation-Id: <UUID>
X-Worker-Ids: 17

{"order_id": 841}
```

**Ciało 200:**

```json
{
  "message": "Zamówienie 25_01277 jest na stole Formatowania.",
  "wynik": "wyslano",
  "wyslane": ["o:841"],
  "przywrocone": [],
  "juz_na_stole": [],
  "stanowisko": { "...": "pełne stanowisko jak §7.2, stan po zapisie" }
}
```

`wynik`: `wyslano` (coś doszło albo wróciło z odłożonych) albo `juz_na_stole` (nic do zrobienia).

| Status | `error` | Kiedy |
|---|---|---|
| 400 | `dane_niepoprawne` | brak `order_id` |
| 404 | `stanowisko_nieznane` | zły kod |
| 404 | `zamowienie_nieznane` | nie ma zamówienia |
| 409 | `brak_na_stanowisku` | zamówienie nie ma teraz pozycji na tym stanowisku |
| 409 | `stanowisko_bez_stolu` | Lakiernia |

Żaden z tych błędów nie jest zapamiętany pod `X-Operation-Id`.

### 7.4 `POST /api/mobile/manager/stations/<kod>/desk/remove`, czyli „Zdejmij ze stołu”

Usuwa kafel ze stołu albo z odłożonych (także widmo). Pozycja zostaje na stanowisku i kafel wraca do kolejki.

```json
{"unit_key": "o:812"}
```

**Ciało 200:** `{"message", "unit_key", "order_id", "product_id" (null dla kafla zamówienia), "odlozony": bool,
"stanowisko": {...stan po zapisie jak §7.2}}`.

| Status | `error` | Kiedy |
|---|---|---|
| 400 | `dane_niepoprawne` | zły `unit_key` |
| 404 | `stanowisko_nieznane` | zły kod |
| 404 | `brak_kafla` | kafla już nie ma na stole (ktoś zdjął wcześniej, pozycja poszła dalej) — appka odświeża stanowisko |
| 409 | `stanowisko_bez_stolu` | Lakiernia |

### 7.5 `GET /api/mobile/manager/workers/now`, czyli „Kto teraz pracuje”

`no-store`.

```json
{
  "stanowiska": [
    {"kod": "formatting", "nazwa": "Formatowanie", "osoby": [
      {"id": 3, "imie": "Adam", "nazwisko": "Kowalczyk", "inicjaly": "AK", "kolor": "#2E7D32",
       "od": "2026-10-19T06:02:11", "pierwsze_dzis": "2026-10-19T06:02:11",
       "ostatnia_aktywnosc": "2026-10-19T09:38:40", "bezczynnosc_min": 3}
    ]}
  ],
  "lacznie_osob": 14,
  "wyliczono": "2026-10-19T09:41:07"
}
```

Lista obejmuje wszystkie stanowiska w kolejności z §4.1, także te bez osób (`osoby: []`). Liczą się sesje
otwarte i z dzisiejszą datą pracy. `bezczynnosc_min` to minuty od ostatniej akcji produkcyjnej pracownika.

**`od` nie jest czasem pracy.** To początek BIEŻĄCEJ sesji pracownika na tym stanowisku, a sesja zaczyna się od nowa
przy każdym przełączeniu profilu na tablecie (zmierzone na produkcji: pracownik krążący między stanowiskami miał
w ciągu dnia kilkanaście sesji, część krótszych niż dwie minuty). Panel webowy świadomie go nie pokazuje. Appka nie
może go podpisywać jako „na stanowisku od 11:10” ani sugerować nim przepracowanych godzin; początek dnia pracy to
`pierwsze_dzis`, a „na bieżąco” mówi `bezczynnosc_min`.

---

## 8. Podgląd: trasy, trakownia, raporty

### 8.1 `GET /api/mobile/manager/routes`

Parametry: `status` (`robocza`, `zatwierdzona`, `zaladowana`, `w_trasie`, `wykonana`), `od`, `do`
(`RRRR-MM-DD`). Bez `od`: wszystkie aktywne oraz wykonane z ostatnich 30 dni. ETag, `max-age=15`.

```json
{
  "trasy": [
    {
      "id": 33,
      "nazwa": "Rzeszów czw.",
      "date_from": "2026-10-23",
      "date_to": "2026-10-23",
      "status": "zatwierdzona",
      "status_etykieta": "Zatwierdzona",
      "pojazd": {"nazwa": "Iveco", "rejestracja": "RZ 12345"},
      "kierowca": {"id": 21, "nazwa": "Piotr Nowak"},
      "notatka": null,
      "podsumowanie": {"przystanki": 7, "m3": 3.912, "waga_kg": 2350, "km": 312.4, "minuty": 410,
                       "przyblizony": false, "bez_lokalizacji": 0, "przekroczona_ladownosc": false},
      "postep": {"przystanki": 7, "zaladowane": 0, "dostarczone": 0, "niedostarczone": 0, "zdjete": 0},
      "zatwierdzona": "2026-10-18T15:20:00",
      "zaladowana": null,
      "wyjazd": null,
      "wykonana": null
    }
  ]
}
```

Kolejność: w trasie, załadowane, zatwierdzone, robocze, wykonane, a w każdej grupie według daty. Statusy:
`robocza` (planowana), `zatwierdzona`, `zaladowana`, `w_trasie`, `wykonana` (etykieta „Dostarczona”).

**Kilometry na liście mogą być nieaktualne.** Backend nigdy nie przelicza przebiegu przy odczycie, więc po zmianie
przystanków lista pokazuje ostatnio policzone `km` i `minuty`, dopóki ktokolwiek nie otworzy trasy w panelu webowym
(to on przelicza). Flagę nieaktualności ma dopiero szczegół trasy: `przebieg_nieaktualny` w §8.2.

Przy przybliżonym przebiegu (`przyblizony: true`, linie proste — brak klucza do usługi tras albo jej błąd) `km`
to suma odcinków w linii prostej, czyli liczba ZANIŻONA wobec jazdy drogami, a `minuty` są null. Tak samo pokazuje
to panel webowy. Appka ma wtedy opatrzyć kilometry dopiskiem „przebieg przybliżony”.

### 8.2 `GET /api/mobile/manager/routes/<route_id>`

Trasa z §8.1 oraz poniższe pola. ETag, `max-age=0`.

```json
{
  "trasa": {
    "...": "pola z §8.1",
    "magazyn": {"lat": 49.840438, "lng": 22.254053, "nazwa": "WoodPower — Bachórz 14N"},
    "przystanki": [
      {
        "pozycja": 1,
        "order_id": 812,
        "numer": "25_01234",
        "klient": "Jan Kowalski",
        "firma": "Kowalski Meble Sp. z o.o.",
        "miasto": "Rzeszów",
        "m3": 0.4122,
        "waga_kg": 290,
        "paczki": {"liczba": 2, "zaladowane": 0},
        "stan": "zweryfikowane",
        "stan_etykieta": "Zweryfikowane",
        "zostaje": null,
        "niedostarczone": null,
        "dostarczono": null,
        "geo": {"lat": 50.0412, "lng": 21.9991, "dokladnosc": "dokladna"}
      }
    ],
    "niedostarczone_zdjete": [
      {"order_id": 790, "numer": "25_01170", "klient": "Anna Wiśniewska", "miasto": "Krosno",
       "powod_etykieta": "Brak klienta", "notatka": null, "kiedy": "2026-10-16T13:10:00"}
    ],
    "przebieg": {"type": "LineString", "coordinates": [[22.254053, 49.840438], [21.9991, 50.0412]]},
    "przebieg_nieaktualny": false,
    "odcinki_proste": []
  }
}
```

| Pole | Znaczenie |
|---|---|
| `stan` | stan przystanku: `niespakowane`, `niezweryfikowane`, `zweryfikowane`, `zaladowane`, `dostarczone`, `niedostarczone`, `anulowane`, `problem` (etykieta w `stan_etykieta`). Zamówienie anulowane w całości zostaje na liście przystanków ze `stan: "anulowane"` i `pozycja: null`, i nie wchodzi do `podsumowanie` ani `postep` — tak samo jak w panelu |
| `zostaje` | `{powod, etykieta, notatka}`, gdy kierowca oznaczył „Zostaje” przy załadunku |
| `niedostarczone` | `{powod, etykieta, notatka, kiedy}` |
| `geo` | punkt na mapę albo null (adres nie znaleziony); `dokladnosc`: `dokladna` albo `przyblizona` |
| `przebieg` | GeoJSON `LineString` (współrzędne `[lng, lat]`) magazyn → przystanki → magazyn, albo null. Serwer go **nie przelicza** przy odczycie, tylko podaje ostatni zapisany |
| `przebieg_nieaktualny` | true, gdy przystanki zmieniły się od ostatniego przeliczenia; appka rysuje wtedy linie proste między punktami |
| `odcinki_proste` | odcinki, których serwis tras nie umiał poprowadzić drogami (lista par `[[lng,lat],[lng,lat]]`) |

**Podkładu mapy (kafelków) API nie dostarcza.** To decyzja appki (np. OpenStreetMap z atrybucją albo mapa bez
podkładu).

**Błędy:** 404 `trasa_nieznana`.

### 8.3 `GET /api/mobile/manager/sawmill/orders`

Parametry:
- `status`: `new`, `in_progress`, `completed` lub `settled`;
- `date_from`, `date_to`: data dostawy;
- `q`: numer zlecenia albo faktury;
- `only_deviation=1`: tylko z odchyłką.

Bez żadnego z filtrów `status`, `date_from`, `date_to`, `q` zwraca otwarte zlecenia oraz zlecenia z dostawą
w ostatnich 90 dniach. Sam `q` okna nie zawęża — szukanie po numerze ma trafiać też w zlecenia starsze.
Zły parametr (nieznany `status`, niepoprawna data) to 400 `dane_niepoprawne`, jak wszędzie w tym API.
ETag, `max-age=15`.

```json
{
  "zlecenia": [
    {
      "id": 57, "numer": "TRK/2026/057", "status": "completed", "status_etykieta": "Zakończone",
      "gatunek": "Dąb", "dostawca": "Tartak Leśny s.c.", "faktura": "FV 112/10/2026",
      "data_dostawy": "2026-10-14",
      "zadeklarowane_m3": 12.5, "zadeklarowane_klody": 40, "uzgodnione_m3": null,
      "zmierzone_m3": 11.874, "klody": 41,
      "roznica_m3": -0.626, "roznica_proc": -5.01, "odchylka": true, "roznica_w_toku": false,
      "notatki": null, "rozpoczeto": "2026-10-15T07:30:00", "zakonczono": "2026-10-15T14:10:00"
    }
  ],
  "podsumowanie": {"otwarte": 2, "klody_dzis": 18, "m3_dzis": 5.211, "do_rozliczenia": 3, "postep_proc": 64},
  "prog_odchylki_proc": 3.0
}
```

| Pole | Znaczenie |
|---|---|
| `status` | `new` Nowe, `in_progress` W trakcie, `completed` Zakończone, `settled` Rozliczone |
| `roznica_*` | zmierzone − zadeklarowane; null, dopóki zlecenie jest otwarte (`roznica_w_toku: true`) |
| `odchylka` | różnica % poza progiem `prog_odchylki_proc` |
| `podsumowanie` | licznik trakowni na dziś (kłody i m³ według czasu pomiaru) |

Ceny, wartości i notatek rozliczenia API nie zwraca.

### 8.4 `GET /api/mobile/manager/sawmill/orders/<id>`

`no-store`. Zawiera zlecenie z §8.3 oraz:

```json
{
  "zlecenie": { "...": "jak §8.3" },
  "srednie": {"m3": 0.2896, "srednica_cm": 38.2, "dlugosc_cm": 252.0},
  "klody": [
    {"id": 9001, "lp": 1, "srednica_cm": 41.0, "dlugosc_cm": 260.0, "m3": 0.3433,
     "zmierzono": "2026-10-15T07:31:12", "pracownik": {"id": 8, "nazwa": "Marek Z."}}
  ]
}
```

Kłody są w kolejności `lp`, bez skasowanych. **Błędy:** 404 `zlecenie_nieznane`.

### 8.5 `GET /api/mobile/manager/reports/stations`, czyli przerób stanowisk

Parametry raportów (§8.5–8.7): `start_date`, `end_date` (`RRRR-MM-DD`, obie granice włącznie, oba albo żaden).
Domyślnie dziś. Zakres najwyżej 92 dni, inaczej 400 `zakres_niepoprawny`. `no-store`.

```json
{
  "start_date": "2026-10-13",
  "end_date": "2026-10-19",
  "stanowiska": [
    {"kod": "formatting", "nazwa": "Formatowanie", "sztuki": 96, "m3": 14.2033, "pozycji": 71, "zamowien": 38,
     "cofniecia": 2, "kolejka_szt": 54, "kolejka_m3": 7.9011, "dni_zapasu": 2.6}
  ],
  "hala": {"sztuki": 512, "m3": 71.0432, "pozycji": 301, "zamowien": 96, "cofniecia": 5},
  "zakonczone": {"sztuki": 88, "m3": 12.9001},
  "trakownia": {"klody": 120, "m3": 33.904}
}
```

| Pole | Znaczenie |
|---|---|
| `sztuki`, `m3` | praca ludzi na stanowisku w zakresie, netto (po odjęciu cofnięć); bez automatycznych przejść |
| `pozycji`, `zamowien` | ile pozycji i zamówień dotknięto na stanowisku. **Nie sumuj zamówień między stanowiskami**: łączną liczbę unikalnych daje `hala.zamowien` |
| `cofniecia` | sztuki cofnięte w zakresie |
| `kolejka_szt`, `kolejka_m3`, `dni_zapasu` | stan **teraz** (niezależny od zakresu); `dni_zapasu` = kolejka / średni dzienny przerób z 14 dni roboczych, null bez danych. Stanowisko z pustą kolejką i bez przerobu ma `0.0`, nie null — to parytet z panelem; appka nie powinna pokazywać tego jako ostrzeżenia „0 dni zapasu” |
| `zakonczone` | Pakowanie, czyli to, co wyszło z produkcji |
| `trakownia` | surowiec zmierzony na trakowni; nie wchodzi do sumy `hala` |

### 8.6 `GET /api/mobile/manager/reports/workers`, czyli wydajność pracowników

Parametry jak §8.5 oraz opcjonalny `station` (kod stanowiska procesu).

```json
{
  "start_date": "2026-10-13",
  "end_date": "2026-10-19",
  "station": null,
  "pracownicy": [
    {"id": 3, "nazwa": "Adam Kowalczyk", "sztuki": 41.5, "m3": 6.012, "godziny": 37.8, "tempo_m3_h": 0.159,
     "stanowiska": ["formatting", "edges"], "otwarta_sesja": true,
     "wg_stanowisk": [{"stanowisko": "formatting", "sztuki": 30.0, "m3": 4.5}],
     "m2": {"olejowane": 12.5, "lakierowane": 3.0}}
  ],
  "nieprzypisane": {"sztuki": 12.0, "m3": 1.402},
  "podsumowanie": {"osoby": 14, "godziny": 402.5, "sztuki": 498.0, "m3": 69.64, "pokrycie_atrybucji_proc": 97.3}
}
```

| Pole | Znaczenie |
|---|---|
| `sztuki`, `m3` | udział pracownika: przy pracy zespołowej (N osób na jednym tablecie) każdy dostaje 1/N, stąd ułamki. Tu wyjątkowo **trzy** miejsca po przecinku, nie cztery — tak zaokrągla wspólny raport wydajności |
| `godziny` | z sesji pracownika (otwarta sesja liczona do teraz, najwyżej do limitu bezczynności i godziny nocnego zamknięcia) |
| `tempo_m3_h` | m³ na godzinę; null, gdy pracownik nie ma przypisanej pracy (null to nie zero). Mianownik to godziny sesji na stanowiskach PROCESU — sesja na trakowni, Weryfikacji, Dostawie albo na tablecie kierownika nie zaniża tempa, choc wchodzi do `godziny` |
| `m2` | tylko pracownik z pracą na Lakierni: `{olejowane, lakierowane}` w metrach kwadratowych (właściwa jednostka tego stanowiska); brak klucza, gdy pracownik tam nie pracował |
| `nieprzypisane` | praca bez wybranego profilu na tablecie |
| `pokrycie_atrybucji_proc` | jaki % pracy ma przypisanego pracownika |

Kolejność kluczy w obiektach (np. `stanowiska` w §8.7) nie jest częścią kontraktu — serwer sortuje je alfabetycznie.

**Uwaga do pokazania w appce:** dane są orientacyjne, bo profil na tablecie wybiera się bez PIN-u. Tempa nie
porównuj między stanowiskami, bo m³ na różnych stanowiskach to różna praca.

### 8.7 `GET /api/mobile/manager/reports/daily`, czyli przerób dzień po dniu

Parametry jak §8.5.

```json
{
  "start_date": "2026-10-13",
  "end_date": "2026-10-19",
  "dni": [
    {"data": "2026-10-13", "sztuki": 81, "m3": 11.2, "zakonczone_m3": 1.9,
     "stanowiska": {"cutting": {"sztuki": 12, "m3": 1.7}, "formatting": {"sztuki": 15, "m3": 2.2}}}
  ]
}
```

Lista ma każdy dzień zakresu, także dni bez pracy (zera). `stanowiska` zawiera klucze wszystkich 7 stanowisk.
`zakonczone_m3` to Pakowanie.

---

## 9. Odświeżanie i sygnały

**Realtime:** `GET /api/mobile/realtime-token` dla tabletu kierownika zwraca kanały `station:cutting` …
`station:packaging` (7). Sygnał `{"kind": "station", "station": "<kod>"}` przychodzi po każdej zmianie stołu lub
kolejki stanowiska (ZAKOŃCZ, odłożenie, zmiana statusu, „Na stół” i inne). Sygnał nie niesie danych. Appka po
nim pobiera:

- `GET /manager/stations` (przegląd), z opóźnieniem zbiorczym ok. 2 s, bo sygnały przychodzą seriami;
- `GET /manager/stations/<kod>`, jeśli ten ekran jest otwarty.

**Bez realtime** (token 503 albo połączenie zerwane) albo jako siatka bezpieczeństwa:

| Ekran | Rytm odpytywania |
|---|---|
| Przegląd stanowisk | 30 s |
| Otwarte stanowisko | 15 s |
| Kto teraz pracuje | 60 s |
| Lista zamówień | przy wejściu i przeciągnięciu w dół (ETag, 304 kosztuje mało) |
| Trasy, trakownia | przy wejściu i co 60 s na otwartym ekranie |
| Raporty | tylko na żądanie |

Ekran w tle (appka zminimalizowana) nie odpytuje.

---

## 10. Zapisy, ponawianie i brak sieci

Zapisy kierownika dotyczą **bieżącego** stanu hali, dlatego appka **nie** wkłada ich do kolejki offline na później.

1. Każdy zapis (status, „Na stół”, „Zdejmij”) dostaje nowy `X-Operation-Id` (UUID) w chwili kliknięcia.
2. Brak odpowiedzi (timeout, zerwane połączenie) albo 5xx: appka ponawia **z tym samym** `X-Operation-Id` do 3 razy
   w ciągu ok. 30 s. Serwer, który już wykonał operację, odda tę samą odpowiedź, więc operacja nie wykona się dwa
   razy.
3. Po trzech nieudanych próbach appka pokazuje „Nie udało się — sprawdź połączenie” i odświeża ekran. Kliknięcie
   jeszcze raz to **nowa** operacja z nowym `X-Operation-Id`.
4. Odpowiedzi 4xx są decyzją serwera na bieżącym stanie. Appka pokazuje `message` i odświeża dane, bez ponawiania.
   Serwer nie zapamiętuje ich pod `X-Operation-Id`, więc ponowienie z tym samym identyfikatorem i tak dałoby nową
   decyzję na nowym stanie.

Limit czasu żądania w appce: zapis 20 s, odczyt 15 s.

---

## 11. Czego to API nigdy nie zwróci

- Kwot: cen, wartości netto pozycji i zamówień, ceny za m³ i wartości trakowni, kosztu wysyłki.
- E-maila, telefonu ani ulicy klienta (trasy mają punkt na mapie i miasto).
- Notatek rozliczenia trakowni.
- Etykiet przewozowych.

---

## 12. Zgodność i kolejność wydania

- Backend i appkę można wydać w dowolnej kolejności:
  - **appka przed backendem:** rejestracja na `manager` się nie uda (kod nieznany), a `/manager/*` zwróci 404. Appka
    ma wtedy pokazać „Tryb kierownika nie jest jeszcze dostępny na serwerze”;
  - **backend przed appką:** stare tablety dostają w katalogu pracowników nowe pole `is_manager` i mają je
    ignorować. Katalog pobiorą raz od nowa (nowy ETag).
- Przed pierwszym użyciem admin zaznacza pracownikowi „Kierownik hali” (zakładka Pracownicy) i zatwierdza tablet w
  zakładce „Urządzenia mobilne”.

---

## 13. Scenariusze do sprawdzenia na urządzeniu

1. Rejestracja tabletu jako `manager` → prośba → zatwierdzenie w panelu → token.
2. Wybór profilu bez `is_manager` → profil wyszarzony (albo, gdy appka go przepuści, 403 `not_a_manager` z
   komunikatem).
3. Lista bieżących: liczby w `statystyki` zgadzają się z zakładką Produkty w webie (ten sam filtr).
4. Archiwum z zakresem dat → `zakonczono` w zakresie, średni czas realizacji.
5. Wyszukanie zamówienia po numerze Base. z `view=all`.
6. Karta zamówienia: rysunek kształtu, załącznik (także „Plik niedostępny” dla 403 z Base.), „na stanowiskach”.
7. Zmiana statusu jednej pozycji na „Wstrzymane” → kafel znika ze stołu stanowiska (sygnał, odświeżenie) i
   zmiana widać w historii pozycji z nazwiskiem kierownika.
8. Zmiana statusu pozycji zamówienia na trasie w drodze → 409 `trasa_w_drodze` z komunikatem.
9. Zerwanie sieci w trakcie zmiany statusu → ponowienie z tym samym `X-Operation-Id` → jedna zmiana w historii.
10. „Na stół” zamówienia z kolejki Formatowania → kafel na stole ze źródłem `biuro` i nazwiskiem kierownika, tablet
    Formatowania pokazuje go po sygnale.
11. „Zdejmij ze stołu” kafla z `wroci_przy_dopelnieniu: true` → ostrzeżenie w appce.
12. „Na stół” na Lakierni → przycisku nie ma (`ma_stol: false`).
13. Trasa w trasie: przystanki z pinezkami, przebieg, postęp dostarczeń.
14. Trakownia: zlecenie zakończone z odchyłką → różnica m³ i %, bez kwot.
15. Raporty: dziś, ostatnie 7 dni, zakres > 92 dni → 400 z komunikatem.
16. Wyłączony realtime (503) → przegląd odświeża się co 30 s.

---

## 14. Czego ten dokument nie rozstrzyga

- Wyglądu, nawigacji i kolejności ekranów (sesja appki).
- Mapy: podkładu, klastrów pinezek, stylu przebiegu.
- Jak appka grupuje zaznaczanie wielu pozycji do zmiany statusu (API przyjmuje dowolny zbiór do 500).
