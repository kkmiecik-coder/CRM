# API mobilne po podziale Wykańczania — co się zmieniło

Referencja różnicowa dla aplikacji Android (`crm_prod_app`). Opisuje **stan sprzed zmiany**
(na którym stoi aplikacja wydana dzisiaj), **stan po zmianie** i **jak wołać API dla dwóch
nowych stanowisk**.

Każde twierdzenie ma odnośnik do pliku i linii — sprawdzaj w kodzie, nie ufaj temu dokumentowi
na słowo. Odnośniki wskazują stan na gałęzi `feature/podzial-stanowiska-krawedzie`.

---

## Najważniejsze w trzech zdaniach

1. **Powierzchnia API się nie zmieniła.** Osiemnaście tras przed, osiemnaście po, żadna nie
   powstała, nie zniknęła i nie zmieniła ścieżki. Zmieniły się wyłącznie **wartości** kodu
   stanowiska.
2. Stanowisko `finishing` („Wykańczanie") **zniknęło** i zostało zastąpione przez `edges`
   („Krawędzie"). Osobno istnieje `painting` („Lakiernia"), które **wcześniej nie mogło przyjąć
   rejestracji tabletu**.
3. Przez okres przejściowy serwer **przyjmuje nadal `finishing`** i traktuje je jak `edges`.
   Alias zostanie zdjęty osobnym commitem po potwierdzeniu, że cała flota jest na nowym buildzie.

---

## 1. Kody stanowisk: przed i po

| | przed | po |
|---|---|---|
| kolejność stanowisk | `cutting, assembly, gluing, formatting, **finishing**, painting, packaging` | `cutting, assembly, gluing, formatting, **edges**, painting, packaging` |
| etykieta | `finishing` = „Wykańczanie" | `edges` = „Krawędzie" |
| Lakiernia w katalogu | była (`painting` = „Lakiernia") | bez zmian |
| **rejestracja tabletu** | `packaging, cutting, assembly, gluing, formatting, finishing, sawmill` — **bez `painting`** | dochodzą `edges` i `painting`, `finishing` zostaje na okres przejściowy |

Źródło: `modules/production/services/station_catalog.py`,
`modules/production/models.py` (`ProductionDevice.VALID_STATION_CODES`).

**To jest sedno zmiany dla aplikacji.** Lakiernia istniała wcześniej jako etykieta i jako status
produktu, ale tabletu nie dało się na niej zarejestrować — żyła jako zakładka wewnątrz tabletu
Wykańczania. Teraz jest samodzielnym stanowiskiem z własną rejestracją.

### Status produktu

W enumie statusów zmieniła się **dokładnie jedna wartość**:

```
czeka_na_wykanczanie   →   czeka_na_krawedzie
```

`czeka_na_lakiernie` istniało wcześniej i jest nietknięte. Pozostałe dziesięć wartości bez zmian.

**Alias nie działa w domenie statusów** — tylko w domenie kodów stanowisk. Nie ma niczego, co
zamieniłoby przychodzące `czeka_na_wykanczanie` na `czeka_na_krawedzie`. Stara wartość została
zdjęta z enuma i żyje już wyłącznie jako tekst w historii.

---

## 2. Alias okresu przejściowego

Serwer przyjmuje `finishing` wszędzie tam, gdzie kod stanowiska przychodzi **z żądania** —
w segmencie ścieżki i w ciele. Rozwija go na kod kanoniczny **przed** jakąkolwiek logiką.

Konsekwencje, o których trzeba wiedzieć:

- **Odpowiedzi 200 zawsze niosą kod kanoniczny.** Wyślij `finishing`, dostaniesz `edges`.
  To naturalne miejsce, żeby aplikacja „nauczyła się" nowego kodu.
- **Ciało błędu 403 `station_mismatch` niesie kod surowy**, prosto z wiersza urządzenia, bez
  rozwinięcia (`modules/production/routers/mobile_api.py:96, :241, :573, :639`). Nie bierz
  `device_station` z odpowiedzi 403 jako źródła prawdy o własnym stanowisku i nie zapisuj go
  u siebie.
- **`/stations/finishing/orders` i `/stations/edges/orders` oddają identyczny ETag**, bo alias
  rozwija się przed zbudowaniem klucza (`mobile_api.py:233 → :267`). Nie zakładaj, że zmiana
  kodu w adresie sama unieważni cache — z punktu widzenia serwera to ta sama kolejka.
- **Telemetria jest jedynym miejscem, gdzie alias nie ratuje.** Kody spoza listy stanowisk
  z tabletami są odrzucane po cichu, bez rozwinięcia aliasu
  (`modules/production/services/mobile_api_service.py:258-261, :306-307`).

---

## 3. Rejestracja urządzenia

`POST /api/mobile/register`

- Pole `station_code` w ciele jest **wymagane**; puste daje 400 `missing_fields`
  (`mobile_api.py:183-187`).
- Endpoint **nadpisuje** kod stanowiska w wierszu urządzenia tym, co przyszło
  (`mobile_api_service.py:727`). Jest **echem tego, co wysłała aplikacja**, a nie źródłem prawdy
  o tym, jakim stanowiskiem tablet jest. Nie ma ścieżki „przypomnij mi, czym jestem".
- Jest idempotentny po `device_id`: ponowna rejestracja aktualizuje wiersz i nie tworzy drugiego.
- **Nie podbija** wersji tokenu.

Tablet Lakierni rejestruje się jako `painting`. Przed tą zmianą taka rejestracja kończyła się
błędem walidacji.

---

## 4. Unieważnienie tokenu i odpowiedź 401

Tokeny mają długi czas życia, a kod stanowiska zapisany w tokenie **nie jest przez serwer
czytany** — tożsamość i stanowisko biorą się z bazy (`mobile_api_service.py:197-207`). Nie
używaj tej wartości do niczego, także do logów i ekranów serwisowych: w tokenie wydanym przed
zmianą będzie stary kod.

Przy wdrożeniu wersje tokenów zostaną podbite i **każdy tablet dostanie 401**:

```
401  {"error": "invalid_token", "detail": "..."}
```

Aplikacja ma to obsłużyć automatyczną ponowną rejestracją ze **składowanym** `device_id`
i **bez kasowania kolejki offline**.

Trzy rzeczy, których kontrakt nie mówił, a które mają znaczenie:

1. **Ponów żądanie z tym samym `X-Operation-Id`.** Idempotencja kluczuje wyłącznie po tym
   nagłówku (`mobile_api_service.py:507, :522-535`). Nowy identyfikator przy ponowieniu znaczy
   drugie wykonanie tej samej pracy.
2. **401 to nie zawsze podbita wersja tokenu.** Ten sam kod i to samo pole `error` dostaniesz
   przy wygaśnięciu podpisu, nieznanym urządzeniu i przy urządzeniu **zablokowanym przez
   administratora** (`mobile_api_service.py:190-207`) — różnią się tylko polem `detail`.
   Bezwarunkowa automatyczna re-rejestracja **odblokuje urządzenie, które ktoś celowo
   zablokował**.
3. Odróżniaj te przypadki po `detail`, zanim się przerejestrujesz.

---

## 5. Która trasa produktu dokąd prowadzi

Po formatowaniu produkt idzie jedną z trzech dróg:

| produkt | trasa |
|---|---|
| surowy | pomija Krawędzie i Lakiernię |
| tylko olejowany / lakierowany | prosto na **Lakiernię** |
| z obróbką krawędzi | na **Krawędzie**, a stamtąd na **Lakiernię**, jeśli ma też wykończenie powierzchni |

**Uwaga na pole `finish`.** Serwer buduje je **tylko dla produktów niesurowych**
(`mobile_api_service.py:1027-1034`). Dla produktu surowego całe pole jest `null` —
wartość `"surowe"` **nigdy nie pojawia się** w `finish.type`. Poprawny test:

```
finish == null                              → surowy
finish.type in ("olejowane","lakierowane")  → idzie na Lakiernię
```

Aplikacja sprawdzająca `finish.type == "surowe"` nie trafi nigdy, a w Kotlinie dostanie `null`
tam, gdzie spodziewa się stringa.

---

## 6. Rozdzielność stanowisk nie jest dziś egzekwowana

Do czasu zdjęcia okresu przejściowego serwer traktuje Krawędzie i Lakiernię jako jedną grupę
(`mobile_api_service.py:112-114, :139-141`). Tablet Lakierni pytający o kolejkę Krawędzi
**nie dostanie 403** — dostanie dane.

Rozdzielność jest więc na razie wyłącznie dyscypliną aplikacji. Błąd w konfiguracji wariantu
buildu nie ujawni się teraz, tylko przy zdejmowaniu okresu przejściowego.

---

## 7. Etykiety stanowisk nie są wystawiane przez API

Wśród wszystkich osiemnastu tras nie ma niczego w rodzaju `GET /stations`. Nazwy „Krawędzie"
i „Lakiernia" żyją wyłącznie po stronie serwera i panelu webowego.

Oznacza to, że **etykiety muszą być zaszyte w buildzie aplikacji** i nie da się ich zmienić bez
wydania nowego APK.

---

## 8. Błędy: co ponawiać, a czego nie

Kolejka offline jest miejscem, w którym zła decyzja oznacza **trwałą utratę odbitych sztuk**,
więc to jest najważniejsza sekcja tego dokumentu.

| kod | znaczenie | co robić |
|---|---|---|
| 400 `worker_ids_required` | brak nagłówka z obsadą przy włączonej bramce | wrócić na ekran wyboru profilu i **zachować akcję** |
| 422 `invalid_worker_ids` | nagłówek pusty albo ze śmieciami | to błąd trwały, ponawianie nie pomoże |
| 401 `invalid_token` | patrz sekcja 4 | przerejestrować się i ponowić z **tym samym** `X-Operation-Id` |
| 403 `station_mismatch` | urządzenie pyta o cudze stanowisko | nie ponawiać w pętli — sprawdzić własną rejestrację |
| 426 `app_version_too_old` | build poniżej progu | **nie jest zapamiętywany** — wpis zostaje w kolejce i wróci; pokazać człowiekowi, że tablet wymaga aktualizacji |

Lista kodów uznawanych za ponawialne siedzi w `mobile_api.py:118`. **Nie wszystkie 400 są
ponawialne** — obejmuje ona także błędy trwałe, więc nie traktuj całej klasy 400 jako
„spróbuj później".

### Sesje odpowiadają 200 także wtedy, gdy się nie udało

- `POST /sessions/start` **zawsze** zwraca 200, także gdy sesję przejął inny tablet. O tym, czy
  obsada jest twoja, mówi pole `superseded` w ciele, a **nie kod HTTP**
  (`mobile_api.py:1042-1051, :1095-1106`).
- `POST /sessions/end` zawsze zwraca 200 z niepustym ciałem JSON, również dla grupy już
  domkniętej albo nieznanej. Ciało musi się sparsować — 200 z pustym ciałem wywraca konwerter
  i wpis wraca do kolejki.

---

## 9. Dwie rzeczy, które trzeba sprawdzić po stronie serwera przed wdrożeniem

Nie są zadaniem aplikacji, ale wpływają na to, co człowiek zobaczy na tablecie:

1. **Ani Krawędzie, ani Lakiernia nie mają dziś prawa druku etykiet.** Lista stanowisk
   z drukarką jest konfiguracją runtime i nie zawiera nowych kodów; żądanie druku z kodu spoza
   listy kończy się błędem uprawnień.
2. **Podbicie minimalnej wspieranej wersji aplikacji zamyka pobieranie APK przez API.**
   `GET /app/apk` stoi za tym samym dekoratorem, który zwraca 426, i bramka odpala się **przed**
   wywołaniem handlera (`mobile_api.py:682-684`, `mobile_api_service.py:438-445`). Tablet poniżej
   progu dostanie 426 zamiast pliku, więc aktualizację trzeba wtedy wnieść na urządzenie ręcznie.

---

## 10. Czego ten dokument nie rozstrzyga

- Jak aplikacja ma rozłożyć dwa stanowiska w interfejsie — to decyzja po stronie `crm_prod_app`.
- Czy tablety Krawędzi i Lakierni mają być osobnymi wariantami buildu, czy jednym z wyborem
  przy rejestracji.
- Kolejności czynności w noc wdrożenia — to osobny dokument operacyjny, poza tym repozytorium.
