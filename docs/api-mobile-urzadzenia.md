# API mobilne — dostęp urządzeń po zatwierdzeniu (appka 1.9.0)

## 0. Do kogo i na czym stoi ten dokument

Referencja różnicowa dla aplikacji Android (`woodpower_prod_app` / `crm_prod_app` — ta sama appka). Opisuje, co
zmienia się w rejestracji i uwierzytelnianiu urządzeń, i jak appka 1.9.0 ma z tym pracować. Sesja appki pracuje
wyłącznie z tego dokumentu; projekt strony CRM:
`docs/superpowers/specs/2026-10-12-urzadzenia-mobilne-zatwierdzanie-design.md`.

**Stan dokumentu:** po implementacji CRM (gałąź `feature/urzadzenia-zatwierdzanie` @ `ab187c7f`, jeszcze niewdrożona na
`main`). Kształty odpowiedzi z sekcji 3, 6 i 7 sprawdzono z kodem i testami (`tests/test_urzadzenia_*.py`) — zgadzają
się 1:1 i pozostają wiążące dla obu stron. Sekcje 4a i 4b opisują zachowania appki wynikające z kodu 1.8.2
(`AuthManager.clear()`, `SyncClassifier`) — to ustalenia po stronie appki, nie nowe końcówki.

Gdzie to stoi w kodzie CRM:

- `POST /api/mobile/register` — `modules/production/routers/mobile_api.py:202` (`register`; cienka nakładka, 500
  `registration_failed` przy nieoczekiwanym wyjątku). Logika, walidacja i maszyna stanów:
  `modules/production/services/device_access_service.py:121` (`zarejestruj_albo_popros`).
- Normalizacja MAC (`AA:BB:CC:DD:EE:FF`, odrzucanie atrap) — `device_access_service.py:45` (`normalizuj_mac`); MAC
  zgłoszony przez urządzenie i `mac_conflict` — `:82` (`zapisz_zgloszony_mac`); zmiana statusu urządzenia
  (jedyne miejsce) — `:60` (`ustaw_status`).
- Uwierzytelnianie — `modules/production/services/mobile_api_service.py:197` (`validate_token`) i `:186`
  (`BladTokenu` z polem `reason`); odpowiedź 401 składa `:407` (`require_device_token`).
- Heartbeat — `mobile_api.py:1676` (`device_heartbeat`, MAC przez `normalizuj_mac` i `zapisz_zgloszony_mac`).

---

## 1. Najważniejsze w pięciu zdaniach

1. **Nowe urządzenie nie dostaje tokenu od razu.** `register` z nieznanym `device_id` zakłada prośbę i odpowiada
   **202 `pending`**; token wydaje dopiero po zatwierdzeniu przez admina w zakładce „Urządzenia mobilne”.
2. **Appka wysyła MAC** (`mac_address`, z `DevicePolicyManager.getWifiMacAddress()`) i model (`device_model`) w
   `register` oraz MAC w heartbeacie — admin porównuje MAC z ekranem urządzenia.
3. **Odpytywanie = ponawianie `register`** z tym samym body co `retry_after_s` sekund — bez nowych końcówek.
4. **Zablokowane urządzenie dostaje 403 `device_blocked` z `register` i 401 z `reason: "blocked"` z każdej innej
   końcówki;** `register` nigdy nie odblokowuje.
5. **Zatwierdzone urządzenie działa jak dziś:** zmiana stanowiska i cicha naprawa po 401 przez `register` dostają 200
   z tokenem; 401 ma nowe pole maszynowe `reason`, proza w `detail` się nie zmienia.

## 2. MAC urządzenia

- Odczyt: `DevicePolicyManager.getWifiMacAddress(adminComponent)` (appka jest device-ownerem na wszystkich
  urządzeniach — tablety, telefony Weryfikacji i kierowców). `WifiInfo.getMacAddress()` **nie** — zwraca atrapę
  `02:00:00:00:00:00`.
- `null` = Wi-Fi nigdy nie było włączone (albo urządzenie nie ma Wi-Fi). Appka **nie wysyła prośby**; pokazuje:
  „Włącz Wi-Fi raz, żeby odczytać adres urządzenia” i przycisk „Sprawdź ponownie”.
- Format wysyłany: dowolny z `AA:BB:CC:DD:EE:FF`, `aa-bb-cc-dd-ee-ff`, `aabbccddeeff` — serwer normalizuje do
  `AA:BB:CC:DD:EE:FF` i taką postać oddaje. Appka **pokazuje** MAC zawsze w postaci `AA:BB:CC:DD:EE:FF` (tak samo
  wygląda w panelu).
- Serwer odrzuca: nie-12 cyfr hex, `02:00:00:00:00:00`, `00:00:00:00:00:00` → 400 `mac_invalid`.

## 3. `POST /api/mobile/register`

Bez JWT (jak dziś). Nagłówek `X-App-Version` jak dziś (panel pokazuje wersję przy prośbie).

### 3.1 Body

```json
{
  "device_id": "3f6c1a1e-9c2b-4d7e-8f00-1b2c3d4e5f60",
  "device_name": "Pakowanie 1",
  "station_code": "packaging",
  "mac_address": "A4:50:46:12:34:56",
  "device_model": "BAH2-W19"
}
```

| Pole | Wymagane | Uwagi |
|---|---|---|
| `device_id` | tak | ≤ 64 znaki, jak dziś |
| `station_code` | tak | jak dziś (`resolve_station_code`, w tym alias `finishing`) |
| `device_name` | nie | ≤ 128 znaków; dla **zatwierdzonego** urządzenia serwer go **ignoruje** (nazwę nadaje admin) |
| `mac_address` | tak dla nowego / oczekującego `device_id` | dla zatwierdzonego opcjonalny (stara appka go nie ma) |
| `device_model` | nie | `Build.MODEL`, ≤ 64 znaki |

Nie-tekstowy `device_id` albo `station_code` (np. `device_id: 123`) i body niebędące obiektem JSON dają 400
`missing_fields`; nie-tekstowe `device_name` i `device_model` są traktowane jak puste (bez błędu). `mac_address`
nie-tekstowy, złożony z samych spacji albo w złym formacie daje 400 `mac_invalid` (nigdy 500); tylko `null` i `""` są
traktowane jak brak MAC-u.

### 3.2 Odpowiedzi

| Kod | Body | Kiedy | Appka |
|---|---|---|---|
| 200 | `{"status": "approved", "token": "…", "device_id": "…", "station_code": "packaging", "device_name": "Pakowanie 1"}` | urządzenie zatwierdzone | zapisuje token i stanowisko **z odpowiedzi**; `device_name` to nazwa nadana przez admina — pokazuj ją zamiast wpisanej; `null` (wpis sprzed zmiany bez nazwy) = zostaje nazwa lokalna |
| 202 | `{"status": "pending", "device_id": "…", "mac_address": "A4:50:46:12:34:56", "retry_after_s": 5}` | prośba czeka na admina | ekran „Czekam na zatwierdzenie” (sekcja 4) |
| 403 | `{"error": "device_blocked", "retry_after_s": 30}` | odrzucona prośba albo urządzenie zablokowane | ekran blokady (sekcja 4) |
| 400 | `{"error": "missing_fields", "required": ["device_id", "station_code"]}` | jak dziś | błąd formularza |
| 400 | `{"error": "invalid_station_code", "allowed": [...]}` | jak dziś | błąd formularza |
| 400 | `{"error": "mac_required"}` | nowe / oczekujące `device_id` bez `mac_address` | nie powinno się zdarzyć w 1.9.0 (sekcja 2) — błąd techniczny |
| 400 | `{"error": "mac_invalid"}` | MAC w złym formacie / atrapa | błąd techniczny z MAC-iem w treści |
| 400 | `{"error": "field_too_long", "field": "device_name"}` | przekroczona długość | błąd formularza |
| 429 | `{"error": "too_many_pending", "retry_after_s": 60}` | na serwerze czeka już 20 próśb | „Za dużo oczekujących próśb — poproś administratora o porządek”; ponów po `retry_after_s` |
| 500 | `{"error": "registration_failed"}` | błąd serwera | ponów później |

Zatwierdzone urządzenie dostaje 200 **także bez** `mac_address` (zgodność z 1.8.2). 1.9.0 wysyła MAC zawsze.

## 4. Ekrany oczekiwania i blokady

**„Czekam na zatwierdzenie”** (po 202):

- Pokazuje: **MAC dużą czcionką o stałej szerokości**, nazwę, stanowisko, napis „Pokaż ten ekran administratorowi —
  zatwierdzi urządzenie w CRM, zakładka «Urządzenia mobilne»”.
- Ponawia `register` z **tym samym body** co `retry_after_s` (5 s), dopóki ekran jest na wierzchu — po wyjściu appki
  w tło (`ON_PAUSE`) przerywa odpytywanie i wznawia je po powrocie; przy błędach sieci i 5xx nie częściej niż
  `retry_after_s`, a po kilku kolejnych porażkach rzadziej (np. do 30 s). Każde ponowienie odświeża prośbę na
  serwerze (prośba nieodświeżana przez 7 dni znika; kolejne `register` zakłada ją wtedy od nowa).
- 200 → zapis tokenu, wejście do pracy (dalej jak po dzisiejszej rejestracji). 403 → ekran blokady. 429 / 5xx /
  brak sieci → dalej czeka, ponawia.
- Przycisk „Wróć” → formularz rejestracji; ponowne wysłanie aktualizuje tę samą prośbę (ten sam `device_id`).

**„Urządzenie zablokowane”** (po 403 z `register` albo 401 `reason: "blocked"`):

- Pokazuje MAC i nazwę, napis „Urządzenie zablokowane — zgłoś się do administratora”.
- Ponawia `register` co `retry_after_s` (30 s). Po odblokowaniu przez admina dostaje 200 i wraca do pracy samo.

**Bramka aktualizacji** (`AppUpdateGate`) nie może zasłaniać tych ekranów: urządzenie bez tokenu nie pobierze APK
(`/app/apk` wymaga JWT, a JWT dostaje tylko zatwierdzone) — ta sama pułapka co z niezarejestrowanym tabletem.
`/app/version` jest publiczne i działa bez zmian.

## 4a. „Wyrejestruj” i czyszczenie danych appki

- `AuthManager.clear()` (przycisk „Wyrejestruj”) kasuje tylko JWT i zachowuje `device_id`. Serwer **nie** dowiaduje się
  o wyrejestrowaniu: wiersz urządzenia zostaje `zatwierdzone`, więc kolejny `register` z tym samym `device_id` i
  `station_code` dostaje od razu **200 z tokenem — bez ponownej akceptacji admina**. To zamierzone: dostęp odbiera
  wyłącznie blokada w panelu, a „Wyrejestruj” służy zmianie stanowiska/serwisowi.
- Wyczyszczenie danych appki (Clear Data) albo reinstalacja generuje nowe `device_id`: `register` zakłada nową
  prośbę, a panel pokazuje „to samo urządzenie co «…»” (ten sam MAC); zatwierdzenie blokuje stary wpis (scenariusz 7).
- Nazwa nadana przez admina dociera do appki wyłącznie w odpowiedzi 200 z `register`; zmiana nazwy w panelu jest
  widoczna na urządzeniu dopiero przy następnym `register` (appka może do tego czasu pokazywać nazwę lokalną).

## 4b. Kolejka offline i sesje pracowników przy blokadzie

- 401 (w tym `reason: "blocked"`) klasyfikator kolejki (`SyncClassifier`/`StationActionClassifier`) traktuje jako
  `Transient` + `breakChain`: wpisy **zostają w kolejce** i czekają. Dla blokady zostaje tak samo — **żaden wpis kolejki
  nie jest kasowany ani oznaczany jako odrzucony** z powodu `blocked`; `SyncWorker` wstrzymuje drenowanie, dopóki nie
  ma ważnego tokenu (jak dziś po `clear()`).
- Po odblokowaniu `register` zwraca 200 z nowym tokenem (blokada podbiła wersję tokenów), a kolejka rusza z tymi samymi
  `operation_id`. Stanowisko urządzenia po stronie serwera się nie zmienia, więc wpisy nie dostają 403
  `station_mismatch`.
- Ekran blokady nie zamyka sesji pracownika na siłę; dalsze zachowanie sesji jak przy dzisiejszym 401.

## 5. Zmiana stanowiska i cicha naprawa — bez zmian

- `StationSwitcher` (`register` tym samym `device_id`, nowe `station_code`) i `DeviceReRegistrar` (po 401
  `expired` / `token_revoked`) działają jak dziś: zatwierdzone urządzenie dostaje 200 z tokenem.
- Różnica: `device_name` z żądania jest ignorowane — w odpowiedzi przychodzi nazwa z serwera.
- Gdyby w trakcie takiego `register` przyszło 403 `device_blocked` → ekran blokady (nie formularz rejestracji).

## 6. Heartbeat — `POST /api/mobile/devices/heartbeat`

Nowe opcjonalne pole:

```json
{ "battery_pct": 81, "battery_charging": true, "temperature_c": 31.5,
  "app_version_code": 47, "app_version_name": "1.9.0", "ip_address": "…",
  "mac_address": "A4:50:46:12:34:56" }
```

- Tak urządzenia zarejestrowane przed 1.9.0 przekazują MAC (do nich `register` z MAC-iem już nie przyjdzie).
- Zły albo brakujący MAC **nie** zmienia odpowiedzi (dalej 204). Inny MAC niż zapisany nie blokuje — panel pokazuje
  adminowi „MAC się zmienił”.

## 7. 401 z polem `reason`

Każde 401 `invalid_token` dostaje pole maszynowe; `detail` zostaje słowo w słowo jak dziś (1.8.2 na nim polega):

```json
{ "error": "invalid_token", "detail": "Token wygasł", "reason": "expired" }
```

| `reason` | `detail` | 1.9.0 robi |
|---|---|---|
| `expired` | `Token wygasł` | cicha re-rejestracja (`register`) |
| `token_revoked` | `Token unieważniony (token_version mismatch)` | cicha re-rejestracja |
| `blocked` | `Urządzenie zablokowane` | ekran blokady (sekcja 4) |
| `unknown_device` | `Urządzenie nieznane` | ekran serwisowy (jak dziś) |
| `invalid` | `Token nieprawidłowy: …` / `Token bez device_id` | ekran serwisowy (jak dziś) |
| brak pola | — | stara logika na `detail` (`decideTokenRecovery`) — siatka na wypadek starego backendu |

Brak nagłówka `Authorization: Bearer …` to nadal 401 `{"error": "missing_token"}` — **bez** `reason` i `detail`
(jak dziś; appka traktuje to jak brak rejestracji). `reason` dotyczy każdej końcówki za `require_device_token`:
stanowiska, Weryfikacja, Dostawa, Trakownia, `realtime-token`, `/app/apk`. Nie dotyczy `register` i `/app/version`
(bez JWT).

Kolejność po stronie serwera: blokada jest sprawdzana **przed** `token_version`, więc zablokowane urządzenie dostaje
`blocked`, a nie zaproszenie do re-rejestracji.

403 `ip_not_allowed` znika z API (whitelista IP usunięta).

## 8. Zgodność i kolejność wydania

- **Backend wchodzi pierwszy.** Po jego wdrożeniu 1.8.2 działa bez zmian (wszystkie dotychczasowe urządzenia są
  zatwierdzone z automatu, a ich tokeny **zostają ważne** — wdrożenie nie wymusza ponownej rejestracji i nie podbija
  wersji tokenów). Nowego urządzenia na 1.8.2 nie da się już zarejestrować (400 `mac_required`).
- **Urządzenia nieaktywne sprzed wdrożenia** (zablokowane ręcznie wcześniej) stają się `zablokowane` — 1.9.0 pokaże im
  ekran blokady zamiast formularza rejestracji.
- **1.9.0 ze starym backendem** (gdyby backend trzeba było cofnąć): stary `register` ignoruje nowe pola i odpowiada
  200 jak dziś (bez `status` i `device_name` — appka musi to znieść: brak `status` przy 200 z tokenem = zatwierdzone,
  brak `device_name` = zostaje lokalna), stary heartbeat ignoruje `mac_address`, 401 nie ma `reason` (siatka z
  sekcji 7).
- Po aktywacji 1.9.0 admin, gdy wszystkie urządzenia mają MAC, blokuje w panelu wpisy bez MAC-u — urządzenie, które
  nie zaktualizuje się do 1.9.0, straci wtedy dostęp.

## 9. Scenariusze do sprawdzenia na urządzeniu

1. Czyste dane appki → formularz → „Wyślij prośbę” → ekran oczekiwania z MAC-iem → zatwierdzenie w panelu → wejście do
   pracy w ≤ 5 s, nazwa z panelu widoczna w appce.
2. Odrzucenie prośby → ekran blokady; „Zatwierdź” odrzuconej w panelu → appka wraca sama w ≤ 30 s.
3. Zablokowanie działającego urządzenia → najbliższe żądanie: ekran blokady (nie formularz, nie cicha
   re-rejestracja) → odblokowanie → powrót sam w ≤ 30 s.
4. Zmiana stanowiska z bramki „Kto pracuje?” na zatwierdzonym urządzeniu → działa jak w 1.8.2.
5. Wi-Fi nigdy niewłączone (telefon kierowcy) → komunikat o Wi-Fi, prośba nie wychodzi; po włączeniu Wi-Fi →
   „Sprawdź ponownie” → prośba.
6. Urządzenie zarejestrowane na 1.8.2 po aktualizacji do 1.9.0 → pierwszy heartbeat → MAC widoczny w panelu.
7. Reinstalacja appki (nowe `device_id`, ten sam MAC) → panel pokazuje „to samo urządzenie co «…»”, zatwierdzenie
   blokuje stary wpis.
8. Brak sieci na ekranie oczekiwania → appka czeka i ponawia, nie wyrzuca do formularza.
9. „Wyrejestruj” na zatwierdzonym urządzeniu → formularz → ten sam `device_id` → 200 z tokenem od razu, bez akceptacji
   admina (sekcja 4a).
10. Zablokowanie urządzenia z niepustą kolejką offline → ekran blokady, wpisy kolejki nietknięte → odblokowanie →
    kolejka się opróżnia (sekcja 4b), nic nie trafia do „zablokowanych wpisów”.
11. Zmiana nazwy w panelu → widoczna na urządzeniu dopiero po następnym `register` (np. po zmianie stanowiska).
